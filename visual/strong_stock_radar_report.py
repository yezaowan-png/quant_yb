"""HTML report for the research-only strong-stock radar."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

import pandas as pd

from analysis.strong_stock_radar import build_evaluation_summary, radar_config
from visual.components import html_document, json_script_data, stock_link_html
from visual.index_report import _echarts_script_tag


STATE_LABELS = {
    "CORE_STRONG": "核心强势",
    "ACCELERATING": "加速走强",
    "HIGH_TIGHT": "高位蓄势",
    "BREAKOUT": "突破确认",
    "STRONG_WEAKENING": "强势转弱",
    "WATCH": "观察",
}


ROTATION_HELPERS_JS = r"""
const ROTATION_METRICS = {
  industry_rs5_pct: { label: 'RS5', deltaField: 'industry_rs5_pct_delta_5d_common' },
  industry_rs10_pct: { label: 'RS10', deltaField: 'industry_rs10_pct_delta_5d_common' },
  industry_rs20_pct: { label: 'RS20', deltaField: 'industry_rs20_pct_delta_5d_common' },
  industry_rs60_pct: { label: 'RS60', deltaField: 'industry_rs60_pct_delta_5d_common' },
  industry_rs120_pct: { label: 'RS120', deltaField: 'industry_rs120_pct_delta_5d_common' }
};
function finiteOrNull(value) {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}
function rotationMetric(metric) {
  return { field: metric, ...(ROTATION_METRICS[metric] || ROTATION_METRICS.industry_rs60_pct) };
}
function signedNumber(value) {
  const number = finiteOrNull(value);
  return number === null ? '--' : (number >= 0 ? '+' : '') + number.toFixed(2);
}
function sortRotationRows(rows, field, ascending) {
  return rows.slice().sort((left, right) => {
    const leftValue = finiteOrNull(left[field]);
    const rightValue = finiteOrNull(right[field]);
    if (leftValue === null && rightValue === null) return String(left.industry).localeCompare(String(right.industry), 'zh-CN');
    if (leftValue === null) return 1;
    if (rightValue === null) return -1;
    if (leftValue !== rightValue) return ascending ? leftValue - rightValue : rightValue - leftValue;
    return String(left.industry).localeCompare(String(right.industry), 'zh-CN');
  });
}
function rankRotationRows(rows, field) {
  const sorted = sortRotationRows(rows, field, false);
  const rankByIndustry = {};
  let start = 0;
  while (start < sorted.length) {
    const value = finiteOrNull(sorted[start][field]);
    let end = start + 1;
    while (end < sorted.length && finiteOrNull(sorted[end][field]) === value) end += 1;
    for (let index = start; index < end; index += 1) rankByIndustry[sorted[index].industry] = end;
    start = end;
  }
  return { rows: sorted, rankByIndustry };
}
function comparisonState(history, metric, requestedDate) {
  const config = rotationMetric(metric);
  const dates = [...new Set(history.map(row => row.trade_date).filter(Boolean))].sort().reverse();
  const orderedDates = dates.slice().reverse().filter(date => history.some(row => row.trade_date === date && row.industry !== '未分类' && finiteOrNull(row[config.field]) !== null));
  const cutoffDate = requestedDate && orderedDates.includes(requestedDate)
    ? requestedDate
    : orderedDates.slice(-1)[0] || '';
  const cutoffIndex = orderedDates.indexOf(cutoffDate);
  const previousDate = cutoffIndex >= 5 ? orderedDates[cutoffIndex - 5] : '';
  const allRows = history.filter(row => row.trade_date === cutoffDate && row.industry !== '未分类');
  const validRows = allRows.filter(row => finiteOrNull(row[config.field]) !== null);
  const previousRows = history.filter(row => row.trade_date === previousDate && row.industry !== '未分类' && finiteOrNull(row[config.field]) !== null);
  const currentRanking = rankRotationRows(validRows, config.field);
  const previousRanking = rankRotationRows(previousRows, config.field);
  const currentByIndustry = Object.fromEntries(validRows.map(row => [row.industry, row]));
  const previousByIndustry = Object.fromEntries(previousRows.map(row => [row.industry, row]));
  const comparisonByIndustry = {};
  validRows.forEach(row => {
    const previous = previousByIndustry[row.industry];
    if (!previous) return;
    const currentValue = finiteOrNull(row[config.field]);
    const previousValue = finiteOrNull(previous[config.field]);
    if (currentValue === null || previousValue === null) return;
    comparisonByIndustry[row.industry] = {
      previousDate,
      previousValue,
      previousRank: previousRanking.rankByIndustry[row.industry],
      previousCount: previousRanking.rows.length,
      delta: currentValue - previousValue,
      rankChange: previousRanking.rankByIndustry[row.industry] - currentRanking.rankByIndustry[row.industry],
    };
  });
  return { config, cutoffDate, previousDate, allRows, validRows, rankedRows: currentRanking.rows, validCount: currentRanking.rows.length, rankByIndustry: currentRanking.rankByIndustry, currentByIndustry, previousByIndustry, comparisonByIndustry };
}
function rotationState(history, metric) {
  const primary = comparisonState(history, metric);
  const rs20 = comparisonState(history, 'industry_rs20_pct', primary.cutoffDate);
  const dailyRanking = rankRotationRows(primary.allRows.filter(row => finiteOrNull(row.industry_daily_return) !== null), 'industry_daily_return');
  return { ...primary, dailyRows: dailyRanking.rows, dailyRankByIndustry: dailyRanking.rankByIndustry, rs20ComparisonByIndustry: rs20.comparisonByIndustry };
}
function rotationCategory(row, state) {
  const rs = finiteOrNull(row[state.config.field]);
  const comparison = state.comparisonByIndustry[row.industry];
  if (rs === null || !comparison) return '暂无统一比较日期的有效数据';
  if (rs >= 80 && comparison.rankChange > 0) return '高位继续增强';
  if (rs < 50 && comparison.rankChange > 0) return '低位改善观察';
  if (comparison.rankChange > 0) return '中位改善';
  if (rs >= 80 && comparison.rankChange < 0) return '高位回落';
  if (comparison.rankChange < 0) return '排名走弱';
  return '名次不变';
}
function filteredRotationRows(state, filter, watchlist, minRankChange) {
  const { field } = state.config;
  const rows = state.validRows;
  const comparison = row => state.comparisonByIndustry[row.industry];
  const improving = row => comparison(row) && comparison(row).rankChange >= minRankChange;
  const weakening = row => comparison(row) && comparison(row).rankChange <= -minRankChange;
  const compareImprovement = (left, right) => {
    const leftComparison = comparison(left), rightComparison = comparison(right);
    if (leftComparison.delta !== rightComparison.delta) return rightComparison.delta - leftComparison.delta;
    if (leftComparison.rankChange !== rightComparison.rankChange) return rightComparison.rankChange - leftComparison.rankChange;
    return String(left.industry).localeCompare(String(right.industry), 'zh-CN');
  };
  if (filter === 'currentStrong') return sortRotationRows(rows, field, false).slice(0, 15);
  if (filter === 'improving') return rows.filter(improving).sort(compareImprovement).slice(0, 15);
  if (filter === 'strengthening') return rows.filter(row => finiteOrNull(row[field]) >= 80 && improving(row)).sort(compareImprovement);
  if (filter === 'lowImproving') return rows.filter(row => finiteOrNull(row[field]) < 50 && improving(row)).sort(compareImprovement);
  if (filter === 'weakening') return rows.filter(row => finiteOrNull(row[field]) >= 80 && weakening(row)).sort((left, right) => {
    const leftComparison = comparison(left), rightComparison = comparison(right);
    if (leftComparison.rankChange !== rightComparison.rankChange) return leftComparison.rankChange - rightComparison.rankChange;
    if (leftComparison.delta !== rightComparison.delta) return leftComparison.delta - rightComparison.delta;
    return String(left.industry).localeCompare(String(right.industry), 'zh-CN');
  });
  if (filter === 'shortTerm') {
    const dailyLimit = Math.ceil(state.dailyRows.length / 2);
    return state.allRows.filter(row => {
      const rs5 = finiteOrNull(row.industry_rs5_pct);
      const rs20Comparison = state.rs20ComparisonByIndustry[row.industry];
      const advancing = finiteOrNull(row.pct_advancing);
      const dailyRank = state.dailyRankByIndustry[row.industry];
      return rs5 !== null && rs5 >= 60 && rs20Comparison && rs20Comparison.delta > 0
        && dailyRank !== undefined && dailyRank <= dailyLimit && advancing !== null && advancing >= 0.5;
    }).sort((left, right) => {
      const leftValue = state.comparisonByIndustry[left.industry].delta;
      const rightValue = state.comparisonByIndustry[right.industry].delta;
      return rightValue - leftValue || String(left.industry).localeCompare(String(right.industry), 'zh-CN');
    });
  }
  if (filter === 'watchlist') return sortRotationRows(rows.filter(row => watchlist.includes(row.industry)), field, false);
  return state.rankedRows;
}
"""


def heatmap_color_band(value: Any) -> str:
    """Fixed industry-RS heatmap palette; missing values stay visually distinct."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "missing"
    if pd.isna(number):
        return "missing"
    if number < 20:
        return "weak"
    if number < 40:
        return "weakish"
    if number < 60:
        return "neutral"
    if number < 80:
        return "upper"
    return "strong"


def _num(value: Any, digits: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"
    if pd.isna(number):
        return "--"
    return f"{number:.{digits}f}"


def _pct(value: Any, digits: int = 1) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"
    if pd.isna(number):
        return "--"
    return f"{number * 100:.{digits}f}%"


def _signed_pct(value: Any, digits: int = 1) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"
    if pd.isna(number):
        return "--"
    return f"{number * 100:+.{digits}f}%"


def _state_label(value: Any) -> str:
    state = str(value or "")
    return STATE_LABELS.get(state, state or "--")


def _safe_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return html.escape(str(value))


def _market_environment_card(market_environment: dict[str, Any]) -> tuple[str, str, str]:
    breadth = str(market_environment.get("breadth_state") or "").strip()
    style = str(market_environment.get("style_regime_name") or "").strip()
    liquidity = str(market_environment.get("liquidity_state") or "").strip()
    date = str(market_environment.get("date") or "").strip()
    value_parts = []
    if breadth:
        value_parts.append(f"广度 {breadth}")
    if style:
        value_parts.append(style)
    if not value_parts:
        value_parts.append("--")
    note = f"流动性 {liquidity}" if liquidity else date
    return "市场环境", " / ".join(value_parts), note or date


def _metric_cards(stocks: pd.DataFrame, industry: pd.DataFrame, market_environment: dict[str, Any]) -> str:
    counts = stocks.get("state", pd.Series(dtype=str)).value_counts().to_dict() if not stocks.empty else {}
    strong_industries = 0
    if not industry.empty and "industry_state" in industry.columns:
        strong_industries = int(industry["industry_state"].isin(["STRONG", "STRENGTHENING"]).sum())
    cards = [
        _market_environment_card(market_environment),
        ("强势行业", str(strong_industries), "STRONG / STRENGTHENING"),
        ("CORE_STRONG", str(int(counts.get("CORE_STRONG", 0))), "持续强势"),
        ("ACCELERATING", str(int(counts.get("ACCELERATING", 0))), "正在增强"),
        ("HIGH_TIGHT", str(int(counts.get("HIGH_TIGHT", 0))), "高位收缩"),
        ("BREAKOUT", str(int(counts.get("BREAKOUT", 0))), "突破确认"),
        ("STRONG_WEAKENING", str(int(counts.get("STRONG_WEAKENING", 0))), "旧强转弱"),
    ]
    return "".join(
        "<article class='metric'>"
        f"<span>{html.escape(title)}</span>"
        f"<strong>{html.escape(value)}</strong>"
        f"<small>{html.escape(note)}</small>"
        "</article>"
        for title, value, note in cards
    )


def _delta_label(value: Any, up: float, down: float) -> str:
    number = _num(value)
    if number == "--":
        return "--"
    direction = "↑" if float(value) >= up else "↓" if float(value) <= down else "→"
    return f"{float(value):+.2f} {direction}"


def _sparkline(history: pd.DataFrame, industry: str) -> str:
    series = history[history["industry"] == industry].tail(20) if not history.empty else pd.DataFrame()
    values = pd.to_numeric(series.get("industry_rs60_pct"), errors="coerce") if not series.empty else pd.Series(dtype=float)
    points = []
    for index, (date, value) in enumerate(zip(series.get("trade_date", []), values)):
        if pd.notna(value):
            points.append(f"{index * 4 + 2:.1f},{22 - float(value) * .2:.1f}")
    title = "；".join(f"{date}: {value:.2f}" for date, value in zip(series.get("trade_date", []), values) if pd.notna(value))
    return f"<svg class='spark' viewBox='0 0 80 24' title='{html.escape(title, quote=True)}'><polyline points='{','.join(points)}'/></svg>"


def _industry_table(industry: pd.DataFrame, history: pd.DataFrame, config: dict) -> str:
    if industry.empty:
        return "<p class='empty'>暂无行业强度数据</p>"
    columns = [
        ("industry", "行业", str),
        ("industry_rs5_pct", "RS5", _num),
        ("industry_rs10_pct", "RS10", _num),
        ("industry_rs20_pct", "RS20", _num),
        ("industry_rs60_pct", "RS60", _num),
        ("industry_rs120_pct", "RS120", _num),
        ("industry_rs60_pct_delta_5d", "RS60排名5D", _num),
        ("industry_rs60_pct_delta_10d", "RS60排名10D", _num),
        ("industry_rs60_persistence_20d", "RS60持续率20D", _pct),
        ("industry_rs60_trend", "RS60趋势", str),
        ("pct_above_ma10", "MA10以上", _pct),
        ("pct_above_ma20", "MA20以上", _pct),
        ("pct_new_high_20d", "20日新高", _pct),
        ("industry_state", "状态", str),
    ]
    rows = []
    for _, row in industry.iterrows():
        cells = []
        for col, _, formatter in columns:
            value = row.get(col)
            if col == "industry":
                text = _safe_text(value)
                cells.append(f"<td><button class='link-filter' data-industry='{text}'>{text}</button></td>")
            elif col == "industry_state":
                cells.append(f"<td><span class='badge state-{html.escape(str(value))}'>{html.escape(str(value or '--'))}</span></td>")
            elif col == "industry_rs60_trend":
                cells.append(f"<td>{_sparkline(history, str(row.get('industry') or ''))}</td>")
            elif col in {"industry_rs60_pct_delta_5d", "industry_rs60_pct_delta_10d"}:
                hcfg = radar_config(config)["industry_rs_history"]
                cells.append(f"<td data-sort='{_num(value, 6)}'>{html.escape(_delta_label(value, hcfg['delta_up_threshold'], hcfg['delta_down_threshold']))}</td>")
            elif col == "industry_rs60_persistence_20d":
                days = row.get("industry_rs60_top20_days_20d")
                samples = row.get("industry_rs60_persistence_sample_days_20d")
                text = "--" if pd.isna(days) or pd.isna(samples) else f"{_pct(value)}（{int(days)}/{int(samples)}）"
                cells.append(f"<td data-sort='{_num(value, 6)}'>{text}</td>")
            else:
                cells.append(f"<td data-sort='{_num(value, 6)}'>{html.escape(formatter(value))}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    header = "".join(f"<th>{html.escape(label)}</th>" for _, label, _ in columns)
    return f"<div class='table-wrap'><table class='sortable'><thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


def _custom_concept_table(history: pd.DataFrame, trade_date: str) -> str:
    latest = history[history.get("trade_date", pd.Series(dtype=str)).astype(str) == str(trade_date)].copy() if not history.empty else pd.DataFrame()
    if latest.empty:
        return "<p class='empty'>暂无可用自定义概念池数据</p>"
    columns = [
        ("concept_name", "概念池", str),
        ("category", "类别", str),
        ("concept_rs5_pct", "RS5", _num),
        ("concept_rs10_pct", "RS10", _num),
        ("concept_rs20_pct", "RS20", _num),
        ("concept_rs60_pct", "RS60", _num),
        ("concept_rs120_pct", "RS120", _num),
        ("member_return_mean", "成员平均收益", _pct),
        ("member_return_median", "成员中位收益", _pct),
        ("pct_advancing", "上涨成员", _pct),
        ("valid_members", "有效/总成员", _num),
        ("coverage_ratio", "覆盖率", _pct),
        ("small_sample", "样本状态", str),
    ]
    rows = []
    for _, row in latest.sort_values("concept_rs60_pct", ascending=False).iterrows():
        cells = []
        for column, _, formatter in columns:
            value = row.get(column)
            if column == "concept_name":
                cells.append(f"<td>{html.escape(_safe_text(value))}</td>")
            elif column == "valid_members":
                valid = "--" if pd.isna(value) else str(int(value))
                total = "--" if pd.isna(row.get("total_members")) else str(int(row.get("total_members")))
                cells.append(f"<td data-sort='{_num(value, 6)}'>{valid}/{total}</td>")
            elif column == "small_sample":
                text = "小样本（少于5只）" if bool(value) else "常规样本"
                cells.append(f"<td>{text}</td>")
            else:
                cells.append(f"<td data-sort='{_num(value, 6)}'>{html.escape(formatter(value))}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    header = "".join(f"<th>{html.escape(label)}</th>" for _, label, _ in columns)
    return f"<div class='table-wrap'><table class='sortable'><thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


def _stock_table(config: dict, output_path: Path, stocks: pd.DataFrame) -> str:
    if stocks.empty:
        return "<p class='empty'>暂无强势股雷达结果</p>"
    columns = [
        ("ts_code", "股票代码"),
        ("name", "股票名称"),
        ("industry", "行业"),
        ("state", "state"),
        ("rs5_pct", "RS5"),
        ("rs10_pct", "RS10"),
        ("rs60_pct", "rs60_pct"),
        ("rs60_delta_5d", "rs60_delta_5d"),
        ("rs60_persistence_20d", "rs60_persistence_20d"),
        ("trend_state", "trend_state"),
        ("distance_to_high_250d", "distance_to_high_250d"),
        ("amount_ratio_20d", "amount_ratio_20d"),
        ("volume_price_state", "volume_price_state"),
    ]
    rows = []
    for _, row in stocks.iterrows():
        state = str(row.get("state") or "")
        industry = str(row.get("industry") or "")
        trend = str(row.get("trend_state") or "")
        rs5 = _num(row.get("rs5_pct"))
        rs10 = _num(row.get("rs10_pct"))
        rs60 = _num(row.get("rs60_pct"))
        distance = _signed_pct(row.get("distance_to_high_250d"))
        cells = [
            f"<td>{stock_link_html(config, output_path, row.get('ts_code'))}</td>",
            f"<td>{_safe_text(row.get('name'))}</td>",
            f"<td>{html.escape(industry)}</td>",
            f"<td><span class='badge state-{html.escape(state)}'>{html.escape(_state_label(state))}</span></td>",
            f"<td data-sort='{_num(row.get('rs5_pct'), 6)}'>{rs5}</td>",
            f"<td data-sort='{_num(row.get('rs10_pct'), 6)}'>{rs10}</td>",
            f"<td data-sort='{_num(row.get('rs60_pct'), 6)}'>{rs60}</td>",
            f"<td data-sort='{_num(row.get('rs60_delta_5d'), 6)}'>{_num(row.get('rs60_delta_5d'))}</td>",
            f"<td data-sort='{_num(row.get('rs60_persistence_20d'), 6)}'>{_pct(row.get('rs60_persistence_20d'))}</td>",
            f"<td>{html.escape(trend)}</td>",
            f"<td data-sort='{_num(row.get('distance_to_high_250d'), 6)}'>{distance}</td>",
            f"<td data-sort='{_num(row.get('amount_ratio_20d'), 6)}'>{_num(row.get('amount_ratio_20d'))}</td>",
            f"<td>{_safe_text(row.get('volume_price_state'))}</td>",
        ]
        rows.append(
            "<tr "
            f"data-industry='{html.escape(industry, quote=True)}' "
            f"data-code='{html.escape(str(row.get('ts_code') or ''), quote=True)}' "
            f"data-state='{html.escape(state, quote=True)}' "
            f"data-trend='{html.escape(trend, quote=True)}' "
            f"data-rs60='{html.escape(rs60, quote=True)}' "
            f"data-near-high='{1 if pd.notna(row.get('distance_to_high_250d')) and float(row.get('distance_to_high_250d')) >= -0.08 else 0}'"
            ">"
            + "".join(cells)
            + "</tr>"
        )
    header = "".join(f"<th>{html.escape(label)}</th>" for _, label in columns)
    return f"<div class='table-wrap strong-stock-table-wrap'><table id='stockTable' class='sortable'><thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


def _evaluation_table(evaluation: pd.DataFrame) -> str:
    summary = build_evaluation_summary(evaluation)
    if summary.empty:
        return "<p class='empty'>暂无足够历史 snapshot 生成后验审计</p>"
    cols = [
        ("state", "state", str),
        ("sample_count", "样本", lambda v: str(int(v)) if pd.notna(v) else "--"),
        ("t5_median", "T+5中位", _signed_pct),
        ("t5_win_rate", "T+5胜率", _pct),
        ("t10_median", "T+10中位", _signed_pct),
        ("t10_win_rate", "T+10胜率", _pct),
        ("t20_median", "T+20中位", _signed_pct),
        ("t20_win_rate", "T+20胜率", _pct),
        ("mfe_20d_median", "MFE20中位", _signed_pct),
        ("mae_20d_median", "MAE20中位", _signed_pct),
    ]
    rows = []
    for _, row in summary.iterrows():
        rows.append("<tr>" + "".join(f"<td>{html.escape(fmt(row.get(col)))}</td>" for col, _, fmt in cols) + "</tr>")
    header = "".join(f"<th>{html.escape(label)}</th>" for _, label, _ in cols)
    return f"<div class='table-wrap'><table class='sortable'><thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


def _options(values: list[str]) -> str:
    return "".join(f"<option value='{html.escape(value, quote=True)}'>{html.escape(value)}</option>" for value in values)


def _theme_pool_report_data(theme_pool_payload: dict[str, Any] | None) -> dict[str, Any]:
    """Expose confirmed RS members and confirmed watch-only memberships separately."""
    payload = theme_pool_payload if isinstance(theme_pool_payload, dict) else {}
    raw_themes = payload.get("themes", {})
    raw_stocks = payload.get("stocks", {})
    themes = raw_themes if isinstance(raw_themes, dict) else {
        str(item.get("theme_id") or item.get("id")): item
        for item in raw_themes
        if isinstance(item, dict) and (item.get("theme_id") or item.get("id"))
    }
    stocks = raw_stocks if isinstance(raw_stocks, dict) else {}
    definitions: list[dict[str, Any]] = []
    members_by_theme: dict[str, list[dict[str, Any]]] = {}
    watch_by_theme: dict[str, list[dict[str, Any]]] = {}
    pending_by_theme: dict[str, int] = {}
    pending_roles_by_theme: dict[str, dict[str, int]] = {}
    for theme_id, theme in themes.items():
        if not isinstance(theme, dict) or theme.get("enabled", True) is False:
            continue
        normalized_id = str(theme_id)
        definitions.append(
            {
                "theme_id": normalized_id,
                "name": str(theme.get("name") or normalized_id),
                "definition": str(theme.get("definition") or ""),
            }
        )
        members_by_theme[normalized_id] = []
        watch_by_theme[normalized_id] = []
        pending_by_theme[normalized_id] = 0
        pending_roles_by_theme[normalized_id] = {"rs_member": 0, "watch_only": 0}
    for code, stock in stocks.items():
        if not isinstance(stock, dict):
            continue
        assignments = stock.get("assignments", {})
        if not isinstance(assignments, dict):
            continue
        for theme_id, assignment in assignments.items():
            if theme_id not in members_by_theme or not isinstance(assignment, dict):
                continue
            if assignment.get("status") == "pending":
                pending_by_theme[theme_id] += 1
                role = assignment.get("pool_role") if assignment.get("pool_role") in {"rs_member", "watch_only"} else "rs_member"
                pending_roles_by_theme[theme_id][role] += 1
            if assignment.get("status") != "confirmed":
                continue
            member = {
                "ts_code": str(stock.get("ts_code") or code),
                "stock_name": str(stock.get("stock_name") or stock.get("name") or code),
                "latest_limit_up_date": stock.get("latest_limit_up_date"),
                "limit_up_count_20d": stock.get("limit_up_count_20d"),
                "limit_up_count_60d": stock.get("limit_up_count_60d"),
                "limit_up_count_120d": stock.get("limit_up_count_120d"),
                "classification_source": assignment.get("classification_source"),
                "reason": assignment.get("reason"),
                "industry_relation": assignment.get("industry_relation"),
                "market_theme_relation": assignment.get("market_theme_relation"),
                "confidence": assignment.get("confidence"),
                "status": assignment.get("status"),
                "pool_role": assignment.get("pool_role") if assignment.get("pool_role") in {"rs_member", "watch_only"} else "rs_member",
                "evidence": assignment.get("evidence") if isinstance(assignment.get("evidence"), list) else [],
            }
            if member["pool_role"] == "watch_only":
                watch_by_theme[theme_id].append(member)
            else:
                members_by_theme[theme_id].append(member)
    return {
        "themes": definitions,
        "membersByTheme": members_by_theme,
        "watchByTheme": watch_by_theme,
        "pendingByTheme": pending_by_theme,
        "pendingRolesByTheme": pending_roles_by_theme,
    }


def _compact_theme_stock_history(history: pd.DataFrame | None) -> dict[str, Any]:
    """Group the browser payload by theme and omit repeated classification metadata."""
    value_columns = ["rs5_pct", "rs10_pct", "rs20_pct", "rs60_pct", "rs120_pct"]
    payload: dict[str, Any] = {"valueColumns": value_columns, "byTheme": {}}
    if history is None or history.empty or "theme_id" not in history.columns:
        return payload
    for theme_id, rows in history.groupby("theme_id", sort=True):
        group = rows.copy()
        group["trade_date"] = group["trade_date"].astype(str)
        dates = sorted(group["trade_date"].dropna().unique().tolist())
        date_positions = {date: index for index, date in enumerate(dates)}
        series: dict[str, list[Any]] = {}
        for ts_code, stock_rows in group.groupby("ts_code", sort=True):
            values: list[Any] = [None] * len(dates)
            for _, row in stock_rows.iterrows():
                point = []
                for column in value_columns:
                    value = row.get(column)
                    point.append(None if pd.isna(value) else round(float(value), 2))
                values[date_positions[str(row["trade_date"])]] = point
            series[str(ts_code)] = values
        payload["byTheme"][str(theme_id)] = {"dates": dates, "series": series}
    return payload


def _compact_industry_history(history: pd.DataFrame) -> dict[str, Any]:
    """Keep only fields consumed by the interactive industry charts."""
    columns = [
        "trade_date", "industry", "industry_daily_return", "pct_advancing",
        "industry_rs5_pct", "industry_rs10_pct", "industry_rs20_pct",
        "industry_rs60_pct", "industry_rs120_pct",
        "industry_rs5_pct_delta_5d_common", "industry_rs10_pct_delta_5d_common",
        "industry_rs20_pct_delta_5d_common", "industry_rs60_pct_delta_5d_common",
        "industry_rs120_pct_delta_5d_common", "industry_rs60_pct_delta_5d",
        "industry_rs60_pct_delta_10d", "industry_rs60_persistence_20d",
        "pct_above_ma20", "pct_new_high_20d", "industry_state",
    ]
    if history.empty:
        return {"columns": columns, "rows": []}
    compact = history.reindex(columns=columns).copy()
    numeric = compact.select_dtypes(include="number").columns
    compact[numeric] = compact[numeric].round(4)
    compact = compact.astype(object).where(pd.notna(compact), None)
    return {"columns": columns, "rows": compact.values.tolist()}


def generate_strong_stock_radar_report(
    config: dict,
    trade_date: str,
    industry_strength: pd.DataFrame,
    industry_rs_history: pd.DataFrame,
    stock_snapshot: pd.DataFrame,
    evaluation: pd.DataFrame,
    market_environment: dict[str, Any],
    output_path: str | Path,
    full_stock_snapshot: pd.DataFrame | None = None,
    custom_concept_history: pd.DataFrame | None = None,
    custom_concept_pools: list[Any] | None = None,
    custom_concept_warnings: list[str] | None = None,
    theme_pool_payload: dict[str, Any] | None = None,
    theme_stock_history: pd.DataFrame | None = None,
) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    stocks = stock_snapshot.copy()
    metric_stocks = full_stock_snapshot.copy() if full_stock_snapshot is not None else stocks
    if not stocks.empty:
        stocks = stocks.sort_values(["rs60_pct", "rs120_pct"], ascending=False)
    industries = sorted(stocks["industry"].dropna().astype(str).unique().tolist()) if "industry" in stocks.columns else []
    states = sorted(stocks["state"].dropna().astype(str).unique().tolist()) if "state" in stocks.columns else []
    trends = sorted(stocks["trend_state"].dropna().astype(str).unique().tolist()) if "trend_state" in stocks.columns else []
    theme_pool_data = _theme_pool_report_data(theme_pool_payload)
    theme_stock_payload = _compact_theme_stock_history(theme_stock_history)
    theme_available = bool(theme_pool_data["themes"])
    theme_member_count = sum(len(members) for members in theme_pool_data["membersByTheme"].values())
    theme_watch_count = sum(len(members) for members in theme_pool_data["watchByTheme"].values())
    body = f"""
    <main class="page">
      <header>
        <div>
          <p class="eyebrow">QuantYB 研究模块</p>
          <h1>强势股雷达</h1>
          <p class="sub">数据日期 {html.escape(str(trade_date))} · 仅用于市场观察、强弱排序、复盘和后验验证，不输出自动买卖建议。</p>
        </div>
      </header>
      <section class="metrics">{_metric_cards(metric_stocks, industry_strength, market_environment)}</section>
      <section class="theme-entry">
        <div><h2>自定义主题股票池</h2><span>{len(theme_pool_data['themes'])} 个主题 · 正式成员 {theme_member_count} · 观察成员 {theme_watch_count}</span></div>
        <label>打开主题<select id="themeQuickSelect"{' disabled' if not theme_available else ''}><option value="">选择主题</option></select></label>
      </section>
      <details id="industryHeatSection" class="report-section">
        <summary><span>行业 RS 轮动热力图</span><small>数据截止 {html.escape(str(trade_date))}</small></summary>
        <div class="section-content">
        <div class="rotation-controls"><select id="heatMetric"><optgroup label="短线轮动"><option value="industry_rs5_pct">RS5</option><option value="industry_rs10_pct">RS10</option><option value="industry_rs20_pct">RS20</option></optgroup><optgroup label="中期趋势"><option value="industry_rs60_pct" selected>RS60</option><option value="industry_rs120_pct">RS120</option></optgroup></select><select id="heatFrequency"><option value="day">日频</option><option value="week">周频</option></select><select id="heatRange"><option value="3">最近3个月</option><option value="6">最近6个月</option><option value="12">最近1年</option></select><select id="heatFilter"><option value="all">全部行业</option><option value="currentStrong">当前RS前15</option><option value="improving">RS百分位改善最快</option><option value="strengthening">高位继续增强</option><option value="lowImproving">低位改善观察</option><option value="weakening">高位回落</option><option value="shortTerm">短线动量改善观察</option><option value="watchlist">自选行业</option></select><label class="rotation-threshold">最小名次变化<select id="heatRankChange"><option value="1">≥1名：灵敏</option><option value="2" selected>≥2名：默认</option><option value="3">≥3名：明显</option></select></label><span id="heatCount" class="muted"></span></div>
        <p id="heatSelectionInfo" class="rotation-note"></p>
        <div id="rotationHeatmap" class="chart"></div>
        </div>
      </details>
      <details id="strongIndustrySection" class="report-section">
        <summary><span>强势行业</span><small>点击行业联动详情和下方个股</small></summary>
        <div class="section-content">{_industry_table(industry_strength, industry_rs_history, config)}</div>
      </details>
      <details id="industryDetailSection" class="report-section">
        <summary><span>行业 RS 历史</span><small id="industryDetailTitle">选择行业查看 RS20 / RS60 / RS120</small></summary>
        <div class="section-content">
          <div class="rotation-controls"><select id="detailIndustry">{_options(sorted(industry_strength.get('industry', pd.Series(dtype=str)).dropna().astype(str).tolist()))}</select><button type="button" data-range="120">120日</button><button type="button" data-range="250">250日</button></div>
          <div id="industrySummary" class="industry-summary"></div>
          <div id="industryDetail" class="chart"></div>
        </div>
      </details>
      <details id="themeRotationSection" class="report-section">
        <summary><span>自定义主题 RS 轮动热力图</span><small>主题间排名 · 仅 confirmed + rs_member</small></summary>
        <div class="section-content">
        <div class="rotation-controls"><select id="themeRotationMetric"><option value="rs5_pct">RS5</option><option value="rs10_pct">RS10</option><option value="rs20_pct">RS20</option><option value="rs60_pct" selected>RS60</option></select><select id="themeRotationFrequency"><option value="day">日频</option><option value="week">周频</option></select><select id="themeRotationRange"><option value="3">最近3个月</option><option value="6" selected>最近6个月</option><option value="12">最近1年</option></select><span id="themeRotationCount" class="muted"></span></div>
        <p id="themeRotationInfo" class="rotation-note"></p>
        <div id="themeRotationHeatmap" class="chart"></div>
        </div>
      </details>
      <details id="themeMembersSection" class="report-section">
        <summary><span>自定义主题池热力图</span><small>仅 confirmed + rs_member 进入主题内排名</small></summary>
        <div class="section-content">
        <div class="rotation-controls"><label>主题<select id="themePoolSelect"{' disabled' if not theme_available else ''}></select></label><select id="themeHeatMetric"><option value="rs5_pct">RS5</option><option value="rs10_pct">RS10</option><option value="rs20_pct" selected>RS20</option><option value="rs60_pct">RS60</option></select><select id="themeHeatFrequency"><option value="day">日频</option><option value="week">周频</option></select><select id="themeHeatRange"><option value="3">最近3个月</option><option value="6" selected>最近6个月</option><option value="12">最近1年</option></select></div>
        <p id="themePoolInfo" class="rotation-note"></p>
        <h3 class="theme-subhead">正式 RS 成员</h3>
        <div id="themeStockHeatmap" class="chart theme-stock-chart"></div>
        <h3 class="theme-subhead">题材观察成员</h3>
        <div id="themeWatchMembers" class="theme-watch-members"></div>
        </div>
      </details>
      <details id="strongStocksSection" class="report-section">
        <summary><span>强势股票</span><small id="rowCount" data-total-stock-count="{len(metric_stocks)}"></small></summary>
        <div class="section-content">
        <div class="filters">
          <select id="industryFilter"><option value="">全部行业</option>{_options(industries)}</select>
          <select id="stateFilter"><option value="">全部 state</option>{_options(states)}</select>
          <select id="trendFilter"><option value="">全部趋势</option>{_options(trends)}</select>
          <select id="rsFilter"><option value="">全部 RS</option><option value="90">RS60 >= 90</option><option value="80">RS60 >= 80</option></select>
          <label><input type="checkbox" id="nearHighFilter"> 接近250日高点</label>
          <button type="button" id="resetFilters">重置</button>
        </div>
        {_stock_table(config, target, stocks)}
        </div>
      </details>
      <section>
        <div class="section-head"><h2>后验审计摘要</h2><span>future_return / MFE / MAE 只来自历史 snapshot 之后的数据</span></div>
        {_evaluation_table(evaluation)}
      </section>
      <section class="notes">
        <h2>口径说明</h2>
        <ul>
          <li>雷达使用本地日 K 缓存和本地股票元数据；成交量统一为股，成交额统一为元。</li>
          <li>趋势斜率为 MA / MA.shift(slope_window) - 1 后除以 slope_window。</li>
          <li>BREAKOUT 是研究状态，不等同买入信号；正式策略、仓位、订单和 market_risk_gate 不读取本报告。</li>
        </ul>
      </section>
    </main>
    """
    rotation_payload = _compact_industry_history(industry_rs_history)
    scripts = json_script_data(
        {
            "generated_for": trade_date,
            "history": rotation_payload,
            "themePool": theme_pool_data,
            "themeStockHistory": theme_stock_payload,
            "watchlist": radar_config(config)["industry_rs_history"].get("watchlist", []),
        },
        "radarMeta",
    ) + "<script>\n" + ROTATION_HELPERS_JS + """
    function numberFromCell(cell) {
      const raw = cell.dataset.sort || cell.textContent.trim().replace('%', '');
      const value = finiteOrNull(raw);
      return value === null ? (raw && raw !== '--' ? raw : null) : value;
    }
    document.querySelectorAll('table.sortable th').forEach(th => {
      th.addEventListener('click', () => {
        const table = th.closest('table');
        const body = table.querySelector('tbody');
        const index = Array.from(table.querySelectorAll('thead th')).indexOf(th);
        if (index < 0) return;
        const current = th.dataset.order === 'asc' ? 'desc' : 'asc';
        table.querySelectorAll('th').forEach(item => delete item.dataset.order);
        th.dataset.order = current;
        const rows = Array.from(body.querySelectorAll('tr'));
        rows.sort((a, b) => {
          const av = numberFromCell(a.children[index]);
          const bv = numberFromCell(b.children[index]);
          if (av === null && bv === null) return 0;
          if (av === null) return 1;
          if (bv === null) return -1;
          if (typeof av === 'number' && typeof bv === 'number') return current === 'asc' ? av - bv : bv - av;
          return current === 'asc' ? String(av).localeCompare(String(bv), 'zh-CN') : String(bv).localeCompare(String(av), 'zh-CN');
        });
        rows.forEach(row => body.appendChild(row));
      });
    });
    const filters = {
      industry: document.getElementById('industryFilter'),
      state: document.getElementById('stateFilter'),
      trend: document.getElementById('trendFilter'),
      rs: document.getElementById('rsFilter'),
      nearHigh: document.getElementById('nearHighFilter'),
      rowCount: document.getElementById('rowCount')
    };
    function applyFilters() {
      const rows = Array.from(document.querySelectorAll('#stockTable tbody tr'));
      let visible = 0;
      rows.forEach(row => {
        const rs60 = finiteOrNull(row.dataset.rs60);
        const ok = (!filters.industry.value || row.dataset.industry === filters.industry.value)
          && (!filters.state.value || row.dataset.state === filters.state.value)
          && (!filters.trend.value || row.dataset.trend === filters.trend.value)
          && (!filters.rs.value || (rs60 !== null && rs60 >= finiteOrNull(filters.rs.value)))
          && (!filters.nearHigh.checked || row.dataset.nearHigh === '1');
        row.hidden = !ok;
        if (ok) visible += 1;
      });
      const total=finiteOrNull(filters.rowCount.dataset.totalStockCount)||rows.length;
      filters.rowCount.textContent = '当前显示 ' + visible + ' / 报告 ' + rows.length + ' · 全量 ' + total;
    }
    ['industry','state','trend','rs'].forEach(key => filters[key].addEventListener('change', applyFilters));
    filters.nearHigh.addEventListener('change', applyFilters);
    document.querySelectorAll('.link-filter').forEach(button => {
      button.addEventListener('click', () => {
        filters.industry.value = button.dataset.industry;
        applyFilters();
      });
    });
    document.getElementById('resetFilters').addEventListener('click', () => {
      filters.industry.value = '';
      filters.state.value = '';
      filters.trend.value = '';
      filters.rs.value = '';
      filters.nearHigh.checked = false;
      applyFilters();
    });
    applyFilters();
    const radarMeta=JSON.parse(document.getElementById('radarMeta').textContent||'{}'), industryPayload=radarMeta.history||{}, watchlist=radarMeta.watchlist||[], themePool=radarMeta.themePool||{}, themeStockHistory=radarMeta.themeStockHistory||{};
    const industryHistory=(industryPayload.rows||[]).map(values=>Object.fromEntries((industryPayload.columns||[]).map((column,index)=>[column,values[index]])));
    const history=industryHistory;
    let selectedIndustry=document.getElementById('detailIndustry').value, rangeDays=250, heatChart, detailChart;
    function dateOf(s){return new Date(s.slice(0,4)+'-'+s.slice(4,6)+'-'+s.slice(6,8));}
    function weekKey(s){const d=dateOf(s), y=new Date(d.getFullYear(),0,1);return d.getFullYear()+'-'+String(Math.ceil((((d-y)/86400000)+y.getDay()+1)/7)).padStart(2,'0');}
    function sampledRows(metric, frequency, months) {
      const end = history.map(row => row.trade_date).sort().slice(-1)[0] || '';
      const cutoff = dateOf(end); cutoff.setMonth(cutoff.getMonth() - months);
      const source = history.filter(row => dateOf(row.trade_date) >= cutoff);
      if (frequency === 'day') return source;
      const picked = {};
      source.forEach(row => {
        if (finiteOrNull(row[metric]) === null) return;
        const key = weekKey(row.trade_date) + '|' + row.industry;
        if (!picked[key] || picked[key].trade_date < row.trade_date) picked[key] = row;
      });
      return Object.values(picked);
    }
    function heatDataValues(point) { return Array.isArray(point.data) ? point.data : point.data.value; }
    function rankChangeText(change) {
      if (change === null || change === undefined) return '--';
      if (change > 0) return '前进' + change + '名';
      if (change < 0) return '后退' + Math.abs(change) + '名';
      return '名次不变';
    }
    function shortTermDetails(row, state) {
      const rs5 = finiteOrNull(row.industry_rs5_pct);
      const rs20Comparison = state.rs20ComparisonByIndustry[row.industry];
      const dailyRank = state.dailyRankByIndustry[row.industry];
      const dailyLimit = Math.ceil(state.dailyRows.length / 2);
      const advancing = finiteOrNull(row.pct_advancing);
      return '短线条件（固定，不随周期切换）<br>RS5：' + (rs5 === null ? '--' : rs5.toFixed(2)) + '（' + (rs5 !== null && rs5 >= 60 ? '满足' : '不满足') + '）'
        + '<br>RS20百分位变化：' + (rs20Comparison ? signedNumber(rs20Comparison.delta) : '--') + '（' + (rs20Comparison && rs20Comparison.delta > 0 ? '满足' : '不满足') + '）'
        + '<br>当日行业收益排名：' + (dailyRank === undefined ? '--' : dailyRank + '/' + state.dailyRows.length) + '（' + (dailyRank !== undefined && dailyRank <= dailyLimit ? '满足' : '不满足') + '）'
        + '<br>上涨成员比例：' + (advancing === null ? '--' : (advancing * 100).toFixed(1) + '%') + '（' + (advancing !== null && advancing >= 0.5 ? '满足' : '不满足') + '）';
    }
    function drawHeat() {
      if (!window.echarts) return;
      const metric = document.getElementById('heatMetric').value;
      const frequency = document.getElementById('heatFrequency').value;
      const months = finiteOrNull(document.getElementById('heatRange').value) || 6;
      const filter = document.getElementById('heatFilter').value;
      const minRankChange = finiteOrNull(document.getElementById('heatRankChange').value) || 2;
      const state = rotationState(history, metric);
      const visibleRows = filteredRotationRows(state, filter, watchlist, minRankChange);
      const visibleIndustries = visibleRows.map(row => row.industry);
      const rows = sampledRows(metric, frequency, months);
      const axisOf = row => frequency === 'week' ? weekKey(row.trade_date) : row.trade_date;
      const axes = [...new Set(rows.map(axisOf))].sort();
      const labelByAxis = {};
      rows.forEach(row => { const axis = axisOf(row); if (!labelByAxis[axis] || labelByAxis[axis] < row.trade_date) labelByAxis[axis] = row.trade_date; });
      document.getElementById('heatCount').textContent = '当前展示 ' + visibleRows.length + '/' + state.validCount + ' 个有效行业';
      const filterNote = filter === 'shortTerm'
        ? '短线动量改善观察使用固定 RS5、RS20、当日收益和上涨成员比例条件，不随上方周期切换；阈值尚未经过收益回测。'
        : '最小名次变化为≥' + minRankChange + '名；RS百分位改善表示相对排名上升，不代表行业价格一定上涨。';
      document.getElementById('heatSelectionInfo').textContent = '当前筛选依据日期：' + state.cutoffDate + '，统一比较日期：' + (state.previousDate || '--') + '。RS表示当日横截面中的相对强弱百分位，不是行业涨跌幅。RS5用于发现一周内的快速异动，噪声较高；RS10用于观察短期强势是否开始延续；RS20、RS60、RS120用于观察更长周期趋势。' + filterNote + '所有筛选仅用于轮动观察、复盘和后续验证，不生成自动买卖建议。';
      const lookup = {};
      rows.forEach(row => { const key = axisOf(row) + '|' + row.industry; if (!lookup[key] || lookup[key].trade_date < row.trade_date) lookup[key] = row; });
      const comparisonCache = {};
      const comparisonAt = date => comparisonCache[date] || (comparisonCache[date] = comparisonState(history, metric, date));
      const data = [];
      visibleIndustries.forEach((industry, y) => axes.forEach((axis, x) => {
        const row = lookup[axis + '|' + industry];
        const date = row ? row.trade_date : labelByAxis[axis];
        const value = row ? finiteOrNull(row[metric]) : null;
        const dateState = comparisonAt(date);
        const comparison = dateState.comparisonByIndustry[industry] || null;
        const cell = [x, y, value, industry, date, dateState.rankByIndustry[industry] || null, dateState.validCount, comparison, row ? rotationCategory(row, dateState) : '暂无有效数据', row || null];
        data.push(value === null ? { value: cell, itemStyle: { color: '#f1f3f5' } } : cell);
      }));
      if (!heatChart) heatChart = echarts.init(document.getElementById('rotationHeatmap'));
      document.getElementById('rotationHeatmap').style.height = Math.max(390, visibleIndustries.length * 25 + 95) + 'px';
      heatChart.resize();
      heatChart.setOption({
        tooltip: { formatter: point => {
          const value = heatDataValues(point), comparison = value[7];
          if (value[2] === null) return '行业：' + value[3] + '<br>日期：' + value[4] + '<br>暂无有效数据';
          let text = '行业：' + value[3] + '<br>当前日期：' + value[4] + '<br>当前' + state.config.label + '：' + value[2].toFixed(2) + '<br>当前排名：' + value[5] + '/' + value[6];
          if (!comparison) return text + '<br>暂无统一比较日期的有效数据';
          text += '<br>比较日期：' + comparison.previousDate + '<br>比较日' + state.config.label + '：' + comparison.previousValue.toFixed(2)
            + '<br>比较日排名：' + comparison.previousRank + '/' + comparison.previousCount
            + '<br>RS百分位变化：' + signedNumber(comparison.delta)
            + '<br>实际名次变化：' + rankChangeText(comparison.rankChange);
          if (comparison.previousCount !== value[6]) text += '<br>前后有效行业数量不同，名次和百分位变化可能受到行业集合变化影响。';
          if (filter === 'shortTerm' && value[4] === state.cutoffDate) text += '<br>' + shortTermDetails(state.allRows.find(row => row.industry === value[3]) || {}, state);
          return text + '<br>分类：' + value[8];
        } },
        grid: { left: 280, right: 92, top: 18, bottom: 58 },
        xAxis: { type: 'category', data: axes.map(axis => labelByAxis[axis].slice(4,6) + '-' + labelByAxis[axis].slice(6,8)), axisLabel: { interval: frequency === 'day' ? Math.max(9, Math.floor(axes.length / 9)) : 2, rotate: 0 } },
        yAxis: { type: 'category', data: visibleIndustries, inverse: true, axisLabel: { formatter: industry => { const row = state.currentByIndustry[industry] || {}; const comparison = state.comparisonByIndustry[industry]; return industry + '｜' + state.config.label + ' ' + finiteOrNull(row[metric]).toFixed(2) + '｜' + (comparison ? rankChangeText(comparison.rankChange) : '--') + '｜' + state.rankByIndustry[industry] + '/' + state.validCount; } } },
        visualMap: { dimension: 2, min: 0, max: 100, calculable: false, orient: 'vertical', right: 8, top: 34, itemHeight: 180, text: ['强势', '弱'], textStyle: { color: '#435168' }, inRange: { color: ['#173f8a', '#75a8dc', '#e5e7eb', '#ed9a57', '#c93c3c'] }, seriesIndex: 0 },
        series: [{ type: 'heatmap', data: data, itemStyle: { borderColor: '#fff', borderWidth: 1 } }]
      });
      heatChart.off('click');
      heatChart.on('click', point => { const value = heatDataValues(point); if (value[2] !== null) selectIndustry(value[3]); });
    }
    function drawDetail(){if(!window.echarts)return;const rows=history.filter(r=>r.industry===selectedIndustry).slice(-rangeDays), dates=rows.map(r=>r.trade_date), last=rows[rows.length-1]||{};if(!detailChart)detailChart=echarts.init(document.getElementById('industryDetail'));detailChart.setOption({tooltip:{trigger:'axis'},legend:{data:['RS5','RS10','RS20','RS60','RS120']},grid:{left:48,right:20,top:42,bottom:44},xAxis:{type:'category',data:dates},yAxis:{min:0,max:100,splitLine:{show:true}},series:[['industry_rs5_pct','RS5','#0f766e'],['industry_rs10_pct','RS10','#0891b2'],['industry_rs20_pct','RS20','#2563eb'],['industry_rs60_pct','RS60','#9333ea'],['industry_rs120_pct','RS120','#d97706']].map(x=>({name:x[1],type:'line',data:rows.map(r=>finiteOrNull(r[x[0]])),showSymbol:false,lineStyle:{color:x[2]},markLine:{silent:true,data:[{yAxis:50},{yAxis:80,label:{formatter:'强势区'}}]}}))});document.getElementById('industryDetailTitle').textContent=selectedIndustry+' · 最近 '+rangeDays+' 个交易日';document.getElementById('industrySummary').textContent=['RS5 '+fmt(last.industry_rs5_pct),'RS10 '+fmt(last.industry_rs10_pct),'RS20 '+fmt(last.industry_rs20_pct),'RS60 '+fmt(last.industry_rs60_pct),'RS120 '+fmt(last.industry_rs120_pct),'RS60排名5D '+fmt(last.industry_rs60_pct_delta_5d),'RS60排名10D '+fmt(last.industry_rs60_pct_delta_10d),'持续率 '+pct(last.industry_rs60_persistence_20d),'MA20以上 '+pct(last.pct_above_ma20),'20日新高 '+pct(last.pct_new_high_20d),'状态 '+(last.industry_state||'--')].join('  ·  ');}
    function fmt(value){const number=finiteOrNull(value);return number===null?'--':number.toFixed(2);} function pct(value){const number=finiteOrNull(value);return number===null?'--':(number*100).toFixed(1)+'%';}
    function selectIndustry(industry){selectedIndustry=industry;document.getElementById('detailIndustry').value=industry;filters.industry.value=industry;applyFilters();const section=document.getElementById('industryDetailSection');section.open=true;requestAnimationFrame(drawDetail);}
    function themeHtml(value) { const node=document.createElement('span'); node.textContent=value===null||value===undefined?'--':String(value); return node.innerHTML; }
    function rankThemeStocks(rows, field) {
      const sorted=rows.slice().sort((left,right)=>finiteOrNull(right[field])-finiteOrNull(left[field]) || String(left.ts_code).localeCompare(String(right.ts_code)));
      const rankByCode={}; let start=0;
      while(start<sorted.length){const value=finiteOrNull(sorted[start][field]);let end=start+1;while(end<sorted.length&&finiteOrNull(sorted[end][field])===value)end+=1;for(let index=start;index<end;index+=1)rankByCode[sorted[index].ts_code]=end;start=end;}
      return {rows:sorted,rankByCode};
    }
    function themeMembers(themeId) { return (themePool.membersByTheme||{})[themeId]||[]; }
    function themeWatchMembers(themeId) { return (themePool.watchByTheme||{})[themeId]||[]; }
    const themeHistoryCache={}, themeDatesCache={}, themeRankingCache={};
    function themeHistoryRows(themeId) {
      if(themeHistoryCache[themeId])return themeHistoryCache[themeId];
      const columns=themeStockHistory.valueColumns||[], group=((themeStockHistory.byTheme||{})[themeId]||{}), dates=group.dates||[], rows=[];
      Object.entries(group.series||{}).forEach(([tsCode,points])=>points.forEach((values,index)=>{
        if(!Array.isArray(values)||!dates[index])return;
        const row={trade_date:dates[index],ts_code:tsCode};
        columns.forEach((column,columnIndex)=>{row[column]=values[columnIndex];});
        rows.push(row);
      }));
      themeHistoryCache[themeId]=rows;
      return rows;
    }
    function safeThemeUrl(value) { try { const url=new URL(String(value)); return ['http:','https:'].includes(url.protocol) ? url.href : ''; } catch (_) { return ''; } }
    function drawThemeWatchMembers(themeId) {
      const container=document.getElementById('themeWatchMembers'), members=themeWatchMembers(themeId);
      if(!members.length){container.innerHTML='<p class="empty">该主题暂无已确认的题材观察成员。</p>';return;}
      container.innerHTML='<div class="theme-watch-grid">'+members.map(member=>{
        const evidence=(member.evidence||[]).map(item=>{const url=safeThemeUrl(item.url);const title=themeHtml(item.title||item.source_name||'证据来源');return '<li>'+ (url?'<a href="'+themeHtml(url)+'" target="_blank" rel="noopener">'+title+'</a>':title) +'：'+themeHtml(item.supports||'--')+'</li>';}).join('');
        return '<article class="theme-watch-item"><strong>'+themeHtml(member.stock_name)+'（'+themeHtml(member.ts_code)+'）</strong><span class="watch-badge">仅观察，不参与主题RS</span><p>产业关系：'+themeHtml(member.industry_relation)+' · 市场题材关系：'+themeHtml(member.market_theme_relation)+' · 置信度：'+themeHtml(member.confidence)+'</p><p>理由：'+themeHtml(member.reason)+'</p><ul>'+ (evidence||'<li>未提供证据</li>') +'</ul></article>';
      }).join('')+'</div>';
    }
    function themeDates(themeId) { return themeDatesCache[themeId]||(themeDatesCache[themeId]=[...new Set(themeHistoryRows(themeId).map(row=>row.trade_date).filter(Boolean))].sort()); }
    function themeRanking(themeId, field, date) {
      const key=themeId+'|'+field+'|'+date;
      if(themeRankingCache[key])return themeRankingCache[key];
      const rows=themeHistoryRows(themeId).filter(row=>row.trade_date===date&&finiteOrNull(row[field])!==null);
      return themeRankingCache[key]=rankThemeStocks(rows,field);
    }
    function themeSampledRows(themeId, field, frequency, months) {
      const dates=themeDates(themeId), end=dates[dates.length-1]||'';
      if(!end)return {rows:[],axes:[],labels:{}};
      const cutoff=dateOf(end);cutoff.setMonth(cutoff.getMonth()-months);
      const source=themeHistoryRows(themeId).filter(row=>dateOf(row.trade_date)>=cutoff);
      const labels={};source.forEach(row=>{if(!labels[row.trade_date])labels[row.trade_date]=row.trade_date;});
      if(frequency==='day')return {rows:source,axes:Object.keys(labels).sort(),labels};
      const picked={};source.forEach(row=>{if(finiteOrNull(row[field])===null)return;const key=weekKey(row.trade_date)+'|'+row.ts_code;if(!picked[key]||picked[key].trade_date<row.trade_date)picked[key]=row;});
      const rows=Object.values(picked), weeklyLabels={};rows.forEach(row=>{const key=weekKey(row.trade_date);if(!weeklyLabels[key]||weeklyLabels[key]<row.trade_date)weeklyLabels[key]=row.trade_date;});
      return {rows,axes:Object.keys(weeklyLabels).sort(),labels:weeklyLabels};
    }
    const themeRotationCache={}; let themeRotationChart;
    function rankThemes(rows) {
      const sorted=rows.slice().sort((left,right)=>right.value-left.value||left.themeName.localeCompare(right.themeName,'zh-CN'));
      const rankByTheme={};let start=0;
      while(start<sorted.length){const value=sorted[start].value;let end=start+1;while(end<sorted.length&&sorted[end].value===value)end+=1;for(let index=start;index<end;index+=1)rankByTheme[sorted[index].themeId]=end;start=end;}
      return {rows:sorted,rankByTheme};
    }
    function themeRotationRows(field) {
      if(themeRotationCache[field])return themeRotationCache[field];
      const rows=[];
      (themePool.themes||[]).forEach(theme=>{
        const valuesByDate={};
        themeHistoryRows(theme.theme_id).forEach(row=>{const value=finiteOrNull(row[field]);if(value!==null)(valuesByDate[row.trade_date]||(valuesByDate[row.trade_date]=[])).push(value);});
        Object.entries(valuesByDate).forEach(([tradeDate,values])=>rows.push({themeId:theme.theme_id,themeName:theme.name,trade_date:tradeDate,value:values.reduce((sum,value)=>sum+value,0)/values.length,memberCount:values.length}));
      });
      return themeRotationCache[field]=rows.sort((left,right)=>left.trade_date.localeCompare(right.trade_date)||left.themeId.localeCompare(right.themeId));
    }
    function themeRotationState(rows, date) { return rankThemes(rows.filter(row=>row.trade_date===date&&finiteOrNull(row.value)!==null)); }
    function themeRotationSample(rows, frequency, months) {
      const dates=[...new Set(rows.map(row=>row.trade_date))].sort(), end=dates[dates.length-1]||'';
      if(!end)return {rows:[],axes:[],labels:{}};
      const cutoff=dateOf(end);cutoff.setMonth(cutoff.getMonth()-months);
      const source=rows.filter(row=>dateOf(row.trade_date)>=cutoff), labels={};source.forEach(row=>{if(!labels[row.trade_date])labels[row.trade_date]=row.trade_date;});
      if(frequency==='day')return {rows:source,axes:Object.keys(labels).sort(),labels};
      const picked={};source.forEach(row=>{const key=weekKey(row.trade_date)+'|'+row.themeId;if(!picked[key]||picked[key].trade_date<row.trade_date)picked[key]=row;});
      const weeklyLabels={};Object.values(picked).forEach(row=>{const key=weekKey(row.trade_date);if(!weeklyLabels[key]||weeklyLabels[key]<row.trade_date)weeklyLabels[key]=row.trade_date;});
      return {rows:Object.values(picked),axes:Object.keys(weeklyLabels).sort(),labels:weeklyLabels};
    }
    function drawThemeRotationHeatmap() {
      if(!window.echarts)return;
      const metric=document.getElementById('themeRotationMetric').value,frequency=document.getElementById('themeRotationFrequency').value,months=finiteOrNull(document.getElementById('themeRotationRange').value)||6,container=document.getElementById('themeRotationHeatmap'),info=document.getElementById('themeRotationInfo'),count=document.getElementById('themeRotationCount'),rows=themeRotationRows(metric),dates=[...new Set(rows.map(row=>row.trade_date))].sort(),cutoffDate=dates[dates.length-1]||'',currentState=themeRotationState(rows,cutoffDate),sampled=themeRotationSample(rows,frequency,months);
      if(!currentState.rows.length||!sampled.axes.length){count.textContent='当前展示 0 个有效主题';info.textContent='暂无可用于主题间比较的已确认正式 RS 成员。';if(themeRotationChart){themeRotationChart.dispose();themeRotationChart=null;}container.innerHTML='<p class="empty">暂无主题 RS 历史数据。</p>';return;}
      const previousDate=dates.indexOf(cutoffDate)>=5?dates[dates.indexOf(cutoffDate)-5]:'',previousState=themeRotationState(rows,previousDate),visible=currentState.rows.map(row=>({themeId:row.themeId,themeName:row.themeName,value:row.value,memberCount:row.memberCount,rank:currentState.rankByTheme[row.themeId],previousRank:previousState.rankByTheme[row.themeId]||null}));
      const axisOf=row=>frequency==='week'?weekKey(row.trade_date):row.trade_date,lookup={};sampled.rows.forEach(row=>{const key=axisOf(row)+'|'+row.themeId;if(!lookup[key]||lookup[key].trade_date<row.trade_date)lookup[key]=row;});
      count.textContent='当前展示 '+visible.length+'/'+currentState.rows.length+' 个有效主题';
      info.textContent='当前排名截止日期：'+cutoffDate+'；统一比较日期：'+(previousDate||'--')+'。主题 RS 为主题内 confirmed + rs_member 个股的全市场 '+metric.replace('_pct','').toUpperCase()+' 等权均值；颜色表示主题 RS 水平，排名仅在有效主题间计算，不代表主题涨跌幅。';
      if(!themeRotationChart){container.innerHTML='';themeRotationChart=echarts.init(container);}container.style.height=Math.max(390,visible.length*28+105)+'px';themeRotationChart.resize();
      const data=[];visible.forEach((theme,y)=>sampled.axes.forEach((axis,x)=>{const row=lookup[axis+'|'+theme.themeId],date=row?row.trade_date:sampled.labels[axis],value=row?finiteOrNull(row.value):null,state=themeRotationState(rows,date),rank=state.rankByTheme[theme.themeId]||null,index=dates.indexOf(date),priorDate=index>=5?dates[index-5]:'',priorState=themeRotationState(rows,priorDate),rankChange=rank&&priorState.rankByTheme[theme.themeId]?priorState.rankByTheme[theme.themeId]-rank:null,cell=[x,y,value,theme.themeId,theme.themeName,date,rank,state.rows.length,rankChange,row?row.memberCount:null];data.push(value===null?{value:cell,itemStyle:{color:'#f1f3f5'}}:cell);}));
      const label=theme=>theme.themeName+'｜'+metric.replace('_pct','').toUpperCase()+' '+theme.value.toFixed(2)+'｜'+rankChangeText(theme.previousRank?theme.previousRank-theme.rank:null)+'｜'+theme.rank+'/'+currentState.rows.length;
      themeRotationChart.setOption({tooltip:{formatter:point=>{const value=heatDataValues(point);let text='主题：'+themeHtml(value[4])+'<br>日期：'+themeHtml(value[5]);if(value[2]===null)return text+'<br>暂无有效数据';return text+'<br>主题 '+themeHtml(metric.replace('_pct','').toUpperCase())+'：'+value[2].toFixed(2)+'<br>主题间排名：'+value[6]+'/'+value[7]+'<br>5日主题间名次变化：'+rankChangeText(value[8])+'<br>有效正式成员：'+(value[9]===null?'--':value[9])+'<br>点击查看该主题成员个股 RS';}},grid:{left:300,right:92,top:18,bottom:58},xAxis:{type:'category',data:sampled.axes.map(axis=>{const date=sampled.labels[axis];return date.slice(4,6)+'-'+date.slice(6,8);}),axisLabel:{interval:frequency==='day'?Math.max(9,Math.floor(sampled.axes.length/9)):2}},yAxis:{type:'category',data:visible.map(label),inverse:true,axisLabel:{width:280,overflow:'truncate'}},visualMap:{dimension:2,min:0,max:100,calculable:false,orient:'vertical',right:8,top:34,itemHeight:180,text:['强势','弱'],textStyle:{color:'#435168'},inRange:{color:['#173f8a','#75a8dc','#e5e7eb','#ed9a57','#c93c3c']},seriesIndex:0},series:[{type:'heatmap',data,itemStyle:{borderColor:'#fff',borderWidth:1}}]});
      themeRotationChart.off('click');themeRotationChart.on('click',point=>{const value=heatDataValues(point);if(value[2]===null)return;document.getElementById('themePoolSelect').value=value[3];const section=document.getElementById('themeMembersSection');section.open=true;requestAnimationFrame(drawThemeStockHeatmap);section.scrollIntoView({behavior:'smooth',block:'start'});});
    }
    function setThemeStockEmptyState(message) {
      const container=document.getElementById('themeStockHeatmap');
      if(window.themeStockHeatChart){window.themeStockHeatChart.dispose();window.themeStockHeatChart=null;}
      container.innerHTML='<p class="empty">'+themeHtml(message)+'</p>';
    }
    function drawThemeStockHeatmap() {
      if(!window.echarts)return;
      const select=document.getElementById('themePoolSelect'), metric=document.getElementById('themeHeatMetric').value, frequency=document.getElementById('themeHeatFrequency').value, months=finiteOrNull(document.getElementById('themeHeatRange').value)||6, container=document.getElementById('themeStockHeatmap'), info=document.getElementById('themePoolInfo');
      if(!select.value){info.textContent='当前没有可展示的已确认主题。';setThemeStockEmptyState('暂无已确认的正式 RS 成员。');document.getElementById('themeWatchMembers').innerHTML='<p class="empty">暂无题材观察成员。</p>';return;}
      const themeId=select.value, definition=(themePool.themes||[]).find(item=>item.theme_id===themeId)||{}, members=themeMembers(themeId), watchMembers=themeWatchMembers(themeId), dates=themeDates(themeId), cutoffDate=dates[dates.length-1]||'', currentRanking=themeRanking(themeId,metric,cutoffDate), currentByCode=Object.fromEntries(currentRanking.rows.map(row=>[row.ts_code,row])), sampled=themeSampledRows(themeId,metric,frequency,months), axisOf=row=>frequency==='week'?weekKey(row.trade_date):row.trade_date, lookup={};
      drawThemeWatchMembers(themeId);
      sampled.rows.forEach(row=>{const key=axisOf(row)+'|'+row.ts_code;if(!lookup[key]||lookup[key].trade_date<row.trade_date)lookup[key]=row;});
      const visible=members.slice().sort((left,right)=>{const l=finiteOrNull((currentByCode[left.ts_code]||{})[metric]),r=finiteOrNull((currentByCode[right.ts_code]||{})[metric]);if(l===null&&r===null)return left.stock_name.localeCompare(right.stock_name,'zh-CN');if(l===null)return 1;if(r===null)return -1;return r-l||left.stock_name.localeCompare(right.stock_name,'zh-CN');});
      const pendingRoles=((themePool.pendingRolesByTheme||{})[themeId]||{}),pendingRs=pendingRoles.rs_member||0,pendingWatch=pendingRoles.watch_only||0,marketCount=members.filter(item=>currentByCode[item.ts_code]).length;
      info.textContent='主题：'+(definition.name||themeId)+'；正式RS成员 '+members.length+'；观察成员 '+watchMembers.length+'；当前有行情成员 '+marketCount+'；待确认（RS/观察） '+pendingRs+'/'+pendingWatch+'；数据截止 '+(cutoffDate||'--')+'。颜色表示全市场RS，池内名次只统计已确认的正式RS成员。';
      if(!members.length||!sampled.axes.length){setThemeStockEmptyState('该主题暂无已确认成员或可用 RS 历史。');return;}
      if(!window.themeStockHeatChart){container.innerHTML='';window.themeStockHeatChart=echarts.init(container);}const chart=window.themeStockHeatChart;
      container.style.height=Math.max(390,visible.length*27+105)+'px';chart.resize();
      const rankingIndex=dates.indexOf(cutoffDate), rankingPriorDate=rankingIndex>=5?dates[rankingIndex-5]:'', rankingPrior=themeRanking(themeId,metric,rankingPriorDate);
      const memberLabel=member=>{const row=currentByCode[member.ts_code]||{},value=finiteOrNull(row[metric]),rank=currentRanking.rankByCode[member.ts_code]||null,priorRank=rankingPrior.rankByCode[member.ts_code]||null,change=rank&&priorRank?priorRank-rank:null;return member.stock_name+'（'+member.ts_code+'）｜'+metric.replace('_pct','').toUpperCase()+' '+(value===null?'--':value.toFixed(2))+'｜排名 '+(rank?rank+'/'+currentRanking.rows.length:'--')+'｜'+rankChangeText(change);};
      const data=[];visible.forEach((member,y)=>sampled.axes.forEach((axis,x)=>{const row=lookup[axis+'|'+member.ts_code],value=row?finiteOrNull(row[metric]):null;const date=row?row.trade_date:sampled.labels[axis];const ranking=themeRanking(themeId,metric,date),rank=ranking.rankByCode[member.ts_code]||null;const index=dates.indexOf(date),priorDate=index>=5?dates[index-5]:'',priorRanking=themeRanking(themeId,metric,priorDate),rankChange=rank&&priorRanking.rankByCode[member.ts_code]?priorRanking.rankByCode[member.ts_code]-rank:null;const cell=[x,y,value,member.ts_code,date,rank,ranking.rows.length,rankChange,member,row||null,priorDate];data.push(value===null?{value:cell,itemStyle:{color:'#f1f3f5'}}:cell);}));
      chart.setOption({tooltip:{formatter:point=>{const value=heatDataValues(point),member=value[8]||{},row=value[9];let text='股票：'+themeHtml(member.stock_name)+'（'+themeHtml(value[3])+'）<br>日期：'+themeHtml(value[4]);if(value[2]===null)return text+'<br>暂无有效数据';text+='<br>全市场 '+themeHtml(metric.replace('_pct','').toUpperCase())+'：'+value[2].toFixed(2)+'<br>主题内 '+themeHtml(metric.replace('_pct','').toUpperCase())+' 排名：'+value[5]+'/'+value[6]+'<br>5日主题内名次变化：'+rankChangeText(value[7])+'<br>最近涨停：'+themeHtml(member.latest_limit_up_date)+'<br>涨停次数（20/60/120）：'+themeHtml(member.limit_up_count_20d)+'/'+themeHtml(member.limit_up_count_60d)+'/'+themeHtml(member.limit_up_count_120d)+'<br>分类来源：'+themeHtml(member.classification_source)+'<br>分类理由：'+themeHtml(member.reason)+'<br>产业关系：'+themeHtml(member.industry_relation)+'<br>市场题材关系：'+themeHtml(member.market_theme_relation)+'<br>确信度：'+themeHtml(member.confidence)+'<br>确认状态：'+themeHtml(member.status)+'<br>数据截止：'+themeHtml(cutoffDate);return text;}},grid:{left:430,right:92,top:18,bottom:58},xAxis:{type:'category',data:sampled.axes.map(axis=>{const date=sampled.labels[axis];return date.slice(4,6)+'-'+date.slice(6,8);}),axisLabel:{interval:frequency==='day'?Math.max(9,Math.floor(sampled.axes.length/9)):2}},yAxis:{type:'category',data:visible.map(memberLabel),inverse:true,axisLabel:{width:405,overflow:'truncate'}},visualMap:{dimension:2,min:0,max:100,calculable:false,orient:'vertical',right:8,top:34,itemHeight:180,text:['强势','弱'],textStyle:{color:'#435168'},inRange:{color:['#173f8a','#75a8dc','#e5e7eb','#ed9a57','#c93c3c']},seriesIndex:0},series:[{type:'heatmap',data,itemStyle:{borderColor:'#fff',borderWidth:1}}]});
    }
    function populateThemePoolSelect(){const select=document.getElementById('themePoolSelect'), quick=document.getElementById('themeQuickSelect');(themePool.themes||[]).forEach(theme=>{const option=document.createElement('option');option.value=theme.theme_id;option.textContent=theme.name;select.appendChild(option);const quickOption=option.cloneNode(true);quick.appendChild(quickOption);});}
    function drawWhenOpen(sectionId, draw){const section=document.getElementById(sectionId);if(section&&section.open)requestAnimationFrame(draw);}
    populateThemePoolSelect();
    document.getElementById('heatMetric').addEventListener('change',e=>{const map={industry_rs5_pct:['day','3'],industry_rs10_pct:['day','3'],industry_rs20_pct:['day','3'],industry_rs60_pct:['day','6'],industry_rs120_pct:['week','12']}[e.target.value];document.getElementById('heatFrequency').value=map[0];document.getElementById('heatRange').value=map[1];drawWhenOpen('industryHeatSection',drawHeat);});
    ['heatFrequency','heatRange','heatFilter','heatRankChange'].forEach(id=>document.getElementById(id).addEventListener('change',()=>drawWhenOpen('industryHeatSection',drawHeat)));
    ['themePoolSelect','themeHeatMetric','themeHeatFrequency','themeHeatRange'].forEach(id=>document.getElementById(id).addEventListener('change',()=>drawWhenOpen('themeMembersSection',drawThemeStockHeatmap)));
    ['themeRotationMetric','themeRotationFrequency','themeRotationRange'].forEach(id=>document.getElementById(id).addEventListener('change',()=>drawWhenOpen('themeRotationSection',drawThemeRotationHeatmap)));
    document.getElementById('themeQuickSelect').addEventListener('change',e=>{const themeId=e.target.value;if(!themeId)return;document.getElementById('themePoolSelect').value=themeId;const section=document.getElementById('themeMembersSection');section.open=true;requestAnimationFrame(drawThemeStockHeatmap);section.scrollIntoView({behavior:'smooth',block:'start'});});
    document.getElementById('detailIndustry').addEventListener('change',e=>selectIndustry(e.target.value));
    document.querySelectorAll('[data-range]').forEach(b=>b.addEventListener('click',()=>{rangeDays=finiteOrNull(b.dataset.range)||250;drawWhenOpen('industryDetailSection',drawDetail);}));
    document.querySelectorAll('.link-filter').forEach(b=>b.addEventListener('click',()=>selectIndustry(b.dataset.industry)));
    [['industryHeatSection',drawHeat],['industryDetailSection',drawDetail],['themeRotationSection',drawThemeRotationHeatmap],['themeMembersSection',drawThemeStockHeatmap]].forEach(([id,draw])=>document.getElementById(id).addEventListener('toggle',event=>{if(event.target.open)requestAnimationFrame(draw);}));
    window.addEventListener('resize',()=>{if(heatChart)heatChart.resize();if(detailChart)detailChart.resize();if(themeRotationChart)themeRotationChart.resize();if(window.themeStockHeatChart)window.themeStockHeatChart.resize();});
    </script>
    """
    document = html_document(
        title=f"强势股雷达 {trade_date}",
        body=body,
        scripts=scripts,
        styles="""
        :root { --ink:#202631; --muted:#657084; --line:#d8e0ea; --paper:#eef2f4; --panel:#fff; --blue:#2867d6; --green:#16805e; --amber:#a66814; --red:#c84444; --violet:#6b56c8; }
        * { box-sizing:border-box; } body { margin:0; background:var(--paper); color:var(--ink); font-family:"Microsoft YaHei","PingFang SC",sans-serif; font-size:14px; }
        .page { width:min(1420px,calc(100vw - 32px)); margin:0 auto; padding:22px 0 42px; }
        header, .metric, .table-wrap, .notes { background:var(--panel); border:1px solid var(--line); border-radius:8px; }
        header { padding:20px; display:flex; justify-content:space-between; gap:16px; align-items:flex-start; }
        h1,h2,p { margin:0; } h1 { font-size:28px; letter-spacing:0; } h2 { font-size:18px; letter-spacing:0; }
        .eyebrow { color:var(--blue); font-weight:800; margin-bottom:5px; } .sub, .section-head span, small { color:var(--muted); }
        .metrics { display:grid; grid-template-columns:repeat(7,minmax(0,1fr)); gap:10px; margin-top:12px; }
        .metric { min-height:98px; padding:14px; display:flex; flex-direction:column; justify-content:flex-end; }
        .metric span { color:var(--muted); font-size:12px; } .metric strong { display:block; margin:6px 0 3px; font-size:21px; line-height:1.25; overflow-wrap:break-word; }
        section, .report-section { margin-top:18px; } .section-head { display:flex; justify-content:space-between; align-items:baseline; gap:12px; margin-bottom:8px; }
        .report-section { border:1px solid var(--line); border-radius:8px; background:var(--panel); overflow:hidden; }
        .report-section > summary { min-height:52px; padding:0 16px; display:flex; align-items:center; gap:10px; cursor:pointer; list-style:none; font-size:18px; font-weight:800; }
        .report-section > summary::-webkit-details-marker { display:none; }
        .report-section > summary::before { content:'+'; width:22px; color:var(--blue); font-size:20px; font-weight:500; }
        .report-section[open] > summary::before { content:'−'; }
        .report-section > summary small { margin-left:auto; font-size:13px; font-weight:400; }
        .section-content { padding:4px 14px 14px; }
        .theme-entry { min-height:58px; padding:10px 14px; border:1px solid var(--line); border-radius:8px; background:var(--panel); display:flex; align-items:center; justify-content:space-between; gap:16px; }
        .theme-entry div { display:flex; align-items:baseline; gap:12px; } .theme-entry h2 { white-space:nowrap; } .theme-entry span { color:var(--muted); }
        .theme-entry label { display:flex; align-items:center; gap:7px; white-space:nowrap; }
        .filters { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:0 0 10px; }
        select, button { height:34px; border:1px solid var(--line); border-radius:6px; background:#fff; color:var(--ink); padding:0 10px; }
        button { cursor:pointer; } .link-filter { height:auto; padding:0; border:0; background:transparent; color:var(--blue); font-weight:800; }
        .table-wrap { overflow:auto; } .strong-stock-table-wrap { max-height:min(70vh,620px); } .strong-stock-table-wrap thead th { position:sticky; top:0; z-index:1; } .chart { height:390px; background:#fff; border:1px solid var(--line); border-radius:8px; } .rotation-controls { display:flex; flex-wrap:wrap; gap:8px; margin:0 0 10px; align-items:center; } .rotation-threshold { display:flex; align-items:center; gap:5px; color:var(--muted); } .rotation-note { margin:0 0 10px; color:var(--muted); line-height:1.6; } .industry-summary { padding:9px 10px; margin:0 0 10px; background:#fff; border:1px solid var(--line); color:var(--muted); white-space:normal; line-height:1.7; } .spark { width:80px; height:24px; vertical-align:middle; } .spark polyline { fill:none; stroke:#2867d6; stroke-width:1.5; } table { width:100%; border-collapse:collapse; } th,td { padding:9px 10px; border-bottom:1px solid #e8edf3; white-space:nowrap; text-align:right; font-size:13px; }
        th { background:#f7f9fc; color:#435168; font-size:12px; cursor:pointer; user-select:none; } th::after { content:'\\2195'; color:#9aa6b8; font-size:10px; margin-left:4px; } th[data-order="asc"]::after { content:'\\2191'; color:var(--blue); } th[data-order="desc"]::after { content:'\\2193'; color:var(--blue); } th:first-child, td:first-child, th:nth-child(2), td:nth-child(2), th:nth-child(3), td:nth-child(3), th:nth-child(4), td:nth-child(4) { text-align:left; }
        tr:hover { background:#f9fbff; } tr[hidden] { display:none; }
        .badge { display:inline-flex; align-items:center; min-height:24px; padding:3px 7px; border-radius:6px; border:1px solid var(--line); background:#f7f9fb; font-weight:800; font-size:12px; }
        .theme-subhead { margin:14px 0 7px; font-size:15px; } .theme-watch-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:10px; } .theme-watch-item { padding:12px; border:1px solid var(--line); border-radius:8px; background:#fff; } .theme-watch-item strong { display:inline-block; margin-right:7px; } .theme-watch-item p,.theme-watch-item ul { margin:8px 0 0; color:var(--muted); line-height:1.55; } .theme-watch-item ul { padding-left:18px; } .theme-watch-item a { color:var(--blue); } .watch-badge { display:inline-block; padding:2px 6px; border:1px solid #edc580; border-radius:5px; background:#fff7eb; color:#925c0f; font-size:12px; }
        .state-CORE_STRONG { color:var(--green); background:#eff9f4; } .state-ACCELERATING,.state-BREAKOUT { color:var(--blue); background:#eef5ff; } .state-HIGH_TIGHT { color:var(--violet); background:#f3f1ff; } .state-STRONG_WEAKENING,.state-WEAKENING { color:var(--amber); background:#fff7eb; }
        .empty { padding:22px; color:var(--muted); background:#fff; border:1px solid var(--line); border-radius:8px; }
        .notes { padding:16px; } .notes ul { margin:10px 0 0; padding-left:20px; color:var(--muted); line-height:1.7; }
        @media (max-width:1100px) { .metrics { grid-template-columns:repeat(3,minmax(0,1fr)); } }
        @media (max-width:720px) { .page { width:min(100vw - 20px,1420px); } .metrics { grid-template-columns:repeat(2,minmax(0,1fr)); } header { padding:16px; } h1 { font-size:24px; } .theme-entry,.theme-entry div { align-items:flex-start; flex-direction:column; } .report-section > summary { align-items:flex-start; padding:14px; flex-wrap:wrap; } .report-section > summary small { width:100%; margin-left:32px; } }
        """,
        head_extra=_echarts_script_tag() + '<link rel="icon" href="data:,">',
    )
    target.write_text(document, encoding="utf-8")
    return target
