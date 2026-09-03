"""Shared CLI helpers used by Click commands and the interactive shell."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from project_config import PROJECT_ROOT, load_project_config


def load_config() -> dict:
    return load_project_config()


def list_strategies() -> list[str]:
    strategy_dir = PROJECT_ROOT / "strategy"
    return sorted(
        path.stem
        for path in strategy_dir.glob("*.py")
        if path.stem not in {"base", "__init__"}
    )


def list_cached_symbols(config: dict) -> list[str]:
    cache_dir = Path(config["data"]["cache_dir"])
    if not cache_dir.exists():
        return []
    return sorted(
        path.stem
        for path in cache_dir.glob("*.csv")
        if not path.name.startswith("_")
    )


def load_cache_df(symbol: str, config: dict) -> pd.DataFrame:
    cache_path = Path(config["data"]["cache_dir"]) / f"{symbol}.csv"
    if not cache_path.exists():
        raise FileNotFoundError(f"缓存数据不存在: {cache_path}，请先执行 data download")
    df = pd.read_csv(cache_path, dtype={"date": str})
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def split_trade_log_name(name: str) -> Optional[tuple[str, str]]:
    for strategy_name in sorted(list_strategies(), key=len, reverse=True):
        suffix = f"_{strategy_name}"
        if name.endswith(suffix):
            symbol = name[:-len(suffix)]
            if symbol:
                return symbol, strategy_name
    return None


def find_trade_logs(
    trades_dir: Path,
    symbol: Optional[str] = None,
    strategy: Optional[str] = None,
) -> list[tuple[str, str, Path]]:
    if not trades_dir.exists():
        return []

    results: list[tuple[str, str, Path]] = []
    for path in trades_dir.glob("*.csv"):
        name = path.stem
        if name.startswith("_") or name.endswith("_equity"):
            continue
        split = split_trade_log_name(name)
        if split is None:
            continue
        candidate_symbol, candidate_strategy = split
        if symbol is not None and candidate_symbol != symbol:
            continue
        if strategy is not None and candidate_strategy != strategy:
            continue
        results.append((candidate_symbol, candidate_strategy, path))
    return results
