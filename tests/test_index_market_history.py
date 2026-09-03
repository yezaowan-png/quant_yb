import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.index_market_history import (
    FROZEN_MARKET_STRUCTURE_HISTORY_DIR,
    _assert_not_frozen_history_target,
    _compact_structure,
    _coerce_bool_series,
    _forward_path_extreme,
    _forward_path_max_drawdown,
    _rolling_percentile_at_end,
    _write_text,
    add_forward_outcomes,
    add_research_temperature_candidates,
    build_event_episodes,
    build_feature_correlations,
    build_future_outcomes_long,
    build_group_event_study,
    build_industry_validation,
    build_state_transitions,
    build_style_validation,
    write_history_audit_tables,
    write_history_reproducibility_manifest,
)
from data.market_benchmark import MARKET_BENCHMARK_SYMBOL
from scripts.backfill_market_structure_history import _history_batch_paths


class IndexMarketHistoryTest(unittest.TestCase):
    def test_frozen_history_guard_resolves_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frozen = root / FROZEN_MARKET_STRUCTURE_HISTORY_DIR
            frozen.mkdir()
            alias = root / "history_alias"
            alias.symlink_to(frozen, target_is_directory=True)

            with self.assertRaisesRegex(PermissionError, "历史审计目录已冻结"):
                _assert_not_frozen_history_target(alias / "snapshot.json")
            with self.assertRaises(PermissionError):
                _write_text(alias / "snapshot.json", "must not be written", overwrite=True)
            self.assertFalse((frozen / "snapshot.json").exists())

    def test_frozen_history_batch_table_and_manifest_writers_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            frozen = Path(tmp) / FROZEN_MARKET_STRUCTURE_HISTORY_DIR
            frozen.mkdir()

            with self.assertRaises(PermissionError):
                write_history_audit_tables(pd.DataFrame(), frozen)
            with self.assertRaises(PermissionError):
                write_history_reproducibility_manifest(
                    frozen,
                    {"data": {}, "output": {}},
                    Path(tmp),
                    {},
                )
            self.assertEqual(list(frozen.iterdir()), [])

    def test_backfill_rejects_the_completed_400_day_batch_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {"output": {"reports_dir": str(Path(tmp) / "reports")}}
            with self.assertRaises(PermissionError):
                _history_batch_paths(
                    config,
                    days=400,
                    last_trade_date=pd.Timestamp("2026-07-14"),
                )

    def test_compact_structure_omits_repeated_histories(self):
        structure = {
            "date": "2026-07-14",
            "index_history": [{"trade_date": "2026-07-14"}],
            "breadth": {"latest": {"advance_ratio": 0.5}, "history": [{"trade_date": "2026-07-14"}]},
            "style_history": [{"trade_date": "2026-07-14"}],
            "indices": {},
            "styles": {},
        }
        compact = _compact_structure(structure, 1050)
        self.assertEqual(compact["index_history"], [])
        self.assertEqual(compact["breadth"]["history"], [])
        self.assertEqual(compact["style_history"], [])
        self.assertTrue(compact["archive_metadata"]["history_arrays_omitted"])
        self.assertFalse(compact["archive_metadata"]["llm_called_for_snapshot"])

    def test_forward_outcomes_are_offline_and_last_rows_are_unmatured(self):
        dates = pd.bdate_range("2026-01-01", periods=30)
        close = pd.DataFrame(
            {"A.SH": np.arange(30) + 10.0, "B.SZ": np.arange(30) + 20.0}, index=dates,
        )
        index_frame = pd.DataFrame({"date": dates, "close": np.arange(30) + 100.0})
        snapshots = pd.DataFrame({"trade_date": dates[-10:].strftime("%Y-%m-%d")})
        result = add_forward_outcomes(
            snapshots,
            close,
            {"000001.SH": index_frame, "000300.SH": index_frame, MARKET_BENCHMARK_SYMBOL: index_frame},
            horizons=(1, 5),
        )
        self.assertTrue(result.iloc[0]["future_mature_5d"])
        self.assertFalse(result.iloc[-1]["future_mature_1d"])
        self.assertGreater(result.iloc[0]["future_stock_median_return_5d"], 0)
        self.assertTrue(pd.isna(result.iloc[-1]["future_all_a_return_1d"]))

    def test_history_percentile_uses_recent_rows_not_recent_non_null_values(self):
        values = pd.Series([100.0] * 10 + [np.nan] * 10 + [1.0])
        # The last 11 rows contain one valid observation; a row-window therefore
        # does not meet min_periods, unlike dropna-before-tail behavior.
        self.assertIsNone(_rolling_percentile_at_end(values, window=11, min_periods=2))
        self.assertAlmostEqual(_rolling_percentile_at_end(values, window=11, min_periods=1), 1.0 / 11.0)

    def test_forward_max_drawdown_is_not_mae_from_signal(self):
        series = pd.Series([100.0, 120.0, 110.0, 115.0])
        drawdown = _forward_path_max_drawdown(series, 3)
        self.assertAlmostEqual(drawdown.iloc[0], 110.0 / 120.0 - 1.0)

    def test_forward_mae_and_mfe_include_signal_zero_baseline(self):
        rising = pd.Series([100.0, 110.0, 120.0])
        falling = pd.Series([100.0, 90.0, 80.0])
        self.assertEqual(_forward_path_extreme(rising, 2, "min").iloc[0], 0.0)
        self.assertAlmostEqual(_forward_path_extreme(rising, 2, "max").iloc[0], 0.20)
        self.assertAlmostEqual(_forward_path_extreme(falling, 2, "min").iloc[0], -0.20)
        self.assertEqual(_forward_path_extreme(falling, 2, "max").iloc[0], 0.0)

    def test_style_future_labels_handle_unmatured_all_nan_rows(self):
        dates = pd.bdate_range("2026-01-01", periods=12)
        snapshots = pd.DataFrame(
            {"trade_date": dates.strftime("%Y-%m-%d"), "style_leader_20d": ["权重价值"] * len(dates)}
        )
        style_keys = ("value", "securities", "growth", "consumer", "small_cap")
        for rank, key in enumerate(style_keys):
            snapshots[f"style_{key}_return_1d"] = 0.005 - rank * 0.001
            snapshots[f"style_{key}_strength"] = 100.0 - rank * 10.0
        close = pd.DataFrame({"A.SH": 100.0 + np.arange(len(dates))}, index=dates)
        index_frame = pd.DataFrame({"date": dates, "close": 100.0 + np.arange(len(dates))})
        result = add_forward_outcomes(
            snapshots,
            close,
            {"000001.SH": index_frame, "000300.SH": index_frame, MARKET_BENCHMARK_SYMBOL: index_frame},
            horizons=(1, 5),
        )
        self.assertEqual(result.iloc[0]["future_style_best_5d"], "value")
        self.assertTrue(pd.isna(result.iloc[-1]["future_style_best_1d"]))
        self.assertAlmostEqual(result.iloc[0]["future_style_strength_rank_ic_5d"], 1.0)
        validation = build_style_validation(result)
        five_day = validation[(validation["dimension"] == "all_styles") & (validation["horizon"] == 5)].iloc[0]
        self.assertEqual(five_day["leader_hit_n"], len(dates) - 5)
        self.assertEqual(five_day["leader_hit_rate"], 1.0)

    def test_industry_spread_requires_three_valid_indexes_on_both_sides(self):
        dates = pd.bdate_range("2026-01-01", periods=12)
        snapshots = pd.DataFrame(
            {
                "trade_date": [dates[0].strftime("%Y-%m-%d")],
                "industry_strong_1_symbol": ["S1.TI"],
                "industry_strong_2_symbol": ["S2.TI"],
                "industry_strong_3_symbol": ["S3.TI"],
                "industry_weak_1_symbol": ["W1.TI"],
                "industry_weak_2_symbol": ["W2.TI"],
                "industry_weak_3_symbol": ["W3.TI"],
            }
        )
        close = pd.DataFrame({"A.SH": 100.0 + np.arange(len(dates))}, index=dates)
        index_frame = pd.DataFrame({"date": dates, "close": 100.0 + np.arange(len(dates))})
        ths_frames = {
            symbol: pd.DataFrame({"date": dates, "close": 100.0 + np.arange(len(dates)) + offset})
            for offset, symbol in enumerate(("S1.TI", "S2.TI", "S3.TI", "W1.TI", "W2.TI"))
        }
        ths_frames["W3.TI"] = pd.DataFrame({"date": dates[:5], "close": 100.0 + np.arange(5)})
        result = add_forward_outcomes(
            snapshots,
            close,
            {"000001.SH": index_frame, "000300.SH": index_frame, MARKET_BENCHMARK_SYMBOL: index_frame},
            horizons=(5,),
            ths_index_frames=ths_frames,
        )
        self.assertEqual(result.iloc[0]["future_industry_strong3_valid_count_5d"], 3)
        self.assertEqual(result.iloc[0]["future_industry_weak3_valid_count_5d"], 2)
        self.assertTrue(pd.isna(result.iloc[0]["future_industry_weak3_return_5d"]))
        self.assertTrue(pd.isna(result.iloc[0]["future_industry_strong_minus_weak_5d"]))
        validation = build_industry_validation(result)
        self.assertEqual(validation.loc[validation["horizon"] == 5, "sample_count"].iloc[0], 0)

    def test_bool_parser_and_event_studies_do_not_treat_false_strings_as_true(self):
        parsed = _coerce_bool_series(pd.Series(["False", "true", "0", "1", 0.0, 1.0, np.nan, "unknown"]))
        self.assertEqual(parsed.iloc[:6].tolist(), [False, True, False, True, False, True])
        self.assertTrue(pd.isna(parsed.iloc[6]))
        self.assertTrue(pd.isna(parsed.iloc[7]))
        panel = pd.DataFrame(
            {
                "state": ["same", "same"],
                "future_mature_1d": ["False", "True"],
                "future_all_a_return_1d": [9.9, 0.1],
                "future_all_a_min_return_1d": [-9.9, -0.1],
                "future_all_a_max_drawdown_1d": [-9.9, -0.05],
                "future_stock_median_return_1d": [9.9, 0.2],
            }
        )
        study = build_group_event_study(panel, ["state"]).iloc[0]
        self.assertEqual(study["all_a_return_1d_n"], 1)
        self.assertAlmostEqual(study["all_a_return_1d_mean"], 0.1)
        long = build_future_outcomes_long(panel)
        self.assertFalse(bool(long.iloc[0]["valid_label"]))

    def test_event_episodes_parse_boolean_strings_and_expose_maturity_counts(self):
        panel = pd.DataFrame(
            {
                "trade_date": ["2026-01-01", "2026-01-02", "2026-01-05"],
                "tail_pressure": ["low"] * 3,
                "risk_direction": ["stable"] * 3,
                "breadth_20d_state": ["neutral"] * 3,
                "research_icepoint_candidate_v1": ["False", "True", "True"],
                "research_overheat_candidate_v1": ["False"] * 3,
                "research_overheat_score_v1": [0] * 3,
                "research_icepoint_score_v1": [0, 4, 5],
                "future_mature_1d": ["True", "True", "False"],
                "future_mature_5d": ["False"] * 3,
                "future_all_a_return_1d": [0.0, 0.01, np.nan],
            }
        )
        episodes = build_event_episodes(panel)
        ice = episodes[episodes["event_type"] == "temperature_icepoint_v1"].iloc[0]
        self.assertEqual(ice["start_date"], "2026-01-02")
        self.assertEqual(ice["duration_days"], 2)
        self.assertTrue(ice["future_mature_1d"])
        self.assertEqual(ice["mature_sample_count_1d"], 1)
        self.assertEqual(ice["mature_sample_count_5d"], 0)

    def test_research_temperature_rules_are_predeclared_scores(self):
        hot = {
            "percentile_advance_ratio": 0.95,
            "percentile_pct_above_ma20": 0.95,
            "percentile_new_high_20_ratio": 0.95,
            "percentile_advance_gt_5_ratio": 0.95,
            "percentile_normalized_ad_5d": 0.95,
            "index_all_a_return_20d": 0.10,
        }
        cold = {
            "percentile_decline_gt_5_ratio": 0.95,
            "percentile_approximate_limit_down_ratio": 0.95,
            "percentile_new_low_20_ratio": 0.95,
            "percentile_cross_section_dispersion": 0.95,
            "percentile_market_realized_volatility_5d": 0.95,
            "percentile_advance_ratio": 0.05,
            "percentile_pct_above_ma20": 0.05,
        }
        result = add_research_temperature_candidates(pd.DataFrame([hot, cold]))
        self.assertTrue(result.iloc[0]["research_overheat_candidate_v1"])
        self.assertFalse(result.iloc[0]["research_icepoint_candidate_v1"])
        self.assertTrue(result.iloc[1]["research_icepoint_candidate_v1"])

    def test_audit_tables_are_written(self):
        panel = pd.DataFrame(
            {
                "trade_date": pd.bdate_range("2026-01-01", periods=12).strftime("%Y-%m-%d"),
                "tail_pressure": ["low"] * 6 + ["high"] * 6,
                "risk_direction": ["stable", "expanding"] * 6,
                "breadth_today_state": ["neutral"] * 12,
                "breadth_5d_state": ["neutral"] * 12,
                "breadth_20d_state": ["neutral"] * 12,
                "style_regime": ["rotation"] * 12,
                "research_overheat_candidate_v1": [False] * 12,
                "research_icepoint_candidate_v1": [False] * 12,
                "research_overheat_score_v1": [0] * 12,
                "research_icepoint_score_v1": [0] * 12,
                "breadth_advance_ratio": np.linspace(0.2, 0.8, 12),
                "future_all_a_return_1d": np.linspace(-0.01, 0.01, 12),
                "future_all_a_min_return_1d": np.linspace(-0.02, 0.0, 12),
                "future_stock_median_return_1d": np.linspace(-0.01, 0.01, 12),
                "future_mature_1d": [True] * 11 + [False],
            }
        )
        self.assertFalse(build_group_event_study(panel, ["tail_pressure"]).empty)
        self.assertFalse(build_state_transitions(panel, ["tail_pressure"]).empty)
        self.assertFalse(build_feature_correlations(panel).empty)
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_history_audit_tables(panel, Path(tmp))
            self.assertTrue(all(path.exists() for path in paths.values()))


if __name__ == "__main__":
    unittest.main()
