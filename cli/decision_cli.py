"""Decision memory commands."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import click
import pandas as pd
import yaml

from decision.evaluator import evaluate_memory, parse_horizons, summarize_memory
from decision.recorder import append_signals_from_file, decision_memory_path


def _load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _latest_signals_file(config: dict, strategy: str) -> Path | None:
    signals_dir = Path(config["output"].get("signals_dir", "output/signals"))
    if not signals_dir.exists():
        return None
    paths = sorted(
        signals_dir.glob(f"buy_signals_{strategy}_*.csv"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return paths[0] if paths else None


def _load_data_map_for_file(config: dict, signals_file: Path) -> dict[str, pd.DataFrame]:
    try:
        signals_df = pd.read_csv(signals_file, dtype={"symbol": str})
    except Exception:
        return {}
    cache_dir = Path(config["data"]["cache_dir"])
    data_map: dict[str, pd.DataFrame] = {}
    for symbol in sorted(set(signals_df.get("symbol", pd.Series(dtype=str)).dropna().astype(str))):
        path = cache_dir / f"{symbol}.csv"
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path, dtype={"date": str})
            df["date"] = pd.to_datetime(df["date"])
            data_map[symbol] = df.sort_values("date").reset_index(drop=True)
        except Exception:
            continue
    return data_map


@click.group(name="decision")
def decision_group():
    """决策记忆：记录买点信号并复盘未来表现。"""
    pass


@decision_group.command(name="record")
@click.option("--strategy", required=True, help="策略名称，如 sma_cross")
@click.option("--signals-file", default=None, help="买点扫描 CSV；默认读取该策略最新 buy_signals 文件")
def record_decisions(strategy: str, signals_file: Optional[str]):
    """把买点扫描 CSV 写入 decision memory。"""
    config = _load_config()
    path = Path(signals_file) if signals_file else _latest_signals_file(config, strategy)
    if path is None or not path.exists():
        click.echo(f"未找到策略 {strategy} 的买点 CSV，请先执行 backtest scan。", err=True)
        return
    data_map = _load_data_map_for_file(config, path)
    out_path, added = append_signals_from_file(
        config=config,
        strategy=strategy,
        signals_file=path,
        data_map=data_map,
    )
    click.echo(f"决策记忆已更新: {out_path}，新增 {added} 条信号。")


@decision_group.command(name="evaluate")
@click.option("--strategy", default=None, help="只评估某个策略")
@click.option("--symbol", default=None, help="只评估某只股票")
@click.option("--horizons", default="5,10,20", help="交易日窗口，逗号分隔，如 5,10,20")
def evaluate_decisions(strategy: Optional[str], symbol: Optional[str], horizons: str):
    """用本地缓存评估信号未来 N 个交易日收益。"""
    config = _load_config()
    parsed = parse_horizons(horizons)
    stats = evaluate_memory(config, strategy=strategy, symbol=symbol, horizons=parsed)
    click.echo(f"决策记忆评估完成: {stats['path']}")
    click.echo(f"  匹配信号: {stats['matched']}")
    click.echo(f"  完整评估: {stats['evaluated']}")
    click.echo(f"  部分评估: {stats['partial']}")
    click.echo(f"  未来数据不足: {stats['pending']}")
    click.echo(f"  缺少标的数据: {stats['missing']}")


@decision_group.command(name="summary")
@click.option("--strategy", default=None, help="只汇总某个策略")
def summarize_decisions(strategy: Optional[str]):
    """显示 decision memory 摘要。"""
    config = _load_config()
    summary = summarize_memory(config, strategy=strategy)
    path = decision_memory_path(config)
    click.echo(f"决策记忆: {path}")
    click.echo(f"  信号总数: {summary['count']}")
    click.echo(f"  完整评估: {summary['evaluated']}")
    click.echo(f"  部分评估: {summary['partial']}")
    click.echo(f"  待评估:   {summary['pending']}")
    click.echo(f"  最新信号: {summary['latest_signal_date'] or '--'}")
    avg_5d = summary["avg_future_5d_return_pct"]
    avg_excess = summary["avg_excess_5d_return_pct"]
    click.echo(f"  平均5日收益: {'--' if avg_5d is None else f'{avg_5d:+.2f}%'}")
    click.echo(f"  平均5日超额: {'--' if avg_excess is None else f'{avg_excess:+.2f}%'}")

