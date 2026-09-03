"""Low-complexity, strictly time-ordered models for the market risk gate."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from analysis.market_risk_features import MINIMAL_RISK_FEATURES, available_minimal_features
from analysis.market_risk_labels import RISK_LABELS, fold_risk_labels, risk_outcome_columns


L2_GRID = (0.01, 0.1, 1.0, 10.0)
FROZEN_BASELINES = {
    "large_decline_only": "current_large_decline_ratio",
    "ad_only": "normalized_ad",
    "nhnl_only": "normalized_nhnl",
    "volatility_only": "realized_volatility_5d",
    "simple_trend": "index_return_5d",
    "simple_mean_reversion": "index_return_5d",
}


@dataclass(frozen=True)
class RiskExperiment:
    experiment: str
    horizon: int
    label: str
    feature_set: str = "minimal_v1"
    class_weight: str = "balanced"
    calibration: str = "none"

    def validate(self) -> None:
        if self.label not in RISK_LABELS:
            raise ValueError(f"不支持的风险标签: {self.label}")
        if self.horizon not in (1, 5, 10, 20):
            raise ValueError(f"不支持的风险周期: {self.horizon}")
        if self.feature_set not in {"minimal_v1", "minimal_no_interaction"}:
            raise ValueError(f"不支持的风险特征集: {self.feature_set}")
        if self.class_weight not in {"none", "balanced"}:
            raise ValueError(f"不支持的类别权重: {self.class_weight}")
        if self.calibration not in {"none", "platt_nested"}:
            raise ValueError(f"不支持的校准方式: {self.calibration}")


def default_experiment_matrix() -> list[RiskExperiment]:
    return [
        RiskExperiment("E1", 5, "R1"),
        RiskExperiment("E2", 5, "R2"),
        RiskExperiment("E3", 5, "R3"),
        RiskExperiment("E4", 5, "R4"),
        RiskExperiment("E5", 5, "R5"),
        RiskExperiment("E6", 5, "R2", feature_set="minimal_no_interaction"),
        RiskExperiment("E7", 5, "R2", feature_set="minimal_no_interaction", class_weight="none"),
        RiskExperiment("E8", 5, "R2", feature_set="minimal_no_interaction", class_weight="none", calibration="platt_nested"),
        RiskExperiment("E9", 10, "R2", feature_set="minimal_no_interaction", class_weight="none"),
        RiskExperiment("E10", 20, "R2", feature_set="minimal_no_interaction", class_weight="none"),
        RiskExperiment("H1_R1", 1, "R1", feature_set="minimal_no_interaction", class_weight="none"),
    ]


def _sigmoid(values: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(values, -35.0, 35.0)))


def _fit_logistic(
    x: np.ndarray,
    y: np.ndarray,
    l2: float,
    class_weight: str,
    iterations: int = 500,
    learning_rate: float = 0.08,
) -> np.ndarray:
    weights = np.zeros(x.shape[1] + 1, dtype="float64")
    if class_weight == "balanced":
        positives = max(int((y == 1).sum()), 1)
        negatives = max(int((y == 0).sum()), 1)
        sample_weight = np.where(y == 1, len(y) / (2 * positives), len(y) / (2 * negatives))
    else:
        sample_weight = np.ones(len(y), dtype="float64")
    design = np.column_stack([np.ones(len(x)), x])
    for _ in range(iterations):
        probability = _sigmoid(design @ weights)
        gradient = design.T @ ((probability - y) * sample_weight) / max(len(y), 1)
        gradient[1:] += float(l2) * weights[1:] / max(len(y), 1)
        weights -= learning_rate * gradient
    return weights


def _prepare(
    frame: pd.DataFrame,
    features: list[str],
    train_index: np.ndarray,
    apply_index: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    train = frame.iloc[train_index][features].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    apply = frame.iloc[apply_index][features].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    medians = train.median().fillna(0.0)
    train = train.fillna(medians)
    apply = apply.fillna(medians)
    lower = train.quantile(0.01)
    upper = train.quantile(0.99)
    train = train.clip(lower=lower, upper=upper, axis=1)
    apply = apply.clip(lower=lower, upper=upper, axis=1)
    mean = train.mean()
    std = train.std(ddof=0).replace(0, 1.0).fillna(1.0)
    return ((train - mean) / std).to_numpy(dtype="float64"), ((apply - mean) / std).to_numpy(dtype="float64")


def _auc(actual: np.ndarray, score: np.ndarray) -> float | None:
    actual = np.asarray(actual, dtype=int)
    positives = int((actual == 1).sum())
    negatives = int((actual == 0).sum())
    if not positives or not negatives:
        return None
    ranks = pd.Series(score).rank(method="average").to_numpy()
    return float((ranks[actual == 1].sum() - positives * (positives + 1) / 2) / (positives * negatives))


def _pr_auc(actual: np.ndarray, score: np.ndarray) -> float | None:
    actual = np.asarray(actual, dtype=int)
    if not (actual == 1).any():
        return None
    order = np.argsort(-np.asarray(score, dtype="float64"))
    y = actual[order]
    tp = np.cumsum(y == 1)
    fp = np.cumsum(y == 0)
    precision = tp / np.maximum(tp + fp, 1)
    recall = tp / int((actual == 1).sum())
    return float(np.sum((recall - np.r_[0.0, recall[:-1]]) * precision))


def _probability_metrics(actual: np.ndarray, probability: np.ndarray, train_prior: float) -> dict[str, float | None]:
    actual = np.asarray(actual, dtype=int)
    probability = np.clip(np.asarray(probability, dtype="float64"), 1e-6, 1 - 1e-6)
    brier = float(np.mean((probability - actual) ** 2))
    baseline = float(np.mean((float(train_prior) - actual) ** 2))
    buckets = np.minimum((probability * 10).astype(int), 9)
    ece = 0.0
    for bucket in range(10):
        mask = buckets == bucket
        if mask.any():
            ece += mask.mean() * abs(float(probability[mask].mean()) - float(actual[mask].mean()))
    return {
        "brier_score": round(brier, 6),
        "brier_skill": round(1 - brier / baseline, 4) if baseline > 0 else None,
        "ece": round(float(ece), 4),
    }


def _threshold_metrics(actual: np.ndarray, score: np.ndarray, threshold: float) -> dict[str, float]:
    predicted = np.asarray(score) >= float(threshold)
    actual = np.asarray(actual, dtype=bool)
    tp = int((predicted & actual).sum())
    fp = int((predicted & ~actual).sum())
    fn = int((~predicted & actual).sum())
    tn = int((~predicted & ~actual).sum())
    return {
        "recall": round(tp / (tp + fn), 4) if tp + fn else 0.0,
        "precision": round(tp / (tp + fp), 4) if tp + fp else 0.0,
        "false_positive_rate": round(fp / (fp + tn), 4) if fp + tn else 0.0,
        "false_negative_rate": round(fn / (fn + tp), 4) if fn + tp else 0.0,
    }


def _select_policy_threshold(actual: np.ndarray, score: np.ndarray) -> float:
    base_rate = float(np.mean(actual))
    candidates = []
    for threshold in np.linspace(0.10, 0.90, 17):
        metrics = _threshold_metrics(actual, score, float(threshold))
        feasible = metrics["recall"] >= 0.50 and metrics["precision"] >= base_rate
        utility = metrics["recall"] - 0.5 * metrics["false_positive_rate"]
        candidates.append((int(feasible), utility, -abs(float(threshold) - 0.5), float(threshold)))
    return max(candidates)[-1]


def _platt_nested(
    raw_calibration: np.ndarray,
    calibration_actual: np.ndarray,
    raw_apply: np.ndarray,
) -> tuple[np.ndarray, bool]:
    if len(raw_calibration) < 126 or len(np.unique(calibration_actual)) < 2:
        return raw_apply, False
    cal = np.clip(raw_calibration, 1e-6, 1 - 1e-6)
    apply = np.clip(raw_apply, 1e-6, 1 - 1e-6)
    x_cal = np.log(cal / (1 - cal)).reshape(-1, 1)
    x_apply = np.log(apply / (1 - apply)).reshape(-1, 1)
    weights = _fit_logistic(x_cal, calibration_actual.astype(float), 1.0, "none", iterations=400)
    return _sigmoid(np.column_stack([np.ones(len(x_apply)), x_apply]) @ weights), True


def _risk_sort_metrics(
    frame: pd.DataFrame,
    index: np.ndarray,
    score: np.ndarray,
    validation_score: np.ndarray,
    horizon: int,
) -> dict[str, float | None]:
    low_cut = float(np.quantile(validation_score, 0.20))
    high_cut = float(np.quantile(validation_score, 0.80))
    low = np.asarray(score) <= low_cut
    high = np.asarray(score) >= high_cut
    suffix = f"_{int(horizon)}d"
    metrics: dict[str, float | None] = {}
    for name, column in (
        ("q10", f"future_return_q10{suffix}"),
        ("max_drawdown", f"future_median_max_drawdown{suffix}"),
        ("large_decline_ratio", f"future_large_decline_ratio{suffix}"),
    ):
        values = pd.to_numeric(frame.iloc[index][column], errors="coerce").to_numpy(dtype="float64")
        low_value = float(np.nanmean(values[low])) if low.any() else np.nan
        high_value = float(np.nanmean(values[high])) if high.any() else np.nan
        metrics[f"low_risk_{name}"] = round(low_value, 6) if np.isfinite(low_value) else None
        metrics[f"high_risk_{name}"] = round(high_value, 6) if np.isfinite(high_value) else None
        metrics[f"high_minus_low_{name}"] = round(high_value - low_value, 6) if np.isfinite(low_value + high_value) else None
    return metrics


def _baseline_probabilities(
    frame: pd.DataFrame,
    train_index: np.ndarray,
    apply_index: np.ndarray,
    y_train: np.ndarray,
    l2: float,
) -> dict[str, np.ndarray]:
    output = {"train_risk_rate": np.full(len(apply_index), float(y_train.mean()))}
    for name, feature in FROZEN_BASELINES.items():
        x_train, x_apply = _prepare(frame, [feature], train_index, apply_index)
        if name == "simple_trend":
            # Frozen direction: a weak 5-day trend means higher risk.
            output[name] = _sigmoid(-x_apply[:, 0])
            continue
        if name == "simple_mean_reversion":
            # Frozen opposite hypothesis: a strong 5-day rise precedes mean reversion.
            output[name] = _sigmoid(x_apply[:, 0])
            continue
        weights = _fit_logistic(x_train, y_train.astype(float), l2, "none")
        output[name] = _sigmoid(np.column_stack([np.ones(len(x_apply)), x_apply]) @ weights)
    return output


def run_risk_experiment(
    frame: pd.DataFrame,
    experiment: RiskExperiment,
    initial_train: int = 504,
    validation_size: int = 63,
    test_size: int = 63,
) -> dict[str, Any]:
    """Run one factor-controlled risk experiment with strict OOS test folds."""
    experiment.validate()
    horizon = int(experiment.horizon)
    outcomes = risk_outcome_columns(horizon)
    required = ["trade_date", *outcomes]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"风险实验缺少字段: {', '.join(missing)}")
    work = frame.dropna(subset=required).sort_values("trade_date").reset_index(drop=True).copy()
    features = available_minimal_features(work)
    if experiment.feature_set == "minimal_no_interaction":
        features = [feature for feature in features if feature != "ad_level_x_slope_5"]
    if len(features) > 11 or len(features) < 8:
        raise ValueError(f"风险特征数量不符合8-11个约束: {len(features)}")
    fold_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []
    baseline_rows: list[dict[str, Any]] = []
    coefficient_rows: list[dict[str, Any]] = []
    fold = 0
    test_start = int(initial_train) + horizon + int(validation_size) + horizon
    while test_start < len(work):
        validation_start = test_start - horizon - int(validation_size)
        train_end = validation_start - horizon
        test_end = min(test_start + int(test_size), len(work))
        train_index = np.arange(train_end)
        validation_index = np.arange(validation_start, validation_start + int(validation_size))
        test_index = np.arange(test_start, test_end)
        if len(train_index) < int(initial_train):
            test_start += int(test_size)
            continue
        train_labels = fold_risk_labels(work.iloc[train_index], work.iloc[train_index], horizon)[experiment.label].astype(int).to_numpy()
        validation_labels = fold_risk_labels(work.iloc[train_index], work.iloc[validation_index], horizon)[experiment.label].astype(int).to_numpy()
        test_label_frame = fold_risk_labels(work.iloc[train_index], work.iloc[test_index], horizon)
        test_labels = test_label_frame[experiment.label].astype(int).to_numpy()
        if len(np.unique(train_labels)) < 2 or len(np.unique(validation_labels)) < 2:
            test_start += int(test_size)
            continue
        x_train, x_validation = _prepare(work, features, train_index, validation_index)
        _, x_test = _prepare(work, features, train_index, test_index)
        best = None
        for l2 in L2_GRID:
            weights = _fit_logistic(x_train, train_labels.astype(float), l2, experiment.class_weight)
            validation_raw = _sigmoid(np.column_stack([np.ones(len(x_validation)), x_validation]) @ weights)
            auc = _auc(validation_labels, validation_raw)
            candidate = (-1.0 if auc is None else auc, -l2, weights, validation_raw)
            if best is None or candidate[:2] > best[:2]:
                best = candidate
        assert best is not None
        l2 = -best[1]
        weights = best[2]
        validation_score = best[3]
        test_score = _sigmoid(np.column_stack([np.ones(len(x_test)), x_test]) @ weights)
        calibration_valid = False
        if experiment.calibration == "platt_nested":
            calibration_size = 126
            base_end = len(train_index) - calibration_size - horizon
            if base_end >= 252:
                base_index = train_index[:base_end]
                calibration_index = train_index[base_end + horizon :]
                base_labels = fold_risk_labels(work.iloc[base_index], work.iloc[base_index], horizon)[experiment.label].astype(int).to_numpy()
                calibration_labels = fold_risk_labels(work.iloc[base_index], work.iloc[calibration_index], horizon)[experiment.label].astype(int).to_numpy()
                x_base, x_cal = _prepare(work, features, base_index, calibration_index)
                _, x_validation_nested = _prepare(work, features, base_index, validation_index)
                _, x_test_nested = _prepare(work, features, base_index, test_index)
                nested_weights = _fit_logistic(x_base, base_labels.astype(float), l2, experiment.class_weight)
                cal_raw = _sigmoid(np.column_stack([np.ones(len(x_cal)), x_cal]) @ nested_weights)
                validation_raw = _sigmoid(np.column_stack([np.ones(len(x_validation_nested)), x_validation_nested]) @ nested_weights)
                test_raw = _sigmoid(np.column_stack([np.ones(len(x_test_nested)), x_test_nested]) @ nested_weights)
                validation_score, calibration_valid = _platt_nested(cal_raw, calibration_labels, validation_raw)
                test_score, test_calibration_valid = _platt_nested(cal_raw, calibration_labels, test_raw)
                calibration_valid = calibration_valid and test_calibration_valid
        probability_valid = experiment.class_weight == "none" and (
            experiment.calibration == "none" or calibration_valid
        )
        threshold = _select_policy_threshold(validation_labels, validation_score)
        fold += 1
        auc = _auc(test_labels, test_score)
        pr_auc = _pr_auc(test_labels, test_score)
        metrics = _threshold_metrics(test_labels, test_score, threshold)
        probability_metrics = _probability_metrics(test_labels, test_score, float(train_labels.mean()))
        sort_metrics = _risk_sort_metrics(work, test_index, test_score, validation_score, horizon)
        fold_rows.append({
            **asdict(experiment), "fold": fold,
            "train_start": str(work.iloc[0]["trade_date"]), "train_end": str(work.iloc[train_end - 1]["trade_date"]),
            "validation_start": str(work.iloc[validation_start]["trade_date"]),
            "validation_end": str(work.iloc[validation_index[-1]]["trade_date"]),
            "test_start": str(work.iloc[test_start]["trade_date"]), "test_end": str(work.iloc[test_end - 1]["trade_date"]),
            "train_count": len(train_index), "validation_count": len(validation_index), "test_count": len(test_index),
            "purge_days": horizon, "embargo_days": horizon, "feature_count": len(features), "l2": l2,
            "risk_event_base_rate": round(float(test_labels.mean()), 4),
            "roc_auc": round(float(auc), 4) if auc is not None else None,
            "pr_auc": round(float(pr_auc), 4) if pr_auc is not None else None,
            "policy_threshold": round(float(threshold), 4), "probability_valid": probability_valid,
            "calibration_valid": calibration_valid, **probability_metrics, **metrics, **sort_metrics,
        })
        for feature, coefficient in zip(["intercept", *features], weights):
            coefficient_rows.append({
                "experiment": experiment.experiment, "fold": fold, "feature": feature,
                "coefficient": round(float(coefficient), 6),
            })
        baseline_test = _baseline_probabilities(work, train_index, test_index, train_labels, l2)
        for baseline_name, baseline_score in baseline_test.items():
            baseline_rows.append({
                "experiment": experiment.experiment, "fold": fold, "baseline": baseline_name,
                "roc_auc": round(float(value), 4) if (value := _auc(test_labels, baseline_score)) is not None else None,
                "pr_auc": round(float(value), 4) if (value := _pr_auc(test_labels, baseline_score)) is not None else None,
            })
        for offset, position in enumerate(test_index):
            prediction_rows.append({
                "trade_date": str(work.iloc[position]["trade_date"]), "experiment": experiment.experiment,
                "fold": fold, "actual_risk": int(test_labels[offset]),
                "future_risk_state": str(test_label_frame.iloc[offset]["future_risk_state"]),
                "risk_score": round(float(test_score[offset]) * 100.0, 4),
                "risk_probability": round(float(test_score[offset]), 6) if probability_valid else None,
                "alert": bool(test_score[offset] >= threshold), "policy_threshold": round(float(threshold), 4),
                **{column: work.iloc[position][column] for column in outcomes},
            })
        test_start += int(test_size)
    return {
        "experiment": experiment, "features": features,
        "folds": pd.DataFrame(fold_rows), "predictions": pd.DataFrame(prediction_rows),
        "baselines": pd.DataFrame(baseline_rows), "coefficients": pd.DataFrame(coefficient_rows),
    }
