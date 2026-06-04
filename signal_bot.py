import os
import requests
import pandas as pd
import yfinance as yf

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# ~190 of the most liquid S&P names. (Not literally all 503 - the bottom names
# are smaller/less liquid, add rate-limit load, and rarely give cleaner setups.)
SYMBOLS = [
    "AAPL","MSFT","NVDA","AMZN","GOOGL","GOOG","META","TSLA","AVGO","ORCL","CRM","ADBE",
    "AMD","CSCO","ACN","INTC","IBM","QCOM","TXN","INTU","NOW","AMAT","ADI","MU",
    "LRCX","KLAC","SNPS","CDNS","PANW","ANET","CRWD","FTNT","NXPI","MCHP","ON","ROP",
    "APH","MSI","NFLX","DIS","CMCSA","T","VZ","TMUS","PYPL",
    "JPM","BAC","WFC","C","GS","MS","BLK","SCHW","AXP","SPGI","V","MA",
    "COF","USB","PNC","TFC","BK","CB","PGR","MMC","AON","ICE","CME","MCO",
    "UNH","JNJ","LLY","ABBV","MRK","PFE","TMO","ABT","DHR","BMY","AMGN","MDT",
    "ISRG","GILD","VRTX","REGN","CVS","CI","ELV","ZTS","BSX","SYK","HCA","BDX",
    "HD","MCD","NKE","LOW","SBUX","TJX","BKNG","CMG","ORLY","AZO","ROST","MAR",
    "HLT","GM","F","WMT","COST","PG","KO","PEP","PM","MO","MDLZ","CL",
    "KMB","GIS","TGT","DG","DLTR","KHC","MNST","KDP",
    "BA","CAT","HON","GE","UPS","RTX","LMT","DE","UNP","GD","NOC","EMR",
    "ETN","ITW","CSX","NSC","FDX","MMM","PH","GEV",
    "XOM","CVX","COP","SLB","EOG","MPC","PSX","VLO","OXY","WMB","KMI",
    "NEE","DUK","SO","LIN","APD","SHW","FCX","NEM","PLD","AMT","EQIX","CCI",
]

# --- Strategy dials (tune any of these, one number at a time) ---
LEFT_K = 20            # swing significance
RIGHT_K = 3
ENTRY_MIN_PCT = 3.0    # price must be 3-8% above the recent higher low
ENTRY_MAX_PCT = 8.0
NEAR_SUPPORT_PCT = 6.0 # price must be within this % above the support line (tight pullback)
RECENT_LOW_MAX_BARS = 40  # the bounce low must be recent (a fresh pullback, not a stale one)
VOL_MULT = 1.0         # bounce-day volume must beat the 20-day average by this multiple
STOP_PCT = 4.0
CHUNK = 50             # download this many tickers at a time


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


def trendline(pivots, x):
    """Returns (value_at_x, slope) for the least-squares line through the last 3 pivots."""
    pts = pivots[-3:]
    n = len(pts)
    if n < 2:
        return pts[-1][1], 0.0
    sx = sum(p[0] for p in pts); sy = sum(p[1] for p in pts)
    sxx = sum(p[0] * p[0] for p in pts); sxy = sum(p[0] * p[1] for p in pts)
    denom = n * sxx - sx * sx
    if denom == 0:
        return pts[-1][1], 0.0
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return slope * x + intercept, slope


def evaluate(highs, lows, closes, vols):
    if len(closes) < LEFT_K + RIGHT_K + 5:
        return None
    price = float(closes[-1]); x = len(closes) - 1
    swing_highs, swing_lows = find_pivots(highs, lows, LEFT_K, RIGHT_K)
    if len(swing_lows) < 2 or len(swing_highs) < 2:
        return None
    low_prev, low_last = swing_lows[-2], swing_lows[-1]
    high_prev, high_last = swing_highs[-2], swing_highs[-1]
    support, sup_slope = trendline(swing_lows, x)
    resistance, _ = trendline(swing_highs, x)

    higher_highs = (high_last[1] > high_prev[1]) or (price > high_last[1])
    is_uptrend = higher_highs and sup_slope > 0                      # stronger-trend filter
    low_bars_ago = x - low_last[0]
    coming_off_recent_low = (low_last[0] > high_last[0]) and (low_bars_ago <= RECENT_LOW_MAX_BARS)
    near_support = support <= price <= support * (1 + NEAR_SUPPORT_PCT / 100)   # tight pullback
    pct = (price - low_last[1]) / low_last[1] * 100
    in_zone = ENTRY_MIN_PCT <= pct <= ENTRY_MAX_PCT
    turning_up = closes[-1] > closes[-2]
    avg_vol = sum(vols[-20:]) / 20.0
    volume_ok = avg_vol > 0 and vols[-1] > VOL_MULT * avg_vol         # volume confirmation

    pulled_back = is_uptrend and coming_off_recent_low and near_support and in_zone and price < resistance
    fires = pulled_back and turning_up and volume_ok
    return dict(price=price, pct=pct, is_uptrend=is_uptrend, pulled_back=pulled_back,
                fires=fires, resistance=resistance, stop=price * (1 - STOP_PCT / 100))


def get_ohlcv(data, sym):
    try:
        sub = data[sym] if isinstance(data.columns, pd.MultiIndex) else data
        sub = sub[["High", "Low", "Close", "Volume"]].dropna()
        if len(sub) == 0:
            return None
        return (sub["High"].tolist(), sub["Low"].tolist(),
                sub["Close"].tolist(), sub["Volume"].tolist())
    except Exception:
        return None


def main():
    print(f"Scanning {len(SYMBOLS)} stocks...")
    scanned = uptrends = pulled = 0
    hits = []
    watchlist = []

    for i in range(0, len(SYMBOLS), CHUNK):
        chunk = SYMBOLS[i:i + CHUNK]
        try:
            data = yf.download(chunk, period="1y", interval="1d", group_by="ticker",
                               auto_adjust=True, progress=False, threads=True)
        except Exception as e:
            print(f"Chunk download failed ({e}); skipping {len(chunk)} tickers.")
            continue
        for sym in chunk:
            ohlcv = get_ohlcv(data, sym)
            if ohlcv is None:
                continue
            r = evaluate(*ohlcv)
            if r is None:
                continue
            scanned += 1
            if r["is_uptrend"]:
                uptrends += 1
            if r["pulled_back"]:
                pulled += 1
                if not r["fires"]:
                    watchlist.append((sym, r["pct"]))
            if r["fires"]:
                hits.append((sym, r))

    print(f"\nFUNNEL: scanned {scanned} | uptrends {uptrends} | pulled back {pulled} | BUY setups {len(hits)}")

    if hits:
        for sym, r in hits:
            print(f"  BUY {sym}: ${r['price']:.2f}  stop ${r['stop']:.2f}  target ${r['resistance']:.2f}")
    if watchlist:
        print("\nWatchlist (pulled back, awaiting confirmation):")
        for sym, pct in watchlist[:10]:
            print(f"  {sym}: {pct:.1f}% off low")

    if hits:
        lines = [f"\U0001F6A8 {len(hits)} BUY setup(s) today:\n"]
        for sym, r in hits:
            lines.append(f"{sym}: ${r['price']:.2f}  | stop ${r['stop']:.2f}  | target ${r['resistance']:.2f}")
        lines.append("\nSet stop + take-profit in Plus500.")
        send_telegram_message("\n".join(lines))
        print("\nSummary message sent.")
    else:
        print("\nNo buy setups across the universe today.")
