import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
from click.testing import CliRunner

from analysis.index_forecast import build_rule_forecast
from analysis.index_market_structure import (
    _approximate_price_limit_thresholds,
    ALL_A_INDEX_NAME,
    ALL_A_INDEX_SYMBOL,
    REGIME_NAMES,
    StockMarketPanels,
    _basket_daily_return,
    _index_metric,
    attach_market_structure_columns,
    build_market_structure,
    classify_breadth_periods,
    classify_market_style_regime,
    classify_period_divergence,
    classify_risk_directions,
    classify_style_period_state,
    load_required_index_frames,
    save_market_structure_outputs,
)
from cli.index_cli import (
    _archive_market_structure_outputs,
    _market_structure_alias_path,
    _market_structure_archive_dir,
    index_group,
)
from visual.components import relative_href
from visual.index_forecast_report import (
    _fmt_ratio_pct,
    _industry_technical_kline_payload,
    _market_chart_payload,
    _technical_kline_payload,
    generate_index_forecast_report,
    generate_market_structure_snapshot_report,
)


def _panels(days: int = 280) -> StockMarketPanels:
    dates = pd.date_range("2025-01-02", periods=days, freq="B")
    symbols = ["A.SH", "B.SH", "C.SZ", "D.SZ", "E.SH", "F.SZ"]
    close = pd.DataFrame(index=dates, columns=symbols, dtype=float)
    for offset, symbol in enumerate(symbols):
        trend = np.arange(days) * (0.018 + offset * 0.002)
        cycle = np.sin(np.arange(days) / (6.0 + offset)) * (0.2 + offset * 0.02)
        close[symbol] = 10.0 + offset + trend + cycle
    amount = pd.DataFrame(
        {symbol: 100_000 + np.arange(days) * (100 + offset * 10) for offset, symbol in enumerate(symbols)},
        index=dates,
    )
    metadata = pd.DataFrame(
        {
            "ts_code": symbols,
            "name": ["银行甲", "银行乙", "证券甲", "芯片甲", "食品甲", "保险甲"],
            "industry": ["银行", "银行", "证券", "半导体", "食品", "保险"],
            "market": ["主板", "主板", "主板", "创业板", "主板", "主板"],
        }
    )
    return StockMarketPanels(close=close, amount=amount, metadata=metadata)


def _index_frame(dates: pd.DatetimeIndex, start: float = 3000.0) -> pd.DataFrame:
    close = start + np.arange(len(dates)) * 1.5 + np.sin(np.arange(len(dates)) / 8.0) * 10
    return pd.DataFrame(
        {
            "date": dates,
            "open": close - 2,
            "high": close + 8,
            "low": close - 8,
            "close": close,
            "volume": 1_000_000 + np.arange(len(dates)) * 100,
            "amount": 2_000_000 + np.arange(len(dates)) * 200,
        }
    )


def _ths_index_frame_without_amount(dates: pd.DatetimeIndex, start: float = 3000.0) -> pd.DataFrame:
    frame = _index_frame(dates, start)
    return frame.drop(columns=["amount"])


def _structure(panels: StockMarketPanels) -> dict:
    primary = _index_frame(panels.close.index)
    hs300 = _index_frame(panels.close.index, 3800.0)
    csi1000 = _index_frame(panels.close.index, 6100.0)
    all_a = _index_frame(panels.close.index, 15000.0)
    return build_market_structure(
        "000001.SH",
        {
            "000001.SH": primary,
            "000300.SH": hs300,
            "000852.SH": csi1000,
            ALL_A_INDEX_SYMBOL: all_a,
        },
        panels,
    )


class IndexMarketStructureTest(unittest.TestCase):
    def test_layered_breadth_chart_payload_supports_ma_and_breakout_switches(self):
        row = {"trade_date": "2026-07-15", "advance_ratio": 0.5}
        for window in (5, 10, 20, 60):
            row[f"pct_above_ma{window}"] = window / 100.0
            row[f"new_high_{window}_ratio"] = window / 200.0
            row[f"new_low_{window}_ratio"] = window / 400.0
        payload = _market_chart_payload(
            {"layered_breadth": {"全A": {"history": [row], "state": "mixed"}}}
        )
        series = payload["layered_breadth_series"][0]
        for window in (5, 10, 20, 60):
            self.assertEqual(series[f"pct_above_ma{window}"], [window / 100.0])
            self.assertEqual(series[f"new_high_{window}_ratio"], [window / 200.0])
            self.assertEqual(series[f"new_low_{window}_ratio"], [window / 400.0])

    def test_market_chart_payload_uses_full_breadth_total_market_amount_history(self):
        payload = _market_chart_payload(
            {
                "breadth": {
                    "history": [
                        {"trade_date": "2026-07-14", "total_market_amount": 1100000000},
                        {"trade_date": "2026-07-15", "total_market_amount": 1200000000},
                        {"trade_date": "2026-07-16", "total_market_amount": 1300000000},
                    ]
                },
                "liquidity_structure": {
                    "history": [
                        {"trade_date": "2026-07-16", "total_amount": 999999999},
                    ]
                }
            }
        )

        self.assertEqual(payload["market_amount_dates"], ["2026-07-14", "2026-07-15", "2026-07-16"])
        self.assertEqual(payload["market_total_amount"], [1100000000.0, 1200000000.0, 1300000000.0])

    def test_market_chart_payload_falls_back_to_liquidity_history(self):
        payload = _market_chart_payload(
            {"liquidity_structure": {"history": [{"trade_date": "2026-07-15", "total_amount": 1200000000}]}}
        )
        self.assertEqual(payload["market_amount_dates"], ["2026-07-15"])
        self.assertEqual(payload["market_total_amount"], [1200000000.0])

    def test_breadth_denominator_ad_and_missing_index_are_explicit(self):
        panels = _panels()
        previous = panels.close.iloc[-2].copy()
        panels.close.iloc[-1] = previous * [1.01, 1.00, 0.99, 1.00, 1.03, np.nan]
        panels.amount.iloc[-1, 3] = 0.0
        structure = _structure(panels)
        latest = structure["breadth"]["latest"]
        self.assertEqual(latest["valid_stock_count"], 4.0)
        self.assertEqual(latest["advance_count"], 2.0)
        self.assertEqual(latest["decline_count"], 1.0)
        self.assertEqual(latest["flat_count"], 1.0)
        self.assertAlmostEqual(latest["normalized_ad"], 1.0 / 3.0)
        distribution = structure["breadth"]["return_distribution"]
        self.assertEqual(len(distribution), 12)
        self.assertEqual(distribution[0]["label"], "<-10%")
        self.assertEqual(distribution[-1]["label"], ">10%")
        self.assertEqual(sum(item["count"] for item in distribution), int(latest["valid_stock_count"]))
        self.assertFalse(structure["indices"]["上证50"]["available"])
        self.assertIn("missing_index_data:上证50:000016.SH", structure["data_quality_flags"])
        self.assertEqual(structure["styles"]["小盘题材"]["basket_type"], "official_index_proxy")
        self.assertIsNotNone(structure["styles"]["小盘题材"]["strength"])
        self.assertEqual(structure["styles"]["小盘题材"]["proxy_note"], "指数代理，无内部个股广度")

    def test_20260710_multiperiod_breadth_and_divergence_regression(self):
        sample = {
            "advance_ratio": 0.6844385833,
            "median_stock_return_1d": 0.0124940276,
            "equal_weight_return_1d": 0.0087946784,
            "normalized_ad": 0.3845274390,
            "median_stock_return_5d": -0.0361881852,
            "equal_weight_return_5d": -0.0393468775,
            "normalized_ad_5d": -1.1765705358,
            "median_stock_return_20d": -0.0461443663,
            "equal_weight_return_20d": -0.0193739757,
            "normalized_ad_20d": -1.6836027349,
            "pct_above_ma20": 0.2709800190,
        }
        states = classify_breadth_periods(sample)
        self.assertEqual(states["today_state"], "strong_repair")
        self.assertEqual(states["short_5d_state"], "weak")
        self.assertEqual(states["medium_20d_state"], "very_weak")
        self.assertEqual(states["summary"], "short_repair_medium_weak")
        self.assertEqual(classify_period_divergence(-0.0195897617, 0.0087946784), "stocks_stronger")
        self.assertEqual(classify_period_divergence(-0.0126775708, -0.0393468775), "large_cap_stronger")
        self.assertEqual(classify_period_divergence(0.0123611615, -0.0193739757), "large_cap_stronger")

    def test_strong_repair_requires_weak_short_or_medium_context(self):
        sample = {
            "advance_ratio": 0.70,
            "median_stock_return_1d": 0.02,
            "equal_weight_return_1d": 0.02,
            "normalized_ad": 0.50,
            "median_stock_return_5d": 0.03,
            "equal_weight_return_5d": 0.03,
            "normalized_ad_5d": 1.0,
            "median_stock_return_20d": 0.05,
            "equal_weight_return_20d": 0.05,
            "normalized_ad_20d": 2.0,
            "pct_above_ma20": 0.70,
        }
        self.assertEqual(classify_breadth_periods(sample)["today_state"], "strong")

    def test_approximate_limit_thresholds_include_bse_30_percent_board(self):
        metadata = pd.DataFrame(
            {
                "ts_code": ["600000.SH", "300001.SZ", "688001.SH", "830001.BJ", "000001.SZ"],
                "name": ["浦发银行", "创业公司", "科创公司", "北交公司", "ST测试"],
                "market": ["主板", "创业板", "科创板", "北交所", "主板"],
                "exchange": ["SSE", "SZSE", "SSE", "BSE", "SZSE"],
            }
        )
        thresholds = _approximate_price_limit_thresholds(metadata, pd.Index(metadata["ts_code"]))
        self.assertAlmostEqual(thresholds["600000.SH"], 0.095)
        self.assertAlmostEqual(thresholds["300001.SZ"], 0.195)
        self.assertAlmostEqual(thresholds["688001.SH"], 0.195)
        self.assertAlmostEqual(thresholds["830001.BJ"], 0.295)
        self.assertAlmostEqual(thresholds["000001.SZ"], 0.048)

    def test_20260710_style_periods_are_not_collapsed(self):
        self.assertEqual(classify_style_period_state(-0.0265510678, 0.0127958097), "pullback")
        self.assertEqual(classify_style_period_state(0.0343809128, 0.0537548885), "strong")
        self.assertEqual(classify_style_period_state(-0.0337471366, 0.0055997409), "weak")
        self.assertEqual(classify_style_period_state(0.0855195522, 0.1048935279), "strong")

    def test_risk_has_pressure_and_direction(self):
        frame = pd.DataFrame(
            [
                {"new_low_20_ratio": 0.21, "decline_gt_5_ratio": 0.16, "normalized_ad": -0.07, "normalized_nhnl_20": -0.18},
                {"new_low_20_ratio": 0.07, "decline_gt_5_ratio": 0.07, "normalized_ad": 0.38, "normalized_nhnl_20": -0.04},
            ]
        )
        directions = classify_risk_directions(frame, "medium")
        self.assertEqual(directions["risk_direction"], "contracting")
        self.assertTrue(all(key in directions for key in ("new_low_direction", "large_decline_direction", "ad_direction", "nhnl_direction")))

    def test_future_rows_do_not_change_past_breadth_or_new_high_low(self):
        full = _panels(285)
        prefix = StockMarketPanels(
            close=full.close.iloc[:280].copy(),
            amount=full.amount.iloc[:280].copy(),
            metadata=full.metadata,
        )
        full.close.iloc[280:] = full.close.iloc[279].to_numpy() * np.array([2, 0.5, 2, 0.5, 2, 0.5])
        prefix_structure = _structure(prefix)
        full_structure = _structure(full)
        date = prefix_structure["date"]
        past = next(row for row in full_structure["breadth"]["history"] if row["trade_date"] == date)
        for key in (
            "advance_ratio", "normalized_ad", "pct_above_ma20", "pct_above_ma200",
            "new_high_20_ratio", "new_low_20_ratio", "normalized_nhnl_250",
        ):
            self.assertAlmostEqual(prefix_structure["breadth"]["latest"][key], past[key])
        prefix_index = next(
            row for row in prefix_structure["index_history"] if row["trade_date"] == date
        )[ALL_A_INDEX_NAME]
        full_index = next(
            row for row in full_structure["index_history"] if row["trade_date"] == date
        )[ALL_A_INDEX_NAME]
        self.assertAlmostEqual(prefix_index, full_index)

    def test_average_price_benchmark_replaces_ths_all_a_contract(self):
        structure = _structure(_panels())
        self.assertNotIn("全A等权（合成）", structure["indices"])
        self.assertNotIn("all_a_equal_weight", structure)
        self.assertIn(ALL_A_INDEX_NAME, structure["indices"])
        self.assertEqual(structure["indices"][ALL_A_INDEX_NAME]["symbol"], ALL_A_INDEX_SYMBOL)
        self.assertTrue(structure["indices"][ALL_A_INDEX_NAME]["synthetic"])
        self.assertEqual(structure["all_a_index"]["source"], "本地股票池收盘价等权平均")

    def test_ths_style_and_industry_indexes_prefer_vendor_proxy_when_cached(self):
        panels = _panels()
        dates = panels.close.index
        ths_frames = {
            "881155.TI": _index_frame(dates, 1200.0),
            "881156.TI": _index_frame(dates, 1600.0),
            "881157.TI": _index_frame(dates, 1800.0),
        }
        structure = build_market_structure(
            "000001.SH",
            {
                "000001.SH": _index_frame(dates),
                "000300.SH": _index_frame(dates, 3800.0),
                "000852.SH": _index_frame(dates, 6100.0),
                ALL_A_INDEX_SYMBOL: _index_frame(dates, 15000.0),
            },
            panels,
            ths_index_frames=ths_frames,
            ths_index_names={"881155.TI": "银行", "881156.TI": "保险", "881157.TI": "证券"},
            ths_industry_symbols={"881155.TI", "881156.TI", "881157.TI"},
            ths_style_config={"权重价值": {"symbols": ["881155.TI"], "note": "银行同花顺指数代理"}},
        )

        self.assertEqual(structure["styles"]["权重价值"]["basket_type"], "ths_index_proxy")
        self.assertEqual(structure["styles"]["权重价值"]["data_source"], "Tushare ths_daily")
        self.assertEqual(structure["styles"]["权重价值"]["symbols"], ["881155.TI"])
        self.assertEqual(structure["sector_details"]["银行"]["basket_type"], "ths_index_proxy")
        self.assertEqual(structure["sector_details"]["银行"]["symbols"], ["881155.TI"])
        self.assertEqual(structure["sector_details"]["保险"]["symbols"], ["881156.TI"])
        self.assertEqual(structure["sector_details"]["证券"]["symbols"], ["881157.TI"])
        self.assertTrue(structure["industry_rankings"]["method_note"].startswith("同花顺行业指数"))
        self.assertEqual(structure["industry_rankings"]["rank_basis"], "return_1d")
        self.assertIn("all", structure["industry_rankings"])
        self.assertGreaterEqual(len(structure["industry_rankings"]["all"]), len(structure["industry_rankings"]["strongest"]))
        self.assertIn("银行", {row["industry"] for row in structure["industry_rankings"]["strongest"] + structure["industry_rankings"]["weakest"]})
        self.assertIn("ths_style_proxy_indexes_used", structure["data_quality_flags"])
        self.assertIn("financial_sector_proxy_indexes_used", structure["data_quality_flags"])
        self.assertIn("ths_industry_rankings_used", structure["data_quality_flags"])

    def test_ths_style_strength_works_without_amount_column(self):
        panels = _panels(days=69)
        dates = panels.close.index
        ths_frames = {
            "881155.TI": _ths_index_frame_without_amount(dates, 1200.0),
            "881156.TI": _ths_index_frame_without_amount(dates, 1600.0),
            "881157.TI": _ths_index_frame_without_amount(dates, 1800.0),
            "700030.TI": _ths_index_frame_without_amount(dates, 2200.0),
        }
        structure = build_market_structure(
            "000001.SH",
            {
                "000001.SH": _index_frame(dates),
                "000300.SH": _index_frame(dates, 3800.0),
                "000852.SH": _index_frame(dates, 6100.0),
                ALL_A_INDEX_SYMBOL: _index_frame(dates, 15000.0),
            },
            panels,
            ths_index_frames=ths_frames,
            ths_style_config={
                "权重价值": {"symbols": ["881155.TI", "881156.TI"]},
                "证券风险偏好": {"symbols": ["881157.TI"]},
                "小盘题材": {"symbols": ["700030.TI"]},
            },
        )

        self.assertEqual(structure["styles"]["权重价值"]["basket_type"], "ths_index_proxy")
        self.assertIsNotNone(structure["styles"]["权重价值"]["strength"])
        self.assertIsNotNone(structure["styles"]["证券风险偏好"]["strength"])
        self.assertIsNotNone(structure["styles"]["小盘题材"]["strength"])
        latest = structure["style_history"][-1]
        self.assertIsNotNone(latest["value_strength"])
        self.assertIsNotNone(latest["securities_strength"])
        self.assertIsNotNone(latest["small_cap_strength"])

    def test_report_industry_rankings_are_clickable_with_ths_kline_payload(self):
        panels = _panels()
        dates = panels.close.index
        ths_frames = {
            "881155.TI": _index_frame(dates, 1200.0),
            "881156.TI": _index_frame(dates, 1600.0),
            "881157.TI": _index_frame(dates, 1800.0),
        }
        structure = build_market_structure(
            "000001.SH",
            {
                "000001.SH": _index_frame(dates),
                "000300.SH": _index_frame(dates, 3800.0),
                "000852.SH": _index_frame(dates, 6100.0),
                ALL_A_INDEX_SYMBOL: _index_frame(dates, 15000.0),
            },
            panels,
            ths_index_frames=ths_frames,
            ths_index_names={"881155.TI": "银行", "881156.TI": "保险", "881157.TI": "证券"},
            ths_industry_symbols={"881155.TI", "881156.TI", "881157.TI"},
            ths_style_config={"权重价值": {"symbols": ["881155.TI"]}},
        )
        frame = _index_frame(dates[-90:])
        features = frame.rename(columns={"date": "trade_date"})
        features["trade_date"] = pd.to_datetime(features["trade_date"]).dt.strftime("%Y-%m-%d")
        for window in (20, 60, 120):
            features[f"ma{window}"] = features["close"].rolling(window, min_periods=1).mean()
        predictions = pd.DataFrame(
            {
                "trade_date": features["trade_date"],
                "market_score": 50.0,
                "predicted_opportunity_score": 50.0,
                "predicted_risk_score": 50.0,
                "environment_signal": "neutral",
                "signal": "neutral",
                "model": "rule_v1",
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.html"
            generate_index_forecast_report(
                features,
                predictions,
                output,
                "000001.SH",
                "上证指数",
                5,
                {},
                structure,
                llm_summary_links={
                    "summary": "000001.SH_h5_market_structure_llm_summary.html",
                    "facts": "000001.SH_h5_market_structure_llm_input.md",
                },
                technical_industry_frames=ths_frames,
            )
            html = output.read_text(encoding="utf-8")

        self.assertIn("查看大模型复盘总结", html)
        self.assertIn("000001.SH_h5_market_structure_llm_summary.html", html)
        self.assertIn("LLM事实包", html)
        self.assertIn("行业指数K线与技术指标", html)
        self.assertIn('id="industry-kline"', html)
        self.assertIn('id="industry-indicator"', html)
        self.assertIn("window._INDUSTRY_KLINES", html)
        self.assertIn("switchIndustryKline", html)
        self.assertIn("switchIndustryIndicator", html)
        self.assertIn("data-industry-symbol='881155.TI'", html)
        self.assertIn("data-industry-symbol='881157.TI'", html)
        self.assertIn('"881155.TI"', html)
        self.assertIn('"volume_ma20"', html)
        self.assertIn("代理指数1个", html)
        self.assertIn("risk-explain-list", html)
        self.assertIn("尾部压力等级", html)
        self.assertIn("20日新低方向", html)
        self.assertIn("方向与压力等级互补", html)
        self.assertNotIn("<strong>尾部压力：</strong>", html)

    def test_industry_kline_payload_keeps_full_cached_history_when_features_are_short(self):
        panels = _panels()
        dates = panels.close.index
        ths_frames = {
            "881155.TI": _index_frame(dates, 1200.0),
            "881157.TI": _index_frame(dates, 1800.0),
        }
        structure = build_market_structure(
            "000001.SH",
            {
                "000001.SH": _index_frame(dates),
                "000300.SH": _index_frame(dates, 3800.0),
                "000852.SH": _index_frame(dates, 6100.0),
                ALL_A_INDEX_SYMBOL: _index_frame(dates, 15000.0),
            },
            panels,
            ths_index_frames=ths_frames,
            ths_index_names={"881155.TI": "银行", "881157.TI": "证券"},
            ths_industry_symbols={"881155.TI", "881157.TI"},
            ths_style_config={"权重价值": {"symbols": ["881155.TI"]}},
        )
        features = _index_frame(dates[-30:]).rename(columns={"date": "trade_date"})
        features["trade_date"] = pd.to_datetime(features["trade_date"]).dt.strftime("%Y-%m-%d")

        payload = _industry_technical_kline_payload(
            features,
            structure["industry_rankings"],
            ths_frames,
        )

        bank_dates = payload["881155.TI"]["timeframes"]["1d"]["dates"]
        self.assertEqual(bank_dates[0], dates[0].strftime("%Y-%m-%d"))
        self.assertEqual(bank_dates[-1], dates[-1].strftime("%Y-%m-%d"))
        self.assertGreater(len(bank_dates), len(features))

    def test_required_index_frames_prefer_full_cached_primary_history(self):
        dates = pd.date_range("2025-01-02", periods=120, freq="B")
        full = _index_frame(dates)
        short = _index_frame(dates[-20:])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "index"
            root.mkdir(parents=True)
            full.assign(date=full["date"].dt.strftime("%Y%m%d")).to_csv(root / "000001.SH.csv", index=False)

            frames = load_required_index_frames(tmp, short, "000001.SH")

        self.assertEqual(len(frames["000001.SH"]), len(full))
        self.assertEqual(pd.to_datetime(frames["000001.SH"]["date"]).iloc[0], dates[0])

    def test_required_index_frames_clip_cached_future_rows_to_primary_as_of(self):
        dates = pd.date_range("2025-01-02", periods=130, freq="B")
        cached = _index_frame(dates)
        primary = _index_frame(dates[:120])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "index"
            root.mkdir(parents=True)
            cached.assign(date=cached["date"].dt.strftime("%Y%m%d")).to_csv(root / "000001.SH.csv", index=False)
            cached.assign(date=cached["date"].dt.strftime("%Y%m%d")).to_csv(root / "000300.SH.csv", index=False)

            frames = load_required_index_frames(tmp, primary, "000001.SH")

        cutoff = dates[119]
        self.assertEqual(pd.to_datetime(frames["000001.SH"]["date"]).max(), cutoff)
        self.assertEqual(pd.to_datetime(frames["000300.SH"]["date"]).max(), cutoff)

    def test_build_market_structure_as_of_ignores_future_inputs(self):
        panels = _panels(285)
        cutoff = panels.close.index[279]
        frames = {
            "000001.SH": _index_frame(panels.close.index),
            "000300.SH": _index_frame(panels.close.index, 3800.0),
            "000852.SH": _index_frame(panels.close.index, 6100.0),
            ALL_A_INDEX_SYMBOL: _index_frame(panels.close.index, 15000.0),
        }
        as_of_structure = build_market_structure("000001.SH", frames, panels, as_of=cutoff)
        prefix_panels = StockMarketPanels(
            close=panels.close.loc[:cutoff], amount=panels.amount.loc[:cutoff], metadata=panels.metadata,
        )
        prefix_frames = {symbol: frame[pd.to_datetime(frame["date"]) <= cutoff] for symbol, frame in frames.items()}
        prefix_structure = build_market_structure("000001.SH", prefix_frames, prefix_panels)

        self.assertEqual(as_of_structure["date"], cutoff.strftime("%Y-%m-%d"))
        self.assertEqual(as_of_structure["market_structure"], prefix_structure["market_structure"])
        self.assertLessEqual(
            max(pd.to_datetime(row["trade_date"]) for row in as_of_structure["index_history"]), cutoff,
        )

    def test_weekly_metric_is_stable_when_only_future_week_is_appended(self):
        dates = pd.date_range("2024-01-02", periods=180, freq="B")
        frame = _index_frame(dates)
        as_of = _index_metric("测试", "TEST", frame.iloc[:175])
        same_as_of = _index_metric("测试", "TEST", frame.iloc[:175].copy())
        self.assertEqual(as_of["weekly_trend"], same_as_of["weekly_trend"])
        self.assertEqual(as_of["date"], same_as_of["date"])
        expected_10d = frame.iloc[174]["close"] / frame.iloc[164]["close"] - 1.0
        self.assertAlmostEqual(as_of["return_10d"], expected_10d)

    def test_unfinished_week_is_not_used_by_weekly_metric(self):
        dates = pd.bdate_range("2024-01-01", periods=180)
        frame = _index_frame(dates)
        monday_positions = [idx for idx, value in enumerate(dates) if value.weekday() == 0 and idx > 150]
        monday = monday_positions[0]
        monday_metric = _index_metric("测试", "TEST", frame.iloc[: monday + 1])
        prior_friday_metric = _index_metric("测试", "TEST", frame.iloc[:monday])
        self.assertEqual(monday_metric["weekly_trend"], prior_friday_metric["weekly_trend"])

    def test_report_and_snapshot_clip_future_kline_payload_to_structure_date(self):
        panels = _panels()
        cutoff = panels.close.index[-11]
        structure = _structure(
            StockMarketPanels(
                close=panels.close.loc[:cutoff], amount=panels.amount.loc[:cutoff], metadata=panels.metadata,
            )
        )
        full_frame = _index_frame(panels.close.index)
        features = full_frame.rename(columns={"date": "trade_date"})
        features["trade_date"] = pd.to_datetime(features["trade_date"]).dt.strftime("%Y-%m-%d")
        for window in (20, 60, 120):
            features[f"ma{window}"] = features["close"].rolling(window, min_periods=1).mean()
        predictions = pd.DataFrame(
            {
                "trade_date": features["trade_date"], "market_score": 50.0,
                "predicted_opportunity_score": 50.0, "predicted_risk_score": 50.0,
                "environment_signal": "neutral", "model": "rule_v1",
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.html"
            snapshot = Path(tmp) / "snapshot.html"
            generate_index_forecast_report(
                features, predictions, output, "000001.SH", "上证指数", 5, {}, structure,
                technical_index_frames={"000001.SH": full_frame},
            )
            generate_market_structure_snapshot_report(
                structure, snapshot, "000001.SH", "上证指数", "facts.md",
            )
            html = output.read_text(encoding="utf-8")
            snapshot_html = snapshot.read_text(encoding="utf-8")

        self.assertIn(cutoff.strftime("%Y-%m-%d"), html)
        self.assertNotIn(panels.close.index[-1].strftime("%Y-%m-%d"), html)
        self.assertIn("历史 as-of 快照", snapshot_html)
        self.assertIn("facts.md", snapshot_html)

    def test_industry_is_equal_weighted_before_style_basket(self):
        index = pd.date_range("2026-01-01", periods=2)
        daily = pd.DataFrame(
            {"A1": [0.0, 0.10], "A2": [0.0, 0.10], "A3": [0.0, 0.10], "B1": [0.0, -0.10]},
            index=index,
        )
        basket = _basket_daily_return(daily, {"行业A": ["A1", "A2", "A3"], "行业B": ["B1"]})
        self.assertAlmostEqual(basket.iloc[-1], 0.0)

    def test_regime_is_mutually_exclusive_and_priority_is_fixed(self):
        base = dict(
            risk_repairing=False, breadth_state="neutral", tail_level="medium",
            value_state="neutral", growth_state="neutral", securities_state="neutral",
            small_return_20d=None, hs300_return_20d=0.01, all_a_return_20d=0.0,
            bank_return_20d=0.01, securities_return_20d=0.0,
            consumer_state="neutral", consumer_relative_20d=0.0,
            consumer_advance_ratio=0.5, amount_ratio_20=1.0,
        )
        self.assertEqual(classify_market_style_regime(**base), "mixed_rotation")
        overlapping = dict(base, risk_repairing=True, breadth_state="weak", tail_level="extreme")
        self.assertEqual(classify_market_style_regime(**overlapping), "panic_recovery")
        broad = dict(base, breadth_state="strong", tail_level="low", value_state="strong", growth_state="strong")
        self.assertEqual(classify_market_style_regime(**broad), "broad_strength")
        self.assertEqual(set(REGIME_NAMES), {
            "broad_strength", "value_defensive", "growth_risk_on", "consumer_recovery",
            "mixed_rotation", "broad_weakness", "panic_recovery",
        })

    def test_summary_output_json_and_legacy_forecast_are_compatible(self):
        structure = _structure(_panels())
        self.assertIn(structure["market_structure"]["style"]["regime_name"], structure["market_structure"]["headline"])
        self.assertIn("trend", structure["market_structure"])
        self.assertIn("breadth", structure["market_structure"])
        self.assertIn("risk", structure["market_structure"])
        self.assertIn("divergence", structure["market_structure"])
        with tempfile.TemporaryDirectory() as tmp:
            config = {"output": {"statistics_dir": tmp}}
            paths = save_market_structure_outputs(config, "000001.SH", structure)
            loaded = json.loads(paths["json"].read_text(encoding="utf-8"))
            self.assertEqual(loaded["date"], structure["date"])
            self.assertTrue(paths["breadth"].exists())

        dates = pd.date_range("2025-01-01", periods=40, freq="B").strftime("%Y-%m-%d")
        features = pd.DataFrame({"trade_date": dates, "close": np.arange(40) + 3000.0})
        baseline = build_rule_forecast(features, horizon=5)
        attached_output = attach_market_structure_columns(features, structure)
        self.assertIn("market_style_regime", attached_output.columns)
        self.assertNotIn("market_style_regime", baseline.columns)
        pd.testing.assert_series_equal(baseline["market_score"], build_rule_forecast(features, horizon=5)["market_score"])

    def test_market_structure_is_horizon_independent(self):
        panels = _panels()
        first = _structure(panels)
        second = _structure(panels)
        first["legacy_forecast"] = {"horizon": 1, "signal": "neutral"}
        second["legacy_forecast"] = {"horizon": 20, "signal": "conservative"}
        self.assertEqual(first["market_structure"], second["market_structure"])
        self.assertEqual(first["breadth"], second["breadth"])
        self.assertEqual(first["styles"], second["styles"])

    def test_switchable_index_payload_contains_timeframe_technical_indicators(self):
        dates = pd.date_range("2025-01-02", periods=90, freq="B")
        frame = _index_frame(dates)
        payload = _technical_kline_payload(frame, "000001.SH")
        daily = payload["1d"]
        self.assertEqual(len(daily["dates"]), 90)
        self.assertEqual(len(daily["volume"]), 90)
        self.assertEqual(daily["volume"][-1], float(frame["volume"].iloc[-1]))
        self.assertTrue(any(value is not None for value in daily["kdj_k"]))
        self.assertTrue(any(value is not None for value in daily["macd_dif"]))
        self.assertTrue(any(value is not None for value in daily["macd_hist"]))

    def test_report_keeps_existing_echarts_shell_and_folds_legacy_section(self):
        panels = _panels()
        structure = _structure(panels)
        frame = _index_frame(panels.close.index[-80:])
        features = frame.rename(columns={"date": "trade_date"})
        features["trade_date"] = pd.to_datetime(features["trade_date"]).dt.strftime("%Y-%m-%d")
        for window in (20, 60, 120):
            features[f"ma{window}"] = features["close"].rolling(window, min_periods=1).mean()
        for column in ("kdj_k", "kdj_d", "kdj_j", "macd_dif_norm", "macd_dea_norm", "macd_hist_norm", "ad_slope_5", "ad_slope_20", "nhnl_slope_5", "nhnl_slope_20"):
            features[column] = 0.0
        predictions = pd.DataFrame(
            {
                "trade_date": features["trade_date"], "market_score": 50.0,
                "predicted_opportunity_score": 50.0, "predicted_risk_score": 50.0,
                "environment_signal": "neutral", "signal": "neutral", "model": "rule_v1",
            }
        )
        chinext = _index_frame(panels.close.index[-80:], 2100.0)
        structure["indices"]["创业板指"] = _index_metric("创业板指", "399006.SZ", chinext)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.html"
            generate_index_forecast_report(
                features, predictions, output, "000001.SH", "上证指数", 5, {}, structure,
                technical_index_frames={"399006.SZ": chinext},
            )
            html = output.read_text(encoding="utf-8")
        self.assertIn("上证指数与市场结构分析", html)
        self.assertIn("市场广度", html)
        self.assertIn("实验性预测诊断", html)
        self.assertIn("旧模型失效警告", html)
        self.assertNotIn("策略实际收益与旧环境过滤", html)
        self.assertIn("window._MARKET_STRUCTURE", html)
        self.assertIn("window._TECHNICAL_INDEX_KLINES", html)
        self.assertIn("创业板指（399006.SZ）", html)
        self.assertIn("<th>10日</th>", html)
        self.assertIn("switchForecastIndex", html)
        self.assertIn("指数K线与手动画线", html)
        self.assertIn("自动结构线显示已关闭", html)
        self.assertIn("forecast-kline-toolbar", html)
        self.assertIn("forecast-manual-btn", html)
        self.assertIn("setForecastManualTool", html)
        self.assertIn("forecastManualUndo", html)
        self.assertIn("forecastManualClear", html)
        self.assertNotIn('class="structure-filter" data-kind="horizontal"', html)
        self.assertIn("成交额", html)
        self.assertIn('id="forecast-index-indicator"', html)
        self.assertIn("switchForecastIndicator", html)
        self.assertIn("forecastVolumeOption", html)
        self.assertIn("forecastKdjOption", html)
        self.assertIn("forecastMacdOption", html)
        self.assertNotIn('id="forecast-index-volume"', html)
        self.assertNotIn('id="forecast-index-technical"', html)
        self.assertIn("主要指数区间强度对比", html)
        self.assertIn("switchIndexCompareWindow", html)
        self.assertIn('data-window="120"', html)
        self.assertIn("csi500_index", html)
        self.assertIn("csi1000_index", html)
        self.assertIn("csi2000_index", html)
        self.assertIn('id="structure-index-ranking"', html)
        self.assertNotIn("各指数统一归一化为1000", html)
        self.assertIn("全市场成交与流动性", html)
        self.assertIn("同花顺平均股价指数", html)
        self.assertNotIn("全A等权（合成）", html)
        self.assertIn("breadth-metric-grid", html)
        self.assertIn("breadth-metric-detail", html)
        self.assertIn("标准化A/D（当日/5日/20日）", html)
        self.assertIn("A/D EMA10", html)
        self.assertIn("累计A/D EMA10", html)
        self.assertIn("累计A/D EMA20", html)
        self.assertIn("'MA20上方':false", html)
        self.assertIn("'累计A/D EMA10':false", html)
        self.assertIn("normalized_ad_ema10", html)
        self.assertIn("ad_line_ema10", html)
        self.assertIn("ad_line_ema20", html)
        self.assertIn("breadth-ad-chart", html)
        self.assertIn("当日个股涨跌幅分布", html)
        self.assertIn('id="structure-return-distribution"', html)
        self.assertIn("return_distribution_counts", html)
        self.assertIn("股票数量", html)
        self.assertIn("优先使用同花顺行业/风格代理指数缓存", html)
        self.assertIn("适合做风格温度计", html)
        self.assertIn("建议维护专门股票池", html)
        self.assertNotIn("优先于KDJ和MACD；分母仅含当日有效股票", html)
        self.assertNotIn("标准化 A/D =（上涨家数－下跌家数）/（上涨家数＋下跌家数）。", html)
        self.assertIn("echarts", html.lower())
        self.assertIn("Apache Software Foundation", html)
        self.assertIn("assets.pyecharts.org", html)
        self.assertIn("当前行业分类用于历史回溯", html)
        self.assertNotIn("react", html.lower())
        self.assertEqual(_fmt_ratio_pct(0.684), "68.4%")
        self.assertNotIn("+68.4%", html)

        payload = _market_chart_payload(structure)
        self.assertIn("normalized_ad_ema10", payload)
        self.assertIn("ad_line_ema10", payload)
        self.assertIn("ad_line_ema20", payload)
        self.assertTrue(any(value is not None for value in payload["normalized_ad_ema10"]))
        self.assertTrue(any(value is not None for value in payload["ad_line_ema10"]))
        self.assertTrue(any(value is not None for value in payload["ad_line_ema20"]))
        self.assertEqual(payload["return_distribution_labels"][0], "<-10%")
        self.assertEqual(payload["return_distribution_labels"][-1], ">10%")
        self.assertEqual(sum(payload["return_distribution_counts"]), int(structure["breadth"]["latest"]["valid_stock_count"]))

    def test_cli_keeps_forecast_and_adds_structure_alias(self):
        result = CliRunner().invoke(index_group, ["--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("forecast", result.output)
        self.assertIn("structure", result.output)
        self.assertIn("structure-brief", result.output)
        path = _market_structure_alias_path({"output": {"reports_dir": "/tmp/reports"}}, "000001.SH")
        self.assertEqual(path.name, "000001.SH_market_structure.html")

    def test_market_structure_archive_copies_daily_report_and_llm_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {"output": {"reports_dir": str(root / "reports")}}
            source = root / "source"
            source.mkdir()
            report = source / "report.html"
            alias = source / "alias.html"
            structure_json = source / "structure.json"
            llm_html = source / "summary.html"
            llm_md = source / "summary.md"
            facts = source / "facts.md"
            prompt = source / "prompt.md"
            for path in (report, alias, structure_json, llm_html, llm_md, facts, prompt):
                path.write_text(path.name, encoding="utf-8")

            archived = _archive_market_structure_outputs(
                config,
                symbol="000001.SH",
                horizon=5,
                report_date="2026-07-14",
                report_path=report,
                alias_path=alias,
                structure_paths={"json": structure_json},
                llm_paths=SimpleNamespace(html=llm_html, summary=llm_md, facts=facts, prompt=prompt),
                llm_call_status="succeeded",
            )

            archive_dir = root / "reports" / "index_forecast" / "archive" / "2026-07-14"
            self.assertEqual(archived["report"], archive_dir / "000001.SH_h5_market_structure.html")
            self.assertTrue((archive_dir / "000001.SH_h5_market_structure.html").exists())
            self.assertTrue((archive_dir / "000001.SH_h5_market_structure.json").exists())
            self.assertTrue((archive_dir / "000001.SH_h5_llm_summary.html").exists())
            self.assertTrue((archive_dir / "000001.SH_h5_llm_input.md").exists())
            manifest = json.loads(archived["manifest"].read_text(encoding="utf-8"))
            self.assertEqual(manifest["report_date"], "2026-07-14")
            self.assertEqual(manifest["llm_call"]["status"], "succeeded")
            records = {item["key"]: item for item in manifest["artifacts"]}
            self.assertEqual(records["llm_summary_html"]["status"], "written")
            self.assertEqual(len(records["llm_summary_html"]["sha256"]), 64)
            self.assertGreater(records["llm_summary_html"]["bytes"], 0)

    def test_v2_archive_uses_dated_names_and_local_historical_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {"output": {"reports_dir": str(root / "reports")}}
            report_root = root / "reports" / "index_forecast"
            source = root / "source"
            report_root.mkdir(parents=True)
            source.mkdir()
            report = root / "custom-output" / "000001.SH_h5.html"
            report.parent.mkdir()
            alias = report_root / "000001.SH_market_structure.html"
            structure_json = source / "structure.json"
            indices = source / "indices.csv"
            breadth = source / "breadth.csv"
            styles = source / "styles.csv"
            style_history = source / "style_history.csv"
            layered = source / "layered.csv"
            llm_html = source / "000001.SH_h5_market_structure_llm_summary.html"
            llm_md = source / "000001.SH_h5_market_structure_llm_summary.md"
            facts = source / "000001.SH_h5_market_structure_llm_input.md"
            prompt = source / "000001.SH_h5_market_structure_llm_prompt.md"
            archive_prefix = "000001.SH_h5_2026-07-14"
            summary_href = relative_href(report, llm_html)
            facts_href = relative_href(report, facts)
            html = (
                "<header><div class='sub'>as-of</div>"
                "<div class=\"top-actions\">"
                f"<a href='{summary_href}'>summary</a>"
                f"<a href='{facts_href}'>facts</a>"
                "</div></header><main>snapshot</main>"
            )
            report.write_text(html, encoding="utf-8")
            alias.write_text(html, encoding="utf-8")
            for path in (
                structure_json,
                indices,
                breadth,
                styles,
                style_history,
                layered,
                llm_html,
                llm_md,
                facts,
                prompt,
            ):
                path.write_text(path.name, encoding="utf-8")
            metadata = {
                "schema_version": "market_structure_v2",
                "algorithm_version": "2.0.0",
                "config_hash": "c" * 64,
                "data_hash": "d" * 64,
                "source_freshness": {"stock_universe": {"status": "fresh"}},
                "point_in_time": {"future_rows_used": False},
            }

            archived = _archive_market_structure_outputs(
                config,
                symbol="000001.SH",
                horizon=5,
                report_date="2026-07-14",
                report_path=report,
                alias_path=alias,
                structure_paths={
                    "json": structure_json,
                    "indices": indices,
                    "breadth": breadth,
                    "styles": styles,
                    "style_history": style_history,
                    "layered_breadth": layered,
                },
                llm_paths=SimpleNamespace(
                    html=llm_html,
                    summary=llm_md,
                    facts=facts,
                    prompt=prompt,
                ),
                llm_call_status="succeeded",
                structure_metadata=metadata,
            )

            archive_dir = (
                report_root / "archive" / "market_structure_v2" / "2026-07-14"
            )
            expected_names = {
                "report": f"{archive_prefix}_market_structure.html",
                "alias": "000001.SH_2026-07-14_market_structure.html",
                "json": f"{archive_prefix}_market_structure.json",
                "indices": f"{archive_prefix}_market_structure_indices.csv",
                "breadth": f"{archive_prefix}_market_structure_breadth.csv",
                "styles": f"{archive_prefix}_market_structure_styles.csv",
                "style_history": f"{archive_prefix}_market_structure_style_history.csv",
                "layered_breadth": f"{archive_prefix}_market_structure_layered_breadth.csv",
                "llm_facts": f"{archive_prefix}_llm_input.md",
                "llm_prompt": f"{archive_prefix}_llm_prompt.md",
                "llm_summary": f"{archive_prefix}_llm_summary.md",
                "llm_summary_html": f"{archive_prefix}_llm_summary.html",
            }
            for key, filename in expected_names.items():
                self.assertEqual(archived[key], archive_dir / filename)
                self.assertIn("2026-07-14", archived[key].name)
                self.assertTrue(archived[key].exists())

            archived_html = archived["report"].read_text(encoding="utf-8")
            self.assertIn(f"href='{archive_prefix}_llm_summary.html'", archived_html)
            self.assertIn(f"href='{archive_prefix}_llm_input.md'", archived_html)
            self.assertNotIn("archive/market_structure_v2", archived_html)
            for filename in (
                f"{archive_prefix}_llm_summary.html",
                f"{archive_prefix}_llm_input.md",
            ):
                self.assertTrue((archive_dir / filename).exists())
                self.assertIn(f"href='{filename}'", archived_html)

            latest_html = report.read_text(encoding="utf-8")
            latest_summary_href = relative_href(
                report,
                archive_dir / f"{archive_prefix}_llm_summary.html",
            )
            latest_facts_href = relative_href(
                report,
                archive_dir / f"{archive_prefix}_llm_input.md",
            )
            self.assertIn(f"href='{latest_summary_href}'", latest_html)
            self.assertIn(f"href='{latest_facts_href}'", latest_html)
            self.assertEqual(
                (report.parent / latest_summary_href).resolve(),
                archived["llm_summary_html"].resolve(),
            )
            self.assertTrue((report.parent / latest_summary_href).resolve().exists())

            alias_html = alias.read_text(encoding="utf-8")
            alias_summary_href = relative_href(
                alias,
                archive_dir / f"{archive_prefix}_llm_summary.html",
            )
            self.assertIn(f"href='{alias_summary_href}'", alias_html)
            self.assertEqual(
                (alias.parent / alias_summary_href).resolve(),
                archived["llm_summary_html"].resolve(),
            )
            self.assertTrue((alias.parent / alias_summary_href).resolve().exists())

            manifest = json.loads(archived["manifest"].read_text(encoding="utf-8"))
            self.assertIn("2026-07-14", archived["manifest"].name)
            self.assertEqual(manifest["schema_version"], "market_structure_v2")
            self.assertEqual(manifest["algorithm_version"], "2.0.0")
            self.assertEqual(manifest["config_hash"], "c" * 64)
            self.assertEqual(manifest["data_hash"], "d" * 64)
            self.assertFalse(manifest["point_in_time"]["future_rows_used"])
            records = {item["key"]: item for item in manifest["artifacts"]}
            report_digest = hashlib.sha256(archived["report"].read_bytes()).hexdigest()
            self.assertEqual(records["report"]["sha256"], report_digest)

    def test_v2_same_day_llm_retry_adds_links_without_replacing_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {"output": {"reports_dir": str(root / "reports")}}
            report_root = root / "reports" / "index_forecast"
            source = root / "source"
            custom = root / "custom"
            report_root.mkdir(parents=True)
            source.mkdir()
            custom.mkdir()
            report = custom / "market.html"
            alias = report_root / "000001.SH_market_structure.html"
            facts = source / "facts.md"
            prompt = source / "prompt.md"
            summary = source / "summary.md"
            summary_html = source / "summary.html"
            for path in (facts, prompt, summary, summary_html):
                path.write_text(path.name, encoding="utf-8")
            metadata = {
                "schema_version": "market_structure_v2",
                "algorithm_version": "2.0.0",
                "config_hash": "c" * 64,
                "data_hash": "d" * 64,
                "source_freshness": {},
                "point_in_time": {"future_rows_used": False},
            }
            llm_paths = SimpleNamespace(
                html=summary_html,
                summary=summary,
                facts=facts,
                prompt=prompt,
            )

            first_html = (
                "<header><div class='sub'>2026-07-14</div></header>"
                "<main>FIRST SNAPSHOT BODY</main>"
            )
            report.write_text(first_html, encoding="utf-8")
            alias.write_text(first_html, encoding="utf-8")
            kwargs = dict(
                config=config,
                symbol="000001.SH",
                horizon=5,
                report_date="2026-07-14",
                report_path=report,
                alias_path=alias,
                structure_paths={},
                llm_paths=llm_paths,
                structure_metadata=metadata,
            )
            _archive_market_structure_outputs(
                **kwargs,
                llm_call_status="failed",
                llm_error_type="TimeoutError",
            )

            summary_href = relative_href(report, summary_html)
            facts_href = relative_href(report, facts)
            second_html = (
                "<header><div class='sub'>2026-07-14</div>"
                "<div class=\"top-actions\">"
                f"<a href='{summary_href}'>summary</a>"
                f"<a href='{facts_href}'>facts</a>"
                "</div></header><main>SECOND BODY MUST NOT REPLACE</main>"
            )
            report.write_text(second_html, encoding="utf-8")
            alias.write_text(second_html, encoding="utf-8")
            archived = _archive_market_structure_outputs(
                **kwargs,
                llm_call_status="succeeded",
            )

            archived_html = archived["report"].read_text(encoding="utf-8")
            self.assertIn("FIRST SNAPSHOT BODY", archived_html)
            self.assertNotIn("SECOND BODY MUST NOT REPLACE", archived_html)
            self.assertEqual(archived_html.count("top-actions"), 1)
            for key in ("llm_summary_html", "llm_facts"):
                target = archived[key]
                self.assertIn(f"href='{target.name}'", archived_html)
                self.assertTrue((archived["report"].parent / target.name).exists())

            latest_summary_href = relative_href(report, archived["llm_summary_html"])
            self.assertIn(
                f"href='{latest_summary_href}'",
                report.read_text(encoding="utf-8"),
            )
            self.assertTrue((report.parent / latest_summary_href).resolve().exists())

            manifest = json.loads(archived["manifest"].read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["attempts"]), 2)
            records = {item["key"]: item for item in manifest["artifacts"]}
            self.assertEqual(records["report"]["status"], "preserved_links_updated")

    def test_v2_failed_same_day_retry_restores_links_to_existing_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {"output": {"reports_dir": str(root / "reports")}}
            report_root = root / "reports" / "index_forecast"
            source = root / "source"
            custom = root / "custom"
            report_root.mkdir(parents=True)
            source.mkdir()
            custom.mkdir()
            report = custom / "market.html"
            alias = report_root / "000001.SH_market_structure.html"
            facts = source / "facts.md"
            prompt = source / "prompt.md"
            summary = source / "summary.md"
            summary_html = source / "summary.html"
            facts.write_text("first facts", encoding="utf-8")
            prompt.write_text("first prompt", encoding="utf-8")
            summary.write_text("ARCHIVED SUCCESS SUMMARY", encoding="utf-8")
            summary_html.write_text(
                "<html>ARCHIVED SUCCESS SUMMARY HTML</html>",
                encoding="utf-8",
            )
            metadata = {
                "schema_version": "market_structure_v2",
                "algorithm_version": "2.0.0",
                "config_hash": "c" * 64,
                "data_hash": "d" * 64,
                "source_freshness": {},
                "point_in_time": {"future_rows_used": False},
            }
            llm_paths = SimpleNamespace(
                html=summary_html,
                summary=summary,
                facts=facts,
                prompt=prompt,
            )
            summary_href = relative_href(report, summary_html)
            facts_href = relative_href(report, facts)
            successful_html = (
                "<header><div class='sub'>2026-07-14</div>"
                "<div class=\"top-actions\">"
                f"<a href='{summary_href}'>summary</a>"
                f"<a href='{facts_href}'>facts</a>"
                "</div></header><main>SUCCESSFUL SNAPSHOT</main>"
            )
            report.write_text(successful_html, encoding="utf-8")
            alias.write_text(successful_html, encoding="utf-8")
            kwargs = dict(
                config=config,
                symbol="000001.SH",
                horizon=5,
                report_date="2026-07-14",
                report_path=report,
                alias_path=alias,
                structure_paths={},
                llm_paths=llm_paths,
                structure_metadata=metadata,
            )
            first_archive = _archive_market_structure_outputs(
                **kwargs,
                llm_call_status="succeeded",
            )
            archived_summary_html = first_archive["llm_summary_html"]
            archived_summary_md = first_archive["llm_summary"]
            archived_html_before = archived_summary_html.read_bytes()
            archived_md_before = archived_summary_md.read_bytes()

            # Simulate stale root-level output left behind when the retry API
            # fails.  These bytes must never enter the preserved daily archive.
            summary_html.write_text("STALE ROOT HTML", encoding="utf-8")
            summary.write_text("STALE ROOT MARKDOWN", encoding="utf-8")
            failed_html = (
                "<header><div class='sub'>2026-07-14</div></header>"
                "<main>FAILED RETRY CURRENT SNAPSHOT</main>"
            )
            report.write_text(failed_html, encoding="utf-8")
            alias.write_text(failed_html, encoding="utf-8")
            archived = _archive_market_structure_outputs(
                **kwargs,
                llm_call_status="failed",
                llm_error_type="TimeoutError",
            )

            self.assertEqual(archived_summary_html.read_bytes(), archived_html_before)
            self.assertEqual(archived_summary_md.read_bytes(), archived_md_before)
            self.assertNotIn("STALE ROOT", archived_summary_html.read_text(encoding="utf-8"))
            self.assertNotIn("STALE ROOT", archived_summary_md.read_text(encoding="utf-8"))

            for latest_report in (report, alias):
                latest_html = latest_report.read_text(encoding="utf-8")
                self.assertIn("FAILED RETRY CURRENT SNAPSHOT", latest_html)
                self.assertEqual(latest_html.count("top-actions"), 1)
                summary_archive_href = relative_href(
                    latest_report,
                    archived["llm_summary_html"],
                )
                facts_archive_href = relative_href(
                    latest_report,
                    archived["llm_facts"],
                )
                self.assertIn(f"href='{summary_archive_href}'", latest_html)
                self.assertIn(f"href='{facts_archive_href}'", latest_html)
                self.assertEqual(
                    (latest_report.parent / summary_archive_href).resolve(),
                    archived_summary_html.resolve(),
                )
                self.assertTrue(
                    (latest_report.parent / summary_archive_href).resolve().exists()
                )

            archived_report_html = archived["report"].read_text(encoding="utf-8")
            self.assertIn("SUCCESSFUL SNAPSHOT", archived_report_html)
            self.assertNotIn("FAILED RETRY CURRENT SNAPSHOT", archived_report_html)
            manifest = json.loads(archived["manifest"].read_text(encoding="utf-8"))
            self.assertEqual(manifest["llm_call"]["status"], "failed")
            records = {item["key"]: item for item in manifest["artifacts"]}
            self.assertEqual(records["llm_summary"]["status"], "preserved_previous")
            self.assertEqual(
                records["llm_summary_html"]["status"],
                "preserved_previous",
            )

    def test_daily_archive_rejects_frozen_400_day_target(self):
        config = {
            "output": {
                "reports_dir": "/tmp/reports",
            }
        }
        with self.assertRaisesRegex(RuntimeError, "400日"):
            _market_structure_archive_dir(
                config,
                "_history_400_2026-07-14",
                "market_structure_v2",
            )

    def test_archive_without_key_does_not_copy_stale_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {"output": {"reports_dir": str(root / "reports")}}
            source = root / "source"
            source.mkdir()
            report = source / "report.html"
            alias = source / "alias.html"
            facts = source / "facts.md"
            prompt = source / "prompt.md"
            stale_summary = source / "summary.md"
            stale_html = source / "summary.html"
            for path, content in (
                (report, "current report"),
                (alias, "current alias"),
                (facts, "current facts"),
                (prompt, "current prompt"),
                (stale_summary, "previous trading day summary"),
                (stale_html, "previous trading day html"),
            ):
                path.write_text(content, encoding="utf-8")

            archived = _archive_market_structure_outputs(
                config,
                symbol="000001.SH",
                horizon=5,
                report_date="2026-07-15",
                report_path=report,
                alias_path=alias,
                structure_paths={},
                llm_paths=SimpleNamespace(
                    html=stale_html,
                    summary=stale_summary,
                    facts=facts,
                    prompt=prompt,
                ),
                llm_call_status="skipped_no_key",
            )

            archive_dir = root / "reports" / "index_forecast" / "archive" / "2026-07-15"
            self.assertTrue((archive_dir / "000001.SH_h5_llm_input.md").exists())
            self.assertTrue((archive_dir / "000001.SH_h5_llm_prompt.md").exists())
            self.assertFalse((archive_dir / "000001.SH_h5_llm_summary.md").exists())
            self.assertFalse((archive_dir / "000001.SH_h5_llm_summary.html").exists())
            manifest = json.loads(archived["manifest"].read_text(encoding="utf-8"))
            records = {item["key"]: item for item in manifest["artifacts"]}
            self.assertEqual(manifest["llm_call"]["status"], "skipped_no_key")
            self.assertEqual(records["llm_facts"]["status"], "written")
            self.assertEqual(records["llm_summary"]["status"], "skipped_llm_not_succeeded")
            self.assertIsNone(records["llm_summary"]["sha256"])

    def test_archive_after_api_failure_keeps_facts_but_not_old_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {"output": {"reports_dir": str(root / "reports")}}
            source = root / "source"
            source.mkdir()
            report = source / "report.html"
            alias = source / "alias.html"
            facts = source / "facts.md"
            prompt = source / "prompt.md"
            stale_summary = source / "summary.md"
            stale_html = source / "summary.html"
            for path in (report, alias, facts, prompt, stale_summary, stale_html):
                path.write_text(path.name, encoding="utf-8")

            archived = _archive_market_structure_outputs(
                config,
                symbol="000001.SH",
                horizon=5,
                report_date="2026-07-16",
                report_path=report,
                alias_path=alias,
                structure_paths={},
                llm_paths=SimpleNamespace(
                    html=stale_html,
                    summary=stale_summary,
                    facts=facts,
                    prompt=prompt,
                ),
                llm_call_status="failed",
                llm_error_type="TimeoutError",
            )

            archive_dir = root / "reports" / "index_forecast" / "archive" / "2026-07-16"
            self.assertTrue((archive_dir / "000001.SH_h5_llm_input.md").exists())
            self.assertTrue((archive_dir / "000001.SH_h5_llm_prompt.md").exists())
            self.assertFalse((archive_dir / "000001.SH_h5_llm_summary.md").exists())
            manifest = json.loads(archived["manifest"].read_text(encoding="utf-8"))
            self.assertEqual(manifest["llm_call"]["status"], "failed")
            self.assertEqual(manifest["llm_call"]["error_type"], "TimeoutError")

    def test_repeated_archive_preserves_existing_snapshot_and_records_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {"output": {"reports_dir": str(root / "reports")}}
            source = root / "source"
            source.mkdir()
            report = source / "report.html"
            alias = source / "alias.html"
            structure_json = source / "structure.json"
            report.write_text("first report", encoding="utf-8")
            alias.write_text("first alias", encoding="utf-8")
            structure_json.write_text("first json", encoding="utf-8")
            kwargs = dict(
                config=config,
                symbol="000001.SH",
                horizon=5,
                report_date="2026-07-14",
                report_path=report,
                alias_path=alias,
                structure_paths={"json": structure_json},
                llm_paths=None,
                llm_call_status="not_called",
            )
            _archive_market_structure_outputs(**kwargs)
            report.write_text("second report", encoding="utf-8")
            alias.write_text("second alias", encoding="utf-8")
            structure_json.write_text("second json", encoding="utf-8")
            archived = _archive_market_structure_outputs(**kwargs)

            archive_dir = root / "reports" / "index_forecast" / "archive" / "2026-07-14"
            archived_report = archive_dir / "000001.SH_h5_market_structure.html"
            self.assertEqual(archived_report.read_text(encoding="utf-8"), "first report")
            manifest = json.loads(archived["manifest"].read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["attempts"]), 2)
            records = {item["key"]: item for item in manifest["artifacts"]}
            self.assertEqual(records["report"]["status"], "preserved")
            self.assertEqual(records["report"]["bytes"], len("first report"))


if __name__ == "__main__":
    unittest.main()
