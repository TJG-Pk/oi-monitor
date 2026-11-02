import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from playwright.sync_api import sync_playwright

TARGET_URL = os.environ["TARGET_URL"]
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# ปรับได้ผ่าน environment variable
WAIT_SECONDS = int(os.environ.get("WAIT_SECONDS", "12"))  # รอให้ Apps Script โหลดข้อมูลเสร็จ
VIEWPORT_WIDTH = int(os.environ.get("VIEWPORT_WIDTH", "1600"))
VIEWPORT_HEIGHT = int(os.environ.get("VIEWPORT_HEIGHT", "1200"))
TIMEZONE = os.environ.get("TIMEZONE", "Asia/Bangkok")

OUTPUT_FILE = "screenshot.png"


def take_screenshot() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
            device_scale_factor=1,
        )
        page.goto(TARGET_URL, wait_until="networkidle", timeout=90_000)
        page.wait_for_timeout(WAIT_SECONDS * 1000)
        page.screenshot(path=OUTPUT_FILE, full_page=True)
        browser.close()


def send_to_telegram() -> None:
    now = datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d %H:%M")
    caption = f"Intraday OI Monitor\n{now} ({TIMEZONE})"
    base = f"https://api.telegram.org/bot{BOT_TOKEN}"

    with open(OUTPUT_FILE, "rb") as f:
        resp = requests.post(
            f"{base}/sendPhoto",
            data={"chat_id": CHAT_ID, "caption": caption},
            files={"photo": f},
            timeout=60,
        )

    # ถ้ารูปใหญ่/สูงเกินที่ sendPhoto รับได้ ให้ส่งเป็นไฟล์แทน
    if not resp.ok:
        print(f"sendPhoto failed ({resp.status_code}): {resp.text}", file=sys.stderr)
        with open(OUTPUT_FILE, "rb") as f:
            resp = requests.post(
                f"{base}/sendDocument",
                data={"chat_id": CHAT_ID, "caption": caption},
                files={"document": f},
                timeout=60,
            )

    resp.raise_for_status()
    print("Sent to Telegram OK")


if __name__ == "__main__":
    take_screenshot()
    send_to_telegram()
