"""Local CSV provider for offline and cached workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import pandas as pd

from data.providers.base import MarketDataProvider, ProviderMetadata


class LocalCsvProvider(MarketDataProvider):
    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.cache_dir = Path(self.config["data"]["cache_dir"])
        self.index_cache_dir = self.cache_dir / "index"

    def _read_csv(self, path: Path, start: str, end: str, dtype: Optional[dict] = None) -> pd.DataFrame:
        if not path.exists():
            raise FileNotFoundError(path)
        df = pd.read_csv(path, dtype=dtype or {"date": str})
        if df.empty:
            raise ValueError(f"空 CSV: {path}")
        df["date"] = pd.to_datetime(df["date"])
        mask = (df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))
        return df.loc[mask].sort_values("date").reset_index(drop=True)

    def get_daily(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        return self._read_csv(self.cache_dir / f"{symbol}.csv", start, end)

    def get_index_daily(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        path = self.index_cache_dir / f"{symbol}.csv"
        if not path.exists():
            path = self.cache_dir / f"{symbol}.csv"
        return self._read_csv(path, start, end, dtype={"date": str, "ts_code": str})

    def get_stock_list(self) -> list[dict]:
        if not self.cache_dir.exists():
            return []
        rows = []
        for path in sorted(self.cache_dir.glob("*.csv")):
            if path.name.startswith("_"):
                continue
            rows.append({"ts_code": path.stem, "name": path.stem})
        return rows

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            name="local_csv",
            source=str(self.cache_dir),
            supports_network=False,
            notes=("只读取本地缓存 CSV，不联网",),
        )
