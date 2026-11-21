"""Claude analysis: classify new headlines (importance, sentiment, event grouping) and
write the pre-market / after-close briefings. Falls back to keyword rules and a plain
headline digest when no API key is set or the API is unavailable."""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel

from .news import Article

Importance = Literal["critical", "high", "medium", "low"]
Sentiment = Literal["positive", "negative", "neutral", "mixed"]
IMPORTANCE_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


class Classified(BaseModel):
    id: int
    relevant: bool
    importance: Importance
    sentiment: Sentiment
    event_key: str
    repeat_of_recent_alert: bool
    summary: str


class Classification(BaseModel):
    items: list[Classified]


CLASSIFY_SYSTEM = """You triage financial news headlines for one private investor's stock watchlist.
For each headline decide:
- relevant: is it materially about the listed company (not a passing mention, listicle, or generic market piece)?
- importance:
  critical = could move the stock sharply now: M&A/takeover, bankruptcy, trading halt, fraud/SEC enforcement, \
CEO sudden exit, guidance cut/raise, major earnings surprise, FDA decision, huge contract loss/win.
  high = scheduled earnings results, analyst up/downgrade from a major firm, large offering/buyback, \
significant legal/regulatory step, major product or partnership news, unusual >7% move with a stated reason.
  medium = useful context: previews, price-target tweaks, sector news naming the company, insider filings.
  low = recycled commentary, opinion, minor mentions.
- sentiment for the company's shareholders: positive, negative, neutral, mixed.
- event_key: short lowercase slug naming the underlying event, IDENTICAL for headlines covering the same event \
(e.g. "shop-q3-earnings-beat").
- repeat_of_recent_alert: true if the event is the same as one in RECENTLY ALERTED.
- summary: one factual sentence (max 30 words) on what happened and why it matters. Use only what the headline \
states; do not invent numbers, quotes or reasons. If the headline is ambiguous, say so.
Return one entry per headline id."""


BRIEFING_SYSTEM = """You write a concise, factual stock briefing delivered as a Telegram message (plain text, \
no markdown, no tables). Audience: one private investor who owns/watches the listed stocks.

Hard rules:
- Use ONLY the price data and headlines provided. Never invent news, numbers, analyst opinions, quotes or sources.
- Cite headlines by their [n] number right after the claim they support. Do not write URLs; the sources list is appended.
- Separate fact from interpretation: label interpretation with words like "may", "could", "suggests".
- Correlation is not causation: do not say a headline caused a price move unless the headline itself reports it \
explains the move; otherwise say the move "coincided with" the news or that no clear catalyst was found.
- If a price is marked stale or missing, say so plainly — never present it as current.
- If there is little news, keep it short. Do not pad.
- Use short sections with simple emoji headers, and keep the whole briefing under ~550 words."""


def _client(api_key: str):
    import anthropic
    return anthropic.Anthropic(api_key=api_key, max_retries=3, timeout=120)


def _request_extras(use_fallbacks: bool) -> dict:
    # Server-side refusal fallback: if the model declines, the API re-runs on a fallback model.
    return {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"} if use_fallbacks else {}


# --------------------------------------------------------------------------- classify

KEYWORDS_CRITICAL = re.compile(
    r"\b(bankrupt\w*|chapter 11|halted|halts trading|fraud|delist\w*|to be acquired|agrees to (buy|acquire)|"
    r"takeover|buyout|merger agreement|ceo (resigns|steps down|ousted|fired)|cuts? (guidance|outlook)|"
    r"raises? (guidance|outlook)|sec charges|recall)\b", re.I)
KEYWORDS_HIGH = re.compile(
    r"\b(earnings|quarterly results|q[1-4] results|revenue|guidance|downgrade\w*|upgrade\w*|"
    r"offering|buyback|repurchase|lawsuit|investigation|acquire\w*|acquisition|partnership|contract|"
    r"plunge\w*|soar\w*|surge\w*|tumble\w*|sinks?|jumps?|layoffs?|dividend)\b", re.I)
KEYWORDS_POS = re.compile(r"\b(beat\w*|raise\w*|upgrade\w*|soar\w*|surge\w*|jumps?|record|wins?|rall\w+)\b", re.I)
KEYWORDS_NEG = re.compile(r"\b(miss\w*|cuts?|downgrade\w*|plunge\w*|tumble\w*|sinks?|falls?|lawsuit|probe|"
                          r"investigation|layoffs?|recall|fraud)\b", re.I)


def heuristic_classify(articles: list[Article]) -> list[Classified]:
    out = []
    for i, a in enumerate(articles):
        t = a.title
        imp = "critical" if KEYWORDS_CRITICAL.search(t) else ("high" if KEYWORDS_HIGH.search(t) else "medium")
        pos, neg = bool(KEYWORDS_POS.search(t)), bool(KEYWORDS_NEG.search(t))
        sent = "mixed" if pos and neg else "positive" if pos else "negative" if neg else "neutral"
        out.append(Classified(id=i, relevant=True, importance=imp, sentiment=sent,
                              event_key=f"{a.ticker.lower()}-{a.key[:8]}", repeat_of_recent_alert=False,
                              summary="(Keyword triage — AI analysis unavailable.)"))
    return out


def classify(articles: list[Article], recent_alerts: list[dict], api_key: str, model: str,
             use_fallbacks: bool = True) -> tuple[list[Classified], bool]:
    """Returns (classifications aligned by id, used_ai)."""
    if not articles:
        return [], False
    if not api_key:
        return heuristic_classify(articles), False
    lines = [f"[{i}] {a.ticker} | {a.published:%Y-%m-%d %H:%M}Z | {a.source} | {a.title}"
             for i, a in enumerate(articles)]
    recent = "\n".join(f"- {r['ticker']}: {r['title']} (event: {r.get('event','')})" for r in recent_alerts[-40:])
    prompt = (f"RECENTLY ALERTED (last 72h):\n{recent or '(none)'}\n\nNEW HEADLINES:\n" + "\n".join(lines))
    try:
        resp = _client(api_key).beta.messages.parse(
            model=model,
            max_tokens=16000,
            system=CLASSIFY_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_format=Classification,
            output_config={"effort": "low"},
            **_request_extras(use_fallbacks),
        )
        if resp.stop_reason == "refusal" or resp.parsed_output is None:
            raise RuntimeError(f"no usable classification (stop_reason={resp.stop_reason})")
        by_id = {c.id: c for c in resp.parsed_output.items}
        fallback = heuristic_classify(articles)
        return [by_id.get(i, fallback[i]) for i in range(len(articles))], True
    except Exception as e:
        print(f"AI classification failed, using keyword triage: {e}")
        return heuristic_classify(articles), False


# --------------------------------------------------------------------------- briefing

def write_briefing(kind_label: str, context: str, api_key: str, model: str,
                   use_fallbacks: bool = True) -> str | None:
    """Claude-written briefing body, or None (caller then sends the plain digest)."""
    if not api_key:
        return None
    try:
        resp = _client(api_key).beta.messages.create(
            model=model,
            max_tokens=16000,
            system=BRIEFING_SYSTEM,
            messages=[{"role": "user", "content": f"Write the {kind_label}.\n\n{context}"}],
            output_config={"effort": "medium"},
            **_request_extras(use_fallbacks),
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError("model declined")
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        return text or None
    except Exception as e:
        print(f"AI briefing failed, sending plain digest: {e}")
        return None


def debug_dump(items: list[Classified]) -> str:
    return json.dumps([i.model_dump() for i in items], indent=1)


# --------------------------------------------------------------------------- plain-English requests

class Action(BaseModel):
    type: Literal["add", "remove", "clear", "list", "news", "brief", "status", "help", "none"]
    ticker: str
    name: str


class Intent(BaseModel):
    actions: list[Action]
    reply: str


INTENT_SYSTEM = """You turn a Telegram message into actions for a stock-news bot. The bot ONLY manages a watchlist \
and sends news; it never gives buy/sell advice or technical analysis.
Action types:
- add: watch a stock. ticker = its primary US-listed ticker (e.g. Nvidia -> NVDA, Google/Alphabet -> GOOGL, \
TSMC/Taiwan Semiconductor -> TSM), name = short company name; if it's widely known by another name, add it in \
parentheses, e.g. "Alphabet (Google)", "Taiwan Semiconductor (TSMC)".
- remove: stop watching a stock (use the ticker as it appears in the CURRENT WATCHLIST).
- clear: remove every stock (e.g. "delete my old watchlist", "start fresh"). Put clear BEFORE any adds.
- list: show the watchlist. news: latest headlines for one ticker. brief: a news briefing now.
- status: market hours/schedule. help: what the bot can do.
- none: nothing to do (greeting, thanks, question outside the bot's scope).
For list/brief/status/help/clear/none use ticker "" and name "".
reply: one short, friendly sentence only if the message needs an answer the actions don't give \
(e.g. it asks for analysis: explain the bot only sends news). Otherwise "".
Never invent tickers: if unsure which company is meant, use none and ask in reply."""


def parse_request(text: str, watchlist: list[str], api_key: str, model: str,
                  use_fallbacks: bool = True) -> Intent | None:
    """Understand a free-text message. None if AI is unavailable."""
    if not api_key:
        return None
    try:
        resp = _client(api_key).beta.messages.parse(
            model=model,
            max_tokens=4000,
            system=INTENT_SYSTEM,
            messages=[{"role": "user", "content":
                       f"CURRENT WATCHLIST: {', '.join(watchlist) or '(empty)'}\n\nMESSAGE: {text}"}],
            output_format=Intent,
            output_config={"effort": "low"},
            **_request_extras(use_fallbacks),
        )
        if resp.stop_reason == "refusal":
            return None
        return resp.parsed_output
    except Exception as e:
        print(f"AI request parsing failed: {e}")
        return None
