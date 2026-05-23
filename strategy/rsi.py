"""RSI 超买超卖策略"""

import backtrader as bt

from strategy.base import BaseStrategy


class RsiStrategy(BaseStrategy):
    """RSI < oversold 买入，RSI > overbought 卖出"""

    params = (
        ("period", 14),
        ("oversold", 30),
        ("overbought", 70),
    )

    def _init_indicators(self):
        self.rsi = {}

        for data in self.datas:
            self.rsi[data] = bt.indicators.RSI(data.close, period=self.p.period)

    def _next_buy_signal(self, data) -> bool:
        rsi = self.rsi.get(data)
        if rsi is None:
            return False
        return rsi[0] < self.p.oversold

    def _next_sell_signal(self, data) -> bool:
        rsi = self.rsi.get(data)
        if rsi is None:
            return False
        return rsi[0] > self.p.overbought
