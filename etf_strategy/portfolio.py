"""ETF portfolio and order-intent helpers."""

from __future__ import annotations

from typing import Iterable

import pandas as pd

from .data_provider import normalize_etf_symbol
from .models import OrderIntent, RankResult


def _held_symbols(positions: pd.DataFrame) -> set[str]:
    if positions is None or positions.empty or "symbol" not in positions.columns:
        return set()
    return {normalize_etf_symbol(symbol) for symbol in positions["symbol"].dropna().astype(str)}


def _available_amounts(positions: pd.DataFrame | None) -> dict[str, int]:
    if positions is None or positions.empty or "symbol" not in positions.columns:
        return {}
    amount_col = "available_amount" if "available_amount" in positions.columns else "available" if "available" in positions.columns else "amount"
    if amount_col not in positions.columns:
        return {}
    amounts: dict[str, int] = {}
    for _, row in positions.iterrows():
        symbol = normalize_etf_symbol(str(row.get("symbol", "")))
        if not symbol:
            continue
        amount = pd.to_numeric(pd.Series([row.get(amount_col)]), errors="coerce").fillna(0).iloc[0]
        amounts[symbol] = amounts.get(symbol, 0) + int(amount)
    return amounts


def order_intents_from_ranking(
    ranking: Iterable[RankResult],
    positions: pd.DataFrame | None,
    buy_amount: int = 1_000_000,
    top_n: int = 10,
    blacklist_amounts: dict[str, int] | None = None,
    trend_position_pct: dict[str, int] | None = None,
) -> list[OrderIntent]:
    """Convert parsed ETF ranking results into safe order intents.

    The helper mirrors the guide's execution rules but returns intentions only.
    A concrete broker adapter is responsible for position/cash checks and order
    placement.
    """
    held = _held_symbols(positions if positions is not None else pd.DataFrame())
    blacklist_amounts = blacklist_amounts or {}
    trend_position_pct = trend_position_pct or {}
    intents: list[OrderIntent] = []
    for item in sorted(ranking, key=lambda row: row.rank or 999999)[:top_n]:
        symbol = normalize_etf_symbol(item.symbol)
        if not symbol or symbol in held:
            continue
        amount = int(blacklist_amounts.get(item.name, buy_amount))
        status = str(item.raw.get("status", ""))
        if status in trend_position_pct:
            amount = int(amount * float(trend_position_pct[status]) / 100)
        if amount <= 0:
            continue
        intents.append(
            OrderIntent(
                symbol=symbol,
                name=item.name or symbol,
                side="buy",
                amount=amount,
                reason=f"{item.strategy or 'ETF排名'} 第{item.rank}名",
            )
        )
    return intents


def order_intents_from_rank_signal(
    rank_signal: dict,
    positions: pd.DataFrame | None,
    prices: dict[str, float] | None = None,
    buy_amount: int = 1_000_000,
    top_n: int = 10,
    blacklist_amounts: dict[str, int] | None = None,
    trend_position_pct: dict[str, int] | None = None,
    smash_sell_pct: int = 10,
) -> list[OrderIntent]:
    """Convert external ETF rank/emotion signals to dry-run order intents.

    Sell intents use share quantity. Buy intents use target cash amount, matching
    the existing research helper convention and leaving share sizing to a broker
    adapter with live quotes.
    """
    prices = {normalize_etf_symbol(k): float(v) for k, v in (prices or {}).items() if v}
    held = _held_symbols(positions if positions is not None else pd.DataFrame())
    available = _available_amounts(positions)
    blacklist_amounts = blacklist_amounts or {}
    trend_position_pct = trend_position_pct or {}
    intents: list[OrderIntent] = []
    sold: set[str] = set()

    for item in _rank_items(rank_signal.get("smash_signals", [])):
        symbol = normalize_etf_symbol(item.get("symbol", ""))
        if symbol not in held or symbol in sold:
            continue
        amount = _sell_lot_from_cash(
            cash=float(buy_amount) * float(smash_sell_pct) / 100.0,
            price=prices.get(symbol),
            available=available.get(symbol, 0),
        )
        if amount > 0:
            intents.append(OrderIntent(symbol=symbol, name=item.get("name") or symbol, side="sell", amount=amount, reason="抢砸信号"))
            sold.add(symbol)

    for item in _rank_items(rank_signal.get("exits", [])):
        symbol = normalize_etf_symbol(item.get("symbol", ""))
        amount = available.get(symbol, 0)
        if symbol in held and amount > 0 and symbol not in sold:
            intents.append(OrderIntent(symbol=symbol, name=item.get("name") or symbol, side="sell", amount=amount, reason="退出前N"))
            sold.add(symbol)

    trend_by_target = {
        _target_symbol(item.get("target", "")): str(item.get("status", ""))
        for item in rank_signal.get("trend_status", []) or []
        if isinstance(item, dict)
    }
    for item in _rank_items(rank_signal.get("ranking_rows") or rank_signal.get("ranking", []))[:top_n]:
        symbol = normalize_etf_symbol(item.get("symbol", ""))
        if not symbol or symbol in held:
            continue
        amount = int(blacklist_amounts.get(item.get("name", ""), blacklist_amounts.get(item.get("target", ""), buy_amount)))
        status = item.get("status") or trend_by_target.get(symbol, "")
        if status in trend_position_pct:
            amount = int(amount * float(trend_position_pct[status]) / 100)
        if amount <= 0:
            continue
        intents.append(
            OrderIntent(
                symbol=symbol,
                name=item.get("name") or symbol,
                side="buy",
                amount=amount,
                reason=f"外部三因子排名 第{item.get('rank') or len(intents) + 1}名",
            )
        )
    return intents


def _rank_items(items: Iterable) -> list[dict]:
    rows = []
    for idx, item in enumerate(items, start=1):
        if isinstance(item, dict):
            symbol = normalize_etf_symbol(str(item.get("symbol") or _target_symbol(str(item.get("target", "")))))
            name = str(item.get("name") or str(item.get("target", "")).split(":", 1)[0] or symbol)
            rows.append({**item, "symbol": symbol, "name": name, "target": f"{name}:{symbol}", "rank": item.get("rank") or idx})
        else:
            text = str(item)
            symbol = _target_symbol(text)
            name = text.split(":", 1)[0] if ":" in text else symbol
            rows.append({"symbol": symbol, "name": name, "target": text, "rank": idx, "status": ""})
    return rows


def _target_symbol(text: str) -> str:
    return normalize_etf_symbol(str(text or "").rsplit(":", 1)[-1])


def _sell_lot_from_cash(cash: float, price: float | None, available: int) -> int:
    if available <= 0:
        return 0
    max_available = int((available - 100) // 100 * 100) if available > 100 else 0
    if max_available <= 0:
        return 0
    if price is None or price <= 0:
        return max_available
    amount = int(cash / price // 100 * 100)
    return max(0, min(max_available, amount))
