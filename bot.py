# bot.py
import re
import os
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import asyncio
from datetime import datetime, timezone, timedelta
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

# Initialize Telegram client
if SESSION_STRING:
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
else:
    client = TelegramClient('signal_forwarder', API_ID, API_HASH)

# Keep track of processed messages to avoid duplicates
processed_messages = {}

# =============================
# TIMEZONE UTILS
# =============================
IST = timezone(timedelta(hours=5, minutes=30))

def now_ist():
    return datetime.now(IST)

# =============================
# MESSAGE PARSING FUNCTIONS
# =============================
def format_signal_message(text: str):
    """
    Parses trading signal messages with Leverage, Entry, Target 1, SL
    """
    pair_match = re.search(r'#?([A-Z0-9]{1,10})/?([A-Z0-9]{1,10})?', text)
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
    if direction_raw in ['BUY', 'LONG']:
        direction = "BUY 💹"
    else:
        direction = "SELL 🛑"

    leverage = leverage_match.group(1).upper() if leverage_match else "N/A"
    entry = entry_match.group(1)
    target = target_match.group(1)
    sl = sl_match.group(1)

    formatted = (
        f"Action: {direction}\n"
        f"Symbol: #{pair}\n"
        f"--- ⌁ ---\n"
        f"Exchange: Binance Futures\n\n"
        f"Leverage: Cross ({leverage})\n"
        f"--- ⌁ ---\n"
        f"☑️ Entry Price: {entry}\n\n"
        f"☑️ Take-Profit: {target}\n"
        f"☑️ Stop Loss: {sl}"
    )
    return formatted

def process_message(text: str):
    """
    Processes messages for Manually Cancelled or Leverage signals
    """
    if not text:
        return None, False

    has_leverage = 'leverage' in text.lower()
    processed_text = text

    # --- Handle Manually Cancelled ---
    cancelled_match = re.search(
        r'(?i)^#?([A-Z0-9]{1,10})/?([A-Z0-9]{1,10})?\s+Manually Cancelled', 
        text
    )
    if cancelled_match:
        base = cancelled_match.group(1)
        quote = cancelled_match.group(2) or 'USDT'
        pair = f"{base}{quote}"
        return f"/close #{pair}", False

    # --- Handle normal formatted signals with Leverage ---
    if has_leverage:
        formatted = format_signal_message(text)
        if formatted:
            return formatted, True

    return None, has_leverage

# =============================
# MESSAGE HANDLER
# =============================
@client.on(events.NewMessage(chats=SOURCE_CHANNEL))
async def handler(event):
    msg_id = event.message.id
    # Cleanup old entries
    now = now_ist()
    keys_to_remove = [k for k, t in processed_messages.items() if now - t > timedelta(hours=24)]
    for k in keys_to_remove:
        processed_messages.pop(k)

    if msg_id in processed_messages:
        return  # Skip already processed message

    try:
        original_text = event.message.text
        processed_text, has_leverage = process_message(original_text)

        if processed_text:
            await client.send_message(TARGET_CHANNEL, processed_text)
            processed_messages[msg_id] = now
            print(f"[{now.strftime('%H:%M:%S')}] Forwarded message:")
            print(f"   Original: {original_text[:80]}...")
            if processed_text != original_text:
                print(f"   Modified: {processed_text[:80]}...")

    except Exception as e:
        print(f"Error forwarding message: {e}")

# =============================
# KEEP-ALIVE TASK
# =============================
async def keep_alive():
    while True:
        try:
            await asyncio.sleep(180)  # 3 minutes
            print(f"[{now_ist().strftime('%H:%M:%S')}] Keep-alive ping")
            if not client.is_connected():
                print("Reconnecting Telegram client...")
                await client.connect()
        except Exception as e:
            print(f"Keep-alive error: {e}")

# =============================
# WEB SERVER
# =============================
async def health_check(request):
    return web.Response(text="Bot is running!", status=200)

async def status_page(request):
    html = f"""
    <!DOCTYPE html>
    <html>
    <head><title>Telegram Forwarder Bot</title></head>
    <body>
        <h1>Telegram Signal Forwarder Bot</h1>
        <p>Status: RUNNING</p>
        <p>Source: {SOURCE_CHANNEL}</p>
        <p>Target: {TARGET_CHANNEL}</p>
        <p>Time: {now_ist().strftime('%Y-%m-%d %H:%M:%S')}</p>
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')

async def ping(request):
    auth_header = request.headers.get("Authorization")
    if PING_TOKEN and auth_header != f"Bearer {PING_TOKEN}":
        return web.Response(status=401, text="Unauthorized")
    print(f"[{now_ist().strftime('%H:%M:%S')}] Ping received")
    return web.json_response({"status": "alive", "time": now_ist().isoformat()})

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
    print("Starting Telegram Signal Forwarder Bot...", flush=True)
    await client.start(phone=PHONE)
    print("Bot connected!")

    if not SESSION_STRING:
        session_str = client.session.save()
        print("Save this session string as env variable SESSION_STRING:")
        print(session_str)

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
        print("Bot stopped by user")
    except Exception as e:
        print(f"Fatal error: {e}")
