import os
from collections import deque
from datetime import datetime
from dotenv import load_dotenv
from kalshi_python_sync import Configuration, KalshiClient
from telegram.ext import Application, ContextTypes
import httpx
import asyncio

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

raw_key = os.getenv("KALSHI_PRIVATE_KEY_PEM", "")
clean_key = raw_key.replace('\r\n', '\n').replace('\r', '\n').strip()

config = Configuration(host="https://external-api.kalshi.com/trade-api/v2")
config.api_key_id = os.getenv("KALSHI_KEY_ID")
config.private_key_pem = clean_key
kalshi = KalshiClient(config)

price_history = deque(maxlen=40)
last_strong_alert = None

async def get_btc_price_async():
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
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

def get_momentum():
    if len(price_history) < 8:
        return 0

    prices = [p[1] for p in price_history]
    
    # Short momentum (last ~40-50 seconds)
    short_recent = prices[-3:]
    short_older = prices[-6:-3]
    short_mom = ((sum(short_recent)/3) - (sum(short_older)/3)) / (sum(short_older)/3) * 100

    # Medium momentum (last ~1.5-2 min)
    med_recent = prices[-5:]
    med_older = prices[-10:-5]
    med_mom = ((sum(med_recent)/5) - (sum(med_older)/5)) / (sum(med_older)/5) * 100

    # Combined
    return (short_mom * 0.6) + (med_mom * 0.4)

async def send_update(context: ContextTypes.DEFAULT_TYPE):
    global last_strong_alert

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

        momentum = get_momentum()

        first = markets.markets[0] if markets and markets.markets else None
        mid = 0.5
        if first:
            mid = (float(first.yes_bid_dollars or 0) + float(first.yes_ask_dollars or 0)) / 2

        # === Much stricter scoring ===
        up_score = 5
        down_score = 5

        # Momentum (more weight)
        if momentum > 0.18:
            up_score += 3
        elif momentum > 0.09:
            up_score += 2
        elif momentum > 0.04:
            up_score += 1
        elif momentum < -0.18:
            down_score += 3
        elif momentum < -0.09:
            down_score += 2
        elif momentum < -0.04:
            down_score += 1

        # Market odds (only help if not extreme)
        if 0.52 < mid < 0.68:
            if mid > 0.58:
                up_score += 1
            elif mid < 0.42:
                down_score += 1

        up_score = min(up_score, 10)
        down_score = min(down_score, 10)

        # Normal message
        msg = ""
        if btc_price:
            msg += f"₿ BTC: `${btc_price:,.2f}`\n"
            msg += f"Momentum: `{momentum:+.2f}%`\n\n"

        msg += f"ARRIBA: `{up_score}/10` | ABAJO: `{down_score}/10`\n\n"
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

        # === Strong signal (much harder to trigger) ===
        now = datetime.now()
        
        # Only fire if score is high AND momentum is meaningful AND odds aren't already extreme
        strong_up = (
            up_score >= 8 and 
            up_score >= down_score + 2 and 
            momentum > 0.08 and
            mid < 0.70
        )
        
        strong_down = (
            down_score >= 8 and 
            down_score >= up_score + 2 and 
            momentum < -0.08 and
            mid > 0.30
        )

        if (strong_up or strong_down) and (last_strong_alert is None or (now - last_strong_alert).seconds > 180):
            if strong_up:
                alert = f"🔥 *SEÑAL FUERTE: ARRIBA*\n\nPuntuación: `{up_score}/10`\nMomentum: `{momentum:+.2f}%`"
            else:
                alert = f"🔥 *SEÑAL FUERTE: ABAJO*\n\nPuntuación: `{down_score}/10`\nMomentum: `{momentum:+.2f}%`"

            if btc_price:
                alert += f"\n₿ `${btc_price:,.2f}`"

            await context.bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=alert,
                parse_mode="Markdown"
            )
            last_strong_alert = now

    except Exception as e:
        print(f"Error en send_update: {e}")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.job_queue.run_repeating(send_update, interval=12, first=5)
    print("Bot iniciado correctamente")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()