import tempfile
import unittest
from pathlib import Path

import pandas as pd

from analysis.data_quality import audit_market_data, save_market_data_audit
from visual.data_quality_report import generate_data_quality_report
from visual.dashboard import generate_dashboard


class MarketDataQualityTest(unittest.TestCase):
    def test_audit_reports_freshness_amount_and_invalid_ohlc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            index = cache / "index"
            meta = root / "meta"
            daily = meta / "daily_basic"
            stats = root / "statistics"
            reports = root / "reports"
            for path in (cache, index, daily, stats, reports):
                path.mkdir(parents=True, exist_ok=True)

            columns = ["date", "open", "high", "low", "close", "volume", "amount"]
            pd.DataFrame(
                [["20260806", 10, 11, 9, 10.5, 100, 1000], ["20260807", 10.5, 12, 10, 11, 120, 1500]],
                columns=columns,
            ).to_csv(cache / "000001.SZ.csv", index=False)
            pd.DataFrame(
                [["20260806", 10, 11, 9, 10, 100, 800]], columns=columns
            ).to_csv(cache / "000002.SZ.csv", index=False)
            pd.DataFrame(
                [["20260807", 10, 9, 11, 10, 100, 500]], columns=columns
            ).to_csv(cache / "000003.SZ.csv", index=False)
            pd.DataFrame(
                [["20260807", 3000, 3010, 2990, 3005]],
                columns=["date", "open", "high", "low", "close"],
            ).to_csv(index / "000001.SH.csv", index=False)
            for symbol in ("000001.SZ", "000002.SZ", "000003.SZ"):
                pd.DataFrame([{"ts_code": symbol, "trade_date": "20260807", "total_mv": 100000}]).to_csv(
                    daily / f"{symbol}.csv", index=False
                )
            pd.DataFrame(
                [{"ts_code": symbol, "name": symbol} for symbol in ("000001.SZ", "000002.SZ", "000003.SZ")]
            ).to_csv(meta / "stocks.csv", index=False)
            config = {
                "data": {"cache_dir": str(cache), "meta_dir": str(meta)},
                "output": {
                    "statistics_dir": str(stats),
                    "reports_dir": str(reports),
                    "trades_dir": str(root / "trades"),
                    "signals_dir": str(root / "signals"),
                },
                "index_overview": {"indexes": []},
            }

            result = audit_market_data(config)
            json_path, issues_path = save_market_data_audit(config, result)
            report_path = generate_data_quality_report(result, reports / "data_quality.html")
            (reports / "project_optimization_audit.html").write_text("<html>audit</html>", encoding="utf-8")

            self.assertEqual(result["status"], "critical")
            self.assertEqual(result["datasets"]["stocks"]["reference_date"], "20260807")
            self.assertEqual(result["datasets"]["stocks"]["stale_symbols"], ["000002.SZ"])
            self.assertEqual(result["datasets"]["stocks"]["latest_amount_cny"], 2_000_000.0)
            self.assertTrue(any(item["check"] == "ohlc_bounds" for item in result["issues"]))
            self.assertEqual(result["remediation"]["stock_redownload_symbols"], ["000003.SZ"])
            self.assertIn("--symbol 000003.SZ", result["remediation"]["stock_redownload_command"])
            self.assertTrue(json_path.exists())
            self.assertTrue(issues_path.exists())
            self.assertIn("本地市场数据质量报告", report_path.read_text(encoding="utf-8"))

            dashboard = generate_dashboard(config).read_text(encoding="utf-8")
            self.assertIn("data_quality.html", dashboard)
            self.assertIn("数据新鲜度", dashboard)
            self.assertIn("project_optimization_audit.html", dashboard)
            self.assertIn("项目优化审计", dashboard)

    def test_deep_audit_checks_historical_prices_and_daily_basic_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            index = cache / "index"
            daily = root / "meta" / "daily_basic"
            for path in (cache, index, daily):
                path.mkdir(parents=True, exist_ok=True)

            pd.DataFrame(
                [
                    {"date": "20260801", "open": 10, "high": 9, "low": 8, "close": 10, "volume": 100, "amount": 1000},
                    {"date": "20260807", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100, "amount": 1000},
                ]
            ).to_csv(cache / "000001.SZ.csv", index=False)
            pd.DataFrame(
                [
                    {"ts_code": "000001.SZ", "trade_date": "20260801"},
                    {"ts_code": "000001.SZ", "trade_date": "20260801"},
                    {"ts_code": "000001.SZ", "trade_date": "20260807"},
                ]
            ).to_csv(daily / "000001.SZ.csv", index=False)
            pd.DataFrame([{"ts_code": "000001.SZ", "name": "平安银行"}]).to_csv(
                root / "meta" / "stocks.csv", index=False
            )
            config = {"data": {"cache_dir": str(cache), "meta_dir": str(root / "meta")}}

            quick = audit_market_data(config)
            deep = audit_market_data(config, deep=True)

            self.assertFalse(any(item["check"] == "ohlc_bounds" for item in quick["issues"]))
            self.assertTrue(any(item["check"] == "ohlc_bounds" for item in deep["issues"]))
            self.assertTrue(any(item["check"] == "date_unique" for item in deep["issues"]))
            self.assertEqual(deep["datasets"]["stocks"]["row_count"], 2)
            self.assertEqual(deep["datasets"]["daily_basic"]["row_count"], 3)


if __name__ == "__main__":
    unittest.main()
