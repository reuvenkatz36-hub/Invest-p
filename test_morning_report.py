"""Tests for the 8 AM morning report orchestrator (offline, everything monkeypatched)."""

import os
import unittest

os.environ.setdefault("TELEGRAM_TOKEN", "x")
os.environ.setdefault("TELEGRAM_CHAT_ID", "1")

import morning_report as mr


class TestMorningReport(unittest.TestCase):
    def test_sections_sent_in_order_with_standalone_targets(self):
        sent = []
        orig = (mr.sb.send_telegram_message, mr.sb.send_long, mr.sb.main,
                mr.ns.check_watch_targets, mr.ns.fetch_market_headlines,
                mr.ns.pick_candidates, mr.ns.evaluate_candidates, mr.ns.build_message,
                mr.cb.load_json, mr.cb.handle_watchlist)
        mr.sb.send_telegram_message = lambda m: sent.append(("single", m)) or True
        mr.sb.send_long = lambda m: sent.append(("long", m)) or 1
        mr.sb.main = lambda: sent.append(("long", "SCAN"))
        mr.ns.check_watch_targets = lambda: ["🎯 LII reached your goal price! $700.10 ≥ your $700 target",
                                             "🎯 MAS reached your goal price! $91.00 ≥ your $90 target"]
        mr.ns.fetch_market_headlines = lambda: ["headline"]
        mr.ns.pick_candidates = lambda h: []
        mr.ns.evaluate_candidates = lambda p: ([], [])
        mr.ns.build_message = lambda r, d, h, s: "NEWS"
        mr.cb.load_json = lambda p, default: {"watch": ["LII"], "open": [], "closed": []}
        mr.cb.handle_watchlist = lambda t: "WATCHLIST PAGE"
        try:
            mr.main()
        finally:
            (mr.sb.send_telegram_message, mr.sb.send_long, mr.sb.main,
             mr.ns.check_watch_targets, mr.ns.fetch_market_headlines,
             mr.ns.pick_candidates, mr.ns.evaluate_candidates, mr.ns.build_message,
             mr.cb.load_json, mr.cb.handle_watchlist) = orig

        # two DEDICATED goal messages first, each standalone
        self.assertEqual(sent[0][0], "single")
        self.assertIn("LII reached your goal price", sent[0][1])
        self.assertEqual(sent[1][0], "single")
        self.assertIn("MAS", sent[1][1])
        # then watchlist page, news, scan — in that order
        self.assertIn("WATCHLIST PAGE", sent[2][1])
        self.assertEqual(sent[3][1], "NEWS")
        self.assertEqual(sent[4][1], "SCAN")

    def test_empty_watchlist_skips_page(self):
        sent = []
        orig = (mr.sb.send_telegram_message, mr.sb.send_long, mr.sb.main,
                mr.ns.check_watch_targets, mr.ns.fetch_market_headlines,
                mr.ns.pick_candidates, mr.ns.evaluate_candidates, mr.ns.build_message,
                mr.cb.load_json)
        mr.sb.send_telegram_message = lambda m: sent.append(m) or True
        mr.sb.send_long = lambda m: sent.append(m) or 1
        mr.sb.main = lambda: None
        mr.ns.check_watch_targets = lambda: []
        mr.ns.fetch_market_headlines = lambda: []
        mr.ns.pick_candidates = lambda h: []
        mr.ns.evaluate_candidates = lambda p: ([], [])
        mr.ns.build_message = lambda r, d, h, s: "NEWS"
        mr.cb.load_json = lambda p, default: {"watch": [], "open": [], "closed": []}
        try:
            mr.main()
        finally:
            (mr.sb.send_telegram_message, mr.sb.send_long, mr.sb.main,
             mr.ns.check_watch_targets, mr.ns.fetch_market_headlines,
             mr.ns.pick_candidates, mr.ns.evaluate_candidates, mr.ns.build_message,
             mr.cb.load_json) = orig
        self.assertTrue(all("watchlist" not in str(m).lower() for m in sent))


if __name__ == "__main__":
    unittest.main(verbosity=2)
