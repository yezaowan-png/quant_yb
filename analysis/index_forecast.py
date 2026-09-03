"""Index forecast feature building and rule-based forecast model."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from analysis.market_environment_labels import attach_environment_targets, environment_evaluation


DEFAULT_HORIZONS = (1, 5, 10, 20)
SLOPE_WINDOWS = (3, 5, 10, 20)
RANK_LABEL_WINDOW = 252
RANK_LABEL_MIN_PERIODS = 80


def _abs_label_threshold(horizon: int) -> float:
    if horizon <= 3:
        return 0.008
    if horizon <= 5:
        return 0.015
    return 0.04


def _rank_label_thresholds(
    fwd_ret: pd.Series,
    horizon: int,
    window: int = RANK_LABEL_WINDOW,
    min_periods: int = RANK_LABEL_MIN_PERIODS,
) -> tuple[pd.Series, pd.Series]:
    historical = pd.to_numeric(fwd_ret, errors="coerce").shift(int(horizon))
    lower = historical.rolling(window=window, min_periods=min_periods).quantile(0.30)
    upper = historical.rolling(window=window, min_periods=min_periods).quantile(0.70)
    return lower, upper


@dataclass(frozen=True)
class ForecastPaths:
    root: Path
    indicators: Path
    features: Path
    predictions: Path


def forecast_paths(config: dict, symbol: str, horizon: int, model: str = "rule_v1") -> ForecastPaths:
    stats_dir = Path(config["output"].get("statistics_dir", "output/statistics"))
    root = stats_dir / "index_forecast"
    safe_symbol = symbol.upper()
    model_suffix = "" if (model or "rule_v1").lower() == "rule_v1" else f"_{(model or '').lower()}"
    return ForecastPaths(
        root=root,
        indicators=root / f"indicators_{safe_symbol}.csv",
        features=root / f"features_{safe_symbol}.csv",
        predictions=root / f"predictions_{safe_symbol}_h{int(horizon)}{model_suffix}.csv",
    )


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _date_key(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce").dt.strftime("%Y-%m-%d")


def _pct_change(series: pd.Series, window: int) -> pd.Series:
    return series / series.shift(window) - 1.0


def _slope(series: pd.Series, window: int) -> pd.Series:
    return series - series.shift(window)


def _safe_div(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator / denominator.replace(0, np.nan)


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def _prepare_index_frame(index_df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    required = ["date", "open", "high", "low", "close"]
    missing = [col for col in required if col not in index_df.columns]
    if missing:
        raise ValueError(f"指数数据缺少字段: {', '.join(missing)}")

    df = index_df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in ["open", "high", "low", "close", "volume", "amount", "pct_chg"]:
        if col in df.columns:
            df[col] = _num(df[col])
    if "volume" not in df.columns:
        df["volume"] = np.nan
    if "amount" not in df.columns:
        df["amount"] = np.nan
    df = df.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date")
    df = df.reset_index(drop=True)
    df["trade_date"] = df["date"].dt.strftime("%Y-%m-%d")
    df["symbol"] = symbol.upper()
    return df


def _add_index_features(df: pd.DataFrame) -> pd.DataFrame:
    close = df["close"]
    high = df["high"]
    low = df["low"]
    open_ = df["open"]

    for window in (1, 3, 5, 10, 20, 60):
        df[f"ret_{window}d"] = _pct_change(close, window)

    for window in (5, 10, 20, 60, 120, 250):
        ma = close.rolling(window, min_periods=window).mean()
        df[f"ma{window}"] = ma
        df[f"dist_ma{window}"] = close / ma - 1.0

    for ma_window in (20, 60):
        for slope_window in (5, 10):
            df[f"ma{ma_window}_slope_{slope_window}"] = (
                df[f"ma{ma_window}"] / df[f"ma{ma_window}"].shift(slope_window) - 1.0
            )

    df["above_ma20"] = close > df["ma20"]
    df["above_ma60"] = close > df["ma60"]
    df["above_ma120"] = close > df["ma120"]
    df["ma20_gt_ma60"] = df["ma20"] > df["ma60"]
    df["ma60_gt_ma120"] = df["ma60"] > df["ma120"]
    for window in (20, 60, 120):
        rolling_high = close.rolling(window, min_periods=window).max()
        rolling_low = close.rolling(window, min_periods=window).min()
        df[f"drawdown_{window}d"] = close / rolling_high - 1.0
        df[f"break_high_{window}d"] = close >= rolling_high
        df[f"break_low_{window}d"] = close <= rolling_low

    prev_close = close.shift(1)
    true_range = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    for window in (14, 20):
        atr = true_range.rolling(window, min_periods=window).mean()
        df[f"atr{window}_pct"] = atr / close
    df["index_volatility_10d"] = df["ret_1d"].rolling(10, min_periods=10).std()
    df["index_volatility_20d"] = df["ret_1d"].rolling(20, min_periods=20).std()
    daily_range = (high - low).replace(0, np.nan)
    df["intraday_range_pct"] = daily_range / close
    df["upper_shadow_ratio"] = (high - pd.concat([open_, close], axis=1).max(axis=1)) / daily_range
    df["lower_shadow_ratio"] = (pd.concat([open_, close], axis=1).min(axis=1) - low) / daily_range

    amount_ma20 = df["amount"].rolling(20, min_periods=20).mean()
    amount_ma5 = df["amount"].rolling(5, min_periods=5).mean()
    volume_ma20 = df["volume"].rolling(20, min_periods=20).mean()
    df["amount_ratio_20"] = df["amount"] / amount_ma20
    df["amount_ma5_ratio_20"] = amount_ma5 / amount_ma20
    df["amount_slope_5_20"] = df["amount_ma5_ratio_20"] - 1.0
    df["volume_ratio_20"] = df["volume"] / volume_ma20
    df["amount_up_confirm"] = (df["ret_1d"] > 0) & (df["amount_ratio_20"] > 1.2)
    df["amount_down_expand"] = (df["ret_1d"] < 0) & (df["amount_ratio_20"] > 1.2)
    df["amount_stalling"] = (
        (df["amount_ratio_20"] >= 1.5)
        & (df["ret_1d"].abs() <= 0.5 * df["atr20_pct"])
        & (df["upper_shadow_ratio"] >= 0.35)
        & (close >= df["ma20"])
    )

    dif = _ema(close, 12) - _ema(close, 26)
    dea = _ema(dif, 9)
    macd_hist = 2.0 * (dif - dea)
    df["macd_dif_norm"] = dif / close
    df["macd_dea_norm"] = dea / close
    df["macd_hist_norm"] = macd_hist / close
    df["macd_diff_norm"] = (dif - dea) / close
    df["macd_hist_delta_1"] = macd_hist.diff(1) / close
    df["macd_hist_delta_3"] = macd_hist.diff(3) / close
    df["macd_hist_delta_5"] = macd_hist.diff(5) / close
    df["macd_gold"] = dif > dea
    df["macd_dif_above_zero"] = dif > 0
    df["macd_dea_above_zero"] = dea > 0
    df["macd_hist_up_3"] = macd_hist.diff().gt(0).rolling(3, min_periods=3).sum().eq(3)
    df["macd_hist_down_3"] = macd_hist.diff().lt(0).rolling(3, min_periods=3).sum().eq(3)

    low9 = low.rolling(9, min_periods=9).min()
    high9 = high.rolling(9, min_periods=9).max()
    rsv = (close - low9) / (high9 - low9).replace(0, np.nan) * 100.0
    k = rsv.rolling(3, min_periods=3).mean()
    d = k.rolling(3, min_periods=3).mean()
    j = 3.0 * k - 2.0 * d
    df["kdj_k"] = k / 100.0
    df["kdj_d"] = d / 100.0
    df["kdj_j"] = j / 100.0
    df["kdj_k_minus_d"] = (k - d) / 100.0
    df["kdj_k_slope_1"] = k.diff(1) / 100.0
    df["kdj_k_slope_3"] = k.diff(3) / 100.0
    df["kdj_j_slope_1"] = j.diff(1) / 100.0
    df["kdj_j_slope_3"] = j.diff(3) / 100.0
    df["kdj_gold"] = k > d
    df["kdj_j_below_0"] = j < 0
    df["kdj_j_below_minus10"] = j < -10
    df["kdj_j_above_90"] = j > 90
    df["kdj_j_above_100"] = j > 100
    df["kdj_overbought"] = (k > 80) | (j > 90)
    df["kdj_oversold"] = (k < 20) | (j < 0)
    df["kdj_high_sticky"] = (k > 80).rolling(3, min_periods=3).sum().eq(3) & (k > d)
    df["kdj_low_repair"] = (k.shift(1) < d.shift(1)) & (k > d) & (k < 30)
    return df


def _breadth_frame(breadth_by_date: dict[str, dict[str, Any]] | None) -> pd.DataFrame:
    if not breadth_by_date:
        return pd.DataFrame(columns=["trade_date"])
    rows = []
    for date_key, item in sorted(breadth_by_date.items()):
        up = int(item.get("up", 0) or 0)
        down = int(item.get("down", 0) or 0)
        flat = int(item.get("flat", 0) or 0)
        new_high = int(item.get("new_high", 0) or 0)
        new_low = int(item.get("new_low", 0) or 0)
        total = up + down + flat
        ad_total = up + down
        nhnl = new_high - new_low
        rows.append(
            {
                "trade_date": date_key,
                "breadth_up": up,
                "breadth_down": down,
                "breadth_flat": flat,
                "breadth_total": total,
                "up_ratio": (up / total) if total else np.nan,
                "daily_ad": up - down,
                "ad_norm": ((up - down) / ad_total) if ad_total else np.nan,
                "normalized_ad": ((up - down) / ad_total) if ad_total else np.nan,
                "new_high": new_high,
                "new_low": new_low,
                "nhnl": nhnl,
                "daily_nhnl": nhnl,
                "nhnl_norm": (nhnl / total) if total else np.nan,
                "normalized_nhnl": (nhnl / total) if total else np.nan,
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["ad_norm_line"] = df["ad_norm"].fillna(0.0).cumsum()
    df["nhnl_sum_5"] = df["nhnl"].rolling(5, min_periods=1).sum()
    df["nhnl_sum_10"] = df["nhnl"].rolling(10, min_periods=1).sum()
    for window in SLOPE_WINDOWS:
        df[f"ad_slope_{window}"] = _slope(df["ad_norm_line"], window)
        df[f"nhnl_slope_{window}"] = _slope(df["nhnl_norm"], window)
        df[f"ad_line_slope_{window}"] = df[f"ad_slope_{window}"]
        df[f"nhnl_line_slope_{window}"] = df[f"nhnl_slope_{window}"]
    df["ad_slope_5_delta"] = df["ad_slope_5"].diff()
    df["ad_slope_5_minus_20"] = df["ad_slope_5"] - df["ad_slope_20"]
    df["nhnl_slope_5_minus_20"] = df["nhnl_slope_5"] - df["nhnl_slope_20"]
    df["nhnl_sum5_slope_5"] = df["nhnl_sum_5"] - df["nhnl_sum_5"].shift(5)
    nhnl_mean = df["nhnl"].rolling(60, min_periods=20).mean()
    nhnl_std = df["nhnl"].rolling(60, min_periods=20).std()
    df["nhnl_z60"] = (df["nhnl"] - nhnl_mean) / nhnl_std.replace(0, np.nan)
    return df


def _group_breadth_frame(breadth_groups: dict[str, dict[str, list[Any]]] | None) -> pd.DataFrame:
    if not breadth_groups:
        return pd.DataFrame(columns=["trade_date"])
    merged: pd.DataFrame | None = None
    for label, payload in breadth_groups.items():
        dates = payload.get("dates") or []
        if not dates:
            continue
        safe_label = (
            str(label)
            .replace("/", "_")
            .replace(" ", "_")
            .replace("全A", "all_a")
            .replace("沪深300", "hs300")
            .replace("中证1000", "csi1000")
            .replace("中证2000", "csi2000")
            .replace("创业板", "chinext")
        )
        line = payload.get("ad_norm_line_rebased") or payload.get("ad_norm_line") or []
        ad_norm = payload.get("ad_norm") or []
        df = pd.DataFrame(
            {
                "trade_date": dates,
                f"{safe_label}_ad_norm": pd.Series(ad_norm, dtype="float64"),
                f"{safe_label}_ad_line": pd.Series(line, dtype="float64"),
            }
        )
        for window in (5, 10, 20):
            df[f"{safe_label}_ad_slope_{window}"] = _slope(df[f"{safe_label}_ad_line"], window)
        merged = df if merged is None else merged.merge(df, on="trade_date", how="outer")
    if merged is None:
        return pd.DataFrame(columns=["trade_date"])
    if {"hs300_ad_slope_5", "all_a_ad_slope_5"}.issubset(merged.columns):
        merged["hs300_minus_all_a_ad_slope_5"] = merged["hs300_ad_slope_5"] - merged["all_a_ad_slope_5"]
    if {"csi1000_ad_slope_5", "hs300_ad_slope_5"}.issubset(merged.columns):
        merged["csi1000_minus_hs300_ad_slope_5"] = merged["csi1000_ad_slope_5"] - merged["hs300_ad_slope_5"]
    if {"csi2000_ad_slope_5", "hs300_ad_slope_5"}.issubset(merged.columns):
        merged["csi2000_minus_hs300_ad_slope_5"] = merged["csi2000_ad_slope_5"] - merged["hs300_ad_slope_5"]
    if {"chinext_ad_slope_5", "hs300_ad_slope_5"}.issubset(merged.columns):
        merged["chinext_minus_hs300_ad_slope_5"] = merged["chinext_ad_slope_5"] - merged["hs300_ad_slope_5"]
    return merged.sort_values("trade_date").reset_index(drop=True)


def build_index_forecast_indicators(
    index_df: pd.DataFrame,
    symbol: str,
    breadth_by_date: dict[str, dict[str, Any]] | None = None,
    breadth_groups: dict[str, dict[str, list[Any]]] | None = None,
    cross_section_features: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build the reusable index indicator table used by forecast models."""
    df = _prepare_index_frame(index_df, symbol)
    df = _add_index_features(df)
    breadth = _breadth_frame(breadth_by_date)
    if not breadth.empty:
        df = df.merge(breadth, on="trade_date", how="left")
    groups = _group_breadth_frame(breadth_groups)
    if not groups.empty:
        df = df.merge(groups, on="trade_date", how="left")
    if cross_section_features is not None and not cross_section_features.empty:
        df = df.merge(cross_section_features, on="trade_date", how="left", validate="one_to_one")
    return df


def add_forecast_labels(
    indicator_df: pd.DataFrame,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    environment_targets: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Add environment targets plus deprecated index-return labels.

    ``label_*`` remains for backward-compatible diagnostics only.  New model
    evaluation must use ``environment_label_*``.
    """
    df = indicator_df.copy()
    label_columns: dict[str, pd.Series] = {}
    for horizon in horizons:
        fwd = df["close"].shift(-horizon) / df["close"] - 1.0
        threshold = np.maximum(
            0.015 if horizon <= 5 else 0.04,
            (0.70 if horizon <= 5 else 1.0) * df["atr20_pct"] * np.sqrt(horizon),
        )
        label = pd.Series(
            np.select(
                [fwd >= threshold, fwd <= -threshold],
                ["bull", "bear"],
                default="neutral",
            ),
            index=df.index,
            dtype=object,
        )
        label.loc[fwd.isna() | pd.isna(threshold)] = np.nan
        abs_threshold = _abs_label_threshold(int(horizon))
        label_abs = pd.Series(
            np.select(
                [fwd >= abs_threshold, fwd <= -abs_threshold],
                ["bull", "bear"],
                default="neutral",
            ),
            index=df.index,
            dtype=object,
        )
        label_abs.loc[fwd.isna()] = np.nan

        rank_lower, rank_upper = _rank_label_thresholds(fwd, int(horizon))
        label_rank = pd.Series(
            np.select(
                [fwd >= rank_upper, fwd <= rank_lower],
                ["bull", "bear"],
                default="neutral",
            ),
            index=df.index,
            dtype=object,
        )
        label_rank.loc[fwd.isna() | rank_lower.isna() | rank_upper.isna()] = np.nan

        label_columns[f"fwd_ret_{horizon}d"] = fwd
        label_columns[f"threshold_{horizon}d"] = pd.Series(threshold, index=df.index)
        label_columns[f"label_{horizon}d"] = label
        label_columns[f"threshold_abs_{horizon}d"] = pd.Series(abs_threshold, index=df.index)
        label_columns[f"rank_lower_{horizon}d"] = rank_lower
        label_columns[f"rank_upper_{horizon}d"] = rank_upper
        label_columns[f"label_abs_{horizon}d"] = label_abs
        label_columns[f"label_rank_{horizon}d"] = label_rank

    if label_columns:
        df = pd.concat([df, pd.DataFrame(label_columns, index=df.index)], axis=1)
    if environment_targets is not None:
        df = attach_environment_targets(df, environment_targets)
    return df.copy()


def _max_drawdown(series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return None
    drawdown = values / values.cummax() - 1.0
    return float(drawdown.min())


def _record_float(value: Any, digits: int = 6) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def _signal_summary(evaluated: pd.DataFrame, ret_col: str, label_col: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for signal in ("bull", "neutral", "bear"):
        group = evaluated[evaluated["signal"] == signal]
        if group.empty:
            rows.append(
                {
                    "signal": signal,
                    "count": 0,
                    "avg_return": None,
                    "median_return": None,
                    "win_rate": None,
                    "hit_rate": None,
                }
            )
            continue
        returns = pd.to_numeric(group[ret_col], errors="coerce")
        rows.append(
            {
                "signal": signal,
                "count": int(len(group)),
                "avg_return": _record_float(returns.mean()),
                "median_return": _record_float(returns.median()),
                "win_rate": _record_float((returns > 0).mean(), 4),
                "hit_rate": _record_float((group["signal"] == group[label_col]).mean(), 4),
            }
        )
    return rows


def _score_bucket_summary(evaluated: pd.DataFrame, ret_col: str) -> list[dict[str, Any]]:
    frame = evaluated.copy()
    frame["score_bucket"] = pd.cut(
        pd.to_numeric(frame["market_score"], errors="coerce"),
        bins=[0, 20, 40, 60, 80, 100],
        labels=["0-20", "20-40", "40-60", "60-80", "80-100"],
        include_lowest=True,
    )
    rows: list[dict[str, Any]] = []
    for bucket in ["0-20", "20-40", "40-60", "60-80", "80-100"]:
        group = frame[frame["score_bucket"].astype(str) == bucket]
        returns = pd.to_numeric(group[ret_col], errors="coerce")
        rows.append(
            {
                "bucket": bucket,
                "count": int(len(group)),
                "avg_return": _record_float(returns.mean()) if not group.empty else None,
                "median_return": _record_float(returns.median()) if not group.empty else None,
                "win_rate": _record_float((returns > 0).mean(), 4) if not group.empty else None,
            }
        )
    return rows


def _timing_curve(predictions: pd.DataFrame) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    frame = predictions.copy()
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["trade_date", "close"]).sort_values("trade_date").reset_index(drop=True)
    if len(frame) < 2:
        return [], {}
    if "environment_signal" in frame.columns:
        exposure = frame["environment_signal"].map(
            {"positive": 1.0, "neutral": 0.5, "conservative": 0.0}
        ).fillna(0.5)
    else:
        exposure = frame["signal"].map({"bull": 1.0, "neutral": 0.3, "bear": 0.0}).fillna(0.3)
    daily_ret = frame["close"].pct_change().fillna(0.0)
    strategy_ret = exposure.shift(1).fillna(0.0) * daily_ret
    strategy_equity = (1.0 + strategy_ret).cumprod()
    buyhold_equity = frame["close"] / frame["close"].iloc[0]
    curve = [
        {
            "date": str(date),
            "strategy": _record_float(strategy),
            "buyhold": _record_float(buyhold),
            "exposure": _record_float(exp),
        }
        for date, strategy, buyhold, exp in zip(
            frame["trade_date"],
            strategy_equity,
            buyhold_equity,
            exposure,
        )
    ]
    stats = {
        "strategy_return": _record_float(strategy_equity.iloc[-1] - 1.0),
        "buyhold_return": _record_float(buyhold_equity.iloc[-1] - 1.0),
        "excess_return": _record_float(strategy_equity.iloc[-1] - buyhold_equity.iloc[-1]),
        "strategy_max_drawdown": _record_float(_max_drawdown(strategy_equity)),
        "buyhold_max_drawdown": _record_float(_max_drawdown(buyhold_equity)),
        "avg_exposure": _record_float(exposure.mean(), 4),
    }
    return curve, stats



def build_index_forecast_features(
    index_df: pd.DataFrame,
    symbol: str,
    breadth_by_date: dict[str, dict[str, Any]] | None = None,
    breadth_groups: dict[str, dict[str, list[Any]]] | None = None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> pd.DataFrame:
    """Build the labeled feature table kept for backwards-compatible callers."""
    indicators = build_index_forecast_indicators(
        index_df,
        symbol=symbol,
        breadth_by_date=breadth_by_date,
        breadth_groups=breadth_groups,
    )
    return add_forecast_labels(indicators, horizons=horizons)


def _score_bool(value: Any, points: float) -> float:
    if value is None or pd.isna(value):
        return 0.0
    return points if bool(value) else 0.0


def _score_positive(value: Any, points: float, negative_points: float = 0.0) -> float:
    if pd.isna(value):
        return 0.0
    value = float(value)
    if value > 0:
        return points
    if value < 0:
        return negative_points
    return 0.0


def _clip_score(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return float(np.clip(value, lower, upper))


def _environment_prediction_score(row: pd.Series) -> tuple[float, float, float, str]:
    """Score the future environment using only features observable on the row date."""
    def ratio(name: str, default: float = 0.5) -> float:
        value = row.get(name)
        return default if value is None or pd.isna(value) else _clip_score(float(value), 0.0, 1.0)

    def signed(name: str, scale: float) -> float:
        value = row.get(name)
        if value is None or pd.isna(value):
            return 50.0
        return _clip_score(50.0 + float(value) / scale * 50.0)

    trend = np.mean([
        signed("dist_ma20", 0.08),
        signed("dist_ma60", 0.15),
        signed("macd_diff_norm", 0.01),
        signed("kdj_k_minus_d", 0.25),
    ])
    breadth = np.mean([
        ratio("stock_up_ratio") * 100.0,
        ratio("stocks_above_ma20_ratio") * 100.0,
        ratio("stocks_above_ma50_ratio") * 100.0,
        ratio("stocks_above_ma200_ratio") * 100.0,
        signed("normalized_ad", 0.5),
        signed("ad_line_slope_5", 2.5),
        signed("ad_line_slope_10", 5.0),
        signed("ad_line_slope_20", 10.0),
        signed("normalized_nhnl", 0.10),
        signed("nhnl_line_slope_5", 0.10),
        signed("nhnl_line_slope_10", 0.15),
        signed("nhnl_line_slope_20", 0.20),
    ])
    liquidity = np.mean([
        signed("amount_ratio_20", 1.0),
        signed("volume_ratio_20", 1.0),
    ])
    structure = np.mean([
        signed("index_equal_weight_gap_1d", -0.02),
        signed("index_equal_weight_gap_5d", -0.05),
        signed("large_small_relative_strength_1d", -0.02),
        signed("large_small_relative_strength_5d", -0.05),
    ])
    opportunity = _clip_score(0.20 * trend + 0.55 * breadth + 0.10 * liquidity + 0.15 * structure)

    volatility = row.get("cross_section_volatility_20d")
    decline_ratio = row.get("market_large_decline_ratio_1d")
    negative_ad = max(0.0, -float(row.get("normalized_ad") or 0.0)) * 100.0
    weak_nhnl = max(0.0, -float(row.get("normalized_nhnl") or 0.0)) * 500.0
    risk = _clip_score(
        0.35 * _clip_score((float(volatility) if volatility is not None and not pd.isna(volatility) else 0.20) / 0.40 * 100.0)
        + 0.30 * _clip_score((float(decline_ratio) if decline_ratio is not None and not pd.isna(decline_ratio) else 0.0) / 0.10 * 100.0)
        + 0.20 * _clip_score(negative_ad)
        + 0.15 * _clip_score(weak_nhnl)
    )
    environment = _clip_score(0.70 * opportunity + 0.30 * (100.0 - risk))
    signal = "conservative" if environment <= 40.0 or risk >= 80.0 else "positive" if environment >= 65.0 and risk < 70.0 else "neutral"
    return environment, opportunity, risk, signal


def _rule_score(row: pd.Series) -> tuple[float, dict[str, float]]:
    trend = 0.0
    trend += _score_bool(row.get("above_ma20"), 4)
    trend += _score_bool(row.get("above_ma60"), 4)
    trend += _score_bool(row.get("above_ma120"), 3)
    trend += _score_bool(row.get("ma20_gt_ma60"), 4)
    trend += _score_bool(row.get("ma60_gt_ma120"), 3)
    trend += _score_positive(row.get("ret_20d"), 2)

    momentum = 5.0
    momentum += _score_bool(row.get("macd_gold"), 2)
    momentum += _score_bool(row.get("macd_dif_above_zero"), 1)
    momentum += _score_bool(row.get("macd_hist_up_3"), 2)
    momentum -= _score_bool(row.get("macd_hist_down_3"), 2)
    if bool(row.get("kdj_j_below_0")):
        momentum += 2 if _score_positive(row.get("ad_slope_5"), 1) else 1
    if bool(row.get("kdj_j_above_90")):
        momentum -= 3
    if bool(row.get("kdj_j_above_100")):
        momentum -= 2
    momentum = _clip_score(momentum, 0, 10)

    amount = 7.0
    if not pd.isna(row.get("amount_ratio_20")):
        ratio = float(row.get("amount_ratio_20"))
        if ratio >= 1.2 and float(row.get("ret_1d", 0) or 0) > 0:
            amount += 4
        elif ratio >= 1.2 and float(row.get("ret_1d", 0) or 0) < 0:
            amount -= 3
        if float(row.get("amount_slope_5_20", 0) or 0) > 0:
            amount += 2
    if bool(row.get("amount_stalling")):
        amount -= 3
    amount = _clip_score(amount, 0, 15)

    breadth = 8.0
    breadth += _score_positive(row.get("ad_slope_5"), 5, -3)
    breadth += _score_positive(row.get("ad_slope_20"), 5, -3)
    breadth += _score_positive(row.get("ad_slope_5_delta"), 2, -1)
    breadth = _clip_score(breadth, 0, 20)

    grouped = 7.0
    for col in (
        "hs300_minus_all_a_ad_slope_5",
        "csi1000_minus_hs300_ad_slope_5",
        "csi2000_minus_hs300_ad_slope_5",
        "chinext_minus_hs300_ad_slope_5",
    ):
        grouped += _score_positive(row.get(col), 2, -1)
    grouped = _clip_score(grouped, 0, 15)

    nhnl = 6.0
    nhnl += _score_positive(row.get("nhnl_norm"), 3, -2)
    nhnl += _score_positive(row.get("nhnl_slope_5"), 3, -2)
    nhnl += _score_positive(row.get("nhnl_slope_20"), 3, -2)
    nhnl += _score_positive(row.get("nhnl_sum5_slope_5"), 2, -1)
    nhnl = _clip_score(nhnl, 0, 15)

    risk = 5.0
    if not pd.isna(row.get("index_volatility_20d")) and float(row.get("index_volatility_20d")) > 0.02:
        risk -= 2
    if bool(row.get("amount_down_expand")):
        risk -= 2
    if bool(row.get("kdj_j_above_90")) and _score_positive(row.get("ad_slope_5"), 0, -1) < 0:
        risk -= 1
    risk = _clip_score(risk, 0, 5)

    parts = {
        "trend_score": round(trend, 4),
        "momentum_score": round(momentum, 4),
        "amount_score": round(amount, 4),
        "breadth_score": round(breadth, 4),
        "group_score": round(grouped, 4),
        "nhnl_score": round(nhnl, 4),
        "risk_score": round(risk, 4),
    }
    return _clip_score(sum(parts.values())), parts


def _probabilities(score: float) -> tuple[float, float, float, str]:
    bull = max(0.05, _clip_score((score - 55.0) / 25.0, 0.0, 1.0))
    bear = max(0.05, _clip_score((45.0 - score) / 20.0, 0.0, 1.0))
    neutral = max(0.05, _clip_score(1.0 - abs(score - 50.0) / 30.0, 0.0, 1.0))
    total = bull + neutral + bear
    bull, neutral, bear = bull / total, neutral / total, bear / total
    if score >= 70:
        signal = "bull"
    elif score <= 35:
        signal = "bear"
    else:
        signal = "neutral"
    return round(bull, 4), round(neutral, 4), round(bear, 4), signal


def _bool_value(value: Any) -> bool:
    if value is None or pd.isna(value):
        return False
    return bool(value)


def _float_value(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _rule_h3_v2_score(row: pd.Series) -> tuple[float, dict[str, Any], tuple[float, float, float, str]]:
    trend = 0.0
    trend += 4.0 if _bool_value(row.get("above_ma20")) else -1.0
    trend += 4.0 if _bool_value(row.get("above_ma60")) else -1.0
    trend += 3.0 if _bool_value(row.get("ma20_gt_ma60")) else -1.0
    trend += 2.0 if _bool_value(row.get("ma60_gt_ma120")) else 0.0
    trend += 2.0 if _float_value(row.get("ma20_slope_5")) > 0 else -1.0
    trend += 1.5 if _float_value(row.get("ret_20d")) > 0 else -0.5
    trend = _clip_score(trend, 0, 18)

    ret5 = _float_value(row.get("ret_5d"))
    dist_ma20 = _float_value(row.get("dist_ma20"))
    drawdown20 = _float_value(row.get("drawdown_20d"))
    amount_ratio = _float_value(row.get("amount_ratio_20"), 1.0)
    intraday_range = _float_value(row.get("intraday_range_pct"))
    ad_slope_5 = _float_value(row.get("ad_slope_5"))
    ad_slope_delta = _float_value(row.get("ad_slope_5_delta"))
    ad_norm = _float_value(row.get("ad_norm"))
    nhnl_slope_3 = _float_value(row.get("nhnl_slope_3"))
    nhnl_slope_5 = _float_value(row.get("nhnl_slope_5"))
    upper_shadow = _float_value(row.get("upper_shadow_ratio"))
    ret20 = _float_value(row.get("ret_20d"))
    ma20_slope_5 = _float_value(row.get("ma20_slope_5"))
    above_ma20 = _bool_value(row.get("above_ma20"))
    above_ma60 = _bool_value(row.get("above_ma60"))
    above_ma120 = _bool_value(row.get("above_ma120"))
    ma20_gt_ma60 = _bool_value(row.get("ma20_gt_ma60"))

    oversold = (
        drawdown20 < -0.02
        or dist_ma20 < -0.02
        or ret5 < -0.02
        or _bool_value(row.get("kdj_j_below_minus10"))
    )
    deep_oversold = (
        drawdown20 < -0.035
        or dist_ma20 < -0.03
        or ret5 < -0.035
        or _bool_value(row.get("kdj_j_below_minus10"))
    )
    amount_release = amount_ratio > 1.1
    range_release = intraday_range > 0.025
    breadth_repair = ad_slope_delta > 0
    amount_down = _bool_value(row.get("amount_down_expand"))
    amount_stalling = _bool_value(row.get("amount_stalling"))
    kdj_below_0 = _bool_value(row.get("kdj_j_below_0"))
    kdj_below_minus10 = _bool_value(row.get("kdj_j_below_minus10"))
    amount_up_confirm = _bool_value(row.get("amount_up_confirm"))
    break_high_20d = _bool_value(row.get("break_high_20d"))
    break_low_20d = _bool_value(row.get("break_low_20d"))

    high_vol_repair = oversold and (
        amount_down
        or amount_ratio > 1.2
        or intraday_range > 0.03
        or (breadth_repair and ad_norm > -0.2)
    )
    if high_vol_repair:
        market_regime = "high_vol_repair"
    elif trend >= 11 and above_ma20 and above_ma60 and ma20_gt_ma60 and ad_slope_5 >= 0:
        market_regime = "trend_bull"
    elif (not above_ma60) and (not above_ma120) and ma20_slope_5 <= 0 and (ad_slope_5 < 0 or break_low_20d):
        market_regime = "downtrend"
    elif above_ma60 and trend >= 7:
        market_regime = "strong_range"
    else:
        market_regime = "weak_range"

    rebound = 0.0
    rebound_reasons: list[str] = []
    if oversold:
        rebound += 4.0
        rebound_reasons.append("oversold")
        if deep_oversold:
            rebound += 2.0
            rebound_reasons.append("deep_oversold")
        if amount_release:
            rebound += 2.0
            rebound_reasons.append("release_amount_confirm")
        if range_release:
            rebound += 1.5
            rebound_reasons.append("release_range_confirm")
        if amount_down:
            rebound += 3.5
            rebound_reasons.append("volume_down_repair")
        if breadth_repair:
            rebound += 2.0
            rebound_reasons.append("breadth_delta_repair")
        if kdj_below_minus10:
            rebound += 2.0
            rebound_reasons.append("kdj_deep_low")
        elif kdj_below_0:
            rebound += 1.0
            rebound_reasons.append("kdj_low_confirm")
    elif kdj_below_minus10 and (amount_release or breadth_repair):
        rebound += 4.0
        rebound_reasons.append("kdj_deep_low")
        if amount_release:
            rebound += 1.5
            rebound_reasons.append("release_amount_confirm")
        if breadth_repair:
            rebound += 1.5
            rebound_reasons.append("breadth_delta_repair")
    elif kdj_below_0 and breadth_repair:
        rebound += 1.5
        rebound_reasons.append("kdj_low_confirm")
    rebound = _clip_score(rebound, 0, 16)

    breakout = 0.0
    breakout_reasons: list[str] = []
    if break_high_20d and amount_ratio > 1.1 and ad_norm > 0:
        breakout += 7.0
        breakout_reasons.append("breakout_confirm")
        if ad_slope_5 > 0:
            breakout += 2.0
            breakout_reasons.append("breakout_breadth_follow")
        if amount_ratio <= 1.8:
            breakout += 1.0
            breakout_reasons.append("breakout_volume_healthy")
    if amount_up_confirm and ad_slope_5 > 0:
        breakout += 3.0
        breakout_reasons.append("volume_up_confirm")
        if trend >= 11:
            breakout += 1.0
            breakout_reasons.append("volume_trend_support")
    breakout = _clip_score(breakout, 0, 14)

    trend_follow = 0.0
    trend_follow_reasons: list[str] = []
    if trend >= 11 and ad_slope_5 > 0:
        trend_follow += 5.0
        trend_follow_reasons.append("trend_breadth_support")
        if nhnl_slope_5 > 0 or nhnl_slope_3 > 0:
            trend_follow += 2.0
            trend_follow_reasons.append("trend_nhnl_support")
        if amount_up_confirm:
            trend_follow += 2.0
            trend_follow_reasons.append("trend_volume_support")
        if ret20 > 0:
            trend_follow += 1.0
            trend_follow_reasons.append("trend_return_support")
    trend_follow = _clip_score(trend_follow, 0, 12)

    sub_scores = {
        "rebound": rebound,
        "breakout": breakout,
        "trend_follow": trend_follow,
    }
    opportunity_type = max(sub_scores, key=sub_scores.get)
    primary_reasons = {
        "rebound": rebound_reasons,
        "breakout": breakout_reasons,
        "trend_follow": trend_follow_reasons,
    }[opportunity_type]
    opportunity_reasons = rebound_reasons + breakout_reasons + trend_follow_reasons
    active_sources = sum(1 for value in sub_scores.values() if value >= 5)
    synergy = 2.0 if active_sources >= 2 else 0.0
    if rebound >= 8 and (breakout >= 5 or trend_follow >= 5):
        synergy += 1.0
    opportunity = max(sub_scores.values()) + synergy
    opportunity = _clip_score(opportunity, 0, 24)

    overheat_weak = _bool_value(row.get("kdj_j_above_90")) and ad_slope_5 < 0
    overheat_risk = 0.0
    overheat_reasons: list[str] = []
    if overheat_weak:
        overheat_risk += 6.0
        overheat_reasons.append("overheat_ad_weak")
        if _bool_value(row.get("kdj_j_above_100")):
            overheat_risk += 3.0
            overheat_reasons.append("kdj_j_above_100")
        if nhnl_slope_3 <= 0:
            overheat_risk += 3.0
            overheat_reasons.append("nhnl_weak")
        if upper_shadow > 0.35 and (amount_stalling or nhnl_slope_3 <= 0):
            overheat_risk += 2.0
            overheat_reasons.append("upper_shadow")
        if amount_stalling:
            overheat_risk += 3.0
            overheat_reasons.append("amount_stalling")
        if dist_ma20 > 0.02:
            overheat_risk += 2.0
            overheat_reasons.append("high_above_ma20")
    overheat_risk = _clip_score(overheat_risk, 0, 18)

    breakdown_risk = 0.0
    breakdown_reasons: list[str] = []
    if amount_down and not oversold and ad_slope_5 < 0:
        breakdown_risk += 4.0
        breakdown_reasons.append("volume_down_weak")
    if break_low_20d and ad_slope_5 < 0:
        breakdown_risk += 3.0
        breakdown_reasons.append("break_low_weak")
        if not above_ma60:
            breakdown_risk += 2.0
            breakdown_reasons.append("below_ma60_break")
        if ma20_slope_5 <= 0:
            breakdown_risk += 1.0
            breakdown_reasons.append("ma20_slope_weak")
    if (not above_ma60) and ad_slope_5 < 0 and nhnl_slope_3 < 0:
        breakdown_risk += 3.0
        breakdown_reasons.append("trend_breadth_weak")
    if ret5 < -0.02 and not deep_oversold and ad_slope_5 < 0:
        breakdown_risk += 2.0
        breakdown_reasons.append("short_down_weak")
    if deep_oversold and amount_release:
        breakdown_risk -= 2.0
        breakdown_reasons.append("deep_oversold_risk_discount")
    breakdown_risk = _clip_score(breakdown_risk, 0, 18)

    risk_type = "overheat" if overheat_risk >= breakdown_risk else "breakdown"
    risk_reasons = overheat_reasons + breakdown_reasons
    risk = max(overheat_risk, breakdown_risk)
    if overheat_risk >= 6 and breakdown_risk >= 6:
        risk += 2.0
    if market_regime == "high_vol_repair" and breakdown_risk > 0:
        risk -= 1.0
    risk = _clip_score(risk, 0, 24)

    net = opportunity - risk
    adjusted = net + (trend - 9.0) * 0.25
    bull_min = 8.0
    bull_adjusted_min = 5.0
    bear_min = 8.0
    bear_adjusted_max = -4.0
    if market_regime == "trend_bull":
        bull_min = 7.5
        bull_adjusted_min = 4.5
        bear_min = 9.0
        bear_adjusted_max = -5.0
    elif market_regime == "high_vol_repair":
        bull_min = 8.0
        bull_adjusted_min = 4.0
        bear_min = 9.0
        bear_adjusted_max = -4.5
    elif market_regime == "downtrend":
        bull_min = 8.0
        bull_adjusted_min = 5.5
        bear_min = 9.0
        bear_adjusted_max = -5.0
    elif market_regime == "weak_range":
        bull_min = 9.0
        bull_adjusted_min = 5.5

    bull_allowed = not (
        market_regime == "downtrend"
        and not (rebound >= 8 and risk <= 3 and (amount_down or breadth_repair or amount_release))
    )
    bear_allowed = overheat_risk >= 6 or (
        breakdown_risk >= 8
        and amount_down
        and not oversold
        and ad_slope_5 < 0
    )
    if opportunity >= bull_min and adjusted >= bull_adjusted_min and bull_allowed:
        signal = "bull"
    elif risk >= bear_min and adjusted <= bear_adjusted_max and bear_allowed:
        signal = "bear"
    else:
        signal = "neutral"

    bull_raw = max(0.05, min(0.90, 0.25 + adjusted / 30.0))
    bear_raw = max(0.05, min(0.90, 0.25 - adjusted / 30.0 + risk / 80.0))
    neutral_raw = max(0.10, 1.0 - abs(adjusted) / 18.0)
    total = bull_raw + neutral_raw + bear_raw
    p_bull = round(bull_raw / total, 4)
    p_neutral = round(neutral_raw / total, 4)
    p_bear = round(bear_raw / total, 4)
    market_score = _clip_score(50.0 + adjusted * 2.0, 0, 100)
    parts = {
        "opportunity_score": round(opportunity, 4),
        "rebound_score": round(rebound, 4),
        "breakout_score": round(breakout, 4),
        "trend_follow_score": round(trend_follow, 4),
        "risk_score": round(risk, 4),
        "overheat_risk_score": round(overheat_risk, 4),
        "breakdown_risk_score": round(breakdown_risk, 4),
        "trend_context_score": round(trend, 4),
        "net_score": round(net, 4),
        "adjusted_net_score": round(adjusted, 4),
        "market_regime": market_regime,
        "opportunity_type": opportunity_type if opportunity > 0 else "",
        "risk_type": risk_type if risk > 0 else "",
        "rebound_reason": "|".join(dict.fromkeys(rebound_reasons)),
        "breakout_reason": "|".join(dict.fromkeys(breakout_reasons)),
        "trend_follow_reason": "|".join(dict.fromkeys(trend_follow_reasons)),
        "overheat_risk_reason": "|".join(dict.fromkeys(overheat_reasons)),
        "breakdown_risk_reason": "|".join(dict.fromkeys(breakdown_reasons)),
        "opportunity_reason": "|".join(dict.fromkeys(opportunity_reasons)),
        "risk_reason": "|".join(dict.fromkeys(risk_reasons)),
        "signal_reason": (
            "|".join(dict.fromkeys(primary_reasons or opportunity_reasons))
            if signal == "bull"
            else "|".join(dict.fromkeys(risk_reasons))
            if signal == "bear"
            else f"watch_{opportunity_type}"
            if opportunity >= 8
            else "watch_risk"
            if risk >= 8
            else "neutral"
        ),
    }
    return market_score, parts, (p_bull, p_neutral, p_bear, signal)


def build_rule_forecast(feature_df: pd.DataFrame, horizon: int = 5, model: str = "rule_v1") -> pd.DataFrame:
    """Apply a rule forecast model to a feature frame."""
    model = (model or "rule_v1").lower()
    if model not in {"rule_v1", "rule_h3_v2"}:
        raise ValueError(f"不支持的指数预测模型: {model}")
    rows = []
    for _, row in feature_df.iterrows():
        if model == "rule_h3_v2":
            score, parts, probs = _rule_h3_v2_score(row)
            p_bull, p_neutral, p_bear, signal = probs
        else:
            score, parts = _rule_score(row)
            p_bull, p_neutral, p_bear, signal = _probabilities(score)
        environment_score, predicted_opportunity, predicted_risk, environment_signal = _environment_prediction_score(row)
        out = {
            "trade_date": row.get("trade_date"),
            "symbol": row.get("symbol"),
            "close": row.get("close"),
            "horizon": int(horizon),
            "model": model,
            "environment_model": "shared_environment_rule_v1",
            "market_score": round(environment_score, 4),
            "legacy_index_rule_score": round(score, 4),
            "predicted_opportunity_score": round(predicted_opportunity, 4),
            "predicted_risk_score": round(predicted_risk, 4),
            "p_bull": p_bull,
            "p_neutral": p_neutral,
            "p_bear": p_bear,
            "signal": signal,
            "environment_signal": environment_signal,
            "breadth_up": row.get("breadth_up"),
            "breadth_flat": row.get("breadth_flat"),
            "breadth_down": row.get("breadth_down"),
            f"fwd_ret_{int(horizon)}d": row.get(f"fwd_ret_{int(horizon)}d"),
            f"label_{int(horizon)}d": row.get(f"label_{int(horizon)}d"),
            f"label_abs_{int(horizon)}d": row.get(f"label_abs_{int(horizon)}d"),
            f"label_rank_{int(horizon)}d": row.get(f"label_rank_{int(horizon)}d"),
        }
        for name in (
            "stock_up_ratio", "stocks_above_ma20_ratio", "stocks_above_ma50_ratio",
            "stocks_above_ma200_ratio", "cross_section_volatility_20d",
            "market_large_decline_ratio_1d", "index_equal_weight_gap_1d",
            "index_equal_weight_gap_5d", "large_small_relative_strength_1d",
            "large_small_relative_strength_5d", "normalized_ad", "normalized_nhnl",
        ):
            out[name] = row.get(name)
        suffix = f"_{int(horizon)}d"
        for name in (
            "market_cap_index_return", "equal_weight_return", "median_stock_return",
            "stock_win_rate", "future_breadth", "return_q10", "median_max_drawdown",
            "volatility", "large_decline_ratio", "opportunity_score", "risk_score",
            "environment_score", "environment_label", "index_breadth_gap", "divergence_label",
        ):
            out[f"{name}{suffix}"] = row.get(f"{name}{suffix}")
        out.update(parts)
        rows.append(out)
    return pd.DataFrame(rows)


def evaluate_forecast(
    predictions: pd.DataFrame,
    horizon: int,
    strategy_returns: dict[str, pd.Series] | None = None,
) -> dict[str, Any]:
    label_col = f"label_{int(horizon)}d"
    ret_col = f"fwd_ret_{int(horizon)}d"
    environment_col = f"environment_label_{int(horizon)}d"
    has_environment = environment_col in predictions.columns and predictions[environment_col].notna().any()
    evaluated = predictions.dropna(subset=[environment_col if has_environment else label_col]).copy()
    curve, timing_stats = _timing_curve(predictions)
    if evaluated.empty:
        return {"sample_count": 0, "timing_curve": curve, "timing_stats": timing_stats}
    if has_environment:
        accuracy = float((evaluated["environment_signal"] == evaluated[environment_col]).mean())
    else:
        accuracy = float((evaluated["signal"] == evaluated[label_col]).mean())
    bullish = evaluated[evaluated["signal"] == "bull"]
    bearish = evaluated[evaluated["signal"] == "bear"]
    result = {
        "sample_count": int(len(evaluated)),
        "accuracy": round(accuracy, 4),
        "bull_count": int(len(bullish)),
        "bear_count": int(len(bearish)),
        "bull_avg_return": round(float(bullish[ret_col].mean()), 6) if not bullish.empty else None,
        "bear_avg_return": round(float(bearish[ret_col].mean()), 6) if not bearish.empty else None,
        "signal_summary": _signal_summary(evaluated, ret_col, label_col),
        "score_buckets": _score_bucket_summary(evaluated, ret_col),
        "timing_curve": curve,
        "timing_stats": timing_stats,
        "latest": predictions.iloc[-1].to_dict() if not predictions.empty else {},
    }
    if has_environment:
        result["environment_evaluation"] = environment_evaluation(
            evaluated,
            horizon=int(horizon),
            predicted_col="environment_signal",
            strategy_returns=strategy_returns,
        )
        result["target_type"] = "cross_section_environment"
    else:
        result["target_type"] = "legacy_index_return"
    return result


def save_forecast_outputs(
    config: dict,
    symbol: str,
    horizon: int,
    indicators: pd.DataFrame,
    features: pd.DataFrame,
    predictions: pd.DataFrame,
    model: str = "rule_v1",
) -> ForecastPaths:
    paths = forecast_paths(config, symbol, horizon, model=model)
    paths.root.mkdir(parents=True, exist_ok=True)
    indicators.to_csv(paths.indicators, index=False)
    features.to_csv(paths.features, index=False)
    predictions.to_csv(paths.predictions, index=False)
    return paths
