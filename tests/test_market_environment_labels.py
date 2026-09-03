import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.market_environment_labels import (
    _environment_label,
    _expanding_percentile,
    build_current_cross_section_features,
    build_market_environment_targets,
    environment_evaluation,
    load_strategy_daily_returns,
)


class MarketEnvironmentLabelsTest(unittest.TestCase):
    def setUp(self):
        self.dates = pd.date_range("2024-01-02", periods=120, freq="B")
        base = np.arange(120, dtype=float)
        self.closes = pd.DataFrame(
            {
                "A.SZ": 10.0 + base * 0.05,
                "B.SZ": 20.0 + base * 0.02,
                "C.SH": 30.0 - base * 0.03,
                "D.SH": 15.0 + np.sin(base / 4.0),
            },
            index=self.dates,
        )
        index_close = 3000.0 + base * 2.0
        self.index = pd.DataFrame({"date": self.dates, "close": index_close})

    def test_builds_all_required_horizons_and_scores(self):
        targets = build_market_environment_targets(
            self.index,
            self.closes,
            horizons=(1, 5, 10, 20),
            percentile_window=80,
            percentile_min_periods=10,
        )
        for horizon in (1, 5, 10, 20):
            suffix = f"_{horizon}d"
            for name in (
                "market_cap_index_return", "equal_weight_return", "median_stock_return",
                "stock_win_rate", "future_breadth", "return_q10", "median_max_drawdown",
                "volatility", "large_decline_ratio", "opportunity_score", "risk_score",
                "environment_score", "environment_label", "index_breadth_gap", "divergence_label",
            ):
                self.assertIn(f"{name}{suffix}", targets.columns)
            valid = targets[f"risk_score{suffix}"].dropna()
            self.assertTrue(valid.between(0, 100).all())
            expected = (
                0.70 * targets[f"opportunity_score{suffix}"]
                + 0.30 * (100.0 - targets[f"risk_score{suffix}"])
            )
            pd.testing.assert_series_equal(
                targets[f"environment_score{suffix}"], expected, check_names=False
            )
            self.assertTrue(targets[f"market_cap_index_return{suffix}"].tail(horizon).isna().all())

    def test_rolling_percentile_excludes_uncompleted_outcomes(self):
        values = pd.Series(np.linspace(-0.1, 0.1, 100))
        baseline = _expanding_percentile(values, horizon=5, window=80, min_periods=10)
        changed = values.copy()
        changed.iloc[76:80] = 99.0
        rescored = _expanding_percentile(changed, horizon=5, window=80, min_periods=10)
        self.assertEqual(baseline.iloc[80], rescored.iloc[80])

    def test_risk_veto_and_label_thresholds(self):
        self.assertEqual(_environment_label(90.0, 85.0), "conservative")
        self.assertEqual(_environment_label(70.0, 60.0), "positive")
        self.assertEqual(_environment_label(55.0, 60.0), "neutral")

    def test_current_features_include_required_market_structure(self):
        index_close = pd.Series(self.index["close"].to_numpy(), index=self.dates)
        features = build_current_cross_section_features(
            self.closes,
            index_close=index_close,
            large_cap_symbols={"A.SZ", "B.SZ"},
            small_cap_symbols={"C.SH", "D.SH"},
        )
        for column in (
            "stocks_above_ma20_ratio", "stocks_above_ma50_ratio", "stocks_above_ma200_ratio",
            "stock_up_ratio", "cross_section_volatility_20d", "market_large_decline_ratio_1d",
            "index_equal_weight_gap_1d", "large_small_relative_strength_1d",
        ):
            self.assertIn(column, features.columns)

    def test_environment_evaluation_and_strategy_filter(self):
        targets = build_market_environment_targets(
            self.index,
            self.closes,
            horizons=(5,),
            percentile_window=80,
            percentile_min_periods=10,
        )
        targets["environment_signal"] = targets["environment_label_5d"].fillna("neutral")
        strategy = pd.Series(0.001, index=self.dates)
        result = environment_evaluation(
            targets,
            horizon=5,
            predicted_col="environment_signal",
            strategy_returns={"demo": strategy},
        )
        self.assertGreater(result["sample_count"], 0)
        self.assertEqual(result["accuracy"], 1.0)
        self.assertEqual(len(result["strategy_filter_comparison"]), 1)
        self.assertIn("payoff_ratio", result["strategy_filter_comparison"][0]["before"])
        self.assertIn(
            "positive_to_conservative_drawdown_change",
            result["strategy_filter_comparison"][0],
        )

    def test_load_strategy_daily_returns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "000001.SZ_sma_cross_equity.csv"
            pd.DataFrame(
                {"dates": self.dates[:3], "equity": [100.0, 101.0, 102.01]}
            ).to_csv(path, index=False)
            result = load_strategy_daily_returns(tmp)
            self.assertIn("sma_cross", result)
            self.assertAlmostEqual(float(result["sma_cross"].dropna().iloc[0]), 0.01)


if __name__ == "__main__":
    unittest.main()
