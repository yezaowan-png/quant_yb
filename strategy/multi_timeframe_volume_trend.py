"""日线突破 + 周线趋势过滤策略。"""

from __future__ import annotations

import backtrader as bt

from strategy.base import BaseStrategy


class MultiTimeframeVolumeTrendStrategy(BaseStrategy):
    """Use completed weekly trend as a filter, trade breakouts on daily bars."""

    REQUIRES_WEEKLY = True

    PARAM_ALIASES = {
        "fast": "fast_ma",
        "slow": "slow_ma",
        "weekly": "weekly_ma",
        "lookback": "breakout_lookback",
        "vol_period": "volume_period",
        "vol_mult": "volume_multiplier",
    }
    PARAM_DEFINITIONS = {
        "fast_ma": {"type": int, "default": 10, "help": "日线快均线周期"},
        "slow_ma": {"type": int, "default": 30, "help": "日线慢均线周期"},
        "weekly_ma": {"type": int, "default": 20, "help": "周线趋势均线周期"},
        "breakout_lookback": {"type": int, "default": 20, "help": "日线突破回看交易日数"},
        "volume_period": {"type": int, "default": 20, "help": "日线均量周期"},
        "volume_multiplier": {"type": float, "default": 1.5, "help": "放量倍数"},
        "stop_loss_pct": {"type": float, "default": 0.10, "help": "买入价止损比例"},
    }

    params = (
        ("fast_ma", 10),
        ("slow_ma", 30),
        ("weekly_ma", 20),
        ("breakout_lookback", 20),
        ("volume_period", 20),
        ("volume_multiplier", 1.5),
        ("stop_loss_pct", 0.10),
    )

    def _init_indicators(self):
        self.daily = self.datas[0]
        self.weekly = self.datas[1] if len(self.datas) > 1 else None
        self.daily_fast = bt.indicators.SMA(self.daily.close, period=self.p.fast_ma)
        self.daily_slow = bt.indicators.SMA(self.daily.close, period=self.p.slow_ma)
        self.daily_volume = bt.indicators.SMA(self.daily.volume, period=self.p.volume_period)
        self.weekly_ma = (
            bt.indicators.SMA(self.weekly.close, period=self.p.weekly_ma)
            if self.weekly is not None else None
        )
        self._entry_price = {}

    def _has_daily_history(self, data) -> bool:
        required = max(self.p.slow_ma, self.p.breakout_lookback, self.p.volume_period)
        return len(data) > required

    def _has_weekly_history(self) -> bool:
        if self.weekly is None or self.weekly_ma is None:
            return False
        return len(self.weekly) > self.p.weekly_ma

    def _weekly_trend_ok(self) -> bool:
        if not self._has_weekly_history():
            return False
        return (
            float(self.weekly.close[0]) > float(self.weekly_ma[0])
            and float(self.weekly.close[0]) >= float(self.weekly.close[-1])
        )

    def _daily_breakout_ok(self, data) -> bool:
        prior_high = max(float(data.high[-i]) for i in range(1, self.p.breakout_lookback + 1))
        close = float(data.close[0])
        if close <= prior_high:
            return False
        if close <= float(self.daily_fast[0]) or float(self.daily_fast[0]) <= float(self.daily_slow[0]):
            return False
        avg_volume = float(self.daily_volume[0])
        if avg_volume <= 0:
            return False
        return float(data.volume[0]) >= avg_volume * self.p.volume_multiplier

    def _next_buy_signal(self, data) -> bool:
        if data is not self.daily:
            return False
        if self.getposition(data).size > 0:
            return False
        if not self._has_daily_history(data):
            return False
        return self._weekly_trend_ok() and self._daily_breakout_ok(data)

    def notify_order(self, order: bt.Order):
        super().notify_order(order)
        if order.status != order.Completed or order.executed.size == 0:
            return
        if order.isbuy():
            self._entry_price[order.data] = float(order.executed.price)
        elif self.getposition(order.data).size <= 0:
            self._entry_price.pop(order.data, None)

    def _next_sell_signal(self, data) -> bool:
        if data is not self.daily:
            return False
        pos = self.getposition(data).size
        if pos <= 0:
            self._entry_price.pop(data, None)
            return False
        close = float(data.close[0])
        if close < float(self.daily_slow[0]):
            return True
        if self._has_weekly_history() and float(self.weekly.close[0]) < float(self.weekly_ma[0]):
            return True
        entry_price = self._entry_price.get(data)
        if entry_price is not None and close <= entry_price * (1 - self.p.stop_loss_pct):
            return True
        return False
