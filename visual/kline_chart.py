"""K线图 + 均线叠加 + 成交量柱（pyecharts）—— Midnight 暗色主题"""

import inspect

from pyecharts.charts import Kline, Bar, Line, Grid
from pyecharts import options as opts

# pyecharts 各版本 MarkPointItem 支持的参数不同，运行时自动检测
_MARKPOINT_VALID_PARAMS = set(inspect.signature(opts.MarkPointItem.__init__).parameters.keys())

# ---- 暗色主题常量 ----
_CHART_BG = "#1a1d23"
_TITLE_COLOR = "#e4e4e4"
_AXIS_LABEL_COLOR = "#8b8d93"
_AXIS_LINE_COLOR = "rgba(255,255,255,0.1)"
_SPLIT_LINE_COLOR = "rgba(255,255,255,0.06)"
_UP_COLOR = "#f06070"        # 涨（K线阳线、买点）
_DOWN_COLOR = "#4ecb71"      # 跌（K线阴线、卖点）
_DIF_COLOR = "#6c8cff"       # MACD DIF / KDJ K / RSI
_DEA_COLOR = "#f0a030"       # MACD DEA / KDJ D
_J_COLOR = "#f06070"         # KDJ J
_MA_COLORS = ["#e8b830", "#60a5fa", "#a78bfa", "#fb7185"]  # MA5/10/20/60

# ---------------------------------------------------------------------------
#  兼容辅助
# ---------------------------------------------------------------------------

def _make_mark_point_item(name, coord, value, symbol, symbol_size,
                          symbol_rotate=None, itemstyle_opts=None, label_opts=None):
    """创建 MarkPointItem，自动过滤当前 pyecharts 版本不支持的参数"""
    kwargs = {k: v for k, v in dict(
        name=name, coord=coord, value=value,
        symbol=symbol, symbol_size=symbol_size,
        symbol_rotate=symbol_rotate,
        itemstyle_opts=itemstyle_opts,
        label_opts=label_opts,
    ).items() if v is not None and k in _MARKPOINT_VALID_PARAMS}
    return opts.MarkPointItem(**kwargs)


def _dark_axis_opts(is_category=True, boundary_gap=True, show_split=True,
                    y_min=None, y_max=None, y_name=""):
    """构建暗色主题通用轴配置"""
    extra = {}
    if y_min is not None:
        extra["min_"] = y_min
    if y_max is not None:
        extra["max_"] = y_max
    if y_name:
        extra["name"] = y_name
        extra["name_textstyle_opts"] = opts.TextStyleOpts(font_size=10, color=_AXIS_LABEL_COLOR)
    return opts.AxisOpts(
        type_="category" if is_category else "value",
        boundary_gap=boundary_gap,
        axislabel_opts=opts.LabelOpts(rotate=30, font_size=10, color=_AXIS_LABEL_COLOR),
        axisline_opts=opts.AxisLineOpts(linestyle_opts=opts.LineStyleOpts(color=_AXIS_LINE_COLOR)),
        splitline_opts=opts.SplitLineOpts(
            is_show=show_split,
            linestyle_opts=opts.LineStyleOpts(type_="dashed", color=_SPLIT_LINE_COLOR),
        ) if show_split else None,
        **extra,
    )


def _dark_yaxis(is_scale=False, y_min=None, y_max=None, y_name=""):
    """暗色主题 Y 轴"""
    extra = {}
    if y_min is not None:
        extra["min_"] = y_min
    if y_max is not None:
        extra["max_"] = y_max
    extra["is_scale"] = is_scale
    if y_name:
        extra["name"] = y_name
        extra["name_textstyle_opts"] = opts.TextStyleOpts(font_size=10, color=_AXIS_LABEL_COLOR)
    return opts.AxisOpts(
        type_="value",
        axislabel_opts=opts.LabelOpts(font_size=11, color=_AXIS_LABEL_COLOR),
        splitline_opts=opts.SplitLineOpts(
            is_show=True,
            linestyle_opts=opts.LineStyleOpts(type_="dashed", color=_SPLIT_LINE_COLOR),
        ),
        splitarea_opts=opts.SplitAreaOpts(
            is_show=True,
            areastyle_opts=opts.AreaStyleOpts(opacity=0.04),
        ),
        **extra,
    )


def _dark_yaxis_compact(y_min=None, y_max=None, y_name=""):
    """暗色 Y 轴（紧凑版，无 splitarea）"""
    extra = {}
    if y_min is not None:
        extra["min_"] = y_min
    if y_max is not None:
        extra["max_"] = y_max
    if y_name:
        extra["name"] = y_name
        extra["name_textstyle_opts"] = opts.TextStyleOpts(font_size=10, color=_AXIS_LABEL_COLOR)
    return opts.AxisOpts(
        type_="value",
        axislabel_opts=opts.LabelOpts(font_size=10, color=_AXIS_LABEL_COLOR),
        splitline_opts=opts.SplitLineOpts(
            is_show=True,
            linestyle_opts=opts.LineStyleOpts(type_="dashed", color=_SPLIT_LINE_COLOR),
        ),
        **extra,
    )


# ---------------------------------------------------------------------------
#  图表函数
# ---------------------------------------------------------------------------

def create_kline_chart(
    dates: list[str],
    ohlc: list[list[float]],
    buy_marks: list[tuple[str, float]],
    sell_marks: list[tuple[str, float]],
    title: str = "K 线图",
    ma5: list = None,
    ma10: list = None,
    ma20: list = None,
    ma60: list = None,
) -> Grid:
    mark_data = []

    for date_str, price in buy_marks:
        mark_data.append(_make_mark_point_item(
            name="买入", coord=[date_str, price], value="买入",
            symbol="triangle", symbol_size=26,
            itemstyle_opts=opts.ItemStyleOpts(
                color=_UP_COLOR, border_color="#ffffff", border_width=2,
            ),
            label_opts=opts.LabelOpts(is_show=True, position="top", font_size=11,
                                      font_weight="bold", color=_UP_COLOR, distance=8),
        ))

    for date_str, price in sell_marks:
        mark_data.append(_make_mark_point_item(
            name="卖出", coord=[date_str, price], value="卖出",
            symbol="triangle", symbol_rotate=180, symbol_size=26,
            itemstyle_opts=opts.ItemStyleOpts(
                color=_DOWN_COLOR, border_color="#ffffff", border_width=2,
            ),
            label_opts=opts.LabelOpts(is_show=True, position="bottom", font_size=11,
                                      font_weight="bold", color=_DOWN_COLOR, distance=8),
        ))

    visible_start = max(70, 100 - max(30, 100 * 90 // len(dates)))

    kline = (
        Kline(init_opts=opts.InitOpts(width="100%", height="500px", bg_color=_CHART_BG))
        .add_xaxis(dates)
        .add_yaxis(
            series_name="K线", y_axis=ohlc,
            markpoint_opts=opts.MarkPointOpts(data=mark_data),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title=title, pos_left="left", pos_top="2%",
                title_textstyle_opts=opts.TextStyleOpts(font_size=18, font_weight="bold", color=_TITLE_COLOR),
            ),
            xaxis_opts=_dark_axis_opts(),
            yaxis_opts=_dark_yaxis(is_scale=True),
            legend_opts=opts.LegendOpts(
                pos_top="2%", pos_left="center",
                textstyle_opts=opts.TextStyleOpts(color=_AXIS_LABEL_COLOR),
            ),
            datazoom_opts=[
                opts.DataZoomOpts(type_="inside", range_start=visible_start, range_end=100),
                opts.DataZoomOpts(type_="slider", range_start=visible_start, range_end=100, pos_bottom="2%"),
            ],
            tooltip_opts=opts.TooltipOpts(trigger="axis", axis_pointer_type="cross"),
            toolbox_opts=opts.ToolboxOpts(
                is_show=True, pos_left="right",
                feature={"saveAsImage": {"title": "保存为图片"}, "dataZoom": {"title": {"zoom": "区域缩放", "back": "还原"}}},
            ),
        )
        .set_series_opts(
            itemstyle_opts=opts.ItemStyleOpts(
                color=_UP_COLOR, color0=_DOWN_COLOR,
                border_color=_UP_COLOR, border_color0=_DOWN_COLOR,
            ),
            bar_max_width="60%", bar_min_width="3",
        )
    )

    ma_configs = [
        (ma5, "MA5", _MA_COLORS[0]),
        (ma10, "MA10", _MA_COLORS[1]),
        (ma20, "MA20", _MA_COLORS[2]),
        (ma60, "MA60", _MA_COLORS[3]),
    ]
    for ma_data, ma_name, ma_color in ma_configs:
        if ma_data is None or len(ma_data) == 0:
            continue
        line_ma = (
            Line()
            .add_xaxis(dates)
            .add_yaxis(
                series_name=ma_name, y_axis=ma_data,
                is_smooth=True, symbol="none",
                linestyle_opts=opts.LineStyleOpts(color=ma_color, width=1.8, opacity=0.7),
                label_opts=opts.LabelOpts(is_show=False),
            )
        )
        kline.overlap(line_ma)

    grid = Grid(init_opts=opts.InitOpts(width="100%", height="500px", bg_color=_CHART_BG))
    grid.add(kline, grid_opts=opts.GridOpts(pos_top="14%", pos_bottom="10%", pos_left="10%", pos_right="5%"))
    return grid


def create_macd_chart(dates: list[str], dif: list, dea: list, macd_hist: list) -> Grid:
    """MACD 指标图：DIF / DEA 线 + 柱状图"""
    if not dates or not dif or not dea or not macd_hist:
        return None

    visible_start = max(70, 100 - max(30, 100 * 90 // len(dates)))

    line = (
        Line(init_opts=opts.InitOpts(width="100%", height="350px", bg_color=_CHART_BG))
        .add_xaxis(dates)
        .add_yaxis(
            series_name="DIF",
            y_axis=[round(v, 4) if v is not None else None for v in dif],
            is_smooth=True, symbol="none",
            linestyle_opts=opts.LineStyleOpts(color=_DIF_COLOR, width=1.8),
            label_opts=opts.LabelOpts(is_show=False),
            is_connect_nones=True,
        )
        .add_yaxis(
            series_name="DEA",
            y_axis=[round(v, 4) if v is not None else None for v in dea],
            is_smooth=True, symbol="none",
            linestyle_opts=opts.LineStyleOpts(color=_DEA_COLOR, width=1.8),
            label_opts=opts.LabelOpts(is_show=False),
            is_connect_nones=True,
        )
        .add_yaxis(
            series_name="MACD",
            y_axis=[round(v, 4) if v is not None else None for v in macd_hist],
            areastyle_opts=opts.AreaStyleOpts(opacity=0.12),
            linestyle_opts=opts.LineStyleOpts(color=_UP_COLOR, width=1),
            label_opts=opts.LabelOpts(is_show=False),
            is_connect_nones=True,
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title="MACD (12, 26, 9)", pos_left="left", pos_top="2%",
                title_textstyle_opts=opts.TextStyleOpts(font_size=16, font_weight="bold", color=_TITLE_COLOR),
            ),
            xaxis_opts=_dark_axis_opts(show_split=False),
            yaxis_opts=_dark_yaxis_compact(),
            legend_opts=opts.LegendOpts(
                pos_top="2%", pos_left="center",
                textstyle_opts=opts.TextStyleOpts(color=_AXIS_LABEL_COLOR),
            ),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
            datazoom_opts=[
                opts.DataZoomOpts(type_="inside", range_start=visible_start, range_end=100),
                opts.DataZoomOpts(type_="slider", range_start=visible_start, range_end=100, pos_bottom="2%"),
            ],
        )
    )

    grid = Grid(init_opts=opts.InitOpts(width="100%", height="350px", bg_color=_CHART_BG))
    grid.add(line, grid_opts=opts.GridOpts(pos_top="16%", pos_bottom="16%", pos_left="10%", pos_right="5%"))
    return grid


def create_kdj_chart(dates: list[str], k_vals: list, d_vals: list, j_vals: list) -> Grid:
    """KDJ 指标图：K / D / J 三条线"""
    if not dates or not k_vals or not d_vals or not j_vals:
        return None

    visible_start = max(70, 100 - max(30, 100 * 90 // len(dates)))

    line = (
        Line(init_opts=opts.InitOpts(width="100%", height="350px", bg_color=_CHART_BG))
        .add_xaxis(dates)
        .add_yaxis(
            series_name="K",
            y_axis=[round(v, 2) if v is not None else None for v in k_vals],
            is_smooth=True, symbol="none",
            linestyle_opts=opts.LineStyleOpts(color=_DIF_COLOR, width=1.8),
            label_opts=opts.LabelOpts(is_show=False),
            is_connect_nones=True,
        )
        .add_yaxis(
            series_name="D",
            y_axis=[round(v, 2) if v is not None else None for v in d_vals],
            is_smooth=True, symbol="none",
            linestyle_opts=opts.LineStyleOpts(color=_DEA_COLOR, width=1.8),
            label_opts=opts.LabelOpts(is_show=False),
            is_connect_nones=True,
        )
        .add_yaxis(
            series_name="J",
            y_axis=[round(v, 2) if v is not None else None for v in j_vals],
            is_smooth=True, symbol="none",
            linestyle_opts=opts.LineStyleOpts(color=_J_COLOR, width=1.2, opacity=0.7),
            label_opts=opts.LabelOpts(is_show=False),
            is_connect_nones=True,
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title="KDJ (9, 3, 3)", pos_left="left", pos_top="2%",
                title_textstyle_opts=opts.TextStyleOpts(font_size=16, font_weight="bold", color=_TITLE_COLOR),
            ),
            xaxis_opts=_dark_axis_opts(show_split=False),
            yaxis_opts=_dark_yaxis_compact(y_min=0, y_max=100),
            legend_opts=opts.LegendOpts(
                pos_top="2%", pos_left="center",
                textstyle_opts=opts.TextStyleOpts(color=_AXIS_LABEL_COLOR),
            ),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
            datazoom_opts=[
                opts.DataZoomOpts(type_="inside", range_start=visible_start, range_end=100),
                opts.DataZoomOpts(type_="slider", range_start=visible_start, range_end=100, pos_bottom="2%"),
            ],
        )
    )

    grid = Grid(init_opts=opts.InitOpts(width="100%", height="350px", bg_color=_CHART_BG))
    grid.add(line, grid_opts=opts.GridOpts(pos_top="16%", pos_bottom="16%", pos_left="10%", pos_right="5%"))
    return grid


def create_volume_chart(dates: list[str], ohlc: list[list[float]], volumes: list) -> Grid:
    """独立成交量柱状图（红涨绿跌），带 dataZoom 用于联动"""
    if not dates or not volumes or not ohlc:
        return None

    visible_start = max(70, 100 - max(30, 100 * 90 // len(dates)))

    up_volumes = []
    down_volumes = []
    for i, v in enumerate(volumes):
        safe_v = max(v, 0.01)
        if i < len(ohlc) and ohlc[i][1] >= ohlc[i][0]:
            up_volumes.append(safe_v)
            down_volumes.append(0)
        else:
            up_volumes.append(0)
            down_volumes.append(safe_v)

    bar_vol = (
        Bar(init_opts=opts.InitOpts(width="100%", height="300px", bg_color=_CHART_BG))
        .add_xaxis(dates)
        .add_yaxis(
            series_name="", y_axis=up_volumes, stack="volume",
            label_opts=opts.LabelOpts(is_show=False),
            itemstyle_opts=opts.ItemStyleOpts(color=_UP_COLOR),
        )
        .add_yaxis(
            series_name="", y_axis=down_volumes, stack="volume",
            label_opts=opts.LabelOpts(is_show=False),
            itemstyle_opts=opts.ItemStyleOpts(color=_DOWN_COLOR),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title="成交量", pos_left="left", pos_top="2%",
                title_textstyle_opts=opts.TextStyleOpts(font_size=16, font_weight="bold", color=_TITLE_COLOR),
            ),
            xaxis_opts=_dark_axis_opts(show_split=False),
            yaxis_opts=_dark_yaxis_compact(y_name="成交量"),
            legend_opts=opts.LegendOpts(is_show=False),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
            datazoom_opts=[
                opts.DataZoomOpts(type_="inside", range_start=visible_start, range_end=100),
            ],
        )
    )

    grid = Grid(init_opts=opts.InitOpts(width="100%", height="300px", bg_color=_CHART_BG))
    grid.add(bar_vol, grid_opts=opts.GridOpts(pos_top="16%", pos_bottom="8%", pos_left="10%", pos_right="5%"))
    return grid


def create_rsi_chart(dates: list[str], rsi_vals: list) -> Grid:
    """RSI 指标图，含 30/70 超买超卖参考线"""
    if not dates or not rsi_vals:
        return None

    visible_start = max(70, 100 - max(30, 100 * 90 // len(dates)))

    line = (
        Line(init_opts=opts.InitOpts(width="100%", height="300px", bg_color=_CHART_BG))
        .add_xaxis(dates)
        .add_yaxis(
            series_name="RSI",
            y_axis=[round(v, 2) if v is not None else None for v in rsi_vals],
            is_smooth=True, symbol="none",
            linestyle_opts=opts.LineStyleOpts(color=_DIF_COLOR, width=2),
            label_opts=opts.LabelOpts(is_show=False),
            is_connect_nones=True,
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title="RSI (14)", pos_left="left", pos_top="2%",
                title_textstyle_opts=opts.TextStyleOpts(font_size=16, font_weight="bold", color=_TITLE_COLOR),
            ),
            xaxis_opts=_dark_axis_opts(show_split=False),
            yaxis_opts=_dark_yaxis_compact(y_min=0, y_max=100),
            legend_opts=opts.LegendOpts(
                pos_top="2%", pos_left="center",
                textstyle_opts=opts.TextStyleOpts(color=_AXIS_LABEL_COLOR),
            ),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
            datazoom_opts=[
                opts.DataZoomOpts(type_="inside", range_start=visible_start, range_end=100),
            ],
        )
    )

    line_mark = (
        Line()
        .add_xaxis(dates)
        .add_yaxis(
            series_name="超卖线(30)", y_axis=[30] * len(dates),
            is_smooth=False, symbol="none",
            linestyle_opts=opts.LineStyleOpts(color=_DOWN_COLOR, width=1, type_="dashed", opacity=0.5),
            label_opts=opts.LabelOpts(is_show=False),
            is_connect_nones=True,
        )
        .add_yaxis(
            series_name="超买线(70)", y_axis=[70] * len(dates),
            is_smooth=False, symbol="none",
            linestyle_opts=opts.LineStyleOpts(color=_UP_COLOR, width=1, type_="dashed", opacity=0.5),
            label_opts=opts.LabelOpts(is_show=False),
            is_connect_nones=True,
        )
    )

    line.overlap(line_mark)

    grid = Grid(init_opts=opts.InitOpts(width="100%", height="300px", bg_color=_CHART_BG))
    grid.add(line, grid_opts=opts.GridOpts(pos_top="16%", pos_bottom="8%", pos_left="10%", pos_right="5%"))
    return grid
