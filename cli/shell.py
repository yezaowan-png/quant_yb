"""交互式命令 REPL —— 直接输入命令而非逐级菜单"""

import shlex
from datetime import date
from pathlib import Path
from typing import Optional

import click
import yaml
import pandas as pd

from data.downloader import DataDownloader, today_str, default_start
from strategy.base import normalize_strategy_params


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


def _strategy_names_by_length() -> list[str]:
    return sorted(_list_strategies(), key=len, reverse=True)


def _split_trade_log_name(name: str) -> Optional[tuple[str, str]]:
    for strategy_name in _strategy_names_by_length():
        suffix = f"_{strategy_name}"
        if name.endswith(suffix):
            symbol = name[:-len(suffix)]
            if symbol:
                return symbol, strategy_name
    return None


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


def _build_strategy_params(strategy_cls, symbol: str, args: dict) -> dict:
    """从 REPL 解析的参数构建策略参数字典。"""
    params, ignored = normalize_strategy_params(strategy_cls, args, symbol)
    if ignored:
        click.echo(f"  提示: 当前策略不使用这些参数，已忽略: {', '.join(ignored)}")
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
    click.echo("  index           指数数据与每日概览")
    click.echo("    子命令: download / report / overview")
    click.echo("    参数: --symbol (默认 000001.SH) --all --start --end --force --output")
    click.echo("    示例: index overview --symbol 000001.SH")
    click.echo("          index overview --all")
    click.echo("          index report --symbol 000001.SH")
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
    click.echo("          --lookback --max_range_pct --volume_multiplier (平台突破参数)")
    click.echo("          --platform_sell_tolerance --stop_loss_pct (平台突破卖出参数)")
    click.echo(f"    可用策略: {', '.join(_list_strategies())}")
    click.echo("    示例: backtest --strategy sma_cross --symbol 000001.SZ")
    click.echo("          backtest --strategy macd_cross --symbol 000001.SZ --fast 12 --slow 26")
    click.echo("          backtest --strategy rsi --symbol 000001.SZ --period 14 --oversold 30")
    click.echo()
    click.echo("  scan            扫描近N日存在买点的股票")
    click.echo("    参数: --strategy (策略名称)  --days (回看天数)")
    click.echo("    示例: scan --strategy sma_cross --days 5")
    click.echo()
    click.echo("  decision        决策记忆：记录买点并复盘未来表现")
    click.echo("    子命令: record / evaluate / summary")
    click.echo("    示例: decision record --strategy sma_cross")
    click.echo("          decision evaluate --strategy sma_cross --horizons 5,10,20")
    click.echo("          decision summary --strategy sma_cross")
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
    click.echo("  stats           数据统计分析")
    click.echo("    子命令: analyze (单策略画像)  /  compare (多策略对比)")
    click.echo("    参数: --strategy (策略名称, analyze 必需)")
    click.echo("    示例: stats analyze --strategy rsi")
    click.echo("          stats compare")
    click.echo()
    click.echo("  dashboard       生成项目汇总导航面板")
    click.echo("    参数: --output (输出 HTML 路径，默认 output/reports/dashboard.html)")
    click.echo("    示例: dashboard")
    click.echo()
    click.echo("  experiment      实验配置：从 YAML 运行可归档回测任务")
    click.echo("    子命令: run")
    click.echo("    示例: experiment run experiments/sma_cross_baseline.yaml")
    click.echo()
    click.echo("  audit           静态审计：未来函数和数据泄露启发式检查")
    click.echo("    子命令: lookahead")
    click.echo("    示例: audit lookahead --strategy sma_cross")
    click.echo("          audit lookahead")
    click.echo()
    click.echo("  portfolio       组合研究：从买点信号生成目标权重")
    click.echo("    子命令: build")
    click.echo("    示例: portfolio build --signals output/signals/buy_signals_sma_cross_YYYYMMDD.csv")
    click.echo()
    click.secho("  放量平台突破常用命令（可直接复制）:", fg="yellow", bold=True)
    click.echo("    1) 回测全市场:")
    click.echo("       backtest --strategy volume_platform_breakout")
    click.echo("    2) 生成报告:")
    click.echo("       report --strategy volume_platform_breakout")
    click.echo("       report --symbol 603662.SH --strategy volume_platform_breakout")
    click.echo("    3) 生成策略画像统计:")
    click.echo("       stats analyze --strategy volume_platform_breakout")
    click.echo("    4) 扫描最近买点:")
    click.echo("       scan --strategy volume_platform_breakout --days 10")
    click.echo("    5) 一键流水线:")
    click.echo('       run "backtest --strategy volume_platform_breakout; report --strategy volume_platform_breakout; stats analyze --strategy volume_platform_breakout"')
    click.echo()
    click.echo("  list            列出已缓存股票和可用策略")
    click.echo("  run             按顺序批量执行多条命令")
    click.echo("    参数: 命令字符串（分号 ; 或换行分隔），或 --file 指定脚本文件")
    click.echo("    每行可加 ! 前缀忽略该条失败继续执行")
    click.echo("    示例: run \"download; backtest --strategy rsi; report; stats compare\"")
    click.echo("          run --file pipeline.txt")
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


def _index_symbol_name(config: dict, symbol: str) -> str:
    for item in config.get("index_overview", {}).get("indexes", []):
        if item.get("symbol", "").upper() == symbol.upper():
            return item.get("name") or symbol
    return "上证指数" if symbol.upper() == "000001.SH" else symbol


def _configured_index_items(config: dict) -> list[dict]:
    indexes = config.get("index_overview", {}).get("indexes", [])
    if indexes:
        return indexes
    return [{"symbol": "000001.SH", "name": "上证指数", "market": "SH"}]


def _cmd_index(config: dict, **kwargs):
    sub = kwargs.get("sub") or "overview"
    all_indexes = bool(kwargs.get("all", False))
    if all_indexes:
        index_items = _configured_index_items(config)
    else:
        symbol = kwargs.get("symbol") or config.get("index_overview", {}).get("default_symbol", "000001.SH")
        if isinstance(symbol, bool):
            symbol = "000001.SH"
        symbol = symbol.strip().upper()
        index_items = [{"symbol": symbol, "name": _index_symbol_name(config, symbol)}]
    start = kwargs.get("start", default_start())
    end = kwargs.get("end", today_str())
    force = bool(kwargs.get("force", False))
    output = kwargs.get("output")
    if isinstance(output, bool):
        output = None

    dl = DataDownloader(config)

    if sub == "download":
        click.echo(f"  日期范围: {start} ~ {end}")
        click.echo(f"  指数数量: {len(index_items)}")
        for item in index_items:
            symbol = item["symbol"].upper()
            name = item.get("name") or _index_symbol_name(config, symbol)
            click.echo(f"  指数: {symbol} ({name})")
            df = dl.download_index(symbol=symbol, start=start, end=end, force=force)
            click.secho(f"  完成: {len(df)} 条指数日线，缓存文件: {dl._index_cache_path(symbol)}", fg="green")
        return

    from visual.index_report import generate_index_report

    click.echo(f"  指数数量: {len(index_items)}")
    if sub == "download":
        pass
    elif sub not in {"report", "overview"}:
        click.secho("  用法: index download|report|overview --symbol 000001.SH 或 --all", fg="yellow")
        return

    for item in index_items:
        symbol = item["symbol"].upper()
        name = item.get("name") or _index_symbol_name(config, symbol)
        click.echo(f"  指数: {symbol} ({name})")

        if sub == "overview":
            click.echo(f"  日期范围: {start} ~ {end}")
            df = dl.download_index(symbol=symbol, start=start, end=end, force=force)
        else:
            df = dl.load_index_cache(symbol)
            if df is None or df.empty:
                click.secho(f"  指数缓存不存在: {symbol}，请先执行 index download --symbol {symbol}", fg="red")
                return

        if output and all_indexes:
            out_path = Path(output) / f"{symbol}_overview.html"
        elif output:
            out_path = Path(output)
        else:
            out_path = Path(config["output"]["reports_dir"]) / "index" / f"{symbol}_overview.html"
        generate_index_report(df, symbol=symbol, name=name, output_path=out_path)
        click.secho(f"  报告已生成: {out_path}", fg="green")

    return


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
    params = _build_strategy_params(cls, "", kwargs)

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
        click.echo(f"  年化收益:  {s['annual_return_pct']}%")
        click.echo(f"  年化波动:  {s['annual_volatility_pct']}%")
        if "excess_return_pct" in s:
            click.echo(f"  超额收益:  {s['excess_return_pct']}%")
            click.echo(f"  信息比率:  {s['information_ratio']}")
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

    from engine.runner import BacktestRunner, load_strategy_class

    runner = BacktestRunner(config)
    cls = load_strategy_class(strategy)
    params = _build_strategy_params(cls, "", kwargs)
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
        split = _split_trade_log_name(name)
        if split is None:
            continue
        candidate_symbol, candidate_strategy = split
        if (symbol is None or candidate_symbol == symbol) and (strategy is None or candidate_strategy == strategy):
            results.append((candidate_symbol, candidate_strategy, p))
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
    strategies = _list_strategies()

    click.echo()
    click.echo(f"  {'策略':<16s} {'收益率':>8s} {'夏普':>8s} {'最大回撤':>8s} {'交易数':>6s} {'胜率':>6s} {'最终资金':>10s}")
    click.echo("  " + "-" * 62)

    best_name, best_ret = "", -999.0
    for strategy_name in strategies:
        params = {"symbol": symbol}
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


def _cmd_stats(config: dict, **kwargs):
    """stats 命令路由：分发到 analyze 或 compare 子命令。"""
    sub = kwargs.get("sub", "")
    if isinstance(sub, bool):
        sub = ""
    sub = sub.strip().lower()

    strategy = kwargs.get("strategy", "")
    if isinstance(strategy, bool):
        strategy = ""

    from analysis.report import build_analyze_page, build_compare_page
    from analysis.analyzer import load_summary, load_all_summaries, compute_stats, _STRATEGY_LABELS

    stats_dir = Path(config["output"].get("statistics_dir", "output/statistics"))
    stats_dir.mkdir(parents=True, exist_ok=True)

    if sub == "analyze":
        if not strategy:
            click.secho("  请指定 --strategy。示例: stats analyze --strategy rsi", fg="red")
            return
        df = load_summary(strategy)
        if df is None or len(df) == 0:
            click.secho(f"  策略 '{strategy}' 无回测数据。请先执行 backtest run --strategy {strategy}", fg="red")
            return
        s = compute_stats(df)
        display = _STRATEGY_LABELS.get(strategy, strategy)
        click.echo()
        click.secho(f"  {display} — 策略画像 ({s['count']} 只)", fg="green")
        click.echo(f"  平均收益: {s['avg_return']:+.1f}%    中位数: {s['median_return']:+.1f}%")
        click.echo(f"  正收益比例: {s['positive_ratio']:.1f}%    "
                   f"平均夏普: {s['avg_sharpe']:.3f}    平均回撤: {s['avg_max_dd']:.1f}%")
        click.echo(f"  平均胜率: {s['avg_win_rate']:.1f}%    平均交易: {s['avg_trades']} 次")
        click.echo()
        output_path = stats_dir / f"analysis_{strategy}.html"
        build_analyze_page(strategy, df, output_path)
        click.secho(f"  报告已生成: {output_path}", fg="green")
    elif sub == "compare":
        data_map = load_all_summaries()
        if len(data_map) < 2:
            click.secho("  需要至少 2 个策略有回测数据。", fg="red")
            return
        click.echo()
        click.secho(f"  策略横向对比 ({len(data_map)} 个策略)", fg="green")
        for name, df in data_map.items():
            s = compute_stats(df)
            display = _STRATEGY_LABELS.get(name, name)
            click.echo(f"  {display:<10s}  {s['count']:>5d} 只  "
                       f"收益 {s['avg_return']:>+7.1f}%  正向率 {s['positive_ratio']:>5.1f}%")
        click.echo()
        output_path = stats_dir / "comparison.html"
        build_compare_page(data_map, output_path)
        click.secho(f"  报告已生成: {output_path}", fg="green")
    else:
        click.secho(f'  未知子命令: "{sub}"。可用: analyze, compare。示例: stats analyze --strategy rsi', fg="red")


def _cmd_dashboard(config: dict, **kwargs):
    from visual.dashboard import generate_dashboard

    output = kwargs.get("output")
    if isinstance(output, bool):
        output = None
    out_path = generate_dashboard(config, output)
    click.secho(f"  汇总面板已生成: {out_path}", fg="green")


def _cmd_experiment(config: dict, **kwargs):
    sub = kwargs.get("sub") or "run"
    if isinstance(sub, bool):
        sub = "run"
    sub = str(sub).strip().lower()
    if sub != "run":
        click.secho("  用法: experiment run <config.yaml>", fg="yellow")
        return

    config_path = kwargs.get("config_path") or kwargs.get("path")
    if isinstance(config_path, bool) or not config_path:
        click.secho("  请提供实验配置路径。示例: experiment run experiments/sma_cross_baseline.yaml", fg="red")
        return

    from experiment.runner import run_experiment

    manifest = run_experiment(config, config_path)
    counts = manifest.get("result_counts", {})
    click.secho(f"  实验已完成: {manifest['id']} ({manifest['status']})", fg="green")
    click.echo(f"  标的: {counts.get('succeeded', 0)}/{counts.get('requested', 0)} 成功")
    click.echo(f"  输出目录: {manifest['output_dir']}")


def _cmd_audit(config: dict, **kwargs):
    sub = kwargs.get("sub") or "lookahead"
    if isinstance(sub, bool):
        sub = "lookahead"
    sub = str(sub).strip().lower()
    if sub != "lookahead":
        click.secho("  用法: audit lookahead [--strategy 策略名]", fg="yellow")
        return

    from audit.lookahead import run_lookahead_audit

    strategy = kwargs.get("strategy") or None
    if isinstance(strategy, bool):
        strategy = None
    output_dir = kwargs.get("output") or config.get("output", {}).get("audit_dir", "output/audit")
    if isinstance(output_dir, bool):
        output_dir = "output/audit"
    df, csv_path, html_path = run_lookahead_audit(strategy=strategy, output_dir=output_dir)
    high = int((df["severity"] == "high").sum()) if not df.empty else 0
    medium = int((df["severity"] == "medium").sum()) if not df.empty else 0
    low = int((df["severity"] == "low").sum()) if not df.empty else 0
    click.echo(f"  Lookahead Audit: High {high} | Medium {medium} | Low {low}")
    click.echo(f"  CSV:  {csv_path}")
    click.echo(f"  HTML: {html_path}")


def _cmd_portfolio(config: dict, **kwargs):
    sub = kwargs.get("sub") or "build"
    if isinstance(sub, bool):
        sub = "build"
    sub = str(sub).strip().lower()
    if sub != "build":
        click.secho("  用法: portfolio build --signals <buy_signals.csv>", fg="yellow")
        return

    signals_path = kwargs.get("signals")
    if isinstance(signals_path, bool) or not signals_path:
        click.secho("  请提供 --signals。", fg="red")
        return
    from portfolio.allocator import build_target_weights

    result = build_target_weights(
        config=config,
        signals_path=Path(signals_path),
        method=str(kwargs.get("method") or "equal"),
        max_weight=float(kwargs.get("max_weight") or kwargs.get("max-weight") or 0.10),
        gross_exposure=float(kwargs.get("gross_exposure") or kwargs.get("gross-exposure") or 1.0),
        lookback=int(kwargs.get("lookback") or 60),
        output_dir=kwargs.get("output") or None,
    )
    click.secho(f"  目标权重已生成: {result.output_path}", fg="green")
    click.echo(f"  标的 {result.count} | 总仓位 {result.gross_exposure:.2%} | 最大单股 {result.max_weight:.2%}")


def _cmd_decision(config: dict, **kwargs):
    sub = kwargs.get("sub") or "summary"
    if isinstance(sub, bool):
        sub = "summary"
    sub = sub.strip().lower()
    strategy = kwargs.get("strategy")
    if isinstance(strategy, bool):
        strategy = None
    symbol = kwargs.get("symbol")
    if isinstance(symbol, bool):
        symbol = None

    if sub == "record":
        if not strategy:
            click.secho("  请指定 --strategy。示例: decision record --strategy sma_cross", fg="red")
            return
        from cli.decision_cli import _latest_signals_file, _load_data_map_for_file
        from decision.recorder import append_signals_from_file

        signals_file = kwargs.get("signals_file")
        if isinstance(signals_file, bool):
            signals_file = None
        path = Path(signals_file) if signals_file else _latest_signals_file(config, strategy)
        if path is None or not path.exists():
            click.secho(f"  未找到策略 {strategy} 的买点 CSV，请先执行 scan --strategy {strategy}", fg="red")
            return
        data_map = _load_data_map_for_file(config, path)
        out_path, added = append_signals_from_file(config, strategy, path, data_map=data_map)
        click.secho(f"  决策记忆已更新: {out_path}，新增 {added} 条", fg="green")
    elif sub == "evaluate":
        from decision.evaluator import evaluate_memory, parse_horizons

        horizons = kwargs.get("horizons", "5,10,20")
        if isinstance(horizons, bool):
            horizons = "5,10,20"
        stats = evaluate_memory(
            config,
            strategy=strategy,
            symbol=symbol,
            horizons=parse_horizons(str(horizons)),
        )
        click.secho(f"  决策记忆评估完成: {stats['path']}", fg="green")
        click.echo(f"  匹配 {stats['matched']} | 完整 {stats['evaluated']} | 部分 {stats['partial']} | 待评估 {stats['pending']} | 缺数据 {stats['missing']}")
    elif sub == "summary":
        from decision.evaluator import summarize_memory
        from decision.recorder import decision_memory_path

        summary = summarize_memory(config, strategy=strategy)
        click.echo(f"  决策记忆: {decision_memory_path(config)}")
        click.echo(f"  信号 {summary['count']} | 完整 {summary['evaluated']} | 部分 {summary['partial']} | 待评估 {summary['pending']}")
        click.echo(f"  最新信号: {summary['latest_signal_date'] or '--'}")
        avg_5d = summary["avg_future_5d_return_pct"]
        avg_excess = summary["avg_excess_5d_return_pct"]
        click.echo(f"  平均5日收益: {'--' if avg_5d is None else f'{avg_5d:+.2f}%'}")
        click.echo(f"  平均5日超额: {'--' if avg_excess is None else f'{avg_excess:+.2f}%'}")
    else:
        click.secho("  用法: decision record|evaluate|summary", fg="yellow")


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


def _execute_pipeline(config: dict, commands_text: str) -> None:
    """按顺序执行多条命令（分号或换行分隔）。

    遇到错误立即停止，可通过 ! 前缀忽略某条命令的失败（类似 make）。"""
    # 先按换行拆，再按分号拆
    lines = []
    for raw_line in commands_text.strip().split("\n"):
        raw_line = raw_line.strip()
        if not raw_line or raw_line.startswith("#"):
            continue
        for part in raw_line.split(";"):
            part = part.strip()
            if part and not part.startswith("#"):
                lines.append(part)

    if not lines:
        click.secho("  没有可执行的命令。", fg="yellow")
        return

    for line_no, command_line in enumerate(lines, 1):
        # 支持 ! 前缀：即使这条命令失败也继续
        ignore_error = command_line.startswith("!")
        if ignore_error:
            command_line = command_line[1:].strip()

        try:
            parts = shlex.split(command_line)
        except ValueError:
            click.secho(f"  [{line_no}/{len(lines)}] 引号不匹配，跳过: {command_line}", fg="red")
            if not ignore_error:
                break
            continue

        if not parts:
            continue

        cmd = parts[0].lower()
        args = _parse_args(parts[1:])

        click.echo()
        click.secho(f"── [{line_no}/{len(lines)}] $ {command_line}", fg="cyan")

        try:
            if cmd in ("exit", "quit", "q"):
                click.secho(f"  流水线在第 {line_no} 条终止（exit）。", fg="yellow")
                break
            elif cmd == "help":
                _print_help()
            elif cmd == "list":
                _cmd_list(config)
            elif cmd in ("download", "dl"):
                _cmd_download(config, **args)
            elif cmd == "index":
                sub = parts[1] if len(parts) > 1 else "overview"
                sub_args = _parse_args(parts[2:]) if len(parts) > 2 else {}
                sub_args["sub"] = sub
                _cmd_index(config, **sub_args)
            elif cmd in ("backtest", "bt"):
                _cmd_backtest(config, **args)
            elif cmd == "scan":
                _cmd_scan(config, **args)
            elif cmd == "decision":
                sub = parts[1] if len(parts) > 1 else "summary"
                sub_args = _parse_args(parts[2:]) if len(parts) > 2 else {}
                sub_args["sub"] = sub
                _cmd_decision(config, **sub_args)
            elif cmd in ("report", "rp"):
                _cmd_report(config, **args)
            elif cmd in ("compare", "cmp"):
                _cmd_compare(config, **args)
            elif cmd == "stats":
                sub = parts[1] if len(parts) > 1 else ""
                sub_args = _parse_args(parts[2:]) if len(parts) > 2 else {}
                sub_args["sub"] = sub
                _cmd_stats(config, **sub_args)
            elif cmd == "dashboard":
                _cmd_dashboard(config, **args)
            elif cmd == "experiment":
                sub = parts[1] if len(parts) > 1 else "run"
                sub_args = _parse_args(parts[3:]) if len(parts) > 3 else {}
                sub_args["sub"] = sub
                if len(parts) > 2:
                    sub_args["config_path"] = parts[2]
                _cmd_experiment(config, **sub_args)
            elif cmd == "audit":
                sub = parts[1] if len(parts) > 1 else "lookahead"
                sub_args = _parse_args(parts[2:]) if len(parts) > 2 else {}
                sub_args["sub"] = sub
                _cmd_audit(config, **sub_args)
            elif cmd == "portfolio":
                sub = parts[1] if len(parts) > 1 else "build"
                sub_args = _parse_args(parts[2:]) if len(parts) > 2 else {}
                sub_args["sub"] = sub
                _cmd_portfolio(config, **sub_args)
            else:
                click.secho(f'  未知命令: "{cmd}"', fg="red")
                if not ignore_error:
                    click.secho(f"  流水线在第 {line_no} 条中止。", fg="red")
                    break
        except KeyboardInterrupt:
            click.echo()
            click.secho("  流水线被用户中断。", fg="yellow")
            break
        except Exception as e:
            click.secho(f"  错误: {e}", fg="red")
            if not ignore_error:
                click.secho(f"  流水线在第 {line_no} 条中止。", fg="red")
                break

    click.echo()
    click.secho(f"  流水线执行完毕。", fg="green")


def _cmd_run(config: dict, **kwargs):
    """run 命令：从参数或文件读取并执行命令序列。"""
    commands_text = kwargs.get("commands", "")
    file_path = kwargs.get("file", "")

    if file_path:
        file_p = Path(file_path)
        if not file_p.exists():
            click.secho(f"  文件不存在: {file_path}", fg="red")
            return
        commands_text = file_p.read_text(encoding="utf-8")

    if not commands_text or not commands_text.strip():
        click.secho("  请提供要执行的命令。用法: run \"cmd1; cmd2\" 或 run --file script.txt", fg="yellow")
        return

    _execute_pipeline(config, commands_text)


def run_interactive():
    """启动交互式命令 REPL"""
    config = _load_config()
    token = config.get("tushare", {}).get("token", "")
    if not token or token in {"your_token_here", "你的Tushare Token"}:
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

        # run 命令特殊处理：后续内容直接作为命令字符串
        if cmd == "run":
            file_arg = ""
            commands_arg = " ".join(parts[1:])
            if commands_arg.startswith("--file"):
                file_arg = commands_arg[len("--file"):].strip()
                commands_arg = ""
            _cmd_run(config, commands=commands_arg, file=file_arg)
            continue

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
            elif cmd == "index":
                sub = parts[1] if len(parts) > 1 else "overview"
                sub_args = _parse_args(parts[2:]) if len(parts) > 2 else {}
                sub_args["sub"] = sub
                _cmd_index(config, **sub_args)
            elif cmd in ("backtest", "bt"):
                _cmd_backtest(config, **args)
            elif cmd == "scan":
                _cmd_scan(config, **args)
            elif cmd == "decision":
                sub = parts[1] if len(parts) > 1 else "summary"
                sub_args = _parse_args(parts[2:]) if len(parts) > 2 else {}
                sub_args["sub"] = sub
                _cmd_decision(config, **sub_args)
            elif cmd in ("report", "rp"):
                _cmd_report(config, **args)
            elif cmd in ("compare", "cmp"):
                _cmd_compare(config, **args)
            elif cmd == "stats":
                # stats has subcommands that _parse_args would drop
                sub = parts[1] if len(parts) > 1 else ""
                sub_args = _parse_args(parts[2:]) if len(parts) > 2 else {}
                sub_args["sub"] = sub
                _cmd_stats(config, **sub_args)
            elif cmd == "dashboard":
                _cmd_dashboard(config, **args)
            elif cmd == "experiment":
                sub = parts[1] if len(parts) > 1 else "run"
                sub_args = _parse_args(parts[3:]) if len(parts) > 3 else {}
                sub_args["sub"] = sub
                if len(parts) > 2:
                    sub_args["config_path"] = parts[2]
                _cmd_experiment(config, **sub_args)
            elif cmd == "audit":
                sub = parts[1] if len(parts) > 1 else "lookahead"
                sub_args = _parse_args(parts[2:]) if len(parts) > 2 else {}
                sub_args["sub"] = sub
                _cmd_audit(config, **sub_args)
            elif cmd == "portfolio":
                sub = parts[1] if len(parts) > 1 else "build"
                sub_args = _parse_args(parts[2:]) if len(parts) > 2 else {}
                sub_args["sub"] = sub
                _cmd_portfolio(config, **sub_args)
            else:
                click.secho(f'  未知命令: "{cmd}"，输入 help 查看帮助。', fg="red")
        except KeyboardInterrupt:
            click.echo()
            click.secho("  操作已取消", fg="yellow")
        except Exception as e:
            click.secho(f"  错误: {e}", fg="red")

    click.secho("  再见!", fg="cyan")
