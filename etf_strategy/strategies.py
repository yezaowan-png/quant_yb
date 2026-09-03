"""ETF signal and rotation strategy cores.

All functions accept standardized OHLCV data and return signal data only.  The
module deliberately contains no broker or order placement code.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .data_provider import STANDARD_COLUMNS


def ensure_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    rename = {column.lower(): column for column in STANDARD_COLUMNS}
    work = work.rename(columns={key: value for key, value in rename.items() if key in work.columns})
    if "date" in work.columns:
        work.index = pd.to_datetime(work["date"], errors="coerce")
    work.index = pd.to_datetime(work.index, errors="coerce")
    work = work.loc[work.index.notna()].sort_index()
    for column in STANDARD_COLUMNS:
        if column not in work.columns:
            work[column] = np.nan
        work[column] = pd.to_numeric(work[column], errors="coerce")
    return work[STANDARD_COLUMNS].dropna(subset=["Close"])


def _cross_signal(fast: pd.Series, slow: pd.Series) -> pd.Series:
    cross_up = (fast > slow) & (fast.shift(1) <= slow.shift(1))
    cross_down = (fast < slow) & (fast.shift(1) >= slow.shift(1))
    signal = pd.Series(0, index=fast.index, dtype="int64")
    signal.loc[cross_up] = 1
    signal.loc[cross_down] = -1
    return signal


def macd_timing(frame: pd.DataFrame, fast: int = 12, slow: int = 26, signal_period: int = 9) -> dict[str, Any]:
    df = ensure_ohlcv(frame)
    ema_fast = df["Close"].ewm(span=fast, adjust=False, min_periods=1).mean()
    ema_slow = df["Close"].ewm(span=slow, adjust=False, min_periods=1).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal_period, adjust=False, min_periods=1).mean()
    hist = (dif - dea) * 2
    out = df.copy()
    out["DIF"] = dif
    out["DEA"] = dea
    out["MACD"] = hist
    out["Signal"] = _cross_signal(dif, dea)
    latest = int(out["Signal"].iloc[-1]) if not out.empty else 0
    return {"signal": latest, "message": _signal_message(latest, "MACD"), "data": out}


def kama_timing(frame: pd.DataFrame, fast_period: int = 10, slow_period: int = 20) -> dict[str, Any]:
    df = ensure_ohlcv(frame)
    out = df.copy()
    out["KAMA_FAST"] = _kama(df["Close"], fast_period)
    out["KAMA_SLOW"] = _kama(df["Close"], slow_period)
    out["Signal"] = _cross_signal(out["KAMA_FAST"], out["KAMA_SLOW"])
    latest = int(out["Signal"].iloc[-1]) if not out.empty else 0
    return {"signal": latest, "message": _signal_message(latest, "双KAMA"), "data": out}


def bollinger_breakout(frame: pd.DataFrame, period: int = 20, upper_mult: float = 1.2, lower_mult: float = 1.2) -> dict[str, Any]:
    df = ensure_ohlcv(frame)
    ma = df["Close"].rolling(period, min_periods=1).mean()
    std = df["Close"].rolling(period, min_periods=2).std().fillna(0)
    upper = ma + upper_mult * std
    lower = ma - lower_mult * std
    out = df.copy()
    out["BOLL_MID"] = ma
    out["BOLL_UPPER"] = upper
    out["BOLL_LOWER"] = lower
    signal = pd.Series(0, index=out.index, dtype="int64")
    signal.loc[(df["Close"] > upper) & (df["Close"].shift(1) <= upper.shift(1))] = 1
    signal.loc[(df["Close"] < lower) & (df["Close"].shift(1) >= lower.shift(1))] = -1
    out["Signal"] = signal
    latest = int(out["Signal"].iloc[-1]) if not out.empty else 0
    return {"signal": latest, "message": _signal_message(latest, "布林带"), "data": out}


def n_day_breakout(frame: pd.DataFrame, high_days: int = 15, low_days: int = 5) -> dict[str, Any]:
    df = ensure_ohlcv(frame)
    high_line = df["High"].shift(1).rolling(high_days, min_periods=1).max()
    low_line = df["Low"].shift(1).rolling(low_days, min_periods=1).min()
    out = df.copy()
    out["BREAK_HIGH"] = high_line
    out["BREAK_LOW"] = low_line
    signal = pd.Series(0, index=out.index, dtype="int64")
    signal.loc[df["Close"] > high_line] = 1
    signal.loc[df["Close"] < low_line] = -1
    out["Signal"] = signal
    latest = int(out["Signal"].iloc[-1]) if not out.empty else 0
    return {"signal": latest, "message": _signal_message(latest, "N日突破"), "data": out}


def atr_stop(frame: pd.DataFrame, high_days: int = 15, low_days: int = 5, win_mult: float = 3.4, loss_mult: float = 1.8) -> dict[str, Any]:
    base = n_day_breakout(frame, high_days=high_days, low_days=low_days)["data"]
    out = base.copy()
    out["ATR21"] = _atr(out, 21)
    buy_price = math.nan
    signals: list[int] = []
    for _, row in out.iterrows():
        signal = int(row.get("Signal", 0))
        if signal == 1:
            buy_price = float(row["Close"])
        elif not math.isnan(buy_price):
            close = float(row["Close"])
            atr = float(row["ATR21"]) if pd.notna(row["ATR21"]) else 0.0
            if buy_price > close and (buy_price - close) > loss_mult * atr:
                signal = -1
                buy_price = math.nan
            elif buy_price < close and (close - buy_price) > win_mult * atr:
                signal = -1
                buy_price = math.nan
        if signal == -1:
            buy_price = math.nan
        signals.append(signal)
    out["Signal"] = signals
    latest = int(out["Signal"].iloc[-1]) if not out.empty else 0
    return {"signal": latest, "message": _signal_message(latest, "ATR止盈止损"), "data": out}


def momentum_rotation(
    all_etf_data: dict[str, pd.DataFrame],
    momentum_window: int = 20,
    hold_period: int = 5,
    hold_count: int = 3,
) -> dict[str, Any]:
    frames = {symbol: ensure_ohlcv(frame) for symbol, frame in all_etf_data.items() if not frame.empty}
    dates = sorted(set().union(*(set(frame.index) for frame in frames.values()))) if frames else []
    signal_frames = {symbol: frame.assign(Signal=0, Momentum=np.nan) for symbol, frame in frames.items()}
    holdings: dict[str, int] = {}
    ranking_rows: list[dict[str, Any]] = []
    for date in dates:
        scores: list[tuple[str, float]] = []
        for symbol, frame in frames.items():
            hist = frame.loc[frame.index < date]
            if len(hist) <= momentum_window:
                continue
            momentum = float(hist["Close"].iloc[-1] / hist["Close"].iloc[-momentum_window - 1] - 1)
            scores.append((symbol, momentum))
        scores.sort(key=lambda item: item[1], reverse=True)
        targets = [symbol for symbol, _ in scores[:hold_count]]
        for rank, (symbol, score) in enumerate(scores, start=1):
            ranking_rows.append({"date": date, "symbol": symbol, "momentum": score, "rank": rank, "target": symbol in targets})
        for symbol in list(holdings):
            holdings[symbol] += 1
            if symbol not in targets and holdings[symbol] >= hold_period and date in signal_frames[symbol].index:
                signal_frames[symbol].loc[date, "Signal"] = -1
                holdings.pop(symbol, None)
        for symbol in targets:
            if symbol not in holdings and len(holdings) < hold_count and date in signal_frames[symbol].index:
                signal_frames[symbol].loc[date, "Signal"] = 1
                holdings[symbol] = 0
            if date in signal_frames[symbol].index:
                score = next((value for candidate, value in scores if candidate == symbol), np.nan)
                signal_frames[symbol].loc[date, "Momentum"] = score
    if dates:
        last_date = dates[-1]
        for symbol in list(holdings):
            if last_date in signal_frames[symbol].index:
                signal_frames[symbol].loc[last_date, "Signal"] = -1
    return {"signals": signal_frames, "ranking": pd.DataFrame(ranking_rows)}


def three_factor_rotation(
    all_etf_data: dict[str, pd.DataFrame],
    trend_window: int = 15,
    momentum_short: int = 5,
    momentum_long: int = 10,
    volume_short: int = 5,
    volume_long: int = 15,
    min_slope: float = 0.0,
    hold_period: int = 5,
    hold_count: int = 1,
    trend_weight: float = 0.4,
    momentum_weight: float = 0.3,
    volume_weight: float = 0.3,
) -> dict[str, Any]:
    frames = {symbol: ensure_ohlcv(frame) for symbol, frame in all_etf_data.items() if not frame.empty}
    dates = sorted(set().union(*(set(frame.index) for frame in frames.values()))) if frames else []
    signal_frames = {symbol: frame.assign(Signal=0, FactorScore=np.nan) for symbol, frame in frames.items()}
    holdings: dict[str, int] = {}
    ranking_rows: list[dict[str, Any]] = []
    min_history = max(trend_window, momentum_long + 1, volume_long)
    for date in dates:
        raw_rows: list[dict[str, Any]] = []
        for symbol, frame in frames.items():
            hist = frame.loc[frame.index < date]
            if len(hist) < min_history:
                continue
            factors = _three_factors(hist, trend_window, momentum_short, momentum_long, volume_short, volume_long, min_slope)
            raw_rows.append({"symbol": symbol, **factors})
        if not raw_rows:
            continue
        score_df = pd.DataFrame(raw_rows)
        for column in ("trend_factor", "momentum_factor", "volume_factor"):
            score_df[column + "_norm"] = _zscore(score_df[column])
        score_df["score"] = (
            trend_weight * score_df["trend_factor_norm"]
            + momentum_weight * score_df["momentum_factor_norm"]
            + volume_weight * score_df["volume_factor_norm"]
        )
        score_df["score_norm"] = _zscore(score_df["score"])
        score_df = score_df.sort_values("score_norm", ascending=False).reset_index(drop=True)
        targets = score_df["symbol"].head(hold_count).tolist()
        for rank, row in score_df.iterrows():
            ranking_rows.append({**row.to_dict(), "date": date, "rank": rank + 1, "target": row["symbol"] in targets})
        for symbol in list(holdings):
            holdings[symbol] += 1
            if symbol not in targets and holdings[symbol] >= hold_period and date in signal_frames[symbol].index:
                signal_frames[symbol].loc[date, "Signal"] = -1
                holdings.pop(symbol, None)
        for symbol in targets:
            if symbol not in holdings and len(holdings) < hold_count and date in signal_frames[symbol].index:
                signal_frames[symbol].loc[date, "Signal"] = 1
                holdings[symbol] = 0
            if date in signal_frames[symbol].index:
                value = score_df.loc[score_df["symbol"] == symbol, "score_norm"]
                signal_frames[symbol].loc[date, "FactorScore"] = float(value.iloc[0]) if not value.empty else np.nan
    if dates:
        last_date = dates[-1]
        for symbol in list(holdings):
            if last_date in signal_frames[symbol].index:
                signal_frames[symbol].loc[last_date, "Signal"] = -1
    return {"signals": signal_frames, "ranking": pd.DataFrame(ranking_rows)}


def latest_signal_text(value: int | float | None) -> str:
    try:
        signal = int(value)
    except (TypeError, ValueError):
        signal = 0
    return {1: "买入", -1: "卖出", 0: "观望"}.get(signal, "观望")


def _signal_message(signal: int, name: str) -> str:
    action = latest_signal_text(signal)
    return f"{name}: {action}"


def _kama(close: pd.Series, period: int, fast: int = 2, slow: int = 30) -> pd.Series:
    close = pd.to_numeric(close, errors="coerce")
    change = close.diff(period).abs()
    volatility = close.diff().abs().rolling(period, min_periods=1).sum()
    er = (change / volatility.replace(0, np.nan)).fillna(0)
    fast_sc = 2 / (fast + 1)
    slow_sc = 2 / (slow + 1)
    sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
    result = close.copy()
    for idx in range(1, len(close)):
        prev = result.iloc[idx - 1] if pd.notna(result.iloc[idx - 1]) else close.iloc[idx - 1]
        result.iloc[idx] = prev + sc.iloc[idx] * (close.iloc[idx] - prev)
    return result


def _atr(frame: pd.DataFrame, period: int) -> pd.Series:
    prev_close = frame["Close"].shift(1)
    true_range = pd.concat(
        [
            frame["High"] - frame["Low"],
            (frame["High"] - prev_close).abs(),
            (frame["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(period, min_periods=1).mean()


def _three_factors(
    hist: pd.DataFrame,
    trend_window: int,
    momentum_short: int,
    momentum_long: int,
    volume_short: int,
    volume_long: int,
    min_slope: float,
) -> dict[str, float]:
    close = hist["Close"].dropna()
    volume = hist["Volume"].dropna()
    y = np.log(close.iloc[-trend_window:].to_numpy(dtype=float))
    x = np.arange(len(y), dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    predicted = slope * x + intercept
    ss_res = float(((y - predicted) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    trend_factor = 0.0 if ss_tot == 0 else max(0.0, 1 - ss_res / ss_tot)
    if slope < min_slope:
        trend_factor *= 0.1
    momentum_factor = (
        float(close.iloc[-1] / close.iloc[-momentum_short - 1] - 1)
        + float(close.iloc[-1] / close.iloc[-momentum_long - 1] - 1)
    ) * 0.2
    vol_short = float(volume.iloc[-volume_short:].mean()) if len(volume) >= volume_short else np.nan
    vol_long = float(volume.iloc[-volume_long:].mean()) if len(volume) >= volume_long else np.nan
    volume_factor = vol_short / vol_long if vol_long and not np.isnan(vol_long) else 0.0
    return {
        "trend_factor": float(trend_factor),
        "momentum_factor": float(momentum_factor),
        "volume_factor": float(volume_factor),
    }


def _zscore(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    std = values.std(ddof=0)
    if pd.isna(std) or std == 0:
        return pd.Series(0.0, index=series.index)
    return (values - values.mean()) / std
