"""Project dashboard report for local QuantYB research outputs."""

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from analysis.analyzer import _STRATEGY_LABELS, compute_stats


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


def _fmt_plain(value: Any, digits: int = 2) -> str:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "--"
    return f"{num:,.{digits}f}"


def _safe_float(value: Any) -> float | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(num):
        return None
    return num


def _numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[column], errors="coerce")


def _rel(from_path: Path, target: Path) -> str:
    try:
        return target.resolve().relative_to(from_path.parent.resolve()).as_posix()
    except ValueError:
        import os

        return Path(os.path.relpath(target.resolve(), from_path.parent.resolve())).as_posix()


def _latest_date_from_csv(path: Path) -> str:
    try:
        df = pd.read_csv(path, usecols=["date"], dtype={"date": str})
    except Exception:
        return ""
    if df.empty:
        return ""
    return str(df["date"].max())[:10]


def _read_index_snapshot(cache_path: Path) -> dict[str, Any]:
    if not cache_path.exists():
        return {"cache_exists": False}
    try:
        df = pd.read_csv(cache_path, dtype={"date": str})
    except Exception:
        return {"cache_exists": True, "read_error": True}
    if df.empty:
        return {"cache_exists": True, "empty": True}
    row = df.sort_values("date").iloc[-1]
    pct_num = _safe_float(row.get("pct_chg"))
    return {
        "cache_exists": True,
        "date": str(row.get("date", "")),
        "close": _fmt_num(row.get("close")),
        "pct_chg": _fmt_pct(pct_num),
        "pct_chg_num": pct_num,
        "amount": _fmt_num(row.get("amount"), 0),
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
    avg_return = _safe_float(stats.get("avg_return"))
    avg_active_return = _safe_float(stats.get("avg_active_return"))
    positive_ratio = _safe_float(stats.get("positive_ratio"))
    avg_sharpe = _safe_float(stats.get("avg_sharpe"))
    avg_max_dd = _safe_float(stats.get("avg_max_dd"))
    return {
        "count": stats.get("count", 0),
        "active_count": stats.get("active_count", 0),
        "active_ratio": _fmt_pct(stats.get("active_ratio"), 1).replace("+", ""),
        "avg_return": _fmt_pct(avg_return),
        "avg_return_num": avg_return,
        "avg_active_return": _fmt_pct(avg_active_return),
        "avg_active_return_num": avg_active_return,
        "positive_ratio": _fmt_pct(positive_ratio, 1).replace("+", ""),
        "positive_ratio_num": positive_ratio,
        "avg_drawdown": _fmt_pct(-abs(avg_max_dd or 0), 1),
        "avg_drawdown_num": avg_max_dd,
        "avg_sharpe": _fmt_plain(avg_sharpe, 3),
        "avg_sharpe_num": avg_sharpe,
    }


def _stock_report_count(reports_dir: Path) -> int:
    if not reports_dir.exists():
        return 0
    return sum(1 for p in reports_dir.glob("*.html") if p.name != "dashboard.html")


def _recent_stock_reports(reports_dir: Path, output_path: Path, limit: int = 10) -> list[dict[str, str]]:
    if not reports_dir.exists():
        return []
    paths = sorted(
        [p for p in reports_dir.glob("*.html") if p.name != "dashboard.html"],
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


def _decision_snapshot(decision_path: Path) -> dict[str, Any]:
    if not decision_path.exists():
        return {
            "exists": False,
            "count": 0,
            "evaluated": 0,
            "partial": 0,
            "pending": 0,
            "latest_signal_date": "",
            "avg_future_5d": "--",
            "avg_excess_5d": "--",
        }
    try:
        df = pd.read_csv(decision_path, dtype={"symbol": str, "signal_date": str})
    except Exception:
        return {"exists": False, "count": 0, "evaluated": 0, "partial": 0, "pending": 0}
    if df.empty:
        return {"exists": True, "count": 0, "evaluated": 0, "partial": 0, "pending": 0}
    if "evaluation_status" in df.columns:
        statuses = df["evaluation_status"].fillna("pending")
    else:
        statuses = pd.Series(["pending"] * len(df), index=df.index)
    future_5d = _numeric_series(df, "future_5d_return_pct")
    excess_5d = _numeric_series(df, "excess_5d_return_pct")
    return {
        "exists": True,
        "count": int(len(df)),
        "evaluated": int((statuses == "evaluated").sum()),
        "partial": int((statuses == "partial").sum()),
        "pending": int(statuses.isin(["pending", "pending_future_data"]).sum()),
        "latest_signal_date": str(df["signal_date"].dropna().max())[:10] if "signal_date" in df.columns else "",
        "avg_future_5d": _fmt_pct(future_5d.mean()) if not future_5d.dropna().empty else "--",
        "avg_excess_5d": _fmt_pct(excess_5d.mean()) if not excess_5d.dropna().empty else "--",
    }


def _recent_decisions(decision_path: Path, limit: int = 8) -> list[dict[str, str]]:
    if not decision_path.exists():
        return []
    try:
        df = pd.read_csv(decision_path, dtype={"symbol": str, "signal_date": str})
    except Exception:
        return []
    if df.empty:
        return []
    sort_cols = [c for c in ["signal_date", "recorded_at"] if c in df.columns]
    df = df.sort_values(sort_cols, ascending=False, na_position="last").head(limit) if sort_cols else df.head(limit)
    rows = []
    for _, row in df.iterrows():
        future_5d = row.get("future_5d_return_pct")
        rows.append(
            {
                "symbol": str(row.get("symbol", "")),
                "strategy": _STRATEGY_LABELS.get(str(row.get("strategy", "")), str(row.get("strategy", ""))),
                "date": str(row.get("signal_date", ""))[:10],
                "status": str(row.get("evaluation_status", "pending")),
                "future_5d": _fmt_pct(future_5d) if pd.notna(future_5d) else "--",
            }
        )
    return rows


def _cache_health(cache_dir: Path, index_cache_dir: Path, indexes: list[dict[str, Any]]) -> dict[str, Any]:
    stock_paths = [p for p in cache_dir.glob("*.csv") if not p.name.startswith("_")] if cache_dir.exists() else []
    latest_dates = [_latest_date_from_csv(path) for path in stock_paths]
    latest_dates = [d for d in latest_dates if d]
    latest_stock_date = max(latest_dates) if latest_dates else ""
    stale_count = sum(1 for d in latest_dates if latest_stock_date and d < latest_stock_date)
    index_cache_count = sum(1 for item in indexes if item.get("snapshot", {}).get("cache_exists"))
    return {
        "stock_cache_count": len(stock_paths),
        "latest_stock_date": latest_stock_date,
        "stale_stock_count": stale_count,
        "index_cache_count": index_cache_count,
        "index_total": len(indexes),
        "index_report_count": sum(1 for item in indexes if item.get("exists")),
        "index_cache_dir_exists": index_cache_dir.exists(),
    }


def _market_temperature(indexes: list[dict[str, Any]]) -> dict[str, Any]:
    available = [idx for idx in indexes if idx.get("snapshot", {}).get("pct_chg_num") is not None]
    if not available:
        return {
            "status": "待生成",
            "avg_pct": "--",
            "up_count": 0,
            "down_count": 0,
            "strongest": "--",
            "weakest": "--",
            "latest_date": "--",
            "tone": "flat",
        }
    avg_pct = sum(float(idx["snapshot"]["pct_chg_num"]) for idx in available) / len(available)
    up_count = sum(1 for idx in available if float(idx["snapshot"]["pct_chg_num"]) >= 0)
    down_count = len(available) - up_count
    strongest = max(available, key=lambda idx: float(idx["snapshot"]["pct_chg_num"]))
    weakest = min(available, key=lambda idx: float(idx["snapshot"]["pct_chg_num"]))
    if avg_pct >= 0.5:
        status = "偏暖"
        tone = "up"
    elif avg_pct <= -0.5:
        status = "偏冷"
        tone = "down"
    else:
        status = "中性"
        tone = "flat"
    dates = [str(idx["snapshot"].get("date", "")) for idx in available if idx["snapshot"].get("date")]
    return {
        "status": status,
        "avg_pct": _fmt_pct(avg_pct),
        "up_count": up_count,
        "down_count": down_count,
        "strongest": f"{strongest['name']} {strongest['snapshot']['pct_chg']}",
        "weakest": f"{weakest['name']} {weakest['snapshot']['pct_chg']}",
        "latest_date": max(dates) if dates else "--",
        "tone": tone,
    }


def _strategy_leaderboard(strategies: list[dict[str, Any]], limit: int = 6) -> list[dict[str, str]]:
    ready = [s for s in strategies if s.get("snapshot", {}).get("avg_return_num") is not None]
    ready.sort(key=lambda s: float(s["snapshot"]["avg_return_num"]), reverse=True)
    rows = []
    for rank, item in enumerate(ready[:limit], start=1):
        snap = item["snapshot"]
        rows.append(
            {
                "rank": str(rank),
                "name": item["label"],
                "code": item["name"],
                "avg_return": snap.get("avg_return", "--"),
                "active_return": snap.get("avg_active_return", "--"),
                "positive_ratio": snap.get("positive_ratio", "--"),
                "sharpe": snap.get("avg_sharpe", "--"),
                "drawdown": snap.get("avg_drawdown", "--"),
                "href": item.get("href", ""),
            }
        )
    return rows


def _recent_experiments(experiments_dir: Path, output_path: Path, limit: int = 6) -> list[dict[str, str]]:
    if not experiments_dir.exists():
        return []
    dirs = [p for p in experiments_dir.iterdir() if p.is_dir()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    rows = []
    for exp_dir in dirs[:limit]:
        manifest_path = exp_dir / "manifest.json"
        manifest = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                manifest = {}
        report_path = exp_dir / "reports"
        href = _rel(output_path, report_path) if report_path.exists() else ""
        rows.append(
            {
                "id": str(manifest.get("id") or exp_dir.name),
                "strategy": str(manifest.get("strategy") or "--"),
                "status": str(manifest.get("status") or "local"),
                "time": datetime.fromtimestamp(exp_dir.stat().st_mtime).strftime("%m-%d %H:%M"),
                "href": href,
            }
        )
    return rows


def _latest_portfolio(portfolio_dir: Path, output_path: Path, limit: int = 5) -> dict[str, Any]:
    if not portfolio_dir.exists():
        return {"exists": False, "rows": []}
    paths = sorted(portfolio_dir.glob("target_weights_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not paths:
        return {"exists": False, "rows": []}
    path = paths[0]
    try:
        df = pd.read_csv(path, dtype={"symbol": str})
    except Exception:
        return {"exists": True, "read_error": True, "path": str(path), "rows": []}
    if df.empty:
        return {"exists": True, "empty": True, "path": str(path), "rows": []}
    weights = pd.to_numeric(df.get("target_weight"), errors="coerce").fillna(0)
    top = df.assign(_weight=weights).sort_values("_weight", ascending=False).head(limit)
    rows = [
        {
            "symbol": str(row.get("symbol", "")),
            "weight": _fmt_pct(float(row.get("_weight", 0)) * 100, 2).replace("+", ""),
            "status": str(row.get("data_status", "")),
        }
        for _, row in top.iterrows()
    ]
    return {
        "exists": True,
        "path": str(path),
        "href": _rel(output_path, path),
        "date": str(df.get("date", pd.Series([""])).iloc[0]),
        "method": str(df.get("method", pd.Series([""])).iloc[0]),
        "count": int(len(df)),
        "gross_exposure": _fmt_pct(float(weights.sum()) * 100, 2).replace("+", ""),
        "max_weight": _fmt_pct(float(weights.max()) * 100, 2).replace("+", ""),
        "rows": rows,
    }


def _risk_notes(config: dict, data: dict[str, Any]) -> list[dict[str, str]]:
    notes = [
        {
            "title": "股票池偏差",
            "body": "当前股票池通常来自当前上市列表并过滤 ST，严肃绩效判断需标注退市股和历史 ST 状态覆盖不足。",
            "level": "warn",
        }
    ]
    health = data["data_health"]
    if health.get("stale_stock_count", 0):
        notes.append(
            {
                "title": "缓存日期不齐",
                "body": f"{health['stale_stock_count']} 个股票缓存早于最新缓存日期，批量对比前建议更新数据。",
                "level": "warn",
            }
        )
    benchmark = config.get("benchmark", {})
    benchmark_symbol = benchmark.get("symbol")
    if benchmark.get("enabled", True) and benchmark_symbol:
        cache_dir = Path(config["data"]["cache_dir"])
        benchmark_path = cache_dir / f"{benchmark_symbol}.csv"
        benchmark_index_path = cache_dir / "index" / f"{benchmark_symbol}.csv"
        if not benchmark_path.exists() and not benchmark_index_path.exists():
            notes.append(
                {
                    "title": "基准缺失",
                    "body": f"未找到 {benchmark_symbol} 本地缓存，超额收益和信息比率可能为空。",
                    "level": "warn",
                }
            )
    pending = data["decision_snapshot"].get("pending", 0)
    if pending:
        notes.append(
            {
                "title": "信号待评估",
                "body": f"{pending} 条信号仍缺少足够未来交易日，复盘均值会随数据更新变化。",
                "level": "info",
            }
        )
    audit_dir = Path(config["output"].get("audit_dir", "output/audit"))
    if not any(audit_dir.glob("lookahead_audit_*.html")):
        notes.append(
            {
                "title": "未来函数审计未接入",
                "body": "尚未找到 Lookahead Audit 报告。运行 audit lookahead 后可在 output/audit 查看启发式审计结果。",
                "level": "info",
            }
        )
    if not data.get("portfolio_snapshot", {}).get("exists"):
        notes.append(
            {
                "title": "组合权重未生成",
                "body": "尚未找到 target_weights_*.csv。运行 portfolio build 可从买点信号生成研究用目标权重。",
                "level": "info",
            }
        )
    return notes


def _collect_dashboard_data(config: dict, output_path: Path) -> dict[str, Any]:
    reports_dir = Path(config["output"]["reports_dir"])
    stats_dir = Path(config["output"].get("statistics_dir", "output/statistics"))
    trades_dir = Path(config["output"]["trades_dir"])
    decisions_dir = Path(config["output"].get("decisions_dir", "output/decisions"))
    experiments_dir = Path(config["output"].get("experiments_dir") or (trades_dir.parent / "experiments"))
    portfolio_dir = Path(config["output"].get("portfolio_dir", trades_dir.parent / "portfolio"))
    index_cache_dir = Path(config["data"]["cache_dir"]) / "index"
    index_reports_dir = reports_dir / "index"
    decision_path = decisions_dir / "decision_memory.csv"

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
    data = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "indexes": indexes,
        "strategies": strategies,
        "comparison_href": _rel(output_path, comparison_path) if comparison_path.exists() else "",
        "comparison_exists": comparison_path.exists(),
        "stock_report_count": _stock_report_count(reports_dir),
        "recent_stock_reports": _recent_stock_reports(reports_dir, output_path),
        "decision_snapshot": _decision_snapshot(decision_path),
        "recent_decisions": _recent_decisions(decision_path),
        "recent_experiments": _recent_experiments(experiments_dir, output_path),
        "portfolio_snapshot": _latest_portfolio(portfolio_dir, output_path),
    }
    data["data_health"] = _cache_health(Path(config["data"]["cache_dir"]), index_cache_dir, indexes)
    data["market_temperature"] = _market_temperature(indexes)
    data["strategy_leaderboard"] = _strategy_leaderboard(strategies)
    data["risk_notes"] = _risk_notes(config, data)
    return data


def _json_script(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def _badge(exists: bool) -> str:
    label = "已生成" if exists else "待生成"
    cls = "ok" if exists else "wait"
    return f'<span class="badge {cls}">{label}</span>'


def _tone_from_pct(value: str) -> str:
    if value.startswith("+"):
        return "up"
    if value.startswith("-"):
        return "down"
    return "flat"


def _build_status_grid(data: dict[str, Any]) -> str:
    health = data["data_health"]
    market = data["market_temperature"]
    decision = data["decision_snapshot"]
    latest_date = health.get("latest_stock_date") or "--"
    return f"""
      <section class="status-grid">
        <article class="status-panel market {html.escape(market.get("tone", "flat"))}">
          <div class="panel-kicker">市场温度</div>
          <div class="panel-main">{html.escape(market.get("status", "待生成"))}</div>
          <div class="panel-sub">平均涨跌 {html.escape(market.get("avg_pct", "--"))} · 上涨 {market.get("up_count", 0)} / 下跌 {market.get("down_count", 0)}</div>
          <div class="mini-stat"><span>最强</span><strong>{html.escape(market.get("strongest", "--"))}</strong></div>
          <div class="mini-stat"><span>最弱</span><strong>{html.escape(market.get("weakest", "--"))}</strong></div>
        </article>
        <article class="status-panel">
          <div class="panel-kicker">数据健康</div>
          <div class="panel-main">{health.get("stock_cache_count", 0)} 只</div>
          <div class="panel-sub">股票缓存 · 最新 {html.escape(latest_date)}</div>
          <div class="health-grid">
            <div><span>指数缓存</span><strong>{health.get("index_cache_count", 0)}/{health.get("index_total", 0)}</strong></div>
            <div><span>指数报告</span><strong>{health.get("index_report_count", 0)}</strong></div>
            <div><span>过期股票</span><strong>{health.get("stale_stock_count", 0)}</strong></div>
            <div><span>策略汇总</span><strong>{sum(1 for s in data["strategies"] if s.get("summary_exists"))}</strong></div>
          </div>
        </article>
        <article class="status-panel signal">
          <div class="panel-kicker">信号复盘</div>
          <div class="panel-main">{decision.get("count", 0)} 条</div>
          <div class="panel-sub">完整 {decision.get("evaluated", 0)} · 待评估 {decision.get("pending", 0)} · 最近 {html.escape(decision.get("latest_signal_date") or "--")}</div>
          <div class="health-grid two">
            <div><span>5日均值</span><strong>{html.escape(decision.get("avg_future_5d", "--"))}</strong></div>
            <div><span>5日超额</span><strong>{html.escape(decision.get("avg_excess_5d", "--"))}</strong></div>
          </div>
        </article>
      </section>
    """


def _build_kpis(data: dict[str, Any]) -> str:
    index_count = len(data["indexes"])
    strategy_count = len(data["strategies"])
    decision_count = data["decision_snapshot"].get("count", 0)
    experiments_count = len(data["recent_experiments"])
    portfolio_count = data.get("portfolio_snapshot", {}).get("count", 0)
    return f"""
    <section class="kpis">
      <div class="kpi"><span>指数概览</span><strong>{index_count}</strong></div>
      <div class="kpi"><span>策略模块</span><strong>{strategy_count}</strong></div>
      <div class="kpi"><span>单标的报告</span><strong>{data["stock_report_count"]}</strong></div>
      <div class="kpi"><span>信号复盘</span><strong>{decision_count}</strong></div>
      <div class="kpi"><span>实验归档</span><strong>{experiments_count}</strong></div>
      <div class="kpi"><span>组合标的</span><strong>{portfolio_count}</strong></div>
    </section>
    """


def _build_index_cards(data: dict[str, Any]) -> str:
    cards = []
    for idx, item in enumerate(data["indexes"], start=1):
        snap = item["snapshot"]
        href = html.escape(item["href"])
        attrs = f'href="{href}"' if href else 'href="#" aria-disabled="true"'
        pct = snap.get("pct_chg", "--")
        tone = _tone_from_pct(pct)
        cards.append(
            f"""
            <a class="index-card {tone}" {attrs}>
              <div class="card-top"><span>{idx:02d}</span>{_badge(item["exists"])}</div>
              <h3>{html.escape(item["name"])}</h3>
              <p>{html.escape(item["symbol"])}</p>
              <div class="quote">
                <strong>{html.escape(snap.get("close", "--"))}</strong>
                <em>{html.escape(pct)}</em>
              </div>
              <div class="meta"><span>{html.escape(snap.get("date", "--"))}</span><span>成交额 {html.escape(snap.get("amount", "--"))}</span></div>
            </a>
            """
        )
    return "\n".join(cards)


def _build_leaderboard(data: dict[str, Any]) -> str:
    rows = data["strategy_leaderboard"]
    if not rows:
        return '<p class="empty">暂无策略汇总数据</p>'
    html_rows = []
    for row in rows:
        attrs = f'href="{html.escape(row["href"])}"' if row["href"] else 'href="#" aria-disabled="true"'
        html_rows.append(
            f"""
            <a class="leader-row {_tone_from_pct(row["avg_return"])}" {attrs}>
              <span class="rank">{html.escape(row["rank"])}</span>
              <div><strong>{html.escape(row["name"])}</strong><em>{html.escape(row["code"])}</em></div>
              <b>{html.escape(row["avg_return"])}</b>
              <span>{html.escape(row["active_return"])}</span>
              <span>{html.escape(row["positive_ratio"])}</span>
              <span>{html.escape(row["sharpe"])}</span>
              <span>{html.escape(row["drawdown"])}</span>
            </a>
            """
        )
    return f"""
      <div class="leader-head">
        <span>#</span><span>策略</span><span>平均收益</span><span>交易股</span><span>正收益</span><span>夏普</span><span>回撤</span>
      </div>
      <div class="leader-list">{"".join(html_rows)}</div>
    """


def _build_strategy_cards(data: dict[str, Any]) -> str:
    cards = []
    for item in data["strategies"]:
        snap = item["snapshot"]
        href = html.escape(item["href"])
        attrs = f'href="{href}"' if href else 'href="#" aria-disabled="true"'
        ret = snap.get("avg_return", "--")
        tone = _tone_from_pct(ret)
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


def _build_decision_panel(data: dict[str, Any]) -> str:
    recent = data["recent_decisions"]
    if not recent:
        return '<p class="empty">暂无信号复盘</p>'
    return "\n".join(
        f"""
        <div class="decision-row">
          <span>{html.escape(item["symbol"])}</span>
          <strong>{html.escape(item["strategy"])}</strong>
          <em>{html.escape(item["date"])}</em>
          <b>{html.escape(item["future_5d"])}</b>
        </div>
        """
        for item in recent
    )


def _build_experiments(data: dict[str, Any]) -> str:
    rows = data["recent_experiments"]
    if not rows:
        return '<p class="empty">暂无实验归档</p>'
    return "\n".join(
        f"""
        <a class="experiment-row" href="{html.escape(item["href"] or "#")}" {"aria-disabled='true'" if not item["href"] else ""}>
          <strong>{html.escape(item["id"])}</strong>
          <span>{html.escape(item["strategy"])}</span>
          <em>{html.escape(item["time"])}</em>
        </a>
        """
        for item in rows
    )


def _build_portfolio_panel(data: dict[str, Any]) -> str:
    snapshot = data.get("portfolio_snapshot", {})
    if not snapshot.get("exists"):
        return '<p class="empty">暂无目标权重</p>'
    rows = snapshot.get("rows", [])
    top_rows = "\n".join(
        f"""
        <div class="decision-row">
          <span>{html.escape(item["symbol"])}</span>
          <strong>{html.escape(item["weight"])}</strong>
          <em>{html.escape(item["status"] or "--")}</em>
          <b></b>
        </div>
        """
        for item in rows
    )
    href = html.escape(snapshot.get("href", "#"))
    return f"""
      <a class="mini-link" href="{href}">
        <span>{html.escape(snapshot.get("method", "--"))}</span>
        <strong>{html.escape(snapshot.get("gross_exposure", "--"))} 总仓位</strong>
        <em>{html.escape(snapshot.get("max_weight", "--"))} 最大</em>
      </a>
      {top_rows or '<p class="empty">暂无权重明细</p>'}
    """


def _build_risk_notes(data: dict[str, Any]) -> str:
    return "\n".join(
        f"""
        <div class="risk-note {html.escape(item["level"])}">
          <strong>{html.escape(item["title"])}</strong>
          <span>{html.escape(item["body"])}</span>
        </div>
        """
        for item in data["risk_notes"]
    )


def _build_html(data: dict[str, Any]) -> str:
    comparison_link = (
        f'<a class="primary-link" href="{html.escape(data["comparison_href"])}">策略横向对比</a>'
        if data["comparison_exists"]
        else '<span class="primary-link muted">策略横向对比</span>'
    )
    first_index = next((item for item in data["indexes"] if item.get("href")), None)
    index_link = (
        f'<a class="primary-link" href="{html.escape(first_index["href"])}">{html.escape(first_index["name"])}</a>'
        if first_index
        else '<span class="primary-link muted">指数报告</span>'
    )
    dashboard_json = _json_script(data)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>QuantYB 研究总控面板</title>
  <style>
    :root {{
      --ink: #172033;
      --muted: #69748a;
      --line: #d9e0ea;
      --paper: #f5f6f8;
      --panel: #ffffff;
      --soft: #eef2f7;
      --blue: #2f6df6;
      --green: #168457;
      --red: #c94343;
      --amber: #b47a16;
      --violet: #6f5fb8;
      --shadow: 0 16px 44px rgba(24, 34, 53, .09);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background:
        linear-gradient(90deg, rgba(23,32,51,.035) 1px, transparent 1px) 0 0 / 36px 36px,
        linear-gradient(rgba(23,32,51,.035) 1px, transparent 1px) 0 0 / 36px 36px,
        var(--paper);
      font-family: "Microsoft YaHei", "Noto Sans SC", "PingFang SC", sans-serif;
    }}
    a {{ color: inherit; text-decoration: none; }}
    .shell {{ width: min(1480px, calc(100vw - 48px)); margin: 0 auto; padding: 28px 0 42px; }}
    .topbar {{
      display: grid; grid-template-columns: 1fr auto; gap: 18px; align-items: end;
      padding: 24px 0 22px; border-bottom: 1px solid var(--line);
    }}
    .mark {{ display: flex; align-items: center; gap: 14px; }}
    .mark-icon {{
      width: 46px; height: 46px; border: 2px solid var(--ink); display: grid; place-items: center;
      font-weight: 900; background: linear-gradient(135deg, #ffffff 0%, #e9eef8 100%);
      box-shadow: 5px 5px 0 var(--ink);
    }}
    h1 {{ margin: 0; font-size: clamp(28px, 4vw, 52px); line-height: 1; letter-spacing: 0; }}
    .subtitle {{ margin: 9px 0 0; color: var(--muted); font-size: 14px; }}
    .actions {{ display: flex; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }}
    .primary-link {{
      display: inline-flex; align-items: center; min-height: 40px; border: 1px solid var(--ink);
      padding: 0 14px; background: var(--ink); color: white; font-weight: 700;
      box-shadow: 4px 4px 0 rgba(23,32,51,.18);
    }}
    .primary-link.muted {{ background: transparent; color: var(--muted); border-color: var(--line); box-shadow: none; }}
    .kpis {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; margin: 22px 0; }}
    .kpi {{
      background: var(--panel); border: 1px solid var(--line); padding: 16px 18px;
      min-height: 94px; display: flex; flex-direction: column; justify-content: space-between;
    }}
    .kpi span, .panel-kicker {{ color: var(--muted); font-size: 13px; }}
    .kpi strong {{ font-size: 28px; letter-spacing: 0; }}
    .status-grid {{ display: grid; grid-template-columns: 1.15fr 1fr 1fr; gap: 14px; margin: 22px 0 10px; }}
    .status-panel {{
      min-height: 235px; background: var(--panel); border: 1px solid var(--line);
      padding: 18px; display: flex; flex-direction: column; gap: 12px;
    }}
    .status-panel.market {{ border-top: 4px solid var(--blue); }}
    .status-panel.market.up {{ border-top-color: var(--red); }}
    .status-panel.market.down {{ border-top-color: var(--green); }}
    .panel-main {{ font-size: 38px; font-weight: 900; line-height: 1; }}
    .panel-sub {{ color: var(--muted); font-size: 13px; }}
    .mini-stat {{ border-top: 1px solid var(--line); padding-top: 10px; display: grid; gap: 3px; }}
    .mini-stat span {{ color: var(--muted); font-size: 12px; }}
    .mini-stat strong {{ font-size: 14px; }}
    .health-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: auto; }}
    .health-grid div {{ border: 1px solid var(--line); background: #fbfcfe; padding: 10px; }}
    .health-grid span {{ display: block; color: var(--muted); font-size: 12px; margin-bottom: 4px; }}
    .health-grid strong {{ font-size: 18px; }}
    .section-head {{ display: flex; justify-content: space-between; align-items: baseline; margin: 30px 0 12px; }}
    .section-head h2 {{ margin: 0; font-size: 22px; }}
    .section-head span {{ color: var(--muted); font-size: 13px; }}
    .leader-panel, .side-panel {{
      background: var(--panel); border: 1px solid var(--line); padding: 16px;
    }}
    .leader-head, .leader-row {{
      display: grid; grid-template-columns: 42px minmax(160px, 1.2fr) repeat(5, minmax(82px, .7fr));
      gap: 10px; align-items: center;
    }}
    .leader-head {{ color: var(--muted); font-size: 12px; padding: 0 10px 8px; border-bottom: 1px solid var(--line); }}
    .leader-list {{ display: grid; gap: 8px; margin-top: 8px; }}
    .leader-row {{ border: 1px solid var(--line); padding: 11px 10px; background: #fbfcfe; transition: transform .16s ease, box-shadow .16s ease; }}
    .leader-row:hover, .index-card:hover, .strategy-row:hover, .mini-link:hover {{ transform: translateY(-2px); box-shadow: var(--shadow); }}
    .leader-row .rank {{ font-weight: 900; color: var(--blue); }}
    .leader-row strong {{ display: block; font-size: 15px; }}
    .leader-row em {{ display: block; color: var(--muted); font-size: 12px; font-style: normal; }}
    .leader-row b {{ font-size: 16px; }}
    .index-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }}
    .index-card {{
      min-height: 218px; background: var(--panel); border: 1px solid var(--line); padding: 16px;
      display: flex; flex-direction: column; justify-content: space-between; transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
    }}
    .card-top {{ display: flex; justify-content: space-between; align-items: center; color: var(--muted); font-size: 12px; }}
    .badge {{ border: 1px solid var(--line); padding: 3px 8px; font-size: 12px; color: var(--muted); background: #f9fafc; }}
    .badge.ok {{ color: var(--green); border-color: rgba(22,132,87,.28); background: rgba(22,132,87,.07); }}
    .badge.wait {{ color: var(--amber); border-color: rgba(180,122,22,.3); background: rgba(180,122,22,.08); }}
    .index-card h3 {{ margin: 12px 0 4px; font-size: 24px; }}
    .index-card p {{ margin: 0; color: var(--muted); font-weight: 700; }}
    .quote {{ display: flex; align-items: end; justify-content: space-between; gap: 10px; }}
    .quote strong {{ font-size: 30px; letter-spacing: 0; }}
    .quote em {{ font-style: normal; font-size: 22px; font-weight: 900; }}
    .up em, .up .row-metric:nth-child(3) strong, .up b {{ color: var(--red); }}
    .down em, .down .row-metric:nth-child(3) strong, .down b {{ color: var(--green); }}
    .meta {{ display: flex; justify-content: space-between; gap: 8px; color: var(--muted); font-size: 12px; border-top: 1px solid var(--line); padding-top: 10px; }}
    .split {{ display: grid; grid-template-columns: minmax(0, 1.45fr) minmax(330px, .78fr); gap: 18px; align-items: start; }}
    .strategy-list {{ display: grid; gap: 10px; }}
    .strategy-row {{
      display: grid; grid-template-columns: minmax(190px, 1.3fr) repeat(5, minmax(92px, .72fr)) auto;
      gap: 12px; align-items: center; background: var(--panel); border: 1px solid var(--line); padding: 14px;
      transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
    }}
    .row-title {{ font-size: 18px; font-weight: 900; }}
    .row-sub {{ color: var(--muted); font-size: 12px; margin-top: 3px; }}
    .row-metric span {{ display: block; color: var(--muted); font-size: 12px; margin-bottom: 3px; }}
    .row-metric strong {{ font-size: 16px; }}
    .right-rail {{ display: grid; gap: 14px; position: sticky; top: 18px; }}
    .side-panel h3 {{ margin: 0 0 12px; font-size: 18px; }}
    .mini-list {{ display: grid; gap: 8px; }}
    .mini-link, .experiment-row {{
      display: grid; grid-template-columns: 86px 1fr auto; gap: 10px; align-items: center;
      border: 1px solid var(--line); padding: 10px; background: #fbfcfe;
      transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
    }}
    .mini-link span {{ font-weight: 900; }}
    .mini-link strong, .experiment-row strong {{ font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .mini-link em, .experiment-row em {{ color: var(--muted); font-size: 12px; font-style: normal; }}
    .decision-row {{
      display: grid; grid-template-columns: 72px 1fr 78px 72px; gap: 8px; align-items: center;
      border: 1px solid var(--line); padding: 9px; background: #fbfcfe; font-size: 12px;
    }}
    .decision-row span {{ font-weight: 900; }}
    .decision-row strong {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .decision-row em {{ color: var(--muted); font-style: normal; }}
    .decision-row b {{ text-align: right; }}
    .risk-note {{ border-left: 4px solid var(--blue); background: #fbfcfe; padding: 10px 12px; display: grid; gap: 4px; font-size: 13px; }}
    .risk-note.warn {{ border-left-color: var(--amber); }}
    .risk-note strong {{ font-size: 14px; }}
    .risk-note span {{ color: var(--muted); line-height: 1.45; }}
    .empty {{ color: var(--muted); margin: 0; }}
    [aria-disabled="true"] {{ cursor: default; pointer-events: none; opacity: .62; }}
    footer {{ margin-top: 30px; color: var(--muted); font-size: 12px; border-top: 1px solid var(--line); padding-top: 16px; }}
    @media (max-width: 1120px) {{
      .status-grid, .split {{ grid-template-columns: 1fr; }}
      .right-rail {{ position: static; }}
      .index-grid, .kpis {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .strategy-row, .leader-head, .leader-row {{ grid-template-columns: 1fr 1fr 1fr; }}
      .leader-head span:nth-child(n+4), .leader-row span:nth-child(n+4) {{ display: none; }}
    }}
    @media (max-width: 680px) {{
      .shell {{ width: min(100vw - 24px, 1480px); padding-top: 14px; }}
      .topbar {{ grid-template-columns: 1fr; }}
      .actions {{ justify-content: flex-start; }}
      .index-grid, .kpis {{ grid-template-columns: 1fr; }}
      .strategy-row {{ grid-template-columns: 1fr 1fr; }}
      .mini-link, .experiment-row, .decision-row {{ grid-template-columns: 1fr; }}
      .quote strong {{ font-size: 24px; }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div class="mark">
        <div class="mark-icon">QY</div>
        <div>
          <h1>QuantYB 研究总控</h1>
          <p class="subtitle">生成时间 {html.escape(data["generated_at"])} · 本地研究输出</p>
        </div>
      </div>
      <nav class="actions">
        {comparison_link}
        {index_link}
      </nav>
    </header>

    {_build_kpis(data)}
    {_build_status_grid(data)}

    <section>
      <div class="section-head"><h2>策略排行榜</h2><span>按全市场平均收益排序</span></div>
      <div class="leader-panel">{_build_leaderboard(data)}</div>
    </section>

    <section>
      <div class="section-head"><h2>指数导航</h2><span>index_daily · 日K/周K/月K · MACD/KDJ/RSI</span></div>
      <div class="index-grid">{_build_index_cards(data)}</div>
    </section>

    <section class="split">
      <div>
        <div class="section-head"><h2>策略汇总</h2><span>来自 output/trades/_summary_*.csv</span></div>
        <div class="strategy-list">{_build_strategy_cards(data)}</div>
      </div>
      <div class="right-rail">
        <aside class="side-panel"><h3>最近信号</h3><div class="mini-list">{_build_decision_panel(data)}</div></aside>
        <aside class="side-panel"><h3>目标权重</h3><div class="mini-list">{_build_portfolio_panel(data)}</div></aside>
        <aside class="side-panel"><h3>最近实验</h3><div class="mini-list">{_build_experiments(data)}</div></aside>
        <aside class="side-panel"><h3>最近报告</h3><div class="mini-list">{_build_recent_reports(data)}</div></aside>
        <aside class="side-panel"><h3>风险提示</h3><div class="mini-list">{_build_risk_notes(data)}</div></aside>
      </div>
    </section>

    <footer>数据和链接均来自本地 data/cache 与 output 目录；缺失项会显示待生成。</footer>
  </main>
  <script type="application/json" id="dashboard-data">{dashboard_json}</script>
</body>
</html>
"""


def generate_dashboard(config: dict, output_path: str | Path | None = None) -> Path:
    reports_dir = Path(config["output"]["reports_dir"])
    out_path = Path(output_path) if output_path else reports_dir / "dashboard.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data = _collect_dashboard_data(config, out_path)
    out_path.write_text(_build_html(data), encoding="utf-8")
    return out_path
