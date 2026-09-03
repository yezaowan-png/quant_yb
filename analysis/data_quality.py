"""Data quality checks for local stock, index, and daily-basic caches."""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from data.csv_utils import read_csv_tail_records


AUDIT_SCHEMA_VERSION = "market_data_audit_v1"
STOCK_REQUIRED_COLUMNS = {"date", "open", "high", "low", "close", "volume", "amount"}
INDEX_REQUIRED_COLUMNS = {"date", "open", "high", "low", "close"}


def _header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        return next(csv.reader(handle), [])


def _date_key(value: Any) -> str:
    text = str(value or "").strip().replace("-", "").replace("/", "")
    if len(text) >= 8 and text[:8].isdigit():
        return text[:8]
    return ""


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    return number


def _issue(
    severity: str,
    dataset: str,
    symbol: str,
    check: str,
    detail: str,
) -> dict[str, str]:
    return {
        "severity": severity,
        "dataset": dataset,
        "symbol": symbol,
        "check": check,
        "detail": detail,
    }


def _validate_row(
    row: dict[str, Any], dataset: str, symbol: str, issues: list[dict[str, str]]
) -> None:
    row_date = _date_key(row.get("date") or row.get("trade_date")) or "未知日期"
    row_label = f"{row_date} 记录"
    values = {key: _number(row.get(key)) for key in ("open", "high", "low", "close")}
    if any(value is None for value in values.values()):
        issues.append(_issue("critical", dataset, symbol, "ohlc_numeric", f"{row_label} OHLC 存在空值或非数值"))
        return
    open_, high, low, close = (values["open"], values["high"], values["low"], values["close"])
    assert open_ is not None and high is not None and low is not None and close is not None
    if min(open_, high, low, close) <= 0:
        issues.append(_issue("critical", dataset, symbol, "positive_price", f"{row_label}包含非正价格"))
    if high < max(open_, close, low) or low > min(open_, close, high):
        issues.append(_issue("critical", dataset, symbol, "ohlc_bounds", f"{row_label}高低价边界不成立"))
    for field in ("volume", "amount"):
        value = _number(row.get(field))
        if value is not None and value < 0:
            issues.append(_issue("critical", dataset, symbol, f"non_negative_{field}", f"{row_label} {field} 为负数"))


def _deep_records(path: Path) -> Iterable[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        yield from csv.DictReader(handle)


def _profile_price_files(
    paths: list[Path],
    dataset: str,
    required_columns: set[str],
    deep: bool,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    schemas: Counter[tuple[str, ...]] = Counter()
    latest_dates: dict[str, str] = {}
    latest_amounts: dict[str, float] = {}
    valid_files = 0
    row_count = 0

    for path in paths:
        symbol = path.stem.upper()
        try:
            columns = _header(path)
            schemas[tuple(columns)] += 1
            missing = sorted(required_columns.difference(columns))
            if missing:
                issues.append(
                    _issue("critical", dataset, symbol, "required_columns", f"缺少字段: {', '.join(missing)}")
                )
                continue
            rows = list(_deep_records(path)) if deep else read_csv_tail_records(path, 8)
        except (OSError, UnicodeError, csv.Error) as exc:
            issues.append(_issue("critical", dataset, symbol, "readable", f"CSV 读取失败: {exc}"))
            continue
        if not rows:
            issues.append(_issue("critical", dataset, symbol, "non_empty", "CSV 没有数据记录"))
            continue
        if deep:
            row_count += len(rows)
        dates = [_date_key(row.get("date") or row.get("trade_date")) for row in rows]
        valid_dates = [date for date in dates if date]
        if not valid_dates:
            issues.append(_issue("critical", dataset, symbol, "valid_date", "没有可解析的日期"))
            continue
        if any(not date for date in dates):
            issues.append(_issue("critical", dataset, symbol, "valid_date", "存在不可解析日期"))
        if valid_dates != sorted(valid_dates):
            issues.append(_issue("warning", dataset, symbol, "date_order", "日期未按升序排列"))
        if len(valid_dates) != len(set(valid_dates)):
            scope = "全文件" if deep else "末尾 8 行"
            issues.append(_issue("critical", dataset, symbol, "date_unique", f"{scope}存在重复日期"))
        latest_date = max(valid_dates)
        latest_row = max(rows, key=lambda row: _date_key(row.get("date") or row.get("trade_date")))
        latest_dates[symbol] = latest_date
        amount = _number(latest_row.get("amount"))
        if amount is not None:
            latest_amounts[symbol] = amount
        validation_rows = rows if deep else [latest_row]
        for row in validation_rows:
            _validate_row(row, dataset, symbol, issues)
        valid_files += 1

    reference_date = max(latest_dates.values(), default="")
    stale_symbols = sorted(symbol for symbol, date in latest_dates.items() if date != reference_date)
    for symbol in stale_symbols:
        issues.append(
            _issue(
                "warning",
                dataset,
                symbol,
                "freshness",
                f"最新日期 {latest_dates[symbol]}，全体参考日期 {reference_date}",
            )
        )
    latest_count = sum(1 for date in latest_dates.values() if date == reference_date)
    latest_coverage = latest_count / valid_files if valid_files else 0.0
    amount_raw = sum(
        amount for symbol, amount in latest_amounts.items() if latest_dates.get(symbol) == reference_date
    )
    return (
        {
            "file_count": len(paths),
            "valid_file_count": valid_files,
            "row_count": row_count if deep else None,
            "reference_date": reference_date,
            "latest_count": latest_count,
            "latest_coverage": round(latest_coverage, 6),
            "stale_count": len(stale_symbols),
            "stale_symbols": stale_symbols,
            "schema_count": len(schemas),
            "schemas": [
                {"columns": list(columns), "file_count": count}
                for columns, count in schemas.most_common()
            ],
            "latest_amount_raw": round(amount_raw, 2),
            "latest_amount_cny": round(amount_raw * 1000.0, 2),
        },
        issues,
    )


def _profile_daily_basic(paths: list[Path], deep: bool) -> tuple[dict[str, Any], list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    latest_dates: dict[str, str] = {}
    row_count = 0
    for path in paths:
        symbol = path.stem.upper()
        try:
            columns = _header(path)
            if "trade_date" not in columns:
                issues.append(_issue("critical", "daily_basic", symbol, "required_columns", "缺少字段: trade_date"))
                continue
            rows = list(_deep_records(path)) if deep else read_csv_tail_records(path, 8)
        except (OSError, UnicodeError, csv.Error) as exc:
            issues.append(_issue("critical", "daily_basic", symbol, "readable", f"CSV 读取失败: {exc}"))
            continue
        if not rows:
            issues.append(_issue("warning", "daily_basic", symbol, "non_empty", "CSV 没有数据记录"))
            continue
        if deep:
            row_count += len(rows)
        dates = [_date_key(row.get("trade_date")) for row in rows]
        valid_dates = [date for date in dates if date]
        if valid_dates:
            latest_dates[symbol] = max(valid_dates)
        else:
            scope = "全文件" if deep else "末尾记录"
            issues.append(_issue("warning", "daily_basic", symbol, "valid_date", f"{scope}没有可解析日期"))
            continue
        if any(not date for date in dates):
            issues.append(_issue("critical", "daily_basic", symbol, "valid_date", "存在不可解析日期"))
        if valid_dates != sorted(valid_dates):
            issues.append(_issue("warning", "daily_basic", symbol, "date_order", "日期未按升序排列"))
        if len(valid_dates) != len(set(valid_dates)):
            scope = "全文件" if deep else "末尾 8 行"
            issues.append(_issue("critical", "daily_basic", symbol, "date_unique", f"{scope}存在重复日期"))
    reference_date = max(latest_dates.values(), default="")
    latest_count = sum(1 for date in latest_dates.values() if date == reference_date)
    stale_symbols = sorted(symbol for symbol, date in latest_dates.items() if date != reference_date)
    if stale_symbols:
        sample = ", ".join(stale_symbols[:8])
        issues.append(
            _issue(
                "warning",
                "daily_basic",
                "",
                "freshness_coverage",
                f"{len(stale_symbols)} 个指标文件未更新至参考日期 {reference_date}；示例: {sample}",
            )
        )
    return (
        {
            "file_count": len(paths),
            "valid_file_count": len(latest_dates),
            "row_count": row_count if deep else None,
            "reference_date": reference_date,
            "latest_count": latest_count,
            "latest_coverage": round(latest_count / len(latest_dates), 6) if latest_dates else 0.0,
            "stale_count": len(stale_symbols),
        },
        issues,
    )


def _profile_stock_basic(path: Path, cache_symbols: set[str]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    if not path.exists():
        return {"exists": False, "row_count": 0}, [
            _issue("warning", "stock_basic", "", "exists", "stocks.csv 不存在")
        ]
    try:
        frame = pd.read_csv(path, dtype=str, usecols=lambda column: column in {"ts_code", "name", "list_status"})
    except (OSError, ValueError, UnicodeError) as exc:
        return {"exists": True, "row_count": 0}, [
            _issue("critical", "stock_basic", "", "readable", f"stocks.csv 读取失败: {exc}")
        ]
    symbols = frame.get("ts_code", pd.Series(dtype=str)).dropna().astype(str).str.upper()
    duplicate_count = int(symbols.duplicated().sum())
    if duplicate_count:
        issues.append(_issue("critical", "stock_basic", "", "symbol_unique", f"重复代码 {duplicate_count} 条"))
    metadata_symbols = set(symbols.tolist())
    cache_without_metadata = sorted(cache_symbols.difference(metadata_symbols))
    metadata_without_cache = sorted(metadata_symbols.difference(cache_symbols))
    if cache_without_metadata:
        issues.append(
            _issue(
                "warning",
                "stock_basic",
                "",
                "cache_metadata_coverage",
                f"{len(cache_without_metadata)} 个缓存代码不在 stocks.csv；示例: {', '.join(cache_without_metadata[:8])}",
            )
        )
    if metadata_without_cache:
        issues.append(
            _issue(
                "warning",
                "stock_basic",
                "",
                "metadata_cache_coverage",
                f"{len(metadata_without_cache)} 个基础信息代码没有 K 线缓存；可能包含新股、停牌或下载失败标的",
            )
        )
    return (
        {
            "exists": True,
            "row_count": int(len(frame)),
            "duplicate_symbol_count": duplicate_count,
            "cache_without_metadata_count": len(cache_without_metadata),
            "metadata_without_cache_count": len(metadata_without_cache),
        },
        issues,
    )


def audit_market_data(config: dict[str, Any], deep: bool = False) -> dict[str, Any]:
    """Audit local market data at file grain; optionally scan every historical row."""
    cache_dir = Path(config.get("data", {}).get("cache_dir", "data/cache"))
    meta_dir = Path(config.get("data", {}).get("meta_dir") or cache_dir.parent / "meta")
    stock_paths = sorted(path for path in cache_dir.glob("*.csv") if not path.name.startswith("_"))
    index_paths = sorted((cache_dir / "index").glob("*.csv"))
    daily_basic_paths = sorted((meta_dir / "daily_basic").glob("*.csv"))

    stocks, stock_issues = _profile_price_files(
        stock_paths, "stocks", STOCK_REQUIRED_COLUMNS, deep
    )
    indexes, index_issues = _profile_price_files(
        index_paths, "indexes", INDEX_REQUIRED_COLUMNS, deep
    )
    daily_basic, daily_issues = _profile_daily_basic(daily_basic_paths, deep)
    stock_basic, metadata_issues = _profile_stock_basic(
        meta_dir / "stocks.csv", {path.stem.upper() for path in stock_paths}
    )
    issues = stock_issues + index_issues + daily_issues + metadata_issues
    severity_counts = Counter(item["severity"] for item in issues)
    stock_redownload_symbols = sorted(
        {
            item["symbol"]
            for item in issues
            if item["severity"] == "critical" and item["dataset"] == "stocks" and item["symbol"]
        }
    )
    status = "critical" if severity_counts["critical"] else "warning" if severity_counts["warning"] else "healthy"
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "scope": "deep_full_history" if deep else "quick_file_and_tail",
        "status": status,
        "summary": {
            "issue_count": len(issues),
            "critical_count": severity_counts["critical"],
            "warning_count": severity_counts["warning"],
        },
        "datasets": {
            "stocks": stocks,
            "indexes": indexes,
            "daily_basic": daily_basic,
            "stock_basic": stock_basic,
        },
        "remediation": {
            "stock_redownload_symbols": stock_redownload_symbols,
            "stock_redownload_command": (
                "python main.py data download --force --symbol " + ",".join(stock_redownload_symbols)
                if stock_redownload_symbols
                else ""
            ),
        },
        "issues": issues,
        "notes": [
            "quick_file_and_tail 检查全部文件的字段、最新日期和末尾记录，不证明完整历史无重复或无异常；deep_full_history 会逐行检查价格记录及 daily_basic 日期完整性。",
            "停牌、退市和新上市股票可能合理地晚于全体参考日期，freshness 告警需结合标的状态解释。",
            "Tushare 股票 amount 单位按千元换算为人民币；指数缓存存在不同来源字段集合。",
        ],
    }


def save_market_data_audit(
    config: dict[str, Any], result: dict[str, Any], output_dir: str | Path | None = None
) -> tuple[Path, Path]:
    root = Path(output_dir) if output_dir else Path(config.get("output", {}).get("statistics_dir", "output/statistics")) / "data_quality"
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / "market_data_audit.json"
    issues_path = root / "market_data_issues.csv"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(result.get("issues") or [], columns=["severity", "dataset", "symbol", "check", "detail"]).to_csv(
        issues_path, index=False, encoding="utf-8-sig"
    )
    return json_path, issues_path
