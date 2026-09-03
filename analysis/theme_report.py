"""HTML dashboard for theme period performance."""

from __future__ import annotations

import html
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from analysis.technical_structure import TechnicalStructureService, normalize_ohlcv, resample_ohlcv
from visual.components import DEFAULT_ECHARTS_CDN, echarts_script_tag, html_document, inline_script, safe_json, stock_link_html
from visual.technical_structure_renderer import TechnicalStructureRenderer


ECHARTS_SRC = DEFAULT_ECHARTS_CDN


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return False


def _num(value: Any) -> float | None:
    if _is_missing(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return number


def _fmt_pct(value: Any, digits: int = 2) -> str:
    number = _num(value)
    if number is None:
        return "-"
    return f"{number:+.{digits}f}%"


def _fmt_num(value: Any, digits: int = 2) -> str:
    number = _num(value)
    if number is None:
        return "-"
    return f"{number:,.{digits}f}"


def _json(data: Any) -> str:
    return safe_json(data, allow_nan=False)


def _tone(value: Any) -> str:
    number = _num(value)
    if number is None:
        return "neutral"
    if number > 0:
        return "up"
    if number < 0:
        return "down"
    return "neutral"


def _card(label: str, value: str, tone: str = "neutral", sub: str = "") -> str:
    return f"""
    <div class="stat-card {tone}">
      <div class="stat-label">{html.escape(label)}</div>
      <div class="stat-value">{html.escape(value)}</div>
      <div class="stat-sub">{html.escape(sub)}</div>
    </div>
    """


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for _, row in df.iterrows():
        rows.append(
            {
                "ts_code": str(row.get("ts_code", "")),
                "name": str(row.get("name", "")),
                "return_pct": _num(row.get("return_pct")),
                "max_drawdown_pct": _num(row.get("max_drawdown_pct")),
                "annualized_volatility_pct": _num(row.get("annualized_volatility_pct")),
                "return_drawdown_ratio": _num(row.get("return_drawdown_ratio")),
                "avg_turnover_rate": _num(row.get("avg_turnover_rate")),
                "avg_volume_ratio": _num(row.get("avg_volume_ratio")),
                "total_mv_change_pct": _num(row.get("total_mv_change_pct")),
                "latest_close_vs_ma20_pct": _num(row.get("latest_close_vs_ma20_pct")),
                "latest_close_vs_ma60_pct": _num(row.get("latest_close_vs_ma60_pct")),
                "latest_volume_ratio_20": _num(row.get("latest_volume_ratio_20")),
                "latest_high20_distance_pct": _num(row.get("latest_high20_distance_pct")),
                "latest_low20_distance_pct": _num(row.get("latest_low20_distance_pct")),
                "start_date": str(row.get("start_date", "")),
                "end_date": str(row.get("end_date", "")),
                "trading_days": int(_num(row.get("trading_days")) or 0),
                "valid": bool(row.get("valid", False)),
                "reason": "" if _is_missing(row.get("reason")) else str(row.get("reason", "")),
            }
        )
    return rows


def _rank_records(df: pd.DataFrame, top_n: int = 7, bottom_n: int = 5) -> list[dict[str, Any]]:
    valid = df[df["valid"] == True].copy()  # noqa: E712
    valid["return_pct"] = pd.to_numeric(valid.get("return_pct"), errors="coerce")
    valid = valid.dropna(subset=["return_pct"])
    if valid.empty:
        return []
    top = valid.sort_values("return_pct", ascending=False).head(top_n)
    bottom = valid.sort_values("return_pct", ascending=True).head(bottom_n)
    ranked = pd.concat([top, bottom], ignore_index=False).drop_duplicates(subset=["ts_code"], keep="first")
    return _records(ranked.sort_values("return_pct", ascending=True))


def _index_records(df: pd.DataFrame | None) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    rows = []
    for _, row in df.iterrows():
        rows.append(
            {
                "date": str(row.get("date", "")),
                "open": _num(row.get("open")),
                "high": _num(row.get("high")),
                "low": _num(row.get("low")),
                "close": _num(row.get("close")),
                "volume": _num(row.get("volume")),
                "amount": _num(row.get("amount")),
                "member_count": int(_num(row.get("member_count")) or 0),
                "pct_chg": _num(row.get("pct_chg")),
                "ma5": _num(row.get("ma5")),
                "ma20": _num(row.get("ma20")),
                "ma60": _num(row.get("ma60")),
                "volume_ma5": _num(row.get("volume_ma5")),
                "volume_ma20": _num(row.get("volume_ma20")),
                "amount_ma5": _num(row.get("amount_ma5")),
                "amount_ma20": _num(row.get("amount_ma20")),
                "advance_count": int(_num(row.get("advance_count")) or 0),
                "decline_count": int(_num(row.get("decline_count")) or 0),
                "flat_count": int(_num(row.get("flat_count")) or 0),
                "advance_ratio_pct": _num(row.get("advance_ratio_pct")),
                "above_ma20_count": int(_num(row.get("above_ma20_count")) or 0),
                "above_ma20_ratio_pct": _num(row.get("above_ma20_ratio_pct")),
                "above_ma60_count": int(_num(row.get("above_ma60_count")) or 0),
                "above_ma60_ratio_pct": _num(row.get("above_ma60_ratio_pct")),
                "new_high_20_count": int(_num(row.get("new_high_20_count")) or 0),
                "new_high_20_ratio_pct": _num(row.get("new_high_20_ratio_pct")),
                "new_low_20_count": int(_num(row.get("new_low_20_count")) or 0),
                "new_low_20_ratio_pct": _num(row.get("new_low_20_ratio_pct")),
                "member_return_std_pct": _num(row.get("member_return_std_pct")),
            }
        )
    return rows


def _build_table(details: pd.DataFrame, output_path: Path, config: dict | None = None) -> str:
    rows = []
    for _, row in details.iterrows():
        ret = row.get("return_pct")
        dd = row.get("max_drawdown_pct")
        valid = bool(row.get("valid", False))
        ret_cls = _tone(ret)
        reason = "" if _is_missing(row.get("reason")) else str(row.get("reason", ""))
        rows.append(
            f"""
            <tr>
              <td>{stock_link_html(config, output_path, row.get("ts_code", ""))}</td>
              <td>{html.escape(str(row.get("name", "")))}</td>
              <td class="{ret_cls}" data-sort="{_num(ret) if _num(ret) is not None else ''}">{_fmt_pct(ret)}</td>
              <td data-sort="{_num(dd) if _num(dd) is not None else ''}">{_fmt_pct(dd)}</td>
              <td data-sort="{_num(row.get('annualized_volatility_pct')) if _num(row.get('annualized_volatility_pct')) is not None else ''}">{_fmt_pct(row.get("annualized_volatility_pct"))}</td>
              <td data-sort="{_num(row.get('return_drawdown_ratio')) if _num(row.get('return_drawdown_ratio')) is not None else ''}">{_fmt_num(row.get("return_drawdown_ratio"))}</td>
              <td class="{_tone(row.get("latest_close_vs_ma20_pct"))}" data-sort="{_num(row.get('latest_close_vs_ma20_pct')) if _num(row.get('latest_close_vs_ma20_pct')) is not None else ''}">{_fmt_pct(row.get("latest_close_vs_ma20_pct"))}</td>
              <td class="{_tone(row.get("latest_close_vs_ma60_pct"))}" data-sort="{_num(row.get('latest_close_vs_ma60_pct')) if _num(row.get('latest_close_vs_ma60_pct')) is not None else ''}">{_fmt_pct(row.get("latest_close_vs_ma60_pct"))}</td>
              <td data-sort="{_num(row.get('latest_volume_ratio_20')) if _num(row.get('latest_volume_ratio_20')) is not None else ''}">{_fmt_num(row.get("latest_volume_ratio_20"))}</td>
              <td>{_fmt_num(row.get("avg_turnover_rate"))}</td>
              <td>{_fmt_num(row.get("avg_volume_ratio"))}</td>
              <td class="{_tone(row.get("total_mv_change_pct"))}">{_fmt_pct(row.get("total_mv_change_pct"))}</td>
              <td>{html.escape(str(row.get("start_date", "")))} → {html.escape(str(row.get("end_date", "")))}</td>
              <td>{int(_num(row.get("trading_days")) or 0)}</td>
              <td>{'有效' if valid else html.escape(reason or '无效')}</td>
            </tr>
            """
        )

    return f"""
    <section class="table-section">
      <div class="section-head">
        <h2>个股明细</h2>
        <span>点击表头可排序</span>
      </div>
      <div class="table-wrap">
        <table id="detailTable">
          <thead>
            <tr>
              <th>代码</th>
              <th>名称</th>
              <th>涨跌幅</th>
              <th>最大回撤</th>
              <th>年化波动</th>
              <th>收益/回撤</th>
              <th>距MA20</th>
              <th>距MA60</th>
              <th>20日量能</th>
              <th>平均换手</th>
              <th>平均量比</th>
              <th>市值变化</th>
              <th>实际区间</th>
              <th>交易日</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
    </section>
    """


def build_theme_dashboard(
    summary: dict[str, object],
    details: pd.DataFrame,
    output_path: Path,
    concept_index: pd.DataFrame | None = None,
    config: dict | None = None,
) -> None:
    """Write an HTML dashboard for theme analysis."""
    valid = details[details["valid"] == True].copy()  # noqa: E712
    valid = valid.sort_values("return_pct", ascending=False, na_position="last")
    chart_rows = _records(valid)
    rank_rows = _rank_records(details)
    heat_rows = [
        row for row in chart_rows
        if row["avg_turnover_rate"] is not None or row["avg_volume_ratio"] is not None
    ]

    technical_series: dict[str, list[dict[str, Any]]] = {}
    if concept_index is not None and not concept_index.empty:
        project_config = config or {}
        technical_config = {
            **(project_config.get("technical_structure", {}) or {}),
            "cache_dir": str(Path(project_config.get("output", {}).get("statistics_dir", "output/statistics"))),
        }
        symbol = f"THEME_{summary.get('pool', 'CONCEPT')}"
        service = TechnicalStructureService(technical_config, cache_dir=technical_config["cache_dir"])
        results = service.analyze_multi_timeframe(
            symbol=symbol, asset_type="other", timeframes=["1d", "1w", "1mo"],
            ohlcv=concept_index, adjustment="none",
        )
        source = normalize_ohlcv(concept_index, symbol=symbol, asset_type="other", adjustment="none")
        frames = {
            "1d": source.data,
            "1w": resample_ohlcv(source, "1w").data,
            "1mo": resample_ohlcv(source, "1mo").data,
        }
        renderer = TechnicalStructureRenderer()
        for timeframe, frame in frames.items():
            technical_series[timeframe] = renderer.build_multi_timeframe_series(
                results,
                chart_timeframe=timeframe,
                date_axis=frame["date"].dt.strftime("%Y-%m-%d").tolist() if not frame.empty else [],
                options={"include_broken": True, "include_expired": True},
            )

    cards = [
        _card("概念指数涨跌", _fmt_pct(summary.get("concept_return_pct")), _tone(summary.get("concept_return_pct")),
              f"{_fmt_num(summary.get('concept_start'), 1)} → {_fmt_num(summary.get('concept_end'), 1)}"),
        _card("概念指数回撤", _fmt_pct(summary.get("concept_max_drawdown_pct")), "down",
              "等权归一化收盘价最大回撤"),
        _card("概念成交量变化", _fmt_pct(summary.get("concept_volume_change_pct")), _tone(summary.get("concept_volume_change_pct")),
              f"最新 {_fmt_num(summary.get('concept_latest_volume'), 0)}"),
        _card("最新上涨占比", f"{_fmt_num(summary.get('concept_latest_advance_ratio_pct'), 1)}%", "up" if _num(summary.get("concept_latest_advance_ratio_pct")) and _num(summary.get("concept_latest_advance_ratio_pct")) >= 50 else "down",
              f"覆盖 {summary.get('concept_latest_member_count', 0)} 只有效成员"),
        _card("MA20上方占比", f"{_fmt_num(summary.get('concept_latest_above_ma20_ratio_pct'), 1)}%", "up" if _num(summary.get("concept_latest_above_ma20_ratio_pct")) and _num(summary.get("concept_latest_above_ma20_ratio_pct")) >= 50 else "down",
              f"MA60 {_fmt_num(summary.get('concept_latest_above_ma60_ratio_pct'), 1)}%"),
        _card("20日新高/新低", f"{_fmt_num(summary.get('concept_latest_new_high_20_ratio_pct'), 1)}% / {_fmt_num(summary.get('concept_latest_new_low_20_ratio_pct'), 1)}%", "up" if _num(summary.get("concept_latest_new_high_20_ratio_pct")) and (_num(summary.get("concept_latest_new_low_20_ratio_pct")) or 0) <= _num(summary.get("concept_latest_new_high_20_ratio_pct")) else "down",
              "成员收盘价相对20日区间"),
        _card("股票数", str(summary.get("stock_count", 0)), "neutral",
              f"有效 {summary.get('valid_count', 0)} / 缺失 {summary.get('missing_count', 0)}"),
        _card("平均涨跌", _fmt_pct(summary.get("avg_return_pct")), _tone(summary.get("avg_return_pct")),
              "所有有效样本等权平均"),
        _card("中位涨跌", _fmt_pct(summary.get("median_return_pct")), _tone(summary.get("median_return_pct")),
              "降低极端个股影响"),
        _card("上涨占比", f"{_fmt_num(summary.get('positive_ratio_pct'), 1)}%", "up" if _num(summary.get("positive_ratio_pct")) and _num(summary.get("positive_ratio_pct")) >= 50 else "down",
              f"{summary.get('positive_count', 0)} / {summary.get('valid_count', 0)}"),
        _card("平均回撤", _fmt_pct(summary.get("avg_max_drawdown_pct")), "down",
              "区间内收盘价最大回撤均值"),
        _card("个股离散度", _fmt_pct(summary.get("return_std_pct")), "neutral",
              f"强弱差 {_fmt_pct(summary.get('return_spread_pct'))}"),
        _card("平均波动率", _fmt_pct(summary.get("avg_annualized_volatility_pct")), "neutral",
              f"收益/回撤 {_fmt_num(summary.get('avg_return_drawdown_ratio'))}"),
        _card("最新日分化", _fmt_pct(summary.get("concept_latest_member_return_std_pct")), "neutral",
              "成员当日涨跌标准差"),
        _card("平均量比", _fmt_num(summary.get("avg_volume_ratio")), "neutral",
              "依赖 daily_basic 本地缓存"),
        _card("最强个股", f"{summary.get('best_symbol', '')} {_fmt_pct(summary.get('best_return_pct'))}", "up",
              str(summary.get("best_name", ""))),
        _card("最弱个股", f"{summary.get('worst_symbol', '')} {_fmt_pct(summary.get('worst_return_pct'))}", "down",
              str(summary.get("worst_name", ""))),
    ]

    payload = {
        "rows": chart_rows,
        "rankRows": rank_rows,
        "heatRows": heat_rows,
        "indexRows": _index_records(concept_index),
        "pool": str(summary.get("pool", "")),
        "start": str(summary.get("start", "")),
        "end": str(summary.get("end", "")),
        "technicalSeries": technical_series,
    }

    css = """
* { box-sizing: border-box; }
body {
  margin: 0;
  background: #f3f5f8;
  color: #202438;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
}
.container { max-width: 1480px; margin: 0 auto; padding: 28px 24px 36px; }
.topbar {
  display: flex; align-items: flex-end; justify-content: space-between;
  gap: 18px; margin-bottom: 22px; padding-bottom: 16px; border-bottom: 1px solid #dfe4ec;
}
h1 { margin: 0; font-size: 26px; letter-spacing: 0; }
.subtitle { margin-top: 6px; color: #6f7787; font-size: 13px; }
.badge { color: #536dfe; background: #eef1ff; padding: 6px 12px; border-radius: 6px; font-size: 12px; font-weight: 700; white-space: nowrap; }
.stats-grid {
  display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px; margin-bottom: 16px;
}
.stat-card {
  background: #fff; border: 1px solid #e3e8f0; border-radius: 8px;
  padding: 16px 18px; min-height: 112px; box-shadow: 0 1px 4px rgba(30, 41, 59, .04);
}
.stat-label { color: #7b8494; font-size: 12px; font-weight: 700; margin-bottom: 8px; }
.stat-value { font-size: 22px; line-height: 1.2; font-weight: 760; color: #202438; word-break: break-word; }
.stat-sub { color: #9aa3b2; font-size: 12px; margin-top: 8px; min-height: 18px; }
.up .stat-value, .up { color: #ef5350; }
.down .stat-value, .down { color: #26a69a; }
.neutral .stat-value { color: #536dfe; }
.chart-grid {
  display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(0, .75fr);
  gap: 16px; margin-bottom: 16px;
}
.concept-grid {
  display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(0, .75fr);
  gap: 16px; margin-bottom: 16px;
}
.panel, .table-section {
  background: #fff; border: 1px solid #e3e8f0; border-radius: 8px;
  box-shadow: 0 1px 4px rgba(30, 41, 59, .04);
}
.panel { padding: 18px; min-height: 390px; }
.panel.full { grid-column: 1 / -1; }
.section-head {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 10px; gap: 12px;
}
.section-head h2 { margin: 0; font-size: 16px; }
.section-head span { color: #8b93a3; font-size: 12px; }
.chart { width: 100%; height: 330px; }
.chart.tall { height: 430px; }
.indicator-tabs {
  display: flex; gap: 0; margin: 0 0 8px; border-bottom: 1px solid #e7ebf2;
}
.tab-btn {
  appearance: none; background: transparent; border: 0; color: #7b8494;
  padding: 9px 14px; font-size: 13px; font-weight: 700; cursor: pointer;
  position: relative; white-space: nowrap;
}
.tab-btn::after {
  content: ""; position: absolute; left: 10px; right: 10px; bottom: -1px;
  height: 2px; background: #536dfe; transform: scaleX(0); transition: transform .16s ease;
}
.tab-btn:hover, .tab-btn.active { color: #202438; }
.tab-btn.active::after { transform: scaleX(1); }
.indicator-panel { display: none; }
.indicator-panel.active { display: block; }
.period-tabs {
  display: flex; gap: 0; margin: 0 0 8px; border-bottom: 1px solid #e7ebf2;
}
.period-tab-btn {
  appearance: none; background: transparent; border: 0; color: #7b8494;
  padding: 9px 14px; font-size: 13px; font-weight: 700; cursor: pointer;
  position: relative; white-space: nowrap;
}
.period-tab-btn::after {
  content: ""; position: absolute; left: 10px; right: 10px; bottom: -1px;
  height: 2px; background: #536dfe; transform: scaleX(0); transition: transform .16s ease;
}
.period-tab-btn:hover, .period-tab-btn.active { color: #202438; }
.period-tab-btn.active::after { transform: scaleX(1); }
.empty {
  height: 330px; display: flex; align-items: center; justify-content: center;
  color: #9aa3b2; border: 1px dashed #d8dee9; border-radius: 8px; font-size: 13px;
}
.table-section { padding: 18px; }
.table-wrap { overflow: auto; max-height: 620px; }
table { width: 100%; border-collapse: collapse; min-width: 1420px; font-size: 13px; }
th, td { padding: 9px 10px; border-bottom: 1px solid #edf0f5; text-align: right; font-variant-numeric: tabular-nums; }
th { position: sticky; top: 0; background: #f8fafc; color: #667085; font-size: 12px; cursor: pointer; z-index: 1; }
th:first-child, th:nth-child(2), td:first-child, td:nth-child(2) { text-align: left; }
td:first-child { color: #536dfe; font-weight: 700; }
a.stock-link { color: #2454a6; font-weight: 700; text-decoration: none; }
a.stock-link:hover { text-decoration: underline; }
tbody tr:hover { background: #fafcff; }
.footer { color: #a2aab8; text-align: center; font-size: 12px; margin-top: 24px; }
@media (max-width: 980px) {
  .stats-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .concept-grid { grid-template-columns: 1fr; }
  .chart-grid { grid-template-columns: 1fr; }
  .topbar { align-items: flex-start; flex-direction: column; }
}
@media (max-width: 560px) {
  .container { padding: 18px 12px 28px; }
  .stats-grid { grid-template-columns: 1fr; }
  h1 { font-size: 22px; }
}
"""

    js = f"""
var THEME_DATA = {_json(payload)};

function pct(v) {{
  if (v === null || v === undefined || Number.isNaN(v)) return '-';
  return (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
}}

function conceptZoomStart(rows) {{
  return Math.max(0, 100 - Math.max(30, 100 * 120 / Math.max(rows.length, 1)));
}}

function conceptDataZoom(rows, sliderBottom) {{
  var start = conceptZoomStart(rows);
  return [
    {{ type: 'inside', start: start, end: 100 }},
    {{ type: 'slider', height: 18, bottom: sliderBottom || 18, start: start, end: 100 }}
  ];
}}

function resampleConceptRows(rows, period) {{
  if (period === 'daily') return rows;
  var groups = {{}};
  rows.forEach(function(r) {{
    var key = r.date;
    if (period === 'weekly') key = weekKey(r.date);
    if (period === 'monthly') key = r.date.slice(0, 6);
    if (!groups[key]) groups[key] = [];
    groups[key].push(r);
  }});
  return Object.keys(groups).sort().map(function(key) {{
    var g = groups[key];
    var first = g[0], last = g[g.length - 1];
    var firstIndex = rows.indexOf(first);
    var prevClose = firstIndex > 0 ? rows[firstIndex - 1] : null;
    var volume = sum(g, 'volume');
    var amount = sum(g, 'amount');
    var advance = sum(g, 'advance_count');
    var decline = sum(g, 'decline_count');
    var flat = sum(g, 'flat_count');
    var denom = advance + decline + flat;
    return {{
      date: last.date,
      open: first.open,
      high: max(g, 'high'),
      low: min(g, 'low'),
      close: last.close,
      volume: volume,
      amount: amount,
      member_count: last.member_count,
      pct_chg: prevClose && prevClose.close ? (last.close / prevClose.close - 1) * 100 : null,
      ma5: null,
      ma20: null,
      volume_ma5: null,
      volume_ma20: null,
      amount_ma5: null,
      amount_ma20: null,
      advance_count: advance,
      decline_count: decline,
      flat_count: flat,
      advance_ratio_pct: denom ? advance / denom * 100 : null,
      above_ma20_count: last.above_ma20_count,
      above_ma20_ratio_pct: last.above_ma20_ratio_pct,
      above_ma60_count: last.above_ma60_count,
      above_ma60_ratio_pct: last.above_ma60_ratio_pct,
      new_high_20_count: last.new_high_20_count,
      new_high_20_ratio_pct: last.new_high_20_ratio_pct,
      new_low_20_count: last.new_low_20_count,
      new_low_20_ratio_pct: last.new_low_20_ratio_pct,
      member_return_std_pct: avg(g, 'member_return_std_pct')
    }};
  }}).map(function(r, idx, arr) {{
    r.ma5 = avgWindow(arr, idx, 'close', 5);
    r.ma20 = avgWindow(arr, idx, 'close', 20);
    r.volume_ma5 = avgWindow(arr, idx, 'volume', 5);
    r.volume_ma20 = avgWindow(arr, idx, 'volume', 20);
    r.amount_ma5 = avgWindow(arr, idx, 'amount', 5);
    r.amount_ma20 = avgWindow(arr, idx, 'amount', 20);
    return r;
  }});
}}

function weekKey(dateText) {{
  var y = Number(dateText.slice(0, 4));
  var m = Number(dateText.slice(4, 6)) - 1;
  var d = Number(dateText.slice(6, 8));
  var date = new Date(Date.UTC(y, m, d));
  var day = date.getUTCDay() || 7;
  date.setUTCDate(date.getUTCDate() + 4 - day);
  var yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
  var week = Math.ceil((((date - yearStart) / 86400000) + 1) / 7);
  return date.getUTCFullYear() + '-W' + String(week).padStart(2, '0');
}}

function sum(rows, field) {{
  return rows.reduce(function(total, r) {{ return total + (Number(r[field]) || 0); }}, 0);
}}

function max(rows, field) {{
  return Math.max.apply(null, rows.map(function(r) {{ return Number(r[field]); }}).filter(Number.isFinite));
}}

function min(rows, field) {{
  return Math.min.apply(null, rows.map(function(r) {{ return Number(r[field]); }}).filter(Number.isFinite));
}}

function avgWindow(rows, idx, field, size) {{
  var start = Math.max(0, idx - size + 1);
  var values = rows.slice(start, idx + 1).map(function(r) {{ return Number(r[field]); }}).filter(Number.isFinite);
  if (!values.length) return null;
  return values.reduce(function(total, v) {{ return total + v; }}, 0) / values.length;
}}

function avg(rows, field) {{
  var values = rows.map(function(r) {{ return Number(r[field]); }}).filter(Number.isFinite);
  if (!values.length) return null;
  return values.reduce(function(total, v) {{ return total + v; }}, 0) / values.length;
}}

function initReturnChart() {{
  var el = document.getElementById('returnChart');
  if (!el || THEME_DATA.rankRows.length === 0) return null;
  var rows = THEME_DATA.rankRows.slice().sort(function(a, b) {{ return a.return_pct - b.return_pct; }});
  var chart = echarts.init(el);
  chart.setOption({{
    tooltip: {{
      trigger: 'axis',
      axisPointer: {{ type: 'shadow' }},
      formatter: function(params) {{
        var p = params[0];
        var row = rows[p.dataIndex];
        return row.ts_code + ' ' + row.name + '<br/>涨跌幅: ' + pct(row.return_pct) + '<br/>最大回撤: ' + pct(row.max_drawdown_pct);
      }}
    }},
    grid: {{ left: 72, right: 28, top: 16, bottom: 28 }},
    xAxis: {{ type: 'value', axisLabel: {{ formatter: '{{value}}%' }}, splitLine: {{ lineStyle: {{ type: 'dashed', color: '#e7ebf2' }} }} }},
    yAxis: {{ type: 'category', data: rows.map(function(r) {{ return r.name || r.ts_code; }}), axisLabel: {{ width: 86, overflow: 'truncate' }} }},
    series: [{{
      type: 'bar',
      data: rows.map(function(r) {{ return {{ value: r.return_pct, itemStyle: {{ color: r.return_pct >= 0 ? '#ef5350' : '#26a69a' }} }}; }}),
      barMaxWidth: 18,
      label: {{ show: true, position: 'right', formatter: function(p) {{ return pct(p.value); }}, fontSize: 11 }}
    }}]
  }});
  return chart;
}}

function initConceptKlineChart(period) {{
  var el = document.getElementById('conceptKlineChart');
  if (!el) return null;
  if (THEME_DATA.indexRows.length === 0) {{
    el.className = 'empty';
    el.innerHTML = '区间内有效成员 K 线不足，暂无概念指数';
    return null;
  }}
  var rows = resampleConceptRows(THEME_DATA.indexRows, period || 'daily');
  var timeframe = period === 'weekly' ? '1w' : (period === 'monthly' ? '1mo' : '1d');
  var structureSeries = (THEME_DATA.technicalSeries && THEME_DATA.technicalSeries[timeframe]) || [];
  var legendNames = ['概念指数', 'MA5', 'MA20'];
  var selected = {{}};
  structureSeries.forEach(function(item) {{ if(item.name) {{ legendNames.push(item.name); if(item.technicalStructureStatus && item.technicalStructureStatus !== 'active' && item.technicalStructureStatus !== 'role_reversal') selected[item.name] = false; }} }});
  var chart = echarts.init(el);
  chart.setOption({{
    tooltip: {{
      trigger: 'axis',
      axisPointer: {{ type: 'cross' }},
      formatter: function(params) {{
        var row = rows[params[0].dataIndex];
        return row.date + '<br/>开: ' + row.open.toFixed(2) +
          ' 高: ' + row.high.toFixed(2) +
          '<br/>低: ' + row.low.toFixed(2) +
          ' 收: ' + row.close.toFixed(2) +
          '<br/>涨跌: ' + pct(row.pct_chg) +
          '<br/>有效成员: ' + row.member_count;
      }}
    }},
    legend: {{ type: 'scroll', top: 0, left: 24, right: 24, data: legendNames, selected: selected }},
    grid: {{ left: 58, right: 24, top: 42, bottom: 72 }},
    dataZoom: conceptDataZoom(rows, 22),
    xAxis: {{ type: 'category', data: rows.map(function(r) {{ return r.date; }}), boundaryGap: true, axisLabel: {{ hideOverlap: true }} }},
    yAxis: {{ type: 'value', scale: true, splitLine: {{ lineStyle: {{ type: 'dashed', color: '#e7ebf2' }} }} }},
    series: [
      {{
        name: '概念指数',
        type: 'candlestick',
        data: rows.map(function(r) {{ return [r.open, r.close, r.low, r.high]; }}),
        itemStyle: {{ color: '#ef5350', color0: '#26a69a', borderColor: '#ef5350', borderColor0: '#26a69a' }}
      }},
      {{ name: 'MA5', type: 'line', data: rows.map(function(r) {{ return r.ma5; }}), smooth: true, showSymbol: false, lineStyle: {{ width: 1.5, color: '#f59e0b' }} }},
      {{ name: 'MA20', type: 'line', data: rows.map(function(r) {{ return r.ma20; }}), smooth: true, showSymbol: false, lineStyle: {{ width: 1.5, color: '#536dfe' }} }}
    ].concat(structureSeries)
  }});
  return chart;
}}

function initConceptVolumeChart(period) {{
  var el = document.getElementById('conceptVolumeChart');
  if (!el) return null;
  if (THEME_DATA.indexRows.length === 0) {{
    el.className = 'empty';
    el.innerHTML = '暂无概念成交量数据';
    return null;
  }}
  var rows = resampleConceptRows(THEME_DATA.indexRows, period || 'daily');
  var chart = echarts.init(el);
  chart.setOption({{
    tooltip: {{ trigger: 'axis' }},
    legend: {{ top: 0, data: ['成交量', '量MA5', '量MA20'] }},
    grid: {{ left: 62, right: 22, top: 42, bottom: 58 }},
    xAxis: {{ type: 'category', data: rows.map(function(r) {{ return r.date; }}), axisLabel: {{ hideOverlap: true }} }},
    yAxis: {{ type: 'value', splitLine: {{ lineStyle: {{ type: 'dashed', color: '#e7ebf2' }} }} }},
    dataZoom: conceptDataZoom(rows, 14),
    series: [
      {{ name: '成交量', type: 'bar', data: rows.map(function(r) {{ return r.volume; }}), itemStyle: {{ color: '#8fb3ff' }}, barMaxWidth: 18 }},
      {{ name: '量MA5', type: 'line', data: rows.map(function(r) {{ return r.volume_ma5; }}), smooth: true, showSymbol: false, lineStyle: {{ color: '#f59e0b', width: 1.4 }} }},
      {{ name: '量MA20', type: 'line', data: rows.map(function(r) {{ return r.volume_ma20; }}), smooth: true, showSymbol: false, lineStyle: {{ color: '#536dfe', width: 1.4 }} }}
    ]
  }});
  return chart;
}}

function initConceptAmountChart(period) {{
  var el = document.getElementById('conceptAmountChart');
  if (!el) return null;
  if (THEME_DATA.indexRows.length === 0) {{
    el.className = 'empty';
    el.innerHTML = '暂无概念成交金额数据';
    return null;
  }}
  var rows = resampleConceptRows(THEME_DATA.indexRows, period || 'daily');
  var chart = echarts.init(el);
  chart.setOption({{
    tooltip: {{ trigger: 'axis' }},
    legend: {{ top: 0, data: ['成交金额', '额MA5', '额MA20'] }},
    grid: {{ left: 62, right: 22, top: 42, bottom: 58 }},
    xAxis: {{ type: 'category', data: rows.map(function(r) {{ return r.date; }}), axisLabel: {{ hideOverlap: true }} }},
    yAxis: {{ type: 'value', splitLine: {{ lineStyle: {{ type: 'dashed', color: '#e7ebf2' }} }} }},
    dataZoom: conceptDataZoom(rows, 14),
    series: [
      {{ name: '成交金额', type: 'bar', data: rows.map(function(r) {{ return r.amount; }}), itemStyle: {{ color: '#a78bfa' }}, barMaxWidth: 18 }},
      {{ name: '额MA5', type: 'line', data: rows.map(function(r) {{ return r.amount_ma5; }}), smooth: true, showSymbol: false, lineStyle: {{ color: '#f59e0b', width: 1.4 }} }},
      {{ name: '额MA20', type: 'line', data: rows.map(function(r) {{ return r.amount_ma20; }}), smooth: true, showSymbol: false, lineStyle: {{ color: '#536dfe', width: 1.4 }} }}
    ]
  }});
  return chart;
}}

function initBreadthChart(period) {{
  var el = document.getElementById('breadthChart');
  if (!el) return null;
  if (THEME_DATA.indexRows.length === 0) {{
    el.className = 'empty';
    el.innerHTML = '暂无涨跌家数数据';
    return null;
  }}
  var rows = resampleConceptRows(THEME_DATA.indexRows, period || 'daily');
  var chart = echarts.init(el);
  chart.setOption({{
    tooltip: {{ trigger: 'axis' }},
    legend: {{ top: 0, data: ['上涨家数', '下跌家数', '上涨占比'] }},
    grid: {{ left: 48, right: 48, top: 42, bottom: 58 }},
    xAxis: {{ type: 'category', data: rows.map(function(r) {{ return r.date; }}), axisLabel: {{ hideOverlap: true }} }},
    yAxis: [
      {{ type: 'value', name: '家数', minInterval: 1, splitLine: {{ lineStyle: {{ type: 'dashed', color: '#e7ebf2' }} }} }},
      {{ type: 'value', name: '占比%', min: 0, max: 100, axisLabel: {{ formatter: '{{value}}%' }} }}
    ],
    dataZoom: conceptDataZoom(rows, 14),
    series: [
      {{ name: '上涨家数', type: 'bar', stack: 'breadth', data: rows.map(function(r) {{ return r.advance_count; }}), itemStyle: {{ color: '#ef5350' }}, barMaxWidth: 18 }},
      {{ name: '下跌家数', type: 'bar', stack: 'breadth', data: rows.map(function(r) {{ return r.decline_count; }}), itemStyle: {{ color: '#26a69a' }}, barMaxWidth: 18 }},
      {{ name: '上涨占比', type: 'line', yAxisIndex: 1, data: rows.map(function(r) {{ return r.advance_ratio_pct; }}), smooth: true, showSymbol: false, lineStyle: {{ color: '#111827', width: 1.6 }} }}
    ]
  }});
  return chart;
}}

function initTrendBreadthChart(period) {{
  var el = document.getElementById('trendBreadthChart');
  if (!el) return null;
  if (THEME_DATA.indexRows.length === 0) {{
    el.className = 'empty';
    el.innerHTML = '暂无趋势广度数据';
    return null;
  }}
  var rows = resampleConceptRows(THEME_DATA.indexRows, period || 'daily');
  var chart = echarts.init(el);
  chart.setOption({{
    tooltip: {{ trigger: 'axis' }},
    legend: {{ top: 0, data: ['MA20上方占比', 'MA60上方占比', '20日新高家数', '20日新低家数', '日涨跌离散'] }},
    grid: {{ left: 48, right: 52, top: 48, bottom: 58 }},
    xAxis: {{ type: 'category', data: rows.map(function(r) {{ return r.date; }}), axisLabel: {{ hideOverlap: true }} }},
    yAxis: [
      {{ type: 'value', name: '占比%', min: 0, max: 100, axisLabel: {{ formatter: '{{value}}%' }}, splitLine: {{ lineStyle: {{ type: 'dashed', color: '#e7ebf2' }} }} }},
      {{ type: 'value', name: '家数/离散', minInterval: 1 }}
    ],
    dataZoom: conceptDataZoom(rows, 14),
    series: [
      {{ name: 'MA20上方占比', type: 'line', data: rows.map(function(r) {{ return r.above_ma20_ratio_pct; }}), smooth: true, showSymbol: false, lineStyle: {{ color: '#ef5350', width: 1.6 }} }},
      {{ name: 'MA60上方占比', type: 'line', data: rows.map(function(r) {{ return r.above_ma60_ratio_pct; }}), smooth: true, showSymbol: false, lineStyle: {{ color: '#536dfe', width: 1.6 }} }},
      {{ name: '20日新高家数', type: 'bar', yAxisIndex: 1, data: rows.map(function(r) {{ return r.new_high_20_count; }}), itemStyle: {{ color: '#f59e0b' }}, barMaxWidth: 14 }},
      {{ name: '20日新低家数', type: 'bar', yAxisIndex: 1, data: rows.map(function(r) {{ return -r.new_low_20_count; }}), itemStyle: {{ color: '#26a69a' }}, barMaxWidth: 14 }},
      {{ name: '日涨跌离散', type: 'line', yAxisIndex: 1, data: rows.map(function(r) {{ return r.member_return_std_pct; }}), smooth: true, showSymbol: false, lineStyle: {{ color: '#111827', width: 1.4, type: 'dashed' }} }}
    ]
  }});
  return chart;
}}

function initScatterChart() {{
  var el = document.getElementById('scatterChart');
  if (!el || THEME_DATA.rows.length === 0) return null;
  var chart = echarts.init(el);
  chart.setOption({{
    tooltip: {{
      formatter: function(p) {{
        var r = p.data.raw;
        return r.ts_code + ' ' + r.name + '<br/>涨跌幅: ' + pct(r.return_pct) + '<br/>最大回撤: ' + pct(r.max_drawdown_pct);
      }}
    }},
    grid: {{ left: 52, right: 20, top: 16, bottom: 42 }},
    xAxis: {{ type: 'value', name: '最大回撤%', axisLabel: {{ formatter: '{{value}}%' }}, splitLine: {{ lineStyle: {{ type: 'dashed', color: '#e7ebf2' }} }} }},
    yAxis: {{ type: 'value', name: '涨跌幅%', axisLabel: {{ formatter: '{{value}}%' }}, splitLine: {{ lineStyle: {{ type: 'dashed', color: '#e7ebf2' }} }} }},
    series: [{{
      type: 'scatter',
      symbolSize: function(data) {{ return Math.max(8, Math.min(22, Math.abs(data[1]) / 2 + 8)); }},
      data: THEME_DATA.rows.map(function(r) {{ return {{ value: [r.max_drawdown_pct, r.return_pct], raw: r, itemStyle: {{ color: r.return_pct >= 0 ? '#ef5350' : '#26a69a', opacity: .82 }} }}; }}),
      label: {{ show: true, formatter: function(p) {{ return p.data.raw.name || p.data.raw.ts_code; }}, position: 'top', fontSize: 10 }}
    }}]
  }});
  return chart;
}}

function initHeatChart() {{
  var el = document.getElementById('heatChart');
  if (!el) return null;
  if (THEME_DATA.heatRows.length === 0) {{
    el.className = 'empty';
    el.innerHTML = '本地区间 daily_basic 指标不足，暂无换手率/量比图';
    return null;
  }}
  var rows = THEME_DATA.heatRows.slice().sort(function(a, b) {{
    return (b.avg_turnover_rate || 0) - (a.avg_turnover_rate || 0);
  }});
  var chart = echarts.init(el);
  chart.setOption({{
    tooltip: {{ trigger: 'axis' }},
    legend: {{ top: 0 }},
    grid: {{ left: 52, right: 24, top: 44, bottom: 72 }},
    xAxis: {{ type: 'category', data: rows.map(function(r) {{ return r.name || r.ts_code; }}), axisLabel: {{ rotate: 35, width: 80, overflow: 'truncate' }} }},
    yAxis: {{ type: 'value', splitLine: {{ lineStyle: {{ type: 'dashed', color: '#e7ebf2' }} }} }},
    series: [
      {{ name: '平均换手', type: 'bar', data: rows.map(function(r) {{ return r.avg_turnover_rate; }}), itemStyle: {{ color: '#5470c6' }}, barMaxWidth: 22 }},
      {{ name: '平均量比', type: 'bar', data: rows.map(function(r) {{ return r.avg_volume_ratio; }}), itemStyle: {{ color: '#fac858' }}, barMaxWidth: 22 }}
    ]
  }});
  return chart;
}}

function initStrengthChart() {{
  var el = document.getElementById('strengthChart');
  if (!el || THEME_DATA.rows.length === 0) return null;
  var rows = THEME_DATA.rows.slice().sort(function(a, b) {{
    return (b.latest_close_vs_ma20_pct || -999) - (a.latest_close_vs_ma20_pct || -999);
  }});
  var chart = echarts.init(el);
  chart.setOption({{
    tooltip: {{
      trigger: 'axis',
      formatter: function(params) {{
        var row = rows[params[0].dataIndex];
        return row.ts_code + ' ' + row.name +
          '<br/>距MA20: ' + pct(row.latest_close_vs_ma20_pct) +
          '<br/>距MA60: ' + pct(row.latest_close_vs_ma60_pct) +
          '<br/>20日量能: ' + (row.latest_volume_ratio_20 == null ? '-' : row.latest_volume_ratio_20.toFixed(2)) +
          '<br/>年化波动: ' + pct(row.annualized_volatility_pct);
      }}
    }},
    legend: {{ top: 0, data: ['距MA20', '距MA60', '20日量能'] }},
    grid: {{ left: 54, right: 46, top: 44, bottom: 88 }},
    xAxis: {{ type: 'category', data: rows.map(function(r) {{ return r.name || r.ts_code; }}), axisLabel: {{ rotate: 35, width: 80, overflow: 'truncate' }} }},
    yAxis: [
      {{ type: 'value', name: '偏离%', axisLabel: {{ formatter: '{{value}}%' }}, splitLine: {{ lineStyle: {{ type: 'dashed', color: '#e7ebf2' }} }} }},
      {{ type: 'value', name: '量能' }}
    ],
    series: [
      {{ name: '距MA20', type: 'bar', data: rows.map(function(r) {{ return r.latest_close_vs_ma20_pct; }}), itemStyle: {{ color: '#ef5350' }}, barMaxWidth: 18 }},
      {{ name: '距MA60', type: 'bar', data: rows.map(function(r) {{ return r.latest_close_vs_ma60_pct; }}), itemStyle: {{ color: '#8fb3ff' }}, barMaxWidth: 18 }},
      {{ name: '20日量能', type: 'line', yAxisIndex: 1, data: rows.map(function(r) {{ return r.latest_volume_ratio_20; }}), smooth: true, showSymbol: false, lineStyle: {{ color: '#111827', width: 1.6 }} }}
    ]
  }});
  return chart;
}}

var conceptCharts = [];
var currentConceptPeriod = 'daily';
var otherCharts = [];

function allCharts() {{
  return conceptCharts.concat(otherCharts).filter(Boolean);
}}

function initConceptCharts(period) {{
  conceptCharts.forEach(function(c) {{ try {{ c.dispose(); }} catch (e) {{}} }});
  conceptCharts = [
    initConceptKlineChart(period),
    initConceptVolumeChart(period),
    initConceptAmountChart(period),
    initBreadthChart(period),
    initTrendBreadthChart(period)
  ].filter(Boolean);
  conceptCharts.forEach(function(c) {{ c.group = 'theme-concept-index'; }});
  if (conceptCharts.length > 1) echarts.connect('theme-concept-index');
  return conceptCharts;
}}

initConceptCharts(currentConceptPeriod);

otherCharts = [
  initReturnChart(),
  initScatterChart(),
  initStrengthChart(),
  initHeatChart()
].filter(Boolean);
window.addEventListener('resize', function() {{ allCharts().forEach(function(c) {{ c.resize(); }}); }});

function resizeVisibleCharts(container) {{
  setTimeout(function() {{
    allCharts().forEach(function(c) {{
      try {{
        var dom = c.getDom();
        if (dom && container.contains(dom)) c.resize();
      }} catch (e) {{}}
    }});
  }}, 80);
}}

function switchThemeIndicator(btn, targetId) {{
  var section = btn.closest('.indicator-switcher');
  if (!section) return;
  section.querySelectorAll('.tab-btn').forEach(function(item) {{ item.classList.remove('active'); }});
  section.querySelectorAll('.indicator-panel').forEach(function(panel) {{ panel.classList.remove('active'); }});
  btn.classList.add('active');
  var panel = document.getElementById(targetId);
  if (panel) {{
    panel.classList.add('active');
    resizeVisibleCharts(panel);
  }}
}}
window.switchThemeIndicator = switchThemeIndicator;

function switchConceptPeriod(btn, period) {{
  document.querySelectorAll('.period-tab-btn').forEach(function(item) {{ item.classList.remove('active'); }});
  btn.classList.add('active');
  currentConceptPeriod = period;
  initConceptCharts(period);
  var activePanel = document.querySelector('.indicator-switcher .indicator-panel.active');
  if (activePanel) resizeVisibleCharts(activePanel);
}}
window.switchConceptPeriod = switchConceptPeriod;

(function initSort() {{
  var table = document.getElementById('detailTable');
  if (!table) return;
  var tbody = table.querySelector('tbody');
  Array.from(table.querySelectorAll('th')).forEach(function(th, idx) {{
    th.addEventListener('click', function() {{
      var asc = th.getAttribute('data-sort-dir') !== 'asc';
      Array.from(table.querySelectorAll('th')).forEach(function(h) {{ h.removeAttribute('data-sort-dir'); }});
      th.setAttribute('data-sort-dir', asc ? 'asc' : 'desc');
      var rows = Array.from(tbody.querySelectorAll('tr'));
      rows.sort(function(a, b) {{
        var av = a.children[idx].getAttribute('data-sort') || a.children[idx].textContent.trim();
        var bv = b.children[idx].getAttribute('data-sort') || b.children[idx].textContent.trim();
        var an = parseFloat(av), bn = parseFloat(bv);
        var result = (!Number.isNaN(an) && !Number.isNaN(bn)) ? an - bn : av.localeCompare(bv);
        return asc ? result : -result;
      }});
      rows.forEach(function(row) {{ tbody.appendChild(row); }});
    }});
  }});
}})();
"""

    body = f"""<main class="container">
    <header class="topbar">
      <div>
        <h1>{html.escape(str(summary.get("pool", "")))} 题材涨跌看板</h1>
        <div class="subtitle">{html.escape(str(summary.get("start", "")))} ~ {html.escape(str(summary.get("end", "")))} · 数据来自本地 K 线缓存和 daily_basic 缓存</div>
      </div>
      <div class="badge">Generated {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
    </header>

    <section class="stats-grid">{''.join(cards)}</section>

    <section class="concept-grid">
      <div class="panel">
        <div class="section-head"><h2>概念指数 K 线</h2><span>股票缓存完整区间；摘要按上方日期统计</span></div>
        <div class="period-tabs">
          <button class="period-tab-btn active" onclick="switchConceptPeriod(this,'daily')">日线</button>
          <button class="period-tab-btn" onclick="switchConceptPeriod(this,'weekly')">周线</button>
          <button class="period-tab-btn" onclick="switchConceptPeriod(this,'monthly')">月线</button>
        </div>
        <div id="conceptKlineChart" class="chart tall"></div>
      </div>
      <div class="panel indicator-switcher">
        <div class="section-head"><h2>概念指标</h2><span>与 K 线缩放联动</span></div>
        <div class="indicator-tabs">
          <button class="tab-btn active" onclick="switchThemeIndicator(this,'panel-concept-volume')">成交量</button>
          <button class="tab-btn" onclick="switchThemeIndicator(this,'panel-concept-amount')">成交金额</button>
          <button class="tab-btn" onclick="switchThemeIndicator(this,'panel-concept-breadth')">涨跌家数</button>
          <button class="tab-btn" onclick="switchThemeIndicator(this,'panel-concept-trend')">趋势广度</button>
        </div>
        <div id="panel-concept-volume" class="indicator-panel active"><div id="conceptVolumeChart" class="chart"></div></div>
        <div id="panel-concept-amount" class="indicator-panel"><div id="conceptAmountChart" class="chart"></div></div>
        <div id="panel-concept-breadth" class="indicator-panel"><div id="breadthChart" class="chart"></div></div>
        <div id="panel-concept-trend" class="indicator-panel"><div id="trendBreadthChart" class="chart"></div></div>
      </div>
    </section>

    <section class="chart-grid">
      <div class="panel">
        <div class="section-head"><h2>个股涨跌排行</h2><span>{html.escape(str(summary.get("start", "")))} ~ {html.escape(str(summary.get("end", "")))} · 涨幅前7 / 跌幅后5</span></div>
        <div id="returnChart" class="chart"></div>
      </div>
      <div class="panel">
        <div class="section-head"><h2>收益 - 回撤分布</h2><span>越靠左上越强</span></div>
        <div id="scatterChart" class="chart"></div>
      </div>
      <div class="panel full">
        <div class="section-head"><h2>趋势强弱</h2><span>按距 MA20 排序；量能=最新成交量/20日均量</span></div>
        <div id="strengthChart" class="chart"></div>
      </div>
      <div class="panel full">
        <div class="section-head"><h2>热度指标</h2><span>依赖 daily-basic 数据</span></div>
        <div id="heatChart" class="chart"></div>
      </div>
    </section>

    {_build_table(details, output_path, config)}

    <div class="footer">QuantYB · Theme Analytics</div>
  </main>"""
    document = html_document(
        title=f"{summary.get('pool', '')} — 题材涨跌看板",
        body=body,
        styles=css,
        head_extra=echarts_script_tag(
            ECHARTS_SRC,
            Path(__file__).resolve().parents[1] / "visual" / "assets" / "echarts.min.js",
        ),
        scripts=inline_script(js),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(document, encoding="utf-8")
