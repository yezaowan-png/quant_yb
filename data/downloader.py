"""Tushare 数据下载与本地缓存"""

import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional

import click
import pandas as pd
import tushare as ts

from data.adjustment import apply_price_adjustment, is_adjusted_mode, overlap_price_mismatch
from data.cache_store import CsvCacheStore
from data.download_failures import load_symbols_from_file, write_failure_snapshot
from data.download_planner import estimate_download_plan
from data.download_retry import build_retry_commands, is_retryable_download_error, retry_symbols
from data.download_service import download_symbols_parallel, format_download_plan_messages
from data.market_benchmark import (
    MARKET_BENCHMARK_SYMBOL,
    build_average_price_index_from_stock_cache,
    is_market_benchmark_symbol,
)
from data.metadata import (
    build_stock_name_map,
    clean_daily_basic,
    clean_stock_basic,
    filter_non_st_stocks,
    missing_daily_basic_dates,
)
from data.price_cleaning import (
    INDEX_DAILY_COLUMN_MAP,
    STOCK_DAILY_COLUMN_MAP,
    clean_index_daily,
    clean_stock_daily,
    clean_ths_index_daily,
)
from data.tushare_client import TushareClient
from project_config import load_project_config


def load_config() -> dict:
    return load_project_config()


def today_str() -> str:
    return date.today().strftime("%Y%m%d")


def default_start() -> str:
    config = load_config()
    return config.get("defaults", {}).get("start_date", "20210101")


class DataDownloader:
    """A股日K线数据下载器，带本地 CSV 缓存与增量更新，支持并行下载"""

    COLUMN_MAP = STOCK_DAILY_COLUMN_MAP
    INDEX_COLUMN_MAP = INDEX_DAILY_COLUMN_MAP
    STOCK_BASIC_FIELDS = ",".join(
        [
            "ts_code",
            "symbol",
            "name",
            "area",
            "industry",
            "fullname",
            "enname",
            "cnspell",
            "market",
            "exchange",
            "curr_type",
            "list_status",
            "list_date",
            "delist_date",
            "is_hs",
        ]
    )
    DAILY_BASIC_FIELDS = ",".join(
        [
            "ts_code",
            "trade_date",
            "close",
            "turnover_rate",
            "turnover_rate_f",
            "volume_ratio",
            "pe",
            "pe_ttm",
            "pb",
            "ps",
            "ps_ttm",
            "dv_ratio",
            "dv_ttm",
            "total_share",
            "float_share",
            "free_share",
            "total_mv",
            "circ_mv",
        ]
    )

    def __init__(self, config: Optional[dict] = None):
        self.config = config or load_config()
        self.cache_store = CsvCacheStore.from_config(self.config)
        self.cache_dir = self.cache_store.cache_dir
        self.index_cache_dir = self.cache_store.index_cache_dir
        self.stock_adj = self.config.get("data", {}).get("stock_adj", "qfq")
        self.last_failed_symbols: list[str] = []
        self.last_failed_errors: dict[str, str] = {}
        self.last_failed_file: Optional[Path] = None
        self.failed_record_files: list[Path] = []

        rate_cfg = self.config.get("rate_limit", {})
        self._failed_retry_rounds = int(rate_cfg.get("failed_retry_rounds", 2))
        self._failed_retry_wait_seconds = float(rate_cfg.get("failed_retry_wait_seconds", 120))
        self._max_workers = self.config.get("parallel", {}).get("download_workers", 5)
        self._cancel_event = threading.Event()
        self.tushare_client = TushareClient.from_config(self.config, self._cancel_event)
        self._download_run_id = ""
        self.pro = self.tushare_client.primary_api

    def _cache_path(self, symbol: str) -> Path:
        return self.cache_store.stock_cache_path(symbol)

    def _index_cache_path(self, symbol: str) -> Path:
        return self.cache_store.index_cache_path(symbol)

    def _index_intraday_path(self, symbol: str, freq: str = "5min") -> Path:
        return self.cache_store.index_intraday_path(symbol, freq)

    def _meta_dir(self) -> Path:
        return self.cache_store.meta_dir

    def _stock_basic_path(self) -> Path:
        return self.cache_store.stock_basic_path()

    def _stock_name_map_path(self) -> Path:
        return self.cache_store.stock_name_map_path()

    def _daily_basic_dir(self) -> Path:
        return self.cache_store.daily_basic_dir()

    def _daily_basic_path(self, symbol: str | None = None) -> Path:
        return self.cache_store.daily_basic_path(symbol)

    def _index_members_path(self, index_code: str) -> Path:
        return self.cache_store.index_members_path(index_code)

    def _ths_index_list_path(self) -> Path:
        return self._meta_dir() / "ths_indices.csv"

    def _kline_checked_dates_path(self) -> Path:
        return self.cache_store.kline_checked_dates_path()

    def _failure_dir(self) -> Path:
        return self.cache_store.failure_dir

    @staticmethod
    def load_symbols_from_file(path: str | Path) -> list[str]:
        """从失败 CSV 或普通文本中读取股票代码。"""
        return load_symbols_from_file(path)

    def _is_index_symbol(self, symbol: str) -> bool:
        if is_market_benchmark_symbol(symbol):
            return True
        code, _, market = symbol.partition(".")
        return (market == "SH" and code.startswith("000")) or (
            market == "SZ" and code.startswith("399")
        )

    def _write_failure_snapshot(
        self,
        failed: dict[str, str],
        start: str,
        end: str,
        stage: str,
    ) -> Optional[Path]:
        """把当前剩余失败股票写入 CSV，方便后续增量补下载。"""
        run_id = self._download_run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        path = write_failure_snapshot(
            self._failure_dir(),
            failed,
            start,
            end,
            stage,
            self.stock_adj,
            run_id,
        )
        if path is None:
            return None
        self.last_failed_file = path
        self.failed_record_files.append(path)
        return path

    def _stock_cache_matches_adjustment(self, cached: Optional[pd.DataFrame]) -> bool:
        """股票缓存必须和当前复权口径一致；旧缓存没有 adj 列时视为不匹配。"""
        expected = self.stock_adj or "raw"
        if cached is None or cached.empty:
            return False
        if "adj" not in cached.columns:
            return expected == "raw"
        cached_adj = cached["adj"].fillna("raw").astype(str).str.lower()
        return bool((cached_adj == str(expected).lower()).all())

    def _load_cache(self, symbol: str) -> Optional[pd.DataFrame]:
        """加载本地缓存，不存在返回 None"""
        return self.cache_store.load_stock_cache(symbol)

    @staticmethod
    def _cache_covers_range(cached: Optional[pd.DataFrame], start: str, end: str) -> bool:
        if cached is None or cached.empty:
            return False
        cached_start = cached["date"].min().strftime("%Y%m%d")
        cached_end = cached["date"].max().strftime("%Y%m%d")
        return cached_start <= start and cached_end >= end

    @staticmethod
    def _slice_cache(cached: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
        mask = (cached["date"] >= pd.Timestamp(start)) & (
            cached["date"] <= pd.Timestamp(end)
        )
        return cached[mask].reset_index(drop=True)

    @staticmethod
    def _date_str(ts: pd.Timestamp) -> str:
        return pd.Timestamp(ts).strftime("%Y%m%d")

    @staticmethod
    def _parse_yyyymmdd(value: str) -> pd.Timestamp:
        return pd.to_datetime(str(value), format="%Y%m%d")

    @staticmethod
    def _next_day_str(ts: pd.Timestamp) -> str:
        return (pd.Timestamp(ts) + pd.Timedelta(days=1)).strftime("%Y%m%d")

    @staticmethod
    def _prev_day_str(ts: pd.Timestamp) -> str:
        return (pd.Timestamp(ts) - pd.Timedelta(days=1)).strftime("%Y%m%d")

    def _adjusted_stock_cache(self) -> bool:
        return is_adjusted_mode(self.stock_adj)

    @staticmethod
    def _overlap_price_mismatch(existing: pd.DataFrame, fetched: pd.DataFrame) -> bool:
        return overlap_price_mismatch(existing, fetched)

    def load_index_cache(self, symbol: str) -> Optional[pd.DataFrame]:
        """加载指数缓存，优先读取 data/cache/index，兼容旧的根目录缓存。"""
        return self.cache_store.load_index_cache(symbol)

    def _save_cache(self, symbol: str, df: pd.DataFrame) -> None:
        """保存到本地 CSV，去重排序，日期统一存为 YYYYMMDD 格式"""
        path = self._cache_path(symbol)
        existing = self._load_cache(symbol)
        if existing is not None and (
            self._is_index_symbol(symbol) or self._stock_cache_matches_adjustment(existing)
        ):
            df = pd.concat([existing, df], ignore_index=True)
        self.cache_store.save_price_cache(path, df)

    def _save_index_cache(self, symbol: str, df: pd.DataFrame) -> None:
        """保存指数 CSV 到 data/cache/index/{symbol}.csv。"""
        path = self._index_cache_path(symbol)
        existing = self.load_index_cache(symbol)
        if existing is not None:
            df = pd.concat([existing, df], ignore_index=True)
        self.cache_store.save_price_cache(path, df)

    def _load_kline_checked_dates(self) -> set[str]:
        """读取已按全市场日截面检查过的 K 线交易日。"""
        return self.cache_store.load_kline_checked_dates()

    def _record_kline_checked_date(self, trade_date: str, rows: int, target_symbols: int) -> None:
        """记录某个交易日已经全市场拉取并拆分处理过。"""
        self.cache_store.record_kline_checked_date(trade_date, rows, target_symbols)

    def _datewise_stock_update_eligible(
        self,
        symbols: list[str],
        start: str,
        end: str,
        force: bool,
    ) -> bool:
        """是否适合按交易日全市场下载再拆分。

        只用于已有股票缓存的尾部增量更新。首次建库、强制刷新、补历史头部、
        指数数据仍走逐标的逻辑，避免前复权历史重算不完整。
        """
        if force or not symbols:
            return False
        requested_end = self._parse_yyyymmdd(end)
        needs_tail = False
        for symbol in symbols:
            if self._is_index_symbol(symbol):
                return False
            cached = self._load_cache(symbol)
            if cached is None or not self._stock_cache_matches_adjustment(cached):
                return False
            if self._adjusted_stock_cache() and "adj_factor" not in cached.columns:
                return False
            if requested_end > cached["date"].max():
                needs_tail = True
        return needs_tail

    def _datewise_stock_update_groups(
        self,
        symbols: list[str],
        start: str,
        end: str,
        force: bool,
    ) -> tuple[list[str], list[str]]:
        """Split symbols into datewise-tail eligible and regular-download groups."""
        if force or not symbols:
            return [], list(symbols)
        requested_start = self._parse_yyyymmdd(start)
        requested_end = self._parse_yyyymmdd(end)
        eligible: list[str] = []
        regular: list[str] = []
        for symbol in symbols:
            if self._is_index_symbol(symbol):
                regular.append(symbol)
                continue
            cached = self._load_cache(symbol)
            if cached is None or cached.empty:
                regular.append(symbol)
                continue
            if not self._stock_cache_matches_adjustment(cached):
                regular.append(symbol)
                continue
            if self._adjusted_stock_cache() and "adj_factor" not in cached.columns:
                regular.append(symbol)
                continue
            if requested_start < cached["date"].min():
                regular.append(symbol)
                continue
            if requested_end > cached["date"].max():
                eligible.append(symbol)
            else:
                regular.append(symbol)
        return eligible, regular

    def _fetch_stock_daily_by_trade_date(self, trade_date: str) -> pd.DataFrame:
        """按交易日下载全市场股票日线。"""
        return self._call_tushare_with_retry(
            trade_date,
            "daily",
            lambda pro, d=trade_date: pro.daily(
                trade_date=d,
                fields="ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
            ),
        )

    def _fetch_adj_factor_by_trade_date(self, trade_date: str) -> pd.DataFrame:
        """按交易日下载全市场复权因子。"""
        return self._call_tushare_with_retry(
            trade_date,
            "adj_factor",
            lambda pro, d=trade_date: pro.adj_factor(
                trade_date=d,
                fields="ts_code,trade_date,adj_factor",
            ),
        )

    def download_stock_kline_by_date(
        self,
        symbols: list[str],
        start: str,
        end: str,
    ) -> dict[str, pd.DataFrame]:
        """按交易日下载全市场 K 线，再拆分追加到各股票 CSV。

        该方法只处理已有缓存的尾部增量。若发现某只股票复权因子变化，
        会对该股票从本地缓存起点到本次结束日期做一次逐标的刷新。
        """
        click.echo(f"  正在获取交易日历: {start} ~ {end}")
        trade_dates = self._trade_dates(start, end)
        click.echo(f"  交易日数量: {len(trade_dates)}")
        symbol_set = {s.upper() for s in symbols}
        click.echo(f"  正在扫描本地K线缓存缺口: {len(symbols)} 只股票")
        cached_map = {}
        for idx, symbol in enumerate(symbols, start=1):
            cached_map[symbol] = self._load_cache(symbol)
            if idx % 1000 == 0 or idx == len(symbols):
                click.echo(f"  缓存扫描进度: {idx}/{len(symbols)}")
        date_targets: dict[str, list[str]] = {}
        for symbol, cached in cached_map.items():
            if cached is None or cached.empty:
                continue
            cached_end = cached["date"].max()
            missing = [
                d for d in trade_dates
                if self._parse_yyyymmdd(d) > cached_end
            ]
            for d in missing:
                date_targets.setdefault(d, []).append(symbol)

        checked_dates = self._load_kline_checked_dates()
        if checked_dates:
            before = len(date_targets)
            date_targets = {
                d: targets
                for d, targets in date_targets.items()
                if d not in checked_dates
            }
            skipped = before - len(date_targets)
            if skipped:
                click.echo(f"  已跳过 {skipped} 个此前检查过的交易日。")

        if not date_targets:
            click.echo("  K线缓存已覆盖请求区间，无需按交易日增量更新。")
            return {s: pd.DataFrame() for s in symbols}

        adj = self.stock_adj
        use_adjustment = not (adj is None or str(adj).lower() in {"", "none", "raw"})
        refresh_symbols: set[str] = set()
        updated_symbols: set[str] = set()
        total_rows = 0
        dates = sorted(date_targets)
        click.echo(f"  按交易日增量下载K线: {len(dates)} 个交易日，{len(symbols)} 只股票")

        for idx, trade_date in enumerate(dates, start=1):
            click.echo(f"  [{trade_date}] 下载 daily ({idx}/{len(dates)}) ...")
            raw = self._fetch_stock_daily_by_trade_date(trade_date)
            if raw is None or raw.empty:
                click.echo(f"  [{trade_date}] daily 为空，跳过。")
                continue
            click.echo(f"  [{trade_date}] daily 返回 {len(raw)} 条")
            raw = raw[raw["ts_code"].astype(str).str.upper().isin(symbol_set)].copy()
            if raw.empty:
                click.echo(f"  [{trade_date}] 没有匹配目标股票，跳过。")
                continue

            if use_adjustment:
                click.echo(f"  [{trade_date}] 下载 adj_factor ...")
                factors = self._fetch_adj_factor_by_trade_date(trade_date)
                if factors is None or factors.empty:
                    click.echo(f"  [{trade_date}] adj_factor 为空，跳过复权处理。")
                    factors = pd.DataFrame(columns=["ts_code", "trade_date", "adj_factor"])
                else:
                    click.echo(f"  [{trade_date}] adj_factor 返回 {len(factors)} 条")
                factors = factors.copy()
                factors["ts_code"] = factors["ts_code"].astype(str).str.upper()
                raw["ts_code"] = raw["ts_code"].astype(str).str.upper()
                merged = raw.merge(
                    factors[["ts_code", "trade_date", "adj_factor"]],
                    on=["ts_code", "trade_date"],
                    how="left",
                )
            else:
                merged = raw

            target_symbols = set(date_targets.get(trade_date, []))
            merged = merged[merged["ts_code"].isin(target_symbols)]
            written_for_date = 0
            for symbol, part in merged.groupby("ts_code", sort=False):
                symbol = str(symbol).upper()
                cached = cached_map.get(symbol)
                if cached is None or cached.empty:
                    continue

                if use_adjustment and "adj_factor" in part.columns and "adj_factor" in cached.columns:
                    old_factor = pd.to_numeric(cached["adj_factor"], errors="coerce").dropna()
                    new_factor = pd.to_numeric(part["adj_factor"], errors="coerce").dropna()
                    if not old_factor.empty and not new_factor.empty:
                        if abs(float(old_factor.iloc[-1]) - float(new_factor.iloc[-1])) > 1e-8:
                            refresh_symbols.add(symbol)

                cleaned = self._clean(part, adj=None if not use_adjustment else self.stock_adj)
                self._save_cache(symbol, cleaned)
                updated_symbols.add(symbol)
                total_rows += len(cleaned)
                written_for_date += len(cleaned)

            self._record_kline_checked_date(
                trade_date,
                rows=written_for_date,
                target_symbols=len(target_symbols),
            )

            if idx % 20 == 0 or idx == len(dates):
                click.echo(f"  进度: {idx}/{len(dates)} 个交易日，写入 {total_rows} 条K线")

        if refresh_symbols:
            click.echo(f"  {len(refresh_symbols)} 只股票复权因子变化，逐标的刷新前复权缓存。")
            for symbol in sorted(refresh_symbols):
                cached = self._load_cache(symbol)
                if cached is None or cached.empty:
                    continue
                refresh_start = self._date_str(cached["date"].min())
                df = self._fetch_api_clean(symbol, refresh_start, end)
                self._save_cache(symbol, df)

        click.echo(f"  按交易日K线增量完成: {len(updated_symbols)} 只股票，{total_rows} 条记录")
        return {s: pd.DataFrame() for s in symbols}

    def get_stock_list(self) -> list[dict]:
        """获取全A股股票列表（剔除ST股票）。

        Returns:
            [{"ts_code": "000001.SZ", "name": "平安银行"}, ...]
        """
        click.echo("  正在获取全A股股票列表 ...")
        try:
            df = self._call_tushare_with_retry(
                "stock_basic",
                "stock_basic",
                lambda pro: pro.stock_basic(
                    exchange="",
                    list_status="L",
                    fields="ts_code,name",
                ),
            )
        except Exception as e:
            click.echo(f"  获取股票列表失败: {e}", err=True)
            return []

        if df is None or df.empty:
            click.echo("  股票列表为空。")
            return []

        df = filter_non_st_stocks(df)
        click.echo(f"  获取到 {len(df)} 只非ST股票。")
        return df[["ts_code", "name"]].to_dict("records")

    def download_stock_basic(self, list_status: str = "L", force: bool = False) -> pd.DataFrame:
        """下载股票基础信息，并保存代码名称映射表。"""
        path = self._stock_basic_path()
        name_map_path = self._stock_name_map_path()
        if path.exists() and not force:
            df = pd.read_csv(path, dtype=str)
            click.echo(f"  使用已缓存股票基础信息: {path}")
        else:
            status = (list_status or "L").upper()
            click.echo(f"  正在下载股票基础信息 list_status={status} ...")
            df = self._call_tushare_with_retry(
                "stock_basic",
                "stock_basic",
                lambda pro: pro.stock_basic(
                    exchange="",
                    list_status=status,
                    fields=self.STOCK_BASIC_FIELDS,
                ),
            )
            if df is None or df.empty:
                raise ValueError("股票基础信息为空")
            df = clean_stock_basic(df)
            df.to_csv(path, index=False)

        name_map = build_stock_name_map(df)
        if not name_map.empty:
            name_map.to_csv(name_map_path, index=False)
        return df

    def load_daily_basic(self, symbol: str) -> Optional[pd.DataFrame]:
        """读取单只股票每日指标缓存。"""
        return self.cache_store.load_daily_basic(symbol)

    def load_index_members(self, index_code: str) -> Optional[pd.DataFrame]:
        """读取指数成分缓存。"""
        return self.cache_store.load_index_members(index_code)

    def download_index_members(
        self,
        index_code: str,
        start: str,
        end: str,
        force: bool = False,
    ) -> pd.DataFrame:
        """下载指数成分和权重，并增量保存到 meta/index_members。"""
        index_code = index_code.upper()
        path = self._index_members_path(index_code)
        cached = None if force else self.load_index_members(index_code)
        if cached is not None and not cached.empty:
            cached_start = str(cached["trade_date"].min())
            cached_end = str(cached["trade_date"].max())
            if cached_start <= start and cached_end >= end:
                click.echo(f"  使用已缓存指数成分: {path}")
                return cached

        click.echo(f"  正在下载指数成分: {index_code} {start} ~ {end}")
        df = self._call_tushare_with_retry(
            index_code,
            "index_weight",
            lambda pro: pro.index_weight(
                index_code=index_code,
                start_date=start,
                end_date=end,
                fields="index_code,con_code,trade_date,weight",
            ),
        )
        if df is None or df.empty:
            raise ValueError(f"指数成分为空: {index_code}")
        df = df.copy()
        for col in ["index_code", "con_code", "trade_date"]:
            if col in df.columns:
                df[col] = df[col].astype(str)
        if "weight" in df.columns:
            df["weight"] = pd.to_numeric(df["weight"], errors="coerce")
        saved_path = self.cache_store.save_index_members(index_code, df)
        click.echo(f"  指数成分已保存: {saved_path}")
        saved = self.load_index_members(index_code)
        return saved if saved is not None else df

    def _daily_basic_cached_dates(self) -> set[str]:
        """返回已完整落地过的 daily_basic 日期。

        日期只要在任意股票文件中出现，就视为已抓过该交易日；如果需要重抓，
        可使用 --force 覆盖指定日期区间。
        """
        return self.cache_store.daily_basic_cached_dates()

    def _save_daily_basic_by_symbol(self, df: pd.DataFrame) -> int:
        """把 daily_basic 全市场日截面拆分追加到每只股票自己的 CSV。"""
        return self.cache_store.save_daily_basic_by_symbol(df)

    def _trade_dates(self, start: str, end: str) -> list[str]:
        """获取交易日列表，失败时回退到自然工作日。"""
        try:
            cal = self._call_tushare_with_retry(
                "trade_cal",
                "trade_cal",
                lambda pro: pro.trade_cal(
                    exchange="SSE",
                    start_date=start,
                    end_date=end,
                    is_open="1",
                    fields="cal_date",
                ),
            )
            if cal is not None and not cal.empty and "cal_date" in cal.columns:
                return sorted(cal["cal_date"].dropna().astype(str).unique().tolist())
        except Exception as exc:
            click.echo(f"  获取交易日历失败，回退到工作日估算: {exc}", err=True)
        return [d.strftime("%Y%m%d") for d in pd.bdate_range(start=start, end=end)]

    def download_daily_basic(self, start: str, end: str, force: bool = False) -> dict[str, int]:
        """按交易日下载全市场每日指标，并拆分保存到 meta/daily_basic/{symbol}.csv。"""
        path = self._daily_basic_dir()
        existing_dates = set() if force else self._daily_basic_cached_dates()
        trade_dates = self._trade_dates(start, end)
        missing_dates = missing_daily_basic_dates(trade_dates, existing_dates, force)
        if not missing_dates:
            click.echo(f"  每日指标缓存已覆盖 {start} ~ {end}: {path}")
            return {"dates": 0, "rows": 0, "files": len(list(path.glob("*.csv")))}

        click.echo(f"  将下载 {len(missing_dates)}/{len(trade_dates)} 个交易日的 daily_basic。")
        saved_rows = 0
        for idx, trade_date in enumerate(missing_dates, start=1):
            raw = self._call_tushare_with_retry(
                trade_date,
                "daily_basic",
                lambda pro, d=trade_date: pro.daily_basic(
                    trade_date=d,
                    fields=self.DAILY_BASIC_FIELDS,
                ),
            )
            if raw is None or raw.empty:
                click.echo(f"  [{trade_date}] daily_basic 为空，跳过。")
                continue
            cleaned = self._clean_daily_basic(raw)
            saved_rows += self._save_daily_basic_by_symbol(cleaned)
            if idx % 20 == 0 or idx == len(missing_dates):
                click.echo(f"  进度: {idx}/{len(missing_dates)} 个交易日")
        return {"dates": len(missing_dates), "rows": saved_rows, "files": len(list(path.glob("*.csv")))}

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
            cache_ok = self._cache_covers_range(cached, start, end)
            if not self._is_index_symbol(symbol):
                cache_ok = cache_ok and self._stock_cache_matches_adjustment(cached)
            if cache_ok:
                return self._slice_cache(cached, start, end)

            if cached is not None and (
                self._is_index_symbol(symbol) or self._stock_cache_matches_adjustment(cached)
            ):
                try:
                    return self._download_incremental(symbol, cached, start, end)
                except Exception:
                    cached = self._load_cache(symbol)
                    cache_ok = self._cache_covers_range(cached, start, end)
                    if not self._is_index_symbol(symbol):
                        cache_ok = cache_ok and self._stock_cache_matches_adjustment(cached)
                    if cache_ok:
                        return self._slice_cache(cached, start, end)
                    raise

        try:
            df = self._fetch_from_api(symbol, start, end)
        except Exception:
            cached = self._load_cache(symbol)
            cache_ok = self._cache_covers_range(cached, start, end)
            if not self._is_index_symbol(symbol):
                cache_ok = cache_ok and self._stock_cache_matches_adjustment(cached)
            if cache_ok:
                return self._slice_cache(cached, start, end)
            raise

        return df

    def _download_incremental(
        self,
        symbol: str,
        cached: pd.DataFrame,
        start: str,
        end: str,
    ) -> pd.DataFrame:
        """只下载缓存缺失区间并合并回 CSV。

        前复权/后复权向前补历史会改变复权基准，直接全量刷新请求区间；
        向后追加时带上缓存最后一天做重叠校验，如发现复权基准变化也全量刷新。
        """
        requested_start = self._parse_yyyymmdd(start)
        requested_end = self._parse_yyyymmdd(end)
        cached_start = cached["date"].min()
        cached_end = cached["date"].max()
        fetched_parts: list[pd.DataFrame] = []

        if requested_start < cached_start:
            if not self._is_index_symbol(symbol) and self._adjusted_stock_cache():
                df = self._fetch_api_clean(symbol, start, end)
                self._save_cache(symbol, df)
                refreshed = self._load_cache(symbol)
                return self._slice_cache(refreshed, start, end)

            head_end = self._prev_day_str(cached_start)
            if self._parse_yyyymmdd(head_end) >= requested_start:
                fetched_parts.append(self._fetch_api_clean(symbol, start, head_end))

        if requested_end > cached_end:
            if not self._is_index_symbol(symbol) and self._adjusted_stock_cache():
                tail_start = self._date_str(cached_end)
            else:
                tail_start = self._next_day_str(cached_end)
            if self._parse_yyyymmdd(tail_start) <= requested_end:
                tail = self._fetch_api_clean(symbol, tail_start, end)
                if (
                    not self._is_index_symbol(symbol)
                    and self._adjusted_stock_cache()
                    and self._overlap_price_mismatch(cached, tail)
                ):
                    click.echo(f"  [{symbol}] 复权基准变化，自动刷新请求区间。")
                    df = self._fetch_api_clean(symbol, start, end)
                    self._save_cache(symbol, df)
                    refreshed = self._load_cache(symbol)
                    return self._slice_cache(refreshed, start, end)
                fetched_parts.append(tail)

        if fetched_parts:
            fetched = pd.concat(fetched_parts, ignore_index=True)
            self._save_cache(symbol, fetched)

        refreshed = self._load_cache(symbol)
        if self._cache_covers_range(refreshed, start, end):
            return self._slice_cache(refreshed, start, end)
        df = self._fetch_api_clean(symbol, start, end)
        self._save_cache(symbol, df)
        refreshed = self._load_cache(symbol)
        return self._slice_cache(refreshed, start, end)

    def download_index(
        self,
        symbol: str = "000001.SH",
        start: str = "20210101",
        end: Optional[str] = None,
        force: bool = False,
    ) -> pd.DataFrame:
        """下载指数日线；``.TI`` 使用 ``ths_daily``，其余使用 ``index_daily``。"""
        end = end or today_str()
        symbol = symbol.upper()
        if is_market_benchmark_symbol(symbol):
            if not force:
                cached = self.load_index_cache(symbol)
                if self._cache_covers_range(cached, start, end):
                    return self._slice_cache(cached, start, end)
            df = build_average_price_index_from_stock_cache(self.cache_dir)
            if df.empty:
                cached = self.load_index_cache(symbol)
                if self._cache_covers_range(cached, start, end):
                    return self._slice_cache(cached, start, end)
                raise ValueError(f"无本地股票缓存，无法生成指数数据: {MARKET_BENCHMARK_SYMBOL}")
            self._save_index_cache(symbol, df)
            refreshed = self.load_index_cache(symbol)
            return self._slice_cache(refreshed if refreshed is not None else df, start, end)
        if not force:
            cached = self.load_index_cache(symbol)
            if self._cache_covers_range(cached, start, end):
                return self._slice_cache(cached, start, end)

        try:
            df = self._fetch_index_from_api(symbol, start, end)
        except Exception:
            cached = self.load_index_cache(symbol)
            if self._cache_covers_range(cached, start, end):
                return self._slice_cache(cached, start, end)
            raise

        return df

    def load_index_intraday(self, symbol: str, freq: str = "5min") -> Optional[pd.DataFrame]:
        return self.cache_store.load_index_intraday(symbol, freq)

    def download_index_intraday(
        self,
        symbol: str,
        trade_date: str,
        freq: str = "5min",
        force: bool = False,
    ) -> pd.DataFrame:
        """下载单个交易日的指数分钟线并增量写入独立缓存。"""
        symbol = symbol.upper()
        normalized_freq = str(freq).lower()
        if normalized_freq not in {"1min", "5min", "15min", "30min", "60min"}:
            raise ValueError(f"不支持的分钟频率: {freq}")
        day = pd.to_datetime(str(trade_date), errors="raise").strftime("%Y-%m-%d")
        cached = None if force else self.load_index_intraday(symbol, normalized_freq)
        if cached is not None and not cached.empty:
            selected = cached[cached["trade_time"].dt.strftime("%Y-%m-%d") == day]
            if not selected.empty:
                return selected.reset_index(drop=True)

        start_time = f"{day} 09:00:00"
        end_time = f"{day} 16:00:00"
        raw = self.tushare_client.call_primary(
            symbol,
            "pro_bar_index_intraday",
            lambda pro: ts.pro_bar(
                ts_code=symbol,
                api=pro,
                asset="I",
                freq=normalized_freq,
                start_date=start_time,
                end_date=end_time,
                retry_count=1,
            ),
        )
        if raw is None or raw.empty:
            raise ValueError(f"无指数分钟数据: {symbol} {day} {normalized_freq}")
        df = raw.copy()
        if "trade_time" not in df.columns:
            raise ValueError(f"指数分钟数据缺少 trade_time: {symbol}")
        df["trade_time"] = pd.to_datetime(df["trade_time"], errors="coerce")
        for column in ("open", "high", "low", "close", "vol", "amount"):
            if column in df.columns:
                df[column] = pd.to_numeric(df[column], errors="coerce")
        df = df.dropna(subset=["trade_time", "open", "high", "low", "close"])
        self.cache_store.save_index_intraday(symbol, normalized_freq, df)
        return df.sort_values("trade_time").reset_index(drop=True)

    def download_ths_index_list(self, exchange: str | None = None, force: bool = False) -> pd.DataFrame:
        """下载并缓存同花顺指数列表。"""
        path = self._ths_index_list_path()
        if path.exists() and not force:
            return pd.read_csv(path, dtype={"ts_code": str})
        kwargs = {}
        if exchange:
            kwargs["exchange"] = str(exchange).upper()
        raw = self.tushare_client.call_primary(
            "THS_INDEX_LIST",
            "ths_index",
            lambda pro: pro.ths_index(**kwargs),
        )
        if raw is None or raw.empty:
            raise ValueError("无同花顺指数列表数据")
        df = raw.copy()
        if "ts_code" in df.columns:
            df["ts_code"] = df["ts_code"].astype(str).str.upper()
        path.parent.mkdir(parents=True, exist_ok=True)
        df.drop_duplicates("ts_code", keep="last").sort_values("ts_code").to_csv(path, index=False)
        return pd.read_csv(path, dtype={"ts_code": str})

    def load_ths_index_list(self) -> Optional[pd.DataFrame]:
        path = self._ths_index_list_path()
        if not path.exists():
            return None
        return pd.read_csv(path, dtype={"ts_code": str})

    def download_ths_indexes(
        self,
        symbols: list[str],
        start: str,
        end: Optional[str] = None,
        force: bool = False,
    ) -> list[tuple[str, pd.DataFrame]]:
        """批量下载同花顺指数日线，只更新缓存，不生成报告。"""
        end = end or today_str()
        results: list[tuple[str, pd.DataFrame]] = []
        seen: set[str] = set()
        for raw_symbol in symbols:
            symbol = str(raw_symbol).upper()
            if not symbol.endswith(".TI") or symbol in seen:
                continue
            seen.add(symbol)
            df = self.download_index(symbol=symbol, start=start, end=end, force=force)
            results.append((symbol, df))
        return results

    def _fetch_index_from_api(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        """按指数来源调用 Tushare 行情接口并写入统一指数缓存。"""
        if symbol.endswith(".TI"):
            return self._fetch_ths_index_from_api(symbol, start, end)

        raw = self._call_tushare_with_retry(
            symbol,
            "index_daily",
            lambda pro: pro.index_daily(
                ts_code=symbol,
                start_date=start,
                end_date=end,
                fields="ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
            ),
        )

        if raw is None or raw.empty:
            raise ValueError(f"无指数数据: {symbol}")

        df = self._clean_index(raw)
        self._save_index_cache(symbol, df)
        return df

    def _fetch_ths_index_from_api(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        """调用 ``ths_daily``；按八年分段，避免超过单次 3000 行限制。"""
        cursor = self._parse_yyyymmdd(start)
        end_date = self._parse_yyyymmdd(end)
        chunks: list[pd.DataFrame] = []
        while cursor <= end_date:
            chunk_end = min(cursor + pd.DateOffset(years=8) - pd.Timedelta(days=1), end_date)
            raw = self.tushare_client.call_primary(
                symbol,
                "ths_daily",
                lambda pro, chunk_start=self._date_str(cursor), chunk_stop=self._date_str(chunk_end): pro.ths_daily(
                    ts_code=symbol,
                    start_date=chunk_start,
                    end_date=chunk_stop,
                    fields=(
                        "ts_code,trade_date,open,high,low,close,pre_close,change,pct_change,"
                        "vol,amount,turnover_rate,total_mv,float_mv"
                    ),
                ),
            )
            if raw is not None and not raw.empty:
                chunks.append(raw)
            cursor = chunk_end + pd.Timedelta(days=1)

        if not chunks:
            raise ValueError(f"无同花顺指数数据: {symbol}")

        df = clean_ths_index_daily(pd.concat(chunks, ignore_index=True))
        self._save_index_cache(symbol, df)
        return df

    def _fetch_from_api(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        """通过限流器调用 Tushare API 并清洗存入缓存"""
        df = self._fetch_api_clean(symbol, start, end)
        self._save_cache(symbol, df)
        return df

    def _fetch_api_clean(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        """调用 Tushare API 并清洗为本地标准列，不直接写缓存。"""
        if self._is_index_symbol(symbol):
            raw = self._call_tushare_with_retry(
                symbol,
                "index_daily",
                lambda pro: pro.index_daily(
                    ts_code=symbol,
                    start_date=start,
                    end_date=end,
                    fields="trade_date,open,high,low,close,vol,amount",
                ),
            )
        else:
            raw = self._fetch_stock_daily_from_api(symbol, start, end)

        if raw is None or raw.empty:
            raise ValueError(f"无数据: {symbol}")

        df = self._clean(raw, adj=None if self._is_index_symbol(symbol) else self.stock_adj)
        return df

    def _fetch_stock_daily_from_api(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        """下载股票日线。

        Tushare 的 `pro_bar(adj="qfq")` 内部会连续调用 `daily` 和
        `adj_factor`，项目级限流器无法感知第二次调用。这里显式拆开，
        让每个真实接口请求都经过 `_call_tushare_with_retry()`。
        """
        raw = self._call_tushare_with_retry(
            symbol,
            "daily",
            lambda pro: pro.daily(
                ts_code=symbol,
                start_date=start,
                end_date=end,
                fields="trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
            ),
        )
        adj = self.stock_adj
        if not is_adjusted_mode(adj):
            return raw

        factors = self._call_tushare_with_retry(
            symbol,
            "adj_factor",
            lambda pro: pro.adj_factor(
                ts_code=symbol,
                start_date=start,
                end_date=end,
                fields="trade_date,adj_factor",
            ),
        )
        return apply_price_adjustment(raw, factors, adj)

    def _estimated_api_calls_per_symbol(self, symbol: str) -> int:
        if self._is_index_symbol(symbol):
            return 1
        adj = self.stock_adj
        if adj is None or str(adj).lower() in {"", "none", "raw"}:
            return 1
        return 2

    def _estimated_api_calls_for_request(
        self,
        symbol: str,
        cached: Optional[pd.DataFrame],
        start: str,
        end: str,
        force: bool,
    ) -> int:
        if force or cached is None or cached.empty:
            return self._estimated_api_calls_per_symbol(symbol)
        cache_ok = self._cache_covers_range(cached, start, end)
        if not self._is_index_symbol(symbol):
            cache_ok = cache_ok and self._stock_cache_matches_adjustment(cached)
        if cache_ok:
            return 0
        if not self._is_index_symbol(symbol) and not self._stock_cache_matches_adjustment(cached):
            return self._estimated_api_calls_per_symbol(symbol)

        requested_start = self._parse_yyyymmdd(start)
        requested_end = self._parse_yyyymmdd(end)
        cached_start = cached["date"].min()
        cached_end = cached["date"].max()
        ranges = 0
        if requested_start < cached_start:
            ranges += 1
            if not self._is_index_symbol(symbol) and self._adjusted_stock_cache():
                return self._estimated_api_calls_per_symbol(symbol)
        if requested_end > cached_end:
            ranges += 1
        return ranges * self._estimated_api_calls_per_symbol(symbol)

    @staticmethod
    def _is_retryable_download_error(error_text: str) -> bool:
        return is_retryable_download_error(error_text)

    def _call_tushare_with_retry(self, symbol: str, api_name: str, call: Callable[[object], pd.DataFrame]):
        """统一的 Tushare 调用入口，限流后执行，频率超限时退避重试。"""
        return self.tushare_client.call(symbol, api_name, call)

    def download_batch(
        self,
        symbols: list[str],
        start: str,
        end: str,
        force: bool = False,
    ) -> dict[str, pd.DataFrame]:
        """并行批量下载，带限流和进度预估"""
        results: dict[str, pd.DataFrame] = {}
        failed: dict[str, str] = {}
        self._cancel_event.clear()
        self.last_failed_symbols = []
        self.last_failed_errors = {}
        self.last_failed_file = None
        self.failed_record_files = []
        self._download_run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        total = len(symbols)
        workers = max(1, self._max_workers)
        rpm = self.tushare_client.effective_calls_per_minute

        datewise_symbols, regular_symbols = self._datewise_stock_update_groups(
            symbols,
            start,
            end,
            force,
        )
        if datewise_symbols:
            use_incremental = click.confirm(
                "  检测到可以按交易日增量下载K线，是否使用增量下载? "
                "选择 n 将重新全量下载。",
                default=True,
            )
            if not use_incremental:
                click.echo("  已选择重新全量下载。")
                force = True
            else:
                if regular_symbols:
                    click.echo(
                        f"  已选择按交易日增量下载: {len(datewise_symbols)} 只；"
                        f"其余 {len(regular_symbols)} 只新增/缓存不匹配股票走逐标的下载。"
                    )
                else:
                    click.echo("  已选择按交易日增量下载。")
                try:
                    results.update(self.download_stock_kline_by_date(datewise_symbols, start, end))
                    if not regular_symbols:
                        return results
                    symbols = regular_symbols
                    total = len(symbols)
                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    click.echo(
                        f"  按交易日增量K线失败，回退到逐股票下载: {exc}",
                        err=True,
                    )

        # ---- 预估时间 ----
        cached_by_symbol = {
            sym: None if force else self._load_cache(sym)
            for sym in symbols
        }
        plan = estimate_download_plan(
            symbols=symbols,
            cached_by_symbol=cached_by_symbol,
            start=start,
            end=end,
            force=force,
            effective_rpm=rpm,
            cache_covers_range=self._cache_covers_range,
            is_index_symbol=self._is_index_symbol,
            stock_cache_matches_adjustment=self._stock_cache_matches_adjustment,
            estimate_api_calls_for_request=self._estimated_api_calls_for_request,
        )
        for message in format_download_plan_messages(plan, workers):
            click.echo(message)

        # ---- 并行下载 ----
        start_ts = time.monotonic()
        completed = 0
        lock = threading.Lock()

        def _download_symbols(batch_symbols: list[str], label: str = "") -> None:
            nonlocal completed
            progress_callback = None
            if not label:
                def progress_callback(_symbol: str) -> None:
                    nonlocal completed
                    with lock:
                        completed += 1
                        current = completed
                    if current % 50 == 0 or current == total:
                        elapsed = time.monotonic() - start_ts
                        click.echo(f"  进度: {current}/{total}  已耗时: {elapsed:.0f}s")

            download_symbols_parallel(
                batch_symbols,
                download_one=lambda sym: self.download(sym, start, end, force),
                results=results,
                failed=failed,
                workers=workers,
                cancel_event=self._cancel_event,
                label=label,
                on_item_done=progress_callback,
            )

        try:
            _download_symbols(symbols)
            initial_failed_file = self._write_failure_snapshot(
                failed, start, end, "initial"
            )
            if initial_failed_file is not None:
                click.echo(f"  第一轮失败记录: {initial_failed_file}")

            for round_no in range(1, max(0, self._failed_retry_rounds) + 1):
                symbols_to_retry = retry_symbols(failed, self._is_retryable_download_error)
                if not symbols_to_retry:
                    break
                wait_seconds = self._failed_retry_wait_seconds * round_no
                click.echo(
                    f"  自动补下载第 {round_no}/{self._failed_retry_rounds} 轮: "
                    f"{len(symbols_to_retry)} 只，等待 {wait_seconds:.0f}s ..."
                )
                self.tushare_client.cooldown_all(wait_seconds)
                self.tushare_client.wait_once()
                _download_symbols(symbols_to_retry, label=f"补下载{round_no}")
                retry_failed_file = self._write_failure_snapshot(
                    failed, start, end, f"retry{round_no}"
                )
                if retry_failed_file is not None:
                    click.echo(f"  补下载第 {round_no} 轮剩余失败记录: {retry_failed_file}")
        except KeyboardInterrupt:
            self._cancel_event.set()
            cancel_file = self._write_failure_snapshot(failed, start, end, "cancelled")
            if cancel_file is not None:
                click.echo(f"  已记录取消前失败股票: {cancel_file}")
            click.echo("  下载任务已取消，后台线程正在退出。")
            raise

        elapsed = time.monotonic() - start_ts
        click.echo(f"  下载完成，总耗时: {elapsed:.0f} 秒 ({elapsed/60:.1f} 分钟)")
        self.last_failed_symbols = sorted(failed)
        self.last_failed_errors = {sym: failed[sym] for sym in self.last_failed_symbols}
        if self.last_failed_symbols:
            final_failed_file = self._write_failure_snapshot(failed, start, end, "final")
            commands = build_retry_commands(self.last_failed_symbols, start, end, final_failed_file)
            click.echo()
            click.secho(f"  下载失败股票 ({len(self.last_failed_symbols)} 只):", fg="yellow")
            click.echo(f"  {commands.symbols_csv}")
            click.echo(f"  失败记录 CSV: {final_failed_file}")
            click.echo("  可执行以下增量补下载命令：")
            click.echo(f"  {commands.cli_symbol_command}")
            click.echo(f"  {commands.cli_failed_file_command}")
            click.echo("  REPL 中可执行：")
            click.echo(f"  {commands.repl_symbol_command}")
            click.echo(f"  {commands.repl_failed_file_command}")
        elif self.failed_record_files:
            click.echo()
            click.echo("  第一轮失败股票已在自动补下载中全部补齐。")
            click.echo("  失败过程记录:")
            for path in self.failed_record_files:
                click.echo(f"  {path}")
        return results

    def _clean(self, raw: pd.DataFrame, adj: Optional[str] = None) -> pd.DataFrame:
        """清洗为标准格式"""
        return clean_stock_daily(raw, adj=adj)

    def _clean_daily_basic(self, raw: pd.DataFrame) -> pd.DataFrame:
        """清洗每日指标数据，保留 Tushare daily_basic 原字段名。"""
        return clean_daily_basic(raw, self.DAILY_BASIC_FIELDS)

    def _clean_index(self, raw: pd.DataFrame) -> pd.DataFrame:
        """清洗指数日线，保留涨跌幅字段供概览分析使用。"""
        return clean_index_daily(raw)
