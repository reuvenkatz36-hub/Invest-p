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


class TestSharperGates(unittest.TestCase):
    def _uptrend(self, n=300):
        # staircase uptrend with real pullbacks so swing highs AND lows form:
        # 15 bars up ~1%, then 6 bars down ~1.2% (net rising)
        closes, v = [], 50.0
        for i in range(n):
            v = v * (1.010 if i % 21 < 15 else 0.988)
            closes.append(v)
        return closes

    def test_old_crash_no_longer_erratic(self):
        # a -25% day ~290 bars ago is OUTSIDE the 252-bar window -> not erratic anymore
        closes = self._uptrend(300)
        closes[10] = closes[9] * 0.75
        highs = [c * 1.01 for c in closes]; lows = [c * 0.99 for c in closes]
        r = sb.evaluate(highs, lows, closes, [1000] * 300)
        self.assertFalse(r["erratic"])

    def test_recent_crash_still_erratic(self):
        closes = self._uptrend(300)
        closes[-30] = closes[-31] * 0.75          # same crash inside the last year
        highs = [c * 1.01 for c in closes]; lows = [c * 0.99 for c in closes]
        r = sb.evaluate(highs, lows, closes, [1000] * 300)
        self.assertTrue(r["erratic"])
        self.assertFalse(r["fires"])

    def test_volume_spike_yesterday_counts(self):
        closes = self._uptrend(120)
        highs = [c * 1.01 for c in closes]; lows = [c * 0.99 for c in closes]
        vols = [1000] * 120
        vols[-2] = 2500                            # the bounce's volume day was yesterday
        r = sb.evaluate(highs, lows, closes, vols)
        self.assertTrue(r["volume_ok"])
        vols[-2] = 1000                            # neither of the last 2 bars beats the average
        r = sb.evaluate(highs, lows, closes, vols)
        self.assertFalse(r["volume_ok"])

    def test_gate_misses_names_the_failures(self):
        r = {"turning_up": False, "volume_ok": True, "erratic": False, "in_macro_downtrend": True}
        self.assertEqual(sb.gate_misses(r), ["not turning up", "macro downtrend"])
        r_ok = {"turning_up": True, "volume_ok": True, "erratic": False, "in_macro_downtrend": False}
        self.assertEqual(sb.gate_misses(r_ok), [])


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


def _flat_base(level=100.0, floor=90.0, tail=("break",)):
    """A flat-top base: ~3 ceiling touches at `level` over ~60 bars, floor at `floor`,
    then a tail: 'break' (fresh close above), 'stall' (still under), or a retest sequence."""
    cyc = []
    for _ in range(3):                                   # three touches at the ceiling
        cyc += [floor + (level - floor) * i / 9 for i in range(1, 10)] + [level]
        cyc += [level - (level - floor) * i / 9 for i in range(1, 10)] + [floor]
    closes = [95.0] * 12 + cyc                           # lead-in so pivots have left context
    closes += [floor + (level - floor) * i / 9 for i in range(1, 9)]   # climb back toward the rim
    if tail == ("break",):
        closes += [level * 1.01]
    elif tail == ("stall",):
        closes += [level * 0.99]
    else:
        closes += list(tail)                              # custom post-rim bars (retest scenarios)
    return _mk(closes)


class TestFlatTopAndRetest(unittest.TestCase):
    def test_flat_top_breakout_fires(self):
        flat = sb.detect_flat_top(*_flat_base()[:3])
        self.assertIsNotNone(flat)
        self.assertEqual(flat["kind"], "breakout")
        self.assertGreaterEqual(flat["touches"], 3)
        self.assertAlmostEqual(flat["target"], flat["level"] + flat["height"], places=2)

    def test_no_breakout_no_fire(self):
        self.assertIsNone(sb.detect_flat_top(*_flat_base(tail=("stall",))[:3]))

    def test_two_touches_not_enough(self):
        # only 2 ceiling touches -> no flat top
        cyc = []
        for _ in range(2):
            cyc += [90 + i for i in range(1, 10)] + [100]
            cyc += [100 - i for i in range(1, 10)] + [90]
        closes = [95.0] * 12 + cyc + [90 + i for i in range(1, 9)] + [101.0]
        self.assertIsNone(sb.detect_flat_top(*_mk(closes)[:3]))

    def test_retest_second_chance_fires(self):
        # break out, run, pull back to the level, hold, turn up -> retest entry
        tail = [101.0, 104.0, 106.0, 103.0, 101.5, 100.5, 102.5]
        flat = sb.detect_flat_top(*_flat_base(tail=tuple(tail))[:3])
        self.assertIsNotNone(flat)
        self.assertEqual(flat["kind"], "retest")

    def test_failed_breakout_no_retest(self):
        # breaks out then collapses back UNDER the level -> failed breakout, no entry
        tail = [101.0, 104.0, 99.0, 95.0, 94.0, 96.0, 97.0]
        self.assertIsNone(sb.detect_flat_top(*_flat_base(tail=tuple(tail))[:3]))

    def test_evaluate_reports_flat_fields(self):
        r = sb.evaluate(*_flat_base())
        self.assertTrue(r["flat_fires"])
        self.assertEqual(r["flat_kind"], "breakout")
        self.assertIsNotNone(r["flat_target"])


class TestGoldenCross(unittest.TestCase):
    def _series(self, first, then, n1=200, n2=30):
        return [first] * n1 + [then] * n2

    def test_fresh_cross(self):
        # flat at 100 for 200 bars, then a jump to 130 for the last 30 -> 50d SMA just crossed the 200d
        closes = self._series(100.0, 130.0)
        highs = [c * 1.01 for c in closes]; lows = [c * 0.99 for c in closes]
        r = sb.evaluate(highs, lows, closes, [1000] * len(closes))
        if r is not None:
            self.assertIn(r["golden_cross"], ("fresh", "active"))

    def test_downtrend_no_cross(self):
        closes = [130.0] * 200 + [95.0] * 30       # 50d SMA below 200d
        highs = [c * 1.01 for c in closes]; lows = [c * 0.99 for c in closes]
        r = sb.evaluate(highs, lows, closes, [1000] * len(closes))
        if r is not None:
            self.assertIsNone(r["golden_cross"])


class TestEnrichQualityGates(unittest.TestCase):
    """The daily alert must show only clean sheets (zero red flags), capped at MAX_ALERTS,
    ranked by score — and run the expensive AI/news enrichment ONLY for the finalists."""

    def setUp(self):
        import xray
        self._orig = (sb.revenue_growth, xray.xray, xray._ai_layer, sb.fetch_news)
        self.ai_calls = []
        def fake_xray(sym, ai=False):
            score, reds = self.profiles[sym]
            items = [{"label": "Debt", "flag": "red"}] * reds + [{"label": "FCF", "flag": "green"}]
            return {"ok": True, "score": score, "coverage": 0.9, "items": items,
                    "verdict": "Excellent", "opportunity": "o", "danger": "d"}
        sb.revenue_growth = lambda sym: self.revs.get(sym, ("yes", "rev +9% YoY"))
        xray.xray = fake_xray
        xray._ai_layer = lambda sym, xr, web=False: self.ai_calls.append(sym)
        sb.fetch_news = lambda sym, limit=3: []

    def tearDown(self):
        import xray
        sb.revenue_growth, xray.xray, xray._ai_layer, sb.fetch_news = self._orig

    def test_red_flags_blocked_and_top_n_capped(self):
        # 8 hits: one has a red flag, one has declining revenue, six are clean (scores 10..5)
        self.profiles = {"REDF": (9, 1), "NORV": (10, 0),
                         "A": (10, 0), "B": (9, 0), "C": (9, 0), "D": (8, 0), "E": (8, 0), "F": (8, 0)}
        self.revs = {"NORV": ("no", "rev -2% YoY")}
        hits = [(s, {"price": 10.0}) for s in self.profiles]
        kept, drops = sb.enrich_hits(hits)
        syms = [h["sym"] for h in kept]
        self.assertNotIn("REDF", syms)                     # red flag -> out
        self.assertNotIn("NORV", syms)                     # revenue -> out
        self.assertLessEqual(len(kept), sb.MAX_ALERTS)     # capped
        self.assertEqual(syms[0], "A")                     # best score first
        self.assertEqual(drops["red_flags"], 1)
        self.assertEqual(drops["revenue"], 1)
        self.assertEqual(drops["beyond_top"], 6 - sb.MAX_ALERTS)
        # expensive AI layer ran only for the finalists
        self.assertEqual(sorted(self.ai_calls), sorted(syms))

    def test_equal_scores_ranked_by_strategy_fit(self):
        # same health score -> the more textbook setup (bounce+cup+fresh golden cross)
        # must outrank a lone retest
        self.profiles = {"WEAK": (9, 0), "STRONG": (9, 0)}
        self.revs = {}
        strong_r = {"price": 10.0, "fires": True, "cup_fires": True, "cup_kind": "breakout",
                    "golden_cross": "fresh", "is_uptrend": True, "volume_ok": True}
        weak_r = {"price": 10.0, "fires": False, "flat_fires": True, "flat_kind": "retest",
                  "golden_cross": None, "is_uptrend": True, "volume_ok": False}
        kept, _ = sb.enrich_hits([("WEAK", weak_r), ("STRONG", strong_r)])
        self.assertEqual([h["sym"] for h in kept], ["STRONG", "WEAK"])
        self.assertGreater(sb.setup_strength(strong_r), sb.setup_strength(weak_r))

    def test_all_clean_under_cap_all_kept(self):
        self.profiles = {"X": (9, 0), "Y": (10, 0)}
        self.revs = {}
        kept, drops = sb.enrich_hits([(s, {"price": 5.0}) for s in self.profiles])
        self.assertEqual([h["sym"] for h in kept], ["Y", "X"])
        self.assertEqual(drops["beyond_top"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
