"""回测命令组: run / scan / report"""

import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import click
import pandas as pd
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


def _list_strategies() -> list[str]:
    strat_dir = Path(__file__).parent.parent / "strategy"
    names = []
    for p in strat_dir.glob("*.py"):
        if p.stem in ("base", "__init__"):
            continue
        names.append(p.stem)
    return sorted(names)


def _build_strategy_params(symbol: str, extra: dict) -> dict:
    """Build params dict from CLI options."""
    params = {"symbol": symbol}
    for k, v in extra.items():
        if v is not None:
            params[k] = v
    return params


# ============================================================
#  并行报告生成 worker
# ============================================================

def _report_worker(task: dict) -> Optional[dict]:
    """进程级报告生成 worker：加载数据 → 生成 HTML → 返回状态"""
    import sys as _sys
    _sys.stdout = open(os.devnull, "w")
    _sys.stderr = open(os.devnull, "w")
    for key in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS",
                "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[key] = "1"

    try:
        sym = task["symbol"]
        strat = task["strategy"]
        log_path = Path(task["log_path"])
        cache_path = Path(task["cache_dir"]) / f"{sym}.csv"
        reports_dir = Path(task["reports_dir"])
        trades_dir = Path(task["trades_dir"])

        df = pd.read_csv(cache_path, dtype={"date": str})
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        trades = pd.read_csv(log_path)

        equity_path = trades_dir / f"{sym}_{strat}_equity.csv"
        equity_df = pd.read_csv(equity_path) if equity_path.exists() else None

        out_path = reports_dir / f"{sym}_{strat}.html"
        generate_report(df, trades, sym, strat, out_path, equity_df)

        return {"symbol": sym, "strategy": strat, "success": True}
    except Exception as e:
        return {"symbol": task.get("symbol", "?"), "strategy": task.get("strategy", "?"),
                "success": False, "error": str(e)}


def _run_batch_reports(pairs: list[tuple[str, str, Path]], config: dict) -> tuple[int, int]:
    """并行批量生成报告，返回 (success_count, fail_count)。"""
    cache_dir = config["data"]["cache_dir"]
    trades_dir = config["output"]["trades_dir"]
    reports_dir = config["output"]["reports_dir"]
    Path(reports_dir).mkdir(parents=True, exist_ok=True)

    workers = config.get("parallel", {}).get("report_workers") or \
              config.get("parallel", {}).get("backtest_workers", 8)
    workers = max(1, min(workers, len(pairs)))

    tasks = [
        {"symbol": sym, "strategy": strat, "log_path": str(lp),
         "cache_dir": cache_dir, "trades_dir": trades_dir, "reports_dir": reports_dir}
        for sym, strat, lp in pairs
    ]

    click.echo(f"  并行生成报告 (进程数: {workers}, 共 {len(pairs)} 个)")

    success = 0
    failed = 0
    t0 = time.monotonic()
    completed = 0
    total = len(pairs)

    try:
        executor = ProcessPoolExecutor(max_workers=workers, max_tasks_per_child=100)
    except TypeError:
        executor = ProcessPoolExecutor(max_workers=workers)

    with executor as ex:
        futures = {ex.submit(_report_worker, t): t["symbol"] for t in tasks}
        for future in as_completed(futures):
            completed += 1
            try:
                r = future.result()
            except Exception:
                failed += 1
                continue

            if r and r.get("success"):
                success += 1
            else:
                failed += 1

            if completed % 500 == 0 or completed == total:
                elapsed = time.monotonic() - t0
                rate = completed / elapsed if elapsed > 0 else 0
                click.echo(f"  进度: {completed}/{total}  已耗时: {elapsed:.0f}s  速率: {rate:.1f}个/秒")

    elapsed = time.monotonic() - t0
    click.echo(f"  报告生成完成: {success}/{total} 个 → {reports_dir}  (总耗时 {elapsed:.0f}s)")
    return success, failed


# ============================================================
#  Click 命令组
# ============================================================

@click.group(name="backtest")
def backtest_group():
    """策略回测：运行回测、扫描买点、生成报告"""
    pass


@backtest_group.command(name="run")
@click.option("--strategy", required=True, help=f"策略名称，如 sma_cross。可用: {', '.join(_list_strategies())}")
@click.option("--symbol", default=None, help="股票代码。不指定则回测所有已缓存股票")
@click.option("--symbols", default=None, help="多只股票，逗号分隔，如 000001.SZ,600519.SH")
@click.option("--fast", default=None, type=int, help="快线/短周期参数 (sma_cross/macd_cross)")
@click.option("--slow", default=None, type=int, help="慢线/长周期参数 (sma_cross/macd_cross)")
@click.option("--period", default=None, type=int, help="通用周期参数 (single_ma/rsi/bollinger)")
@click.option("--signal-period", default=None, type=int, help="信号周期 (macd_cross)")
@click.option("--oversold", default=None, type=int, help="超卖阈值 (rsi/kdj)")
@click.option("--overbought", default=None, type=int, help="超买阈值 (rsi/kdj)")
@click.option("--devfactor", default=None, type=float, help="标准差倍数 (bollinger)")
@click.option("--k-period", default=None, type=int, help="KDJ K线周期")
@click.option("--smooth", default=None, type=int, help="KDJ 平滑参数")
def run_backtest(
    strategy: str, symbol: Optional[str], symbols: Optional[str],
    fast: Optional[int], slow: Optional[int], period: Optional[int],
    signal_period: Optional[int], oversold: Optional[int], overbought: Optional[int],
    devfactor: Optional[float], k_period: Optional[int], smooth: Optional[int],
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
        click.echo(f"未指定股票，将对全部 {len(sym_list)} 只已缓存股票进行批量回测。")
        click.echo(f"建议先指定单只股票测试: python main.py backtest run --strategy rsi --symbol 000001.SZ")
        if not click.confirm("确认批量回测全部股票?", default=False):
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
    strategy_params = _build_strategy_params("", {
        "fast_period": fast, "slow_period": slow, "period": period,
        "signal_period": signal_period, "oversold": oversold,
        "overbought": overbought, "devfactor": devfactor,
        "k_period": k_period, "smooth": smooth,
    })

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
@click.option("--fast", default=None, type=int, help="快线/短周期参数")
@click.option("--slow", default=None, type=int, help="慢线/长周期参数")
@click.option("--period", default=None, type=int, help="通用周期参数")
@click.option("--signal-period", default=None, type=int, help="信号周期 (macd_cross)")
@click.option("--oversold", default=None, type=int, help="超卖阈值 (rsi/kdj)")
@click.option("--overbought", default=None, type=int, help="超买阈值 (rsi/kdj)")
@click.option("--devfactor", default=None, type=float, help="标准差倍数 (bollinger)")
@click.option("--k-period", default=None, type=int, help="KDJ K线周期")
@click.option("--smooth", default=None, type=int, help="KDJ 平滑参数")
def scan_buy_signals(
    strategy: str, days: int,
    fast: Optional[int], slow: Optional[int], period: Optional[int],
    signal_period: Optional[int], oversold: Optional[int], overbought: Optional[int],
    devfactor: Optional[float], k_period: Optional[int], smooth: Optional[int],
):
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
    strategy_params = _build_strategy_params("", {
        "fast_period": fast, "slow_period": slow, "period": period,
        "signal_period": signal_period, "oversold": oversold,
        "overbought": overbought, "devfactor": devfactor,
        "k_period": k_period, "smooth": smooth,
    })
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


@backtest_group.command(name="compare")
@click.option("--symbol", required=True, help="股票代码")
def compare_strategies(symbol: str):
    """对比所有策略在单只股票上的表现"""
    config = _load_config()
    sym = symbol.upper()

    try:
        df = _load_cache_df(sym, config)
    except FileNotFoundError as e:
        click.echo(f"错误: {e}", err=True)
        return

    strategies = _list_strategies()
    runner = BacktestRunner(config)

    # Default params for each strategy
    strategy_configs = [
        ("sma_cross", {"fast_period": 5, "slow_period": 20}),
        ("macd_cross", {"fast_period": 12, "slow_period": 26, "signal_period": 9}),
        ("kdj", {"k_period": 9, "smooth": 3, "oversold": 20, "overbought": 80}),
        ("bollinger", {"period": 20, "devfactor": 2.0}),
        ("rsi", {"period": 14, "oversold": 30, "overbought": 70}),
        ("single_ma", {"period": 20}),
    ]

    click.echo(f"\n{'='*80}")
    click.echo(f"  策略对比 — {sym}")
    click.echo(f"{'='*80}")
    click.echo(f"{'策略':<16s} {'收益率':>8s} {'夏普':>8s} {'最大回撤':>8s} {'交易数':>6s} {'胜率':>6s} {'最终资金':>10s}")
    click.echo("-" * 64)

    results_list = []
    for strategy_name, params in strategy_configs:
        params["symbol"] = sym
        cls = load_strategy_class(strategy_name)
        result = runner.run(df, cls, params, verbose=False)
        stats = result["stats"]
        results_list.append((strategy_name, stats))

        click.echo(
            f"{strategy_name:<16s} "
            f"{stats['total_return_pct']:>7.2f}% "
            f"{stats['sharpe_ratio']:>8.2f} "
            f"{stats['max_drawdown_pct']:>7.2f}% "
            f"{stats['total_trades']:>6d} "
            f"{stats['win_rate_pct']:>5.1f}% "
            f"{stats['final_value']:>10,.2f}"
        )

    # Export results
    import pandas as pd
    rows = []
    for strategy_name, stats in results_list:
        rows.append({
            "strategy": strategy_name,
            "return_pct": stats["total_return_pct"],
            "sharpe": stats["sharpe_ratio"],
            "max_dd_pct": stats["max_drawdown_pct"],
            "trades": stats["total_trades"],
            "win_rate_pct": stats["win_rate_pct"],
            "final_value": stats["final_value"],
        })

    comparison_dir = Path(config["output"]["trades_dir"])
    comparison_dir.mkdir(parents=True, exist_ok=True)
    out_path = comparison_dir / f"_comparison_{sym}.csv"
    pd.DataFrame(rows).to_csv(out_path, index=False)
    click.echo(f"\n  对比结果已导出: {out_path}")

    # Best strategy
    best = max(results_list, key=lambda x: x[1]["total_return_pct"])
    click.echo(f"  最佳策略: {best[0]} (收益率 {best[1]['total_return_pct']:.2f}%)")


def _find_trade_logs(trades_dir: Path, symbol: Optional[str] = None, strategy: Optional[str] = None) -> list[tuple[str, str, Path]]:
    """Scan trades_dir for trade log CSVs. Returns [(symbol, strategy_name, log_path), ...]."""
    if not trades_dir.exists():
        return []
    results = []
    for p in trades_dir.glob("*.csv"):
        name = p.stem
        if name.startswith("_") or name.endswith("_equity"):
            continue
        if "_" not in name:
            continue
        # Find the split point: strategy is after the last underscore pattern
        # symbol can contain underscores (e.g. 000001.SZ has none, but symbol format is consistent)
        # Strategy names: sma_cross, macd_cross, kdj, bollinger, rsi, single_ma
        parts = name.split("_")
        # Try to find where strategy name starts
        for i in range(1, len(parts)):
            candidate_strategy = "_".join(parts[i:])
            candidate_symbol = "_".join(parts[:i])
            if candidate_strategy in ("sma_cross", "macd_cross", "kdj", "bollinger", "rsi", "single_ma"):
                if (symbol is None or candidate_symbol == symbol) and (strategy is None or candidate_strategy == strategy):
                    results.append((candidate_symbol, candidate_strategy, p))
                break
    return results


def _generate_one_report(config: dict, symbol: str, strategy: str, log_path: Path, output_path: Optional[Path] = None) -> Optional[Path]:
    """Generate a single HTML report. Returns output path or None on failure."""
    import pandas as pd

    cache_dir = Path(config["data"]["cache_dir"])
    cache_path = cache_dir / f"{symbol}.csv"
    if not cache_path.exists():
        click.echo(f"  跳过 {symbol}: 缓存数据不存在")
        return None

    df = pd.read_csv(cache_path, dtype={"date": str})
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    trades = pd.read_csv(log_path)

    trades_dir = Path(config["output"]["trades_dir"])
    equity_path = trades_dir / f"{symbol}_{strategy}_equity.csv"
    equity_data = pd.read_csv(equity_path) if equity_path.exists() else None

    if output_path:
        out_path = output_path
    else:
        reports_dir = Path(config["output"]["reports_dir"])
        reports_dir.mkdir(parents=True, exist_ok=True)
        out_path = reports_dir / f"{symbol}_{strategy}.html"

    generate_report(df, trades, symbol, strategy, out_path, equity_data)
    return out_path


@backtest_group.command(name="report")
@click.option("--symbol", default=None, help="股票代码。不指定则为所有有交易流水的股票生成报告")
@click.option("--log-file", default=None, help="交易流水 CSV 路径（默认自动查找）")
@click.option("--strategy", default=None, help="策略名称。不指定则匹配所有策略")
@click.option("--output", default=None, help="输出 HTML 路径（批量模式下忽略）")
def report(symbol: Optional[str], log_file: Optional[str], strategy: Optional[str], output: Optional[str]):
    """生成可视化 HTML 报告：K线图 + 买卖点 + 权益曲线 + 回撤"""
    config = _load_config()
    trades_dir = Path(config["output"]["trades_dir"])
    reports_dir = Path(config["output"]["reports_dir"])
    reports_dir.mkdir(parents=True, exist_ok=True)

    if log_file:
        # Explicit log file: single report mode
        if not symbol:
            click.echo("错误: 指定 --log-file 时必须同时指定 --symbol", err=True)
            return
        strat = strategy or "unknown"
        log_path = Path(log_file)
        if not log_path.exists():
            click.echo(f"错误: 交易流水文件不存在: {log_path}", err=True)
            return
        out = _generate_one_report(config, symbol.upper(), strat, log_path,
                                   Path(output) if output else None)
        if out:
            click.echo(f"报告已生成: {out}")
        return

    # Auto-detect mode
    sym_filter = symbol.upper() if symbol else None
    pairs = _find_trade_logs(trades_dir, symbol=sym_filter, strategy=strategy)

    if not pairs:
        click.echo("错误: 未找到匹配的交易流水文件，请先执行 backtest run。", err=True)
        return

    if len(pairs) == 1:
        sym, strat, log_path = pairs[0]
        out = _generate_one_report(config, sym, strat, log_path,
                                   Path(output) if output else None)
        if out:
            click.echo(f"报告已生成: {out}")
    else:
        _run_batch_reports(pairs, config)
