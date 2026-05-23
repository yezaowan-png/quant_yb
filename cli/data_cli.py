"""数据下载命令组"""

from pathlib import Path
from typing import Optional

import click
import yaml

from data.downloader import DataDownloader, today_str, default_start


def _load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@click.group(name="data")
def data_group():
    """数据管理：下载 A 股日K线数据"""
    pass


@data_group.command(name="download")
@click.option("--symbol", default=None, help="股票代码，如 000001.SZ。不指定则下载全部A股（剔除ST）")
@click.option("--start", default=None, help="起始日期 YYYYMMDD（默认 20210101）")
@click.option("--end", default=None, help="结束日期 YYYYMMDD（默认今天）")
@click.option("--force", is_flag=True, help="强制重新下载（忽略缓存）")
def download(symbol: Optional[str], start: Optional[str], end: Optional[str], force: bool):
    """下载日K线数据并缓存到本地"""
    config = _load_config()
    dl = DataDownloader(config)

    start = start or default_start()
    end = end or today_str()

    if symbol:
        symbols = [s.strip().upper() for s in symbol.split(",")]
    else:
        # 默认下载全部A股（剔除ST）
        stocks = dl.get_stock_list()
        if not stocks:
            click.echo("错误: 无法获取股票列表。", err=True)
            return
        symbols = [s["ts_code"] for s in stocks]
        click.echo(f"将下载全部 {len(symbols)} 只非ST股票的数据。")
        if not click.confirm("确认下载全部股票数据?", default=True):
            return

    click.echo(f"日期范围: {start} ~ {end}")
    click.echo(f"股票数量: {len(symbols)}")
    results = dl.download_batch(symbols, start, end, force)

    success = len(results)
    click.echo(f"\n完成: {success}/{len(symbols)} 只股票下载成功。")
