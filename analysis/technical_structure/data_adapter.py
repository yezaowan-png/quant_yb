"""Normalize provider data and resample daily OHLCV without fabricating bars."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .models import (
    OHLCVFrame,
    SUPPORTED_ADJUSTMENTS,
    SUPPORTED_ASSET_TYPES,
    SUPPORTED_TIMEFRAMES,
)


_ALIASES = {
    "trade_date": "date",
    "datetime": "date",
    "vol": "volume",
    "turnover": "amount",
}


def _date_text(value: Any) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _parse_dates(values: pd.Series) -> pd.Series:
    """Parse provider dates, including integer/string YYYYMMDD values."""
    text = values.astype("string").str.strip().str.replace(r"\.0$", "", regex=True)
    compact = text.str.fullmatch(r"\d{8}", na=False)
    parsed = pd.to_datetime(text.where(~compact), errors="coerce")
    parsed.loc[compact] = pd.to_datetime(text.loc[compact], format="%Y%m%d", errors="coerce")
    return parsed


def normalize_ohlcv(
    ohlcv: pd.DataFrame,
    *,
    symbol: str,
    asset_type: str,
    timeframe: str = "1d",
    adjustment: str | None = None,
    as_of_date: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> OHLCVFrame:
    """Return provider-independent, increasing OHLCV data.

    Volume and amount are optional. Suspended dates are not generated.
    """
    asset = str(asset_type or "other").lower()
    if asset not in SUPPORTED_ASSET_TYPES:
        raise ValueError(f"unsupported asset_type: {asset_type}")
    tf = str(timeframe or "1d").lower()
    if tf not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    adj = "none" if asset == "index" else str(adjustment or "qfq").lower()
    if adj not in SUPPORTED_ADJUSTMENTS:
        raise ValueError(f"unsupported adjustment: {adjustment}")

    frame = ohlcv.copy().rename(
        columns={
            key: value
            for key, value in _ALIASES.items()
            if key in ohlcv.columns and value not in ohlcv.columns
        }
    )
    required = {"date", "open", "high", "low", "close"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"OHLCV data missing columns: {', '.join(missing)}")
    for optional in ("volume", "amount"):
        if optional not in frame.columns:
            frame[optional] = np.nan
    frame = frame[["date", "open", "high", "low", "close", "volume", "amount"]].copy()
    frame["date"] = _parse_dates(frame["date"])
    for column in ("open", "high", "low", "close", "volume", "amount"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["date", "open", "high", "low", "close"])
    frame = frame[(frame[["open", "high", "low", "close"]] > 0).all(axis=1)]
    frame = frame[
        (frame["high"] >= frame[["open", "close", "low"]].max(axis=1))
        & (frame["low"] <= frame[["open", "close", "high"]].min(axis=1))
    ]
    frame = frame.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    if as_of_date:
        cutoff = pd.to_datetime(as_of_date, errors="raise")
        frame = frame[frame["date"] <= cutoff].reset_index(drop=True)

    flags: list[str] = []
    if frame["volume"].isna().all():
        flags.append("missing_volume")
    if asset == "stock" and not frame.empty:
        volume = pd.to_numeric(frame["volume"], errors="coerce")
        zero_or_missing = float((volume.isna() | volume.le(0)).mean())
        if zero_or_missing >= 0.20:
            flags.append("suspension_heavy")
        positive = volume[volume > 0]
        if positive.empty or (len(frame) >= 20 and float(positive.tail(60).median()) <= 100.0):
            flags.append("low_liquidity")
        jump = frame["close"].pct_change().abs()
        gap = (frame["open"] / frame["close"].shift(1) - 1.0).abs()
        intraday = (frame["high"] / frame["low"] - 1.0).abs()
        if bool(((jump > 0.25) & (gap > 0.20) & (intraday < 0.08)).any()):
            flags.append("adjustment_anomaly")

    frame["is_complete"] = True
    frame["eligible_for_structure"] = True
    return OHLCVFrame(
        symbol=str(symbol).upper(),
        asset_type=asset,
        timeframe=tf,
        adjustment=adj,
        data=frame,
        metadata=dict(metadata or {}),
        data_quality_flags=sorted(set(flags)),
    )


def _period_key(dates: pd.Series, timeframe: str) -> pd.Series:
    if timeframe == "1w":
        return dates.dt.to_period("W-FRI").astype(str)
    if timeframe == "1mo":
        return dates.dt.to_period("M").astype(str)
    return dates.dt.strftime("%Y-%m-%d")


def _current_period_complete(last_date: pd.Timestamp, timeframe: str, config: dict | None = None) -> bool:
    cfg = config or {}
    explicit = {str(value).replace("-", "") for value in cfg.get("completed_period_end_dates", [])}
    if last_date.strftime("%Y%m%d") in explicit:
        return True
    if timeframe == "1w":
        return int(last_date.weekday()) == 4
    if timeframe == "1mo":
        return bool(last_date.is_month_end)
    return True


def resample_ohlcv(
    daily: OHLCVFrame | pd.DataFrame,
    timeframe: str,
    *,
    include_incomplete_bar: bool = False,
    as_of_date: str | None = None,
    config: dict | None = None,
) -> OHLCVFrame:
    """Resample actual daily observations; labels use the last observed trade date."""
    if isinstance(daily, OHLCVFrame):
        source = daily
    else:
        source = normalize_ohlcv(
            daily, symbol="UNKNOWN", asset_type="other", timeframe="1d", adjustment="none", as_of_date=as_of_date
        )
    tf = str(timeframe).lower()
    if tf not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    frame = source.data.copy()
    if as_of_date:
        frame = frame[frame["date"] <= pd.to_datetime(as_of_date)].reset_index(drop=True)
    if tf == "1d":
        return OHLCVFrame(
            source.symbol, source.asset_type, tf, source.adjustment, frame,
            dict(source.metadata), list(source.data_quality_flags),
        )
    if frame.empty:
        return OHLCVFrame(
            source.symbol, source.asset_type, tf, source.adjustment, frame,
            dict(source.metadata), list(source.data_quality_flags),
        )

    work = frame.copy()
    work["_period"] = _period_key(work["date"], tf)
    rows: list[dict[str, Any]] = []
    for _, group in work.groupby("_period", sort=True):
        group = group.sort_values("date")
        rows.append(
            {
                "date": group["date"].iloc[-1],
                "open": float(group["open"].iloc[0]),
                "high": float(group["high"].max()),
                "low": float(group["low"].min()),
                "close": float(group["close"].iloc[-1]),
                "volume": group["volume"].sum(min_count=1),
                "amount": group["amount"].sum(min_count=1),
                "is_complete": True,
                "eligible_for_structure": True,
            }
        )
    result = pd.DataFrame(rows)
    flags = list(source.data_quality_flags)
    if not result.empty and not _current_period_complete(pd.Timestamp(result["date"].iloc[-1]), tf, config):
        result.loc[result.index[-1], "is_complete"] = False
        result.loc[result.index[-1], "eligible_for_structure"] = False
        flags.append("incomplete_bar_excluded")
        if not include_incomplete_bar:
            result = result.iloc[:-1].reset_index(drop=True)
    return OHLCVFrame(
        symbol=source.symbol,
        asset_type=source.asset_type,
        timeframe=tf,
        adjustment=source.adjustment,
        data=result,
        metadata=dict(source.metadata),
        data_quality_flags=sorted(set(flags)),
    )


def bar_records(frame: pd.DataFrame, atr: pd.Series | None = None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, row in frame.reset_index(drop=True).iterrows():
        records.append(
            {
                "bar_index": int(index),
                "date": _date_text(row["date"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": None if pd.isna(row.get("volume")) else float(row.get("volume")),
                "amount": None if pd.isna(row.get("amount")) else float(row.get("amount")),
                "atr": None if atr is None or pd.isna(atr.iloc[index]) else float(atr.iloc[index]),
                "is_complete": bool(row.get("is_complete", True)),
                "eligible_for_structure": bool(row.get("eligible_for_structure", True)),
            }
        )
    return records
