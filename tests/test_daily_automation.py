from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from cli.index_cli import index_group
from cli.shell import _execute_pipeline
from main import cli
from scripts.verify_daily_market_structure import (
    DailyArchiveVerificationError,
    verify_daily_market_structure_archive,
)


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

    def test_main_run_command_returns_nonzero_when_pipeline_fails(self):
        runner = CliRunner()
        with patch("cli.shell._load_config", return_value={}), patch(
            "cli.shell._dispatch_command", side_effect=RuntimeError("fixture failure")
        ):
            result = runner.invoke(cli, ["run", "bad"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("流水线执行失败", result.output)


class DailyArchiveVerificationTests(unittest.TestCase):
    def test_complete_data_dated_structure_and_llm_archive_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _write_complete_archive(Path(tmp))
            result = verify_daily_market_structure_archive(fixture["config"])
        self.assertEqual(result["report_date"], "2026-07-14")
        self.assertEqual(Path(result["manifest"]), fixture["manifest"])
        self.assertEqual(set(result["artifacts"]), {"report", "json", "llm_summary", "llm_summary_html"})

    def test_failed_llm_call_rejects_archive_even_when_stale_files_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _write_complete_archive(Path(tmp), llm_status="failed")
            with self.assertRaisesRegex(DailyArchiveVerificationError, "LLM总结未成功"):
                verify_daily_market_structure_archive(fixture["config"])

    def test_missing_llm_html_rejects_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _write_complete_archive(Path(tmp))
            fixture["files"]["llm_summary_html"].unlink()
            with self.assertRaisesRegex(DailyArchiveVerificationError, "不存在或为空"):
                verify_daily_market_structure_archive(fixture["config"])

    def test_archive_hash_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _write_complete_archive(Path(tmp))
            fixture["files"]["llm_summary"].write_text("tampered", encoding="utf-8")
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


if __name__ == "__main__":
    unittest.main()
