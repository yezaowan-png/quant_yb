import unittest

import pandas as pd

from analysis.trendlines import (
    TrendlineConfig,
    analyze_trendlines,
    detect_downtrend_lines,
    detect_necklines,
    detect_support_resistance,
    detect_trend_channels,
    detect_uptrend_lines,
    identify_pivots,
)


def _frame_from_prices(highs, lows) -> pd.DataFrame:
    rows = []
    for idx, (high, low) in enumerate(zip(highs, lows)):
        close = (float(high) + float(low)) / 2.0
        rows.append(
            {
                "date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=idx),
                "open": close,
                "high": float(high),
                "low": float(low),
                "close": close,
                "volume": 1000 + idx,
            }
        )
    return pd.DataFrame(rows)


def _uptrend_frame() -> pd.DataFrame:
    low_pivots = {5, 15, 25, 35, 45, 55}
    high_pivots = {10, 20, 30, 40, 50}
    rows = []
    for idx in range(62):
        base = 10.0 + idx * 0.08
        low = base if idx in low_pivots else base + 0.7
        high = base + 2.8 if idx in high_pivots else low + 1.1
        close = (high + low) / 2.0
        rows.append(
            {
                "date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=idx),
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1000 + idx,
            }
        )
    return pd.DataFrame(rows)


def _downtrend_frame() -> pd.DataFrame:
    high_pivots = {5, 15, 25, 35, 45, 55}
    low_pivots = {10, 20, 30, 40, 50}
    rows = []
    for idx in range(62):
        base = 30.0 - idx * 0.08
        high = base if idx in high_pivots else base - 0.7
        low = base - 2.8 if idx in low_pivots else high - 1.1
        close = (high + low) / 2.0
        rows.append(
            {
                "date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=idx),
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1000 + idx,
            }
        )
    return pd.DataFrame(rows)


def _manual_pivot(index, date, price, pivot_type, strength=5.0):
    return {
        "index": index,
        "date": (pd.Timestamp("2026-01-01") + pd.Timedelta(days=index)).strftime("%Y-%m-%d"),
        "price": price,
        "type": pivot_type,
        "strength": strength,
        "confirmed_index": index + 2,
        "confirmed_date": (pd.Timestamp("2026-01-01") + pd.Timedelta(days=index + 2)).strftime("%Y-%m-%d"),
    }


class TrendlinesTest(unittest.TestCase):
    def test_identify_pivots_marks_fractal_highs_and_lows(self):
        df = _frame_from_prices(
            highs=[10, 11, 15, 12, 11, 10, 14, 11, 10],
            lows=[9, 8, 7, 8, 9, 6, 8, 9, 10],
        )

        pivots = identify_pivots(df, pivot_window=2)

        high_indices = [item["index"] for item in pivots if item["type"] == "swing_high"]
        low_indices = [item["index"] for item in pivots if item["type"] == "swing_low"]
        self.assertIn(2, high_indices)
        self.assertIn(6, high_indices)
        self.assertIn(5, low_indices)
        self.assertTrue(all("strength" in item for item in pivots))

    def test_detect_uptrend_lines_from_rising_swing_lows(self):
        df = _uptrend_frame()
        cfg = TrendlineConfig(pivot_window=2, tolerance_pct=0.015, atr_tolerance_mult=0.4)
        pivots = identify_pivots(df, cfg.pivot_window)

        lines = detect_uptrend_lines(df, pivots, cfg)

        self.assertTrue(lines)
        self.assertGreater(lines[0]["slope"], 0)
        self.assertGreaterEqual(lines[0]["touch_count"], 2)
        self.assertEqual(lines[0]["label"], "Uptrend Line")
        self.assertIn("close_distance_pct", lines[0])

    def test_detect_downtrend_lines_from_falling_swing_highs(self):
        df = _downtrend_frame()
        cfg = TrendlineConfig(pivot_window=2, tolerance_pct=0.015, atr_tolerance_mult=0.4)
        pivots = identify_pivots(df, cfg.pivot_window)

        lines = detect_downtrend_lines(df, pivots, cfg)

        self.assertTrue(lines)
        self.assertLess(lines[0]["slope"], 0)
        self.assertGreaterEqual(lines[0]["touch_count"], 2)
        self.assertEqual(lines[0]["label"], "Downtrend Line")

    def test_support_resistance_clusters_nearby_pivots(self):
        df = _frame_from_prices([16] * 30, [14] * 30)
        pivots = [
            _manual_pivot(3, "2026-01-04", 10.00, "swing_low"),
            _manual_pivot(9, "2026-01-10", 10.08, "swing_low"),
            _manual_pivot(15, "2026-01-16", 10.12, "swing_low"),
            _manual_pivot(6, "2026-01-07", 20.00, "swing_high"),
            _manual_pivot(12, "2026-01-13", 20.10, "swing_high"),
        ]
        cfg = TrendlineConfig(support_resistance_pct=0.02, support_resistance_atr_mult=0.0)

        levels = detect_support_resistance(df, pivots, cfg)

        self.assertEqual(levels["support"][0]["touch_count"], 3)
        self.assertEqual(levels["support"][0]["type"], "support")
        self.assertEqual(levels["resistance"][0]["touch_count"], 2)
        self.assertEqual(levels["resistance"][0]["type"], "resistance")

    def test_detect_trend_channels_builds_parallel_line(self):
        df = _uptrend_frame()
        cfg = TrendlineConfig(pivot_window=2, tolerance_pct=0.015, atr_tolerance_mult=0.4)
        pivots = identify_pivots(df, cfg.pivot_window)
        up_lines = detect_uptrend_lines(df, pivots, cfg)

        channels = detect_trend_channels(df, uptrend_lines=up_lines, downtrend_lines=[], pivots=pivots, config=cfg)

        self.assertTrue(channels)
        self.assertEqual(channels[0]["type"], "uptrend_channel")
        self.assertEqual(channels[0]["parallel_line"]["label"], "Channel Upper")
        self.assertGreater(channels[0]["width"], 0)

    def test_detect_neckline_candidates_for_head_and_shoulders(self):
        df = _frame_from_prices([24] * 35, [14] * 35)
        pivots = [
            _manual_pivot(5, "2026-01-06", 20.0, "swing_high"),
            _manual_pivot(10, "2026-01-11", 16.0, "swing_low"),
            _manual_pivot(15, "2026-01-16", 23.0, "swing_high"),
            _manual_pivot(20, "2026-01-21", 15.5, "swing_low"),
            _manual_pivot(25, "2026-01-26", 20.4, "swing_high"),
        ]
        cfg = TrendlineConfig(pivot_window=2)

        necklines = detect_necklines(df, pivots, cfg)

        self.assertTrue(necklines)
        self.assertEqual(necklines[0]["pattern_type"], "Head and Shoulders")
        self.assertEqual(necklines[0]["line"]["label"], "Neckline: Head and Shoulders")
        self.assertIn(necklines[0]["breakout_status"], {"not_broken", "testing", "broken_down"})

    def test_analyze_trendlines_supports_rolling_as_of_index(self):
        df = _uptrend_frame()
        cfg = TrendlineConfig(pivot_window=2, tolerance_pct=0.015, atr_tolerance_mult=0.4)

        full = analyze_trendlines(df, cfg)
        rolling = analyze_trendlines(df, cfg, as_of_index=30)

        self.assertLessEqual(rolling["latest"]["index"], 30)
        self.assertLessEqual(len(rolling["pivots"]), len(full["pivots"]))
        self.assertEqual(rolling["latest"]["date"], "2026-01-31")


if __name__ == "__main__":
    unittest.main()
