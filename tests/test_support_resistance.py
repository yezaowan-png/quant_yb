import tempfile
import unittest
from pathlib import Path

import pandas as pd

from analysis.support_resistance import (
    FIBONACCI_RATIOS,
    calc_fibonacci_levels,
    find_resonance_zone,
    normalize_stock_symbol,
    save_support_resistance_analysis,
)


def _price_frame(closes):
    close = pd.Series(closes, dtype=float)
    dates = pd.date_range("2024-01-01", periods=len(close), freq="D")
    return pd.DataFrame(
        {
            "date": dates,
            "open": close - 0.1,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "volume": 1000.0,
        }
    )


class SupportResistanceTest(unittest.TestCase):
    def test_normalize_stock_symbol_accepts_common_code_prefixes(self):
        cases = {
            "600519": ("sh600519", "600519.SH"),
            "SH600519": ("sh600519", "600519.SH"),
            "600519.sh": ("sh600519", "600519.SH"),
            "000001": ("sz000001", "000001.SZ"),
            "SZ000001": ("sz000001", "000001.SZ"),
            "000001.SZ": ("sz000001", "000001.SZ"),
        }

        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_stock_symbol(raw), expected)

    def test_fibonacci_levels_follow_high_low_time_order(self):
        dates = pd.date_range("2024-01-01", periods=3, freq="D")
        rising = pd.DataFrame(
            {"high": [10.0, 14.0, 13.0], "low": [9.0, 11.0, 12.0]},
            index=dates,
        )
        falling = pd.DataFrame(
            {"high": [14.0, 13.0, 12.0], "low": [13.0, 10.0, 11.0]},
            index=dates,
        )

        rising_levels = calc_fibonacci_levels(rising)
        falling_levels = calc_fibonacci_levels(falling)

        self.assertEqual(rising_levels["trend_dir"], "上涨")
        self.assertAlmostEqual(rising_levels["0.236"], 9.0 + (14.0 - 9.0) * 0.236)
        self.assertEqual(falling_levels["trend_dir"], "下跌")
        self.assertAlmostEqual(falling_levels["0.236"], 14.0 + (10.0 - 14.0) * 0.236)

    def test_resonance_uses_strict_two_percent_threshold(self):
        frame = pd.DataFrame({"close": [100.0, 100.0, 100.0]})
        fib_levels = {key: 100.0 for key, _ in FIBONACCI_RATIOS}
        fib_levels.update(
            {
                "0.236": 101.5,
                "0.382": 102.0,
                "0.500": 98.0,
                "0.618": 97.0,
                "0.786": 99.5,
            }
        )

        zones = find_resonance_zone(frame, fib_levels, ma_periods=(3,), threshold_pct=2.0)
        zones_by_fib = {zone["fib"]: zone for zone in zones}

        self.assertEqual(set(zones_by_fib), {"0.236", "0.786"})
        self.assertAlmostEqual(zones_by_fib["0.236"]["diff_pct"], 1.5)
        self.assertAlmostEqual(zones_by_fib["0.786"]["diff_pct"], 0.5)
        self.assertEqual(zones_by_fib["0.236"]["reference_type"], "压力")
        self.assertEqual(zones_by_fib["0.786"]["reference_type"], "支撑")

    def test_save_analysis_builds_html_and_local_echarts_without_network(self):
        frame = _price_frame([10.0, 10.2, 10.4, 10.6, 10.8])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {
                "output": {"reports_dir": str(root / "fallback-reports")},
                "support_resistance": {
                    "ma_periods": [3],
                    "resonance_threshold_pct": 2.0,
                    "adjust": "qfq",
                    "output_dir": str(root / "reports"),
                },
            }
            fetch_calls = []

            def price_fetcher(symbol, adjust):
                fetch_calls.append((symbol, adjust))
                return frame.copy()

            result = save_support_resistance_analysis(
                config=config,
                symbol="000001",
                stock_name="示例股票",
                start_date="20240101",
                end_date="20240105",
                price_fetcher=price_fetcher,
            )

            self.assertEqual(fetch_calls, [("sz000001", "qfq")])
            self.assertEqual(result.symbol, "000001.SZ")
            self.assertEqual(result.ak_symbol, "sz000001")
            self.assertIsNotNone(result.report_path)

            report_path = Path(result.report_path)
            document = report_path.read_text(encoding="utf-8")
            asset_path = report_path.parent / "assets" / "echarts.min.js"

            self.assertTrue(report_path.is_file())
            self.assertIn("K 线与关键价位", document)
            self.assertIn("文字分析", document)
            self.assertIn("type:'candlestick'", document)
            self.assertIn('<script src="assets/echarts.min.js"></script>', document)
            self.assertTrue(asset_path.is_file())
            self.assertGreater(asset_path.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
