"""交互式命令 REPL —— 直接输入命令而非逐级菜单"""

import shlex
from datetime import date
from pathlib import Path
from typing import Optional

import click
import yaml
import pandas as pd

from data.downloader import DataDownloader, today_str, default_start


def _load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _list_cached_symbols(config: dict) -> list[str]:
    cache_dir = Path(config["data"]["cache_dir"])
    if not cache_dir.exists():
        return []
    return sorted(p.stem for p in cache_dir.glob("*.csv") if not p.name.startswith("_"))


def _list_strategies() -> list[str]:
    strat_dir = Path(__file__).parent.parent / "strategy"
    names = []
    for p in strat_dir.glob("*.py"):
        if p.stem in ("base", "__init__"):
            continue
        names.append(p.stem)
    return sorted(names)


def _load_cache_df(symbol: str, config: dict) -> pd.DataFrame:
    cache_dir = Path(config["data"]["cache_dir"])
    path = cache_dir / f"{symbol}.csv"
    if not path.exists():
        raise FileNotFoundError(f"缓存数据不存在: {path}")
    df = pd.read_csv(path, dtype={"date": str})
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def _parse_args(args: list[str]) -> dict:
    """将 ['--key1', 'val1', '--key2', '--key3', 'val3'] 解析为 {key1: val1, key2: True, key3: val3}"""
    kwargs = {}
    i = 0
    while i < len(args):
        if args[i].startswith("--"):
            key = args[i][2:].replace("-", "_")
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                kwargs[key] = args[i + 1]
                i += 2
            else:
                kwargs[key] = True
                i += 1
        else:
            i += 1
    return kwargs


def _build_strategy_params(symbol: str, args: dict) -> dict:
    """从 REPL 解析的参数构建策略参数字典。"""
    param_keys = [
        "fast_period", "slow_period", "period", "signal_period",
        "oversold", "overbought", "devfactor", "k_period", "smooth",
    ]
    params = {"symbol": symbol}
    for k in param_keys:
        if k in args:
            v = args[k]
            try:
                params[k] = int(v)
            except (ValueError, TypeError):
                try:
                    params[k] = float(v)
                except (ValueError, TypeError):
                    params[k] = v
    return params


def _print_help():
    click.echo()
    click.secho("可用命令:", fg="yellow", bold=True)
    click.echo()
    click.echo("  download, dl    下载股票日K线数据")
    click.echo("    参数: --symbol (股票代码, 不指定则下载全部A股)")
    click.echo("          --start (起始日期, 默认20210101)")
    click.echo("          --end (结束日期, 默认今天)")
    click.echo("          --force (强制重新下载)")
    click.echo("    示例: download --start 20210101 --end 20231231")
    click.echo("          download --symbol 000001.SZ --force")
    click.echo()
    click.echo("  backtest, bt    运行策略回测")
    click.echo("    参数: --strategy (策略名称)")
    click.echo("          --symbol (股票代码)")
    click.echo("          --symbols (多只股票逗号分隔)")
    click.echo("          --fast (快线周期)  --slow (慢线周期)")
    click.echo("          --period (通用周期)  --signal_period (信号周期)")
    click.echo("          --oversold (超卖阈值)  --overbought (超买阈值)")
    click.echo("          --devfactor (布林标准差倍数)  --k_period (KDJ周期)")
    click.echo("          --smooth (KDJ平滑参数)")
    click.echo(f"    可用策略: {', '.join(_list_strategies())}")
    click.echo("    示例: backtest --strategy sma_cross --symbol 000001.SZ")
    click.echo("          backtest --strategy macd_cross --symbol 000001.SZ --fast 12 --slow 26")
    click.echo("          backtest --strategy rsi --symbol 000001.SZ --period 14 --oversold 30")
    click.echo()
    click.echo("  scan            扫描近N日存在买点的股票")
    click.echo("    参数: --strategy (策略名称)  --days (回看天数)")
    click.echo("    示例: scan --strategy sma_cross --days 5")
    click.echo()
    click.echo("  report, rp      生成可视化 HTML 报告（不指定 --symbol 则为所有股票生成）")
    click.echo("    参数: --symbol (股票代码, 可选)  --strategy (策略名称, 可选)")
    click.echo("    示例: report --symbol 000001.SZ --strategy sma_cross")
    click.echo("          report --strategy rsi  (为所有RSI交易流水生成报告)")
    click.echo("          report  (为所有交易流水生成报告)")
    click.echo()
    click.echo("  compare, cmp    对比所有策略在单只股票上的表现")
    click.echo("    参数: --symbol (股票代码)")
    click.echo("    示例: compare --symbol 000001.SZ")
    click.echo()
    click.echo("  list            列出已缓存股票和可用策略")
    click.echo("  help            显示本帮助")
    click.echo("  exit, quit      退出程序")
    click.echo()


def _cmd_download(config: dict, **kwargs):
    symbol = kwargs.get("symbol", "")
    if isinstance(symbol, bool):
        symbol = ""
    symbol = symbol.strip().upper()
    start = kwargs.get("start", default_start())
    end = kwargs.get("end", today_str())
    force = bool(kwargs.get("force", False))

    dl = DataDownloader(config)

    if symbol:
        symbols = [s.strip().upper() for s in symbol.split(",")]
    else:
        stocks = dl.get_stock_list()
        if not stocks:
            click.secho("  无法获取股票列表。", fg="red")
            return
        symbols = [s["ts_code"] for s in stocks]
        click.echo(f"  将下载 {len(symbols)} 只股票的数据。")
        if not click.confirm("  确认下载全部股票数据?", default=True):
            return

    click.echo(f"  日期范围: {start} ~ {end}")
    click.echo(f"  股票数量: {len(symbols)}")
    click.echo()
    dl.download_batch(symbols, start, end, force)
    click.echo()
    click.secho("  下载完成。", fg="green")


def _cmd_backtest(config: dict, **kwargs):
    strategy = kwargs.get("strategy", "sma_cross")
    symbol = kwargs.get("symbol", "")
    if isinstance(symbol, bool):
        symbol = ""
    symbol = symbol.strip().upper()
    symbols_raw = kwargs.get("symbols", "")
    if isinstance(symbols_raw, bool):
        symbols_raw = ""
    symbols_raw = symbols_raw.strip()

    from engine.runner import BacktestRunner, load_strategy_class

    runner = BacktestRunner(config)
    cls = load_strategy_class(strategy)
    params = _build_strategy_params("", kwargs)

    if symbols_raw:
        sym_list = [s.strip().upper() for s in symbols_raw.split(",")]
    elif symbol:
        sym_list = [symbol]
    else:
        sym_list = _list_cached_symbols(config)
        if not sym_list:
            click.secho("  本地无缓存数据，请先执行 download。", fg="red")
            return
        click.echo(f"  未指定股票，将对全部 {len(sym_list)} 只已缓存股票进行批量回测。")
        click.echo(f"  建议先指定单只股票测试: backtest --strategy rsi --symbol 000001.SZ")
        if not click.confirm("  确认批量回测全部股票?", default=False):
            return

    data_map = {}
    for sym in sym_list:
        try:
            data_map[sym] = _load_cache_df(sym, config)
        except FileNotFoundError as e:
            click.echo(f"  跳过 {sym}: {e}")

    if not data_map:
        click.secho("  没有可用的数据。", fg="red")
        return

    trades_dir = Path(config["output"]["trades_dir"])
    trades_dir.mkdir(parents=True, exist_ok=True)

    if len(data_map) == 1:
        sym = list(data_map.keys())[0]
        params["symbol"] = sym
        df = data_map[sym]
        result = runner.run(df, cls, params)
        runner._export_trade_log(result["trade_records"], trades_dir, sym, strategy)
        runner._export_equity(result["equity"], trades_dir, sym, strategy)

        s = result["stats"]
        click.echo()
        click.secho(f"  --- 绩效摘要 [{sym}] ---", fg="green")
        click.echo(f"  总收益率:  {s['total_return_pct']}%")
        click.echo(f"  夏普比率:  {s['sharpe_ratio']}")
        click.echo(f"  最大回撤:  {s['max_drawdown_pct']}%")
        click.echo(f"  交易次数:  {s['total_trades']}")
        click.echo(f"  胜率:      {s['win_rate_pct']}%")
        click.echo(f"  最终资金:  {s['final_value']:,.2f}")
    else:
        runner.run_batch(data_map, strategy, params)


def _cmd_scan(config: dict, **kwargs):
    strategy = kwargs.get("strategy", "sma_cross")
    days = int(kwargs.get("days", 5))

    cached = _list_cached_symbols(config)
    if not cached:
        click.secho("  本地无缓存数据，请先执行 download。", fg="red")
        return

    data_map = {}
    for sym in cached:
        try:
            data_map[sym] = _load_cache_df(sym, config)
        except FileNotFoundError:
            pass

    if not data_map:
        click.secho("  没有可用的数据。", fg="red")
        return

    from engine.runner import BacktestRunner

    runner = BacktestRunner(config)
    params = _build_strategy_params("", kwargs)
    click.echo(f"  扫描 {len(data_map)} 只股票，回看 {days} 日 ...")
    results = runner.scan_recent_buy_signals(data_map, strategy, params, lookback_days=days)

    if results:
        click.echo()
        click.secho(f"  近{days}日存在买点的股票 ({len(results)} 只):", fg="green")
        for r in results:
            click.echo(f"    {r['symbol']:12s}  买点日期: {r['recent_buy_dates']:20s}  最新价: {r.get('last_price', '-')}")


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
        parts = name.split("_")
        for i in range(1, len(parts)):
            candidate_strategy = "_".join(parts[i:])
            candidate_symbol = "_".join(parts[:i])
            if candidate_strategy in ("sma_cross", "macd_cross", "kdj", "bollinger", "rsi", "single_ma"):
                if (symbol is None or candidate_symbol == symbol) and (strategy is None or candidate_strategy == strategy):
                    results.append((candidate_symbol, candidate_strategy, p))
                break
    return results


def _cmd_report(config: dict, **kwargs):
    symbol = kwargs.get("symbol", "")
    if isinstance(symbol, bool):
        symbol = ""
    symbol = symbol.strip().upper() or None
    strategy = kwargs.get("strategy")
    if isinstance(strategy, bool):
        strategy = None
    output = kwargs.get("output")

    trades_dir = Path(config["output"]["trades_dir"])
    reports_dir = Path(config["output"]["reports_dir"])
    reports_dir.mkdir(parents=True, exist_ok=True)

    from visual.report import generate_report
    from cli.backtest_cli import _run_batch_reports

    pairs = _find_trade_logs(trades_dir, symbol=symbol, strategy=strategy)

    if not pairs:
        click.secho("  未找到匹配的交易流水文件，请先执行回测。", fg="red")
        if trades_dir.exists():
            available = [p.name for p in trades_dir.glob("*.csv") if not p.name.startswith("_")]
            if available:
                click.echo(f"  可用流水: {', '.join(available[:20])}")
        return

    if output or len(pairs) == 1:
        sym, strat, log_path = pairs[0]
        try:
            df = _load_cache_df(sym, config)
        except FileNotFoundError:
            click.secho(f"  缓存数据不存在: {sym}", fg="red")
            return

        equity_path = trades_dir / f"{sym}_{strat}_equity.csv"
        equity_df = pd.read_csv(equity_path) if equity_path.exists() else None

        if output:
            out_path = Path(output)
        else:
            out_path = reports_dir / f"{sym}_{strat}.html"

        trades = pd.read_csv(log_path)
        generate_report(df, trades, sym, strat, out_path, equity_df)
        click.secho(f"  报告已生成: {out_path}", fg="green")
    else:
        _run_batch_reports(pairs, config)


def _cmd_compare(config: dict, **kwargs):
    symbol = kwargs.get("symbol", "")
    if isinstance(symbol, bool):
        symbol = ""
    symbol = symbol.strip().upper()
    if not symbol:
        click.secho("  请指定 --symbol。", fg="red")
        return

    try:
        df = _load_cache_df(symbol, config)
    except FileNotFoundError:
        click.secho(f"  缓存数据不存在: {symbol}", fg="red")
        return

    from engine.runner import BacktestRunner, load_strategy_class

    runner = BacktestRunner(config)
    strategy_configs = [
        ("sma_cross", {"fast_period": 5, "slow_period": 20}),
        ("macd_cross", {"fast_period": 12, "slow_period": 26, "signal_period": 9}),
        ("kdj", {"k_period": 9, "smooth": 3, "oversold": 20, "overbought": 80}),
        ("bollinger", {"period": 20, "devfactor": 2.0}),
        ("rsi", {"period": 14, "oversold": 30, "overbought": 70}),
        ("single_ma", {"period": 20}),
    ]

    click.echo()
    click.echo(f"  {'策略':<16s} {'收益率':>8s} {'夏普':>8s} {'最大回撤':>8s} {'交易数':>6s} {'胜率':>6s} {'最终资金':>10s}")
    click.echo("  " + "-" * 62)

    best_name, best_ret = "", -999.0
    for strategy_name, params in strategy_configs:
        params["symbol"] = symbol
        cls = load_strategy_class(strategy_name)
        result = runner.run(df, cls, params, verbose=False)
        stats = result["stats"]
        if stats["total_return_pct"] > best_ret:
            best_ret = stats["total_return_pct"]
            best_name = strategy_name

        click.echo(
            f"  {strategy_name:<16s} "
            f"{stats['total_return_pct']:>7.2f}% "
            f"{stats['sharpe_ratio']:>8.2f} "
            f"{stats['max_drawdown_pct']:>7.2f}% "
            f"{stats['total_trades']:>6d} "
            f"{stats['win_rate_pct']:>5.1f}% "
            f"{stats['final_value']:>10,.2f}"
        )

    click.echo()
    click.secho(f"  最佳策略: {best_name} (收益率 {best_ret:+.2f}%)", fg="green")


def _cmd_list(config: dict):
    cached = _list_cached_symbols(config)
    strats = _list_strategies()
    click.echo()
    click.secho(f"  已缓存股票 ({len(cached)} 只):", fg="cyan")
    if cached:
        for s in cached:
            click.echo(f"    {s}")
    click.echo()
    click.secho(f"  可用策略 ({len(strats)} 个):", fg="cyan")
    for s in strats:
        click.echo(f"    {s}")
    click.echo()


def run_interactive():
    """启动交互式命令 REPL"""
    config = _load_config()
    token = config.get("tushare", {}).get("token", "")
    if not token or token == "your_token_here":
        click.secho("  请先在 config.yaml 中配置 tushare token", fg="red")
        if not click.confirm("  Token 未配置，是否继续?", default=False):
            return

    click.clear()
    click.secho("=" * 52, fg="cyan")
    click.secho("   A 股量化回测系统  —  命令模式", fg="cyan", bold=True)
    click.secho("=" * 52, fg="cyan")
    click.echo()
    click.echo('  输入 "help" 查看命令列表，"exit" 退出。')
    click.echo(f'  已缓存股票: {len(_list_cached_symbols(config))} 只  |  可用策略: {", ".join(_list_strategies())}')
    click.echo()

    while True:
        try:
            raw = click.prompt("quant", prompt_suffix="> ").strip()
        except (EOFError, KeyboardInterrupt):
            click.echo()
            break

        if not raw:
            continue

        try:
            parts = shlex.split(raw)
        except ValueError:
            click.secho("  引号不匹配，请检查输入。", fg="red")
            continue

        cmd = parts[0].lower()
        args = _parse_args(parts[1:])

        try:
            if cmd in ("exit", "quit", "q"):
                break
            elif cmd == "help":
                _print_help()
            elif cmd == "list":
                _cmd_list(config)
            elif cmd in ("download", "dl"):
                _cmd_download(config, **args)
            elif cmd in ("backtest", "bt"):
                _cmd_backtest(config, **args)
            elif cmd == "scan":
                _cmd_scan(config, **args)
            elif cmd in ("report", "rp"):
                _cmd_report(config, **args)
            elif cmd in ("compare", "cmp"):
                _cmd_compare(config, **args)
            else:
                click.secho(f'  未知命令: "{cmd}"，输入 help 查看帮助。', fg="red")
        except KeyboardInterrupt:
            click.echo()
            click.secho("  操作已取消", fg="yellow")
        except Exception as e:
            click.secho(f"  错误: {e}", fg="red")

    click.secho("  再见!", fg="cyan")
