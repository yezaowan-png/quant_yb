"""HTML report for broad market index environment."""

from __future__ import annotations

from html import escape
import os
from pathlib import Path

import pandas as pd

from analysis.technical_structure import TechnicalStructureService
from analysis.index_market import build_market_overview
from analysis.market_breadth import breadth_indicator_payload
from visual.components import html_document, inline_script, to_compact_json
from visual.index_report import _echarts_script_tag
from visual.stock_report_data import calc_ma, clean_list
from visual.technical_structure_renderer import TechnicalStructureRenderer


_CSS = """
* { box-sizing: border-box; }
body {
  margin: 0;
  background: #f5f6f8;
  color: #172033;
  font-family: "Microsoft YaHei", "Noto Sans SC", "PingFang SC", sans-serif;
}
.shell { width: min(1400px, calc(100vw - 40px)); margin: 0 auto; padding: 26px 0 42px; }
.topbar {
  display: flex; justify-content: space-between; gap: 18px; align-items: flex-end;
  border-bottom: 1px solid #d9e0ea; padding-bottom: 18px;
}
h1 { margin: 0; font-size: 34px; line-height: 1.1; letter-spacing: 0; }
.sub { margin-top: 8px; color: #69748a; font-size: 13px; }
.badge {
  border: 1px solid #172033; background: #172033; color: #fff;
  min-height: 40px; display: inline-flex; align-items: center; padding: 0 14px;
  font-weight: 800;
}
.summary {
  margin: 18px 0 0; padding: 16px 18px; background: #fff; border: 1px solid #d9e0ea;
  font-size: 15px; line-height: 1.7;
}
.cards { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 18px; }
.card { background: #fff; border: 1px solid #d9e0ea; padding: 14px 16px; min-height: 94px; }
.card span { color: #69748a; font-size: 12px; }
.card strong { display: block; margin-top: 9px; font-size: 25px; }
.panel { background: #fff; border: 1px solid #d9e0ea; margin-top: 20px; overflow: hidden; }
.panel-head { display: flex; justify-content: space-between; gap: 12px; padding: 16px 18px; border-bottom: 1px solid #d9e0ea; }
.panel-head h2 { margin: 0; font-size: 21px; }
.panel-head span { color: #69748a; font-size: 13px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 11px 12px; border-bottom: 1px solid #edf0f5; text-align: right; white-space: nowrap; }
th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) { text-align: left; }
th { color: #69748a; background: #fbfcfe; font-weight: 700; }
tr:last-child td { border-bottom: none; }
.up { color: #c94343; font-weight: 800; }
.down { color: #168457; font-weight: 800; }
.flag { display: inline-flex; align-items: center; justify-content: center; min-width: 32px; height: 24px; border: 1px solid #d9e0ea; color: #69748a; }
.flag.on { color: #c94343; border-color: rgba(201,67,67,.26); background: rgba(201,67,67,.07); }
.rank { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 18px; }
.rank-box { background: #fff; border: 1px solid #d9e0ea; padding: 16px; }
.rank-box h3 { margin: 0 0 12px; font-size: 17px; }
.rank-box p { display: flex; justify-content: space-between; margin: 9px 0; color: #374151; }
.index-link { color: #172033; font-weight: 800; text-decoration: none; border-bottom: 1px solid rgba(23,32,51,.24); }
.index-link:hover { color: #2f6df6; border-bottom-color: #2f6df6; }
.main-chart { padding: 16px 16px 0; }
.chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; padding: 16px; }
.chart-box { min-height: 360px; }
.chart-box.main { min-height: 440px; }
.footer { margin-top: 22px; color: #8a94a6; font-size: 12px; text-align: center; }
@media (max-width: 980px) {
  .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .rank { grid-template-columns: 1fr; }
  .chart-grid { grid-template-columns: 1fr; }
  .panel { overflow-x: auto; }
}
@media (max-width: 620px) {
  .shell { width: min(100vw - 24px, 1400px); }
  .topbar { align-items: flex-start; flex-direction: column; }
  .cards { grid-template-columns: 1fr; }
}
"""


def _tone(value: str) -> str:
    if value.startswith("+"):
        return "up"
    if value.startswith("-"):
        return "down"
    return ""


def _flag(enabled: bool) -> str:
    return '<span class="flag on">是</span>' if enabled else '<span class="flag">否</span>'


def _overview_href(output_path: Path, symbol: str) -> str:
    target = output_path.parent / "index" / f"{symbol}_overview.html"
    return Path(os.path.relpath(target, output_path.parent)).as_posix()


def _index_link(output_path: Path, symbol: str, text: str) -> str:
    href = escape(_overview_href(output_path, symbol))
    return f'<a class="index-link" href="{href}">{escape(text)}</a>'


def _rank_items(rows: list[dict], output_path: Path) -> str:
    return "".join(
        f"<p><span>{_index_link(output_path, row['symbol'], row['name'])}</span>"
        f"<strong>{escape(row.get('ret20_text', '--'))} / 趋势{row['score']}</strong></p>"
        for row in rows
    )


def _shanghai_dates(index_frames: list[tuple[str, str, pd.DataFrame]]) -> list[str]:
    df = _shanghai_frame(index_frames)
    if df is None:
        return []
    dates = pd.to_datetime(df["date"], errors="coerce").dropna().sort_values()
    return dates.dt.strftime("%Y-%m-%d").tolist()


def _shanghai_frame(index_frames: list[tuple[str, str, pd.DataFrame]]) -> pd.DataFrame | None:
    for symbol, _, df in index_frames:
        if symbol.upper() != "000001.SH" or df is None or df.empty or "date" not in df.columns:
            continue
        frame = df.copy()
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
        return frame
    return None


def _shanghai_kline_payload(
    index_frames: list[tuple[str, str, pd.DataFrame]],
    technical_structure_config: dict | None = None,
) -> dict:
    df = _shanghai_frame(index_frames)
    if df is None or df.empty:
        return {"dates": [], "ohlc": [], "ma5": [], "ma10": [], "ma20": [], "ma60": []}
    dates = df["date"].dt.strftime("%Y-%m-%d").tolist()
    close = pd.to_numeric(df["close"], errors="coerce")
    config = technical_structure_config or {}
    results = TechnicalStructureService(config, cache_dir=config.get("cache_dir")).analyze_multi_timeframe(
        symbol="000001.SH", asset_type="index", timeframes=["1d", "1w", "1mo"], ohlcv=df, adjustment="none"
    )
    technical_series = TechnicalStructureRenderer().build_multi_timeframe_series(
        results, "1d", dates, {"include_broken": True, "include_expired": True}
    )
    return {
        "dates": dates,
        "ohlc": [
            [round(float(o), 2), round(float(c), 2), round(float(l), 2), round(float(h), 2)]
            for o, c, l, h in df[["open", "close", "low", "high"]].values.tolist()
        ],
        "ma5": clean_list(calc_ma(close, 5), 2),
        "ma10": clean_list(calc_ma(close, 10), 2),
        "ma20": clean_list(calc_ma(close, 20), 2),
        "ma60": clean_list(calc_ma(close, 60), 2),
        "technicalStructureSeries": technical_series,
        "technical_structure": results["1d"].to_dict(),
    }


_CHART_JS = r"""
<script>
(function(){
var C={up:'#c94343',down:'#168457',blue:'#2f6df6',orange:'#d38b24',pink:'#dc5f7d',axis:'#69748a',line:'#d9e0ea',split:'#edf0f5'};
function ax(d){return{data:d,boundaryGap:true,axisLabel:{fontSize:10,color:C.axis,rotate:30},axisLine:{lineStyle:{color:C.line}},splitLine:{show:true,lineStyle:{type:'dashed',color:C.split}}};}
function ya(o){o=o||{};var r={type:'value',scale:true,axisLabel:{fontSize:10,color:C.axis},splitLine:{show:true,lineStyle:{type:'dashed',color:C.split}}};if(o.name)r.name=o.name;return r;}
function dz(d){var start=Math.max(70,100-Math.max(30,100*90/Math.max(d.dates.length,1)));return[{type:'inside',start:start,end:100},{type:'slider',start:start,end:100,height:22,bottom:0}];}
function lg(data,selected){var r={type:'scroll',top:30,left:24,right:24,textStyle:{fontSize:10,color:C.axis},data:data};if(selected)r.selected=selected;return r;}
function title(t){return{text:t,left:10,top:6,textStyle:{fontSize:15,fontWeight:'bold',color:'#172033'}};}
function chart(id,opt){var el=document.getElementById(id);if(!el)return null;var c=echarts.init(el,null,{renderer:'canvas'});c.setOption(opt);return c;}
function kTooltip(params){
  var idx=params&&params.length?params[0].dataIndex:-1, date=params&&params.length?params[0].axisValue:'', d=window._SH_KLINE||{}, o=d.ohlc&&d.ohlc[idx]?d.ohlc[idx]:[];
  return '<strong>'+date+'</strong><br/>开盘 '+o[0]+'<br/>收盘 '+o[1]+'<br/>最低 '+o[2]+'<br/>最高 '+o[3];
}
function init(){
  var d=window._BREADTH_INDICATORS||{};
  if(!d.dates||!d.dates.length)return;
  var k=window._SH_KLINE||{};
  var charts=[];
  if(k.dates&&k.dates.length){
    var kSeries=[{name:'K线',type:'candlestick',data:k.ohlc,itemStyle:{color:C.up,color0:C.down,borderColor:C.up,borderColor0:C.down},barMaxWidth:'60%',barMinWidth:3}];
    var kNames=['K线','MA5','MA10','MA20','MA60'],selected={};
    [['MA5',k.ma5,C.orange],['MA10',k.ma10,C.blue],['MA20',k.ma20,'#7c60c5'],['MA60',k.ma60,C.pink]].forEach(function(m){kSeries.push({name:m[0],type:'line',data:m[1],smooth:true,symbol:'none',lineStyle:{color:m[2],width:1.5,opacity:.8},connectNulls:true});});
    (k.technicalStructureSeries||[]).forEach(function(item){kSeries.push(item);if(item.name){kNames.push(item.name);if(item.technicalStructureStatus&&item.technicalStructureStatus!=='active'&&item.technicalStructureStatus!=='role_reversal')selected[item.name]=false;}});
    charts.push(chart('market-sh-kline-chart',{title:title('上证指数 K线 · 自动技术结构'),legend:lg(kNames,selected),tooltip:{trigger:'axis',axisPointer:{type:'cross'},formatter:kTooltip},grid:{top:72,left:52,right:24,bottom:58},xAxis:ax(k.dates),yAxis:ya(),dataZoom:dz(k),series:kSeries}));
  }
  var groups=window._BREADTH_GROUPS||{};
  var names=Object.keys(groups).filter(function(k){return groups[k]&&groups[k].dates&&groups[k].dates.length;});
  if(!names.length){groups={'全A':d};names=['全A'];}
  var base=groups[names[0]], colors=[C.orange,C.blue,C.pink,'#7c60c5','#168457'];
  var adSeries=names.map(function(name,i){var line=groups[name].ad_norm_line_rebased||groups[name].ad_norm_line;return{name:name+' 起点归零A/D线',type:'line',data:line,smooth:true,symbol:'none',lineStyle:{color:colors[i%colors.length],width:i===0?2.5:2},connectNulls:true};});
  if(groups['全A']&&groups['全A'].ad_norm){adSeries.unshift({name:'全A每日广度',type:'bar',data:groups['全A'].ad_norm,itemStyle:{color:function(p){return p.value>=0?C.up:C.down;}},barMaxWidth:10});}
  charts.push(chart('market-ad-chart',{title:title('分层腾落指数 A/D（标准化，起点归零）'),legend:lg(adSeries.map(function(s){return s.name;})),tooltip:{trigger:'axis'},grid:{top:72,left:52,right:24,bottom:58},xAxis:ax(base.dates),yAxis:ya(),dataZoom:dz(base),series:adSeries}));
  charts.push(chart('market-nhnl-chart',{title:title('NH-NL 新高-新低'),legend:lg(['NH-NL','NH-NL 5日','一年新高','一年新低']),tooltip:{trigger:'axis'},grid:{top:72,left:52,right:24,bottom:58},xAxis:ax(d.dates),yAxis:ya(),dataZoom:dz(d),series:[{name:'NH-NL',type:'bar',data:d.nhnl,itemStyle:{color:function(p){return p.value>=0?C.up:C.down;}}},{name:'NH-NL 5日',type:'line',data:d.nhnl_5d,smooth:true,symbol:'none',lineStyle:{color:C.blue,width:2},connectNulls:true},{name:'一年新高',type:'line',data:d.new_high,smooth:true,symbol:'none',lineStyle:{color:C.orange,width:1.2,opacity:.75},connectNulls:true},{name:'一年新低',type:'line',data:d.new_low,smooth:true,symbol:'none',lineStyle:{color:C.pink,width:1.2,opacity:.75},connectNulls:true}]}));
  charts=charts.filter(Boolean);
  charts.forEach(function(c){c.group='market-breadth';});
  if(charts.length>1)echarts.connect('market-breadth');
  window.addEventListener('resize',function(){charts.forEach(function(c){c.resize();});});
}
window.addEventListener('DOMContentLoaded',init);
})();
</script>
"""


def generate_market_report(
    index_frames: list[tuple[str, str, pd.DataFrame]],
    output_path: Path,
    breadth_by_date: dict[str, dict[str, int]] | None = None,
    breadth_groups: dict | None = None,
    technical_structure_config: dict | None = None,
) -> Path:
    """Generate a broad-market environment HTML report."""
    overview = build_market_overview(index_frames, breadth_by_date=breadth_by_date)
    breadth_indicators = breadth_indicator_payload(_shanghai_dates(index_frames), breadth_by_date)
    shanghai_kline = _shanghai_kline_payload(index_frames, technical_structure_config)
    cards_html = "".join(
        f"<div class='card'><span>{escape(card['label'])}</span><strong>{escape(str(card['value']))}</strong></div>"
        for card in overview["cards"]
    )
    rows_html = []
    for row in overview["rows"]:
        rows_html.append(
            f"""
            <tr>
              <td>{_index_link(output_path, row['symbol'], row['name'])}</td>
              <td>{_index_link(output_path, row['symbol'], row['symbol'])}</td>
              <td>{escape(row['close_text'])}</td>
              <td class="{_tone(row['pct_chg_text'])}">{escape(row['pct_chg_text'])}</td>
              <td class="{_tone(row['ret5_text'])}">{escape(row['ret5_text'])}</td>
              <td class="{_tone(row['ret20_text'])}">{escape(row['ret20_text'])}</td>
              <td class="{_tone(row['ret60_text'])}">{escape(row['ret60_text'])}</td>
              <td class="{_tone(row['ytd_text'])}">{escape(row['ytd_text'])}</td>
              <td class="{_tone(row['drawdown20_text'])}">{escape(row['drawdown20_text'])}</td>
              <td>{escape(row['volatility20_text'])}</td>
              <td>{_flag(row['above_ma20'])}</td>
              <td>{_flag(row['above_ma60'])}</td>
              <td>{_flag(row['above_ma120'])}</td>
              <td>{escape(row['relative_score_text'])}</td>
              <td>{row['score']}</td>
            </tr>
            """
        )

    body = f"""
    <main class="shell">
      <header class="topbar">
        <div>
          <h1>大盘环境分析</h1>
          <div class="sub">数据截至 {escape(overview['latest_date'])} · 多指数横向比较 · 本地股票缓存广度/NH-NL</div>
        </div>
        <div class="badge">{escape(overview['environment'])}</div>
      </header>
      <section class="summary">{escape(overview['summary'])}</section>
      <section class="cards">{cards_html}</section>
      <section class="rank">
        <div class="rank-box"><h3>相对强势</h3>{_rank_items(overview['strongest'], output_path)}</div>
        <div class="rank-box"><h3>相对弱势</h3>{_rank_items(overview['weakest'], output_path)}</div>
      </section>
      <section class="panel">
        <div class="panel-head"><h2>上证广度指标</h2><span>K线叠加因果水平结构及当前周期有效斜向结构；A/D 与 NH-NL 描述市场内部</span></div>
        <div class="main-chart">
          <div id="market-sh-kline-chart" class="chart-box main"></div>
        </div>
        <div class="chart-grid">
          <div id="market-ad-chart" class="chart-box"></div>
          <div id="market-nhnl-chart" class="chart-box"></div>
        </div>
      </section>
      <section class="panel">
        <div class="panel-head"><h2>指数横向比较</h2><span>MA 状态和涨跌幅均基于已缓存 index_daily</span></div>
        <table>
          <thead>
            <tr>
              <th>指数</th><th>代码</th><th>收盘</th><th>当日</th><th>近5日</th><th>近20日</th>
              <th>近60日</th><th>年初至今</th><th>20日回撤</th><th>20日波动率</th>
              <th>MA20</th><th>MA60</th><th>MA120</th><th>相对分</th><th>趋势分</th>
            </tr>
          </thead>
          <tbody>{''.join(rows_html)}</tbody>
        </table>
      </section>
      <div class="footer">QuantYB &copy; 2026 · 大盘环境分析仅基于历史行情与技术指标，不构成投资建议</div>
    </main>
    """

    html = html_document(
        title="大盘环境分析",
        body=body,
        styles=_CSS,
        head_extra=_echarts_script_tag(),
        scripts=(
            inline_script(
                f"window._MARKET_OVERVIEW={to_compact_json(overview)};"
                f"window._BREADTH_INDICATORS={to_compact_json(breadth_indicators)};"
                f"window._BREADTH_GROUPS={to_compact_json(breadth_groups or {})};"
                f"window._SH_KLINE={to_compact_json(shanghai_kline)};"
            )
            + "\n"
            + _CHART_JS
        ),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path
