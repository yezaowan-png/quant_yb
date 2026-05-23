"""双均线交叉策略 (SMA Cross)"""

import backtrader as bt

from strategy.base import BaseStrategy


class SmaCrossStrategy(BaseStrategy):
    """快速均线上穿慢速均线买入，下穿卖出"""

    params = (
        ("fast_period", 5),
        ("slow_period", 20),
    )

    def _init_indicators(self):
        self.sma_fast = {}
        self.sma_slow = {}
        self.cross_up = {}
        self.cross_down = {}

        for data in self.datas:
            sma_f = bt.indicators.SMA(data.close, period=self.p.fast_period)
            sma_s = bt.indicators.SMA(data.close, period=self.p.slow_period)
            self.sma_fast[data] = sma_f
            self.sma_slow[data] = sma_s
            self.cross_up[data] = bt.indicators.CrossOver(sma_f, sma_s)
            self.cross_down[data] = bt.indicators.CrossDown(sma_f, sma_s)

    def _next_buy_signal(self, data) -> bool:
        return bool(self.cross_up.get(data, 0))

    def _next_sell_signal(self, data) -> bool:
        return bool(self.cross_down.get(data, 0))
