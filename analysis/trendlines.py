"""Deterministic technical line detection for OHLCV data.

The module is intentionally descriptive rather than predictive.  It detects
confirmed pivots, trend lines, parallel channels, horizontal support/resistance
levels, and early neckline candidates.  For strategy usage, pass ``as_of`` or
``as_of_index`` to analyze only the bars known at that point in time.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

import numpy as np
import pandas as pd


REQUIRED_COLUMNS = ("date", "open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class TrendlineConfig:
    pivot_window: int = 5
    atr_period: int = 20
    tolerance_pct: float = 0.01
    atr_tolerance_mult: float = 0.35
    max_trend_lines: int = 3
    min_line_touches: int = 2
    max_violation_ratio: float = 0.12
    max_candidate_pivots: int = 48
    dedup_price_pct: float = 0.006
    dedup_slope_pct: float = 0.25
    support_resistance_max_levels: int = 8
    support_resistance_atr_mult: float = 0.5
    support_resistance_pct: float = 0.01
    max_channels: int = 3
    max_necklines: int = 5
    shoulder_tolerance_pct: float = 0.06
    head_prominence_pct: float = 0.03
    double_pattern_tolerance_pct: float = 0.035
    neckline_depth_pct: float = 0.02


def _config_from_any(config: TrendlineConfig | dict | None) -> TrendlineConfig:
    if config is None:
        return TrendlineConfig()
    if isinstance(config, TrendlineConfig):
        return config
    allowed = set(TrendlineConfig.__dataclass_fields__)
    return TrendlineConfig(**{key: value for key, value in config.items() if key in allowed})


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(f"OHLCV data missing columns: {', '.join(missing)}")

    result = df.loc[:, list(REQUIRED_COLUMNS)].copy()
    result["date"] = pd.to_datetime(result["date"])
    for column in ("open", "high", "low", "close", "volume"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result = result.dropna(subset=["date", "open", "high", "low", "close"])
    return result.sort_values("date").reset_index(drop=True)


def _date_str(value) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def calculate_atr(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Calculate a deterministic rolling ATR-like range estimate."""
    price = _normalize_ohlcv(df)
    prev_close = price["close"].shift(1)
    true_range = pd.concat(
        [
            price["high"] - price["low"],
            (price["high"] - prev_close).abs(),
            (price["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(window=max(int(period), 1), min_periods=1).mean()


def _tolerance_series(price: pd.DataFrame, config: TrendlineConfig) -> pd.Series:
    atr = calculate_atr(price, config.atr_period)
    return pd.concat(
        [
            atr * float(config.atr_tolerance_mult),
            price["close"].abs() * float(config.tolerance_pct),
        ],
        axis=1,
    ).max(axis=1)


def _latest_tolerance(price: pd.DataFrame, config: TrendlineConfig) -> float:
    if price.empty:
        return 0.0
    return float(_tolerance_series(price, config).iloc[-1])


def _relation(distance: float, reference_price: float, tolerance: float) -> str:
    if abs(distance) <= max(tolerance, abs(reference_price) * 1e-9):
        return "near"
    return "above" if distance > 0 else "below"


def _line_value(slope: float, intercept: float, index: int | float) -> float:
    return float(slope * float(index) + intercept)


def _distance_payload(
    current_close: float,
    line_price: float,
    tolerance: float,
) -> dict:
    distance = float(current_close - line_price)
    distance_pct = distance / line_price * 100.0 if line_price else 0.0
    return {
        "latest_line_price": round(float(line_price), 4),
        "close_distance": round(distance, 4),
        "close_distance_pct": round(distance_pct, 4),
        "relation": _relation(distance, line_price, tolerance),
    }


def _make_line(
    price: pd.DataFrame,
    line_type: str,
    label: str,
    slope: float,
    intercept: float,
    start_index: int,
    end_index: int,
    touch_count: int = 0,
    violation_count: int = 0,
    score: float = 0.0,
    source_pivots: list[dict] | None = None,
    tolerance: float | None = None,
) -> dict:
    current_close = float(price["close"].iloc[-1])
    tol = _latest_tolerance(price, TrendlineConfig()) if tolerance is None else float(tolerance)
    start_price = _line_value(slope, intercept, start_index)
    end_price = _line_value(slope, intercept, end_index)
    latest_line_price = _line_value(slope, intercept, len(price) - 1)
    line = {
        "type": line_type,
        "label": label,
        "start_index": int(start_index),
        "end_index": int(end_index),
        "start_date": _date_str(price["date"].iloc[start_index]),
        "end_date": _date_str(price["date"].iloc[end_index]),
        "start_price": round(start_price, 4),
        "end_price": round(end_price, 4),
        "slope": round(float(slope), 8),
        "intercept": round(float(intercept), 4),
        "touch_count": int(touch_count),
        "violation_count": int(violation_count),
        "score": round(float(score), 4),
        "source_pivots": source_pivots or [],
    }
    line.update(_distance_payload(current_close, latest_line_price, tol))
    return line


def identify_pivots(df: pd.DataFrame, pivot_window: int = 5) -> list[dict]:
    """Identify confirmed fractal swing highs/lows.

    A pivot at index ``i`` is only emitted when both the left and right
    ``pivot_window`` bars are present.  In rolling use, slice the input up to
    the current as-of bar before calling this function.
    """
    price = _normalize_ohlcv(df)
    window = max(int(pivot_window), 1)
    if len(price) < window * 2 + 1:
        return []

    highs = price["high"].to_numpy(dtype=float)
    lows = price["low"].to_numpy(dtype=float)
    closes = price["close"].to_numpy(dtype=float)
    pivots: list[dict] = []

    for idx in range(window, len(price) - window):
        left_high = float(highs[idx - window:idx].max())
        right_high = float(highs[idx + 1:idx + window + 1].max())
        left_low = float(lows[idx - window:idx].min())
        right_low = float(lows[idx + 1:idx + window + 1].min())
        close_ref = max(abs(float(closes[idx])), 1e-12)

        if highs[idx] > left_high and highs[idx] > right_high:
            prominence = float(highs[idx] - max(left_high, right_high))
            pivots.append(
                {
                    "index": int(idx),
                    "date": _date_str(price["date"].iloc[idx]),
                    "price": round(float(highs[idx]), 4),
                    "type": "swing_high",
                    "strength": round(max(prominence / close_ref * 100.0, 0.0), 4),
                    "confirmed_index": int(idx + window),
                    "confirmed_date": _date_str(price["date"].iloc[idx + window]),
                }
            )

        if lows[idx] < left_low and lows[idx] < right_low:
            prominence = float(min(left_low, right_low) - lows[idx])
            pivots.append(
                {
                    "index": int(idx),
                    "date": _date_str(price["date"].iloc[idx]),
                    "price": round(float(lows[idx]), 4),
                    "type": "swing_low",
                    "strength": round(max(prominence / close_ref * 100.0, 0.0), 4),
                    "confirmed_index": int(idx + window),
                    "confirmed_date": _date_str(price["date"].iloc[idx + window]),
                }
            )

    return sorted(pivots, key=lambda item: (item["index"], item["type"]))


def _select_candidate_pivots(pivots: list[dict], config: TrendlineConfig) -> list[dict]:
    limit = int(config.max_candidate_pivots)
    if len(pivots) <= limit:
        return pivots
    recent = sorted(pivots, key=lambda item: item["index"], reverse=True)[:limit]
    return sorted(recent, key=lambda item: item["index"])


def _pivots_of_type(pivots: Iterable[dict], pivot_type: str) -> list[dict]:
    return sorted(
        [pivot for pivot in pivots if pivot.get("type") == pivot_type],
        key=lambda item: item["index"],
    )


def _candidate_score(
    price: pd.DataFrame,
    touches: list[dict],
    violation_count: int,
    violation_ratio: float,
    start_index: int,
) -> float:
    duration_score = (len(price) - 1 - start_index) / max(len(price) - 1, 1) * 20.0
    if touches:
        last_touch_index = max(int(pivot["index"]) for pivot in touches)
        avg_strength = float(np.mean([float(pivot.get("strength", 0.0)) for pivot in touches]))
    else:
        last_touch_index = start_index
        avg_strength = 0.0
    recency_score = max(0.0, 1.0 - (len(price) - 1 - last_touch_index) / max(len(price), 1)) * 25.0
    touch_score = min(len(touches), 8) * 22.0
    strength_score = min(avg_strength, 12.0) * 2.0
    penalty = violation_count * 9.0 + violation_ratio * 80.0
    return max(0.0, touch_score + duration_score + recency_score + strength_score - penalty)


def _evaluate_trend_line(
    price: pd.DataFrame,
    pivots: list[dict],
    p1: dict,
    p2: dict,
    direction: str,
    config: TrendlineConfig,
    tolerance: pd.Series,
) -> dict | None:
    idx1 = int(p1["index"])
    idx2 = int(p2["index"])
    if idx2 <= idx1:
        return None
    slope = (float(p2["price"]) - float(p1["price"])) / (idx2 - idx1)
    if direction == "uptrend" and slope <= 0:
        return None
    if direction == "downtrend" and slope >= 0:
        return None

    intercept = float(p1["price"]) - slope * idx1
    check_index = np.arange(idx1, len(price))
    line_values = slope * check_index + intercept
    tol_values = tolerance.iloc[check_index].to_numpy(dtype=float)

    if direction == "uptrend":
        observed = price["low"].iloc[check_index].to_numpy(dtype=float)
        violations = observed < (line_values - tol_values)
        pivot_type = "swing_low"
        label = "Uptrend Line"
    else:
        observed = price["high"].iloc[check_index].to_numpy(dtype=float)
        violations = observed > (line_values + tol_values)
        pivot_type = "swing_high"
        label = "Downtrend Line"

    violation_count = int(violations.sum())
    violation_ratio = violation_count / max(len(check_index), 1)
    if violation_ratio > float(config.max_violation_ratio):
        return None

    touches: list[dict] = []
    for pivot in _pivots_of_type(pivots, pivot_type):
        pivot_index = int(pivot["index"])
        if pivot_index < idx1:
            continue
        expected = _line_value(slope, intercept, pivot_index)
        if abs(float(pivot["price"]) - expected) <= float(tolerance.iloc[pivot_index]):
            touches.append(pivot)

    if len(touches) < int(config.min_line_touches):
        return None

    score = _candidate_score(price, touches, violation_count, violation_ratio, idx1)
    return _make_line(
        price=price,
        line_type=direction,
        label=label,
        slope=slope,
        intercept=intercept,
        start_index=idx1,
        end_index=len(price) - 1,
        touch_count=len(touches),
        violation_count=violation_count,
        score=score,
        source_pivots=[
            {
                "index": int(pivot["index"]),
                "date": pivot["date"],
                "price": round(float(pivot["price"]), 4),
                "strength": round(float(pivot.get("strength", 0.0)), 4),
            }
            for pivot in touches
        ],
        tolerance=float(tolerance.iloc[-1]),
    )


def _is_duplicate_line(
    existing: dict,
    candidate: dict,
    latest_close: float,
    config: TrendlineConfig,
) -> bool:
    price_gap = abs(float(existing["latest_line_price"]) - float(candidate["latest_line_price"]))
    if price_gap > abs(latest_close) * float(config.dedup_price_pct):
        return False
    slope_gap = abs(float(existing["slope"]) - float(candidate["slope"]))
    slope_ref = max(abs(float(existing["slope"])), abs(float(candidate["slope"])), 1e-9)
    return slope_gap / slope_ref <= float(config.dedup_slope_pct)


def _rank_lines(lines: list[dict], price: pd.DataFrame, config: TrendlineConfig) -> list[dict]:
    ranked = sorted(
        lines,
        key=lambda item: (
            -float(item["score"]),
            -int(item["touch_count"]),
            -int(item["start_index"]),
            float(item["slope"]),
        ),
    )
    latest_close = float(price["close"].iloc[-1])
    selected: list[dict] = []
    for candidate in ranked:
        if any(_is_duplicate_line(line, candidate, latest_close, config) for line in selected):
            continue
        selected.append(candidate)
        if len(selected) >= int(config.max_trend_lines):
            break
    return selected


def detect_uptrend_lines(
    df: pd.DataFrame,
    pivots: list[dict] | None = None,
    config: TrendlineConfig | dict | None = None,
) -> list[dict]:
    price = _normalize_ohlcv(df)
    cfg = _config_from_any(config)
    pivot_data = pivots if pivots is not None else identify_pivots(price, cfg.pivot_window)
    lows = _select_candidate_pivots(_pivots_of_type(pivot_data, "swing_low"), cfg)
    tolerance = _tolerance_series(price, cfg)
    candidates: list[dict] = []
    for left in range(len(lows) - 1):
        for right in range(left + 1, len(lows)):
            line = _evaluate_trend_line(price, lows, lows[left], lows[right], "uptrend", cfg, tolerance)
            if line is not None:
                candidates.append(line)
    return _rank_lines(candidates, price, cfg)


def detect_downtrend_lines(
    df: pd.DataFrame,
    pivots: list[dict] | None = None,
    config: TrendlineConfig | dict | None = None,
) -> list[dict]:
    price = _normalize_ohlcv(df)
    cfg = _config_from_any(config)
    pivot_data = pivots if pivots is not None else identify_pivots(price, cfg.pivot_window)
    highs = _select_candidate_pivots(_pivots_of_type(pivot_data, "swing_high"), cfg)
    tolerance = _tolerance_series(price, cfg)
    candidates: list[dict] = []
    for left in range(len(highs) - 1):
        for right in range(left + 1, len(highs)):
            line = _evaluate_trend_line(price, highs, highs[left], highs[right], "downtrend", cfg, tolerance)
            if line is not None:
                candidates.append(line)
    return _rank_lines(candidates, price, cfg)


def _cluster_pivots_by_price(
    price: pd.DataFrame,
    pivots: list[dict],
    level_type: str,
    config: TrendlineConfig,
) -> list[dict]:
    if not pivots:
        return []

    latest_close = float(price["close"].iloc[-1])
    atr = calculate_atr(price, config.atr_period)
    cluster_tolerance = max(
        float(atr.iloc[-1]) * float(config.support_resistance_atr_mult),
        abs(latest_close) * float(config.support_resistance_pct),
    )

    clusters: list[list[dict]] = []
    for pivot in sorted(pivots, key=lambda item: float(item["price"])):
        matched = False
        for cluster in clusters:
            cluster_price = float(np.mean([float(item["price"]) for item in cluster]))
            if abs(float(pivot["price"]) - cluster_price) <= cluster_tolerance:
                cluster.append(pivot)
                matched = True
                break
        if not matched:
            clusters.append([pivot])

    levels: list[dict] = []
    latest_index = len(price) - 1
    for cluster in clusters:
        weights = np.array([max(float(item.get("strength", 0.0)), 0.1) for item in cluster])
        values = np.array([float(item["price"]) for item in cluster])
        level_price = float(np.average(values, weights=weights))
        last_touch = max(cluster, key=lambda item: int(item["index"]))
        avg_strength = float(np.mean([float(item.get("strength", 0.0)) for item in cluster]))
        recency_score = max(0.0, 1.0 - (latest_index - int(last_touch["index"])) / max(len(price), 1)) * 35.0
        strength_score = min(len(cluster), 10) * 14.0 + min(avg_strength, 12.0) * 2.5 + recency_score
        distance = latest_close - level_price
        levels.append(
            {
                "type": level_type,
                "label": "Support" if level_type == "support" else "Resistance",
                "price": round(level_price, 4),
                "touch_count": int(len(cluster)),
                "last_touch_date": last_touch["date"],
                "last_touch_index": int(last_touch["index"]),
                "strength_score": round(strength_score, 4),
                "member_indices": [int(item["index"]) for item in sorted(cluster, key=lambda x: x["index"])],
                "close_distance": round(float(distance), 4),
                "close_distance_pct": round(float(distance / level_price * 100.0), 4) if level_price else 0.0,
                "relation": _relation(distance, level_price, cluster_tolerance),
            }
        )

    return sorted(
        levels,
        key=lambda item: (-float(item["strength_score"]), -int(item["last_touch_index"]), float(item["price"])),
    )[: int(config.support_resistance_max_levels)]


def detect_support_resistance(
    df: pd.DataFrame,
    pivots: list[dict] | None = None,
    config: TrendlineConfig | dict | None = None,
) -> dict:
    price = _normalize_ohlcv(df)
    cfg = _config_from_any(config)
    pivot_data = pivots if pivots is not None else identify_pivots(price, cfg.pivot_window)
    return {
        "support": _cluster_pivots_by_price(
            price,
            _pivots_of_type(pivot_data, "swing_low"),
            "support",
            cfg,
        ),
        "resistance": _cluster_pivots_by_price(
            price,
            _pivots_of_type(pivot_data, "swing_high"),
            "resistance",
            cfg,
        ),
    }


def _channel_from_line(
    price: pd.DataFrame,
    base_line: dict,
    opposite_pivots: list[dict],
    channel_type: str,
    config: TrendlineConfig,
) -> dict | None:
    if not opposite_pivots:
        return None

    slope = float(base_line["slope"])
    intercept = float(base_line["intercept"])
    start_index = int(base_line["start_index"])
    tolerance = _tolerance_series(price, config)
    candidates = []

    for pivot in opposite_pivots:
        pivot_index = int(pivot["index"])
        if pivot_index < start_index:
            continue
        base_value = _line_value(slope, intercept, pivot_index)
        offset = float(pivot["price"]) - base_value
        if channel_type == "uptrend_channel" and offset > float(tolerance.iloc[pivot_index]):
            candidates.append((offset, pivot))
        elif channel_type == "downtrend_channel" and -offset > float(tolerance.iloc[pivot_index]):
            candidates.append((-offset, pivot))

    if not candidates:
        return None

    width, anchor = max(candidates, key=lambda item: (item[0], int(item[1]["index"])))
    if channel_type == "uptrend_channel":
        parallel_intercept = intercept + width
        label = "Channel Upper"
        parallel_type = "channel_upper"
        touch_source = "swing_high"
        expected_side = "upper"
    else:
        parallel_intercept = intercept - width
        label = "Channel Lower"
        parallel_type = "channel_lower"
        touch_source = "swing_low"
        expected_side = "lower"

    touches = []
    violations = 0
    for pivot in _pivots_of_type(opposite_pivots, touch_source):
        pivot_index = int(pivot["index"])
        if pivot_index < start_index:
            continue
        expected = _line_value(slope, parallel_intercept, pivot_index)
        diff = float(pivot["price"]) - expected
        tol = float(tolerance.iloc[pivot_index])
        if abs(diff) <= tol:
            touches.append(pivot)
        elif expected_side == "upper" and diff > tol:
            violations += 1
        elif expected_side == "lower" and diff < -tol:
            violations += 1

    parallel = _make_line(
        price=price,
        line_type=parallel_type,
        label=label,
        slope=slope,
        intercept=parallel_intercept,
        start_index=start_index,
        end_index=len(price) - 1,
        touch_count=max(len(touches), 1),
        violation_count=violations,
        score=float(base_line["score"]),
        source_pivots=[
            {
                "index": int(anchor["index"]),
                "date": anchor["date"],
                "price": round(float(anchor["price"]), 4),
                "strength": round(float(anchor.get("strength", 0.0)), 4),
            }
        ],
        tolerance=float(tolerance.iloc[-1]),
    )
    score = float(base_line["score"]) + max(len(touches), 1) * 12.0 - violations * 8.0
    return {
        "type": channel_type,
        "base_line": base_line,
        "parallel_line": parallel,
        "width": round(float(width), 4),
        "start_date": base_line["start_date"],
        "end_date": base_line["end_date"],
        "score": round(max(score, 0.0), 4),
    }


def detect_trend_channels(
    df: pd.DataFrame,
    uptrend_lines: list[dict] | None = None,
    downtrend_lines: list[dict] | None = None,
    pivots: list[dict] | None = None,
    config: TrendlineConfig | dict | None = None,
) -> list[dict]:
    price = _normalize_ohlcv(df)
    cfg = _config_from_any(config)
    pivot_data = pivots if pivots is not None else identify_pivots(price, cfg.pivot_window)
    up_lines = uptrend_lines if uptrend_lines is not None else detect_uptrend_lines(price, pivot_data, cfg)
    down_lines = downtrend_lines if downtrend_lines is not None else detect_downtrend_lines(price, pivot_data, cfg)

    channels: list[dict] = []
    highs = _pivots_of_type(pivot_data, "swing_high")
    lows = _pivots_of_type(pivot_data, "swing_low")
    for line in up_lines:
        channel = _channel_from_line(price, line, highs, "uptrend_channel", cfg)
        if channel is not None:
            channels.append(channel)
    for line in down_lines:
        channel = _channel_from_line(price, line, lows, "downtrend_channel", cfg)
        if channel is not None:
            channels.append(channel)

    return sorted(channels, key=lambda item: -float(item["score"]))[: int(cfg.max_channels)]


def _between(pivots: list[dict], start_index: int, end_index: int, pivot_type: str) -> list[dict]:
    return [
        pivot
        for pivot in pivots
        if pivot.get("type") == pivot_type and start_index < int(pivot["index"]) < end_index
    ]


def _neckline_line(
    price: pd.DataFrame,
    pattern_type: str,
    start_index: int,
    start_price: float,
    end_index: int,
    end_price: float,
    confidence: float,
    source_pivots: list[dict],
    bearish: bool,
    config: TrendlineConfig,
) -> dict:
    if end_index == start_index:
        slope = 0.0
    else:
        slope = (float(end_price) - float(start_price)) / (end_index - start_index)
    intercept = float(start_price) - slope * start_index
    line = _make_line(
        price=price,
        line_type="neckline",
        label=f"Neckline: {pattern_type}",
        slope=slope,
        intercept=intercept,
        start_index=int(start_index),
        end_index=len(price) - 1,
        score=confidence,
        source_pivots=source_pivots,
        tolerance=_latest_tolerance(price, config),
    )
    line_price = _line_value(slope, intercept, len(price) - 1)
    current_close = float(price["close"].iloc[-1])
    tolerance = _latest_tolerance(price, config)
    if bearish:
        if current_close < line_price - tolerance:
            breakout = "broken_down"
        elif abs(current_close - line_price) <= tolerance:
            breakout = "testing"
        else:
            breakout = "not_broken"
    else:
        if current_close > line_price + tolerance:
            breakout = "broken_up"
        elif abs(current_close - line_price) <= tolerance:
            breakout = "testing"
        else:
            breakout = "not_broken"
    return {
        "pattern_type": pattern_type,
        "line": line,
        "confidence": round(float(confidence), 4),
        "breakout_status": breakout,
        "source_pivots": source_pivots,
    }


def _source_pivots(*items: dict) -> list[dict]:
    return [
        {
            "index": int(item["index"]),
            "date": item["date"],
            "price": round(float(item["price"]), 4),
            "type": item.get("type", ""),
            "strength": round(float(item.get("strength", 0.0)), 4),
        }
        for item in items
    ]


def _ratio_gap(left: float, right: float) -> float:
    denominator = max((abs(left) + abs(right)) / 2.0, 1e-12)
    return abs(left - right) / denominator


def detect_necklines(
    df: pd.DataFrame,
    pivots: list[dict] | None = None,
    config: TrendlineConfig | dict | None = None,
) -> list[dict]:
    price = _normalize_ohlcv(df)
    cfg = _config_from_any(config)
    pivot_data = pivots if pivots is not None else identify_pivots(price, cfg.pivot_window)
    highs = _pivots_of_type(pivot_data, "swing_high")
    lows = _pivots_of_type(pivot_data, "swing_low")
    necklines: list[dict] = []

    for idx in range(len(highs) - 2):
        left, head, right = highs[idx], highs[idx + 1], highs[idx + 2]
        if not (left["index"] < head["index"] < right["index"]):
            continue
        if not (
            float(head["price"]) > float(left["price"]) * (1 + cfg.head_prominence_pct)
            and float(head["price"]) > float(right["price"]) * (1 + cfg.head_prominence_pct)
        ):
            continue
        shoulder_gap = _ratio_gap(float(left["price"]), float(right["price"]))
        if shoulder_gap > cfg.shoulder_tolerance_pct:
            continue
        low_left = _between(pivot_data, int(left["index"]), int(head["index"]), "swing_low")
        low_right = _between(pivot_data, int(head["index"]), int(right["index"]), "swing_low")
        if not low_left or not low_right:
            continue
        neck_left = min(low_left, key=lambda item: float(item["price"]))
        neck_right = min(low_right, key=lambda item: float(item["price"]))
        prominence = min(
            float(head["price"]) / max(float(left["price"]), 1e-12) - 1.0,
            float(head["price"]) / max(float(right["price"]), 1e-12) - 1.0,
        )
        confidence = 55.0 + min(prominence / cfg.head_prominence_pct, 3.0) * 10.0
        confidence += max(0.0, 1.0 - shoulder_gap / cfg.shoulder_tolerance_pct) * 15.0
        necklines.append(
            _neckline_line(
                price,
                "Head and Shoulders",
                int(neck_left["index"]),
                float(neck_left["price"]),
                int(neck_right["index"]),
                float(neck_right["price"]),
                min(confidence, 100.0),
                _source_pivots(left, neck_left, head, neck_right, right),
                bearish=True,
                config=cfg,
            )
        )

    for idx in range(len(lows) - 2):
        left, head, right = lows[idx], lows[idx + 1], lows[idx + 2]
        if not (left["index"] < head["index"] < right["index"]):
            continue
        if not (
            float(head["price"]) < float(left["price"]) * (1 - cfg.head_prominence_pct)
            and float(head["price"]) < float(right["price"]) * (1 - cfg.head_prominence_pct)
        ):
            continue
        shoulder_gap = _ratio_gap(float(left["price"]), float(right["price"]))
        if shoulder_gap > cfg.shoulder_tolerance_pct:
            continue
        high_left = _between(pivot_data, int(left["index"]), int(head["index"]), "swing_high")
        high_right = _between(pivot_data, int(head["index"]), int(right["index"]), "swing_high")
        if not high_left or not high_right:
            continue
        neck_left = max(high_left, key=lambda item: float(item["price"]))
        neck_right = max(high_right, key=lambda item: float(item["price"]))
        prominence = min(
            1.0 - float(head["price"]) / max(float(left["price"]), 1e-12),
            1.0 - float(head["price"]) / max(float(right["price"]), 1e-12),
        )
        confidence = 55.0 + min(prominence / cfg.head_prominence_pct, 3.0) * 10.0
        confidence += max(0.0, 1.0 - shoulder_gap / cfg.shoulder_tolerance_pct) * 15.0
        necklines.append(
            _neckline_line(
                price,
                "Inverse Head and Shoulders",
                int(neck_left["index"]),
                float(neck_left["price"]),
                int(neck_right["index"]),
                float(neck_right["price"]),
                min(confidence, 100.0),
                _source_pivots(left, neck_left, head, neck_right, right),
                bearish=False,
                config=cfg,
            )
        )

    for idx in range(len(highs) - 1):
        left, right = highs[idx], highs[idx + 1]
        gap = _ratio_gap(float(left["price"]), float(right["price"]))
        if gap > cfg.double_pattern_tolerance_pct:
            continue
        middle_lows = _between(pivot_data, int(left["index"]), int(right["index"]), "swing_low")
        if not middle_lows:
            continue
        neck = min(middle_lows, key=lambda item: float(item["price"]))
        avg_top = (float(left["price"]) + float(right["price"])) / 2.0
        depth = (avg_top - float(neck["price"])) / max(avg_top, 1e-12)
        if depth < cfg.neckline_depth_pct:
            continue
        confidence = 45.0 + max(0.0, 1.0 - gap / cfg.double_pattern_tolerance_pct) * 25.0
        confidence += min(depth / cfg.neckline_depth_pct, 3.0) * 8.0
        necklines.append(
            _neckline_line(
                price,
                "Double Top",
                int(neck["index"]),
                float(neck["price"]),
                len(price) - 1,
                float(neck["price"]),
                min(confidence, 100.0),
                _source_pivots(left, neck, right),
                bearish=True,
                config=cfg,
            )
        )

    for idx in range(len(lows) - 1):
        left, right = lows[idx], lows[idx + 1]
        gap = _ratio_gap(float(left["price"]), float(right["price"]))
        if gap > cfg.double_pattern_tolerance_pct:
            continue
        middle_highs = _between(pivot_data, int(left["index"]), int(right["index"]), "swing_high")
        if not middle_highs:
            continue
        neck = max(middle_highs, key=lambda item: float(item["price"]))
        avg_bottom = (float(left["price"]) + float(right["price"])) / 2.0
        depth = (float(neck["price"]) - avg_bottom) / max(avg_bottom, 1e-12)
        if depth < cfg.neckline_depth_pct:
            continue
        confidence = 45.0 + max(0.0, 1.0 - gap / cfg.double_pattern_tolerance_pct) * 25.0
        confidence += min(depth / cfg.neckline_depth_pct, 3.0) * 8.0
        necklines.append(
            _neckline_line(
                price,
                "Double Bottom",
                int(neck["index"]),
                float(neck["price"]),
                len(price) - 1,
                float(neck["price"]),
                min(confidence, 100.0),
                _source_pivots(left, neck, right),
                bearish=False,
                config=cfg,
            )
        )

    return sorted(
        necklines,
        key=lambda item: (
            -float(item["confidence"]),
            -int(item["line"]["start_index"]),
            str(item["pattern_type"]),
        ),
    )[: int(cfg.max_necklines)]


def _slice_as_of(
    price: pd.DataFrame,
    as_of=None,
    as_of_index: int | None = None,
) -> pd.DataFrame:
    if as_of_index is not None:
        index = max(0, min(int(as_of_index), len(price) - 1))
        return price.iloc[: index + 1].copy()
    if as_of is not None:
        cutoff = pd.Timestamp(as_of)
        return price[price["date"] <= cutoff].copy().reset_index(drop=True)
    return price


def analyze_trendlines(
    df: pd.DataFrame,
    config: TrendlineConfig | dict | None = None,
    as_of=None,
    as_of_index: int | None = None,
) -> dict:
    """Return the legacy schema using the causal technical-structure engine."""
    from analysis.technical_structure import TechnicalStructureService

    cfg = _config_from_any(config)
    price = _slice_as_of(_normalize_ohlcv(df), as_of=as_of, as_of_index=as_of_index)
    if price.empty:
        return {
            "config": asdict(cfg),
            "latest": None,
            "pivots": [],
            "uptrend_lines": [],
            "downtrend_lines": [],
            "channels": [],
            "support": [],
            "resistance": [],
            "necklines": [],
        }

    latest_close = float(price["close"].iloc[-1])

    technical_config = {
        "technical_structure": {
            "defaults": {"cache_enabled": False, "include_incomplete_bar": True},
            "timeframe": {
                "daily": {
                    "pivot_reversal_atr": max(0.7, float(cfg.atr_tolerance_mult) * 4.0),
                    "level_tolerance_pct": float(cfg.support_resistance_pct),
                    "level_tolerance_atr": float(cfg.support_resistance_atr_mult),
                    "max_support": max(1, int(cfg.support_resistance_max_levels) // 2),
                    "max_resistance": max(1, int(cfg.support_resistance_max_levels) // 2),
                    "max_trendlines_per_type": int(cfg.max_trend_lines),
                    "max_candidate_pivots": int(cfg.max_candidate_pivots),
                }
            },
            "trendline": {
                "touch_tolerance_atr": max(float(cfg.atr_tolerance_mult), 0.1),
                "max_violation_ratio": float(cfg.max_violation_ratio),
                "dedup_slope_ratio": float(cfg.dedup_slope_pct),
            },
        }
    }
    result = TechnicalStructureService(technical_config).analyze(
        symbol="LEGACY", asset_type="other", timeframe="1d", ohlcv=price, adjustment="none",
    )

    def legacy_pivot(item: dict) -> dict:
        return {
            "type": "swing_low" if item["pivot_type"] == "low" else "swing_high",
            "index": int(item["bar_index"]), "date": item["pivot_date"], "price": float(item["price"]),
            "strength": float(item.get("strength", 0.0)),
            "confirmed_index": int(item["confirmation_bar_index"]),
            "confirmed_date": item["confirmation_date"],
        }

    tolerance = _latest_tolerance(price, cfg)

    def legacy_line(item: dict, label: str) -> dict:
        latest_price = float(item["latest_price"])
        distance = latest_close - latest_price
        distance_pct = item.get("distance_pct")
        return {
            "type": "uptrend" if "support" in item["type"] else "downtrend", "label": label,
            "start_index": int(item["start_bar_index"]), "end_index": int(item["projection_end_bar_index"]),
            "start_date": item["start_date"], "end_date": item["projection_end_date"],
            "start_price": float(item["start_price"]), "end_price": float(item["projection_end_price"]),
            "slope": float(item["slope_per_bar"]), "intercept": float(item["intercept"]),
            "touch_count": int(item.get("touch_count", 0)),
            "violation_count": int(item.get("violation_count", 0)), "score": float(item.get("score", 0.0)),
            "source_pivots": list(item.get("touch_pivot_ids", [])), "latest_line_price": latest_price,
            "close_distance": round(distance, 4),
            "close_distance_pct": None if distance_pct is None else round(float(distance_pct) * 100.0, 4),
            "relation": _relation(distance, latest_price, tolerance), "status": item.get("status", "active"),
            "confirmation_date": item.get("confirmation_date"),
        }

    automatic_lines = [item for item in result.trendlines if item.get("source") == "automatic"]
    line_by_id = {item["id"]: item for item in automatic_lines}
    uptrend_lines = [legacy_line(item, "Uptrend Support") for item in automatic_lines if item["type"] == "ascending_support"]
    downtrend_lines = [legacy_line(item, "Downtrend Resistance") for item in automatic_lines if item["type"] == "descending_resistance"]

    def legacy_level(item: dict) -> dict:
        level_price = float(item["price"])
        distance = latest_close - level_price
        return {
            "type": item["type"], "price": level_price, "touch_count": int(item.get("touch_count", 0)),
            "strength_score": float(item.get("score", 0.0)), "first_touch_date": item.get("first_touch_date"),
            "last_touch_date": item.get("last_touch_date"), "latest_line_price": level_price,
            "close_distance": round(distance, 4),
            "close_distance_pct": round(float(item.get("distance_pct", 0.0)) * 100.0, 4),
            "relation": _relation(distance, level_price, tolerance), "status": item.get("status", "active"),
        }

    channels = []
    for item in result.channels:
        base = line_by_id.get(item.get("base_line_id"))
        if base is None:
            continue
        base_legacy = legacy_line(base, "Channel Base")
        parallel = item["upper_line"] if item["type"] == "ascending_channel" else item["lower_line"]
        parallel_price = float(parallel["intercept"]) + float(parallel["slope_per_bar"]) * (len(price) - 1)
        parallel_legacy = {
            **base_legacy,
            "label": "Channel Upper" if item["type"] == "ascending_channel" else "Channel Lower",
            "start_price": float(parallel["start_price"]), "end_price": float(parallel["projection_end_price"]),
            "intercept": float(parallel["intercept"]), "latest_line_price": parallel_price,
        }
        channels.append({
            "type": "uptrend_channel" if item["type"] == "ascending_channel" else "downtrend_channel",
            "base_line": base_legacy, "parallel_line": parallel_legacy,
            "score": float(item.get("score", 0.0)),
            "width": abs(parallel_price - float(base["latest_price"])),
        })

    support = [legacy_level(item) for item in result.horizontal_levels if item["type"] == "support"]
    resistance = [legacy_level(item) for item in result.horizontal_levels if item["type"] == "resistance"]

    return {
        "config": asdict(cfg),
        "latest": {
            "index": int(len(price) - 1),
            "date": _date_str(price["date"].iloc[-1]),
            "close": round(latest_close, 4),
        },
        "pivots": [legacy_pivot(item) for item in result.pivots],
        "uptrend_lines": uptrend_lines,
        "downtrend_lines": downtrend_lines,
        "channels": channels,
        "support": support,
        "resistance": resistance,
        "necklines": [],
    }
