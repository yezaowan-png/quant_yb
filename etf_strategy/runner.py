"""ETF strategy report runner."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from visual.etf_strategy_report import generate_etf_strategy_report

from .config import etf_strategy_config
from .data_provider import EtfDataProvider, normalize_etf_symbol
from .signal_provider import ExternalSignalProvider, parse_rank_emotion_frame, red_green_decision
from .strategies import (
    atr_stop,
    bollinger_breakout,
    kama_timing,
    latest_signal_text,
    macd_timing,
    momentum_rotation,
    n_day_breakout,
    three_factor_rotation,
)


DEFAULT_ETF_POOL = [
    {"symbol": "515880.SH", "name": "通信ETF"},
    {"symbol": "159919.SZ", "name": "沪深300ETF"},
    {"symbol": "588200.SH", "name": "科创芯片ETF"},
    {"symbol": "513000.SH", "name": "日经225ETF"},
    {"symbol": "512760.SH", "name": "芯片ETF"},
]

_STOCK_NAME_CACHE: dict[str, dict[str, str]] = {}
_TUSHARE_HOLDINGS_DISABLED = False


def load_etf_pool(config: dict[str, Any], symbols: str | None = None) -> list[dict[str, str]]:
    if symbols:
        return [
            {
                "symbol": normalize_etf_symbol(symbol),
                "name": normalize_etf_symbol(symbol),
                "category": "自选",
                "subcategory": "命令行",
            }
            for symbol in symbols.split(",")
            if symbol.strip()
        ]
    configured = config.get("etf_strategy", {}).get("pool") or DEFAULT_ETF_POOL
    result: list[dict[str, str]] = []
    for item in configured:
        if isinstance(item, str):
            symbol = normalize_etf_symbol(item)
            result.append({"symbol": symbol, "name": symbol, "category": "未分组", "subcategory": "未分组"})
        elif isinstance(item, dict) and item.get("symbol"):
            symbol = normalize_etf_symbol(str(item["symbol"]))
            result.append(
                {
                    "symbol": symbol,
                    "name": str(item.get("name") or symbol),
                    "category": str(item.get("category") or "未分组"),
                    "subcategory": str(item.get("subcategory") or "未分组"),
                }
            )
    return result


def run_etf_strategy_report(
    config: dict[str, Any],
    symbols: str | None = None,
    start: str | None = None,
    end: str | None = None,
    force: bool = False,
    output: str | Path | None = None,
) -> dict[str, Any]:
    provider = EtfDataProvider(config)
    pool = load_etf_pool(config, symbols)
    section = etf_strategy_config(config)
    start = start or _default_etf_start(section)
    data: dict[str, pd.DataFrame] = {}
    load_errors: dict[str, str] = {}
    for item in pool:
        symbol = item["symbol"]
        try:
            frame = provider.get_daily_bars(symbol, start=start, end=end, force=force)
        except Exception as exc:
            load_errors[symbol] = str(exc)
            continue
        if frame.empty:
            load_errors[symbol] = "无日线数据"
            continue
        data[symbol] = frame
    if not data:
        raise ValueError("没有可用 ETF 日线数据，无法生成 ETF 策略板块")

    timing_params = section.get("timing", {})
    rotation_params = section.get("rotation", {})
    latest_rows = _latest_signal_rows(pool, data, timing_params)
    momentum = momentum_rotation(
        data,
        momentum_window=int(rotation_params.get("momentum_window", 20)),
        hold_period=int(rotation_params.get("hold_period", 5)),
        hold_count=int(rotation_params.get("hold_count", 3)),
    )
    factor = three_factor_rotation(
        data,
        trend_window=int(rotation_params.get("trend_window", 15)),
        momentum_short=int(rotation_params.get("momentum_short", 5)),
        momentum_long=int(rotation_params.get("momentum_long", 10)),
        volume_short=int(rotation_params.get("volume_short", 5)),
        volume_long=int(rotation_params.get("volume_long", 15)),
        min_slope=float(rotation_params.get("min_slope", 0.0)),
        hold_period=int(rotation_params.get("hold_period", 5)),
        hold_count=int(rotation_params.get("factor_hold_count", 1)),
        trend_weight=float(rotation_params.get("trend_weight", 0.4)),
        momentum_weight=float(rotation_params.get("momentum_weight", 0.3)),
        volume_weight=float(rotation_params.get("volume_weight", 0.3)),
    )

    external = ExternalSignalProvider(config)
    rank_frame = external.load_rank_emotion_signal()
    red_green_frame = external.load_red_green_signal()
    rank_emotion = parse_rank_emotion_frame(
        rank_frame,
        top_n=int(section.get("rank_top_n", 10)),
    )
    if external.download_errors:
        rank_emotion["download_errors"] = external.download_errors.copy()
        rank_emotion["log"] = f"{rank_emotion.get('log', '')}；FTP下载错误：{'；'.join(external.download_errors)}"
    red_green = [
        red_green_decision(red_green_frame, symbol)
        for symbol in data
    ]

    stats_dir = Path(config.get("output", {}).get("statistics_dir", "output/statistics")) / "etf_strategy"
    reports_dir = Path(config.get("output", {}).get("reports_dir", "output/reports")) / "etf_strategy"
    stats_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = Path(output) if output else reports_dir / "etf_strategy_dashboard.html"

    summary = _summary_frame(latest_rows, momentum["ranking"], factor["ranking"])
    summary_path = stats_dir / "etf_strategy_summary.csv"
    timing_path = stats_dir / "etf_strategy_timing_signals.csv"
    momentum_path = stats_dir / "etf_strategy_momentum_ranking.csv"
    factor_path = stats_dir / "etf_strategy_three_factor_ranking.csv"
    summary.to_csv(summary_path, index=False)
    pd.DataFrame(latest_rows).to_csv(timing_path, index=False)
    momentum["ranking"].to_csv(momentum_path, index=False)
    factor["ranking"].to_csv(factor_path, index=False)

    generate_etf_strategy_report(
        config=config,
        output_path=report_path,
        summary=summary,
        timing_rows=latest_rows,
        momentum_ranking=momentum["ranking"],
        factor_ranking=factor["ranking"],
        rank_emotion=rank_emotion,
        red_green=red_green,
        load_errors=load_errors,
        kline_payload=_etf_kline_payload(pool, data, config=config),
        artifacts={
            "summary": summary_path,
            "timing": timing_path,
            "momentum": momentum_path,
            "factor": factor_path,
        },
    )
    return {
        "report_path": report_path,
        "summary_path": summary_path,
        "timing_path": timing_path,
        "momentum_path": momentum_path,
        "factor_path": factor_path,
        "loaded": sorted(data),
        "errors": load_errors,
        "external_signal_errors": external.download_errors.copy(),
    }


def _latest_signal_rows(pool: list[dict[str, str]], data: dict[str, pd.DataFrame], params: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    names = {item["symbol"]: item["name"] for item in pool}
    categories = {item["symbol"]: item.get("category", "未分组") for item in pool}
    subcategories = {item["symbol"]: item.get("subcategory", "未分组") for item in pool}
    for symbol, frame in data.items():
        macd = macd_timing(
            frame,
            fast=int(params.get("macd_fast", 12)),
            slow=int(params.get("macd_slow", 26)),
            signal_period=int(params.get("macd_signal", 9)),
        )
        kama = kama_timing(
            frame,
            fast_period=int(params.get("kama_fast", 10)),
            slow_period=int(params.get("kama_slow", 20)),
        )
        boll = bollinger_breakout(
            frame,
            period=int(params.get("boll_period", 20)),
            upper_mult=float(params.get("boll_upper_mult", 1.2)),
            lower_mult=float(params.get("boll_lower_mult", 1.2)),
        )
        breakout = n_day_breakout(
            frame,
            high_days=int(params.get("break_high_days", 15)),
            low_days=int(params.get("break_low_days", 5)),
        )
        atr = atr_stop(
            frame,
            high_days=int(params.get("atr_high_days", 15)),
            low_days=int(params.get("atr_low_days", 5)),
            win_mult=float(params.get("atr_win_mult", 3.4)),
            loss_mult=float(params.get("atr_loss_mult", 1.8)),
        )
        latest_date = frame.index[-1]
        rows.append(
            {
                "symbol": symbol,
                "name": names.get(symbol, symbol),
                "category": categories.get(symbol, "未分组"),
                "subcategory": subcategories.get(symbol, "未分组"),
                "date": latest_date.strftime("%Y-%m-%d"),
                "close": round(float(frame["Close"].iloc[-1]), 4),
                "return_20d_pct": _return_pct(frame, 20),
                "macd_signal": int(macd["signal"]),
                "macd_action": latest_signal_text(macd["signal"]),
                "kama_signal": int(kama["signal"]),
                "kama_action": latest_signal_text(kama["signal"]),
                "boll_signal": int(boll["signal"]),
                "boll_action": latest_signal_text(boll["signal"]),
                "breakout_signal": int(breakout["signal"]),
                "breakout_action": latest_signal_text(breakout["signal"]),
                "atr_signal": int(atr["signal"]),
                "atr_action": latest_signal_text(atr["signal"]),
                "history_bars": int(len(frame)),
            }
        )
    return rows


def _summary_frame(
    latest_rows: list[dict[str, Any]],
    momentum_ranking: pd.DataFrame,
    factor_ranking: pd.DataFrame,
) -> pd.DataFrame:
    summary = pd.DataFrame(latest_rows)
    if summary.empty:
        return summary
    if not momentum_ranking.empty:
        latest_date = momentum_ranking["date"].max()
        latest = momentum_ranking.loc[momentum_ranking["date"] == latest_date, ["symbol", "momentum", "rank", "target"]]
        latest = latest.rename(columns={"momentum": "momentum_score", "rank": "momentum_rank", "target": "momentum_target"})
        summary = summary.merge(latest, on="symbol", how="left")
    if not factor_ranking.empty:
        latest_date = factor_ranking["date"].max()
        latest = factor_ranking.loc[factor_ranking["date"] == latest_date, ["symbol", "score_norm", "rank", "target"]]
        latest = latest.rename(columns={"score_norm": "factor_score", "rank": "factor_rank", "target": "factor_target"})
        summary = summary.merge(latest, on="symbol", how="left")
    return summary.sort_values(["momentum_rank", "factor_rank", "symbol"], na_position="last").reset_index(drop=True)


def _etf_kline_payload(
    pool: list[dict[str, str]],
    data: dict[str, pd.DataFrame],
    config: dict[str, Any] | None = None,
    limit: int = 520,
) -> dict[str, Any]:
    meta = {item["symbol"]: item for item in pool}
    etf_config = ((config or {}).get("etf_strategy", {}) or {})
    timing = etf_config.get("timing", {}) or {}
    limit = int(etf_config.get("kline_display_bars", limit) or limit)
    boll_period = int(timing.get("boll_period", 20) or 20)
    upper_mult = float(timing.get("boll_upper_mult", 1.2) or 1.2)
    lower_mult = float(timing.get("boll_lower_mult", 1.2) or 1.2)
    payload: dict[str, Any] = {}
    for symbol, frame in data.items():
        work = frame.tail(limit).copy()
        if work.empty:
            continue
        dates = [pd.to_datetime(item).strftime("%Y-%m-%d") for item in work.index]
        close = pd.to_numeric(work["Close"], errors="coerce")
        volume = pd.to_numeric(work["Volume"], errors="coerce")
        amount = pd.to_numeric(work["Amount"], errors="coerce") if "Amount" in work.columns else close * volume
        boll_mid = close.rolling(boll_period, min_periods=1).mean()
        boll_std = close.rolling(boll_period, min_periods=2).std().fillna(0)
        payload[symbol] = {
            "symbol": symbol,
            "name": meta.get(symbol, {}).get("name", symbol),
            "category": meta.get(symbol, {}).get("category", "未分组"),
            "subcategory": meta.get(symbol, {}).get("subcategory", "未分组"),
            "adjust": str(etf_config.get("adjust") or "none"),
            "holdings": _load_etf_holdings(config or {}, symbol),
            "dates": dates,
            "ohlc": [
                [
                    _round_or_none(row.Open),
                    _round_or_none(row.Close),
                    _round_or_none(row.Low),
                    _round_or_none(row.High),
                ]
                for row in work.itertuples()
            ],
            "volume": [_round_or_none(value, 0) for value in volume.tolist()],
            "amount": [_round_or_none(value, 0) for value in amount.tolist()],
            "ma5": [_round_or_none(value) for value in close.rolling(5, min_periods=1).mean().tolist()],
            "ma10": [_round_or_none(value) for value in close.rolling(10, min_periods=1).mean().tolist()],
            "ma20": [_round_or_none(value) for value in close.rolling(20, min_periods=1).mean().tolist()],
            "ma60": [_round_or_none(value) for value in close.rolling(60, min_periods=1).mean().tolist()],
            "boll_mid": [_round_or_none(value) for value in boll_mid.tolist()],
            "boll_upper": [_round_or_none(value) for value in (boll_mid + upper_mult * boll_std).tolist()],
            "boll_lower": [_round_or_none(value) for value in (boll_mid - lower_mult * boll_std).tolist()],
        }
    return payload


def _load_etf_holdings(config: dict[str, Any], symbol: str, limit: int = 20) -> list[dict[str, Any]]:
    root_value = ((config.get("etf_strategy") or {}).get("holdings_dir") or "")
    root = Path(root_value) if root_value else None
    normalized = normalize_etf_symbol(symbol)
    if root is not None:
        cached = _read_etf_holdings_cache(root, normalized, limit=limit)
        if cached:
            return cached
    fetched = _fetch_tushare_etf_holdings(config, normalized, limit=limit)
    if fetched and root is not None:
        root.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(fetched).to_csv(root / f"{normalized}.csv", index=False)
    return fetched


def _read_etf_holdings_cache(root: Path, symbol: str, limit: int = 20) -> list[dict[str, Any]]:
    candidates = [
        root / f"{symbol}.csv",
        root / f"{symbol.replace('.', '_')}.csv",
        root / f"{symbol[:6]}.csv",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            frame = pd.read_csv(path, dtype=str)
        except Exception:
            continue
        return _normalize_holdings_frame(frame, limit=limit)
    return []


def _fetch_tushare_etf_holdings(config: dict[str, Any], symbol: str, limit: int = 20) -> list[dict[str, Any]]:
    global _TUSHARE_HOLDINGS_DISABLED
    if _TUSHARE_HOLDINGS_DISABLED:
        return []
    token = ((config.get("tushare") or {}).get("token") or "").strip()
    if not token:
        return []
    try:
        import tushare as ts

        pro = ts.pro_api(token)
        frame = pro.query("fund_portfolio", ts_code=symbol)
    except Exception:
        _TUSHARE_HOLDINGS_DISABLED = True
        return []
    if frame is None or frame.empty:
        return []
    if "end_date" in frame.columns:
        latest_period = pd.to_numeric(frame["end_date"], errors="coerce").max()
        frame = frame.loc[pd.to_numeric(frame["end_date"], errors="coerce") == latest_period]
    if "mkv" in frame.columns:
        frame = frame.assign(_mkv=pd.to_numeric(frame["mkv"], errors="coerce")).sort_values("_mkv", ascending=False)
    names = _load_stock_name_map(config)
    if "symbol" in frame.columns:
        frame = frame.copy()
        frame["stock_name"] = frame["symbol"].astype(str).map(names).fillna("")
    return _normalize_holdings_frame(frame, limit=limit)


def _normalize_holdings_frame(frame: pd.DataFrame, limit: int = 20) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    work = frame.copy()
    if "mkv" not in work.columns and "持有股票市值(元)" in work.columns:
        work["mkv"] = work["持有股票市值(元)"]
    if "amount" not in work.columns and "持有股票数量（股）" in work.columns:
        work["amount"] = work["持有股票数量（股）"]
    mkv = pd.to_numeric(work.get("mkv"), errors="coerce") if "mkv" in work.columns else pd.Series(dtype=float)
    mkv_sum = float(mkv.sum()) if not mkv.empty and pd.notna(mkv.sum()) else 0.0
    rows: list[dict[str, Any]] = []
    for idx, row in work.head(limit).iterrows():
        stock_code = row.get("stock_code") or row.get("symbol") or row.get("code") or row.get("证券代码") or row.get("ts_code") or ""
        stock_name = row.get("stock_name") or row.get("name") or row.get("股票名称") or row.get("证券名称") or ""
        raw_weight = row.get("weight") or row.get("mkv_ratio") or row.get("持仓占比") or row.get("占比") or ""
        row_mkv = pd.to_numeric(row.get("mkv"), errors="coerce")
        weight = str(raw_weight) if raw_weight not in (None, "") else ""
        if not weight and mkv_sum > 0 and pd.notna(row_mkv):
            weight = f"{float(row_mkv) / mkv_sum * 100:.2f}%"
        rows.append(
            {
                "code": str(stock_code),
                "name": str(stock_name or stock_code),
                "weight": weight,
                "mkv": _round_or_none(row_mkv, 0),
                "amount": _round_or_none(row.get("amount"), 0),
                "end_date": str(row.get("end_date") or row.get("报告期") or ""),
                "ann_date": str(row.get("ann_date") or row.get("公告日期") or ""),
            }
        )
    return rows


def _load_stock_name_map(config: dict[str, Any]) -> dict[str, str]:
    meta_dir = Path((config.get("data") or {}).get("meta_dir") or "data/meta")
    key = str(meta_dir)
    if key in _STOCK_NAME_CACHE:
        return _STOCK_NAME_CACHE[key]
    names: dict[str, str] = {}
    candidates = [meta_dir / "stock_basic.csv", meta_dir / "stock_basic_L.csv"]
    for path in candidates:
        if not path.exists():
            continue
        try:
            frame = pd.read_csv(path, dtype=str)
        except Exception:
            continue
        code_col = "ts_code" if "ts_code" in frame.columns else "symbol" if "symbol" in frame.columns else ""
        name_col = "name" if "name" in frame.columns else "股票名称" if "股票名称" in frame.columns else ""
        if code_col and name_col:
            names.update(dict(zip(frame[code_col].astype(str), frame[name_col].astype(str))))
            break
    if not names:
        token = ((config.get("tushare") or {}).get("token") or "").strip()
        if token:
            try:
                import tushare as ts

                frame = ts.pro_api(token).query("stock_basic", exchange="", list_status="L", fields="ts_code,name")
                if frame is not None and not frame.empty:
                    names.update(dict(zip(frame["ts_code"].astype(str), frame["name"].astype(str))))
                    meta_dir.mkdir(parents=True, exist_ok=True)
                    frame.to_csv(meta_dir / "stock_basic.csv", index=False)
            except Exception:
                pass
    _STOCK_NAME_CACHE[key] = names
    return names


def _round_or_none(value: Any, digits: int = 4) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    return round(number, digits)


def _return_pct(frame: pd.DataFrame, window: int) -> float | None:
    if len(frame) <= window:
        return None
    value = float(frame["Close"].iloc[-1] / frame["Close"].iloc[-window - 1] - 1) * 100
    return round(value, 2)


def _default_etf_start(section: dict[str, Any]) -> str | None:
    if section.get("start_date"):
        return str(section.get("start_date"))
    years = int(section.get("history_years", 0) or 0)
    if years <= 0:
        return None
    return (pd.Timestamp.today().normalize() - pd.DateOffset(years=years)).strftime("%Y%m%d")
