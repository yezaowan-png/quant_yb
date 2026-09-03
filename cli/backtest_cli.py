"""回测命令组: run / scan / report"""

import json
import os
import time

# ---- 必须在 import numpy/pandas 之前设置，防止 ProcessPoolExecutor
#      spawn 的子进程里 OpenBLAS 多线程耗尽内存 ----
for _key in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS",
             "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_key, "1")

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import click
import pandas as pd

from cli.common import find_trade_logs as _find_trade_logs
from cli.common import list_cached_symbols as _list_cached_symbols
from cli.common import list_strategies as _list_strategies
from cli.common import load_cache_df as _load_cache_df
from cli.common import load_config as _load_config
from engine.runner import BacktestRunner, load_strategy_class
from strategy.base import normalize_strategy_params
from data.stock_pool import StockPoolError, resolve_pool_symbols
from visual.report import generate_report


def _build_strategy_params(strategy_cls, symbol: str, extra: dict) -> dict:
    """Build params dict from the selected strategy's declared schema."""
    params, ignored = normalize_strategy_params(strategy_cls, extra, symbol)
    if ignored:
        click.echo(f"提示: 当前策略不使用这些参数，已忽略: {', '.join(ignored)}")
    return params


# ============================================================
#  并行报告生成 worker
# ============================================================

def _report_worker(task: dict) -> Optional[dict]:
    """线程级报告生成 worker：加载数据 → 生成 HTML → 返回状态"""

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
        strategy_params = _load_report_strategy_params(log_path)
        generate_report(
            df,
            trades,
            sym,
            strat,
            out_path,
            equity_df,
            strategy_params,
            task.get("trendline_config") or {},
            technical_structure_config=task.get("technical_structure_config") or {},
            adjustment=task.get("adjustment") or "qfq",
        )

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
         "cache_dir": cache_dir, "trades_dir": trades_dir, "reports_dir": reports_dir,
         "trendline_config": config.get("trendlines", {}),
         "technical_structure_config": {
             **(config.get("technical_structure", {}) or {}),
             "cache_dir": str(Path(config.get("output", {}).get("statistics_dir", "output/statistics"))),
         },
         "adjustment": str(config.get("data", {}).get("stock_adj") or "none")}
        for sym, strat, lp in pairs
    ]

    click.echo(f"  并行生成报告 (线程数: {workers}, 共 {len(pairs)} 个)")

    success = 0
    failed = 0
    t0 = time.monotonic()
    completed = 0
    total = len(pairs)

    executor = ThreadPoolExecutor(max_workers=workers)

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
@click.option("--pool", default=None, help="股票池/题材名称，多个用逗号分隔，如 机器人,AI")
@click.option("--pool-mode", default="any", type=click.Choice(["any", "all"]), help="多个股票池的合并方式: any=并集, all=交集")
@click.option("--fast", default=None, type=int, help="快线/短周期参数 (sma_cross/macd_cross)")
@click.option("--slow", default=None, type=int, help="慢线/长周期参数 (sma_cross/macd_cross)")
@click.option("--period", default=None, type=int, help="通用周期参数 (single_ma/rsi/bollinger)")
@click.option("--signal-period", default=None, type=int, help="信号周期 (macd_cross)")
@click.option("--oversold", default=None, type=int, help="超卖阈值 (rsi/kdj)")
@click.option("--overbought", default=None, type=int, help="超买阈值 (rsi/kdj)")
@click.option("--devfactor", default=None, type=float, help="标准差倍数 (bollinger)")
@click.option("--k-period", default=None, type=int, help="KDJ K线周期")
@click.option("--smooth", default=None, type=int, help="KDJ 平滑参数")
@click.option("--lookback", default=None, type=int, help="平台突破回看周期 (volume_platform_breakout)")
@click.option("--max-range-pct", default=None, type=float, help="平台最大振幅 (volume_platform_breakout)")
@click.option("--touch-tolerance", default=None, type=float, help="平台上下沿触碰容忍度")
@click.option("--min-upper-touches", default=None, type=int, help="平台上沿最少触碰次数")
@click.option("--min-lower-touches", default=None, type=int, help="平台下沿最少触碰次数")
@click.option("--breakout-pct", default=None, type=float, help="突破确认幅度")
@click.option("--volume-period", default=None, type=int, help="均量周期")
@click.option("--volume-multiplier", default=None, type=float, help="放量倍数")
@click.option("--ma-slope-days", default=None, type=int, help="MA20 向上确认天数")
@click.option("--platform-sell-tolerance", default=None, type=float, help="跌破平台上沿卖出容忍度")
@click.option("--stop-loss-pct", default=None, type=float, help="买入价止损比例")
@click.option("--trend-filter-mode", default=None, type=click.Choice(["weekly", "daily_proxy"]), help="趋势过滤模式")
@click.option("--weekly-fast-ema", default=None, type=int, help="周线代理快 EMA 周期")
@click.option("--weekly-slow-ema", default=None, type=int, help="周线代理慢 EMA 周期")
@click.option("--weekly-macd-fast", default=None, type=int, help="周线代理 MACD 快线周期")
@click.option("--weekly-macd-slow", default=None, type=int, help="周线代理 MACD 慢线周期")
@click.option("--weekly-macd-signal", default=None, type=int, help="周线代理 MACD 信号周期")
@click.option("--daily-ema-period", default=None, type=int, help="日线回调 EMA 周期")
@click.option("--rsi-period", default=None, type=int, help="多周期量价 RSI 周期")
@click.option("--pullback-lookback", default=None, type=int, help="回撤高点回看窗口")
@click.option("--pullback-pct", default=None, type=float, help="从历史高点回撤比例")
@click.option("--pullback-rsi", default=None, type=float, help="回调 RSI 阈值")
@click.option("--pullback-valid-days", default=None, type=int, help="回调信号有效交易日数")
@click.option("--breakout-lookback", default=None, type=int, help="突破高点回看窗口")
@click.option("--vol-ma-period", default=None, type=int, help="均量周期")
@click.option("--volume-mult", default=None, type=float, help="相对成交量倍数")
@click.option("--vpt-ma-period", default=None, type=int, help="VPT 均线周期")
@click.option("--obv-ma-period", default=None, type=int, help="OBV 均线周期")
@click.option("--min-volume-confirmations", default=None, type=int, help="最少量价确认数量")
@click.option("--atr-period", default=None, type=int, help="ATR 周期")
@click.option("--atr-mult", default=None, type=float, help="初始止损 ATR 倍数")
@click.option("--trail-atr-mult", default=None, type=float, help="移动止损 ATR 倍数")
@click.option("--trend-exit-confirm-days", default=None, type=int, help="趋势失效确认天数")
@click.option("--use-post-accel-platform-filter/--no-post-accel-platform-filter", default=None, help="是否过滤加速上涨后的平台震荡买入")
@click.option("--accel-lookback", default=None, type=int, help="加速上涨累计涨幅窗口")
@click.option("--accel-scan-days", default=None, type=int, help="向前扫描加速上涨的交易日数")
@click.option("--accel-return-pct", default=None, type=float, help="加速上涨累计涨幅阈值")
@click.option("--post-accel-pullback-pct", default=None, type=float, help="加速后回落确认比例")
@click.option("--platform-lookback", default=None, type=int, help="加速后平台观察窗口")
@click.option("--platform-max-range-pct", default=None, type=float, help="平台最大振幅")
@click.option("--platform-ma-slope-pct", default=None, type=float, help="平台均线走平阈值")
@click.option("--platform-breakout-pct", default=None, type=float, help="解除平台过滤的突破幅度")
@click.option("--platform-breakout-volume-mult", default=None, type=float, help="解除平台过滤的放量倍数")
@click.option("--use-stalling-buy-filter/--no-stalling-buy-filter", default=None, help="是否过滤近 N 日放量滞涨后的买入")
@click.option("--stalling-buy-filter-days", default=None, type=int, help="买入前放量滞涨过滤交易日数")
@click.option("--use-stalling-ma-exit/--no-stalling-ma-exit", default=None, help="是否启用放量滞涨后跌破短均线退出")
@click.option("--stalling-volume-mult", default=None, type=float, help="放量滞涨的相对成交量阈值")
@click.option("--stalling-max-close-gain-pct", default=None, type=float, help="滞涨允许的最大收盘涨幅")
@click.option("--stalling-prev-gain-min-pct", default=None, type=float, help="冲高回落滞涨要求的前一日最小涨幅")
@click.option("--stalling-gain-fade-pct", default=None, type=float, help="冲高回落滞涨要求的涨幅衰减")
@click.option("--stalling-upper-shadow-pct", default=None, type=float, help="冲高回落滞涨要求的上影线比例")
@click.option("--stalling-close-position-max", default=None, type=float, help="冲高回落滞涨允许的最高收盘位置")
@click.option("--use-entry-day-stalling-exit/--no-entry-day-stalling-exit", default=None, help="买入成交当天放量滞涨时是否次日开盘退出")
@click.option("--stalling-exit-ma-period", default=None, type=int, help="放量滞涨后的清仓均线周期")
@click.option("--use-take-profit/--no-take-profit", default=None, help="是否启用固定 R 倍数止盈")
@click.option("--take-profit-r", default=None, type=float, help="固定止盈 R 倍数")
@click.option("--use-volume-exhaust-exit/--no-volume-exhaust-exit", default=None, help="是否启用量价衰竭退出")
def run_backtest(
    strategy: str, symbol: Optional[str], symbols: Optional[str],
    pool: Optional[str], pool_mode: str,
    fast: Optional[int], slow: Optional[int], period: Optional[int],
    signal_period: Optional[int], oversold: Optional[int], overbought: Optional[int],
    devfactor: Optional[float], k_period: Optional[int], smooth: Optional[int],
    lookback: Optional[int], max_range_pct: Optional[float],
    touch_tolerance: Optional[float], min_upper_touches: Optional[int],
    min_lower_touches: Optional[int], breakout_pct: Optional[float],
    volume_period: Optional[int], volume_multiplier: Optional[float],
    ma_slope_days: Optional[int], platform_sell_tolerance: Optional[float],
    stop_loss_pct: Optional[float], trend_filter_mode: Optional[str],
    weekly_fast_ema: Optional[int],
    weekly_slow_ema: Optional[int], weekly_macd_fast: Optional[int],
    weekly_macd_slow: Optional[int], weekly_macd_signal: Optional[int],
    daily_ema_period: Optional[int], rsi_period: Optional[int],
    pullback_lookback: Optional[int],
    pullback_pct: Optional[float], pullback_rsi: Optional[float],
    pullback_valid_days: Optional[int], breakout_lookback: Optional[int],
    vol_ma_period: Optional[int], volume_mult: Optional[float],
    vpt_ma_period: Optional[int], obv_ma_period: Optional[int],
    min_volume_confirmations: Optional[int], atr_period: Optional[int],
    atr_mult: Optional[float], trail_atr_mult: Optional[float],
    trend_exit_confirm_days: Optional[int], use_post_accel_platform_filter: Optional[bool],
    accel_lookback: Optional[int], accel_scan_days: Optional[int],
    accel_return_pct: Optional[float], post_accel_pullback_pct: Optional[float],
    platform_lookback: Optional[int], platform_max_range_pct: Optional[float],
    platform_ma_slope_pct: Optional[float], platform_breakout_pct: Optional[float],
    platform_breakout_volume_mult: Optional[float], use_stalling_buy_filter: Optional[bool],
    stalling_buy_filter_days: Optional[int], use_stalling_ma_exit: Optional[bool],
    stalling_volume_mult: Optional[float], stalling_max_close_gain_pct: Optional[float],
    stalling_prev_gain_min_pct: Optional[float], stalling_gain_fade_pct: Optional[float],
    stalling_upper_shadow_pct: Optional[float], stalling_close_position_max: Optional[float],
    use_entry_day_stalling_exit: Optional[bool],
    stalling_exit_ma_period: Optional[int], use_take_profit: Optional[bool],
    take_profit_r: Optional[float], use_volume_exhaust_exit: Optional[bool],
):
    """运行策略回测，导出交易流水 CSV"""
    config = _load_config()
    extra = dict(locals())
    for key in ("config", "strategy", "symbol", "symbols", "pool", "pool_mode"):
        extra.pop(key, None)
    run_backtest_workflow(config, strategy, symbol, symbols, pool, pool_mode, extra)


def run_backtest_workflow(
    config: dict,
    strategy: str,
    symbol: Optional[str] = None,
    symbols: Optional[str] = None,
    pool: Optional[str] = None,
    pool_mode: str = "any",
    extra: Optional[dict] = None,
) -> dict:
    """共享的回测执行入口，供 Click 命令和交互式 shell 复用。"""
    runner = BacktestRunner(config)

    if isinstance(strategy, bool) or not strategy:
        strategy = "sma_cross"
    if isinstance(symbol, bool) or symbol is None:
        symbol = ""
    if isinstance(symbols, bool) or symbols is None:
        symbols = ""
    if isinstance(pool, bool) or pool is None:
        pool = ""
    if isinstance(pool_mode, bool) or not pool_mode:
        pool_mode = "any"

    symbol = str(symbol).strip().upper()
    symbols = str(symbols).strip()
    pool = str(pool).strip()
    pool_mode = str(pool_mode).strip()

    # Resolve symbols
    if symbols:
        sym_list = [s.strip().upper() for s in symbols.split(",")]
    elif symbol:
        sym_list = [symbol]
    elif pool:
        try:
            sym_list = resolve_pool_symbols(config, pool, pool_mode)
        except StockPoolError as e:
            raise click.ClickException(str(e))
        click.echo(f"股票池 {pool} ({pool_mode}) 命中 {len(sym_list)} 只股票。")
    else:
        sym_list = _list_cached_symbols(config)
        if not sym_list:
            raise click.ClickException("本地无缓存数据，请先执行 data download。")
        click.echo(f"未指定股票，将对全部 {len(sym_list)} 只已缓存股票进行批量回测。")
        click.echo(f"建议先指定单只股票测试: python main.py backtest run --strategy rsi --symbol 000001.SZ")

    # Load data
    data_map = {}
    for sym in sym_list:
        try:
            data_map[sym] = _load_cache_df(sym, config)
        except FileNotFoundError as e:
            click.echo(f"跳过 {sym}: {e}", err=True)

    if not data_map:
        raise click.ClickException("没有可用的数据。")

    cls = load_strategy_class(strategy)

    # Strategy params
    raw_params = dict(extra or {})
    for key in ("config", "strategy", "symbol", "symbols", "pool", "pool_mode"):
        raw_params.pop(key, None)
    strategy_params = _build_strategy_params(cls, "", raw_params)

    if len(data_map) == 1:
        # Single stock: full run with CLI output
        sym = list(data_map.keys())[0]
        strategy_params["symbol"] = sym
        df = data_map[sym]
        result = runner.run(df, cls, strategy_params)

        # Export trade log and equity
        trades_dir = Path(config["output"]["trades_dir"])
        trades_dir.mkdir(parents=True, exist_ok=True)
        runner._export_trade_log(result["trade_records"], trades_dir, sym, strategy, strategy_params)
        runner._export_equity(result["equity"], trades_dir, sym, strategy)

        # Print stats
        stats = result["stats"]
        click.echo(f"\n--- 绩效摘要 [{sym}] ---")
        click.echo(f"  总收益率:    {stats['total_return_pct']}%")
        click.echo(f"  年化收益率:  {stats['annual_return_pct']}%")
        click.echo(f"  年化波动率:  {stats['annual_volatility_pct']}%")
        if "excess_return_pct" in stats:
            click.echo(f"  超额收益率:  {stats['excess_return_pct']}%")
            click.echo(f"  信息比率:    {stats['information_ratio']}")
        click.echo(f"  夏普比率:    {stats['sharpe_ratio']}")
        click.echo(f"  最大回撤:    {stats['max_drawdown_pct']}%")
        click.echo(f"  交易次数:    {stats['total_trades']}")
        click.echo(f"  胜率:        {stats['win_rate_pct']}%")
        click.echo(f"  最终资金:    {stats['final_value']:,.2f}")
        return {"symbols": [sym], "stats": stats, "strategy_params": strategy_params}
    else:
        # Batch mode (includes buy signal scanning)
        runner.run_batch(data_map, strategy, strategy_params)
        return {"symbols": list(data_map.keys()), "strategy_params": strategy_params}


def run_scan_buy_signals(
    config: dict,
    strategy: str,
    days: int = 5,
    extra: Optional[dict] = None,
) -> list[dict]:
    """Scan cached stocks for recent buy signals using one shared code path."""
    sym_list = _list_cached_symbols(config)
    if not sym_list:
        raise click.ClickException("本地无缓存数据，请先执行 data download。")

    data_map = {}
    for sym in sym_list:
        try:
            data_map[sym] = _load_cache_df(sym, config)
        except FileNotFoundError:
            pass

    if not data_map:
        raise click.ClickException("没有可用的数据。")

    runner = BacktestRunner(config)
    cls = load_strategy_class(strategy)
    raw_params = dict(extra or {})
    raw_params["strategy"] = strategy
    raw_params["days"] = days
    strategy_params = _build_strategy_params(cls, "", raw_params)

    click.echo(f"扫描 {len(data_map)} 只股票，回看 {days} 日 ...")
    results = runner.scan_recent_buy_signals(
        data_map, strategy, strategy_params, lookback_days=days
    )

    if results:
        click.echo(f"\n近{days}日存在买点的股票 ({len(results)} 只):")
        for row in results:
            click.echo(
                f"  {row['symbol']:12s}  买点日期: {row['recent_buy_dates']:20s}  "
                f"最新价: {row.get('last_price', '-')}"
            )
    else:
        click.echo(f"\n近{days}日无买点信号。")
    return results


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
@click.option("--lookback", default=None, type=int, help="平台突破回看周期 (volume_platform_breakout)")
@click.option("--max-range-pct", default=None, type=float, help="平台最大振幅 (volume_platform_breakout)")
@click.option("--touch-tolerance", default=None, type=float, help="平台上下沿触碰容忍度")
@click.option("--min-upper-touches", default=None, type=int, help="平台上沿最少触碰次数")
@click.option("--min-lower-touches", default=None, type=int, help="平台下沿最少触碰次数")
@click.option("--breakout-pct", default=None, type=float, help="突破确认幅度")
@click.option("--volume-period", default=None, type=int, help="均量周期")
@click.option("--volume-multiplier", default=None, type=float, help="放量倍数")
@click.option("--ma-slope-days", default=None, type=int, help="MA20 向上确认天数")
@click.option("--platform-sell-tolerance", default=None, type=float, help="跌破平台上沿卖出容忍度")
@click.option("--stop-loss-pct", default=None, type=float, help="买入价止损比例")
@click.option("--trend-filter-mode", default=None, type=click.Choice(["weekly", "daily_proxy"]), help="趋势过滤模式")
@click.option("--weekly-fast-ema", default=None, type=int, help="周线代理快 EMA 周期")
@click.option("--weekly-slow-ema", default=None, type=int, help="周线代理慢 EMA 周期")
@click.option("--weekly-macd-fast", default=None, type=int, help="周线代理 MACD 快线周期")
@click.option("--weekly-macd-slow", default=None, type=int, help="周线代理 MACD 慢线周期")
@click.option("--weekly-macd-signal", default=None, type=int, help="周线代理 MACD 信号周期")
@click.option("--daily-ema-period", default=None, type=int, help="日线回调 EMA 周期")
@click.option("--rsi-period", default=None, type=int, help="多周期量价 RSI 周期")
@click.option("--pullback-lookback", default=None, type=int, help="回撤高点回看窗口")
@click.option("--pullback-pct", default=None, type=float, help="从历史高点回撤比例")
@click.option("--pullback-rsi", default=None, type=float, help="回调 RSI 阈值")
@click.option("--pullback-valid-days", default=None, type=int, help="回调信号有效交易日数")
@click.option("--breakout-lookback", default=None, type=int, help="突破高点回看窗口")
@click.option("--vol-ma-period", default=None, type=int, help="均量周期")
@click.option("--volume-mult", default=None, type=float, help="相对成交量倍数")
@click.option("--vpt-ma-period", default=None, type=int, help="VPT 均线周期")
@click.option("--obv-ma-period", default=None, type=int, help="OBV 均线周期")
@click.option("--min-volume-confirmations", default=None, type=int, help="最少量价确认数量")
@click.option("--atr-period", default=None, type=int, help="ATR 周期")
@click.option("--atr-mult", default=None, type=float, help="初始止损 ATR 倍数")
@click.option("--trail-atr-mult", default=None, type=float, help="移动止损 ATR 倍数")
@click.option("--trend-exit-confirm-days", default=None, type=int, help="趋势失效确认天数")
@click.option("--use-post-accel-platform-filter/--no-post-accel-platform-filter", default=None, help="是否过滤加速上涨后的平台震荡买入")
@click.option("--accel-lookback", default=None, type=int, help="加速上涨累计涨幅窗口")
@click.option("--accel-scan-days", default=None, type=int, help="向前扫描加速上涨的交易日数")
@click.option("--accel-return-pct", default=None, type=float, help="加速上涨累计涨幅阈值")
@click.option("--post-accel-pullback-pct", default=None, type=float, help="加速后回落确认比例")
@click.option("--platform-lookback", default=None, type=int, help="加速后平台观察窗口")
@click.option("--platform-max-range-pct", default=None, type=float, help="平台最大振幅")
@click.option("--platform-ma-slope-pct", default=None, type=float, help="平台均线走平阈值")
@click.option("--platform-breakout-pct", default=None, type=float, help="解除平台过滤的突破幅度")
@click.option("--platform-breakout-volume-mult", default=None, type=float, help="解除平台过滤的放量倍数")
@click.option("--use-stalling-buy-filter/--no-stalling-buy-filter", default=None, help="是否过滤近 N 日放量滞涨后的买入")
@click.option("--stalling-buy-filter-days", default=None, type=int, help="买入前放量滞涨过滤交易日数")
@click.option("--use-stalling-ma-exit/--no-stalling-ma-exit", default=None, help="是否启用放量滞涨后跌破短均线退出")
@click.option("--stalling-volume-mult", default=None, type=float, help="放量滞涨的相对成交量阈值")
@click.option("--stalling-max-close-gain-pct", default=None, type=float, help="滞涨允许的最大收盘涨幅")
@click.option("--stalling-prev-gain-min-pct", default=None, type=float, help="冲高回落滞涨要求的前一日最小涨幅")
@click.option("--stalling-gain-fade-pct", default=None, type=float, help="冲高回落滞涨要求的涨幅衰减")
@click.option("--stalling-upper-shadow-pct", default=None, type=float, help="冲高回落滞涨要求的上影线比例")
@click.option("--stalling-close-position-max", default=None, type=float, help="冲高回落滞涨允许的最高收盘位置")
@click.option("--use-entry-day-stalling-exit/--no-entry-day-stalling-exit", default=None, help="买入成交当天放量滞涨时是否次日开盘退出")
@click.option("--stalling-exit-ma-period", default=None, type=int, help="放量滞涨后的清仓均线周期")
@click.option("--use-take-profit/--no-take-profit", default=None, help="是否启用固定 R 倍数止盈")
@click.option("--take-profit-r", default=None, type=float, help="固定止盈 R 倍数")
@click.option("--use-volume-exhaust-exit/--no-volume-exhaust-exit", default=None, help="是否启用量价衰竭退出")
def scan_buy_signals(
    strategy: str, days: int,
    fast: Optional[int], slow: Optional[int], period: Optional[int],
    signal_period: Optional[int], oversold: Optional[int], overbought: Optional[int],
    devfactor: Optional[float], k_period: Optional[int], smooth: Optional[int],
    lookback: Optional[int], max_range_pct: Optional[float],
    touch_tolerance: Optional[float], min_upper_touches: Optional[int],
    min_lower_touches: Optional[int], breakout_pct: Optional[float],
    volume_period: Optional[int], volume_multiplier: Optional[float],
    ma_slope_days: Optional[int], platform_sell_tolerance: Optional[float],
    stop_loss_pct: Optional[float], trend_filter_mode: Optional[str],
    weekly_fast_ema: Optional[int],
    weekly_slow_ema: Optional[int], weekly_macd_fast: Optional[int],
    weekly_macd_slow: Optional[int], weekly_macd_signal: Optional[int],
    daily_ema_period: Optional[int], rsi_period: Optional[int],
    pullback_lookback: Optional[int],
    pullback_pct: Optional[float], pullback_rsi: Optional[float],
    pullback_valid_days: Optional[int], breakout_lookback: Optional[int],
    vol_ma_period: Optional[int], volume_mult: Optional[float],
    vpt_ma_period: Optional[int], obv_ma_period: Optional[int],
    min_volume_confirmations: Optional[int], atr_period: Optional[int],
    atr_mult: Optional[float], trail_atr_mult: Optional[float],
    trend_exit_confirm_days: Optional[int], use_post_accel_platform_filter: Optional[bool],
    accel_lookback: Optional[int], accel_scan_days: Optional[int],
    accel_return_pct: Optional[float], post_accel_pullback_pct: Optional[float],
    platform_lookback: Optional[int], platform_max_range_pct: Optional[float],
    platform_ma_slope_pct: Optional[float], platform_breakout_pct: Optional[float],
    platform_breakout_volume_mult: Optional[float], use_stalling_buy_filter: Optional[bool],
    stalling_buy_filter_days: Optional[int], use_stalling_ma_exit: Optional[bool],
    stalling_volume_mult: Optional[float], stalling_max_close_gain_pct: Optional[float],
    stalling_prev_gain_min_pct: Optional[float], stalling_gain_fade_pct: Optional[float],
    stalling_upper_shadow_pct: Optional[float], stalling_close_position_max: Optional[float],
    use_entry_day_stalling_exit: Optional[bool],
    stalling_exit_ma_period: Optional[int], use_take_profit: Optional[bool],
    take_profit_r: Optional[float], use_volume_exhaust_exit: Optional[bool],
):
    """扫描近N日存在买点的股票，汇总导出"""
    config = _load_config()
    extra = dict(locals())
    extra.pop("config", None)
    extra.pop("strategy", None)
    extra.pop("days", None)
    run_scan_buy_signals(config, strategy, days, extra)


@backtest_group.command(name="compare")
@click.option("--symbol", required=True, help="股票代码")
def compare_strategies(symbol: str):
    """对比所有策略在单只股票上的表现"""
    config = _load_config()
    run_strategy_comparison(config, symbol)


def run_strategy_comparison(config: dict, symbol: str) -> tuple[list[tuple[str, dict]], Path]:
    """Run all available strategies on one symbol and export comparison CSV."""
    sym = symbol.upper()

    try:
        df = _load_cache_df(sym, config)
    except FileNotFoundError as e:
        raise click.ClickException(str(e)) from e

    runner = BacktestRunner(config)
    strategies = _list_strategies()

    click.echo(f"\n{'='*80}")
    click.echo(f"  策略对比 — {sym}")
    click.echo(f"{'='*80}")
    click.echo(f"{'策略':<16s} {'收益率':>8s} {'夏普':>8s} {'最大回撤':>8s} {'交易数':>6s} {'胜率':>6s} {'最终资金':>10s}")
    click.echo("-" * 64)

    results_list = []
    for strategy_name in strategies:
        params = {"symbol": sym}
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
    return results_list, out_path


def _load_report_strategy_params(log_path: Path) -> dict:
    """Load strategy params saved next to a trade log, if available."""
    params_path = log_path.with_suffix(".params.json")
    if not params_path.exists():
        return {}
    try:
        return json.loads(params_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


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

    strategy_params = _load_report_strategy_params(log_path)
    generate_report(
        df,
        trades,
        symbol,
        strategy,
        out_path,
        equity_data,
        strategy_params,
        config.get("trendlines", {}),
        technical_structure_config={
            **(config.get("technical_structure", {}) or {}),
            "cache_dir": str(Path(config.get("output", {}).get("statistics_dir", "output/statistics"))),
        },
        adjustment=str(config.get("data", {}).get("stock_adj") or "none"),
    )
    return out_path


def run_report(
    config: dict,
    symbol: Optional[str] = None,
    log_file: Optional[str] = None,
    strategy: Optional[str] = None,
    output: Optional[str] = None,
) -> tuple[int, int]:
    """Generate one or more reports from exported trade logs."""
    trades_dir = Path(config["output"]["trades_dir"])
    reports_dir = Path(config["output"]["reports_dir"])
    reports_dir.mkdir(parents=True, exist_ok=True)

    if log_file:
        if not symbol:
            click.echo("错误: 指定 --log-file 时必须同时指定 --symbol", err=True)
            return 0, 1
        strat = strategy or "unknown"
        log_path = Path(log_file)
        if not log_path.exists():
            click.echo(f"错误: 交易流水文件不存在: {log_path}", err=True)
            return 0, 1
        out = _generate_one_report(
            config,
            symbol.upper(),
            strat,
            log_path,
            Path(output) if output else None,
        )
        if out:
            click.echo(f"报告已生成: {out}")
            return 1, 0
        return 0, 1

    sym_filter = symbol.upper() if symbol else None
    pairs = _find_trade_logs(trades_dir, symbol=sym_filter, strategy=strategy)
    if not pairs:
        click.echo("错误: 未找到匹配的交易流水文件，请先执行 backtest run。", err=True)
        return 0, 1

    if len(pairs) == 1:
        sym, strat, log_path = pairs[0]
        out = _generate_one_report(
            config,
            sym,
            strat,
            log_path,
            Path(output) if output else None,
        )
        if out:
            click.echo(f"报告已生成: {out}")
            return 1, 0
        return 0, 1

    return _run_batch_reports(pairs, config)


@backtest_group.command(name="report")
@click.option("--symbol", default=None, help="股票代码。不指定则为所有有交易流水的股票生成报告")
@click.option("--log-file", default=None, help="交易流水 CSV 路径（默认自动查找）")
@click.option("--strategy", default=None, help="策略名称。不指定则匹配所有策略")
@click.option("--output", default=None, help="输出 HTML 路径（批量模式下忽略）")
def report(symbol: Optional[str], log_file: Optional[str], strategy: Optional[str], output: Optional[str]):
    """生成可视化 HTML 报告：K线图 + 买卖点 + 权益曲线 + 回撤"""
    config = _load_config()
    run_report(config, symbol, log_file, strategy, output)


def _trendline_config_with_overrides(
    config: dict,
    pivot_window: Optional[int] = None,
    max_lines: Optional[int] = None,
    max_levels: Optional[int] = None,
) -> dict:
    trendline_config = dict(config.get("trendlines", {}) or {})
    if pivot_window is not None:
        trendline_config["pivot_window"] = int(pivot_window)
    if max_lines is not None:
        trendline_config["max_trend_lines"] = int(max_lines)
    if max_levels is not None:
        trendline_config["support_resistance_max_levels"] = int(max_levels)
    return trendline_config


def run_trendline_analysis(
    config: dict,
    symbol: str,
    bars: int = 0,
    output: Optional[str] = None,
    pivot_window: Optional[int] = None,
    max_lines: Optional[int] = None,
    max_levels: Optional[int] = None,
    print_json: bool = True,
) -> tuple[dict, Path]:
    """Generate the canonical stock K-line page with integrated manual drawing."""
    sym = str(symbol or "").strip().upper()
    if not sym:
        raise click.ClickException("请指定 --symbol。")

    df = _load_cache_df(sym, config)
    if bars and int(bars) > 0:
        df = df.tail(int(bars)).reset_index(drop=True)

    if output:
        out_path = Path(output)
    else:
        reports_dir = Path(config["output"]["reports_dir"])
        reports_dir.mkdir(parents=True, exist_ok=True)
        out_path = reports_dir / "stock_kline" / f"{sym}.html"

    from visual.dashboard import generate_stock_kline_page

    target = generate_stock_kline_page(
        config,
        symbol=sym,
        bars=bars,
        back_href="../dashboard.html",
        back_label="返回 Dashboard",
    )
    if output and Path(output).resolve() != target.resolve():
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
        target = out_path

    latest_row = df.iloc[-1] if not df.empty else {}
    latest = {
        "date": str(latest_row.get("date", ""))[:10],
        "close": float(latest_row.get("close", 0)) if len(df) else None,
    }
    analysis = {"latest": latest, "manual_drawing": True}
    click.echo(f"个股 K 线页已生成: {target}")
    click.echo(
        "画线工具已集成在 stock_kline 页面: 趋势线(两点)、支撑线(单点水平线)、阻力线(单点水平线); "
        f"latest={latest.get('date')} close={latest.get('close')}"
    )
    if print_json:
        click.echo(json.dumps(analysis, ensure_ascii=False, indent=2))
    return analysis, target


@backtest_group.command(name="trendlines")
@click.option("--symbol", required=True, help="股票代码，如 000001.SZ")
@click.option("--bars", default=0, type=int, help="使用最近 N 根 K 线，0 表示使用全部缓存")
@click.option("--pivot-window", default=None, type=int, help="兼容旧命令的灵敏度参数；生产识别使用因果 ATR ZigZag")
@click.option("--max-lines", default=None, type=int, help="最多显示的上升/下降趋势线数量")
@click.option("--max-levels", default=None, type=int, help="最多显示的支撑/压力水平位数量")
@click.option("--output", default=None, help="输出 HTML 路径，默认 output/reports/stock_kline/{symbol}.html")
@click.option("--print-json/--no-print-json", default=True, help="是否打印结构化分析 JSON")
def trendlines(
    symbol: str,
    bars: int,
    pivot_window: Optional[int],
    max_lines: Optional[int],
    max_levels: Optional[int],
    output: Optional[str],
    print_json: bool,
):
    """兼容入口：生成集成手动画线的个股 K 线页。"""
    config = _load_config()
    run_trendline_analysis(
        config,
        symbol=symbol,
        bars=bars,
        output=output,
        pivot_window=pivot_window,
        max_lines=max_lines,
        max_levels=max_levels,
        print_json=print_json,
    )
