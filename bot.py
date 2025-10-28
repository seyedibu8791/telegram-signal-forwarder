# bot.py
import re
import os
import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from aiohttp import web

# =============================
# CONFIGURATION
# =============================
API_ID = os.environ.get('API_ID')
API_HASH = os.environ.get('API_HASH')
PHONE = os.environ.get('PHONE')
SOURCE_CHANNEL = os.environ.get('SOURCE_CHANNEL')
TARGET_CHANNEL = os.environ.get('TARGET_CHANNEL')
SESSION_STRING = os.environ.get('SESSION_STRING', '')
PORT = int(os.environ.get('PORT', 10000))
PING_TOKEN = os.environ.get('PING_TOKEN')

# Duplicate skip window (in seconds)
DUPLICATE_WINDOW = int(os.environ.get('DUPLICATE_WINDOW', 10))

# =============================
# TELEGRAM CLIENT INIT
# =============================
if SESSION_STRING:
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
else:
    client = TelegramClient('signal_forwarder', API_ID, API_HASH)

# =============================
# HELPERS
# =============================
IST = timezone(timedelta(hours=5, minutes=30))

def now_ist():
    return datetime.now(IST)

processed_messages = {}  # {msg_hash: timestamp}

def get_message_hash(text: str) -> str:
    """Generate a stable hash for message text."""
    return hashlib.sha256(text.strip().lower().encode()).hexdigest()

# =============================
# PARSING AND FORMATTING
# =============================
def format_signal_message(text: str):
    """
    Parses flexible signal formats and returns clean formatted output.
    Example inputs:
      ETH/USDT LONG ✳️ Leverage - 30x Entries 4089 Target 1 4150 SL 4020
      SOL/USDT SHORT 🛑 Leverage 10x Entries 204.6 Target 1 200 SL 205.5
    """
    # Normalize text
    clean_text = re.sub(r'\s+', ' ', text).strip()

    # Extract key fields
    pair_match = re.search(r'([A-Z]{2,10})/?([A-Z]{2,10})?', clean_text)
    direction_match = re.search(r'\b(BUY|LONG|SELL|SHORT)\b', clean_text, re.IGNORECASE)
    leverage_match = re.search(r'Leverage\s*[-:]?\s*([0-9]+x)', clean_text, re.IGNORECASE)
    entry_match = re.search(r'(?:Entry|Entries)\s*[-:]?\s*([\d.]+)', clean_text, re.IGNORECASE)
    target_match = re.search(r'Target\s*1\s*[-:]?\s*([\d.]+)', clean_text, re.IGNORECASE)
    sl_match = re.search(r'SL\s*[-:]?\s*([\d.]+)', clean_text, re.IGNORECASE)

    if not (pair_match and direction_match and entry_match and target_match and sl_match):
        return None  # Skip if incomplete

    base = pair_match.group(1)
    quote = pair_match.group(2) or 'USDT'
    pair = f"{base}{quote}"

    direction_raw = direction_match.group(1).upper()
    direction = "BUY 💹" if direction_raw in ['BUY', 'LONG'] else "SELL 🛑"

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
# PROCESS MESSAGE
# =============================
def process_message(text: str):
    """Decide what to do with each message."""
    if not text:
        return None

    text_lower = text.lower()

    # --- Case 1: Manually Cancelled ---
    cancelled = re.search(r'#?([A-Z0-9]{1,10})/?([A-Z0-9]{1,10})?\s+manually cancelled', text, re.IGNORECASE)
    if cancelled:
        base = cancelled.group(1)
        quote = cancelled.group(2) or 'USDT'
        pair = f"{base}{quote}"
        return f"/close #{pair}"

    # --- Case 2: Signal with Leverage ---
    if 'leverage' in text_lower:
        formatted = format_signal_message(text)
        if formatted:
            return formatted

    return None

# =============================
# TELEGRAM EVENT HANDLER
# =============================
@client.on(events.NewMessage(chats=SOURCE_CHANNEL))
async def handler(event):
    original_text = event.message.text or ""
    now = now_ist()
    msg_hash = get_message_hash(original_text)

    # Cleanup old processed messages
    for key, timestamp in list(processed_messages.items()):
        if (now - timestamp).total_seconds() > 86400:  # 24 hours
            processed_messages.pop(key, None)

    # Duplicate detection
    if msg_hash in processed_messages:
        if (now - processed_messages[msg_hash]).total_seconds() < DUPLICATE_WINDOW:
            print(f"[DUPLICATE] Ignored within {DUPLICATE_WINDOW}s window.")
            return

    # Process
    processed_text = process_message(original_text)
    if processed_text:
        await client.send_message(TARGET_CHANNEL, processed_text)
        processed_messages[msg_hash] = now
        print(f"[{now.strftime('%H:%M:%S')}] Forwarded: {processed_text[:80]}...")
    else:
        print(f"[SKIPPED] Unrecognized message: {original_text[:80]}")

# =============================
# KEEP-ALIVE
# =============================
async def keep_alive():
    while True:
        await asyncio.sleep(180)
        now = now_ist()
        print(f"Keep-alive ping: {now.strftime('%Y-%m-%d %H:%M:%S')}")

# =============================
# WEB SERVER
# =============================
async def health(request):
    return web.Response(text="Bot is alive!", status=200)

async def ping(request):
    auth = request.headers.get("Authorization")
    if PING_TOKEN and auth != f"Bearer {PING_TOKEN}":
        return web.Response(status=401, text="Unauthorized")
    return web.json_response({"status": "alive", "time": now_ist().strftime('%Y-%m-%d %H:%M:%S')})

async def start_web():
    app = web.Application()
    app.router.add_get('/', health)
    app.router.add_get('/ping', ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    print(f"Web server running on port {PORT}")

# =============================
# MAIN
# =============================
async def main():
    print("Starting bot...")
    await client.start(phone=PHONE)
    print("Connected to Telegram.")

    if not SESSION_STRING:
        print("Save this session string:")
        print(client.session.save())

    await start_web()
    asyncio.create_task(keep_alive())
    await client.run_until_disconnected()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped manually.")
