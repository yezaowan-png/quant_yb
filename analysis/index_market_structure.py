"""Current A-share market structure analysis for the existing index forecast flow."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from data.market_benchmark import (
    MARKET_BENCHMARK_NAME,
    MARKET_BENCHMARK_QUALITY_FLAG,
    MARKET_BENCHMARK_SOURCE,
    MARKET_BENCHMARK_SYMBOL,
    build_average_price_index_frame,
)

ALL_A_INDEX_NAME = MARKET_BENCHMARK_NAME
ALL_A_INDEX_SYMBOL = MARKET_BENCHMARK_SYMBOL

DEFAULT_THS_STYLE_PROXIES = {
    "权重价值": {
        "key": "value",
        "symbols": ("881155.TI", "881156.TI", "881105.TI", "881145.TI", "881180.TI"),
        "note": "银行、保险、煤炭、电力、石油加工贸易同花顺行业指数等权代理",
    },
    "证券风险偏好": {
        "key": "securities",
        "symbols": ("881157.TI",),
        "note": "证券同花顺行业指数代理",
    },
    "科技成长": {
        "key": "growth",
        "symbols": ("881121.TI", "881272.TI", "881129.TI", "881171.TI", "881144.TI"),
        "note": "半导体、软件开发、通信设备、自动化设备、医疗器械同花顺行业指数等权代理",
    },
    "消费": {
        "key": "consumer",
        "symbols": ("881133.TI", "881134.TI", "884188.TI", "881131.TI", "881125.TI", "881160.TI"),
        "note": "饮料制造、食品加工制造、白酒、白色家电、汽车整车、旅游及酒店同花顺行业指数等权代理",
    },
    "小盘题材": {
        "key": "small_cap",
        "symbols": ("700030.TI",),
        "note": "同花顺小盘指数代理",
    },
}

DEFAULT_FINANCIAL_SECTOR_THS_PROXIES = {
    "银行": {
        "key": "bank_sector",
        "symbols": ("881155.TI",),
        "note": "银行同花顺行业指数代理",
    },
    "保险": {
        "key": "insurance_sector",
        "symbols": ("881156.TI",),
        "note": "保险同花顺行业指数代理",
    },
    "证券": {
        "key": "securities_sector",
        "symbols": ("881157.TI",),
        "note": "证券同花顺行业指数代理",
    },
}

REQUIRED_INDICES = (
    ("上证指数", "000001.SH"),
    ("深证成指", "399001.SZ"),
    ("沪深300", "000300.SH"),
    ("上证50", "000016.SH"),
    ("中证500", "000905.SH"),
    ("中证1000", "000852.SH"),
    ("中证2000", "932000.CSI"),
    ("创业板指", "399006.SZ"),
    ("科创50", "000688.SH"),
    (ALL_A_INDEX_NAME, ALL_A_INDEX_SYMBOL),
)

STYLE_DEFINITIONS = {
    "value": {
        "name": "权重价值",
        "industries": (
            "银行", "保险", "石油开采", "石油加工", "石油贸易", "煤炭开采", "焦炭加工",
            "火力发电", "水力发电", "新型电力", "供气供热", "水务", "电信运营",
        ),
    },
    "securities": {"name": "证券风险偏好", "industries": ("证券",)},
    "growth": {
        "name": "科技成长",
        "industries": (
            "半导体", "元器件", "软件服务", "IT设备", "互联网", "通信设备", "电器仪表",
            "航空", "生物制药", "化学制药", "电气设备",
        ),
    },
    "consumer": {
        "name": "消费",
        "industries": (
            "食品", "白酒", "乳制品", "软饮料", "啤酒", "红黄酒", "家用电器", "汽车整车",
            "汽车配件", "百货", "超市连锁", "商贸代理", "旅游景点", "旅游服务", "酒店餐饮",
            "医疗保健", "家居用品",
        ),
    },
}

REGIME_NAMES = {
    "broad_strength": "全面强势",
    "value_defensive": "权重防御",
    "growth_risk_on": "成长进攻",
    "consumer_recovery": "消费修复",
    "mixed_rotation": "风格轮动",
    "broad_weakness": "全面弱势",
    "panic_recovery": "恐慌修复",
}

STYLE_REGIME_NAMES = {
    "broad": "全面占优",
    "rotation": "风格轮动",
    "value_led": "价值主导",
    "growth_led": "成长主导",
    "consumer_led": "消费主导",
    "broad_weakness": "全面弱势",
}

BREADTH_STATE_NAMES = {
    "strong": "强势",
    "strong_repair": "强修复",
    "neutral": "中性",
    "weak": "偏弱",
    "very_weak": "弱势",
}

DIVERGENCE_NAMES = {
    "stocks_stronger": "个股强于指数",
    "large_cap_stronger": "权重指数强于平均股价",
    "synchronized": "权重指数与平均股价大致同步",
    "unknown": "数据不足",
}


@dataclass
class StockMarketPanels:
    close: pd.DataFrame
    amount: pd.DataFrame
    metadata: pd.DataFrame
    open: pd.DataFrame | None = None
    high: pd.DataFrame | None = None
    low: pd.DataFrame | None = None
    volume: pd.DataFrame | None = None


def _clean_price_panel(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    return result.where(result > 0).astype("float32")


def load_stock_market_panels(
    cache_dir: str | Path,
    metadata_path: str | Path,
    dates: pd.Series | pd.DatetimeIndex | None = None,
) -> StockMarketPanels:
    """Load close and amount once; unavailable fields remain null."""
    root = Path(cache_dir)
    metadata_file = Path(metadata_path)
    metadata = pd.read_csv(metadata_file, dtype={"ts_code": str}) if metadata_file.exists() else pd.DataFrame()
    panel_series: dict[str, list[pd.Series]] = {
        "open": [],
        "high": [],
        "low": [],
        "close": [],
        "volume": [],
        "amount": [],
    }
    for path in sorted(root.glob("*.csv")):
        if path.name.startswith("_"):
            continue
        try:
            frame = pd.read_csv(
                path,
                usecols=lambda column: column in {"date", "open", "high", "low", "close", "volume", "amount"},
                dtype={"date": str},
            )
        except (OSError, ValueError, pd.errors.ParserError):
            continue
        if not {"date", "close"}.issubset(frame.columns):
            continue
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.dropna(subset=["date"]).drop_duplicates("date", keep="last").set_index("date")
        if frame.empty:
            continue
        symbol = path.stem.upper()
        for column in panel_series:
            series = (
                pd.to_numeric(frame.get(column), errors="coerce")
                if column in frame
                else pd.Series(np.nan, index=frame.index)
            )
            panel_series[column].append(series.rename(symbol))
    if not panel_series["close"]:
        return StockMarketPanels(pd.DataFrame(), pd.DataFrame(), metadata)
    panels = {column: pd.concat(series, axis=1).sort_index() for column, series in panel_series.items()}
    if dates is not None:
        wanted = pd.DatetimeIndex(pd.to_datetime(list(dates), errors="coerce")).dropna().unique().sort_values()
        panels = {column: frame.reindex(wanted) for column, frame in panels.items()}
    return StockMarketPanels(
        close=_clean_price_panel(panels["close"]),
        amount=panels["amount"].apply(pd.to_numeric, errors="coerce").astype("float32"),
        metadata=metadata,
        open=_clean_price_panel(panels["open"]),
        high=_clean_price_panel(panels["high"]),
        low=_clean_price_panel(panels["low"]),
        volume=panels["volume"].apply(pd.to_numeric, errors="coerce").astype("float32"),
    )


def _clip_frame_as_of(frame: pd.DataFrame, as_of: Any | None) -> pd.DataFrame:
    """Return a sorted copy whose date column never exceeds ``as_of``."""
    if frame is None or frame.empty or "date" not in frame.columns:
        return pd.DataFrame() if frame is None else frame.copy()
    work = frame.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work = work.dropna(subset=["date"])
    if as_of is not None:
        cutoff = pd.to_datetime(as_of, errors="coerce")
        if pd.notna(cutoff):
            work = work[work["date"] <= cutoff]
    return work.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)


def load_required_index_frames(
    cache_dir: str | Path,
    primary: pd.DataFrame,
    primary_symbol: str,
    as_of: Any | None = None,
) -> dict[str, pd.DataFrame]:
    """Load long index histories while enforcing the caller's point-in-time boundary.

    The primary frame usually reflects the CLI ``--end`` boundary.  Cached history is
    still useful for long K-lines and rolling indicators, but it must never extend
    beyond that boundary.
    """
    root = Path(cache_dir) / "index"
    primary_symbol = primary_symbol.upper()
    primary_dates = pd.to_datetime(primary.get("date"), errors="coerce") if "date" in primary.columns else pd.Series(dtype="datetime64[ns]")
    effective_as_of = pd.to_datetime(as_of, errors="coerce") if as_of is not None else primary_dates.max()
    frames: dict[str, pd.DataFrame] = {}
    symbols = list(dict.fromkeys([primary_symbol, *[symbol for _, symbol in REQUIRED_INDICES]]))
    for symbol in symbols:
        path = root / f"{symbol}.csv"
        if path.exists():
            frame = pd.read_csv(path, dtype={"date": str})
            if symbol == primary_symbol and primary is not None and not primary.empty:
                # Keep the cache's longer history but let the caller's frame win on
                # overlapping dates (for example, after an incremental refresh).
                frame = pd.concat([frame, primary], ignore_index=True, sort=False)
            clipped = _clip_frame_as_of(frame, effective_as_of)
            if "close" in clipped.columns:
                clipped = clipped.dropna(subset=["close"]).reset_index(drop=True)
            if not clipped.empty:
                frames[symbol] = clipped
        elif symbol == primary_symbol:
            clipped = _clip_frame_as_of(primary, effective_as_of)
            if not clipped.empty:
                frames[symbol] = clipped
    return frames


def _rolling_percentile(series: pd.Series, window: int = 756, min_periods: int = 60) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    return values.rolling(window, min_periods=min_periods).apply(
        lambda data: float(np.mean(data <= data[-1])) if np.isfinite(data[-1]) else np.nan,
        raw=True,
    )


def _approximate_price_limit_thresholds(metadata: pd.DataFrame, columns: pd.Index) -> pd.Series:
    """Return board-aware approximate daily price-limit thresholds.

    These thresholds deliberately leave a small allowance for exchange price
    rounding.  Historical ST status and no-limit IPO days remain unavailable in
    the current metadata and are disclosed as data-quality limitations.
    """
    threshold = pd.Series(0.095, index=columns, dtype="float64")
    if metadata.empty or "ts_code" not in metadata.columns:
        return threshold
    meta = metadata.drop_duplicates("ts_code").copy()
    meta.index = meta["ts_code"].astype(str).str.upper()
    names = meta["name"].reindex(columns).fillna("").astype(str) if "name" in meta else pd.Series("", index=columns)
    markets = meta["market"].reindex(columns).fillna("").astype(str) if "market" in meta else pd.Series("", index=columns)
    exchanges = meta["exchange"].reindex(columns).fillna("").astype(str).str.upper() if "exchange" in meta else pd.Series("", index=columns)
    threshold[names.str.contains("ST", case=False, regex=False)] = 0.048
    threshold[markets.isin(["创业板", "科创板"])] = 0.195
    threshold[markets.eq("北交所") | exchanges.eq("BSE")] = 0.295
    return threshold


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _index_metric(name: str, symbol: str, frame: pd.DataFrame | None) -> dict[str, Any]:
    empty = {"name": name, "symbol": symbol, "available": False, "proxy_used": False}
    if frame is None or frame.empty:
        return empty
    work = frame.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work["close"] = pd.to_numeric(work["close"], errors="coerce")
    work["amount"] = pd.to_numeric(work.get("amount"), errors="coerce")
    work = work.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    close = work["close"]
    for window in (20, 60, 120):
        work[f"ma{window}"] = close.rolling(window, min_periods=window).mean()
    work["ma20_slope"] = work["ma20"] / work["ma20"].shift(5) - 1.0
    work["ma60_slope"] = work["ma60"] / work["ma60"].shift(5) - 1.0
    for window in (20, 60):
        work[f"high_{window}"] = close.rolling(window, min_periods=window).max()
        work[f"low_{window}"] = close.rolling(window, min_periods=window).min()
    work["amount_ratio_20"] = work["amount"] / work["amount"].rolling(20, min_periods=20).mean()
    latest = work.iloc[-1]
    if latest["close"] > latest["ma20"] and latest["ma20_slope"] > 0 and (
        latest["close"] >= latest["ma60"] or latest["close"] / latest["ma60"] - 1 >= -0.02
    ):
        daily_trend = "uptrend"
    elif latest["close"] < latest["ma20"] and latest["ma20_slope"] < 0 and latest["close"] < latest["ma60"]:
        daily_trend = "downtrend"
    else:
        daily_trend = "sideways"
    weekly = work.set_index("date")["close"].resample("W-FRI").last().dropna().to_frame("close")
    # A W-FRI label later than the latest observation represents an unfinished
    # week.  Historical as-of reports must only use completed weekly bars.
    weekly = weekly[weekly.index <= latest["date"]]
    weekly["ma10"] = weekly["close"].rolling(10, min_periods=10).mean()
    weekly["ma20"] = weekly["close"].rolling(20, min_periods=20).mean()
    weekly["ma10_slope"] = weekly["ma10"] / weekly["ma10"].shift(2) - 1.0
    if weekly.empty:
        weekly_trend = "unknown"
    else:
        w = weekly.iloc[-1]
        weekly_trend = (
            "uptrend" if w["close"] > w["ma10"] and w["ma10_slope"] > 0 and w["close"] >= w["ma20"]
            else "downtrend" if w["close"] < w["ma10"] and w["ma10_slope"] < 0 and w["close"] < w["ma20"]
            else "sideways"
        )
    return {
        "name": name, "symbol": symbol, "available": True, "proxy_used": False,
        "date": latest["date"].strftime("%Y-%m-%d"), "close": _finite(latest["close"]),
        **{f"return_{window}d": _finite(close.iloc[-1] / close.shift(window).iloc[-1] - 1.0) for window in (1, 5, 10, 20, 60)},
        **{f"ma{window}": _finite(latest[f"ma{window}"]) for window in (20, 60, 120)},
        "ma20_state": "above" if latest["close"] >= latest["ma20"] else "below",
        "ma60_state": "above" if latest["close"] >= latest["ma60"] else "below",
        "ma20_slope": _finite(latest["ma20_slope"]), "ma60_slope": _finite(latest["ma60_slope"]),
        **{f"high_{window}d": _finite(latest[f"high_{window}"]) for window in (20, 60)},
        **{f"low_{window}d": _finite(latest[f"low_{window}"]) for window in (20, 60)},
        **{f"distance_high_{window}d": _finite(latest["close"] / latest[f"high_{window}"] - 1.0) for window in (20, 60)},
        **{f"distance_low_{window}d": _finite(latest["close"] / latest[f"low_{window}"] - 1.0) for window in (20, 60)},
        "amount_ratio_20d": _finite(latest["amount_ratio_20"]),
        "daily_trend": daily_trend, "weekly_trend": weekly_trend,
        "support_pressure": _support_pressure(latest),
    }


def _support_pressure(row: pd.Series) -> str:
    close = _finite(row.get("close"))
    if close is None:
        return "unknown"
    d20h = close / row.get("high_20") - 1.0 if pd.notna(row.get("high_20")) else np.nan
    d20l = close / row.get("low_20") - 1.0 if pd.notna(row.get("low_20")) else np.nan
    d60h = close / row.get("high_60") - 1.0 if pd.notna(row.get("high_60")) else np.nan
    d60l = close / row.get("low_60") - 1.0 if pd.notna(row.get("low_60")) else np.nan
    if d20h >= -0.01:
        return "接近20日压力或高位"
    if d60h >= -0.02:
        return "接近60日压力"
    if d20l <= 0.02:
        return "接近短期支撑"
    if d60l <= 0.03:
        return "接近中期支撑"
    return "区间中部"


def _group_columns(metadata: pd.DataFrame, columns: pd.Index, industries: tuple[str, ...]) -> dict[str, list[str]]:
    if metadata.empty or not {"ts_code", "industry"}.issubset(metadata.columns):
        return {}
    work = metadata[["ts_code", "industry"]].dropna().copy()
    work["ts_code"] = work["ts_code"].astype(str).str.upper()
    work = work[work["industry"].astype(str).isin(industries) & work["ts_code"].isin(columns)]
    return {
        str(industry): sorted(group["ts_code"].tolist())
        for industry, group in work.groupby("industry")
        if not group.empty
    }


def _basket_daily_return(daily: pd.DataFrame, groups: dict[str, list[str]]) -> pd.Series:
    industry_returns = [daily[symbols].mean(axis=1, skipna=True).rename(industry) for industry, symbols in groups.items() if symbols]
    return pd.concat(industry_returns, axis=1).mean(axis=1, skipna=True) if industry_returns else pd.Series(np.nan, index=daily.index)


def _group_ratio(condition: pd.DataFrame, valid: pd.DataFrame, symbols: list[str]) -> pd.Series:
    selected = [symbol for symbol in symbols if symbol in condition.columns]
    if not selected:
        return pd.Series(np.nan, index=condition.index)
    denominator = valid[selected].sum(axis=1).replace(0, np.nan)
    return (condition[selected] & valid[selected]).sum(axis=1) / denominator


def _amount_share(amount: pd.DataFrame, symbols: list[str], total: pd.Series) -> pd.Series:
    selected = [symbol for symbol in symbols if symbol in amount.columns]
    return amount[selected].sum(axis=1, min_count=1) / total.replace(0, np.nan) if selected else pd.Series(np.nan, index=amount.index)


def _all_industry_groups(metadata: pd.DataFrame, columns: pd.Index) -> dict[str, list[str]]:
    if metadata.empty or not {"ts_code", "industry"}.issubset(metadata.columns):
        return {}
    work = metadata[["ts_code", "industry"]].dropna().copy()
    work["ts_code"] = work["ts_code"].astype(str).str.upper()
    work["industry"] = work["industry"].astype(str).str.strip()
    work = work[work["ts_code"].isin(columns) & work["industry"].ne("")]
    return {
        industry: sorted(group["ts_code"].unique().tolist())
        for industry, group in work.groupby("industry")
        if not group.empty
    }


def _normalized_index_history(index_frames: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    series: dict[str, pd.Series] = {}
    for name, symbol in REQUIRED_INDICES:
        frame = index_frames.get(symbol)
        if frame is None or frame.empty:
            continue
        dates = pd.to_datetime(frame["date"], errors="coerce")
        values = pd.to_numeric(frame["close"], errors="coerce")
        item = pd.Series(values.to_numpy(), index=dates, name=name).dropna()
        if not item.empty:
            series[name] = item / item.iloc[0] * 1000.0
    if not series:
        return []
    frame = pd.concat(series, axis=1).sort_index()
    frame.insert(0, "trade_date", frame.index.strftime("%Y-%m-%d"))
    return _serialize_history(frame.reset_index(drop=True))


def _serialize_history(frame: pd.DataFrame) -> list[dict[str, Any]]:
    records = frame.replace([np.inf, -np.inf], np.nan).to_dict("records")
    serialized: list[dict[str, Any]] = []
    for row in records:
        normalized: dict[str, Any] = {}
        for key, value in row.items():
            if pd.isna(value):
                normalized[key] = None
            elif isinstance(value, pd.Timestamp):
                normalized[key] = value.strftime("%Y-%m-%d")
            elif isinstance(value, np.generic):
                normalized[key] = value.item()
            else:
                normalized[key] = value
        serialized.append(normalized)
    return serialized


RETURN_DISTRIBUTION_BUCKETS: tuple[tuple[str, float | None, float | None], ...] = (
    ("<-10%", None, -0.10),
    ("-10~-7%", -0.10, -0.07),
    ("-7~-5%", -0.07, -0.05),
    ("-5~-3%", -0.05, -0.03),
    ("-3~-1%", -0.03, -0.01),
    ("-1~0%", -0.01, 0.0),
    ("0~1%", 0.0, 0.01),
    ("1~3%", 0.01, 0.03),
    ("3~5%", 0.03, 0.05),
    ("5~7%", 0.05, 0.07),
    ("7~10%", 0.07, 0.10),
    (">10%", 0.10, None),
)


def _return_distribution(values: pd.Series) -> list[dict[str, Any]]:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    total = int(len(clean))
    rows: list[dict[str, Any]] = []
    for label, lower, upper in RETURN_DISTRIBUTION_BUCKETS:
        mask = pd.Series(True, index=clean.index)
        if lower is not None:
            mask &= clean >= lower
        if upper is not None:
            mask &= clean < upper
        count = int(mask.sum())
        rows.append(
            {
                "label": label,
                "lower": lower,
                "upper": upper,
                "count": count,
                "ratio": (count / total) if total else None,
            }
        )
    return rows


def _prepare_index_close(frame: pd.DataFrame | None, dates: pd.Index) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(np.nan, index=dates, dtype="float64")
    work = frame.copy()
    date_column = "date" if "date" in work.columns else "trade_date" if "trade_date" in work.columns else None
    if date_column is None or "close" not in work.columns:
        return pd.Series(np.nan, index=dates, dtype="float64")
    work[date_column] = pd.to_datetime(work[date_column], errors="coerce")
    work["close"] = pd.to_numeric(work["close"], errors="coerce")
    work = work.dropna(subset=[date_column, "close"]).drop_duplicates(date_column, keep="last")
    return work.set_index(date_column)["close"].sort_index().reindex(dates)


def _prepare_index_amount(frame: pd.DataFrame | None, dates: pd.Index) -> pd.Series:
    if frame is None or frame.empty or "amount" not in frame.columns:
        return pd.Series(np.nan, index=dates, dtype="float64")
    work = frame.copy()
    date_column = "date" if "date" in work.columns else "trade_date" if "trade_date" in work.columns else None
    if date_column is None:
        return pd.Series(np.nan, index=dates, dtype="float64")
    work[date_column] = pd.to_datetime(work[date_column], errors="coerce")
    work["amount"] = pd.to_numeric(work["amount"], errors="coerce")
    work = work.dropna(subset=[date_column]).drop_duplicates(date_column, keep="last")
    return work.set_index(date_column)["amount"].sort_index().reindex(dates)


def _normalize_style_proxy_config(config: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not config:
        return {name: dict(item) for name, item in DEFAULT_THS_STYLE_PROXIES.items()}
    normalized: dict[str, dict[str, Any]] = {}
    for name, default in DEFAULT_THS_STYLE_PROXIES.items():
        item = dict(default)
        override = config.get(name) or config.get(default["key"]) or {}
        if isinstance(override, dict):
            item.update({key: value for key, value in override.items() if value is not None})
        normalized[name] = item
    return normalized


def _build_ths_style_metric(
    name: str,
    item: dict[str, Any],
    frames: dict[str, pd.DataFrame],
    dates: pd.Index,
    all_a_returns: pd.DataFrame,
    hs300_ret20: pd.Series,
    min_history_bars: int = 60,
) -> tuple[dict[str, Any] | None, pd.DataFrame]:
    symbols = [str(symbol).upper() for symbol in item.get("symbols") or () if str(symbol).strip()]
    available = [symbol for symbol in symbols if symbol in frames and frames[symbol] is not None and not frames[symbol].empty]
    if not available:
        return None, pd.DataFrame(index=dates)
    closes = pd.DataFrame({symbol: _prepare_index_close(frames.get(symbol), dates) for symbol in available}, index=dates)
    amounts = pd.DataFrame({symbol: _prepare_index_amount(frames.get(symbol), dates) for symbol in available}, index=dates)
    history_bars = closes.dropna(how="all").shape[0]
    if history_bars < max(1, int(min_history_bars)):
        return None, pd.DataFrame(index=dates)
    daily = closes.pct_change(fill_method=None)
    basket_daily = daily.mean(axis=1, skipna=True)
    basket = (1.0 + basket_daily.fillna(0.0)).cumprod()
    history = pd.DataFrame(index=dates)
    key = str(item.get("key") or name)
    history["daily_return"] = basket_daily
    for window in (1, 5, 20, 60):
        history[f"return_{window}d"] = basket / basket.shift(window) - 1.0
        history[f"relative_all_a_{window}d"] = history[f"return_{window}d"] - all_a_returns.get(f"all_a_index_return_{window}d")
    ma20 = closes.rolling(20, min_periods=20).mean()
    ma60 = closes.rolling(60, min_periods=60).mean()
    valid = closes.notna()
    history["advance_ratio"] = (daily > 0).sum(axis=1) / daily.notna().sum(axis=1).replace(0, np.nan)
    history["pct_above_ma20"] = ((closes > ma20) & valid).sum(axis=1) / (valid & ma20.notna()).sum(axis=1).replace(0, np.nan)
    history["pct_above_ma60"] = ((closes > ma60) & valid).sum(axis=1) / (valid & ma60.notna()).sum(axis=1).replace(0, np.nan)
    amount = amounts.sum(axis=1, min_count=1)
    history["amount_ratio_20d"] = amount / amount.rolling(20, min_periods=20).mean()
    history["relative_hs300_20d"] = history["return_20d"] - hs300_ret20
    percentile_min_periods = min(60, max(20, history_bars // 3))
    p5 = _rolling_percentile(history["relative_all_a_5d"], min_periods=percentile_min_periods)
    p20 = _rolling_percentile(history["relative_all_a_20d"], min_periods=percentile_min_periods)
    pamount = _rolling_percentile(history["amount_ratio_20d"], min_periods=percentile_min_periods)
    components = pd.DataFrame(
        {
            "relative_5d": p5,
            "relative_20d": p20,
            "pct_above_ma20": history["pct_above_ma20"],
            "pct_above_ma60": history["pct_above_ma60"],
            "amount_ratio": pamount,
        },
        index=dates,
    )
    weights = pd.Series(
        {
            "relative_5d": 0.25,
            "relative_20d": 0.35,
            "pct_above_ma20": 0.20,
            "pct_above_ma60": 0.10,
            "amount_ratio": 0.10,
        }
    )
    available_weight = components.notna().mul(weights, axis=1).sum(axis=1)
    weighted_sum = components.mul(weights, axis=1).sum(axis=1, min_count=1)
    score = weighted_sum / available_weight.replace(0, np.nan) * 100
    required = p5.notna() & p20.notna() & history["pct_above_ma20"].notna()
    score[~required] = np.nan
    history["strength"] = score
    latest = history.iloc[-1]
    source_dates = [closes[symbol].last_valid_index() for symbol in available if closes[symbol].notna().any()]
    source_min_date = min(source_dates) if source_dates else None
    source_max_date = max(source_dates) if source_dates else None
    snapshot_date = pd.Timestamp(dates[-1]) if len(dates) else None
    strength = _finite(latest.get("strength"))
    state_5d = classify_style_period_state(latest.get("return_5d"), latest.get("relative_all_a_5d"))
    state_20d = classify_style_period_state(latest.get("return_20d"), latest.get("relative_all_a_20d"))
    state_60d = classify_style_period_state(latest.get("return_60d"), latest.get("relative_all_a_60d"))
    metric = {
        "key": key,
        "name": name,
        "basket_type": "ths_index_proxy",
        "available": True,
        "symbols": available,
        "missing_symbols": [symbol for symbol in symbols if symbol not in available],
        "proxy_note": str(item.get("note") or "同花顺指数代理"),
        "data_source": "Tushare ths_daily",
        "source_date_min": source_min_date.strftime("%Y-%m-%d") if source_min_date is not None else None,
        "source_date_max": source_max_date.strftime("%Y-%m-%d") if source_max_date is not None else None,
        "source_lag_calendar_days": (
            int((snapshot_date - source_min_date).days)
            if snapshot_date is not None and source_min_date is not None else None
        ),
        "index_count": len(available),
        "data_coverage": _finite(closes.iloc[-1].notna().sum() / len(available)) if available else None,
        **{f"return_{window}d": _finite(latest.get(f"return_{window}d")) for window in (1, 5, 20, 60)},
        "median_stock_return_5d": None,
        "median_stock_return_20d": None,
        "advance_ratio": _finite(latest.get("advance_ratio")),
        "pct_above_ma20": _finite(latest.get("pct_above_ma20")),
        "pct_above_ma60": _finite(latest.get("pct_above_ma60")),
        "new_high_20_ratio": None,
        "new_low_20_ratio": None,
        "amount": _finite(amount.iloc[-1]) if not amount.empty else None,
        "amount_share": None,
        "amount_share_change_5d": None,
        "amount_share_change_20d": None,
        "amount_ratio_20d": _finite(latest.get("amount_ratio_20d")),
        "relative_all_a_5d": _finite(latest.get("relative_all_a_5d")),
        "relative_all_a_20d": _finite(latest.get("relative_all_a_20d")),
        "relative_all_a_60d": _finite(latest.get("relative_all_a_60d")),
        "relative_hs300_20d": _finite(latest.get("relative_hs300_20d")),
        "strength": strength,
        "strength_state": None if strength is None else "strong" if strength >= 65 else "weak" if strength < 35 else "neutral",
        "state_5d": state_5d,
        "state_20d": state_20d,
        "state_60d": state_60d,
        "momentum_direction": _style_momentum_direction(state_5d, state_20d, state_60d),
        "industry_count": None,
        "stock_count": None,
        "valid_stock_count": None,
        "industry_contributions": {},
    }
    prefixed = history.add_prefix(f"{key}_")
    return metric, prefixed


def _build_ths_industry_rankings(
    frames: dict[str, pd.DataFrame],
    names: dict[str, str],
    dates: pd.Index,
) -> dict[str, Any] | None:
    rows: list[dict[str, Any]] = []
    for symbol, frame in frames.items():
        if not symbol.endswith(".TI") or frame is None or frame.empty:
            continue
        name = names.get(symbol, symbol)
        close = _prepare_index_close(frame, dates)
        if close.dropna().empty:
            continue
        amount = _prepare_index_amount(frame, dates)
        latest = close.iloc[-1]
        if pd.isna(latest):
            continue
        row = {
            "industry": name,
            "symbol": symbol,
            "return_1d": _finite(latest / close.shift(1).iloc[-1] - 1.0),
            "return_5d": _finite(latest / close.shift(5).iloc[-1] - 1.0),
            "return_20d": _finite(latest / close.shift(20).iloc[-1] - 1.0),
            "return_60d": _finite(latest / close.shift(60).iloc[-1] - 1.0),
            "advance_ratio": None,
            "pct_above_ma20": _finite(float(latest >= close.rolling(20, min_periods=20).mean().iloc[-1])) if pd.notna(close.rolling(20, min_periods=20).mean().iloc[-1]) else None,
            "amount_share_change_20d": _finite(amount.iloc[-1] / amount.shift(20).iloc[-1] - 1.0) if pd.notna(amount.iloc[-1]) and pd.notna(amount.shift(20).iloc[-1]) and amount.shift(20).iloc[-1] else None,
            "stock_count": None,
            "valid_stock_count": None,
            "data_coverage": None,
        }
        if row["return_1d"] is not None:
            rows.append(row)
    if not rows:
        return None
    return {
        "rank_basis": "return_1d",
        "all": sorted(rows, key=lambda row: float(row["return_1d"]), reverse=True),
        "strongest": sorted(rows, key=lambda row: float(row["return_1d"]), reverse=True)[:10],
        "weakest": sorted(rows, key=lambda row: float(row["return_1d"]))[:10],
        "method_note": "同花顺行业指数行情口径，来源 Tushare ths_daily；行业成分由同花顺维护。",
    }


def classify_market_style_regime(
    *,
    risk_repairing: bool,
    breadth_state: str,
    tail_level: str,
    value_state: str | None,
    growth_state: str | None,
    securities_state: str | None,
    small_return_20d: float | None,
    hs300_return_20d: float | None,
    all_a_return_20d: float | None,
    bank_return_20d: float | None,
    securities_return_20d: float | None,
    consumer_state: str | None,
    consumer_relative_20d: float | None,
    consumer_advance_ratio: float | None,
    amount_ratio_20: float | None,
) -> str:
    """Classify one mutually-exclusive regime using an explicit fixed priority."""
    value_strong = value_state == "strong"
    growth_strong = growth_state == "strong"
    growth_weak = growth_state == "weak"
    securities_not_weak = securities_state in {"neutral", "strong"}
    if risk_repairing:
        return "panic_recovery"
    if breadth_state == "weak" and tail_level in {"high", "extreme"} and not value_strong and not growth_strong:
        return "broad_weakness"
    if breadth_state == "strong" and tail_level in {"low", "medium"} and not growth_weak and value_state != "weak":
        return "broad_strength"
    if (
        growth_strong
        and securities_not_weak
        and breadth_state != "weak"
        and (small_return_20d is None or hs300_return_20d is None or small_return_20d > hs300_return_20d)
        and (amount_ratio_20 is None or amount_ratio_20 >= 0.8)
    ):
        return "growth_risk_on"
    if (
        value_strong
        and growth_weak
        and hs300_return_20d is not None
        and all_a_return_20d is not None
        and hs300_return_20d > all_a_return_20d
        and bank_return_20d is not None
        and securities_return_20d is not None
        and bank_return_20d > securities_return_20d
    ):
        return "value_defensive"
    if (
        consumer_state == "strong"
        and consumer_relative_20d is not None
        and consumer_relative_20d > 0
        and consumer_advance_ratio is not None
        and consumer_advance_ratio > 0.5
    ):
        return "consumer_recovery"
    return "mixed_rotation"


def classify_period_divergence(
    large_cap_return: float | None,
    all_a_equal_return: float | None,
    threshold: float = 0.003,
) -> str:
    """Compare a cap-weighted index with the all-A equal-weight return."""
    large = _finite(large_cap_return)
    equal = _finite(all_a_equal_return)
    if large is None or equal is None:
        return "unknown"
    gap = equal - large
    if gap >= threshold:
        return "stocks_stronger"
    if gap <= -threshold:
        return "large_cap_stronger"
    return "synchronized"


def classify_breadth_periods(latest: pd.Series | dict[str, Any]) -> dict[str, str]:
    """Return independent today/5-day/20-day breadth states."""
    row = latest if isinstance(latest, dict) else latest.to_dict()
    advance = _finite(row.get("advance_ratio"))
    median1 = _finite(row.get("median_stock_return_1d"))
    equal1 = _finite(row.get("equal_weight_return_1d"))
    ad1 = _finite(row.get("normalized_ad"))
    def period_state(window: int) -> str:
        ad = _finite(row.get(f"normalized_ad_{window}d"))
        equal_ret = _finite(row.get(f"equal_weight_return_{window}d"))
        median_ret = _finite(row.get(f"median_stock_return_{window}d"))
        values = [ad, equal_ret, median_ret]
        if any(value is None for value in values):
            return "neutral"
        positive = sum(value > 0 for value in values)
        negative = sum(value < 0 for value in values)
        if positive >= 2:
            return "strong"
        if negative >= 2:
            if window == 20 and _finite(row.get("pct_above_ma20")) is not None and float(row["pct_above_ma20"]) < 0.30:
                return "very_weak"
            return "weak"
        return "neutral"

    short = period_state(5)
    medium = period_state(20)
    broad_advance = bool(
        None not in {advance, median1, equal1, ad1}
        and advance >= 0.60 and median1 > 0 and equal1 > 0 and ad1 > 0
    )
    if broad_advance and (short in {"weak", "very_weak"} or medium in {"weak", "very_weak"}):
        today = "strong_repair"
    elif None not in {advance, median1, ad1} and advance >= 0.55 and median1 > 0 and ad1 > 0:
        today = "strong"
    elif None not in {advance, median1, ad1} and advance <= 0.40 and median1 < 0 and ad1 < 0:
        today = "weak"
    else:
        today = "neutral"
    if today == "strong_repair" and short in {"weak", "very_weak"} and medium in {"weak", "very_weak"}:
        summary = "short_repair_medium_weak"
    elif short == "strong" and medium == "strong":
        summary = "broad_strength"
    elif short in {"weak", "very_weak"} and medium in {"weak", "very_weak"}:
        summary = "persistent_weakness"
    else:
        summary = "mixed"
    return {
        "today_state": today,
        "short_5d_state": short,
        "medium_20d_state": medium,
        "summary": summary,
    }


def classify_style_period_state(return_value: Any, relative_return: Any) -> str:
    """Classify one style at one horizon without collapsing other horizons."""
    absolute = _finite(return_value)
    relative = _finite(relative_return)
    if absolute is None:
        return "unknown"
    if absolute <= -0.03:
        return "weak"
    if absolute < -0.005:
        return "pullback" if relative is not None and relative > 0 else "weak"
    if absolute < 0.005:
        return "neutral"
    if relative is not None and relative > 0 and absolute >= 0.02:
        return "strong"
    if relative is not None and relative > 0:
        return "outperforming"
    return "recovering"


def classify_risk_directions(breadth: pd.DataFrame, pressure_level: str) -> dict[str, str]:
    """Describe whether tail-risk evidence is expanding or contracting today."""
    if len(breadth) < 2:
        return {
            "new_low_direction": "stable", "large_decline_direction": "stable",
            "ad_direction": "stable", "nhnl_direction": "stable", "risk_direction": "stable",
        }
    latest, previous = breadth.iloc[-1], breadth.iloc[-2]

    def lower_is_better(column: str, tolerance: float = 1e-12) -> str:
        current, prior = _finite(latest.get(column)), _finite(previous.get(column))
        if current is None or prior is None or abs(current - prior) <= tolerance:
            return "stable"
        return "contracting" if current < prior else "expanding"

    def higher_is_better(column: str, tolerance: float = 1e-12) -> str:
        current, prior = _finite(latest.get(column)), _finite(previous.get(column))
        if current is None or prior is None or abs(current - prior) <= tolerance:
            return "stable"
        return "contracting" if current > prior else "expanding"

    directions = {
        "new_low_direction": lower_is_better("new_low_20_ratio"),
        "large_decline_direction": lower_is_better("decline_gt_5_ratio"),
        "ad_direction": higher_is_better("normalized_ad"),
        "nhnl_direction": higher_is_better("normalized_nhnl_20"),
    }
    contracting = sum(value == "contracting" for value in directions.values())
    expanding = sum(value == "expanding" for value in directions.values())
    if pressure_level in {"high", "extreme"} and contracting >= 3:
        risk_direction = "repairing"
    elif contracting >= 3:
        risk_direction = "contracting"
    elif expanding >= 3:
        risk_direction = "expanding"
    else:
        risk_direction = "stable"
    directions["risk_direction"] = risk_direction
    return directions


def _consensus_trend(metrics: list[dict[str, Any]], key: str) -> str:
    values = [str(item.get(key)) for item in metrics if item.get("available") and item.get(key)]
    if not values:
        return "unknown"
    return values[0] if all(value == values[0] for value in values) else "mixed"


def _style_momentum_direction(state_5d: str, state_20d: str, state_60d: str) -> str:
    if state_5d in {"weak", "pullback"} and state_20d in {"strong", "outperforming"}:
        return "mid_leading_short_pullback"
    if state_5d in {"strong", "outperforming"} and state_20d in {"weak", "pullback"}:
        return "short_rebound_mid_weak"
    if state_5d in {"strong", "outperforming"} and state_20d in {"strong", "outperforming"}:
        return "strengthening"
    if state_5d in {"weak", "pullback"} and state_20d in {"weak", "pullback"}:
        return "weakening"
    if state_60d == "strong" and state_20d in {"weak", "pullback"}:
        return "long_strong_mid_cooling"
    return "mixed"


def build_market_structure(
    primary_symbol: str,
    index_frames: dict[str, pd.DataFrame],
    panels: StockMarketPanels,
    ths_index_frames: dict[str, pd.DataFrame] | None = None,
    ths_index_names: dict[str, str] | None = None,
    ths_industry_symbols: set[str] | None = None,
    ths_style_config: dict[str, Any] | None = None,
    ths_industry_min_available: int = 20,
    ths_style_min_history_bars: int = 60,
    as_of: Any | None = None,
    index_member_frames: dict[str, pd.DataFrame] | None = None,
    market_structure_v2_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if panels.close.empty:
        raise ValueError("市场结构分析需要本地个股收盘价缓存")
    effective_as_of = pd.to_datetime(as_of, errors="coerce") if as_of is not None else pd.to_datetime(panels.close.index, errors="coerce").max()
    if pd.isna(effective_as_of):
        raise ValueError("市场结构分析缺少有效 as-of 日期")
    close = panels.close.loc[pd.to_datetime(panels.close.index, errors="coerce") <= effective_as_of].copy()
    if close.empty:
        raise ValueError("市场结构分析在 as-of 日期前没有个股数据")
    amount = panels.amount.reindex(index=close.index, columns=close.columns)
    open_panel = (
        getattr(panels, "open", None).reindex(index=close.index, columns=close.columns)
        if getattr(panels, "open", None) is not None else None
    )
    high_panel = (
        getattr(panels, "high", None).reindex(index=close.index, columns=close.columns)
        if getattr(panels, "high", None) is not None else None
    )
    low_panel = (
        getattr(panels, "low", None).reindex(index=close.index, columns=close.columns)
        if getattr(panels, "low", None) is not None else None
    )
    volume_panel = (
        getattr(panels, "volume", None).reindex(index=close.index, columns=close.columns)
        if getattr(panels, "volume", None) is not None else None
    )
    panels = StockMarketPanels(
        close=close,
        amount=amount,
        metadata=panels.metadata,
        open=open_panel,
        high=high_panel,
        low=low_panel,
        volume=volume_panel,
    )
    index_frames = {
        str(symbol).upper(): clipped
        for symbol, frame in index_frames.items()
        if not (clipped := _clip_frame_as_of(frame, effective_as_of)).empty
    }
    ths_index_frames = {
        str(symbol).upper(): clipped
        for symbol, frame in (ths_index_frames or {}).items()
        if not (clipped := _clip_frame_as_of(frame, effective_as_of)).empty
    }
    average_price_frame = build_average_price_index_frame(
        close=panels.close,
        amount=panels.amount,
        open_=panels.open,
        high=panels.high,
        low=panels.low,
        volume=panels.volume,
    )
    if not average_price_frame.empty:
        index_frames[ALL_A_INDEX_SYMBOL] = average_price_frame
    daily = close.pct_change(fill_method=None)
    # A valid breadth observation must have both a return and positive turnover.
    # This excludes suspended/no-trade rows instead of counting unchanged closes as flat.
    valid_daily = daily.notna() & amount.notna() & amount.gt(0)
    valid_count = valid_daily.sum(axis=1).replace(0, np.nan)
    up = ((daily > 0) & valid_daily).sum(axis=1)
    down = ((daily < 0) & valid_daily).sum(axis=1)
    flat = ((daily == 0) & valid_daily).sum(axis=1)
    equal_return = daily.where(valid_daily).mean(axis=1, skipna=True)
    total_amount = amount.sum(axis=1, min_count=1)
    all_a_frame = index_frames.get(ALL_A_INDEX_SYMBOL)
    all_a_close = pd.Series(np.nan, index=close.index, dtype="float64")
    if all_a_frame is not None and not all_a_frame.empty:
        all_a_work = all_a_frame.copy()
        all_a_work["date"] = pd.to_datetime(all_a_work["date"], errors="coerce")
        all_a_work["close"] = pd.to_numeric(all_a_work["close"], errors="coerce")
        all_a_work = all_a_work.dropna(subset=["date", "close"]).drop_duplicates("date", keep="last")
        all_a_close = all_a_work.set_index("date")["close"].reindex(close.index)
    breadth = pd.DataFrame(index=close.index)
    breadth["trade_date"] = breadth.index.strftime("%Y-%m-%d")
    breadth["advance_count"] = up
    breadth["decline_count"] = down
    breadth["flat_count"] = flat
    breadth["valid_stock_count"] = valid_count
    breadth["advance_ratio"] = up / valid_count
    breadth["decline_ratio"] = down / valid_count
    breadth["median_stock_return_1d"] = daily.where(valid_daily).median(axis=1, skipna=True)
    breadth["equal_weight_return_1d"] = equal_return
    breadth["all_a_index_return_1d"] = all_a_close.pct_change(fill_method=None)
    for window in (5, 20, 60):
        terminal = (close / close.shift(window) - 1.0).where(valid_daily)
        breadth[f"median_stock_return_{window}d"] = terminal.median(axis=1, skipna=True)
        breadth[f"equal_weight_return_{window}d"] = terminal.mean(axis=1, skipna=True)
        breadth[f"all_a_index_return_{window}d"] = all_a_close / all_a_close.shift(window) - 1.0
    breadth["normalized_ad"] = (up - down) / (up + down).replace(0, np.nan)
    breadth["normalized_ad_5d"] = breadth["normalized_ad"].rolling(5, min_periods=5).sum()
    breadth["normalized_ad_20d"] = breadth["normalized_ad"].rolling(20, min_periods=20).sum()
    breadth["ad_line_rebased"] = breadth["normalized_ad"].fillna(0).cumsum()
    breadth["ad_slope_5"] = breadth["ad_line_rebased"] - breadth["ad_line_rebased"].shift(5)
    breadth["ad_slope_20"] = breadth["ad_line_rebased"] - breadth["ad_line_rebased"].shift(20)

    style_groups: dict[str, dict[str, list[str]]] = {
        key: _group_columns(panels.metadata, close.columns, definition["industries"])
        for key, definition in STYLE_DEFINITIONS.items()
    }
    industry_groups = _all_industry_groups(panels.metadata, close.columns)
    style_symbols = {key: sorted({symbol for symbols in groups.values() for symbol in symbols}) for key, groups in style_groups.items()}
    style_history = pd.DataFrame(index=close.index)
    style_history["trade_date"] = style_history.index.strftime("%Y-%m-%d")
    style_daily: dict[str, pd.Series] = {}
    for key, groups in style_groups.items():
        style_daily[key] = _basket_daily_return(daily.where(valid_daily), groups)
        style_history[f"{key}_daily_return"] = style_daily[key]

    for window in (20, 50, 200):
        moving_average = close.rolling(window, min_periods=window).mean()
        valid = close.notna() & moving_average.notna() & amount.notna() & amount.gt(0)
        condition = close > moving_average
        breadth[f"pct_above_ma{window}"] = (condition & valid).sum(axis=1) / valid.sum(axis=1).replace(0, np.nan)
        if window in (20,):
            for key, symbols in style_symbols.items():
                style_history[f"{key}_pct_above_ma20"] = _group_ratio(condition, valid, symbols)
        if window == 50:
            # Page contract uses MA50 for all-A breadth; styles use MA60 below.
            pass
    ma60 = close.rolling(60, min_periods=60).mean()
    valid_ma60 = close.notna() & ma60.notna() & amount.notna() & amount.gt(0)
    for key, symbols in style_symbols.items():
        style_history[f"{key}_pct_above_ma60"] = _group_ratio(close > ma60, valid_ma60, symbols)

    for window in (20, 60, 120, 250):
        historical_high = close.rolling(window, min_periods=window).max().shift(1)
        historical_low = close.rolling(window, min_periods=window).min().shift(1)
        valid = (
            close.notna() & historical_high.notna() & historical_low.notna()
            & amount.notna() & amount.gt(0)
        )
        new_high = (close > historical_high) & valid
        new_low = (close < historical_low) & valid
        denominator = valid.sum(axis=1).replace(0, np.nan)
        breadth[f"new_high_{window}_count"] = new_high.sum(axis=1)
        breadth[f"new_low_{window}_count"] = new_low.sum(axis=1)
        breadth[f"new_high_{window}_ratio"] = new_high.sum(axis=1) / denominator
        breadth[f"new_low_{window}_ratio"] = new_low.sum(axis=1) / denominator
        breadth[f"normalized_nhnl_{window}"] = (new_high.sum(axis=1) - new_low.sum(axis=1)) / denominator
        if window == 20:
            for key, symbols in style_symbols.items():
                style_history[f"{key}_new_high_20_ratio"] = _group_ratio(new_high, valid, symbols)
                style_history[f"{key}_new_low_20_ratio"] = _group_ratio(new_low, valid, symbols)
    breadth["new_low_20_change_5d"] = breadth["new_low_20_count"] - breadth["new_low_20_count"].shift(5)
    breadth["nhnl_20_slope_5"] = breadth["normalized_nhnl_20"] - breadth["normalized_nhnl_20"].shift(5)

    breadth["decline_gt_3_ratio"] = ((daily <= -0.03) & valid_daily).sum(axis=1) / valid_count
    breadth["decline_gt_5_ratio"] = ((daily <= -0.05) & valid_daily).sum(axis=1) / valid_count
    breadth["advance_gt_3_ratio"] = ((daily >= 0.03) & valid_daily).sum(axis=1) / valid_count
    breadth["advance_gt_5_ratio"] = ((daily >= 0.05) & valid_daily).sum(axis=1) / valid_count
    threshold = _approximate_price_limit_thresholds(panels.metadata, close.columns)
    breadth["approximate_limit_down_ratio"] = (daily.le(-threshold, axis=1) & valid_daily).sum(axis=1) / valid_count
    breadth["approximate_limit_up_ratio"] = (daily.ge(threshold, axis=1) & valid_daily).sum(axis=1) / valid_count
    breadth["cross_section_dispersion"] = daily.where(valid_daily).std(axis=1, skipna=True)
    breadth["market_realized_volatility_5d"] = breadth["all_a_index_return_1d"].rolling(5, min_periods=5).std(ddof=0) * np.sqrt(252)
    breadth["total_market_amount"] = total_amount
    breadth["amount_ma5"] = total_amount.rolling(5, min_periods=5).mean()
    breadth["amount_ma20"] = total_amount.rolling(20, min_periods=20).mean()
    breadth["amount_ratio_20"] = total_amount / breadth["amount_ma20"]
    breadth["advance_amount_ratio"] = amount.where(daily > 0).sum(axis=1, min_count=1) / total_amount.replace(0, np.nan)
    breadth["decline_amount_ratio"] = amount.where(daily < 0).sum(axis=1, min_count=1) / total_amount.replace(0, np.nan)

    index_metrics = {
        name: _index_metric(name, symbol, index_frames.get(symbol))
        for name, symbol in REQUIRED_INDICES
    }
    all_a_metric = index_metrics[ALL_A_INDEX_NAME]
    all_a_metric.update({
        "official": False,
        "vendor": "同花顺",
        "source": MARKET_BENCHMARK_SOURCE,
        "synthetic": True,
    })
    hs300 = index_metrics["沪深300"]
    hs300_frame = index_frames.get("000300.SH")
    hs300_close = pd.Series(np.nan, index=close.index)
    if hs300_frame is not None and not hs300_frame.empty:
        temp = hs300_frame.copy()
        temp.index = pd.to_datetime(temp["date"], errors="coerce")
        hs300_close = pd.to_numeric(temp["close"], errors="coerce").reindex(close.index)
    hs300_ret5 = hs300_close / hs300_close.shift(5) - 1.0
    hs300_ret20 = hs300_close / hs300_close.shift(20) - 1.0
    all_a_returns = breadth[[f"all_a_index_return_{window}d" for window in (1, 5, 20, 60)]].copy()

    style_metrics: dict[str, dict[str, Any]] = {}
    for key, definition in STYLE_DEFINITIONS.items():
        groups = style_groups[key]
        symbols = style_symbols[key]
        basket = (1.0 + style_daily[key].fillna(0.0)).cumprod()
        for window in (1, 5, 20, 60):
            style_history[f"{key}_return_{window}d"] = basket / basket.shift(window) - 1.0
        for window in (5, 20):
            terminal = (
                (close[symbols] / close[symbols].shift(window) - 1.0).where(valid_daily[symbols])
                if symbols else pd.DataFrame(index=close.index)
            )
            style_history[f"{key}_median_return_{window}d"] = terminal.median(axis=1, skipna=True) if symbols else np.nan
        style_history[f"{key}_advance_ratio"] = _group_ratio(daily > 0, valid_daily, symbols)
        share = _amount_share(amount, symbols, total_amount)
        style_history[f"{key}_amount"] = amount[symbols].sum(axis=1, min_count=1) if symbols else np.nan
        style_history[f"{key}_amount_share"] = share
        style_history[f"{key}_amount_share_change_5d"] = share - share.shift(5)
        style_history[f"{key}_amount_share_change_20d"] = share - share.shift(20)
        style_history[f"{key}_relative_all_a_5d"] = style_history[f"{key}_return_5d"] - breadth["all_a_index_return_5d"]
        style_history[f"{key}_relative_all_a_20d"] = style_history[f"{key}_return_20d"] - breadth["all_a_index_return_20d"]
        style_history[f"{key}_relative_all_a_60d"] = style_history[f"{key}_return_60d"] - breadth["all_a_index_return_60d"]
        style_history[f"{key}_relative_hs300_20d"] = style_history[f"{key}_return_20d"] - hs300_ret20
        internal_ad = (
            ((daily[symbols] > 0).sum(axis=1) - (daily[symbols] < 0).sum(axis=1))
            / ((daily[symbols] > 0).sum(axis=1) + (daily[symbols] < 0).sum(axis=1)).replace(0, np.nan)
            if symbols else pd.Series(np.nan, index=close.index)
        )
        style_history[f"{key}_internal_ad_5d"] = internal_ad.rolling(5, min_periods=5).sum()
        p5 = _rolling_percentile(style_history[f"{key}_relative_all_a_5d"])
        p20 = _rolling_percentile(style_history[f"{key}_relative_all_a_20d"])
        pad = _rolling_percentile(style_history[f"{key}_internal_ad_5d"])
        pamount = _rolling_percentile(style_history[f"{key}_amount_share_change_20d"])
        components = pd.concat([p5, p20, style_history[f"{key}_pct_above_ma20"], pad, pamount], axis=1)
        score = (0.20 * p5 + 0.30 * p20 + 0.20 * style_history[f"{key}_pct_above_ma20"] + 0.15 * pad + 0.15 * pamount) * 100
        score[components.isna().any(axis=1)] = np.nan
        style_history[f"{key}_strength"] = score
        latest = style_history.iloc[-1]
        strength = _finite(latest[f"{key}_strength"])
        contribution_rows: dict[int, list[dict[str, Any]]] = {5: [], 20: []}
        for industry, members in groups.items():
            current_valid = [symbol for symbol in members if bool(valid_daily[symbol].iloc[-1])]
            for window in (5, 20):
                terminal = (close[members] / close[members].shift(window) - 1.0).where(valid_daily[members])
                industry_return = _finite(terminal.iloc[-1].mean())
                contribution_rows[window].append(
                    {
                        "industry": industry,
                        "return": industry_return,
                        "contribution": _finite(industry_return / len(groups)) if industry_return is not None and groups else None,
                        "stock_count": len(members),
                        "valid_stock_count": len(current_valid),
                    }
                )

        def contribution_slice(window: int, reverse: bool) -> list[dict[str, Any]]:
            usable = [row for row in contribution_rows[window] if row["return"] is not None]
            return sorted(usable, key=lambda row: float(row["return"]), reverse=reverse)[:3]

        state_5d = classify_style_period_state(latest[f"{key}_return_5d"], latest[f"{key}_relative_all_a_5d"])
        state_20d = classify_style_period_state(latest[f"{key}_return_20d"], latest[f"{key}_relative_all_a_20d"])
        state_60d = classify_style_period_state(latest[f"{key}_return_60d"], latest[f"{key}_relative_all_a_60d"])
        latest_valid_count = int(valid_daily[symbols].iloc[-1].sum()) if symbols else 0
        style_metrics[definition["name"]] = {
            "key": key, "name": definition["name"], "basket_type": "stock_basket", "available": bool(symbols),
            "industry_count": len(groups), "stock_count": len(symbols),
            "valid_stock_count": latest_valid_count,
            "data_coverage": _finite(latest_valid_count / len(symbols)) if symbols else None,
            **{f"return_{window}d": _finite(latest[f"{key}_return_{window}d"]) for window in (1, 5, 20, 60)},
            "median_stock_return_5d": _finite(latest[f"{key}_median_return_5d"]),
            "median_stock_return_20d": _finite(latest[f"{key}_median_return_20d"]),
            "advance_ratio": _finite(latest[f"{key}_advance_ratio"]),
            "pct_above_ma20": _finite(latest[f"{key}_pct_above_ma20"]),
            "pct_above_ma60": _finite(latest[f"{key}_pct_above_ma60"]),
            "new_high_20_ratio": _finite(latest[f"{key}_new_high_20_ratio"]),
            "new_low_20_ratio": _finite(latest[f"{key}_new_low_20_ratio"]),
            "amount": _finite(latest[f"{key}_amount"]), "amount_share": _finite(latest[f"{key}_amount_share"]),
            "amount_share_change_5d": _finite(latest[f"{key}_amount_share_change_5d"]),
            "amount_share_change_20d": _finite(latest[f"{key}_amount_share_change_20d"]),
            "relative_all_a_5d": _finite(latest[f"{key}_relative_all_a_5d"]),
            "relative_all_a_20d": _finite(latest[f"{key}_relative_all_a_20d"]),
            "relative_all_a_60d": _finite(latest[f"{key}_relative_all_a_60d"]),
            "relative_hs300_20d": _finite(latest[f"{key}_relative_hs300_20d"]),
            "strength": strength,
            "strength_state": None if strength is None else "strong" if strength >= 65 else "weak" if strength < 35 else "neutral",
            "state_5d": state_5d, "state_20d": state_20d, "state_60d": state_60d,
            "momentum_direction": _style_momentum_direction(state_5d, state_20d, state_60d),
            "industry_contributions": {
                "top_5d": contribution_slice(5, True), "bottom_5d": contribution_slice(5, False),
                "top_20d": contribution_slice(20, True), "bottom_20d": contribution_slice(20, False),
            },
        }

    # Small-cap uses an official index only; no current-constituent history is backfilled.
    small = index_metrics["中证1000"]
    small_frame = index_frames.get("000852.SH")
    small_strength = None
    if small_frame is not None and not small_frame.empty:
        proxy = small_frame.copy()
        proxy.index = pd.to_datetime(proxy["date"], errors="coerce")
        proxy_close = pd.to_numeric(proxy["close"], errors="coerce").reindex(close.index)
        proxy_amount = pd.to_numeric(proxy.get("amount"), errors="coerce").reindex(close.index)
        proxy_ma20 = proxy_close.rolling(20, min_periods=20).mean()
        proxy_ma60 = proxy_close.rolling(60, min_periods=60).mean()
        proxy_ret5 = proxy_close / proxy_close.shift(5) - 1.0
        proxy_ret20 = proxy_close / proxy_close.shift(20) - 1.0
        proxy_amount_ratio = proxy_amount / proxy_amount.rolling(20, min_periods=20).mean()
        small_components = pd.concat(
            [
                _rolling_percentile(proxy_ret5 - hs300_ret5),
                _rolling_percentile(proxy_ret20 - hs300_ret20),
                (proxy_close >= proxy_ma20).astype(float),
                (proxy_close >= proxy_ma60).astype(float),
                _rolling_percentile(proxy_amount_ratio),
            ],
            axis=1,
        )
        small_score = (
            0.25 * small_components.iloc[:, 0]
            + 0.35 * small_components.iloc[:, 1]
            + 0.20 * small_components.iloc[:, 2]
            + 0.10 * small_components.iloc[:, 3]
            + 0.10 * small_components.iloc[:, 4]
        ) * 100.0
        small_score[small_components.isna().any(axis=1)] = np.nan
        style_history["small_cap_strength"] = small_score
        small_strength = _finite(small_score.iloc[-1])
    else:
        style_history["small_cap_strength"] = np.nan

    small_relative_all_a = {
        window: (
            _finite(small.get(f"return_{window}d") - breadth[f"all_a_index_return_{window}d"].iloc[-1])
            if small.get(f"return_{window}d") is not None and pd.notna(breadth[f"all_a_index_return_{window}d"].iloc[-1]) else None
        )
        for window in (5, 20, 60)
    }
    small_states = {
        window: classify_style_period_state(small.get(f"return_{window}d"), small_relative_all_a[window])
        for window in (5, 20, 60)
    }
    style_metrics["小盘题材"] = {
        "key": "small_cap", "name": "小盘题材", "basket_type": "official_index_proxy",
        "available": bool(small.get("available")), "official_index_proxy": "000852.SH",
        "proxy_used": bool(small.get("available")), "proxy_note": "指数代理，无内部个股广度",
        **{f"return_{window}d": small.get(f"return_{window}d") for window in (1, 5, 20, 60)},
        "ma20": small.get("ma20"), "ma60": small.get("ma60"),
        "ma20_state": small.get("ma20_state"), "ma60_state": small.get("ma60_state"),
        "amount_ratio_20d": small.get("amount_ratio_20d"),
        "relative_hs300_5d": _difference(small, hs300, "return_5d"),
        "relative_hs300_20d": _difference(small, hs300, "return_20d"),
        "relative_hs300_60d": _difference(small, hs300, "return_60d"),
        "relative_all_a_5d": small_relative_all_a[5],
        "relative_all_a_20d": small_relative_all_a[20],
        "relative_all_a_60d": small_relative_all_a[60],
        "median_stock_return_5d": None, "median_stock_return_20d": None,
        "advance_ratio": None, "pct_above_ma20": None, "pct_above_ma60": None,
        "new_high_20_ratio": None, "new_low_20_ratio": None, "amount": None,
        "amount_share": None, "amount_share_change_5d": None, "amount_share_change_20d": None,
        "strength": small_strength,
        "strength_state": None if small_strength is None else "strong" if small_strength >= 65 else "weak" if small_strength < 35 else "neutral",
        "state_5d": small_states[5], "state_20d": small_states[20], "state_60d": small_states[60],
        "momentum_direction": _style_momentum_direction(small_states[5], small_states[20], small_states[60]),
        "industry_count": None, "stock_count": None, "valid_stock_count": None,
        "data_coverage": None, "industry_contributions": {},
    }

    ths_frames = {str(symbol).upper(): frame for symbol, frame in (ths_index_frames or {}).items() if frame is not None and not frame.empty}
    ths_names = {str(symbol).upper(): str(name) for symbol, name in (ths_index_names or {}).items()}
    ths_style_used = False
    if ths_frames:
        style_proxy_config = _normalize_style_proxy_config(ths_style_config)
        proxy_histories: list[pd.DataFrame] = []
        for style_name, proxy_item in style_proxy_config.items():
            metric, proxy_history = _build_ths_style_metric(
                style_name,
                proxy_item,
                ths_frames,
                close.index,
                all_a_returns,
                hs300_ret20,
                ths_style_min_history_bars,
            )
            if metric is None:
                continue
            style_metrics[style_name] = metric
            if not proxy_history.empty:
                proxy_histories.append(proxy_history)
            ths_style_used = True
        if proxy_histories:
            proxy_history_frame = pd.concat(proxy_histories, axis=1)
            overlapping_columns = [column for column in proxy_history_frame.columns if column in style_history.columns]
            if overlapping_columns:
                style_history = style_history.drop(columns=overlapping_columns)
            style_history = pd.concat([style_history, proxy_history_frame], axis=1)

    industry_rows: list[dict[str, Any]] = []
    ma20_all = close.rolling(20, min_periods=20).mean()
    for industry, members in industry_groups.items():
        valid_today = valid_daily[members].iloc[-1]
        valid_total = int(valid_today.sum())
        if valid_total == 0:
            continue
        returns = {
            window: (close[members] / close[members].shift(window) - 1.0).where(valid_daily[members])
            for window in (5, 20)
        }
        share = _amount_share(amount, members, total_amount)
        industry_rows.append(
            {
                "industry": industry,
                "return_1d": _finite(daily[members].iloc[-1].where(valid_today).mean()),
                "return_5d": _finite(returns[5].iloc[-1].mean()),
                "return_20d": _finite(returns[20].iloc[-1].mean()),
                "advance_ratio": _finite(((daily[members].iloc[-1] > 0) & valid_today).sum() / valid_total),
                "pct_above_ma20": _finite(((close[members].iloc[-1] > ma20_all[members].iloc[-1]) & valid_today).sum() / valid_total),
                "amount_share_change_20d": _finite(share.iloc[-1] - share.shift(20).iloc[-1]),
                "stock_count": len(members), "valid_stock_count": valid_total,
                "data_coverage": _finite(valid_total / len(members)),
            }
        )
    ranked_industries = [row for row in industry_rows if row.get("return_1d") is not None]
    industry_rankings = {
        "rank_basis": "return_1d",
        "all": sorted(ranked_industries, key=lambda row: float(row["return_1d"]), reverse=True),
        "strongest": sorted(ranked_industries, key=lambda row: float(row["return_1d"]), reverse=True)[:10],
        "weakest": sorted(ranked_industries, key=lambda row: float(row["return_1d"]))[:10],
        "method_note": "当前行业分类回溯口径，历史比较置信度有限。",
    }
    if ths_frames and ths_industry_symbols:
        industry_symbols = {str(symbol).upper() for symbol in ths_industry_symbols}
        ths_industry_frames = {symbol: frame for symbol, frame in ths_frames.items() if symbol in industry_symbols}
        required_industry_count = min(max(1, int(ths_industry_min_available)), len(industry_symbols))
        ths_rankings = _build_ths_industry_rankings(ths_industry_frames, ths_names, close.index)
        if ths_rankings and len(ths_industry_frames) >= required_industry_count:
            industry_rankings = ths_rankings

    b = breadth.iloc[-1]
    up_p65 = _rolling_percentile(breadth["advance_ratio"]).iloc[-1]
    ma20_p = _rolling_percentile(breadth["pct_above_ma20"]).iloc[-1]
    strong_conditions = [b["advance_ratio"] >= 0.55 or up_p65 >= 0.65, b["pct_above_ma20"] >= 0.60 or ma20_p >= 0.65, b["normalized_ad_5d"] > 0, b["median_stock_return_1d"] > 0]
    weak_conditions = [b["advance_ratio"] <= 0.40 or up_p65 <= 0.35, b["pct_above_ma20"] <= 0.40 or ma20_p <= 0.35, b["normalized_ad_5d"] < 0, b["median_stock_return_1d"] < 0]
    breadth_state = "strong" if sum(bool(x) for x in strong_conditions) >= 3 else "weak" if sum(bool(x) for x in weak_conditions) >= 3 else "neutral"
    pressure_flags = [
        _rolling_percentile(breadth["decline_gt_5_ratio"]).iloc[-1] >= 0.90,
        _rolling_percentile(breadth["approximate_limit_down_ratio"]).iloc[-1] >= 0.90,
        _rolling_percentile(breadth["cross_section_dispersion"]).iloc[-1] >= 0.90,
        _rolling_percentile(breadth["market_realized_volatility_5d"]).iloc[-1] >= 0.90,
        _rolling_percentile(breadth["new_low_20_ratio"]).iloc[-1] >= 0.90,
    ]
    pressure_count = sum(bool(x) for x in pressure_flags)
    tail_level = "extreme" if pressure_count >= 4 else "high" if pressure_count >= 3 else "medium" if pressure_count >= 1 else "low"
    breadth_periods = classify_breadth_periods(b)
    risk_directions = classify_risk_directions(breadth, tail_level)
    risk_repairing = bool(
        tail_level in {"high", "extreme"} and b["new_low_20_change_5d"] < 0
        and b["ad_slope_5"] > 0 and b["nhnl_20_slope_5"] > 0
    )
    tail_state = "risk_repairing" if risk_repairing else "risk_expanding" if tail_level in {"high", "extreme"} and b["new_low_20_change_5d"] > 0 else "stable"
    amount_ratio = _finite(b["amount_ratio_20"])
    liquidity_state = "normal"
    if amount_ratio is not None:
        if amount_ratio >= 1.5 and abs(b["all_a_index_return_1d"]) < 0.003:
            liquidity_state = "high_volume_stalling"
        elif b["all_a_index_return_1d"] > 0 and amount_ratio > 1.1:
            liquidity_state = "advance_on_volume"
        elif b["all_a_index_return_1d"] < 0 and amount_ratio > 1.1:
            liquidity_state = "decline_on_volume"
        elif b["all_a_index_return_1d"] > 0 and amount_ratio < 0.8:
            liquidity_state = "low_volume_rebound"

    primary_name = next((name for name, symbol in REQUIRED_INDICES if symbol == primary_symbol), primary_symbol)
    primary_metric = index_metrics.get(primary_name, _index_metric(primary_name, primary_symbol, index_frames.get(primary_symbol)))
    period_divergence = {
        "one_day": classify_period_divergence(hs300.get("return_1d"), all_a_metric.get("return_1d")),
        "five_day": classify_period_divergence(hs300.get("return_5d"), all_a_metric.get("return_5d")),
        "twenty_day": classify_period_divergence(hs300.get("return_20d"), all_a_metric.get("return_20d")),
    }
    divergence_evidence = {
        "one_day_gap": _difference(all_a_metric, hs300, "return_1d"),
        "five_day_gap": _difference(all_a_metric, hs300, "return_5d"),
        "twenty_day_gap": _difference(all_a_metric, hs300, "return_20d"),
    }
    if period_divergence == {
        "one_day": "stocks_stronger", "five_day": "large_cap_stronger", "twenty_day": "large_cap_stronger"
    }:
        divergence_summary = "短期个股强，中期权重强"
    elif period_divergence["one_day"] == period_divergence["five_day"] == period_divergence["twenty_day"]:
        divergence_summary = DIVERGENCE_NAMES[period_divergence["one_day"]]
    else:
        divergence_summary = "指数与个股多周期分化"
    hs300_ret1 = hs300.get("return_1d") or 0.0
    equal1 = float(all_a_metric.get("return_1d") or 0.0)
    divergences = {
        "weight_only_rally": bool((hs300_ret1 > 0 or (primary_metric.get("return_1d") or 0) > 0) and equal1 < hs300_ret1 - 0.003 and b["advance_ratio"] < 0.50 and b["normalized_ad"] < 0),
        "stocks_outperform_index": bool(hs300_ret1 <= 0 and equal1 > hs300_ret1 + 0.003 and b["advance_ratio"] > 0.55 and b["ad_slope_5"] > 0),
        "index_high_breadth_weak": bool((hs300.get("distance_high_20d") or -1) >= -0.02 and breadth["pct_above_ma20"].iloc[-1] < breadth["pct_above_ma20"].shift(5).iloc[-1] and b["new_high_20_count"] < breadth["new_high_20_count"].shift(5).iloc[-1] and b["new_low_20_count"] > breadth["new_low_20_count"].shift(5).iloc[-1]),
        "low_level_internal_repair": bool((hs300.get("distance_low_60d") or 1) <= 0.08 and b["new_low_20_change_5d"] < 0 and b["ad_slope_5"] > 0 and b["nhnl_20_slope_5"] > 0 and b["advance_ratio"] > 0.50),
    }
    value = style_metrics["权重价值"]
    growth = style_metrics["科技成长"]
    consumer = style_metrics["消费"]
    securities = style_metrics["证券风险偏好"]
    fallback_financial_sectors = {
        "银行": _sector_snapshot("银行", style_groups, daily, valid_daily, close, amount, total_amount),
        "保险": _sector_snapshot("保险", style_groups, daily, valid_daily, close, amount, total_amount),
        "证券": securities,
    }
    financial_sector_proxies: dict[str, dict[str, Any]] = {}
    if ths_frames:
        for sector_name, proxy_item in DEFAULT_FINANCIAL_SECTOR_THS_PROXIES.items():
            metric, _proxy_history = _build_ths_style_metric(
                sector_name,
                proxy_item,
                ths_frames,
                close.index,
                all_a_returns,
                hs300_ret20,
                ths_style_min_history_bars,
            )
            if metric is not None:
                financial_sector_proxies[sector_name] = metric
    sector_details = {
        name: financial_sector_proxies.get(name) or fallback
        for name, fallback in fallback_financial_sectors.items()
    }
    financial_sector_proxy_used = bool(financial_sector_proxies)
    bank = sector_details["银行"]
    insurance = sector_details["保险"]
    securities_sector = sector_details["证券"]
    small_return = style_metrics["小盘题材"].get("return_20d")
    legacy_regime = classify_market_style_regime(
        risk_repairing=risk_repairing,
        breadth_state=breadth_state,
        tail_level=tail_level,
        value_state=value.get("strength_state"),
        growth_state=growth.get("strength_state"),
        securities_state=securities.get("strength_state"),
        small_return_20d=small_return,
        hs300_return_20d=hs300.get("return_20d"),
        all_a_return_20d=all_a_metric.get("return_20d"),
        bank_return_20d=bank.get("return_20d"),
        securities_return_20d=securities_sector.get("return_20d"),
        consumer_state=consumer.get("strength_state"),
        consumer_relative_20d=consumer.get("relative_all_a_20d"),
        consumer_advance_ratio=consumer.get("advance_ratio"),
        amount_ratio_20=amount_ratio,
    )

    def style_leader(window: int) -> str | None:
        candidates = [
            item for item in style_metrics.values()
            if item.get("available") and item.get(f"return_{window}d") is not None
        ]
        return max(candidates, key=lambda item: float(item[f"return_{window}d"]))["name"] if candidates else None

    style_leaders = {window: style_leader(window) for window in (5, 20, 60)}
    if breadth_periods["short_5d_state"] == "strong" and breadth_periods["medium_20d_state"] == "strong":
        style_regime = "broad"
    elif (
        breadth_periods["short_5d_state"] in {"weak", "very_weak"}
        and breadth_periods["medium_20d_state"] in {"weak", "very_weak"}
        and tail_level in {"high", "extreme"}
    ):
        style_regime = "broad_weakness"
    elif style_leaders[20] == "权重价值" and value.get("state_20d") in {"strong", "outperforming"}:
        style_regime = "value_led"
    elif style_leaders[20] == "科技成长" and growth.get("state_20d") in {"strong", "outperforming"}:
        style_regime = "growth_led"
    elif style_leaders[20] == "消费" and consumer.get("state_20d") in {"strong", "outperforming"}:
        style_regime = "consumer_led"
    else:
        style_regime = "rotation"

    large_cap_metric = hs300 if hs300.get("available") else primary_metric
    growth_metrics = [index_metrics["创业板指"], index_metrics["科创50"]]
    trend_dimensions = {
        "large_cap_daily": large_cap_metric.get("daily_trend", "unknown"),
        "large_cap_weekly": large_cap_metric.get("weekly_trend", "unknown"),
        "growth_daily": _consensus_trend(growth_metrics, "daily_trend"),
        "growth_weekly": _consensus_trend(growth_metrics, "weekly_trend"),
        "large_cap_name": large_cap_metric.get("name"),
        "growth_evidence": {
            item["name"]: {"daily": item.get("daily_trend"), "weekly": item.get("weekly_trend")}
            for item in growth_metrics if item.get("available")
        },
    }

    if (
        period_divergence["one_day"] == "stocks_stronger"
        and (hs300.get("return_1d") or 0) < 0
        and (all_a_metric.get("return_1d") or 0) > 0
    ):
        today_text = "今日主要权重指数下跌，但平均股价和多数个股上涨，短期个股表现明显强于权重指数。"
    else:
        today_text = (
            f"今日{DIVERGENCE_NAMES[period_divergence['one_day']]}，"
            f"当日赚钱效应为{BREADTH_STATE_NAMES[breadth_periods['today_state']]}。"
        )
    five_text = (
        f"最近5日，{DIVERGENCE_NAMES[period_divergence['five_day']]}，"
        f"5日市场广度{BREADTH_STATE_NAMES[breadth_periods['short_5d_state']]}。"
    )
    twenty_text = (
        f"最近20日，{DIVERGENCE_NAMES[period_divergence['twenty_day']]}，"
        f"20日市场广度{BREADTH_STATE_NAMES[breadth_periods['medium_20d_state']]}。"
    )
    style_text = (
        f"中期主导风格为{style_leaders[20] or '数据不足'}；"
        f"科技成长5日{_style_state_cn(growth.get('state_5d'))}、20日{_style_state_cn(growth.get('state_20d'))}，"
        f"证券5日{_style_state_cn(securities.get('state_5d'))}、20日{_style_state_cn(securities.get('state_20d'))}。"
    )
    risk_text = (
        f"尾部压力处于{_tail_cn(tail_level)}水平，风险方向{_risk_direction_cn(risk_directions['risk_direction'])}，"
        f"当前属于{STYLE_REGIME_NAMES[style_regime]}。"
    )
    headline = today_text + five_text + twenty_text + style_text + risk_text
    divergence_text = divergence_summary
    data_quality_flags = [
        "incomplete_point_in_time_universe",
        "missing_delisted_stocks",
        "missing_historical_st_status",
        "current_tushare_industry_classification_used_for_history",
        "theme_history_not_backfilled",
        "limit_up_down_is_board_aware_approximation",
        "historical_ipo_no_limit_days_not_excluded",
        MARKET_BENCHMARK_QUALITY_FLAG,
    ]
    if (style_metrics.get("小盘题材") or {}).get("basket_type") == "official_index_proxy":
        data_quality_flags.append("small_cap_official_index_proxy_used")
    if ths_style_used:
        data_quality_flags.append("ths_style_proxy_indexes_used")
    if financial_sector_proxy_used:
        data_quality_flags.append("financial_sector_proxy_indexes_used")
    if (industry_rankings.get("method_note") or "").startswith("同花顺行业指数"):
        data_quality_flags.append("ths_industry_rankings_used")
    for name, metric in index_metrics.items():
        if not metric.get("available"):
            data_quality_flags.append(f"missing_index_data:{name}:{metric['symbol']}")

    relative_strength = {
        "value_vs_growth_5d": _difference(value, growth, "return_5d"),
        "value_vs_growth_20d": _difference(value, growth, "return_20d"),
        "value_vs_growth_60d": _difference(value, growth, "return_60d"),
        "securities_vs_bank_5d": _difference(securities_sector, bank, "return_5d"),
        "securities_vs_bank_20d": _difference(securities_sector, bank, "return_20d"),
        "consumer_vs_all_a_20d": consumer.get("relative_all_a_20d"),
        "small_vs_hs300_20d": style_metrics["小盘题材"].get("relative_hs300_20d"),
        "hs300_vs_all_a_5d": _difference(hs300, all_a_metric, "return_5d"),
        "hs300_vs_all_a_20d": _difference(hs300, all_a_metric, "return_20d"),
    }
    latest_breadth = {key: _finite(value) if not isinstance(value, str) else value for key, value in b.to_dict().items()}
    latest_returns = daily.iloc[-1].where(valid_daily.iloc[-1])
    return_distribution = _return_distribution(latest_returns)
    result = {
        "date": str(breadth.iloc[-1]["trade_date"]),
        "market_structure": {
            "trend": trend_dimensions,
            "breadth": breadth_periods,
            "risk": {"pressure_level": tail_level, **risk_directions},
            "style": {
                "leader_5d": style_leaders[5], "leader_20d": style_leaders[20],
                "leader_60d": style_leaders[60], "regime": style_regime,
                "regime_name": STYLE_REGIME_NAMES[style_regime],
            },
            "divergence": {**period_divergence, "summary": divergence_summary, "evidence": divergence_evidence},
            # Compatibility fields retained for dashboard and older consumers.
            "trend_state": primary_metric.get("daily_trend"), "weekly_trend": primary_metric.get("weekly_trend"),
            "breadth_state": breadth_periods["medium_20d_state"], "tail_pressure_state": tail_level,
            "tail_direction": risk_directions["risk_direction"],
            "style_regime": style_regime, "style_regime_name": STYLE_REGIME_NAMES[style_regime],
            "legacy_style_regime": legacy_regime, "legacy_style_regime_name": REGIME_NAMES[legacy_regime],
            "market_participation": divergence_text, "liquidity_state": liquidity_state,
            "headline": headline,
            "detail_lines": [
                f"上涨/下跌/平盘家数：{int(b['advance_count'])}/{int(b['decline_count'])}/{int(b['flat_count'])}",
                f"MA20上方股票比例：{b['pct_above_ma20']:.1%}",
                f"20日新高/新低比例：{b['new_high_20_ratio']:.1%}/{b['new_low_20_ratio']:.1%}",
                "当前结构状态只描述当下，不表示未来收益概率。",
            ],
        },
        "indices": index_metrics,
        "index_history": _normalized_index_history(index_frames),
        "all_a_index": {
            "name": ALL_A_INDEX_NAME, "symbol": ALL_A_INDEX_SYMBOL, "official": False,
            "vendor": "同花顺", "source": MARKET_BENCHMARK_SOURCE, "synthetic": True,
        },
        "breadth": {
            "latest": latest_breadth,
            "history": _serialize_history(breadth),
            "return_distribution": return_distribution,
        },
        "styles": style_metrics, "style_history": _serialize_history(style_history),
        "industry_rankings": industry_rankings,
        "sector_details": sector_details,
        "tail_pressure": {
            "state": tail_level, "direction": risk_directions["risk_direction"], **risk_directions,
            "current_pressure_only": True, "not_future_probability": True,
        },
        "liquidity": {"state": liquidity_state, "amount_ratio_20": amount_ratio},
        "divergences": divergences, "relative_strength": relative_strength,
        "technical_indicators": {"role": "辅助描述短期位置和趋势动量，不单独决定市场状态"},
        "legacy_forecast": {}, "data_quality_flags": sorted(set(data_quality_flags)),
    }
    # V2 is an additive deterministic description layer.  Existing keys remain
    # available so dashboards and legacy forecast diagnostics keep their public
    # contracts, while overlapping state dictionaries retain old fields.
    from analysis.market_structure_v2 import build_market_structure_v2

    v2_style_symbols = {
        definition["name"]: style_symbols.get(key, [])
        for key, definition in STYLE_DEFINITIONS.items()
    }
    v2_style_industries = {
        definition["name"]: style_groups.get(key, {})
        for key, definition in STYLE_DEFINITIONS.items()
    }
    v2_style_proxy_symbols = {
        str(symbol).upper()
        for item in _normalize_style_proxy_config(ths_style_config).values()
        for symbol in (item.get("symbols") or [])
    }
    v2 = build_market_structure_v2(
        primary_symbol=primary_symbol,
        base_structure=result,
        panels=panels,
        index_frames=index_frames,
        index_member_frames=index_member_frames,
        ths_index_frames=ths_index_frames,
        style_proxy_symbols=v2_style_proxy_symbols,
        industry_proxy_symbols={str(symbol).upper() for symbol in (ths_industry_symbols or set())},
        style_symbol_groups=v2_style_symbols,
        style_industry_groups=v2_style_industries,
        industry_groups=industry_groups,
        as_of=effective_as_of,
        config=market_structure_v2_config,
    )
    v2_market = v2.pop("market_structure")
    for key, value in v2_market.items():
        if isinstance(value, dict) and isinstance(result["market_structure"].get(key), dict):
            result["market_structure"][key] = {**result["market_structure"][key], **value}
        else:
            result["market_structure"][key] = value
    summary = v2.get("deterministic_summary") or {}
    if summary.get("headline"):
        result["market_structure"]["headline"] = summary["headline"]
        result["market_structure"]["detail_lines"] = summary.get("lines") or []
    for key, value in v2.items():
        if key == "data_quality_flags":
            result[key] = sorted(set(result.get(key) or []) | set(value or []))
        else:
            result[key] = value
    for symbol, gate in (result.get("index_state_gates") or {}).items():
        if gate != "unknown":
            continue
        for metric in result.get("indices", {}).values():
            if metric.get("symbol") == symbol:
                metric["state_status"] = "unknown"
                metric["daily_trend"] = "unknown"
                metric["weekly_trend"] = "unknown"
    trend = result.get("market_structure", {}).get("trend") or {}
    freshness = result.get("source_freshness") or {}
    if freshness.get("index:000300.SH", {}).get("status") != "fresh":
        trend["large_cap_daily"] = "unknown"
        trend["large_cap_weekly"] = "unknown"
    growth_statuses = [
        freshness.get("index:399006.SZ", {}).get("status"),
        freshness.get("index:000688.SH", {}).get("status"),
    ]
    if not any(status == "fresh" for status in growth_statuses):
        trend["growth_daily"] = "unknown"
        trend["growth_weekly"] = "unknown"
    all_a = result.get("indices", {}).get(ALL_A_INDEX_NAME) or {}
    if all_a.get("amount_ratio_20d") is None:
        all_a.pop("amount_ratio_20d", None)
        all_a["amount_ratio_20d_status"] = "local_proxy_amount_unavailable"
    return result


def _sector_snapshot(
    industry: str,
    style_groups: dict[str, dict[str, list[str]]],
    daily: pd.DataFrame,
    valid_daily: pd.DataFrame,
    close: pd.DataFrame,
    amount: pd.DataFrame,
    total_amount: pd.Series,
) -> dict[str, Any]:
    symbols = sorted({symbol for groups in style_groups.values() for name, members in groups.items() if name == industry for symbol in members})
    if not symbols:
        return {"name": industry, "available": False}
    terminal5 = close[symbols] / close[symbols].shift(5) - 1.0
    terminal20 = close[symbols] / close[symbols].shift(20) - 1.0
    ma20 = close[symbols].rolling(20, min_periods=20).mean()
    valid_today = valid_daily[symbols].iloc[-1]
    return {
        "name": industry, "available": True, "stock_count": len(symbols),
        "return_1d": _finite(daily[symbols].iloc[-1].where(valid_today).mean()),
        "return_5d": _finite(terminal5.iloc[-1].where(valid_today).mean()),
        "return_20d": _finite(terminal20.iloc[-1].where(valid_today).mean()),
        "advance_ratio": _finite((daily[symbols].iloc[-1].where(valid_today) > 0).sum() / valid_today.sum()) if valid_today.any() else None,
        "pct_above_ma20": _finite((close[symbols].iloc[-1].where(valid_today) > ma20.iloc[-1].where(valid_today)).sum() / valid_today.sum()) if valid_today.any() else None,
        "amount": _finite(amount[symbols].sum(axis=1, min_count=1).iloc[-1]),
        "amount_share": _finite(_amount_share(amount, symbols, total_amount).iloc[-1]),
    }


def _difference(left: dict[str, Any], right: dict[str, Any], key: str) -> float | None:
    a, b = left.get(key), right.get(key)
    return _finite(float(a) - float(b)) if a is not None and b is not None else None


def _trend_cn(value: str | None) -> str:
    return {"uptrend": "偏强", "downtrend": "偏弱", "sideways": "震荡"}.get(str(value), "数据不足")


def _breadth_cn(value: str) -> str:
    return {"strong": "偏强", "weak": "偏弱", "neutral": "中性"}.get(value, value)


def _tail_cn(value: str) -> str:
    return {"low": "较低", "medium": "中等", "high": "较高", "extreme": "极端"}.get(value, value)


def _liquidity_cn(value: str) -> str:
    return {
        "normal": "正常", "advance_on_volume": "上涨放量", "decline_on_volume": "下跌放量",
        "low_volume_rebound": "缩量反弹", "high_volume_stalling": "成交异常、巨量滞涨",
    }.get(value, value)


def _style_state_cn(value: str | None) -> str:
    return {
        "strong": "强势", "outperforming": "相对占优", "recovering": "修复",
        "neutral": "中性", "pullback": "回调", "weak": "弱势", "unknown": "数据不足",
    }.get(str(value), "数据不足")


def _risk_direction_cn(value: str | None) -> str:
    return {
        "expanding": "正在扩散", "stable": "相对稳定",
        "contracting": "正在收缩", "repairing": "正在修复",
    }.get(str(value), "数据不足")


def attach_market_structure_columns(indicators: pd.DataFrame, structure: dict[str, Any]) -> pd.DataFrame:
    history = pd.DataFrame(structure.get("breadth", {}).get("history") or [])
    if history.empty:
        return indicators.copy()
    duplicate = [column for column in history.columns if column != "trade_date" and column in indicators.columns]
    history = history.drop(columns=duplicate)
    result = indicators.merge(history, on="trade_date", how="left", validate="one_to_one").copy()
    latest_date = str(structure.get("date"))
    latest_mask = result["trade_date"].astype(str) == latest_date
    state_columns = pd.DataFrame(
        {
            "market_style_regime": pd.Series(None, index=result.index, dtype="object"),
            "market_breadth_state": pd.Series(None, index=result.index, dtype="object"),
            "market_tail_pressure_state": pd.Series(None, index=result.index, dtype="object"),
        }
    )
    result = pd.concat([result, state_columns], axis=1)
    result.loc[latest_mask, "market_style_regime"] = structure["market_structure"]["style_regime"]
    result.loc[latest_mask, "market_breadth_state"] = structure["market_structure"]["breadth_state"]
    result.loc[latest_mask, "market_tail_pressure_state"] = structure["market_structure"]["tail_pressure_state"]
    return result


def save_market_structure_outputs(config: dict, symbol: str, structure: dict[str, Any]) -> dict[str, Path]:
    root = Path(config["output"].get("statistics_dir", "output/statistics")) / "index_forecast"
    root.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": root / f"market_structure_{symbol.upper()}.json",
        "indices": root / f"market_structure_indices_{symbol.upper()}.csv",
        "breadth": root / f"market_structure_breadth_{symbol.upper()}.csv",
        "styles": root / f"market_structure_styles_{symbol.upper()}.csv",
        "style_history": root / f"market_structure_style_history_{symbol.upper()}.csv",
        "layered_breadth": root / f"market_structure_layered_breadth_{symbol.upper()}.csv",
        "concentration": root / f"market_structure_concentration_{symbol.upper()}.csv",
        "return_distribution": root / f"market_structure_return_distribution_{symbol.upper()}.csv",
        "liquidity_structure": root / f"market_structure_liquidity_{symbol.upper()}.csv",
        "state_history": root / f"market_structure_state_history_{symbol.upper()}.csv",
        "source_freshness": root / f"market_structure_source_freshness_{symbol.upper()}.csv",
        "index_lift_structure": root / f"market_structure_index_lift_structure_{symbol.upper()}.csv",
    }
    paths["json"].write_text(
        json.dumps(
            structure,
            ensure_ascii=False,
            indent=2,
            default=lambda value: value.item() if isinstance(value, np.generic) else str(value),
        ),
        encoding="utf-8",
    )
    pd.DataFrame(structure.get("indices", {}).values()).to_csv(paths["indices"], index=False)
    pd.DataFrame(structure.get("breadth", {}).get("history") or []).to_csv(paths["breadth"], index=False)
    pd.DataFrame(structure.get("styles", {}).values()).to_csv(paths["styles"], index=False)
    pd.DataFrame(structure.get("style_history") or []).to_csv(paths["style_history"], index=False)
    layered_rows = []
    for name, item in (structure.get("layered_breadth") or {}).items():
        layered_rows.append(
            {
                "layer": name,
                "symbol": item.get("symbol"),
                "state": item.get("state"),
                "composition_point_in_time": item.get("composition_point_in_time"),
                "membership_source": item.get("membership_source"),
                **(item.get("latest") or {}),
            }
        )
    pd.DataFrame(layered_rows).to_csv(paths["layered_breadth"], index=False)
    pd.DataFrame((structure.get("contribution_analysis") or {}).get("history") or []).to_csv(paths["concentration"], index=False)
    pd.DataFrame((structure.get("return_distribution") or {}).get("history") or []).to_csv(paths["return_distribution"], index=False)
    pd.DataFrame((structure.get("liquidity_structure") or {}).get("history") or []).to_csv(paths["liquidity_structure"], index=False)
    state_rows = []
    dimensions = (((structure.get("market_structure") or {}).get("state_history") or {}).get("dimensions") or {})
    for dimension, item in dimensions.items():
        for row in item.get("history") or []:
            state_rows.append({"dimension": dimension, **row})
    pd.DataFrame(state_rows).to_csv(paths["state_history"], index=False)
    lift_rows = []
    for item in ((structure.get("index_lift_structure") or {}).get("by_symbol") or {}).values():
        for row in item.get("history") or []:
            lift_rows.append({"symbol": item.get("symbol"), "index_name": item.get("index_name"), **row})
    pd.DataFrame(lift_rows).to_csv(paths["index_lift_structure"], index=False)
    freshness_rows = [{"source_key": key, **value} for key, value in (structure.get("source_freshness") or {}).items()]
    pd.DataFrame(freshness_rows).to_csv(paths["source_freshness"], index=False)
    return paths
