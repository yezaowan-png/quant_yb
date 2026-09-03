"""Simulation-only policy and hysteresis for the market extreme-risk gate."""

from __future__ import annotations

import ast
import json
from typing import Any

import pandas as pd


RISK_LEVELS = ("green", "yellow", "orange", "red")
LEVEL_POLICY = {
    "green": {"allow_new_positions": True, "position_cap": 1.0},
    "yellow": {"allow_new_positions": True, "position_cap": 0.6},
    "orange": {"allow_new_positions": False, "position_cap": 0.3},
    "red": {"allow_new_positions": False, "position_cap": 0.0},
}


def raw_risk_level(state: str, risk_score: float) -> str:
    if state == "panic" and risk_score >= 70:
        return "red"
    if state == "panic" or risk_score >= 60:
        return "orange"
    if state in {"stressed", "recovering"} or risk_score >= 35:
        return "yellow"
    return "green"


def apply_policy_hysteresis(states: pd.DataFrame, release_days: int = 3) -> pd.DataFrame:
    """Risk can enter quickly but must step down after consecutive improvement."""
    if states.empty:
        return pd.DataFrame()
    current_level = "green"
    improvement_streak = 0
    rows = []
    for _, row in states.sort_values("trade_date").iterrows():
        requested = raw_risk_level(str(row["current_state"]), float(row["risk_score"]))
        current_index = RISK_LEVELS.index(current_level)
        requested_index = RISK_LEVELS.index(requested)
        if requested_index > current_index:
            current_level = requested
            improvement_streak = 0
        elif requested_index < current_index:
            improvement_streak += 1
            if improvement_streak >= int(release_days):
                # Never jump directly from panic/red to green.
                current_level = RISK_LEVELS[current_index - 1]
                improvement_streak = 0
        else:
            improvement_streak = 0
        policy = LEVEL_POLICY[current_level]
        release_conditions = []
        if current_level in {"orange", "red"}:
            release_conditions = [
                "大跌股票比例降至历史P80以下",
                "NH-NL斜率连续转正",
                "A/D斜率连续转正",
                "创新低数量明显收缩",
                "站上MA20股票比例开始恢复",
                f"连续{int(release_days)}日改善后逐级解除",
            ]
        rows.append({
            **row.to_dict(), "risk_level": current_level,
            "allow_new_positions": bool(policy["allow_new_positions"]),
            "position_cap": float(policy["position_cap"]),
            "release_conditions": release_conditions,
            "policy_mode": "simulation_only",
        })
    return pd.DataFrame(rows)


def policy_payload(row: pd.Series, probabilities: dict[int, float | None] | None = None) -> dict[str, Any]:
    def as_list(value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return []
        if isinstance(value, str):
            for loader in (json.loads, ast.literal_eval):
                try:
                    parsed = loader(value)
                except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
                    continue
                if isinstance(parsed, (list, tuple)):
                    return list(parsed)
            return [value]
        return [value]

    return {
        "date": str(row["trade_date"]), "current_state": str(row["current_state"]),
        "risk_level": str(row["risk_level"]), "risk_score": float(row["risk_score"]),
        **{f"extreme_risk_probability_{horizon}d": (probabilities or {}).get(horizon) for horizon in (1, 5, 10, 20)},
        "allow_new_positions": bool(row["allow_new_positions"]),
        "position_cap": float(row["position_cap"]),
        "reasons": [f"current_state={row['current_state']}", f"risk_level={row['risk_level']}"],
        "risk_flags": as_list(row.get("risk_flags")),
        "release_conditions": as_list(row.get("release_conditions")),
        "data_quality_flags": [
            "incomplete_point_in_time_universe",
            "missing_delisted_stocks",
            "missing_historical_st_status",
        ],
    }
