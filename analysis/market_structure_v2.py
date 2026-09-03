"""Market-structure description system v2.

The v2 layer extends the existing index market-structure facts.  It is a
deterministic, point-in-time-aware description system: it does not forecast
returns and it has no dependency on strategy, position, order, risk-gate, or
LLM modules.
"""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from analysis.index_lift_structure import build_index_lift_structure
from data.market_benchmark import (
    MARKET_BENCHMARK_QUALITY_FLAG,
    MARKET_BENCHMARK_SOURCE,
    MARKET_BENCHMARK_SYMBOL,
)
from analysis.market_structure_state_v2 import (
    UNKNOWN,
    StateTracker,
    StateTrackerConfig,
    classify_concentration,
    classify_heat_phase,
    classify_ice_phase,
    classify_layer_breadth,
    classify_leadership_quality,
    classify_liquidity,
    classify_repair,
    classify_return_distribution,
    classify_risk_phase,
    classify_rotation,
    evidence_block,
    finite,
    merge_state_segments,
)


SCHEMA_VERSION = "market_structure_v2"
ALGORITHM_VERSION = "2.0.0"
DEFAULT_HISTORY_DAYS = 60

INDEX_LAYERS: tuple[dict[str, Any], ...] = (
    {"name": "上证50", "symbol": "000016.SH", "member_codes": ("000016.SH",)},
    {"name": "沪深300", "symbol": "000300.SH", "member_codes": ("000300.SH", "399300.SZ")},
    {"name": "中证500", "symbol": "000905.SH", "member_codes": ("000905.SH",)},
    {"name": "中证1000", "symbol": "000852.SH", "member_codes": ("000852.SH",)},
    {"name": "中证2000", "symbol": "932000.CSI", "member_codes": ("932000.CSI",)},
    {"name": "创业板", "symbol": "399006.SZ", "member_codes": ("399006.SZ",), "fallback_market": "创业板"},
    {"name": "科创50", "symbol": "000688.SH", "member_codes": ("000688.SH",), "fallback_market": "科创板"},
    {"name": "深市", "symbol": "399001.SZ", "member_codes": ("399001.SZ",), "fallback_exchange": "SZSE"},
)


def _json_default(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_index_member_frames(meta_dir: str | Path) -> dict[str, pd.DataFrame]:
    """Load cached index-weight snapshots without downloading or changing them."""
    root = Path(meta_dir) / "index_members"
    frames: dict[str, pd.DataFrame] = {}
    if not root.exists():
        return frames
    for path in sorted(root.glob("*.csv")):
        try:
            frame = pd.read_csv(
                path,
                dtype={"index_code": str, "con_code": str, "trade_date": str},
            )
        except (OSError, ValueError, pd.errors.ParserError):
            continue
        if frame.empty or not {"con_code", "trade_date"}.issubset(frame.columns):
            continue
        frame = frame.copy()
        frame["con_code"] = frame["con_code"].astype(str).str.upper()
        frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
        frame["weight"] = pd.to_numeric(frame.get("weight"), errors="coerce")
        frame = frame.dropna(subset=["con_code", "trade_date"]).sort_values(["trade_date", "con_code"])
        if not frame.empty:
            frames[path.stem.upper()] = frame.reset_index(drop=True)
    return frames


def _prepare_member_frames(frames: dict[str, pd.DataFrame] | None, as_of: pd.Timestamp) -> dict[str, pd.DataFrame]:
    prepared: dict[str, pd.DataFrame] = {}
    for code, source in (frames or {}).items():
        if source is None or source.empty or not {"trade_date", "con_code"}.issubset(source.columns):
            continue
        frame = source.copy()
        frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
        frame["con_code"] = frame["con_code"].astype(str).str.upper()
        frame["weight"] = pd.to_numeric(frame.get("weight"), errors="coerce")
        frame = frame.dropna(subset=["trade_date", "con_code"])
        frame = frame[frame["trade_date"] <= as_of].sort_values(["trade_date", "con_code"])
        if not frame.empty:
            prepared[str(code).upper()] = frame.reset_index(drop=True)
    return prepared


def _member_snapshot(frame: pd.DataFrame | None, date: pd.Timestamp) -> tuple[list[str], pd.Series | None, str | None]:
    if frame is None or frame.empty:
        return [], None, None
    eligible = frame[frame["trade_date"] <= date]
    if eligible.empty:
        return [], None, None
    snapshot_date = eligible["trade_date"].max()
    snapshot = eligible[eligible["trade_date"] == snapshot_date].drop_duplicates("con_code", keep="last")
    symbols = snapshot["con_code"].astype(str).str.upper().tolist()
    weights = pd.to_numeric(snapshot["weight"], errors="coerce")
    if weights.notna().any() and float(weights.fillna(0).sum()) > 0:
        weight_series = pd.Series(weights.to_numpy(dtype=float), index=symbols, dtype="float64")
        weight_series = weight_series / weight_series.sum()
    else:
        weight_series = None
    return symbols, weight_series, pd.Timestamp(snapshot_date).strftime("%Y-%m-%d")


def _metadata_symbols(
    metadata: pd.DataFrame,
    columns: pd.Index,
    *,
    market: str | None = None,
    exchange: str | None = None,
) -> list[str]:
    if metadata.empty or "ts_code" not in metadata.columns:
        return []
    frame = metadata.copy()
    frame["ts_code"] = frame["ts_code"].astype(str).str.upper()
    mask = frame["ts_code"].isin(columns)
    if market and "market" in frame.columns:
        mask &= frame["market"].astype(str).eq(market)
    if exchange and "exchange" in frame.columns:
        mask &= frame["exchange"].astype(str).str.upper().eq(exchange.upper())
    if "name" in frame.columns:
        mask &= ~frame["name"].astype(str).str.contains("ST", case=False, na=False)
    return sorted(frame.loc[mask, "ts_code"].dropna().unique().tolist())


def _source_date(frame: pd.DataFrame | None) -> pd.Timestamp | None:
    if frame is None or frame.empty:
        return None
    date_column = "date" if "date" in frame.columns else "trade_date" if "trade_date" in frame.columns else None
    if date_column is None:
        return None
    value = pd.to_datetime(frame[date_column], errors="coerce").max()
    return value if pd.notna(value) else None


def _freshness_entry(
    *,
    source: str,
    data_date: pd.Timestamp | None,
    as_of: pd.Timestamp,
    trading_calendar: pd.DatetimeIndex,
    point_in_time: bool,
    available: bool = True,
    stale_after_trading_days: int = 0,
) -> dict[str, Any]:
    if not available or data_date is None:
        return {
            "source": source,
            "data_date": None,
            "as_of": as_of.strftime("%Y-%m-%d"),
            "as_of_date": as_of.strftime("%Y-%m-%d"),
            "lag_calendar_days": None,
            "lag_trading_days": None,
            "status": "missing",
            "point_in_time": point_in_time,
        }
    date = pd.Timestamp(data_date).normalize()
    calendar = pd.DatetimeIndex(trading_calendar).normalize().unique().sort_values()
    lag_trading = int(((calendar > date) & (calendar <= as_of.normalize())).sum())
    lag_calendar = max(0, int((as_of.normalize() - date).days))
    status = "fresh" if lag_trading <= stale_after_trading_days else "stale"
    return {
        "source": source,
        "data_date": date.strftime("%Y-%m-%d"),
        "as_of": as_of.strftime("%Y-%m-%d"),
        "as_of_date": as_of.strftime("%Y-%m-%d"),
        "lag_calendar_days": lag_calendar,
        "lag_trading_days": lag_trading,
        "status": status,
        "point_in_time": point_in_time,
    }


def build_source_freshness(
    *,
    close: pd.DataFrame,
    amount: pd.DataFrame,
    metadata: pd.DataFrame,
    index_frames: dict[str, pd.DataFrame],
    index_member_frames: dict[str, pd.DataFrame] | None = None,
    ths_index_frames: dict[str, pd.DataFrame],
    style_proxy_symbols: set[str] | None = None,
    industry_proxy_symbols: set[str] | None = None,
    as_of: pd.Timestamp,
) -> dict[str, dict[str, Any]]:
    calendar = pd.DatetimeIndex(close.index)
    entries: dict[str, dict[str, Any]] = {}
    universe_date = pd.to_datetime(close.dropna(how="all").index, errors="coerce").max() if not close.empty else None
    amount_date = pd.to_datetime(amount.dropna(how="all").index, errors="coerce").max() if not amount.empty else None
    entries["stock_universe"] = _freshness_entry(
        source="local_stock_daily", data_date=universe_date, as_of=as_of,
        trading_calendar=calendar, point_in_time=False, available=not close.empty,
    )
    entries["amount"] = _freshness_entry(
        source="local_stock_daily.amount", data_date=amount_date, as_of=as_of,
        trading_calendar=calendar, point_in_time=False, available=not amount.empty,
    )
    for layer in INDEX_LAYERS:
        frame = index_frames.get(layer["symbol"])
        entries[f"index:{layer['symbol']}"] = _freshness_entry(
            source="Tushare index_daily", data_date=_source_date(frame), as_of=as_of,
            trading_calendar=calendar, point_in_time=True, available=frame is not None and not frame.empty,
        )
    member_codes: set[str] = set()
    available_member_codes = {str(code).upper() for code in (index_member_frames or {})}
    for layer in INDEX_LAYERS:
        alternatives = [str(code).upper() for code in layer.get("member_codes", ())]
        selected = next(
            (code for code in alternatives if code in available_member_codes),
            alternatives[0] if alternatives else None,
        )
        if selected:
            member_codes.add(selected)
    for member_code in sorted(member_codes):
        frame = (index_member_frames or {}).get(member_code)
        entries[f"index_members:{member_code}"] = _freshness_entry(
            source=f"Tushare index_weight:{member_code}",
            data_date=_source_date(frame),
            as_of=as_of,
            trading_calendar=calendar,
            point_in_time=True,
            available=frame is not None and not frame.empty,
            # Index weights are low-frequency snapshots rather than daily quotes.
            stale_after_trading_days=120,
        )
    all_a = index_frames.get(MARKET_BENCHMARK_SYMBOL)
    entries["all_a_index"] = _freshness_entry(
        source=MARKET_BENCHMARK_SOURCE, data_date=_source_date(all_a), as_of=as_of,
        trading_calendar=calendar, point_in_time=True, available=all_a is not None and not all_a.empty,
    )
    all_ths_symbols = {str(symbol).upper() for symbol in ths_index_frames}
    style_symbols = (
        {str(symbol).upper() for symbol in style_proxy_symbols}
        if style_proxy_symbols is not None
        else all_ths_symbols
    )
    industry_symbols = (
        {str(symbol).upper() for symbol in industry_proxy_symbols}
        if industry_proxy_symbols is not None
        else all_ths_symbols
    )

    def grouped_dates(symbols: set[str]) -> list[pd.Timestamp]:
        dates = [
            _source_date(ths_index_frames.get(symbol))
            for symbol in sorted(symbols)
            if symbol in ths_index_frames
        ]
        return [date for date in dates if date is not None]

    style_dates = grouped_dates(style_symbols)
    industry_dates = grouped_dates(industry_symbols)
    entries["style_proxies"] = _freshness_entry(
        source="Tushare ths_daily style proxies",
        data_date=min(style_dates) if style_dates else None,
        as_of=as_of, trading_calendar=calendar, point_in_time=True,
        available=bool(style_dates),
    )
    style_available_count = sum(symbol in ths_index_frames for symbol in style_symbols)
    entries["style_proxies"].update(
        {
            "expected_source_count": len(style_symbols),
            "available_source_count": style_available_count,
            "coverage": finite(style_available_count / len(style_symbols)) if style_symbols else None,
        }
    )
    if style_symbols and style_available_count < len(style_symbols):
        entries["style_proxies"]["limitation"] = "some configured style proxy series are unavailable"
    entries["industry_quotes"] = _freshness_entry(
        source="Tushare ths_daily industry indices",
        data_date=min(industry_dates) if industry_dates else None,
        as_of=as_of, trading_calendar=calendar, point_in_time=True,
        available=bool(industry_dates),
    )
    industry_available_count = sum(symbol in ths_index_frames for symbol in industry_symbols)
    entries["industry_quotes"].update(
        {
            "expected_source_count": len(industry_symbols),
            "available_source_count": industry_available_count,
            "coverage": finite(industry_available_count / len(industry_symbols)) if industry_symbols else None,
        }
    )
    if industry_symbols and industry_available_count < len(industry_symbols):
        entries["industry_quotes"]["limitation"] = "some configured industry index series are unavailable"
    entries["industry_classification"] = {
        **_freshness_entry(
            source="current stocks.csv industry classification", data_date=as_of if not metadata.empty else None,
            as_of=as_of, trading_calendar=calendar, point_in_time=False, available=not metadata.empty,
        ),
        "limitation": "current classification is used for historical rows",
    }
    entries["price_limit_rules"] = {
        **_freshness_entry(
            source="board-aware approximation", data_date=as_of, as_of=as_of,
            trading_calendar=calendar, point_in_time=False, available=True,
        ),
        "limitation": "historical ST and IPO no-limit days are unavailable",
    }
    entries["valuation"] = _freshness_entry(
        source="reserved daily_basic interface", data_date=None, as_of=as_of,
        trading_calendar=calendar, point_in_time=True, available=False,
    )
    entries["external"] = _freshness_entry(
        source="reserved external context interface", data_date=None, as_of=as_of,
        trading_calendar=calendar, point_in_time=True, available=False,
    )
    return entries


def _serialize_frame(frame: pd.DataFrame, tail: int | None = None) -> list[dict[str, Any]]:
    work = frame.tail(tail).copy() if tail else frame.copy()
    if isinstance(work.index, pd.DatetimeIndex) and "trade_date" not in work.columns:
        work.insert(0, "trade_date", work.index.strftime("%Y-%m-%d"))
    records: list[dict[str, Any]] = []
    for row in work.replace([np.inf, -np.inf], np.nan).to_dict("records"):
        item: dict[str, Any] = {}
        for key, value in row.items():
            if pd.isna(value):
                item[str(key)] = None
            elif isinstance(value, pd.Timestamp):
                item[str(key)] = value.strftime("%Y-%m-%d")
            elif isinstance(value, np.generic):
                item[str(key)] = value.item()
            else:
                item[str(key)] = value
        records.append(item)
    return records


def _rolling_percentile(series: pd.Series, window: int = 756, min_periods: int = 60) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    return values.rolling(window, min_periods=min_periods).apply(
        lambda data: float(np.mean(data <= data[-1])) if np.isfinite(data[-1]) else np.nan,
        raw=True,
    )


def _top_fraction_share(values: pd.Series, fraction: float = 0.10, positive_only: bool = False) -> float | None:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if positive_only:
        clean = clean[clean > 0]
    if clean.empty:
        return None
    denominator = float(clean.sum())
    if denominator <= 0:
        return None
    count = max(1, int(np.ceil(len(clean) * fraction)))
    return float(clean.nlargest(count).sum() / denominator)


def _top_n_share(values: pd.Series, count: int, positive_only: bool = False) -> float | None:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if positive_only:
        clean = clean[clean > 0]
    if clean.empty:
        return None
    denominator = float(clean.sum())
    if denominator <= 0:
        return None
    return float(clean.nlargest(min(count, len(clean))).sum() / denominator)


def _layer_row(
    *,
    date: pd.Timestamp,
    symbols: list[str],
    close: pd.DataFrame,
    amount: pd.DataFrame,
    daily: pd.DataFrame,
    ma5: pd.DataFrame,
    ma10: pd.DataFrame,
    ma20: pd.DataFrame,
    ma60: pd.DataFrame,
    ma200: pd.DataFrame,
    high5: pd.DataFrame,
    low5: pd.DataFrame,
    high10: pd.DataFrame,
    low10: pd.DataFrame,
    high20: pd.DataFrame,
    low20: pd.DataFrame,
    high60: pd.DataFrame,
    low60: pd.DataFrame,
    total_amount: pd.Series,
) -> dict[str, Any]:
    selected = [symbol for symbol in symbols if symbol in close.columns]
    base = {
        "trade_date": date.strftime("%Y-%m-%d"),
        "member_count": len(symbols),
        "available_member_count": len(selected),
    }
    if not selected or date not in close.index:
        return {
            **base,
            "valid_count": 0,
            "advance_count": 0,
            "decline_count": 0,
            "flat_count": 0,
            "coverage": None,
        }
    returns = daily.loc[date, selected]
    traded = amount.loc[date, selected].gt(0) & amount.loc[date, selected].notna()
    valid = returns.notna() & traded
    values = returns.where(valid)
    valid_count = int(valid.sum())
    denominator = float(valid_count) if valid_count else np.nan

    def ratio(condition: pd.Series, eligible: pd.Series) -> float | None:
        count = int(eligible.sum())
        return finite((condition & eligible).sum() / count) if count else None

    valid_price = close.loc[date, selected].notna() & traded
    ma5_valid = valid_price & ma5.loc[date, selected].notna()
    ma10_valid = valid_price & ma10.loc[date, selected].notna()
    ma20_valid = valid_price & ma20.loc[date, selected].notna()
    ma60_valid = valid_price & ma60.loc[date, selected].notna()
    ma200_valid = valid_price & ma200.loc[date, selected].notna()
    h5_valid = valid_price & high5.loc[date, selected].notna()
    h10_valid = valid_price & high10.loc[date, selected].notna()
    h20_valid = valid_price & high20.loc[date, selected].notna()
    h60_valid = valid_price & high60.loc[date, selected].notna()
    amount_value = finite(amount.loc[date, selected].where(traded).sum(min_count=1))
    total_value = finite(total_amount.loc[date])
    directional_count = int((values > 0).sum() + (values < 0).sum())
    quantiles = values.dropna().quantile([0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95]) if valid_count else pd.Series(dtype=float)
    return {
        **base,
        "valid_count": valid_count,
        "advance_count": int((values > 0).sum()),
        "decline_count": int((values < 0).sum()),
        "flat_count": int((values == 0).sum()),
        "coverage": finite(valid_count / len(symbols)) if symbols else None,
        "advance_ratio": finite((values > 0).sum() / denominator),
        "decline_ratio": finite((values < 0).sum() / denominator),
        "median_return_1d": finite(values.median()),
        "equal_weight_return_1d": finite(values.mean()),
        "q05": finite(quantiles.get(0.05)),
        "q10": finite(quantiles.get(0.10)),
        "q25": finite(quantiles.get(0.25)),
        "median": finite(quantiles.get(0.50)),
        "q75": finite(quantiles.get(0.75)),
        "q90": finite(quantiles.get(0.90)),
        "q95": finite(quantiles.get(0.95)),
        "return_std": finite(values.std(ddof=0)),
        "return_iqr": finite(quantiles.get(0.75) - quantiles.get(0.25)) if valid_count else None,
        "return_skew": finite(values.skew()),
        "pct_above_ma5": ratio(close.loc[date, selected] > ma5.loc[date, selected], ma5_valid),
        "pct_above_ma10": ratio(close.loc[date, selected] > ma10.loc[date, selected], ma10_valid),
        "pct_above_ma20": ratio(close.loc[date, selected] > ma20.loc[date, selected], ma20_valid),
        "pct_above_ma60": ratio(close.loc[date, selected] > ma60.loc[date, selected], ma60_valid),
        "pct_above_ma200": ratio(close.loc[date, selected] > ma200.loc[date, selected], ma200_valid),
        "new_high_5_ratio": ratio(close.loc[date, selected] > high5.loc[date, selected], h5_valid),
        "new_low_5_ratio": ratio(close.loc[date, selected] < low5.loc[date, selected], h5_valid),
        "new_high_10_ratio": ratio(close.loc[date, selected] > high10.loc[date, selected], h10_valid),
        "new_low_10_ratio": ratio(close.loc[date, selected] < low10.loc[date, selected], h10_valid),
        "new_high_20_ratio": ratio(close.loc[date, selected] > high20.loc[date, selected], h20_valid),
        "new_low_20_ratio": ratio(close.loc[date, selected] < low20.loc[date, selected], h20_valid),
        "new_high_60_ratio": ratio(close.loc[date, selected] > high60.loc[date, selected], h60_valid),
        "new_low_60_ratio": ratio(close.loc[date, selected] < low60.loc[date, selected], h60_valid),
        "decline_gt_3_ratio": finite((values <= -0.03).sum() / denominator),
        "decline_gt_5_ratio": finite((values <= -0.05).sum() / denominator),
        "amount": amount_value,
        "turnover_share": finite(amount_value / total_value) if amount_value is not None and total_value else None,
        "normalized_ad": finite(((values > 0).sum() - (values < 0).sum()) / directional_count)
        if directional_count else None,
    }


def build_layered_breadth(
    *,
    close: pd.DataFrame,
    amount: pd.DataFrame,
    metadata: pd.DataFrame,
    index_member_frames: dict[str, pd.DataFrame],
    index_frames: dict[str, pd.DataFrame],
    style_symbol_groups: dict[str, list[str]],
    source_freshness: dict[str, dict[str, Any]],
    history_days: int,
) -> tuple[dict[str, Any], list[str]]:
    daily = close.pct_change(fill_method=None)
    ma5 = close.rolling(5, min_periods=5).mean()
    ma10 = close.rolling(10, min_periods=10).mean()
    ma20 = close.rolling(20, min_periods=20).mean()
    ma60 = close.rolling(60, min_periods=60).mean()
    ma200 = close.rolling(200, min_periods=200).mean()
    high5 = close.rolling(5, min_periods=5).max().shift(1)
    low5 = close.rolling(5, min_periods=5).min().shift(1)
    high10 = close.rolling(10, min_periods=10).max().shift(1)
    low10 = close.rolling(10, min_periods=10).min().shift(1)
    high20 = close.rolling(20, min_periods=20).max().shift(1)
    low20 = close.rolling(20, min_periods=20).min().shift(1)
    high60 = close.rolling(60, min_periods=60).max().shift(1)
    low60 = close.rolling(60, min_periods=60).min().shift(1)
    total_amount = amount.sum(axis=1, min_count=1)
    dates = pd.DatetimeIndex(close.index[-max(history_days + 20, 80):])
    output: dict[str, Any] = {}
    quality_flags: list[str] = []

    layer_specs: list[dict[str, Any]] = list(INDEX_LAYERS)
    layer_specs.append({"name": "全A", "symbol": MARKET_BENCHMARK_SYMBOL, "all_a": True})
    for style_name, symbols in style_symbol_groups.items():
        layer_specs.append({"name": style_name, "symbol": None, "fixed_symbols": symbols, "style": True})

    for spec in layer_specs:
        member_frame = None
        member_code = None
        for code in spec.get("member_codes", ()):
            if code in index_member_frames:
                member_frame = index_member_frames[code]
                member_code = code
                break
        fixed_symbols: list[str] = []
        point_in_time = member_frame is not None
        membership_source = f"Tushare index_weight:{member_code}" if member_code else None
        if spec.get("all_a"):
            fixed_symbols = list(close.columns)
            point_in_time = False
            membership_source = "current local stock universe"
        elif spec.get("fixed_symbols") is not None:
            fixed_symbols = [symbol for symbol in spec["fixed_symbols"] if symbol in close.columns]
            point_in_time = False
            membership_source = "current stocks.csv industry basket"
        elif member_frame is None:
            if spec.get("fallback_market") or spec.get("fallback_exchange"):
                fixed_symbols = _metadata_symbols(
                    metadata,
                    close.columns,
                    market=spec.get("fallback_market"),
                    exchange=spec.get("fallback_exchange"),
                )
            else:
                fixed_symbols = []
            membership_source = "current stocks.csv fallback" if fixed_symbols else "missing"
            quality_flags.append(
                f"composition_not_point_in_time:{spec['name']}"
                if fixed_symbols else f"missing_index_membership:{spec['name']}"
            )
        rows: list[dict[str, Any]] = []
        snapshot_dates: list[str] = []
        for date in dates:
            if member_frame is not None:
                symbols, _weights, snapshot_date = _member_snapshot(member_frame, date)
                if snapshot_date:
                    snapshot_dates.append(snapshot_date)
            else:
                symbols = fixed_symbols
            row = _layer_row(
                date=date,
                symbols=symbols,
                close=close,
                amount=amount,
                daily=daily,
                ma5=ma5,
                ma10=ma10,
                ma20=ma20,
                ma60=ma60,
                ma200=ma200,
                high5=high5,
                low5=low5,
                high10=high10,
                low10=low10,
                high20=high20,
                low20=low20,
                high60=high60,
                low60=low60,
                total_amount=total_amount,
            )
            rows.append(row)
        history = pd.DataFrame(rows)
        if history.empty:
            tracker = StateTracker().track([], [], dimension=f"layered_breadth:{spec['name']}")
            latest: dict[str, Any] = {}
        else:
            ad_series = (
                pd.to_numeric(history["normalized_ad"], errors="coerce")
                if "normalized_ad" in history.columns else pd.Series(np.nan, index=history.index)
            )
            turnover_series = (
                pd.to_numeric(history["turnover_share"], errors="coerce")
                if "turnover_share" in history.columns else pd.Series(np.nan, index=history.index)
            )
            history["ad_5d"] = ad_series.rolling(5, min_periods=5).sum()
            history["ad_20d"] = ad_series.rolling(20, min_periods=20).sum()
            history["turnover_share_change_20d"] = turnover_series - turnover_series.shift(20)
            raw_states = [classify_layer_breadth(row) for _, row in history.iterrows()]
            universe_fresh = source_freshness.get("stock_universe", {}).get("status") == "fresh"
            if not universe_fresh:
                raw_states[-1] = UNKNOWN
            history["raw_state"] = raw_states
            tracker = StateTracker(
                StateTrackerConfig(min_confirm_days=2, min_hold_days=2, extreme_states=("broad_weakness",))
            ).track(history["trade_date"], raw_states, dimension=f"layered_breadth:{spec['name']}")
            history["state"] = [item["state"] for item in tracker["history"]]
            latest = history.iloc[-1].replace({np.nan: None}).to_dict()
            latest["universe"] = spec["name"]
            latest["effective_count"] = latest.get("valid_count")
            latest["nhnl_20d"] = (
                finite(latest.get("new_high_20_ratio") - latest.get("new_low_20_ratio"))
                if latest.get("new_high_20_ratio") is not None and latest.get("new_low_20_ratio") is not None else None
            )
            latest["breadth_state_today"] = str(history.iloc[-1].get("raw_state") or UNKNOWN)
            latest["breadth_state_5d"] = (
                "strong" if finite(latest.get("ad_5d")) is not None and float(latest["ad_5d"]) > 0
                else "weak" if finite(latest.get("ad_5d")) is not None and float(latest["ad_5d"]) < 0 else UNKNOWN
            )
            latest["breadth_state_20d"] = tracker["state"]
        quote_freshness = source_freshness.get(f"index:{spec.get('symbol')}") if spec.get("symbol") else None
        membership_freshness = (
            source_freshness.get(f"index_members:{member_code}")
            if member_code else None
        )
        output[spec["name"]] = {
            "name": spec["name"],
            "symbol": spec.get("symbol"),
            "membership_source": membership_source,
            "membership_snapshot_date": max(snapshot_dates) if snapshot_dates else None,
            "composition_point_in_time": point_in_time,
            "confidence_limited": not point_in_time,
            "confidence": "unknown" if not latest else "high" if point_in_time else "limited",
            "index_quote_freshness": quote_freshness,
            "membership_freshness": membership_freshness,
            "latest": latest,
            "state": tracker["state"],
            "state_tracker": {key: value for key, value in tracker.items() if key != "history"},
            "history": _serialize_frame(history, history_days) if not history.empty else [],
        }
    return output, sorted(set(quality_flags))


def _weighted_contribution_metrics(
    returns: pd.Series,
    weights: pd.Series | None,
) -> dict[str, Any]:
    empty = {
        "weighted_return_1d": None,
        "top10_index_positive_contribution_share": None,
        "top20_index_positive_contribution_share": None,
        "top50_index_positive_contribution_share": None,
        "top10_index_signed_contribution": None,
        "top20_index_signed_contribution": None,
        "top50_index_signed_contribution": None,
        "weight_hhi": None,
        "weight_member_count": 0,
    }
    if weights is None or weights.empty:
        return empty
    common = weights.index.intersection(returns.dropna().index)
    if common.empty:
        return empty
    normalized = weights.reindex(common).dropna()
    normalized = normalized[normalized > 0]
    if normalized.empty:
        return empty
    normalized = normalized / normalized.sum()
    contributions = returns.reindex(normalized.index) * normalized
    positive = contributions[contributions > 0]
    positive_total = float(positive.sum()) if not positive.empty else 0.0
    result = dict(empty)
    result.update(
        {
            "weighted_return_1d": finite(contributions.sum()),
            "weight_hhi": finite((normalized ** 2).sum()),
            "weight_member_count": int(len(normalized)),
        }
    )
    for count in (10, 20, 50):
        result[f"top{count}_index_positive_contribution_share"] = (
            finite(positive.nlargest(min(count, len(positive))).sum() / positive_total)
            if positive_total > 0 else None
        )
        result[f"top{count}_index_signed_contribution"] = finite(
            contributions.reindex(contributions.abs().nlargest(min(count, len(contributions))).index).sum()
        )
    return result


def build_concentration_analysis(
    *,
    primary_symbol: str,
    close: pd.DataFrame,
    amount: pd.DataFrame,
    industry_groups: dict[str, list[str]],
    index_member_frames: dict[str, pd.DataFrame],
    source_freshness: dict[str, dict[str, Any]],
    history_days: int,
) -> tuple[dict[str, Any], list[str]]:
    dates = pd.DatetimeIndex(close.index[-min(len(close), 816):])
    daily = close.pct_change(fill_method=None).reindex(dates)
    daily_amount = amount.reindex(dates)
    valid = daily.notna() & daily_amount.notna() & daily_amount.gt(0)
    industry_returns = pd.DataFrame(index=dates)
    industry_amounts = pd.DataFrame(index=dates)
    for industry, symbols in industry_groups.items():
        selected = [symbol for symbol in symbols if symbol in close.columns]
        if not selected:
            continue
        industry_returns[industry] = daily[selected].where(valid[selected]).mean(axis=1, skipna=True)
        industry_amounts[industry] = daily_amount[selected].where(daily_amount[selected].gt(0)).sum(axis=1, min_count=1)

    member_priority: list[str] = [primary_symbol.upper()]
    if primary_symbol.upper() == "000300.SH":
        member_priority.append("399300.SZ")
    member_priority.extend(["000300.SH", "399300.SZ"])
    member_code = next((code for code in member_priority if code in index_member_frames), None)
    member_frame = index_member_frames.get(member_code) if member_code else None
    quality_flags: list[str] = ["current_industry_classification_used_for_concentration_history"]
    if member_frame is None:
        quality_flags.append("weight_data_not_point_in_time")

    rows: list[dict[str, Any]] = []
    for date in dates:
        stock_returns = daily.loc[date].where(valid.loc[date]).dropna()
        stock_amount = daily_amount.loc[date].where(valid.loc[date]).dropna()
        total_amount = float(stock_amount.sum()) if not stock_amount.empty else 0.0
        symbols, weights, snapshot_date = _member_snapshot(member_frame, date)
        weighted = _weighted_contribution_metrics(stock_returns, weights)
        industry_ret = industry_returns.loc[date].dropna() if date in industry_returns.index else pd.Series(dtype=float)
        positive_industry = industry_ret[industry_ret > 0]
        positive_total = float(positive_industry.sum()) if not positive_industry.empty else 0.0
        industry_amt = industry_amounts.loc[date].dropna() if date in industry_amounts.index else pd.Series(dtype=float)
        industry_amount_total = float(industry_amt.sum()) if not industry_amt.empty else 0.0
        equal_return = finite(stock_returns.mean())
        weighted_return = weighted.get("weighted_return_1d")
        member_returns = stock_returns.reindex(symbols).dropna() if symbols else pd.Series(dtype=float)
        row = {
            "trade_date": date.strftime("%Y-%m-%d"),
            "valid_stock_count": int(len(stock_returns)),
            "weight_source": f"Tushare index_weight:{member_code}" if member_code else None,
            "weight_snapshot_date": snapshot_date,
            "weight_point_in_time": bool(weights is not None and snapshot_date is not None),
            "top_10pct_positive_all_a_contribution_share": _top_fraction_share(stock_returns, 0.10, positive_only=True),
            "top_10pct_turnover_share": finite(stock_amount.nlargest(max(1, int(np.ceil(len(stock_amount) * 0.10)))).sum() / total_amount) if total_amount > 0 else None,
            "top3_industry_positive_contribution_share": finite(positive_industry.nlargest(min(3, len(positive_industry))).sum() / positive_total) if positive_total > 0 else None,
            "top5_industry_turnover_share": finite(industry_amt.nlargest(min(5, len(industry_amt))).sum() / industry_amount_total) if industry_amount_total > 0 else None,
            "weighted_vs_equal_return_gap": finite(weighted_return - equal_return) if weighted_return is not None and equal_return is not None else None,
            "weight_stock_vs_all_a_median_gap": finite(member_returns.mean() - stock_returns.median()) if not member_returns.empty and not stock_returns.empty else None,
            **weighted,
        }
        rows.append(row)

    history = pd.DataFrame(rows)
    percentile_columns = [
        "top_10pct_positive_all_a_contribution_share",
        "top_10pct_turnover_share",
        "top3_industry_positive_contribution_share",
        "top5_industry_turnover_share",
        "weight_hhi",
    ]
    percentile_series: list[pd.Series] = []
    for column in percentile_columns:
        percentile = _rolling_percentile(history[column], window=756, min_periods=60)
        history[f"{column}_percentile"] = percentile
        percentile_series.append(percentile.rename(column))
    percentiles = pd.concat(percentile_series, axis=1)
    available_components = percentiles.notna().sum(axis=1)
    history["concentration_percentile"] = percentiles.mean(axis=1, skipna=True).where(available_components >= 3)
    history["raw_state"] = [classify_concentration(value) for value in history["concentration_percentile"]]
    if source_freshness.get("stock_universe", {}).get("status") != "fresh" and not history.empty:
        history.loc[history.index[-1], "raw_state"] = UNKNOWN
    tracker = StateTracker(
        StateTrackerConfig(min_confirm_days=2, min_hold_days=2, extreme_states=("extreme_concentration",))
    ).track(history["trade_date"], history["raw_state"], dimension="concentration")
    history["state"] = [item["state"] for item in tracker["history"]]
    latest = history.iloc[-1].replace({np.nan: None}).to_dict() if not history.empty else {}
    if not history.empty:
        latest_date = dates[-1]
        latest_returns = daily.loc[latest_date].where(valid.loc[latest_date]).dropna()
        latest_industries = industry_returns.loc[latest_date].dropna() if not industry_returns.empty else pd.Series(dtype=float)
        latest["leading_stocks"] = [
            {"symbol": str(symbol), "return_1d": finite(value)}
            for symbol, value in latest_returns.nlargest(min(10, len(latest_returns))).items()
        ]
        latest["leading_industries"] = [
            {"industry": str(industry), "return_1d": finite(value)}
            for industry, value in latest_industries.nlargest(min(5, len(latest_industries))).items()
        ]
        latest["top_20_contribution_pct"] = latest.get("top20_index_positive_contribution_share")
        latest["top_10pct_turnover_share"] = latest.get("top_10pct_turnover_share")
        latest["weighted_equal_weight_gap"] = latest.get("weighted_vs_equal_return_gap")
        latest["approximate"] = not bool(latest.get("weight_point_in_time"))
        latest["summary"] = {
            "broad_participation": "市场贡献相对分散",
            "moderate_concentration": "市场贡献中度集中",
            "high_concentration": "指数表现主要由少数权重股贡献",
            "extreme_concentration": "指数和成交贡献高度集中",
        }.get(tracker["state"], "集中度数据不足")
    return {
        "state": tracker["state"],
        "latest": latest,
        "state_tracker": {key: value for key, value in tracker.items() if key != "history"},
        "history": _serialize_frame(history, history_days),
        "method": {
            "state_thresholds": {"broad_participation": "<60%", "moderate_concentration": "60-80%", "high_concentration": "80-95%", "extreme_concentration": ">=95%"},
            "percentile_window": 756,
            "minimum_history": 60,
            "positive_contribution_definition": "share of positive cross-sectional contribution",
            "index_contribution_weight_source": f"Tushare index_weight:{member_code}" if member_code else None,
        },
    }, sorted(set(quality_flags))


def build_return_distribution(
    *,
    close: pd.DataFrame,
    amount: pd.DataFrame,
    source_freshness: dict[str, dict[str, Any]],
    history_days: int,
) -> dict[str, Any]:
    daily = close.pct_change(fill_method=None)
    valid = daily.notna() & amount.notna() & amount.gt(0)
    rows: list[dict[str, Any]] = []
    for date in close.index[-max(history_days, 60):]:
        values = pd.to_numeric(daily.loc[date].where(valid.loc[date]), errors="coerce").dropna()
        if len(values) < 20:
            rows.append({"trade_date": pd.Timestamp(date).strftime("%Y-%m-%d"), "valid_count": int(len(values))})
            continue
        quantiles = values.quantile([0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95])
        rows.append(
            {
                "trade_date": pd.Timestamp(date).strftime("%Y-%m-%d"),
                "valid_count": int(len(values)),
                "q05": finite(quantiles.loc[0.05]),
                "q10": finite(quantiles.loc[0.10]),
                "q25": finite(quantiles.loc[0.25]),
                "median": finite(quantiles.loc[0.50]),
                "q75": finite(quantiles.loc[0.75]),
                "q90": finite(quantiles.loc[0.90]),
                "q95": finite(quantiles.loc[0.95]),
                "std": finite(values.std(ddof=0)),
                "iqr": finite(quantiles.loc[0.75] - quantiles.loc[0.25]),
                "skew": finite(values.skew()),
                "up_ratio": finite((values > 0).mean()),
                "decline_gt_3_ratio": finite((values <= -0.03).mean()),
                "decline_gt_5_ratio": finite((values <= -0.05).mean()),
                "advance_gt_3_ratio": finite((values >= 0.03).mean()),
                "advance_gt_5_ratio": finite((values >= 0.05).mean()),
            }
        )
    history = pd.DataFrame(rows)
    history["raw_state"] = [classify_return_distribution(row) for _, row in history.iterrows()]
    if source_freshness.get("stock_universe", {}).get("status") != "fresh" and not history.empty:
        history.loc[history.index[-1], "raw_state"] = UNKNOWN
    tracker = StateTracker(
        StateTrackerConfig(min_confirm_days=2, min_hold_days=2, extreme_states=("broad_decline",))
    ).track(history["trade_date"], history["raw_state"], dimension="return_distribution")
    history["state"] = [item["state"] for item in tracker["history"]]
    latest = history.iloc[-1].replace({np.nan: None}).to_dict() if not history.empty else {}
    latest_values = daily.iloc[-1].where(valid.iloc[-1]).dropna() if not daily.empty else pd.Series(dtype=float)
    histogram_edges = [-np.inf, -0.10, -0.07, -0.05, -0.03, -0.01, 0.0, 0.01, 0.03, 0.05, 0.07, 0.10, np.inf]
    histogram_labels = ["<-10%", "-10~-7%", "-7~-5%", "-5~-3%", "-3~-1%", "-1~0%", "0~1%", "1~3%", "3~5%", "5~7%", "7~10%", ">10%"]
    bins = pd.cut(latest_values, bins=histogram_edges, labels=histogram_labels, right=False)
    counts = bins.value_counts(sort=False) if not latest_values.empty else pd.Series(0, index=histogram_labels)
    histogram = [
        {
            "label": label,
            "count": int(counts.get(label, 0)),
            "ratio": finite(counts.get(label, 0) / len(latest_values)) if len(latest_values) else None,
        }
        for label in histogram_labels
    ]
    return {
        "state": tracker["state"],
        "latest": latest,
        "history": _serialize_frame(history, history_days),
        "histogram": histogram,
        "state_tracker": {key: value for key, value in tracker.items() if key != "history"},
    }


def _scaled_mean(frame: pd.DataFrame, minimum: int = 2) -> pd.Series:
    count = frame.notna().sum(axis=1)
    return frame.mean(axis=1, skipna=True).where(count >= minimum)


def build_risk_structure(
    *,
    breadth_history: pd.DataFrame,
    source_freshness: dict[str, dict[str, Any]],
    history_days: int,
) -> dict[str, Any]:
    frame = breadth_history.copy()
    if frame.empty:
        tracker = StateTracker().track([], [], dimension="risk")
        return {"state": UNKNOWN, "latest": {}, "history": [], "state_tracker": tracker}
    if "trade_date" not in frame.columns:
        frame.insert(0, "trade_date", pd.RangeIndex(len(frame)).astype(str))
    def numeric(name: str) -> pd.Series:
        if name not in frame.columns:
            return pd.Series(np.nan, index=frame.index, dtype="float64")
        return pd.to_numeric(frame[name], errors="coerce")
    extreme = pd.DataFrame(
        {
            "decline_gt_3": (numeric("decline_gt_3_ratio") / 0.25 * 100).clip(0, 100),
            "decline_gt_5": (numeric("decline_gt_5_ratio") / 0.12 * 100).clip(0, 100),
            "limit_down": (numeric("approximate_limit_down_ratio") / 0.05 * 100).clip(0, 100),
        }
    )
    internal = pd.DataFrame(
        {
            "new_low_20": (numeric("new_low_20_ratio") / 0.20 * 100).clip(0, 100),
            "below_ma20": ((1 - numeric("pct_above_ma20")) * 100).clip(0, 100),
            "below_ma50": ((1 - numeric("pct_above_ma50")) * 100).clip(0, 100),
            "negative_ad": ((1 - numeric("normalized_ad")) / 2 * 100).clip(0, 100),
        }
    )
    dispersion_percentile = _rolling_percentile(numeric("cross_section_dispersion"), min_periods=20) * 100
    volatility_percentile = _rolling_percentile(numeric("market_realized_volatility_5d"), min_periods=20) * 100
    index_stock_volatility_gap = (
        numeric("market_realized_volatility_5d")
        - numeric("cross_section_dispersion") * np.sqrt(252.0)
    ).abs()
    disorder = pd.DataFrame(
        {
            "dispersion": dispersion_percentile,
            "volatility": volatility_percentile,
            "index_stock_volatility_gap": _rolling_percentile(index_stock_volatility_gap, min_periods=20) * 100,
            "decline_amount": (numeric("decline_amount_ratio") * 100).clip(0, 100),
        }
    )
    result = pd.DataFrame({"trade_date": frame["trade_date"].astype(str)})
    result["extreme_decline_score"] = _scaled_mean(extreme, minimum=2)
    result["internal_damage_score"] = _scaled_mean(internal, minimum=2)
    result["disorder_score"] = _scaled_mean(disorder, minimum=2)
    family_scores = result[["extreme_decline_score", "internal_damage_score", "disorder_score"]]
    result["evidence_family_count"] = family_scores.notna().sum(axis=1)
    result["raw_score"] = family_scores.mean(axis=1, skipna=True).where(result["evidence_family_count"] >= 2)
    result["smooth_3d"] = result["raw_score"].rolling(3, min_periods=2).mean()
    result["smooth_5d"] = result["raw_score"].rolling(5, min_periods=3).mean()
    result["change_1d"] = result["smooth_5d"] - result["smooth_5d"].shift(1)
    result["change_5d"] = result["smooth_5d"] - result["smooth_5d"].shift(5)
    result["risk_score_raw"] = result["raw_score"]
    result["risk_score_smoothed_3d"] = result["smooth_3d"]
    result["risk_score_smoothed_5d"] = result["smooth_5d"]
    result["risk_change_1d"] = result["change_1d"]
    result["risk_change_5d"] = result["change_5d"]
    result["raw_state"] = [
        classify_risk_phase(row.get("smooth_5d"), row.get("change_1d"), row.get("change_5d"))
        for _, row in result.iterrows()
    ]
    freshness_ok = (
        source_freshness.get("stock_universe", {}).get("status") == "fresh"
        and source_freshness.get("amount", {}).get("status") == "fresh"
    )
    if not freshness_ok:
        result.loc[result.index[-1], "raw_state"] = UNKNOWN
    tracker = StateTracker(
        StateTrackerConfig(
            min_confirm_days=2,
            min_hold_days=2,
            extreme_states=("risk_expanding",),
        )
    ).track(result["trade_date"], result["raw_state"], dimension="risk")
    result["state"] = [item["state"] for item in tracker["history"]]
    latest = result.iloc[-1].replace({np.nan: None}).to_dict()
    latest["duration_trading_days"] = tracker["duration_trading_days"]
    latest["risk_duration"] = tracker["duration_days"]
    return {
        "state": tracker["state"],
        "latest": latest,
        "evidence_families": {
            "extreme_declines": list(extreme.columns),
            "internal_damage": list(internal.columns),
            "disorder": list(disorder.columns),
        },
        "history": _serialize_frame(result, history_days),
        "state_tracker": {key: value for key, value in tracker.items() if key != "history"},
        "method": {
            "smoothing": [3, 5],
            "normal_transition_confirmation_days": 2,
            "extreme_fast_switch": True,
            "missing_is_unknown": True,
        },
    }


def _style_quality_history(
    *,
    name: str,
    symbols: list[str],
    close: pd.DataFrame,
    amount: pd.DataFrame,
    all_a_return_5d: pd.Series,
    all_a_return_20d: pd.Series,
    subindustries: dict[str, list[str]] | None = None,
    calculation_days: int | None = None,
) -> pd.DataFrame:
    selected = [symbol for symbol in symbols if symbol in close.columns]
    frame = pd.DataFrame(index=close.index)
    frame["trade_date"] = frame.index.strftime("%Y-%m-%d")
    if not selected:
        return frame
    daily = close[selected].pct_change(fill_method=None)
    traded = amount[selected].gt(0) & amount[selected].notna()
    terminal5 = (close[selected] / close[selected].shift(5) - 1.0).where(traded)
    terminal10 = (close[selected] / close[selected].shift(10) - 1.0).where(traded)
    terminal20 = (close[selected] / close[selected].shift(20) - 1.0).where(traded)
    ma20 = close[selected].rolling(20, min_periods=20).mean()
    valid_today = daily.notna() & traded
    frame["return_5d"] = terminal5.mean(axis=1, skipna=True)
    frame["return_10d"] = terminal10.mean(axis=1, skipna=True)
    frame["return_20d"] = terminal20.mean(axis=1, skipna=True)
    frame["median_return_5d"] = terminal5.median(axis=1, skipna=True)
    frame["median_return_10d"] = terminal10.median(axis=1, skipna=True)
    frame["median_return_20d"] = terminal20.median(axis=1, skipna=True)
    frame["relative_strength_5d"] = frame["return_5d"] - all_a_return_5d
    frame["relative_strength_20d"] = frame["return_20d"] - all_a_return_20d
    frame["advance_ratio"] = ((daily > 0) & valid_today).sum(axis=1) / valid_today.sum(axis=1).replace(0, np.nan)
    ma_valid = close[selected].notna() & ma20.notna() & traded
    frame["pct_above_ma20"] = ((close[selected] > ma20) & ma_valid).sum(axis=1) / ma_valid.sum(axis=1).replace(0, np.nan)
    frame["breadth_change_5d"] = frame["advance_ratio"] - frame["advance_ratio"].shift(5)
    frame["breadth_change_20d"] = frame["advance_ratio"] - frame["advance_ratio"].shift(20)
    high20 = close[selected].rolling(20, min_periods=20).max().shift(1)
    high_valid = close[selected].notna() & high20.notna() & traded
    frame["new_high_20_ratio"] = ((close[selected] > high20) & high_valid).sum(axis=1) / high_valid.sum(axis=1).replace(0, np.nan)
    group_amount = amount[selected].where(traded).sum(axis=1, min_count=1)
    total_amount = amount.where(amount.gt(0)).sum(axis=1, min_count=1)
    turnover_share = group_amount / total_amount.replace(0, np.nan)
    frame["turnover_share"] = turnover_share
    frame["turnover_share_change_5d"] = turnover_share - turnover_share.shift(5)
    frame["turnover_share_change_20d"] = turnover_share - turnover_share.shift(20)
    frame["strong_stock_count"] = (terminal20 >= 0.03).sum(axis=1)
    frame["top5_positive_contribution_share"] = np.nan
    frame["top10_turnover_share"] = np.nan
    calculation_index = close.index[-calculation_days:] if calculation_days else close.index
    for date in calculation_index:
        frame.loc[date, "top5_positive_contribution_share"] = _top_n_share(terminal20.loc[date], 5, positive_only=True)
        frame.loc[date, "top10_turnover_share"] = _top_n_share(
            amount.loc[date, selected].where(traded.loc[date]), 10, positive_only=False
        )
    if subindustries:
        subindustry_returns = pd.DataFrame(index=close.index)
        for industry, members in subindustries.items():
            members = [symbol for symbol in members if symbol in selected]
            if members:
                subindustry_returns[industry] = (close[members] / close[members].shift(20) - 1.0).mean(axis=1, skipna=True)
        frame["synchronized_subindustry_ratio"] = (subindustry_returns > 0).sum(axis=1) / subindustry_returns.notna().sum(axis=1).replace(0, np.nan)
        frame["synchronized_subindustry_count"] = (subindustry_returns > 0).sum(axis=1)
    else:
        frame["synchronized_subindustry_ratio"] = np.nan
        frame["synchronized_subindustry_count"] = np.nan
    frame["raw_quality_state"] = [classify_leadership_quality(row) for _, row in frame.iterrows()]
    return frame


def build_leadership_and_industries(
    *,
    close: pd.DataFrame,
    amount: pd.DataFrame,
    style_symbol_groups: dict[str, list[str]],
    style_industry_groups: dict[str, dict[str, list[str]]],
    industry_groups: dict[str, list[str]],
    source_freshness: dict[str, dict[str, Any]],
    history_days: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, pd.DataFrame]]:
    all_a_5d = (close / close.shift(5) - 1.0).mean(axis=1, skipna=True)
    all_a_20d = (close / close.shift(20) - 1.0).mean(axis=1, skipna=True)
    style_frames: dict[str, pd.DataFrame] = {}
    style_latest: dict[str, dict[str, Any]] = {}
    for name, symbols in style_symbol_groups.items():
        frame = _style_quality_history(
            name=name,
            symbols=symbols,
            close=close,
            amount=amount,
            all_a_return_5d=all_a_5d,
            all_a_return_20d=all_a_20d,
            subindustries=style_industry_groups.get(name),
            calculation_days=max(history_days + 20, 80),
        )
        style_frames[name] = frame
        latest = frame.iloc[-1].replace({np.nan: None}).to_dict() if not frame.empty else {}
        style_latest[name] = {
            "name": name,
            **latest,
            "composition_point_in_time": False,
            "confidence_limited": True,
        }

    dates = close.index
    leaders: list[str | None] = []
    raw_quality: list[str] = []
    quality_rows: list[dict[str, Any]] = []
    for date in dates:
        candidates = {
            name: finite(frame.loc[date, "return_20d"])
            for name, frame in style_frames.items()
            if date in frame.index and finite(frame.loc[date, "return_20d"]) is not None
        }
        leader = max(candidates, key=lambda key: float(candidates[key])) if candidates else None
        leaders.append(leader)
        if leader is None:
            raw = UNKNOWN
            row: dict[str, Any] = {"trade_date": pd.Timestamp(date).strftime("%Y-%m-%d"), "leader": None}
        else:
            source_row = style_frames[leader].loc[date]
            raw = str(source_row.get("raw_quality_state") or UNKNOWN)
            row = {
                "trade_date": pd.Timestamp(date).strftime("%Y-%m-%d"),
                "leader": leader,
                **{
                    key: finite(source_row.get(key))
                    for key in (
                        "return_5d", "return_10d", "return_20d", "median_return_5d", "median_return_10d", "median_return_20d", "relative_strength_5d", "relative_strength_20d",
                        "advance_ratio", "pct_above_ma20", "new_high_20_ratio",
                        "top5_positive_contribution_share", "top10_turnover_share",
                        "synchronized_subindustry_ratio", "synchronized_subindustry_count",
                        "breadth_change_5d", "breadth_change_20d", "turnover_share", "turnover_share_change_5d", "turnover_share_change_20d", "strong_stock_count",
                    )
                },
            }
        raw_quality.append(raw)
        row["raw_state"] = raw
        quality_rows.append(row)
    if source_freshness.get("stock_universe", {}).get("status") != "fresh" and raw_quality:
        raw_quality[-1] = UNKNOWN
        quality_rows[-1]["raw_state"] = UNKNOWN
    quality_history = pd.DataFrame(quality_rows)
    quality_tracker = StateTracker(
        StateTrackerConfig(min_confirm_days=2, min_hold_days=2, extreme_states=("failed",))
    ).track(quality_history["trade_date"], raw_quality, dimension="leadership")
    quality_history["state"] = [row["state"] for row in quality_tracker["history"]]
    leader_tracker = StateTracker(
        StateTrackerConfig(min_confirm_days=2, min_hold_days=2)
    ).track(
        [pd.Timestamp(value).strftime("%Y-%m-%d") for value in dates],
        [leader or UNKNOWN for leader in leaders],
        dimension="style_leader",
    )

    industry_rows: list[dict[str, Any]] = []
    for industry, symbols in industry_groups.items():
        frame = _style_quality_history(
            name=industry,
            symbols=symbols,
            close=close,
            amount=amount,
            all_a_return_5d=all_a_5d,
            all_a_return_20d=all_a_20d,
            calculation_days=1,
        )
        if frame.empty:
            continue
        row = frame.iloc[-1]
        if finite(row.get("return_10d")) is None:
            continue
        industry_rows.append(
            {
                "industry": industry,
                "stock_count": len(symbols),
                **{
                    key: finite(row.get(key))
                    for key in (
                        "return_5d", "return_10d", "return_20d", "median_return_5d", "median_return_10d", "median_return_20d", "relative_strength_5d", "relative_strength_20d",
                        "advance_ratio", "pct_above_ma20", "new_high_20_ratio",
                        "top5_positive_contribution_share", "top10_turnover_share", "breadth_change_5d", "breadth_change_20d", "strong_stock_count",
                    )
                },
                "leadership_quality": str(row.get("raw_quality_state") or UNKNOWN),
                "composition_point_in_time": False,
            }
        )
    strongest = sorted(industry_rows, key=lambda row: float(row.get("return_10d") or -999), reverse=True)[:10]
    weakest = sorted(industry_rows, key=lambda row: float(row.get("return_10d") or 999))[:10]
    leadership = {
        "state": quality_tracker["state"],
        "leader": leader_tracker["state"],
        "latest": quality_history.iloc[-1].replace({np.nan: None}).to_dict() if not quality_history.empty else {},
        "styles": style_latest,
        "history": _serialize_frame(quality_history, history_days),
        "state_tracker": {key: value for key, value in quality_tracker.items() if key != "history"},
        "leader_tracker": {key: value for key, value in leader_tracker.items() if key != "history"},
        "leader_history": leader_tracker["history"][-history_days:],
        "method": "absolute return + relative strength + internal breadth + MA participation + top-stock contribution + turnover concentration",
    }
    industry_structure = {
        "strongest": strongest,
        "weakest": weakest,
        "rank_basis": "return_10d",
        "composition_point_in_time": False,
        "data_quality_flag": "current_industry_classification_used_for_history",
    }
    return leadership, industry_structure, style_frames


def build_style_rotation(
    *,
    style_frames: dict[str, pd.DataFrame],
    source_freshness: dict[str, dict[str, Any]],
    history_days: int,
) -> dict[str, Any]:
    style_outputs: dict[str, Any] = {}
    level_series: dict[str, pd.Series] = {}
    for name, frame in style_frames.items():
        relative = pd.to_numeric(frame.get("relative_strength_20d"), errors="coerce")
        breadth = pd.to_numeric(frame.get("advance_ratio"), errors="coerce")
        ma20 = pd.to_numeric(frame.get("pct_above_ma20"), errors="coerce")
        relative_pct = _rolling_percentile(relative, window=252, min_periods=20)
        level = (0.40 * relative_pct + 0.30 * breadth + 0.30 * ma20) * 100
        level_series[name] = level
        out = pd.DataFrame(index=frame.index)
        out["trade_date"] = frame["trade_date"]
        out["level"] = level
        out["strength_level"] = level
        out["change_1d"] = level - level.shift(1)
        out["change_5d"] = level - level.shift(5)
        out["strength_change_1d"] = out["change_1d"]
        out["strength_change_5d"] = out["change_5d"]
        out["relative_slope_5d"] = relative - relative.shift(5)
        out["relative_slope_20d"] = relative - relative.shift(20)
        out["acceleration"] = out["relative_slope_5d"] - out["relative_slope_5d"].shift(5)
        out["relative_strength_slope_5d"] = out["relative_slope_5d"]
        out["relative_strength_slope_20d"] = out["relative_slope_20d"]
        out["relative_strength_acceleration"] = out["acceleration"]
        out["breadth_change_5d"] = frame.get("breadth_change_5d")
        out["turnover_share_change_5d"] = frame.get("turnover_share_change_5d")
        out["turnover_share_change_20d"] = frame.get("turnover_share_change_20d")
        out["raw_state"] = [classify_rotation(row) for _, row in out.iterrows()]
        tracker = StateTracker(StateTrackerConfig(min_confirm_days=2, min_hold_days=2)).track(
            out["trade_date"], out["raw_state"], dimension=f"style_rotation:{name}"
        )
        out["state"] = [row["state"] for row in tracker["history"]]
        style_outputs[name] = {
            "state": tracker["state"],
            "latest": out.iloc[-1].replace({np.nan: None}).to_dict(),
            "history": _serialize_frame(out, history_days),
            "state_tracker": {key: value for key, value in tracker.items() if key != "history"},
        }
    levels = pd.DataFrame(level_series)
    leaders = (
        levels.apply(lambda row: row.dropna().idxmax() if row.notna().any() else None, axis=1)
        if not levels.empty else pd.Series(dtype=object)
    )
    leader_changes = leaders.ne(leaders.shift(1)) & leaders.notna() & leaders.shift(1).notna()
    latest_leader = leaders.iloc[-1] if not leaders.empty and pd.notna(leaders.iloc[-1]) else None
    days_as_leader = 0
    if latest_leader is not None:
        for value in reversed(leaders.tolist()):
            if value != latest_leader:
                break
            days_as_leader += 1
    for name, item in style_outputs.items():
        item["days_as_leader"] = days_as_leader if name == latest_leader else 0
        item["leader_change_count_20d"] = int(leader_changes.tail(20).sum())
        item["leader_change_count_60d"] = int(leader_changes.tail(60).sum())
        item["leadership_quality"] = None
    overall_fresh = source_freshness.get("stock_universe", {}).get("status") == "fresh"
    return {
        "leader": latest_leader,
        "days_as_leader": days_as_leader,
        "leader_changes_20d": int(leader_changes.tail(20).sum()),
        "leader_changes_60d": int(leader_changes.tail(60).sum()),
        "leader_change_count_20d": int(leader_changes.tail(20).sum()),
        "leader_change_count_60d": int(leader_changes.tail(60).sum()),
        "styles": style_outputs,
        "freshness_status": "fresh" if overall_fresh else "unknown",
        "method": "historical percentile level, 1/5-day change, 5/20-day relative slope and acceleration",
    }


def build_liquidity_structure(
    *,
    close: pd.DataFrame,
    amount: pd.DataFrame,
    breadth_history: pd.DataFrame,
    concentration_history: list[dict[str, Any]],
    layered_breadth: dict[str, Any],
    style_symbol_groups: dict[str, list[str]],
    industry_groups: dict[str, list[str]],
    source_freshness: dict[str, dict[str, Any]],
    history_days: int,
) -> dict[str, Any]:
    dates = pd.DatetimeIndex(close.index)
    daily = close.pct_change(fill_method=None)
    traded = amount.notna() & amount.gt(0)
    total = amount.where(traded).sum(axis=1, min_count=1)
    total_ma5 = total.rolling(5, min_periods=5).mean()
    total_ma20 = total.rolling(20, min_periods=20).mean()
    advance_amount = amount.where((daily > 0) & traded).sum(axis=1, min_count=1)
    decline_amount = amount.where((daily < 0) & traded).sum(axis=1, min_count=1)
    high20 = close.rolling(20, min_periods=20).max().shift(1)
    low20 = close.rolling(20, min_periods=20).min().shift(1)
    high_amount = amount.where((close > high20) & traded).sum(axis=1, min_count=1)
    low_amount = amount.where((close < low20) & traded).sum(axis=1, min_count=1)
    total_amount_percentile = _rolling_percentile(total, window=252, min_periods=20)
    concentration = pd.DataFrame(concentration_history)
    if not concentration.empty and "trade_date" in concentration.columns:
        concentration["trade_date"] = pd.to_datetime(concentration["trade_date"], errors="coerce")
        concentration = concentration.dropna(subset=["trade_date"]).set_index("trade_date")
    breadth = breadth_history.copy()
    if "trade_date" in breadth.columns:
        breadth["trade_date"] = pd.to_datetime(breadth["trade_date"], errors="coerce")
        breadth = breadth.dropna(subset=["trade_date"]).set_index("trade_date")
    industry_returns = pd.DataFrame(index=dates)
    industry_amounts = pd.DataFrame(index=dates)
    industry_amount_ratios = pd.DataFrame(index=dates)
    for industry, symbols in industry_groups.items():
        selected = [symbol for symbol in symbols if symbol in close.columns]
        if not selected:
            continue
        industry_returns[industry] = daily[selected].where(traded[selected]).mean(axis=1, skipna=True)
        industry_total = amount[selected].where(traded[selected]).sum(axis=1, min_count=1)
        industry_amounts[industry] = industry_total
        industry_amount_ratios[industry] = industry_total / industry_total.rolling(20, min_periods=20).mean()
    rows: list[dict[str, Any]] = []
    for date in dates[-max(history_days, 60):]:
        amount_ratio_5d = finite(total.loc[date] / total_ma5.loc[date])
        amount_ratio = finite(total.loc[date] / total_ma20.loc[date])
        equal_return = finite(daily.loc[date].where(traded.loc[date]).mean())
        top_share = None
        if not concentration.empty and date in concentration.index:
            top_share = finite(concentration.loc[date].get("top_10pct_turnover_share"))
        stock_returns = daily.loc[date].where(traded.loc[date]).dropna()
        stock_amount = amount.loc[date].where(traded.loc[date]).dropna()
        valid_symbols = stock_returns.index.intersection(stock_amount.index)
        stock_returns = stock_returns.reindex(valid_symbols).dropna()
        stock_amount = stock_amount.reindex(stock_returns.index).dropna()
        valid_total_amount = float(stock_amount.sum()) if not stock_amount.empty else 0.0
        top_fraction_count = max(1, int(np.ceil(len(stock_returns) * 0.10))) if len(stock_returns) else 0
        top_gainer_symbols = stock_returns.nlargest(top_fraction_count).index if top_fraction_count else []
        top_loser_symbols = stock_returns.nsmallest(top_fraction_count).index if top_fraction_count else []
        row = {
            "trade_date": date.strftime("%Y-%m-%d"),
            "total_amount": finite(total.loc[date]),
            "amount_ratio_5d": amount_ratio_5d,
            "amount_ratio_20d": amount_ratio,
            "total_amount_percentile_20d": finite(total_amount_percentile.loc[date]),
            "advance_amount": finite(advance_amount.loc[date]),
            "decline_amount": finite(decline_amount.loc[date]),
            "advance_amount_ratio": finite(advance_amount.loc[date] / total.loc[date]) if finite(total.loc[date]) else None,
            "decline_amount_ratio": finite(decline_amount.loc[date] / total.loc[date]) if finite(total.loc[date]) else None,
            "advance_decline_amount_ratio": finite(advance_amount.loc[date] / decline_amount.loc[date]) if finite(decline_amount.loc[date]) not in {None, 0.0} else None,
            "new_high_amount_share": finite(high_amount.loc[date] / total.loc[date]) if finite(total.loc[date]) else None,
            "new_low_amount_share": finite(low_amount.loc[date] / total.loc[date]) if finite(total.loc[date]) else None,
            "top_10pct_turnover_share": top_share,
            "top_10pct_gainer_amount_share": finite(stock_amount.reindex(top_gainer_symbols).sum() / valid_total_amount) if valid_total_amount > 0 and top_fraction_count else None,
            "top_10pct_loser_amount_share": finite(stock_amount.reindex(top_loser_symbols).sum() / valid_total_amount) if valid_total_amount > 0 and top_fraction_count else None,
            "top_10pct_gainer_count": int(top_fraction_count) if top_fraction_count else None,
            "top_10pct_loser_count": int(top_fraction_count) if top_fraction_count else None,
            "equal_weight_return_1d": equal_return,
            "expanding_up_industry_count": int(((industry_amount_ratios.loc[date] >= 1.10) & (industry_returns.loc[date] > 0)).sum()) if not industry_returns.empty else None,
            "expanding_down_industry_count": int(((industry_amount_ratios.loc[date] >= 1.10) & (industry_returns.loc[date] < 0)).sum()) if not industry_returns.empty else None,
        }
        rows.append(row)
    history = pd.DataFrame(rows)
    history["raw_state"] = [classify_liquidity(row) for _, row in history.iterrows()]
    fresh = source_freshness.get("amount", {}).get("status") == "fresh"
    if not fresh and not history.empty:
        history.loc[history.index[-1], "raw_state"] = UNKNOWN
    tracker = StateTracker(
        StateTrackerConfig(min_confirm_days=2, min_hold_days=2, extreme_states=("selling_expansion",))
    ).track(history["trade_date"], history["raw_state"], dimension="liquidity")
    history["state"] = [item["state"] for item in tracker["history"]]
    cap_turnover_shares = {
        name: finite((item.get("latest") or {}).get("turnover_share"))
        for name, item in layered_breadth.items()
        if name in {"上证50", "沪深300", "中证500", "中证1000", "中证2000", "创业板", "科创50"}
    }
    cap_turnover_share_changes: dict[str, dict[str, float | None]] = {}
    for name, item in layered_breadth.items():
        if name not in {"上证50", "沪深300", "中证500", "中证1000", "中证2000", "创业板", "科创50"}:
            continue
        layer_history = pd.DataFrame(item.get("history") or [])
        if layer_history.empty or "turnover_share" not in layer_history.columns:
            cap_turnover_share_changes[name] = {"change_5d": None, "change_20d": None}
            continue
        layer_history["trade_date"] = pd.to_datetime(layer_history.get("trade_date"), errors="coerce")
        layer_history = layer_history.dropna(subset=["trade_date"]).sort_values("trade_date")
        layer_history["turnover_share"] = pd.to_numeric(layer_history["turnover_share"], errors="coerce")
        current = finite(layer_history["turnover_share"].iloc[-1])
        cap_turnover_share_changes[name] = {
            "change_5d": finite(current - layer_history["turnover_share"].shift(5).iloc[-1]) if current is not None else None,
            "change_20d": finite(current - layer_history["turnover_share"].shift(20).iloc[-1]) if current is not None else None,
        }
    cap_turnover_shares.update(
        {
            "large_cap": cap_turnover_shares.get("沪深300"),
            "mid_cap": cap_turnover_shares.get("中证500"),
            "small_cap": cap_turnover_shares.get("中证1000"),
        }
    )
    style_turnover_shares: dict[str, float | None] = {}
    style_turnover_share_changes: dict[str, dict[str, float | None]] = {}
    style_turnover_series: dict[str, pd.Series] = {}
    latest_date = dates[-1]
    for name, symbols in style_symbol_groups.items():
        selected = [symbol for symbol in symbols if symbol in amount.columns]
        if selected:
            value_series = amount[selected].where(amount[selected].gt(0)).sum(axis=1, min_count=1)
            share_series = value_series / total.replace(0, np.nan)
            value = value_series.loc[latest_date]
        else:
            share_series = pd.Series(index=dates, dtype=float)
            value = np.nan
        style_turnover_series[name] = share_series
        style_turnover_shares[name] = finite(value / total.loc[latest_date]) if finite(total.loc[latest_date]) else None
        current_share = style_turnover_shares[name]
        style_turnover_share_changes[name] = {
            "change_5d": finite(current_share - share_series.shift(5).loc[latest_date]) if current_share is not None else None,
            "change_20d": finite(current_share - share_series.shift(20).loc[latest_date]) if current_share is not None else None,
        }
    industry_turnover_shares: list[dict[str, Any]] = []
    if not industry_amounts.empty and finite(total.loc[latest_date]):
        shares = industry_amounts.div(total, axis=0)
        for industry in industry_amounts.columns:
            current_share = finite(shares.loc[latest_date, industry])
            if current_share is None:
                continue
            industry_turnover_shares.append(
                {
                    "industry": industry,
                    "amount_share": current_share,
                    "amount_share_change_5d": finite(current_share - shares[industry].shift(5).loc[latest_date]),
                    "amount_share_change_20d": finite(current_share - shares[industry].shift(20).loc[latest_date]),
                    "amount_ratio_20d": finite(industry_amount_ratios.loc[latest_date, industry]),
                    "return_1d": finite(industry_returns.loc[latest_date, industry]),
                }
            )
        industry_turnover_shares.sort(key=lambda item: item["amount_share"], reverse=True)
    turnover_migration: list[dict[str, Any]] = []
    for name in ("沪深300", "中证1000", "中证2000"):
        changes = cap_turnover_share_changes.get(name) or {}
        turnover_migration.append(
            {
                "bucket": "权重宽基",
                "name": name,
                "amount_share": cap_turnover_shares.get(name),
                "amount_share_change_5d": changes.get("change_5d"),
                "amount_share_change_20d": changes.get("change_20d"),
            }
        )
    for name, share in style_turnover_shares.items():
        changes = style_turnover_share_changes.get(name) or {}
        turnover_migration.append(
            {
                "bucket": "题材风格",
                "name": name,
                "amount_share": share,
                "amount_share_change_5d": changes.get("change_5d"),
                "amount_share_change_20d": changes.get("change_20d"),
            }
        )
    return {
        "state": tracker["state"],
        "latest": history.iloc[-1].replace({np.nan: None}).to_dict() if not history.empty else {},
        "cap_turnover_shares": cap_turnover_shares,
        "cap_turnover_share_changes": cap_turnover_share_changes,
        "style_turnover_shares": style_turnover_shares,
        "style_turnover_share_changes": style_turnover_share_changes,
        "industry_turnover_shares": industry_turnover_shares,
        "turnover_migration": turnover_migration,
        "history": _serialize_frame(history, history_days),
        "state_tracker": {key: value for key, value in tracker.items() if key != "history"},
        "real_amount_only": True,
    }


def build_repair_structure(
    *,
    breadth_history: pd.DataFrame,
    risk_structure: dict[str, Any],
    source_freshness: dict[str, dict[str, Any]],
    history_days: int,
) -> dict[str, Any]:
    breadth = breadth_history.copy()
    risk = pd.DataFrame(risk_structure.get("history") or [])
    if breadth.empty or risk.empty or "trade_date" not in breadth.columns or "trade_date" not in risk.columns:
        tracker = StateTracker().track([], [], dimension="repair")
        return {"state": UNKNOWN, "latest": {}, "history": [], "state_tracker": tracker}
    frame = breadth.merge(
        risk[["trade_date", "smooth_5d", "change_5d"]],
        on="trade_date",
        how="inner",
        validate="one_to_one",
    )
    def num(column: str) -> pd.Series:
        if column not in frame.columns:
            return pd.Series(np.nan, index=frame.index, dtype="float64")
        return pd.to_numeric(frame[column], errors="coerce")

    frame["risk_score"] = pd.to_numeric(frame["smooth_5d"], errors="coerce")
    frame["risk_change_5d"] = pd.to_numeric(frame["change_5d"], errors="coerce")
    frame["ad_slope_5d"] = num("ad_slope_5")
    frame["new_low_change_5d"] = num("new_low_20_change_5d")
    frame["pct_above_ma20_change_5d"] = num("pct_above_ma20") - num("pct_above_ma20").shift(5)
    frame["equal_weight_return_5d"] = num("equal_weight_return_5d")
    frame["decline_gt_3_change_5d"] = num("decline_gt_3_ratio") - num("decline_gt_3_ratio").shift(5)
    frame["decline_gt_5_change_5d"] = num("decline_gt_5_ratio") - num("decline_gt_5_ratio").shift(5)
    frame["advance_ratio_3d"] = num("advance_ratio").rolling(3, min_periods=3).mean()
    median_return = num("median_stock_return_1d")
    frame["median_positive_3d"] = median_return.gt(0).rolling(3, min_periods=3).sum()
    frame["new_high_change_5d"] = num("new_high_20_ratio") - num("new_high_20_ratio").shift(5)
    frame["rebound_amount_ratio_20d"] = num("amount_ratio_20")
    frame["all_a_equal_repair"] = frame["equal_weight_return_5d"].gt(0)
    frame["small_cap_synchronized_repair"] = None
    frame["retested_prior_low"] = None
    frame["risk_reexpanding"] = frame["risk_change_5d"].gt(0)
    frame["raw_state"] = [classify_repair(row) for _, row in frame.iterrows()]
    fresh = source_freshness.get("stock_universe", {}).get("status") == "fresh"
    if not fresh and not frame.empty:
        frame.loc[frame.index[-1], "raw_state"] = UNKNOWN
    tracker = StateTracker(
        StateTrackerConfig(min_confirm_days=2, min_hold_days=2, extreme_states=("panic_expanding",))
    ).track(frame["trade_date"], frame["raw_state"], dimension="repair")
    frame["state"] = [item["state"] for item in tracker["history"]]
    keep = [
        "trade_date", "risk_score", "risk_change_5d", "advance_ratio", "ad_slope_5d",
        "new_low_change_5d", "pct_above_ma20", "pct_above_ma20_change_5d",
        "equal_weight_return_5d", "raw_state", "state",
        "decline_gt_3_change_5d", "decline_gt_5_change_5d", "advance_ratio_3d",
        "median_positive_3d", "new_high_change_5d", "rebound_amount_ratio_20d",
        "all_a_equal_repair", "small_cap_synchronized_repair", "retested_prior_low", "risk_reexpanding",
    ]
    compact = frame[[column for column in keep if column in frame.columns]]
    return {
        "state": tracker["state"],
        "latest": compact.iloc[-1].replace({np.nan: None}).to_dict() if not compact.empty else {},
        "history": _serialize_frame(compact, history_days),
        "state_tracker": {key: value for key, value in tracker.items() if key != "history"},
        "descriptive_only": True,
        "not_a_buy_signal": True,
    }


def build_divergence_tracker(
    *,
    index_frames: dict[str, pd.DataFrame],
    close: pd.DataFrame,
    source_freshness: dict[str, dict[str, Any]],
    history_days: int,
) -> dict[str, Any]:
    dates = pd.DatetimeIndex(close.index)
    all_a_equal = (close / close.shift(5) - 1.0).mean(axis=1, skipna=True)
    hs300_frame = index_frames.get("000300.SH")
    if hs300_frame is None or hs300_frame.empty:
        tracker = StateTracker().track([], [], dimension="divergence")
        return {"state": UNKNOWN, "latest": {}, "history": [], "state_tracker": tracker}
    work = hs300_frame.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work["close"] = pd.to_numeric(work["close"], errors="coerce")
    hs300 = work.dropna(subset=["date", "close"]).drop_duplicates("date", keep="last").set_index("date")["close"].reindex(dates)
    hs300_ret5 = hs300 / hs300.shift(5) - 1.0
    gap = all_a_equal - hs300_ret5
    raw = pd.Series(
        np.where(gap >= 0.003, "stocks_stronger", np.where(gap <= -0.003, "large_cap_stronger", "synchronized")),
        index=dates,
        dtype="object",
    )
    raw[gap.isna()] = UNKNOWN
    if source_freshness.get("index:000300.SH", {}).get("status") != "fresh" or source_freshness.get("stock_universe", {}).get("status") != "fresh":
        raw.iloc[-1] = UNKNOWN
    frame = pd.DataFrame(
        {
            "trade_date": dates.strftime("%Y-%m-%d"),
            "all_a_equal_return_5d": all_a_equal.to_numpy(),
            "hs300_return_5d": hs300_ret5.to_numpy(),
            "gap_5d": gap.to_numpy(),
            "raw_state": raw.to_numpy(),
        }
    )
    tracker = StateTracker(StateTrackerConfig(min_confirm_days=2, min_hold_days=2)).track(
        frame["trade_date"], frame["raw_state"], dimension="divergence"
    )
    frame["state"] = [item["state"] for item in tracker["history"]]
    return {
        "state": tracker["state"],
        "latest": frame.iloc[-1].replace({np.nan: None}).to_dict(),
        "history": _serialize_frame(frame, history_days),
        "state_tracker": {key: value for key, value in tracker.items() if key != "history"},
    }


def _build_participation_tracker(layer: dict[str, Any], history_days: int) -> dict[str, Any]:
    history = pd.DataFrame(layer.get("history") or [])
    if history.empty:
        return StateTracker().track([], [], dimension="participation")
    raw: list[str] = []
    for _, row in history.iterrows():
        advance = finite(row.get("advance_ratio"))
        equal_return = finite(row.get("equal_weight_return_1d"))
        if advance is None or equal_return is None:
            raw.append(UNKNOWN)
        elif advance >= 0.60 and equal_return > 0:
            raw.append("broad_participation")
        elif advance <= 0.40 and equal_return < 0:
            raw.append("weak_participation")
        else:
            raw.append("selective_participation")
    return StateTracker(
        StateTrackerConfig(min_confirm_days=2, min_hold_days=2, extreme_states=("weak_participation",))
    ).track(history["trade_date"], raw, dimension="participation")


def _component_history(component: dict[str, Any]) -> list[dict[str, Any]]:
    history = component.get("history") or []
    return [row for row in history if isinstance(row, dict)]


def _state_timeline(components: dict[str, dict[str, Any]], history_days: int) -> dict[str, Any]:
    dimensions: dict[str, Any] = {}
    for name, component in components.items():
        history = _component_history(component)[-history_days:]
        dimensions[name] = {
            "history": history,
            "segments": merge_state_segments(history),
        }
    return {
        "lookback_trading_days": history_days,
        "dimensions": dimensions,
        "chart_type": "horizontal_state_bands",
    }


def _data_hash(
    close: pd.DataFrame,
    amount: pd.DataFrame,
    index_frames: dict[str, pd.DataFrame],
    member_frames: dict[str, pd.DataFrame],
) -> str:
    digest = hashlib.sha256()
    for name, frame in (("close", close.tail(260)), ("amount", amount.tail(260))):
        digest.update(name.encode("utf-8"))
        digest.update(pd.util.hash_pandas_object(frame, index=True).values.tobytes())
    for symbol in sorted(index_frames):
        frame = index_frames[symbol]
        columns = [column for column in ("date", "close", "amount", "turnover_rate") if column in frame.columns]
        digest.update(symbol.encode("utf-8"))
        if columns:
            digest.update(pd.util.hash_pandas_object(frame[columns].tail(260), index=False).values.tobytes())
    for symbol in sorted(member_frames):
        frame = member_frames[symbol]
        columns = [column for column in ("trade_date", "con_code", "weight") if column in frame.columns]
        digest.update(symbol.encode("utf-8"))
        digest.update(pd.util.hash_pandas_object(frame[columns], index=False).values.tobytes())
    return digest.hexdigest()


def _fmt_pct(value: Any) -> str:
    number = finite(value)
    return "数据不足" if number is None else f"{number:+.1%}"


def _deterministic_summary(
    *,
    base_structure: dict[str, Any],
    layered: dict[str, Any],
    concentration: dict[str, Any],
    leadership: dict[str, Any],
    risk: dict[str, Any],
    repair: dict[str, Any],
    style_rotation: dict[str, Any],
    index_lift_structure: dict[str, Any] | None,
    quality_flags: list[str],
    source_freshness: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    all_a_latest = (layered.get("全A") or {}).get("latest") or {}
    trend = (base_structure.get("market_structure") or {}).get("trend") or {}
    large_cap_fresh = source_freshness.get("index:000300.SH", {}).get("status") == "fresh"
    growth_fresh = any(
        source_freshness.get(f"index:{symbol}", {}).get("status") == "fresh"
        for symbol in ("399006.SZ", "000688.SH")
    )
    legacy_style = (base_structure.get("market_structure") or {}).get("style") or {}
    layer_states = [
        f"{name}:{item.get('state', UNKNOWN)}"
        for name, item in layered.items()
        if name in {"上证50", "沪深300", "中证500", "中证1000", "中证2000", "创业板", "科创50", "全A"}
    ]
    lines = [
        f"赚钱效应：全A上涨比例{_fmt_pct(all_a_latest.get('advance_ratio'))}，等权当日收益{_fmt_pct(all_a_latest.get('equal_weight_return_1d'))}。",
        f"指数趋势：权重日线{trend.get('large_cap_daily', UNKNOWN) if large_cap_fresh else UNKNOWN}、周线{trend.get('large_cap_weekly', UNKNOWN) if large_cap_fresh else UNKNOWN}；成长日线{trend.get('growth_daily', UNKNOWN) if growth_fresh else UNKNOWN}。",
        f"指数拉升质量：{(index_lift_structure or {}).get('state_cn') or '数据不足'}，质量分{finite(((index_lift_structure or {}).get('scores') or {}).get('index_lift_quality'))}，掩护风险分{finite(((index_lift_structure or {}).get('scores') or {}).get('index_masking_risk'))}。",
        "分层广度：" + "，".join(layer_states) + "。",
        f"市场集中度：{concentration.get('state', UNKNOWN)}，历史分位{_fmt_pct((concentration.get('latest') or {}).get('concentration_percentile'))}。",
        f"风格轮动：当前领先为{style_rotation.get('leader') or '数据不足'}，近20日领先切换{style_rotation.get('leader_changes_20d', 0)}次；旧兼容标签“{legacy_style.get('regime_name') or '数据不足'}”不参与v2状态。",
        f"领涨质量：{leadership.get('state', UNKNOWN)}，当前领涨风格{leadership.get('leader') or '数据不足'}。",
        f"风险阶段：{risk.get('state', UNKNOWN)}，5日平滑压力分{finite((risk.get('latest') or {}).get('smooth_5d')) if risk.get('latest') else None}。",
        f"修复阶段：{repair.get('state', UNKNOWN)}，仅描述内部修复进度。",
        f"数据限制：{'; '.join(quality_flags[:6]) if quality_flags else '未发现新增质量标记'}。",
    ]
    return {
        "ordered_dimensions": [
            "money_effect", "trend", "index_lift_structure", "layered_breadth", "concentration", "style",
            "leadership", "risk", "repair", "data_limitations",
        ],
        "lines": lines,
        "headline": "".join(lines),
        "deterministic": True,
        "contains_prediction": False,
        "contains_position_or_order_advice": False,
    }


def _research_candidates(
    *,
    risk: dict[str, Any],
    repair: dict[str, Any],
    concentration: dict[str, Any],
    leadership: dict[str, Any],
    distribution: dict[str, Any],
    style_rotation: dict[str, Any],
) -> dict[str, Any]:
    excluded = ["headline", "position", "order", "formal_signal", "market_risk_gate"]
    ice_phase = classify_ice_phase(
        risk.get("state", UNKNOWN),
        repair.get("state", UNKNOWN),
        (risk.get("latest") or {}).get("smooth_5d"),
        (risk.get("latest") or {}).get("change_5d"),
    )
    heat_phase = classify_heat_phase(
        concentration.get("state", UNKNOWN),
        leadership.get("state", UNKNOWN),
        distribution.get("state", UNKNOWN),
    )
    common = {"exploratory_only": True, "excluded_from": excluded}
    return {
        "ice": {**common, "phase": ice_phase, "descriptive_candidate": True},
        "heat": {**common, "phase": heat_phase, "descriptive_candidate": True},
        "rebound_failure": {
            **common,
            "phase": "candidate" if repair.get("state") == "failed_rebound" else "none",
            "descriptive_candidate": True,
        },
        "style_continuation": {
            **common,
            "phase": "candidate" if style_rotation.get("days_as_leader", 0) >= 5 else "none",
            "leader": style_rotation.get("leader"),
            "descriptive_candidate": True,
        },
    }


def build_market_structure_v2(
    *,
    primary_symbol: str,
    base_structure: dict[str, Any],
    panels: Any,
    index_frames: dict[str, pd.DataFrame],
    index_member_frames: dict[str, pd.DataFrame] | None = None,
    ths_index_frames: dict[str, pd.DataFrame] | None = None,
    style_proxy_symbols: set[str] | None = None,
    industry_proxy_symbols: set[str] | None = None,
    style_symbol_groups: dict[str, list[str]] | None = None,
    style_industry_groups: dict[str, dict[str, list[str]]] | None = None,
    industry_groups: dict[str, list[str]] | None = None,
    as_of: Any | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build every v2 fact/state/research layer from existing local inputs."""
    close = panels.close.copy()
    amount = panels.amount.reindex(index=close.index, columns=close.columns).copy()
    metadata = panels.metadata.copy()
    cutoff = pd.to_datetime(as_of, errors="coerce") if as_of is not None else pd.to_datetime(close.index, errors="coerce").max()
    if pd.isna(cutoff):
        raise ValueError("market_structure_v2 requires a valid as_of date")
    close = close.loc[pd.to_datetime(close.index, errors="coerce") <= cutoff].sort_index()
    amount = amount.reindex(index=close.index, columns=close.columns)
    if close.empty:
        raise ValueError("market_structure_v2 has no stock facts at or before as_of")
    cutoff = pd.Timestamp(close.index[-1])
    member_frames = _prepare_member_frames(index_member_frames, cutoff)
    clipped_indices: dict[str, pd.DataFrame] = {}
    for symbol, frame in index_frames.items():
        if frame is None or frame.empty:
            continue
        work = frame.copy()
        date_column = "date" if "date" in work.columns else "trade_date" if "trade_date" in work.columns else None
        if date_column is None:
            continue
        work[date_column] = pd.to_datetime(work[date_column], errors="coerce")
        work = work.dropna(subset=[date_column])
        work = work[work[date_column] <= cutoff].sort_values(date_column).drop_duplicates(date_column, keep="last")
        if not work.empty:
            clipped_indices[str(symbol).upper()] = work.reset_index(drop=True)
    clipped_ths: dict[str, pd.DataFrame] = {}
    for symbol, frame in (ths_index_frames or {}).items():
        if frame is None or frame.empty or "date" not in frame.columns:
            continue
        work = frame.copy()
        work["date"] = pd.to_datetime(work["date"], errors="coerce")
        work = work.dropna(subset=["date"])
        work = work[work["date"] <= cutoff].sort_values("date").drop_duplicates("date", keep="last")
        if not work.empty:
            clipped_ths[str(symbol).upper()] = work.reset_index(drop=True)

    history_days = max(20, int((config or {}).get("history_days", DEFAULT_HISTORY_DAYS)))
    style_symbol_groups = style_symbol_groups or {}
    style_industry_groups = style_industry_groups or {}
    industry_groups = industry_groups or {}
    freshness = build_source_freshness(
        close=close,
        amount=amount,
        metadata=metadata,
        index_frames=clipped_indices,
        index_member_frames=member_frames,
        ths_index_frames=clipped_ths,
        style_proxy_symbols=style_proxy_symbols,
        industry_proxy_symbols=industry_proxy_symbols,
        as_of=cutoff,
    )
    layered, layer_flags = build_layered_breadth(
        close=close,
        amount=amount,
        metadata=metadata,
        index_member_frames=member_frames,
        index_frames=clipped_indices,
        style_symbol_groups=style_symbol_groups,
        source_freshness=freshness,
        history_days=history_days,
    )
    concentration, concentration_flags = build_concentration_analysis(
        primary_symbol=primary_symbol,
        close=close,
        amount=amount,
        industry_groups=industry_groups,
        index_member_frames=member_frames,
        source_freshness=freshness,
        history_days=history_days,
    )
    distribution = build_return_distribution(
        close=close,
        amount=amount,
        source_freshness=freshness,
        history_days=history_days,
    )
    distribution["layers"] = {
        name: {
            key: (item.get("latest") or {}).get(key)
            for key in ("effective_count", "q05", "q10", "q25", "median", "q75", "q90", "q95", "return_std", "return_iqr", "return_skew", "advance_ratio")
        }
        for name, item in layered.items()
    }
    breadth_history = pd.DataFrame((base_structure.get("breadth") or {}).get("history") or [])
    risk = build_risk_structure(
        breadth_history=breadth_history,
        source_freshness=freshness,
        history_days=history_days,
    )
    leadership, industry_structure, style_frames = build_leadership_and_industries(
        close=close,
        amount=amount,
        style_symbol_groups=style_symbol_groups,
        style_industry_groups=style_industry_groups,
        industry_groups=industry_groups,
        source_freshness=freshness,
        history_days=history_days,
    )
    rotation = build_style_rotation(
        style_frames=style_frames,
        source_freshness=freshness,
        history_days=history_days,
    )
    for style_name, style_item in (rotation.get("styles") or {}).items():
        style_item["leadership_quality"] = (
            (leadership.get("styles") or {}).get(style_name, {}).get("raw_quality_state")
        )
    liquidity = build_liquidity_structure(
        close=close,
        amount=amount,
        breadth_history=breadth_history,
        concentration_history=concentration.get("history") or [],
        layered_breadth=layered,
        style_symbol_groups=style_symbol_groups,
        industry_groups=industry_groups,
        source_freshness=freshness,
        history_days=history_days,
    )
    repair = build_repair_structure(
        breadth_history=breadth_history,
        risk_structure=risk,
        source_freshness=freshness,
        history_days=history_days,
    )
    divergence = build_divergence_tracker(
        index_frames=clipped_indices,
        close=close,
        source_freshness=freshness,
        history_days=history_days,
    )
    index_lift_structure = build_index_lift_structure(
        primary_symbol=primary_symbol,
        close=close,
        amount=amount,
        metadata=metadata,
        index_frames=clipped_indices,
        index_member_frames=member_frames,
        as_of=cutoff,
        config=(config or {}).get("index_lift_structure", {}),
    )
    all_a_layer = layered.get("全A") or {}
    participation_tracker = _build_participation_tracker(all_a_layer, history_days)
    participation = {
        "state": participation_tracker["state"],
        "latest": all_a_layer.get("latest") or {},
        "history": participation_tracker["history"][-history_days:],
        "state_tracker": {key: value for key, value in participation_tracker.items() if key != "history"},
    }
    breadth_component = {
        "state": all_a_layer.get("state", UNKNOWN),
        "latest": all_a_layer.get("latest") or {},
        "history": all_a_layer.get("history") or [],
        "state_tracker": all_a_layer.get("state_tracker") or {},
    }

    quality_flags = sorted(
        set((base_structure.get("data_quality_flags") or []) + layer_flags + concentration_flags + (index_lift_structure.get("data_quality_flags") or []))
        | {
            "v2_descriptive_states_only",
            "current_stock_universe_not_point_in_time",
            "valuation_context_not_loaded",
            "external_context_not_loaded",
        }
    )
    if MARKET_BENCHMARK_SYMBOL in clipped_indices:
        quality_flags.append(MARKET_BENCHMARK_QUALITY_FLAG)
    quality_flags = sorted(set(quality_flags))

    components = {
        "participation": participation,
        "breadth": breadth_component,
        "concentration": concentration,
        "risk": risk,
        "leadership": leadership,
        "style": {
            "state": leadership.get("leader", UNKNOWN),
            "history": leadership.get("leader_history") or [],
        },
        "repair": repair,
        "divergence": divergence,
        "index_lift_structure": {
            "state": index_lift_structure.get("state", UNKNOWN),
            "history": index_lift_structure.get("history") or [],
        },
    }
    timeline = _state_timeline(components, history_days)
    coverage = finite((all_a_layer.get("latest") or {}).get("coverage")) or 0.0
    stock_fresh = freshness.get("stock_universe", {}).get("status") == "fresh"
    evidence = {
        "participation": evidence_block(
            state=participation["state"],
            supporting=[f"advance_ratio={(all_a_layer.get('latest') or {}).get('advance_ratio')}", f"equal_return={(all_a_layer.get('latest') or {}).get('equal_weight_return_1d')}"],
            contradicting=[], independent_family_count=2, freshness_ok=stock_fresh,
            coverage=coverage, point_in_time=False,
        ),
        "concentration": evidence_block(
            state=concentration["state"],
            supporting=[f"top10pct_turnover={(concentration.get('latest') or {}).get('top_10pct_turnover_share')}", f"top3_industry={(concentration.get('latest') or {}).get('top3_industry_positive_contribution_share')}", f"hhi={(concentration.get('latest') or {}).get('weight_hhi')}"],
            contradicting=[], independent_family_count=3, freshness_ok=stock_fresh,
            coverage=coverage, point_in_time=bool((concentration.get("latest") or {}).get("weight_point_in_time")),
        ),
        "risk": evidence_block(
            state=risk["state"],
            supporting=[f"extreme_declines={(risk.get('latest') or {}).get('extreme_decline_score')}", f"internal_damage={(risk.get('latest') or {}).get('internal_damage_score')}", f"disorder={(risk.get('latest') or {}).get('disorder_score')}"],
            contradicting=[], independent_family_count=int((risk.get("latest") or {}).get("evidence_family_count") or 0),
            freshness_ok=stock_fresh and freshness.get("amount", {}).get("status") == "fresh",
            coverage=coverage, point_in_time=False,
        ),
        "leadership": evidence_block(
            state=leadership["state"],
            supporting=[f"leader={leadership.get('leader')}", f"breadth={(leadership.get('latest') or {}).get('advance_ratio')}", f"top5={(leadership.get('latest') or {}).get('top5_positive_contribution_share')}"],
            contradicting=[], independent_family_count=3, freshness_ok=stock_fresh,
            coverage=coverage, point_in_time=False,
        ),
        "repair": evidence_block(
            state=repair["state"],
            supporting=[f"risk_change_5d={(repair.get('latest') or {}).get('risk_change_5d')}", f"new_low_change_5d={(repair.get('latest') or {}).get('new_low_change_5d')}", f"ma20_change={(repair.get('latest') or {}).get('pct_above_ma20_change_5d')}"],
            contradicting=[], independent_family_count=3, freshness_ok=stock_fresh,
            coverage=coverage, point_in_time=False,
        ),
        "index_lift_structure": evidence_block(
            state=index_lift_structure.get("state", UNKNOWN),
            supporting=index_lift_structure.get("supporting_evidence") or [],
            contradicting=index_lift_structure.get("contradicting_evidence") or [],
            independent_family_count=4,
            freshness_ok=stock_fresh and freshness.get("amount", {}).get("status") == "fresh",
            coverage=coverage,
            point_in_time=not bool(index_lift_structure.get("index_weight_not_point_in_time")),
        ),
    }
    research = _research_candidates(
        risk=risk,
        repair=repair,
        concentration=concentration,
        leadership=leadership,
        distribution=distribution,
        style_rotation=rotation,
    )
    summary = _deterministic_summary(
        base_structure=base_structure,
        layered=layered,
        concentration=concentration,
        leadership=leadership,
        risk=risk,
        repair=repair,
        style_rotation=rotation,
        index_lift_structure=index_lift_structure,
        quality_flags=quality_flags,
        source_freshness=freshness,
    )
    algorithm_config = {
        "history_days": history_days,
        "state_tracker": asdict(StateTrackerConfig()),
        "concentration_percentile_thresholds": [0.60, 0.80, 0.95],
        "risk_smoothing_days": [3, 5],
        **(config or {}),
    }
    point_in_time = {
        "as_of": cutoff.strftime("%Y-%m-%d"),
        "index_quotes": True,
        "index_weight_snapshots": bool(member_frames),
        "stock_universe": False,
        "industry_classification": False,
        "historical_st_status": False,
        "future_rows_used": False,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "algorithm_version": ALGORITHM_VERSION,
        "config_hash": canonical_hash(algorithm_config),
        "data_hash": _data_hash(close, amount, clipped_indices, member_frames),
        "source_freshness": freshness,
        "point_in_time": point_in_time,
        "market_structure": {
            "participation": participation,
            "concentration": concentration,
            "breadth": breadth_component,
            "leadership": leadership,
            "risk": risk,
            "style": rotation,
            "repair": repair,
            "divergence": divergence,
            "index_lift_structure": index_lift_structure,
            "state_history": timeline,
            "evidence": evidence,
        },
        "layered_breadth": layered,
        "contribution_analysis": concentration,
        "index_lift_structure": index_lift_structure,
        "return_distribution": distribution,
        "liquidity_structure": liquidity,
        "style_rotation": rotation,
        "industry_structure": industry_structure,
        "research_candidates": research,
        "valuation_context": {
            "status": UNKNOWN,
            "metrics": {"pe": None, "pb": None, "dividend_yield": None},
            "freshness": freshness["valuation"],
            "core_state_influence": False,
        },
        "external_context": {
            "status": UNKNOWN,
            "metrics": {"financing": None, "etf_flow": None, "accounts": None, "option_iv": None, "social": None},
            "freshness": freshness["external"],
            "core_state_influence": False,
        },
        "deterministic_summary": summary,
        "data_quality_flags": quality_flags,
        "index_state_gates": {
            key.split(":", 1)[1]: ("available" if value.get("status") == "fresh" else UNKNOWN)
            for key, value in freshness.items()
            if key.startswith("index:")
        },
        "llm_calls": 0,
        "formal_strategy_influence": False,
        "position_or_order_influence": False,
        "market_risk_gate_influence": False,
    }
