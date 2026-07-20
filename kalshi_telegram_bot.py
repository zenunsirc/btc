import os
from dotenv import load_dotenv
from kalshi_python_sync import Configuration, KalshiClient
from telegram.ext import Application, ContextTypes
import httpx

load_dotenv()

print("=== Bot starting ===")

KALSHI_KEY_ID = os.getenv("KALSHI_KEY_ID")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

print(f"KALSHI_KEY_ID loaded: {bool(KALSHI_KEY_ID)}")
print(f"TELEGRAM_TOKEN loaded: {bool(TELEGRAM_TOKEN)}")
print(f"TELEGRAM_CHAT_ID loaded: {bool(TELEGRAM_CHAT_ID)}")

raw_key = os.getenv("KALSHI_PRIVATE_KEY_PEM", "")
clean_key = raw_key.replace('\r\n', '\n').replace('\r', '\n').strip()

print(f"Private key length: {len(clean_key)} characters")

config = Configuration(host="https://external-api.kalshi.com/trade-api/v2")
config.api_key_id = KALSHI_KEY_ID
config.private_key_pem = clean_key

try:
    kalshi = KalshiClient(config)
    print("✅ Kalshi client connected successfully")
except Exception as e:
    print(f"❌ Failed to connect to Kalshi: {e}")

async def send_update(context: ContextTypes.DEFAULT_TYPE):
    try:
        balance = kalshi.get_balance()
        print(f"Balance fetched: ${balance.balance / 100:.2f}")
        # ... rest of your monitoring code ...
    except Exception as e:
        print(f"Update error: {e}")

def main():
    print("Starting Telegram bot...")
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.job_queue.run_repeating(send_update, interval=60, first=10)
    print("Bot is running!")
    app.run_polling()

if __name__ == "__main__":
    main()