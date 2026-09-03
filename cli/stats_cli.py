"""数据统计命令组：策略画像 + 策略对比 + 题材涨跌"""

import json
import os
from datetime import date
from pathlib import Path
from typing import Optional

import click

from cli.common import list_strategies as _list_strategies
from cli.common import load_config as _load_config
from analysis.analyzer import (
    _STRATEGY_LABELS,
    load_summary,
    load_all_summaries,
    compute_stats,
)
from analysis.report import build_analyze_page, build_compare_page
from analysis.theme import save_theme_analysis
from analysis.rps import save_rps_top, save_rps_track
from analysis.patterns import PATTERN_SCANNERS, save_pattern_scan
from analysis.screener import SCREEN_PRESETS, save_screen
from analysis.rotation import save_rotation
from analysis.limit_moves import save_limit_board
from analysis.limit_strength import build_limit_strength
from analysis.limit_up_research import save_limit_up_research
from analysis.limit_up_candidate_pool import (
    build_limit_up_candidate_pool,
    probe_limit_list_permission,
    save_limit_up_candidate_pool,
    select_limit_data_client,
)
from analysis.strong_stock_radar import load_stock_metadata, save_strong_stock_radar
from analysis.custom_concept_pools import ConceptPoolConfigError, validate_custom_concept_pools
from analysis.support_resistance import save_support_resistance_analysis
from analysis.theme_stock_pools import (
    ThemeStockPoolError,
    add_pending_assignment,
    add_manual_core_stock,
    confirm_assignment,
    generate_classification_batches,
    import_classification_result,
    list_pending,
    read_candidates,
    reject_assignment,
    revise_pending_assignment,
    set_assignment_pool_role,
    validate_theme_stock_pools,
)
from data.stock_pool import (
    StockPoolError,
    export_stock_pool,
    import_stock_pool,
    save_pool_from_result_csv,
)


def _fmt_pct(value: object, digits: int = 2) -> str:
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{number:+.{digits}f}%"


def _fmt_plain(value: object, digits: int = 2) -> str:
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{number:.{digits}f}"


def _print_theme_result(result) -> None:
    summary = result.summary
    details = result.details
    click.echo(f"\n{'='*60}")
    click.echo(f"  {summary['pool']} — 题材区间涨跌 ({summary['start']} ~ {summary['end']})")
    click.echo(f"{'='*60}")
    click.echo(f"  股票数:     {summary['stock_count']}")
    click.echo(f"  有效样本:   {summary['valid_count']}  缺失/不足: {summary['missing_count']}")
    click.echo(f"  平均涨跌:   {_fmt_pct(summary['avg_return_pct'])}")
    click.echo(f"  中位涨跌:   {_fmt_pct(summary['median_return_pct'])}")
    click.echo(f"  上涨占比:   {summary['positive_ratio_pct']:.1f}% ({summary['positive_count']}/{summary['valid_count']})")
    click.echo(f"  平均回撤:   {_fmt_pct(summary['avg_max_drawdown_pct'])}")
    click.echo(f"  个股离散度: {_fmt_pct(summary.get('return_std_pct'))}")
    click.echo(f"  平均波动率: {_fmt_pct(summary.get('avg_annualized_volatility_pct'))}")
    click.echo(f"  收益/回撤:  {_fmt_plain(summary.get('avg_return_drawdown_ratio'))}")
    click.echo(f"  平均换手:   {_fmt_plain(summary['avg_turnover_rate'])}")
    click.echo(f"  平均量比:   {_fmt_plain(summary['avg_volume_ratio'])}")
    click.echo(f"  平均市值变化: {_fmt_pct(summary['avg_total_mv_change_pct'])}")
    click.echo(f"  概念指数涨跌: {_fmt_pct(summary.get('concept_return_pct'))}")
    click.echo(f"  概念指数回撤: {_fmt_pct(summary.get('concept_max_drawdown_pct'))}")
    click.echo(f"  概念成交量变化: {_fmt_pct(summary.get('concept_volume_change_pct'))}")
    latest_adv = _fmt_plain(summary.get("concept_latest_advance_ratio_pct"), 1)
    click.echo(f"  最新上涨占比: {latest_adv if latest_adv == '-' else latest_adv + '%'}")
    latest_ma20 = _fmt_plain(summary.get("concept_latest_above_ma20_ratio_pct"), 1)
    latest_ma60 = _fmt_plain(summary.get("concept_latest_above_ma60_ratio_pct"), 1)
    click.echo(
        "  MA20/MA60上方: "
        f"{latest_ma20 if latest_ma20 == '-' else latest_ma20 + '%'} / "
        f"{latest_ma60 if latest_ma60 == '-' else latest_ma60 + '%'}"
    )
    latest_high20 = _fmt_plain(summary.get("concept_latest_new_high_20_ratio_pct"), 1)
    latest_low20 = _fmt_plain(summary.get("concept_latest_new_low_20_ratio_pct"), 1)
    click.echo(
        "  20日新高/新低: "
        f"{latest_high20 if latest_high20 == '-' else latest_high20 + '%'} / "
        f"{latest_low20 if latest_low20 == '-' else latest_low20 + '%'}"
    )

    if summary.get("best_symbol"):
        click.echo(
            f"  最强个股:   {summary['best_symbol']} {summary['best_name']} "
            f"{_fmt_pct(summary['best_return_pct'])}"
        )
        click.echo(
            f"  最弱个股:   {summary['worst_symbol']} {summary['worst_name']} "
            f"{_fmt_pct(summary['worst_return_pct'])}"
        )

    valid = details[details["valid"] == True].head(10)  # noqa: E712
    if len(valid) > 0:
        click.echo("\n  TOP 10:")
        click.echo("  " + "-" * 62)
        for _, row in valid.iterrows():
            click.echo(
                f"  {row['ts_code']:<10s} {str(row['name'])[:8]:<8s} "
                f"{_fmt_pct(row['return_pct']):>9s}  "
                f"回撤 {_fmt_pct(row['max_drawdown_pct']):>9s}  "
                f"{row['start_date']}->{row['end_date']}"
            )

    click.echo(f"\n  摘要已保存: {result.summary_path}")
    click.echo(f"  明细已保存: {result.output_path}")
    click.echo(f"  概念指数:   {result.index_path}")
    click.echo(f"  看板已生成: {result.html_path}")


def run_theme_analysis(config: dict, pool: str, start: str, end: str | None = None, pool_mode: str = "any"):
    if not pool:
        raise click.ClickException("请指定 --pool，例如: stats theme --pool 人形机器人 --start 20260601")
    if not start:
        raise click.ClickException("请指定 --start，例如: stats theme --pool 人形机器人 --start 20260601")
    if not end:
        end = date.today().strftime("%Y%m%d")
    result = save_theme_analysis(config, pool, start, end, pool_mode=pool_mode)
    _print_theme_result(result)
    return result


def run_rps_top(
    config: dict,
    window: int = 120,
    top: int = 50,
    trade_date: str | None = None,
    pool: str | None = None,
    pool_mode: str = "any",
    stock_pages: bool = True,
    stock_bars: int = 0,
):
    result = save_rps_top(config, window=window, top=top, trade_date=trade_date, pool=pool, pool_mode=pool_mode)
    click.echo(f"\nRPS Top {top} 已生成: {result.output_path}")
    click.echo(f"HTML 看板: {result.html_path}")
    if result.rows.empty:
        click.echo("  暂无有效 RPS 数据。")
    else:
        click.echo(f"  截止日期: {result.trade_date}  有效结果: {len(result.rows)}")
        for _, row in result.rows.head(10).iterrows():
            click.echo(
                f"  {int(row['rank']):>2d}. {row['ts_code']:<10s} {str(row.get('name', ''))[:8]:<8s} "
                f"RPS {row['rps']:>6.2f}  {window}日收益 {_fmt_pct(row['return_pct'])}"
            )
        if stock_pages:
            _ensure_stock_trendline_reports(config, result.rows["ts_code"].tolist(), bars=stock_bars)
    return result


def _ensure_stock_trendline_reports(config: dict, symbols: list[object], bars: int = 0) -> None:
    """Generate fresh canonical stock K-line pages for linked static statistics reports."""
    from visual.dashboard import generate_stock_kline_page

    reports_dir = Path(config.get("output", {}).get("reports_dir", "output/reports"))
    cache_dir = Path(config.get("data", {}).get("cache_dir", "data/cache"))
    report_template = Path(__file__).resolve().parent.parent / "visual" / "dashboard.py"
    report_template_mtime = report_template.stat().st_mtime if report_template.exists() else 0
    generated = 0
    skipped = 0
    failed: list[tuple[str, str]] = []
    seen: set[str] = set()

    for raw_symbol in symbols:
        symbol = str(raw_symbol or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        output_path = reports_dir / "stock_kline" / f"{symbol}.html"
        cache_path = cache_dir / f"{symbol}.csv"
        if (
            output_path.exists()
            and (not cache_path.exists() or output_path.stat().st_mtime >= cache_path.stat().st_mtime)
            and output_path.stat().st_mtime >= report_template_mtime
        ):
            skipped += 1
            continue
        try:
            generate_stock_kline_page(
                config,
                symbol=symbol,
                bars=bars,
                back_href="../dashboard.html",
                back_label="返回 Dashboard",
            )
            generated += 1
        except Exception as exc:  # noqa: BLE001 - continue generating other stock pages.
            failed.append((symbol, str(exc)))

    click.echo(f"个股 K 线页: 生成/刷新 {generated}，已是最新 {skipped}，失败 {len(failed)}")
    for symbol, error in failed[:10]:
        click.echo(f"  {symbol}: {error}")


def run_rps_track(config: dict, symbol: str, window: int = 120):
    if not symbol:
        raise click.ClickException("请指定 --symbol")
    result = save_rps_track(config, symbol, window=window)
    click.echo(f"\n{result.symbol} RPS 轨迹已生成: {result.output_path}")
    click.echo(f"HTML 看板: {result.html_path}")
    click.echo(f"  有效交易日: {len(result.rows)}")
    return result


def run_pattern_scan(
    config: dict,
    pattern: str,
    pool: str | None = None,
    pool_mode: str = "any",
):
    result = save_pattern_scan(config, pattern=pattern, pool=pool, pool_mode=pool_mode)
    click.echo(f"\n{pattern} 形态扫描已生成: {result.output_path}")
    click.echo(f"HTML 看板: {result.html_path}")
    click.echo(f"  命中股票: {len(result.rows)}")
    if not result.rows.empty:
        for _, row in result.rows.head(12).iterrows():
            click.echo(
                f"  {row['ts_code']:<10s} {str(row.get('name', ''))[:8]:<8s} "
                f"评分 {row.get('score', '-')!s:>6s}  {row.get('reason', '')}"
            )
    return result


def run_screen(
    config: dict,
    preset: str,
    pool: str | None = None,
    pool_mode: str = "any",
    trade_date: str | None = None,
    lookback: int = 250,
    touch_days: int = 3,
    max_distance_pct: float = 1.5,
    break_pct: float = 1.0,
    top: int = 100,
    pivot_window: int = 5,
    max_lines: int = 3,
    save_pool: bool = False,
    pool_name: str | None = None,
    merge_pool: bool = False,
):
    try:
        result = save_screen(
            config,
            preset=preset,
            pool=pool,
            pool_mode=pool_mode,
            trade_date=trade_date,
            lookback=lookback,
            top=top,
            touch_days=touch_days,
            max_distance_pct=max_distance_pct,
            break_pct=break_pct,
            pivot_window=pivot_window,
            max_lines=max_lines,
            save_pool=save_pool,
            pool_name=pool_name,
            merge_pool=merge_pool,
        )
    except (ValueError, StockPoolError) as e:
        raise click.ClickException(str(e)) from e

    click.echo(f"\n{preset} 选股筛选已生成: {result.output_path}")
    click.echo(f"HTML 看板: {result.html_path}")
    click.echo(f"  命中股票: {len(result.rows)}")
    if result.pool_path:
        click.echo(f"  已写入股票池: {result.pool_path}")
    if not result.rows.empty:
        for _, row in result.rows.head(12).iterrows():
            click.echo(
                f"  {row['ts_code']:<10s} {str(row.get('name', ''))[:8]:<8s} "
                f"评分 {row.get('score', '-')!s:>6s}  "
                f"距线 {row.get('distance_pct', '-')!s:>7s}%  {row.get('reason', '')}"
            )
    return result


def run_rotation_analysis(
    config: dict,
    pool: str | None,
    pool_mode: str,
    model: str,
    start: str | None,
    end: str | None,
    hold_count: int,
    rebalance_days: int,
    momentum_window: int,
):
    result = save_rotation(
        config,
        pool=pool,
        pool_mode=pool_mode,
        model=model,
        start=start,
        end=end,
        hold_count=hold_count,
        rebalance_days=rebalance_days,
        momentum_window=momentum_window,
    )
    s = result.summary
    click.echo(f"\n轮动研究已生成: {result.html_path}")
    click.echo(f"  净值: {result.nav_path}")
    click.echo(f"  持仓: {result.holdings_path}")
    click.echo(f"  总收益: {_fmt_pct(s['total_return_pct'])}  最大回撤: {_fmt_pct(s['max_drawdown_pct'])}  夏普: {s['sharpe_ratio']}")
    return result


def run_limit_board(
    config: dict,
    trade_date: str,
    save_pools: bool = False,
    pool_prefix: str = "涨跌停",
):
    if not trade_date:
        trade_date = date.today().strftime("%Y%m%d")
    result = save_limit_board(config, trade_date=trade_date, save_pools=save_pools, pool_prefix=pool_prefix)
    up_count = int((result.detail.get("limit_type") == "U").sum()) if not result.detail.empty else 0
    down_count = int((result.detail.get("limit_type") == "D").sum()) if not result.detail.empty else 0
    z_count = int((result.detail.get("limit_type") == "Z").sum()) if not result.detail.empty else 0
    click.echo(f"\n{result.trade_date} 涨跌停看板已生成: {result.html_path}")
    click.echo(f"  明细: {result.detail_path}")
    click.echo(f"  行业: {result.industry_path}")
    click.echo(f"  概念: {result.concept_path}")
    click.echo(f"  涨停 {up_count} / 跌停 {down_count} / 炸板 {z_count}")
    if result.pool_path:
        click.echo(f"  已按分类写入股票池: {result.pool_path}")
    return result


def run_limit_up_research(
    config: dict,
    start: str | None,
    end: str | None,
    months: int,
    min_limit_count: int,
    save_pools: bool,
    pool_prefix: str,
    fundamental_top: int,
):
    result = save_limit_up_research(
        config,
        start=start,
        end=end,
        months=months,
        min_limit_count=min_limit_count,
        save_pools=save_pools,
        pool_prefix=pool_prefix,
        fundamental_top=fundamental_top,
    )
    click.echo(f"\n最近涨停研究已生成: {result.report_path}")
    click.echo(f"  区间: {result.start} ~ {result.end}  交易日: {len(result.trade_dates)}")
    click.echo(f"  涨停事件: {len(result.detail)}  股票数: {len(result.stock_summary)}")
    click.echo(f"  明细: {result.detail_path}")
    click.echo(f"  个股汇总: {result.summary_path}")
    click.echo(f"  主题汇总: {result.theme_path}")
    click.echo(f"  基本面快照: {result.fundamentals_path}")
    if result.pool_path:
        click.echo(f"  已写入细分股票池: {result.pool_path}")
    if not result.theme_summary.empty:
        click.echo("\n  TOP 细分主题:")
        for _, row in result.theme_summary.head(10).iterrows():
            click.echo(
                f"  {row['theme']}: {int(row['stock_count'])} 只 / "
                f"{int(row['limit_up_events'])} 次，代表: {row['leaders']}"
            )
    return result


def run_limit_strength(
    config: dict,
    data_path: str | None = None,
    back_days: int | None = None,
    min_limit_count: int | None = None,
    output_dir: str | None = None,
):
    overrides = dict(config)
    raw = dict(overrides.get("limit_strength") or {})
    if data_path:
        raw["data_path"] = data_path
    if back_days is not None:
        raw["back_days"] = back_days
    if min_limit_count is not None:
        raw["min_limit_count"] = min_limit_count
    if output_dir:
        raw["output_dir"] = output_dir
    overrides["limit_strength"] = raw
    result = build_limit_strength(overrides)
    click.echo(f"\n涨停强势股筛选已生成: {result.html_path}")
    click.echo(f"  加载日期: {', '.join(result.loaded_dates[:10]) if result.loaded_dates else '无'}")
    click.echo(f"  涨停记录: {len(result.records)}  候选: {len(result.candidates)}  上榜: {len(result.result)}")
    click.echo(f"  结果: {result.result_path}")
    click.echo(f"  最新: {result.latest_path}")
    click.echo(f"  变化: {result.changes_path}")
    return result


def run_support_resistance(
    config: dict,
    symbol: str,
    stock_name: str,
    start: str,
    end: str,
):
    try:
        result = save_support_resistance_analysis(
            config=config,
            symbol=symbol,
            stock_name=stock_name,
            start_date=start,
            end_date=end,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"\n支撑压力共振分析已生成: {result.report_path}")
    click.echo(f"  股票: {result.stock_name or result.symbol} ({result.symbol})")
    click.echo(f"  区间: {result.start_date} ~ {result.end_date}  日线: {len(result.data)}")
    click.echo(f"  复权: {result.settings.adjust or 'none'}  共振区域: {len(result.resonance_zones)}")
    for line in result.report_lines:
        click.echo(f"  {line}")
    return result


def run_strong_stock_radar(
    config: dict,
    trade_date: str | None = None,
    top: int | None = None,
    write_report: bool = True,
    evaluate: bool = True,
):
    try:
        result = save_strong_stock_radar(
            config,
            trade_date=trade_date,
            top=top,
            write_report=write_report,
            evaluate=evaluate,
        )
    except ValueError as e:
        raise click.ClickException(str(e)) from e
    click.echo(f"\n强势股雷达已生成: {result.trade_date}")
    click.echo(f"  Snapshot: {result.snapshot_path}")
    click.echo(f"  最新全量表: {result.latest_snapshot_path}")
    click.echo(f"  可交易股票池: {result.tradable_universe_path}")
    click.echo(f"  行业强度: {result.industry_path}")
    click.echo(f"  后验审计: {result.evaluation_path}")
    if result.report_path:
        click.echo(f"  HTML 看板: {result.report_path}")
    click.echo(f"  可交易股票: {len(result.tradable_universe)}  行业: {len(result.industry_strength)}")
    if not result.stock_snapshot.empty and "state" in result.stock_snapshot.columns:
        counts = result.stock_snapshot["state"].value_counts()
        summary = " / ".join(f"{state} {int(count)}" for state, count in counts.head(8).items())
        click.echo(f"  state 分布: {summary}")
    return result


def run_limit_up_candidate_pool(config: dict, as_of_date: str | None = None, probe: bool = False):
    """Build official candidates only when all 120 exchange sessions are present."""
    probe_date = "20260703"
    if probe:
        checked = probe_limit_list_permission(config, probe_date)
        click.echo(f"  涨停数据账号: {checked['account']}；Token: {'已配置' if checked['token_from_environment'] or checked['account'] == '默认账号' else '未配置'}")
        click.echo(f"  权限探测: {'成功' if checked['ok'] else '失败'}（{checked['account']}）")
        if not checked["ok"]:
            raise click.ClickException(f"limit_list_d 权限探测失败: {checked['error_type']}")
        return checked
    account_label = "limit专用账号" if os.environ.get("TUSHARE_LIMIT_TOKEN") else "默认账号"
    click.echo(f"  涨停数据账号: {account_label}；Token: 已配置")
    result = build_limit_up_candidate_pool(
        config,
        as_of_date=as_of_date,
        stock_metadata=load_stock_metadata(config),
    )
    if not result.official:
        missing = ", ".join(result.status.get("missing_trade_days", [])[:10])
        raise click.ClickException(
            f"涨停候选池数据不完整，未覆盖正式输出。{'; '.join(result.errors)}"
            + (f" 缺失: {missing}" if missing else "")
        )
    output_dir = Path(config["output"].get("statistics_dir", "output/statistics"))
    paths = save_limit_up_candidate_pool(result, output_dir)
    click.echo(f"\n涨停基础候选池已生成: {paths['candidates_path']}")
    click.echo(f"  状态: {paths['status_path']}")
    click.echo(
        f"  窗口: {result.status['window_start_date']} ~ {result.status['window_end_date']} "
        f"({result.status['loaded_trade_days']}/{result.status['expected_trade_days']} 交易日)"
    )
    click.echo(f"  U {result.status['limit_up_event_count']} / Z {result.status['opened_event_count']} / 候选 {len(result.candidates)}")
    return result, paths


def run_concept_pool_validation(config: dict) -> dict:
    """Validate user-maintained concept pools without calculating the radar."""
    try:
        summary = validate_custom_concept_pools(config, load_stock_metadata(config))
    except ConceptPoolConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"\n自定义概念池校验: {summary['path']}")
    click.echo(f"  启用概念池: {summary['enabled_count']}  历史口径: {summary['history_mode']}")
    for pool in summary['pools']:
        suffix = '（小样本）' if pool['small_sample'] else ''
        click.echo(f"  {pool['name']} [{pool['id']}]: 有效成员 {pool['members']}，无效成员 {len(pool['invalid_members'])}{suffix}")
    for warning in summary['warnings']:
        click.echo(f"  警告: {warning}")
    if not summary['can_run']:
        raise click.ClickException('没有可计算的启用概念池')
    return summary


def build_strategy_analysis(config: dict, strategy: str) -> tuple[dict, Path]:
    """Build one strategy analysis report and return its stats and path."""
    df = load_summary(strategy)
    if df is None or len(df) == 0:
        raise click.ClickException(
            f"策略 '{strategy}' 无回测数据。请先执行 backtest run --strategy {strategy}"
        )
    stats_dir = Path(config["output"].get("statistics_dir", "output/statistics"))
    stats_dir.mkdir(parents=True, exist_ok=True)
    stats = compute_stats(df)
    output_path = stats_dir / f"analysis_{strategy}.html"
    build_analyze_page(strategy, df, output_path)
    return stats, output_path


def build_strategy_comparison(config: dict) -> tuple[dict, Path]:
    """Build the cross-strategy comparison report."""
    data_map = load_all_summaries()
    if len(data_map) < 2:
        raise click.ClickException(
            "需要至少 2 个策略有回测数据才能对比。请先执行 backtest run。"
        )
    stats_dir = Path(config["output"].get("statistics_dir", "output/statistics"))
    stats_dir.mkdir(parents=True, exist_ok=True)
    output_path = stats_dir / "comparison.html"
    build_compare_page(data_map, output_path)
    return data_map, output_path


@click.group(name="stats")
def stats_group():
    """数据分析：策略画像、多策略对比、题材涨跌"""
    pass


@stats_group.command(name="analyze")
@click.option("--strategy", required=True,
              help=f"策略名称。可用: {', '.join(_list_strategies())}")
def analyze_strategy(strategy: str):
    """单策略深度分析 —— 收益分布、风险散点、TOP/BOTTOM 榜单"""
    config = _load_config()
    stats, output_path = build_strategy_analysis(config, strategy)
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

    click.echo(f"\n  报告已生成: {output_path}")


@stats_group.command(name="compare")
def compare_strategies():
    """多策略横向对比 —— 雷达图、箱线图、相关性分析"""
    config = _load_config()
    data_map, output_path = build_strategy_comparison(config)

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

    click.echo(f"\n  报告已生成: {output_path}")


@stats_group.command(name="theme")
@click.option("--pool", required=True, help="题材股票池名称，多个题材用英文逗号分隔")
@click.option("--pool-mode", default="any", type=click.Choice(["any", "all"]),
              show_default=True, help="多个题材时 any=并集，all=交集")
@click.option("--start", required=True, help="开始日期 YYYYMMDD")
@click.option("--end", default=None, help="结束日期 YYYYMMDD，默认今天")
def theme_stats(pool: str, pool_mode: str, start: str, end: Optional[str]):
    """统计题材股票池在指定区间内的涨跌、回撤和热度指标。"""
    config = _load_config()
    run_theme_analysis(config, pool=pool, pool_mode=pool_mode, start=start, end=end)


@stats_group.command(name="rps")
@click.option("--window", default=120, type=int, show_default=True, help="RPS 收益窗口，单位交易日")
@click.option("--top", default=50, type=int, show_default=True, help="输出排名数量")
@click.option("--trade-date", default=None, help="截止交易日 YYYYMMDD，默认最新缓存交易日")
@click.option("--pool", default=None, help="股票池名称，可选")
@click.option("--pool-mode", default="any", type=click.Choice(["any", "all"]), show_default=True)
@click.option("--stock-pages/--no-stock-pages", default=True, show_default=True, help="同步生成 Top N 个股 K 线画线页")
@click.option("--stock-bars", default=0, type=int, show_default=True, help="个股 K 线页使用最近 N 根日 K，0 表示全部缓存")
def rps_top(
    window: int,
    top: int,
    trade_date: Optional[str],
    pool: Optional[str],
    pool_mode: str,
    stock_pages: bool,
    stock_bars: int,
):
    """生成全市场或股票池 RPS Top N。"""
    config = _load_config()
    run_rps_top(
        config,
        window=window,
        top=top,
        trade_date=trade_date,
        pool=pool,
        pool_mode=pool_mode,
        stock_pages=stock_pages,
        stock_bars=stock_bars,
    )


@stats_group.command(name="rps-track")
@click.option("--symbol", required=True, help="股票代码")
@click.option("--window", default=120, type=int, show_default=True, help="RPS 收益窗口，单位交易日")
def rps_track_command(symbol: str, window: int):
    """生成单只股票的历史 RPS 轨迹。"""
    config = _load_config()
    run_rps_track(config, symbol=symbol.upper(), window=window)


@stats_group.command(name="pattern")
@click.option("--pattern", required=True, type=click.Choice(sorted(PATTERN_SCANNERS)), help="形态名称")
@click.option("--pool", default=None, help="股票池名称，可选")
@click.option("--pool-mode", default="any", type=click.Choice(["any", "all"]), show_default=True)
def pattern_scan_command(pattern: str, pool: Optional[str], pool_mode: str):
    """扫描主升浪、底部突破或单针探底形态。"""
    config = _load_config()
    run_pattern_scan(config, pattern=pattern, pool=pool, pool_mode=pool_mode)


@stats_group.command(name="screen")
@click.option("--preset", default="trendline_pullback", type=click.Choice(sorted(SCREEN_PRESETS)),
              show_default=True, help="筛选预设")
@click.option("--pool", default=None, help="股票池名称，可选；多个题材用英文逗号分隔")
@click.option("--pool-mode", default="any", type=click.Choice(["any", "all"]), show_default=True)
@click.option("--trade-date", default=None, help="截止交易日 YYYYMMDD，默认每只股票最新缓存日")
@click.option("--lookback", default=250, type=int, show_default=True, help="每只股票最多使用最近N根K线")
@click.option("--touch-days", default=3, type=int, show_default=True, help="最近N个交易日内贴近趋势线")
@click.option("--max-distance-pct", default=1.5, type=float, show_default=True, help="贴近趋势线的最大距离百分比")
@click.option("--break-pct", default=1.0, type=float, show_default=True, help="允许收盘价跌破趋势线的最大百分比")
@click.option("--top", default=100, type=int, show_default=True, help="最多输出候选数量")
@click.option("--pivot-window", default=5, type=int, show_default=True, help="趋势线 pivot 窗口")
@click.option("--max-lines", default=3, type=int, show_default=True, help="每只股票最多评估的上升趋势线数量")
@click.option("--save-pool/--no-save-pool", default=False, show_default=True, help="是否把筛选结果写入股票池")
@click.option("--pool-name", default=None, help="写入股票池名称，配合 --save-pool 使用")
@click.option("--merge-pool/--replace-pool", default=False, show_default=True, help="写入股票池时是否合并已有成员")
def screen_command(
    preset: str,
    pool: Optional[str],
    pool_mode: str,
    trade_date: Optional[str],
    lookback: int,
    touch_days: int,
    max_distance_pct: float,
    break_pct: float,
    top: int,
    pivot_window: int,
    max_lines: int,
    save_pool: bool,
    pool_name: Optional[str],
    merge_pool: bool,
):
    """通用选股筛选：第一版支持趋势向上后回踩趋势线。"""
    config = _load_config()
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
        pool_name=pool_name,
        merge_pool=merge_pool,
    )


@stats_group.command(name="rotation")
@click.option("--pool", default=None, help="股票池名称，不指定则使用全部缓存股票")
@click.option("--pool-mode", default="any", type=click.Choice(["any", "all"]), show_default=True)
@click.option("--model", default="momentum", type=click.Choice(["momentum", "three_factor"]), show_default=True)
@click.option("--start", default=None, help="开始日期 YYYYMMDD")
@click.option("--end", default=None, help="结束日期 YYYYMMDD")
@click.option("--hold-count", default=3, type=int, show_default=True, help="持仓数量")
@click.option("--rebalance-days", default=5, type=int, show_default=True, help="换仓间隔，单位交易日")
@click.option("--momentum-window", default=20, type=int, show_default=True, help="动量窗口")
def rotation_command(
    pool: Optional[str],
    pool_mode: str,
    model: str,
    start: Optional[str],
    end: Optional[str],
    hold_count: int,
    rebalance_days: int,
    momentum_window: int,
):
    """研究型动量/三因子轮动，不改变 Backtrader 回测口径。"""
    config = _load_config()
    run_rotation_analysis(
        config,
        pool=pool,
        pool_mode=pool_mode,
        model=model,
        start=start,
        end=end,
        hold_count=hold_count,
        rebalance_days=rebalance_days,
        momentum_window=momentum_window,
    )


@stats_group.command(name="limit-board")
@click.option("--trade-date", default=None, help="交易日 YYYYMMDD，默认今天")
@click.option("--save-pools/--no-save-pools", default=False, show_default=True, help="是否把涨停/跌停/行业分类写入股票池")
@click.option("--pool-prefix", default="涨跌停", show_default=True, help="自动生成股票池名称前缀")
def limit_board_command(trade_date: Optional[str], save_pools: bool, pool_prefix: str):
    """生成每日涨跌停看板，并可按行业/涨跌停类型分类写入股票池。"""
    config = _load_config()
    run_limit_board(config, trade_date=trade_date or "", save_pools=save_pools, pool_prefix=pool_prefix)


@stats_group.command(name="limit-research")
@click.option("--start", default=None, help="开始日期 YYYYMMDD；默认最近 --months 个月")
@click.option("--end", default=None, help="结束日期 YYYYMMDD；默认今天并自动回落到最近交易日")
@click.option("--months", default=6, type=int, show_default=True, help="未指定 --start 时回看月份")
@click.option("--min-limit-count", default=1, type=int, show_default=True, help="写入股票池的最小半年涨停次数")
@click.option("--save-pools/--no-save-pools", default=True, show_default=True, help="是否按细分主题写入股票池")
@click.option("--pool-prefix", default="半年涨停", show_default=True, help="自动生成股票池名称前缀")
@click.option("--fundamental-top", default=80, type=int, show_default=True, help="抓取财务指标的高频股票数量")
def limit_research_command(
    start: Optional[str],
    end: Optional[str],
    months: int,
    min_limit_count: int,
    save_pools: bool,
    pool_prefix: str,
    fundamental_top: int,
):
    """抓取最近区间涨停股，按细分主题入池并生成基本面研究文档。"""
    config = _load_config()
    run_limit_up_research(
        config,
        start=start,
        end=end,
        months=months,
        min_limit_count=min_limit_count,
        save_pools=save_pools,
        pool_prefix=pool_prefix,
        fundamental_top=fundamental_top,
    )


@stats_group.command(name="limit-strength")
@click.option("--data-path", default=None, help="本地涨停数据库目录，默认读取 limit_strength.data_path")
@click.option("--back-days", default=None, type=int, help="回看最近 N 个涨停明细文件，默认读取配置")
@click.option("--min-limit-count", default=None, type=int, help="近期最少涨停次数，默认读取配置")
@click.option("--output-dir", default=None, help="输出目录，默认 output.statistics_dir/limit_strength")
def limit_strength_command(
    data_path: Optional[str],
    back_days: Optional[int],
    min_limit_count: Optional[int],
    output_dir: Optional[str],
):
    """基于本地涨停板数据库筛选并评分强势股。"""
    config = _load_config()
    run_limit_strength(
        config,
        data_path=data_path,
        back_days=back_days,
        min_limit_count=min_limit_count,
        output_dir=output_dir,
    )


@stats_group.command(name="support-resistance")
@click.option("--symbol", required=True, help="股票代码，如 688981、sh688981 或 688981.SH")
@click.option("--name", "stock_name", default="", help="股票名称，用于报告标题")
@click.option("--start", required=True, help="开始日期 YYYYMMDD")
@click.option("--end", required=True, help="结束日期 YYYYMMDD")
def support_resistance_command(symbol: str, stock_name: str, start: str, end: str):
    """生成单股均线与斐波那契支撑压力共振报告。"""
    config = _load_config()
    run_support_resistance(
        config,
        symbol=symbol,
        stock_name=stock_name,
        start=start,
        end=end,
    )


@stats_group.command(name="radar")
@click.option("--trade-date", default=None, help="截止交易日 YYYYMMDD，默认最新缓存交易日")
@click.option("--top", default=None, type=int, help="HTML 看板最多展示股票数；不指定则使用 strong_stock_radar.display_top")
@click.option("--report/--no-report", default=True, show_default=True, help="是否生成 HTML 看板")
@click.option("--evaluate/--no-evaluate", default=True, show_default=True, help="是否刷新历史 snapshot 后验审计")
@click.option("--validate-concept-pools", is_flag=True, help="仅校验自定义概念池 YAML，不计算雷达")
def strong_stock_radar_command(
    trade_date: Optional[str],
    top: Optional[int],
    report: bool,
    evaluate: bool,
    validate_concept_pools: bool,
):
    """生成研究型强势股雷达、行业强度和后验审计快照。"""
    config = _load_config()
    if validate_concept_pools:
        run_concept_pool_validation(config)
        return
    run_strong_stock_radar(
        config,
        trade_date=trade_date,
        top=top,
        write_report=report,
        evaluate=evaluate,
    )


@stats_group.command(name="pool-import")
@click.option("--input", "input_path", required=True, help="输入文件路径")
@click.option("--name", "pool_name", required=True, help="写入的股票池名称")
@click.option("--format", "source_format", default="csv", type=click.Choice(["csv", "qtyx", "blk"]), show_default=True)
@click.option("--source-pool", default=None, help="QTYX trade_pool.json 中的池名称")
@click.option("--merge/--replace", default=False, show_default=True, help="是否合并到已有股票池")
def pool_import_command(input_path: str, pool_name: str, source_format: str, source_pool: Optional[str], merge: bool):
    """从 CSV、QTYX 股票池或通达信 blk 导入股票池。"""
    config = _load_config()
    try:
        path = import_stock_pool(config, input_path, pool_name, source_format=source_format, source_pool=source_pool, merge=merge)
    except StockPoolError as e:
        raise click.ClickException(str(e)) from e
    click.echo(f"股票池已导入: {pool_name} -> {path}")


@stats_group.command(name="pool-export")
@click.option("--pool", required=True, help="股票池名称")
@click.option("--output", "output_path", required=True, help="输出文件路径")
@click.option("--format", "output_format", default="csv", type=click.Choice(["csv", "blk"]), show_default=True)
def pool_export_command(pool: str, output_path: str, output_format: str):
    """导出股票池为 CSV 或通达信 blk。"""
    config = _load_config()
    try:
        path = export_stock_pool(config, pool, output_path, output_format=output_format)
    except StockPoolError as e:
        raise click.ClickException(str(e)) from e
    click.echo(f"股票池已导出: {pool} -> {path}")


@stats_group.command(name="pool-from-signals")
@click.option("--input", "input_path", required=True, help="扫描结果 CSV，如 pattern_signals/rps_top/limit_board")
@click.option("--name", "pool_name", required=True, help="写入的股票池名称")
@click.option("--description", default="", help="股票池说明")
@click.option("--merge/--replace", default=False, show_default=True, help="是否合并到已有股票池")
def pool_from_signals_command(input_path: str, pool_name: str, description: str, merge: bool):
    """把扫描结果 CSV 中的股票代码保存为股票池。"""
    config = _load_config()
    try:
        path = save_pool_from_result_csv(config, input_path, pool_name, description=description, merge=merge)
    except StockPoolError as e:
        raise click.ClickException(str(e)) from e
    click.echo(f"扫描结果已写入股票池: {pool_name} -> {path}")


@stats_group.command(name="limit-up-candidates")
@click.option("--as-of-date", default=None, help="候选池截止日 YYYYMMDD；--probe 时为完整历史交易日")
@click.option("--probe", is_flag=True, help="仅对一个交易日执行 limit_list_d 最小权限探测，不回填")
def limit_up_candidates_command(as_of_date: str | None, probe: bool):
    """用完整 120 个真实交易日生成涨停基础候选池。"""
    run_limit_up_candidate_pool(_load_config(), as_of_date, probe)


@stats_group.group(name="theme-pool")
def theme_pool_group():
    """独立主题股票池：ChatGPT 人工交接、导入与确认。"""
    pass


@theme_pool_group.command(name="validate")
@click.option("--pool-file", default="config/theme_stock_pools.json", show_default=True, help="独立主题池 JSON")
def theme_pool_validate_command(pool_file: str):
    """校验独立主题股票池 JSON。"""
    try:
        summary = validate_theme_stock_pools(pool_file)
    except ThemeStockPoolError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(summary, ensure_ascii=False, indent=2))


@theme_pool_group.command(name="batch")
@click.option("--candidates", required=True, help="基础候选池 CSV 或 JSON")
@click.option("--as-of-date", required=True, help="候选池截止日 YYYYMMDD")
@click.option("--output-dir", required=True, help="ChatGPT 待分类批次输出目录")
@click.option("--batch-size", default=25, type=int, show_default=True)
@click.option("--pool-file", default="config/theme_stock_pools.json", show_default=True, help="独立主题池 JSON")
@click.option("--force-symbol", "force_symbols", multiple=True, help="显式重新研究的股票代码，可重复传入")
def theme_pool_batch_command(candidates: str, as_of_date: str, output_dir: str, batch_size: int, pool_file: str, force_symbols: tuple[str, ...]):
    """从基础候选池生成非空 ChatGPT 待分类批次。"""
    try:
        paths = generate_classification_batches(
            read_candidates(candidates), as_of_date, output_dir, pool_file, batch_size, force_symbols
        )
    except ThemeStockPoolError as exc:
        raise click.ClickException(str(exc)) from exc
    if not paths:
        click.echo("无新增待分类股票，未生成空批次。")
        return
    for path in paths:
        click.echo(f"已生成批次: {path}")


@theme_pool_group.command(name="import")
@click.option("--input", "input_path", required=True, help="ChatGPT 返回的分类结果 JSON")
@click.option("--pool-file", default="config/theme_stock_pools.json", show_default=True, help="独立主题池 JSON")
@click.option("--dry-run", is_flag=True, help="仅校验并输出新增/冲突，不写入")
def theme_pool_import_command(input_path: str, pool_file: str, dry_run: bool):
    """导入 ChatGPT 分类建议；默认写入 pending。"""
    try:
        result = import_classification_result(input_path, pool_file, dry_run=dry_run)
    except ThemeStockPoolError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))


@theme_pool_group.command(name="pending")
@click.option("--pool-file", default="config/theme_stock_pools.json", show_default=True, help="独立主题池 JSON")
def theme_pool_pending_command(pool_file: str):
    """查看等待人工确认的股票—主题关系。"""
    try:
        click.echo(json.dumps(list_pending(pool_file), ensure_ascii=False, indent=2))
    except ThemeStockPoolError as exc:
        raise click.ClickException(str(exc)) from exc


@theme_pool_group.command(name="confirm")
@click.option("--symbol", required=True, help="股票代码")
@click.option("--theme-id", required=True)
@click.option("--reason", default=None, help="可选人工修订理由")
@click.option("--pool-role", type=click.Choice(["rs_member", "watch_only"]), default=None, help="确认后的主题池角色")
@click.option("--pool-file", default="config/theme_stock_pools.json", show_default=True, help="独立主题池 JSON")
def theme_pool_confirm_command(symbol: str, theme_id: str, reason: Optional[str], pool_role: str | None, pool_file: str):
    """确认 pending 关系，并启用 manual_locked 保护。"""
    try:
        path, backup = confirm_assignment(symbol, theme_id, pool_file, reason, pool_role)
    except ThemeStockPoolError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"已确认: {symbol} / {theme_id} -> {path}；备份: {backup or '-'}")


@theme_pool_group.command(name="set-role")
@click.option("--symbol", required=True, help="股票代码")
@click.option("--theme-id", required=True)
@click.option("--pool-role", required=True, type=click.Choice(["rs_member", "watch_only"]), help="rs_member 参与主题 RS；watch_only 仅题材观察")
@click.option("--pool-file", default="config/theme_stock_pools.json", show_default=True, help="独立主题池 JSON")
def theme_pool_set_role_command(symbol: str, theme_id: str, pool_role: str, pool_file: str):
    """人工调整已确认关系的主题池角色，并锁定避免自动覆盖。"""
    try:
        path, backup = set_assignment_pool_role(symbol, theme_id, pool_role, pool_file)
    except ThemeStockPoolError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"已调整主题角色: {symbol} / {theme_id} -> {pool_role}；文件: {path}；备份: {backup or '-'}")


@theme_pool_group.command(name="reject")
@click.option("--symbol", required=True, help="股票代码")
@click.option("--theme-id", required=True)
@click.option("--reason", default=None, help="可选人工拒绝理由")
@click.option("--pool-file", default="config/theme_stock_pools.json", show_default=True, help="独立主题池 JSON")
def theme_pool_reject_command(symbol: str, theme_id: str, reason: Optional[str], pool_file: str):
    """拒绝关系并锁定，避免后续自动导入写回。"""
    try:
        path, backup = reject_assignment(symbol, theme_id, pool_file, reason)
    except ThemeStockPoolError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"已拒绝: {symbol} / {theme_id} -> {path}；备份: {backup or '-'}")


@theme_pool_group.command(name="revise")
@click.option("--symbol", required=True, help="股票代码")
@click.option("--theme-id", required=True)
@click.option("--pool-role", required=True, type=click.Choice(["rs_member", "watch_only"]))
@click.option("--industry-relation", required=True, type=click.Choice(["core", "direct", "indirect", "unknown"]))
@click.option("--market-theme-relation", required=True, type=click.Choice(["core", "active", "catalyst", "mapping_only", "unknown"]))
@click.option("--confidence", required=True, type=click.Choice(["high", "medium", "low", "unknown"]))
@click.option("--reason", required=True, help="人工复核后的归类理由")
@click.option("--pool-file", default="config/theme_stock_pools.json", show_default=True, help="独立主题池 JSON")
def theme_pool_revise_command(
    symbol: str,
    theme_id: str,
    pool_role: str,
    industry_relation: str,
    market_theme_relation: str,
    confidence: str,
    reason: str,
    pool_file: str,
):
    """修订 pending 关系字段后确认，并记录复核历史。"""
    try:
        path, backup = revise_pending_assignment(
            symbol, theme_id, pool_role, industry_relation, market_theme_relation, confidence, reason, pool_file
        )
    except ThemeStockPoolError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"已修订并确认: {symbol} / {theme_id} -> {path}；备份: {backup or '-'}")


@theme_pool_group.command(name="add-pending")
@click.option("--symbol", required=True, help="股票代码")
@click.option("--name", "stock_name", required=True, help="股票名称")
@click.option("--theme-id", required=True)
@click.option("--pool-role", required=True, type=click.Choice(["rs_member", "watch_only"]))
@click.option("--industry-relation", required=True, type=click.Choice(["core", "direct", "indirect", "unknown"]))
@click.option("--market-theme-relation", required=True, type=click.Choice(["core", "active", "catalyst", "mapping_only", "unknown"]))
@click.option("--confidence", required=True, type=click.Choice(["high", "medium", "low", "unknown"]))
@click.option("--reason", required=True, help="待审核关系理由")
@click.option("--source-url", default="", help="审计交接证据 URL")
@click.option("--pool-file", default="config/theme_stock_pools.json", show_default=True, help="独立主题池 JSON")
def theme_pool_add_pending_command(
    symbol: str,
    stock_name: str,
    theme_id: str,
    pool_role: str,
    industry_relation: str,
    market_theme_relation: str,
    confidence: str,
    reason: str,
    source_url: str,
    pool_file: str,
):
    """添加未确认的主题关系，供后续人工复核。"""
    try:
        path, backup = add_pending_assignment(
            symbol, stock_name, theme_id, pool_role, industry_relation, market_theme_relation, confidence, reason, source_url, pool_file
        )
    except ThemeStockPoolError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"已新增 pending 关系: {symbol} / {theme_id} -> {path}；备份: {backup or '-'}")


@theme_pool_group.command(name="add-core")
@click.option("--symbol", required=True, help="股票代码")
@click.option("--name", "stock_name", required=True, help="股票名称")
@click.option("--theme-id", required=True)
@click.option("--reason", required=True, help="人工纳入理由")
@click.option("--pool-file", default="config/theme_stock_pools.json", show_default=True, help="独立主题池 JSON")
def theme_pool_add_core_command(symbol: str, stock_name: str, theme_id: str, reason: str, pool_file: str):
    """人工添加已确认且锁定的产业核心股票。"""
    try:
        path, backup = add_manual_core_stock(symbol, stock_name, theme_id, reason, pool_file)
    except ThemeStockPoolError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"已添加人工核心股: {symbol} / {theme_id} -> {path}；备份: {backup or '-'}")
