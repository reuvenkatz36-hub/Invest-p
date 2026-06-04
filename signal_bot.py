import os
import requests
import yfinance as yf

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Starter universe: liquid large-caps. We expand to the full S&P 500 once this works.
SYMBOLS = [
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AVGO","AMD","NFLX",
    "ADBE","CRM","ORCL","CSCO","INTC","QCOM","TXN","AMAT","MU","PYPL",
    "JPM","BAC","WFC","GS","MS","V","MA",
    "UNH","JNJ","LLY","PFE","MRK","ABBV",
    "WMT","COST","HD","NKE","MCD","SBUX","DIS",
    "XOM","CVX","BA","CAT","GE","KO","PEP",
]

LEFT_K = 20
RIGHT_K = 3
ENTRY_MIN_PCT = 3.0
ENTRY_MAX_PCT = 8.0
STOP_PCT = 4.0


def send_telegram_message(message: str) -> None:
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": CHAT_ID, "text": message}, timeout=10)
        if not resp.ok:
            print(f"Telegram API error {resp.status_code}: {resp.text}")
    except requests.RequestException as e:
        print(f"Error sending Telegram message: {e}")


def find_pivots(highs, lows, left_k, right_k):
    swing_highs, swing_lows = [], []
    n = len(highs)
    for i in range(left_k, n - right_k):
        if highs[i] == max(highs[i - left_k:i + right_k + 1]):
            swing_highs.append((i, highs[i]))
        if lows[i] == min(lows[i - left_k:i + right_k + 1]):
            swing_lows.append((i, lows[i]))
    return swing_highs, swing_lows


def trendline_value(pivots, x):
    pts = pivots[-3:]
    n = len(pts)
    if n < 2:
        return pts[-1][1]
    sx = sum(p[0] for p in pts)
    sy = sum(p[1] for p in pts)
    sxx = sum(p[0] * p[0] for p in pts)
    sxy = sum(p[0] * p[1] for p in pts)
    denom = n * sxx - sx * sx
    if denom == 0:
        return pts[-1][1]
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return slope * x + intercept


def evaluate(highs, lows, closes):
    if len(closes) < LEFT_K + RIGHT_K + 5:
        return None
    price = float(closes[-1])
    x_now = len(closes) - 1
    swing_highs, swing_lows = find_pivots(highs, lows, LEFT_K, RIGHT_K)
    if len(swing_lows) < 2 or len(swing_highs) < 2:
        return None
    low_prev, low_last = swing_lows[-2], swing_lows[-1]
    high_prev, high_last = swing_highs[-2], swing_highs[-1]
    higher_lows = low_last[1] > low_prev[1]
    higher_highs = (high_last[1] > high_prev[1]) or (price > high_last[1])
    coming_off_low = low_last[0] > high_last[0]
    resistance = trendline_value(swing_highs, x_now)
    pct = (price - low_last[1]) / low_last[1] * 100
    in_zone = ENTRY_MIN_PCT <= pct <= ENTRY_MAX_PCT
    fires = higher_lows and higher_highs and coming_off_low and in_zone and price < resistance
    return dict(price=price, higher_lows=higher_lows, higher_highs=higher_highs,
                pct=pct, fires=fires, resistance=resistance,
                stop=price * (1 - STOP_PCT / 100), target=resistance)


def main():
    print(f"Scanning {len(SYMBOLS)} stocks...")
    hits = []
    scanned = 0
    uptrends = 0
    for sym in SYMBOLS:
        try:
            data = yf.download(sym, period="1y", interval="1d",
                               auto_adjust=True, multi_level_index=False, progress=False)
            if data is None or len(data) == 0:
                print(f"{sym}: no data")
                continue
            r = evaluate(data["High"].tolist(), data["Low"].tolist(), data["Close"].tolist())
            if r is None:
                continue
            scanned += 1
            if r["higher_lows"] and r["higher_highs"]:
                uptrends += 1
                tag = "  <-- BUY" if r["fires"] else ""
                print(f"{sym}: uptrend, {r['pct']:.1f}% off low{tag}")
            if r["fires"]:
                hits.append((sym, r))
        except Exception as e:
            print(f"{sym}: error ({e})")

    print(f"\nScanned {scanned} | uptrends {uptrends} | buy setups {len(hits)}")

    if hits:
        lines = [f"\U0001F6A8 {len(hits)} BUY setup(s) today:\n"]
        for sym, r in hits:
            lines.append(f"{sym}: ${r['price']:.2f}  | stop ${r['stop']:.2f}  | target ${r['target']:.2f}")
        lines.append("\nSet stop + take-profit in Plus500.")
        send_telegram_message("\n".join(lines))
        print("Summary message sent.")
    else:
        print("No buy setups across the universe today.")


if __name__ == "__main__":
    main()
