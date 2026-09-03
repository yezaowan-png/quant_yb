"""Research-grade pool rotation backtests.

This module intentionally stays outside `engine/runner.py`: it estimates a
portfolio rotation NAV from local K-line caches without changing the existing
single-symbol Backtrader contract.
"""

from __future__ import annotations

from dataclasses import dataclass
import html
import math
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from data.stock_pool import resolve_pool_symbols
from visual.components import html_document, stock_link_html


@dataclass
class RotationResult:
    model: str
    nav_path: Path
    holdings_path: Path
    html_path: Path
    summary: dict[str, float | int | str]
    nav: pd.DataFrame
    holdings: pd.DataFrame


def _cache_dir(config: dict) -> Path:
    return Path(config["data"]["cache_dir"])


def _stats_dir(config: dict) -> Path:
    return Path(config["output"].get("statistics_dir", "output/statistics"))


def _resolve_symbols(config: dict, pool: str | None, pool_mode: str, symbols: Iterable[str] | None) -> list[str]:
    if symbols:
        return [str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()]
    if pool:
        return resolve_pool_symbols(config, pool, pool_mode)
    cache_dir = _cache_dir(config)
    return sorted(path.stem.upper() for path in cache_dir.glob("*.csv") if not path.name.startswith("_"))


def _load_symbol_frame(config: dict, symbol: str) -> pd.DataFrame | None:
    path = _cache_dir(config) / f"{symbol}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, dtype={"date": str})
    if "date" not in df.columns or "close" not in df.columns:
        return None
    df["date"] = df["date"].astype(str).str.replace("-", "", regex=False)
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    else:
        df["volume"] = 0.0
    return df.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)


def _wide_panel(config: dict, symbols: list[str], start: str | None, end: str | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    closes = {}
    volumes = {}
    for symbol in symbols:
        df = _load_symbol_frame(config, symbol)
        if df is None or len(df) < 2:
            continue
        if start:
            df = df[df["date"] >= str(start).replace("-", "")]
        if end:
            df = df[df["date"] <= str(end).replace("-", "")]
        if len(df) < 2:
            continue
        closes[symbol] = pd.Series(df["close"].to_numpy(), index=df["date"].astype(str))
        volumes[symbol] = pd.Series(df["volume"].to_numpy(), index=df["date"].astype(str))
    return pd.DataFrame(closes).sort_index(), pd.DataFrame(volumes).sort_index()


def _trend_score(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if len(values) < 3 or (values <= 0).any():
        return 0.0
    y = np.log(values.to_numpy())
    x = np.arange(len(y), dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    fitted = slope * x + intercept
    ss_res = float(((y - fitted) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 0.0 if ss_tot == 0 else max(0.0, 1.0 - ss_res / ss_tot)
    return float(slope * r2)


def _score_table(
    closes: pd.DataFrame,
    volumes: pd.DataFrame,
    idx: int,
    model: str,
    momentum_window: int,
    trend_window: int,
    volume_short: int,
    volume_long: int,
) -> pd.Series:
    # Scores for rebalance at `idx` use data only through `idx - 1`.
    end = idx
    history = closes.iloc[:end]
    volume_history = volumes.iloc[:end]
    if len(history) <= max(momentum_window, trend_window, volume_long):
        return pd.Series(dtype=float)

    if model == "momentum":
        return (history.iloc[-1] / history.iloc[-momentum_window] - 1.0).dropna()

    rows = {}
    for symbol in history.columns:
        close = history[symbol].dropna()
        vol = volume_history[symbol].dropna() if symbol in volume_history else pd.Series(dtype=float)
        if len(close) <= max(momentum_window, trend_window) or len(vol) < volume_long:
            continue
        trend = _trend_score(close.tail(trend_window))
        momentum = float(close.iloc[-1] / close.iloc[-momentum_window] - 1.0)
        vol_short = float(vol.tail(volume_short).mean())
        vol_long = float(vol.tail(volume_long).mean())
        volume_factor = vol_short / vol_long if vol_long else 0.0
        rows[symbol] = {"trend": trend, "momentum": momentum, "volume": volume_factor}
    if not rows:
        return pd.Series(dtype=float)
    factors = pd.DataFrame(rows).T
    normed = pd.DataFrame(index=factors.index)
    for col in factors.columns:
        values = factors[col].astype(float)
        spread = values.max() - values.min()
        normed[col] = 0.0 if spread == 0 else (values - values.min()) / spread
    return (normed["trend"] * 0.4 + normed["momentum"] * 0.35 + normed["volume"] * 0.25).sort_values(ascending=False)


def run_rotation(
    config: dict,
    pool: str | None = None,
    pool_mode: str = "any",
    symbols: Iterable[str] | None = None,
    model: str = "momentum",
    start: str | None = None,
    end: str | None = None,
    hold_count: int = 3,
    rebalance_days: int = 5,
    momentum_window: int = 20,
    trend_window: int = 15,
    volume_short: int = 5,
    volume_long: int = 15,
    cost_bps: float = 5.0,
    initial_nav: float = 1000.0,
) -> tuple[dict[str, float | int | str], pd.DataFrame, pd.DataFrame]:
    """Run a simple next-day executable rotation research backtest."""
    if model not in {"momentum", "three_factor"}:
        raise ValueError("--model 只支持 momentum 或 three_factor")
    selected = _resolve_symbols(config, pool, pool_mode, symbols)
    closes, volumes = _wide_panel(config, selected, start, end)
    closes = closes.dropna(axis=0, how="all")
    if len(closes) < max(momentum_window, trend_window, volume_long) + 2:
        raise ValueError("有效 K 线数据不足，无法轮动回测")

    daily_returns = closes.pct_change().fillna(0.0)
    holdings: list[str] = []
    nav = float(initial_nav)
    nav_rows = []
    holding_rows = []
    turnover_sum = 0.0
    rebalance_count = 0
    min_warmup = max(momentum_window, trend_window, volume_long) + 1

    for idx, trade_date in enumerate(closes.index):
        if idx == 0:
            nav_rows.append({"date": trade_date, "nav": nav, "daily_return_pct": 0.0, "holdings": ""})
            continue

        if holdings:
            ret = daily_returns.iloc[idx][holdings].dropna()
            portfolio_ret = float(ret.mean()) if len(ret) else 0.0
        else:
            portfolio_ret = 0.0
        nav *= 1.0 + portfolio_ret

        should_rebalance = idx >= min_warmup and ((idx - min_warmup) % max(1, rebalance_days) == 0)
        if should_rebalance:
            scores = _score_table(
                closes,
                volumes,
                idx,
                model=model,
                momentum_window=momentum_window,
                trend_window=trend_window,
                volume_short=volume_short,
                volume_long=volume_long,
            )
            new_holdings = scores.head(max(1, hold_count)).index.tolist()
            if new_holdings:
                old_set = set(holdings)
                new_set = set(new_holdings)
                turnover = len(old_set.symmetric_difference(new_set)) / max(len(old_set | new_set), 1)
                turnover_sum += turnover
                nav *= 1.0 - turnover * float(cost_bps) / 10000.0
                holdings = new_holdings
                rebalance_count += 1
                for rank, symbol in enumerate(holdings, start=1):
                    holding_rows.append(
                        {
                            "date": trade_date,
                            "rank": rank,
                            "ts_code": symbol,
                            "score": round(float(scores.get(symbol, 0.0)), 6),
                            "turnover": round(turnover, 4),
                        }
                    )

        nav_rows.append(
            {
                "date": trade_date,
                "nav": round(nav, 6),
                "daily_return_pct": round(portfolio_ret * 100.0, 6),
                "holdings": ",".join(holdings),
            }
        )

    nav_df = pd.DataFrame(nav_rows)
    holdings_df = pd.DataFrame(holding_rows)
    total_return = nav / initial_nav - 1.0
    days = max(len(nav_df) - 1, 1)
    annual_return = (nav / initial_nav) ** (244 / days) - 1.0 if nav > 0 else 0.0
    nav_series = pd.to_numeric(nav_df["nav"], errors="coerce")
    drawdown = nav_series / nav_series.cummax() - 1.0
    returns = nav_series.pct_change().dropna()
    volatility = float(returns.std(ddof=0) * math.sqrt(244)) if len(returns) else 0.0
    sharpe = float(annual_return / volatility) if volatility else 0.0
    summary = {
        "model": model,
        "start_date": str(nav_df["date"].iloc[0]),
        "end_date": str(nav_df["date"].iloc[-1]),
        "symbols": len(closes.columns),
        "hold_count": int(hold_count),
        "rebalance_days": int(rebalance_days),
        "rebalance_count": int(rebalance_count),
        "final_nav": round(float(nav), 4),
        "total_return_pct": round(float(total_return * 100.0), 2),
        "annual_return_pct": round(float(annual_return * 100.0), 2),
        "annual_volatility_pct": round(float(volatility * 100.0), 2),
        "sharpe_ratio": round(sharpe, 4),
        "max_drawdown_pct": round(float(drawdown.min() * 100.0), 2),
        "avg_turnover": round(float(turnover_sum / rebalance_count), 4) if rebalance_count else 0.0,
    }
    return summary, nav_df, holdings_df


def _write_report(summary: dict, nav: pd.DataFrame, holdings: pd.DataFrame, output_path: Path, config: dict | None = None) -> Path:
    metric_items = "".join(
        f"<div><span>{html.escape(str(key))}</span><strong>{html.escape(str(value))}</strong></div>"
        for key, value in summary.items()
    )
    latest_holdings = holdings.tail(30)
    rows = []
    if not latest_holdings.empty:
        for _, row in latest_holdings.iterrows():
            cells = []
            for col in latest_holdings.columns:
                value = row.get(col, "")
                if str(col) in {"ts_code", "symbol"}:
                    cells.append(f"<td>{stock_link_html(config, output_path, value)}</td>")
                else:
                    cells.append(f"<td>{html.escape(str(value))}</td>")
            rows.append(
                "<tr>"
                + "".join(cells)
                + "</tr>"
            )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        html_document(
            title="轮动研究报告",
            styles="""
            body { margin: 0; background: #f4f6fa; color: #1f2937; font-family: "Microsoft YaHei", "Noto Sans SC", sans-serif; }
            main { width: min(1180px, calc(100vw - 40px)); margin: 0 auto; padding: 28px 0 44px; }
            h1 { margin: 0 0 16px; font-size: 28px; }
            .metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-bottom: 18px; }
            .metrics div { background: white; border: 1px solid #d9e2ef; border-radius: 8px; padding: 12px; }
            .metrics span { display: block; color: #667085; font-size: 12px; margin-bottom: 4px; }
            table { width: 100%; border-collapse: collapse; background: white; border: 1px solid #d9e2ef; }
            th, td { padding: 8px 10px; border-bottom: 1px solid #e6edf5; text-align: left; font-size: 13px; }
            th { background: #eef4ff; }
            a.stock-link { color: #2454a6; font-weight: 700; text-decoration: none; }
            a.stock-link:hover { text-decoration: underline; }
            """,
            body=f"""
            <main>
              <h1>轮动研究报告</h1>
              <section class="metrics">{metric_items}</section>
              <h2>最近换仓</h2>
              <table><thead><tr>{''.join(f'<th>{html.escape(str(c))}</th>' for c in latest_holdings.columns)}</tr></thead><tbody>{''.join(rows)}</tbody></table>
            </main>
            """,
        ),
        encoding="utf-8",
    )
    return output_path


def save_rotation(config: dict, **kwargs) -> RotationResult:
    summary, nav, holdings = run_rotation(config, **kwargs)
    stats_dir = _stats_dir(config)
    stats_dir.mkdir(parents=True, exist_ok=True)
    model = str(kwargs.get("model", "momentum"))
    pool = str(kwargs.get("pool") or "all").replace(",", "_").replace("/", "_")
    start = summary["start_date"]
    end = summary["end_date"]
    stem = f"rotation_{model}_{pool}_{start}_{end}"
    nav_path = stats_dir / f"{stem}_nav.csv"
    holdings_path = stats_dir / f"{stem}_holdings.csv"
    html_path = stats_dir / f"{stem}.html"
    nav.to_csv(nav_path, index=False)
    holdings.to_csv(holdings_path, index=False)
    _write_report(summary, nav, holdings, html_path, config)
    return RotationResult(model, nav_path, holdings_path, html_path, summary, nav, holdings)
