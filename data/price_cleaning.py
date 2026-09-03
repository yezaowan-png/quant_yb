"""Pure helpers for cleaning Tushare daily price datasets."""

from __future__ import annotations

from typing import Optional

import pandas as pd


STOCK_DAILY_COLUMN_MAP = {
    "trade_date": "date",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "vol": "volume",
    "amount": "amount",
}

INDEX_DAILY_COLUMN_MAP = {
    "ts_code": "ts_code",
    "trade_date": "date",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "pre_close": "pre_close",
    "change": "change",
    "pct_chg": "pct_chg",
    "vol": "volume",
    "amount": "amount",
}

THS_INDEX_DAILY_COLUMN_MAP = {
    **INDEX_DAILY_COLUMN_MAP,
    "pct_change": "pct_chg",
    "turnover_rate": "turnover_rate",
    "total_mv": "total_mv",
    "float_mv": "float_mv",
}

STOCK_DAILY_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount", "adj_factor"]
INDEX_DAILY_COLUMNS = [
    "ts_code",
    "date",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "change",
    "pct_chg",
    "volume",
    "amount",
    "turnover_rate",
    "total_mv",
    "float_mv",
]


def clean_price_data(
    raw: pd.DataFrame,
    column_map: dict[str, str],
    keep_cols: list[str],
    adj: Optional[str] = None,
) -> pd.DataFrame:
    """Normalize a Tushare daily-like dataframe into local CSV format."""
    df = raw.rename(columns=column_map)
    df = df[[c for c in keep_cols if c in df.columns]]

    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    for col in keep_cols:
        if col in {"date", "ts_code"}:
            continue
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["open", "high", "low", "close"])
    price_cols = ["open", "high", "low", "close"]
    positive_prices = df[price_cols].gt(0).all(axis=1)
    valid_bounds = df["high"].ge(df[price_cols].max(axis=1)) & df["low"].le(df[price_cols].min(axis=1))
    valid_activity = pd.Series(True, index=df.index)
    for col in ("volume", "amount"):
        if col in df.columns:
            valid_activity &= df[col].isna() | df[col].ge(0)
    df = df.loc[positive_prices & valid_bounds & valid_activity].sort_values("date")
    if adj is not None:
        df["adj"] = adj
    return df.reset_index(drop=True)


def clean_stock_daily(raw: pd.DataFrame, adj: Optional[str] = None) -> pd.DataFrame:
    return clean_price_data(raw, STOCK_DAILY_COLUMN_MAP, STOCK_DAILY_COLUMNS, adj=adj)


def clean_index_daily(raw: pd.DataFrame) -> pd.DataFrame:
    return clean_price_data(raw, INDEX_DAILY_COLUMN_MAP, INDEX_DAILY_COLUMNS)


def clean_ths_index_daily(raw: pd.DataFrame) -> pd.DataFrame:
    """Normalize Tushare ``ths_daily`` rows to the local index cache schema."""
    return clean_price_data(raw, THS_INDEX_DAILY_COLUMN_MAP, INDEX_DAILY_COLUMNS)
