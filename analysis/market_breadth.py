"""Market breadth helpers built from local stock K-line caches."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def _parse_date_bound(value: str | None) -> pd.Timestamp | None:
    if not value:
        return None
    return pd.to_datetime(str(value), format="%Y%m%d", errors="coerce")


def build_market_breadth(
    cache_dir: str | Path,
    start: str | None = None,
    end: str | None = None,
    nhnl_lookback: int = 252,
    symbols: set[str] | list[str] | None = None,
) -> dict[str, dict[str, int]]:
    """Count daily market breadth metrics from local stock cache CSVs.

    Dates are returned as ``YYYY-MM-DD`` so they can be aligned directly with
    report payloads. Index files under ``cache_dir/index`` are ignored.

    ``new_high`` and ``new_low`` use a 252-trading-day default window to
    approximate one-year highs/lows. Stocks with insufficient history for the
    window are ignored for NH-NL so newly listed names do not dominate the
    signal.
    """
    root = Path(cache_dir)
    if not root.exists():
        return {}

    start_ts = _parse_date_bound(start)
    end_ts = _parse_date_bound(end)
    symbol_filter = {str(symbol).upper() for symbol in symbols} if symbols else None
    counts: dict[str, dict[str, int]] = {}

    for path in root.glob("*.csv"):
        if path.name.startswith("_"):
            continue
        symbol = path.stem.upper()
        if symbol_filter is not None and symbol not in symbol_filter:
            continue
        try:
            df = pd.read_csv(path, usecols=["date", "close"], dtype={"date": str})
        except Exception:
            continue
        if df.empty:
            continue

        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.dropna(subset=["date", "close"]).sort_values("date")
        if len(df) < 2:
            continue

        df["prev_close"] = df["close"].shift(1)
        if nhnl_lookback > 1:
            rolling_close = df["close"]
            df["rolling_high"] = rolling_close.rolling(nhnl_lookback, min_periods=nhnl_lookback).max()
            df["rolling_low"] = rolling_close.rolling(nhnl_lookback, min_periods=nhnl_lookback).min()
            df["new_high_signal"] = df["close"] >= df["rolling_high"] - 1e-9
            df["new_low_signal"] = df["close"] <= df["rolling_low"] + 1e-9
        else:
            df["new_high_signal"] = False
            df["new_low_signal"] = False
        df = df.dropna(subset=["prev_close"])
        if start_ts is not None:
            df = df[df["date"] >= start_ts]
        if end_ts is not None:
            df = df[df["date"] <= end_ts]
        if df.empty:
            continue

        diff = df["close"] - df["prev_close"]
        for date_value, delta, is_new_high, is_new_low in zip(
            df["date"],
            diff,
            df["new_high_signal"],
            df["new_low_signal"],
        ):
            date_key = pd.Timestamp(date_value).strftime("%Y-%m-%d")
            bucket = counts.setdefault(
                date_key,
                {"up": 0, "down": 0, "flat": 0, "new_high": 0, "new_low": 0},
            )
            if float(delta) > 1e-9:
                bucket["up"] += 1
            elif float(delta) < -1e-9:
                bucket["down"] += 1
            else:
                bucket["flat"] += 1
            if bool(is_new_high):
                bucket["new_high"] += 1
            if bool(is_new_low):
                bucket["new_low"] += 1

    return dict(sorted(counts.items()))


def load_latest_index_member_symbols(
    meta_dir: str | Path,
    index_code: str,
    as_of: str | None = None,
) -> list[str]:
    """Load latest cached index member symbols before ``as_of``."""
    path = Path(meta_dir) / "index_members" / f"{index_code.upper()}.csv"
    if not path.exists():
        return []
    try:
        df = pd.read_csv(path, dtype={"con_code": str, "trade_date": str})
    except Exception:
        return []
    if df.empty or "con_code" not in df.columns or "trade_date" not in df.columns:
        return []
    df = df.dropna(subset=["con_code", "trade_date"]).copy()
    if as_of:
        as_of_digits = str(as_of).replace("-", "")
        df = df[df["trade_date"].astype(str) <= as_of_digits]
    if df.empty:
        return []
    latest_date = df["trade_date"].astype(str).max()
    latest = df[df["trade_date"].astype(str) == latest_date]
    return sorted(latest["con_code"].astype(str).str.upper().unique().tolist())


def load_stock_basic_symbols_by_market(meta_dir: str | Path, market: str) -> list[str]:
    """Load stock symbols by stock_basic market label, such as 创业板."""
    path = Path(meta_dir) / "stocks.csv"
    if not path.exists():
        return []
    try:
        df = pd.read_csv(path, dtype=str)
    except Exception:
        return []
    if df.empty or "ts_code" not in df.columns or "market" not in df.columns:
        return []
    mask = df["market"].astype(str) == str(market)
    if "name" in df.columns:
        mask &= ~df["name"].astype(str).str.contains("ST", na=False)
    if "list_status" in df.columns:
        mask &= df["list_status"].fillna("L").astype(str).eq("L")
    return sorted(df.loc[mask, "ts_code"].dropna().astype(str).str.upper().unique().tolist())


def breadth_for_payload(
    dates: list[str],
    breadth_by_date: dict[str, dict[str, Any]] | None,
) -> list[dict[str, int] | None]:
    """Align breadth counts with chart date strings."""
    if not breadth_by_date:
        return [None for _ in dates]
    aligned: list[dict[str, int] | None] = []
    for date_key in dates:
        item = breadth_by_date.get(date_key)
        if not item:
            aligned.append(None)
            continue
        aligned.append(
            {
                "up": int(item.get("up", 0)),
                "down": int(item.get("down", 0)),
                "flat": int(item.get("flat", 0)),
            }
        )
    return aligned


def breadth_indicator_payload(
    dates: list[str],
    breadth_by_date: dict[str, dict[str, Any]] | None,
) -> dict[str, list[Any]]:
    """Build A/D and NH-NL series aligned with report chart dates."""
    payload: dict[str, list[Any]] = {
        "dates": [],
        "ad": [],
        "ad_line": [],
        "ad_norm": [],
        "ad_norm_line": [],
        "ad_norm_line_rebased": [],
        "new_high": [],
        "new_low": [],
        "nhnl": [],
        "nhnl_5d": [],
    }
    if not breadth_by_date:
        return payload

    ad_line = 0
    ad_norm_line = 0.0
    ad_norm_line_base: float | None = None
    nhnl_window: list[int] = []
    for date_key in dates:
        item = breadth_by_date.get(date_key)
        if not item:
            continue
        up = int(item.get("up", 0) or 0)
        down = int(item.get("down", 0) or 0)
        new_high = int(item.get("new_high", 0) or 0)
        new_low = int(item.get("new_low", 0) or 0)
        ad_value = up - down
        ad_total = up + down
        ad_norm = (ad_value / ad_total) if ad_total else 0.0
        nhnl_value = new_high - new_low
        ad_line += ad_value
        ad_norm_line += ad_norm
        if ad_norm_line_base is None:
            ad_norm_line_base = ad_norm_line
        rebased_ad_norm_line = ad_norm_line - ad_norm_line_base
        nhnl_window.append(nhnl_value)
        if len(nhnl_window) > 5:
            nhnl_window.pop(0)

        payload["dates"].append(date_key)
        payload["ad"].append(ad_value)
        payload["ad_line"].append(ad_line)
        payload["ad_norm"].append(round(ad_norm, 4))
        payload["ad_norm_line"].append(round(ad_norm_line, 4))
        payload["ad_norm_line_rebased"].append(round(rebased_ad_norm_line, 4))
        payload["new_high"].append(new_high)
        payload["new_low"].append(new_low)
        payload["nhnl"].append(nhnl_value)
        payload["nhnl_5d"].append(sum(nhnl_window))

    return payload
