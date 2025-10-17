# Save this as: README.md

# Telegram Signal Auto-Forward Bot

Automatically forwards trading signals from one Telegram channel to another.

## Features
- Filters messages containing "Leverage"
- Replaces "Manually Cancelled TICKER" with "/Close TICKER"
- Real-time forwarding with no delays
- Keep-alive mechanism: Pings every 3 minutes to prevent Render from sleeping
- Only forwards messages with "Leverage" keyword

## Deployment on Render

### Prerequisites
1. Telegram API credentials (API_ID and API_HASH) from https://my.telegram.org
2. GitHub account
3. Render account (free tier available)

### Setup Steps
See deployment instructions in the repository.

## Environment Variables Required
- `API_ID`: Your Telegram API ID
- `API_HASH`: Your Telegram API Hash
- `PHONE`: Your phone number with country code (e.g., +1234567890)
- `SOURCE_CHANNEL`: Source channel username or ID (e.g., @sourcechannel)
- `TARGET_CHANNEL`: Target channel username or ID (e.g., @targetchannel)
- `SESSION_STRING`: (Optional) Session string from first authentication

## Keep-Alive Feature
The bot includes a built-in keep-alive mechanism that:
- Prints a heartbeat message every 3 minutes
- Checks connection status
- Prevents Render free tier from sleeping
- Does NOT send any messages to channels
- Only processes and forwards messages containing "Leverage"

## Local Testing
```bash
pip install -r requirements.txt
python bot.py
```

## How It Works
1. Bot monitors SOURCE_CHANNEL for new messages
2. If message contains "Leverage" → processes and forwards to TARGET_CHANNEL
3. If message does NOT contain "Leverage" → skips (keeps bot alive but doesn't forward)
4. Replaces cancellation messages with close commands:
   - "Manually Cancelled BTCUSDT" → "/Close #BTCUSDT"
   - "Manually Cancelled #BTCUSDT" → "/Close #BTCUSDT"
   - "#BTCUSDT Manually Cancelled" → "/Close #BTCUSDT"
5. Sends keep-alive ping every 3 minutes to maintain connection and prevent sleeping
