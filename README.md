# brewlog

A deliberately chaotic coffee-shop API used to explore self-hosted
[SigNoz](https://signoz.io) for the Agents of SigNoz hackathon (July 2026).
Full write-up: see [`blog-final.md`](blog-final.md) (published on Dev.to).
The two Foundry bugs found along the way: [SigNoz/foundry#161](https://github.com/SigNoz/foundry/issues/161).

Two FastAPI services from one file:

- **brewlog-api** (`:8001`) — `GET /menu`, `POST /order` (SQLite writes, then an
  httpx call to the brew machine, so every order is a 2-service trace)
- **brew-machine** (`:8002`) — `POST /brew/{drink}` with custom
  `grind_beans`/`extract` spans, per-drink latency (pour_over is a designed
  p99 outlier) and an 8% random "machine jammed" failure rate

Instrumented with OpenTelemetry auto-instrumentation (traces + metrics + logs
over OTLP), plus a custom counter (`brewlog.orders.total`), a histogram with
explicit sub-second bucket boundaries (`brewlog.brew.duration`), and stdlib
logging shipped as OTel logs for trace↔log correlation. There's also a
`POST /alert-hook` endpoint used as a SigNoz webhook alert channel, so alert
notifications loop back into SigNoz logs.

## Run it

Prereqs: a SigNoz instance listening for OTLP on `localhost:4317`
(`casting.yaml` here is the Foundry manifest I used — note that on a fresh
install the OTLP ports stay closed until the first admin user is registered;
see the blog post).

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/opentelemetry-bootstrap -a install

./run.sh            # starts both services under opentelemetry-instrument
./traffic.sh 300    # mixed traffic: valid orders, menu browsing, 400s, 502s
```

`screenshots.py` / `shoot_firing.py` capture the SigNoz UI headlessly with
Playwright (`SIGNOZ_EMAIL` and `SIGNOZ_PASSWORD` env vars required).
Screenshots from my run are in `shots/`.
