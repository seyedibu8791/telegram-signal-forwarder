# bot.py
import re
import os
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import asyncio
from datetime import datetime
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
# MESSAGE PARSER
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


# =============================
# MESSAGE PROCESSING FUNCTION
# =============================
def process_message(text: str):
    """
    Handles message routing logic:
    - Detects 'Manually Cancelled' → '/Close'
    - Detects Leverage → formats trade message
    - Skips irrelevant content
    """
    if not text:
        return None, False

    has_leverage = 'leverage' in text.lower()
    has_cancelled = 'manually cancelled' in text.lower()

    # --- CASE 1: Trade signal message ---
    if has_leverage:
        formatted = format_signal_message(text)
        if formatted:
            return formatted, True
        else:
            return text, True

    # --- CASE 2: Cancel message ---
    if has_cancelled:
        processed_text = text
        pattern1 = r'(#[A-Z0-9]+(?:/[A-Z0-9]+)?)\s+(?:[A-Z]*\s+)?Manually\s+Cancelled'
        processed_text = re.sub(pattern1, r'/Close \1', processed_text, flags=re.IGNORECASE)

        pattern2 = r'Manually\s+Cancelled\s+(#[A-Z0-9]+(?:/[A-Z0-9]+)?)'
        processed_text = re.sub(pattern2, r'/Close \1', processed_text, flags=re.IGNORECASE)

        pattern3 = r'Manually\s+Cancelled\s+([A-Z0-9]+(?:/[A-Z0-9]+)?)'
        processed_text = re.sub(pattern3, r'/Close #\1', processed_text, flags=re.IGNORECASE)

        processed_text = re.sub(r'\s+', ' ', processed_text).strip()
        return processed_text, True

    # --- OTHERWISE SKIP ---
    return None, False


# =============================
# MESSAGE HANDLER
# =============================
@client.on(events.NewMessage(chats=SOURCE_CHANNEL))
async def handler(event):
    try:
        original_text = event.message.text
        processed_text, should_forward = process_message(original_text)

        if not should_forward:
            print(f"⏭ Skipped at {datetime.now().strftime('%H:%M:%S')}")
            return

        await client.send_message(TARGET_CHANNEL, processed_text)
        print(f"✅ Forwarded at {datetime.now().strftime('%H:%M:%S')}")
        if processed_text != original_text:
            print(f"   Modified: {processed_text[:100]}...")

    except Exception as e:
        print(f"❌ Error forwarding message: {e}")


# =============================
# KEEP-ALIVE TASK
# =============================
async def keep_alive():
    while True:
        try:
            await asyncio.sleep(300)  # every 5 min
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"[Keep-alive] Ping at {current_time}", flush=True)

            if not await client.is_connected():
                print("Reconnecting client...", flush=True)
                await client.connect()

        except Exception as e:
            print(f"[Keep-alive error] {e}", flush=True)


# =============================
# WEB SERVER (Render)
# =============================
async def health_check(request):
    return web.Response(text="Bot is running!", status=200)

async def status_page(request):
    html = f"""
    <html>
        <head><title>Telegram Forwarder Bot</title></head>
        <body style='font-family:Arial'>
            <h1>✅ Telegram Forwarder Bot Active</h1>
            <p><b>Source:</b> {SOURCE_CHANNEL}</p>
            <p><b>Target:</b> {TARGET_CHANNEL}</p>
            <p>Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')

async def ping(request):
    """Used by GitHub Action or uptime monitors"""
    auth_header = request.headers.get("Authorization")
    if PING_TOKEN and auth_header != f"Bearer {PING_TOKEN}":
        return web.Response(status=401, text="Unauthorized")
    print(f"Ping received at {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    return web.json_response({"status": "alive", "time": datetime.utcnow().isoformat()})

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', status_page)
    app.router.add_get('/health', health_check)
    app.router.add_get('/ping', ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    print(f"🌍 Web server started on port {PORT}")


# =============================
# MAIN FUNCTION
# =============================
async def main():
    print("🚀 Starting Telegram Forwarder Bot...", flush=True)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)

    await client.start(phone=PHONE)
    print("✅ Telegram client connected", flush=True)

    if not SESSION_STRING:
        print("=" * 60)
        print("⚠️ Save this SESSION_STRING to Render env variable:")
        print(client.session.save())
        print("=" * 60)

    try:
        src = await client.get_entity(SOURCE_CHANNEL)
        tgt = await client.get_entity(TARGET_CHANNEL)
        print(f"Listening to: {getattr(src, 'title', SOURCE_CHANNEL)}")
        print(f"Forwarding to: {getattr(tgt, 'title', TARGET_CHANNEL)}")
    except Exception as e:
        print(f"Error getting channels: {e}")
        return

    await start_web_server()
    asyncio.create_task(keep_alive())

    print("💡 Bot running. Waiting for messages...")
    await client.run_until_disconnected()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped manually.")
    except Exception as e:
        print(f"Fatal error: {e}")
