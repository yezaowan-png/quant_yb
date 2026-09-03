import unittest

import pandas as pd

from analysis.index_forecast import (
    add_forecast_labels,
    build_index_forecast_indicators,
    build_rule_forecast,
    evaluate_forecast,
)
from analysis.index_forecast_diagnostics import build_diagnostics
from analysis.market_environment_labels import build_market_environment_targets


def _index_frame(days: int = 320) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=days, freq="B")
    close = [3000 + i * 2 + (i % 7) for i in range(days)]
    return pd.DataFrame(
        {
            "date": dates,
            "open": [v - 2 for v in close],
            "high": [v + 8 for v in close],
            "low": [v - 8 for v in close],
            "close": close,
            "volume": [100000 + i * 10 for i in range(days)],
            "amount": [200000 + i * 20 for i in range(days)],
        }
    )


class IndexForecastTest(unittest.TestCase):
    def test_build_features_and_rule_forecast(self):
        df = _index_frame()
        breadth = {}
        for date in pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d"):
            breadth[date] = {"up": 3000, "down": 1500, "flat": 100, "new_high": 200, "new_low": 50}

        indicators = build_index_forecast_indicators(df, "000001.SH", breadth_by_date=breadth)
        self.assertIn("macd_hist_delta_3", indicators.columns)
        self.assertIn("kdj_j_above_90", indicators.columns)
        self.assertIn("amount_ratio_20", indicators.columns)
        self.assertIn("ad_slope_5", indicators.columns)
        self.assertIn("nhnl_slope_5", indicators.columns)
        self.assertNotIn("label_5d", indicators.columns)

        features = add_forecast_labels(indicators, horizons=(5,))
        self.assertIn("label_5d", features.columns)

        predictions = build_rule_forecast(features, horizon=5)
        self.assertIn("market_score", predictions.columns)
        self.assertIn("p_bull", predictions.columns)
        self.assertIn("signal", predictions.columns)
        self.assertTrue((predictions["environment_model"] == "shared_environment_rule_v1").all())
        self.assertTrue(predictions["market_score"].between(0, 100).all())

        evaluation = evaluate_forecast(predictions, horizon=5)
        self.assertGreater(evaluation["sample_count"], 0)

    def test_cross_section_environment_is_primary_evaluation_target(self):
        df = _index_frame()
        dates = pd.to_datetime(df["date"])
        close = pd.Series(df["close"].to_numpy(), index=dates)
        matrix = pd.DataFrame(
            {
                "A.SZ": close.to_numpy() / 300.0,
                "B.SZ": close.to_numpy() / 150.0 + pd.Series(range(len(close))).to_numpy() * 0.002,
                "C.SH": 30.0 - pd.Series(range(len(close))).to_numpy() * 0.01,
            },
            index=dates,
        )
        indicators = build_index_forecast_indicators(df, "000001.SH")
        targets = build_market_environment_targets(
            df,
            matrix,
            horizons=(5,),
            percentile_min_periods=20,
        )
        features = add_forecast_labels(
            indicators,
            horizons=(5,),
            environment_targets=targets,
        )
        predictions = build_rule_forecast(features, horizon=5)
        corrupted_targets = features.copy()
        for column in corrupted_targets.columns:
            if column.startswith((
                "market_cap_index_return_", "equal_weight_return_", "median_stock_return_",
                "stock_win_rate_", "future_breadth_", "return_q10_", "median_max_drawdown_",
                "volatility_", "large_decline_ratio_", "opportunity_score_", "risk_score_",
                "environment_score_", "environment_label_", "index_breadth_gap_",
            )):
                corrupted_targets[column] = 999.0
        corrupted_predictions = build_rule_forecast(corrupted_targets, horizon=5)
        pd.testing.assert_series_equal(
            predictions["market_score"], corrupted_predictions["market_score"]
        )
        pd.testing.assert_series_equal(
            predictions["environment_signal"], corrupted_predictions["environment_signal"]
        )
        evaluation = evaluate_forecast(predictions, horizon=5)
        self.assertEqual(evaluation["target_type"], "cross_section_environment")
        self.assertIn("environment_evaluation", evaluation)
        diagnostics = build_diagnostics(
            features,
            predictions,
            horizon=5,
            symbol="000001.SH",
            label_mode="environment",
        )
        self.assertEqual(diagnostics["metrics"]["label_column"], "environment_label_5d")


if __name__ == "__main__":
    unittest.main()
