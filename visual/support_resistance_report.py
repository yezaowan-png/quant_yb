"""Interactive ECharts report for support/resistance resonance analysis."""

from __future__ import annotations

import html
from pathlib import Path

from analysis.support_resistance import FIBONACCI_RATIOS, SupportResistanceResult
from visual.components import html_document, json_script_data, script_src


FIB_COLORS = {
    "0.236": "#b8860b",
    "0.382": "#d97706",
    "0.500": "#b45309",
    "0.618": "#15803d",
    "0.786": "#7e22ce",
}


def _ensure_echarts_asset(output_dir: Path) -> str:
    source = Path(__file__).parent / "assets" / "echarts.min.js"
    target = output_dir / "assets" / "echarts.min.js"
    if source.exists() and (not target.exists() or target.stat().st_mtime < source.stat().st_mtime):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    return "assets/echarts.min.js"


def _round(value: object, digits: int = 4) -> float:
    return round(float(value), digits)


def _chart_payload(result: SupportResistanceResult) -> dict:
    frame = result.data
    dates = [value.strftime("%Y-%m-%d") for value in frame.index]
    moving_averages = []
    for period in result.settings.ma_periods:
        name = f"MA{period}"
        if name not in frame.columns:
            continue
        moving_averages.append(
            {
                "name": name,
                "values": [None if value != value else _round(value) for value in frame[name].tolist()],
            }
        )

    fib_lines = [
        {
            "name": f"Fib {key}",
            "value": _round(result.fibonacci_levels[key]),
            "color": FIB_COLORS[key],
        }
        for key, _ in FIBONACCI_RATIOS
    ]
    fib_lines.extend(
        [
            {"name": "区间高点", "value": _round(result.fibonacci_levels["high"]), "color": "#dc2626"},
            {"name": "区间低点", "value": _round(result.fibonacci_levels["low"]), "color": "#16a34a"},
            {"name": "当前价", "value": _round(frame["close"].iloc[-1]), "color": "#111827"},
        ]
    )
    zones = [
        {
            "name": f"{zone['ma']} ≈ Fib {zone['fib']}",
            "lower": _round(zone["lower"]),
            "upper": _round(zone["upper"]),
        }
        for zone in result.resonance_zones
    ]
    return {
        "dates": dates,
        "candles": [
            [_round(row.open), _round(row.close), _round(row.low), _round(row.high)]
            for row in frame[["open", "close", "low", "high"]].itertuples(index=False)
        ],
        "movingAverages": moving_averages,
        "fibLines": fib_lines,
        "zones": zones,
        "highPoint": [result.fibonacci_levels["high_date"].strftime("%Y-%m-%d"), _round(result.fibonacci_levels["high"])],
        "lowPoint": [result.fibonacci_levels["low_date"].strftime("%Y-%m-%d"), _round(result.fibonacci_levels["low"])],
    }


def _resonance_table(result: SupportResistanceResult) -> str:
    if not result.resonance_zones:
        return '<p class="empty">当前区间没有满足阈值的共振区域。</p>'
    rows = []
    for zone in result.resonance_zones:
        tone = "support" if zone["reference_type"] == "支撑" else "pressure" if zone["reference_type"] == "压力" else "near"
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(zone['ma']))}</td>"
            f"<td>{float(zone['ma_value']):.2f}</td>"
            f"<td>Fib {html.escape(str(zone['fib']))}</td>"
            f"<td>{float(zone['fib_value']):.2f}</td>"
            f"<td>{float(zone['diff_pct']):.2f}%</td>"
            f"<td><span class='zone-tag {tone}'>{html.escape(str(zone['reference_type']))}</span></td>"
            "</tr>"
        )
    return f"""
    <div class="table-wrap"><table>
      <thead><tr><th>均线</th><th>均线价</th><th>黄金分割</th><th>分割价</th><th>偏差</th><th>位置属性</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table></div>
    """


def build_support_resistance_report(result: SupportResistanceResult, output_path: str | Path) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    asset_href = _ensure_echarts_asset(output.parent)
    title_name = result.stock_name or result.symbol
    fib = result.fibonacci_levels
    adjust_label = {"qfq": "前复权", "hfq": "后复权", "": "不复权"}[result.settings.adjust]
    report_items = "".join(f"<li>{html.escape(line)}</li>" for line in result.report_lines)
    payload = _chart_payload(result)

    body = f"""
    <main>
      <header>
        <div>
          <p class="eyebrow">股票技术结构</p>
          <h1>{html.escape(title_name)} <span>{html.escape(result.symbol)}</span></h1>
          <p class="subtitle">均线与斐波那契黄金分割共振分析</p>
        </div>
        <div class="status">{html.escape(str(fib['trend_dir']))}区间</div>
      </header>

      <section class="metrics">
        <div><span>数据区间</span><strong>{result.start_date} - {result.end_date}</strong></div>
        <div><span>当前价</span><strong>{float(result.data['close'].iloc[-1]):.2f}</strong></div>
        <div><span>区间高 / 低</span><strong>{float(fib['high']):.2f} / {float(fib['low']):.2f}</strong></div>
        <div><span>共振组数</span><strong>{len(result.resonance_zones)}</strong></div>
      </section>

      <section class="chart-section">
        <div class="section-head">
          <div><h2>K 线与关键价位</h2><p>{adjust_label} · MA {' / '.join(str(item) for item in result.settings.ma_periods)} · 共振偏差 &lt; {result.settings.resonance_threshold_pct:g}%</p></div>
        </div>
        <div id="support-resistance-chart" role="img" aria-label="股票支撑压力共振K线图"></div>
      </section>

      <section class="analysis-grid">
        <article>
          <h2>文字分析</h2>
          <ol>{report_items}</ol>
        </article>
        <article>
          <h2>黄金分割价位</h2>
          <dl>
            {''.join(f'<div><dt>{key}</dt><dd>{float(fib[key]):.2f}</dd></div>' for key, _ in FIBONACCI_RATIOS)}
          </dl>
        </article>
      </section>

      <section class="resonance-section">
        <div class="section-head"><div><h2>共振区域</h2><p>均线价与黄金分割价的偏差按均线价为分母计算</p></div></div>
        {_resonance_table(result)}
      </section>
      <footer>本报告是技术结构观察结果，不构成买卖建议。</footer>
    </main>
    """

    styles = """
    :root { --ink:#172033; --muted:#667085; --line:#d8dee9; --panel:#ffffff; --bg:#f4f7fb; --red:#dc2626; --green:#15803d; --blue:#2563eb; }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--bg); color:var(--ink); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif; letter-spacing:0; }
    main { width:min(1500px,calc(100% - 40px)); margin:0 auto; padding:32px 0 28px; }
    header { display:flex; align-items:flex-start; justify-content:space-between; gap:24px; margin-bottom:22px; }
    .eyebrow { margin:0 0 8px; color:var(--blue); font-size:13px; font-weight:700; }
    h1 { margin:0; font-size:32px; line-height:1.25; }
    h1 span { color:var(--muted); font-size:18px; font-weight:600; }
    .subtitle { margin:8px 0 0; color:var(--muted); }
    .status { padding:8px 12px; border:1px solid var(--line); border-radius:6px; background:var(--panel); font-weight:700; white-space:nowrap; }
    .metrics { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); border:1px solid var(--line); background:var(--panel); margin-bottom:18px; }
    .metrics div { min-width:0; padding:16px 18px; border-right:1px solid var(--line); }
    .metrics div:last-child { border-right:0; }
    .metrics span { display:block; color:var(--muted); font-size:13px; margin-bottom:7px; }
    .metrics strong { display:block; font-size:18px; overflow-wrap:anywhere; }
    .chart-section,.analysis-grid article,.resonance-section { background:var(--panel); border:1px solid var(--line); border-radius:6px; }
    .chart-section,.resonance-section { padding:20px; margin-bottom:18px; }
    .section-head { display:flex; align-items:flex-start; justify-content:space-between; gap:20px; }
    h2 { margin:0; font-size:20px; }
    .section-head p { margin:6px 0 0; color:var(--muted); font-size:13px; }
    #support-resistance-chart { width:100%; height:680px; margin-top:8px; }
    .analysis-grid { display:grid; grid-template-columns:1.7fr 1fr; gap:18px; margin-bottom:18px; }
    .analysis-grid article { padding:20px; }
    ol { margin:16px 0 0; padding-left:22px; }
    li { margin:10px 0; line-height:1.65; }
    dl { margin:14px 0 0; }
    dl div { display:flex; justify-content:space-between; gap:20px; padding:10px 0; border-bottom:1px solid #edf0f5; }
    dt { color:var(--muted); }
    dd { margin:0; font-weight:700; }
    .table-wrap { overflow-x:auto; margin-top:15px; }
    table { width:100%; border-collapse:collapse; min-width:720px; }
    th,td { padding:12px 14px; border-bottom:1px solid #e7ebf1; text-align:right; white-space:nowrap; }
    th:first-child,td:first-child { text-align:left; }
    th { color:var(--muted); font-size:12px; background:#f8fafc; }
    .zone-tag { display:inline-block; padding:4px 8px; border-radius:4px; font-size:12px; font-weight:700; }
    .zone-tag.support { color:#166534; background:#dcfce7; }
    .zone-tag.pressure { color:#991b1b; background:#fee2e2; }
    .zone-tag.near { color:#1e40af; background:#dbeafe; }
    .empty { color:var(--muted); margin:18px 0 4px; }
    footer { color:var(--muted); font-size:12px; text-align:center; padding:8px 0; }
    @media (max-width:900px) { main { width:min(100% - 24px,1500px); padding-top:20px; } .metrics { grid-template-columns:repeat(2,minmax(0,1fr)); } .metrics div:nth-child(2) { border-right:0; } .metrics div:nth-child(-n+2) { border-bottom:1px solid var(--line); } .analysis-grid { grid-template-columns:1fr; } #support-resistance-chart { height:540px; } }
    @media (max-width:560px) { header { display:block; } .status { display:inline-block; margin-top:14px; } h1 { font-size:26px; } .metrics { grid-template-columns:1fr; } .metrics div { border-right:0; border-bottom:1px solid var(--line); } .metrics div:last-child { border-bottom:0; } #support-resistance-chart { height:460px; } }
    """

    scripts = json_script_data(payload, "support-resistance-data") + """
    <script>
    (function(){
      const root=document.getElementById('support-resistance-chart');
      const data=JSON.parse(document.getElementById('support-resistance-data').textContent);
      if(!root||!window.echarts){ if(root) root.textContent='图表组件未加载'; return; }
      const chart=echarts.init(root);
      const maColors=['#ea580c','#2563eb','#7e22ce','#0891b2','#4f46e5'];
      const markLines=data.fibLines.map(function(item){return {name:item.name,yAxis:item.value,lineStyle:{color:item.color,width:item.name==='当前价'?1.8:1.1,type:item.name==='当前价'?'solid':'dashed'},label:{formatter:item.name+'  '+item.value,position:'insideEndTop',color:item.color}};});
      const markAreas=data.zones.map(function(item){return [{name:item.name,yAxis:item.lower,itemStyle:{color:'rgba(245, 158, 11, 0.14)'},label:{show:true,color:'#92400e',fontSize:11}}, {yAxis:item.upper}];});
      const series=[{
        name:'日K',type:'candlestick',data:data.candles,itemStyle:{color:'#dc2626',color0:'#16a34a',borderColor:'#dc2626',borderColor0:'#16a34a'},
        markLine:{symbol:['none','none'],silent:true,data:markLines},markArea:{silent:true,data:markAreas},
        markPoint:{symbolSize:50,data:[{name:'高点',coord:data.highPoint,value:data.highPoint[1],itemStyle:{color:'#dc2626'}},{name:'低点',coord:data.lowPoint,value:data.lowPoint[1],itemStyle:{color:'#16a34a'}}]}
      }];
      data.movingAverages.forEach(function(item,index){series.push({name:item.name,type:'line',data:item.values,showSymbol:false,smooth:false,connectNulls:false,lineStyle:{width:1.7,color:maColors[index%maColors.length]},emphasis:{focus:'series'}});});
      chart.setOption({animation:false,backgroundColor:'#fff',legend:{top:6,left:'center',data:series.map(function(item){return item.name;})},tooltip:{trigger:'axis',axisPointer:{type:'cross'}},grid:{left:62,right:112,top:52,bottom:78},xAxis:{type:'category',data:data.dates,boundaryGap:true,axisLine:{lineStyle:{color:'#9ca3af'}},axisLabel:{hideOverlap:true}},yAxis:{scale:true,splitLine:{lineStyle:{color:'#e8edf4'}}},dataZoom:[{type:'inside',start:60,end:100},{type:'slider',start:60,end:100,bottom:18,height:24}],series:series});
      window.addEventListener('resize',function(){chart.resize();});
    })();
    </script>
    """
    output.write_text(
        html_document(
            title=f"{title_name} 支撑压力共振分析",
            body=body,
            styles=styles,
            head_extra='<link rel="icon" href="data:,">' + script_src(asset_href),
            scripts=scripts,
        ),
        encoding="utf-8",
    )
    return output
