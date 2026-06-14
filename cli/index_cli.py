"""Index overview commands."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import click
import yaml

from data.downloader import DataDownloader, default_start, today_str
from visual.index_report import generate_index_report


DEFAULT_INDEX_SYMBOL = "000001.SH"
DEFAULT_INDEX_NAME = "上证指数"


def _load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _configured_indexes(config: dict) -> list[dict]:
    indexes = config.get("index_overview", {}).get("indexes", [])
    if indexes:
        return indexes
    return [{"symbol": DEFAULT_INDEX_SYMBOL, "name": DEFAULT_INDEX_NAME, "market": "SH"}]


def _index_name(config: dict, symbol: str) -> str:
    for item in _configured_indexes(config):
        if item.get("symbol", "").upper() == symbol.upper():
            return item.get("name") or symbol
    if symbol.upper() == DEFAULT_INDEX_SYMBOL:
        return DEFAULT_INDEX_NAME
    return symbol


def _default_symbol(config: dict) -> str:
    return config.get("index_overview", {}).get("default_symbol", DEFAULT_INDEX_SYMBOL)


def _selected_indexes(config: dict, symbol: Optional[str], all_indexes: bool) -> list[dict]:
    if all_indexes:
        return _configured_indexes(config)
    selected_symbol = (symbol or _default_symbol(config)).upper()
    return [{"symbol": selected_symbol, "name": _index_name(config, selected_symbol)}]


def _output_path(config: dict, symbol: str, output: Optional[str], all_indexes: bool = False) -> Path:
    if output:
        path = Path(output)
        return path / f"{symbol}_overview.html" if all_indexes else path
    reports_dir = Path(config["output"]["reports_dir"]) / "index"
    return reports_dir / f"{symbol}_overview.html"


@click.group(name="index")
def index_group():
    """指数数据与每日概览。"""
    pass


@index_group.command(name="download")
@click.option("--symbol", default=None, help="指数代码，默认 000001.SH（上证指数）")
@click.option("--all", "all_indexes", is_flag=True, help="下载配置中的第一阶段指数列表")
@click.option("--start", default=None, help="起始日期 YYYYMMDD，默认读取 defaults.start_date")
@click.option("--end", default=None, help="结束日期 YYYYMMDD，默认今天")
@click.option("--force", is_flag=True, help="强制重新下载并合并缓存")
def download(symbol: Optional[str], all_indexes: bool, start: Optional[str], end: Optional[str], force: bool):
    """下载指数日线并缓存到 data/cache/index。"""
    config = _load_config()
    dl = DataDownloader(config)
    start = start or default_start()
    end = end or today_str()
    indexes = _selected_indexes(config, symbol, all_indexes)

    click.echo(f"日期范围: {start} ~ {end}")
    click.echo(f"指数数量: {len(indexes)}")
    for item in indexes:
        sym = item["symbol"].upper()
        name = item.get("name") or _index_name(config, sym)
        click.echo(f"\n指数: {sym} ({name})")
        df = dl.download_index(symbol=sym, start=start, end=end, force=force)
        click.echo(f"完成: {len(df)} 条指数日线，缓存文件: {dl._index_cache_path(sym)}")


@index_group.command(name="report")
@click.option("--symbol", default=None, help="指数代码，默认 000001.SH（上证指数）")
@click.option("--all", "all_indexes", is_flag=True, help="为配置中的第一阶段指数列表生成报告")
@click.option("--output", default=None, help="输出 HTML 路径；--all 时表示输出目录")
def report(symbol: Optional[str], all_indexes: bool, output: Optional[str]):
    """基于本地缓存生成指数概览 HTML。"""
    config = _load_config()
    dl = DataDownloader(config)
    indexes = _selected_indexes(config, symbol, all_indexes)

    for item in indexes:
        sym = item["symbol"].upper()
        name = item.get("name") or _index_name(config, sym)
        df = dl.load_index_cache(sym)
        if df is None or df.empty:
            raise click.ClickException(f"指数缓存不存在: {sym}，请先执行 python main.py index download --symbol {sym}")

        out_path = _output_path(config, sym, output, all_indexes)
        generate_index_report(df, symbol=sym, name=name, output_path=out_path)
        click.echo(f"报告已生成: {out_path}")


@index_group.command(name="overview")
@click.option("--symbol", default=None, help="指数代码，默认 000001.SH（上证指数）")
@click.option("--all", "all_indexes", is_flag=True, help="更新配置中的第一阶段指数列表并生成报告")
@click.option("--start", default=None, help="起始日期 YYYYMMDD，默认读取 defaults.start_date")
@click.option("--end", default=None, help="结束日期 YYYYMMDD，默认今天")
@click.option("--force", is_flag=True, help="强制重新下载并合并缓存")
@click.option("--output", default=None, help="输出 HTML 路径；--all 时表示输出目录")
def overview(
    symbol: Optional[str],
    all_indexes: bool,
    start: Optional[str],
    end: Optional[str],
    force: bool,
    output: Optional[str],
):
    """更新指数日线并生成每日概览。"""
    config = _load_config()
    dl = DataDownloader(config)
    start = start or default_start()
    end = end or today_str()
    indexes = _selected_indexes(config, symbol, all_indexes)

    click.echo(f"日期范围: {start} ~ {end}")
    click.echo(f"指数数量: {len(indexes)}")
    for item in indexes:
        sym = item["symbol"].upper()
        name = item.get("name") or _index_name(config, sym)
        click.echo(f"\n指数: {sym} ({name})")
        df = dl.download_index(symbol=sym, start=start, end=end, force=force)
        out_path = _output_path(config, sym, output, all_indexes)
        generate_index_report(df, symbol=sym, name=name, output_path=out_path)
        click.echo(f"完成: {len(df)} 条指数日线")
        click.echo(f"报告已生成: {out_path}")
