import os
from collections import deque
from datetime import datetime
from dotenv import load_dotenv
from kalshi_python_sync import Configuration, KalshiClient
from telegram.ext import Application, ContextTypes
import httpx

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

raw_key = os.getenv("KALSHI_PRIVATE_KEY_PEM", "")
clean_key = raw_key.replace('\r\n', '\n').replace('\r', '\n').strip()

config = Configuration(host="https://external-api.kalshi.com/trade-api/v2")
config.api_key_id = os.getenv("KALSHI_KEY_ID")
config.private_key_pem = clean_key
kalshi = KalshiClient(config)

price_history = deque(maxlen=100)
last_btc_price = None
last_strong_alert = None

async def get_btc_price_async():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT")
            return float(r.json()["price"])
    except:
        return None

async def send_update(context: ContextTypes.DEFAULT_TYPE):
    global last_btc_price, last_strong_alert
    try:
        markets = kalshi.get_markets(series_ticker="KXBTC15M", status="open", limit=6)
        btc_price = await get_btc_price_async()

        if btc_price:
            price_history.append((datetime.now(), btc_price))

        first = markets.markets[0] if markets.markets else None

        # Scoring
        buy_score = 5
        sell_score = 5

        if first:
            mid = (float(first.yes_bid_dollars or 0) + float(first.yes_ask_dollars or 0)) / 2
            if mid > 0.62: buy_score = 8
            elif mid > 0.56: buy_score = 7
            elif mid < 0.38: sell_score = 8
            elif mid < 0.44: sell_score = 7

        msg = "💰 *money printer🤑*\n\n"
        if btc_price:
            msg += f"₿ BTC: `${btc_price:,.2f}`\n\n"
        msg += f"Compra: `{buy_score}/10` | Venta: `{sell_score}/10`\n\n"
        msg += "*Mercados BTC 15min:*\n"

        for m in markets.markets:
            yes_bid = float(m.yes_bid_dollars or 0)
            yes_ask = float(m.yes_ask_dollars or 0)
            mid = (yes_bid + yes_ask) / 2 if (yes_bid + yes_ask) > 0 else 0
            up = round(mid * 100)
            down = 100 - up
            lock = " 🔒💵" if up >= 75 or down >= 75 else ""
            msg += f"• Arriba · {up}% | Bajo · {down}%{lock}\n"

        await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode="Markdown")

        # Strong Alert
        now = datetime.now()
        if (buy_score >= 8 or sell_score >= 8):
            if last_strong_alert is None or (now - last_strong_alert).seconds > 180:
                alert = "🔥 *SEÑAL FUERTE DETECTADA*\n\n"
                if buy_score >= 8:
                    alert += f"📈 Compra fuerte: `{buy_score}/10`\n"
                if sell_score >= 8:
                    alert += f"📉 Venta fuerte: `{sell_score}/10`\n"
                if btc_price:
                    alert += f"\n₿ BTC: `${btc_price:,.2f}`"

                await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=alert, parse_mode="Markdown")
                last_strong_alert = now

        last_btc_price = btc_price

    except Exception as e:
        print(f"Error: {e}")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.job_queue.run_repeating(send_update, interval=15, first=5)
    print("Bot iniciado correctamente")
    app.run_polling()

if __name__ == "__main__":
    main()