"""Readable HTML report for local market-data quality checks."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from visual.components import html_document


STATUS_LABELS = {"healthy": "正常", "warning": "需关注", "critical": "异常"}


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "--"


def _amount(value: Any) -> str:
    try:
        return f"{float(value) / 1_0000_0000_0000:.2f}万亿"
    except (TypeError, ValueError):
        return "--"


def generate_data_quality_report(result: dict[str, Any], output_path: str | Path) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    datasets = result.get("datasets") or {}
    stocks = datasets.get("stocks") or {}
    indexes = datasets.get("indexes") or {}
    daily_basic = datasets.get("daily_basic") or {}
    summary = result.get("summary") or {}
    remediation = result.get("remediation") or {}
    status = str(result.get("status") or "warning")
    issue_rows = []
    for item in (result.get("issues") or [])[:300]:
        issue_rows.append(
            "<tr>"
            f"<td><span class='severity {html.escape(str(item.get('severity', '')))}'>{html.escape(str(item.get('severity', '')))}</span></td>"
            f"<td>{html.escape(str(item.get('dataset', '')))}</td>"
            f"<td>{html.escape(str(item.get('symbol', '')))}</td>"
            f"<td>{html.escape(str(item.get('check', '')))}</td>"
            f"<td>{html.escape(str(item.get('detail', '')))}</td>"
            "</tr>"
        )
    if not issue_rows:
        issue_rows.append("<tr><td colspan='5' class='empty'>未发现问题</td></tr>")
    redownload_symbols = remediation.get("stock_redownload_symbols") or []
    remediation_html = ""
    if redownload_symbols:
        command = str(remediation.get("stock_redownload_command") or "")
        remediation_html = f"""
        <section class="remediation">
          <div><h2>建议修复</h2><p>{len(redownload_symbols)} 只股票存在严重历史行情异常。清洗器已阻止同类坏行再次写入；确认网络与 Tushare 配额后，可强制重拉这些标的。</p></div>
          <code>{html.escape(command)}</code>
        </section>
        """
    notes = "".join(f"<li>{html.escape(str(note))}</li>" for note in result.get("notes") or [])
    body = f"""
    <main class="page">
      <header>
        <div><p class="eyebrow">QuantYB 数据可信度</p><h1>本地市场数据质量报告</h1><p>{html.escape(str(result.get('generated_at', '')))} · {html.escape(str(result.get('scope', '')))}</p></div>
        <span class="status {html.escape(status)}">{STATUS_LABELS.get(status, status)}</span>
      </header>
      <section class="metrics">
        <article><span>个股缓存</span><strong>{stocks.get('file_count', 0)}</strong><small>{stocks.get('reference_date', '--')} · 覆盖 {_pct(stocks.get('latest_coverage'))}</small></article>
        <article><span>全市场成交额</span><strong>{_amount(stocks.get('latest_amount_cny'))}</strong><small>Tushare 千元口径换算</small></article>
        <article><span>指数缓存</span><strong>{indexes.get('file_count', 0)}</strong><small>{indexes.get('reference_date', '--')} · 覆盖 {_pct(indexes.get('latest_coverage'))}</small></article>
        <article><span>每日指标</span><strong>{daily_basic.get('file_count', 0)}</strong><small>{daily_basic.get('reference_date', '--')} · 覆盖 {_pct(daily_basic.get('latest_coverage'))}</small></article>
      </section>
      <section class="summary">
        <div><span>严重</span><strong>{summary.get('critical_count', 0)}</strong></div>
        <div><span>警告</span><strong>{summary.get('warning_count', 0)}</strong></div>
        <div><span>个股陈旧</span><strong>{stocks.get('stale_count', 0)}</strong></div>
        <div><span>指数陈旧</span><strong>{indexes.get('stale_count', 0)}</strong></div>
      </section>
      {remediation_html}
      <section>
        <div class="section-head"><h2>问题明细</h2><span>最多展示 300 条；完整记录见同目录 CSV / JSON</span></div>
        <div class="table-wrap"><table><thead><tr><th>级别</th><th>数据集</th><th>标的</th><th>检查项</th><th>说明</th></tr></thead><tbody>{''.join(issue_rows)}</tbody></table></div>
      </section>
      <section class="notes"><h2>口径与限制</h2><ul>{notes}</ul></section>
    </main>
    """
    document = html_document(
        title="QuantYB 数据质量报告",
        styles="""
        :root { --ink:#202631; --muted:#657084; --line:#d5dde8; --paper:#eef2f4; --panel:#fff; --blue:#2d6cdf; --red:#c84545; --amber:#a56a18; --green:#15805d; }
        * { box-sizing:border-box; } body { margin:0; color:var(--ink); background:var(--paper); font-family:"Microsoft YaHei","PingFang SC",sans-serif; font-size:14px; }
        .page { width:min(1320px,calc(100vw - 32px)); margin:0 auto; padding:22px 0 40px; }
        header { display:flex; align-items:center; justify-content:space-between; gap:20px; padding:20px; background:var(--panel); border:1px solid var(--line); border-radius:8px; }
        h1,h2,p { margin:0; } h1 { font-size:28px; letter-spacing:0; } h2 { font-size:18px; letter-spacing:0; }
        header p:last-child,.section-head span,.metrics small { color:var(--muted); } .eyebrow { color:var(--blue); font-weight:800; margin-bottom:5px; }
        .status { min-width:88px; padding:9px 12px; text-align:center; border-radius:7px; font-weight:900; border:1px solid var(--line); }
        .status.healthy { color:var(--green); background:#eff9f4; } .status.warning { color:var(--amber); background:#fff8eb; } .status.critical { color:var(--red); background:#fff1f1; }
        .metrics { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin-top:12px; }
        .metrics article,.summary,.table-wrap,.notes,.remediation { background:var(--panel); border:1px solid var(--line); border-radius:8px; }
        .metrics article { min-height:112px; padding:15px; display:flex; flex-direction:column; justify-content:flex-end; }
        .metrics span,.summary span { color:var(--muted); font-size:12px; } .metrics strong { font-size:26px; margin:5px 0; }
        .summary { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:0; margin-top:10px; padding:13px; }
        .summary div { padding:4px 13px; border-right:1px solid var(--line); } .summary div:last-child { border:0; } .summary strong { display:block; font-size:20px; margin-top:4px; }
        .remediation { padding:16px; display:grid; grid-template-columns:minmax(0,1fr) minmax(320px,auto); gap:16px; align-items:center; border-left:4px solid var(--red); }
        .remediation p { color:var(--muted); margin-top:6px; line-height:1.6; }
        .remediation code { display:block; padding:10px 12px; overflow:auto; background:#f7f9fb; border:1px solid var(--line); border-radius:6px; white-space:nowrap; }
        section { margin-top:18px; } .section-head { display:flex; justify-content:space-between; align-items:baseline; gap:12px; margin-bottom:8px; }
        .table-wrap { overflow:auto; } table { width:100%; border-collapse:collapse; } th,td { padding:10px 12px; text-align:left; border-bottom:1px solid #e6ebf1; white-space:nowrap; } th { background:#f7f9fb; color:var(--muted); font-size:12px; } td:last-child { white-space:normal; min-width:360px; }
        .severity { font-weight:800; } .severity.critical { color:var(--red); } .severity.warning { color:var(--amber); } .empty { color:var(--muted); text-align:center; padding:28px; }
        .notes { padding:16px; } .notes ul { margin:10px 0 0; padding-left:20px; color:var(--muted); line-height:1.7; }
        @media (max-width:850px) { .metrics { grid-template-columns:repeat(2,minmax(0,1fr)); } .summary { grid-template-columns:repeat(2,minmax(0,1fr)); } .summary div:nth-child(2) { border-right:0; } .remediation { grid-template-columns:1fr; } header { align-items:flex-start; } }
        """,
        body=body,
    )
    target.write_text(document, encoding="utf-8")
    return target
