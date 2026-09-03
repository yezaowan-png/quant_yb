"""Theme stock pool period performance analysis."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re
from typing import Iterable

import pandas as pd

from data.stock_pool import StockPoolError, resolve_pool_symbols
from analysis.theme_report import build_theme_dashboard


@dataclass
class ThemeAnalysisResult:
    pool: str
    start: str
    end: str
    output_path: Path
    summary_path: Path
    index_path: Path
    html_path: Path
    summary: dict[str, object]
    details: pd.DataFrame
    concept_index: pd.DataFrame


def _normalize_date(value: str) -> str:
    text = str(value or "").strip().replace("-", "")
    if not re.fullmatch(r"\d{8}", text):
        raise ValueError("日期格式应为 YYYYMMDD，例如 20260601")
    return text


def _safe_filename(value: str) -> str:
    safe = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", value.strip())
    return safe.strip("_") or "theme"


def _cache_path(config: dict, symbol: str) -> Path:
    return Path(config["data"]["cache_dir"]) / f"{symbol}.csv"


def _daily_basic_path(config: dict, symbol: str) -> Path:
    meta_dir = Path(config.get("data", {}).get("meta_dir", "data/meta"))
    return meta_dir / "daily_basic" / f"{symbol}.csv"


def load_stock_name_map(config: dict) -> dict[str, str]:
    """Load ts_code -> name mapping from meta stock_names.csv if available."""
    meta_dir = Path(config.get("data", {}).get("meta_dir", "data/meta"))
    path = meta_dir / "stock_names.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype=str)
    if "ts_code" not in df.columns or "name" not in df.columns:
        return {}
    return dict(zip(df["ts_code"].astype(str), df["name"].astype(str)))


def _load_kline(config: dict, symbol: str) -> pd.DataFrame | None:
    path = _cache_path(config, symbol)
    if not path.exists():
        return None
    df = pd.read_csv(path, dtype={"date": str})
    if "date" not in df.columns or "close" not in df.columns:
        return None
    df["date"] = df["date"].astype(str).str.replace("-", "", regex=False)
    for column in ("open", "high", "low", "close", "volume", "vol", "amount"):
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


def _max_drawdown_pct(closes: pd.Series) -> float:
    values = pd.to_numeric(closes, errors="coerce").dropna()
    if len(values) == 0:
        return 0.0
    running_max = values.cummax()
    drawdown = values / running_max - 1.0
    return float(drawdown.min() * 100)


def _safe_pct(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return (numerator / denominator - 1.0) * 100


def _latest_technical_snapshot(kline: pd.DataFrame, end_date: str) -> dict[str, float | None]:
    """Calculate end-date technical context using data known up to that date."""
    history = kline[kline["date"] <= end_date].copy()
    history = history.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
    empty = {
        "latest_close_vs_ma20_pct": None,
        "latest_close_vs_ma60_pct": None,
        "latest_volume_ratio_20": None,
        "latest_high20_distance_pct": None,
        "latest_low20_distance_pct": None,
    }
    if history.empty:
        return empty

    close = pd.to_numeric(history["close"], errors="coerce")
    latest_close = float(close.iloc[-1])
    metrics = dict(empty)
    ma20 = float(close.tail(20).mean()) if len(close.tail(20).dropna()) else None
    ma60 = float(close.tail(60).mean()) if len(close.tail(60).dropna()) else None
    metrics["latest_close_vs_ma20_pct"] = _safe_pct(latest_close, ma20)
    metrics["latest_close_vs_ma60_pct"] = _safe_pct(latest_close, ma60)

    volume = _column_or_default(history, "volume", pd.Series(0.0, index=history.index))
    if "vol" in history.columns and volume.fillna(0).sum() == 0:
        volume = _column_or_default(history, "vol", pd.Series(0.0, index=history.index))
    volume = pd.to_numeric(volume, errors="coerce")
    avg_volume_20 = float(volume.tail(20).mean()) if len(volume.tail(20).dropna()) else None
    latest_volume = float(volume.iloc[-1]) if pd.notna(volume.iloc[-1]) else None
    metrics["latest_volume_ratio_20"] = latest_volume / avg_volume_20 if latest_volume is not None and avg_volume_20 else None

    high = _column_or_default(history, "high", close)
    low = _column_or_default(history, "low", close)
    high20 = float(pd.to_numeric(high.tail(20), errors="coerce").max())
    low20 = float(pd.to_numeric(low.tail(20), errors="coerce").min())
    metrics["latest_high20_distance_pct"] = _safe_pct(latest_close, high20)
    metrics["latest_low20_distance_pct"] = _safe_pct(latest_close, low20)
    return metrics


def _load_daily_basic_metrics(config: dict, symbol: str, start: str, end: str) -> dict[str, float | None]:
    path = _daily_basic_path(config, symbol)
    empty = {
        "avg_turnover_rate": None,
        "avg_volume_ratio": None,
        "total_mv_start": None,
        "total_mv_end": None,
        "total_mv_change_pct": None,
    }
    if not path.exists():
        return empty

    df = pd.read_csv(path, dtype={"trade_date": str})
    if "trade_date" not in df.columns:
        return empty
    df["trade_date"] = df["trade_date"].astype(str).str.replace("-", "", regex=False)
    period = df[(df["trade_date"] >= start) & (df["trade_date"] <= end)].copy()
    if period.empty:
        return empty
    period = period.sort_values("trade_date")

    metrics = dict(empty)
    if "turnover_rate" in period.columns:
        metrics["avg_turnover_rate"] = float(pd.to_numeric(period["turnover_rate"], errors="coerce").mean())
    if "volume_ratio" in period.columns:
        metrics["avg_volume_ratio"] = float(pd.to_numeric(period["volume_ratio"], errors="coerce").mean())
    if "total_mv" in period.columns:
        total_mv = pd.to_numeric(period["total_mv"], errors="coerce").dropna()
        if len(total_mv) > 0:
            start_mv = float(total_mv.iloc[0])
            end_mv = float(total_mv.iloc[-1])
            metrics["total_mv_start"] = start_mv
            metrics["total_mv_end"] = end_mv
            metrics["total_mv_change_pct"] = ((end_mv / start_mv - 1.0) * 100) if start_mv else None
    return metrics


def _analyze_symbol(config: dict, symbol: str, name: str, start: str, end: str) -> dict[str, object]:
    row: dict[str, object] = {
        "ts_code": symbol,
        "name": name,
        "valid": False,
        "reason": "",
        "start_date": "",
        "end_date": "",
        "trading_days": 0,
        "start_close": None,
        "end_close": None,
        "return_pct": None,
        "max_drawdown_pct": None,
        "annualized_volatility_pct": None,
        "return_drawdown_ratio": None,
        "avg_turnover_rate": None,
        "avg_volume_ratio": None,
        "total_mv_start": None,
        "total_mv_end": None,
        "total_mv_change_pct": None,
        "latest_close_vs_ma20_pct": None,
        "latest_close_vs_ma60_pct": None,
        "latest_volume_ratio_20": None,
        "latest_high20_distance_pct": None,
        "latest_low20_distance_pct": None,
    }

    kline = _load_kline(config, symbol)
    if kline is None:
        row["reason"] = "无K线缓存"
        return row

    period = kline[(kline["date"] >= start) & (kline["date"] <= end)].copy()
    period = period.dropna(subset=["close"])
    if len(period) < 2:
        row["reason"] = "区间内有效交易日不足2天"
        row["trading_days"] = int(len(period))
        return row

    start_close = float(period["close"].iloc[0])
    end_close = float(period["close"].iloc[-1])
    return_pct = (end_close / start_close - 1.0) * 100 if start_close else None
    max_drawdown_pct = _max_drawdown_pct(period["close"])
    daily_returns = pd.to_numeric(period["close"], errors="coerce").pct_change().dropna()
    annualized_volatility_pct = float(daily_returns.std(ddof=0) * math.sqrt(244) * 100) if len(daily_returns) else None
    row.update(
        {
            "valid": True,
            "start_date": str(period["date"].iloc[0]),
            "end_date": str(period["date"].iloc[-1]),
            "trading_days": int(len(period)),
            "start_close": start_close,
            "end_close": end_close,
            "return_pct": return_pct,
            "max_drawdown_pct": max_drawdown_pct,
            "annualized_volatility_pct": annualized_volatility_pct,
            "return_drawdown_ratio": return_pct / abs(max_drawdown_pct) if return_pct is not None and max_drawdown_pct else None,
        }
    )
    row.update(_latest_technical_snapshot(kline, str(period["date"].iloc[-1])))
    row.update(_load_daily_basic_metrics(config, symbol, start, end))
    return row


def _mean_numeric(values: Iterable[object]) -> float | None:
    series = pd.to_numeric(pd.Series(list(values)), errors="coerce").dropna()
    if len(series) == 0:
        return None
    return float(series.mean())


def _median_numeric(values: Iterable[object]) -> float | None:
    series = pd.to_numeric(pd.Series(list(values)), errors="coerce").dropna()
    if len(series) == 0:
        return None
    return float(series.median())


def _column_or_default(df: pd.DataFrame, column: str, default: pd.Series) -> pd.Series:
    if column in df.columns:
        return pd.to_numeric(df[column], errors="coerce")
    return default.copy()


def build_concept_index(
    config: dict,
    symbols: Iterable[str],
    start: str | None = None,
    end: str | None = None,
    base_value: float = 1000.0,
) -> pd.DataFrame:
    """Build an equal-weight concept OHLCV index from member K-line caches.

    Each member is normalized by its first valid close inside the selected
    period, or by its first cached close when no period is provided. The concept
    OHLC columns are the equal-weight average of normalized member OHLC values,
    while volume/amount are raw sums across valid members.
    """
    frames: list[pd.DataFrame] = []
    for symbol in symbols:
        kline = _load_kline(config, symbol)
        if kline is None:
            continue
        period = kline.copy()
        if start:
            period = period[period["date"] >= start]
        if end:
            period = period[period["date"] <= end]
        period = period.dropna(subset=["close"])
        if len(period) < 2:
            continue
        period = period.sort_values("date").reset_index(drop=True)
        first_close = float(period["close"].iloc[0])
        if first_close <= 0:
            continue

        close = pd.to_numeric(period["close"], errors="coerce")
        open_ = _column_or_default(period, "open", close)
        high = _column_or_default(period, "high", close)
        low = _column_or_default(period, "low", close)
        volume = _column_or_default(period, "volume", pd.Series(0.0, index=period.index))
        if "vol" in period.columns and volume.fillna(0).sum() == 0:
            volume = _column_or_default(period, "vol", pd.Series(0.0, index=period.index))
        amount = _column_or_default(period, "amount", pd.Series(0.0, index=period.index))
        factor = base_value / first_close
        close_ma20 = close.rolling(20, min_periods=1).mean()
        close_ma60 = close.rolling(60, min_periods=1).mean()
        close_high20 = close.rolling(20, min_periods=1).max()
        close_low20 = close.rolling(20, min_periods=1).min()

        frames.append(
            pd.DataFrame(
                {
                    "date": period["date"].astype(str),
                    "symbol": symbol,
                    "open_norm": open_ * factor,
                    "high_norm": high * factor,
                    "low_norm": low * factor,
                    "close_norm": close * factor,
                    "volume": volume,
                    "amount": amount,
                    "member_return_pct": close.pct_change() * 100,
                    "above_ma20": close > close_ma20,
                    "above_ma60": close > close_ma60,
                    "new_high_20": close >= close_high20,
                    "new_low_20": close <= close_low20,
                }
            )
        )

    columns = [
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "member_count",
        "pct_chg",
        "ma5",
        "ma20",
        "ma60",
        "volume_ma5",
        "volume_ma20",
        "amount_ma5",
        "amount_ma20",
        "advance_count",
        "decline_count",
        "flat_count",
        "advance_ratio_pct",
        "above_ma20_count",
        "above_ma20_ratio_pct",
        "above_ma60_count",
        "above_ma60_ratio_pct",
        "new_high_20_count",
        "new_high_20_ratio_pct",
        "new_low_20_count",
        "new_low_20_ratio_pct",
        "member_return_std_pct",
    ]
    if not frames:
        return pd.DataFrame(columns=columns)

    merged = pd.concat(frames, ignore_index=True)
    grouped = merged.groupby("date", sort=True)
    index = pd.DataFrame(
        {
            "date": grouped.size().index.astype(str),
            "open": grouped["open_norm"].mean().values,
            "high": grouped["high_norm"].mean().values,
            "low": grouped["low_norm"].mean().values,
            "close": grouped["close_norm"].mean().values,
            "volume": grouped["volume"].sum(min_count=1).fillna(0).values,
            "amount": grouped["amount"].sum(min_count=1).fillna(0).values,
            "member_count": grouped["symbol"].nunique().values,
            "advance_count": grouped["member_return_pct"].apply(lambda s: int((s > 0).sum())).values,
            "decline_count": grouped["member_return_pct"].apply(lambda s: int((s < 0).sum())).values,
            "flat_count": grouped["member_return_pct"].apply(lambda s: int((s == 0).sum())).values,
            "above_ma20_count": grouped["above_ma20"].sum().astype(int).values,
            "above_ma60_count": grouped["above_ma60"].sum().astype(int).values,
            "new_high_20_count": grouped["new_high_20"].sum().astype(int).values,
            "new_low_20_count": grouped["new_low_20"].sum().astype(int).values,
            "member_return_std_pct": grouped["member_return_pct"].std(ddof=0).fillna(0).values,
        }
    )
    index = index.sort_values("date").reset_index(drop=True)
    index["pct_chg"] = index["close"].pct_change() * 100
    index["ma5"] = index["close"].rolling(5, min_periods=1).mean()
    index["ma20"] = index["close"].rolling(20, min_periods=1).mean()
    index["ma60"] = index["close"].rolling(60, min_periods=1).mean()
    index["volume_ma5"] = index["volume"].rolling(5, min_periods=1).mean()
    index["volume_ma20"] = index["volume"].rolling(20, min_periods=1).mean()
    index["amount_ma5"] = index["amount"].rolling(5, min_periods=1).mean()
    index["amount_ma20"] = index["amount"].rolling(20, min_periods=1).mean()
    denominator = index["advance_count"] + index["decline_count"] + index["flat_count"]
    index["advance_ratio_pct"] = (index["advance_count"] / denominator.replace(0, pd.NA)) * 100
    member_denominator = index["member_count"].replace(0, pd.NA)
    index["above_ma20_ratio_pct"] = (index["above_ma20_count"] / member_denominator) * 100
    index["above_ma60_ratio_pct"] = (index["above_ma60_count"] / member_denominator) * 100
    index["new_high_20_ratio_pct"] = (index["new_high_20_count"] / member_denominator) * 100
    index["new_low_20_ratio_pct"] = (index["new_low_20_count"] / member_denominator) * 100
    return index[columns]


def build_theme_summary(pool: str, start: str, end: str, details: pd.DataFrame) -> dict[str, object]:
    valid = details[details["valid"] == True].copy()  # noqa: E712
    returns = pd.to_numeric(valid.get("return_pct"), errors="coerce").dropna()
    summary: dict[str, object] = {
        "pool": pool,
        "start": start,
        "end": end,
        "stock_count": int(len(details)),
        "valid_count": int(len(valid)),
        "missing_count": int(len(details) - len(valid)),
        "avg_return_pct": _mean_numeric(returns),
        "median_return_pct": _median_numeric(returns),
        "positive_count": int((returns > 0).sum()) if len(returns) else 0,
        "positive_ratio_pct": float((returns > 0).mean() * 100) if len(returns) else 0.0,
        "avg_max_drawdown_pct": _mean_numeric(valid.get("max_drawdown_pct", [])),
        "return_std_pct": float(returns.std(ddof=0)) if len(returns) else None,
        "return_spread_pct": float(returns.max() - returns.min()) if len(returns) else None,
        "avg_annualized_volatility_pct": _mean_numeric(valid.get("annualized_volatility_pct", [])),
        "avg_return_drawdown_ratio": _mean_numeric(valid.get("return_drawdown_ratio", [])),
        "avg_turnover_rate": _mean_numeric(valid.get("avg_turnover_rate", [])),
        "avg_volume_ratio": _mean_numeric(valid.get("avg_volume_ratio", [])),
        "avg_total_mv_change_pct": _mean_numeric(valid.get("total_mv_change_pct", [])),
    }

    if len(returns):
        best_idx = pd.to_numeric(valid["return_pct"], errors="coerce").idxmax()
        worst_idx = pd.to_numeric(valid["return_pct"], errors="coerce").idxmin()
        best = valid.loc[best_idx]
        worst = valid.loc[worst_idx]
        summary.update(
            {
                "best_symbol": best["ts_code"],
                "best_name": best["name"],
                "best_return_pct": float(best["return_pct"]),
                "worst_symbol": worst["ts_code"],
                "worst_name": worst["name"],
                "worst_return_pct": float(worst["return_pct"]),
            }
        )
    else:
        summary.update(
            {
                "best_symbol": "",
                "best_name": "",
                "best_return_pct": None,
                "worst_symbol": "",
                "worst_name": "",
                "worst_return_pct": None,
            }
        )
    return summary


def _add_index_summary(summary: dict[str, object], concept_index: pd.DataFrame) -> None:
    if concept_index.empty or len(concept_index) < 2:
        summary.update(
            {
                "concept_start": None,
                "concept_end": None,
                "concept_return_pct": None,
                "concept_max_drawdown_pct": None,
                "concept_volume_change_pct": None,
                "concept_latest_volume": None,
                "concept_latest_member_count": 0,
                "concept_latest_advance_ratio_pct": None,
                "concept_latest_above_ma20_ratio_pct": None,
                "concept_latest_above_ma60_ratio_pct": None,
                "concept_latest_new_high_20_ratio_pct": None,
                "concept_latest_new_low_20_ratio_pct": None,
                "concept_latest_member_return_std_pct": None,
                "concept_latest_close_vs_ma20_pct": None,
                "concept_latest_close_vs_ma60_pct": None,
            }
        )
        return

    start_close = float(concept_index["close"].iloc[0])
    end_close = float(concept_index["close"].iloc[-1])
    start_volume = float(concept_index["volume"].iloc[0])
    end_volume = float(concept_index["volume"].iloc[-1])
    latest = concept_index.iloc[-1]
    summary.update(
        {
            "concept_start": float(start_close),
            "concept_end": float(end_close),
            "concept_return_pct": (end_close / start_close - 1.0) * 100 if start_close else None,
            "concept_max_drawdown_pct": _max_drawdown_pct(concept_index["close"]),
            "concept_volume_change_pct": (end_volume / start_volume - 1.0) * 100 if start_volume else None,
            "concept_latest_volume": end_volume,
            "concept_latest_member_count": int(concept_index["member_count"].iloc[-1]),
            "concept_latest_advance_ratio_pct": float(concept_index["advance_ratio_pct"].iloc[-1])
            if pd.notna(concept_index["advance_ratio_pct"].iloc[-1])
            else None,
            "concept_latest_above_ma20_ratio_pct": float(latest["above_ma20_ratio_pct"])
            if pd.notna(latest.get("above_ma20_ratio_pct"))
            else None,
            "concept_latest_above_ma60_ratio_pct": float(latest["above_ma60_ratio_pct"])
            if pd.notna(latest.get("above_ma60_ratio_pct"))
            else None,
            "concept_latest_new_high_20_ratio_pct": float(latest["new_high_20_ratio_pct"])
            if pd.notna(latest.get("new_high_20_ratio_pct"))
            else None,
            "concept_latest_new_low_20_ratio_pct": float(latest["new_low_20_ratio_pct"])
            if pd.notna(latest.get("new_low_20_ratio_pct"))
            else None,
            "concept_latest_member_return_std_pct": float(latest["member_return_std_pct"])
            if pd.notna(latest.get("member_return_std_pct"))
            else None,
            "concept_latest_close_vs_ma20_pct": _safe_pct(float(latest["close"]), float(latest["ma20"]))
            if pd.notna(latest.get("ma20"))
            else None,
            "concept_latest_close_vs_ma60_pct": _safe_pct(float(latest["close"]), float(latest["ma60"]))
            if pd.notna(latest.get("ma60"))
            else None,
        }
    )


def analyze_theme(
    config: dict,
    pool: str,
    start: str,
    end: str,
    pool_mode: str = "any",
) -> tuple[dict[str, object], pd.DataFrame]:
    """Analyze a stock pool's period performance using local cached data."""
    start_date = _normalize_date(start)
    end_date = _normalize_date(end)
    if start_date > end_date:
        raise ValueError("--start 不能晚于 --end")

    symbols = resolve_pool_symbols(config, pool, mode=pool_mode)
    if not symbols:
        raise StockPoolError(f"股票池为空: {pool}")

    names = load_stock_name_map(config)
    rows = [
        _analyze_symbol(config, symbol, names.get(symbol, ""), start_date, end_date)
        for symbol in symbols
    ]
    details = pd.DataFrame(rows)
    details = details.sort_values(
        by=["valid", "return_pct", "ts_code"],
        ascending=[False, False, True],
        na_position="last",
    ).reset_index(drop=True)
    concept_index = build_concept_index(config, symbols)
    period_concept_index = build_concept_index(config, symbols, start_date, end_date)
    summary = build_theme_summary(pool, start_date, end_date, details)
    _add_index_summary(summary, period_concept_index)
    return summary, details, concept_index


def save_theme_analysis(
    config: dict,
    pool: str,
    start: str,
    end: str,
    pool_mode: str = "any",
) -> ThemeAnalysisResult:
    """Run theme analysis and write the detail CSV to statistics_dir."""
    summary, details, concept_index = analyze_theme(config, pool, start, end, pool_mode=pool_mode)
    stats_dir = Path(config["output"].get("statistics_dir", "output/statistics"))
    stats_dir.mkdir(parents=True, exist_ok=True)
    output_path = stats_dir / f"theme_{_safe_filename(pool)}_{summary['start']}_{summary['end']}.csv"
    summary_path = stats_dir / f"theme_{_safe_filename(pool)}_{summary['start']}_{summary['end']}_summary.csv"
    index_path = stats_dir / f"theme_index_{_safe_filename(pool)}_{summary['start']}_{summary['end']}.csv"
    html_path = stats_dir / f"theme_{_safe_filename(pool)}_{summary['start']}_{summary['end']}.html"
    details.to_csv(output_path, index=False, encoding="utf-8-sig")
    pd.DataFrame([summary]).to_csv(summary_path, index=False, encoding="utf-8-sig")
    concept_index.to_csv(index_path, index=False, encoding="utf-8-sig")
    build_theme_dashboard(summary, details, html_path, concept_index=concept_index, config=config)
    return ThemeAnalysisResult(
        pool=pool,
        start=str(summary["start"]),
        end=str(summary["end"]),
        output_path=output_path,
        summary_path=summary_path,
        index_path=index_path,
        html_path=html_path,
        summary=summary,
        details=details,
        concept_index=concept_index,
    )
