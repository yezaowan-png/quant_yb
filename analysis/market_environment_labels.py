"""Cross-sectional future market-environment targets.

The target is deliberately based on the distribution of future A-share returns,
not on a single capitalization-weighted index.  Every rolling percentile uses
only target observations whose full forward window had completed by the score
date, so the label construction does not leak unfinished future outcomes into
historical thresholds.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd


ENVIRONMENT_HORIZONS = (1, 5, 10, 20)
ENVIRONMENT_LABELS = ("positive", "neutral", "conservative")
ENVIRONMENT_LABEL_TEXT = {
    "positive": "积极",
    "neutral": "中性",
    "conservative": "保守",
}


def load_stock_close_matrix(
    cache_dir: str | Path,
    dates: Iterable[Any] | None = None,
    symbols: set[str] | list[str] | None = None,
) -> pd.DataFrame:
    """Load local stock caches into a date-by-symbol close matrix."""
    root = Path(cache_dir)
    if not root.exists():
        return pd.DataFrame()
    wanted = {str(item).upper() for item in symbols} if symbols else None
    series: list[pd.Series] = []
    for path in sorted(root.glob("*.csv")):
        if path.name.startswith("_"):
            continue
        symbol = path.stem.upper()
        if wanted is not None and symbol not in wanted:
            continue
        try:
            frame = pd.read_csv(path, usecols=["date", "close"], dtype={"date": str})
        except Exception:
            continue
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame = frame.dropna(subset=["date", "close"]).drop_duplicates("date", keep="last")
        if frame.empty:
            continue
        series.append(frame.set_index("date")["close"].rename(symbol))
    if not series:
        return pd.DataFrame()
    matrix = pd.concat(series, axis=1).sort_index()
    if dates is not None:
        index = pd.DatetimeIndex(pd.to_datetime(list(dates), errors="coerce")).dropna().unique().sort_values()
        matrix = matrix.reindex(index)
    return matrix


def build_current_cross_section_features(
    close_matrix: pd.DataFrame,
    index_close: pd.Series | None = None,
    large_cap_symbols: set[str] | list[str] | None = None,
    small_cap_symbols: set[str] | list[str] | None = None,
    large_cap_index_close: pd.Series | None = None,
    small_cap_index_close: pd.Series | None = None,
    large_decline_threshold: float = -0.05,
) -> pd.DataFrame:
    """Build predictor features observable at each date from stock closes."""
    if close_matrix.empty:
        return pd.DataFrame(columns=["trade_date"])
    closes = close_matrix.apply(pd.to_numeric, errors="coerce").sort_index()
    daily = closes.pct_change(fill_method=None)
    result = pd.DataFrame(index=closes.index)
    result["equal_weight_market_return_1d"] = daily.mean(axis=1, skipna=True)
    result["stock_up_ratio"] = (daily > 0).sum(axis=1) / daily.notna().sum(axis=1).replace(0, np.nan)
    result["market_large_decline_ratio_1d"] = (
        (daily <= float(large_decline_threshold)).sum(axis=1)
        / daily.notna().sum(axis=1).replace(0, np.nan)
    )
    result["cross_section_volatility_20d"] = result["equal_weight_market_return_1d"].rolling(
        20, min_periods=10
    ).std() * np.sqrt(252.0)
    for window in (20, 50, 200):
        ma = closes.rolling(window, min_periods=window).mean()
        valid = closes.notna() & ma.notna()
        result[f"stocks_above_ma{window}_ratio"] = ((closes > ma) & valid).sum(axis=1) / valid.sum(axis=1).replace(0, np.nan)
    if index_close is not None:
        index_series = pd.to_numeric(index_close, errors="coerce").reindex(result.index)
        result["index_equal_weight_gap_1d"] = index_series.pct_change(fill_method=None) - result[
            "equal_weight_market_return_1d"
        ]
        for window in (5, 10, 20):
            equal_return = (closes / closes.shift(window) - 1.0).mean(axis=1, skipna=True)
            result[f"equal_weight_market_return_{window}d"] = equal_return
            result[f"index_equal_weight_gap_{window}d"] = (
                index_series / index_series.shift(window) - 1.0 - equal_return
            )

    def _group_return(symbols: set[str] | list[str] | None) -> pd.Series:
        selected = sorted(set(closes.columns) & {str(item).upper() for item in (symbols or [])})
        return daily[selected].mean(axis=1, skipna=True) if selected else pd.Series(np.nan, index=result.index)

    if large_cap_index_close is not None:
        result["large_cap_return_1d"] = pd.to_numeric(
            large_cap_index_close, errors="coerce"
        ).reindex(result.index).pct_change(fill_method=None)
    else:
        result["large_cap_return_1d"] = _group_return(large_cap_symbols)
    if small_cap_index_close is not None:
        result["small_cap_return_1d"] = pd.to_numeric(
            small_cap_index_close, errors="coerce"
        ).reindex(result.index).pct_change(fill_method=None)
    else:
        result["small_cap_return_1d"] = _group_return(small_cap_symbols)
    result["large_small_relative_strength_1d"] = result["large_cap_return_1d"] - result["small_cap_return_1d"]
    for window in (5, 10, 20):
        large = (1.0 + result["large_cap_return_1d"]).rolling(window, min_periods=window).apply(np.prod, raw=True) - 1.0
        small = (1.0 + result["small_cap_return_1d"]).rolling(window, min_periods=window).apply(np.prod, raw=True) - 1.0
        result[f"large_small_relative_strength_{window}d"] = large - small
    result["trade_date"] = result.index.strftime("%Y-%m-%d")
    return result.reset_index(drop=True)


def _future_path_drawdown(values: np.ndarray) -> np.ndarray:
    output = np.full(values.shape[1], np.nan, dtype="float64")
    valid = np.isfinite(values).all(axis=0)
    if not valid.any():
        return output
    complete = values[:, valid]
    running_max = np.maximum.accumulate(complete, axis=0)
    output[valid] = np.min(complete / running_max - 1.0, axis=0)
    return output


def _expanding_percentile(
    values: pd.Series,
    horizon: int,
    window: int = 756,
    min_periods: int = 60,
    higher_is_better: bool = True,
) -> pd.Series:
    """Score values against only forward outcomes completed by that date."""
    numeric = pd.to_numeric(values, errors="coerce")
    scored = pd.Series(np.nan, index=numeric.index, dtype="float64")
    completed = numeric.shift(int(horizon))
    for position, current in enumerate(numeric.to_numpy(dtype="float64")):
        if not np.isfinite(current):
            continue
        start = max(0, position - int(window) + 1)
        history = completed.iloc[start : position + 1].dropna().to_numpy(dtype="float64")
        if len(history) < int(min_periods):
            continue
        percentile = 100.0 * float(np.mean(history <= current))
        scored.iloc[position] = percentile if higher_is_better else 100.0 - percentile
    return scored


def _divergence_label(index_return: float, equal_return: float, win_rate: float) -> str | None:
    if not all(np.isfinite(value) for value in (index_return, equal_return, win_rate)):
        return None
    if index_return > 0 and equal_return <= 0 and win_rate < 0.5:
        return "index_only_rally"
    if index_return < 0 and equal_return >= 0 and win_rate > 0.5:
        return "breadth_stronger_than_index"
    if index_return > 0 and equal_return > 0 and win_rate >= 0.5:
        return "broad_market_rally"
    if index_return < 0 and equal_return < 0 and win_rate <= 0.5:
        return "broad_market_decline"
    return "mixed_market"


def _environment_label(environment_score: float, risk_score: float) -> str | None:
    if not np.isfinite(environment_score) or not np.isfinite(risk_score):
        return None
    if risk_score >= 80.0 or environment_score <= 40.0:
        return "conservative"
    if environment_score >= 65.0 and risk_score < 70.0:
        return "positive"
    return "neutral"


def build_market_environment_targets(
    index_df: pd.DataFrame,
    close_matrix: pd.DataFrame,
    horizons: tuple[int, ...] = ENVIRONMENT_HORIZONS,
    large_decline_threshold: float = -0.05,
    percentile_window: int = 756,
    percentile_min_periods: int = 60,
) -> pd.DataFrame:
    """Build future cross-sectional outcomes, scores, labels and divergence tags."""
    if close_matrix.empty:
        raise ValueError("市场环境标签需要本地个股收盘价矩阵")
    if "date" not in index_df.columns or "close" not in index_df.columns:
        raise ValueError("指数数据缺少 date/close 字段")
    index = index_df[["date", "close"]].copy()
    index["date"] = pd.to_datetime(index["date"], errors="coerce")
    index["close"] = pd.to_numeric(index["close"], errors="coerce")
    index = index.dropna().drop_duplicates("date", keep="last").sort_values("date").set_index("date")
    closes = close_matrix.apply(pd.to_numeric, errors="coerce").reindex(index.index)
    daily_returns = closes.pct_change(fill_method=None)
    result = pd.DataFrame(index=index.index)
    result["trade_date"] = result.index.strftime("%Y-%m-%d")

    for raw_horizon in horizons:
        horizon = int(raw_horizon)
        if horizon <= 0:
            raise ValueError("预测周期必须为正整数")
        suffix = f"_{horizon}d"
        stock_returns = closes.shift(-horizon) / closes - 1.0
        valid_count = stock_returns.notna().sum(axis=1)
        result[f"effective_stock_count{suffix}"] = valid_count
        result[f"market_cap_index_return{suffix}"] = index["close"].shift(-horizon) / index["close"] - 1.0
        result[f"equal_weight_return{suffix}"] = stock_returns.mean(axis=1, skipna=True)
        result[f"median_stock_return{suffix}"] = stock_returns.median(axis=1, skipna=True)
        result[f"stock_win_rate{suffix}"] = (stock_returns > 0).sum(axis=1) / valid_count.replace(0, np.nan)
        result[f"return_q10{suffix}"] = stock_returns.quantile(0.10, axis=1)
        result[f"large_decline_ratio{suffix}"] = (
            (stock_returns <= float(large_decline_threshold)).sum(axis=1) / valid_count.replace(0, np.nan)
        )

        future_ad = pd.Series(np.nan, index=result.index, dtype="float64")
        future_vol = pd.Series(np.nan, index=result.index, dtype="float64")
        future_drawdown = pd.Series(np.nan, index=result.index, dtype="float64")
        for position in range(len(result) - horizon):
            path_daily = daily_returns.iloc[position + 1 : position + horizon + 1]
            up = (path_daily > 0).sum(axis=1)
            down = (path_daily < 0).sum(axis=1)
            future_ad.iloc[position] = ((up - down) / (up + down).replace(0, np.nan)).sum(min_count=1)
            ew_daily = path_daily.mean(axis=1, skipna=True)
            if horizon > 1:
                future_vol.iloc[position] = ew_daily.std(ddof=0) * np.sqrt(252.0)
            else:
                cross_section_day = path_daily.iloc[0].dropna()
                future_vol.iloc[position] = (
                    cross_section_day.std(ddof=0) * np.sqrt(252.0) if len(cross_section_day) else np.nan
                )
            path = closes.iloc[position : position + horizon + 1].to_numpy(dtype="float64")
            if path.shape[0] == horizon + 1:
                drawdowns = _future_path_drawdown(path)
                future_drawdown.iloc[position] = float(np.nanmedian(drawdowns)) if np.isfinite(drawdowns).any() else np.nan
        result[f"future_breadth{suffix}"] = future_ad
        result[f"median_max_drawdown{suffix}"] = future_drawdown
        result[f"volatility{suffix}"] = future_vol

        score_specs = {
            "median_stock_return_score": (f"median_stock_return{suffix}", True),
            "equal_weight_return_score": (f"equal_weight_return{suffix}", True),
            "stock_win_rate_score": (f"stock_win_rate{suffix}", True),
            "future_breadth_score": (f"future_breadth{suffix}", True),
            "downside_quantile_score": (f"return_q10{suffix}", False),
            "max_drawdown_score": (f"median_max_drawdown{suffix}", False),
            "volatility_score": (f"volatility{suffix}", True),
            "large_decline_ratio_score": (f"large_decline_ratio{suffix}", True),
            "negative_breadth_score": (f"future_breadth{suffix}", False),
        }
        for score_name, (source, high_value_means_high_score) in score_specs.items():
            result[f"{score_name}{suffix}"] = _expanding_percentile(
                result[source],
                horizon,
                percentile_window,
                percentile_min_periods,
                higher_is_better=high_value_means_high_score,
            )

        result[f"opportunity_score{suffix}"] = (
            0.35 * result[f"median_stock_return_score{suffix}"]
            + 0.25 * result[f"equal_weight_return_score{suffix}"]
            + 0.20 * result[f"stock_win_rate_score{suffix}"]
            + 0.20 * result[f"future_breadth_score{suffix}"]
        )
        result[f"risk_score{suffix}"] = (
            0.30 * result[f"downside_quantile_score{suffix}"]
            + 0.25 * result[f"max_drawdown_score{suffix}"]
            + 0.20 * result[f"volatility_score{suffix}"]
            + 0.15 * result[f"large_decline_ratio_score{suffix}"]
            + 0.10 * result[f"negative_breadth_score{suffix}"]
        )
        result[f"environment_score{suffix}"] = (
            0.70 * result[f"opportunity_score{suffix}"] + 0.30 * (100.0 - result[f"risk_score{suffix}"])
        )
        result[f"environment_label{suffix}"] = [
            _environment_label(score, risk)
            for score, risk in zip(result[f"environment_score{suffix}"], result[f"risk_score{suffix}"])
        ]
        result[f"index_breadth_gap{suffix}"] = (
            result[f"market_cap_index_return{suffix}"] - result[f"equal_weight_return{suffix}"]
        )
        result[f"divergence_label{suffix}"] = [
            _divergence_label(index_ret, equal_ret, win_rate)
            for index_ret, equal_ret, win_rate in zip(
                result[f"market_cap_index_return{suffix}"],
                result[f"equal_weight_return{suffix}"],
                result[f"stock_win_rate{suffix}"],
            )
        ]
    return result.reset_index(drop=True)


def attach_environment_targets(indicators: pd.DataFrame, targets: pd.DataFrame) -> pd.DataFrame:
    """Attach target columns to an observable indicator frame by trade date."""
    if targets.empty:
        return indicators.copy()
    return indicators.merge(targets, on="trade_date", how="left", validate="one_to_one")


def environment_evaluation(
    frame: pd.DataFrame,
    horizon: int,
    predicted_col: str = "signal",
    strategy_returns: Mapping[str, pd.Series] | None = None,
) -> dict[str, Any]:
    """Evaluate predicted environments on cross-sectional outcomes and strategies."""
    suffix = f"_{int(horizon)}d"
    actual_col = f"environment_label{suffix}"
    required = [predicted_col, actual_col, f"median_stock_return{suffix}", f"equal_weight_return{suffix}"]
    evaluated = frame.dropna(subset=[col for col in required if col in frame.columns]).copy()
    rows: list[dict[str, Any]] = []
    forward_strategy: dict[str, pd.Series] = {}
    if strategy_returns:
        dates = frame["trade_date"].astype(str)
        for name, values in strategy_returns.items():
            series = pd.to_numeric(values, errors="coerce").copy()
            series.index = pd.to_datetime(series.index, errors="coerce").strftime("%Y-%m-%d")
            daily = series.reindex(dates).reset_index(drop=True)
            forward_strategy[str(name)] = (
                (1.0 + daily.shift(-1)).rolling(int(horizon), min_periods=int(horizon)).apply(np.prod, raw=True).shift(-(int(horizon) - 1)) - 1.0
            )
            forward_strategy[str(name)].index = frame.index
    for label in ENVIRONMENT_LABELS:
        group = evaluated[evaluated[predicted_col] == label]
        rows.append(
            {
                "label": label,
                "count": int(len(group)),
                "median_stock_return": _mean(group.get(f"median_stock_return{suffix}")),
                "equal_weight_return": _mean(group.get(f"equal_weight_return{suffix}")),
                "stock_win_rate": _mean(group.get(f"stock_win_rate{suffix}")),
                "tail_loss_q10": _mean(group.get(f"return_q10{suffix}")),
                "median_max_drawdown": _mean(group.get(f"median_max_drawdown{suffix}")),
                "hit_rate": float((group[predicted_col] == group[actual_col]).mean()) if len(group) else None,
                "strategy_returns": {
                    name: _mean(values.reindex(group.index)) for name, values in forward_strategy.items()
                },
            }
        )
    output: dict[str, Any] = {
        "sample_count": int(len(evaluated)),
        "accuracy": float((evaluated[predicted_col] == evaluated[actual_col]).mean()) if len(evaluated) else None,
        "label_summary": rows,
    }
    if strategy_returns:
        output["strategy_filter_comparison"] = _strategy_filter_comparison(
            frame, strategy_returns, predicted_col=predicted_col
        )
    return output


def _mean(values: pd.Series | None) -> float | None:
    if values is None:
        return None
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return float(numeric.mean()) if len(numeric) else None


def _strategy_filter_comparison(
    frame: pd.DataFrame,
    strategy_returns: Mapping[str, pd.Series],
    predicted_col: str = "signal",
) -> list[dict[str, Any]]:
    labels = frame.set_index("trade_date")[predicted_col]
    rows: list[dict[str, Any]] = []
    for name, values in strategy_returns.items():
        returns = pd.to_numeric(values, errors="coerce").copy()
        returns.index = pd.to_datetime(returns.index, errors="coerce").strftime("%Y-%m-%d")
        aligned = returns.reindex(labels.index).fillna(0.0)
        exposure = labels.map({"positive": 1.0, "neutral": 0.5, "conservative": 0.0}).fillna(0.5).shift(1).fillna(0.0)
        filtered = aligned * exposure
        before = _return_stats(aligned)
        after = _return_stats(filtered)
        transitions = (labels.shift(1) == "positive") & (labels == "conservative")
        transition_before_dd = []
        transition_after_dd = []
        for pos in np.flatnonzero(transitions.to_numpy()):
            before_path = (1.0 + aligned.iloc[pos : pos + 21]).cumprod()
            after_path = (1.0 + filtered.iloc[pos : pos + 21]).cumprod()
            if len(before_path):
                transition_before_dd.append(float((before_path / before_path.cummax() - 1.0).min()))
                transition_after_dd.append(float((after_path / after_path.cummax() - 1.0).min()))
        transition_before = float(np.mean(transition_before_dd)) if transition_before_dd else None
        transition_after = float(np.mean(transition_after_dd)) if transition_after_dd else None
        rows.append({
            "strategy": str(name),
            "before": before,
            "after": after,
            "positive_to_conservative_before_avg_20d_drawdown": transition_before,
            "positive_to_conservative_after_avg_20d_drawdown": transition_after,
            "positive_to_conservative_drawdown_change": (
                transition_after - transition_before
                if transition_before is not None and transition_after is not None
                else None
            ),
        })
    return rows


def load_strategy_daily_returns(trades_dir: str | Path) -> dict[str, pd.Series]:
    """Aggregate existing per-symbol equity CSVs into daily strategy returns."""
    root = Path(trades_dir)
    grouped: dict[str, list[pd.Series]] = {}
    if not root.exists():
        return {}
    for path in sorted(root.glob("*_equity.csv")):
        stem = path.stem.removesuffix("_equity")
        if "_" not in stem or stem.startswith("_"):
            continue
        _, strategy = stem.split("_", 1)
        try:
            frame = pd.read_csv(path)
        except Exception:
            continue
        date_col = "dates" if "dates" in frame.columns else "date" if "date" in frame.columns else None
        equity_col = "equity" if "equity" in frame.columns else None
        if not date_col or not equity_col:
            continue
        dates = pd.to_datetime(frame[date_col], errors="coerce")
        equity = pd.to_numeric(frame[equity_col], errors="coerce")
        series = pd.Series(equity.to_numpy(), index=dates).dropna().sort_index().pct_change(fill_method=None)
        if series.notna().any():
            grouped.setdefault(strategy, []).append(series.rename(path.name))
    return {
        strategy: pd.concat(items, axis=1).mean(axis=1, skipna=True)
        for strategy, items in grouped.items()
        if items
    }


def _return_stats(returns: pd.Series) -> dict[str, float | None]:
    values = pd.to_numeric(returns, errors="coerce").dropna()
    if values.empty:
        return {"return": None, "win_rate": None, "max_drawdown": None, "payoff_ratio": None}
    equity = (1.0 + values).cumprod()
    gains = values[values > 0]
    losses = values[values < 0]
    payoff = float(gains.mean() / abs(losses.mean())) if len(gains) and len(losses) else None
    return {
        "return": float(equity.iloc[-1] - 1.0),
        "win_rate": float((values > 0).mean()),
        "max_drawdown": float((equity / equity.cummax() - 1.0).min()),
        "payoff_ratio": payoff,
    }
