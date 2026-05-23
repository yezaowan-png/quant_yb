"""MACD 金叉/死叉策略"""

import backtrader as bt

from strategy.base import BaseStrategy


class MacdCrossStrategy(BaseStrategy):
    """DIF 上穿 DEA 买入，DIF 下穿 DEA 卖出"""

    params = (
        ("fast_period", 12),
        ("slow_period", 26),
        ("signal_period", 9),
    )

    def _init_indicators(self):
        self.macd = {}
        self.cross_up = {}
        self.cross_down = {}

        for data in self.datas:
            macd = bt.indicators.MACD(
                data.close,
                period_me1=self.p.fast_period,
                period_me2=self.p.slow_period,
                period_signal=self.p.signal_period,
            )
            self.macd[data] = macd
            self.cross_up[data] = bt.indicators.CrossOver(macd.macd, macd.signal)
            self.cross_down[data] = bt.indicators.CrossDown(macd.macd, macd.signal)

    def _next_buy_signal(self, data) -> bool:
        return bool(self.cross_up.get(data, 0))

    def _next_sell_signal(self, data) -> bool:
        return bool(self.cross_down.get(data, 0))
