"""Diagnostics for index forecast models."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd

from analysis.index_forecast import build_rule_forecast, forecast_paths
from analysis.index_forecast_p0 import (
    available_p0_features,
    build_breadth_level_slope_events,
    build_feature_decile_study,
    build_feature_group_ablation,
    build_point_in_time_quality_study,
    build_environment_transition_study,
    build_oos_regime_stability,
    build_research_gate_audit,
    build_purged_walk_forward_research,
    is_target_or_leakage_column,
    summarize_walk_forward_research,
    summarize_coefficient_stability,
    evaluate_oos_strategy_policies,
)
from visual.components import html_document, inline_script, to_compact_json
from visual.index_report import _echarts_script_tag


LEGACY_LABELS = ("bull", "neutral", "bear")
ENVIRONMENT_LABELS = ("positive", "neutral", "conservative")
LABEL_MODES = ("environment", "legacy", "abs", "rank")


def _classes(label_col: str) -> tuple[str, str, str]:
    return ENVIRONMENT_LABELS if label_col.startswith("environment_label") else LEGACY_LABELS


@dataclass(frozen=True)
class DiagnosticPaths:
    html: Path
    metrics: Path
    feature_correlations: Path
    condition_summary: Path
    yearly_summary: Path
    calibration: Path
    split_summary: Path
    reason_summary: Path
    feature_whitelist: Path
    breadth_events: Path
    walk_forward: Path
    walk_forward_predictions: Path
    walk_forward_baselines: Path
    walk_forward_coefficients: Path
    label_stability: Path
    feature_deciles: Path
    ablation: Path
    research_summary: Path
    point_in_time_quality: Path
    regime_stability: Path
    transition_study: Path
    strategy_policies: Path
    gate_audit: Path
    coefficient_stability: Path


def diagnostic_paths(
    config: dict,
    symbol: str,
    horizon: int,
    output: str | Path | None = None,
    label_mode: str = "environment",
) -> DiagnosticPaths:
    stats_dir = Path(config["output"].get("statistics_dir", "output/statistics")) / "index_forecast"
    reports_dir = Path(config["output"].get("reports_dir", "output/reports")) / "index_forecast"
    safe_symbol = symbol.upper()
    h = int(horizon)
    mode = (label_mode or "environment").lower()
    if mode not in LABEL_MODES:
        raise ValueError(f"不支持的标签模式: {label_mode}")
    suffix = "" if mode == "environment" else f"_{mode}"
    html_path = Path(output) if output else reports_dir / f"diagnostics_{safe_symbol}_h{h}{suffix}.html"
    return DiagnosticPaths(
        html=html_path,
        metrics=stats_dir / f"diagnostics_{safe_symbol}_h{h}{suffix}_metrics.csv",
        feature_correlations=stats_dir / f"diagnostics_{safe_symbol}_h{h}{suffix}_feature_correlations.csv",
        condition_summary=stats_dir / f"diagnostics_{safe_symbol}_h{h}{suffix}_conditions.csv",
        yearly_summary=stats_dir / f"diagnostics_{safe_symbol}_h{h}{suffix}_yearly.csv",
        calibration=stats_dir / f"diagnostics_{safe_symbol}_h{h}{suffix}_calibration.csv",
        split_summary=stats_dir / f"diagnostics_{safe_symbol}_h{h}{suffix}_splits.csv",
        reason_summary=stats_dir / f"diagnostics_{safe_symbol}_h{h}{suffix}_reasons.csv",
        feature_whitelist=stats_dir / f"diagnostics_{safe_symbol}_h{h}{suffix}_feature_whitelist.csv",
        breadth_events=stats_dir / f"diagnostics_{safe_symbol}_h{h}{suffix}_breadth_events.csv",
        walk_forward=stats_dir / f"diagnostics_{safe_symbol}_h{h}{suffix}_walk_forward.csv",
        walk_forward_predictions=stats_dir / f"diagnostics_{safe_symbol}_h{h}{suffix}_walk_forward_predictions.csv",
        walk_forward_baselines=stats_dir / f"diagnostics_{safe_symbol}_h{h}{suffix}_walk_forward_baselines.csv",
        walk_forward_coefficients=stats_dir / f"diagnostics_{safe_symbol}_h{h}{suffix}_walk_forward_coefficients.csv",
        label_stability=stats_dir / f"diagnostics_{safe_symbol}_h{h}{suffix}_label_stability.csv",
        feature_deciles=stats_dir / f"diagnostics_{safe_symbol}_h{h}{suffix}_feature_deciles.csv",
        ablation=stats_dir / f"diagnostics_{safe_symbol}_h{h}{suffix}_ablation.csv",
        research_summary=stats_dir / f"diagnostics_{safe_symbol}_h{h}{suffix}_research_summary.csv",
        point_in_time_quality=stats_dir / f"diagnostics_{safe_symbol}_h{h}{suffix}_point_in_time_quality.csv",
        regime_stability=stats_dir / f"diagnostics_{safe_symbol}_h{h}{suffix}_regime_stability.csv",
        transition_study=stats_dir / f"diagnostics_{safe_symbol}_h{h}{suffix}_transitions.csv",
        strategy_policies=stats_dir / f"diagnostics_{safe_symbol}_h{h}{suffix}_strategy_policies.csv",
        gate_audit=stats_dir / f"diagnostics_{safe_symbol}_h{h}{suffix}_gate_audit.csv",
        coefficient_stability=stats_dir / f"diagnostics_{safe_symbol}_h{h}{suffix}_coefficient_stability.csv",
    )


def _label_column(horizon: int, label_mode: str = "environment") -> str:
    mode = (label_mode or "environment").lower()
    if mode not in LABEL_MODES:
        raise ValueError(f"不支持的标签模式: {label_mode}")
    if mode == "abs":
        return f"label_abs_{int(horizon)}d"
    if mode == "rank":
        return f"label_rank_{int(horizon)}d"
    if mode == "environment":
        return f"environment_label_{int(horizon)}d"
    return f"label_{int(horizon)}d"


def _as_date_key(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce").dt.strftime("%Y-%m-%d")


def _date_bound(value: str | None) -> str | None:
    if not value:
        return None
    parsed = pd.to_datetime(str(value), errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.strftime("%Y-%m-%d")


def _record_float(value: Any, digits: int = 6) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return round(float(value), digits)
    except Exception:
        return None


def _pct(value: Any, digits: int = 1) -> str:
    try:
        if value is None or pd.isna(value):
            return "--"
        return f"{float(value) * 100:+.{digits}f}%"
    except Exception:
        return "--"


def _num(value: Any, digits: int = 2) -> str:
    try:
        if value is None or pd.isna(value):
            return "--"
        return f"{float(value):,.{digits}f}"
    except Exception:
        return "--"


def _int(value: Any) -> str:
    try:
        if value is None or pd.isna(value):
            return "--"
        return f"{int(float(value)):,}"
    except Exception:
        return "--"


def _max_drawdown(series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return None
    drawdown = values / values.cummax() - 1.0
    return _record_float(drawdown.min())


def _annualized_return(equity: pd.Series, periods_per_year: int = 252) -> float | None:
    values = pd.to_numeric(equity, errors="coerce").dropna()
    if len(values) < 2 or values.iloc[0] <= 0:
        return None
    total = values.iloc[-1] / values.iloc[0]
    years = max((len(values) - 1) / periods_per_year, 1e-9)
    return _record_float(total ** (1.0 / years) - 1.0)


def _sharpe(daily_returns: pd.Series, periods_per_year: int = 252) -> float | None:
    values = pd.to_numeric(daily_returns, errors="coerce").dropna()
    std = values.std()
    if values.empty or not std or pd.isna(std):
        return None
    return _record_float(values.mean() / std * np.sqrt(periods_per_year), 4)


def _calmar(equity: pd.Series) -> float | None:
    ann = _annualized_return(equity)
    mdd = _max_drawdown(equity)
    if ann is None or mdd is None or mdd == 0:
        return None
    return _record_float(ann / abs(mdd), 4)


def _ensure_forecast_files(
    config: dict,
    symbol: str,
    horizon: int,
    start: str | None,
    end: str | None,
    force: bool,
    build_forecast: Callable[[], Any] | None = None,
) -> None:
    paths = forecast_paths(config, symbol, horizon)
    required = [paths.features, paths.predictions]
    if force or any(not path.exists() for path in required):
        if build_forecast is None:
            missing = ", ".join(str(path) for path in required if not path.exists())
            raise FileNotFoundError(f"预测文件不存在: {missing}")
        build_forecast()
        return

    if not start and not end:
        return
    predictions = pd.read_csv(paths.predictions, dtype={"trade_date": str})
    if predictions.empty or "trade_date" not in predictions.columns:
        if build_forecast is None:
            raise ValueError(f"预测文件为空或缺少 trade_date: {paths.predictions}")
        build_forecast()
        return

    dates = _as_date_key(predictions["trade_date"]).dropna()
    start_key = _date_bound(start)
    end_key = _date_bound(end)
    # CLI bounds are calendar dates and often fall on weekends/holidays.  Allow a
    # small calendar-day tolerance while still rejecting materially short files.
    min_date = pd.to_datetime(dates.min()) if not dates.empty else pd.NaT
    max_date = pd.to_datetime(dates.max()) if not dates.empty else pd.NaT
    start_limit = pd.to_datetime(start_key) + pd.Timedelta(days=10) if start_key else None
    end_limit = pd.to_datetime(end_key) - pd.Timedelta(days=10) if end_key else None
    covers_start = True if start_limit is None else bool(pd.notna(min_date) and min_date <= start_limit)
    covers_end = True if end_limit is None else bool(pd.notna(max_date) and max_date >= end_limit)
    if not (covers_start and covers_end):
        if build_forecast is None:
            raise ValueError("现有预测文件不覆盖请求区间")
        build_forecast()


def load_diagnostic_frames(
    config: dict,
    symbol: str,
    horizon: int,
    start: str | None = None,
    end: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    paths = forecast_paths(config, symbol, horizon)
    features = pd.read_csv(paths.features, dtype={"trade_date": str})
    predictions = pd.read_csv(paths.predictions, dtype={"trade_date": str})
    for frame in (features, predictions):
        if "trade_date" in frame.columns:
            frame["trade_date"] = _as_date_key(frame["trade_date"])
    start_key = _date_bound(start)
    end_key = _date_bound(end)
    if start_key:
        features = features[features["trade_date"] >= start_key]
        predictions = predictions[predictions["trade_date"] >= start_key]
    if end_key:
        features = features[features["trade_date"] <= end_key]
        predictions = predictions[predictions["trade_date"] <= end_key]
    return features.reset_index(drop=True), predictions.reset_index(drop=True)


def _evaluated_frame(
    features: pd.DataFrame,
    predictions: pd.DataFrame,
    horizon: int,
    label_mode: str = "environment",
) -> pd.DataFrame:
    label_col = _label_column(horizon, label_mode)
    environment_mode = label_col.startswith("environment_label")
    ret_col = f"equal_weight_return_{int(horizon)}d" if environment_mode else f"fwd_ret_{int(horizon)}d"
    pred_cols = [
        col
        for col in ["trade_date", "signal", "environment_signal", "market_score", "p_bull", "p_bear", "model"]
        if col in predictions.columns
    ]
    frame = features.merge(
        predictions[pred_cols].drop_duplicates(subset=["trade_date"], keep="last"),
        on="trade_date",
        how="left",
        suffixes=("", "_pred"),
    )
    if "signal" not in frame.columns and "signal_pred" in frame.columns:
        frame["signal"] = frame["signal_pred"]
    if environment_mode and "environment_signal" in frame.columns:
        frame["signal"] = frame["environment_signal"]
    elif environment_mode and "environment_signal_pred" in frame.columns:
        frame["signal"] = frame["environment_signal_pred"]
    if ret_col in predictions.columns and ret_col not in frame.columns:
        frame = frame.merge(predictions[["trade_date", ret_col]], on="trade_date", how="left")
    if label_col in predictions.columns and label_col not in frame.columns:
        frame = frame.merge(predictions[["trade_date", label_col]], on="trade_date", how="left")
    if label_col not in frame.columns:
        raise ValueError(f"诊断数据缺少标签列: {label_col}")
    frame[ret_col] = pd.to_numeric(frame.get(ret_col), errors="coerce")
    frame[label_col] = frame.get(label_col)
    return frame.dropna(subset=[ret_col, label_col]).reset_index(drop=True)


def _confusion_matrix(frame: pd.DataFrame, signal_col: str, label_col: str) -> pd.DataFrame:
    matrix = pd.crosstab(frame[signal_col], frame[label_col])
    classes = _classes(label_col)
    return matrix.reindex(index=classes, columns=classes, fill_value=0)


def _signal_quality(frame: pd.DataFrame, signal_col: str, label_col: str, ret_col: str) -> pd.DataFrame:
    rows = []
    classes = _classes(label_col)
    for signal in classes:
        group = frame[frame[signal_col] == signal]
        label_group = frame[frame[label_col] == signal]
        returns = pd.to_numeric(group[ret_col], errors="coerce")
        rows.append(
            {
                "signal": signal,
                "count": int(len(group)),
                "precision": _record_float((group[label_col] == signal).mean(), 4) if len(group) else None,
                "recall": _record_float((label_group[signal_col] == signal).mean(), 4) if len(label_group) else None,
                "avg_return": _record_float(returns.mean()),
                "median_return": _record_float(returns.median()),
                "win_rate": _record_float((returns > 0).mean(), 4) if len(group) else None,
            }
        )
    return pd.DataFrame(rows)


def _prediction_quality(frame: pd.DataFrame, signal_col: str, label_col: str, ret_col: str) -> dict[str, Any]:
    if frame.empty or signal_col not in frame.columns:
        return {}
    accuracy = (frame[signal_col] == frame[label_col]).mean()
    recalls = []
    f1_scores = []
    classes = _classes(label_col)
    for label in classes:
        label_group = frame[frame[label_col] == label]
        if len(label_group):
            recalls.append((label_group[signal_col] == label).mean())
        tp = int(((frame[signal_col] == label) & (frame[label_col] == label)).sum())
        fp = int(((frame[signal_col] == label) & (frame[label_col] != label)).sum())
        fn = int(((frame[signal_col] != label) & (frame[label_col] == label)).sum())
        denom = 2 * tp + fp + fn
        f1_scores.append(2 * tp / denom if denom else 0.0)
    signals = _signal_quality(frame, signal_col, label_col, ret_col)
    bull_label, _, bear_label = classes
    bull_avg = signals.loc[signals["signal"] == bull_label, "avg_return"].iloc[0]
    bear_avg = signals.loc[signals["signal"] == bear_label, "avg_return"].iloc[0]
    return {
        "sample_count": int(len(frame)),
        "accuracy": _record_float(accuracy, 4),
        "balanced_accuracy": _record_float(np.mean(recalls), 4) if recalls else None,
        "macro_f1": _record_float(np.mean(f1_scores), 4) if f1_scores else None,
        "bull_count": int((frame[signal_col] == bull_label).sum()),
        "neutral_count": int((frame[signal_col] == "neutral").sum()),
        "bear_count": int((frame[signal_col] == bear_label).sum()),
        "neutral_ratio": _record_float((frame[signal_col] == "neutral").mean(), 4),
        "bull_avg_return": bull_avg,
        "bear_avg_return": bear_avg,
        "long_short_spread": _record_float(bull_avg - bear_avg) if pd.notna(bull_avg) and pd.notna(bear_avg) else None,
    }


def _score_buckets(frame: pd.DataFrame, score_col: str, ret_col: str, buckets: int = 10) -> pd.DataFrame:
    if frame.empty or score_col not in frame.columns:
        return pd.DataFrame()
    out = frame.copy()
    scores = pd.to_numeric(out[score_col], errors="coerce")
    out = out[scores.notna()].copy()
    if out.empty:
        return pd.DataFrame()
    out["score_bucket"] = pd.cut(
        pd.to_numeric(out[score_col], errors="coerce"),
        bins=np.linspace(0, 100, buckets + 1),
        labels=[f"{int(i)}-{int(i + 100 / buckets)}" for i in np.linspace(0, 100 - 100 / buckets, buckets)],
        include_lowest=True,
    )
    rows = []
    for bucket, group in out.groupby("score_bucket", observed=False):
        returns = pd.to_numeric(group[ret_col], errors="coerce")
        rows.append(
            {
                "bucket": str(bucket),
                "count": int(len(group)),
                "avg_return": _record_float(returns.mean()),
                "median_return": _record_float(returns.median()),
                "win_rate": _record_float((returns > 0).mean(), 4),
            }
        )
    return pd.DataFrame(rows)


def _feature_correlations(frame: pd.DataFrame, ret_col: str, top_n: int = 40) -> pd.DataFrame:
    target = pd.to_numeric(frame[ret_col], errors="coerce")
    rows = []
    for col in frame.columns:
        if is_target_or_leakage_column(col):
            continue
        series = frame[col]
        if series.dtype == bool:
            values = series.astype(float)
        else:
            values = pd.to_numeric(series, errors="coerce")
        values = values.replace([np.inf, -np.inf], np.nan)
        valid = values.notna() & target.notna()
        if valid.sum() < 30 or values[valid].nunique() <= 1:
            continue
        corr = values[valid].corr(target[valid])
        rank_corr = values[valid].rank().corr(target[valid].rank())
        if pd.isna(corr):
            continue
        rows.append(
            {
                "feature": col,
                "count": int(valid.sum()),
                "corr": _record_float(corr, 6),
                "rank_corr": _record_float(rank_corr, 6),
                "abs_corr": abs(float(corr)),
            }
        )
    corr_df = pd.DataFrame(rows)
    if corr_df.empty:
        return corr_df
    return corr_df.sort_values("abs_corr", ascending=False).head(top_n).reset_index(drop=True)


def _condition_mask(frame: pd.DataFrame, expression: str) -> pd.Series:
    def col(name: str) -> pd.Series:
        if name in frame.columns:
            return frame[name]
        return pd.Series(np.nan, index=frame.index)

    masks: dict[str, pd.Series] = {
        "amount_up_confirm": col("amount_up_confirm").fillna(False).astype(bool),
        "amount_down_expand": col("amount_down_expand").fillna(False).astype(bool),
        "break_high_20d": col("break_high_20d").fillna(False).astype(bool),
        "break_low_20d": col("break_low_20d").fillna(False).astype(bool),
        "ret5_lt_minus2": pd.to_numeric(col("ret_5d"), errors="coerce") < -0.02,
        "dist_ma20_lt_minus2": pd.to_numeric(col("dist_ma20"), errors="coerce") < -0.02,
        "drawdown20_lt_minus2": pd.to_numeric(col("drawdown_20d"), errors="coerce") < -0.02,
        "kdj_j_below_0": col("kdj_j_below_0").fillna(False).astype(bool),
        "kdj_j_below_minus10": col("kdj_j_below_minus10").fillna(False).astype(bool),
        "kdj_j_above_90": col("kdj_j_above_90").fillna(False).astype(bool),
        "kdj_j_above_100": col("kdj_j_above_100").fillna(False).astype(bool),
        "ad5_lt_0": pd.to_numeric(col("ad_slope_5"), errors="coerce") < 0,
        "nhnl3_le_0": pd.to_numeric(col("nhnl_slope_3"), errors="coerce") <= 0,
    }
    if expression == "amount_down_expand_and_drawdown20_lt_minus2":
        return masks["amount_down_expand"] & masks["drawdown20_lt_minus2"]
    if expression == "kdj_j_above_90_and_ad5_lt_0":
        return masks["kdj_j_above_90"] & masks["ad5_lt_0"]
    if expression == "kdj_j_above_100_and_ad5_lt_0":
        return masks["kdj_j_above_100"] & masks["ad5_lt_0"]
    if expression == "overheat_breadth_weak":
        return masks["kdj_j_above_90"] & masks["ad5_lt_0"] & masks["nhnl3_le_0"]
    return masks.get(expression, pd.Series(False, index=frame.index))


def _condition_summary(frame: pd.DataFrame, ret_col: str, label_col: str) -> pd.DataFrame:
    positive_label, _, conservative_label = _classes(label_col)
    specs = [
        ("amount_up_confirm", "放量上涨确认"),
        ("amount_down_expand", "放量下跌"),
        ("amount_down_expand_and_drawdown20_lt_minus2", "放量下跌且20日回撤<-2%"),
        ("break_high_20d", "20日突破"),
        ("break_low_20d", "20日新低"),
        ("ret5_lt_minus2", "近5日跌幅<-2%"),
        ("dist_ma20_lt_minus2", "低于MA20超过2%"),
        ("kdj_j_below_0", "KDJ J<0"),
        ("kdj_j_below_minus10", "KDJ J<-10"),
        ("kdj_j_above_90_and_ad5_lt_0", "J>90且A/D斜率<0"),
        ("kdj_j_above_100_and_ad5_lt_0", "J>100且A/D斜率<0"),
        ("overheat_breadth_weak", "过热且广度/NH-NL走弱"),
    ]
    rows = []
    for key, label in specs:
        mask = _condition_mask(frame, key)
        group = frame[mask.fillna(False)]
        returns = pd.to_numeric(group[ret_col], errors="coerce")
        rows.append(
            {
                "condition": key,
                "name": label,
                "count": int(len(group)),
                "avg_return": _record_float(returns.mean()) if len(group) else None,
                "median_return": _record_float(returns.median()) if len(group) else None,
                "win_rate": _record_float((returns > 0).mean(), 4) if len(group) else None,
                "bull_label_rate": _record_float((group[label_col] == positive_label).mean(), 4) if len(group) else None,
                "bear_label_rate": _record_float((group[label_col] == conservative_label).mean(), 4) if len(group) else None,
            }
        )
    return pd.DataFrame(rows)


def _reason_summary(frame: pd.DataFrame, label_col: str, ret_col: str, horizon: int) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    model_frame = build_rule_forecast(frame, horizon=horizon, model="rule_h3_v2")
    cols = [
        "trade_date",
        "signal",
        "opportunity_reason",
        "risk_reason",
        "signal_reason",
        "opportunity_score",
        "risk_score",
        "trend_context_score",
        "net_score",
        "adjusted_net_score",
    ]
    available = [col for col in cols if col in model_frame.columns]
    out = frame.merge(model_frame[available], on="trade_date", how="left", suffixes=("", "_v2"))
    rows = []
    positive_label, _, conservative_label = _classes(label_col)
    specs = [
        ("signal_reason", "信号来源"),
        ("opportunity_reason", "机会来源"),
        ("risk_reason", "风险来源"),
    ]
    for column, label in specs:
        if column not in out.columns:
            continue
        reason_rows = []
        for _, row in out.iterrows():
            value = row.get(column)
            if value is None or pd.isna(value) or str(value).strip() == "":
                continue
            for reason in str(value).split("|"):
                reason = reason.strip()
                if not reason:
                    continue
                reason_rows.append(
                    {
                        "reason_type": label,
                        "reason": reason,
                        "signal": row.get("signal_v2", row.get("signal")),
                        ret_col: row.get(ret_col),
                        label_col: row.get(label_col),
                    }
                )
        if not reason_rows:
            continue
        reason_df = pd.DataFrame(reason_rows)
        for (reason, signal), group in reason_df.groupby(["reason", "signal"], dropna=False):
            returns = pd.to_numeric(group[ret_col], errors="coerce")
            rows.append(
                {
                    "reason_type": label,
                    "reason": str(reason),
                    "signal": str(signal),
                    "count": int(len(group)),
                    "avg_return": _record_float(returns.mean()),
                    "median_return": _record_float(returns.median()),
                    "win_rate": _record_float((returns > 0).mean(), 4),
                    "bull_label_rate": _record_float((group[label_col] == positive_label).mean(), 4),
                    "bear_label_rate": _record_float((group[label_col] == conservative_label).mean(), 4),
                }
            )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["reason_type", "signal", "count"], ascending=[True, True, False])


def _yearly_summary(frame: pd.DataFrame, signal_col: str, label_col: str, ret_col: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    out["year"] = pd.to_datetime(out["trade_date"], errors="coerce").dt.year
    rows = []
    for year, group in out.dropna(subset=["year"]).groupby("year"):
        quality = _prediction_quality(group, signal_col, label_col, ret_col)
        rows.append({"year": int(year), **quality})
    return pd.DataFrame(rows)


def _baseline_signals(frame: pd.DataFrame, horizon: int, label_col: str) -> dict[str, pd.Series]:
    def bool_col(name: str) -> pd.Series:
        if name not in frame.columns:
            return pd.Series(False, index=frame.index)
        return frame[name].fillna(False).astype(bool)

    ret5 = pd.to_numeric(frame.get("ret_5d"), errors="coerce")
    dist_ma20 = pd.to_numeric(frame.get("dist_ma20"), errors="coerce")
    ad5 = pd.to_numeric(frame.get("ad_slope_5"), errors="coerce")

    simple_oversold = pd.Series("neutral", index=frame.index, dtype=object)
    simple_oversold[(bool_col("kdj_j_below_minus10")) | (ret5 < -0.02) | (dist_ma20 < -0.02)] = "bull"
    simple_oversold[(bool_col("kdj_j_above_90")) & (ad5 < 0)] = "bear"

    simple_trend = pd.Series("neutral", index=frame.index, dtype=object)
    simple_trend[bool_col("above_ma20") & bool_col("above_ma60") & bool_col("ma20_gt_ma60")] = "bull"
    simple_trend[(~bool_col("above_ma20")) & (~bool_col("above_ma60"))] = "bear"

    rule_h3_v2 = build_rule_forecast(frame, horizon=horizon, model="rule_h3_v2")
    rule_h3_v2_signal = rule_h3_v2.get("signal", pd.Series("neutral", index=frame.index)).reindex(frame.index).fillna("neutral")
    signals = {
        "always_neutral": pd.Series("neutral", index=frame.index, dtype=object),
        "buy_and_hold": pd.Series("bull", index=frame.index, dtype=object),
        "simple_oversold_h3": simple_oversold,
        "simple_trend_h3": simple_trend,
        "rule_v1": frame.get("signal", pd.Series("neutral", index=frame.index, dtype=object)).fillna("neutral"),
        "rule_h3_v2_legacy_shared_environment": rule_h3_v2_signal,
    }
    if label_col.startswith("environment_label"):
        mapping = {"bull": "positive", "neutral": "neutral", "bear": "conservative"}
        signals = {name: values.map(mapping).fillna("neutral") for name, values in signals.items()}
        signals["rule_v1"] = frame.get(
            "environment_signal", frame.get("signal", pd.Series("neutral", index=frame.index))
        ).fillna("neutral")
        signals["rule_h3_v2_legacy_shared_environment"] = rule_h3_v2.get(
            "environment_signal", pd.Series("neutral", index=frame.index)
        ).reindex(frame.index).fillna("neutral")
    return signals


def _model_comparison(frame: pd.DataFrame, label_col: str, ret_col: str, horizon: int) -> pd.DataFrame:
    rows = []
    for model, signals in _baseline_signals(frame, horizon, label_col).items():
        temp = frame.copy()
        temp["_model_signal"] = signals
        quality = _prediction_quality(temp, "_model_signal", label_col, ret_col)
        rows.append({"model": model, **quality})
    return pd.DataFrame(rows)


def _timing_stats_for_signals(frame: pd.DataFrame, signals: pd.Series) -> dict[str, Any]:
    if frame.empty or "close" not in frame.columns:
        return {}
    out = frame[["trade_date", "close"]].copy()
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out["_signal"] = signals.reindex(frame.index).fillna("neutral").values
    out = out.dropna(subset=["close"]).sort_values("trade_date").reset_index(drop=True)
    if len(out) < 2:
        return {}
    exposure = out["_signal"].map(
        {"bull": 1.0, "positive": 1.0, "neutral": 0.5, "bear": 0.0, "conservative": 0.0}
    ).fillna(0.5)
    daily_ret = out["close"].pct_change().fillna(0.0)
    strategy_ret = exposure.shift(1).fillna(0.0) * daily_ret
    strategy_equity = (1.0 + strategy_ret).cumprod()
    buyhold_equity = out["close"] / out["close"].iloc[0]
    return {
        "timing_return": _record_float(strategy_equity.iloc[-1] - 1.0),
        "timing_max_drawdown": _max_drawdown(strategy_equity),
        "buyhold_return": _record_float(buyhold_equity.iloc[-1] - 1.0),
        "excess_return": _record_float(strategy_equity.iloc[-1] - buyhold_equity.iloc[-1]),
    }


def _boundary_mask(frame: pd.DataFrame, raw_mask: pd.Series, drop_start: int = 0, drop_end: int = 0) -> pd.Series:
    idx = frame[raw_mask.fillna(False)].sort_values("trade_date").index.tolist()
    if drop_start > 0:
        idx = idx[drop_start:]
    if drop_end > 0:
        idx = idx[:-drop_end] if len(idx) > drop_end else []
    return pd.Series(frame.index.isin(idx), index=frame.index)


def _split_masks(frame: pd.DataFrame, horizon: int) -> dict[str, pd.Series]:
    if frame.empty or "trade_date" not in frame.columns:
        return {}
    dates = pd.to_datetime(frame["trade_date"], errors="coerce")
    purge_days = int(horizon)
    embargo_days = max(int(horizon), 5)
    raw_train = (dates >= "2021-01-01") & (dates <= "2023-12-31")
    raw_validate = (dates >= "2024-01-01") & (dates <= "2024-12-31")
    raw_test = (dates >= "2025-01-01") & (dates <= "2026-12-31")
    return {
        "train_2021_2023": _boundary_mask(frame, raw_train, drop_start=0, drop_end=purge_days),
        "validate_2024": _boundary_mask(frame, raw_validate, drop_start=embargo_days, drop_end=purge_days),
        "test_2025_2026": _boundary_mask(frame, raw_test, drop_start=embargo_days, drop_end=0),
    }


def _split_summary(frame: pd.DataFrame, label_col: str, ret_col: str, horizon: int) -> pd.DataFrame:
    rows = []
    baselines = _baseline_signals(frame, horizon, label_col)
    for split, mask in _split_masks(frame, horizon).items():
        split_frame = frame[mask.fillna(False)].copy()
        if split_frame.empty:
            continue
        start = str(split_frame["trade_date"].min())
        end = str(split_frame["trade_date"].max())
        for model, signals in baselines.items():
            temp = split_frame.copy()
            model_signals = signals.reindex(split_frame.index).fillna("neutral")
            temp["_model_signal"] = model_signals
            quality = _prediction_quality(temp, "_model_signal", label_col, ret_col)
            timing = _timing_stats_for_signals(split_frame, model_signals)
            rows.append(
                {
                    "split": split,
                    "model": model,
                    "start": start,
                    "end": end,
                    "purge_days": int(horizon),
                    "embargo_days": max(int(horizon), 5),
                    **quality,
                    **timing,
                }
            )
    return pd.DataFrame(rows)


def _timing_stats(predictions: pd.DataFrame) -> dict[str, Any]:
    frame = predictions.dropna(subset=["trade_date", "close"]).copy()
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["close"]).sort_values("trade_date").reset_index(drop=True)
    if len(frame) < 2:
        return {}
    signal_col = "environment_signal" if "environment_signal" in frame.columns else "signal"
    exposure = frame[signal_col].map(
        {"bull": 1.0, "positive": 1.0, "neutral": 0.5, "bear": 0.0, "conservative": 0.0}
    ).fillna(0.5)
    daily_ret = frame["close"].pct_change().fillna(0.0)
    strategy_ret = exposure.shift(1).fillna(0.0) * daily_ret
    strategy_equity = (1.0 + strategy_ret).cumprod()
    buyhold_equity = frame["close"] / frame["close"].iloc[0]
    return {
        "timing_return": _record_float(strategy_equity.iloc[-1] - 1.0),
        "timing_annual_return": _annualized_return(strategy_equity),
        "timing_max_drawdown": _max_drawdown(strategy_equity),
        "timing_sharpe": _sharpe(strategy_ret),
        "timing_calmar": _calmar(strategy_equity),
        "buyhold_return": _record_float(buyhold_equity.iloc[-1] - 1.0),
        "buyhold_annual_return": _annualized_return(buyhold_equity),
        "buyhold_max_drawdown": _max_drawdown(buyhold_equity),
        "excess_return": _record_float(strategy_equity.iloc[-1] - buyhold_equity.iloc[-1]),
        "avg_exposure": _record_float(exposure.mean(), 4),
    }


def _brier_score(frame: pd.DataFrame, prob_col: str, positive_label: str, label_col: str) -> float | None:
    if prob_col not in frame.columns:
        return None
    prob = pd.to_numeric(frame[prob_col], errors="coerce")
    actual = (frame[label_col] == positive_label).astype(float)
    valid = prob.notna()
    if valid.sum() == 0:
        return None
    return _record_float(((prob[valid] - actual[valid]) ** 2).mean(), 6)


def _calibration_bins(frame: pd.DataFrame, prob_col: str, positive_label: str, label_col: str) -> pd.DataFrame:
    if prob_col not in frame.columns:
        return pd.DataFrame()
    out = frame.copy()
    out[prob_col] = pd.to_numeric(out[prob_col], errors="coerce")
    out = out.dropna(subset=[prob_col])
    if out.empty:
        return pd.DataFrame()
    out["bucket"] = pd.cut(
        out[prob_col],
        bins=np.linspace(0, 1, 6),
        labels=["0-20%", "20-40%", "40-60%", "60-80%", "80-100%"],
        include_lowest=True,
    )
    rows = []
    for bucket, group in out.groupby("bucket", observed=False):
        rows.append(
            {
                "probability": prob_col,
                "bucket": str(bucket),
                "count": int(len(group)),
                "avg_probability": _record_float(group[prob_col].mean(), 4),
                "actual_rate": _record_float((group[label_col] == positive_label).mean(), 4),
            }
        )
    return pd.DataFrame(rows)


def build_diagnostics(
    features: pd.DataFrame,
    predictions: pd.DataFrame,
    horizon: int,
    symbol: str,
    label_mode: str = "environment",
    strategy_returns: Mapping[str, pd.Series] | None = None,
) -> dict[str, Any]:
    label_col = _label_column(horizon, label_mode)
    environment_mode = label_col.startswith("environment_label")
    ret_col = f"equal_weight_return_{int(horizon)}d" if environment_mode else f"fwd_ret_{int(horizon)}d"
    frame = _evaluated_frame(features, predictions, horizon, label_mode=label_mode)
    quality = _prediction_quality(frame, "signal", label_col, ret_col)
    model_comparison = _model_comparison(frame, label_col, ret_col, int(horizon))
    confusion = _confusion_matrix(frame, "signal", label_col)
    signal_quality = _signal_quality(frame, "signal", label_col, ret_col)
    buckets = _score_buckets(frame, "market_score", ret_col)
    correlations = _feature_correlations(frame, ret_col)
    conditions = _condition_summary(frame, ret_col, label_col)
    reasons = _reason_summary(frame, label_col, ret_col, int(horizon))
    yearly = _yearly_summary(frame, "signal", label_col, ret_col)
    splits = _split_summary(frame, label_col, ret_col, int(horizon))
    feature_whitelist = available_p0_features(frame) if environment_mode else []
    breadth_events = build_breadth_level_slope_events(frame, int(horizon)) if environment_mode else pd.DataFrame()
    if environment_mode:
        research = build_purged_walk_forward_research(frame, int(horizon))
        walk_forward = research["folds"]
        walk_forward_predictions = research["predictions"]
        walk_forward_baselines = research["baselines"]
        walk_forward_coefficients = research["coefficients"]
        label_stability = research["label_stability"]
        feature_whitelist = research["features"]
        coefficient_stability = summarize_coefficient_stability(
            walk_forward_coefficients, len(walk_forward)
        )
        feature_deciles = build_feature_decile_study(frame, int(horizon))
        ablation = build_feature_group_ablation(frame, int(horizon), baseline_research=research)
        research_summary = summarize_walk_forward_research(research, int(horizon))
        point_in_time_quality = build_point_in_time_quality_study(frame, int(horizon))
        regime_stability = build_oos_regime_stability(frame, walk_forward_predictions, int(horizon))
        transition_study = build_environment_transition_study(frame, walk_forward_predictions)
        strategy_policies = evaluate_oos_strategy_policies(frame, walk_forward_predictions, strategy_returns)
        gate_audit = build_research_gate_audit(research_summary, strategy_policies)
    else:
        walk_forward, walk_forward_predictions = pd.DataFrame(), pd.DataFrame()
        walk_forward_baselines, walk_forward_coefficients, label_stability = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        feature_deciles, ablation, research_summary = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        point_in_time_quality = pd.DataFrame()
        regime_stability, transition_study, strategy_policies = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        gate_audit = pd.DataFrame()
        coefficient_stability = pd.DataFrame()
    timing = _timing_stats(predictions)
    if environment_mode:
        brier_bull = None
        brier_bear = None
        calibration = pd.DataFrame()
    else:
        brier_bull = _brier_score(frame, "p_bull", "bull", label_col)
        brier_bear = _brier_score(frame, "p_bear", "bear", label_col)
        calibration = pd.concat(
            [
                _calibration_bins(frame, "p_bull", "bull", label_col),
                _calibration_bins(frame, "p_bear", "bear", label_col),
            ],
            ignore_index=True,
        )
    score_ic = None
    rank_ic = None
    if "market_score" in frame.columns and not frame.empty:
        score = pd.to_numeric(frame["market_score"], errors="coerce")
        returns = pd.to_numeric(frame[ret_col], errors="coerce")
        valid = score.notna() & returns.notna()
        if valid.sum() >= 30:
            score_ic = _record_float(score[valid].corr(returns[valid]), 6)
            rank_ic = _record_float(score[valid].rank().corr(returns[valid].rank()), 6)

    metrics = {
        "symbol": symbol.upper(),
        "horizon": int(horizon),
        "model": "rule_v1",
        "label_mode": (label_mode or "environment").lower(),
        "label_column": label_col,
        "start": str(features["trade_date"].min()) if "trade_date" in features.columns and not features.empty else "",
        "end": str(features["trade_date"].max()) if "trade_date" in features.columns and not features.empty else "",
        "daily_sample_count": int(len(frame)),
        "approx_non_overlapping_sample_count": int(len(frame) // max(int(horizon), 1)),
        "p0_feature_count": int(len(feature_whitelist)),
        "walk_forward_fold_count": int(len(walk_forward)),
        "opportunity_auc_mean": _record_float(pd.to_numeric(walk_forward.get("opportunity_auc"), errors="coerce").mean(), 4) if not walk_forward.empty else None,
        "risk_auc_mean": _record_float(pd.to_numeric(walk_forward.get("risk_auc"), errors="coerce").mean(), 4) if not walk_forward.empty else None,
        **quality,
        "score_ic": score_ic,
        "rank_ic": rank_ic,
        "brier_bull": brier_bull,
        "brier_bear": brier_bear,
        **timing,
    }
    return {
        "frame": frame,
        "metrics": metrics,
        "model_comparison": model_comparison,
        "confusion": confusion,
        "signal_quality": signal_quality,
        "score_buckets": buckets,
        "feature_correlations": correlations,
        "condition_summary": conditions,
        "reason_summary": reasons,
        "yearly_summary": yearly,
        "split_summary": splits,
        "calibration": calibration,
        "feature_whitelist": pd.DataFrame({"feature": feature_whitelist}),
        "breadth_events": breadth_events,
        "walk_forward": walk_forward,
        "walk_forward_predictions": walk_forward_predictions,
        "walk_forward_baselines": walk_forward_baselines,
        "walk_forward_coefficients": walk_forward_coefficients,
        "label_stability": label_stability,
        "feature_deciles": feature_deciles,
        "ablation": ablation,
        "research_summary": research_summary,
        "point_in_time_quality": point_in_time_quality,
        "regime_stability": regime_stability,
        "transition_study": transition_study,
        "strategy_policies": strategy_policies,
        "gate_audit": gate_audit,
        "coefficient_stability": coefficient_stability,
    }


def save_diagnostics(config: dict, symbol: str, horizon: int, diagnostics: dict[str, Any], output: str | Path | None = None) -> DiagnosticPaths:
    label_mode = diagnostics.get("metrics", {}).get("label_mode", "environment")
    paths = diagnostic_paths(config, symbol, horizon, output, label_mode=label_mode)
    for path in (
        paths.html,
        paths.metrics,
        paths.feature_correlations,
        paths.condition_summary,
        paths.yearly_summary,
        paths.calibration,
        paths.split_summary,
        paths.reason_summary,
        paths.feature_whitelist,
        paths.breadth_events,
        paths.walk_forward,
        paths.walk_forward_predictions,
        paths.walk_forward_baselines,
        paths.walk_forward_coefficients,
        paths.label_stability,
        paths.feature_deciles,
        paths.ablation,
        paths.research_summary,
        paths.point_in_time_quality,
        paths.regime_stability,
        paths.transition_study,
        paths.strategy_policies,
        paths.gate_audit,
        paths.coefficient_stability,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)

    pd.DataFrame([diagnostics["metrics"]]).to_csv(paths.metrics, index=False)
    diagnostics["feature_correlations"].to_csv(paths.feature_correlations, index=False)
    diagnostics["condition_summary"].to_csv(paths.condition_summary, index=False)
    diagnostics["reason_summary"].to_csv(paths.reason_summary, index=False)
    diagnostics["yearly_summary"].to_csv(paths.yearly_summary, index=False)
    diagnostics["calibration"].to_csv(paths.calibration, index=False)
    diagnostics["split_summary"].to_csv(paths.split_summary, index=False)
    diagnostics["feature_whitelist"].to_csv(paths.feature_whitelist, index=False)
    diagnostics["breadth_events"].to_csv(paths.breadth_events, index=False)
    diagnostics["walk_forward"].to_csv(paths.walk_forward, index=False)
    diagnostics["walk_forward_predictions"].to_csv(paths.walk_forward_predictions, index=False)
    diagnostics["walk_forward_baselines"].to_csv(paths.walk_forward_baselines, index=False)
    diagnostics["walk_forward_coefficients"].to_csv(paths.walk_forward_coefficients, index=False)
    diagnostics["label_stability"].to_csv(paths.label_stability, index=False)
    diagnostics["feature_deciles"].to_csv(paths.feature_deciles, index=False)
    diagnostics["ablation"].to_csv(paths.ablation, index=False)
    diagnostics["research_summary"].to_csv(paths.research_summary, index=False)
    diagnostics["point_in_time_quality"].to_csv(paths.point_in_time_quality, index=False)
    diagnostics["regime_stability"].to_csv(paths.regime_stability, index=False)
    diagnostics["transition_study"].to_csv(paths.transition_study, index=False)
    diagnostics["strategy_policies"].to_csv(paths.strategy_policies, index=False)
    diagnostics["gate_audit"].to_csv(paths.gate_audit, index=False)
    diagnostics["coefficient_stability"].to_csv(paths.coefficient_stability, index=False)
    paths.html.write_text(render_diagnostics_html(symbol, horizon, diagnostics), encoding="utf-8")
    return paths


_CSS = """
* { box-sizing: border-box; }
body { margin: 0; background: #f5f6f8; color: #172033; font-family: "Microsoft YaHei", "Noto Sans SC", "PingFang SC", sans-serif; }
.shell { width: min(1440px, calc(100vw - 40px)); margin: 0 auto; padding: 26px 0 42px; }
.topbar { display: flex; justify-content: space-between; gap: 18px; align-items: flex-end; border-bottom: 1px solid #d9e0ea; padding-bottom: 18px; }
h1 { margin: 0; font-size: 34px; line-height: 1.1; letter-spacing: 0; }
.sub { margin-top: 8px; color: #69748a; font-size: 13px; }
.cards { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 18px; }
.card { background: #fff; border: 1px solid #d9e0ea; padding: 14px 16px; min-height: 90px; }
.card span { color: #69748a; font-size: 12px; }
.card strong { display: block; margin-top: 9px; font-size: 24px; }
.panel { background: #fff; border: 1px solid #d9e0ea; margin-top: 20px; overflow: hidden; }
.panel-head { display: flex; justify-content: space-between; gap: 12px; padding: 16px 18px; border-bottom: 1px solid #d9e0ea; }
.panel-head h2 { margin: 0; font-size: 21px; }
.panel-head span { color: #69748a; font-size: 13px; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; padding: 16px; }
.chart { height: 330px; padding: 12px 16px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 9px 11px; border-bottom: 1px solid #edf0f5; text-align: right; white-space: nowrap; }
th:first-child, td:first-child { text-align: left; }
th { color: #69748a; background: #fbfcfe; font-weight: 700; }
.up { color: #c94343; font-weight: 800; }
.down { color: #168457; font-weight: 800; }
.neutral { color: #69748a; font-weight: 800; }
.note { margin-top: 18px; padding: 14px 16px; background: #fff; border: 1px solid #d9e0ea; color: #69748a; font-size: 13px; line-height: 1.7; }
@media (max-width: 980px) { .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); } .grid { grid-template-columns: 1fr; } .panel { overflow-x: auto; } }
@media (max-width: 620px) { .shell { width: min(100vw - 24px, 1440px); } .topbar { align-items: flex-start; flex-direction: column; } .cards { grid-template-columns: 1fr; } }
"""


def _tone(value: Any) -> str:
    try:
        num = float(value)
    except Exception:
        return "neutral"
    if num > 0:
        return "up"
    if num < 0:
        return "down"
    return "neutral"


def _cards(metrics: dict[str, Any]) -> str:
    items = [
        ("可评估样本", _int(metrics.get("sample_count"))),
        ("命中率", _pct(metrics.get("accuracy"), 1)),
        ("平衡命中率", _pct(metrics.get("balanced_accuracy"), 1)),
        ("多空收益差", _pct(metrics.get("long_short_spread"), 2)),
        ("Score IC", _num(metrics.get("score_ic"), 4)),
        ("Rank IC", _num(metrics.get("rank_ic"), 4)),
        ("择时收益", _pct(metrics.get("timing_return"), 1)),
        ("择时最大回撤", _pct(metrics.get("timing_max_drawdown"), 1)),
    ]
    return "".join(
        f"<div class='card'><span>{escape(label)}</span><strong>{escape(value)}</strong></div>"
        for label, value in items
    )


def _df_rows(df: pd.DataFrame, columns: list[tuple[str, str, str]], empty_cols: int) -> str:
    if df.empty:
        return f"<tr><td colspan='{empty_cols}'>暂无数据</td></tr>"
    rows = []
    for _, row in df.iterrows():
        cells = []
        for col, kind, label in columns:
            value = row.get(col)
            if kind == "pct":
                text = _pct(value, 2)
                cls = _tone(value)
            elif kind == "pct1":
                text = _pct(value, 1)
                cls = _tone(value)
            elif kind == "num":
                text = _num(value, 4)
                cls = _tone(value)
            elif kind == "int":
                text = _int(value)
                cls = ""
            else:
                text = str(value if value is not None and not pd.isna(value) else "")
                cls = ""
            class_attr = f" class='{cls}'" if cls else ""
            cells.append(f"<td{class_attr}>{escape(text)}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return "".join(rows)


def _table(df: pd.DataFrame, headers: list[str], columns: list[tuple[str, str, str]]) -> str:
    head = "".join(f"<th>{escape(header)}</th>" for header in headers)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{_df_rows(df, columns, len(headers))}</tbody></table>"


def _confusion_table(confusion: pd.DataFrame) -> str:
    labels = tuple(str(item) for item in confusion.columns)
    signals = tuple(str(item) for item in confusion.index)
    headers = ["预测\\实际", *labels]
    rows = []
    for signal in signals:
        cells = [f"<td>{escape(signal)}</td>"]
        for label in labels:
            cells.append(f"<td>{_int(confusion.loc[signal, label] if label in confusion.columns else 0)}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    head = "".join(f"<th>{escape(header)}</th>" for header in headers)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _chart_payload(diagnostics: dict[str, Any]) -> dict[str, Any]:
    buckets = diagnostics["score_buckets"]
    corr = diagnostics["feature_correlations"].head(15)
    yearly = diagnostics["yearly_summary"]
    comparison = diagnostics["model_comparison"]

    def values(df: pd.DataFrame, column: str) -> list[Any]:
        if df.empty or column not in df.columns:
            return []
        out = []
        for item in pd.to_numeric(df[column], errors="coerce").tolist():
            out.append(None if pd.isna(item) else float(item))
        return out

    return {
        "bucket_names": buckets["bucket"].astype(str).tolist() if not buckets.empty else [],
        "bucket_returns": values(buckets, "avg_return"),
        "bucket_win_rates": values(buckets, "win_rate"),
        "features": corr["feature"].astype(str).tolist() if not corr.empty else [],
        "feature_corrs": values(corr, "corr"),
        "years": yearly["year"].astype(str).tolist() if not yearly.empty else [],
        "year_spread": values(yearly, "long_short_spread"),
        "models": comparison["model"].astype(str).tolist() if not comparison.empty else [],
        "model_spread": values(comparison, "long_short_spread"),
    }


_JS = r"""
<script>
(function(){
var C={up:'#c94343',down:'#168457',blue:'#2f6df6',orange:'#d38b24',axis:'#69748a',line:'#d9e0ea',split:'#edf0f5',ink:'#172033'};
function axisCategory(d, rotate){return{type:'category',data:d,axisLabel:{fontSize:10,color:C.axis,rotate:rotate||0},axisLine:{lineStyle:{color:C.line}},splitLine:{show:false}};}
function axisValue(name){return{type:'value',scale:true,name:name||'',axisLabel:{fontSize:10,color:C.axis},splitLine:{show:true,lineStyle:{type:'dashed',color:C.split}}};}
function chart(id,opt){var el=document.getElementById(id);if(!el)return null;var c=echarts.init(el,null,{renderer:'canvas'});c.setOption(opt);return c;}
function color(v){return (v||0)>=0?C.up:C.down;}
function init(){
 var d=window._DIAGNOSTICS||{}; var charts=[];
 if(d.bucket_names&&d.bucket_names.length){
  charts.push(chart('diag-buckets',{tooltip:{trigger:'axis'},legend:{top:8,data:['平均未来收益','胜率']},grid:{left:52,right:42,top:48,bottom:42},xAxis:axisCategory(d.bucket_names,0),yAxis:[axisValue('收益'),axisValue('胜率')],series:[{name:'平均未来收益',type:'bar',data:d.bucket_returns,itemStyle:{color:function(p){return color(p.value);}}},{name:'胜率',type:'line',yAxisIndex:1,data:d.bucket_win_rates,symbol:'circle',lineStyle:{color:C.blue,width:2}}]}));
 }
 if(d.features&&d.features.length){
  charts.push(chart('diag-corr',{tooltip:{trigger:'axis'},grid:{left:160,right:42,top:24,bottom:28},xAxis:axisValue('相关'),yAxis:{type:'category',data:d.features.reverse(),axisLabel:{fontSize:10,color:C.axis},axisLine:{lineStyle:{color:C.line}}},series:[{name:'相关系数',type:'bar',data:d.feature_corrs.reverse(),itemStyle:{color:function(p){return color(p.value);}}}]}));
 }
 if(d.years&&d.years.length){
  charts.push(chart('diag-yearly',{tooltip:{trigger:'axis'},grid:{left:52,right:42,top:24,bottom:42},xAxis:axisCategory(d.years,0),yAxis:axisValue('多空差'),series:[{name:'年度多空差',type:'bar',data:d.year_spread,itemStyle:{color:function(p){return color(p.value);}}}]}));
 }
 if(d.models&&d.models.length){
  charts.push(chart('diag-models',{tooltip:{trigger:'axis'},grid:{left:72,right:42,top:24,bottom:68},xAxis:axisCategory(d.models,25),yAxis:axisValue('多空差'),series:[{name:'模型多空差',type:'bar',data:d.model_spread,itemStyle:{color:function(p){return color(p.value);}}}]}));
 }
 window.addEventListener('resize',function(){charts.filter(Boolean).forEach(function(c){c.resize();});});
}
window.addEventListener('DOMContentLoaded',init);
})();
</script>
"""


def render_diagnostics_html(symbol: str, horizon: int, diagnostics: dict[str, Any]) -> str:
    metrics = diagnostics["metrics"]
    signal_table = _table(
        diagnostics["signal_quality"],
        ["预测", "样本", "Precision", "Recall", "平均收益", "中位收益", "胜率"],
        [
            ("signal", "text", "预测"),
            ("count", "int", "样本"),
            ("precision", "pct1", "Precision"),
            ("recall", "pct1", "Recall"),
            ("avg_return", "pct", "平均收益"),
            ("median_return", "pct", "中位收益"),
            ("win_rate", "pct1", "胜率"),
        ],
    )
    comparison_table = _table(
        diagnostics["model_comparison"],
        ["模型", "样本", "命中率", "平衡命中率", "Bull数", "Bear数", "多空收益差"],
        [
            ("model", "text", "模型"),
            ("sample_count", "int", "样本"),
            ("accuracy", "pct1", "命中率"),
            ("balanced_accuracy", "pct1", "平衡命中率"),
            ("bull_count", "int", "Bull数"),
            ("bear_count", "int", "Bear数"),
            ("long_short_spread", "pct", "多空收益差"),
        ],
    )
    condition_table = _table(
        diagnostics["condition_summary"],
        ["条件", "样本", "平均收益", "中位收益", "胜率", "Bull标签", "Bear标签"],
        [
            ("name", "text", "条件"),
            ("count", "int", "样本"),
            ("avg_return", "pct", "平均收益"),
            ("median_return", "pct", "中位收益"),
            ("win_rate", "pct1", "胜率"),
            ("bull_label_rate", "pct1", "Bull标签"),
            ("bear_label_rate", "pct1", "Bear标签"),
        ],
    )
    reason_table = _table(
        diagnostics["reason_summary"],
        ["类型", "来源", "信号", "样本", "平均收益", "中位收益", "胜率", "Bull标签", "Bear标签"],
        [
            ("reason_type", "text", "类型"),
            ("reason", "text", "来源"),
            ("signal", "text", "信号"),
            ("count", "int", "样本"),
            ("avg_return", "pct", "平均收益"),
            ("median_return", "pct", "中位收益"),
            ("win_rate", "pct1", "胜率"),
            ("bull_label_rate", "pct1", "Bull标签"),
            ("bear_label_rate", "pct1", "Bear标签"),
        ],
    )
    yearly_table = _table(
        diagnostics["yearly_summary"],
        ["年份", "样本", "命中率", "平衡命中率", "Bull数", "Bear数", "多空收益差"],
        [
            ("year", "text", "年份"),
            ("sample_count", "int", "样本"),
            ("accuracy", "pct1", "命中率"),
            ("balanced_accuracy", "pct1", "平衡命中率"),
            ("bull_count", "int", "Bull数"),
            ("bear_count", "int", "Bear数"),
            ("long_short_spread", "pct", "多空收益差"),
        ],
    )
    split_table = _table(
        diagnostics["split_summary"],
        ["区间", "模型", "起始", "结束", "样本", "命中率", "平衡命中率", "多空收益差", "择时收益", "买入持有"],
        [
            ("split", "text", "区间"),
            ("model", "text", "模型"),
            ("start", "text", "起始"),
            ("end", "text", "结束"),
            ("sample_count", "int", "样本"),
            ("accuracy", "pct1", "命中率"),
            ("balanced_accuracy", "pct1", "平衡命中率"),
            ("long_short_spread", "pct", "多空收益差"),
            ("timing_return", "pct", "择时收益"),
            ("buyhold_return", "pct", "买入持有"),
        ],
    )
    calibration_table = _table(
        diagnostics["calibration"],
        ["概率", "概率分桶", "样本", "平均预测概率", "实际发生率"],
        [
            ("probability", "text", "概率"),
            ("bucket", "text", "概率分桶"),
            ("count", "int", "样本"),
            ("avg_probability", "pct1", "平均预测概率"),
            ("actual_rate", "pct1", "实际发生率"),
        ],
    )
    research_table = _table(
        diagnostics.get("research_summary", pd.DataFrame()),
        ["类别", "目标", "AUC", "最佳简单基线", "逐折胜率", "Rank IC", "IC正折", "高低组差", "区块CI下界", "区块CI上界"],
        [
            ("section", "text", "类别"), ("target", "text", "目标"), ("mean_auc", "num", "AUC"),
            ("best_simple_mean_auc", "num", "最佳简单基线"), ("fold_win_rate", "pct1", "逐折胜率"),
            ("mean_rank_ic", "num", "Rank IC"), ("positive_fold_ratio", "pct1", "IC正折"),
            ("high_minus_low", "pct", "高低组差"), ("block_bootstrap_ci_low", "pct", "区块CI下界"),
            ("block_bootstrap_ci_high", "pct", "区块CI上界"),
        ],
    )
    ablation_table = _table(
        diagnostics.get("ablation", pd.DataFrame()),
        ["删除特征组", "特征数", "折数", "机会AUC", "风险AUC", "机会Rank IC"],
        [
            ("excluded_group", "text", "删除特征组"), ("feature_count", "int", "特征数"),
            ("fold_count", "int", "折数"), ("opportunity_auc", "num", "机会AUC"),
            ("risk_auc", "num", "风险AUC"), ("opportunity_rank_ic", "num", "机会Rank IC"),
        ],
    )
    quality_table = _table(
        diagnostics.get("point_in_time_quality", pd.DataFrame()),
        ["年份", "天数", "最少股票", "中位股票", "最多股票", "相对完整历史最大值"],
        [
            ("year", "text", "年份"), ("days", "int", "天数"), ("min_stock_count", "int", "最少股票"),
            ("median_stock_count", "int", "中位股票"), ("max_stock_count", "int", "最多股票"),
            ("coverage_vs_full_history_max", "pct1", "相对完整历史最大值"),
        ],
    )
    gate_table = _table(
        diagnostics.get("gate_audit", pd.DataFrame()),
        ["门槛", "实际", "比较", "阈值", "通过", "决策"],
        [
            ("gate", "text", "门槛"), ("actual", "num", "实际"), ("operator", "text", "比较"),
            ("threshold", "num", "阈值"), ("passed", "text", "通过"), ("decision", "text", "决策"),
        ],
    )
    body = f"""
    <main class="shell">
      <header class="topbar">
        <div>
          <h1>{escape(symbol.upper())} 预测诊断</h1>
          <div class="sub">预测周期 {int(horizon)} 个交易日 · 标签 {escape(str(metrics.get('label_column', '')))} · {escape(str(metrics.get('start', '')))} ~ {escape(str(metrics.get('end', '')))} · 诊断报告</div>
        </div>
      </header>
      <section class="cards">{_cards(metrics)}</section>
      <section class="panel">
        <div class="panel-head"><h2>模型对比与混淆矩阵</h2><span>先和固定基准比较，避免只看 rule_v1 自身</span></div>
        <div class="grid">
          {comparison_table}
          {_confusion_table(diagnostics["confusion"])}
        </div>
      </section>
      <section class="panel">
        <div class="panel-head"><h2>时间切分验证</h2><span>train=2021-2023，validate=2024，test=2025-2026；边界使用 purge/embargo</span></div>
        {split_table}
      </section>
      <section class="panel">
        <div class="panel-head"><h2>P0/P1 严格样本外门槛</h2><span>扩展训练窗 + 验证调参 + purge/embargo + 测试冻结</span></div>
        {research_table}
        {gate_table}
      </section>
      <section class="panel">
        <div class="panel-head"><h2>特征组消融</h2><span>删除趋势、广度或风险/结构特征后重新跑同一组时间折</span></div>
        {ablation_table}
      </section>
      <section class="panel">
        <div class="panel-head"><h2>信号质量</h2><span>Precision/Recall 和分组收益比单纯命中率更重要</span></div>
        <div class="grid">
          {signal_table}
          <div id="diag-models" class="chart"></div>
        </div>
      </section>
      <section class="panel">
        <div class="panel-head"><h2>分数桶与特征相关性</h2><span>检查分数是否有排序能力，以及哪些特征和未来收益更接近</span></div>
        <div class="grid">
          <div id="diag-buckets" class="chart"></div>
          <div id="diag-corr" class="chart"></div>
        </div>
      </section>
      <section class="panel">
        <div class="panel-head"><h2>关键条件组合</h2><span>用于验证超跌、放量、KDJ 过热等规则假设</span></div>
        {condition_table}
      </section>
      <section class="panel">
        <div class="panel-head"><h2>rule_h3_v2 来源表现</h2><span>按 signal/opportunity/risk 来源拆解，定位赚钱或拖累规则</span></div>
        {reason_table}
      </section>
      <section class="panel">
        <div class="panel-head"><h2>年度稳定性</h2><span>观察模型是否只在某几年有效</span></div>
        <div class="grid">
          {yearly_table}
          <div id="diag-yearly" class="chart"></div>
        </div>
      </section>
      <section class="panel">
        <div class="panel-head"><h2>概率校准</h2><span>检查预测概率和实际发生率是否匹配</span></div>
        {calibration_table}
      </section>
      <section class="panel">
        <div class="panel-head"><h2>历史股票池覆盖</h2><span>本地当前股票缓存不能补回退市股和历史 ST 状态，早期结果存在幸存者偏差</span></div>
        {quality_table}
      </section>
      <section class="note">
        说明：诊断报告只用于评估模型，不改变正式预测信号。rule_h3_v2 的旧指数规则不同，但环境输出明确标记为 shared_environment_rule_v1。
        P0/P1 时间折使用训练→purge→验证→embargo→测试；所有预处理、正则、校准和政策阈值均在测试前冻结。
      </section>
    </main>
    """
    return html_document(
        title=f"{symbol.upper()} 预测诊断",
        body=body,
        styles=_CSS,
        head_extra=_echarts_script_tag(),
        scripts=inline_script(f"window._DIAGNOSTICS={to_compact_json(_chart_payload(diagnostics))};") + _JS,
    )
