"""Broad market overview metrics from configured indexes."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from analysis.index_overview import (
    _annualized_volatility_pct,
    _max_drawdown_pct,
    _pct_change_from_window,
    _ytd_return_pct,
)


def _fmt_pct(value: float | None, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "--"
    return f"{value:+.{digits}f}%"


def _fmt_num(value: float | None, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "--"
    return f"{value:,.{digits}f}"


def _num_or_zero(value: float | None) -> float:
    if value is None or pd.isna(value):
        return 0.0
    return float(value)


def _latest_pct_chg(df: pd.DataFrame) -> float | None:
    latest = df.iloc[-1]
    value = latest.get("pct_chg")
    if value is not None and not pd.isna(value):
        return float(value)
    if len(df) >= 2 and float(df["close"].iloc[-2]) != 0:
        return float((df["close"].iloc[-1] / df["close"].iloc[-2] - 1.0) * 100)
    return None


def _fmt_int(value: int | None) -> str:
    if value is None:
        return "--"
    return f"{value:,}"


def _ma(close: pd.Series, window: int) -> float | None:
    if len(close) < window:
        return None
    return float(close.tail(window).mean())


def _index_row(symbol: str, name: str, df: pd.DataFrame) -> dict[str, Any]:
    if not pd.api.types.is_datetime64_any_dtype(df["date"]):
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    close = df["close"].astype(float)
    latest_close = float(close.iloc[-1])
    ma20 = _ma(close, 20)
    ma60 = _ma(close, 60)
    ma120 = _ma(close, 120)
    ret5 = _pct_change_from_window(close, 5)
    ret20 = _pct_change_from_window(close, 20)
    ret60 = _pct_change_from_window(close, 60)
    ytd = _ytd_return_pct(df)

    above_ma20 = bool(ma20 is not None and latest_close >= ma20)
    above_ma60 = bool(ma60 is not None and latest_close >= ma60)
    above_ma120 = bool(ma120 is not None and latest_close >= ma120)
    score = 0
    score += 2 if above_ma20 else -1
    score += 2 if above_ma60 else -1
    score += 1 if above_ma120 else 0
    if ret20 is not None:
        score += 1 if ret20 > 0 else -1
    if ret5 is not None:
        score += 1 if ret5 > 0 else -1
    relative_score = (
        _num_or_zero(ret20) * 0.50
        + _num_or_zero(ret60) * 0.30
        + _num_or_zero(ytd) * 0.15
        + _num_or_zero(_latest_pct_chg(df)) * 0.05
    )

    return {
        "symbol": symbol,
        "name": name or symbol,
        "date": df["date"].iloc[-1].strftime("%Y-%m-%d"),
        "close": latest_close,
        "pct_chg": _latest_pct_chg(df),
        "ret5": ret5,
        "ret20": ret20,
        "ret60": ret60,
        "ytd": ytd,
        "drawdown20": _max_drawdown_pct(close, 20),
        "volatility20": _annualized_volatility_pct(close, 20),
        "above_ma20": above_ma20,
        "above_ma60": above_ma60,
        "above_ma120": above_ma120,
        "score": score,
        "relative_score": relative_score,
    }


def build_market_overview(
    index_frames: list[tuple[str, str, pd.DataFrame]],
    breadth_by_date: dict[str, dict[str, int]] | None = None,
) -> dict[str, Any]:
    """Build multi-index market environment metrics."""
    rows = [
        _index_row(symbol, name, df)
        for symbol, name, df in index_frames
        if df is not None and not df.empty
    ]
    if not rows:
        raise ValueError("没有可用指数数据，无法生成大盘环境看板。")

    latest_date = max(row["date"] for row in rows)
    latest_breadth = (breadth_by_date or {}).get(latest_date, {})
    up = int(latest_breadth.get("up", 0) or 0)
    down = int(latest_breadth.get("down", 0) or 0)
    flat = int(latest_breadth.get("flat", 0) or 0)
    total_breadth = up + down + flat
    up_ratio = (up / total_breadth * 100) if total_breadth else None
    ad_value = (up - down) if total_breadth else None
    breadth_dates = sorted(date_key for date_key in (breadth_by_date or {}) if date_key <= latest_date)
    ad_line = None
    if breadth_dates:
        ad_line = sum(
            int((breadth_by_date or {}).get(date_key, {}).get("up", 0) or 0)
            - int((breadth_by_date or {}).get(date_key, {}).get("down", 0) or 0)
            for date_key in breadth_dates
        )
    has_nhnl = "new_high" in latest_breadth or "new_low" in latest_breadth
    new_high = int(latest_breadth.get("new_high", 0) or 0) if has_nhnl else None
    new_low = int(latest_breadth.get("new_low", 0) or 0) if has_nhnl else None
    nhnl = (new_high - new_low) if new_high is not None and new_low is not None else None
    nhnl_dates = breadth_dates[-5:]
    nhnl_5d = None
    if nhnl_dates and any(
        "new_high" in (breadth_by_date or {}).get(date_key, {})
        or "new_low" in (breadth_by_date or {}).get(date_key, {})
        for date_key in nhnl_dates
    ):
        nhnl_5d = sum(
            int((breadth_by_date or {}).get(date_key, {}).get("new_high", 0) or 0)
            - int((breadth_by_date or {}).get(date_key, {}).get("new_low", 0) or 0)
            for date_key in nhnl_dates
        )

    above20_count = sum(1 for row in rows if row["above_ma20"])
    above60_count = sum(1 for row in rows if row["above_ma60"])
    avg_ret20_values = [row["ret20"] for row in rows if row["ret20"] is not None]
    avg_ret20 = float(np.mean(avg_ret20_values)) if avg_ret20_values else None
    avg_score = float(np.mean([row["score"] for row in rows]))

    if avg_score >= 4 and above20_count >= max(1, len(rows) * 0.7):
        environment = "偏强"
        summary = "多数宽基指数处于均线之上，市场风险偏好较积极。"
    elif avg_score <= 0 and above20_count <= len(rows) * 0.4:
        environment = "偏弱"
        summary = "多数宽基指数处于短期均线下方，市场仍需防守。"
    elif avg_ret20 is not None and avg_ret20 > 0:
        environment = "修复"
        summary = "指数整体处于修复区间，但共振强度仍需继续观察。"
    else:
        environment = "震荡"
        summary = "指数强弱分化，适合降低追涨、等待更明确的方向。"

    cards = [
        {"label": "市场环境", "value": environment},
        {"label": "覆盖指数", "value": str(len(rows))},
        {"label": "站上MA20", "value": f"{above20_count}/{len(rows)}"},
        {"label": "站上MA60", "value": f"{above60_count}/{len(rows)}"},
        {"label": "指数20日均涨跌", "value": _fmt_pct(avg_ret20)},
        {"label": "上涨家数", "value": str(up) if total_breadth else "--"},
        {"label": "下跌家数", "value": str(down) if total_breadth else "--"},
        {"label": "上涨占比", "value": _fmt_pct(up_ratio)},
    ]

    display_rows = []
    for row in rows:
        display = dict(row)
        display.update(
            {
                "close_text": _fmt_num(row["close"]),
                "pct_chg_text": _fmt_pct(row["pct_chg"]),
                "ret5_text": _fmt_pct(row["ret5"]),
                "ret20_text": _fmt_pct(row["ret20"]),
                "ret60_text": _fmt_pct(row["ret60"]),
                "ytd_text": _fmt_pct(row["ytd"]),
                "drawdown20_text": _fmt_pct(row["drawdown20"]),
                "volatility20_text": _fmt_pct(row["volatility20"]),
                "relative_score_text": _fmt_num(row["relative_score"], 2),
            }
        )
        display_rows.append(display)
    strongest = sorted(display_rows, key=lambda row: row["relative_score"], reverse=True)[:3]
    weakest = sorted(display_rows, key=lambda row: row["relative_score"])[:3]

    return {
        "latest_date": latest_date,
        "environment": environment,
        "summary": summary,
        "cards": cards,
        "rows": sorted(display_rows, key=lambda row: row["relative_score"], reverse=True),
        "strongest": strongest,
        "weakest": weakest,
        "breadth": {
            "date": latest_date,
            "up": up,
            "down": down,
            "flat": flat,
            "up_ratio": up_ratio,
            "ad": ad_value,
            "ad_line": ad_line,
            "new_high": new_high,
            "new_low": new_low,
            "nhnl": nhnl,
            "nhnl_5d": nhnl_5d,
        },
    }
