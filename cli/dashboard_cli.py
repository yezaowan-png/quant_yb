"""Dashboard command."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import click
import yaml

from visual.dashboard import generate_dashboard


def _load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@click.command(name="dashboard")
@click.option("--output", default=None, help="输出 HTML 路径，默认 output/reports/dashboard.html")
def dashboard_command(output: Optional[str]):
    """生成项目汇总导航面板。"""
    config = _load_config()
    out_path = generate_dashboard(config, output)
    click.echo(f"汇总面板已生成: {out_path}")
