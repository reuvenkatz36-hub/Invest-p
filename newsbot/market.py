"""US market calendar (NYSE): trading days, holidays, early closes, briefing timing.

All decisions use real exchange session times (exchange_calendars XNYS), so US and
Israeli daylight-saving shifts, holidays and early-close days are handled automatically.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from functools import lru_cache
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

ET = ZoneInfo("America/New_York")
UTC = dt.timezone.utc


@lru_cache(maxsize=1)
def _calendar():
    return xcals.get_calendar("XNYS")


@dataclass
class Session:
    date: dt.date          # session date (US Eastern)
    open: dt.datetime      # aware UTC
    close: dt.datetime     # aware UTC

    @property
    def early_close(self) -> bool:
        return self.close.astimezone(ET).time() < dt.time(16, 0)


def session_for(date: dt.date) -> Session | None:
    """The NYSE regular session on `date`, or None if the market is closed that day."""
    cal = _calendar()
    ts = pd.Timestamp(date)
    if ts < cal.first_session or ts > cal.last_session or not cal.is_session(ts):
        return None
    return Session(
        date=date,
        open=cal.session_open(ts).to_pydatetime().astimezone(UTC),
        close=cal.session_close(ts).to_pydatetime().astimezone(UTC),
    )


def next_session(after: dt.date) -> Session | None:
    for i in range(1, 15):
        s = session_for(after + dt.timedelta(days=i))
        if s:
            return s
    return None


def previous_session(before: dt.date) -> Session | None:
    for i in range(1, 15):
        s = session_for(before - dt.timedelta(days=i))
        if s:
            return s
    return None


def et_date(now: dt.datetime) -> dt.date:
    return now.astimezone(ET).date()


def closed_reason(date: dt.date) -> str:
    if date.weekday() >= 5:
        return "weekend"
    return "US market holiday"


@dataclass
class DueBriefing:
    kind: str        # "pre" | "post" | "closed"
    key: str         # state key, e.g. "2026-11-23:pre"
    session: Session | None
    late: bool = False


def due_briefing(now: dt.datetime, sent: dict, lead_min: int, delay_min: int) -> DueBriefing | None:
    """Which briefing (if any) should go out right now.

    - Trading day:  "pre"  from (open - lead) until close; marked late after the open.
                    "post" from (close + delay) until the end of the US/Eastern day.
    - Closed day:   one "closed" edition from 09:00 ET (a weekend/holiday news digest).
    GitHub's scheduler often fires late, so each edition has a window rather than a minute.
    """
    today = et_date(now)
    sess = session_for(today)
    if sess is None:
        key = f"{today.isoformat()}:closed"
        start = dt.datetime.combine(today, dt.time(9, 0), tzinfo=ET)
        if key not in sent and now >= start:
            return DueBriefing("closed", key, None)
        return None

    pre_key, post_key = f"{today.isoformat()}:pre", f"{today.isoformat()}:post"
    pre_start = sess.open - dt.timedelta(minutes=lead_min)
    post_start = sess.close + dt.timedelta(minutes=delay_min)
    if post_key not in sent and now >= post_start:
        return DueBriefing("post", post_key, sess)
    if pre_key not in sent and pre_start <= now < sess.close:
        return DueBriefing("pre", pre_key, sess, late=now >= sess.open)
    return None


def market_status(now: dt.datetime) -> str:
    sess = session_for(et_date(now))
    if sess is None:
        return "closed"
    if now < sess.open:
        return "pre-market"
    if now < sess.close:
        return "open"
    return "after-hours"
