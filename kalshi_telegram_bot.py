import os
import requests
from dotenv import load_dotenv
from kalshi_python_sync import Configuration, KalshiClient

load_dotenv()

KALSHI_KEY_ID = os.getenv("KALSHI_KEY_ID")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

send_telegram("🔄 Testing Kalshi connection...")

try:
    raw_key = os.getenv("KALSHI_PRIVATE_KEY_PEM", "")
    clean_key = raw_key.replace('\r\n', '\n').replace('\r', '\n').strip()

    config = Configuration(host="https://external-api.kalshi.com/trade-api/v2")
    config.api_key_id = KALSHI_KEY_ID
    config.private_key_pem = clean_key

    kalshi = KalshiClient(config)
    send_telegram("✅ Kalshi client created successfully")

    # Try one simple call
    balance = kalshi.get_balance()
    send_telegram(f"✅ Balance fetch successful: ${balance.balance / 100:.2f}")

except Exception as e:
    send_telegram(f"❌ ERROR: {type(e).__name__} - {str(e)}")
