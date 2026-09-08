"""Standalone excerpt page for selected market-structure screens."""

from __future__ import annotations

from html import escape
import json
from pathlib import Path
from typing import Any

import pandas as pd

from visual.components import html_document, inline_script, relative_href, to_compact_json
from visual.index_forecast_report import (
    _CSS,
    _JS_V11,
    _distribution_metric_tiles,
    _fmt_int,
    _fmt_multiple,
    _fmt_num,
    _fmt_pct,
    _fmt_ratio_pct,
    _index_lift_stock_table,
    _index_structure_rows,
    _layered_breadth_rows,
    _leadership_callout,
    _market_chart_payload,
    _style_rotation_rows,
    _technical_index_kline_payload,
    _tone,
)
from visual.index_report import _echarts_script_tag


_BRIEF_CSS = """
.brief-shell {
  width: min(1880px, calc(100vw - 28px));
  padding: 18px 0 34px;
}
.brief-shell .topbar {
  margin-bottom: 16px;
}
.brief-shell .panel {
  border-radius: 12px;
}
.brief-shell .panel-head {
  padding: 18px 22px;
}
.brief-section > summary.panel-head {
  align-items: center;
  cursor: pointer;
  list-style: none;
  user-select: none;
}
.brief-section > summary.panel-head::-webkit-details-marker {
  display: none;
}
.brief-section > summary.panel-head h2::before {
  content: "−";
  display: inline-block;
  width: 20px;
  color: #2468d8;
}
.brief-section:not([open]) > summary.panel-head h2::before {
  content: "+";
}
.brief-section > .brief-section-content {
  overflow: hidden;
}
.brief-shell .chart {
  height: min(62vh, 680px);
  min-height: 500px;
}
.brief-shell .chart.small {
  min-height: 360px;
}
.brief-shell #forecast-kline {
  height: min(86vh, 980px);
  min-height: 820px;
}
.brief-shell #industry-kline {
  height: min(72vh, 780px);
  min-height: 580px;
}
.brief-shell #forecast-index-indicator,
.brief-shell #industry-indicator {
  height: 260px;
  min-height: 240px;
}
.brief-collapsible {
  margin: 14px 18px 2px;
  border: 1px solid #d8e1ed;
  border-radius: 10px;
  background: #fbfcff;
  overflow: hidden;
}
.brief-collapsible > summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-height: 50px;
  padding: 0 16px;
  cursor: pointer;
  list-style: none;
  user-select: none;
}
.brief-collapsible > summary::-webkit-details-marker {
  display: none;
}
.brief-collapsible > summary::after {
  content: "展开";
  flex: 0 0 auto;
  border: 1px solid #cbd7e6;
  border-radius: 999px;
  padding: 4px 11px;
  color: #4f6280;
  background: #fff;
  font-size: 12px;
  font-weight: 800;
}
.brief-collapsible[open] > summary::after {
  content: "收起";
}
.brief-collapsible strong {
  color: #1f2a3a;
  font-size: 16px;
}
.brief-collapsible small {
  margin-left: 12px;
  color: #7a879a;
  font-size: 13px;
  font-weight: 700;
}
.brief-collapsible em {
  color: #718096;
  font-size: 13px;
  font-style: normal;
  font-weight: 800;
}
.brief-scroll-table {
  max-height: 320px;
  overflow: auto;
  border-top: 1px solid #e5ebf3;
  background: #fff;
}
.layered-breadth-details .brief-scroll-table {
  max-height: 240px;
}
.brief-scroll-table table {
  min-width: 1680px;
  margin: 0;
}
.brief-scroll-table thead th {
  position: sticky;
  top: 0;
  z-index: 2;
  background: #f6f8fb;
}
.brief-distribution-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 14px;
  padding: 10px 18px 18px;
}
.brief-distribution-card {
  border: 1px solid #e5ebf3;
  background: #fff;
  min-width: 0;
}
.brief-distribution-card .breadth-subhead {
  margin: 0;
  padding: 12px 14px 0;
  border-top: 0;
}
.brief-distribution-card .chart.breadth-distribution-chart,
.brief-distribution-card .chart.distribution-quantile-chart {
  height: 260px;
}
.brief-lift-summary {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}
.brief-lift-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  padding: 0 18px 18px;
}
.brief-lift-card {
  border: 1px solid #e5ebf3;
  background: #fff;
  min-width: 0;
}
.brief-lift-card .subpanel-title {
  margin: 0;
  padding: 12px 14px;
  border-top: 0;
}
.brief-lift-card .v2-table-wrap {
  max-height: 420px;
  overflow: auto;
  border-top: 1px solid #e5ebf3;
}
.brief-amount-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 14px;
  padding: 0 18px 18px;
}
.brief-amount-card {
  min-width: 0;
  border: 1px solid #e5ebf3;
  background: #fff;
}
.brief-amount-card .subpanel-title {
  margin: 0;
  padding: 12px 14px;
  border-top: 0;
}
.brief-amount-card .v2-table-wrap {
  max-height: 340px;
  overflow: auto;
  border-top: 1px solid #e5ebf3;
}
@media (max-width: 980px) {
  .brief-distribution-grid,
  .brief-lift-grid,
  .brief-amount-grid {
    grid-template-columns: 1fr;
  }
  .brief-lift-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
"""


def _as_of(structure: dict[str, Any]) -> pd.Timestamp | None:
    value = pd.to_datetime(structure.get("date"), errors="coerce")
    return None if pd.isna(value) else value


def _clip_frame(frame: pd.DataFrame, as_of: pd.Timestamp | None) -> pd.DataFrame:
    if frame.empty or as_of is None:
        return frame.copy()
    work = frame.copy()
    date_column = "date" if "date" in work.columns else "trade_date" if "trade_date" in work.columns else None
    if date_column is None:
        return work
    dates = pd.to_datetime(work[date_column], errors="coerce")
    return work.loc[dates.notna() & dates.le(as_of)].copy()


def _read_index_frame(config: dict, symbol: str, as_of: pd.Timestamp | None) -> pd.DataFrame:
    cache_dir = Path(config.get("data", {}).get("cache_dir", "data/cache")) / "index"
    path = cache_dir / f"{symbol.upper()}.csv"
    if not path.exists():
        return pd.DataFrame()
    try:
        frame = pd.read_csv(path, dtype={"date": str, "trade_date": str, "ts_code": str})
    except Exception:
        return pd.DataFrame()
    return _clip_frame(frame, as_of)


def _brief_index_lift_panel(structure: dict[str, Any]) -> str:
    root = structure.get("index_lift_structure") or {}
    by_symbol = root.get("by_symbol") or {}
    primary = str(root.get("symbol") or next(iter(by_symbol or {}), "")).upper()
    item = by_symbol.get(primary) or (next(iter(by_symbol.values())) if by_symbol else root)
    if not item or not (item.get("top_positive_contributors") or item.get("top_negative_contributors") or item.get("top_turnover_stocks")):
        return (
            "<div class='subpanel-title'><strong>指数涨跌与成交贡献</strong>"
            "<span>暂无可用指数成分、权重或成交额明细</span></div>"
            "<div class='empty-v2'>当前文件没有可展示的指数贡献明细；运行完整市场结构计算后会自动生成。</div>"
        )
    returns = item.get("returns") or {}
    concentration = item.get("contribution_concentration") or {}
    turnover = item.get("turnover_confirmation") or {}
    top_positive_rows = item.get("top_positive_contributors") or []
    top_negative_rows = item.get("top_negative_contributors") or []
    top_turnover_rows = item.get("top_turnover_stocks") or []
    index_name = f"{item.get('index_name') or root.get('index_name') or '--'} {item.get('symbol') or root.get('symbol') or ''}".strip()
    turnover_count = min(20, len(top_turnover_rows))
    metrics = [
        ("观察指数", index_name, f"交易日 {item.get('trade_date') or root.get('trade_date') or '--'}"),
        (
            "上涨前20贡献占比",
            _fmt_ratio_pct(sum(float(row.get("contribution_share") or 0.0) for row in top_positive_rows[:20])),
            f"80%正贡献需 {_fmt_int(concentration.get('stocks_needed_for_80pct_positive_contribution'))} 只",
        ),
        (
            "下跌前20拖累占比",
            _fmt_ratio_pct(sum(float(row.get("contribution_share") or 0.0) for row in top_negative_rows[:20])),
            "占全部负贡献绝对值",
        ),
        (
            f"成交额前{turnover_count or 20}占比",
            _fmt_ratio_pct(turnover.get("top20_turnover_amount_share")),
            f"前20成交股占比 {_fmt_ratio_pct(turnover.get('top20_turnover_amount_share'))}",
        ),
    ]
    tiles = "<div class='metric-strip brief-lift-summary'>" + "".join(
        "<div class='metric-tile'>"
        f"<span>{escape(str(label))}</span><strong>{escape(str(value))}</strong><small>{escape(str(detail))}</small>"
        "</div>"
        for label, value, detail in metrics
    ) + "</div>"
    return f"""
        <div class="subpanel-title"><strong>指数涨跌与成交贡献</strong><span>贡献 = 上一可见指数权重 × 成分当日收益；成交额按成分当日成交额排序</span></div>
        {tiles}
        <div class="brief-lift-grid">
          <div class="brief-lift-card">
            <div class="subpanel-title"><strong>上涨贡献前20</strong><span>按正指数贡献排序，贡献占比为占全部正贡献</span></div>
            <div class="v2-table-wrap compact"><table>
              <thead><tr><th>成分</th><th>行业</th><th>权重</th><th>1日收益</th><th>成交额</th><th>成交/20日</th><th>指数贡献</th><th>贡献占比</th></tr></thead>
              <tbody>{_index_lift_stock_table(top_positive_rows[:20])}</tbody>
            </table></div>
          </div>
          <div class="brief-lift-card">
            <div class="subpanel-title"><strong>下跌拖累前20</strong><span>按负指数贡献排序，贡献占比为占全部负贡献绝对值</span></div>
            <div class="v2-table-wrap compact"><table>
              <thead><tr><th>成分</th><th>行业</th><th>权重</th><th>1日收益</th><th>成交额</th><th>成交/20日</th><th>指数贡献</th><th>拖累占比</th></tr></thead>
              <tbody>{_index_lift_stock_table(top_negative_rows[:20])}</tbody>
            </table></div>
          </div>
          <div class="brief-lift-card">
            <div class="subpanel-title"><strong>成交额前20</strong><span>统计这些股票占指数成分总成交额的比例</span></div>
            <div class="v2-table-wrap compact"><table>
              <thead><tr><th>成分</th><th>行业</th><th>权重</th><th>1日收益</th><th>成交额</th><th>成交/20日</th><th>指数贡献</th><th>成交占比</th></tr></thead>
              <tbody>{_index_lift_stock_table(top_turnover_rows[:20], turnover=True)}</tbody>
            </table></div>
          </div>
        </div>
    """


def _amount_structure_industry_rows(rows: list[dict[str, Any]]) -> str:
    sorted_rows = sorted(
        rows,
        key=lambda item: (
            float(item.get("amount_share_change_20d"))
            if item.get("amount_share_change_20d") is not None
            else float("-inf")
        ),
        reverse=True,
    )
    output: list[str] = []
    for item in sorted_rows[:12]:
        output.append(
            "<tr>"
            f"<td>{escape(str(item.get('industry') or '--'))}</td>"
            f"<td>{escape(_fmt_ratio_pct(item.get('amount_share')))}</td>"
            f"<td class='{_tone(item.get('amount_share_change_5d'))}'>{escape(_fmt_pct(item.get('amount_share_change_5d')))}</td>"
            f"<td class='{_tone(item.get('amount_share_change_20d'))}'>{escape(_fmt_pct(item.get('amount_share_change_20d')))}</td>"
            f"<td>{escape(_fmt_multiple(item.get('amount_ratio_20d')))}</td>"
            f"<td class='{_tone(item.get('return_1d'))}'>{escape(_fmt_pct(item.get('return_1d')))}</td>"
            "</tr>"
        )
    return "".join(output) or "<tr><td colspan='6'>暂无行业成交额增量数据</td></tr>"


def _amount_structure_migration_rows(liquidity: dict[str, Any]) -> str:
    rows = liquidity.get("turnover_migration") or []
    if not rows:
        cap_shares = liquidity.get("cap_turnover_shares") or {}
        cap_changes = liquidity.get("cap_turnover_share_changes") or {}
        style_shares = liquidity.get("style_turnover_shares") or {}
        style_changes = liquidity.get("style_turnover_share_changes") or {}
        rows = [
            {
                "bucket": "权重宽基",
                "name": name,
                "amount_share": cap_shares.get(name),
                "amount_share_change_5d": (cap_changes.get(name) or {}).get("change_5d"),
                "amount_share_change_20d": (cap_changes.get(name) or {}).get("change_20d"),
            }
            for name in ("沪深300", "中证1000", "中证2000")
        ]
        rows.extend(
            {
                "bucket": "题材风格",
                "name": name,
                "amount_share": share,
                "amount_share_change_5d": (style_changes.get(name) or {}).get("change_5d"),
                "amount_share_change_20d": (style_changes.get(name) or {}).get("change_20d"),
            }
            for name, share in style_shares.items()
        )
    rows = [row for row in rows if row.get("amount_share") is not None]
    rows = sorted(
        rows,
        key=lambda item: abs(float(item.get("amount_share_change_20d") or 0.0)),
        reverse=True,
    )
    output: list[str] = []
    for item in rows[:14]:
        output.append(
            "<tr>"
            f"<td>{escape(str(item.get('bucket') or '--'))}</td>"
            f"<td>{escape(str(item.get('name') or '--'))}</td>"
            f"<td>{escape(_fmt_ratio_pct(item.get('amount_share')))}</td>"
            f"<td class='{_tone(item.get('amount_share_change_5d'))}'>{escape(_fmt_pct(item.get('amount_share_change_5d')))}</td>"
            f"<td class='{_tone(item.get('amount_share_change_20d'))}'>{escape(_fmt_pct(item.get('amount_share_change_20d')))}</td>"
            "</tr>"
        )
    return "".join(output) or "<tr><td colspan='5'>暂无权重/题材成交迁移数据</td></tr>"


def _fmt_tushare_amount_yi(value: Any, digits: int = 0) -> str:
    """Format Tushare daily ``amount`` from 千元 to 亿元 for reader-facing HTML."""
    try:
        if pd.isna(value):
            return "--"
        return f"{float(value) / 100000:,.{digits}f}亿"
    except Exception:
        return "--"


def _brief_amount_structure_panel(structure: dict[str, Any]) -> str:
    liquidity = structure.get("liquidity_structure") or {}
    latest = liquidity.get("latest") or {}
    if not latest:
        return (
            "<div class='subpanel-title'><strong>成交额结构</strong>"
            "<span>暂无真实成交额结构数据</span></div>"
            "<div class='empty-v2'>当前文件没有可展示的成交额结构；运行完整市场结构计算后会自动生成。</div>"
        )
    cap_shares = liquidity.get("cap_turnover_shares") or {}
    metrics = [
        (
            "总成交额 / 5日 / 20日均额",
            f"{_fmt_tushare_amount_yi(latest.get('total_amount'))} / {_fmt_multiple(latest.get('amount_ratio_5d'))} / {_fmt_multiple(latest.get('amount_ratio_20d'))}",
            "总成交额按 Tushare amount 千元换算为亿元",
        ),
        (
            "沪深300 / 中证1000 / 中证2000成交占比",
            f"{_fmt_ratio_pct(cap_shares.get('沪深300'))} / {_fmt_ratio_pct(cap_shares.get('中证1000'))} / {_fmt_ratio_pct(cap_shares.get('中证2000'))}",
            "宽基成分成交额占全市场比例",
        ),
        (
            "上涨 / 下跌股票成交占比",
            f"{_fmt_ratio_pct(latest.get('advance_amount_ratio'))} / {_fmt_ratio_pct(latest.get('decline_amount_ratio'))}",
            f"涨跌成交比 {_fmt_num(latest.get('advance_decline_amount_ratio'), 2)}",
        ),
        (
            "涨幅前10% / 跌幅前10%成交集中度",
            f"{_fmt_ratio_pct(latest.get('top_10pct_gainer_amount_share'))} / {_fmt_ratio_pct(latest.get('top_10pct_loser_amount_share'))}",
            f"样本各 {_fmt_int(latest.get('top_10pct_gainer_count'))} 只",
        ),
    ]
    tiles = "<div class='metric-strip'>" + "".join(
        "<div class='metric-tile'>"
        f"<span>{escape(label)}</span><strong>{escape(value)}</strong><small>{escape(note)}</small>"
        "</div>"
        for label, value, note in metrics
    ) + "</div>"
    return f"""
        <div class="subpanel-title"><strong>成交额结构</strong><span>只使用真实成交额；观察放量集中、宽基占比和风格迁移</span></div>
        {tiles}
        <div class="brief-amount-grid">
          <div class="brief-amount-card">
            <div class="subpanel-title"><strong>行业成交额增量排名</strong><span>按20日成交占比增量降序</span></div>
            <div class="v2-table-wrap compact"><table>
              <thead><tr><th>行业</th><th>当前成交占比</th><th>5日变化百分点</th><th>20日变化百分点</th><th>成交/20日</th><th>1日收益</th></tr></thead>
              <tbody>{_amount_structure_industry_rows(liquidity.get('industry_turnover_shares') or [])}</tbody>
            </table></div>
          </div>
          <div class="brief-amount-card">
            <div class="subpanel-title"><strong>权重板块与题材板块成交额迁移</strong><span>按20日变化绝对值排序</span></div>
            <div class="v2-table-wrap compact"><table>
              <thead><tr><th>类型</th><th>板块</th><th>当前成交占比</th><th>5日变化百分点</th><th>20日变化百分点</th></tr></thead>
              <tbody>{_amount_structure_migration_rows(liquidity)}</tbody>
            </table></div>
          </div>
        </div>
    """


def _default_index_frames(config: dict, structure: dict[str, Any]) -> dict[str, pd.DataFrame]:
    as_of = _as_of(structure)
    frames: dict[str, pd.DataFrame] = {}
    for item in (structure.get("indices") or {}).values():
        symbol = str(item.get("symbol") or "").upper()
        if not symbol or not item.get("available", True) or item.get("synthetic"):
            continue
        frame = _read_index_frame(config, symbol, as_of)
        if not frame.empty:
            frames[symbol] = frame
    return frames


def _primary_symbol(structure: dict[str, Any], fallback: str = "000001.SH") -> str:
    for item in (structure.get("indices") or {}).values():
        symbol = str(item.get("symbol") or "").upper()
        if symbol == fallback and item.get("available", True) and not item.get("synthetic"):
            return symbol
    for item in (structure.get("indices") or {}).values():
        symbol = str(item.get("symbol") or "").upper()
        if symbol and item.get("available", True) and not item.get("synthetic"):
            return symbol
    return fallback


def _technical_config(config: dict) -> dict[str, Any]:
    return {
        **(config.get("technical_structure", {}) or {}),
        "cache_dir": str(Path(config.get("output", {}).get("statistics_dir", "output/statistics"))),
    }


def generate_market_structure_brief(
    config: dict,
    structure: dict[str, Any],
    output_path: str | Path,
    *,
    full_report_path: str | Path | None = None,
    features: pd.DataFrame | None = None,
    symbol: str | None = None,
    name: str = "上证指数",
    technical_index_frames: dict[str, pd.DataFrame] | None = None,
    technical_industry_frames: dict[str, pd.DataFrame] | None = None,
    technical_structure_config: dict[str, Any] | None = None,
) -> Path:
    """Generate a collapsible excerpt from saved v2 market-structure facts and local caches."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    primary_symbol = str(symbol or _primary_symbol(structure)).upper()
    index_frames = technical_index_frames or _default_index_frames(config, structure)
    primary_features = features.copy() if features is not None else index_frames.get(primary_symbol, pd.DataFrame()).copy()
    if primary_features.empty:
        primary_features = _read_index_frame(config, primary_symbol, _as_of(structure))
    if primary_symbol not in index_frames and not primary_features.empty:
        index_frames = {**index_frames, primary_symbol: primary_features}
    tech_config = technical_structure_config or _technical_config(config)
    technical_index_payload = _technical_index_kline_payload(
        primary_features,
        primary_symbol,
        structure,
        index_frames,
        tech_config,
    )
    if primary_symbol not in technical_index_payload and technical_index_payload:
        primary_symbol = next(iter(technical_index_payload))
    technical_index_options = "".join(
        f"<option value='{escape(code, quote=True)}'{' selected' if code == primary_symbol else ''}>"
        f"{escape(str(item.get('name') or code))}（{escape(code)}）</option>"
        for code, item in technical_index_payload.items()
    )
    primary_technical_timeframes = technical_index_payload.get(primary_symbol, {}).get("timeframes") or {}
    forecast_chart = primary_technical_timeframes.get("1d") or {}

    structure_state = structure.get("market_structure") or {}
    breadth_history_path = (
        Path(config.get("output", {}).get("statistics_dir", "output/statistics"))
        / "index_forecast"
        / f"market_structure_layered_breadth_history_{primary_symbol}.csv"
    )
    breadth_history_link = (
        f"<a href='{escape(relative_href(output, breadth_history_path), quote=True)}' download>导出最近6个月 CSV</a>"
        if breadth_history_path.exists() else ""
    )
    full_link = (
        f"<a class='primary' href='{escape(relative_href(output, full_report_path), quote=True)}'>完整市场结构报告</a>"
        if full_report_path else ""
    )
    body = f"""
    <main class="shell brief-shell">
      <header class="topbar">
        <div>
          <h1>{escape(name)}市场结构摘录</h1>
          <div class="sub">{escape(primary_symbol)} · 市场结构摘要 · 数据截至 {escape(str(structure.get('date', '--')))} · 不参与策略、仓位或订单。</div>
          <div class="top-actions"><a href="../dashboard.html">返回 Dashboard</a>{full_link}</div>
        </div>
        <div class="badge neutral">{escape(str(structure_state.get('style_regime_name') or '结构摘录'))}</div>
      </header>

      <details class="panel brief-section" data-section="index-technical" open>
        <summary class="panel-head"><h2>指数趋势与技术结构</h2><span>日/周趋势、K线、技术指标与归一化相对强度</span></summary>
        <div class="brief-section-content">
        <details class="brief-collapsible index-overview-details">
          <summary><span><strong>主要指数概览</strong><small>默认折叠；展开后可用滚轮下拉、横向滚动查看完整字段</small></span><em>{len(structure.get('indices') or {})} 个指数</em></summary>
          <div class="v2-table-wrap brief-scroll-table"><table>
            <thead><tr><th>指数</th><th>代码</th><th>1日</th><th>5日</th><th>10日</th><th>20日</th><th>60日</th><th>日线</th><th>周线</th><th>成交/20日</th><th>MA20</th><th>MA60</th><th>20日高/距离</th><th>20日低/距离</th><th>60日高/距离</th><th>60日低/距离</th><th>位置</th></tr></thead>
            <tbody>{_index_structure_rows(structure)}</tbody>
          </table></div>
        </details>
        <div class="subpanel-title"><strong>指数K线与手动画线</strong><span>K线、成交量、成交额、量额比、三市总额及其 5/20 日均额同图；指数使用不复权点位</span></div>
        <div class="forecast-kline-toolbar">
          <div class="kline-tools">
            <strong>指数</strong>
            <select id="forecast-index-select" class="kline-index-select" onchange="switchForecastIndex(this.value)">{technical_index_options}</select>
            <button class="kline-period-btn active" data-timeframe="1d" onclick="switchForecastKline('1d',this)">日K</button>
            <button class="kline-period-btn" data-timeframe="1w" onclick="switchForecastKline('1w',this)">周K</button>
            <button class="kline-period-btn" data-timeframe="1mo" onclick="switchForecastKline('1mo',this)">月K</button>
          </div>
          <div class="forecast-manual-tools">
            <strong>画线</strong>
            <button class="forecast-manual-btn" data-tool="trend" type="button" onclick="setForecastManualTool('trend')">趋势线</button>
            <button class="forecast-manual-btn" data-tool="support" type="button" onclick="setForecastManualTool('support')">支撑线</button>
            <button class="forecast-manual-btn" data-tool="resistance" type="button" onclick="setForecastManualTool('resistance')">阻力线</button>
            <button class="forecast-manual-btn" type="button" onclick="setForecastManualTool(null)">选择/调整</button>
            <button class="forecast-manual-btn" type="button" onclick="forecastManualUndo()">撤销</button>
            <button class="forecast-manual-btn danger" type="button" onclick="forecastManualClear()">清空本周期</button>
            <span id="forecast-manual-status" class="forecast-manual-status">选择工具后在指数 K 线图点击画线；画完可拖动圆点调整。</span>
          </div>
        </div>
        <div class="forecast-integrated-note">主图下方依次显示指数成交量、指数成交额、指数量额比和三市总成交额；三市总额柱状图叠加 5 日、20 日均额线，红色代表上涨日、绿色代表下跌日；自动结构线显示已关闭，支撑/阻力/趋势线均由你手动绘制并保存在浏览器本地。</div>
        <div id="forecast-kline" class="chart"></div>
        <div class="kline-subchart-head"><div class="indicator-switches"><strong>副图</strong><button type="button" class="indicator-switch-btn" data-indicator="kdj" onclick="switchForecastIndicator('kdj')">KDJ</button><button type="button" class="indicator-switch-btn" data-indicator="macd" onclick="switchForecastIndicator('macd')">MACD</button></div><span>成交量/成交额已在主图内；KDJ/MACD 可按需展开</span></div>
        <div id="forecast-index-indicator" class="chart index-indicator"></div>
        <div class="subpanel-title"><strong>主要指数区间强度对比</strong><span>所选区间首个有效交易日统一归一为100，只比较区间涨跌强弱</span></div>
        <div class="index-compare-tools"><strong>比较区间</strong><button type="button" class="index-compare-window" data-window="20" onclick="switchIndexCompareWindow(20)">20日</button><button type="button" class="index-compare-window" data-window="60" onclick="switchIndexCompareWindow(60)">60日</button><button type="button" class="index-compare-window active" data-window="120" onclick="switchIndexCompareWindow(120)">120日</button><button type="button" class="index-compare-window" data-window="250" onclick="switchIndexCompareWindow(250)">250日</button><span>包含上证、沪深300、中证500/1000/2000、创业板、科创50和平均股价</span></div>
        <div id="structure-index-compare" class="chart"></div>
        <div id="structure-index-ranking" class="index-strength-ranking"></div>
        </div>
      </details>

      <details class="panel brief-section" data-section="layered-breadth" open>
        <summary class="panel-head"><h2>分层市场广度</h2><span>最近6个月：全A与主要宽基的参与度、均线覆盖和A/D</span></summary>
        <div class="brief-section-content">
        <details class="brief-collapsible layered-breadth-details">
          <summary><span><strong>分层市场广度概览</strong><small>默认折叠；展开后可用滚轮下滑、横向滚动查看完整字段</small></span><em>{len(structure.get('layered_breadth') or {})} 个层级</em></summary>
          <div class="v2-table-wrap brief-scroll-table"><table>
            <thead><tr><th>层级</th><th>状态</th><th>有效成员</th><th>覆盖率</th><th>上涨比例</th><th>MA20上方</th><th>MA60上方</th><th>20日新高/新低</th><th>标准化A/D</th><th>成交占比</th><th>成员口径</th><th>行情新鲜度</th></tr></thead>
            <tbody>{_layered_breadth_rows(structure)}</tbody>
          </table></div>
        </details>
        <div class="layered-breadth-tools"><strong>图表指标</strong>
          <button type="button" class="layered-breadth-switch active" data-metric="advance_ratio" onclick="switchLayeredBreadthMetric('advance_ratio')">上涨比例</button>
          <button type="button" class="layered-breadth-switch" data-metric="pct_above_ma5" onclick="switchLayeredBreadthMetric('pct_above_ma5')">MA5</button><button type="button" class="layered-breadth-switch" data-metric="pct_above_ma10" onclick="switchLayeredBreadthMetric('pct_above_ma10')">MA10</button><button type="button" class="layered-breadth-switch" data-metric="pct_above_ma20" onclick="switchLayeredBreadthMetric('pct_above_ma20')">MA20</button><button type="button" class="layered-breadth-switch" data-metric="pct_above_ma60" onclick="switchLayeredBreadthMetric('pct_above_ma60')">MA60</button>
          <button type="button" class="layered-breadth-switch" data-metric="new_high_5_ratio" onclick="switchLayeredBreadthMetric('new_high_5_ratio')">5日新高</button><button type="button" class="layered-breadth-switch" data-metric="new_low_5_ratio" onclick="switchLayeredBreadthMetric('new_low_5_ratio')">5日新低</button><button type="button" class="layered-breadth-switch" data-metric="new_high_10_ratio" onclick="switchLayeredBreadthMetric('new_high_10_ratio')">10日新高</button><button type="button" class="layered-breadth-switch" data-metric="new_low_10_ratio" onclick="switchLayeredBreadthMetric('new_low_10_ratio')">10日新低</button><button type="button" class="layered-breadth-switch" data-metric="new_high_20_ratio" onclick="switchLayeredBreadthMetric('new_high_20_ratio')">20日新高</button><button type="button" class="layered-breadth-switch" data-metric="new_low_20_ratio" onclick="switchLayeredBreadthMetric('new_low_20_ratio')">20日新低</button><button type="button" class="layered-breadth-switch" data-metric="new_high_60_ratio" onclick="switchLayeredBreadthMetric('new_high_60_ratio')">60日新高</button><button type="button" class="layered-breadth-switch" data-metric="new_low_60_ratio" onclick="switchLayeredBreadthMetric('new_low_60_ratio')">60日新低</button>
          <span>最近6个月；新高/新低基准均排除当日</span>{breadth_history_link}
        </div>
        <div id="structure-layered-breadth" class="chart layered-chart"></div>
        <div class="subpanel-title"><strong>横截面收益分布</strong><span>当日直方图与最近20个交易日 Q10/中位数/Q90；不是未来收益分布</span></div>
        {_distribution_metric_tiles(structure)}
        <div class="brief-distribution-grid">
          <div class="brief-distribution-card">
            <div class="breadth-subhead"><strong>当日个股涨跌幅分布</strong><span>按有效股票 1 日涨跌幅分桶</span></div>
            <div id="structure-return-distribution" class="chart breadth-distribution-chart"></div>
          </div>
          <div class="brief-distribution-card">
            <div class="breadth-subhead"><strong>20日分位轨迹</strong><span>Q10、中位数与Q90</span></div>
            <div id="structure-distribution-quantiles" class="chart distribution-quantile-chart"></div>
          </div>
        </div>
        </div>
      </details>

      <details class="panel brief-section" data-section="style-and-structure" open>
        <summary class="panel-head"><h2>风格轮动、领涨质量与行业结构</h2><span>当前横向强弱，不表示未来收益概率</span></summary>
        <div class="brief-section-content">
        {_leadership_callout(structure)}
        {_brief_index_lift_panel(structure)}
        {_brief_amount_structure_panel(structure)}
        <div class="subpanel-title"><strong>风格轮动状态</strong><span>强度水位、5日变化、20日相对斜率与领涨持续时间</span></div>
        <div class="v2-table-wrap compact"><table><thead><tr><th>风格</th><th>当前强度</th><th>5日变化</th><th>20日相对强弱</th><th>领涨天数</th><th>领涨质量</th><th>当前状态</th></tr></thead><tbody>{_style_rotation_rows(structure)}</tbody></table></div>
        </div>
      </details>
    </main>
    """
    html = html_document(
        title=f"{name}市场结构摘录",
        body=body,
        styles=_CSS + _BRIEF_CSS,
        head_extra=_echarts_script_tag() + '<link rel="icon" href="data:,">',
        scripts=(
            inline_script(
                f"window._FORECAST_CHART={to_compact_json(forecast_chart)};"
                f"window._MARKET_STRUCTURE={to_compact_json(_market_chart_payload(structure))};"
                "window._INDEX_LIFT_STRUCTURE={\"by_symbol\":{}};"
                f"window._PRIMARY_TECHNICAL_INDEX={to_compact_json(primary_symbol)};"
                f"window._TECHNICAL_INDEX_KLINES={to_compact_json(technical_index_payload)};"
                f"window._TECHNICAL_KLINES={to_compact_json(primary_technical_timeframes)};"
            )
            + _JS_V11
            + inline_script(
                "document.addEventListener('toggle',function(event){"
                "if(event.target.classList&&event.target.classList.contains('brief-section')&&event.target.open){"
                "window.dispatchEvent(new Event('resize'));"
                "}},true);"
            )
        ),
    )
    output.write_text(html, encoding="utf-8")
    return output


def generate_market_structure_brief_from_file(
    config: dict,
    structure_path: str | Path,
    output_path: str | Path,
    *,
    full_report_path: str | Path | None = None,
) -> Path:
    structure = json.loads(Path(structure_path).read_text(encoding="utf-8"))
    return generate_market_structure_brief(
        config,
        structure,
        output_path,
        full_report_path=full_report_path,
    )
