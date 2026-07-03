"""Builds the data file for the web dashboard (docs/data/dashboard.enc).

Reads trades.json, computes P&L over time + per-period totals, prices the open positions,
scores holdings/watchlist with the X-ray, gathers + AI-summarizes news, then ENCRYPTS the
whole thing with your DASHBOARD_PASSWORD (AES-256-GCM) so it's safe to publish on a public
GitHub Pages site. The static page decrypts it in the browser with the same password.

Env: DASHBOARD_PASSWORD (required), ANTHROPIC_API_KEY + CHAT_MODEL (optional, for the news
summary), TELEGRAM_TOKEN/TELEGRAM_CHAT_ID (only because signal_bot imports them).
"""

import os
import json
import base64
import datetime

import yfinance as yf

import xray
import signal_bot as sb           # fetch_news_items, evaluate, get_ohlcv

TRADES_FILE = os.environ.get("TRADES_FILE", "trades.json")
OUT_PATH = os.environ.get("DASH_OUT", "docs/data/dashboard.enc")
MAX_SYMBOLS = 40                  # cap network work per build


def _load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _last_price(sym):
    try:
        data = yf.download(sym, period="5d", interval="1d", auto_adjust=True,
                           progress=False, threads=False)
        return round(float(data["Close"].dropna().iloc[-1]), 2)
    except Exception:
        return None


def _shares_of(p):
    if p.get("shares"):
        return p["shares"]
    if p.get("amount") and p.get("entry"):
        return p["amount"] / p["entry"]
    return None


def _performance(closed, unrealized, starting_capital):
    today = datetime.date.today()
    spans = {"week": 7, "month": 30, "year": 365, "all": 10 ** 6}
    realized = {k: 0.0 for k in spans}
    have_usd = 0
    for t in closed:
        usd = t.get("pnl_usd")
        if usd is None:
            continue
        have_usd += 1
        try:
            cd = datetime.date.fromisoformat((t.get("close_date") or t.get("date"))[:10])
        except Exception:
            cd = today
        age = (today - cd).days
        for k, days in spans.items():
            if age <= days:
                realized[k] += usd
    # equity curve = cumulative realized, with a final "today" point that adds open P&L
    curve = []
    run = 0.0
    for t in sorted([t for t in closed if t.get("pnl_usd") is not None],
                    key=lambda x: x.get("close_date") or x.get("date") or ""):
        run += t["pnl_usd"]
        curve.append({"date": (t.get("close_date") or t.get("date"))[:10], "cum": round(run, 2)})
    curve.append({"date": today.isoformat(), "cum": round(run + (unrealized or 0), 2)})

    wins = [t for t in closed if t.get("outcome") == "win"]
    losses = [t for t in closed if t.get("outcome") == "loss"]
    pct = [t.get("pnl_pct") for t in closed if t.get("pnl_pct") is not None]
    # key must coerce a present-but-None pnl_pct (not just a missing key) or max/min raises TypeError
    rated = [t for t in closed if t.get("pnl_pct") is not None]
    best = max(rated, key=lambda t: t["pnl_pct"], default=None)
    worst = min(rated, key=lambda t: t["pnl_pct"], default=None)
    realized_all = realized["all"]
    balance = round(starting_capital + realized_all, 2)              # cash + closed P&L
    equity = round(starting_capital + realized_all + (unrealized or 0), 2)  # like TradingView equity
    return {
        "starting_capital": round(starting_capital, 2),
        "balance": balance,
        "equity": equity,
        "total_return_pct": round((equity / starting_capital - 1) * 100, 2) if starting_capital else None,
        "realized": {k: round(v, 2) for k, v in realized.items()},
        "unrealized": round(unrealized or 0, 2),
        "total": round(realized["all"] + (unrealized or 0), 2),
        "closed": len(closed), "wins": len(wins), "losses": len(losses),
        "win_rate": round(len(wins) / len(closed) * 100) if closed else None,
        "avg_pct": round(sum(pct) / len(pct), 1) if pct else None,
        "best": {"sym": best["sym"], "pct": round(best.get("pnl_pct", 0), 1)} if best else None,
        "worst": {"sym": worst["sym"], "pct": round(worst.get("pnl_pct", 0), 1)} if worst else None,
        "usd_coverage": f"{have_usd}/{len(closed)}",
        "curve": curve,
    }


def _holdings(open_positions):
    out, unreal = [], 0.0
    for p in open_positions[:MAX_SYMBOLS]:
        sym = p["sym"]
        price = _last_price(sym)
        sh = _shares_of(p)
        pnl_usd = round((price - p["entry"]) * sh, 2) if (price and sh) else None
        pnl_pct = round((price / p["entry"] - 1) * 100, 1) if price else None
        if pnl_usd:
            unreal += pnl_usd
        res = xray.xray(sym, ai=False)
        out.append({"sym": sym, "entry": p["entry"], "price": price,
                    "pnl_usd": pnl_usd, "pnl_pct": pnl_pct,
                    "score": res.get("score") if res.get("ok") else None,
                    "verdict": res.get("verdict") if res.get("ok") else None})
    out.sort(key=lambda h: h.get("pnl_pct") if h.get("pnl_pct") is not None else -999, reverse=True)
    return out, unreal


def _watchlist(watch):
    out = []
    for sym in watch[:MAX_SYMBOLS]:
        price = _last_price(sym)
        res = xray.xray(sym, ai=False)
        setup = "—"
        try:
            data = yf.download(sym, period="2y", interval="1d", auto_adjust=True,
                               progress=False, threads=False)
            ohlcv = sb.get_ohlcv(data, sym)
            r = sb.evaluate(*ohlcv) if ohlcv else None
            if r:
                setup = ("🟢 buy setup" if (r["fires"] or r.get("cup_fires") or r.get("flat_fires"))
                         else "🟡 pulled back" if r["pulled_back"]
                         else "⚪ uptrend" if r["is_uptrend"] else "🔴 no setup")
        except Exception:
            pass
        out.append({"sym": sym, "price": price, "setup": setup,
                    "score": res.get("score") if res.get("ok") else None})
    return out


def _news(symbols):
    items = []
    for sym in symbols[:25]:
        try:
            for it in sb.fetch_news_items(sym, limit=3):
                items.append({"sym": sym, "title": it["title"],
                              "source": it.get("source", ""), "link": it.get("link", "")})
        except Exception:
            pass
    summary = _ai_news_summary(items)
    return {"summary": summary, "items": items[:60]}


def _ai_news_summary(items):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or not items:
        return None
    try:
        import anthropic
        headlines = "\n".join(f"- [{it['sym']}] {it['title']}" for it in items[:50])
        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model=os.environ.get("CHAT_MODEL", "claude-sonnet-4-6"),
            max_tokens=700,
            system="You summarize stock-market news briefly and plainly. Honest and concrete. Not financial advice.",
            messages=[{"role": "user", "content":
                       "These are the latest headlines on my holdings and watchlist. In 4-6 bullet points, "
                       "summarize what's most important and relevant for me to know this week (what's moving, "
                       "why, and what to watch):\n\n" + headlines}],
        )
        return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    except Exception as e:
        print(f"news summary failed: {e}")
        return None


def _encrypt(text, password):
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives.hashes import SHA256
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt = os.urandom(16)
    key = PBKDF2HMAC(algorithm=SHA256(), length=32, salt=salt, iterations=200000).derive(password.encode())
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, text.encode(), None)     # ct includes the GCM tag at the end
    return base64.b64encode(salt + nonce + ct).decode()


def main():
    password = os.environ.get("DASHBOARD_PASSWORD")
    if not password:
        raise SystemExit("DASHBOARD_PASSWORD is not set — add it as a GitHub secret.")
    trades = _load(TRADES_FILE, {"open": [], "closed": [], "watch": []})
    opens = trades.get("open", [])
    watch = trades.get("watch", [])
    closed = trades.get("closed", [])

    holdings, unrealized = _holdings(opens)
    symbols = list(dict.fromkeys([p["sym"] for p in opens] + watch))
    starting_capital = float(trades.get("account", {}).get("starting_capital")
                             or os.environ.get("START_CAPITAL") or 100000)
    data = {
        "generated": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "performance": _performance(closed, unrealized, starting_capital),
        "holdings": holdings,
        "watchlist": _watchlist(watch),
        "news": _news(symbols),
    }
    blob = _encrypt(json.dumps(data, ensure_ascii=False), password)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        f.write(blob)
    print(f"Wrote {OUT_PATH} ({len(blob)} bytes, encrypted). "
          f"{len(holdings)} holdings, {len(watch)} watch, {len(closed)} closed.")


if __name__ == "__main__":
    main()
