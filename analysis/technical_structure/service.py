"""Causal ATR-ZigZag technical structure service.

The service is asset/page agnostic. It only consumes normalized OHLCV data and
returns serializable pivots, levels, lines, channels and current context.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .data_adapter import bar_records, normalize_ohlcv, resample_ohlcv
from .models import TechnicalStructureResult


ALGORITHM_VERSION = "technical_structure_v1.2.1"

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "defaults": {
        "adjustment_stock": "qfq",
        "adjustment_index": "none",
        "include_incomplete_bar": False,
        "atr_period": 14,
        "cache_enabled": True,
    },
    "timeframe": {
        "daily": {
            "pivot_reversal_atr": 1.5, "pivot_reversal_pct_floor": 0.02,
            "min_pivot_separation_bars": 3, "horizontal_lookback_bars": 500,
            "trendline_min_span_bars": 20, "trendline_min_pair_separation_bars": 10,
            "trendline_max_age_bars": 500,
            "projection_bars": 30, "level_tolerance_atr": 0.8, "level_tolerance_pct": 0.01,
            "max_candidate_pivots": 80, "max_support": 3, "max_resistance": 3,
            "max_trendlines_per_type": 2, "max_channels": 1, "minimum_history_bars": 40,
        },
        "weekly": {
            "pivot_reversal_atr": 1.8, "pivot_reversal_pct_floor": 0.04,
            "min_pivot_separation_bars": 2, "horizontal_lookback_bars": 260,
            "trendline_min_span_bars": 8, "trendline_min_pair_separation_bars": 4,
            "trendline_max_age_bars": 260,
            "projection_bars": 12, "level_tolerance_atr": 0.9, "level_tolerance_pct": 0.015,
            "max_candidate_pivots": 50, "max_support": 3, "max_resistance": 3,
            "max_trendlines_per_type": 2, "max_channels": 1, "minimum_history_bars": 20,
        },
        "monthly": {
            "pivot_reversal_atr": 2.0, "pivot_reversal_pct_floor": 0.08,
            "min_pivot_separation_bars": 1, "horizontal_lookback_bars": 180,
            "trendline_min_span_bars": 5, "trendline_min_pair_separation_bars": 2,
            "trendline_max_age_bars": 120,
            "projection_bars": 6, "level_tolerance_atr": 1.0, "level_tolerance_pct": 0.025,
            "max_candidate_pivots": 30, "max_support": 2, "max_resistance": 2,
            "max_trendlines_per_type": 1, "max_channels": 1, "minimum_history_bars": 12,
        },
    },
    "breakout": {"atr_buffer": 0.25, "confirmation_bars": 2, "role_reversal_lookahead_bars": 60},
    "trendline": {
        "touch_tolerance_atr": 0.75, "max_violation_atr": 0.8,
        "max_violation_ratio": 0.12, "max_anchor_penetration_atr": 0.8,
        "break_confirmation_bars": 2, "expire_after_bars": 180,
        "dedup_latest_atr": 0.8, "dedup_slope_ratio": 0.25,
        "channel_min_opposite_touches": 2, "channel_max_violation_ratio": 0.08,
        "channel_max_penetration_atr": 1.5,
        "show_secondary_types": False,
    },
    "overlay_timeframes": {"daily_chart": ["1d", "1w", "1mo"], "weekly_chart": ["1w", "1mo"], "monthly_chart": ["1mo"]},
    "manual_technical_lines": {},
}

_TIMEFRAME_KEYS = {"1d": "daily", "1w": "weekly", "1mo": "monthly"}


def _deep_merge(base: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _json_default(value: Any):
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    raise TypeError(type(value).__name__)


def _hash_payload(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default)
    return sha256(raw.encode("utf-8")).hexdigest()[:16]


def _date(value: Any) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def calculate_atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    previous = frame["close"].shift(1)
    true_range = pd.concat(
        [frame["high"] - frame["low"], (frame["high"] - previous).abs(), (frame["low"] - previous).abs()],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1.0 / max(int(period), 1), adjust=False, min_periods=1).mean()


def _threshold(price: float, atr_value: float, cfg: dict[str, Any]) -> float:
    return max(float(cfg["pivot_reversal_atr"]) * max(float(atr_value), 0.0), abs(float(price)) * float(cfg["pivot_reversal_pct_floor"]))


def identify_causal_pivots(
    frame: pd.DataFrame,
    *,
    timeframe: str,
    atr: pd.Series,
    config: dict[str, Any],
    asset_type: str,
) -> list[dict[str, Any]]:
    """Confirm pivots only after a subsequent ATR/percentage reversal."""
    if len(frame) < 3:
        return []
    high = frame["high"].to_numpy(float)
    low = frame["low"].to_numpy(float)
    open_ = frame["open"].to_numpy(float)
    close = frame["close"].to_numpy(float)
    volume = pd.to_numeric(frame["volume"], errors="coerce").to_numpy(float)
    atr_values = atr.to_numpy(float)
    min_separation = max(int(config["min_pivot_separation_bars"]), 1)

    running_high_idx = running_low_idx = 0
    direction: str | None = None
    candidate_idx = 0
    pivots: list[dict[str, Any]] = []

    def add_pivot(pivot_type: str, pivot_index: int, confirmation_index: int, reversal: float) -> None:
        if pivots and pivot_index <= int(pivots[-1]["bar_index"]):
            return
        # Separation is enforced at the first observable confirmation point.
        # Using only the extrema indices can permanently strand the ZigZag
        # state when a sharp reversal occurs immediately after the last pivot.
        if pivots and confirmation_index - int(pivots[-1]["bar_index"]) < min_separation:
            return
        price = high[pivot_index] if pivot_type == "high" else low[pivot_index]
        atr_value = max(float(atr_values[pivot_index]), 1e-12)
        strength = min(100.0, max(0.0, reversal / atr_value * 22.0))
        if asset_type == "stock" and np.isfinite(volume[pivot_index]):
            one_price = abs(high[pivot_index] - low[pivot_index]) <= max(abs(close[pivot_index]) * 1e-8, 1e-10)
            if one_price and volume[pivot_index] > 0:
                strength *= 0.7
        pivots.append(
            {
                "id": f"{timeframe}-{pivot_type}-{pivot_index}-{confirmation_index}",
                "pivot_type": pivot_type,
                "timeframe": timeframe,
                "pivot_date": _date(frame["date"].iloc[pivot_index]),
                "confirmation_date": _date(frame["date"].iloc[confirmation_index]),
                "bar_index": int(pivot_index),
                "confirmation_bar_index": int(confirmation_index),
                "price": round(float(price), 6),
                "atr": round(float(atr_values[pivot_index]), 6),
                "reversal_pct": round(float(reversal / max(abs(price), 1e-12)), 8),
                "strength": round(float(strength), 4),
                "is_confirmed": True,
            }
        )

    for index in range(1, len(frame)):
        if direction is None:
            if high[index] >= high[running_high_idx]:
                running_high_idx = index
            if low[index] <= low[running_low_idx]:
                running_low_idx = index
            high_reversal = high[running_high_idx] - low[index]
            low_reversal = high[index] - low[running_low_idx]
            if running_high_idx < index and high_reversal >= _threshold(high[running_high_idx], atr_values[index], config):
                add_pivot("high", running_high_idx, index, high_reversal)
                direction, candidate_idx = "down", index
            elif running_low_idx < index and low_reversal >= _threshold(low[running_low_idx], atr_values[index], config):
                add_pivot("low", running_low_idx, index, low_reversal)
                direction, candidate_idx = "up", index
            continue

        if direction == "up":
            if high[index] >= high[candidate_idx]:
                candidate_idx = index
            reversal = high[candidate_idx] - low[index]
            if index - candidate_idx >= 1 and reversal >= _threshold(high[candidate_idx], atr_values[index], config):
                before = len(pivots)
                add_pivot("high", candidate_idx, index, reversal)
                if len(pivots) > before:
                    direction, candidate_idx = "down", index
        else:
            if low[index] <= low[candidate_idx]:
                candidate_idx = index
            reversal = high[index] - low[candidate_idx]
            if index - candidate_idx >= 1 and reversal >= _threshold(low[candidate_idx], atr_values[index], config):
                before = len(pivots)
                add_pivot("low", candidate_idx, index, reversal)
                if len(pivots) > before:
                    direction, candidate_idx = "up", index
    return pivots


def _cluster_pivots(
    frame: pd.DataFrame,
    pivots: list[dict[str, Any]],
    atr: pd.Series,
    timeframe: str,
    cfg: dict[str, Any],
    breakout_cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    if not pivots:
        return []
    lookback_start = max(0, len(frame) - int(cfg["horizontal_lookback_bars"]))
    usable = [pivot for pivot in pivots if int(pivot["bar_index"]) >= lookback_start]
    clusters: list[list[dict[str, Any]]] = []
    for pivot in sorted(usable, key=lambda item: float(item["price"])):
        best: list[dict[str, Any]] | None = None
        best_gap = float("inf")
        for cluster in clusters:
            center = float(np.average([float(item["price"]) for item in cluster], weights=[max(float(item["strength"]), 1.0) for item in cluster]))
            pivot_atr = max(float(pivot.get("atr") or 0), 0.0)
            tolerance = max(float(cfg["level_tolerance_atr"]) * pivot_atr, abs(center) * float(cfg["level_tolerance_pct"]))
            gap = abs(float(pivot["price"]) - center)
            if gap <= tolerance and gap < best_gap:
                best, best_gap = cluster, gap
        if best is None:
            clusters.append([pivot])
        else:
            best.append(pivot)

    close = frame["close"].to_numpy(float)
    high = frame["high"].to_numpy(float)
    low = frame["low"].to_numpy(float)
    latest_close = float(close[-1])
    levels: list[dict[str, Any]] = []
    for number, cluster in enumerate(clusters):
        if len(cluster) < 2:
            continue
        weights = np.array([max(float(item["strength"]), 1.0) for item in cluster])
        prices = np.array([float(item["price"]) for item in cluster])
        level_price = float(np.average(prices, weights=weights))
        last = max(cluster, key=lambda item: int(item["bar_index"]))
        first = min(cluster, key=lambda item: int(item["bar_index"]))
        source_high = sum(item["pivot_type"] == "high" for item in cluster)
        source_low = len(cluster) - source_high
        original_type = "resistance" if source_high > source_low else "support"
        tolerance = max(float(cfg["level_tolerance_atr"]) * float(atr.iloc[-1]), abs(level_price) * float(cfg["level_tolerance_pct"]))
        zone_low, zone_high = level_price - tolerance, level_price + tolerance
        start_check = max(int(item["confirmation_bar_index"]) for item in cluster)
        buffer = float(breakout_cfg["atr_buffer"])
        confirmations = max(int(breakout_cfg["confirmation_bars"]), 1)
        break_index: int | None = None
        for index in range(start_check, len(frame) - confirmations + 1):
            threshold = buffer * float(atr.iloc[index])
            window = close[index:index + confirmations]
            broken = bool(np.all(window > zone_high + threshold)) if original_type == "resistance" else bool(np.all(window < zone_low - threshold))
            if broken:
                break_index = index + confirmations - 1
                break
        status = "active"
        effective_type = original_type
        role_date = None
        if break_index is not None:
            status = "broken"
            test_end = min(len(frame), break_index + int(breakout_cfg["role_reversal_lookahead_bars"]) + 1)
            for index in range(break_index + 1, test_end):
                if original_type == "resistance" and low[index] <= zone_high + tolerance and close[index] >= zone_low:
                    status, effective_type, role_date = "role_reversal", "support", _date(frame["date"].iloc[index])
                    break
                if original_type == "support" and high[index] >= zone_low - tolerance and close[index] <= zone_high:
                    status, effective_type, role_date = "role_reversal", "resistance", _date(frame["date"].iloc[index])
                    break
        recency = max(0.0, 1.0 - (len(frame) - 1 - int(last["bar_index"])) / max(int(cfg["horizontal_lookback_bars"]), 1))
        dispersion = float(np.mean(np.abs(prices - level_price)) / max(tolerance, 1e-12))
        score = min(100.0, len(cluster) * 14.0 + recency * 28.0 + float(np.mean([p["strength"] for p in cluster])) * 0.25 - dispersion * 10.0)
        levels.append(
            {
                "id": f"{timeframe}-level-{number}-{int(first['bar_index'])}",
                "type": effective_type,
                "original_type": original_type,
                "timeframe": timeframe,
                "price": round(level_price, 6),
                "zone_low": round(zone_low, 6),
                "zone_high": round(zone_high, 6),
                "first_touch_date": first["pivot_date"],
                "last_touch_date": last["pivot_date"],
                "confirmation_date": max(item["confirmation_date"] for item in cluster),
                "touch_count": len(cluster),
                "status": status,
                "break_date": None if break_index is None else _date(frame["date"].iloc[break_index]),
                "role_reversal_date": role_date,
                "score": round(max(score, 0.0), 4),
                "source": "automatic",
                "pivot_ids": [item["id"] for item in cluster],
                "distance_pct": round((latest_close / level_price - 1.0), 8),
                "reasons": [f"{len(cluster)}个已确认pivot聚类", "ATR与百分比双重容差", f"状态:{status}"],
            }
        )
    supports = sorted([item for item in levels if item["type"] == "support"], key=lambda item: (-item["score"], abs(item["distance_pct"])))[: int(cfg["max_support"])]
    resistance = sorted([item for item in levels if item["type"] == "resistance"], key=lambda item: (-item["score"], abs(item["distance_pct"])))[: int(cfg["max_resistance"])]
    return sorted(supports + resistance, key=lambda item: (item["type"], -item["score"]))


def _line_price(line: dict[str, Any], bar_index: int) -> float:
    return float(line["intercept"]) + float(line["slope_per_bar"]) * int(bar_index)


def _first_confirmed_break(
    frame: pd.DataFrame,
    *,
    intercept: float,
    slope: float,
    line_type: str,
    start_index: int,
    atr: pd.Series,
    tolerance_atr: float,
    confirmation_bars: int,
) -> int | None:
    """Return the first causal bar-confirmed break of a trend boundary."""
    observations = frame["low"].to_numpy(float) if "support" in line_type else frame["high"].to_numpy(float)
    streak = 0
    streak_start = 0
    for index in range(max(int(start_index), 0), len(frame)):
        expected = intercept + slope * index
        buffer = tolerance_atr * max(float(atr.iloc[index]), 1e-12)
        crossed = observations[index] < expected - buffer if "support" in line_type else observations[index] > expected + buffer
        if crossed:
            if streak == 0:
                streak_start = index
            streak += 1
            if streak >= max(int(confirmation_bars), 1):
                return streak_start
        else:
            streak = 0
    return None


def _line_payload(
    frame: pd.DataFrame,
    atr: pd.Series,
    p1: dict[str, Any],
    p2: dict[str, Any],
    pivots: list[dict[str, Any]],
    line_type: str,
    timeframe: str,
    cfg: dict[str, Any],
    common: dict[str, Any],
) -> dict[str, Any] | None:
    index1, index2 = int(p1["bar_index"]), int(p2["bar_index"])
    separation = index2 - index1
    if separation < int(cfg["trendline_min_pair_separation_bars"]):
        return None
    if len(frame) - 1 - index1 > int(cfg.get("trendline_max_age_bars", len(frame))):
        return None
    slope = (float(p2["price"]) - float(p1["price"])) / separation
    if line_type == "ascending_support" and slope <= 0:
        return None
    if line_type == "descending_resistance" and slope >= 0:
        return None
    if line_type == "ascending_resistance" and slope <= 0:
        return None
    if line_type == "descending_support" and slope >= 0:
        return None
    intercept = float(p1["price"]) - slope * index1
    pivot_type = "low" if "support" in line_type else "high"
    same = [item for item in pivots if item["pivot_type"] == pivot_type and int(item["bar_index"]) >= index1]
    touch_tolerance = float(common["touch_tolerance_atr"])
    touches: list[dict[str, Any]] = []
    errors: list[float] = []
    for pivot in same:
        index = int(pivot["bar_index"])
        expected = intercept + slope * index
        error = abs(float(pivot["price"]) - expected) / max(float(atr.iloc[index]), 1e-12)
        if error <= touch_tolerance:
            touches.append(pivot)
            errors.append(error)
    if len(touches) < 2:
        return None
    # Geometry and causal state are deliberately separate.  The line is only
    # observable when the second anchor is confirmed, but at that moment every
    # bar between both anchors is already known and the segment must not cut
    # materially through price.
    confirmation_index = max(int(p1["confirmation_bar_index"]), int(p2["confirmation_bar_index"]))
    observations = frame["low"].to_numpy(float) if "support" in line_type else frame["high"].to_numpy(float)
    violation_atr = float(common["max_violation_atr"])
    anchor_violations: list[int] = []
    anchor_penetrations: list[float] = []
    for index in range(index1, index2 + 1):
        expected = intercept + slope * index
        normalized = (expected - observations[index]) / max(float(atr.iloc[index]), 1e-12) if "support" in line_type else (observations[index] - expected) / max(float(atr.iloc[index]), 1e-12)
        if normalized > violation_atr:
            anchor_violations.append(index)
            anchor_penetrations.append(float(normalized))
    anchor_violation_ratio = len(anchor_violations) / max(index2 - index1 + 1, 1)
    if anchor_violation_ratio > float(common["max_violation_ratio"]):
        return None
    if anchor_penetrations and max(anchor_penetrations) > float(common.get("max_anchor_penetration_atr", 0.8)):
        return None

    post_violations: list[int] = []
    for index in range(confirmation_index, len(frame)):
        expected = intercept + slope * index
        normalized = (expected - observations[index]) / max(float(atr.iloc[index]), 1e-12) if "support" in line_type else (observations[index] - expected) / max(float(atr.iloc[index]), 1e-12)
        if normalized > violation_atr:
            post_violations.append(index)
    violations = sorted(set(anchor_violations + post_violations))
    violation_ratio = len(violations) / max(index2 - index1 + 1 + len(frame) - confirmation_index, 1)
    span = int(max(item["bar_index"] for item in touches) - min(item["bar_index"] for item in touches))
    if span < int(cfg["trendline_min_span_bars"]):
        return None
    last_touch = max(int(item["bar_index"]) for item in touches)
    recency = max(0.0, 1.0 - (len(frame) - 1 - last_touch) / max(int(common["expire_after_bars"]), 1))
    span_score = min(span / max(int(cfg["trendline_min_span_bars"]), 1), 3.0) / 3.0
    error_score = max(0.0, 1.0 - float(np.mean(errors)) / max(touch_tolerance, 1e-12))
    touch_score = min(len(touches), 5) / 5.0
    strength_score = min(float(np.mean([p["strength"] for p in touches])) / 100.0, 1.0)
    violation_penalty = min(1.0, violation_ratio / max(float(common["max_violation_ratio"]), 1e-12))
    score = 100.0 * (
        touch_score * 0.30
        + recency * 0.22
        + span_score * 0.13
        + error_score * 0.20
        + strength_score * 0.15
        - violation_penalty * 0.25
    )
    # The report axis only contains observed bars. Keep every surviving line
    # projected through the current observed bar; future-date projection would
    # require fabricating exchange sessions and would misalign the renderer.
    projection_index = len(frame) - 1
    latest_price = intercept + slope * (len(frame) - 1)
    current_close = float(frame["close"].iloc[-1])
    break_index = _first_confirmed_break(
        frame, intercept=intercept, slope=slope, line_type=line_type,
        start_index=confirmation_index, atr=atr, tolerance_atr=violation_atr,
        confirmation_bars=int(common.get("break_confirmation_bars", 2)),
    )
    broken = break_index is not None
    status = "broken" if broken else "expired" if len(frame) - 1 - last_touch > int(common["expire_after_bars"]) else "active"
    break_date = _date(frame["date"].iloc[break_index]) if break_index is not None else None
    return {
        "id": f"{timeframe}-{line_type}-{index1}-{index2}",
        "type": line_type,
        "timeframe": timeframe,
        "start_date": _date(frame["date"].iloc[index1]),
        "end_date": _date(frame["date"].iloc[index2]),
        "confirmation_date": _date(frame["date"].iloc[confirmation_index]),
        "projection_end_date": _date(frame["date"].iloc[projection_index]),
        "start_bar_index": index1,
        "end_bar_index": index2,
        "projection_end_bar_index": projection_index,
        "start_price": round(intercept + slope * index1, 6),
        "end_price": round(intercept + slope * index2, 6),
        "projection_end_price": round(intercept + slope * projection_index, 6),
        "latest_price": round(latest_price, 6),
        "slope_per_bar": round(slope, 10),
        "intercept": round(intercept, 8),
        "touch_pivot_ids": [item["id"] for item in touches],
        "touch_count": len(touches),
        "violation_count": len(violations),
        "normalized_error": round(float(np.mean(errors)), 6),
        "status": status,
        "break_date": break_date,
        "score": round(max(score, 0.0), 4),
        "source": "automatic",
        "distance_pct": round(current_close / latest_price - 1.0, 8) if latest_price else None,
        "reasons": [f"连接{len(touches)}个已确认{pivot_type} pivot", "bar_index拟合", "ATR标准化误差"],
    }


def _deduplicate_lines(lines: list[dict[str, Any]], atr_latest: float, cfg: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    status_rank = {"active": 0, "expired": 1, "broken": 2}
    for candidate in sorted(lines, key=lambda item: (status_rank.get(str(item.get("status")), 3), -float(item["score"]), -int(item["touch_count"]), -int(item["start_bar_index"]))):
        duplicate = False
        for existing in selected:
            price_gap = abs(float(candidate["latest_price"]) - float(existing["latest_price"]))
            slope_ref = max(abs(float(candidate["slope_per_bar"])), abs(float(existing["slope_per_bar"])), 1e-12)
            slope_gap = abs(float(candidate["slope_per_bar"]) - float(existing["slope_per_bar"])) / slope_ref
            candidate_touches = set(candidate.get("touch_pivot_ids") or [])
            existing_touches = set(existing.get("touch_pivot_ids") or [])
            overlap = len(candidate_touches & existing_touches) / max(min(len(candidate_touches), len(existing_touches)), 1)
            same_last_anchor = int(candidate.get("end_bar_index", -1)) == int(existing.get("end_bar_index", -2))
            if price_gap <= float(cfg["dedup_latest_atr"]) * max(atr_latest, 1e-12) and (
                slope_gap <= float(cfg["dedup_slope_ratio"]) or overlap >= 0.6 or same_last_anchor
            ):
                duplicate = True
                break
        if not duplicate:
            selected.append(candidate)
        if len(selected) >= limit:
            break
    return selected


def _detect_trendlines(
    frame: pd.DataFrame,
    pivots: list[dict[str, Any]],
    atr: pd.Series,
    timeframe: str,
    cfg: dict[str, Any],
    common: dict[str, Any],
) -> list[dict[str, Any]]:
    limit = int(cfg["max_candidate_pivots"])
    candidate_types = [("low", "ascending_support"), ("high", "descending_resistance")]
    if bool(common.get("show_secondary_types", False)):
        candidate_types.extend([("high", "ascending_resistance"), ("low", "descending_support")])
    result: list[dict[str, Any]] = []
    for pivot_type, line_type in candidate_types:
        typed = [item for item in pivots if item["pivot_type"] == pivot_type][-limit:]
        candidates: list[dict[str, Any]] = []
        for left in range(len(typed) - 1):
            for right in range(left + 1, len(typed)):
                line = _line_payload(frame, atr, typed[left], typed[right], pivots, line_type, timeframe, cfg, common)
                if line is not None:
                    candidates.append(line)
        result.extend(_deduplicate_lines(candidates, float(atr.iloc[-1]), common, int(cfg["max_trendlines_per_type"])))
    return sorted(result, key=lambda item: (item["type"], -float(item["score"])))


def _detect_channels(
    frame: pd.DataFrame,
    pivots: list[dict[str, Any]],
    atr: pd.Series,
    trendlines: list[dict[str, Any]],
    timeframe: str,
    cfg: dict[str, Any],
    common: dict[str, Any],
) -> list[dict[str, Any]]:
    channels: list[dict[str, Any]] = []
    tolerance_mult = float(common["touch_tolerance_atr"])
    for base in sorted([item for item in trendlines if item["status"] == "active"], key=lambda item: -float(item["score"])):
        ascending = base["type"] == "ascending_support"
        descending = base["type"] == "descending_resistance"
        if not (ascending or descending):
            continue
        opposite_type = "high" if ascending else "low"
        opposite = [item for item in pivots if item["pivot_type"] == opposite_type and int(item["bar_index"]) >= int(base["start_bar_index"])]
        if not opposite:
            continue
        offsets = []
        for pivot in opposite:
            index = int(pivot["bar_index"])
            offset = float(pivot["price"]) - _line_price(base, index)
            if (ascending and offset > 0) or (descending and offset < 0):
                offsets.append((offset, pivot))
        if not offsets:
            continue
        best: tuple[int, float, float, dict[str, Any]] | None = None
        best_touches: list[dict[str, Any]] = []
        for offset, anchor in offsets:
            errors = []
            touched_pivots: list[dict[str, Any]] = []
            for _, pivot in offsets:
                error = abs(float(pivot["price"]) - (_line_price(base, int(pivot["bar_index"])) + offset)) / max(float(atr.iloc[int(pivot["bar_index"])]), 1e-12)
                if error <= tolerance_mult:
                    touched_pivots.append(pivot)
                    errors.append(error)
            candidate = (len(touched_pivots), -float(np.mean(errors) if errors else 999), abs(offset), anchor)
            if best is None or candidate[:3] > best[:3]:
                best = candidate
                best_offset = offset
                best_touches = touched_pivots
        if best is None:
            continue
        touches = int(best[0])
        if touches < int(common.get("channel_min_opposite_touches", 2)):
            continue

        # A channel needs two independently confirmed opposite-side contacts.
        # Validate the completed envelope up to the latest such contact before
        # deciding whether it remains active after confirmation.
        channel_end_index = max(int(item["bar_index"]) for item in best_touches)
        date_to_index = {
            _date(value): index for index, value in enumerate(frame["date"])
        }
        base_confirmation_index = date_to_index.get(
            str(base.get("confirmation_date")),
            int(base.get("end_bar_index", base["start_bar_index"])),
        )
        channel_confirmation_index = max(
            base_confirmation_index,
            max(int(item["confirmation_bar_index"]) for item in best_touches),
        )
        outside: list[float] = []
        for index in range(int(base["start_bar_index"]), channel_end_index + 1):
            base_price = _line_price(base, index)
            parallel_price = base_price + best_offset
            lower = min(base_price, parallel_price)
            upper = max(base_price, parallel_price)
            scale = max(float(atr.iloc[index]), 1e-12)
            penetration = max(
                (lower - float(frame["low"].iloc[index])) / scale,
                (float(frame["high"].iloc[index]) - upper) / scale,
                0.0,
            )
            if penetration > float(common["max_violation_atr"]):
                outside.append(penetration)
        channel_span = max(channel_end_index - int(base["start_bar_index"]) + 1, 1)
        if len(outside) / channel_span > float(common.get("channel_max_violation_ratio", 0.08)):
            continue
        if outside and max(outside) > float(common.get("channel_max_penetration_atr", 1.5)):
            continue

        break_bars = max(int(common.get("break_confirmation_bars", 2)), 1)
        low_values = frame["low"].to_numpy(float)
        high_values = frame["high"].to_numpy(float)
        break_index: int | None = None
        streak = 0
        streak_start = 0
        for index in range(channel_confirmation_index, len(frame)):
            base_price = _line_price(base, index)
            parallel_price = base_price + best_offset
            lower = min(base_price, parallel_price)
            upper = max(base_price, parallel_price)
            buffer = float(common["max_violation_atr"]) * max(float(atr.iloc[index]), 1e-12)
            crossed = low_values[index] < lower - buffer or high_values[index] > upper + buffer
            if crossed:
                if streak == 0:
                    streak_start = index
                streak += 1
                if streak >= break_bars:
                    break_index = streak_start
                    break
            else:
                streak = 0
        parallel = {
            "slope_per_bar": base["slope_per_bar"],
            "intercept": round(float(base["intercept"]) + best_offset, 8),
            "start_date": base["start_date"],
            "projection_end_date": base["projection_end_date"],
            "start_bar_index": base["start_bar_index"],
            "projection_end_bar_index": base["projection_end_bar_index"],
            "start_price": round(_line_price(base, int(base["start_bar_index"])) + best_offset, 6),
            "projection_end_price": round(_line_price(base, int(base["projection_end_bar_index"])) + best_offset, 6),
        }
        score = min(100.0, float(base["score"]) * 0.65 + touches * 10.0 - len(outside) / channel_span * 100.0)
        channel_status = "broken" if break_index is not None else base["status"]
        channels.append(
            {
                "id": f"{timeframe}-channel-{base['id']}",
                "type": "ascending_channel" if ascending else "descending_channel",
                "timeframe": timeframe,
                "base_line_id": base["id"],
                "upper_line": parallel if ascending else base,
                "lower_line": base if ascending else parallel,
                "touch_count_upper": touches if ascending else int(base["touch_count"]),
                "touch_count_lower": int(base["touch_count"]) if ascending else touches,
                "score": round(score, 4),
                "status": channel_status,
                "break_date": _date(frame["date"].iloc[break_index]) if break_index is not None else None,
                "confirmation_date": _date(frame["date"].iloc[min(channel_confirmation_index, len(frame) - 1)]),
                "source": "automatic",
            }
        )
        if len(channels) >= int(cfg["max_channels"]):
            break
    return channels


def _manual_items(
    config: dict[str, Any], symbol: str, timeframe: str, adjustment: str,
    frame: pd.DataFrame,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    by_symbol = (config.get("manual_technical_lines") or {}).get(symbol, {})
    items = by_symbol.get(timeframe, []) if isinstance(by_symbol, dict) else []
    levels: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    flags: list[str] = []
    dates = frame["date"].dt.strftime("%Y-%m-%d").tolist()
    for number, item in enumerate(items):
        if item.get("adjustment") and str(item["adjustment"]).lower() != adjustment:
            flags.append("manual_adjustment_mismatch")
            continue
        item_type = str(item.get("type", ""))
        if item_type in {"horizontal_support", "horizontal_resistance"} and item.get("price") is not None:
            price = float(item["price"])
            levels.append(
                {
                    "id": f"{timeframe}-manual-level-{number}", "type": "support" if "support" in item_type else "resistance",
                    "original_type": "support" if "support" in item_type else "resistance", "timeframe": timeframe,
                    "price": price, "zone_low": price, "zone_high": price,
                    "first_touch_date": str(item.get("start_date") or dates[0]), "last_touch_date": dates[-1],
                    "confirmation_date": str(item.get("start_date") or dates[0]), "touch_count": 0,
                    "status": "active", "break_date": None, "score": 0.0, "source": "manual",
                    "distance_pct": float(frame["close"].iloc[-1] / price - 1.0),
                    "reasons": [str(item.get("note") or "人工结构线，不参与自动评分")],
                }
            )
        elif item_type == "trendline" and item.get("start") and item.get("end"):
            start, end = item["start"], item["end"]
            start_date, end_date = str(start["date"]), str(end["date"])
            try:
                start_index = min(range(len(dates)), key=lambda i: abs(pd.Timestamp(dates[i]) - pd.Timestamp(start_date)))
                end_index = min(range(len(dates)), key=lambda i: abs(pd.Timestamp(dates[i]) - pd.Timestamp(end_date)))
            except (ValueError, TypeError):
                continue
            if end_index <= start_index:
                continue
            slope = (float(end["price"]) - float(start["price"])) / (end_index - start_index)
            intercept = float(start["price"]) - slope * start_index
            line_type = "ascending_support" if slope > 0 else "descending_resistance"
            latest_price = intercept + slope * (len(frame) - 1)
            lines.append(
                {
                    "id": f"{timeframe}-manual-line-{number}", "type": line_type, "timeframe": timeframe,
                    "start_date": dates[start_index], "end_date": dates[end_index], "confirmation_date": dates[end_index],
                    "projection_end_date": dates[-1], "start_bar_index": start_index, "end_bar_index": end_index,
                    "projection_end_bar_index": len(frame) - 1, "start_price": float(start["price"]),
                    "end_price": float(end["price"]), "projection_end_price": latest_price, "latest_price": latest_price,
                    "slope_per_bar": slope, "intercept": intercept, "touch_pivot_ids": [], "touch_count": 0,
                    "violation_count": 0, "normalized_error": None, "status": "active", "break_date": None,
                    "score": 0.0, "source": "manual", "distance_pct": float(frame["close"].iloc[-1] / latest_price - 1.0),
                    "reasons": [str(item.get("note") or "人工结构线，不参与自动评分")],
                }
            )
    return levels, lines, flags


def _level_context(level: dict[str, Any], close: float) -> dict[str, Any]:
    return {
        "id": level["id"], "price": level["price"],
        "zone_low": level["zone_low"], "zone_high": level["zone_high"],
        "distance_pct": round(close / float(level["price"]) - 1.0, 8),
        "score": level["score"], "timeframe": level["timeframe"], "status": level["status"],
    }


def _build_context(
    frame: pd.DataFrame,
    levels: list[dict[str, Any]],
    lines: list[dict[str, Any]],
    channels: list[dict[str, Any]],
    timeframe: str,
) -> dict[str, Any]:
    close = float(frame["close"].iloc[-1])
    # Context follows the conventional directional meaning: support centre is
    # below the current close, resistance centre is above it. Wide ATR zones
    # may overlap the close, but must not invert the displayed range.
    supports = [item for item in levels if item["type"] == "support" and item["status"] in {"active", "role_reversal"} and float(item["price"]) <= close]
    resistances = [item for item in levels if item["type"] == "resistance" and item["status"] in {"active", "role_reversal"} and float(item["price"]) >= close]
    support = max(supports, key=lambda item: float(item["price"])) if supports else None
    resistance = min(resistances, key=lambda item: float(item["price"])) if resistances else None
    active_support = sorted([item for item in lines if item["status"] == "active" and "support" in item["type"]], key=lambda item: -float(item["score"]))
    active_resistance = sorted([item for item in lines if item["status"] == "active" and "resistance" in item["type"]], key=lambda item: -float(item["score"]))
    active_channel = next((item for item in channels if item["status"] == "active"), None)
    if active_support and not active_resistance:
        trend = "up"
    elif active_resistance and not active_support:
        trend = "down"
    elif active_support and active_resistance:
        trend = "mixed"
    else:
        trend = "range"
    current_range = None
    range_position = None
    if support and resistance and float(resistance["price"]) > float(support["price"]):
        low_price, high_price = float(support["price"]), float(resistance["price"])
        range_position = min(1.0, max(0.0, (close - low_price) / (high_price - low_price)))
        current_range = {"low": low_price, "high": high_price}
    summaries = []
    if support:
        summaries.append(f"最近{timeframe}支撑区约为{float(support['zone_low']):.2f}至{float(support['zone_high']):.2f}")
    if resistance:
        summaries.append(f"最近{timeframe}阻力区约为{float(resistance['zone_low']):.2f}至{float(resistance['zone_high']):.2f}")
    if active_support:
        summaries.append("价格仍位于有效上升支撑趋势线附近")
    if active_resistance:
        summaries.append("价格仍受有效下降阻力趋势线约束")
    if not summaries:
        summaries.append("当前没有达到显示阈值的主要技术结构")
    return {
        "nearest_support": None if support is None else _level_context(support, close),
        "nearest_resistance": None if resistance is None else _level_context(resistance, close),
        "active_support_trendline": active_support[0] if active_support else None,
        "active_resistance_trendline": active_resistance[0] if active_resistance else None,
        "active_channel": active_channel,
        "current_range": current_range,
        "active_trend": trend,
        "range_position_pct": None if range_position is None else round(range_position, 6),
        "summary_lines": summaries,
        "structure_summary": summaries,
    }


class TechnicalStructureService:
    """Analyze one or many assets with a single reusable structure pipeline."""

    def __init__(self, config: dict[str, Any] | None = None, cache_dir: str | Path | None = None):
        section = (config or {}).get("technical_structure", config or {})
        self.config = _deep_merge(DEFAULT_CONFIG, section)
        configured_cache = self.config.get("cache_dir")
        self.cache_dir = Path(cache_dir or configured_cache) if (cache_dir or configured_cache) else None

    def _frame_config(self, timeframe: str, override: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
        merged = _deep_merge(self.config, override)
        return merged, merged["timeframe"][_TIMEFRAME_KEYS[timeframe]]

    def _cache_path(
        self, symbol: str, asset_type: str, timeframe: str, adjustment: str,
        as_of: str, data_last_date: str, data_hash: str, config_hash: str,
    ) -> Path | None:
        if self.cache_dir is None:
            return None
        filename = f"{adjustment}_{as_of.replace('-', '')}_{data_last_date.replace('-', '')}_{config_hash}_{data_hash}_{ALGORITHM_VERSION}.json"
        return self.cache_dir / "technical_structure" / asset_type / symbol / timeframe / filename

    def analyze(
        self,
        symbol: str,
        asset_type: str,
        timeframe: str,
        ohlcv: pd.DataFrame,
        as_of_date: str | None = None,
        lookback_bars: int | None = None,
        adjustment: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> TechnicalStructureResult:
        tf = str(timeframe).lower()
        merged, tf_cfg = self._frame_config(tf, config)
        defaults = merged["defaults"]
        adjustment_value = "none" if asset_type == "index" else str(adjustment or defaults.get("adjustment_stock", "qfq"))
        daily = normalize_ohlcv(
            ohlcv, symbol=symbol, asset_type=asset_type, timeframe="1d",
            adjustment=adjustment_value, as_of_date=as_of_date,
        )
        include_incomplete = bool(defaults.get("include_incomplete_bar", False))
        sampled = resample_ohlcv(
            daily, tf, include_incomplete_bar=include_incomplete,
            as_of_date=as_of_date, config=merged,
        )
        display_frame = sampled.data.copy()
        structure_frame = display_frame[display_frame.get("eligible_for_structure", True) == True].reset_index(drop=True)  # noqa: E712
        if lookback_bars and int(lookback_bars) > 0:
            structure_frame = structure_frame.tail(int(lookback_bars)).reset_index(drop=True)
            display_frame = display_frame[display_frame["date"] >= structure_frame["date"].iloc[0]].reset_index(drop=True) if not structure_frame.empty else display_frame.iloc[0:0]
        requested_as_of = pd.to_datetime(as_of_date).strftime("%Y-%m-%d") if as_of_date else (_date(daily.data["date"].iloc[-1]) if not daily.data.empty else "")
        flags = sorted(set(daily.data_quality_flags + sampled.data_quality_flags))
        if len(structure_frame) < int(tf_cfg["minimum_history_bars"]):
            flags.append("insufficient_history")
        if structure_frame.empty:
            return TechnicalStructureResult(
                symbol=str(symbol).upper(), asset_type=asset_type, timeframe=tf, adjustment=sampled.adjustment,
                as_of_date=requested_as_of, bar_count=0, current_context={"summary_lines": ["有效K线不足"]},
                data_quality_flags=sorted(set(flags)), algorithm_version=ALGORITHM_VERSION,
            )

        atr = calculate_atr(structure_frame, int(defaults.get("atr_period", 14)))
        config_hash = _hash_payload({"config": merged, "timeframe": tf, "algorithm": ALGORITHM_VERSION})
        data_hash = _hash_payload(
            structure_frame[["date", "open", "high", "low", "close", "volume", "amount"]].assign(
                date=lambda x: x["date"].dt.strftime("%Y-%m-%d")
            ).fillna("-").to_dict("records")
        )
        data_last_date = _date(structure_frame["date"].iloc[-1])
        cache_path = self._cache_path(str(symbol).upper(), asset_type, tf, sampled.adjustment, requested_as_of, data_last_date, data_hash, config_hash)
        if cache_path is not None and bool(defaults.get("cache_enabled", True)) and cache_path.exists():
            try:
                cached = TechnicalStructureResult.from_dict(json.loads(cache_path.read_text(encoding="utf-8")))
                cached.cache_path = str(cache_path)
                return cached
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass

        pivots = identify_causal_pivots(
            structure_frame, timeframe=tf, atr=atr, config=tf_cfg, asset_type=asset_type,
        )
        levels = _cluster_pivots(structure_frame, pivots, atr, tf, tf_cfg, merged["breakout"])
        lines = _detect_trendlines(structure_frame, pivots, atr, tf, tf_cfg, merged["trendline"])
        channels = _detect_channels(structure_frame, pivots, atr, lines, tf, tf_cfg, merged["trendline"])
        manual_levels, manual_lines, manual_flags = _manual_items(
            merged, str(symbol).upper(), tf, sampled.adjustment, structure_frame,
        )
        levels.extend(manual_levels)
        lines.extend(manual_lines)
        flags.extend(manual_flags)
        context = _build_context(structure_frame, levels, lines, channels, tf)
        result = TechnicalStructureResult(
            symbol=str(symbol).upper(), asset_type=asset_type, timeframe=tf, adjustment=sampled.adjustment,
            as_of_date=requested_as_of, bar_count=len(structure_frame), pivots=pivots,
            horizontal_levels=levels, trendlines=lines, channels=channels,
            current_context=context, data_quality_flags=sorted(set(flags)),
            bars=bar_records(structure_frame, atr), algorithm_version=ALGORITHM_VERSION,
            cache_path=None if cache_path is None else str(cache_path),
        )
        if cache_path is not None and bool(defaults.get("cache_enabled", True)):
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        return result

    def analyze_multi_timeframe(
        self,
        symbol: str,
        asset_type: str,
        timeframes: Iterable[str],
        ohlcv: pd.DataFrame,
        as_of_date: str | None = None,
        lookback_bars: int | None = None,
        adjustment: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, TechnicalStructureResult]:
        return {
            str(timeframe): self.analyze(
                symbol=symbol, asset_type=asset_type, timeframe=str(timeframe), ohlcv=ohlcv,
                as_of_date=as_of_date, lookback_bars=lookback_bars,
                adjustment=adjustment, config=config,
            )
            for timeframe in timeframes
        }

    def analyze_many(
        self,
        symbols: list[str],
        timeframe: str,
        ohlcv_by_symbol: dict[str, pd.DataFrame],
        *,
        asset_type: str = "stock",
        as_of_date: str | None = None,
        adjustment: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, TechnicalStructureResult]:
        return {
            symbol: self.analyze(
                symbol=symbol, asset_type=asset_type, timeframe=timeframe,
                ohlcv=ohlcv_by_symbol[symbol], as_of_date=as_of_date,
                adjustment=adjustment, config=config,
            )
            for symbol in symbols if symbol in ohlcv_by_symbol
        }
