"""Screenshot the Triggered Alerts tab (and refreshed dashboard) — run when firing."""
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path.home() / "signoz-demo" / "shots"
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1720, "height": 1000})
    page.goto("http://localhost:8080", wait_until="networkidle", timeout=60000)
    if page.locator("#email").count() or page.locator("input[type='email']").count():
        sel = "#email" if page.locator("#email").count() else "input[type='email']"
        page.fill(sel, os.environ["SIGNOZ_EMAIL"])
        if not page.locator("input[type='password']").count():
            page.keyboard.press("Enter")
            page.wait_for_timeout(3000)
        page.fill("input[type='password']", os.environ["SIGNOZ_PASSWORD"])
        page.keyboard.press("Enter")
        page.wait_for_timeout(8000)
    page.goto("http://localhost:8080/alerts", wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(6000)
    try:
        page.get_by_text("Triggered Alerts").first.click()
        page.wait_for_timeout(8000)
    except Exception as e:
        print("tab click failed:", e)
    page.screenshot(path=str(OUT / "alerts-triggered.png"))
    print("captured alerts-triggered")
    page.goto(
        "http://localhost:8080/dashboard/019f74eb-f421-7b62-bcc6-5775f8b535c9",
        wait_until="networkidle", timeout=60000,
    )
    page.wait_for_timeout(18000)
    page.screenshot(path=str(OUT / "dashboard-brewlog-final.png"))
    print("captured dashboard-brewlog-final")
    b.close()
