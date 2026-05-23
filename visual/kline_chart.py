"""K 线图 + 买卖点标记（pyecharts）"""

from pyecharts.charts import Kline
from pyecharts import options as opts


def create_kline_chart(
    dates: list[str],
    ohlc: list[list[float]],
    buy_marks: list[tuple[str, float]],
    sell_marks: list[tuple[str, float]],
    title: str = "K 线图",
) -> Kline:
    mark_data = []

    for date_str, price in buy_marks:
        mark_data.append(
            opts.MarkPointItem(
                name="买入",
                coord=[date_str, price],
                value="买入",
                symbol="triangle",
                symbol_size=26,
                itemstyle_opts=opts.ItemStyleOpts(
                    color="#ef5350",
                    border_color="#ffffff",
                    border_width=2,
                ),
                label_opts=opts.LabelOpts(
                    is_show=True,
                    position="top",
                    font_size=11,
                    font_weight="bold",
                    color="#ef5350",
                    distance=8,
                ),
            )
        )

    for date_str, price in sell_marks:
        mark_data.append(
            opts.MarkPointItem(
                name="卖出",
                coord=[date_str, price],
                value="卖出",
                symbol="triangle",
                symbol_rotate=180,
                symbol_size=26,
                itemstyle_opts=opts.ItemStyleOpts(
                    color="#26a69a",
                    border_color="#ffffff",
                    border_width=2,
                ),
                label_opts=opts.LabelOpts(
                    is_show=True,
                    position="bottom",
                    font_size=11,
                    font_weight="bold",
                    color="#26a69a",
                    distance=8,
                ),
            )
        )

    # 默认展示最近 30% 的数据 (避免蜡烛太窄)
    visible_start = max(70, 100 - max(30, 100 * 90 // len(dates)))

    kline = (
        Kline(init_opts=opts.InitOpts(
            width="100%",
            height="650px",
            bg_color="#ffffff",
        ))
        .add_xaxis(dates)
        .add_yaxis(
            series_name="K线",
            y_axis=ohlc,
            markpoint_opts=opts.MarkPointOpts(data=mark_data),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title=title,
                pos_left="left",
                pos_top="2%",
                title_textstyle_opts=opts.TextStyleOpts(
                    font_size=18, font_weight="bold", color="#2c3e50"
                ),
            ),
            xaxis_opts=opts.AxisOpts(
                type_="category",
                boundary_gap=True,
                axislabel_opts=opts.LabelOpts(rotate=30, font_size=10),
                axisline_opts=opts.AxisLineOpts(
                    linestyle_opts=opts.LineStyleOpts(color="#bdc3c7")
                ),
            ),
            yaxis_opts=opts.AxisOpts(
                type_="value",
                is_scale=True,
                splitarea_opts=opts.SplitAreaOpts(
                    is_show=True,
                    areastyle_opts=opts.AreaStyleOpts(opacity=0.03),
                ),
                axislabel_opts=opts.LabelOpts(font_size=11),
                splitline_opts=opts.SplitLineOpts(
                    is_show=True,
                    linestyle_opts=opts.LineStyleOpts(type_="dashed", opacity=0.3),
                ),
            ),
            datazoom_opts=[
                opts.DataZoomOpts(type_="inside", range_start=visible_start, range_end=100),
                opts.DataZoomOpts(
                    type_="slider",
                    range_start=visible_start,
                    range_end=100,
                    pos_bottom="2%",
                ),
            ],
            tooltip_opts=opts.TooltipOpts(
                trigger="axis",
                axis_pointer_type="cross",
            ),
            toolbox_opts=opts.ToolboxOpts(
                is_show=True,
                pos_left="right",
                feature={
                    "saveAsImage": {"title": "保存为图片"},
                    "dataZoom": {"title": {"zoom": "区域缩放", "back": "还原"}},
                },
            ),
        )
        .set_series_opts(
            itemstyle_opts=opts.ItemStyleOpts(
                color="#ef5350",
                color0="#26a69a",
                border_color="#ef5350",
                border_color0="#26a69a",
            ),
            bar_max_width="60%",
            bar_min_width="3",
        )
    )

    return kline
