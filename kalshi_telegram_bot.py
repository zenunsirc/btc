import os
import time
import requests
from datetime import datetime, timezone

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

POLL_SEC = 7
MIN_SCORE = 8
MIN_SEP = 3
NO_TRADE_FIRST_SEC = 300
NO_TRADE_LAST_SEC = 100
MIN_DEV = 0.04

last_alert_ticker = None
last_alert_side = None
last_window = None


def tg(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(
        url,
        json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=15,
    )


def get_btc():
    r = requests.get(
        "https://data-api.binance.vision/api/v3/klines",
        params={"symbol": "BTCUSDT", "interval": "1m", "limit": 90},
        timeout=10,
    )
    r.raise_for_status()
    rows = r.json()
    closes = [float(x[4]) for x in rows]
    return closes[-1], closes


def get_kalshi():
    r = requests.get(
        "https://api.elections.kalshi.com/trade-api/v2/markets",
        params={"series_ticker": "KXBTC15M", "status": "open", "limit": 12},
        timeout=10,
    )
    r.raise_for_status()
    markets = r.json().get("markets", [])

    def close_ts(m):
        t = m.get("close_time") or m.get("expected_expiration_time") or ""
        try:
            return datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 1e18

    markets = sorted(markets, key=close_ts)
    for m in markets:
        if m.get("floor_strike") or m.get("cap_strike"):
            return m
    return markets[0] if markets else None


def rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(-period, 0):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag = sum(gains) / period
    al = sum(losses) / period
    if al == 0:
        return 100.0
    return 100 - (100 / (1 + ag / al))


def momentum(closes):
    if len(closes) < 25:
        return 0.0, 0.0, 0.0
    last = closes[-1]
    s = (last - closes[-4]) / closes[-4] * 100
    t = (last - closes[-11]) / closes[-11] * 100
    slow = (last - closes[-21]) / closes[-21] * 100
    return s, t, slow


def soft(x):
    return x / (1 + abs(x))


def model_up(spot, target, closes, sec, mid):
    s, t, slow = momentum(closes)
    blended = s * 0.5 + t * 0.35 + slow * 0.15
    r = rsi(closes)
    mins = max(0.5, (sec or 450) / 60.0)

    rets = []
    for i in range(-20, 0):
        if closes[i - 1] > 0:
            rets.append((closes[i] - closes[i - 1]) / closes[i - 1] * 100)
    vol = (sum(x * x for x in rets) / max(len(rets), 1)) ** 0.5 if rets else 0.04
    expected = max(0.025, vol * (mins ** 0.5) * 1.25)

    z = 0.0
    if target and target > 0:
        z = ((spot - target) / target * 100) / expected

    p = 0.5 + 0.28 * soft(z * 1.1)
    p += 0.10 * soft(blended * 14)
    p += 0.04 * soft((r - 50) / 18)

    if sec is not None and sec < 150 and target:
        urg = (1 - sec / 150) ** 1.3
        p += (1 if spot >= target else -1) * urg * 0.22

    if 0.15 < mid < 0.85:
        conv = min(1.0, abs(z) * 0.65) * 0.65 + min(1.0, abs(blended) * 9) * 0.35
        w = (1 - conv) * 0.28
        p = p * (1 - w) + mid * w

    late = sec is not None and sec < 90
    return max(0.15 if late else 0.28, min(0.85 if late else 0.72, p))


def scores(spot, target, closes, mid, model, sec):
    s, t, slow = momentum(closes)
    r = rsi(closes)
    buy = 0
    sell = 0

    if s > 0.14:
        buy += 3
    elif s > 0.07:
        buy += 2
    elif s > 0.03:
        buy += 1
    if s < -0.14:
        sell += 3
    elif s < -0.07:
        sell += 2
    elif s < -0.03:
        sell += 1

    if t > 0.10 or (t > 0.05 and slow > 0):
        buy += 2
    elif t > 0.04:
        buy += 1
    if t < -0.10 or (t < -0.05 and slow < 0):
        sell += 2
    elif t < -0.04:
        sell += 1

    if r > 63:
        buy += 2
    elif r > 55:
        buy += 1
    if r < 37:
        sell += 2
    elif r < 45:
        sell += 1

    if target and target > 0:
        dev = (spot - target) / target * 100
        if dev > 0.10:
            buy += 2
        elif dev > 0.04:
            buy += 1
        if dev < -0.10:
            sell += 2
        elif dev < -0.04:
            sell += 1

    if 0.15 < mid < 0.85:
        if mid > 0.62:
            buy += 2
        elif mid > 0.55:
            buy += 1
        if mid < 0.38:
            sell += 2
        elif mid < 0.45:
            sell += 1

    edge_up = model - mid
    edge_dn = mid - model
    if edge_up > 0.12:
        buy += 2
    elif edge_up > 0.06:
        buy += 1
    if edge_dn > 0.12:
        sell += 2
    elif edge_dn > 0.06:
        sell += 1

    if sec is not None and sec < 100 and target:
        if spot > target * 1.0004:
            buy += 1
        if spot < target * 0.9996:
            sell += 1

    return min(10, buy), min(10, sell)


def mid_from_market(m):
    bid = float(m.get("yes_bid_dollars") or m.get("yes_bid") or 0)
    ask = float(m.get("yes_ask_dollars") or m.get("yes_ask") or 0)
    last = float(m.get("last_price_dollars") or m.get("last_price") or 0)
    if bid > 1.5:
        bid /= 100
    if ask > 1.5:
        ask /= 100
    if last > 1.5:
        last /= 100
    if bid + ask < 0.03:
        return last if 0.08 < last < 0.92 else 0.5
    if bid > 0 and ask > 0:
        return max(0.03, min(0.97, (bid + ask) / 2))
    return max(0.03, min(0.97, last or 0.5))


def seconds_left(m):
    t = m.get("close_time") or m.get("expected_expiration_time")
    if not t:
        return None
    try:
        close = datetime.fromisoformat(t.replace("Z", "+00:00"))
        return max(0, int((close - datetime.now(timezone.utc)).total_seconds()))
    except Exception:
        return None


def decide(spot, target, closes, mid, sec):
    model = model_up(spot, target, closes, sec, mid)
    buy, sell = scores(spot, target, closes, mid, model, sec)

    if sec is not None and sec > 900 - NO_TRADE_FIRST_SEC:
        return None, buy, sell, model, "EARLY"

    if target and target > 0:
        dev = abs((spot - target) / target * 100)
    else:
        dev = 0.0

    if sec is not None and sec < NO_TRADE_LAST_SEC:
        final_up = (
            target
            and spot > target * 1.0004
            and buy >= 8
            and buy >= sell + MIN_SEP
            and model >= 0.58
        )
        final_dn = (
            target
            and spot < target * 0.9996
            and sell >= 8
            and sell >= buy + MIN_SEP
            and model <= 0.42
        )
        if final_up:
            return "LOCK_UP", buy, sell, model, "FINAL LOCK"
        if final_dn:
            return "LOCK_DOWN", buy, sell, model, "FINAL LOCK"
        return None, buy, sell, model, "TOO LATE"

    # hard LOCK only
    lock_up = (
        buy >= MIN_SCORE
        and buy >= sell + MIN_SEP
        and mid < 0.75
        and model >= 0.55
        and dev >= MIN_DEV
        and (momentum(closes)[0] > 0.02 or (target and spot > target))
    )
    lock_dn = (
        sell >= MIN_SCORE
        and sell >= buy + MIN_SEP
        and mid > 0.25
        and model <= 0.45
        and dev >= MIN_DEV
        and (momentum(closes)[0] < -0.02 or (target and spot < target))
    )

    if lock_up:
        return "LOCK_UP", buy, sell, model, "LOCK"
    if lock_dn:
        return "LOCK_DOWN", buy, sell, model, "LOCK"

    return None, buy, sell, model, "WAIT"


def fmt_msg(side, buy, sell, model, mid, spot, target, sec, tag):
    arrow = "ARRIBA 🟢" if "UP" in side else "ABAJO 🔴"
    tl = f"{sec // 60}:{sec % 60:02d}" if sec is not None else "—"
    tgt = f"${target:,.2f}" if target else "—"
    return (
        f"<b>LOCK · {arrow}</b>\n"
        f"Buy <b>{buy}/10</b> · Sell <b>{sell}/10</b>\n"
        f"Model {model * 100:.0f}% · Market {mid * 100:.0f}%\n"
        f"BTC ${spot:,.0f} · Target {tgt}\n"
        f"Time left {tl}\n"
        f"<i>{tag} · size small · one shot this window</i>"
    )


def loop():
    global last_alert_ticker, last_alert_side, last_window
    print("bot online · lock only · stricter")
    while True:
        try:
            spot, closes = get_btc()
            m = get_kalshi()
            if not m:
                time.sleep(POLL_SEC)
                continue

            ticker = m.get("ticker") or ""
            target = m.get("floor_strike") or m.get("cap_strike")
            if target is not None:
                target = float(target)

            mid = mid_from_market(m)
            sec = seconds_left(m)

            if ticker and ticker != last_window:
                last_window = ticker
                last_alert_ticker = None
                last_alert_side = None

            side, buy, sell, model, tag = decide(spot, target, closes, mid, sec)

            if side and not (
                last_alert_ticker == ticker and last_alert_side == side
            ):
                tg(fmt_msg(side, buy, sell, model, mid, spot, target, sec, tag))
                last_alert_ticker = ticker
                last_alert_side = side
                print("alert", side, ticker, f"buy={buy} sell={sell}")

        except Exception as e:
            print("err", e)

        time.sleep(POLL_SEC)


if __name__ == "__main__":
    loop()