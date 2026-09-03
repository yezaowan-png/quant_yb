"""生成完整 HTML 可视化报告 —— 亮色主题 + 紧凑渲染"""

from __future__ import annotations  # 仅用于推迟求值，不影响运行时

from pathlib import Path
from typing import Optional

import pandas as pd

from engine.runner import _add_completed_weekly_features, load_strategy_class
from visual.components import echarts_script_tag, html_document, inline_script, script_src, to_compact_json
from visual.stock_report_data import (
    build_stock_period_payload,
    build_weekly_ema_diagnostics,
    build_equity_payload,
    build_mtf_diagnostics_payload,
    calc_ema,
    calc_kdj,
    calc_ma,
    calc_macd,
    calc_rsi,
    clean_list,
    compute_drawdowns,
    map_trades_to_period,
    resample_ohlc,
    strategy_param_value,
)
from analysis.technical_structure import TechnicalStructureService
from visual.technical_structure_renderer import TechnicalStructureRenderer

# ---- echarts CDN ----
_ECHARTS_SRC = "https://assets.pyecharts.org/assets/v6/echarts.min.js"

# ---- 策略中文名 ----
_STRAT_NAMES = {"sma_cross": "双均线交叉", "macd_cross": "MACD 金叉", "kdj": "KDJ",
                "bollinger": "布林带", "rsi": "RSI", "single_ma": "单均线",
                "volume_platform_breakout": "放量平台突破",
                "multi_timeframe_volume_trend": "多周期量价趋势",
                "trendlines": "手动画线工具"}


# ============================================================
#  技术指标计算（纯 Python，不依赖 pyecharts）
# ============================================================

def _calc_ma(close: pd.Series, period: int) -> list:
    return calc_ma(close, period)


def _calc_ema(close: pd.Series, period: int) -> list:
    return calc_ema(close, period)


def _calc_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    return calc_macd(close, fast=fast, slow=slow, signal=signal)


def _calc_kdj(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 9):
    return calc_kdj(high, low, close, period=period)


def _calc_rsi(close: pd.Series, period: int = 14) -> list:
    return calc_rsi(close, period=period)


# ============================================================
#  周期降采样
# ============================================================

def _resample_ohlc(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    return resample_ohlc(df, freq, include_incomplete_bar=False)


def _map_trades_to_period(
    trades_df: pd.DataFrame, period_df: pd.DataFrame
) -> tuple[list, list]:
    return map_trades_to_period(trades_df, period_df)


# ============================================================
#  JSON 序列化辅助
# ============================================================

def _to_json(obj) -> str:
    return to_compact_json(obj)


def _clean_list(lst, decimals=None):
    """将指标值列表转为 JSON-safe 类型，None 保持 null。"""
    return clean_list(lst, decimals)


# ============================================================
#  权益曲线计算
# ============================================================

def _compute_drawdowns(values: list[float]) -> list[float]:
    return compute_drawdowns(values)


def _strategy_param_value(strategy_cls, strategy_params: Optional[dict], name: str, default):
    return strategy_param_value(strategy_cls, strategy_params, name, default)


def _calc_mtf_diagnostics(
    df_ohlc: pd.DataFrame,
    df_trades: pd.DataFrame,
    strategy_params: Optional[dict] = None,
) -> tuple[dict, str]:
    """Recompute stage-3 diagnostics for multi_timeframe_volume_trend reports."""
    cls = load_strategy_class("multi_timeframe_volume_trend")
    params = strategy_params or {}
    diagnostics, summary = build_mtf_diagnostics_payload(
        df_ohlc=df_ohlc,
        df_trades=df_trades,
        strategy_cls=cls,
        strategy_params=params,
        weekly_feature_builder=_add_completed_weekly_features,
    )
    diagnostic_html = f"""
    <div class="diagnostic-grid">
        <div class="diagnostic-card"><span>{summary["trend_label"]}</span><strong>{summary["trend_text"]}</strong></div>
        <div class="diagnostic-card"><span>近{summary["pullback_valid_days"]}日回调</span><strong>{summary["pullback_text"]}</strong></div>
        <div class="diagnostic-card"><span>近{summary["stalling_buy_filter_days"]}日滞涨</span><strong>{summary["stalling_text"]}</strong></div>
        <div class="diagnostic-card"><span>加速平台过滤</span><strong>{summary["post_accel_text"]}</strong></div>
        <div class="diagnostic-card"><span>今日突破</span><strong>{summary["breakout_text"]}</strong></div>
        <div class="diagnostic-card"><span>量价确认</span><strong>{summary["confirm_text"]}/4</strong></div>
        <div class="diagnostic-card"><span>买入设置</span><strong>{summary["setup_text"]}</strong></div>
    </div>
    """
    return diagnostics, diagnostic_html



# ============================================================
#  统计卡片
# ============================================================

def _compute_stats(df_trades, equity_data) -> dict:
    stats: dict = {}
    if df_trades is not None and not df_trades.empty:
        sells = df_trades[df_trades["direction"] == "SELL"]
        buys = df_trades[df_trades["direction"] == "BUY"]
        total_trades = len(buys)
        if total_trades > 0:
            win_trades = int((sells["pnl"] > 0).sum())
            stats["total_trades"] = total_trades
            stats["win_trades"] = win_trades
            stats["lose_trades"] = total_trades - win_trades
            stats["win_rate"] = round(win_trades / total_trades * 100, 2)
            stats["total_pnl"] = round(sells["pnl"].sum(), 2)

    if equity_data is not None and not equity_data.empty:
        eq = equity_data["equity"].tolist()
        if eq:
            stats["initial_value"] = round(eq[0], 2)
            stats["final_value"] = round(eq[-1], 2)
            if stats["initial_value"] > 0:
                stats["total_return"] = round(
                    (stats["final_value"] - stats["initial_value"]) / stats["initial_value"] * 100, 2)
            dd = _compute_drawdowns(eq)
            stats["max_drawdown"] = round(min(dd), 2) if dd else 0

    return stats


def _build_stats_html(stats: dict) -> str:
    cards: list[str] = []

    def _card(label: str, value: str, css_class: str = "") -> str:
        cls = f" {css_class}" if css_class else ""
        return f'<div class="stat-card"><div class="stat-label">{label}</div><div class="stat-value{cls}">{value}</div></div>'

    if "total_return" in stats:
        ret = stats["total_return"]
        cards.append(_card("总收益率", f"{'+' if ret >= 0 else ''}{ret}%", "up" if ret >= 0 else "down"))
    if "max_drawdown" in stats:
        cards.append(_card("最大回撤", f"{stats['max_drawdown']}%", "down"))
    if "total_trades" in stats:
        cards.append(_card("交易次数", str(stats["total_trades"])))
    if "win_rate" in stats:
        cards.append(_card("胜率", f"{stats['win_rate']}%"))
    if "final_value" in stats:
        cards.append(_card("最终权益", f"&yen;{stats['final_value']:,.2f}"))
    if "total_pnl" in stats:
        pnl = stats["total_pnl"]
        cards.append(_card("总盈亏", f"{'+' if pnl >= 0 else ''}&yen;{pnl:,.2f}", "up" if pnl >= 0 else "down"))

    return "\n".join(cards)


# ============================================================
#  JS 图表工厂模板（嵌入 HTML，约 5KB）
# ============================================================

_CHART_JS = r"""<script>
(function(){
var C={bg:'#fff',up:'#ef5350',dn:'#26a69a',bl:'#5470c6',or:'#e8a020',jr:'#ee6666',
 ma:['#e8b830','#60a5fa','#a78bfa','#fb7185'],ti:'#1a1a2e',lb:'#6b6b7b',
 ln:'#d0d0d8',sp:'#e8e8ec'};

function ax(d,s){return{data:d,boundaryGap:true,axisLabel:{fontSize:10,color:C.lb,rotate:30},axisLine:{lineStyle:{color:C.ln}},splitLine:s!==false?{show:true,lineStyle:{type:'dashed',color:C.sp}}:{show:false}};}

function ya(o){o=o||{};var r={type:'value',scale:true,axisLabel:{fontSize:10,color:C.lb},splitLine:{show:true,lineStyle:{type:'dashed',color:C.sp}}};if(o.name)r.name=o.name,r.nameTextStyle={fontSize:10,color:C.lb};if(o.min!=null)r.min=o.min;if(o.max!=null)r.max=o.max;return r;}

function tl(){return{trigger:'axis',axisPointer:{type:'cross'}};}
function dz(vs){vs=vs||70;return[{type:'inside',start:vs,end:100},{type:'slider',start:vs,end:100,height:22,bottom:2}];}
function tb(){return{show:true,right:5,feature:{saveAsImage:{title:'保存为图片'}}};}
function lg(d,s){return{show:d&&d.length>0,type:'scroll',top:18,left:'center',right:120,textStyle:{fontSize:11,color:C.lb},data:d||[],selected:s||{}};}
function ti(t){return{text:t,left:16,top:16,textStyle:{fontSize:16,fontWeight:'bold',color:C.ti}};}
function grid(top,bottom){return{left:64,right:42,top:top||86,bottom:bottom||74};}

var ALL=[];
function ch(dom,opt){var c=echarts.init(document.getElementById(dom),null,{renderer:'canvas'});c.setOption(opt);ALL.push(c);return c;}

// ---- K-line ----
function diagSeries(name,data,symbol,size,color,labelText){
  return {name:name,type:'scatter',data:data||[],symbol:symbol,symbolSize:size,z:5,
    itemStyle:{color:color,opacity:.92,borderColor:'#fff',borderWidth:1},
    label:{show:!!labelText,formatter:labelText||'',position:'top',fontSize:10,color:color,distance:6},
    tooltip:{formatter:function(p){return name+'<br/>'+p.data[0]+' : '+p.data[1];}}};
}
function tlSeriesName(prefix,line){
  var score=line&&line.score!=null?(' · '+Number(line.score).toFixed(1)):'';
  return prefix+score;
}
function take(a,n){return (a||[]).slice(0,n);}
function sortLevels(levels,n){
  return (levels||[]).slice().sort(function(a,b){
    var da=Math.abs(Number(a.close_distance_pct||0)),db=Math.abs(Number(b.close_distance_pct||0));
    if(da!==db)return da-db;
    return Number(b.strength_score||0)-Number(a.strength_score||0);
  }).slice(0,n);
}
function addLineOverlay(se,lgD,name,line,color,lineType,labelText,opacity,width,kind,status){
  if(!line||line.start_date==null||line.end_date==null)return;
  var label=labelText||line.label||name;
  if(lgD&&name)lgD.push(name);
  se.push({name:name,type:'line',data:[[line.start_date,line.start_price],[line.end_date,line.end_price]],
    technicalStructureKind:kind||'trendline',technicalStructureStatus:status||'active',
    symbol:'none',smooth:false,z:4,
    lineStyle:{color:color,width:width||1.2,type:lineType||'solid',opacity:opacity||.7},
    label:{show:false},
    endLabel:{show:false},
    tooltip:{formatter:function(){var d=line.close_distance_pct;var rel=line.relation||'';return label+'<br/>'+line.start_date+' → '+line.end_date+'<br/>距离最新收盘: '+(d==null?'-':d+'%')+' '+rel;}}});
}
function addLevelOverlay(se,lgD,d,level,color,lineType,opacity,width){
  if(!level||!d.dates||!d.dates.length)return;
  var label=level.label||level.type||'Level';
  var name=label+' '+Number(level.price).toFixed(2);
  if(lgD&&name)lgD.push(name);
  se.push({name:name,type:'line',data:[[d.dates[0],level.price],[d.dates[d.dates.length-1],level.price]],
    technicalStructureKind:'horizontal',technicalStructureStatus:level.status||'active',
    symbol:'none',smooth:false,z:3,
    lineStyle:{color:color,width:width||1,type:lineType||'dashed',opacity:opacity||.55},
    label:{show:false},
    endLabel:{show:false},
    tooltip:{formatter:function(){return label+' '+Number(level.price).toFixed(2)+'<br/>触碰: '+level.touch_count+'<br/>距离最新收盘: '+level.close_distance_pct+'% '+(level.relation||'');}}});
}
function addTrendlineOverlays(se,lgD,lgS,d){
  if(d.technicalStructureSeries&&d.technicalStructureSeries.length){
    d.technicalStructureSeries.forEach(function(item){
      if(item&&item.name)lgD.push(item.name);
      if(item&&item.name&&item.technicalStructureStatus&&item.technicalStructureStatus!=='active'&&item.technicalStructureStatus!=='role_reversal')lgS[item.name]=false;
      if(item)item.legendHoverLink=false;
      se.push(item);
    });
    return;
  }
  var t=d.trendlines;if(!t)return;
  take(t.uptrend_lines,1).forEach(function(line,i){addLineOverlay(se,lgD,tlSeriesName('Uptrend Line '+(i+1),line),line,'#8b5cf6','solid','Uptrend Line',.82,1.6,'trendline',line.status||'active');});
  take(t.downtrend_lines,1).forEach(function(line,i){addLineOverlay(se,lgD,tlSeriesName('Downtrend Line '+(i+1),line),line,'#0ea5e9','solid','Downtrend Line',.82,1.6,'trendline',line.status||'active');});
  take(t.channels,1).forEach(function(ch,i){
    if(ch.parallel_line){
      var label=ch.parallel_line.label||'Channel';
      addLineOverlay(se,lgD,tlSeriesName(label+' '+(i+1),ch.parallel_line),ch.parallel_line,'#64748b','dashed',label,.58,1.2,'channel',ch.status||'active');
    }
  });
  sortLevels(t.support,2).forEach(function(level){addLevelOverlay(se,lgD,d,level,'#16a34a','dashed',.55,1);});
  sortLevels(t.resistance,2).forEach(function(level){addLevelOverlay(se,lgD,d,level,'#dc2626','dashed',.55,1);});
  take(t.necklines,1).forEach(function(n,i){
    if(n.line){addLineOverlay(se,lgD,'Neckline: '+n.pattern_type+' '+(i+1),n.line,'#f97316','dotted','Neckline: '+n.pattern_type,.62,1.1,'trendline',n.status||'active');}
  });
}
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function relText(r){return r==='above'?'上方':(r==='below'?'下方':'附近');}
function pct(v){return v==null?'-':(Number(v).toFixed(2)+'%');}
function lineMeta(line){
  return '线价 '+Number(line.latest_line_price||line.end_price||0).toFixed(2)+' · 距离 '+pct(line.close_distance_pct)+' · '+relText(line.relation)+' · 分 '+Number(line.score||0).toFixed(1);
}
function levelMeta(level){
  return '价位 '+Number(level.price||0).toFixed(2)+' · 距离 '+pct(level.close_distance_pct)+' · '+relText(level.relation)+' · 触碰 '+(level.touch_count||0);
}
function panelItem(label,meta,color){
  return '<div class="tl-item"><span class="tl-swatch" style="background:'+esc(color)+'"></span><div><div class="tl-title">'+esc(label)+'</div><div class="tl-meta">'+esc(meta)+'</div></div></div>';
}
function renderTrendlinePanel(dom,d){
  var el=document.getElementById(dom);if(!el)return;
  var pid=dom.replace(/^tl-/,'');
  var close='<button class="tl-close" type="button" onclick="toggleTrendPanel(&quot;'+esc(pid)+'&quot;,false)">×</button>';
  var nt=d.technical_structure;
  if(nt&&nt.current_context){
    var ctx=nt.current_context||{}, adj={qfq:'前复权',hfq:'后复权',none:'不复权'}[nt.adjustment]||nt.adjustment;
    var html='<h3>技术结构</h3><div class="tl-summary">'+esc(nt.timeframe)+' · '+esc(adj)+' · 截止 '+esc(nt.as_of_date)+'</div>';
    (ctx.summary_lines||[]).forEach(function(line){html+='<div class="tl-item"><div><div class="tl-title">'+esc(line)+'</div></div></div>';});
    html+='<div class="tl-section"><h4>结构数量</h4><div class="tl-meta">Pivot '+(nt.pivots||[]).length+' · 水平位 '+(nt.horizontal_levels||[]).length+' · 趋势线 '+(nt.trendlines||[]).length+' · 通道 '+(nt.channels||[]).length+'</div></div>';
    if((nt.data_quality_flags||[]).length)html+='<div class="tl-note">数据质量：'+esc(nt.data_quality_flags.join('、'))+'</div>';
    else html+='<div class="tl-note">结构线只描述历史价格关系，不预测突破方向。</div>';
    el.innerHTML=close+html;return;
  }
  var t=d.trendlines;if(!t||!t.latest){el.innerHTML=close+'<div class="tl-empty">暂无画线结果</div>';return;}
  var html='<h3>画线结构</h3><div class="tl-summary">最新 '+esc(t.latest.date)+' · 收盘 '+Number(t.latest.close||0).toFixed(2)+'</div>';
  function section(title,items){
    if(!items.length)return '';
    return '<div class="tl-section"><h4>'+esc(title)+'</h4>'+items.join('')+'</div>';
  }
  var trend=[];
  (t.uptrend_lines||[]).forEach(function(line,i){trend.push(panelItem('Uptrend Line '+(i+1),lineMeta(line),'#8b5cf6'));});
  (t.downtrend_lines||[]).forEach(function(line,i){trend.push(panelItem('Downtrend Line '+(i+1),lineMeta(line),'#0ea5e9'));});
  (t.channels||[]).forEach(function(ch,i){if(ch.parallel_line){trend.push(panelItem((ch.parallel_line.label||'Channel')+' '+(i+1),lineMeta(ch.parallel_line),'#64748b'));}});
  var levels=[];
  (t.support||[]).forEach(function(level,i){levels.push(panelItem('Support '+(i+1),levelMeta(level),'#16a34a'));});
  (t.resistance||[]).forEach(function(level,i){levels.push(panelItem('Resistance '+(i+1),levelMeta(level),'#dc2626'));});
  var neck=[];
  (t.necklines||[]).forEach(function(n,i){if(n.line){neck.push(panelItem('Neckline: '+n.pattern_type,lineMeta(n.line)+' · '+(n.breakout_status||''),'#f97316'));}});
  html+=section('趋势 / 通道',trend)+section('支撑 / 压力',levels)+section('颈线候选',neck);
  if(!trend.length&&!levels.length&&!neck.length)html+='<div class="tl-empty">暂无有效结构线</div>';
  html+='<div class="tl-note">图上仅显示最近/最重要的少量线，完整候选保留在此列表。</div>';
  el.innerHTML=close+html;
}

// ---- Manual drawing ----
var DRAW={tool:null,pending:null,dragging:false};
var DRAW_LABEL={trend:'趋势线',support:'支撑线',resistance:'阻力线'};
var DRAW_COLOR={trend:'#2563eb',support:'#16a34a',resistance:'#dc2626'};
function activePeriodSection(){return document.querySelector('.period-section.active');}
function activeKlineChart(){
  var sec=activePeriodSection();if(!sec)return null;
  var dom=sec.querySelector('[id^="k-"]');if(!dom)return null;
  for(var i=0;i<ALL.length;i++){if(ALL[i].getDom&&ALL[i].getDom()===dom)return ALL[i];}
  return null;
}
function drawStorageKey(chart){
  return 'quantyb.manual-draw.v1.'+(chart._manualSymbol||'')+'.'+(chart._manualPeriod||'');
}
function loadManualLines(chart){
  if(chart._manualLines)return chart._manualLines;
  try{chart._manualLines=JSON.parse(localStorage.getItem(drawStorageKey(chart))||'[]')||[];}catch(e){chart._manualLines=[];}
  return chart._manualLines;
}
function saveManualLines(chart){
  try{localStorage.setItem(drawStorageKey(chart),JSON.stringify(chart._manualLines||[]));}catch(e){}
}
function manualStatus(text){
  var el=document.getElementById('manual-status');
  if(el)el.textContent=text||'选择画线工具后，在当前 K 线图上点击画线。';
}
function setManualTool(tool){
  DRAW.tool=tool||null;DRAW.pending=null;
  document.querySelectorAll('.manual-tool-btn[data-tool]').forEach(function(btn){
    btn.classList.toggle('active',btn.getAttribute('data-tool')===DRAW.tool);
  });
  if(!DRAW.tool)manualStatus('已取消画线。');
  else if(DRAW.tool==='trend')manualStatus('趋势线：请在 K 线图上依次点击两个点。');
  else manualStatus(DRAW_LABEL[DRAW.tool]+'：请在 K 线图上点击一个价位。');
}
function manualPointFromEvent(chart,ev){
  var p=[ev.offsetX,ev.offsetY];
  return manualPointFromPixel(chart,p);
}
function manualPointFromPixel(chart,p){
  var coord=chart.convertFromPixel({gridIndex:0},p);
  if(!coord||coord.length<2)return null;
  var rawX=coord[0],idx;
  if(typeof rawX==='number')idx=Math.round(rawX);
  else idx=(chart._manualDates||[]).indexOf(String(rawX));
  var dates=chart._manualDates||[];
  if(idx<0)idx=0;if(idx>=dates.length)idx=dates.length-1;
  var price=Number(coord[1]);
  if(!isFinite(price))return null;
  return {index:idx,date:dates[idx],price:Number(price.toFixed(3))};
}
function manualPixelFromPoint(chart,point){
  if(!chart||!point||point.date==null||point.price==null)return null;
  var pixel=chart.convertToPixel({gridIndex:0},[point.date,Number(point.price)]);
  if(!pixel||pixel.length<2||!isFinite(pixel[0])||!isFinite(pixel[1]))return null;
  return [Number(pixel[0]),Number(pixel[1])];
}
function manualRightEdgeDate(chart){
  var dates=chart._manualDates||[];
  if(!dates.length)return '';
  try{
    var opt=chart.getOption()||{},dz=(opt.dataZoom||[])[0]||{},idx=dates.length-1;
    if(dz.endValue!=null){
      if(typeof dz.endValue==='number')idx=Math.round(dz.endValue);
      else{var found=dates.indexOf(String(dz.endValue));if(found>=0)idx=found;}
    }else if(dz.end!=null){
      idx=Math.round((Number(dz.end)||100)/100*(dates.length-1));
    }
    if(idx<0)idx=0;if(idx>=dates.length)idx=dates.length-1;
    return dates[idx];
  }catch(e){return dates[dates.length-1];}
}
function manualSeries(line,chart){
  var dates=chart._manualDates||[],data=[];
  var color=DRAW_COLOR[line.type]||'#2563eb';
  var label=DRAW_LABEL[line.type]||'手动画线';
  var isHorizontal=line.type==='support'||line.type==='resistance';
  if(line.type==='trend'){
    var p1=line.p1||{},p2=line.p2||{};
    var i1=Number(p1.index),i2=Number(p2.index);
    var y1=Number(p1.price),y2=Number(p2.price);
    if(!isFinite(i1)||!isFinite(i2)||!isFinite(y1)||!isFinite(y2)||i1===i2){
      data=[[p1.date,y1],[p2.date,y2]];
    }else{
      var slope=(y2-y1)/(i2-i1);
      var startIndex=Math.min(i1,i2);
      data=dates.map(function(date,idx){return idx<startIndex?[date,null]:[date,Number((y1+slope*(idx-i1)).toFixed(3))];});
    }
    return {id:'manual-'+line.id,name:label,type:'line',data:data,manualDrawLine:true,
      symbol:'circle',symbolSize:6,z:30,silent:false,clip:false,
      lineStyle:{color:color,width:2.2,type:'solid',opacity:.98},
      endLabel:{show:true,formatter:function(p){var v=p&&p.value?p.value[1]:null;return label+(v==null?'':' '+Number(v).toFixed(2));},color:color,fontSize:11,fontWeight:'bold'},
    tooltip:{formatter:function(){return label+'<br/>'+p1.date+' '+p1.price+' → '+p2.date+' '+p2.price+'<br/>已延伸到右侧最新日期';}}};
  }
  data=dates.map(function(date){return [date,Number(line.price)];});
  var lineType=line.type==='support'?'dashed':(line.type==='resistance'?'dashed':'solid');
  return {id:'manual-'+line.id,name:label,type:'line',data:data,manualDrawLine:true,
    symbol:'none',z:28,silent:false,clip:false,
    lineStyle:{color:color,width:2.4,type:lineType,opacity:.98},
    endLabel:{show:true,formatter:function(){return label+' '+Number(line.price).toFixed(2);},color:color,fontSize:11,fontWeight:'bold',distance:8},
    markLine:{silent:false,symbol:'none',precision:3,label:{show:false},lineStyle:{color:color,width:2.4,type:lineType,opacity:.98},data:[{yAxis:Number(line.price)}]},
    tooltip:{formatter:function(){return label+'<br/>价位: '+Number(line.price).toFixed(3);}}};
}
function manualSeriesList(chart){
  return loadManualLines(chart).map(function(line){return manualSeries(line,chart);});
}
function renderManualSeriesOnly(chart){
  if(!chart||!chart._manualBaseSeries)return;
  chart.setOption({series:(chart._manualBaseSeries||[]).concat(manualSeriesList(chart))},{replaceMerge:['series']});
}
function updateManualTrendPoint(chart,lineId,which,pixel){
  var point=manualPointFromPixel(chart,pixel);if(!point)return false;
  var lines=loadManualLines(chart),changed=false;
  lines.forEach(function(line){
    if(line.id===lineId&&line.type==='trend'){line[which]=point;changed=true;}
  });
  if(changed){chart._manualLines=lines;saveManualLines(chart);renderManualSeriesOnly(chart);}
  return changed;
}
function updateManualHorizontalPrice(chart,lineId,pixel){
  var coord=chart.convertFromPixel({gridIndex:0},pixel);
  if(!coord||coord.length<2||!isFinite(Number(coord[1])))return false;
  var price=Number(Number(coord[1]).toFixed(3));
  var lines=loadManualLines(chart),changed=false;
  lines.forEach(function(line){
    if(line.id===lineId&&(line.type==='support'||line.type==='resistance')){line.price=price;changed=true;}
  });
  if(changed){chart._manualLines=lines;saveManualLines(chart);renderManualSeriesOnly(chart);}
  return changed;
}
function manualHandleStyle(color){
  return {fill:color,stroke:'#fff',lineWidth:2,shadowBlur:8,shadowColor:'rgba(15,23,42,.18)'};
}
function manualHandleTooltip(text){
  return {show:true,formatter:text,backgroundColor:'rgba(15,23,42,.9)',borderWidth:0,textStyle:{color:'#fff',fontSize:12}};
}
function manualGraphicHandle(chart,line,which,point,label,color){
  var pos=manualPixelFromPoint(chart,point);if(!pos)return null;
  return {id:'manual-handle-'+line.id+'-'+which,type:'circle',position:pos,shape:{r:7},draggable:true,
    cursor:'move',z:120,style:manualHandleStyle(color),tooltip:manualHandleTooltip(label+'：拖动调整位置'),
    ondragstart:function(){DRAW.dragging=true;},
    ondrag:function(){updateManualTrendPoint(chart,line.id,which,this.position);},
    ondragend:function(){updateManualTrendPoint(chart,line.id,which,this.position);renderManualLines(chart);setTimeout(function(){DRAW.dragging=false;},0);},
    onclick:function(){DRAW.dragging=true;setTimeout(function(){DRAW.dragging=false;},0);}
  };
}
function manualHorizontalHandle(chart,line,label,color){
  var date=manualRightEdgeDate(chart);
  var pos=manualPixelFromPoint(chart,{date:date,price:line.price});if(!pos)return null;
  return {id:'manual-handle-'+line.id+'-price',type:'circle',position:pos,shape:{r:7},draggable:true,
    cursor:'ns-resize',z:120,style:manualHandleStyle(color),tooltip:manualHandleTooltip(label+'：上下拖动调整价位'),
    ondragstart:function(){DRAW.dragging=true;},
    ondrag:function(){updateManualHorizontalPrice(chart,line.id,this.position);},
    ondragend:function(){updateManualHorizontalPrice(chart,line.id,this.position);renderManualLines(chart);setTimeout(function(){DRAW.dragging=false;},0);},
    onclick:function(){DRAW.dragging=true;setTimeout(function(){DRAW.dragging=false;},0);}
  };
}
function manualGraphics(chart){
  var graphics=[];
  loadManualLines(chart).forEach(function(line){
    var color=DRAW_COLOR[line.type]||'#2563eb';
    var label=DRAW_LABEL[line.type]||'手动画线';
    if(line.type==='trend'){
      var p1=manualGraphicHandle(chart,line,'p1',line.p1,label+'起点',color);
      var p2=manualGraphicHandle(chart,line,'p2',line.p2,label+'终点',color);
      if(p1)graphics.push(p1);if(p2)graphics.push(p2);
    }else if(line.type==='support'||line.type==='resistance'){
      var h=manualHorizontalHandle(chart,line,label,color);
      if(h)graphics.push(h);
    }
  });
  return graphics;
}
function renderManualLines(chart){
  if(!chart||!chart._manualBaseSeries)return;
  chart.setOption({series:(chart._manualBaseSeries||[]).concat(manualSeriesList(chart)),graphic:manualGraphics(chart)},{replaceMerge:['series','graphic']});
}
function addManualLine(chart,line){
  var lines=loadManualLines(chart);
  lines.push(line);chart._manualLines=lines;saveManualLines(chart);renderManualLines(chart);
}
function bindManualDrawing(chart,d,period){
  chart._manualSymbol=d.symbol||'';chart._manualPeriod=period;chart._manualDates=d.dates||[];
  chart._manualBaseSeries=(chart.getOption().series||[]).map(function(s){return s;});
  chart._manualLines=null;renderManualLines(chart);
  if(!chart._manualDrawingBound){
    chart._manualDrawingBound=true;
    chart.on('dataZoom',function(){setTimeout(function(){renderManualLines(chart);},0);});
  }
  chart.getZr().on('click',function(ev){
    if(!DRAW.tool||DRAW.dragging)return;
    var point=manualPointFromEvent(chart,ev);if(!point)return;
    var id=Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,7);
    if(DRAW.tool==='trend'){
      if(!DRAW.pending){DRAW.pending=point;manualStatus('趋势线：已选择第一个点 '+point.date+' / '+point.price+'，请点击第二个点。');return;}
      addManualLine(chart,{id:id,type:'trend',p1:DRAW.pending,p2:point});
      DRAW.pending=null;manualStatus('趋势线已添加。拖动两个圆点可调整两端，或继续点击两个点画下一条。');
    }else if(DRAW.tool==='support'||DRAW.tool==='resistance'){
      addManualLine(chart,{id:id,type:DRAW.tool,price:point.price,date:point.date});
      manualStatus(DRAW_LABEL[DRAW.tool]+'已添加：'+point.price+'。拖动右侧圆点可上下调整价位。');
    }
  });
}
function manualUndo(){
  var chart=activeKlineChart();if(!chart)return;
  var lines=loadManualLines(chart);lines.pop();chart._manualLines=lines;saveManualLines(chart);renderManualLines(chart);
  manualStatus('已撤销当前周期最后一条手动画线。');
}
function manualClear(){
  var chart=activeKlineChart();if(!chart)return;
  if(!confirm('清空当前周期的全部手动画线？'))return;
  chart._manualLines=[];saveManualLines(chart);renderManualLines(chart);manualStatus('当前周期手动画线已清空。');
}
window.setManualTool=setManualTool;
window.manualUndo=manualUndo;
window.manualClear=manualClear;

function kline(dom,d){
  var vs=Math.max(70,100-Math.max(30,100*90/Math.max(d.dates.length,1)));
  var mk=[];
  (d.trades.buy||[]).forEach(function(t){mk.push({name:'买入',coord:[t[0],t[1]],value:'买入',symbol:'triangle',symbolSize:26,itemStyle:{color:C.up,borderColor:'#fff',borderWidth:3},label:{show:true,position:'top',fontSize:11,fontWeight:'bold',color:C.up,distance:8}});});
  (d.trades.sell||[]).forEach(function(t){mk.push({name:'卖出',coord:[t[0],t[1]],value:'卖出',symbol:'triangle',symbolSize:26,symbolRotate:180,itemStyle:{color:C.dn,borderColor:'#fff',borderWidth:3},label:{show:true,position:'bottom',fontSize:11,fontWeight:'bold',color:C.dn,distance:8}});});
  var se=[{name:'K线',type:'candlestick',data:d.ohlc,markPoint:{data:mk},itemStyle:{color:C.up,color0:C.dn,borderColor:C.up,borderColor0:C.dn},barMaxWidth:'60%',barMinWidth:3}];
  var lgD=['K线'];
  var structureLegend=[];
  var lgS={};
  [{d:d.ma5,n:'MA5'},{d:d.ma10,n:'MA10'},{d:d.ma20,n:'MA20'},{d:d.ma60,n:'MA60'}].forEach(function(m,i){
    if(m.d&&m.d.length){se.push({name:m.n,type:'line',data:m.d,smooth:true,symbol:'none',lineStyle:{color:C.ma[i],width:1.5,opacity:0.7}});lgD.push(m.n);}
  });
  if(!d.manualDrawing)addTrendlineOverlays(se,structureLegend,lgS,d);
  if(d.diagnostics){
    if(d.diagnostics.dailyEma50&&d.diagnostics.dailyEma50.length){var emaName=d.diagnostics.dailyEmaLabel||'EMA50(日线)';se.push({name:emaName,type:'line',data:d.diagnostics.dailyEma50,smooth:true,symbol:'none',lineStyle:{color:'#0ea5e9',width:1.8,type:'dashed',opacity:.85},connectNulls:true});lgD.push(emaName);}
    if(d.diagnostics.weeklyEmaFast&&d.diagnostics.weeklyEmaFast.length){var wfName=d.diagnostics.weeklyEmaFastLabel||'周EMA快';se.push({name:wfName,type:'line',data:d.diagnostics.weeklyEmaFast,smooth:true,symbol:'none',lineStyle:{color:'#f97316',width:2,opacity:.9},connectNulls:true});lgD.push(wfName);}
    if(d.diagnostics.weeklyEmaSlow&&d.diagnostics.weeklyEmaSlow.length){var wsName=d.diagnostics.weeklyEmaSlowLabel||'周EMA慢';se.push({name:wsName,type:'line',data:d.diagnostics.weeklyEmaSlow,smooth:true,symbol:'none',lineStyle:{color:'#334155',width:2,opacity:.85},connectNulls:true});lgD.push(wsName);}
    if(d.diagnostics.initialStop&&d.diagnostics.initialStop.length){se.push({name:'初始止损',type:'line',data:d.diagnostics.initialStop,smooth:false,symbol:'none',lineStyle:{color:'#ef4444',width:1.4,type:'dashed'},connectNulls:false});lgD.push('初始止损');}
    if(d.diagnostics.trailingStop&&d.diagnostics.trailingStop.length){se.push({name:'跟踪止损',type:'line',data:d.diagnostics.trailingStop,smooth:false,symbol:'none',lineStyle:{color:'#0f766e',width:1.4,type:'dashed'},connectNulls:false});lgD.push('跟踪止损');}
    [
      {name:'回调',data:d.diagnostics.pullback,symbol:'circle',size:9,color:'#5470c6'},
      {name:'突破',data:d.diagnostics.breakout,symbol:'diamond',size:11,color:'#e8a020'},
      {name:'买入设置',data:d.diagnostics.setup,symbol:'pin',size:18,color:'#a855f7'},
      {name:'放量滞涨',data:d.diagnostics.stalling,symbol:'rect',size:13,color:'#f97316',label:'滞涨'}
    ].forEach(function(m){
      if(m.data&&m.data.length){se.push(diagSeries(m.name,m.data,m.symbol,m.size,m.color,m.label));lgD.push(m.name);lgS[m.name]=false;}
    });
  }
  var legends=[lg(lgD,{})];
  if(structureLegend.length)legends.push({show:false,data:structureLegend,selected:lgS});
  var chart=ch(dom,{backgroundColor:C.bg,title:ti(d.title),grid:grid(92,76),xAxis:ax(d.dates),yAxis:ya(),legend:legends,tooltip:tl(),dataZoom:dz(vs),toolbox:tb(),series:se});
  if(d.manualDrawing)bindManualDrawing(chart,d,dom.replace(/^k-/,''));
  return chart;
}

// ---- Volume ----
function volume(dom,d){
  var vs=Math.max(70,100-Math.max(30,100*90/Math.max(d.dates.length,1)));
  var uv=[],dv=[];
  d.ohlc.forEach(function(o,i){var v=d.volume[i]||0;if(o[1]>=o[0]){uv.push(v||0.01);dv.push(0);}else{uv.push(0);dv.push(v||0.01);}});
  return ch(dom,{backgroundColor:C.bg,title:ti('成交量'),grid:grid(72,72),xAxis:ax(d.dates,false),yAxis:ya({name:'成交量'}),legend:lg([]),tooltip:tl(),dataZoom:dz(vs),series:[{name:'',type:'bar',data:uv,stack:'_v',itemStyle:{color:C.up}},{name:'',type:'bar',data:dv,stack:'_v',itemStyle:{color:C.dn}}]});
}

// ---- MACD ----
function macd(dom,d){
  var vs=Math.max(70,100-Math.max(30,100*90/Math.max(d.dates.length,1)));
  return ch(dom,{backgroundColor:C.bg,title:ti('MACD (12, 26, 9)'),grid:grid(72,72),xAxis:ax(d.dates,false),yAxis:ya(),legend:lg(['DIF','DEA','MACD']),tooltip:tl(),dataZoom:dz(vs),series:[{name:'DIF',type:'line',data:d.macd.dif,smooth:true,symbol:'none',lineStyle:{color:C.bl,width:1.8},connectNulls:true},{name:'DEA',type:'line',data:d.macd.dea,smooth:true,symbol:'none',lineStyle:{color:C.or,width:1.8},connectNulls:true},{name:'MACD',type:'line',data:d.macd.hist,areaStyle:{opacity:0.1},lineStyle:{color:C.up,width:1},connectNulls:true}]});
}

// ---- KDJ ----
function kdj(dom,d){
  var vs=Math.max(70,100-Math.max(30,100*90/Math.max(d.dates.length,1)));
  return ch(dom,{backgroundColor:C.bg,title:ti('KDJ (9, 3, 3)'),grid:grid(72,72),xAxis:ax(d.dates,false),yAxis:ya(),legend:lg(['K','D','J']),tooltip:tl(),dataZoom:dz(vs),series:[{name:'K',type:'line',data:d.kdj.k,smooth:true,symbol:'none',lineStyle:{color:C.bl,width:1.8},connectNulls:true},{name:'D',type:'line',data:d.kdj.d,smooth:true,symbol:'none',lineStyle:{color:C.or,width:1.8},connectNulls:true},{name:'J',type:'line',data:d.kdj.j,smooth:true,symbol:'none',lineStyle:{color:C.jr,width:1.2,opacity:0.7},connectNulls:true}]});
}

// ---- RSI ----
function rsi(dom,d){
  var vs=Math.max(70,100-Math.max(30,100*90/Math.max(d.dates.length,1)));
  var len=d.dates.length,f30=Array(len).fill(30),f70=Array(len).fill(70);
  return ch(dom,{backgroundColor:C.bg,title:ti('RSI (14)'),grid:grid(72,72),xAxis:ax(d.dates,false),yAxis:ya({min:0,max:100}),legend:lg(['RSI','超卖线(30)','超买线(70)']),tooltip:tl(),dataZoom:dz(vs),series:[{name:'RSI',type:'line',data:d.rsi,smooth:true,symbol:'none',lineStyle:{color:C.bl,width:2},connectNulls:true},{name:'超卖线(30)',type:'line',data:f30,smooth:false,symbol:'none',lineStyle:{color:C.dn,width:1,type:'dashed',opacity:0.5}},{name:'超买线(70)',type:'line',data:f70,smooth:false,symbol:'none',lineStyle:{color:C.up,width:1,type:'dashed',opacity:0.5}}]});
}

// ---- Equity ----
function equity(dom,d){
  if(!d)return null;
  var vs=Math.max(70,100-Math.max(30,100*90/Math.max(d.dates.length,1)));
  var eq=ch(dom,{backgroundColor:C.bg,title:ti('权益曲线 & 回撤'),grid:grid(76,76),xAxis:ax(d.dates),yAxis:[ya({name:'权益 (元)'}),{type:'value',name:'回撤 %',axisLabel:{fontSize:10,color:C.lb,formatter:'{value}%'},splitLine:{show:false},nameTextStyle:{color:C.lb}}],legend:lg(['权益曲线','回撤']),tooltip:tl(),dataZoom:dz(vs),toolbox:tb(),series:[{name:'权益曲线',type:'line',data:d.equity,yAxisIndex:0,smooth:true,symbol:'none',lineStyle:{color:C.bl,width:2.5},areaStyle:{opacity:0.08,color:C.bl}},{name:'回撤',type:'line',data:d.drawdowns,yAxisIndex:1,smooth:true,symbol:'none',lineStyle:{color:C.up,width:1.5},areaStyle:{opacity:0.1,color:C.up}}]});
  return eq;
}

// ---- Bootstrap ----
function initAll(){
  if(window._D){
    ['daily','weekly','monthly'].forEach(function(pk){
      var p=window._D[pk];if(!p)return;
      kline('k-'+pk,p);volume('vol-'+pk,p);macd('macd-'+pk,p);kdj('kdj-'+pk,p);rsi('rsi-'+pk,p);
    });
  }
  if(window._E){equity('equity',window._E);}
  ALL.forEach(function(c){c.group='qg';});
  echarts.connect('qg');
  window._ALL=ALL;
}

// ---- Tab: period switch ----
function switchPeriod(targetId){
  document.querySelectorAll('.period-tab-btn').forEach(function(b){b.classList.remove('active');});
  document.querySelectorAll('.period-section').forEach(function(s){s.classList.remove('active');});
  var btn=document.querySelector('[data-target="'+targetId+'"]');
  if(btn)btn.classList.add('active');
  var sec=document.getElementById(targetId);
  if(sec){sec.classList.add('active');resizeIn(sec);}
}
function resizeIn(container){
  setTimeout(function(){
    ALL.forEach(function(c){
      try{
        var d=c.getDom();
        if(d&&container.contains(d)){
          c.resize();
          if(c._manualBaseSeries)renderManualLines(c);
        }
      }catch(e){}
    });
  },80);
}

// ---- Tab: indicator switch (scoped to period section) ----
function switchIndicator(btn,targetId){
  var section=btn.closest('.period-section');
  section.querySelectorAll('.tab-btn').forEach(function(b){b.classList.remove('active');});
  section.querySelectorAll('.indicator-panel').forEach(function(p){p.classList.remove('active');});
  btn.classList.add('active');
  var panel=document.getElementById(targetId);
  if(panel){panel.classList.add('active');resizeIn(panel);}
}

window.switchPeriod=switchPeriod;
window.switchIndicator=switchIndicator;
window.toggleTechnicalStructure=function(input){
  var kind=input.getAttribute('data-kind'),checked=!!input.checked;
  ALL.forEach(function(chart){
    try{(chart.getOption().series||[]).forEach(function(series){
      var matched=kind==='inactive'?(series.technicalStructureStatus&&series.technicalStructureStatus!=='active'&&series.technicalStructureStatus!=='role_reversal'):(series.technicalStructureKind===kind);
      if(matched&&series.name)chart.dispatchAction({type:checked?'legendSelect':'legendUnSelect',name:series.name});
    });}catch(e){}
  });
};
document.addEventListener('keydown',function(ev){if(ev.key==='Escape')setManualTool(null);});
window.addEventListener('resize',function(){
  setTimeout(function(){
    ALL.forEach(function(c){try{c.resize();if(c._manualBaseSeries)renderManualLines(c);}catch(e){}});
  },80);
});
window.addEventListener('DOMContentLoaded',initAll);
})();
</script>"""


# ============================================================
#  HTML 页面拼装
# ============================================================

_CSS = """* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
    background: #f0f2f5; color: #333; line-height: 1.6;
    -webkit-font-smoothing: antialiased;
}
.container { max-width: 1840px; margin: 0 auto; padding: 28px 24px; }

.topbar {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 28px; padding-bottom: 16px;
    border-bottom: 1px solid #e0e0e8;
}
.topbar-left { display: flex; align-items: baseline; gap: 14px; }
.topbar-left h1 { font-size: 24px; font-weight: 700; color: #1a1a2e; letter-spacing: .2px; }
.topbar-left h1 span { color: #5470c6; }
.topbar-left .code-tag {
    font-size: 12px; font-weight: 600; color: #5470c6;
    background: #eef1fb; padding: 4px 14px; border-radius: 4px; letter-spacing: .5px;
}
.topbar-right { font-size: 11px; color: #bbb; letter-spacing: .4px; }

.stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
    gap: 10px; margin-bottom: 28px;
}
.stat-card {
    background: #fff; border: 1px solid #eaeaef;
    border-radius: 8px; padding: 18px 22px;
    transition: box-shadow .2s, transform .2s;
}
.stat-card:hover { box-shadow: 0 3px 12px rgba(0,0,0,0.08); transform: translateY(-1px); }
.stat-label {
    font-size: 10px; color: #999; text-transform: uppercase;
    letter-spacing: 1px; margin-bottom: 8px; font-weight: 600;
}
.stat-value { font-size: 26px; font-weight: 700; color: #1a1a2e; letter-spacing: -.4px; line-height: 1; }
.stat-value.up { color: #ef5350; }
.stat-value.down { color: #26a69a; }

.diagnostic-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 10px; margin: -12px 0 28px;
}
.diagnostic-card {
    background: #fff; border: 1px solid #eaeaef;
    border-radius: 8px; padding: 14px 18px;
}
.diagnostic-card span {
    display: block; color: #999; font-size: 10px;
    text-transform: uppercase; letter-spacing: .8px; margin-bottom: 6px;
}
.diagnostic-card strong { color: #1a1a2e; font-size: 20px; }

.chart-section {
    background: #fff; border: 1px solid #eaeaef;
    border-radius: 8px; padding: 0; margin-bottom: 0;
    overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,0.03);
}
.chart-section.chart-section--equity { margin-top: 28px; }
.chart-section .chart-container { width: 100% !important; height: 480px; }
.chart-section .chart-container.ht-300 { height: 300px; }
.chart-section .chart-container.ht-350 { height: 350px; }
.chart-section .chart-container.ht-500 { height: 500px; }
.chart-section .chart-container.ht-720 { height: min(76vh, 760px); min-height: 640px; }
.chart-section .chart-container.ht-520 { height: 520px; }

.kline-layout {
    display: block;
}
.kline-layout .chart-section { min-width: 0; }
.kline-chart-card { border-radius: 10px; }

.period-tabs { display: flex; gap: 20px; margin-top: 28px; border-bottom: 2px solid #eaeaef; padding: 0; }
.technical-controls {
    display:flex; flex-wrap:wrap; align-items:center; gap:12px;
    margin:12px 0 10px; color:#64748b; font-size:12px;
}
.manual-drawing-toolbar {
    display:flex; flex-wrap:wrap; align-items:center; gap:8px;
    margin:12px 0 12px; padding:10px 12px;
    background:#fff; border:1px solid #dce5f2; border-radius:12px;
    box-shadow:0 1px 4px rgba(15,23,42,.04);
}
.manual-toolbar-label {
    font-size:12px; color:#334155; font-weight:800; margin-right:4px;
}
.manual-tool-btn {
    height:32px; border:1px solid #d6dfef; background:#f8fafc;
    color:#334155; border-radius:999px; padding:0 12px;
    cursor:pointer; font-size:12px; font-weight:750; font-family:inherit;
}
.manual-tool-btn:hover { color:#3157c8; border-color:#b9c7f0; background:#fff; }
.manual-tool-btn.active {
    color:#fff; background:#5470c6; border-color:#5470c6;
    box-shadow:0 6px 14px rgba(84,112,198,.22);
}
.manual-tool-btn.danger:hover { color:#dc2626; border-color:#fecaca; }
.manual-status {
    color:#8a97ad; font-size:12px; margin-left:4px;
}
.period-tab-btn {
    padding: 10px 28px; border: none; background: none;
    cursor: pointer; font-size: 14px; font-weight: 600;
    color: #999; letter-spacing: .5px;
    transition: color .2s; font-family: inherit; outline: none; position: relative;
}
.period-tab-btn::after {
    content: ''; position: absolute; bottom: -2px; left: 0; right: 0;
    height: 2px; background: #5470c6; transform: scaleX(0); transition: transform .2s;
}
.period-tab-btn:hover { color: #555; }
.period-tab-btn.active { color: #1a1a2e; }
.period-tab-btn.active::after { transform: scaleX(1); }
.period-section { display: none; }
.period-section.active { display: block; }
.period-section .indicator-tabs { margin-top: 28px; }

.indicator-tabs { display: flex; gap: 0; margin-top: 28px; border-bottom: 1px solid #eaeaef; padding: 0; }
.tab-btn {
    padding: 10px 24px; border: none; background: none;
    cursor: pointer; font-size: 13px; font-weight: 500;
    color: #999; letter-spacing: .3px;
    transition: color .2s; font-family: inherit; outline: none; position: relative;
}
.tab-btn::after {
    content: ''; position: absolute; bottom: -1px; left: 0; right: 0;
    height: 2px; background: #5470c6; transform: scaleX(0); transition: transform .2s;
}
.tab-btn:hover { color: #555; }
.tab-btn.active { color: #1a1a2e; }
.tab-btn.active::after { transform: scaleX(1); }
.indicator-panel { display: none; }
.indicator-panel.active { display: block; }
.indicator-panel .chart-section { border-top: none; border-radius: 0 0 8px 8px; }

.footer { text-align: center; color: #ccc; font-size: 10px; padding: 36px 0 8px; letter-spacing: .4px; }

@keyframes fadeUp {
    from { opacity: 0; transform: translateY(12px); }
    to   { opacity: 1; transform: translateY(0); }
}
.stat-card, .chart-section { animation: fadeUp .4s ease both; }
.stat-card:nth-child(1) { animation-delay: .02s; }
.stat-card:nth-child(2) { animation-delay: .05s; }
.stat-card:nth-child(3) { animation-delay: .08s; }
.stat-card:nth-child(4) { animation-delay: .11s; }
.stat-card:nth-child(5) { animation-delay: .14s; }
.stat-card:nth-child(6) { animation-delay: .17s; }

@media (max-width: 1100px) {
    .container { padding: 20px 12px; }
    .chart-section .chart-container.ht-720 { height: 620px; min-height: 560px; }
    .manual-status { flex-basis:100%; margin-left:0; }
}
"""


def _build_page(symbol: str, strategy_name: str, stats: dict,
                period_data_json: str, equity_data_json: str,
                diagnostic_html: str = "") -> str:
    """组装完整 HTML 页面。period_data_json 和 equity_data_json 是预序列化的 JSON 字符串。"""
    stats_html = _build_stats_html(stats)
    display_name = _STRAT_NAMES.get(strategy_name, strategy_name)
    manual_drawing_mode = strategy_name == "trendlines"
    heading_text = "手动画线" if manual_drawing_mode else "回测报告"

    period_tab_btns = (
        '<button class="period-tab-btn active" data-target="period-daily" '
        'onclick="switchPeriod(\'period-daily\')">日K</button>'
        '<button class="period-tab-btn" data-target="period-weekly" '
        'onclick="switchPeriod(\'period-weekly\')">周K</button>'
        '<button class="period-tab-btn" data-target="period-monthly" '
        'onclick="switchPeriod(\'period-monthly\')">月K</button>'
    )

    # 三个周期的 section
    period_sections: list[str] = []
    for pid, pname in [("daily", "日K"), ("weekly", "周K"), ("monthly", "月K")]:
        active = ' active' if pid == "daily" else ""
        period_sections.append(f"""<div id="period-{pid}" class="period-section{active}">
    <div class="kline-layout">
        <div class="chart-section kline-chart-card"><div id="k-{pid}" class="chart-container ht-720"></div></div>
    </div>
    <div class="indicator-tabs">
        <button class="tab-btn active" data-target="panel-volume-{pid}" onclick="switchIndicator(this,'panel-volume-{pid}')">成交量</button>
        <button class="tab-btn" data-target="panel-macd-{pid}" onclick="switchIndicator(this,'panel-macd-{pid}')">MACD</button>
        <button class="tab-btn" data-target="panel-kdj-{pid}" onclick="switchIndicator(this,'panel-kdj-{pid}')">KDJ</button>
        <button class="tab-btn" data-target="panel-rsi-{pid}" onclick="switchIndicator(this,'panel-rsi-{pid}')">RSI</button>
    </div>
    <div id="panel-volume-{pid}" class="indicator-panel active"><div class="chart-section"><div id="vol-{pid}" class="chart-container ht-300"></div></div></div>
    <div id="panel-macd-{pid}" class="indicator-panel"><div class="chart-section"><div id="macd-{pid}" class="chart-container ht-350"></div></div></div>
    <div id="panel-kdj-{pid}" class="indicator-panel"><div class="chart-section"><div id="kdj-{pid}" class="chart-container ht-350"></div></div></div>
    <div id="panel-rsi-{pid}" class="indicator-panel"><div class="chart-section"><div id="rsi-{pid}" class="chart-container ht-300"></div></div></div>
</div>""")

    equity_section = ""
    if equity_data_json and equity_data_json != "null":
        equity_section = '<div class="chart-section chart-section--equity"><div id="equity" class="chart-container ht-520"></div></div>'

    manual_toolbar = ""
    if manual_drawing_mode:
        manual_toolbar = """
    <div class="manual-drawing-toolbar">
      <span class="manual-toolbar-label">画线工具</span>
      <button class="manual-tool-btn" data-tool="trend" type="button" onclick="setManualTool('trend')">趋势线</button>
      <button class="manual-tool-btn" data-tool="support" type="button" onclick="setManualTool('support')">支撑线</button>
      <button class="manual-tool-btn" data-tool="resistance" type="button" onclick="setManualTool('resistance')">阻力线</button>
      <button class="manual-tool-btn" type="button" onclick="setManualTool(null)">取消</button>
      <button class="manual-tool-btn" type="button" onclick="manualUndo()">撤销</button>
      <button class="manual-tool-btn danger" type="button" onclick="manualClear()">清空当前周期</button>
      <span id="manual-status" class="manual-status">选择工具后在 K 线图点击画线；画完拖动圆点调整，水平线拖右侧点上下移动。</span>
    </div>
        """

    body = f"""<div class="container">
    <div class="topbar">
        <div class="topbar-left">
            <h1><span>{symbol}</span> {heading_text}</h1>
            <span class="code-tag">{display_name}</span>
        </div>
        <div class="topbar-right">QuantYB</div>
    </div>
    <div class="stats-grid">{stats_html}</div>
    {diagnostic_html}
    <div class="period-tabs">{period_tab_btns}</div>
    {manual_toolbar}
    {"".join(period_sections)}
    {equity_section}
    <div class="footer">QuantYB &copy; 2026 &nbsp;&middot;&nbsp; A-Share Quantitative Backtesting System</div>
</div>"""
    scripts = f"{inline_script(f'window._D={period_data_json};window._E={equity_data_json};')}\n{_CHART_JS}"
    return html_document(
        title=f"{symbol} · {display_name}",
        body=body,
        styles=_CSS,
        # Keep the historical CDN marker for consumers that inspect report
        # provenance, while executing the checked-in bundle offline.
        head_extra=(
            f"<!-- CDN fallback: {script_src(_ECHARTS_SRC)} -->"
            + echarts_script_tag(
                _ECHARTS_SRC, Path(__file__).resolve().parent / "assets" / "echarts.min.js"
            )
        ),
        scripts=scripts,
    )


# ============================================================
#  主入口
# ============================================================

def generate_report(
    df_ohlc: pd.DataFrame,
    df_trades: pd.DataFrame,
    symbol: str,
    strategy_name: str,
    output_path: Path,
    equity_data: Optional[pd.DataFrame] = None,
    strategy_params: Optional[dict] = None,
    trendline_config: Optional[dict] = None,
    technical_structure_config: Optional[dict] = None,
    adjustment: str = "qfq",
) -> None:
    # ---- 日期归一化 ----
    if not pd.api.types.is_datetime64_any_dtype(df_ohlc["date"]):
        df_ohlc = df_ohlc.copy()
        df_ohlc["date"] = pd.to_datetime(df_ohlc["date"])
    df_ohlc = df_ohlc.sort_values("date").reset_index(drop=True)

    # ---- 降采样周线 / 月线 ----
    df_weekly = _resample_ohlc(df_ohlc, "W")
    df_monthly = _resample_ohlc(df_ohlc, "M")

    periods = [
        ("daily", "日K", df_ohlc),
        ("weekly", "周K", df_weekly),
        ("monthly", "月K", df_monthly),
    ]

    manual_drawing_mode = strategy_name == "trendlines"

    # One shared causal engine serves strategy reports.  The standalone
    # trendlines page is now a manual drawing desk, so it intentionally avoids
    # automatic structure detection and automatic line overlays.
    technical_results: dict[str, object] = {}
    structure_renderer: TechnicalStructureRenderer | None = None
    if not manual_drawing_mode:
        structure_config = technical_structure_config if technical_structure_config is not None else (trendline_config or {})
        structure_service = TechnicalStructureService(
            structure_config,
            cache_dir=(structure_config or {}).get("cache_dir") if isinstance(structure_config, dict) else None,
        )
        technical_results = structure_service.analyze_multi_timeframe(
            symbol=symbol,
            asset_type="stock",
            timeframes=["1d", "1w", "1mo"],
            ohlcv=df_ohlc,
            adjustment=adjustment or "qfq",
        )
        structure_renderer = TechnicalStructureRenderer()

    # ---- 权益数据（周期无关）----
    equity_payload = build_equity_payload(equity_data)
    equity_json = "null" if equity_payload is None else _to_json(equity_payload)

    # ---- 统计 ----
    stats = _compute_stats(df_trades, equity_data)
    mtf_diagnostics = None
    diagnostic_html = ""
    mtf_cls = None
    mtf_weekly_fast_ema = None
    mtf_weekly_slow_ema = None
    if strategy_name == "multi_timeframe_volume_trend":
        mtf_cls = load_strategy_class("multi_timeframe_volume_trend")
        mtf_weekly_fast_ema = int(
            _strategy_param_value(mtf_cls, strategy_params, "weekly_fast_ema", 13)
        )
        mtf_weekly_slow_ema = int(
            _strategy_param_value(mtf_cls, strategy_params, "weekly_slow_ema", 26)
        )
        mtf_diagnostics, diagnostic_html = _calc_mtf_diagnostics(
            df_ohlc, df_trades, strategy_params
        )

    # ---- 逐周期构造数据 JSON ----
    period_data: dict = {}
    for period_id, period_label, df_period in periods:
        timeframe = {"daily": "1d", "weekly": "1w", "monthly": "1mo"}[period_id]
        period_dates = df_period["date"].dt.strftime("%Y-%m-%d").tolist()
        period_payload = build_stock_period_payload(
            symbol=symbol,
            strategy_name=strategy_name,
            period_id=period_id,
            period_label=period_label,
            df_period=df_period,
            df_trades=df_trades,
            trendline_config=trendline_config,
            technical_structure_result=None if manual_drawing_mode else technical_results[timeframe],
            technical_structure_series=[] if manual_drawing_mode or structure_renderer is None else structure_renderer.build_multi_timeframe_series(
                technical_results,
                chart_timeframe=timeframe,
                date_axis=period_dates,
                options={"include_broken": True, "include_expired": True},
            ),
            manual_drawing=manual_drawing_mode,
        )
        if period_id == "daily" and mtf_diagnostics is not None:
            period_payload["diagnostics"] = mtf_diagnostics
        if (
            period_id == "weekly"
            and mtf_cls is not None
            and mtf_weekly_fast_ema is not None
            and mtf_weekly_slow_ema is not None
        ):
            period_payload["diagnostics"] = build_weekly_ema_diagnostics(
                close=df_period["close"],
                fast_period=mtf_weekly_fast_ema,
                slow_period=mtf_weekly_slow_ema,
            )
        period_data[period_id] = period_payload

    # ---- 序列化 ----
    period_json = _to_json(period_data)

    # ---- 组装 HTML ----
    html = _build_page(symbol, strategy_name, stats, period_json, equity_json, diagnostic_html)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")


def generate_trendline_report(
    df_ohlc: pd.DataFrame,
    symbol: str,
    output_path: Path,
    trendline_config: Optional[dict] = None,
    technical_structure_config: Optional[dict] = None,
    adjustment: str = "qfq",
) -> None:
    """Generate a K-line report focused on browser-side manual drawing tools."""
    empty_trades = pd.DataFrame(columns=["date", "symbol", "direction", "price", "size", "commission", "pnl"])
    generate_report(
        df_ohlc=df_ohlc,
        df_trades=empty_trades,
        symbol=symbol,
        strategy_name="trendlines",
        output_path=output_path,
        equity_data=None,
        strategy_params=None,
        trendline_config=trendline_config,
        technical_structure_config=technical_structure_config,
        adjustment=adjustment,
    )
