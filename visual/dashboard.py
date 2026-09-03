"""Project dashboard report for navigating indexes and strategy summaries."""

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from analysis.analyzer import _STRATEGY_LABELS, compute_stats
from data.csv_utils import read_csv_tail_records
from visual.components import html_document, inline_script, json_script_data, script_src, stock_link_html, stock_report_href
from visual.industry_market_report import generate_concept_market_report, generate_industry_market_report
from visual.market_structure_brief import generate_market_structure_brief


INDEX_FALLBACKS = {
    "000001.SH": "上证指数",
    "399001.SZ": "深证成指",
    "399006.SZ": "创业板指",
    "000688.SH": "科创50",
    "000300.SH": "沪深300",
    "000905.SH": "中证500",
    "000852.SH": "中证1000",
    "000985.SH": "中证全指",
}

STOCK_SELECTOR_COLUMNS = {
    "symbol": "股票代码",
    "name": "股票简称",
    "industry_l1": "一级行业",
    "industry_l2": "二级行业",
    "industry_l3": "三级行业",
    "industry_board": "行业板块",
    "concept_board": "概念板块",
    "price": "最新价",
    "pct_chg": "最新涨跌幅",
}

STOCK_SELECTOR_MARKET_CAP_COLUMNS = (
    "总市值",
    "市值",
    "最新总市值",
    "total_mv",
    "market_cap",
    "总市值(万元)",
    "总市值(元)",
)


def _ensure_echarts_asset(reports_dir: Path) -> None:
    source = Path(__file__).parent / "assets" / "echarts.min.js"
    if not source.exists():
        return
    target = reports_dir / "assets" / "echarts.min.js"
    if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())


def _dashboard_echarts_tag() -> str:
    return script_src("assets/echarts.min.js")


def _stock_kline_echarts_tag() -> str:
    return script_src("../assets/echarts.min.js")


def _fmt_pct(value: Any, digits: int = 2) -> str:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "--"
    return f"{num:+.{digits}f}%"


def _fmt_num(value: Any, digits: int = 2) -> str:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "--"
    return f"{num:,.{digits}f}"


def _fmt_tushare_amount(value: Any, digits: int = 0) -> str:
    """Format Tushare amount fields from 千元 to reader-facing CNY."""
    number = _round_or_none(value, 4)
    if number is None:
        return "--"
    yi = number / 100000.0
    if abs(yi) >= 10000:
        return f"{yi / 10000.0:,.2f}万亿"
    return f"{yi:,.{digits}f}亿"


def _fmt_multiple(value: Any, digits: int = 2) -> str:
    number = _round_or_none(value, digits)
    if number is None:
        return "--"
    return f"{number:.{digits}f}x"


def _fmt_ratio_pct(value: Any, digits: int = 1) -> str:
    number = _round_or_none(value, 5)
    if number is None:
        return "--"
    return f"{number * 100:.{digits}f}%"


def _rel(from_path: Path, target: Path) -> str:
    try:
        return target.resolve().relative_to(from_path.parent.resolve()).as_posix()
    except ValueError:
        import os

        return Path(os.path.relpath(target.resolve(), from_path.parent.resolve())).as_posix()


def _read_index_snapshot(cache_path: Path) -> dict[str, Any]:
    if not cache_path.exists():
        return {}
    try:
        df = pd.read_csv(cache_path)
    except Exception:
        return {}
    if df.empty:
        return {}
    row = df.sort_values("date").iloc[-1]
    return {
        "date": str(row.get("date", "")),
        "close": _fmt_num(row.get("close")),
        "pct_chg": _fmt_pct(row.get("pct_chg")),
        "amount": _fmt_tushare_amount(row.get("amount")),
    }


def _read_index_chart(cache_path: Path, limit: int = 520) -> dict[str, Any]:
    if not cache_path.exists():
        return {}
    try:
        df = pd.read_csv(cache_path)
    except Exception:
        return {}
    required = {"date", "open", "high", "low", "close"}
    if df.empty or not required.issubset(df.columns):
        return {}
    work = df.sort_values("date").tail(limit).copy()
    for column in ("open", "high", "low", "close", "amount", "volume"):
        if column in work.columns:
            work[column] = pd.to_numeric(work[column], errors="coerce")

    def _round(value: Any, digits: int = 4) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if pd.isna(number):
            return None
        return round(number, digits)

    amount = work["amount"] if "amount" in work.columns else (
        work["close"] * work["volume"] if "volume" in work.columns else pd.Series([pd.NA] * len(work))
    )
    return {
        "dates": [str(item) for item in work["date"].tolist()],
        "ohlc": [
            [_round(row.open), _round(row.close), _round(row.low), _round(row.high)]
            for row in work.itertuples()
        ],
        "amount": [_round(value, 0) for value in amount.tolist()],
    }


def _stock_selector_config(config: dict) -> dict[str, Any]:
    raw = (
        (config.get("dashboard", {}) or {}).get("stock_selector")
        or config.get("stock_selector")
        or {}
    )
    if isinstance(raw, (str, Path)):
        raw = {"csv_path": str(raw)}
    if not isinstance(raw, dict):
        raw = {}
    return {
        "csv_path": str(raw.get("csv_path") or raw.get("path") or "").strip(),
        "enabled": bool(raw.get("enabled", True)),
        "generate_kline_pages": bool(raw.get("generate_kline_pages", False)),
        "kline_bars": max(0, int(raw.get("kline_bars", 0) or 0)),
        "limit": int(raw.get("limit", 0) or 0),
        "custom_boards_path": str(raw.get("custom_boards_path") or "").strip(),
    }


def _split_board(value: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for part in str(value or "").replace("，", "|").replace(",", "|").split("|"):
        item = part.strip()
        if item and item.lower() != "nan" and item not in seen:
            result.append(item)
            seen.add(item)
    return result


def _safe_cell(row: pd.Series, column: str) -> str:
    if column not in row:
        return ""
    value = row.get(column)
    if pd.isna(value):
        return ""
    return str(value).strip()


def _round_or_none(value: Any, digits: int = 3) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    return round(number, digits)


def _first_numeric_cell(row: pd.Series, columns: tuple[str, ...], digits: int = 3) -> float | None:
    for column in columns:
        value = _round_or_none(_safe_cell(row, column), digits)
        if value is not None:
            return value
    return None


def _read_stock_selector_daily_basic_metrics(daily_basic_path: Path) -> dict[str, float | None]:
    if not daily_basic_path.exists():
        return {"market_cap": None}
    try:
        rows = read_csv_tail_records(daily_basic_path, 8)
    except Exception:
        return {"market_cap": None}
    if not rows:
        return {"market_cap": None}
    rows.sort(key=lambda row: str(row.get("trade_date") or ""))
    for column in ("total_mv", "market_cap", "circ_mv", "float_mv"):
        values = [
            value
            for value in (_round_or_none(row.get(column), 3) for row in rows)
            if value is not None
        ]
        if values:
            return {"market_cap": values[-1]}
    return {"market_cap": None}


def _fmt_market_cap_value(value: Any) -> str:
    """Format Tushare daily_basic market cap values, whose unit is 10k CNY."""
    number = _round_or_none(value, 4)
    if number is None:
        return "--"
    yi = number / 10000.0
    if abs(yi) >= 1000:
        return f"{yi:,.0f}亿"
    if abs(yi) >= 100:
        return f"{yi:,.1f}亿"
    return f"{yi:,.2f}亿"


def _fmt_ratio_value(value: Any, digits: int = 2) -> str:
    number = _round_or_none(value, digits + 2)
    if number is None:
        return "--"
    return f"{number:.{digits}f}"


def _read_stock_kline_basic_info(config: dict, symbol: str) -> dict[str, Any]:
    code = str(symbol or "").strip().upper()
    cache_dir = Path(config.get("data", {}).get("cache_dir", "data/cache"))
    meta_dir = Path(config.get("data", {}).get("meta_dir") or (cache_dir.parent / "meta"))
    basic: dict[str, Any] = {}
    stocks_path = meta_dir / "stocks.csv"
    if stocks_path.exists():
        try:
            stocks = pd.read_csv(stocks_path, dtype=str).fillna("")
            if "ts_code" in stocks.columns:
                matched = stocks.loc[stocks["ts_code"].astype(str).str.upper() == code]
                if not matched.empty:
                    row = matched.iloc[-1]
                    basic.update(
                        {
                            "area": str(row.get("area", "")),
                            "industry": str(row.get("industry", "")),
                            "market": str(row.get("market", "")),
                            "exchange": str(row.get("exchange", "")),
                            "list_date": str(row.get("list_date", "")),
                        }
                    )
        except Exception:
            basic = {}

    daily_path = meta_dir / "daily_basic" / f"{code}.csv"
    if daily_path.exists():
        try:
            daily = pd.read_csv(daily_path, dtype={"ts_code": str, "trade_date": str})
        except Exception:
            daily = pd.DataFrame()
        if not daily.empty:
            work = daily.copy()
            if "trade_date" in work.columns:
                work = work.sort_values("trade_date")
            latest = work.iloc[-1]
            basic.update(
                {
                    "basic_date": str(latest.get("trade_date", "")),
                    "total_mv": _round_or_none(latest.get("total_mv"), 3),
                    "circ_mv": _round_or_none(latest.get("circ_mv"), 3),
                    "pe": _round_or_none(latest.get("pe"), 3),
                    "pe_ttm": _round_or_none(latest.get("pe_ttm"), 3),
                    "pb": _round_or_none(latest.get("pb"), 3),
                    "turnover_rate": _round_or_none(latest.get("turnover_rate"), 4),
                    "turnover_rate_f": _round_or_none(latest.get("turnover_rate_f"), 4),
                }
            )
    basic["total_mv_text"] = _fmt_market_cap_value(basic.get("total_mv"))
    basic["circ_mv_text"] = _fmt_market_cap_value(basic.get("circ_mv"))
    basic["pe_text"] = _fmt_ratio_value(basic.get("pe"))
    basic["pe_ttm_text"] = _fmt_ratio_value(basic.get("pe_ttm"))
    basic["pb_text"] = _fmt_ratio_value(basic.get("pb"))
    basic["turnover_rate_text"] = (
        f"{_fmt_ratio_value(basic.get('turnover_rate'))}%" if basic.get("turnover_rate") is not None else "--"
    )
    return basic


def _stock_kline_daily_basic_by_date(config: dict, symbol: str) -> dict[str, dict[str, Any]]:
    code = str(symbol or "").strip().upper()
    cache_dir = Path(config.get("data", {}).get("cache_dir", "data/cache"))
    meta_dir = Path(config.get("data", {}).get("meta_dir") or (cache_dir.parent / "meta"))
    path = meta_dir / "daily_basic" / f"{code}.csv"
    if not path.exists():
        return {}
    try:
        frame = pd.read_csv(
            path,
            dtype={"ts_code": str, "trade_date": str},
            usecols=lambda column: column in {"trade_date", "turnover_rate", "turnover_rate_f", "pe", "pe_ttm", "pb", "total_mv", "circ_mv"},
        )
    except Exception:
        return {}
    if frame.empty or "trade_date" not in frame.columns:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for _, row in frame.iterrows():
        date = pd.to_datetime(str(row.get("trade_date", "")), errors="coerce")
        if pd.isna(date):
            continue
        result[date.strftime("%Y-%m-%d")] = {
            "turnover_rate": _round_or_none(row.get("turnover_rate"), 4),
            "turnover_rate_f": _round_or_none(row.get("turnover_rate_f"), 4),
            "pe": _round_or_none(row.get("pe"), 3),
            "pe_ttm": _round_or_none(row.get("pe_ttm"), 3),
            "pb": _round_or_none(row.get("pb"), 3),
            "total_mv": _round_or_none(row.get("total_mv"), 3),
            "circ_mv": _round_or_none(row.get("circ_mv"), 3),
        }
    return result


def _read_stock_selector_cache_metrics(cache_path: Path) -> dict[str, float | None]:
    if not cache_path.exists():
        return {"price": None, "pct_chg": None, "pct_5d": None, "date": None}
    try:
        rows = read_csv_tail_records(cache_path, 8)
    except Exception:
        return {"price": None, "pct_chg": None, "pct_5d": None, "date": None}
    if not rows:
        return {"price": None, "pct_chg": None, "pct_5d": None, "date": None}
    rows.sort(key=lambda row: str(row.get("date") or ""))
    price: float | None = None
    pct_chg: float | None = None
    pct_5d: float | None = None
    date = str(rows[-1].get("date") or "") or None
    close = [
        value
        for value in (_round_or_none(row.get("close"), 8) for row in rows)
        if value is not None
    ]
    if close:
        price = round(close[-1], 3)
    if len(close) >= 2 and close[-2]:
        pct_chg = round((close[-1] / close[-2] - 1.0) * 100.0, 3)
    if len(close) >= 6 and close[-6]:
        pct_5d = round((close[-1] / close[-6] - 1.0) * 100.0, 3)
    return {"price": price, "pct_chg": pct_chg, "pct_5d": pct_5d, "date": date}


def _normalize_custom_board_symbols(value: Any) -> list[str]:
    symbols: list[str] = []
    seen: set[str] = set()
    if isinstance(value, dict):
        value = value.get("stocks") or value.get("symbols") or []
    if not isinstance(value, list):
        return symbols
    for item in value:
        if isinstance(item, dict):
            symbol = str(item.get("symbol") or item.get("ts_code") or item.get("code") or "").strip().upper()
        else:
            symbol = str(item or "").strip().upper()
        if symbol and symbol not in seen:
            symbols.append(symbol)
            seen.add(symbol)
    return symbols


def _read_stock_selector_custom_boards(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "boards": {}, "error": ""}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"path": str(path), "exists": True, "boards": {}, "error": f"自定义板块 JSON 读取失败: {exc}"}
    source = payload.get("boards") if isinstance(payload, dict) and isinstance(payload.get("boards"), dict) else payload
    boards: dict[str, list[str]] = {}
    if isinstance(source, dict):
        for name, value in source.items():
            board_name = str(name or "").strip()
            if not board_name:
                continue
            boards[board_name] = _normalize_custom_board_symbols(value)
    return {"path": str(path), "exists": True, "boards": boards, "error": ""}


def _normalize_stock_kline_frame(cache_path: Path) -> pd.DataFrame:
    if not cache_path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(cache_path)
    except Exception:
        return pd.DataFrame()
    required = {"date", "open", "high", "low", "close"}
    if df.empty or not required.issubset(df.columns):
        return pd.DataFrame()
    work = df.copy()
    work["date"] = pd.to_datetime(work["date"].astype(str), errors="coerce")
    for column in ("open", "high", "low", "close", "volume", "vol", "amount"):
        if column in work.columns:
            work[column] = pd.to_numeric(work[column], errors="coerce")
    if "volume" not in work.columns and "vol" in work.columns:
        work["volume"] = work["vol"]
    if "volume" not in work.columns:
        work["volume"] = 0.0
    if "amount" not in work.columns:
        work["amount"] = work["close"] * work["volume"]
    return (
        work.dropna(subset=["date", "open", "high", "low", "close"])
        .sort_values("date")
        .reset_index(drop=True)
    )


def _resample_stock_kline(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if df.empty:
        return df
    indexed = df.copy()
    indexed["_period_date"] = indexed["date"]
    indexed = indexed.set_index("date")
    result = indexed.resample(rule).agg(
        {
            "_period_date": "last",
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
            "amount": "sum",
        }
    )
    result = result.dropna(subset=["open", "high", "low", "close", "_period_date"]).reset_index(drop=True)
    result["date"] = pd.to_datetime(result.pop("_period_date"), errors="coerce")
    return result.dropna(subset=["date"]).reset_index(drop=True)


def _stock_indicator_payload(
    work: pd.DataFrame,
    limit: int = 0,
    daily_basic_by_date: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if work.empty:
        return {}
    bar_limit = int(limit or 0)
    if bar_limit > 0:
        data = work.tail(max(30, bar_limit)).copy().reset_index(drop=True)
    else:
        data = work.copy().reset_index(drop=True)
    close = pd.to_numeric(data["close"], errors="coerce")
    high = pd.to_numeric(data["high"], errors="coerce")
    low = pd.to_numeric(data["low"], errors="coerce")
    volume = pd.to_numeric(data.get("volume", pd.Series([pd.NA] * len(data))), errors="coerce")
    amount = pd.to_numeric(data.get("amount", close * volume), errors="coerce")
    pct_chg = close.pct_change() * 100.0
    basic_map = daily_basic_by_date or {}
    period_turnover: list[float | None] = []
    period_turnover_f: list[float | None] = []
    period_pe: list[float | None] = []
    period_pe_ttm: list[float | None] = []
    for item in data["date"].tolist():
        date_key = pd.Timestamp(item).strftime("%Y-%m-%d")
        basic = basic_map.get(date_key, {})
        period_turnover.append(_round_or_none(basic.get("turnover_rate"), 4))
        period_turnover_f.append(_round_or_none(basic.get("turnover_rate_f"), 4))
        period_pe.append(_round_or_none(basic.get("pe"), 3))
        period_pe_ttm.append(_round_or_none(basic.get("pe_ttm"), 3))

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    macd = (dif - dea) * 2

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rsi = 100 - 100 / (1 + gain / loss.replace(0, float("nan")))

    low9 = low.rolling(9).min()
    high9 = high.rolling(9).max()
    rsv = (close - low9) / (high9 - low9).replace(0, float("nan")) * 100
    k = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    d = k.ewm(alpha=1 / 3, adjust=False).mean()
    j = 3 * k - 2 * d

    return {
        "dates": [item.strftime("%Y-%m-%d") for item in data["date"].tolist()],
        "ohlc": [
            [_round_or_none(row.open), _round_or_none(row.close), _round_or_none(row.low), _round_or_none(row.high)]
            for row in data.itertuples()
        ],
        "ma5": [_round_or_none(v) for v in close.rolling(5).mean().tolist()],
        "ma10": [_round_or_none(v) for v in close.rolling(10).mean().tolist()],
        "ma20": [_round_or_none(v) for v in close.rolling(20).mean().tolist()],
        "ma60": [_round_or_none(v) for v in close.rolling(60).mean().tolist()],
        "volume": [_round_or_none(v, 0) for v in volume.tolist()],
        "amount": [_round_or_none(v, 0) for v in amount.tolist()],
        "pct_chg": [_round_or_none(v, 3) for v in pct_chg.tolist()],
        "turnover_rate": period_turnover,
        "turnover_rate_f": period_turnover_f,
        "pe": period_pe,
        "pe_ttm": period_pe_ttm,
        "macd_dif": [_round_or_none(v, 4) for v in dif.tolist()],
        "macd_dea": [_round_or_none(v, 4) for v in dea.tolist()],
        "macd_hist": [_round_or_none(v, 4) for v in macd.tolist()],
        "rsi": [_round_or_none(v, 3) for v in rsi.tolist()],
        "kdj_k": [_round_or_none(v, 3) for v in k.tolist()],
        "kdj_d": [_round_or_none(v, 3) for v in d.tolist()],
        "kdj_j": [_round_or_none(v, 3) for v in j.tolist()],
    }


def _read_stock_kline_payload(
    cache_path: Path,
    limit: int = 0,
    daily_basic_by_date: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    base = _normalize_stock_kline_frame(cache_path)
    if base.empty:
        return {}
    bar_limit = max(0, int(limit or 0))
    payload = {
        "periods": {
            "day": _stock_indicator_payload(base, bar_limit, daily_basic_by_date),
            "week": _stock_indicator_payload(_resample_stock_kline(base, "W-FRI"), bar_limit),
            "month": _stock_indicator_payload(_resample_stock_kline(base, "ME"), bar_limit),
        },
        "default_period": "day",
        "default_indicator": "",
    }
    if not payload["periods"]["day"]:
        return {}
    return payload


def _build_light_stock_kline_html(
    stock: dict[str, Any],
    payload: dict[str, Any],
    dashboard_href: str,
    back_label: str = "返回 Dashboard",
) -> str:
    title = f"{stock.get('name') or stock.get('symbol')} {stock.get('symbol')} · K线图"
    basic = stock.get("basic") if isinstance(stock.get("basic"), dict) else {}

    def info_item(label: str, value: Any) -> str:
        text = str(value or "--")
        return f'<div><span>{html.escape(label)}</span><strong>{html.escape(text)}</strong></div>'

    basic_html = "".join(
        [
            info_item("总市值", basic.get("total_mv_text")),
            info_item("流通市值", basic.get("circ_mv_text")),
            info_item("PE", basic.get("pe_text")),
            info_item("PE(TTM)", basic.get("pe_ttm_text")),
            info_item("PB", basic.get("pb_text")),
            info_item("换手率", basic.get("turnover_rate_text")),
        ]
    )
    secondary_meta = " · ".join(
        item
        for item in [
            str(basic.get("area") or "").strip(),
            str(basic.get("market") or "").strip(),
            f"上市 {str(basic.get('list_date') or '').strip()}" if basic.get("list_date") else "",
            f"基本面截至 {str(basic.get('basic_date') or '').strip()}" if basic.get("basic_date") else "",
        ]
        if item
    )
    return html_document(
        title=title,
        styles="""
    :root { --ink:#202631; --muted:#657084; --line:#dbe3ef; --paper:#eef2f4; --panel:#fff; --soft:#f7f9fc; --red:#c84545; --green:#15805d; --blue:#2d6cdf; --dark:#1f2937; }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--paper); color:var(--ink); font-family:"Microsoft YaHei","Noto Sans SC","PingFang SC",sans-serif; }
    button { font-family:inherit; }
    .page { width:min(1880px, calc(100vw - 28px)); margin:0 auto; padding:18px 0 28px; }
    .head { display:flex; justify-content:space-between; gap:14px; align-items:flex-start; background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:16px 18px; margin-bottom:12px; }
    .head-main { min-width:0; flex:1 1 auto; }
    h1 { margin:0; font-size:24px; line-height:1.2; }
    .meta { margin-top:6px; color:var(--muted); font-size:13px; }
    .basic-grid { display:grid; grid-template-columns:repeat(6, minmax(92px, 1fr)); gap:8px; margin-top:12px; max-width:860px; }
    .basic-grid div { border:1px solid #e2e8f0; background:#f8fafc; border-radius:8px; padding:8px 10px; min-width:0; }
    .basic-grid span { display:block; color:var(--muted); font-size:11px; font-weight:800; line-height:1.2; }
    .basic-grid strong { display:block; color:var(--ink); font-size:15px; line-height:1.25; margin-top:3px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    .back { display:inline-flex; min-height:34px; align-items:center; border:1px solid var(--line); border-radius:8px; padding:0 12px; color:var(--blue); font-weight:900; text-decoration:none; background:#f7f9fc; }
    .toolbar { display:flex; flex-wrap:wrap; gap:10px; align-items:center; justify-content:space-between; background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:12px 14px; margin-bottom:12px; }
    .tool-group { display:flex; flex-wrap:wrap; gap:7px; align-items:center; }
    .tool-label { color:var(--muted); font-size:12px; font-weight:900; margin-right:2px; }
    .tool-btn { min-height:30px; border:1px solid var(--line); border-radius:999px; background:var(--soft); color:var(--ink); padding:0 11px; font-size:12px; font-weight:900; cursor:pointer; }
    .tool-btn.active { color:#fff; background:var(--blue); border-color:#245ac0; }
    .tool-btn.danger { color:#9f1239; }
    .hint { color:var(--muted); font-size:12px; }
    .chart-card { position:relative; background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:14px; }
    .chart-wrap { position:relative; width:100%; height:min(82vh, 900px); min-height:720px; }
    #stock-kline-chart { position:absolute; inset:0; width:100%; height:100%; }
    #manual-drawing-layer { position:absolute; inset:0; width:100%; height:100%; pointer-events:none; z-index:5; overflow:visible; }
    #manual-drawing-layer.active { pointer-events:auto; cursor:crosshair; }
    .manual-line { pointer-events:stroke; cursor:move; }
    .manual-handle { pointer-events:all; cursor:grab; }
    .manual-handle:active { cursor:grabbing; }
    .manual-label { pointer-events:none; font-size:12px; font-weight:900; paint-order:stroke; stroke:#fff; stroke-width:3px; }
    .note { margin-top:10px; color:var(--muted); font-size:12px; }
    @media (max-width: 900px) {
      .head { flex-direction:column; }
      .basic-grid { grid-template-columns:repeat(2, minmax(0, 1fr)); max-width:none; }
    }
        """,
        body=f"""
    <main class="page">
      <header class="head">
        <div class="head-main">
          <h1>{html.escape(str(stock.get("name") or "--"))} <span>{html.escape(str(stock.get("symbol") or ""))}</span></h1>
          <div class="meta">{html.escape(str(stock.get("industry") or "--"))} · 日/周/月 K / MA5/10/20/60 / 成交量 / 成交额 / MACD / RSI / KDJ / 手动画线</div>
          <div class="meta">{html.escape(secondary_meta or "基本信息来自本地 stock_basic / daily_basic 缓存")}</div>
          <div class="basic-grid">{basic_html}</div>
        </div>
        <a class="back" href="{html.escape(dashboard_href, quote=True)}">{html.escape(back_label)}</a>
      </header>
      <section class="toolbar">
        <div class="tool-group" id="period-tools">
          <span class="tool-label">周期</span>
          <button type="button" class="tool-btn active" data-period="day">日K</button>
          <button type="button" class="tool-btn" data-period="week">周K</button>
          <button type="button" class="tool-btn" data-period="month">月K</button>
        </div>
        <div class="tool-group" id="indicator-tools">
          <span class="tool-label">副图</span>
          <button type="button" class="tool-btn" data-indicator="macd">MACD</button>
          <button type="button" class="tool-btn" data-indicator="rsi">RSI</button>
          <button type="button" class="tool-btn" data-indicator="kdj">KDJ</button>
          <button type="button" class="tool-btn active" data-indicator="">隐藏指标</button>
        </div>
        <div class="tool-group" id="drawing-tools">
          <span class="tool-label">画线</span>
          <button type="button" class="tool-btn" data-draw="trend">趋势线</button>
          <button type="button" class="tool-btn" data-draw="support">支撑线</button>
          <button type="button" class="tool-btn" data-draw="resistance">阻力线</button>
          <button type="button" class="tool-btn" data-draw="select">选择/调整</button>
          <button type="button" class="tool-btn" id="drawing-undo">撤销</button>
          <button type="button" class="tool-btn danger" id="drawing-clear">清空本周期</button>
        </div>
        <div class="hint" id="drawing-hint">点击“趋势线”后在主图点两个位置；支撑/阻力点一次。画好后可拖动端点或水平线上下调整。</div>
      </section>
      <section class="chart-card">
        <div class="chart-wrap">
          <div id="stock-kline-chart"></div>
          <svg id="manual-drawing-layer"></svg>
        </div>
      </section>
      <div class="note">数据来源：本地股票日线缓存；成交额无原始 amount 字段时使用 Close × Volume 估算。手动画线保存在当前浏览器本地，只影响本页展示。</div>
    </main>
        """,
        head_extra='<link rel="icon" href="data:,">' + _stock_kline_echarts_tag(),
        scripts=json_script_data({"stock": stock, "chart": payload}, "stock-kline-data")
        + inline_script(
            """
(function(){
  var raw=document.getElementById('stock-kline-data');
  var data=raw?JSON.parse(raw.textContent||'{}'):{};
  var stock=data.stock||{}, chartPayload=data.chart||{}, periods=chartPayload.periods||{};
  var defaultIndicator=chartPayload.default_indicator==='volume'?'':(chartPayload.default_indicator||'');
  var state={period:chartPayload.default_period||'day',indicator:defaultIndicator,drawMode:'select',pending:null,selected:null,drag:null};
  var C={up:'#c84545',down:'#15805d',line:'#dbe3ef',split:'#edf2f7',axis:'#657084',ma:['#5470c6','#b5d81c','#414b7a','#b46f1c'],support:'#16a34a',resistance:'#dc2626',trend:'#2563eb'};
  function fmt(v){var n=Number(v);if(!isFinite(n))return'--';if(Math.abs(n)>=1e8)return(n/1e8).toFixed(2)+'亿';if(Math.abs(n)>=1e4)return(n/1e4).toFixed(0)+'万';return n.toFixed(0);}
  function fmtTushareAmount(v){var n=Number(v);if(!isFinite(n))return'--';var cny=n*1000;if(Math.abs(cny)>=1e12)return(cny/1e12).toFixed(2)+'万亿';if(Math.abs(cny)>=1e8)return(cny/1e8).toFixed(2)+'亿';if(Math.abs(cny)>=1e4)return(cny/1e4).toFixed(0)+'万';return cny.toFixed(0);}
  function pct(v){var n=Number(v);return isFinite(n)?n.toFixed(2):'--';}
  function signedPct(v){if(v==null||v==='')return'--';var n=Number(v);return isFinite(n)?(n>=0?'+':'')+n.toFixed(2)+'%':'--';}
  function pctUnit(v){if(v==null||v==='')return'--';var n=Number(v);return isFinite(n)?n.toFixed(2)+'%':'--';}
  function tip(params){
    var ps=Array.isArray(params)?params:[params], first=ps[0]||{}, i=first.dataIndex||0, c=active(), o=(c.ohlc||[])[i]||[], date=(c.dates||[])[i]||first.axisValue||'';
    var lines=[date,'K线','open&nbsp;&nbsp;&nbsp;&nbsp;'+(o[0]??'--'),'close&nbsp;&nbsp;&nbsp;'+(o[1]??'--'),'lowest&nbsp;&nbsp;'+(o[2]??'--'),'highest&nbsp;'+(o[3]??'--'),'涨幅&nbsp;&nbsp;&nbsp;&nbsp;'+signedPct((c.pct_chg||[])[i]),'换手率&nbsp;&nbsp;'+pctUnit((c.turnover_rate||[])[i])];
    ps.forEach(function(p){
      if(!p||p.seriesName==='K线')return;
      var val=p.value;
      if(val&&typeof val==='object'&&'value' in val)val=val.value;
      if(p.seriesName==='成交量')val=fmt(val);
      if(p.seriesName==='成交额')val=fmtTushareAmount(val);
      lines.push(String(p.marker||'')+p.seriesName+'&nbsp;&nbsp;'+(val==null?'--':val));
    });
    return lines.join('<br/>');
  }
  function active(){return periods[state.period]||periods.day||{};}
  function dates(){return active().dates||[];}
  function storageKey(){return 'quantyb:stock_kline_drawings:'+String(stock.symbol||'')+':'+state.period;}
  function loadLines(){try{return JSON.parse(localStorage.getItem(storageKey())||'[]')||[];}catch(e){return[];}}
  function saveLines(lines){try{localStorage.setItem(storageKey(),JSON.stringify(lines||[]));}catch(e){}}
  function bars(values){var c=active(), ohlc=c.ohlc||[];return(values||[]).map(function(v,i){var o=ohlc[i]||[],open=Number(o[0]),close=Number(o[1]);return{value:v,itemStyle:{color:close>=open?C.up:C.down,opacity:.66}};});}
  var el=document.getElementById('stock-kline-chart');if(!el||typeof echarts==='undefined')return;
  var chart=echarts.init(el,null,{renderer:'canvas'});
  var svg=document.getElementById('manual-drawing-layer');
  function lineColor(type){return type==='support'?C.support:type==='resistance'?C.resistance:C.trend;}
  function px(x,y){return chart.convertToPixel({xAxisIndex:0,yAxisIndex:0},[x,y]);}
  function dataPoint(evt){var r=svg.getBoundingClientRect(), x=evt.clientX-r.left, y=evt.clientY-r.top;var p=chart.convertFromPixel({xAxisIndex:0,yAxisIndex:0},[x,y])||[0,0];var max=Math.max(0,dates().length-1);return{x:Math.max(0,Math.min(max,Math.round(Number(p[0])||0))),y:Number(p[1])||0,px:x,py:y};}
  function addSvg(tag,attrs){var node=document.createElementNS('http://www.w3.org/2000/svg',tag);Object.keys(attrs||{}).forEach(function(k){node.setAttribute(k,attrs[k]);});svg.appendChild(node);return node;}
  function renderDrawings(){
    if(!svg)return;
    svg.innerHTML='';
    var rect=el.getBoundingClientRect();svg.setAttribute('viewBox','0 0 '+rect.width+' '+rect.height);
    var all=loadLines(), max=Math.max(0,dates().length-1);
    all.forEach(function(line,idx){
      if(line.type==='support'||line.type==='resistance'){line.x1=0;line.x2=max;line.y2=line.y1;}
      var p1=px(line.x1,line.y1), p2=px(line.x2,line.y2);
      if(!p1||!p2||!isFinite(p1[0])||!isFinite(p1[1])||!isFinite(p2[0])||!isFinite(p2[1]))return;
      var color=lineColor(line.type), selected=state.selected===line.id;
      var l=addSvg('line',{x1:p1[0],y1:p1[1],x2:p2[0],y2:p2[1],stroke:color,'stroke-width':selected?3:2,'stroke-dasharray':line.type==='trend'?'':'8 4',class:'manual-line','data-id':line.id});
      l.addEventListener('pointerdown',function(e){e.stopPropagation();state.selected=line.id;state.drag={kind:line.type==='trend'?'move':'horizontal',id:line.id,start:dataPoint(e),orig:JSON.parse(JSON.stringify(line))};svg.setPointerCapture(e.pointerId);renderDrawings();});
      addSvg('text',{x:p2[0]+6,y:p2[1]-6,fill:color,class:'manual-label'}).textContent=(line.type==='support'?'支撑':line.type==='resistance'?'阻力':'趋势')+' '+(idx+1);
      [['start',p1],['end',p2]].forEach(function(pair){
        if((line.type==='support'||line.type==='resistance')&&pair[0]==='start')return;
        var h=addSvg('circle',{cx:pair[1][0],cy:pair[1][1],r:selected?6:5,fill:'#fff',stroke:color,'stroke-width':2,class:'manual-handle','data-id':line.id,'data-point':pair[0]});
        h.addEventListener('pointerdown',function(e){e.stopPropagation();state.selected=line.id;state.drag={kind:line.type==='trend'?pair[0]:'horizontal',id:line.id,start:dataPoint(e),orig:JSON.parse(JSON.stringify(line))};svg.setPointerCapture(e.pointerId);renderDrawings();});
      });
    });
  }
  function setLines(lines){saveLines(lines);renderDrawings();}
  function updateDrag(evt){
    if(!state.drag)return;
    var p=dataPoint(evt), all=loadLines(), line=all.find(function(x){return x.id===state.drag.id;});
    if(!line)return;
    if(state.drag.kind==='start'){line.x1=p.x;line.y1=p.y;}
    else if(state.drag.kind==='end'){line.x2=p.x;line.y2=p.y;}
    else if(state.drag.kind==='horizontal'){line.y1=p.y;line.y2=p.y;}
    else if(state.drag.kind==='move'){
      var dx=p.x-state.drag.start.x, dy=p.y-state.drag.start.y, o=state.drag.orig;
      line.x1=Math.max(0,Math.min(dates().length-1,Math.round(o.x1+dx)));
      line.x2=Math.max(0,Math.min(dates().length-1,Math.round(o.x2+dx)));
      line.y1=o.y1+dy;line.y2=o.y2+dy;
    }
    setLines(all);
  }
  function finishDrag(){state.drag=null;}
  function clickDraw(evt){
    if(state.drag||state.drawMode==='select')return;
    var p=dataPoint(evt), all=loadLines(), max=Math.max(0,dates().length-1);
    if(state.drawMode==='support'||state.drawMode==='resistance'){
      all.push({id:String(Date.now())+'_'+Math.random().toString(16).slice(2),type:state.drawMode,x1:0,x2:max,y1:p.y,y2:p.y});
      state.selected=all[all.length-1].id;setLines(all);setDrawMode('select');return;
    }
    if(state.drawMode==='trend'){
      if(!state.pending){state.pending=p;setHint('趋势线：再点第二个位置完成。');return;}
      all.push({id:String(Date.now())+'_'+Math.random().toString(16).slice(2),type:'trend',x1:state.pending.x,y1:state.pending.y,x2:p.x,y2:p.y});
      state.pending=null;state.selected=all[all.length-1].id;setLines(all);setDrawMode('select');
    }
  }
  function setHint(text){var h=document.getElementById('drawing-hint');if(h)h.textContent=text;}
  function setDrawMode(mode){
    state.drawMode=mode;state.pending=null;
    document.querySelectorAll('[data-draw]').forEach(function(b){b.classList.toggle('active',(b.getAttribute('data-draw')||'select')===mode);});
    svg.classList.toggle('active',mode!=='select');
    setHint(mode==='trend'?'趋势线：在主图点两个位置，完成后拖动两端调整。':mode==='support'?'支撑线：在主图点一个价格，之后可上下拖动。':mode==='resistance'?'阻力线：在主图点一个价格，之后可上下拖动。':'选择/调整：拖动线或端点微调；滚轮仍可缩放图表。');
  }
  function indicatorSeries(c){
    if(state.indicator==='macd')return[{name:'DIF',type:'line',xAxisIndex:3,yAxisIndex:3,data:c.macd_dif||[],symbol:'none',lineStyle:{color:C.ma[0]}},{name:'DEA',type:'line',xAxisIndex:3,yAxisIndex:3,data:c.macd_dea||[],symbol:'none',lineStyle:{color:C.ma[3]}},{name:'MACD柱',type:'bar',xAxisIndex:3,yAxisIndex:3,data:(c.macd_hist||[]).map(function(v){return{value:v,itemStyle:{color:Number(v)>=0?C.up:C.down,opacity:.65}};})}];
    if(state.indicator==='rsi')return[{name:'RSI14',type:'line',xAxisIndex:3,yAxisIndex:3,data:c.rsi||[],symbol:'none',lineStyle:{color:'#7c3aed',width:1.5}},{name:'RSI 70',type:'line',xAxisIndex:3,yAxisIndex:3,data:(c.dates||[]).map(function(){return 70;}),symbol:'none',lineStyle:{color:'#ef4444',type:'dashed',opacity:.45}},{name:'RSI 30',type:'line',xAxisIndex:3,yAxisIndex:3,data:(c.dates||[]).map(function(){return 30;}),symbol:'none',lineStyle:{color:'#22c55e',type:'dashed',opacity:.45}}];
    if(state.indicator==='kdj')return[{name:'K',type:'line',xAxisIndex:3,yAxisIndex:3,data:c.kdj_k||[],symbol:'none',lineStyle:{color:C.ma[0]}},{name:'D',type:'line',xAxisIndex:3,yAxisIndex:3,data:c.kdj_d||[],symbol:'none',lineStyle:{color:C.ma[3]}},{name:'J',type:'line',xAxisIndex:3,yAxisIndex:3,data:c.kdj_j||[],symbol:'none',lineStyle:{color:'#ec4899'}}];
    return[];
  }
  function defaultZoomStart(ds){
    if(!ds||!ds.length)return 0;
    var latest=Date.parse(ds[ds.length-1]);
    if(!isFinite(latest)){
      var visible=Math.min(252,Math.max(30,ds.length));
      return Math.max(0,100-visible/ds.length*100);
    }
    var cutoff=latest-365*24*60*60*1000, idx=0;
    for(var i=0;i<ds.length;i++){
      var t=Date.parse(ds[i]);
      if(isFinite(t)&&t>=cutoff){idx=i;break;}
    }
    if(ds.length<=1)return 0;
    return Math.max(0,Math.min(100,idx/(ds.length-1)*100));
  }
  function applyOption(){
    var c=active(), ds=c.dates||[];
    var start=defaultZoomStart(ds);
    var legend=['K线','MA5','MA10','MA20','MA60','成交量','成交额'];
    if(state.indicator==='macd')legend=legend.concat(['DIF','DEA','MACD柱']);
    else if(state.indicator==='rsi')legend=legend.concat(['RSI14','RSI 70','RSI 30']);
    else if(state.indicator==='kdj')legend=legend.concat(['K','D','J']);
    var hasIndicator=!!state.indicator, xAxisIndexes=hasIndicator?[0,1,2,3]:[0,1,2];
    var grids=hasIndicator?[{left:62,right:34,top:48,height:'50%'},{left:62,right:34,top:'64%',height:'9%'},{left:62,right:34,top:'76%',height:'9%'},{left:62,right:34,top:'88%',height:'8%'}]:[{left:62,right:34,top:48,height:'58%'},{left:62,right:34,top:'70%',height:'11%'},{left:62,right:34,top:'84%',height:'10%'}];
    var xAxes=[{type:'category',data:ds,axisLabel:{color:C.axis},axisPointer:{show:true},axisLine:{lineStyle:{color:C.line}},splitLine:{show:true,lineStyle:{type:'dashed',color:C.split}}},{type:'category',gridIndex:1,data:ds,axisLabel:{show:false},axisPointer:{show:true},axisLine:{lineStyle:{color:C.line}}},{type:'category',gridIndex:2,data:ds,axisLabel:{color:C.axis,rotate:22},axisPointer:{show:true},axisLine:{lineStyle:{color:C.line}}}];
    var yAxes=[{scale:true,axisLabel:{color:C.axis},splitLine:{show:true,lineStyle:{type:'dashed',color:C.split}}},{gridIndex:1,scale:true,name:'成交量',axisLabel:{color:C.axis,formatter:fmt},splitLine:{show:true,lineStyle:{type:'dashed',color:C.split}}},{gridIndex:2,scale:true,name:'成交额',axisLabel:{color:C.axis,formatter:fmtTushareAmount},splitLine:{show:true,lineStyle:{type:'dashed',color:C.split}}}];
    if(hasIndicator){
      xAxes.push({type:'category',gridIndex:3,data:ds,axisLabel:{color:C.axis,rotate:22},axisPointer:{show:true},axisLine:{lineStyle:{color:C.line}}});
      yAxes.push({gridIndex:3,scale:true,name:state.indicator.toUpperCase(),axisLabel:{color:C.axis,formatter:function(v){return pct(v);}},splitLine:{show:true,lineStyle:{type:'dashed',color:C.split}}});
    }
    chart.setOption({animation:false,tooltip:{trigger:'axis',axisPointer:{type:'cross'},formatter:tip},axisPointer:{link:[{xAxisIndex:'all'}],label:{backgroundColor:'#64748b'}},legend:{top:4,left:'center',data:legend},grid:grids,xAxis:xAxes,yAxis:yAxes,dataZoom:[{type:'inside',xAxisIndex:xAxisIndexes,start:start,end:100,zoomOnMouseWheel:true,moveOnMouseMove:true,moveOnMouseWheel:false},{type:'slider',xAxisIndex:xAxisIndexes,height:22,bottom:4,start:start,end:100}],series:[{name:'K线',type:'candlestick',data:c.ohlc||[],itemStyle:{color:C.up,color0:C.down,borderColor:C.up,borderColor0:C.down}},{name:'MA5',type:'line',data:c.ma5||[],symbol:'none',smooth:true,lineStyle:{color:C.ma[0],width:1.5}},{name:'MA10',type:'line',data:c.ma10||[],symbol:'none',smooth:true,lineStyle:{color:C.ma[1],width:1.5}},{name:'MA20',type:'line',data:c.ma20||[],symbol:'none',smooth:true,lineStyle:{color:C.ma[2],width:1.5}},{name:'MA60',type:'line',data:c.ma60||[],symbol:'none',smooth:true,lineStyle:{color:C.ma[3],width:1.7}},{name:'成交量',type:'bar',xAxisIndex:1,yAxisIndex:1,data:bars(c.volume)},{name:'成交额',type:'bar',xAxisIndex:2,yAxisIndex:2,data:bars(c.amount)}].concat(indicatorSeries(c))},true);
    setTimeout(renderDrawings,0);
  }
  document.querySelectorAll('[data-period]').forEach(function(btn){btn.addEventListener('click',function(){state.period=btn.getAttribute('data-period')||'day';state.selected=null;state.pending=null;document.querySelectorAll('[data-period]').forEach(function(b){b.classList.toggle('active',b===btn);});applyOption();});});
  document.querySelectorAll('[data-indicator]').forEach(function(btn){btn.addEventListener('click',function(){state.indicator=btn.getAttribute('data-indicator')||'';document.querySelectorAll('[data-indicator]').forEach(function(b){b.classList.toggle('active',b===btn);});applyOption();});});
  document.querySelectorAll('[data-draw]').forEach(function(btn){btn.addEventListener('click',function(){setDrawMode(btn.getAttribute('data-draw')||'select');});});
  document.getElementById('drawing-undo')&&document.getElementById('drawing-undo').addEventListener('click',function(){var all=loadLines();all.pop();setLines(all);});
  document.getElementById('drawing-clear')&&document.getElementById('drawing-clear').addEventListener('click',function(){if(confirm('清空当前周期的手动画线？'))setLines([]);});
  svg.addEventListener('pointerdown',clickDraw);
  svg.addEventListener('pointermove',updateDrag);
  svg.addEventListener('pointerup',finishDrag);
  svg.addEventListener('pointercancel',finishDrag);
  chart.on('dataZoom',function(){setTimeout(renderDrawings,0);});
  chart.on('finished',renderDrawings);
  window.addEventListener('resize',function(){chart.resize();setTimeout(renderDrawings,0);});
  applyOption();
})();
            """
        ),
    )


def _ensure_light_stock_kline_page(
    config: dict,
    output_path: Path,
    stock: dict[str, Any],
    cache_path: Path,
    source_mtime: float,
    bars: int,
) -> tuple[bool, str]:
    reports_dir = Path(config["output"]["reports_dir"])
    target_dir = reports_dir / "stock_kline"
    target = target_dir / f"{stock['symbol']}.html"
    if not cache_path.exists():
        return False, ""
    meta_dir = Path(config.get("data", {}).get("meta_dir") or (Path(config.get("data", {}).get("cache_dir", "data/cache")).parent / "meta"))
    basic_path = meta_dir / "daily_basic" / f"{str(stock.get('symbol', '')).upper()}.csv"
    source_times = [cache_path.stat().st_mtime, source_mtime]
    if basic_path.exists():
        source_times.append(basic_path.stat().st_mtime)
    newest_source = max(source_times)
    if target.exists() and target.stat().st_mtime >= newest_source:
        return True, _rel(output_path, target)
    stock = {**stock}
    basic_info = _read_stock_kline_basic_info(config, str(stock.get("symbol", "")))
    stock["basic"] = basic_info
    if not stock.get("industry"):
        stock["industry"] = basic_info.get("industry") or ""
    payload = _read_stock_kline_payload(
        cache_path, bars, _stock_kline_daily_basic_by_date(config, stock.get("symbol", ""))
    )
    if not payload:
        return False, ""
    target_dir.mkdir(parents=True, exist_ok=True)
    dashboard_href = _rel(target, output_path)
    target.write_text(
        _build_light_stock_kline_html(stock, payload, dashboard_href, back_label="返回股票选择器"),
        encoding="utf-8",
    )
    return True, _rel(output_path, target)


def generate_stock_kline_page(
    config: dict,
    symbol: str,
    bars: int = 0,
    back_href: str = "../dashboard.html",
    back_label: str = "返回 Dashboard",
) -> Path:
    """Generate the canonical lightweight stock K-line page with manual drawing."""
    code = str(symbol or "").strip().upper()
    if not code:
        raise ValueError("symbol 不能为空")
    reports_dir = Path(config.get("output", {}).get("reports_dir", "output/reports"))
    cache_dir = Path(config.get("data", {}).get("cache_dir", "data/cache"))
    cache_path = cache_dir / f"{code}.csv"
    payload = _read_stock_kline_payload(
        cache_path, bars, _stock_kline_daily_basic_by_date(config, code)
    )
    if not payload:
        raise ValueError(f"缺少有效个股 K 线缓存: {code}")
    names: dict[str, str] = {}
    name_path = Path(config.get("data", {}).get("meta_dir", "data/meta")) / "stock_names.csv"
    if name_path.exists():
        try:
            name_df = pd.read_csv(name_path, dtype=str).fillna("")
            if {"ts_code", "name"}.issubset(name_df.columns):
                names = dict(zip(name_df["ts_code"].astype(str), name_df["name"].astype(str)))
        except Exception:
            names = {}
    basic_info = _read_stock_kline_basic_info(config, code)
    stock = {
        "symbol": code,
        "name": names.get(code, code),
        "industry": basic_info.get("industry") or "",
        "basic": basic_info,
    }
    target_dir = reports_dir / "stock_kline"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{code}.html"
    target.write_text(
        _build_light_stock_kline_html(stock, payload, back_href, back_label=back_label),
        encoding="utf-8",
    )
    return target


def _read_stock_selector(config: dict, output_path: Path) -> dict[str, Any]:
    cfg = _stock_selector_config(config)
    if not cfg["enabled"] or not cfg["csv_path"]:
        return {"enabled": False, "rows": [], "source": "", "error": ""}
    source = Path(cfg["csv_path"]).expanduser()
    if not source.exists():
        return {"enabled": True, "rows": [], "source": str(source), "error": "股票选择 CSV 不存在"}
    try:
        df = pd.read_csv(source, dtype=str).fillna("")
    except Exception as exc:
        return {"enabled": True, "rows": [], "source": str(source), "error": f"股票选择 CSV 读取失败: {exc}"}
    rows: list[dict[str, Any]] = []
    cache_dir = Path(config.get("data", {}).get("cache_dir", "data/cache"))
    meta_dir = Path(config.get("data", {}).get("meta_dir") or (cache_dir.parent / "meta"))
    daily_basic_dir = meta_dir / "daily_basic"
    custom_boards_path = Path(cfg["custom_boards_path"]).expanduser() if cfg["custom_boards_path"] else meta_dir / "stock_selector_custom_boards.json"
    custom_boards = _read_stock_selector_custom_boards(custom_boards_path)
    reports_config = {"output": {"reports_dir": config.get("output", {}).get("reports_dir", "output/reports")}, "data": {"cache_dir": str(cache_dir)}}
    source_mtime = source.stat().st_mtime
    limit = int(cfg.get("limit") or 0)
    for row in df.to_dict("records"):
        symbol = _safe_cell(row, STOCK_SELECTOR_COLUMNS["symbol"]).upper()
        if not symbol:
            continue
        name = _safe_cell(row, STOCK_SELECTOR_COLUMNS["name"])
        industry_parts = [
            _safe_cell(row, STOCK_SELECTOR_COLUMNS["industry_l1"]),
            _safe_cell(row, STOCK_SELECTOR_COLUMNS["industry_l2"]),
            _safe_cell(row, STOCK_SELECTOR_COLUMNS["industry_l3"]),
        ]
        industry_tags = _split_board(_safe_cell(row, STOCK_SELECTOR_COLUMNS["industry_board"]))
        for item in industry_parts:
            if item and item not in industry_tags:
                industry_tags.append(item)
        concept_tags = _split_board(_safe_cell(row, STOCK_SELECTOR_COLUMNS["concept_board"]))
        stock = {
            "symbol": symbol,
            "name": name,
            "industry": " / ".join([item for item in industry_parts if item]) or " / ".join(industry_tags[:3]),
            "industry_tags": industry_tags[:12],
            "concepts": concept_tags[:36],
            "price": _round_or_none(_safe_cell(row, STOCK_SELECTOR_COLUMNS["price"])),
            "pct_chg": _round_or_none(_safe_cell(row, STOCK_SELECTOR_COLUMNS["pct_chg"])),
        }
        cache_path = cache_dir / f"{symbol}.csv"
        cache_metrics = _read_stock_selector_cache_metrics(cache_path)
        if cache_metrics.get("price") is not None:
            stock["price"] = cache_metrics.get("price")
        if cache_metrics.get("pct_chg") is not None:
            stock["pct_chg"] = cache_metrics.get("pct_chg")
        market_cap = _first_numeric_cell(row, STOCK_SELECTOR_MARKET_CAP_COLUMNS, 3)
        if market_cap is None:
            market_cap = _read_stock_selector_daily_basic_metrics(daily_basic_dir / f"{symbol}.csv").get("market_cap")
        kline_exists = False
        kline_href = ""
        if cfg["generate_kline_pages"]:
            kline_exists, kline_href = _ensure_light_stock_kline_page(
                config, output_path, stock, cache_path, source_mtime, int(cfg["kline_bars"])
            )
        if not kline_href:
            kline_href = stock_report_href(reports_config, output_path, symbol)
            kline_exists = (
                Path(config.get("output", {}).get("reports_dir", "output/reports"))
                / "stock_kline"
                / f"{symbol}.html"
            ).exists()
        stock.update(
            {
                "href": kline_href,
                "kline_exists": bool(kline_exists),
                "cache_exists": cache_path.exists(),
                "date": cache_metrics.get("date") or "",
                "pct_5d": cache_metrics.get("pct_5d"),
                "market_cap": market_cap,
                "name_text": f"{symbol} {name}".lower(),
                "industry_text": " ".join(industry_tags).lower(),
                "concept_text": " ".join(concept_tags).lower(),
                "search_text": f"{symbol} {name} {' '.join(industry_tags)} {' '.join(concept_tags)}".lower(),
            }
        )
        rows.append(stock)
        if limit and len(rows) >= limit:
            break

    def _top_tags(field: str, n: int = 18) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for item in rows:
            for tag in item.get(field, [])[:24]:
                counts[tag] = counts.get(tag, 0) + 1
        return [{"name": key, "count": value} for key, value in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]

    return {
        "enabled": True,
        "source": str(source),
        "error": "",
        "rows": rows,
        "count": len(rows),
        "kline_count": sum(1 for item in rows if item.get("kline_exists")),
        "cache_count": sum(1 for item in rows if item.get("cache_exists")),
        "top_concepts": _top_tags("concepts"),
        "top_industries": _top_tags("industry_tags"),
        "custom_boards_path": custom_boards.get("path", ""),
        "custom_boards_exists": bool(custom_boards.get("exists")),
        "custom_boards_error": custom_boards.get("error", ""),
        "custom_boards": custom_boards.get("boards", {}),
    }


def _stock_selector_summary(
    selector: dict[str, Any],
    selector_path: Path,
    output_path: Path,
    viewer_path: Path | None = None,
) -> dict[str, Any]:
    """Return a compact dashboard-safe stock selector summary without row payloads."""
    available = bool(selector.get("enabled")) and not selector.get("error") and selector_path.exists()
    viewer_available = bool(selector.get("enabled")) and not selector.get("error") and bool(viewer_path and viewer_path.exists())
    return {
        "enabled": bool(selector.get("enabled")),
        "source": str(selector.get("source", "")),
        "error": str(selector.get("error", "")),
        "count": int(selector.get("count") or len(selector.get("rows") or [])),
        "cache_count": int(selector.get("cache_count") or 0),
        "kline_count": int(selector.get("kline_count") or 0),
        "top_concepts": selector.get("top_concepts", [])[:8],
        "top_industries": selector.get("top_industries", [])[:8],
        "href": _rel(output_path, selector_path) if available else "",
        "viewer_href": _rel(output_path, viewer_path) if viewer_available and viewer_path else "",
        "selector_href": _rel(output_path, selector_path) if available else "",
        "viewer_exists": viewer_available,
        "exists": available,
    }


def _configured_indexes(config: dict) -> list[dict[str, str]]:
    indexes = config.get("index_overview", {}).get("indexes", [])
    if indexes:
        return [
            {
                "symbol": str(item.get("symbol", "")).upper(),
                "name": str(item.get("name") or item.get("symbol", "")),
            }
            for item in indexes
            if item.get("symbol")
        ]
    return [{"symbol": symbol, "name": name} for symbol, name in INDEX_FALLBACKS.items()]


def _discover_strategies() -> list[str]:
    strategy_dir = Path(__file__).parent.parent / "strategy"
    names = []
    for path in strategy_dir.glob("*.py"):
        if path.stem not in {"base", "__init__"}:
            names.append(path.stem)
    return sorted(names)


def _strategy_snapshot(summary_path: Path) -> dict[str, Any]:
    if not summary_path.exists():
        return {}
    try:
        df = pd.read_csv(summary_path)
        if df.empty:
            return {}
        stats = compute_stats(df)
    except Exception:
        return {}
    return {
        "count": stats.get("count", 0),
        "active_ratio": _fmt_pct(stats.get("active_ratio"), 1).replace("+", ""),
        "avg_return": _fmt_pct(stats.get("avg_return")),
        "avg_active_return": _fmt_pct(stats.get("avg_active_return")),
        "positive_ratio": _fmt_pct(stats.get("positive_ratio"), 1).replace("+", ""),
        "avg_drawdown": _fmt_pct(-abs(float(stats.get("avg_max_dd", 0))), 1),
        "avg_sharpe": _fmt_num(stats.get("avg_sharpe"), 3),
    }


def _stock_report_count(reports_dir: Path) -> int:
    if not reports_dir.exists():
        return 0
    return sum(1 for p in reports_dir.glob("*.html") if _is_stock_report_file(p))


def _is_stock_report_file(path: Path) -> bool:
    if path.name in {"dashboard.html", "stock_selector.html"}:
        return False
    if path.name.endswith("_trendlines.html"):
        return False
    head = path.stem.split("_", 1)[0].upper()
    return head.endswith((".SZ", ".SH", ".BJ")) and len(head.split(".", 1)[0]) == 6


def _recent_stock_reports(reports_dir: Path, output_path: Path, limit: int = 12) -> list[dict[str, str]]:
    if not reports_dir.exists():
        return []
    stock_kline_dir = reports_dir / "stock_kline"
    html_paths = list(reports_dir.glob("*.html"))
    if stock_kline_dir.exists():
        html_paths.extend(stock_kline_dir.glob("*.html"))
    paths = sorted(
        [p for p in html_paths if _is_stock_report_file(p)],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:limit]
    reports = []
    for path in paths:
        stem = path.stem
        parts = stem.split("_", 1)
        symbol = parts[0]
        strategy = parts[1] if len(parts) > 1 else ""
        reports.append(
            {
                "name": stem,
                "symbol": symbol,
                "strategy": _STRATEGY_LABELS.get(strategy, strategy),
                "href": _rel(output_path, path),
                "time": datetime.fromtimestamp(path.stat().st_mtime).strftime("%m-%d %H:%M"),
            }
        )
    return reports


def _theme_dashboards(stats_dir: Path, output_path: Path) -> list[dict[str, Any]]:
    if not stats_dir.exists():
        return []

    def _as_int(value: Any) -> int:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0
        if pd.isna(number):
            return 0
        return int(number)

    items: list[dict[str, Any]] = []
    for summary_path in stats_dir.glob("theme_*_summary.csv"):
        try:
            df = pd.read_csv(summary_path)
        except Exception:
            continue
        if df.empty:
            continue

        row = df.iloc[0]
        html_path = summary_path.with_name(summary_path.name.replace("_summary.csv", ".html"))
        detail_path = summary_path.with_name(summary_path.name.replace("_summary.csv", ".csv"))
        pool = str(row.get("pool", summary_path.stem.replace("theme_", "").replace("_summary", "")))
        start = str(row.get("start", ""))
        end = str(row.get("end", ""))
        avg_return = row.get("avg_return_pct")
        items.append(
            {
                "pool": pool,
                "start": start,
                "end": end,
                "stock_count": _as_int(row.get("stock_count", 0)),
                "valid_count": _as_int(row.get("valid_count", 0)),
                "avg_return": _fmt_pct(avg_return),
                "concept_return": _fmt_pct(row.get("concept_return_pct")),
                "median_return": _fmt_pct(row.get("median_return_pct")),
                "positive_ratio": _fmt_pct(row.get("positive_ratio_pct"), 1).replace("+", ""),
                "avg_drawdown": _fmt_pct(row.get("avg_max_drawdown_pct"), 1),
                "trend_breadth": _fmt_pct(row.get("concept_latest_above_ma20_ratio_pct"), 1).replace("+", ""),
                "new_high_ratio": _fmt_pct(row.get("concept_latest_new_high_20_ratio_pct"), 1).replace("+", ""),
                "new_low_ratio": _fmt_pct(row.get("concept_latest_new_low_20_ratio_pct"), 1).replace("+", ""),
                "dispersion": _fmt_pct(row.get("return_std_pct"), 1).replace("+", ""),
                "volatility": _fmt_pct(row.get("avg_annualized_volatility_pct"), 1).replace("+", ""),
                "best": f"{row.get('best_symbol', '')} {row.get('best_name', '')}".strip(),
                "best_return": _fmt_pct(row.get("best_return_pct")),
                "href": _rel(output_path, html_path) if html_path.exists() else "",
                "detail_href": _rel(output_path, detail_path) if detail_path.exists() else "",
                "exists": html_path.exists(),
                "mtime": html_path.stat().st_mtime if html_path.exists() else summary_path.stat().st_mtime,
                "tone": "up" if str(_fmt_pct(avg_return)).startswith("+") else "down" if str(_fmt_pct(avg_return)).startswith("-") else "flat",
            }
        )

    latest_by_pool: dict[str, dict[str, Any]] = {}
    for item in items:
        pool = str(item.get("pool", ""))
        if pool not in latest_by_pool or float(item.get("mtime", 0)) > float(latest_by_pool[pool].get("mtime", 0)):
            latest_by_pool[pool] = item

    return sorted(latest_by_pool.values(), key=lambda item: item["mtime"], reverse=True)


def _etf_strategy_snapshot(stats_dir: Path, reports_dir: Path, output_path: Path) -> dict[str, Any]:
    report_path = reports_dir / "etf_strategy" / "etf_strategy_dashboard.html"
    summary_path = stats_dir / "etf_strategy" / "etf_strategy_summary.csv"
    snapshot = {
        "exists": report_path.exists(),
        "href": _rel(output_path, report_path) if report_path.exists() else "",
        "summary_exists": summary_path.exists(),
        "summary_href": _rel(output_path, summary_path) if summary_path.exists() else "",
        "count": 0,
        "date": "--",
        "leader": "--",
        "leader_return": "--",
        "macd_buy": 0,
        "momentum_targets": "--",
    }
    if not summary_path.exists():
        return snapshot
    try:
        df = pd.read_csv(summary_path)
    except Exception:
        return snapshot
    if df.empty:
        return snapshot
    snapshot["count"] = int(len(df))
    dates = df.get("date", pd.Series(["--"])).dropna()
    snapshot["date"] = str(dates.iloc[-1]) if not dates.empty else "--"
    if "return_20d_pct" in df.columns:
        ranked = df.sort_values("return_20d_pct", ascending=False, na_position="last")
        row = ranked.iloc[0]
        snapshot["leader"] = f"{row.get('name', '')} {row.get('symbol', '')}".strip()
        snapshot["leader_return"] = _fmt_pct(row.get("return_20d_pct"))
    if "macd_signal" in df.columns:
        snapshot["macd_buy"] = int((pd.to_numeric(df["macd_signal"], errors="coerce") == 1).sum())
    if "momentum_target" in df.columns:
        targets = df.loc[df["momentum_target"].fillna(False).astype(bool)]
        snapshot["momentum_targets"] = "、".join(
            str(item).strip()
            for item in (targets.get("name", targets.get("symbol", pd.Series(dtype=str))).head(3).tolist())
            if str(item).strip()
        ) or "--"
    return snapshot


def _latest_file(directory: Path, pattern: str) -> Path | None:
    if not directory.exists():
        return None
    paths = sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    return paths[0] if paths else None


def _read_rows(path: Path | None, limit: int = 8) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    try:
        df = pd.read_csv(path)
    except Exception:
        return []
    return df.head(limit).fillna("").to_dict("records")


def _signal_center(stats_dir: Path, signals_dir: Path, output_path: Path) -> dict[str, Any]:
    rps_path = _latest_file(stats_dir, "rps_top_*.csv")
    pattern_path = _latest_file(signals_dir, "pattern_signals_*.csv")
    screen_path = _latest_file(signals_dir, "screen_signals_*.csv")
    limit_path = _latest_file(stats_dir, "limit_board_????????.csv")
    limit_strength_path = _latest_file(stats_dir / "limit_strength", "limit_strength_????????.csv")
    rotation_path = _latest_file(stats_dir, "rotation_*_nav.csv")
    radar_path = stats_dir / "strong_stock_radar" / "strong_stock_radar_latest.csv"
    radar_report = output_path.parent / "strong_stock_radar" / "strong_stock_radar.html"

    limit_summary: dict[str, Any] = {}
    if limit_path is not None:
        rows = _read_rows(limit_path, 10000)
        up = sum(1 for row in rows if row.get("limit_type") == "U")
        down = sum(1 for row in rows if row.get("limit_type") == "D")
        opened = sum(1 for row in rows if row.get("limit_type") == "Z")
        limit_summary = {"up": up, "down": down, "opened": opened}

    rotation_summary: dict[str, Any] = {}
    if rotation_path is not None:
        try:
            nav_df = pd.read_csv(rotation_path)
            if not nav_df.empty:
                first = float(nav_df["nav"].iloc[0])
                last = float(nav_df["nav"].iloc[-1])
                rotation_summary = {
                    "date": str(nav_df["date"].iloc[-1]),
                    "return": _fmt_pct((last / first - 1) * 100 if first else 0),
                    "holdings": str(nav_df.get("holdings", pd.Series([""])).iloc[-1]),
                }
        except Exception:
            pass

    def _href(path: Path | None, suffix: str = ".html") -> str:
        if path is None:
            return ""
        target = path.with_suffix(suffix)
        return _rel(output_path, target) if target.exists() else _rel(output_path, path)

    rotation_href = ""
    if rotation_path is not None:
        rotation_html = rotation_path.with_name(rotation_path.name.replace("_nav.csv", ".html"))
        rotation_href = _rel(output_path, rotation_html) if rotation_html.exists() else _rel(output_path, rotation_path)

    return {
        "rps": {
            "href": _href(rps_path),
            "exists": rps_path is not None,
            "rows": _read_rows(rps_path, 6),
            "file": rps_path.name if rps_path else "",
        },
        "patterns": {
            "href": _href(pattern_path),
            "exists": pattern_path is not None,
            "rows": _read_rows(pattern_path, 6),
            "file": pattern_path.name if pattern_path else "",
        },
        "screens": {
            "href": _href(screen_path),
            "exists": screen_path is not None,
            "rows": _read_rows(screen_path, 6),
            "file": screen_path.name if screen_path else "",
        },
        "limit": {
            "href": _href(limit_path),
            "exists": limit_path is not None,
            "rows": _read_rows(limit_path, 6),
            "summary": limit_summary,
            "file": limit_path.name if limit_path else "",
        },
        "limit_strength": {
            "href": _href(limit_strength_path),
            "exists": limit_strength_path is not None,
            "rows": _read_rows(limit_strength_path, 6),
            "file": limit_strength_path.name if limit_strength_path else "",
        },
        "rotation": {
            "href": rotation_href,
            "exists": rotation_path is not None,
            "summary": rotation_summary,
            "file": rotation_path.name if rotation_path else "",
        },
        "radar": {
            "href": _rel(output_path, radar_report) if radar_report.exists() else "",
            "exists": radar_path.exists(),
            "rows": _read_rows(radar_path, 6),
            "file": radar_path.name if radar_path.exists() else "",
            "summary": _strong_stock_radar_summary(radar_path),
        },
    }


def _strong_stock_radar_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"date": "--", "core": 0, "accelerating": 0, "breakout": 0, "weakening": 0}
    try:
        df = pd.read_csv(path)
    except Exception:
        return {"date": "--", "core": 0, "accelerating": 0, "breakout": 0, "weakening": 0}
    if df.empty:
        return {"date": "--", "core": 0, "accelerating": 0, "breakout": 0, "weakening": 0}
    states = df.get("state", pd.Series(dtype=str)).value_counts()
    dates = df.get("trade_date", pd.Series(["--"])).dropna()
    return {
        "date": str(dates.iloc[-1]) if not dates.empty else "--",
        "core": int(states.get("CORE_STRONG", 0)),
        "accelerating": int(states.get("ACCELERATING", 0)),
        "breakout": int(states.get("BREAKOUT", 0)),
        "weakening": int(states.get("STRONG_WEAKENING", 0)),
    }


def _market_amount_payload(structure: dict[str, Any]) -> dict[str, Any]:
    liquidity = structure.get("liquidity_structure") or {}
    breadth = structure.get("breadth") or {}
    history = breadth.get("history") or liquidity.get("history") or []
    if not isinstance(history, list):
        history = []

    rows: list[dict[str, Any]] = []
    for row in history[-520:]:
        if not isinstance(row, dict):
            continue
        trade_date = str(row.get("trade_date") or row.get("date") or "").strip()
        total_amount = _round_or_none(row.get("total_market_amount", row.get("total_amount")), 0)
        if not trade_date or total_amount is None:
            continue
        ratio_20d = _round_or_none(row.get("amount_ratio_20", row.get("amount_ratio_20d")), 4)
        amount_ma20 = _round_or_none(row.get("amount_ma20"), 0)
        rows.append(
            {
                "trade_date": trade_date,
                "total_amount": total_amount,
                "amount_ma20": amount_ma20 if amount_ma20 is not None else (round(total_amount / ratio_20d, 0) if ratio_20d and ratio_20d > 0 else None),
                "amount_ratio_5d": _round_or_none(row.get("amount_ratio_5d"), 4),
                "amount_ratio_20d": ratio_20d,
                "advance_amount_ratio": _round_or_none(row.get("advance_amount_ratio"), 5),
                "decline_amount_ratio": _round_or_none(row.get("decline_amount_ratio"), 5),
                "equal_weight_return_1d": _round_or_none(row.get("equal_weight_return_1d"), 5),
                "state": str(row.get("state") or ""),
            }
        )

    latest = liquidity.get("latest") if isinstance(liquidity.get("latest"), dict) else {}
    if not latest and rows:
        latest = rows[-1]

    latest_amount = _round_or_none(latest.get("total_amount") if isinstance(latest, dict) else None, 0)
    latest_ratio_20d = _round_or_none(latest.get("amount_ratio_20d") if isinstance(latest, dict) else None, 4)
    return {
        "dates": [row["trade_date"] for row in rows],
        "total_amount": [row["total_amount"] for row in rows],
        "amount_ma20": [row["amount_ma20"] for row in rows],
        "amount_ratio_5d": [row["amount_ratio_5d"] for row in rows],
        "amount_ratio_20d": [row["amount_ratio_20d"] for row in rows],
        "advance_amount_ratio": [row["advance_amount_ratio"] for row in rows],
        "decline_amount_ratio": [row["decline_amount_ratio"] for row in rows],
        "equal_weight_return_1d": [row["equal_weight_return_1d"] for row in rows],
        "state": [row["state"] for row in rows],
        "latest": {
            "trade_date": str((latest or {}).get("trade_date") or (latest or {}).get("date") or structure.get("date", "--")),
            "total_amount": latest_amount,
            "total_amount_text": _fmt_tushare_amount(latest_amount),
            "amount_ratio_5d": _round_or_none((latest or {}).get("amount_ratio_5d"), 4),
            "amount_ratio_20d": latest_ratio_20d,
            "amount_ratio_20d_text": _fmt_multiple(latest_ratio_20d),
            "advance_amount_ratio": _round_or_none((latest or {}).get("advance_amount_ratio"), 5),
            "advance_amount_ratio_text": _fmt_ratio_pct((latest or {}).get("advance_amount_ratio")),
            "decline_amount_ratio": _round_or_none((latest or {}).get("decline_amount_ratio"), 5),
            "decline_amount_ratio_text": _fmt_ratio_pct((latest or {}).get("decline_amount_ratio")),
            "state": str((latest or {}).get("state") or ""),
        },
    }


def _return_distribution_payload(structure: dict[str, Any]) -> dict[str, Any]:
    distribution = structure.get("return_distribution") or {}
    histogram = distribution.get("histogram") or (structure.get("breadth") or {}).get("return_distribution") or []
    if not isinstance(histogram, list):
        histogram = []
    rows = []
    for item in histogram:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        count = _round_or_none(item.get("count"), 0)
        ratio = _round_or_none(item.get("ratio"), 5)
        if label and count is not None:
            rows.append({"label": label, "count": count, "ratio": ratio})
    latest = distribution.get("latest") if isinstance(distribution.get("latest"), dict) else {}
    return {
        "date": str(latest.get("trade_date") or structure.get("date", "--")),
        "state": str(distribution.get("state") or ""),
        "valid_count": int(_round_or_none(latest.get("valid_count"), 0) or sum(row["count"] for row in rows)),
        "median": _round_or_none(latest.get("median"), 5),
        "up_ratio": _round_or_none((structure.get("breadth") or {}).get("latest", {}).get("advance_ratio"), 5),
        "histogram": rows,
    }


def _output_is_fresh(target: Path, sources: list[Path]) -> bool:
    """Return whether a derived report is newer than all available inputs."""
    if not target.exists():
        return False
    source_times = [source.stat().st_mtime for source in sources if source.exists()]
    return bool(source_times) and target.stat().st_mtime >= max(source_times)


def _ths_section_source_paths(config: dict, section: str) -> list[Path]:
    ths_cfg = config.get("ths_indices", {}) if isinstance(config.get("ths_indices"), dict) else {}
    section_cfg = ths_cfg.get(section) if isinstance(ths_cfg.get(section), dict) else {}
    meta_dir = Path(config.get("data", {}).get("meta_dir", "data/meta"))
    paths = [meta_dir / "ths_indices.csv"]
    for key in ("include_path", "exclude_path"):
        value = str(section_cfg.get(key) or "").strip()
        if not value:
            continue
        path = Path(value).expanduser()
        paths.append(path if path.is_absolute() else meta_dir / path)
    return paths


def _read_ths_symbols_for_dashboard(path: Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()
    try:
        frame = pd.read_csv(path, dtype=str).fillna("")
    except Exception:
        return set()
    if frame.empty:
        return set()
    symbol_col = next((col for col in ("ts_code", "symbol", "代码") if col in frame.columns), frame.columns[0])
    return {
        str(value).strip().upper()
        for value in frame[symbol_col].tolist()
        if str(value).strip().upper().endswith(".TI")
    }


def _ths_section_cache_paths(config: dict, section: str) -> list[Path]:
    """Return local 同花顺 index cache files that can make a market page stale."""
    ths_cfg = config.get("ths_indices", {}) if isinstance(config.get("ths_indices"), dict) else {}
    section_cfg = ths_cfg.get(section) if isinstance(ths_cfg.get(section), dict) else {}
    meta_dir = Path(config.get("data", {}).get("meta_dir", "data/meta"))
    index_list_path = meta_dir / "ths_indices.csv"
    if not index_list_path.exists():
        return []
    try:
        frame = pd.read_csv(index_list_path, dtype={"ts_code": str}).fillna("")
    except Exception:
        return []
    if frame.empty or "ts_code" not in frame.columns:
        return []

    default_type = "I" if section == "industries" else "N"
    exchange = str(section_cfg.get("exchange", "A")).upper()
    index_type = str(section_cfg.get("type", default_type)).upper()
    min_count = section_cfg.get("min_count", 1)
    mask = pd.Series(True, index=frame.index)
    if "exchange" in frame.columns:
        mask &= frame["exchange"].astype(str).str.upper() == exchange
    if "type" in frame.columns:
        mask &= frame["type"].astype(str).str.upper() == index_type
    if "count" in frame.columns and min_count is not None:
        mask &= pd.to_numeric(frame["count"], errors="coerce").fillna(0) >= float(min_count)

    symbols = frame.loc[mask, "ts_code"].astype(str).str.upper().tolist()
    include_symbols: set[str] = set()
    exclude_symbols: set[str] = set()
    raw_include = str(section_cfg.get("include_path") or "").strip()
    raw_exclude = str(section_cfg.get("exclude_path") or "").strip()
    if raw_include:
        path = Path(raw_include).expanduser()
        include_symbols = _read_ths_symbols_for_dashboard(path if path.is_absolute() else meta_dir / path)
    if raw_exclude:
        path = Path(raw_exclude).expanduser()
        exclude_symbols = _read_ths_symbols_for_dashboard(path if path.is_absolute() else meta_dir / path)
    if include_symbols:
        symbols = [symbol for symbol in symbols if symbol in include_symbols]
    if exclude_symbols:
        symbols = [symbol for symbol in symbols if symbol not in exclude_symbols]
    limit = section_cfg.get("limit")
    if limit:
        symbols = symbols[: int(limit)]

    cache_dir = Path(config.get("data", {}).get("cache_dir", "data/cache")) / "index"
    return [cache_dir / f"{symbol}.csv" for symbol in dict.fromkeys(symbols) if symbol.endswith(".TI")]


def _collect_dashboard_data(config: dict, output_path: Path) -> dict[str, Any]:
    reports_dir = Path(config["output"]["reports_dir"])
    stats_dir = Path(config["output"].get("statistics_dir", "output/statistics"))
    trades_dir = Path(config["output"]["trades_dir"])
    signals_dir = Path(config["output"].get("signals_dir", "output/signals"))
    index_cache_dir = Path(config["data"]["cache_dir"]) / "index"
    index_reports_dir = reports_dir / "index"
    market_report_path = reports_dir / "market_overview.html"
    structure_alias = reports_dir / "index_forecast" / "000001.SH_market_structure.html"
    structure_brief = reports_dir / "index_forecast" / "000001.SH_market_structure_brief.html"
    industry_market_report = reports_dir / "industry" / "industry_market.html"
    concept_market_report = reports_dir / "concept" / "concept_market.html"
    legacy_forecast_report = reports_dir / "index_forecast" / "000001.SH_h5.html"
    forecast_report_path = structure_alias if structure_alias.exists() else legacy_forecast_report
    forecast_csv_path = stats_dir / "index_forecast" / "predictions_000001.SH_h5.csv"
    market_structure_path = stats_dir / "index_forecast" / "market_structure_000001.SH.json"
    data_quality_path = stats_dir / "data_quality" / "market_data_audit.json"
    data_quality_report = reports_dir / "data_quality.html"
    optimization_audit_report = reports_dir / "project_optimization_audit.html"
    sector_money_flow_report = reports_dir / "sector_money_flow.html"
    support_resistance_dir = Path(
        (config.get("support_resistance") or {}).get("output_dir")
        or reports_dir / "support_resistance"
    )
    support_resistance_report = _latest_file(support_resistance_dir, "*_support_resistance.html")
    stock_selector_path = reports_dir / "stock_selector.html"
    stock_viewer_path = reports_dir / "stock_viewer.html"
    stock_selector_full = _read_stock_selector(config, stock_selector_path)
    if stock_selector_full.get("enabled") and not stock_selector_full.get("error"):
        stock_selector_path.write_text(
            _build_stock_selector_html(stock_selector_full, _rel(stock_selector_path, output_path)),
            encoding="utf-8",
        )
        stock_viewer_path.write_text(
            _build_stock_viewer_html(
                stock_selector_full,
                _rel(stock_viewer_path, output_path),
                _rel(stock_viewer_path, stock_selector_path),
            ),
            encoding="utf-8",
        )
    forecast_snapshot = {"date": "--", "signal": "--", "score": "--"}
    data_quality = {
        "exists": data_quality_report.exists(),
        "href": _rel(output_path, data_quality_report) if data_quality_report.exists() else "",
        "status": "unknown",
        "latest_coverage": None,
        "warning_count": 0,
        "critical_count": 0,
    }
    if data_quality_path.exists():
        try:
            audit = json.loads(data_quality_path.read_text(encoding="utf-8"))
            audit_summary = audit.get("summary") or {}
            audit_stocks = (audit.get("datasets") or {}).get("stocks") or {}
            data_quality.update(
                {
                    "status": str(audit.get("status") or "unknown"),
                    "latest_coverage": _round_or_none(audit_stocks.get("latest_coverage"), 6),
                    "warning_count": int(audit_summary.get("warning_count") or 0),
                    "critical_count": int(audit_summary.get("critical_count") or 0),
                    "reference_date": str(audit_stocks.get("reference_date") or ""),
                }
            )
        except (OSError, ValueError, TypeError):
            pass
    market_amount: dict[str, Any] = {}
    return_distribution: dict[str, Any] = {}
    if market_structure_path.exists():
        try:
            structure = json.loads(market_structure_path.read_text(encoding="utf-8"))
            state = structure.get("market_structure") or {}
            market_amount = _market_amount_payload(structure)
            return_distribution = _return_distribution_payload(structure)
            forecast_snapshot = {
                "date": str(structure.get("date", "--")),
                "signal": str(state.get("style_regime_name", "--")),
                "score": str({"strong": "偏强", "neutral": "中性", "weak": "偏弱"}.get(state.get("breadth_state"), "--")),
            }
            brief_sources = [
                market_structure_path,
                Path(generate_market_structure_brief.__code__.co_filename),
            ]
            if not _output_is_fresh(structure_brief, brief_sources):
                generate_market_structure_brief(
                    config,
                    structure,
                    structure_brief,
                    full_report_path=structure_alias if structure_alias.exists() else None,
                )
            industry_sources = [
                market_structure_path,
                Path(generate_industry_market_report.__code__.co_filename),
                *_ths_section_source_paths(config, "industries"),
                *_ths_section_source_paths(config, "concepts"),
                *_ths_section_cache_paths(config, "industries"),
                *_ths_section_cache_paths(config, "concepts"),
            ]
            if not _output_is_fresh(industry_market_report, industry_sources):
                generate_industry_market_report(config, structure, industry_market_report)
            concept_sources = [
                market_structure_path,
                Path(generate_concept_market_report.__code__.co_filename),
                *_ths_section_source_paths(config, "concepts"),
                *_ths_section_cache_paths(config, "concepts"),
            ]
            if not _output_is_fresh(concept_market_report, concept_sources):
                generate_concept_market_report(config, structure, concept_market_report)
        except (OSError, ValueError, TypeError):
            pass
    if forecast_csv_path.exists():
        try:
            forecast_df = pd.read_csv(forecast_csv_path)
            if not forecast_df.empty and forecast_snapshot["date"] == "--":
                latest_forecast = forecast_df.iloc[-1]
                forecast_snapshot = {
                    "date": str(latest_forecast.get("trade_date", "--")),
                    "signal": str(latest_forecast.get("signal", "--")),
                    "score": _fmt_num(latest_forecast.get("market_score")),
                }
        except Exception:
            pass

    indexes = []
    for item in _configured_indexes(config):
        symbol = item["symbol"]
        report_path = index_reports_dir / f"{symbol}_overview.html"
        cache_path = index_cache_dir / f"{symbol}.csv"
        indexes.append(
            {
                "symbol": symbol,
                "name": item["name"],
                "snapshot": _read_index_snapshot(cache_path),
                "chart": _read_index_chart(cache_path),
                "href": _rel(output_path, report_path) if report_path.exists() else "",
                "exists": report_path.exists(),
            }
        )

    strategies = []
    for strategy in _discover_strategies():
        summary_path = trades_dir / f"_summary_{strategy}.csv"
        analyze_path = stats_dir / f"analysis_{strategy}.html"
        strategies.append(
            {
                "name": strategy,
                "label": _STRATEGY_LABELS.get(strategy, strategy),
                "snapshot": _strategy_snapshot(summary_path),
                "summary_exists": summary_path.exists(),
                "href": _rel(output_path, analyze_path) if analyze_path.exists() else "",
                "exists": analyze_path.exists(),
            }
        )

    comparison_path = stats_dir / "comparison.html"
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "indexes": indexes,
        "market_report_href": _rel(output_path, market_report_path) if market_report_path.exists() else "",
        "market_report_exists": market_report_path.exists(),
        "forecast_report_href": _rel(output_path, structure_alias) if structure_alias.exists() else "",
        "forecast_report_exists": structure_alias.exists(),
        "market_brief_href": _rel(output_path, structure_brief) if structure_brief.exists() else "",
        "market_brief_exists": structure_brief.exists(),
        "industry_market_href": _rel(output_path, industry_market_report) if industry_market_report.exists() else "",
        "industry_market_exists": industry_market_report.exists(),
        "concept_market_href": (_rel(output_path, industry_market_report) + "#concept") if industry_market_report.exists() else (_rel(output_path, concept_market_report) if concept_market_report.exists() else ""),
        "concept_market_exists": industry_market_report.exists() or concept_market_report.exists(),
        "forecast_snapshot": forecast_snapshot,
        "market_amount": market_amount,
        "return_distribution": return_distribution,
        "strategies": strategies,
        "comparison_href": _rel(output_path, comparison_path) if comparison_path.exists() else "",
        "comparison_exists": comparison_path.exists(),
        "stock_report_count": _stock_report_count(reports_dir),
        "recent_stock_reports": _recent_stock_reports(reports_dir, output_path),
        "theme_dashboards": _theme_dashboards(stats_dir, output_path),
        "etf_strategy": _etf_strategy_snapshot(stats_dir, reports_dir, output_path),
        "sector_money_flow": {
            "exists": sector_money_flow_report.exists(),
            "href": _rel(output_path, sector_money_flow_report) if sector_money_flow_report.exists() else "",
        },
        "support_resistance": {
            "exists": support_resistance_report is not None,
            "href": _rel(output_path, support_resistance_report) if support_resistance_report is not None else "",
            "file": support_resistance_report.name if support_resistance_report is not None else "",
        },
        "signal_center": _signal_center(stats_dir, signals_dir, output_path),
        "stock_selector": _stock_selector_summary(stock_selector_full, stock_selector_path, output_path, stock_viewer_path),
        "data_quality": data_quality,
        "optimization_audit": {
            "exists": optimization_audit_report.exists(),
            "href": _rel(output_path, optimization_audit_report) if optimization_audit_report.exists() else "",
        },
        "_reports_dir": str(reports_dir),
        "_output_path": str(output_path),
    }


def _badge(exists: bool) -> str:
    label = "已生成" if exists else "待生成"
    cls = "ok" if exists else "wait"
    return f'<span class="badge {cls}">{label}</span>'


def _build_index_cards(data: dict[str, Any]) -> str:
    indexes = data.get("indexes", [])
    if not indexes:
        return '<p class="empty">暂无指数数据</p>'
    buttons = []
    first = indexes[0]
    for idx, item in enumerate(indexes, start=1):
        snap = item.get("snapshot", {})
        pct = str(snap.get("pct_chg", "--"))
        tone = _tone_from_pct(pct)
        active = " active" if idx == 1 else ""
        buttons.append(
            f"""
            <button type="button" class="index-select {html.escape(tone)}{active}" data-symbol="{html.escape(str(item.get("symbol", "")), quote=True)}">
              <span>{idx:02d}</span>
              <strong>{html.escape(str(item.get("name", "--")))}</strong>
              <em>{html.escape(str(item.get("symbol", "--")))}</em>
              <b>{html.escape(pct)}</b>
            </button>
            """
        )
    first_snap = first.get("snapshot", {})
    first_href = html.escape(str(first.get("href", "")), quote=True)
    return f"""
    <article class="index-nav-panel">
      <div class="index-select-list">{"".join(buttons)}</div>
      <div class="index-mini-panel">
        <div class="index-mini-head">
          <div>
            <h3 id="index-mini-name">{html.escape(str(first.get("name", "--")))}</h3>
            <p id="index-mini-meta">{html.escape(str(first.get("symbol", "--")))} · {html.escape(str(first_snap.get("date", "--")))}</p>
          </div>
          <div class="index-mini-quote">
            <strong id="index-mini-close">{html.escape(str(first_snap.get("close", "--")))}</strong>
            <em id="index-mini-pct" class="{html.escape(_tone_from_pct(str(first_snap.get("pct_chg", "--"))))}">{html.escape(str(first_snap.get("pct_chg", "--")))}</em>
            <a id="index-mini-link" href="{first_href}" {'aria-disabled="true"' if not first_href else ''}>打开报告</a>
          </div>
        </div>
        <div id="index-mini-chart" class="index-mini-chart"></div>
        <div class="distribution-mini-panel">
          <div class="distribution-mini-head">
            <strong>当天涨跌分布</strong>
            <span id="distribution-mini-meta">按全市场个股 1 日涨跌幅分桶</span>
          </div>
          <div id="index-distribution-chart" class="index-distribution-chart"></div>
        </div>
      </div>
    </article>
    """


def _build_strategy_cards(data: dict[str, Any]) -> str:
    cards = []
    for item in data["strategies"]:
        snap = item["snapshot"]
        href = html.escape(item["href"])
        attrs = f'href="{href}"' if href else 'href="#" aria-disabled="true"'
        ret = snap.get("avg_return", "--")
        tone = "up" if ret.startswith("+") else "down" if ret.startswith("-") else "flat"
        cards.append(
            f"""
            <a class="strategy-row {tone}" {attrs}>
              <div>
                <div class="row-title">{html.escape(item["label"])}</div>
                <div class="row-sub">{html.escape(item["name"])}</div>
              </div>
              <div class="row-metric"><span>股票数</span><strong>{html.escape(str(snap.get("count", "--")))}</strong></div>
              <div class="row-metric"><span>平均收益</span><strong>{html.escape(ret)}</strong></div>
              <div class="row-metric"><span>交易股</span><strong>{html.escape(snap.get("avg_active_return", "--"))}</strong></div>
              <div class="row-metric"><span>正收益</span><strong>{html.escape(snap.get("positive_ratio", "--"))}</strong></div>
              <div class="row-metric"><span>夏普</span><strong>{html.escape(snap.get("avg_sharpe", "--"))}</strong></div>
              {_badge(item["exists"])}
            </a>
            """
        )
    return "\n".join(cards)


def _build_recent_reports(data: dict[str, Any]) -> str:
    reports = data["recent_stock_reports"]
    if not reports:
        return '<p class="empty">暂无单标的报告</p>'
    return "\n".join(
        f"""
        <a class="mini-link" href="{html.escape(item["href"])}">
          <span>{html.escape(item["symbol"])}</span>
          <strong>{html.escape(item["strategy"] or item["name"])}</strong>
          <em>{html.escape(item["time"])}</em>
        </a>
        """
        for item in reports
    )


def _build_theme_cards(data: dict[str, Any]) -> str:
    themes = data["theme_dashboards"]
    if not themes:
        return '<p class="empty">暂无题材看板</p>'

    cards = []
    for item in themes:
        href = html.escape(item["href"])
        board_link = (
            f'<a class="subtle-link primary" href="{href}">打开看板</a>'
            if href
            else '<span class="subtle-link muted">打开看板</span>'
        )
        detail_href = html.escape(item["detail_href"])
        detail_link = (
            f'<a class="subtle-link" href="{detail_href}">明细CSV</a>'
            if detail_href
            else '<span class="subtle-link muted">明细CSV</span>'
        )
        cards.append(
            f"""
            <article class="theme-card {html.escape(item["tone"])}">
              <div class="theme-top">
                <span>{html.escape(item["pool"])}</span>
                {_badge(item["exists"])}
              </div>
              <div class="theme-period">{html.escape(item["start"])} ~ {html.escape(item["end"])}</div>
              <div class="theme-main">
                <span>概念涨跌</span>
                <strong>{html.escape(item["concept_return"])}</strong>
              </div>
              <div class="theme-metrics">
                <div><span>平均涨跌</span><strong>{html.escape(item["avg_return"])}</strong></div>
                <div><span>上涨占比</span><strong>{html.escape(item["positive_ratio"])}</strong></div>
                <div><span>MA20上方</span><strong>{html.escape(item["trend_breadth"])}</strong></div>
                <div><span>20日新高</span><strong>{html.escape(item["new_high_ratio"])}</strong></div>
                <div><span>20日新低</span><strong>{html.escape(item["new_low_ratio"])}</strong></div>
                <div><span>离散度</span><strong>{html.escape(item["dispersion"])}</strong></div>
              </div>
              <div class="theme-foot">
                <span>{item["valid_count"]}/{item["stock_count"]} 只有效</span>
                <span>最强 {html.escape(item["best"])} {html.escape(item["best_return"])}</span>
              </div>
              <div class="theme-actions">
                {board_link}
                {detail_link}
              </div>
            </article>
            """
        )
    return "\n".join(cards)


def _build_etf_strategy_panel(data: dict[str, Any]) -> str:
    item = data.get("etf_strategy", {})
    href = item.get("href", "")
    summary_href = item.get("summary_href", "")
    report_link = _link_pill(href, "打开 ETF 策略板块", "primary")
    summary_link = _link_pill(summary_href, "ETF 汇总 CSV")
    return f"""
      <section id="etf" class="desk-section">
        <div class="section-head"><h2>ETF 策略板块</h2><span>ETF 择时 · 动量轮动 · 三因子轮动 · 外部红绿灯/排名</span></div>
        <article class="etf-panel">
          <div class="panel-title"><span>独立研究入口</span>{_badge(bool(item.get("exists")))}</div>
          <div class="etf-main">
            <div><span>覆盖 ETF</span><strong>{html.escape(str(item.get("count", 0)))}</strong></div>
            <div><span>最新日期</span><strong>{html.escape(str(item.get("date", "--")))}</strong></div>
            <div><span>MACD 买点</span><strong>{html.escape(str(item.get("macd_buy", 0)))}</strong></div>
            <div><span>20日最强</span><strong>{html.escape(str(item.get("leader_return", "--")))}</strong></div>
          </div>
          <div class="etf-leader">
            <span>领涨 ETF</span>
            <strong>{html.escape(str(item.get("leader", "--")))}</strong>
            <em>动量目标：{html.escape(str(item.get("momentum_targets", "--")))}</em>
          </div>
          <div class="theme-actions">{report_link}{summary_link}</div>
        </article>
      </section>
    """


def _stock_title_html(row: dict[str, Any], output_path: Path, config: dict | None, prefix: str = "") -> str:
    symbol = row.get("ts_code") or row.get("symbol") or ""
    name = str(row.get("name", "") or "")
    link = stock_link_html(config, output_path, symbol)
    title = f"{prefix}{link}".strip()
    if name:
        title = f"{title} {html.escape(name)}".strip()
    return title or html.escape(str(row))


def _mini_signal_rows(rows: list[dict[str, Any]], kind: str, output_path: Path, config: dict | None) -> str:
    if not rows:
        return '<p class="empty">暂无数据</p>'
    items = []
    for row in rows:
        if kind == "rps":
            title = _stock_title_html(row, output_path, config, prefix=f"{row.get('rank', '')}. ")
            value = f"RPS {row.get('rps', '--')} · {row.get('return_pct', '--')}%"
        elif kind == "pattern":
            title = _stock_title_html(row, output_path, config)
            value = f"{row.get('pattern_name', row.get('pattern', ''))} · {row.get('score', '--')}"
        elif kind == "screen":
            title = _stock_title_html(row, output_path, config)
            value = f"{row.get('preset_name', row.get('preset', ''))} · {row.get('score', '--')} · 距线{row.get('distance_pct', '--')}%"
        elif kind == "limit":
            title = _stock_title_html(row, output_path, config)
            value = f"{row.get('industry', '')} · {row.get('up_stat', '')}"
        elif kind == "radar":
            title = _stock_title_html(row, output_path, config)
            value = f"{row.get('state', '')} · RS60 {row.get('rs60_pct', '--')}"
        elif kind == "limit_strength":
            title = _stock_title_html(row, output_path, config)
            value = f"{row.get('所属题材', '')} · 评分 {row.get('综合评分', '--')} · {row.get('近期涨停数', '--')}板"
        else:
            title = html.escape(str(row))
            value = ""
        items.append(
            f"""
            <div class="signal-item">
              <span>{title}</span>
              <strong>{html.escape(str(value))}</strong>
            </div>
            """
        )
    return "\n".join(items)


def _primary_index(data: dict[str, Any]) -> dict[str, Any]:
    indexes = data.get("indexes", [])
    for wanted in ("000001.SH", "000300.SH", "399006.SZ"):
        for item in indexes:
            if item.get("symbol") == wanted and item.get("snapshot"):
                return item
    for item in indexes:
        if item.get("snapshot"):
            return item
    return indexes[0] if indexes else {"name": "--", "symbol": "--", "snapshot": {}}


def _tone_from_pct(text: str) -> str:
    if str(text).startswith("+"):
        return "up"
    if str(text).startswith("-"):
        return "down"
    return "flat"


def _link_pill(href: str, label: str, cls: str = "") -> str:
    safe_label = html.escape(label)
    if href:
        return f'<a class="link-pill {cls}" href="{html.escape(href)}">{safe_label}</a>'
    return f'<span class="link-pill muted {cls}">{safe_label}</span>'


def _stock_selector_link_pill(data: dict[str, Any], cls: str = "primary") -> str:
    selector = data.get("stock_selector") or {}
    if selector.get("viewer_exists") and selector.get("viewer_href"):
        return _link_pill(str(selector.get("viewer_href", "")), "股票查看器", cls)
    if selector.get("exists") and selector.get("href"):
        return _link_pill(str(selector.get("href", "")), "股票选择器", cls)
    return _link_pill("", "股票查看器", cls)


def _signal_total(center: dict[str, Any]) -> int:
    limit_summary = center.get("limit", {}).get("summary", {})
    limit_count = 0
    for key in ("up", "down", "opened"):
        try:
            limit_count += int(limit_summary.get(key, 0))
        except (TypeError, ValueError):
            pass
    return (
        len(center.get("rps", {}).get("rows", []))
        + len(center.get("patterns", {}).get("rows", []))
        + len(center.get("screens", {}).get("rows", []))
        + len(center.get("limit_strength", {}).get("rows", []))
        + limit_count
        + (1 if center.get("rotation", {}).get("exists") else 0)
        + len(center.get("radar", {}).get("rows", []))
    )


def _build_report_entry_section(data: dict[str, Any]) -> str:
    selector = data.get("stock_selector") or {}
    quality = data.get("data_quality") or {}
    quality_coverage = _fmt_ratio_pct(quality.get("latest_coverage"), 1)
    return f"""
    <section id="report-entry" class="desk-section report-entry-section">
      <div class="section-head"><h2>报告入口</h2><span>核心研究报告与常用工具</span></div>
      <article class="report-entry-panel">
        <div class="report-entry-main">
          {_link_pill(data.get("market_brief_href", ""), "市场结构摘录", "primary")}
          {_link_pill(data.get("industry_market_href", ""), "行业行情", "primary")}
          {_link_pill((data.get("signal_center") or {}).get("radar", {}).get("href", ""), "强势股雷达", "primary")}
          {_link_pill((data.get("signal_center") or {}).get("limit_strength", {}).get("href", ""), "涨停强势", "primary")}
          {_link_pill((data.get("support_resistance") or {}).get("href", ""), "支撑压力", "primary")}
          {_stock_selector_link_pill(data)}
        </div>
        <details class="report-entry-backup">
          <summary>备用报告入口</summary>
          <div class="report-entry-main report-entry-backup-links">
            {_link_pill(data.get("market_report_href", ""), "大盘环境")}
            {_link_pill(data.get("concept_market_href", ""), "概念行情")}
            {_link_pill((data.get("sector_money_flow") or {}).get("href", ""), "板块资金流")}
            {_link_pill(data.get("etf_strategy", {}).get("href", ""), "ETF 策略板块")}
            {_link_pill(data.get("forecast_report_href", ""), "完整市场结构")}
            {_link_pill(quality.get("href", ""), "数据质量")}
            {_link_pill((data.get("optimization_audit") or {}).get("href", ""), "项目优化审计")}
          </div>
        </details>
        <div class="report-entry-stats">
          <div><span>股票选择</span><strong>{html.escape(str(selector.get("count", 0)))}</strong></div>
          <div><span>K线页</span><strong>{html.escape(str(selector.get("kline_count", 0)))}</strong></div>
          <div><span>指数</span><strong>{len(data.get("indexes", []))}</strong></div>
          <div><span>题材</span><strong>{len(data.get("theme_dashboards", []))}</strong></div>
          <div><span>策略</span><strong>{len(data.get("strategies", []))}</strong></div>
          <div><span>个股报告</span><strong>{html.escape(str(data.get("stock_report_count", 0)))}</strong></div>
          <div><span>数据新鲜度</span><strong>{html.escape(quality_coverage)}</strong></div>
        </div>
      </article>
    </section>
    """


def _build_signal_stream(center: dict[str, Any], output_path: Path, config: dict | None) -> str:
    entries: list[dict[str, str]] = []
    for row in center.get("rps", {}).get("rows", [])[:4]:
        entries.append(
            {
                "kind": "RPS",
                "title": _stock_title_html(row, output_path, config, prefix=f"{row.get('rank', '')}. "),
                "meta": f"RPS {row.get('rps', '--')} / {row.get('return_pct', '--')}%",
                "tone": "up",
            }
        )
    for row in center.get("patterns", {}).get("rows", [])[:4]:
        entries.append(
            {
                "kind": "形态",
                "title": _stock_title_html(row, output_path, config),
                "meta": f"{row.get('pattern_name', row.get('pattern', ''))} / 评分 {row.get('score', '--')}",
                "tone": "watch",
            }
        )
    for row in center.get("screens", {}).get("rows", [])[:4]:
        entries.append(
            {
                "kind": "选股",
                "title": _stock_title_html(row, output_path, config),
                "meta": f"{row.get('preset_name', row.get('preset', ''))} / 评分 {row.get('score', '--')}",
                "tone": "watch",
            }
        )
    for row in center.get("radar", {}).get("rows", [])[:4]:
        state = str(row.get("state", ""))
        entries.append(
            {
                "kind": "雷达",
                "title": _stock_title_html(row, output_path, config),
                "meta": f"{state} / RS60 {row.get('rs60_pct', '--')}",
                "tone": "up" if state in {"CORE_STRONG", "ACCELERATING", "BREAKOUT"} else "watch",
            }
        )
    for row in center.get("limit_strength", {}).get("rows", [])[:4]:
        entries.append(
            {
                "kind": "涨停强势",
                "title": _stock_title_html(row, output_path, config),
                "meta": f"{row.get('所属题材', '--')} / 评分 {row.get('综合评分', '--')} / {row.get('新增/剔除状态', '')}",
                "tone": "up" if str(row.get("新增/剔除状态", "")) == "新增" else "watch",
            }
        )
    for row in center.get("limit", {}).get("rows", [])[:5]:
        limit_type = str(row.get("limit_type", ""))
        tone = "up" if limit_type == "U" else "down" if limit_type == "D" else "watch"
        entries.append(
            {
                "kind": "涨跌停",
                "title": _stock_title_html(row, output_path, config),
                "meta": f"{row.get('industry', '--')} / {row.get('up_stat', row.get('limit_type', '--'))}",
                "tone": tone,
            }
        )
    rotation = center.get("rotation", {}).get("summary", {})
    if center.get("rotation", {}).get("exists"):
        ret = str(rotation.get("return", "--"))
        entries.append(
            {
                "kind": "轮动",
                "title": html.escape(str(rotation.get("date", "--"))),
                "meta": f"{ret} / {rotation.get('holdings', '暂无持仓')}",
                "tone": _tone_from_pct(ret),
            }
        )
    if not entries:
        return '<p class="empty">暂无信号记录</p>'

    rows = []
    for item in entries[:12]:
        rows.append(
            f"""
            <div class="stream-row {html.escape(item["tone"])}">
              <span>{html.escape(item["kind"])}</span>
              <strong>{item["title"]}</strong>
              <em>{html.escape(item["meta"])}</em>
            </div>
            """
        )
    return "\n".join(rows)


def _build_signal_center(data: dict[str, Any]) -> str:
    center = data["signal_center"]
    limit_summary = center["limit"].get("summary", {})
    rotation = center["rotation"].get("summary", {})
    radar_summary = center.get("radar", {}).get("summary", {})
    output_path = Path(data.get("_output_path", "output/reports/dashboard.html"))
    config = {"output": {"reports_dir": data.get("_reports_dir", "output/reports")}}

    return f"""
    <div class="signal-workbench">
      <article class="signal-stream">
        <div class="panel-title"><span>信号流</span><strong>{_signal_total(center)}</strong></div>
        <div class="stream-list">{_build_signal_stream(center, output_path, config)}</div>
      </article>
      <div class="signal-grid">
        <article class="signal-card">
          <div class="signal-top"><span>RPS 强度</span>{_badge(center["rps"]["exists"])}</div>
          <div class="signal-list">{_mini_signal_rows(center["rps"]["rows"], "rps", output_path, config)}</div>
          <div class="theme-actions">{_link_pill(center["rps"].get("href", ""), "打开 RPS", "primary")}</div>
        </article>
        <article class="signal-card">
          <div class="signal-top"><span>形态扫描</span>{_badge(center["patterns"]["exists"])}</div>
          <div class="signal-list">{_mini_signal_rows(center["patterns"]["rows"], "pattern", output_path, config)}</div>
          <div class="theme-actions">{_link_pill(center["patterns"].get("href", ""), "打开形态", "primary")}</div>
        </article>
        <article class="signal-card">
          <div class="signal-top"><span>选股筛选</span>{_badge(center["screens"]["exists"])}</div>
          <div class="signal-list">{_mini_signal_rows(center["screens"]["rows"], "screen", output_path, config)}</div>
          <div class="theme-actions">{_link_pill(center["screens"].get("href", ""), "打开选股", "primary")}</div>
        </article>
        <article class="signal-card">
          <div class="signal-top"><span>强势股雷达</span>{_badge(center.get("radar", {}).get("exists", False))}</div>
          <div class="signal-stats">
            <div><span>核心</span><strong>{html.escape(str(radar_summary.get("core", "--")))}</strong></div>
            <div><span>加速</span><strong>{html.escape(str(radar_summary.get("accelerating", "--")))}</strong></div>
            <div><span>突破</span><strong>{html.escape(str(radar_summary.get("breakout", "--")))}</strong></div>
          </div>
          <div class="signal-list">{_mini_signal_rows(center.get("radar", {}).get("rows", []), "radar", output_path, config)}</div>
          <div class="theme-actions">{_link_pill(center.get("radar", {}).get("href", ""), "打开雷达", "primary")}</div>
        </article>
        <article class="signal-card">
          <div class="signal-top"><span>涨停强势</span>{_badge(center.get("limit_strength", {}).get("exists", False))}</div>
          <div class="signal-list">{_mini_signal_rows(center.get("limit_strength", {}).get("rows", []), "limit_strength", output_path, config)}</div>
          <div class="theme-actions">{_link_pill(center.get("limit_strength", {}).get("href", ""), "打开强势股", "primary")}</div>
        </article>
        <article class="signal-card">
          <div class="signal-top"><span>涨跌停</span>{_badge(center["limit"]["exists"])}</div>
          <div class="signal-stats">
            <div><span>涨停</span><strong>{html.escape(str(limit_summary.get("up", "--")))}</strong></div>
            <div><span>跌停</span><strong>{html.escape(str(limit_summary.get("down", "--")))}</strong></div>
            <div><span>炸板</span><strong>{html.escape(str(limit_summary.get("opened", "--")))}</strong></div>
          </div>
          <div class="signal-list">{_mini_signal_rows(center["limit"]["rows"], "limit", output_path, config)}</div>
          <div class="theme-actions">{_link_pill(center["limit"].get("href", ""), "打开涨跌停", "primary")}</div>
        </article>
        <article class="signal-card">
          <div class="signal-top"><span>轮动研究</span>{_badge(center["rotation"]["exists"])}</div>
          <div class="rotation-box">
            <span>{html.escape(str(rotation.get("date", "--")))}</span>
            <strong>{html.escape(str(rotation.get("return", "--")))}</strong>
            <p>{html.escape(str(rotation.get("holdings", "暂无持仓")) or "暂无持仓")}</p>
          </div>
          <div class="theme-actions">{_link_pill(center["rotation"].get("href", ""), "打开轮动", "primary")}</div>
        </article>
      </div>
    </div>
    """


def _build_stock_selector_panel(data: dict[str, Any]) -> str:
    selector = data.get("stock_selector", {}) or {}
    if not selector.get("enabled"):
        return """
        <section id="stock-selector" class="desk-section">
          <div class="section-head"><h2>股票选择器</h2><span>未配置股票选择 CSV</span></div>
          <article class="selector-panel"><p class="empty">在 config.yaml 配置 dashboard.stock_selector.csv_path 后启用。</p></article>
        </section>
        """
    if selector.get("error"):
        return f"""
        <section id="stock-selector" class="desk-section">
          <div class="section-head"><h2>股票选择器</h2><span>概念 / 行业 / 股票名称搜索</span></div>
          <article class="selector-panel"><p class="empty">{html.escape(str(selector.get("error")))}</p></article>
        </section>
        """
    count = int(selector.get("count") or 0)
    cache_count = int(selector.get("cache_count") or 0)
    kline_count = int(selector.get("kline_count") or 0)
    concept_chips = "".join(
        f'<button type="button" class="selector-chip" data-mode="concept" data-query="{html.escape(str(item.get("name", "")), quote=True)}">{html.escape(str(item.get("name", "")))}<span>{html.escape(str(item.get("count", 0)))}</span></button>'
        for item in selector.get("top_concepts", [])[:12]
    )
    industry_chips = "".join(
        f'<button type="button" class="selector-chip" data-mode="industry" data-query="{html.escape(str(item.get("name", "")), quote=True)}">{html.escape(str(item.get("name", "")))}<span>{html.escape(str(item.get("count", 0)))}</span></button>'
        for item in selector.get("top_industries", [])[:10]
    )
    return f"""
      <section id="stock-selector" class="desk-section">
        <div class="section-head"><h2>股票选择器</h2><span>概念板块 / 行业板块 / 股票名称搜索 · 点击打开 K 线</span></div>
        <article class="selector-panel">
          <div class="selector-top">
            <div>
              <strong>{count}</strong>
              <span>股票池：缓存 {cache_count} / K线页 {kline_count}</span>
            </div>
            <div class="selector-search">
              <input id="stock-selector-input" type="search" placeholder="输入概念、行业、股票简称或代码，比如 人工智能 / 半导体 / 平安银行" autocomplete="off">
              <button type="button" id="stock-selector-clear">清空</button>
            </div>
          </div>
          <div class="selector-modes">
            <button type="button" class="selector-mode active" data-mode="all">综合</button>
            <button type="button" class="selector-mode" data-mode="concept">概念板块</button>
            <button type="button" class="selector-mode" data-mode="industry">行业板块</button>
            <button type="button" class="selector-mode" data-mode="name">股票名称/代码</button>
            <button type="button" class="selector-mode" data-mode="custom">自定义板块</button>
          </div>
          <div class="selector-chips">{concept_chips}{industry_chips}</div>
          <div class="selector-custom">
            <div class="selector-custom-head">
              <strong>自定义板块</strong>
              <span id="selector-custom-status">浏览器本地保存；先新建/选择板块，再在股票行里加入。</span>
            </div>
            <div class="selector-custom-actions">
              <input id="selector-custom-name" type="text" placeholder="输入板块名，比如 我的机器人 / 算力观察池" autocomplete="off">
              <button type="button" id="selector-custom-create">新建/选择</button>
              <button type="button" id="selector-custom-view">只看当前板块</button>
              <button type="button" id="selector-custom-all">返回全部</button>
              <button type="button" id="selector-custom-import-btn">导入JSON</button>
              <button type="button" id="selector-custom-export">导出JSON</button>
              <button type="button" id="selector-custom-delete">删除当前板块</button>
              <input id="selector-custom-import" type="file" accept="application/json,.json">
            </div>
            <div id="selector-custom-boards" class="selector-custom-boards"></div>
          </div>
          <div class="selector-result-head">
            <span id="stock-selector-summary">输入关键词开始筛选</span>
            <div class="selector-sort">
              <em>排序</em>
              <button type="button" class="selector-sort-btn active" data-sort="match">匹配顺序</button>
              <button type="button" class="selector-sort-btn" data-sort="name">名称</button>
              <button type="button" class="selector-sort-btn" data-sort="pct1d">1日涨幅</button>
              <button type="button" class="selector-sort-btn" data-sort="pct5d">5日涨幅</button>
              <button type="button" class="selector-sort-btn" data-sort="marketcap">市值</button>
            </div>
          </div>
          <div id="stock-selector-results" class="selector-results"></div>
        </article>
      </section>
    """


def _build_stock_selector_entry(data: dict[str, Any]) -> str:
    selector = data.get("stock_selector", {}) or {}
    count = int(selector.get("count") or 0)
    cache_count = int(selector.get("cache_count") or 0)
    kline_count = int(selector.get("kline_count") or 0)
    href = html.escape(str(selector.get("href", "")), quote=True)
    exists = bool(selector.get("exists"))
    if selector.get("error"):
        body = f'<p class="empty">{html.escape(str(selector.get("error")))}</p>'
        action = '<span class="link-pill muted">选择器不可用</span>'
    elif not selector.get("enabled"):
        body = '<p class="empty">未配置股票选择 CSV。</p>'
        action = '<span class="link-pill muted">未启用</span>'
    else:
        top_concepts = "、".join(str(item.get("name", "")) for item in selector.get("top_concepts", [])[:5] if item.get("name")) or "--"
        top_industries = "、".join(str(item.get("name", "")) for item in selector.get("top_industries", [])[:5] if item.get("name")) or "--"
        viewer_href = html.escape(str(selector.get("viewer_href") or selector.get("href", "")), quote=True)
        selector_href = html.escape(str(selector.get("selector_href") or selector.get("href", "")), quote=True)
        body = f"""
          <div class="selector-entry-grid">
            <div><span>股票数</span><strong>{count}</strong></div>
            <div><span>本地缓存</span><strong>{cache_count}</strong></div>
            <div><span>K线页</span><strong>{kline_count}</strong></div>
          </div>
          <p class="selector-entry-note">热门概念：{html.escape(top_concepts)}</p>
          <p class="selector-entry-note">热门行业：{html.escape(top_industries)}</p>
        """
        action = (
            f'<a class="link-pill primary" href="{viewer_href}">打开股票查看器</a>'
            + (f'<a class="link-pill" href="{selector_href}">股票选择器</a>' if selector_href and selector_href != viewer_href else "")
            if viewer_href
            else '<span class="link-pill muted primary">待生成</span>'
        )
    return f"""
      <section id="stock-selector" class="desk-section">
        <div class="section-head"><h2>股票查看器</h2><span>独立页面 · 搜索 / 我的板块 / K线即时切换</span></div>
        <article class="selector-entry-card">
          <div class="panel-title"><span>股票查看入口</span>{_badge(exists)}</div>
          {body}
          <div class="theme-actions">{action}</div>
        </article>
      </section>
    """


def _stock_selector_page_styles() -> str:
    return """
    :root {
      --ink: #202631;
      --muted: #657084;
      --line: #d5dde8;
      --paper: #eef2f4;
      --panel: #ffffff;
      --soft: #f7f9fb;
      --blue: #2d6cdf;
      --green: #15805d;
      --red: #c84545;
      --shadow: 0 12px 28px rgba(31, 41, 55, .10);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      background: var(--paper);
      font-family: "Microsoft YaHei", "Noto Sans SC", "PingFang SC", sans-serif;
      font-size: 14px;
    }
    a { color: inherit; text-decoration: none; }
    .selector-page { width:min(1660px, calc(100vw - 28px)); margin:0 auto; padding:18px 0 32px; }
    .selector-head {
      display:flex; justify-content:space-between; gap:14px; align-items:flex-start;
      background:var(--panel); border:1px solid var(--line); border-radius:10px;
      padding:16px 18px; margin-bottom:14px;
    }
    h1 { margin:0; font-size:28px; line-height:1.18; }
    .subtitle { margin:6px 0 0; color:var(--muted); font-size:13px; }
    .link-pill {
      display:inline-flex; align-items:center; justify-content:center; min-height:34px;
      border:1px solid var(--line); border-radius:7px; padding:0 11px;
      background:var(--soft); color:var(--ink); font-size:12px; font-weight:900;
      white-space:nowrap;
    }
    .link-pill.primary { color:#fff; background:var(--blue); border-color:#245ac0; }
    .empty { color:var(--muted); margin:0; }
    .selector-panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 14px;
      box-shadow: 0 1px 2px rgba(31, 41, 55, .04);
    }
    .selector-top {
      display: grid;
      grid-template-columns: 230px minmax(0, 1fr);
      gap: 12px;
      align-items: center;
    }
    .selector-top strong { display:block; font-size:30px; line-height:1; }
    .selector-top span { display:block; color:var(--muted); font-size:12px; margin-top:5px; }
    .selector-search { display:grid; grid-template-columns:minmax(0, 1fr) 72px; gap:8px; }
    .selector-search input {
      width:100%; min-height:40px; border:1px solid var(--line); border-radius:8px;
      padding:0 12px; font:inherit; background:#fbfcfe; outline:none;
    }
    .selector-search input:focus { border-color:#9db5d8; box-shadow:0 0 0 3px rgba(45,108,223,.10); }
    .selector-search button, .selector-mode, .selector-chip, .selector-sort-btn, .selector-custom button, .selector-board-chip, .selector-add-board {
      border:1px solid var(--line); border-radius:999px; background:#f7f9fb;
      color:var(--ink); font:inherit; font-size:12px; font-weight:900; cursor:pointer;
    }
    .selector-search button { border-radius:8px; }
    .selector-modes { display:flex; flex-wrap:wrap; gap:8px; margin:12px 0 10px; }
    .selector-mode { min-height:30px; padding:0 12px; }
    .selector-mode.active { background:var(--blue); border-color:#245ac0; color:white; }
    .selector-chips { display:flex; flex-wrap:wrap; gap:7px; padding:10px 0; border-top:1px solid var(--line); border-bottom:1px solid var(--line); }
    .selector-chip { min-height:28px; padding:0 10px; }
    .selector-chip span { margin-left:5px; color:var(--muted); font-weight:800; }
    .selector-chip:hover { border-color:#9db5d8; background:#eef5ff; }
    .selector-custom {
      margin:10px 0;
      border:1px solid var(--line);
      border-radius:9px;
      background:#fbfcfe;
      padding:10px;
    }
    .selector-custom-head { display:flex; justify-content:space-between; gap:10px; align-items:center; margin-bottom:8px; }
    .selector-custom-head strong { font-size:13px; }
    .selector-custom-head span { color:var(--muted); font-size:12px; }
    .selector-custom-actions { display:grid; grid-template-columns:minmax(180px, 1fr) repeat(6, auto); gap:8px; align-items:center; }
    .selector-custom-actions input {
      width:100%; min-height:34px; border:1px solid var(--line); border-radius:8px;
      padding:0 10px; font:inherit; background:#fff; outline:none;
    }
    .selector-custom-actions input:focus { border-color:#9db5d8; box-shadow:0 0 0 3px rgba(45,108,223,.10); }
    .selector-custom-actions button { min-height:34px; padding:0 11px; border-radius:8px; }
    .selector-custom-actions #selector-custom-create { background:var(--blue); border-color:#245ac0; color:#fff; }
    .selector-custom-actions #selector-custom-delete { color:#a13c3c; }
    #selector-custom-import { display:none; }
    .selector-custom-boards { display:flex; flex-wrap:wrap; gap:7px; margin-top:8px; min-height:28px; }
    .selector-board-chip { min-height:28px; padding:0 10px; }
    .selector-board-chip span { margin-left:5px; color:var(--muted); font-weight:800; }
    .selector-board-chip.active { background:#202631; color:#fff; border-color:#202631; }
    .selector-board-chip.active span { color:#d7deea; }
    .selector-result-head { display:flex; justify-content:space-between; gap:12px; align-items:center; color:var(--muted); font-size:12px; margin:10px 0; }
    .selector-result-head span { font-weight:900; color:var(--ink); }
    .selector-result-head em { font-style:normal; }
    .selector-sort { display:flex; align-items:center; justify-content:flex-end; gap:6px; flex-wrap:wrap; }
    .selector-sort-btn { min-height:26px; padding:0 9px; }
    .selector-sort-btn.active { background:#202631; color:white; border-color:#202631; }
    .selector-results { display:grid; gap:7px; max-height:calc(100vh - 390px); min-height:360px; overflow:auto; padding-right:4px; }
    .selector-row {
      display:grid;
      grid-template-columns: 176px minmax(130px,.62fr) minmax(230px,1.15fr) 150px 248px;
      gap:10px; align-items:center; border:1px solid var(--line); border-radius:8px;
      background:#fbfcfe; padding:10px; transition:transform .14s ease, box-shadow .14s ease, border-color .14s ease;
    }
    .selector-row:hover { transform:translateY(-1px); box-shadow:0 8px 18px rgba(31,41,55,.08); border-color:#aeb9c7; }
    .selector-stock strong { display:block; font-size:14px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .selector-stock span { display:block; color:var(--muted); margin-top:2px; font-size:12px; font-weight:800; direction:ltr; unicode-bidi:isolate; }
    .selector-tags { display:flex; flex-wrap:wrap; gap:5px; max-height:50px; overflow:hidden; }
    .selector-tags span { display:inline-flex; align-items:center; min-height:22px; padding:0 7px; border:1px solid var(--line); border-radius:999px; color:var(--muted); background:#fff; font-size:11px; font-weight:800; }
    .selector-tags.concept span { color:#496079; }
    .selector-tags span.selector-tag-hit { border-color:#f0b04d; color:#8a5200; background:#fff4df; }
    .selector-tags em { color:var(--muted); font-size:12px; font-style:normal; }
    .selector-metrics { display:grid; grid-template-columns:repeat(2, minmax(0,1fr)); gap:4px 10px; text-align:right; }
    .selector-metrics strong { display:block; grid-column:1 / -1; font-size:14px; }
    .selector-metrics span { display:block; font-size:12px; font-weight:900; }
    .selector-metrics small { display:block; color:var(--muted); font-size:11px; font-weight:800; }
    .selector-metrics .up { color:var(--red); }
    .selector-metrics .down { color:var(--green); }
    .selector-metrics .flat { color:var(--muted); }
    .selector-metrics .mv { grid-column:1 / -1; color:var(--muted); }
    .selector-open {
      display:inline-flex; align-items:center; justify-content:center; min-height:30px;
      border-radius:7px; background:var(--blue); color:white; font-size:12px; font-weight:900;
    }
    .selector-open.disabled { background:#edf1f6; color:var(--muted); border:1px solid var(--line); }
    .selector-row-actions { display:grid; grid-template-columns:minmax(86px,1fr) 68px 72px; gap:7px; align-items:center; }
    .selector-board-target {
      width:100%; min-height:30px; border:1px solid var(--line); border-radius:7px;
      padding:0 8px; background:#fff; color:var(--ink); font:inherit; font-size:12px; font-weight:900;
    }
    .selector-add-board { min-height:30px; padding:0 8px; border-radius:7px; color:#2d4d7d; background:#eef5ff; }
    .selector-add-board.in-board { color:#7a4e00; background:#fff4df; border-color:#efbf73; }
    .selector-add-board.disabled { color:var(--muted); background:#edf1f6; }
    [aria-disabled="true"] { cursor: default; pointer-events: none; opacity: .62; }
    @media (max-width: 1180px) {
      .selector-top { grid-template-columns:1fr; }
      .selector-row { grid-template-columns:1fr 1fr; }
    }
    @media (max-width: 720px) {
      .selector-page { width:min(100vw - 20px, 1660px); padding-top:10px; }
      .selector-head, .selector-search, .selector-row { grid-template-columns:1fr; display:grid; }
      h1 { font-size:24px; }
    }
    """


def _stock_selector_script(element_id: str = "stock-selector-data") -> str:
    return inline_script(
        f"""
(function(){{
  var raw=document.getElementById('{element_id}');
  var stockSelector=raw?JSON.parse(raw.textContent||'{{}}'):{{}};
  var selectorRows=stockSelector.rows||[];
  function esc(text){{return String(text==null?'':text).replace(/[&<>"']/g,function(ch){{return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch];}});}}
  function pctText(v){{var n=Number(v);if(!isFinite(n))return'--';return(n>=0?'+':'')+n.toFixed(2)+'%';}}
  function priceText(v){{var n=Number(v);if(!isFinite(n))return'--';return n.toFixed(2);}}
  function mvText(v){{
    if(v==null||v==='')return'市值 --';
    var n=Number(v);if(!isFinite(n))return'市值 --';
    if(Math.abs(n)>=100000000)return'市值 '+(n/100000000).toFixed(2)+'万亿';
    if(Math.abs(n)>=10000)return'市值 '+(n/10000).toFixed(2)+'亿';
    return'市值 '+n.toFixed(0)+'万';
  }}
  function pctTone(v){{var n=Number(v);if(!isFinite(n)||n===0)return'flat';return n>0?'up':'down';}}
  var selectorMode='all';
  var selectorSort='match';
  var selectorBatchSize=80;
  var selectorRenderState={{matched:[],query:'',rendered:0,version:0}};
  var selectorDebounceTimer=null;
  var selectorScrollTicking=false;
  var selectorCustomKey='quantyb:stock_selector_custom_boards:v1';
  var selectorFileCustomBoards=normalizeCustomBoards(stockSelector.custom_boards||{{}});
  var selectorCustomBoardsPath=stockSelector.custom_boards_path||'';
  var selectorCustomState=loadCustomBoards();
  var selectorActiveBoard=selectorCustomState.active||'';
  var selectorRowsBySymbol={{}};
  function norm(text){{return String(text==null?'':text).trim().toLowerCase();}}
  selectorRows.forEach(function(row,idx){{row._rank=idx;if(row.symbol)selectorRowsBySymbol[row.symbol]=row;}});
  function normalizeCustomBoards(input){{
    var boards={{}};
    var source=input&&typeof input==='object'&&input.boards&&typeof input.boards==='object'?input.boards:input;
    if(!source||typeof source!=='object')return boards;
    Object.keys(source).forEach(function(name){{
      var boardName=String(name||'').trim();
      if(!boardName)return;
      var raw=source[name];
      var stocks=Array.isArray(raw)?raw:(raw&&Array.isArray(raw.stocks)?raw.stocks:(raw&&Array.isArray(raw.symbols)?raw.symbols:[]));
      var seen={{}};
      boards[boardName]={{name:boardName,stocks:[]}};
      stocks.forEach(function(item){{
        var symbol=typeof item==='object'&&item?String(item.symbol||item.ts_code||item.code||'').trim().toUpperCase():String(item||'').trim().toUpperCase();
        if(symbol&&!seen[symbol]){{boards[boardName].stocks.push(symbol);seen[symbol]=1;}}
      }});
    }});
    return boards;
  }}
  function cloneCustomBoards(boards){{
    var out={{}};
    Object.keys(boards||{{}}).forEach(function(name){{
      var board=boards[name]||{{}};
      out[name]={{name:board.name||name,stocks:Array.isArray(board.stocks)?board.stocks.slice():[]}};
    }});
    return out;
  }}
  function mergeCustomBoardInto(target,name,board){{
    if(!name||!board)return;
    if(!target[name])target[name]={{name:name,stocks:[]}};
    var seen={{}};
    target[name].stocks.forEach(function(symbol){{seen[symbol]=1;}});
    (Array.isArray(board.stocks)?board.stocks:[]).forEach(function(symbol){{
      symbol=String(symbol||'').trim().toUpperCase();
      if(symbol&&!seen[symbol]){{target[name].stocks.push(symbol);seen[symbol]=1;}}
    }});
  }}
  function loadCustomBoards(){{
    try{{
      var parsed=JSON.parse(localStorage.getItem(selectorCustomKey)||'{{}}')||{{}};
      var boards=cloneCustomBoards(selectorFileCustomBoards);
      var localBoards=parsed.boards&&typeof parsed.boards==='object'?parsed.boards:{{}};
      Object.keys(localBoards).forEach(function(name){{mergeCustomBoardInto(boards,name,localBoards[name]);}});
      Object.keys(boards).forEach(function(name){{
        var board=boards[name]||{{}};
        board.name=board.name||name;
        board.stocks=Array.isArray(board.stocks)?board.stocks.filter(Boolean):[];
        boards[name]=board;
      }});
      var names=Object.keys(boards).sort(function(a,b){{return a.localeCompare(b,'zh-Hans-CN');}});
      return {{active:parsed.active||names[0]||'',boards:boards}};
    }}catch(err){{
      var fallback=cloneCustomBoards(selectorFileCustomBoards);
      var fallbackNames=Object.keys(fallback).sort(function(a,b){{return a.localeCompare(b,'zh-Hans-CN');}});
      return {{active:fallbackNames[0]||'',boards:fallback}};
    }}
  }}
  function saveCustomBoards(){{
    try{{localStorage.setItem(selectorCustomKey,JSON.stringify(selectorCustomState));}}catch(err){{}}
  }}
  function getActiveBoard(){{
    if(!selectorActiveBoard)return null;
    return selectorCustomState.boards[selectorActiveBoard]||null;
  }}
  function boardHasSymbol(name,symbol){{
    var board=name?selectorCustomState.boards[name]:null;
    return !!(board&&Array.isArray(board.stocks)&&board.stocks.indexOf(symbol)>=0);
  }}
  function activeBoardHas(row){{return !!(row&&row.symbol&&selectorActiveBoard&&boardHasSymbol(selectorActiveBoard,row.symbol));}}
  function customBoardNames(){{
    return Object.keys(selectorCustomState.boards||{{}}).sort(function(a,b){{return a.localeCompare(b,'zh-Hans-CN');}});
  }}
  function targetBoardForRow(row){{
    var names=customBoardNames();
    if(selectorActiveBoard&&selectorCustomState.boards[selectorActiveBoard])return selectorActiveBoard;
    return names[0]||'';
  }}
  function boardOptionsHtml(selected){{
    var names=customBoardNames();
    if(!names.length)return '<option value="">先建板块</option>';
    return names.map(function(name){{
      return '<option value="'+esc(name)+'" '+(name===selected?'selected':'')+'>'+esc(name)+'</option>';
    }}).join('');
  }}
  function setSelectorMode(mode){{
    selectorMode=mode||'all';
    document.querySelectorAll('.selector-mode').forEach(function(x){{x.classList.toggle('active',x.getAttribute('data-mode')===selectorMode);}});
  }}
  function rowText(row){{
    if(selectorMode==='custom')return row.search_text||'';
    if(selectorMode==='concept')return row.concept_text||'';
    if(selectorMode==='industry')return row.industry_text||'';
    if(selectorMode==='name')return row.name_text||'';
    return row.search_text||'';
  }}
  function matchSelector(row,query){{
    if(selectorMode==='custom'&&(!selectorActiveBoard||!boardHasSymbol(selectorActiveBoard,row.symbol)))return false;
    if(!query)return true;
    var q=String(query||'').trim().toLowerCase();
    if(!q)return true;
    return rowText(row).indexOf(q)>=0;
  }}
  function numericValue(row,key){{
    if(row[key]==null||row[key]==='')return null;
    var n=Number(row[key]);
    return isFinite(n)?n:null;
  }}
  function compareText(a,b){{
    return String(a.name||a.symbol||'').localeCompare(String(b.name||b.symbol||''),'zh-Hans-CN');
  }}
  function sortRows(rows){{
    var out=rows.slice();
    if(selectorSort==='name'){{
      out.sort(function(a,b){{return compareText(a,b)||((a._rank||0)-(b._rank||0));}});
      return out;
    }}
    var key=null;
    if(selectorSort==='pct1d')key='pct_chg';
    if(selectorSort==='pct5d')key='pct_5d';
    if(selectorSort==='marketcap')key='market_cap';
    if(key){{
      out.sort(function(a,b){{
        var av=numericValue(a,key), bv=numericValue(b,key);
        if(av==null&&bv==null)return (a._rank||0)-(b._rank||0);
        if(av==null)return 1;
        if(bv==null)return -1;
        return (bv-av)||((a._rank||0)-(b._rank||0));
      }});
      return out;
    }}
    return out.sort(function(a,b){{return (a._rank||0)-(b._rank||0);}});
  }}
  function rankTags(tags,query,limit){{
    var q=norm(query);
    var seen={{}}, hits=[], rest=[];
    (tags||[]).forEach(function(tag){{
      var key=String(tag||'');
      if(!key||seen[key])return;
      seen[key]=1;
      if(q&&norm(key).indexOf(q)>=0)hits.push(key);else rest.push(key);
    }});
    return hits.concat(rest).slice(0,limit).map(function(tag){{return {{name:tag,hit:q&&norm(tag).indexOf(q)>=0}};}});
  }}
  function tagHtml(tags,query,limit){{
    return rankTags(tags,query,limit).map(function(item){{
      return '<span class="'+(item.hit?'selector-tag-hit':'')+'">'+esc(item.name)+'</span>';
    }}).join('');
  }}
  function customBoardCount(name){{
    var board=name?selectorCustomState.boards[name]:null;
    return board&&Array.isArray(board.stocks)?board.stocks.length:0;
  }}
  function renderCustomBoards(){{
    var box=document.getElementById('selector-custom-boards');
    var status=document.getElementById('selector-custom-status');
    var names=Object.keys(selectorCustomState.boards||{{}}).sort(function(a,b){{return a.localeCompare(b,'zh-Hans-CN');}});
    if(selectorActiveBoard&&!selectorCustomState.boards[selectorActiveBoard])selectorActiveBoard='';
    selectorCustomState.active=selectorActiveBoard;
    if(box){{
      box.innerHTML=names.length?names.map(function(name){{
        return '<button type="button" class="selector-board-chip '+(name===selectorActiveBoard?'active':'')+'" data-board="'+esc(name)+'">'+esc(name)+'<span>'+customBoardCount(name)+'</span></button>';
      }}).join(''):'<span class="empty">还没有自定义板块。</span>';
    }}
  if(status){{
      var sourceText=selectorCustomBoardsPath?' · 文件 '+selectorCustomBoardsPath:'';
      status.textContent=selectorActiveBoard
        ? '当前板块：'+selectorActiveBoard+' · '+customBoardCount(selectorActiveBoard)+' 只 · 浏览器本地保存'+sourceText
        : '浏览器本地保存；先新建/选择板块，再在股票行里加入。'+sourceText;
    }}
  }}
  function selectorScrollSnapshot(){{
    var list=document.getElementById('stock-selector-results');
    return {{windowX:window.scrollX||0,windowY:window.scrollY||0,listTop:list?list.scrollTop:0}};
  }}
  function restoreSelectorScroll(snapshot){{
    if(!snapshot)return;
    var restore=function(){{
      var list=document.getElementById('stock-selector-results');
      if(list)list.scrollTop=snapshot.listTop||0;
      window.scrollTo(snapshot.windowX||0,snapshot.windowY||0);
    }};
    restore();
    if(window.requestAnimationFrame)window.requestAnimationFrame(restore);
    else window.setTimeout(restore,0);
  }}
  function createOrSelectCustomBoard(){{
    var input=document.getElementById('selector-custom-name');
    var name=input?String(input.value||'').trim():'';
    if(!name){{if(input)input.focus();return;}}
    if(!selectorCustomState.boards[name])selectorCustomState.boards[name]={{name:name,created_at:new Date().toISOString(),stocks:[]}};
    selectorActiveBoard=name;
    selectorCustomState.active=name;
    saveCustomBoards();
    renderCustomBoards();
    renderSelector();
  }}
  function toggleStockInBoard(symbol,boardName,preserveScroll){{
    var scrollState=preserveScroll?selectorScrollSnapshot():null;
    boardName=String(boardName||'').trim();
    if(!boardName){{
      var input=document.getElementById('selector-custom-name');
      if(input)input.focus();
      return;
    }}
    var board=selectorCustomState.boards[boardName];
    if(!board){{board=selectorCustomState.boards[boardName]={{name:boardName,created_at:new Date().toISOString(),stocks:[]}};}}
    var idx=board.stocks.indexOf(symbol);
    if(idx>=0)board.stocks.splice(idx,1);
    else board.stocks.push(symbol);
    selectorActiveBoard=boardName;
    selectorCustomState.active=boardName;
    saveCustomBoards();
    renderCustomBoards();
    renderSelector();
    restoreSelectorScroll(scrollState);
  }}
  function deleteActiveCustomBoard(){{
    if(!selectorActiveBoard)return;
    if(!window.confirm('删除自定义板块「'+selectorActiveBoard+'」？股票本身不会删除。'))return;
    delete selectorCustomState.boards[selectorActiveBoard];
    var names=Object.keys(selectorCustomState.boards||{{}}).sort(function(a,b){{return a.localeCompare(b,'zh-Hans-CN');}});
    selectorActiveBoard=names[0]||'';
    selectorCustomState.active=selectorActiveBoard;
    if(!selectorActiveBoard&&selectorMode==='custom')setSelectorMode('all');
    saveCustomBoards();
    renderCustomBoards();
    renderSelector();
  }}
  function importCustomBoardsFromText(text){{
    var imported;
    try{{imported=normalizeCustomBoards(JSON.parse(text||'{{}}'));}}
    catch(err){{window.alert('JSON 解析失败：'+err.message);return;}}
    var names=Object.keys(imported);
    if(!names.length){{window.alert('这个 JSON 里没有可用板块。');return;}}
    names.forEach(function(name){{mergeCustomBoardInto(selectorCustomState.boards,name,imported[name]);}});
    if(!selectorActiveBoard||!selectorCustomState.boards[selectorActiveBoard])selectorActiveBoard=names[0];
    selectorCustomState.active=selectorActiveBoard;
    saveCustomBoards();
    renderCustomBoards();
    renderSelector();
  }}
  function exportCustomBoards(){{
    var payload={{}};
    customBoardNames().forEach(function(name){{
      payload[name]=(selectorCustomState.boards[name].stocks||[]).slice();
    }});
    var blob=new Blob([JSON.stringify(payload,null,2)],{{type:'application/json;charset=utf-8'}});
    var url=URL.createObjectURL(blob);
    var a=document.createElement('a');
    a.href=url;
    a.download='stock_selector_custom_boards.json';
    document.body.appendChild(a);
    a.click();
    setTimeout(function(){{URL.revokeObjectURL(url);a.remove();}},0);
  }}
  function selectorRowHtml(row,query){{
    var concepts=tagHtml(row.concepts||[],query,8);
    var industries=tagHtml(row.industry_tags||[],query,5);
    var toneCls=pctTone(row.pct_chg);
    var pct1Tone=pctTone(row.pct_chg);
    var pct5Tone=pctTone(row.pct_5d);
    var href=row.href||'#';
    var klineLabel=row.kline_exists?'打开K线':(row.cache_exists?'打开/待生成':'缺缓存');
    var disabled=!row.cache_exists&&!row.kline_exists;
    var targetBoard=targetBoardForRow(row);
    var inBoard=targetBoard&&boardHasSymbol(targetBoard,row.symbol);
    var boardDisabled=!targetBoard;
    var boardLabel=boardDisabled?'先选板块':(inBoard?'移出板块':'加入板块');
    return '<div class="selector-row '+toneCls+'" data-href="'+esc(href)+'" data-disabled="'+(disabled?'1':'0')+'">'
      +'<div class="selector-stock"><strong>'+esc(row.name||'--')+'</strong><span>'+esc(row.symbol||'')+'</span></div>'
      +'<div class="selector-tags industry">'+(industries||'<em>--</em>')+'</div>'
      +'<div class="selector-tags concept">'+(concepts||'<em>--</em>')+'</div>'
      +'<div class="selector-metrics"><strong>'+priceText(row.price)+'</strong><span class="'+pct1Tone+'"><small>1日</small>'+pctText(row.pct_chg)+'</span><span class="'+pct5Tone+'"><small>5日</small>'+pctText(row.pct_5d)+'</span><span class="mv">'+mvText(row.market_cap)+'</span></div>'
      +'<div class="selector-row-actions"><select class="selector-board-target" data-symbol="'+esc(row.symbol||'')+'">'+boardOptionsHtml(targetBoard)+'</select><button type="button" class="selector-add-board '+(inBoard?'in-board':'')+' '+(boardDisabled?'disabled':'')+'" data-symbol="'+esc(row.symbol||'')+'" data-board="'+esc(targetBoard)+'" '+(boardDisabled?'disabled':'')+'>'+esc(boardLabel)+'</button><a class="selector-open '+(disabled?'disabled':'')+'" href="'+esc(href)+'" target="_blank" '+(disabled?'aria-disabled="true"':'')+'>'+esc(klineLabel)+'</a></div>'
      +'</div>';
  }}
  function updateSelectorSummary(){{
    var summary=document.getElementById('stock-selector-summary');
    if(!summary)return;
    var total=selectorRenderState.matched.length;
    var shown=Math.min(selectorRenderState.rendered,total);
    var q=selectorRenderState.query;
    var scope=selectorMode==='custom'
      ? (selectorActiveBoard?'自定义板块「'+selectorActiveBoard+'」':'自定义板块（未选择）')
      : (q?'“'+q+'”':'全部');
    summary.textContent=scope+' · 匹配 '+total+' 只，已加载 '+shown+'/'+total+(shown<total?'，滚动继续加载':'，已全部显示');
  }}
  function appendSelectorRows(){{
    var list=document.getElementById('stock-selector-results');
    if(!list)return;
    var total=selectorRenderState.matched.length;
    var start=selectorRenderState.rendered;
    if(start>=total)return;
    var end=Math.min(total,start+selectorBatchSize);
    var html=selectorRenderState.matched.slice(start,end).map(function(row){{return selectorRowHtml(row,selectorRenderState.query);}}).join('');
    list.insertAdjacentHTML('beforeend',html);
    selectorRenderState.rendered=end;
    updateSelectorSummary();
  }}
  function renderSelector(){{
    var input=document.getElementById('stock-selector-input');
    var list=document.getElementById('stock-selector-results');
    if(!list)return;
    var q=input?input.value.trim():'';
    var matched=sortRows(selectorRows.filter(function(row){{return matchSelector(row,q);}}));
    selectorRenderState={{matched:matched,query:q,rendered:0,version:selectorRenderState.version+1}};
    list.scrollTop=0;
    list.innerHTML=matched.length?'':'<p class="empty">没有匹配股票，换个关键词试试。</p>';
    updateSelectorSummary();
    appendSelectorRows();
  }}
  function scheduleSelectorRender(delay){{
    if(selectorDebounceTimer)window.clearTimeout(selectorDebounceTimer);
    selectorDebounceTimer=window.setTimeout(renderSelector,delay==null?120:delay);
  }}
  function refreshRowBoardAction(selectEl){{
    var rowEl=selectEl&&selectEl.closest?selectEl.closest('.selector-row'):null;
    if(!rowEl)return;
    var btn=rowEl.querySelector('.selector-add-board');
    if(!btn)return;
    var symbol=selectEl.getAttribute('data-symbol')||btn.getAttribute('data-symbol')||'';
    var boardName=selectEl.value||'';
    var inBoard=boardName&&boardHasSymbol(boardName,symbol);
    btn.setAttribute('data-board',boardName);
    btn.disabled=!boardName;
    btn.classList.toggle('disabled',!boardName);
    btn.classList.toggle('in-board',!!inBoard);
    btn.textContent=!boardName?'先选板块':(inBoard?'移出板块':'加入板块');
  }}
  var selectorInput=document.getElementById('stock-selector-input');
  if(selectorInput){{selectorInput.addEventListener('input',function(){{scheduleSelectorRender(120);}});}}
  var selectorList=document.getElementById('stock-selector-results');
  if(selectorList){{
    selectorList.addEventListener('click',function(evt){{
      var addBtn=evt.target&&evt.target.closest?evt.target.closest('.selector-add-board'):null;
      if(!addBtn)return;
      evt.preventDefault();
      evt.stopPropagation();
      if(addBtn.disabled)return;
      var rowEl=addBtn.closest?addBtn.closest('.selector-row'):null;
      var target=rowEl?rowEl.querySelector('.selector-board-target'):null;
      var boardName=target?target.value:(addBtn.getAttribute('data-board')||selectorActiveBoard||'');
      toggleStockInBoard(addBtn.getAttribute('data-symbol')||'',boardName,true);
    }});
    selectorList.addEventListener('change',function(evt){{
      var selectEl=evt.target&&evt.target.closest?evt.target.closest('.selector-board-target'):null;
      if(!selectEl)return;
      refreshRowBoardAction(selectEl);
    }});
    selectorList.addEventListener('dblclick',function(evt){{
      var rowEl=evt.target&&evt.target.closest?evt.target.closest('.selector-row'):null;
      if(!rowEl||rowEl.getAttribute('data-disabled')==='1')return;
      var href=rowEl.getAttribute('data-href');if(href&&href!=='#')window.open(href,'_blank');
    }});
    selectorList.addEventListener('scroll',function(){{
      if(selectorScrollTicking)return;
      selectorScrollTicking=true;
      window.requestAnimationFrame(function(){{
        selectorScrollTicking=false;
        if(selectorList.scrollTop+selectorList.clientHeight>=selectorList.scrollHeight-260)appendSelectorRows();
      }});
    }});
  }}
  var selectorClear=document.getElementById('stock-selector-clear');
  if(selectorClear){{selectorClear.addEventListener('click',function(){{if(selectorInput)selectorInput.value='';renderSelector();selectorInput&&selectorInput.focus();}});}}
  var customNameInput=document.getElementById('selector-custom-name');
  if(customNameInput){{customNameInput.addEventListener('keydown',function(evt){{if(evt.key==='Enter'){{evt.preventDefault();createOrSelectCustomBoard();}}}});}}
  var customCreate=document.getElementById('selector-custom-create');
  if(customCreate){{customCreate.addEventListener('click',createOrSelectCustomBoard);}}
  var customView=document.getElementById('selector-custom-view');
  if(customView){{customView.addEventListener('click',function(){{if(!selectorActiveBoard){{if(customNameInput)customNameInput.focus();return;}}setSelectorMode('custom');renderSelector();}});}}
  var customAll=document.getElementById('selector-custom-all');
  if(customAll){{customAll.addEventListener('click',function(){{setSelectorMode('all');renderSelector();}});}}
  var customImportBtn=document.getElementById('selector-custom-import-btn');
  var customImport=document.getElementById('selector-custom-import');
  if(customImportBtn&&customImport){{customImportBtn.addEventListener('click',function(){{customImport.click();}});}}
  if(customImport){{
    customImport.addEventListener('change',function(){{
      var file=customImport.files&&customImport.files[0];
      if(!file)return;
      var reader=new FileReader();
      reader.onload=function(evt){{importCustomBoardsFromText(evt.target?evt.target.result:'');customImport.value='';}};
      reader.onerror=function(){{window.alert('文件读取失败。');customImport.value='';}};
      reader.readAsText(file,'utf-8');
    }});
  }}
  var customExport=document.getElementById('selector-custom-export');
  if(customExport){{customExport.addEventListener('click',exportCustomBoards);}}
  var customDelete=document.getElementById('selector-custom-delete');
  if(customDelete){{customDelete.addEventListener('click',deleteActiveCustomBoard);}}
  var customBoards=document.getElementById('selector-custom-boards');
  if(customBoards){{
    customBoards.addEventListener('click',function(evt){{
      var chip=evt.target&&evt.target.closest?evt.target.closest('.selector-board-chip'):null;
      if(!chip)return;
      selectorActiveBoard=chip.getAttribute('data-board')||'';
      selectorCustomState.active=selectorActiveBoard;
      if(customNameInput)customNameInput.value=selectorActiveBoard;
      saveCustomBoards();
      renderCustomBoards();
      setSelectorMode('custom');
      renderSelector();
    }});
  }}
  document.querySelectorAll('.selector-mode').forEach(function(btn){{
    btn.addEventListener('click',function(){{
      var nextMode=btn.getAttribute('data-mode')||'all';
      if(nextMode==='custom'&&!selectorActiveBoard){{
        if(customNameInput)customNameInput.focus();
      }}
      setSelectorMode(nextMode);
      renderSelector();
    }});
  }});
  document.querySelectorAll('.selector-sort-btn').forEach(function(btn){{
    btn.addEventListener('click',function(){{
      selectorSort=btn.getAttribute('data-sort')||'match';
      document.querySelectorAll('.selector-sort-btn').forEach(function(x){{x.classList.toggle('active',x===btn);}});
      renderSelector();
    }});
  }});
  document.querySelectorAll('.selector-chip').forEach(function(btn){{
    btn.addEventListener('click',function(){{
      setSelectorMode(btn.getAttribute('data-mode')||'all');
      if(selectorInput){{selectorInput.value=btn.getAttribute('data-query')||'';selectorInput.focus();}}
      renderSelector();
    }});
  }});
  if(customNameInput&&selectorActiveBoard)customNameInput.value=selectorActiveBoard;
  renderCustomBoards();
  if(selectorRows.length)renderSelector();
}})();
        """
    )


def _stock_viewer_page_styles() -> str:
    return """
    :root {
      --ink:#202631;
      --muted:#657084;
      --line:#d5dde8;
      --paper:#eef2f4;
      --panel:#ffffff;
      --soft:#f7f9fb;
      --blue:#2d6cdf;
      --green:#15805d;
      --red:#c84545;
      --dark:#202631;
    }
    * { box-sizing:border-box; }
    body {
      margin:0;
      color:var(--ink);
      background:var(--paper);
      font-family:"Microsoft YaHei","Noto Sans SC","PingFang SC",sans-serif;
      font-size:14px;
    }
    button, input { font:inherit; }
    a { color:inherit; text-decoration:none; }
    .stock-viewer-page {
      width:min(1920px, calc(100vw - 24px));
      margin:0 auto;
      padding:14px 0 24px;
    }
    .viewer-head {
      display:flex;
      justify-content:space-between;
      gap:14px;
      align-items:flex-start;
      background:var(--panel);
      border:1px solid var(--line);
      border-radius:10px;
      padding:14px 16px;
      margin-bottom:12px;
    }
    h1 { margin:0; font-size:26px; line-height:1.2; }
    .subtitle { margin:5px 0 0; color:var(--muted); font-size:13px; }
    .viewer-actions { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:8px; }
    .link-pill, .viewer-toggle {
      display:inline-flex;
      align-items:center;
      justify-content:center;
      min-height:34px;
      border:1px solid var(--line);
      border-radius:7px;
      padding:0 11px;
      background:var(--soft);
      color:var(--ink);
      font-size:12px;
      font-weight:900;
      white-space:nowrap;
    }
    .viewer-toggle { cursor:pointer; }
    .link-pill.primary { color:#fff; background:var(--blue); border-color:#245ac0; }
    .viewer-shell {
      display:grid;
      grid-template-columns:390px minmax(0, 1fr);
      gap:12px;
      min-height:calc(100vh - 126px);
    }
    .viewer-shell.sidebar-collapsed { grid-template-columns:minmax(0, 1fr); }
    .viewer-shell.sidebar-collapsed .viewer-sidebar { display:none; }
    .viewer-sidebar, .viewer-main {
      background:var(--panel);
      border:1px solid var(--line);
      border-radius:10px;
      box-shadow:0 1px 2px rgba(31,41,55,.04);
      min-width:0;
    }
    .viewer-sidebar {
      display:flex;
      flex-direction:column;
      overflow:hidden;
      max-height:calc(100vh - 126px);
    }
    .viewer-search {
      padding:12px;
      border-bottom:1px solid var(--line);
      background:#fbfcfe;
    }
    .viewer-panel-title {
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:8px;
      margin-bottom:8px;
    }
    .viewer-panel-title strong { font-size:13px; }
    .viewer-collapse {
      min-height:26px;
      border:1px solid var(--line);
      border-radius:999px;
      background:#fff;
      color:var(--blue);
      padding:0 9px;
      font-size:12px;
      font-weight:900;
      cursor:pointer;
    }
    .viewer-section-body { display:block; }
    .viewer-section-collapsed .viewer-section-body { display:none; }
    .viewer-counts {
      display:grid;
      grid-template-columns:repeat(3, minmax(0, 1fr));
      gap:8px;
      margin-bottom:10px;
    }
    .viewer-counts div {
      border:1px solid #e3e9f2;
      border-radius:8px;
      background:#fff;
      padding:8px;
    }
    .viewer-counts span { display:block; color:var(--muted); font-size:11px; font-weight:900; }
    .viewer-counts strong { display:block; margin-top:2px; font-size:17px; line-height:1.15; }
    .viewer-search-row {
      display:grid;
      grid-template-columns:minmax(0,1fr) 54px;
      gap:8px;
    }
    .viewer-search input {
      min-height:38px;
      width:100%;
      border:1px solid var(--line);
      border-radius:8px;
      padding:0 10px;
      background:#fff;
      outline:none;
    }
    .viewer-search input:focus { border-color:#9db5d8; box-shadow:0 0 0 3px rgba(45,108,223,.10); }
    .viewer-button, .viewer-mode, .viewer-chip, .viewer-board-chip, .viewer-add-board {
      border:1px solid var(--line);
      border-radius:999px;
      background:#f7f9fb;
      color:var(--ink);
      font-size:12px;
      font-weight:900;
      cursor:pointer;
    }
    .viewer-button { border-radius:8px; min-height:38px; }
    .viewer-modes { display:flex; flex-wrap:wrap; gap:7px; margin-top:10px; }
    .viewer-mode { min-height:30px; padding:0 10px; }
    .viewer-mode.active, .viewer-chip.active, .viewer-board-chip.active {
      background:var(--blue);
      color:#fff;
      border-color:#245ac0;
    }
    .viewer-chip-strip {
      display:flex;
      flex-wrap:wrap;
      gap:6px;
      max-height:84px;
      overflow:auto;
      padding-top:10px;
    }
    .viewer-chip, .viewer-board-chip { min-height:28px; padding:0 9px; }
    .viewer-chip span, .viewer-board-chip span { margin-left:4px; color:var(--muted); }
    .viewer-chip.active span, .viewer-board-chip.active span { color:#dce8ff; }
    .viewer-boards {
      padding:10px 12px;
      border-bottom:1px solid var(--line);
      background:#fff;
    }
    .viewer-board-title {
      display:flex;
      justify-content:space-between;
      gap:8px;
      align-items:center;
      margin-bottom:8px;
    }
    .viewer-board-title strong { font-size:13px; }
    .viewer-board-title span { color:var(--muted); font-size:12px; text-align:right; }
    .viewer-board-create {
      display:grid;
      grid-template-columns:minmax(0,1fr) 72px;
      gap:8px;
      margin-bottom:8px;
    }
    .viewer-board-create input {
      min-height:34px;
      border:1px solid var(--line);
      border-radius:8px;
      padding:0 9px;
      outline:none;
      background:#fbfcfe;
    }
    .viewer-board-create button {
      min-height:34px;
      border-radius:8px;
      border:1px solid #245ac0;
      background:var(--blue);
      color:#fff;
      font-weight:900;
      cursor:pointer;
    }
    .viewer-board-list { display:flex; flex-wrap:wrap; gap:6px; max-height:76px; overflow:auto; }
    .viewer-list-head {
      display:flex;
      justify-content:space-between;
      gap:8px;
      align-items:center;
      color:var(--muted);
      font-size:12px;
      font-weight:900;
      padding:9px 12px;
      border-bottom:1px solid var(--line);
    }
    .viewer-list {
      display:grid;
      gap:7px;
      overflow:auto;
      padding:10px 10px 12px;
      min-height:0;
      flex:1 1 auto;
      overscroll-behavior:contain;
    }
    .viewer-row {
      display:grid;
      grid-template-columns:minmax(0,1fr) auto;
      gap:8px;
      border:1px solid var(--line);
      border-radius:8px;
      background:#fbfcfe;
      padding:9px;
      cursor:pointer;
      transition:border-color .15s ease, background .15s ease, transform .15s ease;
    }
    .viewer-row:hover, .viewer-row.active {
      background:#eef5ff;
      border-color:#9db5d8;
    }
    .viewer-row:hover { transform:translateY(-1px); }
    .viewer-row strong {
      display:block;
      overflow:hidden;
      text-overflow:ellipsis;
      white-space:nowrap;
      font-size:14px;
    }
    .viewer-row small, .viewer-row em {
      display:block;
      color:var(--muted);
      font-size:12px;
      font-style:normal;
      margin-top:2px;
    }
    .viewer-row-metrics {
      min-width:74px;
      text-align:right;
      font-weight:900;
      line-height:1.35;
    }
    .viewer-row-metrics span { display:block; font-size:13px; }
    .viewer-row-metrics .up { color:var(--red); }
    .viewer-row-metrics .down { color:var(--green); }
    .viewer-row-metrics .flat { color:var(--muted); }
    .viewer-row-actions {
      grid-column:1 / -1;
      display:flex;
      flex-wrap:wrap;
      gap:6px;
      align-items:center;
    }
    .viewer-row-actions select {
      min-height:28px;
      max-width:170px;
      border:1px solid var(--line);
      border-radius:7px;
      background:#fff;
      padding:0 7px;
      color:var(--ink);
      font-size:12px;
      font-weight:900;
    }
    .viewer-add-board {
      min-height:28px;
      padding:0 8px;
      border-radius:7px;
      background:#eef5ff;
      color:#2d4d7d;
    }
    .viewer-add-board.in-board {
      background:#fff4df;
      border-color:#efbf73;
      color:#7a4e00;
    }
    .viewer-add-board.disabled { color:var(--muted); background:#edf1f6; }
    .viewer-open-new {
      min-height:28px;
      display:inline-flex;
      align-items:center;
      padding:0 8px;
      border:1px solid var(--line);
      border-radius:7px;
      background:#fff;
      color:var(--blue);
      font-size:12px;
      font-weight:900;
    }
    .viewer-main {
      display:flex;
      flex-direction:column;
      overflow:hidden;
    }
    .viewer-current {
      display:flex;
      justify-content:space-between;
      gap:12px;
      align-items:center;
      min-height:58px;
      padding:10px 12px;
      border-bottom:1px solid var(--line);
      background:#fbfcfe;
    }
    .viewer-current strong { display:block; font-size:18px; line-height:1.2; }
    .viewer-current span { display:block; color:var(--muted); font-size:12px; margin-top:3px; }
    .viewer-current .tone { font-size:16px; font-weight:900; }
    .up { color:var(--red); }
    .down { color:var(--green); }
    .flat { color:var(--muted); }
    .viewer-frame-wrap { position:relative; flex:1 1 auto; min-height:680px; background:#eef2f4; }
    .viewer-frame {
      width:100%;
      height:100%;
      border:0;
      display:block;
      background:#eef2f4;
    }
    .viewer-empty {
      position:absolute;
      inset:0;
      display:flex;
      align-items:center;
      justify-content:center;
      text-align:center;
      color:var(--muted);
      padding:24px;
    }
    .empty { color:var(--muted); margin:0; }
    @media (max-width:1180px) {
      .viewer-shell { grid-template-columns:330px minmax(0,1fr); }
    }
    @media (max-width:860px) {
      .stock-viewer-page { width:min(100vw - 18px, 1920px); padding-top:10px; }
      .viewer-head { flex-direction:column; }
      .viewer-actions { justify-content:flex-start; }
      .viewer-shell { grid-template-columns:1fr; }
      .viewer-shell.sidebar-collapsed { grid-template-columns:1fr; }
      .viewer-sidebar { max-height:58vh; }
      .viewer-frame-wrap { min-height:720px; }
    }
    """


def _stock_viewer_script(element_id: str = "stock-viewer-data") -> str:
    return inline_script(
        f"""
(function(){{
  var raw=document.getElementById('{element_id}');
  var payload=raw?JSON.parse(raw.textContent||'{{}}'):{{}};
  var rows=payload.rows||[];
  var state={{mode:'all',query:'',activeBoard:'',selectedSymbol:'',sort:'match',sidebarCollapsed:false}};
  var customKey='quantyb:stock_selector_custom_boards:v1';
  var fileBoards=normalizeBoards(payload.custom_boards||{{}});
  var customState=loadBoards();
  var rowsBySymbol={{}};
  rows.forEach(function(row,idx){{row._rank=idx;if(row.symbol)rowsBySymbol[row.symbol]=row;}});
  function esc(text){{return String(text==null?'':text).replace(/[&<>"']/g,function(ch){{return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch];}});}}
  function norm(text){{return String(text==null?'':text).trim().toLowerCase();}}
  function tone(v){{var n=Number(v);if(!isFinite(n)||n===0)return'flat';return n>0?'up':'down';}}
  function pct(v){{var n=Number(v);if(!isFinite(n))return'--';return(n>=0?'+':'')+n.toFixed(2)+'%';}}
  function price(v){{var n=Number(v);if(!isFinite(n))return'--';return n.toFixed(2);}}
  function mv(v){{var n=Number(v);if(!isFinite(n))return'市值 --';if(Math.abs(n)>=100000000)return'市值 '+(n/100000000).toFixed(2)+'万亿';if(Math.abs(n)>=10000)return'市值 '+(n/10000).toFixed(2)+'亿';return'市值 '+n.toFixed(0)+'万';}}
  function normalizeBoards(input){{
    var boards={{}}, source=input&&input.boards&&typeof input.boards==='object'?input.boards:input;
    if(!source||typeof source!=='object')return boards;
    Object.keys(source).forEach(function(name){{
      var boardName=String(name||'').trim();if(!boardName)return;
      var rawBoard=source[name];
      var stocks=Array.isArray(rawBoard)?rawBoard:(rawBoard&&Array.isArray(rawBoard.stocks)?rawBoard.stocks:(rawBoard&&Array.isArray(rawBoard.symbols)?rawBoard.symbols:[]));
      var seen={{}};
      boards[boardName]={{name:boardName,stocks:[]}};
      stocks.forEach(function(item){{
        var symbol=typeof item==='object'&&item?String(item.symbol||item.ts_code||item.code||'').trim().toUpperCase():String(item||'').trim().toUpperCase();
        if(symbol&&!seen[symbol]){{boards[boardName].stocks.push(symbol);seen[symbol]=1;}}
      }});
    }});
    return boards;
  }}
  function cloneBoards(boards){{
    var out={{}};
    Object.keys(boards||{{}}).forEach(function(name){{
      var board=boards[name]||{{}};
      out[name]={{name:board.name||name,stocks:Array.isArray(board.stocks)?board.stocks.slice():[]}};
    }});
    return out;
  }}
  function mergeBoard(target,name,board){{
    if(!name||!board)return;
    if(!target[name])target[name]={{name:name,stocks:[]}};
    var seen={{}};
    target[name].stocks.forEach(function(symbol){{seen[symbol]=1;}});
    (board.stocks||[]).forEach(function(symbol){{
      symbol=String(symbol||'').trim().toUpperCase();
      if(symbol&&!seen[symbol]){{target[name].stocks.push(symbol);seen[symbol]=1;}}
    }});
  }}
  function loadBoards(){{
    var fallback=cloneBoards(fileBoards);
    try{{
      var parsed=JSON.parse(localStorage.getItem(customKey)||'{{}}')||{{}};
      var boards=cloneBoards(parsed.boards||{{}});
      Object.keys(fallback).forEach(function(name){{mergeBoard(boards,name,fallback[name]);}});
      var names=Object.keys(boards).sort(function(a,b){{return a.localeCompare(b,'zh-Hans-CN');}});
      return {{active:parsed.active||names[0]||'',boards:boards}};
    }}catch(err){{
      var names=Object.keys(fallback).sort(function(a,b){{return a.localeCompare(b,'zh-Hans-CN');}});
      return {{active:names[0]||'',boards:fallback}};
    }}
  }}
  function saveBoards(){{try{{localStorage.setItem(customKey,JSON.stringify(customState));}}catch(err){{}}}}
  function boardNames(){{return Object.keys(customState.boards||{{}}).sort(function(a,b){{return a.localeCompare(b,'zh-Hans-CN');}});}}
  function boardCount(name){{var b=name?customState.boards[name]:null;return b&&Array.isArray(b.stocks)?b.stocks.length:0;}}
  function hasSymbol(name,symbol){{var b=name?customState.boards[name]:null;return !!(b&&Array.isArray(b.stocks)&&b.stocks.indexOf(symbol)>=0);}}
  function targetBoard(row){{return state.activeBoard&&customState.boards[state.activeBoard]?state.activeBoard:(boardNames()[0]||'');}}
  function boardOptions(selected){{
    var names=boardNames();
    if(!names.length)return '<option value="">先建板块</option>';
    return names.map(function(name){{return '<option value="'+esc(name)+'" '+(name===selected?'selected':'')+'>'+esc(name)+'</option>';}}).join('');
  }}
  function createBoard(){{
    var input=document.getElementById('viewer-board-input');
    var name=input?String(input.value||'').trim():'';
    if(!name){{if(input)input.focus();return;}}
    if(!customState.boards[name])customState.boards[name]={{name:name,created_at:new Date().toISOString(),stocks:[]}};
    state.activeBoard=name;customState.active=name;saveBoards();renderBoards();renderRows();
  }}
  function viewerScrollSnapshot(){{
    var list=document.getElementById('viewer-stock-list');
    return {{windowX:window.scrollX||0,windowY:window.scrollY||0,listTop:list?list.scrollTop:0}};
  }}
  function restoreViewerScroll(snapshot){{
    if(!snapshot)return;
    var restore=function(){{
      var list=document.getElementById('viewer-stock-list');
      if(list)list.scrollTop=snapshot.listTop||0;
      window.scrollTo(snapshot.windowX||0,snapshot.windowY||0);
    }};
    restore();
    if(window.requestAnimationFrame)window.requestAnimationFrame(restore);
    else window.setTimeout(restore,0);
  }}
  function toggleInBoard(symbol,boardName,preserveScroll){{
    var scrollState=preserveScroll?viewerScrollSnapshot():null;
    boardName=String(boardName||'').trim();if(!boardName)return;
    if(!customState.boards[boardName])customState.boards[boardName]={{name:boardName,created_at:new Date().toISOString(),stocks:[]}};
    var stocks=customState.boards[boardName].stocks||[], idx=stocks.indexOf(symbol);
    if(idx>=0)stocks.splice(idx,1);else stocks.push(symbol);
    state.activeBoard=boardName;customState.active=boardName;saveBoards();renderBoards();renderRows();
    restoreViewerScroll(scrollState);
  }}
  function rowText(row){{
    if(state.mode==='custom')return row.search_text||'';
    if(state.mode==='concept')return row.concept_text||'';
    if(state.mode==='industry')return row.industry_text||'';
    if(state.mode==='name')return row.name_text||'';
    return row.search_text||'';
  }}
  function matches(row){{
    if(state.mode==='custom'&&(!state.activeBoard||!hasSymbol(state.activeBoard,row.symbol)))return false;
    var q=norm(state.query);if(!q)return true;
    return norm(rowText(row)).indexOf(q)>=0;
  }}
  function sortRows(list){{
    var out=list.slice();
    if(state.sort==='name')return out.sort(function(a,b){{return String(a.name||a.symbol||'').localeCompare(String(b.name||b.symbol||''),'zh-Hans-CN')||((a._rank||0)-(b._rank||0));}});
    var key=state.sort==='pct1d'?'pct_chg':state.sort==='pct5d'?'pct_5d':state.sort==='marketcap'?'market_cap':'';
    if(key)return out.sort(function(a,b){{var av=Number(a[key]),bv=Number(b[key]);if(!isFinite(av)&&!isFinite(bv))return(a._rank||0)-(b._rank||0);if(!isFinite(av))return 1;if(!isFinite(bv))return-1;return(bv-av)||((a._rank||0)-(b._rank||0));}});
    return out.sort(function(a,b){{return(a._rank||0)-(b._rank||0);}});
  }}
  function setMode(mode){{
    state.mode=mode||'all';
    document.querySelectorAll('[data-viewer-mode]').forEach(function(btn){{btn.classList.toggle('active',btn.getAttribute('data-viewer-mode')===state.mode);}});
    renderRows();
  }}
  function setSidebarCollapsed(collapsed){{
    state.sidebarCollapsed=!!collapsed;
    var shell=document.querySelector('.viewer-shell');
    var toggle=document.getElementById('viewer-sidebar-toggle');
    if(shell)shell.classList.toggle('sidebar-collapsed',state.sidebarCollapsed);
    if(toggle)toggle.textContent=state.sidebarCollapsed?'展开查找栏':'隐藏查找栏';
  }}
  function toggleSection(name){{
    var section=document.querySelector('[data-viewer-section="'+name+'"]');
    if(!section)return;
    var collapsed=!section.classList.contains('viewer-section-collapsed');
    section.classList.toggle('viewer-section-collapsed',collapsed);
    var btn=section.querySelector('[data-collapse-section]');
    if(btn)btn.textContent=collapsed?'展开':'折叠';
  }}
  function setBoard(name){{
    state.activeBoard=name||'';
    customState.active=state.activeBoard;
    if(state.activeBoard)state.mode='custom';
    saveBoards();
    renderBoards();
    document.querySelectorAll('[data-viewer-mode]').forEach(function(btn){{btn.classList.toggle('active',btn.getAttribute('data-viewer-mode')===state.mode);}});
    renderRows();
  }}
  function renderBoards(){{
    var list=document.getElementById('viewer-board-list'), status=document.getElementById('viewer-board-status');
    var names=boardNames();
    if(state.activeBoard&&!customState.boards[state.activeBoard])state.activeBoard=names[0]||'';
    if(list)list.innerHTML=names.length?names.map(function(name){{return '<button type="button" class="viewer-board-chip '+(name===state.activeBoard?'active':'')+'" data-board="'+esc(name)+'">'+esc(name)+'<span>'+boardCount(name)+'</span></button>';}}).join(''):'<span class="empty">还没有我的板块。</span>';
    if(status)status.textContent=state.activeBoard?'当前：'+state.activeBoard+' · '+boardCount(state.activeBoard)+' 只':'新建后可从股票行加入。';
  }}
  function renderTags(items,limit){{return(items||[]).slice(0,limit||3).map(function(x){{return esc(x);}}).join(' / ');}}
  function renderRows(){{
    var list=document.getElementById('viewer-stock-list'), summary=document.getElementById('viewer-list-summary');
    if(!list)return;
    var matched=sortRows(rows.filter(matches));
    var limit=state.mode==='custom'?matched.length:160;
    var capped=matched.slice(0,limit);
    if(summary)summary.textContent=(state.mode==='custom'&&state.activeBoard?'我的板块「'+state.activeBoard+'」':'当前范围')+' · 匹配 '+matched.length+' 只'+(matched.length>capped.length?'，显示前 '+capped.length+' 只':'')+(state.mode==='custom'&&matched.length>12?' · 可滚轮下滑查看':'');
    list.innerHTML=capped.length?capped.map(function(row){{
      var disabled=!row.href;
      var target=targetBoard(row), inBoard=target&&hasSymbol(target,row.symbol);
      return '<div class="viewer-row '+(row.symbol===state.selectedSymbol?'active':'')+'" data-symbol="'+esc(row.symbol||'')+'" data-href="'+esc(row.href||'')+'" data-disabled="'+(disabled?'1':'0')+'">'
        +'<div><strong>'+esc(row.name||row.symbol||'--')+'</strong><small>'+esc(row.symbol||'')+' · '+esc(renderTags(row.industry_tags,2)||row.industry||'--')+'</small><em>'+esc(renderTags(row.concepts,3)||'--')+'</em></div>'
        +'<div class="viewer-row-metrics"><span>'+esc(price(row.price))+'</span><span class="'+tone(row.pct_chg)+'">'+esc(pct(row.pct_chg))+'</span><small>'+esc(mv(row.market_cap))+'</small></div>'
        +'<div class="viewer-row-actions"><select class="viewer-board-target" data-symbol="'+esc(row.symbol||'')+'">'+boardOptions(target)+'</select><button type="button" class="viewer-add-board '+(inBoard?'in-board':'')+' '+(!target?'disabled':'')+'" data-symbol="'+esc(row.symbol||'')+'" '+(!target?'disabled':'')+'>'+(target?(inBoard?'移出板块':'加入板块'):'先建板块')+'</button><a class="viewer-open-new" href="'+esc(row.href||'#')+'" target="_blank" '+(disabled?'aria-disabled="true"':'')+'>新页打开</a></div>'
        +'</div>';
    }}).join(''):'<p class="empty">没有匹配股票，换个关键词或板块试试。</p>';
  }}
  function selectStock(symbol,href){{
    var row=rowsBySymbol[symbol]||null;
    href=href||(row&&row.href)||'';
    if(!row||!href)return;
    state.selectedSymbol=symbol;
    var frame=document.getElementById('viewer-frame'), empty=document.getElementById('viewer-empty');
    if(frame&&frame.getAttribute('src')!==href)frame.setAttribute('src',href);
    if(empty)empty.style.display='none';
    var name=document.getElementById('viewer-current-name'), meta=document.getElementById('viewer-current-meta'), pctNode=document.getElementById('viewer-current-pct');
    if(name)name.textContent=(row.name||symbol)+' '+symbol;
    if(meta)meta.textContent=(renderTags(row.industry_tags,3)||row.industry||'--')+' · '+(renderTags(row.concepts,4)||'--');
    if(pctNode){{pctNode.textContent=pct(row.pct_chg);pctNode.className='tone '+tone(row.pct_chg);}}
    renderRows();
  }}
  function firstViewable(){{return rows.find(function(row){{return !!row.href;}})||rows[0]||null;}}
  document.querySelectorAll('[data-viewer-mode]').forEach(function(btn){{btn.addEventListener('click',function(){{setMode(btn.getAttribute('data-viewer-mode')||'all');}});}});
  var sidebarToggle=document.getElementById('viewer-sidebar-toggle');
  if(sidebarToggle)sidebarToggle.addEventListener('click',function(){{setSidebarCollapsed(!state.sidebarCollapsed);}});
  document.querySelectorAll('[data-collapse-section]').forEach(function(btn){{btn.addEventListener('click',function(){{toggleSection(btn.getAttribute('data-collapse-section')||'');}});}});
  document.querySelectorAll('[data-chip-query]').forEach(function(btn){{btn.addEventListener('click',function(){{state.query=btn.getAttribute('data-chip-query')||'';var input=document.getElementById('viewer-search-input');if(input)input.value=state.query;setMode(btn.getAttribute('data-chip-mode')||'all');}});}});
  var search=document.getElementById('viewer-search-input');
  if(search)search.addEventListener('input',function(){{state.query=search.value||'';renderRows();}});
  var clear=document.getElementById('viewer-search-clear');
  if(clear)clear.addEventListener('click',function(){{state.query='';if(search){{search.value='';search.focus();}}renderRows();}});
  var boardInput=document.getElementById('viewer-board-input');
  if(boardInput)boardInput.addEventListener('keydown',function(evt){{if(evt.key==='Enter'){{evt.preventDefault();createBoard();}}}});
  var boardCreate=document.getElementById('viewer-board-create');
  if(boardCreate)boardCreate.addEventListener('click',createBoard);
  var boardList=document.getElementById('viewer-board-list');
  if(boardList)boardList.addEventListener('click',function(evt){{var chip=evt.target&&evt.target.closest?evt.target.closest('.viewer-board-chip'):null;if(chip)setBoard(chip.getAttribute('data-board')||'');}});
  var stockList=document.getElementById('viewer-stock-list');
  if(stockList){{
    stockList.addEventListener('click',function(evt){{
      var add=evt.target&&evt.target.closest?evt.target.closest('.viewer-add-board'):null;
      if(add){{evt.preventDefault();evt.stopPropagation();if(add.disabled)return;var rowEl=add.closest('.viewer-row'), target=rowEl?rowEl.querySelector('.viewer-board-target'):null;toggleInBoard(add.getAttribute('data-symbol')||'',target?target.value:state.activeBoard,true);return;}}
      if(evt.target&&evt.target.closest&&evt.target.closest('.viewer-board-target'))return;
      if(evt.target&&evt.target.closest&&evt.target.closest('.viewer-open-new'))return;
      var row=evt.target&&evt.target.closest?evt.target.closest('.viewer-row'):null;
      if(row&&row.getAttribute('data-disabled')!=='1')selectStock(row.getAttribute('data-symbol')||'',row.getAttribute('data-href')||'');
    }});
    stockList.addEventListener('change',function(evt){{
      var sel=evt.target&&evt.target.closest?evt.target.closest('.viewer-board-target'):null;if(!sel)return;
      var rowEl=sel.closest('.viewer-row'), btn=rowEl?rowEl.querySelector('.viewer-add-board'):null;
      if(!btn)return;
      var inBoard=sel.value&&hasSymbol(sel.value,sel.getAttribute('data-symbol')||'');
      btn.disabled=!sel.value;btn.classList.toggle('disabled',!sel.value);btn.classList.toggle('in-board',!!inBoard);btn.textContent=!sel.value?'先建板块':(inBoard?'移出板块':'加入板块');
    }});
  }}
  state.activeBoard=customState.active||boardNames()[0]||'';
  if(boardInput&&state.activeBoard)boardInput.value=state.activeBoard;
  renderBoards();
  renderRows();
  var first=firstViewable();
  if(first&&first.href)selectStock(first.symbol,first.href);
}})();
        """
    )


def _build_stock_viewer_html(selector: dict[str, Any], dashboard_href: str, selector_href: str) -> str:
    top_concepts = selector.get("top_concepts", [])[:12]
    top_industries = selector.get("top_industries", [])[:10]
    chips = "".join(
        f'<button type="button" class="viewer-chip" data-chip-mode="concept" data-chip-query="{html.escape(str(item.get("name", "")), quote=True)}">{html.escape(str(item.get("name", "")))}<span>{html.escape(str(item.get("count", 0)))}</span></button>'
        for item in top_concepts
    ) + "".join(
        f'<button type="button" class="viewer-chip" data-chip-mode="industry" data-chip-query="{html.escape(str(item.get("name", "")), quote=True)}">{html.escape(str(item.get("name", "")))}<span>{html.escape(str(item.get("count", 0)))}</span></button>'
        for item in top_industries
    )
    count = int(selector.get("count") or len(selector.get("rows") or []))
    cache_count = int(selector.get("cache_count") or 0)
    kline_count = int(selector.get("kline_count") or 0)
    return html_document(
        title="QuantYB 股票查看器",
        styles=_stock_viewer_page_styles(),
        body=f"""
    <main class="stock-viewer-page">
      <header class="viewer-head">
        <div>
          <h1>股票查看器</h1>
          <p class="subtitle">左侧搜索股票、行业、概念和我的板块；右侧直接切换本地 K 线页，不再来回跳选择器。</p>
        </div>
        <div class="viewer-actions">
          <button id="viewer-sidebar-toggle" class="viewer-toggle" type="button">隐藏查找栏</button>
          <a class="link-pill" href="{html.escape(selector_href, quote=True)}">打开股票选择器</a>
          <a class="link-pill primary" href="{html.escape(dashboard_href, quote=True)}">返回 Dashboard</a>
        </div>
      </header>
      <section class="viewer-shell">
        <aside class="viewer-sidebar">
          <div class="viewer-search" data-viewer-section="search">
            <div class="viewer-panel-title">
              <strong>查找</strong>
              <button class="viewer-collapse" type="button" data-collapse-section="search">折叠</button>
            </div>
            <div class="viewer-section-body">
              <div class="viewer-counts">
                <div><span>股票</span><strong>{count}</strong></div>
                <div><span>缓存</span><strong>{cache_count}</strong></div>
                <div><span>K线页</span><strong>{kline_count}</strong></div>
              </div>
              <div class="viewer-search-row">
                <input id="viewer-search-input" type="search" placeholder="搜索代码、简称、行业、概念" autocomplete="off">
                <button id="viewer-search-clear" class="viewer-button" type="button">清空</button>
              </div>
              <div class="viewer-modes">
                <button type="button" class="viewer-mode active" data-viewer-mode="all">全部</button>
                <button type="button" class="viewer-mode" data-viewer-mode="concept">概念</button>
                <button type="button" class="viewer-mode" data-viewer-mode="industry">行业</button>
                <button type="button" class="viewer-mode" data-viewer-mode="name">名称/代码</button>
                <button type="button" class="viewer-mode" data-viewer-mode="custom">我的板块</button>
              </div>
              <div class="viewer-chip-strip">{chips}</div>
            </div>
          </div>
          <div class="viewer-boards" data-viewer-section="boards">
            <div class="viewer-board-title">
              <strong>我的板块</strong>
              <span id="viewer-board-status">浏览器本地保存</span>
              <button class="viewer-collapse" type="button" data-collapse-section="boards">折叠</button>
            </div>
            <div class="viewer-section-body">
              <div class="viewer-board-create">
                <input id="viewer-board-input" type="text" placeholder="新建/选择板块">
                <button id="viewer-board-create" type="button">确定</button>
              </div>
              <div id="viewer-board-list" class="viewer-board-list"></div>
            </div>
          </div>
          <div class="viewer-list-head">
            <span id="viewer-list-summary">准备加载股票</span>
          </div>
          <div id="viewer-stock-list" class="viewer-list"></div>
        </aside>
        <section class="viewer-main">
          <div class="viewer-current">
            <div>
              <strong id="viewer-current-name">请选择股票</strong>
              <span id="viewer-current-meta">搜索或点击我的板块里的股票</span>
            </div>
            <div id="viewer-current-pct" class="tone flat">--</div>
          </div>
          <div class="viewer-frame-wrap">
            <iframe id="viewer-frame" class="viewer-frame" title="股票 K 线查看"></iframe>
            <div id="viewer-empty" class="viewer-empty">没有可打开的本地 K 线页。请先生成股票 K 线页或检查缓存。</div>
          </div>
        </section>
      </section>
    </main>
        """,
        head_extra='<link rel="icon" href="data:,">',
        scripts=json_script_data(selector, "stock-viewer-data") + _stock_viewer_script(),
    )


def _build_stock_selector_html(selector: dict[str, Any], dashboard_href: str) -> str:
    return html_document(
        title="QuantYB 股票选择器",
        styles=_stock_selector_page_styles(),
        body=f"""
    <main class="selector-page">
      <header class="selector-head">
        <div>
          <h1>股票选择器</h1>
          <p class="subtitle">按概念板块、行业板块、股票名称/代码搜索；选择股票后打开本地 K 线页。</p>
        </div>
        <a class="link-pill primary" href="{html.escape(dashboard_href, quote=True)}">返回 Dashboard</a>
      </header>
      {_build_stock_selector_panel({"stock_selector": selector})}
    </main>
        """,
        head_extra='<link rel="icon" href="data:,">',
        scripts=json_script_data(selector, "stock-selector-data") + _stock_selector_script(),
    )


def _dashboard_script() -> str:
    return inline_script(
        """
(function(){
  var raw=document.getElementById('dashboard-data');
  var data=raw?JSON.parse(raw.textContent||'{}'):{};
  var indexes=data.indexes||[];
  var chart=null;
  var distributionChart=null;
  var C={up:'#c84545',down:'#15805d',flat:'#b9c3d1',line:'#d5dde8',split:'#edf1f6',axis:'#657084',blue:'#2d6cdf'};
  function fmtAmount(v){var n=Number(v);if(!isFinite(n))return'--';var yi=n/100000;if(Math.abs(yi)>=10000)return(yi/10000).toFixed(2)+'万亿';return yi.toFixed(Math.abs(yi)>=1000?0:1)+'亿';}
  function fmtPctRatio(v){var n=Number(v);if(!isFinite(n))return'--';return(n*100).toFixed(1)+'%';}
  function fmtRatio(v){var n=Number(v);if(!isFinite(n))return'--';return n.toFixed(2)+'x';}
  function tone(pct){pct=String(pct||'');return pct.indexOf('+')===0?'up':(pct.indexOf('-')===0?'down':'flat');}
  function initChart(){var el=document.getElementById('index-mini-chart');if(!el||typeof echarts==='undefined')return null;if(!chart)chart=echarts.init(el,null,{renderer:'canvas'});return chart;}
  function initDistributionChart(){var el=document.getElementById('index-distribution-chart');if(!el||typeof echarts==='undefined')return null;if(!distributionChart)distributionChart=echarts.init(el,null,{renderer:'canvas'});return distributionChart;}
  function normDate(v){return String(v||'').replace(/-/g,'');}
  function marketMaps(){var m=data.market_amount||{},out={amount:{},ma20:{},ratio20:{},advance:{},decline:{},ret:{}};(m.dates||[]).forEach(function(d,i){var k=normDate(d);out.amount[k]=(m.total_amount||[])[i];out.ma20[k]=(m.amount_ma20||[])[i];out.ratio20[k]=(m.amount_ratio_20d||[])[i];out.advance[k]=(m.advance_amount_ratio||[])[i];out.decline[k]=(m.decline_amount_ratio||[])[i];out.ret[k]=(m.equal_weight_return_1d||[])[i];});return out;}
  function indexMaps(item){var c=item.chart||{},out={display:{},ohlc:{},amount:{}};(c.dates||[]).forEach(function(d,i){var k=normDate(d);out.display[k]=d;out.ohlc[k]=(c.ohlc||[])[i]||null;out.amount[k]=(c.amount||[])[i];});return out;}
  function chartDates(item,idxMaps){var seen={};(item.chart&&item.chart.dates||[]).forEach(function(d){var k=normDate(d);if(k)seen[k]=idxMaps.display[k]||d;});((data.market_amount||{}).dates||[]).forEach(function(d){var k=normDate(d);if(k&&!seen[k])seen[k]=d;});return Object.keys(seen).sort().map(function(k){return seen[k];});}
  function zoomStart(dates){var len=(dates||[]).length;if(len<=120)return 0;return Math.max(0,100-(120/len*100));}
  function klineData(dates,idxMaps){return dates.map(function(d){var row=idxMaps.ohlc[normDate(d)];return row||[null,null,null,null];});}
  function indexBarData(dates,idxMaps){return dates.map(function(d){var k=normDate(d),o=idxMaps.ohlc[k]||[],open=Number(o[0]),close=Number(o[1]);return{value:idxMaps.amount[k]==null?null:idxMaps.amount[k],itemStyle:{color:close>open?C.up:(close<open?C.down:C.flat),opacity:.62}};});}
  function marketBarData(dates,maps){return dates.map(function(d){var k=normDate(d),r=Number(maps.ret[k]);return{value:maps.amount[k]==null?null:maps.amount[k],itemStyle:{color:isFinite(r)&&r<0?C.down:C.up,opacity:.68}};});}
  function marketLineData(dates,maps){return dates.map(function(d){var v=maps.ma20[normDate(d)];return v==null?null:v;});}
  function option(item){var maps=marketMaps(),idxMaps=indexMaps(item),dates=chartDates(item,idxMaps);return{animation:false,tooltip:{trigger:'axis',axisPointer:{type:'cross'},formatter:function(params){var i=params&&params[0]?params[0].dataIndex:0,date=dates[i],k=normDate(date),o=idxMaps.ohlc[k]||[];var kline=o.length?('开 '+(o[0]??'--')+' 收 '+(o[1]??'--')+'<br/>低 '+(o[2]??'--')+' 高 '+(o[3]??'--')):'指数K线 --';return date+'<br/>'+kline+'<br/>指数成交额 '+fmtAmount(idxMaps.amount[k])+'<br/>全市场成交额 '+fmtAmount(maps.amount[k])+'<br/>20日均量比 '+fmtRatio(maps.ratio20[k])+'<br/>上涨成交占比 '+fmtPctRatio(maps.advance[k]);}},axisPointer:{link:[{xAxisIndex:'all'}],label:{backgroundColor:'#64748b'}},legend:{top:0,right:8,data:['K线','指数成交额','全市场成交额','20日均额'],textStyle:{color:C.axis,fontSize:11}},grid:[{left:54,right:20,top:34,height:'50%'},{left:54,right:20,top:'62%',height:'12%'},{left:54,right:20,top:'80%',height:'14%'}],xAxis:[{type:'category',data:dates,axisLabel:{color:C.axis,fontSize:10},axisLine:{lineStyle:{color:C.line}},splitLine:{show:true,lineStyle:{type:'dashed',color:C.split}}},{type:'category',gridIndex:1,data:dates,axisLabel:{show:false},axisLine:{lineStyle:{color:C.line}},axisPointer:{show:true}},{type:'category',gridIndex:2,data:dates,axisLabel:{color:C.axis,fontSize:10,rotate:20},axisLine:{lineStyle:{color:C.line}},axisPointer:{show:true}}],yAxis:[{scale:true,axisLabel:{color:C.axis},splitLine:{show:true,lineStyle:{type:'dashed',color:C.split}}},{gridIndex:1,min:0,name:'指数额',nameTextStyle:{color:C.axis,fontSize:10},axisLabel:{color:C.axis,formatter:fmtAmount},splitLine:{show:true,lineStyle:{type:'dashed',color:C.split}}},{gridIndex:2,min:0,name:'全市场额',nameTextStyle:{color:C.axis,fontSize:10},axisLabel:{color:C.axis,formatter:fmtAmount},splitLine:{show:true,lineStyle:{type:'dashed',color:C.split}}}],dataZoom:[{type:'inside',xAxisIndex:[0,1,2],start:zoomStart(dates),end:100}],series:[{name:'K线',type:'candlestick',data:klineData(dates,idxMaps),itemStyle:{color:C.up,color0:C.down,borderColor:C.up,borderColor0:C.down}},{name:'指数成交额',type:'bar',xAxisIndex:1,yAxisIndex:1,data:indexBarData(dates,idxMaps),barMaxWidth:12},{name:'全市场成交额',type:'bar',xAxisIndex:2,yAxisIndex:2,data:marketBarData(dates,maps),barMaxWidth:14},{name:'20日均额',type:'line',xAxisIndex:2,yAxisIndex:2,data:marketLineData(dates,maps),symbol:'none',smooth:true,lineStyle:{color:C.blue,width:1.7}}]};}
  function distributionOption(){var d=data.return_distribution||{},rows=d.histogram||[],labels=rows.map(function(x){return x.label;}),counts=rows.map(function(x){return x.count||0;});return{animation:false,tooltip:{trigger:'axis',axisPointer:{type:'shadow'},formatter:function(params){var p=params&&params[0]?params[0]:null;if(!p)return'';var row=rows[p.dataIndex]||{};return (d.date||'')+'<br/>'+row.label+'：'+(row.count||0)+'只<br/>占比 '+fmtPctRatio(row.ratio);}},grid:{left:46,right:14,top:12,bottom:34},xAxis:{type:'category',data:labels,axisLabel:{color:C.axis,fontSize:10,interval:0,rotate:18},axisTick:{show:false},axisLine:{lineStyle:{color:C.line}}},yAxis:{type:'value',min:0,axisLabel:{color:C.axis},splitLine:{show:true,lineStyle:{type:'dashed',color:C.split}}},series:[{name:'股票数',type:'bar',data:rows.map(function(row){var label=String(row.label||''),color=label.indexOf('-')===0||label.indexOf('<')===0?C.down:(label.indexOf('0~')===0?C.flat:C.up);return{value:row.count||0,itemStyle:{color:color,opacity:.72}};}),barMaxWidth:28}]};}
  function renderDistribution(){var ch=initDistributionChart();if(!ch)return;var d=data.return_distribution||{};var meta=document.getElementById('distribution-mini-meta');if(meta){var median=Number(d.median);var up=Number(d.up_ratio);meta.textContent=(d.date||'--')+' · 有效 '+(d.valid_count||'--')+' 只 · 中位 '+(isFinite(median)?(median*100).toFixed(2)+'%':'--')+' · 上涨 '+(isFinite(up)?(up*100).toFixed(1)+'%':'--');}ch.setOption(distributionOption(),true);setTimeout(function(){ch.resize();},0);}
  function select(symbol){var item=indexes.find(function(x){return x.symbol===symbol;})||indexes[0];if(!item)return;document.querySelectorAll('.index-select').forEach(function(btn){btn.classList.toggle('active',btn.getAttribute('data-symbol')===item.symbol);});var snap=item.snapshot||{};var name=document.getElementById('index-mini-name'),meta=document.getElementById('index-mini-meta'),close=document.getElementById('index-mini-close'),pct=document.getElementById('index-mini-pct'),link=document.getElementById('index-mini-link');if(name)name.textContent=item.name||'--';if(meta)meta.textContent=(item.symbol||'--')+' · '+(snap.date||'--');if(close)close.textContent=snap.close||'--';if(pct){pct.textContent=snap.pct_chg||'--';pct.className=tone(snap.pct_chg);}if(link){if(item.href){link.href=item.href;link.removeAttribute('aria-disabled');}else{link.href='#';link.setAttribute('aria-disabled','true');}}var ch=initChart();if(ch){ch.setOption(option(item),true);setTimeout(function(){ch.resize();},0);}}
  document.querySelectorAll('.index-select').forEach(function(btn){btn.addEventListener('click',function(){select(btn.getAttribute('data-symbol'));});});
  if(indexes.length)select(indexes[0].symbol);
  renderDistribution();
  window.addEventListener('resize',function(){if(chart)chart.resize();if(distributionChart)distributionChart.resize();});
})();
        """
    )


def _build_html(data: dict[str, Any]) -> str:
    index_count = len(data["indexes"])
    strategy_count = len(data["strategies"])
    theme_count = len(data["theme_dashboards"])
    signal_count = _signal_total(data["signal_center"])
    etf_count = data.get("etf_strategy", {}).get("count", 0)
    stock_selector_count = int((data.get("stock_selector") or {}).get("count") or 0)
    return html_document(
        title="QuantYB 总控面板",
        styles=f"""
    :root {{
      --ink: #202631;
      --muted: #657084;
      --line: #d5dde8;
      --paper: #eef2f4;
      --panel: #ffffff;
      --soft: #f7f9fb;
      --rail: #2d333b;
      --rail-soft: #39424c;
      --blue: #2d6cdf;
      --teal: #117e73;
      --green: #15805d;
      --red: #c84545;
      --amber: #a56a18;
      --shadow: 0 12px 28px rgba(31, 41, 55, .10);
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      color: var(--ink);
      background: var(--paper);
      font-family: "Microsoft YaHei", "Noto Sans SC", "PingFang SC", sans-serif;
      font-size: 14px;
    }}
    a {{ color: inherit; text-decoration: none; }}
    .workbench {{
      width: min(1640px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 16px 0 36px;
      display: grid;
      grid-template-columns: 244px minmax(0, 1fr);
      gap: 16px;
      align-items: start;
    }}
    .rail {{
      position: sticky;
      top: 16px;
      min-height: calc(100vh - 32px);
      background: var(--rail);
      color: #f4f7fb;
      border: 1px solid #222a32;
      border-radius: 8px;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }}
    .brand {{ display: flex; gap: 12px; align-items: center; padding-bottom: 14px; border-bottom: 1px solid rgba(255,255,255,.12); }}
    .brand-mark {{
      width: 38px;
      height: 38px;
      display: grid;
      place-items: center;
      border-radius: 8px;
      background: #f4f7fb;
      color: var(--rail);
      font-weight: 900;
    }}
    .brand strong {{ display: block; font-size: 18px; }}
    .brand em {{ display: block; margin-top: 2px; color: #b8c4d2; font-style: normal; font-size: 12px; }}
    .rail-nav {{ display: grid; gap: 6px; }}
    .rail-nav a {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      min-height: 38px;
      padding: 0 10px;
      border-radius: 7px;
      color: #dce4ee;
      background: transparent;
      border: 1px solid transparent;
      font-weight: 800;
    }}
    .rail-nav a:hover {{ background: var(--rail-soft); border-color: rgba(255,255,255,.12); }}
    .rail-nav span {{ color: #9fb0c5; font-size: 12px; font-weight: 700; }}
    .rail-card {{
      margin-top: auto;
      padding: 12px;
      border: 1px solid rgba(255,255,255,.14);
      border-radius: 8px;
      background: rgba(255,255,255,.06);
    }}
    .rail-card span {{ display: block; color: #b8c4d2; font-size: 12px; margin-bottom: 5px; }}
    .rail-card strong {{ display: block; font-size: 13px; line-height: 1.45; }}
    .desk {{ min-width: 0; }}
    .desk-head {{
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 16px;
      align-items: center;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px 18px;
      box-shadow: 0 1px 2px rgba(31, 41, 55, .05);
    }}
    h1 {{ margin: 0; font-size: 28px; line-height: 1.15; letter-spacing: 0; }}
    .subtitle {{ margin: 6px 0 0; color: var(--muted); font-size: 13px; }}
    .head-actions {{ display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }}
    .link-pill {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 34px;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 0 11px;
      background: var(--soft);
      color: var(--ink);
      font-size: 12px;
      font-weight: 900;
      white-space: nowrap;
    }}
    .link-pill.primary {{ color: white; background: var(--blue); border-color: #245ac0; }}
    .link-pill.muted {{ color: var(--muted); background: transparent; }}
    .kpis {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin: 12px 0;
    }}
    .kpi {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 13px 14px;
      min-height: 78px;
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: end;
    }}
    .kpi span {{ color: var(--muted); font-size: 12px; }}
    .kpi strong {{ font-size: 24px; letter-spacing: 0; }}
    .desk-section {{ margin-top: 14px; }}
    .section-head {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
      margin: 20px 0 9px;
    }}
    .section-head h2 {{ margin: 0; font-size: 18px; }}
    .section-head span {{ color: var(--muted); font-size: 12px; }}
    .report-entry-section {{ margin-top: 12px; }}
    .report-entry-panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 15px;
      box-shadow: 0 1px 2px rgba(31, 41, 55, .04);
    }}
    .report-entry-main {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(128px, 1fr));
      gap: 8px;
    }}
    .report-entry-main .link-pill {{ min-height: 40px; }}
    .report-entry-backup {{ margin-top: 10px; border-top: 1px solid var(--line); padding-top: 10px; }}
    .report-entry-backup summary {{ cursor: pointer; color: var(--muted); font-size: 13px; font-weight: 800; }}
    .report-entry-backup-links {{ margin-top: 10px; }}
    .report-entry-stats {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(128px, 1fr));
      gap: 8px;
      margin-top: 10px;
      padding-top: 10px;
      border-top: 1px solid var(--line);
    }}
    .report-entry-stats div {{
      border: 1px solid var(--line);
      border-radius: 7px;
      background: var(--soft);
      padding: 10px;
    }}
    .report-entry-stats span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 3px;
    }}
    .report-entry-stats strong {{ font-size: 18px; }}
    .market-layout {{ display: grid; grid-template-columns: 1fr; gap: 0; }}
    .market-section-head {{ grid-column: 1 / -1; }}
    .market-panel, .signal-stream, .side-panel, .etf-panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 15px;
      box-shadow: 0 1px 2px rgba(31, 41, 55, .04);
    }}
    .panel-title {{ display: flex; justify-content: space-between; align-items: center; gap: 10px; color: var(--muted); font-size: 12px; font-weight: 800; }}
    .panel-title strong {{ color: var(--ink); font-size: 12px; }}
    .market-main {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto auto;
      gap: 16px;
      align-items: end;
      margin: 14px 0;
    }}
    .market-main span {{ display: block; font-size: 18px; font-weight: 900; }}
    .market-main em {{ display: block; color: var(--muted); font-style: normal; margin-top: 3px; }}
    .market-main strong {{ font-size: 32px; letter-spacing: 0; }}
    .market-main b {{ font-size: 24px; letter-spacing: 0; }}
    .market-main em, .index-card p, .row-sub, .mini-link span {{
      direction: ltr;
      unicode-bidi: isolate;
      font-variant-numeric: tabular-nums;
    }}
    .field-grid, .coverage-grid, .etf-main {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
    }}
    .field-grid div, .coverage-grid div, .signal-stats div, .rotation-box, .etf-main div, .etf-leader {{
      border: 1px solid var(--line);
      border-radius: 7px;
      background: var(--soft);
      padding: 10px;
    }}
    .field-grid span, .coverage-grid span, .signal-stats span, .rotation-box span, .etf-main span, .etf-leader span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 4px;
    }}
    .field-grid strong, .coverage-grid strong, .signal-stats strong, .rotation-box strong, .etf-main strong {{ font-size: 18px; }}
    .etf-main {{ margin: 12px 0 10px; }}
    .etf-leader strong {{ display:block; font-size:18px; }}
    .etf-leader em {{ display:block; margin-top:4px; color:var(--muted); font-size:12px; font-style:normal; }}
    .quick-links {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 13px 0; }}
    .signal-workbench {{ display: grid; grid-template-columns: minmax(300px, .8fr) minmax(0, 1.6fr); gap: 12px; align-items: stretch; }}
    .signal-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
    .signal-card, .index-card, .theme-card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
    }}
    .signal-card {{ min-height: 222px; }}
    .index-card {{ min-height: 178px; }}
    .theme-card {{ min-height: 224px; }}
    .index-card:hover, .theme-card:hover, .signal-card:hover, .strategy-row:hover, .mini-link:hover, .stream-row:hover, .etf-panel:hover {{
      transform: translateY(-2px);
      box-shadow: var(--shadow);
      border-color: #aeb9c7;
    }}
    .stream-list {{ display: grid; gap: 8px; margin-top: 12px; }}
    .stream-row {{
      display: grid;
      grid-template-columns: 58px minmax(0, 1fr);
      gap: 6px 10px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fbfcfe;
      padding: 10px;
      transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
    }}
    .stream-row span {{ grid-row: span 2; color: var(--muted); font-size: 12px; font-weight: 900; }}
    .stream-row strong {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .stream-row em {{ color: var(--muted); font-style: normal; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .badge {{ border: 1px solid var(--line); border-radius: 999px; padding: 3px 8px; font-size: 12px; color: var(--muted); background: #f9fafc; font-weight: 800; white-space: nowrap; }}
    .badge.ok {{ color: var(--green); border-color: rgba(21,128,93,.28); background: rgba(21,128,93,.07); }}
    .badge.wait {{ color: var(--amber); border-color: rgba(165,106,24,.3); background: rgba(165,106,24,.08); }}
    .signal-top, .theme-top, .card-top {{ display: flex; justify-content: space-between; align-items: center; gap: 8px; }}
    .signal-top, .theme-top {{ color: var(--ink); font-size: 15px; font-weight: 900; }}
    .card-top {{ color: var(--muted); font-size: 12px; }}
    .signal-list {{ display: grid; gap: 7px; margin: 12px 0; }}
    .signal-item {{ border-bottom: 1px solid var(--line); padding-bottom: 7px; min-height: 36px; }}
    .signal-item span {{ display: block; font-weight: 900; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .signal-item strong {{ display: block; color: var(--muted); font-size: 12px; margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    a.stock-link {{ color: #2454a6; font-weight: 900; text-decoration: none; }}
    a.stock-link:hover {{ text-decoration: underline; }}
    .signal-stats {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin: 12px 0; }}
    .rotation-box p {{ margin: 8px 0 0; color: var(--muted); font-size: 12px; word-break: break-all; }}
    .theme-actions {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 11px; }}
    .selector-entry-card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 15px;
      box-shadow: 0 1px 2px rgba(31, 41, 55, .04);
      transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
    }}
    .selector-entry-card:hover {{
      transform: translateY(-2px);
      box-shadow: var(--shadow);
      border-color: #aeb9c7;
    }}
    .selector-entry-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      margin: 12px 0;
    }}
    .selector-entry-grid div {{
      border: 1px solid var(--line);
      border-radius: 7px;
      background: var(--soft);
      padding: 10px;
    }}
    .selector-entry-grid span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 4px;
    }}
    .selector-entry-grid strong {{ font-size: 22px; }}
    .selector-entry-note {{ margin: 6px 0 0; color: var(--muted); font-size: 12px; }}
    .selector-panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      box-shadow: 0 1px 2px rgba(31, 41, 55, .04);
    }}
    .selector-top {{
      display: grid;
      grid-template-columns: 210px minmax(0, 1fr);
      gap: 12px;
      align-items: center;
    }}
    .selector-top strong {{ display:block; font-size:28px; line-height:1; }}
    .selector-top span {{ display:block; color:var(--muted); font-size:12px; margin-top:5px; }}
    .selector-search {{ display:grid; grid-template-columns:minmax(0, 1fr) 72px; gap:8px; }}
    .selector-search input {{
      width:100%;
      min-height:38px;
      border:1px solid var(--line);
      border-radius:8px;
      padding:0 12px;
      font:inherit;
      background:#fbfcfe;
      outline:none;
    }}
    .selector-search input:focus {{ border-color:#9db5d8; box-shadow:0 0 0 3px rgba(45,108,223,.10); }}
    .selector-search button, .selector-mode, .selector-chip {{
      border:1px solid var(--line);
      border-radius:999px;
      background:#f7f9fb;
      color:var(--ink);
      font:inherit;
      font-size:12px;
      font-weight:900;
      cursor:pointer;
    }}
    .selector-search button {{ border-radius:8px; }}
    .selector-modes {{ display:flex; flex-wrap:wrap; gap:8px; margin:12px 0 10px; }}
    .selector-mode {{ min-height:30px; padding:0 12px; }}
    .selector-mode.active {{ background:var(--blue); border-color:#245ac0; color:white; }}
    .selector-chips {{ display:flex; flex-wrap:wrap; gap:7px; padding:10px 0; border-top:1px solid var(--line); border-bottom:1px solid var(--line); }}
    .selector-chip {{ min-height:28px; padding:0 10px; }}
    .selector-chip span {{ margin-left:5px; color:var(--muted); font-weight:800; }}
    .selector-chip:hover {{ border-color:#9db5d8; background:#eef5ff; }}
    .selector-result-head {{ display:flex; justify-content:space-between; gap:12px; align-items:center; color:var(--muted); font-size:12px; margin:10px 0; }}
    .selector-result-head span {{ font-weight:900; color:var(--ink); }}
    .selector-result-head em {{ font-style:normal; }}
    .selector-results {{ display:grid; gap:7px; max-height:520px; overflow:auto; padding-right:4px; }}
    .selector-row {{
      display:grid;
      grid-template-columns: 176px minmax(150px,.72fr) minmax(260px,1.25fr) 92px 86px;
      gap:10px;
      align-items:center;
      border:1px solid var(--line);
      border-radius:8px;
      background:#fbfcfe;
      padding:10px;
      transition:transform .14s ease, box-shadow .14s ease, border-color .14s ease;
    }}
    .selector-row:hover {{ transform:translateY(-1px); box-shadow:0 8px 18px rgba(31,41,55,.08); border-color:#aeb9c7; }}
    .selector-stock strong {{ display:block; font-size:14px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
    .selector-stock span {{ display:block; color:var(--muted); margin-top:2px; font-size:12px; font-weight:800; direction:ltr; unicode-bidi:isolate; }}
    .selector-tags {{ display:flex; flex-wrap:wrap; gap:5px; max-height:50px; overflow:hidden; }}
    .selector-tags span {{ display:inline-flex; align-items:center; min-height:22px; padding:0 7px; border:1px solid var(--line); border-radius:999px; color:var(--muted); background:#fff; font-size:11px; font-weight:800; }}
    .selector-tags.concept span {{ color:#496079; }}
    .selector-tags em {{ color:var(--muted); font-size:12px; font-style:normal; }}
    .selector-price {{ text-align:right; }}
    .selector-price strong {{ display:block; font-size:14px; }}
    .selector-price span {{ display:block; margin-top:2px; font-size:12px; font-weight:900; }}
    .selector-row.up .selector-price span {{ color:var(--red); }}
    .selector-row.down .selector-price span {{ color:var(--green); }}
    .selector-open {{
      display:inline-flex;
      align-items:center;
      justify-content:center;
      min-height:30px;
      border-radius:7px;
      background:var(--blue);
      color:white;
      font-size:12px;
      font-weight:900;
    }}
    .selector-open.disabled {{ background:#edf1f6; color:var(--muted); border:1px solid var(--line); }}
    .index-grid {{ display: block; }}
    .index-nav-panel {{
      display: grid;
      grid-template-columns: 300px minmax(0, 1fr);
      gap: 12px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      box-shadow: 0 1px 2px rgba(31, 41, 55, .04);
    }}
    .index-select-list {{
      display: grid;
      gap: 7px;
      max-height: 360px;
      overflow: auto;
      padding-right: 4px;
    }}
    .index-select {{
      display: grid;
      grid-template-columns: 34px minmax(0, 1fr) auto;
      gap: 3px 8px;
      align-items: center;
      min-height: 52px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfe;
      color: var(--ink);
      text-align: left;
      padding: 8px 10px;
      cursor: pointer;
      font-family: inherit;
    }}
    .index-select:hover, .index-select.active {{ border-color: #9db5d8; background: #eef5ff; }}
    .index-select span {{ grid-row: span 2; color: var(--muted); font-size: 12px; font-weight: 900; }}
    .index-select strong {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; }}
    .index-select em {{ color: var(--muted); font-style: normal; font-size: 12px; direction:ltr; unicode-bidi:isolate; }}
    .index-select b {{ grid-row: span 2; font-size: 14px; }}
    .index-select.up b, #index-mini-pct.up {{ color: var(--red); }}
    .index-select.down b, #index-mini-pct.down {{ color: var(--green); }}
    .index-mini-panel {{ min-width: 0; border: 1px solid var(--line); border-radius: 8px; background: #fbfcfe; padding: 12px; }}
    .index-mini-head {{ display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; margin-bottom: 6px; }}
    .index-mini-head h3 {{ margin: 0; font-size: 18px; }}
    .index-mini-head p {{ margin: 4px 0 0; color: var(--muted); font-size: 12px; direction:ltr; unicode-bidi:isolate; }}
    .index-mini-quote {{ display: grid; justify-items: end; gap: 3px; }}
    .index-mini-quote strong {{ font-size: 20px; }}
    .index-mini-quote em {{ font-style: normal; font-size: 14px; font-weight: 900; }}
    .index-mini-quote a {{ color: var(--blue); font-size: 12px; font-weight: 900; }}
    .index-mini-chart {{ width: 100%; height: 430px; }}
    .distribution-mini-panel {{
      margin-top: 10px;
      border-top: 1px solid var(--line);
      padding-top: 10px;
    }}
    .distribution-mini-head {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 10px;
      margin-bottom: 4px;
    }}
    .distribution-mini-head strong {{ font-size: 14px; }}
    .distribution-mini-head span {{ color: var(--muted); font-size: 12px; text-align: right; }}
    .index-distribution-chart {{ width: 100%; height: 170px; }}
    .theme-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }}
    .index-card h3 {{ margin: 12px 0 4px; font-size: 20px; }}
    .index-card p {{ margin: 0; color: var(--muted); font-weight: 800; }}
    .quote {{ display: flex; align-items: end; justify-content: space-between; gap: 10px; }}
    .quote strong {{ font-size: 24px; letter-spacing: 0; }}
    .quote em {{ font-style: normal; font-size: 18px; font-weight: 900; }}
    .up em, .up .row-metric:nth-child(3) strong, .market-panel.up .market-main b, .stream-row.up span {{ color: var(--red); }}
    .down em, .down .row-metric:nth-child(3) strong, .market-panel.down .market-main b, .stream-row.down span {{ color: var(--green); }}
    .stream-row.watch span {{ color: var(--amber); }}
    .theme-card.up .theme-main strong, .theme-card.up .theme-foot span:last-child {{ color: var(--red); }}
    .theme-card.down .theme-main strong, .theme-card.down .theme-foot span:last-child {{ color: var(--green); }}
    .meta {{ display: flex; justify-content: space-between; gap: 8px; color: var(--muted); font-size: 12px; border-top: 1px solid var(--line); padding-top: 10px; }}
    .theme-period {{ color: var(--muted); font-size: 12px; margin-top: 4px; }}
    .theme-main {{ display: flex; align-items: end; justify-content: space-between; margin: 12px 0 10px; }}
    .theme-main span {{ color: var(--muted); font-size: 12px; }}
    .theme-main strong {{ font-size: 26px; letter-spacing: 0; }}
    .theme-metrics {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px 10px; padding: 10px 0; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }}
    .theme-metrics span {{ display: block; color: var(--muted); font-size: 11px; margin-bottom: 3px; }}
    .theme-metrics strong {{ font-size: 14px; }}
    .theme-foot {{ display: flex; justify-content: space-between; gap: 10px; color: var(--muted); font-size: 12px; border-top: 1px solid var(--line); padding-top: 10px; }}
    .theme-foot span:last-child {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .split {{ display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(320px, .72fr); gap: 14px; align-items: start; }}
    .strategy-list {{ display: grid; gap: 9px; }}
    .strategy-row {{
      display: grid;
      grid-template-columns: minmax(176px, 1.25fr) repeat(5, minmax(82px, .72fr)) auto;
      gap: 10px;
      align-items: center;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
    }}
    .row-title {{ font-size: 15px; font-weight: 900; }}
    .row-sub {{ color: var(--muted); font-size: 12px; margin-top: 3px; }}
    .row-metric span {{ display: block; color: var(--muted); font-size: 12px; margin-bottom: 3px; }}
    .row-metric strong {{ font-size: 15px; }}
    .side-panel {{ position: sticky; top: 16px; }}
    .side-panel h3 {{ margin: 0 0 12px; font-size: 17px; }}
    .mini-list {{ display: grid; gap: 8px; }}
    .mini-link {{
      display: grid;
      grid-template-columns: 82px 1fr auto;
      gap: 8px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 9px 10px;
      background: #fbfcfe;
      transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
    }}
    .mini-link span {{ font-weight: 900; }}
    .mini-link strong {{ font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .mini-link em {{ color: var(--muted); font-size: 12px; font-style: normal; }}
    .empty {{ color: var(--muted); margin: 0; }}
    [aria-disabled="true"] {{ cursor: default; pointer-events: none; opacity: .62; }}
    footer {{ margin-top: 24px; color: var(--muted); font-size: 12px; border-top: 1px solid var(--line); padding-top: 14px; }}
    @media (max-width: 1180px) {{
      .workbench {{ grid-template-columns: 1fr; }}
      .rail {{ position: static; min-height: auto; }}
      .rail-nav {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
      .rail-card {{ margin-top: 0; }}
      .market-layout, .signal-workbench, .split {{ grid-template-columns: 1fr; }}
      .side-panel {{ position: static; }}
      .index-nav-panel {{ grid-template-columns: 1fr; }}
      .selector-top {{ grid-template-columns:1fr; }}
      .selector-row {{ grid-template-columns:1fr 1fr; }}
      .index-select-list {{ grid-template-columns: repeat(2, minmax(0, 1fr)); max-height: none; }}
      .theme-grid, .kpis {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .report-entry-main, .report-entry-stats {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
      .strategy-row {{ grid-template-columns: 1fr 1fr 1fr; }}
    }}
    @media (max-width: 720px) {{
      .workbench {{ width: min(100vw - 20px, 1640px); padding-top: 10px; }}
      .desk-head {{ grid-template-columns: 1fr; }}
      .head-actions {{ justify-content: flex-start; }}
      .rail-nav, .index-select-list, .theme-grid, .signal-grid, .kpis, .field-grid, .coverage-grid, .etf-main, .report-entry-main, .report-entry-stats {{ grid-template-columns: 1fr; }}
      .selector-search, .selector-row {{ grid-template-columns: 1fr; }}
      .market-main {{ grid-template-columns: 1fr; align-items: start; }}
      .strategy-row {{ grid-template-columns: 1fr 1fr; }}
      .mini-link {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 24px; }}
    }}
  """,
        body=f"""
  <main class="workbench">
    <aside class="rail">
      <div class="brand">
        <span class="brand-mark">QY</span>
        <div><strong>QuantYB</strong><em>Research Desk</em></div>
      </div>
      <nav class="rail-nav">
        <a href="#report-entry">报告<span>{html.escape(str(data["stock_report_count"]))}</span></a>
        <a href="{html.escape(str((data.get('data_quality') or {}).get('href') or '#report-entry'))}">质量<span>{html.escape(str((data.get('data_quality') or {}).get('warning_count', 0)))}</span></a>
        <a href="#indexes">指数<span>{index_count}</span></a>
        <a href="#signals">信号<span>{signal_count}</span></a>
        <a href="#stock-selector">看股<span>{stock_selector_count}</span></a>
        <a href="#themes">题材<span>{theme_count}</span></a>
        <a href="#etf">ETF<span>{html.escape(str(etf_count))}</span></a>
        <a href="#strategies">策略<span>{strategy_count}</span></a>
      </nav>
      <div class="rail-card">
        <span>生成时间</span>
        <strong>{html.escape(data["generated_at"])}</strong>
      </div>
    </aside>

    <section class="desk">
      <header class="desk-head">
        <div>
          <h1>QuantYB 总控面板</h1>
          <p class="subtitle">市场、信号、题材、策略和个股报告的本地工作台</p>
        </div>
      </header>

      {_build_report_entry_section(data)}

      <section id="indexes" class="desk-section">
        <div class="section-head"><h2>指数导航</h2><span>左侧选择 · K线/全市场成交额/涨跌分布联动</span></div>
        <div class="index-grid">
          {_build_index_cards(data)}
        </div>
      </section>

      <section id="signals" class="desk-section">
        <div class="section-head"><h2>信号中心</h2><span>RPS · 形态 · 选股 · 雷达 · 涨停强势 · 涨跌停 · 轮动</span></div>
        {_build_signal_center(data)}
      </section>

      {_build_stock_selector_entry(data)}

      <section id="themes" class="desk-section">
        <div class="section-head"><h2>题材看板</h2><span>题材强弱和广度</span></div>
        <div class="theme-grid">
          {_build_theme_cards(data)}
        </div>
      </section>

      {_build_etf_strategy_panel(data)}

      <section id="strategies" class="split desk-section">
        <div>
          <div class="section-head"><h2>策略汇总</h2><span>批量回测画像</span></div>
          <div class="strategy-list">
            {_build_strategy_cards(data)}
          </div>
        </div>
        <aside id="recent-reports" class="side-panel">
          <h3>最近单标的报告</h3>
          <div class="mini-list">
            {_build_recent_reports(data)}
          </div>
        </aside>
      </section>

      <footer>本页只聚合本地 output 目录结果；待生成项不会参与信号计算。</footer>
    </section>
  </main>
  """,
        head_extra='<link rel="icon" href="data:,">' + _dashboard_echarts_tag(),
        scripts=json_script_data(data, "dashboard-data") + _dashboard_script(),
    )


def generate_dashboard(config: dict, output_path: str | Path | None = None) -> Path:
    reports_dir = Path(config["output"]["reports_dir"])
    out_path = Path(output_path) if output_path else reports_dir / "dashboard.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_echarts_asset(reports_dir)
    data = _collect_dashboard_data(config, out_path)
    out_path.write_text(_build_html(data), encoding="utf-8")
    return out_path
