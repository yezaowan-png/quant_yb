"""DeepSeek V4 Pro audit for a completed 400-day market-structure batch.

The paid call is deliberately fail-closed: all local evidence is validated and
frozen before the call lock is created.  A successful raw API response is also
enough to finish the report later without issuing another request.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import urllib.error
import urllib.request
import uuid

import numpy as np
import pandas as pd

from analysis.index_market_llm import _api_key_from_env_or_dotenv, _markdown_html


MODEL_NAME = "deepseek-v4-pro"
EXPECTED_DAYS = 400
HORIZONS = (1, 5, 10, 20)

AUDIT_TABLE_FILES = {
    "panel": "market_structure_400d_panel.csv",
    "event_study": "market_structure_400d_event_study.csv",
    "transitions": "market_structure_400d_state_transitions.csv",
    "correlations": "market_structure_400d_feature_correlations.csv",
    "episodes": "market_structure_400d_event_episodes.csv",
    "missingness": "market_structure_400d_missingness.csv",
    "style_validation": "market_structure_400d_style_validation.csv",
    "industry_validation": "market_structure_400d_industry_validation.csv",
}
CONTROL_FILES = {
    "quality": "market_structure_400d_quality_checks.json",
    "manifest_csv": "market_structure_400d_manifest.csv",
    "manifest_json": "market_structure_400d_manifest.json",
    "reproducibility": "market_structure_400d_reproducibility.json",
    "complete": "market_structure_400d_complete.json",
}
IN_PROGRESS_FILE = "market_structure_400d_in_progress.json"

PERCENTILE_COLUMNS = (
    "percentile_advance_ratio",
    "percentile_decline_ratio",
    "percentile_pct_above_ma20",
    "percentile_pct_above_ma50",
    "percentile_pct_above_ma200",
    "percentile_normalized_ad_5d",
    "percentile_normalized_ad_20d",
    "percentile_new_high_20_ratio",
    "percentile_new_low_20_ratio",
    "percentile_advance_gt_5_ratio",
    "percentile_decline_gt_5_ratio",
    "percentile_approximate_limit_up_ratio",
    "percentile_approximate_limit_down_ratio",
    "percentile_cross_section_dispersion",
    "percentile_market_realized_volatility_5d",
)
INDEX_LAG_COLUMNS = (
    "index_sse_lag_calendar_days",
    "index_hs300_lag_calendar_days",
    "index_sse50_lag_calendar_days",
    "index_csi500_lag_calendar_days",
    "index_csi1000_lag_calendar_days",
    "index_csi2000_lag_calendar_days",
    "index_chinext_lag_calendar_days",
    "index_star50_lag_calendar_days",
    "index_all_a_lag_calendar_days",
)
STYLE_COVERAGE_COLUMNS = tuple(
    f"style_{key}_data_coverage"
    for key in ("value", "securities", "growth", "consumer", "small_cap")
)

CORE_PANEL_COLUMNS = (
    "trade_date",
    "style_regime",
    "tail_pressure",
    "risk_direction",
    "breadth_today_state",
    "breadth_5d_state",
    "breadth_20d_state",
    "large_cap_daily_trend",
    "large_cap_weekly_trend",
    "growth_daily_trend",
    "growth_weekly_trend",
    "style_leader_20d",
    "divergence_1d",
    "divergence_5d",
    "divergence_20d",
    "liquidity_state",
    "data_quality_flag_count",
    "data_quality_flags",
    "breadth_valid_stock_count",
    "breadth_advance_ratio",
    "breadth_decline_ratio",
    "breadth_median_stock_return_1d",
    "breadth_equal_weight_return_1d",
    "breadth_pct_above_ma20",
    "breadth_pct_above_ma50",
    "breadth_pct_above_ma200",
    "breadth_normalized_ad",
    "breadth_normalized_ad_5d",
    "breadth_normalized_ad_20d",
    "breadth_new_high_20_ratio",
    "breadth_new_low_20_ratio",
    "breadth_normalized_nhnl_20",
    "breadth_advance_gt_5_ratio",
    "breadth_decline_gt_5_ratio",
    "breadth_approximate_limit_up_ratio",
    "breadth_approximate_limit_down_ratio",
    "breadth_cross_section_dispersion",
    "breadth_market_realized_volatility_5d",
    "breadth_amount_ratio_20",
    "tail_pressure_flag_count_recomputed",
    "index_sse_return_1d",
    "index_sse_return_5d",
    "index_sse_return_20d",
    "index_hs300_return_1d",
    "index_hs300_return_5d",
    "index_hs300_return_20d",
    "index_all_a_return_1d",
    "index_all_a_return_5d",
    "index_all_a_return_20d",
    "style_value_strength",
    "style_securities_strength",
    "style_growth_strength",
    "style_consumer_strength",
    "style_small_cap_strength",
    "research_overheat_score_v1",
    "research_icepoint_score_v1",
    "research_overheat_candidate_v1",
    "research_icepoint_candidate_v1",
    "industry_strong_1_name",
    "industry_strong_2_name",
    "industry_strong_3_name",
    "industry_weak_1_name",
    "industry_weak_2_name",
    "industry_weak_3_name",
    *PERCENTILE_COLUMNS,
    *INDEX_LAG_COLUMNS,
    *STYLE_COVERAGE_COLUMNS,
)

AGGREGATE_REQUIRED_COLUMNS = {
    "event_study": {"dimension", "state", "count"},
    "transitions": {"dimension", "from_state", "to_state", "count", "probability"},
    "correlations": {"feature", "outcome", "sample_count", "spearman", "pearson"},
    "episodes": {"event_type", "episode_id", "start_date", "end_date", "duration_days"},
    "missingness": {"column", "missing_count", "missing_ratio"},
    "style_validation": {"dimension", "horizon", "leader_hit_n"},
    "industry_validation": {"horizon", "sample_count", "strong_minus_weak_mean"},
}


@dataclass(frozen=True)
class HistoryLLMAuditPaths:
    prompt: Path
    response: Path
    html: Path
    metadata: Path
    raw_response: Path
    call_lock: Path


@dataclass(frozen=True)
class PreparedHistoryAudit:
    prompt: str
    input_files: dict[str, dict[str, Any]]
    first_trade_date: str
    last_trade_date: str
    batch_run_id: str


def history_llm_audit_paths(batch_dir: str | Path) -> HistoryLLMAuditPaths:
    root = Path(batch_dir)
    return HistoryLLMAuditPaths(
        prompt=root / "deepseek_v4_pro_market_structure_400d_prompt.md",
        response=root / "deepseek_v4_pro_market_structure_400d_audit.md",
        html=root / "deepseek_v4_pro_market_structure_400d_audit.html",
        metadata=root / "deepseek_v4_pro_market_structure_400d_metadata.json",
        raw_response=root / "deepseek_v4_pro_market_structure_400d_raw_response.json",
        call_lock=root / ".deepseek_v4_pro_market_structure_400d_call.lock",
    )


def _csv_block(frame: pd.DataFrame, max_rows: int | None = None) -> str:
    selected = frame.head(max_rows) if max_rows is not None else frame
    return selected.to_csv(index=False, na_rep="")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_record(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": _sha256(path),
    }


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def _read_nonempty_csv(path: Path, required_columns: set[str] | None = None) -> pd.DataFrame:
    if not path.exists() or not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"审计证据文件缺失或为空: {path.name}")
    try:
        frame = pd.read_csv(path)
    except pd.errors.EmptyDataError as exc:
        raise RuntimeError(f"审计证据表为空: {path.name}") from exc
    if frame.empty:
        raise RuntimeError(f"审计证据表没有数据行: {path.name}")
    missing = sorted((required_columns or set()) - set(frame.columns))
    if missing:
        raise RuntimeError(f"审计证据表缺少字段 {path.name}: {', '.join(missing)}")
    return frame


def _as_bool(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False).astype(bool)
    truthy = {"1", "true", "t", "yes", "y"}
    falsy = {"0", "false", "f", "no", "n", "", "nan", "none"}
    normalized = series.astype(str).str.strip().str.lower()
    unknown = ~normalized.isin(truthy | falsy)
    if unknown.any():
        raise RuntimeError(f"布尔字段含无法识别的值: {sorted(normalized[unknown].unique())[:5]}")
    return normalized.isin(truthy)


def _parse_time(value: Any, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{label} 时间格式无效: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def _validate_quality(quality: dict[str, Any], panel: pd.DataFrame) -> None:
    expected_true = (
        "all_as_of_checks_passed",
        "all_required_files_exist",
        "facts_contain_no_future_labels",
        "breadth_counts_reconcile",
        "tail_pressure_recomputed_matches_production",
    )
    failures: list[str] = []
    if quality.get("status") != "passed":
        failures.append("status != passed")
    for field in expected_true:
        if quality.get(field) is not True:
            failures.append(f"{field} != true")
    if int(quality.get("snapshot_count") or -1) != EXPECTED_DAYS:
        failures.append("snapshot_count != 400")
    if int(quality.get("unique_trade_dates") or -1) != EXPECTED_DAYS:
        failures.append("unique_trade_dates != 400")
    if "per_snapshot_deepseek_calls" not in quality or int(quality.get("per_snapshot_deepseek_calls") or 0) != 0:
        failures.append("per_snapshot_deepseek_calls != 0")
    allowed_snapshot_sources = {
        "fresh_point_in_time_replay",
        "fresh_point_in_time_replay_then_archive_reconstruction",
    }
    if quality.get("analysis_snapshot_source") not in allowed_snapshot_sources:
        failures.append("analysis_snapshot_source 不是受支持的point-in-time重放口径")
    if quality.get("original_daily_artifacts_preserved") is not True:
        failures.append("original_daily_artifacts_preserved != true")
    if int(quality.get("history_bars") or 0) < 1050:
        failures.append("history_bars < 1050")
    first_date = str(panel["trade_date"].iloc[0])
    last_date = str(panel["trade_date"].iloc[-1])
    if str(quality.get("first_trade_date")) != first_date:
        failures.append("quality.first_trade_date 与 panel 不一致")
    if str(quality.get("last_trade_date")) != last_date:
        failures.append("quality.last_trade_date 与 panel 不一致")
    if failures:
        raise RuntimeError("400日批次质量门禁失败: " + "; ".join(failures))


def _validate_panel(panel: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(set(CORE_PANEL_COLUMNS) - set(panel.columns))
    for horizon in HORIZONS:
        required = {
            f"future_mature_{horizon}d",
            f"future_all_a_return_{horizon}d",
            f"future_all_a_min_return_{horizon}d",
            f"future_all_a_max_return_{horizon}d",
            f"future_all_a_max_drawdown_{horizon}d",
            f"future_stock_median_return_{horizon}d",
            f"future_stock_win_rate_{horizon}d",
            f"future_style_leader_20d_hit_{horizon}d",
            f"future_style_strength_rank_ic_{horizon}d",
        }
        missing.extend(sorted(required - set(panel.columns)))
    missing.extend(
        sorted(
            {"future_industry_strong_minus_weak_5d", "future_industry_strong_minus_weak_20d"}
            - set(panel.columns)
        )
    )
    if missing:
        raise RuntimeError("400日面板缺少核心证据字段: " + ", ".join(sorted(set(missing))))
    if len(panel) != EXPECTED_DAYS:
        raise RuntimeError(f"400日面板行数错误: {len(panel)}")
    dates = pd.to_datetime(panel["trade_date"], errors="coerce")
    if dates.isna().any() or dates.nunique() != EXPECTED_DAYS or not dates.is_monotonic_increasing:
        raise RuntimeError("400日面板交易日必须有效、唯一且严格升序")
    result = panel.copy()
    result["trade_date"] = dates.dt.strftime("%Y-%m-%d")

    valid_counts = pd.to_numeric(result["breadth_valid_stock_count"], errors="coerce")
    if valid_counts.isna().any() or valid_counts.le(0).any():
        raise RuntimeError("breadth_valid_stock_count 含缺失或非正值")
    for column in PERCENTILE_COLUMNS:
        values = pd.to_numeric(result[column], errors="coerce")
        if values.isna().any() or values.lt(0).any() or values.gt(1).any():
            raise RuntimeError(f"滚动分位字段越界或缺失: {column}")

    pressure_count = pd.to_numeric(result["tail_pressure_flag_count_recomputed"], errors="coerce")
    if pressure_count.isna().any():
        raise RuntimeError("tail_pressure_flag_count_recomputed 含缺失")
    recomputed = pd.Series("low", index=result.index, dtype="object")
    recomputed[pressure_count.ge(1)] = "medium"
    recomputed[pressure_count.ge(3)] = "high"
    recomputed[pressure_count.ge(4)] = "extreme"
    if not recomputed.eq(result["tail_pressure"].astype(str)).all():
        raise RuntimeError("tail_pressure 与重新计算的尾压计数不一致")

    for horizon in HORIZONS:
        mature_column = f"future_mature_{horizon}d"
        mature = _as_bool(result[mature_column])
        expected = pd.Series(np.arange(EXPECTED_DAYS) < EXPECTED_DAYS - horizon, index=result.index)
        if not mature.eq(expected).all():
            raise RuntimeError(f"{mature_column} 不是前{EXPECTED_DAYS - horizon}真、末{horizon}假")
        core_outcomes = (
            f"future_all_a_return_{horizon}d",
            f"future_all_a_min_return_{horizon}d",
            f"future_all_a_max_return_{horizon}d",
            f"future_all_a_max_drawdown_{horizon}d",
            f"future_stock_median_return_{horizon}d",
            f"future_stock_win_rate_{horizon}d",
        )
        for column in core_outcomes:
            if result.loc[mature, column].isna().any():
                raise RuntimeError(f"成熟未来标签存在缺失: {column}")
        horizon_columns = [
            column
            for column in result.columns
            if column.startswith("future_")
            and column.endswith(f"_{horizon}d")
            and column != mature_column
            and "_valid_count_" not in column
        ]
        leaked = [column for column in horizon_columns if result.loc[~mature, column].notna().any()]
        if leaked:
            raise RuntimeError(f"未成熟尾部含未来值({horizon}日): {', '.join(leaked)}")
        valid_count_columns = [
            column
            for column in result.columns
            if column.startswith("future_")
            and column.endswith(f"_{horizon}d")
            and "_valid_count_" in column
        ]
        invalid_counts = [
            column
            for column in valid_count_columns
            if not pd.to_numeric(result.loc[~mature, column], errors="coerce").fillna(0).eq(0).all()
        ]
        if invalid_counts:
            raise RuntimeError(f"未成熟尾部的有效样本数不是0({horizon}日): {', '.join(invalid_counts)}")
    return result


def _validate_manifest(
    manifest: pd.DataFrame,
    panel: pd.DataFrame,
    sentinel_mtime_ns: int,
) -> None:
    required = {"trade_date", "status", "as_of_check", "deepseek_called"}
    missing = sorted(required - set(manifest.columns))
    if missing:
        raise RuntimeError("批次 manifest 缺少字段: " + ", ".join(missing))
    if len(manifest) != EXPECTED_DAYS or manifest["trade_date"].astype(str).nunique() != EXPECTED_DAYS:
        raise RuntimeError("批次 manifest 不是400个唯一交易日")
    if set(manifest["trade_date"].astype(str)) != set(panel["trade_date"].astype(str)):
        raise RuntimeError("批次 manifest 与 panel 交易日集合不一致")
    if not manifest["status"].astype(str).eq("ok").all():
        raise RuntimeError("批次 manifest 存在非 ok 快照")
    if not _as_bool(manifest["as_of_check"]).all():
        raise RuntimeError("批次 manifest 存在未通过 as-of 的快照")
    if _as_bool(manifest["deepseek_called"]).any():
        raise RuntimeError("批次 manifest 显示历史快照调用过 DeepSeek")

    for column in (item for item in manifest.columns if item.endswith("_path")):
        values = manifest[column].dropna().astype(str)
        for raw_path in values:
            path = Path(raw_path)
            if not path.exists() or not path.is_file():
                raise RuntimeError(f"manifest 引用文件不存在: {path}")
            if path.stat().st_mtime_ns > sentinel_mtime_ns:
                raise RuntimeError(f"manifest 引用文件晚于完成哨兵，批次可能仍在变化: {path}")


def _load_and_validate_batch(
    root: Path,
) -> tuple[dict[str, pd.DataFrame], dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    in_progress = root / IN_PROGRESS_FILE
    if in_progress.exists():
        raise RuntimeError(f"检测到运行中哨兵 {IN_PROGRESS_FILE}，400日批次尚未完成")
    expected_paths = {
        **{key: root / filename for key, filename in AUDIT_TABLE_FILES.items()},
        **{key: root / filename for key, filename in CONTROL_FILES.items()},
    }
    missing = [path.name for path in expected_paths.values() if not path.exists()]
    if missing:
        raise RuntimeError("400日批次尚未完成，缺少证据/完成哨兵: " + ", ".join(sorted(missing)))

    before = {key: _file_record(path) for key, path in expected_paths.items()}
    tables: dict[str, pd.DataFrame] = {}
    panel = pd.read_csv(expected_paths["panel"], dtype={"trade_date": str})
    panel = _validate_panel(panel)
    tables["panel"] = panel
    for key, required_columns in AGGREGATE_REQUIRED_COLUMNS.items():
        tables[key] = _read_nonempty_csv(expected_paths[key], required_columns)

    quality = json.loads(expected_paths["quality"].read_text(encoding="utf-8"))
    reproducibility = json.loads(expected_paths["reproducibility"].read_text(encoding="utf-8"))
    completion = json.loads(expected_paths["complete"].read_text(encoding="utf-8"))
    manifest = pd.read_csv(expected_paths["manifest_csv"], dtype={"trade_date": str})
    _validate_quality(quality, panel)

    completion_failures: list[str] = []
    if completion.get("status") != "complete":
        completion_failures.append("status != complete")
    if not str(completion.get("batch_run_id") or "").strip():
        completion_failures.append("batch_run_id 为空")
    if int(completion.get("snapshot_count") or -1) != EXPECTED_DAYS:
        completion_failures.append("snapshot_count != 400")
    if str(completion.get("first_trade_date")) != panel["trade_date"].iloc[0]:
        completion_failures.append("first_trade_date 与 panel 不一致")
    if str(completion.get("last_trade_date")) != panel["trade_date"].iloc[-1]:
        completion_failures.append("last_trade_date 与 panel 不一致")
    if completion_failures:
        raise RuntimeError("400日完成哨兵无效: " + "; ".join(completion_failures))

    if int(reproducibility.get("schema_version") or 0) < 1:
        raise RuntimeError("reproducibility 完成哨兵 schema_version 无效")
    parameters = reproducibility.get("parameters") or {}
    expected_parameters = {
        "days": EXPECTED_DAYS,
        "first_trade_date": panel["trade_date"].iloc[0],
        "last_trade_date": panel["trade_date"].iloc[-1],
    }
    for field, expected in expected_parameters.items():
        actual = parameters.get(field)
        if str(actual) != str(expected):
            raise RuntimeError(f"reproducibility 参数不一致: {field}={actual!r}, expected={expected!r}")
    generated_at = _parse_time(reproducibility.get("generated_at"), "reproducibility.generated_at")
    finished_at = _parse_time(quality.get("finished_at"), "quality.finished_at")
    # The reproducibility writer uses second precision while quality currently
    # records microseconds; tolerate only that sub-second serialization loss.
    if (finished_at - generated_at).total_seconds() > 1.0:
        raise RuntimeError("reproducibility 完成哨兵早于质量检查完成时间")
    completion_finished_at = _parse_time(completion.get("finished_at"), "complete.finished_at")
    if completion_finished_at < generated_at or completion_finished_at < finished_at:
        raise RuntimeError("完成哨兵时间早于质量检查或可复现清单")
    sentinel_mtime_ns = expected_paths["complete"].stat().st_mtime_ns
    for key, path in expected_paths.items():
        if key != "complete" and path.stat().st_mtime_ns > sentinel_mtime_ns:
            raise RuntimeError(f"输入文件晚于完成哨兵，批次可能仍在变化: {path.name}")

    completed_inputs = completion.get("input_files")
    if not isinstance(completed_inputs, dict):
        raise RuntimeError("完成哨兵缺少 input_files 哈希清单")
    required_completed_names = {
        path.name
        for key, path in expected_paths.items()
        if key in set(AUDIT_TABLE_FILES) | {"quality", "manifest_csv", "manifest_json"}
    }
    missing_completed_names = sorted(required_completed_names - set(completed_inputs))
    if missing_completed_names:
        raise RuntimeError("完成哨兵缺少输入记录: " + ", ".join(missing_completed_names))
    for filename in sorted(required_completed_names):
        path = root / filename
        actual = _file_record(path)
        declared = completed_inputs.get(filename) or {}
        for field in ("bytes", "mtime_ns", "sha256"):
            if str(declared.get(field)) != str(actual[field]):
                raise RuntimeError(f"完成哨兵输入记录不匹配: {filename}.{field}")
    _validate_manifest(manifest, panel, sentinel_mtime_ns)

    # The JSON and CSV manifests must describe the same number of snapshots.
    manifest_json = json.loads(expected_paths["manifest_json"].read_text(encoding="utf-8"))
    if not isinstance(manifest_json, list) or len(manifest_json) != EXPECTED_DAYS:
        raise RuntimeError("JSON manifest 不是400条记录")

    after = {key: _file_record(path) for key, path in expected_paths.items()}
    if before != after:
        raise RuntimeError("本地证据在读取/校验期间发生变化，拒绝调用")
    return tables, quality, completion, after


def _state_counts(panel: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for column in (
        "style_regime",
        "tail_pressure",
        "risk_direction",
        "breadth_today_state",
        "breadth_5d_state",
        "breadth_20d_state",
        "liquidity_state",
        "research_overheat_candidate_v1",
        "research_icepoint_candidate_v1",
    ):
        for state, count in panel[column].fillna("<missing>").value_counts(dropna=False).items():
            rows.append(
                {
                    "dimension": column,
                    "state": state,
                    "count": int(count),
                    "ratio": float(count / len(panel)),
                }
            )
    return pd.DataFrame(rows)


def _render_prompt(
    tables: dict[str, pd.DataFrame],
    quality: dict[str, Any],
    completion: dict[str, Any],
) -> str:
    panel = tables["panel"]
    compact_columns = list(dict.fromkeys(CORE_PANEL_COLUMNS))
    for horizon in HORIZONS:
        compact_columns.extend(
            [
                f"future_mature_{horizon}d",
                f"future_all_a_return_{horizon}d",
                f"future_all_a_min_return_{horizon}d",
                f"future_all_a_max_return_{horizon}d",
                f"future_all_a_max_drawdown_{horizon}d",
                f"future_stock_median_return_{horizon}d",
                f"future_stock_win_rate_{horizon}d",
                f"future_style_leader_20d_hit_{horizon}d",
                f"future_style_strength_rank_ic_{horizon}d",
            ]
        )
    compact_columns.extend(
        ["future_industry_strong_minus_weak_5d", "future_industry_strong_minus_weak_20d"]
    )
    daily = panel[list(dict.fromkeys(compact_columns))].copy()
    numeric_columns = daily.select_dtypes(include="number").columns
    daily[numeric_columns] = daily[numeric_columns].round(6)

    correlations = tables["correlations"].copy()
    correlations["abs_spearman"] = pd.to_numeric(correlations["spearman"], errors="coerce").abs()
    correlation_top = correlations.sort_values("abs_spearman", ascending=False).head(80)
    missingness = tables["missingness"]
    high_missing = missingness[
        pd.to_numeric(missingness["missing_ratio"], errors="coerce") > 0.05
    ].head(100)
    state_counts = _state_counts(panel)

    return f"""# DeepSeek V4 Pro：A股市场结构 400 交易日独立审计任务

你是独立的量化研究审计员。请审查下面这套 A 股市场结构系统，而不是撰写每日行情复盘。所有 400 个交易日都已包含在“逐日锁定面板”中。请只根据给出的证据推理，明确区分事实、推断和建议；不得给出具体交易指令。

## 强制回答的问题

1. 这 400 日数据是否足以验证系统？还需要多少年/多少交易日，为什么？
2. 当前状态（广度、尾部压力、风险方向、风格、背离）哪些有信息量，哪些区分度不足或命名会误导？
3. 系统能否较好识别“冰点”？必须区分恐慌扩散、高压稳定、高压收缩/修复和假冰点。
4. 当前系统没有正式“过热”状态。研究候选 `overheat_score_v1` 是否有初步依据？如何定义“过热”与“过热衰竭”？
5. 未来 1/5/10/20 日结果是否呈现单调性、稳定性和可行动的效应？注意未来标签高度重叠，不能把 400 行当作 400 个独立样本。
6. 哪些数据质量问题会实质改变结论？特别检查当前股票池幸存者偏差、历史 ST/退市/行业分类缺失、有效股票数与同花顺代理指数滞后。
7. 给出按 P0/P1/P2 排序的系统修改建议、验证设计、通过/停止门槛。

## 口径、规则与边界

- 标的：上证指数结构页；全市场基准使用 `AVG_PRICE.LOCAL` 同花顺平均股价指数（本地股票池等权平均代理）。
- 日期范围：{panel['trade_date'].iloc[0]} 至 {panel['trade_date'].iloc[-1]}，共 {len(panel)} 个交易日。比例和收益字段均以小数表示，例如 `0.01=1%`。
- 批次运行ID：`{completion.get('batch_run_id')}`。只有完成哨兵、输入文件大小/mtime/SHA256与实际文件完全一致时，本提示词才允许生成。
- 每日输入按 signal date 截断；每个快照最多使用 1050 个交易日预热。滚动分位使用过去最多756日、至少60个观测，包含当日值。
- 广度今日状态：上涨比例>=60%、个股中位数/全A等权/A-D均为正，且5日或20日仍弱时记 `strong_repair`；上涨比例>=55%、中位数和A-D为正记 `strong`；上涨比例<=40%、中位数和A-D为负记 `weak`；其余 `neutral`。
- 5/20日广度状态由 A-D、等权收益、个股中位收益三项多数表决；至少两项正为 `strong`，至少两项负为 `weak`；20日弱且MA20上方占比<30%为 `very_weak`。
- 尾部压力由跌超5%、近似跌停、新低20、横截面离散度、5日实现波动五项是否达到各自756日90%分位计数：0=`low`、1-2=`medium`、3=`high`、4-5=`extreme`。
- 风险方向比较今日与前一日的新低20、跌超5%、A-D、NH-NL四项；至少3项改善为 `contracting`，高/极高尾压下称 `repairing`；至少3项恶化为 `expanding`，其余 `stable`。
- 风格5/20/60日状态：绝对收益<=-3%为 `weak`；-3%到-0.5%且相对平均股价为正是 `pullback`，否则 `weak`；-0.5%到+0.5%为 `neutral`；绝对收益>=2%且相对为正是 `strong`；相对为正是 `outperforming`；其余 `recovering`。风格总状态按“5/20日广度同强→broad；同弱且尾压高→broad_weakness；20日领涨风格满足对应强态→value/growth/consumer_led；否则rotation”的固定优先级。
- 背离是“平均股价收益 - 沪深300收益”：差值>=0.3%为个股更强，<=-0.3%为权重更强，其余同步，分别计算1/5/20日。
- 流动性：20日成交额比>=1.5且全A当日涨跌<0.3%为放量滞涨；成交额比>1.1时按全A涨跌记放量上涨/下跌；全A上涨且成交额比<0.8为缩量反弹；其余正常。
- `overheat_score_v1`：上涨比例、MA20覆盖、新高20、涨超5%、5日A/D达到90%分位，加全A20日收益为正，共6项；>=4仅标记候选。
- `icepoint_score_v1`：跌超5%、近似跌停、新低20、离散度、5日波动达到90%分位，加上涨比例和MA20覆盖处于10%分位以下，共7项；>=4仅标记候选。
- 近似涨跌停阈值：主板9.5%、创业板/科创板19.5%、北交所29.5%；仍缺完整历史ST状态和IPO无涨跌幅限制日。
- 每日 DeepSeek 调用为0；每日事实包不含未来字段。`future_*`只存在本批次离线验证面板。
- `future_*_min_return_*` 是相对信号日收盘价的最大不利收益（MAE）；真正路径峰谷回撤为 `future_*_max_drawdown_*`。
- 股票池是当前本地缓存，不是完整point-in-time股票池；缺少历史退市股、历史ST和历史行业分类快照。
- 研究候选阈值虽在读取结果前预声明，但仍没有冻结样本外检验。
- 下列事件研究是重叠的逐日样本，只提供均值/中位数/胜率，未计算HAC、block bootstrap置信区间或多重检验校正。它们只能作为探索性证据，不能据此宣称统计显著或可交易。

## 批次质量检查

```json
{json.dumps(quality, ensure_ascii=False, indent=2)}
```

## 状态分布

```csv
{_csv_block(state_counts)}
```

## 分组事件研究（逐日重叠口径，未做显著性检验）

```csv
{_csv_block(tables['event_study'])}
```

## 去重后的连续事件 episode

```csv
{_csv_block(tables['episodes'])}
```

## 次日状态转移矩阵（长表）

```csv
{_csv_block(tables['transitions'])}
```

## 连续指标与未来结果的相关性（按 |Spearman| 前80；未校正重叠与多重检验）

```csv
{_csv_block(correlation_top)}
```

## 缺失率超过5%的字段

```csv
{_csv_block(high_missing)}
```

## 风格强度的未来横截面验证

```csv
{_csv_block(tables['style_validation'])}
```

## 行业强弱榜（当前20日强弱前三）未来收益差验证

```csv
{_csv_block(tables['industry_validation'])}
```

## 逐日锁定面板（完整400行；含覆盖度、全部滚动分位和全部指数源滞后）

```csv
{_csv_block(daily)}
```

## 输出格式

请输出一份完整中文审计报告，至少包含：

1. 执行摘要（先给结论，注明证据强度）
2. 数据质量与可用样本
3. 状态分布、持续性和转移
4. 尾部压力、风险方向与冰点识别
5. 过热候选与过热衰竭
6. 风格、趋势、背离标签的有效性
7. 失败案例与冲突信号
8. 需要新增的数据和历史范围
9. P0/P1/P2 修改清单
10. 下一轮严格验证方案（训练/冻结测试、episode去重、block bootstrap/HAC、FDR、阈值敏感性）
11. 明确回答“现在是否可以用于预测/仓位/交易”

每个重要结论必须引用样本数和至少一个具体数值；样本很少时必须写“证据不足”。不要把相关性写成因果关系，不得把未做显著性检验的探索结果写成已验证规律。
"""


def _prepare_history_audit(batch_dir: str | Path) -> PreparedHistoryAudit:
    root = Path(batch_dir)
    tables, quality, completion, input_files = _load_and_validate_batch(root)
    prompt = _render_prompt(tables, quality, completion)
    panel = tables["panel"]
    return PreparedHistoryAudit(
        prompt=prompt,
        input_files=input_files,
        first_trade_date=str(panel["trade_date"].iloc[0]),
        last_trade_date=str(panel["trade_date"].iloc[-1]),
        batch_run_id=str(completion["batch_run_id"]),
    )


def build_history_deepseek_prompt(batch_dir: str | Path) -> str:
    """Validate a completed batch and return the immutable audit prompt."""
    return _prepare_history_audit(batch_dir).prompt


def _assert_inputs_unchanged(input_files: dict[str, dict[str, Any]]) -> None:
    changed: list[str] = []
    for key, expected in input_files.items():
        path = Path(expected["path"])
        if not path.exists() or _file_record(path) != expected:
            changed.append(key)
    if changed:
        raise RuntimeError("冻结后的审计输入发生变化: " + ", ".join(changed))


def _audit_code_files() -> dict[str, dict[str, Any]]:
    project_root = Path(__file__).resolve().parents[1]
    paths = {
        "analysis/index_market_history_llm.py": Path(__file__).resolve(),
        "scripts/analyze_market_structure_history_deepseek.py": (
            project_root / "scripts" / "analyze_market_structure_history_deepseek.py"
        ),
    }
    return {name: _file_record(path) for name, path in paths.items()}


def _local_api_preflight(config: dict[str, Any]) -> tuple[str, str]:
    provider = ((config.get("llm_summary") or {}).get("deepseek") or {})
    env_name = str(provider.get("api_key_env") or "DEEPSEEK_API_KEY")
    token = _api_key_from_env_or_dotenv(env_name, config)
    if not token:
        raise RuntimeError(f"缺少 DeepSeek API Key，请设置 {env_name}")
    base_url = str(provider.get("base_url") or "https://api.deepseek.com").rstrip("/")
    _validate_api_endpoint(base_url)
    return token, base_url


def _validate_api_endpoint(base_url: str) -> None:
    parsed = urlparse(base_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "api.deepseek.com"
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise RuntimeError("唯一审计调用只允许使用 https://api.deepseek.com")


def _response_content_and_metadata(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("DeepSeek V4 Pro 未返回 choices")
    choice = choices[0]
    content = str(((choice.get("message") or {}).get("content") or "")).strip()
    if not content:
        raise RuntimeError("DeepSeek V4 Pro 返回正文为空")
    metadata = {
        "model_requested": MODEL_NAME,
        "model_returned": data.get("model"),
        "finish_reason": choice.get("finish_reason"),
        "usage": data.get("usage") or {},
        "response_id": data.get("id"),
        "response_created": data.get("created"),
        "system_fingerprint": data.get("system_fingerprint"),
        "thinking_enabled": True,
        "reasoning_effort": "max",
        "reasoning_chars": int(((data.get("_archive_note") or {}).get("reasoning_chars") or 0)),
    }
    if metadata["model_returned"] != MODEL_NAME:
        raise RuntimeError(f"DeepSeek 返回模型不符: {metadata['model_returned']!r}")
    if metadata["finish_reason"] != "stop":
        raise RuntimeError(f"DeepSeek V4 Pro 未完整正常结束: {metadata['finish_reason']!r}")
    return content, metadata


def _sanitized_response(data: dict[str, Any]) -> dict[str, Any]:
    sanitized = copy.deepcopy(data)
    reasoning_chars = 0
    for choice in sanitized.get("choices") or []:
        message = choice.get("message") or {}
        reasoning_chars += len(str(message.pop("reasoning_content", "") or ""))
    sanitized["_archive_note"] = {
        "reasoning_content_omitted": True,
        "reasoning_chars": reasoning_chars,
    }
    return sanitized


def call_deepseek_v4_pro_audit(
    prompt: str,
    config: dict[str, Any],
    *,
    timeout_seconds: float = 1200,
    max_tokens: int = 32000,
    raw_response_path: Path | None = None,
    token: str | None = None,
    base_url: str | None = None,
) -> tuple[str, dict[str, Any]]:
    if token is None or base_url is None:
        token, base_url = _local_api_preflight(config)
    if not token:
        raise RuntimeError("DeepSeek API Key 为空")
    _validate_api_endpoint(base_url)
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "system",
                "content": "你是严谨的量化研究审计员。区分事实、推断与建议；不得编造样本外事实，不得给交易指令。",
            },
            {"role": "user", "content": prompt},
        ],
        "thinking": {"type": "enabled"},
        "reasoning_effort": "max",
        "max_tokens": int(max_tokens),
        "stream": False,
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=float(timeout_seconds)) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek V4 Pro 请求失败: HTTP {exc.code}: {body[:1000]}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"DeepSeek V4 Pro 网络错误: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("DeepSeek V4 Pro 返回了非JSON响应") from exc

    sanitized = _sanitized_response(data)
    if raw_response_path is not None:
        _atomic_write_json(raw_response_path, sanitized)
    return _response_content_and_metadata(sanitized)


def _write_or_verify_prompt(paths: HistoryLLMAuditPaths, prepared: PreparedHistoryAudit) -> str:
    prompt_hash = hashlib.sha256(prepared.prompt.encode("utf-8")).hexdigest()
    if paths.prompt.exists():
        if _sha256(paths.prompt) != prompt_hash:
            raise RuntimeError("已有提示词与当前冻结证据不一致，拒绝覆盖")
    else:
        _atomic_write_text(paths.prompt, prepared.prompt)
    return prompt_hash


def _read_lock(paths: HistoryLLMAuditPaths) -> dict[str, Any]:
    try:
        return json.loads(paths.call_lock.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("DeepSeek 调用锁损坏，拒绝发起或恢复调用") from exc


def _verify_locked_inputs(lock: dict[str, Any], prepared: PreparedHistoryAudit) -> None:
    locked_inputs = lock.get("input_files")
    if not isinstance(locked_inputs, dict) or locked_inputs != prepared.input_files:
        raise RuntimeError("当前批次输入与调用锁冻结的输入不一致")
    if str(lock.get("batch_run_id")) != prepared.batch_run_id:
        raise RuntimeError("当前批次 run-id 与调用锁不一致")


def _completed_metadata_if_valid(
    paths: HistoryLLMAuditPaths,
    prepared: PreparedHistoryAudit,
    lock: dict[str, Any],
) -> dict[str, Any] | None:
    if not all(path.exists() for path in (paths.response, paths.html, paths.metadata)):
        return None
    metadata = json.loads(paths.metadata.read_text(encoding="utf-8"))
    checks = {
        "prompt_sha256": _sha256(paths.prompt),
        "response_sha256": _sha256(paths.response),
        "raw_response_sha256": _sha256(paths.raw_response),
    }
    for field, actual in checks.items():
        if metadata.get(field) != actual:
            raise RuntimeError(f"已完成审计产物哈希不一致: {field}")
    if metadata.get("input_files") != prepared.input_files:
        raise RuntimeError("已完成审计的输入哈希与当前批次不一致")
    if str(metadata.get("batch_run_id")) != prepared.batch_run_id:
        raise RuntimeError("已完成审计的 batch_run_id 与当前批次不一致")
    if lock.get("status") != "completed":
        raise RuntimeError("最终报告存在但调用锁不是 completed，拒绝自动判定完成")
    return {**metadata, "api_called_this_run": False, "already_completed": True}


def _finalize_from_raw(
    paths: HistoryLLMAuditPaths,
    prepared: PreparedHistoryAudit,
    lock: dict[str, Any],
    *,
    api_called_this_run: bool,
) -> tuple[HistoryLLMAuditPaths, dict[str, Any]]:
    _verify_locked_inputs(lock, prepared)
    if not paths.prompt.exists() or _sha256(paths.prompt) != lock.get("prompt_sha256"):
        raise RuntimeError("冻结提示词缺失或哈希与调用锁不一致")
    _assert_inputs_unchanged(prepared.input_files)
    completed = _completed_metadata_if_valid(paths, prepared, lock)
    if completed is not None:
        return paths, completed

    raw_data = json.loads(paths.raw_response.read_text(encoding="utf-8"))
    content, api_metadata = _response_content_and_metadata(raw_data)
    if paths.response.exists() and paths.response.read_text(encoding="utf-8") != content:
        raise RuntimeError("既有Markdown响应与raw响应不一致，拒绝覆盖")
    _atomic_write_text(paths.response, content)
    _atomic_write_text(paths.html, _markdown_html(content, "DeepSeek V4 Pro：市场结构400日审计"))
    completed_at = datetime.now().astimezone().isoformat(timespec="seconds")
    metadata = {
        **api_metadata,
        "called_at": lock.get("started_at"),
        "completed_at": completed_at,
        "api_called_this_run": bool(api_called_this_run),
        "recovered_from_raw": not api_called_this_run,
        "single_batch_call": True,
        "first_trade_date": prepared.first_trade_date,
        "last_trade_date": prepared.last_trade_date,
        "batch_run_id": prepared.batch_run_id,
        "prompt_chars": len(prepared.prompt),
        "prompt_sha256": _sha256(paths.prompt),
        "response_chars": len(content),
        "response_sha256": _sha256(paths.response),
        "raw_response_sha256": _sha256(paths.raw_response),
        "input_files": prepared.input_files,
        "audit_code_files": lock.get("audit_code_files") or {},
    }
    _atomic_write_json(paths.metadata, metadata)
    completed_lock = {
        **lock,
        "status": "completed",
        "finished_at": completed_at,
        "response_sha256": metadata["response_sha256"],
        "raw_response_sha256": metadata["raw_response_sha256"],
    }
    _atomic_write_json(paths.call_lock, completed_lock)
    return paths, metadata


def prepare_deepseek_history_audit(
    batch_dir: str | Path,
) -> tuple[HistoryLLMAuditPaths, dict[str, Any]]:
    """Validate/freeze evidence and write the prompt without calling the API."""
    paths = history_llm_audit_paths(batch_dir)
    existing = [
        path
        for path in (paths.response, paths.html, paths.metadata, paths.raw_response, paths.call_lock)
        if path.exists()
    ]
    if existing:
        raise RuntimeError("检测到既有调用产物/锁，准备模式拒绝覆盖: " + ", ".join(path.name for path in existing))
    prepared = _prepare_history_audit(batch_dir)
    prompt_hash = _write_or_verify_prompt(paths, prepared)
    _assert_inputs_unchanged(prepared.input_files)
    return paths, {
        "status": "prepared_local_only",
        "api_called": False,
        "prompt_sha256": prompt_hash,
        "prompt_chars": len(prepared.prompt),
        "input_files": prepared.input_files,
        "batch_run_id": prepared.batch_run_id,
        "audit_code_files": _audit_code_files(),
    }


def recover_deepseek_history_audit(
    batch_dir: str | Path,
) -> tuple[HistoryLLMAuditPaths, dict[str, Any]]:
    """Finish artifacts from a successful raw response without any API call."""
    paths = history_llm_audit_paths(batch_dir)
    if not paths.raw_response.exists() or not paths.call_lock.exists():
        raise RuntimeError("没有可恢复的raw响应和调用锁；恢复模式绝不会调用API")
    prepared = _prepare_history_audit(batch_dir)
    lock = _read_lock(paths)
    return _finalize_from_raw(paths, prepared, lock, api_called_this_run=False)


def write_deepseek_history_audit(
    batch_dir: str | Path,
    config: dict[str, Any],
) -> tuple[HistoryLLMAuditPaths, dict[str, Any]]:
    paths = history_llm_audit_paths(batch_dir)

    # Check paid-call artifacts before writing or replacing the prompt.  A raw
    # response always takes the no-network recovery path.
    if paths.raw_response.exists():
        if not paths.call_lock.exists():
            raise RuntimeError("发现raw响应但没有调用锁，拒绝调用或覆盖")
        return recover_deepseek_history_audit(batch_dir)
    existing = [path for path in (paths.response, paths.html, paths.metadata, paths.call_lock) if path.exists()]
    if existing:
        raise RuntimeError("检测到既有调用产物/锁，拒绝重复计费: " + ", ".join(path.name for path in existing))

    prepared = _prepare_history_audit(batch_dir)
    # All non-network preflight checks, including the secret's availability and
    # endpoint allow-list, happen before the atomic billable-call lock.
    token, base_url = _local_api_preflight(config)
    prompt_hash = _write_or_verify_prompt(paths, prepared)
    _assert_inputs_unchanged(prepared.input_files)
    attempt = {
        "status": "calling",
        "model_requested": MODEL_NAME,
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "single_batch_call": True,
        "prompt_sha256": prompt_hash,
        "input_files": prepared.input_files,
        "batch_run_id": prepared.batch_run_id,
        "audit_code_files": _audit_code_files(),
    }
    with paths.call_lock.open("x", encoding="utf-8") as handle:
        json.dump(attempt, handle, ensure_ascii=False, indent=2)
    try:
        call_deepseek_v4_pro_audit(
            prepared.prompt,
            config,
            raw_response_path=paths.raw_response,
            token=token,
            base_url=base_url,
        )
        _assert_inputs_unchanged(prepared.input_files)
        return _finalize_from_raw(paths, prepared, attempt, api_called_this_run=True)
    except Exception as exc:
        failure = {
            **attempt,
            "status": "response_received_postprocess_failed" if paths.raw_response.exists() else "call_failed_or_ambiguous",
            "failed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:1000],
        }
        _atomic_write_json(paths.call_lock, failure)
        raise
