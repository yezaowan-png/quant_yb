"""ETF strategy research commands."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import click

from cli.common import load_config as _load_config
from etf_strategy.runner import run_etf_strategy_report
from etf_strategy.signal_provider import ExternalSignalProvider, parse_rank_emotion_frame, red_green_decision


def run_etf_report(
    config: dict,
    symbols: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    force: bool = False,
    output: Optional[str] = None,
) -> dict:
    result = run_etf_strategy_report(
        config,
        symbols=symbols,
        start=start,
        end=end,
        force=force,
        output=Path(output) if output else None,
    )
    click.echo(f"ETF 策略板块: {result['report_path']}")
    click.echo(f"ETF 策略汇总: {result['summary_path']}")
    if result.get("errors"):
        click.echo(f"ETF 数据缺失/跳过: {len(result['errors'])} 项")
    return result


@click.group(name="etf")
def etf_group():
    """ETF 策略研究：日线适配、择时信号、轮动排名和独立报告。"""


@etf_group.command(name="report")
@click.option("--symbols", default=None, help="ETF 代码列表，逗号分隔；默认读取 etf_strategy.pool")
@click.option("--start", default=None, help="开始日期，如 20240101 或 2024-01-01")
@click.option("--end", default=None, help="结束日期，如 20260724 或 2026-07-24")
@click.option("--force", is_flag=True, help="忽略本地 ETF 缓存，重新从新浪拉取日线")
@click.option("--output", default=None, help="输出 HTML 路径，默认 output/reports/etf_strategy/etf_strategy_dashboard.html")
def report(symbols: Optional[str], start: Optional[str], end: Optional[str], force: bool, output: Optional[str]):
    """生成 ETF 策略独立板块。"""
    run_etf_report(_load_config(), symbols=symbols, start=start, end=end, force=force, output=output)


@etf_group.command(name="signals")
@click.option("--refresh", is_flag=True, help="按 etf_strategy.ftp 配置刷新公共 FTP 外部信号文件")
@click.option("--symbol", default="515880.SH", help="用于红绿灯样例解析的 ETF 代码")
@click.option("--top-n", default=None, type=int, help="排名解析前 N，默认读取 etf_strategy.rank_top_n")
def signals(refresh: bool, symbol: str, top_n: Optional[int]):
    """读取/刷新 ETF 外部红绿灯与排名情绪信号。"""
    config = _load_config()
    provider = ExternalSignalProvider(config)
    if refresh:
        result = provider.refresh()
        click.echo(f"红绿灯目录/文件: {result['red_green_path']}")
        click.echo(f"排名情绪目录/文件: {result['rank_emotion_path']}")
    red_green_frame = provider.load_red_green_signal()
    rank_frame = provider.load_rank_emotion_signal()
    decision = red_green_decision(red_green_frame, symbol)
    rank = parse_rank_emotion_frame(rank_frame, top_n=top_n or int((config.get("etf_strategy") or {}).get("rank_top_n", 10)))
    click.echo(f"红绿灯 {decision['symbol']}: {decision['action']} / {'; '.join(decision['reasons'])}")
    click.echo(rank.get("log", ""))
    if provider.download_errors:
        click.echo(f"FTP下载错误: {'; '.join(provider.download_errors)}")
