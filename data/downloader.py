"""Tushare 数据下载与本地缓存"""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Optional

import click
import pandas as pd
import yaml

from data.providers import create_provider


def load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def today_str() -> str:
    return date.today().strftime("%Y%m%d")


def default_start() -> str:
    config = load_config()
    return config.get("defaults", {}).get("start_date", "20210101")


class RateLimiter:
    """滑动窗口限流器 —— 控制 API 调用频率，不阻塞并发线程"""

    def __init__(self, calls_per_minute: int = 200):
        self._min_interval = 60.0 / calls_per_minute
        self._last_call = 0.0
        self._lock = threading.Lock()

    def wait(self):
        """等待直到可以发起下一次 API 调用"""
        with self._lock:
            now = time.monotonic()
            wait = self._last_call + self._min_interval - now
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()


class DataDownloader:
    """A股日K线数据下载器，带本地 CSV 缓存与增量更新，支持并行下载"""

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

    def __init__(self, config: Optional[dict] = None):
        self.config = config or load_config()
        self.cache_dir = Path(self.config["data"]["cache_dir"])
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.index_cache_dir = self.cache_dir / "index"
        self.index_cache_dir.mkdir(parents=True, exist_ok=True)

        rpm = self.config.get("rate_limit", {}).get("calls_per_minute", 200)
        self._rate_limiter = RateLimiter(rpm)
        self._max_workers = self.config.get("parallel", {}).get("download_workers", 5)
        self.provider = create_provider(self.config, rate_limiter=self._rate_limiter)

    def _cache_path(self, symbol: str) -> Path:
        return self.cache_dir / f"{symbol}.csv"

    def _index_cache_path(self, symbol: str) -> Path:
        return self.index_cache_dir / f"{symbol}.csv"

    def _is_index_symbol(self, symbol: str) -> bool:
        code, _, market = symbol.partition(".")
        return (market == "SH" and code.startswith("000")) or (
            market == "SZ" and code.startswith("399")
        )

    def _load_cache(self, symbol: str) -> Optional[pd.DataFrame]:
        """加载本地缓存，不存在返回 None"""
        path = self._cache_path(symbol)
        if not path.exists():
            return None
        df = pd.read_csv(path, dtype={"date": str})
        if df.empty:
            return None
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)

    def load_index_cache(self, symbol: str) -> Optional[pd.DataFrame]:
        """加载指数缓存，优先读取 data/cache/index，兼容旧的根目录缓存。"""
        path = self._index_cache_path(symbol)
        if not path.exists():
            legacy_path = self._cache_path(symbol)
            path = legacy_path if legacy_path.exists() else path
        if not path.exists():
            return None
        df = pd.read_csv(path, dtype={"date": str, "ts_code": str})
        if df.empty:
            return None
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)

    def _save_cache(self, symbol: str, df: pd.DataFrame) -> None:
        """保存到本地 CSV，去重排序，日期统一存为 YYYYMMDD 格式"""
        path = self._cache_path(symbol)
        existing = self._load_cache(symbol)
        if existing is not None:
            df = pd.concat([existing, df], ignore_index=True)
        df = df.drop_duplicates(subset=["date"]).sort_values("date")
        df_to_save = df.copy()
        df_to_save["date"] = df_to_save["date"].dt.strftime("%Y%m%d")
        df_to_save.to_csv(path, index=False)

    def _save_index_cache(self, symbol: str, df: pd.DataFrame) -> None:
        """保存指数 CSV 到 data/cache/index/{symbol}.csv。"""
        path = self._index_cache_path(symbol)
        existing = self.load_index_cache(symbol)
        if existing is not None:
            df = pd.concat([existing, df], ignore_index=True)
        df = df.drop_duplicates(subset=["date"]).sort_values("date")
        df_to_save = df.copy()
        df_to_save["date"] = df_to_save["date"].dt.strftime("%Y%m%d")
        df_to_save.to_csv(path, index=False)

    def get_stock_list(self) -> list[dict]:
        """获取全A股股票列表（剔除ST股票）。

        Returns:
            [{"ts_code": "000001.SZ", "name": "平安银行"}, ...]
        """
        click.echo("  正在获取全A股股票列表 ...")
        try:
            rows = self.provider.get_stock_list()
        except Exception as e:
            click.echo(f"  获取股票列表失败: {e}", err=True)
            return []

        if not rows:
            click.echo("  股票列表为空。")
            return []

        click.echo(f"  获取到 {len(rows)} 只非ST股票。")
        return rows

    def download(
        self,
        symbol: str,
        start: str,
        end: str,
        force: bool = False,
    ) -> pd.DataFrame:
        """
        下载单只股票日K线数据。

        Args:
            symbol: 股票代码，如 000001.SZ
            start: 起始日期 YYYYMMDD
            end: 结束日期 YYYYMMDD
            force: 是否强制重新下载（忽略缓存）

        Returns:
            清洗后的 DataFrame
        """
        if not force:
            cached = self._load_cache(symbol)
            if cached is not None:
                cached_start = cached["date"].min().strftime("%Y%m%d")
                cached_end = cached["date"].max().strftime("%Y%m%d")

                if cached_start <= start and cached_end >= end:
                    mask = (cached["date"] >= pd.Timestamp(start)) & (
                        cached["date"] <= pd.Timestamp(end)
                    )
                    return cached[mask].reset_index(drop=True)

        try:
            df = self._fetch_from_api(symbol, start, end)
        except Exception:
            cached = self._load_cache(symbol)
            if cached is not None:
                mask = (cached["date"] >= pd.Timestamp(start)) & (
                    cached["date"] <= pd.Timestamp(end)
                )
                return cached[mask].reset_index(drop=True)
            raise

        return df

    def download_index(
        self,
        symbol: str = "000001.SH",
        start: str = "20210101",
        end: Optional[str] = None,
        force: bool = False,
    ) -> pd.DataFrame:
        """下载单个指数日线，使用 Tushare index_daily 接口。"""
        end = end or today_str()
        symbol = symbol.upper()
        if not force:
            cached = self.load_index_cache(symbol)
            if cached is not None:
                cached_start = cached["date"].min().strftime("%Y%m%d")
                cached_end = cached["date"].max().strftime("%Y%m%d")

                if cached_start <= start and cached_end >= end:
                    mask = (cached["date"] >= pd.Timestamp(start)) & (
                        cached["date"] <= pd.Timestamp(end)
                    )
                    return cached[mask].reset_index(drop=True)

        try:
            df = self._fetch_index_from_api(symbol, start, end)
        except Exception:
            cached = self.load_index_cache(symbol)
            if cached is not None:
                mask = (cached["date"] >= pd.Timestamp(start)) & (
                    cached["date"] <= pd.Timestamp(end)
                )
                return cached[mask].reset_index(drop=True)
            raise

        return df

    def _fetch_index_from_api(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        """Fetch index daily bars through configured provider and write cache."""
        try:
            df = self.provider.get_index_daily(symbol, start, end)
        except Exception as e:
            click.echo(f"  [{symbol}] 指数数据获取失败: {e}", err=True)
            raise

        if df is None or df.empty:
            raise ValueError(f"无指数数据: {symbol}")

        self._save_index_cache(symbol, df)
        return df

    def _fetch_from_api(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        """Fetch daily bars through configured provider and write cache."""
        try:
            if self._is_index_symbol(symbol):
                df = self.provider.get_index_daily(symbol, start, end)
            else:
                df = self.provider.get_daily(symbol, start, end)
        except Exception as e:
            click.echo(f"  [{symbol}] 数据获取失败: {e}", err=True)
            raise

        if df is None or df.empty:
            raise ValueError(f"无数据: {symbol}")

        self._save_cache(symbol, df)
        return df

    def download_batch(
        self,
        symbols: list[str],
        start: str,
        end: str,
        force: bool = False,
    ) -> dict[str, pd.DataFrame]:
        """并行批量下载，带限流和进度预估"""
        results: dict[str, pd.DataFrame] = {}
        total = len(symbols)
        workers = max(1, self._max_workers)
        rpm = self.config.get("rate_limit", {}).get("calls_per_minute", 200)

        # ---- 预估时间 ----
        cached_count = 0
        if not force:
            for sym in symbols:
                cached = self._load_cache(sym)
                if cached is not None:
                    cs = cached["date"].min().strftime("%Y%m%d")
                    ce = cached["date"].max().strftime("%Y%m%d")
                    if cs <= start and ce >= end:
                        cached_count += 1

        need_api = total - cached_count
        if need_api > 0:
            api_sec_per_stock = 60.0 / rpm
            est_minutes = (need_api * api_sec_per_stock) / workers
            click.echo(f"  共 {total} 只 | 缓存命中 {cached_count} 只 | 需下载 {need_api} 只")
            click.echo(f"  并行线程: {workers} | API限速: {rpm}次/分钟")
            if est_minutes >= 1:
                click.echo(f"  预计约需 {est_minutes:.0f} 分钟 {est_minutes * 60:.0f} 秒")
            else:
                click.echo(f"  预计约需 {est_minutes * 60:.0f} 秒")
        else:
            click.echo(f"  共 {total} 只 | 全部已缓存，直接从本地读取")

        # ---- 并行下载 ----
        start_ts = time.monotonic()
        completed = 0
        lock = threading.Lock()

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(self.download, sym, start, end, force): sym
                for sym in symbols
            }
            for future in as_completed(futures):
                sym = futures[future]
                with lock:
                    completed += 1
                try:
                    results[sym] = future.result()
                except Exception as e:
                    with lock:
                        click.echo(f"  [{sym}] 下载失败: {e}", err=True)
                if completed % 50 == 0 or completed == total:
                    elapsed = time.monotonic() - start_ts
                    click.echo(f"  进度: {completed}/{total}  已耗时: {elapsed:.0f}s")

        elapsed = time.monotonic() - start_ts
        click.echo(f"  下载完成，总耗时: {elapsed:.0f} 秒 ({elapsed/60:.1f} 分钟)")
        return results

    def _clean(self, raw: pd.DataFrame) -> pd.DataFrame:
        """清洗为标准格式"""
        df = raw.rename(columns=self.COLUMN_MAP)
        keep_cols = ["date", "open", "high", "low", "close", "volume", "amount"]
        df = df[[c for c in keep_cols if c in df.columns]]

        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
        for col in ["open", "high", "low", "close", "volume", "amount"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
        return df.reset_index(drop=True)

    def _clean_index(self, raw: pd.DataFrame) -> pd.DataFrame:
        """清洗指数日线，保留涨跌幅字段供概览分析使用。"""
        df = raw.rename(columns=self.INDEX_COLUMN_MAP)
        keep_cols = [
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
        ]
        df = df[[c for c in keep_cols if c in df.columns]]

        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
        for col in [
            "open",
            "high",
            "low",
            "close",
            "pre_close",
            "change",
            "pct_chg",
            "volume",
            "amount",
        ]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
        return df.reset_index(drop=True)
