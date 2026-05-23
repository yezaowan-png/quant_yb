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
                name="B",
                coord=[date_str, price],
                value=f"B {price}",
                symbol="triangle",
                symbol_size=16,
                itemstyle_opts=opts.ItemStyleOpts(color="#ef2323"),
            )
        )

    for date_str, price in sell_marks:
        mark_data.append(
            opts.MarkPointItem(
                name="S",
                coord=[date_str, price],
                value=f"S {price}",
                symbol="arrow",
                symbol_size=16,
                itemstyle_opts=opts.ItemStyleOpts(color="#14b143"),
            )
        )

    # 默认展示最近 30% 的数据 (避免蜡烛太窄)
    visible_start = max(70, 100 - max(30, 100 * 90 // len(dates)))

    kline = (
        Kline()
        .add_xaxis(dates)
        .add_yaxis(
            series_name="K线",
            y_axis=ohlc,
            markpoint_opts=opts.MarkPointOpts(data=mark_data),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title=title, pos_left="left", pos_top="2%",
                title_textstyle_opts=opts.TextStyleOpts(font_size=16),
            ),
            xaxis_opts=opts.AxisOpts(
                type_="category",
                boundary_gap=True,
                axislabel_opts=opts.LabelOpts(rotate=30, font_size=10),
            ),
            yaxis_opts=opts.AxisOpts(
                type_="value",
                is_scale=True,
                splitarea_opts=opts.SplitAreaOpts(
                    is_show=True, areastyle_opts=opts.AreaStyleOpts(opacity=0.05)
                ),
                axislabel_opts=opts.LabelOpts(font_size=11),
            ),
            datazoom_opts=[
                opts.DataZoomOpts(type_="inside", range_start=visible_start, range_end=100),
                opts.DataZoomOpts(type_="slider", range_start=visible_start, range_end=100,
                                  pos_bottom="2%"),
            ],
            tooltip_opts=opts.TooltipOpts(
                trigger="axis",
                axis_pointer_type="cross",
            ),
            toolbox_opts=opts.ToolboxOpts(is_show=True, pos_left="right"),
        )
        .set_series_opts(
            itemstyle_opts=opts.ItemStyleOpts(
                color="#ef2323", color0="#14b143",
                border_color="#ef2323", border_color0="#14b143",
            ),
            bar_max_width="60%",
            bar_min_width="3",
        )
    )

    return kline
