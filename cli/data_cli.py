"""数据下载命令组"""

from typing import Optional
from pathlib import Path

import click

from analysis.data_quality import audit_market_data, save_market_data_audit
from cli.common import load_config as _load_config
from data.downloader import DataDownloader, today_str, default_start
from data.download_service import resolve_download_symbols
from visual.data_quality_report import generate_data_quality_report


def run_download(
    config: dict,
    symbol: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    force: bool = False,
    failed_file: Optional[str] = None,
) -> dict:
    """Execute the stock download workflow for Click and the REPL."""
    dl = DataDownloader(config)
    start = start or default_start()
    end = end or today_str()

    selection = resolve_download_symbols(
        symbol=symbol,
        failed_file=failed_file,
        load_symbols_from_file=DataDownloader.load_symbols_from_file,
        get_stock_list=dl.get_stock_list,
    )
    symbols = selection.symbols

    if selection.source == "failed_file":
        if not symbols:
            raise click.ClickException(f"失败文件中没有可下载股票: {failed_file}")
        click.echo(f"从失败文件读取 {len(symbols)} 只股票: {failed_file}")
    elif selection.source == "all_stocks":
        if not symbols:
            raise click.ClickException("无法获取股票列表")
        click.echo(f"将下载全部 {len(symbols)} 只非ST股票的数据。")
        if selection.requires_confirm and not click.confirm("确认下载全部股票数据?", default=True):
            return {}

    click.echo(f"日期范围: {start} ~ {end}")
    click.echo(f"股票数量: {len(symbols)}")
    results = dl.download_batch(symbols, start, end, force)
    failed = len(dl.last_failed_symbols)
    click.echo(f"\n完成: {len(results)}/{len(symbols)} 只股票下载成功，失败 {failed} 只。")
    return results


def run_stock_basic(config: dict, list_status: str = "L", force: bool = False):
    """Download stock metadata and name mapping."""
    dl = DataDownloader(config)
    df = dl.download_stock_basic(list_status=list_status, force=force)
    click.echo(f"完成: {len(df)} 只股票基础信息")
    click.echo(f"基础信息: {dl._stock_basic_path()}")
    click.echo(f"名称映射: {dl._stock_name_map_path()}")
    return df


def run_daily_basic(
    config: dict,
    start: Optional[str] = None,
    end: Optional[str] = None,
    force: bool = False,
) -> dict[str, int]:
    """Download and incrementally store daily_basic data."""
    dl = DataDownloader(config)
    start = start or default_start()
    end = end or today_str()
    result = dl.download_daily_basic(start=start, end=end, force=force)
    click.echo(
        f"完成: 下载 {result['dates']} 个交易日，写入 {result['rows']} 条记录，"
        f"当前 {result['files']} 个股票指标文件"
    )
    click.echo(f"每日指标目录: {dl._daily_basic_dir()}")
    return result


def run_data_audit(config: dict, deep: bool = False, output: Optional[str] = None) -> dict:
    """Audit local market-data caches and save inspectable artifacts."""
    result = audit_market_data(config, deep=deep)
    output_dir = Path(output) if output else None
    json_path, issues_path = save_market_data_audit(config, result, output_dir)
    reports_dir = Path(config.get("output", {}).get("reports_dir", "output/reports"))
    report_path = generate_data_quality_report(result, reports_dir / "data_quality.html")
    stocks = result["datasets"]["stocks"]
    click.echo(
        f"数据质量: {result['status']} | 个股 {stocks['file_count']} | "
        f"最新 {stocks['reference_date']} 覆盖 {stocks['latest_coverage']:.1%} | "
        f"严重 {result['summary']['critical_count']} / 警告 {result['summary']['warning_count']}"
    )
    click.echo(f"审计报告: {report_path}")
    click.echo(f"审计 JSON: {json_path}")
    click.echo(f"问题明细: {issues_path}")
    return result


@click.group(name="data")
def data_group():
    """数据管理：下载 A 股日K线数据"""
    pass


@data_group.command(name="download")
@click.option("--symbol", default=None, help="股票代码，如 000001.SZ。不指定则下载全部A股（剔除ST）")
@click.option("--start", default=None, help="起始日期 YYYYMMDD（默认读取 defaults.start_date，当前 20110101）")
@click.option("--end", default=None, help="结束日期 YYYYMMDD（默认今天）")
@click.option("--force", is_flag=True, help="强制重新下载（忽略缓存）")
@click.option("--failed-file", default=None, help="从下载失败 CSV/TXT 中读取股票列表并补下载")
def download(
    symbol: Optional[str],
    start: Optional[str],
    end: Optional[str],
    force: bool,
    failed_file: Optional[str],
):
    """下载日K线数据并缓存到本地"""
    run_download(_load_config(), symbol, start, end, force, failed_file)


@data_group.command(name="stock-basic")
@click.option("--list-status", default="L", help="上市状态: L=上市, D=退市, P=暂停上市")
@click.option("--force", is_flag=True, help="强制重新下载并覆盖本地缓存")
def stock_basic(list_status: str, force: bool):
    """下载股票基础信息，并保存股票代码-名称映射表"""
    run_stock_basic(_load_config(), list_status, force)


@data_group.command(name="daily-basic")
@click.option("--start", default=None, help="起始日期 YYYYMMDD（默认读取 defaults.start_date，当前 20110101）")
@click.option("--end", default=None, help="结束日期 YYYYMMDD（默认今天）")
@click.option("--force", is_flag=True, help="强制重新下载指定区间并覆盖重复日期")
def daily_basic(start: Optional[str], end: Optional[str], force: bool):
    """下载全市场每日指标 daily_basic，并增量保存"""
    run_daily_basic(_load_config(), start, end, force)


@data_group.command(name="audit")
@click.option("--deep", is_flag=True, help="逐行扫描完整历史；默认只做全文件字段与末尾记录检查")
@click.option("--output", default=None, help="JSON/CSV 输出目录，默认 output.statistics_dir/data_quality")
def data_audit(deep: bool, output: Optional[str]):
    """检查本地个股、指数和 daily_basic 数据质量"""
    run_data_audit(_load_config(), deep=deep, output=output)
