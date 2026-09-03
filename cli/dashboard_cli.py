"""Dashboard command."""

from __future__ import annotations

from typing import Optional

import click

from cli.common import load_config as _load_config
from visual.dashboard import generate_dashboard


def run_dashboard(config: dict, output: Optional[str] = None):
    """Generate the project dashboard for Click and the REPL."""
    out_path = generate_dashboard(config, output)
    click.echo(f"汇总面板已生成: {out_path}")
    return out_path


@click.command(name="dashboard")
@click.option("--output", default=None, help="输出 HTML 路径，默认 output/reports/dashboard.html")
def dashboard_command(output: Optional[str]):
    """生成项目汇总导航面板。"""
    run_dashboard(_load_config(), output)
