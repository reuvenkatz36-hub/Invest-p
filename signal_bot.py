import os
import requests
import yfinance as yf

# --- Secrets (set in GitHub repo Secrets, not here) ---
TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SYMBOL = os.environ.get("SYMBOL", "AAPL")

# --- Strategy dials (tune these after you see real signals) ---
PIVOT_K = 5            # swing sensitivity: lower = more (noisier) pivots
ENTRY_MIN_PCT = 3.0    # buy only when price is >= this % above the last higher low
ENTRY_MAX_PCT = 8.0    # ...and <= this % (so you don't chase a move that already ran)
STOP_PCT = 4.0         # stop loss, % below entry


def send_telegram_message(message: str) -> None:
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": CHAT_ID, "text": message}, timeout=10)
        if not resp.ok:
            print(f"Telegram API error {resp.status_code}: {resp.text}")
    except requests.RequestException as e:
        print(f"Error sending Telegram message: {e}")


def find_pivots(highs, lows, k):
    """Return swing highs and lows as lists of (position, price)."""
    swing_highs, swing_lows = [], []
    n = len(highs)
    for i in range(k, n - k):
        if highs[i] == max(highs[i - k:i + k + 1]):
            swing_highs.append((i, highs[i]))
        if lows[i] == min(lows[i - k:i + k + 1]):
            swing_lows.append((i, lows[i]))
    return swing_highs, swing_lows


def line_value_at(p1, p2, x):
    """Value of the straight line through p1 and p2, at position x."""
    (x1, y1), (x2, y2) = p1, p2
    if x2 == x1:
        return y2
    slope = (y2 - y1) / (x2 - x1)
    return y1 + slope * (x - x1)


def check_strategy() -> None:
    print(f"Scanning {SYMBOL}...")

    data = yf.download(
        SYMBOL, period="1y", interval="1d",
        auto_adjust=True, multi_level_index=False, progress=False,
    )
    if data is None or len(data) < 2 * PIVOT_K + 5:
        print("Not enough data to scan.")
        return

    highs = data["High"].tolist()
    lows = data["Low"].tolist()
    closes = data["Close"].tolist()
    price = float(closes[-1])
    x_now = len(closes) - 1

    swing_highs, swing_lows = find_pivots(highs, lows, PIVOT_K)
    if len(swing_lows) < 2 or len(swing_highs) < 2:
        print("Not enough swing points yet. Try lowering PIVOT_K.")
        return

    low_prev, low_last = swing_lows[-2], swing_lows[-1]
    high_prev, high_last = swing_highs[-2], swing_highs[-1]

    higher_lows = low_last[1] > low_prev[1]
    higher_highs = high_last[1] > high_prev[1]
    coming_off_low = low_last[0] > high_last[0]   # the higher low is the most recent pivot

    support_now = line_value_at(low_prev, low_last, x_now)
    resistance_now = line_value_at(high_prev, high_last, x_now)

    pct_above_low = (price - low_last[1]) / low_last[1] * 100
    in_entry_zone = ENTRY_MIN_PCT <= pct_above_low <= ENTRY_MAX_PCT
    below_resistance = price < resistance_now

    # Diagnostics so you can see WHY it fired or didn't, and tune the dials.
    print(f"Price now: {price:.2f}")
    print(f"Higher lows:  {higher_lows}  ({low_prev[1]:.2f} -> {low_last[1]:.2f})")
    print(f"Higher highs: {higher_highs}  ({high_prev[1]:.2f} -> {high_last[1]:.2f})")
    print(f"Coming off the higher low: {coming_off_low}")
    print(f"% above last higher low: {pct_above_low:.1f}%  (need {ENTRY_MIN_PCT}-{ENTRY_MAX_PCT}%)")
    print(f"Support ~{support_now:.2f} | Resistance ~{resistance_now:.2f}")

    if higher_lows and higher_highs and coming_off_low and in_entry_zone and below_resistance:
        entry = price
        stop = entry * (1 - STOP_PCT / 100)
        target = resistance_now
        send_telegram_message(
            f"\U0001F6A8 BUY SETUP: {SYMBOL}\n"
            f"Price now: ${entry:.2f}\n"
            f"Rising lows + rising highs, {pct_above_low:.1f}% off the last higher low.\n\n"
            f"Set these in Plus500:\n"
            f"\u2022 Stop loss: ${stop:.2f}  (-{STOP_PCT:.0f}%)\n"
            f"\u2022 Take-profit / sell 60%: ${target:.2f}  (upper trendline - rises over time)"
        )
        print("BUY signal sent.")
    else:
        print("No buy setup today. (This is normal most days.)")


if __name__ == "__main__":
    check_strategy()
