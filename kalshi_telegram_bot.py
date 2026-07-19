import os
import time
import requests
from dotenv import load_dotenv
from kalshi_python_sync import Configuration, KalshiClient

load_dotenv()

KALSHI_KEY_ID = os.getenv("KALSHI_KEY_ID")
KALSHI_PRIVATE_KEY_PATH = os.getenv("KALSHI_PRIVATE_KEY_PATH")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

# Kalshi Demo
config = Configuration(host="https://external-api.demo.kalshi.co/trade-api/v2")
config.api_key_id = KALSHI_KEY_ID

with open(KALSHI_PRIVATE_KEY_PATH, "r") as f:
    config.private_key_pem = f.read()

kalshi = KalshiClient(config)

print("✅ Bot started in cloud (Demo)")

while True:
    try:
        balance = kalshi.get_balance()
        markets = kalshi.get_markets(series_ticker="KXBTC15M", status="open", limit=6)

        msg = "✅ *Kalshi BTC 15m Bot* (Demo)\n\n"
        msg += f"💰 Balance: `${balance.balance / 100:.2f}`\n\n"
        msg += "*Open Markets:*\n"
        for m in markets.markets:
            yes_bid = (m.yes_bid or 0) / 100
            yes_ask = (m.yes_ask or 0) / 100
            msg += f"• `{m.ticker}` | Bid `${yes_bid:.2f}` Ask `${yes_ask:.2f}`\n"

        send_telegram(msg)
        print("Message sent. Sleeping 5 minutes...")

    except Exception as e:
        send_telegram(f"⚠️ Error: {str(e)}")

    time.sleep(300)   # Run every 5 minutes (we can change this later)
