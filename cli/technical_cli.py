"""Generic technical-structure CLI; it never generates a business HTML page."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import click
import pandas as pd

from analysis.technical_structure import TechnicalStructureService
from cli.common import load_config


@click.group(name="technical")
def technical_group():
    """通用技术结构识别。"""


def _cache_path(config: dict, symbol: str, asset_type: str) -> Path:
    root = Path(config["data"]["cache_dir"])
    return root / "index" / f"{symbol}.csv" if asset_type == "index" else root / f"{symbol}.csv"


@technical_group.command(name="structure")
@click.option("--symbol", required=True, help="标的代码，如 600519.SH 或 000001.SH")
@click.option("--asset-type", type=click.Choice(["index", "stock", "fund", "other"]), default="stock", show_default=True)
@click.option("--timeframe", type=click.Choice(["1d", "1w", "1mo"]), default=None, help="单周期")
@click.option("--timeframes", default=None, help="多周期，逗号分隔，如 1d,1w,1mo")
@click.option("--adjustment", type=click.Choice(["qfq", "hfq", "none"]), default=None)
@click.option("--as-of", "as_of_date", default=None, help="历史回放截止日 YYYYMMDD")
@click.option("--lookback", "lookback_bars", type=int, default=None, help="最多分析最近N根目标周期K线")
@click.option("--cache/--no-cache", "use_cache", default=True, show_default=True)
def technical_structure(
    symbol: str,
    asset_type: str,
    timeframe: Optional[str],
    timeframes: Optional[str],
    adjustment: Optional[str],
    as_of_date: Optional[str],
    lookback_bars: Optional[int],
    use_cache: bool,
):
    """分析标准OHLCV并打印结构摘要和缓存位置，不创建独立HTML。"""
    config = load_config()
    symbol = symbol.strip().upper()
    path = _cache_path(config, symbol, asset_type)
    if not path.exists():
        raise click.ClickException(f"行情缓存不存在: {path}")
    frame = pd.read_csv(path, dtype={"date": str, "trade_date": str})
    selected = [item.strip() for item in (timeframes or timeframe or "1d").split(",") if item.strip()]
    invalid = sorted(set(selected) - {"1d", "1w", "1mo"})
    if invalid:
        raise click.ClickException(f"不支持的周期: {', '.join(invalid)}")
    technical_config = {
        **(config.get("technical_structure", {}) or {}),
        "cache_dir": str(Path(config.get("output", {}).get("statistics_dir", "output/statistics"))),
    }
    technical_config.setdefault("defaults", {})["cache_enabled"] = bool(use_cache)
    chosen_adjustment = "none" if asset_type == "index" else str(adjustment or config.get("data", {}).get("stock_adj") or "none")
    service = TechnicalStructureService(technical_config, cache_dir=technical_config["cache_dir"])
    results = service.analyze_multi_timeframe(
        symbol=symbol,
        asset_type=asset_type,
        timeframes=selected,
        ohlcv=frame,
        as_of_date=as_of_date,
        lookback_bars=lookback_bars,
        adjustment=chosen_adjustment,
    )
    summary = {
        "symbol": symbol,
        "asset_type": asset_type,
        "adjustment": "none" if asset_type == "index" else chosen_adjustment,
        "source": str(path),
        "results": {
            key: {
                "as_of_date": result.as_of_date,
                "bar_count": result.bar_count,
                "pivot_count": len(result.pivots),
                "horizontal_level_count": len(result.horizontal_levels),
                "trendline_count": len(result.trendlines),
                "channel_count": len(result.channels),
                "current_context": result.current_context,
                "data_quality_flags": result.data_quality_flags,
                "cache_path": result.cache_path,
                "algorithm_version": result.algorithm_version,
            }
            for key, result in results.items()
        },
    }
    click.echo(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))
