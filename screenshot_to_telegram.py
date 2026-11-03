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
TELEGRAM_RETRIES = int(os.environ.get("TELEGRAM_RETRIES", "3"))  # จำนวนครั้งที่ลองส่ง Telegram ถ้าเน็ตหลุด

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


HIDE_BANNER_JS = """
() => {
    const text = "created by a Google Apps Script user";
    const el = [...document.querySelectorAll("body *")]
        .find(e => e.children.length === 0 && (e.textContent || "").includes(text));
    if (!el) return false;
    // ไล่ขึ้นไปหากล่องแถบเตือนทั้งแถบ (ไม่เกินความสูงของแถบ จะได้ไม่ซ่อนตัวแอป)
    let bar = el;
    while (bar.parentElement && bar.parentElement !== document.body
           && bar.parentElement.offsetHeight < 80) {
        bar = bar.parentElement;
    }
    bar.style.display = "none";
    return true;
}
"""


def hide_banner(page) -> None:
    """ซ่อนแถบ 'This application was created by a Google Apps Script user' ด้านบน"""
    try:
        if page.evaluate(HIDE_BANNER_JS):
            print("Hid Apps Script banner")
        else:
            print("WARN: ไม่พบแถบ Apps Script", file=sys.stderr)
    except Exception as e:
        print(f"WARN: ซ่อนแถบ Apps Script ไม่สำเร็จ: {e}", file=sys.stderr)


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
        hide_banner(page)
        page.wait_for_timeout(500)
        page.screenshot(path=OUTPUT_FILE, full_page=True)
        browser.close()


def post_file(url: str, data: dict, field: str):
    """ส่งไฟล์ไป Telegram ถ้าการเชื่อมต่อหลุด/timeout/429/5xx จะลองใหม่ (เปิดไฟล์ใหม่ทุกครั้ง)"""
    for attempt in range(1, TELEGRAM_RETRIES + 1):
        last = attempt == TELEGRAM_RETRIES
        try:
            with open(OUTPUT_FILE, "rb") as f:
                resp = requests.post(url, data=data, files={field: f}, timeout=60)
        except requests.exceptions.RequestException as e:
            if last:
                raise
            wait = 5 * attempt
            print(
                f"WARN: ส่ง Telegram ไม่สำเร็จ ({attempt}/{TELEGRAM_RETRIES}): {e} "
                f"ลองใหม่ใน {wait} วินาที",
                file=sys.stderr,
            )
            time.sleep(wait)
            continue

        if (resp.status_code == 429 or resp.status_code >= 500) and not last:
            wait = 5 * attempt
            print(
                f"WARN: Telegram ตอบ {resp.status_code} ({attempt}/{TELEGRAM_RETRIES}) "
                f"ลองใหม่ใน {wait} วินาที",
                file=sys.stderr,
            )
            time.sleep(wait)
            continue

        return resp


def send_to_telegram() -> None:
    now = datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d %H:%M")
    caption = f"Intraday OI Monitor\n{now} ({TIMEZONE})"
    base = f"https://api.telegram.org/bot{BOT_TOKEN}"

    resp = post_file(
        f"{base}/sendPhoto",
        {"chat_id": CHAT_ID, "caption": caption},
        "photo",
    )

    # ถ้ารูปใหญ่/สูงเกินที่ sendPhoto รับได้ ให้ส่งเป็นไฟล์แทน
    if not resp.ok:
        print(f"sendPhoto failed ({resp.status_code}): {resp.text}", file=sys.stderr)
        resp = post_file(
            f"{base}/sendDocument",
            {"chat_id": CHAT_ID, "caption": caption},
            "document",
        )

    resp.raise_for_status()

    # บอกว่าส่งไปที่ไหน จะได้รู้ว่าต้องไปดูข้อความที่แชทไหน (ไม่แสดงเลข chat id เต็ม)
    result = resp.json()["result"]
    chat = result["chat"]
    chat_name = chat.get("title") or chat.get("username") or chat.get("first_name") or "-"
    chat_id = str(chat["id"])
    print(f"Sent to Telegram OK: message_id={result['message_id']}")
    print(f"  chat type: {chat['type']}, name: {chat_name}, id ends with: ...{chat_id[-4:]}")


def print_bot_info() -> None:
    resp = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=30)
    resp.raise_for_status()
    bot = resp.json()["result"]
    print(f"Bot: @{bot['username']} ({bot['first_name']})")


if __name__ == "__main__":
    print_bot_info()
    take_screenshot()
    send_to_telegram()
