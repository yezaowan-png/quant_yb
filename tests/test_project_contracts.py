import ast
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from decision.evaluator import evaluate_memory
from decision.recorder import append_buy_signals, load_memory


ROOT = Path(__file__).resolve().parents[1]


def strategy_class_name(strategy_name: str) -> str:
    return "".join(part.capitalize() for part in strategy_name.split("_")) + "Strategy"


class ProjectContractsTest(unittest.TestCase):
    def test_strategy_files_follow_loader_naming_contract(self):
        strategy_dir = ROOT / "strategy"
        for path in strategy_dir.glob("*.py"):
            if path.stem in {"__init__", "base"}:
                continue
            with self.subTest(strategy=path.stem):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                classes = {
                    node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
                }
                self.assertIn(strategy_class_name(path.stem), classes)

    def test_gitignore_excludes_sensitive_and_generated_paths(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for expected in [
            "config.yaml",
            "data/cache/",
            "output/trades/",
            "output/reports/",
            "output/signals/",
            "output/statistics/",
            "output/decisions/",
            "output/audit/",
        ]:
            with self.subTest(pattern=expected):
                self.assertIn(expected, gitignore)

    def test_config_example_keeps_execution_safety_defaults(self):
        text = (ROOT / "config.example.yaml").read_text(encoding="utf-8")
        self.assertIn('token: "你的Tushare Token"', text)
        self.assertIn("enforce_price_limits: true", text)
        self.assertIn("calls_per_minute: 500", text)
        self.assertIn("decisions_dir:", text)
        self.assertIn("decision_memory:", text)

    def test_decision_memory_records_and_evaluates_with_trade_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir = root / "cache"
            cache_dir.mkdir()
            output_dir = root / "output"
            dates = pd.date_range("2026-01-01", periods=25, freq="B")
            prices = list(range(10, 35))
            pd.DataFrame({"date": dates.strftime("%Y%m%d"), "close": prices}).to_csv(
                cache_dir / "000001.SZ.csv", index=False
            )
            pd.DataFrame({"date": dates.strftime("%Y%m%d"), "close": prices}).to_csv(
                cache_dir / "000300.SH.csv", index=False
            )
            config = {
                "data": {"cache_dir": str(cache_dir)},
                "output": {"decisions_dir": str(output_dir / "decisions")},
                "benchmark": {"enabled": True, "symbol": "000300.SH"},
            }

            path, added = append_buy_signals(
                config,
                strategy="sma_cross",
                signals=[{"symbol": "000001.SZ", "recent_buy_dates": "2026-01-05"}],
            )
            self.assertEqual(added, 1)
            self.assertTrue(path.exists())

            stats = evaluate_memory(config, strategy="sma_cross", horizons=(5, 10, 20))
            self.assertEqual(stats["matched"], 1)
            self.assertEqual(stats["evaluated"], 1)
            memory = load_memory(config)
            row = memory.iloc[0]
            self.assertEqual(row["evaluation_status"], "evaluated")
            self.assertFalse(pd.isna(row["future_5d_return_pct"]))


if __name__ == "__main__":
    unittest.main()
