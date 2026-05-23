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
import tushare as ts


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

    def __init__(self, config: Optional[dict] = None):
        self.config = config or load_config()
        self.cache_dir = Path(self.config["data"]["cache_dir"])
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        token = self.config["tushare"]["token"]
        ts.set_token(token)
        self.pro = ts.pro_api()

        rpm = self.config.get("rate_limit", {}).get("calls_per_minute", 200)
        self._rate_limiter = RateLimiter(rpm)
        self._max_workers = self.config.get("parallel", {}).get("download_workers", 5)

    def _cache_path(self, symbol: str) -> Path:
        return self.cache_dir / f"{symbol}.csv"

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

    def get_stock_list(self) -> list[dict]:
        """获取全A股股票列表（剔除ST股票）。

        Returns:
            [{"ts_code": "000001.SZ", "name": "平安银行"}, ...]
        """
        click.echo("  正在获取全A股股票列表 ...")
        self._rate_limiter.wait()
        try:
            df = self.pro.stock_basic(
                exchange="",
                list_status="L",
                fields="ts_code,name",
            )
        except Exception as e:
            click.echo(f"  获取股票列表失败: {e}", err=True)
            return []

        if df is None or df.empty:
            click.echo("  股票列表为空。")
            return []

        df = df[~df["name"].str.contains("ST", na=False)]
        click.echo(f"  获取到 {len(df)} 只非ST股票。")
        return df[["ts_code", "name"]].to_dict("records")

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

    def _fetch_from_api(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        """通过限流器调用 Tushare API 并清洗存入缓存"""
        self._rate_limiter.wait()
        try:
            raw = self.pro.daily(
                ts_code=symbol,
                start_date=start,
                end_date=end,
                fields="trade_date,open,high,low,close,vol,amount",
            )
        except Exception as e:
            click.echo(f"  [{symbol}] API 调用失败: {e}", err=True)
            raise

        if raw is None or raw.empty:
            raise ValueError(f"无数据: {symbol}")

        df = self._clean(raw)
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
                click.echo(f"  ⏱ 预计约需 {est_minutes:.0f} 分钟 {est_minutes * 60:.0f} 秒")
            else:
                click.echo(f"  ⏱ 预计约需 {est_minutes * 60:.0f} 秒")
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
