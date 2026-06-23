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
ENTRY_MIN_PCT = 3.0    # price must be 3-8% above the recent higher low
ENTRY_MAX_PCT = 8.0
NEAR_SUPPORT_PCT = 6.0 # price must be within this % above the support line (tight pullback)
RECENT_LOW_MAX_BARS = 40  # the bounce low must be recent (a fresh pullback, not a stale one)
VOL_MULT = 1.0         # bounce-day volume must beat the prior 20-day average by this multiple
STOP_PCT = 4.0
MAX_SWING_PCT = 20.0   # reject a stock if ANY single day (up OR down) moved this % or more — too erratic
CHUNK = 50             # download this many tickers at a time
CHUNK_PAUSE = 1.0      # seconds to pause between chunks (be gentle on the data source)


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

    higher_highs = high_last[1] > high_prev[1]                       # each high above the last high
    higher_lows = low_last[1] > low_prev[1]                          # pullback bottoms above the prior low
    is_uptrend = higher_highs and higher_lows and sup_slope > 0      # classic uptrend staircase
    low_bars_ago = x - low_last[0]
    coming_off_recent_low = (low_last[0] > high_last[0]) and (low_bars_ago <= RECENT_LOW_MAX_BARS)
    near_support = support <= price <= support * (1 + NEAR_SUPPORT_PCT / 100)   # tight pullback
    pct = (price - low_last[1]) / low_last[1] * 100
    in_zone = ENTRY_MIN_PCT <= pct <= ENTRY_MAX_PCT
    turning_up = closes[-1] > closes[-2]
    prior = vols[-21:-1]                                             # prior up-to-20 days, excludes today
    prev_avg_vol = sum(prior) / len(prior) if prior else 0          # divide by what we actually have
    volume_ok = prev_avg_vol > 0 and vols[-1] > VOL_MULT * prev_avg_vol  # volume confirmation

    pulled_back = is_uptrend and coming_off_recent_low and near_support and in_zone and price < resistance
    # Stability guard: reject erratic names that had a violent single-day move (up OR down) over the
    # lookback (e.g. CRVL/FLEX). Crazy jumps = inconsistent = untrustworthy, so never suggest them.
    worst_drop, biggest_jump = largest_daily_swing(closes)
    worst_swing = worst_drop if abs(worst_drop) >= biggest_jump else biggest_jump
    erratic = (worst_drop <= -MAX_SWING_PCT) or (biggest_jump >= MAX_SWING_PCT)
    fires = pulled_back and turning_up and volume_ok and not erratic
    return dict(price=price, pct=pct, is_uptrend=is_uptrend, pulled_back=pulled_back,
                fires=fires, resistance=resistance, stop=price * (1 - STOP_PCT / 100),
                higher_highs=higher_highs, higher_lows=higher_lows, near_support=near_support,
                in_zone=in_zone, volume_ok=volume_ok, turning_up=turning_up,
                erratic=erratic, worst_swing=round(worst_swing, 1),
                support=support, sup_slope=sup_slope)


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


def revenue_growth(sym):
    """Year-over-year revenue check: latest quarter vs the same quarter a year ago.
    Returns (status, label) where status is 'yes' (growing), 'no' (declining), or
    'unknown' (not enough data). Only called for stocks that pass the chart screen."""
    try:
        t = yf.Ticker(sym)
        df = None
        for attr in ("quarterly_income_stmt", "quarterly_financials"):
            df = getattr(t, attr, None)
            if df is not None and not df.empty and "Total Revenue" in df.index:
                break
            df = None
        if df is None:
            return ("unknown", "rev n/a")
        rev = df.loc["Total Revenue"].dropna()
        # columns are quarter-end dates; sort newest-first
        rev = rev.sort_index(ascending=False)
        if len(rev) < 5:
            return ("unknown", "rev n/a")          # need 5 quarters for a YoY compare
        latest = float(rev.iloc[0]); year_ago = float(rev.iloc[4])
        if year_ago == 0:
            return ("unknown", "rev n/a")
        pct = (latest - year_ago) / abs(year_ago) * 100
        if latest > year_ago:
            return ("yes", f"rev +{pct:.0f}% YoY")
        return ("no", f"rev {pct:.0f}% YoY")
    except Exception:
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
    """For each chart-screen hit, add the YoY revenue status and recent news.
    Drops names whose revenue is clearly declining (if DROP_IF_REVENUE_DECLINING).
    Returns a list of dicts."""
    enriched = []
    for sym, r in hits:
        status, rev_label = revenue_growth(sym)
        if REQUIRE_CONFIRMED_GROWTH and status != "yes":
            reason = "declining" if status == "no" else "growth unverifiable"
            print(f"  drop {sym}: {rev_label} ({reason})")
            continue
        news = fetch_news(sym)
        try:
            # Sonnet sharpens the verdict; web search per setup is opt-in (XRAY_WEB=1) to control cost
            xr = xray.xray(sym, ai=True, web=os.environ.get("XRAY_WEB") == "1")
        except Exception as e:
            print(f"  xray failed for {sym}: {e}")
            xr = None
        enriched.append(dict(sym=sym, r=r, rev_status=status, rev_label=rev_label, news=news, xray=xr))
        time.sleep(0.3)   # be gentle on the news/fundamentals endpoints
    return enriched


def build_summary(universe_n, scanned, uptrends, pulled, hits, used_fallback):
    if scanned == 0:
        return (f"⚠️ Stock bot: scan FAILED — 0 of {universe_n} symbols "
                f"returned data (likely rate-limited or a network error). No reliable "
                f"signal today.")
    rev_icon = {"yes": "✅", "no": "⚠️", "unknown": "❓"}
    lines = [f"\U0001F4CA Daily scan: {scanned} scanned | {uptrends} uptrends | "
             f"{pulled} pulled back | {len(hits)} BUY setup(s)"]
    if used_fallback:
        lines.append("(used fallback symbol list — live universe fetch failed)")
    if not hits:
        lines.append("\nNo buy setups today (in an uptrend, pulled back to a higher low, "
                     "bouncing on volume, with growing revenue).")
        return "\n".join(lines)

    lines.append("")
    lines.append("\U0001F6A8 BUY setups (ranked by fundamental health score):")
    hits = sorted(hits, key=lambda h: (h.get("xray") or {}).get("score", 0), reverse=True)
    for h in hits:
        r = h["r"]
        lines.append("")
        lines.append(f"{h['sym']}: ${r['price']:.2f} | stop ${r['stop']:.2f} | "
                     f"target ${r['resistance']:.2f}")
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
    watchlist = []

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
                    watchlist.append((sym, r["pct"]))
            if r["fires"]:
                hits.append((sym, r))
        time.sleep(CHUNK_PAUSE)

    print(f"\nFUNNEL: scanned {scanned} | uptrends {uptrends} | pulled back {pulled} | "
          f"chart setups {len(hits)}")

    # Fundamental gate (YoY revenue) + news, only for the handful of chart hits.
    enriched = enrich_hits(hits)

    if enriched:
        print(f"\nBUY setups after revenue gate ({len(enriched)}):")
        for h in enriched:
            r = h["r"]
            print(f"  BUY {h['sym']}: ${r['price']:.2f}  stop ${r['stop']:.2f}  "
                  f"target ${r['resistance']:.2f}  [{h['rev_label']}]")
    if watchlist:
        print("\nWatchlist (pulled back, awaiting confirmation):")
        for sym, pct in watchlist[:10]:
            print(f"  {sym}: {pct:.1f}% off low")

    summary = build_summary(len(symbols), scanned, uptrends, pulled, enriched, used_fallback)
    sent = send_long(summary)
    if sent:
        print(f"\nSummary sent in {sent} message(s).")
    else:
        print("\nSummary message FAILED to send (check TELEGRAM_TOKEN / TELEGRAM_CHAT_ID).")


if __name__ == "__main__":
    main()
