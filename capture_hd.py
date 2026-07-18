"""Recapture SigNoz UI screenshots at 2x device scale (retina/HD).

Usage:
  capture_hd.py main <error_trace_id> <slow_trace_id>
  capture_hd.py firing
Credentials via SIGNOZ_EMAIL / SIGNOZ_PASSWORD env vars.
"""
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8080"
OUT = Path.home() / "signoz-demo" / "shots" / "hd"
OUT.mkdir(parents=True, exist_ok=True)

mode = sys.argv[1]


def login(page):
    page.goto(BASE, wait_until="networkidle", timeout=60000)
    if page.locator("#email").count() or page.locator("input[type='email']").count():
        sel = "#email" if page.locator("#email").count() else "input[type='email']"
        page.fill(sel, os.environ["SIGNOZ_EMAIL"])
        if not page.locator("input[type='password']").count():
            page.keyboard.press("Enter")
            page.wait_for_timeout(3000)
        page.fill("input[type='password']", os.environ["SIGNOZ_PASSWORD"])
        page.keyboard.press("Enter")
        page.wait_for_timeout(8000)


def dismiss_popups(page):
    try:
        page.get_by_role("button", name="Okay").click(timeout=2000)
        page.wait_for_timeout(1000)
    except Exception:
        pass


def shoot(page, name, path, wait):
    try:
        page.goto(BASE + path, wait_until="networkidle", timeout=60000)
    except Exception as e:
        print(f"{name}: goto issue ({e}), continuing")
    page.wait_for_timeout(wait * 1000)
    dismiss_popups(page)
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=False)
    print("captured", name)


with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1720, "height": 1000}, device_scale_factor=2)
    login(page)

    if mode == "main":
        err, slow = sys.argv[2], sys.argv[3]
        shoot(page, "services", "/services", 12)
        shoot(page, "trace-explorer", "/traces-explorer", 15)
        shoot(page, "trace-error-detail", f"/trace/{err}", 15)
        shoot(page, "trace-slow-pourover", f"/trace/{slow}", 15)
        shoot(page, "logs-explorer", "/logs/logs-explorer", 15)
        shoot(page, "dashboards-list", "/dashboard", 10)
        shoot(page, "dashboard-brewlog",
              "/dashboard/019f74eb-f421-7b62-bcc6-5775f8b535c9", 18)
        shoot(page, "alerts-rules", "/alerts", 12)
    elif mode == "firing":
        page.goto(BASE + "/alerts", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(6000)
        try:
            page.get_by_text("Triggered Alerts").first.click()
            page.wait_for_timeout(8000)
        except Exception as e:
            print("tab click failed:", e)
        page.screenshot(path=str(OUT / "alerts-triggered.png"))
        print("captured alerts-triggered")
        shoot(page, "dashboard-brewlog",
              "/dashboard/019f74eb-f421-7b62-bcc6-5775f8b535c9", 18)
    b.close()
print("done")
