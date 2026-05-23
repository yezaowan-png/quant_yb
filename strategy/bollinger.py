"""布林带策略 —— 价格触及下轨反弹买入，触及上轨回落卖出"""

import backtrader as bt

from strategy.base import BaseStrategy


class BollingerStrategy(BaseStrategy):
    """收盘价突破下轨次日买入，突破上轨次日卖出"""

    params = (
        ("period", 20),
        ("devfactor", 2.0),
    )

    def _init_indicators(self):
        self.bb = {}
        self.signal_buy = {}
        self.signal_sell = {}

        for data in self.datas:
            bb = bt.indicators.BollingerBands(
                data.close, period=self.p.period, devfactor=self.p.devfactor,
            )
            self.bb[data] = bb
            # 前一日收盘 < 下轨 → 今日买入信号
            self.signal_buy[data] = data.close(-1) < bb.lines.bot(-1)
            # 前一日收盘 > 上轨 → 今日卖出信号
            self.signal_sell[data] = data.close(-1) > bb.lines.top(-1)

    def _next_buy_signal(self, data) -> bool:
        return bool(self.signal_buy.get(data, 0))

    def _next_sell_signal(self, data) -> bool:
        return bool(self.signal_sell.get(data, 0))
