"""Strong-stock radar built from local A-share caches.

The module is intentionally deterministic and research-only.  It does not
produce trading orders, positions, or buy/sell recommendations.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from analysis.custom_concept_pools import (
    build_custom_concept_rs_history,
    load_custom_concept_pools,
)
from analysis.theme_stock_pools import ThemeStockPoolError, load_theme_stock_pools


RADAR_SCHEMA_VERSION = "strong_stock_radar_v1"


DEFAULT_RADAR_CONFIG: dict[str, Any] = {
    "benchmark_symbol": "",
    "history_bars": 1050,
    "display_top": 300,
    "universe": {
        "min_listing_days": 120,
        "min_avg_amount_20d": 50_000_000.0,
        "max_stale_trading_days": 0,
        "exclude_st": True,
        "exclude_suspended": True,
        "exclude_one_word_limit": True,
        "one_word_limit_return_abs": 0.095,
    },
    "units": {
        "volume_unit": 100.0,
        "amount_unit": 1000.0,
    },
    "rs": {
        "windows": [5, 10, 20, 60, 120],
        "persistence_window": 20,
        "persistence_threshold": 90.0,
        "industry_stock_rs_threshold": 80.0,
    },
    "trend": {
        "slope_window": 5,
        "strong_slope_min": 0.0,
        "mid_slope_min": 0.0,
    },
    "high_position": {
        "windows": [20, 60, 120, 250],
        "near_high_250d": -0.08,
    },
    "volume_price": {
        "healthy_min_return": 0.025,
        "healthy_min_amount_ratio": 1.3,
        "healthy_min_close_position": 0.7,
        "effort_min_amount_ratio": 2.0,
        "effort_max_return": 0.01,
        "effort_max_close_position": 0.45,
        "contraction_max_amount_ratio": 0.75,
        "contraction_max_abs_return": 0.025,
    },
    "contraction": {
        "early_volume_ma5_to_ma20_max": 0.85,
        "clear_volume_ma5_to_ma20_max": 0.7,
        "early_range10_to_20_max": 0.75,
        "clear_range5_to_20_max": 0.45,
        "near_high_250d": -0.12,
    },
    "industry": {
        "strong_rs60_pct": 80.0,
        "strong_above_ma20_pct": 0.55,
        "strengthening_delta_5d": 0.03,
        "weakening_delta_10d": -0.05,
    },
    "industry_rs_history": {
        "lookback_days": 250,
        "line_default_days": 250,
        "line_short_days": 120,
        "heatmap_weeks": 26,
        "persistence_window": 20,
        "persistence_threshold": 80.0,
        "delta_up_threshold": 5.0,
        "delta_down_threshold": -5.0,
        "watchlist": [],
    },
    "state": {
        "core_industry_rs60_pct": 80.0,
        "core_rs60_pct": 90.0,
        "core_rs120_pct": 85.0,
        "core_persistence_min": 0.55,
        "core_near_high_250d": -0.08,
        "accelerating_rs60_pct": 80.0,
        "accelerating_delta_5d": 5.0,
        "accelerating_delta_10d": 8.0,
        "high_tight_rs60_pct": 85.0,
        "high_tight_near_high_250d": -0.08,
        "breakout_amount_ratio_min": 1.3,
        "breakout_close_position_min": 0.7,
        "breakout_buffer": 0.0,
        "weakening_rs60_pct": 80.0,
        "weakening_delta_5d": -5.0,
        "weakening_delta_10d": -8.0,
    },
    "evaluation": {
        "horizons": [5, 10, 20],
        "mfe_mae_horizon": 20,
    },
}


SNAPSHOT_COLUMNS = [
    "trade_date",
    "ts_code",
    "name",
    "industry",
    "state",
    "rs5_pct",
    "rs10_pct",
    "rs20_pct",
    "rs60_pct",
    "rs120_pct",
    "rs60_delta_5d",
    "rs60_persistence_20d",
    "trend_state",
    "distance_to_high_250d",
    "amount_ratio_20d",
    "volume_price_state",
    "contraction_state",
]


@dataclass
class StrongStockRadarResult:
    trade_date: str
    output_dir: Path
    snapshot_path: Path
    latest_snapshot_path: Path
    tradable_universe_path: Path
    industry_path: Path
    industry_history_path: Path
    industry_history_latest_path: Path
    custom_concept_history_path: Path
    custom_concept_history_latest_path: Path
    theme_stock_history_path: Path
    theme_stock_history_latest_path: Path
    evaluation_path: Path
    report_path: Path | None
    tradable_universe: pd.DataFrame
    industry_strength: pd.DataFrame
    industry_rs_history: pd.DataFrame
    custom_concept_rs_history: pd.DataFrame
    theme_stock_history: pd.DataFrame
    stock_snapshot: pd.DataFrame
    evaluation: pd.DataFrame
    market_environment: dict[str, Any]


def _deep_merge(base: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in base.items():
        if isinstance(value, dict):
            result[key] = _deep_merge(value, {})
        elif isinstance(value, list):
            result[key] = list(value)
        else:
            result[key] = value
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def radar_config(config: dict[str, Any] | None) -> dict[str, Any]:
    merged = _deep_merge(DEFAULT_RADAR_CONFIG, (config or {}).get("strong_stock_radar") or {})
    if not merged.get("benchmark_symbol"):
        merged["benchmark_symbol"] = (
            (config or {}).get("benchmark", {}) or {}
        ).get("symbol") or "000300.SH"
    units = merged.setdefault("units", {})
    backtest_cfg = (config or {}).get("backtest", {}) or {}
    units["volume_unit"] = float(units.get("volume_unit") or backtest_cfg.get("volume_unit") or 100.0)
    units["amount_unit"] = float(units.get("amount_unit") or 1000.0)
    rs_config = merged.setdefault("rs", {})
    rs_windows = {5, 10, 20, 60, 120}
    rs_windows.update(int(value) for value in (rs_config.get("windows") or []))
    rs_config["windows"] = sorted(rs_windows)
    history = merged.setdefault("industry_rs_history", {})
    for name in ("lookback_days", "line_default_days", "line_short_days", "heatmap_weeks", "persistence_window"):
        history[name] = int(history[name])
    for name in ("persistence_threshold", "delta_up_threshold", "delta_down_threshold"):
        history[name] = float(history[name])
    history["watchlist"] = [str(value).strip() for value in (history.get("watchlist") or []) if str(value).strip()]
    return merged


def _cache_dir(config: dict[str, Any]) -> Path:
    return Path(config["data"]["cache_dir"])


def _meta_dir(config: dict[str, Any]) -> Path:
    return Path(config.get("data", {}).get("meta_dir", "data/meta"))


def _stats_dir(config: dict[str, Any]) -> Path:
    return Path(config["output"].get("statistics_dir", "output/statistics")) / "strong_stock_radar"


def _reports_dir(config: dict[str, Any]) -> Path:
    return Path(config["output"].get("reports_dir", "output/reports")) / "strong_stock_radar"


def list_stock_cache_symbols(config: dict[str, Any]) -> list[str]:
    root = _cache_dir(config)
    if not root.exists():
        return []
    return sorted(
        path.stem.upper()
        for path in root.glob("*.csv")
        if not path.name.startswith("_") and "." in path.stem
    )


def _date_key(value: Any) -> str:
    text = str(value or "").strip().replace("-", "").replace("/", "")
    return text[:8] if len(text) >= 8 and text[:8].isdigit() else ""


def _read_stock_selector_metadata(config: dict[str, Any]) -> pd.DataFrame:
    selector_cfg = ((config.get("dashboard") or {}).get("stock_selector") or {})
    csv_path = str(selector_cfg.get("csv_path") or "").strip()
    if not csv_path:
        return pd.DataFrame()
    path = Path(csv_path).expanduser()
    if not path.exists():
        return pd.DataFrame()
    try:
        frame = pd.read_csv(path, dtype=str).fillna("")
    except Exception:
        return pd.DataFrame()
    code_col = next((col for col in ("股票代码", "ts_code", "symbol", "代码") if col in frame.columns), "")
    if not code_col:
        return pd.DataFrame()
    result = pd.DataFrame({"ts_code": frame[code_col].astype(str).str.upper()})
    if "股票简称" in frame.columns:
        result["name"] = frame["股票简称"].astype(str)
    if "行业板块" in frame.columns:
        result["industry"] = frame["行业板块"].astype(str).str.split("|").str[0]
    elif "一级行业" in frame.columns:
        result["industry"] = frame["一级行业"].astype(str)
    elif "industry" in frame.columns:
        result["industry"] = frame["industry"].astype(str)
    if "概念板块" in frame.columns:
        result["concepts"] = frame["概念板块"].astype(str)
    return result.drop_duplicates("ts_code", keep="last")


def load_stock_metadata(config: dict[str, Any]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    selector_meta = _read_stock_selector_metadata(config)
    if not selector_meta.empty:
        frames.append(selector_meta)
    for name in ("stock_basic.csv", "stocks.csv", "stock_names.csv"):
        path = _meta_dir(config) / name
        if not path.exists():
            continue
        try:
            frame = pd.read_csv(path, dtype=str).fillna("")
        except Exception:
            continue
        if "ts_code" not in frame.columns:
            continue
        keep = ["ts_code"]
        for column in ("name", "industry", "market", "list_date", "list_status"):
            if column in frame.columns:
                keep.append(column)
        frames.append(frame[keep])
    if not frames:
        return pd.DataFrame(columns=["ts_code", "name", "industry"])
    merged = frames[0].copy()
    for frame in frames[1:]:
        merged = merged.merge(frame, on="ts_code", how="outer", suffixes=("", "_new"))
        for column in list(merged.columns):
            if not column.endswith("_new"):
                continue
            base = column[:-4]
            if base in merged.columns:
                merged[base] = merged[base].replace("", pd.NA).fillna(merged[column])
                merged = merged.drop(columns=[column])
            else:
                merged = merged.rename(columns={column: base})
    for column in ("name", "industry", "market", "list_date", "list_status", "concepts"):
        if column not in merged.columns:
            merged[column] = ""
    merged["ts_code"] = merged["ts_code"].astype(str).str.upper()
    merged["industry"] = merged["industry"].replace("", "未分类").fillna("未分类")
    return merged.drop_duplicates("ts_code", keep="last").reset_index(drop=True)


def _read_stock_frame(path: Path, rcfg: dict[str, Any], max_rows: int | None) -> pd.DataFrame:
    usecols = ["date", "open", "high", "low", "close", "volume", "amount"]
    try:
        frame = pd.read_csv(path, usecols=lambda col: col in usecols, dtype={"date": str})
    except Exception:
        return pd.DataFrame(columns=usecols)
    if frame.empty or "date" not in frame.columns or "close" not in frame.columns:
        return pd.DataFrame(columns=usecols)
    frame["date"] = frame["date"].map(_date_key)
    for column in ("open", "high", "low", "close", "volume", "amount"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        else:
            frame[column] = np.nan
    frame = frame.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date")
    frame = frame.drop_duplicates("date", keep="last")
    if max_rows and max_rows > 0:
        frame = frame.tail(int(max_rows))
    frame["volume"] = frame["volume"].fillna(0.0) * float(rcfg["units"]["volume_unit"])
    frame["amount"] = frame["amount"].fillna(0.0) * float(rcfg["units"]["amount_unit"])
    return frame.reset_index(drop=True)


def load_price_panels(
    config: dict[str, Any],
    symbols: Iterable[str] | None = None,
    trade_date: str | None = None,
    extra_bars: int = 40,
) -> dict[str, pd.DataFrame]:
    rcfg = radar_config(config)
    selected = list(symbols) if symbols is not None else list_stock_cache_symbols(config)
    max_rows = int(rcfg.get("history_bars") or 0) + int(extra_bars or 0)
    cache_dir = _cache_dir(config)
    frames: dict[str, pd.DataFrame] = {}
    cutoff = _date_key(trade_date)
    for symbol in selected:
        normalized = str(symbol).strip().upper()
        if not normalized:
            continue
        frame = _read_stock_frame(cache_dir / f"{normalized}.csv", rcfg, max_rows=max_rows or None)
        if frame.empty:
            continue
        if cutoff:
            frame = frame[frame["date"] <= cutoff]
        if frame.empty:
            continue
        frames[normalized] = frame
    return frames


def _wide(frames: dict[str, pd.DataFrame], column: str) -> pd.DataFrame:
    series = {}
    for symbol, frame in frames.items():
        if column not in frame.columns:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        series[symbol] = pd.Series(values.to_numpy(), index=frame["date"].astype(str), name=symbol)
    if not series:
        return pd.DataFrame()
    return pd.DataFrame(series).sort_index()


def _load_benchmark_close(config: dict[str, Any], dates: pd.Index, trade_date: str | None) -> pd.Series:
    rcfg = radar_config(config)
    symbol = str(rcfg.get("benchmark_symbol") or "000300.SH").upper()
    path = _cache_dir(config) / "index" / f"{symbol}.csv"
    if not path.exists():
        return pd.Series(np.nan, index=dates, name=symbol)
    try:
        frame = pd.read_csv(path, usecols=["date", "close"], dtype={"date": str})
    except Exception:
        return pd.Series(np.nan, index=dates, name=symbol)
    frame["date"] = frame["date"].map(_date_key)
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    if trade_date:
        frame = frame[frame["date"] <= _date_key(trade_date)]
    frame = frame.dropna(subset=["date", "close"]).sort_values("date").drop_duplicates("date", keep="last")
    return pd.Series(frame["close"].to_numpy(), index=frame["date"].astype(str), name=symbol).reindex(dates).ffill()


def percentile_rank(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.rank(axis=1, pct=True, method="max") * 100.0


def rs_persistence(rs_pct: pd.DataFrame, window: int, threshold: float) -> pd.DataFrame:
    valid = rs_pct.notna().rolling(window, min_periods=1).sum()
    hits = rs_pct.ge(float(threshold)).rolling(window, min_periods=1).sum()
    return hits / valid.replace(0, np.nan)


def ma_slope(series: pd.DataFrame | pd.Series, window: int) -> pd.DataFrame | pd.Series:
    """Normalized moving-average slope: `ma / ma.shift(window) - 1`, divided by `window`."""
    win = max(int(window), 1)
    return (series / series.shift(win) - 1.0) / win


def close_position(close: pd.DataFrame, high: pd.DataFrame, low: pd.DataFrame) -> pd.DataFrame:
    spread = high - low
    position = (close - low) / spread.replace(0, np.nan)
    return position.where(spread.ne(0), 0.5).clip(0.0, 1.0)


def rolling_distance_to_high(close: pd.DataFrame, window: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    high = close.rolling(int(window), min_periods=int(window)).max()
    distance = close / high - 1.0
    return high, distance


def _atr_pct(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, window: int) -> pd.DataFrame:
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).stack(),
            (high - prev_close).abs().stack(),
            (low - prev_close).abs().stack(),
        ],
        axis=1,
    ).max(axis=1).unstack()
    return tr.rolling(int(window), min_periods=int(window)).mean() / close


def trend_state_for_row(row: pd.Series, cfg: dict[str, Any]) -> str:
    strong_min = float(cfg["trend"]["strong_slope_min"])
    mid_min = float(cfg["trend"]["mid_slope_min"])
    close_value = row.get("close")
    ma20 = row.get("ma20")
    ma60 = row.get("ma60")
    ma120 = row.get("ma120")
    ma20_slope = row.get("ma20_slope")
    ma60_slope = row.get("ma60_slope")
    if pd.isna(close_value) or pd.isna(ma60) or pd.isna(ma120):
        return "UNKNOWN"
    if (
        pd.notna(ma20)
        and pd.notna(ma20_slope)
        and pd.notna(ma60_slope)
        and close_value > ma20 > ma60 > ma120
        and ma20_slope > strong_min
        and ma60_slope > strong_min
    ):
        return "STRONG"
    if pd.notna(ma60_slope) and close_value > ma60 > ma120 and ma60_slope > mid_min:
        return "MID_STRONG"
    if close_value < ma60 and (pd.isna(ma60_slope) or ma60_slope <= mid_min):
        return "BROKEN"
    if pd.notna(ma20) and close_value < ma20:
        return "WEAKENING"
    return "WEAKENING"


def volume_price_state_for_row(row: pd.Series, cfg: dict[str, Any]) -> str:
    c = cfg["volume_price"]
    ret = row.get("daily_return")
    amount_ratio = row.get("amount_ratio_20d")
    pos = row.get("close_position")
    dist = row.get("distance_to_high_60d")
    if pd.isna(ret) or pd.isna(amount_ratio) or pd.isna(pos):
        return "NORMAL"
    if (
        ret >= float(c["healthy_min_return"])
        and amount_ratio >= float(c["healthy_min_amount_ratio"])
        and pos >= float(c["healthy_min_close_position"])
    ):
        return "HEALTHY_EXPANSION"
    if amount_ratio >= float(c["effort_min_amount_ratio"]) and (
        ret <= float(c["effort_max_return"]) or pos <= float(c["effort_max_close_position"])
    ):
        return "EFFORT_NO_RESULT"
    if (
        pd.notna(dist)
        and dist >= float(cfg["high_position"]["near_high_250d"])
        and amount_ratio <= float(c["contraction_max_amount_ratio"])
        and abs(ret) <= float(c["contraction_max_abs_return"])
    ):
        return "CONTRACTION"
    return "NORMAL"


def contraction_state_for_row(row: pd.Series, cfg: dict[str, Any]) -> str:
    c = cfg["contraction"]
    dist = row.get("distance_to_high_250d")
    range20 = row.get("range_20d_pct")
    range10 = row.get("range_10d_pct")
    range5 = row.get("range_5d_pct")
    vol_ratio = row.get("volume_ma5_to_ma20")
    if pd.isna(dist) or pd.isna(range20) or range20 <= 0 or pd.isna(vol_ratio):
        return "NONE"
    if dist < float(c["near_high_250d"]):
        return "NONE"
    clear = (
        pd.notna(range5)
        and range5 <= range20 * float(c["clear_range5_to_20_max"])
        and vol_ratio <= float(c["clear_volume_ma5_to_ma20_max"])
    )
    if clear:
        return "CLEAR"
    early = (
        pd.notna(range10)
        and range10 <= range20 * float(c["early_range10_to_20_max"])
        and vol_ratio <= float(c["early_volume_ma5_to_ma20_max"])
    )
    return "EARLY" if early else "NONE"


def industry_state_for_row(row: pd.Series, cfg: dict[str, Any]) -> str:
    c = cfg["industry"]
    if pd.isna(row.get("industry_rs60_pct")):
        return "UNKNOWN"
    if (
        row.get("industry_rs60_delta_10d", 0.0) <= float(c["weakening_delta_10d"])
        and row.get("industry_rs60_pct", 0.0) >= float(c["strong_rs60_pct"])
    ):
        return "WEAKENING"
    if row.get("industry_rs60_delta_5d", 0.0) >= float(c["strengthening_delta_5d"]):
        return "STRENGTHENING"
    if (
        row.get("industry_rs60_pct", 0.0) >= float(c["strong_rs60_pct"])
        and row.get("pct_above_ma20", 0.0) >= float(c["strong_above_ma20_pct"])
    ):
        return "STRONG"
    return "NORMAL"


def stock_state_for_row(row: pd.Series, cfg: dict[str, Any]) -> str:
    c = cfg["state"]
    trend = str(row.get("trend_state") or "")
    industry_state = str(row.get("industry_state") or "")
    if (
        row.get("rs60_pct", 0.0) >= float(c["weakening_rs60_pct"])
        and (
            row.get("rs60_delta_5d", 0.0) <= float(c["weakening_delta_5d"])
            or row.get("rs60_delta_10d", 0.0) <= float(c["weakening_delta_10d"])
            or trend in {"WEAKENING", "BROKEN"}
            or industry_state == "WEAKENING"
            or row.get("volume_price_state") == "EFFORT_NO_RESULT"
        )
    ):
        return "STRONG_WEAKENING"
    if (
        bool(row.get("breakout_signal"))
        and row.get("amount_ratio_20d", 0.0) >= float(c["breakout_amount_ratio_min"])
        and row.get("close_position", 0.0) >= float(c["breakout_close_position_min"])
    ):
        return "BREAKOUT"
    if (
        row.get("industry_rs60_pct", 0.0) >= float(c["core_industry_rs60_pct"])
        and row.get("rs60_pct", 0.0) >= float(c["core_rs60_pct"])
        and row.get("rs120_pct", 0.0) >= float(c["core_rs120_pct"])
        and row.get("rs60_persistence_20d", 0.0) >= float(c["core_persistence_min"])
        and trend == "STRONG"
        and row.get("distance_to_high_250d", -1.0) >= float(c["core_near_high_250d"])
    ):
        return "CORE_STRONG"
    if (
        row.get("rs60_pct", 0.0) >= float(c["high_tight_rs60_pct"])
        and trend in {"STRONG", "MID_STRONG"}
        and row.get("distance_to_high_250d", -1.0) >= float(c["high_tight_near_high_250d"])
        and row.get("contraction_state") == "CLEAR"
    ):
        return "HIGH_TIGHT"
    if (
        row.get("rs60_pct", 0.0) >= float(c["accelerating_rs60_pct"])
        and row.get("rs60_delta_5d", 0.0) >= float(c["accelerating_delta_5d"])
        and row.get("rs60_delta_10d", 0.0) >= float(c["accelerating_delta_10d"])
        and row.get("industry_rs60_delta_5d", 0.0) >= float(cfg["industry"]["strengthening_delta_5d"])
        and trend in {"STRONG", "MID_STRONG"}
    ):
        return "ACCELERATING"
    return "WATCH"


def _latest_trade_date(close: pd.DataFrame, requested: str | None) -> str:
    if close.empty:
        return ""
    if requested:
        target = _date_key(requested)
        available = [str(date) for date in close.index.astype(str) if str(date) <= target]
        return available[-1] if available else ""
    return str(close.index[-1])


def build_strong_stock_radar(
    config: dict[str, Any],
    trade_date: str | None = None,
    symbols: Iterable[str] | None = None,
) -> dict[str, Any]:
    rcfg = radar_config(config)
    frames = load_price_panels(config, symbols=symbols, trade_date=trade_date, extra_bars=300)
    close = _wide(frames, "close")
    open_ = _wide(frames, "open").reindex_like(close)
    high = _wide(frames, "high").reindex_like(close)
    low = _wide(frames, "low").reindex_like(close)
    volume = _wide(frames, "volume").reindex_like(close)
    amount = _wide(frames, "amount").reindex_like(close)
    selected_date = _latest_trade_date(close, trade_date)
    if not selected_date:
        raise ValueError("没有可用股票缓存数据")

    benchmark = _load_benchmark_close(config, close.index, selected_date)
    benchmark_returns = {
        int(window): benchmark / benchmark.shift(int(window)) - 1.0
        for window in rcfg["rs"]["windows"]
    }

    bar_count = close.notna().cumsum()
    avg_amount_20d = amount.rolling(20, min_periods=20).mean()
    avg_volume_20d = volume.rolling(20, min_periods=20).mean()
    daily_return = close / close.shift(1) - 1.0
    tradable_mask = (
        bar_count.ge(int(rcfg["universe"]["min_listing_days"]))
        & avg_amount_20d.ge(float(rcfg["universe"]["min_avg_amount_20d"]))
        & close.notna()
        & amount.gt(0)
    )
    if bool(rcfg["universe"]["exclude_one_word_limit"]):
        one_word = high.eq(low) & daily_return.abs().ge(float(rcfg["universe"]["one_word_limit_return_abs"]))
        tradable_mask &= ~one_word

    metadata = load_stock_metadata(config)
    meta = metadata.set_index("ts_code") if not metadata.empty else pd.DataFrame()
    names = meta["name"].to_dict() if "name" in meta.columns else {}
    industries = meta["industry"].to_dict() if "industry" in meta.columns else {}
    st_symbols = {
        symbol for symbol, name in names.items()
        if "ST" in str(name).upper()
    }
    if bool(rcfg["universe"]["exclude_st"]) and st_symbols:
        tradable_mask.loc[:, [sym for sym in tradable_mask.columns if sym in st_symbols]] = False

    returns: dict[int, pd.DataFrame] = {}
    excess: dict[int, pd.DataFrame] = {}
    rs_pct: dict[int, pd.DataFrame] = {}
    for window in rcfg["rs"]["windows"]:
        win = int(window)
        ret = close / close.shift(win) - 1.0
        ret = ret.where(tradable_mask)
        returns[win] = ret
        excess[win] = ret.sub(benchmark_returns[win], axis=0)
        rs_pct[win] = percentile_rank(excess[win])

    persistence_window = int(rcfg["rs"]["persistence_window"])
    persistence_threshold = float(rcfg["rs"]["persistence_threshold"])
    rs20_persistence = rs_persistence(rs_pct[20], persistence_window, persistence_threshold)
    rs60_persistence = rs_persistence(rs_pct[60], persistence_window, persistence_threshold)
    rs60_delta_5d = rs_pct[60] - rs_pct[60].shift(5)
    rs60_delta_10d = rs_pct[60] - rs_pct[60].shift(10)
    rs120_delta_10d = rs_pct[120] - rs_pct[120].shift(10)

    ma10 = close.rolling(10, min_periods=10).mean()
    ma20 = close.rolling(20, min_periods=20).mean()
    ma60 = close.rolling(60, min_periods=60).mean()
    ma120 = close.rolling(120, min_periods=120).mean()
    slope_window = int(rcfg["trend"]["slope_window"])
    ma20_slope = ma_slope(ma20, slope_window)
    ma60_slope = ma_slope(ma60, slope_window)
    ma120_slope = ma_slope(ma120, slope_window)

    highs: dict[int, pd.DataFrame] = {}
    distances: dict[int, pd.DataFrame] = {}
    for window in rcfg["high_position"]["windows"]:
        win = int(window)
        highs[win], distances[win] = rolling_distance_to_high(close, win)

    amount_ratio_20d = amount / avg_amount_20d.replace(0, np.nan)
    volume_ratio_20d = volume / avg_volume_20d.replace(0, np.nan)
    cp = close_position(close, high, low)
    amplitude = high / low - 1.0
    atr_20_pct = _atr_pct(high, low, close, 20)
    range_20d_pct = high.rolling(20, min_periods=20).max() / low.rolling(20, min_periods=20).min() - 1.0
    range_10d_pct = high.rolling(10, min_periods=10).max() / low.rolling(10, min_periods=10).min() - 1.0
    range_5d_pct = high.rolling(5, min_periods=5).max() / low.rolling(5, min_periods=5).min() - 1.0
    volume_ma5 = volume.rolling(5, min_periods=5).mean()
    volume_ma20 = volume.rolling(20, min_periods=20).mean()
    volume_ma5_to_ma20 = volume_ma5 / volume_ma20.replace(0, np.nan)
    prev_high20 = highs[20].shift(1)
    prev_high60 = highs[60].shift(1)
    breakout_signal = (
        close.gt(prev_high20 * (1.0 + float(rcfg["state"]["breakout_buffer"])))
        | close.gt(prev_high60 * (1.0 + float(rcfg["state"]["breakout_buffer"])))
    )

    latest = selected_date
    stock_rows = []
    for symbol in close.columns:
        row = {
            "trade_date": latest,
            "ts_code": symbol,
            "name": names.get(symbol, ""),
            "industry": industries.get(symbol, "未分类") or "未分类",
            "close": _at(close, latest, symbol),
            "open": _at(open_, latest, symbol),
            "high": _at(high, latest, symbol),
            "low": _at(low, latest, symbol),
            "daily_return": _at(daily_return, latest, symbol),
            "amplitude": _at(amplitude, latest, symbol),
            "avg_volume_20d": _at(avg_volume_20d, latest, symbol),
            "avg_amount_20d": _at(avg_amount_20d, latest, symbol),
            "volume_ratio_20d": _at(volume_ratio_20d, latest, symbol),
            "amount_ratio_20d": _at(amount_ratio_20d, latest, symbol),
            "rs5_pct": _at(rs_pct[5], latest, symbol),
            "rs10_pct": _at(rs_pct[10], latest, symbol),
            "rs20_pct": _at(rs_pct[20], latest, symbol),
            "rs60_pct": _at(rs_pct[60], latest, symbol),
            "rs120_pct": _at(rs_pct[120], latest, symbol),
            "return_5d": _at(returns[5], latest, symbol),
            "return_10d": _at(returns[10], latest, symbol),
            "return_20d": _at(returns[20], latest, symbol),
            "return_60d": _at(returns[60], latest, symbol),
            "return_120d": _at(returns[120], latest, symbol),
            "excess_return_5d": _at(excess[5], latest, symbol),
            "excess_return_10d": _at(excess[10], latest, symbol),
            "excess_return_20d": _at(excess[20], latest, symbol),
            "excess_return_60d": _at(excess[60], latest, symbol),
            "excess_return_120d": _at(excess[120], latest, symbol),
            "rs20_persistence_20d": _at(rs20_persistence, latest, symbol),
            "rs60_persistence_20d": _at(rs60_persistence, latest, symbol),
            "rs60_delta_5d": _at(rs60_delta_5d, latest, symbol),
            "rs60_delta_10d": _at(rs60_delta_10d, latest, symbol),
            "rs120_delta_10d": _at(rs120_delta_10d, latest, symbol),
            "ma10": _at(ma10, latest, symbol),
            "ma20": _at(ma20, latest, symbol),
            "ma60": _at(ma60, latest, symbol),
            "ma120": _at(ma120, latest, symbol),
            "ma20_slope": _at(ma20_slope, latest, symbol),
            "ma60_slope": _at(ma60_slope, latest, symbol),
            "ma120_slope": _at(ma120_slope, latest, symbol),
            "close_position": _at(cp, latest, symbol),
            "atr_20_pct": _at(atr_20_pct, latest, symbol),
            "range_20d_pct": _at(range_20d_pct, latest, symbol),
            "range_10d_pct": _at(range_10d_pct, latest, symbol),
            "range_5d_pct": _at(range_5d_pct, latest, symbol),
            "volume_ma5": _at(volume_ma5, latest, symbol),
            "volume_ma20": _at(volume_ma20, latest, symbol),
            "volume_ma5_to_ma20": _at(volume_ma5_to_ma20, latest, symbol),
            "breakout_signal": bool(_at(breakout_signal, latest, symbol) or False),
            "tradable": bool(_at(tradable_mask, latest, symbol) or False),
        }
        for window in (20, 60, 120, 250):
            row[f"high_{window}d"] = _at(highs[window], latest, symbol)
            row[f"distance_to_high_{window}d"] = _at(distances[window], latest, symbol)
        row["trend_state"] = trend_state_for_row(pd.Series(row), rcfg)
        row["volume_price_state"] = volume_price_state_for_row(pd.Series(row), rcfg)
        row["contraction_state"] = contraction_state_for_row(pd.Series(row), rcfg)
        stock_rows.append(row)
    stocks = pd.DataFrame(stock_rows)

    industry_history = build_industry_rs_history(
        stocks,
        close=close,
        tradable_mask=tradable_mask,
        rs60_pct=rs_pct[60],
        benchmark_returns=benchmark_returns,
        selected_date=latest,
        cfg=rcfg,
    )
    concept_settings, concept_pools, concept_warnings, concept_config_path = load_custom_concept_pools(config, metadata)
    custom_concept_history = build_custom_concept_rs_history(
        concept_pools,
        concept_settings,
        close=close,
        tradable_mask=tradable_mask,
        benchmark_returns=benchmark_returns,
        windows=[int(value) for value in rcfg["rs"]["windows"]],
    )
    try:
        theme_pool_payload = load_theme_stock_pools()
        theme_pool_warning = ""
    except ThemeStockPoolError as exc:
        theme_pool_payload = {"themes": {}, "stocks": {}}
        theme_pool_warning = str(exc)
    theme_stock_history = build_theme_stock_rs_history(
        theme_pool_payload,
        rs_pct,
        close.index.astype(str).tolist(),
    )
    industry = industry_history[industry_history["trade_date"] == latest].copy() if not industry_history.empty else pd.DataFrame()
    if not industry.empty:
        stocks = stocks.merge(
            industry[["industry", "industry_rs60_pct", "industry_rs60_delta_5d", "industry_rs60_delta_10d", "industry_state"]],
            on="industry",
            how="left",
        )
    else:
        stocks["industry_rs60_pct"] = np.nan
        stocks["industry_rs60_delta_5d"] = np.nan
        stocks["industry_rs60_delta_10d"] = np.nan
        stocks["industry_state"] = "UNKNOWN"
    stocks["state"] = stocks.apply(lambda row: stock_state_for_row(row, rcfg), axis=1)
    stocks = stocks[stocks["tradable"]].reset_index(drop=True)

    tradable = stocks[
        [
            "trade_date",
            "ts_code",
            "name",
            "industry",
            "close",
            "avg_amount_20d",
            "amount_ratio_20d",
            "rs5_pct",
            "rs10_pct",
            "rs60_pct",
            "trend_state",
        ]
    ].copy()
    market_environment = load_market_environment(config)
    return {
        "trade_date": latest,
        "config": rcfg,
        "tradable_universe": tradable,
        "industry_strength": industry,
        "industry_rs_history": industry_history.tail(0) if industry_history.empty else industry_history.groupby("industry", group_keys=False).tail(int(rcfg["industry_rs_history"]["lookback_days"])).sort_values(["trade_date", "industry"]).reset_index(drop=True),
        "custom_concept_rs_history": custom_concept_history.tail(0) if custom_concept_history.empty else custom_concept_history.groupby("concept_id", group_keys=False).tail(int(rcfg["industry_rs_history"]["lookback_days"])).sort_values(["trade_date", "concept_id"]).reset_index(drop=True),
        "custom_concept_pools": concept_pools,
        "custom_concept_warnings": concept_warnings,
        "custom_concept_config_path": concept_config_path,
        "theme_pool_payload": theme_pool_payload,
        "theme_pool_warning": theme_pool_warning,
        "theme_stock_history": theme_stock_history.tail(0) if theme_stock_history.empty else theme_stock_history.groupby(["theme_id", "ts_code"], group_keys=False).tail(int(rcfg["industry_rs_history"]["lookback_days"])).sort_values(["theme_id", "trade_date", "ts_code"]).reset_index(drop=True),
        "stock_snapshot": stocks,
        "market_environment": market_environment,
        "history": {
            "dates": close.index.astype(str).tolist(),
            "rs5_pct": rs_pct[5],
            "rs10_pct": rs_pct[10],
            "rs20_pct": rs_pct[20],
            "rs60_pct": rs_pct[60],
            "rs120_pct": rs_pct[120],
            "close": close,
            "high": high,
            "low": low,
        },
    }


def _at(frame: pd.DataFrame, date_value: str, symbol: str) -> Any:
    if frame.empty or date_value not in frame.index or symbol not in frame.columns:
        return np.nan
    return frame.at[date_value, symbol]


def build_theme_stock_rs_history(
    theme_pool: dict[str, Any],
    rs_pct: dict[int, pd.DataFrame],
    trade_dates: Iterable[str],
) -> pd.DataFrame:
    """Expose confirmed RS members with unchanged full-market RS values.

    Theme ranks are calculated only for presentation and remain separate from
    the cross-sectional all-market percentile already present in ``rs_pct``.
    """
    themes = theme_pool.get("themes", {}) if isinstance(theme_pool, dict) else {}
    stocks = theme_pool.get("stocks", {}) if isinstance(theme_pool, dict) else {}
    if not isinstance(themes, dict) or not isinstance(stocks, dict):
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for theme_id, theme in themes.items():
        if not isinstance(theme, dict) or theme.get("enabled") is False:
            continue
        for code, stock in stocks.items():
            assignment = (stock.get("assignments", {}) or {}).get(theme_id) if isinstance(stock, dict) else None
            if not isinstance(assignment, dict) or assignment.get("status") != "confirmed":
                continue
            # Legacy confirmed assignments predate pool_role and remain members.
            if assignment.get("pool_role") not in (None, "rs_member"):
                continue
            for trade_date in trade_dates:
                row = {
                    "trade_date": str(trade_date), "theme_id": str(theme_id),
                    "theme_name": str(theme.get("name") or theme_id), "ts_code": str(code),
                    "stock_name": str(stock.get("stock_name") or code),
                    "classification_source": assignment.get("classification_source"),
                    "reason": assignment.get("reason"), "industry_relation": assignment.get("industry_relation"),
                    "market_theme_relation": assignment.get("market_theme_relation"),
                    "confidence": assignment.get("confidence"), "status": assignment.get("status"),
                    "latest_limit_up_date": stock.get("latest_limit_up_date"),
                    "limit_up_count_20d": stock.get("limit_up_count_20d"),
                    "limit_up_count_60d": stock.get("limit_up_count_60d"),
                    "limit_up_count_120d": stock.get("limit_up_count_120d"),
                }
                for window in (5, 10, 20, 60, 120):
                    frame = rs_pct.get(window, pd.DataFrame())
                    row[f"rs{window}_pct"] = _at(frame, str(trade_date), str(code))
                rows.append(row)
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    for window in (5, 10, 20, 60, 120):
        field = f"rs{window}_pct"
        rank = result.groupby(["theme_id", "trade_date"])[field].rank(method="min", ascending=False)
        denominator = result.groupby(["theme_id", "trade_date"])[field].transform("count")
        result[f"theme_rs{window}_rank"] = rank.where(result[field].notna())
        result[f"theme_rs{window}_denominator"] = denominator.where(result[field].notna())
        matrix = result.pivot(index="trade_date", columns=["theme_id", "ts_code"], values=f"theme_rs{window}_rank").sort_index()
        previous = matrix.shift(5).rename_axis(index="trade_date", columns=["theme_id", "ts_code"]).stack(["theme_id", "ts_code"], future_stack=True).rename(f"theme_rs{window}_rank_change_5d").reset_index()
        result = result.merge(previous, on=["trade_date", "theme_id", "ts_code"], how="left", validate="one_to_one")
    return result.sort_values(["theme_id", "trade_date", "ts_code"]).reset_index(drop=True)


def build_industry_rs_history(
    latest_stocks: pd.DataFrame,
    close: pd.DataFrame,
    tradable_mask: pd.DataFrame,
    rs60_pct: pd.DataFrame,
    benchmark_returns: dict[int, pd.Series],
    selected_date: str,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    if latest_stocks.empty or "industry" not in latest_stocks.columns:
        return pd.DataFrame()
    symbol_industry = latest_stocks.set_index("ts_code")["industry"].fillna("未分类").to_dict()
    industries = sorted(set(symbol_industry.values()))
    frames = []
    for industry in industries:
        symbols = [symbol for symbol, value in symbol_industry.items() if value == industry and symbol in close.columns]
        if not symbols:
            continue
        member_close = close[symbols]
        member_tradable = tradable_mask[symbols]
        item = pd.DataFrame(index=member_close.index)
        item["trade_date"] = item.index.astype(str)
        item["industry"] = industry
        item["member_count"] = len(symbols)
        for window in cfg["rs"]["windows"]:
            window = int(window)
            stock_ret = member_close / member_close.shift(window) - 1.0
            industry_ret_series = stock_ret.where(member_tradable).mean(axis=1)
            industry_rs_series = industry_ret_series - benchmark_returns[window]
            item[f"industry_return_{window}d"] = industry_ret_series
            item[f"industry_rs_{window}d"] = industry_rs_series
        ma10 = member_close.rolling(10, min_periods=10).mean()
        ma20 = member_close.rolling(20, min_periods=20).mean()
        ma60 = member_close.rolling(60, min_periods=60).mean()
        rolling_high20 = member_close.rolling(20, min_periods=20).max()
        daily_return = member_close / member_close.shift(1) - 1.0
        valid_count = member_tradable.sum(axis=1).replace(0, np.nan)
        item["tradable_member_count"] = valid_count
        item["industry_daily_return"] = daily_return.where(member_tradable).mean(axis=1)
        item["pct_advancing"] = (
            daily_return.gt(0).where(member_tradable).sum(axis=1) / valid_count
        ).where(valid_count.notna())
        for name, ma in (("pct_above_ma10", ma10), ("pct_above_ma20", ma20), ("pct_above_ma60", ma60)):
            item[name] = (member_close.gt(ma).where(member_tradable).sum(axis=1) / valid_count).where(valid_count.notna())
        item["pct_new_high_20d"] = (member_close.ge(rolling_high20).where(member_tradable).sum(axis=1) / valid_count).where(valid_count.notna())
        item["pct_stock_rs60_above_80"] = (rs60_pct[symbols].ge(float(cfg["rs"]["industry_stock_rs_threshold"])).where(member_tradable).sum(axis=1) / valid_count).where(valid_count.notna())
        frames.append(item.reset_index(drop=True))
    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if result.empty:
        return result
    for window in cfg["rs"]["windows"]:
        window = int(window)
        col = f"industry_rs_{window}d"
        result[f"industry_rs{window}_pct"] = result.groupby("trade_date")[col].rank(pct=True, method="max") * 100.0
    result = result.sort_values(["industry", "trade_date"]).reset_index(drop=True)
    for industry, indexes in result.groupby("industry").groups.items():
        index = list(indexes)
        for source, target, periods in (
            ("industry_rs_60d", "industry_rs60_delta_5d", 5),
            ("industry_rs_60d", "industry_rs60_delta_10d", 10),
            ("industry_rs5_pct", "industry_rs5_pct_delta_5d", 5),
            ("industry_rs10_pct", "industry_rs10_pct_delta_5d", 5),
            ("industry_rs20_pct", "industry_rs20_pct_delta_5d", 5),
            ("industry_rs60_pct", "industry_rs60_pct_delta_5d", 5),
            ("industry_rs120_pct", "industry_rs120_pct_delta_5d", 5),
            ("industry_rs60_pct", "industry_rs60_pct_delta_10d", 10),
            ("industry_rs120_pct", "industry_rs120_pct_delta_10d", 10),
        ):
            values = result.loc[index, source]
            valid = values.dropna()
            delta = pd.Series(np.nan, index=values.index)
            delta.loc[valid.index] = valid - valid.shift(periods)
            result.loc[index, target] = delta
        ranks = result.loc[index, "industry_rs60_pct"]
        valid_ranks = ranks.dropna()
        rate = pd.Series(np.nan, index=ranks.index)
        top_days = pd.Series(np.nan, index=ranks.index)
        sample_days = pd.Series(np.nan, index=ranks.index)
        if not valid_ranks.empty:
            window = int(cfg["industry_rs_history"]["persistence_window"])
            threshold = float(cfg["industry_rs_history"]["persistence_threshold"])
            rate.loc[valid_ranks.index] = valid_ranks.ge(threshold).rolling(window, min_periods=1).mean()
            top_days.loc[valid_ranks.index] = valid_ranks.ge(threshold).rolling(window, min_periods=1).sum()
            sample_days.loc[valid_ranks.index] = valid_ranks.rolling(window, min_periods=1).count()
        result.loc[index, "industry_rs60_persistence_20d"] = rate
        result.loc[index, "industry_rs60_top20_days_20d"] = top_days
        result.loc[index, "industry_rs60_persistence_sample_days_20d"] = sample_days
    # Keep legacy per-industry deltas above intact. The report's cross-sectional
    # comparison fields below always use the same pair of trading dates.
    trade_dates = result["trade_date"].drop_duplicates().sort_values().tolist()
    for window in (5, 10, 20, 60, 120):
        source = f"industry_rs{window}_pct"
        target = f"industry_rs{window}_pct_delta_5d_common"
        matrix = result.pivot(index="trade_date", columns="industry", values=source).reindex(trade_dates)
        common_delta = matrix - matrix.shift(5)
        delta_frame = (
            common_delta.rename_axis(index="trade_date", columns="industry")
            .reset_index()
            .melt(id_vars="trade_date", var_name="industry", value_name=target)
        )
        result = result.merge(delta_frame, on=["trade_date", "industry"], how="left", validate="one_to_one")
    result["industry_state"] = result.apply(lambda row: industry_state_for_row(row, cfg), axis=1)
    return result.sort_values(["trade_date", "industry_rs60_pct", "industry_rs20_pct"], ascending=[True, False, False]).reset_index(drop=True)


def build_industry_strength(*args: Any, **kwargs: Any) -> pd.DataFrame:
    """Backward-compatible latest cross-section view of industry RS history."""
    selected_date = str(kwargs.get("selected_date") or "")
    history = build_industry_rs_history(*args, **kwargs)
    return history[history["trade_date"] == selected_date].reset_index(drop=True) if not history.empty else history


def _series_at(series: pd.Series, date_value: str) -> Any:
    if series is None or date_value not in series.index:
        return np.nan
    return series.at[date_value]


def load_market_environment(config: dict[str, Any]) -> dict[str, Any]:
    stats_dir = Path(config["output"].get("statistics_dir", "output/statistics"))
    path = stats_dir / "index_forecast" / "market_structure_000001.SH.json"
    if not path.exists():
        return {"date": "", "headline": "", "breadth_state": "", "style_regime_name": ""}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"date": "", "headline": "", "breadth_state": "", "style_regime_name": ""}
    state = data.get("market_structure") or {}
    return {
        "date": str(data.get("date") or ""),
        "headline": str(state.get("headline") or ""),
        "breadth_state": str(state.get("breadth_state") or ""),
        "style_regime_name": str(state.get("style_regime_name") or ""),
        "liquidity_state": str(state.get("liquidity_state") or ""),
    }


def save_strong_stock_radar(
    config: dict[str, Any],
    trade_date: str | None = None,
    top: int | None = None,
    write_report: bool = True,
    evaluate: bool = True,
) -> StrongStockRadarResult:
    built = build_strong_stock_radar(config, trade_date=trade_date)
    output_dir = _stats_dir(config)
    output_dir.mkdir(parents=True, exist_ok=True)
    reports_dir = _reports_dir(config)
    reports_dir.mkdir(parents=True, exist_ok=True)
    trade = built["trade_date"]
    snapshot = built["stock_snapshot"].copy()
    configured_top = int(radar_config(config).get("display_top") or 300)
    report_top = int(top) if top is not None and int(top) > 0 else configured_top
    snapshot_for_report = snapshot.sort_values(["rs60_pct", "rs120_pct"], ascending=False).head(report_top)
    snapshot_path = output_dir / f"radar_snapshot_{trade}.csv"
    latest_snapshot_path = output_dir / "strong_stock_radar_latest.csv"
    tradable_path = output_dir / f"tradable_universe_{trade}.csv"
    industry_path = output_dir / f"industry_strength_{trade}.csv"
    industry_history_path = output_dir / f"industry_rs_history_{trade}.csv"
    industry_history_latest_path = output_dir / "industry_rs_history_latest.csv"
    custom_concept_history_path = output_dir / f"custom_concept_rs_history_{trade}.csv"
    custom_concept_history_latest_path = output_dir / "custom_concept_rs_history_latest.csv"
    theme_stock_history_path = output_dir / f"theme_stock_rs_history_{trade}.csv"
    theme_stock_history_latest_path = output_dir / "theme_stock_rs_history_latest.csv"
    snapshot_audit = snapshot[[column for column in SNAPSHOT_COLUMNS if column in snapshot.columns]].copy()
    snapshot_audit.to_csv(snapshot_path, index=False)
    snapshot.to_csv(latest_snapshot_path, index=False)
    built["tradable_universe"].to_csv(tradable_path, index=False)
    built["industry_strength"].to_csv(industry_path, index=False)
    built["industry_rs_history"].to_csv(industry_history_path, index=False)
    built["industry_rs_history"].to_csv(industry_history_latest_path, index=False)
    built["custom_concept_rs_history"].to_csv(custom_concept_history_path, index=False)
    built["custom_concept_rs_history"].to_csv(custom_concept_history_latest_path, index=False)
    built["theme_stock_history"].to_csv(theme_stock_history_path, index=False)
    built["theme_stock_history"].to_csv(theme_stock_history_latest_path, index=False)
    evaluation = update_radar_evaluation(config) if evaluate else pd.DataFrame()
    evaluation_path = output_dir / "radar_evaluation.csv"
    if not evaluation.empty:
        evaluation.to_csv(evaluation_path, index=False)
    elif not evaluation_path.exists():
        pd.DataFrame().to_csv(evaluation_path, index=False)
    report_path: Path | None = None
    if write_report:
        from visual.strong_stock_radar_report import generate_strong_stock_radar_report

        report_path = reports_dir / "strong_stock_radar.html"
        generate_strong_stock_radar_report(
            config,
            trade,
            built["industry_strength"],
            built["industry_rs_history"],
            snapshot_for_report,
            evaluation,
            built["market_environment"],
            report_path,
            full_stock_snapshot=snapshot,
            custom_concept_history=built["custom_concept_rs_history"],
            custom_concept_pools=built["custom_concept_pools"],
            custom_concept_warnings=built["custom_concept_warnings"],
            theme_pool_payload=built["theme_pool_payload"],
            theme_stock_history=built["theme_stock_history"],
        )
    return StrongStockRadarResult(
        trade_date=trade,
        output_dir=output_dir,
        snapshot_path=snapshot_path,
        latest_snapshot_path=latest_snapshot_path,
        tradable_universe_path=tradable_path,
        industry_path=industry_path,
        industry_history_path=industry_history_path,
        industry_history_latest_path=industry_history_latest_path,
        custom_concept_history_path=custom_concept_history_path,
        custom_concept_history_latest_path=custom_concept_history_latest_path,
        theme_stock_history_path=theme_stock_history_path,
        theme_stock_history_latest_path=theme_stock_history_latest_path,
        evaluation_path=evaluation_path,
        report_path=report_path,
        tradable_universe=built["tradable_universe"],
        industry_strength=built["industry_strength"],
        industry_rs_history=built["industry_rs_history"],
        custom_concept_rs_history=built["custom_concept_rs_history"],
        theme_stock_history=built["theme_stock_history"],
        stock_snapshot=snapshot,
        evaluation=evaluation,
        market_environment=built["market_environment"],
    )


def update_radar_evaluation(config: dict[str, Any]) -> pd.DataFrame:
    rcfg = radar_config(config)
    output_dir = _stats_dir(config)
    snapshots = sorted(output_dir.glob("radar_snapshot_*.csv"))
    if not snapshots:
        return pd.DataFrame()
    rows: list[pd.DataFrame] = []
    for path in snapshots:
        try:
            frame = pd.read_csv(path, dtype={"trade_date": str, "ts_code": str})
        except Exception:
            continue
        if frame.empty:
            continue
        rows.append(frame)
    if not rows:
        return pd.DataFrame()
    combined = pd.concat(rows, ignore_index=True).drop_duplicates(["trade_date", "ts_code"], keep="last")
    symbols = sorted(combined["ts_code"].dropna().astype(str).str.upper().unique())
    frames = load_price_panels(config, symbols=symbols, trade_date=None, extra_bars=0)
    close = _wide(frames, "close")
    high = _wide(frames, "high").reindex_like(close)
    low = _wide(frames, "low").reindex_like(close)
    horizons = [int(value) for value in rcfg["evaluation"]["horizons"]]
    mfe_horizon = int(rcfg["evaluation"]["mfe_mae_horizon"])
    out_rows = []
    for _, row in combined.iterrows():
        symbol = str(row.get("ts_code") or "").upper()
        trade = _date_key(row.get("trade_date"))
        item = row.to_dict()
        if symbol not in close.columns or trade not in close.index:
            out_rows.append(item)
            continue
        entry_close = close.at[trade, symbol]
        for horizon in horizons:
            future = close[symbol].shift(-horizon)
            item[f"future_return_{horizon}d"] = (
                future.at[trade] / entry_close - 1.0
                if pd.notna(entry_close) and trade in future.index and pd.notna(future.at[trade])
                else np.nan
            )
        loc = close.index.get_loc(trade)
        if isinstance(loc, slice):
            loc = loc.start
        end = int(loc) + mfe_horizon + 1
        if int(loc) + 1 < len(close.index):
            future_high = high[symbol].iloc[int(loc) + 1:end]
            future_low = low[symbol].iloc[int(loc) + 1:end]
            item["mfe_20d"] = future_high.max() / entry_close - 1.0 if not future_high.dropna().empty else np.nan
            item["mae_20d"] = future_low.min() / entry_close - 1.0 if not future_low.dropna().empty else np.nan
        out_rows.append(item)
    return pd.DataFrame(out_rows)


def build_evaluation_summary(evaluation: pd.DataFrame) -> pd.DataFrame:
    if evaluation.empty or "state" not in evaluation.columns:
        return pd.DataFrame()
    rows = []
    for state, part in evaluation.groupby("state", dropna=False):
        row: dict[str, Any] = {"state": state, "sample_count": len(part)}
        for horizon in (5, 10, 20):
            col = f"future_return_{horizon}d"
            raw_values = part[col] if col in part.columns else pd.Series(dtype=float)
            values = pd.to_numeric(raw_values, errors="coerce").dropna()
            row[f"t{horizon}_median"] = values.median() if not values.empty else np.nan
            row[f"t{horizon}_win_rate"] = (values > 0).mean() if not values.empty else np.nan
            row[f"t{horizon}_p25"] = values.quantile(0.25) if not values.empty else np.nan
            row[f"t{horizon}_p75"] = values.quantile(0.75) if not values.empty else np.nan
        for col in ("mfe_20d", "mae_20d"):
            raw_values = part[col] if col in part.columns else pd.Series(dtype=float)
            values = pd.to_numeric(raw_values, errors="coerce").dropna()
            row[f"{col}_median"] = values.median() if not values.empty else np.nan
        rows.append(row)
    return pd.DataFrame(rows).sort_values("sample_count", ascending=False).reset_index(drop=True)
