"""Index lift quality and turnover-structure diagnostics.

This module is part of the market-structure description layer only.  It is
kept separate from execution systems.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd


UNKNOWN = "unknown"

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "history_window": 252,
    "min_history": 120,
    "top_contributors": {
        "top_n": 20,
        "high_weight_quantile": 0.80,
        "high_turnover_quantile": 0.80,
    },
    "turnover": {
        "low_volume_ratio": 0.80,
        "heavy_volume_ratio": 1.20,
    },
    "scoring": {
        "participation_weight": 0.30,
        "turnover_confirmation_weight": 0.25,
        "contribution_dispersion_weight": 0.25,
        "heavy_turnover_direction_weight": 0.20,
    },
    "display": {
        "recent_days": 60,
        "top_stock_count": 10,
        "top_turnover_stock_count": 20,
    },
    "reconciliation_error_threshold": 0.01,
}

SUPPORTED_INDICES: tuple[dict[str, Any], ...] = (
    {"name": "上证指数", "symbol": "000001.SH", "member_codes": ("000001.SH",), "fallback_exchange": "SSE"},
    {"name": "沪深300", "symbol": "000300.SH", "member_codes": ("000300.SH", "399300.SZ")},
    {"name": "上证50", "symbol": "000016.SH", "member_codes": ("000016.SH",)},
    {"name": "中证500", "symbol": "000905.SH", "member_codes": ("000905.SH",)},
    {"name": "中证1000", "symbol": "000852.SH", "member_codes": ("000852.SH",)},
    {"name": "中证2000", "symbol": "932000.CSI", "member_codes": ("932000.CSI",)},
    {"name": "创业板指", "symbol": "399006.SZ", "member_codes": ("399006.SZ",), "fallback_market": "创业板"},
    {"name": "科创50", "symbol": "000688.SH", "member_codes": ("000688.SH",), "fallback_market": "科创板"},
)

STATE_CN = {
    "broad_confirmed_rise": "广泛确认上涨",
    "concentrated_but_supported": "集中但有成交支撑",
    "thin_weighted_lift": "缩量拉权重",
    "masked_distribution": "掩护性上涨结构",
    "broad_decline": "广泛下跌",
    "mixed_divergence": "多空分化",
    UNKNOWN: "数据不足",
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    result = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _finite(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
        number = float(value)
    except Exception:
        return None
    return number if np.isfinite(number) else None


def _safe_div(numerator: Any, denominator: Any) -> float | None:
    n = _finite(numerator)
    d = _finite(denominator)
    if n is None or d is None or d == 0:
        return None
    return n / d


def _serialize(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): _serialize(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_serialize(child) for child in value]
    return value


def _index_return_series(frame: pd.DataFrame | None, dates: pd.DatetimeIndex) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(index=dates, dtype="float64")
    work = frame.copy()
    date_column = "date" if "date" in work.columns else "trade_date" if "trade_date" in work.columns else None
    if date_column is None or "close" not in work.columns:
        return pd.Series(index=dates, dtype="float64")
    work[date_column] = pd.to_datetime(work[date_column], errors="coerce")
    work["close"] = pd.to_numeric(work["close"], errors="coerce")
    close = (
        work.dropna(subset=[date_column, "close"])
        .drop_duplicates(date_column, keep="last")
        .sort_values(date_column)
        .set_index(date_column)["close"]
        .reindex(dates)
    )
    return close.pct_change(fill_method=None)


def _stock_name_map(metadata: pd.DataFrame) -> dict[str, str]:
    if metadata is None or metadata.empty or "ts_code" not in metadata.columns:
        return {}
    name_col = "name" if "name" in metadata.columns else None
    industry_col = "industry" if "industry" in metadata.columns else None
    result: dict[str, str] = {}
    for _, row in metadata.iterrows():
        code = str(row.get("ts_code") or "").upper()
        if not code:
            continue
        name = row.get(name_col) if name_col else None
        industry = row.get(industry_col) if industry_col else None
        result[code] = str(name or industry or code)
    return result


def _industry_map(metadata: pd.DataFrame) -> dict[str, str]:
    if metadata is None or metadata.empty or "ts_code" not in metadata.columns or "industry" not in metadata.columns:
        return {}
    return {
        str(row.get("ts_code") or "").upper(): str(row.get("industry") or "--")
        for _, row in metadata.iterrows()
        if str(row.get("ts_code") or "")
    }


def _metadata_symbols(
    metadata: pd.DataFrame,
    columns: Iterable[str],
    *,
    market: str | None = None,
    exchange: str | None = None,
) -> list[str]:
    if metadata is None or metadata.empty or "ts_code" not in metadata.columns:
        return []
    column_set = {str(column).upper() for column in columns}
    frame = metadata.copy()
    frame["ts_code"] = frame["ts_code"].astype(str).str.upper()
    mask = frame["ts_code"].isin(column_set)
    if market and "market" in frame.columns:
        mask &= frame["market"].astype(str).eq(market)
    if exchange and "exchange" in frame.columns:
        mask &= frame["exchange"].astype(str).str.upper().eq(exchange.upper())
    if "name" in frame.columns:
        mask &= ~frame["name"].astype(str).str.contains("ST", case=False, na=False)
    return sorted(frame.loc[mask, "ts_code"].dropna().unique().tolist())


def _prepare_member_frames(frames: dict[str, pd.DataFrame] | None) -> dict[str, pd.DataFrame]:
    prepared: dict[str, pd.DataFrame] = {}
    for code, source in (frames or {}).items():
        if source is None or source.empty or not {"trade_date", "con_code"}.issubset(source.columns):
            continue
        frame = source.copy()
        frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
        frame["con_code"] = frame["con_code"].astype(str).str.upper()
        frame["weight"] = pd.to_numeric(frame.get("weight"), errors="coerce")
        frame = frame.dropna(subset=["trade_date", "con_code"]).sort_values(["trade_date", "con_code"])
        if not frame.empty:
            prepared[str(code).upper()] = frame.reset_index(drop=True)
    return prepared


def _strict_member_snapshot(
    member_frames: dict[str, pd.DataFrame],
    member_codes: Iterable[str],
    date: pd.Timestamp,
) -> tuple[list[str], pd.Series | None, str | None]:
    """Return the latest index-weight snapshot strictly before *date*."""
    for code in member_codes:
        frame = member_frames.get(str(code).upper())
        if frame is None or frame.empty:
            continue
        eligible = frame[frame["trade_date"] < date]
        if eligible.empty:
            continue
        snapshot_date = eligible["trade_date"].max()
        snapshot = eligible[eligible["trade_date"] == snapshot_date].drop_duplicates("con_code", keep="last")
        symbols = snapshot["con_code"].astype(str).str.upper().tolist()
        weights = pd.to_numeric(snapshot["weight"], errors="coerce")
        if weights.notna().any() and float(weights.fillna(0).sum()) > 0:
            series = pd.Series(weights.to_numpy(dtype=float), index=symbols, dtype="float64")
            series = series / series.sum()
        else:
            series = None
        return symbols, series, pd.Timestamp(snapshot_date).strftime("%Y-%m-%d")
    return [], None, None


def _fallback_weights(
    *,
    layer: dict[str, Any],
    close: pd.DataFrame,
    metadata: pd.DataFrame,
) -> tuple[list[str], pd.Series | None, list[str]]:
    flags = ["index_weight_is_approximate", "index_weight_not_point_in_time"]
    symbols = _metadata_symbols(
        metadata,
        close.columns,
        market=layer.get("fallback_market"),
        exchange=layer.get("fallback_exchange"),
    )
    if not symbols and layer.get("symbol") == "000001.SH":
        symbols = _metadata_symbols(metadata, close.columns, exchange="SSE")
    if not symbols:
        flags.append("missing_index_constituents")
        return [], None, flags
    cap_column = next(
        (column for column in ("float_market_cap", "float_mv", "circ_mv", "market_cap", "total_mv") if column in metadata.columns),
        None,
    )
    if cap_column:
        frame = metadata.copy()
        frame["ts_code"] = frame["ts_code"].astype(str).str.upper()
        caps = pd.to_numeric(frame.set_index("ts_code")[cap_column], errors="coerce").reindex(symbols)
        if caps.notna().any() and float(caps.fillna(0).sum()) > 0:
            weights = caps.fillna(0.0).astype(float)
            return symbols, weights / weights.sum(), flags
    flags.append("missing_float_market_cap")
    weights = pd.Series(1.0 / len(symbols), index=symbols, dtype="float64")
    return symbols, weights, flags


def _stocks_needed(values: pd.Series, target_share: float) -> int | None:
    values = values.dropna().sort_values(ascending=False)
    total = float(values.sum())
    if values.empty or total <= 0:
        return None
    return int((values.cumsum() / total >= target_share).idxmax() in values.index and np.searchsorted((values.cumsum() / total).to_numpy(), target_share, side="left") + 1)


def _top_share(values: pd.Series, n: int) -> float | None:
    values = values.dropna()
    total = float(values.sum())
    if values.empty or total <= 0:
        return None
    return float(values.sort_values(ascending=False).head(n).sum() / total)


def _hhi(values: pd.Series) -> float | None:
    values = values.dropna()
    total = float(values.sum())
    if values.empty or total <= 0:
        return None
    shares = values / total
    return float((shares * shares).sum())


def _amount_weighted_return(returns: pd.Series, amount: pd.Series) -> float | None:
    valid = returns.notna() & amount.notna() & (amount > 0)
    if not bool(valid.any()):
        return None
    return float((returns[valid] * amount[valid]).sum() / amount[valid].sum())


def _stock_rows(
    *,
    symbols: list[str],
    weights: pd.Series,
    returns: pd.Series,
    amount: pd.Series,
    amount_ratio: pd.Series,
    contribution: pd.Series,
    name_map: dict[str, str],
    industry_map: dict[str, str],
    top_n: int,
    mode: str,
) -> list[dict[str, Any]]:
    if mode == "positive":
        ordered = contribution[contribution > 0].sort_values(ascending=False).head(top_n)
        denom = float(contribution[contribution > 0].sum())
    elif mode == "negative":
        ordered = contribution[contribution < 0].sort_values(ascending=True).head(top_n)
        denom = float(abs(contribution[contribution < 0].sum()))
    elif mode == "absolute":
        ordered = contribution.reindex(symbols).abs().sort_values(ascending=False).head(top_n)
        denom = float(contribution.reindex(symbols).abs().sum())
    else:
        ordered = amount.reindex(symbols).sort_values(ascending=False).head(top_n)
        denom = float(amount.reindex(symbols).sum())
    rows: list[dict[str, Any]] = []
    for symbol, value in ordered.items():
        contrib = _finite(contribution.get(symbol))
        row_amount = _finite(amount.get(symbol))
        row = {
            "symbol": symbol,
            "name": name_map.get(symbol, symbol),
            "industry": industry_map.get(symbol, "--"),
            "index_weight": _finite(weights.get(symbol)),
            "return_1d": _finite(returns.get(symbol)),
            "amount": row_amount,
            "amount_ratio_20d": _finite(amount_ratio.get(symbol)),
            "amount_share": _safe_div(row_amount, float(amount.reindex(symbols).sum())),
            "index_contribution": contrib,
            "contribution_share": _safe_div(abs(contrib) if mode in {"absolute", "negative"} else contrib, denom),
        }
        rows.append(row)
    return rows


def _group_rows(
    *,
    symbols: list[str],
    returns: pd.Series,
    amount: pd.Series,
    amount_ratio: pd.Series,
    weights: pd.Series,
    contribution: pd.Series,
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], float | None]:
    top_cfg = config["top_contributors"]
    heavy_ratio = float(config["turnover"]["heavy_volume_ratio"])
    high_weight_cut = weights.quantile(float(top_cfg["high_weight_quantile"])) if len(weights.dropna()) else np.nan
    amount_cut = amount.reindex(symbols).quantile(float(top_cfg["high_turnover_quantile"])) if len(symbols) else np.nan
    high_weight = weights >= high_weight_cut
    high_turnover = (amount >= amount_cut) | (amount_ratio >= heavy_ratio)
    definitions = [
        ("high_weight_high_turnover", "高权重高成交", high_weight & high_turnover),
        ("high_weight_low_turnover", "高权重低成交", high_weight & ~high_turnover),
        ("low_weight_high_turnover", "低权重高成交", ~high_weight & high_turnover),
        ("low_weight_low_turnover", "低权重低成交", ~high_weight & ~high_turnover),
    ]
    total_amount = float(amount.reindex(symbols).sum())
    total_positive = float(contribution[contribution > 0].sum())
    rows: list[dict[str, Any]] = []
    for code, name, mask in definitions:
        selected = [symbol for symbol in symbols if bool(mask.get(symbol, False))]
        selected_returns = returns.reindex(selected)
        selected_amount = amount.reindex(selected)
        selected_contribution = contribution.reindex(selected)
        rows.append(
            {
                "group": code,
                "group_cn": name,
                "count": int(len(selected)),
                "equal_return": _finite(selected_returns.mean(skipna=True)),
                "amount_weighted_return": _amount_weighted_return(selected_returns, selected_amount),
                "index_contribution": _finite(selected_contribution.sum()),
                "amount_share": _safe_div(float(selected_amount.sum()), total_amount),
                "advance_ratio": _safe_div(float((selected_returns > 0).sum()), float(selected_returns.notna().sum())),
            }
        )
    low_volume_lift = contribution[(contribution > 0) & high_weight & ~high_turnover].sum()
    return rows, _safe_div(float(low_volume_lift), total_positive)


def _row_for_date(
    *,
    layer: dict[str, Any],
    date: pd.Timestamp,
    close: pd.DataFrame,
    amount: pd.DataFrame,
    amount_ma20: pd.DataFrame,
    amount_ratio: pd.DataFrame,
    new_low20: pd.DataFrame,
    stock_returns: pd.DataFrame,
    index_returns: pd.Series,
    member_frames: dict[str, pd.DataFrame],
    metadata: pd.DataFrame,
    name_map: dict[str, str],
    industry_map: dict[str, str],
    config: dict[str, Any],
    include_details: bool,
    fallback_cache: tuple[list[str], pd.Series | None, list[str]] | None = None,
) -> dict[str, Any]:
    flags: list[str] = []
    symbols, weights, snapshot_date = _strict_member_snapshot(member_frames, layer.get("member_codes", ()), date)
    if not symbols or weights is None:
        fallback_symbols, fallback_weights, fallback_flags = (
            fallback_cache if fallback_cache is not None else _fallback_weights(layer=layer, close=close, metadata=metadata)
        )
        symbols, weights = fallback_symbols, fallback_weights
        flags.extend(fallback_flags)
    if not symbols or weights is None:
        return {
            "trade_date": date.strftime("%Y-%m-%d"),
            "symbol": layer["symbol"],
            "index_name": layer["name"],
            "state": UNKNOWN,
            "state_cn": STATE_CN[UNKNOWN],
            "data_quality_flags": sorted(set(flags + ["missing_index_constituents"])),
        }
    symbols = [symbol for symbol in symbols if symbol in close.columns]
    if not symbols:
        return {
            "trade_date": date.strftime("%Y-%m-%d"),
            "symbol": layer["symbol"],
            "index_name": layer["name"],
            "state": UNKNOWN,
            "state_cn": STATE_CN[UNKNOWN],
            "data_quality_flags": sorted(set(flags + ["missing_index_constituents"])),
        }
    returns = stock_returns.loc[date, symbols].astype(float)
    amount_row = amount.loc[date, symbols].astype(float)
    amount_ma = amount_ma20.loc[date, symbols].astype(float)
    amount_ratio_row = amount_ratio.loc[date, symbols].astype(float)
    valid = returns.notna() & amount_row.notna() & (amount_row > 0)
    if int(valid.sum()) < max(3, min(10, len(symbols) // 5)):
        flags.append("missing_amount_data")
    if amount_ma.notna().sum() < max(3, min(10, len(symbols) // 5)):
        flags.append("insufficient_amount_history")
    symbols = [symbol for symbol in symbols if bool(valid.get(symbol, False))]
    if not symbols:
        return {
            "trade_date": date.strftime("%Y-%m-%d"),
            "symbol": layer["symbol"],
            "index_name": layer["name"],
            "state": UNKNOWN,
            "state_cn": STATE_CN[UNKNOWN],
            "data_quality_flags": sorted(set(flags)),
        }
    returns = returns.reindex(symbols)
    amount_row = amount_row.reindex(symbols)
    amount_ma = amount_ma.reindex(symbols)
    amount_ratio_row = amount_ratio_row.reindex(symbols)
    weights = weights.reindex(symbols).fillna(0.0).astype(float)
    if float(weights.sum()) <= 0:
        weights = pd.Series(1.0 / len(symbols), index=symbols)
        flags.extend(["index_weight_is_approximate", "index_weight_not_point_in_time"])
    else:
        weights = weights / weights.sum()
    contribution = returns * weights
    positive = contribution[contribution > 0]
    negative = contribution[contribution < 0]
    total_positive = float(positive.sum())
    top_n = int(config["top_contributors"]["top_n"])
    top_positive = positive.sort_values(ascending=False).head(top_n)
    top_absolute = contribution.abs().sort_values(ascending=False).head(top_n)
    top_absolute_signed_contribution = float(contribution.reindex(top_absolute.index).sum())
    top10_contributor_amount = amount_row.reindex(top_positive.index)
    contribution_weighted_amount_ratio = None
    if total_positive > 0 and amount_ratio_row.notna().any():
        contribution_weighted_amount_ratio = float((amount_ratio_row.reindex(positive.index).fillna(0.0) * (positive / total_positive)).sum())
    low_volume_positive = positive[amount_ratio_row.reindex(positive.index) < float(config["turnover"]["low_volume_ratio"])]
    down_amount = float(amount_row[returns < 0].sum())
    up_amount = float(amount_row[returns > 0].sum())
    total_amount = float(amount_row.sum())
    top_turnover_count = max(1, int(np.ceil(len(symbols) * 0.20)))
    top_turnover_symbols = amount_row.sort_values(ascending=False).head(top_turnover_count).index
    top_turnover_display_count = max(1, int((config.get("display") or {}).get("top_turnover_stock_count", 20)))
    top_turnover_display_amount = float(amount_row.sort_values(ascending=False).head(top_turnover_display_count).sum())
    heavy_selling = (returns < 0) & (amount_ratio_row >= float(config["turnover"]["heavy_volume_ratio"]))
    new_low = new_low20.loc[date, symbols].fillna(False).astype(bool)
    estimated_return = float(contribution.sum())
    official_return = _finite(index_returns.get(date))
    reconciliation_error = None if official_return is None else estimated_return - official_return
    if reconciliation_error is not None and abs(reconciliation_error) > float(config.get("reconciliation_error_threshold", 0.01)):
        flags.append("contribution_reconciliation_failed")
    if snapshot_date is None:
        snapshot_date = None
    groups, low_turnover_lift_share = _group_rows(
        symbols=symbols,
        returns=returns,
        amount=amount_row,
        amount_ratio=amount_ratio_row,
        weights=weights,
        contribution=contribution,
        config=config,
    )
    top_positive_rows = (
        _stock_rows(symbols=symbols, weights=weights, returns=returns, amount=amount_row, amount_ratio=amount_ratio_row, contribution=contribution, name_map=name_map, industry_map=industry_map, top_n=top_n, mode="positive")
        if include_details else []
    )
    top_negative_rows = (
        _stock_rows(symbols=symbols, weights=weights, returns=returns, amount=amount_row, amount_ratio=amount_ratio_row, contribution=contribution, name_map=name_map, industry_map=industry_map, top_n=top_n, mode="negative")
        if include_details else []
    )
    top_absolute_rows = (
        _stock_rows(symbols=symbols, weights=weights, returns=returns, amount=amount_row, amount_ratio=amount_ratio_row, contribution=contribution, name_map=name_map, industry_map=industry_map, top_n=top_n, mode="absolute")
        if include_details else []
    )
    top_turnover_rows = (
        _stock_rows(symbols=symbols, weights=weights, returns=returns, amount=amount_row, amount_ratio=amount_ratio_row, contribution=contribution, name_map=name_map, industry_map=industry_map, top_n=top_turnover_display_count, mode="turnover")
        if include_details else []
    )
    returns_block = {
        "index_return": official_return,
        "estimated_index_return": estimated_return,
        "equal_weight_return": _finite(returns.mean(skipna=True)),
        "amount_weighted_return": _amount_weighted_return(returns, amount_row),
        "index_equal_weight_gap": None,
        "index_amount_weighted_gap": None,
        "reconciliation_error": reconciliation_error,
    }
    if returns_block["index_return"] is not None and returns_block["equal_weight_return"] is not None:
        returns_block["index_equal_weight_gap"] = returns_block["index_return"] - returns_block["equal_weight_return"]
    if returns_block["index_return"] is not None and returns_block["amount_weighted_return"] is not None:
        returns_block["index_amount_weighted_gap"] = returns_block["index_return"] - returns_block["amount_weighted_return"]
    row = {
        "trade_date": date.strftime("%Y-%m-%d"),
        "symbol": layer["symbol"],
        "index_name": layer["name"],
        "member_snapshot_date": snapshot_date,
        "stock_count": int(len(symbols)),
        "valid_stock_count": int(len(symbols)),
        "returns": returns_block,
        "contribution_concentration": {
            "top_3_positive_contribution_share": _top_share(positive, 3),
            "top_5_positive_contribution_share": _top_share(positive, 5),
            "top_10_positive_contribution_share": _top_share(positive, 10),
            "top_10_absolute_contribution_share": _top_share(contribution.abs(), 10),
            "top_10_signed_index_contribution": _finite(top_absolute_signed_contribution),
            "top_10_signed_index_return_share": _safe_div(
                top_absolute_signed_contribution,
                returns_block["index_return"] if returns_block["index_return"] is not None else estimated_return,
            ),
            "positive_contribution_hhi": _hhi(positive),
            "stocks_needed_for_50pct_positive_contribution": _stocks_needed(positive, 0.50),
            "stocks_needed_for_80pct_positive_contribution": _stocks_needed(positive, 0.80),
        },
        "turnover_confirmation": {
            "top10_contributor_amount_share": _safe_div(float(top10_contributor_amount.sum()), total_amount),
            "top20_turnover_amount_share": _safe_div(top_turnover_display_amount, total_amount),
            "top10_contributor_amount_ratio_20d": _finite(top10_contributor_amount.sum() / amount_ma.reindex(top_positive.index).sum()) if float(amount_ma.reindex(top_positive.index).sum(skipna=True)) > 0 else None,
            "contribution_weighted_amount_ratio_20d": contribution_weighted_amount_ratio,
            "low_volume_positive_contribution_share": _safe_div(float(low_volume_positive.sum()), total_positive),
            "contribution_amount_gap": (
                (_top_share(positive, 10) or 0.0) - (_safe_div(float(top10_contributor_amount.sum()), total_amount) or 0.0)
                if total_positive > 0 and total_amount > 0 else None
            ),
            "high_weight_low_turnover_positive_contribution_share": low_turnover_lift_share,
        },
        "heavy_turnover_pressure": {
            "up_amount_share": _safe_div(up_amount, total_amount),
            "down_amount_share": _safe_div(down_amount, total_amount),
            "up_down_amount_ratio": _safe_div(up_amount, down_amount),
            "heavy_selling_amount_share": _safe_div(float(amount_row[heavy_selling].sum()), total_amount),
            "top_turnover_20pct_return": _amount_weighted_return(returns.reindex(top_turnover_symbols), amount_row.reindex(top_turnover_symbols)),
            "new_low_amount_share": _safe_div(float(amount_row[new_low].sum()), total_amount),
        },
        "weight_turnover_groups": groups if include_details else [],
        "top_positive_contributors": top_positive_rows,
        "top_negative_contributors": top_negative_rows,
        "top_absolute_contributors": top_absolute_rows,
        "top_turnover_stocks": top_turnover_rows,
        "state": UNKNOWN,
        "state_cn": STATE_CN[UNKNOWN],
        "supporting_evidence": [],
        "contradicting_evidence": [],
        "confidence": UNKNOWN,
        "data_quality_flags": sorted(set(flags)),
        "index_weight_is_approximate": "index_weight_is_approximate" in flags,
        "index_weight_not_point_in_time": "index_weight_not_point_in_time" in flags,
    }
    row.update(
        {
            "index_return": returns_block["index_return"],
            "equal_weight_return": returns_block["equal_weight_return"],
            "amount_weighted_return": returns_block["amount_weighted_return"],
            "index_equal_weight_gap": returns_block["index_equal_weight_gap"],
            "index_amount_weighted_gap": returns_block["index_amount_weighted_gap"],
            "top_10_positive_contribution_share": row["contribution_concentration"]["top_10_positive_contribution_share"],
            "top_10_absolute_contribution_share": row["contribution_concentration"]["top_10_absolute_contribution_share"],
            "top_10_signed_index_contribution": row["contribution_concentration"]["top_10_signed_index_contribution"],
            "top_10_signed_index_return_share": row["contribution_concentration"]["top_10_signed_index_return_share"],
            "top10_contributor_amount_share": row["turnover_confirmation"]["top10_contributor_amount_share"],
            "top20_turnover_amount_share": row["turnover_confirmation"]["top20_turnover_amount_share"],
            "contribution_weighted_amount_ratio_20d": row["turnover_confirmation"]["contribution_weighted_amount_ratio_20d"],
            "down_amount_share": row["heavy_turnover_pressure"]["down_amount_share"],
            "up_amount_share": row["heavy_turnover_pressure"]["up_amount_share"],
            "heavy_selling_amount_share": row["heavy_turnover_pressure"]["heavy_selling_amount_share"],
            "top_turnover_20pct_return": row["heavy_turnover_pressure"]["top_turnover_20pct_return"],
            "advance_ratio": _safe_div(float((returns > 0).sum()), float(returns.notna().sum())),
            "new_low_amount_share": row["heavy_turnover_pressure"]["new_low_amount_share"],
            "high_weight_low_turnover_positive_contribution_share": low_turnover_lift_share,
        }
    )
    return _serialize(row)


def _rolling_percentile(value: float | None, history: pd.Series) -> float | None:
    current = _finite(value)
    sample = pd.to_numeric(history, errors="coerce").dropna()
    if current is None or sample.empty:
        return None
    return float((sample <= current).mean() * 100.0)


def _mean_optional(values: list[float | None]) -> float | None:
    numbers = [float(value) for value in values if value is not None and np.isfinite(float(value))]
    return float(np.mean(numbers)) if numbers else None


def _apply_scores(rows: list[dict[str, Any]], config: dict[str, Any]) -> None:
    frame = pd.DataFrame(rows)
    history_window = int(config["history_window"])
    min_history = int(config["min_history"])
    weights_cfg = config["scoring"]
    for position, row in enumerate(rows):
        start = max(0, position - history_window)
        sample = frame.iloc[start:position]
        if len(sample) < min_history:
            row["scores"] = {
                "contribution_concentration": None,
                "turnover_confirmation": None,
                "participation": None,
                "heavy_turnover_pressure": None,
                "index_lift_quality": None,
                "index_masking_risk": None,
            }
            continue
        required_columns = [
            "top_10_positive_contribution_share",
            "contribution_weighted_amount_ratio_20d",
            "advance_ratio",
            "up_amount_share",
            "down_amount_share",
            "heavy_selling_amount_share",
            "new_low_amount_share",
            "top_turnover_20pct_return",
            "index_equal_weight_gap",
            "index_amount_weighted_gap",
        ]
        if any(column not in row for column in required_columns) or any(column not in sample.columns for column in required_columns):
            row["scores"] = {
                "contribution_concentration": None,
                "turnover_confirmation": None,
                "participation": None,
                "heavy_turnover_pressure": None,
                "index_lift_quality": None,
                "index_masking_risk": None,
            }
            continue
        concentration_score = _mean_optional(
            [
                _rolling_percentile(row.get("top_10_positive_contribution_share"), sample["top_10_positive_contribution_share"]),
                _rolling_percentile(
                    (row.get("contribution_concentration") or {}).get("positive_contribution_hhi"),
                    sample.apply(lambda x: ((x.get("contribution_concentration") or {}).get("positive_contribution_hhi")), axis=1),
                ),
            ]
        )
        turnover_score = _mean_optional(
            [
                _rolling_percentile(row.get("contribution_weighted_amount_ratio_20d"), sample["contribution_weighted_amount_ratio_20d"]),
                _rolling_percentile((row.get("turnover_confirmation") or {}).get("top10_contributor_amount_ratio_20d"), sample.apply(lambda x: ((x.get("turnover_confirmation") or {}).get("top10_contributor_amount_ratio_20d")), axis=1)),
            ]
        )
        participation_score = _mean_optional(
            [
                _rolling_percentile(row.get("advance_ratio"), sample["advance_ratio"]),
                _rolling_percentile(row.get("up_amount_share"), sample["up_amount_share"]),
            ]
        )
        heavy_score = _mean_optional(
            [
                _rolling_percentile(row.get("down_amount_share"), sample["down_amount_share"]),
                _rolling_percentile(row.get("heavy_selling_amount_share"), sample["heavy_selling_amount_share"]),
                _rolling_percentile(row.get("new_low_amount_share"), sample["new_low_amount_share"]),
                _rolling_percentile(-float(row.get("top_turnover_20pct_return") or 0.0), -pd.to_numeric(sample["top_turnover_20pct_return"], errors="coerce")),
            ]
        )
        masking_raw = (
            max(float(row.get("index_equal_weight_gap") or 0.0), 0.0)
            + max(float(row.get("index_amount_weighted_gap") or 0.0), 0.0)
            + float(row.get("top_10_positive_contribution_share") or 0.0)
            + float(row.get("down_amount_share") or 0.0)
        )
        sample_masking = (
            pd.to_numeric(sample["index_equal_weight_gap"], errors="coerce").clip(lower=0).fillna(0)
            + pd.to_numeric(sample["index_amount_weighted_gap"], errors="coerce").clip(lower=0).fillna(0)
            + pd.to_numeric(sample["top_10_positive_contribution_share"], errors="coerce").fillna(0)
            + pd.to_numeric(sample["down_amount_share"], errors="coerce").fillna(0)
        )
        quality_parts = [
            (participation_score, float(weights_cfg["participation_weight"])),
            (turnover_score, float(weights_cfg["turnover_confirmation_weight"])),
            (None if concentration_score is None else 100.0 - concentration_score, float(weights_cfg["contribution_dispersion_weight"])),
            (None if heavy_score is None else 100.0 - heavy_score, float(weights_cfg["heavy_turnover_direction_weight"])),
        ]
        available = [(value, weight) for value, weight in quality_parts if value is not None]
        quality = None if not available else sum(value * weight for value, weight in available) / sum(weight for _, weight in available)
        row["scores"] = {
            "contribution_concentration": concentration_score,
            "turnover_confirmation": turnover_score,
            "participation": participation_score,
            "heavy_turnover_pressure": heavy_score,
            "index_lift_quality": quality,
            "index_masking_risk": _rolling_percentile(masking_raw, sample_masking),
        }


def _classify_row(row: dict[str, Any], config: dict[str, Any]) -> None:
    returns = row.get("returns") or {}
    conc = row.get("contribution_concentration") or {}
    turnover = row.get("turnover_confirmation") or {}
    pressure = row.get("heavy_turnover_pressure") or {}
    index_ret = _finite(returns.get("index_return"))
    equal_ret = _finite(returns.get("equal_weight_return"))
    amount_ret = _finite(returns.get("amount_weighted_return"))
    gap_equal = _finite(returns.get("index_equal_weight_gap"))
    top10 = _finite(conc.get("top_10_positive_contribution_share"))
    top10_amount_ratio = _finite(turnover.get("top10_contributor_amount_ratio_20d"))
    weighted_amount_ratio = _finite(turnover.get("contribution_weighted_amount_ratio_20d"))
    low_volume_lift = _finite(turnover.get("high_weight_low_turnover_positive_contribution_share"))
    down_share = _finite(pressure.get("down_amount_share"))
    up_share = _finite(pressure.get("up_amount_share"))
    heavy_selling = _finite(pressure.get("heavy_selling_amount_share"))
    top_turnover_ret = _finite(pressure.get("top_turnover_20pct_return"))
    if index_ret is None or equal_ret is None or amount_ret is None:
        state = UNKNOWN
    elif (
        (index_ret > 0 or (gap_equal is not None and gap_equal > 0.003))
        and equal_ret < 0
        and amount_ret < 0
        and (down_share or 0) >= 0.55
        and (top_turnover_ret or 0) < 0
        and (top10 or 0) >= 0.60
    ):
        state = "masked_distribution"
    elif index_ret < 0 and equal_ret < 0 and amount_ret < 0 and (down_share or 0) > (up_share or 0):
        state = "broad_decline"
    elif index_ret > 0 and equal_ret > 0 and amount_ret > 0 and (up_share or 0) > (down_share or 0) and (top10 or 0) <= 0.60:
        state = "broad_confirmed_rise"
    elif (
        index_ret > 0
        and (top10 or 0) >= 0.70
        and (
            (weighted_amount_ratio is not None and weighted_amount_ratio < float(config["turnover"]["low_volume_ratio"]))
            or (top10_amount_ratio is not None and top10_amount_ratio < float(config["turnover"]["low_volume_ratio"]))
            or (low_volume_lift or 0) >= 0.50
        )
        and (gap_equal or 0) >= 0.003
        and (heavy_selling or 0) < 0.25
        and (down_share or 0) < 0.55
    ):
        state = "thin_weighted_lift"
    elif (
        index_ret > 0
        and (top10 or 0) >= 0.60
        and ((weighted_amount_ratio or 0) >= 1.0 or (top10_amount_ratio or 0) >= 1.0)
        and (down_share or 0) < 0.55
        and (top_turnover_ret is None or top_turnover_ret >= -0.003)
    ):
        state = "concentrated_but_supported"
    else:
        state = "mixed_divergence"
    supporting = [
        f"指数收益={index_ret:+.2%}" if index_ret is not None else "指数收益缺失",
        f"等权收益={equal_ret:+.2%}" if equal_ret is not None else "等权收益缺失",
        f"前10正贡献占比={top10:.1%}" if top10 is not None else "前10正贡献占比缺失",
        f"下跌成交占比={down_share:.1%}" if down_share is not None else "下跌成交占比缺失",
    ]
    contradicting = []
    if "contribution_reconciliation_failed" in (row.get("data_quality_flags") or []):
        contradicting.append("估算贡献与官方指数收益偏差较大")
    if row.get("index_weight_is_approximate"):
        contradicting.append("指数权重为近似口径")
    confidence = "high"
    if state == UNKNOWN:
        confidence = UNKNOWN
    elif row.get("index_weight_is_approximate") or "contribution_reconciliation_failed" in (row.get("data_quality_flags") or []):
        confidence = "low"
    elif row.get("scores", {}).get("index_lift_quality") is None:
        confidence = "medium"
    row["state"] = state
    row["state_cn"] = STATE_CN.get(state, "数据不足")
    row["supporting_evidence"] = supporting
    row["contradicting_evidence"] = contradicting
    row["confidence"] = confidence


def _latest_package(rows: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    if not rows:
        return {}
    latest = dict(rows[-1])
    recent_days = int(config["display"]["recent_days"])
    latest["history"] = [
        {
            "trade_date": row.get("trade_date"),
            "state": row.get("state"),
            "state_cn": row.get("state_cn"),
            "index_return": row.get("index_return"),
            "equal_weight_return": row.get("equal_weight_return"),
            "amount_weighted_return": row.get("amount_weighted_return"),
            "index_equal_weight_gap": row.get("index_equal_weight_gap"),
            "index_amount_weighted_gap": row.get("index_amount_weighted_gap"),
            "top_10_positive_contribution_share": row.get("top_10_positive_contribution_share"),
            "top_10_signed_index_contribution": row.get("top_10_signed_index_contribution"),
            "top_10_signed_index_return_share": row.get("top_10_signed_index_return_share"),
            "top10_contributor_amount_share": row.get("top10_contributor_amount_share"),
            "top20_turnover_amount_share": row.get("top20_turnover_amount_share"),
            "contribution_weighted_amount_ratio_20d": row.get("contribution_weighted_amount_ratio_20d"),
            "down_amount_share": row.get("down_amount_share"),
            "heavy_selling_amount_share": row.get("heavy_selling_amount_share"),
            "top_turnover_20pct_return": row.get("top_turnover_20pct_return"),
            "index_lift_quality": (row.get("scores") or {}).get("index_lift_quality"),
            "index_masking_risk": (row.get("scores") or {}).get("index_masking_risk"),
        }
        for row in rows[-recent_days:]
    ]
    return _serialize(latest)


def build_index_lift_structure(
    *,
    primary_symbol: str,
    close: pd.DataFrame,
    amount: pd.DataFrame,
    metadata: pd.DataFrame,
    index_frames: dict[str, pd.DataFrame],
    index_member_frames: dict[str, pd.DataFrame] | None = None,
    as_of: Any | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build index lift quality diagnostics for supported A-share indices."""
    cfg = _deep_merge(DEFAULT_CONFIG, config or {})
    if not bool(cfg.get("enabled", True)):
        return {"state": UNKNOWN, "state_cn": STATE_CN[UNKNOWN], "enabled": False, "by_symbol": {}, "history": []}
    close = close.copy()
    close.index = pd.to_datetime(close.index, errors="coerce")
    close = close.loc[close.index.notna()].sort_index()
    cutoff = pd.to_datetime(as_of, errors="coerce") if as_of is not None else close.index.max()
    if pd.isna(cutoff) or close.empty:
        return {"state": UNKNOWN, "state_cn": STATE_CN[UNKNOWN], "by_symbol": {}, "history": [], "data_quality_flags": ["missing_stock_universe"]}
    close = close.loc[close.index <= cutoff]
    amount = amount.reindex(index=close.index, columns=close.columns).copy()
    dates = pd.DatetimeIndex(close.index)
    stock_returns = close.pct_change(fill_method=None)
    amount_ma20 = amount.rolling(20, min_periods=20).mean()
    amount_ratio = amount / amount_ma20
    rolling_low20 = close.rolling(20, min_periods=20).min().shift(1)
    new_low20 = close < rolling_low20
    member_frames = _prepare_member_frames(index_member_frames)
    name_map = _stock_name_map(metadata)
    ind_map = _industry_map(metadata)
    by_symbol: dict[str, Any] = {}
    fallback_caches = {
        layer["symbol"]: _fallback_weights(layer=layer, close=close, metadata=metadata)
        for layer in SUPPORTED_INDICES
    }
    for layer in SUPPORTED_INDICES:
        index_returns = _index_return_series(index_frames.get(layer["symbol"]), dates)
        rows: list[dict[str, Any]] = []
        lookback_rows = int(cfg["min_history"]) + int(cfg["display"]["recent_days"]) + 5
        start_position = max(1, len(dates) - lookback_rows)
        selected_dates = list(dates[start_position:])
        latest_date = selected_dates[-1] if selected_dates else None
        for date in selected_dates:
            rows.append(
                _row_for_date(
                    layer=layer,
                    date=pd.Timestamp(date),
                    close=close,
                    amount=amount,
                    amount_ma20=amount_ma20,
                    amount_ratio=amount_ratio,
                    new_low20=new_low20,
                    stock_returns=stock_returns,
                    index_returns=index_returns,
                    member_frames=member_frames,
                    metadata=metadata,
                    name_map=name_map,
                    industry_map=ind_map,
                    config=cfg,
                    include_details=latest_date is not None and pd.Timestamp(date) == pd.Timestamp(latest_date),
                    fallback_cache=fallback_caches.get(layer["symbol"]),
                )
            )
        _apply_scores(rows, cfg)
        for row in rows:
            _classify_row(row, cfg)
        package = _latest_package(rows, cfg)
        if package:
            by_symbol[layer["symbol"]] = package
    preferred = str(primary_symbol or "").upper()
    if preferred not in by_symbol:
        preferred = "000300.SH" if "000300.SH" in by_symbol else next(iter(by_symbol), "")
    primary = dict(by_symbol.get(preferred) or {})
    if not primary:
        return {
            "state": UNKNOWN,
            "state_cn": STATE_CN[UNKNOWN],
            "by_symbol": by_symbol,
            "history": [],
            "available_indices": list(by_symbol),
            "data_quality_flags": ["missing_index_lift_structure"],
        }
    primary["as_of_date"] = pd.Timestamp(close.index[-1]).strftime("%Y-%m-%d")
    primary["available_indices"] = [
        {"symbol": symbol, "index_name": item.get("index_name"), "state": item.get("state"), "state_cn": item.get("state_cn")}
        for symbol, item in by_symbol.items()
    ]
    primary["by_symbol"] = by_symbol
    primary["index_lift_structure"] = True
    return _serialize(primary)
