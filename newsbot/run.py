"""Main entry point — one invocation does everything that is due right now:

  1. Read your Telegram commands (/add, /remove, /list, /news, /brief, /status, /help).
  2. Scan the watchlist's news; push CRITICAL/HIGH items immediately (one alert per event).
  3. If a briefing is due, send it: pre-market (before the US open), after-close recap,
     or a market-closed digest on weekends/holidays.

Run every ~15 minutes (GitHub Actions cron). Safe to run more often: everything is
de-duplicated and every briefing is sent at most once per day.

    python -m newsbot            # normal run
    python -m newsbot --dry-run  # print instead of sending to Telegram
    python -m newsbot --brief pre|post|closed   # force a briefing (not recorded)
"""

from __future__ import annotations

import argparse
import datetime as dt
import time
import traceback
from zoneinfo import ZoneInfo

from . import ai, market, news, prices
from .config import (CONFIG_PATH, STATE_PATH, TICKER_RE, Config, Stock, load_config,
                     load_secrets, save_watchlist)
from .state import load_state, save_state
from .telegram import Telegram

IMPORTANCE_ICON = {"critical": "\U0001F534", "high": "\U0001F7E0", "medium": "\U0001F7E1", "low": "⚪"}
SENTIMENT_ICON = {"positive": "\U0001F4C8", "negative": "\U0001F4C9", "neutral": "➖", "mixed": "↕️"}
BRIEFING_WINDOW_MAX_H = 20


# --------------------------------------------------------------------------- helpers

def local(ts: dt.datetime, tz: str) -> str:
    return ts.astimezone(ZoneInfo(tz)).strftime("%a %d %b %H:%M")


def in_quiet_hours(now: dt.datetime, cfg: Config) -> bool:
    if not cfg.quiet_enabled:
        return False
    t = now.astimezone(ZoneInfo(cfg.timezone)).time()
    start = dt.time.fromisoformat(cfg.quiet_start)
    end = dt.time.fromisoformat(cfg.quiet_end)
    return (start <= t or t < end) if start > end else (start <= t < end)


def format_alert(group: list[tuple[news.Article, ai.Classified]], tz: str) -> str:
    art, c = group[0]
    lines = [
        f"{IMPORTANCE_ICON[c.importance]} {c.importance.upper()} · {art.ticker} · "
        f"{SENTIMENT_ICON[c.sentiment]} {c.sentiment}",
        "",
        art.title,
        "",
        c.summary,
        "",
        f"\U0001F552 {local(art.published, tz)} ({tz.split('/')[-1]} time) · {art.source}",
        art.url,
    ]
    if len(group) > 1:
        lines.append("")
        lines.append(f"Also covered by {len(group) - 1} more source(s):")
        for a, _ in group[1:4]:
            lines.append(f"• {a.source}: {a.url}")
    return "\n".join(lines)


def alert_record(art: news.Article, c: ai.Classified) -> dict:
    return {"ts": time.time(), "ticker": art.ticker, "title": art.title, "event": c.event_key}


def queue_record(art: news.Article, c: ai.Classified | None) -> dict:
    d = art.to_dict()
    if c:
        d.update(importance=c.importance, sentiment=c.sentiment, summary=c.summary, event=c.event_key)
    return d


# --------------------------------------------------------------------------- news scan

def scan(cfg: Config, state: dict, tg: Telegram, secrets, articles: list[news.Article],
         now: dt.datetime) -> None:
    known = set(state.setdefault("known_tickers", []))
    fresh = [a for a in articles if a.key not in state["seen"]]
    ts = time.time()

    # First run (or lost state) and newly added tickers: absorb existing news silently.
    silent = [a for a in fresh if not state["bootstrapped"] or a.ticker not in known]
    for a in silent:
        state["seen"][a.key] = ts
    state["known_tickers"] = sorted(known | set(cfg.tickers()))
    fresh = [a for a in fresh if a.key not in state["seen"]]
    if not state["bootstrapped"]:
        state["bootstrapped"] = True
        tg.send(f"✅ News bot is live. Watching {len(cfg.watchlist)} stocks: "
                f"{', '.join(cfg.tickers())}.\nAbsorbed {len(silent)} existing headlines silently — "
                f"you'll only get alerts for news from now on. Send /help for commands.")

    quiet = in_quiet_hours(now, cfg)
    to_send: list[list[tuple[news.Article, ai.Classified]]] = []

    # Release HIGH alerts held during quiet hours.
    if not quiet and state["held"]:
        for h in state["held"]:
            art = news.Article.from_dict(h)
            to_send.append([(art, ai.Classified(id=0, relevant=True, importance=h["importance"],
                                                sentiment=h["sentiment"], event_key=h["event"],
                                                repeat_of_recent_alert=False,
                                                summary=h["summary"] + " (held during quiet hours)"))])
        state["held"] = []

    if fresh:
        print(f"Classifying {len(fresh)} new articles...")
        results, used_ai = ai.classify(fresh, state["recent_alerts"], secrets.anthropic_key,
                                       secrets.claude_model, secrets.use_fallbacks)
        recent_events = {(r["ticker"], r.get("event")) for r in state["recent_alerts"]}
        groups: dict[tuple[str, str], list[tuple[news.Article, ai.Classified]]] = {}
        for art, c in zip(fresh, results):
            state["seen"][art.key] = ts
            if not c.relevant or c.importance == "low":
                continue
            if c.importance == "medium":
                state["queue"].append(queue_record(art, c))
                continue
            if c.repeat_of_recent_alert or (art.ticker, c.event_key) in recent_events:
                state["queue"].append(queue_record(art, c))   # follow-up coverage -> briefing
                continue
            groups.setdefault((art.ticker, c.event_key), []).append((art, c))
        for grp in groups.values():
            grp.sort(key=lambda p: news.source_rank(p[0].source))   # best source leads
            art, c = grp[0]
            if quiet and c.importance != "critical":
                state["held"].append(queue_record(art, c))
            else:
                to_send.append(grp)
        if not used_ai:
            print("(keyword triage used)")

    to_send.sort(key=lambda g: ai.IMPORTANCE_ORDER[g[0][1].importance])
    for grp in to_send[:cfg.max_alerts_per_run]:
        tg.send(format_alert(grp, cfg.timezone))
        state["recent_alerts"].append(alert_record(*grp[0]))
    for grp in to_send[cfg.max_alerts_per_run:]:          # overflow is never dropped
        state["queue"].append(queue_record(*grp[0]))
    state["last_scan_ts"] = ts
    print(f"Alerts sent: {min(len(to_send), cfg.max_alerts_per_run)}; queued for briefing: {len(state['queue'])}")


# --------------------------------------------------------------------------- briefings

def _price_block(quotes: dict, symbols: list[tuple[str, str]], expected: dt.date | None) -> list[str]:
    lines = []
    for sym, label in symbols:
        q = quotes.get(sym)
        if not q:
            lines.append(f"• {label}: price unavailable")
            continue
        stale = expected is not None and q.bar_date < expected
        lines.append(q.line() + (f"  ⚠ STALE — expected {expected:%b %d} close" if stale else ""))
    return lines


def build_briefing(kind: str, cfg: Config, state: dict, articles: list[news.Article],
                   now: dt.datetime, secrets, late: bool = False) -> str:
    tz = cfg.timezone
    today = market.et_date(now)
    sess = market.session_for(today)
    stock_syms = [(s.ticker, f"{s.ticker} ({s.name})") for s in cfg.watchlist]

    if kind == "pre":
        prev = market.previous_session(today)
        title = f"\U0001F305 PRE-MARKET BRIEFING — {today:%a %d %b %Y}"
        sub = (f"US open {local(sess.open, tz)} {tz.split('/')[-1]} time"
               + (" · early close today " + local(sess.close, tz) if sess.early_close else "")
               + (" · (sent late: market already open)" if late else ""))
        expected = prev.date if prev else None
        idx_syms = prices.FUTURES + prices.INDICES
        price_note = f"Stock prices are the previous session's close ({expected:%b %d})." if expected else ""
    elif kind == "post":
        title = f"\U0001F306 AFTER-CLOSE RECAP — {today:%a %d %b %Y}"
        sub = (f"US close {local(sess.close, tz)} {tz.split('/')[-1]} time"
               + (" (early close)" if sess.early_close else ""))
        expected = today
        idx_syms = prices.INDICES
        price_note = "Prices are today's regular-session closes."
    else:
        nxt = market.next_session(today)
        title = f"\U0001F4F4 MARKET CLOSED ({market.closed_reason(today)}) — {today:%a %d %b %Y}"
        sub = f"Next US session opens {local(nxt.open, tz)} {tz.split('/')[-1]} time" if nxt else ""
        expected = None
        idx_syms = prices.INDICES
        price_note = "No trading today. Prices shown are the last session's closes."

    quotes = prices.daily_quotes(stock_syms + idx_syms)
    market_lines = _price_block(quotes, idx_syms, expected if kind == "post" else None)
    stock_lines = _price_block(quotes, stock_syms, expected)

    # Headlines: everything since the last briefing (capped), plus queued medium/overflow items.
    since = max(state.get("last_briefing_ts", 0), time.time() - BRIEFING_WINDOW_MAX_H * 3600)
    pool: dict[str, dict] = {}
    for q in state["queue"]:
        pool[news.dedupe_key(q["ticker"], q["title"])] = q
    for a in articles:
        if a.published.timestamp() >= since and a.key not in pool:
            pool[a.key] = a.to_dict()
    for r in state["recent_alerts"]:
        if r["ts"] >= since:
            k = news.dedupe_key(r["ticker"], r["title"])
            if k in pool:
                pool[k]["importance"] = pool[k].get("importance", "high")
    items = sorted(pool.values(), key=lambda d: (ai.IMPORTANCE_ORDER.get(d.get("importance", "medium"), 2),
                                                 -dt.datetime.fromisoformat(d["published"]).timestamp()))[:25]

    sources = [f"[{i + 1}] {d['source']} — {d['url']}" for i, d in enumerate(items)]
    headline_lines = [
        f"[{i + 1}] {d['ticker']} | {local(dt.datetime.fromisoformat(d['published']), tz)} | "
        f"{d.get('importance', 'unrated')} | {d['title']}" + (f" — note: {d['summary']}" if d.get("summary") else "")
        for i, d in enumerate(items)]

    label = {"pre": "pre-market briefing (prepare for today's US session: what changed overnight, "
                    "what to watch today, upcoming catalysts mentioned in the headlines)",
             "post": "after-close recap (how the market and each watchlist stock did today, what may explain "
                     "notable moves, key company news, what to watch tomorrow)",
             "closed": "market-closed digest (US market is closed today; summarize relevant news and what to "
                       "watch at the next session; do not describe a trading session that did not happen)"}[kind]
    context = "\n".join([
        f"Briefing type: {kind}. Current time: {local(now, tz)} ({tz}). Market status: {market.market_status(now)}.",
        price_note,
        "", "MARKET:", *market_lines,
        "", "WATCHLIST PRICES:", *stock_lines,
        "", "HEADLINES (cite as [n]):", *(headline_lines or ["(no new headlines for the watchlist)"]),
    ])
    body = ai.write_briefing(label, context, secrets.anthropic_key, secrets.claude_model, secrets.use_fallbacks)
    if body is None:   # plain digest fallback
        body = "\n".join(["\U0001F4CA Market", *market_lines, "", "\U0001F4BC Your stocks", *stock_lines, "",
                          "\U0001F4F0 Headlines", *([f"[{i + 1}] {d['ticker']}: {d['title']}"
                                                     for i, d in enumerate(items)] or ["No new headlines."])])
    parts = [title, sub, "", body]
    if sources:
        parts += ["", "\U0001F517 Sources", *sources]
    return "\n".join(p for p in parts if p is not None)


def maybe_brief(cfg: Config, state: dict, tg: Telegram, secrets, articles, now: dt.datetime) -> None:
    due = market.due_briefing(now, state["briefings"], cfg.pre_market_lead_minutes,
                              cfg.post_market_delay_minutes)
    if not due:
        return
    print(f"Briefing due: {due.key}")
    text = build_briefing(due.kind, cfg, state, articles, now, secrets, late=due.late)
    if tg.send(text) or tg.dry_run:
        state["briefings"][due.key] = time.time()
        state["last_briefing_ts"] = time.time()
        state["queue"] = []


# --------------------------------------------------------------------------- commands

HELP = """\U0001F916 I send you news about your stocks \u2014 alerts during the day and a briefing before and after the US market.

Just write to me normally, for example:
\u2022 "add Nvidia and Apple"
\u2022 "remove Shopify"
\u2022 "delete my whole watchlist"
\u2022 "show my list" / "news on TSM"

Or use commands:
/list \u2014 your watchlist
/add TICKER [Company name] \u2014 watch a stock (e.g. /add NVDA Nvidia)
/remove TICKER \u2014 stop watching
/clear \u2014 remove all stocks
/news TICKER \u2014 latest headlines for a stock
/brief \u2014 a news briefing right now
/status \u2014 market status & schedule"""


class Collector:
    """Stands in for Telegram to gather several replies into one message."""

    def __init__(self):
        self.parts: list[str] = []
        self.dry_run = True

    def send(self, text: str) -> bool:
        self.parts.append(text)
        return True


def lookup_name(ticker: str) -> str | None:
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
        if not (info.get("regularMarketPrice") or info.get("previousClose") or info.get("currentPrice")):
            return None
        return info.get("shortName") or info.get("longName") or ticker
    except Exception:
        return None


def handle_command(text: str, cfg: Config, state: dict, tg: Telegram, secrets,
                   now: dt.datetime) -> bool:
    """Returns True if the watchlist changed."""
    parts = text.split()
    cmd = parts[0].split("@")[0].lower() if parts else ""
    arg = parts[1].upper() if len(parts) > 1 else ""
    if cmd in ("/start", "/help"):
        tg.send(HELP)
    elif cmd == "/list":
        tg.send("\U0001F4CB Watchlist\n" + "\n".join(f"• {s.ticker} — {s.name}" for s in cfg.watchlist)
                if cfg.watchlist else "Your watchlist is empty. /add TICKER")
    elif cmd == "/add":
        if not TICKER_RE.match(arg):
            tg.send("Usage: /add TICKER [Company name]")
        elif cfg.find(arg):
            tg.send(f"{arg} is already on your watchlist.")
        else:
            name = " ".join(parts[2:]) or lookup_name(arg)
            if not name:
                tg.send(f"Couldn't find a listed stock with ticker {arg}.")
                return False
            cfg.watchlist.append(Stock(arg, name))
            tg.send(f"✅ Added {arg} ({name}). News alerts start from now.")
            return True
    elif cmd == "/remove":
        s = cfg.find(arg)
        if not s:
            tg.send(f"{arg or '?'} is not on your watchlist.")
        else:
            cfg.watchlist.remove(s)
            tg.send(f"\U0001F5D1 Removed {arg}.")
            return True
    elif cmd == "/clear":
        if not cfg.watchlist:
            tg.send("Your watchlist is already empty.")
            return False
        removed = ", ".join(cfg.tickers())
        cfg.watchlist.clear()
        tg.send(f"\U0001F5D1 Cleared your watchlist ({removed}).")
        return True
    elif cmd == "/news":
        s = cfg.find(arg) or (Stock(arg, lookup_name(arg) or arg) if TICKER_RE.match(arg) else None)
        if not s:
            tg.send("Usage: /news TICKER")
        else:
            arts = news.fetch_stock_news(s, 72)[:8]
            tg.send(f"\U0001F4F0 {s.ticker} — latest headlines\n\n" + "\n\n".join(
                f"{a.title}\n{a.source} · {local(a.published, cfg.timezone)}\n{a.url}" for a in arts)
                if arts else f"No recent headlines found for {s.ticker}.")
    elif cmd == "/brief":
        sess = market.session_for(market.et_date(now))
        kind = "closed" if sess is None else ("post" if now >= sess.close else "pre")
        arts = news.fetch_all(cfg.watchlist, cfg.max_article_age_hours)
        tg.send(build_briefing(kind, cfg, state, arts, now, secrets))
    elif cmd == "/status":
        today = market.et_date(now)
        sess = market.session_for(today)
        if sess:
            sched = (f"Today's session: {local(sess.open, cfg.timezone)} → {local(sess.close, cfg.timezone)}"
                     + (" (early close)" if sess.early_close else ""))
        else:
            nxt = market.next_session(today)
            sched = f"Closed today ({market.closed_reason(today)}). Next open: {local(nxt.open, cfg.timezone)}"
        last = (local(dt.datetime.fromtimestamp(state["last_scan_ts"], dt.timezone.utc), cfg.timezone)
                if state.get("last_scan_ts") else "never")
        tg.send(f"ℹ️ Market: {market.market_status(now)}\n{sched}\n"
                f"Last news scan: {last}\nQueued for next briefing: {len(state['queue'])}\n"
                f"Quiet hours: {cfg.quiet_start}–{cfg.quiet_end}" + ("" if cfg.quiet_enabled else " (off)"))
    elif cmd.startswith("/"):
        tg.send("Unknown command. /help")
    elif text.strip():
        return handle_plain_text(text, cfg, state, tg, secrets, now)
    return False


def handle_plain_text(text: str, cfg: Config, state: dict, tg: Telegram, secrets,
                      now: dt.datetime) -> bool:
    """Understand a normal sentence ("remove Shopify and add Nvidia") via Claude."""
    intent = ai.parse_request(text, cfg.tickers(), secrets.anthropic_key, secrets.claude_model,
                              secrets.use_fallbacks)
    if intent is None:
        tg.send("Sorry, I didn't understand that. Try /add NVDA, /remove SHOP, /clear or /list. /help")
        return False
    out = Collector()
    changed = False
    for a in intent.actions:
        t = a.ticker.upper().strip()
        if a.type == "add" and TICKER_RE.match(t):
            changed |= handle_command(f"/add {t} {a.name}".strip(), cfg, state, out, secrets, now)
        elif a.type == "remove" and t:
            changed |= handle_command(f"/remove {t}", cfg, state, out, secrets, now)
        elif a.type == "news" and t:
            handle_command(f"/news {t}", cfg, state, out, secrets, now)
        elif a.type in ("clear", "list", "brief", "status", "help"):
            changed |= handle_command(f"/{a.type}", cfg, state, out, secrets, now)
    if changed and not any(a.type == "list" for a in intent.actions):
        out.send("\U0001F4CB Now watching: " + (", ".join(cfg.tickers()) or "nothing"))
    if intent.reply:
        out.send(intent.reply)
    tg.send("\n\n".join(out.parts) if out.parts else "OK \U0001F44D")
    return changed


# --------------------------------------------------------------------------- main

def process_messages(cfg: Config, state: dict, tg: Telegram, secrets, wait: int = 0) -> None:
    texts, state["telegram_offset"] = tg.get_commands(state.get("telegram_offset", 0), wait=wait)
    changed = False
    for t in texts:
        print(f"message: {t[:80]!r}")
        try:
            changed |= handle_command(t, cfg, state, tg, secrets, dt.datetime.now(dt.timezone.utc))
        except Exception as e:
            print(f"command {t!r} failed: {e}")
            tg.send(f"\u26A0 Sorry, that failed: {t}")
    if changed:
        save_watchlist(cfg, CONFIG_PATH)


def run_cycle(cfg: Config, state: dict, tg: Telegram, secrets) -> bool:
    """News scan + briefing check. Returns True if a stage failed."""
    now = dt.datetime.now(dt.timezone.utc)
    print(f"Cycle at {now.isoformat()} \u2014 market {market.market_status(now)}, {len(cfg.watchlist)} stocks")
    articles = news.fetch_all(cfg.watchlist, cfg.max_article_age_hours)
    failed = False
    # Each stage is isolated: a failed news scan never blocks a briefing, and vice versa.
    for stage in (scan, maybe_brief):
        try:
            stage(cfg, state, tg, secrets, articles, now)
        except Exception:
            failed = True
            traceback.print_exc()
    return failed


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="newsbot")
    p.add_argument("--dry-run", action="store_true", help="print messages instead of sending")
    p.add_argument("--brief", choices=["pre", "post", "closed"], help="force a briefing now (not recorded)")
    p.add_argument("--loop", type=int, default=0, metavar="SECONDS",
                   help="stay running this long: answer messages instantly, scan news every --interval")
    p.add_argument("--interval", type=int, default=900, help="seconds between news scans in --loop mode")
    args = p.parse_args(argv)

    cfg = load_config()
    secrets = load_secrets()
    state = load_state(STATE_PATH)
    tg = Telegram(secrets.telegram_token, secrets.telegram_chat_id, dry_run=args.dry_run)
    print(f"Start \u2014 AI {'on (' + secrets.claude_model + ')' if secrets.anthropic_key else 'off'}")

    try:
        if args.brief:
            now = dt.datetime.now(dt.timezone.utc)
            articles = news.fetch_all(cfg.watchlist, cfg.max_article_age_hours)
            tg.send(build_briefing(args.brief, cfg, state, articles, now, secrets))
            return 0
        if not args.loop:
            process_messages(cfg, state, tg, secrets)
            return 1 if run_cycle(cfg, state, tg, secrets) else 0

        end = time.time() + args.loop
        next_scan = 0.0
        while time.time() < end:
            if time.time() >= next_scan:
                run_cycle(cfg, state, tg, secrets)
                next_scan = time.time() + args.interval
                save_state(state, STATE_PATH)
            wait = int(max(1, min(50, next_scan - time.time(), end - time.time())))
            try:
                process_messages(cfg, state, tg, secrets, wait=wait)
            except Exception:
                traceback.print_exc()
                time.sleep(5)
            save_state(state, STATE_PATH)
        return 0
    finally:
        save_state(state, STATE_PATH)   # always persist dedupe state, even after an error
