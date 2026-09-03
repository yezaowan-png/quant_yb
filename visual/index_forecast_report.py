"""HTML report for index forecast outputs."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from analysis.technical_structure import TechnicalStructureService
from data.market_benchmark import (
    MARKET_BENCHMARK_CHART_KEY,
    MARKET_BENCHMARK_NAME,
    MARKET_BENCHMARK_QUALITY_FLAG,
    MARKET_BENCHMARK_SYMBOL,
)
from visual.components import html_document, inline_script, to_compact_json
from visual.index_report import _echarts_script_tag
from visual.technical_structure_renderer import TechnicalStructureRenderer


_CSS = """
* { box-sizing: border-box; }
body {
  margin: 0;
  background: #f5f6f8;
  color: #172033;
  font-family: "Microsoft YaHei", "Noto Sans SC", "PingFang SC", sans-serif;
}
.shell { width: min(1440px, calc(100vw - 40px)); margin: 0 auto; padding: 26px 0 42px; }
.topbar { display: flex; justify-content: space-between; gap: 18px; align-items: flex-end; border-bottom: 1px solid #d9e0ea; padding-bottom: 18px; }
h1 { margin: 0; font-size: 34px; line-height: 1.1; letter-spacing: 0; }
.sub { margin-top: 8px; color: #69748a; font-size: 13px; }
.top-actions { display:flex; align-items:center; justify-content:flex-end; flex-wrap:wrap; gap:8px; margin-top:10px; }
.top-actions a { display:inline-flex; align-items:center; min-height:32px; padding:0 12px; border:1px solid #d9e0ea; background:#fff; color:#465268; text-decoration:none; font-size:12px; font-weight:800; }
.top-actions a.primary { color:#fff; background:#172033; border-color:#172033; }
.top-actions a:hover { border-color:#8796b2; box-shadow:0 0 0 1px #8796b2 inset; }
.badge { min-height: 42px; display: inline-flex; align-items: center; padding: 0 16px; color: #fff; background: #172033; font-weight: 900; }
.badge.bull, .badge.positive { background: #c94343; }
.badge.bear, .badge.conservative { background: #168457; }
.badge.neutral { background: #69748a; }
.badge.neutral { color: #fff; }
.cards { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 18px; }
.card { position:relative; background: #fff; border: 1px solid #d9e0ea; padding: 14px 16px; min-height: 96px; }
.card span { color: #69748a; font-size: 12px; }
.card strong { display: block; margin-top: 9px; font-size: 25px; }
.card small { display: block; margin-top: 8px; color: #69748a; font-size: 12px; line-height: 1.55; }
.card-tooltip { display:none; position:absolute; z-index:80; left:14px; right:14px; top:calc(100% - 8px); min-width:280px; padding:11px 12px; border:1px solid #cfd7e5; background:#fff; box-shadow:0 12px 28px rgba(23,32,51,.18); }
.card:hover { border-color:#8796b2; box-shadow:0 0 0 1px #8796b2 inset; }
.card:hover .card-tooltip, .card:focus-within .card-tooltip { display:block; }
.card-tooltip-title { display:block; margin-bottom:7px; color:#465268; font-size:12px; font-weight:900; }
.card-tooltip-row { display:flex; justify-content:space-between; gap:12px; padding:5px 0; border-top:1px solid #edf0f5; color:#69748a; font-size:12px; line-height:1.35; }
.card-tooltip-row:first-of-type { border-top:0; }
.card-tooltip-row b { flex:0 0 auto; color:#172033; font-weight:900; white-space:nowrap; }
.panel { background: #fff; border: 1px solid #d9e0ea; margin-top: 20px; overflow: hidden; }
.panel-head { display: flex; justify-content: space-between; gap: 12px; padding: 16px 18px; border-bottom: 1px solid #d9e0ea; }
.panel-head h2 { margin: 0; font-size: 21px; }
.panel-head span { color: #69748a; font-size: 13px; }
.chart { height: 420px; padding: 12px 16px; }
.chart.small { height: 320px; }
.chart.index-indicator { height:280px; padding-top:4px; }
#forecast-kline { height: 860px; }
.kline-subchart-head { display:flex; justify-content:space-between; gap:12px; margin:8px 18px 0; padding:10px 0 6px; border-top:1px solid #edf0f5; }
.kline-subchart-head strong { font-size:14px; }
.kline-subchart-head span { color:#69748a; font-size:12px; }
.kline-control-grid { display:grid; grid-template-columns:minmax(320px, .9fr) minmax(420px, 1.1fr); gap:12px; padding:12px 18px 0; }
.kline-control-group { min-width:0; border:1px solid #e3e8f0; background:#fbfcfe; padding:10px 12px; }
.kline-control-title { display:block; margin-bottom:8px; color:#465268; font-size:12px; font-weight:800; }
.kline-tools { display:flex; flex-wrap:wrap; align-items:center; gap:10px; color:#69748a; font-size:12px; }
.kline-structure-options { display:grid; grid-template-columns:repeat(4, minmax(108px, 1fr)); gap:8px; overflow:visible; }
.forecast-kline-toolbar { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:10px 18px; margin:12px 18px 0; padding:10px 12px; border:1px solid #e3e8f0; background:#fbfcfe; }
.forecast-kline-toolbar .kline-tools { flex:1 1 460px; }
.forecast-manual-tools { display:flex; flex:2 1 620px; flex-wrap:wrap; align-items:center; justify-content:flex-end; gap:7px; color:#69748a; font-size:12px; }
.forecast-manual-tools strong { color:#465268; font-size:12px; }
.forecast-manual-btn { border:1px solid #d9e0ea; background:#fff; color:#465268; padding:6px 12px; cursor:pointer; font-weight:800; }
.forecast-manual-btn:hover { border-color:#b9c7f0; color:#3157c8; }
.forecast-manual-btn.active { color:#fff; background:#2f6df6; border-color:#2f6df6; }
.forecast-manual-btn.danger { color:#c94343; }
.forecast-manual-status { flex:1 1 100%; color:#69748a; text-align:right; font-size:12px; line-height:1.45; }
.forecast-integrated-note { margin:8px 18px 0; color:#69748a; font-size:12px; line-height:1.6; }
.structure-filter { position:relative; min-width:0; }
.structure-filter > summary { display:flex; min-height:34px; align-items:center; justify-content:space-between; gap:6px; padding:6px 9px; border:1px solid #d9e0ea; background:#fff; color:#465268; cursor:pointer; list-style:none; white-space:nowrap; }
.structure-filter > summary::-webkit-details-marker { display:none; }
.structure-filter > summary::after { content:'\\25BE'; color:#8a94a8; font-size:11px; }
.structure-filter[open] > summary { border-color:#8796b2; box-shadow:0 0 0 1px #8796b2 inset; }
.structure-filter-count { margin-left:auto; color:#69748a; font-size:11px; }
.structure-filter-menu { position:absolute; z-index:30; top:calc(100% + 4px); left:0; width:max(280px, 100%); max-height:300px; overflow:auto; padding:8px; border:1px solid #cfd7e5; background:#fff; box-shadow:0 10px 26px rgba(23,32,51,.16); }
.structure-filter-actions { display:flex; gap:6px; padding-bottom:7px; border-bottom:1px solid #edf0f5; }
.structure-filter-actions button { border:1px solid #d9e0ea; background:#fbfcfe; color:#465268; padding:4px 9px; cursor:pointer; font-size:12px; }
.structure-filter-list { display:grid; gap:2px; padding-top:6px; }
.structure-filter-list label { display:flex; align-items:flex-start; gap:7px; padding:6px; color:#465268; cursor:pointer; line-height:1.35; white-space:normal; }
.structure-filter-list label:hover { background:#f3f6fb; }
.structure-filter-list input { flex:0 0 auto; margin:2px 0 0; }
.structure-filter-empty { padding:10px 6px; color:#8a94a8; font-size:12px; }
.indicator-switches { display:flex; align-items:center; gap:6px; }
.indicator-switch-btn, .industry-indicator-switch { border:1px solid #d9e0ea; background:#fff; color:#69748a; padding:6px 14px; cursor:pointer; }
.indicator-switch-btn.active, .industry-indicator-switch.active { color:#fff; background:#172033; border-color:#172033; }
.industry-row-clickable { cursor:pointer; }
.industry-row-clickable:hover { background:#f3f6fb; }
.industry-row-clickable.active { background:#eef4ff; box-shadow:inset 3px 0 0 #2f6df6; }
.industry-link { color:#2f6df6; font-weight:800; text-decoration:none; }
.industry-chart-head { display:flex; justify-content:space-between; gap:12px; align-items:center; margin:14px 18px 0; padding-top:12px; border-top:1px solid #edf0f5; }
.industry-chart-title { color:#172033; font-weight:900; }
.industry-chart-title small { display:block; margin-top:4px; color:#69748a; font-weight:400; font-size:12px; }
.industry-chart-empty { margin:14px 18px; padding:14px; color:#69748a; border:1px dashed #d9e0ea; background:#fbfcfe; }
.chart.industry-indicator { height:260px; padding-top:4px; }
.index-compare-tools { display:flex; flex-wrap:wrap; align-items:center; gap:7px; padding:12px 18px 0; color:#69748a; font-size:12px; }
.index-compare-window { border:1px solid #d9e0ea; background:#fff; color:#69748a; padding:6px 12px; cursor:pointer; }
.index-compare-window.active { color:#fff; background:#172033; border-color:#172033; }
.index-strength-ranking { display:flex; flex-wrap:wrap; gap:7px; margin:0 18px 14px; padding:10px 12px; border:1px solid #e3e8f0; background:#fbfcfe; color:#69748a; font-size:12px; }
.index-strength-ranking strong { color:#465268; margin-right:3px; }
.index-strength-item { display:inline-flex; gap:4px; align-items:center; padding:4px 7px; border:1px solid #e3e8f0; background:#fff; }
.index-strength-item.up { color:#c94343; }
.index-strength-item.down { color:#168457; }
.breadth-metric-grid { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:10px; padding:16px 18px 4px; }
.breadth-metric { border:1px solid #e3e8f0; background:#fbfcfe; min-width:0; }
.breadth-metric > summary { display:grid; grid-template-columns:minmax(0, 1fr) auto 12px; align-items:center; gap:10px; padding:11px 12px; cursor:pointer; list-style:none; }
.breadth-metric > summary::-webkit-details-marker { display:none; }
.breadth-metric > summary::after { content:'\\25BE'; color:#8a94a8; font-size:11px; justify-self:end; grid-column:3; }
.breadth-metric[open] > summary { border-bottom:1px solid #edf0f5; }
.breadth-metric-title { color:#465268; font-size:13px; font-weight:800; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.breadth-metric-value { grid-column:2; color:#172033; font-size:14px; font-weight:900; white-space:nowrap; }
.breadth-metric-detail { padding:0 12px 12px; color:#69748a; font-size:12px; line-height:1.65; }
.breadth-subhead { display:flex; justify-content:space-between; gap:12px; align-items:flex-end; margin:14px 18px 0; padding-top:12px; border-top:1px solid #edf0f5; }
.breadth-subhead strong { font-size:15px; }
.breadth-subhead span { color:#69748a; font-size:12px; }
.chart.breadth-distribution-chart { height:320px; padding-top:4px; }
.chart.breadth-ad-chart { height:560px; }
.risk-explain-list { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:10px; padding:16px 18px 4px; }
.risk-explain-item { border:1px solid #e3e8f0; background:#fbfcfe; min-width:0; }
.risk-explain-item > summary { display:grid; grid-template-columns:minmax(0, 1fr) auto 12px; align-items:center; gap:10px; padding:11px 12px; cursor:pointer; list-style:none; }
.risk-explain-item > summary::-webkit-details-marker { display:none; }
.risk-explain-item > summary::after { content:'\\25BE'; color:#8a94a8; font-size:11px; justify-self:end; grid-column:3; }
.risk-explain-item[open] > summary { border-bottom:1px solid #edf0f5; }
.risk-explain-name { color:#465268; font-size:13px; font-weight:800; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.risk-explain-value { grid-column:2; color:#172033; font-size:14px; font-weight:900; white-space:nowrap; }
.risk-explain-detail { padding:0 12px 12px; color:#69748a; font-size:12px; line-height:1.65; }
.sector-sample small { display:block; margin-top:3px; color:#69748a; font-size:11px; line-height:1.35; white-space:normal; }
.kline-structure-note { padding:8px 18px 0; color:#69748a; font-size:12px; line-height:1.6; }
.kline-period-btn { border:1px solid #d9e0ea; background:#fff; color:#69748a; padding:6px 12px; cursor:pointer; }
.kline-period-btn.active { color:#fff; background:#172033; border-color:#172033; }
.kline-index-select { width:300px; max-width:100%; border:1px solid #d9e0ea; background:#fff; color:#172033; padding:6px 10px; min-width:150px; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; padding: 16px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 10px 12px; border-bottom: 1px solid #edf0f5; text-align: right; white-space: nowrap; }
th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) { text-align: left; }
th { color: #69748a; background: #fbfcfe; font-weight: 700; }
.up { color: #c94343; font-weight: 800; }
.down { color: #168457; font-weight: 800; }
.neutral { color: #69748a; font-weight: 800; }
.note { margin-top: 18px; padding: 14px 16px; background: #fff; border: 1px solid #d9e0ea; color: #69748a; font-size: 13px; line-height: 1.7; }
.headline { color: #172033; font-size: 16px; font-weight: 700; line-height: 1.8; }
.legacy > summary { cursor: pointer; list-style: none; padding: 16px 18px; font-size: 21px; font-weight: 800; border-bottom: 1px solid #d9e0ea; }
.legacy[open] > summary { background: #fbfcfe; }
.flag { display: inline-block; margin: 3px 5px 3px 0; padding: 4px 8px; border: 1px solid #d9e0ea; background: #fbfcfe; font-size: 12px; }
.muted { color: #69748a; }
.details-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; padding: 12px 16px 18px; }
.details-grid details { border: 1px solid #edf0f5; background: #fbfcfe; padding: 10px 12px; }
.details-grid summary { cursor: pointer; font-weight: 800; }
.compact-note { padding: 10px 12px; color: #69748a; font-size: 12px; }
.screen-kicker { display:inline-flex; align-items:center; min-height:24px; margin-right:8px; padding:0 8px; border:1px solid #cfd7e5; background:#f3f6fb; color:#465268; font-size:11px; font-weight:900; letter-spacing:.04em; }
.summary-lines { margin:0; padding:14px 20px 14px 42px; background:#fff; border:1px solid #d9e0ea; color:#263148; font-size:14px; line-height:1.75; }
.summary-lines li + li { margin-top:4px; }
.summary-meta { display:flex; flex-wrap:wrap; gap:7px; margin-top:10px; color:#69748a; font-size:11px; }
.summary-meta span { padding:3px 7px; border:1px solid #e3e8f0; background:#fbfcfe; }
.evidence-folds { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:10px; margin-top:12px; }
.evidence-folds details { min-width:0; border:1px solid #d9e0ea; background:#fff; }
.evidence-folds summary { display:flex; justify-content:space-between; gap:8px; padding:10px 12px; cursor:pointer; list-style:none; font-size:12px; font-weight:800; }
.evidence-folds summary::-webkit-details-marker { display:none; }
.evidence-body { padding:0 12px 12px; color:#69748a; font-size:12px; line-height:1.65; }
.evidence-body strong { color:#465268; }
.state-chip { display:inline-flex; align-items:center; min-height:23px; padding:2px 8px; border:1px solid #d9e0ea; background:#f6f8fb; color:#465268; font-size:11px; font-weight:800; white-space:nowrap; }
.state-chip.risk, .state-chip.stale, .state-chip.missing { border-color:#f0c6c6; background:#fff3f3; color:#a83a3a; }
.state-chip.good, .state-chip.fresh { border-color:#bfe0d1; background:#f1fbf6; color:#13704b; }
.state-chip.warn { border-color:#ead9ad; background:#fff9e9; color:#8a6417; }
.metric-strip { display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:10px; padding:16px 18px 4px; }
.metric-tile { min-width:0; border:1px solid #e3e8f0; background:#fbfcfe; padding:11px 12px; }
.metric-tile span { display:block; color:#69748a; font-size:11px; }
.metric-tile strong { display:block; margin-top:7px; color:#172033; font-size:18px; }
.metric-tile small { display:block; margin-top:6px; color:#69748a; line-height:1.45; }
.v2-table-wrap { overflow-x:auto; padding:0 16px 16px; }
.v2-table-wrap table { min-width:1040px; }
.v2-table-wrap.compact table { min-width:760px; }
.subpanel-title { display:flex; justify-content:space-between; gap:12px; align-items:flex-end; margin:14px 18px 0; padding:12px 0 8px; border-top:1px solid #edf0f5; }
.subpanel-title strong { font-size:15px; }
.subpanel-title span { color:#69748a; font-size:12px; }
.layered-breadth-tools { display:flex; flex-wrap:wrap; align-items:center; gap:8px; margin:12px 18px 0; }
.layered-breadth-tools strong { margin-right:4px; font-size:13px; }
.layered-breadth-tools span { margin-left:6px; color:#69748a; font-size:12px; }
.layered-breadth-switch { border:1px solid #d9e0ea; background:#fff; color:#69748a; padding:6px 10px; cursor:pointer; }
.layered-breadth-switch.active { color:#fff; background:#172033; border-color:#172033; }
.lift-tools { display:flex; flex-wrap:wrap; align-items:center; gap:8px; padding:12px 18px 0; color:#69748a; font-size:12px; }
.lift-tools strong { color:#465268; margin-right:4px; }
.lift-symbol-btn { border:1px solid #d9e0ea; background:#fff; color:#69748a; padding:6px 10px; cursor:pointer; }
.lift-symbol-btn.active { color:#fff; background:#172033; border-color:#172033; }
.lift-symbol-panel { display:none; }
.lift-symbol-panel.active { display:block; }
.chart.layered-chart { height:390px; }
.chart.distribution-quantile-chart { height:310px; }
.chart.state-history-chart { height:430px; }
.leadership-callout { margin:14px 18px 0; padding:13px 14px; border-left:4px solid #2f6df6; background:#f3f6fb; color:#465268; line-height:1.7; }
.leadership-callout strong { color:#172033; }
.research-warning { margin:14px 18px 0; padding:12px 14px; border:1px solid #ead9ad; background:#fff9e9; color:#755515; font-weight:800; line-height:1.6; }
.research-grid { display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:10px; padding:12px 18px 4px; }
.research-item { border:1px solid #ead9ad; background:#fffdf5; padding:11px 12px; }
.research-item span { display:block; color:#8a6417; font-size:11px; }
.research-item strong { display:block; margin-top:6px; color:#5f4512; font-size:17px; }
.research-item small { display:block; margin-top:6px; color:#8a6d32; line-height:1.45; }
.quality-matrix { display:grid; grid-template-columns:1.15fr .85fr; gap:14px; padding:16px; }
.quality-block { min-width:0; border:1px solid #e3e8f0; background:#fff; }
.quality-block h3 { margin:0; padding:11px 12px; border-bottom:1px solid #edf0f5; background:#fbfcfe; font-size:14px; }
.quality-flags { padding:12px; }
.empty-v2 { margin:14px 18px; padding:14px; border:1px dashed #cfd7e5; background:#fbfcfe; color:#69748a; font-size:12px; }
@media (max-width: 1100px) { .kline-control-grid { grid-template-columns:1fr; } }
@media (max-width: 980px) { .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); } .grid, .quality-matrix { grid-template-columns: 1fr; } .metric-strip { grid-template-columns:repeat(2, minmax(0, 1fr)); } .evidence-folds { grid-template-columns:repeat(2, minmax(0, 1fr)); } .research-grid { grid-template-columns:repeat(2, minmax(0, 1fr)); } .panel { overflow-x: auto; } }
@media (max-width: 620px) { .shell { width: min(100vw - 24px, 1440px); } .topbar { align-items: flex-start; flex-direction: column; } .cards, .metric-strip, .evidence-folds, .research-grid { grid-template-columns: 1fr; } .breadth-metric-grid, .risk-explain-list { grid-template-columns:1fr; } .kline-structure-options { grid-template-columns:repeat(2, minmax(112px, 1fr)); } .kline-subchart-head { align-items:flex-start; flex-direction:column; } }
"""


def _fmt_pct(value: Any, digits: int = 2) -> str:
    try:
        if pd.isna(value):
            return "--"
        return f"{float(value) * 100:+.{digits}f}%"
    except Exception:
        return "--"


def _fmt_ratio_pct(value: Any, digits: int = 1) -> str:
    try:
        if pd.isna(value):
            return "--"
        return f"{float(value) * 100:.{digits}f}%"
    except Exception:
        return "--"


def _fmt_multiple(value: Any, digits: int = 2) -> str:
    try:
        if pd.isna(value):
            return "--"
        return f"{float(value):.{digits}f}倍"
    except Exception:
        return "--"


def _fmt_num(value: Any, digits: int = 2) -> str:
    try:
        if pd.isna(value):
            return "--"
        return f"{float(value):,.{digits}f}"
    except Exception:
        return "--"


def _fmt_signed_num(value: Any, digits: int = 3) -> str:
    try:
        if pd.isna(value):
            return "--"
        return f"{float(value):+.{digits}f}"
    except Exception:
        return "--"


def _fmt_int(value: Any) -> str:
    try:
        if pd.isna(value):
            return "--"
        return f"{int(float(value)):,}"
    except Exception:
        return "--"


def _fmt_breadth_triplet(row: pd.Series) -> str:
    return (
        f"{_fmt_int(row.get('breadth_up'))}/"
        f"{_fmt_int(row.get('breadth_flat'))}/"
        f"{_fmt_int(row.get('breadth_down'))}"
    )


def _fmt_breadth_triplet_html(row: pd.Series) -> str:
    up = escape(_fmt_int(row.get("breadth_up")))
    flat = escape(_fmt_int(row.get("breadth_flat")))
    down = escape(_fmt_int(row.get("breadth_down")))
    if up == "--" and flat == "--" and down == "--":
        return "--/--/--"
    return f"<span class='up'>{up}</span>/{flat}/<span class='down'>{down}</span>"


def _signal_text(signal: str) -> str:
    return {
        "bull": "偏强", "neutral": "中性", "bear": "偏弱",
        "positive": "积极", "conservative": "保守",
    }.get(str(signal), str(signal))


def _style_state_text(value: Any) -> str:
    return {
        "strong": "强势", "outperforming": "相对占优", "recovering": "修复",
        "neutral": "中性", "pullback": "回调", "weak": "弱势", "unknown": "数据不足",
    }.get(str(value), "数据不足")


def _momentum_text(value: Any) -> str:
    return {
        "mid_leading_short_pullback": "中期领先，短期回撤",
        "short_rebound_mid_weak": "短期反弹，中期仍弱",
        "strengthening": "短中期同步增强", "weakening": "短中期同步走弱",
        "long_strong_mid_cooling": "长期较强，中期降温", "mixed": "多周期分化",
    }.get(str(value), "数据不足")


def _divergence_text(value: Any) -> str:
    return {
        "stocks_stronger": "个股强", "large_cap_stronger": "权重强",
        "synchronized": "同步", "unknown": "数据不足",
    }.get(str(value), "数据不足")


def _tone(value: Any, signal: str | None = None) -> str:
    if signal:
        return {
            "bull": "up", "positive": "up", "bear": "down",
            "conservative": "down", "neutral": "neutral",
        }.get(signal, "neutral")
    try:
        value = float(value)
    except Exception:
        return ""
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return "neutral"


def _series_payload(df: pd.DataFrame, column: str, digits: int = 4) -> list[Any]:
    if column not in df.columns:
        return [None for _ in range(len(df))]
    values = pd.to_numeric(df[column], errors="coerce").round(digits)
    return [None if pd.isna(value) else float(value) for value in values.tolist()]


def _scaled_series_payload(df: pd.DataFrame, column: str, scale: float, digits: int = 4) -> list[Any]:
    return [None if value is None else round(float(value) * scale, digits) for value in _series_payload(df, column, digits + 2)]


def _index_technical_indicator_payload(bars: pd.DataFrame) -> dict[str, list[Any]]:
    """Calculate chart-only volume, amount, KDJ and MACD for one index timeframe."""
    close = pd.to_numeric(bars["close"], errors="coerce")
    high = pd.to_numeric(bars["high"], errors="coerce")
    low = pd.to_numeric(bars["low"], errors="coerce")
    volume_source = bars["volume"] if "volume" in bars.columns else pd.Series(np.nan, index=bars.index)
    amount_source = bars["amount"] if "amount" in bars.columns else pd.Series(np.nan, index=bars.index)
    volume = pd.to_numeric(volume_source, errors="coerce")
    amount = pd.to_numeric(amount_source, errors="coerce")
    if amount.isna().all():
        amount = close * volume

    low9 = low.rolling(9, min_periods=9).min()
    high9 = high.rolling(9, min_periods=9).max()
    rsv = (close - low9) / (high9 - low9).replace(0, np.nan) * 100.0
    k = rsv.rolling(3, min_periods=3).mean()
    d = k.rolling(3, min_periods=3).mean()
    j = 3.0 * k - 2.0 * d

    ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False, min_periods=9).mean()
    macd_hist = 2.0 * (dif - dea)
    frame = pd.DataFrame(
        {
            "volume": volume,
            "volume_ma5": volume.rolling(5, min_periods=5).mean(),
            "volume_ma20": volume.rolling(20, min_periods=20).mean(),
            "amount": amount,
            "amount_ma5": amount.rolling(5, min_periods=5).mean(),
            "amount_ma20": amount.rolling(20, min_periods=20).mean(),
            "kdj_k": k,
            "kdj_d": d,
            "kdj_j": j,
            "macd_dif": dif,
            "macd_dea": dea,
            "macd_hist": macd_hist,
        }
    )
    return {
        "volume": _series_payload(frame, "volume", 2),
        "volume_ma5": _series_payload(frame, "volume_ma5", 2),
        "volume_ma20": _series_payload(frame, "volume_ma20", 2),
        "amount": _series_payload(frame, "amount", 2),
        "amount_ma5": _series_payload(frame, "amount_ma5", 2),
        "amount_ma20": _series_payload(frame, "amount_ma20", 2),
        "kdj_k": _series_payload(frame, "kdj_k", 4),
        "kdj_d": _series_payload(frame, "kdj_d", 4),
        "kdj_j": _series_payload(frame, "kdj_j", 4),
        "macd_dif": _series_payload(frame, "macd_dif", 6),
        "macd_dea": _series_payload(frame, "macd_dea", 6),
        "macd_hist": _series_payload(frame, "macd_hist", 6),
    }


def _chart_payload(features: pd.DataFrame, predictions: pd.DataFrame) -> dict[str, Any]:
    merged = features.merge(
        predictions[[
            "trade_date", "market_score", "predicted_opportunity_score",
            "predicted_risk_score", "environment_signal",
        ]],
        on="trade_date",
        how="left",
    )
    dates = merged["trade_date"].astype(str).tolist()
    ohlc = [
        [round(float(o), 2), round(float(c), 2), round(float(l), 2), round(float(h), 2)]
        for o, c, l, h in merged[["open", "close", "low", "high"]].fillna(0).values.tolist()
    ]
    return {
        "dates": dates,
        "ohlc": ohlc,
        "score": _series_payload(merged, "market_score"),
        "opportunity": _series_payload(merged, "predicted_opportunity_score"),
        "risk": _series_payload(merged, "predicted_risk_score"),
        "ma20": _series_payload(merged, "ma20", 2),
        "ma60": _series_payload(merged, "ma60", 2),
        "ma120": _series_payload(merged, "ma120", 2),
        "high20": [None if pd.isna(value) else round(float(value), 2) for value in pd.to_numeric(merged["close"], errors="coerce").rolling(20, min_periods=20).max()],
        "low20": [None if pd.isna(value) else round(float(value), 2) for value in pd.to_numeric(merged["close"], errors="coerce").rolling(20, min_periods=20).min()],
        "amount": _series_payload(merged, "amount", 2),
        "kdj_k": _scaled_series_payload(merged, "kdj_k", 100.0),
        "kdj_d": _scaled_series_payload(merged, "kdj_d", 100.0),
        "kdj_j": _scaled_series_payload(merged, "kdj_j", 100.0),
        "macd_dif": _series_payload(merged, "macd_dif_norm", 6),
        "macd_dea": _series_payload(merged, "macd_dea_norm", 6),
        "macd_hist": _series_payload(merged, "macd_hist_norm", 6),
        "ad_slope_5": _series_payload(merged, "ad_slope_5"),
        "ad_slope_20": _series_payload(merged, "ad_slope_20"),
        "nhnl_slope_5": _series_payload(merged, "nhnl_slope_5"),
        "nhnl_slope_20": _series_payload(merged, "nhnl_slope_20"),
    }


def _technical_kline_payload(
    features: pd.DataFrame,
    symbol: str,
    technical_structure_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = features.copy()
    if "date" not in source.columns and "trade_date" in source.columns:
        source = source.rename(columns={"trade_date": "date"})
    if "volume" not in source.columns:
        source["volume"] = source["vol"] if "vol" in source.columns else np.nan
    if "amount" not in source.columns:
        source["amount"] = np.nan
    config = technical_structure_config or {}
    service = TechnicalStructureService(config, cache_dir=config.get("cache_dir"))
    results = service.analyze_multi_timeframe(
        symbol=symbol,
        asset_type="index",
        timeframes=["1d", "1w", "1mo"],
        ohlcv=source,
        adjustment="none",
    )
    renderer = TechnicalStructureRenderer()
    payload: dict[str, Any] = {}
    for timeframe, result in results.items():
        bars = pd.DataFrame(result.bars)
        if bars.empty:
            payload[timeframe] = {"symbol": symbol, "dates": [], "ohlc": [], "technicalStructureSeries": []}
            continue
        dates = bars["date"].astype(str).tolist()
        close = pd.to_numeric(bars["close"], errors="coerce")
        indicator_payload = _index_technical_indicator_payload(bars)
        payload[timeframe] = {
            "symbol": symbol,
            "dates": dates,
            "ohlc": [
                [round(float(o), 2), round(float(c), 2), round(float(l), 2), round(float(h), 2)]
                for o, c, l, h in bars[["open", "close", "low", "high"]].values.tolist()
            ],
            "ma20": _series_payload(pd.DataFrame({"value": close.rolling(20, min_periods=20).mean()}), "value", 2),
            "ma60": _series_payload(pd.DataFrame({"value": close.rolling(60, min_periods=60).mean()}), "value", 2),
            "ma120": _series_payload(pd.DataFrame({"value": close.rolling(120, min_periods=120).mean()}), "value", 2),
            **indicator_payload,
            "technical_structure": result.to_dict(),
            "technicalStructureSeries": renderer.build_multi_timeframe_series(
                results,
                chart_timeframe=timeframe,
                date_axis=dates,
                options={"include_broken": True, "include_expired": True},
            ),
        }
    return payload


def _technical_index_kline_payload(
    features: pd.DataFrame,
    primary_symbol: str,
    structure: dict[str, Any],
    index_frames: dict[str, pd.DataFrame] | None,
    technical_structure_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build switchable K-line/structure payloads for available official indices."""
    primary = str(primary_symbol).upper()
    names_by_symbol = {
        str(item.get("symbol", "")).upper(): str(item.get("name") or item.get("symbol") or "")
        for item in (structure.get("indices") or {}).values()
        if item.get("symbol")
        and item.get("available")
        and (not item.get("synthetic") or str(item.get("symbol")).upper() == MARKET_BENCHMARK_SYMBOL)
    }
    names_by_symbol.setdefault(primary, primary)
    as_of = pd.to_datetime(structure.get("date"), errors="coerce")

    def clip(frame: pd.DataFrame) -> pd.DataFrame:
        work = frame.copy()
        date_column = "date" if "date" in work.columns else "trade_date" if "trade_date" in work.columns else None
        if date_column is None or pd.isna(as_of):
            return work
        dates = pd.to_datetime(work[date_column], errors="coerce")
        return work.loc[dates.notna() & dates.le(as_of)].copy()

    source_frames: dict[str, pd.DataFrame] = {primary: clip(features)}
    for raw_symbol, frame in (index_frames or {}).items():
        symbol = str(raw_symbol).upper()
        if symbol in names_by_symbol and frame is not None and not frame.empty:
            source_frames[symbol] = clip(frame)

    ordered_symbols = [
        str(item.get("symbol")).upper()
        for item in (structure.get("indices") or {}).values()
        if item.get("available")
        and (not item.get("synthetic") or str(item.get("symbol")).upper() == MARKET_BENCHMARK_SYMBOL)
        and str(item.get("symbol", "")).upper() in source_frames
    ]
    if primary not in ordered_symbols:
        ordered_symbols.insert(0, primary)

    payload: dict[str, Any] = {}
    for symbol in dict.fromkeys(ordered_symbols):
        frame = source_frames.get(symbol)
        if frame is None or frame.empty:
            continue
        clipped = frame.copy()
        if clipped.empty:
            continue
        payload[symbol] = {
            "symbol": symbol,
            "name": names_by_symbol.get(symbol, symbol),
            "timeframes": _technical_kline_payload(clipped, symbol, technical_structure_config),
        }
    return payload


def _plain_daily_kline_payload(frame: pd.DataFrame) -> dict[str, Any]:
    source = frame.copy()
    if "date" not in source.columns and "trade_date" in source.columns:
        source = source.rename(columns={"trade_date": "date"})
    if "volume" not in source.columns:
        source["volume"] = source["vol"] if "vol" in source.columns else np.nan
    if "amount" not in source.columns:
        source["amount"] = np.nan
    source["date"] = pd.to_datetime(source["date"], errors="coerce")
    source = source.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    if source.empty:
        return {"dates": [], "ohlc": []}
    close = pd.to_numeric(source["close"], errors="coerce")
    bars = source[["open", "close", "low", "high", "volume", "amount"]].copy()
    indicator_payload = _index_technical_indicator_payload(bars)
    return {
        "dates": source["date"].dt.strftime("%Y-%m-%d").tolist(),
        "ohlc": [
            [round(float(o), 2), round(float(c), 2), round(float(l), 2), round(float(h), 2)]
            for o, c, l, h in source[["open", "close", "low", "high"]].values.tolist()
        ],
        "ma20": _series_payload(pd.DataFrame({"value": close.rolling(20, min_periods=20).mean()}), "value", 2),
        "ma60": _series_payload(pd.DataFrame({"value": close.rolling(60, min_periods=60).mean()}), "value", 2),
        "ma120": _series_payload(pd.DataFrame({"value": close.rolling(120, min_periods=120).mean()}), "value", 2),
        **indicator_payload,
    }


def _plain_multi_timeframe_kline_payload(frame: pd.DataFrame) -> dict[str, Any]:
    source = frame.copy()
    if "date" not in source.columns and "trade_date" in source.columns:
        source = source.rename(columns={"trade_date": "date"})
    if "volume" not in source.columns:
        source["volume"] = source["vol"] if "vol" in source.columns else np.nan
    if "amount" not in source.columns:
        source["amount"] = np.nan
    if "date" not in source.columns:
        return {"1d": {"dates": [], "ohlc": []}}
    source["date"] = pd.to_datetime(source["date"], errors="coerce")
    source = source.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    if source.empty:
        return {"1d": {"dates": [], "ohlc": []}}
    for column in ("open", "high", "low", "close", "volume", "amount"):
        source[column] = pd.to_numeric(source[column], errors="coerce")
    source = source.dropna(subset=["open", "high", "low", "close"])
    if source.empty:
        return {"1d": {"dates": [], "ohlc": []}}

    def aggregate(freq: str) -> pd.DataFrame:
        indexed = source.set_index("date")
        result = indexed.resample(freq).agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            amount=("amount", "sum"),
        ).dropna(subset=["open", "high", "low", "close"])
        return result.reset_index()

    return {
        "1d": _plain_daily_kline_payload(source),
        "1w": _plain_daily_kline_payload(aggregate("W-FRI")),
        "1mo": _plain_daily_kline_payload(aggregate("ME")),
    }


def _industry_technical_kline_payload(
    features: pd.DataFrame,
    rankings: dict[str, Any],
    industry_frames: dict[str, pd.DataFrame] | None,
    technical_structure_config: dict[str, Any] | None = None,
    as_of: Any | None = None,
) -> dict[str, Any]:
    """Build switchable K-line payloads for industries visible in the ranking tables."""
    frames = {str(symbol).upper(): frame for symbol, frame in (industry_frames or {}).items() if frame is not None and not frame.empty}
    if not frames:
        return {}
    rows = rankings.get("all") or (rankings.get("strongest") or []) + (rankings.get("weakest") or [])
    ordered: list[tuple[str, str]] = []
    for row in rows:
        symbol = str(row.get("symbol") or "").upper()
        name = str(row.get("industry") or row.get("name") or symbol)
        if symbol.endswith(".TI") and symbol in frames:
            ordered.append((symbol, name))
    if not ordered:
        return {}

    payload: dict[str, Any] = {}
    for symbol, name in dict.fromkeys(ordered):
        frame = frames.get(symbol)
        if frame is None or frame.empty:
            continue
        clipped = frame.copy()
        cutoff = pd.to_datetime(as_of, errors="coerce")
        date_column = "date" if "date" in clipped.columns else "trade_date" if "trade_date" in clipped.columns else None
        if date_column is not None and pd.notna(cutoff):
            dates = pd.to_datetime(clipped[date_column], errors="coerce")
            clipped = clipped.loc[dates.notna() & dates.le(cutoff)].copy()
        if clipped.empty:
            continue
        payload[symbol] = {
            "symbol": symbol,
            "name": name,
            "timeframes": _plain_multi_timeframe_kline_payload(clipped),
        }
    return payload


def _market_chart_payload(structure: dict[str, Any]) -> dict[str, Any]:
    breadth = pd.DataFrame((structure.get("breadth") or {}).get("history") or [])
    styles = pd.DataFrame(structure.get("style_history") or [])
    indexes = pd.DataFrame(structure.get("index_history") or [])
    liquidity = pd.DataFrame((structure.get("liquidity_structure") or {}).get("history") or [])
    payload: dict[str, Any] = {}
    if not breadth.empty and "trade_date" in breadth.columns:
        if "normalized_ad" in breadth.columns:
            normalized_ad = pd.to_numeric(breadth["normalized_ad"], errors="coerce")
            breadth["normalized_ad_ema10"] = normalized_ad.ewm(span=10, adjust=False, min_periods=1).mean()
        if "ad_line_rebased" in breadth.columns:
            ad_line = pd.to_numeric(breadth["ad_line_rebased"], errors="coerce")
            breadth["ad_line_ema10"] = ad_line.ewm(span=10, adjust=False, min_periods=1).mean()
            breadth["ad_line_ema20"] = ad_line.ewm(span=20, adjust=False, min_periods=1).mean()
        payload["dates"] = breadth["trade_date"].astype(str).tolist()
        distribution = ((structure.get("breadth") or {}).get("return_distribution") or [])
        if distribution:
            payload["return_distribution_labels"] = [str(item.get("label", "")) for item in distribution]
            payload["return_distribution_counts"] = [item.get("count") for item in distribution]
            payload["return_distribution_ratios"] = [item.get("ratio") for item in distribution]
        for column in (
            "advance_ratio", "pct_above_ma20", "pct_above_ma50", "pct_above_ma200",
            "normalized_ad", "normalized_ad_ema10", "ad_line_rebased", "ad_line_ema10", "ad_line_ema20", "new_high_20_ratio", "new_low_20_ratio",
            "normalized_nhnl_20", "decline_gt_3_ratio", "decline_gt_5_ratio", "approximate_limit_down_ratio",
            "cross_section_dispersion", "amount_ratio_20", "equal_weight_return_1d", "all_a_index_return_1d",
            "advance_amount_ratio", "decline_amount_ratio",
        ):
            payload[column] = _series_payload(breadth, column, 6)
    # ``breadth`` retains the full cached market history while the liquidity
    # diagnostics intentionally keep only a short rolling window.  The K-line
    # panel needs the former so total-market turnover remains continuous.
    if not breadth.empty and {"trade_date", "total_market_amount"}.issubset(breadth.columns):
        market_amount = breadth[["trade_date", "total_market_amount"]].copy()
        market_amount["trade_date"] = pd.to_datetime(market_amount["trade_date"], errors="coerce")
        market_amount = market_amount.dropna(subset=["trade_date"]).sort_values("trade_date")
        if not market_amount.empty:
            payload["market_amount_dates"] = market_amount["trade_date"].dt.strftime("%Y-%m-%d").tolist()
            payload["market_total_amount"] = _series_payload(market_amount, "total_market_amount", 2)
    elif not liquidity.empty and "trade_date" in liquidity.columns:
        liquidity = liquidity.copy()
        liquidity["trade_date"] = pd.to_datetime(liquidity["trade_date"], errors="coerce")
        liquidity = liquidity.dropna(subset=["trade_date"]).sort_values("trade_date")
        if not liquidity.empty:
            payload["market_amount_dates"] = liquidity["trade_date"].dt.strftime("%Y-%m-%d").tolist()
            payload["market_total_amount"] = _series_payload(liquidity, "total_amount", 2)
    if not styles.empty:
        payload["style_dates"] = styles["trade_date"].astype(str).tolist()
        for key in ("value", "securities", "growth", "consumer", "small_cap"):
            for suffix in ("strength", "return_20d", "relative_all_a_20d"):
                column = f"{key}_{suffix}"
                payload[column] = _series_payload(styles, column, 6)
    if not indexes.empty:
        payload["index_dates"] = indexes["trade_date"].astype(str).tolist()
        index_columns = {
            "上证指数": "sse_index", "沪深300": "hs300_index", "创业板指": "chinext_index",
            "科创50": "star50_index", "中证500": "csi500_index", "中证1000": "csi1000_index",
            "中证2000": "csi2000_index", MARKET_BENCHMARK_NAME: MARKET_BENCHMARK_CHART_KEY,
        }
        for source, target in index_columns.items():
            payload[target] = _series_payload(indexes, source, 4)
        if {"沪深300", MARKET_BENCHMARK_NAME}.issubset(indexes.columns):
            ratio = pd.to_numeric(indexes["沪深300"], errors="coerce") / pd.to_numeric(indexes[MARKET_BENCHMARK_NAME], errors="coerce")
            first = ratio.dropna().iloc[0] if not ratio.dropna().empty else None
            indexes["hs300_vs_all_a"] = ratio / first * 100.0 if first else np.nan
            payload["hs300_vs_all_a"] = _series_payload(indexes, "hs300_vs_all_a", 4)

    # V2 charts keep their own date axes.  Do not coerce them onto the legacy
    # breadth calendar: historical membership and source freshness can make
    # otherwise related series start on different dates.
    layered = structure.get("layered_breadth") or {}
    layer_order = ["全A", "上证50", "沪深300", "中证500", "中证1000", "中证2000", "创业板", "科创50"]
    layer_dates = sorted(
        {
            str(row.get("trade_date"))
            for name in layer_order
            for row in ((layered.get(name) or {}).get("history") or [])
            if row.get("trade_date")
        }
    )
    layer_series: list[dict[str, Any]] = []
    if layer_dates:
        for name in layer_order:
            item = layered.get(name) or {}
            rows = {
                str(row.get("trade_date")): row
                for row in item.get("history") or []
                if row.get("trade_date")
            }
            if not rows:
                continue
            layer_series.append(
                {
                    "name": name,
                    "state": item.get("state"),
                    "advance_ratio": [rows.get(date, {}).get("advance_ratio") for date in layer_dates],
                    "normalized_ad": [rows.get(date, {}).get("normalized_ad") for date in layer_dates],
                    **{
                        f"pct_above_ma{window}": [
                            rows.get(date, {}).get(f"pct_above_ma{window}") for date in layer_dates
                        ]
                        for window in (5, 10, 20, 60)
                    },
                    **{
                        f"new_{direction}_{window}_ratio": [
                            rows.get(date, {}).get(f"new_{direction}_{window}_ratio") for date in layer_dates
                        ]
                        for window in (5, 10, 20, 60)
                        for direction in ("high", "low")
                    },
                }
            )
        payload["layered_breadth_dates"] = layer_dates
        payload["layered_breadth_series"] = layer_series

    distribution_v2 = structure.get("return_distribution") or {}
    histogram = distribution_v2.get("histogram") or []
    if histogram:
        payload["v2_distribution_labels"] = [str(item.get("label", "")) for item in histogram]
        payload["v2_distribution_counts"] = [item.get("count") for item in histogram]
        payload["v2_distribution_ratios"] = [item.get("ratio") for item in histogram]
    distribution_history = [
        row for row in (distribution_v2.get("history") or []) if row.get("trade_date")
    ][-20:]
    if distribution_history:
        payload["distribution_dates"] = [str(row.get("trade_date")) for row in distribution_history]
        for column in ("q10", "median", "q90"):
            payload[f"distribution_{column}"] = [row.get(column) for row in distribution_history]

    timeline = ((structure.get("market_structure") or {}).get("state_history") or {})
    dimensions = timeline.get("dimensions") or {}
    timeline_dates = sorted(
        {
            str(row.get("trade_date"))
            for item in dimensions.values()
            for row in (item.get("history") or [])
            if row.get("trade_date")
        }
    )
    if timeline_dates:
        timeline_names = {
            "participation": "参与度", "breadth": "广度", "concentration": "集中度",
            "risk": "风险", "leadership": "领涨质量", "style": "风格领先",
            "repair": "修复", "divergence": "指数/个股分化",
        }
        payload["state_history_dates"] = timeline_dates
        payload["state_history_dimensions"] = [
            {
                "name": timeline_names.get(str(name), str(name)),
                "states": [
                    {
                        str(row.get("trade_date")): str(row.get("state") or "unknown")
                        for row in (item.get("history") or [])
                        if row.get("trade_date")
                    }.get(date, "unknown")
                    for date in timeline_dates
                ],
            }
            for name, item in dimensions.items()
        ]
    return payload


def _cards(latest: dict[str, Any], evaluation: dict[str, Any]) -> str:
    signal = str(latest.get("environment_signal", "neutral"))
    timing_stats = evaluation.get("timing_stats") or {}
    items = [
        ("预测状态", _signal_text(signal)),
        ("环境分数", _fmt_num(latest.get("market_score"), 1)),
        ("预测机会分", _fmt_num(latest.get("predicted_opportunity_score"), 1)),
        ("预测风险分", _fmt_num(latest.get("predicted_risk_score"), 1)),
    ]
    if latest.get("model") == "rule_h3_v2":
        items.extend(
            [
                ("机会分", _fmt_num(latest.get("opportunity_score"), 1)),
                ("修复分", _fmt_num(latest.get("rebound_score"), 1)),
                ("突破分", _fmt_num(latest.get("breakout_score"), 1)),
                ("趋势跟随", _fmt_num(latest.get("trend_follow_score"), 1)),
                ("风险分", _fmt_num(latest.get("risk_score"), 1)),
                ("过热风险", _fmt_num(latest.get("overheat_risk_score"), 1)),
                ("破位风险", _fmt_num(latest.get("breakdown_risk_score"), 1)),
                ("趋势背景", _fmt_num(latest.get("trend_context_score"), 1)),
                ("市场状态", str(latest.get("market_regime", "--") or "--")),
                ("净机会", _fmt_num(latest.get("net_score"), 1)),
            ]
        )
    else:
        items.extend(
            [
                ("上涨股票比例", _fmt_ratio_pct(latest.get("stock_up_ratio"), 1)),
                ("MA20上方比例", _fmt_ratio_pct(latest.get("stocks_above_ma20_ratio"), 1)),
                ("横截面波动", _fmt_ratio_pct(latest.get("cross_section_volatility_20d"), 1)),
                ("指数/等权5日差", _fmt_pct(latest.get("index_equal_weight_gap_5d"), 1)),
            ]
        )
    return "".join(
        f"<div class='card'><span>{escape(label)}</span><strong>{escape(value)}</strong></div>"
        for label, value in items
    )


def _market_structure_cards(structure: dict[str, Any]) -> str:
    state = structure.get("market_structure") or {}
    trend = state.get("trend") or {}
    breadth_state = state.get("breadth") or {}
    risk = state.get("risk") or {}
    style = state.get("style") or {}
    divergence = state.get("divergence") or {}
    latest = (structure.get("breadth") or {}).get("latest") or {}
    styles = structure.get("styles") or {}
    index_lift = structure.get("index_lift_structure") or (state.get("index_lift_structure") or {})
    lift_returns = index_lift.get("returns") or {}
    lift_scores = index_lift.get("scores") or {}
    lift_concentration = index_lift.get("contribution_concentration") or {}
    lift_turnover = index_lift.get("turnover_confirmation") or {}
    lift_pressure = index_lift.get("heavy_turnover_pressure") or {}

    def trend_cn(value: Any) -> str:
        return {"uptrend": "上升", "sideways": "震荡", "downtrend": "下降", "mixed": "分化", "unknown": "数据不足"}.get(str(value), "数据不足")

    def breadth_cn(value: Any) -> str:
        return {"strong": "强", "strong_repair": "强修复", "neutral": "中性", "weak": "偏弱", "very_weak": "弱势"}.get(str(value), "数据不足")

    def pressure_cn(value: Any) -> str:
        return {"low": "较低", "medium": "中等", "high": "较高", "extreme": "极端"}.get(str(value), "数据不足")

    def risk_cn(value: Any) -> str:
        return {"expanding": "正在扩散", "stable": "相对稳定", "contracting": "正在收缩", "repairing": "正在修复"}.get(str(value), "数据不足")

    def metric(label: str, value: str) -> tuple[str, str]:
        return (label, value)

    leader = style.get("leader_20d") or "数据不足"
    leader_data = styles.get(leader) or {}
    indices = structure.get("indices") or {}
    large_cap = indices.get(trend.get("large_cap_name") or "沪深300") or {}
    growth_evidence = trend.get("growth_evidence") or {}
    items = [
        (
            "权重指数趋势",
            f"日线{trend_cn(trend.get('large_cap_daily'))}",
            f"周线{trend_cn(trend.get('large_cap_weekly'))} · {trend.get('large_cap_name') or '--'}",
            [
                metric("代表指数", str(trend.get("large_cap_name") or "--")),
                metric("1日/5日收益", f"{_fmt_pct(large_cap.get('return_1d'))} / {_fmt_pct(large_cap.get('return_5d'))}"),
                metric("MA20 / MA60", f"{_fmt_num(large_cap.get('ma20'), 2)} / {_fmt_num(large_cap.get('ma60'), 2)}"),
                metric("MA20 5日斜率", _fmt_pct(large_cap.get("ma20_slope"))),
            ],
        ),
        (
            "成长指数趋势",
            f"日线{trend_cn(trend.get('growth_daily'))}",
            f"周线{trend_cn(trend.get('growth_weekly'))} · 创业板/科创50",
            [
                metric("创业板日/周", f"{trend_cn((growth_evidence.get('创业板指') or {}).get('daily'))} / {trend_cn((growth_evidence.get('创业板指') or {}).get('weekly'))}"),
                metric("科创50日/周", f"{trend_cn((growth_evidence.get('科创50') or {}).get('daily'))} / {trend_cn((growth_evidence.get('科创50') or {}).get('weekly'))}"),
                metric("创业板1日/20日", f"{_fmt_pct((indices.get('创业板指') or {}).get('return_1d'))} / {_fmt_pct((indices.get('创业板指') or {}).get('return_20d'))}"),
                metric("科创501日/20日", f"{_fmt_pct((indices.get('科创50') or {}).get('return_1d'))} / {_fmt_pct((indices.get('科创50') or {}).get('return_20d'))}"),
            ],
        ),
        (
            "当日赚钱效应",
            breadth_cn(breadth_state.get("today_state")),
            f"上涨比例{_fmt_ratio_pct(latest.get('advance_ratio'))}，中位收益{_fmt_pct(latest.get('median_stock_return_1d'))}",
            [
                metric("上涨/下跌股票", f"{_fmt_int(latest.get('advance_count'))} / {_fmt_int(latest.get('decline_count'))}"),
                metric("上涨比例", _fmt_ratio_pct(latest.get("advance_ratio"))),
                metric("个股中位收益", _fmt_pct(latest.get("median_stock_return_1d"))),
                metric("全A等权收益", _fmt_pct(latest.get("equal_weight_return_1d"))),
                metric("当日标准化A/D", _fmt_signed_num(latest.get("normalized_ad"), 3)),
            ],
        ),
        (
            "中期市场广度",
            breadth_cn(breadth_state.get("medium_20d_state")),
            f"MA20上方{_fmt_ratio_pct(latest.get('pct_above_ma20'))}，20日A/D {_fmt_num(latest.get('normalized_ad_20d'), 3)}",
            [
                metric("MA20上方比例", _fmt_ratio_pct(latest.get("pct_above_ma20"))),
                metric("MA60上方比例", _fmt_ratio_pct(latest.get("pct_above_ma60"))),
                metric("20日标准化A/D", _fmt_signed_num(latest.get("normalized_ad_20d"), 3)),
                metric("20日等权收益", _fmt_pct(latest.get("equal_weight_return_20d"))),
                metric("20日个股中位收益", _fmt_pct(latest.get("median_stock_return_20d"))),
            ],
        ),
        (
            "尾部压力",
            pressure_cn(risk.get("pressure_level")),
            f"跌超5% {_fmt_ratio_pct(latest.get('decline_gt_5_ratio'))}，20日新低{_fmt_ratio_pct(latest.get('new_low_20_ratio'))}",
            [
                metric("跌超3% / 跌超5%", f"{_fmt_ratio_pct(latest.get('decline_gt_3_ratio'))} / {_fmt_ratio_pct(latest.get('decline_gt_5_ratio'))}"),
                metric("近似跌停比例", _fmt_ratio_pct(latest.get("approximate_limit_down_ratio"))),
                metric("20日新低比例", _fmt_ratio_pct(latest.get("new_low_20_ratio"))),
                metric("横截面离散度", _fmt_ratio_pct(latest.get("cross_section_dispersion"), 2)),
                metric("近期市场波动", _fmt_ratio_pct(latest.get("market_realized_volatility_5d"), 2)),
            ],
        ),
        (
            "指数拉升质量",
            str(index_lift.get("state_cn") or _state_text(index_lift.get("state"))),
            f"质量分{_fmt_num(lift_scores.get('index_lift_quality'), 1)}，掩护风险{_fmt_num(lift_scores.get('index_masking_risk'), 1)}",
            [
                metric("观察指数", f"{index_lift.get('index_name') or '--'} {index_lift.get('symbol') or ''}".strip()),
                metric("指数/等权收益", f"{_fmt_pct(lift_returns.get('index_return'))} / {_fmt_pct(lift_returns.get('equal_weight_return'))}"),
                metric("前10正贡献占比", _fmt_ratio_pct(lift_concentration.get("top_10_positive_contribution_share"))),
                metric("前10贡献成交占比", _fmt_ratio_pct(lift_turnover.get("top10_contributor_amount_share"))),
                metric("下跌成交占比", _fmt_ratio_pct(lift_pressure.get("down_amount_share"))),
                metric("高权重低成交正贡献", _fmt_ratio_pct(lift_turnover.get("high_weight_low_turnover_positive_contribution_share"))),
                metric("置信度", _confidence_text(index_lift.get("confidence"))),
            ],
        ),
        (
            "风险扩散方向",
            risk_cn(risk.get("risk_direction")),
            f"新低{risk_cn(risk.get('new_low_direction'))}，A/D {risk_cn(risk.get('ad_direction'))}",
            [
                metric("20日新低方向", risk_cn(risk.get("new_low_direction"))),
                metric("跌超5%方向", risk_cn(risk.get("large_decline_direction"))),
                metric("A/D方向", risk_cn(risk.get("ad_direction"))),
                metric("NH-NL方向", risk_cn(risk.get("nhnl_direction"))),
            ],
        ),
        (
            "中期主导风格",
            str(leader),
            f"20日收益{_fmt_pct(leader_data.get('return_20d'))}，状态{_style_state_text(leader_data.get('state_20d'))}",
            [
                metric("20日领涨风格", str(style.get("leader_20d") or "--")),
                metric("5日/20日收益", f"{_fmt_pct(leader_data.get('return_5d'))} / {_fmt_pct(leader_data.get('return_20d'))}"),
                metric("20日相对平均股价", _fmt_pct(leader_data.get("relative_all_a_20d"))),
                metric("上涨比例", _fmt_ratio_pct(leader_data.get("advance_ratio"))),
                metric("MA20上方比例", _fmt_ratio_pct(leader_data.get("pct_above_ma20"))),
            ],
        ),
        (
            "指数与个股分化",
            str(divergence.get("summary", "数据不足")),
            f"1日{_divergence_text(divergence.get('one_day'))}，5/20日{_divergence_text(divergence.get('five_day'))}/{_divergence_text(divergence.get('twenty_day'))}",
            [
                metric("1日判断", _divergence_text(divergence.get("one_day"))),
                metric("5日判断", _divergence_text(divergence.get("five_day"))),
                metric("20日判断", _divergence_text(divergence.get("twenty_day"))),
                metric("1日差值证据", _fmt_pct(divergence.get("gap_1d"))),
                metric("5日差值证据", _fmt_pct(divergence.get("gap_5d"))),
            ],
        ),
    ]
    concentration = structure.get("contribution_analysis") or state.get("concentration") or {}
    if concentration:
        concentration_latest = concentration.get("latest") or {}
        items.append(
            (
                "市场集中度",
                _state_text(concentration.get("state")),
                f"历史分位{_fmt_ratio_pct(concentration_latest.get('concentration_percentile'))} · 前10%成交占比{_fmt_ratio_pct(concentration_latest.get('top_10pct_turnover_share'))}",
                [
                    metric("综合历史分位", _fmt_ratio_pct(concentration_latest.get("concentration_percentile"))),
                    metric("前10%成交占比", _fmt_ratio_pct(concentration_latest.get("top_10pct_turnover_share"))),
                    metric("前三行业正贡献", _fmt_ratio_pct(concentration_latest.get("top3_industry_positive_contribution_share"))),
                    metric("前五行业成交", _fmt_ratio_pct(concentration_latest.get("top5_industry_turnover_share"))),
                    metric("权重HHI", _fmt_num(concentration_latest.get("weight_hhi"), 3)),
                ],
            )
        )
    if risk.get("state"):
        risk_latest = risk.get("latest") or {}
        items.extend(
            [
                (
                    "风险阶段",
                    _state_text(risk.get("state")),
                    f"5日平滑压力{_fmt_num(risk_latest.get('smooth_5d'), 1)} · 证据族{_fmt_int(risk_latest.get('evidence_family_count'))}",
                    [
                        metric("风险分5日平滑", _fmt_num(risk_latest.get("smooth_5d"), 1)),
                        metric("风险1日变化", _fmt_signed_num(risk_latest.get("change_1d"), 1)),
                        metric("风险5日变化", _fmt_signed_num(risk_latest.get("change_5d"), 1)),
                        metric("有效证据族", _fmt_int(risk_latest.get("evidence_family_count"))),
                    ],
                ),
                (
                    "风险状态持续",
                    f"{_fmt_int((risk.get('state_tracker') or {}).get('duration_trading_days', risk_latest.get('duration_trading_days')))}个交易日",
                    f"起始{(risk.get('state_tracker') or {}).get('state_start_date') or '--'} · 稳定性{_state_text((risk.get('state_tracker') or {}).get('stability'))}",
                    [
                        metric("当前稳定状态", _state_text(risk.get("state"))),
                        metric("起始日期", str((risk.get("state_tracker") or {}).get("state_start_date") or "--")),
                        metric("持续交易日", _fmt_int((risk.get("state_tracker") or {}).get("duration_trading_days", risk_latest.get("duration_trading_days")))),
                        metric("20日切换次数", _fmt_int((risk.get("state_tracker") or {}).get("transition_count_20d"))),
                    ],
                ),
            ]
        )
    def render_card(item: tuple[Any, ...]) -> str:
        label, value, evidence = item[:3]
        details = item[3] if len(item) > 3 else []
        tooltip = ""
        if details:
            rows = "".join(
                f"<div class='card-tooltip-row'><span>{escape(str(detail_label))}</span><b>{escape(str(detail_value))}</b></div>"
                for detail_label, detail_value in details
            )
            tooltip = f"<div class='card-tooltip'><span class='card-tooltip-title'>关键指标</span>{rows}</div>"
        title = "；".join(f"{detail_label}: {detail_value}" for detail_label, detail_value in details)
        return (
            f"<div class='card' tabindex='0' title='{escape(title, quote=True)}'>"
            f"<span>{escape(str(label))}</span><strong>{escape(str(value))}</strong>"
            f"<small>{escape(str(evidence))}</small>{tooltip}</div>"
        )

    return "".join(render_card(item) for item in items)


_STATE_NAMES = {
    "unknown": "数据不足", "fresh": "新鲜", "stale": "滞后", "missing": "缺失",
    "stable": "稳定", "rotating": "轮动", "unstable": "不稳定", "normal": "常态",
    "dispersed": "分散", "moderate": "中等", "high": "高", "extreme": "极端",
    "moderate_concentration": "中度集中", "high_concentration": "高度集中", "extreme_concentration": "极端集中",
    "broad_strength": "广泛走强", "broad_weakness": "广泛走弱", "selective": "局部参与",
    "broad_participation": "广泛参与", "selective_participation": "选择性参与", "weak_participation": "参与偏弱",
    "broad_rally": "普涨", "narrow_rally": "窄幅上涨", "mixed": "分化", "narrow_decline": "局部下跌", "broad_decline": "普跌",
    "risk_expanding": "风险扩张", "risk_building": "风险累积", "high_pressure_stable": "高压稳定",
    "low_pressure_stable": "低压稳定", "risk_contracting": "风险收缩", "risk_repairing": "风险修复",
    "repairing": "修复中", "contracting": "收缩中",
    "panic_expanding": "恐慌扩张", "panic_stable": "恐慌稳定", "initial_rebound": "初步反弹",
    "breadth_repair": "广度修复", "trend_repair": "趋势修复", "failed_rebound": "反弹失败",
    "strong_accelerating": "强势加速", "strong_decelerating": "强势减速", "weak_improving": "弱势改善",
    "weak_deteriorating": "弱势恶化", "building": "持续构筑", "decelerating": "强度减速",
    "deteriorating": "转弱", "neutral_rotation": "中性轮动", "persistent": "持续领先",
    "confirmed": "质量确认", "failed": "质量失效", "exhaustion_warning": "衰竭警示",
    "selling_expansion": "抛售放量", "broad_expansion": "普遍放量", "concentrated_expansion": "集中放量",
    "quiet": "交投平静", "polarized": "两极分化", "broad": "分布广泛", "narrow": "分布集中",
    "stocks_stronger": "个股更强", "large_cap_stronger": "权重更强", "synchronized": "同步",
    "none": "无", "candidate": "候选", "low": "低", "medium": "中", "rebound_confirmed": "反弹确认",
    "panic_contracting": "恐慌收缩", "rebound_failed": "反弹失败", "heat_building": "热度累积",
    "heat_persistent": "热度持续", "exhaustion_confirmed": "衰竭确认",
    "shrinking_rebound": "缩量反弹", "weak_improving": "弱修复", "broad_expansion": "广泛扩张",
    "broad_confirmed_rise": "广泛确认上涨", "concentrated_but_supported": "集中但有成交支撑",
    "thin_weighted_lift": "缩量拉权重", "masked_distribution": "掩护性上涨结构",
    "mixed_divergence": "多空分化",
}


def _state_text(value: Any) -> str:
    raw = str(value or "unknown")
    return _STATE_NAMES.get(raw, raw.replace("_", " "))


def _state_chip(value: Any) -> str:
    raw = str(value or "unknown")
    risk_states = {"stale", "missing", "risk_expanding", "panic_expanding", "failed", "failed_rebound", "broad_decline", "selling_expansion"}
    good_states = {"fresh", "broad_strength", "broad_participation", "broad_rally", "confirmed", "trend_repair", "breadth_repair"}
    css = "risk" if raw in risk_states else "good" if raw in good_states else "warn" if raw == "unknown" else ""
    return f"<span class='state-chip {css}' title='{escape(raw, quote=True)}'>{escape(_state_text(raw))}</span>"


def _confidence_text(value: Any) -> str:
    return {"high": "高", "medium": "中", "low": "低", "unknown": "数据不足"}.get(
        str(value or "unknown"), str(value or "数据不足")
    )


def _confidence_chip(value: Any) -> str:
    raw = str(value or "unknown")
    css = "good" if raw == "high" else "warn" if raw in {"medium", "unknown"} else "risk"
    return f"<span class='state-chip {css}' title='{escape(raw, quote=True)}'>{escape(_confidence_text(raw))}</span>"


def _deterministic_summary_html(structure: dict[str, Any]) -> str:
    summary = structure.get("deterministic_summary") or {}
    lines = [str(value) for value in summary.get("lines") or [] if value]
    if not lines:
        headline = str((structure.get("market_structure") or {}).get("headline") or "当前市场结构数据不足。")
        lines = [headline]
    items = "".join(f"<li>{escape(line)}</li>" for line in lines)
    meta = ""
    if summary:
        meta = (
            "<div class='summary-meta'>"
            "<span>确定性规则总结</span><span>不含收益预测</span><span>不含仓位/订单建议</span>"
            f"<span>维度顺序：{escape(' → '.join(str(item) for item in summary.get('ordered_dimensions') or []))}</span>"
            "</div>"
        )
    return f"<ol class='summary-lines'>{items}</ol>{meta}"


def _overview_evidence_details(structure: dict[str, Any]) -> str:
    evidence = ((structure.get("market_structure") or {}).get("evidence") or {})
    if not evidence:
        return "<div class='empty-v2'>当前文件没有 v2 证据块，已继续展示兼容版结构结论。</div>"
    names = {
        "participation": "参与度", "concentration": "集中度", "risk": "风险",
        "leadership": "领涨质量", "repair": "修复", "index_lift_structure": "指数拉升质量",
    }
    blocks = []
    for key, item in evidence.items():
        support = "；".join(str(value) for value in item.get("supporting_evidence") or []) or "无"
        contradict = "；".join(str(value) for value in item.get("contradicting_evidence") or []) or "无"
        blocks.append(
            "<details>"
            f"<summary><span>{escape(names.get(str(key), str(key)))}</span>{_state_chip(item.get('state'))}</summary>"
            "<div class='evidence-body'>"
            f"<strong>置信度：</strong>{escape(_confidence_text(item.get('confidence')))}（{escape(_fmt_ratio_pct(item.get('confidence_score')))}） · "
            f"证据族 {escape(_fmt_int(item.get('independent_evidence_families')))} · 覆盖率 {escape(_fmt_ratio_pct(item.get('coverage')))}<br>"
            f"<strong>支持：</strong>{escape(support)}<br><strong>反证：</strong>{escape(contradict)}<br>"
            f"<strong>时点口径：</strong>{'是' if item.get('point_in_time') else '否/受限'}；置信度表示证据完整性与一致性，不是概率。"
            "</div></details>"
        )
    return "<div class='evidence-folds'>" + "".join(blocks) + "</div>"


def _index_lift_chart_payload(structure: dict[str, Any]) -> dict[str, Any]:
    root = structure.get("index_lift_structure") or {}
    by_symbol = root.get("by_symbol") or {}
    payload: dict[str, Any] = {"primary_symbol": root.get("symbol"), "by_symbol": {}}
    for symbol, item in by_symbol.items():
        history = [row for row in (item.get("history") or []) if row.get("trade_date")]
        payload["by_symbol"][str(symbol)] = {
            "name": item.get("index_name") or symbol,
            "dates": [str(row.get("trade_date")) for row in history],
            "index_return": [row.get("index_return") for row in history],
            "equal_weight_return": [row.get("equal_weight_return") for row in history],
            "amount_weighted_return": [row.get("amount_weighted_return") for row in history],
            "index_equal_weight_gap": [row.get("index_equal_weight_gap") for row in history],
            "index_amount_weighted_gap": [row.get("index_amount_weighted_gap") for row in history],
            "top_10_positive_contribution_share": [row.get("top_10_positive_contribution_share") for row in history],
            "top10_contributor_amount_share": [row.get("top10_contributor_amount_share") for row in history],
            "down_amount_share": [row.get("down_amount_share") for row in history],
            "top_turnover_20pct_return": [row.get("top_turnover_20pct_return") for row in history],
            "index_lift_quality": [row.get("index_lift_quality") for row in history],
            "index_masking_risk": [row.get("index_masking_risk") for row in history],
        }
    return payload


def _index_lift_metric_strip(item: dict[str, Any]) -> str:
    returns = item.get("returns") or {}
    concentration = item.get("contribution_concentration") or {}
    turnover = item.get("turnover_confirmation") or {}
    pressure = item.get("heavy_turnover_pressure") or {}
    scores = item.get("scores") or {}
    metrics = [
        ("状态 / 质量分", item.get("state_cn") or _state_text(item.get("state")), f"质量{_fmt_num(scores.get('index_lift_quality'), 1)} · 掩护风险{_fmt_num(scores.get('index_masking_risk'), 1)}"),
        ("指数 / 等权 / 成交加权收益", f"{_fmt_pct(returns.get('index_return'))} / {_fmt_pct(returns.get('equal_weight_return'))} / {_fmt_pct(returns.get('amount_weighted_return'))}", f"指数-等权差{_fmt_pct(returns.get('index_equal_weight_gap'))}"),
        ("前10正贡献占比", _fmt_ratio_pct(concentration.get("top_10_positive_contribution_share")), f"HHI {_fmt_num(concentration.get('positive_contribution_hhi'), 3)} · 80%所需{_fmt_int(concentration.get('stocks_needed_for_80pct_positive_contribution'))}只"),
        ("贡献成交确认", _fmt_multiple(turnover.get("contribution_weighted_amount_ratio_20d")), f"前10贡献成交占比{_fmt_ratio_pct(turnover.get('top10_contributor_amount_share'))} · 前20成交占比{_fmt_ratio_pct(turnover.get('top20_turnover_amount_share'))}"),
        ("下跌成交占比", _fmt_ratio_pct(pressure.get("down_amount_share")), f"下跌/上涨成交比{_fmt_multiple(pressure.get('up_down_amount_ratio'))}"),
        ("大成交承压", _fmt_ratio_pct(pressure.get("heavy_selling_amount_share")), f"前20%成交股收益{_fmt_pct(pressure.get('top_turnover_20pct_return'))}"),
        ("高权重低成交正贡献", _fmt_ratio_pct(turnover.get("high_weight_low_turnover_positive_contribution_share")), f"低量正贡献{_fmt_ratio_pct(turnover.get('low_volume_positive_contribution_share'))}"),
        ("置信度 / 权重口径", _confidence_text(item.get("confidence")), "近似权重" if item.get("index_weight_is_approximate") else f"快照{item.get('member_snapshot_date') or '--'}"),
    ]
    return "".join(
        "<div class='metric-tile'>"
        f"<span>{escape(str(label))}</span><strong>{escape(str(value))}</strong><small>{escape(str(detail))}</small>"
        "</div>"
        for label, value, detail in metrics
    )


def _index_lift_stock_table(rows: list[dict[str, Any]], *, turnover: bool = False) -> str:
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{escape(str(row.get('name') or row.get('symbol') or '--'))}<br><span class='muted'>{escape(str(row.get('symbol') or '--'))}</span></td>"
            f"<td>{escape(str(row.get('industry') or '--'))}</td>"
            f"<td>{escape(_fmt_ratio_pct(row.get('index_weight')))}</td>"
            f"<td class='{_tone(row.get('return_1d'))}'>{escape(_fmt_pct(row.get('return_1d')))}</td>"
            f"<td>{escape(_fmt_num(row.get('amount'), 0))}</td>"
            f"<td>{escape(_fmt_multiple(row.get('amount_ratio_20d')))}</td>"
            f"<td class='{_tone(row.get('index_contribution'))}'>{escape(_fmt_pct(row.get('index_contribution')))}</td>"
            f"<td>{escape(_fmt_ratio_pct(row.get('amount_share')) if turnover else _fmt_ratio_pct(row.get('contribution_share')))}</td>"
            "</tr>"
        )
    return "".join(body) or "<tr><td colspan='8'>暂无有效成分明细。</td></tr>"


def _index_lift_group_rows(rows: list[dict[str, Any]]) -> str:
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{escape(str(row.get('group_cn') or row.get('group') or '--'))}</td>"
            f"<td>{escape(_fmt_int(row.get('count')))}</td>"
            f"<td class='{_tone(row.get('equal_return'))}'>{escape(_fmt_pct(row.get('equal_return')))}</td>"
            f"<td class='{_tone(row.get('amount_weighted_return'))}'>{escape(_fmt_pct(row.get('amount_weighted_return')))}</td>"
            f"<td class='{_tone(row.get('index_contribution'))}'>{escape(_fmt_pct(row.get('index_contribution')))}</td>"
            f"<td>{escape(_fmt_ratio_pct(row.get('amount_share')))}</td>"
            f"<td>{escape(_fmt_ratio_pct(row.get('advance_ratio')))}</td>"
            "</tr>"
        )
    return "".join(body) or "<tr><td colspan='7'>暂无分组数据。</td></tr>"


def _index_lift_structure_panel(structure: dict[str, Any]) -> str:
    root = structure.get("index_lift_structure") or {}
    by_symbol = root.get("by_symbol") or {}
    if not by_symbol:
        return "<section class='panel'><div class='panel-head'><h2>指数拉升质量与成交结构</h2><span>暂无可用数据</span></div><div class='empty-v2'>当前没有指数成分、成交额或指数行情可用于计算拉升质量。</div></section>"
    primary = str(root.get("symbol") or next(iter(by_symbol))).upper()
    buttons = "".join(
        f"<button type='button' class='lift-symbol-btn{' active' if str(symbol).upper() == primary else ''}' data-symbol='{escape(str(symbol), quote=True)}' onclick='switchIndexLiftSymbol(\"{escape(str(symbol), quote=True)}\")'>{escape(str(item.get('index_name') or symbol))}</button>"
        for symbol, item in by_symbol.items()
    )
    panels = []
    for symbol, item in by_symbol.items():
        active = " active" if str(symbol).upper() == primary else ""
        flags = item.get("data_quality_flags") or []
        flag_html = "".join(f"<span class='flag'>{escape(str(flag))}</span>" for flag in flags[:8]) or "<span class='flag'>无新增质量标记</span>"
        safe_symbol = escape(str(symbol), quote=True)
        panels.append(
            f"""
            <div class='lift-symbol-panel{active}' data-lift-symbol='{safe_symbol}'>
              <div class='metric-strip'>{_index_lift_metric_strip(item)}</div>
              <div class='subpanel-title'><strong>近期走势与分数</strong><span>收益、指数-内部收益差、贡献集中与成交承压；仅描述截至当日的结构</span></div>
              <div class='grid'>
                <div id='index-lift-returns-{safe_symbol}' class='chart small'></div>
                <div id='index-lift-scores-{safe_symbol}' class='chart small'></div>
              </div>
              <div class='subpanel-title'><strong>前十大正贡献成分</strong><span>贡献 = 上一可见权重 × 成分当日收益</span></div>
              <div class='v2-table-wrap compact'><table>
                <thead><tr><th>成分</th><th>行业</th><th>权重</th><th>1日收益</th><th>成交额</th><th>成交/20日</th><th>指数贡献</th><th>贡献占比</th></tr></thead>
                <tbody>{_index_lift_stock_table(item.get('top_positive_contributors') or [])}</tbody>
              </table></div>
              <div class='subpanel-title'><strong>成交额前二十成分</strong><span>观察大成交是否确认指数拉升，或是否集中在承压成分</span></div>
              <div class='v2-table-wrap compact'><table>
                <thead><tr><th>成分</th><th>行业</th><th>权重</th><th>1日收益</th><th>成交额</th><th>成交/20日</th><th>指数贡献</th><th>成交占比</th></tr></thead>
                <tbody>{_index_lift_stock_table(item.get('top_turnover_stocks') or [], turnover=True)}</tbody>
              </table></div>
              <div class='subpanel-title'><strong>权重 × 成交分组</strong><span>高权重为权重位于前20%，高成交为成交额前20%或成交/20日 ≥ 1.2倍</span></div>
              <div class='v2-table-wrap compact'><table>
                <thead><tr><th>分组</th><th>成分数</th><th>等权收益</th><th>成交加权收益</th><th>指数贡献</th><th>成交占比</th><th>上涨比例</th></tr></thead>
                <tbody>{_index_lift_group_rows(item.get('weight_turnover_groups') or [])}</tbody>
              </table></div>
              <div class='compact-note'>质量标记：{flag_html}</div>
            </div>
            """
        )
    return (
        "<section class='panel' data-screen='1b'>"
        "<div class='panel-head'><h2><span class='screen-kicker'>新增</span>指数拉升质量与成交结构</h2><span>识别贡献集中、缩量拉权重、大成交承压与掩护性上涨结构</span></div>"
        f"<div class='lift-tools'><strong>观察指数</strong>{buttons}</div>"
        f"{''.join(panels)}"
        "</section>"
    )


def _layered_breadth_rows(structure: dict[str, Any]) -> str:
    layered = structure.get("layered_breadth") or {}
    order = ["全A", "上证50", "沪深300", "中证500", "中证1000", "中证2000", "创业板", "科创50"]
    rows = []
    for name in order:
        item = layered.get(name) or {}
        if not item:
            continue
        latest = item.get("latest") or {}
        freshness = item.get("index_quote_freshness") or {}
        membership = str(item.get("membership_source") or "--")
        if item.get("confidence_limited"):
            membership += "（置信受限）"
        freshness_html = _state_chip(freshness.get("status")) if freshness else "<span class='muted'>--</span>"
        rows.append(
            "<tr>"
            f"<td><strong>{escape(name)}</strong><br><span class='muted'>{escape(str(item.get('symbol') or '股票全样本'))}</span></td>"
            f"<td>{_state_chip(item.get('state'))}</td>"
            f"<td>{escape(_fmt_int(latest.get('available_member_count', latest.get('member_count'))))}</td>"
            f"<td>{escape(_fmt_ratio_pct(latest.get('coverage')))}</td>"
            f"<td>{escape(_fmt_ratio_pct(latest.get('advance_ratio')))}</td>"
            f"<td>{escape(_fmt_ratio_pct(latest.get('pct_above_ma20')))}</td>"
            f"<td>{escape(_fmt_ratio_pct(latest.get('pct_above_ma60')))}</td>"
            f"<td>{escape(_fmt_ratio_pct(latest.get('new_high_20_ratio')))} / {escape(_fmt_ratio_pct(latest.get('new_low_20_ratio')))}</td>"
            f"<td>{escape(_fmt_signed_num(latest.get('normalized_ad'), 3))}</td>"
            f"<td>{escape(_fmt_ratio_pct(latest.get('turnover_share')))}</td>"
            f"<td>{escape(membership)}<br><span class='muted'>快照 {escape(str(item.get('membership_snapshot_date') or '--'))}</span></td>"
            f"<td>{freshness_html}</td>"
            "</tr>"
        )
    return "".join(rows) or "<tr><td colspan='12'>当前报告未包含分层广度 v2 数据。</td></tr>"


def _distribution_metric_tiles(structure: dict[str, Any]) -> str:
    distribution = structure.get("return_distribution") or {}
    latest = distribution.get("latest") or {}
    if not distribution:
        return "<div class='empty-v2'>当前文件没有收益分布 v2 状态，直方图回退使用兼容版数据。</div>"
    items = [
        ("分布状态", _state_text(distribution.get("state")), f"样本 {_fmt_int(latest.get('valid_count'))}"),
        ("Q10 / 中位 / Q90", f"{_fmt_pct(latest.get('q10'))} / {_fmt_pct(latest.get('median'))} / {_fmt_pct(latest.get('q90'))}", "横截面收益分位数"),
        ("标准差 / IQR", f"{_fmt_ratio_pct(latest.get('std'))} / {_fmt_ratio_pct(latest.get('iqr'))}", f"偏度 {_fmt_num(latest.get('skew'), 2)}"),
        ("跌超3% / 跌超5%", f"{_fmt_ratio_pct(latest.get('decline_gt_3_ratio'))} / {_fmt_ratio_pct(latest.get('decline_gt_5_ratio'))}", f"上涨比例 {_fmt_ratio_pct(latest.get('up_ratio'))}"),
    ]
    return "<div class='metric-strip'>" + "".join(
        f"<div class='metric-tile'><span>{escape(label)}</span><strong>{escape(value)}</strong><small>{escape(note)}</small></div>"
        for label, value, note in items
    ) + "</div>"


def _style_rotation_rows(structure: dict[str, Any]) -> str:
    rotation = structure.get("style_rotation") or {}
    leadership = ((structure.get("market_structure") or {}).get("leadership") or {})
    leader = rotation.get("leader")
    rows = []
    for name, item in (rotation.get("styles") or {}).items():
        latest = item.get("latest") or {}
        quality = ((leadership.get("styles") or {}).get(name) or {}).get("raw_quality_state")
        leader_badge = " <span class='state-chip good'>当前领先</span>" if name == leader else ""
        rows.append(
            "<tr>"
            f"<td><strong>{escape(str(name))}</strong>{leader_badge}</td>"
            f"<td>{escape(_fmt_num(latest.get('level'), 1))}</td>"
            f"<td class='{_tone(latest.get('change_5d'))}'>{escape(_fmt_signed_num(latest.get('change_5d'), 1))}</td>"
            f"<td class='{_tone(latest.get('relative_slope_20d'))}'>{escape(_fmt_pct(latest.get('relative_slope_20d')))}</td>"
            f"<td>{escape(str(rotation.get('days_as_leader', 0) if name == leader else '--'))}</td>"
            f"<td>{_state_chip(quality)}</td>"
            f"<td>{_state_chip(item.get('state'))}</td>"
            "</tr>"
        )
    return "".join(rows) or "<tr><td colspan='7'>当前报告未包含风格轮动 v2 数据。</td></tr>"


def _leadership_callout(structure: dict[str, Any]) -> str:
    leadership = ((structure.get("market_structure") or {}).get("leadership") or {})
    if not leadership:
        return ""
    latest = leadership.get("latest") or {}
    tracker = leadership.get("state_tracker") or {}
    return (
        "<div class='leadership-callout'>"
        f"<strong>领涨质量：</strong>{_state_chip(leadership.get('state'))} · 当前领涨 {escape(str(leadership.get('leader') or latest.get('leader') or '--'))} · "
        f"持续 {escape(_fmt_int(tracker.get('duration_trading_days')))} 个交易日 · 20日切换 {escape(_fmt_int((leadership.get('leader_tracker') or {}).get('transition_count_20d')))} 次。"
        f" 内部上涨比例 {escape(_fmt_ratio_pct(latest.get('advance_ratio')))}，MA20上方 {escape(_fmt_ratio_pct(latest.get('pct_above_ma20')))}，"
        f"前5只正贡献占比 {escape(_fmt_ratio_pct(latest.get('top5_positive_contribution_share')))}。"
        "</div>"
    )


def _v2_industry_rows(items: list[dict[str, Any]]) -> str:
    rows = []
    for item in items:
        rows.append(
            "<tr>"
            f"<td>{escape(str(item.get('industry') or '--'))}</td>"
            f"<td>{escape(_fmt_int(item.get('stock_count')))}</td>"
            f"<td class='{_tone(item.get('return_5d'))}'>{escape(_fmt_pct(item.get('return_5d')))}</td>"
            f"<td class='{_tone(item.get('return_10d'))}'>{escape(_fmt_pct(item.get('return_10d')))}</td>"
            f"<td class='{_tone(item.get('return_20d'))}'>{escape(_fmt_pct(item.get('return_20d')))}</td>"
            f"<td class='{_tone(item.get('relative_strength_20d'))}'>{escape(_fmt_pct(item.get('relative_strength_20d')))}</td>"
            f"<td>{escape(_fmt_ratio_pct(item.get('advance_ratio')))}</td>"
            f"<td>{escape(_fmt_ratio_pct(item.get('pct_above_ma20')))}</td>"
            f"<td>{_state_chip(item.get('leadership_quality'))}</td>"
            "</tr>"
        )
    return "".join(rows) or "<tr><td colspan='9'>暂无 v2 行业结构数据。</td></tr>"


def _risk_v2_tiles(structure: dict[str, Any]) -> str:
    risk = ((structure.get("market_structure") or {}).get("risk") or {})
    repair = ((structure.get("market_structure") or {}).get("repair") or {})
    if not risk.get("latest"):
        return "<div class='empty-v2'>当前文件没有风险证据族 v2 数据，以下继续展示兼容版风险指标。</div>"
    latest = risk.get("latest") or {}
    families = risk.get("evidence_families") or {}
    family_names = {
        "extreme_declines": ("极端下跌", "extreme_decline_score"),
        "internal_damage": ("内部破坏", "internal_damage_score"),
        "disorder": ("失序程度", "disorder_score"),
    }
    blocks = []
    for key, (label, score_key) in family_names.items():
        components = "、".join(str(value) for value in families.get(key) or []) or "数据不足"
        blocks.append(
            f"<div class='metric-tile'><span>{escape(label)}</span><strong>{escape(_fmt_num(latest.get(score_key), 1))}</strong><small>{escape(components)}</small></div>"
        )
    repair_latest = repair.get("latest") or {}
    blocks.append(
        f"<div class='metric-tile'><span>修复阶段</span><strong>{escape(_state_text(repair.get('state')))}</strong>"
        f"<small>风险5日变化 {_fmt_signed_num(repair_latest.get('risk_change_5d'), 1)} · MA20覆盖5日变化 {_fmt_pct(repair_latest.get('pct_above_ma20_change_5d'))}</small></div>"
    )
    return "<div class='metric-strip'>" + "".join(blocks) + "</div>"


def _research_candidates_html(structure: dict[str, Any]) -> str:
    research = structure.get("research_candidates") or {}
    if not research:
        return ""
    names = {"ice": "冰点阶段", "heat": "热度阶段", "rebound_failure": "反弹失败", "style_continuation": "风格延续"}
    items = []
    for key in ("ice", "heat", "rebound_failure", "style_continuation"):
        item = research.get(key) or {}
        excluded = "、".join(str(value) for value in item.get("excluded_from") or [])
        extra = f" · 领涨{item.get('leader')}" if item.get("leader") else ""
        items.append(
            f"<div class='research-item'><span>{escape(names.get(key, key))}</span><strong>{escape(_state_text(item.get('phase')))}</strong>"
            f"<small>exploratory_only={str(bool(item.get('exploratory_only'))).lower()}{escape(extra)}<br>排除：{escape(excluded or '--')}</small></div>"
        )
    return (
        "<div class='research-warning'>探索性研究：冰点/热度等候选状态不进入确定性总结、仓位、订单、正式信号或市场风险闸门。</div>"
        "<div class='research-grid'>" + "".join(items) + "</div>"
    )


def _liquidity_tiles(structure: dict[str, Any]) -> str:
    liquidity = structure.get("liquidity_structure") or {}
    latest = liquidity.get("latest") or {}
    if not latest:
        return "<div class='empty-v2'>当前文件没有流动性结构 v2 数据。</div>"
    items = [
        ("流动性状态", _state_text(liquidity.get("state")), "只使用真实成交额" if liquidity.get("real_amount_only") else "成交口径待确认"),
        ("成交额 / 20日均值", _fmt_multiple(latest.get("amount_ratio_20d")), f"总成交 {_fmt_num(latest.get('total_amount'), 0)}"),
        ("上涨 / 下跌成交占比", f"{_fmt_ratio_pct(latest.get('advance_amount_ratio'))} / {_fmt_ratio_pct(latest.get('decline_amount_ratio'))}", f"比值 {_fmt_num(latest.get('advance_decline_amount_ratio'), 2)}"),
        ("新高 / 新低成交占比", f"{_fmt_ratio_pct(latest.get('new_high_amount_share'))} / {_fmt_ratio_pct(latest.get('new_low_amount_share'))}", f"上涨放量行业 {_fmt_int(latest.get('expanding_up_industry_count'))}，下跌放量 {_fmt_int(latest.get('expanding_down_industry_count'))}"),
    ]
    return "<div class='metric-strip'>" + "".join(
        f"<div class='metric-tile'><span>{escape(label)}</span><strong>{escape(value)}</strong><small>{escape(note)}</small></div>"
        for label, value, note in items
    ) + "</div>"


def _contribution_rows(structure: dict[str, Any]) -> str:
    concentration = structure.get("contribution_analysis") or {}
    latest = concentration.get("latest") or {}
    metrics = [
        ("集中度状态", _state_text(concentration.get("state")), "由多项历史分位综合"),
        ("综合集中度历史分位", _fmt_ratio_pct(latest.get("concentration_percentile")), "滚动历史分位，不是概率"),
        ("前10%股票正贡献占比", _fmt_ratio_pct(latest.get("top_10pct_positive_all_a_contribution_share")), "全A正收益贡献集中度"),
        ("前10%股票成交占比", _fmt_ratio_pct(latest.get("top_10pct_turnover_share")), "成交集中度"),
        ("前三行业正贡献占比", _fmt_ratio_pct(latest.get("top3_industry_positive_contribution_share")), "使用当前行业分类，PIT受限"),
        ("前五行业成交占比", _fmt_ratio_pct(latest.get("top5_industry_turnover_share")), "行业成交集中度"),
        ("权重收益－等权收益", _fmt_pct(latest.get("weighted_vs_equal_return_gap")), "权重股相对市场等权差"),
        ("指数权重HHI", _fmt_num(latest.get("weight_hhi"), 4), f"权重成员 {_fmt_int(latest.get('weight_member_count'))}"),
    ]
    return "".join(
        f"<tr><td>{escape(label)}</td><td>{escape(value)}</td><td>{escape(note)}</td></tr>"
        for label, value, note in metrics
    ) if latest else "<tr><td colspan='3'>当前文件没有贡献/集中度 v2 数据。</td></tr>"


def _state_history_rows(structure: dict[str, Any]) -> str:
    timeline = (((structure.get("market_structure") or {}).get("state_history") or {}).get("dimensions") or {})
    names = {"participation": "参与度", "breadth": "广度", "concentration": "集中度", "risk": "风险", "leadership": "领涨质量", "style": "风格领先", "repair": "修复", "divergence": "指数/个股分化"}
    rows = []
    for key, item in timeline.items():
        segments = item.get("segments") or []
        current = segments[-1] if segments else {}
        rows.append(
            f"<tr><td>{escape(names.get(str(key), str(key)))}</td><td>{_state_chip(current.get('state'))}</td>"
            f"<td>{escape(str(current.get('start_date') or '--'))}</td><td>{escape(str(current.get('end_date') or '--'))}</td>"
            f"<td>{escape(_fmt_int(current.get('duration_trading_days')))}</td><td>{escape(_fmt_int(len(segments)))}</td></tr>"
        )
    return "".join(rows) or "<tr><td colspan='6'>当前文件没有状态历史 v2 数据。</td></tr>"


def _evidence_matrix_rows(structure: dict[str, Any]) -> str:
    evidence = ((structure.get("market_structure") or {}).get("evidence") or {})
    rows = []
    for key, item in evidence.items():
        rows.append(
            f"<tr><td>{escape(str(key))}</td><td>{_state_chip(item.get('state'))}</td><td>{_confidence_chip(item.get('confidence'))}</td>"
            f"<td>{escape(_fmt_ratio_pct(item.get('confidence_score')))}</td><td>{escape(_fmt_int(item.get('independent_evidence_families')))}</td>"
            f"<td>{escape(_fmt_ratio_pct(item.get('coverage')))}</td><td>{'是' if item.get('freshness_ok') else '否'}</td><td>{'是' if item.get('point_in_time') else '否/受限'}</td></tr>"
        )
    return "".join(rows) or "<tr><td colspan='8'>无 v2 证据矩阵。</td></tr>"


def _source_freshness_rows(structure: dict[str, Any]) -> str:
    rows = []
    for key, item in (structure.get("source_freshness") or {}).items():
        rows.append(
            f"<tr><td>{escape(str(key))}</td><td>{escape(str(item.get('source') or '--'))}</td>"
            f"<td>{escape(str(item.get('data_date') or '--'))}</td><td>{escape(str(item.get('as_of') or '--'))}</td>"
            f"<td>{escape(_fmt_int(item.get('lag_trading_days')))}</td><td>{_state_chip(item.get('status'))}</td>"
            f"<td>{'是' if item.get('point_in_time') else '否/受限'}</td></tr>"
        )
    return "".join(rows) or "<tr><td colspan='7'>无来源新鲜度矩阵。</td></tr>"


def _point_in_time_rows(structure: dict[str, Any]) -> str:
    names = {
        "as_of": "报告时点", "index_quotes": "指数行情", "index_weight_snapshots": "指数权重快照",
        "stock_universe": "历史股票池", "industry_classification": "历史行业分类",
        "historical_st_status": "历史ST状态", "future_rows_used": "是否使用未来数据",
    }
    rows = []
    for key, value in (structure.get("point_in_time") or {}).items():
        if isinstance(value, bool):
            display = "是" if value else "否"
            if key == "future_rows_used":
                display = "否（通过）" if not value else "是（异常）"
        else:
            display = str(value or "--")
        rows.append(f"<tr><td>{escape(names.get(str(key), str(key)))}</td><td>{escape(display)}</td></tr>")
    return "".join(rows) or "<tr><td colspan='2'>无 PIT 声明。</td></tr>"


def _breadth_metric_cards(structure: dict[str, Any]) -> str:
    latest = (structure.get("breadth") or {}).get("latest") or {}
    items = [
        (
            "上涨/下跌/平盘家数",
            f"{_fmt_int(latest.get('advance_count'))}/{_fmt_int(latest.get('decline_count'))}/{_fmt_int(latest.get('flat_count'))}",
            "以上一交易日有效收盘价为基准，统计当日收益大于0、小于0、等于0的股票数。停牌、缺失价格和无有效收益的股票不进入分母。",
        ),
        (
            "有效股票数",
            _fmt_int(latest.get("valid_stock_count")),
            "当日能参与横截面统计的股票数量。它决定涨跌比例、收益中位数、A/D等指标的样本范围。",
        ),
        (
            "上涨/下跌比例",
            f"{_fmt_ratio_pct(latest.get('advance_ratio'), 1)} / {_fmt_ratio_pct(latest.get('decline_ratio'), 1)}",
            "上涨家数和下跌家数分别除以有效股票数。上涨比例高于50%通常表示个股扩散较好，低于40%说明赚钱效应偏弱。",
        ),
        (
            "个股中位/等权1日收益",
            f"{_fmt_pct(latest.get('median_stock_return_1d'))} / {_fmt_pct(latest.get('equal_weight_return_1d'))}",
            "中位数用于观察典型股票表现，等权收益让每只有效股票权重相同。两者能辅助判断指数涨跌是否被少数权重股带动。",
        ),
        (
            "MA20/50/200上方比例",
            f"{_fmt_ratio_pct(latest.get('pct_above_ma20'), 1)} / {_fmt_ratio_pct(latest.get('pct_above_ma50'), 1)} / {_fmt_ratio_pct(latest.get('pct_above_ma200'), 1)}",
            "分别统计站上20、50、200日均线的有效股票比例。MA20偏短期参与度，MA50偏中期结构，MA200偏长期趋势覆盖。",
        ),
        (
            "标准化A/D（当日/5日/20日）",
            f"{_fmt_signed_num(latest.get('normalized_ad'), 3)} / {_fmt_signed_num(latest.get('normalized_ad_5d'), 3)} / {_fmt_signed_num(latest.get('normalized_ad_20d'), 3)}",
            "当日A/D =（上涨家数 - 下跌家数）/（上涨家数 + 下跌家数）。5日和20日是滚动求和，用来观察广度连续性，不是收益率。",
        ),
        (
            "20日新高/新低比例",
            f"{_fmt_ratio_pct(latest.get('new_high_20_ratio'), 2)} / {_fmt_ratio_pct(latest.get('new_low_20_ratio'), 2)}",
            "统计当日收盘是否突破此前20个交易日高点或低点。历史窗口不包含触发日，避免把当天价格反向纳入基准。",
        ),
        (
            "60日新高/新低比例",
            f"{_fmt_ratio_pct(latest.get('new_high_60_ratio'), 2)} / {_fmt_ratio_pct(latest.get('new_low_60_ratio'), 2)}",
            "用更长窗口观察趋势扩散和破位范围。新低比例持续高企时，说明尾部压力仍在扩散。",
        ),
        (
            "上涨超3%/5%",
            f"{_fmt_ratio_pct(latest.get('advance_gt_3_ratio'), 2)} / {_fmt_ratio_pct(latest.get('advance_gt_5_ratio'), 2)}",
            "统计强势上涨股票占比。它比普通上涨比例更强调风险偏好和弹性，适合观察进攻扩散。",
        ),
        (
            "下跌超3%/5%",
            f"{_fmt_ratio_pct(latest.get('decline_gt_3_ratio'), 2)} / {_fmt_ratio_pct(latest.get('decline_gt_5_ratio'), 2)}",
            "统计大幅下跌股票占比。该指标越高，尾部风险越重，指数反弹也可能只是少数权重托底。",
        ),
        (
            "近似涨停/跌停",
            f"{_fmt_ratio_pct(latest.get('approximate_limit_up_ratio'), 2)} / {_fmt_ratio_pct(latest.get('approximate_limit_down_ratio'), 2)}",
            "用日收益阈值近似识别涨停和跌停股票比例。它是情绪和流动性压力的粗略代理，不等同交易所精确涨跌停状态。",
        ),
        (
            "横截面离散度/5日波动",
            f"{_fmt_ratio_pct(latest.get('cross_section_dispersion'), 2)} / {_fmt_ratio_pct(latest.get('market_realized_volatility_5d'), 2)}",
            "横截面离散度描述个股当日收益分化，5日波动描述全市场等权收益近期波动。两者升高时，市场结构更不稳定。",
        ),
    ]
    return "".join(
        "<details class='breadth-metric'>"
        f"<summary><span class='breadth-metric-title'>{escape(label)}</span><span class='breadth-metric-value'>{escape(value)}</span></summary>"
        f"<div class='breadth-metric-detail'>{escape(detail)}</div>"
        "</details>"
        for label, value, detail in items
    )


def _index_structure_rows(structure: dict[str, Any]) -> str:
    trend_names = {"uptrend": "上升", "sideways": "震荡", "downtrend": "下降", "mixed": "分化"}
    rows = []
    for item in (structure.get("indices") or {}).values():
        if not item.get("available"):
            rows.append(
                f"<tr><td>{escape(str(item.get('name')))}</td><td>{escape(str(item.get('symbol')))}</td>"
                "<td colspan='15'>暂无本地指数数据</td></tr>"
            )
            continue
        display_name = escape(str(item.get("name")))
        if item.get("synthetic"):
            display_name += '<br><span class="muted">非官方指数</span>'
        rows.append(
            "<tr>"
            f"<td>{display_name}</td><td>{escape(str(item.get('symbol')))}</td>"
            f"<td class='{_tone(item.get('return_1d'))}'>{escape(_fmt_pct(item.get('return_1d')))}</td>"
            f"<td class='{_tone(item.get('return_5d'))}'>{escape(_fmt_pct(item.get('return_5d')))}</td>"
            f"<td class='{_tone(item.get('return_10d'))}'>{escape(_fmt_pct(item.get('return_10d')))}</td>"
            f"<td class='{_tone(item.get('return_20d'))}'>{escape(_fmt_pct(item.get('return_20d')))}</td>"
            f"<td class='{_tone(item.get('return_60d'))}'>{escape(_fmt_pct(item.get('return_60d')))}</td>"
            f"<td>{escape(trend_names.get(str(item.get('daily_trend')), '数据不足'))}</td>"
            f"<td>{escape(trend_names.get(str(item.get('weekly_trend')), '数据不足'))}</td>"
            f"<td>{escape(_fmt_multiple(item.get('amount_ratio_20d'), 2))}</td>"
            f"<td>{escape(_fmt_num(item.get('ma20'), 2))}</td>"
            f"<td>{escape(_fmt_num(item.get('ma60'), 2))}</td>"
            f"<td>{escape(_fmt_num(item.get('high_20d'), 2))}<br><span class='muted'>{escape(_fmt_pct(item.get('distance_high_20d')))}</span></td>"
            f"<td>{escape(_fmt_num(item.get('low_20d'), 2))}<br><span class='muted'>{escape(_fmt_pct(item.get('distance_low_20d')))}</span></td>"
            f"<td>{escape(_fmt_num(item.get('high_60d'), 2))}<br><span class='muted'>{escape(_fmt_pct(item.get('distance_high_60d')))}</span></td>"
            f"<td>{escape(_fmt_num(item.get('low_60d'), 2))}<br><span class='muted'>{escape(_fmt_pct(item.get('distance_low_60d')))}</span></td>"
            f"<td>{escape(str(item.get('support_pressure', '--')))}</td>"
            "</tr>"
        )
    return "".join(rows) or "<tr><td colspan='17'>暂无指数数据</td></tr>"


def _style_rows(structure: dict[str, Any]) -> str:
    rows = []
    for item in (structure.get("styles") or {}).values():
        if item.get("basket_type") in {"official_index_proxy", "ths_index_proxy"}:
            ma20 = {"above": "MA20上方", "below": "MA20下方"}.get(str(item.get("ma20_state")), "MA20数据不足")
            ma60 = {"above": "MA60上方", "below": "MA60下方"}.get(str(item.get("ma60_state")), "MA60数据不足")
            if item.get("basket_type") == "ths_index_proxy":
                internal = (
                    f"{item.get('proxy_note') or '同花顺指数代理'} · "
                    f"代理指数{escape(str(item.get('index_count', '--')))}个 · "
                    f"MA20上方{_fmt_ratio_pct(item.get('pct_above_ma20'))} · "
                    f"成交{_fmt_multiple(item.get('amount_ratio_20d'))}"
                )
                basket_label = "同花顺指数代理"
            else:
                internal = f"{item.get('proxy_note') or '指数代理，无内部个股广度'} · {ma20}/{ma60} · 成交{_fmt_multiple(item.get('amount_ratio_20d'))}"
                basket_label = "指数代理"
        else:
            internal = f"上涨{_fmt_ratio_pct(item.get('advance_ratio'))} · MA20上方{_fmt_ratio_pct(item.get('pct_above_ma20'))}"
            basket_label = "股票篮子"
        rows.append(
            "<tr>"
            f"<td>{escape(str(item.get('name')))}<br><span class='muted'>{escape(basket_label)}</span></td>"
            f"<td class='{_tone(item.get('return_5d'))}'>{escape(_fmt_pct(item.get('return_5d')))}</td>"
            f"<td class='{_tone(item.get('return_20d'))}'>{escape(_fmt_pct(item.get('return_20d')))}</td>"
            f"<td class='{_tone(item.get('return_60d'))}'>{escape(_fmt_pct(item.get('return_60d')))}</td>"
            f"<td>{escape(_style_state_text(item.get('state_5d')))}</td>"
            f"<td>{escape(_style_state_text(item.get('state_20d')))}</td>"
            f"<td>{escape(_style_state_text(item.get('state_60d')))}</td>"
            f"<td class='{_tone(item.get('relative_all_a_20d'))}'>{escape(_fmt_pct(item.get('relative_all_a_20d')))}</td>"
            f"<td>{escape(internal)}</td>"
            f"<td>{escape(_fmt_num(item.get('strength'), 1))}</td>"
            f"<td>{escape(_momentum_text(item.get('momentum_direction')))}</td>"
            "</tr>"
        )
    return "".join(rows) or "<tr><td colspan='11'>暂无可靠风格数据</td></tr>"


def _style_contribution_details(structure: dict[str, Any]) -> str:
    blocks = []
    for item in (structure.get("styles") or {}).values():
        if item.get("basket_type") != "stock_basket":
            continue
        contributions = item.get("industry_contributions") or {}

        def names(key: str) -> str:
            rows = contributions.get(key) or []
            return "、".join(
                f"{row.get('industry')}(收益{_fmt_pct(row.get('return'))}，贡献{_fmt_pct(row.get('contribution'))})"
                for row in rows
            ) or "数据不足"

        coverage = _fmt_ratio_pct(item.get("data_coverage"), 1)
        blocks.append(
            "<details>"
            f"<summary>{escape(str(item.get('name')))}：行业贡献</summary>"
            f"<div class='compact-note'>行业数 {escape(str(item.get('industry_count', '--')))} · 股票数 {escape(str(item.get('stock_count', '--')))} · 有效 {escape(str(item.get('valid_stock_count', '--')))} · 覆盖率 {escape(coverage)}</div>"
            f"<div class='compact-note'><strong>5日贡献前三：</strong>{escape(names('top_5d'))}<br><strong>5日拖累前三：</strong>{escape(names('bottom_5d'))}<br>"
            f"<strong>20日贡献前三：</strong>{escape(names('top_20d'))}<br><strong>20日拖累前三：</strong>{escape(names('bottom_20d'))}</div>"
            "</details>"
        )
    return "".join(blocks)


def _style_method_note() -> str:
    return (
        "市场风格优先使用同花顺行业/风格代理指数缓存：权重价值、证券风险偏好、科技成长、消费由若干同花顺行业指数等权代理，"
        "小盘题材优先使用同花顺小盘指数；缺少缓存时才回退到本地股票篮子。"
        "同花顺指数比当前行业字段拼篮子更稳定，适合做风格温度计；若要交易化，仍建议维护专门股票池或官方风格/主题指数清单，并做时点成分管理。"
    )


def _industry_rows(items: list[dict[str, Any]], clickable_symbols: set[str] | None = None) -> str:
    clickable_symbols = clickable_symbols or set()
    rows: list[str] = []
    for item in items:
        symbol = str(item.get("symbol") or "").upper()
        industry = str(item.get("industry") or "--")
        clickable = symbol in clickable_symbols
        attrs = (
            f" class='industry-row-clickable' data-industry-symbol='{escape(symbol, quote=True)}' onclick='switchIndustryKline(\"{escape(symbol, quote=True)}\")'"
            if clickable else ""
        )
        label = (
            f"<span class='industry-link'>{escape(industry)}</span><br><small>{escape(symbol)}</small>"
            if clickable else escape(industry)
        )
        rows.append(
            f"<tr{attrs}>"
            f"<td>{label}</td>"
            f"<td class='{_tone(item.get('return_1d'))}'>{escape(_fmt_pct(item.get('return_1d')))}</td>"
            f"<td class='{_tone(item.get('return_5d'))}'>{escape(_fmt_pct(item.get('return_5d')))}</td>"
            f"<td class='{_tone(item.get('return_20d'))}'>{escape(_fmt_pct(item.get('return_20d')))}</td>"
            f"<td>{escape(_fmt_ratio_pct(item.get('advance_ratio')))}</td>"
            f"<td>{escape(_fmt_ratio_pct(item.get('pct_above_ma20')))}</td>"
            f"<td class='{_tone(item.get('amount_share_change_20d'))}'>{escape(_fmt_pct(item.get('amount_share_change_20d')))}</td>"
            "</tr>"
        )
    return "".join(rows) or "<tr><td colspan='7'>暂无行业数据</td></tr>"


def _risk_direction_rows(structure: dict[str, Any]) -> str:
    risk = ((structure.get("market_structure") or {}).get("risk") or {})
    latest = ((structure.get("breadth") or {}).get("latest") or {})
    direction_values = {
        "expanding": "正在扩散",
        "stable": "相对稳定",
        "contracting": "正在收缩",
        "repairing": "正在修复",
    }
    pressure_values = {"low": "较低", "medium": "中等", "high": "较高", "extreme": "极端"}
    items = [
        (
            "尾部压力等级",
            pressure_values.get(str(risk.get("pressure_level")), "数据不足"),
            (
                "描述当前市场尾部风险水平，主要观察跌超5%、近似跌停、20日新低、横截面波动和5日实现波动等是否处在历史偏高位置。"
                "它是当前压力刻画，不是未来下跌概率。"
            ),
        ),
        (
            "20日新低方向",
            direction_values.get(str(risk.get("new_low_direction")), "数据不足"),
            (
                f"观察创20日新低股票比例的变化。当前20日新低比例为{_fmt_ratio_pct(latest.get('new_low_20_ratio'), 2)}；"
                "扩散表示破位个股覆盖面扩大，收缩/修复表示尾部抛压减轻。"
            ),
        ),
        (
            "跌超5%方向",
            direction_values.get(str(risk.get("large_decline_direction")), "数据不足"),
            (
                f"观察当日跌幅超过5%的股票比例变化。当前跌超5%比例为{_fmt_ratio_pct(latest.get('decline_gt_5_ratio'), 2)}；"
                "该指标更偏向衡量极端下跌是否扩散。"
            ),
        ),
        (
            "A/D方向",
            direction_values.get(str(risk.get("ad_direction")), "数据不足"),
            (
                f"A/D 是上涨家数与下跌家数的标准化差值，当前5日A/D为{_fmt_num(latest.get('normalized_ad_5d'), 3)}。"
                "它反映市场广度是在改善还是恶化。"
            ),
        ),
        (
            "NH-NL方向",
            direction_values.get(str(risk.get("nhnl_direction")), "数据不足"),
            (
                f"NH-NL 是新高数量减新低数量后的广度信号，当前20日新高/新低为"
                f"{_fmt_ratio_pct(latest.get('new_high_20_ratio'), 2)} / {_fmt_ratio_pct(latest.get('new_low_20_ratio'), 2)}。"
                "它用来观察趋势端的强势扩散和弱势扩散谁占优。"
            ),
        ),
        (
            "综合风险方向",
            direction_values.get(str(risk.get("risk_direction")), "数据不足"),
            (
                "综合20日新低、跌超5%、A/D、NH-NL等多个方向信号，描述风险相对上一阶段是在扩散、稳定、收缩还是修复。"
                "方向与压力等级互补：方向看变化，等级看当前水位。"
            ),
        ),
    ]
    blocks = []
    for label, value, detail in items:
        blocks.append(
            "<details class='risk-explain-item'>"
            f"<summary><span class='risk-explain-name'>{escape(label)}</span>"
            f"<span class='risk-explain-value'>{escape(value)}</span></summary>"
            f"<div class='risk-explain-detail'>{escape(detail)}</div>"
            "</details>"
        )
    return "".join(blocks)


def _sector_rows(structure: dict[str, Any]) -> str:
    rows = []
    for name, item in (structure.get("sector_details") or {}).items():
        if item.get("basket_type") == "ths_index_proxy":
            symbols = ", ".join(str(symbol) for symbol in item.get("symbols") or [])
            sample = (
                f"<span class='sector-sample'>代理指数{escape(str(item.get('index_count', '--')))}个"
                f"<small>{escape(symbols or str(item.get('data_source') or '同花顺指数代理'))}</small></span>"
            )
            amount_evidence = _fmt_multiple(item.get("amount_ratio_20d"))
        else:
            sample = escape(str(item.get("stock_count", "--")))
            amount_evidence = _fmt_ratio_pct(item.get("amount_share"), 2)
        rows.append(
            "<tr>"
            f"<td>{escape(str(name))}</td>"
            f"<td>{sample}</td>"
            f"<td class='{_tone(item.get('return_1d'))}'>{escape(_fmt_pct(item.get('return_1d')))}</td>"
            f"<td class='{_tone(item.get('return_5d'))}'>{escape(_fmt_pct(item.get('return_5d')))}</td>"
            f"<td class='{_tone(item.get('return_20d'))}'>{escape(_fmt_pct(item.get('return_20d')))}</td>"
            f"<td>{escape(_fmt_ratio_pct(item.get('advance_ratio'), 1))}</td>"
            f"<td>{escape(_fmt_ratio_pct(item.get('pct_above_ma20'), 1))}</td>"
            f"<td>{escape(amount_evidence)}</td>"
            "</tr>"
        )
    return "".join(rows) or "<tr><td colspan='8'>暂无银行、保险或证券数据</td></tr>"


def _relative_strength_rows(structure: dict[str, Any]) -> str:
    names = {
        "value_vs_growth_5d": "权重价值相对科技成长5日",
        "value_vs_growth_20d": "权重价值相对科技成长20日",
        "value_vs_growth_60d": "权重价值相对科技成长60日",
        "securities_vs_bank_5d": "证券相对银行5日",
        "securities_vs_bank_20d": "证券相对银行20日",
        "consumer_vs_all_a_20d": "消费相对平均股价20日",
        "small_vs_hs300_20d": "小盘相对沪深300 20日",
        "hs300_vs_all_a_5d": "沪深300相对平均股价 5日",
        "hs300_vs_all_a_20d": "沪深300相对平均股价 20日",
    }
    return "".join(
        f"<tr><td>{escape(names.get(key, key))}</td><td class='{_tone(value)}'>{escape(_fmt_pct(value))}</td></tr>"
        for key, value in (structure.get("relative_strength") or {}).items()
    )


def _quality_flags(structure: dict[str, Any]) -> str:
    names = {
        "current_tushare_industry_classification_used_for_history": "当前行业分类用于历史回溯",
        "incomplete_point_in_time_universe": "历史股票池不完整",
        "missing_delisted_stocks": "缺少历史退市股票",
        "missing_historical_st_status": "缺少历史ST状态",
        "limit_up_down_is_board_aware_approximation": "涨跌停为分板块近似统计",
        "theme_history_not_backfilled": "历史题材成分未回填",
        "small_cap_official_index_proxy_used": "小盘题材使用官方指数代理",
        "ths_style_proxy_indexes_used": "风格使用同花顺指数代理",
        "financial_sector_proxy_indexes_used": "银行/保险/证券使用同花顺行业指数",
        "ths_industry_rankings_used": "行业强弱榜使用同花顺行业指数",
        "v2_descriptive_states_only": "v2 仅描述当前结构，不做收益预测",
        "current_stock_universe_not_point_in_time": "股票池不是历史时点成分",
        "current_industry_classification_used_for_concentration_history": "集中度历史使用当前行业分类",
        "current_industry_classification_used_for_history": "行业历史使用当前分类",
        "weight_data_not_point_in_time": "指数权重缺少历史时点快照",
        "valuation_context_not_loaded": "估值上下文未接入",
        "external_context_not_loaded": "外部资金/情绪上下文未接入",
        "all_a_vendor_amount_unavailable": "旧供应商成交额字段不可用",
        MARKET_BENCHMARK_QUALITY_FLAG: "平均股价基准使用本地股票池等权代理",
    }
    def label(flag: str) -> str:
        if flag.startswith("missing_index_data:"):
            parts = flag.split(":", 2)
            return f"指数数据缺失：{parts[1]} {parts[2]}" if len(parts) == 3 else "指数数据缺失"
        return names.get(flag, flag)
    return "".join(
        f"<span class='flag' title='{escape(str(flag), quote=True)}'>{escape(label(str(flag)))}</span>"
        for flag in structure.get("data_quality_flags") or []
    )


def _evaluation_chart_payload(evaluation: dict[str, Any]) -> dict[str, Any]:
    environment = evaluation.get("environment_evaluation") or {}
    buckets = environment.get("label_summary") or evaluation.get("score_buckets") or []
    curve = evaluation.get("timing_curve") or []
    return {
        "bucket_names": [_signal_text(str(item.get("label", item.get("bucket", "")))) for item in buckets],
        "bucket_avg_return": [item.get("equal_weight_return", item.get("avg_return")) for item in buckets],
        "bucket_win_rate": [item.get("stock_win_rate", item.get("win_rate")) for item in buckets],
        "curve_dates": [str(item.get("date", "")) for item in curve],
        "strategy": [item.get("strategy") for item in curve],
        "buyhold": [item.get("buyhold") for item in curve],
        "exposure": [item.get("exposure") for item in curve],
    }


def _signal_summary_rows(evaluation: dict[str, Any]) -> str:
    rows = []
    environment = evaluation.get("environment_evaluation") or {}
    for item in environment.get("label_summary") or []:
        equal_ret = item.get("equal_weight_return")
        rows.append(
            f"""
            <tr>
              <td>{escape(_signal_text(str(item.get('label', ''))))}</td>
              <td>{escape(str(item.get('count', 0)))}</td>
              <td class="{_tone(item.get('median_stock_return'))}">{escape(_fmt_pct(item.get('median_stock_return'), 2))}</td>
              <td class="{_tone(equal_ret)}">{escape(_fmt_pct(equal_ret, 2))}</td>
              <td>{escape(_fmt_ratio_pct(item.get('stock_win_rate'), 1))}</td>
              <td class="{_tone(item.get('tail_loss_q10'))}">{escape(_fmt_pct(item.get('tail_loss_q10'), 2))}</td>
              <td class="{_tone(item.get('median_max_drawdown'))}">{escape(_fmt_pct(item.get('median_max_drawdown'), 2))}</td>
              <td>{escape(_fmt_ratio_pct(item.get('hit_rate'), 1))}</td>
            </tr>
            """
        )
    return "".join(rows) or "<tr><td colspan='8'>暂无可评估样本</td></tr>"


def _score_bucket_rows(evaluation: dict[str, Any]) -> str:
    rows = []
    for item in evaluation.get("score_buckets") or []:
        avg_ret = item.get("avg_return")
        rows.append(
            f"""
            <tr>
              <td>{escape(str(item.get('bucket', '')))}</td>
              <td>{escape(str(item.get('count', 0)))}</td>
              <td class="{_tone(avg_ret)}">{escape(_fmt_pct(avg_ret, 2))}</td>
              <td class="{_tone(item.get('median_return'))}">{escape(_fmt_pct(item.get('median_return'), 2))}</td>
              <td>{escape(_fmt_ratio_pct(item.get('win_rate'), 1))}</td>
            </tr>
            """
        )
    return "".join(rows) or "<tr><td colspan='5'>暂无可评估样本</td></tr>"


def _strategy_environment_rows(evaluation: dict[str, Any]) -> str:
    rows = []
    environment = evaluation.get("environment_evaluation") or {}
    for item in environment.get("label_summary") or []:
        for strategy, value in (item.get("strategy_returns") or {}).items():
            rows.append(
                f"<tr><td>{escape(_signal_text(str(item.get('label', ''))))}</td>"
                f"<td>{escape(str(strategy))}</td><td class='{_tone(value)}'>{escape(_fmt_pct(value, 2))}</td></tr>"
            )
    return "".join(rows) or "<tr><td colspan='3'>暂无可对齐的策略权益曲线</td></tr>"


def _strategy_filter_rows(evaluation: dict[str, Any]) -> str:
    rows = []
    environment = evaluation.get("environment_evaluation") or {}
    for item in environment.get("strategy_filter_comparison") or []:
        before = item.get("before") or {}
        after = item.get("after") or {}
        rows.append(
            "<tr>"
            f"<td>{escape(str(item.get('strategy', '')))}</td>"
            f"<td>{escape(_fmt_pct(before.get('return'), 2))}</td>"
            f"<td>{escape(_fmt_pct(after.get('return'), 2))}</td>"
            f"<td>{escape(_fmt_ratio_pct(before.get('win_rate'), 1))}</td>"
            f"<td>{escape(_fmt_ratio_pct(after.get('win_rate'), 1))}</td>"
            f"<td>{escape(_fmt_pct(before.get('max_drawdown'), 2))}</td>"
            f"<td>{escape(_fmt_pct(after.get('max_drawdown'), 2))}</td>"
            f"<td>{escape(_fmt_num(before.get('payoff_ratio'), 2))}</td>"
            f"<td>{escape(_fmt_num(after.get('payoff_ratio'), 2))}</td>"
            f"<td>{escape(_fmt_pct(item.get('positive_to_conservative_before_avg_20d_drawdown'), 2))}</td>"
            f"<td>{escape(_fmt_pct(item.get('positive_to_conservative_after_avg_20d_drawdown'), 2))}</td>"
            f"<td>{escape(_fmt_pct(item.get('positive_to_conservative_drawdown_change'), 2))}</td>"
            "</tr>"
        )
    return "".join(rows) or "<tr><td colspan='12'>暂无可对齐的策略权益曲线</td></tr>"


def _recent_rows(predictions: pd.DataFrame, horizon: int) -> str:
    rows = []
    suffix = f"_{int(horizon)}d"
    label_col = f"environment_label{suffix}"
    for _, row in predictions.tail(20).iloc[::-1].iterrows():
        signal = str(row.get("environment_signal", "neutral"))
        equal_return = row.get(f"equal_weight_return{suffix}")
        rows.append(
            f"""
            <tr>
              <td>{escape(str(row.get('trade_date', '')))}</td>
              <td>{escape(_fmt_num(row.get('close'), 2))}</td>
              <td class="{_tone(None, signal)}">{escape(_signal_text(signal))}</td>
              <td>{escape(_fmt_num(row.get('market_score'), 1))}</td>
              <td>{_fmt_breadth_triplet_html(row)}</td>
              <td class="{_tone(row.get(f'median_stock_return{suffix}'))}">{escape(_fmt_pct(row.get(f'median_stock_return{suffix}'), 2))}</td>
              <td class="{_tone(equal_return)}">{escape(_fmt_pct(equal_return, 2))}</td>
              <td>{escape(_fmt_ratio_pct(row.get(f'stock_win_rate{suffix}'), 1))}</td>
              <td class="{_tone(row.get(f'return_q10{suffix}'))}">{escape(_fmt_pct(row.get(f'return_q10{suffix}'), 2))}</td>
              <td>{escape(str(row.get(f'divergence_label{suffix}', '') if pd.notna(row.get(f'divergence_label{suffix}', None)) else ''))}</td>
              <td>{escape(_signal_text(str(row.get(label_col, '') if pd.notna(row.get(label_col, None)) else '')))}</td>
            </tr>
            """
        )
    return "".join(rows)


_JS = r"""
<script>
(function(){
var C={up:'#c94343',down:'#168457',blue:'#2f6df6',orange:'#d38b24',pink:'#dc5f7d',axis:'#69748a',line:'#d9e0ea',split:'#edf0f5',ink:'#172033'};
function ax(d){return{data:d,boundaryGap:true,axisLabel:{fontSize:10,color:C.axis,rotate:30},axisLine:{lineStyle:{color:C.line}},splitLine:{show:true,lineStyle:{type:'dashed',color:C.split}}};}
function ya(name){return{type:'value',scale:true,name:name||'',axisLabel:{fontSize:10,color:C.axis},splitLine:{show:true,lineStyle:{type:'dashed',color:C.split}}};}
function dz(d){var start=Math.max(65,100-Math.max(35,100*160/Math.max(d.dates.length,1)));return[{type:'inside',start:start,end:100},{type:'slider',start:start,end:100,height:22,bottom:0}];}
function chart(id,opt){var el=document.getElementById(id);if(!el)return null;var c=echarts.init(el,null,{renderer:'canvas'});c.setOption(opt);return c;}
function init(){
 var d=window._FORECAST_CHART||{}; if(!d.dates||!d.dates.length)return;
 var charts=[];
 var xMain=ax(d.dates),xScore=ax(d.dates),yMain=ya('指数'),yScore=ya('分数'); xMain.axisLabel={show:false};xScore.gridIndex=1;yScore.gridIndex=1;
 charts.push(chart('forecast-kline',{tooltip:{trigger:'axis',axisPointer:{type:'cross'}},legend:{top:14,data:['K线','MA20','MA60','MA120','20日高点','20日低点']},grid:{left:52,right:48,top:56,bottom:58},xAxis:ax(d.dates),yAxis:ya('指数'),dataZoom:dz(d),series:[{name:'K线',type:'candlestick',data:d.ohlc,itemStyle:{color:C.up,color0:C.down,borderColor:C.up,borderColor0:C.down}},{name:'MA20',type:'line',data:d.ma20,symbol:'none',lineStyle:{color:C.blue,width:1.5}},{name:'MA60',type:'line',data:d.ma60,symbol:'none',lineStyle:{color:C.orange,width:1.5}},{name:'MA120',type:'line',data:d.ma120,symbol:'none',lineStyle:{color:C.pink,width:1.5}},{name:'20日高点',type:'line',data:d.high20,symbol:'none',lineStyle:{color:C.up,width:1,type:'dashed'}},{name:'20日低点',type:'line',data:d.low20,symbol:'none',lineStyle:{color:C.down,width:1,type:'dashed'}}]}));
 charts.push(chart('structure-technical',{tooltip:{trigger:'axis'},legend:{top:10,data:['K','D','J','DIF','DEA','MACD柱']},grid:[{left:52,right:32,top:50,height:'34%'},{left:52,right:32,top:'57%',height:'28%'}],xAxis:[ax(d.dates),Object.assign(ax(d.dates),{gridIndex:1})],yAxis:[ya('KDJ'),Object.assign(ya('MACD'),{gridIndex:1})],dataZoom:dz(d),series:[{name:'K',type:'line',data:d.kdj_k,symbol:'none',lineStyle:{color:C.blue}},{name:'D',type:'line',data:d.kdj_d,symbol:'none',lineStyle:{color:C.orange}},{name:'J',type:'line',data:d.kdj_j,symbol:'none',lineStyle:{color:C.pink}},{name:'DIF',type:'line',xAxisIndex:1,yAxisIndex:1,data:d.macd_dif,symbol:'none',lineStyle:{color:C.blue}},{name:'DEA',type:'line',xAxisIndex:1,yAxisIndex:1,data:d.macd_dea,symbol:'none',lineStyle:{color:C.orange}},{name:'MACD柱',type:'bar',xAxisIndex:1,yAxisIndex:1,data:d.macd_hist,itemStyle:{color:function(p){return p.value>=0?C.up:C.down;}}}]}));
 charts.push(chart('forecast-ad',{tooltip:{trigger:'axis'},legend:{top:14,data:['A/D斜率5','A/D斜率20','NH-NL斜率5','NH-NL斜率20']},grid:{left:52,right:30,top:56,bottom:58},xAxis:ax(d.dates),yAxis:ya('斜率'),dataZoom:dz(d),series:[{name:'A/D斜率5',type:'line',data:d.ad_slope_5,symbol:'none',lineStyle:{color:C.blue,width:2}},{name:'A/D斜率20',type:'line',data:d.ad_slope_20,symbol:'none',lineStyle:{color:C.orange,width:2}},{name:'NH-NL斜率5',type:'line',data:d.nhnl_slope_5,symbol:'none',lineStyle:{color:C.pink,width:2}},{name:'NH-NL斜率20',type:'line',data:d.nhnl_slope_20,symbol:'none',lineStyle:{color:C.down,width:2}}]}));
 var m=window._MARKET_STRUCTURE||{};
 if(m.dates&&m.dates.length){
  charts.push(chart('structure-breadth',{tooltip:{trigger:'axis'},legend:{top:10,data:['上涨比例','MA20上方','MA50上方','MA200上方','标准化A/D']},grid:{left:52,right:42,top:50,bottom:58},xAxis:ax(m.dates),yAxis:[ya('比例'),ya('A/D')],dataZoom:dz(m),series:[{name:'上涨比例',type:'line',data:m.advance_ratio,symbol:'none',lineStyle:{color:C.up,width:1.5}},{name:'MA20上方',type:'line',data:m.pct_above_ma20,symbol:'none',lineStyle:{color:C.blue,width:1.5}},{name:'MA50上方',type:'line',data:m.pct_above_ma50,symbol:'none',lineStyle:{color:C.orange,width:1.5}},{name:'MA200上方',type:'line',data:m.pct_above_ma200,symbol:'none',lineStyle:{color:C.pink,width:1.5}},{name:'标准化A/D',type:'bar',yAxisIndex:1,data:m.normalized_ad,itemStyle:{color:function(p){return p.value>=0?C.up:C.down;},opacity:.35}}]}));
  charts.push(chart('structure-tail',{tooltip:{trigger:'axis'},legend:{top:10,data:['20日新高','20日新低','NH-NL','跌超5%','近似跌停']},grid:{left:52,right:42,top:50,bottom:58},xAxis:ax(m.dates),yAxis:ya('比例'),dataZoom:dz(m),series:[{name:'20日新高',type:'line',data:m.new_high_20_ratio,symbol:'none',lineStyle:{color:C.up,width:1.5}},{name:'20日新低',type:'line',data:m.new_low_20_ratio,symbol:'none',lineStyle:{color:C.down,width:1.5}},{name:'NH-NL',type:'line',data:m.normalized_nhnl_20,symbol:'none',lineStyle:{color:C.blue,width:1.5}},{name:'跌超5%',type:'bar',data:m.decline_gt_5_ratio,itemStyle:{color:C.down,opacity:.35}},{name:'近似跌停',type:'line',data:m.approximate_limit_down_ratio,symbol:'none',lineStyle:{color:C.ink,width:1,type:'dashed'}}]}));
  charts.push(chart('structure-liquidity',{tooltip:{trigger:'axis'},legend:{top:10,data:['成交额/20日','上涨成交占比','下跌成交占比','平均股价收益']},grid:{left:52,right:42,top:50,bottom:58},xAxis:ax(m.dates),yAxis:[ya('比例'),ya('收益')],dataZoom:dz(m),series:[{name:'成交额/20日',type:'line',data:m.amount_ratio_20,symbol:'none',lineStyle:{color:C.ink,width:2}},{name:'上涨成交占比',type:'line',data:m.advance_amount_ratio,symbol:'none',lineStyle:{color:C.up,width:1.5}},{name:'下跌成交占比',type:'line',data:m.decline_amount_ratio,symbol:'none',lineStyle:{color:C.down,width:1.5}},{name:'平均股价收益',type:'bar',yAxisIndex:1,data:m.all_a_index_return_1d,itemStyle:{color:function(p){return p.value>=0?C.up:C.down;},opacity:.35}}]}));
 }
 if(m.style_dates&&m.style_dates.length){
  charts.push(chart('structure-style',{tooltip:{trigger:'axis'},legend:{top:10,data:['权重价值','证券','科技成长','消费']},grid:{left:52,right:32,top:50,bottom:58},xAxis:ax(m.style_dates),yAxis:ya('强度'),dataZoom:dz({dates:m.style_dates}),series:[{name:'权重价值',type:'line',data:m.value_strength,symbol:'none',lineStyle:{color:C.ink,width:2}},{name:'证券',type:'line',data:m.securities_strength,symbol:'none',lineStyle:{color:C.orange,width:2}},{name:'科技成长',type:'line',data:m.growth_strength,symbol:'none',lineStyle:{color:C.blue,width:2}},{name:'消费',type:'line',data:m.consumer_strength,symbol:'none',lineStyle:{color:C.pink,width:2}}]}));
 }
 var e=window._FORECAST_EVAL||{};
 if(e.bucket_names&&e.bucket_names.length){
  charts.push(chart('forecast-buckets',{tooltip:{trigger:'axis'},legend:{top:14,data:['等权市场收益','上涨股票比例']},grid:{left:52,right:42,top:56,bottom:42},xAxis:{type:'category',data:e.bucket_names,axisLabel:{color:C.axis},axisLine:{lineStyle:{color:C.line}}},yAxis:[ya('收益'),ya('比例')],series:[{name:'等权市场收益',type:'bar',data:e.bucket_avg_return,itemStyle:{color:function(p){return p.value>=0?C.up:C.down;}}},{name:'上涨股票比例',type:'line',yAxisIndex:1,data:e.bucket_win_rate,symbol:'circle',lineStyle:{color:C.blue,width:2}}]}));
 }
 if(e.curve_dates&&e.curve_dates.length){
  charts.push(chart('forecast-equity',{tooltip:{trigger:'axis'},legend:{top:14,data:['规则择时','买入持有','仓位']},grid:{left:52,right:42,top:56,bottom:58},xAxis:ax(e.curve_dates),yAxis:[ya('净值'),ya('仓位')],dataZoom:dz({dates:e.curve_dates}),series:[{name:'规则择时',type:'line',data:e.strategy,symbol:'none',lineStyle:{color:C.up,width:2}},{name:'买入持有',type:'line',data:e.buyhold,symbol:'none',lineStyle:{color:C.ink,width:2}},{name:'仓位',type:'line',yAxisIndex:1,data:e.exposure,symbol:'none',lineStyle:{color:C.blue,width:1,opacity:.55}}]}));
 }
 window.addEventListener('resize',function(){charts.filter(Boolean).forEach(function(c){c.resize();});});
}
window.addEventListener('DOMContentLoaded',init);
})();
</script>
"""


_JS_V11 = r"""
<script>
(function(){
var C={up:'#c94343',down:'#168457',blue:'#2f6df6',orange:'#d38b24',pink:'#dc5f7d',axis:'#69748a',line:'#d9e0ea',split:'#edf0f5',ink:'#172033',purple:'#7654c4'};
function pct(v){return v==null?'--':(v*100).toFixed(1)+'%';}
function signedPct(v){return v==null?'--':(v>=0?'+':'')+(v*100).toFixed(2)+'%';}
function multiple(v){return v==null?'--':Number(v).toFixed(2)+'倍';}
function compactNumber(v){var n=Number(v);if(!isFinite(n))return'--';if(Math.abs(n)>=1e8)return(n/1e8).toFixed(2)+'亿';if(Math.abs(n)>=1e4)return(n/1e4).toFixed(1)+'万';return n.toFixed(0);}
function compactTushareAmount(v){var n=Number(v);if(!isFinite(n))return'--';var cny=n*1000;if(Math.abs(cny)>=1e12)return(cny/1e12).toFixed(2)+'万亿';if(Math.abs(cny)>=1e8)return(cny/1e8).toFixed(2)+'亿';if(Math.abs(cny)>=1e4)return(cny/1e4).toFixed(1)+'万';return cny.toFixed(0);}
function volumeAmountRatio(v){var n=Number(v);if(!isFinite(n))return'--';return n.toFixed(Math.abs(n)>=10?2:3);}
function stateName(v){var names={unknown:'数据不足',fresh:'新鲜',stale:'滞后',missing:'缺失',stable:'稳定',rotating:'轮动',unstable:'不稳定',normal:'常态',dispersed:'分散',moderate:'中等',high:'高',extreme:'极端',moderate_concentration:'中度集中',high_concentration:'高度集中',extreme_concentration:'极端集中',broad_strength:'广泛走强',broad_weakness:'广泛走弱',broad_participation:'广泛参与',selective_participation:'选择性参与',weak_participation:'参与偏弱',broad_rally:'普涨',narrow_rally:'窄幅上涨',mixed:'分化',narrow_decline:'局部下跌',broad_decline:'普跌',risk_expanding:'风险扩张',risk_building:'风险累积',high_pressure_stable:'高压稳定',low_pressure_stable:'低压稳定',risk_contracting:'风险收缩',risk_repairing:'风险修复',repairing:'修复中',panic_expanding:'恐慌扩张',panic_stable:'恐慌稳定',panic_contracting:'恐慌收缩',initial_rebound:'初步反弹',breadth_repair:'广度修复',trend_repair:'趋势修复',failed_rebound:'反弹失败',rebound_confirmed:'反弹确认',rebound_failed:'反弹失败',strong_accelerating:'强势加速',strong_decelerating:'强势减速',weak_improving:'弱势改善',weak_deteriorating:'弱势恶化',building:'持续构筑',decelerating:'强度减速',deteriorating:'转弱',neutral_rotation:'中性轮动',confirmed:'质量确认',failed:'质量失效',heat_building:'热度累积',heat_persistent:'热度持续',exhaustion_warning:'衰竭警示',exhaustion_confirmed:'衰竭确认',selling_expansion:'抛售放量',broad_expansion:'普遍放量',concentrated_expansion:'集中放量',shrinking_rebound:'缩量反弹',quiet:'交投平静',polarized:'两极分化',stocks_stronger:'个股更强',large_cap_stronger:'权重更强',synchronized:'同步',broad_confirmed_rise:'广泛确认上涨',concentrated_but_supported:'集中但有成交支撑',thin_weighted_lift:'缩量拉权重',masked_distribution:'掩护性上涨结构',mixed_divergence:'多空分化'};return names[v]||String(v||'数据不足').replace(/_/g,' ');}
function stateColor(v){if(v==='unknown'||v==='missing'||v==='stale')return'#b6becb';if(/risk|panic|failed|decline|selling|weak/.test(v))return'#c94343';if(/repair|broad_strength|broad_participation|rally|confirmed|fresh/.test(v))return'#168457';if(/high|extreme|warning|concentrated/.test(v))return'#d38b24';if(/rotation|mixed|selective|polarized/.test(v))return'#7654c4';return'#2f6df6';}
function ax(d,grid){return{type:'category',gridIndex:grid||0,data:d,boundaryGap:true,axisLabel:{fontSize:10,color:C.axis,rotate:30},axisLine:{lineStyle:{color:C.line}},splitLine:{show:true,lineStyle:{type:'dashed',color:C.split}}};}
function ya(name,grid,formatter){return{type:'value',gridIndex:grid||0,scale:true,name:name||'',axisLabel:{fontSize:10,color:C.axis,formatter:formatter||null},splitLine:{show:true,lineStyle:{type:'dashed',color:C.split}}};}
function zoom(d,indexes){var target=760;var start=d.length>target?Math.max(0,100-100*target/Math.max(d.length,1)):0;return[{type:'inside',xAxisIndex:indexes||[0],start:start,end:100},{type:'slider',xAxisIndex:indexes||[0],start:start,end:100,height:22,bottom:0}];}
function insideZoom(d,indexes){return[zoom(d,indexes)[0]];}
function mark(values){return{silent:true,symbol:'none',label:{show:false},lineStyle:{type:'dashed',color:'#98a2b3',width:1},data:values.map(function(v){return{yAxis:v};})};}
function line(name,data,color,axis,fmt){return{name:name,type:'line',data:data,symbol:'none',xAxisIndex:axis||0,yAxisIndex:axis||0,lineStyle:{color:color,width:1.8},tooltip:{valueFormatter:fmt}};}
function chart(id,opt,group){var el=document.getElementById(id);if(!el)return null;var c=echarts.init(el,null,{renderer:'canvas'});if(group)c.group=group;c.setOption(opt);return c;}
var forecastKlineChart=null,forecastIndicatorChart=null,indexCompareChart=null,layeredBreadthChart=null,industryKlineChart=null,industryIndicatorChart=null,currentForecastSymbol=null,currentForecastTimeframe='1d',currentForecastIndicator=null,currentIndustrySymbol=null,currentIndustryTimeframe='1d',currentIndustryIndicator='volume',currentIndexCompareWindow=120,currentLayeredBreadthMetric='advance_ratio',currentIndexLiftSymbol=null,liftCharts={};
var forecastStructureSelections={};
var forecastManualDraw={tool:null,pending:null,dragging:false};
var forecastManualLabels={trend:'趋势线',support:'支撑线',resistance:'阻力线'};
var forecastManualColors={trend:'#2563eb',support:'#16a34a',resistance:'#dc2626'};
var indexCompareSeries=[
 {name:'上证指数',key:'sse_index',color:'#172033'},
 {name:'沪深300',key:'hs300_index',color:'#2f6df6'},
 {name:'中证500',key:'csi500_index',color:'#d38b24'},
 {name:'中证1000',key:'csi1000_index',color:'#dc5f7d'},
 {name:'中证2000',key:'csi2000_index',color:'#168457'},
 {name:'创业板指',key:'chinext_index',color:'#7654c4'},
 {name:'科创50',key:'star50_index',color:'#00a0b0'},
 {name:'平均股价',key:'ths_average_price_index',color:'#c94343'}
];
function structureStateKey(){return String(currentForecastSymbol||'')+'|'+currentForecastTimeframe;}
function structureIsInactive(item){var status=item&&item.technicalStructureStatus;return !!status&&status!=='active'&&status!=='role_reversal';}
function structureMatches(item,kind){return kind==='inactive'?structureIsInactive(item):(item&&item.technicalStructureKind===kind);}
function forecastStructureState(d){
 var key=structureStateKey(),state=forecastStructureSelections[key]||(forecastStructureSelections[key]={});
 (d.technicalStructureSeries||[]).forEach(function(item){if(item.name&&state[item.name]===undefined)state[item.name]=!structureIsInactive(item);});
 return state;
}
function forecastIndexName(){var entry=(window._TECHNICAL_INDEX_KLINES||{})[currentForecastSymbol]||{};return entry.name||currentForecastSymbol||'指数';}
function forecastTooltipRow(marker,label,value){return '<div style="display:flex;gap:8px;justify-content:space-between"><span>'+marker+label+'</span><strong>'+value+'</strong></div>';}
function forecastKlineTooltip(params,d){
 var items=params||[],first=items[0]||{},date=first.axisValueLabel||first.axisValue||'',index=Number(first.dataIndex),bars=d.ohlc||[],bar=bars[index]||[],open=Number(bar[0]),close=Number(bar[1]),low=Number(bar[2]),high=Number(bar[3]),previous=index>0?Number((bars[index-1]||[])[1]):NaN;
 var byName={};items.forEach(function(item){if(item&&item.seriesName)byName[item.seriesName]=item;});
 var rows=['<div style="font-weight:700;margin-bottom:6px">'+date+'</div>'];
 [['三市总成交额',compactTushareAmount],['量额比',volumeAmountRatio],['成交额',compactTushareAmount],['成交量',compactNumber]].forEach(function(config){var item=byName[config[0]];if(item&&item.value!=null)rows.push(forecastTooltipRow(item.marker||'',config[0],config[1](item.value)));});
 if(isFinite(close)){
  var change=isFinite(previous)&&previous!==0?(close/previous-1)*100:NaN,changeText=isFinite(change)?forecastIndexName()+(change>=0?'上涨 ':'下跌 ')+Math.abs(change).toFixed(2)+'%':forecastIndexName()+' 收盘 '+close.toFixed(2);
  rows.push('<div style="margin-top:6px;font-weight:700">'+changeText+'</div>');
  rows.push(forecastTooltipRow(byName['K线']&&byName['K线'].marker||'','开 / 收',open.toFixed(2)+' / '+close.toFixed(2)));
  rows.push(forecastTooltipRow('','低 / 高',low.toFixed(2)+' / '+high.toFixed(2)));
 }
 [['MA20',function(v){return Number(v).toFixed(2);} ],['MA60',function(v){return Number(v).toFixed(2);} ],['MA120',function(v){return Number(v).toFixed(2);} ]].forEach(function(config){var item=byName[config[0]],value=Number(item&&item.value);if(item&&isFinite(value))rows.push(forecastTooltipRow(item.marker||'',config[0],config[1](value)));});
 items.forEach(function(item){if(!item||['K线','MA20','MA60','MA120','成交量','成交额','量额比','三市总成交额'].includes(item.seriesName)||item.value==null)return;var value=Array.isArray(item.value)?item.value[item.value.length-1]:item.value;if(value!=null&&isFinite(Number(value)))rows.push(forecastTooltipRow(item.marker||'',item.seriesName,Number(value).toFixed(2)));});
 return rows.join('');
}
function forecastKlineOption(d){
 var dates=d.dates||[];
 var x0=ax(dates,0),x1=ax(dates,1),x2=ax(dates,2),x3=ax(dates,3),x4=ax(dates,4);
 [x0,x1,x2,x3,x4].forEach(function(axis){axis.axisPointer={show:true,type:'line',snap:true,lineStyle:{type:'dashed',color:'#98a2b3',width:1}};});
 x0.axisLabel={show:false};x1.axisLabel={show:false};x2.axisLabel={show:false};x3.axisLabel={show:false};
 var volumeColor=function(p){var bar=(d.ohlc||[])[p.dataIndex]||[];return Number(bar[1])>=Number(bar[0])?C.up:C.down;};
 var ratioData=(d.volume||[]).map(function(v,i){var vol=Number(v),amount=Number((d.amount||[])[i]);return isFinite(vol)&&isFinite(amount)&&amount>0?Number((vol/amount).toFixed(6)):null;});
 var marketAmount=marketAmountForDates(dates);
 var series=[
  {name:'K线',type:'candlestick',data:d.ohlc,itemStyle:{color:C.up,color0:C.down,borderColor:C.up,borderColor0:C.down},barMaxWidth:'60%',barMinWidth:2},
  {name:'MA20',type:'line',data:d.ma20,symbol:'none',lineStyle:{color:C.blue,width:1.5}},
  {name:'MA60',type:'line',data:d.ma60,symbol:'none',lineStyle:{color:C.orange,width:1.5}},
  {name:'MA120',type:'line',data:d.ma120,symbol:'none',lineStyle:{color:C.pink,width:1.5}},
  {name:'成交量',type:'bar',xAxisIndex:1,yAxisIndex:1,data:d.volume||[],tooltip:{valueFormatter:compactNumber},itemStyle:{color:volumeColor,opacity:.58},barMaxWidth:'55%'},
  {name:'成交额',type:'bar',xAxisIndex:2,yAxisIndex:2,data:d.amount||[],tooltip:{valueFormatter:compactTushareAmount},itemStyle:{color:volumeColor,opacity:.58},barMaxWidth:'55%'},
  {name:'量额比',type:'bar',xAxisIndex:3,yAxisIndex:3,data:ratioData,tooltip:{valueFormatter:volumeAmountRatio},itemStyle:{color:'#7654c4',opacity:.62},barMaxWidth:'55%'},
  {name:'三市总成交额',type:'bar',xAxisIndex:4,yAxisIndex:4,data:marketAmount,tooltip:{valueFormatter:compactTushareAmount},itemStyle:{color:'#8aa3c7',opacity:.72},barMaxWidth:'55%'}
 ];
 return{animation:false,tooltip:{trigger:'axis',axisPointer:{type:'cross'},formatter:function(params){return forecastKlineTooltip(params,d);}},axisPointer:{link:[{xAxisIndex:[0,1,2,3,4]}]},legend:{type:'scroll',top:12,left:24,right:24,data:['K线','MA20','MA60','MA120','成交量','成交额','量额比','三市总成交额']},grid:[{left:56,right:42,top:52,height:'47%'},{left:56,right:42,top:'61%',height:'7%'},{left:56,right:42,top:'70%',height:'7%'},{left:56,right:42,top:'79%',height:'7%'},{left:56,right:42,top:'88%',height:'7%'}],xAxis:[x0,x1,x2,x3,x4],yAxis:[ya('指数',0),ya('成交量',1,compactNumber),ya('成交额',2,compactTushareAmount),ya('量额比',3,volumeAmountRatio),ya('三市总额',4,compactTushareAmount)],dataZoom:zoom(dates,[0,1,2,3,4]),series:series};
}
function marketAmountForDates(targetDates){
 var m=window._MARKET_STRUCTURE||{},srcDates=m.market_amount_dates||m.dates||[],srcValues=m.market_total_amount||m.total_amount||[],byDate={};
 srcDates.forEach(function(date,i){var key=String(date||'').replace(/-/g,''),value=Number(srcValues[i]);if(key&&isFinite(value))byDate[key]=value;});
 if(currentForecastTimeframe==='1d')return(targetDates||[]).map(function(date){var value=byDate[String(date||'').replace(/-/g,'')];return value==null?null:value;});
 var source=srcDates.map(function(date,i){return{time:Date.parse(date),value:Number(srcValues[i])};}).filter(function(row){return isFinite(row.time)&&isFinite(row.value);}).sort(function(a,b){return a.time-b.time;});
 var cursor=0,previous=-Infinity;
 return(targetDates||[]).map(function(date){var end=Date.parse(date),sum=0,seen=false;if(!isFinite(end)){return null;}while(cursor<source.length&&source[cursor].time<=end){if(source[cursor].time>previous){sum+=source[cursor].value;seen=true;}cursor++;}previous=end;return seen?Number(sum.toFixed(2)):null;});
}
function forecastManualStorageKey(chart){return'quantyb.'+(chart._manualScope||'index')+'-manual-draw.v1.'+(chart._manualSymbol||'')+'.'+(chart._manualPeriod||'');}
function loadForecastManualLines(chart){if(chart._manualLines)return chart._manualLines;try{chart._manualLines=JSON.parse(localStorage.getItem(forecastManualStorageKey(chart))||'[]')||[];}catch(e){chart._manualLines=[];}return chart._manualLines;}
function saveForecastManualLines(chart){try{localStorage.setItem(forecastManualStorageKey(chart),JSON.stringify(chart._manualLines||[]));}catch(e){}}
function forecastManualStatus(text){var el=document.getElementById('forecast-manual-status');if(el)el.textContent=text||'选择工具后在 K 线图点击画线；拖动圆点可微调。';}
function setForecastManualTool(tool){
 forecastManualDraw.tool=tool||null;forecastManualDraw.pending=null;
 document.querySelectorAll('.forecast-manual-btn[data-tool]').forEach(function(btn){btn.classList.toggle('active',btn.getAttribute('data-tool')===forecastManualDraw.tool);});
 if(!forecastManualDraw.tool)forecastManualStatus('选择/调整：可拖动画线圆点；滚轮可缩放图表。');
 else if(forecastManualDraw.tool==='trend')forecastManualStatus('趋势线：请在 K 线图上依次点击两个点。');
 else forecastManualStatus(forecastManualLabels[forecastManualDraw.tool]+'：请在 K 线图上点击一个价位。');
}
function forecastManualPointFromPixel(chart,p){
 var coord=chart.convertFromPixel({gridIndex:0},p);if(!coord||coord.length<2)return null;
 var rawX=coord[0],idx,dates=chart._manualDates||[];
 if(typeof rawX==='number')idx=Math.round(rawX);else idx=dates.indexOf(String(rawX));
 if(idx<0)idx=0;if(idx>=dates.length)idx=dates.length-1;
 var price=Number(coord[1]);if(!isFinite(price)||!dates.length)return null;
 return{index:idx,date:dates[idx],price:Number(price.toFixed(3))};
}
function forecastManualPointFromEvent(chart,ev){return forecastManualPointFromPixel(chart,[ev.offsetX,ev.offsetY]);}
function forecastManualPixelFromPoint(chart,point){
 if(!chart||!point||point.date==null||point.price==null)return null;
 var pixel=chart.convertToPixel({gridIndex:0},[point.date,Number(point.price)]);
 if(!pixel||pixel.length<2||!isFinite(pixel[0])||!isFinite(pixel[1]))return null;
 return[Number(pixel[0]),Number(pixel[1])];
}
function forecastManualRightEdgeDate(chart){
 var dates=chart._manualDates||[];if(!dates.length)return'';
 try{var opt=chart.getOption()||{},dz=(opt.dataZoom||[])[0]||{},idx=dates.length-1;
  if(dz.endValue!=null){if(typeof dz.endValue==='number')idx=Math.round(dz.endValue);else{var found=dates.indexOf(String(dz.endValue));if(found>=0)idx=found;}}
  else if(dz.end!=null){idx=Math.round((Number(dz.end)||100)/100*(dates.length-1));}
  if(idx<0)idx=0;if(idx>=dates.length)idx=dates.length-1;return dates[idx];
 }catch(e){return dates[dates.length-1];}
}
function forecastManualSeries(lineObj,chart){
 var dates=chart._manualDates||[],color=forecastManualColors[lineObj.type]||'#2563eb',label=forecastManualLabels[lineObj.type]||'手动画线',data=[];
 if(lineObj.type==='trend'){
  var p1=lineObj.p1||{},p2=lineObj.p2||{},i1=Number(p1.index),i2=Number(p2.index),y1=Number(p1.price),y2=Number(p2.price);
  if(!isFinite(i1)||!isFinite(i2)||!isFinite(y1)||!isFinite(y2)||i1===i2){data=[[p1.date,y1],[p2.date,y2]];}
  else{var slope=(y2-y1)/(i2-i1),startIndex=Math.min(i1,i2);data=dates.map(function(date,idx){return idx<startIndex?[date,null]:[date,Number((y1+slope*(idx-i1)).toFixed(3))];});}
  return{id:'manual-'+lineObj.id,name:label,type:'line',data:data,manualDrawLine:true,symbol:'circle',symbolSize:6,z:40,silent:false,clip:false,lineStyle:{color:color,width:2.2,type:'solid',opacity:.98},endLabel:{show:true,formatter:function(p){var v=p&&p.value?p.value[1]:null;return label+(v==null?'':' '+Number(v).toFixed(2));},color:color,fontSize:11,fontWeight:'bold'},tooltip:{formatter:function(){return label+'<br/>'+p1.date+' '+p1.price+' → '+p2.date+' '+p2.price+'<br/>已延伸到右侧最新日期';}}};
 }
 data=dates.map(function(date){return[date,Number(lineObj.price)];});
 var lineType=lineObj.type==='support'?'dashed':(lineObj.type==='resistance'?'dashed':'solid');
 return{id:'manual-'+lineObj.id,name:label,type:'line',data:data,manualDrawLine:true,symbol:'none',z:38,silent:false,clip:false,lineStyle:{color:color,width:2.4,type:lineType,opacity:.98},endLabel:{show:true,formatter:function(){return label+' '+Number(lineObj.price).toFixed(2);},color:color,fontSize:11,fontWeight:'bold',distance:8},markLine:{silent:false,symbol:'none',precision:3,label:{show:false},lineStyle:{color:color,width:2.4,type:lineType,opacity:.98},data:[{yAxis:Number(lineObj.price)}]},tooltip:{formatter:function(){return label+'<br/>价位: '+Number(lineObj.price).toFixed(3);}}};
}
function forecastManualSeriesList(chart){return loadForecastManualLines(chart).map(function(lineObj){return forecastManualSeries(lineObj,chart);});}
function renderForecastManualSeriesOnly(chart){if(!chart||!chart._manualBaseSeries)return;chart.setOption({series:(chart._manualBaseSeries||[]).concat(forecastManualSeriesList(chart))},{replaceMerge:['series']});}
function updateForecastManualTrendPoint(chart,lineId,which,pixel){
 var point=forecastManualPointFromPixel(chart,pixel);if(!point)return false;
 var lines=loadForecastManualLines(chart),changed=false;lines.forEach(function(lineObj){if(lineObj.id===lineId&&lineObj.type==='trend'){lineObj[which]=point;changed=true;}});
 if(changed){chart._manualLines=lines;saveForecastManualLines(chart);renderForecastManualSeriesOnly(chart);}return changed;
}
function updateForecastManualHorizontalPrice(chart,lineId,pixel){
 var coord=chart.convertFromPixel({gridIndex:0},pixel);if(!coord||coord.length<2||!isFinite(Number(coord[1])))return false;
 var price=Number(Number(coord[1]).toFixed(3)),lines=loadForecastManualLines(chart),changed=false;
 lines.forEach(function(lineObj){if(lineObj.id===lineId&&(lineObj.type==='support'||lineObj.type==='resistance')){lineObj.price=price;changed=true;}});
 if(changed){chart._manualLines=lines;saveForecastManualLines(chart);renderForecastManualSeriesOnly(chart);}return changed;
}
function forecastManualHandleStyle(color){return{fill:color,stroke:'#fff',lineWidth:2,shadowBlur:8,shadowColor:'rgba(15,23,42,.18)'};}
function forecastManualHandle(chart,lineObj,which,point,label,color){
 var pos=forecastManualPixelFromPoint(chart,point);if(!pos)return null;
 return{id:'manual-handle-'+lineObj.id+'-'+which,type:'circle',position:pos,shape:{r:7},draggable:true,cursor:'move',z:120,style:forecastManualHandleStyle(color),tooltip:{show:true,formatter:label+'：拖动调整位置'},ondragstart:function(){forecastManualDraw.dragging=true;},ondrag:function(){updateForecastManualTrendPoint(chart,lineObj.id,which,this.position);},ondragend:function(){updateForecastManualTrendPoint(chart,lineObj.id,which,this.position);renderForecastManualLines(chart);setTimeout(function(){forecastManualDraw.dragging=false;},0);},onclick:function(){forecastManualDraw.dragging=true;setTimeout(function(){forecastManualDraw.dragging=false;},0);}};
}
function forecastManualHorizontalHandle(chart,lineObj,label,color){
 var pos=forecastManualPixelFromPoint(chart,{date:forecastManualRightEdgeDate(chart),price:lineObj.price});if(!pos)return null;
 return{id:'manual-handle-'+lineObj.id+'-price',type:'circle',position:pos,shape:{r:7},draggable:true,cursor:'ns-resize',z:120,style:forecastManualHandleStyle(color),tooltip:{show:true,formatter:label+'：上下拖动调整价位'},ondragstart:function(){forecastManualDraw.dragging=true;},ondrag:function(){updateForecastManualHorizontalPrice(chart,lineObj.id,this.position);},ondragend:function(){updateForecastManualHorizontalPrice(chart,lineObj.id,this.position);renderForecastManualLines(chart);setTimeout(function(){forecastManualDraw.dragging=false;},0);},onclick:function(){forecastManualDraw.dragging=true;setTimeout(function(){forecastManualDraw.dragging=false;},0);}};
}
function forecastManualGraphics(chart){
 var graphics=[];loadForecastManualLines(chart).forEach(function(lineObj){var color=forecastManualColors[lineObj.type]||'#2563eb',label=forecastManualLabels[lineObj.type]||'手动画线';
  if(lineObj.type==='trend'){var p1=forecastManualHandle(chart,lineObj,'p1',lineObj.p1,label+'起点',color),p2=forecastManualHandle(chart,lineObj,'p2',lineObj.p2,label+'终点',color);if(p1)graphics.push(p1);if(p2)graphics.push(p2);}
  else if(lineObj.type==='support'||lineObj.type==='resistance'){var h=forecastManualHorizontalHandle(chart,lineObj,label,color);if(h)graphics.push(h);}
 });
 return graphics;
}
function renderForecastManualLines(chart){if(!chart||!chart._manualBaseSeries)return;chart.setOption({series:(chart._manualBaseSeries||[]).concat(forecastManualSeriesList(chart)),graphic:forecastManualGraphics(chart)},{replaceMerge:['series','graphic']});}
function addForecastManualLine(chart,lineObj){var lines=loadForecastManualLines(chart);lines.push(lineObj);chart._manualLines=lines;saveForecastManualLines(chart);renderForecastManualLines(chart);}
function bindForecastManualDrawing(chart,d,scope,period){
 if(!chart||!d)return;
 chart._manualScope=scope||'index';
 chart._manualSymbol=d.symbol||(chart._manualScope==='industry'?currentIndustrySymbol:currentForecastSymbol)||'';
 chart._manualPeriod=period||(chart._manualScope==='industry'?'1d':currentForecastTimeframe);chart._manualDates=d.dates||[];
 chart._manualBaseSeries=(chart.getOption().series||[]).filter(function(item){return !item.manualDrawLine;}).map(function(item){return item;});
 chart._manualLines=null;renderForecastManualLines(chart);
 if(!chart._forecastManualBound){
  chart._forecastManualBound=true;
  chart.on('dataZoom',function(){setTimeout(function(){renderForecastManualLines(chart);},0);});
  chart.getZr().on('click',function(ev){
   if(!forecastManualDraw.tool||forecastManualDraw.dragging)return;
   var point=forecastManualPointFromEvent(chart,ev);if(!point)return;
   var id=Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,7);
   if(forecastManualDraw.tool==='trend'){
    if(!forecastManualDraw.pending){forecastManualDraw.pending=point;forecastManualStatus('趋势线：已选择第一个点 '+point.date+' / '+point.price+'，请点击第二个点。');return;}
    addForecastManualLine(chart,{id:id,type:'trend',p1:forecastManualDraw.pending,p2:point});forecastManualDraw.pending=null;forecastManualStatus('趋势线已添加。拖动两个圆点可调整两端。');
   }else if(forecastManualDraw.tool==='support'||forecastManualDraw.tool==='resistance'){
    addForecastManualLine(chart,{id:id,type:forecastManualDraw.tool,price:point.price,date:point.date});forecastManualStatus(forecastManualLabels[forecastManualDraw.tool]+'已添加：'+point.price+'。拖动右侧圆点可上下调整。');
   }
  });
 }
}
function forecastManualTargetChart(){return forecastKlineChart||industryKlineChart;}
function forecastManualUndo(){var target=forecastManualTargetChart();if(!target)return;var lines=loadForecastManualLines(target);lines.pop();target._manualLines=lines;saveForecastManualLines(target);renderForecastManualLines(target);forecastManualStatus('已撤销当前标的/周期最后一条手动画线。');}
function forecastManualClear(){var target=forecastManualTargetChart();if(!target)return;if(!confirm('清空当前标的/周期的全部手动画线？'))return;target._manualLines=[];saveForecastManualLines(target);renderForecastManualLines(target);forecastManualStatus('当前标的/周期手动画线已清空。');}
window.setForecastManualTool=setForecastManualTool;
window.forecastManualUndo=forecastManualUndo;
window.forecastManualClear=forecastManualClear;
function forecastVolumeOption(d){
 return{tooltip:{trigger:'axis',axisPointer:{type:'shadow'}},legend:{top:6,data:['成交量','成交量MA5','成交量MA20']},grid:{left:68,right:36,top:42,bottom:40},xAxis:ax(d.dates),yAxis:ya('成交量',0,compactNumber),dataZoom:insideZoom(d.dates),series:[{name:'成交量',type:'bar',data:d.volume||[],tooltip:{valueFormatter:compactNumber},itemStyle:{color:function(p){var bar=(d.ohlc||[])[p.dataIndex]||[];return Number(bar[1])>=Number(bar[0])?C.up:C.down;},opacity:.55}},line('成交量MA5',d.volume_ma5||[],C.blue,0,compactNumber),line('成交量MA20',d.volume_ma20||[],C.orange,0,compactNumber)]};
}
function forecastKdjOption(d){
 var k=line('K',d.kdj_k||[],C.blue,0,function(v){return Number(v).toFixed(1);});k.markLine=mark([20,80]);
 var yKdj=ya('KDJ',0);yKdj.min=function(v){return Math.min(-20,Math.floor(v.min/10)*10);};yKdj.max=function(v){return Math.max(120,Math.ceil(v.max/10)*10);};
 return{tooltip:{trigger:'axis',axisPointer:{type:'cross'}},legend:{top:6,data:['K','D','J']},grid:{left:56,right:36,top:42,bottom:40},xAxis:ax(d.dates),yAxis:yKdj,dataZoom:insideZoom(d.dates),series:[k,line('D',d.kdj_d||[],C.orange),line('J',d.kdj_j||[],C.pink)]};
}
function forecastMacdOption(d){
 var dif=line('DIF',d.macd_dif||[],C.blue,0,function(v){return Number(v).toFixed(2);});dif.markLine=mark([0]);
 return{tooltip:{trigger:'axis',axisPointer:{type:'cross'}},legend:{top:6,data:['DIF','DEA','MACD柱']},grid:{left:56,right:36,top:42,bottom:40},xAxis:ax(d.dates),yAxis:ya('MACD'),dataZoom:insideZoom(d.dates),series:[dif,line('DEA',d.macd_dea||[],C.orange,0,function(v){return Number(v).toFixed(2);}),{name:'MACD柱',type:'bar',data:d.macd_hist||[],itemStyle:{color:function(p){return p.value>=0?C.up:C.down;},opacity:.55}}]};
}
function plainKlineOption(d,title){
 return{tooltip:{trigger:'axis',axisPointer:{type:'cross'}},legend:{type:'scroll',top:12,left:24,right:24,data:['K线','MA20','MA60','MA120']},grid:{left:56,right:36,top:50,bottom:58},xAxis:ax(d.dates),yAxis:ya(title||'指数'),dataZoom:zoom(d.dates),series:[{name:'K线',type:'candlestick',data:d.ohlc,itemStyle:{color:C.up,color0:C.down,borderColor:C.up,borderColor0:C.down}},{name:'MA20',type:'line',data:d.ma20,symbol:'none',lineStyle:{color:C.blue,width:1.5}},{name:'MA60',type:'line',data:d.ma60,symbol:'none',lineStyle:{color:C.orange,width:1.5}},{name:'MA120',type:'line',data:d.ma120,symbol:'none',lineStyle:{color:C.pink,width:1.5}}]};
}
function technicalTimeframes(symbol){var root=window._TECHNICAL_INDEX_KLINES||{},entry=root[symbol]||{};return entry.timeframes||window._TECHNICAL_KLINES||{};}
function currentForecastData(){var all=technicalTimeframes(currentForecastSymbol),d=all[currentForecastTimeframe];if((!d||!d.dates||!d.dates.length)&&currentForecastTimeframe!=='1d'){currentForecastTimeframe='1d';d=all['1d'];}return d;}
function industryTimeframes(symbol){var root=window._INDUSTRY_KLINES||{},entry=root[symbol]||{};return entry.timeframes||{};}
function currentIndustryData(){var all=industryTimeframes(currentIndustrySymbol),d=all[currentIndustryTimeframe];if((!d||!d.dates||!d.dates.length)&&currentIndustryTimeframe!=='1d'){currentIndustryTimeframe='1d';d=all['1d'];}return d&&d.dates&&d.dates.length?d:null;}
function applyForecastStructureSelection(d){if(!forecastKlineChart)return;var state=forecastStructureState(d);(d.technicalStructureSeries||[]).forEach(function(item){if(item.name)forecastKlineChart.dispatchAction({type:state[item.name]===false?'legendUnSelect':'legendSelect',name:item.name});});}
function updateForecastStructureCounts(d){var state=forecastStructureState(d);document.querySelectorAll('.structure-filter').forEach(function(filter){var kind=filter.getAttribute('data-kind'),items=(d.technicalStructureSeries||[]).filter(function(item){return item.name&&structureMatches(item,kind);}),checked=items.filter(function(item){return state[item.name]!==false;}).length,count=filter.querySelector('.structure-filter-count');if(count)count.textContent=checked+'/'+items.length;});}
function renderForecastStructureFilters(d){
 var state=forecastStructureState(d);
 document.querySelectorAll('.structure-filter').forEach(function(filter){
  var kind=filter.getAttribute('data-kind'),list=filter.querySelector('.structure-filter-list'),items=(d.technicalStructureSeries||[]).filter(function(item){return item.name&&structureMatches(item,kind);});
  if(!list)return;list.textContent='';
  if(!items.length){var empty=document.createElement('div');empty.className='structure-filter-empty';empty.textContent='当前指数/周期没有此类结构线';list.appendChild(empty);}
  items.forEach(function(item){var label=document.createElement('label'),input=document.createElement('input'),text=document.createElement('span');input.type='checkbox';input.checked=state[item.name]!==false;input.setAttribute('data-series-name',item.name);input.onchange=function(){window.toggleForecastStructureSeries(input);};text.textContent=item.name;label.title=item.name;label.appendChild(input);label.appendChild(text);list.appendChild(label);});
 });
 updateForecastStructureCounts(d);
}
function renderForecastIndicator(d){
 var el=document.getElementById('forecast-index-indicator');
 document.querySelectorAll('.indicator-switch-btn').forEach(function(button){button.classList.toggle('active',button.getAttribute('data-indicator')===currentForecastIndicator);});
 if(!el)return;
 if(!currentForecastIndicator){el.style.display='none';return;}
 el.style.display='block';
 var option=currentForecastIndicator==='kdj'?forecastKdjOption(d):forecastMacdOption(d);
 if(!forecastIndicatorChart){forecastIndicatorChart=chart('forecast-index-indicator',option,'forecast-index-sync');}
 else forecastIndicatorChart.setOption(option,true);
}
function renderIndustryIndicator(d){if(!industryIndicatorChart)return;var option=currentIndustryIndicator==='kdj'?forecastKdjOption(d):(currentIndustryIndicator==='macd'?forecastMacdOption(d):forecastVolumeOption(d));industryIndicatorChart.setOption(option,true);document.querySelectorAll('.industry-indicator-switch').forEach(function(button){button.classList.toggle('active',button.getAttribute('data-indicator')===currentIndustryIndicator);});}
function normalizedCompareValues(values,start){var sliced=(values||[]).slice(start),base=null;for(var i=0;i<sliced.length;i++){var value=sliced[i],n=Number(value);if(value!==null&&value!==undefined&&value!==''&&isFinite(n)&&n!==0){base=n;break;}}return sliced.map(function(value){var n=Number(value),valid=value!==null&&value!==undefined&&value!==''&&isFinite(n);return base!==null&&valid?Number((n/base*100).toFixed(4)):null;});}
function indexCompareData(m){var dates=m.index_dates||[],start=Math.max(0,dates.length-currentIndexCompareWindow),series=indexCompareSeries.map(function(config){return{name:config.name,key:config.key,color:config.color,data:normalizedCompareValues(m[config.key],start)};}).filter(function(item){return item.data.some(function(value){return value!==null;});});return{dates:dates.slice(start),series:series};}
function indexCompareOption(m){
 var payload=indexCompareData(m),series=payload.series.map(function(item,index){var result={name:item.name,type:'line',data:item.data,symbol:'none',connectNulls:false,lineStyle:{color:item.color,width:item.name==='平均股价'?2.6:2},endLabel:{show:true,color:item.color,formatter:function(p){var v=Number(p.value);return item.name+' '+(v>=100?'+':'')+(v-100).toFixed(1)+'%';}},labelLayout:{moveOverlap:'shiftY'},emphasis:{focus:'series'},tooltip:{valueFormatter:function(v){var n=Number(v);return(n>=100?'+':'')+(n-100).toFixed(2)+'%';}}};if(index===0)result.markLine=mark([100]);return result;});
 return{animation:false,tooltip:{trigger:'axis',axisPointer:{type:'cross'}},legend:{type:'scroll',top:8,left:36,right:36,data:payload.series.map(function(item){return item.name;})},grid:{left:56,right:160,top:52,bottom:42},xAxis:ax(payload.dates),yAxis:ya('区间起点=100'),series:series};
}
function renderIndexStrengthRanking(m){var root=document.getElementById('structure-index-ranking');if(!root)return;var payload=indexCompareData(m),items=payload.series.map(function(item){for(var i=item.data.length-1;i>=0;i--){if(item.data[i]!==null)return{name:item.name,value:item.data[i]-100};}return null;}).filter(Boolean).sort(function(a,b){return b.value-a.value;});root.textContent='';var title=document.createElement('strong');title.textContent=currentIndexCompareWindow+'日区间涨跌排名';root.appendChild(title);items.forEach(function(item,index){var span=document.createElement('span');span.className='index-strength-item '+(item.value>=0?'up':'down');span.textContent=(index+1)+'. '+item.name+' '+(item.value>=0?'+':'')+item.value.toFixed(2)+'%';root.appendChild(span);});}
function renderIndexComparison(m){if(!indexCompareChart)return;indexCompareChart.setOption(indexCompareOption(m),true);renderIndexStrengthRanking(m);document.querySelectorAll('.index-compare-window').forEach(function(button){button.classList.toggle('active',Number(button.getAttribute('data-window'))===currentIndexCompareWindow);});}
var layeredBreadthMetrics={advance_ratio:'上涨比例',pct_above_ma5:'MA5上方',pct_above_ma10:'MA10上方',pct_above_ma20:'MA20上方',pct_above_ma60:'MA60上方',new_high_5_ratio:'5日新高',new_low_5_ratio:'5日新低',new_high_10_ratio:'10日新高',new_low_10_ratio:'10日新低',new_high_20_ratio:'20日新高',new_low_20_ratio:'20日新低',new_high_60_ratio:'60日新高',new_low_60_ratio:'60日新低'};
function layeredBreadthOption(m,metric){var label=layeredBreadthMetrics[metric]||metric,layerColors=['#172033','#2f6df6','#d38b24','#dc5f7d','#168457','#7654c4','#00a0b0','#c94343'];var series=(m.layered_breadth_series||[]).map(function(item,index){var s=line(item.name,item[metric],layerColors[index%layerColors.length],0,pct);s.emphasis={focus:'series'};return s;});if(series[0]&&(metric==='advance_ratio'||metric.indexOf('pct_above_ma')===0))series[0].markLine=mark([.5]);return{animation:false,tooltip:{trigger:'axis',axisPointer:{type:'cross'}},legend:{type:'scroll',top:8,left:36,right:36},grid:{left:56,right:42,top:50,bottom:58},xAxis:ax(m.layered_breadth_dates),yAxis:{type:'value',min:0,max:1,name:label,axisLabel:{formatter:function(v){return(v*100).toFixed(0)+'%';}},splitLine:{show:true,lineStyle:{type:'dashed',color:C.split}}},dataZoom:zoom(m.layered_breadth_dates),series:series};}
function renderLayeredBreadth(m){if(!layeredBreadthChart)return;layeredBreadthChart.setOption(layeredBreadthOption(m,currentLayeredBreadthMetric),true);document.querySelectorAll('.layered-breadth-switch').forEach(function(button){button.classList.toggle('active',button.getAttribute('data-metric')===currentLayeredBreadthMetric);});}
function liftEntry(symbol){var root=window._INDEX_LIFT_STRUCTURE||{},by=root.by_symbol||{};return by[symbol]||null;}
function liftReturnsOption(item){var dates=item.dates||[];return{animation:false,tooltip:{trigger:'axis',axisPointer:{type:'cross'}},legend:{type:'scroll',top:8,left:20,right:20,data:['指数收益','等权收益','成交加权收益','指数-等权差','指数-成交加权差']},grid:[{left:56,right:42,top:50,height:'30%'},{left:56,right:42,top:'57%',height:'27%'}],xAxis:[ax(dates,0),ax(dates,1)],yAxis:[ya('收益',0,function(v){return(v*100).toFixed(1)+'%';}),ya('差值',1,function(v){return(v*100).toFixed(1)+'%';})],dataZoom:zoom(dates,[0,1]),series:[line('指数收益',item.index_return||[],C.ink,0,signedPct),line('等权收益',item.equal_weight_return||[],C.blue,0,signedPct),line('成交加权收益',item.amount_weighted_return||[],C.orange,0,signedPct),line('指数-等权差',item.index_equal_weight_gap||[],C.purple,1,signedPct),line('指数-成交加权差',item.index_amount_weighted_gap||[],C.pink,1,signedPct)]};}
function liftScoresOption(item){var dates=item.dates||[];return{animation:false,tooltip:{trigger:'axis',axisPointer:{type:'cross'}},legend:{type:'scroll',top:8,left:20,right:20,data:['质量分','掩护风险','前10正贡献','前10贡献成交','下跌成交','前20%成交股收益']},grid:[{left:56,right:42,top:50,height:'30%'},{left:56,right:42,top:'57%',height:'27%'}],xAxis:[ax(dates,0),ax(dates,1)],yAxis:[ya('分数',0),ya('比例/收益',1,function(v){return(v*100).toFixed(0)+'%';})],dataZoom:zoom(dates,[0,1]),series:[line('质量分',item.index_lift_quality||[],C.blue,0,function(v){return v==null?'--':Number(v).toFixed(1);}),line('掩护风险',item.index_masking_risk||[],C.pink,0,function(v){return v==null?'--':Number(v).toFixed(1);}),line('前10正贡献',item.top_10_positive_contribution_share||[],C.ink,1,pct),line('前10贡献成交',item.top10_contributor_amount_share||[],C.orange,1,pct),line('下跌成交',item.down_amount_share||[],C.down,1,pct),line('前20%成交股收益',item.top_turnover_20pct_return||[],C.purple,1,signedPct)]};}
function renderIndexLift(symbol){var root=window._INDEX_LIFT_STRUCTURE||{},by=root.by_symbol||{};currentIndexLiftSymbol=String(symbol||currentIndexLiftSymbol||root.primary_symbol||Object.keys(by)[0]||'').toUpperCase();document.querySelectorAll('.lift-symbol-btn').forEach(function(button){button.classList.toggle('active',String(button.getAttribute('data-symbol')||'').toUpperCase()===currentIndexLiftSymbol);});document.querySelectorAll('.lift-symbol-panel').forEach(function(panel){panel.classList.toggle('active',String(panel.getAttribute('data-lift-symbol')||'').toUpperCase()===currentIndexLiftSymbol);});var item=liftEntry(currentIndexLiftSymbol);if(!item||!item.dates||!item.dates.length)return;var retId='index-lift-returns-'+currentIndexLiftSymbol,scoreId='index-lift-scores-'+currentIndexLiftSymbol;if(!liftCharts[retId])liftCharts[retId]=chart(retId,liftReturnsOption(item));else liftCharts[retId].setOption(liftReturnsOption(item),true);if(!liftCharts[scoreId])liftCharts[scoreId]=chart(scoreId,liftScoresOption(item));else liftCharts[scoreId].setOption(liftScoresOption(item),true);}
function renderForecastKline(){var d=currentForecastData();if(!d||!d.dates||!d.dates.length)return;if(forecastKlineChart){forecastKlineChart.setOption(forecastKlineOption(d),true);bindForecastManualDrawing(forecastKlineChart,d,'index',currentForecastTimeframe);}renderForecastIndicator(d);document.querySelectorAll('.kline-period-btn').forEach(function(item){item.classList.toggle('active',item.getAttribute('data-timeframe')===currentForecastTimeframe);});}
function renderIndustryKline(){var d=currentIndustryData(),root=window._INDUSTRY_KLINES||{},entry=root[currentIndustrySymbol]||{},title=document.getElementById('industry-kline-title'),periodLabel={'1d':'日K','1w':'周K','1mo':'月K'}[currentIndustryTimeframe]||'日K';if(!d)return;if(industryKlineChart){industryKlineChart.setOption(plainKlineOption(d,entry.name||'行业'),true);bindForecastManualDrawing(industryKlineChart,d,'industry',currentIndustryTimeframe);}renderIndustryIndicator(d);if(title)title.textContent=(entry.name||currentIndustrySymbol)+'（'+currentIndustrySymbol+'） · '+periodLabel;document.querySelectorAll('.industry-period-btn').forEach(function(item){item.classList.toggle('active',item.getAttribute('data-timeframe')===currentIndustryTimeframe);});document.querySelectorAll('.industry-row-clickable').forEach(function(row){row.classList.toggle('active',row.getAttribute('data-industry-symbol')===currentIndustrySymbol);});}
window.switchForecastKline=function(timeframe,button){currentForecastTimeframe=timeframe;forecastManualDraw.pending=null;renderForecastKline();};
window.switchForecastIndex=function(symbol){currentForecastSymbol=String(symbol||'').toUpperCase();forecastManualDraw.pending=null;renderForecastKline();};
window.switchForecastIndicator=function(indicator){currentForecastIndicator=(currentForecastIndicator===indicator?null:indicator);var d=currentForecastData();if(d)renderForecastIndicator(d);};
window.switchIndustryKline=function(symbol){currentIndustrySymbol=String(symbol||'').toUpperCase();renderIndustryKline();};
window.switchIndustryTimeframe=function(timeframe){currentIndustryTimeframe=timeframe||'1d';forecastManualDraw.pending=null;renderIndustryKline();};
window.switchIndustryIndicator=function(indicator){currentIndustryIndicator=indicator;var d=currentIndustryData();if(d)renderIndustryIndicator(d);};
window.switchIndexCompareWindow=function(windowSize){currentIndexCompareWindow=Number(windowSize)||120;renderIndexComparison(window._MARKET_STRUCTURE||{});};
window.switchLayeredBreadthMetric=function(metric){if(!layeredBreadthMetrics[metric])return;currentLayeredBreadthMetric=metric;renderLayeredBreadth(window._MARKET_STRUCTURE||{});};
window.switchIndexLiftSymbol=function(symbol){renderIndexLift(symbol);};
window.toggleForecastStructureSeries=function(input){var d=currentForecastData();if(!d||!input)return;var name=input.getAttribute('data-series-name'),checked=!!input.checked;forecastStructureState(d)[name]=checked;if(forecastKlineChart)forecastKlineChart.dispatchAction({type:checked?'legendSelect':'legendUnSelect',name:name});document.querySelectorAll('.structure-filter-list input[data-series-name]').forEach(function(other){if(other.getAttribute('data-series-name')===name)other.checked=checked;});updateForecastStructureCounts(d);};
window.setForecastStructureGroup=function(kind,checked){var d=currentForecastData();if(!d)return;var state=forecastStructureState(d);(d.technicalStructureSeries||[]).forEach(function(item){if(item.name&&structureMatches(item,kind)){state[item.name]=checked;if(forecastKlineChart)forecastKlineChart.dispatchAction({type:checked?'legendSelect':'legendUnSelect',name:item.name});}});renderForecastStructureFilters(d);};
function init(){
 var d=window._FORECAST_CHART||{},m=window._MARKET_STRUCTURE||{},root=window._TECHNICAL_INDEX_KLINES||{},charts=[];
 renderIndexLift();
 currentForecastSymbol=String(window._PRIMARY_TECHNICAL_INDEX||Object.keys(root)[0]||'').toUpperCase();
 var tk=technicalTimeframes(currentForecastSymbol);
 if(d.dates&&d.dates.length){
  var initial=tk['1d']&&tk['1d'].dates&&tk['1d'].dates.length?tk['1d']:d;forecastKlineChart=chart('forecast-kline',forecastKlineOption(initial),'forecast-index-sync');charts.push(forecastKlineChart);
  bindForecastManualDrawing(forecastKlineChart,initial);renderForecastIndicator(initial);
 }
 if(m.index_dates&&m.index_dates.length){
  indexCompareChart=chart('structure-index-compare',indexCompareOption(m));charts.push(indexCompareChart);renderIndexStrengthRanking(m);
  var relative=line('沪深300/平均股价',m.hs300_vs_all_a,C.blue);relative.markLine=mark([100]);
  charts.push(chart('structure-relative',{tooltip:{trigger:'axis'},grid:{left:56,right:36,top:36,bottom:58},xAxis:ax(m.index_dates),yAxis:ya('相对强弱'),dataZoom:zoom(m.index_dates),series:[relative]}));
 }
 if(m.layered_breadth_dates&&m.layered_breadth_dates.length){
  layeredBreadthChart=chart('structure-layered-breadth',layeredBreadthOption(m,currentLayeredBreadthMetric));charts.push(layeredBreadthChart);renderLayeredBreadth(m);
 }
 var distributionLabels=m.v2_distribution_labels||m.return_distribution_labels||[],distributionCounts=m.v2_distribution_counts||m.return_distribution_counts||[],distributionRatios=m.v2_distribution_ratios||m.return_distribution_ratios||[];
 if(distributionLabels.length){
  charts.push(chart('structure-return-distribution',{tooltip:{trigger:'axis',axisPointer:{type:'shadow'},formatter:function(params){var p=params&&params[0]||{},i=p.dataIndex,ratio=distributionRatios[i];return p.name+'<br/>股票数量：'+p.value+' 家<br/>占比：'+pct(ratio);}},grid:{left:56,right:28,top:28,bottom:54},xAxis:{type:'category',data:distributionLabels,axisLabel:{fontSize:10,color:C.axis,rotate:20},axisLine:{lineStyle:{color:C.line}},splitLine:{show:false}},yAxis:ya('股票数量'),series:[{name:'股票数量',type:'bar',data:distributionCounts,barMaxWidth:34,itemStyle:{color:function(p){return p.dataIndex<Math.floor(distributionLabels.length/2)?C.down:C.up;},opacity:.72},label:{show:true,position:'top',fontSize:10,color:C.axis}}]}));
 }
 if(m.distribution_dates&&m.distribution_dates.length){
  var q10=line('Q10',m.distribution_q10,C.down,0,signedPct),median=line('中位数',m.distribution_median,C.ink,0,signedPct),q90=line('Q90',m.distribution_q90,C.up,0,signedPct);median.markLine=mark([0]);
  charts.push(chart('structure-distribution-quantiles',{tooltip:{trigger:'axis',axisPointer:{type:'cross'}},legend:{top:8,data:['Q10','中位数','Q90']},grid:{left:56,right:36,top:48,bottom:58},xAxis:ax(m.distribution_dates),yAxis:ya('横截面收益',0,function(v){return(v*100).toFixed(1)+'%';}),dataZoom:zoom(m.distribution_dates),series:[q10,median,q90]}));
 }
 if(m.dates&&m.dates.length){
  var advance=line('上涨比例',m.advance_ratio,C.up,0,pct);advance.markLine=mark([0.5]);
  var ad=line('标准化A/D',m.normalized_ad,C.blue,1);ad.markLine=mark([0]);
  var adEma10=line('A/D EMA10',m.normalized_ad_ema10,C.orange,1);
  var cumulative=line('累计A/D',m.ad_line_rebased,C.ink,1);cumulative.yAxisIndex=2;
  var cumulativeEma10=line('累计A/D EMA10',m.ad_line_ema10,C.purple,1);cumulativeEma10.yAxisIndex=2;
  var cumulativeEma20=line('累计A/D EMA20',m.ad_line_ema20,C.orange,1);cumulativeEma20.yAxisIndex=2;cumulativeEma20.lineStyle.type='dashed';
  charts.push(chart('structure-breadth',{tooltip:{trigger:'axis'},legend:{type:'scroll',top:8,left:36,right:36,data:['上涨比例','MA20上方','MA50上方','MA200上方','标准化A/D','A/D EMA10','累计A/D','累计A/D EMA10','累计A/D EMA20'],selected:{'MA20上方':false,'MA50上方':false,'MA200上方':false,'标准化A/D':false,'A/D EMA10':false,'累计A/D EMA10':false,'累计A/D EMA20':false}},grid:[{left:56,right:64,top:52,height:'30%'},{left:56,right:64,top:'54%',height:'34%'}],xAxis:[ax(m.dates,0),ax(m.dates,1)],yAxis:[ya('覆盖比例',0,function(v){return (v*100).toFixed(0)+'%';}),ya('A/D',1),Object.assign(ya('累计A/D',1),{position:'right'})],dataZoom:zoom(m.dates,[0,1]),series:[advance,line('MA20上方',m.pct_above_ma20,C.blue,0,pct),line('MA50上方',m.pct_above_ma50,C.orange,0,pct),line('MA200上方',m.pct_above_ma200,C.pink,0,pct),ad,adEma10,cumulative,cumulativeEma10,cumulativeEma20]}));
  var nhnl=line('NH-NL',m.normalized_nhnl_20,C.blue,0);nhnl.markLine=mark([0]);
  charts.push(chart('structure-tail',{tooltip:{trigger:'axis'},legend:{top:8,data:['20日新高','20日新低','NH-NL','跌超3%','跌超5%','近似跌停','横截面离散度']},grid:[{left:56,right:42,top:48,height:'31%'},{left:56,right:42,top:'57%',height:'27%'}],xAxis:[ax(m.dates,0),ax(m.dates,1)],yAxis:[ya('新高新低',0,function(v){return (v*100).toFixed(0)+'%';}),ya('尾部比例',1,function(v){return (v*100).toFixed(0)+'%';})],dataZoom:zoom(m.dates,[0,1]),series:[line('20日新高',m.new_high_20_ratio,C.up,0,pct),line('20日新低',m.new_low_20_ratio,C.down,0,pct),nhnl,{name:'跌超3%',type:'bar',xAxisIndex:1,yAxisIndex:1,data:m.decline_gt_3_ratio,tooltip:{valueFormatter:pct},itemStyle:{color:C.orange,opacity:.35}},{name:'跌超5%',type:'bar',xAxisIndex:1,yAxisIndex:1,data:m.decline_gt_5_ratio,tooltip:{valueFormatter:pct},itemStyle:{color:C.down,opacity:.45}},line('近似跌停',m.approximate_limit_down_ratio,C.ink,1,pct),line('横截面离散度',m.cross_section_dispersion,C.purple,1,pct)]}));
  charts.push(chart('structure-liquidity',{tooltip:{trigger:'axis'},legend:{top:8,data:['成交额/20日','上涨成交占比','下跌成交占比','平均股价收益']},grid:{left:56,right:42,top:48,bottom:58},xAxis:ax(m.dates),yAxis:[ya('倍数'),Object.assign(ya('收益'),{position:'right'})],dataZoom:zoom(m.dates),series:[line('成交额/20日',m.amount_ratio_20,C.ink,0,multiple),line('上涨成交占比',m.advance_amount_ratio,C.up,0,pct),line('下跌成交占比',m.decline_amount_ratio,C.down,0,pct),{name:'平均股价收益',type:'bar',yAxisIndex:1,data:m.all_a_index_return_1d,tooltip:{valueFormatter:signedPct},itemStyle:{color:function(p){return p.value>=0?C.up:C.down;},opacity:.35}}]}));
 }
 if(m.style_dates&&m.style_dates.length){
  var value=line('权重价值',m.value_strength,C.ink);value.markLine=mark([35,65]);
  charts.push(chart('structure-style',{tooltip:{trigger:'axis'},legend:{top:8,data:['权重价值','证券','科技成长','消费','小盘代理']},grid:{left:56,right:36,top:48,bottom:58},xAxis:ax(m.style_dates),yAxis:{type:'value',min:0,max:100,name:'强度',splitLine:{show:true,lineStyle:{type:'dashed',color:C.split}}},dataZoom:zoom(m.style_dates),series:[value,line('证券',m.securities_strength,C.orange),line('科技成长',m.growth_strength,C.blue),line('消费',m.consumer_strength,C.pink),line('小盘代理',m.small_cap_strength,C.purple)]}));
 }
 var industryRoot=window._INDUSTRY_KLINES||{};
 currentIndustrySymbol=String(window._PRIMARY_INDUSTRY_INDEX||Object.keys(industryRoot)[0]||'').toUpperCase();
 var industryInitial=currentIndustryData();
 if(industryInitial){
  industryKlineChart=chart('industry-kline',plainKlineOption(industryInitial,(industryRoot[currentIndustrySymbol]||{}).name||'行业'),'industry-index-sync');industryIndicatorChart=chart('industry-indicator',forecastVolumeOption(industryInitial),'industry-index-sync');charts.push(industryKlineChart,industryIndicatorChart);renderIndustryKline();
 }
 if(m.state_history_dates&&m.state_history_dates.length){
  var stateLabels=[],stateCode=function(v){var i=stateLabels.indexOf(v);if(i<0){stateLabels.push(v);i=stateLabels.length-1;}return i;},stateDims=m.state_history_dimensions||[],stateData=[];
  stateDims.forEach(function(item,y){(item.states||[]).forEach(function(value,x){stateData.push([x,y,stateCode(value)]);});});
  charts.push(chart('structure-state-history',{animation:false,tooltip:{formatter:function(p){var value=stateLabels[p.data[2]]||'unknown';return m.state_history_dates[p.data[0]]+'<br/>'+stateDims[p.data[1]].name+'：'+stateName(value)+'<br/><span style="color:#8a94a8">'+value+'</span>'; }},grid:{left:112,right:36,top:24,bottom:58},xAxis:{type:'category',data:m.state_history_dates,axisLabel:{fontSize:10,color:C.axis,rotate:30},axisLine:{lineStyle:{color:C.line}},splitArea:{show:false}},yAxis:{type:'category',data:stateDims.map(function(item){return item.name;}),axisLabel:{color:C.axis},axisLine:{lineStyle:{color:C.line}}},dataZoom:zoom(m.state_history_dates),series:[{name:'状态',type:'heatmap',data:stateData,itemStyle:{color:function(p){return stateColor(stateLabels[p.data[2]]||'unknown');},borderColor:'#fff',borderWidth:1},emphasis:{itemStyle:{shadowBlur:6,shadowColor:'rgba(0,0,0,.25)'}}}]}));
 }
 try{echarts.connect('forecast-index-sync');echarts.connect('industry-index-sync');}catch(e){}
 window.addEventListener('resize',function(){charts.filter(Boolean).forEach(function(c){c.resize();});if(forecastIndicatorChart)forecastIndicatorChart.resize();if(forecastKlineChart)renderForecastManualLines(forecastKlineChart);Object.keys(liftCharts).forEach(function(key){if(liftCharts[key])liftCharts[key].resize();});});
}
window.addEventListener('DOMContentLoaded',init);
})();
</script>
"""


def generate_index_forecast_report(
    features: pd.DataFrame,
    predictions: pd.DataFrame,
    output_path: str | Path,
    symbol: str,
    name: str,
    horizon: int,
    evaluation: dict[str, Any],
    market_structure: dict[str, Any] | None = None,
    legacy_links: dict[str, str] | None = None,
    llm_summary_links: dict[str, str] | None = None,
    technical_structure_config: dict[str, Any] | None = None,
    technical_index_frames: dict[str, pd.DataFrame] | None = None,
    technical_industry_frames: dict[str, pd.DataFrame] | None = None,
) -> Path:
    """Write the existing report with current market structure as the primary narrative."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    structure = market_structure or {}
    report_as_of = pd.to_datetime(structure.get("date"), errors="coerce")

    def clip_report_frame(frame: pd.DataFrame) -> pd.DataFrame:
        work = frame.copy()
        if pd.isna(report_as_of):
            return work
        date_column = "trade_date" if "trade_date" in work.columns else "date" if "date" in work.columns else None
        if date_column is None:
            return work
        dates = pd.to_datetime(work[date_column], errors="coerce")
        return work.loc[dates.notna() & dates.le(report_as_of)].copy()

    # This is a report-level safety boundary.  Historical reports must remain
    # causal even if a caller accidentally supplies full current caches.
    features = clip_report_frame(features)
    predictions = clip_report_frame(predictions)
    latest = predictions.iloc[-1].to_dict() if not predictions.empty else {}
    signal = str(latest.get("environment_signal", "neutral"))
    model = str(latest.get("model", "rule_v1"))
    structure_state = structure.get("market_structure") or {}
    regime = str(structure_state.get("style_regime", "mixed_rotation"))
    regime_name = str(structure_state.get("style_regime_name", "风格轮动"))
    headline = str(structure_state.get("headline", "当前市场结构数据不足。"))
    links = legacy_links or {}
    llm_links = llm_summary_links or {}
    llm_link_html = "".join(
        f"<a class='{escape(css_class, quote=True)}' href='{escape(href, quote=True)}' target='_blank'>{escape(label)}</a>"
        for label, href, css_class in (
            ("查看大模型复盘总结", llm_links.get("summary", ""), "primary"),
            ("LLM事实包", llm_links.get("facts", ""), ""),
        )
        if href
    )
    legacy_link_html = " · ".join(
        f"<a href='{escape(href, quote=True)}'>{escape(label)}</a>"
        for label, href in (("完整预测CSV", links.get("predictions", "")), ("完整诊断报告", links.get("diagnostics", "")))
        if href
    ) or "完整数据继续保存在原统计输出和诊断报告中"
    rankings = structure.get("industry_rankings") or {}
    technical_index_payload = _technical_index_kline_payload(
        features,
        symbol,
        structure,
        technical_index_frames,
        technical_structure_config,
    )
    primary_technical_symbol = str(symbol).upper()
    if primary_technical_symbol not in technical_index_payload and technical_index_payload:
        primary_technical_symbol = next(iter(technical_index_payload))
    technical_index_options = "".join(
        f"<option value='{escape(code, quote=True)}'{' selected' if code == primary_technical_symbol else ''}>"
        f"{escape(str(item.get('name') or code))}（{escape(code)}）</option>"
        for code, item in technical_index_payload.items()
    )
    primary_technical_timeframes = (
        technical_index_payload.get(primary_technical_symbol, {}).get("timeframes") or {}
    )
    industry_technical_payload = _industry_technical_kline_payload(
        features,
        rankings,
        technical_industry_frames,
        technical_structure_config,
        as_of=structure.get("date"),
    )
    primary_industry_symbol = next(iter(industry_technical_payload), "")
    clickable_industry_symbols = set(industry_technical_payload)
    industry_chart_html = (
        f"""
        <div class="industry-chart-head">
          <div class="industry-chart-title">行业指数K线与技术指标<small id="industry-kline-title">点击上方行业行查看K线</small></div>
          <div class="indicator-switches"><strong>周期</strong><button type="button" class="kline-period-btn industry-period-btn active" data-timeframe="1d" onclick="switchIndustryTimeframe('1d')">日K</button><button type="button" class="kline-period-btn industry-period-btn" data-timeframe="1w" onclick="switchIndustryTimeframe('1w')">周K</button><button type="button" class="kline-period-btn industry-period-btn" data-timeframe="1mo" onclick="switchIndustryTimeframe('1mo')">月K</button><strong>技术指标</strong><button type="button" class="industry-indicator-switch active" data-indicator="volume" onclick="switchIndustryIndicator('volume')">成交量</button><button type="button" class="industry-indicator-switch" data-indicator="kdj" onclick="switchIndustryIndicator('kdj')">KDJ</button><button type="button" class="industry-indicator-switch" data-indicator="macd" onclick="switchIndustryIndicator('macd')">MACD</button></div>
        </div>
        <div id="industry-kline" class="chart"></div>
        <div id="industry-indicator" class="chart industry-indicator"></div>
        """
        if industry_technical_payload
        else "<div class='industry-chart-empty'>当前行业榜没有可用的同花顺行业指数K线缓存；运行 <code>python main.py index ths</code> 后可点击行业查看K线。</div>"
    )
    body = f"""
    <main class="shell">
      <header class="topbar">
        <div>
          <h1>{escape(name)}与市场结构分析</h1>
          <div class="sub">{escape(symbol)} · 当前结构分析 · 数据截至 {escape(str(structure.get('date', latest.get('trade_date', '--'))))} · {escape(str(structure.get('schema_version') or '兼容版'))}</div>
          {f'<div class="top-actions">{llm_link_html}</div>' if llm_link_html else ''}
        </div>
        <div class="badge neutral">{escape(regime_name)}</div>
      </header>

      <section data-screen="1">
        <div class="panel-head" style="padding-left:0;padding-right:0;border:0"><h2><span class="screen-kicker">第1屏</span>市场状态总览</h2><span>确定性事实与状态；不引用探索性研究候选</span></div>
        <section class="cards">{_market_structure_cards(structure)}</section>
        <section style="margin-top:14px">{_deterministic_summary_html(structure)}</section>
        {_overview_evidence_details(structure)}
      </section>

      {_index_lift_structure_panel(structure)}

      <section class="panel" data-screen="2">
        <div class="panel-head"><h2><span class="screen-kicker">第2屏</span>指数趋势与技术结构</h2><span>日/周趋势、K线、技术指标与归一化相对强度</span></div>
        <div class="subpanel-title"><strong>主要指数</strong><span>日线、周线和支撑压力均为透明结构描述</span></div>
        <div class="v2-table-wrap"><table>
          <thead><tr><th>指数</th><th>代码</th><th>1日</th><th>5日</th><th>10日</th><th>20日</th><th>60日</th><th>日线</th><th>周线</th><th>成交/20日</th><th>MA20</th><th>MA60</th><th>20日高/距离</th><th>20日低/距离</th><th>60日高/距离</th><th>60日低/距离</th><th>位置</th></tr></thead>
          <tbody>{_index_structure_rows(structure)}</tbody>
        </table></div>
        <div class="subpanel-title"><strong>指数K线与手动画线</strong><span>K线、成交量、成交额、三市总成交额与量额比同图；指数使用不复权点位</span></div>
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
        <div class="forecast-integrated-note">主图下方依次显示指数成交量、指数成交额、三市总成交额和指数量额比，红色代表上涨日、绿色代表下跌日；自动结构线显示已关闭，支撑/阻力/趋势线均由你手动绘制并保存在浏览器本地。</div>
        <div id="forecast-kline" class="chart"></div>
        <div class="kline-subchart-head"><div class="indicator-switches"><strong>副图</strong><button type="button" class="indicator-switch-btn" data-indicator="kdj" onclick="switchForecastIndicator('kdj')">KDJ</button><button type="button" class="indicator-switch-btn" data-indicator="macd" onclick="switchForecastIndicator('macd')">MACD</button></div><span>成交量/成交额已在主图内；KDJ/MACD 可按需展开</span></div>
        <div id="forecast-index-indicator" class="chart index-indicator"></div>
        <div class="subpanel-title"><strong>主要指数区间强度对比</strong><span>所选区间首个有效交易日统一归一为100，只比较区间涨跌强弱</span></div>
        <div class="index-compare-tools"><strong>比较区间</strong><button type="button" class="index-compare-window" data-window="20" onclick="switchIndexCompareWindow(20)">20日</button><button type="button" class="index-compare-window" data-window="60" onclick="switchIndexCompareWindow(60)">60日</button><button type="button" class="index-compare-window active" data-window="120" onclick="switchIndexCompareWindow(120)">120日</button><button type="button" class="index-compare-window" data-window="250" onclick="switchIndexCompareWindow(250)">250日</button><span>包含上证、沪深300、中证500/1000/2000、创业板、科创50和平均股价</span></div>
        <div id="structure-index-compare" class="chart"></div>
        <div id="structure-index-ranking" class="index-strength-ranking"></div>
        <div class="grid">
          <div>
            <div class="panel-head"><h2>沪深300与平均股价相对强弱</h2><span>高于100表示沪深300相对占优</span></div>
            <div id="structure-relative" class="chart small"></div>
          </div>
          <table><thead><tr><th>周期</th><th>分化判断</th><th>差值证据（平均股价－沪深300）</th></tr></thead><tbody>
            <tr><td>1日</td><td>{escape(_divergence_text((structure_state.get('divergence') or {}).get('one_day')))}</td><td>{escape(_fmt_pct(((structure_state.get('divergence') or {}).get('evidence') or {}).get('one_day_gap')))}</td></tr>
            <tr><td>5日</td><td>{escape(_divergence_text((structure_state.get('divergence') or {}).get('five_day')))}</td><td>{escape(_fmt_pct(((structure_state.get('divergence') or {}).get('evidence') or {}).get('five_day_gap')))}</td></tr>
            <tr><td>20日</td><td>{escape(_divergence_text((structure_state.get('divergence') or {}).get('twenty_day')))}</td><td>{escape(_fmt_pct(((structure_state.get('divergence') or {}).get('evidence') or {}).get('twenty_day_gap')))}</td></tr>
          </tbody></table>
        </div>
      </section>

      <section class="panel" data-screen="3">
        <div class="panel-head"><h2><span class="screen-kicker">第3屏</span>分层市场广度</h2><span>统一展示全A与主要宽基的参与度、均线覆盖和A/D</span></div>
        <div class="v2-table-wrap"><table>
          <thead><tr><th>层级</th><th>状态</th><th>有效成员</th><th>覆盖率</th><th>上涨比例</th><th>MA20上方</th><th>MA60上方</th><th>20日新高/新低</th><th>标准化A/D</th><th>成交占比</th><th>成员口径</th><th>行情新鲜度</th></tr></thead>
          <tbody>{_layered_breadth_rows(structure)}</tbody>
        </table></div>
        <div class="layered-breadth-tools"><strong>图表指标</strong>
          <button type="button" class="layered-breadth-switch active" data-metric="advance_ratio" onclick="switchLayeredBreadthMetric('advance_ratio')">上涨比例</button>
          <button type="button" class="layered-breadth-switch" data-metric="pct_above_ma5" onclick="switchLayeredBreadthMetric('pct_above_ma5')">MA5</button><button type="button" class="layered-breadth-switch" data-metric="pct_above_ma10" onclick="switchLayeredBreadthMetric('pct_above_ma10')">MA10</button><button type="button" class="layered-breadth-switch" data-metric="pct_above_ma20" onclick="switchLayeredBreadthMetric('pct_above_ma20')">MA20</button><button type="button" class="layered-breadth-switch" data-metric="pct_above_ma60" onclick="switchLayeredBreadthMetric('pct_above_ma60')">MA60</button>
          <button type="button" class="layered-breadth-switch" data-metric="new_high_5_ratio" onclick="switchLayeredBreadthMetric('new_high_5_ratio')">5日新高</button><button type="button" class="layered-breadth-switch" data-metric="new_low_5_ratio" onclick="switchLayeredBreadthMetric('new_low_5_ratio')">5日新低</button><button type="button" class="layered-breadth-switch" data-metric="new_high_10_ratio" onclick="switchLayeredBreadthMetric('new_high_10_ratio')">10日新高</button><button type="button" class="layered-breadth-switch" data-metric="new_low_10_ratio" onclick="switchLayeredBreadthMetric('new_low_10_ratio')">10日新低</button><button type="button" class="layered-breadth-switch" data-metric="new_high_20_ratio" onclick="switchLayeredBreadthMetric('new_high_20_ratio')">20日新高</button><button type="button" class="layered-breadth-switch" data-metric="new_low_20_ratio" onclick="switchLayeredBreadthMetric('new_low_20_ratio')">20日新低</button><button type="button" class="layered-breadth-switch" data-metric="new_high_60_ratio" onclick="switchLayeredBreadthMetric('new_high_60_ratio')">60日新高</button><button type="button" class="layered-breadth-switch" data-metric="new_low_60_ratio" onclick="switchLayeredBreadthMetric('new_low_60_ratio')">60日新低</button>
          <span>新高/新低基准均排除当日</span>
        </div>
        <div id="structure-layered-breadth" class="chart layered-chart"></div>
        <div class="subpanel-title"><strong>市场广度明细</strong><span>展开每个指标查看定义和口径</span></div>
        <div class="breadth-metric-grid">{_breadth_metric_cards(structure)}</div>
        <div class="breadth-subhead"><strong>A/D 与均线覆盖</strong><span>默认显示上涨比例与累计 A/D；累计 A/D EMA10/20 可在图例打开</span></div>
        <div id="structure-breadth" class="chart breadth-ad-chart"></div>
      </section>

      <section class="panel" data-screen="4">
        <div class="panel-head"><h2><span class="screen-kicker">第4屏</span>横截面收益分布</h2><span>当日直方图与最近20个交易日 Q10/中位数/Q90；不是未来收益分布</span></div>
        {_distribution_metric_tiles(structure)}
        <div class="breadth-subhead"><strong>当日个股涨跌幅分布</strong><span>按最新交易日有效股票 1 日涨跌幅分桶；柱高为股票数量</span></div>
        <div id="structure-return-distribution" class="chart breadth-distribution-chart"></div>
        <div class="breadth-subhead"><strong>20日分位轨迹</strong><span>Q10、横截面中位数与Q90分别描述左尾、典型股票和右尾</span></div>
        <div id="structure-distribution-quantiles" class="chart distribution-quantile-chart"></div>
      </section>

      <section class="panel" data-screen="5">
        <div class="panel-head"><h2><span class="screen-kicker">第5屏</span>风格轮动、领涨质量与行业结构</h2><span>当前横向强弱，不表示未来收益概率</span></div>
        {_leadership_callout(structure)}
        <div class="subpanel-title"><strong>风格轮动状态</strong><span>强度水位、5日变化、20日相对斜率与领涨持续时间</span></div>
        <div class="v2-table-wrap compact"><table><thead><tr><th>风格</th><th>当前强度</th><th>5日变化</th><th>20日相对强弱</th><th>领涨天数</th><th>领涨质量</th><th>当前状态</th></tr></thead><tbody>{_style_rotation_rows(structure)}</tbody></table></div>
        <div class="subpanel-title"><strong>兼容版市场风格</strong><span>行业先内部等权、再行业等权</span></div>
        <div class="note" style="margin:14px 16px 0">{escape(_style_method_note())}</div>
        <table>
          <thead><tr><th>风格</th><th>5日</th><th>20日</th><th>60日</th><th>5日状态</th><th>20日状态</th><th>60日状态</th><th>相对平均股价20日</th><th>内部证据</th><th>强度</th><th>综合</th></tr></thead>
          <tbody>{_style_rows(structure)}</tbody>
        </table>
        <div class="details-grid">{_style_contribution_details(structure)}</div>
        <div id="structure-style" class="chart"></div>
        <div class="subpanel-title"><strong>行业结构 v2</strong><span>按10日强弱排序；展示5/10/20日收益、相对强弱、内部广度与领涨质量</span></div>
        <div class="grid">
          <table><thead><tr><th>最强行业</th><th>股票数</th><th>5日</th><th>10日</th><th>20日</th><th>相对平均股价20日</th><th>上涨比例</th><th>MA20上方</th><th>领涨质量</th></tr></thead><tbody>{_v2_industry_rows((structure.get('industry_structure') or {}).get('strongest') or [])}</tbody></table>
          <table><thead><tr><th>最弱行业</th><th>股票数</th><th>5日</th><th>10日</th><th>20日</th><th>相对平均股价20日</th><th>上涨比例</th><th>MA20上方</th><th>领涨质量</th></tr></thead><tbody>{_v2_industry_rows((structure.get('industry_structure') or {}).get('weakest') or [])}</tbody></table>
        </div>
        <div class="subpanel-title"><strong>行业强弱榜</strong><span>同花顺行业指数代理；按当日强弱排序，只描述当前结构</span></div>
        <div class="note" style="margin:14px 16px 0">{escape(str(rankings.get('method_note', '当前行业分类回溯口径，历史比较置信度有限。')))}</div>
        <div class="grid">
          <table><thead><tr><th>最强行业</th><th>1日</th><th>5日</th><th>20日</th><th>上涨比例</th><th>MA20上方</th><th>成交占比变化</th></tr></thead><tbody>{_industry_rows(rankings.get('strongest') or [], clickable_industry_symbols)}</tbody></table>
          <table><thead><tr><th>最弱行业</th><th>1日</th><th>5日</th><th>20日</th><th>上涨比例</th><th>MA20上方</th><th>成交占比变化</th></tr></thead><tbody>{_industry_rows(rankings.get('weakest') or [], clickable_industry_symbols)}</tbody></table>
        </div>
        {industry_chart_html}
        <div class="subpanel-title"><strong>银行、保险与证券</strong><span>优先使用同花顺行业指数代理；银行强、证券弱通常更接近防御而非全面进攻</span></div>
        <div class="grid">
          <table>
            <thead><tr><th>板块</th><th>样本</th><th>1日</th><th>5日</th><th>20日</th><th>上涨比例</th><th>MA20上方</th><th>成交证据</th></tr></thead>
            <tbody>{_sector_rows(structure)}</tbody>
          </table>
          <table>
            <thead><tr><th>关键相对强弱</th><th>当前值</th></tr></thead>
            <tbody>{_relative_strength_rows(structure)}</tbody>
          </table>
        </div>
      </section>

      <section class="panel" data-screen="6">
        <div class="panel-head"><h2><span class="screen-kicker">第6屏</span>风险、修复与探索性阶段</h2><span>三类独立风险证据族与修复状态；当前压力不等于未来下跌概率</span></div>
        {_risk_v2_tiles(structure)}
        {_research_candidates_html(structure)}
        <div class="subpanel-title"><strong>新高新低与风险扩散</strong><span>近似涨跌停已区分ST、创业板/科创板和主板</span></div>
        <div class="risk-explain-list">{_risk_direction_rows(structure)}</div>
        <div id="structure-tail" class="chart"></div>
      </section>

      <section class="panel" data-screen="7">
        <div class="panel-head"><h2><span class="screen-kicker">第7屏</span>流动性、贡献与集中度</h2><span>全A真实成交口径，不随上方指数选择切换</span></div>
        {_liquidity_tiles(structure)}
        <div class="subpanel-title"><strong>贡献与集中度证据</strong><span>集中度使用历史分位，权重贡献取决于可用权重快照</span></div>
        <div class="v2-table-wrap compact"><table><thead><tr><th>指标</th><th>当前值</th><th>含义/限制</th></tr></thead><tbody>{_contribution_rows(structure)}</tbody></table></div>
        <div class="subpanel-title"><strong>全市场成交与流动性</strong><span>兼容版时间序列</span></div>
        <div id="structure-liquidity" class="chart"></div>
      </section>

      <section class="panel" data-screen="8">
        <div class="panel-head"><h2><span class="screen-kicker">第8屏</span>市场状态历史</h2><span>横向状态带展示最近状态段；底部滑块仅控制本图日期轴</span></div>
        <div id="structure-state-history" class="chart state-history-chart"></div>
        <div class="v2-table-wrap compact"><table><thead><tr><th>维度</th><th>当前状态</th><th>开始日期</th><th>结束日期</th><th>持续交易日</th><th>区间状态段数</th></tr></thead><tbody>{_state_history_rows(structure)}</tbody></table></div>
      </section>

      <section class="panel" data-screen="9">
        <div class="panel-head"><h2><span class="screen-kicker">第9屏</span>证据、来源新鲜度与时点质量</h2><span>缺失就是未知；质量矩阵不把未知自动解释为中性</span></div>
        <div class="subpanel-title"><strong>证据质量矩阵</strong><span>置信度表示证据完整性与一致性，不是概率</span></div>
        <div class="v2-table-wrap"><table><thead><tr><th>维度</th><th>状态</th><th>置信等级</th><th>置信分</th><th>独立证据族</th><th>覆盖率</th><th>新鲜</th><th>PIT</th></tr></thead><tbody>{_evidence_matrix_rows(structure)}</tbody></table></div>
        <div class="subpanel-title"><strong>数据来源新鲜度</strong><span>交易日滞后按本地有效交易日历计算</span></div>
        <div class="v2-table-wrap"><table><thead><tr><th>来源键</th><th>数据源</th><th>数据日期</th><th>报告时点</th><th>滞后交易日</th><th>状态</th><th>PIT</th></tr></thead><tbody>{_source_freshness_rows(structure)}</tbody></table></div>
        <div class="quality-matrix">
          <div class="quality-block"><h3>Point-in-time 声明</h3><table><thead><tr><th>项目</th><th>当前声明</th></tr></thead><tbody>{_point_in_time_rows(structure)}</tbody></table></div>
          <div class="quality-block"><h3>数据质量标记</h3><div class="quality-flags">{_quality_flags(structure)}</div></div>
        </div>
        <section class="note" style="margin:0 16px 16px">
          当前行业篮子使用Tushare现有行业分类，缺少point-in-time历史退市股、历史ST及历史行业快照；主题概念没有可靠历史成分时未回填。
          小盘题材第一版使用中证1000官方指数代理。近似涨跌停只作当前结构统计。所有状态均描述当前市场，不预测明日涨跌，也不构成仓位建议。
        </section>
      </section>

      <details class="panel legacy">
        <summary>实验性预测诊断（不参与当前市场结构结论）</summary>
        <section class="note"><strong>旧模型失效警告：</strong>旧预测只保留用于回归和研究复盘，不参与顶部市场总结、市场结构状态、正式策略、仓位或订单。</section>
        <section class="cards">{_cards(latest, evaluation)}</section>
        <section class="panel">
          <div class="panel-head"><h2>旧模型核心评估摘要</h2><span>{legacy_link_html}</span></div>
          <table><thead><tr><th>预测环境</th><th>样本</th><th>个股收益中位数</th><th>等权收益</th><th>上涨股票比例</th><th>尾部Q10</th><th>中位最大回撤</th><th>标签命中</th></tr></thead><tbody>{_signal_summary_rows(evaluation)}</tbody></table>
        </section>
        <section class="panel">
          <div class="panel-head"><h2>最近20条实验预测</h2><span>最新日期未来收益为空属正常</span></div>
          <table><thead><tr><th>日期</th><th>收盘</th><th>预测环境</th><th>分数</th><th>涨/平/跌</th><th>个股中位收益</th><th>等权收益</th><th>上涨比例</th><th>尾部Q10</th><th>指数/广度分化</th><th>实际环境</th></tr></thead><tbody>{_recent_rows(predictions, horizon)}</tbody></table>
        </section>
      </details>
    </main>
    """
    html = html_document(
        title=f"{name}与市场结构分析",
        body=body,
        styles=_CSS,
        head_extra=_echarts_script_tag(),
        scripts=(
            inline_script(
                f"window._FORECAST_CHART={to_compact_json(_chart_payload(features, predictions))};"
                f"window._MARKET_STRUCTURE={to_compact_json(_market_chart_payload(structure))};"
                f"window._INDEX_LIFT_STRUCTURE={to_compact_json(_index_lift_chart_payload(structure))};"
                f"window._PRIMARY_TECHNICAL_INDEX={to_compact_json(primary_technical_symbol)};"
                f"window._TECHNICAL_INDEX_KLINES={to_compact_json(technical_index_payload)};"
                f"window._TECHNICAL_KLINES={to_compact_json(primary_technical_timeframes)};"
                f"window._PRIMARY_INDUSTRY_INDEX={to_compact_json(primary_industry_symbol)};"
                f"window._INDUSTRY_KLINES={to_compact_json(industry_technical_payload)};"
            )
            + _JS_V11
        ),
    )
    output.write_text(html, encoding="utf-8")
    return output


def generate_market_structure_snapshot_report(
    structure: dict[str, Any],
    output_path: str | Path,
    symbol: str,
    name: str,
    facts_href: str | None = None,
) -> Path:
    """Write a compact, chart-free historical market-structure snapshot.

    The normal interactive report embeds many years of K-line and chart payloads and
    is intentionally large.  Historical backfills instead keep one lightweight HTML
    per date while the machine-readable JSON/CSV files remain the audit source.
    """
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    state = structure.get("market_structure") or {}
    rankings = structure.get("industry_rankings") or {}
    facts_link = (
        f"<a href='{escape(facts_href, quote=True)}' target='_blank'>查看 LLM 事实包</a>"
        if facts_href else ""
    )
    body = f"""
    <main class="shell snapshot-shell">
      <header class="topbar">
        <div>
          <h1>{escape(name)}与市场结构分析</h1>
          <div class="sub">{escape(symbol.upper())} · 历史 as-of 快照 · 数据截至 {escape(str(structure.get('date', '--')))}</div>
          {f'<div class="top-actions">{facts_link}</div>' if facts_link else ''}
        </div>
        <div class="badge neutral">{escape(str(state.get('style_regime_name', '数据不足')))}</div>
      </header>
      <section class="cards">{_market_structure_cards(structure)}</section>
      <section class="note headline">{escape(str(state.get('headline', '当前市场结构数据不足。')))}</section>
      <section class="panel">
        <div class="panel-head"><h2>主要指数</h2><span>所有字段均已按快照日期截断</span></div>
        <div class="snapshot-table"><table><thead><tr><th>指数</th><th>代码</th><th>1日</th><th>5日</th><th>10日</th><th>20日</th><th>60日</th><th>日线</th><th>周线</th><th>成交/20日</th><th>MA20</th><th>MA60</th><th>20日高/距离</th><th>20日低/距离</th><th>60日高/距离</th><th>60日低/距离</th><th>位置</th></tr></thead><tbody>{_index_structure_rows(structure)}</tbody></table></div>
      </section>
      <section class="panel">
        <div class="panel-head"><h2>市场广度</h2><span>展开每个指标查看定义</span></div>
        <div class="breadth-metric-grid">{_breadth_metric_cards(structure)}</div>
      </section>
      <section class="panel">
        <div class="panel-head"><h2>市场风格</h2><span>结构描述，不代表未来收益概率</span></div>
        <div class="snapshot-table"><table><thead><tr><th>风格</th><th>5日</th><th>20日</th><th>60日</th><th>5日状态</th><th>20日状态</th><th>60日状态</th><th>相对平均股价20日</th><th>内部证据</th><th>强度</th><th>综合</th></tr></thead><tbody>{_style_rows(structure)}</tbody></table></div>
      </section>
      <section class="panel">
        <div class="panel-head"><h2>行业强弱榜</h2><span>{escape(str(rankings.get('method_note', '--')))}</span></div>
        <div class="grid">
          <table><thead><tr><th>最强行业</th><th>1日</th><th>5日</th><th>20日</th><th>上涨比例</th><th>MA20上方</th><th>成交变化</th></tr></thead><tbody>{_industry_rows(rankings.get('strongest') or [])}</tbody></table>
          <table><thead><tr><th>最弱行业</th><th>1日</th><th>5日</th><th>20日</th><th>上涨比例</th><th>MA20上方</th><th>成交变化</th></tr></thead><tbody>{_industry_rows(rankings.get('weakest') or [])}</tbody></table>
        </div>
      </section>
      <section class="panel">
        <div class="panel-head"><h2>银行、保险与证券</h2><span>优先使用同花顺行业指数代理</span></div>
        <div class="grid">
          <table><thead><tr><th>板块</th><th>样本</th><th>1日</th><th>5日</th><th>20日</th><th>上涨比例</th><th>MA20上方</th><th>成交证据</th></tr></thead><tbody>{_sector_rows(structure)}</tbody></table>
          <table><thead><tr><th>关键相对强弱</th><th>当前值</th></tr></thead><tbody>{_relative_strength_rows(structure)}</tbody></table>
        </div>
      </section>
      <section class="panel">
        <div class="panel-head"><h2>新高新低与风险扩散</h2><span>压力等级与变化方向分开解释</span></div>
        <div class="risk-explain-list">{_risk_direction_rows(structure)}</div>
      </section>
      <section class="note"><strong>数据质量与口径：</strong>{_quality_flags(structure)}<br>该文件是轻量历史快照；完整纵向研究以同批次汇总面板和事件研究表为准。</section>
    </main>
    """
    styles = _CSS + """
    .snapshot-shell { width:min(1280px, calc(100vw - 40px)); }
    .snapshot-table { overflow-x:auto; }
    .snapshot-table table { min-width:1100px; }
    """
    output.write_text(
        html_document(title=f"{name}市场结构历史快照", body=body, styles=styles),
        encoding="utf-8",
    )
    return output
