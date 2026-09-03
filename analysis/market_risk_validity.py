"""Falsification tests for market_risk_gate state, prediction and decision utility."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from analysis.market_risk_labels import expanding_risk_labels
from analysis.market_risk_state import trailing_percentile


LEVELS = ("green", "yellow", "orange", "red")
LEVEL_SCORE = {level: position for position, level in enumerate(LEVELS)}
HORIZONS = (1, 5, 10, 20)
CRISES = {
    "2011_selloff": ("2011-07-01", "2012-01-31"),
    "2015_crash": ("2015-06-01", "2015-09-30"),
    "2016_circuit_breaker": ("2015-12-01", "2016-03-31"),
    "2018_bear": ("2018-01-01", "2018-12-31"),
    "2020_covid": ("2020-02-01", "2020-04-30"),
    "2022_drawdown": ("2022-01-01", "2022-10-31"),
    "2024_selloff": ("2024-01-01", "2024-02-29"),
}


def _auc(actual: pd.Series, score: pd.Series) -> float | None:
    joined = pd.DataFrame({"actual": actual, "score": score}).dropna()
    if joined.empty:
        return None
    y = joined["actual"].astype(int).to_numpy()
    positives = int((y == 1).sum())
    negatives = int((y == 0).sum())
    if not positives or not negatives:
        return None
    ranks = joined["score"].rank(method="average").to_numpy()
    return float((ranks[y == 1].sum() - positives * (positives + 1) / 2) / (positives * negatives))


def _strategy_stats(returns: pd.Series) -> dict[str, float | None]:
    values = pd.to_numeric(returns, errors="coerce").dropna()
    if values.empty:
        return {"total_return": None, "max_drawdown": None, "calmar": None, "tail_loss_q05": None}
    equity = (1.0 + values).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    annual = float(equity.iloc[-1] ** (252 / max(len(equity), 1)) - 1.0)
    maximum = float(drawdown.min())
    return {
        "total_return": float(equity.iloc[-1] - 1.0),
        "max_drawdown": maximum,
        "calmar": annual / abs(maximum) if maximum else None,
        "tail_loss_q05": float(values.quantile(0.05)),
    }


def measurement_validity(features: pd.DataFrame, policies: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = policies[["trade_date", "risk_level"]].merge(features, on="trade_date", how="inner")
    definitions = {
        "current_large_decline_ratio": "higher",
        "cross_section_dispersion": "higher",
        "realized_volatility_5d": "higher",
        "normalized_ad": "lower",
        "normalized_nhnl": "lower",
        "pct_above_ma20": "lower",
        "new_low_ratio": "higher",
        "limit_down_ratio": "higher",
    }
    rows: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    for metric, risk_direction in definitions.items():
        means = frame.groupby("risk_level")[metric].mean().reindex(LEVELS)
        transformed = -means if risk_direction == "lower" else means
        pairs = [
            bool(transformed.iloc[position + 1] >= transformed.iloc[position])
            for position in range(len(LEVELS) - 1)
            if pd.notna(transformed.iloc[position : position + 2]).all()
        ]
        checks.append({
            "metric": metric, "risk_direction": risk_direction,
            "adjacent_pairs_correct": int(sum(pairs)), "adjacent_pairs_total": len(pairs),
            "monotonic_ratio": float(np.mean(pairs)) if pairs else None,
            "measurement_direction_passed": bool(pairs and np.mean(pairs) >= 2 / 3),
        })
        for level in LEVELS:
            rows.append({
                "risk_level": level, "level_order": LEVEL_SCORE[level], "metric": metric,
                "mean": means.get(level), "median": frame.loc[frame["risk_level"] == level, metric].median(),
                "sample_count": int((frame["risk_level"] == level).sum()),
            })
    return pd.DataFrame(rows), pd.DataFrame(checks)


def predictive_validity(
    outcomes: pd.DataFrame,
    policies: pd.DataFrame,
    horizons: tuple[int, ...] = HORIZONS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = policies[["trade_date", "risk_level"]].merge(outcomes, on="trade_date", how="inner")
    metric_templates = {
        "future_median_return": "lower",
        "future_equal_weight_return": "lower",
        "future_return_q10": "lower",
        "future_median_max_drawdown": "lower",
        "future_large_decline_ratio": "higher",
        "future_stock_win_rate": "lower",
    }
    rows: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    for horizon in horizons:
        for metric, risk_direction in metric_templates.items():
            column = f"{metric}_{int(horizon)}d"
            if column not in frame:
                continue
            means = frame.groupby("risk_level")[column].mean().reindex(LEVELS)
            transformed = -means if risk_direction == "lower" else means
            pairs = [
                bool(transformed.iloc[position + 1] >= transformed.iloc[position])
                for position in range(len(LEVELS) - 1)
                if pd.notna(transformed.iloc[position : position + 2]).all()
            ]
            checks.append({
                "horizon": horizon, "metric": metric, "risk_direction": risk_direction,
                "adjacent_pairs_correct": int(sum(pairs)), "adjacent_pairs_total": len(pairs),
                "monotonic_ratio": float(np.mean(pairs)) if pairs else None,
                "predictive_direction_passed": bool(pairs and np.mean(pairs) >= 2 / 3),
            })
            for level in LEVELS:
                selected = frame[frame["risk_level"] == level][column]
                rows.append({
                    "horizon": horizon, "risk_level": level, "level_order": LEVEL_SCORE[level],
                    "metric": metric, "mean": selected.mean(), "median": selected.median(),
                    "sample_count": int(selected.notna().sum()),
                })
    return pd.DataFrame(rows), pd.DataFrame(checks)


def build_risk_episodes(policies: pd.DataFrame, cooldown: int = 10) -> pd.DataFrame:
    """Enter on orange/red, end on the first return to green, then merge cooldown recurrences."""
    work = policies.sort_values("trade_date").reset_index(drop=True)
    raw: list[dict[str, Any]] = []
    position = 0
    while position < len(work):
        if str(work.iloc[position]["risk_level"]) not in {"orange", "red"}:
            position += 1
            continue
        start = position
        position += 1
        while position < len(work) and str(work.iloc[position]["risk_level"]) != "green":
            position += 1
        end = min(position, len(work) - 1)
        raw.append({"start_position": start, "end_position": end})
        position = end + 1
    merged: list[dict[str, Any]] = []
    for episode in raw:
        if merged and episode["start_position"] - merged[-1]["end_position"] <= int(cooldown):
            merged[-1]["end_position"] = episode["end_position"]
        else:
            merged.append(episode.copy())
    rows = []
    for episode_id, episode in enumerate(merged, start=1):
        start = int(episode["start_position"])
        end = int(episode["end_position"])
        levels = work.iloc[start : end + 1]["risk_level"].astype(str)
        rows.append({
            "episode_id": episode_id,
            "episode_start": str(work.iloc[start]["trade_date"]),
            "episode_end": str(work.iloc[end]["trade_date"]),
            "start_position": start, "end_position": end,
            "duration_days": end - start + 1,
            "start_year": int(str(work.iloc[start]["trade_date"])[:4]),
            "max_risk_level": "red" if (levels == "red").any() else "orange",
            "cooldown_days": int(cooldown),
        })
    return pd.DataFrame(rows)


def build_boolean_episodes(dates: pd.Series, flags: pd.Series, cooldown: int = 0) -> pd.DataFrame:
    policies = pd.DataFrame({
        "trade_date": dates.astype(str),
        "risk_level": np.where(flags.fillna(False).astype(bool), "orange", "green"),
    })
    return build_risk_episodes(policies, cooldown=cooldown)


def episode_exposure(
    policies: pd.DataFrame,
    episodes: pd.DataFrame,
    random_episodes: pd.DataFrame | None = None,
) -> pd.Series:
    work = policies.sort_values("trade_date").reset_index(drop=True)
    exposure = pd.Series(1.0, index=work.index, dtype="float64")
    source = episodes.set_index("episode_id") if not episodes.empty else pd.DataFrame()
    target = episodes if random_episodes is None else random_episodes
    for _, row in target.iterrows():
        start = int(row["start_position"])
        end = int(row["end_position"])
        template_id = int(row.get("template_episode_id", row.get("episode_id")))
        template = source.loc[template_id]
        original = pd.to_numeric(
            work.iloc[int(template["start_position"]) : int(template["end_position"]) + 1]["position_cap"],
            errors="coerce",
        ).fillna(1.0).to_numpy()
        length = end - start + 1
        exposure.iloc[start : end + 1] = original[:length]
    exposure.index = work["trade_date"].astype(str)
    return exposure


def generate_block_random_episodes(
    dates: pd.Series,
    episodes: pd.DataFrame,
    simulations: int = 1000,
    block_size: int = 5,
    cooldown: int = 10,
    seed: int = 20260713,
) -> list[pd.DataFrame]:
    if simulations < 1000:
        raise ValueError("区块随机检验至少需要1000组模拟")
    if block_size < 5:
        raise ValueError("区块随机长度至少为5个交易日")
    if episodes.empty:
        return [episodes.copy() for _ in range(simulations)]
    date_values = pd.to_datetime(dates, errors="coerce")
    years = date_values.dt.year.to_numpy()
    rng = np.random.default_rng(seed)
    results: list[pd.DataFrame] = []
    templates = episodes.to_dict("records")
    for simulation in range(int(simulations)):
        placed = []
        for attempt in range(200):
            placed = []
            occupied: list[tuple[int, int]] = []
            # Long episodes first avoids fragmenting dense years such as 2020.
            year_order = rng.permutation(sorted({int(item["start_year"]) for item in templates}))
            ordered: list[dict[str, Any]] = []
            for year in year_order:
                current = [item for item in templates if int(item["start_year"]) == int(year)]
                random_tie = {int(item["episode_id"]): float(rng.random()) for item in current}
                ordered.extend(sorted(
                    current,
                    key=lambda item: (-int(item["duration_days"]), random_tie[int(item["episode_id"])]),
                ))
            failed = False
            for template in ordered:
                duration = int(template["duration_days"])
                year = int(template["start_year"])
                candidates = np.flatnonzero(years == year)
                candidates = candidates[candidates + duration < len(dates)]
                offset = int(rng.integers(0, block_size))
                block_candidates = candidates[offset::block_size]
                rng.shuffle(block_candidates)

                def available(start: int, enforce_cooldown: bool = True) -> bool:
                    end = start + duration - 1
                    padding = int(cooldown) if enforce_cooldown else 0
                    return not any(start <= right + padding and end >= left - padding for left, right in occupied)

                chosen = next((int(item) for item in block_candidates if available(int(item))), None)
                if chosen is None and attempt >= 100:
                    # Preserve count/year/duration and non-overlap; cooldown is a
                    # real-signal definition, not a required random spacing.
                    shuffled = candidates.copy()
                    rng.shuffle(shuffled)
                    chosen = next((int(item) for item in shuffled if available(int(item), False)), None)
                if chosen is None:
                    failed = True
                    break
                end = chosen + duration - 1
                occupied.append((chosen, end))
                placed.append({
                    "episode_id": len(placed) + 1,
                    "template_episode_id": int(template["episode_id"]),
                    "episode_start": str(dates.iloc[chosen]), "episode_end": str(dates.iloc[end]),
                    "start_position": chosen, "end_position": end, "duration_days": duration,
                    "start_year": year, "cooldown_days": int(cooldown), "simulation": simulation,
                })
            if not failed and len(placed) == len(templates):
                break
        if len(placed) != len(templates):
            raise RuntimeError("区块随机episode在200次重启后仍无法保持数量、年份、时长和非重叠约束")
        results.append(pd.DataFrame(placed).sort_values("start_position").reset_index(drop=True))
    return results


def frozen_simple_rule_alerts(features: pd.DataFrame, index_df: pd.DataFrame) -> pd.DataFrame:
    frame = features.sort_values("trade_date").reset_index(drop=True).copy()
    output = frame[["trade_date"]].copy()

    def threshold(column: str, quantile: float) -> pd.Series:
        values = pd.to_numeric(frame[column], errors="coerce")
        return values.rolling(756, min_periods=252).quantile(quantile).shift(1)

    output["normalized_ad_p10"] = frame["normalized_ad"] < threshold("normalized_ad", 0.10)
    output["normalized_nhnl_p10"] = frame["normalized_nhnl"] < threshold("normalized_nhnl", 0.10)
    output["large_decline_ratio_p90"] = frame["current_large_decline_ratio"] > threshold("current_large_decline_ratio", 0.90)
    output["realized_volatility_p90"] = frame["realized_volatility_5d"] > threshold("realized_volatility_5d", 0.90)
    output["index_return_5d_p10"] = frame["index_return_5d"] < threshold("index_return_5d", 0.10)
    index = index_df[["date", "close"]].copy()
    index["trade_date"] = pd.to_datetime(index["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    index["close"] = pd.to_numeric(index["close"], errors="coerce")
    index["index_below_ma20"] = index["close"] < index["close"].rolling(20, min_periods=20).mean()
    output = output.merge(index[["trade_date", "index_below_ma20"]], on="trade_date", how="left")
    for column in output.columns[1:]:
        output[column] = output[column].fillna(False).astype(bool)
    return output


def _actual_event_episodes(frame: pd.DataFrame) -> pd.DataFrame:
    return build_boolean_episodes(frame["trade_date"], frame["actual_risk"], cooldown=0)


def episode_metrics(
    frame: pd.DataFrame,
    episodes: pd.DataFrame,
    horizon: int,
) -> tuple[dict[str, Any], pd.DataFrame]:
    work = frame.reset_index(drop=True)
    signal_mask = pd.Series(False, index=work.index)
    for _, episode in episodes.iterrows():
        signal_mask.iloc[int(episode["start_position"]) : int(episode["end_position"]) + 1] = True
    actual_episodes = _actual_event_episodes(work)
    details: list[dict[str, Any]] = []
    lead_days: list[int] = []
    hit_actual_ids: set[int] = set()
    for _, signal in episodes.iterrows():
        start = int(signal["start_position"])
        end = int(signal["end_position"])
        eligible = actual_episodes[
            (actual_episodes["start_position"] >= start)
            & (actual_episodes["start_position"] <= end + int(horizon))
        ]
        hit = not eligible.empty
        lead = None
        if hit:
            first = eligible.iloc[0]
            lead = int(first["start_position"] - start)
            lead_days.append(lead)
            hit_actual_ids.update(eligible["episode_id"].astype(int).tolist())
        details.append({
            **signal.to_dict(), "hit": hit, "false_alarm": not hit,
            "lead_days": lead,
            "future_q10": work.iloc[start].get(f"future_return_q10_{horizon}d"),
            "future_max_drawdown": work.iloc[start].get(f"future_median_max_drawdown_{horizon}d"),
            "future_large_decline_ratio": work.iloc[start].get(f"future_large_decline_ratio_{horizon}d"),
        })
    detail_frame = pd.DataFrame(details)
    actual_days = work["actual_risk"].fillna(False).astype(bool)
    q10 = pd.to_numeric(work[f"future_return_q10_{horizon}d"], errors="coerce")
    worst_cut = q10.quantile(0.05)
    worst = q10 <= worst_cut
    years = max(pd.to_datetime(work["trade_date"]).dt.year.nunique(), 1)
    hit_count = int(detail_frame["hit"].sum()) if not detail_frame.empty else 0
    metrics = {
        "risk_event_base_rate": float(actual_days.mean()),
        "episode_count": int(len(episodes)),
        "episode_precision": hit_count / len(episodes) if len(episodes) else None,
        "episode_recall": len(hit_actual_ids) / len(actual_episodes) if len(actual_episodes) else None,
        "false_alarms_per_year": int((~detail_frame["hit"]).sum()) / years if not detail_frame.empty else 0.0,
        "missed_extreme_events": max(int(len(actual_episodes) - len(hit_actual_ids)), 0),
        "average_lead_days": float(np.mean(lead_days)) if lead_days else None,
        "median_lead_days": float(np.median(lead_days)) if lead_days else None,
        "tail_day_capture_rate": float((signal_mask & actual_days).sum() / actual_days.sum()) if actual_days.sum() else None,
        "worst_5pct_day_capture_rate": float((signal_mask & worst).sum() / worst.sum()) if worst.sum() else None,
        "average_episode_future_q10": float(pd.to_numeric(detail_frame.get("future_q10"), errors="coerce").mean()) if not detail_frame.empty else None,
        "average_episode_max_drawdown": float(pd.to_numeric(detail_frame.get("future_max_drawdown"), errors="coerce").mean()) if not detail_frame.empty else None,
        "average_episode_large_decline_ratio": float(pd.to_numeric(detail_frame.get("future_large_decline_ratio"), errors="coerce").mean()) if not detail_frame.empty else None,
    }
    return metrics, detail_frame


def strategy_decision_utility(
    dates: pd.Series,
    exposure: pd.Series,
    strategy_returns: Mapping[str, pd.Series] | None,
    strategy_trades: Mapping[str, pd.DataFrame] | None = None,
    policy_name: str = "risk_gate",
    target_average_exposure: Mapping[str, float] | None = None,
) -> pd.DataFrame:
    if not strategy_returns:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    date_index = dates.astype(str)
    exposure = exposure.reindex(date_index).fillna(1.0)
    for strategy, returns in strategy_returns.items():
        daily = pd.to_numeric(returns, errors="coerce").copy()
        daily.index = pd.to_datetime(daily.index, errors="coerce").strftime("%Y-%m-%d")
        aligned = daily.reindex(date_index)
        available = aligned.notna()
        if not available.any():
            continue
        aligned = aligned[available]
        executable = exposure.reindex(aligned.index).shift(1).fillna(1.0)
        raw_average = float(executable.mean())
        target = (target_average_exposure or {}).get(strategy)
        if target is not None and np.isfinite(target):
            target = float(np.clip(target, 0.0, 1.0))
            if raw_average > target and raw_average > 0:
                executable = executable * (target / raw_average)
            elif raw_average < target and raw_average < 1:
                executable = executable + (1.0 - executable) * (
                    (target - raw_average) / (1.0 - raw_average)
                )
        filtered = aligned * executable
        baseline = _strategy_stats(aligned)
        gated = _strategy_stats(filtered)
        blocked_dates = set(executable.index[executable < 1.0])
        trades = (strategy_trades or {}).get(strategy, pd.DataFrame())
        blocked = trades[trades["trade_date"].astype(str).isin(blocked_dates)] if not trades.empty else pd.DataFrame()
        realized = pd.to_numeric(blocked.get("realized_return"), errors="coerce") if not blocked.empty else pd.Series(dtype=float)
        rows.append({
            "strategy": strategy, "policy": policy_name,
            "average_exposure": float(executable.mean()),
            "raw_average_exposure": raw_average,
            "exposure_matching_adjustment": float(executable.mean() - raw_average),
            **{f"unfiltered_{key}": value for key, value in baseline.items()},
            **{f"gated_{key}": value for key, value in gated.items()},
            "max_drawdown_improvement_pct": (
                (gated["max_drawdown"] - baseline["max_drawdown"]) / abs(baseline["max_drawdown"])
                if baseline["max_drawdown"] else None
            ),
            "calmar_improvement_pct": (
                (gated["calmar"] - baseline["calmar"]) / abs(baseline["calmar"])
                if baseline["calmar"] else None
            ),
            "opportunity_cost": float((aligned - filtered).sum()),
            "blocked_trade_count": int(len(blocked)),
            "blocked_trade_realized_return": float(realized.sum()) if realized.notna().any() else None,
            "execution_lag_days": 1,
        })
    return pd.DataFrame(rows)


def _subset_stability_row(
    frame: pd.DataFrame,
    mask: pd.Series,
    dimension: str,
    value: str,
    horizon: int,
) -> dict[str, Any]:
    selected = frame[mask.fillna(False)].copy()
    score = selected["risk_level"].map(LEVEL_SCORE)
    high = selected["risk_level"].isin(["orange", "red"])
    low = selected["risk_level"] == "green"
    q10 = pd.to_numeric(selected[f"future_return_q10_{horizon}d"], errors="coerce")
    return {
        "dimension": dimension, "value": value, "count": len(selected),
        "risk_event_base_rate": float(selected["actual_risk"].mean()) if len(selected) else None,
        "roc_auc": _auc(selected["actual_risk"], score),
        "high_minus_green_q10": float(q10[high].mean() - q10[low].mean()) if high.any() and low.any() else None,
    }


def stability_diagnostics(frame: pd.DataFrame, index_df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    work = frame.copy()
    dates = pd.to_datetime(work["trade_date"], errors="coerce")
    rows: list[dict[str, Any]] = []
    for crisis, (start, end) in CRISES.items():
        mask = ~dates.between(pd.Timestamp(start), pd.Timestamp(end))
        rows.append(_subset_stability_row(work, mask, "leave_one_crisis_out", crisis, horizon))
    for year in sorted(dates.dt.year.dropna().unique()):
        rows.append(_subset_stability_row(work, dates.dt.year != year, "leave_one_year_out", str(int(year)), horizon))
    for name, start, end in (
        ("2011_2015", 2011, 2015), ("2016_2020", 2016, 2020), ("2021_current", 2021, 9999),
    ):
        rows.append(_subset_stability_row(work, dates.dt.year.between(start, end), "period", name, horizon))
    vol_rank = trailing_percentile(work["realized_volatility_5d"])
    rows.append(_subset_stability_row(work, vol_rank <= 0.33, "volatility", "low", horizon))
    rows.append(_subset_stability_row(work, vol_rank >= 0.67, "volatility", "high", horizon))
    index = index_df[["date", "close"]].copy()
    index["trade_date"] = pd.to_datetime(index["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    index["return_60d"] = pd.to_numeric(index["close"], errors="coerce").pct_change(60, fill_method=None)
    work = work.merge(index[["trade_date", "return_60d"]], on="trade_date", how="left")
    regimes = np.where(work["return_60d"] >= 0.10, "bull", np.where(work["return_60d"] <= -0.10, "bear", "sideways"))
    for regime in ("bull", "bear", "sideways"):
        rows.append(_subset_stability_row(work, pd.Series(regimes == regime, index=work.index), "market_regime", regime, horizon))
    for offset in range(5):
        rows.append(_subset_stability_row(
            work, pd.Series(np.arange(len(work)) % 5 == offset, index=work.index),
            "non_overlapping_horizon_offset", str(offset), horizon,
        ))
    return pd.DataFrame(rows)


def _empirical_comparison(real: dict[str, float], random: pd.DataFrame) -> pd.DataFrame:
    directions = {
        "future_q10": "lower", "future_max_drawdown": "lower",
        "large_decline_ratio": "higher", "strategy_max_drawdown": "higher",
        "strategy_calmar": "higher", "opportunity_cost": "lower",
    }
    rows = []
    for metric, direction in directions.items():
        actual = real.get(metric)
        values = pd.to_numeric(random.get(metric), errors="coerce").dropna()
        if actual is None or pd.isna(actual) or values.empty:
            percentile = p_value = None
        else:
            percentile = float((values <= actual).mean() * 100.0)
            if direction == "lower":
                p_value = float(((values <= actual).sum() + 1) / (len(values) + 1))
            else:
                p_value = float(((values >= actual).sum() + 1) / (len(values) + 1))
        rows.append({
            "metric": metric, "better_direction": direction, "real_value": actual,
            "random_mean": float(values.mean()) if len(values) else None,
            "random_std": float(values.std(ddof=0)) if len(values) else None,
            "real_percentile": percentile, "empirical_p_value": p_value,
            "simulation_count": int(len(values)),
        })
    return pd.DataFrame(rows)


def run_risk_gate_validity(
    features: pd.DataFrame,
    outcomes: pd.DataFrame,
    policies: pd.DataFrame,
    index_df: pd.DataFrame,
    strategy_returns: Mapping[str, pd.Series] | None = None,
    strategy_trades: Mapping[str, pd.DataFrame] | None = None,
    horizon: int = 5,
    simulations: int = 1000,
    cooldown: int = 10,
    block_size: int = 5,
    seed: int = 20260713,
) -> dict[str, Any]:
    measurement, measurement_checks = measurement_validity(features, policies)
    predictive, predictive_checks = predictive_validity(outcomes, policies)
    labels = expanding_risk_labels(outcomes, int(horizon))[["trade_date", "R2"]].rename(columns={"R2": "actual_risk"})
    frame = (
        policies[["trade_date", "risk_level", "position_cap"]]
        .merge(features, on="trade_date", how="inner")
        .merge(outcomes, on="trade_date", how="inner")
        .merge(labels, on="trade_date", how="left")
    )
    frame["actual_risk"] = frame["actual_risk"].fillna(False).astype(bool)
    episodes = build_risk_episodes(policies, cooldown=cooldown)
    core, episode_details = episode_metrics(frame, episodes, int(horizon))
    real_exposure = episode_exposure(policies, episodes)
    decision_utility = strategy_decision_utility(
        frame["trade_date"], real_exposure, strategy_returns, strategy_trades, "complex_risk_gate",
    )
    core["opportunity_cost"] = float(decision_utility["opportunity_cost"].mean()) if not decision_utility.empty else None
    core["blocked_trade_count"] = int(decision_utility["blocked_trade_count"].sum()) if not decision_utility.empty else 0
    core["blocked_trade_realized_return"] = float(decision_utility["blocked_trade_realized_return"].sum()) if not decision_utility.empty else None
    core_metrics = pd.DataFrame([core])

    rules = frozen_simple_rule_alerts(features, index_df)
    comparison_rows = [{
        "signal": "complex_risk_gate", "roc_auc": _auc(frame["actual_risk"], frame["risk_level"].map(LEVEL_SCORE)),
        **core,
    }]
    for rule in rules.columns[1:]:
        rule_episodes = build_boolean_episodes(rules["trade_date"], rules[rule], cooldown=cooldown)
        rule_metrics, _ = episode_metrics(frame, rule_episodes, int(horizon))
        comparison_rows.append({
            "signal": rule, "roc_auc": _auc(frame["actual_risk"], rules[rule].astype(int)), **rule_metrics,
        })
    simple_rules = pd.DataFrame(comparison_rows)

    random_sets = generate_block_random_episodes(
        frame["trade_date"], episodes, simulations=simulations, block_size=block_size,
        cooldown=cooldown, seed=seed,
    )
    random_rows: list[dict[str, Any]] = []
    random_strategy_rows: list[pd.DataFrame] = []
    target_exposure = (
        decision_utility.set_index("strategy")["average_exposure"].astype(float).to_dict()
        if not decision_utility.empty else {}
    )
    for simulation, random_episodes in enumerate(random_sets):
        random_metrics, _ = episode_metrics(frame, random_episodes, int(horizon))
        random_exposure = episode_exposure(policies, episodes, random_episodes=random_episodes)
        utility = strategy_decision_utility(
            frame["trade_date"], random_exposure, strategy_returns, None,
            f"random_{simulation}", target_average_exposure=target_exposure,
        )
        if not utility.empty:
            utility["simulation"] = simulation
            random_strategy_rows.append(utility)
        random_rows.append({
            "simulation": simulation,
            "episode_count": len(random_episodes),
            "future_q10": random_metrics["average_episode_future_q10"],
            "future_max_drawdown": random_metrics["average_episode_max_drawdown"],
            "large_decline_ratio": random_metrics["average_episode_large_decline_ratio"],
            "strategy_max_drawdown": float(utility["gated_max_drawdown"].mean()) if not utility.empty else None,
            "strategy_calmar": float(utility["gated_calmar"].mean()) if not utility.empty else None,
            "opportunity_cost": float(utility["opportunity_cost"].mean()) if not utility.empty else None,
            "average_exposure": float(utility["average_exposure"].mean()) if not utility.empty else float(random_exposure.mean()),
        })
    random_distribution = pd.DataFrame(random_rows)
    random_strategy = pd.concat(random_strategy_rows, ignore_index=True) if random_strategy_rows else pd.DataFrame()
    real_values = {
        "future_q10": core["average_episode_future_q10"],
        "future_max_drawdown": core["average_episode_max_drawdown"],
        "large_decline_ratio": core["average_episode_large_decline_ratio"],
        "strategy_max_drawdown": float(decision_utility["gated_max_drawdown"].mean()) if not decision_utility.empty else None,
        "strategy_calmar": float(decision_utility["gated_calmar"].mean()) if not decision_utility.empty else None,
        "opportunity_cost": core["opportunity_cost"],
    }
    random_comparison = _empirical_comparison(real_values, random_distribution)
    stability = stability_diagnostics(frame, index_df, int(horizon))

    measurement_pass = bool(measurement_checks["measurement_direction_passed"].mean() >= 0.75)
    horizon_checks = predictive_checks[predictive_checks["horizon"] == int(horizon)]
    predictive_pass = bool(horizon_checks["predictive_direction_passed"].mean() >= 2 / 3)
    p_values = random_comparison.set_index("metric")["empirical_p_value"]
    market_random_pass = sum(bool(p_values.get(metric, 1.0) <= 0.05) for metric in (
        "future_q10", "future_max_drawdown", "large_decline_ratio",
    )) >= 2
    utility_random_pass = bool(
        p_values.get("strategy_max_drawdown", 1.0) <= 0.05
        and p_values.get("strategy_calmar", 1.0) <= 0.05
    )
    complex_auc = float(comparison_rows[0]["roc_auc"] or 0.0)
    if complex_auc >= 0.57 and market_random_pass and utility_random_pass:
        qualification = "soft_gate_candidate"
    elif market_random_pass:
        qualification = "warning_only"
    else:
        qualification = "state_monitor_only"
    qualification_audit = pd.DataFrame([{
        "qualification": qualification,
        "measurement_validity_passed": measurement_pass,
        "predictive_monotonicity_passed": predictive_pass,
        "complex_oos_auc": complex_auc,
        "auc_at_least_057": complex_auc >= 0.57,
        "future_risk_better_than_random": market_random_pass,
        "same_exposure_strategy_utility_better_than_random": utility_random_pass,
        "strategy_count": int(decision_utility["strategy"].nunique()) if not decision_utility.empty else 0,
        "hard_gate_candidate_allowed": False,
        "simulation_count": int(simulations), "block_size": int(block_size), "cooldown": int(cooldown),
    }])
    return {
        "measurement": measurement, "measurement_checks": measurement_checks,
        "predictive": predictive, "predictive_checks": predictive_checks,
        "episodes": episodes, "episode_details": episode_details, "core_metrics": core_metrics,
        "simple_rules": simple_rules, "decision_utility": decision_utility,
        "random_distribution": random_distribution, "random_strategy": random_strategy,
        "random_comparison": random_comparison, "stability": stability,
        "qualification": qualification_audit,
    }


def save_risk_gate_validity(result: dict[str, Any], output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    for name, frame in result.items():
        if isinstance(frame, pd.DataFrame):
            frame.to_csv(root / f"{name}.csv", index=False)
    return root
