"""Tests for the hard revenue-growth gate at buy time (chat_bot.handle_buy / handle_message).

Fully offline: analyze_symbol is monkeypatched so no network/yfinance calls happen.
Run:  python -m unittest test_chat -v
"""

import os
import unittest

os.environ.setdefault("TELEGRAM_TOKEN", "x")
os.environ.setdefault("TELEGRAM_CHAT_ID", "1")

import chat_bot as cb


def fake_analyze(rev_status):
    """Return an analyze_symbol stand-in with a fixed revenue status and a firing setup."""
    r = {"fires": True, "is_uptrend": True, "higher_highs": True, "higher_lows": True,
         "near_support": True, "in_zone": True, "volume_ok": True, "pct": 5.0}
    label = {"yes": "rev +8% YoY", "no": "rev -3% YoY", "unknown": "rev n/a"}[rev_status]
    return lambda sym: (r, rev_status, label, [])


class TestRevenueGate(unittest.TestCase):
    def setUp(self):
        self._orig = cb.analyze_symbol

    def tearDown(self):
        cb.analyze_symbol = self._orig

    def test_unconfirmed_revenue_is_blocked(self):
        cb.analyze_symbol = fake_analyze("unknown")
        trades = {"open": [], "closed": []}
        msg = cb.handle_buy("DAC", 50.0, None, 10, trades)
        self.assertIn("⛔", msg)
        self.assertIn("force", msg.lower())
        self.assertEqual(trades["open"], [])          # nothing recorded

    def test_declining_revenue_is_blocked(self):
        cb.analyze_symbol = fake_analyze("no")
        trades = {"open": [], "closed": []}
        msg = cb.handle_buy("CWEN", 20.0, None, 5, trades)
        self.assertIn("⛔", msg)
        self.assertIn("DECLINING", msg)
        self.assertEqual(trades["open"], [])

    def test_force_records_but_flags_off_strategy(self):
        cb.analyze_symbol = fake_analyze("unknown")
        trades = {"open": [], "closed": []}
        msg = cb.handle_buy("DAC", 50.0, None, 10, trades, force=True)
        self.assertEqual(len(trades["open"]), 1)
        self.assertEqual(trades["open"][0].get("off_strategy"), "unconfirmed_revenue")
        self.assertIn("OFF-STRATEGY", msg)

    def test_confirmed_revenue_records_normally(self):
        cb.analyze_symbol = fake_analyze("yes")
        trades = {"open": [], "closed": []}
        msg = cb.handle_buy("NVDA", 240.0, None, 10, trades)
        self.assertEqual(len(trades["open"]), 1)
        self.assertNotIn("off_strategy", trades["open"][0])
        self.assertIn("Recorded BUY", msg)

    def test_message_force_keyword_threads_through(self):
        cb.analyze_symbol = fake_analyze("unknown")
        trades = {"open": [], "closed": []}
        blocked = cb.handle_message("bought 10 DAC at 50", trades)
        self.assertIn("⛔", blocked)
        self.assertEqual(trades["open"], [])
        forced = cb.handle_message("bought 10 DAC at 50 force", trades)
        self.assertEqual(len(trades["open"]), 1)
        self.assertEqual(trades["open"][0].get("off_strategy"), "unconfirmed_revenue")

    def test_force_is_not_parsed_as_ticker(self):
        self.assertNotIn("FORCE", cb.extract_ticker("bought 10 DAC at 50 force") or "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
