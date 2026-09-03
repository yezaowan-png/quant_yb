import unittest

import numpy as np
import pandas as pd

from analysis.market_risk_labels import FUTURE_STATES, fold_risk_labels


class MarketRiskLabelsTest(unittest.TestCase):
    def _outcomes(self, rows=300):
        x = np.linspace(-1, 1, rows)
        return pd.DataFrame({
            "future_return_q10_5d": -0.05 + 0.03 * x,
            "future_median_return_5d": 0.01 + 0.02 * x,
            "future_stock_win_rate_5d": 0.5 + 0.2 * x,
            "future_large_decline_ratio_5d": 0.15 - 0.10 * x,
            "future_median_max_drawdown_5d": -0.04 + 0.02 * x,
            "future_recovery_ratio_5d": np.clip(0.5 + x, 0, 2),
            "future_negative_breadth_days_5d": np.where(x < 0, 4, 1),
        })

    def test_r1_r5_and_future_states_are_transparent_and_mutually_exclusive(self):
        train = self._outcomes()
        applied = fold_risk_labels(train, train.iloc[[0, 150, 299]], 5)
        self.assertTrue({"R1", "R2", "R3", "R4", "R5"} <= set(applied.columns))
        self.assertTrue(set(applied["future_risk_state"]).issubset(FUTURE_STATES))
        self.assertEqual(applied.iloc[0]["future_risk_state"], "persistent_tail_risk")

    def test_apply_values_cannot_change_train_thresholds(self):
        train = self._outcomes()
        first = fold_risk_labels(train, train.iloc[[10]], 5)
        extreme = train.iloc[[10]].copy()
        extreme["future_return_q10_5d"] = -99
        second = fold_risk_labels(train, extreme, 5)
        for column in ("q10_cut", "median_cut", "large_decline_cut", "max_drawdown_cut"):
            self.assertEqual(first.iloc[0][column], second.iloc[0][column])


if __name__ == "__main__":
    unittest.main()
