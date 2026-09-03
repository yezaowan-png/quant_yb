"""Stock pool helpers backed by a JSON file.

The canonical JSON shape is:

{
  "pools": {
    "机器人": {
      "description": "题材说明",
      "stocks": [
        {"ts_code": "000001.SZ", "name": "平安银行"},
        {"ts_code": "000002.SZ", "name": "万科A"}
      ]
    },
    "AI": ["000002.SZ", "600519.SH"]
  }
}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import pandas as pd


class StockPoolError(ValueError):
    """Raised when a stock pool file or pool selection is invalid."""


def get_stock_pool_path(config: dict) -> Path:
    """Return configured stock pool JSON path."""
    pool_cfg = config.get("stock_pool", {}) or {}
    path = pool_cfg.get("path") or config.get("data", {}).get("stock_pool_path")
    if not path:
        path = "data/stock_pools.json"
    return Path(path)


def split_pool_names(value: str | Iterable[str]) -> list[str]:
    """Split comma separated pool names and keep first occurrence order."""
    if isinstance(value, str):
        raw_names = value.split(",")
    else:
        raw_names = list(value)

    names: list[str] = []
    seen: set[str] = set()
    for raw in raw_names:
        name = str(raw).strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def normalize_symbol(value: object) -> str:
    """Normalize common A-share/ETF code formats to Tushare `000001.SZ` style."""
    symbol = str(value or "").strip().upper()
    if not symbol:
        return ""
    symbol = symbol.replace(" ", "")
    if "." in symbol:
        left, right = symbol.split(".", 1)
        if len(left) == 2 and len(right) == 6:
            return f"{right}.{left}"
        return f"{left}.{right}"
    if len(symbol) >= 8 and symbol[:2] in {"SH", "SZ", "BJ"}:
        return f"{symbol[2:8]}.{symbol[:2]}"
    if len(symbol) >= 7 and symbol[0] in {"0", "1"} and symbol[1:7].isdigit():
        market = "SH" if symbol[0] == "1" else "SZ"
        return f"{symbol[1:7]}.{market}"
    if len(symbol) >= 6 and symbol[:6].isdigit():
        code = symbol[:6]
        if code.startswith(("60", "68", "51", "52", "56", "58")):
            market = "SH"
        elif code.startswith(("00", "30", "15", "16", "18")):
            market = "SZ"
        elif code.startswith(("43", "83", "87", "88", "92")):
            market = "BJ"
        else:
            market = "SZ"
        return f"{code}.{market}"
    return symbol


def normalize_symbols(symbols: Iterable[object]) -> list[str]:
    """Normalize stock symbols and remove duplicates while preserving order."""
    normalized: list[str] = []
    seen: set[str] = set()
    for value in symbols:
        if isinstance(value, dict):
            raw_symbol = (
                value.get("ts_code")
                or value.get("symbol")
                or value.get("code")
                or ""
            )
        else:
            raw_symbol = value
        symbol = normalize_symbol(raw_symbol)
        if symbol and symbol not in seen:
            seen.add(symbol)
            normalized.append(symbol)
    return normalized


def load_stock_pools(path: str | Path) -> dict[str, list[str]]:
    """Load stock pools from JSON.

    Supported shapes:

    - `{pool_name: [symbols...]}`
    - `{pool_name: {"symbols": [symbols...]}}`
    - `{pool_name: {"stocks": [{"ts_code": "...", "name": "..."}]}}`
    - `{"pools": {pool_name: ...}, "meta": {...}}`
    """
    file_path = Path(path)
    if not file_path.exists():
        raise StockPoolError(f"股票池文件不存在: {file_path}")

    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StockPoolError(f"股票池 JSON 格式错误: {file_path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise StockPoolError("股票池 JSON 顶层必须是对象，例如 {\"机器人\": [\"000001.SZ\"]}")

    raw_pools = payload.get("pools") if isinstance(payload.get("pools"), dict) else payload

    pools: dict[str, list[str]] = {}
    for raw_name, raw_value in raw_pools.items():
        name = str(raw_name).strip()
        if not name or name == "meta":
            continue
        if isinstance(raw_value, dict):
            raw_symbols = raw_value.get("stocks", raw_value.get("symbols", []))
        else:
            raw_symbols = raw_value
        if not isinstance(raw_symbols, list):
            raise StockPoolError(f"股票池 {name} 必须是股票代码数组，或包含 symbols/stocks 数组")
        pools[name] = normalize_symbols(raw_symbols)
    return pools


def resolve_pool_symbols(
    config: dict,
    pool_names: str | Iterable[str],
    mode: str = "any",
) -> list[str]:
    """Resolve symbols from one or more pools.

    mode="any" returns the union of selected pools. mode="all" returns the
    intersection, useful for selecting stocks that belong to every theme.
    """
    names = split_pool_names(pool_names)
    if not names:
        raise StockPoolError("请指定至少一个股票池名称")

    if mode not in {"any", "all"}:
        raise StockPoolError("--pool-mode 只支持 any 或 all")

    pools = load_stock_pools(get_stock_pool_path(config))
    missing = [name for name in names if name not in pools]
    if missing:
        available = ", ".join(sorted(pools)) or "无"
        raise StockPoolError(f"股票池不存在: {', '.join(missing)}。可用股票池: {available}")

    selected = [pools[name] for name in names]
    if mode == "any":
        merged: list[str] = []
        seen: set[str] = set()
        for symbols in selected:
            for symbol in symbols:
                if symbol not in seen:
                    seen.add(symbol)
                    merged.append(symbol)
        return merged

    common = set(selected[0])
    for symbols in selected[1:]:
        common &= set(symbols)
    return [symbol for symbol in selected[0] if symbol in common]


def _stock_entry(value: object, name_map: dict[str, str] | None = None) -> dict[str, str]:
    name_map = name_map or {}
    if isinstance(value, dict):
        symbol = normalize_symbol(value.get("ts_code") or value.get("symbol") or value.get("code"))
        name = str(value.get("name") or value.get("股票名称") or name_map.get(symbol, "") or "")
    else:
        symbol = normalize_symbol(value)
        name = name_map.get(symbol, "")
    return {"ts_code": symbol, "name": name}


def _load_payload(path: Path) -> dict:
    if not path.exists():
        return {"meta": {"format_version": 2}, "pools": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StockPoolError(f"股票池 JSON 格式错误: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise StockPoolError("股票池 JSON 顶层必须是对象")
    if "pools" not in payload or not isinstance(payload.get("pools"), dict):
        payload = {"meta": {"format_version": 2}, "pools": payload}
    payload.setdefault("meta", {"format_version": 2})
    payload.setdefault("pools", {})
    return payload


def _load_name_map(config: dict) -> dict[str, str]:
    path = Path(config.get("data", {}).get("meta_dir", "data/meta")) / "stock_names.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype=str)
    if "ts_code" not in df.columns or "name" not in df.columns:
        return {}
    return dict(zip(df["ts_code"].astype(str), df["name"].astype(str)))


def get_stock_pool_entries(config: dict, pool_name: str) -> list[dict[str, str]]:
    """Return stock objects for one pool, preserving names when present."""
    path = get_stock_pool_path(config)
    payload = _load_payload(path)
    pools = payload.get("pools", {})
    if pool_name not in pools:
        raise StockPoolError(f"股票池不存在: {pool_name}")
    raw = pools[pool_name]
    raw_stocks = raw.get("stocks", raw.get("symbols", [])) if isinstance(raw, dict) else raw
    name_map = _load_name_map(config)
    entries = [_stock_entry(item, name_map) for item in raw_stocks if _stock_entry(item, name_map)["ts_code"]]
    seen = set()
    result = []
    for entry in entries:
        if entry["ts_code"] not in seen:
            seen.add(entry["ts_code"])
            result.append(entry)
    return result


def save_stock_pool(
    config: dict,
    pool_name: str,
    stocks: Iterable[object],
    description: str = "",
    merge: bool = False,
) -> Path:
    """Create or update one stock pool in the configured JSON file."""
    name = str(pool_name or "").strip()
    if not name:
        raise StockPoolError("股票池名称不能为空")
    path = get_stock_pool_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _load_payload(path)
    name_map = _load_name_map(config)
    existing = []
    if merge and name in payload["pools"]:
        raw = payload["pools"][name]
        existing = raw.get("stocks", raw.get("symbols", [])) if isinstance(raw, dict) else raw
    entries = [_stock_entry(item, name_map) for item in [*existing, *list(stocks)]]
    deduped: list[dict[str, str]] = []
    seen = set()
    for entry in entries:
        symbol = entry["ts_code"]
        if symbol and symbol not in seen:
            seen.add(symbol)
            deduped.append(entry)
    payload["pools"][name] = {"description": description, "stocks": deduped}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _symbol_name_rows_from_csv(path: str | Path) -> list[dict[str, str]]:
    df = pd.read_csv(path, dtype=str)
    symbol_col = None
    for col in ("ts_code", "symbol", "code", "股票代码"):
        if col in df.columns:
            symbol_col = col
            break
    if symbol_col is None:
        raise StockPoolError("CSV 中未找到股票代码列，支持 ts_code/symbol/code/股票代码")
    name_col = next((col for col in ("name", "股票名称", "名称") if col in df.columns), None)
    rows = []
    for _, row in df.iterrows():
        symbol = normalize_symbol(row.get(symbol_col))
        if not symbol:
            continue
        rows.append({"ts_code": symbol, "name": str(row.get(name_col, "") if name_col else "")})
    return rows


def import_stock_pool(
    config: dict,
    input_path: str | Path,
    pool_name: str,
    source_format: str = "csv",
    source_pool: str | None = None,
    merge: bool = False,
) -> Path:
    """Import a pool from CSV, QTYX trade_pool.json, or TDX blk."""
    fmt = str(source_format).lower()
    path = Path(input_path)
    if fmt == "csv":
        rows = _symbol_name_rows_from_csv(path)
    elif fmt == "qtyx":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise StockPoolError("QTYX 股票池 JSON 顶层必须是对象")
        key = source_pool or next(iter(payload), "")
        raw_pool = payload.get(key, {})
        rows = []
        if isinstance(raw_pool, dict):
            for name, item in raw_pool.items():
                if isinstance(item, dict):
                    code = item.get("code") or item.get("ts_code") or item.get("symbol")
                else:
                    code = item
                rows.append({"ts_code": normalize_symbol(code), "name": str(name)})
        elif isinstance(raw_pool, list):
            rows = [_stock_entry(item) for item in raw_pool]
        else:
            raise StockPoolError(f"无法解析 QTYX 股票池: {key}")
    elif fmt == "blk":
        rows = []
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            text = line.strip()
            if text:
                rows.append({"ts_code": normalize_symbol(text), "name": ""})
    else:
        raise StockPoolError("--format 只支持 csv、qtyx 或 blk")
    return save_stock_pool(config, pool_name, rows, merge=merge)


def export_stock_pool(
    config: dict,
    pool_name: str,
    output_path: str | Path,
    output_format: str = "csv",
) -> Path:
    """Export one stock pool to CSV or Tongdaxin blk."""
    entries = get_stock_pool_entries(config, pool_name)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fmt = str(output_format).lower()
    if fmt == "csv":
        pd.DataFrame(entries).to_csv(path, index=False)
    elif fmt == "blk":
        lines = []
        for entry in entries:
            code, _, market = entry["ts_code"].partition(".")
            prefix = "1" if market == "SH" else "0"
            lines.append(f"{prefix}{code}")
        path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    else:
        raise StockPoolError("--format 只支持 csv 或 blk")
    return path


def save_pool_from_result_csv(
    config: dict,
    result_path: str | Path,
    pool_name: str,
    description: str = "",
    merge: bool = False,
) -> Path:
    """Create/update a stock pool from a scanner/backtest result CSV."""
    rows = _symbol_name_rows_from_csv(result_path)
    return save_stock_pool(config, pool_name, rows, description=description, merge=merge)
