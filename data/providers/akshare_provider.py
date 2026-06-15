"""AKShare provider placeholder.

The interface is intentionally present before enabling live AKShare calls so the
project can document provider selection without silently changing data quality.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from data.providers.base import MarketDataProvider, ProviderMetadata


class AkshareProvider(MarketDataProvider):
    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        try:
            import akshare  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "AKShare provider requires installing akshare and validating target interfaces."
            ) from exc

    def get_daily(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        raise NotImplementedError("AKShare daily adapter is not enabled yet.")

    def get_index_daily(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        raise NotImplementedError("AKShare index adapter is not enabled yet.")

    def get_stock_list(self) -> list[dict]:
        raise NotImplementedError("AKShare stock list adapter is not enabled yet.")

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            name="akshare",
            source="AKShare",
            supports_network=True,
            notes=("占位接口，尚未启用真实下载",),
        )
