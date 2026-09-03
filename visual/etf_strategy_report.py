"""Standalone HTML report for ETF strategy research."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

import pandas as pd

from visual.components import html_document, inline_script, relative_href, to_compact_json
from visual.index_report import _echarts_script_tag


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None or value == "":
        return "--"
    try:
        if pd.isna(value):
            return "--"
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:.{digits}f}"


def _fmt_pct(value: Any) -> str:
    text = _fmt(value, 2)
    return "--" if text == "--" else f"{float(text):+.2f}%"


def _tone(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "flat"
    return "up" if number > 0 else "down" if number < 0 else "flat"


def _fmt_amount(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"
    if pd.isna(number):
        return "--"
    if abs(number) >= 100_000_000:
        return f"{number / 100_000_000:.2f}亿"
    if abs(number) >= 10_000:
        return f"{number / 10_000:.0f}万"
    return f"{number:.0f}"


def _action_cls(text: str) -> str:
    if text == "买入":
        return "buy"
    if text == "卖出":
        return "sell"
    return "hold"


def _summary_rows(summary: pd.DataFrame) -> str:
    if summary.empty:
        return '<tr><td colspan="12" class="empty">暂无 ETF 策略数据</td></tr>'
    rows = []
    for _, row in summary.iterrows():
        rows.append(
            f"""
            <tr>
              <td><strong>{html.escape(str(row.get("name", "")))}</strong><span>{html.escape(str(row.get("symbol", "")))}</span></td>
              <td>{html.escape(str(row.get("date", "--")))}</td>
              <td>{html.escape(_fmt(row.get("close"), 4))}</td>
              <td class="{_tone(row.get("return_20d_pct"))}">{html.escape(_fmt_pct(row.get("return_20d_pct")))}</td>
              <td class="{_action_cls(str(row.get("macd_action", "")))}">{html.escape(str(row.get("macd_action", "--")))}</td>
              <td class="{_action_cls(str(row.get("kama_action", "")))}">{html.escape(str(row.get("kama_action", "--")))}</td>
              <td class="{_action_cls(str(row.get("boll_action", "")))}">{html.escape(str(row.get("boll_action", "--")))}</td>
              <td class="{_action_cls(str(row.get("breakout_action", "")))}">{html.escape(str(row.get("breakout_action", "--")))}</td>
              <td class="{_action_cls(str(row.get("atr_action", "")))}">{html.escape(str(row.get("atr_action", "--")))}</td>
              <td>{html.escape(_fmt(row.get("momentum_rank"), 0))}</td>
              <td>{html.escape(_fmt(row.get("factor_rank"), 0))}</td>
              <td>{html.escape(str(row.get("history_bars", "--")))}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def _category_pool_sections(summary: pd.DataFrame, kline_payload: dict[str, Any]) -> str:
    if summary.empty:
        return '<p class="empty">暂无 ETF 分类池</p>'
    categories = list(summary["category"].dropna().astype(str).drop_duplicates())
    tabs = "".join(
        f"""
        <button type="button" class="category-tab {'active' if idx == 0 else ''}" data-category="{html.escape(category, quote=True)}">
          {html.escape(category)} <span>{len(summary.loc[summary['category'].astype(str) == category])}</span>
        </button>
        """
        for idx, category in enumerate(categories)
    )
    panes = []
    for category, group in summary.groupby("category", sort=False):
        sub_rows = []
        for _, row in group.sort_values(["subcategory", "name", "symbol"]).iterrows():
            symbol = str(row.get("symbol", ""))
            latest_amount = ((kline_payload.get(symbol) or {}).get("amount") or [None])[-1]
            sub_rows.append(
                f"""
                <tr class="etf-row" data-symbol="{html.escape(symbol, quote=True)}">
                  <td><strong>{html.escape(str(row.get("name", "")))}</strong><span>{html.escape(symbol)}</span></td>
                  <td>{html.escape(str(row.get("subcategory", "--")))}</td>
                  <td>{html.escape(_fmt(row.get("close"), 4))}</td>
                  <td class="{_tone(row.get("return_20d_pct"))}">{html.escape(_fmt_pct(row.get("return_20d_pct")))}</td>
                  <td class="{_action_cls(str(row.get("macd_action", "")))}">{html.escape(str(row.get("macd_action", "--")))}</td>
                  <td class="{_action_cls(str(row.get("kama_action", "")))}">{html.escape(str(row.get("kama_action", "--")))}</td>
                  <td class="{_action_cls(str(row.get("boll_action", "")))}">{html.escape(str(row.get("boll_action", "--")))}</td>
                  <td class="{_action_cls(str(row.get("breakout_action", "")))}">{html.escape(str(row.get("breakout_action", "--")))}</td>
                  <td class="{_action_cls(str(row.get("atr_action", "")))}">{html.escape(str(row.get("atr_action", "--")))}</td>
                  <td>{html.escape(_fmt(row.get("momentum_rank"), 0))}</td>
                  <td>{html.escape(_fmt(row.get("factor_rank"), 0))}</td>
                  <td>{html.escape(_fmt_amount(latest_amount))}</td>
                </tr>
                """
            )
        panes.append(
            f"""
            <div class="category-pane {'active' if len(panes) == 0 else ''}" data-category="{html.escape(str(category), quote=True)}">
              <div class="category-head">
                <h3>{html.escape(str(category))}</h3>
                <span>{len(group)} 只</span>
              </div>
              <table>
                <thead><tr><th>ETF</th><th>子方向</th><th>收盘</th><th>20日</th><th>MACD</th><th>双KAMA</th><th>布林</th><th>突破</th><th>ATR</th><th>动量</th><th>三因子</th><th>成交额</th></tr></thead>
                <tbody>{''.join(sub_rows)}</tbody>
              </table>
            </div>
            """
        )
    return f"""
    <article class="pool-panel">
      <div class="pool-tabs">{tabs}</div>
      <div class="pool-panes">{''.join(panes)}</div>
    </article>
    """


def _mini_etf_switcher(summary: pd.DataFrame) -> str:
    if summary.empty:
        return ""
    buttons = []
    for _, row in summary.sort_values(["category", "subcategory", "name", "symbol"]).iterrows():
        symbol = str(row.get("symbol", ""))
        buttons.append(
            f"""
            <button type="button" class="mini-etf-chip" data-symbol="{html.escape(symbol, quote=True)}" title="{html.escape(symbol, quote=True)}">
              {html.escape(str(row.get("name", symbol)))}
            </button>
            """
        )
    return f'<div class="mini-etf-switcher" aria-label="ETF 快速切换">{"".join(buttons)}</div>'


def _etf_name_map(summary: pd.DataFrame) -> dict[str, str]:
    if summary.empty or "symbol" not in summary.columns:
        return {}
    return {
        str(row.get("symbol", "")): str(row.get("name") or row.get("symbol", ""))
        for _, row in summary.iterrows()
    }


def _ranking_rows(frame: pd.DataFrame, score_col: str, score_label: str, name_map: dict[str, str] | None = None) -> str:
    if frame.empty:
        return '<tr><td colspan="5" class="empty">暂无轮动排名</td></tr>'
    name_map = name_map or {}
    latest_date = frame["date"].max()
    latest = frame.loc[frame["date"] == latest_date].sort_values("rank").head(10)
    rows = []
    for _, row in latest.iterrows():
        symbol = str(row.get("symbol", ""))
        name = name_map.get(symbol, symbol)
        rows.append(
            f"""
            <tr>
              <td>{html.escape(_fmt(row.get("rank"), 0))}</td>
              <td><strong>{html.escape(name)}</strong><span>{html.escape(symbol)}</span></td>
              <td class="{_tone(row.get(score_col))}">{html.escape(_fmt(row.get(score_col), 4))}</td>
              <td>{'是' if bool(row.get("target")) else '否'}</td>
              <td>{html.escape(str(pd.to_datetime(row.get("date")).date()))}</td>
            </tr>
            """
        )
    return "\n".join(rows).replace("<th>得分</th>", f"<th>{html.escape(score_label)}</th>")


def _external_rank_rows(rank_emotion: dict[str, Any]) -> str:
    ranking = rank_emotion.get("ranking") or []
    if not ranking:
        return '<li class="empty">暂无外部排名文件</li>'
    return "\n".join(f"<li>{idx}. {html.escape(str(item))}</li>" for idx, item in enumerate(ranking[:10], start=1))


def _red_green_rows(items: list[dict[str, Any]]) -> str:
    if not items:
        return '<tr><td colspan="3" class="empty">暂无红绿灯文件</td></tr>'
    rows = []
    for item in items:
        action = {"buy": "买入", "sell": "卖出", "hold": "观望"}.get(str(item.get("action")), "观望")
        rows.append(
            f"""
            <tr>
              <td>{html.escape(str(item.get("symbol", "")))}</td>
              <td class="{_action_cls(action)}">{html.escape(action)}</td>
              <td>{html.escape("；".join(str(reason) for reason in item.get("reasons", [])))}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def generate_etf_strategy_report(
    config: dict[str, Any],
    output_path: str | Path,
    summary: pd.DataFrame,
    timing_rows: list[dict[str, Any]],
    momentum_ranking: pd.DataFrame,
    factor_ranking: pd.DataFrame,
    rank_emotion: dict[str, Any],
    red_green: list[dict[str, Any]],
    load_errors: dict[str, str],
    kline_payload: dict[str, Any],
    artifacts: dict[str, Path],
) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    dashboard_href = relative_href(output, Path(config.get("output", {}).get("reports_dir", "output/reports")) / "dashboard.html")
    artifacts_html = " ".join(
        f'<a class="pill" href="{html.escape(relative_href(output, path))}">{html.escape(label)}</a>'
        for label, path in artifacts.items()
        if Path(path).exists()
    )
    error_html = (
        "<ul>" + "".join(f"<li>{html.escape(symbol)}: {html.escape(reason)}</li>" for symbol, reason in load_errors.items()) + "</ul>"
        if load_errors
        else "<p>全部 ETF 日线加载成功。</p>"
    )
    name_map = _etf_name_map(summary)
    body = f"""
    <main>
      <header>
        <div>
          <p class="kicker">ETF Strategy Desk</p>
          <h1>ETF 策略研究板块</h1>
          <p>独立于股票回测和正式交易链路：只生成 ETF 信号、轮动排名和研究报告，不直接下单。</p>
        </div>
        <nav><a href="{html.escape(dashboard_href)}">返回 Dashboard</a>{artifacts_html}</nav>
      </header>

      <section class="desk-section">
        <div class="section-title"><h2>ETF 分类池</h2><span>在一个池子里切换科技/医药/周期/红利；点击 ETF 后下方刷新图表</span></div>
        {_category_pool_sections(summary, kline_payload)}
      </section>

      <section class="chart-panel">
          <div class="chart-title">
            <div><strong id="etf-chart-name">请选择 ETF</strong><span id="etf-chart-meta">日 K / 成交量 / 成交额</span></div>
            <em>成交额 = Close × Volume；新浪轻量日线接口无原始 amount 字段</em>
          </div>
          {_mini_etf_switcher(summary)}
          <div class="drawing-toolbar" aria-label="ETF 画线工具">
            <span>画线</span>
            <button class="drawing-btn" data-draw-tool="trend" type="button" onclick="setEtfDrawTool('trend')">趋势线</button>
            <button class="drawing-btn" data-draw-tool="support" type="button" onclick="setEtfDrawTool('support')">支撑线</button>
            <button class="drawing-btn" data-draw-tool="resistance" type="button" onclick="setEtfDrawTool('resistance')">阻力线</button>
            <button class="drawing-btn" data-draw-tool="select" type="button" onclick="setEtfDrawTool(null)">选择/调整</button>
            <button class="drawing-btn" type="button" onclick="etfDrawUndo()">撤销</button>
            <button class="drawing-btn danger" type="button" onclick="etfDrawClear()">清空当前 ETF</button>
            <em id="etf-drawing-status">选择工具后在 K 线主图点击画线。</em>
          </div>
          <div id="etf-kline-chart" class="kline-chart"></div>
          <details class="holdings-panel">
            <summary><strong>对应持仓股票</strong><span id="etf-holdings-note">读取本地持仓明细缓存</span></summary>
            <div id="etf-holdings-list" class="holdings-list"><p class="empty">请选择 ETF</p></div>
          </details>
      </section>

      <section class="grid">
        <article class="panel">
          <div class="panel-head"><h2>动量轮动策略</h2><span>Close / Close.shift(动量周期) - 1；信号使用前一交易日及以前数据</span></div>
          <table><thead><tr><th>排名</th><th>ETF 名称 / 代码</th><th>动量</th><th>目标持仓</th><th>日期</th></tr></thead><tbody>{_ranking_rows(momentum_ranking, "momentum", "动量", name_map)}</tbody></table>
        </article>
        <article class="panel">
          <div class="panel-head"><h2>三因子轮动策略</h2><span>趋势 R²、动量、成交量因子 Z-Score 组合；避免未来函数</span></div>
          <table><thead><tr><th>排名</th><th>ETF 名称 / 代码</th><th>得分</th><th>目标持仓</th><th>日期</th></tr></thead><tbody>{_ranking_rows(factor_ranking, "score_norm", "综合得分", name_map)}</tbody></table>
        </article>
      </section>

      <section class="grid">
        <article class="panel">
          <div class="panel-head"><h2>外部三因子排名抄作业</h2><span>{html.escape(str(rank_emotion.get("log", "")))}</span></div>
          <ol class="rank-list">{_external_rank_rows(rank_emotion)}</ol>
        </article>
        <article class="panel">
          <div class="panel-head"><h2>指数红绿灯通行</h2><span>读取本地红绿灯文件；无文件时保持观望</span></div>
          <table><thead><tr><th>ETF</th><th>动作</th><th>原因</th></tr></thead><tbody>{_red_green_rows(red_green)}</tbody></table>
        </article>
      </section>

      <section class="panel secondary">
        <div class="panel-head"><h2>数据状态</h2><span>ETF 日线统一为 Open / High / Low / Close / Volume</span></div>
        {error_html}
      </section>
    </main>
    """
    html_text = html_document(
        title="ETF 策略研究板块",
        styles="""
        body { margin:0; background:#eef2f4; color:#202631; font-family:"Microsoft YaHei","Noto Sans SC",sans-serif; font-size:14px; }
        main { width:min(1760px, calc(100vw - 36px)); margin:0 auto; padding:22px 0 40px; }
        header { display:flex; justify-content:space-between; gap:16px; align-items:center; background:#fff; border:1px solid #d5dde8; border-radius:9px; padding:18px 20px; }
        h1 { margin:4px 0 8px; font-size:28px; }
        h2 { margin:0; font-size:18px; }
        p { margin:0; color:#657084; }
        .kicker { color:#2d6cdf; font-weight:900; letter-spacing:.04em; text-transform:uppercase; font-size:12px; }
        nav { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:8px; }
        a, .pill { display:inline-flex; align-items:center; min-height:34px; padding:0 11px; border-radius:7px; border:1px solid #d5dde8; background:#f7f9fb; color:#202631; text-decoration:none; font-weight:900; font-size:12px; }
        header nav a:first-child { background:#2d6cdf; color:#fff; border-color:#245ac0; }
        .section-title { display:flex; justify-content:space-between; gap:12px; align-items:baseline; margin:18px 0 9px; }
        .section-title span { color:#657084; font-size:12px; }
        .pool-panel, .chart-panel { background:#fff; border:1px solid #d5dde8; border-radius:9px; padding:14px; box-shadow:0 1px 2px rgba(31,41,55,.04); }
        .pool-panel { overflow:hidden; }
        .pool-tabs { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px; border-bottom:1px solid #e5eaf1; padding-bottom:10px; }
        .category-tab { min-height:34px; padding:0 12px; border-radius:7px; border:1px solid #d5dde8; background:#f7f9fb; color:#202631; font-weight:900; cursor:pointer; }
        .category-tab span { color:#657084; font-size:12px; margin-left:4px; }
        .category-tab.active { background:#2d6cdf; color:white; border-color:#245ac0; }
        .category-tab.active span { color:#dbe8ff; }
        .pool-panes { max-height:430px; overflow:auto; padding-right:4px; }
        .category-pane { display:none; }
        .category-pane.active { display:block; }
        .category-head { display:flex; justify-content:space-between; align-items:baseline; gap:12px; margin-bottom:10px; }
        .category-head h3 { margin:0; font-size:17px; }
        .category-head span { color:#657084; font-size:12px; font-weight:900; }
        .pool-panel thead th { position:sticky; top:0; z-index:1; }
        .chart-panel { margin-top:14px; }
        .chart-title { display:flex; justify-content:space-between; gap:14px; align-items:flex-start; margin-bottom:10px; }
        .chart-title strong { display:block; font-size:18px; }
        .chart-title span { display:block; margin-top:3px; color:#657084; font-size:12px; }
        .chart-title em { color:#657084; font-size:12px; font-style:normal; max-width:250px; text-align:right; }
        .mini-etf-switcher { position:sticky; top:8px; z-index:5; display:flex; flex-wrap:wrap; gap:6px; max-height:78px; overflow:auto; margin:0 0 8px auto; padding:8px; border:1px solid #d5dde8; border-radius:9px; background:rgba(255,255,255,.94); box-shadow:0 8px 24px rgba(31,41,55,.10); backdrop-filter:blur(8px); }
        .mini-etf-chip { border:1px solid #d5dde8; border-radius:999px; background:#f7f9fb; color:#202631; font-weight:900; font-size:12px; padding:6px 10px; cursor:pointer; }
        .mini-etf-chip:hover, .mini-etf-chip.active { background:#2d6cdf; border-color:#245ac0; color:#fff; }
        .drawing-toolbar { display:flex; flex-wrap:wrap; align-items:center; gap:8px; margin:8px 0 10px; padding:8px 10px; border:1px solid #d5dde8; border-radius:8px; background:#f7f9fb; }
        .drawing-toolbar span { color:#657084; font-size:12px; font-weight:900; margin-right:2px; }
        .drawing-toolbar em { color:#657084; font-size:12px; font-style:normal; margin-left:auto; text-align:right; }
        .drawing-btn { min-height:30px; padding:0 10px; border:1px solid #d5dde8; border-radius:7px; background:#fff; color:#202631; font-weight:900; font-size:12px; cursor:pointer; }
        .drawing-btn:hover, .drawing-btn.active { background:#2d6cdf; border-color:#245ac0; color:#fff; }
        .drawing-btn.danger { color:#b42342; }
        .drawing-btn.danger:hover { background:#b42342; border-color:#9f1239; color:#fff; }
        .kline-chart { height:820px; width:100%; }
        .holdings-panel { margin-top:12px; border:1px solid #e5eaf1; border-radius:8px; background:#fbfcfe; padding:0; }
        .holdings-panel summary { display:flex; justify-content:space-between; gap:10px; align-items:center; cursor:pointer; padding:10px 12px; list-style:none; }
        .holdings-panel summary::-webkit-details-marker { display:none; }
        .holdings-panel summary::before { content:"展开"; color:#2d6cdf; font-weight:900; font-size:12px; margin-right:8px; }
        .holdings-panel[open] summary::before { content:"收起"; }
        .holdings-panel summary strong { font-size:15px; }
        .holdings-panel summary span { color:#657084; font-size:12px; margin-left:auto; text-align:right; }
        .holdings-list { border-top:1px solid #e5eaf1; padding:4px 12px 8px; display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); column-gap:18px; }
        .holding-row { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px; padding:8px 0; border-bottom:1px solid #edf1f6; }
        .holding-row strong { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .holding-row span { display:block; color:#657084; font-size:12px; margin-top:2px; }
        .holding-row em { color:#202631; font-style:normal; font-weight:900; }
        .holding-row small { display:block; color:#657084; font-size:11px; margin-top:2px; text-align:right; }
        .secondary { margin-top:24px; opacity:.96; }
        .panel { margin-top:14px; background:#fff; border:1px solid #d5dde8; border-radius:9px; padding:15px; box-shadow:0 1px 2px rgba(31,41,55,.04); overflow:auto; }
        .grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }
        .panel-head { display:flex; justify-content:space-between; gap:12px; align-items:baseline; margin-bottom:12px; }
        .panel-head span { color:#657084; font-size:12px; }
        table { width:100%; border-collapse:collapse; }
        th { text-align:left; color:#657084; font-size:12px; background:#f7f9fb; }
        th, td { border-bottom:1px solid #e5eaf1; padding:10px 9px; white-space:nowrap; }
        td span { display:block; color:#657084; font-size:12px; margin-top:2px; direction:ltr; unicode-bidi:isolate; }
        .etf-row { cursor:pointer; transition:background .15s ease; }
        .etf-row:hover, .etf-row.active { background:#eef5ff; }
        .up, .buy { color:#c84545; font-weight:900; }
        .down, .sell { color:#15805d; font-weight:900; }
        .hold { color:#657084; font-weight:900; }
        .empty { color:#657084; }
        .rank-list { margin:0; padding-left:20px; color:#202631; line-height:1.9; }
        @media (max-width: 1180px) { .holdings-list { grid-template-columns:repeat(2,minmax(0,1fr)); } }
        @media (max-width: 980px) { header, .grid { grid-template-columns:1fr; display:grid; } nav { justify-content:flex-start; } .kline-chart { height:600px; } .holdings-list { grid-template-columns:1fr; } }
        """,
        body=body,
        head_extra=_echarts_script_tag(),
        scripts=inline_script(
            "window._ETF_KLINES="
            + to_compact_json(kline_payload)
            + """;
(function(){
var root=window._ETF_KLINES||{},chart=null;
var C={up:'#c84545',down:'#15805d',blue:'#2d6cdf',teal:'#00a7a7',purple:'#7357c8',orange:'#a56a18',gray:'#8793a7',line:'#d5dde8',split:'#edf1f6',axis:'#657084',ink:'#202631'};
function fmtAmount(v){var n=Number(v);if(!isFinite(n))return'--';if(Math.abs(n)>=1e8)return(n/1e8).toFixed(2)+'亿';if(Math.abs(n)>=1e4)return(n/1e4).toFixed(0)+'万';return n.toFixed(0);}
function esc(v){return String(v==null?'':v).replace(/[&<>"']/g,function(ch){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch];});}
function zoomStart(item){var n=(item&&item.dates?item.dates.length:0);if(n<=260)return 0;return Math.max(0,Math.round((n-252)/n*100));}
function barData(item,field){var values=(item&&item[field])||[],ohlc=(item&&item.ohlc)||[];return values.map(function(v,i){var o=ohlc[i]||[],open=Number(o[0]),close=Number(o[1]);var color=close>open?C.up:(close<open?C.down:'#b9c3d1');return{value:v,itemStyle:{color:color,opacity:.68}};});}
function initChart(){var el=document.getElementById('etf-kline-chart');if(!el||typeof echarts==='undefined')return null;if(!chart)chart=echarts.init(el,null,{renderer:'canvas'});return chart;}
function option(item){var zs=zoomStart(item);return{animation:false,tooltip:{trigger:'axis',axisPointer:{type:'cross'},formatter:function(params){var i=params&&params[0]?params[0].dataIndex:0;var o=(item.ohlc||[])[i]||[];return item.dates[i]+'<br/>开 '+o[0]+' 收 '+o[1]+'<br/>低 '+o[2]+' 高 '+o[3]+'<br/>MA5 '+((item.ma5||[])[i]||'--')+' / MA10 '+((item.ma10||[])[i]||'--')+' / MA20 '+((item.ma20||[])[i]||'--')+' / MA60 '+((item.ma60||[])[i]||'--')+'<br/>BOLL '+((item.boll_lower||[])[i]||'--')+' / '+((item.boll_mid||[])[i]||'--')+' / '+((item.boll_upper||[])[i]||'--')+'<br/>成交量 '+fmtAmount((item.volume||[])[i])+'<br/>成交额 '+fmtAmount((item.amount||[])[i]);}},legend:{top:8,data:['K线','MA5','MA10','MA20','MA60','BOLL上轨','BOLL中轨','BOLL下轨','成交量','成交额']},grid:[{left:58,right:52,top:54,height:'54%'},{left:58,right:52,top:'70%',height:'11%'},{left:58,right:52,top:'85%',height:'9%'}],xAxis:[{type:'category',data:item.dates,axisLabel:{color:C.axis,fontSize:10},axisLine:{lineStyle:{color:C.line}},splitLine:{show:true,lineStyle:{type:'dashed',color:C.split}}},{type:'category',gridIndex:1,data:item.dates,axisLabel:{show:false},axisLine:{lineStyle:{color:C.line}}},{type:'category',gridIndex:2,data:item.dates,axisLabel:{color:C.axis,fontSize:10,rotate:25},axisLine:{lineStyle:{color:C.line}}}],yAxis:[{scale:true,axisLabel:{color:C.axis},splitLine:{show:true,lineStyle:{type:'dashed',color:C.split}}},{gridIndex:1,scale:true,name:'成交量',axisLabel:{color:C.axis,formatter:fmtAmount},splitLine:{show:true,lineStyle:{type:'dashed',color:C.split}}},{gridIndex:2,scale:true,name:'成交额',axisLabel:{color:C.axis,formatter:fmtAmount},splitLine:{show:true,lineStyle:{type:'dashed',color:C.split}}}],dataZoom:[{type:'inside',xAxisIndex:[0,1,2],start:zs,end:100},{type:'slider',xAxisIndex:[0,1,2],start:zs,end:100,height:18,bottom:0}],series:[{name:'K线',type:'candlestick',data:item.ohlc,itemStyle:{color:C.up,color0:C.down,borderColor:C.up,borderColor0:C.down}},{name:'MA5',type:'line',data:item.ma5,symbol:'none',lineStyle:{color:C.teal,width:1.2}},{name:'MA10',type:'line',data:item.ma10,symbol:'none',lineStyle:{color:C.purple,width:1.2}},{name:'MA20',type:'line',data:item.ma20,symbol:'none',lineStyle:{color:C.blue,width:1.5}},{name:'MA60',type:'line',data:item.ma60,symbol:'none',lineStyle:{color:C.orange,width:1.5}},{name:'BOLL上轨',type:'line',data:item.boll_upper,symbol:'none',lineStyle:{color:'#bd9b47',width:1,type:'dashed'}},{name:'BOLL中轨',type:'line',data:item.boll_mid,symbol:'none',lineStyle:{color:C.gray,width:1,type:'dotted'}},{name:'BOLL下轨',type:'line',data:item.boll_lower,symbol:'none',lineStyle:{color:'#bd9b47',width:1,type:'dashed'}},{name:'成交量',type:'bar',xAxisIndex:1,yAxisIndex:1,data:barData(item,'volume')},{name:'成交额',type:'bar',xAxisIndex:2,yAxisIndex:2,data:barData(item,'amount')}]};}
var etfDraw={tool:null,pending:null,dragging:false};
var drawLabel={trend:'趋势线',support:'支撑线',resistance:'阻力线'};
var drawColor={trend:'#2563eb',support:'#16a34a',resistance:'#dc2626'};
function drawStatus(text){var el=document.getElementById('etf-drawing-status');if(el)el.textContent=text||'选择工具后在 K 线主图点击画线。';}
function setEtfDrawTool(tool){etfDraw.tool=tool||null;etfDraw.pending=null;var activeTool=etfDraw.tool||'select';document.querySelectorAll('.drawing-btn[data-draw-tool]').forEach(function(btn){btn.classList.toggle('active',btn.getAttribute('data-draw-tool')===activeTool);});if(!etfDraw.tool)drawStatus('选择/调整：拖动圆点调整线条。');else if(etfDraw.tool==='trend')drawStatus('趋势线：在 K 线主图依次点击两个点。');else drawStatus(drawLabel[etfDraw.tool]+'：在 K 线主图点击一个价位。');}
function drawStorageKey(c){return 'quantyb.etf-manual-draw.v1.'+(c&&c._etfDrawSymbol?c._etfDrawSymbol:'');}
function loadDrawLines(c){if(!c)return[];if(c._etfDrawLines)return c._etfDrawLines;try{c._etfDrawLines=JSON.parse(localStorage.getItem(drawStorageKey(c))||'[]')||[];}catch(e){c._etfDrawLines=[];}return c._etfDrawLines;}
function saveDrawLines(c){try{localStorage.setItem(drawStorageKey(c),JSON.stringify(c._etfDrawLines||[]));}catch(e){}}
function drawPointFromPixel(c,pixel){var coord=c.convertFromPixel({gridIndex:0},pixel);if(!coord||coord.length<2)return null;var dates=c._etfDrawDates||[],rawX=coord[0],idx=typeof rawX==='number'?Math.round(rawX):dates.indexOf(String(rawX));if(!dates.length)return null;if(idx<0)idx=0;if(idx>=dates.length)idx=dates.length-1;var price=Number(coord[1]);if(!isFinite(price))return null;return{index:idx,date:dates[idx],price:Number(price.toFixed(4))};}
function drawPointFromEvent(c,ev){return drawPointFromPixel(c,[ev.offsetX,ev.offsetY]);}
function drawPixelFromPoint(c,point){if(!c||!point||point.date==null||point.price==null)return null;var pixel=c.convertToPixel({gridIndex:0},[point.date,Number(point.price)]);if(!pixel||pixel.length<2||!isFinite(pixel[0])||!isFinite(pixel[1]))return null;return[Number(pixel[0]),Number(pixel[1])];}
function drawRightEdgeDate(c){var dates=c._etfDrawDates||[];if(!dates.length)return'';try{var opt=c.getOption()||{},dz=(opt.dataZoom||[])[0]||{},idx=dates.length-1;if(dz.endValue!=null){if(typeof dz.endValue==='number')idx=Math.round(dz.endValue);else{var found=dates.indexOf(String(dz.endValue));if(found>=0)idx=found;}}else if(dz.end!=null){idx=Math.round((Number(dz.end)||100)/100*(dates.length-1));}if(idx<0)idx=0;if(idx>=dates.length)idx=dates.length-1;return dates[idx];}catch(e){return dates[dates.length-1];}}
function drawSeries(line,c){var dates=c._etfDrawDates||[],color=drawColor[line.type]||drawColor.trend,label=drawLabel[line.type]||'手动画线';if(line.type==='trend'){var p1=line.p1||{},p2=line.p2||{},i1=Number(p1.index),i2=Number(p2.index),y1=Number(p1.price),y2=Number(p2.price),data=[];if(!isFinite(i1)||!isFinite(i2)||!isFinite(y1)||!isFinite(y2)||i1===i2){data=[[p1.date,y1],[p2.date,y2]];}else{var slope=(y2-y1)/(i2-i1),startIndex=Math.min(i1,i2);data=dates.map(function(date,idx){return idx<startIndex?[date,null]:[date,Number((y1+slope*(idx-i1)).toFixed(4))];});}return{id:'etf-draw-'+line.id,name:label,type:'line',data:data,symbol:'circle',symbolSize:6,z:40,silent:false,clip:false,lineStyle:{color:color,width:2.2,type:'solid',opacity:.98},endLabel:{show:true,formatter:function(p){var v=p&&p.value?p.value[1]:null;return label+(v==null?'':' '+Number(v).toFixed(3));},color:color,fontSize:11,fontWeight:'bold'},tooltip:{formatter:function(){return label+'<br/>'+p1.date+' '+p1.price+' → '+p2.date+' '+p2.price;}}};}var price=Number(line.price),lineType=line.type==='trend'?'solid':'dashed';return{id:'etf-draw-'+line.id,name:label,type:'line',data:dates.map(function(date){return[date,price];}),symbol:'none',z:38,silent:false,clip:false,lineStyle:{color:color,width:2.4,type:lineType,opacity:.98},endLabel:{show:true,formatter:function(){return label+' '+price.toFixed(3);},color:color,fontSize:11,fontWeight:'bold',distance:8},markLine:{silent:false,symbol:'none',precision:4,label:{show:false},lineStyle:{color:color,width:2.4,type:lineType,opacity:.98},data:[{yAxis:price}]},tooltip:{formatter:function(){return label+'<br/>价位: '+price.toFixed(4);}}};}
function drawSeriesList(c){return loadDrawLines(c).map(function(line){return drawSeries(line,c);});}
function renderDrawSeriesOnly(c){if(!c||!c._etfBaseSeries)return;c.setOption({series:(c._etfBaseSeries||[]).concat(drawSeriesList(c))},{replaceMerge:['series']});}
function updateTrendPoint(c,id,which,pixel){var point=drawPointFromPixel(c,pixel);if(!point)return false;var changed=false,lines=loadDrawLines(c);lines.forEach(function(line){if(line.id===id&&line.type==='trend'){line[which]=point;changed=true;}});if(changed){c._etfDrawLines=lines;saveDrawLines(c);renderDrawSeriesOnly(c);}return changed;}
function updateHorizontalPrice(c,id,pixel){var coord=c.convertFromPixel({gridIndex:0},pixel);if(!coord||coord.length<2||!isFinite(Number(coord[1])))return false;var price=Number(Number(coord[1]).toFixed(4)),changed=false,lines=loadDrawLines(c);lines.forEach(function(line){if(line.id===id&&(line.type==='support'||line.type==='resistance')){line.price=price;changed=true;}});if(changed){c._etfDrawLines=lines;saveDrawLines(c);renderDrawSeriesOnly(c);}return changed;}
function handleStyle(color){return{fill:color,stroke:'#fff',lineWidth:2,shadowBlur:8,shadowColor:'rgba(15,23,42,.18)'};}
function handleTooltip(text){return{show:true,formatter:text,backgroundColor:'rgba(15,23,42,.9)',borderWidth:0,textStyle:{color:'#fff',fontSize:12}};}
function trendHandle(c,line,which,point,label,color){var pos=drawPixelFromPoint(c,point);if(!pos)return null;return{id:'etf-draw-handle-'+line.id+'-'+which,type:'circle',position:pos,shape:{r:7},draggable:true,cursor:'move',z:120,style:handleStyle(color),tooltip:handleTooltip(label+'：拖动调整位置'),ondragstart:function(){etfDraw.dragging=true;},ondrag:function(){updateTrendPoint(c,line.id,which,this.position);},ondragend:function(){updateTrendPoint(c,line.id,which,this.position);renderDrawLines(c);setTimeout(function(){etfDraw.dragging=false;},0);},onclick:function(){etfDraw.dragging=true;setTimeout(function(){etfDraw.dragging=false;},0);}};}
function horizontalHandle(c,line,label,color){var pos=drawPixelFromPoint(c,{date:drawRightEdgeDate(c),price:line.price});if(!pos)return null;return{id:'etf-draw-handle-'+line.id+'-price',type:'circle',position:pos,shape:{r:7},draggable:true,cursor:'ns-resize',z:120,style:handleStyle(color),tooltip:handleTooltip(label+'：上下拖动调整价位'),ondragstart:function(){etfDraw.dragging=true;},ondrag:function(){updateHorizontalPrice(c,line.id,this.position);},ondragend:function(){updateHorizontalPrice(c,line.id,this.position);renderDrawLines(c);setTimeout(function(){etfDraw.dragging=false;},0);},onclick:function(){etfDraw.dragging=true;setTimeout(function(){etfDraw.dragging=false;},0);}};}
function drawGraphics(c){var graphics=[];loadDrawLines(c).forEach(function(line){var color=drawColor[line.type]||drawColor.trend,label=drawLabel[line.type]||'手动画线';if(line.type==='trend'){var p1=trendHandle(c,line,'p1',line.p1,label+'起点',color),p2=trendHandle(c,line,'p2',line.p2,label+'终点',color);if(p1)graphics.push(p1);if(p2)graphics.push(p2);}else if(line.type==='support'||line.type==='resistance'){var h=horizontalHandle(c,line,label,color);if(h)graphics.push(h);}});return graphics;}
function renderDrawLines(c){if(!c||!c._etfBaseSeries)return;c.setOption({series:(c._etfBaseSeries||[]).concat(drawSeriesList(c)),graphic:drawGraphics(c)},{replaceMerge:['series','graphic']});}
function addDrawLine(c,line){var lines=loadDrawLines(c);lines.push(line);c._etfDrawLines=lines;saveDrawLines(c);renderDrawLines(c);}
function bindEtfDrawing(c,item){c._etfDrawSymbol=item.symbol||'';c._etfDrawDates=item.dates||[];c._etfBaseSeries=(c.getOption().series||[]).map(function(s){return s;});c._etfDrawLines=null;renderDrawLines(c);if(!c._etfDrawingBound){c._etfDrawingBound=true;c.on('dataZoom',function(){setTimeout(function(){renderDrawLines(c);},0);});c.getZr().on('click',function(ev){if(!etfDraw.tool||etfDraw.dragging)return;var point=drawPointFromEvent(c,ev);if(!point)return;var id=Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,7);if(etfDraw.tool==='trend'){if(!etfDraw.pending){etfDraw.pending=point;drawStatus('趋势线：已选 '+point.date+' / '+point.price+'，再点第二个点。');return;}addDrawLine(c,{id:id,type:'trend',p1:etfDraw.pending,p2:point});etfDraw.pending=null;drawStatus('趋势线已添加，可拖动两个圆点微调。');}else if(etfDraw.tool==='support'||etfDraw.tool==='resistance'){addDrawLine(c,{id:id,type:etfDraw.tool,price:point.price,date:point.date});drawStatus(drawLabel[etfDraw.tool]+'已添加：'+point.price+'。');}});}}
function etfDrawUndo(){var c=chart;if(!c)return;var lines=loadDrawLines(c);lines.pop();c._etfDrawLines=lines;saveDrawLines(c);renderDrawLines(c);drawStatus('已撤销当前 ETF 最后一条线。');}
function etfDrawClear(){var c=chart;if(!c)return;if(!confirm('清空当前 ETF 的全部手动画线？'))return;c._etfDrawLines=[];saveDrawLines(c);renderDrawLines(c);drawStatus('当前 ETF 手动画线已清空。');}
window.setEtfDrawTool=setEtfDrawTool;window.etfDrawUndo=etfDrawUndo;window.etfDrawClear=etfDrawClear;
setEtfDrawTool(null);
function renderHoldings(item){var el=document.getElementById('etf-holdings-list'),note=document.getElementById('etf-holdings-note');if(!el)return;var rows=(item&&item.holdings)||[];var period=rows.length&&rows[0].end_date?rows[0].end_date:'';if(note)note.textContent=rows.length?('报告期 '+period+' · 前 '+rows.length+' 条'):'读取 Tushare fund_portfolio / 本地缓存';if(!rows.length){el.innerHTML='<p class="empty">暂无持仓明细缓存<br/><span>可由 Tushare fund_portfolio 自动缓存，或在 etf_strategy.holdings_dir 放入 '+esc(item?item.symbol:'ETF代码')+'.csv</span></p>';return;}el.innerHTML=rows.map(function(row){var name=row.name||'--',code=row.code||'',weight=row.weight||'--',mkv=fmtAmount(row.mkv),amount=fmtAmount(row.amount);return '<div class="holding-row"><div><strong>'+esc(name)+'</strong><span>'+esc(code)+' · 市值 '+esc(mkv)+' · 股数 '+esc(amount)+'</span></div><div><em>'+esc(weight)+'</em><small>估算占比</small></div></div>';}).join('');}
function show(symbol){var item=root[symbol],c=initChart();if(!item||!c)return;var adj=item.adjust==='qfq'?'前复权日K':'日K';document.getElementById('etf-chart-name').textContent=item.name+' '+item.symbol;document.getElementById('etf-chart-meta').textContent=item.category+' / '+item.subcategory+' · '+adj+' / MA5/10/20/60 / 布林线 / 成交量 / 成交额';document.querySelectorAll('.etf-row').forEach(function(row){row.classList.toggle('active',row.getAttribute('data-symbol')===symbol);});document.querySelectorAll('.mini-etf-chip').forEach(function(chip){chip.classList.toggle('active',chip.getAttribute('data-symbol')===symbol);});renderHoldings(item);c.setOption(option(item),true);bindEtfDrawing(c,item);}
function switchCategory(category){document.querySelectorAll('.category-tab').forEach(function(tab){tab.classList.toggle('active',tab.getAttribute('data-category')===category);});document.querySelectorAll('.category-pane').forEach(function(pane){pane.classList.toggle('active',pane.getAttribute('data-category')===category);});var first=document.querySelector('.category-pane.active .etf-row');if(first)show(first.getAttribute('data-symbol'));if(chart)setTimeout(function(){chart.resize();},0);}
window.showEtfKline=show;
window.switchEtfCategory=switchCategory;
document.querySelectorAll('.category-tab').forEach(function(tab){tab.addEventListener('click',function(){switchCategory(tab.getAttribute('data-category'));});});
document.querySelectorAll('.etf-row').forEach(function(row){row.addEventListener('click',function(){show(row.getAttribute('data-symbol'));});});
document.querySelectorAll('.mini-etf-chip').forEach(function(chip){chip.addEventListener('click',function(){show(chip.getAttribute('data-symbol'));});});
var firstTab=document.querySelector('.category-tab');if(firstTab)switchCategory(firstTab.getAttribute('data-category'));else{var first=document.querySelector('.etf-row');if(first)show(first.getAttribute('data-symbol'));}window.addEventListener('resize',function(){if(chart)chart.resize();});
})();"""
        ),
    )
    output.write_text(html_text, encoding="utf-8")
    return output
