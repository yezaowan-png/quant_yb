import ast
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from decision.evaluator import evaluate_memory
from decision.recorder import append_buy_signals, load_memory
from engine.runner import BacktestRunner, load_strategy_class
from experiment.runner import run_experiment
from visual.dashboard import generate_dashboard


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
            "output/experiments/",
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
        self.assertIn("experiments_dir:", text)
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

    def test_dashboard_generates_research_cockpit_from_local_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir = root / "cache"
            index_cache_dir = cache_dir / "index"
            reports_dir = root / "reports"
            trades_dir = root / "trades"
            stats_dir = root / "statistics"
            decisions_dir = root / "decisions"
            experiments_dir = root / "experiments"
            for path in [index_cache_dir, reports_dir / "index", trades_dir, stats_dir, decisions_dir, experiments_dir]:
                path.mkdir(parents=True)

            pd.DataFrame(
                {
                    "date": ["20260101", "20260102"],
                    "close": [3200.0, 3225.0],
                    "pct_chg": [0.1, 0.78],
                    "amount": [350000000, 390000000],
                }
            ).to_csv(index_cache_dir / "000001.SH.csv", index=False)
            pd.DataFrame({"date": ["20260101", "20260102"], "close": [10.0, 10.4]}).to_csv(
                cache_dir / "000001.SZ.csv", index=False
            )
            pd.DataFrame(
                {
                    "symbol": ["000001.SZ", "000002.SZ"],
                    "total_return_pct": [8.0, -2.0],
                    "annual_return_pct": [20.0, -5.0],
                    "sharpe_ratio": [1.1, -0.3],
                    "max_drawdown_pct": [-4.0, -8.0],
                    "win_rate_pct": [55.0, 40.0],
                    "total_trades": [4, 0],
                }
            ).to_csv(trades_dir / "_summary_sma_cross.csv", index=False)
            pd.DataFrame(
                {
                    "symbol": ["000001.SZ"],
                    "strategy": ["sma_cross"],
                    "signal_date": ["2026-01-02"],
                    "recorded_at": ["2026-01-02T15:00:00"],
                    "evaluation_status": ["evaluated"],
                    "future_5d_return_pct": [3.5],
                    "excess_5d_return_pct": [1.2],
                }
            ).to_csv(decisions_dir / "decision_memory.csv", index=False)
            (reports_dir / "index" / "000001.SH_overview.html").write_text("index", encoding="utf-8")
            (reports_dir / "000001.SZ_sma_cross.html").write_text("stock report", encoding="utf-8")
            (stats_dir / "analysis_sma_cross.html").write_text("analysis", encoding="utf-8")
            (stats_dir / "comparison.html").write_text("comparison", encoding="utf-8")
            exp_dir = experiments_dir / "20260102_sma_cross"
            (exp_dir / "reports").mkdir(parents=True)
            (exp_dir / "manifest.json").write_text(
                '{"id": "exp-001", "strategy": "sma_cross", "status": "done"}',
                encoding="utf-8",
            )

            config = {
                "data": {"cache_dir": str(cache_dir)},
                "output": {
                    "reports_dir": str(reports_dir),
                    "trades_dir": str(trades_dir),
                    "statistics_dir": str(stats_dir),
                    "decisions_dir": str(decisions_dir),
                    "experiments_dir": str(experiments_dir),
                },
                "index_overview": {"indexes": [{"symbol": "000001.SH", "name": "上证指数"}]},
                "benchmark": {"enabled": True, "symbol": "000300.SH"},
            }

            output_path = generate_dashboard(config)
            html = output_path.read_text(encoding="utf-8")

            self.assertIn("QuantYB 研究总控", html)
            self.assertIn("市场温度", html)
            self.assertIn("数据健康", html)
            self.assertIn("策略排行榜", html)
            self.assertIn("最近实验", html)
            self.assertIn("风险提示", html)
            self.assertIn("20260102", html)
            self.assertNotIn("20260102.0", html)

    def test_experiment_runner_archives_config_summary_manifest_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir = root / "cache"
            cache_dir.mkdir()
            output_dir = root / "output"
            dates = pd.date_range("2026-01-01", periods=80, freq="B")
            closes = [10 + i * 0.03 + (i % 9) * 0.08 for i in range(len(dates))]
            pd.DataFrame(
                {
                    "date": dates.strftime("%Y%m%d"),
                    "open": [v - 0.05 for v in closes],
                    "high": [v + 0.12 for v in closes],
                    "low": [v - 0.12 for v in closes],
                    "close": closes,
                    "volume": [100000 + i * 1000 for i in range(len(dates))],
                }
            ).to_csv(cache_dir / "000001.SZ.csv", index=False)

            exp_config = root / "experiment.yaml"
            exp_config.write_text(
                """
id: unit_sma_cross
strategy: sma_cross
symbols:
  - 000001.SZ
start: "20260101"
end: "20260430"
params:
  fast: 3
  slow: 8
cost:
  commission: 0.00025
  stamp_duty: 0.001
  slippage_perc: 0.001
""".strip(),
                encoding="utf-8",
            )
            config = {
                "data": {"cache_dir": str(cache_dir)},
                "backtest": {
                    "initial_cash": 100000.0,
                    "commission": 0.00025,
                    "stamp_duty": 0.001,
                    "min_commission": 5.0,
                    "slippage_perc": 0.001,
                    "enforce_price_limits": True,
                    "limit_pct": 0.10,
                    "volume_limit_ratio": 0.0,
                    "volume_unit": 100,
                },
                "benchmark": {"enabled": False},
                "parallel": {"backtest_workers": 1},
                "output": {"trades_dir": str(output_dir / "trades")},
            }

            manifest = run_experiment(config, exp_config)
            exp_dir = output_dir / "experiments" / "unit_sma_cross"

            self.assertEqual(manifest["status"], "ready")
            self.assertEqual(manifest["result_counts"]["succeeded"], 1)
            self.assertTrue((exp_dir / "config.yaml").exists())
            self.assertTrue((exp_dir / "summary.csv").exists())
            self.assertTrue((exp_dir / "manifest.json").exists())
            self.assertTrue((exp_dir / "reports" / "000001.SZ_sma_cross.html").exists())
            summary = pd.read_csv(exp_dir / "summary.csv")
            for col in [
                "sortino_ratio",
                "profit_factor",
                "avg_trade_pnl",
                "longest_win_streak",
                "longest_loss_streak",
                "max_drawdown_days",
            ]:
                with self.subTest(summary_column=col):
                    self.assertIn(col, summary.columns)

    def test_multi_timeframe_strategy_runs_with_weekly_resample(self):
        dates = pd.date_range("2025-01-01", periods=160, freq="B")
        closes = [10 + i * 0.04 + (i % 17) * 0.05 for i in range(len(dates))]
        df = pd.DataFrame(
            {
                "date": dates,
                "open": [v - 0.03 for v in closes],
                "high": [v + 0.15 for v in closes],
                "low": [v - 0.15 for v in closes],
                "close": closes,
                "volume": [100000 + (i % 13) * 15000 for i in range(len(dates))],
            }
        )
        config = {
            "backtest": {
                "initial_cash": 100000.0,
                "commission": 0.00025,
                "stamp_duty": 0.001,
                "min_commission": 5.0,
                "slippage_perc": 0.001,
                "enforce_price_limits": True,
                "limit_pct": 0.10,
                "volume_limit_ratio": 0.0,
                "volume_unit": 100,
            },
            "benchmark": {"enabled": False},
            "parallel": {"backtest_workers": 1},
            "output": {"trades_dir": "unused"},
        }

        strategy_cls = load_strategy_class("multi_timeframe_volume_trend")
        self.assertTrue(getattr(strategy_cls, "REQUIRES_WEEKLY", False))
        result = BacktestRunner(config).run(
            df,
            strategy_cls,
            {"symbol": "000001.SZ", "volume_multiplier": 1.0},
            verbose=False,
        )
        self.assertIn("stats", result)
        self.assertEqual(result["stats"]["start_date"], "2025-01-01")
        self.assertIn("sortino_ratio", result["stats"])


if __name__ == "__main__":
    unittest.main()
