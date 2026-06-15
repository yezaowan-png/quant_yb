"""生成完整 HTML 可视化报告 —— 亮色主题 + 紧凑渲染"""

from __future__ import annotations  # 仅用于推迟求值，不影响运行时

import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# ---- echarts CDN ----
_ECHARTS_SRC = "https://assets.pyecharts.org/assets/v6/echarts.min.js"

# ---- 策略中文名 ----
_STRAT_NAMES = {"sma_cross": "双均线交叉", "macd_cross": "MACD 金叉", "kdj": "KDJ",
                "bollinger": "布林带", "rsi": "RSI", "single_ma": "单均线",
                "volume_platform_breakout": "放量平台突破"}


# ============================================================
#  技术指标计算（纯 Python，不依赖 pyecharts）
# ============================================================

def _calc_ma(close: pd.Series, period: int) -> list:
    ma = close.rolling(window=period).mean()
    return [round(v, 3) if not pd.isna(v) else None for v in ma.tolist()]


def _calc_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd_hist = 2 * (dif - dea)
    return (
        [round(v, 4) if not pd.isna(v) else None for v in dif.tolist()],
        [round(v, 4) if not pd.isna(v) else None for v in dea.tolist()],
        [round(v, 4) if not pd.isna(v) else None for v in macd_hist.tolist()],
    )


def _calc_kdj(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 9):
    lowest_low = low.rolling(window=period).min()
    highest_high = high.rolling(window=period).max()
    rsv = ((close - lowest_low) / (highest_high - lowest_low + 1e-10)) * 100

    k_vals, d_vals, j_vals = [], [], []
    k, d = 50.0, 50.0
    smooth = 3
    alpha_k = 1.0 / smooth
    alpha_d = 1.0 / smooth

    for r in rsv:
        if pd.isna(r):
            k_vals.append(None)
            d_vals.append(None)
            j_vals.append(None)
        else:
            k = k * (1 - alpha_k) + r * alpha_k
            d = d * (1 - alpha_d) + k * alpha_d
            j = 3 * k - 2 * d
            k_vals.append(round(k, 2))
            d_vals.append(round(d, 2))
            j_vals.append(round(j, 2))

    return k_vals, d_vals, j_vals


def _calc_rsi(close: pd.Series, period: int = 14) -> list:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi.iloc[:period] = None
    return [round(v, 2) if not pd.isna(v) else None for v in rsi.tolist()]


# ============================================================
#  周期降采样
# ============================================================

def _resample_ohlc(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    try:
        resampler = df.set_index("date").resample(freq)
    except ValueError:
        if freq == "M":
            resampler = df.set_index("date").resample("ME")
        else:
            raise
    return (
        resampler
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
        .reset_index()
    )


def _map_trades_to_period(
    trades_df: pd.DataFrame, period_df: pd.DataFrame
) -> tuple[list, list]:
    trade_dates = pd.to_datetime(trades_df["date"])
    period_dates = period_df["date"].values
    period_closes = period_df["close"].values

    buy_marks: list = []
    sell_marks: list = []

    for i, trade_date in enumerate(trade_dates):
        idx = np.searchsorted(period_dates, trade_date.to_numpy())
        if idx >= len(period_dates):
            continue
        bar_date_str = pd.Timestamp(period_dates[idx]).strftime("%Y-%m-%d")
        bar_close = float(period_closes[idx])
        direction = trades_df.iloc[i]["direction"]
        if direction == "BUY":
            buy_marks.append((bar_date_str, bar_close))
        else:
            sell_marks.append((bar_date_str, bar_close))

    return buy_marks, sell_marks


# ============================================================
#  JSON 序列化辅助
# ============================================================

class _CompactEncoder(json.JSONEncoder):
    """将 numpy/pandas 类型转为 JSON-safe 类型，并紧凑输出。"""
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return None if np.isnan(obj) else round(float(obj), 6)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


def _to_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), cls=_CompactEncoder,
                      allow_nan=False)


def _clean_list(lst, decimals=None):
    """将指标值列表转为 JSON-safe 类型，None 保持 null。"""
    result = []
    for v in lst:
        if v is None:
            result.append(None)
        elif hasattr(v, "item"):
            result.append(v.item() if decimals is None else round(v.item(), decimals))
        else:
            result.append(v if decimals is None else round(v, decimals))
    return result


# ============================================================
#  权益曲线计算
# ============================================================

def _compute_drawdowns(values: list[float]) -> list[float]:
    arr = np.array(values)
    if len(arr) == 0:
        return []
    peak = np.maximum.accumulate(arr)
    dd = (arr - peak) / peak * 100
    return [round(v, 2) for v in dd.tolist()]


def _longest_streak(values: list[float], positive: bool) -> int:
    longest = 0
    current = 0
    for value in values:
        matched = value > 0 if positive else value < 0
        if matched:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _compute_rolling_sharpe(values: list[float], window: int = 60) -> list:
    returns = pd.Series(values, dtype="float64").pct_change()
    roll_mean = returns.rolling(window=window).mean()
    roll_std = returns.rolling(window=window).std()
    sharpe = roll_mean / (roll_std + 1e-12) * np.sqrt(252)
    return [round(float(v), 3) if not pd.isna(v) else None for v in sharpe.tolist()]


def _compute_monthly_returns(equity_data: pd.DataFrame) -> dict:
    frame = equity_data.copy()
    frame["dates"] = pd.to_datetime(frame["dates"])
    monthly = frame.set_index("dates")["equity"].resample("M").last().pct_change().dropna() * 100
    if monthly.empty:
        return {"years": [], "months": [], "data": []}
    years = [str(y) for y in sorted(monthly.index.year.unique())]
    year_index = {year: i for i, year in enumerate(years)}
    data = []
    for dt, value in monthly.items():
        data.append([int(dt.month) - 1, year_index[str(dt.year)], round(float(value), 2)])
    return {
        "years": years,
        "months": [f"{i}月" for i in range(1, 13)],
        "data": data,
    }


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
            sell_pnls = [float(v or 0) for v in sells["pnl"].tolist()]
            win_trades = int((sells["pnl"] > 0).sum())
            gross_profit = sum(v for v in sell_pnls if v > 0)
            gross_loss = sum(v for v in sell_pnls if v < 0)
            stats["total_trades"] = total_trades
            stats["win_trades"] = win_trades
            stats["lose_trades"] = total_trades - win_trades
            stats["win_rate"] = round(win_trades / total_trades * 100, 2)
            stats["total_pnl"] = round(sells["pnl"].sum(), 2)
            if gross_loss < 0:
                stats["profit_factor"] = round(gross_profit / abs(gross_loss), 3)
            elif gross_profit > 0:
                stats["profit_factor"] = "N/A"
            stats["longest_win_streak"] = _longest_streak(sell_pnls, positive=True)
            stats["longest_loss_streak"] = _longest_streak(sell_pnls, positive=False)

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
            returns = pd.Series(eq, dtype="float64").pct_change().dropna()
            downside = returns[returns < 0]
            if len(downside) > 1 and downside.std() > 0:
                stats["sortino"] = round(float(returns.mean() / downside.std() * np.sqrt(252)), 3)

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
    if "sortino" in stats:
        cards.append(_card("Sortino", f"{stats['sortino']}", "up" if stats["sortino"] >= 0 else "down"))
    if "profit_factor" in stats:
        cards.append(_card("Profit Factor", f"{stats['profit_factor']}"))
    if "longest_win_streak" in stats:
        cards.append(_card("最长连赢/连亏", f"{stats['longest_win_streak']}/{stats.get('longest_loss_streak', 0)}"))
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
function lg(d){return{show:d&&d.length>0,top:4,left:'center',textStyle:{fontSize:10,color:C.lb},data:d||[]};}
function ti(t){return{text:t,left:'left',top:6,textStyle:{fontSize:15,fontWeight:'bold',color:C.ti}};}

var ALL=[];
function ch(dom,opt){var c=echarts.init(document.getElementById(dom),null,{renderer:'canvas'});c.setOption(opt);ALL.push(c);return c;}

// ---- K-line ----
function kline(dom,d){
  var vs=Math.max(70,100-Math.max(30,100*90/Math.max(d.dates.length,1)));
  var mk=[];
  (d.trades.buy||[]).forEach(function(t){mk.push({name:'买入',coord:[t[0],t[1]],value:'买入',symbol:'triangle',symbolSize:26,itemStyle:{color:C.up,borderColor:'#fff',borderWidth:3},label:{show:true,position:'top',fontSize:11,fontWeight:'bold',color:C.up,distance:8}});});
  (d.trades.sell||[]).forEach(function(t){mk.push({name:'卖出',coord:[t[0],t[1]],value:'卖出',symbol:'triangle',symbolSize:26,symbolRotate:180,itemStyle:{color:C.dn,borderColor:'#fff',borderWidth:3},label:{show:true,position:'bottom',fontSize:11,fontWeight:'bold',color:C.dn,distance:8}});});
  var se=[{name:'K线',type:'candlestick',data:d.ohlc,markPoint:{data:mk},itemStyle:{color:C.up,color0:C.dn,borderColor:C.up,borderColor0:C.dn},barMaxWidth:'60%',barMinWidth:3}];
  var lgD=['K线'];
  [{d:d.ma5,n:'MA5'},{d:d.ma10,n:'MA10'},{d:d.ma20,n:'MA20'},{d:d.ma60,n:'MA60'}].forEach(function(m,i){
    if(m.d&&m.d.length){se.push({name:m.n,type:'line',data:m.d,smooth:true,symbol:'none',lineStyle:{color:C.ma[i],width:1.5,opacity:0.7}});lgD.push(m.n);}
  });
  return ch(dom,{backgroundColor:C.bg,title:ti(d.title),xAxis:ax(d.dates),yAxis:ya(),legend:lg(lgD),tooltip:tl(),dataZoom:dz(vs),toolbox:tb(),series:se});
}

// ---- Volume ----
function volume(dom,d){
  var vs=Math.max(70,100-Math.max(30,100*90/Math.max(d.dates.length,1)));
  var uv=[],dv=[];
  d.ohlc.forEach(function(o,i){var v=d.volume[i]||0;if(o[1]>=o[0]){uv.push(v||0.01);dv.push(0);}else{uv.push(0);dv.push(v||0.01);}});
  return ch(dom,{backgroundColor:C.bg,title:ti('成交量'),xAxis:ax(d.dates,false),yAxis:ya({name:'成交量'}),legend:lg([]),tooltip:tl(),dataZoom:dz(vs),series:[{name:'',type:'bar',data:uv,stack:'_v',itemStyle:{color:C.up}},{name:'',type:'bar',data:dv,stack:'_v',itemStyle:{color:C.dn}}]});
}

// ---- MACD ----
function macd(dom,d){
  var vs=Math.max(70,100-Math.max(30,100*90/Math.max(d.dates.length,1)));
  return ch(dom,{backgroundColor:C.bg,title:ti('MACD (12, 26, 9)'),xAxis:ax(d.dates,false),yAxis:ya(),legend:lg(['DIF','DEA','MACD']),tooltip:tl(),dataZoom:dz(vs),series:[{name:'DIF',type:'line',data:d.macd.dif,smooth:true,symbol:'none',lineStyle:{color:C.bl,width:1.8},connectNulls:true},{name:'DEA',type:'line',data:d.macd.dea,smooth:true,symbol:'none',lineStyle:{color:C.or,width:1.8},connectNulls:true},{name:'MACD',type:'line',data:d.macd.hist,areaStyle:{opacity:0.1},lineStyle:{color:C.up,width:1},connectNulls:true}]});
}

// ---- KDJ ----
function kdj(dom,d){
  var vs=Math.max(70,100-Math.max(30,100*90/Math.max(d.dates.length,1)));
  return ch(dom,{backgroundColor:C.bg,title:ti('KDJ (9, 3, 3)'),xAxis:ax(d.dates,false),yAxis:ya(),legend:lg(['K','D','J']),tooltip:tl(),dataZoom:dz(vs),series:[{name:'K',type:'line',data:d.kdj.k,smooth:true,symbol:'none',lineStyle:{color:C.bl,width:1.8},connectNulls:true},{name:'D',type:'line',data:d.kdj.d,smooth:true,symbol:'none',lineStyle:{color:C.or,width:1.8},connectNulls:true},{name:'J',type:'line',data:d.kdj.j,smooth:true,symbol:'none',lineStyle:{color:C.jr,width:1.2,opacity:0.7},connectNulls:true}]});
}

// ---- RSI ----
function rsi(dom,d){
  var vs=Math.max(70,100-Math.max(30,100*90/Math.max(d.dates.length,1)));
  var len=d.dates.length,f30=Array(len).fill(30),f70=Array(len).fill(70);
  return ch(dom,{backgroundColor:C.bg,title:ti('RSI (14)'),xAxis:ax(d.dates,false),yAxis:ya({min:0,max:100}),legend:lg(['RSI','超卖线(30)','超买线(70)']),tooltip:tl(),dataZoom:dz(vs),series:[{name:'RSI',type:'line',data:d.rsi,smooth:true,symbol:'none',lineStyle:{color:C.bl,width:2},connectNulls:true},{name:'超卖线(30)',type:'line',data:f30,smooth:false,symbol:'none',lineStyle:{color:C.dn,width:1,type:'dashed',opacity:0.5}},{name:'超买线(70)',type:'line',data:f70,smooth:false,symbol:'none',lineStyle:{color:C.up,width:1,type:'dashed',opacity:0.5}}]});
}

// ---- Equity ----
function equity(dom,d){
  if(!d)return null;
  var vs=Math.max(70,100-Math.max(30,100*90/Math.max(d.dates.length,1)));
  var eq=ch(dom,{backgroundColor:C.bg,title:ti('权益曲线 & Underwater 回撤'),xAxis:ax(d.dates),yAxis:[ya({name:'权益 (元)'}),{type:'value',name:'回撤 %',axisLabel:{fontSize:10,color:C.lb,formatter:'{value}%'},splitLine:{show:false},nameTextStyle:{color:C.lb}}],legend:lg(['权益曲线','回撤']),tooltip:tl(),dataZoom:dz(vs),toolbox:tb(),series:[{name:'权益曲线',type:'line',data:d.equity,yAxisIndex:0,smooth:true,symbol:'none',lineStyle:{color:C.bl,width:2.5},areaStyle:{opacity:0.08,color:C.bl}},{name:'回撤',type:'line',data:d.drawdowns,yAxisIndex:1,smooth:true,symbol:'none',lineStyle:{color:C.up,width:1.5},areaStyle:{opacity:0.1,color:C.up}}]});
  return eq;
}

function rollingSharpe(dom,d){
  if(!d||!d.rollingSharpe)return null;
  var vs=Math.max(70,100-Math.max(30,100*90/Math.max(d.dates.length,1)));
  return ch(dom,{backgroundColor:C.bg,title:ti('Rolling Sharpe (60日)'),xAxis:ax(d.dates),yAxis:ya({name:'Sharpe'}),legend:lg(['Rolling Sharpe']),tooltip:tl(),dataZoom:dz(vs),toolbox:tb(),series:[{name:'Rolling Sharpe',type:'line',data:d.rollingSharpe,smooth:true,symbol:'none',connectNulls:true,lineStyle:{color:C.bl,width:2.2},areaStyle:{opacity:0.08,color:C.bl}}]});
}

function monthlyHeatmap(dom,d){
  if(!d||!d.monthly||!d.monthly.data||!d.monthly.data.length)return null;
  return ch(dom,{backgroundColor:C.bg,title:ti('月度收益热力图'),tooltip:{position:'top',formatter:function(p){return d.monthly.years[p.value[1]]+' '+d.monthly.months[p.value[0]]+': '+p.value[2]+'%';}},grid:{height:'62%',top:'18%'},xAxis:{type:'category',data:d.monthly.months,splitArea:{show:true},axisLabel:{color:C.lb}},yAxis:{type:'category',data:d.monthly.years,splitArea:{show:true},axisLabel:{color:C.lb}},visualMap:{min:-20,max:20,calculable:true,orient:'horizontal',left:'center',bottom:'5%',inRange:{color:[C.dn,'#f7f7f7',C.up]}},series:[{name:'月度收益',type:'heatmap',data:d.monthly.data,label:{show:true,formatter:function(p){return p.value[2]+'%';},fontSize:10},emphasis:{itemStyle:{shadowBlur:8,shadowColor:'rgba(0,0,0,.18)'}}}]});
}

function tradePnl(dom,d){
  if(!d||!d.pnl||!d.pnl.length)return null;
  var colors=d.pnl.map(function(v){return v>=0?C.up:C.dn;});
  return ch(dom,{backgroundColor:C.bg,title:ti('交易 PnL 分布'),xAxis:ax(d.labels,false),yAxis:ya({name:'PnL'}),legend:lg([]),tooltip:tl(),dataZoom:dz(60),toolbox:tb(),series:[{name:'PnL',type:'bar',data:d.pnl,itemStyle:{color:function(p){return colors[p.dataIndex];}},label:{show:false}}]});
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
  if(window._E){rollingSharpe('rolling-sharpe',window._E);monthlyHeatmap('monthly-heatmap',window._E);}
  if(window._T){tradePnl('trade-pnl',window._T);}
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
    ALL.forEach(function(c){try{var d=c.getDom();if(d&&container.contains(d))c.resize();}catch(e){}});
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
.container { max-width: 1460px; margin: 0 auto; padding: 28px 24px; }

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
.chart-section .chart-container.ht-520 { height: 520px; }

.period-tabs { display: flex; gap: 20px; margin-top: 28px; border-bottom: 2px solid #eaeaef; padding: 0; }
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
"""


def _build_page(symbol: str, strategy_name: str, stats: dict,
                period_data_json: str, equity_data_json: str,
                trade_data_json: str) -> str:
    """组装完整 HTML 页面。period_data_json 和 equity_data_json 是预序列化的 JSON 字符串。"""
    stats_html = _build_stats_html(stats)
    display_name = _STRAT_NAMES.get(strategy_name, strategy_name)

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
    <div class="chart-section"><div id="k-{pid}" class="chart-container ht-500"></div></div>
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
        equity_section = """<div class="chart-section chart-section--equity"><div id="equity" class="chart-container ht-520"></div></div>
    <div class="chart-section chart-section--equity"><div id="rolling-sharpe" class="chart-container ht-350"></div></div>
    <div class="chart-section chart-section--equity"><div id="monthly-heatmap" class="chart-container ht-350"></div></div>"""

    trade_section = ""
    if trade_data_json and trade_data_json != "null":
        trade_section = '<div class="chart-section chart-section--equity"><div id="trade-pnl" class="chart-container ht-350"></div></div>'

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{symbol} &middot; {display_name}</title>
<script src="{_ECHARTS_SRC}"></script>
<style>{_CSS}</style>
</head>
<body>
<div class="container">
    <div class="topbar">
        <div class="topbar-left">
            <h1><span>{symbol}</span> 回测报告</h1>
            <span class="code-tag">{display_name}</span>
        </div>
        <div class="topbar-right">QuantYB</div>
    </div>
    <div class="stats-grid">{stats_html}</div>
    <div class="period-tabs">{period_tab_btns}</div>
    {"".join(period_sections)}
    {equity_section}
    {trade_section}
    <div class="footer">QuantYB &copy; 2026 &nbsp;&middot;&nbsp; A-Share Quantitative Backtesting System</div>
</div>
<script>window._D={period_data_json};window._E={equity_data_json};window._T={trade_data_json};</script>
{_CHART_JS}
</body>
</html>"""


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

    # ---- 权益数据（周期无关）----
    equity_json = "null"
    if equity_data is not None and not equity_data.empty:
        eq_list = [round(float(v), 2) for v in equity_data["equity"].tolist()]
        dd_list = _compute_drawdowns(eq_list)
        dates_eq = equity_data["dates"].astype(str).tolist()
        equity_json = _to_json({
            "dates": dates_eq,
            "equity": eq_list,
            "drawdowns": dd_list,
            "rollingSharpe": _compute_rolling_sharpe(eq_list, 60),
            "monthly": _compute_monthly_returns(equity_data),
        })

    trade_json = "null"
    if df_trades is not None and not df_trades.empty:
        sells = df_trades[df_trades["direction"] == "SELL"].copy()
        if not sells.empty and "pnl" in sells.columns:
            labels = sells["date"].astype(str).tolist()
            pnl = [round(float(v or 0), 2) for v in sells["pnl"].tolist()]
            trade_json = _to_json({"labels": labels, "pnl": pnl})

    # ---- 统计 ----
    stats = _compute_stats(df_trades, equity_data)

    # ---- 逐周期构造数据 JSON ----
    period_data: dict = {}
    for period_id, period_label, df_period in periods:
        dates = df_period["date"].dt.strftime("%Y-%m-%d").tolist()
        ohlc = df_period[["open", "close", "low", "high"]].values.tolist()
        # OHLC rounding
        ohlc_rounded = [[round(float(o), 2), round(float(c), 2), round(float(l), 2), round(float(h), 2)]
                         for o, c, l, h in ohlc]
        close = df_period["close"]
        volumes_raw = df_period["volume"].tolist() if "volume" in df_period.columns else []

        # 技术指标
        ma5 = _clean_list(_calc_ma(close, 5), 2)
        ma10 = _clean_list(_calc_ma(close, 10), 2)
        ma20 = _clean_list(_calc_ma(close, 20), 2)
        ma60 = _clean_list(_calc_ma(close, 60), 2)
        dif, dea, macd_hist = _calc_macd(close)
        dif_c = _clean_list(dif, 3)
        dea_c = _clean_list(dea, 3)
        hist_c = _clean_list(macd_hist, 3)
        k_vals, d_vals, j_vals = _calc_kdj(df_period["high"], df_period["low"], close)
        k_c = _clean_list(k_vals, 1)
        d_c = _clean_list(d_vals, 1)
        j_c = _clean_list(j_vals, 1)
        rsi_vals = _clean_list(_calc_rsi(close, 14), 1)
        volumes_c = _clean_list(volumes_raw, 0)

        # 买卖点
        if period_id == "daily":
            buy_marks, sell_marks = [], []
            if df_trades is not None and not df_trades.empty:
                for _, row in df_trades.iterrows():
                    if row["direction"] == "BUY":
                        buy_marks.append((str(row["date"]), round(float(row["price"]), 2)))
                    else:
                        sell_marks.append((str(row["date"]), round(float(row["price"]), 2)))
        else:
            buy_marks, sell_marks = _map_trades_to_period(df_trades, df_period)

        title = f"{symbol}  —  {strategy_name}  ({period_label})"

        period_data[period_id] = {
            "title": title,
            "dates": dates,
            "ohlc": ohlc_rounded,
            "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60,
            "macd": {"dif": dif_c, "dea": dea_c, "hist": hist_c},
            "kdj": {"k": k_c, "d": d_c, "j": j_c},
            "rsi": rsi_vals,
            "volume": volumes_c,
            "trades": {"buy": buy_marks, "sell": sell_marks},
        }

    # ---- 序列化 ----
    period_json = _to_json(period_data)

    # ---- 组装 HTML ----
    html = _build_page(symbol, strategy_name, stats, period_json, equity_json, trade_json)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
