from __future__ import annotations

from pathlib import Path
import ast
import unittest

import numpy as np
import pandas as pd

from analysis.index_lift_structure import build_index_lift_structure


def _fixture() -> dict[str, object]:
    dates = pd.bdate_range("2026-01-02", periods=150)
    symbols = [f"00000{i}.SZ" for i in range(1, 9)]
    rng = np.random.default_rng(42)
    returns = pd.DataFrame(
        rng.normal(0.0005, 0.012, size=(len(dates), len(symbols))),
        index=dates,
        columns=symbols,
    )
    returns.iloc[-1] = [0.050, 0.035, -0.020, -0.015, 0.010, -0.030, 0.080, -0.010]
    close = 10.0 * (1.0 + returns).cumprod()
    base_amount = np.tile(1_000_000.0 * (1.0 + np.arange(len(symbols)) / 10.0), (len(dates), 1))
    amount = pd.DataFrame(base_amount, index=dates, columns=symbols)
    amount = amount.mul(1.0 + 0.05 * np.sin(np.arange(len(dates)) / 9.0), axis=0)
    amount.iloc[-1] = [700_000, 900_000, 3_800_000, 3_500_000, 1_000_000, 4_000_000, 800_000, 3_200_000]
    weights = pd.Series(
        [0.30, 0.25, 0.15, 0.10, 0.08, 0.05, 0.04, 0.03],
        index=symbols,
    )
    index_returns = (returns * weights).sum(axis=1)
    index_close = 3000.0 * (1.0 + index_returns).cumprod()
    index_frame = pd.DataFrame(
        {
            "date": dates,
            "close": index_close.to_numpy(),
            "amount": 1_000_000_000.0,
        }
    )
    member_rows = [
        {"trade_date": dates[0] - pd.tseries.offsets.BDay(1), "con_code": symbol, "weight": weight * 100.0}
        for symbol, weight in weights.items()
    ]
    member_rows.extend(
        [
            {"trade_date": dates[-1], "con_code": symbols[-1], "weight": 95.0},
            {"trade_date": dates[-1], "con_code": symbols[0], "weight": 5.0},
        ]
    )
    metadata = pd.DataFrame(
        {
            "ts_code": symbols,
            "name": [f"测试{i}" for i in range(1, 9)],
            "industry": ["行业甲", "行业甲", "行业乙", "行业乙", "行业丙", "行业丙", "行业丁", "行业丁"],
            "market": ["主板"] * len(symbols),
            "exchange": ["SSE"] * len(symbols),
            "float_mv": [900, 800, 700, 600, 500, 400, 300, 200],
        }
    )
    return {
        "dates": dates,
        "symbols": symbols,
        "close": close,
        "amount": amount,
        "metadata": metadata,
        "index_frames": {"000300.SH": index_frame, "000001.SH": index_frame.copy()},
        "index_member_frames": {"000300.SH": pd.DataFrame(member_rows)},
    }


class IndexLiftStructureTest(unittest.TestCase):
    def setUp(self) -> None:
        data = _fixture()
        self.data = data
        self.result = build_index_lift_structure(
            primary_symbol="000300.SH",
            close=data["close"],
            amount=data["amount"],
            metadata=data["metadata"],
            index_frames=data["index_frames"],
            index_member_frames=data["index_member_frames"],
            as_of=data["dates"][-1],
            config={"history_window": 60, "min_history": 20, "display": {"recent_days": 30}},
        )

    def test_01_outputs_required_top_level_shape(self):
        self.assertEqual(self.result["symbol"], "000300.SH")
        self.assertIn("returns", self.result)
        self.assertIn("contribution_concentration", self.result)
        self.assertIn("turnover_confirmation", self.result)
        self.assertIn("heavy_turnover_pressure", self.result)
        self.assertIn("weight_turnover_groups", self.result)
        self.assertIn("scores", self.result)
        self.assertIn("by_symbol", self.result)

    def test_02_uses_previous_weight_snapshot_not_same_day(self):
        self.assertLess(str(self.result["member_snapshot_date"]), str(self.result["trade_date"]))
        first = self.result["top_positive_contributors"][0]
        self.assertEqual(first["symbol"], "000001.SZ")
        self.assertLess(first["index_weight"], 0.31)

    def test_03_calculates_return_gaps_and_reconciles_official_index(self):
        returns = self.result["returns"]
        self.assertIsNotNone(returns["index_return"])
        self.assertIsNotNone(returns["equal_weight_return"])
        self.assertAlmostEqual(abs(returns["reconciliation_error"]), 0.0, places=10)

    def test_04_positive_contribution_concentration_metrics_exist(self):
        concentration = self.result["contribution_concentration"]
        self.assertGreater(concentration["top_3_positive_contribution_share"], 0)
        self.assertGreater(concentration["top_10_absolute_contribution_share"], 0)
        self.assertIsNotNone(concentration["top_10_signed_index_contribution"])
        self.assertIsNotNone(concentration["top_10_signed_index_return_share"])
        self.assertGreater(concentration["positive_contribution_hhi"], 0)
        self.assertGreaterEqual(concentration["stocks_needed_for_80pct_positive_contribution"], 1)

    def test_05_turnover_confirmation_and_pressure_metrics_exist(self):
        turnover = self.result["turnover_confirmation"]
        pressure = self.result["heavy_turnover_pressure"]
        self.assertIsNotNone(turnover["top10_contributor_amount_share"])
        self.assertIsNotNone(turnover["top20_turnover_amount_share"])
        self.assertIsNotNone(turnover["contribution_weighted_amount_ratio_20d"])
        self.assertIsNotNone(pressure["down_amount_share"])
        self.assertIsNotNone(pressure["top_turnover_20pct_return"])

    def test_06_groups_cover_weight_turnover_quadrants(self):
        groups = {row["group"] for row in self.result["weight_turnover_groups"]}
        self.assertEqual(
            groups,
            {"high_weight_high_turnover", "high_weight_low_turnover", "low_weight_high_turnover", "low_weight_low_turnover"},
        )

    def test_07_scores_are_0_to_100_after_min_history(self):
        scores = self.result["scores"]
        for key in ("participation", "turnover_confirmation", "contribution_concentration", "heavy_turnover_pressure", "index_lift_quality", "index_masking_risk"):
            self.assertIsNotNone(scores[key])
            self.assertGreaterEqual(scores[key], 0)
            self.assertLessEqual(scores[key], 100)

    def test_08_state_and_evidence_are_deterministic(self):
        self.assertIn(self.result["state"], {"broad_confirmed_rise", "concentrated_but_supported", "thin_weighted_lift", "masked_distribution", "broad_decline", "mixed_divergence", "unknown"})
        self.assertIn("state_cn", self.result)
        self.assertTrue(self.result["supporting_evidence"])
        self.assertIn(self.result["confidence"], {"high", "medium", "low", "unknown"})

    def test_09_fallback_index_marks_approximate_weights(self):
        fallback = self.result["by_symbol"]["000001.SH"]
        self.assertTrue(fallback["index_weight_is_approximate"])
        self.assertIn("index_weight_is_approximate", fallback["data_quality_flags"])
        self.assertIn("index_weight_not_point_in_time", fallback["data_quality_flags"])

    def test_10_history_is_bounded_for_display(self):
        self.assertLessEqual(len(self.result["history"]), 30)
        self.assertTrue(all("index_lift_quality" in row for row in self.result["history"]))

    def test_11_top_tables_include_required_fields(self):
        for table in ("top_positive_contributors", "top_negative_contributors", "top_absolute_contributors", "top_turnover_stocks"):
            self.assertTrue(self.result[table])
            row = self.result[table][0]
            for key in ("symbol", "index_weight", "return_1d", "amount", "amount_ratio_20d", "industry", "index_contribution"):
                self.assertIn(key, row)
        self.assertEqual(len(self.result["top_turnover_stocks"]), len(self.data["symbols"]))

    def test_12_module_is_explanation_layer_only(self):
        source = Path("analysis/index_lift_structure.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        forbidden_roots = ("strategy", "engine", "analysis.index_market_llm", "analysis.market_risk_policy")
        for module in imported:
            self.assertFalse(any(module == root or module.startswith(root + ".") for root in forbidden_roots), module)
        self.assertNotIn("deepseek", source.lower())


if __name__ == "__main__":
    unittest.main()
