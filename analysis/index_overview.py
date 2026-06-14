"""Index overview metrics for broad-market daily reports."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from visual.report import _calc_kdj, _calc_macd, _calc_ma, _calc_rsi


def _pct_change_from_window(close: pd.Series, window: int) -> float | None:
    if len(close) <= window:
        return None
    base = close.iloc[-window - 1]
    if pd.isna(base) or base == 0:
        return None
    return float((close.iloc[-1] / base - 1.0) * 100)


def _max_drawdown_pct(close: pd.Series, window: int = 20) -> float | None:
    if close.empty:
        return None
    values = close.tail(window).astype(float).to_numpy()
    if len(values) == 0:
        return None
    peaks = np.maximum.accumulate(values)
    drawdowns = (values - peaks) / peaks * 100
    return float(drawdowns.min())


def _annualized_volatility_pct(close: pd.Series, window: int = 20) -> float | None:
    returns = close.pct_change().dropna().tail(window)
    if returns.empty:
        return None
    return float(returns.std() * np.sqrt(252) * 100)


def _ytd_return_pct(df: pd.DataFrame) -> float | None:
    if df.empty:
        return None
    latest_year = df["date"].iloc[-1].year
    year_df = df[df["date"].dt.year == latest_year]
    if year_df.empty:
        return None
    first_close = year_df["close"].iloc[0]
    if pd.isna(first_close) or first_close == 0:
        return None
    return float((year_df["close"].iloc[-1] / first_close - 1.0) * 100)


def _fmt_pct(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{value:+.2f}%"


def _fmt_num(value: float | None, decimals: int = 2) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{value:,.{decimals}f}"


def _trend_text(close: pd.Series, ma20: list, ma60: list) -> str:
    latest_close = float(close.iloc[-1])
    latest_ma20 = ma20[-1]
    latest_ma60 = ma60[-1]
    if latest_ma20 is None or latest_ma60 is None:
        return "趋势：历史数据不足，暂不判断均线状态。"
    if latest_close >= latest_ma20 and latest_close >= latest_ma60:
        return "趋势：收盘位于 MA20 与 MA60 上方，中短期趋势偏强。"
    if latest_close >= latest_ma20:
        return "趋势：收盘位于 MA20 上方但仍低于 MA60，短线修复中。"
    if latest_close < latest_ma20 and latest_close < latest_ma60:
        return "趋势：收盘低于 MA20 与 MA60，趋势仍偏弱。"
    return "趋势：收盘低于 MA20 但高于 MA60，短期震荡整理。"


def _momentum_text(macd: dict[str, list]) -> str:
    dif = macd["dif"]
    dea = macd["dea"]
    if not dif or not dea or dif[-1] is None or dea[-1] is None:
        return "动量：MACD 数据不足，暂不判断。"
    if dif[-1] >= dea[-1] and dif[-1] >= 0:
        return "动量：DIF 位于 DEA 与 0 轴上方，动量偏积极。"
    if dif[-1] >= dea[-1]:
        return "动量：DIF 位于 DEA 上方但仍在 0 轴下方，反弹动能初现。"
    if dif[-1] < dea[-1] and dif[-1] < 0:
        return "动量：DIF 位于 DEA 与 0 轴下方，动量偏弱。"
    return "动量：DIF 回落至 DEA 下方，短线动能放缓。"


def _oscillator_text(kdj: dict[str, list], rsi: list) -> str:
    latest_j = kdj["j"][-1] if kdj["j"] else None
    latest_rsi = rsi[-1] if rsi else None
    if latest_j is None and latest_rsi is None:
        return "震荡：KDJ/RSI 数据不足，暂不判断。"
    if latest_rsi is not None and latest_rsi >= 70:
        return "震荡：RSI 进入偏高区域，短线需留意过热。"
    if latest_rsi is not None and latest_rsi <= 30:
        return "震荡：RSI 进入偏低区域，短线有超跌特征。"
    if latest_j is not None and latest_j >= 100:
        return "震荡：KDJ J 值偏高，短线波动可能加大。"
    if latest_j is not None and latest_j <= 0:
        return "震荡：KDJ J 值偏低，短线处于弱势修复区。"
    return "震荡：KDJ/RSI 处于常规区间，暂无极端超买超卖。"


def build_index_overview(df: pd.DataFrame, symbol: str, name: str = "") -> dict[str, Any]:
    """Build cards and short status notes for an index OHLCV dataframe."""
    if df.empty:
        raise ValueError("指数数据为空，无法生成概览。")
    if not pd.api.types.is_datetime64_any_dtype(df["date"]):
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    close = df["close"].astype(float)
    latest = df.iloc[-1]
    ma20 = _calc_ma(close, 20)
    ma60 = _calc_ma(close, 60)
    dif, dea, hist = _calc_macd(close)
    k_vals, d_vals, j_vals = _calc_kdj(df["high"], df["low"], close)
    rsi_vals = _calc_rsi(close, 14)

    pct_chg = latest.get("pct_chg")
    if pd.isna(pct_chg) and len(close) >= 2 and close.iloc[-2] != 0:
        pct_chg = (close.iloc[-1] / close.iloc[-2] - 1.0) * 100

    amount_ma20 = None
    if "amount" in df.columns:
        amount_ma20 = float(df["amount"].tail(20).mean())

    cards = [
        {"label": "最新日期", "value": latest["date"].strftime("%Y-%m-%d")},
        {"label": "最新收盘", "value": _fmt_num(float(latest["close"]))},
        {"label": "当日涨跌幅", "value": _fmt_pct(float(pct_chg) if not pd.isna(pct_chg) else None)},
        {"label": "近5日", "value": _fmt_pct(_pct_change_from_window(close, 5))},
        {"label": "近20日", "value": _fmt_pct(_pct_change_from_window(close, 20))},
        {"label": "年初至今", "value": _fmt_pct(_ytd_return_pct(df))},
        {"label": "20日最大回撤", "value": _fmt_pct(_max_drawdown_pct(close, 20))},
        {"label": "20日波动率", "value": _fmt_pct(_annualized_volatility_pct(close, 20))},
    ]
    if amount_ma20 is not None:
        cards.append({"label": "20日均成交额", "value": _fmt_num(amount_ma20, 0)})

    macd = {"dif": dif, "dea": dea, "hist": hist}
    kdj = {"k": k_vals, "d": d_vals, "j": j_vals}
    notes = [
        _trend_text(close, ma20, ma60),
        _momentum_text(macd),
        _oscillator_text(kdj, rsi_vals),
    ]

    return {
        "symbol": symbol,
        "name": name or symbol,
        "cards": cards,
        "notes": notes,
    }
