"""Interactive Telegram chat bot for the stock screener.

Runs every few minutes from GitHub Actions: polls Telegram for new messages,
answers them, and persists a trade journal back into the repo. Talk to it like:

  NVDA                      -> full analysis of NVDA
  what about AFL?           -> full analysis of AFL
  bought AFL at 114.50      -> records an open position
  bought AFL at 114 for $10 -> records position sized at $10
  sold AFL at 120           -> closes it, logs the win/loss
  positions                 -> your open positions + live P&L
  history                   -> closed trades, win/loss record
  learn                     -> what your losing trades had in common (+ AI review)
  help                      -> this list

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
             "LOOK", "ANALYZE", "ANALYSE", "CHECK", "POSITIONS", "HISTORY", "LEARN", "HELP", "USD", "I"}


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


def get_updates(offset):
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    params = {"timeout": 0}
    if offset is not None:
        params["offset"] = offset
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=25)
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
    user = (f"Stock: {sym}\nComputed indicators: {facts}\n"
            f"Recent news headlines: {news[:3]}\n"
            f"My trading history: {hist}\n\n"
            "In 4-6 sentences give your honest opinion on this stock for my strategy: does it fit, "
            "what's the risk, and would you wait or act? Plain language.")
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


HELP = ("I can analyze stocks and track your trades. Try:\n"
        "• NVDA  — analyze a stock\n"
        "• what about AFL?  — same thing\n"
        "• bought AFL at 114.50  — record a buy (add 'for $10' to size it)\n"
        "• sold AFL at 120  — close it & log win/loss\n"
        "• positions  — open trades + live P&L\n"
        "• history  — closed trades\n"
        "• learn  — what your losing trades have in common\n"
        "• help  — this message")


def handle_message(text, trades):
    low = text.strip().lower()
    if low in ("help", "/help", "start", "/start"):
        return HELP
    if low in ("positions", "/positions", "portfolio"):
        return handle_positions(trades)
    if low in ("history", "/history", "trades"):
        return handle_history(trades)
    if low in ("learn", "/learn", "why"):
        return handle_learn(trades)
    trade = parse_trade(text)
    if trade:
        action, sym, price, amount, shares = trade
        return handle_sell(sym, price, trades) if action == "sell" else handle_buy(sym, price, amount, shares, trades)
    sym = extract_ticker(text)
    if not sym:
        return "I didn't catch a stock symbol. " + HELP
    r, rev_status, rev_label, news = analyze_symbol(sym)
    report = rule_report(sym, r, rev_status, rev_label, news)
    ai = ai_opinion(sym, r, rev_label, news, trades)
    if ai:
        report += "\n\n\U0001F916 " + ai
    return report


def main():
    state = load_json(STATE_FILE, {"offset": None})
    trades = load_json(TRADES_FILE, {"open": [], "closed": []})
    offset = state.get("offset")
    processed = 0
    delete_webhook()   # ensure polling isn't blocked by a stale webhook

    while True:
        updates = get_updates(offset)
        if not updates:   # None (conflict) or [] (drained) -> done for this cycle
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

    state["offset"] = offset
    save_json(STATE_FILE, state)
    save_json(TRADES_FILE, trades)
    print(f"Processed {processed} message(s).")


if __name__ == "__main__":
    main()
