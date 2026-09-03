"""Daily review markdown commands."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import click

from analysis.daily_review import DEFAULT_INDEX_SYMBOL, generate_daily_review
from cli.common import load_config


@click.group(name="review")
def review_group():
    """生成每日复盘等研究笔记。"""


@review_group.command(name="daily")
@click.option("--date", "trade_date", default=None, help="交易日期，支持 YYYYMMDD / YYYY-MM-DD / MMDD；不传则读取最新市场结构日期")
@click.option("--output-dir", required=True, help="输出目录，例如 /Users/.../A股每日复盘")
@click.option("--template", default=None, help="复盘模版 Markdown 路径；第一版用于记录来源，生成结构按内置事实模板")
@click.option("--symbol", default=DEFAULT_INDEX_SYMBOL, show_default=True, help="观察指数代码")
@click.option("--overwrite/--no-overwrite", default=True, show_default=True, help="目标文件已存在时是否覆盖")
def daily(
    trade_date: Optional[str],
    output_dir: str,
    template: Optional[str],
    symbol: str,
    overwrite: bool,
):
    """按市场结构事实生成一份不含主观判断的 A 股每日复盘 Markdown。"""
    config = load_config()
    result = generate_daily_review(
        config,
        date=trade_date,
        output_dir=Path(output_dir),
        template=template,
        symbol=symbol,
        overwrite=overwrite,
    )
    click.echo(f"复盘日期: {result.trade_date}")
    click.echo(f"市场结构数据: {result.structure_path}")
    click.echo(f"输出文件: {result.output_path}")
    if result.missing_items:
        click.echo("缺失项:")
        for item in result.missing_items:
            click.echo(f"  - {item}")
