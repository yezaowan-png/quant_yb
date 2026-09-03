"""Pure helpers for stock metadata and daily basic datasets."""

from __future__ import annotations

import pandas as pd


def filter_non_st_stocks(df: pd.DataFrame) -> pd.DataFrame:
    """Return listed stocks excluding names that contain ST."""
    return df[~df["name"].astype(str).str.contains("ST", na=False)].copy()


def clean_stock_basic(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize stock_basic output before caching."""
    cleaned = df.copy()
    for col in cleaned.columns:
        cleaned[col] = cleaned[col].astype("string")
    return cleaned.sort_values("ts_code").reset_index(drop=True)


def build_stock_name_map(df: pd.DataFrame) -> pd.DataFrame:
    """Build ts_code -> name mapping from stock_basic output."""
    if "ts_code" not in df.columns or "name" not in df.columns:
        return pd.DataFrame(columns=["ts_code", "name"])
    return (
        df[["ts_code", "name"]]
        .dropna(subset=["ts_code"])
        .drop_duplicates(subset=["ts_code"], keep="last")
        .sort_values("ts_code")
        .reset_index(drop=True)
    )


def clean_daily_basic(raw: pd.DataFrame, fields: str) -> pd.DataFrame:
    """Normalize daily_basic output while preserving Tushare field names."""
    df = raw.copy()
    keep_cols = [c for c in fields.split(",") if c in df.columns]
    df = df[keep_cols]
    for col in ["ts_code", "trade_date"]:
        if col in df.columns:
            df[col] = df[col].astype(str)
    numeric_cols = [c for c in df.columns if c not in {"ts_code", "trade_date"}]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["ts_code", "trade_date"]).reset_index(drop=True)


def missing_daily_basic_dates(
    trade_dates: list[str],
    existing_dates: set[str],
    force: bool,
) -> list[str]:
    """Return trade dates that still need daily_basic download."""
    if force:
        return list(trade_dates)
    return [d for d in trade_dates if d not in existing_dates]
