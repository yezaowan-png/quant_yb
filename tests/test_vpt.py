from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from click.testing import CliRunner

from analysis.vpt import VPTConfig, analyze_vpt, analyze_vpt_history, prepare_vpt_frame, save_vpt_scan
from cli.shell import _execute_pipeline
from main import cli


def _base_rows(periods: int = 25) -> tuple[list[dict], pd.DatetimeIndex]:
    dates = pd.bdate_range("2026-01-02", periods=periods + 30)
    rows = []
    for index in range(periods):
        close = 10.0 + index * 0.02
        rows.append(
            {
                "date": dates[index].strftime("%Y%m%d"),
                "open": close - 0.02,
                "high": close + 0.08,
                "low": close - 0.08,
                "close": close,
                "volume": 100.0,
                "amount": close * 100.0,
            }
        )
    return rows, dates


def _healthy_frame() -> pd.DataFrame:
    rows, dates = _base_rows()
    rows.append(
        {
            "date": dates[25].strftime("%Y%m%d"),
            "open": 10.45,
            "high": 11.15,
            "low": 10.40,
            "close": 11.00,
            "volume": 220.0,
            "amount": 2420.0,
        }
    )
    post = [
        (11.25, 150.0),
        (11.50, 160.0),
        (11.35, 70.0),
        (11.25, 65.0),
        (11.60, 150.0),
        (11.85, 160.0),
        (11.70, 65.0),
        (12.00, 165.0),
        (12.20, 170.0),
    ]
    previous = 11.00
    for offset, (close, volume) in enumerate(post, start=26):
        rows.append(
            {
                "date": dates[offset].strftime("%Y%m%d"),
                "open": previous,
                "high": max(previous, close) + 0.08,
                "low": min(previous, close) - 0.08,
                "close": close,
                "volume": volume,
                "amount": close * volume,
            }
        )
        previous = close
    return pd.DataFrame(rows)


def _replace_post(frame: pd.DataFrame, closes: list[float], volumes: list[float]) -> pd.DataFrame:
    result = frame.iloc[:26].copy().to_dict("records")
    dates = pd.bdate_range(pd.Timestamp(frame.iloc[25]["date"]), periods=len(closes) + 1)[1:]
    previous = float(frame.iloc[25]["close"])
    for date, close, volume in zip(dates, closes, volumes):
        result.append(
            {
                "date": date.strftime("%Y%m%d"),
                "open": previous,
                "high": max(previous, close) + 0.06,
                "low": min(previous, close) - 0.06,
                "close": close,
                "volume": volume,
                "amount": close * volume,
            }
        )
        previous = close
    return pd.DataFrame(result)


class VPTIndicatorTests(unittest.TestCase):
    def test_healthy_demand_and_supply_contraction_qualifies(self):
        result = analyze_vpt(_healthy_frame())
        self.assertEqual(result["vpt_state"], "QUALIFIED")
        self.assertGreaterEqual(result["vpt_score"], 80)
        self.assertGreater(result["udvr"], 1.5)
        self.assertGreater(result["dv"], 0.3)
        self.assertLess(result["pvr"], 0.65)
        self.assertIn("PULLBACK_VOLUME_CONTRACTION", result["qualification_flags"])

    def test_valid_t0_starts_as_spike_detected(self):
        result = analyze_vpt(_healthy_frame().iloc[:26])
        self.assertEqual(result["vpt_state"], "SPIKE_DETECTED")
        self.assertFalse(result["structure_broken"])

    def test_early_fall_below_breakout_fails_event(self):
        frame = _replace_post(_healthy_frame(), [10.45, 10.35, 10.30], [120, 130, 140])
        result = analyze_vpt(frame)
        self.assertEqual(result["vpt_state"], "FAILED")
        self.assertTrue(result["breakout_failed_early"])
        self.assertIn("BREAKOUT_FAILED", result["failure_flags"])

    def test_effort_without_result_is_failed(self):
        rows, dates = _base_rows()
        rows.append(
            {
                "date": dates[25].strftime("%Y%m%d"),
                "open": 10.48,
                "high": 12.00,
                "low": 10.20,
                "close": 10.30,
                "volume": 320.0,
                "amount": 3296.0,
            }
        )
        result = analyze_vpt(pd.DataFrame(rows))
        self.assertEqual(result["vpt_state"], "FAILED")
        self.assertTrue(result["effort_no_result"])
        self.assertIn("EFFORT_NO_RESULT", result["failure_flags"])

    def test_volume_expanding_pullback_weakens_or_fails(self):
        frame = _replace_post(
            _healthy_frame(),
            [11.20, 11.45, 11.05, 10.72, 10.55, 10.40],
            [145, 155, 190, 200, 210, 220],
        )
        result = analyze_vpt(frame)
        self.assertIn(result["vpt_state"], {"WEAKENING", "FAILED"})
        self.assertTrue(result["supply_expansion"])
        self.assertIn("SUPPLY_EXPANSION", result["failure_flags"])

    def test_equal_up_down_volume_cannot_score_high(self):
        frame = _replace_post(
            _healthy_frame(),
            [11.20, 11.05, 11.25, 11.10, 11.30, 11.15],
            [100, 100, 100, 100, 100, 100],
        )
        result = analyze_vpt(frame)
        self.assertAlmostEqual(result["udvr"], 1.0)
        self.assertAlmostEqual(result["dv"], 0.0)
        self.assertLess(result["volume_structure_score"], 10)
        self.assertNotEqual(result["vpt_state"], "QUALIFIED")

    def test_low_volume_decline_is_not_a_healthy_trend(self):
        rows, dates = _base_rows()
        previous = float(rows[-1]["close"])
        for offset in range(25, 35):
            close = previous * 0.99
            rows.append(
                {
                    "date": dates[offset].strftime("%Y%m%d"),
                    "open": previous,
                    "high": previous + 0.03,
                    "low": close - 0.03,
                    "close": close,
                    "volume": 60.0,
                    "amount": close * 60.0,
                }
            )
            previous = close
        result = analyze_vpt(pd.DataFrame(rows))
        self.assertNotEqual(result["vpt_state"], "QUALIFIED")

    def test_t0_volume_does_not_pollute_udvr(self):
        frame = _replace_post(
            _healthy_frame(),
            [11.20, 11.05, 11.25, 11.10],
            [100, 100, 100, 100],
        )
        frame.loc[25, "volume"] = 1000.0
        result = analyze_vpt(frame)
        self.assertAlmostEqual(result["udvr"], 1.0)
        self.assertNotEqual(result["vpt_state"], "QUALIFIED")

    def test_zero_volume_bars_are_not_treated_as_trading_days(self):
        frame = _healthy_frame()
        frame.loc[10, "volume"] = 0
        prepared = prepare_vpt_frame(frame, VPTConfig())
        self.assertEqual(len(prepared), len(frame) - 1)
        self.assertTrue((prepared["volume"] > 0).all())

    def test_minimum_valid_spike_receives_low_nonzero_startup_credit(self):
        frame = _healthy_frame()
        frame.loc[25, "volume"] = 180.0
        result = analyze_vpt(frame)
        self.assertTrue(result["t0_valid"])
        self.assertGreaterEqual(result["startup_score"], 2.0)

    def test_resume_gap_spike_is_not_valid_t0(self):
        rows, dates = _base_rows()
        rows.append(
            {
                "date": (dates[24] + pd.Timedelta(days=30)).strftime("%Y%m%d"),
                "open": 10.48,
                "high": 11.20,
                "low": 10.40,
                "close": 11.00,
                "volume": 250.0,
                "amount": 2750.0,
            }
        )
        result = analyze_vpt(pd.DataFrame(rows))
        self.assertFalse(result["t0_valid"])
        self.assertEqual(result["vpt_state"], "FAILED")
        self.assertIn("RESUME_GAP_SPIKE", result["failure_flags"])

    def test_prefix_recalculation_is_future_invariant(self):
        frame = _healthy_frame()
        cutoff = 31
        prefix_result = analyze_vpt(frame.iloc[:cutoff])
        history = analyze_vpt_history(frame, days=len(frame))
        history_result = history[history["trade_date"] == prefix_result["trade_date"]].iloc[-1]
        for field in ("vpt_state", "vpt_score", "t0_date", "udvr", "dv", "pvr"):
            left = prefix_result[field]
            right = history_result[field]
            if isinstance(left, float):
                self.assertAlmostEqual(left, right)
            else:
                self.assertEqual(left, right)


class VPTIntegrationTests(unittest.TestCase):
    def test_scan_writes_snapshot_candidates_history_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            meta = root / "meta"
            cache.mkdir()
            meta.mkdir()
            _healthy_frame().assign(adj="qfq").to_csv(cache / "000001.SZ.csv", index=False)
            pd.DataFrame([{"ts_code": "000001.SZ", "name": "测试股票"}]).to_csv(meta / "stock_names.csv", index=False)
            config = {
                "data": {"cache_dir": str(cache), "meta_dir": str(meta), "stock_adj": "qfq"},
                "output": {
                    "signals_dir": str(root / "signals"),
                    "statistics_dir": str(root / "statistics"),
                    "reports_dir": str(root / "reports"),
                },
            }
            result = save_vpt_scan(config, symbols=["000001.SZ"], top=10, history_days=20)
            self.assertEqual(len(result.snapshot), 1)
            self.assertEqual(len(result.candidates), 1)
            for path in (result.snapshot_path, result.candidates_path, result.history_path, result.html_path):
                self.assertTrue(path.exists(), path)
            report = result.html_path.read_text(encoding="utf-8")
            self.assertIn("VPT-01 放量启动", report)
            self.assertIn("状态变化时间线", report)
            self.assertIn("data-sort=\"vpt_score\"", report)

    def test_st_and_stale_symbols_remain_auditable_but_not_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            meta = root / "meta"
            cache.mkdir()
            meta.mkdir()
            current = _healthy_frame().assign(adj="qfq")
            current.to_csv(cache / "000001.SZ.csv", index=False)
            current.to_csv(cache / "000002.SZ.csv", index=False)
            current.iloc[:-1].to_csv(cache / "000003.SZ.csv", index=False)
            pd.DataFrame(
                [
                    {"ts_code": "000001.SZ", "name": "正常股票"},
                    {"ts_code": "000002.SZ", "name": "ST测试"},
                    {"ts_code": "000003.SZ", "name": "停牌测试"},
                ]
            ).to_csv(meta / "stock_names.csv", index=False)
            config = {
                "data": {"cache_dir": str(cache), "meta_dir": str(meta), "stock_adj": "qfq"},
                "output": {
                    "signals_dir": str(root / "signals"),
                    "statistics_dir": str(root / "statistics"),
                    "reports_dir": str(root / "reports"),
                },
            }
            result = save_vpt_scan(config, top=10, history_days=5)
            self.assertEqual(set(result.snapshot["ts_code"]), {"000001.SZ", "000002.SZ", "000003.SZ"})
            self.assertEqual(result.candidates["ts_code"].tolist(), ["000001.SZ"])
            st_row = result.snapshot.set_index("ts_code").loc["000002.SZ"]
            stale_row = result.snapshot.set_index("ts_code").loc["000003.SZ"]
            self.assertEqual(st_row["exclusion_reason"], "ST_EXCLUDED")
            self.assertFalse(bool(stale_row["is_current_date"]))

    def test_cli_command_is_registered(self):
        result = CliRunner().invoke(cli, ["stats", "vpt", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--min-score", result.output)
        self.assertIn("--history-days", result.output)
        self.assertNotIn("FAILED", result.output)

    def test_repl_routes_vpt_options(self):
        with patch("cli.stats_cli.run_vpt_scan") as run:
            result = _execute_pipeline(
                {},
                "stats vpt --pool AI --trade-date 20260904 --top 25 --min-score 70 --state QUALIFIED --history-days 30",
            )
        self.assertTrue(result)
        run.assert_called_once_with(
            {},
            pool="AI",
            pool_mode="any",
            trade_date="20260904",
            lookback=250,
            top=25,
            min_score=70.0,
            state="QUALIFIED",
            history_days=30,
        )


if __name__ == "__main__":
    unittest.main()
