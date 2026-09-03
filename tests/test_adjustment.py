import unittest

import pandas as pd

from data.adjustment import apply_price_adjustment, is_adjusted_mode, overlap_price_mismatch


class AdjustmentTest(unittest.TestCase):
    def test_is_adjusted_mode(self):
        self.assertFalse(is_adjusted_mode(None))
        self.assertFalse(is_adjusted_mode(""))
        self.assertFalse(is_adjusted_mode("raw"))
        self.assertFalse(is_adjusted_mode("none"))
        self.assertTrue(is_adjusted_mode("qfq"))
        self.assertTrue(is_adjusted_mode("hfq"))

    def test_qfq_uses_first_factor_as_base(self):
        raw = pd.DataFrame(
            [
                {
                    "trade_date": "20260103",
                    "open": 10.0,
                    "high": 12.0,
                    "low": 9.0,
                    "close": 11.0,
                    "pre_close": 10.0,
                },
                {
                    "trade_date": "20260102",
                    "open": 8.0,
                    "high": 9.0,
                    "low": 7.0,
                    "close": 8.0,
                    "pre_close": 7.5,
                },
            ]
        )
        factors = pd.DataFrame(
            [
                {"trade_date": "20260103", "adj_factor": 2.0},
                {"trade_date": "20260102", "adj_factor": 1.0},
            ]
        )

        adjusted = apply_price_adjustment(raw, factors, "qfq")

        self.assertEqual(adjusted.loc[0, "close"], 11.0)
        self.assertEqual(adjusted.loc[1, "close"], 4.0)
        self.assertEqual(adjusted.loc[1, "pre_close"], 3.75)
        self.assertEqual(adjusted.loc[1, "change"], 0.25)

    def test_hfq_multiplies_by_factor(self):
        raw = pd.DataFrame(
            [{"trade_date": "20260102", "open": 8.0, "high": 9.0, "low": 7.0, "close": 8.0}]
        )
        factors = pd.DataFrame([{"trade_date": "20260102", "adj_factor": 1.5}])

        adjusted = apply_price_adjustment(raw, factors, "hfq")

        self.assertEqual(adjusted.loc[0, "close"], 12.0)

    def test_missing_factors_returns_empty_raw_shape(self):
        raw = pd.DataFrame([{"trade_date": "20260102", "close": 8.0}])

        adjusted = apply_price_adjustment(raw, pd.DataFrame(), "qfq")

        self.assertTrue(adjusted.empty)

    def test_overlap_price_mismatch_uses_tolerance(self):
        existing = pd.DataFrame(
            [{"date": pd.Timestamp("2026-01-02"), "open": 10.0, "high": 11, "low": 9, "close": 10}]
        )
        same = pd.DataFrame(
            [{"date": pd.Timestamp("2026-01-02"), "open": 10.005, "high": 11, "low": 9, "close": 10}]
        )
        changed = pd.DataFrame(
            [{"date": pd.Timestamp("2026-01-02"), "open": 10.02, "high": 11, "low": 9, "close": 10}]
        )

        self.assertFalse(overlap_price_mismatch(existing, same))
        self.assertTrue(overlap_price_mismatch(existing, changed))


if __name__ == "__main__":
    unittest.main()
