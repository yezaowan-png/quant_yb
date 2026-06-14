import ast
import unittest
from pathlib import Path


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
        ]:
            with self.subTest(pattern=expected):
                self.assertIn(expected, gitignore)

    def test_config_example_keeps_execution_safety_defaults(self):
        text = (ROOT / "config.example.yaml").read_text(encoding="utf-8")
        self.assertIn('token: "你的Tushare Token"', text)
        self.assertIn("enforce_price_limits: true", text)
        self.assertIn("calls_per_minute: 500", text)


if __name__ == "__main__":
    unittest.main()
