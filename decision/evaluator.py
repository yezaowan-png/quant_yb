"""Decision memory post-signal evaluation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

from decision.recorder import load_memory, save_memory


DEFAULT_HORIZONS = (5, 10, 20)


def parse_horizons(raw: str | Iterable[int] | None) -> tuple[int, ...]:
    """Parse CLI horizon input such as ``5,10,20``."""
    if raw is None:
        return DEFAULT_HORIZONS
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        return tuple(sorted({int(p) for p in parts if int(p) > 0}))
    return tuple(sorted({int(v) for v in raw if int(v) > 0}))


def _cache_path(config: dict, symbol: str) -> Path:
    cache_dir = Path(config["data"]["cache_dir"])
    index_path = cache_dir / "index" / f"{symbol}.csv"
    if index_path.exists():
        return index_path
    return cache_dir / f"{symbol}.csv"


def _load_price_data(config: dict, symbol: str) -> pd.DataFrame | None:
    path = _cache_path(config, symbol)
    if not path.exists():
        return None
    df = pd.read_csv(path, dtype={"date": str})
    if df.empty or "close" not in df.columns:
        return None
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def _future_return(df: pd.DataFrame, signal_date: str, horizon: int) -> float | None:
    if df is None or df.empty:
        return None
    target = pd.Timestamp(signal_date)
    rows = df[df["date"] >= target]
    if rows.empty:
        return None
    start_idx = int(rows.index[0])
    future_idx = start_idx + horizon
    if future_idx >= len(df):
        return None
    start_close = float(df.loc[start_idx, "close"])
    future_close = float(df.loc[future_idx, "close"])
    if start_close <= 0:
        return None
    return round((future_close / start_close - 1) * 100, 4)


def _benchmark_symbol(config: dict) -> str | None:
    benchmark = config.get("benchmark", {})
    if not benchmark.get("enabled", True):
        return None
    symbol = benchmark.get("symbol")
    return str(symbol).upper() if symbol else None


def evaluate_memory(
    config: dict,
    strategy: str | None = None,
    symbol: str | None = None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> dict:
    """Evaluate recorded signals using future trading-day returns."""
    df = load_memory(config)
    if df.empty:
        return {
            "path": save_memory(config, df),
            "matched": 0,
            "evaluated": 0,
            "partial": 0,
            "pending": 0,
            "missing": 0,
        }

    for text_col in ("evaluation_status", "evaluated_at"):
        if text_col in df.columns:
            df[text_col] = df[text_col].astype("object")

    mask = pd.Series(True, index=df.index)
    if strategy:
        mask &= df["strategy"].astype(str) == strategy
    if symbol:
        mask &= df["symbol"].astype(str).str.upper() == symbol.upper()

    benchmark_symbol = _benchmark_symbol(config)
    benchmark_df = _load_price_data(config, benchmark_symbol) if benchmark_symbol else None
    price_cache: dict[str, pd.DataFrame | None] = {}
    evaluated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    stats = {"matched": int(mask.sum()), "evaluated": 0, "partial": 0, "pending": 0, "missing": 0}

    for idx in df[mask].index:
        row = df.loc[idx]
        row_symbol = str(row["symbol"]).upper()
        if row_symbol not in price_cache:
            price_cache[row_symbol] = _load_price_data(config, row_symbol)
        symbol_df = price_cache[row_symbol]
        if symbol_df is None:
            df.at[idx, "evaluation_status"] = "missing_symbol_data"
            stats["missing"] += 1
            continue

        signal_date = str(row["signal_date"])[:10]
        available_returns = 0
        expected_returns = len(horizons)
        for horizon in horizons:
            future_col = f"future_{horizon}d_return_pct"
            benchmark_col = f"benchmark_{horizon}d_return_pct"
            excess_col = f"excess_{horizon}d_return_pct"
            for col in (future_col, benchmark_col, excess_col):
                if col not in df.columns:
                    df[col] = pd.NA

            future_ret = _future_return(symbol_df, signal_date, horizon)
            benchmark_ret = _future_return(benchmark_df, signal_date, horizon) if benchmark_df is not None else None
            df.at[idx, future_col] = future_ret
            df.at[idx, benchmark_col] = benchmark_ret
            if future_ret is not None and benchmark_ret is not None:
                df.at[idx, excess_col] = round(future_ret - benchmark_ret, 4)
            elif future_ret is None:
                df.at[idx, excess_col] = pd.NA
            else:
                df.at[idx, excess_col] = pd.NA
            if future_ret is not None:
                available_returns += 1

        if available_returns == expected_returns:
            df.at[idx, "evaluation_status"] = "evaluated"
            stats["evaluated"] += 1
        elif available_returns > 0:
            df.at[idx, "evaluation_status"] = "partial"
            stats["partial"] += 1
        else:
            df.at[idx, "evaluation_status"] = "pending_future_data"
            stats["pending"] += 1
        df.at[idx, "evaluated_at"] = evaluated_at

    path = save_memory(config, df)
    stats["path"] = path
    return stats


def summarize_memory(config: dict, strategy: str | None = None) -> dict:
    """Summarize decision memory for CLI and dashboard use."""
    df = load_memory(config)
    if strategy and not df.empty:
        df = df[df["strategy"].astype(str) == strategy]
    if df.empty:
        return {
            "count": 0,
            "evaluated": 0,
            "partial": 0,
            "pending": 0,
            "latest_signal_date": "",
            "avg_future_5d_return_pct": None,
            "avg_excess_5d_return_pct": None,
        }
    statuses = df["evaluation_status"].fillna("pending")
    return {
        "count": int(len(df)),
        "evaluated": int((statuses == "evaluated").sum()),
        "partial": int((statuses == "partial").sum()),
        "pending": int(statuses.isin(["pending", "pending_future_data"]).sum()),
        "latest_signal_date": str(df["signal_date"].dropna().max())[:10],
        "avg_future_5d_return_pct": _mean_col(df, "future_5d_return_pct"),
        "avg_excess_5d_return_pct": _mean_col(df, "excess_5d_return_pct"),
    }


def _mean_col(df: pd.DataFrame, column: str) -> float | None:
    if column not in df.columns:
        return None
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    if values.empty:
        return None
    return round(float(values.mean()), 4)
