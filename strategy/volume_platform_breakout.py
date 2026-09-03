"""放量平台突破策略 (Volume Platform Breakout)."""

from __future__ import annotations

import backtrader as bt

from strategy.base import BaseStrategy


class VolumePlatformBreakoutStrategy(BaseStrategy):
    """平台窄幅整理后，放量向上突破并满足均线趋势时买入。"""

    PARAM_DEFINITIONS = {
        "lookback": {"type": int, "default": 60, "help": "平台识别回看交易日数"},
        "max_range_pct": {"type": float, "default": 0.2, "help": "平台最大振幅"},
        "touch_tolerance": {"type": float, "default": 0.06, "help": "上下沿触碰容忍度"},
        "min_upper_touches": {"type": int, "default": 2, "help": "上沿最少触碰次数"},
        "min_lower_touches": {"type": int, "default": 2, "help": "下沿最少触碰次数"},
        "breakout_pct": {"type": float, "default": 0.02, "help": "突破上沿确认幅度"},
        "volume_period": {"type": int, "default": 30, "help": "均量计算周期"},
        "volume_multiplier": {"type": float, "default": 1.3, "help": "放量倍数"},
        "ma_slope_days": {"type": int, "default": 1, "help": "MA20 向上确认天数"},
        "platform_sell_tolerance": {"type": float, "default": 0.05, "help": "跌破平台上沿卖出容忍度"},
        "stop_loss_pct": {"type": float, "default": 0.10, "help": "买入价止损比例"},
    }

    params = (
        ("lookback", 60),
        ("max_range_pct", 0.2),
        ("touch_tolerance", 0.06),
        ("min_upper_touches", 2),
        ("min_lower_touches", 2),
        ("breakout_pct", 0.02),
        ("volume_period", 30),
        ("volume_multiplier", 1.3),
        ("ma_slope_days", 1),
        ("platform_sell_tolerance", 0.05),
        ("stop_loss_pct", 0.10),
    )

    def _init_indicators(self):
        self.ma20 = {}
        self._entry_upper = {}
        self._entry_price = {}

        for data in self.datas:
            self.ma20[data] = bt.indicators.SMA(data.close, period=20)

    def _has_enough_history(self, data) -> bool:
        required = max(self.p.lookback, self.p.volume_period, 20 + self.p.ma_slope_days)
        return len(data) > required

    def _platform_bounds(self, data) -> tuple[float, float]:
        highs = [float(data.high[-i]) for i in range(1, self.p.lookback + 1)]
        lows = [float(data.low[-i]) for i in range(1, self.p.lookback + 1)]
        return max(highs), min(lows)

    def _volume_average(self, data) -> float:
        volumes = [float(data.volume[-i]) for i in range(1, self.p.volume_period + 1)]
        return sum(volumes) / self.p.volume_period

    def _next_buy_signal(self, data) -> bool:
        if self.getposition(data).size > 0:
            return False
        if not self._has_enough_history(data):
            return False

        upper, lower = self._platform_bounds(data)
        if lower <= 0:
            return False

        range_pct = (upper - lower) / lower
        if range_pct > self.p.max_range_pct:
            return False

        upper_touch_level = upper * (1 - self.p.touch_tolerance)
        lower_touch_level = lower * (1 + self.p.touch_tolerance)
        upper_touches = sum(
            1 for i in range(1, self.p.lookback + 1)
            if float(data.high[-i]) >= upper_touch_level
        )
        lower_touches = sum(
            1 for i in range(1, self.p.lookback + 1)
            if float(data.low[-i]) <= lower_touch_level
        )
        if upper_touches < self.p.min_upper_touches:
            return False
        if lower_touches < self.p.min_lower_touches:
            return False

        close = float(data.close[0])
        if close <= upper * (1 + self.p.breakout_pct):
            return False

        avg_volume = self._volume_average(data)
        if avg_volume <= 0 or float(data.volume[0]) <= avg_volume * self.p.volume_multiplier:
            return False

        ma20 = self.ma20[data]
        if close <= ma20[0]:
            return False
        if ma20[0] <= ma20[-self.p.ma_slope_days]:
            return False

        self._entry_upper[data] = upper
        return True

    def notify_order(self, order: bt.Order):
        super().notify_order(order)
        if order.status != order.Completed or order.executed.size == 0:
            return
        if order.isbuy():
            self._entry_price[order.data] = float(order.executed.price)
        else:
            if self.getposition(order.data).size <= 0:
                self._entry_price.pop(order.data, None)
                self._entry_upper.pop(order.data, None)

    def _next_sell_signal(self, data) -> bool:
        pos = self.getposition(data).size
        if pos <= 0:
            self._entry_upper.pop(data, None)
            self._entry_price.pop(data, None)
            return False

        close = float(data.close[0])
        if close < self.ma20[data][0]:
            return True

        entry_upper = self._entry_upper.get(data)
        if entry_upper is not None and close < entry_upper * (1 - self.p.platform_sell_tolerance):
            return True

        entry_price = self._entry_price.get(data)
        if entry_price is not None and close <= entry_price * (1 - self.p.stop_loss_pct):
            return True

        return False
