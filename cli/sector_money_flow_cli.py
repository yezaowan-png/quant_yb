"""Sector money-flow monitoring commands."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import time
from typing import Optional

import click

from analysis.sector_money_flow import (
    add_new_data_point,
    init_sector_money_flow_state,
    sector_money_flow_config,
)
from cli.common import load_config as _load_config
from visual.sector_money_flow_report import generate_sector_money_flow_report


def _default_output(config: dict) -> Path:
    reports_dir = Path(config.get("output", {}).get("reports_dir", "output/reports"))
    return reports_dir / "sector_money_flow.html"


def run_sector_money_flow_collect(config: dict) -> Path | None:
    settings = sector_money_flow_config(config)
    state = init_sector_money_flow_state(settings)
    ok, message, path = add_new_data_point(settings, state)
    click.echo(message)
    if ok and path is not None:
        click.echo(f"行业资金流快照已保存: {path}")
    return path


def run_sector_money_flow_report(
    config: dict,
    output: Optional[str] = None,
    *,
    trade_date: Optional[str] = None,
    collect_now: bool = False,
) -> Path:
    settings = sector_money_flow_config(config)
    state = init_sector_money_flow_state(settings, trade_date=trade_date)
    if collect_now:
        ok, message, _ = add_new_data_point(settings, state)
        click.echo(message)
        if not ok and not state.is_replay_mode:
            click.echo("未新增实时数据，报告将使用当前本地状态。")
    target = Path(output) if output else _default_output(config)
    path = generate_sector_money_flow_report(state, settings, target)
    click.echo(f"行业板块资金流监控页已生成: {path}")
    return path


def run_sector_money_flow_watch(config: dict, output: Optional[str] = None, *, once: bool = False) -> Path:
    settings = sector_money_flow_config(config)
    target = Path(output) if output else _default_output(config)
    last_report = target
    click.echo(f"行业资金流监控启动，采集间隔 {settings.interval_seconds}s，输出 {target}")
    try:
        while True:
            state = init_sector_money_flow_state(settings, now=datetime.now(), trade_date=datetime.now())
            ok, message, _ = add_new_data_point(settings, state, now=datetime.now())
            click.echo(message)
            last_report = generate_sector_money_flow_report(state, settings, target)
            click.echo(f"监控页已刷新: {last_report}")
            if once:
                return last_report
            time.sleep(settings.interval_seconds)
    except KeyboardInterrupt:
        click.echo("行业资金流监控已停止。")
        return last_report


@click.group(name="sector-flow")
def sector_money_flow_group():
    """行业板块资金流实时监控/历史回放。"""


@sector_money_flow_group.command(name="collect")
def sector_money_flow_collect_command():
    """采集并归档一次 AkShare 行业资金流快照。"""
    run_sector_money_flow_collect(_load_config())


@sector_money_flow_group.command(name="report")
@click.option("--output", default=None, help="输出 HTML 路径，默认 output/reports/sector_money_flow.html")
@click.option("--date", "trade_date", default=None, help="回放日期 YYYY-MM-DD，默认今天")
@click.option("--collect-now", is_flag=True, help="生成报告前尝试采集一次实时数据")
def sector_money_flow_report_command(output: Optional[str], trade_date: Optional[str], collect_now: bool):
    """生成行业板块资金流监控/历史回放页面。"""
    run_sector_money_flow_report(_load_config(), output, trade_date=trade_date, collect_now=collect_now)


@sector_money_flow_group.command(name="watch")
@click.option("--output", default=None, help="输出 HTML 路径，默认 output/reports/sector_money_flow.html")
@click.option("--once", is_flag=True, help="只执行一轮采集和报告刷新，便于验证")
def sector_money_flow_watch_command(output: Optional[str], once: bool):
    """按配置间隔持续采集并刷新本地监控页。"""
    run_sector_money_flow_watch(_load_config(), output, once=once)
