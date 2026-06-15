"""Tushare market data provider."""

from __future__ import annotations

from typing import Any

import pandas as pd
import tushare as ts

from data.providers.base import MarketDataProvider, ProviderMetadata, normalize_ohlc


class TushareProvider(MarketDataProvider):
    COLUMN_MAP = {
        "trade_date": "date",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "vol": "volume",
        "amount": "amount",
    }
    INDEX_COLUMN_MAP = {
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

    def __init__(self, config: dict[str, Any], rate_limiter=None):
        super().__init__(config)
        token = self.config["tushare"]["token"]
        ts.set_token(token)
        self.pro = ts.pro_api()
        self.rate_limiter = rate_limiter

    def _wait(self) -> None:
        if self.rate_limiter is not None:
            self.rate_limiter.wait()

    def get_daily(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        self._wait()
        raw = self.pro.daily(
            ts_code=symbol,
            start_date=start,
            end_date=end,
            fields="trade_date,open,high,low,close,vol,amount",
        )
        if raw is None or raw.empty:
            raise ValueError(f"无数据: {symbol}")
        return normalize_ohlc(
            raw,
            self.COLUMN_MAP,
            ["date", "open", "high", "low", "close", "volume", "amount"],
        )

    def get_index_daily(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        self._wait()
        raw = self.pro.index_daily(
            ts_code=symbol,
            start_date=start,
            end_date=end,
            fields="ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
        )
        if raw is None or raw.empty:
            raise ValueError(f"无指数数据: {symbol}")
        return normalize_ohlc(
            raw,
            self.INDEX_COLUMN_MAP,
            [
                "ts_code", "date", "open", "high", "low", "close", "pre_close",
                "change", "pct_chg", "volume", "amount",
            ],
        )

    def get_stock_list(self) -> list[dict]:
        self._wait()
        df = self.pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
        if df is None or df.empty:
            return []
        df = df[~df["name"].str.contains("ST", na=False)]
        return df[["ts_code", "name"]].to_dict("records")

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            name="tushare",
            source="Tushare Pro",
            supports_network=True,
            notes=("A 股日线、指数日线和当前上市股票列表",),
        )
