"""Morning news scan — runs ~30 min before the US open and ~30 min after.

Reads the day's market headlines, asks Claude to pick stocks with genuinely positive
catalysts, then puts every candidate through the SAME discipline as the daily scan:
fundamental health score >= MIN_SCORE, confirmed YoY revenue growth, and an honest
chart verdict (news alone is never a buy signal). Sends a ranked Telegram brief.

Env: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID (required); ANTHROPIC_API_KEY + CHAT_MODEL
(recommended — without them the scan falls back to sending raw headlines).
"""

import os
import re
import json
import time
import datetime
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

import requests

import signal_bot as sb   # reuse feeds idiom, evaluate, download_chunk, send_long, MIN_SCORE
import xray

# Broad market queries — Google News aggregates Reuters/Bloomberg/CNBC/WSJ/etc.
MARKET_QUERIES = [
    "stock market today",
    "premarket movers",
    "stocks to watch today",
    "earnings report beat today",
    "analyst upgrade stock price target",
]
MAX_HEADLINES = 40
MAX_CANDIDATES = 10


def fetch_market_headlines(per_query=8):
    """Top deduped headlines across the market queries. Best-effort per feed."""
    items, seen = [], set()
    for q in MARKET_QUERIES:
        url = f"https://news.google.com/rss/search?q={quote_plus(q)}&hl=en-US&gl=US&ceid=US:en"
        try:
            resp = requests.get(url, headers={"User-Agent": sb.BROWSER_UA}, timeout=8)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            for item in root.findall(".//item")[:per_query]:
                title = (item.findtext("title") or "").strip()
                key = sb._norm_title(title)
                if title and key and key not in seen:
                    seen.add(key)
                    items.append(title)
        except Exception:
            pass
    return items[:MAX_HEADLINES]


def extract_json_array(text):
    """Pull the first JSON array out of a model reply (tolerates prose around it)."""
    m = re.search(r"\[.*\]", text or "", re.S)
    if not m:
        return []
    try:
        out = json.loads(m.group(0))
        return out if isinstance(out, list) else []
    except Exception:
        return []


def validate_picks(picks):
    """Keep only well-formed {ticker, catalyst} entries with plausible US tickers."""
    clean, seen = [], set()
    for p in picks:
        if not isinstance(p, dict):
            continue
        sym = str(p.get("ticker", "")).upper().strip()
        catalyst = str(p.get("catalyst", "")).strip()
        if not catalyst or sym in seen or not re.fullmatch(r"[A-Z]{1,5}(-[A-Z])?", sym):
            continue
        seen.add(sym)
        clean.append({"ticker": sym, "catalyst": catalyst[:200]})
    return clean[:MAX_CANDIDATES]


def pick_candidates(headlines):
    """Ask Claude which US-listed stocks the headlines suggest could move UP today, and why."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or not headlines:
        return []
    try:
        import anthropic
    except ImportError:
        return []
    text = "\n".join(f"- {h}" for h in headlines)
    user = (
        "Here are this morning's market headlines:\n\n" + text + "\n\n"
        "List the US-listed stocks these headlines suggest could rise TODAY on a genuine "
        "positive catalyst (earnings beat, guidance raise, analyst upgrade, product/regulatory "
        "win, big partnership). Skip rumors, meme pumps, penny stocks, and anything negative "
        "or ambiguous. Answer with ONLY a JSON array, no other text, max 12 entries:\n"
        '[{"ticker": "XYZ", "catalyst": "<one concrete sentence naming the news>"}]'
    )
    try:
        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model=os.environ.get("CHAT_MODEL", "claude-sonnet-4-6"),
            max_tokens=900,
            system="You are a careful markets analyst. Only cite catalysts actually present in the headlines. Not financial advice.",
            messages=[{"role": "user", "content": user}],
        )
        txt = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    except Exception as e:
        print(f"news-scan AI failed: {e}")
        return []
    return validate_picks(extract_json_array(txt))


def chart_verdict(r):
    """(one-line chart verdict, rank) — rank orders candidates: real setups first."""
    if r is None:
        return "no price data", 0
    if r.get("erratic"):
        return "🔴 erratic swings — avoid", 0
    if r.get("cup_fires"):
        entry = "breakout" if r.get("cup_kind") != "retest" else "retest entry"
        return f"☕ cup & handle {entry} — ENTRY signal", 4
    if r.get("flat_fires"):
        entry = "breakout" if r.get("flat_kind") != "retest" else "retest entry"
        return f"📏 flat-top {entry} — ENTRY signal", 4
    if r["fires"]:
        return "🟢 full buy setup — ENTRY signal", 4
    if r["pulled_back"]:
        return "🟡 pulled back — wait for the bounce", 3
    if r["is_uptrend"]:
        return "⚪ uptrend, no entry signal yet", 2
    return "🔴 no chart setup — news only", 1


def evaluate_candidates(picks):
    """Score each news pick with the strategy's quality gates. Returns (kept, dropped)."""
    kept, dropped = [], []
    for p in picks:
        sym = p["ticker"]
        r = None
        try:
            data = sb.download_chunk([sym], retries=2)
            ohlcv = sb.get_ohlcv(data, sym) if data is not None else None
            if ohlcv:
                r = sb.evaluate(*ohlcv)
        except Exception:
            pass
        xr = xray.xray(sym)
        score = xr.get("score") if xr.get("ok") else None
        if score is None or score < sb.MIN_SCORE:
            dropped.append(f"{sym} (health {score if score is not None else 'n/a'}/10)")
            continue
        rev_status, rev_label = sb.revenue_growth(sym)
        if rev_status != "yes":
            dropped.append(f"{sym} ({rev_label})")
            continue
        verdict, rank = chart_verdict(r)
        kept.append(dict(sym=sym, catalyst=p["catalyst"], score=score, verdict=verdict,
                         rank=rank, rev_label=rev_label,
                         price=r.get("price") if r else None,
                         golden=r.get("golden_cross") if r else None))
        time.sleep(0.3)
    kept.sort(key=lambda c: (c["rank"], c["score"]), reverse=True)
    return kept, dropped


def build_message(results, dropped, headlines, session_label):
    if not results and not dropped and not headlines:
        return "🌅 Morning news scan: couldn't fetch any news right now — feeds unreachable."
    lines = [f"🌅 Morning news scan ({session_label}):"]
    if not results:
        lines.append("No news candidate cleared the quality bar "
                     f"(health ≥ {sb.MIN_SCORE}/10 + growing revenue).")
    for i, c in enumerate(results, 1):
        price = f" ${c['price']:.2f}" if c.get("price") else ""
        star = " | ⭐ golden cross" if c.get("golden") else ""
        lines.append("")
        lines.append(f"{i}. {c['sym']}{price} — 🩻 {c['score']}/10 | {c['verdict']}{star}")
        lines.append(f"   📰 {c['catalyst']}")
        lines.append(f"   ✅ {c['rev_label']}")
    if dropped:
        lines.append("")
        lines.append("Dropped by the quality bar: " + ", ".join(dropped))
    if not results and headlines:
        lines.append("")
        lines.append("Top headlines:")
        lines += [f"• {h}" for h in headlines[:8]]
    lines.append("")
    lines.append("News ≠ buy signal — only act when the chart shows an ENTRY. Not financial advice.")
    return "\n".join(lines)


def main():
    now = datetime.datetime.utcnow()
    session_label = "pre-open" if now.hour <= 13 else "post-open"   # 13:00/14:00 UTC runs (EDT)
    headlines = fetch_market_headlines()
    print(f"Fetched {len(headlines)} headlines.")
    picks = pick_candidates(headlines)
    print(f"Claude proposed {len(picks)} candidates: {[p['ticker'] for p in picks]}")
    results, dropped = evaluate_candidates(picks)
    msg = build_message(results, dropped, headlines, session_label)
    print("\n" + msg)
    sent = sb.send_long(msg)
    print(f"\nSent in {sent} message(s)." if sent else "\nSend FAILED.")


if __name__ == "__main__":
    main()
