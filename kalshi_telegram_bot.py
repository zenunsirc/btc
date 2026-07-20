import os
from dotenv import load_dotenv
from kalshi_python_sync import Configuration, KalshiClient
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

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

current_ticker = None
last_btc_price = None

def get_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("🔼 Buy $10", callback_data="buy_10"),
            InlineKeyboardButton("🔽 Sell All", callback_data="sell_all")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_btc_price():
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=5)
        return float(r.json()["price"])
    except:
        return None

async def send_monitoring(context: ContextTypes.DEFAULT_TYPE):
    global current_ticker
    try:
        balance = kalshi.get_balance()
        markets = kalshi.get_markets(series_ticker="KXBTC15M", status="open", limit=8)

        if markets.markets:
            current_ticker = markets.markets[0].ticker

        msg = "✅ *Kalshi BTC 15m Bot*\n\n"
        msg += f"💰 Balance: `${balance.balance / 100:.2f}`\n\n"
        msg += "*BTC 15min Markets:*\n"

        for m in markets.markets:
            yes_bid = float(m.yes_bid_dollars or 0)
            yes_ask = float(m.yes_ask_dollars or 0)
            mid = (yes_bid + yes_ask) / 2 if (yes_bid + yes_ask) > 0 else 0
            up_pct = round(mid * 100)
            down_pct = 100 - up_pct
            lock = " 🔒💵" if up_pct >= 70 or down_pct >= 70 else ""

            msg += f"• Up · {up_pct}% | Down · {down_pct}%{lock}\n"

        await context.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=msg,
            parse_mode="Markdown"
        )

    except Exception as e:
        print(f"Monitoring error: {e}")

async def price_alerts(context: ContextTypes.DEFAULT_TYPE):
    global last_btc_price
    try:
        price = get_btc_price()
        if price is None:
            return

        if last_btc_price is None:
            last_btc_price = price
            return

        change = ((price - last_btc_price) / last_btc_price) * 100

        if abs(change) >= 0.5:
            direction = "🚀 Up" if change > 0 else "📉 Down"
            msg = f"⚡ *BTC Alert* {direction} **{abs(change):.2f}%**\n"
            msg += f"Price: `${price:,.2f}`"
            await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode="Markdown")

        last_btc_price = price

    except Exception as e:
        print(f"Price alert error: {e}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_ticker
    query = update.callback_query
    await query.answer()

    if not current_ticker:
        await query.edit_message_text("No active market right now.")
        return

    try:
        response = kalshi.get_market(ticker=current_ticker)
        market = response.market
        price = float(market.yes_ask_dollars or market.yes_bid_dollars or 0)

        if query.data == "buy_10":
            order = kalshi.create_order(
                ticker=current_ticker, action="buy", side="yes", count=10,
                yes_price=int(price * 100), type="limit", time_in_force="good_till_canceled"
            )
            await query.edit_message_text(f"✅ Bought $10 worth!\nOrder ID: {order.order_id}")

        elif query.data == "sell_all":
            order = kalshi.create_order(
                ticker=current_ticker, action="sell", side="yes", count=10,
                yes_price=1, type="limit", time_in_force="good_till_canceled"
            )
            await query.edit_message_text(f"✅ Sell order placed!\nOrder ID: {order.order_id}")

    except Exception as e:
        await query.edit_message_text(f"❌ Error: {str(e)}")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CallbackQueryHandler(button_handler))

    # Monitoring every 60 seconds
    app.job_queue.run_repeating(send_monitoring, interval=60, first=10)

    # Real-time price alerts every 15 seconds
    app.job_queue.run_repeating(price_alerts, interval=15, first=5)

    print("Bot is running cleanly!")
    app.run_polling()

if __name__ == "__main__":
    main()