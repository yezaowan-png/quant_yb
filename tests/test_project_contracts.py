import ast
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
import pandas as pd

from analysis.theme import save_theme_analysis
from cli.backtest_cli import run_report
from cli.common import find_trade_logs, split_trade_log_name
from cli.index_cli import run_index_report
from cli.shell import _dispatch_command
from cli.stats_cli import build_strategy_analysis
from data.stock_pool import resolve_pool_symbols
from main import cli as root_cli
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
        ]:
            with self.subTest(pattern=expected):
                self.assertIn(expected, gitignore)

    def test_config_example_keeps_execution_safety_defaults(self):
        text = (ROOT / "config.example.yaml").read_text(encoding="utf-8")
        self.assertIn('token: "你的Tushare Token"', text)
        self.assertIn("enforce_price_limits: true", text)
        self.assertIn("calls_per_minute: 500", text)

    def test_stock_pool_json_resolves_union_and_intersection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stock_pools.json"
            path.write_text(
                json.dumps(
                    {
                        "机器人": ["000001.sz", "000002.SZ"],
                        "AI": ["000002.SZ", "600519.SH"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config = {"stock_pool": {"path": str(path)}}

            self.assertEqual(
                resolve_pool_symbols(config, "机器人,AI", "any"),
                ["000001.SZ", "000002.SZ", "600519.SH"],
            )
            self.assertEqual(
                resolve_pool_symbols(config, "机器人,AI", "all"),
                ["000002.SZ"],
            )

    def test_stock_pool_json_accepts_named_stock_objects(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stock_pools.json"
            path.write_text(
                json.dumps(
                    {
                        "meta": {"format_version": 2},
                        "pools": {
                            "人形机器人": {
                                "description": "示例",
                                "stocks": [
                                    {"ts_code": "300024.sz", "name": "机器人"},
                                    {"ts_code": "002747.SZ", "name": "埃斯顿"},
                                ],
                            },
                            "AI算力": {
                                "stocks": [
                                    {"symbol": "002747.SZ", "name": "埃斯顿"},
                                    {"code": "603019.SH", "name": "中科曙光"},
                                ]
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config = {"stock_pool": {"path": str(path)}}

            self.assertEqual(
                resolve_pool_symbols(config, "人形机器人,AI算力", "any"),
                ["300024.SZ", "002747.SZ", "603019.SH"],
            )
            self.assertEqual(
                resolve_pool_symbols(config, "人形机器人,AI算力", "all"),
                ["002747.SZ"],
            )

    def test_theme_analysis_writes_summary_detail_and_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir = root / "cache"
            meta_dir = root / "meta"
            stats_dir = root / "output" / "statistics"
            cache_dir.mkdir(parents=True)
            meta_dir.mkdir(parents=True)

            pd.DataFrame(
                [
                    {"date": "20260102", "close": 10.0},
                    {"date": "20260103", "close": 11.0},
                ]
            ).to_csv(cache_dir / "000001.SZ.csv", index=False)
            pd.DataFrame(
                [
                    {"date": "20260102", "close": 20.0},
                    {"date": "20260103", "close": 18.0},
                ]
            ).to_csv(cache_dir / "000002.SZ.csv", index=False)
            pd.DataFrame(
                [
                    {"ts_code": "000001.SZ", "name": "甲公司"},
                    {"ts_code": "000002.SZ", "name": "乙公司"},
                ]
            ).to_csv(meta_dir / "stock_names.csv", index=False)

            pool_path = meta_dir / "stock_pools.json"
            pool_path.write_text(
                json.dumps({"测试题材": ["000001.SZ", "000002.SZ"]}, ensure_ascii=False),
                encoding="utf-8",
            )
            config = {
                "data": {"cache_dir": str(cache_dir), "meta_dir": str(meta_dir)},
                "stock_pool": {"path": str(pool_path)},
                "output": {"statistics_dir": str(stats_dir)},
            }

            result = save_theme_analysis(config, "测试题材", "20260102", "20260103")

            self.assertAlmostEqual(result.summary["avg_return_pct"], 0.0)
            self.assertAlmostEqual(result.summary["positive_ratio_pct"], 50.0)
            self.assertEqual(result.summary["best_symbol"], "000001.SZ")
            self.assertTrue(result.output_path.exists())
            self.assertTrue(result.summary_path.exists())
            self.assertTrue(result.html_path.exists())
            self.assertIn("测试题材", result.html_path.read_text(encoding="utf-8"))

    def test_dashboard_discovers_theme_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports_dir = root / "output" / "reports"
            stats_dir = root / "output" / "statistics"
            trades_dir = root / "output" / "trades"
            cache_dir = root / "cache"
            meta_dir = root / "meta"
            daily_basic_dir = meta_dir / "daily_basic"
            for path in (reports_dir, stats_dir, trades_dir, cache_dir, daily_basic_dir):
                path.mkdir(parents=True)

            stem = "theme_测试题材_20260101_20260131"
            pd.DataFrame(
                [
                    {
                        "pool": "测试题材",
                        "start": "20260101",
                        "end": "20260131",
                        "stock_count": 2,
                        "valid_count": 2,
                        "avg_return_pct": 3.5,
                        "median_return_pct": 3.5,
                        "positive_ratio_pct": 50.0,
                        "avg_max_drawdown_pct": -4.0,
                        "best_symbol": "000001.SZ",
                        "best_name": "甲公司",
                        "best_return_pct": 10.0,
                    }
                ]
            ).to_csv(stats_dir / f"{stem}_summary.csv", index=False)
            (stats_dir / f"{stem}.html").write_text("<html>theme</html>", encoding="utf-8")

            config = {
                "data": {"cache_dir": str(cache_dir)},
                "output": {
                    "reports_dir": str(reports_dir),
                    "statistics_dir": str(stats_dir),
                    "trades_dir": str(trades_dir),
                },
                "index_overview": {"indexes": []},
            }
            dashboard_path = generate_dashboard(config)
            dashboard = dashboard_path.read_text(encoding="utf-8")

            self.assertIn("测试题材", dashboard)
            self.assertIn(f"../statistics/{stem}.html", dashboard)
            self.assertIn("index-nav-panel", dashboard)
            self.assertIn("index-mini-chart", dashboard)
            self.assertIn("左侧选择 · K线/全市场成交额/涨跌分布联动", dashboard)
            self.assertIn("index-distribution-chart", dashboard)

    def test_dashboard_stock_selector_searches_csv_and_generates_kline_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports_dir = root / "output" / "reports"
            stats_dir = root / "output" / "statistics"
            trades_dir = root / "output" / "trades"
            cache_dir = root / "cache"
            meta_dir = root / "meta"
            daily_basic_dir = meta_dir / "daily_basic"
            for path in (reports_dir, stats_dir, trades_dir, cache_dir, daily_basic_dir):
                path.mkdir(parents=True)

            pd.DataFrame(
                [
                    {
                        "date": f"202601{day:02d}",
                        "open": 10 + day * 0.1,
                        "high": 10.4 + day * 0.1,
                        "low": 9.8 + day * 0.1,
                        "close": 10.2 + day * 0.1,
                        "volume": 1000 + day,
                    }
                    for day in range(1, 32)
                ]
            ).to_csv(cache_dir / "000001.SZ.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "ts_code": "000001.SZ",
                        "trade_date": "20260131",
                        "close": "13.2",
                        "total_mv": "1234567.89",
                    }
                ]
            ).to_csv(daily_basic_dir / "000001.SZ.csv", index=False)
            selector_csv = root / "iwencai.csv"
            pd.DataFrame(
                [
                    {
                        "股票代码": "000001.SZ",
                        "股票简称": "平安银行",
                        "一级行业": "银行",
                        "二级行业": "银行",
                        "三级行业": "股份制银行",
                        "行业板块": "银行|股份制银行",
                        "概念板块": "高股息精选|人工智能",
                        "最新价": "11.08",
                        "最新涨跌幅": "1.5",
                    }
                ]
            ).to_csv(selector_csv, index=False)
            config = {
                "data": {"cache_dir": str(cache_dir), "meta_dir": str(meta_dir)},
                "output": {
                    "reports_dir": str(reports_dir),
                    "statistics_dir": str(stats_dir),
                    "trades_dir": str(trades_dir),
                },
                "index_overview": {"indexes": []},
                "dashboard": {
                    "stock_selector": {
                        "csv_path": str(selector_csv),
                        "generate_kline_pages": True,
                        "kline_bars": 30,
                    }
                },
            }

            dashboard_path = generate_dashboard(config)
            dashboard = dashboard_path.read_text(encoding="utf-8")
            selector_page = reports_dir / "stock_selector.html"
            viewer_page = reports_dir / "stock_viewer.html"
            selector_html = selector_page.read_text(encoding="utf-8")
            viewer_html = viewer_page.read_text(encoding="utf-8")
            kline_page = reports_dir / "stock_kline" / "000001.SZ.html"

            self.assertTrue(selector_page.exists())
            self.assertTrue(viewer_page.exists())
            self.assertTrue(kline_page.exists())
            self.assertIn("股票选择器", dashboard)
            self.assertIn("股票查看器", dashboard)
            self.assertIn("stock_selector.html", dashboard)
            self.assertIn("stock_viewer.html", dashboard)
            self.assertNotIn("stock-selector-input", dashboard)
            self.assertIn("stock-selector-input", selector_html)
            self.assertIn("selector-mode", selector_html)
            self.assertIn("selector-sort-btn", selector_html)
            self.assertIn("selector-custom-name", selector_html)
            self.assertIn("selector-custom-create", selector_html)
            self.assertIn("selector-custom-import-btn", selector_html)
            self.assertIn("selector-custom-export", selector_html)
            self.assertIn("selector-add-board", selector_html)
            self.assertIn("selector-board-target", selector_html)
            self.assertIn("selectorScrollSnapshot", selector_html)
            self.assertIn("restoreSelectorScroll", selector_html)
            self.assertIn("quantyb:stock_selector_custom_boards:v1", selector_html)
            self.assertIn("custom_boards_path", selector_html)
            self.assertIn("pct_5d", selector_html)
            self.assertIn("market_cap", selector_html)
            self.assertIn("人工智能", dashboard)
            self.assertIn("stock_kline/000001.SZ.html", selector_html)
            self.assertIn("股票查看器", viewer_html)
            self.assertIn("viewer-search-input", viewer_html)
            self.assertIn("viewer-sidebar-toggle", viewer_html)
            self.assertIn("隐藏查找栏", viewer_html)
            self.assertIn("data-collapse-section=\"search\"", viewer_html)
            self.assertIn("data-collapse-section=\"boards\"", viewer_html)
            self.assertIn("sidebar-collapsed", viewer_html)
            self.assertIn("我的板块", viewer_html)
            self.assertIn("viewer-frame", viewer_html)
            self.assertIn("viewerScrollSnapshot", viewer_html)
            self.assertIn("restoreViewerScroll", viewer_html)
            self.assertIn("stock-viewer-data", viewer_html)
            self.assertIn("quantyb:stock_selector_custom_boards:v1", viewer_html)
            self.assertIn("stock_kline/000001.SZ.html", viewer_html)
            kline_html = kline_page.read_text(encoding="utf-8")
            self.assertIn("平安银行", kline_html)
            self.assertIn("axisPointer:{link:[{xAxisIndex:'all'}]", kline_html)
            self.assertNotIn('data-indicator="volume"', kline_html)
            self.assertIn("隐藏指标", kline_html)
            self.assertIn("function fmtTushareAmount(v)", kline_html)
            self.assertIn("if(p.seriesName==='成交额')val=fmtTushareAmount(val);", kline_html)

    def test_cli_common_recognizes_strategy_names_with_underscores(self):
        self.assertEqual(
            split_trade_log_name("000001.SZ_multi_timeframe_volume_trend"),
            ("000001.SZ", "multi_timeframe_volume_trend"),
        )

        with tempfile.TemporaryDirectory() as tmp:
            trades_dir = Path(tmp)
            expected = trades_dir / "000001.SZ_multi_timeframe_volume_trend.csv"
            expected.write_text("date,symbol,direction,price,size,commission,pnl\n", encoding="utf-8")
            (trades_dir / "000001.SZ_multi_timeframe_volume_trend_equity.csv").write_text(
                "date,equity\n", encoding="utf-8"
            )

            self.assertEqual(
                find_trade_logs(trades_dir),
                [("000001.SZ", "multi_timeframe_volume_trend", expected)],
            )

    def test_shell_dispatcher_routes_subcommands_once(self):
        with patch("cli.shell._cmd_stats") as command:
            self.assertTrue(
                _dispatch_command(
                    {},
                    [
                        "stats",
                        "theme",
                        "--pool",
                        "测试题材",
                        "--pool-mode",
                        "all",
                        "--start",
                        "20260101",
                        "--end",
                        "20260131",
                    ],
                )
            )
            command.assert_called_once_with(
                {},
                sub="theme",
                pool="测试题材",
                pool_mode="all",
                start="20260101",
                end="20260131",
            )

        with patch("cli.shell._cmd_dashboard") as command:
            self.assertTrue(
                _dispatch_command({}, ["dashboard", "--output", "report.html"])
            )
            command.assert_called_once_with({}, output="report.html")

        with patch("cli.backtest_cli.run_backtest_workflow") as command:
            self.assertTrue(
                _dispatch_command(
                    {},
                    ["backtest", "--strategy", "rsi", "--symbol", "000001.SZ"],
                )
            )
            command.assert_called_once_with(
                {},
                "rsi",
                "000001.SZ",
                None,
                None,
                "any",
                {"strategy": "rsi", "symbol": "000001.SZ"},
            )

        with patch("cli.shell._cmd_download") as command:
            self.assertTrue(
                _dispatch_command(
                    {},
                    [
                        "download",
                        "--symbol",
                        "000001.SZ",
                        "--start",
                        "20260101",
                        "--end",
                        "20260131",
                        "--force",
                        "--failed-file",
                        "failed.csv",
                    ],
                )
            )
            command.assert_called_once_with(
                {},
                symbol="000001.SZ",
                start="20260101",
                end="20260131",
                force=True,
                failed_file="failed.csv",
            )

        with patch("cli.shell._cmd_data_audit") as command:
            self.assertTrue(
                _dispatch_command({}, ["data-audit", "--deep", "--output", "audit"])
            )
            command.assert_called_once_with({}, deep=True, output="audit")

        with patch("cli.shell._cmd_sector_flow") as command:
            self.assertTrue(
                _dispatch_command(
                    {},
                    ["sector-flow", "report", "--date", "2026-08-24", "--output", "flow.html"],
                )
            )
            command.assert_called_once_with({}, sub="report", date="2026-08-24", output="flow.html")

        with patch("cli.shell.run_limit_strength") as command:
            self.assertTrue(
                _dispatch_command(
                    {},
                    ["stats", "limit-strength", "--back-days", "10", "--min-limit-count", "2"],
                )
            )
            command.assert_called_once_with(
                {},
                data_path=None,
                back_days=10,
                min_limit_count=2,
                output_dir=None,
            )

        with patch("cli.shell.run_support_resistance") as command:
            self.assertTrue(
                _dispatch_command(
                    {},
                    [
                        "stats",
                        "support-resistance",
                        "--symbol",
                        "688981",
                        "--name",
                        "中芯国际",
                        "--start",
                        "20240101",
                        "--end",
                        "20260717",
                    ],
                )
            )
            command.assert_called_once_with(
                {},
                symbol="688981",
                stock_name="中芯国际",
                start="20240101",
                end="20260717",
            )

        with patch("cli.shell.run_index_market") as command:
            self.assertTrue(
                _dispatch_command(
                    {},
                    ["index", "market", "--start", "20260101", "--end", "20260131"],
                )
            )
            command.assert_called_once_with(
                {},
                "20260101",
                "20260131",
                False,
                None,
            )

        with patch("cli.shell.run_index_members") as command:
            self.assertTrue(
                _dispatch_command(
                    {},
                    ["index", "members", "--all", "--start", "20260601", "--end", "20260630"],
                )
            )
            command.assert_called_once_with(
                {},
                None,
                True,
                "20260601",
                "20260630",
                False,
                False,
            )

        self.assertFalse(_dispatch_command({}, ["exit"]))
        with self.assertRaisesRegex(ValueError, "未知命令"):
            _dispatch_command({}, ["not-a-command"])

    def test_click_cli_routes_shared_services_with_expected_args(self):
        from cli.index_cli import DEFAULT_MEMBER_INDEX_CODES

        self.assertEqual(DEFAULT_MEMBER_INDEX_CODES.get("中证2000"), "932000.CSI")

        runner = CliRunner()
        config = {"test": True}

        with patch("cli.dashboard_cli._load_config", return_value=config), patch(
            "cli.dashboard_cli.run_dashboard"
        ) as command:
            result = runner.invoke(root_cli, ["dashboard", "--output", "report.html"])
            self.assertEqual(result.exit_code, 0, result.output)
            command.assert_called_once_with(config, "report.html")

        with patch("cli.sector_money_flow_cli._load_config", return_value=config), patch(
            "cli.sector_money_flow_cli.run_sector_money_flow_report"
        ) as command:
            result = runner.invoke(
                root_cli,
                ["sector-flow", "report", "--date", "2026-08-24", "--output", "flow.html"],
            )
            self.assertEqual(result.exit_code, 0, result.output)
            command.assert_called_once_with(
                config,
                "flow.html",
                trade_date="2026-08-24",
                collect_now=False,
            )

        with patch("cli.stats_cli._load_config", return_value=config), patch(
            "cli.stats_cli.run_theme_analysis"
        ) as command:
            result = runner.invoke(
                root_cli,
                [
                    "stats",
                    "theme",
                    "--pool",
                    "测试题材",
                    "--pool-mode",
                    "all",
                    "--start",
                    "20260101",
                    "--end",
                    "20260131",
                ],
            )
            self.assertEqual(result.exit_code, 0, result.output)
            command.assert_called_once_with(
                config,
                pool="测试题材",
                pool_mode="all",
                start="20260101",
                end="20260131",
            )

        with patch("cli.stats_cli._load_config", return_value=config), patch(
            "cli.stats_cli.run_limit_strength"
        ) as command:
            result = runner.invoke(
                root_cli,
                [
                    "stats",
                    "limit-strength",
                    "--data-path",
                    "uplim",
                    "--back-days",
                    "10",
                    "--min-limit-count",
                    "2",
                    "--output-dir",
                    "out",
                ],
            )
            self.assertEqual(result.exit_code, 0, result.output)
            command.assert_called_once_with(
                config,
                data_path="uplim",
                back_days=10,
                min_limit_count=2,
                output_dir="out",
            )

        with patch("cli.stats_cli._load_config", return_value=config), patch(
            "cli.stats_cli.run_support_resistance"
        ) as command:
            result = runner.invoke(
                root_cli,
                [
                    "stats",
                    "support-resistance",
                    "--symbol",
                    "688981",
                    "--name",
                    "中芯国际",
                    "--start",
                    "20240101",
                    "--end",
                    "20260717",
                ],
            )
            self.assertEqual(result.exit_code, 0, result.output)
            command.assert_called_once_with(
                config,
                symbol="688981",
                stock_name="中芯国际",
                start="20240101",
                end="20260717",
            )

        with patch("cli.data_cli._load_config", return_value=config), patch(
            "cli.data_cli.run_download"
        ) as command:
            result = runner.invoke(
                root_cli,
                [
                    "data",
                    "download",
                    "--symbol",
                    "000001.SZ",
                    "--start",
                    "20260101",
                    "--end",
                    "20260131",
                    "--force",
                    "--failed-file",
                    "failed.csv",
                ],
            )
            self.assertEqual(result.exit_code, 0, result.output)
            command.assert_called_once_with(
                config,
                "000001.SZ",
                "20260101",
                "20260131",
                True,
                "failed.csv",
            )

        with patch("cli.data_cli._load_config", return_value=config), patch(
            "cli.data_cli.run_data_audit"
        ) as command:
            result = runner.invoke(
                root_cli,
                ["data", "audit", "--deep", "--output", "audit"],
            )
            self.assertEqual(result.exit_code, 0, result.output)
            command.assert_called_once_with(config, deep=True, output="audit")

    def test_index_report_service_uses_configured_output_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports_dir = Path(tmp) / "reports"
            config = {
                "output": {"reports_dir": str(reports_dir)},
                "index_overview": {
                    "indexes": [{"symbol": "000001.SH", "name": "上证指数"}]
                },
            }
            downloader = MagicMock()
            downloader.load_index_cache.return_value = pd.DataFrame(
                [{"date": "20260102", "close": 3200.0}]
            )

            with patch("cli.index_cli.DataDownloader", return_value=downloader), patch(
                "cli.index_cli.generate_index_report"
            ) as generate:
                paths = run_index_report(config, symbol="000001.SH")

            expected = reports_dir / "index" / "000001.SH_overview.html"
            self.assertEqual(paths, [expected])
            generate.assert_called_once()
            self.assertEqual(generate.call_args.kwargs["output_path"], expected)

    def test_strategy_analysis_service_builds_expected_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            stats_dir = Path(tmp) / "statistics"
            config = {"output": {"statistics_dir": str(stats_dir)}}
            frame = pd.DataFrame([{"total_return_pct": 1.0}])
            stats = {"count": 1}

            with patch("cli.stats_cli.load_summary", return_value=frame), patch(
                "cli.stats_cli.compute_stats", return_value=stats
            ), patch("cli.stats_cli.build_analyze_page") as build_page:
                result, output_path = build_strategy_analysis(config, "rsi")

            self.assertEqual(result, stats)
            self.assertEqual(output_path, stats_dir / "analysis_rsi.html")
            build_page.assert_called_once_with("rsi", frame, output_path)

    def test_report_service_auto_detects_single_trade_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trades_dir = root / "trades"
            reports_dir = root / "reports"
            trades_dir.mkdir()
            log_path = trades_dir / "000001.SZ_rsi.csv"
            log_path.write_text(
                "date,symbol,direction,price,size,commission,pnl\n",
                encoding="utf-8",
            )
            config = {
                "output": {
                    "trades_dir": str(trades_dir),
                    "reports_dir": str(reports_dir),
                }
            }
            expected = reports_dir / "000001.SZ_rsi.html"

            with patch(
                "cli.backtest_cli._generate_one_report", return_value=expected
            ) as generate:
                result = run_report(config, symbol="000001.SZ", strategy="rsi")

            self.assertEqual(result, (1, 0))
            generate.assert_called_once_with(
                config, "000001.SZ", "rsi", log_path, None
            )


if __name__ == "__main__":
    unittest.main()
