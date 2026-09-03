"""Stock price adjustment helpers.

These functions are intentionally pure and small. Download orchestration stays
in DataDownloader; this module only calculates adjusted daily prices.
"""

from __future__ import annotations

import pandas as pd


PRICE_COLUMNS = ["open", "high", "low", "close", "pre_close"]


def is_adjusted_mode(adj: object) -> bool:
    return not (adj is None or str(adj).lower() in {"", "none", "raw"})


def apply_price_adjustment(raw: pd.DataFrame, factors: pd.DataFrame, adj: object) -> pd.DataFrame:
    """Apply qfq/hfq adjustment to raw Tushare daily rows.

    The current project convention treats the first returned factor as qfq base,
    matching the previous DataDownloader implementation.
    """
    if raw is None or raw.empty or not is_adjusted_mode(adj):
        return raw
    if factors is None or factors.empty:
        return raw.iloc[0:0]

    mode = str(adj).lower()
    merged = raw.set_index("trade_date", drop=False).merge(
        factors.set_index("trade_date"),
        left_index=True,
        right_index=True,
        how="left",
    )
    merged["adj_factor"] = pd.to_numeric(merged["adj_factor"], errors="coerce").bfill()
    base_factor = float(pd.to_numeric(factors["adj_factor"], errors="coerce").iloc[0])

    for col in PRICE_COLUMNS:
        if col not in merged.columns:
            continue
        merged[col] = pd.to_numeric(merged[col], errors="coerce")
        if mode == "hfq":
            merged[col] = merged[col] * merged["adj_factor"]
        elif mode == "qfq":
            merged[col] = merged[col] * merged["adj_factor"] / base_factor
        merged[col] = merged[col].round(2)

    if "pre_close" in merged.columns:
        merged["change"] = merged["close"] - merged["pre_close"]
        merged["pct_chg"] = merged["change"] / merged["pre_close"] * 100
    return merged.reset_index(drop=True)


def overlap_price_mismatch(existing: pd.DataFrame, fetched: pd.DataFrame, tolerance: float = 0.01) -> bool:
    if existing is None or existing.empty or fetched is None or fetched.empty:
        return False
    overlap_dates = set(existing["date"]).intersection(set(fetched["date"]))
    if not overlap_dates:
        return False
    existing_idx = existing.set_index("date")
    fetched_idx = fetched.set_index("date")
    for dt in overlap_dates:
        for col in ["open", "high", "low", "close"]:
            old = existing_idx.at[dt, col]
            new = fetched_idx.at[dt, col]
            if pd.isna(old) or pd.isna(new):
                continue
            if abs(float(old) - float(new)) > tolerance:
                return True
    return False
