import os
from collections import deque
from datetime import datetime
from dotenv import load_dotenv
from kalshi_python_sync import Configuration, KalshiClient
from telegram.ext import Application, ContextTypes
import httpx
import asyncio
import statistics

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

raw_key = os.getenv("KALSHI_PRIVATE_KEY_PEM", "")
clean_key = raw_key.replace('\r\n', '\n').replace('\r', '\n').strip()

config = Configuration(host="https://external-api.kalshi.com/trade-api/v2")
config.api_key_id = os.getenv("KALSHI_KEY_ID")
config.private_key_pem = clean_key
kalshi = KalshiClient(config)

price_history = deque(maxlen=60)
last_strong_alert = None
last_lotto_alert = None

async def get_btc_price_async():
    try:
        async with httpx.AsyncClient(timeout=7.0) as client:
            r = await client.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT")
            if r.status_code != 200:
                return None
            data = r.json()
            if "price" not in data:
                return None
            return float(data["price"])
    except Exception as e:
        print(f"Error Binance: {e}")
        return None

def get_momentum_and_vol():
    if len(price_history) < 5:
        return 0.0, 0.0

    prices = [p[1] for p in price_history]

    short = ((prices[-1] - prices[-2]) / prices[-2]) * 100 if len(prices) >= 2 else 0
    medium = ((prices[-1] - prices[-4]) / prices[-4]) * 100 if len(prices) >= 4 else 0
    momentum = (short * 0.65) + (medium * 0.35)

    returns = []
    for i in range(1, min(7, len(prices))):
        ret = ((prices[-i] - prices[-i-1]) / prices[-i-1]) * 100
        returns.append(ret)

    vol = statistics.stdev(returns) if len(returns) > 2 else 0.0
    return momentum, vol

async def send_update(context: ContextTypes.DEFAULT_TYPE):
    global last_strong_alert, last_lotto_alert

    try:
        markets = await asyncio.to_thread(
            kalshi.get_markets,
            series_ticker="KXBTC15M",
            status="open",
            limit=3
        )

        btc_price = await get_btc_price_async()
        if btc_price:
            price_history.append((datetime.now(), btc_price))

        momentum, vol = get_momentum_and_vol()

        first = markets.markets[0] if markets and markets.markets else None
        mid = 0.50
        if first:
            mid = (float(first.yes_bid_dollars or 0) + float(first.yes_ask_dollars or 0)) / 2

        # === Model Probability (improved) ===
        model_up = 0.50 + (momentum * 3.2)
        model_up = max(0.12, min(0.88, model_up))
        model_down = 1.0 - model_up

        edge_up = model_up - mid
        edge_down = model_down - (1.0 - mid)

        # === Scoring ===
        up_score = 5
        down_score = 5

        if momentum > 0.15:
            up_score += 3
        elif momentum > 0.07:
            up_score += 2
        elif momentum > 0.03:
            up_score += 1
        elif momentum < -0.15:
            down_score += 3
        elif momentum < -0.07:
            down_score += 2
        elif momentum < -0.03:
            down_score += 1

        if mid > 0.58:
            up_score += 1
        elif mid < 0.42:
            down_score += 1

        up_score = min(up_score, 10)
        down_score = min(down_score, 10)

        # === Normal Message ===
        msg = ""
        if btc_price:
            msg += f"₿ BTC: `${btc_price:,.2f}`\n"
            msg += f"Momentum: `{momentum:+.2f}%` | Vol: `{vol:.2f}`\n\n"

        msg += f"ARRIBA: `{up_score}/10` | ABAJO: `{down_score}/10`\n"
        msg += f"Model: `{model_up*100:.0f}%` UP | Kalshi: `{mid*100:.0f}%`\n\n"
        msg += "*Mercados BTC 15min:*\n"

        if markets and markets.markets:
            for m in markets.markets:
                yes_bid = float(m.yes_bid_dollars or 0)
                yes_ask = float(m.yes_ask_dollars or 0)
                m_mid = (yes_bid + yes_ask) / 2 if (yes_bid + yes_ask) > 0 else 0
                up = round(m_mid * 100)
                down = 100 - up
                lock = " 🔒" if up >= 72 or down >= 72 else ""
                msg += f"• ARRIBA {up}% | ABAJO {down}%{lock}\n"
        else:
            msg += "No hay mercados abiertos\n"

        await context.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=msg,
            parse_mode="Markdown"
        )

        now = datetime.now()

        # === STRONG SIGNAL ===
        strong_up = (
            up_score >= 8 and
            up_score >= down_score + 2 and
            momentum > 0.08 and
            mid < 0.64
        )
        strong_down = (
            down_score >= 8 and
            down_score >= up_score + 2 and
            momentum < -0.08 and
            mid > 0.36
        )

        if (strong_up or strong_down) and (last_strong_alert is None or (now - last_strong_alert).seconds > 140):
            if strong_up:
                alert = (
                    f"🟢🟢 *BUY / ARRIBA* 🟢🟢\n\n"
                    f"Score: `{up_score}/10`\n"
                    f"Momentum: `{momentum:+.2f}%`\n"
                    f"Model: `{model_up*100:.0f}%`"
                )
            else:
                alert = (
                    f"🔴🔴 *SELL / ABAJO* 🔴🔴\n\n"
                    f"Score: `{down_score}/10`\n"
                    f"Momentum: `{momentum:+.2f}%`\n"
                    f"Model: `{model_down*100:.0f}%`"
                )

            if btc_price:
                alert += f"\n₿ `${btc_price:,.2f}`"

            await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=alert, parse_mode="Markdown")
            last_strong_alert = now

        # === LOTTO ===
        if last_lotto_alert is None or (now - last_lotto_alert).seconds > 90:
            if edge_up >= 0.11 and model_up >= 0.60 and mid < 0.61:
                lotto = (
                    f"🎰 *LOTTO ARRIBA*\n\n"
                    f"Model: `{model_up*100:.0f}%`\n"
                    f"Kalshi: `{mid*100:.0f}%`\n"
                    f"Edge: `+{edge_up*100:.1f}%`\n"
                    f"Momentum: `{momentum:+.2f}%`"
                )
                if btc_price:
                    lotto += f"\n₿ `${btc_price:,.2f}`"
                await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=lotto, parse_mode="Markdown")
                last_lotto_alert = now

            elif edge_down >= 0.11 and model_down >= 0.60 and mid > 0.39:
                lotto = (
                    f"🎰 *LOTTO ABAJO*\n\n"
                    f"Model: `{model_down*100:.0f}%`\n"
                    f"Kalshi: `{(1-mid)*100:.0f}%`\n"
                    f"Edge: `+{edge_down*100:.1f}%`\n"
                    f"Momentum: `{momentum:+.2f}%`"
                )
                if btc_price:
                    lotto += f"\n₿ `${btc_price:,.2f}`"
                await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=lotto, parse_mode="Markdown")
                last_lotto_alert = now

    except Exception as e:
        print(f"Error en send_update: {e}")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.job_queue.run_repeating(send_update, interval=10, first=5)
    print("Bot improved")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()