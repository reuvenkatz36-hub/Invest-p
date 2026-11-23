"""Price data via yfinance (daily bars). Every quote carries the date of the bar it came
from, so a briefing can never present yesterday's close as today's."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

INDICES = [("^GSPC", "S&P 500"), ("^IXIC", "Nasdaq"), ("^DJI", "Dow"), ("^VIX", "VIX")]
FUTURES = [("ES=F", "S&P futures"), ("NQ=F", "Nasdaq futures")]


@dataclass
class Quote:
    symbol: str
    label: str
    last: float
    prev_close: float
    bar_date: dt.date

    @property
    def change_pct(self) -> float:
        return (self.last / self.prev_close - 1) * 100 if self.prev_close else 0.0

    def line(self) -> str:
        arrow = "▲" if self.change_pct > 0 else ("▼" if self.change_pct < 0 else "▪")
        return f"{arrow} {self.label} {self.last:,.2f} ({self.change_pct:+.1f}%)"


def daily_quotes(symbols: list[tuple[str, str]]) -> dict[str, Quote]:
    """Last daily bar vs the one before it, per symbol. Missing data is simply omitted."""
    out: dict[str, Quote] = {}
    if not symbols:
        return out
    try:
        import yfinance as yf
        data = yf.download([s for s, _ in symbols], period="7d", interval="1d",
                           group_by="ticker", auto_adjust=False, progress=False, threads=True)
    except Exception as e:  # network / provider outage: briefing degrades gracefully
        print(f"price download failed: {e}")
        return out
    for sym, label in symbols:
        try:
            closes = (data[sym]["Close"] if len(symbols) > 1 else data["Close"]).dropna()
            if hasattr(closes, "columns"):     # newer yfinance returns a 1-col frame
                closes = closes.iloc[:, 0]
            if len(closes) < 2:
                continue
            out[sym] = Quote(sym, label, float(closes.iloc[-1]), float(closes.iloc[-2]),
                             closes.index[-1].date())
        except Exception:
            continue
    return out
