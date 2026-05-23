"""生成完整 HTML 可视化报告"""

import re
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from pyecharts.charts import Grid, Line
from pyecharts import options as opts

from visual.kline_chart import create_kline_chart


def _compute_drawdowns(values: list[float]) -> list[float]:
    arr = np.array(values)
    peak = np.maximum.accumulate(arr)
    dd = (arr - peak) / peak * 100
    return dd.tolist()


def _create_equity_chart(
    dates: list[str],
    equity: list[float],
) -> Grid:
    drawdowns = _compute_drawdowns(equity)
    visible_start = max(70, 100 - max(30, 100 * 90 // len(dates)))

    line = (
        Line()
        .add_xaxis(dates)
        .add_yaxis(
            series_name="权益曲线",
            y_axis=[round(v, 2) for v in equity],
            yaxis_index=0,
            is_smooth=True,
            symbol="none",
            linestyle_opts=opts.LineStyleOpts(color="#5c6bc0", width=2.5),
            areastyle_opts=opts.AreaStyleOpts(opacity=0.08, color="#5c6bc0"),
            label_opts=opts.LabelOpts(is_show=False),
        )
        .extend_axis(
            yaxis=opts.AxisOpts(
                type_="value",
                name="回撤 %",
                axislabel_opts=opts.LabelOpts(formatter="{value}%", font_size=11),
                splitline_opts=opts.SplitLineOpts(is_show=False),
            )
        )
        .add_yaxis(
            series_name="回撤",
            y_axis=[round(d, 2) for d in drawdowns],
            yaxis_index=1,
            is_smooth=True,
            symbol="none",
            linestyle_opts=opts.LineStyleOpts(color="#ef5350", width=1.5),
            areastyle_opts=opts.AreaStyleOpts(opacity=0.15, color="#ef5350"),
            label_opts=opts.LabelOpts(is_show=False),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title="权益曲线 & 回撤",
                pos_left="left",
                pos_top="2%",
                title_textstyle_opts=opts.TextStyleOpts(
                    font_size=18, font_weight="bold", color="#2c3e50"
                ),
            ),
            xaxis_opts=opts.AxisOpts(
                type_="category",
                axislabel_opts=opts.LabelOpts(rotate=30, font_size=10),
                axisline_opts=opts.AxisLineOpts(
                    linestyle_opts=opts.LineStyleOpts(color="#bdc3c7")
                ),
            ),
            yaxis_opts=opts.AxisOpts(
                type_="value",
                name="权益 (元)",
                axislabel_opts=opts.LabelOpts(formatter="{value}", font_size=11),
                splitline_opts=opts.SplitLineOpts(
                    is_show=True,
                    linestyle_opts=opts.LineStyleOpts(type_="dashed", opacity=0.3),
                ),
            ),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
            datazoom_opts=[
                opts.DataZoomOpts(type_="inside", range_start=visible_start, range_end=100),
                opts.DataZoomOpts(
                    type_="slider",
                    range_start=visible_start,
                    range_end=100,
                    pos_bottom="2%",
                ),
            ],
            legend_opts=opts.LegendOpts(pos_top="2%", pos_left="center"),
            toolbox_opts=opts.ToolboxOpts(
                is_show=True,
                pos_left="right",
                feature={"saveAsImage": {"title": "保存为图片"}},
            ),
        )
    )

    grid = Grid(init_opts=opts.InitOpts(
        width="100%", height="520px", bg_color="#ffffff",
    ))
    grid.add(line, grid_opts=opts.GridOpts(
        pos_top="16%", pos_bottom="16%", pos_left="10%", pos_right="5%",
    ))
    return grid


def _compute_stats(
    df_trades: Optional[pd.DataFrame],
    equity_data: Optional[pd.DataFrame],
) -> dict:
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
                    (stats["final_value"] - stats["initial_value"])
                    / stats["initial_value"] * 100,
                    2,
                )
            dd = _compute_drawdowns(eq)
            stats["max_drawdown"] = round(min(dd), 2) if dd else 0

    return stats


def _build_stats_html(stats: dict) -> str:
    cards: list[str] = []

    def _card(label: str, value: str, css_class: str = "") -> str:
        cls = f" {css_class}" if css_class else ""
        return (
            f'<div class="stat-card">'
            f'<div class="stat-label">{label}</div>'
            f'<div class="stat-value{cls}">{value}</div>'
            f'</div>'
        )

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


def _extract_chart_parts(html: str) -> tuple[str, str, str]:
    """从 pyecharts render_embed() 的完整 HTML 中提取 (echarts_js_src, div, script)。"""
    # 提取 echarts JS 库的 <script> 标签（只需第一个）
    lib_match = re.search(r'<script\s+type="text/javascript"\s+src="(https://[^"]+echarts[^"]*)"', html)
    echarts_src = lib_match.group(1) if lib_match else "https://assets.pyecharts.org/assets/v6/echarts.min.js"

    # 提取 chart-container div
    div_match = re.search(r'(<div\s+id="[^"]*"\s+class="chart-container"[^>]*></div>)', html)
    div_html = div_match.group(1) if div_match else ""

    # 提取初始化脚本
    script_match = re.search(r'(<script>\s*var\s+chart_.*?</script>)', html, re.DOTALL)
    script_html = script_match.group(1) if script_match else ""

    return echarts_src, div_html, script_html


def _build_page(
    symbol: str,
    strategy_name: str,
    stats: dict,
    echarts_src: str,
    kline_div: str,
    kline_script: str,
    equity_div: str,
    equity_script: str,
) -> str:
    stats_html = _build_stats_html(stats)

    equity_section = ""
    if equity_div and equity_script:
        equity_section = f"""
        <div class="chart-section">
            {equity_div}
        </div>
        {equity_script}"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{symbol} — {strategy_name} 回测报告</title>
<script src="{echarts_src}"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 "Helvetica Neue", Arial, "Microsoft YaHei", sans-serif;
    background: #f0f2f5;
    color: #2c3e50;
    line-height: 1.6;
}}
.container {{ max-width: 1420px; margin: 0 auto; padding: 24px; }}
.header {{
    background: linear-gradient(135deg, #2c3e50 0%, #34495e 100%);
    color: #fff; padding: 28px 36px; border-radius: 12px; margin-bottom: 24px;
}}
.header h1 {{ font-size: 22px; font-weight: 600; letter-spacing: .5px; }}
.header .subtitle {{ font-size: 13px; opacity: .75; margin-top: 4px; }}
.stats-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 16px; margin-bottom: 24px;
}}
.stat-card {{
    background: #fff; padding: 20px 24px; border-radius: 10px;
    box-shadow: 0 2px 8px rgba(0,0,0,.06);
    transition: transform .15s, box-shadow .15s;
}}
.stat-card:hover {{ transform: translateY(-2px); box-shadow: 0 4px 16px rgba(0,0,0,.1); }}
.stat-label {{ font-size: 13px; color: #7f8c8d; margin-bottom: 8px; }}
.stat-value {{ font-size: 24px; font-weight: 700; color: #2c3e50; }}
.stat-value.up {{ color: #ef5350; }}
.stat-value.down {{ color: #26a69a; }}
.chart-section {{
    background: #fff; padding: 20px 24px 28px; border-radius: 10px;
    box-shadow: 0 2px 8px rgba(0,0,0,.06); margin-bottom: 24px;
}}
.chart-section .chart-container {{ width: 100% !important; }}
.footer {{ text-align: center; color: #95a5a6; font-size: 12px; padding: 16px 0 8px; }}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>{symbol} &nbsp;&mdash;&nbsp; {strategy_name} &nbsp; 回测报告</h1>
        <div class="subtitle">A 股量化回测系统 &nbsp;|&nbsp; Generated by QuantYB</div>
    </div>
    <div class="stats-grid">
        {stats_html}
    </div>
    <div class="chart-section">
        {kline_div}
    </div>
    {kline_script}
    {equity_section}
    <div class="footer">QuantYB &copy; 2026</div>
</div>
</body>
</html>"""


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

    buy_marks: list[tuple[str, float]] = []
    sell_marks: list[tuple[str, float]] = []
    if df_trades is not None and not df_trades.empty:
        for _, row in df_trades.iterrows():
            if row["direction"] == "BUY":
                buy_marks.append((str(row["date"]), float(row["price"])))
            else:
                sell_marks.append((str(row["date"]), float(row["price"])))

    title = f"{symbol}  —  {strategy_name}"
    kline = create_kline_chart(dates, ohlc, buy_marks, sell_marks, title)
    kline_raw = kline.render_embed()
    echarts_src, kline_div, kline_script = _extract_chart_parts(kline_raw)

    equity_div = ""
    equity_script = ""
    if equity_data is not None and not equity_data.empty:
        equity_chart = _create_equity_chart(
            equity_data["dates"].tolist(),
            equity_data["equity"].tolist(),
        )
        equity_raw = equity_chart.render_embed()
        _, equity_div, equity_script = _extract_chart_parts(equity_raw)

    stats = _compute_stats(df_trades, equity_data)
    html = _build_page(
        symbol, strategy_name, stats,
        echarts_src, kline_div, kline_script,
        equity_div, equity_script,
    )

    output_path.write_text(html, encoding="utf-8")
