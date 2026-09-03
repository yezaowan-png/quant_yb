"""Static ECharts report for sector money-flow monitoring."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from analysis.sector_money_flow import (
    SectorMoneyFlowConfig,
    SectorMoneyFlowState,
    state_to_payload,
)
from visual.components import html_document, inline_script, json_script_data, script_src


def generate_sector_money_flow_report(
    state: SectorMoneyFlowState,
    settings: SectorMoneyFlowConfig,
    output_path: str | Path,
) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    _ensure_echarts_asset(target.parent)
    payload = state_to_payload(state, settings)
    target.write_text(_build_html(payload), encoding="utf-8")
    return target


def _ensure_echarts_asset(reports_dir: Path) -> None:
    source = Path(__file__).parent / "assets" / "echarts.min.js"
    if not source.exists():
        return
    target = reports_dir / "assets" / "echarts.min.js"
    if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())


def _echarts_tag() -> str:
    return script_src("assets/echarts.min.js")


def _build_html(data: dict[str, Any]) -> str:
    mode_text = "历史回放" if data.get("mode") == "history_replay" else "实时监控"
    refresh = ""
    if data.get("mode") == "realtime" and data.get("report_auto_refresh"):
        refresh = (
            '<span class="chip">页面自动刷新 '
            f'{html.escape(str(data.get("interval_seconds", 60)))}s</span>'
        )
    return html_document(
        "行业板块资金流监控",
        body=f"""
  <main class="page">
    <header class="topbar">
      <div>
        <h1>行业板块资金流监控</h1>
        <p>分钟级采集 · 午休跳过 · 本地 CSV 归档 · 板块净额排序</p>
      </div>
      <div class="meta">
        <span class="chip">{html.escape(mode_text)}</span>
        <span class="chip">快照 {html.escape(str(data.get("data_point_count", 0)))} 个</span>
        {refresh}
        <span>生成: {html.escape(str(data.get("generated_at", "--")))}</span>
      </div>
    </header>

    <section class="layout">
      <div class="chart-panel">
        <div id="flow-chart"></div>
      </div>
      <aside class="rank-panel">
        <div class="rank-head"><span>板块</span><span>净额(亿)</span></div>
        <div id="rank-list"></div>
      </aside>
    </section>

    <section class="controls">
      <button id="play-btn" type="button">播放</button>
      <button id="pause-btn" type="button">暂停</button>
      <button id="reset-btn" type="button">重置</button>
      <span id="status"></span>
    </section>

    <footer>归档目录: {html.escape(str(data.get("archive_dir", "")))}</footer>
  </main>
  """,
        styles=_styles(),
        head_extra='<link rel="icon" href="data:,">' + _echarts_tag(),
        scripts=json_script_data(data, "sector-flow-data") + inline_script(_script()),
    )


def _styles() -> str:
    return """
    :root { --red:#d64545; --green:#178f5b; --ink:#172033; --muted:#647083; --line:#dfe5ee; --bg:#f5f7fb; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,"Noto Sans SC",sans-serif; color:var(--ink); background:var(--bg); }
    .page { width:min(100vw - 32px, 1440px); margin:0 auto; padding:22px 0 18px; }
    .topbar { display:flex; justify-content:space-between; gap:20px; align-items:flex-end; padding:0 2px 16px; }
    h1 { margin:0 0 6px; font-size:28px; letter-spacing:0; }
    p { margin:0; color:var(--muted); font-size:14px; }
    .meta { display:flex; flex-wrap:wrap; gap:10px; align-items:center; justify-content:flex-end; color:var(--muted); font-size:13px; }
    .chip { display:inline-flex; align-items:center; min-height:26px; border:1px solid var(--line); padding:3px 9px; border-radius:6px; background:#fff; color:#263449; }
    .layout { display:grid; grid-template-columns:minmax(0, 1fr) 280px; gap:14px; align-items:stretch; }
    .chart-panel, .rank-panel { background:#fff; border:1px solid var(--line); border-radius:8px; overflow:hidden; }
    #flow-chart { width:100%; height:560px; }
    .rank-panel { min-height:560px; }
    .rank-head, .rank-row { display:grid; grid-template-columns:1fr 90px; align-items:center; gap:8px; }
    .rank-head { padding:12px 14px; border-bottom:1px solid var(--line); color:var(--muted); font-weight:700; font-size:13px; background:#fafbfd; }
    #rank-list { max-height:515px; overflow:auto; }
    .rank-row { padding:9px 14px 9px 11px; border-bottom:1px solid #eef2f7; border-left:3px solid transparent; font-size:14px; }
    .rank-row strong { text-align:right; font-size:14px; }
    .rank-row.positive { border-left-color:var(--red); background:#fff7f7; }
    .rank-row.negative { border-left-color:var(--green); background:#f4fbf7; }
    .rank-row .pos { color:var(--red); }
    .rank-row .neg { color:var(--green); }
    .controls { display:flex; align-items:center; justify-content:center; gap:10px; padding:15px 0 8px; }
    button { border:1px solid #c9d2df; background:#fff; color:#172033; border-radius:6px; min-width:76px; height:34px; font-weight:700; cursor:pointer; }
    button:hover { background:#edf3fb; }
    #status { color:var(--muted); min-width:260px; }
    footer { color:var(--muted); font-size:12px; padding:8px 2px 0; }
    @media (max-width: 860px) {
      .page { width:min(100vw - 20px, 1440px); }
      .topbar { display:block; }
      .meta { justify-content:flex-start; margin-top:10px; }
      .layout { grid-template-columns:1fr; }
      #flow-chart { height:440px; }
      .rank-panel { min-height:0; }
    }
    """


def _script() -> str:
    return r"""
    (function(){
      var payload = JSON.parse(document.getElementById('sector-flow-data').textContent || '{}');
      var chartEl = document.getElementById('flow-chart');
      var chart = echarts.init(chartEl);
      var timer = null;
      var current = Number(payload.current_idx || 0);
      var maxIdx = Number(payload.max_data_idx || 0);
      var timestamps = payload.timestamps || [];
      var snapshotTimes = payload.snapshot_timestamps || [];
      var sectors = payload.sector_names || [];
      var seriesData = payload.series || {};
      var snapshotSeries = payload.snapshot_series || {};
      var dataIndices = (payload.data_indices || []).map(function(value){ return Number(value); }).filter(function(value){ return !Number.isNaN(value); });
      if (!dataIndices.length && timestamps.length) dataIndices = [Math.max(0, Math.min(maxIdx, timestamps.length - 1))];
      if (!snapshotTimes.length) snapshotTimes = dataIndices.map(function(idx){ return timestamps[idx] || ''; });
      var playPos = 0;
      var colors = ['#d64545','#2563eb','#f59e0b','#16a34a','#7c3aed','#0891b2','#db2777','#4f46e5','#84cc16','#6b7280'];

      function latestValue(values, idx) {
        for (var i=Math.min(idx, values.length - 1); i>=0; i--) {
          if (values[i] !== null && values[i] !== undefined) return Number(values[i]);
        }
        return 0;
      }
      function rankRows(idx) {
        return sectors.map(function(sector){
          return { sector: sector, value: latestValue(seriesData[sector] || [], idx) };
        }).sort(function(a,b){ return b.value - a.value; });
      }
      function renderRank(idx) {
        var list = document.getElementById('rank-list');
        list.innerHTML = rankRows(idx).map(function(item){
          var positive = item.value > 0;
          var cls = positive ? 'positive' : 'negative';
          var numCls = positive ? 'pos' : 'neg';
          var sign = item.value > 0 ? '+' : '';
          return '<div class="rank-row '+cls+'"><span>'+escapeHtml(item.sector)+'</span><strong class="'+numCls+'">'+sign+item.value.toFixed(2)+'</strong></div>';
        }).join('');
      }
      function renderChart(idx) {
        var limit = Math.max(0, Math.min(idx, timestamps.length - 1));
        var pointLimit = Math.max(0, dataIndices.filter(function(item){ return item <= limit; }).length - 1);
        var visibleTimes = snapshotTimes.slice(0, pointLimit + 1);
        var option = {
          color: colors,
          tooltip: { trigger: 'axis' },
          legend: { top: 6, type: 'scroll' },
          grid: { left: 56, right: 22, top: 64, bottom: 42 },
          xAxis: { type: 'category', boundaryGap: false, data: visibleTimes },
          yAxis: { type: 'value', name: '净额(亿)', splitLine: { lineStyle: { color: '#eef2f7' } } },
          series: sectors.map(function(sector){
            var values = (snapshotSeries[sector] || []).slice(0, pointLimit + 1);
            return { name: sector, type: 'line', showSymbol: true, symbolSize: 6, connectNulls: false, data: values };
          })
        };
        chart.setOption(option, true);
        var visiblePoint = pointLimit + 1;
        document.getElementById('status').textContent = '快照: ' + visiblePoint + '/' + dataIndices.length + ' · 当前: ' + (snapshotTimes[pointLimit] || timestamps[limit] || '--') + ' · 仅显示已采集快照';
        renderRank(limit);
      }
      function setStatusHint(text) {
        document.getElementById('status').textContent = text;
      }
      function escapeHtml(text) {
        return String(text).replace(/[&<>"']/g, function(ch){
          return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]);
        });
      }
      function play() {
        pause();
        if (dataIndices.length <= 1) {
          renderChart(dataIndices[0] || current);
          setStatusHint('只有 1 个归档数据点，请继续采集或运行 watch 积累多个分钟快照后刷新。');
          return;
        }
        if (current >= dataIndices[dataIndices.length - 1]) current = dataIndices[0];
        playPos = dataIndices.findIndex(function(item){ return item > current; });
        if (playPos < 0) playPos = 0;
        timer = window.setInterval(function(){
          if (playPos < dataIndices.length) {
            current = dataIndices[playPos];
            playPos += 1;
            renderChart(current);
          } else {
            pause();
          }
        }, 500);
      }
      function pause() {
        if (timer) window.clearInterval(timer);
        timer = null;
      }
      document.getElementById('play-btn').addEventListener('click', play);
      document.getElementById('pause-btn').addEventListener('click', pause);
      document.getElementById('reset-btn').addEventListener('click', function(){ pause(); current = 0; renderChart(current); });
      window.addEventListener('resize', function(){ chart.resize(); });
      renderChart(dataIndices[0] || Math.min(current, maxIdx));
      if (payload.mode === 'realtime' && payload.report_auto_refresh) {
        window.setTimeout(function(){ window.location.reload(); }, Math.max(5, Number(payload.interval_seconds || 60)) * 1000);
      }
    })();
    """
