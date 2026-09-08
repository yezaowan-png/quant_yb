"""Dashboard command."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import click

from cli.common import load_config as _load_config
from visual.dashboard import generate_dashboard as generate_legacy_dashboard
from visual.product_dashboard import generate_product_dashboard


def run_dashboard(config: dict, output: Optional[str] = None, legacy: bool = False):
    """Generate the read-only product dashboard for Click and the REPL."""
    if legacy:
        reports_dir = Path((config.get("output") or {}).get("reports_dir", "output/reports"))
        out_path = generate_legacy_dashboard(config, output or str(reports_dir / "legacy_dashboard.html"))
    else:
        out_path = generate_product_dashboard(config, output)
    click.echo(f"汇总面板已生成: {out_path}")
    return out_path


@click.command(name="dashboard")
@click.option("--output", default=None, help="输出 HTML 路径，默认 output/reports/dashboard.html")
@click.option("--legacy", is_flag=True, help="生成兼容旧版总面板到 legacy_dashboard.html")
def dashboard_command(output: Optional[str], legacy: bool):
    """生成只读产品导航面板。"""
    if legacy:
        run_dashboard(_load_config(), output, legacy=True)
    else:
        run_dashboard(_load_config(), output)
