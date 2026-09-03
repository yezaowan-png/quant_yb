import unittest

import pandas as pd

from analysis.market_risk_diagnostics import evaluate_strategy_risk_gate, experiment_gate
from analysis.market_risk_model import RiskExperiment


class MarketRiskGateTest(unittest.TestCase):
    def _summary(self, **overrides):
        values = {
            "roc_auc": 0.58,
            "pr_auc": 0.25,
            "risk_event_base_rate": 0.20,
            "high_minus_low_q10": -0.02,
            "high_minus_low_max_drawdown": -0.03,
            "high_minus_low_large_decline_ratio": 0.10,
            "fold_win_rate_vs_frozen_large_decline": 0.60,
            "brier_skill": 0.01,
            "ece": 0.09,
        }
        values.update(overrides)
        return pd.DataFrame([values])

    def test_continue_requires_all_research_gates(self):
        gate = experiment_gate(self._summary())
        self.assertEqual(gate.iloc[-1]["decision"], "continue_risk_gate_research")
        failed = experiment_gate(self._summary(pr_auc=0.10))
        self.assertEqual(failed.iloc[-1]["decision"], "stop_future_risk_prediction_use_state_monitor_only")

    def test_eligible_uses_stricter_probability_gates(self):
        gate = experiment_gate(self._summary(
            roc_auc=0.61, fold_win_rate_vs_frozen_large_decline=0.75,
            brier_skill=0.05, ece=0.08,
        ))
        self.assertTrue(bool(gate.set_index("gate").loc["model_eligible_candidate", "passed"]))
        self.assertEqual(gate.iloc[-1]["decision"], "continue_risk_gate_research")

    def test_random_policy_matches_gate_exposure(self):
        dates = pd.bdate_range("2026-01-01", periods=20).strftime("%Y-%m-%d")
        result = {
            "experiment": RiskExperiment("test", 5, "R2"),
            "predictions": pd.DataFrame({
                "trade_date": dates,
                "risk_score": [20, 40, 70, 90] * 5,
                "alert": [False, False, True, True] * 5,
            }),
        }
        returns = {"demo": pd.Series([0.001] * 20, index=pd.to_datetime(dates))}
        table = evaluate_strategy_risk_gate(result, returns)
        selected = table.set_index("policy")
        self.assertEqual(
            selected.loc["D_extreme_risk_gate", "average_exposure"],
            selected.loc["E_random_matched_exposure", "average_exposure"],
        )


if __name__ == "__main__":
    unittest.main()
