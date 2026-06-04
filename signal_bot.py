"""
SMA Crossover -> Telegram alert bot.
Runs ONCE per invocation on a schedule (GitHub Actions cron).
Secrets come from environment variables, never committed:
  TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, SYMBOL (optional, defaults to AAPL)
"""

import os
import requests
import yfinance as yf

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SYMBOL = os.environ.get("SYMBOL", "AAPL")


def send_telegram_message(message: str) -> None:
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": CHAT_ID, "text": message},
            timeout=10,
        )
        if not resp.ok:
            print(f"Telegram API error {resp.status_code}: {resp.text}")
    except requests.RequestException as e:
        print(f"Error sending Telegram message: {e}")


def check_strategy() -> None:
    print(f"Checking {SYMBOL}...")

    data = yf.download(
        SYMBOL,
        period="60d",
        interval="1d",
        auto_adjust=True,
        multi_level_index=False,  # keep columns flat -> data["Close"] is a Series
        progress=False,
    )

    if data is None or len(data) < 21:
        print("Not enough data to evaluate the 20-day SMA.")
        return

    data["SMA5"] = data["Close"].rolling(window=5).mean()
    data["SMA20"] = data["Close"].rolling(window=20).mean()

    last = data.iloc[-1]
    prev = data.iloc[-2]
    price = float(last["Close"])

    print(f"Close={price:.2f}  SMA5={last['SMA5']:.2f}  SMA20={last['SMA20']:.2f}")

    crossed_up = prev["SMA5"] <= prev["SMA20"] and last["SMA5"] > last["SMA20"]
    crossed_down = prev["SMA5"] >= prev["SMA20"] and last["SMA5"] < last["SMA20"]

    if crossed_up:
        send_telegram_message(
            f"\U0001F6A8 BUY ALERT: {SYMBOL}\n"
            f"Price: ${price:.2f}\n"
            f"5-day SMA crossed ABOVE 20-day SMA (golden cross)."
        )
    elif crossed_down:
        send_telegram_message(
            f"\u26A0\uFE0F SELL ALERT: {SYMBOL}\n"
            f"Price: ${price:.2f}\n"
            f"5-day SMA crossed BELOW 20-day SMA (death cross)."
        )
    else:
        print("No new crossover. Nothing to send.")


if __name__ == "__main__":
    check_strategy()
