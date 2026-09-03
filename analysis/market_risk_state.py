"""Current market pressure states; this module never reads future outcomes."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


CURRENT_STATES = ("normal", "stressed", "panic", "recovering")
DATA_QUALITY_FLAGS = (
    "incomplete_point_in_time_universe",
    "missing_delisted_stocks",
    "missing_historical_st_status",
)


def trailing_percentile(
    series: pd.Series,
    window: int = 756,
    min_periods: int = 60,
) -> pd.Series:
    """Percentile against T and earlier values only."""
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    result = pd.Series(np.nan, index=series.index, dtype="float64")
    for position, current in enumerate(values.to_numpy(dtype="float64")):
        if not np.isfinite(current):
            continue
        history = values.iloc[max(0, position - window + 1) : position + 1].dropna().to_numpy()
        if len(history) >= min_periods:
            result.iloc[position] = float(np.mean(history <= current))
    return result


def build_market_risk_states(features: pd.DataFrame) -> pd.DataFrame:
    """Classify normal/stressed/panic/recovering using rolling percentiles."""
    required = [
        "trade_date", "normalized_ad", "ad_slope_5", "normalized_nhnl", "nhnl_slope_5",
        "current_large_decline_ratio", "cross_section_dispersion", "realized_volatility_5d",
        "pct_above_ma20", "new_low_ratio", "limit_down_ratio",
    ]
    missing = [column for column in required if column not in features.columns]
    if missing:
        raise ValueError(f"市场风险状态缺少字段: {', '.join(missing)}")
    work = features.copy()
    percentiles = {
        column: trailing_percentile(work[column])
        for column in required if column != "trade_date"
    }
    low_ad = percentiles["normalized_ad"] <= 0.10
    low_nhnl = percentiles["normalized_nhnl"] <= 0.10
    weak_ma = percentiles["pct_above_ma20"] <= 0.20
    high_decline = percentiles["current_large_decline_ratio"] >= 0.90
    high_dispersion = percentiles["cross_section_dispersion"] >= 0.90
    high_volatility = percentiles["realized_volatility_5d"] >= 0.90
    high_new_low = percentiles["new_low_ratio"] >= 0.90
    high_limit_down = percentiles["limit_down_ratio"] >= 0.90
    ad_slope = pd.to_numeric(work["ad_slope_5"], errors="coerce")
    nhnl_slope = pd.to_numeric(work["nhnl_slope_5"], errors="coerce")
    improving = (ad_slope > 0) & (nhnl_slope > 0)
    deteriorating = (ad_slope <= 0) & (nhnl_slope <= 0)
    extreme_count = pd.concat(
        [low_ad, low_nhnl, weak_ma, high_decline, high_dispersion, high_volatility, high_new_low, high_limit_down],
        axis=1,
    ).sum(axis=1)
    weak_level = low_ad | low_nhnl | weak_ma | high_new_low
    state = pd.Series("normal", index=work.index, dtype=object)
    state[(extreme_count >= 2) | (weak_level & deteriorating)] = "stressed"
    state[(extreme_count >= 5) & deteriorating] = "panic"
    state[weak_level & improving & (extreme_count >= 1)] = "recovering"
    risk_score = (
        15 * low_ad.astype(float) + 15 * low_nhnl.astype(float) + 10 * weak_ma.astype(float)
        + 15 * high_decline.astype(float) + 10 * high_dispersion.astype(float)
        + 10 * high_volatility.astype(float) + 15 * high_new_low.astype(float)
        + 10 * high_limit_down.astype(float)
    ).clip(0, 100)
    risk_score[state == "recovering"] = (risk_score[state == "recovering"] - 20).clip(lower=20)
    out = pd.DataFrame({
        "trade_date": work["trade_date"].astype(str),
        "current_state": state,
        "risk_score": risk_score.round(2),
        "extreme_indicator_count": extreme_count.astype(int),
        "breadth_improving": improving,
        "breadth_deteriorating": deteriorating,
    })
    out["risk_flags"] = [
        [
            name for name, active in (
                ("ad_extreme_weak", bool(low_ad.iloc[i])), ("nhnl_extreme_weak", bool(low_nhnl.iloc[i])),
                ("ma20_breadth_weak", bool(weak_ma.iloc[i])), ("large_decline_extreme", bool(high_decline.iloc[i])),
                ("dispersion_extreme", bool(high_dispersion.iloc[i])), ("volatility_extreme", bool(high_volatility.iloc[i])),
                ("new_low_extreme", bool(high_new_low.iloc[i])), ("limit_down_extreme", bool(high_limit_down.iloc[i])),
            ) if active
        ]
        for i in range(len(out))
    ]
    return out


def latest_state_payload(
    states: pd.DataFrame,
    probabilities: dict[int, float | None] | None = None,
) -> dict[str, Any]:
    if states.empty:
        raise ValueError("市场风险状态为空")
    row = states.iloc[-1]
    state = str(row["current_state"])
    reasons = {
        "normal": ["未检测到系统性风险扩散"],
        "stressed": ["多项风险指标开始恶化"],
        "panic": ["尾部、广度和波动风险同时处于极端区域"],
        "recovering": ["风险水平仍弱，但A/D与NH-NL斜率开始改善"],
    }[state]
    return {
        "date": str(row["trade_date"]), "current_state": state,
        "risk_score": float(row["risk_score"]),
        **{f"extreme_risk_probability_{horizon}d": (probabilities or {}).get(horizon) for horizon in (1, 5, 10, 20)},
        "reasons": reasons, "risk_flags": list(row.get("risk_flags") or []),
        "data_quality_flags": list(DATA_QUALITY_FLAGS),
    }
