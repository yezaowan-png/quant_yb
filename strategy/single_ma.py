"""单均线策略 —— 价格上穿均线买入，下穿卖出"""

import backtrader as bt

from strategy.base import BaseStrategy


class SingleMaStrategy(BaseStrategy):
    """收盘价上穿SMA买入，下穿卖出"""

    params = (
        ("period", 20),
    )

    def _init_indicators(self):
        self.sma = {}
        self.cross_up = {}
        self.cross_down = {}

        for data in self.datas:
            sma = bt.indicators.SMA(data.close, period=self.p.period)
            self.sma[data] = sma
            self.cross_up[data] = bt.indicators.CrossOver(data.close, sma)
            self.cross_down[data] = bt.indicators.CrossDown(data.close, sma)

    def _next_buy_signal(self, data) -> bool:
        return bool(self.cross_up.get(data, 0))

    def _next_sell_signal(self, data) -> bool:
        return bool(self.cross_down.get(data, 0))
