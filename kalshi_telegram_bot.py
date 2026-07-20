import os
import time
import requests
import asyncio
from dotenv import load_dotenv
from kalshi_python_sync import Configuration, KalshiClient
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

KALSHI_KEY_ID = os.getenv("KALSHI_KEY_ID")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Kalshi setup
raw_key = os.getenv("KALSHI_PRIVATE_KEY_PEM", "")
clean_key = raw_key.replace('\r\n', '\n').replace('\r', '\n').strip()

config = Configuration(host="https://external-api.kalshi.com/trade-api/v2")
config.api_key_id = KALSHI_KEY_ID
config.private_key_pem = clean_key
kalshi = KalshiClient(config)

def get_btc_price():
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=5)
        return float(r.json()["price"])
    except:
        return None

async def send_monitoring_update(app):
    while True:
        try:
            balance = kalshi.get_balance()
            markets = kalshi.get_markets(series_ticker="KXBTC15M", status="open", limit=8)
            btc_price = get_btc_price()

            first = markets.markets[0] if markets.markets else None
            bias = "Neutral"
            if first:
                mid = (float(first.yes_bid_dollars or 0) + float(first.yes_ask_dollars or 0)) / 2
                bias = "Bullish" if mid > 0.5 else "Bearish"

            msg = "✅ *Kalshi BTC 15m Bot*\n\n"
            msg += f"💰 Balance: `${balance.balance / 100:.2f}`\n"
            if btc_price:
                msg += f"₿ BTC: `${btc_price:,.2f}`\n"
            msg += f"📊 Bias: *{bias}*\n\n"
            msg += "*BTC 15min Markets:*\n"

            for m in markets.markets:
                yes_bid = float(m.yes_bid_dollars or 0)
                yes_ask = float(m.yes_ask_dollars or 0)
                mid = (yes_bid + yes_ask) / 2 if (yes_bid + yes_ask) > 0 else 0
                up_pct = round(mid * 100)
                down_pct = 100 - up_pct
                lock = " 🔒💵" if up_pct >= 70 or down_pct >= 70 else ""

                msg += f"• Up · {up_pct}% | Down · {down_pct}%{lock}\n"

            await app.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode="Markdown")

        except Exception as e:
            print(f"Monitoring error: {e}")

        await asyncio.sleep(60)

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        ticker, count = context.args[0], int(context.args[1])
        market = kalshi.get_market(ticker=ticker)
        price = float(market.yes_ask_dollars or market.yes_bid_dollars)

        order = kalshi.create_order(
            ticker=ticker, action="buy", side="yes", count=count,
            yes_price=int(price * 100), type="limit", time_in_force="good_till_canceled"
        )
        await update.message.reply_text(f"✅ Buy order placed! ID: {order.order_id}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        ticker, count = context.args[0], int(context.args[1])
        market = kalshi.get_market(ticker=ticker)
        price = float(market.yes_bid_dollars or market.yes_ask_dollars)

        order = kalshi.create_order(
            ticker=ticker, action="sell", side="yes", count=count,
            yes_price=int(price * 100), type="limit", time_in_force="good_till_canceled"
        )
        await update.message.reply_text(f"✅ Sell order placed! ID: {order.order_id}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bal = kalshi.get_balance()
    await update.message.reply_text(f"💰 Balance: ${bal.balance / 100:.2f}")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("sell", sell))
    app.add_handler(CommandHandler("balance", balance_cmd))

    # Start monitoring in background
    asyncio.create_task(send_monitoring_update(app))

    print("Bot running with monitoring + commands...")
    app.run_polling()

if __name__ == "__main__":
    main()