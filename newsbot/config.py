"""Configuration: config.json (watchlist + schedule settings) and environment secrets."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("NEWSBOT_CONFIG", ROOT / "config.json"))
STATE_PATH = Path(os.environ.get("NEWSBOT_STATE", ROOT / "state.json"))

TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


@dataclass
class Stock:
    ticker: str
    name: str


@dataclass
class Config:
    timezone: str = "Asia/Jerusalem"
    quiet_enabled: bool = True
    quiet_start: str = "23:00"
    quiet_end: str = "07:00"
    pre_market_lead_minutes: int = 60
    post_market_delay_minutes: int = 20
    max_article_age_hours: int = 36
    max_alerts_per_run: int = 6
    watchlist: list[Stock] = field(default_factory=list)

    def tickers(self) -> list[str]:
        return [s.ticker for s in self.watchlist]

    def find(self, ticker: str) -> Stock | None:
        return next((s for s in self.watchlist if s.ticker == ticker.upper()), None)


def load_config(path: Path = CONFIG_PATH) -> Config:
    raw = json.loads(Path(path).read_text())
    quiet = raw.get("quiet_hours", {})
    return Config(
        timezone=raw.get("timezone", "Asia/Jerusalem"),
        quiet_enabled=bool(quiet.get("enabled", True)),
        quiet_start=quiet.get("start", "23:00"),
        quiet_end=quiet.get("end", "07:00"),
        pre_market_lead_minutes=int(raw.get("pre_market_lead_minutes", 60)),
        post_market_delay_minutes=int(raw.get("post_market_delay_minutes", 20)),
        max_article_age_hours=int(raw.get("max_article_age_hours", 36)),
        max_alerts_per_run=int(raw.get("max_alerts_per_run", 6)),
        watchlist=[Stock(s["ticker"].upper(), s.get("name") or s["ticker"].upper())
                   for s in raw.get("watchlist", [])],
    )


def save_watchlist(cfg: Config, path: Path = CONFIG_PATH) -> None:
    """Rewrite only the watchlist in config.json, preserving every other setting."""
    raw = json.loads(Path(path).read_text())
    raw["watchlist"] = [{"ticker": s.ticker, "name": s.name} for s in cfg.watchlist]
    Path(path).write_text(json.dumps(raw, indent=2) + "\n")


@dataclass
class Secrets:
    telegram_token: str
    telegram_chat_id: str
    anthropic_key: str
    claude_model: str
    use_fallbacks: bool


def load_secrets() -> Secrets:
    return Secrets(
        telegram_token=os.environ.get("TELEGRAM_TOKEN", ""),
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
        anthropic_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        claude_model=os.environ.get("CLAUDE_MODEL", "claude-opus-5-5"),
        use_fallbacks=os.environ.get("CLAUDE_FALLBACKS", "1") != "0",
    )
