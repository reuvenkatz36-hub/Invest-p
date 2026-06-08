"""Interactive Telegram chat bot for the stock screener.

Runs every few minutes from GitHub Actions: polls Telegram for new messages,
answers them, and persists a trade journal back into the repo. Talk to it like:

  NVDA / what about AFL?    -> full stock analysis vs the strategy
  /news NVDA                -> aggregated headlines from many free sources
  /price NVDA               -> quick price + day move + 52w range
  /earnings NVDA            -> next earnings date
  bought 10 AFL at 114.50   -> records an open position (/buy works too)
  sold AFL at 120           -> closes it, logs the win/loss (/sell works too)
  positions / /stats        -> open positions, live P&L, portfolio summary
  /remove NVDA              -> delete a position logged by mistake
  history / learn           -> closed trades; what your losers had in common
  /watch NVDA, /watchlist, /scan -> personal watchlist + on-demand scan
  /strategy                 -> explain the rules
  help / /help              -> the full command list (also shown in the "/" menu)

Analysis is rule-based (same indicators as the daily screener). If an
ANTHROPIC_API_KEY secret is present, a written AI opinion is added on top.
"""

import os
import re
import json
import time
import datetime

import requests
import yfinance as yf

import signal_bot as sb   # reuse evaluate / revenue_growth / fetch_news / get_ohlcv

TOKEN = os.environ["TELEGRAM_TOKEN"]
OWNER_CHAT_ID = str(os.environ["TELEGRAM_CHAT_ID"])
CHAT_MODEL = os.environ.get("CHAT_MODEL", "claude-opus-4-8")

STATE_FILE = "bot_state.json"
TRADES_FILE = "trades.json"

STRATEGY_BRIEF = (
    "You are a stock trading assistant for a beginner investor. The strategy is: buy a stock that is in a "
    "clear UPTREND (higher highs AND higher lows), that has pulled back DOWN to a HIGHER LOW and is just "
    "starting to bounce 3-8% off that low on above-average volume, AND whose revenue is growing year-over-year. "
    "Stop loss is ~4% below entry; target is the resistance trendline. Be concise, practical and honest. "
    "Never give guarantees; this is not financial advice. Explain WHY in plain language a beginner understands."
)

STOPWORDS = {"BUY", "BOUGHT", "BOT", "SELL", "SOLD", "AT", "FOR", "THE", "OF", "IN", "A", "AN",
             "SHARE", "SHARES", "STOCK", "STOCKS", "ABOUT", "THINK", "WHAT", "DO", "YOU", "IS",
             "IT", "ON", "AND", "ME", "MY", "TO", "WORTH", "GOOD", "BAD", "HEY", "HI", "PLEASE",
             "LOOK", "ANALYZE", "ANALYSE", "CHECK", "POSITIONS", "HISTORY", "LEARN", "HELP", "USD", "I",
             "NEWS", "HEADLINES", "PRICE", "QUOTE", "EARNINGS", "STATS", "SUMMARY", "SCAN", "WATCH",
             "WATCHLIST", "UNWATCH", "STRATEGY", "RULES", "REMOVE", "DELETE", "FORGET", "PORTFOLIO",
             "HOLDINGS", "MENU", "COMMANDS", "START", "TODAY", "NOW", "DAILY", "MARKET", "FULL"}

# The bot's "memory": red flags it looks for in your OWN losing trades, so it can warn
# you when a new candidate repeats the same mistake. Each entry is
#   (human label, was-flag-present-in-this-past-trade?, is-flag-present-in-candidate-now?)
# `in_loss` reads a stored setup snapshot; `in_now` reads a fresh analysis (r, rev_status).
LOSS_FLAGS = [
    ("no full buy signal",
     lambda s: s.get("fires") is False, lambda r, rev: not r["fires"]),
    ("below-average bounce volume",
     lambda s: s.get("volume_ok") is False, lambda r, rev: not r["volume_ok"]),
    ("unconfirmed/declining revenue",
     lambda s: s.get("rev_status") not in (None, "yes"), lambda r, rev: rev != "yes"),
    ("a shaky (non-)uptrend",
     lambda s: s.get("is_uptrend") is False, lambda r, rev: not r["is_uptrend"]),
    ("entry outside the 3-8% buy zone",
     lambda s: s.get("in_zone") is False, lambda r, rev: not r["in_zone"]),
]


def loss_patterns(trades):
    """Recurring red flags across the user's losing trades.
    Returns (list of '3/4 losses had X' strings, number_of_losses)."""
    losses = [t for t in trades.get("closed", []) if t.get("outcome") == "loss"]
    n = len(losses)
    out = []
    for label, in_loss, _ in LOSS_FLAGS:
        cnt = sum(1 for t in losses if in_loss(t.get("setup", {})))
        if cnt >= 2 and cnt / n >= 0.5:          # showed up in at least half (and 2+) of losses
            out.append(f"{cnt}/{n} losses had {label}")
    return out, n


def memory_warnings(sym, r, rev_status, trades, limit=3):
    """Compare a candidate against the user's own past losses. Returns plain-language
    warnings — empty if nothing rhymes with a previous mistake."""
    losses = [t for t in trades.get("closed", []) if t.get("outcome") == "loss"]
    warns = []
    lost_syms = [t["sym"] for t in losses]
    if sym in lost_syms:                          # you've been burned by this exact ticker
        warns.append(f"You've taken a loss on {sym} before ({lost_syms.count(sym)}×) — "
                     "make sure this setup is genuinely different.")
    if r is not None and losses:                  # this candidate repeats a recurring red flag
        n = len(losses)
        for label, in_loss, in_now in LOSS_FLAGS:
            cnt = sum(1 for t in losses if in_loss(t.get("setup", {})))
            try:
                now_bad = in_now(r, rev_status)
            except Exception:
                now_bad = False
            if cnt >= 2 and cnt / n >= 0.5 and now_bad:
                warns.append(f"{cnt} of your {n} losses had {label} — and {sym} has it too right now.")
    return warns[:limit]


def memory_block(sym, r, rev_status, trades):
    warns = memory_warnings(sym, r, rev_status, trades)
    if not warns:
        return ""
    return "\n\n\U0001F9E0 From your own history:\n" + "\n".join(f"• {w}" for w in warns)


# ---------- persistence ----------
def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ---------- telegram ----------
def send(chat_id, text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=15)
    except requests.RequestException as e:
        print(f"send failed: {e}")


def delete_webhook():
    """Clear any registered webhook so getUpdates polling works (we use polling)."""
    try:
        requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook", timeout=15)
    except requests.RequestException:
        pass


def get_updates(offset, wait=0):
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    params = {"timeout": wait}   # >0 = long-poll: Telegram holds the request until a message arrives
    if offset is not None:
        params["offset"] = offset
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=wait + 15)
        except requests.RequestException as e:
            print(f"getUpdates network error: {e}")
            time.sleep(3)
            continue
        if r.status_code == 409:
            # Conflict: a webhook is active or another poller is briefly in flight.
            # Clear any webhook, back off, and retry before giving up the cycle.
            print(f"getUpdates 409 conflict (attempt {attempt + 1}) — clearing webhook, backing off.")
            delete_webhook()
            time.sleep(3)
            continue
        r.raise_for_status()
        return r.json().get("result", [])
    print("getUpdates still conflicting — skipping this cycle; next run will retry.")
    return None


# ---------- analysis ----------
def analyze_symbol(sym):
    """Returns (evaluate_dict_or_None, rev_status, rev_label, news_list)."""
    try:
        data = yf.download(sym, period="1y", interval="1d", auto_adjust=True,
                           progress=False, threads=False)
    except Exception:
        return None, "unknown", "rev n/a", []
    ohlcv = sb.get_ohlcv(data, sym)
    if ohlcv is None:
        return None, "unknown", "rev n/a", []
    r = sb.evaluate(*ohlcv)
    rev_status, rev_label = sb.revenue_growth(sym)
    news = sb.fetch_news(sym)
    return r, rev_status, rev_label, news


def rule_report(sym, r, rev_status, rev_label, news):
    if r is None:
        return f"{sym}: couldn't get enough price data to analyze."
    chk = lambda b: "✅" if b else "❌"
    rev_icon = {"yes": "✅", "no": "❌", "unknown": "❓"}[rev_status]
    lines = [f"\U0001F4C8 {sym} — ${r['price']:.2f}  ({r['pct']:.1f}% off the recent low)",
             f"{chk(r['is_uptrend'])} Uptrend (higher highs & higher lows)",
             f"{chk(r['near_support'])} Pulled back near support",
             f"{chk(r['in_zone'])} In the {sb.ENTRY_MIN_PCT:.0f}-{sb.ENTRY_MAX_PCT:.0f}% buy zone off the low",
             f"{chk(r['volume_ok'])} Bounce volume above average",
             f"{rev_icon} {rev_label}"]
    if r["fires"] and rev_status == "yes":
        verdict = "\U0001F7E2 STRONG — matches the full buy setup."
    elif r["pulled_back"]:
        verdict = "\U0001F7E1 WATCH — pulled back in an uptrend, waiting on the bounce + volume (and revenue)."
    elif r["is_uptrend"]:
        verdict = "⚪ Uptrend, but not at a buy point right now."
    else:
        verdict = "\U0001F534 Not an uptrend setup right now."
    lines += ["", verdict]
    if r["fires"]:
        lines.append(f"Entry ${r['price']:.2f} | stop ${r['stop']:.2f} | target ${r['resistance']:.2f}")
    if news:
        lines.append("\nNews:")
        lines += [f"• {n}" for n in news[:3]]
    return "\n".join(lines)


def ai_opinion(sym, r, rev_label, news, trades):
    """Optional AI-written opinion. Returns text or None if no key / failure."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic
    except ImportError:
        return None
    facts = "no clean setup data" if r is None else (
        f"price=${r['price']:.2f}, {r['pct']:.1f}% off low, uptrend={r['is_uptrend']}, "
        f"higher_highs={r['higher_highs']}, higher_lows={r['higher_lows']}, near_support={r['near_support']}, "
        f"in_buy_zone={r['in_zone']}, volume_above_avg={r['volume_ok']}, full_buy_signal={r['fires']}, "
        f"{rev_label}, stop=${r['stop']:.2f}, target=${r['resistance']:.2f}")
    closed = trades.get("closed", [])
    losses = [t for t in closed if t.get("outcome") == "loss"]
    hist = (f"{len(closed)} closed trades, {len(losses)} losses. "
            f"Recent: {[ (t['sym'], t.get('outcome')) for t in closed[-5:] ]}") if closed else "no trade history yet"
    patterns, _ = loss_patterns(trades)
    patt_str = "; ".join(patterns) if patterns else "no clear recurring pattern yet"
    user = (f"Stock: {sym}\nComputed indicators: {facts}\n"
            f"Recent news headlines: {news[:3]}\n"
            f"My trading history: {hist}\n"
            f"My recurring loss patterns: {patt_str}\n\n"
            "In 4-6 sentences give your honest opinion on this stock for my strategy: does it fit, "
            "what's the risk, and would you wait or act? If this stock repeats any of my recurring "
            "loss patterns, explicitly call it out. Plain language.")
    try:
        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model=CHAT_MODEL,
            max_tokens=1500,
            system=STRATEGY_BRIEF,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()
    except Exception as e:
        print(f"AI opinion failed: {e}")
        return None


def setup_snapshot(r, rev_status):
    if r is None:
        return {"rev_status": rev_status}
    return {k: r[k] for k in ("is_uptrend", "higher_highs", "higher_lows", "near_support",
                              "in_zone", "volume_ok", "fires", "pct")} | {"rev_status": rev_status}


# ---------- message parsing ----------
def extract_ticker(text):
    for tok in re.findall(r"\b([A-Za-z]{1,5}(?:\.[A-Za-z])?)\b", text):
        if tok.upper() not in STOPWORDS:
            return tok.upper()
    return None


def parse_trade(text):
    low = text.lower()
    if re.search(r"\b(sold|sell)\b", low):
        action = "sell"
    elif re.search(r"\b(bought|buy|bot)\b", low):
        action = "buy"
    else:
        return None

    # optional share quantity: "bought 15 dac", "buy 40 tcbk", "15 shares of dac"
    shares = None
    m = re.search(r"\b(?:bought|buy|bot|sold|sell)\s+(\d+)\b", low)
    if m:
        shares = int(m.group(1))
    else:
        m = re.search(r"\b(\d+)\s+shares?\b", low)
        if m:
            shares = int(m.group(1))

    sym = None
    m = re.search(r"\b([A-Z]{1,5}(?:\.[A-Z])?)\b", text)   # prefer an explicit uppercase ticker
    if m and m.group(1) not in STOPWORDS:
        sym = m.group(1)
    if sym is None:   # "bought [15] dac" / "buy dac" (ticker right after the verb, qty optional)
        m = re.search(r"\b(?:bought|buy|bot|sold|sell)\s+(?:\d+\s+)?([A-Za-z]{1,5})\b", low)
        if m and m.group(1).upper() not in STOPWORDS:
            sym = m.group(1).upper()
    if sym is None:
        m = re.search(r"\b(?:of|in)\s+([A-Za-z]{1,5})\b", low)
        if m and m.group(1).upper() not in STOPWORDS:
            sym = m.group(1).upper()

    # explicit dollar position size: "for $10"
    amount = None
    m = re.search(r"for\s*\$(\d+(?:\.\d+)?)", low)
    if m:
        amount = float(m.group(1))

    # price per share: "at 114", "@ 114.50", or a bare "for 131.58" (no $ = a price, not a size)
    price = None
    m = re.search(r"(?:at|@)\s*\$?(\d+(?:\.\d+)?)", low)
    if m:
        price = float(m.group(1))
    if price is None:
        m = re.search(r"\bfor\s+(\d+(?:\.\d+)?)\b", low)
        if m:
            price = float(m.group(1))
    if price is None:   # last resort: last number in the message that isn't the share count
        nums = [n for n in re.findall(r"\$?(\d+(?:\.\d+)?)", text)
                if shares is None or float(n) != float(shares)]
        if nums:
            price = float(nums[-1])

    if not sym or price is None:
        return None
    return action, sym, price, amount, shares


# ---------- handlers ----------
def handle_buy(sym, price, amount, shares, trades):
    # Don't double-log: if an identical open position already exists (same symbol, entry
    # and share count), treat a repeat as a no-op instead of creating a duplicate.
    for p in trades.get("open", []):
        if p.get("sym") == sym and abs((p.get("entry") or 0) - price) < 1e-6 and p.get("shares") == shares:
            return (f"ℹ️ You already have an open {sym} position at ${price:.2f} on record — "
                    "I didn't add a duplicate. Send 'positions' to see your holdings.")
    r, rev_status, rev_label, _ = analyze_symbol(sym)
    if amount is None and shares is not None:   # derive $ size from shares × price
        amount = round(shares * price, 2)
    trades.setdefault("open", []).append({
        "sym": sym, "entry": price, "amount": amount, "shares": shares,
        "date": datetime.date.today().isoformat(),
        "setup": setup_snapshot(r, rev_status),
    })
    size = []
    if shares:
        size.append(f"{shares} sh")
    if amount:
        size.append(f"${amount:.0f}")
    extra = f" ({', '.join(size)})" if size else ""
    note = ""
    if r is not None and not r["fires"]:
        note = "\n⚠️ Heads up: this isn't a full buy signal on our strategy right now."
    note += memory_block(sym, r, rev_status, trades)   # remind you of similar past losses
    return f"\U0001F4DD Recorded BUY {sym} @ ${price:.2f}{extra}. Good luck!{note}"


def handle_sell(sym, price, trades):
    opens = trades.setdefault("open", [])
    idx = next((i for i, t in enumerate(opens) if t["sym"] == sym), None)
    if idx is None:
        return f"I don't have an open {sym} position on record. Tell me 'bought {sym} at <price>' first."
    pos = opens.pop(idx)
    pnl_pct = (price - pos["entry"]) / pos["entry"] * 100
    outcome = "win" if pnl_pct >= 0 else "loss"
    pnl_usd = pos["amount"] * pnl_pct / 100 if pos.get("amount") else None
    rec = {**pos, "exit": price, "pnl_pct": pnl_pct, "outcome": outcome,
           "pnl_usd": pnl_usd, "close_date": datetime.date.today().isoformat()}
    trades.setdefault("closed", []).append(rec)
    usd = f" ({'+' if pnl_usd and pnl_usd >= 0 else ''}${pnl_usd:.2f})" if pnl_usd is not None else ""
    emoji = "\U0001F7E2" if outcome == "win" else "\U0001F534"
    msg = f"{emoji} Closed {sym}: {pnl_pct:+.1f}%{usd}. Logged as a {outcome}."
    if outcome == "loss":
        msg += "\nSend 'learn' and I'll look at what your losers have in common."
    return msg


def handle_positions(trades):
    opens = trades.get("open", [])
    if not opens:
        return "No open positions on record."
    lines = ["\U0001F4BC Open positions:"]
    for t in opens:
        live = ""
        try:
            data = yf.download(t["sym"], period="5d", interval="1d", auto_adjust=True,
                               progress=False, threads=False)
            last = float(data["Close"].dropna().iloc[-1])
            pct = (last - t["entry"]) / t["entry"] * 100
            live = f" | now ${last:.2f} ({pct:+.1f}%)"
        except Exception:
            pass
        amt = f" ${t['amount']:.0f}" if t.get("amount") else ""
        lines.append(f"• {t['sym']} @ ${t['entry']:.2f}{amt}{live}")
    return "\n".join(lines)


def handle_history(trades):
    closed = trades.get("closed", [])
    if not closed:
        return "No closed trades yet."
    wins = [t for t in closed if t["outcome"] == "win"]
    lines = [f"\U0001F4D3 {len(closed)} closed | {len(wins)} wins | {len(closed) - len(wins)} losses"]
    for t in closed[-10:]:
        lines.append(f"• {t['sym']}: {t['entry']:.2f}→{t['exit']:.2f}  {t['pnl_pct']:+.1f}%  ({t['outcome']})")
    return "\n".join(lines)


def handle_learn(trades):
    closed = trades.get("closed", [])
    losses = [t for t in closed if t["outcome"] == "loss"]
    if not closed:
        return ("No closed trades yet, so nothing to learn from. Tell me when you buy and sell "
                "(e.g. 'sold AFL at 120') and I'll start spotting patterns in your losers.")
    lines = [f"\U0001F4DA Review: {len(closed)} closed | {len(losses)} losses"]
    if losses:
        off_system = sum(1 for t in losses if not t.get("setup", {}).get("fires"))
        bad_rev = sum(1 for t in losses if t.get("setup", {}).get("rev_status") != "yes")
        no_vol = sum(1 for t in losses if not t.get("setup", {}).get("volume_ok"))
        avg = sum(t["pnl_pct"] for t in losses) / len(losses)
        lines.append(f"• Average loss: {avg:.1f}%")
        lines.append(f"• {off_system}/{len(losses)} losses were bought WITHOUT a full buy signal")
        lines.append(f"• {bad_rev}/{len(losses)} losses had unconfirmed/declining revenue")
        lines.append(f"• {no_vol}/{len(losses)} losses lacked above-average bounce volume")
        patterns, _ = loss_patterns(trades)
        if patterns:
            lines.append("")
            lines.append("\U0001F9E0 I'll now warn you when a new stock repeats these:")
            lines += [f"• {p}" for p in patterns]
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=key)
            resp = client.messages.create(
                model=CHAT_MODEL, max_tokens=1500, system=STRATEGY_BRIEF,
                messages=[{"role": "user", "content":
                           "Here are my closed trades (JSON). In 4-6 sentences, tell me what my losing "
                           "trades have in common and ONE concrete change to my rules that might help. "
                           "Be specific and honest.\n\n" + json.dumps(closed[-30:])}],
            )
            txt = "".join(b.text for b in resp.content if b.type == "text").strip()
            if txt:
                lines += ["", "\U0001F916 " + txt]
        except Exception as e:
            print(f"learn AI failed: {e}")
    return "\n".join(lines)


# Canonical command list — drives /help AND the native Telegram "/" menu (setMyCommands).
# (command, one-line description). Keep descriptions single-line and < 256 chars.
# (command, clean menu description, optional example). The example is shown only in /help —
# the in-app "/" menu uses just the description so it doesn't repeat a sample ticker everywhere.
COMMANDS = [
    ("help",       "Show every command I understand",            ""),
    ("analyze",    "Analyze a stock vs the strategy",            "/analyze AAPL"),
    ("news",       "Latest news for a stock",                    "/news AAPL"),
    ("price",      "Quick price & day move",                     "/price AAPL"),
    ("earnings",   "Next earnings date for a stock",             "/earnings AAPL"),
    ("buy",        "Log a buy",                                  "/buy 10 AAPL at 240"),
    ("sell",       "Log a sell",                                 "/sell AAPL at 255"),
    ("positions",  "Your open positions + live P&L",             ""),
    ("remove",     "Delete a position logged by mistake",        "/remove AAPL"),
    ("history",    "Closed trades & win/loss record",            ""),
    ("stats",      "Portfolio summary: invested, P&L, win rate", ""),
    ("learn",      "What your losing trades have in common",     ""),
    ("watch",      "Add a stock to your watchlist",              "/watch AAPL"),
    ("unwatch",    "Remove a stock from your watchlist",         "/unwatch AAPL"),
    ("watchlist",  "Show your watchlist",                        ""),
    ("scan",       "Scan watchlist + positions for buy setups",  ""),
    ("daily",      "Run the full daily market scan now",         ""),
    ("strategy",   "Explain the trading strategy",               ""),
]

HELP = ("🤖 Everything I can do:\n\n"
        + "\n".join(f"/{c} — {d}" + (f"  (e.g. {ex})" if ex else "") for c, d, ex in COMMANDS)
        + "\n\nNote: tickers in the examples (AAPL) are just samples — use ANY stock you want."
        + "\n\nNo slash needed for the basics — you can just type a ticker (NVDA), "
          "or talk normally: 'bought 10 nvda at 240', 'positions', 'news on AFL'.")

STRATEGY_TEXT = (
    "📈 The strategy in plain English:\n"
    "1) UPTREND — the stock makes higher highs AND higher lows.\n"
    "2) PULLBACK — it dips back to a higher low (doesn't break the trend).\n"
    "3) BOUNCE — it's 3–8% up off that low and turning up on above-average volume.\n"
    "4) REVENUE growing year-over-year.\n\n"
    "When all 4 line up → BUY. Stop-loss ~4% below entry; target is the resistance line.\n"
    "One position at a time, cut losers fast. Not financial advice — always check the news first."
)


def analyze_and_report(sym, trades):
    r, rev_status, rev_label, news = analyze_symbol(sym)
    report = rule_report(sym, r, rev_status, rev_label, news)
    report += memory_block(sym, r, rev_status, trades)   # warn about repeats of past mistakes
    ai = ai_opinion(sym, r, rev_label, news, trades)
    if ai:
        report += "\n\n\U0001F916 " + ai
    return report


def quick_eval(sym):
    """Lightweight analyze for /scan: chart + revenue, but skips the news fetch."""
    try:
        data = yf.download(sym, period="1y", interval="1d", auto_adjust=True,
                           progress=False, threads=False)
    except Exception:
        return None, "unknown"
    ohlcv = sb.get_ohlcv(data, sym)
    if ohlcv is None:
        return None, "unknown"
    rev_status, _ = sb.revenue_growth(sym)
    return sb.evaluate(*ohlcv), rev_status


def handle_news(sym):
    items = sb.fetch_news_items(sym, limit=8)
    if not items:
        return f"No news found for {sym} right now."
    lines = [f"\U0001F4F0 News for {sym}:"]
    for it in items:
        src = f"  [{it['source']}]" if it.get("source") else ""
        lines.append(f"• {it['title']}{src}")
    lines.append(f"\nMore: {sb.news_link(sym)}")
    return "\n".join(lines)


def handle_quote(sym):
    try:
        data = yf.download(sym, period="1y", interval="1d", auto_adjust=True,
                           progress=False, threads=False)
        closes = data["Close"].dropna()
        last = float(closes.iloc[-1])
        prev = float(closes.iloc[-2]) if len(closes) > 1 else last
        chg = (last - prev) / prev * 100 if prev else 0.0
        hi = float(data["High"].dropna().max())
        lo = float(data["Low"].dropna().min())
        arrow = "\U0001F7E2" if chg >= 0 else "\U0001F534"
        return (f"\U0001F4B5 {sym}: ${last:.2f}  {arrow} {chg:+.1f}% (vs prev close)\n"
                f"52-week range: ${lo:.2f} – ${hi:.2f}")
    except Exception:
        return f"Couldn't fetch a price for {sym}."


def handle_earnings(sym):
    try:
        import pandas as pd
        df = yf.Ticker(sym).get_earnings_dates(limit=12)
        if df is not None and len(df):
            now = pd.Timestamp.now(tz=df.index.tz)
            future = sorted(d for d in df.index if d >= now)
            if future:
                return f"\U0001F4C5 {sym}: next earnings ~ {future[0].date().isoformat()}"
            past = sorted(df.index)
            return f"\U0001F4C5 {sym}: no upcoming date posted; last reported {past[-1].date().isoformat()}"
    except Exception:
        pass
    return f"Couldn't find an earnings date for {sym}."


def handle_remove(sym, trades):
    opens = trades.get("open", [])
    idx = next((i for i, t in enumerate(opens) if t["sym"] == sym), None)
    if idx is None:
        return f"No open {sym} position to remove."
    opens.pop(idx)
    return f"\U0001F5D1 Removed {sym} from your open positions (no win/loss logged)."


def handle_stats(trades):
    opens = trades.get("open", [])
    closed = trades.get("closed", [])
    invested = sum(p.get("amount") or 0 for p in opens)
    cur, priced_all = 0.0, True
    for p in opens:
        try:
            data = yf.download(p["sym"], period="5d", interval="1d", auto_adjust=True,
                               progress=False, threads=False)
            last = float(data["Close"].dropna().iloc[-1])
            sh = p.get("shares")
            if sh is None and p.get("amount") and p.get("entry"):
                sh = p["amount"] / p["entry"]
            cur += last * (sh or 0)
        except Exception:
            priced_all = False
    wins = [t for t in closed if t.get("outcome") == "win"]
    realized = sum(t.get("pnl_usd") or 0 for t in closed)
    lines = ["\U0001F4CA Portfolio summary:",
             f"• Open positions: {len(opens)}"]
    if invested:
        lines.append(f"• Invested (open): ${invested:,.0f}")
        if priced_all and cur:
            lines.append(f"• Current value: ${cur:,.0f} ({cur - invested:+,.0f} unrealized)")
    lines.append(f"• Closed: {len(closed)} | {len(wins)} wins | {len(closed) - len(wins)} losses")
    if closed:
        lines.append(f"• Win rate: {len(wins) / len(closed) * 100:.0f}%")
        lines.append(f"• Realized P&L: ${realized:+,.0f}")
    return "\n".join(lines)


def handle_watch_add(sym, trades):
    wl = trades.setdefault("watch", [])
    if sym in wl:
        return f"{sym} is already on your watchlist."
    wl.append(sym)
    return f"\U0001F440 Added {sym} to your watchlist ({len(wl)} total). Send /scan to check them."


def handle_watch_remove(sym, trades):
    wl = trades.setdefault("watch", [])
    if sym not in wl:
        return f"{sym} isn't on your watchlist."
    wl.remove(sym)
    return f"Removed {sym} from your watchlist ({len(wl)} left)."


def handle_watchlist(trades):
    wl = trades.get("watch", [])
    if not wl:
        return "Your watchlist is empty. Add one with /watch NVDA."
    return "\U0001F440 Watchlist: " + ", ".join(wl) + "\nSend /scan to check them for buy setups."


def handle_scan(trades):
    syms = list(dict.fromkeys([p["sym"] for p in trades.get("open", [])] + trades.get("watch", [])))
    if not syms:
        return "Nothing to scan yet. Add stocks with /watch NVDA (or log a buy)."
    lines = [f"\U0001F50E Scanning {len(syms)}: {', '.join(syms)}"]
    for sym in syms[:15]:
        r, rev_status = quick_eval(sym)
        if r is None:
            lines.append(f"• {sym}: no data")
            continue
        if r["fires"] and rev_status == "yes":
            tag = "\U0001F7E2 STRONG buy setup"
        elif r["fires"]:
            tag = "\U0001F7E2 buy setup (revenue unconfirmed)"
        elif r["pulled_back"]:
            tag = "\U0001F7E1 watch — pulled back, awaiting bounce"
        elif r["is_uptrend"]:
            tag = "⚪ uptrend, no buy point"
        else:
            tag = "\U0001F534 no setup"
        lines.append(f"• {sym} ${r['price']:.2f}: {tag}")
    if len(syms) > 15:
        lines.append(f"…and {len(syms) - 15} more (showing first 15).")
    return "\n".join(lines)


def trigger_daily_scan():
    """Launch the full daily market-scan workflow (signal_bot) via the GitHub API,
    so it runs as its own job and posts results here when done. Returns (ok, error)."""
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    wf = os.environ.get("DAILY_WORKFLOW", "main.yml")
    if not token or not repo:
        return False, "the on-demand scan isn't configured (no GitHub token in this environment)."
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{wf}/dispatches"
    try:
        resp = requests.post(url, json={"ref": "main"}, timeout=15, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        if resp.status_code in (201, 204):
            return True, None
        return False, f"GitHub said {resp.status_code}: {resp.text[:140]}"
    except requests.RequestException as e:
        return False, str(e)


def handle_daily():
    ok, err = trigger_daily_scan()
    if ok:
        return ("\U0001F501 Started the full daily market scan. It runs in the background and takes "
                "a few minutes — the results will arrive here as a separate message when it's done.")
    return f"Couldn't start the daily scan: {err}"


def handle_command(cmd, arg, trades):
    """Dispatch an explicit /slash command. `arg` is the text after the command."""
    sym = extract_ticker(arg) if arg else None
    if cmd in ("help", "commands", "start", "menu", "?"):
        return HELP
    if cmd in ("analyze", "analyse", "stock", "check", "a"):
        return analyze_and_report(sym, trades) if sym else "Usage: /analyze NVDA"
    if cmd in ("news", "headlines"):
        return handle_news(sym) if sym else "Usage: /news NVDA"
    if cmd in ("price", "quote", "p"):
        return handle_quote(sym) if sym else "Usage: /price NVDA"
    if cmd in ("earnings", "earning"):
        return handle_earnings(sym) if sym else "Usage: /earnings NVDA"
    if cmd in ("buy", "bought"):
        t = parse_trade("bought " + arg)
        return apply_trade(t, trades) if t else "Usage: /buy 10 NVDA at 240"
    if cmd in ("sell", "sold"):
        t = parse_trade("sold " + arg)
        return apply_trade(t, trades) if t else "Usage: /sell NVDA at 255"
    if cmd in ("positions", "portfolio", "holdings", "pos"):
        return handle_positions(trades)
    if cmd in ("remove", "delete", "forget", "rm"):
        return handle_remove(sym, trades) if sym else "Usage: /remove NVDA"
    if cmd in ("history", "trades", "hist"):
        return handle_history(trades)
    if cmd in ("stats", "summary", "stat"):
        return handle_stats(trades)
    if cmd == "learn":
        return handle_learn(trades)
    if cmd == "watch":
        return handle_watch_add(sym, trades) if sym else "Usage: /watch NVDA"
    if cmd in ("unwatch", "unwatchlist"):
        return handle_watch_remove(sym, trades) if sym else "Usage: /unwatch NVDA"
    if cmd in ("watchlist", "watches", "wl"):
        return handle_watchlist(trades)
    if cmd == "scan":
        return handle_scan(trades)
    if cmd in ("daily", "today", "dailyscan", "marketscan", "fullscan"):
        return handle_daily()
    if cmd in ("strategy", "rules"):
        return STRATEGY_TEXT
    return f"Unknown command /{cmd}. Send /help to see everything I can do."


def set_my_commands():
    """Register the command list with Telegram so the in-app '/' menu shows them."""
    cmds = [{"command": c, "description": d} for c, d, _ex in COMMANDS]
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/setMyCommands",
                      json={"commands": cmds}, timeout=15)
    except requests.RequestException as e:
        print(f"setMyCommands failed: {e}")


def apply_trade(trade, trades):
    action, sym, price, amount, shares = trade
    if action == "sell":
        return handle_sell(sym, price, trades)
    return handle_buy(sym, price, amount, shares, trades)


def handle_message(text, trades):
    raw = text.strip()
    # ----- explicit /slash commands take priority -----
    if raw.startswith("/"):
        parts = raw[1:].split(maxsplit=1)
        if parts:
            return handle_command(parts[0].lower(), parts[1].strip() if len(parts) > 1 else "", trades)
    low = raw.lower()
    has = lambda *words: any(re.search(r"\b" + w + r"\b", low) for w in words)
    if low in ("help", "start", "commands", "menu") or has("help") or "what can you do" in low:
        return HELP
    if has("news", "headlines"):                      # "news on AFL", "AFL news"
        sym = extract_ticker(low.replace("news", " ").replace("headlines", " "))
        if sym:
            return handle_news(sym)
    # explicit trades win first, so "log my buy" style messages aren't caught by the menus below.
    # A single message can hold several trades on separate lines ("bought X\nalso bought Y") —
    # handle each so none get silently dropped.
    lines = [ln for ln in text.splitlines() if ln.strip()]
    parsed = [parse_trade(ln) for ln in lines]
    if sum(1 for p in parsed if p) >= 2:
        return "\n".join(apply_trade(p, trades) for p in parsed if p)
    trade = parse_trade(text)
    if trade:
        return apply_trade(trade, trades)
    if has("positions", "position", "portfolio", "holdings", "holding"):
        return handle_positions(trades)
    if has("history") or "my trades" in low or "track record" in low or "closed trades" in low:
        return handle_history(trades)
    if has("learn", "lessons", "patterns", "mistakes") or low == "why":
        return handle_learn(trades)
    if has("strategy", "rules"):
        return STRATEGY_TEXT
    if "daily" in low or "market scan" in low or "scan the market" in low or "full scan" in low:
        return handle_daily()
    if has("scan"):
        return handle_scan(trades)
    if has("stats", "summary"):
        return handle_stats(trades)
    sym = extract_ticker(text)
    if not sym:
        return "I didn't catch a stock symbol. " + HELP
    return analyze_and_report(sym, trades)


def main():
    state = load_json(STATE_FILE, {"offset": None})
    trades = load_json(TRADES_FILE, {"open": [], "closed": []})
    offset = state.get("offset")
    processed = 0
    delete_webhook()   # ensure polling isn't blocked by a stale webhook
    set_my_commands()  # populate the in-app "/" command menu

    # GitHub's scheduler can only start a run every few minutes (and is often late),
    # so each run stays awake for a short window, long-polling Telegram, to answer
    # messages that arrive while it's up instead of making them wait for the next run.
    window = int(os.environ.get("POLL_SECONDS", "120"))
    deadline = time.time() + window
    first = True
    while time.time() < deadline:
        updates = get_updates(offset, wait=0 if first else 20)
        first = False
        if updates is None:   # 409 conflict -> stop, next run retries
            break
        for u in updates:
            offset = u["update_id"] + 1
            msg = u.get("message") or u.get("edited_message")
            if not msg or "text" not in msg:
                continue
            if str(msg["chat"]["id"]) != OWNER_CHAT_ID:
                continue   # only talk to the owner
            text = msg["text"]
            print(f"> {text}")
            try:
                reply = handle_message(text, trades)
            except Exception as e:
                reply = f"Something went wrong handling that: {e}"
                print(f"handler error: {e}")
            send(msg["chat"]["id"], reply)
            processed += 1
        # persist after each batch so a timeout never re-answers or loses progress
        state["offset"] = offset
        save_json(STATE_FILE, state)
        save_json(TRADES_FILE, trades)

    state["offset"] = offset
    save_json(STATE_FILE, state)
    save_json(TRADES_FILE, trades)
    print(f"Processed {processed} message(s).")


if __name__ == "__main__":
    main()
