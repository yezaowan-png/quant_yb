"""ETF broker interfaces.

The dashboard integration uses these interfaces only to model order intent.
Actual QMT wiring should live in a concrete adapter outside the research report
path, with account credentials supplied by local secure configuration.
"""

from __future__ import annotations

from typing import Protocol

import pandas as pd

from .models import OrderIntent


class Broker(Protocol):
    def get_positions(self) -> pd.DataFrame:
        ...

    def get_cash(self) -> float:
        ...

    def get_quote(self, symbol: str) -> dict:
        ...

    def can_buy(self, symbol: str, price: float, amount: int) -> bool:
        ...

    def can_sell(self, symbol: str, amount: int) -> bool:
        ...

    def buy(self, symbol: str, amount: int, price: float, reason: str):
        ...

    def sell(self, symbol: str, amount: int, price: float, reason: str):
        ...


class DryRunBroker:
    """A safe broker adapter that records intents and never places orders."""

    def __init__(self, cash: float = 0.0, positions: pd.DataFrame | None = None):
        self.cash = float(cash)
        self.positions = positions.copy() if positions is not None else pd.DataFrame(columns=["symbol", "amount"])
        self.intents: list[OrderIntent] = []

    def get_positions(self) -> pd.DataFrame:
        return self.positions.copy()

    def get_cash(self) -> float:
        return self.cash

    def get_quote(self, symbol: str) -> dict:
        return {"symbol": symbol}

    def can_buy(self, symbol: str, price: float, amount: int) -> bool:
        return amount > 0 and price > 0 and self.cash >= price * amount

    def can_sell(self, symbol: str, amount: int) -> bool:
        if "symbol" not in self.positions.columns or "amount" not in self.positions.columns:
            return False
        held = pd.to_numeric(
            self.positions.loc[self.positions["symbol"].astype(str).str.upper() == symbol.upper(), "amount"],
            errors="coerce",
        ).fillna(0)
        return int(held.sum()) >= amount > 0

    def buy(self, symbol: str, amount: int, price: float, reason: str):
        intent = OrderIntent(symbol=symbol, name=symbol, side="buy", amount=int(amount), price=float(price), reason=reason)
        self.intents.append(intent)
        return intent

    def sell(self, symbol: str, amount: int, price: float, reason: str):
        intent = OrderIntent(symbol=symbol, name=symbol, side="sell", amount=int(amount), price=float(price), reason=reason)
        self.intents.append(intent)
        return intent
