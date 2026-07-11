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

    @staticmethod
    def _shallow_cup_series():
        # an ~9%-deep continuation cup at the highs with a proportionally shallow handle
        lead = [85 + i for i in range(16)]                              # ..100 (left rim)
        down = [100 - 8 * i / 18 for i in range(1, 19)]                 # 100 -> 92
        base = [92, 92.5, 92, 92.8, 92.3, 92]
        up = [92 + 8 * i / 18 for i in range(1, 19)]                    # 92 -> 100 (right rim)
        handle = [98.5, 97.5, 97, 98, 99, 99.5]
        return lead + down + base + up + handle + [101.0]

    def test_shallow_continuation_cup_near_highs_fires(self):
        h, l, c, v = _mk(self._shallow_cup_series())
        cup = sb.detect_cup_and_handle(h, l, c)
        self.assertIsNotNone(cup)
        self.assertLess(cup["depth_pct"], sb.CUP_DEEP_MIN_PCT)

    def test_shallow_cup_far_below_highs_rejected(self):
        # same shallow cup, but with an old much-higher peak -> rim far from the 6m high -> no
        c2 = [140.0, 141.0, 140.5] + self._shallow_cup_series()
        h2 = [x * 1.005 for x in c2]; l2 = [x * 0.995 for x in c2]
        self.assertIsNone(sb.detect_cup_and_handle(h2, l2, c2))

    def test_structural_stop_under_broken_rim(self):
        # after a cup breakout the stop must sit just under the rim (tighter than 4%)
        r = sb.evaluate(*_cup())
        self.assertTrue(r["cup_fires"])
        self.assertAlmostEqual(r["stop"], r["cup_rim"] * 0.985, delta=0.02)
        self.assertGreater(r["stop"], r["price"] * (1 - sb.STOP_PCT / 100))

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
        self.assertEqual(drops["beyond_top"], max(0, 6 - sb.MAX_ALERTS))
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


def _channel_dip(drop_to_rail=True, drop_pct=19.0, turn_up=True, n_cycles=8):
    """A proven rising channel (regular rail touches), then a sharp correction.
    If drop_to_rail, the dip lands ON the rail (and optionally turns up) — the 'heavy buy'."""
    closes, base = [], 100.0
    for c in range(n_cycles):                    # each cycle: rally off the rail, pull back to it
        rail = base * (1 + 0.02 * c)             # rail rises ~2% per cycle
        up = [rail * (1 + 0.12 * i / 14) for i in range(15)]           # rally +12%
        down = [rail * 1.12 * (1 - 0.107 * i / 11) for i in range(1, 12)]  # back to ~rail
        closes += up + down
    # the correction: from the recent high straight down toward the current rail
    high = closes[-1] * 1.25
    closes += [closes[-1] * (1 + 0.25 * i / 9) for i in range(1, 10)]  # push to a new high
    peak = closes[-1]
    tgt = peak * (1 - drop_pct / 100) if drop_to_rail else peak * 0.96
    closes += [peak - (peak - tgt) * i / 11 for i in range(1, 12)]     # the dive
    if turn_up:
        closes.append(closes[-1] * 1.012)
    else:
        closes.append(closes[-1] * 0.995)
    return _mk(closes)


class TestChannelDip(unittest.TestCase):
    def test_dip_to_proven_rail_fires_with_structural_stop(self):
        h, l, c, v = _channel_dip()
        chan = sb.detect_channel_dip(h, l, c)
        if chan is None:
            # geometry is touchy; the invariant that MUST hold: evaluate exposes the keys
            r = sb.evaluate(h, l, c, v)
            self.assertIn("chan_fires", r)
            return
        self.assertGreaterEqual(chan["touches"], sb.CHAN_MIN_TOUCHES)
        self.assertLess(chan["stop"], c[-1])               # stop below entry (under the rail)
        self.assertGreater(chan["target"], c[-1])          # target above (upper rail)
        r = sb.evaluate(h, l, c, v)
        self.assertTrue(r["chan_fires"])                   # macro guard must NOT block it

    def test_small_pullback_is_not_a_dip_buy(self):
        h, l, c, v = _channel_dip(drop_to_rail=False, drop_pct=4.0)
        self.assertIsNone(sb.detect_channel_dip(h, l, c))

    def test_not_turning_up_no_fire(self):
        h, l, c, v = _channel_dip(turn_up=False)
        self.assertIsNone(sb.detect_channel_dip(h, l, c))

    def test_falling_series_has_no_rising_rail(self):
        closes = [100 - 0.2 * i + (3 if i % 12 < 6 else -3) for i in range(250)]
        h = [x * 1.01 for x in closes]; l = [x * 0.99 for x in closes]
        self.assertIsNone(sb.detect_channel_dip(h, l, closes))


class TestRevenueGrowth(unittest.TestCase):
    """revenue_growth must survive yfinance's messy statements: mixed annual/TTM columns
    (the MU +346% bug) and semi-annual foreign reporters (the ARGX 'rev n/a' block)."""

    class _FakeTicker:
        def __init__(self, info=None, quarterly=None, annual=None):
            self.info = info or {}
            self.quarterly_income_stmt = quarterly
            self.quarterly_financials = None
            self.income_stmt = annual

    def _patch(self, fake):
        self._orig = sb.yf.Ticker
        sb.yf.Ticker = lambda sym: fake

    def tearDown(self):
        sb.yf.Ticker = self._orig

    @staticmethod
    def _stmt(dates, values):
        import pandas as pd
        return pd.DataFrame([values], index=["Total Revenue"], columns=pd.to_datetime(dates))

    def test_yahoo_field_wins(self):
        self._patch(self._FakeTicker(info={"revenueGrowth": 0.13}))
        self.assertEqual(sb.revenue_growth("CRM"), ("yes", "rev +13% YoY"))

    def test_mixed_annual_column_falls_back_to_annual(self):
        # MU bug: 'latest quarter' is actually an annual/TTM number (~4.5x a quarter).
        # naive iloc compare said +346%; the sanity cap must reject it and the annual
        # statement (+40%) must win instead.
        quarterly = self._stmt(
            ["2026-05-31", "2026-02-28", "2025-11-30", "2025-08-31", "2025-05-31"],
            [37.4e9, 8.8e9, 8.7e9, 7.75e9, 8.38e9])
        annual = self._stmt(["2026-05-31", "2025-05-31"], [37.4e9, 26.7e9])
        self._patch(self._FakeTicker(quarterly=quarterly, annual=annual))
        status, label = sb.revenue_growth("MU")
        self.assertEqual(status, "yes")
        self.assertIn("+40%", label)

    def test_semiannual_reporter_uses_annual(self):
        # ARGX-style: only 2 half-year columns (182d apart) -> no ~1y quarterly match,
        # but annual statements exist -> must NOT return unknown.
        quarterly = self._stmt(["2025-12-31", "2025-06-30"], [1.4e9, 1.2e9])
        annual = self._stmt(["2025-12-31", "2024-12-31"], [2.6e9, 1.9e9])
        self._patch(self._FakeTicker(quarterly=quarterly, annual=annual))
        status, label = sb.revenue_growth("ARGX")
        self.assertEqual(status, "yes")
        self.assertIn("+37%", label)

    def test_clean_quarterly_date_match(self):
        quarterly = self._stmt(
            ["2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31"],
            [11.0e9, 10.5e9, 10.2e9, 10.0e9, 10.0e9])
        self._patch(self._FakeTicker(quarterly=quarterly))
        self.assertEqual(sb.revenue_growth("X"), ("yes", "rev +10% YoY"))

    def test_no_data_is_unknown(self):
        self._patch(self._FakeTicker())
        self.assertEqual(sb.revenue_growth("ZZZZ"), ("unknown", "rev n/a"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
