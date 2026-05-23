"""A 股策略基类 —— 封装 T+1 规则、不对称手续费、交易流水记录"""

from datetime import datetime

import backtrader as bt


class AShareCommission(bt.CommInfoBase):
    """A 股手续费：佣金 + 卖出印花税"""

    params = (
        ("commission", 0.00025),
        ("stamp_duty", 0.001),
        ("min_commission", 5.0),
        ("percabs", True),
        ("stocklike", True),
    )

    def _getcommission(self, size: int, price: float, pseudoexec: bool) -> float:
        value = abs(size) * price
        comm = value * self.p.commission
        comm = max(comm, self.p.min_commission)
        if size < 0:
            comm += value * self.p.stamp_duty
        return comm


class BaseStrategy(bt.Strategy):
    """A 股策略基类

    子类需定义:
        - params 中的策略参数
        - _init_indicators(): 初始化技术指标
        - _next_buy_signal(data) -> bool
        - _next_sell_signal(data) -> bool
    """

    params = (
        ("symbol", ""),
        ("log_trades", True),
    )

    def __init__(self):
        self.trade_records: list[dict] = []
        self._buy_dates: dict[bt.LineBuffer, object] = {}
        self.buy_signal_dates: list[str] = []
        self._init_indicators()

    # ---- 子类覆写入口 ----

    def _init_indicators(self):
        """子类在此初始化技术指标"""
        pass

    def _next_buy_signal(self, data) -> bool:
        """子类返回买入信号"""
        return False

    def _next_sell_signal(self, data) -> bool:
        """子类返回卖出信号"""
        return False

    # ---- backtrader 核心回调 ----

    def next(self):
        for data in self.datas:
            pos = self.getposition(data).size
            today = data.datetime.date(0)

            if self._next_buy_signal(data):
                self.buy_signal_dates.append(today.strftime("%Y-%m-%d"))
                if pos == 0:
                    self.buy(data=data)
                    self._buy_dates[data] = today

            if pos > 0 and self._next_sell_signal(data):
                buy_date = self._buy_dates.get(data)
                if buy_date is not None and today > buy_date:
                    self.sell(data=data)

    def notify_order(self, order: bt.Order):
        if order.status not in (order.Completed,):
            return
        if order.executed.size == 0:
            return

        record = {
            "date": self.data.datetime.date(0).strftime("%Y-%m-%d"),
            "symbol": self.p.symbol,
            "direction": "BUY" if order.isbuy() else "SELL",
            "price": round(order.executed.price, 4),
            "size": int(order.executed.size),
            "commission": round(order.executed.comm, 4),
            "pnl": 0.0,
        }
        self.trade_records.append(record)

    def notify_trade(self, trade: bt.Trade):
        if not trade.isclosed:
            return
        for rec in reversed(self.trade_records):
            if rec["direction"] == "SELL" and rec["pnl"] == 0.0:
                rec["pnl"] = round(trade.pnl, 2)
                break

    def get_trade_records(self) -> list[dict]:
        return self.trade_records
