"""交互式命令 REPL —— 直接输入命令而非逐级菜单"""

import shlex
from pathlib import Path

import click
from cli.common import list_cached_symbols as _list_cached_symbols
from cli.common import list_strategies as _list_strategies
from cli.common import load_config as _load_config
from cli.data_cli import run_daily_basic, run_data_audit, run_download, run_stock_basic
from cli.dashboard_cli import run_dashboard
from cli.etf_cli import run_etf_report
from cli.index_cli import (
    run_index_download,
    run_index_forecast,
    run_index_forecast_diagnose,
    run_index_llm_summary,
    run_index_market,
    run_index_members,
    run_index_overview,
    run_index_report,
    run_index_ths,
)
from cli.stats_cli import run_limit_strength, run_support_resistance
from cli.sector_money_flow_cli import (
    run_sector_money_flow_collect,
    run_sector_money_flow_report,
    run_sector_money_flow_watch,
)
from data.downloader import today_str, default_start


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


def _print_help():
    click.echo()
    click.secho("可用命令:", fg="yellow", bold=True)
    click.echo()
    click.echo("  download, dl    下载股票日K线数据")
    click.echo("    参数: --symbol (股票代码, 不指定则下载全部A股)")
    click.echo("          --start (起始日期, 默认读取 defaults.start_date，当前20110101)")
    click.echo("          --end (结束日期, 默认今天)")
    click.echo("          --force (强制重新下载)")
    click.echo("          --failed_file/--failed-file (从失败记录CSV/TXT补下载)")
    click.echo("    示例: download --start 20110101 --end 20231231")
    click.echo("          download --symbol 000001.SZ --force")
    click.echo()
    click.echo("  stock-basic     下载股票基础信息和代码名称映射")
    click.echo("    参数: --list-status (L上市/D退市/P暂停上市) --force")
    click.echo("    示例: stock-basic --force")
    click.echo()
    click.echo("  daily-basic     下载全市场每日指标 daily_basic")
    click.echo("    参数: --start --end --force")
    click.echo("    示例: daily-basic --start 20260101 --end 20260618")
    click.echo()
    click.echo("  data-audit      检查本地个股、指数和 daily_basic 数据质量")
    click.echo("    参数: --deep (逐行扫描完整历史) --output (JSON/CSV 输出目录)")
    click.echo("    示例: data-audit")
    click.echo()
    click.echo("  index           指数数据与每日概览")
    click.echo("    子命令: download / report / overview / ths / market / members / forecast / structure / forecast-diagnose / llm-summary")
    click.echo("    参数: --symbol (默认 000001.SH) --all --start --end --force --output")
    click.echo("    示例: index overview --symbol 000001.SH")
    click.echo("          index overview --all")
    click.echo("          index report --symbol 000001.SH")
    click.echo("          index ths --include-concepts --skip-failures")
    click.echo("          index market")
    click.echo("          index members --all")
    click.echo("          index forecast --symbol 000001.SH --horizon 5")
    click.echo("          index structure --symbol 000001.SH --horizon 5  # forecast 的结构分析别名")
    click.echo("          index llm-summary --symbol 000001.SH --horizon 5")
    click.echo()
    click.echo("  etf             ETF 策略研究板块")
    click.echo("    子命令: report / signals")
    click.echo("    参数: report --symbols (ETF代码逗号分隔) --start --end --force --output")
    click.echo("          signals --refresh --symbol 515880.SH --top-n 10")
    click.echo("    示例: etf report --symbols 515880.SH,159919.SZ,588200.SH")
    click.echo("          etf signals --refresh --symbol 515880.SH")
    click.echo()
    click.echo("  backtest, bt    运行策略回测")
    click.echo("    参数: --strategy (策略名称)")
    click.echo("          --symbol (股票代码)")
    click.echo("          --symbols (多只股票逗号分隔)")
    click.echo("          --pool (股票池/题材名称，多个用逗号分隔)")
    click.echo("          --pool-mode (any 并集 / all 交集)")
    click.echo("          --fast (快线周期)  --slow (慢线周期)")
    click.echo("          --period (通用周期)  --signal_period (信号周期)")
    click.echo("          --oversold (超卖阈值)  --overbought (超买阈值)")
    click.echo("          --devfactor (布林标准差倍数)  --k_period (KDJ周期)")
    click.echo("          --smooth (KDJ平滑参数)")
    click.echo("          --lookback --max_range_pct --volume_multiplier (平台突破参数)")
    click.echo("          --platform_sell_tolerance --stop_loss_pct (平台突破卖出参数)")
    click.echo("          --trend_filter_mode --daily_ema_period --rsi_period --pullback_pct --volume_mult --atr_mult (多周期量价参数)")
    click.echo("          --accel_return_pct --accel_scan_days --platform_lookback (多周期量价加速平台过滤参数)")
    click.echo("          --stalling_buy_filter_days --stalling_volume_mult --stalling_upper_shadow_pct --stalling_exit_ma_period (多周期量价滞涨参数)")
    click.echo(f"    可用策略: {', '.join(_list_strategies())}")
    click.echo("    示例: backtest --strategy sma_cross --symbol 000001.SZ")
    click.echo("          backtest --strategy sma_cross --pool 机器人")
    click.echo("          backtest --strategy sma_cross --pool 机器人,AI --pool-mode all")
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
    click.echo("  trendlines      手动画线工具（不运行策略，不生成交易流水）")
    click.echo("    参数: --symbol (股票代码)  --bars (最近K线数量, 默认250)")
    click.echo("          --pivot-window / --max-lines / --max-levels 为兼容旧命令保留")
    click.echo("    示例: trendlines --symbol 000001.SZ --bars 250")
    click.echo()
    click.echo("  compare, cmp    对比所有策略在单只股票上的表现")
    click.echo("    参数: --symbol (股票代码)")
    click.echo("    示例: compare --symbol 000001.SZ")
    click.echo()
    click.echo("  stats           数据统计分析")
    click.echo("    子命令: analyze / compare / theme / rps / rps-track / pattern / screen / rotation / limit-board / limit-research / limit-strength / support-resistance")
    click.echo("          pool-import / pool-export / pool-from-signals")
    click.echo("    参数: --strategy (analyze), --pool/--start (theme), --pattern, --symbol, --window")
    click.echo("    示例: stats analyze --strategy rsi")
    click.echo("          stats compare")
    click.echo("          stats theme --pool 人形机器人 --start 20260601 --end 20260619")
    click.echo("          stats rps --window 120 --top 50")
    click.echo("          stats pattern --pattern main_rise_wave --pool 机器人")
    click.echo("          stats screen --preset trendline_pullback --pool 机器人,AI --pool-mode any")
    click.echo("          stats limit-board --trade-date 20260703 --save-pools")
    click.echo("          stats limit-research --months 6 --min-limit-count 1")
    click.echo("          stats limit-strength --back-days 10 --min-limit-count 2")
    click.echo("          stats support-resistance --symbol 688981 --name 中芯国际 --start 20240101 --end 20260717")
    click.echo("          stats radar --top 300")
    click.echo()
    click.echo("  dashboard       生成项目汇总导航面板")
    click.echo("    参数: --output (输出 HTML 路径，默认 output/reports/dashboard.html)")
    click.echo("    示例: dashboard")
    click.echo()
    click.echo("  sector-flow     行业板块资金流监控/历史回放")
    click.echo("    子命令: collect / report / watch")
    click.echo("    参数: --output (报告路径), --date (回放日期 YYYY-MM-DD), --collect-now, --once")
    click.echo("    示例: sector-flow report")
    click.echo("          sector-flow watch --once")
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
    click.secho("  多周期量价趋势常用命令（阶段1日线版）:", fg="yellow", bold=True)
    click.echo("    1) 单标的验证:")
    click.echo("       backtest --strategy multi_timeframe_volume_trend --symbol 000001.SZ --trend_filter_mode weekly")
    click.echo("    2) 扫描最近买点:")
    click.echo("       scan --strategy multi_timeframe_volume_trend --days 10")
    click.echo("    3) 保守参数示例:")
    click.echo("       backtest --strategy multi_timeframe_volume_trend --symbol 000001.SZ --pullback_pct 0.03 --volume_mult 1.8 --min_volume_confirmations 3")
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
    failed_file = kwargs.get("failed_file") or kwargs.get("failed-file") or ""
    if isinstance(failed_file, bool):
        failed_file = ""

    run_download(config, symbol, start, end, force, failed_file or None)


def _cmd_stock_basic(config: dict, **kwargs):
    list_status = kwargs.get("list_status", "L")
    if isinstance(list_status, bool):
        list_status = "L"
    force = bool(kwargs.get("force", False))
    run_stock_basic(config, str(list_status), force)


def _cmd_daily_basic(config: dict, **kwargs):
    start = kwargs.get("start", default_start())
    end = kwargs.get("end", today_str())
    force = bool(kwargs.get("force", False))
    run_daily_basic(config, start, end, force)


def _cmd_data_audit(config: dict, **kwargs):
    output = kwargs.get("output")
    if isinstance(output, bool):
        output = None
    run_data_audit(config, deep=bool(kwargs.get("deep", False)), output=output)


def _cmd_index(config: dict, **kwargs):
    sub = kwargs.get("sub") or "overview"
    all_indexes = bool(kwargs.get("all", False))
    symbol = kwargs.get("symbol")
    if isinstance(symbol, bool):
        symbol = None
    elif symbol:
        symbol = symbol.strip().upper()
    start = kwargs.get("start", default_start())
    end = kwargs.get("end", today_str())
    force = bool(kwargs.get("force", False))
    include_chinext_index = bool(kwargs.get("include_chinext_index", False))
    output = kwargs.get("output")
    if isinstance(output, bool):
        output = None

    if sub == "download":
        run_index_download(config, symbol, all_indexes, start, end, force)
        return
    if sub == "report":
        run_index_report(config, symbol, all_indexes, output)
        return
    if sub == "overview":
        run_index_overview(config, symbol, all_indexes, start, end, force, output)
        return
    if sub == "ths":
        run_index_ths(
            config,
            start,
            end,
            force,
            bool(kwargs.get("refresh_list", kwargs.get("refresh-list", False))),
            not bool(kwargs.get("skip_industries", kwargs.get("skip-industries", False))),
            not bool(kwargs.get("skip_styles", kwargs.get("skip-styles", False))),
            bool(kwargs.get("include_concepts", kwargs.get("include-concepts", False))),
            bool(kwargs.get("skip_failures", kwargs.get("skip-failures", False))),
        )
        return
    if sub == "market":
        run_index_market(config, start, end, force, output)
        return
    if sub == "members":
        run_index_members(config, symbol, all_indexes, start, end, force, include_chinext_index)
        return
    if sub in {"forecast", "structure"}:
        horizon = int(kwargs.get("horizon", 5) or 5)
        model = str(kwargs.get("model", "rule_v1") or "rule_v1")
        run_index_forecast(config, symbol, horizon, start, end, force, output, model)
        return
    if sub in {"forecast-diagnose", "forecast_diagnose", "diagnose"}:
        horizon = int(kwargs.get("horizon", 5) or 5)
        label_mode = str(kwargs.get("label_mode", kwargs.get("label-mode", "legacy")) or "legacy")
        run_index_forecast_diagnose(config, symbol, horizon, start, end, force, output, label_mode)
        return
    if sub in {"llm-summary", "llm_summary", "summary"}:
        horizon = int(kwargs.get("horizon", 5) or 5)
        model = str(kwargs.get("model", "rule_v1") or "rule_v1")
        run_index_llm_summary(
            config,
            symbol=symbol,
            horizon=horizon,
            start=start,
            end=end,
            force=force,
            model=model,
            refresh=bool(kwargs.get("refresh", False)),
            no_api=bool(kwargs.get("no_api", kwargs.get("no-api", False))),
            skip_if_no_key=bool(kwargs.get("skip_if_no_key", kwargs.get("skip-if-no-key", False))),
        )
        return
    if sub not in {"download", "report", "overview", "ths", "market", "members", "forecast", "structure", "forecast-diagnose", "forecast_diagnose", "diagnose", "llm-summary", "llm_summary", "summary"}:
        click.secho("  用法: index download|report|overview|ths|market|members|forecast|structure|forecast-diagnose|llm-summary --symbol 000001.SH 或 --all", fg="yellow")


def _cmd_backtest(config: dict, **kwargs):
    from cli.backtest_cli import run_backtest_workflow

    run_backtest_workflow(
        config,
        kwargs.get("strategy", "sma_cross"),
        kwargs.get("symbol"),
        kwargs.get("symbols"),
        kwargs.get("pool"),
        kwargs.get("pool_mode", "any"),
        kwargs,
    )


def _cmd_scan(config: dict, **kwargs):
    strategy = kwargs.get("strategy", "sma_cross")
    days = int(kwargs.get("days", 5))

    from cli.backtest_cli import run_scan_buy_signals

    run_scan_buy_signals(config, strategy, days, kwargs)


def _cmd_report(config: dict, **kwargs):
    symbol = kwargs.get("symbol", "")
    if isinstance(symbol, bool):
        symbol = ""
    symbol = symbol.strip().upper() or None
    strategy = kwargs.get("strategy")
    if isinstance(strategy, bool):
        strategy = None
    log_file = kwargs.get("log_file")
    if isinstance(log_file, bool):
        log_file = None
    output = kwargs.get("output")
    if isinstance(output, bool):
        output = None

    from cli.backtest_cli import run_report

    run_report(config, symbol, log_file, strategy, output)


def _cmd_compare(config: dict, **kwargs):
    symbol = kwargs.get("symbol", "")
    if isinstance(symbol, bool):
        symbol = ""
    symbol = symbol.strip().upper()
    if not symbol:
        click.secho("  请指定 --symbol。", fg="red")
        return

    from cli.backtest_cli import run_strategy_comparison

    run_strategy_comparison(config, symbol)


def _cmd_trendlines(config: dict, **kwargs):
    symbol = kwargs.get("symbol", "")
    if isinstance(symbol, bool):
        symbol = ""
    symbol = str(symbol).strip().upper()
    if not symbol:
        click.secho("  请指定 --symbol。", fg="red")
        return

    bars = int(kwargs.get("bars", 250) or 250)
    output = kwargs.get("output")
    if isinstance(output, bool):
        output = None
    pivot_window = kwargs.get("pivot_window", kwargs.get("pivot-window"))
    if isinstance(pivot_window, bool):
        pivot_window = None
    max_lines = kwargs.get("max_lines", kwargs.get("max-lines"))
    if isinstance(max_lines, bool):
        max_lines = None
    max_levels = kwargs.get("max_levels", kwargs.get("max-levels"))
    if isinstance(max_levels, bool):
        max_levels = None
    print_json = not bool(kwargs.get("no_print_json", kwargs.get("no-print-json", False)))

    from cli.backtest_cli import run_trendline_analysis

    run_trendline_analysis(
        config,
        symbol=symbol,
        bars=bars,
        output=output,
        pivot_window=int(pivot_window) if pivot_window is not None else None,
        max_lines=int(max_lines) if max_lines is not None else None,
        max_levels=int(max_levels) if max_levels is not None else None,
        print_json=print_json,
    )


def _cmd_stats(config: dict, **kwargs):
    """stats 命令路由：分发到 analyze、compare 或 theme 子命令。"""
    sub = kwargs.get("sub", "")
    if isinstance(sub, bool):
        sub = ""
    sub = sub.strip().lower()

    strategy = kwargs.get("strategy", "")
    if isinstance(strategy, bool):
        strategy = ""

    from analysis.analyzer import compute_stats, _STRATEGY_LABELS
    from cli.stats_cli import (
        build_strategy_analysis,
        build_strategy_comparison,
        run_limit_board,
        run_limit_up_research,
        run_pattern_scan,
        run_screen,
        run_rotation_analysis,
        run_rps_top,
        run_rps_track,
        run_strong_stock_radar,
        run_theme_analysis,
    )
    from data.stock_pool import (
        StockPoolError,
        export_stock_pool,
        import_stock_pool,
        save_pool_from_result_csv,
    )

    if sub == "analyze":
        if not strategy:
            click.secho("  请指定 --strategy。示例: stats analyze --strategy rsi", fg="red")
            return
        s, output_path = build_strategy_analysis(config, strategy)
        display = _STRATEGY_LABELS.get(strategy, strategy)
        click.echo()
        click.secho(f"  {display} — 策略画像 ({s['count']} 只)", fg="green")
        click.echo(f"  平均收益: {s['avg_return']:+.1f}%    中位数: {s['median_return']:+.1f}%")
        click.echo(f"  正收益比例: {s['positive_ratio']:.1f}%    "
                   f"平均夏普: {s['avg_sharpe']:.3f}    平均回撤: {s['avg_max_dd']:.1f}%")
        click.echo(f"  平均胜率: {s['avg_win_rate']:.1f}%    平均交易: {s['avg_trades']} 次")
        click.echo()
        click.secho(f"  报告已生成: {output_path}", fg="green")
    elif sub == "compare":
        data_map, output_path = build_strategy_comparison(config)
        click.echo()
        click.secho(f"  策略横向对比 ({len(data_map)} 个策略)", fg="green")
        for name, df in data_map.items():
            s = compute_stats(df)
            display = _STRATEGY_LABELS.get(name, name)
            click.echo(f"  {display:<10s}  {s['count']:>5d} 只  "
                       f"收益 {s['avg_return']:>+7.1f}%  正向率 {s['positive_ratio']:>5.1f}%")
        click.echo()
        click.secho(f"  报告已生成: {output_path}", fg="green")
    elif sub == "theme":
        pool = kwargs.get("pool", "")
        start = kwargs.get("start", "")
        end = kwargs.get("end", "")
        pool_mode = kwargs.get("pool_mode", "any")
        if isinstance(pool, bool):
            pool = ""
        if isinstance(start, bool):
            start = ""
        if isinstance(end, bool):
            end = ""
        if isinstance(pool_mode, bool):
            pool_mode = "any"
        run_theme_analysis(config, pool=pool, pool_mode=pool_mode, start=start, end=end or None)
    elif sub == "rps":
        window = int(kwargs.get("window", 120) or 120)
        top = int(kwargs.get("top", 50) or 50)
        trade_date = kwargs.get("trade_date") or kwargs.get("trade-date")
        if isinstance(trade_date, bool):
            trade_date = None
        pool = kwargs.get("pool")
        if isinstance(pool, bool):
            pool = None
        pool_mode = kwargs.get("pool_mode", "any")
        if isinstance(pool_mode, bool):
            pool_mode = "any"
        run_rps_top(config, window=window, top=top, trade_date=trade_date, pool=pool, pool_mode=pool_mode)
    elif sub in {"rps-track", "rps_track"}:
        symbol = kwargs.get("symbol", "")
        if isinstance(symbol, bool):
            symbol = ""
        window = int(kwargs.get("window", 120) or 120)
        run_rps_track(config, symbol=str(symbol).upper(), window=window)
    elif sub == "pattern":
        pattern = kwargs.get("pattern", "")
        if isinstance(pattern, bool):
            pattern = ""
        pool = kwargs.get("pool")
        if isinstance(pool, bool):
            pool = None
        pool_mode = kwargs.get("pool_mode", "any")
        if isinstance(pool_mode, bool):
            pool_mode = "any"
        run_pattern_scan(config, pattern=str(pattern), pool=pool, pool_mode=pool_mode)
    elif sub == "screen":
        preset = str(kwargs.get("preset", "trendline_pullback") or "trendline_pullback")
        pool = kwargs.get("pool")
        if isinstance(pool, bool):
            pool = None
        pool_mode = kwargs.get("pool_mode", "any")
        if isinstance(pool_mode, bool):
            pool_mode = "any"
        trade_date = kwargs.get("trade_date", kwargs.get("trade-date"))
        if isinstance(trade_date, bool):
            trade_date = None
        lookback = int(kwargs.get("lookback", 250) or 250)
        touch_days = int(kwargs.get("touch_days", kwargs.get("touch-days", 3)) or 3)
        max_distance_pct = float(kwargs.get("max_distance_pct", kwargs.get("max-distance-pct", 1.5)) or 1.5)
        break_pct = float(kwargs.get("break_pct", kwargs.get("break-pct", 1.0)) or 1.0)
        top = int(kwargs.get("top", 100) or 100)
        pivot_window = int(kwargs.get("pivot_window", kwargs.get("pivot-window", 5)) or 5)
        max_lines = int(kwargs.get("max_lines", kwargs.get("max-lines", 3)) or 3)
        save_pool = bool(kwargs.get("save_pool", kwargs.get("save-pool", False)))
        pool_name = kwargs.get("pool_name", kwargs.get("pool-name"))
        merge_pool = bool(kwargs.get("merge_pool", kwargs.get("merge-pool", False)))
        run_screen(
            config,
            preset=preset,
            pool=pool,
            pool_mode=pool_mode,
            trade_date=trade_date,
            lookback=lookback,
            touch_days=touch_days,
            max_distance_pct=max_distance_pct,
            break_pct=break_pct,
            top=top,
            pivot_window=pivot_window,
            max_lines=max_lines,
            save_pool=save_pool,
            pool_name=None if isinstance(pool_name, bool) else pool_name,
            merge_pool=merge_pool,
        )
    elif sub == "rotation":
        pool = kwargs.get("pool")
        if isinstance(pool, bool):
            pool = None
        pool_mode = kwargs.get("pool_mode", "any")
        if isinstance(pool_mode, bool):
            pool_mode = "any"
        model = str(kwargs.get("model", "momentum") or "momentum")
        start = kwargs.get("start")
        end = kwargs.get("end")
        hold_count = int(kwargs.get("hold_count", kwargs.get("hold-count", 3)) or 3)
        rebalance_days = int(kwargs.get("rebalance_days", kwargs.get("rebalance-days", 5)) or 5)
        momentum_window = int(kwargs.get("momentum_window", kwargs.get("momentum-window", 20)) or 20)
        run_rotation_analysis(
            config,
            pool=pool,
            pool_mode=pool_mode,
            model=model,
            start=None if isinstance(start, bool) else start,
            end=None if isinstance(end, bool) else end,
            hold_count=hold_count,
            rebalance_days=rebalance_days,
            momentum_window=momentum_window,
        )
    elif sub in {"limit-board", "limit_board"}:
        trade_date = kwargs.get("trade_date", kwargs.get("trade-date", ""))
        if isinstance(trade_date, bool):
            trade_date = ""
        save_pools = bool(kwargs.get("save_pools", kwargs.get("save-pools", False)))
        pool_prefix = kwargs.get("pool_prefix", kwargs.get("pool-prefix", "涨跌停"))
        if isinstance(pool_prefix, bool):
            pool_prefix = "涨跌停"
        run_limit_board(config, trade_date=str(trade_date), save_pools=save_pools, pool_prefix=str(pool_prefix))
    elif sub in {"limit-research", "limit_research"}:
        start = kwargs.get("start")
        end = kwargs.get("end")
        months = int(kwargs.get("months", 6) or 6)
        min_limit_count = int(kwargs.get("min_limit_count", kwargs.get("min-limit-count", 1)) or 1)
        save_pools = not bool(kwargs.get("no_save_pools", kwargs.get("no-save-pools", False)))
        pool_prefix = kwargs.get("pool_prefix", kwargs.get("pool-prefix", "半年涨停"))
        fundamental_top = int(kwargs.get("fundamental_top", kwargs.get("fundamental-top", 80)) or 80)
        if isinstance(pool_prefix, bool):
            pool_prefix = "半年涨停"
        run_limit_up_research(
            config,
            start=None if isinstance(start, bool) else start,
            end=None if isinstance(end, bool) else end,
            months=months,
            min_limit_count=min_limit_count,
            save_pools=save_pools,
            pool_prefix=str(pool_prefix),
            fundamental_top=fundamental_top,
        )
    elif sub in {"limit-strength", "limit_strength"}:
        data_path = kwargs.get("data_path", kwargs.get("data-path"))
        output_dir = kwargs.get("output_dir", kwargs.get("output-dir"))
        back_days = kwargs.get("back_days", kwargs.get("back-days"))
        min_limit_count = kwargs.get("min_limit_count", kwargs.get("min-limit-count"))
        run_limit_strength(
            config,
            data_path=None if isinstance(data_path, bool) else data_path,
            back_days=None if back_days is None or isinstance(back_days, bool) else int(back_days),
            min_limit_count=None if min_limit_count is None or isinstance(min_limit_count, bool) else int(min_limit_count),
            output_dir=None if isinstance(output_dir, bool) else output_dir,
        )
    elif sub in {"support-resistance", "support_resistance"}:
        symbol = kwargs.get("symbol")
        stock_name = kwargs.get("name", kwargs.get("stock_name", kwargs.get("stock-name", "")))
        start = kwargs.get("start")
        end = kwargs.get("end")
        if any(value is None or isinstance(value, bool) for value in (symbol, start, end)):
            click.secho(
                "  用法: stats support-resistance --symbol 688981 --name 中芯国际 --start 20240101 --end 20260717",
                fg="red",
            )
            return
        run_support_resistance(
            config,
            symbol=str(symbol),
            stock_name="" if isinstance(stock_name, bool) else str(stock_name),
            start=str(start),
            end=str(end),
        )
    elif sub == "radar":
        trade_date = kwargs.get("trade_date", kwargs.get("trade-date"))
        if isinstance(trade_date, bool):
            trade_date = None
        top = kwargs.get("top")
        if isinstance(top, bool):
            top = None
        no_report = bool(kwargs.get("no_report", kwargs.get("no-report", False)))
        no_evaluate = bool(kwargs.get("no_evaluate", kwargs.get("no-evaluate", False)))
        run_strong_stock_radar(
            config,
            trade_date=None if trade_date is None else str(trade_date),
            top=int(top) if top is not None else None,
            write_report=not no_report,
            evaluate=not no_evaluate,
        )
    elif sub in {"pool-import", "pool_import"}:
        input_path = kwargs.get("input") or kwargs.get("input_path")
        name = kwargs.get("name") or kwargs.get("pool_name")
        source_format = str(kwargs.get("format", kwargs.get("source_format", "csv")) or "csv")
        source_pool = kwargs.get("source_pool", kwargs.get("source-pool"))
        merge = bool(kwargs.get("merge", False))
        if not input_path or isinstance(input_path, bool) or not name or isinstance(name, bool):
            click.secho("  用法: stats pool-import --input 文件 --name 股票池名 --format csv|qtyx|blk", fg="red")
            return
        try:
            path = import_stock_pool(config, input_path, name, source_format=source_format, source_pool=None if isinstance(source_pool, bool) else source_pool, merge=merge)
        except StockPoolError as e:
            click.secho(f"  错误: {e}", fg="red")
            return
        click.secho(f"  股票池已导入: {name} -> {path}", fg="green")
    elif sub in {"pool-export", "pool_export"}:
        pool = kwargs.get("pool")
        output = kwargs.get("output")
        output_format = str(kwargs.get("format", kwargs.get("output_format", "csv")) or "csv")
        if not pool or isinstance(pool, bool) or not output or isinstance(output, bool):
            click.secho("  用法: stats pool-export --pool 股票池 --output 文件 --format csv|blk", fg="red")
            return
        try:
            path = export_stock_pool(config, pool, output, output_format=output_format)
        except StockPoolError as e:
            click.secho(f"  错误: {e}", fg="red")
            return
        click.secho(f"  股票池已导出: {pool} -> {path}", fg="green")
    elif sub in {"pool-from-signals", "pool_from_signals"}:
        input_path = kwargs.get("input") or kwargs.get("input_path")
        name = kwargs.get("name") or kwargs.get("pool_name")
        description = kwargs.get("description", "")
        merge = bool(kwargs.get("merge", False))
        if not input_path or isinstance(input_path, bool) or not name or isinstance(name, bool):
            click.secho("  用法: stats pool-from-signals --input CSV --name 股票池名", fg="red")
            return
        try:
            path = save_pool_from_result_csv(config, input_path, name, description="" if isinstance(description, bool) else description, merge=merge)
        except StockPoolError as e:
            click.secho(f"  错误: {e}", fg="red")
            return
        click.secho(f"  扫描结果已写入股票池: {name} -> {path}", fg="green")
    else:
        click.secho(
            f'  未知子命令: "{sub}"。可用: analyze, compare, theme, rps, rps-track, pattern, screen, rotation, limit-board, limit-research, limit-strength, support-resistance, radar。'
            "示例: stats rps --window 120 --top 50",
            fg="red",
        )


def _cmd_dashboard(config: dict, **kwargs):
    output = kwargs.get("output")
    if isinstance(output, bool):
        output = None
    run_dashboard(config, output)


def _cmd_etf(config: dict, **kwargs):
    sub = str(kwargs.get("sub") or "report").strip().lower()
    if sub != "report":
        click.secho("  用法: etf report --symbols 515880.SH,159919.SZ --start 20240101", fg="yellow")
        return
    output = kwargs.get("output")
    if isinstance(output, bool):
        output = None
    symbols = kwargs.get("symbols")
    if isinstance(symbols, bool):
        symbols = None
    start = kwargs.get("start")
    if isinstance(start, bool):
        start = None
    end = kwargs.get("end")
    if isinstance(end, bool):
        end = None
    run_etf_report(
        config,
        symbols=symbols,
        start=start,
        end=end,
        force=bool(kwargs.get("force", False)),
        output=output,
    )


def _cmd_sector_flow(config: dict, **kwargs):
    sub = str(kwargs.get("sub") or "report").strip().lower()
    output = kwargs.get("output")
    if isinstance(output, bool):
        output = None
    if sub == "collect":
        run_sector_money_flow_collect(config)
    elif sub == "report":
        trade_date = kwargs.get("date") or kwargs.get("trade_date")
        if isinstance(trade_date, bool):
            trade_date = None
        run_sector_money_flow_report(
            config,
            output,
            trade_date=trade_date,
            collect_now=bool(kwargs.get("collect_now", False)),
        )
    elif sub == "watch":
        run_sector_money_flow_watch(config, output, once=bool(kwargs.get("once", False)))
    else:
        click.secho("  用法: sector-flow collect | report --date YYYY-MM-DD | watch --once", fg="yellow")


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


def _dispatch_command(config: dict, parts: list[str]) -> bool:
    """Dispatch one parsed REPL command. Return False when the caller should exit."""
    if not parts:
        return True

    cmd = parts[0].lower()
    args = _parse_args(parts[1:])

    if cmd in ("exit", "quit", "q"):
        return False
    if cmd == "help":
        _print_help()
    elif cmd == "list":
        _cmd_list(config)
    elif cmd in ("download", "dl"):
        _cmd_download(config, **args)
    elif cmd in ("stock-basic", "stock_basic"):
        _cmd_stock_basic(config, **args)
    elif cmd in ("daily-basic", "daily_basic"):
        _cmd_daily_basic(config, **args)
    elif cmd in ("data-audit", "data_audit"):
        _cmd_data_audit(config, **args)
    elif cmd == "index":
        sub = parts[1] if len(parts) > 1 else "overview"
        sub_args = _parse_args(parts[2:]) if len(parts) > 2 else {}
        sub_args["sub"] = sub
        _cmd_index(config, **sub_args)
    elif cmd in ("backtest", "bt"):
        _cmd_backtest(config, **args)
    elif cmd == "scan":
        _cmd_scan(config, **args)
    elif cmd in ("report", "rp"):
        _cmd_report(config, **args)
    elif cmd in ("trendlines", "lines"):
        _cmd_trendlines(config, **args)
    elif cmd in ("compare", "cmp"):
        _cmd_compare(config, **args)
    elif cmd == "stats":
        sub = parts[1] if len(parts) > 1 else ""
        sub_args = _parse_args(parts[2:]) if len(parts) > 2 else {}
        sub_args["sub"] = sub
        _cmd_stats(config, **sub_args)
    elif cmd == "dashboard":
        _cmd_dashboard(config, **args)
    elif cmd == "etf":
        sub = parts[1] if len(parts) > 1 else "report"
        sub_args = _parse_args(parts[2:]) if len(parts) > 2 else {}
        sub_args["sub"] = sub
        _cmd_etf(config, **sub_args)
    elif cmd in ("sector-flow", "sector_flow"):
        sub = parts[1] if len(parts) > 1 else "report"
        sub_args = _parse_args(parts[2:]) if len(parts) > 2 else {}
        sub_args["sub"] = sub
        _cmd_sector_flow(config, **sub_args)
    elif cmd == "run":
        if len(parts) >= 3 and parts[1] in {"--file", "-f"}:
            _cmd_run(config, file=parts[2], commands="")
        else:
            _cmd_run(config, commands=" ".join(parts[1:]), file="")
    else:
        raise ValueError(f'未知命令: "{cmd}"')
    return True


def _execute_pipeline(config: dict, commands_text: str) -> bool:
    """按顺序执行多条命令（分号或换行分隔）。

    遇到错误立即停止，可通过 ! 前缀忽略某条命令的失败（类似 make）。
    返回值供非交互入口传播失败退出码；交互式 REPL 仍可自行决定是否继续。
    """
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
        return True

    succeeded = True
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
                succeeded = False
                break
            continue

        if not parts:
            continue

        click.echo()
        click.secho(f"── [{line_no}/{len(lines)}] $ {command_line}", fg="cyan")

        try:
            if not _dispatch_command(config, parts):
                click.secho(f"  流水线在第 {line_no} 条终止（exit）。", fg="yellow")
                break
        except KeyboardInterrupt:
            click.echo()
            click.secho("  流水线被用户中断。", fg="yellow")
            succeeded = False
            break
        except Exception as e:
            click.secho(f"  错误: {e}", fg="red")
            if not ignore_error:
                click.secho(f"  流水线在第 {line_no} 条中止。", fg="red")
                succeeded = False
                break

    click.echo()
    if succeeded:
        click.secho("  流水线执行完毕。", fg="green")
    else:
        click.secho("  流水线执行失败。", fg="red")
    return succeeded


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

        try:
            if not _dispatch_command(config, parts):
                break
        except KeyboardInterrupt:
            click.echo()
            click.secho("  操作已取消", fg="yellow")
        except Exception as e:
            click.secho(f"  错误: {e}", fg="red")

    click.secho("  再见!", fg="cyan")
