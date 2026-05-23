"""生成完整 HTML 可视化报告"""

import re
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from pyecharts.charts import Grid, Line
from pyecharts import options as opts

from visual.kline_chart import (
    create_kline_chart, create_macd_chart, create_kdj_chart,
    create_volume_chart, create_rsi_chart,
    _CHART_BG, _TITLE_COLOR, _AXIS_LABEL_COLOR, _AXIS_LINE_COLOR, _SPLIT_LINE_COLOR,
    _UP_COLOR, _DOWN_COLOR,
)


# ============================================================
#  技术指标计算
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
    """计算 RSI 指标值，返回 list[float|None]"""
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
#  权益曲线组件
# ============================================================

def _compute_drawdowns(values: list[float]) -> list[float]:
    arr = np.array(values)
    peak = np.maximum.accumulate(arr)
    dd = (arr - peak) / peak * 100
    return dd.tolist()


def _create_equity_chart(dates: list[str], equity: list[float]) -> Grid:
    drawdowns = _compute_drawdowns(equity)
    visible_start = max(70, 100 - max(30, 100 * 90 // len(dates)))

    equity_gold = "#c9a050"

    line = (
        Line()
        .add_xaxis(dates)
        .add_yaxis(
            series_name="权益曲线",
            y_axis=[round(v, 2) for v in equity],
            yaxis_index=0,
            is_smooth=True, symbol="none",
            linestyle_opts=opts.LineStyleOpts(color=equity_gold, width=2.5),
            areastyle_opts=opts.AreaStyleOpts(opacity=0.1, color=equity_gold),
            label_opts=opts.LabelOpts(is_show=False),
        )
        .extend_axis(
            yaxis=opts.AxisOpts(
                type_="value", name="回撤 %",
                axislabel_opts=opts.LabelOpts(formatter="{value}%", font_size=11, color=_AXIS_LABEL_COLOR),
                splitline_opts=opts.SplitLineOpts(is_show=False),
                name_textstyle_opts=opts.TextStyleOpts(color=_AXIS_LABEL_COLOR),
            )
        )
        .add_yaxis(
            series_name="回撤",
            y_axis=[round(d, 2) for d in drawdowns],
            yaxis_index=1,
            is_smooth=True, symbol="none",
            linestyle_opts=opts.LineStyleOpts(color=_UP_COLOR, width=1.5),
            areastyle_opts=opts.AreaStyleOpts(opacity=0.12, color=_UP_COLOR),
            label_opts=opts.LabelOpts(is_show=False),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title="权益曲线 & 回撤", pos_left="left", pos_top="2%",
                title_textstyle_opts=opts.TextStyleOpts(font_size=18, font_weight="bold", color=_TITLE_COLOR),
            ),
            xaxis_opts=opts.AxisOpts(
                type_="category",
                axislabel_opts=opts.LabelOpts(rotate=30, font_size=10, color=_AXIS_LABEL_COLOR),
                axisline_opts=opts.AxisLineOpts(linestyle_opts=opts.LineStyleOpts(color=_AXIS_LINE_COLOR)),
            ),
            yaxis_opts=opts.AxisOpts(
                type_="value", name="权益 (元)",
                axislabel_opts=opts.LabelOpts(formatter="{value}", font_size=11, color=_AXIS_LABEL_COLOR),
                splitline_opts=opts.SplitLineOpts(
                    is_show=True,
                    linestyle_opts=opts.LineStyleOpts(type_="dashed", color=_SPLIT_LINE_COLOR),
                ),
                name_textstyle_opts=opts.TextStyleOpts(color=_AXIS_LABEL_COLOR),
            ),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
            datazoom_opts=[
                opts.DataZoomOpts(type_="inside", range_start=visible_start, range_end=100),
                opts.DataZoomOpts(type_="slider", range_start=visible_start, range_end=100, pos_bottom="2%"),
            ],
            legend_opts=opts.LegendOpts(
                pos_top="2%", pos_left="center",
                textstyle_opts=opts.TextStyleOpts(color=_AXIS_LABEL_COLOR),
            ),
            toolbox_opts=opts.ToolboxOpts(is_show=True, pos_left="right", feature={"saveAsImage": {"title": "保存为图片"}}),
        )
    )

    grid = Grid(init_opts=opts.InitOpts(width="100%", height="520px", bg_color=_CHART_BG))
    grid.add(line, grid_opts=opts.GridOpts(pos_top="16%", pos_bottom="16%", pos_left="10%", pos_right="5%"))
    return grid


# ============================================================
#  统计与 HTML 拼装
# ============================================================

def _compute_stats(df_trades: Optional[pd.DataFrame], equity_data: Optional[pd.DataFrame]) -> dict:
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


def _extract_chart_parts(html: str) -> tuple[str, str, str, str]:
    """从 pyecharts render_embed() 的完整 HTML 中提取 (echarts_js_src, div, script, chart_var)。"""
    lib_match = re.search(r'<script\s+type="text/javascript"\s+src="(https://[^"]+echarts[^"]*)"', html)
    echarts_src = lib_match.group(1) if lib_match else "https://assets.pyecharts.org/assets/v6/echarts.min.js"
    div_match = re.search(r'(<div\s+id="[^"]*"\s+class="chart-container"[^>]*></div>)', html)
    div_html = div_match.group(1) if div_match else ""
    script_match = re.search(r'(<script>\s*var\s+chart_.*?</script>)', html, re.DOTALL)
    script_html = script_match.group(1) if script_match else ""
    var_match = re.search(r'var\s+(chart_\w+)', script_html)
    chart_var = var_match.group(1) if var_match else ""
    return echarts_src, div_html, script_html, chart_var


def _build_page(
    symbol: str, strategy_name: str, stats: dict,
    echarts_src: str,
    kline_div: str, kline_script: str, kline_var: str,
    indicators: list[dict],
    equity_div: str, equity_script: str, equity_var: str,
) -> str:
    """indicators: [{"id": "volume", "label": "成交量", "div": ..., "script": ..., "var": ...}, ...]"""
    stats_html = _build_stats_html(stats)

    _STRAT_NAMES = {"sma_cross": "双均线交叉", "macd_cross": "MACD 金叉", "kdj": "KDJ",
                    "bollinger": "布林带", "rsi": "RSI", "single_ma": "单均线"}
    display_name = _STRAT_NAMES.get(strategy_name, strategy_name)

    # ---- 标签栏按钮 ----
    tab_buttons = []
    for ind in indicators:
        active_class = " active" if ind["id"] == "volume" else ""
        tab_buttons.append(
            f'<button class="tab-btn{active_class}" data-target="panel-{ind["id"]}">{ind["label"]}</button>'
        )

    # ---- 指标面板 ----
    panels = []
    for ind in indicators:
        active_class = " active" if ind["id"] == "volume" else ""
        panels.append(f"""<div id="panel-{ind["id"]}" class="indicator-panel{active_class}">
            <div class="chart-section">
                {ind["div"]}
            </div>
            {ind["script"]}
        </div>""")

    # ---- 权益曲线 ----
    equity_section = ""
    if equity_div and equity_script:
        equity_section = f"""
        <div class="chart-section chart-section--equity">
            {equity_div}
        </div>
        {equity_script}"""

    # ---- 收集所有 chart var 名用于联动脚本 ----
    all_vars = [kline_var] + [ind["var"] for ind in indicators] + [equity_var]
    all_vars = [v for v in all_vars if v]
    vars_json = "[" + ", ".join(all_vars) + "]"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{symbol} &middot; {display_name}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,600;0,700;1,600&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<script src="{echarts_src}"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
    background: #0b0d0f;
    color: #b8bcc4;
    line-height: 1.6;
    -webkit-font-smoothing: antialiased;
}}
body::before {{
    content: '';
    position: fixed;
    top: -40%; left: -40%;
    width: 180%; height: 180%;
    background: radial-gradient(ellipse at 50% 0%, rgba(201,160,80,0.05) 0%, transparent 55%);
    pointer-events: none;
    z-index: 0;
}}
.container {{ max-width: 1460px; margin: 0 auto; padding: 32px 28px; position: relative; z-index: 1; }}

/* ---- 顶栏 ---- */
.topbar {{
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 36px; padding-bottom: 20px;
    border-bottom: 1px solid #22252b;
}}
.topbar-left {{ display: flex; align-items: baseline; gap: 16px; }}
.topbar-left h1 {{
    font-family: "Playfair Display", Georgia, "Times New Roman", serif;
    font-size: 28px; font-weight: 600; color: #e4e4e4;
    letter-spacing: .3px;
}}
.topbar-left h1 span {{ font-style: italic; font-weight: 600; }}
.topbar-left .code-tag {{
    font-family: "JetBrains Mono", "Courier New", monospace;
    font-size: 13px; font-weight: 500; color: #c9a050;
    background: rgba(201,160,80,0.07); padding: 4px 12px; border-radius: 4px;
    letter-spacing: .5px; border: 1px solid rgba(201,160,80,0.12);
}}
.topbar-right {{
    font-size: 11px; color: #4a4d54; letter-spacing: .6px;
    font-family: "JetBrains Mono", "Courier New", monospace;
}}

/* ---- 统计卡片 ---- */
.stats-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
    gap: 10px; margin-bottom: 32px;
}}
.stat-card {{
    background: #131518; border: 1px solid #1d1f24;
    border-radius: 6px; padding: 18px 22px;
    transition: border-color .25s, transform .25s, background .25s;
    position: relative; overflow: hidden;
}}
.stat-card::after {{
    content: ''; position: absolute; inset: 0;
    background: radial-gradient(circle at 100% 0%, rgba(201,160,80,0.05) 0%, transparent 70%);
    opacity: 0; transition: opacity .25s;
}}
.stat-card:hover {{
    border-color: #292c34; transform: translateY(-1px); background: #15171c;
}}
.stat-card:hover::after {{ opacity: 1; }}
.stat-label {{
    font-size: 10px; text-transform: uppercase; letter-spacing: 1.4px;
    color: #5c5f66; margin-bottom: 10px; font-weight: 600;
}}
.stat-value {{
    font-family: "JetBrains Mono", "Courier New", monospace;
    font-size: 25px; font-weight: 500; color: #e4e4e4;
    letter-spacing: -.5px; line-height: 1;
}}
.stat-value.up {{ color: #4ecb71; }}
.stat-value.down {{ color: #f06070; }}

/* ---- 图表区块 ---- */
.chart-section {{
    background: #141619; border: 1px solid #1e2027;
    border-radius: 6px; padding: 0; margin-bottom: 0;
    overflow: hidden;
}}
.chart-section.chart-section--equity {{ margin-top: 32px; }}
.chart-section .chart-container {{ width: 100% !important; }}

/* ---- 标签页 (underline 风格) ---- */
.indicator-tabs {{
    display: flex; gap: 0; margin-top: 32px;
    border-bottom: 1px solid #1e2027;
    padding: 0;
}}
.tab-btn {{
    padding: 10px 24px; border: none; background: none;
    cursor: pointer; font-size: 13px; font-weight: 500;
    color: #5c5f66; letter-spacing: .4px;
    transition: color .2s; font-family: inherit; outline: none;
    position: relative;
}}
.tab-btn::after {{
    content: ''; position: absolute; bottom: -1px; left: 0; right: 0;
    height: 2px; background: #c9a050; transform: scaleX(0);
    transition: transform .2s;
}}
.tab-btn:hover {{ color: #b8bcc4; }}
.tab-btn.active {{ color: #e4e4e4; }}
.tab-btn.active::after {{ transform: scaleX(1); }}
.indicator-panel {{ display: none; }}
.indicator-panel.active {{ display: block; }}
.indicator-panel .chart-section {{
    border-top: none; border-radius: 0 0 6px 6px;
}}

/* ---- 页脚 ---- */
.footer {{
    text-align: center; color: #2e3038; font-size: 10px;
    padding: 40px 0 8px; letter-spacing: .6px;
    font-family: "JetBrains Mono", "Courier New", monospace;
}}

/* ---- 入场动画 ---- */
@keyframes fadeUp {{
    from {{ opacity: 0; transform: translateY(14px); }}
    to   {{ opacity: 1; transform: translateY(0); }}
}}
.stat-card {{ animation: fadeUp .5s ease both; }}
.stat-card:nth-child(1) {{ animation-delay: .03s; }}
.stat-card:nth-child(2) {{ animation-delay: .07s; }}
.stat-card:nth-child(3) {{ animation-delay: .11s; }}
.stat-card:nth-child(4) {{ animation-delay: .15s; }}
.stat-card:nth-child(5) {{ animation-delay: .19s; }}
.stat-card:nth-child(6) {{ animation-delay: .23s; }}
.chart-section {{ animation: fadeUp .6s ease both; animation-delay: .24s; }}
</style>
</head>
<body>
<div class="container">
    <div class="topbar">
        <div class="topbar-left">
            <h1><span>{symbol}</span></h1>
            <span class="code-tag">{display_name}</span>
        </div>
        <div class="topbar-right">QuantYB &middot; 回测报告</div>
    </div>
    <div class="stats-grid">
        {stats_html}
    </div>
    <div class="chart-section">
        {kline_div}
    </div>
    {kline_script}
    <div class="indicator-tabs">
        {"".join(tab_buttons)}
    </div>
    {"".join(panels)}
    {equity_section}
    <div class="footer">QuantYB &copy; 2026 &nbsp;&middot;&nbsp; A-Share Quantitative Backtesting System</div>
</div>
<script>
(function() {{
    var allCharts = {vars_json};
    allCharts.forEach(function(c) {{ if (c) c.group = 'quant_group'; }});
    echarts.connect('quant_group');

    document.querySelectorAll('.tab-btn').forEach(function(btn) {{
        btn.addEventListener('click', function() {{
            var targetId = this.dataset.target;
            document.querySelectorAll('.tab-btn').forEach(function(b) {{ b.classList.remove('active'); }});
            document.querySelectorAll('.indicator-panel').forEach(function(p) {{ p.classList.remove('active'); }});
            this.classList.add('active');
            var panel = document.getElementById(targetId);
            if (panel) {{
                panel.classList.add('active');
                var container = panel.querySelector('.chart-container');
                if (container) {{
                    setTimeout(function() {{
                        allCharts.forEach(function(c) {{
                            if (c && c.getDom() && c.getDom().id === container.id) c.resize();
                        }});
                    }}, 60);
                }}
            }}
        }});
    }});
}})();
</script>
</body>
</html>"""


# ============================================================
#  主入口
# ============================================================

def _render_chart(chart) -> tuple[str, str, str]:
    """Render a pyecharts chart and return (div, script, var_name)."""
    raw = chart.render_embed()
    src, div, script, var = _extract_chart_parts(raw)
    return div, script, var


def generate_report(
    df_ohlc: pd.DataFrame,
    df_trades: pd.DataFrame,
    symbol: str,
    strategy_name: str,
    output_path: Path,
    equity_data: Optional[pd.DataFrame] = None,
) -> None:
    df = df_ohlc.sort_values("date")
    dates = df["date"].dt.strftime("%Y-%m-%d").tolist()
    ohlc = df[["open", "close", "low", "high"]].values.tolist()
    close = df["close"]
    volumes = df["volume"].tolist() if "volume" in df.columns else []

    # ---- 技术指标 ----
    ma5 = _calc_ma(close, 5)
    ma10 = _calc_ma(close, 10)
    ma20 = _calc_ma(close, 20)
    ma60 = _calc_ma(close, 60)
    dif, dea, macd_hist = _calc_macd(close)
    k_vals, d_vals, j_vals = _calc_kdj(df["high"], df["low"], close)
    rsi_vals = _calc_rsi(close, 14)

    # ---- 买卖点标记 ----
    buy_marks: list[tuple[str, float]] = []
    sell_marks: list[tuple[str, float]] = []
    if df_trades is not None and not df_trades.empty:
        for _, row in df_trades.iterrows():
            if row["direction"] == "BUY":
                buy_marks.append((str(row["date"]), float(row["price"])))
            else:
                sell_marks.append((str(row["date"]), float(row["price"])))

    title = f"{symbol}  —  {strategy_name}"

    # ---- K线 + 均线 ----
    kline = create_kline_chart(
        dates, ohlc, buy_marks, sell_marks, title,
        ma5=ma5, ma10=ma10, ma20=ma20, ma60=ma60,
    )
    kline_raw = kline.render_embed()
    echarts_src, kline_div, kline_script, kline_var = _extract_chart_parts(kline_raw)

    # ---- 指标图表列表 ----
    indicators: list[dict] = []

    # 成交量
    if volumes and len(volumes) > 0:
        vol_chart = create_volume_chart(dates, ohlc, volumes)
        if vol_chart is not None:
            vol_div, vol_script, vol_var = _render_chart(vol_chart)
            indicators.append({"id": "volume", "label": "成交量", "div": vol_div, "script": vol_script, "var": vol_var})

    # MACD
    if any(v is not None for v in dif):
        macd_chart = create_macd_chart(dates, dif, dea, macd_hist)
        if macd_chart is not None:
            macd_div, macd_script, macd_var = _render_chart(macd_chart)
            indicators.append({"id": "macd", "label": "MACD", "div": macd_div, "script": macd_script, "var": macd_var})

    # KDJ
    if any(v is not None for v in k_vals):
        kdj_chart = create_kdj_chart(dates, k_vals, d_vals, j_vals)
        if kdj_chart is not None:
            kdj_div, kdj_script, kdj_var = _render_chart(kdj_chart)
            indicators.append({"id": "kdj", "label": "KDJ", "div": kdj_div, "script": kdj_script, "var": kdj_var})

    # RSI
    if any(v is not None for v in rsi_vals):
        rsi_chart = create_rsi_chart(dates, rsi_vals)
        if rsi_chart is not None:
            rsi_div, rsi_script, rsi_var = _render_chart(rsi_chart)
            indicators.append({"id": "rsi", "label": "RSI", "div": rsi_div, "script": rsi_script, "var": rsi_var})

    # ---- 权益曲线 ----
    equity_div = ""
    equity_script = ""
    equity_var = ""
    if equity_data is not None and not equity_data.empty:
        equity_chart = _create_equity_chart(
            equity_data["dates"].tolist(),
            equity_data["equity"].tolist(),
        )
        equity_div, equity_script, equity_var = _render_chart(equity_chart)

    stats = _compute_stats(df_trades, equity_data)
    html = _build_page(
        symbol, strategy_name, stats,
        echarts_src, kline_div, kline_script, kline_var,
        indicators,
        equity_div, equity_script, equity_var,
    )

    output_path.write_text(html, encoding="utf-8")
