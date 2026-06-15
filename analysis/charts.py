"""Pyecharts 图表组件 —— 亮色主题"""

import hashlib
from typing import Optional

import numpy as np
import pandas as pd
from pyecharts.charts import Bar, Boxplot, Grid, Line, Radar, Scatter
from pyecharts import options as opts

# ---- 亮色主题常量 ----
_BG_COLOR = "white"
_TITLE_COLOR = "#1a1a2e"
_TEXT_COLOR = "#5a5a6e"
_AXIS_LABEL_COLOR = "#6b6b7b"
_AXIS_LINE_COLOR = "#d0d0d8"
_SPLIT_LINE_COLOR = "#e8e8ec"
_UP_COLOR = "#ef5350"
_DOWN_COLOR = "#26a69a"
_BLUE = "#5470c6"
_ORANGE = "#fac858"
_GREEN = "#73c0de"
_PURPLE = "#9a7fd4"
_RED = "#ee6666"
_CYAN = "#3ba272"
_STRATEGY_COLORS = ["#5470c6", "#fac858", "#ee6666", "#73c0de", "#9a7fd4", "#3ba272", "#fc8452"]

_STRATEGY_LABELS = {
    "sma_cross": "双均线", "macd_cross": "MACD",
    "kdj": "KDJ", "bollinger": "布林带", "rsi": "RSI", "single_ma": "单均线",
    "volume_platform_breakout": "放量突破",
}


def _base_grid(chart, title: str, height: str = "480px") -> Grid:
    """包装图表到 Grid，添加统一亮色风格。"""
    chart.set_global_opts(
        title_opts=opts.TitleOpts(
            title=title, pos_left="left", pos_top="10px",
            title_textstyle_opts=opts.TextStyleOpts(
                font_size=16, font_weight="bold", color=_TITLE_COLOR,
            ),
        ),
        legend_opts=opts.LegendOpts(
            pos_top="8px", pos_left="right",
            textstyle_opts=opts.TextStyleOpts(color=_TEXT_COLOR, font_size=11),
        ),
    )
    grid = Grid(init_opts=opts.InitOpts(
        width="100%", height=height, bg_color=_BG_COLOR,
    ))
    grid.add(chart, grid_opts=opts.GridOpts(
        pos_top="60px", pos_bottom="40px", pos_left="12%", pos_right="5%",
    ))
    return grid


def _x_axis() -> opts.AxisOpts:
    return opts.AxisOpts(
        axislabel_opts=opts.LabelOpts(font_size=11, color=_AXIS_LABEL_COLOR),
        axisline_opts=opts.AxisLineOpts(linestyle_opts=opts.LineStyleOpts(color=_AXIS_LINE_COLOR)),
    )


def _y_axis(name: str = "") -> opts.AxisOpts:
    extra = {}
    if name:
        extra["name"] = name
        extra["name_textstyle_opts"] = opts.TextStyleOpts(font_size=11, color=_AXIS_LABEL_COLOR)
    return opts.AxisOpts(
        axislabel_opts=opts.LabelOpts(font_size=11, color=_AXIS_LABEL_COLOR),
        axisline_opts=opts.AxisLineOpts(linestyle_opts=opts.LineStyleOpts(color=_AXIS_LINE_COLOR)),
        splitline_opts=opts.SplitLineOpts(
            is_show=True,
            linestyle_opts=opts.LineStyleOpts(type_="dashed", color=_SPLIT_LINE_COLOR),
        ),
        **extra,
    )


# ============================================================
#  单策略分析图表
# ============================================================

def create_return_histogram(hist_data: list[dict], avg: float, median: float,
                            strategy_name: str) -> Grid:
    """收益率分布直方图，标注均值和中位数。"""
    labels = [d["label"] for d in hist_data]
    counts = [d["count"] for d in hist_data]
    colors = [d["color"] for d in hist_data]

    bar = (
        Bar()
        .add_xaxis(labels)
        .add_yaxis("股票数量", counts,
                   itemstyle_opts=opts.ItemStyleOpts(color=colors),
                   label_opts=opts.LabelOpts(is_show=False))
        .set_global_opts(
            xaxis_opts=opts.AxisOpts(
                name="收益率 %",
                axislabel_opts=opts.LabelOpts(font_size=10, color=_AXIS_LABEL_COLOR, rotate=45),
                axisline_opts=opts.AxisLineOpts(linestyle_opts=opts.LineStyleOpts(color=_AXIS_LINE_COLOR)),
            ),
            yaxis_opts=opts.AxisOpts(
                name="股票数量",
                axislabel_opts=opts.LabelOpts(font_size=11, color=_AXIS_LABEL_COLOR),
                splitline_opts=opts.SplitLineOpts(
                    is_show=True,
                    linestyle_opts=opts.LineStyleOpts(type_="dashed", color=_SPLIT_LINE_COLOR),
                ),
            ),
        )
    )

    # 均值线
    line_avg = (
        Line()
        .add_xaxis([float(labels[0].split("~")[0]) if "~" in labels[0] else float(labels[0]),
                     float(labels[-1].split("~")[-1]) if "~" in labels[-1] else float(labels[-1])])
        .add_yaxis(
            f"均值 {avg:+.1f}%",
            [max(counts) * 0.95, max(counts) * 0.95],
            linestyle_opts=opts.LineStyleOpts(color="#ef5350", type_="dashed", width=2),
            label_opts=opts.LabelOpts(is_show=False),
            symbol="none",
        )
    )

    # 中位数线
    line_median = (
        Line()
        .add_xaxis([float(labels[0].split("~")[0]) if "~" in labels[0] else float(labels[0]),
                     float(labels[-1].split("~")[-1]) if "~" in labels[-1] else float(labels[-1])])
        .add_yaxis(
            f"中位数 {median:+.1f}%",
            [max(counts) * 0.85, max(counts) * 0.85],
            linestyle_opts=opts.LineStyleOpts(color="#5470c6", type_="dashed", width=2),
            label_opts=opts.LabelOpts(is_show=False),
            symbol="none",
        )
    )

    bar.overlap(line_avg)
    bar.overlap(line_median)

    display_name = _STRATEGY_LABELS.get(strategy_name, strategy_name)
    return _base_grid(bar, f"{display_name} — 收益率分布", "460px")


def create_risk_scatter(scatter_data: list[dict], strategy_name: str) -> Grid:
    """风险/收益散点图：X=最大回撤, Y=收益率, 颜色=胜率。"""
    # 按胜率分三层
    low_wr = [d for d in scatter_data if d["win_rate"] < 40]
    mid_wr = [d for d in scatter_data if 40 <= d["win_rate"] <= 60]
    high_wr = [d for d in scatter_data if d["win_rate"] > 60]

    scatter = Scatter()
    scatter.add_xaxis([d["max_dd"] for d in scatter_data])

    if low_wr:
        scatter.add_yaxis(
            "胜率 < 40%",
            [[d["max_dd"], d["return_pct"]] for d in low_wr],
            symbol_size=5,
            symbol="circle",
            itemstyle_opts=opts.ItemStyleOpts(color="#ccc", border_width=0),
            label_opts=opts.LabelOpts(is_show=False),
        )
    if mid_wr:
        scatter.add_yaxis(
            "胜率 40-60%",
            [[d["max_dd"], d["return_pct"]] for d in mid_wr],
            symbol_size=5,
            symbol="circle",
            itemstyle_opts=opts.ItemStyleOpts(color=_BLUE, border_width=0),
            label_opts=opts.LabelOpts(is_show=False),
        )
    if high_wr:
        scatter.add_yaxis(
            "胜率 > 60%",
            [[d["max_dd"], d["return_pct"]] for d in high_wr],
            symbol_size=5,
            symbol="circle",
            itemstyle_opts=opts.ItemStyleOpts(color=_UP_COLOR, border_width=0),
            label_opts=opts.LabelOpts(is_show=False),
        )

    scatter.set_global_opts(
        xaxis_opts=opts.AxisOpts(
            name="最大回撤 %",
            axislabel_opts=opts.LabelOpts(font_size=11, color=_AXIS_LABEL_COLOR),
            axisline_opts=opts.AxisLineOpts(linestyle_opts=opts.LineStyleOpts(color=_AXIS_LINE_COLOR)),
        ),
        yaxis_opts=opts.AxisOpts(
            name="收益率 %",
            axislabel_opts=opts.LabelOpts(font_size=11, color=_AXIS_LABEL_COLOR),
            splitline_opts=opts.SplitLineOpts(
                is_show=True,
                linestyle_opts=opts.LineStyleOpts(type_="dashed", color=_SPLIT_LINE_COLOR),
            ),
        ),
    )

    display_name = _STRATEGY_LABELS.get(strategy_name, strategy_name)
    return _base_grid(scatter, f"{display_name} — 风险/收益散点", "500px")


def create_sharpe_histogram(df: pd.DataFrame, strategy_name: str) -> Grid:
    """夏普比率分布直方图。"""
    sharpe = df["sharpe_ratio"].values
    hist, edges = np.histogram(sharpe, bins=40)
    labels = [f"{edges[i]:.2f}" for i in range(len(edges) - 1)]
    colors = ["#26a69a" if float(l) < 0 else "#ef5350" for l in labels]

    bar = (
        Bar()
        .add_xaxis(labels)
        .add_yaxis(
            "股票数量", hist.tolist(),
            itemstyle_opts=opts.ItemStyleOpts(color=colors),
            label_opts=opts.LabelOpts(is_show=False),
        )
        .set_global_opts(
            xaxis_opts=opts.AxisOpts(
                name="夏普比率",
                axislabel_opts=opts.LabelOpts(font_size=10, color=_AXIS_LABEL_COLOR, rotate=45),
                axisline_opts=opts.AxisLineOpts(linestyle_opts=opts.LineStyleOpts(color=_AXIS_LINE_COLOR)),
            ),
            yaxis_opts=_y_axis("股票数量"),
        )
    )

    display_name = _STRATEGY_LABELS.get(strategy_name, strategy_name)
    return _base_grid(bar, f"{display_name} — 夏普比率分布", "420px")


def create_trade_histogram(df: pd.DataFrame, strategy_name: str) -> Grid:
    """交易次数分布直方图。"""
    trades = df["total_trades"].values
    max_t = int(trades.max())
    bins = max(1, min(max_t, 30))
    hist, edges = np.histogram(trades, bins=bins)
    labels = [str(int(edges[i])) for i in range(len(edges) - 1)]

    bar = (
        Bar()
        .add_xaxis(labels)
        .add_yaxis(
            "股票数量", hist.tolist(),
            itemstyle_opts=opts.ItemStyleOpts(color=_BLUE),
            label_opts=opts.LabelOpts(is_show=False),
        )
        .set_global_opts(
            xaxis_opts=opts.AxisOpts(
                name="交易次数",
                axislabel_opts=opts.LabelOpts(font_size=11, color=_AXIS_LABEL_COLOR),
                axisline_opts=opts.AxisLineOpts(linestyle_opts=opts.LineStyleOpts(color=_AXIS_LINE_COLOR)),
            ),
            yaxis_opts=_y_axis("股票数量"),
        )
    )

    display_name = _STRATEGY_LABELS.get(strategy_name, strategy_name)
    return _base_grid(bar, f"{display_name} — 交易次数分布", "420px")


def _finite_series(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(dtype="float64")
    return pd.to_numeric(df[col], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()


def create_profit_factor_histogram(df: pd.DataFrame, strategy_name: str) -> Optional[Grid]:
    """Profit Factor 分布。无亏损导致的无限值在引擎侧留空，这里只展示可有限估计值。"""
    vals = _finite_series(df, "profit_factor")
    if vals.empty:
        return None
    vals = vals.clip(upper=10)
    hist, edges = np.histogram(vals.values, bins=min(30, max(1, len(vals))))
    labels = [f"{edges[i]:.2f}" for i in range(len(edges) - 1)]
    colors = [_UP_COLOR if float(label) >= 1 else _DOWN_COLOR for label in labels]

    bar = (
        Bar()
        .add_xaxis(labels)
        .add_yaxis(
            "股票数量", hist.tolist(),
            itemstyle_opts=opts.ItemStyleOpts(color=colors),
            label_opts=opts.LabelOpts(is_show=False),
        )
        .set_global_opts(
            xaxis_opts=opts.AxisOpts(
                name="Profit Factor（>10 截顶）",
                axislabel_opts=opts.LabelOpts(font_size=10, color=_AXIS_LABEL_COLOR, rotate=45),
                axisline_opts=opts.AxisLineOpts(linestyle_opts=opts.LineStyleOpts(color=_AXIS_LINE_COLOR)),
            ),
            yaxis_opts=_y_axis("股票数量"),
        )
    )

    display_name = _STRATEGY_LABELS.get(strategy_name, strategy_name)
    return _base_grid(bar, f"{display_name} — Profit Factor 分布", "420px")


def create_drawdown_duration_histogram(df: pd.DataFrame, strategy_name: str) -> Optional[Grid]:
    """最大回撤持续天数分布。"""
    vals = _finite_series(df, "max_drawdown_days")
    if vals.empty:
        return None
    hist, edges = np.histogram(vals.values, bins=min(30, max(1, int(vals.max()) or 1)))
    labels = [str(int(edges[i])) for i in range(len(edges) - 1)]

    bar = (
        Bar()
        .add_xaxis(labels)
        .add_yaxis(
            "股票数量", hist.tolist(),
            itemstyle_opts=opts.ItemStyleOpts(color=_PURPLE),
            label_opts=opts.LabelOpts(is_show=False),
        )
        .set_global_opts(
            xaxis_opts=opts.AxisOpts(
                name="最大回撤持续天数",
                axislabel_opts=opts.LabelOpts(font_size=10, color=_AXIS_LABEL_COLOR, rotate=45),
                axisline_opts=opts.AxisLineOpts(linestyle_opts=opts.LineStyleOpts(color=_AXIS_LINE_COLOR)),
            ),
            yaxis_opts=_y_axis("股票数量"),
        )
    )

    display_name = _STRATEGY_LABELS.get(strategy_name, strategy_name)
    return _base_grid(bar, f"{display_name} — 回撤持续时间分布", "420px")


def create_trade_pnl_histogram(df: pd.DataFrame, strategy_name: str) -> Optional[Grid]:
    """按单标的平均平仓 PnL 展示交易质量分布。"""
    vals = _finite_series(df, "avg_trade_pnl")
    if vals.empty:
        return None
    hist, edges = np.histogram(vals.values, bins=min(40, max(1, len(vals))))
    labels = [f"{edges[i]:.0f}" for i in range(len(edges) - 1)]
    colors = [_UP_COLOR if float(label) >= 0 else _DOWN_COLOR for label in labels]

    bar = (
        Bar()
        .add_xaxis(labels)
        .add_yaxis(
            "股票数量", hist.tolist(),
            itemstyle_opts=opts.ItemStyleOpts(color=colors),
            label_opts=opts.LabelOpts(is_show=False),
        )
        .set_global_opts(
            xaxis_opts=opts.AxisOpts(
                name="平均平仓 PnL",
                axislabel_opts=opts.LabelOpts(font_size=10, color=_AXIS_LABEL_COLOR, rotate=45),
                axisline_opts=opts.AxisLineOpts(linestyle_opts=opts.LineStyleOpts(color=_AXIS_LINE_COLOR)),
            ),
            yaxis_opts=_y_axis("股票数量"),
        )
    )

    display_name = _STRATEGY_LABELS.get(strategy_name, strategy_name)
    return _base_grid(bar, f"{display_name} — 平均交易盈亏分布", "420px")


def create_monte_carlo_paths(df: pd.DataFrame, strategy_name: str) -> Optional[Grid]:
    """基于全市场单标的收益分布的简单 Monte Carlo 风险模拟。"""
    vals = _finite_series(df, "total_return_pct") / 100.0
    vals = vals[vals != 0]
    if len(vals) < 5:
        return None

    seed = int(hashlib.sha256(strategy_name.encode("utf-8")).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    steps = 40
    sims = 300
    samples = rng.choice(vals.values, size=(sims, steps), replace=True)
    paths = 100 * np.cumprod(1 + samples, axis=1)
    p10 = np.percentile(paths, 10, axis=0)
    p50 = np.percentile(paths, 50, axis=0)
    p90 = np.percentile(paths, 90, axis=0)
    labels = [str(i + 1) for i in range(steps)]

    line = Line().add_xaxis(labels)
    for i in range(min(12, sims)):
        line.add_yaxis(
            f"样本路径 {i + 1}",
            [round(float(v), 2) for v in paths[i]],
            symbol="none",
            is_smooth=True,
            linestyle_opts=opts.LineStyleOpts(color="#c9cdd8", width=1, opacity=0.35),
            label_opts=opts.LabelOpts(is_show=False),
        )
    line.add_yaxis(
        "P10",
        [round(float(v), 2) for v in p10],
        symbol="none",
        is_smooth=True,
        linestyle_opts=opts.LineStyleOpts(color=_DOWN_COLOR, width=2),
        label_opts=opts.LabelOpts(is_show=False),
    )
    line.add_yaxis(
        "P50",
        [round(float(v), 2) for v in p50],
        symbol="none",
        is_smooth=True,
        linestyle_opts=opts.LineStyleOpts(color=_BLUE, width=2.5),
        label_opts=opts.LabelOpts(is_show=False),
    )
    line.add_yaxis(
        "P90",
        [round(float(v), 2) for v in p90],
        symbol="none",
        is_smooth=True,
        linestyle_opts=opts.LineStyleOpts(color=_UP_COLOR, width=2),
        label_opts=opts.LabelOpts(is_show=False),
    )
    line.set_global_opts(
        xaxis_opts=opts.AxisOpts(
            name="模拟步数",
            axislabel_opts=opts.LabelOpts(font_size=11, color=_AXIS_LABEL_COLOR),
            axisline_opts=opts.AxisLineOpts(linestyle_opts=opts.LineStyleOpts(color=_AXIS_LINE_COLOR)),
        ),
        yaxis_opts=_y_axis("初始 100"),
        tooltip_opts=opts.TooltipOpts(trigger="axis"),
    )

    display_name = _STRATEGY_LABELS.get(strategy_name, strategy_name)
    return _base_grid(line, f"{display_name} — Monte Carlo 收益路径模拟", "480px")


# ============================================================
#  多策略对比图表
# ============================================================

def create_radar_chart(stats_map: dict[str, dict],
                       normed: dict[str, list[float]]) -> Grid:
    """多策略雷达图：6 维度对比。"""
    metrics = ["avg_return", "avg_sharpe", "avg_win_rate",
               "positive_ratio", "avg_max_dd", "avg_trades"]
    metric_labels = ["收益率", "夏普比率", "胜率", "正向率", "回撤控制", "交易活跃度"]

    schema = [opts.RadarIndicatorItem(name=ml, min_=0, max_=100) for ml in metric_labels]

    radar = Radar()
    radar.add_schema(schema=schema, shape="polygon",
                     center=["50%", "52%"],
                     radius="68%",
                     splitarea_opt=opts.SplitAreaOpts(
                         is_show=True,
                         areastyle_opts=opts.AreaStyleOpts(
                             opacity=0.08,
                             color=["#5470c6", "transparent"],
                         ),
                     ),
                     axisline_opt=opts.AxisLineOpts(
                         linestyle_opts=opts.LineStyleOpts(color="#d0d0d8"),
                     ),
                     splitline_opt=opts.SplitLineOpts(
                         linestyle_opts=opts.LineStyleOpts(color="#e8e8ec"),
                     ),
                     textstyle_opts=opts.TextStyleOpts(color=_TEXT_COLOR, font_size=12),
                     )

    names = list(stats_map.keys())
    for i, name in enumerate(names):
        color = _STRATEGY_COLORS[i % len(_STRATEGY_COLORS)]
        label = _STRATEGY_LABELS.get(name, name)
        radar.add(
            series_name=label,
            data=[normed[name]],
            areastyle_opts=opts.AreaStyleOpts(opacity=0.08, color=color),
            linestyle_opts=opts.LineStyleOpts(color=color, width=2),
            label_opts=opts.LabelOpts(is_show=False),
            color=color,
            symbol="circle",
        )

    radar.set_global_opts(
        title_opts=opts.TitleOpts(
            title="策略多维对比 — 雷达图", pos_left="left", pos_top="10px",
            title_textstyle_opts=opts.TextStyleOpts(
                font_size=16, font_weight="bold", color=_TITLE_COLOR,
            ),
        ),
        legend_opts=opts.LegendOpts(
            pos_top="8px", pos_left="right", orient="vertical",
            textstyle_opts=opts.TextStyleOpts(color=_TEXT_COLOR, font_size=10),
        ),
    )

    return Grid(init_opts=opts.InitOpts(width="100%", height="520px", bg_color=_BG_COLOR)).add(
        radar, grid_opts=opts.GridOpts(pos_top="50px", pos_bottom="10px", pos_left="5%", pos_right="20%"),
    )


def create_boxplot_comparison(data_map: dict[str, pd.DataFrame]) -> Grid:
    """多策略收益率箱线图对比。"""
    names = list(data_map.keys())
    labels = [_STRATEGY_LABELS.get(n, n) for n in names]
    series_data = [data_map[n]["total_return_pct"].tolist() for n in names]

    box = Boxplot()
    box.add_xaxis(labels)
    for i, (sd, name) in enumerate(zip(series_data, names)):
        color = _STRATEGY_COLORS[i % len(_STRATEGY_COLORS)]
        box.add_yaxis(
            _STRATEGY_LABELS.get(name, name),
            box.prepare_data([sd]),
            itemstyle_opts=opts.ItemStyleOpts(
                color=color,
                border_color=color,
            ),
        )

    box.set_global_opts(
        xaxis_opts=opts.AxisOpts(
            axislabel_opts=opts.LabelOpts(font_size=11, color=_TEXT_COLOR),
            axisline_opts=opts.AxisLineOpts(linestyle_opts=opts.LineStyleOpts(color=_AXIS_LINE_COLOR)),
        ),
        yaxis_opts=opts.AxisOpts(
            name="收益率 %",
            axislabel_opts=opts.LabelOpts(font_size=11, color=_AXIS_LABEL_COLOR),
            splitline_opts=opts.SplitLineOpts(
                is_show=True,
                linestyle_opts=opts.LineStyleOpts(type_="dashed", color=_SPLIT_LINE_COLOR),
            ),
        ),
    )

    return _base_grid(box, "收益率分布对比 — 箱线图", "480px")


def create_bar_comparison(data_map: dict[str, pd.DataFrame]) -> Grid:
    """多策略核心指标柱状图对比（收益率、夏普、胜率、正向率）。"""
    names = list(data_map.keys())
    labels = [_STRATEGY_LABELS.get(n, n) for n in names]

    avg_returns = [round(data_map[n]["total_return_pct"].mean(), 2) for n in names]
    avg_sharpe = [round(data_map[n]["sharpe_ratio"].mean(), 4) for n in names]
    avg_wr = [round(data_map[n]["win_rate_pct"].mean(), 1) for n in names]
    pos_ratios = [round((data_map[n]["total_return_pct"] > 0).sum() / len(data_map[n]) * 100, 1) for n in names]

    bar = (
        Bar()
        .add_xaxis(labels)
        .add_yaxis("平均收益率 %", avg_returns,
                   itemstyle_opts=opts.ItemStyleOpts(color=_BLUE),
                   label_opts=opts.LabelOpts(is_show=False))
        .add_yaxis("夏普比率 ×100", [round(s * 100, 1) for s in avg_sharpe],
                   itemstyle_opts=opts.ItemStyleOpts(color=_ORANGE),
                   label_opts=opts.LabelOpts(is_show=False))
        .add_yaxis("平均胜率 %", avg_wr,
                   itemstyle_opts=opts.ItemStyleOpts(color=_GREEN),
                   label_opts=opts.LabelOpts(is_show=False))
        .add_yaxis("正收益比例 %", pos_ratios,
                   itemstyle_opts=opts.ItemStyleOpts(color=_PURPLE),
                   label_opts=opts.LabelOpts(is_show=False))
        .set_global_opts(
            xaxis_opts=opts.AxisOpts(
                axislabel_opts=opts.LabelOpts(font_size=11, color=_TEXT_COLOR),
                axisline_opts=opts.AxisLineOpts(linestyle_opts=opts.LineStyleOpts(color=_AXIS_LINE_COLOR)),
            ),
            yaxis_opts=_y_axis(""),
        )
    )

    return _base_grid(bar, "核心指标柱状图对比", "440px")


def create_correlation_heatmap(corr_df: pd.DataFrame) -> Optional[Grid]:
    """策略收益率相关性热力图。"""
    if corr_df.empty:
        return None

    strategies = corr_df.columns.tolist()
    data = []
    x_labels = [_STRATEGY_LABELS.get(s, s) for s in strategies]
    y_labels = x_labels

    for i, row_name in enumerate(strategies):
        for j, col_name in enumerate(strategies):
            val = corr_df.loc[row_name, col_name]
            data.append([j, i, round(float(val), 3)])

    min_val = min(d[2] for d in data)
    max_val = max(d[2] for d in data)

    heatmap = (
        Bar()
        .add_xaxis(x_labels)
        .add_yaxis("", [[d[1], d[2]] for d in data])
    )

    # 使用 Scatter 构建热力图效果
    scatter = (
        Scatter()
        .add_xaxis(x_labels)
    )

    # 实际上用 Bar 的堆叠做热力图比较复杂。
    # 改用简单方案：创建一个自定义的 Grid，用多个系列展示矩阵值
    pass

    # 简化方案：用柱状图展示每个策略对的相关系数
    pairs = []
    pair_vals = []
    pair_colors = []
    for i, s1 in enumerate(strategies):
        for j, s2 in enumerate(strategies):
            if i < j:  # 只取上三角
                val = corr_df.loc[s1, s2]
                pairs.append(f"{_STRATEGY_LABELS.get(s1, s1)} vs {_STRATEGY_LABELS.get(s2, s2)}")
                pair_vals.append(round(float(val), 3))
                pair_colors.append(_UP_COLOR if val > 0 else _DOWN_COLOR)

    bar = (
        Bar()
        .add_xaxis(pairs)
        .add_yaxis(
            "Spearman 秩相关",
            pair_vals,
            itemstyle_opts=opts.ItemStyleOpts(color=pair_colors),
            label_opts=opts.LabelOpts(
                is_show=True, position="top",
                font_size=10, color=_TEXT_COLOR,
            ),
        )
        .set_global_opts(
            xaxis_opts=opts.AxisOpts(
                axislabel_opts=opts.LabelOpts(font_size=10, color=_TEXT_COLOR, rotate=30),
                axisline_opts=opts.AxisLineOpts(linestyle_opts=opts.LineStyleOpts(color=_AXIS_LINE_COLOR)),
            ),
            yaxis_opts=opts.AxisOpts(
                name="相关系数", min_=-1, max_=1,
                axislabel_opts=opts.LabelOpts(font_size=11, color=_AXIS_LABEL_COLOR),
                splitline_opts=opts.SplitLineOpts(
                    is_show=True,
                    linestyle_opts=opts.LineStyleOpts(type_="dashed", color=_SPLIT_LINE_COLOR),
                ),
            ),
        )
    )

    return _base_grid(bar, "策略收益率相关性（Spearman）", "420px")


def create_bubble_chart(data_map: dict[str, pd.DataFrame]) -> Grid:
    """多策略风险收益气泡图：X=回撤, Y=收益, 颜色=策略。"""
    scatter = Scatter()
    scatter.add_xaxis([])

    names = list(data_map.keys())
    for i, name in enumerate(names):
        df = data_map[name]
        color = _STRATEGY_COLORS[i % len(_STRATEGY_COLORS)]
        label = _STRATEGY_LABELS.get(name, name)

        points = []
        for _, row in df.iterrows():
            dd = float(row["max_drawdown_pct"])
            ret = float(row["total_return_pct"])
            points.append([dd, ret])

        if points:
            scatter.add_yaxis(
                label,
                points,
                symbol_size=5,
                itemstyle_opts=opts.ItemStyleOpts(color=color, opacity=0.4, border_width=0),
                label_opts=opts.LabelOpts(is_show=False),
            )

    scatter.set_global_opts(
        xaxis_opts=opts.AxisOpts(
            type_="value", name="最大回撤 %",
            axislabel_opts=opts.LabelOpts(font_size=11, color=_AXIS_LABEL_COLOR),
            axisline_opts=opts.AxisLineOpts(linestyle_opts=opts.LineStyleOpts(color=_AXIS_LINE_COLOR)),
        ),
        yaxis_opts=opts.AxisOpts(
            type_="value", name="收益率 %",
            axislabel_opts=opts.LabelOpts(font_size=11, color=_AXIS_LABEL_COLOR),
            splitline_opts=opts.SplitLineOpts(
                is_show=True,
                linestyle_opts=opts.LineStyleOpts(type_="dashed", color=_SPLIT_LINE_COLOR),
            ),
        ),
    )

    return _base_grid(scatter, "策略风险收益散点图", "520px")


# ============================================================
#  Rendering helper
# ============================================================

def render_charts(charts: list) -> list[dict]:
    """Render pyecharts chart objects to {div, script, var_name} dicts.

    Each chart is rendered via render_embed() and parsed for embedding.
    """
    import re

    results = []
    for chart in charts:
        if chart is None:
            continue
        raw = chart.render_embed()

        lib_match = re.search(r'<script\s+type="text/javascript"\s+src="(https://[^"]+echarts[^"]*)"', raw)
        echarts_src = lib_match.group(1) if lib_match else "https://assets.pyecharts.org/assets/v6/echarts.min.js"

        div_match = re.search(r'(<div\s+id="[^"]*"[^>]*></div>)', raw)
        div_html = div_match.group(1) if div_match else ""

        script_match = re.search(r'(<script>\s*var\s+chart_.*?</script>)', raw, re.DOTALL)
        script_html = script_match.group(1) if script_match else ""

        var_match = re.search(r'var\s+(chart_\w+)', script_html)
        var_name = var_match.group(1) if var_match else ""

        results.append({
            "echarts_src": echarts_src,
            "div": div_html,
            "script": script_html,
            "var": var_name,
        })

    return results
