"""Read-only product navigation shell for the local QuantYB reports."""

from __future__ import annotations

import csv
import html
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from visual.components import html_document, relative_href


PRODUCT_SHELL_MARKER = 'data-product-shell="v1"'


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError, TypeError):
        return {}


def _latest_file(directory: Path, pattern: str) -> Path | None:
    if not directory.exists():
        return None
    candidates = list(directory.glob(pattern))
    # Research outputs encode their as-of date in the file name; this is more
    # reliable than an old report being regenerated later and changing mtime.
    return max(candidates, key=lambda item: item.name) if candidates else None


def _file_entry(output_path: Path, path: Path, label: str, command: str = "") -> dict[str, str | bool]:
    exists = path.exists()
    return {
        "label": label,
        "exists": exists,
        "href": relative_href(output_path, path) if exists else "",
        "command": command,
    }


def _read_radar_summary(path: Path) -> dict[str, str | int]:
    summary: dict[str, str | int] = {"date": "--", "core": 0, "accelerating": 0, "breakout": 0}
    if not path.exists():
        return summary
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError:
        return summary
    if not rows:
        return summary
    summary["date"] = str(rows[-1].get("trade_date") or "--")
    for state, key in (("CORE_STRONG", "core"), ("ACCELERATING", "accelerating"), ("BREAKOUT", "breakout")):
        summary[key] = sum(1 for row in rows if row.get("state") == state)
    return summary


def _read_vpt_summary(path: Path | None, snapshot_path: Path | None = None) -> dict[str, str | int]:
    summary: dict[str, str | int] = {"date": "--", "candidates": 0, "qualified": 0}
    if path is None or not path.exists():
        return summary
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError:
        return summary
    summary["candidates"] = len(rows)
    if rows:
        summary["date"] = str(rows[-1].get("trade_date") or "--")
        summary["qualified"] = sum(1 for row in rows if row.get("vpt_state") == "QUALIFIED")
    if snapshot_path is not None and snapshot_path.exists():
        try:
            with snapshot_path.open(encoding="utf-8-sig", newline="") as handle:
                snapshot = list(csv.DictReader(handle))
        except OSError:
            snapshot = []
        if snapshot:
            dates = [str(row.get("trade_date") or "") for row in snapshot]
            summary["date"] = max((value for value in dates if value), default=str(summary["date"]))
            summary["qualified"] = sum(
                1
                for row in snapshot
                if row.get("vpt_state") == "QUALIFIED"
                and str(row.get("is_current_date", "")).strip().lower() == "true"
                and str(row.get("eligible", "")).strip().lower() == "true"
            )
    return summary


def _collect_product_data(config: dict, output_path: Path) -> dict[str, Any]:
    output = config.get("output") or {}
    reports_dir = Path(output.get("reports_dir", "output/reports"))
    stats_dir = Path(output.get("statistics_dir", "output/statistics"))
    signals_dir = Path(output.get("signals_dir", "output/signals"))
    audit = _read_json(stats_dir / "data_quality" / "market_data_audit.json")
    stocks = (audit.get("datasets") or {}).get("stocks") or {}
    market_structure = _read_json(stats_dir / "index_forecast" / "market_structure_000001.SH.json")
    state = market_structure.get("market_structure") or {}
    radar_path = stats_dir / "strong_stock_radar" / "strong_stock_radar_latest.csv"
    radar = _read_radar_summary(radar_path)

    latest_rps = _latest_file(stats_dir, "rps_top_*.html")
    latest_limit = _latest_file(stats_dir / "limit_strength", "limit_strength_????????.html")
    latest_support = _latest_file(reports_dir / "support_resistance", "*_support_resistance.html")
    latest_pattern = _latest_file(signals_dir, "pattern_signals_*.html")
    latest_vpt = _latest_file(signals_dir, "vpt_candidates_*.csv")
    latest_vpt_snapshot = _latest_file(stats_dir / "vpt", "vpt_snapshot_*.csv")
    vpt = _read_vpt_summary(latest_vpt, latest_vpt_snapshot)

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data_quality": {
            **_file_entry(output_path, reports_dir / "data_quality.html", "数据质量报告", "python main.py data audit"),
            "status": str(audit.get("status") or "未审计"),
            "reference_date": str(stocks.get("reference_date") or "--"),
            "coverage": stocks.get("latest_coverage"),
        },
        "market": {
            "style": str(state.get("style_regime_name") or "--"),
            "breadth": str(state.get("breadth_state") or "--"),
            "date": str(market_structure.get("date") or "--"),
        },
        "radar": radar,
        "vpt": vpt,
        "primary": [
            ("今日总览", "#overview"),
            ("数据中心", "#data"),
            ("市场环境", "#market"),
            ("行情中心", "#quotes"),
            ("强势方向", "#strength"),
            ("策略选股", "#strategy"),
        ],
        "market_links": [
            _file_entry(output_path, reports_dir / "index_forecast" / "000001.SH_market_environment.html", "市场环境", "python main.py index environment"),
            _file_entry(output_path, reports_dir / "index_forecast" / "000001.SH_market_structure_brief.html", "市场结构摘录（详细研究）", "python main.py index structure-brief"),
            _file_entry(output_path, reports_dir / "index_forecast" / "000001.SH_market_structure.html", "市场结构完整报告", "python main.py index forecast"),
            _file_entry(output_path, reports_dir / "market_overview.html", "市场概览", "python main.py index market"),
        ],
        "quote_tabs": {
            "指数": [_file_entry(output_path, reports_dir / "market_overview.html", "指数行情", "python main.py index market")],
            "行业": [_file_entry(output_path, reports_dir / "industry" / "industry_market.html", "行业行情", "python main.py index structure-brief")],
            "主题": [_file_entry(output_path, reports_dir / "concept" / "concept_market.html", "主题行情", "python main.py index structure-brief")],
            "个股": [_file_entry(output_path, reports_dir / "stock_viewer.html", "股票查看器", "python main.py dashboard --legacy")],
            "自选": [_file_entry(output_path, reports_dir / "stock_selector.html", "股票筛选器", "python main.py dashboard --legacy")],
        },
        "strength_links": [
            _file_entry(output_path, reports_dir / "strong_stock_radar" / "strong_stock_radar.html", "强势股雷达", "python main.py stats radar"),
            _file_entry(output_path, latest_limit or stats_dir / "limit_strength" / "limit_strength_latest.html", "涨停强势", "python main.py stats limit-strength"),
        ],
        "strategy_links": [
            _file_entry(
                output_path,
                reports_dir / "vpt" / "vpt_candidates.html",
                "VPT-01 放量启动—供给收缩趋势",
                "python main.py stats vpt",
            ),
        ],
        "research_links": [
            _file_entry(output_path, reports_dir / "legacy_dashboard.html", "旧版总面板", "python main.py dashboard --legacy"),
            _file_entry(output_path, reports_dir / "sector_money_flow.html", "行业资金流", "python main.py sector-flow report"),
            _file_entry(output_path, reports_dir / "etf_strategy" / "etf_strategy_dashboard.html", "ETF 研究", "python main.py etf report"),
            _file_entry(output_path, latest_rps or stats_dir / "rps_top_latest.html", "RPS 排行", "python main.py stats rps"),
            _file_entry(output_path, latest_pattern or signals_dir / "pattern_signals_latest.html", "形态扫描", "python main.py stats patterns"),
            _file_entry(output_path, latest_support or reports_dir / "support_resistance" / "support_resistance.html", "支撑压力", "python main.py stats support-resistance --symbol 688981"),
            _file_entry(output_path, reports_dir / "project_optimization_audit.html", "优化审计", "python main.py dashboard --legacy"),
        ],
    }


def _link(entry: dict[str, str | bool]) -> str:
    label = html.escape(str(entry["label"]))
    if entry["exists"]:
        return f'<a class="entry" href="{html.escape(str(entry["href"]), quote=True)}">{label}<span>打开</span></a>'
    command = html.escape(str(entry["command"]))
    return f'<div class="entry missing"><span>{label}</span><small>待生成 · {command}</small></div>'


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "--"


def _build_html(data: dict[str, Any]) -> str:
    nav = "".join(f'<a href="{href}">{html.escape(label)}</a>' for label, href in data["primary"])
    tabs = "".join(
        f'<section class="quote-tab"><h3>{html.escape(name)}</h3>{"".join(_link(item) for item in links)}</section>'
        for name, links in data["quote_tabs"].items()
    )
    quality = data["data_quality"]
    radar = data["radar"]
    vpt = data["vpt"]
    body = f'''
    <div class="shell" {PRODUCT_SHELL_MARKER}>
      <header class="topbar"><a class="brand" href="#overview">QuantYB</a><nav>{nav}</nav></header>
      <main>
        <section id="overview" class="hero"><p class="eyebrow">本地 A 股研究工作台</p><h1>今日总览</h1><p>只读已有本地报告；数据更新、指标计算和策略运行仍通过原有命令完成。</p><small>页面生成：{html.escape(str(data["generated_at"]))}</small></section>
        <section class="summary-grid">
          <article><span>数据状态</span><strong>{html.escape(str(quality["status"]))}</strong><small>{html.escape(str(quality["reference_date"]))} · 覆盖 {_pct(quality["coverage"])}</small></article>
          <article><span>市场环境</span><strong>{html.escape(str(data["market"]["style"]))}</strong><small>{html.escape(str(data["market"]["date"]))} · 广度 {html.escape(str(data["market"]["breadth"]))}</small></article>
          <article><span>核心强势</span><strong>{radar["core"]}</strong><small>加速 {radar["accelerating"]} · 突破 {radar["breakout"]}</small></article>
          <article><span>VPT-01 报告候选</span><strong>{vpt["candidates"]}</strong><small>{html.escape(str(vpt["date"]))} · 全量合格 {vpt["qualified"]}</small></article>
        </section>
        <section id="data" class="band"><div class="section-head"><div><p class="eyebrow">01</p><h2>数据中心</h2></div><p>数据状态、覆盖率与质量检查。</p></div>{_link(quality)}</section>
        <section id="market" class="band"><div class="section-head"><div><p class="eyebrow">02</p><h2>市场环境</h2></div><p>市场状态的观察与复盘，不改变既有市场结构口径。</p></div><div class="entry-grid">{"".join(_link(item) for item in data["market_links"])}</div></section>
        <section id="quotes" class="band"><div class="section-head"><div><p class="eyebrow">03</p><h2>行情中心</h2></div><p>指数、行业、主题与个股的已有页面入口。</p></div><div class="quote-grid">{tabs}</div></section>
        <section id="strength" class="band"><div class="section-head"><div><p class="eyebrow">04</p><h2>强势方向</h2></div><p>行业、主题和强势个股的横截面观察。</p></div><div class="entry-grid">{"".join(_link(item) for item in data["strength_links"])}</div></section>
        <section id="strategy" class="band"><div class="section-head"><div><p class="eyebrow">05</p><h2>策略选股</h2></div><p>确定性研究筛选，只输出候选与可审计指标。</p></div><div class="entry-grid">{"".join(_link(item) for item in data["strategy_links"])}</div><p class="placeholder">VPT 与 RS 保持独立，仅供人工交叉观察，不写入仓位、订单或风险闸门。</p></section>
        <section id="research" class="band research"><div class="section-head"><div><p class="eyebrow">研究工具</p><h2>备用报告入口</h2></div><p>保留原有研究模块，不放入主导航。</p></div><div class="entry-grid">{"".join(_link(item) for item in data["research_links"])}</div></section>
      </main>
    </div>'''
    return html_document(
        title="QuantYB 研究工作台",
        body=body,
        head_extra='<link rel="icon" href="data:,">',
        styles='''
        :root { --ink:#172033; --muted:#68758b; --line:#d9e1ec; --paper:#f3f6f9; --panel:#fff; --blue:#2468d8; --green:#147a5b; --amber:#a96812; }
        * { box-sizing:border-box; } html { scroll-behavior:smooth; } body { margin:0; color:var(--ink); background:var(--paper); font:14px/1.55 "Microsoft YaHei","PingFang SC",sans-serif; }
        .shell { width:min(1280px,calc(100vw - 32px)); margin:0 auto; padding:16px 0 44px; } .topbar { position:sticky; top:0; z-index:2; display:flex; align-items:center; gap:28px; min-height:52px; padding:0 16px; background:rgba(255,255,255,.96); border:1px solid var(--line); border-radius:8px; }
        .brand { color:var(--blue); font-weight:800; font-size:17px; text-decoration:none; } nav { display:flex; gap:16px; overflow:auto; } nav a { color:var(--muted); text-decoration:none; white-space:nowrap; font-weight:700; } nav a:hover { color:var(--blue); }
        main { display:grid; gap:14px; margin-top:14px; } .hero,.band,.summary-grid article { background:var(--panel); border:1px solid var(--line); border-radius:8px; } .hero { padding:24px; } h1,h2,h3,p { margin:0; } h1 { font-size:30px; } h2 { font-size:21px; } h3 { font-size:14px; } .hero p:not(.eyebrow) { color:var(--muted); margin-top:7px; } .hero small { display:block; color:var(--muted); margin-top:10px; }
        .eyebrow { color:var(--blue); font-size:12px; font-weight:800; } .summary-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; } .summary-grid article { padding:15px; min-height:102px; display:flex; flex-direction:column; justify-content:flex-end; } .summary-grid span,.summary-grid small { color:var(--muted); } .summary-grid strong { font-size:23px; margin:5px 0; }
        .band { padding:18px; } .section-head { display:flex; align-items:end; justify-content:space-between; gap:16px; margin-bottom:13px; } .section-head p:last-child { color:var(--muted); text-align:right; } .entry-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:9px; } .entry { min-height:52px; padding:12px; border:1px solid var(--line); border-radius:6px; color:var(--ink); text-decoration:none; display:flex; justify-content:space-between; align-items:center; gap:10px; font-weight:700; } .entry:hover { border-color:var(--blue); color:var(--blue); } .entry span { color:var(--blue); font-size:12px; } .entry.missing { display:block; color:var(--muted); font-weight:600; } .entry.missing small { display:block; margin-top:4px; color:var(--amber); font:12px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace; overflow-wrap:anywhere; }
        .quote-grid { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:9px; } .quote-tab { min-width:0; padding:11px; background:#f8fafc; border:1px solid var(--line); border-radius:6px; } .quote-tab h3 { color:var(--muted); margin-bottom:8px; } .quote-tab .entry { min-height:44px; padding:9px; font-size:13px; } .placeholder { color:var(--muted); padding:14px; border-left:3px solid var(--blue); background:#f8fafc; } .research { background:#fbfcfd; }
        @media (max-width:900px) { .summary-grid,.entry-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } .quote-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } .topbar { align-items:flex-start; padding:12px; gap:12px; } nav { gap:12px; } }
        @media (max-width:560px) { .shell { width:min(100% - 20px,1280px); } .summary-grid,.entry-grid,.quote-grid { grid-template-columns:1fr; } .section-head { align-items:flex-start; flex-direction:column; } .section-head p:last-child { text-align:left; } h1 { font-size:26px; } }
        ''',
    )


def generate_product_dashboard(config: dict, output_path: str | Path | None = None) -> Path:
    """Write the read-only product shell without generating any underlying reports."""
    reports_dir = Path((config.get("output") or {}).get("reports_dir", "output/reports"))
    target = Path(output_path) if output_path else reports_dir / "dashboard.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    legacy_path = reports_dir / "legacy_dashboard.html"
    if target == reports_dir / "dashboard.html" and target.exists() and not legacy_path.exists():
        try:
            current = target.read_text(encoding="utf-8", errors="ignore")
            if PRODUCT_SHELL_MARKER not in current:
                shutil.copy2(target, legacy_path)
        except OSError:
            pass
    target.write_text(_build_html(_collect_product_data(config, target)), encoding="utf-8")
    return target
