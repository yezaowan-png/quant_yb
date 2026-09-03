"""多周期量价趋势策略。

策略结构固定为两层周期：

1. 周线：由 runner 在日线数据入场前生成“已完成周线”特征，只做长周期方向过滤。
2. 日线：识别趋势内回调、突破触发、量价确认，并负责 ATR 风控退出。

本文件只处理交易信号和持仓状态，不读写文件、不下载数据、不生成报告。报告层会复算
诊断序列用于解释信号，但不会反向影响这里的买卖判断。
"""

from __future__ import annotations

import math

import backtrader as bt

from strategy.base import BaseStrategy


class MultiTimeframeVolumeTrendStrategy(BaseStrategy):
    """多周期量价趋势：已完成周线过滤、日线回调、突破和量价确认。

    买入路径：
    已完成周线趋势向上 -> 最近出现过日线回调 -> 今日突破历史高点 ->
    RVOL/VPT/OBV/收盘上涨中至少满足指定数量。

    卖出路径：
    ATR 初始止损、ATR 跟踪止损、放量滞涨后跌破短均线、周线趋势连续失效，
    可选固定 R 倍数止盈和量价衰竭退出。
    """

    REQUIRES_WEEKLY_FEATURES = True

    PARAM_ALIASES = {
        "volume_multiplier": "volume_mult",
        "volume_period": "vol_ma_period",
    }
    PARAM_DEFINITIONS = {
        "trend_filter_mode": {"type": str, "default": "weekly", "help": "趋势过滤模式: weekly/daily_proxy"},
        "weekly_fast_ema": {"type": int, "default": 13, "help": "周线快 EMA 周期"},
        "weekly_slow_ema": {"type": int, "default": 26, "help": "周线慢 EMA 周期"},
        "weekly_macd_fast": {"type": int, "default": 12, "help": "周线 MACD 快线周期"},
        "weekly_macd_slow": {"type": int, "default": 26, "help": "周线 MACD 慢线周期"},
        "weekly_macd_signal": {"type": int, "default": 9, "help": "周线 MACD 信号周期"},
        "daily_ema_period": {"type": int, "default": 50, "help": "日线回调 EMA 周期"},
        "rsi_period": {"type": int, "default": 14, "help": "RSI 周期"},
        "pullback_lookback": {"type": int, "default": 20, "help": "回撤高点回看窗口"},
        "pullback_pct": {"type": float, "default": 0.02, "help": "从历史高点回撤比例"},
        "pullback_rsi": {"type": float, "default": 40.0, "help": "回调 RSI 阈值"},
        "pullback_valid_days": {"type": int, "default": 10, "help": "回调信号有效交易日数"},
        "breakout_lookback": {"type": int, "default": 3, "help": "突破高点回看窗口"},
        "vol_ma_period": {"type": int, "default": 20, "help": "均量周期"},
        "volume_mult": {"type": float, "default": 1.5, "help": "相对成交量倍数"},
        "vpt_ma_period": {"type": int, "default": 20, "help": "VPT 均线周期"},
        "obv_ma_period": {"type": int, "default": 20, "help": "OBV 均线周期"},
        "min_volume_confirmations": {"type": int, "default": 2, "help": "最少量价确认数量"},
        "atr_period": {"type": int, "default": 14, "help": "ATR 周期"},
        "atr_mult": {"type": float, "default": 2.0, "help": "初始止损 ATR 倍数"},
        "trail_atr_mult": {"type": float, "default": 2.5, "help": "移动止损 ATR 倍数"},
        "trend_exit_confirm_days": {"type": int, "default": 2, "help": "趋势失效确认天数"},
        "use_post_accel_platform_filter": {"type": bool, "default": True, "help": "是否过滤加速上涨后的平台震荡买入"},
        "accel_lookback": {"type": int, "default": 10, "help": "加速上涨累计涨幅窗口"},
        "accel_scan_days": {"type": int, "default": 60, "help": "向前扫描加速上涨的交易日数"},
        "accel_return_pct": {"type": float, "default": 0.30, "help": "加速上涨累计涨幅阈值"},
        "post_accel_pullback_pct": {"type": float, "default": 0.08, "help": "加速后回落确认比例"},
        "platform_lookback": {"type": int, "default": 20, "help": "加速后平台观察窗口"},
        "platform_max_range_pct": {"type": float, "default": 0.10, "help": "平台最大振幅"},
        "platform_ma_slope_pct": {"type": float, "default": 0.03, "help": "平台均线走平阈值"},
        "platform_breakout_pct": {"type": float, "default": 0.01, "help": "解除平台过滤的突破幅度"},
        "platform_breakout_volume_mult": {"type": float, "default": 1.5, "help": "解除平台过滤的放量倍数"},
        "use_stalling_buy_filter": {"type": bool, "default": True, "help": "是否过滤近 N 日放量滞涨后的买入"},
        "stalling_buy_filter_days": {"type": int, "default": 5, "help": "买入前放量滞涨过滤交易日数"},
        "use_stalling_ma_exit": {"type": bool, "default": True, "help": "是否启用放量滞涨后跌破短均线退出"},
        "stalling_volume_mult": {"type": float, "default": 1.3, "help": "放量滞涨的相对成交量阈值"},
        "stalling_max_close_gain_pct": {"type": float, "default": 0.005, "help": "滞涨允许的最大收盘涨幅"},
        "stalling_prev_gain_min_pct": {"type": float, "default": 0.05, "help": "冲高回落滞涨要求的前一日最小涨幅"},
        "stalling_gain_fade_pct": {"type": float, "default": 0.025, "help": "冲高回落滞涨要求的涨幅衰减"},
        "stalling_upper_shadow_pct": {"type": float, "default": 0.04, "help": "冲高回落滞涨要求的上影线比例"},
        "stalling_close_position_max": {"type": float, "default": 0.60, "help": "冲高回落滞涨允许的最高收盘位置"},
        "use_entry_day_stalling_exit": {"type": bool, "default": True, "help": "买入成交当天放量滞涨时是否次日开盘退出"},
        "stalling_exit_ma_period": {"type": int, "default": 5, "help": "放量滞涨后的清仓均线周期"},
        "use_take_profit": {"type": bool, "default": False, "help": "是否启用固定 R 倍数止盈"},
        "take_profit_r": {"type": float, "default": 3.0, "help": "固定止盈 R 倍数"},
        "use_volume_exhaust_exit": {"type": bool, "default": False, "help": "是否启用量价衰竭退出"},
    }

    params = (
        ("trend_filter_mode", "weekly"),
        ("weekly_fast_ema", 13),
        ("weekly_slow_ema", 26),
        ("weekly_macd_fast", 12),
        ("weekly_macd_slow", 26),
        ("weekly_macd_signal", 9),
        ("daily_ema_period", 50),
        ("rsi_period", 14),
        ("pullback_lookback", 20),
        ("pullback_pct", 0.02),
        ("pullback_rsi", 40.0),
        ("pullback_valid_days", 10),
        ("breakout_lookback", 3),
        ("vol_ma_period", 20),
        ("volume_mult", 1.5),
        ("vpt_ma_period", 20),
        ("obv_ma_period", 20),
        ("min_volume_confirmations", 2),
        ("atr_period", 14),
        ("atr_mult", 2.0),
        ("trail_atr_mult", 2.5),
        ("trend_exit_confirm_days", 2),
        ("use_post_accel_platform_filter", True),
        ("accel_lookback", 10),
        ("accel_scan_days", 60),
        ("accel_return_pct", 0.30),
        ("post_accel_pullback_pct", 0.08),
        ("platform_lookback", 20),
        ("platform_max_range_pct", 0.10),
        ("platform_ma_slope_pct", 0.03),
        ("platform_breakout_pct", 0.01),
        ("platform_breakout_volume_mult", 1.5),
        ("use_stalling_buy_filter", True),
        ("stalling_buy_filter_days", 5),
        ("use_stalling_ma_exit", True),
        ("stalling_volume_mult", 1.3),
        ("stalling_max_close_gain_pct", 0.005),
        ("stalling_prev_gain_min_pct", 0.05),
        ("stalling_gain_fade_pct", 0.025),
        ("stalling_upper_shadow_pct", 0.04),
        ("stalling_close_position_max", 0.60),
        ("use_entry_day_stalling_exit", True),
        ("stalling_exit_ma_period", 5),
        ("use_take_profit", False),
        ("take_profit_r", 3.0),
        ("use_volume_exhaust_exit", False),
    )

    def _init_indicators(self):
        # daily_proxy 模式使用的日线扩周期指标；默认 weekly 模式不依赖它们。
        self.trend_fast = {}
        self.trend_slow = {}
        self.trend_macd = {}
        self.daily_ema = {}
        self.stalling_exit_ma = {}
        self.rsi = {}
        self.atr = {}

        # 这些状态都是按 data feed 分开维护，避免批量/多标的回测时互相污染。
        self._last_state_date = {}
        self._vpt_value = {}
        self._obv_value = {}
        self._vpt_history = {}
        self._obv_history = {}
        self._pullback_history = {}
        self._stalling_history = {}
        self._highest_close_since_entry = {}
        self._entry_price = {}
        self._entry_date = {}
        self._initial_stop = {}
        self._entry_risk = {}
        self._trend_fail_count = {}
        self._stalling_exit_armed = {}
        self._entry_day_stalling_exit = {}
        self._post_accel_filter_active = {}
        self._post_accel_platform_seen = {}
        self._post_accel_last_event_date = {}
        self._post_accel_cleared_event_date = {}

        for data in self.datas:
            if self.p.trend_filter_mode == "daily_proxy":
                self.trend_fast[data] = bt.indicators.EMA(
                    data.close, period=self.p.weekly_fast_ema * 5
                )
                self.trend_slow[data] = bt.indicators.EMA(
                    data.close, period=self.p.weekly_slow_ema * 5
                )
                self.trend_macd[data] = bt.indicators.MACD(
                    data.close,
                    period_me1=self.p.weekly_macd_fast * 5,
                    period_me2=self.p.weekly_macd_slow * 5,
                    period_signal=self.p.weekly_macd_signal * 5,
                )
            self.daily_ema[data] = bt.indicators.EMA(
                data.close, period=self.p.daily_ema_period
            )
            self.stalling_exit_ma[data] = bt.indicators.SMA(
                data.close, period=self.p.stalling_exit_ma_period
            )
            self.rsi[data] = bt.indicators.RSI(data.close, period=self.p.rsi_period)
            self.atr[data] = bt.indicators.ATR(data, period=self.p.atr_period)

            self._vpt_value[data] = 0.0
            self._obv_value[data] = 0.0
            self._vpt_history[data] = []
            self._obv_history[data] = []
            self._pullback_history[data] = []
            self._stalling_history[data] = []
            self._trend_fail_count[data] = 0
            self._stalling_exit_armed[data] = False
            self._entry_day_stalling_exit[data] = False
            self._post_accel_filter_active[data] = False
            self._post_accel_platform_seen[data] = False
            self._post_accel_last_event_date[data] = None
            self._post_accel_cleared_event_date[data] = None

    def _required_history(self) -> int:
        """返回当前参数组合下最小预热 bar 数。

        Backtrader 指标会先经历预热期；手写的历史窗口也需要足够 bar。
        这里统一给买卖信号加一道保护，避免早期数据不足时读取负索引越界
        或用未稳定的指标做判断。
        """
        # weekly 模式读取 runner 预计算的已完成周线特征。虽然 NaN 防御能避免
        # 早期报错，但这里仍把周线 EMA/MACD 的预热期计入，避免“可交易历史”
        # 与实际趋势过滤可用历史不一致。
        trend_period = max(
            self.p.weekly_slow_ema * 5,
            (self.p.weekly_macd_slow + self.p.weekly_macd_signal) * 5,
        )
        return max(
            trend_period,
            self.p.daily_ema_period,
            self.p.rsi_period,
            self.p.pullback_lookback,
            self.p.pullback_valid_days,
            self.p.breakout_lookback,
            self.p.vol_ma_period,
            self.p.vpt_ma_period,
            self.p.obv_ma_period,
            self.p.atr_period,
            self.p.accel_lookback + self.p.accel_scan_days,
            self.p.platform_lookback + 5,
            self.p.stalling_exit_ma_period,
            self.p.stalling_buy_filter_days,
            15,
        ) + 2

    def _has_enough_history(self, data) -> bool:
        return len(data) > self._required_history()

    def _trend_long(self, data) -> bool:
        if self.p.trend_filter_mode == "daily_proxy":
            return self._daily_proxy_trend_long(data)
        return self._weekly_trend_long(data)

    def _daily_proxy_trend_long(self, data) -> bool:
        macd = self.trend_macd[data]
        macd_hist = float(macd.macd[0] - macd.signal[0])
        close = float(data.close[0])
        trend_fast = float(self.trend_fast[data][0])
        trend_slow = float(self.trend_slow[data][0])
        return close > trend_slow and trend_fast > trend_slow and macd_hist > 0

    def _weekly_trend_long(self, data) -> bool:
        """读取 runner 生成的已完成周线特征。

        这里不做周线重采样，也不读取未来 bar。`weekly_*` line 已经在
        `engine.runner._add_completed_weekly_features()` 中通过 merge_asof
        贴回日线，当前日只能看到日期不晚于当前日的周线特征。
        """
        try:
            weekly_fast = float(data.weekly_ema_fast[0])
            weekly_slow = float(data.weekly_ema_slow[0])
            weekly_hist = float(data.weekly_macd_hist[0])
        except (AttributeError, IndexError, TypeError, ValueError):
            return False
        if not all(math.isfinite(v) for v in [weekly_fast, weekly_slow, weekly_hist]):
            return False
        return float(data.close[0]) > weekly_slow and weekly_fast > weekly_slow and weekly_hist > 0

    def _historical_high(self, data, lookback: int) -> float:
        # 从 -1 开始取值，明确排除今天，避免“用突破当天高点定义突破阈值”。
        return max(float(data.high[-i]) for i in range(1, lookback + 1))

    def _historical_volume_avg(self, data) -> float:
        # 均量同样只使用昨天及以前的数据；今天成交量只用于和历史均量比较。
        volumes = [float(data.volume[-i]) for i in range(1, self.p.vol_ma_period + 1)]
        return sum(volumes) / self.p.vol_ma_period

    def _line_value(self, line, offset: int) -> float:
        return float(line[-offset]) if offset > 0 else float(line[0])

    def _avg_line(self, line, start_offset: int, period: int) -> float:
        values = [self._line_value(line, start_offset + i) for i in range(period)]
        return sum(values) / period

    def _vpt_ma(self, data) -> float | None:
        history = self._vpt_history[data]
        if len(history) < self.p.vpt_ma_period:
            return None
        return sum(history[-self.p.vpt_ma_period:]) / self.p.vpt_ma_period

    def _obv_ma(self, data) -> float | None:
        history = self._obv_history[data]
        if len(history) < self.p.obv_ma_period:
            return None
        return sum(history[-self.p.obv_ma_period:]) / self.p.obv_ma_period

    def _current_pullback(self, data) -> bool:
        recent_high = self._historical_high(data, self.p.pullback_lookback)
        if recent_high <= 0:
            return False
        close = float(data.close[0])
        pullback_from_high = (recent_high - close) / recent_high
        return (
            close < float(self.daily_ema[data][0])
            or pullback_from_high >= self.p.pullback_pct
            or float(self.rsi[data][0]) <= self.p.pullback_rsi
        )

    def _recent_pullback(self, data) -> bool:
        history = self._pullback_history[data]
        if not history:
            return False
        return any(history[-self.p.pullback_valid_days:])

    def _breakout_long(self, data) -> bool:
        breakout_high = self._historical_high(data, self.p.breakout_lookback)
        return float(data.close[0]) > breakout_high

    def _volume_confirm_count(self, data) -> int:
        count = 0
        avg_volume = self._historical_volume_avg(data)
        if avg_volume > 0 and float(data.volume[0]) / avg_volume >= self.p.volume_mult:
            count += 1

        vpt_ma = self._vpt_ma(data)
        if vpt_ma is not None and self._vpt_value[data] > vpt_ma:
            count += 1

        obv_ma = self._obv_ma(data)
        if obv_ma is not None and self._obv_value[data] > obv_ma:
            count += 1

        if len(data) > 1 and float(data.close[0]) > float(data.close[-1]):
            count += 1
        return count

    def _volume_stalling(self, data) -> bool:
        """放量滞涨：成交量放大，但收盘未能继续有效上攻。

        均量基准只使用昨天及以前的数据；今天成交量和价格只作为当前
        bar 的状态判断，不读取未来 bar。
        """
        if (
            not (
                self.p.use_stalling_ma_exit
                or self.p.use_stalling_buy_filter
                or self.p.use_entry_day_stalling_exit
            )
            or len(data) < 3
        ):
            return False
        avg_volume = self._historical_volume_avg(data)
        if avg_volume <= 0:
            return False

        volume = float(data.volume[0] or 0)
        if volume / avg_volume < self.p.stalling_volume_mult:
            return False

        close = float(data.close[0])
        open_ = float(data.open[0])
        high = float(data.high[0])
        low = float(data.low[0])
        prev_close = float(data.close[-1])
        prev_prev_close = float(data.close[-2])
        close_gain = close / prev_close - 1 if prev_close > 0 else 0.0
        if close <= open_ or close_gain <= self.p.stalling_max_close_gain_pct:
            return True

        prev_gain = prev_close / prev_prev_close - 1 if prev_prev_close > 0 else 0.0
        upper_shadow = max(high - max(open_, close), 0.0)
        upper_shadow_pct = upper_shadow / prev_close if prev_close > 0 else 0.0
        day_range = high - low
        close_position = (close - low) / day_range if day_range > 0 else 1.0
        return (
            prev_gain >= self.p.stalling_prev_gain_min_pct
            and close_gain > self.p.stalling_max_close_gain_pct
            and prev_gain - close_gain >= self.p.stalling_gain_fade_pct
            and upper_shadow_pct >= self.p.stalling_upper_shadow_pct
            and close_position <= self.p.stalling_close_position_max
        )

    def _recent_acceleration_date(self, data):
        """最近一段时间内，最近一次 N 日累计加速上涨的结束日期。"""
        if not self.p.use_post_accel_platform_filter:
            return None
        lookback = int(self.p.accel_lookback or 0)
        scan_days = int(self.p.accel_scan_days or 0)
        if lookback <= 0 or scan_days <= 0:
            return None
        for end_offset in range(scan_days):
            start_offset = end_offset + lookback
            if len(data) <= start_offset:
                break
            start_close = self._line_value(data.close, start_offset)
            if start_close <= 0:
                continue
            end_close = self._line_value(data.close, end_offset)
            if end_close / start_close - 1 >= self.p.accel_return_pct:
                return data.datetime.date(-end_offset) if end_offset > 0 else data.datetime.date(0)
        return None

    def _post_accel_platform(self, data) -> bool:
        lookback = int(self.p.platform_lookback or 0)
        if lookback <= 1 or len(data) <= lookback + 5:
            return False

        highs = [self._line_value(data.high, i) for i in range(lookback)]
        lows = [self._line_value(data.low, i) for i in range(lookback)]
        platform_high = max(highs)
        platform_low = min(lows)
        if platform_low <= 0:
            return False
        if platform_high / platform_low - 1 > self.p.platform_max_range_pct:
            return False

        ma_period = min(20, lookback)
        ma_now = self._avg_line(data.close, 0, ma_period)
        ma_past = self._avg_line(data.close, 5, ma_period)
        if ma_past <= 0:
            return False
        if abs(ma_now / ma_past - 1) > self.p.platform_ma_slope_pct:
            return False

        peak_days = min(len(data) - 1, self.p.accel_scan_days + self.p.accel_lookback)
        recent_peak = max(self._line_value(data.high, i) for i in range(peak_days))
        if recent_peak <= 0:
            return False
        pullback = (recent_peak - float(data.close[0])) / recent_peak
        return pullback >= self.p.post_accel_pullback_pct

    def _post_accel_platform_breakout(self, data) -> bool:
        lookback = int(self.p.platform_lookback or 0)
        if lookback <= 1 or len(data) <= lookback:
            return False
        platform_high = max(self._line_value(data.high, i) for i in range(1, lookback + 1))
        close = float(data.close[0])
        if close <= platform_high * (1 + self.p.platform_breakout_pct):
            return False
        avg_volume = self._historical_volume_avg(data)
        if avg_volume <= 0:
            return False
        return float(data.volume[0] or 0) / avg_volume >= self.p.platform_breakout_volume_mult

    def _update_post_accel_filter(self, data) -> None:
        if not self.p.use_post_accel_platform_filter:
            self._post_accel_filter_active[data] = False
            self._post_accel_platform_seen[data] = False
            return

        accel_date = self._recent_acceleration_date(data)
        cleared_date = self._post_accel_cleared_event_date.get(data)
        if accel_date is not None and (cleared_date is None or accel_date > cleared_date):
            self._post_accel_filter_active[data] = True
            self._post_accel_last_event_date[data] = accel_date

        if not self._post_accel_filter_active.get(data, False):
            return

        if self._post_accel_platform(data):
            self._post_accel_platform_seen[data] = True

        if (
            self._post_accel_platform_seen.get(data, False)
            and self._post_accel_platform_breakout(data)
        ):
            self._post_accel_filter_active[data] = False
            self._post_accel_platform_seen[data] = False
            self._post_accel_cleared_event_date[data] = self._post_accel_last_event_date.get(data)

    def _recent_stalling_for_buy(self, data) -> bool:
        if not self.p.use_stalling_buy_filter:
            return False
        days = int(self.p.stalling_buy_filter_days or 0)
        if days <= 0:
            return False
        history = self._stalling_history[data]
        if not history:
            return False
        return any(history[-days:])

    def _ensure_state_updated(self, data) -> None:
        """每个交易日只推进一次手写状态。

        BaseStrategy 在同一个 bar 上可能先检查买入、再检查卖出。VPT/OBV、
        回调历史和趋势失效计数必须每天只更新一次，否则会把同一根 bar
        重复计入量价状态。
        """
        today = data.datetime.date(0)
        if self._last_state_date.get(data) == today:
            return

        close = float(data.close[0])
        prev_close = float(data.close[-1]) if len(data) > 1 else close
        volume = float(data.volume[0] or 0)

        if prev_close > 0:
            self._vpt_value[data] += volume * (close - prev_close) / prev_close
        if close > prev_close:
            self._obv_value[data] += volume
        elif close < prev_close:
            self._obv_value[data] -= volume

        self._vpt_history[data].append(self._vpt_value[data])
        self._obv_history[data].append(self._obv_value[data])
        keep_indicator_history = max(self.p.vpt_ma_period, self.p.obv_ma_period) * 3
        if len(self._vpt_history[data]) > keep_indicator_history:
            self._vpt_history[data] = self._vpt_history[data][-keep_indicator_history:]
        if len(self._obv_history[data]) > keep_indicator_history:
            self._obv_history[data] = self._obv_history[data][-keep_indicator_history:]

        # 回调不是买点，只是进入候选状态；后续必须再等突破和量价确认。
        pullback = self._has_enough_history(data) and self._current_pullback(data)
        self._pullback_history[data].append(pullback)
        if len(self._pullback_history[data]) > self.p.pullback_valid_days * 3:
            self._pullback_history[data] = self._pullback_history[data][
                -self.p.pullback_valid_days * 3:
            ]

        stalling = self._has_enough_history(data) and self._volume_stalling(data)
        self._stalling_history[data].append(stalling)
        keep_stalling_history = max(self.p.stalling_buy_filter_days, 1) * 3
        if len(self._stalling_history[data]) > keep_stalling_history:
            self._stalling_history[data] = self._stalling_history[data][-keep_stalling_history:]

        if self._has_enough_history(data):
            self._update_post_accel_filter(data)

        if self.getposition(data).size > 0:
            high_close = self._highest_close_since_entry.get(data, close)
            self._highest_close_since_entry[data] = max(high_close, close)
            if stalling:
                self._stalling_exit_armed[data] = True
                if self.p.use_entry_day_stalling_exit and self._entry_date.get(data) == today:
                    self._entry_day_stalling_exit[data] = True
            # 趋势失效需要连续确认，避免周线边界附近的一日抖动触发清仓。
            if self._has_enough_history(data) and not self._trend_long(data):
                self._trend_fail_count[data] = self._trend_fail_count.get(data, 0) + 1
            else:
                self._trend_fail_count[data] = 0
        else:
            self._trend_fail_count[data] = 0
            self._stalling_exit_armed[data] = False
            self._entry_day_stalling_exit[data] = False

        self._last_state_date[data] = today

    def _next_buy_signal(self, data) -> bool:
        self._ensure_state_updated(data)
        if self.getposition(data).size > 0:
            return False
        if not self._has_enough_history(data):
            return False
        return (
            self._trend_long(data)
            and self._recent_pullback(data)
            and self._breakout_long(data)
            and self._volume_confirm_count(data) >= self.p.min_volume_confirmations
            and not self._recent_stalling_for_buy(data)
            and not self._post_accel_filter_active.get(data, False)
        )

    def notify_order(self, order: bt.Order):
        super().notify_order(order)
        if order.status != order.Completed or order.executed.size == 0:
            return

        data = order.data
        if order.isbuy():
            # 买入信号发生在当前 bar，实际成交价来自 Backtrader 订单回调。
            # 初始止损和 R 倍数风险必须基于真实成交价，而不是信号日收盘价。
            entry = float(order.executed.price)
            atr = float(self.atr[data][0])
            initial_stop = entry - self.p.atr_mult * atr
            self._entry_price[data] = entry
            self._entry_date[data] = data.datetime.date(0)
            self._initial_stop[data] = initial_stop
            self._entry_risk[data] = max(entry - initial_stop, 0.0)
            self._highest_close_since_entry[data] = float(data.close[0])
            self._trend_fail_count[data] = 0
            self._stalling_exit_armed[data] = False
            self._entry_day_stalling_exit[data] = False
            if (
                self.p.use_entry_day_stalling_exit
                and self._last_state_date.get(data) == self._entry_date[data]
                and self._stalling_history.get(data)
                and self._stalling_history[data][-1]
            ):
                self._entry_day_stalling_exit[data] = True
        elif self.getposition(data).size <= 0:
            # 清仓后清理入场态，下一次买入重新计算止损、风险和最高收盘价。
            self._entry_price.pop(data, None)
            self._entry_date.pop(data, None)
            self._initial_stop.pop(data, None)
            self._entry_risk.pop(data, None)
            self._highest_close_since_entry.pop(data, None)
            self._trend_fail_count[data] = 0
            self._stalling_exit_armed[data] = False
            self._entry_day_stalling_exit[data] = False

    def _volume_exhaust_exit(self, data) -> bool:
        if len(data) < 2 or float(data.close[0]) <= float(data.close[-1]):
            return False
        avg_volume = self._historical_volume_avg(data)
        vpt_ma = self._vpt_ma(data)
        if avg_volume <= 0 or vpt_ma is None:
            return False
        rvol = float(data.volume[0]) / avg_volume
        return rvol < 1.0 and self._vpt_value[data] < vpt_ma

    def _next_sell_signal(self, data) -> bool:
        self._ensure_state_updated(data)
        pos = self.getposition(data).size
        if pos <= 0:
            return False
        if not self._has_enough_history(data):
            return False

        close = float(data.close[0])
        entry = self._entry_price.get(data, float(self.getposition(data).price or close))
        initial_stop = self._initial_stop.get(data)
        if initial_stop is None:
            # 兼容历史/异常状态：如果持仓存在但入场态缺失，用持仓均价补建。
            atr = float(self.atr[data][0])
            initial_stop = entry - self.p.atr_mult * atr
            self._initial_stop[data] = initial_stop
            self._entry_risk[data] = max(entry - initial_stop, 0.0)

        highest_close = self._highest_close_since_entry.get(data, close)
        trailing_stop = highest_close - self.p.trail_atr_mult * float(self.atr[data][0])
        if close < initial_stop or close < trailing_stop:
            return True

        if self._entry_day_stalling_exit.get(data, False):
            return True

        if self._stalling_exit_armed.get(data, False):
            ma_value = float(self.stalling_exit_ma[data][0])
            if math.isfinite(ma_value) and close < ma_value:
                return True

        if self._trend_fail_count.get(data, 0) >= self.p.trend_exit_confirm_days:
            return True

        if self.p.use_take_profit:
            risk = self._entry_risk.get(data, 0.0)
            if risk > 0 and close >= entry + self.p.take_profit_r * risk:
                return True

        if self.p.use_volume_exhaust_exit and self._volume_exhaust_exit(data):
            return True

        return False
