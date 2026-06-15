"""Audit command group."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import click

from audit.lookahead import run_lookahead_audit


@click.group(name="audit")
def audit_group():
    """静态审计：未来函数和数据泄露启发式检查"""
    pass


@audit_group.command(name="lookahead")
@click.option("--strategy", default=None, help="策略名称；不填则审计 strategy/ 下全部策略")
@click.option("--output", "output_dir", default="output/audit", help="审计报告输出目录")
def lookahead(strategy: Optional[str], output_dir: str):
    """检查策略源码中的明显未来函数风险。"""
    try:
        df, csv_path, html_path = run_lookahead_audit(strategy=strategy, output_dir=Path(output_dir))
    except FileNotFoundError as exc:
        click.echo(f"错误: 找不到策略文件 {exc}", err=True)
        return

    high = int((df["severity"] == "high").sum()) if not df.empty else 0
    medium = int((df["severity"] == "medium").sum()) if not df.empty else 0
    low = int((df["severity"] == "low").sum()) if not df.empty else 0
    click.echo("\nLookahead Audit 完成")
    click.echo(f"  High:   {high}")
    click.echo(f"  Medium: {medium}")
    click.echo(f"  Low:    {low}")
    click.echo(f"  CSV:    {csv_path}")
    click.echo(f"  HTML:   {html_path}")
    if high:
        click.echo("  注意: High 命中项需要人工复核后再信任回测结果。", err=True)
