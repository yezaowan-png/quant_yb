"""KDJ 超买超卖策略"""

import backtrader as bt

from strategy.base import BaseStrategy


class KdjStrategy(BaseStrategy):
    """K < 20 金叉买入，K > 80 死叉卖出"""

    params = (
        ("k_period", 9),
        ("smooth", 3),
        ("oversold", 20),
        ("overbought", 80),
    )

    def _init_indicators(self):
        self.kdj = {}
        self.cross_up = {}
        self.cross_down = {}

        for data in self.datas:
            kdj = KDJIndicator(
                data, period=self.p.k_period, smooth=self.p.smooth,
            )
            self.kdj[data] = kdj
            self.cross_up[data] = bt.indicators.CrossOver(kdj.K, kdj.D)
            self.cross_down[data] = bt.indicators.CrossDown(kdj.K, kdj.D)

    def _next_buy_signal(self, data) -> bool:
        kdj = self.kdj.get(data)
        if kdj is None:
            return False
        return kdj.K[0] < self.p.oversold and bool(self.cross_up.get(data, 0))

    def _next_sell_signal(self, data) -> bool:
        kdj = self.kdj.get(data)
        if kdj is None:
            return False
        return kdj.K[0] > self.p.overbought and bool(self.cross_down.get(data, 0))


class KDJIndicator(bt.Indicator):
    """KDJ 指标：K / D / J 三线"""

    lines = ("K", "D", "J")
    params = (("period", 9), ("smooth", 3))

    def __init__(self):
        highest_high = bt.indicators.Highest(self.data.high, period=self.p.period)
        lowest_low = bt.indicators.Lowest(self.data.low, period=self.p.period)
        rsv = (self.data.close - lowest_low) / (highest_high - lowest_low + 1e-10) * 100
        self.lines.K = bt.indicators.EMA(rsv, period=self.p.smooth)
        self.lines.D = bt.indicators.EMA(self.lines.K, period=self.p.smooth)
        self.lines.J = 3 * self.lines.K - 2 * self.lines.D
