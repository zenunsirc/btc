import os
from dotenv import load_dotenv
from kalshi_python_sync import Configuration, KalshiClient
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

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

def get_main_keyboard():
    keyboard = [
        [InlineKeyboardButton("💰 Balance", callback_data="balance")],
        [InlineKeyboardButton("🔼 Buy", callback_data="buy_menu"),
         InlineKeyboardButton("🔽 Sell", callback_data="sell_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def send_monitoring(context: ContextTypes.DEFAULT_TYPE):
    try:
        balance = kalshi.get_balance()
        markets = kalshi.get_markets(series_ticker="KXBTC15M", status="open", limit=8)

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
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )

    except Exception as e:
        print(f"Monitoring error: {e}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "balance":
        bal = kalshi.get_balance()
        await query.edit_message_text(f"💰 Balance: ${bal.balance / 100:.2f}")

    elif query.data == "buy_menu":
        await query.edit_message_text("Send: /buy TICKER AMOUNT\nExample: /buy KXBTC15M-26JUL200245-45 10")

    elif query.data == "sell_menu":
        await query.edit_message_text("Send: /sell TICKER AMOUNT\nExample: /sell KXBTC15M-26JUL200245-45 5")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CallbackQueryHandler(button_handler))
    app.job_queue.run_repeating(send_monitoring, interval=60, first=10)

    print("Bot running with buttons!")
    app.run_polling()

if __name__ == "__main__":
    main()