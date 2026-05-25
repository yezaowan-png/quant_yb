"""A股量化回测系统 - CLI 入口

用法:
    python main.py                    交互式菜单
    python main.py data download ...  直接命令行
    python main.py backtest run ...   直接命令行
    python main.py run "cmd1; cmd2"   批量流水线
"""

import sys

import click

from cli.data_cli import data_group
from cli.backtest_cli import backtest_group
from cli.stats_cli import stats_group


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


@cli.command("run")
@click.option("--file", "-f", "file_path", default=None, help="从文件读取命令（每行一条，分号分隔）")
@click.argument("commands", required=False, default="")
def run_pipeline(commands: str, file_path: str):
    """按顺序批量执行多条命令，用分号(;)或换行分隔。

    \b
    示例:
      python main.py run "download; backtest --strategy rsi; report; stats compare"
      python main.py run --file pipeline.txt

    \b
    每行可加 ! 前缀忽略该条命令失败继续执行:
      python main.py run "!download; backtest --strategy rsi"
    """
    from cli.shell import _load_config, _execute_pipeline

    config = _load_config()


    if file_path:
        from pathlib import Path
        fp = Path(file_path)
        if not fp.exists():
            click.secho(f"文件不存在: {file_path}", fg="red")
            return
        commands = fp.read_text(encoding="utf-8")

    if not commands or not commands.strip():
        click.secho("请提供要执行的命令。用法: python main.py run \"cmd1; cmd2\"", fg="red")
        return

    _execute_pipeline(config, commands)


cli.add_command(data_group)
cli.add_command(backtest_group)
cli.add_command(stats_group)


if __name__ == "__main__":
    cli()
