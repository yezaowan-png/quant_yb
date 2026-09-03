import json
import os
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from analysis.theme import save_theme_analysis
from visual.dashboard import _theme_dashboards, generate_dashboard


class ThemeOutputTest(unittest.TestCase):
    def _build_config(self, root: Path) -> dict:
        cache_dir = root / "cache"
        meta_dir = root / "meta"
        stats_dir = root / "output" / "statistics"
        reports_dir = root / "output" / "reports"
        trades_dir = root / "output" / "trades"
        signals_dir = root / "output" / "signals"
        pool_path = meta_dir / "stock_pools.json"

        for path in (cache_dir, meta_dir, stats_dir, reports_dir, trades_dir, signals_dir):
            path.mkdir(parents=True, exist_ok=True)

        pool_path.write_text(
            json.dumps(
                {
                    "pools": {
                        "机器人": {
                            "stocks": [
                                {"ts_code": "000001.SZ", "name": "平安银行"},
                                {"ts_code": "000002.SZ", "name": "万科A"},
                            ]
                        }
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "name": "平安银行"},
                {"ts_code": "000002.SZ", "name": "万科A"},
            ]
        ).to_csv(meta_dir / "stock_names.csv", index=False)

        pd.DataFrame(
            [
                {"date": "20260601", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1000},
                {"date": "20260602", "open": 10, "high": 12, "low": 10, "close": 12, "volume": 1100},
            ]
        ).to_csv(cache_dir / "000001.SZ.csv", index=False)
        pd.DataFrame(
            [
                {"date": "20260601", "open": 20, "high": 20, "low": 18, "close": 20, "volume": 1000},
                {"date": "20260602", "open": 20, "high": 20, "low": 18, "close": 18, "volume": 1100},
            ]
        ).to_csv(cache_dir / "000002.SZ.csv", index=False)

        daily_basic_dir = meta_dir / "daily_basic"
        daily_basic_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": "20260601", "turnover_rate": 1.0, "volume_ratio": 1.2, "total_mv": 100},
                {"ts_code": "000001.SZ", "trade_date": "20260602", "turnover_rate": 2.0, "volume_ratio": 1.4, "total_mv": 120},
            ]
        ).to_csv(daily_basic_dir / "000001.SZ.csv", index=False)

        return {
            "data": {"cache_dir": str(cache_dir), "meta_dir": str(meta_dir)},
            "stock_pool": {"path": str(pool_path)},
            "output": {
                "statistics_dir": str(stats_dir),
                "reports_dir": str(reports_dir),
                "trades_dir": str(trades_dir),
                "signals_dir": str(signals_dir),
            },
            "index_overview": {"indexes": []},
        }

    def test_theme_analysis_writes_csv_and_html_dashboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._build_config(Path(tmp))
            result = save_theme_analysis(config, "机器人", "20260601", "20260602")

            self.assertEqual(result.summary["stock_count"], 2)
            self.assertEqual(result.summary["valid_count"], 2)
            self.assertAlmostEqual(result.summary["avg_return_pct"], 5.0)
            self.assertAlmostEqual(result.summary["concept_return_pct"], 5.0)
            self.assertEqual(len(result.concept_index), 2)
            self.assertAlmostEqual(result.concept_index.iloc[0]["close"], 1000.0)
            self.assertAlmostEqual(result.concept_index.iloc[-1]["close"], 1050.0)
            self.assertAlmostEqual(result.concept_index.iloc[-1]["volume"], 2200.0)
            self.assertIn("amount_ma5", result.concept_index.columns)
            self.assertIn("amount_ma20", result.concept_index.columns)
            self.assertIn("ma60", result.concept_index.columns)
            self.assertIn("above_ma20_ratio_pct", result.concept_index.columns)
            self.assertIn("above_ma60_ratio_pct", result.concept_index.columns)
            self.assertIn("new_high_20_count", result.concept_index.columns)
            self.assertIn("new_low_20_count", result.concept_index.columns)
            self.assertIn("member_return_std_pct", result.concept_index.columns)
            self.assertIn("annualized_volatility_pct", result.details.columns)
            self.assertIn("return_drawdown_ratio", result.details.columns)
            self.assertIn("latest_close_vs_ma20_pct", result.details.columns)
            self.assertIn("latest_volume_ratio_20", result.details.columns)
            self.assertIn("return_std_pct", result.summary)
            self.assertIn("concept_latest_above_ma20_ratio_pct", result.summary)
            self.assertIn("concept_latest_new_high_20_ratio_pct", result.summary)
            self.assertTrue(result.output_path.exists())
            self.assertTrue(result.summary_path.exists())
            self.assertTrue(result.index_path.exists())
            self.assertTrue(result.html_path.exists())

            html = result.html_path.read_text(encoding="utf-8")
            self.assertIn("机器人 题材涨跌看板", html)
            self.assertIn("概念指数 K 线", html)
            self.assertIn("conceptKlineChart", html)
            self.assertIn("conceptVolumeChart", html)
            self.assertIn("成交金额", html)
            self.assertIn("conceptAmountChart", html)
            self.assertIn("趋势广度", html)
            self.assertIn("trendBreadthChart", html)
            self.assertIn("MA20上方占比", html)
            self.assertIn("20日新高/新低", html)
            self.assertIn('class="stock-link"', html)
            self.assertIn("../reports/stock_kline/000001.SZ.html", html)
            self.assertIn("个股离散度", html)
            self.assertIn("趋势强弱", html)
            self.assertIn("strengthChart", html)
            self.assertIn("switchThemeIndicator", html)
            self.assertIn("echarts.connect('theme-concept-index')", html)
            self.assertIn("conceptDataZoom(rows", html)
            self.assertIn("日线", html)
            self.assertIn("周线", html)
            self.assertIn("月线", html)
            self.assertIn("switchConceptPeriod", html)
            self.assertIn("resampleConceptRows", html)
            self.assertIn("rankRows", html)
            self.assertIn("涨幅前7 / 跌幅后5", html)
            self.assertIn("20260601 ~ 20260602 · 涨幅前7 / 跌幅后5", html)
            self.assertIn("平安银行", html)

    def test_concept_index_uses_full_cached_kline_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._build_config(Path(tmp))
            cache_dir = Path(config["data"]["cache_dir"])
            pd.DataFrame(
                [
                    {"date": "20260531", "open": 5, "high": 5, "low": 5, "close": 5, "volume": 900},
                    {"date": "20260601", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1000},
                    {"date": "20260602", "open": 10, "high": 12, "low": 10, "close": 12, "volume": 1100},
                ]
            ).to_csv(cache_dir / "000001.SZ.csv", index=False)
            pd.DataFrame(
                [
                    {"date": "20260531", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 900},
                    {"date": "20260601", "open": 20, "high": 20, "low": 18, "close": 20, "volume": 1000},
                    {"date": "20260602", "open": 20, "high": 20, "low": 18, "close": 18, "volume": 1100},
                ]
            ).to_csv(cache_dir / "000002.SZ.csv", index=False)

            result = save_theme_analysis(config, "机器人", "20260601", "20260602")

            self.assertEqual(result.concept_index["date"].tolist(), ["20260531", "20260601", "20260602"])
            self.assertAlmostEqual(result.concept_index.iloc[0]["close"], 1000.0)
            self.assertAlmostEqual(result.summary["concept_return_pct"], 5.0)

    def test_project_dashboard_discovers_theme_dashboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._build_config(Path(tmp))
            save_theme_analysis(config, "机器人", "20260601", "20260602")

            dashboard_path = generate_dashboard(config)
            html = dashboard_path.read_text(encoding="utf-8")

            self.assertIn("题材看板", html)
            self.assertIn("机器人", html)
            self.assertIn("../statistics/theme_机器人_20260601_20260602.html", html)
            self.assertIn("../statistics/theme_机器人_20260601_20260602.csv", html)
            self.assertIn("打开看板", html)
            self.assertIn("明细CSV", html)

    def test_theme_analysis_counts_missing_kline_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._build_config(Path(tmp))
            pool_path = Path(config["stock_pool"]["path"])
            pools = json.loads(pool_path.read_text(encoding="utf-8"))
            pools["pools"]["机器人"]["stocks"].append({"ts_code": "000003.SZ", "name": "缺数据"})
            pool_path.write_text(json.dumps(pools, ensure_ascii=False), encoding="utf-8")

            result = save_theme_analysis(config, "机器人", "20260601", "20260602")

            self.assertEqual(result.summary["stock_count"], 3)
            self.assertEqual(result.summary["valid_count"], 2)
            self.assertEqual(result.summary["missing_count"], 1)
            missing = result.details[result.details["ts_code"] == "000003.SZ"].iloc[0]
            self.assertEqual(missing["reason"], "无K线缓存")

    def test_dashboard_theme_discovery_keeps_summary_without_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stats_dir = root / "statistics"
            reports_dir = root / "reports"
            stats_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)

            pd.DataFrame(
                [
                    {
                        "pool": "缺HTML",
                        "start": "20260601",
                        "end": "20260602",
                        "stock_count": 3,
                        "valid_count": 2,
                        "avg_return_pct": 5.0,
                        "median_return_pct": 4.0,
                        "positive_ratio_pct": 50.0,
                        "avg_max_drawdown_pct": -2.0,
                        "best_symbol": "000001.SZ",
                        "best_name": "平安银行",
                        "best_return_pct": 20.0,
                    }
                ]
            ).to_csv(stats_dir / "theme_缺HTML_20260601_20260602_summary.csv", index=False)
            (stats_dir / "theme_broken_summary.csv").write_text("", encoding="utf-8")

            items = _theme_dashboards(stats_dir, reports_dir / "dashboard.html")

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["pool"], "缺HTML")
            self.assertFalse(items[0]["exists"])
            self.assertEqual(items[0]["href"], "")
            self.assertEqual(items[0]["detail_href"], "")

    def test_dashboard_theme_discovery_keeps_latest_per_pool(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stats_dir = root / "statistics"
            reports_dir = root / "reports"
            stats_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)

            for end, value in [("20260602", 1.0), ("20260702", 2.0)]:
                stem = f"theme_机器人_20260601_{end}"
                pd.DataFrame(
                    [
                        {
                            "pool": "机器人",
                            "start": "20260601",
                            "end": end,
                            "stock_count": 3,
                            "valid_count": 3,
                            "avg_return_pct": value,
                            "median_return_pct": value,
                            "positive_ratio_pct": 50.0,
                            "avg_max_drawdown_pct": -2.0,
                            "best_symbol": "000001.SZ",
                            "best_name": "平安银行",
                            "best_return_pct": value,
                        }
                    ]
                ).to_csv(stats_dir / f"{stem}_summary.csv", index=False)
                html_path = stats_dir / f"{stem}.html"
                html_path.write_text("<html>theme</html>", encoding="utf-8")
                os.utime(html_path, (1 if end == "20260602" else 2, 1 if end == "20260602" else 2))

            items = _theme_dashboards(stats_dir, reports_dir / "dashboard.html")

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["pool"], "机器人")
            self.assertEqual(items[0]["end"], "20260702")
            self.assertEqual(items[0]["avg_return"], "+2.00%")


if __name__ == "__main__":
    unittest.main()
