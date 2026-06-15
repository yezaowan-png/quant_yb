"""Provider factory for market data sources."""

from __future__ import annotations

from typing import Any

from data.providers.base import MarketDataProvider, ProviderMetadata
from data.providers.local_csv_provider import LocalCsvProvider
from data.providers.tushare_provider import TushareProvider


def create_provider(config: dict[str, Any], rate_limiter=None) -> MarketDataProvider:
    name = config.get("data", {}).get("provider", "tushare").lower()
    if name == "tushare":
        return TushareProvider(config, rate_limiter=rate_limiter)
    if name in {"local", "local_csv", "csv"}:
        return LocalCsvProvider(config)
    if name == "akshare":
        from data.providers.akshare_provider import AkshareProvider

        return AkshareProvider(config)
    raise ValueError(f"未知数据 provider: {name}")


__all__ = [
    "MarketDataProvider",
    "ProviderMetadata",
    "create_provider",
]
