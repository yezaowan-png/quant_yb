"""A股量化回测系统 - CLI 入口

用法:
    python main.py                    交互式菜单
    python main.py data download ...  直接命令行
    python main.py backtest run ...   直接命令行
"""

import sys

import click

from cli.data_cli import data_group
from cli.backtest_cli import backtest_group


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context):
    """A股量化回测系统 - 支持数据下载、策略回测、可视化报告

    \b
    直接执行 python main.py 进入交互式菜单。
    也可传子命令直接操作，如 python main.py data download --help
    """
    if ctx.invoked_subcommand is None:
        # 没有子命令 → 进入交互模式
        from cli.shell import run_interactive

        run_interactive()


cli.add_command(data_group)
cli.add_command(backtest_group)


if __name__ == "__main__":
    cli()
    