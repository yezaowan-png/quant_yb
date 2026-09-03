"""Small orchestration helpers for data download workflows."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import click
import pandas as pd

from data.download_planner import DownloadPlanEstimate


@dataclass(frozen=True)
class DownloadSymbolSelection:
    symbols: list[str]
    source: str
    source_detail: str | None = None
    requires_confirm: bool = False


def normalize_symbol_csv(symbol: str | None) -> list[str]:
    """Normalize a comma-separated symbol string into uppercase ts_codes."""
    if not symbol:
        return []
    return [item.strip().upper() for item in symbol.split(",") if item.strip()]


def resolve_download_symbols(
    symbol: str | None = None,
    failed_file: str | Path | None = None,
    *,
    load_symbols_from_file: Callable[[str | Path], list[str]],
    get_stock_list: Callable[[], Sequence[dict]],
) -> DownloadSymbolSelection:
    """Resolve download symbols from failed file, explicit symbol, or all stocks."""
    if failed_file:
        symbols = load_symbols_from_file(failed_file)
        return DownloadSymbolSelection(
            symbols=symbols,
            source="failed_file",
            source_detail=str(failed_file),
            requires_confirm=False,
        )

    symbols = normalize_symbol_csv(symbol)
    if symbols:
        return DownloadSymbolSelection(
            symbols=symbols,
            source="symbol",
            source_detail=symbol,
            requires_confirm=False,
        )

    stocks = list(get_stock_list())
    symbols = [str(item["ts_code"]).upper() for item in stocks if item.get("ts_code")]
    return DownloadSymbolSelection(
        symbols=symbols,
        source="all_stocks",
        source_detail=None,
        requires_confirm=True,
    )


def format_download_plan_messages(plan: DownloadPlanEstimate, workers: int) -> list[str]:
    """Format user-facing batch download estimate messages."""
    if plan.need_api <= 0:
        return [f"  共 {plan.total} 只 | 全部已缓存，直接从本地读取"]

    messages = [
        (
            f"  共 {plan.total} 只 | 缓存命中 {plan.cached_count} 只 | "
            f"需下载 {plan.need_api} 只 | 预计接口 {plan.api_calls} 次"
        ),
        f"  并行线程: {workers} | 有效API限速: {plan.effective_rpm}次/分钟",
    ]
    if plan.estimated_minutes >= 1:
        messages.append(
            f"  ⏱ 预计约需 {plan.estimated_minutes:.0f} 分钟 "
            f"{plan.estimated_seconds:.0f} 秒"
        )
    else:
        messages.append(f"  ⏱ 预计约需 {plan.estimated_seconds:.0f} 秒")
    return messages


def download_symbols_parallel(
    symbols: list[str],
    *,
    download_one: Callable[[str], pd.DataFrame],
    results: dict[str, pd.DataFrame],
    failed: dict[str, str],
    workers: int,
    cancel_event,
    label: str = "",
    on_item_done: Callable[[str], None] | None = None,
) -> None:
    """Download one batch of symbols concurrently and update shared result maps."""
    prefix = f"{label} " if label else ""
    executor = ThreadPoolExecutor(max_workers=workers)
    futures = {}
    try:
        futures = {executor.submit(download_one, sym): sym for sym in symbols}
        for future in as_completed(futures):
            sym = futures[future]
            try:
                results[sym] = future.result()
                failed.pop(sym, None)
            except Exception as exc:
                failed[sym] = str(exc)
                click.echo(f"  {prefix}[{sym}] 下载失败: {exc}", err=True)
            if on_item_done is not None:
                on_item_done(sym)
    except KeyboardInterrupt:
        cancel_event.set()
        for future in futures:
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    finally:
        if not cancel_event.is_set():
            executor.shutdown(wait=True)
