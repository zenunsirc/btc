import os
from collections import deque
from datetime import datetime, timedelta
from dotenv import load_dotenv
from kalshi_python_sync import Configuration, KalshiClient
from telegram.ext import Application, ContextTypes
import httpx

load_dotenv()

KALSHI_KEY_ID = os.getenv("KALSHI_KEY_ID")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

raw_key = os.getenv("KALSHI_PRIVATE_KEY_PEM", "")
clean_key = raw_key.replace('\r\n', '\n').replace('\r', '\n').strip()

config = Configuration(host="https://external-api.kalshi.com/trade-api/v2")
config.api_key_id = KALSHI_KEY_ID
config.private_key_pem = clean_key
kalshi = KalshiClient(config)

# Store price history: (timestamp, price)
price_history = deque(maxlen=100)  # Keep last ~100 data points

async def get_btc_price_async():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT")
            return float(r.json()["price"])
    except:
        return None

def get_bias(current_price, minutes_ago):
    """Calculate bias for a specific timeframe"""
    if not price_history:
        return "Neutral"
    
    cutoff_time = datetime.now() - timedelta(minutes=minutes_ago)
    
    # Find the closest price from X minutes ago
    past_price = None
    for ts, price in reversed(price_history):
        if ts <= cutoff_time:
            past_price = price
            break
    
    if past_price is None:
        return "Neutral"
    
    change = ((current_price - past_price) / past_price) * 100
    
    if change > 0.25:
        return "Bullish"
    elif change < -0.25:
        return "Bearish"
    else:
        return "Neutral"

async def send_update(context: ContextTypes.DEFAULT_TYPE):
    global price_history
    
    try:
        balance = kalshi.get_balance()
        markets = kalshi.get_markets(series_ticker="KXBTC15M", status="open", limit=8)
        btc_price = await get_btc_price_async()

        if btc_price is None:
            return

        # Save price to history
        price_history.append((datetime.now(), btc_price))

        # === Multi-timeframe Bias ===
        bias_1m  = get_bias(btc_price, 1)
        bias_5m  = get_bias(btc_price, 5)
        bias_10m = get_bias(btc_price, 10)
        bias_15m = get_bias(btc_price, 15)

        # === Calculate Buy/Sell Score (1-10) ===
        bullish_count = sum(1 for b in [bias_1m, bias_5m, bias_10m, bias_15m] if b == "Bullish")
        bearish_count = sum(1 for b in [bias_1m, bias_5m, bias_10m, bias_15m] if b == "Bearish")

        buy_score = min(10, 4 + bullish_count * 1.5)
        sell_score = min(10, 4 + bearish_count * 1.5)

        # Kalshi bias
        first = markets.markets[0] if markets.markets else None
        kalshi_bias = "Neutral"
        if first:
            mid = (float(first.yes_bid_dollars or 0) + float(first.yes_ask_dollars or 0)) / 2
            kalshi_bias = "Bullish" if mid > 0.55 else "Bearish" if mid < 0.45 else "Neutral"

        # Final combined bias
        final_bias = "Bullish" if buy_score > sell_score else "Bearish" if sell_score > buy_score else "Neutral"

        # Build message
        msg = "✅ *Kalshi BTC 15m Scalp Dashboard*\n\n"
        msg += f"₿ BTC: `${btc_price:,.2f}`\n"
        msg += f"1m Bias: *{bias_1m}*   |   5m Bias: *{bias_5m}*\n"
        msg += f"10m Bias: *{bias_10m}* |   15m Bias: *{bias_15m}*\n\n"
        msg += f"🎯 Buy Score: `{int(buy_score)}/10`   Sell Score: `{int(sell_score)}/10`\n"
        msg += f"📊 Overall Bias: *{final_bias}*\n\n"
        msg += f"💰 Balance: `${balance.balance / 100:.2f}`\n\n"
        msg += "*BTC 15min Markets:*\n"

        for m in markets.markets:
            yes_bid = float(m.yes_bid_dollars or 0)
            yes_ask = float(m.yes_ask_dollars or 0)
            mid = (yes_bid + yes_ask) / 2 if (yes_bid + yes_ask) > 0 else 0
            up_pct = round(mid * 100)
            down_pct = 100 - up_pct
            lock = " 🔒💵" if up_pct >= 75 or down_pct >= 75 else ""

            msg += f"• Up · {up_pct}% | Down · {down_pct}%{lock}\n"

        await context.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=msg,
            parse_mode="Markdown"
        )

    except Exception as e:
        print(f"Update error: {e}")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Update every 60 seconds
    app.job_queue.run_repeating(send_update, interval=60, first=10)

    print("Bot running with multi-timeframe bias + scores!")
    app.run_polling()

if __name__ == "__main__":
    main()