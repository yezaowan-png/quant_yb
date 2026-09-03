"""CSV cache paths and small read/write helpers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd


class CsvCacheStore:
    """Local CSV cache layout used by the downloader and analysis commands."""

    def __init__(
        self,
        cache_dir: str | Path,
        meta_dir: str | Path | None = None,
        failed_downloads_dir: str | Path | None = None,
        signals_dir: str | Path = "output/signals",
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.index_cache_dir = self.cache_dir / "index"
        self.index_cache_dir.mkdir(parents=True, exist_ok=True)
        self.index_intraday_cache_dir = self.cache_dir / "index_intraday"
        self.index_intraday_cache_dir.mkdir(parents=True, exist_ok=True)

        self.meta_dir = Path(meta_dir) if meta_dir else self.cache_dir.parent / "meta"
        self.meta_dir.mkdir(parents=True, exist_ok=True)

        if failed_downloads_dir:
            self.failure_dir = Path(failed_downloads_dir)
        else:
            self.failure_dir = Path(signals_dir) / "download_failures"
        self.failure_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_config(cls, config: dict) -> "CsvCacheStore":
        data_cfg = config.get("data", {})
        output_cfg = config.get("output", {})
        return cls(
            cache_dir=data_cfg["cache_dir"],
            meta_dir=data_cfg.get("meta_dir"),
            failed_downloads_dir=output_cfg.get("failed_downloads_dir"),
            signals_dir=output_cfg.get("signals_dir", "output/signals"),
        )

    def stock_cache_path(self, symbol: str) -> Path:
        return self.cache_dir / f"{symbol}.csv"

    def index_cache_path(self, symbol: str) -> Path:
        return self.index_cache_dir / f"{symbol}.csv"

    def index_intraday_path(self, symbol: str, freq: str = "5min") -> Path:
        safe_freq = str(freq).lower().replace("/", "_")
        return self.index_intraday_cache_dir / f"{symbol.upper()}_{safe_freq}.csv"

    def stock_basic_path(self) -> Path:
        return self.meta_dir / "stocks.csv"

    def stock_name_map_path(self) -> Path:
        return self.meta_dir / "stock_names.csv"

    def daily_basic_dir(self) -> Path:
        path = self.meta_dir / "daily_basic"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def index_members_dir(self) -> Path:
        path = self.meta_dir / "index_members"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def index_members_path(self, index_code: str) -> Path:
        safe_code = index_code.upper().replace("/", "_")
        return self.index_members_dir() / f"{safe_code}.csv"

    def daily_basic_path(self, symbol: str | None = None) -> Path:
        if symbol:
            return self.daily_basic_dir() / f"{symbol.upper()}.csv"
        return self.daily_basic_dir()

    def kline_checked_dates_path(self) -> Path:
        return self.meta_dir / "kline_checked_dates.csv"

    @staticmethod
    def load_price_cache(path: Path, dtype: Optional[dict] = None) -> Optional[pd.DataFrame]:
        if not path.exists():
            return None
        df = pd.read_csv(path, dtype=dtype or {"date": str})
        if df.empty:
            return None
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)

    def load_stock_cache(self, symbol: str) -> Optional[pd.DataFrame]:
        return self.load_price_cache(self.stock_cache_path(symbol), dtype={"date": str})

    def load_index_cache(self, symbol: str) -> Optional[pd.DataFrame]:
        path = self.index_cache_path(symbol)
        if not path.exists():
            legacy_path = self.stock_cache_path(symbol)
            path = legacy_path if legacy_path.exists() else path
        return self.load_price_cache(path, dtype={"date": str, "ts_code": str})

    def load_index_intraday(self, symbol: str, freq: str = "5min") -> Optional[pd.DataFrame]:
        path = self.index_intraday_path(symbol, freq)
        if not path.exists():
            return None
        df = pd.read_csv(path, dtype={"ts_code": str, "trade_time": str})
        if df.empty or "trade_time" not in df.columns:
            return None
        df["trade_time"] = pd.to_datetime(df["trade_time"], errors="coerce")
        return df.dropna(subset=["trade_time"]).sort_values("trade_time").reset_index(drop=True)

    def save_index_intraday(self, symbol: str, freq: str, df: pd.DataFrame) -> Path:
        path = self.index_intraday_path(symbol, freq)
        existing = self.load_index_intraday(symbol, freq)
        combined = df.copy() if existing is None else pd.concat([existing, df], ignore_index=True)
        combined["trade_time"] = pd.to_datetime(combined["trade_time"], errors="coerce")
        combined = combined.dropna(subset=["trade_time"])
        combined = combined.drop_duplicates(subset=["trade_time"], keep="last").sort_values("trade_time")
        to_save = combined.copy()
        to_save["trade_time"] = to_save["trade_time"].dt.strftime("%Y-%m-%d %H:%M:%S")
        to_save.to_csv(path, index=False)
        return path

    @staticmethod
    def save_price_cache(path: Path, df: pd.DataFrame) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        df = df.drop_duplicates(subset=["date"], keep="last").sort_values("date")
        df_to_save = df.copy()
        df_to_save["date"] = pd.to_datetime(df_to_save["date"]).dt.strftime("%Y%m%d")
        df_to_save.to_csv(path, index=False)

    def load_kline_checked_dates(self) -> set[str]:
        path = self.kline_checked_dates_path()
        if not path.exists():
            return set()
        try:
            df = pd.read_csv(path, dtype={"trade_date": str})
        except Exception:
            return set()
        if df.empty or "trade_date" not in df.columns:
            return set()
        return set(df["trade_date"].dropna().astype(str))

    def record_kline_checked_date(self, trade_date: str, rows: int, target_symbols: int) -> None:
        path = self.kline_checked_dates_path()
        record = pd.DataFrame(
            [
                {
                    "trade_date": str(trade_date),
                    "rows": int(rows),
                    "target_symbols": int(target_symbols),
                    "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            ]
        )
        if path.exists():
            try:
                existing = pd.read_csv(path, dtype={"trade_date": str})
            except Exception:
                existing = pd.DataFrame()
            record = pd.concat([existing, record], ignore_index=True)
        record = record.drop_duplicates(subset=["trade_date"], keep="last")
        record = record.sort_values("trade_date").reset_index(drop=True)
        record.to_csv(path, index=False)

    def load_daily_basic(self, symbol: str) -> Optional[pd.DataFrame]:
        path = self.daily_basic_path(symbol)
        if not path.exists():
            return None
        df = pd.read_csv(path, dtype={"ts_code": str, "trade_date": str})
        if df.empty:
            return None
        return df.sort_values("trade_date").reset_index(drop=True)

    def daily_basic_cached_dates(self) -> set[str]:
        dates: set[str] = set()
        for path in self.daily_basic_dir().glob("*.csv"):
            try:
                cached = pd.read_csv(path, usecols=["trade_date"], dtype={"trade_date": str})
            except Exception:
                continue
            if cached.empty:
                continue
            dates.update(cached["trade_date"].dropna().astype(str).unique().tolist())
        return dates

    def save_daily_basic_by_symbol(self, df: pd.DataFrame) -> int:
        if df is None or df.empty:
            return 0
        saved = 0
        for symbol, part in df.groupby("ts_code", sort=False):
            symbol = str(symbol).upper()
            path = self.daily_basic_path(symbol)
            existing = self.load_daily_basic(symbol)
            combined = part.copy() if existing is None else pd.concat([existing, part], ignore_index=True)
            combined = combined.drop_duplicates(subset=["trade_date"], keep="last")
            combined = combined.sort_values("trade_date").reset_index(drop=True)
            combined.to_csv(path, index=False)
            saved += len(part)
        return saved

    def load_index_members(self, index_code: str) -> Optional[pd.DataFrame]:
        path = self.index_members_path(index_code)
        if not path.exists():
            return None
        df = pd.read_csv(path, dtype={"index_code": str, "con_code": str, "trade_date": str})
        if df.empty:
            return None
        return df.sort_values(["trade_date", "con_code"]).reset_index(drop=True)

    def save_index_members(self, index_code: str, df: pd.DataFrame) -> Path:
        path = self.index_members_path(index_code)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = self.load_index_members(index_code)
        combined = df.copy() if existing is None else pd.concat([existing, df], ignore_index=True)
        combined = combined.drop_duplicates(
            subset=["index_code", "con_code", "trade_date"],
            keep="last",
        )
        combined = combined.sort_values(["trade_date", "con_code"]).reset_index(drop=True)
        combined.to_csv(path, index=False)
        return path
