"""Static, interactive report for VPT-01 candidates."""

from __future__ import annotations

import html
from pathlib import Path

import pandas as pd

from analysis.vpt import VPTConfig
from visual.components import html_document, safe_json, stock_report_href


DISPLAY_COLUMNS = [
    ("ts_code", "股票代码"),
    ("name", "股票名称"),
    ("close", "最新价"),
    ("vpt_score", "VPT Score"),
    ("vpt_state", "当前状态"),
    ("t0_date", "T0日期"),
    ("days_since_t0", "距T0"),
    ("t0_volume_spike_ratio", "T0量比"),
    ("udvr", "UDVR"),
    ("dv", "DV"),
    ("pvr", "PVR"),
    ("trend_r2", "趋势R²"),
    ("rs5_pct", "RS5"),
    ("rs10_pct", "RS10"),
    ("failure_flags", "风险标签"),
]


def _records(frame: pd.DataFrame, project_config: dict, output_path: Path) -> list[dict[str, object]]:
    if frame.empty:
        return []
    work = frame.astype(object).where(pd.notna(frame), None)
    rows = work.to_dict("records")
    for row in rows:
        row["stock_href"] = stock_report_href(project_config, output_path, row.get("ts_code"))
    return rows


def _history_records(frame: pd.DataFrame) -> dict[str, list[dict[str, object]]]:
    if frame.empty or "ts_code" not in frame.columns:
        return {}
    selected = [
        column
        for column in (
            "trade_date",
            "vpt_state",
            "vpt_score",
            "udvr",
            "dv",
            "pvr",
            "trend_r2",
            "qualification_flags",
            "failure_flags",
        )
        if column in frame.columns
    ]
    result = {}
    for symbol, group in frame.groupby("ts_code", sort=False):
        compact = group[selected].astype(object).where(pd.notna(group[selected]), None)
        result[str(symbol)] = compact.to_dict("records")
    return result


def build_vpt_report(
    project_config: dict,
    *,
    candidates: pd.DataFrame,
    history: pd.DataFrame,
    output_path: str | Path,
    trade_date: str,
    config: VPTConfig,
) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = _records(candidates, project_config, target)
    timelines = _history_records(history)
    adjustment = str(project_config.get("data", {}).get("stock_adj") or "none")
    header = "".join(
        f'<th><button type="button" data-sort="{html.escape(field)}">{html.escape(label)} <span>↕</span></button></th>'
        for field, label in DISPLAY_COLUMNS
    )
    body = f"""
    <main>
      <header class="page-head">
        <div>
          <div class="eyebrow">QuantYB 研究筛选</div>
          <h1>VPT-01 放量启动—供给收缩趋势</h1>
          <p>数据截止 {html.escape(str(trade_date))} · 本地日K（复权 {html.escape(adjustment)}） · 仅使用截止日及以前数据 · 不生成交易指令</p>
        </div>
        <div class="count"><strong>{len(rows)}</strong><span>当前候选</span></div>
      </header>
      <section class="controls" aria-label="候选筛选">
        <label>状态
          <select id="state-filter">
            <option value="ALL">全部</option>
            <option>SPIKE_DETECTED</option><option>TREND_CONFIRMING</option>
            <option>QUALIFIED</option><option>WEAKENING</option>
          </select>
        </label>
        <label>最低分
          <select id="score-filter"><option value="0">全部</option><option value="{config.candidate_score:g}">≥{config.candidate_score:g}</option><option value="{config.strong_candidate_score:g}">≥{config.strong_candidate_score:g}</option></select>
        </label>
        <span id="shown-count"></span>
      </section>
      <p class="note">QUALIFIED 同时要求有效启动、趋势健康、上涨量占优和有效缩量回调。UDVR 或 PVR 缺失时不会用极端值补齐。点击股票查看评分拆解和状态时间线。</p>
      <section class="table-wrap">
        <table><thead><tr>{header}</tr></thead><tbody id="candidate-body"></tbody></table>
      </section>
      <section id="detail" class="detail" hidden>
        <div class="detail-head"><div><h2 id="detail-title"></h2><p id="detail-summary"></p></div><button id="detail-close" type="button" aria-label="关闭">×</button></div>
        <div id="score-parts" class="score-parts"></div>
        <h3>状态变化时间线</h3>
        <div class="timeline-wrap"><table><thead><tr><th>日期</th><th>状态</th><th>分数</th><th>UDVR</th><th>DV</th><th>PVR</th><th>趋势R²</th><th>结构/风险</th></tr></thead><tbody id="timeline-body"></tbody></table></div>
      </section>
      <details class="method">
        <summary>查看默认参数与口径</summary>
        <pre>{html.escape(str(config.to_dict()))}</pre>
      </details>
    </main>
    """
    styles = """
    *{box-sizing:border-box} body{margin:0;background:#f3f6f9;color:#172033;font-family:"Microsoft YaHei","Noto Sans SC",sans-serif;letter-spacing:0}
    main{width:min(1600px,calc(100vw - 32px));margin:0 auto;padding:24px 0 40px}.page-head{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;border-bottom:1px solid #d7e0eb;padding:8px 4px 20px}
    .eyebrow{color:#2563eb;font-weight:700;font-size:14px}h1{margin:5px 0 7px;font-size:30px}p{margin:0;color:#667085}.count{display:flex;align-items:baseline;gap:8px}.count strong{font-size:28px}.count span{color:#667085}
    .controls{display:flex;align-items:end;gap:12px;padding:16px 0}.controls label{display:grid;gap:5px;color:#475467;font-size:13px}.controls select{height:36px;border:1px solid #bdc9d8;background:white;padding:0 32px 0 10px;color:#172033}.controls span{margin-left:auto;color:#667085;padding-bottom:8px}
    .note{padding:0 0 14px;line-height:1.7}.table-wrap,.timeline-wrap{overflow:auto;border:1px solid #d7e0eb;background:white;max-height:650px}table{border-collapse:collapse;width:100%;font-size:13px;white-space:nowrap}th{position:sticky;top:0;z-index:2;background:#eef3f8;border-bottom:1px solid #ccd7e4;text-align:left}th button{border:0;background:transparent;color:#344054;font-weight:700;padding:10px 9px;cursor:pointer;width:100%;text-align:left}td{padding:9px;border-bottom:1px solid #e5ebf2}tbody tr{cursor:pointer}tbody tr:hover{background:#f4f8ff}a{color:#175cd3}.state{font-weight:700}.QUALIFIED{color:#b42318}.WEAKENING,.FAILED{color:#b54708}.SPIKE_DETECTED{color:#175cd3}.TREND_CONFIRMING{color:#475467}
    .detail{margin-top:18px;background:white;border:1px solid #d7e0eb;padding:18px}.detail-head{display:flex;justify-content:space-between;gap:20px}.detail h2{margin:0 0 5px;font-size:20px}.detail h3{font-size:16px;margin:20px 0 9px}.detail-head button{border:0;background:transparent;font-size:26px;cursor:pointer}.score-parts{display:grid;grid-template-columns:repeat(6,minmax(110px,1fr));gap:1px;background:#d7e0eb;border:1px solid #d7e0eb;margin-top:16px}.score-parts div{background:#f8fafc;padding:10px}.score-parts b{display:block;font-size:18px;margin-top:4px}.method{margin-top:18px;background:white;border:1px solid #d7e0eb;padding:14px}.method summary{cursor:pointer;font-weight:700}.method pre{white-space:pre-wrap;line-height:1.6;color:#475467}
    @media(max-width:800px){main{width:100%;padding:14px}.page-head{align-items:flex-start}.score-parts{grid-template-columns:repeat(2,1fr)}h1{font-size:24px}}
    """
    scripts = f"""
    <script>
    const rows={safe_json(rows, allow_nan=False)};
    const histories={safe_json(timelines, allow_nan=False)};
    const columns={safe_json(DISPLAY_COLUMNS, allow_nan=False)};
    let sortField='vpt_score', sortAsc=false;
    const numFields=new Set(['close','vpt_score','days_since_t0','t0_volume_spike_ratio','udvr','dv','pvr','trend_r2','rs5_pct','rs10_pct']);
    const fmt=(v,f)=>{{if(v===null||v===undefined||v==='')return '—';if(numFields.has(f)){{const n=Number(v);return Number.isFinite(n)?n.toFixed(f==='days_since_t0'?0:2):'—';}}return String(v);}};
    function visibleRows(){{const state=document.getElementById('state-filter').value;const min=Number(document.getElementById('score-filter').value);return rows.filter(r=>(state==='ALL'||r.vpt_state===state)&&Number(r.vpt_score)>=min).sort((a,b)=>{{let av=a[sortField],bv=b[sortField];if(numFields.has(sortField)){{av=Number(av);bv=Number(bv);}}else{{av=String(av??'');bv=String(bv??'');}}if(av===bv)return String(a.ts_code).localeCompare(String(b.ts_code));return(av>bv?1:-1)*(sortAsc?1:-1);}});}}
    function render(){{const data=visibleRows();document.getElementById('shown-count').textContent=`显示 ${{data.length}} / ${{rows.length}}`;document.getElementById('candidate-body').innerHTML=data.map(r=>`<tr data-code="${{r.ts_code}}">${{columns.map(([f])=>`<td>${{f==='ts_code'?`<a href="${{r.stock_href}}" target="_blank">${{r.ts_code}}</a>`:f==='vpt_state'?`<span class="state ${{r.vpt_state}}">${{r.vpt_state}}</span>`:fmt(r[f],f)}}</td>`).join('')}}</tr>`).join('');document.querySelectorAll('#candidate-body tr').forEach(tr=>tr.addEventListener('click',e=>{{if(e.target.tagName!=='A')showDetail(tr.dataset.code);}}));}}
    function showDetail(code){{const r=rows.find(x=>x.ts_code===code);if(!r)return;document.getElementById('detail').hidden=false;document.getElementById('detail-title').textContent=`${{r.name||''}} ${{r.ts_code}}`;document.getElementById('detail-summary').textContent=`${{r.qualification_reason||'暂无正向结构'}}；风险：${{r.failure_reason||'无'}}`;const parts=[['启动质量',r.startup_score],['趋势结构',r.trend_score],['方向成交量',r.volume_structure_score],['回调质量',r.pullback_score],['趋势稳定',r.stability_score],['风险扣分',r.risk_penalty]];document.getElementById('score-parts').innerHTML=parts.map(([n,v])=>`<div><span>${{n}}</span><b>${{fmt(v,'vpt_score')}}</b></div>`).join('');const hs=histories[code]||[];document.getElementById('timeline-body').innerHTML=hs.map(x=>`<tr><td>${{x.trade_date}}</td><td class="state ${{x.vpt_state}}">${{x.vpt_state}}</td><td>${{fmt(x.vpt_score,'vpt_score')}}</td><td>${{fmt(x.udvr,'udvr')}}</td><td>${{fmt(x.dv,'dv')}}</td><td>${{fmt(x.pvr,'pvr')}}</td><td>${{fmt(x.trend_r2,'trend_r2')}}</td><td>${{x.failure_flags&&x.failure_flags!=='[]'?x.failure_flags:x.qualification_flags||'—'}}</td></tr>`).join('');document.getElementById('detail').scrollIntoView({{behavior:'smooth',block:'start'}});}}
    document.querySelectorAll('[data-sort]').forEach(btn=>btn.addEventListener('click',()=>{{const field=btn.dataset.sort;if(sortField===field)sortAsc=!sortAsc;else{{sortField=field;sortAsc=!numFields.has(field);}}render();}}));
    document.getElementById('state-filter').addEventListener('change',render);document.getElementById('score-filter').addEventListener('change',render);document.getElementById('detail-close').addEventListener('click',()=>document.getElementById('detail').hidden=true);render();
    </script>
    """
    target.write_text(
        html_document(
            "VPT-01 候选",
            body,
            styles=styles,
            scripts=scripts,
            head_extra='<link rel="icon" href="data:,">',
        ),
        encoding="utf-8",
    )
    return target
