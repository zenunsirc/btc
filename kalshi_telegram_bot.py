import os
from collections import deque
from datetime import datetime, timedelta
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

price_history = deque(maxlen=150)

async def get_btc_price_async():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT")
            return float(r.json()["price"])
    except:
        return None

def get_timeframe_bias(current_price, minutes_ago):
    if not price_history:
        return "Neutral", "➖"
    cutoff = datetime.now() - timedelta(minutes=minutes_ago)
    past_prices = [p for ts, p in price_history if ts <= cutoff]
    if not past_prices:
        return "Neutral", "➖"
    past_price = past_prices[-1]
    change = ((current_price - past_price) / past_price) * 100

    if change >= 0.25:
        return "Arriba", "📈"
    elif change <= -0.25:
        return "Bajo", "📉"
    else:
        return "Neutral", "➖"

async def send_update(context: ContextTypes.DEFAULT_TYPE):
    try:
        markets = kalshi.get_markets(series_ticker="KXBTC15M", status="open", limit=8)
        btc_price = await get_btc_price_async()

        if btc_price:
            price_history.append((datetime.now(), btc_price))

        bias_1m, emoji_1m   = get_timeframe_bias(btc_price, 1) if btc_price else ("Neutral", "➖")
        bias_5m, emoji_5m   = get_timeframe_bias(btc_price, 5) if btc_price else ("Neutral", "➖")
        bias_10m, emoji_10m = get_timeframe_bias(btc_price, 10) if btc_price else ("Neutral", "➖")
        bias_15m, emoji_15m = get_timeframe_bias(btc_price, 15) if btc_price else ("Neutral", "➖")

        bullish_count = sum(b == "Arriba" for b in [bias_1m, bias_5m, bias_10m, bias_15m])
        bearish_count = sum(b == "Bajo" for b in [bias_1m, bias_5m, bias_10m, bias_15m])

        buy_score = min(10, 4 + bullish_count * 1.5)
        sell_score = min(10, 4 + bearish_count * 1.5)

        strong_label = ""
        if buy_score >= 8:
            strong_label = " 🔥 Fuerte"
        elif sell_score >= 8:
            strong_label = " 🔥 Fuerte"

        msg = "✅ *Kalshi BTC 15m*\n\n"
        if btc_price:
            msg += f"₿ BTC: `${btc_price:,.2f}`\n"
        msg += f"1m: {emoji_1m} *{bias_1m}*\n"
        msg += f"5m: {emoji_5m} *{bias_5m}*\n"
        msg += f"10m: {emoji_10m} *{bias_10m}*\n"
        msg += f"15m: {emoji_15m} *{bias_15m}*{strong_label}\n\n"
        msg += f"Puntuación de Compra: `{int(buy_score)}/10`\n"
        msg += f"Puntuación de Venta: `{int(sell_score)}/10`\n\n"
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

    except Exception as e:
        print(f"Error: {e}")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.job_queue.run_repeating(send_update, interval=20, first=5)
    print("Bot iniciado correctamente")
    app.run_polling()

if __name__ == "__main__":
    main()