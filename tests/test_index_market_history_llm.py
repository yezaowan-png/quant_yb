import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from analysis.index_market_history_llm import (
    AUDIT_TABLE_FILES,
    CONTROL_FILES,
    CORE_PANEL_COLUMNS,
    HORIZONS,
    INDEX_LAG_COLUMNS,
    PERCENTILE_COLUMNS,
    _sha256,
    build_history_deepseek_prompt,
    call_deepseek_v4_pro_audit,
    history_llm_audit_paths,
    prepare_deepseek_history_audit,
    recover_deepseek_history_audit,
    write_deepseek_history_audit,
)


class _FakeHTTPResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class IndexMarketHistoryLLMTest(unittest.TestCase):
    def _record(self, path: Path) -> dict:
        stat = path.stat()
        return {
            "bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": _sha256(path),
        }

    def _write_batch(self, root: Path, *, status: str = "passed", rows: int = 400) -> None:
        dates = pd.bdate_range("2024-01-01", periods=rows)
        text_defaults = {
            "style_regime": "rotation",
            "tail_pressure": "low",
            "risk_direction": "stable",
            "breadth_today_state": "neutral",
            "breadth_5d_state": "neutral",
            "breadth_20d_state": "neutral",
            "large_cap_daily_trend": "sideways",
            "large_cap_weekly_trend": "sideways",
            "growth_daily_trend": "sideways",
            "growth_weekly_trend": "sideways",
            "style_leader_20d": "科技成长",
            "divergence_1d": "synchronized",
            "divergence_5d": "synchronized",
            "divergence_20d": "synchronized",
            "liquidity_state": "normal",
            "data_quality_flags": "",
            "industry_strong_1_name": "半导体",
            "industry_strong_2_name": "软件",
            "industry_strong_3_name": "证券",
            "industry_weak_1_name": "煤炭",
            "industry_weak_2_name": "钢铁",
            "industry_weak_3_name": "银行",
        }
        data: dict[str, object] = {}
        for column in CORE_PANEL_COLUMNS:
            if column == "trade_date":
                data[column] = dates.strftime("%Y-%m-%d")
            elif column in text_defaults:
                data[column] = [text_defaults[column]] * rows
            elif column in {"research_overheat_candidate_v1", "research_icepoint_candidate_v1"}:
                data[column] = [False] * rows
            elif column == "breadth_valid_stock_count":
                data[column] = [5000] * rows
            elif column in PERCENTILE_COLUMNS:
                data[column] = [0.5] * rows
            elif column in INDEX_LAG_COLUMNS:
                data[column] = [0] * rows
            elif column.endswith("_data_coverage"):
                data[column] = [1.0] * rows
            else:
                data[column] = [0.0] * rows
        if rows:
            data["tail_pressure"][0] = "high"  # type: ignore[index]
            data["risk_direction"][0] = "expanding"  # type: ignore[index]
            data["tail_pressure_flag_count_recomputed"][0] = 3.0  # type: ignore[index]
        panel = pd.DataFrame(data)
        for horizon in HORIZONS:
            mature_count = max(0, rows - horizon)
            mature = [True] * mature_count + [False] * (rows - mature_count)
            panel[f"future_mature_{horizon}d"] = mature
            for column in (
                f"future_all_a_return_{horizon}d",
                f"future_all_a_min_return_{horizon}d",
                f"future_all_a_max_return_{horizon}d",
                f"future_all_a_max_drawdown_{horizon}d",
                f"future_stock_median_return_{horizon}d",
                f"future_stock_win_rate_{horizon}d",
                f"future_style_leader_20d_hit_{horizon}d",
                f"future_style_strength_rank_ic_{horizon}d",
            ):
                value = 1.0 if "win_rate" in column or "hit" in column else 0.01
                panel[column] = [value] * mature_count + [np.nan] * (rows - mature_count)
        panel["future_industry_strong_minus_weak_5d"] = [0.01] * max(0, rows - 5) + [np.nan] * min(5, rows)
        panel["future_industry_strong_minus_weak_20d"] = [0.01] * max(0, rows - 20) + [np.nan] * min(20, rows)
        panel.to_csv(root / AUDIT_TABLE_FILES["panel"], index=False)

        pd.DataFrame([{"dimension": "tail_pressure", "state": "low", "count": rows}]).to_csv(
            root / AUDIT_TABLE_FILES["event_study"], index=False,
        )
        pd.DataFrame(
            [{"dimension": "tail_pressure", "from_state": "low", "to_state": "low", "count": rows - 1, "probability": 1.0}],
        ).to_csv(root / AUDIT_TABLE_FILES["transitions"], index=False)
        pd.DataFrame(
            [{"feature": "breadth_advance_ratio", "outcome": "future_all_a_return_5d", "sample_count": rows - 5, "spearman": 0.1, "pearson": 0.1}],
        ).to_csv(root / AUDIT_TABLE_FILES["correlations"], index=False)
        pd.DataFrame(
            [{"event_type": "panic_expanding", "episode_id": 1, "start_date": str(dates[0].date()), "end_date": str(dates[0].date()), "duration_days": 1}],
        ).to_csv(root / AUDIT_TABLE_FILES["episodes"], index=False)
        pd.DataFrame([{"column": "trade_date", "missing_count": 0, "missing_ratio": 0.0}]).to_csv(
            root / AUDIT_TABLE_FILES["missingness"], index=False,
        )
        pd.DataFrame([{"dimension": "all_styles", "horizon": 5, "leader_hit_n": rows - 5}]).to_csv(
            root / AUDIT_TABLE_FILES["style_validation"], index=False,
        )
        pd.DataFrame([{"horizon": 5, "sample_count": rows - 5, "strong_minus_weak_mean": 0.01}]).to_csv(
            root / AUDIT_TABLE_FILES["industry_validation"], index=False,
        )

        snapshot = root / "snapshot_fact.md"
        snapshot.write_text("事实包，不含未来字段。", encoding="utf-8")
        manifest = pd.DataFrame(
            {
                "trade_date": dates.strftime("%Y-%m-%d"),
                "status": ["ok"] * rows,
                "as_of_check": [True] * rows,
                "deepseek_called": [False] * rows,
                "facts_path": [str(snapshot)] * rows,
            }
        )
        manifest.to_csv(root / CONTROL_FILES["manifest_csv"], index=False)
        (root / CONTROL_FILES["manifest_json"]).write_text(
            json.dumps(manifest.to_dict("records"), ensure_ascii=False), encoding="utf-8",
        )
        first_date = dates[0].strftime("%Y-%m-%d") if rows else ""
        last_date = dates[-1].strftime("%Y-%m-%d") if rows else ""
        quality = {
            "status": status,
            "snapshot_count": rows,
            "unique_trade_dates": rows,
            "first_trade_date": first_date,
            "last_trade_date": last_date,
            "all_as_of_checks_passed": True,
            "all_required_files_exist": True,
            "facts_contain_no_future_labels": True,
            "breadth_counts_reconcile": True,
            "tail_pressure_recomputed_matches_production": True,
            "per_snapshot_deepseek_calls": 0,
            "analysis_snapshot_source": "fresh_point_in_time_replay",
            "original_daily_artifacts_preserved": True,
            "history_bars": 1050,
            "finished_at": "2026-01-01T00:00:00+08:00",
        }
        (root / CONTROL_FILES["quality"]).write_text(json.dumps(quality), encoding="utf-8")
        reproducibility = {
            "schema_version": 1,
            "generated_at": "2026-01-01T00:00:01+08:00",
            "parameters": {
                "days": rows,
                "first_trade_date": first_date,
                "last_trade_date": last_date,
            },
        }
        (root / CONTROL_FILES["reproducibility"]).write_text(json.dumps(reproducibility), encoding="utf-8")

        completed_names = {
            *(root / filename for filename in AUDIT_TABLE_FILES.values()),
            root / CONTROL_FILES["quality"],
            root / CONTROL_FILES["manifest_csv"],
            root / CONTROL_FILES["manifest_json"],
        }
        completion = {
            "batch_run_id": "test-run-001",
            "status": "complete",
            "snapshot_count": rows,
            "first_trade_date": first_date,
            "last_trade_date": last_date,
            "finished_at": "2026-01-01T00:00:02+08:00",
            "input_files": {path.name: self._record(path) for path in completed_names},
        }
        (root / CONTROL_FILES["complete"]).write_text(json.dumps(completion), encoding="utf-8")

    @staticmethod
    def _raw_payload(content: str = "# 审计结果\n\n完成。", reasoning_chars: int = 12) -> dict:
        return {
            "id": "response-test",
            "model": "deepseek-v4-pro",
            "created": 1,
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"content": content}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            "_archive_note": {"reasoning_content_omitted": True, "reasoning_chars": reasoning_chars},
        }

    def test_strict_prompt_contains_rules_and_complete_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_batch(root)
            prompt = build_history_deepseek_prompt(root)
            self.assertIn("共 400 个交易日", prompt)
            self.assertIn("批次运行ID：`test-run-001`", prompt)
            self.assertIn("风险方向比较今日与前一日", prompt)
            self.assertIn("未计算HAC", prompt)
            self.assertIn("breadth_valid_stock_count", prompt)
            self.assertIn("percentile_advance_ratio", prompt)
            self.assertIn("index_all_a_lag_calendar_days", prompt)

    def test_rejects_non_400_failed_or_detailed_quality_failure(self):
        for status, rows in (("failed", 400), ("passed", 399)):
            with self.subTest(status=status, rows=rows), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self._write_batch(root, status=status, rows=rows)
                with self.assertRaises(RuntimeError):
                    build_history_deepseek_prompt(root)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_batch(root)
            quality_path = root / CONTROL_FILES["quality"]
            quality = json.loads(quality_path.read_text())
            quality["facts_contain_no_future_labels"] = False
            quality_path.write_text(json.dumps(quality), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                build_history_deepseek_prompt(root)

    def test_rejects_missing_core_column_empty_aggregate_and_future_tail_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_batch(root)
            panel_path = root / AUDIT_TABLE_FILES["panel"]
            panel = pd.read_csv(panel_path)
            panel.drop(columns=["percentile_advance_ratio"]).to_csv(panel_path, index=False)
            with self.assertRaisesRegex(RuntimeError, "缺少核心证据字段"):
                build_history_deepseek_prompt(root)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_batch(root)
            (root / AUDIT_TABLE_FILES["style_validation"]).write_text("dimension,horizon,leader_hit_n\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "没有数据行"):
                build_history_deepseek_prompt(root)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_batch(root)
            panel_path = root / AUDIT_TABLE_FILES["panel"]
            panel = pd.read_csv(panel_path)
            panel.loc[len(panel) - 1, "future_all_a_return_5d"] = 0.1
            panel.to_csv(panel_path, index=False)
            with self.assertRaisesRegex(RuntimeError, "未成熟尾部含未来值"):
                build_history_deepseek_prompt(root)

    def test_rejects_in_progress_or_completion_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_batch(root)
            (root / "market_structure_400d_in_progress.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "运行中哨兵"):
                build_history_deepseek_prompt(root)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_batch(root)
            completion_path = root / CONTROL_FILES["complete"]
            completion = json.loads(completion_path.read_text())
            completion["input_files"][AUDIT_TABLE_FILES["panel"]]["sha256"] = "bad"
            completion_path.write_text(json.dumps(completion), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "完成哨兵输入记录不匹配"):
                build_history_deepseek_prompt(root)

    def test_missing_key_does_not_create_call_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_batch(root)
            paths = history_llm_audit_paths(root)
            with patch("analysis.index_market_history_llm._api_key_from_env_or_dotenv", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "缺少 DeepSeek API Key"):
                    write_deepseek_history_audit(root, {})
            self.assertFalse(paths.call_lock.exists())
            self.assertFalse(paths.raw_response.exists())

    def test_existing_lock_is_checked_before_prompt_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_batch(root)
            paths = history_llm_audit_paths(root)
            paths.prompt.write_text("不可覆盖", encoding="utf-8")
            paths.call_lock.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "拒绝重复计费"):
                write_deepseek_history_audit(root, {})
            self.assertEqual(paths.prompt.read_text(encoding="utf-8"), "不可覆盖")

    def test_successful_call_is_idempotent_and_records_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_batch(root)

            def fake_call(_prompt, _config, **kwargs):
                raw_path = kwargs["raw_response_path"]
                raw_path.write_text(json.dumps(self._raw_payload(), ensure_ascii=False), encoding="utf-8")
                return "# 审计结果\n\n完成。", {
                    "model_requested": "deepseek-v4-pro",
                    "model_returned": "deepseek-v4-pro",
                    "finish_reason": "stop",
                }

            with patch("analysis.index_market_history_llm._local_api_preflight", return_value=("token", "https://api.deepseek.com")), patch(
                "analysis.index_market_history_llm.call_deepseek_v4_pro_audit", side_effect=fake_call,
            ) as mocked:
                paths, metadata = write_deepseek_history_audit(root, {})
                self.assertEqual(mocked.call_count, 1)
                self.assertTrue(paths.response.exists())
                self.assertTrue(paths.metadata.exists())
                self.assertEqual(metadata["batch_run_id"], "test-run-001")
                self.assertEqual(metadata["reasoning_chars"], 12)
                self.assertEqual(metadata["raw_response_sha256"], _sha256(paths.raw_response))
                self.assertIn("panel", metadata["input_files"])
                _, second_metadata = write_deepseek_history_audit(root, {})
                self.assertEqual(mocked.call_count, 1)
                self.assertFalse(second_metadata["api_called_this_run"])
                self.assertTrue(second_metadata["already_completed"])

    def test_raw_response_recovers_without_api_or_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_batch(root)
            paths, prepared = prepare_deepseek_history_audit(root)
            lock = {
                "status": "response_received_postprocess_failed",
                "model_requested": "deepseek-v4-pro",
                "started_at": "2026-01-01T00:01:00+08:00",
                "single_batch_call": True,
                "prompt_sha256": prepared["prompt_sha256"],
                "input_files": prepared["input_files"],
                "batch_run_id": prepared["batch_run_id"],
            }
            paths.call_lock.write_text(json.dumps(lock), encoding="utf-8")
            paths.raw_response.write_text(json.dumps(self._raw_payload(), ensure_ascii=False), encoding="utf-8")
            with patch("analysis.index_market_history_llm.call_deepseek_v4_pro_audit") as mocked:
                _, metadata = recover_deepseek_history_audit(root)
            mocked.assert_not_called()
            self.assertTrue(metadata["recovered_from_raw"])
            self.assertFalse(metadata["api_called_this_run"])
            self.assertTrue(paths.html.exists())

    def test_api_response_omits_reasoning_but_preserves_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_path = Path(tmp) / "raw.json"
            payload = self._raw_payload()
            payload["choices"][0]["message"]["reasoning_content"] = "内部推理不可归档"
            with patch("analysis.index_market_history_llm.urllib.request.urlopen", return_value=_FakeHTTPResponse(payload)):
                content, metadata = call_deepseek_v4_pro_audit(
                    "prompt", {}, raw_response_path=raw_path,
                    token="not-a-real-token", base_url="https://api.deepseek.com",
                )
            raw_text = raw_path.read_text(encoding="utf-8")
            self.assertEqual(content, "# 审计结果\n\n完成。")
            self.assertNotIn("内部推理不可归档", raw_text)
            self.assertEqual(metadata["reasoning_chars"], len("内部推理不可归档"))


if __name__ == "__main__":
    unittest.main()
