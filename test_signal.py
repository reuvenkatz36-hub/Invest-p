"""Tests for the stability (erratic-swing) guard in signal_bot.evaluate (offline, no network)."""

import os
import unittest

os.environ.setdefault("TELEGRAM_TOKEN", "x")
os.environ.setdefault("TELEGRAM_CHAT_ID", "1")

import signal_bot as sb


class TestSwingGuard(unittest.TestCase):
    def test_largest_daily_swing(self):
        worst, best = sb.largest_daily_swing([100, 80, 90])      # -20% then +12.5%
        self.assertAlmostEqual(worst, -20.0, places=1)
        self.assertGreater(best, 0)
        worst2, best2 = sb.largest_daily_swing([100, 135, 130])  # +35% jump up
        self.assertGreaterEqual(best2, 35 - 0.1)
        self.assertEqual(sb.largest_daily_swing([100, 101, 102, 103])[0], 0.0)  # smooth: no drop

    def _series_with_move(self, factor):
        closes, v = [], 50.0
        for i in range(60):
            v = v * 1.01 + (2 if i % 4 == 0 else -1)
            closes.append(v)
        closes[30] = closes[29] * factor                         # inject one violent day
        highs = [c * 1.01 for c in closes]
        lows = [c * 0.99 for c in closes]
        return highs, lows, closes, [1000] * 60

    def test_crash_down_blocks_buy(self):
        r = sb.evaluate(*self._series_with_move(0.70))           # -30% crash
        if r is not None:
            self.assertTrue(r["erratic"])
            self.assertFalse(r["fires"])

    def test_jump_up_blocks_buy(self):
        r = sb.evaluate(*self._series_with_move(1.30))           # +30% jump UP
        if r is not None:
            self.assertTrue(r["erratic"])
            self.assertFalse(r["fires"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
