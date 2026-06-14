"""Project dashboard report for navigating indexes and strategy summaries."""

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
    return sum(1 for p in reports_dir.glob("*.html") if p.name != "dashboard.html")


def _recent_stock_reports(reports_dir: Path, output_path: Path, limit: int = 12) -> list[dict[str, str]]:
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
    statuses = df.get("evaluation_status", pd.Series([], dtype=str)).fillna("pending")
    future_5d = pd.to_numeric(df.get("future_5d_return_pct"), errors="coerce")
    excess_5d = pd.to_numeric(df.get("excess_5d_return_pct"), errors="coerce")
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
    df = df.sort_values(["signal_date", "recorded_at"], ascending=False, na_position="last").head(limit)
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


def _collect_dashboard_data(config: dict, output_path: Path) -> dict[str, Any]:
    reports_dir = Path(config["output"]["reports_dir"])
    stats_dir = Path(config["output"].get("statistics_dir", "output/statistics"))
    trades_dir = Path(config["output"]["trades_dir"])
    decisions_dir = Path(config["output"].get("decisions_dir", "output/decisions"))
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
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "indexes": indexes,
        "strategies": strategies,
        "comparison_href": _rel(output_path, comparison_path) if comparison_path.exists() else "",
        "comparison_exists": comparison_path.exists(),
        "stock_report_count": _stock_report_count(reports_dir),
        "recent_stock_reports": _recent_stock_reports(reports_dir, output_path),
        "decision_snapshot": _decision_snapshot(decision_path),
        "recent_decisions": _recent_decisions(decision_path),
    }


def _json_script(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def _badge(exists: bool) -> str:
    label = "已生成" if exists else "待生成"
    cls = "ok" if exists else "wait"
    return f'<span class="badge {cls}">{label}</span>'


def _build_index_cards(data: dict[str, Any]) -> str:
    cards = []
    for idx, item in enumerate(data["indexes"], start=1):
        snap = item["snapshot"]
        href = html.escape(item["href"])
        attrs = f'href="{href}"' if href else 'href="#" aria-disabled="true"'
        pct = snap.get("pct_chg", "--")
        tone = "up" if pct.startswith("+") else "down" if pct.startswith("-") else "flat"
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


def _build_decision_panel(data: dict[str, Any]) -> str:
    snapshot = data["decision_snapshot"]
    recent = data["recent_decisions"]
    rows = ""
    if recent:
        rows = "\n".join(
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
    else:
        rows = '<p class="empty">暂无信号复盘</p>'
    return f"""
      <div class="decision-metrics">
        <div><span>信号</span><strong>{html.escape(str(snapshot.get("count", 0)))}</strong></div>
        <div><span>完整</span><strong>{html.escape(str(snapshot.get("evaluated", 0)))}</strong></div>
        <div><span>待评估</span><strong>{html.escape(str(snapshot.get("pending", 0)))}</strong></div>
        <div><span>5日均值</span><strong>{html.escape(snapshot.get("avg_future_5d", "--"))}</strong></div>
      </div>
      <div class="mini-list">{rows}</div>
    """


def _build_html(data: dict[str, Any]) -> str:
    index_count = len(data["indexes"])
    strategy_count = len(data["strategies"])
    decision_count = data["decision_snapshot"].get("count", 0)
    comparison_link = (
        f'<a class="primary-link" href="{html.escape(data["comparison_href"])}">策略横向对比</a>'
        if data["comparison_exists"]
        else '<span class="primary-link muted">策略横向对比</span>'
    )
    dashboard_json = _json_script(data)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>QuantYB 总控面板</title>
  <style>
    :root {{
      --ink: #172033;
      --muted: #69748a;
      --line: #d9e0ea;
      --paper: #f6f7f9;
      --panel: #ffffff;
      --blue: #2f6df6;
      --green: #168457;
      --red: #c94343;
      --amber: #b47a16;
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
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 18px;
      align-items: end;
      padding: 24px 0 22px;
      border-bottom: 1px solid var(--line);
    }}
    .mark {{ display: flex; align-items: center; gap: 14px; }}
    .mark-icon {{
      width: 46px; height: 46px; border: 2px solid var(--ink);
      display: grid; place-items: center; font-weight: 900;
      background: linear-gradient(135deg, #ffffff 0%, #e9eef8 100%);
      box-shadow: 5px 5px 0 var(--ink);
    }}
    h1 {{ margin: 0; font-size: clamp(28px, 4vw, 52px); line-height: 1; letter-spacing: 0; }}
    .subtitle {{ margin: 9px 0 0; color: var(--muted); font-size: 14px; }}
    .actions {{ display: flex; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }}
    .primary-link {{
      display: inline-flex; align-items: center; min-height: 40px;
      border: 1px solid var(--ink); padding: 0 14px; background: var(--ink);
      color: white; font-weight: 700; box-shadow: 4px 4px 0 rgba(23,32,51,.18);
    }}
    .primary-link.muted {{ background: transparent; color: var(--muted); border-color: var(--line); box-shadow: none; }}
    .kpis {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 22px 0; }}
    .kpi {{
      background: var(--panel); border: 1px solid var(--line); padding: 16px 18px;
      min-height: 94px; display: flex; flex-direction: column; justify-content: space-between;
    }}
    .kpi span {{ color: var(--muted); font-size: 13px; }}
    .kpi strong {{ font-size: 28px; letter-spacing: 0; }}
    .section-head {{ display: flex; justify-content: space-between; align-items: baseline; margin: 30px 0 12px; }}
    .section-head h2 {{ margin: 0; font-size: 22px; }}
    .section-head span {{ color: var(--muted); font-size: 13px; }}
    .index-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }}
    .index-card {{
      min-height: 218px; background: var(--panel); border: 1px solid var(--line);
      padding: 16px; display: flex; flex-direction: column; justify-content: space-between;
      transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
    }}
    .index-card:hover, .strategy-row:hover, .mini-link:hover {{
      transform: translateY(-2px); box-shadow: var(--shadow); border-color: var(--ink);
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
    .up em, .up .row-metric:nth-child(3) strong {{ color: var(--red); }}
    .down em, .down .row-metric:nth-child(3) strong {{ color: var(--green); }}
    .meta {{ display: flex; justify-content: space-between; gap: 8px; color: var(--muted); font-size: 12px; border-top: 1px solid var(--line); padding-top: 10px; }}
    .split {{ display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(320px, .75fr); gap: 18px; align-items: start; }}
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
    .side-panel {{
      background: var(--panel); border: 1px solid var(--line); padding: 16px; position: sticky; top: 18px;
    }}
    .side-panel h3 {{ margin: 0 0 12px; font-size: 18px; }}
    .mini-list {{ display: grid; gap: 8px; }}
    .mini-link {{
      display: grid; grid-template-columns: 86px 1fr auto; gap: 10px; align-items: center;
      border: 1px solid var(--line); padding: 10px; background: #fbfcfe;
      transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
    }}
    .mini-link span {{ font-weight: 900; }}
    .mini-link strong {{ font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .mini-link em {{ color: var(--muted); font-size: 12px; font-style: normal; }}
    .decision-metrics {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-bottom: 12px; }}
    .decision-metrics div {{ border: 1px solid var(--line); background: #fbfcfe; padding: 10px; }}
    .decision-metrics span {{ display: block; color: var(--muted); font-size: 12px; margin-bottom: 4px; }}
    .decision-metrics strong {{ font-size: 18px; }}
    .decision-row {{
      display: grid; grid-template-columns: 72px 1fr 78px 72px; gap: 8px; align-items: center;
      border: 1px solid var(--line); padding: 9px; background: #fbfcfe; font-size: 12px;
    }}
    .decision-row span {{ font-weight: 900; }}
    .decision-row strong {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .decision-row em {{ color: var(--muted); font-style: normal; }}
    .decision-row b {{ text-align: right; }}
    .empty {{ color: var(--muted); margin: 0; }}
    [aria-disabled="true"] {{ cursor: default; pointer-events: none; opacity: .62; }}
    footer {{ margin-top: 30px; color: var(--muted); font-size: 12px; border-top: 1px solid var(--line); padding-top: 16px; }}
    @media (max-width: 1100px) {{
      .index-grid, .kpis {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .split {{ grid-template-columns: 1fr; }}
      .side-panel {{ position: static; }}
      .strategy-row {{ grid-template-columns: 1fr 1fr 1fr; }}
    }}
    @media (max-width: 680px) {{
      .shell {{ width: min(100vw - 24px, 1480px); padding-top: 14px; }}
      .topbar {{ grid-template-columns: 1fr; }}
      .actions {{ justify-content: flex-start; }}
      .index-grid, .kpis {{ grid-template-columns: 1fr; }}
      .strategy-row {{ grid-template-columns: 1fr 1fr; }}
      .mini-link {{ grid-template-columns: 1fr; }}
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
          <h1>QuantYB 总控面板</h1>
          <p class="subtitle">生成时间 {html.escape(data["generated_at"])} · 本地报告导航</p>
        </div>
      </div>
      <nav class="actions">
        {comparison_link}
        <a class="primary-link" href="index/000001.SH_overview.html">上证指数</a>
      </nav>
    </header>

    <section class="kpis">
      <div class="kpi"><span>指数概览</span><strong>{index_count}</strong></div>
      <div class="kpi"><span>策略模块</span><strong>{strategy_count}</strong></div>
      <div class="kpi"><span>单标的报告</span><strong>{data["stock_report_count"]}</strong></div>
      <div class="kpi"><span>信号复盘</span><strong>{decision_count}</strong></div>
    </section>

    <section>
      <div class="section-head"><h2>指数导航</h2><span>index_daily · 日K/周K/月K · MACD/KDJ/RSI</span></div>
      <div class="index-grid">
        {_build_index_cards(data)}
      </div>
    </section>

    <section class="split">
      <div>
        <div class="section-head"><h2>策略汇总</h2><span>来自 output/trades/_summary_*.csv</span></div>
        <div class="strategy-list">
          {_build_strategy_cards(data)}
        </div>
      </div>
      <aside class="side-panel">
        <h3>信号复盘</h3>
        {_build_decision_panel(data)}
        <h3 style="margin-top:18px;">最近单标的报告</h3>
        <div class="mini-list">
          {_build_recent_reports(data)}
        </div>
      </aside>
    </section>

    <footer>数据和链接均来自本地 output 目录；缺失项会显示待生成。</footer>
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
