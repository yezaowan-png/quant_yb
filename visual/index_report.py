"""HTML report for index daily overview."""

from __future__ import annotations

from html import escape
from pathlib import Path
import sys
from urllib.request import urlopen

import pandas as pd

from analysis.technical_structure import TechnicalStructureService
from analysis.index_overview import build_index_overview
from analysis.market_breadth import breadth_for_payload, breadth_indicator_payload
from visual.components import (
    DEFAULT_ECHARTS_CDN,
    echarts_script_tag,
    html_document,
    inline_script,
    to_compact_json,
)
from visual.stock_report_data import (
    calc_kdj,
    calc_ma,
    calc_macd,
    calc_rsi,
    clean_list,
    resample_ohlc,
)
from visual.technical_structure_renderer import TechnicalStructureRenderer


_ECHARTS_CDN = DEFAULT_ECHARTS_CDN
_PROJECT_ECHARTS = Path(__file__).resolve().parent / "assets" / "echarts.min.js"
_ECHARTS_DOWNLOAD_ATTEMPTED = False


def _find_local_echarts() -> Path | None:
    """Find a local ECharts bundle so file:// reports work without network."""
    if _PROJECT_ECHARTS.exists() and _PROJECT_ECHARTS.stat().st_size > 100_000:
        return _PROJECT_ECHARTS
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


def _cache_project_echarts() -> Path | None:
    """Cache the existing ECharts dependency locally; CDN remains a fallback."""
    global _ECHARTS_DOWNLOAD_ATTEMPTED
    local = _find_local_echarts()
    if local is not None or _ECHARTS_DOWNLOAD_ATTEMPTED:
        return local
    _ECHARTS_DOWNLOAD_ATTEMPTED = True
    try:
        with urlopen(_ECHARTS_CDN, timeout=10) as response:
            payload = response.read()
        if len(payload) < 100_000 or b"echarts" not in payload[:20_000].lower():
            return None
        _PROJECT_ECHARTS.parent.mkdir(parents=True, exist_ok=True)
        _PROJECT_ECHARTS.write_bytes(payload)
        return _PROJECT_ECHARTS
    except (OSError, ValueError):
        return None


def _echarts_script_tag() -> str:
    local_path = _cache_project_echarts()
    if local_path is None:
        return echarts_script_tag(_ECHARTS_CDN)
    local_tag = echarts_script_tag(_ECHARTS_CDN, local_path)
    fallback = inline_script(
        "if(typeof echarts==='undefined'){document.write('<script src=\""
        + _ECHARTS_CDN
        + "\"><\\/script>');}"
    )
    return local_tag + fallback


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
.technical-controls { display:flex; flex-wrap:wrap; gap:14px; margin:12px 0 0; color:#6b7280; font-size:12px; }
.technical-controls label { display:flex; gap:5px; align-items:center; cursor:pointer; }
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
function lg(data,selected){var r={type:'scroll',top:30,left:24,right:24,textStyle:{fontSize:10,color:C.axis},data:data};if(selected)r.selected=selected;return r;}
function title(t){return{text:t,left:'left',top:6,textStyle:{fontSize:15,fontWeight:'bold',color:'#111827'}};}
function chart(id,opt){var c=echarts.init(document.getElementById(id),null,{renderer:'canvas'});c.setOption(opt);ALL.push(c);return c;}
function kTooltip(d){
  return function(params){
    var idx=params && params.length ? params[0].dataIndex : -1;
    var date=params && params.length ? params[0].axisValue : '';
    var o=d.ohlc[idx] || [];
    var b=d.breadth && d.breadth[idx] ? d.breadth[idx] : null;
    var html='<strong>'+date+'</strong><br/>开盘 '+o[0]+'<br/>收盘 '+o[1]+'<br/>最低 '+o[2]+'<br/>最高 '+o[3];
    if(b){html+='<br/>上涨 '+b.up+' 家<br/>下跌 '+b.down+' 家<br/>平盘 '+b.flat+' 家';}
    return html;
  };
}
function kline(id,d){
  var series=[{name:'K线',type:'candlestick',data:d.ohlc,itemStyle:{color:C.up,color0:C.down,borderColor:C.up,borderColor0:C.down},barMaxWidth:'60%',barMinWidth:3}];
  var names=['K线'],selected={};
  [{v:d.ma5,n:'MA5'},{v:d.ma10,n:'MA10'},{v:d.ma20,n:'MA20'},{v:d.ma60,n:'MA60'}].forEach(function(m,i){series.push({name:m.n,type:'line',data:m.v,smooth:true,symbol:'none',lineStyle:{color:C.ma[i],width:1.5,opacity:.8},connectNulls:true});names.push(m.n);});
  (d.technicalStructureSeries||[]).forEach(function(item){series.push(item);if(item.name){names.push(item.name);if(item.technicalStructureStatus&&item.technicalStructureStatus!=='active'&&item.technicalStructureStatus!=='role_reversal')selected[item.name]=false;}});
  chart(id,{title:title(d.title),legend:lg(names,selected),tooltip:{trigger:'axis',axisPointer:{type:'cross'},formatter:kTooltip(d)},xAxis:ax(d.dates),yAxis:ya(),dataZoom:dz(d),toolbox:{show:true,right:5,feature:{saveAsImage:{title:'保存为图片'}}},series:series});
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
function breadthAd(id,d){
  var groups=window._BG||{};
  var names=Object.keys(groups).filter(function(k){return groups[k]&&groups[k].dates&&groups[k].dates.length;});
  if(!names.length && d && d.dates && d.dates.length){groups={'全A':d};names=['全A'];}
  if(!names.length)return;
  var base=groups[names[0]], colors=[C.orange,C.blue,C.pink,'#7c60c5','#168457'];
  var series=names.map(function(name,i){var line=groups[name].ad_norm_line_rebased||groups[name].ad_norm_line;return{name:name+' 起点归零A/D线',type:'line',data:line,smooth:true,symbol:'none',lineStyle:{color:colors[i%colors.length],width:i===0?2.5:2},connectNulls:true};});
  if(groups['全A']&&groups['全A'].ad_norm){series.unshift({name:'全A每日广度',type:'bar',data:groups['全A'].ad_norm,itemStyle:{color:function(p){return p.value>=0?C.up:C.down;}},barMaxWidth:10});}
  chart(id,{title:title('腾落指数 A/D（标准化，起点归零）'),legend:lg(series.map(function(s){return s.name;})),tooltip:{trigger:'axis'},grid:{top:72,left:52,right:24,bottom:58},xAxis:ax(base.dates,false),yAxis:ya(),dataZoom:dz(base),series:series});
}
function breadthNhnl(id,d){
  if(!d || !d.dates || !d.dates.length)return;
  chart(id,{title:title('NH-NL 新高-新低'),legend:lg(['NH-NL','NH-NL 5日','一年新高','一年新低']),tooltip:{trigger:'axis'},xAxis:ax(d.dates,false),yAxis:ya(),dataZoom:dz(d),series:[{name:'NH-NL',type:'bar',data:d.nhnl,itemStyle:{color:function(p){return p.value>=0?C.up:C.down;}}},{name:'NH-NL 5日',type:'line',data:d.nhnl_5d,smooth:true,symbol:'none',lineStyle:{color:C.blue,width:2},connectNulls:true},{name:'一年新高',type:'line',data:d.new_high,smooth:true,symbol:'none',lineStyle:{color:C.orange,width:1.2,opacity:.75},connectNulls:true},{name:'一年新低',type:'line',data:d.new_low,smooth:true,symbol:'none',lineStyle:{color:C.pink,width:1.2,opacity:.75},connectNulls:true}]});
}
function init(){
  ['daily','weekly','monthly'].forEach(function(p){var d=window._D[p];kline('k-'+p,d);volume('vol-'+p,d);macd('macd-'+p,d);kdj('kdj-'+p,d);rsi('rsi-'+p,d);});
  if((window._B && window._B.dates && window._B.dates.length) || window._BG){breadthAd('breadth-ad-daily',window._B);breadthNhnl('breadth-nhnl-daily',window._B);}
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
window.toggleTechnicalStructure=function(input){var kind=input.getAttribute('data-kind'),checked=!!input.checked;ALL.forEach(function(chart){try{(chart.getOption().series||[]).forEach(function(series){var matched=kind==='inactive'?(series.technicalStructureStatus&&series.technicalStructureStatus!=='active'&&series.technicalStructureStatus!=='role_reversal'):(series.technicalStructureKind===kind);if(matched&&series.name)chart.dispatchAction({type:checked?'legendSelect':'legendUnSelect',name:series.name});});}catch(e){}});};
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


def _period_payload(
    symbol: str,
    period_label: str,
    df: pd.DataFrame,
    breadth_by_date: dict | None = None,
    technical_structure: dict | None = None,
    technical_series: list[dict] | None = None,
) -> dict:
    dates = df["date"].dt.strftime("%Y-%m-%d").tolist()
    ohlc = [
        [round(float(o), 2), round(float(c), 2), round(float(l), 2), round(float(h), 2)]
        for o, c, l, h in df[["open", "close", "low", "high"]].values.tolist()
    ]
    close = df["close"]
    dif, dea, macd_hist = calc_macd(close)
    k_vals, d_vals, j_vals = calc_kdj(df["high"], df["low"], close)
    return {
        "title": f"{symbol} 指数走势 ({period_label})",
        "dates": dates,
        "ohlc": ohlc,
        "breadth": breadth_for_payload(dates, breadth_by_date),
        "ma5": clean_list(calc_ma(close, 5), 2),
        "ma10": clean_list(calc_ma(close, 10), 2),
        "ma20": clean_list(calc_ma(close, 20), 2),
        "ma60": clean_list(calc_ma(close, 60), 2),
        "volume": clean_list(df["volume"].tolist() if "volume" in df.columns else [], 0),
        "macd": {
            "dif": clean_list(dif, 3),
            "dea": clean_list(dea, 3),
            "hist": clean_list(macd_hist, 3),
        },
        "kdj": {
            "k": clean_list(k_vals, 1),
            "d": clean_list(d_vals, 1),
            "j": clean_list(j_vals, 1),
        },
        "rsi": clean_list(calc_rsi(close, 14), 1),
        "technical_structure": technical_structure or {},
        "technicalStructureSeries": technical_series or [],
    }


def _build_period_data(
    symbol: str,
    df: pd.DataFrame,
    breadth_by_date: dict | None = None,
    technical_structure_config: dict | None = None,
) -> dict:
    weekly = resample_ohlc(df, "W", include_incomplete_bar=False)
    monthly = resample_ohlc(df, "M", include_incomplete_bar=False)
    config = technical_structure_config or {}
    service = TechnicalStructureService(config, cache_dir=config.get("cache_dir"))
    results = service.analyze_multi_timeframe(
        symbol=symbol,
        asset_type="index",
        timeframes=["1d", "1w", "1mo"],
        ohlcv=df,
        adjustment="none",
    )
    renderer = TechnicalStructureRenderer()
    frames = {"1d": df, "1w": weekly, "1mo": monthly}
    structure_series = {
        timeframe: renderer.build_multi_timeframe_series(
            results,
            chart_timeframe=timeframe,
            date_axis=frames[timeframe]["date"].dt.strftime("%Y-%m-%d").tolist(),
            options={"include_broken": True, "include_expired": True},
        )
        for timeframe in frames
    }
    return {
        "daily": _period_payload(symbol, "日K", df, breadth_by_date, results["1d"].to_dict(), structure_series["1d"]),
        "weekly": _period_payload(symbol, "周K", weekly, None, results["1w"].to_dict(), structure_series["1w"]),
        "monthly": _period_payload(symbol, "月K", monthly, None, results["1mo"].to_dict(), structure_series["1mo"]),
    }


def generate_index_report(
    df_ohlc: pd.DataFrame,
    symbol: str,
    output_path: Path,
    name: str = "",
    breadth_by_date: dict | None = None,
    breadth_groups: dict | None = None,
    technical_structure_config: dict | None = None,
) -> None:
    """Generate an HTML market overview report for one index."""
    if not pd.api.types.is_datetime64_any_dtype(df_ohlc["date"]):
        df_ohlc = df_ohlc.copy()
        df_ohlc["date"] = pd.to_datetime(df_ohlc["date"])
    df_ohlc = df_ohlc.sort_values("date").reset_index(drop=True)

    overview = build_index_overview(df_ohlc, symbol=symbol, name=name)
    is_shanghai_composite = symbol.upper() == "000001.SH"
    period_data = _build_period_data(symbol, df_ohlc, breadth_by_date, technical_structure_config)
    period_json = to_compact_json(period_data)
    breadth_indicator_json = to_compact_json(
        breadth_indicator_payload(period_data["daily"]["dates"], breadth_by_date)
        if is_shanghai_composite
        else {"dates": []}
    )
    breadth_groups_json = to_compact_json(breadth_groups if is_shanghai_composite and breadth_groups else {})

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
        breadth_tabs = ""
        breadth_panels = ""
        if period_id == "daily" and is_shanghai_composite:
            breadth_tabs = (
                f"<button class=\"tab-btn\" onclick=\"switchIndicator(this,'panel-ad-{period_id}')\">A/D</button>"
                f"<button class=\"tab-btn\" onclick=\"switchIndicator(this,'panel-nhnl-{period_id}')\">NH-NL</button>"
            )
            breadth_panels = f"""
  <div id="panel-ad-{period_id}" class="indicator-panel"><div class="chart-section"><div id="breadth-ad-{period_id}" class="chart-container ht-350"></div></div></div>
  <div id="panel-nhnl-{period_id}" class="indicator-panel"><div class="chart-section"><div id="breadth-nhnl-{period_id}" class="chart-container ht-350"></div></div></div>"""
        sections.append(f"""
<div id="period-{period_id}" class="period-section{active}">
  <div class="chart-section"><div id="k-{period_id}" class="chart-container"></div></div>
  <div class="indicator-tabs">
    <button class="tab-btn active" onclick="switchIndicator(this,'panel-volume-{period_id}')">成交量</button>
    <button class="tab-btn" onclick="switchIndicator(this,'panel-macd-{period_id}')">MACD</button>
    <button class="tab-btn" onclick="switchIndicator(this,'panel-kdj-{period_id}')">KDJ</button>
    <button class="tab-btn" onclick="switchIndicator(this,'panel-rsi-{period_id}')">RSI</button>
    {breadth_tabs}
  </div>
  <div id="panel-volume-{period_id}" class="indicator-panel active"><div class="chart-section"><div id="vol-{period_id}" class="chart-container ht-300"></div></div></div>
  <div id="panel-macd-{period_id}" class="indicator-panel"><div class="chart-section"><div id="macd-{period_id}" class="chart-container ht-350"></div></div></div>
  <div id="panel-kdj-{period_id}" class="indicator-panel"><div class="chart-section"><div id="kdj-{period_id}" class="chart-container ht-350"></div></div></div>
  <div id="panel-rsi-{period_id}" class="indicator-panel"><div class="chart-section"><div id="rsi-{period_id}" class="chart-container ht-300"></div></div></div>
  {breadth_panels}
</div>""")

    title = f"{overview['name']} 指数概览"
    latest_date = df_ohlc["date"].iloc[-1].strftime("%Y-%m-%d")
    body = f"""<div class="container">
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
  <div class="technical-controls">
    <label><input type="checkbox" data-kind="horizontal" checked onchange="toggleTechnicalStructure(this)">支撑阻力</label>
    <label><input type="checkbox" data-kind="trendline" checked onchange="toggleTechnicalStructure(this)">趋势线</label>
    <label><input type="checkbox" data-kind="channel" checked onchange="toggleTechnicalStructure(this)">趋势通道</label>
    <label><input type="checkbox" data-kind="inactive" onchange="toggleTechnicalStructure(this)">已失效结构</label>
    <span>指数使用不复权点位；日K叠加周/月水平结构，斜向结构只显示当前周期</span>
  </div>
  {"".join(sections)}
  <div class="footer">QuantYB &copy; 2026 · 指数概览仅基于历史行情与技术指标，不构成投资建议</div>
</div>"""
    scripts = f"{inline_script(f'window._D={period_json};window._B={breadth_indicator_json};window._BG={breadth_groups_json};')}\n{_CHART_JS}"
    html = html_document(
        title=title,
        body=body,
        styles=_CSS,
        head_extra=_echarts_script_tag(),
        scripts=scripts,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
