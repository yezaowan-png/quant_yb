"""数据统计命令组：策略画像 + 策略对比"""

from pathlib import Path
from typing import Optional

import click
import yaml

from analysis.analyzer import (
    _STRATEGY_LABELS,
    load_summary,
    load_all_summaries,
    compute_stats,
)
from analysis.report import build_analyze_page, build_compare_page


def _load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _list_strategies() -> list[str]:
    strat_dir = Path(__file__).parent.parent / "strategy"
    names = []
    for p in strat_dir.glob("*.py"):
        if p.stem in ("base", "__init__"):
            continue
        names.append(p.stem)
    return sorted(names)


@click.group(name="stats")
def stats_group():
    """数据分析：策略画像、多策略对比"""
    pass


@stats_group.command(name="analyze")
@click.option("--strategy", required=True,
              help=f"策略名称。可用: {', '.join(_list_strategies())}")
def analyze_strategy(strategy: str):
    """单策略深度分析 —— 收益分布、风险散点、TOP/BOTTOM 榜单"""
    config = _load_config()
    stats_dir = Path(config["output"].get("statistics_dir", "output/statistics"))
    stats_dir.mkdir(parents=True, exist_ok=True)

    df = load_summary(strategy)
    if df is None or len(df) == 0:
        click.echo(f"错误: 策略 '{strategy}' 无回测数据。请先执行 backtest run --strategy {strategy}", err=True)
        return

    stats = compute_stats(df)
    display = _STRATEGY_LABELS.get(strategy, strategy)

    click.echo(f"\n{'='*60}")
    click.echo(f"  {display} — 策略画像")
    click.echo(f"{'='*60}")
    click.echo(f"  股票数:     {stats['count']}")
    click.echo(f"  有交易股票: {stats['active_count']} ({stats['active_ratio']:.1f}%)")
    click.echo(f"  平均收益:   {stats['avg_return']:+.2f}%")
    click.echo(f"  平均年化:   {stats['avg_annual_return']:+.2f}%")
    click.echo(f"  交易股平均: {stats['avg_active_return']:+.2f}%")
    click.echo(f"  交易股年化: {stats['avg_active_annual_return']:+.2f}%")
    click.echo(f"  年化波动:   {stats['avg_annual_volatility']:.1f}%")
    click.echo(f"  超额收益:   {stats['avg_excess_return']:+.1f}%")
    click.echo(f"  信息比率:   {stats['avg_information_ratio']:.3f}")
    click.echo(f"  中位收益:   {stats['median_return']:+.1f}%")
    click.echo(f"  正收益比例: {stats['positive_ratio']:.1f}% ({stats['positive_count']}/{stats['count']})")
    click.echo(f"  平均夏普:   {stats['avg_sharpe']:.3f}")
    click.echo(f"  平均回撤:   {stats['avg_max_dd']:.1f}%")
    click.echo(f"  平均胜率:   {stats['avg_win_rate']:.1f}%")
    click.echo(f"  平均交易:   {stats['avg_trades']} 次")
    click.echo(f"  收益范围:   [{stats['min_return']:+.1f}% , {stats['max_return']:+.1f}%]")

    output_path = stats_dir / f"analysis_{strategy}.html"
    click.echo(f"\n  生成报告...")
    build_analyze_page(strategy, df, output_path)
    click.echo(f"  报告已生成: {output_path}")


@stats_group.command(name="compare")
def compare_strategies():
    """多策略横向对比 —— 雷达图、箱线图、相关性分析"""
    config = _load_config()
    stats_dir = Path(config["output"].get("statistics_dir", "output/statistics"))
    stats_dir.mkdir(parents=True, exist_ok=True)

    data_map = load_all_summaries()
    if len(data_map) < 2:
        click.echo("错误: 需要至少 2 个策略有回测数据才能对比。请先执行 backtest run。", err=True)
        return

    click.echo(f"\n{'='*60}")
    click.echo(f"  策略横向对比 ({len(data_map)} 个策略)")
    click.echo(f"{'='*60}")

    for name, df in data_map.items():
        s = compute_stats(df)
        display = _STRATEGY_LABELS.get(name, name)
        click.echo(f"  {display:<10s}  {s['count']:>5d} 只  "
                   f"收益 {s['avg_return']:>+7.2f}%  "
                   f"年化 {s['avg_annual_return']:>+7.2f}%  "
                   f"交易股 {s['avg_active_return']:>+7.2f}%  "
                   f"超额 {s['avg_excess_return']:>+7.1f}%  "
                   f"正向率 {s['positive_ratio']:>5.1f}%  "
                   f"夏普 {s['avg_sharpe']:>+7.3f}")

    output_path = stats_dir / "comparison.html"
    click.echo(f"\n  生成对比报告...")
    build_compare_page(data_map, output_path)
    click.echo(f"  报告已生成: {output_path}")
