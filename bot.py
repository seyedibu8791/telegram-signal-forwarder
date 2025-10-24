# bot.py
import re
import os
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import asyncio
from datetime import datetime, timedelta, timezone
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

# =============================
# HELPER FUNCTIONS
# =============================
IST = timezone(timedelta(hours=5, minutes=30))

def now_ist():
    return datetime.now(IST)

processed_messages = {}  # Track forwarded messages to prevent duplicates

# =============================
# MESSAGE PARSER / FORMATTER
# =============================
def format_signal_message(text: str):
    """
    Parses Leverage signals like:
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
        f"Exchange: Binance Futures\n\n"
        f"Leverage: Cross ({leverage})\n"
        f"--- ⌁ ---\n"
        f"☑️ Entry Price: {entry}\n\n"
        f"☑️ Take-Profit: {target}\n"
        f"☑️ Stop Loss: {sl}"
    )
    return formatted

# =============================
# MESSAGE PROCESSOR
# =============================
def process_message(text: str):
    """
    Processes messages:
    - Manually Cancelled signals → /close #PAIR
    - Leverage signals → formatted
    """
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

    # --- Handle normal Leverage signals ---
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
    msg_id = event.message.id
    now = now_ist()

    # Cleanup old processed messages (older than 24h)
    keys_to_remove = [k for k, t in processed_messages.items() if now - t > timedelta(hours=24)]
    for k in keys_to_remove:
        processed_messages.pop(k)

    if msg_id in processed_messages:
        return  # Skip duplicates

    original_text = event.message.text
    processed_text, _ = process_message(original_text)

    if processed_text:
        await client.send_message(TARGET_CHANNEL, processed_text)
        processed_messages[msg_id] = now
        print(f"[{now.strftime('%H:%M:%S')}] Forwarded message:")
        print(f"   Original: {original_text[:80]}...")
        if processed_text != original_text:
            print(f"   Modified: {processed_text[:80]}...")

# =============================
# KEEP-ALIVE TASK
# =============================
async def keep_alive():
    while True:
        try:
            await asyncio.sleep(180)  # 3 minutes
            now = now_ist()
            print(f"Keep-alive ping at {now}", flush=True)
            if not client.is_connected():
                print("Bot connection lost, reconnecting...", flush=True)
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
    <!DOCTYPE html>
    <html>
    <head>
        <title>Telegram Forwarder Bot</title>
        <style>
            body {{ font-family: Arial; max-width: 800px; margin: 50px auto; padding: 20px; }}
            .status {{ background: #4CAF50; color: white; padding: 20px; border-radius: 5px; }}
            .info {{ background: #f5f5f5; padding: 15px; margin: 20px 0; border-radius: 5px; }}
        </style>
    </head>
    <body>
        <div class="status">
            <h1>Telegram Signal Forwarder Bot</h1>
            <p>Status: <strong>RUNNING</strong></p>
        </div>
        <div class="info">
            <h2>Configuration</h2>
            <p><strong>Source Channel:</strong> {SOURCE_CHANNEL}</p>
            <p><strong>Target Channel:</strong> {TARGET_CHANNEL}</p>
            <p><strong>Keep-Alive:</strong> Every 3 minutes</p>
            <p><strong>Time:</strong> {now_ist().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')

async def ping(request):
    auth_header = request.headers.get("Authorization")
    if PING_TOKEN and auth_header != f"Bearer {PING_TOKEN}":
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
    print("Starting Telegram Signal Forwarder Bot...", flush=True)
    print(f"Current time: {now_ist().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)

    await client.start(phone=PHONE)
    print("Bot connected successfully!", flush=True)

    if not SESSION_STRING:
        session_str = client.session.save()
        print("="*60)
        print("IMPORTANT: Save this Session String as environment variable:")
        print(session_str)
        print("="*60)

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
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Fatal error: {e}")
