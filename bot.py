# bot.py
import re
import os
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import asyncio
from datetime import datetime
from aiohttp import web

# Configuration - Using Environment Variables
API_ID = os.environ.get('API_ID')
API_HASH = os.environ.get('API_HASH')
PHONE = os.environ.get('PHONE')
SOURCE_CHANNEL = os.environ.get('SOURCE_CHANNEL')
TARGET_CHANNEL = os.environ.get('TARGET_CHANNEL')
SESSION_STRING = os.environ.get('SESSION_STRING', '')
PORT = int(os.environ.get('PORT', 10000))
PING_TOKEN = os.environ.get('PING_TOKEN')

# Initialize client with session string if available
if SESSION_STRING:
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
else:
    client = TelegramClient('signal_forwarder', API_ID, API_HASH)


# =============================
# MESSAGE PROCESSING FUNCTION
# =============================
def process_message(text):
    if not text:
        return None, False

    has_leverage = 'leverage' in text.lower()
    processed_text = text

    # Pattern 1: "#TICKER [OPTIONAL_TEXT] Manually Cancelled"
    pattern1 = r'(#[A-Z0-9]+(?:/[A-Z0-9]+)?)\s+(?:[A-Z]*\s+)?Manually\s+Cancelled'
    match1 = re.search(pattern1, processed_text, flags=re.IGNORECASE)
    if match1:
        ticker = match1.group(1)
        processed_text = re.sub(pattern1, f'/Close {ticker}', processed_text, flags=re.IGNORECASE)
        return processed_text, has_leverage

    # Pattern 2: "Manually Cancelled #TICKER"
    pattern2 = r'Manually\s+Cancelled\s+(#[A-Z0-9]+(?:/[A-Z0-9]+)?)'
    match2 = re.search(pattern2, processed_text, flags=re.IGNORECASE)
    if match2:
        ticker = match2.group(1)
        processed_text = re.sub(pattern2, f'/Close {ticker}', processed_text, flags=re.IGNORECASE)
        return processed_text, has_leverage

    # Pattern 3: "Manually Cancelled TICKER" (no #)
    pattern3 = r'Manually\s+Cancelled\s+([A-Z0-9]+(?:/[A-Z0-9]+)?)'
    match3 = re.search(pattern3, processed_text, flags=re.IGNORECASE)
    if match3 and '#' not in processed_text:
        ticker = match3.group(1)
        processed_text = re.sub(pattern3, f'/Close #{ticker}', processed_text, flags=re.IGNORECASE)
        return processed_text, has_leverage

    return processed_text, has_leverage


# =============================
# MESSAGE HANDLER
# =============================
@client.on(events.NewMessage(chats=SOURCE_CHANNEL))
async def handler(event):
    try:
        original_text = event.message.text
        processed_text, has_leverage = process_message(original_text)
        has_cancelled = 'manually cancelled' in original_text.lower() if original_text else False

        if not has_leverage and not has_cancelled:
            print(f"Skipped message (no 'Leverage' or 'Manually Cancelled') - {datetime.now().strftime('%H:%M:%S')}")
            return

        if processed_text:
            await client.send_message(TARGET_CHANNEL, processed_text)
            print(f"Forwarded message at {datetime.now().strftime('%H:%M:%S')}:")
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
            await asyncio.sleep(300)  # 3 minutes
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"Keep-alive ping at {current_time}", flush=True)

            if client.is_connected():
                print("   Bot is active and connected", flush=True)
            else:
                print("   Bot connection lost, reconnecting...", flush=True)
                await client.connect()

        except Exception as e:
            print(f"Keep-alive error: {e}", flush=True)


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
            <p><strong>Keep-Alive:</strong> Every 3 minutes</p>
            <p><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
        <div class="info">
            <h2>Features</h2>
            <ul>
                <li>Forwards messages containing "Leverage"</li>
                <li>Replaces "Manually Cancelled #TICKER" with "/Close #TICKER"</li>
                <li>Real-time forwarding with no delays</li>
                <li>Auto keep-alive to prevent sleeping</li>
            </ul>
        </div>
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')


# =============================
# PING ENDPOINT FOR KEEPALIVE
# =============================
async def ping(request):
    """Ping endpoint for GitHub Action or uptime monitor"""
    auth_header = request.headers.get("Authorization")
    if PING_TOKEN:
        if auth_header != f"Bearer {PING_TOKEN}":
            return web.Response(status=401, text="Unauthorized")

    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC+5:30')
    print(f"Ping received at {now}", flush=True)
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
        print("\n" + "=" * 60, flush=True)
        print("IMPORTANT: Save this Session String as environment variable:", flush=True)
        print("=" * 60, flush=True)
        print(session_str, flush=True)
        print("=" * 60 + "\n", flush=True)

    try:
        source = await client.get_entity(SOURCE_CHANNEL)
        target = await client.get_entity(TARGET_CHANNEL)
        print(f"Monitoring: {getattr(source, 'title', SOURCE_CHANNEL)}", flush=True)
        print(f"Forwarding to: {getattr(target, 'title', TARGET_CHANNEL)}", flush=True)
    except Exception as e:
        print(f"Error accessing channels: {e}", flush=True)
        print("Make sure you've joined both channels and have correct usernames/IDs", flush=True)
        return

    print("Bot is running...", flush=True)
    print("Keep-alive enabled: Ping every 3 minutes", flush=True)
    print("=" * 60, flush=True)

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
