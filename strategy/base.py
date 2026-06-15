"""A 股策略基类 —— 封装 T+1 规则、不对称手续费、交易流水记录"""

from datetime import datetime
from typing import Optional

import backtrader as bt


PARAM_DEFINITIONS: dict[str, dict] = {
    "symbol": {"type": str, "default": "", "help": "股票代码"},
    "log_trades": {"type": bool, "default": True, "help": "是否记录交易流水"},
}


def _param_names(strategy_cls) -> set[str]:
    params = getattr(strategy_cls, "params", ())
    if hasattr(params, "_getitems"):
        return {name for name, _ in params._getitems()}

    names: set[str] = set()
    for item in params:
        if isinstance(item, tuple) and item:
            names.add(item[0])
    return names


def get_strategy_param_definitions(strategy_cls) -> dict[str, dict]:
    """Return user-facing parameter metadata for one strategy class."""
    definitions = dict(PARAM_DEFINITIONS)
    definitions.update(getattr(strategy_cls, "PARAM_DEFINITIONS", {}))
    return {k: v for k, v in definitions.items() if k in _param_names(strategy_cls)}


def get_strategy_aliases(strategy_cls) -> dict[str, str]:
    return dict(getattr(strategy_cls, "PARAM_ALIASES", {}))


def normalize_strategy_params(strategy_cls, raw: dict, symbol: str = "") -> tuple[dict, list[str]]:
    """Filter and type-convert strategy params using the strategy's own schema."""
    definitions = get_strategy_param_definitions(strategy_cls)
    aliases = get_strategy_aliases(strategy_cls)
    normalized = {"symbol": symbol}
    unknown: list[str] = []

    for key, value in raw.items():
        if value is None:
            continue
        canonical = aliases.get(key, key)
        if canonical not in definitions or canonical in ("symbol", "log_trades"):
            if key not in {"strategy", "symbol", "symbols", "days"}:
                unknown.append(key)
            continue

        typ = definitions[canonical].get("type", str)
        try:
            if typ is bool:
                converted = bool(value)
            elif typ is int:
                converted = int(value)
            elif typ is float:
                converted = float(value)
            else:
                converted = value
        except (TypeError, ValueError):
            unknown.append(key)
            continue
        normalized[canonical] = converted

    return normalized, sorted(set(unknown))


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
        - _next_sell_size(data, pos) -> int
    """

    params = (
        ("symbol", ""),
        ("log_trades", True),
        ("enforce_price_limits", True),
        ("limit_pct", 0.10),
        ("volume_limit_ratio", 0.0),
        ("volume_unit", 100),
        ("trade_data_index", 0),
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

    def _next_sell_size(self, data, pos: int) -> int:
        """Return shares to sell. Defaults to full exit for legacy sell signals."""
        if self._next_sell_signal(data):
            return pos
        return 0

    def _normalize_sell_size(self, size: int, pos: int) -> int:
        try:
            size = int(size)
        except (TypeError, ValueError):
            return 0
        if size <= 0:
            return 0
        return min(size, pos)

    def _is_limit_up(self, data) -> bool:
        if not self.p.enforce_price_limits or len(data) < 2:
            return False
        return data.close[0] >= data.close[-1] * (1 + self.p.limit_pct) * 0.999

    def _is_limit_down(self, data) -> bool:
        if not self.p.enforce_price_limits or len(data) < 2:
            return False
        return data.close[0] <= data.close[-1] * (1 - self.p.limit_pct) * 1.001

    def _volume_cap_shares(self, data) -> Optional[int]:
        ratio = float(self.p.volume_limit_ratio or 0)
        if ratio <= 0:
            return None
        raw_volume = max(float(data.volume[0] or 0), 0)
        return int(raw_volume * int(self.p.volume_unit) * ratio)

    # ---- backtrader 核心回调 ----

    def _trade_datas(self):
        """Return data feeds that may submit orders. Multi-timeframe strategies trade data0."""
        try:
            idx = int(self.p.trade_data_index)
        except (TypeError, ValueError):
            idx = 0
        if 0 <= idx < len(self.datas):
            return [self.datas[idx]]
        return list(self.datas)

    def next(self):
        for data in self._trade_datas():
            pos = self.getposition(data).size
            today = data.datetime.date(0)

            if self._next_buy_signal(data):
                self.buy_signal_dates.append(today.strftime("%Y-%m-%d"))
                if pos == 0 and not self._is_limit_up(data):
                    # A股最小交易单位 100 股（1手），按可用资金 95% 计算手数
                    cash = self.broker.getcash()
                    price = data.close[0]
                    lots = int(cash * 0.95 / (price * 100))
                    size = lots * 100
                    volume_cap = self._volume_cap_shares(data)
                    if volume_cap is not None:
                        size = min(size, (volume_cap // 100) * 100)
                    if size > 0:
                        self.buy(data=data, size=size)
                        self._buy_dates[data] = today

            if pos > 0 and not self._is_limit_down(data):
                buy_date = self._buy_dates.get(data)
                if buy_date is not None and today > buy_date:
                    size = self._normalize_sell_size(self._next_sell_size(data, pos), pos)
                    volume_cap = self._volume_cap_shares(data)
                    if volume_cap is not None:
                        size = min(size, volume_cap)
                    if size > 0:
                        self.sell(data=data, size=size)

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
