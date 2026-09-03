"""Data payload helpers for single-stock HTML reports."""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from analysis.technical_structure import TechnicalStructureResult


def resample_ohlc(
    df: pd.DataFrame, freq: str, *, include_incomplete_bar: bool = True
) -> pd.DataFrame:
    """Compatibility helper using the shared last-trading-day resampler.

    Existing direct callers retain the historical inclusive behavior. Report
    entry points explicitly exclude an unfinished current week/month.
    """
    from analysis.technical_structure import normalize_ohlcv, resample_ohlcv

    timeframe = "1w" if str(freq).upper().startswith("W") else "1mo" if str(freq).upper().startswith("M") else "1d"
    source = normalize_ohlcv(
        df, symbol="REPORT", asset_type="other", timeframe="1d", adjustment="none"
    )
    return resample_ohlcv(
        source, timeframe, include_incomplete_bar=include_incomplete_bar
    ).data


def clean_list(values, decimals=None) -> list:
    """Convert indicator values into JSON-safe Python values."""
    result = []
    for value in values:
        if value is None or pd.isna(value):
            result.append(None)
        elif hasattr(value, "item"):
            result.append(value.item() if decimals is None else round(value.item(), decimals))
        else:
            result.append(value if decimals is None else round(value, decimals))
    return result


def calc_ma(close: pd.Series, period: int) -> list:
    ma = close.rolling(window=period).mean()
    return [round(v, 3) if not pd.isna(v) else None for v in ma.tolist()]


def calc_ema(close: pd.Series, period: int) -> list:
    ema = close.ewm(span=period, adjust=False, min_periods=period).mean()
    return [round(v, 3) if not pd.isna(v) else None for v in ema.tolist()]


def calc_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd_hist = 2 * (dif - dea)
    return (
        [round(v, 4) if not pd.isna(v) else None for v in dif.tolist()],
        [round(v, 4) if not pd.isna(v) else None for v in dea.tolist()],
        [round(v, 4) if not pd.isna(v) else None for v in macd_hist.tolist()],
    )


def calc_kdj(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 9):
    lowest_low = low.rolling(window=period).min()
    highest_high = high.rolling(window=period).max()
    rsv = ((close - lowest_low) / (highest_high - lowest_low + 1e-10)) * 100

    k_vals, d_vals, j_vals = [], [], []
    k, d = 50.0, 50.0
    smooth = 3
    alpha_k = 1.0 / smooth
    alpha_d = 1.0 / smooth

    for r in rsv:
        if pd.isna(r):
            k_vals.append(None)
            d_vals.append(None)
            j_vals.append(None)
        else:
            k = k * (1 - alpha_k) + r * alpha_k
            d = d * (1 - alpha_d) + k * alpha_d
            j = 3 * k - 2 * d
            k_vals.append(round(k, 2))
            d_vals.append(round(d, 2))
            j_vals.append(round(j, 2))

    return k_vals, d_vals, j_vals


def calc_rsi(close: pd.Series, period: int = 14) -> list:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi.iloc[:period] = None
    return [round(v, 2) if not pd.isna(v) else None for v in rsi.tolist()]


def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def strategy_param_value(strategy_cls, strategy_params: dict | None, name: str, default):
    """Read a strategy parameter from runtime params, then class metadata/defaults."""
    if strategy_params and name in strategy_params and strategy_params[name] is not None:
        return strategy_params[name]

    definitions = getattr(strategy_cls, "PARAM_DEFINITIONS", {})
    if name in definitions and "default" in definitions[name]:
        return definitions[name]["default"]

    params = getattr(strategy_cls, "params", ())
    if hasattr(params, "_getitems"):
        return dict(params._getitems()).get(name, default)
    for item in params:
        if isinstance(item, tuple) and len(item) >= 2 and item[0] == name:
            return item[1]
    return default


def map_trades_to_period(
    trades_df: pd.DataFrame,
    period_df: pd.DataFrame,
) -> tuple[list, list]:
    trade_dates = pd.to_datetime(trades_df["date"])
    period_dates = period_df["date"].values
    period_closes = period_df["close"].values

    buy_marks: list = []
    sell_marks: list = []

    for i, trade_date in enumerate(trade_dates):
        idx = np.searchsorted(period_dates, trade_date.to_numpy())
        if idx >= len(period_dates):
            continue
        bar_date_str = pd.Timestamp(period_dates[idx]).strftime("%Y-%m-%d")
        bar_close = float(period_closes[idx])
        direction = trades_df.iloc[i]["direction"]
        if direction == "BUY":
            buy_marks.append((bar_date_str, bar_close))
        else:
            sell_marks.append((bar_date_str, bar_close))

    return buy_marks, sell_marks


def compute_drawdowns(values: list[float]) -> list[float]:
    """Compute percentage drawdowns from an equity curve."""
    arr = np.array(values)
    peak = np.maximum.accumulate(arr)
    dd = (arr - peak) / peak * 100
    return [round(v, 2) for v in dd.tolist()]


def build_equity_payload(equity_data: pd.DataFrame | None) -> dict | None:
    """Build the report-wide equity payload, or None when no equity data exists."""
    if equity_data is None or equity_data.empty:
        return None

    eq_list = [round(float(v), 2) for v in equity_data["equity"].tolist()]
    return {
        "dates": equity_data["dates"].astype(str).tolist(),
        "equity": eq_list,
        "drawdowns": compute_drawdowns(eq_list),
    }


def build_stock_period_payload(
    symbol: str,
    strategy_name: str,
    period_id: str,
    period_label: str,
    df_period: pd.DataFrame,
    df_trades: pd.DataFrame,
    trendline_config: dict | None = None,
    technical_structure_result: TechnicalStructureResult | dict | None = None,
    technical_structure_series: list[dict] | None = None,
    manual_drawing: bool = False,
) -> dict:
    """Build chart payload for one daily/weekly/monthly stock report period."""
    dates = df_period["date"].dt.strftime("%Y-%m-%d").tolist()
    ohlc = df_period[["open", "close", "low", "high"]].values.tolist()
    ohlc_rounded = [
        [round(float(o), 2), round(float(c), 2), round(float(l), 2), round(float(h), 2)]
        for o, c, l, h in ohlc
    ]
    close = df_period["close"]
    volumes_raw = df_period["volume"].tolist() if "volume" in df_period.columns else []

    dif, dea, macd_hist = calc_macd(close)
    k_vals, d_vals, j_vals = calc_kdj(df_period["high"], df_period["low"], close)
    display_strategy = "手动画线" if strategy_name == "trendlines" else strategy_name

    if period_id == "daily":
        buy_marks, sell_marks = [], []
        if df_trades is not None and not df_trades.empty:
            for _, row in df_trades.iterrows():
                if row["direction"] == "BUY":
                    buy_marks.append((str(row["date"]), round(float(row["price"]), 2)))
                else:
                    sell_marks.append((str(row["date"]), round(float(row["price"]), 2)))
    else:
        buy_marks, sell_marks = map_trades_to_period(df_trades, df_period)

    payload = {
        "title": f"{symbol}  —  {display_strategy}  ({period_label})",
        "symbol": symbol,
        "period": period_id,
        "dates": dates,
        "ohlc": ohlc_rounded,
        "ma5": clean_list(calc_ma(close, 5), 2),
        "ma10": clean_list(calc_ma(close, 10), 2),
        "ma20": clean_list(calc_ma(close, 20), 2),
        "ma60": clean_list(calc_ma(close, 60), 2),
        "macd": {
            "dif": clean_list(dif, 3),
            "dea": clean_list(dea, 3),
            "hist": clean_list(macd_hist, 3),
        },
        "kdj": {
            "k": clean_list(k_vals, 1),
            "d": clean_list(d_vals, 1),
            "j": clean_list(j_vals, 1),
        },
        "rsi": clean_list(calc_rsi(close, 14), 1),
        "volume": clean_list(volumes_raw, 0),
        "trades": {"buy": buy_marks, "sell": sell_marks},
        "manualDrawing": bool(manual_drawing),
    }
    if not manual_drawing:
        payload["technical_structure"] = (
            technical_structure_result.to_dict()
            if isinstance(technical_structure_result, TechnicalStructureResult)
            else (technical_structure_result or {})
        )
        payload["technicalStructureSeries"] = technical_structure_series or []
    return payload


def build_weekly_ema_diagnostics(
    close: pd.Series,
    fast_period: int,
    slow_period: int,
) -> dict:
    return {
        "weeklyEmaFastLabel": f"周EMA{fast_period}",
        "weeklyEmaSlowLabel": f"周EMA{slow_period}",
        "weeklyEmaFast": clean_list(calc_ema(close, fast_period), 3),
        "weeklyEmaSlow": clean_list(calc_ema(close, slow_period), 3),
    }


def build_mtf_diagnostics_payload(
    df_ohlc: pd.DataFrame,
    df_trades: pd.DataFrame,
    strategy_cls,
    strategy_params: dict | None = None,
    weekly_feature_builder: Callable[[pd.DataFrame, object, dict], pd.DataFrame] | None = None,
) -> tuple[dict, dict]:
    """Recompute chart diagnostics for multi_timeframe_volume_trend reports."""
    params = strategy_params or {}
    df = (
        weekly_feature_builder(df_ohlc, strategy_cls, params).copy()
        if weekly_feature_builder is not None
        else df_ohlc.copy()
    )
    df = df.sort_values("date").reset_index(drop=True)

    trend_filter_mode = str(strategy_param_value(strategy_cls, params, "trend_filter_mode", "weekly"))
    weekly_fast_ema = int(strategy_param_value(strategy_cls, params, "weekly_fast_ema", 13))
    weekly_slow_ema = int(strategy_param_value(strategy_cls, params, "weekly_slow_ema", 26))
    weekly_macd_fast = int(strategy_param_value(strategy_cls, params, "weekly_macd_fast", 12))
    weekly_macd_slow = int(strategy_param_value(strategy_cls, params, "weekly_macd_slow", 26))
    weekly_macd_signal = int(strategy_param_value(strategy_cls, params, "weekly_macd_signal", 9))
    daily_ema_period = int(strategy_param_value(strategy_cls, params, "daily_ema_period", 50))
    rsi_period = int(strategy_param_value(strategy_cls, params, "rsi_period", 14))
    pullback_lookback = int(strategy_param_value(strategy_cls, params, "pullback_lookback", 20))
    pullback_pct = float(strategy_param_value(strategy_cls, params, "pullback_pct", 0.02))
    pullback_rsi = float(strategy_param_value(strategy_cls, params, "pullback_rsi", 40.0))
    pullback_valid_days = int(strategy_param_value(strategy_cls, params, "pullback_valid_days", 10))
    breakout_lookback = int(strategy_param_value(strategy_cls, params, "breakout_lookback", 3))
    vol_ma_period = int(strategy_param_value(strategy_cls, params, "vol_ma_period", 20))
    volume_mult = float(strategy_param_value(strategy_cls, params, "volume_mult", 1.5))
    vpt_ma_period = int(strategy_param_value(strategy_cls, params, "vpt_ma_period", 20))
    obv_ma_period = int(strategy_param_value(strategy_cls, params, "obv_ma_period", 20))
    min_volume_confirmations = int(
        strategy_param_value(strategy_cls, params, "min_volume_confirmations", 2)
    )
    atr_period = int(strategy_param_value(strategy_cls, params, "atr_period", 14))
    atr_mult = float(strategy_param_value(strategy_cls, params, "atr_mult", 2.0))
    trail_atr_mult = float(strategy_param_value(strategy_cls, params, "trail_atr_mult", 2.5))
    use_post_accel_platform_filter = bool(
        strategy_param_value(strategy_cls, params, "use_post_accel_platform_filter", True)
    )
    accel_lookback = int(strategy_param_value(strategy_cls, params, "accel_lookback", 10))
    accel_scan_days = int(strategy_param_value(strategy_cls, params, "accel_scan_days", 60))
    accel_return_pct = float(strategy_param_value(strategy_cls, params, "accel_return_pct", 0.30))
    post_accel_pullback_pct = float(
        strategy_param_value(strategy_cls, params, "post_accel_pullback_pct", 0.08)
    )
    platform_lookback = int(strategy_param_value(strategy_cls, params, "platform_lookback", 20))
    platform_max_range_pct = float(
        strategy_param_value(strategy_cls, params, "platform_max_range_pct", 0.10)
    )
    platform_ma_slope_pct = float(
        strategy_param_value(strategy_cls, params, "platform_ma_slope_pct", 0.03)
    )
    platform_breakout_pct = float(
        strategy_param_value(strategy_cls, params, "platform_breakout_pct", 0.01)
    )
    platform_breakout_volume_mult = float(
        strategy_param_value(strategy_cls, params, "platform_breakout_volume_mult", 1.5)
    )
    use_stalling_buy_filter = bool(
        strategy_param_value(strategy_cls, params, "use_stalling_buy_filter", True)
    )
    stalling_buy_filter_days = int(
        strategy_param_value(strategy_cls, params, "stalling_buy_filter_days", 5)
    )
    use_stalling_ma_exit = bool(
        strategy_param_value(strategy_cls, params, "use_stalling_ma_exit", True)
    )
    use_entry_day_stalling_exit = bool(
        strategy_param_value(strategy_cls, params, "use_entry_day_stalling_exit", True)
    )
    stalling_volume_mult = float(strategy_param_value(strategy_cls, params, "stalling_volume_mult", 1.3))
    stalling_max_close_gain_pct = float(
        strategy_param_value(strategy_cls, params, "stalling_max_close_gain_pct", 0.005)
    )
    stalling_prev_gain_min_pct = float(
        strategy_param_value(strategy_cls, params, "stalling_prev_gain_min_pct", 0.05)
    )
    stalling_gain_fade_pct = float(
        strategy_param_value(strategy_cls, params, "stalling_gain_fade_pct", 0.025)
    )
    stalling_upper_shadow_pct = float(
        strategy_param_value(strategy_cls, params, "stalling_upper_shadow_pct", 0.04)
    )
    stalling_close_position_max = float(
        strategy_param_value(strategy_cls, params, "stalling_close_position_max", 0.60)
    )

    close = df["close"].astype(float)
    open_ = df["open"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float)
    dates = df["date"].dt.strftime("%Y-%m-%d").tolist()

    daily_ema = close.ewm(
        span=daily_ema_period, adjust=False, min_periods=daily_ema_period
    ).mean()
    rsi = pd.Series(calc_rsi(close, rsi_period), index=df.index, dtype="float64")
    recent_high = high.shift(1).rolling(pullback_lookback).max()
    pullback_from_high = (recent_high - close) / recent_high
    pullback = (close < daily_ema) | (pullback_from_high >= pullback_pct) | (rsi <= pullback_rsi)
    recent_pullback = (
        pullback.rolling(pullback_valid_days, min_periods=1).max().fillna(False).astype(bool)
    )
    breakout_high = high.shift(1).rolling(breakout_lookback).max()
    breakout = close > breakout_high

    if trend_filter_mode == "daily_proxy":
        trend_fast = close.ewm(
            span=weekly_fast_ema * 5, adjust=False, min_periods=weekly_fast_ema * 5
        ).mean()
        trend_slow = close.ewm(
            span=weekly_slow_ema * 5, adjust=False, min_periods=weekly_slow_ema * 5
        ).mean()
        macd_fast = close.ewm(
            span=weekly_macd_fast * 5, adjust=False, min_periods=weekly_macd_fast * 5
        ).mean()
        macd_slow = close.ewm(
            span=weekly_macd_slow * 5, adjust=False, min_periods=weekly_macd_slow * 5
        ).mean()
        macd_line = macd_fast - macd_slow
        macd_signal = macd_line.ewm(
            span=weekly_macd_signal * 5, adjust=False, min_periods=weekly_macd_signal * 5
        ).mean()
        trend_long = (
            (close > trend_slow)
            & (trend_fast > trend_slow)
            & ((macd_line - macd_signal) > 0)
        ).fillna(False)
        trend_label = "代理趋势"
    else:
        trend_long = (
            (close > df["weekly_ema_slow"])
            & (df["weekly_ema_fast"] > df["weekly_ema_slow"])
            & (df["weekly_macd_hist"] > 0)
        ).fillna(False)
        trend_label = "周线趋势"

    pct_change = close.pct_change().fillna(0)
    vpt = (volume * pct_change).cumsum()
    obv_delta = np.where(close > close.shift(1), volume, np.where(close < close.shift(1), -volume, 0))
    obv = pd.Series(obv_delta, index=df.index).cumsum()
    avg_volume = volume.shift(1).rolling(vol_ma_period).mean()
    rvol_confirm = (volume / avg_volume) >= volume_mult
    vpt_confirm = vpt > vpt.rolling(vpt_ma_period).mean()
    obv_confirm = obv > obv.rolling(obv_ma_period).mean()
    close_confirm = close > close.shift(1)
    confirm_count = (
        rvol_confirm.fillna(False).astype(int)
        + vpt_confirm.fillna(False).astype(int)
        + obv_confirm.fillna(False).astype(int)
        + close_confirm.fillna(False).astype(int)
    )
    close_gain = close.pct_change()
    prev_gain = close.shift(1) / close.shift(2) - 1
    upper_shadow = (high - pd.concat([open_, close], axis=1).max(axis=1)).clip(lower=0)
    upper_shadow_pct = upper_shadow / close.shift(1)
    day_range = high - low
    close_position = ((close - low) / day_range.replace(0, np.nan)).fillna(1.0)
    stalling_reversal = (
        (prev_gain >= stalling_prev_gain_min_pct)
        & (close_gain > stalling_max_close_gain_pct)
        & ((prev_gain - close_gain) >= stalling_gain_fade_pct)
        & (upper_shadow_pct >= stalling_upper_shadow_pct)
        & (close_position <= stalling_close_position_max)
    )
    stalling = (
        (use_stalling_ma_exit or use_stalling_buy_filter or use_entry_day_stalling_exit)
        & ((volume / avg_volume) >= stalling_volume_mult)
        & ((close <= open_) | (close_gain <= stalling_max_close_gain_pct) | stalling_reversal)
    ).fillna(False)
    recent_stalling_for_buy = (
        stalling.rolling(stalling_buy_filter_days, min_periods=1).max().fillna(False).astype(bool)
        if use_stalling_buy_filter and stalling_buy_filter_days > 0
        else pd.Series(False, index=df.index)
    )

    if use_post_accel_platform_filter and accel_lookback > 0 and accel_scan_days > 0:
        accel_event = (close / close.shift(accel_lookback) - 1) >= accel_return_pct
        accel_event_idx = pd.Series(
            np.where(accel_event.fillna(False).to_numpy(), np.arange(len(df)), -1),
            index=df.index,
        )
        recent_accel_idx = (
            accel_event_idx.rolling(accel_scan_days, min_periods=1).max().fillna(-1).astype(int)
        )
    else:
        recent_accel_idx = pd.Series(-1, index=df.index, dtype=int)

    if platform_lookback > 1:
        platform_high = high.rolling(platform_lookback, min_periods=platform_lookback).max()
        platform_low = low.rolling(platform_lookback, min_periods=platform_lookback).min()
        platform_range_ok = (
            (platform_low > 0)
            & ((platform_high / platform_low - 1) <= platform_max_range_pct)
        )
        ma_period = min(20, platform_lookback)
        ma_now = close.rolling(ma_period, min_periods=ma_period).mean()
        ma_past = ma_now.shift(5)
        platform_ma_flat = (
            (ma_past > 0)
            & ((ma_now / ma_past - 1).abs() <= platform_ma_slope_pct)
        )
        peak_window = max(1, accel_scan_days + accel_lookback)
        recent_peak = high.rolling(peak_window, min_periods=1).max()
        platform_pullback = (
            (recent_peak > 0)
            & (((recent_peak - close) / recent_peak) >= post_accel_pullback_pct)
        )
        post_accel_platform = (platform_range_ok & platform_ma_flat & platform_pullback).fillna(False)
        prior_platform_high = high.shift(1).rolling(
            platform_lookback, min_periods=platform_lookback
        ).max()
        platform_breakout_volume = volume / avg_volume
        post_accel_platform_breakout = (
            (close > prior_platform_high * (1 + platform_breakout_pct))
            & (avg_volume > 0)
            & (platform_breakout_volume >= platform_breakout_volume_mult)
        ).fillna(False)
    else:
        post_accel_platform = pd.Series(False, index=df.index)
        post_accel_platform_breakout = pd.Series(False, index=df.index)

    recent_accel_idx_values = recent_accel_idx.to_numpy()
    platform_values = post_accel_platform.to_numpy(dtype=bool)
    platform_breakout_values = post_accel_platform_breakout.to_numpy(dtype=bool)
    post_accel_filter_active = []
    active = False
    platform_seen = False
    last_accel_idx = -1
    cleared_accel_idx = -1
    for idx in range(len(df)):
        accel_idx = int(recent_accel_idx_values[idx])
        if accel_idx >= 0 and accel_idx > cleared_accel_idx:
            active = True
            last_accel_idx = accel_idx
        if active and platform_values[idx]:
            platform_seen = True
        if active and platform_seen and platform_breakout_values[idx]:
            active = False
            platform_seen = False
            cleared_accel_idx = last_accel_idx
        post_accel_filter_active.append(active)
    post_accel_filter = pd.Series(post_accel_filter_active, index=df.index, dtype=bool)

    setup = (
        trend_long
        & recent_pullback
        & breakout
        & (confirm_count >= min_volume_confirmations)
        & (~recent_stalling_for_buy)
        & (~post_accel_filter)
    )

    atr = calc_atr(high, low, close, atr_period)
    initial_stop = [None] * len(df)
    trailing_stop = [None] * len(df)
    if df_trades is not None and not df_trades.empty:
        trade_rows = df_trades.copy()
        trade_rows["date"] = pd.to_datetime(trade_rows["date"])
        sell_dates = set(
            trade_rows.loc[trade_rows["direction"] == "SELL", "date"].dt.strftime("%Y-%m-%d")
        )
        active_entry = None
        active_initial = None
        highest_close = None
        for _, row in trade_rows.iterrows():
            if row["direction"] != "BUY":
                continue
            start_idx = int(np.searchsorted(df["date"].values, row["date"].to_datetime64()))
            if start_idx >= len(df):
                continue
            active_entry = float(row["price"])
            atr_at_entry = float(atr.iloc[start_idx]) if not pd.isna(atr.iloc[start_idx]) else 0.0
            active_initial = active_entry - atr_mult * atr_at_entry
            highest_close = float(close.iloc[start_idx])
            for j in range(start_idx, len(df)):
                if active_entry is None or active_initial is None or highest_close is None:
                    break
                highest_close = max(highest_close, float(close.iloc[j]))
                atr_now = float(atr.iloc[j]) if not pd.isna(atr.iloc[j]) else 0.0
                trail = highest_close - trail_atr_mult * atr_now
                initial_stop[j] = round(active_initial, 3)
                trailing_stop[j] = round(trail, 3)
                if dates[j] in sell_dates and j > start_idx:
                    active_entry = None
                    active_initial = None
                    highest_close = None
                    break

    diagnostics = {
        "pullback": [
            (dates[i], round(float(low.iloc[i]) * 0.985, 2))
            for i, flag in enumerate(pullback.fillna(False).tolist())
            if flag
        ],
        "breakout": [
            (dates[i], round(float(high.iloc[i]) * 1.015, 2))
            for i, flag in enumerate(breakout.fillna(False).tolist())
            if flag
        ],
        "setup": [
            (dates[i], round(float(high.iloc[i]) * 1.03, 2))
            for i, flag in enumerate(setup.fillna(False).tolist())
            if flag
        ],
        "stalling": [
            (dates[i], round(float(high.iloc[i]) * 1.02, 2))
            for i, flag in enumerate(stalling.tolist())
            if flag
        ],
        "confirmCount": confirm_count.astype(int).tolist(),
        "dailyEmaLabel": f"EMA{daily_ema_period}(日线)",
        "dailyEma50": clean_list(daily_ema.tolist(), 3),
        "initialStop": initial_stop,
        "trailingStop": trailing_stop,
    }

    latest_idx = len(df) - 1
    summary = {
        "trend_label": trend_label,
        "trend_text": "成立" if bool(trend_long.iloc[latest_idx]) else "未成立",
        "pullback_valid_days": pullback_valid_days,
        "pullback_text": "有" if bool(recent_pullback.iloc[latest_idx]) else "无",
        "stalling_buy_filter_days": stalling_buy_filter_days,
        "stalling_text": "有" if bool(recent_stalling_for_buy.iloc[latest_idx]) else "无",
        "post_accel_text": "过滤中" if bool(post_accel_filter.iloc[latest_idx]) else "未触发",
        "breakout_text": "是" if bool(breakout.iloc[latest_idx]) else "否",
        "confirm_text": str(int(confirm_count.iloc[latest_idx])),
        "setup_text": "是" if bool(setup.iloc[latest_idx]) else "否",
    }
    return diagnostics, summary
