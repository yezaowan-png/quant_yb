import unittest

import numpy as np
import pandas as pd

from analysis.market_risk_features import MINIMAL_RISK_FEATURES
from analysis.market_risk_model import RiskExperiment, run_risk_experiment


class MarketRiskWalkForwardTest(unittest.TestCase):
    def _frame(self, rows=780):
        rng = np.random.default_rng(19)
        latent = rng.normal(size=rows)
        frame = pd.DataFrame({"trade_date": pd.bdate_range("2018-01-01", periods=rows).strftime("%Y-%m-%d")})
        for i, feature in enumerate(MINIMAL_RISK_FEATURES):
            frame[feature] = latent * (0.4 if i < 4 else 0.1) + rng.normal(size=rows)
        tail = -0.04 - 0.015 * latent + rng.normal(scale=0.006, size=rows)
        frame["future_return_q10_5d"] = tail
        frame["future_equal_weight_return_5d"] = 0.008 - 0.012 * latent + rng.normal(scale=0.004, size=rows)
        frame["future_median_return_5d"] = 0.005 - 0.01 * latent + rng.normal(scale=0.004, size=rows)
        frame["future_stock_win_rate_5d"] = np.clip(0.52 - 0.12 * latent, 0, 1)
        frame["future_large_decline_ratio_5d"] = np.clip(0.10 + 0.08 * latent, 0, 1)
        frame["future_median_max_drawdown_5d"] = -0.025 - 0.012 * latent
        frame["future_terminal_drawdown_5d"] = -0.01 - 0.01 * latent
        frame["future_recovery_ratio_5d"] = np.clip(0.8 - 0.3 * latent, 0, 2)
        frame["future_negative_breadth_days_5d"] = np.clip(np.round(2.5 + latent), 0, 5)
        return frame

    def test_strict_fold_boundaries_and_probability_semantics(self):
        natural = run_risk_experiment(
            self._frame(), RiskExperiment("test", 5, "R2", class_weight="none"), initial_train=252
        )
        folds = natural["folds"]
        self.assertFalse(folds.empty)
        self.assertTrue((folds["purge_days"] == 5).all())
        self.assertTrue((folds["embargo_days"] == 5).all())
        self.assertTrue((pd.to_datetime(folds["train_end"]) < pd.to_datetime(folds["validation_start"])).all())
        self.assertTrue(natural["predictions"]["risk_probability"].notna().all())
        balanced = run_risk_experiment(
            self._frame(), RiskExperiment("balanced", 5, "R2", class_weight="balanced"), initial_train=252
        )
        self.assertTrue(balanced["predictions"]["risk_probability"].isna().all())
        self.assertTrue(balanced["predictions"]["risk_score"].notna().all())


if __name__ == "__main__":
    unittest.main()
