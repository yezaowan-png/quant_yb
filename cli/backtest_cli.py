"""回测命令组: run / scan / report"""

from pathlib import Path
from typing import Optional

import click
import yaml

from engine.runner import BacktestRunner, load_strategy_class
from visual.report import generate_report


def _load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_cache_df(symbol: str, config: dict):
    import pandas as pd

    cache_dir = Path(config["data"]["cache_dir"])
    path = cache_dir / f"{symbol}.csv"
    if not path.exists():
        raise FileNotFoundError(f"缓存数据不存在: {path}，请先执行 data download")
    df = pd.read_csv(path, dtype={"date": str})
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def _list_cached_symbols(config: dict) -> list[str]:
    cache_dir = Path(config["data"]["cache_dir"])
    if not cache_dir.exists():
        return []
    return sorted(
        [p.stem for p in cache_dir.glob("*.csv") if not p.name.startswith("_")]
    )


@click.group(name="backtest")
def backtest_group():
    """策略回测：运行回测、扫描买点、生成报告"""
    pass


@backtest_group.command(name="run")
@click.option("--strategy", required=True, help="策略名称，如 sma_cross")
@click.option("--symbol", default=None, help="股票代码。不指定则回测所有已缓存股票")
@click.option("--symbols", default=None, help="多只股票，逗号分隔，如 000001.SZ,600519.SH")
@click.option("--fast", default=5, type=int, help="快速均线周期 (默认 5)")
@click.option("--slow", default=20, type=int, help="慢速均线周期 (默认 20)")
def run_backtest(
    strategy: str, symbol: Optional[str], symbols: Optional[str], fast: int, slow: int
):
    """运行策略回测，导出交易流水 CSV"""
    config = _load_config()
    runner = BacktestRunner(config)

    # Resolve symbols
    if symbols:
        sym_list = [s.strip().upper() for s in symbols.split(",")]
    elif symbol:
        sym_list = [symbol.upper()]
    else:
        sym_list = _list_cached_symbols(config)
        if not sym_list:
            click.echo("错误: 本地无缓存数据，请先执行 data download。", err=True)
            return

    # Load data
    data_map = {}
    for sym in sym_list:
        try:
            data_map[sym] = _load_cache_df(sym, config)
        except FileNotFoundError as e:
            click.echo(f"跳过 {sym}: {e}", err=True)

    if not data_map:
        click.echo("没有可用的数据。", err=True)
        return

    # Strategy params
    strategy_params = {"symbol": "", "fast_period": fast, "slow_period": slow}

    if len(data_map) == 1:
        # Single stock: full run with CLI output
        sym = list(data_map.keys())[0]
        strategy_params["symbol"] = sym
        df = data_map[sym]
        cls = load_strategy_class(strategy)
        result = runner.run(df, cls, strategy_params)

        # Export trade log and equity
        trades_dir = Path(config["output"]["trades_dir"])
        trades_dir.mkdir(parents=True, exist_ok=True)
        runner._export_trade_log(result["trade_records"], trades_dir, sym, strategy)
        runner._export_equity(result["equity"], trades_dir, sym, strategy)

        # Print stats
        stats = result["stats"]
        click.echo(f"\n--- 绩效摘要 [{sym}] ---")
        click.echo(f"  总收益率:    {stats['total_return_pct']}%")
        click.echo(f"  夏普比率:    {stats['sharpe_ratio']}")
        click.echo(f"  最大回撤:    {stats['max_drawdown_pct']}%")
        click.echo(f"  交易次数:    {stats['total_trades']}")
        click.echo(f"  胜率:        {stats['win_rate_pct']}%")
        click.echo(f"  最终资金:    {stats['final_value']:,.2f}")
    else:
        # Batch mode (includes buy signal scanning)
        runner.run_batch(data_map, strategy, strategy_params)


@backtest_group.command(name="scan")
@click.option("--strategy", required=True, help="策略名称，如 sma_cross")
@click.option("--days", default=5, type=int, help="回看天数 (默认 5)")
@click.option("--fast", default=5, type=int, help="快速均线周期 (默认 5)")
@click.option("--slow", default=20, type=int, help="慢速均线周期 (默认 20)")
def scan_buy_signals(strategy: str, days: int, fast: int, slow: int):
    """扫描近N日存在买点的股票，汇总导出"""
    config = _load_config()
    sym_list = _list_cached_symbols(config)
    if not sym_list:
        click.echo("错误: 本地无缓存数据，请先执行 data download。", err=True)
        return

    data_map = {}
    for sym in sym_list:
        try:
            data_map[sym] = _load_cache_df(sym, config)
        except FileNotFoundError:
            pass

    if not data_map:
        click.echo("没有可用的数据。", err=True)
        return

    runner = BacktestRunner(config)
    strategy_params = {"symbol": "", "fast_period": fast, "slow_period": slow}
    click.echo(f"扫描 {len(data_map)} 只股票，回看 {days} 日 ...")
    results = runner.scan_recent_buy_signals(
        data_map, strategy, strategy_params, lookback_days=days
    )

    if results:
        click.echo(f"\n近{days}日存在买点的股票 ({len(results)} 只):")
        for r in results:
            click.echo(f"  {r['symbol']:12s}  买点日期: {r['recent_buy_dates']:20s}  最新价: {r.get('last_price', '-')}")
    else:
        click.echo(f"\n近{days}日无买点信号。")


@backtest_group.command(name="report")
@click.option("--symbol", required=True, help="股票代码")
@click.option("--log-file", default=None, help="交易流水 CSV 路径（默认自动查找）")
@click.option("--strategy", default="sma_cross", help="策略名称（当 --log-file 未指定时用于自动查找）")
@click.option("--output", default=None, help="输出 HTML 路径（默认自动生成）")
def report(symbol: str, log_file: Optional[str], strategy: str, output: Optional[str]):
    """生成可视化 HTML 报告：K线图 + 买卖点 + 权益曲线 + 回撤"""
    config = _load_config()
    sym = symbol.upper()

    # Load K-line data
    df = _load_cache_df(sym, config)

    # Load trade log
    if log_file:
        log_path = Path(log_file)
    else:
        log_path = Path(config["output"]["trades_dir"]) / f"{sym}_{strategy}.csv"

    if not log_path.exists():
        click.echo(f"错误: 交易流水文件不存在: {log_path}", err=True)
        click.echo("请先执行 backtest run 或指定 --log-file", err=True)
        return

    import pandas as pd

    trades = pd.read_csv(log_path)

    # Load equity data
    equity_path = Path(config["output"]["trades_dir"]) / f"{sym}_{strategy}_equity.csv"
    equity_data = None
    if equity_path.exists():
        equity_data = pd.read_csv(equity_path)
    else:
        click.echo(f"提示: 未找到权益数据 {equity_path}，报告不含权益曲线。")

    # Output path
    if output:
        out_path = Path(output)
    else:
        reports_dir = Path(config["output"]["reports_dir"])
        reports_dir.mkdir(parents=True, exist_ok=True)
        out_path = reports_dir / f"{sym}_{strategy}.html"

    generate_report(df, trades, sym, strategy, out_path, equity_data)
    click.echo(f"报告已生成: {out_path}")
