import os
import re
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from playwright.sync_api import sync_playwright

TARGET_URL = os.environ["TARGET_URL"]
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# ปรับได้ผ่าน environment variable
WAIT_SECONDS = int(os.environ.get("WAIT_SECONDS", "12"))  # รอให้ Apps Script โหลดข้อมูลเสร็จ
CLICK_WAIT_SECONDS = int(os.environ.get("CLICK_WAIT_SECONDS", "6"))  # รอหลังกด GC ให้ข้อมูลโหลดใหม่
VIEWPORT_WIDTH = int(os.environ.get("VIEWPORT_WIDTH", "1600"))
VIEWPORT_HEIGHT = int(os.environ.get("VIEWPORT_HEIGHT", "1200"))
TIMEZONE = os.environ.get("TIMEZONE", "Asia/Bangkok")

OUTPUT_FILE = "screenshot.png"

GC_TEXT = re.compile(r"^\s*GC\s*$")
CALL_PUT_TEXT = re.compile(r"Call.*Put")


def find_app_frame(page, timeout_s: int = 60):
    """หน้า Apps Script ซ้อนอยู่ใน iframe จึงต้องวนหา frame ที่มีปุ่ม GC"""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for fr in page.frames:
            try:
                if fr.locator("button", has_text=GC_TEXT).count() > 0:
                    return fr
            except Exception:
                pass
        page.wait_for_timeout(1000)
    return None


def click_options(page) -> None:
    """กด GC แล้วกดปุ่ม Call/Put ถ้ากดไม่ได้จะแจ้งเตือนแต่ยังแคปภาพต่อ"""
    fr = find_app_frame(page)
    if fr is None:
        print("WARN: ไม่พบปุ่ม GC ข้ามขั้นตอนกดปุ่ม", file=sys.stderr)
        return

    try:
        fr.locator("button", has_text=GC_TEXT).first.click(timeout=10_000)
        page.wait_for_timeout(CLICK_WAIT_SECONDS * 1000)
        print("Clicked GC")
    except Exception as e:
        print(f"WARN: กด GC ไม่สำเร็จ: {e}", file=sys.stderr)

    try:
        fr.locator("button", has_text=CALL_PUT_TEXT).first.click(timeout=10_000)
        page.wait_for_timeout(2000)
        print("Clicked Call/Put")
    except Exception as e:
        print(f"WARN: กดปุ่ม Call/Put ไม่สำเร็จ: {e}", file=sys.stderr)


def take_screenshot() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
            device_scale_factor=1,
        )
        page.goto(TARGET_URL, wait_until="networkidle", timeout=90_000)
        page.wait_for_timeout(WAIT_SECONDS * 1000)
        click_options(page)
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
