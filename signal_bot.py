import os
import re
import time
import xml.etree.ElementTree as ET
from itertools import zip_longest
from urllib.parse import quote_plus
import requests
import pandas as pd
import yfinance as yf

import xray   # fundamental X-ray + health score (attached to each daily BUY setup)

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/120.0.0.0 Safari/537.36")

# --- Universe: every US-listed stock worth more than $1B market cap ---
MIN_MARKET_CAP = 1_000_000_000
MIN_UNIVERSE = 600        # a healthy live fetch returns ~2,000+; far fewer => treat as incomplete
NASDAQ_SCREENER_URL = "https://api.nasdaq.com/api/screener/stocks"

# --- Fundamental gate + news (only applied to stocks that pass the chart screen) ---
REQUIRE_CONFIRMED_GROWTH = True    # only show names with proven YoY revenue growth
                                   # (drops both declining and unverifiable 'n/a' names)
MIN_SCORE = int(os.environ.get("MIN_SCORE", "8"))   # only suggest stocks with a health score >= this
MAX_ALERTS = int(os.environ.get("MAX_ALERTS", "10"))  # cap the daily alert at the N best clean-sheet names
ERRATIC_WINDOW = 252   # judge "erratic" on the last ~12 months only (an old earnings gap shouldn't blacklist forever)
NEWS_PER_STOCK = 3                 # headlines to attach to each alert

# Fallback universe (curated large caps) used only if the live screener fetch
# fails, so the bot still produces a scan instead of going dark.
FALLBACK_SYMBOLS = [
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
    # --- broader large/mid-cap backup so a failed live fetch still scans wide ---
    "PLTR","SNOW","DDOG","NET","ZS","OKTA","MDB","TEAM","HUBS","TTD","ZM","DOCU","TWLO","U",
    "SHOP","WDAY","ADSK","ANSS","FICO","TYL","PTC","SSNC","FFIV","AKAM","GEN","NTAP","WDC",
    "STX","HPQ","HPE","DELL","SMCI","ZBRA","TRMB","MRVL","SWKS","QRVO","MPWR","ENPH","FSLR",
    "TER","ENTG","ARM","ASML","TSM","UBER","ABNB","DASH","EBAY","ETSY","PINS","SNAP","RBLX",
    "SPOT","ROKU","BABA","JD","PDD","SE","MELI","CPNG","NU","COIN","HOOD","SOFI","AFRM","FIS",
    "FI","GPN","ALLY","RIVN","LCID","STLA","TM","APTV","LEA","BWA","GRMN","DAL","UAL","AAL",
    "LUV","RCL","CCL","NCLH","EXPE","H","DKNG","MGM","LVS","WYNN","CZR","PENN","CHDN","ULTA",
    "DKS","BBY","BURL","FIVE","RH","W","CVNA","KMX","TPR","RL","LULU","DECK","WSM","FND","TSCO",
    "YUM","DPZ","DRI","PWR","URI","PCAR","CMI","DOV","IR","AME","FTV","XYL","GNRC","HUBB","AOS",
    "NDSN","IEX","GGG","WAB","J","ACM","PNR","TT","CARR","OTIS","DXCM","IDXX","ALGN","MTD","WST",
    "RMD","HOLX","PODD","MRNA","BIIB","INCY","WAT","STE","COO","ZBH","BAX","DGX","LH","IQV","A",
    "GEHC","CNC","MOH","HUM","DVN","FANG","HES","CTRA","OVV","EQT","TRGP","OKE","BKR","HAL","NOV",
    "NUE","STLD","CLF","AA","MOS","CF","ALB","NTR","LYB","DOW","DD","PPG","ECL","VMC","MLM","IP",
    "PKG","AVY","BALL","EMN","EL","CLX","CHD","K","HSY","SJM","CAG","HRL","CPB","STZ","TAP","TSN",
    "ADM","BG","KR","SYY","O","SPG","PSA","AVB","EQR","VICI","WELL","DLR","EXR","MAA","ARE","INVH",
    "KIM","REG","BXP","HST","UDR","D","AEP","EXC","XEL","ED","WEC","ES","PEG","PCG","SRE","AEE",
    "CMS","DTE","FE","ETR","PPL","CNP","ATO","NI","WBD","PARA","FOXA","OMC","IPG","LYV","NWSA",
    "TTWO","EA","MTCH","Z","MET","PRU","AIG","ALL","TRV","AFL","HIG","PFG","AMP","RJF","TROW",
    "BEN","IVZ","NDAQ","CBOE","MKTX","FDS","MSCI","BRK-B","KKR","BX","APO","ARES","CG","OWL",
    "SONY","SAP","TD","RY","BNS","UL","BTI","RIO","BHP","BP","SHEL","TTE","NVO","AZN","GSK",
    "SNY","HSBC","ABEV","TTEK","DKNG",
]

# --- Strategy dials (tune any of these, one number at a time) ---
LEFT_K = 10            # swing significance (lookback window before a pivot)
RIGHT_K = 1            # bars required after a low to confirm it (1 = react fast to fresh bounces)
ENTRY_MIN_PCT = 2.5    # price must be 2.5-10% above the recent higher low
ENTRY_MAX_PCT = 10.0
NEAR_SUPPORT_PCT = 8.0 # price must be within this % above the support line (tight pullback)
RECENT_LOW_MAX_BARS = 40  # the bounce low must be recent (a fresh pullback, not a stale one)
VOL_MULT = 1.0         # bounce-day volume must beat the prior 20-day average by this multiple
STOP_PCT = 4.0
MAX_SWING_PCT = 15.0   # reject a stock if ANY single day (up OR down) moved this % or more — too erratic
CHUNK = 50             # download this many tickers at a time
CHUNK_PAUSE = 1.0      # seconds to pause between chunks (be gentle on the data source)

# --- Cup-and-Handle detector dials (a separate, standalone breakout signal) ---
CUP_K              = 15     # pivot significance for the cup's rims/bottom (bigger swings than LEFT_K)
CUP_MIN_BARS       = 25     # rim-to-rim span: minimum
CUP_MAX_BARS       = 250    # rim-to-rim span: maximum (~1 trading year)
CUP_MIN_DEPTH_PCT  = 6.0    # cup depth (rim-bottom) as % of rim: absolute floor
CUP_DEEP_MIN_PCT   = 12.0   # shallower than this = a CONTINUATION cup: only valid near the highs
CUP_NEAR_HIGH_PCT  = 5.0    # ...meaning the rim is within this % of the ~6-month high
CUP_MAX_DEPTH_PCT  = 50.0   # ceiling (deeper = a crash, not a cup)
RIM_TOL_PCT        = 6.0    # right rim must be within this % of the left rim (roughly level)
BOTTOM_CENTER_LO   = 0.30   # bottom must sit in the central 30-70% of the span (rounded, not a late V)
BOTTOM_CENTER_HI   = 0.70
ROUND_MIN_BARS     = 5      # >=5 bars within the bottom 20% of depth => rounded base, not a single-spike V
HANDLE_MIN_BARS    = 3
HANDLE_MAX_BARS    = 40     # handle must form within this many bars after the right rim
HANDLE_MAX_DEPTH_FRAC = 0.5 # handle depth <= 50% of cup depth, AND its low stays in the upper half of the cup
BREAKOUT_BUFFER_PCT   = 0.2 # close must clear the rim by this margin
BREAKOUT_MAX_BARS     = 2   # the breakout cross must be fresh (within the last 1-2 bars)

# --- Flat-top breakout + breakout-retest dials (lessons from the TCBK/HOOD winners) ---
FLAT_TOL_PCT      = 1.5   # swing highs within this % of each other count as the same ceiling
FLAT_MIN_TOUCHES  = 3     # the ceiling must have been tested at least this many times
FLAT_WINDOW       = 120   # look for the ceiling within the last ~6 months
FLAT_MIN_AGE_BARS = 30    # the first touch must be at least this old (a real base, not one week)
FLAT_MIN_HEIGHT   = 5.0   # consolidation depth below the ceiling, % of the level (floor)
FLAT_MAX_HEIGHT   = 30.0  # deeper than this = not a tight base
RETEST_MAX_BARS   = 15    # a breakout this recent can still yield a "second chance" retest entry
RETEST_TOL_PCT    = 2.5   # the pullback must come within this % of the broken level (and hold it)

# --- Channel-dip buy ("heavy buy" at a proven rising channel's lower rail) ---
CHAN_WINDOW        = 180   # fit the channel over the last ~9 months
CHAN_MIN_TOUCHES   = 3     # the lower rail must have been touched at least this many times
CHAN_TOL_PCT       = 2.5   # "at the rail" tolerance (for touches and for the entry)
CHAN_MAX_BREAK_PCT = 3.0   # lows may pierce the rail at most this much (rail must be respected)
CHAN_MIN_DROP_PCT  = 10.0  # the dip must be a real correction off the recent high
CHAN_STOP_PCT      = 2.0   # structural stop: this far below the rail (not a blind 4% off entry)


def send_telegram_message(message: str) -> bool:
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": CHAT_ID, "text": message}, timeout=10)
        if not resp.ok:
            print(f"Telegram API error {resp.status_code}: {resp.text}")
            return False
        return True
    except requests.RequestException as e:
        print(f"Error sending Telegram message: {e}")
        return False


def _parse_cap(value):
    """Parse a market-cap string like '1,234,567,890' into a float (or None)."""
    if value is None:
        return None
    s = str(value).replace(",", "").replace("$", "").strip()
    if not s or s.upper() in ("N/A", "NA", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def get_universe():
    """Every US-listed stock with market cap >= MIN_MARKET_CAP, from the NASDAQ screener
    (covers NASDAQ + NYSE + AMEX). Returns (symbols, used_fallback). Retries on failure, and
    if the live list comes back suspiciously small it merges in the fallback so we never go dark."""
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    params = {"tableonly": "true", "limit": "0", "download": "true"}
    rows = None
    for attempt in range(4):
        try:
            resp = requests.get(NASDAQ_SCREENER_URL, headers=headers, params=params, timeout=30)
            resp.raise_for_status()
            rows = resp.json().get("data", {}).get("rows") or []
            if rows:
                break
        except Exception as e:
            print(f"Universe fetch attempt {attempt + 1}/4 failed: {e}")
        time.sleep(2 ** attempt)

    if not rows:
        print(f"Universe fetch failed after retries; using fallback list of {len(FALLBACK_SYMBOLS)}.")
        return sorted(set(FALLBACK_SYMBOLS)), True

    syms = set()
    for row in rows:
        cap = _parse_cap(row.get("marketCap"))
        if cap is None or cap < MIN_MARKET_CAP:
            continue
        sym = (row.get("symbol") or "").strip().upper()
        if not sym or any(c in sym for c in "^$"):   # skip warrants/units/odd tickers
            continue
        sym = sym.replace("/", "-").replace(".", "-")  # Yahoo uses '-' for share classes
        syms.add(sym)

    merged = len(syms) < MIN_UNIVERSE                 # incomplete fetch -> augment, don't go dark
    if merged:
        print(f"Screener returned only {len(syms)} names (< {MIN_UNIVERSE}); merging fallback to be safe.")
        syms |= set(FALLBACK_SYMBOLS)
    print(f"Universe: {len(syms)} stocks with market cap >= ${MIN_MARKET_CAP:,}.")
    return sorted(syms), merged                       # disclose if the fallback was mixed in


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


def largest_daily_swing(closes):
    """Biggest single-day move in EITHER direction over the series.
    Returns (worst_drop_pct<=0, biggest_jump_pct>=0). Catches erratic, inconsistent names."""
    worst, best = 0.0, 0.0
    for i in range(1, len(closes)):
        if closes[i - 1] > 0:
            ch = (closes[i] / closes[i - 1] - 1) * 100
            worst = min(worst, ch)
            best = max(best, ch)
    return worst, best


def _breakout_kind(closes, lows, level, start):
    """Classify how price broke above `level` after bar `start`.

    Returns (kind, cross_idx):
      "breakout" — the cross happened within the last BREAKOUT_MAX_BARS (fresh, enter now);
      "retest"   — the cross is older (<= RETEST_MAX_BARS), price pulled back to within
                   RETEST_TOL_PCT of the level, HELD it, and is turning up — a second-chance
                   entry (the HOOD pattern: break rim, pull back, continue);
      (None, None) — no valid entry."""
    n = len(closes)
    buffed = level * (1 + BREAKOUT_BUFFER_PCT / 100)
    cross = next((i for i in range(start + 1, n) if closes[i] > buffed), None)
    if cross is None:
        return None, None
    age = n - 1 - cross
    if age <= BREAKOUT_MAX_BARS:
        if closes[-1] > buffed:                      # still on the breakout today
            return "breakout", cross
        return None, None
    if age <= RETEST_MAX_BARS:
        after = closes[cross + 1:]
        pulled_to_level = min(lows[cross + 1:]) <= level * (1 + RETEST_TOL_PCT / 100)
        held_level = min(after) >= level * (1 - RETEST_TOL_PCT / 100)   # never collapsed back under
        if pulled_to_level and held_level and closes[-1] > closes[-2] and closes[-1] > level:
            return "retest", cross
    return None, None


def detect_flat_top(highs, lows, closes):
    """Detect a flat-top breakout (the TCBK pattern): a horizontal ceiling tested several
    times over months finally gives way. Returns a dict (level, touches, floor, height,
    target, kind) or None. Target = level + height of the base (the measured move).
    kind is "breakout" (fresh) or "retest" (broke earlier, pulled back and held)."""
    n = len(closes)
    if n < FLAT_MIN_AGE_BARS + LEFT_K:
        return None
    swing_highs, _ = find_pivots(highs, lows, LEFT_K, RIGHT_K)
    recent = [(i, h) for i, h in swing_highs if i >= n - FLAT_WINDOW]
    if len(recent) < FLAT_MIN_TOUCHES:
        return None
    # The ceiling is the highest CLUSTER of >= FLAT_MIN_TOUCHES swing highs within tolerance
    # (not the single max — a post-breakout run-up high must not steal the level).
    level, touches = None, []
    for _, cand in sorted(recent, key=lambda t: t[1], reverse=True):
        cluster = [(i, h) for i, h in recent if cand * (1 - FLAT_TOL_PCT / 100) <= h <= cand]
        if len(cluster) >= FLAT_MIN_TOUCHES:
            level, touches = cand, cluster
            break
    if level is None:
        return None
    first, last = touches[0][0], touches[-1][0]
    if n - 1 - first < FLAT_MIN_AGE_BARS:            # the ceiling needs real history
        return None
    floor = min(lows[first:last + 1])
    height = level - floor
    height_pct = height / level * 100
    if not (FLAT_MIN_HEIGHT <= height_pct <= FLAT_MAX_HEIGHT):
        return None
    # the ceiling must have actually capped price inside the base
    buffed = level * (1 + BREAKOUT_BUFFER_PCT / 100)
    if any(c > buffed for c in closes[first:last + 1]):
        return None
    kind, _cross = _breakout_kind(closes, lows, level, last)
    if kind is None:
        return None
    return {"level": round(level, 2), "touches": len(touches), "floor": round(floor, 2),
            "height": round(height, 2), "target": round(level + height, 2), "kind": kind}


def detect_cup_and_handle(highs, lows, closes):
    """Detect a FRESH cup-and-handle breakout ending at the latest bar.

    A cup is a rounded dip: down from a rim, a rounded base, back up to ~the same rim.
    A handle is a small shallow dip right after. The signal fires when today's close breaks
    above the rim. Returns a dict (rim, bottom, depth, handle_low, breakout_level, target)
    or None. Target = breakout + full cup depth (the measured move)."""
    n = len(closes)
    if n < CUP_MIN_BARS + HANDLE_MIN_BARS + 2:
        return None
    swing_highs, swing_lows = find_pivots(highs, lows, CUP_K, RIGHT_K)
    if len(swing_highs) < 2 or len(swing_lows) < 1:
        return None

    # Search rim pairs, most-recent right rim first, for a valid cup whose handle+breakout is fresh.
    for r_idx in range(len(swing_highs) - 1, 0, -1):
        i_r, right = swing_highs[r_idx]
        # the right rim must leave room for a handle + breakout near the end
        if i_r > n - (HANDLE_MIN_BARS + 1) or i_r < n - (HANDLE_MAX_BARS + BREAKOUT_MAX_BARS + 1):
            continue
        for l_idx in range(r_idx - 1, -1, -1):
            i_l, left = swing_highs[l_idx]
            span = i_r - i_l
            if span < CUP_MIN_BARS:
                continue
            if span > CUP_MAX_BARS:
                break
            if abs(right - left) / left * 100 > RIM_TOL_PCT:   # rims must be roughly level
                continue
            rim_level = max(left, right)
            base = min(lows[i_l:i_r + 1])
            bottom_idx = i_l + lows[i_l:i_r + 1].index(base)
            depth = rim_level - base
            depth_pct = depth / rim_level * 100
            if not (CUP_MIN_DEPTH_PCT <= depth_pct <= CUP_MAX_DEPTH_PCT):
                continue
            # Shallow cups (6-12%) are CONTINUATION cups — from the user's charts they only
            # count when pressing near the highs (cup chains riding a channel), not deep in a range.
            if depth_pct < CUP_DEEP_MIN_PCT:
                high_6m = max(closes[max(0, n - 126):])
                if rim_level < high_6m * (1 - CUP_NEAR_HIGH_PCT / 100):
                    continue
            # roundedness: bottom roughly central AND price dwells near the base (not a sharp V)
            frac = (bottom_idx - i_l) / span
            if not (BOTTOM_CENTER_LO <= frac <= BOTTOM_CENTER_HI):
                continue
            near_base = sum(1 for lo in lows[i_l:i_r + 1] if lo <= base + 0.20 * depth)
            if near_base < ROUND_MIN_BARS:
                continue
            # handle: shallow dip after the right rim that stays in the upper half of the cup
            seg = closes[i_r + 1:]
            if len(seg) < HANDLE_MIN_BARS:
                continue
            handle_low = min(seg)
            handle_depth = rim_level - handle_low
            if handle_depth > HANDLE_MAX_DEPTH_FRAC * depth:
                continue
            if handle_low < base + 0.5 * depth:                # handle dipped too deep into the cup
                continue
            # entry: a fresh breakout above the rim, OR a successful retest of the broken rim
            kind, _cross = _breakout_kind(closes, lows, rim_level, i_r)
            if kind is None:
                continue
            return {"rim": round(rim_level, 2), "bottom": round(base, 2),
                    "depth": depth, "depth_pct": round(depth_pct, 1),
                    "handle_low": round(handle_low, 2),
                    "breakout_level": round(rim_level * (1 + BREAKOUT_BUFFER_PCT / 100), 2),
                    "target": round(rim_level + depth, 2), "kind": kind}
    return None


def evaluate(highs, lows, closes, vols):
    if len(closes) < LEFT_K + RIGHT_K + 5:
        return None
    price = float(closes[-1]); x = len(closes) - 1

    # Macro trend guard: don't issue a buy signal in an established downtrend.
    # If the stock is >15% below its 6-month high it is in a macro downtrend — skip it.
    lookback = min(126, len(closes))
    high_6m = max(closes[-lookback:])
    in_macro_downtrend = price < 0.85 * high_6m

    swing_highs, swing_lows = find_pivots(highs, lows, LEFT_K, RIGHT_K)
    if len(swing_lows) < 2 or len(swing_highs) < 2:
        return None
    low_prev, low_last = swing_lows[-2], swing_lows[-1]
    high_prev, high_last = swing_highs[-2], swing_highs[-1]
    support, sup_slope = trendline(swing_lows, x)
    resistance, _ = trendline(swing_highs, x)

    higher_highs = high_last[1] > high_prev[1]                       # each high above the last high
    higher_lows = low_last[1] > low_prev[1]                          # pullback bottoms above the prior low
    is_uptrend = higher_highs and higher_lows and sup_slope > 0      # classic uptrend staircase
    low_bars_ago = x - low_last[0]
    coming_off_recent_low = (low_last[0] > high_last[0]) and (low_bars_ago <= RECENT_LOW_MAX_BARS)
    near_support = support <= price <= support * (1 + NEAR_SUPPORT_PCT / 100)   # tight pullback
    pct = (price - low_last[1]) / low_last[1] * 100
    in_zone = ENTRY_MIN_PCT <= pct <= ENTRY_MAX_PCT
    turning_up = closes[-1] > closes[-2]
    prior = vols[-22:-2]                                             # prior up-to-20 days, excludes the last 2
    prev_avg_vol = sum(prior) / len(prior) if prior else 0          # divide by what we actually have
    # Volume confirmation on EITHER of the last 2 bars: the bounce's volume day is often the day
    # before our close check, and an intraday /daily run leaves the final bar's volume partial.
    volume_ok = prev_avg_vol > 0 and any(v > VOL_MULT * prev_avg_vol for v in vols[-2:])

    pulled_back = is_uptrend and coming_off_recent_low and near_support and in_zone and price < resistance
    # Stability guard: reject erratic names that had a violent single-day move (up OR down) within
    # the last ~year (e.g. CRVL/FLEX). Crazy jumps = inconsistent = untrustworthy, so never suggest them.
    worst_drop, biggest_jump = largest_daily_swing(closes[-ERRATIC_WINDOW:])
    worst_swing = worst_drop if abs(worst_drop) >= biggest_jump else biggest_jump
    erratic = (worst_drop <= -MAX_SWING_PCT) or (biggest_jump >= MAX_SWING_PCT)
    fires = pulled_back and turning_up and volume_ok and not erratic and not in_macro_downtrend

    # Cup-and-handle: a separate, standalone breakout signal (near the highs by construction,
    # so the macro-downtrend guard doesn't apply; the erratic guard still does).
    cup = detect_cup_and_handle(highs, lows, closes)
    cup_fires = cup is not None and not erratic

    # Flat-top breakout (the TCBK pattern): a multi-touch horizontal ceiling gives way.
    # Flat tops sit near the highs, so both guards apply.
    flat = detect_flat_top(highs, lows, closes)
    flat_fires = flat is not None and not erratic and not in_macro_downtrend

    # Channel-dip buy: a sharp correction landing on a proven rising channel's lower rail.
    # DELIBERATELY exempt from the macro-downtrend guard — the >10% drop IS the setup;
    # the erratic guard still applies.
    chan = detect_channel_dip(highs, lows, closes)
    chan_fires = chan is not None and not erratic

    # Golden cross (50-day SMA above 200-day): a regime confirmation tag, not a gate.
    golden_cross = None
    if len(closes) >= 210:
        sma50 = sum(closes[-50:]) / 50
        sma200 = sum(closes[-200:]) / 200
        if sma50 > sma200:
            past50 = sum(closes[-60:-10]) / 50           # the same SMAs ~10 bars ago
            past200 = sum(closes[-210:-10]) / 200
            golden_cross = "fresh" if past50 <= past200 else "active"

    # Stop-loss: structural when a level exists (just under the broken rim/ceiling — the
    # user's charts always anchor the stop to structure), else the default % off entry.
    # Structure only tightens the stop, never widens it beyond STOP_PCT.
    stop = price * (1 - STOP_PCT / 100)
    for level in ((cup["rim"] if cup else None), (flat["level"] if flat else None)):
        if level:
            structural = level * 0.985              # ~1.5% under the broken level
            if stop < structural < price:
                stop = structural

    return dict(price=price, pct=pct, is_uptrend=is_uptrend, pulled_back=pulled_back,
                fires=fires, resistance=resistance, stop=stop,
                higher_highs=higher_highs, higher_lows=higher_lows, near_support=near_support,
                in_zone=in_zone, volume_ok=volume_ok, turning_up=turning_up,
                erratic=erratic, worst_swing=round(worst_swing, 1),
                support=support, sup_slope=sup_slope,
                in_macro_downtrend=in_macro_downtrend, high_6m=round(high_6m, 2),
                cup_fires=cup_fires,
                cup_target=cup["target"] if cup else None,
                cup_depth=round(cup["depth"], 2) if cup else None,
                cup_rim=cup["rim"] if cup else None,
                cup_kind=cup["kind"] if cup else None,
                flat_fires=flat_fires,
                flat_target=flat["target"] if flat else None,
                flat_level=flat["level"] if flat else None,
                flat_touches=flat["touches"] if flat else None,
                flat_kind=flat["kind"] if flat else None,
                chan_fires=chan_fires,
                chan_rail=chan["rail"] if chan else None,
                chan_touches=chan["touches"] if chan else None,
                chan_target=chan["target"] if chan else None,
                chan_stop=chan["stop"] if chan else None,
                chan_drop=chan["drop_pct"] if chan else None,
                golden_cross=golden_cross)


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


def download_chunk(chunk, retries=3):
    """Download a chunk with retries/backoff. Returns the DataFrame or None."""
    for attempt in range(retries):
        try:
            data = yf.download(chunk, period="2y", interval="1d", group_by="ticker",
                               auto_adjust=True, progress=False, threads=True)
            if data is not None and len(data) > 0:
                return data
        except Exception as e:
            print(f"  chunk download error (attempt {attempt + 1}): {e}")
        time.sleep(2 ** attempt)
    return None


def _rev_label(pct):
    status = "yes" if pct > 0 else "no"
    return (status, f"rev {pct:+.0f}% YoY")


def revenue_growth(sym):
    """Year-over-year revenue check. Returns (status, label): 'yes' (growing), 'no'
    (declining), or 'unknown'. Tries, in order:
      1. Yahoo's own revenueGrowth figure (most reliable when present);
      2. quarterly statements — latest column vs the column DATED ~1 year earlier
         (index-position compares broke on mixed annual/TTM columns: MU showed +346%);
      3. annual statements — latest fiscal year vs the previous one (covers foreign
         issuers like ARGX that report semi-annually and lack 5 quarterly columns)."""
    try:
        t = yf.Ticker(sym)
    except Exception:
        return ("unknown", "rev n/a")

    diag = []
    for attempt in range(2):                        # 1) Yahoo's precomputed YoY growth
        try:                                        #    (this endpoint gets rate-limited; retry once)
            info = t.info or {}
            rg = info.get("revenueGrowth")
            if isinstance(rg, (int, float)):
                if abs(rg) > 5:                     # percentage form slipped through
                    rg /= 100.0
                return _rev_label(rg * 100)
            diag.append("info empty" if not info else "info has no revenueGrowth")
            if info:
                break
        except Exception as e:
            diag.append(f"info error: {e}")
        if attempt == 0:
            time.sleep(2)

    def _revenue_series(df):
        """The revenue row from a statement, newest-first, with a proper datetime index."""
        if df is None or getattr(df, "empty", True):
            return None
        for row in ("Total Revenue", "Operating Revenue", "Revenue"):
            if row in df.index:
                rev = df.loc[row].dropna()
                if len(rev):
                    rev.index = pd.to_datetime(rev.index, errors="coerce")
                    rev = rev[rev.index.notna()]
                    return rev.sort_index(ascending=False)
        return None

    try:                                            # 2) quarterly, date-matched ~1y apart
        for attr in ("quarterly_income_stmt", "quarterly_financials"):
            rev = _revenue_series(getattr(t, attr, None))
            if rev is None or len(rev) < 2:
                continue
            latest_date, latest = rev.index[0], float(rev.iloc[0])
            best, best_gap = None, None
            for d, v in rev.iloc[1:].items():
                gap = abs((latest_date - d).days - 365)
                if gap <= 120 and (best_gap is None or gap < best_gap):  # a real year apart
                    best, best_gap = float(v), gap
            if best and best != 0:
                pct = (latest - best) / abs(best) * 100
                if abs(pct) <= 200:                 # sanity: >200% = mixed/mislabeled columns
                    return _rev_label(pct)
                diag.append(f"quarterly implausible ({pct:.0f}%)")
            else:
                diag.append(f"quarterly: no column ~1y from {latest_date.date()} ({len(rev)} cols)")
            break
        else:
            diag.append("no quarterly statement")
    except Exception as e:
        diag.append(f"quarterly error: {e}")

    try:                                            # 3) annual: latest FY vs previous FY
        rev = _revenue_series(getattr(t, "income_stmt", None))
        if rev is not None and len(rev) >= 2 and float(rev.iloc[1]) != 0:
            pct = (float(rev.iloc[0]) - float(rev.iloc[1])) / abs(float(rev.iloc[1])) * 100
            return _rev_label(pct)
        diag.append("annual statement missing/short")
    except Exception as e:
        diag.append(f"annual error: {e}")
    print(f"revenue_growth({sym}) -> unknown: " + "; ".join(diag), flush=True)
    return ("unknown", "rev n/a")


# Every free, no-API-key stock-news feed we pull from. Google News alone already
# aggregates Reuters, Bloomberg, CNBC, WSJ, MarketWatch, etc.; the rest add breadth.
# {q} = url-encoded "<SYM> stock", {sym} = url-encoded ticker. All best-effort.
NEWS_FEEDS = [
    ("Google News", "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"),
    ("Yahoo Finance", "https://feeds.finance.yahoo.com/rss/2.0/headline?s={sym}&region=US&lang=en-US"),
    ("Nasdaq", "https://www.nasdaq.com/feed/rssoutbound?symbol={sym}"),
    ("Bing News", "https://www.bing.com/news/search?q={q}&format=rss"),
    ("Seeking Alpha", "https://seekingalpha.com/api/sa/combined/{sym}.xml"),
]


def _norm_title(title):
    return re.sub(r"[^a-z0-9]", "", title.lower())[:60]


def fetch_news_items(sym, limit=NEWS_PER_STOCK, per_feed=4):
    """Aggregate recent headlines across every feed in NEWS_FEEDS, dedupe near-identical
    titles, and interleave sources for variety. Returns a list of dicts:
    {title, link, source}. Best-effort — a feed that fails is just skipped."""
    q = quote_plus(sym + " stock")
    esym = quote_plus(sym)
    per_feed_items = []
    for source, tmpl in NEWS_FEEDS:
        url = tmpl.format(q=q, sym=esym)
        feed_items = []
        try:
            resp = requests.get(url, headers={"User-Agent": BROWSER_UA}, timeout=6)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            for item in root.findall(".//item")[:per_feed]:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                if title:
                    feed_items.append({"title": title, "link": link, "source": source})
        except Exception:
            pass
        per_feed_items.append(feed_items)

    items, seen = [], set()
    for tier in zip_longest(*per_feed_items):       # round-robin across sources
        for it in tier:
            if it is None:
                continue
            key = _norm_title(it["title"])
            if key and key not in seen:
                seen.add(key)
                items.append(it)
    return items[:limit] if limit else items


def fetch_news(sym, limit=NEWS_PER_STOCK):
    """Backward-compatible: top headlines as plain strings (used by the daily scan)."""
    return [it["title"] for it in fetch_news_items(sym, limit)]


def news_link(sym):
    return f"https://news.google.com/search?q={quote_plus(sym + ' stock')}"


def enrich_hits(hits):
    """Quality-gate the chart hits down to THE BEST OF THE BEST, then enrich only those.

    Gates, in order: confirmed YoY revenue growth -> health score >= MIN_SCORE ->
    ZERO red flags (a clean sheet — the user only wants near-perfect names). Survivors
    are ranked by score (then data coverage) and capped at MAX_ALERTS; the expensive
    Sonnet verdict + news run ONLY for those finalists, so the scan can't blow the job
    timeout on a hit-heavy day. Returns (list of dicts, drop-reason tally)."""
    passed = []
    drops = {"revenue": 0, "health_score": 0, "red_flags": 0, "beyond_top": 0}
    for sym, r in hits:
        status, rev_label = revenue_growth(sym)
        if REQUIRE_CONFIRMED_GROWTH and status != "yes":
            reason = "declining" if status == "no" else "growth unverifiable"
            print(f"  drop {sym}: {rev_label} ({reason})")
            drops["revenue"] += 1
            continue
        xr = xray.xray(sym, ai=False)                       # cheap rule-based score first
        if not xr.get("ok") or (xr.get("score") or 0) < MIN_SCORE:
            print(f"  drop {sym}: health score {xr.get('score') if xr.get('ok') else 'n/a'} < {MIN_SCORE}")
            drops["health_score"] += 1
            continue
        reds = [it["label"] for it in xr.get("items", []) if it.get("flag") == "red"]
        if reds:                                            # only clean sheets make the alert
            print(f"  drop {sym}: {len(reds)} red flag(s) — {', '.join(reds[:3])}")
            drops["red_flags"] += 1
            continue
        passed.append(dict(sym=sym, r=r, rev_status=status, rev_label=rev_label, xray=xr))
        time.sleep(0.2)   # be gentle on the fundamentals endpoints

    # Rank: highest health score first, then how perfectly the chart fits the strategy
    # (multiple signals at once = closer to the textbook setup), then data coverage.
    passed.sort(key=lambda h: (h["xray"].get("score", 0), setup_strength(h["r"]),
                               h["xray"].get("coverage", 0)), reverse=True)
    finalists, overflow = passed[:MAX_ALERTS], passed[MAX_ALERTS:]
    drops["beyond_top"] = len(overflow)
    for h in overflow:
        print(f"  beyond top {MAX_ALERTS}: {h['sym']} (score {h['xray'].get('score')})")

    for h in finalists:                                     # expensive extras: finalists only
        try:
            xray._ai_layer(h["sym"], h["xray"], web=os.environ.get("XRAY_WEB") == "1")
        except Exception as e:
            print(f"  xray AI failed for {h['sym']}: {e}")
        h["news"] = fetch_news(h["sym"])
        time.sleep(0.3)
    return finalists, drops


def _lsq_line(points):
    """Least-squares line through (x, y) points. Returns (slope, intercept) or None."""
    n = len(points)
    if n < 2:
        return None
    sx = sum(p[0] for p in points); sy = sum(p[1] for p in points)
    sxx = sum(p[0] * p[0] for p in points); sxy = sum(p[0] * p[1] for p in points)
    denom = n * sxx - sx * sx
    if denom == 0:
        return None
    slope = (n * sxy - sx * sy) / denom
    return slope, (sy - slope * sx) / n


def detect_channel_dip(highs, lows, closes):
    """The 'heavy buy' from the user's charts: a stock riding a long, PROVEN rising channel
    takes a sharp correction straight down to the channel's lower rail and turns up there.
    A drop like that fails the macro-downtrend guard by design — but when it lands on a rail
    that has held 3+ times over months, it's a dip-buy, not a downtrend.

    Returns dict(rail, touches, target, stop, drop_pct) or None. Stop is STRUCTURAL —
    just below the rail — and the target is the channel's upper rail today."""
    n = len(closes)
    if n < CHAN_MIN_TOUCHES * LEFT_K + 10:
        return None
    x = n - 1
    price = float(closes[-1])
    swing_highs, swing_lows = find_pivots(highs, lows, LEFT_K, RIGHT_K)
    lows_w = [(i, v) for i, v in swing_lows if i >= n - CHAN_WINDOW]
    highs_w = [(i, v) for i, v in swing_highs if i >= n - CHAN_WINDOW]
    if len(lows_w) < CHAN_MIN_TOUCHES or len(highs_w) < 2:
        return None
    fit = _lsq_line(lows_w)
    if fit is None or fit[0] <= 0:                          # the rail must RISE
        return None
    slope, intercept = fit
    rail_now = slope * x + intercept
    if rail_now <= 0:
        return None
    # rail quality: touched >= CHAN_MIN_TOUCHES times, never broken by much
    touches = sum(1 for i, v in lows_w if abs(v - (slope * i + intercept)) <= (slope * i + intercept) * CHAN_TOL_PCT / 100)
    worst_break = min((v - (slope * i + intercept)) / (slope * i + intercept) * 100 for i, v in lows_w)
    if touches < CHAN_MIN_TOUCHES or worst_break < -CHAN_MAX_BREAK_PCT:
        return None
    # a REAL correction: price fell CHAN_MIN_DROP_PCT+ from the recent high down to the rail
    recent_high = max(closes[-60:])
    drop_pct = (recent_high - price) / recent_high * 100
    if drop_pct < CHAN_MIN_DROP_PCT:
        return None
    if not (rail_now * (1 - CHAN_TOL_PCT / 100) <= price <= rail_now * (1 + CHAN_TOL_PCT / 100)):
        return None                                         # must be AT the rail
    if closes[-1] <= closes[-2]:                            # and turning up off it
        return None
    # target: the channel's upper rail today (parallel structure through the swing highs)
    fit_hi = _lsq_line(highs_w)
    target = fit_hi[0] * x + fit_hi[1] if fit_hi else None
    if not target or target <= price:
        return None
    return {"rail": round(rail_now, 2), "touches": touches,
            "target": round(target, 2), "stop": round(rail_now * (1 - CHAN_STOP_PCT / 100), 2),
            "drop_pct": round(drop_pct, 1)}


def setup_strength(r):
    """How perfectly a hit matches the strategy: more independent signals firing at once =
    a stronger, more textbook setup. Used to rank the daily finalists (after health score)."""
    s = 0.0
    if r.get("fires"):
        s += 2.0                                            # full higher-low bounce, all conditions
    if r.get("cup_fires"):
        s += 2.0 if r.get("cup_kind") != "retest" else 1.5  # fresh breakout beats a retest
    if r.get("flat_fires"):
        s += 2.0 if r.get("flat_kind") != "retest" else 1.5
    if r.get("chan_fires"):
        s += 2.0                                            # dip to a proven channel rail
    if r.get("golden_cross") == "fresh":
        s += 1.0
    elif r.get("golden_cross") == "active":
        s += 0.5
    if r.get("is_uptrend"):
        s += 0.5
    if r.get("volume_ok"):
        s += 0.5
    return s


def gate_misses(r):
    """Which of the final chart conditions a pulled-back stock is missing (empty = it fires)."""
    missing = []
    if not r["turning_up"]:
        missing.append("not turning up")
    if not r["volume_ok"]:
        missing.append("volume below average")
    if r["erratic"]:
        missing.append("erratic swings")
    if r["in_macro_downtrend"]:
        missing.append("macro downtrend")
    return missing


def build_summary(universe_n, scanned, uptrends, pulled, hits, used_fallback,
                  gate_fails=None, near_misses=None, drops=None):
    if scanned == 0:
        return (f"⚠️ Stock bot: scan FAILED — 0 of {universe_n} symbols "
                f"returned data (likely rate-limited or a network error). No reliable "
                f"signal today.")
    rev_icon = {"yes": "✅", "no": "⚠️", "unknown": "❓"}
    lines = [f"\U0001F4CA Daily scan: {scanned} scanned | {uptrends} uptrends | "
             f"{pulled} pulled back | {len(hits)} BUY setup(s)"]
    if used_fallback:
        lines.append("(used fallback symbol list — live universe fetch failed)")
    drop_parts = []
    if drops:
        if drops.get("revenue"):
            drop_parts.append(f"{drops['revenue']} lacked confirmed revenue growth")
        if drops.get("health_score"):
            drop_parts.append(f"{drops['health_score']} scored below {MIN_SCORE}/10")
        if drops.get("red_flags"):
            drop_parts.append(f"{drops['red_flags']} had red flags (not a clean sheet)")
        if drops.get("beyond_top"):
            drop_parts.append(f"{drops['beyond_top']} passed but ranked below the top {MAX_ALERTS}")

    if not hits:
        lines.append(f"\nNo buy setups today that clear the bar (chart entry + growing revenue + "
                     f"health score ≥ {MIN_SCORE}/10 with ZERO red flags, not erratic).")
        # Explain WHERE the funnel choked, so quiet days aren't a black box.
        if gate_fails and sum(gate_fails.values()):
            parts = [f"{n} {label}" for label, n in gate_fails.items() if n]
            lines.append(f"\nWhy: of the {pulled} pulled back — " + ", ".join(parts) + ".")
        if drop_parts:
            lines.append("Chart setups dropped at the quality gates: " + "; ".join(drop_parts) + ".")
        if near_misses:
            lines.append("\n\U0001F440 Nearly there (one condition missing):")
            for sym, price, cond in near_misses[:5]:
                lines.append(f"• {sym} ${price:.2f} — waiting on: {cond}")
        return "\n".join(lines)

    lines.append("")
    lines.append(f"\U0001F6A8 BUY setups — the best of the best (clean sheet, zero red flags, "
                 f"score ≥ {MIN_SCORE}/10, top {MAX_ALERTS}):")
    if drop_parts:
        lines.append("(" + "; ".join(drop_parts) + ")")
    hits = sorted(hits, key=lambda h: (h.get("xray") or {}).get("score", 0), reverse=True)
    for h in hits:
        r = h["r"]
        lines.append("")
        # Pattern targets are measured moves (level + base height); the bounce uses resistance.
        # The channel dip uses its own structural stop (just below the rail) and rail target.
        target = r.get("cup_target") or r.get("flat_target") or r.get("chan_target") or r["resistance"]
        stop = r.get("chan_stop") if r.get("chan_fires") else r["stop"]
        lines.append(f"{h['sym']}: ${r['price']:.2f} | stop ${stop:.2f} | target ${target:.2f}")
        setups = []
        if r.get("chan_fires"):
            setups.append(f"🛒 Channel-dip buy ({r.get('chan_drop'):.1f}% correction to a rail "
                          f"held {r.get('chan_touches')}×, stop under ${r.get('chan_rail'):.2f})")
        if r.get("cup_fires"):
            entry = "breakout" if r.get("cup_kind") != "retest" else "retest entry 🔁"
            setups.append(f"☕ Cup & Handle {entry} (rim ${r.get('cup_rim'):.2f}, depth ${r.get('cup_depth'):.2f})")
        if r.get("flat_fires"):
            entry = "breakout" if r.get("flat_kind") != "retest" else "retest entry 🔁"
            setups.append(f"📏 Flat-top {entry} ({r.get('flat_touches')} touches at ${r.get('flat_level'):.2f})")
        if r["fires"]:
            setups.append("higher-low bounce")
        if setups:
            lines.append(f"  📐 Setup: {' + '.join(setups)}")
        if r.get("golden_cross"):
            lines.append(f"  ⭐ Golden cross ({r['golden_cross']}) — 50-day avg above 200-day")
        lines.append(f"  {rev_icon.get(h['rev_status'], '')} {h['rev_label']}")
        xr = h.get("xray")
        if xr and xr.get("ok"):
            lines.append(f"  🩻 Health score: {xr['score']}/10 ({xr['verdict']})")
            lines.append(f"  💡 Opportunity: {xr['opportunity']}")
            lines.append(f"  ⚠️ Danger: {xr['danger']}")
            if xr.get("ai_verdict"):
                lines.append(f"  🤖 {xr['ai_verdict']}")
            lines.append(f"  Full X-ray in chat: /xray {h['sym']}")
        for title in h["news"]:
            lines.append(f"  • {title}")
        if h["news"]:
            lines.append(f"  More: {news_link(h['sym'])}")
    lines.append("")
    lines.append("Set stop + take-profit in Plus500. Not financial advice — check the news before buying.")
    return "\n".join(lines)


def send_long(text, limit=3900):
    """Telegram caps messages at 4096 chars, so send a long report as several messages,
    splitting on blank lines so setups stay intact. Any single oversized block is hard-split
    (by lines, then raw chars) so nothing is ever dropped or rejected."""
    def pieces(block):
        if len(block) <= limit:
            return [block]
        out, cur = [], ""
        for ln in block.split("\n"):
            while len(ln) > limit:                 # a single monster line
                out.append(ln[:limit]); ln = ln[limit:]
            if cur and len(cur) + 1 + len(ln) > limit:
                out.append(cur); cur = ln
            else:
                cur = (cur + "\n" + ln) if cur else ln
        if cur:
            out.append(cur)
        return out

    chunk, sent = "", 0
    for b in text.split("\n\n"):
        for piece in pieces(b):
            if chunk and len(chunk) + 2 + len(piece) > limit:
                sent += 1 if send_telegram_message(chunk) else 0
                chunk = piece
            else:
                chunk = (chunk + "\n\n" + piece) if chunk else piece
    if chunk:
        sent += 1 if send_telegram_message(chunk) else 0
    return sent


def main():
    symbols, used_fallback = get_universe()
    print(f"Scanning {len(symbols)} stocks (market cap >= ${MIN_MARKET_CAP:,})"
          f"{' [fallback list]' if used_fallback else ''}...")
    scanned = uptrends = pulled = 0
    hits = []
    watchlist = []           # (sym, price, [missing conditions]) for pulled-back names that didn't fire
    gate_fails = {}          # tally of which final condition killed each pulled-back candidate

    for i in range(0, len(symbols), CHUNK):
        chunk = symbols[i:i + CHUNK]
        data = download_chunk(chunk)
        if data is None:
            print(f"Chunk {i // CHUNK + 1} failed after retries; skipping {len(chunk)} tickers.")
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
                    missing = gate_misses(r)
                    for cond in missing:
                        gate_fails[cond] = gate_fails.get(cond, 0) + 1
                    watchlist.append((sym, r["price"], missing))
            if r["fires"] or r.get("cup_fires") or r.get("flat_fires") or r.get("chan_fires"):
                hits.append((sym, r))
        time.sleep(CHUNK_PAUSE)

    print(f"\nFUNNEL: scanned {scanned} | uptrends {uptrends} | pulled back {pulled} | "
          f"chart setups {len(hits)}")
    if gate_fails:
        print("  final-gate failures among pulled-back: " +
              ", ".join(f"{label}: {n}" for label, n in gate_fails.items()))

    # Fundamental gate (YoY revenue) + news, only for the handful of chart hits.
    enriched, drops = enrich_hits(hits)

    if enriched:
        print(f"\nBUY setups after revenue gate ({len(enriched)}):")
        for h in enriched:
            r = h["r"]
            print(f"  BUY {h['sym']}: ${r['price']:.2f}  stop ${r['stop']:.2f}  "
                  f"target ${r['resistance']:.2f}  [{h['rev_label']}]")
    # Near misses: pulled-back names missing exactly ONE condition (closest to firing).
    near_misses = [(sym, price, missing[0]) for sym, price, missing in watchlist if len(missing) == 1]
    if watchlist:
        print("\nWatchlist (pulled back, awaiting confirmation):")
        for sym, price, missing in watchlist[:10]:
            print(f"  {sym} ${price:.2f}: missing {', '.join(missing) or '?'}")

    summary = build_summary(len(symbols), scanned, uptrends, pulled, enriched, used_fallback,
                            gate_fails=gate_fails, near_misses=near_misses, drops=drops)
    sent = send_long(summary)
    if sent:
        print(f"\nSummary sent in {sent} message(s).")
    else:
        print("\nSummary message FAILED to send (check TELEGRAM_TOKEN / TELEGRAM_CHAT_ID).")


if __name__ == "__main__":
    main()
