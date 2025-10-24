# bot.py
import re
import os
import asyncio
from datetime import datetime, timedelta
from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import StringSession

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

# =============================
# TELEGRAM CLIENT
# =============================
if SESSION_STRING:
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
else:
    client = TelegramClient('signal_forwarder', API_ID, API_HASH)

# =============================
# GLOBAL CACHE TO PREVENT DUPLICATES (Memory-Safe)
# =============================
processed_messages = {}  # {message_id: timestamp}
DUPLICATE_TTL = timedelta(minutes=10)  # keep message IDs for 10 minutes

def cleanup_processed_messages():
    """Remove old message IDs to prevent memory growth"""
    now = datetime.utcnow()
    to_delete = [msg_id for msg_id, ts in processed_messages.items() if now - ts > DUPLICATE_TTL]
    for msg_id in to_delete:
        del processed_messages[msg_id]

# =============================
# MESSAGE PARSER
# =============================
def format_signal_message(text: str):
    # Manually Cancelled
    cancel_match = re.search(r'(?:Manually\s+Cancelled\s+)(#?[A-Z0-9]+(?:/[A-Z0-9]+)?)', text, re.IGNORECASE)
    if cancel_match:
        ticker = cancel_match.group(1).replace('/', '')
        if not ticker.startswith('#'):
            ticker = f"#{ticker}"
        return f"/Close {ticker}", True

    # Extract values for normal signal
    pair_match = re.search(r'([A-Z]{2,10})/?([A-Z]{2,10})?', text)
    direction_match = re.search(r'\b(BUY|LONG|SELL|SHORT)\b', text, re.IGNORECASE)
    leverage_match = re.search(r'Leverage\s*([0-9]+x)', text, re.IGNORECASE)
    entry_match = re.search(r'(?:Entry|Entries)\s*([\d.]+)', text, re.IGNORECASE)
    target_match = re.search(r'Target\s*1\s*([\d.]+)', text, re.IGNORECASE)
    sl_match = re.search(r'SL\s*([\d.]+)', text, re.IGNORECASE)

    if not (pair_match and direction_match and entry_match and target_match and sl_match):
        return None, False

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
        f"Exchange: Binance Futures\n"
        f"Leverage: Cross ({leverage})\n"
        f"--- ⌁ ---\n"
        f"☑️ Entry Price: {entry}\n"
        f"☑️ Take-Profit: {target}\n"
        f"☑️ Stop Loss: {sl}"
    )
    return formatted, True

# =============================
# MESSAGE HANDLER
# =============================
@client.on(events.NewMessage(chats=SOURCE_CHANNEL))
async def handler(event):
    try:
        cleanup_processed_messages()  # clean old IDs first

        msg_id = event.message.id
        if msg_id in processed_messages:
            return  # skip duplicate
        processed_messages[msg_id] = datetime.utcnow()

        text = event.message.text
        processed_text, is_valid = format_signal_message(text)

        if not is_valid:
            print(f"Skipped message (not valid signal) - {datetime.now().strftime('%H:%M:%S')}")
            return

        if processed_text:
            await client.send_message(TARGET_CHANNEL, processed_text)
            print(f"Forwarded message at {datetime.now().strftime('%H:%M:%S')}:")
            print(f"   Original: {text[:80]}...")
            if processed_text != text:
                print(f"   Modified: {processed_text[:80]}...")

    except Exception as e:
        print(f"Error forwarding message: {e}")

# =============================
# KEEP-ALIVE TASK
# =============================
async def keep_alive():
    while True:
        try:
            await asyncio.sleep(300)  # every 5 minutes
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"Keep-alive ping at {now}")
            if not client.is_connected():
                await client.connect()
        except Exception as e:
            print(f"Keep-alive error: {e}")

# =============================
# WEB SERVER FOR RENDER
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
            <p><strong>Keep-Alive:</strong> Every 5 minutes</p>
            <p><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')

async def ping(request):
    auth_header = request.headers.get("Authorization")
    if PING_TOKEN and auth_header != f"Bearer {PING_TOKEN}":
        return web.Response(status=401, text="Unauthorized")
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
    print(f"Ping received at {now}")
    return web.json_response({"status": "alive", "time": now})

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
    print(f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    await client.start(phone=PHONE)
    print("Bot connected successfully!", flush=True)

    if not SESSION_STRING:
        session_str = client.session.save()
        print("\n" + "="*60)
        print("IMPORTANT: Save this Session String as environment variable:")
        print("="*60)
        print(session_str)
        print("="*60 + "\n")

    try:
        source = await client.get_entity(SOURCE_CHANNEL)
        target = await client.get_entity(TARGET_CHANNEL)
        print(f"Monitoring: {getattr(source,'title',SOURCE_CHANNEL)}")
        print(f"Forwarding to: {getattr(target,'title',TARGET_CHANNEL)}")
    except Exception as e:
        print(f"Error accessing channels: {e}")
        return

    await start_web_server()
    asyncio.create_task(keep_alive())
    await client.run_until_disconnected()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Fatal error: {e}")
