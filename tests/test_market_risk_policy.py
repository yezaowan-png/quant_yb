import unittest

import pandas as pd

from analysis.market_risk_policy import apply_policy_hysteresis, policy_payload


class MarketRiskPolicyTest(unittest.TestCase):
    def test_red_enters_immediately_and_releases_stepwise(self):
        states = pd.DataFrame({
            "trade_date": pd.bdate_range("2026-01-01", periods=12).strftime("%Y-%m-%d"),
            "current_state": ["normal", "panic", "normal", "normal", "normal", "normal", "normal", "normal", "normal", "normal", "normal", "normal"],
            "risk_score": [10, 90, 20, 20, 20, 20, 20, 20, 20, 20, 20, 20],
            "risk_flags": [[], ["large_decline_extreme"], [], [], [], [], [], [], [], [], [], []],
        })
        policies = apply_policy_hysteresis(states, release_days=3)
        self.assertEqual(policies.iloc[1]["risk_level"], "red")
        self.assertEqual(policies.iloc[4]["risk_level"], "orange")
        self.assertEqual(policies.iloc[7]["risk_level"], "yellow")
        self.assertEqual(policies.iloc[10]["risk_level"], "green")
        payload = policy_payload(policies.iloc[1])
        self.assertFalse(payload["allow_new_positions"])
        self.assertEqual(payload["position_cap"], 0.0)
        self.assertIn("missing_delisted_stocks", payload["data_quality_flags"])

    def test_cached_list_columns_are_deserialized(self):
        row = pd.Series({
            "trade_date": "2026-07-10", "current_state": "panic", "risk_level": "red",
            "risk_score": 90, "allow_new_positions": False, "position_cap": 0.0,
            "risk_flags": "['large_decline_extreme', 'new_low_extreme']",
            "release_conditions": '["A/D斜率连续转正"]',
        })
        payload = policy_payload(row)
        self.assertEqual(payload["risk_flags"], ["large_decline_extreme", "new_low_extreme"])
        self.assertEqual(payload["release_conditions"], ["A/D斜率连续转正"])


if __name__ == "__main__":
    unittest.main()
