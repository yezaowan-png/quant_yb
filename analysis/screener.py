"""Composable research screeners for local A-share K-line caches.

The screeners are deterministic research filters, not trading strategies.  They
only read local caches and slice each symbol to the requested as-of date before
calculating features, so historical scans do not use future bars.
"""

from __future__ import annotations

from dataclasses import dataclass
import html
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

from analysis.trendlines import TrendlineConfig, analyze_trendlines
from data.stock_pool import (
    StockPoolError,
    get_stock_pool_path,
    load_stock_pools,
    save_stock_pool,
    split_pool_names,
)
from visual.components import html_document, stock_link_html


@dataclass
class ScreenResult:
    preset: str
    output_path: Path
    html_path: Path
    rows: pd.DataFrame
    pool_path: Path | None = None


def _cache_dir(config: dict) -> Path:
    return Path(config["data"]["cache_dir"])


def _signals_dir(config: dict) -> Path:
    return Path(config["output"].get("signals_dir", "output/signals"))


def _load_stock_name_map(config: dict) -> dict[str, str]:
    path = Path(config.get("data", {}).get("meta_dir", "data/meta")) / "stock_names.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype=str)
    if "ts_code" not in df.columns or "name" not in df.columns:
        return {}
    return dict(zip(df["ts_code"].astype(str), df["name"].astype(str)))


def _list_cached_symbols(config: dict) -> list[str]:
    cache_dir = _cache_dir(config)
    if not cache_dir.exists():
        return []
    return sorted(path.stem.upper() for path in cache_dir.glob("*.csv") if not path.name.startswith("_"))


def _normalize_symbol(value: object) -> str:
    return str(value or "").strip().upper()


def _resolve_symbols(
    config: dict,
    pool: str | None = None,
    pool_mode: str = "any",
    symbols: Iterable[str] | None = None,
) -> list[str]:
    if symbols:
        seen = set()
        result = []
        for raw in symbols:
            symbol = _normalize_symbol(raw)
            if symbol and symbol not in seen:
                seen.add(symbol)
                result.append(symbol)
        return result
    if pool:
        from data.stock_pool import resolve_pool_symbols

        return resolve_pool_symbols(config, pool, pool_mode)
    return _list_cached_symbols(config)


def _load_kline(config: dict, symbol: str) -> pd.DataFrame | None:
    path = _cache_dir(config) / f"{symbol}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, dtype={"date": str})
    if "date" not in df.columns or "close" not in df.columns:
        return None
    df = df.copy()
    df["date"] = df["date"].astype(str).str.replace("-", "", regex=False)
    for column in ("open", "high", "low", "close", "volume", "amount", "pct_chg"):
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    if "open" not in df.columns:
        df["open"] = df["close"]
    if "high" not in df.columns:
        df["high"] = df["close"]
    if "low" not in df.columns:
        df["low"] = df["close"]
    if "volume" not in df.columns:
        df["volume"] = 0.0
    return df.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)


def _date_key(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.replace("-", "")[:8]


def _line_value(line: dict, index: int | float) -> float:
    return float(line["slope"]) * float(index) + float(line["intercept"])


def _slice_as_of(df: pd.DataFrame, trade_date: str | None, lookback: int) -> pd.DataFrame:
    result = df.copy()
    if trade_date:
        cutoff = _date_key(trade_date)
        result = result[result["date"].astype(str).str.replace("-", "", regex=False) <= cutoff]
    if int(lookback) > 0:
        result = result.tail(int(lookback))
    return result.reset_index(drop=True)


def _selected_pool_members(config: dict, pool: str | None) -> dict[str, set[str]]:
    if not pool:
        return {}
    names = split_pool_names(pool)
    if not names:
        return {}
    pools = load_stock_pools(get_stock_pool_path(config))
    return {name: set(pools.get(name, [])) for name in names}


def _matched_pool_text(symbol: str, pool_members: dict[str, set[str]]) -> str:
    if not pool_members:
        return ""
    matched = [name for name, members in pool_members.items() if symbol in members]
    return ",".join(matched)


def _empty_screen_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "signal_date",
            "ts_code",
            "name",
            "preset",
            "score",
            "close",
            "trendline_price",
            "distance_pct",
            "line_score",
            "touch_count",
            "violation_count",
            "matched_pool",
            "reason",
        ]
    )


def scan_trendline_pullback(
    df: pd.DataFrame,
    *,
    touch_days: int = 3,
    max_distance_pct: float = 1.5,
    break_pct: float = 1.0,
    pivot_window: int = 5,
    max_lines: int = 3,
) -> dict | None:
    """Return a hit when price recently pulls back near a valid uptrend line."""
    if df.empty:
        return None
    min_bars = max(int(pivot_window) * 2 + 5, 20)
    if len(df) < min_bars:
        return None

    cfg = TrendlineConfig(
        pivot_window=int(pivot_window),
        max_trend_lines=max(int(max_lines), 1),
        tolerance_pct=max(float(max_distance_pct) / 100.0, 0.0001),
    )
    analysis = analyze_trendlines(df, cfg)
    uptrend_lines = analysis.get("uptrend_lines") or []
    if not uptrend_lines:
        return None

    latest = df.iloc[-1]
    latest_index = len(df) - 1
    latest_close = float(latest["close"])
    recent_start = max(0, len(df) - max(int(touch_days), 1))
    recent = df.iloc[recent_start:].copy()

    best_hit: dict | None = None
    for line in uptrend_lines:
        latest_line_price = _line_value(line, latest_index)
        if latest_line_price <= 0:
            continue
        if latest_close < latest_line_price * (1.0 - float(break_pct) / 100.0):
            continue

        touch_payloads = []
        for row_index, row in recent.iterrows():
            line_price = _line_value(line, int(row_index))
            if line_price <= 0:
                continue
            low_distance_pct = (float(row["low"]) - line_price) / line_price * 100.0
            close_distance_pct = (float(row["close"]) - line_price) / line_price * 100.0
            min_abs_distance = min(abs(low_distance_pct), abs(close_distance_pct))
            if min_abs_distance <= float(max_distance_pct):
                touch_payloads.append(
                    {
                        "index": int(row_index),
                        "date": _date_key(row["date"]),
                        "line_price": line_price,
                        "min_abs_distance": min_abs_distance,
                        "low_distance_pct": low_distance_pct,
                        "close_distance_pct": close_distance_pct,
                    }
                )

        if not touch_payloads:
            continue

        touch = min(touch_payloads, key=lambda item: (item["min_abs_distance"], -item["index"]))
        days_since_touch = latest_index - int(touch["index"])
        current_distance_pct = (latest_close - latest_line_price) / latest_line_price * 100.0
        line_score = float(line.get("score", 0.0))
        line_component = min(line_score, 140.0) / 140.0 * 60.0
        distance_component = max(0.0, 1.0 - float(touch["min_abs_distance"]) / max(float(max_distance_pct), 1e-9)) * 25.0
        recency_component = max(0.0, (max(int(touch_days), 1) - days_since_touch) / max(int(touch_days), 1)) * 15.0
        violation_penalty = min(float(line.get("violation_count", 0)) * 2.0, 15.0)
        score = max(0.0, min(100.0, line_component + distance_component + recency_component - violation_penalty))
        reason = (
            f"上升趋势线有效, 最近{max(int(touch_days), 1)}日触线; "
            f"触线日{touch['date']}, 距离{touch['min_abs_distance']:.2f}%; "
            f"当前收盘距趋势线{current_distance_pct:.2f}%"
        )
        payload = {
            "score": round(score, 2),
            "close": round(latest_close, 4),
            "trendline_price": round(latest_line_price, 4),
            "distance_pct": round(current_distance_pct, 4),
            "line_score": round(line_score, 2),
            "touch_count": int(line.get("touch_count", 0)),
            "violation_count": int(line.get("violation_count", 0)),
            "touch_date": touch["date"],
            "touch_days_ago": int(days_since_touch),
            "touch_distance_pct": round(float(touch["min_abs_distance"]), 4),
            "line_start_date": line.get("start_date", ""),
            "line_slope": line.get("slope", 0.0),
            "reason": reason,
        }
        if best_hit is None or float(payload["score"]) > float(best_hit["score"]):
            best_hit = payload

    return best_hit


SCREEN_PRESETS: dict[str, Callable[..., dict | None]] = {
    "trendline_pullback": scan_trendline_pullback,
}

SCREEN_LABELS = {
    "trendline_pullback": "趋势线回踩",
}


def screen_stocks(
    config: dict,
    preset: str = "trendline_pullback",
    pool: str | None = None,
    pool_mode: str = "any",
    symbols: Iterable[str] | None = None,
    trade_date: str | None = None,
    lookback: int = 250,
    top: int = 100,
    **params,
) -> pd.DataFrame:
    preset = str(preset or "").strip()
    if preset not in SCREEN_PRESETS:
        available = ", ".join(sorted(SCREEN_PRESETS))
        raise ValueError(f"未知筛选预设: {preset}。可用: {available}")

    scanner = SCREEN_PRESETS[preset]
    names = _load_stock_name_map(config)
    pool_members = _selected_pool_members(config, pool)
    rows = []
    for symbol in _resolve_symbols(config, pool=pool, pool_mode=pool_mode, symbols=symbols):
        df = _load_kline(config, symbol)
        if df is None or df.empty:
            continue
        sliced = _slice_as_of(df, trade_date=trade_date, lookback=lookback)
        if sliced.empty:
            continue
        hit = scanner(sliced, **params)
        if not hit:
            continue
        row = {
            "signal_date": _date_key(sliced["date"].iloc[-1]),
            "ts_code": symbol,
            "name": names.get(symbol, ""),
            "preset": preset,
            "preset_name": SCREEN_LABELS.get(preset, preset),
            "matched_pool": _matched_pool_text(symbol, pool_members),
        }
        row.update(hit)
        rows.append(row)

    if not rows:
        return _empty_screen_frame()

    result = pd.DataFrame(rows).sort_values(["score", "ts_code"], ascending=[False, True]).reset_index(drop=True)
    if int(top) > 0:
        result = result.head(int(top)).reset_index(drop=True)
    return result


def _safe_name(value: object) -> str:
    text = str(value or "").strip()
    for old in (",", "/", "\\", " "):
        text = text.replace(old, "_")
    return text


def _table_html(df: pd.DataFrame, output_path: Path, config: dict | None = None, limit: int = 200) -> str:
    if df.empty:
        return '<p class="empty">暂无命中股票</p>'
    header = "".join(f"<th>{html.escape(str(column))}</th>" for column in df.columns)
    rows = []
    for _, row in df.head(limit).iterrows():
        cells = []
        for column, value in row.items():
            if column == "ts_code" and not pd.isna(value):
                cells.append(f"<td>{stock_link_html(config, output_path, value)}</td>")
            else:
                cells.append(f"<td>{html.escape('' if pd.isna(value) else str(value))}</td>")
        cells = "".join(cells)
        rows.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _write_report(title: str, subtitle: str, df: pd.DataFrame, output_path: Path, config: dict | None = None) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        html_document(
            title=title,
            styles="""
            body { margin: 0; background: #f4f6fa; color: #1f2937; font-family: "Microsoft YaHei", "Noto Sans SC", sans-serif; }
            main { width: min(1280px, calc(100vw - 40px)); margin: 0 auto; padding: 28px 0 44px; }
            h1 { margin: 0 0 8px; font-size: 28px; }
            .sub { color: #667085; margin-bottom: 18px; }
            table { width: 100%; border-collapse: collapse; background: white; border: 1px solid #d9e2ef; }
            th, td { padding: 8px 10px; border-bottom: 1px solid #e6edf5; text-align: left; font-size: 13px; vertical-align: top; }
            th { background: #eef4ff; color: #334155; }
            td:nth-child(5), td:nth-child(7), td:nth-child(8), td:nth-child(9) { text-align: right; }
            a.stock-link { color: #2454a6; font-weight: 700; text-decoration: none; }
            a.stock-link:hover { text-decoration: underline; }
            .empty { background: white; border: 1px solid #d9e2ef; padding: 18px; }
            """,
            body=f"""
            <main>
              <h1>{html.escape(title)}</h1>
              <div class="sub">{html.escape(subtitle)}</div>
              {_table_html(df, output_path, config)}
            </main>
            """,
        ),
        encoding="utf-8",
    )
    return output_path


def save_screen(
    config: dict,
    preset: str = "trendline_pullback",
    pool: str | None = None,
    pool_mode: str = "any",
    symbols: Iterable[str] | None = None,
    trade_date: str | None = None,
    lookback: int = 250,
    top: int = 100,
    save_pool: bool = False,
    pool_name: str | None = None,
    merge_pool: bool = False,
    **params,
) -> ScreenResult:
    rows = screen_stocks(
        config,
        preset=preset,
        pool=pool,
        pool_mode=pool_mode,
        symbols=symbols,
        trade_date=trade_date,
        lookback=lookback,
        top=top,
        **params,
    )
    date_part = (
        str(rows["signal_date"].max())
        if not rows.empty and "signal_date" in rows.columns
        else (_date_key(trade_date) if trade_date else pd.Timestamp.today().strftime("%Y%m%d"))
    )
    safe_pool = f"_{_safe_name(pool)}" if pool else ""
    out_dir = _signals_dir(config)
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / f"screen_signals_{preset}{safe_pool}_{date_part}.csv"
    html_path = out_dir / f"screen_signals_{preset}{safe_pool}_{date_part}.html"
    rows.to_csv(output_path, index=False)
    title = f"{SCREEN_LABELS.get(preset, preset)} 选股筛选"
    subtitle = (
        f"本地K线缓存 · 截止 {date_part} · lookback {int(lookback)} · "
        "只使用截止日及以前数据"
    )
    _write_report(title, subtitle, rows, html_path, config)

    pool_path: Path | None = None
    if save_pool:
        if not pool_name:
            raise StockPoolError("保存筛选结果为股票池时必须指定 --pool-name")
        description = f"{title} · {date_part} · 来源 {output_path.name}"
        pool_path = save_stock_pool(
            config,
            pool_name,
            rows[["ts_code", "name"]].to_dict("records") if not rows.empty else [],
            description=description,
            merge=merge_pool,
        )

    return ScreenResult(preset, output_path, html_path, rows, pool_path)
