"""Persistent bot state (seen articles, queued items, sent briefings, Telegram offset).

Stored as JSON. In GitHub Actions the file is carried between runs with actions/cache.
If the state is ever lost, the bot bootstraps silently (marks current news as seen)
instead of flooding you with old headlines.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

SEEN_RETENTION_DAYS = 10
ALERT_RETENTION_HOURS = 72
QUEUE_MAX = 80


def empty_state() -> dict:
    return {
        "version": 1,
        "seen": {},            # dedupe key -> unix ts first seen
        "queue": [],           # medium items waiting for the next briefing
        "held": [],            # high items held back during quiet hours
        "recent_alerts": [],   # [{ts, ticker, title, event}] for cross-run event dedupe
        "briefings": {},       # "YYYY-MM-DD:pre|post|closed" -> unix ts sent
        "last_briefing_ts": 0,
        "telegram_offset": 0,
        "last_scan_ts": 0,
        "bootstrapped": False,
    }


def load_state(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text())
        base = empty_state()
        base.update(data)
        return base
    except (FileNotFoundError, json.JSONDecodeError):
        return empty_state()


def prune(state: dict, now: float | None = None) -> dict:
    now = now or time.time()
    cutoff = now - SEEN_RETENTION_DAYS * 86400
    state["seen"] = {k: ts for k, ts in state["seen"].items() if ts >= cutoff}
    a_cut = now - ALERT_RETENTION_HOURS * 3600
    state["recent_alerts"] = [a for a in state["recent_alerts"] if a.get("ts", 0) >= a_cut]
    state["queue"] = state["queue"][-QUEUE_MAX:]
    b_cut = now - 14 * 86400
    state["briefings"] = {k: ts for k, ts in state["briefings"].items() if ts >= b_cut}
    return state


def save_state(state: dict, path: Path) -> None:
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(prune(state), indent=1, sort_keys=True))
    tmp.replace(path)
