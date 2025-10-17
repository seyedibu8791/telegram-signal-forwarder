# bot.py
import re
import os
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import asyncio
from datetime import datetime

# ============================================
# CONFIGURATION - Using Environment Variables
# ============================================
API_ID = os.environ.get('API_ID')
API_HASH = os.environ.get('API_HASH')
PHONE = os.environ.get('PHONE')
SOURCE_CHANNEL = os.environ.get('SOURCE_CHANNEL')
TARGET_CHANNEL = os.environ.get('TARGET_CHANNEL')
SESSION_STRING = os.environ.get('SESSION_STRING', '')

# ============================================
# Bot Implementation
# ============================================

# Initialize client with session string if available
if SESSION_STRING:
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
else:
    client = TelegramClient('signal_forwarder', API_ID, API_HASH)

def process_message(text):
    """
    Process message text:
    1. Check if contains 'Leverage'
    2. Replace 'Manually Cancelled TICKER' or 'Manually Cancelled #TICKER' with '/Close #TICKER'
    """
    if not text:
        return None, False
    
    # Check if message contains "Leverage"
    has_leverage = 'leverage' in text.lower()
    
    # Replace "Manually Cancelled TICKER" with "/Close TICKER"
    # Handles both formats:
    # - "Manually Cancelled BTCUSDT" -> "/Close BTCUSDT"
    # - "Manually Cancelled #BTCUSDT" -> "/Close #BTCUSDT"
    # - "#BTCUSDT Manually Cancelled" -> "/Close #BTCUSDT"
    
    # Pattern 1: Manually Cancelled #TICKER or Manually Cancelled TICKER
    pattern1 = r'Manually\s+Cancelled\s+(#?[A-Z0-9]+)'
    processed_text = re.sub(pattern1, r'/Close \1', text, flags=re.IGNORECASE)
    
    # Pattern 2: #TICKER Manually Cancelled (ticker before the text)
    pattern2 = r'(#[A-Z0-9]+)\s+Manually\s+Cancelled'
    processed_text = re.sub(pattern2, r'/Close \1', processed_text, flags=re.IGNORECASE)
    
    # Ensure hashtag is present in /Close command
    # If we have "/Close TICKER" without #, add it
    pattern3 = r'/Close\s+([A-Z0-9]+)(?!#)'
    if re.search(pattern3, processed_text, flags=re.IGNORECASE):
        # Check if the ticker doesn't already have a #
        processed_text = re.sub(r'/Close\s+(?!#)([A-Z0-9]+)', r'/Close #\1', processed_text, flags=re.IGNORECASE)
    
    return processed_text, has_leverage

@client.on(events.NewMessage(chats=SOURCE_CHANNEL))
async def handler(event):
    """Handle new messages from source channel"""
    try:
        original_text = event.message.text
        processed_text, has_leverage = process_message(original_text)
        
        # Check if message contains "Leverage" keyword
        if not has_leverage:
            print(f"⏭️  Skipped message (no 'Leverage' found) - {datetime.now().strftime('%H:%M:%S')}")
            return
        
        # Forward the processed message
        if processed_text:
            await client.send_message(TARGET_CHANNEL, processed_text)
            print(f"✅ Forwarded message at {datetime.now().strftime('%H:%M:%S')}:")
            print(f"   Original: {original_text[:50]}...")
            if processed_text != original_text:
                print(f"   Modified: {processed_text[:50]}...")
        
    except Exception as e:
        print(f"❌ Error forwarding message: {e}")

async def keep_alive():
    """Send keep-alive ping every 3 minutes to prevent Render from sleeping"""
    while True:
        try:
            await asyncio.sleep(180)  # 3 minutes = 180 seconds
            
            # Just print a keep-alive message - no actual message sending
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"💓 Keep-alive ping at {current_time}")
            
            # Perform a lightweight operation to keep the bot active
            # Check if we're still connected
            if client.is_connected():
                print(f"   ✓ Bot is active and connected")
            else:
                print(f"   ⚠ Bot connection lost, reconnecting...")
                await client.connect()
                
        except Exception as e:
            print(f"❌ Keep-alive error: {e}")

async def main():
    """Start the bot"""
    print("🚀 Starting Telegram Signal Forwarder Bot...")
    print(f"⏰ Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Start the client
    await client.start(phone=PHONE)
    print("✅ Bot connected successfully!")
    
    # Save session string for future use (only on first run)
    if not SESSION_STRING:
        session_str = client.session.save()
        print(f"\n{'='*60}")
        print(f"📝 IMPORTANT: Save this Session String as environment variable:")
        print(f"{'='*60}")
        print(f"{session_str}")
        print(f"{'='*60}\n")
    
    # Verify channels
    try:
        source = await client.get_entity(SOURCE_CHANNEL)
        target = await client.get_entity(TARGET_CHANNEL)
        print(f"📥 Monitoring: {getattr(source, 'title', SOURCE_CHANNEL)}")
        print(f"📤 Forwarding to: {getattr(target, 'title', TARGET_CHANNEL)}")
    except Exception as e:
        print(f"❌ Error accessing channels: {e}")
        print("Make sure you've joined both channels and have correct usernames/IDs")
        return
    
    print("🔄 Bot is running...")
    print("💓 Keep-alive enabled: Ping every 3 minutes")
    print("=" * 60)
    
    # Start keep-alive task in background
    keep_alive_task = asyncio.create_task(keep_alive())
    
    # Keep the bot running
    try:
        await client.run_until_disconnected()
    finally:
        keep_alive_task.cancel()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
