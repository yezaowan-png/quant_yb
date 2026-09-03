"""Deterministic state helpers for market-structure description system v2.

This module deliberately contains no downloader, report, forecasting, position,
order, or LLM dependency.  Its inputs are point-in-time fact series and its
outputs are descriptive states only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd


UNKNOWN = "unknown"


def finite(value: Any) -> float | None:
    """Return a finite float, otherwise ``None``."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result) else None


@dataclass(frozen=True)
class StateTrackerConfig:
    """Hysteresis settings shared by all v2 state dimensions."""

    min_confirm_days: int = 2
    min_hold_days: int = 2
    deadband: float = 0.0
    extreme_states: tuple[str, ...] = ()


class StateTracker:
    """Stabilize a raw daily state sequence and describe the latest episode.

    A normal transition needs consecutive confirmation and observes a minimum
    holding period.  Explicit extreme states may switch immediately.  Missing
    evidence is never converted into a neutral state: ``unknown`` propagates on
    the affected date.
    """

    def __init__(self, config: StateTrackerConfig | None = None) -> None:
        self.config = config or StateTrackerConfig()

    def track(
        self,
        dates: Iterable[Any],
        raw_states: Iterable[Any],
        *,
        dimension: str,
    ) -> dict[str, Any]:
        date_values = [pd.to_datetime(value, errors="coerce") for value in dates]
        state_values = [str(value) if value not in {None, "", "nan"} else UNKNOWN for value in raw_states]
        if len(date_values) != len(state_values):
            raise ValueError("StateTracker dates/raw_states length mismatch")
        if not state_values:
            return self._empty(dimension)

        stable: str | None = None
        candidate: str | None = None
        candidate_count = 0
        held = 0
        previous_stable: str | None = None
        transition_dates: list[pd.Timestamp] = []
        history: list[dict[str, Any]] = []

        for date, raw in zip(date_values, state_values):
            valid_date = date if pd.notna(date) else None
            transitioned = False
            if raw == UNKNOWN:
                output = UNKNOWN
                candidate = None
                candidate_count = 0
                held = 0
            elif stable is None or stable == UNKNOWN:
                stable = raw
                output = stable
                held = 1
                candidate = None
                candidate_count = 0
            elif raw == stable:
                output = stable
                held += 1
                candidate = None
                candidate_count = 0
            else:
                if candidate == raw:
                    candidate_count += 1
                else:
                    candidate = raw
                    candidate_count = 1
                fast = raw in set(self.config.extreme_states)
                confirmed = fast or candidate_count >= max(1, self.config.min_confirm_days)
                hold_satisfied = fast or held >= max(1, self.config.min_hold_days)
                if confirmed and hold_satisfied:
                    previous_stable = stable
                    stable = raw
                    output = stable
                    held = 1
                    transitioned = True
                    candidate = None
                    candidate_count = 0
                    if valid_date is not None:
                        transition_dates.append(valid_date)
                else:
                    output = stable
                    held += 1
            history.append(
                {
                    "trade_date": valid_date.strftime("%Y-%m-%d") if valid_date is not None else None,
                    "raw_state": raw,
                    "state": output,
                    "transitioned": transitioned,
                }
            )

        latest_output = history[-1]["state"]
        if latest_output == UNKNOWN:
            duration = 0
            start_date = None
        else:
            duration = 0
            start_date = None
            for row in reversed(history):
                if row["state"] != latest_output:
                    break
                duration += 1
                start_date = row["trade_date"]

        transition_count_20 = sum(bool(row["transitioned"]) for row in history[-20:])
        transition_count_60 = sum(bool(row["transitioned"]) for row in history[-60:])
        if latest_output == UNKNOWN:
            stability = UNKNOWN
        elif transition_count_20 <= 1:
            stability = "stable"
        elif transition_count_20 <= 3:
            stability = "rotating"
        else:
            stability = "unstable"
        last_transition = transition_dates[-1] if transition_dates else None
        latest_date = next((value for value in reversed(date_values) if pd.notna(value)), None)
        days_since = None
        if last_transition is not None and latest_date is not None:
            positions = [i for i, row in enumerate(history) if row["trade_date"] == last_transition.strftime("%Y-%m-%d")]
            days_since = len(history) - 1 - positions[-1] if positions else None
        return {
            "dimension": dimension,
            "state": latest_output,
            "current_state": latest_output,
            "state_start_date": start_date,
            "duration_trading_days": duration,
            "duration_days": duration,
            "previous_state": previous_stable,
            "last_transition_date": last_transition.strftime("%Y-%m-%d") if last_transition is not None else None,
            "transition_date": last_transition.strftime("%Y-%m-%d") if last_transition is not None else None,
            "days_since_transition": days_since,
            "days_since_last_change": days_since,
            "transition_count_20d": transition_count_20,
            "transition_count_60d": transition_count_60,
            "stability": stability,
            "stability_score": max(0.0, 1.0 - transition_count_20 / 5.0) if latest_output != UNKNOWN else None,
            "parameters": {
                "min_confirm_days": self.config.min_confirm_days,
                "min_hold_days": self.config.min_hold_days,
                "deadband": self.config.deadband,
                "extreme_states": list(self.config.extreme_states),
            },
            "history": history,
        }

    @staticmethod
    def _empty(dimension: str) -> dict[str, Any]:
        return {
            "dimension": dimension,
            "state": UNKNOWN,
            "current_state": UNKNOWN,
            "state_start_date": None,
            "duration_trading_days": 0,
            "duration_days": 0,
            "previous_state": None,
            "last_transition_date": None,
            "transition_date": None,
            "days_since_transition": None,
            "days_since_last_change": None,
            "transition_count_20d": 0,
            "transition_count_60d": 0,
            "stability": UNKNOWN,
            "stability_score": None,
            "parameters": {},
            "history": [],
        }


def classify_concentration(percentile: Any) -> str:
    value = finite(percentile)
    if value is None:
        return UNKNOWN
    if value < 0.60:
        return "broad_participation"
    if value < 0.80:
        return "moderate_concentration"
    if value < 0.95:
        return "high_concentration"
    return "extreme_concentration"


def classify_layer_breadth(row: dict[str, Any] | pd.Series) -> str:
    get = row.get
    advance = finite(get("advance_ratio"))
    ma20 = finite(get("pct_above_ma20"))
    ma60 = finite(get("pct_above_ma60"))
    ad5 = finite(get("ad_5d"))
    if None in {advance, ma20, ad5}:
        return UNKNOWN
    positive = int(advance >= 0.55) + int(ma20 >= 0.55) + int(ad5 > 0)
    negative = int(advance <= 0.40) + int(ma20 <= 0.35) + int(ad5 < 0)
    if ma60 is not None:
        positive += int(ma60 >= 0.55)
        negative += int(ma60 <= 0.35)
    if positive >= 3:
        return "broad_strength"
    if negative >= 3:
        return "broad_weakness"
    if advance >= 0.55 and ad5 > 0:
        return "repairing"
    return "mixed"


def classify_risk_phase(score: Any, change_1d: Any, change_5d: Any) -> str:
    level = finite(score)
    one = finite(change_1d)
    five = finite(change_5d)
    if None in {level, one, five}:
        return UNKNOWN
    if level >= 70:
        return "risk_expanding" if one >= 2 or five >= 5 else "high_pressure_stable"
    if level >= 45:
        if one >= 2 and five >= 3:
            return "risk_building"
        if one <= -2 and five <= -3:
            return "risk_contracting"
        return "high_pressure_stable"
    if level >= 25:
        if one <= -1 and five <= -3:
            return "risk_repairing"
        if one >= 2 and five >= 3:
            return "risk_building"
        return "low_pressure_stable"
    return "low_pressure_stable"


def classify_return_distribution(row: dict[str, Any] | pd.Series) -> str:
    q10 = finite(row.get("q10"))
    median = finite(row.get("median"))
    q90 = finite(row.get("q90"))
    up_ratio = finite(row.get("up_ratio"))
    std = finite(row.get("std"))
    if None in {q10, median, q90, up_ratio, std}:
        return UNKNOWN
    if median >= 0.008 and up_ratio >= 0.65:
        return "broad_rally"
    if median <= -0.008 and up_ratio <= 0.35:
        return "broad_decline"
    if q90 >= 0.025 and median <= 0.003:
        return "narrow_rally"
    if q10 <= -0.025 and median >= -0.003:
        return "narrow_decline"
    if q90 - q10 >= 0.06:
        return "polarized"
    if std <= 0.012:
        return "quiet"
    return UNKNOWN


def classify_liquidity(row: dict[str, Any] | pd.Series) -> str:
    amount_ratio = finite(row.get("amount_ratio_20d"))
    up_amount = finite(row.get("advance_amount_ratio"))
    down_amount = finite(row.get("decline_amount_ratio"))
    top_share = finite(row.get("top_10pct_turnover_share"))
    market_return = finite(row.get("equal_weight_return_1d"))
    if None in {amount_ratio, up_amount, down_amount, top_share, market_return}:
        return UNKNOWN
    if amount_ratio >= 1.10 and up_amount >= 0.58 and top_share <= 0.45:
        return "broad_expansion"
    if amount_ratio >= 1.10 and up_amount >= down_amount and top_share > 0.45:
        return "concentrated_expansion"
    if amount_ratio >= 1.10 and down_amount > up_amount:
        return "selling_expansion"
    if amount_ratio < 0.85 and market_return > 0:
        return "shrinking_rebound"
    if amount_ratio < 0.75 and abs(market_return) < 0.005:
        return "quiet"
    return "normal"


def classify_leadership_quality(row: dict[str, Any] | pd.Series) -> str:
    ret20 = finite(row.get("return_20d"))
    rs5 = finite(row.get("relative_strength_5d"))
    rs20 = finite(row.get("relative_strength_20d"))
    breadth = finite(row.get("advance_ratio"))
    ma20 = finite(row.get("pct_above_ma20"))
    top5 = finite(row.get("top5_positive_contribution_share"))
    breadth_change = finite(row.get("breadth_change_5d"))
    if None in {ret20, rs5, rs20, breadth, ma20, top5}:
        return UNKNOWN
    if ret20 < 0 and rs5 < 0 and rs20 < 0:
        return "failed"
    if (rs20 > 0 and rs5 < 0) or (breadth_change is not None and breadth_change <= -0.10):
        return "deteriorating"
    if ret20 > 0 and breadth >= 0.55 and ma20 >= 0.55 and top5 <= 0.45:
        return "broad"
    if ret20 > 0 and (breadth < 0.45 or top5 >= 0.60):
        return "narrow"
    if ret20 > 0 or rs20 > 0:
        return "moderate"
    return "failed"


def classify_rotation(row: dict[str, Any] | pd.Series) -> str:
    level = finite(row.get("level"))
    slope5 = finite(row.get("relative_slope_5d"))
    slope20 = finite(row.get("relative_slope_20d"))
    acceleration = finite(row.get("acceleration"))
    if None in {level, slope5, slope20, acceleration}:
        return UNKNOWN
    if level >= 65 and slope5 > 0 and acceleration >= 0:
        return "strong_accelerating"
    if level >= 65 and (slope5 <= 0 or acceleration < 0):
        return "strong_decelerating"
    if level < 45 and slope5 > 0:
        return "weak_improving"
    if slope5 < 0 and slope20 < 0:
        return "weak_deteriorating"
    return "neutral_rotation"


def classify_repair(row: dict[str, Any] | pd.Series) -> str:
    risk = finite(row.get("risk_score"))
    risk_change = finite(row.get("risk_change_5d"))
    advance = finite(row.get("advance_ratio"))
    ad5 = finite(row.get("ad_slope_5d"))
    low_change = finite(row.get("new_low_change_5d"))
    ma20 = finite(row.get("pct_above_ma20"))
    ma20_change = finite(row.get("pct_above_ma20_change_5d"))
    return5 = finite(row.get("equal_weight_return_5d"))
    if None in {risk, risk_change, advance, ad5, low_change, ma20, ma20_change, return5}:
        return UNKNOWN
    if risk >= 65 and risk_change > 2:
        return "panic_expanding"
    if risk >= 65 and risk_change >= -2:
        return "panic_stable"
    if risk_change < -3 and advance >= 0.55 and return5 > -0.01:
        return "initial_rebound"
    if ad5 > 0 and low_change < 0 and ma20_change > 0:
        return "breadth_repair"
    if ma20 >= 0.55 and ma20_change > 0 and risk < 45:
        return "trend_repair"
    if return5 < -0.02 and risk_change > 0 and advance < 0.45:
        return "failed_rebound"
    return "normal"


def evidence_block(
    *,
    state: str,
    supporting: list[str],
    contradicting: list[str],
    independent_family_count: int,
    freshness_ok: bool,
    coverage: Any,
    point_in_time: bool,
) -> dict[str, Any]:
    coverage_value = finite(coverage)
    if state == UNKNOWN:
        score = 0.0
        confidence = UNKNOWN
    else:
        family_score = min(max(independent_family_count, 0), 4) / 4.0
        freshness_score = 1.0 if freshness_ok else 0.0
        coverage_score = min(max(coverage_value or 0.0, 0.0), 1.0)
        pit_score = 1.0 if point_in_time else 0.55
        contradiction_penalty = min(len(contradicting) * 0.08, 0.32)
        score = max(0.0, min(1.0, 0.35 * family_score + 0.25 * freshness_score + 0.25 * coverage_score + 0.15 * pit_score - contradiction_penalty))
        confidence = "high" if score >= 0.75 else "medium" if score >= 0.50 else "low"
    return {
        "state": state,
        "supporting_evidence": supporting,
        "contradicting_evidence": contradicting,
        "confidence": confidence,
        "confidence_score": round(score, 4),
        "confidence_semantics": "evidence completeness and consistency; not a probability or forecast",
        "independent_evidence_families": int(independent_family_count),
        "freshness_ok": bool(freshness_ok),
        "coverage": coverage_value,
        "point_in_time": bool(point_in_time),
    }


def merge_state_segments(history: list[dict[str, Any]], state_key: str = "state") -> list[dict[str, Any]]:
    """Merge adjacent equal states for a compact horizontal timeline."""
    segments: list[dict[str, Any]] = []
    for row in history:
        date = row.get("trade_date")
        state = row.get(state_key, UNKNOWN)
        if segments and segments[-1]["state"] == state:
            segments[-1]["end_date"] = date
            segments[-1]["duration_trading_days"] += 1
        else:
            segments.append(
                {
                    "state": state,
                    "start_date": date,
                    "end_date": date,
                    "duration_trading_days": 1,
                }
            )
    return segments


def classify_ice_phase(risk_state: str, repair_state: str, risk_score: Any, risk_change_5d: Any) -> str:
    score = finite(risk_score)
    change = finite(risk_change_5d)
    if score is None or change is None:
        return UNKNOWN
    if risk_state in {"risk_expanding", "risk_building"} and score >= 60:
        return "panic_expanding"
    if score >= 60 and abs(change) < 3:
        return "panic_stable"
    if score >= 50 and change < -3:
        return "panic_contracting"
    if repair_state in {"breadth_repair", "trend_repair"}:
        return "rebound_confirmed"
    if repair_state == "failed_rebound":
        return "rebound_failed"
    return "none"


def classify_heat_phase(concentration_state: str, leadership_state: str, distribution_state: str) -> str:
    if UNKNOWN in {concentration_state, leadership_state, distribution_state}:
        return UNKNOWN
    if concentration_state == "extreme_concentration" and leadership_state in {"narrow", "deteriorating"}:
        return "exhaustion_warning"
    if concentration_state in {"high_concentration", "extreme_concentration"} and distribution_state in {"narrow_rally", "polarized"}:
        return "heat_persistent"
    if leadership_state in {"broad", "moderate"} and distribution_state == "broad_rally":
        return "heat_building"
    if leadership_state == "failed" and distribution_state == "broad_decline":
        return "exhaustion_confirmed"
    return "none"
