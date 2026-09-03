"""P0 diagnostics and low-complexity walk-forward baselines for market environment forecasts."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd


P0_FEATURES = (
    "ret_5d",
    "ret_20d",
    "dist_ma20",
    "dist_ma60",
    "ma20_slope_5",
    "macd_hist_norm",
    "normalized_ad",
    "ad_line_slope_5",
    "ad_line_slope_20",
    "normalized_nhnl",
    "nhnl_line_slope_5",
    "nhnl_line_slope_20",
    "stocks_above_ma20_ratio",
    "stocks_above_ma200_ratio",
    "cross_section_volatility_20d",
    "market_large_decline_ratio_1d",
    "index_equal_weight_gap_5d",
    "large_small_relative_strength_10d",
    "ad_level_x_slope",
    "nhnl_level_x_slope",
    "ret5_x_volatility",
    "large_decline_x_ad_slope",
)

P0_FEATURE_GROUPS = {
    "trend": ("ret_5d", "ret_20d", "dist_ma20", "dist_ma60", "ma20_slope_5", "macd_hist_norm"),
    "breadth": (
        "normalized_ad", "ad_line_slope_5", "ad_line_slope_20", "normalized_nhnl",
        "nhnl_line_slope_5", "nhnl_line_slope_20", "stocks_above_ma20_ratio",
        "stocks_above_ma200_ratio", "ad_level_x_slope", "nhnl_level_x_slope",
    ),
    "risk_structure": (
        "cross_section_volatility_20d", "market_large_decline_ratio_1d",
        "index_equal_weight_gap_5d", "large_small_relative_strength_10d",
        "ret5_x_volatility", "large_decline_x_ad_slope",
    ),
}

TARGET_PREFIXES = (
    "fwd_ret_",
    "threshold_",
    "label_",
    "environment_label_",
    "market_cap_index_return_",
    "equal_weight_return_",
    "median_stock_return_",
    "stock_win_rate_",
    "future_breadth_",
    "return_q10_",
    "median_max_drawdown_",
    "volatility_",
    "large_decline_ratio_",
    "opportunity_score_",
    "risk_score_",
    "environment_score_",
    "index_breadth_gap_",
    "divergence_label_",
    "median_stock_return_score_",
    "equal_weight_return_score_",
    "stock_win_rate_score_",
    "future_breadth_score_",
    "downside_quantile_score_",
    "max_drawdown_score_",
    "volatility_score_",
    "large_decline_ratio_score_",
    "negative_breadth_score_",
    "rank_lower_",
    "rank_upper_",
)

EXCLUDED_EXACT = {
    "date",
    "trade_date",
    "symbol",
    "model",
    "signal",
    "environment_signal",
    "p_bull",
    "p_neutral",
    "p_bear",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "ad_norm_line",
    "all_a_ad_line",
}


def is_target_or_leakage_column(column: str) -> bool:
    """Return whether a column must be excluded from predictor diagnostics/models."""
    name = str(column)
    return name in EXCLUDED_EXACT or name.startswith(TARGET_PREFIXES)


def available_p0_features(frame: pd.DataFrame) -> list[str]:
    """Return the fixed, auditable P0 predictor whitelist available in a frame."""
    return [name for name in P0_FEATURES if name in frame.columns and not is_target_or_leakage_column(name)]


def add_p0_interactions(frame: pd.DataFrame) -> pd.DataFrame:
    """Add only the economically motivated interactions declared by the P0 plan."""
    out = frame.copy()
    def numeric(name: str) -> pd.Series:
        return pd.to_numeric(out.get(name), errors="coerce")
    out["ad_level_x_slope"] = numeric("normalized_ad") * numeric("ad_line_slope_5")
    out["nhnl_level_x_slope"] = numeric("normalized_nhnl") * numeric("nhnl_line_slope_5")
    out["ret5_x_volatility"] = numeric("ret_5d") * numeric("cross_section_volatility_20d")
    out["large_decline_x_ad_slope"] = numeric("market_large_decline_ratio_1d") * numeric("ad_line_slope_5")
    return out


def _record(value: Any, digits: int = 6) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def _observable_percentile(series: pd.Series, window: int = 756, min_periods: int = 60) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    output = pd.Series(np.nan, index=series.index, dtype="float64")
    for position, value in enumerate(numeric.to_numpy(dtype="float64")):
        if not np.isfinite(value):
            continue
        history = numeric.iloc[max(0, position - window + 1) : position + 1].dropna().to_numpy()
        if len(history) < min_periods:
            continue
        output.iloc[position] = float(np.mean(history <= value))
    return output


def build_breadth_level_slope_events(frame: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Describe weak/improving versus weak/deteriorating breadth states."""
    suffix = f"_{int(horizon)}d"
    specs = (
        ("ad", "normalized_ad", "ad_line_slope_5"),
        ("nhnl", "normalized_nhnl", "nhnl_line_slope_5"),
    )
    rows: list[dict[str, Any]] = []
    for indicator, level_col, slope_col in specs:
        if level_col not in frame.columns or slope_col not in frame.columns:
            continue
        level_rank = _observable_percentile(frame[level_col])
        level = pd.Series("middle", index=frame.index, dtype=object)
        level[level_rank <= 0.20] = "very_low"
        level[level_rank >= 0.80] = "very_high"
        slope = pd.to_numeric(frame[slope_col], errors="coerce")
        direction = pd.Series(np.where(slope >= 0, "improving", "deteriorating"), index=frame.index)
        work = frame.copy()
        work["_level"] = level
        work["_direction"] = direction
        work = work[level_rank.notna() & slope.notna()]
        for (level_name, direction_name), group in work.groupby(["_level", "_direction"], dropna=False):
            rows.append(
                {
                    "indicator": indicator,
                    "level": str(level_name),
                    "direction": str(direction_name),
                    "count": int(len(group)),
                    "median_stock_return": _record(pd.to_numeric(group.get(f"median_stock_return{suffix}"), errors="coerce").mean()),
                    "equal_weight_return": _record(pd.to_numeric(group.get(f"equal_weight_return{suffix}"), errors="coerce").mean()),
                    "stock_win_rate": _record(pd.to_numeric(group.get(f"stock_win_rate{suffix}"), errors="coerce").mean(), 4),
                    "return_q10": _record(pd.to_numeric(group.get(f"return_q10{suffix}"), errors="coerce").mean()),
                }
            )
    return pd.DataFrame(rows)


def _sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _fit_logistic(
    x: np.ndarray,
    y: np.ndarray,
    l2: float = 1.0,
    learning_rate: float = 0.08,
    iterations: int = 1200,
) -> np.ndarray:
    """Fit a small class-balanced L2 logistic model with deterministic NumPy GD."""
    weights = np.zeros(x.shape[1] + 1, dtype="float64")
    positives = max(float((y == 1).sum()), 1.0)
    negatives = max(float((y == 0).sum()), 1.0)
    sample_weights = np.where(y == 1, len(y) / (2.0 * positives), len(y) / (2.0 * negatives))
    design = np.column_stack([np.ones(len(x)), x])
    for _ in range(iterations):
        probabilities = _sigmoid(design @ weights)
        gradient = design.T @ ((probabilities - y) * sample_weights) / len(y)
        gradient[1:] += l2 * weights[1:] / len(y)
        weights -= learning_rate * gradient
    return weights


def _auc(y: np.ndarray, probability: np.ndarray) -> float | None:
    positives = int((y == 1).sum())
    negatives = int((y == 0).sum())
    if not positives or not negatives:
        return None
    ranks = pd.Series(probability).rank(method="average").to_numpy()
    value = (ranks[y == 1].sum() - positives * (positives + 1) / 2.0) / (positives * negatives)
    return float(value)


def _prepare_train_test(
    frame: pd.DataFrame,
    features: list[str],
    train_index: np.ndarray,
    test_index: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    train = frame.iloc[train_index][features].apply(pd.to_numeric, errors="coerce")
    test = frame.iloc[test_index][features].apply(pd.to_numeric, errors="coerce")
    train = train.replace([np.inf, -np.inf], np.nan)
    test = test.replace([np.inf, -np.inf], np.nan)
    medians = train.median().fillna(0.0)
    train = train.fillna(medians)
    test = test.fillna(medians)
    lower = train.quantile(0.01)
    upper = train.quantile(0.99)
    train = train.clip(lower=lower, upper=upper, axis=1)
    test = test.clip(lower=lower, upper=upper, axis=1)
    means = train.mean()
    stds = train.std(ddof=0).replace(0, 1.0).fillna(1.0)
    return (
        ((train - means) / stds).to_numpy(dtype="float64"),
        ((test - means) / stds).to_numpy(dtype="float64"),
        means.to_numpy(dtype="float64"),
        stds.to_numpy(dtype="float64"),
    )


def build_purged_walk_forward_baseline(
    frame: pd.DataFrame,
    horizon: int,
    initial_train: int = 252,
    test_size: int = 63,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Run expanding-window dual logistic baselines with a horizon purge."""
    suffix = f"_{int(horizon)}d"
    features = available_p0_features(frame)
    required = [
        "trade_date",
        f"median_stock_return_score{suffix}",
        f"stock_win_rate_score{suffix}",
        f"downside_quantile_score{suffix}",
        f"max_drawdown_score{suffix}",
        f"large_decline_ratio_score{suffix}",
        f"equal_weight_return{suffix}",
        f"return_q10{suffix}",
    ]
    if len(features) < 5 or any(name not in frame.columns for name in required):
        return pd.DataFrame(), pd.DataFrame(), features
    work = frame.dropna(subset=required).sort_values("trade_date").reset_index(drop=True).copy()
    work["_opportunity_score"] = (
        0.60 * pd.to_numeric(work[f"median_stock_return_score{suffix}"], errors="coerce")
        + 0.40 * pd.to_numeric(work[f"stock_win_rate_score{suffix}"], errors="coerce")
    )
    work["_risk_score"] = (
        0.45 * pd.to_numeric(work[f"downside_quantile_score{suffix}"], errors="coerce")
        + 0.35 * pd.to_numeric(work[f"max_drawdown_score{suffix}"], errors="coerce")
        + 0.20 * pd.to_numeric(work[f"large_decline_ratio_score{suffix}"], errors="coerce")
    )
    work["_opportunity_target"] = (work["_opportunity_score"] >= 70.0).astype(int)
    work["_risk_target"] = (work["_risk_score"] >= 70.0).astype(int)

    fold_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []
    fold = 0
    test_start = int(initial_train) + int(horizon)
    while test_start < len(work):
        test_end = min(test_start + int(test_size), len(work))
        train_end = test_start - int(horizon)
        if train_end < int(initial_train):
            test_start += int(test_size)
            continue
        train_index = np.arange(0, train_end)
        test_index = np.arange(test_start, test_end)
        x_train, x_test, _, _ = _prepare_train_test(work, features, train_index, test_index)
        opportunity_train = work.iloc[train_index]["_opportunity_target"].to_numpy(dtype="float64")
        risk_train = work.iloc[train_index]["_risk_target"].to_numpy(dtype="float64")
        if len(np.unique(opportunity_train)) < 2 or len(np.unique(risk_train)) < 2:
            test_start += int(test_size)
            continue
        opportunity_weights = _fit_logistic(x_train, opportunity_train)
        risk_weights = _fit_logistic(x_train, risk_train)
        design = np.column_stack([np.ones(len(x_test)), x_test])
        opportunity_probability = _sigmoid(design @ opportunity_weights)
        risk_probability = _sigmoid(design @ risk_weights)
        opportunity_actual = work.iloc[test_index]["_opportunity_target"].to_numpy(dtype=int)
        risk_actual = work.iloc[test_index]["_risk_target"].to_numpy(dtype=int)
        future_return = pd.to_numeric(work.iloc[test_index][f"equal_weight_return{suffix}"], errors="coerce").to_numpy()
        future_q10 = pd.to_numeric(work.iloc[test_index][f"return_q10{suffix}"], errors="coerce").to_numpy()
        fold += 1
        fold_rows.append(
            {
                "fold": fold,
                "train_start": str(work.iloc[0]["trade_date"]),
                "train_end": str(work.iloc[train_end - 1]["trade_date"]),
                "test_start": str(work.iloc[test_start]["trade_date"]),
                "test_end": str(work.iloc[test_end - 1]["trade_date"]),
                "train_count": int(len(train_index)),
                "test_count": int(len(test_index)),
                "purge_days": int(horizon),
                "opportunity_auc": _record(_auc(opportunity_actual, opportunity_probability), 4),
                "risk_auc": _record(_auc(risk_actual, risk_probability), 4),
                "opportunity_rank_ic": _record(pd.Series(opportunity_probability).rank().corr(pd.Series(future_return).rank()), 4),
                "high_minus_low_return": _record(
                    np.nanmean(future_return[opportunity_probability >= 0.70])
                    - np.nanmean(future_return[opportunity_probability <= 0.30])
                    if (opportunity_probability >= 0.70).any() and (opportunity_probability <= 0.30).any()
                    else None
                ),
                "high_minus_low_risk_q10": _record(
                    np.nanmean(future_q10[risk_probability >= 0.70])
                    - np.nanmean(future_q10[risk_probability <= 0.30])
                    if (risk_probability >= 0.70).any() and (risk_probability <= 0.30).any()
                    else None
                ),
            }
        )
        for position, probability_opp, probability_risk, actual_opp, actual_risk in zip(
            test_index,
            opportunity_probability,
            risk_probability,
            opportunity_actual,
            risk_actual,
        ):
            signal = (
                "positive"
                if probability_opp >= 0.60 and probability_risk < 0.50
                else "conservative"
                if probability_risk >= 0.60 or probability_opp < 0.40
                else "neutral"
            )
            prediction_rows.append(
                {
                    "trade_date": str(work.iloc[position]["trade_date"]),
                    "fold": fold,
                    "opportunity_probability": _record(probability_opp),
                    "risk_probability": _record(probability_risk),
                    "opportunity_actual": int(actual_opp),
                    "risk_actual": int(actual_risk),
                    "environment_signal": signal,
                    f"equal_weight_return{suffix}": _record(work.iloc[position][f"equal_weight_return{suffix}"]),
                    f"return_q10{suffix}": _record(work.iloc[position][f"return_q10{suffix}"]),
                }
            )
        test_start += int(test_size)
    return pd.DataFrame(fold_rows), pd.DataFrame(prediction_rows), features


def _empirical_percentile(reference: np.ndarray, values: np.ndarray, higher_is_better: bool = True) -> np.ndarray:
    reference = np.sort(reference[np.isfinite(reference)])
    result = np.full(len(values), np.nan, dtype="float64")
    valid = np.isfinite(values)
    if not len(reference):
        return result
    result[valid] = np.searchsorted(reference, values[valid], side="right") / len(reference) * 100.0
    return result if higher_is_better else 100.0 - result


def _fold_targets(work: pd.DataFrame, train_index: np.ndarray, apply_index: np.ndarray, suffix: str) -> dict[str, np.ndarray]:
    """Build transparent A/B/C labels using train-only empirical distributions."""
    specs = {
        "median": (f"median_stock_return{suffix}", True),
        "win_rate": (f"stock_win_rate{suffix}", True),
        "q10": (f"return_q10{suffix}", False),
        "drawdown": (f"median_max_drawdown{suffix}", False),
        "large_decline": (f"large_decline_ratio{suffix}", True),
    }
    scores: dict[str, np.ndarray] = {}
    for name, (column, higher) in specs.items():
        train_values = pd.to_numeric(work.iloc[train_index][column], errors="coerce").to_numpy(dtype="float64")
        apply_values = pd.to_numeric(work.iloc[apply_index][column], errors="coerce").to_numpy(dtype="float64")
        scores[name] = _empirical_percentile(train_values, apply_values, higher)
    opportunity = 0.60 * scores["median"] + 0.40 * scores["win_rate"]
    risk = 0.45 * scores["q10"] + 0.35 * scores["drawdown"] + 0.20 * scores["large_decline"]
    return {
        "opportunity_score": opportunity,
        "risk_score": risk,
        "opportunity_target": (opportunity >= 70.0).astype(int),
        "risk_target": (risk >= 70.0).astype(int),
        "label_a_median": (scores["median"] >= 70.0).astype(int),
        "label_b_win_rate": (scores["win_rate"] >= 70.0).astype(int),
        "label_c_downside": (0.55 * scores["q10"] + 0.45 * scores["drawdown"] >= 70.0).astype(int),
        "opportunity_50_50": (0.50 * scores["median"] + 0.50 * scores["win_rate"] >= 70.0).astype(int),
        "opportunity_70_30": (0.70 * scores["median"] + 0.30 * scores["win_rate"] >= 70.0).astype(int),
        "risk_40_40_20": (0.40 * scores["q10"] + 0.40 * scores["drawdown"] + 0.20 * scores["large_decline"] >= 70.0).astype(int),
        "risk_50_30_20": (0.50 * scores["q10"] + 0.30 * scores["drawdown"] + 0.20 * scores["large_decline"] >= 70.0).astype(int),
    }


def _binary_metrics(actual: np.ndarray, probability: np.ndarray) -> dict[str, float | None]:
    probability = np.clip(np.asarray(probability, dtype="float64"), 1e-6, 1.0 - 1e-6)
    actual = np.asarray(actual, dtype=int)
    prior = np.full(len(actual), float(actual.mean()) if len(actual) else 0.5)
    brier = float(np.mean((probability - actual) ** 2)) if len(actual) else np.nan
    prior_brier = float(np.mean((prior - actual) ** 2)) if len(actual) else np.nan
    log_loss = float(-np.mean(actual * np.log(probability) + (1 - actual) * np.log(1 - probability)))
    prior_log_loss = float(-np.mean(actual * np.log(np.clip(prior, 1e-6, 1 - 1e-6)) + (1 - actual) * np.log(np.clip(1 - prior, 1e-6, 1 - 1e-6))))
    bins = np.minimum((probability * 5).astype(int), 4)
    ece = 0.0
    for bucket in range(5):
        mask = bins == bucket
        if mask.any():
            ece += mask.mean() * abs(float(probability[mask].mean()) - float(actual[mask].mean()))
    return {
        "auc": _record(_auc(actual, probability), 4),
        "brier": _record(brier, 6),
        "brier_skill": _record(1.0 - brier / prior_brier, 4) if prior_brier > 0 else None,
        "log_loss": _record(log_loss, 6),
        "log_loss_improvement": _record(1.0 - log_loss / prior_log_loss, 4) if prior_log_loss > 0 else None,
        "ece": _record(ece, 4),
    }


def _platt_fit_apply(
    validation_probability: np.ndarray,
    validation_actual: np.ndarray,
    test_probability: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Fit Platt scaling on validation only and apply the frozen map to test."""
    validation_probability = np.clip(validation_probability, 1e-6, 1 - 1e-6)
    test_probability = np.clip(test_probability, 1e-6, 1 - 1e-6)
    if len(np.unique(validation_actual)) < 2:
        return validation_probability, test_probability
    validation_logit = np.log(validation_probability / (1 - validation_probability)).reshape(-1, 1)
    test_logit = np.log(test_probability / (1 - test_probability)).reshape(-1, 1)
    weights = _fit_logistic(validation_logit, validation_actual.astype(float), l2=1.0, iterations=400)
    calibrated_validation = _sigmoid(np.column_stack([np.ones(len(validation_logit)), validation_logit]) @ weights)
    calibrated_test = _sigmoid(np.column_stack([np.ones(len(test_logit)), test_logit]) @ weights)
    raw_brier = float(np.mean((validation_probability - validation_actual) ** 2))
    calibrated_brier = float(np.mean((calibrated_validation - validation_actual) ** 2))
    if calibrated_brier >= raw_brier:
        return validation_probability, test_probability
    return calibrated_validation, calibrated_test


def _macro_f1(actual: np.ndarray, predicted: np.ndarray, labels: tuple[str, ...]) -> float:
    values = []
    for label in labels:
        tp = int(((actual == label) & (predicted == label)).sum())
        fp = int(((actual != label) & (predicted == label)).sum())
        fn = int(((actual == label) & (predicted != label)).sum())
        denom = 2 * tp + fp + fn
        values.append(2 * tp / denom if denom else 0.0)
    return float(np.mean(values))


def _balanced_accuracy(actual: np.ndarray, predicted: np.ndarray, labels: tuple[str, ...]) -> float:
    recalls = []
    for label in labels:
        mask = actual == label
        if mask.any():
            recalls.append(float((predicted[mask] == label).mean()))
    return float(np.mean(recalls)) if recalls else 0.0


def _policy_signal(opportunity: np.ndarray, risk: np.ndarray, opportunity_threshold: float, risk_threshold: float) -> np.ndarray:
    return np.where(
        (opportunity >= opportunity_threshold) & (risk < risk_threshold),
        "positive",
        np.where((risk >= risk_threshold) | (opportunity < 1.0 - opportunity_threshold), "conservative", "neutral"),
    )


def _actual_environment(opportunity_target: np.ndarray, risk_target: np.ndarray) -> np.ndarray:
    return np.where(
        (opportunity_target == 1) & (risk_target == 0),
        "positive",
        np.where((opportunity_target == 0) & (risk_target == 1), "conservative", "neutral"),
    )


def _candidate_baseline_probabilities(
    frame: pd.DataFrame, index: np.ndarray, target: str, prior: float, seed: int
) -> dict[str, np.ndarray]:
    ret5 = pd.to_numeric(frame.iloc[index].get("ret_5d"), errors="coerce").fillna(0).to_numpy()
    ad = pd.to_numeric(frame.iloc[index].get("normalized_ad"), errors="coerce").fillna(0).to_numpy()
    nhnl = pd.to_numeric(frame.iloc[index].get("normalized_nhnl"), errors="coerce").fillna(0).to_numpy()
    logistic = lambda value: _sigmoid(np.asarray(value, dtype="float64"))
    random_prior = np.random.default_rng(seed).binomial(1, np.clip(prior, 0, 1), len(index)).astype(float)
    if target == "opportunity":
        return {
            "prior": np.full(len(index), prior),
            "random_train_prior": random_prior,
            "simple_trend": logistic(ret5 / 0.02),
            "simple_mean_reversion": logistic(-ret5 / 0.02),
            "ad_only": logistic(ad * 3.0),
            "nhnl_only": logistic(nhnl * 3.0),
        }
    return {
        "prior": np.full(len(index), prior),
        "random_train_prior": random_prior,
        "simple_trend": logistic(-ret5 / 0.02),
        "simple_mean_reversion": logistic(ret5 / 0.02),
        "ad_only": logistic(-ad * 3.0),
        "nhnl_only": logistic(-nhnl * 3.0),
    }


def build_purged_walk_forward_research(
    frame: pd.DataFrame,
    horizon: int,
    initial_train: int = 252,
    validation_size: int = 63,
    test_size: int = 63,
    excluded_feature_group: str | None = None,
) -> dict[str, Any]:
    """Strict train/purge/validation/embargo/test research pipeline for P0/P1."""
    suffix = f"_{int(horizon)}d"
    work = add_p0_interactions(frame).sort_values("trade_date").reset_index(drop=True)
    features = available_p0_features(work)
    if excluded_feature_group:
        excluded = set(P0_FEATURE_GROUPS.get(excluded_feature_group, ()))
        features = [feature for feature in features if feature not in excluded]
    raw_targets = [
        f"median_stock_return{suffix}", f"stock_win_rate{suffix}", f"return_q10{suffix}",
        f"median_max_drawdown{suffix}", f"large_decline_ratio{suffix}", f"equal_weight_return{suffix}",
    ]
    if len(features) < 5 or any(column not in work.columns for column in raw_targets):
        return {"folds": pd.DataFrame(), "predictions": pd.DataFrame(), "features": features}
    work = work.dropna(subset=["trade_date", *raw_targets]).reset_index(drop=True)
    fold_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []
    coefficient_rows: list[dict[str, Any]] = []
    baseline_rows: list[dict[str, Any]] = []
    label_rows: list[dict[str, Any]] = []
    fold = 0
    test_start = int(initial_train) + int(horizon) + int(validation_size) + int(horizon)
    l2_grid = (0.01, 0.1, 1.0, 10.0)
    while test_start < len(work):
        validation_start = test_start - int(horizon) - int(validation_size)
        train_end = validation_start - int(horizon)
        test_end = min(test_start + int(test_size), len(work))
        if train_end < int(initial_train):
            test_start += int(test_size)
            continue
        train_index = np.arange(train_end)
        validation_index = np.arange(validation_start, validation_start + int(validation_size))
        test_index = np.arange(test_start, test_end)
        train_targets = _fold_targets(work, train_index, train_index, suffix)
        validation_targets = _fold_targets(work, train_index, validation_index, suffix)
        test_targets = _fold_targets(work, train_index, test_index, suffix)
        feature_candidates = {"full": features}
        if excluded_feature_group is None:
            for group_name, group_features in P0_FEATURE_GROUPS.items():
                excluded = set(group_features)
                candidate_features = [feature for feature in features if feature not in excluded]
                if len(candidate_features) >= 5:
                    feature_candidates[f"without_{group_name}"] = candidate_features
        selected: dict[str, tuple[float, np.ndarray, np.ndarray, np.ndarray, list[str], str]] = {}
        for target_name in ("opportunity", "risk"):
            y_train = train_targets[f"{target_name}_target"].astype(float)
            y_validation = validation_targets[f"{target_name}_target"].astype(int)
            best = None
            for feature_model, candidate_features in feature_candidates.items():
                x_train, x_validation, _, _ = _prepare_train_test(
                    work, candidate_features, train_index, validation_index
                )
                _, x_test, _, _ = _prepare_train_test(work, candidate_features, train_index, test_index)
                for l2 in l2_grid:
                    weights = _fit_logistic(x_train, y_train, l2=l2, iterations=500)
                    probability = _sigmoid(np.column_stack([np.ones(len(x_validation)), x_validation]) @ weights)
                    test_probability = _sigmoid(np.column_stack([np.ones(len(x_test)), x_test]) @ weights)
                    score = _auc(y_validation, probability)
                    candidate = (
                        -1.0 if score is None else score, -len(candidate_features), -l2,
                        weights, probability, test_probability, candidate_features, feature_model,
                    )
                    if best is None or candidate[:3] > best[:3]:
                        best = candidate
            assert best is not None
            selected[target_name] = (-best[2], best[3], best[4], best[5], best[6], best[7])
        opp_l2, opp_weights, opp_validation, opportunity_test, opp_features, opp_feature_model = selected["opportunity"]
        risk_l2, risk_weights, risk_validation, risk_test, risk_features, risk_feature_model = selected["risk"]
        opp_validation, opportunity_test = _platt_fit_apply(
            opp_validation, validation_targets["opportunity_target"], opportunity_test
        )
        risk_validation, risk_test = _platt_fit_apply(
            risk_validation, validation_targets["risk_target"], risk_test
        )
        best_policy = None
        validation_actual_environment = _actual_environment(
            validation_targets["opportunity_target"], validation_targets["risk_target"]
        )
        for opportunity_threshold in (0.50, 0.55, 0.60, 0.65):
            for risk_threshold in (0.45, 0.50, 0.55, 0.60):
                predicted = _policy_signal(opp_validation, risk_validation, opportunity_threshold, risk_threshold)
                macro_f1 = _macro_f1(validation_actual_environment, predicted, ("positive", "neutral", "conservative"))
                conservative_actual = validation_actual_environment == "conservative"
                conservative_predicted = predicted == "conservative"
                conservative_recall = float((conservative_predicted[conservative_actual]).mean()) if conservative_actual.any() else 0.0
                conservative_precision = float((validation_actual_environment[conservative_predicted] == "conservative").mean()) if conservative_predicted.any() else 0.0
                conservative_base_rate = float(conservative_actual.mean())
                constraint_passed = conservative_recall >= 0.45 and conservative_precision >= conservative_base_rate
                candidate = (int(constraint_passed), macro_f1, -abs(risk_threshold - 0.5), opportunity_threshold, risk_threshold)
                if best_policy is None or candidate > best_policy:
                    best_policy = candidate
        policy_constraint_passed, _, _, opportunity_threshold, risk_threshold = best_policy
        test_signal = _policy_signal(opportunity_test, risk_test, opportunity_threshold, risk_threshold)
        test_actual_environment = _actual_environment(test_targets["opportunity_target"], test_targets["risk_target"])
        train_actual_environment = _actual_environment(train_targets["opportunity_target"], train_targets["risk_target"])
        majority_label = str(pd.Series(train_actual_environment).value_counts().idxmax())
        majority_signal = np.full(len(test_signal), majority_label)
        opportunity_metrics = _binary_metrics(test_targets["opportunity_target"], opportunity_test)
        risk_metrics = _binary_metrics(test_targets["risk_target"], risk_test)
        fold += 1
        fold_rows.append({
            "fold": fold, "train_start": str(work.iloc[0]["trade_date"]),
            "train_end": str(work.iloc[train_end - 1]["trade_date"]),
            "validation_start": str(work.iloc[validation_start]["trade_date"]),
            "validation_end": str(work.iloc[validation_index[-1]]["trade_date"]),
            "test_start": str(work.iloc[test_start]["trade_date"]), "test_end": str(work.iloc[test_end - 1]["trade_date"]),
            "train_count": len(train_index), "validation_count": len(validation_index), "test_count": len(test_index),
            "purge_days": int(horizon), "embargo_days": int(horizon),
            "opportunity_l2": opp_l2, "risk_l2": risk_l2,
            "opportunity_feature_model": opp_feature_model, "risk_feature_model": risk_feature_model,
            "opportunity_threshold": opportunity_threshold, "risk_threshold": risk_threshold,
            "policy_constraint_passed": bool(policy_constraint_passed),
            **{f"opportunity_{key}": value for key, value in opportunity_metrics.items()},
            **{f"risk_{key}": value for key, value in risk_metrics.items()},
            "environment_macro_f1": _record(_macro_f1(test_actual_environment, test_signal, ("positive", "neutral", "conservative")), 4),
            "environment_balanced_accuracy": _record(_balanced_accuracy(test_actual_environment, test_signal, ("positive", "neutral", "conservative")), 4),
            "majority_macro_f1": _record(_macro_f1(test_actual_environment, majority_signal, ("positive", "neutral", "conservative")), 4),
            "majority_balanced_accuracy": _record(_balanced_accuracy(test_actual_environment, majority_signal, ("positive", "neutral", "conservative")), 4),
            "opportunity_rank_ic": _record(
                pd.Series(opportunity_test).rank().corr(
                    pd.Series(pd.to_numeric(work.iloc[test_index][f"equal_weight_return{suffix}"], errors="coerce").to_numpy()).rank()
                ), 4
            ),
        })
        for target_name, weights, selected_features in (
            ("opportunity", opp_weights, opp_features), ("risk", risk_weights, risk_features)
        ):
            for feature, coefficient in zip(["intercept", *selected_features], weights):
                coefficient_rows.append({"fold": fold, "target": target_name, "feature": feature, "coefficient": _record(coefficient)})
        for target_name, target_values in (("opportunity", test_targets["opportunity_target"]), ("risk", test_targets["risk_target"])):
            prior = float(train_targets[f"{target_name}_target"].mean())
            model_probability = opportunity_test if target_name == "opportunity" else risk_test
            for model, probability in {
                "logistic_p1": model_probability,
                **_candidate_baseline_probabilities(work, test_index, target_name, prior, seed=fold * 10 + (0 if target_name == "opportunity" else 1)),
            }.items():
                metrics = _binary_metrics(target_values, probability)
                baseline_rows.append({"fold": fold, "target": target_name, "model": model, **metrics})
        for label in (
            "label_a_median", "label_b_win_rate", "label_c_downside", "opportunity_target", "risk_target",
            "opportunity_50_50", "opportunity_70_30", "risk_40_40_20", "risk_50_30_20",
        ):
            primary = (
                test_targets["risk_target"]
                if label.startswith("risk_") or label == "label_c_downside"
                else test_targets["opportunity_target"]
            )
            label_rows.append({
                "fold": fold, "label": label, "positive_rate": _record(test_targets[label].mean(), 4),
                "agreement_with_primary": _record((test_targets[label] == primary).mean(), 4), "count": len(test_index),
            })
        for offset, position in enumerate(test_index):
            prediction_rows.append({
                "trade_date": str(work.iloc[position]["trade_date"]), "fold": fold,
                "opportunity_probability": _record(opportunity_test[offset]), "risk_probability": _record(risk_test[offset]),
                "opportunity_actual": int(test_targets["opportunity_target"][offset]), "risk_actual": int(test_targets["risk_target"][offset]),
                "label_a_median": int(test_targets["label_a_median"][offset]), "label_b_win_rate": int(test_targets["label_b_win_rate"][offset]),
                "label_c_downside": int(test_targets["label_c_downside"][offset]), "environment_actual": str(test_actual_environment[offset]),
                "environment_signal": str(test_signal[offset]), f"equal_weight_return{suffix}": _record(work.iloc[position][f"equal_weight_return{suffix}"]),
                f"return_q10{suffix}": _record(work.iloc[position][f"return_q10{suffix}"]),
                f"median_max_drawdown{suffix}": _record(work.iloc[position][f"median_max_drawdown{suffix}"]),
                f"large_decline_ratio{suffix}": _record(work.iloc[position][f"large_decline_ratio{suffix}"]),
            })
        test_start += int(test_size)
    return {
        "folds": pd.DataFrame(fold_rows), "predictions": pd.DataFrame(prediction_rows),
        "features": features, "coefficients": pd.DataFrame(coefficient_rows),
        "baselines": pd.DataFrame(baseline_rows), "label_stability": pd.DataFrame(label_rows),
    }


def build_feature_decile_study(frame: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Univariate train-observable deciles for every P0 feature."""
    work = add_p0_interactions(frame)
    suffix = f"_{int(horizon)}d"
    outcomes = [
        f"median_stock_return{suffix}", f"equal_weight_return{suffix}",
        f"stock_win_rate{suffix}", f"return_q10{suffix}",
    ]
    rows: list[dict[str, Any]] = []
    for feature in available_p0_features(work):
        percentile = _observable_percentile(work[feature])
        decile = np.minimum((percentile * 10).fillna(-1).astype(int), 9)
        for bucket in range(10):
            group = work[decile == bucket]
            if group.empty:
                continue
            row: dict[str, Any] = {"feature": feature, "decile": bucket + 1, "count": len(group)}
            for outcome in outcomes:
                row[outcome.removesuffix(suffix)] = _record(pd.to_numeric(group.get(outcome), errors="coerce").mean())
            rows.append(row)
    return pd.DataFrame(rows)


def summarize_walk_forward_research(research: dict[str, Any], horizon: int) -> pd.DataFrame:
    """Aggregate gates and model-vs-baseline evidence without treating overlap as IID."""
    folds = research.get("folds", pd.DataFrame())
    predictions = research.get("predictions", pd.DataFrame())
    baselines = research.get("baselines", pd.DataFrame())
    if folds.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for target in ("opportunity", "risk"):
        target_baselines = baselines[baselines["target"] == target]
        model = target_baselines[target_baselines["model"] == "logistic_p1"].set_index("fold")
        simple = target_baselines[target_baselines["model"] != "logistic_p1"]
        best_simple = simple.groupby("fold")["auc"].max()
        aligned = model.join(best_simple.rename("best_simple_auc"), how="inner")
        rows.append({
            "section": "model_gate", "target": target,
            "mean_auc": _record(pd.to_numeric(model["auc"], errors="coerce").mean(), 4),
            "best_simple_mean_auc": _record(pd.to_numeric(best_simple, errors="coerce").mean(), 4),
            "fold_win_rate": _record((pd.to_numeric(aligned["auc"], errors="coerce") > pd.to_numeric(aligned["best_simple_auc"], errors="coerce")).mean(), 4),
            "brier_skill": _record(pd.to_numeric(model["brier_skill"], errors="coerce").mean(), 4),
            "log_loss_improvement": _record(pd.to_numeric(model["log_loss_improvement"], errors="coerce").mean(), 4),
            "ece": _record(pd.to_numeric(model["ece"], errors="coerce").mean(), 4),
        })
    rank_ic = pd.to_numeric(folds["opportunity_rank_ic"], errors="coerce")
    rows.append({
        "section": "ranking_gate", "target": "opportunity",
        "mean_rank_ic": _record(rank_ic.mean(), 4), "positive_fold_ratio": _record((rank_ic > 0).mean(), 4),
        "environment_macro_f1": _record(pd.to_numeric(folds["environment_macro_f1"], errors="coerce").mean(), 4),
        "majority_macro_f1": _record(pd.to_numeric(folds["majority_macro_f1"], errors="coerce").mean(), 4),
        "environment_balanced_accuracy": _record(pd.to_numeric(folds["environment_balanced_accuracy"], errors="coerce").mean(), 4),
        "majority_balanced_accuracy": _record(pd.to_numeric(folds["majority_balanced_accuracy"], errors="coerce").mean(), 4),
        "policy_constraint_fold_ratio": _record(folds["policy_constraint_passed"].astype(bool).mean(), 4),
    })
    if not predictions.empty:
        for target, probability, outcome in (
            ("opportunity", "opportunity_probability", f"equal_weight_return_{int(horizon)}d"),
            ("risk", "risk_probability", f"return_q10_{int(horizon)}d"),
        ):
            ranked = predictions.copy()
            ranked["bucket"] = pd.qcut(pd.to_numeric(ranked[probability], errors="coerce"), 5, labels=False, duplicates="drop")
            grouped = ranked.groupby("bucket")[outcome].mean()
            values = pd.to_numeric(ranked[outcome], errors="coerce").to_numpy(dtype="float64")
            buckets = ranked["bucket"].to_numpy()
            rng = np.random.default_rng(20260713)
            block = max(int(horizon), 5)
            starts = np.arange(max(len(ranked) - block + 1, 1))
            bootstrap = []
            for _ in range(500):
                sampled: list[int] = []
                while len(sampled) < len(ranked):
                    start = int(rng.choice(starts))
                    sampled.extend(range(start, min(start + block, len(ranked))))
                sampled_array = np.asarray(sampled[: len(ranked)])
                sampled_values = values[sampled_array]
                sampled_buckets = buckets[sampled_array]
                high = sampled_values[sampled_buckets == np.nanmax(buckets)]
                low = sampled_values[sampled_buckets == np.nanmin(buckets)]
                if len(high) and len(low):
                    bootstrap.append(float(np.nanmean(high) - np.nanmean(low)))
            rows.append({
                "section": "economic_sort", "target": target,
                "low_group_outcome": _record(grouped.iloc[0] if len(grouped) else None),
                "high_group_outcome": _record(grouped.iloc[-1] if len(grouped) else None),
                "high_minus_low": _record(grouped.iloc[-1] - grouped.iloc[0] if len(grouped) > 1 else None),
                "tail_worsening_ratio": _record(
                    (grouped.iloc[0] - grouped.iloc[-1]) / abs(grouped.iloc[0])
                    if target == "risk" and len(grouped) > 1 and grouped.iloc[0] != 0 else None,
                    4,
                ),
                "block_bootstrap_ci_low": _record(np.nanquantile(bootstrap, 0.025) if bootstrap else None),
                "block_bootstrap_ci_high": _record(np.nanquantile(bootstrap, 0.975) if bootstrap else None),
                "bootstrap_block_days": block,
            })
    return pd.DataFrame(rows)


def build_feature_group_ablation(
    frame: pd.DataFrame, horizon: int, baseline_research: dict[str, Any] | None = None
) -> pd.DataFrame:
    """Run the same strict folds after removing each economically distinct feature group."""
    rows = []
    for excluded in (None, *P0_FEATURE_GROUPS.keys()):
        result = baseline_research if excluded is None and baseline_research is not None else build_purged_walk_forward_research(
            frame, horizon, excluded_feature_group=excluded
        )
        folds = result.get("folds", pd.DataFrame())
        rows.append({
            "excluded_group": excluded or "none",
            "feature_count": len(result.get("features", [])),
            "fold_count": len(folds),
            "opportunity_auc": _record(pd.to_numeric(folds.get("opportunity_auc"), errors="coerce").mean(), 4) if not folds.empty else None,
            "risk_auc": _record(pd.to_numeric(folds.get("risk_auc"), errors="coerce").mean(), 4) if not folds.empty else None,
            "opportunity_rank_ic": _record(pd.to_numeric(folds.get("opportunity_rank_ic"), errors="coerce").mean(), 4) if not folds.empty else None,
        })
    return pd.DataFrame(rows)


def summarize_coefficient_stability(
    coefficients: pd.DataFrame, total_folds: int
) -> pd.DataFrame:
    """Summarize coefficient direction and selection stability across time folds."""
    if coefficients.empty:
        return pd.DataFrame()
    rows = []
    for (target, feature), group in coefficients.groupby(["target", "feature"]):
        values = pd.to_numeric(group["coefficient"], errors="coerce").dropna()
        rows.append({
            "target": target, "feature": feature, "selected_folds": int(group["fold"].nunique()),
            "selection_rate": _record(group["fold"].nunique() / max(total_folds, 1), 4),
            "mean_coefficient": _record(values.mean()), "std_coefficient": _record(values.std(ddof=0)),
            "positive_rate_when_selected": _record((values > 0).mean(), 4),
            "direction_stability": _record(max((values > 0).mean(), (values < 0).mean()), 4),
        })
    return pd.DataFrame(rows).sort_values(["target", "selection_rate", "direction_stability"], ascending=[True, False, False])


def build_point_in_time_quality_study(frame: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Expose historical universe coverage; it cannot reconstruct missing delisted/ST histories."""
    count_col = f"effective_stock_count_{int(horizon)}d"
    if count_col not in frame.columns or "trade_date" not in frame.columns:
        return pd.DataFrame()
    work = frame[["trade_date", count_col]].copy()
    work["year"] = pd.to_datetime(work["trade_date"], errors="coerce").dt.year
    work[count_col] = pd.to_numeric(work[count_col], errors="coerce")
    maximum = work[count_col].max()
    rows = []
    for year, group in work.dropna().groupby("year"):
        median = group[count_col].median()
        rows.append({
            "year": int(year), "days": len(group), "min_stock_count": int(group[count_col].min()),
            "median_stock_count": int(median), "max_stock_count": int(group[count_col].max()),
            "coverage_vs_full_history_max": _record(median / maximum, 4) if maximum else None,
            "point_in_time_status": "limited_current_cache_universe",
        })
    return pd.DataFrame(rows)


def build_oos_regime_stability(
    frame: pd.DataFrame, predictions: pd.DataFrame, horizon: int
) -> pd.DataFrame:
    """Evaluate OOS discrimination by calendar year and observable volatility regime."""
    if predictions.empty:
        return pd.DataFrame()
    columns = [column for column in ["trade_date", "cross_section_volatility_20d"] if column in frame.columns]
    work = predictions.merge(frame[columns].drop_duplicates("trade_date"), on="trade_date", how="left")
    work["year"] = pd.to_datetime(work["trade_date"], errors="coerce").dt.year
    volatility_rank = _observable_percentile(work.get("cross_section_volatility_20d", pd.Series(np.nan, index=work.index)))
    work["volatility_regime"] = np.where(volatility_rank <= 0.33, "low", np.where(volatility_rank >= 0.67, "high", "middle"))
    rows = []
    for dimension in ("year", "volatility_regime"):
        for value, group in work.groupby(dimension):
            rows.append({
                "dimension": dimension, "value": str(value), "count": len(group),
                "opportunity_auc": _record(_auc(group["opportunity_actual"].to_numpy(), group["opportunity_probability"].to_numpy()), 4),
                "risk_auc": _record(_auc(group["risk_actual"].to_numpy(), group["risk_probability"].to_numpy()), 4),
                "environment_macro_f1": _record(_macro_f1(
                    group["environment_actual"].to_numpy(), group["environment_signal"].to_numpy(),
                    ("positive", "neutral", "conservative"),
                ), 4),
            })
    return pd.DataFrame(rows)


def build_environment_transition_study(
    frame: pd.DataFrame, predictions: pd.DataFrame
) -> pd.DataFrame:
    """Study OOS policy transitions without feeding outcomes back into the policy."""
    if predictions.empty:
        return pd.DataFrame()
    target_columns = [
        column for column in frame.columns
        if column.startswith((
            "equal_weight_return_", "median_stock_return_", "stock_win_rate_", "return_q10_",
            "median_max_drawdown_",
        ))
    ]
    work = predictions[["trade_date", "environment_signal"]].merge(
        frame[["trade_date", *target_columns]].drop_duplicates("trade_date"), on="trade_date", how="left"
    )
    previous = work["environment_signal"].shift(1)
    rows = []
    for source, destination in (("positive", "conservative"), ("conservative", "positive")):
        group = work[(previous == source) & (work["environment_signal"] == destination)]
        for horizon in (1, 5, 10, 20):
            suffix = f"_{horizon}d"
            rows.append({
                "transition": f"{source}_to_{destination}", "horizon": horizon, "count": len(group),
                "equal_weight_return": _record(pd.to_numeric(group.get(f"equal_weight_return{suffix}"), errors="coerce").mean()),
                "median_stock_return": _record(pd.to_numeric(group.get(f"median_stock_return{suffix}"), errors="coerce").mean()),
                "stock_win_rate": _record(pd.to_numeric(group.get(f"stock_win_rate{suffix}"), errors="coerce").mean(), 4),
                "return_q10": _record(pd.to_numeric(group.get(f"return_q10{suffix}"), errors="coerce").mean()),
                "median_max_drawdown": _record(pd.to_numeric(group.get(f"median_max_drawdown{suffix}"), errors="coerce").mean()),
            })
    return pd.DataFrame(rows)


def _strategy_stats(returns: pd.Series, exposure: pd.Series) -> dict[str, Any]:
    values = pd.to_numeric(returns, errors="coerce").fillna(0.0)
    equity = (1.0 + values).cumprod()
    annual = (float(equity.iloc[-1]) ** (252.0 / max(len(equity), 1)) - 1.0) if len(equity) else np.nan
    drawdown = float((equity / equity.cummax() - 1.0).min()) if len(equity) else np.nan
    std = float(values.std(ddof=0))
    return {
        "total_return": _record(equity.iloc[-1] - 1.0 if len(equity) else None),
        "annual_return": _record(annual), "max_drawdown": _record(drawdown),
        "calmar": _record(annual / abs(drawdown), 4) if drawdown else None,
        "sharpe": _record(values.mean() / std * np.sqrt(252.0), 4) if std else None,
        "win_rate": _record((values > 0).mean(), 4),
        "average_exposure": _record(exposure.mean(), 4),
        "turnover": _record(exposure.diff().abs().sum(), 4),
        "worst_20d": _record(values.nsmallest(min(20, len(values))).sum()),
    }


def evaluate_oos_strategy_policies(
    frame: pd.DataFrame,
    predictions: pd.DataFrame,
    strategy_returns: Mapping[str, pd.Series] | None,
) -> pd.DataFrame:
    """Compare A-E filters on the frozen OOS dates, including matched random exposure."""
    if predictions.empty or not strategy_returns:
        return pd.DataFrame()
    feature_columns = [column for column in ("trade_date", "ret_20d", "normalized_ad") if column in frame.columns]
    signals = predictions[["trade_date", "environment_signal"]].merge(
        frame[feature_columns].drop_duplicates("trade_date"), on="trade_date", how="left"
    ).set_index("trade_date")
    p1 = signals["environment_signal"].map({"positive": 1.0, "neutral": 0.5, "conservative": 0.0}).fillna(0.5)
    trend = np.where(pd.to_numeric(signals.get("ret_20d"), errors="coerce") >= 0, 1.0, 0.0)
    breadth = np.where(pd.to_numeric(signals.get("normalized_ad"), errors="coerce") >= 0, 1.0, 0.0)
    rng = np.random.default_rng(20260713)
    random_matched = pd.Series(rng.permutation(p1.to_numpy()), index=p1.index)
    exposures = {
        "A_unfiltered": pd.Series(1.0, index=p1.index),
        "B_index_trend": pd.Series(trend, index=p1.index),
        "C_market_breadth": pd.Series(breadth, index=p1.index),
        "D_full_environment": p1,
        "E_random_matched_exposure": random_matched,
    }
    rows = []
    for strategy, series in strategy_returns.items():
        daily = pd.to_numeric(series, errors="coerce").copy()
        daily.index = pd.to_datetime(daily.index, errors="coerce").strftime("%Y-%m-%d")
        aligned = daily.reindex(signals.index).fillna(0.0)
        for policy, exposure in exposures.items():
            executable_exposure = exposure.shift(1).fillna(0.0)
            rows.append({"strategy": str(strategy), "policy": policy, **_strategy_stats(aligned * executable_exposure, executable_exposure)})
    return pd.DataFrame(rows)


def build_research_gate_audit(
    summary: pd.DataFrame, strategy_policies: pd.DataFrame
) -> pd.DataFrame:
    """Turn the review's numeric thresholds into an explicit pass/fail audit."""
    def value(section: str, target: str, column: str) -> float | None:
        if summary.empty or not {"section", "target"}.issubset(summary.columns):
            return None
        selected = summary[(summary["section"] == section) & (summary["target"] == target)]
        if selected.empty or column not in selected.columns or pd.isna(selected.iloc[0][column]):
            return None
        return float(selected.iloc[0][column])

    specs = [
        ("opportunity_rank_ic", value("ranking_gate", "opportunity", "mean_rank_ic"), 0.03, ">="),
        ("opportunity_positive_fold_ratio", value("ranking_gate", "opportunity", "positive_fold_ratio"), 0.70, ">="),
        ("risk_auc", value("model_gate", "risk", "mean_auc"), 0.60, ">="),
        ("opportunity_fold_win_rate", value("model_gate", "opportunity", "fold_win_rate"), 0.70, ">="),
        ("risk_fold_win_rate", value("model_gate", "risk", "fold_win_rate"), 0.70, ">="),
        ("opportunity_brier_skill", value("model_gate", "opportunity", "brier_skill"), 0.0, ">"),
        ("risk_brier_skill", value("model_gate", "risk", "brier_skill"), 0.0, ">"),
        ("opportunity_log_loss_improvement", value("model_gate", "opportunity", "log_loss_improvement"), 0.05, ">="),
        ("risk_log_loss_improvement", value("model_gate", "risk", "log_loss_improvement"), 0.05, ">="),
        ("opportunity_ece", value("model_gate", "opportunity", "ece"), 0.08, "<="),
        ("risk_ece", value("model_gate", "risk", "ece"), 0.08, "<="),
        (
            "environment_macro_f1_gain",
            (value("ranking_gate", "opportunity", "environment_macro_f1") or 0.0)
            - (value("ranking_gate", "opportunity", "majority_macro_f1") or 0.0),
            0.03, ">=",
        ),
        (
            "environment_balanced_accuracy_gain",
            (value("ranking_gate", "opportunity", "environment_balanced_accuracy") or 0.0)
            - (value("ranking_gate", "opportunity", "majority_balanced_accuracy") or 0.0),
            0.03, ">=",
        ),
        ("opportunity_high_low_return", value("economic_sort", "opportunity", "high_minus_low"), 0.005, ">="),
        ("opportunity_bootstrap_ci_low", value("economic_sort", "opportunity", "block_bootstrap_ci_low"), 0.0, ">"),
        ("risk_tail_worsening_ratio", value("economic_sort", "risk", "tail_worsening_ratio"), 0.20, ">="),
        ("policy_constraint_fold_ratio", value("ranking_gate", "opportunity", "policy_constraint_fold_ratio"), 0.70, ">="),
    ]
    rows = []
    for gate, actual, threshold, operator in specs:
        passed = False if actual is None else (
            actual >= threshold if operator == ">=" else actual > threshold if operator == ">" else actual <= threshold
        )
        rows.append({"gate": gate, "actual": _record(actual, 4), "operator": operator, "threshold": threshold, "passed": passed})
    strategy_count = int(strategy_policies["strategy"].nunique()) if not strategy_policies.empty else 0
    rows.append({"gate": "strategy_count", "actual": strategy_count, "operator": ">=", "threshold": 3, "passed": strategy_count >= 3})
    drawdown_pass_ratio = 0.0
    calmar_pass_ratio = 0.0
    if not strategy_policies.empty:
        pivot_dd = strategy_policies.pivot(index="strategy", columns="policy", values="max_drawdown")
        pivot_calmar = strategy_policies.pivot(index="strategy", columns="policy", values="calmar")
        needed = {"A_unfiltered", "D_full_environment"}
        if needed.issubset(pivot_dd.columns):
            dd_improvement = (pivot_dd["A_unfiltered"].abs() - pivot_dd["D_full_environment"].abs()) / pivot_dd["A_unfiltered"].abs()
            drawdown_pass_ratio = float((dd_improvement >= 0.10).mean())
        if needed.issubset(pivot_calmar.columns):
            calmar_improvement = pivot_calmar["D_full_environment"] - pivot_calmar["A_unfiltered"]
            calmar_pass_ratio = float((calmar_improvement >= 0.15 * pivot_calmar["A_unfiltered"].abs()).mean())
    rows.extend([
        {"gate": "strategy_drawdown_pass_ratio", "actual": _record(drawdown_pass_ratio, 4), "operator": ">=", "threshold": 0.5, "passed": drawdown_pass_ratio >= 0.5 and strategy_count >= 3},
        {"gate": "strategy_calmar_pass_ratio", "actual": _record(calmar_pass_ratio, 4), "operator": ">=", "threshold": 0.5, "passed": calmar_pass_ratio >= 0.5 and strategy_count >= 3},
    ])
    all_passed = all(bool(row["passed"]) for row in rows)
    rows.append({
        "gate": "p2_p3_authorized", "actual": int(all_passed), "operator": "==", "threshold": 1,
        "passed": all_passed,
        "decision": "proceed_to_nonlinear_and_production_validation" if all_passed else "stop_at_p1_keep_formal_signal_unchanged",
    })
    return pd.DataFrame(rows)
