"""生成完整 HTML 可视化报告"""

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
) -> Line:
    drawdowns = _compute_drawdowns(equity)

    # 同步 datazoom 初始范围
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
            linestyle_opts=opts.LineStyleOpts(color="#5470c6", width=2),
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
            series_name="回撤 (%)",
            y_axis=[round(d, 2) for d in drawdowns],
            yaxis_index=1,
            is_smooth=True,
            symbol="none",
            linestyle_opts=opts.LineStyleOpts(color="#ee6666", width=1.5),
            areastyle_opts=opts.AreaStyleOpts(opacity=0.12, color="#ee6666"),
            label_opts=opts.LabelOpts(is_show=False),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title="权益曲线 & 回撤",
                pos_left="left", pos_top="2%",
                title_textstyle_opts=opts.TextStyleOpts(font_size=14),
            ),
            xaxis_opts=opts.AxisOpts(
                type_="category",
                axislabel_opts=opts.LabelOpts(rotate=30, font_size=10),
            ),
            yaxis_opts=opts.AxisOpts(
                type_="value",
                name="权益",
                axislabel_opts=opts.LabelOpts(formatter="{value}", font_size=11),
            ),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
            datazoom_opts=[
                opts.DataZoomOpts(type_="inside", range_start=visible_start, range_end=100),
                opts.DataZoomOpts(type_="slider", range_start=visible_start, range_end=100,
                                  pos_bottom="2%"),
            ],
            legend_opts=opts.LegendOpts(pos_top="2%", pos_left="center"),
        )
    )

    return line


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

    # 买卖点
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

    grid_width = "1600px"

    if equity_data is not None and not equity_data.empty:
        equity_line = _create_equity_chart(
            equity_data["dates"].tolist(),
            equity_data["equity"].tolist(),
        )

        grid = (
            Grid(init_opts=opts.InitOpts(
                width=grid_width, height="950px",
                page_title=f"{symbol} 回测报告",
                bg_color="#f5f5f5",
            ))
            .add(kline, grid_opts=opts.GridOpts(
                pos_top="8%", pos_bottom="47%",
                pos_left="10%", pos_right="5%",
            ))
            .add(equity_line, grid_opts=opts.GridOpts(
                pos_top="53%", pos_bottom="95%",
                pos_left="10%", pos_right="5%",
            ))
        )
    else:
        grid = (
            Grid(init_opts=opts.InitOpts(
                width=grid_width, height="750px",
                page_title=f"{symbol} 回测报告",
                bg_color="#f5f5f5",
            ))
            .add(kline, grid_opts=opts.GridOpts(
                pos_top="8%", pos_bottom="8%",
                pos_left="10%", pos_right="5%",
            ))
        )

    grid.render(str(output_path))
