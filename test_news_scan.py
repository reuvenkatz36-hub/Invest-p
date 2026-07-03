"""Tests for the morning news scan (news_scan.py). Fully offline — all network calls
(feeds, price download, X-ray, revenue) are monkeypatched."""

import os
import unittest

os.environ.setdefault("TELEGRAM_TOKEN", "x")
os.environ.setdefault("TELEGRAM_CHAT_ID", "1")

import news_scan as ns
import signal_bot as sb


class TestJsonExtraction(unittest.TestCase):
    def test_clean_array(self):
        self.assertEqual(ns.extract_json_array('[{"ticker":"NVDA"}]'), [{"ticker": "NVDA"}])

    def test_array_wrapped_in_prose(self):
        txt = 'Sure! Here are the picks:\n[{"ticker":"AAPL","catalyst":"beat"}]\nHope that helps.'
        self.assertEqual(ns.extract_json_array(txt), [{"ticker": "AAPL", "catalyst": "beat"}])

    def test_garbage_returns_empty(self):
        self.assertEqual(ns.extract_json_array("no json here"), [])
        self.assertEqual(ns.extract_json_array("[broken"), [])
        self.assertEqual(ns.extract_json_array(None), [])


class TestValidatePicks(unittest.TestCase):
    def test_filters_bad_tickers_and_dupes(self):
        picks = [
            {"ticker": "nvda", "catalyst": "earnings beat"},
            {"ticker": "NVDA", "catalyst": "duplicate"},
            {"ticker": "TOOLONGG", "catalyst": "x"},
            {"ticker": "BRK-B", "catalyst": "buffett"},
            {"ticker": "AAPL", "catalyst": ""},          # no catalyst
            "not a dict",
        ]
        out = ns.validate_picks(picks)
        self.assertEqual([p["ticker"] for p in out], ["NVDA", "BRK-B"])


class TestRankingAndGates(unittest.TestCase):
    def _patch(self, r_by_sym, score_by_sym, rev_by_sym):
        self._orig = (sb.download_chunk, sb.get_ohlcv, sb.evaluate, sb.revenue_growth, ns.xray.xray)
        sb.download_chunk = lambda syms, retries=2: {"data": syms[0]}
        sb.get_ohlcv = lambda data, sym: ("h", "l", "c", "v")
        current = {}
        sb.evaluate = lambda h, l, c, v: current["r"]

        def fake_eval_candidates_prep(sym):
            current["r"] = r_by_sym.get(sym)
        self._prep = fake_eval_candidates_prep
        ns.xray.xray = lambda sym, ai=False: {"ok": True, "score": score_by_sym[sym]}
        sb.revenue_growth = lambda sym: rev_by_sym[sym]
        # evaluate_candidates calls download->get_ohlcv->evaluate per sym; hook via download
        orig_dl = sb.download_chunk
        def dl(syms, retries=2):
            self._prep(syms[0])
            return orig_dl(syms, retries)
        sb.download_chunk = dl

    def _unpatch(self):
        sb.download_chunk, sb.get_ohlcv, sb.evaluate, sb.revenue_growth, ns.xray.xray = self._orig

    def test_gates_and_ranking(self):
        base = dict(erratic=False, cup_fires=False, flat_fires=False, pulled_back=False,
                    is_uptrend=True, price=100.0, golden_cross=None)
        r_by_sym = {
            "FIRE": {**base, "fires": True},
            "UPTR": {**base, "fires": False},
            "LOWS": {**base, "fires": True},              # will fail the health bar
            "NORV": {**base, "fires": True},              # will fail revenue
            "WILD": {**base, "fires": False, "erratic": True},   # erratic — never a pick
        }
        score_by_sym = {"FIRE": 8, "UPTR": 9, "LOWS": 5, "NORV": 9, "WILD": 10}
        rev_by_sym = {"FIRE": ("yes", "rev +9% YoY"), "UPTR": ("yes", "rev +4% YoY"),
                      "LOWS": ("yes", "rev +2% YoY"), "NORV": ("no", "rev -3% YoY"),
                      "WILD": ("yes", "rev +30% YoY")}
        picks = [{"ticker": t, "catalyst": "news"} for t in ("UPTR", "LOWS", "NORV", "FIRE", "WILD")]
        self._patch(r_by_sym, score_by_sym, rev_by_sym)
        try:
            kept, dropped = ns.evaluate_candidates(picks)
        finally:
            self._unpatch()
        # FIRE (entry signal) ranks above UPTR (no signal) despite the lower health score
        self.assertEqual([c["sym"] for c in kept], ["FIRE", "UPTR"])
        self.assertTrue(any("LOWS" in d for d in dropped))
        self.assertTrue(any("NORV" in d for d in dropped))
        # erratic name is dropped with its reason, never shown as a numbered pick
        self.assertTrue(any("WILD" in d and "erratic" in d for d in dropped))

    def test_chart_verdict_ranks(self):
        base = dict(erratic=False, cup_fires=False, flat_fires=False, fires=False,
                    pulled_back=False, is_uptrend=False)
        self.assertEqual(ns.chart_verdict(None)[1], 0)
        self.assertEqual(ns.chart_verdict({**base, "erratic": True})[1], 0)
        self.assertEqual(ns.chart_verdict({**base, "fires": True})[1], 4)
        self.assertEqual(ns.chart_verdict({**base, "cup_fires": True, "cup_kind": "retest"})[1], 4)
        self.assertEqual(ns.chart_verdict({**base, "pulled_back": True})[1], 3)
        self.assertEqual(ns.chart_verdict({**base, "is_uptrend": True})[1], 2)
        self.assertEqual(ns.chart_verdict(base)[1], 1)


class TestMessage(unittest.TestCase):
    def test_full_message(self):
        results = [dict(sym="HOOD", catalyst="record volumes + job cuts", score=9,
                        verdict="🟢 full buy setup — ENTRY signal", rank=4,
                        rev_label="rev +30% YoY", price=118.14, golden="fresh")]
        msg = ns.build_message(results, ["XYZ (health 6/10)"], ["headline"], "pre-open")
        self.assertIn("HOOD", msg)
        self.assertIn("9/10", msg)
        self.assertIn("record volumes", msg)
        self.assertIn("golden cross", msg)
        self.assertIn("Dropped by the quality bar: XYZ (health 6/10)", msg)

    def test_empty_results_shows_headlines(self):
        msg = ns.build_message([], [], ["Fed holds rates", "Chips rally"], "post-open")
        self.assertIn("No news candidate cleared the quality bar", msg)
        self.assertIn("Fed holds rates", msg)


class TestWatchTargetAlerts(unittest.TestCase):
    def test_target_hit_and_not_hit(self):
        import json, tempfile, os as _os
        trades = {"watch": ["AAA", "BBB", "CCC"],
                  "watch_targets": {"AAA": 100.0, "BBB": 500.0}}   # CCC has no target
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(trades, f)
            path = f.name
        prices = {"AAA": 105.0, "BBB": 480.0}
        orig = (sb.download_chunk, sb.get_ohlcv)
        sb.download_chunk = lambda syms, retries=2: {"syms": syms}
        sb.get_ohlcv = lambda data, sym: ([1], [1], [prices[sym]], [1])
        try:
            import news_scan as ns
            lines = ns.check_watch_targets(trades_file=path)
        finally:
            sb.download_chunk, sb.get_ohlcv = orig
            _os.unlink(path)
        self.assertEqual(len(lines), 1)                    # only AAA is at/above target
        self.assertIn("AAA", lines[0])
        self.assertIn("105.00", lines[0])

    def test_no_targets_no_alerts(self):
        import json, tempfile, os as _os
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"watch": ["AAA"]}, f)
            path = f.name
        import news_scan as ns
        try:
            self.assertEqual(ns.check_watch_targets(trades_file=path), [])
        finally:
            _os.unlink(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
