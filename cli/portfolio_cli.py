"""Portfolio command group."""

from __future__ import annotations

from pathlib import Path

import click
import yaml

from portfolio.allocator import build_target_weights


def _load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@click.group(name="portfolio")
def portfolio_group():
    """组合研究：从信号生成目标权重"""
    pass


@portfolio_group.command(name="build")
@click.option("--signals", "signals_path", required=True, help="买点扫描 CSV 路径")
@click.option("--method", default="equal", type=click.Choice(["equal", "inverse_vol"]), help="权重方法")
@click.option("--max-weight", default=0.10, type=float, help="单股最大目标权重")
@click.option("--gross-exposure", default=1.0, type=float, help="组合总目标仓位")
@click.option("--lookback", default=60, type=int, help="波动率倒数法使用的历史交易日数")
@click.option("--output", "output_dir", default=None, help="输出目录，默认 output.portfolio_dir")
def build(signals_path: str, method: str, max_weight: float, gross_exposure: float, lookback: int, output_dir: str | None):
    """从买点信号 CSV 生成目标权重。"""
    config = _load_config()
    result = build_target_weights(
        config=config,
        signals_path=Path(signals_path),
        method=method,
        max_weight=max_weight,
        gross_exposure=gross_exposure,
        lookback=lookback,
        output_dir=Path(output_dir) if output_dir else None,
    )
    click.echo("\n目标权重已生成")
    click.echo(f"  方法: {result.method}")
    click.echo(f"  标的数: {result.count}")
    click.echo(f"  实际总仓位: {result.gross_exposure:.2%}")
    click.echo(f"  最大单股权重: {result.max_weight:.2%}")
    click.echo(f"  输出: {result.output_path}")
