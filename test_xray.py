"""Reliability tests for the X-ray score (xray.py).

These pin the scoring logic so it can't silently regress. They run fully offline — every
case feeds synthetic fundamentals straight into xray.evaluate(), no network/yfinance calls.

Run:  python -m unittest test_xray -v   (or)   python test_xray.py
"""

import copy
import unittest

import xray

# A complete, healthy, fairly-priced large-cap. Individual tests override fields from this.
STRONG = {
    "sector": "Technology", "revenueGrowth": 0.20, "grossMargins": 0.60, "profitMargins": 0.22,
    "trailingPE": 22, "trailingPegRatio": 1.3, "priceToSalesTrailing12Months": 6,
    "operatingCashflow": 5e9, "netIncomeToCommon": 4e9, "freeCashflow": 3e9,
    "totalCash": 8e9, "totalDebt": 2e9, "debtToEquity": 30, "returnOnEquity": 0.30,
    "earningsGrowth": 0.20, "targetMeanPrice": 130, "currentPrice": 100, "dividendYield": 0.01,
    "recommendationKey": "buy", "numberOfAnalystOpinions": 25, "shortPercentOfFloat": 0.02,
}


def mk(overrides=None, buyback=True, insider_net=1000, earn_beats=(4, 4)):
    info = copy.deepcopy(STRONG)
    if overrides is not None:
        info = {} if overrides == "EMPTY" else {**info, **overrides}
    return {"info": info, "buyback": buyback, "insider_net": insider_net, "earn_beats": earn_beats}


def score(overrides=None, **kw):
    return xray.evaluate(mk(overrides, **kw))


class TestScore(unittest.TestCase):
    def test_strong_cheap_is_ten(self):
        r = score()
        self.assertEqual(r["score"], 10)
        self.assertEqual(r["verdict"], "מצוין")
        self.assertEqual(r["confidence"], "ok")

    def test_great_but_expensive_is_nine_not_ten(self):
        # superb business (huge FCF covers the buyback-driven debt), rich multiple -> 9, flagged pricey
        r = score({"trailingPE": 36, "trailingPegRatio": 2.4, "priceToSalesTrailing12Months": 9,
                   "totalCash": 6.2e10, "totalDebt": 1.0e11, "debtToEquity": 150, "returnOnEquity": 1.5,
                   "operatingCashflow": 1.2e11, "netIncomeToCommon": 1.0e11, "freeCashflow": 1.0e11})
        self.assertEqual(r["score"], 9)
        self.assertIn("מתומחרת ביוקר", r["danger"])

    def test_cash_burner_is_capped_low(self):
        r = score({"profitMargins": -0.5, "netIncomeToCommon": -2e8, "freeCashflow": -1.5e8,
                   "operatingCashflow": -1.4e8})
        self.assertLessEqual(r["score"], 4)
        self.assertNotEqual(r["verdict"], "מצוין")
        self.assertTrue(any("שורפת" in c for c in r["caps"]))

    def test_speculative_price_to_sales_capped(self):
        r = score({"priceToSalesTrailing12Months": 330})
        self.assertLessEqual(r["score"], 6)

    def test_sparse_data_low_confidence_and_capped(self):
        r = xray.evaluate({"info": {"revenueGrowth": 0.2, "grossMargins": 0.5},
                           "buyback": None, "insider_net": None, "earn_beats": None})
        self.assertIn(r["confidence"], ("low", "very_low"))
        self.assertLessEqual(r["score"], 6)

    def test_empty_info_is_not_ok(self):
        r = xray.evaluate({"info": {}, "buyback": None, "insider_net": None, "earn_beats": None})
        self.assertFalse(r.get("known"))
        self.assertEqual(r["score"], 0)

    def test_score_is_deterministic(self):
        self.assertEqual(score({"trailingPE": 36})["score"], score({"trailingPE": 36})["score"])

    def test_score_in_range(self):
        for ov in (None, {"trailingPE": 36}, {"profitMargins": -0.5, "freeCashflow": -1e8,
                   "netIncomeToCommon": -1e8}, {"priceToSalesTrailing12Months": 330}):
            self.assertTrue(0 <= score(ov)["score"] <= 10)


class TestFlags(unittest.TestCase):
    def _flag(self, r, label_part):
        return next(it["flag"] for it in r["items"] if label_part in it["label"])

    def test_short_interest_flag(self):
        self.assertEqual(self._flag(score({"shortPercentOfFloat": 0.24}), "שורט"), "red")
        self.assertEqual(self._flag(score({"shortPercentOfFloat": 0.02}), "שורט"), "green")

    def test_analyst_flag(self):
        self.assertEqual(self._flag(score({"recommendationKey": "strong_buy"}), "קונצנזוס"), "green")
        self.assertEqual(self._flag(score({"recommendationKey": "sell", "targetMeanPrice": 80,
                                           "currentPrice": 100}), "קונצנזוס"), "red")

    def test_earnings_beats_flag(self):
        self.assertEqual(self._flag(score(earn_beats=(4, 4)), "Beats"), "green")
        self.assertEqual(self._flag(score(earn_beats=(0, 4)), "Beats"), "red")

    def test_unprofitable_flag_red(self):
        self.assertEqual(self._flag(score({"profitMargins": -0.3}), "רווח נקי"), "red")

    def test_cashflow_aware_debt_not_falsely_red(self):
        # more debt than cash, but huge FCF easily covers it -> must be green (the AAPL case)
        r = score({"totalCash": 6e10, "totalDebt": 1e11, "debtToEquity": 150, "freeCashflow": 1e11})
        self.assertEqual(self._flag(r, "חוב"), "green")


class TestNormalization(unittest.TestCase):
    def test_margin_percentage_form_is_converted(self):
        info = {"grossMargins": 46, "profitMargins": 25, "returnOnEquity": 150, "revenueGrowth": 17}
        xray._normalize_units(info)
        self.assertAlmostEqual(info["grossMargins"], 0.46)
        self.assertAlmostEqual(info["profitMargins"], 0.25)
        self.assertAlmostEqual(info["returnOnEquity"], 1.5)   # 150% stays a 1.5 fraction
        self.assertAlmostEqual(info["revenueGrowth"], 0.17)

    def test_fraction_form_is_left_alone(self):
        info = {"grossMargins": 0.46, "returnOnEquity": 1.5, "revenueGrowth": 1.61}
        xray._normalize_units(info)
        self.assertAlmostEqual(info["grossMargins"], 0.46)
        self.assertAlmostEqual(info["returnOnEquity"], 1.5)   # AAPL-style 150% ROE untouched
        self.assertAlmostEqual(info["revenueGrowth"], 1.61)   # 161% growth untouched

    def test_score_is_scale_invariant(self):
        frac = score()["score"]
        pct = score({"grossMargins": 60, "profitMargins": 22, "returnOnEquity": 30})["score"]
        self.assertEqual(frac, pct)


if __name__ == "__main__":
    unittest.main(verbosity=2)
