"""Point-in-time history backfill and offline audit helpers for market structure.

This module is deliberately separate from the nightly forecast command.  It loads
the source panels once, replays deterministic as-of snapshots, and never calls an
LLM while building the daily archive.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


FROZEN_MARKET_STRUCTURE_HISTORY_DIR = "_history_400_2026-07-14"


def _assert_not_frozen_history_target(path: Path) -> None:
    """The audited 400-day v1 corpus is immutable after its completion seal."""
    resolved = Path(path).expanduser().resolve()
    if FROZEN_MARKET_STRUCTURE_HISTORY_DIR in resolved.parts:
        raise PermissionError(
            f"历史审计目录已冻结，拒绝写入: {resolved}"
        )

from analysis.index_market_llm import build_llm_fact_markdown
from analysis.index_market_structure import (
    ALL_A_INDEX_NAME,
    ALL_A_INDEX_SYMBOL,
    StockMarketPanels,
    build_market_structure,
)
from visual.index_forecast_report import generate_market_structure_snapshot_report


INDEX_PREFIXES = {
    "000001.SH": "sse",
    "000300.SH": "hs300",
    "000016.SH": "sse50",
    "000905.SH": "csi500",
    "000852.SH": "csi1000",
    "932000.CSI": "csi2000",
    "399006.SZ": "chinext",
    "000688.SH": "star50",
    ALL_A_INDEX_SYMBOL: "all_a",
}

STYLE_KEY_NAMES = {
    "value": "权重价值",
    "securities": "证券风险偏好",
    "growth": "科技成长",
    "consumer": "消费",
    "small_cap": "小盘题材",
}

PERCENTILE_FIELDS = (
    "advance_ratio",
    "decline_ratio",
    "pct_above_ma20",
    "pct_above_ma50",
    "pct_above_ma200",
    "normalized_ad_5d",
    "normalized_ad_20d",
    "new_high_20_ratio",
    "new_low_20_ratio",
    "advance_gt_5_ratio",
    "decline_gt_5_ratio",
    "approximate_limit_up_ratio",
    "approximate_limit_down_ratio",
    "cross_section_dispersion",
    "market_realized_volatility_5d",
)


@dataclass
class MarketStructureHistoryContext:
    symbol: str
    name: str
    horizon: int
    history_bars: int
    archive_root: Path
    index_frames: dict[str, pd.DataFrame]
    panels: StockMarketPanels
    ths_index_frames: dict[str, pd.DataFrame]
    ths_index_names: dict[str, str]
    ths_industry_symbols: set[str]
    ths_style_config: dict[str, Any]
    ths_industry_min_available: int = 20
    ths_style_min_history_bars: int = 60
    overwrite: bool = False
    refresh_generated: bool = False
    conflict_variant: str = "history_replay_400d"


_WORKER_CONTEXT: MarketStructureHistoryContext | None = None


def configure_history_worker(context: MarketStructureHistoryContext) -> None:
    """Install the read-only context before forking worker processes."""
    global _WORKER_CONTEXT
    _WORKER_CONTEXT = context


def _frame_between(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    if frame is None or frame.empty or "date" not in frame.columns:
        return pd.DataFrame()
    dates = pd.to_datetime(frame["date"], errors="coerce")
    return frame.loc[dates.notna() & dates.ge(start) & dates.le(end)].copy()


def _rolling_percentile_at_end(values: pd.Series, window: int = 756, min_periods: int = 60) -> float | None:
    # Match production `_rolling_percentile`: the window is the most recent
    # trading-day rows, not the most recent N non-null observations.  Production
    # uses numpy comparison inside rolling.apply, so null rows compare False and
    # remain in the percentile denominator once min_periods is satisfied.
    recent = pd.to_numeric(values, errors="coerce").tail(window)
    if recent.notna().sum() < min_periods or recent.empty or pd.isna(recent.iloc[-1]):
        return None
    return float(np.mean(recent.to_numpy(dtype="float64") <= float(recent.iloc[-1])))


def _flatten_snapshot(structure: dict[str, Any]) -> dict[str, Any]:
    state = structure.get("market_structure") or {}
    trend = state.get("trend") or {}
    breadth_state = state.get("breadth") or {}
    risk = state.get("risk") or {}
    style_state = state.get("style") or {}
    divergence = state.get("divergence") or {}
    latest = ((structure.get("breadth") or {}).get("latest") or {})
    record: dict[str, Any] = {
        "trade_date": structure.get("date"),
        "style_regime": state.get("style_regime"),
        "style_regime_name": state.get("style_regime_name"),
        "legacy_style_regime": state.get("legacy_style_regime"),
        "breadth_today_state": breadth_state.get("today_state"),
        "breadth_5d_state": breadth_state.get("short_5d_state"),
        "breadth_20d_state": breadth_state.get("medium_20d_state"),
        "breadth_summary": breadth_state.get("summary"),
        "tail_pressure": risk.get("pressure_level"),
        "risk_direction": risk.get("risk_direction"),
        "new_low_direction": risk.get("new_low_direction"),
        "large_decline_direction": risk.get("large_decline_direction"),
        "ad_direction": risk.get("ad_direction"),
        "nhnl_direction": risk.get("nhnl_direction"),
        "large_cap_daily_trend": trend.get("large_cap_daily"),
        "large_cap_weekly_trend": trend.get("large_cap_weekly"),
        "growth_daily_trend": trend.get("growth_daily"),
        "growth_weekly_trend": trend.get("growth_weekly"),
        "style_leader_5d": style_state.get("leader_5d"),
        "style_leader_20d": style_state.get("leader_20d"),
        "style_leader_60d": style_state.get("leader_60d"),
        "divergence_1d": divergence.get("one_day"),
        "divergence_5d": divergence.get("five_day"),
        "divergence_20d": divergence.get("twenty_day"),
        "divergence_summary": divergence.get("summary"),
        "liquidity_state": (structure.get("liquidity") or {}).get("state"),
        "data_quality_flag_count": len(structure.get("data_quality_flags") or []),
        "data_quality_flags": "|".join(str(item) for item in structure.get("data_quality_flags") or []),
    }
    for key, value in latest.items():
        if isinstance(value, (str, int, float, bool, np.number)) or value is None:
            record[f"breadth_{key}"] = value

    breadth_history = pd.DataFrame((structure.get("breadth") or {}).get("history") or [])
    for field in PERCENTILE_FIELDS:
        record[f"percentile_{field}"] = (
            _rolling_percentile_at_end(breadth_history[field]) if field in breadth_history.columns else None
        )

    for item in (structure.get("indices") or {}).values():
        prefix = INDEX_PREFIXES.get(str(item.get("symbol", "")).upper())
        if not prefix:
            continue
        for key in (
            "date", "close", "return_1d", "return_5d", "return_10d", "return_20d", "return_60d",
            "daily_trend", "weekly_trend", "amount_ratio_20d", "distance_high_20d", "distance_low_20d",
        ):
            record[f"index_{prefix}_{key}"] = item.get(key)
        metric_date = pd.to_datetime(item.get("date"), errors="coerce")
        snapshot_date = pd.to_datetime(structure.get("date"), errors="coerce")
        record[f"index_{prefix}_lag_calendar_days"] = (
            int((snapshot_date - metric_date).days)
            if pd.notna(snapshot_date) and pd.notna(metric_date) else None
        )

    for item in (structure.get("styles") or {}).values():
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        for field in (
            "return_1d", "return_5d", "return_20d", "return_60d", "relative_all_a_20d", "strength",
            "strength_state", "state_5d", "state_20d", "state_60d", "momentum_direction", "data_coverage",
            "source_date_min", "source_date_max", "source_lag_calendar_days",
        ):
            record[f"style_{key}_{field}"] = item.get(field)

    for key, value in (structure.get("relative_strength") or {}).items():
        record[f"relative_{key}"] = value

    pressure_percentiles = [
        record.get("percentile_decline_gt_5_ratio"),
        record.get("percentile_approximate_limit_down_ratio"),
        record.get("percentile_cross_section_dispersion"),
        record.get("percentile_market_realized_volatility_5d"),
        record.get("percentile_new_low_20_ratio"),
    ]
    record["tail_pressure_flag_count_recomputed"] = sum(
        value is not None and pd.notna(value) and float(value) >= 0.90 for value in pressure_percentiles
    )

    rankings = structure.get("industry_rankings") or {}
    for side, rows in (("strong", rankings.get("strongest") or []), ("weak", rankings.get("weakest") or [])):
        for rank, item in enumerate(rows[:3], start=1):
            record[f"industry_{side}_{rank}_name"] = item.get("industry") or item.get("name")
            record[f"industry_{side}_{rank}_symbol"] = item.get("symbol")
            record[f"industry_{side}_{rank}_return_20d"] = item.get("return_20d")
    return record


def _compact_structure(structure: dict[str, Any], history_bars: int) -> dict[str, Any]:
    """Drop repeated time-series arrays while preserving every current snapshot field."""
    compact = dict(structure)
    compact["index_history"] = []
    compact["breadth"] = dict(structure.get("breadth") or {})
    compact["breadth"]["history"] = []
    compact["style_history"] = []
    compact["archive_metadata"] = {
        "snapshot_type": "compact_point_in_time",
        "history_arrays_omitted": True,
        "source_warmup_bars": int(history_bars),
        "llm_called_for_snapshot": False,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    return compact


def _json_default(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _write_text(path: Path, text: str, overwrite: bool) -> str:
    _assert_not_frozen_history_target(path)
    if path.exists() and not overwrite:
        return "preserved"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return "written"


def _write_csv(path: Path, frame: pd.DataFrame, overwrite: bool) -> str:
    _assert_not_frozen_history_target(path)
    if path.exists() and not overwrite:
        return "preserved"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return "written"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_generated_compact_snapshot(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    metadata = payload.get("archive_metadata") or {}
    return bool(
        metadata.get("snapshot_type") == "compact_point_in_time"
        and metadata.get("llm_called_for_snapshot") is False
    )


def _validate_as_of(structure: dict[str, Any], as_of: pd.Timestamp) -> None:
    if pd.to_datetime(structure.get("date"), errors="coerce") != as_of:
        raise ValueError(f"快照日期不一致: expected={as_of.date()} actual={structure.get('date')}")
    for item in (structure.get("indices") or {}).values():
        date = pd.to_datetime(item.get("date"), errors="coerce")
        if pd.notna(date) and date > as_of:
            raise ValueError(f"指数 {item.get('symbol')} 泄漏未来日期 {date.date()}")
    for container, key in (
        (structure, "index_history"),
        (structure.get("breadth") or {}, "history"),
        (structure, "style_history"),
    ):
        rows = container.get(key) or []
        for row in rows:
            date = pd.to_datetime(row.get("trade_date"), errors="coerce")
            if pd.notna(date) and date > as_of:
                raise ValueError(f"{key} 泄漏未来日期 {date.date()}")


def build_history_snapshot_worker(date_value: str | pd.Timestamp) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build and archive one daily snapshot; designed for a forked process pool."""
    context = _WORKER_CONTEXT
    if context is None:
        raise RuntimeError("历史回填 worker 尚未配置")
    as_of = pd.Timestamp(date_value).normalize()
    available = context.panels.close.index[pd.to_datetime(context.panels.close.index) <= as_of]
    available = pd.DatetimeIndex(available).sort_values().unique()
    window_dates = available[-int(context.history_bars):]
    if len(window_dates) < 260:
        raise ValueError(f"{as_of.date()} 预热历史不足: {len(window_dates)}")
    start = pd.Timestamp(window_dates[0])
    sliced_panels = StockMarketPanels(
        close=context.panels.close.reindex(window_dates),
        amount=context.panels.amount.reindex(index=window_dates, columns=context.panels.close.columns),
        metadata=context.panels.metadata,
        open=(
            context.panels.open.reindex(index=window_dates, columns=context.panels.close.columns)
            if getattr(context.panels, "open", None) is not None else None
        ),
        high=(
            context.panels.high.reindex(index=window_dates, columns=context.panels.close.columns)
            if getattr(context.panels, "high", None) is not None else None
        ),
        low=(
            context.panels.low.reindex(index=window_dates, columns=context.panels.close.columns)
            if getattr(context.panels, "low", None) is not None else None
        ),
        volume=(
            context.panels.volume.reindex(index=window_dates, columns=context.panels.close.columns)
            if getattr(context.panels, "volume", None) is not None else None
        ),
    )
    index_frames = {
        symbol: clipped
        for symbol, frame in context.index_frames.items()
        if not (clipped := _frame_between(frame, start, as_of)).empty
    }
    ths_frames = {
        symbol: clipped
        for symbol, frame in context.ths_index_frames.items()
        if not (clipped := _frame_between(frame, start, as_of)).empty
    }
    structure = build_market_structure(
        context.symbol,
        index_frames,
        sliced_panels,
        ths_index_frames=ths_frames,
        ths_index_names=context.ths_index_names,
        ths_industry_symbols=context.ths_industry_symbols,
        ths_style_config=context.ths_style_config,
        ths_industry_min_available=context.ths_industry_min_available,
        ths_style_min_history_bars=context.ths_style_min_history_bars,
        as_of=as_of,
    )
    _validate_as_of(structure, as_of)
    record = _flatten_snapshot(structure)
    compact = _compact_structure(structure, context.history_bars)
    base_archive_dir = context.archive_root / as_of.strftime("%Y-%m-%d")
    prefix = f"{context.symbol.upper()}_h{int(context.horizon)}"
    base_json = base_archive_dir / f"{prefix}_market_structure.json"
    generated_compact = _is_generated_compact_snapshot(base_json)
    source_conflict_preserved = bool(
        context.refresh_generated and base_json.exists() and not generated_compact
    )
    archive_dir = (
        base_archive_dir / context.conflict_variant
        if source_conflict_preserved else base_archive_dir
    )
    _assert_not_frozen_history_target(archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)
    effective_overwrite = bool(
        context.overwrite
        or (context.refresh_generated and (generated_compact or source_conflict_preserved))
    )
    paths = {
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
    for path in paths.values():
        _assert_not_frozen_history_target(path)
    statuses: dict[str, str] = {}
    statuses["json"] = _write_text(
        paths["json"], json.dumps(compact, ensure_ascii=False, indent=2, default=_json_default), effective_overwrite,
    )
    statuses["indices"] = _write_csv(paths["indices"], pd.DataFrame(compact.get("indices", {}).values()), effective_overwrite)
    latest_breadth = ((compact.get("breadth") or {}).get("latest") or {})
    statuses["breadth"] = _write_csv(paths["breadth"], pd.DataFrame([latest_breadth]), effective_overwrite)
    statuses["styles"] = _write_csv(paths["styles"], pd.DataFrame(compact.get("styles", {}).values()), effective_overwrite)
    latest_style_history = (structure.get("style_history") or [])[-1:]
    statuses["style_history"] = _write_csv(paths["style_history"], pd.DataFrame(latest_style_history), effective_overwrite)
    rankings = structure.get("industry_rankings") or {}
    industry_rows = [dict(item, ranking_side=side, ranking_position=rank) for side, items in (("strongest", rankings.get("strongest") or []), ("weakest", rankings.get("weakest") or [])) for rank, item in enumerate(items, start=1)]
    statuses["industries"] = _write_csv(paths["industries"], pd.DataFrame(industry_rows), effective_overwrite)
    sector_rows = [dict(item, sector=name) for name, item in (structure.get("sector_details") or {}).items()]
    statuses["sectors"] = _write_csv(paths["sectors"], pd.DataFrame(sector_rows), effective_overwrite)
    facts = build_llm_fact_markdown(structure, symbol=context.symbol, name=context.name)
    statuses["facts"] = _write_text(paths["facts"], facts, effective_overwrite)
    if not paths["report"].exists() or effective_overwrite:
        generate_market_structure_snapshot_report(
            compact, paths["report"], context.symbol, context.name, paths["facts"].name,
        )
        statuses["report"] = "written"
    else:
        statuses["report"] = "preserved"

    max_index_date = max(
        (pd.to_datetime(frame["date"], errors="coerce").max() for frame in index_frames.values()),
        default=pd.NaT,
    )
    max_ths_date = max(
        (pd.to_datetime(frame["date"], errors="coerce").max() for frame in ths_frames.values()),
        default=pd.NaT,
    )
    manifest = {
        "trade_date": as_of.strftime("%Y-%m-%d"),
        "status": "ok",
        "deepseek_called": False,
        "history_bars": len(window_dates),
        "stock_source_max_date": pd.Timestamp(window_dates[-1]).strftime("%Y-%m-%d"),
        "index_source_max_date": max_index_date.strftime("%Y-%m-%d") if pd.notna(max_index_date) else None,
        "ths_source_max_date": max_ths_date.strftime("%Y-%m-%d") if pd.notna(max_ths_date) else None,
        "as_of_check": bool(
            pd.Timestamp(window_dates[-1]) <= as_of
            and (pd.isna(max_index_date) or max_index_date <= as_of)
            and (pd.isna(max_ths_date) or max_ths_date <= as_of)
        ),
        "valid_stock_count": latest_breadth.get("valid_stock_count"),
        "written_count": sum(value == "written" for value in statuses.values()),
        "preserved_count": sum(value == "preserved" for value in statuses.values()),
        "archive_dir": str(archive_dir),
        "artifact_variant": context.conflict_variant if source_conflict_preserved else "standard",
        "source_conflict_preserved": source_conflict_preserved,
    }
    for key, path in paths.items():
        manifest[f"{key}_path"] = str(path)
        manifest[f"{key}_bytes"] = path.stat().st_size if path.exists() else 0
        manifest[f"{key}_sha256"] = _sha256(path) if path.exists() else None
    return manifest, record


def _series_from_index_frame(frame: pd.DataFrame | None, calendar: pd.DatetimeIndex) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(np.nan, index=calendar, dtype="float64")
    dates = pd.to_datetime(frame["date"], errors="coerce")
    values = pd.to_numeric(frame["close"], errors="coerce")
    return pd.Series(values.to_numpy(), index=dates).dropna().sort_index().reindex(calendar)


def _coerce_bool_series(values: pd.Series | Iterable[Any]) -> pd.Series:
    """Parse booleans without treating non-empty ``"False"`` strings as true.

    CSV round-trips can produce native booleans, 0/1 numbers, or strings.  Keep
    unknown/missing values nullable so callers can decide whether they belong in
    a denominator instead of silently coercing them to either class.
    """
    source = values.copy() if isinstance(values, pd.Series) else pd.Series(values)
    if pd.api.types.is_bool_dtype(source.dtype):
        return source.astype("boolean")
    result = pd.Series(pd.NA, index=source.index, dtype="boolean")
    numeric = pd.to_numeric(source, errors="coerce")
    result.loc[numeric.eq(1)] = True
    result.loc[numeric.eq(0)] = False
    normalized = source.astype("string").str.strip().str.lower()
    result.loc[normalized.isin({"true", "yes", "y", "t"})] = True
    result.loc[normalized.isin({"false", "no", "n", "f"})] = False
    return result


def _coerce_bool_value(value: Any, default: bool = False) -> bool:
    parsed = _coerce_bool_series(pd.Series([value])).iloc[0]
    return default if pd.isna(parsed) else bool(parsed)


def _forward_path_extreme(series: pd.Series, horizon: int, kind: str) -> pd.Series:
    """Return MAE/MFE from signal close over the next ``horizon`` bars.

    The signal close is the zero-return baseline.  Including it guarantees that
    MAE is never positive and MFE is never negative, while ``skipna=False`` keeps
    incomplete future paths invalid.
    """
    if kind not in {"min", "max"}:
        raise ValueError(f"未知路径极值类型: {kind}")
    paths = pd.concat(
        [series.shift(-step) / series - 1.0 for step in range(0, horizon + 1)],
        axis=1,
    )
    return paths.min(axis=1, skipna=False) if kind == "min" else paths.max(axis=1, skipna=False)


def _forward_path_max_drawdown(series: pd.Series, horizon: int) -> pd.Series:
    """Peak-to-trough drawdown over signal close plus the next N closes."""
    paths = pd.concat([series.shift(-step) for step in range(0, horizon + 1)], axis=1)
    values = paths.to_numpy(dtype="float64")
    running_peak = np.maximum.accumulate(values, axis=1)
    drawdowns = values / running_peak - 1.0
    complete = np.isfinite(values).all(axis=1)
    result = np.full(len(paths), np.nan, dtype="float64")
    result[complete] = np.nanmin(drawdowns[complete], axis=1)
    return pd.Series(result, index=paths.index)


def add_forward_outcomes(
    snapshot_panel: pd.DataFrame,
    close_panel: pd.DataFrame,
    index_frames: dict[str, pd.DataFrame],
    horizons: Iterable[int] = (1, 5, 10, 20),
    ths_index_frames: dict[str, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    """Append offline-only future labels; these never enter a production fact package."""
    result = snapshot_panel.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce")
    result = result.dropna(subset=["trade_date"]).sort_values("trade_date").reset_index(drop=True)
    calendar = pd.DatetimeIndex(close_panel.index).sort_values().unique()
    target_dates = pd.DatetimeIndex(result["trade_date"])
    index_series = {
        prefix: _series_from_index_frame(index_frames.get(symbol), calendar)
        for symbol, prefix in (("000001.SH", "sse"), ("000300.SH", "hs300"), (ALL_A_INDEX_SYMBOL, "all_a"))
    }
    close = close_panel.reindex(calendar)
    target_index = pd.DatetimeIndex(result["trade_date"])
    style_daily = {
        key: pd.Series(
            pd.to_numeric(result.get(f"style_{key}_return_1d"), errors="coerce").to_numpy(),
            index=target_index,
        )
        for key in STYLE_KEY_NAMES
        if f"style_{key}_return_1d" in result.columns
    }
    ths_series = {
        str(symbol).upper(): _series_from_index_frame(frame, calendar)
        for symbol, frame in (ths_index_frames or {}).items()
        if frame is not None and not frame.empty
    }
    for horizon in horizons:
        for prefix, series in index_series.items():
            result[f"future_{prefix}_return_{horizon}d"] = (series.shift(-horizon) / series - 1.0).reindex(target_dates).to_numpy()
            result[f"future_{prefix}_min_return_{horizon}d"] = _forward_path_extreme(series, horizon, "min").reindex(target_dates).to_numpy()
            result[f"future_{prefix}_max_return_{horizon}d"] = _forward_path_extreme(series, horizon, "max").reindex(target_dates).to_numpy()
            result[f"future_{prefix}_max_drawdown_{horizon}d"] = _forward_path_max_drawdown(series, horizon).reindex(target_dates).to_numpy()
        cross_section = (close.shift(-horizon) / close - 1.0).reindex(target_dates)
        result[f"future_stock_mean_return_{horizon}d"] = cross_section.mean(axis=1, skipna=True).to_numpy()
        result[f"future_stock_median_return_{horizon}d"] = cross_section.median(axis=1, skipna=True).to_numpy()
        result[f"future_stock_win_rate_{horizon}d"] = cross_section.gt(0).sum(axis=1).div(cross_section.notna().sum(axis=1).replace(0, np.nan)).to_numpy()
        result[f"future_stock_q10_return_{horizon}d"] = cross_section.quantile(0.10, axis=1).to_numpy()
        result[f"future_stock_valid_count_{horizon}d"] = cross_section.notna().sum(axis=1).to_numpy()
        target_positions = calendar.get_indexer(target_dates)
        mature = (target_positions >= 0) & (target_positions + horizon < len(calendar))
        result[f"future_mature_{horizon}d"] = mature
        for column in ("breadth_advance_ratio", "breadth_pct_above_ma20", "breadth_new_low_20_ratio"):
            if column in result.columns:
                values = pd.Series(pd.to_numeric(result[column], errors="coerce").to_numpy(), index=target_dates)
                result[f"future_change_{column}_{horizon}d"] = (values.shift(-horizon) - values).reindex(target_dates).to_numpy()

        future_style_columns: list[str] = []
        for key, daily_returns in style_daily.items():
            future_path = pd.concat(
                [1.0 + daily_returns.shift(-step) for step in range(1, horizon + 1)], axis=1,
            )
            future_return = future_path.prod(axis=1, min_count=horizon) - 1.0
            column = f"future_style_{key}_return_{horizon}d"
            result[column] = future_return.reindex(target_dates).to_numpy()
            result[f"future_style_{key}_relative_all_a_{horizon}d"] = (
                result[column] - result[f"future_all_a_return_{horizon}d"]
            )
            future_style_columns.append(column)
        if future_style_columns:
            future_style = result[future_style_columns].apply(pd.to_numeric, errors="coerce")
            complete = future_style.notna().all(axis=1)
            best_key = pd.Series(pd.NA, index=result.index, dtype="object")
            if complete.any():
                best_column = future_style.loc[complete].idxmax(axis=1, skipna=False)
                best_key.loc[complete] = best_column.str.extract(
                    r"future_style_(.+)_return_", expand=False,
                )
            result[f"future_style_best_{horizon}d"] = best_key
            current_leader_key = result.get("style_leader_20d", pd.Series(index=result.index, dtype="object")).map(
                {name: key for key, name in STYLE_KEY_NAMES.items()}
            )
            result[f"future_style_leader_20d_hit_{horizon}d"] = (
                current_leader_key.eq(best_key).where(complete & current_leader_key.notna())
            )
            rank_ics: list[float] = []
            for row_index in result.index:
                current = pd.Series(
                    {
                        key: pd.to_numeric(result.at[row_index, f"style_{key}_strength"], errors="coerce")
                        if f"style_{key}_strength" in result.columns else np.nan
                        for key in STYLE_KEY_NAMES
                    },
                    dtype="float64",
                )
                future = pd.Series(
                    {
                        key: pd.to_numeric(result.at[row_index, f"future_style_{key}_return_{horizon}d"], errors="coerce")
                        if f"future_style_{key}_return_{horizon}d" in result.columns else np.nan
                        for key in STYLE_KEY_NAMES
                    },
                    dtype="float64",
                )
                valid = current.notna() & future.notna()
                rank_ics.append(
                    current[valid].rank().corr(future[valid].rank()) if valid.sum() >= 3 else np.nan
                )
            result[f"future_style_strength_rank_ic_{horizon}d"] = rank_ics

        if ths_series and horizon in {5, 20}:
            ths_forward = pd.DataFrame(
                {symbol: series.shift(-horizon) / series - 1.0 for symbol, series in ths_series.items()},
                index=calendar,
            )
            for side in ("strong", "weak"):
                values: list[float] = []
                valid_counts: list[int] = []
                for _, row in result.iterrows():
                    date = pd.Timestamp(row["trade_date"])
                    symbols = [
                        str(row.get(f"industry_{side}_{rank}_symbol") or "").upper()
                        for rank in range(1, 4)
                    ]
                    observations = [
                        ths_forward.at[date, symbol]
                        for symbol in symbols
                        if symbol in ths_forward.columns and date in ths_forward.index
                        and pd.notna(ths_forward.at[date, symbol])
                    ]
                    valid_counts.append(len(observations))
                    values.append(float(np.mean(observations)) if len(observations) == 3 else np.nan)
                result[f"future_industry_{side}3_return_{horizon}d"] = values
                result[f"future_industry_{side}3_valid_count_{horizon}d"] = valid_counts
            result[f"future_industry_strong_minus_weak_{horizon}d"] = (
                result[f"future_industry_strong3_return_{horizon}d"]
                - result[f"future_industry_weak3_return_{horizon}d"]
            )
    result["trade_date"] = result["trade_date"].dt.strftime("%Y-%m-%d")
    return result


def add_research_temperature_candidates(panel: pd.DataFrame) -> pd.DataFrame:
    """Add predeclared research-only overheat/ice-point scores."""
    result = panel.copy()

    def numeric(column: str) -> pd.Series:
        if column not in result.columns:
            return pd.Series(np.nan, index=result.index, dtype="float64")
        return pd.to_numeric(result[column], errors="coerce")

    def ge(column: str, threshold: float) -> pd.Series:
        return numeric(column).ge(threshold).fillna(False)

    def le(column: str, threshold: float) -> pd.Series:
        return numeric(column).le(threshold).fillna(False)

    hot_flags = [
        ge("percentile_advance_ratio", 0.90),
        ge("percentile_pct_above_ma20", 0.90),
        ge("percentile_new_high_20_ratio", 0.90),
        ge("percentile_advance_gt_5_ratio", 0.90),
        ge("percentile_normalized_ad_5d", 0.90),
        numeric("index_all_a_return_20d").gt(0).fillna(False),
    ]
    cold_flags = [
        ge("percentile_decline_gt_5_ratio", 0.90),
        ge("percentile_approximate_limit_down_ratio", 0.90),
        ge("percentile_new_low_20_ratio", 0.90),
        ge("percentile_cross_section_dispersion", 0.90),
        ge("percentile_market_realized_volatility_5d", 0.90),
        le("percentile_advance_ratio", 0.10),
        le("percentile_pct_above_ma20", 0.10),
    ]
    result["research_overheat_score_v1"] = sum(flag.astype(int) for flag in hot_flags)
    result["research_icepoint_score_v1"] = sum(flag.astype(int) for flag in cold_flags)
    result["research_overheat_candidate_v1"] = result["research_overheat_score_v1"].ge(4)
    result["research_icepoint_candidate_v1"] = result["research_icepoint_score_v1"].ge(4)
    return result


def build_group_event_study(panel: pd.DataFrame, group_columns: Iterable[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for group_column in group_columns:
        if group_column not in panel.columns:
            continue
        for value, group in panel.groupby(group_column, dropna=False):
            row: dict[str, Any] = {"dimension": group_column, "state": str(value), "count": len(group)}
            for horizon in (1, 5, 10, 20):
                mature_column = f"future_mature_{horizon}d"
                mature_mask = (
                    _coerce_bool_series(group[mature_column]).fillna(False).astype(bool)
                    if mature_column in group.columns else pd.Series(False, index=group.index)
                )
                mature = group.loc[mature_mask]
                for outcome, alias in (
                    (f"future_all_a_return_{horizon}d", "all_a_return"),
                    (f"future_stock_median_return_{horizon}d", "stock_median_return"),
                    (f"future_all_a_min_return_{horizon}d", "all_a_min_return"),
                ):
                    values = (
                        pd.to_numeric(mature[outcome], errors="coerce").dropna()
                        if outcome in mature.columns else pd.Series(dtype="float64")
                    )
                    row[f"{alias}_{horizon}d_n"] = len(values)
                    row[f"{alias}_{horizon}d_mean"] = values.mean() if not values.empty else np.nan
                    row[f"{alias}_{horizon}d_median"] = values.median() if not values.empty else np.nan
                    if alias == "all_a_return":
                        row[f"{alias}_{horizon}d_win_rate"] = values.gt(0).mean() if not values.empty else np.nan
                min_column = f"future_all_a_min_return_{horizon}d"
                min_values = (
                    pd.to_numeric(mature[min_column], errors="coerce").dropna()
                    if min_column in mature.columns else pd.Series(dtype="float64")
                )
                row[f"mae_le_3pct_{horizon}d_rate"] = min_values.le(-0.03).mean() if not min_values.empty else np.nan
                row[f"mae_le_5pct_{horizon}d_rate"] = min_values.le(-0.05).mean() if not min_values.empty else np.nan
                drawdown_column = f"future_all_a_max_drawdown_{horizon}d"
                drawdown_values = (
                    pd.to_numeric(mature[drawdown_column], errors="coerce").dropna()
                    if drawdown_column in mature.columns else pd.Series(dtype="float64")
                )
                row[f"max_drawdown_{horizon}d_mean"] = drawdown_values.mean() if not drawdown_values.empty else np.nan
                row[f"max_drawdown_le_3pct_{horizon}d_rate"] = drawdown_values.le(-0.03).mean() if not drawdown_values.empty else np.nan
                row[f"max_drawdown_le_5pct_{horizon}d_rate"] = drawdown_values.le(-0.05).mean() if not drawdown_values.empty else np.nan
            rows.append(row)
    return pd.DataFrame(rows)


def build_state_transitions(panel: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for column in columns:
        if column not in panel.columns:
            continue
        current = panel[column].astype(str)
        following = current.shift(-1)
        table = pd.crosstab(current, following)
        for source in table.index:
            total = int(table.loc[source].sum())
            for target, count in table.loc[source].items():
                if int(count) == 0:
                    continue
                rows.append(
                    {"dimension": column, "from_state": source, "to_state": target, "count": int(count), "probability": float(count / total) if total else np.nan}
                )
    return pd.DataFrame(rows)


def build_feature_correlations(panel: pd.DataFrame) -> pd.DataFrame:
    feature_columns = [
        "breadth_advance_ratio", "breadth_pct_above_ma20", "breadth_pct_above_ma50",
        "breadth_pct_above_ma200", "breadth_normalized_ad_5d", "breadth_normalized_ad_20d",
        "breadth_new_high_20_ratio", "breadth_new_low_20_ratio", "breadth_decline_gt_5_ratio",
        "breadth_approximate_limit_down_ratio", "breadth_cross_section_dispersion",
        "breadth_market_realized_volatility_5d", "breadth_amount_ratio_20",
        "research_overheat_score_v1", "research_icepoint_score_v1",
    ]
    outcomes = [
        f"future_{target}_{metric}_{horizon}d"
        for horizon in (1, 5, 10, 20)
        for target, metric in (
            ("all_a", "return"),
            ("all_a", "min_return"),
            ("all_a", "max_drawdown"),
            ("stock_median", "return"),
        )
    ]
    rows: list[dict[str, Any]] = []
    for feature in feature_columns:
        if feature not in panel.columns:
            continue
        x = pd.to_numeric(panel[feature], errors="coerce")
        for outcome in outcomes:
            if outcome not in panel.columns:
                continue
            y = pd.to_numeric(panel[outcome], errors="coerce")
            valid = x.notna() & y.notna()
            ranked_x = x[valid].rank(method="average")
            ranked_y = y[valid].rank(method="average")
            has_variation = bool(
                valid.sum() >= 10
                and x[valid].nunique(dropna=True) > 1
                and y[valid].nunique(dropna=True) > 1
            )
            rows.append(
                {
                    "feature": feature,
                    "outcome": outcome,
                    "sample_count": int(valid.sum()),
                    "spearman": ranked_x.corr(ranked_y, method="pearson") if has_variation else np.nan,
                    "pearson": x[valid].corr(y[valid], method="pearson") if has_variation else np.nan,
                }
            )
    return pd.DataFrame(rows)


def build_style_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """Convert wide style fields into date-by-style rows for easier auditing."""
    known_keys = ("value", "securities", "growth", "consumer", "small_cap")
    style_keys = [key for key in known_keys if any(column.startswith(f"style_{key}_") for column in panel.columns)]
    rows: list[dict[str, Any]] = []
    for _, source in panel.iterrows():
        for key in style_keys:
            prefix = f"style_{key}_"
            values = {column[len(prefix):]: source.get(column) for column in panel.columns if column.startswith(prefix)}
            if values:
                future = {
                    f"future_return_{horizon}d": source.get(f"future_style_{key}_return_{horizon}d")
                    for horizon in (1, 5, 10, 20)
                }
                future.update(
                    {
                        f"future_relative_all_a_{horizon}d": source.get(
                            f"future_style_{key}_relative_all_a_{horizon}d"
                        )
                        for horizon in (1, 5, 10, 20)
                    }
                )
                rows.append({"trade_date": source.get("trade_date"), "style_key": key, **values, **future})
    return pd.DataFrame(rows)


def build_style_validation(panel: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def numeric(column: str) -> pd.Series:
        if column not in panel.columns:
            return pd.Series(np.nan, index=panel.index, dtype="float64")
        return pd.to_numeric(panel[column], errors="coerce")

    for horizon in (1, 5, 10, 20):
        hit_column = f"future_style_leader_20d_hit_{horizon}d"
        hit = (
            _coerce_bool_series(panel[hit_column]).astype("Float64")
            if hit_column in panel.columns else pd.Series(np.nan, index=panel.index, dtype="float64")
        )
        rank_ic = numeric(f"future_style_strength_rank_ic_{horizon}d")
        rows.append(
            {
                "dimension": "all_styles",
                "horizon": horizon,
                "leader_hit_n": int(hit.notna().sum()),
                "leader_hit_rate": hit.mean(),
                "strength_rank_ic_n": int(rank_ic.notna().sum()),
                "strength_rank_ic_mean": rank_ic.mean(),
                "strength_rank_ic_median": rank_ic.median(),
            }
        )
        for key, name in STYLE_KEY_NAMES.items():
            outcome = numeric(f"future_style_{key}_relative_all_a_{horizon}d")
            is_leader = panel.get("style_leader_20d", pd.Series(index=panel.index, dtype="object")).eq(name)
            selected = outcome[is_leader].dropna()
            rows.append(
                {
                    "dimension": key,
                    "horizon": horizon,
                    "leader_hit_n": int(selected.size),
                    "leader_hit_rate": np.nan,
                    "strength_rank_ic_n": np.nan,
                    "strength_rank_ic_mean": selected.mean() if not selected.empty else np.nan,
                    "strength_rank_ic_median": selected.median() if not selected.empty else np.nan,
                }
            )
    return pd.DataFrame(rows)


def build_industry_validation(panel: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for horizon in (5, 20):
        spread = (
            pd.to_numeric(panel[f"future_industry_strong_minus_weak_{horizon}d"], errors="coerce").dropna()
            if f"future_industry_strong_minus_weak_{horizon}d" in panel.columns
            else pd.Series(dtype="float64")
        )
        rows.append(
            {
                "horizon": horizon,
                "sample_count": int(spread.size),
                "strong_minus_weak_mean": spread.mean() if not spread.empty else np.nan,
                "strong_minus_weak_median": spread.median() if not spread.empty else np.nan,
                "strong_outperforms_rate": spread.gt(0).mean() if not spread.empty else np.nan,
                "q10": spread.quantile(0.10) if not spread.empty else np.nan,
                "q90": spread.quantile(0.90) if not spread.empty else np.nan,
            }
        )
    return pd.DataFrame(rows)


def build_future_outcomes_long(panel: pd.DataFrame) -> pd.DataFrame:
    """Normalize offline future labels into one date-target-horizon row."""
    rows: list[dict[str, Any]] = []
    for _, source in panel.iterrows():
        for horizon in (1, 5, 10, 20):
            mature = _coerce_bool_value(source.get(f"future_mature_{horizon}d"), default=False)
            for target in ("all_a", "hs300", "sse"):
                rows.append(
                    {
                        "signal_date": source.get("trade_date"), "target": target, "horizon": horizon,
                        "valid_label": mature and pd.notna(source.get(f"future_{target}_return_{horizon}d")),
                        "fwd_return": source.get(f"future_{target}_return_{horizon}d"),
                        "fwd_mae_from_signal": source.get(f"future_{target}_min_return_{horizon}d"),
                        "fwd_max_drawdown": source.get(f"future_{target}_max_drawdown_{horizon}d"),
                        "fwd_max_runup": source.get(f"future_{target}_max_return_{horizon}d"),
                    }
                )
            rows.extend(
                [
                    {
                        "signal_date": source.get("trade_date"), "target": target, "horizon": horizon,
                        "valid_label": mature and pd.notna(source.get(column)), "fwd_return": source.get(column),
                        "fwd_mae_from_signal": None, "fwd_max_drawdown": None, "fwd_max_runup": None,
                    }
                    for target, column in (
                        ("stock_equal_weight", f"future_stock_mean_return_{horizon}d"),
                        ("stock_median", f"future_stock_median_return_{horizon}d"),
                    )
                ]
            )
    return pd.DataFrame(rows)


def build_event_episodes(panel: pd.DataFrame) -> pd.DataFrame:
    """Collapse consecutive event days so one market episode is not over-counted."""
    work = panel.sort_values("trade_date").reset_index(drop=True)
    high_pressure = work["tail_pressure"].isin(["high", "extreme"])
    weak_medium = work["breadth_20d_state"].isin(["weak", "very_weak"])
    definitions = {
        "panic_expanding": high_pressure & work["risk_direction"].eq("expanding"),
        "icepoint_repair_candidate": high_pressure & weak_medium & work["risk_direction"].isin(["contracting", "repairing"]),
        "temperature_icepoint_v1": _coerce_bool_series(
            work["research_icepoint_candidate_v1"]
        ).fillna(False).astype(bool),
        "temperature_overheat_v1": _coerce_bool_series(
            work["research_overheat_candidate_v1"]
        ).fillna(False).astype(bool),
    }
    rows: list[dict[str, Any]] = []
    for event_type, mask in definitions.items():
        episode_id = 0
        position = 0
        while position < len(work):
            if not bool(mask.iloc[position]):
                position += 1
                continue
            start = position
            while position + 1 < len(work) and bool(mask.iloc[position + 1]):
                position += 1
            end = position
            episode_id += 1
            source = work.iloc[start]
            row: dict[str, Any] = {
                "event_type": event_type,
                "episode_id": episode_id,
                "start_date": source.get("trade_date"),
                "end_date": work.iloc[end].get("trade_date"),
                "duration_days": end - start + 1,
                "tail_pressure": source.get("tail_pressure"),
                "risk_direction": source.get("risk_direction"),
                "breadth_20d_state": source.get("breadth_20d_state"),
                "overheat_score": source.get("research_overheat_score_v1"),
                "icepoint_score": source.get("research_icepoint_score_v1"),
            }
            for horizon in (1, 5, 10, 20):
                mature = _coerce_bool_value(source.get(f"future_mature_{horizon}d"), default=False)
                row[f"future_mature_{horizon}d"] = mature
                row[f"mature_sample_count_{horizon}d"] = int(
                    mature and pd.notna(source.get(f"future_all_a_return_{horizon}d"))
                )
                for column in (
                    f"future_all_a_return_{horizon}d", f"future_all_a_min_return_{horizon}d",
                    f"future_all_a_max_return_{horizon}d", f"future_all_a_max_drawdown_{horizon}d",
                    f"future_stock_median_return_{horizon}d",
                    f"future_change_breadth_pct_above_ma20_{horizon}d",
                    f"future_change_breadth_new_low_20_ratio_{horizon}d",
                ):
                    row[column] = source.get(column)
            rows.append(row)
            position += 1
    return pd.DataFrame(rows)


def write_history_audit_tables(panel: pd.DataFrame, batch_dir: Path) -> dict[str, Path]:
    _assert_not_frozen_history_target(batch_dir)
    batch_dir.mkdir(parents=True, exist_ok=True)
    event_study = build_group_event_study(
        panel,
        (
            "tail_pressure", "risk_direction", "breadth_today_state", "breadth_5d_state", "breadth_20d_state",
            "style_regime", "research_overheat_candidate_v1", "research_icepoint_candidate_v1",
            "research_overheat_score_v1", "research_icepoint_score_v1",
        ),
    )
    transitions = build_state_transitions(
        panel, ("tail_pressure", "risk_direction", "breadth_today_state", "breadth_5d_state", "breadth_20d_state", "style_regime"),
    )
    correlations = build_feature_correlations(panel)
    style_panel = build_style_panel(panel)
    style_validation = build_style_validation(panel)
    industry_validation = build_industry_validation(panel)
    future_outcomes = build_future_outcomes_long(panel)
    episodes = build_event_episodes(panel)
    missing = pd.DataFrame(
        {
            "column": panel.columns,
            "missing_count": [int(panel[column].isna().sum()) for column in panel.columns],
            "missing_ratio": [float(panel[column].isna().mean()) for column in panel.columns],
        }
    ).sort_values(["missing_ratio", "column"], ascending=[False, True])
    paths = {
        "panel": batch_dir / "market_structure_400d_panel.csv",
        "event_study": batch_dir / "market_structure_400d_event_study.csv",
        "transitions": batch_dir / "market_structure_400d_state_transitions.csv",
        "correlations": batch_dir / "market_structure_400d_feature_correlations.csv",
        "missingness": batch_dir / "market_structure_400d_missingness.csv",
        "style_panel": batch_dir / "market_structure_400d_style_panel.csv",
        "style_validation": batch_dir / "market_structure_400d_style_validation.csv",
        "industry_validation": batch_dir / "market_structure_400d_industry_validation.csv",
        "future_outcomes": batch_dir / "market_structure_400d_future_outcomes.csv",
        "event_episodes": batch_dir / "market_structure_400d_event_episodes.csv",
    }
    frames = {
        "panel": panel,
        "event_study": event_study,
        "transitions": transitions,
        "correlations": correlations,
        "missingness": missing,
        "style_panel": style_panel,
        "style_validation": style_validation,
        "industry_validation": industry_validation,
        "future_outcomes": future_outcomes,
        "event_episodes": episodes,
    }
    for key, path in paths.items():
        _write_csv(path, frames[key], overwrite=True)
    return paths


def write_history_reproducibility_manifest(
    batch_dir: Path,
    config: dict[str, Any],
    project_root: Path,
    parameters: dict[str, Any],
) -> Path:
    """Record code hashes and metadata-only source inventories without secrets."""
    _assert_not_frozen_history_target(batch_dir)

    def file_record(path: Path) -> dict[str, Any]:
        return {
            "path": str(path),
            "exists": path.exists(),
            "bytes": path.stat().st_size if path.exists() else None,
            "sha256": _sha256(path) if path.exists() and path.is_file() else None,
        }

    def inventory(root: Path, pattern: str) -> dict[str, Any]:
        rows = [
            {
                "name": str(path.relative_to(root)),
                "bytes": path.stat().st_size,
                "mtime_ns": path.stat().st_mtime_ns,
            }
            for path in sorted(root.glob(pattern))
            if path.is_file()
        ] if root.exists() else []
        encoded = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return {
            "root": str(root),
            "file_count": len(rows),
            "total_bytes": int(sum(row["bytes"] for row in rows)),
            "metadata_inventory_sha256": hashlib.sha256(encoded).hexdigest(),
            "note": "digest covers relative path, size and mtime; not full market-data contents",
        }

    cache_root = Path(config.get("data", {}).get("cache_dir", "data/cache"))
    meta_root = Path(config.get("data", {}).get("meta_dir", "data/meta"))
    code_files = [
        project_root / "analysis" / "index_market_structure.py",
        project_root / "analysis" / "index_market_history.py",
        project_root / "analysis" / "index_market_history_llm.py",
        project_root / "visual" / "index_forecast_report.py",
        project_root / "scripts" / "backfill_market_structure_history.py",
        project_root / "scripts" / "finalize_market_structure_history_batch.py",
        project_root / "scripts" / "analyze_market_structure_history_codex.py",
        project_root / "scripts" / "analyze_market_structure_history_deepseek.py",
    ]
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "parameters": parameters,
        "safe_config": {
            "stock_adj": config.get("data", {}).get("stock_adj"),
            "cache_dir": str(cache_root),
            "meta_dir": str(meta_root),
            "reports_dir": str(config.get("output", {}).get("reports_dir")),
        },
        "code_files": [file_record(path) for path in code_files],
        "stocks_metadata": file_record(meta_root / "stocks.csv"),
        "stock_cache_inventory": inventory(cache_root, "*.csv"),
        "index_cache_inventory": inventory(cache_root / "index", "*.csv"),
        "secrets_recorded": False,
    }
    path = batch_dir / "market_structure_400d_reproducibility.json"
    _write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2),
        overwrite=True,
    )
    return path
