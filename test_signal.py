"""Tests for the crash-risk guard in signal_bot.evaluate (offline, no network)."""

import os
import unittest

os.environ.setdefault("TELEGRAM_TOKEN", "x")
os.environ.setdefault("TELEGRAM_CHAT_ID", "1")

import signal_bot as sb


class TestCrashGuard(unittest.TestCase):
    def test_worst_daily_drop(self):
        self.assertAlmostEqual(sb.worst_daily_drop([100, 80, 90]), -20.0, places=1)
        self.assertLess(sb.worst_daily_drop([100, 68, 75]), -30)        # ~ -32% like CRVL
        self.assertEqual(sb.worst_daily_drop([100, 101, 102, 103]), 0.0)  # monotonic up -> no drop

    def test_crash_blocks_buy_signal(self):
        # build a 60-bar mild uptrend with one violent -30% crash day
        closes, v = [], 50.0
        for i in range(60):
            v = v * 1.01 + (2 if i % 4 == 0 else -1)
            closes.append(v)
        closes[30] = closes[29] * 0.70                                  # -30% crash
        highs = [c * 1.01 for c in closes]
        lows = [c * 0.99 for c in closes]
        vols = [1000] * 60
        self.assertLessEqual(sb.worst_daily_drop(closes), -20)
        r = sb.evaluate(highs, lows, closes, vols)
        if r is not None:                       # if there are enough pivots to evaluate
            self.assertTrue(r["crash_risk"])
            self.assertFalse(r["fires"])        # a crash-risk stock must never "fire" as a buy


if __name__ == "__main__":
    unittest.main(verbosity=2)
