"""Capture SigNoz UI screenshots for the hackathon blog."""
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8080"
EMAIL = os.environ["SIGNOZ_EMAIL"]
PASSWORD = os.environ["SIGNOZ_PASSWORD"]
OUT = Path.home() / "signoz-demo" / "shots"
OUT.mkdir(exist_ok=True)

ERROR_TRACE = sys.argv[1] if len(sys.argv) > 1 else ""
SLOW_TRACE = sys.argv[2] if len(sys.argv) > 2 else ""

PAGES = [
    ("services", "/services", 12),
    ("trace-explorer", "/traces-explorer", 15),
    ("trace-error-detail", f"/trace/{ERROR_TRACE}", 15),
    ("trace-slow-pourover", f"/trace/{SLOW_TRACE}", 15),
    ("logs-explorer", "/logs/logs-explorer", 15),
    ("dashboards-list", "/dashboard", 10),
    ("alerts", "/alerts", 10),
]

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1720, "height": 1000})
    page.goto(BASE, wait_until="networkidle", timeout=60000)

    # Login if the form is shown
    if page.locator("#email").count() or page.locator("input[type='email']").count():
        email_sel = "#email" if page.locator("#email").count() else "input[type='email']"
        page.fill(email_sel, EMAIL)
        # some versions ask email first, then password on next step
        if not page.locator("input[type='password']").count():
            page.keyboard.press("Enter")
            page.wait_for_timeout(3000)
        page.fill("input[type='password']", PASSWORD)
        page.keyboard.press("Enter")
        page.wait_for_timeout(8000)
        print("logged in, url:", page.url)

    for name, path, wait in PAGES:
        try:
            page.goto(BASE + path, wait_until="networkidle", timeout=60000)
        except Exception as e:
            print(f"{name}: goto issue ({e}), continuing")
        page.wait_for_timeout(wait * 1000)
        page.screenshot(path=str(OUT / f"{name}.png"), full_page=False)
        print(f"captured {name} -> {page.url}")

    # dashboard detail: click through from the list
    try:
        page.goto(BASE + "/dashboard", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(5000)
        link = page.get_by_text("Brewlog Overview").first
        link.click()
        page.wait_for_timeout(15000)
        page.screenshot(path=str(OUT / "dashboard-brewlog.png"))
        print("captured dashboard-brewlog ->", page.url)
    except Exception as e:
        print("dashboard detail failed:", e)

    browser.close()
print("done")
