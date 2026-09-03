"""Shared market benchmark constants and local average-price proxy builders."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


MARKET_BENCHMARK_NAME = "同花顺平均股价指数"
MARKET_BENCHMARK_SHORT_NAME = "平均股价"
MARKET_BENCHMARK_SYMBOL = "AVG_PRICE.LOCAL"
MARKET_BENCHMARK_SOURCE = "本地股票池收盘价等权平均"
MARKET_BENCHMARK_QUALITY_FLAG = "average_price_benchmark_uses_local_stock_pool_proxy"
MARKET_BENCHMARK_CHART_KEY = "ths_average_price_index"


def is_market_benchmark_symbol(symbol: str | None) -> bool:
    return str(symbol or "").upper() == MARKET_BENCHMARK_SYMBOL


def _positive_numeric(frame: pd.DataFrame | None, index: pd.Index, columns: pd.Index) -> pd.DataFrame | None:
    if frame is None or frame.empty:
        return None
    result = frame.reindex(index=index, columns=columns).apply(pd.to_numeric, errors="coerce")
    return result.where(result > 0)


def build_average_price_index_frame(
    *,
    close: pd.DataFrame,
    amount: pd.DataFrame | None = None,
    open_: pd.DataFrame | None = None,
    high: pd.DataFrame | None = None,
    low: pd.DataFrame | None = None,
    volume: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build a local proxy for Tonghuashun's average stock price index.

    The proxy uses the current local stock cache universe.  For each trading day,
    it averages per-stock OHLC prices across stocks with valid positive closes and,
    when turnover is available, positive turnover.  The resulting series is an
    explanatory market-structure benchmark rather than a tradable or official
    vendor index.
    """
    if close is None or close.empty:
        return pd.DataFrame()
    close_num = close.apply(pd.to_numeric, errors="coerce").where(lambda x: x > 0)
    amount_num = _positive_numeric(amount, close_num.index, close_num.columns)
    valid = close_num.notna()
    if amount_num is not None and bool(amount_num.notna().any().any()):
        valid &= amount_num.notna()
    avg_close = close_num.where(valid).mean(axis=1, skipna=True)

    def average_or_close(source: pd.DataFrame | None) -> pd.Series:
        source_num = _positive_numeric(source, close_num.index, close_num.columns)
        if source_num is None:
            return avg_close
        values = source_num.where(valid).mean(axis=1, skipna=True)
        return values.where(values.notna(), avg_close)

    avg_open = average_or_close(open_)
    avg_high = average_or_close(high)
    avg_low = average_or_close(low)
    pre_close = avg_close.shift(1)
    pct = avg_close / pre_close - 1.0
    total_amount = (
        amount_num.where(valid).sum(axis=1, min_count=1)
        if amount_num is not None
        else pd.Series(np.nan, index=close_num.index, dtype="float64")
    )
    volume_num = _positive_numeric(volume, close_num.index, close_num.columns)
    total_volume = (
        volume_num.where(valid).sum(axis=1, min_count=1)
        if volume_num is not None
        else pd.Series(np.nan, index=close_num.index, dtype="float64")
    )
    frame = pd.DataFrame(
        {
            "ts_code": MARKET_BENCHMARK_SYMBOL,
            "date": pd.to_datetime(close_num.index),
            "open": avg_open,
            "high": pd.concat([avg_open, avg_high, avg_close], axis=1).max(axis=1, skipna=True),
            "low": pd.concat([avg_open, avg_low, avg_close], axis=1).min(axis=1, skipna=True),
            "close": avg_close,
            "pre_close": pre_close,
            "change": avg_close - pre_close,
            "pct_chg": pct * 100.0,
            "volume": total_volume,
            "amount": total_amount,
        }
    )
    return frame.dropna(subset=["date", "open", "high", "low", "close"]).reset_index(drop=True)


def build_average_price_index_from_stock_cache(
    cache_dir: str | Path,
    *,
    dates: Iterable[pd.Timestamp] | None = None,
) -> pd.DataFrame:
    root = Path(cache_dir)
    wanted = None
    if dates is not None:
        wanted = pd.DatetimeIndex(pd.to_datetime(list(dates), errors="coerce")).dropna().unique().sort_values()

    panels: dict[str, list[pd.Series]] = {
        "open": [],
        "high": [],
        "low": [],
        "close": [],
        "volume": [],
        "amount": [],
    }
    for path in sorted(root.glob("*.csv")):
        if path.name.startswith("_"):
            continue
        try:
            frame = pd.read_csv(
                path,
                usecols=lambda column: column in {"date", "open", "high", "low", "close", "volume", "amount"},
                dtype={"date": str},
            )
        except (OSError, ValueError, pd.errors.ParserError):
            continue
        if not {"date", "close"}.issubset(frame.columns):
            continue
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.dropna(subset=["date"]).drop_duplicates("date", keep="last").set_index("date")
        if frame.empty:
            continue
        symbol = path.stem.upper()
        for column in panels:
            source = pd.to_numeric(frame.get(column), errors="coerce") if column in frame else pd.Series(np.nan, index=frame.index)
            panels[column].append(source.rename(symbol))

    if not panels["close"]:
        return pd.DataFrame()
    merged = {column: pd.concat(series, axis=1).sort_index() for column, series in panels.items()}
    if wanted is not None:
        merged = {column: frame.reindex(wanted) for column, frame in merged.items()}
    return build_average_price_index_frame(
        close=merged["close"],
        amount=merged["amount"],
        open_=merged["open"],
        high=merged["high"],
        low=merged["low"],
        volume=merged["volume"],
    )
