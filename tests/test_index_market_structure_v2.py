from __future__ import annotations

from functools import lru_cache
import ast
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from analysis.index_market_structure import ALL_A_INDEX_SYMBOL
from analysis.market_structure_state_v2 import (
    StateTracker,
    StateTrackerConfig,
    classify_concentration,
    classify_leadership_quality,
    classify_liquidity,
    classify_repair,
    classify_return_distribution,
)
from analysis.market_structure_v2 import (
    V2_MIN_PANEL_HISTORY_ROWS,
    _build_industry_daily_frames,
    _layer_row,
    _member_snapshot,
    _top_fraction_share,
    _top_n_share,
    build_concentration_analysis,
    build_market_structure_v2,
    build_return_distribution,
    build_source_freshness,
)
def _index_frame(dates: pd.DatetimeIndex, start: float) -> pd.DataFrame:
    position = np.arange(len(dates), dtype=float)
    close = start + position * 1.2 + np.sin(position / 5.0) * 5.0
    return pd.DataFrame(
        {
            "date": dates,
            "open": close - 2.0,
            "high": close + 6.0,
            "low": close - 6.0,
            "close": close,
            "volume": 1_000_000.0 + position * 100.0,
            "amount": 2_000_000.0 + position * 500.0,
        }
    )


def _breadth_history(dates: pd.DatetimeIndex) -> list[dict[str, object]]:
    count = len(dates)
    return pd.DataFrame(
        {
            "trade_date": dates.strftime("%Y-%m-%d"),
            "decline_gt_3_ratio": np.linspace(0.10, 0.02, count),
            "decline_gt_5_ratio": np.linspace(0.04, 0.01, count),
            "approximate_limit_down_ratio": np.linspace(0.02, 0.001, count),
            "new_low_20_ratio": np.linspace(0.20, 0.02, count),
            "pct_above_ma20": np.linspace(0.20, 0.80, count),
            "pct_above_ma50": np.linspace(0.20, 0.75, count),
            "normalized_ad": np.linspace(-0.50, 0.50, count),
            "cross_section_dispersion": np.linspace(0.04, 0.01, count),
            "market_realized_volatility_5d": np.linspace(0.04, 0.01, count),
            "decline_amount_ratio": np.linspace(0.70, 0.30, count),
            "advance_ratio": np.linspace(0.30, 0.70, count),
            "ad_slope_5": np.linspace(-0.10, 0.10, count),
            "new_low_20_change_5d": np.linspace(0.02, -0.02, count),
            "equal_weight_return_5d": np.linspace(-0.03, 0.03, count),
        }
    ).to_dict("records")


def _base_structure(dates: pd.DatetimeIndex, horizon: int) -> dict[str, object]:
    return {
        "market_structure": {
            "trend": {
                "large_cap_daily": "uptrend",
                "large_cap_weekly": "uptrend",
                "growth_daily": "mixed",
            }
        },
        "breadth": {"history": _breadth_history(dates)},
        "legacy_forecast": {"horizon": horizon, "signal": "neutral"},
        "data_quality_flags": [],
    }


@lru_cache(maxsize=1)
def _fixture_bundle() -> dict[str, object]:
    row_count = 225
    stock_count = 30
    dates = pd.bdate_range("2025-08-01", periods=row_count)
    cutoff = dates[-6]
    symbols = [f"{index:06d}.SZ" for index in range(stock_count)]
    position = np.arange(row_count, dtype=float)
    close = pd.DataFrame(
        {
            symbol: (
                10.0
                + index * 0.10
                + position * (0.010 + (index % 7) * 0.0015)
                + np.sin(position / 7.0 + index) * 0.08
            )
            for index, symbol in enumerate(symbols)
        },
        index=dates,
    )
    amount = pd.DataFrame(
        {
            symbol: 1_000_000.0
            * (1.0 + index / 50.0)
            * (1.0 + 0.10 * np.sin(position / 10.0 + index))
            for index, symbol in enumerate(symbols)
        },
        index=dates,
    )
    # Future rows are deliberately extreme.  A correct as-of implementation
    # produces the same result as physically removing these rows.
    close.loc[dates[-5:], symbols[::2]] *= 1.8
    close.loc[dates[-5:], symbols[1::2]] *= 0.55
    amount.loc[dates[-5:]] *= 9.0
    metadata = pd.DataFrame(
        {
            "ts_code": symbols,
            "name": [f"测试股票{index}" for index in range(stock_count)],
            "industry": ["行业甲"] * 10 + ["行业乙"] * 10 + ["行业丙"] * 10,
            "market": ["主板"] * 20 + ["创业板"] * 5 + ["科创板"] * 5,
            "exchange": ["SZSE"] * stock_count,
        }
    )
    index_symbols = (
        "000016.SH",
        "000300.SH",
        "000905.SH",
        "000852.SH",
        "932000.CSI",
        "399006.SZ",
        "000688.SH",
        "399001.SZ",
        ALL_A_INDEX_SYMBOL,
    )
    index_frames = {
        symbol: _index_frame(dates, 2_000.0 + offset * 300.0)
        for offset, symbol in enumerate(index_symbols)
    }
    for frame in index_frames.values():
        frame.loc[frame["date"] > cutoff, "close"] *= 1.5

    member_groups = {
        "000016.SH": symbols[0:3],
        "000300.SH": symbols[3:7],
        "000905.SH": symbols[7:12],
        "000852.SH": symbols[12:18],
        "932000.CSI": symbols[18:25],
    }
    member_frames: dict[str, pd.DataFrame] = {}
    for code, members in member_groups.items():
        historical = pd.DataFrame(
            {
                "trade_date": [dates[40]] * len(members),
                "con_code": members,
                "weight": [100.0 / len(members)] * len(members),
            }
        )
        future = pd.DataFrame(
            {
                "trade_date": [dates[-1]],
                "con_code": [symbols[-1]],
                "weight": [100.0],
            }
        )
        member_frames[code] = pd.concat([historical, future], ignore_index=True)

    style_groups = {
        "权重价值": symbols[:10],
        "科技成长": symbols[10:20],
        "消费": symbols[20:],
    }
    industries = {
        "行业甲": symbols[:10],
        "行业乙": symbols[10:20],
        "行业丙": symbols[20:],
    }
    style_industries = {
        "权重价值": {"行业甲": symbols[:10]},
        "科技成长": {"行业乙": symbols[10:20]},
        "消费": {"行业丙": symbols[20:]},
    }
    full_panels = SimpleNamespace(close=close, amount=amount, metadata=metadata)
    prefix_panels = SimpleNamespace(
        close=close.loc[:cutoff].copy(),
        amount=amount.loc[:cutoff].copy(),
        metadata=metadata.copy(),
    )
    prefix_dates = dates[dates <= cutoff]
    prefix_indices = {
        symbol: frame[pd.to_datetime(frame["date"]) <= cutoff].reset_index(drop=True)
        for symbol, frame in index_frames.items()
    }
    common = {
        "primary_symbol": "000300.SH",
        "index_member_frames": member_frames,
        "ths_index_frames": {"881001.TI": _index_frame(dates, 1_200.0)},
        "style_symbol_groups": style_groups,
        "style_industry_groups": style_industries,
        "industry_groups": industries,
        "config": {"history_days": 60},
    }
    as_of_result = build_market_structure_v2(
        base_structure=_base_structure(prefix_dates, 1),
        panels=full_panels,
        index_frames=index_frames,
        as_of=cutoff,
        **common,
    )
    prefix_result = build_market_structure_v2(
        base_structure=_base_structure(prefix_dates, 20),
        panels=prefix_panels,
        index_frames=prefix_indices,
        as_of=cutoff,
        **common,
    )
    return {
        "dates": dates,
        "cutoff": cutoff,
        "symbols": symbols,
        "close": close,
        "amount": amount,
        "metadata": metadata,
        "index_frames": index_frames,
        "member_frames": member_frames,
        "member_groups": member_groups,
        "style_groups": style_groups,
        "industries": industries,
        "as_of_result": as_of_result,
        "prefix_result": prefix_result,
    }


def _recursive_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key))
            keys.update(_recursive_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_recursive_keys(child))
    return keys


class IndexMarketStructureV2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = _fixture_bundle()
        cls.result = cls.bundle["as_of_result"]

    def test_v2_01_all_calculations_respect_as_of_date(self):
        self.assertEqual(self.result["point_in_time"]["as_of"], self.bundle["cutoff"].strftime("%Y-%m-%d"))
        self.assertFalse(self.result["point_in_time"]["future_rows_used"])
        for layer in self.result["layered_breadth"].values():
            history = layer.get("history") or []
            if history:
                self.assertLessEqual(max(row["trade_date"] for row in history), self.result["point_in_time"]["as_of"])

    def test_v2_01b_layered_breadth_retains_six_month_observation_window(self):
        history = self.result["layered_breadth"]["全A"]["history"]
        self.assertEqual(len(history), 126)
        self.assertIn("advance_ratio", history[-1])
        self.assertIn("pct_above_ma5", history[-1])
        self.assertIn("pct_above_ma10", history[-1])

    def test_v2_02_future_truncation_keeps_historical_result_identical(self):
        self.assertEqual(self.result, self.bundle["prefix_result"])

    def test_v2_03_unmatured_future_fields_are_absent_from_fact_layer(self):
        keys = _recursive_keys(self.result)
        leaked = {
            key
            for key in keys
            if key.startswith("future_") and key != "future_rows_used"
        }
        self.assertEqual(leaked, set())
        self.assertFalse(any(key.startswith("label_") for key in keys))

    def test_v2_04_current_industry_backfill_has_pit_limitation_flag(self):
        self.assertIn("current_industry_classification_used_for_concentration_history", self.result["data_quality_flags"])
        self.assertFalse(self.result["point_in_time"]["industry_classification"])
        self.assertFalse(self.result["industry_structure"]["composition_point_in_time"])
        self.assertEqual(self.result["industry_structure"]["rank_basis"], "return_10d")
        strongest = self.result["industry_structure"]["strongest"]
        if len(strongest) >= 2:
            self.assertGreaterEqual(strongest[0]["return_10d"], strongest[1]["return_10d"])

    def test_v2_05_stale_data_yields_unknown_not_neutral(self):
        cutoff = self.bundle["cutoff"]
        close = self.bundle["close"].loc[:cutoff]
        amount = self.bundle["amount"].loc[:cutoff]
        distribution = build_return_distribution(
            close=close,
            amount=amount,
            source_freshness={"stock_universe": {"status": "stale"}},
            history_days=20,
        )
        self.assertEqual(distribution["state"], "unknown")
        self.assertEqual(distribution["latest"]["raw_state"], "unknown")

    def test_v2_06_each_source_has_independent_freshness(self):
        dates = self.bundle["dates"][-10:]
        close = self.bundle["close"].loc[dates]
        amount = self.bundle["amount"].loc[dates]
        fresh = _index_frame(dates, 3_000.0)
        stale = _index_frame(dates[:-1], 2_000.0)
        member_snapshot = pd.DataFrame(
            {
                "trade_date": [dates[-1]],
                "con_code": ["000001.SZ"],
                "weight": [100.0],
            }
        )
        result = build_source_freshness(
            close=close,
            amount=amount,
            metadata=self.bundle["metadata"],
            index_frames={"000300.SH": fresh, "000016.SH": stale},
            index_member_frames={"000016.SH": member_snapshot},
            ths_index_frames={"STYLE.TI": fresh, "INDUSTRY.TI": stale},
            style_proxy_symbols={"STYLE.TI"},
            industry_proxy_symbols={"INDUSTRY.TI"},
            as_of=dates[-1],
        )
        self.assertEqual(result["index:000300.SH"]["status"], "fresh")
        self.assertEqual(result["index:000016.SH"]["status"], "stale")
        self.assertEqual(result["index:000905.SH"]["status"], "missing")
        self.assertEqual(result["index_members:000016.SH"]["status"], "fresh")
        self.assertEqual(result["index_members:000905.SH"]["status"], "missing")
        self.assertEqual(result["style_proxies"]["status"], "fresh")
        self.assertEqual(result["industry_quotes"]["status"], "stale")

    def test_v2_07_snapshot_contains_schema_algorithm_config_and_data_hashes(self):
        self.assertEqual(self.result["schema_version"], "market_structure_v2")
        self.assertRegex(self.result["algorithm_version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(len(self.result["config_hash"]), 64)
        self.assertEqual(len(self.result["data_hash"]), 64)
        self.assertEqual(self.result["data_hash"], self.bundle["prefix_result"]["data_hash"])

    def test_v2_08_frozen_400_day_directory_cannot_be_targeted(self):
        # Compile the actual guard in isolation.  Importing cli.index_cli also
        # imports the full HTML renderer, which is unrelated to this contract.
        cli_path = Path(__file__).resolve().parents[1] / "cli" / "index_cli.py"
        tree = ast.parse(cli_path.read_text(encoding="utf-8"), filename=str(cli_path))
        guard = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_assert_market_structure_archive_target"
        )
        namespace = {
            "Path": Path,
            "FROZEN_MARKET_STRUCTURE_HISTORY_DIR": "_history_400_2026-07-14",
        }
        exec(compile(ast.Module(body=[guard], type_ignores=[]), str(cli_path), "exec"), namespace)
        with tempfile.TemporaryDirectory() as tmp:
            frozen = Path(tmp) / "_history_400_2026-07-14" / "reports" / "snapshot.json"
            with self.assertRaisesRegex(RuntimeError, "400日市场结构审计目录禁止写入"):
                namespace["_assert_market_structure_archive_target"](frozen)

    def test_v2_09_few_leaders_are_high_concentration(self):
        self.assertEqual(classify_concentration(0.90), "high_concentration")

    def test_v2_10_broad_participation_is_low_concentration(self):
        self.assertEqual(classify_concentration(0.30), "broad_participation")

    def test_v2_11_missing_historical_weights_are_marked_approximate(self):
        cutoff = self.bundle["cutoff"]
        concentration, flags = build_concentration_analysis(
            primary_symbol="000300.SH",
            close=self.bundle["close"].loc[:cutoff],
            amount=self.bundle["amount"].loc[:cutoff],
            industry_groups=self.bundle["industries"],
            index_member_frames={},
            source_freshness={"stock_universe": {"status": "fresh"}},
            history_days=20,
        )
        self.assertIn("weight_data_not_point_in_time", flags)
        self.assertFalse(concentration["latest"]["weight_point_in_time"])

    def test_v2_12_turnover_concentration_is_computed_correctly(self):
        values = pd.Series([70.0, 10.0, 10.0, 10.0])
        self.assertAlmostEqual(_top_fraction_share(values, fraction=0.25), 0.70)

    def test_v2_12b_liquidity_exposes_industry_turnover_share_changes(self):
        rows = self.result["liquidity_structure"]["industry_turnover_shares"]
        self.assertTrue(rows)
        self.assertTrue(
            {"industry", "amount_share", "amount_share_change_5d", "amount_share_change_20d", "amount_ratio_20d"}
            .issubset(rows[0])
        )

    def test_v2_12c_industry_aggregation_is_shared_and_numeric(self):
        cutoff = self.bundle["cutoff"]
        frames = _build_industry_daily_frames(
            close=self.bundle["close"].loc[:cutoff],
            amount=self.bundle["amount"].loc[:cutoff],
            industry_groups=self.bundle["industries"],
        )
        self.assertEqual(set(frames.industry_returns.columns), set(self.bundle["industries"]))
        self.assertEqual(set(frames.industry_amounts.columns), set(self.bundle["industries"]))
        self.assertTrue(all(pd.api.types.is_numeric_dtype(dtype) for dtype in frames.industry_returns.dtypes))
        self.assertTrue(all(pd.api.types.is_numeric_dtype(dtype) for dtype in frames.industry_amounts.dtypes))
        self.assertTrue(frames.industry_amount_ratios.iloc[19:].notna().any().any())

    def test_v2_12d_panel_window_keeps_required_warmup(self):
        self.assertGreaterEqual(V2_MIN_PANEL_HISTORY_ROWS, 816)
        self.assertGreaterEqual(V2_MIN_PANEL_HISTORY_ROWS, 252)

    def test_v2_13_layered_breadth_uses_correct_effective_denominator(self):
        row = self._layer_row_for_test(
            returns=[0.10, -0.10, 0.00],
            amounts=[100.0, 100.0, 100.0],
        )
        self.assertEqual(row["valid_count"], 3)
        self.assertAlmostEqual(row["advance_ratio"], 1.0 / 3.0)
        self.assertAlmostEqual(row["decline_ratio"], 1.0 / 3.0)

    def test_v2_14_suspended_and_missing_returns_are_excluded(self):
        row = self._layer_row_for_test(
            returns=[0.10, -0.10, np.nan, 0.02],
            amounts=[100.0, 0.0, 100.0, np.nan],
        )
        self.assertEqual(row["valid_count"], 1)
        self.assertEqual(row["advance_count"], 1)
        self.assertEqual(row["decline_count"], 0)

    def test_v2_14b_layered_breadth_exposes_requested_ma_and_breakout_windows(self):
        history = self.result["layered_breadth"]["全A"]["history"]
        latest = history[-1]
        expected = {
            "pct_above_ma5", "pct_above_ma10", "pct_above_ma20", "pct_above_ma60",
            "new_high_5_ratio", "new_low_5_ratio",
            "new_high_10_ratio", "new_low_10_ratio",
            "new_high_20_ratio", "new_low_20_ratio",
            "new_high_60_ratio", "new_low_60_ratio",
        }
        self.assertTrue(expected.issubset(latest))

    def test_v2_15_member_snapshot_deduplicates_components(self):
        date = pd.Timestamp("2026-07-01")
        frame = pd.DataFrame(
            {
                "trade_date": [date, date, date],
                "con_code": ["A.SZ", "A.SZ", "B.SZ"],
                "weight": [20.0, 30.0, 70.0],
            }
        )
        symbols, weights, snapshot_date = _member_snapshot(frame, date)
        self.assertEqual(symbols, ["A.SZ", "B.SZ"])
        self.assertAlmostEqual(float(weights.sum()), 1.0)
        self.assertEqual(snapshot_date, "2026-07-01")

    def test_v2_16_missing_pit_membership_lowers_confidence(self):
        layer = self.result["layered_breadth"]["创业板"]
        self.assertFalse(layer["composition_point_in_time"])
        self.assertTrue(layer["confidence_limited"])
        self.assertIn("composition_not_point_in_time:创业板", self.result["data_quality_flags"])

    def test_v2_17_csi500_1000_2000_layers_are_independent(self):
        layers = self.result["layered_breadth"]
        counts = [layers[name]["latest"]["member_count"] for name in ("中证500", "中证1000", "中证2000")]
        self.assertEqual(counts, [5, 6, 7])
        self.assertEqual(
            [layers[name]["symbol"] for name in ("中证500", "中证1000", "中证2000")],
            ["000905.SH", "000852.SH", "932000.CSI"],
        )

    def test_v2_18_state_duration_is_correct(self):
        dates = pd.bdate_range("2026-01-01", periods=3)
        tracked = StateTracker().track(dates, ["a", "a", "a"], dimension="test")
        self.assertEqual(tracked["duration_trading_days"], 3)
        self.assertEqual(tracked["state_start_date"], dates[0].strftime("%Y-%m-%d"))

    def test_v2_19_state_transition_date_is_correct(self):
        dates = pd.bdate_range("2026-01-01", periods=4)
        tracked = StateTracker().track(dates, ["a", "a", "b", "b"], dimension="test")
        self.assertEqual(tracked["state"], "b")
        self.assertEqual(tracked["previous_state"], "a")
        self.assertEqual(tracked["last_transition_date"], dates[3].strftime("%Y-%m-%d"))

    def test_v2_20_state_dead_zone_blocks_one_day_flip(self):
        dates = pd.bdate_range("2026-01-01", periods=4)
        tracked = StateTracker().track(dates, ["a", "a", "b", "a"], dimension="test")
        self.assertEqual(tracked["state"], "a")
        self.assertEqual(tracked["transition_count_20d"], 0)

    def test_v2_21_normal_state_requires_two_day_confirmation(self):
        dates = pd.bdate_range("2026-01-01", periods=4)
        tracked = StateTracker(StateTrackerConfig(min_confirm_days=2, min_hold_days=2)).track(
            dates, ["a", "a", "b", "b"], dimension="test"
        )
        self.assertEqual([row["state"] for row in tracked["history"]], ["a", "a", "a", "b"])

    def test_v2_22_extreme_event_can_switch_immediately(self):
        dates = pd.bdate_range("2026-01-01", periods=3)
        tracked = StateTracker(
            StateTrackerConfig(min_confirm_days=2, min_hold_days=5, extreme_states=("panic",))
        ).track(dates, ["normal", "normal", "panic"], dimension="test")
        self.assertEqual(tracked["state"], "panic")
        self.assertTrue(tracked["history"][-1]["transitioned"])

    def test_v2_23_alternating_raw_state_does_not_churn(self):
        dates = pd.bdate_range("2026-01-01", periods=20)
        raw = ["a" if index % 2 == 0 else "b" for index in range(20)]
        tracked = StateTracker(StateTrackerConfig(min_confirm_days=2, min_hold_days=2)).track(
            dates, raw, dimension="test"
        )
        self.assertEqual(tracked["transition_count_20d"], 0)
        self.assertEqual(tracked["stability"], "stable")

    def test_v2_24_index_up_but_internal_weakness_is_narrow(self):
        state = classify_leadership_quality(
            {
                "return_20d": 0.05,
                "relative_strength_5d": 0.01,
                "relative_strength_20d": 0.02,
                "advance_ratio": 0.35,
                "pct_above_ma20": 0.40,
                "top5_positive_contribution_share": 0.75,
                "breadth_change_5d": 0.0,
            }
        )
        self.assertEqual(state, "narrow")

    def test_v2_25_synchronized_component_strength_is_broad(self):
        state = classify_leadership_quality(
            {
                "return_20d": 0.05,
                "relative_strength_5d": 0.01,
                "relative_strength_20d": 0.02,
                "advance_ratio": 0.75,
                "pct_above_ma20": 0.70,
                "top5_positive_contribution_share": 0.30,
                "breadth_change_5d": 0.05,
            }
        )
        self.assertEqual(state, "broad")

    def test_v2_26_high_relative_strength_with_falling_breadth_deteriorates(self):
        state = classify_leadership_quality(
            {
                "return_20d": 0.05,
                "relative_strength_5d": 0.01,
                "relative_strength_20d": 0.04,
                "advance_ratio": 0.60,
                "pct_above_ma20": 0.65,
                "top5_positive_contribution_share": 0.35,
                "breadth_change_5d": -0.15,
            }
        )
        self.assertEqual(state, "deteriorating")

    def test_v2_27_top_five_contribution_share_is_correct(self):
        returns = pd.Series([0.30, 0.25, 0.20, 0.15, 0.05, 0.05])
        self.assertAlmostEqual(_top_n_share(returns, 5, positive_only=True), 0.95)

    def test_v2_28_cross_section_quantiles_are_correct(self):
        cutoff = self.bundle["cutoff"]
        close = self.bundle["close"].loc[:cutoff]
        amount = self.bundle["amount"].loc[:cutoff]
        returns = (close.iloc[-1] / close.iloc[-2] - 1.0).where(amount.iloc[-1].gt(0)).dropna()
        expected = returns.quantile([0.10, 0.25, 0.50, 0.75, 0.90])
        latest = self.result["return_distribution"]["latest"]
        for quantile, key in ((0.10, "q10"), (0.25, "q25"), (0.50, "median"), (0.75, "q75"), (0.90, "q90")):
            self.assertAlmostEqual(latest[key], expected.loc[quantile])

    def test_v2_29_broad_rally_is_classified(self):
        state = classify_return_distribution(
            {"q10": 0.002, "median": 0.012, "q90": 0.035, "up_ratio": 0.75, "std": 0.02}
        )
        self.assertEqual(state, "broad_rally")

    def test_v2_30_narrow_rally_is_classified(self):
        state = classify_return_distribution(
            {"q10": -0.010, "median": 0.001, "q90": 0.035, "up_ratio": 0.48, "std": 0.02}
        )
        self.assertEqual(state, "narrow_rally")

    def test_v2_31_polarized_distribution_is_classified(self):
        state = classify_return_distribution(
            {"q10": -0.024, "median": 0.005, "q90": 0.040, "up_ratio": 0.50, "std": 0.03}
        )
        self.assertEqual(state, "polarized")

    def test_v2_32_advance_and_decline_turnover_are_partitioned_correctly(self):
        cutoff = self.bundle["cutoff"]
        close = self.bundle["close"].loc[:cutoff]
        amount = self.bundle["amount"].loc[:cutoff]
        daily = close.iloc[-1] / close.iloc[-2] - 1.0
        expected_up = float(amount.iloc[-1].where(daily > 0).sum())
        expected_down = float(amount.iloc[-1].where(daily < 0).sum())
        latest = self.result["liquidity_structure"]["latest"]
        self.assertAlmostEqual(latest["advance_amount"], expected_up)
        self.assertAlmostEqual(latest["decline_amount"], expected_down)

    def test_v2_32b_liquidity_exposes_turnover_structure_ratios(self):
        cutoff = self.bundle["cutoff"]
        close = self.bundle["close"].loc[:cutoff]
        amount = self.bundle["amount"].loc[:cutoff]
        latest = self.result["liquidity_structure"]["latest"]
        total = amount.where(amount.gt(0)).sum(axis=1, min_count=1)
        self.assertAlmostEqual(latest["amount_ratio_5d"], total.iloc[-1] / total.rolling(5, min_periods=5).mean().iloc[-1])
        self.assertAlmostEqual(latest["amount_ratio_20d"], total.iloc[-1] / total.rolling(20, min_periods=20).mean().iloc[-1])
        daily = close.pct_change(fill_method=None).iloc[-1]
        traded = amount.iloc[-1].gt(0) & amount.iloc[-1].notna()
        returns = daily.where(traded).dropna()
        amounts = amount.iloc[-1].where(traded).reindex(returns.index).dropna()
        returns = returns.reindex(amounts.index)
        count = max(1, int(np.ceil(len(returns) * 0.10)))
        expected_gainers = amounts.reindex(returns.nlargest(count).index).sum() / amounts.sum()
        expected_losers = amounts.reindex(returns.nsmallest(count).index).sum() / amounts.sum()
        self.assertAlmostEqual(latest["top_10pct_gainer_amount_share"], expected_gainers)
        self.assertAlmostEqual(latest["top_10pct_loser_amount_share"], expected_losers)
        self.assertEqual(latest["top_10pct_gainer_count"], count)

    def test_v2_32c_liquidity_exposes_weight_and_theme_turnover_migration(self):
        liquidity = self.result["liquidity_structure"]
        rows = liquidity["turnover_migration"]
        self.assertTrue(rows)
        self.assertTrue({"bucket", "name", "amount_share", "amount_share_change_5d", "amount_share_change_20d"}.issubset(rows[0]))
        names = {row["name"] for row in rows}
        self.assertTrue({"沪深300", "中证1000", "中证2000"}.issubset(names))

    def test_v2_33_selling_expansion_is_classified(self):
        state = classify_liquidity(
            {
                "amount_ratio_20d": 1.30,
                "advance_amount_ratio": 0.30,
                "decline_amount_ratio": 0.70,
                "top_10pct_turnover_share": 0.35,
                "equal_weight_return_1d": -0.02,
            }
        )
        self.assertEqual(state, "selling_expansion")

    def test_v2_34_concentrated_expansion_is_classified(self):
        state = classify_liquidity(
            {
                "amount_ratio_20d": 1.30,
                "advance_amount_ratio": 0.60,
                "decline_amount_ratio": 0.40,
                "top_10pct_turnover_share": 0.60,
                "equal_weight_return_1d": 0.01,
            }
        )
        self.assertEqual(state, "concentrated_expansion")

    def test_v2_35_panic_expanding_is_classified(self):
        self.assertEqual(classify_repair(self._repair_row(risk_score=75, risk_change_5d=6)), "panic_expanding")

    def test_v2_36_initial_rebound_is_classified(self):
        row = self._repair_row(
            risk_score=50,
            risk_change_5d=-5,
            advance_ratio=0.65,
            equal_weight_return_5d=0.01,
        )
        self.assertEqual(classify_repair(row), "initial_rebound")

    def test_v2_37_breadth_repair_is_classified(self):
        row = self._repair_row(
            risk_score=40,
            risk_change_5d=0,
            ad_slope_5d=0.10,
            new_low_change_5d=-0.10,
            pct_above_ma20_change_5d=0.10,
        )
        self.assertEqual(classify_repair(row), "breadth_repair")

    def test_v2_38_trend_repair_is_classified(self):
        row = self._repair_row(
            risk_score=30,
            risk_change_5d=0,
            ad_slope_5d=0.0,
            new_low_change_5d=0.0,
            pct_above_ma20=0.65,
            pct_above_ma20_change_5d=0.10,
        )
        self.assertEqual(classify_repair(row), "trend_repair")

    def test_v2_39_failed_rebound_is_classified(self):
        row = self._repair_row(
            risk_score=50,
            risk_change_5d=2,
            advance_ratio=0.30,
            ad_slope_5d=-0.10,
            new_low_change_5d=0.10,
            pct_above_ma20=0.25,
            pct_above_ma20_change_5d=-0.10,
            equal_weight_return_5d=-0.04,
        )
        self.assertEqual(classify_repair(row), "failed_rebound")

    @staticmethod
    def _repair_row(**overrides: float) -> dict[str, float]:
        row = {
            "risk_score": 45.0,
            "risk_change_5d": 0.0,
            "advance_ratio": 0.50,
            "ad_slope_5d": 0.0,
            "new_low_change_5d": 0.0,
            "pct_above_ma20": 0.45,
            "pct_above_ma20_change_5d": 0.0,
            "equal_weight_return_5d": 0.0,
        }
        row.update(overrides)
        return row

    @staticmethod
    def _layer_row_for_test(returns: list[float], amounts: list[float]) -> dict[str, object]:
        dates = pd.bdate_range("2026-01-01", periods=2)
        symbols = [f"S{index}" for index in range(len(returns))]
        prior = pd.Series(10.0, index=symbols)
        latest = prior * (1.0 + pd.Series(returns, index=symbols, dtype="float64"))
        close = pd.DataFrame([prior, latest], index=dates)
        amount = pd.DataFrame(
            [pd.Series(100.0, index=symbols), pd.Series(amounts, index=symbols, dtype="float64")],
            index=dates,
        )
        daily = close.pct_change(fill_method=None)
        baseline = pd.DataFrame(9.0, index=dates, columns=symbols)
        high = pd.DataFrame(11.0, index=dates, columns=symbols)
        low = pd.DataFrame(9.0, index=dates, columns=symbols)
        return _layer_row(
            date=dates[-1],
            symbols=symbols,
            close=close,
            amount=amount,
            daily=daily,
            ma5=baseline,
            ma10=baseline,
            ma20=baseline,
            ma60=baseline,
            ma200=baseline,
            high5=high,
            low5=low,
            high10=high,
            low10=low,
            high20=high,
            low20=low,
            high60=high,
            low60=low,
            total_amount=amount.sum(axis=1, min_count=1),
        )


if __name__ == "__main__":
    unittest.main()
