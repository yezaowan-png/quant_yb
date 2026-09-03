"""Diagnostics, stability checks, policy comparisons and automatic gates for market_risk_gate."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from analysis.market_risk_model import RiskExperiment, default_experiment_matrix, run_risk_experiment
from analysis.market_risk_state import build_market_risk_states, trailing_percentile


GATE_DECISIONS = (
    "continue_risk_gate_research",
    "stop_future_risk_prediction_use_state_monitor_only",
    "eligible_for_strategy_validation",
)


def _auc(actual: np.ndarray, score: np.ndarray) -> float | None:
    actual = np.asarray(actual, dtype=int)
    positives = int((actual == 1).sum())
    negatives = int((actual == 0).sum())
    if not positives or not negatives:
        return None
    ranks = pd.Series(score).rank(method="average").to_numpy()
    return float((ranks[actual == 1].sum() - positives * (positives + 1) / 2) / (positives * negatives))


def summarize_risk_experiment(result: dict[str, Any]) -> pd.DataFrame:
    folds = result["folds"]
    baselines = result["baselines"]
    predictions = result["predictions"]
    experiment: RiskExperiment = result["experiment"]
    if folds.empty:
        return pd.DataFrame([{"experiment": experiment.experiment, "status": "insufficient_data"}])
    primary = baselines[baselines["baseline"] == "large_decline_only"].set_index("fold")
    model_auc = folds.set_index("fold")["roc_auc"]
    aligned = pd.concat([model_auc.rename("model"), primary["roc_auc"].rename("baseline")], axis=1).dropna()
    probability_valid_ratio = folds["probability_valid"].astype(bool).mean()
    false_positives = predictions[(predictions["alert"]) & (predictions["actual_risk"] == 0)].copy()
    false_positives["year"] = pd.to_datetime(false_positives["trade_date"], errors="coerce").dt.year
    yearly_false = false_positives.groupby("year").size()
    lead_days = []
    actual = predictions["actual_risk"].astype(int).to_numpy()
    alert = predictions["alert"].astype(bool).to_numpy()
    for position in range(len(predictions)):
        if actual[position] == 1 and (position == 0 or actual[position - 1] == 0):
            start = max(0, position - int(experiment.horizon))
            prior = np.flatnonzero(alert[start : position + 1])
            lead_days.append(position - (start + int(prior[0])) if len(prior) else 0)
    summary = {
        "experiment": experiment.experiment, "horizon": experiment.horizon, "label": experiment.label,
        "feature_set": experiment.feature_set, "class_weight": experiment.class_weight,
        "calibration": experiment.calibration, "feature_count": len(result["features"]), "fold_count": len(folds),
        "oos_count": len(predictions), "risk_event_base_rate": round(float(predictions["actual_risk"].mean()), 4),
        "roc_auc": round(float(pd.to_numeric(folds["roc_auc"], errors="coerce").mean()), 4),
        "pr_auc": round(float(pd.to_numeric(folds["pr_auc"], errors="coerce").mean()), 4),
        "brier_score": round(float(pd.to_numeric(folds["brier_score"], errors="coerce").mean()), 6),
        "brier_skill": round(float(pd.to_numeric(folds["brier_skill"], errors="coerce").mean()), 4),
        "ece": round(float(pd.to_numeric(folds["ece"], errors="coerce").mean()), 4),
        "recall": round(float(pd.to_numeric(folds["recall"], errors="coerce").mean()), 4),
        "precision": round(float(pd.to_numeric(folds["precision"], errors="coerce").mean()), 4),
        "false_positive_rate": round(float(pd.to_numeric(folds["false_positive_rate"], errors="coerce").mean()), 4),
        "false_negative_rate": round(float(pd.to_numeric(folds["false_negative_rate"], errors="coerce").mean()), 4),
        "avg_false_positive_days_per_year": round(float(yearly_false.mean()), 2) if len(yearly_false) else 0.0,
        "avg_lead_warning_days": round(float(np.mean(lead_days)), 2) if lead_days else 0.0,
        "fold_win_rate_vs_frozen_large_decline": round(float((aligned["model"] > aligned["baseline"]).mean()), 4) if len(aligned) else None,
        "high_minus_low_q10": round(float(pd.to_numeric(folds["high_minus_low_q10"], errors="coerce").mean()), 6),
        "high_minus_low_max_drawdown": round(float(pd.to_numeric(folds["high_minus_low_max_drawdown"], errors="coerce").mean()), 6),
        "high_minus_low_large_decline_ratio": round(float(pd.to_numeric(folds["high_minus_low_large_decline_ratio"], errors="coerce").mean()), 6),
        "probability_valid_ratio": round(float(probability_valid_ratio), 4),
    }
    return pd.DataFrame([summary])


def risk_stability_tables(
    result: dict[str, Any],
    features: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    predictions = result["predictions"]
    if predictions.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    merged = predictions.merge(
        features[["trade_date", "realized_volatility_5d", "effective_stock_count"]].drop_duplicates("trade_date"),
        on="trade_date", how="left",
    )
    current_states = (
        features[["trade_date", "current_state"]]
        if "current_state" in features.columns
        else build_market_risk_states(features)[["trade_date", "current_state"]]
    )
    merged = merged.merge(current_states, on="trade_date", how="left")
    merged["year"] = pd.to_datetime(merged["trade_date"], errors="coerce").dt.year
    vol_rank = trailing_percentile(merged["realized_volatility_5d"])
    merged["volatility_regime"] = np.where(vol_rank <= 0.33, "low", np.where(vol_rank >= 0.67, "high", "middle"))
    merged["stock_count_group"] = pd.qcut(
        pd.to_numeric(merged["effective_stock_count"], errors="coerce"), 3,
        labels=["low_count", "middle_count", "high_count"], duplicates="drop",
    )
    year = merged["year"]
    merged["period"] = np.where(year <= 2015, "2011_2015", np.where(year <= 2020, "2016_2020", "2021_current"))

    def summarize(dimension: str) -> pd.DataFrame:
        rows = []
        for value, group in merged.groupby(dimension, observed=False):
            rows.append({
                "dimension": dimension, "value": str(value), "count": len(group),
                "risk_base_rate": round(float(group["actual_risk"].mean()), 4),
                "roc_auc": round(float(auc), 4) if (auc := _auc(group["actual_risk"].to_numpy(), group["risk_score"].to_numpy())) is not None else None,
                "alert_rate": round(float(group["alert"].mean()), 4),
                "effective_stock_count_median": round(float(pd.to_numeric(group["effective_stock_count"], errors="coerce").median()), 1),
            })
        return pd.DataFrame(rows)

    market_states = pd.concat(
        [summarize("volatility_regime"), summarize("current_state")], ignore_index=True
    )
    return summarize("year"), market_states, summarize("stock_count_group").pipe(
        lambda table: pd.concat([table, summarize("period")], ignore_index=True)
    )


def evaluate_strategy_risk_gate(
    result: dict[str, Any],
    strategy_returns: Mapping[str, pd.Series] | None,
) -> pd.DataFrame:
    predictions = result["predictions"]
    if predictions.empty or not strategy_returns:
        return pd.DataFrame()
    signal = predictions.set_index("trade_date")
    score = pd.to_numeric(signal["risk_score"], errors="coerce") / 100.0
    alert = signal["alert"].astype(bool)
    gate_exposure = pd.Series(np.where(score >= 0.80, 0.0, np.where(alert, 0.30, 1.0)), index=signal.index)
    trend_exposure = pd.Series(np.where(score >= 0.60, 0.5, 1.0), index=signal.index)
    breadth_exposure = pd.Series(np.where(alert, 0.5, 1.0), index=signal.index)
    exposures = {
        "A_unfiltered": pd.Series(1.0, index=signal.index),
        "B_index_trend": trend_exposure,
        "C_simple_breadth": breadth_exposure,
        "D_extreme_risk_gate": gate_exposure,
    }
    rows = []
    for strategy, returns in strategy_returns.items():
        daily = pd.to_numeric(returns, errors="coerce").copy()
        daily.index = pd.to_datetime(daily.index, errors="coerce").strftime("%Y-%m-%d")
        aligned = daily.reindex(signal.index)
        available = aligned.notna()
        if not available.any():
            continue
        aligned = aligned[available]
        executable_exposures = {
            policy: exposure.reindex(aligned.index).shift(1).fillna(0.0)
            for policy, exposure in exposures.items()
        }
        gate_executable = executable_exposures["D_extreme_risk_gate"]
        executable_exposures["E_random_matched_exposure"] = pd.Series(
            np.random.default_rng(20260713).permutation(gate_executable.to_numpy()),
            index=gate_executable.index,
        )
        for policy, executable in executable_exposures.items():
            filtered = aligned * executable
            equity = (1.0 + filtered).cumprod()
            drawdown = equity / equity.cummax() - 1.0
            annual = float(equity.iloc[-1] ** (252 / max(len(equity), 1)) - 1) if len(equity) else np.nan
            rows.append({
                "experiment": result["experiment"].experiment, "strategy": str(strategy), "policy": policy,
                "total_return": round(float(equity.iloc[-1] - 1), 6), "max_drawdown": round(float(drawdown.min()), 6),
                "calmar": round(annual / abs(float(drawdown.min())), 4) if float(drawdown.min()) else None,
                "worst_5d": round(float(filtered.rolling(5).sum().min()), 6),
                "worst_20d": round(float(filtered.rolling(20).sum().min()), 6),
                "tail_loss_q05": round(float(filtered.quantile(0.05)), 6),
                "average_exposure": round(float(executable.mean()), 4),
                "blocked_days": int((executable < 1.0).sum()),
                "blocked_day_actual_return": round(float(aligned[executable < 1.0].sum()), 6),
                "opportunity_cost": round(float((aligned - filtered).sum()), 6),
                "execution_lag_days": 1,
            })
    return pd.DataFrame(rows)


def experiment_gate(summary: pd.DataFrame) -> pd.DataFrame:
    row = summary.iloc[0]
    if str(row.get("status", "")) == "insufficient_data":
        return pd.DataFrame([
            {"gate": "sufficient_oos_data", "passed": False},
            {
                "gate": "automatic_decision", "passed": False,
                "decision": "stop_future_risk_prediction_use_state_monitor_only",
            },
        ])

    def number(name: str, default: float) -> float:
        value = pd.to_numeric(pd.Series([row.get(name)]), errors="coerce").iloc[0]
        return default if pd.isna(value) else float(value)

    checks = {
        "auc_at_least_057": number("roc_auc", 0) >= 0.57,
        "pr_auc_above_base_rate": number("pr_auc", 0) > number("risk_event_base_rate", 1),
        "tail_sort_direction": (
            number("high_minus_low_q10", 0) < 0
            and number("high_minus_low_max_drawdown", 0) < 0
            and number("high_minus_low_large_decline_ratio", 0) > 0
        ),
        "fold_win_rate_at_least_055": number("fold_win_rate_vs_frozen_large_decline", 0) >= 0.55,
    }
    continue_research = all(checks.values())
    eligible = continue_research and (
        number("roc_auc", 0) >= 0.60
        and number("fold_win_rate_vs_frozen_large_decline", 0) >= 0.70
        and number("brier_skill", -1) > 0
        and number("ece", 1) <= 0.10
    )
    # A single model cannot become strategy-eligible by itself. It can only be
    # marked as a candidate; the matrix later checks years, >=3 strategies and
    # the matched-random control before issuing the eligibility decision.
    decision = (
        "continue_risk_gate_research" if continue_research
        else "stop_future_risk_prediction_use_state_monitor_only"
    )
    return pd.DataFrame([
        {"gate": key, "passed": value} for key, value in checks.items()
    ] + [
        {"gate": "model_eligible_candidate", "passed": eligible},
        {"gate": "automatic_decision", "passed": continue_research, "decision": decision},
    ])


def run_experiment_matrix(
    frame: pd.DataFrame,
    features: pd.DataFrame,
    strategy_returns: Mapping[str, pd.Series] | None = None,
    experiments: list[RiskExperiment] | None = None,
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    summaries = []
    gates = []
    stability_features = features.copy()
    if "current_state" not in stability_features.columns:
        stability_features = stability_features.merge(
            build_market_risk_states(stability_features)[["trade_date", "current_state"]],
            on="trade_date", how="left", validate="one_to_one",
        )
    for experiment in experiments or default_experiment_matrix():
        result = run_risk_experiment(frame, experiment)
        summary = summarize_risk_experiment(result)
        gate = experiment_gate(summary)
        yearly, volatility, universe = risk_stability_tables(result, stability_features)
        strategies = evaluate_strategy_risk_gate(result, strategy_returns)
        results[experiment.experiment] = {
            **result, "summary": summary, "gate": gate, "yearly": yearly,
            "volatility": volatility, "universe": universe, "strategies": strategies,
        }
        summaries.append(summary)
        gates.append(gate.assign(experiment=experiment.experiment))
    summary_frame = pd.concat(summaries, ignore_index=True) if summaries else pd.DataFrame()
    gate_frame = pd.concat(gates, ignore_index=True) if gates else pd.DataFrame()
    core_names = ["E1", "E2", "E3", "E4", "E5"]
    core = summary_frame[summary_frame["experiment"].isin(core_names)].copy()
    core_failures = []
    for name in core_names:
        current = results.get(name)
        if current is None or current["summary"].empty:
            core_failures.append(True)
            continue
        row = current["summary"].iloc[0]
        if str(row.get("status", "")) == "insufficient_data":
            core_failures.append(True)
            continue
        auc_failed = float(pd.to_numeric(pd.Series([row.get("roc_auc")]), errors="coerce").fillna(0).iloc[0]) < 0.57
        fold_failed = float(pd.to_numeric(pd.Series([row.get("fold_win_rate_vs_frozen_large_decline")]), errors="coerce").fillna(0).iloc[0]) < 0.55
        gate_rows = current["gate"].set_index("gate")
        sorting_failed = not bool(gate_rows.loc["tail_sort_direction", "passed"])
        core_failures.append(auc_failed and sorting_failed and fold_failed)
    all_failed = bool(len(core) == 5 and all(core_failures))
    eligible_candidates = [
        item for item in results.values()
        if bool(item["gate"].set_index("gate").loc["model_eligible_candidate", "passed"])
    ]
    years_consistent = False
    three_strategies_consistent = False
    incremental_vs_random = False
    if eligible_candidates:
        candidate = max(
            eligible_candidates,
            key=lambda item: float(pd.to_numeric(item["summary"].iloc[0].get("roc_auc"), errors="coerce")),
        )
        yearly = candidate["yearly"].copy()
        year_rows = yearly[yearly.get("dimension", pd.Series(dtype=object)).astype(str) == "year"]
        year_auc = pd.to_numeric(year_rows.get("roc_auc"), errors="coerce").dropna()
        years_consistent = bool(len(year_auc) >= 3 and (year_auc > 0.50).mean() >= 0.60)
        strategies = candidate["strategies"].copy()
        if not strategies.empty:
            comparison = strategies.pivot(index="strategy", columns="policy", values=["max_drawdown", "calmar"])
            required = {
                ("max_drawdown", "A_unfiltered"), ("max_drawdown", "D_extreme_risk_gate"),
                ("max_drawdown", "E_random_matched_exposure"), ("calmar", "A_unfiltered"),
                ("calmar", "D_extreme_risk_gate"), ("calmar", "E_random_matched_exposure"),
            }
            if required.issubset(set(comparison.columns)):
                direction = (
                    (comparison[("max_drawdown", "D_extreme_risk_gate")] > comparison[("max_drawdown", "A_unfiltered")])
                    & (comparison[("calmar", "D_extreme_risk_gate")] > comparison[("calmar", "A_unfiltered")])
                )
                increment = (
                    (comparison[("max_drawdown", "D_extreme_risk_gate")] > comparison[("max_drawdown", "E_random_matched_exposure")])
                    & (comparison[("calmar", "D_extreme_risk_gate")] > comparison[("calmar", "E_random_matched_exposure")])
                )
                three_strategies_consistent = bool(len(direction) >= 3 and direction.mean() >= 2 / 3)
                incremental_vs_random = bool(len(increment) >= 3 and increment.mean() >= 2 / 3)
    strategy_validation_ready = bool(
        eligible_candidates and years_consistent and three_strategies_consistent and incremental_vs_random
    )
    # The permanent-stop rule is deliberately stricter than one experiment's
    # research gate: every R1-R5 label must fail AUC, sorting and fold baseline.
    final_decision = (
        "stop_future_risk_prediction_use_state_monitor_only" if all_failed else
        "eligible_for_strategy_validation" if strategy_validation_ready else
        "continue_risk_gate_research"
    )
    matrix_gates = pd.DataFrame([
        {"gate": "r1_r5_all_failed_stop_rule", "passed": all_failed},
        {"gate": "multiple_years_direction_consistent", "passed": years_consistent},
        {"gate": "at_least_three_strategy_classes", "passed": three_strategies_consistent},
        {"gate": "incremental_vs_matched_random", "passed": incremental_vs_random},
        {"gate": "matrix_automatic_decision", "passed": strategy_validation_ready, "decision": final_decision},
    ])
    gate_frame = pd.concat([gate_frame, matrix_gates.assign(experiment="MATRIX")], ignore_index=True)
    return {"results": results, "summary": summary_frame, "gates": gate_frame, "automatic_decision": final_decision}


def save_experiment_matrix(matrix: dict[str, Any], output_root: str | Path) -> Path:
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    matrix["summary"].to_csv(root / "experiment_matrix_summary.csv", index=False)
    matrix["gates"].to_csv(root / "experiment_matrix_gates.csv", index=False)
    pd.DataFrame([{"automatic_decision": matrix["automatic_decision"]}]).to_csv(
        root / "automatic_decision.csv", index=False
    )
    for experiment, result in matrix["results"].items():
        directory = root / experiment
        directory.mkdir(parents=True, exist_ok=True)
        for name in (
            "folds", "predictions", "baselines", "coefficients", "summary", "gate",
            "yearly", "volatility", "universe", "strategies",
        ):
            result[name].to_csv(directory / f"{name}.csv", index=False)
    return root
