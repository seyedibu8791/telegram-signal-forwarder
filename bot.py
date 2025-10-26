# bot.py
import re
import os
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import asyncio
from datetime import datetime, timedelta, timezone
from aiohttp import web
import hashlib

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

# Initialize Telegram client
if SESSION_STRING:
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
else:
    client = TelegramClient('signal_forwarder', API_ID, API_HASH)

# =============================
# HELPER FUNCTIONS
# =============================
IST = timezone(timedelta(hours=5, minutes=30))

def now_ist():
    return datetime.now(IST)

# Track processed messages: {hash_key: timestamp}
processed_messages = {}

def get_message_hash(text: str) -> str:
    """Generate a stable hash for message text"""
    return hashlib.sha256(text.strip().lower().encode()).hexdigest()

# =============================
# MESSAGE PARSER / FORMATTER
# =============================
def format_signal_message(text: str):
    """
    Parses messages like:
    BTC/USDT SHORT 🛑
    Leverage 30x
    Entries 112700
    Target 1 110200
    SL 114500
    """
    pair_match = re.search(r'([A-Z]{2,10})/?([A-Z]{2,10})?', text)
    direction_match = re.search(r'\b(BUY|LONG|SELL|SHORT)\b', text, re.IGNORECASE)
    leverage_match = re.search(r'Leverage\s*([0-9]+x)', text, re.IGNORECASE)
    entry_match = re.search(r'(?:Entry|Entries)\s*([\d.]+)', text, re.IGNORECASE)
    target_match = re.search(r'Target\s*1\s*([\d.]+)', text, re.IGNORECASE)
    sl_match = re.search(r'SL\s*([\d.]+)', text, re.IGNORECASE)

    if not (pair_match and direction_match and entry_match and target_match and sl_match):
        return None

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
# MESSAGE PROCESSOR
# =============================
def process_message(text: str):
    """Process incoming text and return formatted message + flag"""
    if not text:
        return None, False

    text_lower = text.lower()

    # --- Handle Manually Cancelled ---
    cancelled_match = re.search(r'#?([A-Z0-9]{1,10})/?([A-Z0-9]{1,10})?\s+Manually Cancelled', text, re.IGNORECASE)
    if cancelled_match:
        base = cancelled_match.group(1)
        quote = cancelled_match.group(2) or 'USDT'
        pair = f"{base}{quote}"
        return f"/close #{pair}", False

    # --- Handle Leverage signal ---
    if 'leverage' in text_lower:
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
    msg_id = event.message.id
    now = now_ist()

    # Cleanup old messages (older than 24h)
    for k in list(processed_messages.keys()):
        if now - processed_messages[k] > timedelta(hours=24):
            processed_messages.pop(k, None)

    # Create unique hash based on text content
    msg_hash = get_message_hash(original_text)

    if msg_hash in processed_messages:
        print(f"[DUPLICATE] Ignored duplicate signal (hash match): {original_text[:60]}...")
        return

    processed_text, _ = process_message(original_text)

    if processed_text:
        await client.send_message(TARGET_CHANNEL, processed_text)
        processed_messages[msg_hash] = now
        print(f"[{now.strftime('%H:%M:%S')}] Forwarded unique message:")
        print(f"   Original: {original_text[:100]}...")
        if processed_text != original_text:
            print(f"   Modified: {processed_text[:100]}...")

# =============================
# KEEP-ALIVE TASK
# =============================
async def keep_alive():
    while True:
        try:
            await asyncio.sleep(180)  # 3 minutes
            now = now_ist()
            print(f"Keep-alive ping at {now.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
            if not client.is_connected():
                print("Bot disconnected, reconnecting...", flush=True)
                await client.connect()
        except Exception as e:
            print(f"Keep-alive error: {e}", flush=True)

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
    return web.Response(text=html, content_type='text/html')

async def ping(request):
    auth = request.headers.get("Authorization")
    if PING_TOKEN and auth != f"Bearer {PING_TOKEN}":
        return web.Response(status=401, text="Unauthorized")
    now = now_ist()
    print(f"Ping received at {now}", flush=True)
    return web.json_response({"status": "alive", "time": now.strftime('%Y-%m-%d %H:%M:%S')})

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', status_page)
    app.router.add_get('/health', health_check)
    app.router.add_get('/ping', ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    print(f"Web server started on port {PORT}")

# =============================
# MAIN ENTRY
# =============================
async def main():
    print("Starting Telegram Signal Forwarder Bot...")
    print(f"Time: {now_ist().strftime('%Y-%m-%d %H:%M:%S')}")
    await client.start(phone=PHONE)
    print("Bot connected successfully!")

    if not SESSION_STRING:
        session_str = client.session.save()
        print("="*50)
        print("SAVE THIS SESSION STRING:")
        print(session_str)
        print("="*50)

    try:
        source = await client.get_entity(SOURCE_CHANNEL)
        target = await client.get_entity(TARGET_CHANNEL)
        print(f"Monitoring: {getattr(source, 'title', SOURCE_CHANNEL)}")
        print(f"Forwarding to: {getattr(target, 'title', TARGET_CHANNEL)}")
    except Exception as e:
        print(f"Error accessing channels: {e}")
        return

    await start_web_server()
    keep_alive_task = asyncio.create_task(keep_alive())
    try:
        await client.run_until_disconnected()
    finally:
        keep_alive_task.cancel()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped manually.")
    except Exception as e:
        print(f"Fatal error: {e}")
