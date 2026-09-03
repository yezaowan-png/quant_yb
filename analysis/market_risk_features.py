"""As-of features for the independent market extreme-risk gate."""

from __future__ import annotations

import numpy as np
import pandas as pd


MINIMAL_RISK_FEATURES = (
    "current_large_decline_ratio",
    "cross_section_dispersion",
    "realized_volatility_5d",
    "normalized_ad",
    "ad_slope_5",
    "normalized_nhnl",
    "nhnl_slope_5",
    "index_return_5d",
    "pct_above_ma20",
    "equal_weight_minus_cap_weight_return_5d",
    "ad_level_x_slope_5",
)

FORBIDDEN_FEATURE_PREFIXES = (
    "future_", "label_", "risk_label_", "target_", "environment_",
)


def is_forbidden_risk_feature(column: str) -> bool:
    name = str(column)
    return name.startswith(FORBIDDEN_FEATURE_PREFIXES) or name in {
        "date", "trade_date", "symbol", "open", "high", "low", "close", "volume", "amount",
        "ad_line", "nhnl_line", "dif", "dea", "macd",
    }


def build_market_risk_features(
    index_df: pd.DataFrame,
    close_matrix: pd.DataFrame,
    large_decline_threshold: float = -0.05,
    limit_down_threshold: float = -0.095,
) -> pd.DataFrame:
    """Build current-state features using T and earlier closes only."""
    if close_matrix.empty:
        raise ValueError("极端风险特征需要本地个股收盘价矩阵")
    index = index_df.copy()
    index["date"] = pd.to_datetime(index["date"], errors="coerce")
    for column in ("close", "amount"):
        if column in index.columns:
            index[column] = pd.to_numeric(index[column], errors="coerce")
    index = index.dropna(subset=["date", "close"]).drop_duplicates("date", keep="last").sort_values("date").set_index("date")
    closes = close_matrix.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan).reindex(index.index)
    closes = closes.where(closes > 0)
    daily = closes.pct_change(fill_method=None)
    valid_daily = daily.notna().sum(axis=1).replace(0, np.nan)
    output = pd.DataFrame(index=index.index)
    output["trade_date"] = output.index.strftime("%Y-%m-%d")
    output["effective_stock_count"] = closes.notna().sum(axis=1)
    output["stock_up_ratio"] = (daily > 0).sum(axis=1) / valid_daily
    output["current_large_decline_ratio"] = (daily <= float(large_decline_threshold)).sum(axis=1) / valid_daily
    output["limit_down_ratio"] = (daily <= float(limit_down_threshold)).sum(axis=1) / valid_daily
    output["cross_section_dispersion"] = daily.std(axis=1, skipna=True)
    equal_daily = daily.mean(axis=1, skipna=True)
    output["realized_volatility_5d"] = equal_daily.rolling(5, min_periods=5).std(ddof=0) * np.sqrt(252.0)
    output["equal_weight_return_5d"] = (
        (1.0 + equal_daily).rolling(5, min_periods=5).apply(np.prod, raw=True) - 1.0
    )
    index_return = index["close"].pct_change(fill_method=None)
    output["index_return_5d"] = index["close"] / index["close"].shift(5) - 1.0
    output["equal_weight_minus_cap_weight_return_5d"] = output["equal_weight_return_5d"] - output["index_return_5d"]
    output["amount_ratio_20d"] = (
        index["amount"] / index["amount"].rolling(20, min_periods=20).mean()
        if "amount" in index.columns else np.nan
    )

    up = (daily > 0).sum(axis=1)
    down = (daily < 0).sum(axis=1)
    breadth_total = (up + down).replace(0, np.nan)
    output["normalized_ad"] = (up - down) / breadth_total
    ad_line = output["normalized_ad"].fillna(0.0).cumsum()
    output["ad_slope_3"] = ad_line - ad_line.shift(3)
    output["ad_slope_5"] = ad_line - ad_line.shift(5)

    high20 = closes.rolling(20, min_periods=20).max().shift(1)
    low20 = closes.rolling(20, min_periods=20).min().shift(1)
    valid_extreme = closes.notna() & high20.notna() & low20.notna()
    new_high = ((closes > high20) & valid_extreme).sum(axis=1)
    new_low = ((closes < low20) & valid_extreme).sum(axis=1)
    extreme_total = valid_extreme.sum(axis=1).replace(0, np.nan)
    output["new_low_ratio"] = new_low / extreme_total
    output["normalized_nhnl"] = (new_high - new_low) / extreme_total
    nhnl_line = output["normalized_nhnl"].fillna(0.0).cumsum()
    output["nhnl_slope_3"] = nhnl_line - nhnl_line.shift(3)
    output["nhnl_slope_5"] = nhnl_line - nhnl_line.shift(5)

    for window in (20, 60):
        moving_average = closes.rolling(window, min_periods=window).mean()
        valid = closes.notna() & moving_average.notna()
        output[f"pct_above_ma{window}"] = ((closes > moving_average) & valid).sum(axis=1) / valid.sum(axis=1).replace(0, np.nan)
    output["ad_level_x_slope_5"] = output["normalized_ad"] * output["ad_slope_5"]
    return output.reset_index(drop=True)


def available_minimal_features(frame: pd.DataFrame) -> list[str]:
    return [
        feature for feature in MINIMAL_RISK_FEATURES
        if feature in frame.columns and not is_forbidden_risk_feature(feature)
    ]


def assert_asof_feature_contract(frame: pd.DataFrame) -> None:
    forbidden = [column for column in frame.columns if is_forbidden_risk_feature(column) and column != "trade_date"]
    if forbidden:
        raise ValueError(f"风险特征包含禁止字段: {', '.join(forbidden)}")
    if len(available_minimal_features(frame)) > 11:
        raise ValueError("极端风险最小模型特征不得超过11个")
