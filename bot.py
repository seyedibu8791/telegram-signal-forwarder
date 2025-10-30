import re
import os
import time
import threading
import requests
import hashlib
import asyncio
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from datetime import datetime, timedelta, timezone
from aiohttp import web

# =============================
# CONFIGURATION
# =============================
API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
PHONE = os.environ.get("PHONE")
SOURCE_CHANNEL = os.environ.get("SOURCE_CHANNEL")
TARGET_CHANNEL = os.environ.get("TARGET_CHANNEL")
SESSION_STRING = os.environ.get("SESSION_STRING", "")
PORT = int(os.environ.get("PORT", 10000))
DUPLICATE_WINDOW = int(os.environ.get("DUPLICATE_WINDOW", 5))  # seconds

# Initialize Telegram client
if SESSION_STRING:
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
else:
    client = TelegramClient("signal_forwarder", API_ID, API_HASH)

# =============================
# HELPERS
# =============================
IST = timezone(timedelta(hours=5, minutes=30))
def now_ist():
    return datetime.now(IST)

processed_messages = {}  # {hash_key: timestamp}
recent_signals = {}      # {pair: timestamp} for duplicate prevention


def get_message_hash(text: str) -> str:
    """Generate a stable hash for message text"""
    return hashlib.sha256(text.strip().lower().encode()).hexdigest()


# =============================
# MESSAGE PARSER / FORMATTER
# =============================
def format_signal_message(text: str):
    text = re.sub(r"[^\S\r\n]+", " ", text)
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    # Try to detect main components flexibly
    pair_match = re.search(r"([A-Z]{2,10})/?([A-Z]{2,10})?", text)
    direction_match = re.search(r"\b(LONG|SHORT|BUY|SELL)\b", text, re.IGNORECASE)
    leverage_match = re.search(r"Leverage\s*[-:]?\s*([0-9]+x)", text, re.IGNORECASE)
    entry_match = re.search(r"(?:Entry|Entries)\s*[-:]?\s*([\d.]+)", text, re.IGNORECASE)
    target_match = re.search(r"Target\s*(?:1)?\s*[-:]?\s*([\d.]+)", text, re.IGNORECASE)
    sl_match = re.search(r"SL\s*[-:]?\s*([\d.]+)", text, re.IGNORECASE)

    if not (pair_match and direction_match and entry_match and target_match and sl_match):
        return None

    base = pair_match.group(1)
    quote = pair_match.group(2) or "USDT"
    pair = f"{base}{quote}"

    direction_raw = direction_match.group(1).upper()
    direction = "LONG" if direction_raw in ["LONG", "BUY"] else "SHORT"

    leverage = leverage_match.group(1).upper() if leverage_match else "N/A"
    entry = entry_match.group(1)
    target = target_match.group(1)
    sl = sl_match.group(1)

    formatted = (
        f"Action: {direction}\n"
        f"Symbol: #{pair}\n"
        f"--- ⌁ ---\n"
        f"Exchange: Binance Futures\n"
        f"Leverage: Cross ({leverage})\n"
        f"--- ⌁ ---\n"
        f"☑️ Entry Price: {entry}\n"
        f"☑️ Take-Profit: {target}\n"
        f"☑️ Stop Loss: {sl}"
    )
    return formatted


# =============================
# MESSAGE PROCESSOR
# =============================
def process_message(text: str):
    """Parses and converts messages to standard format"""
    if not text:
        return None, False

    text_lower = text.lower()

    # Handle manually cancelled signals
    cancel_match = re.search(
        r"#?([A-Z0-9]{1,10})/?([A-Z0-9]{1,10})?\s+Manually\s+Cancelled",
        text,
        re.IGNORECASE,
    )
    if cancel_match:
        base = cancel_match.group(1)
        quote = cancel_match.group(2) or "USDT"
        pair = f"{base}{quote}".lower()
        return f"/close #{pair}", False

    # Handle standard leverage signals
    if "leverage" in text_lower:
        formatted = format_signal_message(text)
        if formatted:
            return formatted, True

    return None, False


# =============================
# MESSAGE HANDLER
# =============================
@client.on(events.NewMessage(chats=SOURCE_CHANNEL))
async def handler(event):
    original_text = event.message.text or ""
    now = now_ist()

    # cleanup old records
    for k in list(processed_messages.keys()):
        if now - processed_messages[k] > timedelta(hours=24):
            processed_messages.pop(k, None)

    msg_hash = get_message_hash(original_text)
    if msg_hash in processed_messages:
        print(f"[SKIP] Duplicate message hash: {original_text[:50]}...")
        return

    processed_text, is_signal = process_message(original_text)
    if not processed_text:
        return

    # Skip same pair within DUPLICATE_WINDOW
    pair_match = re.search(r"#?([A-Z]{2,10})(USDT|USD)?", processed_text, re.IGNORECASE)
    if pair_match:
        pair = pair_match.group(1).upper()
        last_time = recent_signals.get(pair)
        if last_time and (now - last_time).total_seconds() < DUPLICATE_WINDOW:
            print(f"[SKIP] Duplicate pair {pair} within {DUPLICATE_WINDOW}s window.")
            return
        recent_signals[pair] = now

    # Forward to target
    await client.send_message(TARGET_CHANNEL, processed_text)
    processed_messages[msg_hash] = now
    print(f"[{now.strftime('%H:%M:%S')}] ✅ Forwarded:")
    print(f"From: {original_text[:100]}...")
    if processed_text != original_text:
        print(f"→ Converted: {processed_text}")


# =============================
# SELF-PING (RENDER KEEPALIVE)
# =============================
def self_ping():
    """Pings its own Render URL every 5 minutes"""
    url = os.environ.get("RENDER_URL")
    if not url:
        print("[WARN] No RENDER_URL set. Skipping self-ping.")
        return
    while True:
        try:
            requests.get(f"{url}/ping", timeout=10)
            print(f"[PING] Self-ping sent → {url}/ping")
        except Exception as e:
            print(f"[PingError] {e}")
        time.sleep(300)  # 5 min


# =============================
# WEB SERVER
# =============================
async def health_check(request):
    return web.Response(text="Bot is running!", status=200)

async def status_page(request):
    html = f"""
    <html><head><title>Telegram Forwarder Bot</title></head>
    <body>
    <h2>Telegram Forwarder Bot - Status</h2>
    <p><b>Status:</b> RUNNING</p>
    <p><b>Source:</b> {SOURCE_CHANNEL}</p>
    <p><b>Target:</b> {TARGET_CHANNEL}</p>
    <p><b>Time:</b> {now_ist().strftime('%Y-%m-%d %H:%M:%S')}</p>
    <p><b>Processed Messages:</b> {len(processed_messages)}</p>
    </body></html>
    """
    return web.Response(text=html, content_type="text/html")

async def ping(request):
    now = now_ist()
    print(f"Ping received at {now}")
    return web.json_response({"status": "alive", "time": now.strftime("%Y-%m-%d %H:%M:%S")})

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", status_page)
    app.router.add_get("/health", health_check)
    app.router.add_get("/ping", ping)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Web server started on port {PORT}")


# =============================
# MAIN
# =============================
async def main():
    print("Starting Telegram Signal Forwarder Bot...")
    await client.start(phone=PHONE)
    print("Bot connected successfully!")

    if not SESSION_STRING:
        session_str = client.session.save()
        print("=" * 50)
        print("SAVE THIS SESSION STRING:")
        print(session_str)
        print("=" * 50)

    try:
        source = await client.get_entity(SOURCE_CHANNEL)
        target = await client.get_entity(TARGET_CHANNEL)
        print(f"Monitoring: {getattr(source, 'title', SOURCE_CHANNEL)}")
        print(f"Forwarding to: {getattr(target, 'title', TARGET_CHANNEL)}")
    except Exception as e:
        print(f"Error accessing channels: {e}")
        return

    # Start background self-ping thread
    threading.Thread(target=self_ping, daemon=True).start()

    await start_web_server()
    try:
        await client.run_until_disconnected()
    except Exception as e:
        print(f"[FatalError] {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped manually.")
    except Exception as e:
        print(f"Fatal error: {e}")
