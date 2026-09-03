#!/usr/bin/env python3
"""Finalize a completed market-structure snapshot replay without rebuilding days.

The backfill deliberately writes every dated artifact before it creates any batch
tables.  If the offline-label stage fails, this script reconstructs the snapshot
panel from the compact JSON archives, restores the production rolling-percentile
fields from one full breadth calculation, and then writes the research-only
future labels and audit tables.  It never calls an LLM.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import html
import json
import os
from pathlib import Path
import sys
import uuid
from typing import Any

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analysis.index_market_history import (  # noqa: E402
    PERCENTILE_FIELDS,
    _flatten_snapshot,
    _rolling_percentile_at_end,
    _sha256,
    _validate_as_of,
    add_forward_outcomes,
    add_research_temperature_candidates,
    write_history_audit_tables,
    write_history_reproducibility_manifest,
)
from analysis.index_market_structure import (  # noqa: E402
    build_market_structure,
    load_required_index_frames,
    load_stock_market_panels,
)
from cli.common import load_config  # noqa: E402
from cli.index_cli import _load_ths_frames_for_structure  # noqa: E402
from data.downloader import DataDownloader  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从已归档日快照完成400日离线研究批次（不调用LLM）")
    parser.add_argument("--symbol", default="000001.SH")
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument("--days", type=int, default=400)
    parser.add_argument("--history-bars", type=int, default=1050)
    parser.add_argument("--end", default="20260714", help="截止交易日 YYYYMMDD")
    parser.add_argument("--conflict-variant", default="history_replay_400d")
    parser.add_argument("--batch-dir", default=None)
    return parser.parse_args()


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _file_record(path: Path) -> dict[str, Any]:
    return {
        "bytes": path.stat().st_size,
        "mtime_ns": path.stat().st_mtime_ns,
        "sha256": _sha256(path),
    }


def _clip_frame(frame: pd.DataFrame, end: pd.Timestamp) -> pd.DataFrame:
    if frame is None or frame.empty or "date" not in frame.columns:
        return pd.DataFrame()
    dates = pd.to_datetime(frame["date"], errors="coerce")
    return frame.loc[dates.notna() & dates.le(end)].copy()


def _artifact_paths(archive_dir: Path, prefix: str) -> dict[str, Path]:
    return {
        "report": archive_dir / f"{prefix}_market_structure.html",
        "json": archive_dir / f"{prefix}_market_structure.json",
        "indices": archive_dir / f"{prefix}_market_structure_indices.csv",
        "breadth": archive_dir / f"{prefix}_market_structure_breadth.csv",
        "styles": archive_dir / f"{prefix}_market_structure_styles.csv",
        "style_history": archive_dir / f"{prefix}_market_structure_style_history.csv",
        "industries": archive_dir / f"{prefix}_market_structure_industries.csv",
        "sectors": archive_dir / f"{prefix}_market_structure_sectors.csv",
        "facts": archive_dir / f"{prefix}_llm_input.md",
    }


def _write_archive_index(manifest: pd.DataFrame, batch_dir: Path) -> Path:
    """Write a human-friendly catalog linking all dated snapshots and fact packs."""

    def link(path_value: Any, label: str) -> str:
        path = Path(str(path_value))
        relative = os.path.relpath(path, start=batch_dir).replace(os.sep, "/")
        return f'<a href="{html.escape(relative, quote=True)}">{html.escape(label)}</a>'

    rows = []
    for item in manifest.sort_values("trade_date", ascending=False).to_dict("records"):
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item['trade_date']))}</td>"
            f"<td>{html.escape(str(item['artifact_variant']))}</td>"
            f"<td>{link(item['report_path'], '结构分析')}</td>"
            f"<td>{link(item['facts_path'], 'LLM事实包')}</td>"
            f"<td>{link(item['json_path'], 'JSON')}</td>"
            f"<td>{html.escape(str(int(float(item['valid_stock_count']))))}</td>"
            "</tr>"
        )
    content = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>市场结构400日归档目录</title>
<style>
body{{margin:0;background:#f5f7fb;color:#172033;font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
.wrap{{max-width:1180px;margin:36px auto;padding:0 20px}} h1{{font-size:30px;margin:0 0 8px}} .meta{{color:#667085;margin-bottom:22px}}
input{{width:260px;padding:10px 12px;border:1px solid #cfd6e4;border-radius:8px;margin-bottom:14px}}
.card{{background:#fff;border:1px solid #dfe4ee;border-radius:12px;overflow:hidden;box-shadow:0 3px 14px #1f2a4410}}
table{{width:100%;border-collapse:collapse}} th,td{{padding:11px 14px;border-bottom:1px solid #edf0f5;text-align:left}}
th{{position:sticky;top:0;background:#f8fafc;color:#475467}} tr:hover td{{background:#f8fbff}} a{{color:#175cd3;text-decoration:none}} a:hover{{text-decoration:underline}}
</style></head><body><main class="wrap"><h1>市场结构 400 交易日归档</h1>
<div class="meta">{html.escape(str(manifest['trade_date'].min()))} 至 {html.escape(str(manifest['trade_date'].max()))}；逐日 DeepSeek 调用 0 次；未来标签不进入事实包。</div>
<input id="filter" placeholder="按日期筛选，例如 2026-07" aria-label="按日期筛选">
<div class="card"><table><thead><tr><th>交易日</th><th>归档类型</th><th>报告</th><th>事实包</th><th>数据</th><th>有效股票</th></tr></thead>
<tbody id="rows">{''.join(rows)}</tbody></table></div></main>
<script>const f=document.getElementById('filter');f.addEventListener('input',()=>{{const q=f.value.trim();document.querySelectorAll('#rows tr').forEach(r=>r.hidden=!r.cells[0].textContent.includes(q));}});</script>
</body></html>"""
    path = batch_dir / "market_structure_400d_archive_index.html"
    path.write_text(content, encoding="utf-8")
    return path


def _latest_source_date(structure: dict[str, Any]) -> pd.Timestamp | None:
    candidates: list[pd.Timestamp] = []
    for item in (structure.get("indices") or {}).values():
        value = pd.to_datetime(item.get("date"), errors="coerce")
        if pd.notna(value):
            candidates.append(pd.Timestamp(value))
    for item in (structure.get("styles") or {}).values():
        value = pd.to_datetime(item.get("source_date_max"), errors="coerce")
        if pd.notna(value):
            candidates.append(pd.Timestamp(value))
    return max(candidates) if candidates else None


def _build_records_and_manifest(
    archive_root: Path,
    target_dates: pd.DatetimeIndex,
    breadth_history: pd.DataFrame,
    symbol: str,
    horizon: int,
    history_bars: int,
    conflict_variant: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    prefix = f"{symbol}_h{horizon}"
    records: list[dict[str, Any]] = []
    manifests: list[dict[str, Any]] = []
    metric_match_count = 0
    metric_compare_count = 0
    history = breadth_history.copy()
    history["trade_date"] = pd.to_datetime(history["trade_date"], errors="coerce")
    history = history.dropna(subset=["trade_date"]).sort_values("trade_date")

    for completed, as_of in enumerate(target_dates, start=1):
        date_dir = archive_root / as_of.strftime("%Y-%m-%d")
        variant_dir = date_dir / conflict_variant
        variant_json = variant_dir / f"{prefix}_market_structure.json"
        archive_dir = variant_dir if variant_json.exists() else date_dir
        paths = _artifact_paths(archive_dir, prefix)
        missing = [str(path) for path in paths.values() if not path.is_file() or path.stat().st_size == 0]
        if missing:
            raise FileNotFoundError(f"{as_of.date()} 日归档不完整: {missing}")
        structure = json.loads(paths["json"].read_text(encoding="utf-8"))
        _validate_as_of(structure, as_of)
        metadata = structure.get("archive_metadata") or {}
        if metadata.get("snapshot_type") != "compact_point_in_time":
            raise ValueError(f"{as_of.date()} 不是本次轻量point-in-time快照")
        if metadata.get("llm_called_for_snapshot") is not False:
            raise ValueError(f"{as_of.date()} 快照标记了逐日LLM调用")

        record = _flatten_snapshot(structure)
        available_history = history[history["trade_date"].le(as_of)]
        if available_history.empty or available_history.iloc[-1]["trade_date"] != as_of:
            raise ValueError(f"{as_of.date()} 无法在全量广度历史中对齐")
        latest_history = available_history.iloc[-1]
        latest_snapshot = ((structure.get("breadth") or {}).get("latest") or {})
        for field in PERCENTILE_FIELDS:
            record[f"percentile_{field}"] = (
                _rolling_percentile_at_end(available_history[field])
                if field in available_history.columns else None
            )
            left = pd.to_numeric(pd.Series([latest_snapshot.get(field)]), errors="coerce").iloc[0]
            right = pd.to_numeric(pd.Series([latest_history.get(field)]), errors="coerce").iloc[0]
            if pd.notna(left) or pd.notna(right):
                metric_compare_count += 1
                if pd.notna(left) and pd.notna(right) and bool(np.isclose(left, right, rtol=1e-10, atol=1e-12)):
                    metric_match_count += 1
        pressure_percentiles = [
            record.get("percentile_decline_gt_5_ratio"),
            record.get("percentile_approximate_limit_down_ratio"),
            record.get("percentile_cross_section_dispersion"),
            record.get("percentile_market_realized_volatility_5d"),
            record.get("percentile_new_low_20_ratio"),
        ]
        record["tail_pressure_flag_count_recomputed"] = sum(
            value is not None and pd.notna(value) and float(value) >= 0.90
            for value in pressure_percentiles
        )
        records.append(record)

        source_date = _latest_source_date(structure)
        index_dates = [
            pd.Timestamp(value)
            for item in (structure.get("indices") or {}).values()
            if pd.notna(value := pd.to_datetime(item.get("date"), errors="coerce"))
        ]
        as_of_check = source_date is None or source_date <= as_of
        manifest: dict[str, Any] = {
            "trade_date": as_of.strftime("%Y-%m-%d"),
            "status": "ok" if as_of_check else "failed",
            "deepseek_called": False,
            "history_bars": int(metadata.get("source_warmup_bars") or history_bars),
            "stock_source_max_date": as_of.strftime("%Y-%m-%d"),
            "index_source_max_date": max(index_dates).strftime("%Y-%m-%d") if index_dates else None,
            "ths_source_max_date": source_date.strftime("%Y-%m-%d") if source_date is not None else None,
            "as_of_check": bool(as_of_check),
            "valid_stock_count": latest_snapshot.get("valid_stock_count"),
            "written_count": 0,
            "preserved_count": len(paths),
            "archive_dir": str(archive_dir),
            "artifact_variant": conflict_variant if archive_dir == variant_dir else "standard",
            "source_conflict_preserved": bool(archive_dir == variant_dir),
        }
        for key, path in paths.items():
            manifest[f"{key}_path"] = str(path)
            manifest[f"{key}_bytes"] = path.stat().st_size
            manifest[f"{key}_sha256"] = _sha256(path)
        manifests.append(manifest)
        if completed == 1 or completed % 50 == 0 or completed == len(target_dates):
            print(f"[{completed}/{len(target_dates)}] 已校验并重建 {as_of.date()}", flush=True)

    diagnostics = {
        "daily_breadth_metric_compare_count": metric_compare_count,
        "daily_breadth_metric_match_count": metric_match_count,
        "daily_breadth_metrics_match_full_recompute": bool(
            metric_compare_count > 0 and metric_match_count == metric_compare_count
        ),
    }
    return pd.DataFrame(records), pd.DataFrame(manifests), diagnostics


def main() -> int:
    args = parse_args()
    config = load_config()
    symbol = args.symbol.upper()
    run_id = f"history-finalize-{datetime.now().strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
    reports_root = Path(config["output"]["reports_dir"]) / "index_forecast"
    archive_root = reports_root / "archive"

    downloader = DataDownloader(config)
    primary = downloader.load_index_cache(symbol)
    if primary is None or primary.empty:
        raise SystemExit(f"指数缓存不存在: {symbol}")
    primary = primary.copy()
    primary["date"] = pd.to_datetime(primary["date"], errors="coerce")
    primary = primary.dropna(subset=["date", "close"]).sort_values("date").drop_duplicates("date", keep="last")
    cutoff = pd.to_datetime(args.end, format="%Y%m%d", errors="raise")
    primary = primary[primary["date"].le(cutoff)].reset_index(drop=True)
    if len(primary) < args.days + 260:
        raise SystemExit(f"主指数历史不足: {len(primary)}")
    target_dates = pd.DatetimeIndex(primary["date"].tail(args.days)).sort_values()
    batch_dir = Path(args.batch_dir) if args.batch_dir else (
        archive_root / f"_history_{args.days}_{target_dates[-1].strftime('%Y-%m-%d')}"
    )
    batch_dir.mkdir(parents=True, exist_ok=True)
    in_progress_path = batch_dir / "market_structure_400d_in_progress.json"
    complete_path = batch_dir / "market_structure_400d_complete.json"
    quality_path = batch_dir / "market_structure_400d_quality_checks.json"
    deepseek_prompt = batch_dir / "deepseek_v4_pro_market_structure_400d_prompt.md"
    paid_artifacts = [
        batch_dir / "deepseek_v4_pro_market_structure_400d_audit.md",
        batch_dir / "deepseek_v4_pro_market_structure_400d_audit.html",
        batch_dir / "deepseek_v4_pro_market_structure_400d_metadata.json",
        batch_dir / "deepseek_v4_pro_market_structure_400d_raw_response.json",
        batch_dir / ".deepseek_v4_pro_market_structure_400d_call.lock",
    ]
    existing_paid = [path.name for path in paid_artifacts if path.exists()]
    if existing_paid:
        raise SystemExit(
            "批次已经存在DeepSeek调用/报告产物，拒绝重写证据以免报告与输入失配: "
            + ", ".join(existing_paid)
        )
    # A prepare-only prompt is provisional and has incurred no API call.  Once
    # source/code hashes change, discard it so the next local preparation can
    # freeze a prompt against the new completion marker.
    deepseek_prompt.unlink(missing_ok=True)
    complete_path.unlink(missing_ok=True)
    started = datetime.now().astimezone()
    _atomic_json(
        in_progress_path,
        {
            "status": "in_progress",
            "batch_run_id": run_id,
            "started_at": started.isoformat(timespec="microseconds"),
            "network_calls": 0,
        },
    )
    _atomic_json(
        quality_path,
        {
            "status": "in_progress",
            "batch_run_id": run_id,
            "started_at": started.isoformat(timespec="microseconds"),
        },
    )

    first_position = int(primary.index[primary["date"].eq(target_dates[0])][0])
    load_start = max(0, first_position - args.history_bars + 1)
    load_dates = pd.DatetimeIndex(primary.loc[load_start:, "date"])
    panels = load_stock_market_panels(
        config["data"]["cache_dir"],
        Path(config["data"].get("meta_dir", "data/meta")) / "stocks.csv",
        dates=load_dates,
    )
    if panels.close.empty:
        raise SystemExit("个股缓存为空")
    index_frames = load_required_index_frames(
        config["data"]["cache_dir"], primary, symbol, as_of=target_dates[-1],
    )
    ths_frames, _ths_names, _ths_industries = _load_ths_frames_for_structure(config)
    ths_frames = {
        key: clipped
        for key, frame in ths_frames.items()
        if not (clipped := _clip_frame(frame, target_dates[-1])).empty
    }

    print("重算一次全区间广度历史，用于恢复每个快照的756行滚动百分位……", flush=True)
    breadth_source = build_market_structure(
        symbol,
        index_frames,
        panels,
        ths_index_frames={},
        as_of=target_dates[-1],
    )
    breadth_history = pd.DataFrame((breadth_source.get("breadth") or {}).get("history") or [])
    snapshot_panel, manifest_frame, diagnostics = _build_records_and_manifest(
        archive_root,
        target_dates,
        breadth_history,
        symbol,
        int(args.horizon),
        int(args.history_bars),
        str(args.conflict_variant),
    )
    snapshot_panel = add_forward_outcomes(
        snapshot_panel,
        panels.close,
        index_frames,
        ths_index_frames=ths_frames,
    )
    snapshot_panel = add_research_temperature_candidates(snapshot_panel)
    table_paths = write_history_audit_tables(snapshot_panel, batch_dir)

    manifest_frame = manifest_frame.sort_values("trade_date").reset_index(drop=True)
    manifest_csv = batch_dir / "market_structure_400d_manifest.csv"
    manifest_json = batch_dir / "market_structure_400d_manifest.json"
    manifest_frame.to_csv(manifest_csv, index=False)
    _atomic_json(manifest_json, manifest_frame.to_dict("records"))
    archive_index_path = _write_archive_index(manifest_frame, batch_dir)

    path_columns = [column for column in manifest_frame.columns if column.endswith("_path")]
    all_paths_exist = all(
        Path(path).is_file() and Path(path).stat().st_size > 0
        for column in path_columns
        for path in manifest_frame[column]
    )
    facts_have_no_future = all(
        "future_" not in Path(path).read_text(encoding="utf-8")
        for path in manifest_frame["facts_path"]
    )
    count_columns = [
        "breadth_advance_count", "breadth_decline_count", "breadth_flat_count", "breadth_valid_stock_count",
    ]
    total = sum(pd.to_numeric(snapshot_panel[column], errors="coerce") for column in count_columns[:3])
    valid = pd.to_numeric(snapshot_panel[count_columns[3]], errors="coerce")
    breadth_counts_reconcile = bool(total.eq(valid).fillna(False).all())
    pressure_count = pd.to_numeric(snapshot_panel["tail_pressure_flag_count_recomputed"], errors="coerce")
    recomputed_level = pd.Series("low", index=snapshot_panel.index, dtype="object")
    recomputed_level[pressure_count.ge(1)] = "medium"
    recomputed_level[pressure_count.ge(3)] = "high"
    recomputed_level[pressure_count.ge(4)] = "extreme"
    tail_pressure_matches = bool(recomputed_level.eq(snapshot_panel["tail_pressure"].astype(str)).all())
    maturity = {
        str(horizon): {
            "expected": int(args.days - horizon),
            "actual": int(snapshot_panel[f"future_mature_{horizon}d"].fillna(False).astype(bool).sum()),
            "tail_unmatured": bool(
                (~snapshot_panel[f"future_mature_{horizon}d"].tail(horizon).fillna(False).astype(bool)).all()
            ),
            "mature_all_a_labels_non_null": bool(
                snapshot_panel.loc[
                    snapshot_panel[f"future_mature_{horizon}d"].fillna(False).astype(bool),
                    f"future_all_a_return_{horizon}d",
                ].notna().all()
            ),
        }
        for horizon in (1, 5, 10, 20)
    }
    maturity_passed = all(
        item["expected"] == item["actual"]
        and item["tail_unmatured"]
        and item["mature_all_a_labels_non_null"]
        for item in maturity.values()
    )
    archive_llm_disabled = bool(manifest_frame["deepseek_called"].eq(False).all())
    as_of_passed = bool(manifest_frame["as_of_check"].eq(True).all())
    snapshot_count_passed = bool(
        len(snapshot_panel) == args.days
        and snapshot_panel["trade_date"].nunique() == args.days
        and manifest_frame["trade_date"].nunique() == args.days
    )
    checks = {
        "snapshot_count_passed": snapshot_count_passed,
        "all_as_of_checks_passed": as_of_passed,
        "all_required_files_exist": bool(all_paths_exist),
        "facts_contain_no_future_labels": bool(facts_have_no_future),
        "breadth_counts_reconcile": breadth_counts_reconcile,
        "tail_pressure_recomputed_matches_production": tail_pressure_matches,
        "daily_breadth_metrics_match_full_recompute": diagnostics[
            "daily_breadth_metrics_match_full_recompute"
        ],
        "future_maturity_checks_passed": maturity_passed,
        "per_snapshot_deepseek_calls_zero": archive_llm_disabled,
    }
    passed = all(checks.values())
    reproducibility_path = write_history_reproducibility_manifest(
        batch_dir,
        config,
        PROJECT_ROOT,
        {
            "symbol": symbol,
            "horizon": int(args.horizon),
            "days": int(args.days),
            "history_bars": int(args.history_bars),
            "first_trade_date": target_dates[0].strftime("%Y-%m-%d"),
            "last_trade_date": target_dates[-1].strftime("%Y-%m-%d"),
            "source": "reconstructed_from_completed_daily_archives",
            "conflict_variant": str(args.conflict_variant),
        },
    )
    quality = {
        "status": "passed" if passed else "failed",
        "batch_run_id": run_id,
        "snapshot_count": int(len(snapshot_panel)),
        "unique_trade_dates": int(snapshot_panel["trade_date"].nunique()),
        "first_trade_date": snapshot_panel["trade_date"].min(),
        "last_trade_date": snapshot_panel["trade_date"].max(),
        **checks,
        **diagnostics,
        "maturity": maturity,
        "per_snapshot_deepseek_calls": 0,
        "isolated_source_conflict_count": int(manifest_frame["source_conflict_preserved"].sum()),
        "isolated_source_conflict_dates": manifest_frame.loc[
            manifest_frame["source_conflict_preserved"], "trade_date"
        ].tolist(),
        "board_limit_thresholds": {"main_board": 0.095, "chinext_star": 0.195, "bse": 0.295},
        "analysis_snapshot_source": "fresh_point_in_time_replay_then_archive_reconstruction",
        "original_daily_artifacts_preserved": True,
        "history_bars": int(args.history_bars),
        "stock_file_count": int(panels.close.shape[1]),
        "stock_price_adjustment": config.get("data", {}).get("stock_adj"),
        "source_limitations": [
            "current_local_stock_universe_not_full_point_in_time",
            "missing_delisted_stocks_and_historical_st_status",
            "current_tushare_industry_classification_used_for_history",
            "overlapping_forward_horizons_reduce_effective_sample_size",
        ],
        "started_at": started.isoformat(timespec="microseconds"),
        "finished_at": datetime.now().astimezone().isoformat(timespec="microseconds"),
    }
    _atomic_json(quality_path, quality)

    readme = batch_dir / "README.md"
    readme.write_text(
        "\n".join(
            [
                f"# {args.days} 日市场结构历史回填",
                "",
                f"- 标的：{symbol}",
                f"- 日期：{quality['first_trade_date']} 至 {quality['last_trade_date']}",
                f"- 每日快照：{args.days} 份结构JSON/HTML与LLM事实包，均按日期归档",
                "- 每日 DeepSeek：0 次；未来标签仅存在批次离线面板",
                f"- 质量门禁：{quality['status']}",
                f"- 冲突隔离：{quality['isolated_source_conflict_count']} 日",
                "- 限制：当前股票池、退市股、历史ST与历史行业分类并非完整point-in-time口径。",
                "",
                "## 批次文件",
                "",
                *[
                    f"- `{path.name}`"
                    for path in [archive_index_path, manifest_csv, manifest_json, quality_path, reproducibility_path, *table_paths.values()]
                ],
            ]
        ),
        encoding="utf-8",
    )

    completion_inputs = {
        path.name: _file_record(path)
        for path in [archive_index_path, manifest_csv, manifest_json, quality_path, reproducibility_path, *table_paths.values()]
    }
    completion = {
        "status": "complete" if passed else "failed",
        "batch_run_id": run_id,
        "snapshot_count": int(len(snapshot_panel)),
        "first_trade_date": quality["first_trade_date"],
        "last_trade_date": quality["last_trade_date"],
        "finished_at": datetime.now().astimezone().isoformat(timespec="microseconds"),
        "network_calls": 0,
        "input_files": completion_inputs,
    }
    _atomic_json(complete_path, completion)
    in_progress_path.unlink(missing_ok=True)
    print(f"质量检查: {quality['status']}")
    print(f"完成哨兵: {complete_path}")
    print(f"离线面板: {table_paths['panel']}")
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
