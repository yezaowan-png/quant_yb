"""Helpers for download failure files."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd


def load_symbols_from_file(path: str | Path) -> list[str]:
    """Read symbols from a failure CSV or a plain text list."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"失败股票文件不存在: {file_path}")

    if file_path.suffix.lower() == ".csv":
        df = pd.read_csv(file_path, dtype=str)
        if "symbol" not in df.columns:
            raise ValueError(f"失败股票 CSV 缺少 symbol 字段: {file_path}")
        values = df["symbol"].dropna().astype(str).tolist()
    else:
        text = file_path.read_text(encoding="utf-8")
        values = []
        for raw in text.replace(",", "\n").splitlines():
            item = raw.strip()
            if item and not item.startswith("#"):
                values.append(item)

    seen = set()
    symbols = []
    for value in values:
        symbol = value.strip().upper()
        if symbol and symbol not in seen:
            seen.add(symbol)
            symbols.append(symbol)
    return symbols


def write_failure_snapshot(
    failure_dir: str | Path,
    failed: dict[str, str],
    start: str,
    end: str,
    stage: str,
    adj: object,
    run_id: str,
) -> Optional[Path]:
    """Write a CSV snapshot for currently failed symbols."""
    if not failed:
        return None
    failure_dir = Path(failure_dir)
    failure_dir.mkdir(parents=True, exist_ok=True)
    run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    path = failure_dir / f"download_failures_{run_id}_{stage}.csv"
    rows = [
        {
            "symbol": sym,
            "start": start,
            "end": end,
            "adj": adj or "raw",
            "stage": stage,
            "error": failed[sym],
            "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        for sym in sorted(failed)
    ]
    pd.DataFrame(rows).to_csv(path, index=False)
    return path
