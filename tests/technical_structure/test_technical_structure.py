from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.technical_structure import TechnicalStructureService, normalize_ohlcv, resample_ohlcv
from analysis.technical_structure.models import TechnicalStructureResult
from analysis.technical_structure.service import (
    DEFAULT_CONFIG,
    _cluster_pivots,
    _detect_channels,
    _line_payload,
    calculate_atr,
    identify_causal_pivots,
)
from visual.technical_structure_renderer import TechnicalStructureRenderer


def oscillating_frame(periods: int = 620, start: str = "2022-01-03") -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=periods)
    x = np.arange(periods, dtype=float)
    close = 100.0 + x * 0.025 + np.sin(x / 5.0) * 5.0 + np.sin(x / 23.0) * 2.0
    open_ = close + np.sin(x / 3.0) * 0.35
    high = np.maximum(open_, close) + 1.0 + np.abs(np.sin(x / 7.0))
    low = np.minimum(open_, close) - 1.0 - np.abs(np.cos(x / 9.0))
    return pd.DataFrame(
        {
            "trade_date": dates.strftime("%Y%m%d"),
            "open": open_, "high": high, "low": low, "close": close,
            "vol": 10000 + x * 3, "amount": (10000 + x * 3) * close,
        }
    )


class DataAdapterTests(unittest.TestCase):
    def test_provider_aliases_sort_and_index_adjustment(self):
        raw = oscillating_frame(20).iloc[::-1]
        normalized = normalize_ohlcv(raw, symbol="000001.SH", asset_type="index", adjustment="qfq")
        self.assertTrue(normalized.data["date"].is_monotonic_increasing)
        self.assertIn("volume", normalized.data.columns)
        self.assertEqual(normalized.adjustment, "none")

    def test_integer_yyyymmdd_dates_are_not_epoch_nanoseconds(self):
        raw = oscillating_frame(3)
        raw["trade_date"] = raw["trade_date"].astype(int)
        normalized = normalize_ohlcv(raw, symbol="TEST", asset_type="other", adjustment="none")
        self.assertEqual(normalized.data.iloc[0]["date"].strftime("%Y-%m-%d"), "2022-01-03")

    def test_canonical_date_wins_when_trade_date_also_exists(self):
        raw = oscillating_frame(3)
        raw["date"] = pd.to_datetime(raw["trade_date"], format="%Y%m%d")
        normalized = normalize_ohlcv(raw, symbol="TEST", asset_type="other", adjustment="none")
        self.assertEqual(normalized.data.columns.tolist().count("date"), 1)
        self.assertEqual(len(normalized.data), 3)

    def test_missing_volume_is_allowed_and_flagged(self):
        raw = oscillating_frame(20).drop(columns=["vol", "amount"])
        normalized = normalize_ohlcv(raw, symbol="TEST", asset_type="other", adjustment="none")
        self.assertEqual(len(normalized.data), 20)
        self.assertIn("missing_volume", normalized.data_quality_flags)

    def test_weekly_ohlcv_uses_last_actual_trade_date(self):
        raw = oscillating_frame(10, "2026-01-05")
        daily = normalize_ohlcv(raw, symbol="TEST", asset_type="other", adjustment="none")
        weekly = resample_ohlcv(daily, "1w")
        first = daily.data.iloc[:5]
        row = weekly.data.iloc[0]
        self.assertEqual(row["date"].strftime("%Y-%m-%d"), first.iloc[-1]["date"].strftime("%Y-%m-%d"))
        self.assertEqual(row["open"], first.iloc[0]["open"])
        self.assertEqual(row["close"], first.iloc[-1]["close"])
        self.assertEqual(row["high"], first["high"].max())
        self.assertEqual(row["low"], first["low"].min())
        self.assertEqual(row["volume"], first["volume"].sum())

    def test_incomplete_week_is_excluded_by_default(self):
        raw = oscillating_frame(8, "2026-01-05")
        daily = normalize_ohlcv(raw, symbol="TEST", asset_type="other", adjustment="none")
        weekly = resample_ohlcv(daily, "1w")
        included = resample_ohlcv(daily, "1w", include_incomplete_bar=True)
        self.assertEqual(len(weekly.data), 1)
        self.assertEqual(len(included.data), 2)
        self.assertFalse(bool(included.data.iloc[-1]["eligible_for_structure"]))
        self.assertIn("incomplete_bar_excluded", included.data_quality_flags)

    def test_holiday_short_week_can_be_explicitly_completed(self):
        raw = oscillating_frame(4, "2026-02-23")
        daily = normalize_ohlcv(raw, symbol="TEST", asset_type="other", adjustment="none")
        end = daily.data.iloc[-1]["date"].strftime("%Y%m%d")
        weekly = resample_ohlcv(daily, "1w", config={"completed_period_end_dates": [end]})
        self.assertEqual(len(weekly.data), 1)
        self.assertTrue(bool(weekly.data.iloc[-1]["is_complete"]))


class CausalityAndDetectionTests(unittest.TestCase):
    def setUp(self):
        self.frame = oscillating_frame()
        self.config = {"technical_structure": {"defaults": {"cache_enabled": False}}}

    def test_pivot_confirmation_never_precedes_pivot(self):
        normalized = normalize_ohlcv(self.frame, symbol="TEST", asset_type="other", adjustment="none")
        atr = calculate_atr(normalized.data)
        pivots = identify_causal_pivots(
            normalized.data, timeframe="1d", atr=atr,
            config=DEFAULT_CONFIG["timeframe"]["daily"], asset_type="other",
        )
        self.assertTrue(pivots)
        self.assertTrue(all(item["confirmation_bar_index"] > item["bar_index"] for item in pivots))

    def test_no_lookahead_for_all_assets_and_periods(self):
        cutoff_index = 519
        cutoff = pd.to_datetime(self.frame.iloc[cutoff_index]["trade_date"]).strftime("%Y-%m-%d")
        clipped = self.frame.iloc[: cutoff_index + 1].copy()
        for asset_type in ("index", "stock"):
            for timeframe in ("1d", "1w", "1mo"):
                service = TechnicalStructureService(self.config)
                full = service.analyze(
                    "000001.SH" if asset_type == "index" else "600000.SH",
                    asset_type, timeframe, self.frame, as_of_date=cutoff,
                    adjustment="none" if asset_type == "index" else "qfq",
                )
                prefix = service.analyze(
                    "000001.SH" if asset_type == "index" else "600000.SH",
                    asset_type, timeframe, clipped,
                    adjustment="none" if asset_type == "index" else "qfq",
                )
                self.assertEqual(full.pivots, prefix.pivots, (asset_type, timeframe, "pivots"))
                self.assertEqual(full.horizontal_levels, prefix.horizontal_levels, (asset_type, timeframe, "levels"))
                self.assertEqual(full.trendlines, prefix.trendlines, (asset_type, timeframe, "lines"))
                self.assertEqual(full.channels, prefix.channels, (asset_type, timeframe, "channels"))
                self.assertEqual(full.current_context, prefix.current_context, (asset_type, timeframe, "context"))

    def test_role_reversal_after_confirmed_break_and_retest(self):
        dates = pd.bdate_range("2026-01-01", periods=35)
        close = np.full(35, 96.0)
        close[22:24] = 104.0
        close[24:] = 102.0
        low = close - 1.0
        low[25] = 99.5
        frame = pd.DataFrame({
            "date": dates, "open": close, "high": close + 1.0, "low": low,
            "close": close, "volume": 1000.0, "amount": close * 1000,
        })
        atr = pd.Series(np.full(35, 1.0))
        pivots = [
            {"id": "h1", "pivot_type": "high", "price": 100.0, "atr": 1.0, "strength": 60,
             "bar_index": 8, "confirmation_bar_index": 10, "pivot_date": "2026-01-13", "confirmation_date": "2026-01-15"},
            {"id": "h2", "pivot_type": "high", "price": 100.2, "atr": 1.0, "strength": 60,
             "bar_index": 18, "confirmation_bar_index": 20, "pivot_date": "2026-01-27", "confirmation_date": "2026-01-29"},
        ]
        cfg = {**DEFAULT_CONFIG["timeframe"]["daily"], "level_tolerance_atr": 0.5, "level_tolerance_pct": 0.005}
        levels = _cluster_pivots(
            frame, pivots, atr, "1d", cfg,
            {"atr_buffer": 0.25, "confirmation_bars": 2, "role_reversal_lookahead_bars": 10},
        )
        self.assertEqual(levels[0]["original_type"], "resistance")
        self.assertEqual(levels[0]["type"], "support")
        self.assertEqual(levels[0]["status"], "role_reversal")

    def test_service_detects_levels_and_lines(self):
        result = TechnicalStructureService(self.config).analyze(
            "TEST", "other", "1d", self.frame, adjustment="none",
        )
        self.assertGreater(len(result.pivots), 10)
        self.assertTrue(result.horizontal_levels)
        self.assertTrue(result.trendlines)
        self.assertIn(result.current_context["active_trend"], {"up", "down", "mixed", "range"})

    def test_late_touch_does_not_hide_earlier_line_violation(self):
        dates = pd.bdate_range("2026-01-01", periods=40)
        expected = 10.0 + np.arange(40) * 0.1
        low = expected + 0.05
        low[20:29] = expected[20:29] - 2.0
        close = expected + 0.5
        close[20:29] = expected[20:29] - 2.0
        frame = pd.DataFrame({
            "date": dates, "open": expected + 0.5, "high": expected + 1.0,
            "low": low, "close": close, "volume": 1000.0, "amount": 10000.0,
        })
        pivots = [
            {"id": "l1", "pivot_type": "low", "bar_index": 5, "confirmation_bar_index": 7,
             "price": 10.5, "strength": 60, "confirmation_date": "2026-01-12"},
            {"id": "l2", "pivot_type": "low", "bar_index": 15, "confirmation_bar_index": 17,
             "price": 11.5, "strength": 60, "confirmation_date": "2026-01-26"},
            {"id": "l3", "pivot_type": "low", "bar_index": 35, "confirmation_bar_index": 37,
             "price": 13.5, "strength": 60, "confirmation_date": "2026-02-23"},
        ]
        cfg = {
            **DEFAULT_CONFIG["timeframe"]["daily"],
            "trendline_min_span_bars": 5,
            "trendline_min_pair_separation_bars": 2,
            "trendline_max_age_bars": 100,
        }
        line = _line_payload(
            frame, pd.Series(np.ones(40)), pivots[0], pivots[1], pivots,
            "ascending_support", "1d", cfg, DEFAULT_CONFIG["trendline"],
        )
        self.assertIsNotNone(line)
        self.assertEqual(line["status"], "broken")
        self.assertEqual(line["break_date"], dates[20].strftime("%Y-%m-%d"))

    def test_line_cannot_cut_through_price_between_anchors(self):
        dates = pd.bdate_range("2026-01-01", periods=45)
        expected = 10.0 + np.arange(45) * 0.1
        low = expected + 0.05
        low[20] = expected[20] - 2.0
        frame = pd.DataFrame({
            "date": dates, "open": expected + 0.5, "high": expected + 1.0,
            "low": low, "close": expected + 0.5, "volume": 1000.0, "amount": 10000.0,
        })
        pivots = [
            {"id": "l1", "pivot_type": "low", "bar_index": 5, "confirmation_bar_index": 7,
             "price": 10.5, "strength": 60, "confirmation_date": dates[7].strftime("%Y-%m-%d")},
            {"id": "l2", "pivot_type": "low", "bar_index": 35, "confirmation_bar_index": 37,
             "price": 13.5, "strength": 60, "confirmation_date": dates[37].strftime("%Y-%m-%d")},
        ]
        cfg = {
            **DEFAULT_CONFIG["timeframe"]["daily"],
            "trendline_min_span_bars": 5,
            "trendline_min_pair_separation_bars": 2,
            "trendline_max_age_bars": 100,
        }
        line = _line_payload(
            frame, pd.Series(np.ones(45)), pivots[0], pivots[1], pivots,
            "ascending_support", "1d", cfg, DEFAULT_CONFIG["trendline"],
        )
        self.assertIsNone(line)

    def test_channel_requires_two_opposite_touches_and_tracks_break(self):
        dates = pd.bdate_range("2026-01-01", periods=30)
        lower = 10.0 + np.arange(30) * 0.1
        upper = lower + 4.0
        frame = pd.DataFrame({
            "date": dates, "open": lower + 2.0, "high": upper - 0.2,
            "low": lower + 0.2, "close": lower + 2.0,
            "volume": 1000.0, "amount": 10000.0,
        })
        base = {
            "id": "base", "type": "ascending_support", "status": "active",
            "score": 80.0, "touch_count": 3, "slope_per_bar": 0.1,
            "intercept": 10.0, "start_date": dates[0].strftime("%Y-%m-%d"),
            "confirmation_date": dates[12].strftime("%Y-%m-%d"),
            "projection_end_date": dates[-1].strftime("%Y-%m-%d"),
            "start_bar_index": 0, "end_bar_index": 10,
            "projection_end_bar_index": 29,
        }
        opposite = [
            {"id": "h1", "pivot_type": "high", "bar_index": 5, "confirmation_bar_index": 6,
             "price": upper[5], "strength": 60},
            {"id": "h2", "pivot_type": "high", "bar_index": 15, "confirmation_bar_index": 16,
             "price": upper[15], "strength": 60},
        ]
        cfg = {**DEFAULT_CONFIG["timeframe"]["daily"], "max_channels": 1}
        common = DEFAULT_CONFIG["trendline"]
        self.assertEqual(_detect_channels(
            frame, opposite[:1], pd.Series(np.ones(30)), [base], "1d", cfg, common,
        ), [])
        channels = _detect_channels(
            frame, opposite, pd.Series(np.ones(30)), [base], "1d", cfg, common,
        )
        self.assertEqual(len(channels), 1)
        self.assertEqual(channels[0]["status"], "active")
        self.assertEqual(channels[0]["confirmation_date"], dates[16].strftime("%Y-%m-%d"))

        broken_frame = frame.copy()
        broken_frame.loc[20:21, "high"] = upper[20:22] + 2.0
        broken = _detect_channels(
            broken_frame, opposite, pd.Series(np.ones(30)), [base], "1d", cfg, common,
        )
        self.assertEqual(broken[0]["status"], "broken")
        self.assertEqual(broken[0]["break_date"], dates[20].strftime("%Y-%m-%d"))


class ConfigurationCacheAndRenderTests(unittest.TestCase):
    def test_cache_separates_adjustment_and_config(self):
        frame = oscillating_frame(180)
        with tempfile.TemporaryDirectory() as tmp:
            service = TechnicalStructureService(
                {"technical_structure": {"defaults": {"cache_enabled": True}}}, cache_dir=tmp
            )
            qfq = service.analyze("600000.SH", "stock", "1d", frame, adjustment="qfq")
            hfq = service.analyze("600000.SH", "stock", "1d", frame, adjustment="hfq")
            changed = service.analyze(
                "600000.SH", "stock", "1d", frame, adjustment="qfq",
                config={"timeframe": {"daily": {"pivot_reversal_atr": 2.2}}},
            )
            self.assertNotEqual(qfq.cache_path, hfq.cache_path)
            self.assertNotEqual(qfq.cache_path, changed.cache_path)
            self.assertTrue(Path(qfq.cache_path).exists())

    def test_manual_lines_do_not_receive_automatic_score(self):
        frame = oscillating_frame(100)
        config = {"technical_structure": {
            "defaults": {"cache_enabled": False},
            "manual_technical_lines": {"TEST": {"1d": [
                {"type": "horizontal_support", "price": 90, "adjustment": "qfq", "note": "人工支撑"},
                {"type": "trendline", "adjustment": "qfq", "start": {"date": "2022-01-10", "price": 92},
                 "end": {"date": "2022-03-10", "price": 98}},
            ]}},
        }}
        result = TechnicalStructureService(config).analyze("TEST", "stock", "1d", frame, adjustment="qfq")
        manual_levels = [item for item in result.horizontal_levels if item["source"] == "manual"]
        manual_lines = [item for item in result.trendlines if item["source"] == "manual"]
        self.assertEqual(manual_levels[0]["score"], 0.0)
        self.assertEqual(manual_lines[0]["score"], 0.0)

    def test_manual_adjustment_mismatch_is_reported(self):
        config = {"technical_structure": {
            "defaults": {"cache_enabled": False},
            "manual_technical_lines": {"TEST": {"1d": [
                {"type": "horizontal_support", "price": 90, "adjustment": "hfq"},
            ]}},
        }}
        result = TechnicalStructureService(config).analyze(
            "TEST", "stock", "1d", oscillating_frame(100), adjustment="qfq",
        )
        self.assertIn("manual_adjustment_mismatch", result.data_quality_flags)

    def test_renderer_clips_line_price_using_bar_index(self):
        bars = [
            {"bar_index": i, "date": date, "open": 1, "high": 1, "low": 1, "close": 1,
             "volume": 1, "amount": 1, "atr": 1, "is_complete": True, "eligible_for_structure": True}
            for i, date in enumerate(["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06"])
        ]
        result = TechnicalStructureResult(
            symbol="TEST", asset_type="other", timeframe="1d", adjustment="none",
            as_of_date="2026-01-06", bar_count=4, bars=bars,
            trendlines=[{
                "id": "line", "type": "ascending_support", "status": "active", "source": "automatic",
                "score": 80, "start_date": "2026-01-01", "projection_end_date": "2026-01-06",
                "start_bar_index": 0, "projection_end_bar_index": 3, "start_price": 10,
                "projection_end_price": 16, "slope_per_bar": 2, "intercept": 10,
                "touch_count": 2, "confirmation_date": "2026-01-02",
            }],
        )
        series = TechnicalStructureRenderer().build_echarts_series(result, ["2026-01-05", "2026-01-06"])
        self.assertEqual(series[0]["data"], [["2026-01-05", 14.0], ["2026-01-06", 16.0]])

    def test_renderer_materializes_points_inside_zoom_window(self):
        dates = pd.bdate_range("2026-01-01", periods=30).strftime("%Y-%m-%d").tolist()
        bars = [
            {"bar_index": index, "date": date, "open": 1, "high": 1, "low": 1, "close": 1,
             "volume": 1, "amount": 1, "atr": 1, "is_complete": True, "eligible_for_structure": True}
            for index, date in enumerate(dates)
        ]
        result = TechnicalStructureResult(
            symbol="TEST", asset_type="other", timeframe="1d", adjustment="none",
            as_of_date=dates[-1], bar_count=len(dates), bars=bars,
            trendlines=[{
                "id": "line", "type": "ascending_support", "status": "active", "source": "automatic",
                "score": 80, "start_date": dates[0], "projection_end_date": dates[-1],
                "start_bar_index": 0, "projection_end_bar_index": 29, "start_price": 10,
                "projection_end_price": 20, "slope_per_bar": 10 / 29, "intercept": 10,
                "touch_count": 2, "confirmation_date": dates[2],
            }],
        )
        series = TechnicalStructureRenderer().build_echarts_series(result, dates)
        visible_dates = set(dates[12:20])
        visible_points = [point for point in series[0]["data"] if point[0] in visible_dates]
        self.assertEqual(len(visible_points), 8)
        self.assertGreater(visible_points[-1][1], visible_points[0][1])

    def test_lower_period_chart_only_overlays_high_period_horizontal_levels(self):
        dates = ["2026-01-01", "2026-01-02", "2026-01-05"]
        daily = TechnicalStructureResult(
            symbol="TEST", asset_type="other", timeframe="1d", adjustment="none",
            as_of_date=dates[-1], bar_count=3,
        )
        weekly = TechnicalStructureResult(
            symbol="TEST", asset_type="other", timeframe="1w", adjustment="none",
            as_of_date=dates[-1], bar_count=3,
            horizontal_levels=[{
                "type": "support", "price": 10, "zone_low": 9.8, "zone_high": 10.2,
                "first_touch_date": dates[0], "touch_count": 3, "score": 80,
                "status": "active", "source": "automatic", "distance_pct": 0.01,
            }],
            trendlines=[{
                "id": "weekly-line", "type": "ascending_support", "status": "active",
                "source": "automatic", "score": 90, "start_date": dates[0],
                "projection_end_date": dates[-1], "start_bar_index": 0,
                "projection_end_bar_index": 2, "start_price": 9,
                "projection_end_price": 11, "slope_per_bar": 1, "intercept": 9,
                "touch_count": 3, "confirmation_date": dates[1],
            }],
        )
        series = TechnicalStructureRenderer().build_multi_timeframe_series(
            {"1d": daily, "1w": weekly}, "1d", dates,
        )
        names = [item["name"] for item in series]
        self.assertTrue(any("周线·支撑" in name for name in names))
        self.assertFalse(any("周线·上升支撑" in name for name in names))

    def test_renderer_hides_inactive_by_default(self):
        result = TechnicalStructureResult(
            symbol="TEST", asset_type="other", timeframe="1d", adjustment="none",
            as_of_date="2026-01-02", bar_count=2,
            horizontal_levels=[{
                "type": "support", "price": 10, "zone_low": 9.8, "zone_high": 10.2,
                "first_touch_date": "2026-01-01", "touch_count": 2, "score": 70,
                "status": "broken", "source": "automatic",
            }],
        )
        renderer = TechnicalStructureRenderer()
        axis = ["2026-01-01", "2026-01-02"]
        self.assertEqual(renderer.build_echarts_series(result, axis), [])
        self.assertEqual(len(renderer.build_echarts_series(result, axis, {"include_broken": True})), 1)


if __name__ == "__main__":
    unittest.main()
