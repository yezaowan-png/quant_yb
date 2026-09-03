"""Read-only local data adapters owned by the independent market risk gate."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd


def load_risk_stock_close_matrix(
    cache_dir: str | Path,
    dates: Iterable[Any] | None = None,
) -> pd.DataFrame:
    root = Path(cache_dir)
    if not root.exists():
        return pd.DataFrame()
    series: list[pd.Series] = []
    for path in sorted(root.glob("*.csv")):
        if path.name.startswith("_"):
            continue
        try:
            frame = pd.read_csv(path, usecols=["date", "close"], dtype={"date": str})
        except (OSError, ValueError, pd.errors.ParserError):
            continue
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame = frame.dropna(subset=["date", "close"]).drop_duplicates("date", keep="last")
        if not frame.empty:
            series.append(frame.set_index("date")["close"].rename(path.stem.upper()))
    if not series:
        return pd.DataFrame()
    matrix = pd.concat(series, axis=1).sort_index()
    if dates is not None:
        index = pd.DatetimeIndex(pd.to_datetime(list(dates), errors="coerce")).dropna().unique().sort_values()
        matrix = matrix.reindex(index)
    return matrix


def load_risk_strategy_daily_returns(trades_dir: str | Path) -> dict[str, pd.Series]:
    root = Path(trades_dir)
    grouped: dict[str, list[pd.Series]] = {}
    if not root.exists():
        return {}
    for path in sorted(root.glob("*_equity.csv")):
        stem = path.stem.removesuffix("_equity")
        if "_" not in stem or stem.startswith("_"):
            continue
        _, strategy = stem.split("_", 1)
        try:
            frame = pd.read_csv(path)
        except (OSError, ValueError, pd.errors.ParserError):
            continue
        date_column = "dates" if "dates" in frame else "date" if "date" in frame else None
        if date_column is None or "equity" not in frame:
            continue
        dates = pd.to_datetime(frame[date_column], errors="coerce")
        equity = pd.to_numeric(frame["equity"], errors="coerce")
        daily = pd.Series(equity.to_numpy(), index=dates).dropna().sort_index().pct_change(fill_method=None)
        if daily.notna().any():
            grouped.setdefault(strategy, []).append(daily.rename(path.name))
    return {
        strategy: pd.concat(items, axis=1).mean(axis=1, skipna=True)
        for strategy, items in grouped.items()
        if items
    }


def load_risk_strategy_trade_events(trades_dir: str | Path) -> dict[str, pd.DataFrame]:
    """Load actual BUY events and attach the subsequent exported realized return."""
    root = Path(trades_dir)
    grouped: dict[str, list[dict[str, Any]]] = {}
    if not root.exists():
        return {}
    for path in sorted(root.glob("*.csv")):
        if path.name.endswith("_equity.csv") or path.name.startswith("_"):
            continue
        stem = path.stem
        if "_" not in stem:
            continue
        _, strategy = stem.split("_", 1)
        try:
            frame = pd.read_csv(path)
        except (OSError, ValueError, pd.errors.ParserError):
            continue
        required = {"date", "direction", "price", "size", "pnl"}
        if not required.issubset(frame.columns):
            continue
        open_buys: list[dict[str, Any]] = []
        for _, row in frame.iterrows():
            direction = str(row.get("direction", "")).upper()
            if direction == "BUY":
                price = float(pd.to_numeric(row.get("price"), errors="coerce"))
                size = abs(float(pd.to_numeric(row.get("size"), errors="coerce")))
                if pd.notna(price) and pd.notna(size) and price > 0 and size > 0:
                    open_buys.append({
                        "trade_date": str(row.get("date"))[:10],
                        "symbol": str(row.get("symbol", path.stem.split("_", 1)[0])),
                        "notional": price * size,
                        "realized_return": None,
                    })
            elif direction == "SELL" and open_buys:
                pnl = float(pd.to_numeric(row.get("pnl"), errors="coerce"))
                total_notional = sum(item["notional"] for item in open_buys)
                realized = pnl / total_notional if pd.notna(pnl) and total_notional > 0 else None
                for item in open_buys:
                    item["realized_return"] = realized
                    grouped.setdefault(strategy, []).append(item)
                open_buys = []
        for item in open_buys:
            grouped.setdefault(strategy, []).append(item)
    return {
        strategy: pd.DataFrame(rows).sort_values("trade_date").reset_index(drop=True)
        for strategy, rows in grouped.items()
        if rows
    }
