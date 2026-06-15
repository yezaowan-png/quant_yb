"""Build research target weights from buy signal CSV files."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class AllocationResult:
    output_path: Path
    method: str
    count: int
    gross_exposure: float
    max_weight: float


def _load_prices(cache_dir: Path, symbol: str, lookback: int) -> tuple[float | None, str]:
    path = cache_dir / f"{symbol}.csv"
    if not path.exists():
        return None, "missing_cache"
    try:
        df = pd.read_csv(path, dtype={"date": str})
    except Exception:
        return None, "read_error"
    if df.empty or "close" not in df.columns:
        return None, "invalid_cache"
    close = pd.to_numeric(df["close"], errors="coerce").dropna().tail(lookback + 1)
    if len(close) < max(10, min(lookback, 20)):
        return None, "insufficient_history"
    returns = close.pct_change().dropna()
    vol = float(returns.std() * np.sqrt(252))
    if not np.isfinite(vol) or vol <= 0:
        return None, "invalid_volatility"
    return vol, "ok"


def _cap_and_redistribute(weights: pd.Series, max_weight: float, gross_exposure: float) -> pd.Series:
    if weights.empty:
        return weights
    weights = weights.clip(lower=0)
    if weights.sum() <= 0:
        weights = pd.Series(1.0 / len(weights), index=weights.index)
    else:
        weights = weights / weights.sum()

    cap = max_weight / gross_exposure if gross_exposure > 0 else max_weight
    cap = max(0.0, min(float(cap), 1.0))
    capped = weights.copy()
    for _ in range(len(weights) + 2):
        over = capped > cap
        if not over.any():
            break
        excess = float((capped[over] - cap).sum())
        capped[over] = cap
        under = ~over
        if not under.any() or excess <= 0:
            break
        under_sum = float(capped[under].sum())
        if under_sum <= 0:
            capped[under] += excess / int(under.sum())
        else:
            capped[under] += capped[under] / under_sum * excess

    return (capped * gross_exposure).round(6)


def build_target_weights(
    config: dict[str, Any],
    signals_path: Path | str,
    method: str = "equal",
    max_weight: float = 0.10,
    gross_exposure: float = 1.0,
    lookback: int = 60,
    output_dir: Path | str | None = None,
) -> AllocationResult:
    signals_path = Path(signals_path)
    if not signals_path.exists():
        raise FileNotFoundError(signals_path)
    signals = pd.read_csv(signals_path, dtype={"symbol": str})
    if signals.empty or "symbol" not in signals.columns:
        raise ValueError("signals CSV must contain a non-empty symbol column")

    rows = signals.drop_duplicates(subset=["symbol"]).copy()
    rows["symbol"] = rows["symbol"].astype(str)
    cache_dir = Path(config.get("data", {}).get("cache_dir", "data/cache"))

    vols: list[float | None] = []
    statuses: list[str] = []
    for symbol in rows["symbol"]:
        vol, status = _load_prices(cache_dir, symbol, lookback)
        vols.append(vol)
        statuses.append(status)
    rows["annual_volatility"] = vols
    rows["data_status"] = statuses

    method = method.lower()
    if method not in {"equal", "inverse_vol"}:
        raise ValueError("method must be equal or inverse_vol")

    if method == "inverse_vol" and rows["annual_volatility"].notna().any():
        raw = 1.0 / rows["annual_volatility"].astype(float)
        raw = raw.replace([np.inf, -np.inf], np.nan).fillna(0)
        if raw.sum() <= 0:
            raw = pd.Series(1.0, index=rows.index)
            rows["data_status"] = rows["data_status"].where(rows["data_status"] == "ok", "fallback_equal")
    else:
        raw = pd.Series(1.0, index=rows.index)
        if method == "inverse_vol":
            rows["data_status"] = "fallback_equal"

    raw_weight = raw / raw.sum() * gross_exposure if raw.sum() > 0 else raw
    target_weight = _cap_and_redistribute(raw_weight, max_weight=max_weight, gross_exposure=gross_exposure)

    out = pd.DataFrame(
        {
            "date": date.today().strftime("%Y%m%d"),
            "symbol": rows["symbol"],
            "strategy": rows.get("strategy", ""),
            "signal_dates": rows.get("recent_buy_dates", rows.get("signal_date", "")),
            "method": method,
            "raw_weight": raw_weight.round(6),
            "target_weight": target_weight,
            "max_weight": max_weight,
            "gross_exposure": gross_exposure,
            "annual_volatility": rows["annual_volatility"].round(6),
            "data_status": rows["data_status"],
            "source": str(signals_path),
        }
    )

    if output_dir:
        target_dir = Path(output_dir)
    else:
        output_cfg = config.get("output", {})
        target_dir = Path(output_cfg.get("portfolio_dir") or (Path(output_cfg.get("trades_dir", "output/trades")).parent / "portfolio"))
    target_dir.mkdir(parents=True, exist_ok=True)
    output_path = target_dir / f"target_weights_{date.today().strftime('%Y%m%d')}.csv"
    out.to_csv(output_path, index=False)
    return AllocationResult(
        output_path=output_path,
        method=method,
        count=len(out),
        gross_exposure=float(out["target_weight"].sum()),
        max_weight=float(out["target_weight"].max()) if len(out) else 0.0,
    )
