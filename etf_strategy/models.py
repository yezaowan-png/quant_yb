"""Standard ETF strategy data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


SignalValue = Literal[-1, 0, 1]
OrderSide = Literal["buy", "sell"]


@dataclass(frozen=True)
class Signal:
    symbol: str
    name: str = ""
    signal: SignalValue = 0
    strategy: str = ""
    message: str = ""
    trade_time: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RankResult:
    symbol: str
    name: str = ""
    rank: int = 0
    score: float = 0.0
    target: bool = False
    strategy: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderIntent:
    symbol: str
    name: str
    side: OrderSide
    amount: int
    reason: str
    price_type: str = "limit"
    price: float | None = None
