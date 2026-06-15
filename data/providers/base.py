"""Market data provider interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class ProviderMetadata:
    name: str
    source: str
    supports_network: bool
    notes: tuple[str, ...] = ()


class MarketDataProvider(ABC):
    """Standard provider interface used by DataDownloader.

    Provider methods return normalized DataFrames using QuantYB cache columns:
    date, open, high, low, close, volume, amount. Index data may include
    ts_code, pre_close, change, and pct_chg.
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config

    @abstractmethod
    def get_daily(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        """Return normalized stock daily bars."""

    @abstractmethod
    def get_index_daily(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        """Return normalized index daily bars."""

    @abstractmethod
    def get_stock_list(self) -> list[dict]:
        """Return [{"ts_code": ..., "name": ...}, ...]."""

    @abstractmethod
    def get_metadata(self) -> ProviderMetadata:
        """Return provider metadata for diagnostics and documentation."""


def normalize_ohlc(raw: pd.DataFrame, column_map: dict[str, str], keep_cols: list[str]) -> pd.DataFrame:
    """Normalize provider output into cache-compatible OHLC columns."""
    df = raw.rename(columns=column_map).copy()
    df = df[[c for c in keep_cols if c in df.columns]]
    if "date" not in df.columns:
        raise ValueError("provider data missing date column")

    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
    for col in [
        "open", "high", "low", "close", "pre_close", "change", "pct_chg",
        "volume", "amount",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date")
    return df.reset_index(drop=True)
