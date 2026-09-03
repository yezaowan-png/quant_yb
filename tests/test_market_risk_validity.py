import unittest

import numpy as np
import pandas as pd

from analysis.market_risk_validity import (
    build_risk_episodes,
    frozen_simple_rule_alerts,
    generate_block_random_episodes,
    measurement_validity,
    predictive_validity,
    strategy_decision_utility,
)


class MarketRiskValidityTest(unittest.TestCase):
    def test_episode_ends_at_green_and_merges_cooldown_reentry(self):
        levels = ["green"] * 35
        levels[2:5] = ["orange", "red", "yellow"]
        levels[5] = "green"
        levels[10:13] = ["orange", "yellow", "yellow"]
        levels[13] = "green"
        levels[27:30] = ["red", "yellow", "yellow"]
        levels[30] = "green"
        policies = pd.DataFrame({
            "trade_date": pd.bdate_range("2026-01-01", periods=len(levels)).strftime("%Y-%m-%d"),
            "risk_level": levels,
            "position_cap": [1.0 if item == "green" else 0.3 for item in levels],
        })
        episodes = build_risk_episodes(policies, cooldown=10)
        self.assertEqual(len(episodes), 2)
        self.assertEqual(episodes.iloc[0]["start_position"], 2)
        self.assertEqual(episodes.iloc[0]["end_position"], 13)
        self.assertEqual(episodes.iloc[1]["end_position"], 30)

    def test_block_random_preserves_count_year_and_duration(self):
        dates = pd.Series(pd.bdate_range("2020-01-01", periods=520).strftime("%Y-%m-%d"))
        policies = pd.DataFrame({"trade_date": dates, "risk_level": "green", "position_cap": 1.0})
        for start, end in ((40, 48), (130, 142), (300, 310), (420, 435)):
            policies.loc[start : end - 1, "risk_level"] = "orange"
            policies.loc[start : end - 1, "position_cap"] = 0.3
        episodes = build_risk_episodes(policies, cooldown=10)
        random_sets = generate_block_random_episodes(dates, episodes, simulations=1000, seed=7)
        expected_durations = sorted(episodes["duration_days"].tolist())
        expected_years = episodes["start_year"].value_counts().sort_index().to_dict()
        self.assertEqual(len(random_sets), 1000)
        for randomized in random_sets[:20]:
            self.assertEqual(len(randomized), len(episodes))
            self.assertEqual(sorted(randomized["duration_days"].tolist()), expected_durations)
            self.assertEqual(randomized["start_year"].value_counts().sort_index().to_dict(), expected_years)

    def test_measurement_and_predictive_monotonicity_are_separate(self):
        dates = pd.bdate_range("2025-01-01", periods=40).strftime("%Y-%m-%d")
        levels = np.repeat(["green", "yellow", "orange", "red"], 10)
        order = pd.Series(levels).map({"green": 0, "yellow": 1, "orange": 2, "red": 3}).to_numpy()
        features = pd.DataFrame({
            "trade_date": dates,
            "current_large_decline_ratio": order,
            "cross_section_dispersion": order,
            "realized_volatility_5d": order,
            "normalized_ad": -order,
            "normalized_nhnl": -order,
            "pct_above_ma20": -order,
            "new_low_ratio": order,
            "limit_down_ratio": order,
        })
        policies = pd.DataFrame({"trade_date": dates, "risk_level": levels})
        _, measurement_checks = measurement_validity(features, policies)
        self.assertTrue(measurement_checks["measurement_direction_passed"].all())
        outcomes = pd.DataFrame({"trade_date": dates})
        for horizon in (1, 5, 10, 20):
            outcomes[f"future_median_return_{horizon}d"] = -order
            outcomes[f"future_equal_weight_return_{horizon}d"] = -order
            outcomes[f"future_return_q10_{horizon}d"] = -order
            outcomes[f"future_median_max_drawdown_{horizon}d"] = -order
            outcomes[f"future_large_decline_ratio_{horizon}d"] = order
            outcomes[f"future_stock_win_rate_{horizon}d"] = -order
        _, predictive_checks = predictive_validity(outcomes, policies)
        self.assertTrue(predictive_checks["predictive_direction_passed"].all())

    def test_simple_rule_thresholds_use_prior_history(self):
        rows = 320
        dates = pd.bdate_range("2020-01-01", periods=rows)
        base = np.linspace(-1, 1, rows)
        features = pd.DataFrame({
            "trade_date": dates.strftime("%Y-%m-%d"),
            "normalized_ad": base,
            "normalized_nhnl": base,
            "current_large_decline_ratio": base,
            "realized_volatility_5d": base,
            "index_return_5d": base,
        })
        index = pd.DataFrame({"date": dates, "close": 3000 + np.arange(rows)})
        first = frozen_simple_rule_alerts(features, index)
        changed = features.copy()
        changed.loc[319, "normalized_ad"] = -999
        second = frozen_simple_rule_alerts(changed, index)
        pd.testing.assert_series_equal(
            first.loc[:318, "normalized_ad_p10"], second.loc[:318, "normalized_ad_p10"]
        )
        self.assertFalse(first.iloc[:252, 1:].to_numpy().any())

    def test_random_strategy_exposure_is_exactly_matched(self):
        dates = pd.Series(pd.bdate_range("2025-01-01", periods=20).strftime("%Y-%m-%d"))
        exposure = pd.Series([1.0, 0.3] * 10, index=dates)
        returns = {"demo": pd.Series(0.001, index=pd.to_datetime(dates))}
        table = strategy_decision_utility(
            dates, exposure, returns, target_average_exposure={"demo": 0.75}
        )
        self.assertAlmostEqual(float(table.iloc[0]["average_exposure"]), 0.75, places=12)
        self.assertNotEqual(float(table.iloc[0]["exposure_matching_adjustment"]), 0.0)


if __name__ == "__main__":
    unittest.main()
