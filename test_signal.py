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


def _mk(closes):
    """Wrap a close series into (highs, lows, closes, vols) with tight intrabar range."""
    highs = [c * 1.005 for c in closes]
    lows = [c * 0.995 for c in closes]
    vols = [1000] * len(closes)
    return highs, lows, closes, vols


def _cup(bottom=80.0, handle_low=92.0, final=101.0, rim=100.0, steps=18):
    """Canonical rounded cup (rim 100) + shallow handle + a fresh breakout close.
    The arms actually descend to / ascend from `bottom`, so depth scales with it."""
    lead = [85 + i for i in range(16)]                                    # ..100 (left rim at index 15)
    down = [rim - (rim - bottom) * i / steps for i in range(1, steps + 1)]  # rim -> bottom
    base = [bottom, bottom + 0.5, bottom, bottom + 0.8, bottom + 0.3, bottom]  # dwell near the base
    up = [bottom + (rim - bottom) * i / steps for i in range(1, steps + 1)]  # bottom -> rim (right rim)
    handle = [97, (handle_low + 94) / 2, handle_low, 94, 97, 99]
    return _mk(lead + down + base + up + handle + [final])


class TestCupAndHandle(unittest.TestCase):
    def test_fires_on_breakout(self):
        cup = sb.detect_cup_and_handle(*_mk(_cup()[2])[:3])
        self.assertIsNotNone(cup)
        self.assertAlmostEqual(cup["rim"], 100.0, delta=1.0)
        # target = breakout (rim) + cup depth (~20)
        self.assertAlmostEqual(cup["target"], cup["rim"] + cup["depth"], places=2)
        self.assertGreater(cup["target"], cup["rim"])
        r = sb.evaluate(*_cup())
        self.assertTrue(r["cup_fires"])
        self.assertEqual(r["cup_target"], cup["target"])

    def test_no_breakout_does_not_fire(self):
        # valid cup + handle, but the last close is still below the rim
        self.assertIsNone(sb.detect_cup_and_handle(*_cup(final=99.0)[:3]))

    def test_too_shallow_is_not_a_cup(self):
        # bottom at 95 -> ~5% depth, below CUP_MIN_DEPTH_PCT
        self.assertIsNone(sb.detect_cup_and_handle(*_cup(bottom=95.0)[:3]))

    def test_deep_handle_rejected(self):
        # handle retraces past the upper half of the cup
        self.assertIsNone(sb.detect_cup_and_handle(*_cup(handle_low=84.0)[:3]))

    def test_sharp_v_is_not_rounded(self):
        lead = [85 + i for i in range(16)]
        down = [100 - (12 / 15) * i for i in range(1, 16)]    # 100 -> 88 gently
        spike = [80.0]                                        # single-bar tip (sharp V)
        up = [88 + (12 / 15) * i for i in range(1, 16)]       # 88 -> 100
        handle = [97, 93, 92, 94, 97, 99]
        self.assertIsNone(sb.detect_cup_and_handle(*_mk(lead + down + spike + up + handle + [101.0])[:3]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
