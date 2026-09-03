from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.index_forecast import build_rule_forecast
from analysis.market_structure_v2 import build_market_structure_v2
from tests.test_index_market_structure_v2 import _fixture_bundle, _recursive_keys


ROOT = Path(__file__).resolve().parents[1]
V2_SOURCE_FILES = (
    ROOT / "analysis" / "market_structure_v2.py",
    ROOT / "analysis" / "market_structure_state_v2.py",
)


def _imports(paths: tuple[Path, ...] = V2_SOURCE_FILES) -> set[str]:
    imported: set[str] = set()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
    return imported


class IndexMarketStructureV2IsolationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = _fixture_bundle()
        cls.result = cls.bundle["as_of_result"]
        cls.imports = _imports()

    def test_v2_40_formal_strategy_and_position_are_isolated(self):
        self.assertFalse(any(name == "strategy" or name.startswith("strategy.") for name in self.imports))
        self.assertFalse(any(name == "engine" or name.startswith("engine.") for name in self.imports))
        self.assertFalse(self.result["formal_strategy_influence"])
        self.assertNotIn("position", _recursive_keys(self.result))
        headline = self.result["deterministic_summary"]["headline"]
        for candidate in self.result["research_candidates"].values():
            self.assertTrue(candidate["exploratory_only"])
            self.assertIn("headline", candidate["excluded_from"])
            self.assertIn("position", candidate["excluded_from"])
            self.assertNotIn(str(candidate.get("phase")), headline)

    def test_v2_41_order_layer_is_not_imported_or_emitted(self):
        self.assertFalse(any(name == "backtrader" or name.startswith("backtrader.") for name in self.imports))
        self.assertFalse(self.result["position_or_order_influence"])
        self.assertNotIn("order", _recursive_keys(self.result))
        for candidate in self.result["research_candidates"].values():
            self.assertIn("order", candidate["excluded_from"])

    def test_v2_42_market_risk_gate_is_not_imported_or_modified(self):
        self.assertFalse(any(name.startswith("analysis.market_risk") for name in self.imports))
        self.assertFalse(any(name.startswith("cli.market_risk") for name in self.imports))
        self.assertFalse(self.result["market_risk_gate_influence"])
        for candidate in self.result["research_candidates"].values():
            self.assertIn("market_risk_gate", candidate["excluded_from"])
        for evidence in self.result["market_structure"]["evidence"].values():
            self.assertIn(evidence["confidence"], {"high", "medium", "low", "unknown"})
            self.assertIn("not a probability or forecast", evidence["confidence_semantics"])
            self.assertGreaterEqual(evidence["confidence_score"], 0.0)
            self.assertLessEqual(evidence["confidence_score"], 1.0)

    def test_v2_43_legacy_forecast_output_is_unchanged_by_v2_columns(self):
        dates = pd.bdate_range("2026-01-01", periods=80).strftime("%Y-%m-%d")
        base = pd.DataFrame(
            {
                "trade_date": dates,
                "close": 3_000.0 + np.arange(len(dates), dtype=float),
            }
        )
        baseline = build_rule_forecast(base, horizon=5)
        enriched = base.assign(
            market_structure_v2_state="broad_participation",
            market_structure_v2_confidence=0.75,
            market_structure_v2_exploratory=False,
        )
        actual = build_rule_forecast(enriched, horizon=5)
        pd.testing.assert_frame_equal(baseline, actual)

    def test_v2_44_llm_call_count_is_zero_and_p2_is_unknown(self):
        self.assertFalse(any("llm" in name.lower() for name in self.imports))
        self.assertEqual(self.result["llm_calls"], 0)
        self.assertEqual(self.result["valuation_context"]["status"], "unknown")
        self.assertEqual(self.result["external_context"]["status"], "unknown")
        self.assertFalse(self.result["valuation_context"]["core_state_influence"])
        self.assertFalse(self.result["external_context"]["core_state_influence"])

    def test_v2_45_different_horizons_have_identical_structure(self):
        signature = inspect.signature(build_market_structure_v2)
        self.assertNotIn("horizon", signature.parameters)
        as_of_result = self.bundle["as_of_result"]
        prefix_result = self.bundle["prefix_result"]
        self.assertEqual(as_of_result["data_hash"], prefix_result["data_hash"])
        self.assertEqual(as_of_result["market_structure"], prefix_result["market_structure"])
        self.assertEqual(as_of_result["layered_breadth"], prefix_result["layered_breadth"])
        self.assertNotIn("horizon", _recursive_keys(as_of_result))


if __name__ == "__main__":
    unittest.main()
