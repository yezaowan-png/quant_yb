#!/usr/bin/env python3
"""One-off point-in-time market-structure history backfill.

The script never calls DeepSeek.  It produces one compact archive snapshot and one
LLM fact package per trading day, then builds an offline validation panel.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import multiprocessing as mp
from pathlib import Path
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analysis.index_market_history import (  # noqa: E402
    MarketStructureHistoryContext,
    _assert_not_frozen_history_target,
    _write_csv,
    _write_text,
    add_forward_outcomes,
    add_research_temperature_candidates,
    build_history_snapshot_worker,
    configure_history_worker,
    write_history_reproducibility_manifest,
    write_history_audit_tables,
)
from analysis.index_market_structure import load_required_index_frames, load_stock_market_panels  # noqa: E402
from cli.common import load_config  # noqa: E402
from cli.index_cli import (  # noqa: E402
    _index_name,
    _load_ths_frames_for_structure,
    _style_proxy_config,
    _ths_config,
)
from data.downloader import DataDownloader  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="回填历史市场结构快照（不调用 DeepSeek）")
    parser.add_argument("--symbol", default="000001.SH")
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument("--days", type=int, default=400)
    parser.add_argument("--history-bars", type=int, default=1050)
    parser.add_argument("--end", default=None, help="截止日期 YYYYMMDD；默认使用本地缓存最后日期")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--overwrite", action="store_true", help="覆盖已有日期归档；默认保护已有备份")
    parser.add_argument(
        "--refresh-generated", action="store_true",
        help="仅刷新本脚本生成的轻量快照；遇到原有日常归档时写入隔离变体目录",
    )
    parser.add_argument("--conflict-variant", default="history_replay_400d")
    return parser.parse_args()


def _history_batch_paths(
    config: dict,
    days: int,
    last_trade_date: pd.Timestamp,
) -> tuple[Path, Path]:
    """Resolve a writable batch path before any replay artifact is created."""
    archive_root = Path(config["output"]["reports_dir"]) / "index_forecast" / "archive"
    batch_dir = archive_root / f"_history_{int(days)}_{last_trade_date.strftime('%Y-%m-%d')}"
    _assert_not_frozen_history_target(batch_dir)
    return archive_root, batch_dir


def main() -> int:
    args = parse_args()
    if args.days <= 0 or args.history_bars < 260:
        raise SystemExit("--days 必须大于0，--history-bars 必须至少260")
    config = load_config()
    symbol = args.symbol.upper()
    downloader = DataDownloader(config)
    primary = downloader.load_index_cache(symbol)
    if primary is None or primary.empty:
        raise SystemExit(f"指数缓存不存在: {symbol}")
    primary = primary.copy()
    primary["date"] = pd.to_datetime(primary["date"], errors="coerce")
    primary = primary.dropna(subset=["date", "close"]).sort_values("date").drop_duplicates("date", keep="last")
    if args.end:
        cutoff = pd.to_datetime(args.end, format="%Y%m%d", errors="raise")
        primary = primary[primary["date"] <= cutoff]
    if len(primary) < args.days + 260:
        raise SystemExit(f"主指数历史不足: 需要至少 {args.days + 260} 日，实际 {len(primary)} 日")

    target_dates = pd.DatetimeIndex(primary["date"].tail(args.days)).sort_values()
    # Use positional lookup after resetting so the earliest target has a complete
    # warm-up window for 756-day percentiles plus 250-day raw indicators.
    primary = primary.reset_index(drop=True)
    first_target_position = int(primary.index[primary["date"] == target_dates[0]][0])
    load_start_position = max(0, first_target_position - args.history_bars + 1)
    load_dates = pd.DatetimeIndex(primary.loc[load_start_position:, "date"])
    if len(load_dates[load_dates <= target_dates[0]]) < args.history_bars:
        raise SystemExit("最早目标日期的预热历史不足，不能保证滚动百分位口径一致")

    archive_root, batch_dir = _history_batch_paths(
        config,
        args.days,
        target_dates[-1],
    )
    batch_dir.mkdir(parents=True, exist_ok=True)
    print(f"历史回填: {symbol}，{len(target_dates)} 个交易日")
    print(f"日期范围: {target_dates[0].date()} ~ {target_dates[-1].date()}")
    print(f"预热窗口: {args.history_bars} 日；逐日 DeepSeek: 禁用")
    print(f"批次目录: {batch_dir}")

    panels = load_stock_market_panels(
        config["data"]["cache_dir"],
        Path(config["data"].get("meta_dir", "data/meta")) / "stocks.csv",
        dates=load_dates,
    )
    if panels.close.empty:
        raise SystemExit("本地个股缓存为空")
    index_frames = load_required_index_frames(
        config["data"]["cache_dir"], primary, symbol, as_of=target_dates[-1],
    )
    ths_frames, ths_names, ths_industry_symbols = _load_ths_frames_for_structure(config)
    ths_cfg = _ths_config(config)
    context = MarketStructureHistoryContext(
        symbol=symbol,
        name=_index_name(config, symbol),
        horizon=args.horizon,
        history_bars=args.history_bars,
        archive_root=archive_root,
        index_frames=index_frames,
        panels=panels,
        ths_index_frames=ths_frames,
        ths_index_names=ths_names,
        ths_industry_symbols=ths_industry_symbols,
        ths_style_config=_style_proxy_config(config),
        ths_industry_min_available=int((ths_cfg.get("industries") or {}).get("min_available", 20)),
        ths_style_min_history_bars=int(ths_cfg.get("style_min_history_bars", 60)),
        overwrite=bool(args.overwrite),
        refresh_generated=bool(args.refresh_generated),
        conflict_variant=str(args.conflict_variant),
    )
    configure_history_worker(context)
    manifests: list[dict] = []
    records: list[dict] = []
    date_strings = [date.strftime("%Y-%m-%d") for date in target_dates]
    workers = max(1, min(int(args.workers), len(date_strings)))
    started = datetime.now().astimezone()
    if workers == 1:
        iterator = map(build_history_snapshot_worker, date_strings)
        for completed, (manifest, record) in enumerate(iterator, start=1):
            manifests.append(manifest)
            records.append(record)
            if completed == 1 or completed % 10 == 0 or completed == len(date_strings):
                print(f"[{completed}/{len(date_strings)}] {manifest['trade_date']} 完成", flush=True)
    else:
        # Fork preserves the large read-only pandas panels via copy-on-write.  This
        # script targets the project's macOS/Linux environment and is not part of
        # the nightly automation.
        with mp.get_context("fork").Pool(processes=workers, maxtasksperchild=25) as pool:
            for completed, (manifest, record) in enumerate(
                pool.imap_unordered(build_history_snapshot_worker, date_strings, chunksize=1), start=1
            ):
                manifests.append(manifest)
                records.append(record)
                if completed == 1 or completed % 10 == 0 or completed == len(date_strings):
                    print(f"[{completed}/{len(date_strings)}] 最近完成 {manifest['trade_date']}", flush=True)

    manifest_frame = pd.DataFrame(manifests).sort_values("trade_date").reset_index(drop=True)
    snapshot_panel = pd.DataFrame(records).sort_values("trade_date").reset_index(drop=True)
    snapshot_panel = add_forward_outcomes(
        snapshot_panel, panels.close, index_frames, ths_index_frames=ths_frames,
    )
    snapshot_panel = add_research_temperature_candidates(snapshot_panel)
    table_paths = write_history_audit_tables(snapshot_panel, batch_dir)
    manifest_csv = batch_dir / "market_structure_400d_manifest.csv"
    manifest_json = batch_dir / "market_structure_400d_manifest.json"
    _write_csv(manifest_csv, manifest_frame, overwrite=True)
    _write_text(
        manifest_json,
        json.dumps(manifest_frame.to_dict("records"), ensure_ascii=False, indent=2),
        overwrite=True,
    )

    required_files_ok = bool(
        manifest_frame["as_of_check"].all()
        and (manifest_frame["status"] == "ok").all()
        and manifest_frame["trade_date"].nunique() == args.days
        and all(Path(path).exists() for column in [item for item in manifest_frame.columns if item.endswith("_path")] for path in manifest_frame[column])
    )
    facts_have_no_future_labels = True
    for path in manifest_frame["facts_path"]:
        if "future_" in Path(path).read_text(encoding="utf-8"):
            facts_have_no_future_labels = False
            break
    count_columns = [
        "breadth_advance_count", "breadth_decline_count", "breadth_flat_count", "breadth_valid_stock_count",
    ]
    breadth_counts_reconcile = False
    if all(column in snapshot_panel.columns for column in count_columns):
        total = sum(pd.to_numeric(snapshot_panel[column], errors="coerce") for column in count_columns[:3])
        valid = pd.to_numeric(snapshot_panel[count_columns[3]], errors="coerce")
        breadth_counts_reconcile = bool(total.eq(valid).fillna(False).all())
    pressure_count = pd.to_numeric(
        snapshot_panel.get("tail_pressure_flag_count_recomputed"), errors="coerce",
    )
    recomputed_level = pd.Series("low", index=snapshot_panel.index, dtype="object")
    recomputed_level[pressure_count.ge(1)] = "medium"
    recomputed_level[pressure_count.ge(3)] = "high"
    recomputed_level[pressure_count.ge(4)] = "extreme"
    tail_pressure_recomputed_matches = bool(
        recomputed_level.eq(snapshot_panel["tail_pressure"].astype(str)).all()
    )
    quality = {
        "status": "passed" if required_files_ok and facts_have_no_future_labels and breadth_counts_reconcile and tail_pressure_recomputed_matches else "failed",
        "snapshot_count": int(len(manifest_frame)),
        "unique_trade_dates": int(manifest_frame["trade_date"].nunique()),
        "first_trade_date": manifest_frame["trade_date"].min(),
        "last_trade_date": manifest_frame["trade_date"].max(),
        "all_as_of_checks_passed": bool(manifest_frame["as_of_check"].all()),
        "all_required_files_exist": required_files_ok,
        "facts_contain_no_future_labels": facts_have_no_future_labels,
        "breadth_counts_reconcile": breadth_counts_reconcile,
        "tail_pressure_recomputed_matches_production": tail_pressure_recomputed_matches,
        "board_limit_thresholds": {
            "main_board": 0.095,
            "chinext_star": 0.195,
            "bse": 0.295,
        },
        "per_snapshot_deepseek_calls": int(manifest_frame["deepseek_called"].sum()),
        "isolated_source_conflict_count": int(manifest_frame["source_conflict_preserved"].sum()),
        "isolated_source_conflict_dates": manifest_frame.loc[
            manifest_frame["source_conflict_preserved"], "trade_date"
        ].tolist(),
        "analysis_snapshot_source": "fresh_point_in_time_replay",
        "original_daily_artifacts_preserved": True,
        "history_bars": int(args.history_bars),
        "stock_file_count": int(panels.close.shape[1]),
        "stock_price_adjustment": config.get("data", {}).get("stock_adj"),
        "max_index_lag_calendar_days": {
            column.removeprefix("index_").removesuffix("_lag_calendar_days"): int(
                pd.to_numeric(snapshot_panel[column], errors="coerce").max()
            )
            for column in snapshot_panel.columns
            if column.startswith("index_") and column.endswith("_lag_calendar_days")
            and pd.to_numeric(snapshot_panel[column], errors="coerce").notna().any()
        },
        "source_limitations": [
            "current_local_stock_universe_not_full_point_in_time",
            "missing_delisted_stocks_and_historical_st_status",
            "current_tushare_industry_classification_used_for_history",
            "overlapping_forward_horizons_reduce_effective_sample_size",
        ],
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    quality_path = batch_dir / "market_structure_400d_quality_checks.json"
    _write_text(
        quality_path,
        json.dumps(quality, ensure_ascii=False, indent=2),
        overwrite=True,
    )
    reproducibility_path = write_history_reproducibility_manifest(
        batch_dir,
        config,
        PROJECT_ROOT,
        {
            "symbol": symbol,
            "horizon": int(args.horizon),
            "days": int(args.days),
            "history_bars": int(args.history_bars),
            "first_trade_date": quality["first_trade_date"],
            "last_trade_date": quality["last_trade_date"],
            "refresh_generated": bool(args.refresh_generated),
            "conflict_variant": str(args.conflict_variant),
        },
    )
    readme = batch_dir / "README.md"
    _write_text(
        readme,
        "\n".join(
            [
                f"# {args.days} 日市场结构历史回填",
                "",
                f"- 标的：{symbol}",
                f"- 日期：{quality['first_trade_date']} 至 {quality['last_trade_date']}",
                f"- 个股缓存列数：{panels.close.shape[1]}",
                f"- 每日预热：{args.history_bars} 个交易日",
                "- 每日输出：轻量HTML、结构JSON、指数/广度/风格/行业/金融板块CSV、LLM事实包",
                "- 每日 DeepSeek：未调用",
                f"- 原日常归档冲突隔离：{quality['isolated_source_conflict_count']} 日（保留原文件，批次重放写入变体子目录）",
                "- 未来收益标签：只存在批次离线验证面板，不写入每日事实包",
                "- 限制：当前股票池、退市股、历史ST和历史行业分类并非完整point-in-time口径。",
                "",
                "## 批次文件",
                "",
                *[f"- `{path.name}`" for path in [manifest_csv, manifest_json, quality_path, reproducibility_path, *table_paths.values()]],
            ]
        ),
        overwrite=True,
    )
    print(f"质量检查: {quality['status']}")
    print(f"归档清单: {manifest_csv}")
    print(f"离线验证面板: {table_paths['panel']}")
    return 0 if quality["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
