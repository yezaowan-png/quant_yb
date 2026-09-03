"""Pure helpers for batch download estimation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Optional

import pandas as pd


@dataclass(frozen=True)
class DownloadPlanEstimate:
    total: int
    cached_count: int
    need_api: int
    api_calls: int
    effective_rpm: int
    estimated_seconds: float

    @property
    def estimated_minutes(self) -> float:
        return self.estimated_seconds / 60.0


def estimate_download_plan(
    symbols: list[str],
    cached_by_symbol: Mapping[str, Optional[pd.DataFrame]],
    start: str,
    end: str,
    force: bool,
    effective_rpm: int,
    cache_covers_range: Callable[[Optional[pd.DataFrame], str, str], bool],
    is_index_symbol: Callable[[str], bool],
    stock_cache_matches_adjustment: Callable[[Optional[pd.DataFrame]], bool],
    estimate_api_calls_for_request: Callable[[str, Optional[pd.DataFrame], str, str, bool], int],
) -> DownloadPlanEstimate:
    """Estimate cache hits, API calls, and elapsed time for a batch download."""
    total = len(symbols)
    cached_count = 0
    if not force:
        for symbol in symbols:
            cached = cached_by_symbol.get(symbol)
            cache_ok = cache_covers_range(cached, start, end)
            if not is_index_symbol(symbol):
                cache_ok = cache_ok and stock_cache_matches_adjustment(cached)
            if cache_ok:
                cached_count += 1

    api_calls = 0
    for symbol in symbols:
        cached = None if force else cached_by_symbol.get(symbol)
        api_calls += estimate_api_calls_for_request(symbol, cached, start, end, force)

    need_api = total - cached_count
    rpm = max(1, int(effective_rpm or 1))
    estimated_seconds = api_calls * 60.0 / rpm
    return DownloadPlanEstimate(
        total=total,
        cached_count=cached_count,
        need_api=need_api,
        api_calls=api_calls,
        effective_rpm=rpm,
        estimated_seconds=estimated_seconds,
    )
