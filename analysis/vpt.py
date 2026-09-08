"""VPT-01 volume-expansion and supply-contraction research filter.

The module is deterministic and side-effect free.  Every result for date t is
calculated from bars up to t only; report and persistence orchestration live in
the CLI layer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import json
import math
from pathlib import Path
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

from analysis.screener import _load_kline, _load_stock_name_map, _resolve_symbols, _slice_as_of


VPT_STATES = (
    "NONE",
    "SPIKE_DETECTED",
    "TREND_CONFIRMING",
    "QUALIFIED",
    "WEAKENING",
    "FAILED",
)
VPT_CANDIDATE_STATES = VPT_STATES[1:5]


@dataclass(frozen=True)
class VPTConfig:
    """Central VPT-01 parameters; ratios are decimals unless noted otherwise."""

    lookback_volume: int = 20
    spike_window: int = 15
    observation_min_days: int = 5
    observation_max_days: int = 15
    volume_spike_min: float = 1.80
    t0_return_min: float = 0.03
    t0_close_location_min: float = 0.60
    near_high_tolerance: float = 0.02
    effort_volume_ratio: float = 2.50
    effort_return_max: float = 0.015
    effort_close_location_max: float = 0.40
    effort_upper_shadow_min: float = 0.45
    up_day_threshold: float = 0.005
    down_day_threshold: float = -0.005
    direction_min_days: int = 1
    udvr_good: float = 1.20
    udvr_strong: float = 1.35
    udvr_very_strong: float = 1.50
    dv_good: float = 0.15
    dv_strong: float = 0.30
    pullback_max_days: int = 5
    prior_advance_days: int = 5
    pvr_good: float = 0.80
    pvr_strong: float = 0.65
    pvr_warning: float = 1.00
    pvr_severe: float = 1.20
    ma20_slope_days: int = 5
    structure_window: int = 5
    higher_low_tolerance: float = 0.015
    supply_expansion_volume: float = 1.50
    supply_expansion_return: float = -0.02
    supply_recent_days: int = 5
    ma20_break_days: int = 2
    breakout_break_days: int = 2
    breakout_failure_days: int = 3
    resume_gap_calendar_days: int = 15
    exclude_st: bool = True
    candidate_score: float = 70.0
    strong_candidate_score: float = 80.0
    elite_candidate_score: float = 90.0

    @classmethod
    def from_mapping(cls, values: Mapping[str, object] | None) -> "VPTConfig":
        allowed = {item.name for item in fields(cls)}
        payload = {key: value for key, value in dict(values or {}).items() if key in allowed}
        return cls(**payload)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _linear_score(value: float | None, low: float, high: float, points: float, *, inverse: bool = False) -> float:
    if value is None or high <= low:
        return 0.0
    scaled = min(1.0, max(0.0, (value - low) / (high - low)))
    return points * (1.0 - scaled if inverse else scaled)


def prepare_vpt_frame(df: pd.DataFrame, cfg: VPTConfig) -> pd.DataFrame:
    required = {"date", "open", "high", "low", "close", "volume"}
    if df is None or df.empty or not required.issubset(df.columns):
        return pd.DataFrame(columns=sorted(required))
    work = df.copy()
    work["date"] = pd.to_datetime(work["date"].astype(str).str.replace("-", "", regex=False), format="%Y%m%d", errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        work[column] = pd.to_numeric(work[column], errors="coerce")
    work = (
        work.dropna(subset=list(required))
        .loc[lambda value: value["volume"] > 0]
        .sort_values("date")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )
    work["daily_return"] = work["close"].pct_change(fill_method=None)
    work["base_volume"] = work["volume"].rolling(cfg.lookback_volume, min_periods=cfg.lookback_volume).median().shift(1)
    work["volume_spike_ratio"] = work["volume"] / work["base_volume"].replace(0, np.nan)
    work["rolling_high_before"] = work["high"].rolling(20, min_periods=20).max().shift(1)
    spread = (work["high"] - work["low"]).clip(lower=1e-12)
    work["close_location"] = (work["close"] - work["low"]) / spread
    work["upper_shadow_ratio"] = (work["high"] - work[["open", "close"]].max(axis=1)) / spread
    work["ma10"] = work["close"].rolling(10, min_periods=10).mean()
    work["ma20"] = work["close"].rolling(20, min_periods=20).mean()
    work["ma20_slope"] = work["ma20"] / work["ma20"].shift(cfg.ma20_slope_days) - 1.0
    work["calendar_gap_days"] = work["date"].diff().dt.days
    return work


def detect_volume_spike(frame: pd.DataFrame, cfg: VPTConfig) -> list[int]:
    """Return recent raw volume-spike positions, oldest to newest."""
    if frame.empty:
        return []
    start = max(cfg.lookback_volume, len(frame) - cfg.spike_window)
    ratios = pd.to_numeric(frame["volume_spike_ratio"], errors="coerce")
    return [int(index) for index in frame.index[start:] if _finite(ratios.iloc[index]) is not None and ratios.iloc[index] >= cfg.volume_spike_min]


def evaluate_t0_quality(frame: pd.DataFrame, index: int, cfg: VPTConfig) -> dict[str, object]:
    row = frame.iloc[index]
    daily_return = _finite(row.get("daily_return"))
    spike_ratio = _finite(row.get("volume_spike_ratio"))
    close_location = _finite(row.get("close_location"))
    upper_shadow = _finite(row.get("upper_shadow_ratio"))
    prior_high = _finite(row.get("rolling_high_before"))
    close = _finite(row.get("close"))
    gap = _finite(row.get("calendar_gap_days"))
    breakout = bool(prior_high and close and close >= prior_high)
    near_high = bool(prior_high and close and close >= prior_high * (1.0 - cfg.near_high_tolerance))
    resumed_after_gap = bool(gap is not None and gap > cfg.resume_gap_calendar_days)
    weak_conditions = []
    if daily_return is None or daily_return < cfg.effort_return_max:
        weak_conditions.append("LOW_PRICE_RESPONSE")
    if close_location is None or close_location < cfg.effort_close_location_max:
        weak_conditions.append("LOW_CLOSE_LOCATION")
    if upper_shadow is not None and upper_shadow > cfg.effort_upper_shadow_min:
        weak_conditions.append("LONG_UPPER_SHADOW")
    effort_no_result = bool(spike_ratio is not None and spike_ratio >= cfg.effort_volume_ratio and weak_conditions)
    valid = bool(
        spike_ratio is not None
        and spike_ratio >= cfg.volume_spike_min
        and daily_return is not None
        and daily_return >= cfg.t0_return_min
        and close_location is not None
        and close_location >= cfg.t0_close_location_min
        and near_high
        and not resumed_after_gap
    )
    return {
        "index": index,
        "valid": valid,
        "breakout": breakout,
        "near_high": near_high,
        "resumed_after_gap": resumed_after_gap,
        "effort_no_result": effort_no_result,
        "effort_weak_conditions": weak_conditions,
        "t0_return": daily_return,
        "t0_volume_spike_ratio": spike_ratio,
        "t0_close_location": close_location,
        "t0_upper_shadow_ratio": upper_shadow,
        "breakout_level": prior_high,
    }


def calculate_udvr(post_t0: pd.DataFrame, cfg: VPTConfig) -> dict[str, object]:
    up = post_t0.loc[post_t0["daily_return"] > cfg.up_day_threshold, "volume"].dropna()
    down = post_t0.loc[post_t0["daily_return"] < cfg.down_day_threshold, "volume"].dropna()
    valid = len(up) >= cfg.direction_min_days and len(down) >= cfg.direction_min_days and float(down.median()) > 0
    return {
        "udvr": float(up.median() / down.median()) if valid else None,
        "udvr_valid": bool(valid),
        "up_day_count": int(len(up)),
        "down_day_count": int(len(down)),
        "up_volume_median": float(up.median()) if len(up) else None,
        "down_volume_median": float(down.median()) if len(down) else None,
    }


def calculate_directional_volume(post_t0: pd.DataFrame, cfg: VPTConfig) -> float | None:
    up = float(post_t0.loc[post_t0["daily_return"] > cfg.up_day_threshold, "volume"].sum())
    down = float(post_t0.loc[post_t0["daily_return"] < cfg.down_day_threshold, "volume"].sum())
    denominator = up + down
    return (up - down) / denominator if denominator > 0 else None


def detect_pullback(post_t0: pd.DataFrame, cfg: VPTConfig) -> dict[str, object]:
    """Find the latest 1-N down-day run and its preceding advance volume."""
    if post_t0.empty:
        return {"pvr": None, "pvr_valid": False, "pullback_start": None, "pullback_end": None}
    is_down = post_t0["daily_return"] < cfg.down_day_threshold
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for position, down in enumerate(is_down.tolist()):
        if down and start is None:
            start = position
        if start is not None and (not down or position == len(is_down) - 1):
            end = position if down and position == len(is_down) - 1 else position - 1
            if 1 <= end - start + 1 <= cfg.pullback_max_days:
                runs.append((start, end))
            start = None
    if not runs:
        return {"pvr": None, "pvr_valid": False, "pullback_start": None, "pullback_end": None}
    start, end = runs[-1]
    pullback = post_t0.iloc[start : end + 1]
    prior = post_t0.iloc[max(0, start - cfg.prior_advance_days) : start]
    prior = prior[prior["daily_return"] > cfg.up_day_threshold]
    pullback_volume = _finite(pullback["volume"].median())
    advance_volume = _finite(prior["volume"].median()) if not prior.empty else None
    valid = bool(pullback_volume is not None and advance_volume is not None and advance_volume > 0)
    return {
        "pvr": pullback_volume / advance_volume if valid else None,
        "pvr_valid": valid,
        "pullback_start": post_t0.iloc[start]["date"].strftime("%Y%m%d"),
        "pullback_end": post_t0.iloc[end]["date"].strftime("%Y%m%d"),
        "pullback_days": int(end - start + 1),
    }


def evaluate_price_structure(frame: pd.DataFrame, t0_index: int, cfg: VPTConfig) -> dict[str, object]:
    latest = frame.iloc[-1]
    window = cfg.structure_window
    recent = frame.tail(window)
    previous = frame.iloc[max(0, len(frame) - 2 * window) : max(0, len(frame) - window)]
    recent_high = _finite(recent["high"].max()) if not recent.empty else None
    recent_low = _finite(recent["low"].min()) if not recent.empty else None
    previous_high = _finite(previous["high"].max()) if len(previous) == window else None
    previous_low = _finite(previous["low"].min()) if len(previous) == window else None
    higher_high = bool(recent_high is not None and previous_high is not None and recent_high > previous_high)
    higher_low = bool(
        recent_low is not None
        and previous_low is not None
        and recent_low >= previous_low * (1.0 - cfg.higher_low_tolerance)
    )
    post_t0 = frame.iloc[t0_index + 1 :]
    post_recent = post_t0.tail(window)
    post_previous = post_t0.iloc[-2 * window : -window] if len(post_t0) >= 2 * window else pd.DataFrame()
    post_recent_low = _finite(post_recent["low"].min()) if len(post_recent) == window else None
    post_previous_low = _finite(post_previous["low"].min()) if len(post_previous) == window else None
    lower_low = bool(
        post_recent_low is not None
        and post_previous_low is not None
        and post_recent_low < post_previous_low * (1.0 - cfg.higher_low_tolerance)
    )
    ma10 = _finite(latest.get("ma10"))
    ma20 = _finite(latest.get("ma20"))
    ma20_slope = _finite(latest.get("ma20_slope"))
    close = float(latest["close"])
    base_trend = bool(ma10 is not None and ma20 is not None and ma20_slope is not None and close > ma10 > ma20 and ma20_slope > 0)
    below_ma20 = frame["close"] < frame["ma20"]
    ma20_broken = bool(len(frame) >= cfg.ma20_break_days and below_ma20.tail(cfg.ma20_break_days).all())
    t0_low = float(frame.iloc[t0_index]["low"])
    t0_low_broken = close < t0_low
    return {
        "ma10": ma10,
        "ma20": ma20,
        "ma20_slope": ma20_slope,
        "base_trend": base_trend,
        "recent_high": recent_high,
        "previous_high": previous_high,
        "recent_low": recent_low,
        "previous_low": previous_low,
        "higher_high": higher_high,
        "higher_low": higher_low,
        "lower_low": lower_low,
        "ma20_broken": ma20_broken,
        "t0_low_broken": t0_low_broken,
    }


def calculate_trend_quality(frame: pd.DataFrame, t0_index: int, cfg: VPTConfig) -> dict[str, float | None]:
    closes = pd.to_numeric(frame.iloc[t0_index:]["close"], errors="coerce").dropna().tail(cfg.observation_max_days + 1)
    if len(closes) < 3 or (closes <= 0).any():
        return {"trend_slope": None, "trend_r2": None}
    x = np.arange(len(closes), dtype=float)
    y = np.log(closes.to_numpy(dtype=float))
    slope, intercept = np.polyfit(x, y, 1)
    fitted = slope * x + intercept
    total = float(np.sum((y - y.mean()) ** 2))
    residual = float(np.sum((y - fitted) ** 2))
    r2 = 1.0 - residual / total if total > 1e-12 else 0.0
    return {"trend_slope": float(slope), "trend_r2": max(0.0, min(1.0, float(r2)))}


def detect_supply_expansion(frame: pd.DataFrame, post_t0: pd.DataFrame, pvr: float | None, cfg: VPTConfig) -> dict[str, object]:
    recent = post_t0.tail(cfg.supply_recent_days)
    ratios = recent["volume"] / recent["base_volume"].replace(0, np.nan)
    expanded = (recent["daily_return"] <= cfg.supply_expansion_return) & (ratios >= cfg.supply_expansion_volume)
    consecutive = int(expanded.astype(int).groupby((~expanded).cumsum()).sum().max()) if not expanded.empty else 0
    return {
        "supply_expansion": bool(expanded.any() or (pvr is not None and pvr > cfg.pvr_severe)),
        "supply_expansion_days": int(expanded.sum()),
        "consecutive_supply_expansion_days": consecutive,
    }


def calculate_vpt_score(metrics: Mapping[str, object], cfg: VPTConfig) -> dict[str, float]:
    spike_ratio = _finite(metrics.get("t0_volume_spike_ratio"))
    spike_score = 0.0
    if spike_ratio is not None and spike_ratio >= cfg.volume_spike_min:
        spike_score = 2.0 + _linear_score(
            spike_ratio,
            cfg.volume_spike_min,
            cfg.effort_volume_ratio,
            6.0,
        )
    startup = (
        spike_score
        + _linear_score(_finite(metrics.get("t0_return")), cfg.t0_return_min, 0.08, 5.0)
        + _linear_score(_finite(metrics.get("t0_close_location")), cfg.t0_close_location_min, 1.0, 4.0)
        + (3.0 if metrics.get("breakout") else 1.5 if metrics.get("near_high") else 0.0)
    )
    trend = (
        (4.0 if metrics.get("close_above_ma10") else 0.0)
        + (4.0 if metrics.get("ma10_above_ma20") else 0.0)
        + _linear_score(_finite(metrics.get("ma20_slope")), 0.0, 0.05, 6.0)
        + (3.0 if metrics.get("higher_high") else 0.0)
        + (3.0 if metrics.get("higher_low") else 0.0)
    )
    directional = 0.0
    if metrics.get("udvr_valid"):
        directional += _linear_score(_finite(metrics.get("udvr")), 1.0, cfg.udvr_very_strong, 15.0)
    directional += _linear_score(_finite(metrics.get("dv")), -0.10, cfg.dv_strong, 10.0)
    pullback = _linear_score(_finite(metrics.get("pvr")), cfg.pvr_strong, cfg.pvr_severe, 20.0, inverse=True) if metrics.get("pvr_valid") else 0.0
    stability = _linear_score(_finite(metrics.get("trend_slope")), 0.0, 0.03, 5.0) + _linear_score(
        _finite(metrics.get("trend_r2")), 0.0, 0.60, 10.0
    )
    penalty = 0.0
    if metrics.get("effort_no_result"):
        penalty += 12.0
    if metrics.get("supply_expansion"):
        penalty += 15.0
    if metrics.get("structure_broken"):
        penalty += 35.0
    total = max(0.0, min(100.0, startup + trend + directional + pullback + stability - penalty))
    return {
        "startup_score": round(startup, 4),
        "trend_score": round(trend, 4),
        "volume_structure_score": round(directional, 4),
        "pullback_score": round(pullback, 4),
        "stability_score": round(stability, 4),
        "risk_penalty": round(penalty, 4),
        "vpt_score": round(total, 4),
    }


def resolve_vpt_state(metrics: Mapping[str, object], cfg: VPTConfig) -> str:
    if not metrics.get("t0_valid"):
        return "FAILED" if metrics.get("effort_no_result") or metrics.get("resumed_after_gap") else "NONE"
    if metrics.get("t0_low_broken") or metrics.get("structure_broken") or int(metrics.get("consecutive_supply_expansion_days") or 0) >= 2:
        return "FAILED"
    days = int(metrics.get("days_since_t0") or 0)
    if days == 0:
        return "SPIKE_DETECTED"
    if days < cfg.observation_min_days:
        return "TREND_CONFIRMING"
    minimum_structure = bool(
        metrics.get("base_trend")
        and metrics.get("higher_low")
        and metrics.get("udvr_valid")
        and (_finite(metrics.get("udvr")) or 0.0) >= cfg.udvr_good
        and (_finite(metrics.get("dv")) or -1.0) > 0.0
        and metrics.get("pvr_valid")
        and (_finite(metrics.get("pvr")) or math.inf) <= cfg.pvr_good
        and int(metrics.get("effort_weak_count") or 0) < 2
        and not metrics.get("supply_expansion")
    )
    if minimum_structure:
        return "QUALIFIED"
    if metrics.get("supply_expansion") or ((_finite(metrics.get("pvr")) or 0.0) > cfg.pvr_warning) or metrics.get("ma20_broken"):
        return "WEAKENING"
    return "TREND_CONFIRMING"


def analyze_vpt(df: pd.DataFrame, config: VPTConfig | None = None) -> dict[str, object]:
    cfg = config or VPTConfig()
    frame = prepare_vpt_frame(df, cfg)
    minimum_bars = cfg.lookback_volume + cfg.ma20_slope_days + 1
    if len(frame) < minimum_bars:
        return {
            "trade_date": frame.iloc[-1]["date"].strftime("%Y%m%d") if not frame.empty else "",
            "vpt_state": "NONE",
            "vpt_score": 0.0,
            "failure_flags": json.dumps(["INSUFFICIENT_HISTORY"], ensure_ascii=False),
            "failure_reason": f"有效K线不足{minimum_bars}根",
            "qualification_flags": "[]",
            "qualification_reason": "",
        }

    events = detect_volume_spike(frame, cfg)
    evaluated = [evaluate_t0_quality(frame, index, cfg) for index in events]
    valid_events = [event for event in evaluated if event["valid"]]
    t0 = valid_events[-1] if valid_events else (evaluated[-1] if evaluated else None)
    if t0 is None:
        return {
            "trade_date": frame.iloc[-1]["date"].strftime("%Y%m%d"),
            "vpt_state": "NONE",
            "vpt_score": 0.0,
            "failure_flags": "[]",
            "failure_reason": "最近窗口无放量事件",
            "qualification_flags": "[]",
            "qualification_reason": "",
        }

    t0_index = int(t0["index"])
    post_t0 = frame.iloc[t0_index + 1 :].copy()
    if len(post_t0) > cfg.observation_max_days:
        post_t0 = post_t0.tail(cfg.observation_max_days)
    udvr = calculate_udvr(post_t0, cfg)
    dv = calculate_directional_volume(post_t0, cfg)
    pullback = detect_pullback(post_t0, cfg)
    structure = evaluate_price_structure(frame, t0_index, cfg)
    trend = calculate_trend_quality(frame, t0_index, cfg)
    supply = detect_supply_expansion(frame, post_t0, _finite(pullback.get("pvr")), cfg)
    latest = frame.iloc[-1]
    breakout_level = _finite(t0.get("breakout_level"))
    breakout_failed_current = bool(
        breakout_level is not None
        and len(frame) >= cfg.breakout_break_days
        and (frame["close"].tail(cfg.breakout_break_days) < breakout_level).all()
    )
    early_window = frame.iloc[t0_index + 1 : t0_index + 1 + cfg.breakout_failure_days]
    breakout_failed_early = bool(
        breakout_level is not None
        and not early_window.empty
        and (early_window["close"] < breakout_level).any()
    )
    post_effort_events = [
        event
        for event in evaluated
        if int(event["index"]) > t0_index and bool(event.get("effort_no_result"))
    ]
    metrics: dict[str, object] = {
        "trade_date": latest["date"].strftime("%Y%m%d"),
        "t0_date": frame.iloc[t0_index]["date"].strftime("%Y%m%d"),
        "days_since_t0": len(frame) - 1 - t0_index,
        "t0_valid": bool(t0.get("valid")),
        **{key: value for key, value in t0.items() if key != "index"},
        **udvr,
        "dv": dv,
        "directional_volume_score": dv,
        **pullback,
        "pullback_volume_ratio": pullback.get("pvr"),
        **structure,
        **trend,
        **supply,
        "close": float(latest["close"]),
        "close_above_ma10": bool(structure.get("ma10") is not None and float(latest["close"]) > float(structure["ma10"])),
        "ma10_above_ma20": bool(structure.get("ma10") is not None and structure.get("ma20") is not None and float(structure["ma10"]) > float(structure["ma20"])),
        "breakout_failed": breakout_failed_current or breakout_failed_early,
        "breakout_failed_early": breakout_failed_early,
        "effort_no_result": bool(t0.get("effort_no_result")) or bool(post_effort_events),
        "effort_weak_count": max(
            [len(t0.get("effort_weak_conditions") or [])]
            + [len(event.get("effort_weak_conditions") or []) for event in post_effort_events]
        ),
    }
    metrics["structure_broken"] = bool(
        structure["t0_low_broken"]
        or metrics["breakout_failed"]
        or structure["ma20_broken"]
        or structure["lower_low"]
    )
    scores = calculate_vpt_score(metrics, cfg)
    metrics.update(scores)
    metrics["vpt_state"] = resolve_vpt_state(metrics, cfg)

    positive_flags = []
    if metrics["t0_valid"]:
        positive_flags.append("VOLUME_SPIKE")
    if metrics.get("breakout"):
        positive_flags.append("BREAKOUT")
    elif metrics.get("near_high"):
        positive_flags.append("NEAR_BREAKOUT")
    if metrics.get("udvr_valid") and (_finite(metrics.get("udvr")) or 0) >= cfg.udvr_good:
        positive_flags.append("UP_VOLUME_DOMINANT")
    if (_finite(metrics.get("dv")) or 0) > cfg.dv_good:
        positive_flags.append("DIRECTIONAL_VOLUME_POSITIVE")
    if metrics.get("pvr_valid") and (_finite(metrics.get("pvr")) or math.inf) <= cfg.pvr_good:
        positive_flags.append("PULLBACK_VOLUME_CONTRACTION")
    if metrics.get("higher_high"):
        positive_flags.append("HIGHER_HIGH")
    if metrics.get("higher_low"):
        positive_flags.append("HIGHER_LOW")

    failure_flags = []
    if metrics.get("effort_no_result"):
        failure_flags.append("EFFORT_NO_RESULT")
    if metrics.get("resumed_after_gap"):
        failure_flags.append("RESUME_GAP_SPIKE")
    if metrics.get("supply_expansion"):
        failure_flags.append("SUPPLY_EXPANSION")
    if metrics.get("breakout_failed"):
        failure_flags.append("BREAKOUT_FAILED")
    if metrics.get("ma20_broken"):
        failure_flags.append("MA20_BROKEN")
    if metrics.get("t0_low_broken"):
        failure_flags.append("T0_LOW_BROKEN")
    if metrics.get("lower_low"):
        failure_flags.append("LOWER_LOW")
    metrics["qualification_flags"] = json.dumps(positive_flags, ensure_ascii=False)
    metrics["failure_flags"] = json.dumps(failure_flags, ensure_ascii=False)
    metrics["qualification_reason"] = ", ".join(positive_flags)
    metrics["failure_reason"] = ", ".join(failure_flags)
    metrics.pop("effort_weak_conditions", None)
    return metrics


def analyze_vpt_history(df: pd.DataFrame, config: VPTConfig | None = None, days: int = 60) -> pd.DataFrame:
    """Calculate an auditable prefix-only VPT history for one symbol."""
    cfg = config or VPTConfig()
    frame = prepare_vpt_frame(df, cfg)
    start = max(cfg.lookback_volume + cfg.ma20_slope_days, len(frame) - max(int(days), 1))
    rows = [analyze_vpt(frame.iloc[: index + 1], cfg) for index in range(start, len(frame))]
    return pd.DataFrame(rows)


def scan_vpt_candidates(
    project_config: dict,
    *,
    pool: str | None = None,
    pool_mode: str = "any",
    symbols: Iterable[str] | None = None,
    trade_date: str | None = None,
    lookback: int = 250,
    vpt_config: VPTConfig | None = None,
) -> pd.DataFrame:
    cfg = vpt_config or VPTConfig.from_mapping(project_config.get("vpt"))
    names = _load_stock_name_map(project_config)
    rows = []
    for symbol in _resolve_symbols(project_config, pool=pool, pool_mode=pool_mode, symbols=symbols):
        frame = _load_kline(project_config, symbol)
        if frame is None or frame.empty:
            continue
        sliced = _slice_as_of(frame, trade_date=trade_date, lookback=max(int(lookback), cfg.lookback_volume + 30))
        if sliced.empty:
            continue
        name = names.get(symbol, "")
        result = analyze_vpt(sliced, cfg)
        eligible = not (cfg.exclude_st and "ST" in str(name).upper())
        if not eligible:
            result.update(
                {
                    "vpt_state": "NONE",
                    "vpt_score": 0.0,
                    "failure_flags": json.dumps(["ST_EXCLUDED"], ensure_ascii=False),
                    "failure_reason": "ST_EXCLUDED",
                }
            )
        result.update(
            {
                "ts_code": symbol,
                "name": name,
                "eligible": eligible,
                "exclusion_reason": "" if eligible else "ST_EXCLUDED",
                "adjustment": str(project_config.get("data", {}).get("stock_adj") or "none"),
            }
        )
        rows.append(result)
    if not rows:
        return pd.DataFrame(columns=["trade_date", "ts_code", "name", "vpt_state", "vpt_score"])
    return pd.DataFrame(rows).sort_values(["vpt_score", "ts_code"], ascending=[False, True]).reset_index(drop=True)


@dataclass
class VPTScanResult:
    trade_date: str
    snapshot_path: Path
    candidates_path: Path
    history_path: Path
    html_path: Path
    snapshot: pd.DataFrame
    candidates: pd.DataFrame
    history: pd.DataFrame
    config: VPTConfig


def _attach_relative_strength(project_config: dict, frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    statistics_dir = Path(project_config.get("output", {}).get("statistics_dir", "output/statistics"))
    radar_path = statistics_dir / "strong_stock_radar" / "strong_stock_radar_latest.csv"
    if not radar_path.exists():
        return frame
    try:
        radar = pd.read_csv(radar_path, usecols=["ts_code", "rs5_pct", "rs10_pct"], dtype={"ts_code": str})
    except (ValueError, OSError):
        return frame
    radar = radar.drop_duplicates("ts_code", keep="last")
    return frame.merge(radar, on="ts_code", how="left")


def save_vpt_scan(
    project_config: dict,
    *,
    pool: str | None = None,
    pool_mode: str = "any",
    symbols: Iterable[str] | None = None,
    trade_date: str | None = None,
    lookback: int = 250,
    top: int = 100,
    min_score: float = 0.0,
    state: str = "ALL",
    history_days: int = 60,
) -> VPTScanResult:
    """Scan current VPT state, persist an all-stock snapshot and candidate report."""
    cfg = VPTConfig.from_mapping(project_config.get("vpt"))
    snapshot = scan_vpt_candidates(
        project_config,
        pool=pool,
        pool_mode=pool_mode,
        symbols=symbols,
        trade_date=trade_date,
        lookback=lookback,
        vpt_config=cfg,
    )
    snapshot = _attach_relative_strength(project_config, snapshot)
    date_part = (
        str(snapshot["trade_date"].dropna().astype(str).max())
        if not snapshot.empty
        else str(trade_date or pd.Timestamp.today().strftime("%Y%m%d")).replace("-", "")[:8]
    )
    snapshot["is_current_date"] = snapshot["trade_date"].astype(str).eq(date_part)
    active_states = set(VPT_CANDIDATE_STATES)
    candidates = snapshot[
        snapshot["vpt_state"].isin(active_states)
        & snapshot["is_current_date"]
        & snapshot["eligible"].fillna(False)
    ].copy()
    candidates = candidates[pd.to_numeric(candidates["vpt_score"], errors="coerce") >= float(min_score)]
    selected_state = str(state or "ALL").strip().upper()
    if selected_state != "ALL":
        if selected_state not in VPT_STATES:
            raise ValueError(f"未知 VPT 状态: {selected_state}")
        candidates = candidates[candidates["vpt_state"] == selected_state]
    candidates = candidates.sort_values(["vpt_score", "ts_code"], ascending=[False, True])
    if int(top) > 0:
        candidates = candidates.head(int(top))
    candidates = candidates.reset_index(drop=True)

    history_rows = []
    for _, candidate in candidates.iterrows():
        symbol = str(candidate["ts_code"])
        source = _load_kline(project_config, symbol)
        if source is None or source.empty:
            continue
        source = _slice_as_of(source, trade_date=trade_date, lookback=max(int(lookback), cfg.lookback_volume + 30))
        timeline = analyze_vpt_history(source, cfg, days=history_days)
        if timeline.empty:
            continue
        timeline.insert(0, "name", candidate.get("name", ""))
        timeline.insert(0, "ts_code", symbol)
        history_rows.append(timeline)
    history = pd.concat(history_rows, ignore_index=True) if history_rows else pd.DataFrame()

    output_cfg = project_config.get("output", {})
    statistics_dir = Path(output_cfg.get("statistics_dir", "output/statistics")) / "vpt"
    signals_dir = Path(output_cfg.get("signals_dir", "output/signals"))
    reports_dir = Path(output_cfg.get("reports_dir", "output/reports")) / "vpt"
    statistics_dir.mkdir(parents=True, exist_ok=True)
    signals_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = statistics_dir / f"vpt_snapshot_{date_part}.csv"
    candidates_path = signals_dir / f"vpt_candidates_{date_part}.csv"
    history_path = statistics_dir / f"vpt_history_{date_part}.csv"
    html_path = reports_dir / "vpt_candidates.html"
    snapshot.to_csv(snapshot_path, index=False)
    candidates.to_csv(candidates_path, index=False)
    history.to_csv(history_path, index=False)

    from visual.vpt_report import build_vpt_report

    build_vpt_report(
        project_config,
        candidates=candidates,
        history=history,
        output_path=html_path,
        trade_date=date_part,
        config=cfg,
    )
    return VPTScanResult(
        trade_date=date_part,
        snapshot_path=snapshot_path,
        candidates_path=candidates_path,
        history_path=history_path,
        html_path=html_path,
        snapshot=snapshot,
        candidates=candidates,
        history=history,
        config=cfg,
    )
