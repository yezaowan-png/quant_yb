"""Decision memory recorder.

The recorder stores strategy signals for later review. Future returns are
intentionally left blank at record time so they cannot influence signal
generation.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


MEMORY_COLUMNS = [
    "signal_id",
    "symbol",
    "strategy",
    "signal_date",
    "signal_type",
    "price",
    "params_json",
    "market_context_json",
    "source",
    "recorded_at",
    "evaluation_status",
    "future_5d_return_pct",
    "future_10d_return_pct",
    "future_20d_return_pct",
    "benchmark_5d_return_pct",
    "benchmark_10d_return_pct",
    "benchmark_20d_return_pct",
    "excess_5d_return_pct",
    "excess_10d_return_pct",
    "excess_20d_return_pct",
    "evaluated_at",
]


def decision_memory_path(config: dict) -> Path:
    """Return the configured decision memory CSV path."""
    output = config.get("output", {})
    decisions_dir = Path(output.get("decisions_dir", "output/decisions"))
    return decisions_dir / "decision_memory.csv"


def load_memory(config: dict) -> pd.DataFrame:
    """Load decision memory, returning an empty frame with stable columns."""
    path = decision_memory_path(config)
    if not path.exists():
        return pd.DataFrame(columns=MEMORY_COLUMNS)
    df = pd.read_csv(path, dtype={"symbol": str, "signal_date": str})
    for column in MEMORY_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA
    return df[MEMORY_COLUMNS]


def save_memory(config: dict, df: pd.DataFrame) -> Path:
    """Persist decision memory with stable column order."""
    path = decision_memory_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    for column in MEMORY_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA
    df[MEMORY_COLUMNS].to_csv(path, index=False)
    return path


def _json_dumps(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True, default=str)


def _signal_id(
    symbol: str,
    strategy: str,
    signal_date: str,
    signal_type: str,
    params_json: str,
) -> str:
    raw = f"{symbol}|{strategy}|{signal_date}|{signal_type}|{params_json}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _split_signal_dates(raw_dates: Any) -> list[str]:
    if raw_dates is None or pd.isna(raw_dates):
        return []
    if isinstance(raw_dates, (list, tuple, set)):
        values = raw_dates
    else:
        values = str(raw_dates).replace(";", ",").split(",")
    return [str(v).strip()[:10] for v in values if str(v).strip()]


def _price_on_signal_date(data: pd.DataFrame | None, signal_date: str) -> float | None:
    if data is None or data.empty or "date" not in data.columns or "close" not in data.columns:
        return None
    df = data.copy()
    if not pd.api.types.is_datetime64_any_dtype(df["date"]):
        df["date"] = pd.to_datetime(df["date"])
    target = pd.Timestamp(signal_date)
    sub = df[df["date"] >= target].sort_values("date")
    if sub.empty:
        return None
    return round(float(sub.iloc[0]["close"]), 4)


def build_rows_from_signals(
    strategy: str,
    signals: Iterable[dict],
    strategy_params: dict | None = None,
    data_map: dict[str, pd.DataFrame] | None = None,
    source: str = "scan",
    signal_type: str = "BUY",
) -> list[dict[str, Any]]:
    """Convert scan result rows into stable decision memory rows."""
    params_json = _json_dumps(strategy_params)
    recorded_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows: list[dict[str, Any]] = []

    for item in signals:
        symbol = str(item.get("symbol", "")).upper().strip()
        if not symbol:
            continue
        date_values = _split_signal_dates(item.get("recent_buy_dates") or item.get("signal_date"))
        data = data_map.get(symbol) if data_map else None

        for signal_date in date_values:
            price = item.get("price")
            if price is None or pd.isna(price):
                price = _price_on_signal_date(data, signal_date)
            row = {
                "signal_id": _signal_id(symbol, strategy, signal_date, signal_type, params_json),
                "symbol": symbol,
                "strategy": strategy,
                "signal_date": signal_date,
                "signal_type": signal_type,
                "price": price,
                "params_json": params_json,
                "market_context_json": "{}",
                "source": source,
                "recorded_at": recorded_at,
                "evaluation_status": "pending",
                "future_5d_return_pct": pd.NA,
                "future_10d_return_pct": pd.NA,
                "future_20d_return_pct": pd.NA,
                "benchmark_5d_return_pct": pd.NA,
                "benchmark_10d_return_pct": pd.NA,
                "benchmark_20d_return_pct": pd.NA,
                "excess_5d_return_pct": pd.NA,
                "excess_10d_return_pct": pd.NA,
                "excess_20d_return_pct": pd.NA,
                "evaluated_at": pd.NA,
            }
            rows.append(row)
    return rows


def append_buy_signals(
    config: dict,
    strategy: str,
    signals: Iterable[dict],
    strategy_params: dict | None = None,
    data_map: dict[str, pd.DataFrame] | None = None,
    source: str = "scan",
) -> tuple[Path, int]:
    """Append buy signals to decision memory and skip already-seen signals."""
    rows = build_rows_from_signals(
        strategy=strategy,
        signals=signals,
        strategy_params=strategy_params,
        data_map=data_map,
        source=source,
        signal_type="BUY",
    )
    path = decision_memory_path(config)
    if not rows:
        return path, 0

    existing = load_memory(config)
    new_df = pd.DataFrame(rows, columns=MEMORY_COLUMNS)
    known_ids = set(existing["signal_id"].dropna().astype(str).tolist())
    new_df = new_df[~new_df["signal_id"].astype(str).isin(known_ids)]
    if new_df.empty:
        return path, 0

    combined = pd.concat([existing, new_df], ignore_index=True)
    combined = combined.drop_duplicates(subset=["signal_id"], keep="first")
    out_path = save_memory(config, combined)
    return out_path, len(new_df)


def append_signals_from_file(
    config: dict,
    strategy: str,
    signals_file: Path,
    strategy_params: dict | None = None,
    data_map: dict[str, pd.DataFrame] | None = None,
) -> tuple[Path, int]:
    """Record signals from an exported buy_signals CSV."""
    df = pd.read_csv(signals_file, dtype={"symbol": str})
    signals = df.to_dict("records")
    return append_buy_signals(
        config=config,
        strategy=strategy,
        signals=signals,
        strategy_params=strategy_params,
        data_map=data_map,
        source=str(signals_file),
    )

