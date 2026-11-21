"""News collection: per-ticker RSS feeds, normalization, relevance filter, de-duplication.

Sources (free, no API key):
  * Yahoo Finance per-ticker headline feed (company press releases, wires, publishers)
  * Google News search (aggregates Reuters, Bloomberg, CNBC, WSJ, Business Wire, SEC news...)
Each source fails independently; a broken feed never stops the run.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import requests

from .config import Stock

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# Publishers ranked higher when several outlets cover the same event.
PREFERRED_SOURCES = (
    "sec.gov", "business wire", "businesswire", "pr newswire", "prnewswire", "globenewswire",
    "reuters", "bloomberg", "wall street journal", "wsj", "financial times", "cnbc",
    "barron", "marketwatch", "associated press", "ap news", "yahoo finance", "investor's business daily",
)
# Low-value content farms / clickbait patterns.
NOISE_PATTERNS = re.compile(
    r"(\bshould you buy\b|\bis it time to buy\b|\b\d+ (top|best) stocks\b|\bmillionaire\b|"
    r"\bsimply wall st\b|\bstock (forecast|prediction)\b|\bprice prediction\b)", re.I)


@dataclass
class Article:
    ticker: str
    title: str
    url: str
    source: str
    published: dt.datetime            # aware UTC
    retrieved: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))

    @property
    def key(self) -> str:
        return dedupe_key(self.ticker, self.title)

    def to_dict(self) -> dict:
        return {"ticker": self.ticker, "title": self.title, "url": self.url,
                "source": self.source, "published": self.published.isoformat()}

    @staticmethod
    def from_dict(d: dict) -> "Article":
        return Article(d["ticker"], d["title"], d["url"], d.get("source", ""),
                       dt.datetime.fromisoformat(d["published"]))


def clean_title(title: str) -> tuple[str, str]:
    """Split Google-News style 'Headline - Publisher' into (headline, publisher)."""
    title = re.sub(r"\s+", " ", title or "").strip()
    m = re.match(r"^(.*\S)\s+[-–—]\s+([^-–—]{2,60})$", title)
    if m:
        return m.group(1), m.group(2).strip()
    return title, ""


def normalize(title: str) -> str:
    t = clean_title(title)[0].lower()
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def dedupe_key(ticker: str, title: str) -> str:
    return hashlib.sha1(f"{ticker}|{normalize(title)}".encode()).hexdigest()[:16]


def _similar(a: str, b: str) -> float:
    """Jaccard similarity of word sets — catches the same story re-titled by syndication."""
    wa, wb = set(normalize(a).split()), set(normalize(b).split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def source_rank(source: str) -> int:
    s = (source or "").lower()
    for i, p in enumerate(PREFERRED_SOURCES):
        if p in s:
            return i
    return len(PREFERRED_SOURCES)


GENERIC_FIRST_WORDS = {"taiwan", "international", "american", "united", "general", "first", "national",
                       "china", "bank", "global", "advanced", "applied", "digital", "energy"}


def aliases(stock: Stock) -> list[str]:
    """'Alphabet (Google)' -> ['Alphabet', 'Google']; 'Taiwan Semiconductor (TSMC)' -> [..., 'TSMC']."""
    out = []
    main = re.sub(r"\(.*?\)", "", stock.name).strip()
    if main:
        out.append(main)
    out += [x.strip() for grp in re.findall(r"\((.*?)\)", stock.name) for x in grp.split("/") if x.strip()]
    return out or [stock.ticker]


def is_relevant(stock: Stock, title: str) -> bool:
    """Headline must name the company (or an alias) or ticker, and not be a content-farm listicle."""
    if NOISE_PATTERNS.search(title):
        return False
    if re.search(rf"(?<![A-Za-z]){re.escape(stock.ticker)}(?![A-Za-z])", title):
        return True
    t = title.lower()
    for name in (a.lower() for a in aliases(stock)):
        if re.search(rf"\b{re.escape(name)}\b", t):
            return True
        first = name.split()[0]
        if len(first) >= 4 and first not in GENERIC_FIRST_WORDS and re.search(rf"\b{re.escape(first)}\b", t):
            return True
    return False


def parse_rss(xml_bytes: bytes, stock: Stock, default_source: str) -> list[Article]:
    out: list[Article] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return out
    for item in root.iter("item"):
        raw_title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not raw_title or not link:
            continue
        title, publisher = clean_title(raw_title)
        src_el = item.find("source")
        source = (src_el.text.strip() if src_el is not None and src_el.text else publisher) or default_source
        try:
            published = parsedate_to_datetime(item.findtext("pubDate") or "")
            if published.tzinfo is None:
                published = published.replace(tzinfo=dt.timezone.utc)
            published = published.astimezone(dt.timezone.utc)
        except (TypeError, ValueError):
            continue  # undated items can't be placed in time; skip rather than guess
        out.append(Article(stock.ticker, title, link, source, published))
    return out


def _get(url: str, retries: int = 2) -> bytes | None:
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=12)
            if r.status_code == 429:
                time.sleep(2 + attempt * 3)
                continue
            r.raise_for_status()
            return r.content
        except requests.RequestException as e:
            if attempt == retries:
                print(f"  feed failed: {url[:80]}... ({e})")
            else:
                time.sleep(1 + attempt * 2)
    return None


def feed_urls(stock: Stock) -> list[tuple[str, str]]:
    names = " OR ".join(f'"{a}"' for a in aliases(stock))
    q = quote_plus(f'{names} OR "{stock.ticker} stock" when:2d')
    return [
        (f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={stock.ticker}&region=US&lang=en-US",
         "Yahoo Finance"),
        (f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en", "Google News"),
    ]


def dedupe(articles: list[Article]) -> list[Article]:
    """Remove exact and near-duplicate headlines, keeping the most authoritative source."""
    ordered = sorted(articles, key=lambda a: (source_rank(a.source), a.published))
    kept: list[Article] = []
    for a in ordered:
        if any(k.ticker == a.ticker and (k.key == a.key or _similar(k.title, a.title) >= 0.8)
               for k in kept):
            continue
        kept.append(a)
    return sorted(kept, key=lambda a: a.published, reverse=True)


def fetch_stock_news(stock: Stock, max_age_hours: int, fetch=_get) -> list[Article]:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=max_age_hours)
    items: list[Article] = []
    for url, src in feed_urls(stock):
        body = fetch(url)
        if body:
            items.extend(parse_rss(body, stock, src))
    items = [a for a in items if a.published >= cutoff and is_relevant(stock, a.title)]
    return dedupe(items)


def fetch_all(stocks: list[Stock], max_age_hours: int, fetch=_get) -> list[Article]:
    out: list[Article] = []
    for s in stocks:
        got = fetch_stock_news(s, max_age_hours, fetch)
        print(f"  {s.ticker}: {len(got)} recent relevant articles")
        out.extend(got)
    return out
