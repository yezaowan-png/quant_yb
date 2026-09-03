#!/usr/bin/env python3
"""Verify daily market-data freshness for indexes and 同花顺板块行情."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cli.common import load_config  # noqa: E402
from cli.index_cli import (  # noqa: E402
    _configured_indexes,
    _select_ths_concept_symbols,
    _select_ths_industry_symbols,
    _ths_config,
    _ths_index_names,
)
from data.downloader import DataDownloader  # noqa: E402


def _latest_date_from_frame(frame: pd.DataFrame | None) -> pd.Timestamp | None:
    if frame is None or frame.empty:
        return None
    date_column = "date" if "date" in frame.columns else "trade_date" if "trade_date" in frame.columns else None
    if date_column is None:
        return None
    dates = pd.to_datetime(frame[date_column], errors="coerce").dropna()
    return None if dates.empty else dates.max().normalize()


def _load_latest_date(path: Path) -> pd.Timestamp | None:
    if not path.exists():
        return None
    try:
        frame = pd.read_csv(path, dtype={"date": str, "trade_date": str}, usecols=lambda col: col in {"date", "trade_date"})
    except Exception:
        return None
    return _latest_date_from_frame(frame)


def _fmt_date(value: pd.Timestamp | None) -> str:
    return "--" if value is None else value.strftime("%Y-%m-%d")


def _lag_days(latest: pd.Timestamp | None, reference: pd.Timestamp | None) -> int | None:
    if latest is None or reference is None:
        return None
    return int((reference - latest).days)


def _section_summary(
    *,
    label: str,
    symbols: list[str],
    names: dict[str, str],
    cache_dir: Path,
    reference_date: pd.Timestamp | None,
    max_lag_days: int,
    stale_preview: int,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        latest = _load_latest_date(cache_dir / f"{symbol}.csv")
        lag = _lag_days(latest, reference_date)
        rows.append(
            {
                "symbol": symbol,
                "name": names.get(symbol, symbol),
                "latest": latest,
                "lag_days": lag,
                "missing": latest is None,
                "stale": lag is None or lag > max_lag_days,
            }
        )
    available = [row for row in rows if row["latest"] is not None]
    latest = max((row["latest"] for row in available), default=None)
    stale = [row for row in rows if row["stale"]]
    print(
        f"{label}: 选中 {len(symbols)} 个，已缓存 {len(available)} 个，"
        f"最新 {_fmt_date(latest)}，阈值 {max_lag_days} 天，落后/缺失 {len(stale)} 个"
    )
    for row in stale[:stale_preview]:
        suffix = "缺失" if row["missing"] else f"最新 {_fmt_date(row['latest'])}，落后 {row['lag_days']} 天"
        print(f"  - {row['symbol']} {row['name']}: {suffix}")
    if len(stale) > stale_preview:
        print(f"  ... 另有 {len(stale) - stale_preview} 个落后/缺失")
    return {
        "label": label,
        "selected": len(symbols),
        "available": len(available),
        "latest": latest,
        "stale_count": len(stale),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="检查每日行业/概念/指数行情缓存是否新鲜")
    parser.add_argument("--max-lag-calendar-days", type=int, default=None, help="允许相对参考指数落后的最大自然日")
    parser.add_argument("--stale-preview", type=int, default=12, help="每类最多打印多少个落后标的")
    parser.add_argument("--strict", action="store_true", help="发现指数整体缺失或板块最新日期超阈值时返回非 0")
    args = parser.parse_args()

    config = load_config()
    dl = DataDownloader(config)
    cache_dir = Path(config.get("data", {}).get("cache_dir", "data/cache")) / "index"
    meta_dir = Path(config.get("data", {}).get("meta_dir", "data/meta"))

    index_rows: list[dict[str, Any]] = []
    for item in _configured_indexes(config):
        symbol = str(item.get("symbol") or "").upper()
        if not symbol:
            continue
        latest = _latest_date_from_frame(dl.load_index_cache(symbol))
        index_rows.append({"symbol": symbol, "name": item.get("name") or symbol, "latest": latest})
    reference_date = max((row["latest"] for row in index_rows if row["latest"] is not None), default=None)
    print(f"指数行情: 配置 {len(index_rows)} 个，参考最新 {_fmt_date(reference_date)}")
    for row in index_rows:
        print(f"  - {row['symbol']} {row['name']}: {_fmt_date(row['latest'])}")

    ths_list_path = meta_dir / "ths_indices.csv"
    if not ths_list_path.exists():
        print(f"同花顺指数列表缺失: {ths_list_path}")
        return 1 if args.strict else 0

    ths_list = pd.read_csv(ths_list_path, dtype={"ts_code": str})
    names = _ths_index_names(ths_list)
    ths_cfg = _ths_config(config)
    default_lag = args.max_lag_calendar_days
    if default_lag is None:
        default_lag = int(ths_cfg.get("max_stale_calendar_days", 4) or 4)

    industry_summary = _section_summary(
        label="同花顺行业行情",
        symbols=_select_ths_industry_symbols(ths_list, config),
        names=names,
        cache_dir=cache_dir,
        reference_date=reference_date,
        max_lag_days=default_lag,
        stale_preview=args.stale_preview,
    )
    concept_summary = _section_summary(
        label="同花顺概念行情",
        symbols=_select_ths_concept_symbols(ths_list, config),
        names=names,
        cache_dir=cache_dir,
        reference_date=reference_date,
        max_lag_days=default_lag,
        stale_preview=args.stale_preview,
    )

    if not args.strict:
        return 0
    if reference_date is None:
        return 1
    for summary in (industry_summary, concept_summary):
        latest = summary["latest"]
        if latest is None or _lag_days(latest, reference_date) is None or _lag_days(latest, reference_date) > default_lag:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
