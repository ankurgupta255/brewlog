"""Brewlog — a tiny coffee-shop API used to demo SigNoz observability.

Endpoints:
  GET  /menu          -> reads drinks from sqlite (DB spans)
  POST /order         -> places an order, calls /brew internally (nested HTTP spans)
  GET  /brew/{drink}  -> simulates brewing: variable latency + random failures
  GET  /health        -> liveness

Run with auto-instrumentation (see run.sh); traces, metrics and logs are
exported over OTLP to SigNoz.
"""

import logging
import random
import sqlite3
import time
import uuid

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from opentelemetry import metrics, trace

logger = logging.getLogger("brewlog")
logging.basicConfig(level=logging.INFO)

tracer = trace.get_tracer("brewlog")
meter = metrics.get_meter("brewlog")

orders_total = meter.create_counter(
    "brewlog.orders.total", description="Orders placed, by drink and outcome"
)
# Default OTel buckets start at 5s — useless for sub-second brews (p99 would
# read ~4.95s for everything). Advise sub-second boundaries instead.
brew_duration = meter.create_histogram(
    "brewlog.brew.duration",
    unit="s",
    description="Time spent brewing",
    explicit_bucket_boundaries_advisory=[
        0.025, 0.05, 0.075, 0.1, 0.15, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0
    ],
)

DB_PATH = "brewlog.db"

# Base brew time in seconds per drink; pour_over is deliberately slow so it
# stands out in p99 latency charts.
DRINKS = {
    "espresso": 0.05,
    "americano": 0.08,
    "latte": 0.12,
    "cappuccino": 0.12,
    "pour_over": 0.9,
}

app = FastAPI(title="brewlog")


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.on_event("startup")
def init_db() -> None:
    conn = db()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS orders ("
        " id TEXT PRIMARY KEY, drink TEXT, status TEXT, created REAL)"
    )
    conn.execute("CREATE TABLE IF NOT EXISTS menu (drink TEXT PRIMARY KEY, price REAL)")
    for drink, base in DRINKS.items():
        conn.execute(
            "INSERT OR IGNORE INTO menu VALUES (?, ?)", (drink, round(2 + base * 4, 2))
        )
    conn.commit()
    conn.close()


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/alert-hook")
async def alert_hook(payload: dict):
    # SigNoz alert notifications land here; logging them ships them straight
    # back into SigNoz as logs.
    for alert in payload.get("alerts", []):
        logger.warning(
            "ALERT %s: %s", alert.get("status"),
            alert.get("annotations", {}).get("summary", "?"),
        )
    return {"received": True}


@app.get("/menu")
def menu():
    conn = db()
    rows = conn.execute("SELECT drink, price FROM menu ORDER BY price").fetchall()
    conn.close()
    logger.info("menu served, %d drinks", len(rows))
    return [dict(r) for r in rows]


class Order(BaseModel):
    drink: str


@app.post("/order")
def order(o: Order):
    if o.drink not in DRINKS:
        logger.warning("unknown drink ordered: %s", o.drink)
        raise HTTPException(status_code=400, detail=f"we don't serve '{o.drink}'")

    order_id = str(uuid.uuid4())[:8]
    span = trace.get_current_span()
    span.set_attribute("brewlog.order.id", order_id)
    span.set_attribute("brewlog.order.drink", o.drink)

    conn = db()
    conn.execute(
        "INSERT INTO orders VALUES (?, ?, 'queued', ?)", (order_id, o.drink, time.time())
    )
    conn.commit()

    logger.info("order %s accepted: %s", order_id, o.drink)

    # Call the brew service in-process over HTTP so the trace shows a
    # realistic client->server hop.
    try:
        resp = httpx.post(f"http://127.0.0.1:8002/brew/{o.drink}", timeout=10)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        conn.execute("UPDATE orders SET status='failed' WHERE id=?", (order_id,))
        conn.commit()
        conn.close()
        orders_total.add(1, {"drink": o.drink, "outcome": "failed"})
        logger.error("order %s failed while brewing: %s", order_id, exc)
        raise HTTPException(status_code=502, detail="the machine is angry") from exc

    conn.execute("UPDATE orders SET status='served' WHERE id=?", (order_id,))
    conn.commit()
    conn.close()
    orders_total.add(1, {"drink": o.drink, "outcome": "served"})
    logger.info("order %s served", order_id)
    return {"id": order_id, "drink": o.drink, "status": "served"}


@app.post("/brew/{drink}")
def brew(drink: str):
    base = DRINKS.get(drink)
    if base is None:
        raise HTTPException(status_code=404, detail="unknown drink")

    with tracer.start_as_current_span("grind_beans") as span:
        span.set_attribute("brewlog.grind.setting", "fine")
        time.sleep(random.uniform(0.01, 0.05))

    started = time.time()
    with tracer.start_as_current_span("extract") as span:
        # ~8% of brews fail: the machine jams.
        if random.random() < 0.08:
            logger.error("machine jammed while brewing %s", drink)
            span.set_attribute("brewlog.machine.jammed", True)
            raise HTTPException(status_code=500, detail="machine jammed")
        time.sleep(base * random.uniform(0.8, 1.6))

    brew_duration.record(time.time() - started, {"drink": drink})
    logger.info("brewed %s in %.2fs", drink, time.time() - started)
    return {"drink": drink, "status": "ready"}
