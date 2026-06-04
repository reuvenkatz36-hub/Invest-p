import os
import requests
import yfinance as yf

# --- Secrets (set in GitHub repo Secrets) ---
TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SYMBOL = os.environ.get("SYMBOL", "AAPL")

# --- Strategy dials (tune after seeing real signals) ---
LEFT_K = 20        # how dominant a swing must be vs bars to its left (higher = bigger swings only)
RIGHT_K = 3        # bars to the right (small, so recent swings still register)
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
    """Swing highs/lows as (position, price). Asymmetric window so recent swings register."""
    swing_highs, swing_lows = [], []
    n = len(highs)
    for i in range(left_k, n - right_k):
        if highs[i] == max(highs[i - left_k:i + right_k + 1]):
            swing_highs.append((i, highs[i]))
        if lows[i] == min(lows[i - left_k:i + right_k + 1]):
            swing_lows.append((i, lows[i]))
    return swing_highs, swing_lows


def trendline_value(pivots, x):
    """Least-squares line through the last 3 pivots, evaluated at position x."""
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


def check_strategy() -> None:
    print(f"Scanning {SYMBOL}...")

    data = yf.download(
        SYMBOL, period="1y", interval="1d",
        auto_adjust=True, multi_level_index=False, progress=False,
    )
    if data is None or len(data) < LEFT_K + RIGHT_K + 5:
        print("Not enough data to scan.")
        return

    highs = data["High"].tolist()
    lows = data["Low"].tolist()
    closes = data["Close"].tolist()
    price = float(closes[-1])
    x_now = len(closes) - 1

    swing_highs, swing_lows = find_pivots(highs, lows, LEFT_K, RIGHT_K)
    if len(swing_lows) < 2 or len(swing_highs) < 2:
        print(f"Not enough swing points (highs={len(swing_highs)}, lows={len(swing_lows)}). Lower LEFT_K.")
        return

    low_prev, low_last = swing_lows[-2], swing_lows[-1]
    high_prev, high_last = swing_highs[-2], swing_highs[-1]

    higher_lows = low_last[1] > low_prev[1]
    higher_highs = (high_last[1] > high_prev[1]) or (price > high_last[1])  # breakout counts
    coming_off_low = low_last[0] > high_last[0]

    support = trendline_value(swing_lows, x_now)
    resistance = trendline_value(swing_highs, x_now)
    pct_above_low = (price - low_last[1]) / low_last[1] * 100
    in_entry_zone = ENTRY_MIN_PCT <= pct_above_low <= ENTRY_MAX_PCT
    below_resistance = price < resistance

    # Diagnostics
    print(f"Price now: {price:.2f}")
    print(f"Last 3 swing highs: {[(i, round(v, 2)) for i, v in swing_highs[-3:]]}")
    print(f"Last 3 swing lows:  {[(i, round(v, 2)) for i, v in swing_lows[-3:]]}")
    print(f"Higher lows: {higher_lows}   Higher highs: {higher_highs}")
    print(f"Coming off the higher low: {coming_off_low}")
    print(f"% above last higher low: {pct_above_low:.1f}%  (need {ENTRY_MIN_PCT}-{ENTRY_MAX_PCT}%)")
    print(f"Support ~{support:.2f}  |  Resistance ~{resistance:.2f}")

    if higher_lows and higher_highs and coming_off_low and in_entry_zone and below_resistance:
        entry = price
        stop = entry * (1 - STOP_PCT / 100)
        target = resistance
        send_telegram_message(
            f"\U0001F6A8 BUY SETUP: {SYMBOL}\n"
            f"Price now: ${entry:.2f}\n"
            f"Rising lows + rising highs, {pct_above_low:.1f}% off the last higher low.\n\n"
            f"Set in Plus500:\n"
            f"\u2022 Stop loss: ${stop:.2f}  (-{STOP_PCT:.0f}%)\n"
            f"\u2022 Sell 60% / take-profit: ${target:.2f}  (upper trendline)"
        )
        print("BUY signal sent.")
    else:
        print("No buy setup today. (Normal most days.)")


if __name__ == "__main__":
    check_strategy()
