"""Transparent, fold-local labels for the independent market extreme-risk gate."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


RISK_HORIZONS = (1, 5, 10, 20)
RISK_LABELS = ("R1", "R2", "R3", "R4", "R5")
FUTURE_STATES = (
    "persistent_tail_risk",
    "shock_then_recovery",
    "broad_weakness",
    "normal_or_positive",
)


def _finite_quantile(values: pd.Series, quantile: float) -> float:
    numeric = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    return float(numeric.quantile(quantile)) if len(numeric) else np.nan


def build_market_risk_outcomes(
    index_df: pd.DataFrame,
    close_matrix: pd.DataFrame,
    horizons: tuple[int, ...] = RISK_HORIZONS,
    large_decline_threshold: float = -0.05,
) -> pd.DataFrame:
    """Build future path outcomes only; no predictor or global label is created here."""
    if close_matrix.empty:
        raise ValueError("极端风险标签需要本地个股收盘价矩阵")
    index = index_df[["date", "close"]].copy()
    index["date"] = pd.to_datetime(index["date"], errors="coerce")
    index["close"] = pd.to_numeric(index["close"], errors="coerce")
    index = index.dropna().drop_duplicates("date", keep="last").sort_values("date").set_index("date")
    closes = close_matrix.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan).reindex(index.index)
    closes = closes.where(closes > 0)
    daily = closes.pct_change(fill_method=None)
    output = pd.DataFrame(index=index.index)
    output["trade_date"] = output.index.strftime("%Y-%m-%d")

    for raw_horizon in horizons:
        horizon = int(raw_horizon)
        if horizon <= 0:
            raise ValueError("风险周期必须为正整数")
        suffix = f"_{horizon}d"
        terminal_returns = closes.shift(-horizon) / closes - 1.0
        valid_count = terminal_returns.notna().sum(axis=1)
        output[f"effective_stock_count{suffix}"] = valid_count
        output[f"future_return_q10{suffix}"] = terminal_returns.quantile(0.10, axis=1)
        output[f"future_equal_weight_return{suffix}"] = terminal_returns.mean(axis=1, skipna=True)
        output[f"future_median_return{suffix}"] = terminal_returns.median(axis=1, skipna=True)
        output[f"future_stock_win_rate{suffix}"] = (
            (terminal_returns > 0).sum(axis=1) / valid_count.replace(0, np.nan)
        )
        output[f"future_large_decline_ratio{suffix}"] = (
            (terminal_returns <= float(large_decline_threshold)).sum(axis=1)
            / valid_count.replace(0, np.nan)
        )

        median_max_drawdown = pd.Series(np.nan, index=output.index, dtype="float64")
        terminal_drawdown = pd.Series(np.nan, index=output.index, dtype="float64")
        recovery_ratio = pd.Series(np.nan, index=output.index, dtype="float64")
        negative_breadth_days = pd.Series(np.nan, index=output.index, dtype="float64")
        for position in range(len(output) - horizon):
            stock_path = closes.iloc[position : position + horizon + 1].to_numpy(dtype="float64")
            if stock_path.shape[0] != horizon + 1:
                continue
            valid = np.isfinite(stock_path).all(axis=0) & (stock_path[0] > 0)
            if valid.any():
                normalized = stock_path[:, valid] / stock_path[0, valid]
                running_max = np.maximum.accumulate(normalized, axis=0)
                drawdowns = np.min(normalized / running_max - 1.0, axis=0)
                median_max_drawdown.iloc[position] = float(np.median(drawdowns))
            path_daily = daily.iloc[position + 1 : position + horizon + 1]
            ew_daily = path_daily.mean(axis=1, skipna=True).fillna(0.0).to_numpy(dtype="float64")
            ew_value = np.concatenate([[1.0], np.cumprod(1.0 + ew_daily)])
            minimum = float(np.min(ew_value))
            final = float(ew_value[-1])
            terminal_drawdown.iloc[position] = final / float(np.max(ew_value)) - 1.0
            recovery_ratio.iloc[position] = (final - minimum) / (abs(minimum - 1.0) + 1e-9)
            up = (path_daily > 0).sum(axis=1)
            down = (path_daily < 0).sum(axis=1)
            negative_breadth_days.iloc[position] = float((down > up).sum())

        output[f"future_median_max_drawdown{suffix}"] = median_max_drawdown
        output[f"future_terminal_drawdown{suffix}"] = terminal_drawdown
        output[f"future_recovery_ratio{suffix}"] = recovery_ratio.clip(lower=0.0)
        output[f"future_negative_breadth_days{suffix}"] = negative_breadth_days
    return output.reset_index(drop=True)


def fold_risk_labels(
    train: pd.DataFrame,
    apply: pd.DataFrame,
    horizon: int,
) -> pd.DataFrame:
    """Apply R1-R5 and mutually exclusive states using thresholds fitted on train only."""
    suffix = f"_{int(horizon)}d"
    required = [
        f"future_return_q10{suffix}", f"future_median_return{suffix}",
        f"future_stock_win_rate{suffix}", f"future_large_decline_ratio{suffix}",
        f"future_median_max_drawdown{suffix}", f"future_recovery_ratio{suffix}",
        f"future_negative_breadth_days{suffix}",
    ]
    missing = [column for column in required if column not in train.columns or column not in apply.columns]
    if missing:
        raise ValueError(f"风险标签缺少字段: {', '.join(missing)}")
    q10_cut = _finite_quantile(train[required[0]], 0.20)
    median_cut = min(0.0, _finite_quantile(train[required[1]], 0.30))
    decline_cut = _finite_quantile(train[required[3]], 0.80)
    drawdown_cut = _finite_quantile(train[required[4]], 0.20)
    q10 = pd.to_numeric(apply[required[0]], errors="coerce")
    median = pd.to_numeric(apply[required[1]], errors="coerce")
    win_rate = pd.to_numeric(apply[required[2]], errors="coerce")
    decline = pd.to_numeric(apply[required[3]], errors="coerce")
    drawdown = pd.to_numeric(apply[required[4]], errors="coerce")
    recovery = pd.to_numeric(apply[required[5]], errors="coerce")
    negative_days = pd.to_numeric(apply[required[6]], errors="coerce")
    tail = q10 <= q10_cut
    weak_median = median <= median_cut
    high_decline = decline >= decline_cut
    negative_majority = negative_days >= max(1, int(horizon) // 2 + 1)
    broad_conditions = pd.concat(
        [(win_rate < 0.40), high_decline, negative_majority, (median < 0)], axis=1
    ).sum(axis=1)
    labels = pd.DataFrame(index=apply.index)
    labels["R1"] = tail
    labels["R2"] = tail & weak_median & (recovery < 0.50)
    labels["R3"] = broad_conditions >= 2
    labels["R4"] = drawdown <= drawdown_cut
    labels["R5"] = high_decline
    labels["future_risk_state"] = np.where(
        tail & (recovery < 0.50),
        "persistent_tail_risk",
        np.where(
            tail & (recovery >= 0.50),
            "shock_then_recovery",
            np.where((~tail) & (broad_conditions >= 2), "broad_weakness", "normal_or_positive"),
        ),
    )
    labels["q10_cut"] = q10_cut
    labels["median_cut"] = median_cut
    labels["large_decline_cut"] = decline_cut
    labels["max_drawdown_cut"] = drawdown_cut
    return labels


def expanding_risk_labels(
    outcomes: pd.DataFrame,
    horizon: int,
    min_train: int = 252,
) -> pd.DataFrame:
    """Create research labels using only outcomes completed before each row."""
    result = outcomes[["trade_date"]].copy()
    for label in RISK_LABELS:
        result[label] = pd.Series(pd.NA, index=result.index, dtype="boolean")
    result["future_risk_state"] = None
    for position in range(int(min_train) + int(horizon), len(outcomes)):
        train_end = position - int(horizon)
        train = outcomes.iloc[:train_end]
        applied = fold_risk_labels(train, outcomes.iloc[[position]], horizon)
        for label in RISK_LABELS:
            result.loc[position, label] = bool(applied.iloc[0][label])
        result.loc[position, "future_risk_state"] = applied.iloc[0]["future_risk_state"]
    return result


def risk_outcome_columns(horizon: int) -> list[str]:
    suffix = f"_{int(horizon)}d"
    return [
        f"future_return_q10{suffix}", f"future_equal_weight_return{suffix}",
        f"future_median_return{suffix}",
        f"future_stock_win_rate{suffix}", f"future_large_decline_ratio{suffix}",
        f"future_median_max_drawdown{suffix}", f"future_terminal_drawdown{suffix}",
        f"future_recovery_ratio{suffix}", f"future_negative_breadth_days{suffix}",
    ]
