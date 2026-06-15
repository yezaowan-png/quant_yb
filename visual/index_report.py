"""HTML report for index daily overview."""

from __future__ import annotations

from html import escape
from pathlib import Path
import sys

import pandas as pd

from analysis.index_overview import build_index_overview
from visual.report import (
    _calc_kdj,
    _calc_ma,
    _calc_macd,
    _calc_rsi,
    _clean_list,
    _resample_ohlc,
    _to_json,
)


_ECHARTS_CDN = "https://assets.pyecharts.org/assets/v6/echarts.min.js"


def _find_local_echarts() -> Path | None:
    """Find a local ECharts bundle so file:// reports work without network."""
    roots = [Path(sys.prefix)]
    parent = Path(sys.prefix).parent
    if parent.name.lower() == "envs":
        roots.append(parent.parent)
    roots.extend([Path("E:/anaconda3"), Path("C:/ProgramData/Anaconda3")])

    patterns = [
        "Lib/site-packages/panel/dist/bundled/echarts/echarts@*/dist/echarts.min.js",
        "Lib/site-packages/pyecharts/datasets/echarts.min.js",
    ]
    seen: set[Path] = set()
    for root in roots:
        if root in seen or not root.exists():
            continue
        seen.add(root)
        for pattern in patterns:
            matches = sorted(root.glob(pattern))
            if matches:
                return matches[0]
    return None


def _echarts_script_tag() -> str:
    local_path = _find_local_echarts()
    if local_path is not None:
        js = local_path.read_text(encoding="utf-8", errors="ignore")
        return f"<script>{js}</script>"
    return f'<script src="{_ECHARTS_CDN}"></script>'


_CSS = """
* { box-sizing: border-box; }
body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
    background: #f5f6f8;
    color: #1f2933;
}
.container { max-width: 1440px; margin: 0 auto; padding: 24px; }
.topbar {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    gap: 16px;
    padding-bottom: 16px;
    border-bottom: 1px solid #d9dee7;
}
.title h1 { margin: 0; font-size: 26px; line-height: 1.2; }
.title .sub { margin-top: 6px; color: #6b7280; font-size: 13px; }
.brand { color: #8a94a6; font-size: 12px; letter-spacing: .4px; }
.stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 10px;
    margin-top: 22px;
}
.stat-card {
    background: #fff;
    border: 1px solid #e5e8ef;
    border-radius: 8px;
    padding: 14px 16px;
}
.stat-label { color: #758195; font-size: 12px; margin-bottom: 8px; }
.stat-value { color: #111827; font-size: 22px; font-weight: 700; line-height: 1.1; }
.stat-value.up { color: #d94444; }
.stat-value.down { color: #20966f; }
.notes {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 10px;
    margin-top: 14px;
}
.note {
    background: #fff;
    border: 1px solid #e5e8ef;
    border-radius: 8px;
    padding: 13px 15px;
    color: #374151;
    font-size: 14px;
}
.period-tabs {
    display: flex;
    gap: 12px;
    margin-top: 24px;
    border-bottom: 1px solid #d9dee7;
}
.period-tab-btn, .tab-btn {
    border: none;
    background: transparent;
    cursor: pointer;
    color: #748094;
    font: inherit;
    font-weight: 600;
}
.period-tab-btn { padding: 11px 20px; position: relative; }
.period-tab-btn.active { color: #111827; }
.period-tab-btn.active::after {
    content: "";
    position: absolute;
    left: 0;
    right: 0;
    bottom: -1px;
    height: 2px;
    background: #2563eb;
}
.period-section { display: none; }
.period-section.active { display: block; }
.chart-section {
    background: #fff;
    border: 1px solid #e5e8ef;
    border-radius: 8px;
    margin-top: 16px;
    overflow: hidden;
}
.chart-container { width: 100%; height: 500px; }
.chart-container.ht-300 { height: 300px; }
.chart-container.ht-350 { height: 350px; }
.indicator-tabs {
    display: flex;
    gap: 4px;
    margin-top: 18px;
    border-bottom: 1px solid #e5e8ef;
}
.tab-btn { padding: 10px 18px; position: relative; }
.tab-btn.active { color: #111827; }
.tab-btn.active::after {
    content: "";
    position: absolute;
    left: 0;
    right: 0;
    bottom: -1px;
    height: 2px;
    background: #2563eb;
}
.indicator-panel { display: none; }
.indicator-panel.active { display: block; }
.indicator-panel .chart-section { border-top: none; border-radius: 0 0 8px 8px; margin-top: 0; }
.footer { color: #9aa4b2; font-size: 11px; text-align: center; padding: 30px 0 6px; }
@media (max-width: 700px) {
    .container { padding: 16px; }
    .topbar { align-items: flex-start; flex-direction: column; }
    .title h1 { font-size: 22px; }
    .period-tabs, .indicator-tabs { overflow-x: auto; }
    .chart-container { height: 420px; }
}
"""


_CHART_JS = r"""
<script>
(function(){
var C={up:'#d94444',down:'#20966f',blue:'#2563eb',orange:'#d38b24',pink:'#dc5f7d',
       ma:['#d9a51d','#2d8bdc','#7c60c5','#dc5f7d'],axis:'#6b7280',line:'#d9dee7',split:'#edf0f5'};
var ALL=[];
function ax(d,s){return{data:d,boundaryGap:true,axisLabel:{fontSize:10,color:C.axis,rotate:30},axisLine:{lineStyle:{color:C.line}},splitLine:s!==false?{show:true,lineStyle:{type:'dashed',color:C.split}}:{show:false}};}
function ya(o){o=o||{};var r={type:'value',scale:true,axisLabel:{fontSize:10,color:C.axis},splitLine:{show:true,lineStyle:{type:'dashed',color:C.split}}};if(o.min!=null)r.min=o.min;if(o.max!=null)r.max=o.max;if(o.name)r.name=o.name;return r;}
function dz(d){var start=Math.max(70,100-Math.max(30,100*90/Math.max(d.dates.length,1)));return[{type:'inside',start:start,end:100},{type:'slider',start:start,end:100,height:22,bottom:2}];}
function lg(data){return{top:5,left:'center',textStyle:{fontSize:10,color:C.axis},data:data};}
function title(t){return{text:t,left:'left',top:6,textStyle:{fontSize:15,fontWeight:'bold',color:'#111827'}};}
function chart(id,opt){var c=echarts.init(document.getElementById(id),null,{renderer:'canvas'});c.setOption(opt);ALL.push(c);return c;}
function kline(id,d){
  var series=[{name:'K线',type:'candlestick',data:d.ohlc,itemStyle:{color:C.up,color0:C.down,borderColor:C.up,borderColor0:C.down},barMaxWidth:'60%',barMinWidth:3}];
  var names=['K线'];
  [{v:d.ma5,n:'MA5'},{v:d.ma10,n:'MA10'},{v:d.ma20,n:'MA20'},{v:d.ma60,n:'MA60'}].forEach(function(m,i){series.push({name:m.n,type:'line',data:m.v,smooth:true,symbol:'none',lineStyle:{color:C.ma[i],width:1.5,opacity:.8},connectNulls:true});names.push(m.n);});
  chart(id,{title:title(d.title),legend:lg(names),tooltip:{trigger:'axis',axisPointer:{type:'cross'}},xAxis:ax(d.dates),yAxis:ya(),dataZoom:dz(d),toolbox:{show:true,right:5,feature:{saveAsImage:{title:'保存为图片'}}},series:series});
}
function volume(id,d){
  var up=[],down=[];
  d.ohlc.forEach(function(o,i){var v=d.volume[i]||0;if(o[1]>=o[0]){up.push(v||0.01);down.push(0);}else{up.push(0);down.push(v||0.01);}});
  chart(id,{title:title('成交量'),tooltip:{trigger:'axis'},xAxis:ax(d.dates,false),yAxis:ya({name:'成交量'}),dataZoom:dz(d),series:[{type:'bar',data:up,stack:'v',itemStyle:{color:C.up}},{type:'bar',data:down,stack:'v',itemStyle:{color:C.down}}]});
}
function macd(id,d){
  chart(id,{title:title('MACD (12, 26, 9)'),legend:lg(['DIF','DEA','MACD']),tooltip:{trigger:'axis'},xAxis:ax(d.dates,false),yAxis:ya(),dataZoom:dz(d),series:[{name:'DIF',type:'line',data:d.macd.dif,smooth:true,symbol:'none',lineStyle:{color:C.blue,width:1.8},connectNulls:true},{name:'DEA',type:'line',data:d.macd.dea,smooth:true,symbol:'none',lineStyle:{color:C.orange,width:1.8},connectNulls:true},{name:'MACD',type:'bar',data:d.macd.hist,itemStyle:{color:function(p){return p.value>=0?C.up:C.down;}}}]});
}
function kdj(id,d){
  chart(id,{title:title('KDJ (9, 3, 3)'),legend:lg(['K','D','J']),tooltip:{trigger:'axis'},xAxis:ax(d.dates,false),yAxis:ya(),dataZoom:dz(d),series:[{name:'K',type:'line',data:d.kdj.k,smooth:true,symbol:'none',lineStyle:{color:C.blue,width:1.8},connectNulls:true},{name:'D',type:'line',data:d.kdj.d,smooth:true,symbol:'none',lineStyle:{color:C.orange,width:1.8},connectNulls:true},{name:'J',type:'line',data:d.kdj.j,smooth:true,symbol:'none',lineStyle:{color:C.pink,width:1.3},connectNulls:true}]});
}
function rsi(id,d){
  var f30=Array(d.dates.length).fill(30),f70=Array(d.dates.length).fill(70);
  chart(id,{title:title('RSI (14)'),legend:lg(['RSI','30','70']),tooltip:{trigger:'axis'},xAxis:ax(d.dates,false),yAxis:ya({min:0,max:100}),dataZoom:dz(d),series:[{name:'RSI',type:'line',data:d.rsi,smooth:true,symbol:'none',lineStyle:{color:C.blue,width:2},connectNulls:true},{name:'30',type:'line',data:f30,symbol:'none',lineStyle:{color:C.down,width:1,type:'dashed'}},{name:'70',type:'line',data:f70,symbol:'none',lineStyle:{color:C.up,width:1,type:'dashed'}}]});
}
function init(){
  ['daily','weekly','monthly'].forEach(function(p){var d=window._D[p];kline('k-'+p,d);volume('vol-'+p,d);macd('macd-'+p,d);kdj('kdj-'+p,d);rsi('rsi-'+p,d);});
  ALL.forEach(function(c){c.group='index-overview';});
  echarts.connect('index-overview');
  window._ALL=ALL;
}
function resizeIn(el){setTimeout(function(){ALL.forEach(function(c){try{if(el.contains(c.getDom()))c.resize();}catch(e){}});},80);}
function switchPeriod(id){
  document.querySelectorAll('.period-tab-btn').forEach(function(b){b.classList.remove('active');});
  document.querySelectorAll('.period-section').forEach(function(s){s.classList.remove('active');});
  var btn=document.querySelector('[data-target="'+id+'"]'); if(btn)btn.classList.add('active');
  var sec=document.getElementById(id); if(sec){sec.classList.add('active');resizeIn(sec);}
}
function switchIndicator(btn,id){
  var sec=btn.closest('.period-section');
  sec.querySelectorAll('.tab-btn').forEach(function(b){b.classList.remove('active');});
  sec.querySelectorAll('.indicator-panel').forEach(function(p){p.classList.remove('active');});
  btn.classList.add('active');
  var panel=document.getElementById(id); if(panel){panel.classList.add('active');resizeIn(panel);}
}
window.switchPeriod=switchPeriod;
window.switchIndicator=switchIndicator;
window.addEventListener('DOMContentLoaded',init);
window.addEventListener('resize',function(){ALL.forEach(function(c){c.resize();});});
})();
</script>
"""


def _class_for_value(value: str) -> str:
    if value.startswith("+"):
        return " up"
    if value.startswith("-"):
        return " down"
    return ""


def _period_payload(symbol: str, period_label: str, df: pd.DataFrame) -> dict:
    dates = df["date"].dt.strftime("%Y-%m-%d").tolist()
    ohlc = [
        [round(float(o), 2), round(float(c), 2), round(float(l), 2), round(float(h), 2)]
        for o, c, l, h in df[["open", "close", "low", "high"]].values.tolist()
    ]
    close = df["close"]
    dif, dea, macd_hist = _calc_macd(close)
    k_vals, d_vals, j_vals = _calc_kdj(df["high"], df["low"], close)
    return {
        "title": f"{symbol} 指数走势 ({period_label})",
        "dates": dates,
        "ohlc": ohlc,
        "ma5": _clean_list(_calc_ma(close, 5), 2),
        "ma10": _clean_list(_calc_ma(close, 10), 2),
        "ma20": _clean_list(_calc_ma(close, 20), 2),
        "ma60": _clean_list(_calc_ma(close, 60), 2),
        "volume": _clean_list(df["volume"].tolist() if "volume" in df.columns else [], 0),
        "macd": {
            "dif": _clean_list(dif, 3),
            "dea": _clean_list(dea, 3),
            "hist": _clean_list(macd_hist, 3),
        },
        "kdj": {
            "k": _clean_list(k_vals, 1),
            "d": _clean_list(d_vals, 1),
            "j": _clean_list(j_vals, 1),
        },
        "rsi": _clean_list(_calc_rsi(close, 14), 1),
    }


def _build_period_data(symbol: str, df: pd.DataFrame) -> dict:
    weekly = _resample_ohlc(df, "W")
    monthly = _resample_ohlc(df, "M")
    return {
        "daily": _period_payload(symbol, "日K", df),
        "weekly": _period_payload(symbol, "周K", weekly),
        "monthly": _period_payload(symbol, "月K", monthly),
    }


def generate_index_report(
    df_ohlc: pd.DataFrame,
    symbol: str,
    output_path: Path,
    name: str = "",
) -> None:
    """Generate an HTML market overview report for one index."""
    if not pd.api.types.is_datetime64_any_dtype(df_ohlc["date"]):
        df_ohlc = df_ohlc.copy()
        df_ohlc["date"] = pd.to_datetime(df_ohlc["date"])
    df_ohlc = df_ohlc.sort_values("date").reset_index(drop=True)

    overview = build_index_overview(df_ohlc, symbol=symbol, name=name)
    period_json = _to_json(_build_period_data(symbol, df_ohlc))

    cards_html = []
    for card in overview["cards"]:
        value = escape(str(card["value"]))
        cards_html.append(
            f'<div class="stat-card"><div class="stat-label">{escape(card["label"])}</div>'
            f'<div class="stat-value{_class_for_value(value)}">{value}</div></div>'
        )
    notes_html = "".join(f'<div class="note">{escape(note)}</div>' for note in overview["notes"])

    period_buttons = (
        '<button class="period-tab-btn active" data-target="period-daily" onclick="switchPeriod(\'period-daily\')">日K</button>'
        '<button class="period-tab-btn" data-target="period-weekly" onclick="switchPeriod(\'period-weekly\')">周K</button>'
        '<button class="period-tab-btn" data-target="period-monthly" onclick="switchPeriod(\'period-monthly\')">月K</button>'
    )

    sections = []
    for period_id in ["daily", "weekly", "monthly"]:
        active = " active" if period_id == "daily" else ""
        sections.append(f"""
<div id="period-{period_id}" class="period-section{active}">
  <div class="chart-section"><div id="k-{period_id}" class="chart-container"></div></div>
  <div class="indicator-tabs">
    <button class="tab-btn active" onclick="switchIndicator(this,'panel-volume-{period_id}')">成交量</button>
    <button class="tab-btn" onclick="switchIndicator(this,'panel-macd-{period_id}')">MACD</button>
    <button class="tab-btn" onclick="switchIndicator(this,'panel-kdj-{period_id}')">KDJ</button>
    <button class="tab-btn" onclick="switchIndicator(this,'panel-rsi-{period_id}')">RSI</button>
  </div>
  <div id="panel-volume-{period_id}" class="indicator-panel active"><div class="chart-section"><div id="vol-{period_id}" class="chart-container ht-300"></div></div></div>
  <div id="panel-macd-{period_id}" class="indicator-panel"><div class="chart-section"><div id="macd-{period_id}" class="chart-container ht-350"></div></div></div>
  <div id="panel-kdj-{period_id}" class="indicator-panel"><div class="chart-section"><div id="kdj-{period_id}" class="chart-container ht-350"></div></div></div>
  <div id="panel-rsi-{period_id}" class="indicator-panel"><div class="chart-section"><div id="rsi-{period_id}" class="chart-container ht-300"></div></div></div>
</div>""")

    title = f"{overview['name']} 指数概览"
    latest_date = df_ohlc["date"].iloc[-1].strftime("%Y-%m-%d")
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(title)}</title>
{_echarts_script_tag()}
<style>{_CSS}</style>
</head>
<body>
<div class="container">
  <div class="topbar">
    <div class="title">
      <h1>{escape(title)}</h1>
      <div class="sub">{escape(symbol)} · 数据截至 {escape(latest_date)} · Tushare index_daily</div>
    </div>
    <div class="brand">QuantYB Index Overview</div>
  </div>
  <div class="stats-grid">{"".join(cards_html)}</div>
  <div class="notes">{notes_html}</div>
  <div class="period-tabs">{period_buttons}</div>
  {"".join(sections)}
  <div class="footer">QuantYB &copy; 2026 · 指数概览仅基于历史行情与技术指标，不构成投资建议</div>
</div>
<script>window._D={period_json};</script>
{_CHART_JS}
</body>
</html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
