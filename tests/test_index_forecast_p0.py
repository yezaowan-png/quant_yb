import unittest
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.index_forecast_p0 import (
    available_p0_features,
    build_breadth_level_slope_events,
    build_purged_walk_forward_baseline,
    build_purged_walk_forward_research,
    build_research_gate_audit,
    is_target_or_leakage_column,
)
from analysis.index_forecast import forecast_paths
from analysis.index_forecast_diagnostics import _ensure_forecast_files


class IndexForecastP0Test(unittest.TestCase):
    def _frame(self, rows=620):
        rng = np.random.default_rng(7)
        frame = pd.DataFrame({"trade_date": pd.bdate_range("2020-01-01", periods=rows).strftime("%Y-%m-%d")})
        feature_names = [
            "ret_5d", "ret_20d", "dist_ma20", "dist_ma60", "ma20_slope_5",
            "macd_hist_norm", "normalized_ad", "ad_line_slope_5", "normalized_nhnl",
            "nhnl_line_slope_5", "stocks_above_ma20_ratio", "stocks_above_ma200_ratio",
        ]
        latent = rng.normal(size=rows)
        for i, name in enumerate(feature_names):
            frame[name] = latent * (0.15 if i < 4 else 0.03) + rng.normal(size=rows)
        future = 0.01 * latent + rng.normal(scale=0.01, size=rows)
        frame["median_stock_return_score_5d"] = pd.Series(future).rank(pct=True) * 100
        frame["stock_win_rate_score_5d"] = frame["median_stock_return_score_5d"]
        frame["downside_quantile_score_5d"] = pd.Series(-future).rank(pct=True) * 100
        frame["max_drawdown_score_5d"] = frame["downside_quantile_score_5d"]
        frame["large_decline_ratio_score_5d"] = frame["downside_quantile_score_5d"]
        frame["equal_weight_return_5d"] = future
        frame["median_stock_return_5d"] = future
        frame["stock_win_rate_5d"] = (future > 0).astype(float)
        frame["return_q10_5d"] = future - 0.02
        frame["median_max_drawdown_5d"] = np.minimum(future, 0) - 0.01
        frame["large_decline_ratio_5d"] = np.clip(-future * 10, 0, 1)
        return frame

    def test_target_derived_columns_are_excluded(self):
        frame = self._frame()
        self.assertTrue(is_target_or_leakage_column("opportunity_score_5d"))
        self.assertTrue(is_target_or_leakage_column("median_stock_return_score_5d"))
        self.assertNotIn("median_stock_return_score_5d", available_p0_features(frame))

    def test_event_and_walk_forward_outputs(self):
        frame = self._frame()
        events = build_breadth_level_slope_events(frame, 5)
        folds, predictions, features = build_purged_walk_forward_baseline(frame, 5)
        self.assertFalse(events.empty)
        self.assertFalse(folds.empty)
        self.assertFalse(predictions.empty)
        self.assertGreaterEqual(len(features), 5)
        self.assertTrue((folds["purge_days"] == 5).all())
        self.assertTrue((pd.to_datetime(folds["train_end"]) < pd.to_datetime(folds["test_start"])).all())

    def test_short_existing_prediction_triggers_rebuild(self):
        with tempfile.TemporaryDirectory() as directory:
            config = {"output": {"statistics_dir": directory}}
            paths = forecast_paths(config, "000001.SH", 5)
            paths.root.mkdir(parents=True)
            pd.DataFrame({"trade_date": ["2024-01-02"]}).to_csv(paths.features, index=False)
            pd.DataFrame({"trade_date": ["2024-01-02"]}).to_csv(paths.predictions, index=False)
            calls = []

            def rebuild():
                calls.append(True)

            _ensure_forecast_files(config, "000001.SH", 5, "20110101", "20260710", False, rebuild)
            self.assertEqual(calls, [True])

    def test_strict_research_has_validation_purge_embargo_and_transparent_labels(self):
        result = build_purged_walk_forward_research(self._frame(760), 5)
        folds = result["folds"]
        self.assertFalse(folds.empty)
        self.assertTrue((folds["purge_days"] == 5).all())
        self.assertTrue((folds["embargo_days"] == 5).all())
        self.assertTrue((pd.to_datetime(folds["train_end"]) < pd.to_datetime(folds["validation_start"])).all())
        self.assertTrue((pd.to_datetime(folds["validation_end"]) < pd.to_datetime(folds["test_start"])).all())
        self.assertIn("label_a_median", result["predictions"].columns)
        self.assertFalse(result["baselines"].empty)
        self.assertFalse(result["coefficients"].empty)

    def test_test_window_cannot_change_fitted_parameters(self):
        base = self._frame(760)
        changed = base.copy()
        test_slice = slice(325, 388)
        changed.loc[test_slice, "ret_5d"] = 999.0
        changed.loc[test_slice, "median_stock_return_5d"] = -9.0
        changed.loc[test_slice, "stock_win_rate_5d"] = 0.0
        original = build_purged_walk_forward_research(base, 5)
        modified = build_purged_walk_forward_research(changed, 5)
        original_coefficients = original["coefficients"].query("fold == 1").reset_index(drop=True)
        modified_coefficients = modified["coefficients"].query("fold == 1").reset_index(drop=True)
        pd.testing.assert_frame_equal(original_coefficients, modified_coefficients)
        fit_columns = ["opportunity_l2", "risk_l2", "opportunity_threshold", "risk_threshold"]
        pd.testing.assert_series_equal(
            original["folds"].iloc[0][fit_columns], modified["folds"].iloc[0][fit_columns], check_names=False
        )

    def test_missing_evidence_never_authorizes_p2_p3(self):
        audit = build_research_gate_audit(pd.DataFrame(), pd.DataFrame())
        decision = audit[audit["gate"] == "p2_p3_authorized"].iloc[0]
        self.assertFalse(bool(decision["passed"]))
        self.assertEqual(decision["decision"], "stop_at_p1_keep_formal_signal_unchanged")


if __name__ == "__main__":
    unittest.main()
