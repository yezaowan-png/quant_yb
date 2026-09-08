"""Read-only market-environment summary built from saved market-structure facts."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from visual.components import html_document, relative_href


_STATE_LABELS = {
    "uptrend": "上行", "sideways": "震荡", "downtrend": "下行", "mixed": "分化",
    "strong": "强", "strong_repair": "强修复", "neutral": "中性", "weak": "偏弱", "very_weak": "弱势",
    "normal": "正常", "low": "低", "medium": "中等", "high": "高", "extreme": "极端",
    "low_pressure_stable": "低压力稳定", "risk_contracting": "风险收敛", "risk_building": "风险累积",
    "high_pressure_stable": "高压力稳定", "broad": "全面占优", "mixed_rotation": "风格轮动",
}


def _value(value: Any, fallback: str = "暂无明确结论") -> str:
    if value is None or value == "":
        return fallback
    return _STATE_LABELS.get(str(value), str(value))


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:+.1f}%"
    except (TypeError, ValueError):
        return "--"


def _ratio_pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "--"


def _multiple(value: Any) -> str:
    try:
        return f"{float(value):.2f}x"
    except (TypeError, ValueError):
        return "--"


def _amount(value: Any) -> str:
    try:
        cny = float(value) * 1000
    except (TypeError, ValueError):
        return "--"
    if abs(cny) >= 1_000_000_000_000:
        return f"{cny / 1_000_000_000_000:.2f}万亿"
    if abs(cny) >= 100_000_000:
        return f"{cny / 100_000_000:.2f}亿"
    return f"{cny:,.0f}元"


def _metric(label: str, value: Any) -> str:
    return f"<div><dt>{escape(label)}</dt><dd>{escape(str(value))}</dd></div>"


def _evidence_block(title: str, subtitle: str, metrics: list[tuple[str, str]]) -> str:
    return (
        '<article class="evidence-block">'
        f"<h3>{escape(title)}</h3><p>{escape(subtitle)}</p>"
        f"<dl>{''.join(_metric(label, value) for label, value in metrics)}</dl>"
        "</article>"
    )


def _index_metrics(structure: dict[str, Any]) -> list[tuple[str, str]]:
    indices = structure.get("indices") or {}
    rows = []
    for name in ("上证指数", "沪深300", "创业板指"):
        item = indices.get(name) or {}
        rows.append((name, f"当日 {_pct(item.get('return_1d'))} · 20日 {_pct(item.get('return_20d'))}"))
    return rows


def _details_link(output_path: Path, path: Path | None, label: str, command: str) -> str:
    if path is not None and path.exists():
        href = escape(relative_href(output_path, path), quote=True)
        return f'<a class="research-link" href="{href}" target="_blank">{escape(label)}<span>新窗口打开</span></a>'
    return f'<div class="research-link missing"><span>{escape(label)}</span><small>待生成 · {escape(command)}</small></div>'


def generate_market_environment(
    structure: dict[str, Any],
    output_path: str | Path,
    *,
    brief_path: str | Path | None = None,
    full_report_path: str | Path | None = None,
    name: str = "上证指数",
) -> Path:
    """Render a presentation-only summary; the input facts remain unchanged."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    state = structure.get("market_structure") or {}
    trend = state.get("trend") or {}
    state_breadth = state.get("breadth") or {}
    risk = state.get("risk") or {}
    style = state.get("style") or {}
    latest = (structure.get("breadth") or {}).get("latest") or {}
    liquidity = structure.get("liquidity") or {}
    liquidity_latest = (structure.get("liquidity_structure") or {}).get("latest") or {}
    distribution = (structure.get("return_distribution") or {}).get("latest") or latest
    contribution = structure.get("index_lift_structure") or (state.get("index_lift_structure") or {})
    concentration = contribution.get("contribution_concentration") or {}
    turnover = contribution.get("turnover_confirmation") or {}
    raw_detail_lines = [str(line) for line in state.get("detail_lines") or [] if line]
    # Preserve the existing wording while keeping the conclusion layer readable.
    detail_lines = [raw_detail_lines[index] for index in (0, 1, 4, 6) if index < len(raw_detail_lines)]
    flags = structure.get("data_quality_flags") or []
    report_date = str(structure.get("date") or state_breadth.get("latest", {}).get("trade_date") or "--")
    brief = Path(brief_path) if brief_path else None
    full_report = Path(full_report_path) if full_report_path else None

    conclusion_rows = [
        ("综合市场状态", _value(state.get("state"))),
        ("趋势", _value(state.get("trend_state") or trend.get("large_cap_daily"))),
        ("广度", _value(state.get("breadth_state") or state_breadth.get("today_state"))),
        ("流动性", _value(state.get("liquidity_state") or liquidity.get("state"))),
        ("风格", _value(state.get("style_regime_name") or style.get("regime_name"))),
        ("结构风险", _value(risk.get("state") or state.get("tail_pressure_state"))),
    ]
    evidence = [
        _evidence_block("指数", "主要指数当日与20日表现", _index_metrics(structure)),
        _evidence_block("市场广度", "全A有效样本的参与度", [
            ("上涨比例", _ratio_pct(latest.get("advance_ratio"))),
            ("MA20上方", _ratio_pct(latest.get("pct_above_ma20"))),
            ("20日新高 / 新低", f"{_ratio_pct(latest.get('new_high_20_ratio'))} / {_ratio_pct(latest.get('new_low_20_ratio'))}"),
            ("当前广度状态", _value(state_breadth.get("today_state") or state.get("breadth_state"))),
        ]),
        _evidence_block("流动性", "已有成交额与量能结构", [
            ("总成交额", _amount(liquidity_latest.get("total_amount"))),
            ("20日均额比", _multiple(liquidity_latest.get("amount_ratio_20d") or liquidity.get("amount_ratio_20"))),
            ("上涨 / 下跌成交占比", f"{_ratio_pct(liquidity_latest.get('advance_amount_ratio'))} / {_ratio_pct(liquidity_latest.get('decline_amount_ratio'))}"),
            ("流动性状态", _value(liquidity.get("state") or state.get("liquidity_state"))),
        ]),
        _evidence_block("风格", "已有风格轮动状态", [
            ("当前风格", _value(state.get("style_regime_name") or style.get("regime_name"))),
            ("当前领先", _value(style.get("leader") or (structure.get("style_rotation") or {}).get("leader"))),
            ("领先持续", f"{style.get('days_as_leader', '--')} 个交易日"),
            ("20日领先切换", f"{style.get('leader_changes_20d', '--')} 次"),
        ]),
        _evidence_block("横截面涨跌分布", "全A有效股票的当日分位数", [
            ("中位数", _pct(distribution.get("median"))),
            ("Q10 / Q90", f"{_pct(distribution.get('q10'))} / {_pct(distribution.get('q90'))}"),
            ("跌超3%", _ratio_pct(distribution.get("decline_gt_3_ratio"))),
            ("跌超5%", _ratio_pct(distribution.get("decline_gt_5_ratio"))),
        ]),
        _evidence_block("指数贡献结构", f"{contribution.get('index_name') or name} 的已有贡献分析", [
            ("正贡献Top10占比", _ratio_pct(concentration.get("top_10_positive_contribution_share"))),
            ("绝对贡献Top10占比", _ratio_pct(concentration.get("top_10_absolute_contribution_share"))),
            ("成交额Top20占比", _ratio_pct(turnover.get("top20_turnover_amount_share"))),
            ("80%正贡献所需", f"{concentration.get('stocks_needed_for_80pct_positive_contribution', '--')} 只股票"),
        ]),
    ]
    feature_html = "".join(f"<li>{escape(line)}</li>" for line in detail_lines) or "<li>暂无明确结论</li>"
    brief_href = escape(relative_href(output, brief), quote=True) if brief and brief.exists() else "#research"
    iframe = f'<iframe title="市场结构摘录" src="{brief_href}" loading="lazy"></iframe>' if brief and brief.exists() else ""
    body = f'''
    <main class="page">
      <header class="topbar"><a href="../dashboard.html">QuantYB</a><span>市场环境</span><a href="#research">详细研究</a></header>
      <section class="intro"><p class="eyebrow">市场环境</p><h1>{escape(name)}市场环境</h1><div class="meta"><span>交易日期 {escape(report_date)}</span><span>结构版本 {escape(str(structure.get('schema_version') or '--'))}</span><span>数据质量标记 {len(flags)} 项</span></div></section>
      <section class="section conclusion"><div class="section-head"><div><p class="eyebrow">结论</p><h2>市场结论</h2></div><p>只呈现已有 market structure state，不新增评分或推断。</p></div><dl class="conclusion-list">{''.join(_metric(label, value) for label, value in conclusion_rows)}</dl><div class="features"><h3>现有数据直接支持的特征</h3><ul>{feature_html}</ul></div></section>
      <section class="section"><div class="section-head"><div><p class="eyebrow">证据</p><h2>关键证据</h2></div><p>每块仅保留主要字段；完整图表和表格见下方。</p></div><div class="evidence-grid">{''.join(evidence)}</div></section>
      <section id="research" class="section research"><div class="section-head"><div><p class="eyebrow">详细研究</p><h2>完整市场结构资料</h2></div><p>不改变原报告的图表、表格和交互。</p></div><details><summary>展开市场结构摘录</summary><div class="research-actions">{_details_link(output, brief, '市场结构摘录', 'python main.py index structure-brief')}{_details_link(output, full_report, '完整市场结构报告', 'python main.py index structure')}</div>{iframe}</details></section>
      <footer>仅用于市场观察与复盘。所有状态、口径与数据限制以详细研究页和原始 market structure JSON 为准。</footer>
    </main>'''
    document = html_document(
        title=f"{name}市场环境",
        body=body,
        head_extra='<link rel="icon" href="data:,">',
        styles='''
        :root { --ink:#172033; --muted:#68758b; --line:#d9e1ec; --paper:#f3f6f9; --panel:#fff; --blue:#2468d8; } * { box-sizing:border-box; } body { margin:0; background:var(--paper); color:var(--ink); font:14px/1.6 "Microsoft YaHei","PingFang SC",sans-serif; } .page { width:min(1320px,calc(100vw - 32px)); margin:0 auto; padding:16px 0 42px; } .topbar { min-height:48px; display:flex; align-items:center; gap:16px; padding:0 16px; background:#fff; border:1px solid var(--line); border-radius:8px; } .topbar a { color:var(--blue); text-decoration:none; font-weight:800; } .topbar span { font-weight:800; } .topbar a:last-child { margin-left:auto; } .intro,.section { margin-top:13px; background:var(--panel); border:1px solid var(--line); border-radius:8px; } .intro { padding:24px; } h1,h2,h3,p { margin:0; } h1 { font-size:30px; } h2 { font-size:21px; } h3 { font-size:15px; } .eyebrow { color:var(--blue); font-size:12px; font-weight:800; } .meta { display:flex; flex-wrap:wrap; gap:16px; margin-top:10px; color:var(--muted); } .section { padding:18px; } .section-head { display:flex; justify-content:space-between; align-items:end; gap:16px; margin-bottom:14px; } .section-head p:last-child { max-width:520px; color:var(--muted); text-align:right; } .conclusion-list { display:grid; grid-template-columns:160px minmax(0,1fr); margin:0; border-top:1px solid var(--line); } .conclusion-list div { display:contents; } dt,dd { margin:0; padding:10px 0; border-bottom:1px solid #e8edf3; } dt { color:var(--muted); font-size:13px; } dd { font-weight:700; overflow-wrap:anywhere; } .features { margin-top:16px; padding:14px 16px; background:#f8fafc; border-left:3px solid var(--blue); } .features ul { margin:8px 0 0; padding-left:19px; color:#435069; } .evidence-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; } .evidence-block { min-width:0; padding:14px; border:1px solid var(--line); border-radius:6px; } .evidence-block p { color:var(--muted); font-size:12px; margin-top:3px; } .evidence-block dl { margin:10px 0 0; } .evidence-block dl div { display:flex; justify-content:space-between; gap:12px; padding:5px 0; border-top:1px solid #edf1f5; } .evidence-block dt { border:0; padding:0; } .evidence-block dd { border:0; padding:0; text-align:right; font-size:13px; } details { border:1px solid var(--line); border-radius:6px; overflow:hidden; } summary { cursor:pointer; padding:13px 15px; font-size:15px; font-weight:800; list-style:none; } summary::-webkit-details-marker { display:none; } summary::after { content:"展开"; float:right; color:var(--blue); font-size:13px; } details[open] summary::after { content:"收起"; } .research-actions { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; padding:0 14px 14px; } .research-link { display:flex; align-items:center; justify-content:space-between; min-height:48px; padding:10px; color:var(--ink); border:1px solid var(--line); border-radius:6px; text-decoration:none; font-weight:700; } .research-link:hover { color:var(--blue); border-color:var(--blue); } .research-link span { color:var(--blue); font-size:12px; } .research-link.missing { color:var(--muted); } .research-link.missing small { color:#a96812; overflow-wrap:anywhere; } iframe { display:block; width:100%; height:900px; border:0; border-top:1px solid var(--line); background:#f8fafc; } footer { color:var(--muted); margin:16px 4px 0; font-size:12px; } @media (max-width:900px) { .evidence-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } } @media (max-width:600px) { .page { width:min(100% - 20px,1320px); } h1 { font-size:25px; } .section-head { align-items:flex-start; flex-direction:column; } .section-head p:last-child { text-align:left; } .conclusion-list { grid-template-columns:1fr; } .conclusion-list dt { padding-bottom:0; border-bottom:0; } .evidence-grid,.research-actions { grid-template-columns:1fr; } iframe { height:720px; } }
        ''',
    )
    output.write_text(document, encoding="utf-8")
    return output
