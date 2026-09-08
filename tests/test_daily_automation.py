from __future__ import annotations

import hashlib
import inspect
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from click.testing import CliRunner

from cli.index_cli import index_group, run_index_forecast, run_index_ths
from cli.shell import _execute_pipeline
from cli.stats_cli import sync_stock_kline_pages
from main import cli
from scripts.verify_daily_market_structure import (
    DailyArchiveVerificationError,
    verify_daily_market_structure_archive,
)
from scripts.verify_daily_market_data import _report_date, _report_freshness_summary


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_complete_archive(root: Path, *, llm_status: str = "succeeded") -> dict:
    reports = root / "reports"
    statistics = root / "statistics"
    structure_dir = statistics / "index_forecast"
    structure_dir.mkdir(parents=True)
    (structure_dir / "market_structure_000001.SH.json").write_text(
        json.dumps(
            {
                "date": "2026-07-14",
                "schema_version": "market_structure_v2",
                "data_hash": "fixture-data-hash",
            }
        ),
        encoding="utf-8",
    )

    archive_dir = (
        reports
        / "index_forecast"
        / "archive"
        / "market_structure_v2"
        / "2026-07-14"
    )
    archive_dir.mkdir(parents=True)
    prefix = "000001.SH_h5_2026-07-14"
    files = {
        "report": archive_dir / f"{prefix}_market_structure.html",
        "json": archive_dir / f"{prefix}_market_structure.json",
        "llm_summary": archive_dir / f"{prefix}_llm_summary.md",
        "llm_summary_html": archive_dir / f"{prefix}_llm_summary.html",
    }
    for key, path in files.items():
        path.write_text(f"fixture:{key}", encoding="utf-8")
    manifest = {
        "schema_version": "market_structure_v2",
        "report_date": "2026-07-14",
        "symbol": "000001.SH",
        "horizon": 5,
        "llm_call": {"status": llm_status, "succeeded": llm_status == "succeeded"},
        "artifacts": [
            {
                "key": key,
                "path": str(path),
                "status": "written",
                "sha256": _digest(path),
                "bytes": path.stat().st_size,
            }
            for key, path in files.items()
        ],
    }
    manifest_path = archive_dir / f"{prefix}_archive_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return {
        "config": {
            "output": {
                "reports_dir": str(reports),
                "statistics_dir": str(statistics),
            }
        },
        "manifest": manifest_path,
        "files": files,
    }


class PipelineFailurePropagationTests(unittest.TestCase):
    def test_non_ignored_command_failure_returns_false_and_stops(self):
        with patch("cli.shell._dispatch_command", side_effect=RuntimeError("fixture failure")) as dispatch:
            result = _execute_pipeline({}, "bad; never-runs")
        self.assertFalse(result)
        self.assertEqual(dispatch.call_count, 1)

    def test_ignored_command_failure_continues_and_returns_true(self):
        calls: list[list[str]] = []

        def dispatch(_config, parts):
            calls.append(parts)
            if parts[0] == "ignored-failure":
                raise RuntimeError("fixture failure")
            return True

        with patch("cli.shell._dispatch_command", side_effect=dispatch):
            result = _execute_pipeline({}, "!ignored-failure; success")
        self.assertTrue(result)
        self.assertEqual(calls, [["ignored-failure"], ["success"]])

    def test_pipeline_reports_each_command_duration(self):
        runner = CliRunner()
        with patch("cli.shell._dispatch_command", return_value=True):
            result = runner.invoke(cli, ["run", "success"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("耗时:", result.output)

    def test_main_run_command_returns_nonzero_when_pipeline_fails(self):
        runner = CliRunner()
        with patch("cli.shell._load_config", return_value={}), patch(
            "cli.shell._dispatch_command", side_effect=RuntimeError("fixture failure")
        ):
            result = runner.invoke(cli, ["run", "bad"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("流水线执行失败", result.output)

    def test_unknown_stats_subcommand_fails_the_pipeline(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "stats not-a-command; dashboard"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn('未知 stats 子命令: "not-a-command"', result.output)
        self.assertNotIn("汇总面板已生成", result.output)


class DailyArchiveVerificationTests(unittest.TestCase):
    def test_complete_data_dated_structure_archive_passes_without_llm_requirement(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _write_complete_archive(Path(tmp))
            result = verify_daily_market_structure_archive(fixture["config"])
        self.assertEqual(result["report_date"], "2026-07-14")
        self.assertEqual(Path(result["manifest"]), fixture["manifest"])
        self.assertEqual(set(result["artifacts"]), {"report", "json"})

    def test_failed_llm_call_does_not_invalidate_deterministic_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _write_complete_archive(Path(tmp), llm_status="failed")
            result = verify_daily_market_structure_archive(fixture["config"])
        self.assertEqual(result["report_date"], "2026-07-14")

    def test_missing_report_rejects_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _write_complete_archive(Path(tmp))
            fixture["files"]["report"].unlink()
            with self.assertRaisesRegex(DailyArchiveVerificationError, "不存在或为空"):
                verify_daily_market_structure_archive(fixture["config"])

    def test_archive_hash_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _write_complete_archive(Path(tmp))
            fixture["files"]["report"].write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(DailyArchiveVerificationError, "SHA256"):
                verify_daily_market_structure_archive(fixture["config"])

    def test_v2_archive_rejects_old_filename_without_data_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _write_complete_archive(Path(tmp))
            manifest = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
            record = next(item for item in manifest["artifacts"] if item["key"] == "report")
            old_name = fixture["files"]["report"].with_name("000001.SH_h5_market_structure.html")
            old_name.write_text("legacy-name", encoding="utf-8")
            record.update(
                {
                    "path": str(old_name),
                    "sha256": _digest(old_name),
                    "bytes": old_name.stat().st_size,
                }
            )
            fixture["manifest"].write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(DailyArchiveVerificationError, "未使用数据日期前缀"):
                verify_daily_market_structure_archive(fixture["config"])

    def test_report_with_preserved_link_rewrite_status_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _write_complete_archive(Path(tmp))
            manifest = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
            next(item for item in manifest["artifacts"] if item["key"] == "report")[
                "status"
            ] = "preserved_links_updated"
            fixture["manifest"].write_text(json.dumps(manifest), encoding="utf-8")
            result = verify_daily_market_structure_archive(fixture["config"])
        self.assertEqual(result["report_date"], "2026-07-14")

    def test_forecast_cli_keeps_valid_daily_parameters(self):
        result = CliRunner().invoke(index_group, ["forecast", "--help"])
        self.assertEqual(result.exit_code, 0)
        for option in ("--symbol", "--horizon", "--start", "--end"):
            self.assertIn(option, result.output)

    def test_industry_market_report_command_is_available(self):
        result = CliRunner().invoke(index_group, ["industry-market", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--structure-json", result.output)
        self.assertIn("--output", result.output)

    def test_daily_forecast_does_not_call_llm(self):
        self.assertNotIn("write_llm_summary_artifacts(", inspect.getsource(run_index_forecast))

    def test_daily_script_runs_verifier_after_forecast(self):
        script = (Path(__file__).resolve().parents[1] / "scripts" / "daily_quant_job.sh").read_text(
            encoding="utf-8"
        )
        self.assertLess(script.index("index forecast"), script.index("verify_daily_market_structure.py"))
        self.assertIn("--symbol 000001.SH", script)
        self.assertIn("--horizon 5", script)
        self.assertIn("tee -a", script)
        self.assertIn("MEMBER_START", script)
        self.assertIn("index members --all --start ${MEMBER_START}", script)
        self.assertIn("download --start ${DATA_START} --end ${AS_OF}", script)
        self.assertIn("index ths --start ${DATA_START} --end ${AS_OF}", script)
        self.assertNotIn("index overview --all", script)
        for symbol in (
            "399001.SZ",
            "399006.SZ",
            "000688.SH",
            "000300.SH",
            "000016.SH",
            "000905.SH",
            "000852.SH",
            "932000.CSI",
        ):
            self.assertIn(f"index download --symbol {symbol} --start ${{DATA_START}} --end ${{AS_OF}}", script)
        self.assertLess(script.index("index forecast"), script.index("index structure-brief"))
        self.assertLess(script.index("index structure-brief"), script.index("index industry-market"))
        self.assertLess(script.index("index industry-market"), script.index("dashboard"))
        self.assertIn("stats radar --top 300", script)
        self.assertIn("stats vpt --trade-date ${AS_OF}", script)
        self.assertIn("stats stock-kline-pages --workers 5 --strict", script)
        for excluded in (
            "--refresh-list",
            "stats pattern",
            "stats theme",
            "stats limit-up-candidates",
            "stats theme-pool batch",
            "index environment",
            "index market --start",
        ):
            self.assertNotIn(excluded, script)
        self.assertNotIn("main.py review daily", script)
        self.assertNotIn("REVIEW_TEMPLATE", script)

    def test_daily_report_freshness_reads_all_product_report_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports = Path(tmp) / "reports"
            paths = [
                reports / "index_forecast" / "000001.SH_market_structure_brief.html",
                reports / "industry" / "industry_market.html",
                reports / "strong_stock_radar" / "strong_stock_radar.html",
                reports / "vpt" / "vpt_candidates.html",
            ]
            for path in paths:
                path.parent.mkdir(parents=True, exist_ok=True)
            paths[0].write_text("<div>数据截至 2026-09-04</div>", encoding="utf-8")
            paths[1].write_text("<div>数据截至 2026-09-04</div>", encoding="utf-8")
            paths[2].write_text("<span>数据日期 20260904</span>", encoding="utf-8")
            paths[3].write_text("<span>数据截止 20260904</span>", encoding="utf-8")
            summary = _report_freshness_summary(
                {"output": {"reports_dir": str(reports)}},
                pd.Timestamp("2026-09-04"),
            )
        self.assertEqual(summary["current_count"], 4)
        self.assertEqual(summary["expected_count"], 4)

    def test_stale_or_missing_report_date_is_not_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports = Path(tmp) / "reports"
            industry = reports / "industry" / "industry_market.html"
            industry.parent.mkdir(parents=True)
            industry.write_text("<div>数据截至 2026-09-03</div>", encoding="utf-8")
            self.assertEqual(_report_date(industry), pd.Timestamp("2026-09-03"))
            summary = _report_freshness_summary(
                {"output": {"reports_dir": str(reports)}},
                pd.Timestamp("2026-09-04"),
            )
        self.assertEqual(summary["current_count"], 0)

    def test_daily_verifier_exposes_expected_trade_date_guard(self):
        script = (Path(__file__).resolve().parents[1] / "scripts" / "daily_quant_job.sh").read_text(
            encoding="utf-8"
        )
        self.assertGreaterEqual(script.count('--expected-date "$AS_OF"'), 2)
        self.assertIn("QUANT_YB_FORCE_DAILY", script)
        self.assertIn("跳过重复更新", script)

    def test_expected_trade_date_requires_same_day_ths_sections(self):
        source = inspect.getsource(__import__("scripts.verify_daily_market_data", fromlist=["main"]).main)
        self.assertIn('latest != expected_date', source)
        self.assertIn("未达到目标", source)

    def test_pipeline_routes_all_daily_market_reports(self):
        with patch("cli.shell.run_market_structure_brief") as brief, patch(
            "cli.shell.run_market_environment"
        ) as environment, patch("cli.shell.run_industry_market_report") as industry:
            result = _execute_pipeline(
                {},
                "index structure-brief --symbol 000001.SH; "
                "index environment --symbol 000001.SH; "
                "index industry-market --symbol 000001.SH",
            )
        self.assertTrue(result)
        brief.assert_called_once()
        environment.assert_called_once()
        industry.assert_called_once()


class StockKlinePageSyncTests(unittest.TestCase):
    @staticmethod
    def _write_kline(path: Path, close: float) -> None:
        pd.DataFrame(
            {
                "date": ["20260102", "20260103"],
                "open": [close - 1.0, close - 0.5],
                "high": [close + 1.0, close + 0.5],
                "low": [close - 1.5, close - 1.0],
                "close": [close - 0.5, close],
                "volume": [1000.0, 1200.0],
                "amount": [10000.0, 12000.0],
            }
        ).to_csv(path, index=False)

    def test_incremental_stock_kline_page_sync_uses_cache_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            reports = root / "reports"
            cache.mkdir()
            self._write_kline(cache / "000001.SZ.csv", 10.0)
            self._write_kline(cache / "000002.SZ.csv", 20.0)
            config = {
                "data": {"cache_dir": str(cache), "meta_dir": str(root / "meta")},
                "output": {"reports_dir": str(reports)},
            }

            first = sync_stock_kline_pages(config)
            self.assertEqual(first["checked"], 2)
            self.assertEqual(first["generated"], 2)
            self.assertEqual(first["skipped"], 0)
            self.assertEqual(first["failed"], [])

            second = sync_stock_kline_pages(config)
            self.assertEqual(second["generated"], 0)
            self.assertEqual(second["skipped"], 2)

            self._write_kline(cache / "000001.SZ.csv", 11.0)
            target_mtime = (reports / "stock_kline" / "000001.SZ.html").stat().st_mtime + 1
            os.utime(cache / "000001.SZ.csv", (target_mtime, target_mtime))
            third = sync_stock_kline_pages(config)
            self.assertEqual(third["generated"], 1)
            self.assertEqual(third["skipped"], 1)
            self.assertIn("2026-01-03", (reports / "stock_kline" / "000001.SZ.html").read_text(encoding="utf-8"))

    def test_stock_kline_page_sync_command_is_available(self):
        result = CliRunner().invoke(cli, ["stats", "stock-kline-pages", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--symbol", result.output)
        self.assertIn("--force", result.output)
        self.assertIn("--strict", result.output)
        self.assertIn("--limit", result.output)
        self.assertIn("--workers", result.output)

    def test_incremental_stock_kline_page_sync_uses_daily_basic_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            reports = root / "reports"
            daily_basic = root / "meta" / "daily_basic"
            cache.mkdir()
            daily_basic.mkdir(parents=True)
            self._write_kline(cache / "000001.SZ.csv", 10.0)
            pd.DataFrame(
                [{"ts_code": "000001.SZ", "trade_date": "20260103", "total_mv": 100.0}]
            ).to_csv(daily_basic / "000001.SZ.csv", index=False)
            config = {
                "data": {"cache_dir": str(cache), "meta_dir": str(root / "meta")},
                "output": {"reports_dir": str(reports)},
            }

            self.assertEqual(sync_stock_kline_pages(config)["generated"], 1)
            target = reports / "stock_kline" / "000001.SZ.html"
            refreshed_at = target.stat().st_mtime + 1
            os.utime(daily_basic / "000001.SZ.csv", (refreshed_at, refreshed_at))

            result = sync_stock_kline_pages(config)
            self.assertEqual(result["generated"], 1)
            self.assertEqual(result["skipped"], 0)

    def test_pipeline_routes_stock_kline_page_sync(self):
        with patch(
            "cli.stats_cli.sync_stock_kline_pages",
            return_value={"checked": 2, "generated": 2, "skipped": 0, "failed": []},
        ) as sync:
            result = _execute_pipeline({}, "stats stock-kline-pages --force --limit 2 --bars 120")
        self.assertTrue(result)
        sync.assert_called_once_with({}, force=True, limit=2, bars=120)


class ThsIndexUpdateTests(unittest.TestCase):
    def test_skip_failures_mode_updates_ths_indexes_concurrently(self):
        symbols = [f"88400{index}.TI" for index in range(1, 5)]

        class FakeDownloader:
            _max_workers = 4

            def __init__(self, _config):
                self.thread_names: set[str] = set()

            def download_ths_index_list(self, exchange=None, force=False):
                return pd.DataFrame(
                    [{"ts_code": symbol, "name": symbol, "exchange": "A", "type": "I"} for symbol in symbols]
                )

            def download_index(self, symbol, start, end, force=False):
                self.thread_names.add(threading.current_thread().name)
                time.sleep(0.02)
                return pd.DataFrame([{"date": end, "close": 1.0}])

            @staticmethod
            def _ths_index_list_path():
                return Path("ths_indices.csv")

            @staticmethod
            def _index_cache_path(symbol):
                return Path(f"{symbol}.csv")

        fake = FakeDownloader({})
        with patch("cli.index_cli.DataDownloader", return_value=fake), patch(
            "cli.index_cli._select_ths_industry_symbols", return_value=symbols
        ):
            result = run_index_ths(
                {"parallel": {"index_download_workers": 4}},
                start="20260801",
                end="20260904",
                include_styles=False,
                skip_failures=True,
            )
        self.assertEqual([symbol for symbol, _ in result], symbols)
        self.assertGreater(len(fake.thread_names), 1)


if __name__ == "__main__":
    unittest.main()
