"""RPS relative strength analysis from local K-line caches."""

from __future__ import annotations

from dataclasses import dataclass
import html
from pathlib import Path
from typing import Iterable

import pandas as pd

from data.stock_pool import resolve_pool_symbols
from visual.components import html_document, stock_link_html


@dataclass
class RpsTopResult:
    window: int
    trade_date: str
    output_path: Path
    html_path: Path
    rows: pd.DataFrame


@dataclass
class RpsTrackResult:
    symbol: str
    window: int
    output_path: Path
    html_path: Path
    rows: pd.DataFrame


def _cache_dir(config: dict) -> Path:
    return Path(config["data"]["cache_dir"])


def _stats_dir(config: dict) -> Path:
    return Path(config["output"].get("statistics_dir", "output/statistics"))


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
    symbols = []
    for path in cache_dir.glob("*.csv"):
        if path.name.startswith("_"):
            continue
        symbols.append(path.stem.upper())
    return sorted(symbols)


def _resolve_symbols(
    config: dict,
    symbols: Iterable[str] | None = None,
    pool: str | None = None,
    pool_mode: str = "any",
) -> list[str]:
    if symbols:
        result = []
        seen = set()
        for symbol in symbols:
            normalized = str(symbol).strip().upper()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result
    if pool:
        return resolve_pool_symbols(config, pool, pool_mode)
    return _list_cached_symbols(config)


def _load_close_series(config: dict, symbol: str) -> pd.Series | None:
    path = _cache_dir(config) / f"{symbol}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, dtype={"date": str})
    if "date" not in df.columns or "close" not in df.columns:
        return None
    df["date"] = df["date"].astype(str).str.replace("-", "", regex=False)
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["date", "close"]).sort_values("date")
    if df.empty:
        return None
    return pd.Series(df["close"].to_numpy(), index=df["date"].astype(str), name=symbol)


def build_rps_table(
    config: dict,
    window: int = 120,
    symbols: Iterable[str] | None = None,
    pool: str | None = None,
    pool_mode: str = "any",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return `(rps, returns)` wide tables indexed by trade date.

    RPS is calculated cross-sectionally for each trade date as percentile rank
    of `window`-day return. Higher return means higher RPS, with 100 as the
    strongest available member on that date.
    """
    if int(window) <= 0:
        raise ValueError("window 必须为正整数")
    selected = _resolve_symbols(config, symbols=symbols, pool=pool, pool_mode=pool_mode)
    returns: dict[str, pd.Series] = {}
    for symbol in selected:
        close = _load_close_series(config, symbol)
        if close is None or len(close) <= window:
            continue
        returns[symbol] = (close / close.shift(window) - 1.0) * 100

    if not returns:
        empty = pd.DataFrame()
        return empty, empty

    ret_df = pd.DataFrame(returns).sort_index()
    ret_df = ret_df.dropna(axis=0, how="all")
    rps = ret_df.rank(axis=1, pct=True, method="max") * 100
    return rps.round(4), ret_df.round(4)


def latest_rps_top(
    config: dict,
    window: int = 120,
    top: int = 50,
    trade_date: str | None = None,
    pool: str | None = None,
    pool_mode: str = "any",
) -> tuple[str, pd.DataFrame]:
    rps, returns = build_rps_table(config, window=window, pool=pool, pool_mode=pool_mode)
    if rps.empty:
        return "", pd.DataFrame(
            columns=["rank", "trade_date", "ts_code", "name", "rps", "return_pct", "window"]
        )

    if trade_date:
        normalized_date = str(trade_date).replace("-", "")
        available = [date for date in rps.index.astype(str) if date <= normalized_date]
        if not available:
            raise ValueError(f"没有不晚于 {trade_date} 的 RPS 数据")
        selected_date = available[-1]
    else:
        selected_date = str(rps.index[-1])

    names = _load_stock_name_map(config)
    rows = []
    scores = rps.loc[selected_date].dropna().sort_values(ascending=False).head(int(top))
    for rank, (symbol, score) in enumerate(scores.items(), start=1):
        rows.append(
            {
                "rank": rank,
                "trade_date": selected_date,
                "ts_code": symbol,
                "name": names.get(symbol, ""),
                "rps": round(float(score), 2),
                "return_pct": round(float(returns.loc[selected_date, symbol]), 2)
                if symbol in returns.columns and pd.notna(returns.loc[selected_date, symbol])
                else None,
                "window": int(window),
            }
        )
    return selected_date, pd.DataFrame(rows)


def rps_track(config: dict, symbol: str, window: int = 120) -> pd.DataFrame:
    symbol = str(symbol).strip().upper()
    rps, returns = build_rps_table(config, window=window)
    if rps.empty or symbol not in rps.columns:
        return pd.DataFrame(columns=["trade_date", "ts_code", "rps", "return_pct", "window"])
    rows = pd.DataFrame(
        {
            "trade_date": rps.index.astype(str),
            "ts_code": symbol,
            "rps": rps[symbol],
            "return_pct": returns[symbol],
            "window": int(window),
        }
    )
    return rows.dropna(subset=["rps"]).reset_index(drop=True)


def _table_html(df: pd.DataFrame, output_path: Path, config: dict | None = None, limit: int = 80) -> str:
    if df.empty:
        return '<p class="empty">暂无数据</p>'
    header = "".join(f"<th>{html.escape(str(col))}</th>" for col in df.columns)
    body = []
    for _, row in df.head(limit).iterrows():
        cells = []
        for column, value in row.items():
            if column == "ts_code" and not pd.isna(value):
                cells.append(f"<td>{stock_link_html(config, output_path, value)}</td>")
            else:
                cells.append(f"<td>{html.escape('' if pd.isna(value) else str(value))}</td>")
        cells = "".join(cells)
        body.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _write_simple_report(title: str, subtitle: str, df: pd.DataFrame, output_path: Path, config: dict | None = None) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = html_document(
        title=title,
        styles="""
        body { margin: 0; background: #f4f6fa; color: #1f2937; font-family: "Microsoft YaHei", "Noto Sans SC", sans-serif; }
        main { width: min(1180px, calc(100vw - 40px)); margin: 0 auto; padding: 28px 0 44px; }
        h1 { margin: 0 0 8px; font-size: 28px; }
        .sub { color: #667085; margin-bottom: 18px; }
        table { width: 100%; border-collapse: collapse; background: white; border: 1px solid #d9e2ef; }
        th, td { padding: 9px 10px; border-bottom: 1px solid #e6edf5; text-align: right; font-size: 13px; }
        th { background: #eef4ff; color: #334155; }
        th:nth-child(3), td:nth-child(3), th:nth-child(4), td:nth-child(4) { text-align: left; }
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
    )
    output_path.write_text(content, encoding="utf-8")
    return output_path


def save_rps_top(
    config: dict,
    window: int = 120,
    top: int = 50,
    trade_date: str | None = None,
    pool: str | None = None,
    pool_mode: str = "any",
) -> RpsTopResult:
    selected_date, rows = latest_rps_top(
        config, window=window, top=top, trade_date=trade_date, pool=pool, pool_mode=pool_mode
    )
    stats_dir = _stats_dir(config)
    stats_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"{window}_{selected_date or 'empty'}"
    if pool:
        safe_pool = str(pool).replace(",", "_").replace("/", "_")
        suffix = f"{safe_pool}_{suffix}"
    output_path = stats_dir / f"rps_top_{suffix}.csv"
    html_path = stats_dir / f"rps_top_{suffix}.html"
    rows.to_csv(output_path, index=False)
    _write_simple_report(
        f"RPS Top {top}",
        f"窗口 {window} 个交易日 · 截止 {selected_date or '--'}",
        rows,
        html_path,
        config,
    )
    return RpsTopResult(int(window), selected_date, output_path, html_path, rows)


def save_rps_track(config: dict, symbol: str, window: int = 120) -> RpsTrackResult:
    rows = rps_track(config, symbol, window=window)
    stats_dir = _stats_dir(config)
    stats_dir.mkdir(parents=True, exist_ok=True)
    safe_symbol = str(symbol).strip().upper()
    output_path = stats_dir / f"rps_track_{safe_symbol}_{window}.csv"
    html_path = stats_dir / f"rps_track_{safe_symbol}_{window}.html"
    rows.to_csv(output_path, index=False)
    _write_simple_report(
        f"{safe_symbol} RPS 轨迹",
        f"窗口 {window} 个交易日 · 共 {len(rows)} 个有效交易日",
        rows.tail(160).sort_values("trade_date", ascending=False),
        html_path,
        config,
    )
    return RpsTrackResult(safe_symbol, int(window), output_path, html_path, rows)
