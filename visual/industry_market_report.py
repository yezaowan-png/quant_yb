"""Standalone industry market report."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

import pandas as pd

from visual.components import html_document, inline_script, json_script_data, relative_href, script_src, to_compact_json
from visual.index_forecast_report import (
    _CSS,
    _JS_V11,
    _fmt_pct,
    _fmt_ratio_pct,
    _industry_technical_kline_payload,
    _plain_multi_timeframe_kline_payload,
    _tone,
)


_INDUSTRY_CSS = """
.industry-market-shell {
  width: min(1880px, calc(100vw - 28px));
  padding: 18px 0 34px;
}
.industry-market-shell .topbar {
  margin-bottom: 16px;
}
.industry-market-shell .chart {
  height: min(70vh, 760px);
  min-height: 560px;
}
.industry-market-shell .chart.industry-indicator {
  height: 260px;
  min-height: 240px;
}
.industry-market-overview-grid {
  display: grid;
  grid-template-columns: minmax(420px, 0.56fr) minmax(360px, 0.44fr);
  gap: 14px;
  align-items: stretch;
  padding: 16px;
}
.industry-market-table-wrap {
  margin: 0;
  max-height: min(46vh, 540px);
  overflow: auto;
}
.industry-market-table {
  min-width: 1180px;
  font-size: 12px;
}
.industry-market-table th,
.industry-market-table td {
  padding: 10px 12px;
}
.industry-market-table th.sortable {
  cursor: pointer;
  user-select: none;
}
.industry-market-table th.sortable:hover {
  color: #2f6df6;
}
.industry-market-table th.sorted::after {
  content: attr(data-sort-mark);
  margin-left: 6px;
  color: #2f6df6;
  font-size: 11px;
}
.industry-market-row-hidden {
  display: none;
}
.ths-market-name-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 170px;
}
.ths-market-name-cell > div {
  min-width: 0;
}
.ths-watch-btn {
  flex: 0 0 26px;
  width: 26px;
  height: 26px;
  border: 1px solid #d9e0ea;
  border-radius: 999px;
  background: #fff;
  color: #8a94a6;
  cursor: pointer;
  font-size: 14px;
  font-weight: 900;
  line-height: 1;
}
.ths-watch-btn:hover,
.ths-watch-btn.active {
  border-color: #f2b35f;
  background: #fff7ed;
  color: #c46a12;
}
.industry-row-clickable.watched {
  box-shadow: inset 3px 0 0 #f2b35f;
}
.ths-market-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.ths-market-title-row h2 {
  margin: 0;
}
.ths-market-mode-switch {
  display: inline-flex;
  gap: 6px;
  padding: 3px;
  border: 1px solid #d9e0ea;
  background: #f7f9fc;
}
.ths-market-mode-btn {
  border: 0;
  background: transparent;
  color: #465268;
  cursor: pointer;
  font-size: 12px;
  font-weight: 900;
  padding: 7px 12px;
}
.ths-market-mode-btn.active {
  background: #172033;
  color: #fff;
}
.industry-amount-head {
  min-width: 116px;
}
.industry-amount-title {
  margin-bottom: 5px;
  color: #69748a;
  font-weight: 900;
}
.industry-sort-chips {
  display: inline-flex;
  gap: 4px;
  align-items: center;
}
.industry-sort-chip {
  border: 1px solid #d9e0ea;
  border-radius: 999px;
  background: #fff;
  color: #5d6b82;
  cursor: pointer;
  font-size: 10px;
  font-weight: 900;
  line-height: 1;
  padding: 4px 7px;
}
.industry-sort-chip:hover,
.industry-sort-chip.sorted {
  border-color: #2f6df6;
  color: #2f6df6;
  background: #eef4ff;
}
.industry-sort-chip.sorted::after {
  content: attr(data-sort-mark);
  margin-left: 3px;
}
.industry-amount-cell {
  display: grid;
  gap: 2px;
  justify-items: end;
  line-height: 1.35;
  white-space: nowrap;
}
.industry-amount-cell strong {
  color: #172033;
  font-weight: 900;
}
.industry-amount-cell span {
  color: #69748a;
  font-size: 10px;
}
.industry-market-note {
  margin: 14px 16px 0;
  padding: 14px 16px;
  border: 1px solid #d9e0ea;
  background: #fbfcfe;
  color: #69748a;
  line-height: 1.7;
}
.ths-market-tools {
  margin: 12px 16px 0;
  padding: 10px 12px;
  border: 1px solid #d9e0ea;
  background: #fbfcfe;
  display: grid;
  gap: 10px;
}
.ths-market-search {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.ths-market-search input {
  flex: 1 1 280px;
  min-width: 220px;
  border: 1px solid #d9e0ea;
  background: #fff;
  color: #172033;
  font-size: 13px;
  font-weight: 700;
  padding: 8px 10px;
}
.ths-market-search input:focus {
  outline: 2px solid rgba(47, 109, 246, 0.18);
  border-color: #2f6df6;
}
.ths-tool-btn {
  border: 1px solid #d9e0ea;
  background: #fff;
  color: #465268;
  cursor: pointer;
  font-size: 12px;
  font-weight: 900;
  padding: 8px 11px;
}
.ths-tool-btn:hover,
.ths-tool-btn.active {
  border-color: #2f6df6;
  background: #eef4ff;
  color: #2f6df6;
}
.ths-market-filter-status {
  margin-left: auto;
  color: #69748a;
  font-size: 12px;
  font-weight: 800;
}
.ths-watch-pool {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-height: 30px;
}
.ths-watch-pool strong {
  flex: 0 0 auto;
  color: #69748a;
  font-size: 12px;
  line-height: 28px;
}
.ths-watch-pool-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-height: 70px;
  overflow: auto;
}
.ths-watch-empty {
  color: #8a94a6;
  font-size: 12px;
  line-height: 28px;
}
.ths-watch-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 220px;
  border: 1px solid #d9e0ea;
  border-radius: 999px;
  background: #fff;
  color: #465268;
  cursor: pointer;
  font-size: 12px;
  font-weight: 900;
  padding: 6px 8px 6px 10px;
}
.ths-watch-chip:hover {
  border-color: #2f6df6;
  color: #2f6df6;
}
.ths-watch-chip.active {
  border-color: #f2b35f;
  background: #fff7ed;
  color: #c46a12;
}
.ths-watch-chip span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ths-market-kind {
  display: inline-flex;
  align-items: center;
  margin-left: 7px;
  padding: 2px 6px;
  border: 1px solid #d9e0ea;
  border-radius: 999px;
  color: #69748a;
  font-size: 10px;
  font-weight: 900;
  line-height: 1;
}
.ths-watch-chip small {
  color: #8a94a6;
  font-size: 10px;
  font-weight: 800;
}
.ths-watch-chip button {
  border: 0;
  background: transparent;
  color: #8a94a6;
  cursor: pointer;
  font-size: 13px;
  font-weight: 900;
  padding: 0 2px;
}
.ths-watch-chip button:hover {
  color: #cf4446;
}
.industry-member-panel {
  border: 1px solid #dbe3ef;
  background: #fff;
  min-height: 260px;
  max-height: min(46vh, 540px);
  overflow: auto;
}
.industry-member-head {
  position: sticky;
  top: 0;
  z-index: 2;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  padding: 12px 14px;
  border-bottom: 1px solid #edf0f5;
  background: #fbfcfe;
}
.industry-member-head strong {
  display: block;
  color: #172033;
  font-size: 14px;
}
.industry-member-head span {
  color: #69748a;
  font-size: 11px;
  text-align: right;
  line-height: 1.5;
}
.industry-member-list { padding: 0; }
.industry-member-empty {
  margin: 12px 0 0;
  padding: 14px;
  border: 1px dashed #d9e0ea;
  background: #fbfcfe;
  color: #69748a;
  line-height: 1.7;
}
.industry-member-table {
  width: 100%;
  min-width: 760px;
  border-collapse: collapse;
  font-size: 11px;
}
.industry-member-table th,
.industry-member-table td {
  padding: 8px 9px;
  border-bottom: 1px solid #edf0f5;
  vertical-align: middle;
}
.industry-member-table th {
  position: sticky;
  top: 49px;
  z-index: 1;
  background: #f6f8fb;
  color: #69748a;
  font-weight: 900;
  text-align: left;
  white-space: nowrap;
}
.industry-member-table th.sortable {
  cursor: pointer;
  user-select: none;
}
.industry-member-table th.sortable:hover { color: #2f6df6; }
.industry-member-table th.sorted::after {
  content: attr(data-sort-mark);
  margin-left: 5px;
  color: #2f6df6;
}
.industry-member-table td.num,
.industry-member-table th.num { text-align: right; }
.industry-member-stock-row { cursor: pointer; }
.industry-member-stock-row:hover { background: #f3f6fb; }
.industry-member-stock-row.active { background: #eef4ff; box-shadow: inset 3px 0 0 #2f6df6; }
.industry-member-name {
  color: #172033;
  font-weight: 800;
  font-size: 12px;
  white-space: nowrap;
}
.industry-member-code,
.industry-member-meta {
  color: #69748a;
  font-size: 10px;
  line-height: 1.5;
}
.industry-member-price {
  text-align: right;
  color: #172033;
  font-weight: 800;
  font-size: 11px;
  white-space: nowrap;
}
.industry-member-kline {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 5px 8px;
  border-radius: 8px;
  background: #2f6df6;
  color: white;
  font-size: 11px;
  font-weight: 800;
  text-decoration: none;
}
.industry-member-kline.missing {
  background: #eef2f7;
  color: #8a94a6;
  pointer-events: none;
}
.industry-member-kline {
  border: 0;
  cursor: pointer;
}
.industry-stock-kline-shell {
  display: none;
  margin: 12px 18px 0;
  border: 1px solid #dbe3ef;
  background: #fff;
}
.industry-stock-kline-bar {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  padding: 10px 12px;
  border-bottom: 1px solid #edf0f5;
  background: #fbfcfe;
}
.industry-stock-kline-bar strong {
  color: #172033;
  font-size: 14px;
}
.industry-stock-kline-bar button {
  border: 1px solid #d9e0ea;
  background: #fff;
  color: #465268;
  padding: 6px 10px;
  cursor: pointer;
  font-weight: 800;
}
.industry-stock-kline-actions,
.industry-stock-period-switches,
.industry-stock-drawing-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  align-items: center;
}
.industry-stock-drawing-tools {
  padding: 10px 12px;
  border-bottom: 1px solid #edf0f5;
  background: #fff;
}
.industry-stock-drawing-tools strong {
  color: #69748a;
  font-size: 12px;
}
.industry-stock-drawing-btn {
  border: 1px solid #d9e0ea;
  border-radius: 999px;
  background: #f7f9fc;
  color: #465268;
  padding: 6px 10px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 900;
}
.industry-stock-drawing-btn.active {
  background: #2f6df6;
  border-color: #245ac0;
  color: #fff;
}
.industry-stock-drawing-btn.danger {
  color: #9f1239;
}
.industry-stock-period-btn {
  border: 1px solid #d9e0ea;
  border-radius: 999px;
  background: #f7f9fc;
  color: #465268;
  padding: 6px 10px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 900;
}
.industry-stock-period-btn.active {
  background: #2f6df6;
  border-color: #245ac0;
  color: #fff;
}
.industry-stock-drawing-status {
  color: #69748a;
  font-size: 12px;
  line-height: 1.6;
}
.industry-stock-chart-wrap {
  position: relative;
  width: 100%;
  height: min(78vh, 820px);
  min-height: 620px;
}
.industry-stock-kline-chart {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  background: #fff;
}
.industry-stock-drawing-layer {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 5;
  overflow: visible;
}
.industry-stock-drawing-layer.active {
  pointer-events: auto;
  cursor: crosshair;
}
.industry-stock-manual-line {
  pointer-events: stroke;
  cursor: move;
}
.industry-stock-manual-handle {
  pointer-events: all;
  cursor: grab;
}
.industry-stock-manual-handle:active {
  cursor: grabbing;
}
.industry-stock-manual-label {
  pointer-events: none;
  font-size: 12px;
  font-weight: 900;
  paint-order: stroke;
  stroke: #fff;
  stroke-width: 3px;
}
.industry-stock-kline-empty {
  margin: 14px;
  padding: 18px;
  border: 1px dashed #d9e0ea;
  background: #fbfcfe;
  color: #69748a;
  line-height: 1.7;
}
.industry-manual-toolbar {
  justify-content: flex-start;
  margin: 10px 18px 0;
  padding: 10px 12px;
  border: 1px solid #e3e8f0;
  background: #fbfcfe;
}
.industry-manual-toolbar #forecast-manual-status {
  flex: 1 1 360px;
  text-align: left;
}
.ths-mode-pane[hidden] {
  display: none !important;
}
.embedded-stock-viewer {
  margin-top: 0;
}
.embedded-stock-viewer .viewer-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}
.embedded-stock-viewer .viewer-head h2 {
  margin: 0;
}
.embedded-stock-viewer .viewer-head span {
  color: #69748a;
  font-size: 12px;
  font-weight: 800;
}
.embedded-stock-viewer .viewer-shell {
  display: block;
  padding: 12px 16px 14px;
}
.embedded-stock-viewer .viewer-sidebar {
  border: 1px solid #dbe3ef;
  background: #fff;
  min-width: 0;
}
.embedded-stock-viewer .viewer-sidebar {
  display: flex;
  flex-direction: column;
  max-height: 620px;
  overflow: hidden;
}
.embedded-stock-viewer .viewer-controls-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.08fr) minmax(360px, .92fr);
}
.embedded-stock-viewer .viewer-search,
.embedded-stock-viewer .viewer-boards {
  padding: 10px 12px;
  border-bottom: 1px solid #edf0f5;
  background: #fbfcfe;
}
.embedded-stock-viewer .viewer-boards {
  border-left: 1px solid #edf0f5;
}
.embedded-stock-viewer .viewer-panel-title,
.embedded-stock-viewer .viewer-board-title,
.embedded-stock-viewer .viewer-list-head,
.embedded-stock-viewer .viewer-current {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
}
.embedded-stock-viewer .viewer-panel-title strong,
.embedded-stock-viewer .viewer-board-title strong {
  color: #172033;
  font-size: 13px;
}
.embedded-stock-viewer .viewer-panel-sub {
  color: #69748a;
  font-size: 12px;
  font-weight: 800;
}
.embedded-stock-viewer .viewer-collapse,
.embedded-stock-viewer .viewer-button,
.embedded-stock-viewer .viewer-mode,
.embedded-stock-viewer .viewer-chip,
.embedded-stock-viewer .viewer-board-chip,
.embedded-stock-viewer .viewer-add-board,
.embedded-stock-viewer .viewer-open-new,
.embedded-stock-viewer .viewer-danger {
  border: 1px solid #d9e0ea;
  background: #f7f9fc;
  color: #172033;
  cursor: pointer;
  font-size: 12px;
  font-weight: 900;
}
.embedded-stock-viewer .viewer-collapse,
.embedded-stock-viewer .viewer-mode,
.embedded-stock-viewer .viewer-chip,
.embedded-stock-viewer .viewer-board-chip {
  border-radius: 999px;
}
.embedded-stock-viewer .viewer-collapse {
  padding: 5px 9px;
  color: #2f6df6;
  background: #fff;
}
.embedded-stock-viewer .viewer-section-collapsed .viewer-section-body {
  display: none;
}
.embedded-stock-viewer .viewer-counts {
  display: none;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin: 8px 0 10px;
}
.embedded-stock-viewer .viewer-counts div {
  border: 1px solid #e3e9f2;
  background: #fff;
  padding: 8px;
}
.embedded-stock-viewer .viewer-counts span,
.embedded-stock-viewer .viewer-board-title span,
.embedded-stock-viewer .viewer-list-head {
  color: #69748a;
  font-size: 12px;
  font-weight: 900;
}
.embedded-stock-viewer .viewer-counts strong {
  display: block;
  margin-top: 2px;
  color: #172033;
  font-size: 17px;
}
.embedded-stock-viewer .viewer-search-row,
.embedded-stock-viewer .viewer-board-create {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  margin-top: 8px;
}
.embedded-stock-viewer .viewer-board-create {
  grid-template-columns: minmax(0, 1fr) auto auto;
}
.embedded-stock-viewer .viewer-search input,
.embedded-stock-viewer .viewer-board-create input {
  min-height: 36px;
  border: 1px solid #d9e0ea;
  background: #fff;
  color: #172033;
  padding: 0 10px;
  outline: none;
}
.embedded-stock-viewer .viewer-button,
.embedded-stock-viewer .viewer-board-create button,
.embedded-stock-viewer .viewer-danger {
  min-height: 36px;
  border-radius: 7px;
  padding: 0 12px;
}
.embedded-stock-viewer .viewer-board-create button {
  border: 1px solid #245ac0;
  background: #2f6df6;
  color: #fff;
  font-weight: 900;
}
.embedded-stock-viewer .viewer-danger {
  color: #b42318;
  background: #fff7f7;
  border-color: #f0c9c9;
}
.embedded-stock-viewer .viewer-modes,
.embedded-stock-viewer .viewer-chip-strip,
.embedded-stock-viewer .viewer-board-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}
.embedded-stock-viewer .viewer-chip-strip,
.embedded-stock-viewer .viewer-board-list {
  max-height: 58px;
  overflow: auto;
}
.embedded-stock-viewer .viewer-mode,
.embedded-stock-viewer .viewer-chip,
.embedded-stock-viewer .viewer-board-chip {
  min-height: 28px;
  padding: 0 9px;
}
.embedded-stock-viewer .viewer-mode.active,
.embedded-stock-viewer .viewer-chip.active,
.embedded-stock-viewer .viewer-board-chip.active {
  background: #2f6df6;
  color: #fff;
  border-color: #245ac0;
}
.embedded-stock-viewer .viewer-chip span,
.embedded-stock-viewer .viewer-board-chip span {
  margin-left: 4px;
  color: #69748a;
}
.embedded-stock-viewer .viewer-list-head {
  padding: 9px 12px;
  border-bottom: 1px solid #edf0f5;
}
.embedded-stock-viewer .viewer-list {
  display: grid;
  gap: 0;
  overflow: auto;
  padding: 0;
  max-height: 430px;
  min-height: 0;
  flex: 1 1 auto;
}
.embedded-stock-viewer .viewer-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 108px 300px;
  gap: 12px;
  align-items: center;
  border: 0;
  border-bottom: 1px solid #edf0f5;
  background: #fff;
  padding: 9px 12px;
  cursor: pointer;
}
.embedded-stock-viewer .viewer-row:hover,
.embedded-stock-viewer .viewer-row.active {
  background: #eef4ff;
  border-color: #9db5d8;
}
.embedded-stock-viewer .viewer-row strong {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #172033;
  font-size: 14px;
}
.embedded-stock-viewer .viewer-row small,
.embedded-stock-viewer .viewer-row em {
  display: block;
  margin-top: 2px;
  color: #69748a;
  font-size: 12px;
  font-style: normal;
}
.embedded-stock-viewer .viewer-row-metrics {
  min-width: 78px;
  text-align: right;
  font-weight: 900;
  line-height: 1.35;
}
.embedded-stock-viewer .viewer-row-metrics span {
  display: block;
}
.embedded-stock-viewer .viewer-row-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
  align-items: center;
}
.embedded-stock-viewer .viewer-row-actions select {
  min-height: 28px;
  max-width: 180px;
  border: 1px solid #d9e0ea;
  background: #fff;
  padding: 0 7px;
  color: #172033;
  font-size: 12px;
  font-weight: 900;
}
.embedded-stock-viewer .viewer-add-board,
.embedded-stock-viewer .viewer-open-new {
  min-height: 28px;
  display: inline-flex;
  align-items: center;
  padding: 0 8px;
  border-radius: 7px;
}
.embedded-stock-viewer .viewer-add-board.in-board {
  background: #fff4df;
  border-color: #efbf73;
  color: #7a4e00;
}
.embedded-stock-viewer .viewer-current {
  min-height: 44px;
  padding: 8px 12px;
  border-bottom: 1px solid #edf0f5;
  background: #fbfcfe;
}
.embedded-stock-viewer .viewer-current strong {
  display: block;
  color: #172033;
  font-size: 14px;
}
.embedded-stock-viewer .viewer-current span {
  display: block;
  margin-top: 3px;
  color: #69748a;
  font-size: 12px;
}
.embedded-stock-viewer .viewer-current .tone {
  font-size: 16px;
  font-weight: 900;
}
.embedded-stock-viewer .empty {
  color: #69748a;
  margin: 0;
}
.embedded-stock-viewer .up { color: #cf4446; }
.embedded-stock-viewer .down { color: #168457; }
.embedded-stock-viewer .flat { color: #69748a; }
@media (max-width: 980px) {
  .industry-market-overview-grid {
    grid-template-columns: 1fr;
  }
  .embedded-stock-viewer .viewer-controls-grid {
    grid-template-columns: 1fr;
  }
  .embedded-stock-viewer .viewer-row {
    grid-template-columns: minmax(0, 1fr);
  }
  .embedded-stock-viewer .viewer-row-actions {
    justify-content: flex-start;
  }
  .embedded-stock-viewer .viewer-boards {
    border-left: 0;
  }
  .embedded-stock-viewer .viewer-sidebar {
    max-height: 620px;
  }
  .ths-market-mode-switch {
    width: 100%;
  }
  .ths-market-mode-btn {
    flex: 1 1 0;
  }
}
"""


_INDUSTRY_MARKET_JS = """
function industryMarketEscape(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
function industryMarketPct(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return '--';
  return (num >= 0 ? '+' : '') + num.toFixed(2) + '%';
}
function industryMarketTone(value) {
  const num = Number(value);
  if (!Number.isFinite(num) || num === 0) return '';
  return num > 0 ? 'pos' : 'neg';
}
const THS_WATCH_KEY = 'quantyb:ths_market_watch_pool:v1';
function thsCurrentMode() {
  if (window._THS_MARKET_MODE === 'stock') return 'stock';
  if (window._THS_MARKET_MODE === 'watch') return 'watch';
  if (window._THS_MARKET_MODE === 'index') return 'index';
  return (window._THS_MARKET_MODE === 'concept') ? 'concept' : 'industry';
}
function thsModeLabel(mode) {
  if (mode === 'watch') return '关注';
  if (mode === 'index') return '指数';
  return mode === 'concept' ? '概念' : '行业';
}
function thsItemMode(mode) {
  return mode === 'concept' ? 'concept' : 'industry';
}
function thsWatchLoad() {
  try {
    const items = JSON.parse(localStorage.getItem(THS_WATCH_KEY) || '[]');
    return Array.isArray(items) ? items.filter(function(item) { return item && item.symbol && item.mode; }) : [];
  } catch (e) {
    return [];
  }
}
function thsWatchSave(items) {
  try { localStorage.setItem(THS_WATCH_KEY, JSON.stringify(items || [])); }
  catch (e) {}
}
function thsWatchId(mode, symbol) {
  return String(mode || 'industry') + ':' + String(symbol || '').toUpperCase();
}
function thsRowMeta(row) {
  const mode = thsCurrentMode() === 'watch' ? thsItemMode(row && row.dataset.thsMode) : thsCurrentMode();
  return {
    mode,
    symbol: String((row && (row.dataset.thsSymbol || row.dataset.industrySymbol)) || '').toUpperCase(),
    name: String((row && row.dataset.thsName) || ''),
  };
}
function thsIsWatched(mode, symbol) {
  const id = thsWatchId(mode, symbol);
  return thsWatchLoad().some(function(item) { return thsWatchId(item.mode, item.symbol) === id; });
}
function updateThsWatchUI() {
  const mode = thsCurrentMode();
  const items = thsWatchLoad();
  const chips = document.getElementById('ths-watch-pool-chips');
  document.querySelectorAll('#industry-market-table tbody tr[data-ths-symbol]').forEach(function(row) {
    const meta = thsRowMeta(row);
    const active = thsIsWatched(meta.mode, meta.symbol);
    row.classList.toggle('watched', active);
    const btn = row.querySelector('.ths-watch-btn');
    if (btn) {
      btn.classList.toggle('active', active);
      btn.textContent = active ? '★' : '☆';
      btn.title = active ? '移出关注池' : '加入关注池';
    }
  });
  if (!chips) return;
  if (!items.length) {
    chips.innerHTML = '<span class="ths-watch-empty">暂无关注</span>';
    return;
  }
  chips.innerHTML = items.map(function(item) {
    const itemMode = item.mode === 'concept' ? 'concept' : 'industry';
    const symbol = String(item.symbol || '').toUpperCase();
    const name = industryMarketEscape(item.name || symbol);
    const active = (mode === 'watch' || itemMode === mode) ? ' active' : '';
    return '<span class="ths-watch-chip' + active + '" onclick="switchThsWatchItem(\\'' + itemMode + '\\', \\'' + industryMarketEscape(symbol) + '\\')">'
      + '<small>' + thsModeLabel(itemMode) + '</small><span>' + name + '</span>'
      + '<button type="button" title="移除" onclick="removeThsWatch(\\'' + itemMode + '\\', \\'' + industryMarketEscape(symbol) + '\\', event)">×</button>'
      + '</span>';
  }).join('');
}
function refreshThsWatchModeIfActive() {
  if (thsCurrentMode() === 'watch' && typeof window.switchThsMarketMode === 'function') {
    window.switchThsMarketMode('watch');
    return true;
  }
  return false;
}
function toggleThsWatch(symbol, event) {
  if (event && typeof event.stopPropagation === 'function') event.stopPropagation();
  const normalized = String(symbol || '').toUpperCase();
  const row = document.querySelector('#industry-market-table tbody tr[data-ths-symbol="' + normalized + '"]');
  const meta = thsRowMeta(row);
  if (!meta.symbol) return;
  const id = thsWatchId(meta.mode, meta.symbol);
  const items = thsWatchLoad();
  const existing = items.findIndex(function(item) { return thsWatchId(item.mode, item.symbol) === id; });
  if (existing >= 0) items.splice(existing, 1);
  else items.push(meta);
  thsWatchSave(items);
  if (refreshThsWatchModeIfActive()) return;
  updateThsWatchUI();
  filterThsMarketRows();
}
function removeThsWatch(mode, symbol, event) {
  if (event && typeof event.stopPropagation === 'function') event.stopPropagation();
  const id = thsWatchId(mode, symbol);
  thsWatchSave(thsWatchLoad().filter(function(item) { return thsWatchId(item.mode, item.symbol) !== id; }));
  if (refreshThsWatchModeIfActive()) return;
  updateThsWatchUI();
  filterThsMarketRows();
}
function switchThsWatchItem(mode, symbol) {
  const normalizedMode = mode === 'concept' ? 'concept' : 'industry';
  const normalizedSymbol = String(symbol || '').toUpperCase();
  if (thsCurrentMode() === 'watch') {
    const row = document.querySelector('#industry-market-table tbody tr[data-ths-symbol="' + normalizedSymbol + '"][data-ths-mode="' + normalizedMode + '"]')
      || document.querySelector('#industry-market-table tbody tr[data-ths-symbol="' + normalizedSymbol + '"]');
    if (row) row.scrollIntoView({behavior: 'smooth', block: 'center'});
    selectIndustryMarketRow(normalizedSymbol);
    return;
  }
  if (normalizedMode !== thsCurrentMode()) {
    window._THS_PENDING_WATCH_SYMBOL = normalizedSymbol;
    if (typeof window.switchThsMarketMode === 'function') window.switchThsMarketMode(normalizedMode);
    return;
  }
  const row = document.querySelector('#industry-market-table tbody tr[data-ths-symbol="' + normalizedSymbol + '"]');
  if (row) row.scrollIntoView({behavior: 'smooth', block: 'center'});
  selectIndustryMarketRow(normalizedSymbol);
}
function filterThsMarketRows() {
  const input = document.getElementById('ths-market-search');
  const status = document.getElementById('ths-market-filter-status');
  const query = String((input && input.value) || '').trim().toLowerCase();
  const onlyWatch = !!window._THS_WATCH_ONLY;
  const rows = Array.from(document.querySelectorAll('#industry-market-table tbody tr[data-ths-symbol]'));
  let visible = 0;
  rows.forEach(function(row) {
    const symbol = String(row.dataset.thsSymbol || '').toUpperCase();
    const rowMode = thsCurrentMode() === 'watch' ? thsItemMode(row.dataset.thsMode) : thsCurrentMode();
    const searchText = String(row.dataset.thsSearch || '').toLowerCase();
    const matchQuery = !query || searchText.indexOf(query) >= 0 || symbol.toLowerCase().indexOf(query) >= 0;
    const matchWatch = !onlyWatch || thsIsWatched(rowMode, symbol);
    const show = matchQuery && matchWatch;
    row.classList.toggle('industry-market-row-hidden', !show);
    if (show) visible += 1;
  });
  if (status) status.textContent = rows.length ? ('显示 ' + visible + '/' + rows.length) : '暂无数据';
}
function clearThsMarketSearch() {
  const input = document.getElementById('ths-market-search');
  if (input) {
    input.value = '';
    input.focus();
  }
  filterThsMarketRows();
}
function toggleThsWatchOnly() {
  window._THS_WATCH_ONLY = !window._THS_WATCH_ONLY;
  const btn = document.getElementById('ths-watch-only-btn');
  if (btn) btn.classList.toggle('active', !!window._THS_WATCH_ONLY);
  filterThsMarketRows();
}
function industryMemberSortValue(item, key) {
  if (key === 'name') return item.name || '';
  if (key === 'price') return Number(item.price_num);
  if (key === 'pct_chg') return Number(item.pct_chg);
  if (key === 'turnover_rate') return Number(item.turnover_rate);
  if (key === 'amount_1d') return Number(item.amount_1d);
  if (key === 'market_cap') return Number(item.market_cap);
  if (key === 'pe_ttm') return Number(item.pe_ttm || item.pe);
  if (key === 'pb') return Number(item.pb);
  return item[key] || '';
}
function sortedIndustryMembers(members) {
  const state = window._INDUSTRY_MEMBER_SORT || {key:'pct_chg', direction:'desc'};
  const key = state.key || 'pct_chg';
  const direction = state.direction || 'desc';
  return members.slice().sort(function(a, b) {
    const av = industryMemberSortValue(a, key);
    const bv = industryMemberSortValue(b, key);
    const an = Number(av);
    const bn = Number(bv);
    let result = 0;
    if (Number.isFinite(an) && Number.isFinite(bn)) result = an - bn;
    else if (Number.isFinite(an)) result = 1;
    else if (Number.isFinite(bn)) result = -1;
    else result = String(av || '').localeCompare(String(bv || ''), 'zh-Hans-CN');
    return direction === 'asc' ? result : -result;
  });
}
function sortIndustryMembers(key, explicitDirection) {
  const state = window._INDUSTRY_MEMBER_SORT || {key:'pct_chg', direction:'desc'};
  const direction = explicitDirection || (state.key === key && state.direction === 'desc' ? 'asc' : 'desc');
  window._INDUSTRY_MEMBER_SORT = {key, direction};
  renderIndustryMembers(window._CURRENT_INDUSTRY_MEMBER_SYMBOL || window._PRIMARY_INDUSTRY_INDEX || '');
}
function findIndustryStockMember(symbol) {
  const normalized = String(symbol || '').toUpperCase();
  const membersRoot = window._INDUSTRY_MEMBERS || {};
  const currentEntry = membersRoot[window._CURRENT_INDUSTRY_MEMBER_SYMBOL || ''] || {};
  const currentMembers = Array.isArray(currentEntry.members) ? currentEntry.members : [];
  let found = currentMembers.find(function(item) { return String(item.symbol || '').toUpperCase() === normalized; });
  if (found) return found;
  for (const entry of Object.values(membersRoot)) {
    const members = Array.isArray(entry && entry.members) ? entry.members : [];
    found = members.find(function(item) { return String(item.symbol || '').toUpperCase() === normalized; });
    if (found) return found;
  }
  return null;
}
function industryStockBarColor(data, index) {
  const item = data && data[index];
  if (!item || item.length < 2) return '#c8d2df';
  return Number(item[1]) >= Number(item[0]) ? '#d84a4a' : '#1b8a5a';
}
function industryStockCurrentPeriod() {
  return window._CURRENT_INDUSTRY_STOCK_PERIOD || '1d';
}
function industryStockTimeframe(entry) {
  const payload = entry || {};
  const frames = payload.timeframes || {};
  const period = industryStockCurrentPeriod();
  return frames[period] || frames['1d'] || payload;
}
function industryStockKlineOption(entry) {
  const data = industryStockTimeframe(entry);
  const dates = data.dates || [];
  const ohlc = data.ohlc || [];
  const period = industryStockCurrentPeriod();
  const visibleBars = period === '1w' ? 156 : period === '1m' ? 36 : 760;
  const start = dates.length > visibleBars ? Math.max(0, ((dates.length - visibleBars) / dates.length) * 100) : 0;
  const volume = data.volume || [];
  const amount = data.amount || [];
  return {
    animation: false,
    color: ['#4b72d9', '#b8d927', '#41476b', '#c17628', '#26a6d1', '#f6c34a', '#2aa9b5', '#f4bf3f', '#ef6f8a'],
    legend: {top: 10, data: ['K线','MA5','MA10','MA20','MA60','BOLL','成交量','成交额'], selected: {'BOLL': true}},
    tooltip: {trigger: 'axis', axisPointer: {type: 'cross'}},
    axisPointer: {link: [{xAxisIndex: 'all'}]},
    grid: [
      {left: 58, right: 28, top: 58, height: '58%'},
      {left: 58, right: 28, top: '70%', height: '10%'},
      {left: 58, right: 28, top: '84%', height: '10%'}
    ],
    xAxis: [
      {type: 'category', data: dates, scale: true, boundaryGap: false, axisLine: {onZero: false}, splitLine: {show: true, lineStyle: {color: '#edf2f7', type: 'dashed'}}, axisLabel: {color: '#6b778c'}},
      {type: 'category', data: dates, gridIndex: 1, scale: true, boundaryGap: false, axisLabel: {show: false}, axisLine: {onZero: false}, splitLine: {show: true, lineStyle: {color: '#edf2f7', type: 'dashed'}}},
      {type: 'category', data: dates, gridIndex: 2, scale: true, boundaryGap: false, axisLabel: {color: '#6b778c'}, axisLine: {onZero: false}, splitLine: {show: true, lineStyle: {color: '#edf2f7', type: 'dashed'}}}
    ],
    yAxis: [
      {scale: true, splitLine: {show: true, lineStyle: {color: '#edf2f7', type: 'dashed'}}, axisLabel: {color: '#6b778c'}},
      {scale: true, gridIndex: 1, name: '成交量', splitLine: {show: true, lineStyle: {color: '#edf2f7', type: 'dashed'}}, axisLabel: {color: '#6b778c'}},
      {scale: true, gridIndex: 2, name: '成交额', splitLine: {show: true, lineStyle: {color: '#edf2f7', type: 'dashed'}}, axisLabel: {color: '#6b778c'}}
    ],
    dataZoom: [
      {type: 'inside', xAxisIndex: [0,1,2], start, end: 100, zoomOnMouseWheel: true, moveOnMouseWheel: true},
      {type: 'slider', xAxisIndex: [0,1,2], start, end: 100, bottom: 4, height: 22}
    ],
    series: [
      {name: 'K线', type: 'candlestick', data: ohlc, itemStyle: {color: '#d84a4a', color0: '#1b8a5a', borderColor: '#d84a4a', borderColor0: '#1b8a5a'}},
      {name: 'MA5', type: 'line', data: data.ma5 || [], smooth: true, showSymbol: false, lineStyle: {width: 1.5}},
      {name: 'MA10', type: 'line', data: data.ma10 || [], smooth: true, showSymbol: false, lineStyle: {width: 1.5}},
      {name: 'MA20', type: 'line', data: data.ma20 || [], smooth: true, showSymbol: false, lineStyle: {width: 1.5}},
      {name: 'MA60', type: 'line', data: data.ma60 || [], smooth: true, showSymbol: false, lineStyle: {width: 1.5}},
      {name: 'BOLL上轨', type: 'line', data: data.boll_upper || [], smooth: true, showSymbol: false, lineStyle: {width: 1.1, type: 'dashed'}},
      {name: 'BOLL中轨', type: 'line', data: data.boll_mid || [], smooth: true, showSymbol: false, lineStyle: {width: 1.1, type: 'dashed'}},
      {name: 'BOLL下轨', type: 'line', data: data.boll_lower || [], smooth: true, showSymbol: false, lineStyle: {width: 1.1, type: 'dashed'}},
      {name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: volume, itemStyle: {color: function(params) { return industryStockBarColor(ohlc, params.dataIndex); }}},
      {name: '成交额', type: 'bar', xAxisIndex: 2, yAxisIndex: 2, data: amount, itemStyle: {color: function(params) { return industryStockBarColor(ohlc, params.dataIndex); }}}
    ]
  };
}
function bindIndustryStockLegendGroups(chart) {
  if (!chart) return;
  chart.off('legendselectchanged');
  chart.on('legendselectchanged', function(params) {
    if (!params || params.name !== 'BOLL') return;
    const action = params.selected && params.selected.BOLL ? 'legendSelect' : 'legendUnSelect';
    ['BOLL上轨', 'BOLL中轨', 'BOLL下轨'].forEach(function(name) {
      chart.dispatchAction({type: action, name: name});
    });
  });
}
function industryStockDrawingKey(symbol) {
  return 'quantyb:stock_kline_drawings:' + String(symbol || '').toUpperCase() + ':' + industryStockCurrentPeriod();
}
function industryStockLoadLines(symbol) {
  try { return JSON.parse(localStorage.getItem(industryStockDrawingKey(symbol)) || '[]') || []; }
  catch (e) { return []; }
}
function industryStockSaveLines(symbol, lines) {
  try { localStorage.setItem(industryStockDrawingKey(symbol), JSON.stringify(lines || [])); }
  catch (e) {}
}
const industryStockDraw = {mode: 'select', pending: null, selected: null, drag: null, bound: false};
function industryStockLineColor(type) {
  if (type === 'support') return '#16a34a';
  if (type === 'resistance') return '#dc2626';
  return '#2563eb';
}
function industryStockSetStatus(text) {
  const status = document.getElementById('industry-stock-drawing-status');
  if (status) status.textContent = text || '';
}
function industryStockSetDrawMode(mode) {
  industryStockDraw.mode = mode || 'select';
  industryStockDraw.pending = null;
  document.querySelectorAll('[data-industry-stock-draw]').forEach(function(btn) {
    btn.classList.toggle('active', (btn.getAttribute('data-industry-stock-draw') || 'select') === industryStockDraw.mode);
  });
  const svg = document.getElementById('industry-stock-drawing-layer');
  if (svg) svg.classList.toggle('active', industryStockDraw.mode !== 'select');
  if (industryStockDraw.mode === 'trend') industryStockSetStatus('趋势线：在个股 K 线图点两个位置；完成后可拖动两端调整。');
  else if (industryStockDraw.mode === 'support') industryStockSetStatus('支撑线：点一个价格生成水平线；之后可上下拖动。');
  else if (industryStockDraw.mode === 'resistance') industryStockSetStatus('阻力线：点一个价格生成水平线；之后可上下拖动。');
  else industryStockSetStatus('选择/调整：拖动线或端点微调；画线按当前周期本地保存。');
}
function industryStockAddSvg(tag, attrs) {
  const svg = document.getElementById('industry-stock-drawing-layer');
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  Object.keys(attrs || {}).forEach(function(key) { node.setAttribute(key, attrs[key]); });
  if (svg) svg.appendChild(node);
  return node;
}
function industryStockPointFromEvent(evt) {
  const chart = window._INDUSTRY_STOCK_KLINE_CHART;
  const svg = document.getElementById('industry-stock-drawing-layer');
  const payload = (window._INDUSTRY_STOCK_KLINES || {})[window._CURRENT_INDUSTRY_STOCK_SYMBOL || ''] || {};
  const dates = industryStockTimeframe(payload).dates || [];
  if (!chart || !svg) return {x: 0, y: 0, px: 0, py: 0};
  const rect = svg.getBoundingClientRect();
  const px = evt.clientX - rect.left;
  const py = evt.clientY - rect.top;
  const point = chart.convertFromPixel({xAxisIndex: 0, yAxisIndex: 0}, [px, py]) || [0, 0];
  const max = Math.max(0, dates.length - 1);
  return {x: Math.max(0, Math.min(max, Math.round(Number(point[0]) || 0))), y: Number(point[1]) || 0, px, py};
}
function industryStockRenderDrawings() {
  const chart = window._INDUSTRY_STOCK_KLINE_CHART;
  const svg = document.getElementById('industry-stock-drawing-layer');
  const symbol = window._CURRENT_INDUSTRY_STOCK_SYMBOL || '';
  const payload = (window._INDUSTRY_STOCK_KLINES || {})[symbol] || {};
  const dates = industryStockTimeframe(payload).dates || [];
  if (!chart || !svg || !symbol || !dates.length) return;
  svg.innerHTML = '';
  const rect = svg.getBoundingClientRect();
  svg.setAttribute('viewBox', '0 0 ' + rect.width + ' ' + rect.height);
  const max = Math.max(0, dates.length - 1);
  const lines = industryStockLoadLines(symbol);
  lines.forEach(function(line, idx) {
    if (line.type === 'support' || line.type === 'resistance') {
      line.x1 = 0;
      line.x2 = max;
      line.y2 = line.y1;
    }
    const p1 = chart.convertToPixel({xAxisIndex: 0, yAxisIndex: 0}, [line.x1, line.y1]);
    const p2 = chart.convertToPixel({xAxisIndex: 0, yAxisIndex: 0}, [line.x2, line.y2]);
    if (!p1 || !p2 || !Number.isFinite(p1[0]) || !Number.isFinite(p1[1]) || !Number.isFinite(p2[0]) || !Number.isFinite(p2[1])) return;
    const color = industryStockLineColor(line.type);
    const selected = industryStockDraw.selected === line.id;
    const lineNode = industryStockAddSvg('line', {
      x1: p1[0], y1: p1[1], x2: p2[0], y2: p2[1],
      stroke: color, 'stroke-width': selected ? 3 : 2,
      'stroke-dasharray': line.type === 'trend' ? '' : '8 4',
      class: 'industry-stock-manual-line', 'data-id': line.id
    });
    lineNode.addEventListener('pointerdown', function(e) {
      e.stopPropagation();
      industryStockDraw.selected = line.id;
      industryStockDraw.drag = {kind: line.type === 'trend' ? 'move' : 'horizontal', id: line.id, start: industryStockPointFromEvent(e), orig: JSON.parse(JSON.stringify(line))};
      svg.setPointerCapture(e.pointerId);
      industryStockRenderDrawings();
    });
    industryStockAddSvg('text', {x: p2[0] + 6, y: p2[1] - 6, fill: color, class: 'industry-stock-manual-label'})
      .textContent = (line.type === 'support' ? '支撑' : line.type === 'resistance' ? '阻力' : '趋势') + ' ' + (idx + 1);
    [['start', p1], ['end', p2]].forEach(function(pair) {
      if ((line.type === 'support' || line.type === 'resistance') && pair[0] === 'start') return;
      const handle = industryStockAddSvg('circle', {
        cx: pair[1][0], cy: pair[1][1], r: selected ? 6 : 5,
        fill: '#fff', stroke: color, 'stroke-width': 2,
        class: 'industry-stock-manual-handle', 'data-id': line.id, 'data-point': pair[0]
      });
      handle.addEventListener('pointerdown', function(e) {
        e.stopPropagation();
        industryStockDraw.selected = line.id;
        industryStockDraw.drag = {kind: line.type === 'trend' ? pair[0] : 'horizontal', id: line.id, start: industryStockPointFromEvent(e), orig: JSON.parse(JSON.stringify(line))};
        svg.setPointerCapture(e.pointerId);
        industryStockRenderDrawings();
      });
    });
  });
}
function industryStockSetLines(lines) {
  industryStockSaveLines(window._CURRENT_INDUSTRY_STOCK_SYMBOL || '', lines);
  industryStockRenderDrawings();
}
function industryStockUpdateDrag(evt) {
  if (!industryStockDraw.drag) return;
  const symbol = window._CURRENT_INDUSTRY_STOCK_SYMBOL || '';
  const payload = (window._INDUSTRY_STOCK_KLINES || {})[symbol] || {};
  const dates = industryStockTimeframe(payload).dates || [];
  const point = industryStockPointFromEvent(evt);
  const lines = industryStockLoadLines(symbol);
  const line = lines.find(function(item) { return item.id === industryStockDraw.drag.id; });
  if (!line) return;
  if (industryStockDraw.drag.kind === 'start') {
    line.x1 = point.x;
    line.y1 = point.y;
  } else if (industryStockDraw.drag.kind === 'end') {
    line.x2 = point.x;
    line.y2 = point.y;
  } else if (industryStockDraw.drag.kind === 'horizontal') {
    line.y1 = point.y;
    line.y2 = point.y;
  } else if (industryStockDraw.drag.kind === 'move') {
    const dx = point.x - industryStockDraw.drag.start.x;
    const dy = point.y - industryStockDraw.drag.start.y;
    const orig = industryStockDraw.drag.orig;
    const max = Math.max(0, dates.length - 1);
    line.x1 = Math.max(0, Math.min(max, Math.round(orig.x1 + dx)));
    line.x2 = Math.max(0, Math.min(max, Math.round(orig.x2 + dx)));
    line.y1 = orig.y1 + dy;
    line.y2 = orig.y2 + dy;
  }
  industryStockSetLines(lines);
}
function industryStockFinishDrag() {
  industryStockDraw.drag = null;
}
function industryStockClickDraw(evt) {
  if (industryStockDraw.drag || industryStockDraw.mode === 'select') return;
  const symbol = window._CURRENT_INDUSTRY_STOCK_SYMBOL || '';
  const payload = (window._INDUSTRY_STOCK_KLINES || {})[symbol] || {};
  const dates = industryStockTimeframe(payload).dates || [];
  if (!symbol || !dates.length) return;
  const point = industryStockPointFromEvent(evt);
  const lines = industryStockLoadLines(symbol);
  const max = Math.max(0, dates.length - 1);
  if (industryStockDraw.mode === 'support' || industryStockDraw.mode === 'resistance') {
    lines.push({id: String(Date.now()) + '_' + Math.random().toString(16).slice(2), type: industryStockDraw.mode, x1: 0, x2: max, y1: point.y, y2: point.y});
    industryStockDraw.selected = lines[lines.length - 1].id;
    industryStockSetLines(lines);
    industryStockSetDrawMode('select');
    return;
  }
  if (industryStockDraw.mode === 'trend') {
    if (!industryStockDraw.pending) {
      industryStockDraw.pending = point;
      industryStockSetStatus('趋势线：再点第二个位置完成。');
      return;
    }
    lines.push({id: String(Date.now()) + '_' + Math.random().toString(16).slice(2), type: 'trend', x1: industryStockDraw.pending.x, y1: industryStockDraw.pending.y, x2: point.x, y2: point.y});
    industryStockDraw.pending = null;
    industryStockDraw.selected = lines[lines.length - 1].id;
    industryStockSetLines(lines);
    industryStockSetDrawMode('select');
  }
}
function industryStockUndoDrawing() {
  const symbol = window._CURRENT_INDUSTRY_STOCK_SYMBOL || '';
  const lines = industryStockLoadLines(symbol);
  lines.pop();
  industryStockSetLines(lines);
}
function industryStockClearDrawings() {
  if (!window.confirm || confirm('清空当前股票日K的手动画线？')) industryStockSetLines([]);
}
function bindIndustryStockDrawingLayer() {
  const chart = window._INDUSTRY_STOCK_KLINE_CHART;
  const svg = document.getElementById('industry-stock-drawing-layer');
  if (!chart || !svg || industryStockDraw.bound) return;
  industryStockDraw.bound = true;
  svg.addEventListener('pointerdown', industryStockClickDraw);
  svg.addEventListener('pointermove', industryStockUpdateDrag);
  svg.addEventListener('pointerup', industryStockFinishDrag);
  svg.addEventListener('pointercancel', industryStockFinishDrag);
  chart.on('dataZoom', function() { setTimeout(industryStockRenderDrawings, 0); });
  chart.on('finished', industryStockRenderDrawings);
  window.addEventListener('resize', function() { setTimeout(industryStockRenderDrawings, 0); });
  industryStockSetDrawMode('select');
}
function industryStockSetPeriodButtons(period) {
  document.querySelectorAll('[data-industry-stock-period]').forEach(function(btn) {
    btn.classList.toggle('active', (btn.getAttribute('data-industry-stock-period') || '1d') === period);
  });
}
function switchIndustryStockPeriod(period) {
  window._CURRENT_INDUSTRY_STOCK_PERIOD = period || '1d';
  industryStockSetPeriodButtons(industryStockCurrentPeriod());
  const symbol = window._CURRENT_INDUSTRY_STOCK_SYMBOL || '';
  if (!symbol) return;
  const item = findIndustryStockMember(symbol) || window._CURRENT_STOCK_VIEWER_ITEM || null;
  renderIndustryStockKline(symbol, item);
}
function renderIndustryStockKline(symbol, item) {
  const normalized = String(symbol || '').toUpperCase();
  const payload = (window._INDUSTRY_STOCK_KLINES || {})[normalized];
  const data = industryStockTimeframe(payload);
  const chartNode = document.getElementById('industry-stock-kline');
  const emptyNode = document.getElementById('industry-stock-kline-empty');
  const label = document.getElementById('industry-stock-kline-label');
  if (label) label.textContent = ((item && item.name) || (payload && payload.name) || '股票') + ' ' + normalized + ' · 个股K线';
  if (!chartNode) return false;
  industryStockSetPeriodButtons(industryStockCurrentPeriod());
  if (!payload || !data.dates || !data.dates.length) {
    chartNode.style.display = 'none';
    if (emptyNode) {
      emptyNode.style.display = 'block';
      emptyNode.innerHTML = '当前股票缺少可直接渲染的本地K线缓存。可先运行每日数据刷新，或打开单独个股 K 线页查看已有文件。';
    }
    return false;
  }
  if (emptyNode) emptyNode.style.display = 'none';
  chartNode.style.display = '';
  if (!window._INDUSTRY_STOCK_KLINE_CHART) {
    window._INDUSTRY_STOCK_KLINE_CHART = echarts.init(chartNode);
    window.addEventListener('resize', function() {
      if (window._INDUSTRY_STOCK_KLINE_CHART) window._INDUSTRY_STOCK_KLINE_CHART.resize();
    });
  }
  window._INDUSTRY_STOCK_KLINE_CHART.setOption(industryStockKlineOption(payload), true);
  bindIndustryStockLegendGroups(window._INDUSTRY_STOCK_KLINE_CHART);
  bindIndustryStockDrawingLayer();
  setTimeout(function() {
    if (window._INDUSTRY_STOCK_KLINE_CHART) window._INDUSTRY_STOCK_KLINE_CHART.resize();
    industryStockRenderDrawings();
  }, 0);
  return true;
}
function loadIndustryStockKlineData(symbol, item) {
  const normalized = String(symbol || '').toUpperCase();
  window._INDUSTRY_STOCK_KLINES = window._INDUSTRY_STOCK_KLINES || {};
  if (window._INDUSTRY_STOCK_KLINES[normalized]) {
    renderIndustryStockKline(normalized, item);
    return;
  }
  const href = item && item.stock_data_href;
  if (!href) {
    renderIndustryStockKline(normalized, item);
    return;
  }
  window._INDUSTRY_STOCK_KLINE_LOADING = window._INDUSTRY_STOCK_KLINE_LOADING || {};
  if (window._INDUSTRY_STOCK_KLINE_LOADING[normalized]) {
    setTimeout(function() { loadIndustryStockKlineData(normalized, item); }, 80);
    return;
  }
  window._INDUSTRY_STOCK_KLINE_LOADING[normalized] = true;
  const script = document.createElement('script');
  script.src = href;
  script.async = true;
  script.onload = function() {
    window._INDUSTRY_STOCK_KLINE_LOADING[normalized] = false;
    renderIndustryStockKline(normalized, item);
  };
  script.onerror = function() {
    window._INDUSTRY_STOCK_KLINE_LOADING[normalized] = false;
    renderIndustryStockKline(normalized, item);
  };
  document.head.appendChild(script);
}
function showIndustryIndexKline() {
  const stockShell = document.getElementById('industry-stock-kline-shell');
  const kline = document.getElementById('industry-kline');
  const indicator = document.getElementById('industry-indicator');
  const toolbar = document.querySelector('.industry-manual-toolbar');
  const title = document.getElementById('industry-kline-title');
  const label = window._THS_MARKET_LABEL || '行业';
  if (stockShell) stockShell.style.display = 'none';
  if (kline) kline.style.display = '';
  if (indicator) indicator.style.display = '';
  if (toolbar) toolbar.style.display = '';
  if (title) title.textContent = '点击上方' + label + '行查看K线';
  document.querySelectorAll('.industry-member-stock-row').forEach(function(row) { row.classList.remove('active'); });
  if (typeof renderIndustryKline === 'function') renderIndustryKline();
  setTimeout(function() { window.dispatchEvent(new Event('resize')); }, 0);
}
function restoreIndustryIndexKline() {
  const symbol = window._CURRENT_INDUSTRY_MEMBER_SYMBOL || window._PRIMARY_INDUSTRY_INDEX || '';
  showIndustryIndexKline();
  if (symbol && typeof window.switchIndustryKline === 'function') window.switchIndustryKline(symbol);
}
function selectIndustryStockKline(symbol, event) {
  if (event) event.stopPropagation();
  const item = findIndustryStockMember(symbol);
  if (!item) return;
  window._CURRENT_INDUSTRY_STOCK_SYMBOL = String(item.symbol || '').toUpperCase();
  const stockShell = document.getElementById('industry-stock-kline-shell');
  const kline = document.getElementById('industry-kline');
  const indicator = document.getElementById('industry-indicator');
  const toolbar = document.querySelector('.industry-manual-toolbar');
  const title = document.getElementById('industry-kline-title');
  if (kline) kline.style.display = 'none';
  if (indicator) indicator.style.display = 'none';
  if (toolbar) toolbar.style.display = 'none';
  if (stockShell) stockShell.style.display = 'block';
  if (title) title.textContent = (item.name || '股票') + '（' + (item.symbol || '') + '） · 个股K线';
  loadIndustryStockKlineData(window._CURRENT_INDUSTRY_STOCK_SYMBOL, item);
  document.querySelectorAll('.industry-member-stock-row').forEach(function(row) {
    row.classList.toggle('active', row.getAttribute('data-stock-symbol') === window._CURRENT_INDUSTRY_STOCK_SYMBOL);
  });
  const target = document.getElementById('industry-stock-kline-shell');
  if (target) target.scrollIntoView({behavior:'smooth', block:'start'});
}
function renderIndustryMembers(symbol) {
  const membersRoot = window._INDUSTRY_MEMBERS || {};
  const normalizedSymbol = String(symbol || '').toUpperCase();
  window._CURRENT_INDUSTRY_MEMBER_SYMBOL = normalizedSymbol;
  const entry = membersRoot[normalizedSymbol] || {};
  const title = document.getElementById('industry-member-title');
  const sub = document.getElementById('industry-member-sub');
  const list = document.getElementById('industry-member-list');
  if (!list) return;
  const members = Array.isArray(entry.members) ? entry.members : [];
  if (title) title.textContent = (entry.industry || window._THS_MARKET_LABEL || '行业') + ' 成分股';
  const sortState = window._INDUSTRY_MEMBER_SORT || {key:'pct_chg', direction:'desc'};
  const sortName = {name:'名称', price:'股价', pct_chg:'日涨幅', turnover_rate:'换手率', amount_1d:'成交额', market_cap:'市值', pe_ttm:'PE', pb:'PB'}[sortState.key] || '日涨幅';
  const sourceLabel = entry.source || '成分来源';
  const quoteLabel = entry.quote_source || '行情来源';
  if (sub) sub.textContent = members.length ? `${sourceLabel} ${members.length} 只，${quoteLabel}，按${sortName}${sortState.direction === 'asc' ? '升序' : '降序'}` : `${sourceLabel} 暂无匹配成分`;
  document.querySelectorAll('.industry-row-clickable').forEach(function(row) {
    row.classList.toggle('active', row.getAttribute('data-industry-symbol') === normalizedSymbol);
  });
  if (!members.length) {
    list.innerHTML = '<div class="industry-member-empty">' + industryMarketEscape(window._THS_MEMBER_EMPTY_MESSAGE || '当前板块没有可用成分股。') + '</div>';
    return;
  }
  const headers = [
    ['name','股票',''],
    ['price','股价','num'],
    ['pct_chg','日涨幅','num'],
    ['turnover_rate','换手','num'],
    ['amount_1d','成交额','num'],
    ['market_cap','市值','num'],
    ['pe_ttm','PE','num'],
    ['pb','PB','num'],
    ['kline','K线','']
  ].map(function(col) {
    const key = col[0], label = col[1], cls = col[2] || '';
    const sortable = key !== 'kline';
    const sorted = sortState.key === key;
    const mark = sorted ? (sortState.direction === 'asc' ? '↑' : '↓') : '';
    return '<th class="' + cls + (sortable ? ' sortable' : '') + (sorted ? ' sorted' : '') + '" data-member-key="' + key + '" data-sort-mark="' + mark + '"' + (sortable ? ' onclick="sortIndustryMembers(\\'' + key + '\\')"' : '') + '>' + label + '</th>';
  }).join('');
  const rows = sortedIndustryMembers(members).map(function(item) {
    const kline = item.kline_available
      ? '<button class="industry-member-kline" type="button" onclick="selectIndustryStockKline(\\'' + industryMarketEscape(item.symbol || '') + '\\', event)">K线</button>'
      : '<span class="industry-member-kline missing">无K线</span>';
    const pct = industryMarketPct(item.pct_chg);
    const pe = item.pe_ttm_text || item.pe_text || '--';
    return '<tr class="industry-member-stock-row" data-stock-symbol="' + industryMarketEscape(String(item.symbol || '').toUpperCase()) + '" onclick="selectIndustryStockKline(\\'' + industryMarketEscape(item.symbol || '') + '\\', event)">'
      + '<td><div class="industry-member-name">' + industryMarketEscape(item.name || '--') + '</div><div class="industry-member-code">' + industryMarketEscape(item.symbol || '') + '</div><div class="industry-member-meta">' + industryMarketEscape(item.industry_path || '--') + '</div></td>'
      + '<td class="num industry-member-price">' + industryMarketEscape(item.price == null ? '--' : item.price) + '</td>'
      + '<td class="num ' + industryMarketTone(item.pct_chg) + '">' + pct + '</td>'
      + '<td class="num">' + industryMarketEscape(item.turnover_rate_text || '--') + '</td>'
      + '<td class="num">' + industryMarketEscape(item.amount_1d_text || '--') + '</td>'
      + '<td class="num">' + industryMarketEscape(item.market_cap_text || '--') + '</td>'
      + '<td class="num">' + industryMarketEscape(pe) + '</td>'
      + '<td class="num">' + industryMarketEscape(item.pb_text || '--') + '</td>'
      + '<td>' + kline + '</td>'
      + '</tr>';
  }).join('');
  list.innerHTML = '<table class="industry-member-table"><thead><tr>' + headers + '</tr></thead><tbody>' + rows + '</tbody></table>';
}
function selectIndustryMarketRow(symbol) {
  const normalized = String(symbol || '').toUpperCase();
  showIndustryIndexKline();
  if (window._INDUSTRY_KLINES && window._INDUSTRY_KLINES[normalized] && typeof window.switchIndustryKline === 'function') {
    window.switchIndustryKline(normalized);
  } else {
    renderIndustryMembers(normalized);
  }
}
function sortIndustryMarketTable(key, explicitDirection, event) {
  if (event && typeof event.stopPropagation === 'function') event.stopPropagation();
  const table = document.getElementById('industry-market-table');
  if (!table) return;
  const tbody = table.querySelector('tbody');
  const headers = Array.from(table.querySelectorAll('th.sortable[data-key], .industry-sort-chip[data-key]'));
  const currentKey = table.dataset.sortKey || '';
  const currentDirection = table.dataset.sortDirection || 'desc';
  const direction = explicitDirection || (currentKey === key && currentDirection === 'desc' ? 'asc' : 'desc');
  table.dataset.sortKey = key;
  table.dataset.sortDirection = direction;
  headers.forEach((item) => {
    item.classList.toggle('sorted', item.dataset.key === key);
    item.dataset.sortMark = item.dataset.key === key ? (direction === 'asc' ? '↑' : '↓') : '';
  });
  const rows = Array.from(tbody.querySelectorAll('tr'));
  const parse = (row) => {
    const cell = row.querySelector(`[data-sort-key="${key}"]`);
    if (!cell) return '';
    const raw = cell.dataset.sortValue ?? cell.textContent ?? '';
    const num = Number(raw);
    return Number.isFinite(num) && raw !== '' ? num : String(raw);
  };
  rows.sort((a, b) => {
    const av = parse(a);
    const bv = parse(b);
    let result = 0;
    if (typeof av === 'number' && typeof bv === 'number') result = av - bv;
    else result = String(av).localeCompare(String(bv), 'zh-Hans-CN');
    return direction === 'asc' ? result : -result;
  });
  rows.forEach((row) => tbody.appendChild(row));
  if (typeof filterThsMarketRows === 'function') filterThsMarketRows();
}
document.addEventListener('DOMContentLoaded', () => {
  sortIndustryMarketTable('return_1d', 'desc');
  if (typeof updateThsWatchUI === 'function') updateThsWatchUI();
  if (typeof filterThsMarketRows === 'function') filterThsMarketRows();
});
"""


_INDUSTRY_MARKET_POST_JS = """
(function() {
  const originalSwitch = window.switchIndustryKline;
  window.switchIndustryKline = function(symbol) {
    const normalized = String(symbol || '').toUpperCase();
    if (typeof originalSwitch === 'function') originalSwitch(normalized);
    renderIndustryMembers(normalized);
  };
  function thsWatchEmptyRow() {
    return '<tr><td colspan="10">暂无关注项</td></tr>';
  }
  function findThsModeRowHtml(payload, mode, symbol) {
    if (!payload || !payload.rowsHtml) return '';
    const box = document.createElement('tbody');
    box.innerHTML = payload.rowsHtml || '';
    const row = box.querySelector('tr[data-ths-symbol="' + String(symbol || '').toUpperCase() + '"]');
    if (!row) return '';
    row.dataset.thsMode = mode;
    row.dataset.thsSearch = ((row.dataset.thsSearch || '') + ' ' + thsModeLabel(mode)).trim();
    const nameCell = row.querySelector('.ths-market-name-cell > div');
    if (nameCell && !nameCell.querySelector('.ths-market-kind')) {
      nameCell.insertAdjacentHTML('beforeend', '<span class="ths-market-kind">' + thsModeLabel(mode) + '</span>');
    }
    return row.outerHTML;
  }
  function buildThsWatchModeData() {
    const data = window._THS_MARKET_MODE_DATA || {};
    const watched = thsWatchLoad();
    const rows = [];
    const klines = {};
    const members = {};
    let primary = '';
    watched.forEach(function(item) {
      const mode = item.mode === 'concept' ? 'concept' : 'industry';
      const symbol = String(item.symbol || '').toUpperCase();
      const payload = data[mode];
      const rowHtml = findThsModeRowHtml(payload, mode, symbol);
      if (!rowHtml) return;
      rows.push(rowHtml);
      if (payload && payload.klines && payload.klines[symbol]) klines[symbol] = payload.klines[symbol];
      if (payload && payload.members && payload.members[symbol]) members[symbol] = payload.members[symbol];
      if (!primary) primary = symbol;
    });
    return {
      mode: 'watch',
      rowLabel: '关注',
      rankingTitle: '关注池行情',
      chartTitle: '关注池指数K线与技术指标',
      memberDefaultTitle: '关注项成分股',
      memberEmptyText: watched.length ? '点击左侧关注项查看成分股' : '暂无关注项',
      memberEmptyMessage: '当前关注项没有可用成分股。',
      panelHint: '已关注行业与概念合并展示；点击表头可排序',
      note: '关注池行情来自本浏览器本地保存的星标行业和概念；行情、成交额、成分股沿用对应行业行情或概念行情的数据口径。',
      primary,
      rowsHtml: rows.join('') || thsWatchEmptyRow(),
      klines,
      members,
    };
  }
  function applyThsMarketMode(mode) {
    const payload = mode === 'watch' ? buildThsWatchModeData() : (window._THS_MARKET_MODE_DATA || {})[mode];
    if (!payload) return false;
    window._THS_MARKET_MODE = mode;
    document.querySelectorAll('.ths-mode-pane').forEach(function(pane) {
      pane.hidden = pane.id === 'stock-viewer';
    });
    window._THS_MARKET_LABEL = payload.rowLabel || '行业';
    window._THS_MEMBER_EMPTY_MESSAGE = payload.memberEmptyMessage || '当前板块没有可用成分股。';
    window._PRIMARY_INDUSTRY_INDEX = String(payload.primary || '').toUpperCase();
    window._INDUSTRY_KLINES = payload.klines || {};
    window._INDUSTRY_MEMBERS = payload.members || {};
    window._CURRENT_INDUSTRY_STOCK_SYMBOL = '';
    window._INDUSTRY_MEMBER_SORT = {key:'pct_chg', direction:'desc'};

    const rankingTitle = document.getElementById('ths-market-ranking-title');
    const panelHint = document.getElementById('ths-market-panel-hint');
    const note = document.getElementById('ths-market-note');
    const firstHead = document.getElementById('industry-market-label-head');
    const thead = document.querySelector('#industry-market-table thead');
    const chartTitle = document.getElementById('ths-market-chart-title');
    const memberTitle = document.getElementById('industry-member-title');
    const memberSub = document.getElementById('industry-member-sub');
    const table = document.getElementById('industry-market-table');
    const tbody = table ? table.querySelector('tbody') : null;
    if (rankingTitle) rankingTitle.textContent = payload.rankingTitle || '';
    if (panelHint) panelHint.textContent = payload.panelHint || '';
    if (note) note.textContent = payload.note || '';
    if (firstHead) firstHead.textContent = payload.rowLabel || '行业';
    if (thead) thead.innerHTML = payload.tableHeadHtml || window._THS_MARKET_DEFAULT_HEAD_HTML || '';
    if (chartTitle) chartTitle.textContent = payload.chartTitle || '';
    if (memberTitle) memberTitle.textContent = payload.memberDefaultTitle || ((payload.rowLabel || '行业') + '成分股');
    if (memberSub) memberSub.textContent = payload.memberEmptyText || '';
    if (tbody) tbody.innerHTML = payload.rowsHtml || '';
    if (table) {
      table.dataset.sortKey = '';
      table.dataset.sortDirection = 'desc';
    }
    document.querySelectorAll('[data-ths-market-mode]').forEach(function(btn) {
      btn.classList.toggle('active', (btn.getAttribute('data-ths-market-mode') || 'industry') === mode);
    });
    if (typeof sortIndustryMarketTable === 'function') sortIndustryMarketTable('return_1d', 'desc');
    if (typeof updateThsWatchUI === 'function') updateThsWatchUI();
    if (typeof filterThsMarketRows === 'function') filterThsMarketRows();
    showIndustryIndexKline();
    const pending = String(window._THS_PENDING_WATCH_SYMBOL || '').toUpperCase();
    window._THS_PENDING_WATCH_SYMBOL = '';
    const primary = pending || String(window._PRIMARY_INDUSTRY_INDEX || Object.keys(window._INDUSTRY_MEMBERS || {})[0] || '').toUpperCase();
    if (primary && typeof window.switchIndustryKline === 'function') window.switchIndustryKline(primary);
    else if (primary) renderIndustryMembers(primary);
    else {
      const list = document.getElementById('industry-member-list');
      if (list) list.innerHTML = '<div class="industry-member-empty">' + industryMarketEscape(payload.memberEmptyText || payload.memberEmptyMessage || '暂无数据') + '</div>';
    }
    return true;
  }
  function thsModeHash(mode) {
    if (mode === 'stock') return '#stock';
    if (mode === 'watch') return '#watch';
    if (mode === 'index') return '#index';
    return mode === 'concept' ? '#concept' : '#industry';
  }
  function applyStockViewerMode() {
    window._THS_MARKET_MODE = 'stock';
    document.querySelectorAll('.ths-mode-pane').forEach(function(pane) {
      pane.hidden = pane.id !== 'stock-viewer';
    });
    document.querySelectorAll('[data-ths-market-mode]').forEach(function(btn) {
      btn.classList.toggle('active', (btn.getAttribute('data-ths-market-mode') || '') === 'stock');
    });
    const rankingTitle = document.getElementById('ths-market-ranking-title');
    const panelHint = document.getElementById('ths-market-panel-hint');
    const note = document.getElementById('ths-market-note');
    if (rankingTitle) rankingTitle.textContent = '股票查看';
    if (panelHint) panelHint.textContent = '搜索股票、查看本地K线，并加入自定义股票板块';
    if (note) note.textContent = '股票查看功能复用股票查看器数据与本地自定义板块；K线页沿用本地 stock_kline 报告。';
    const input = document.getElementById('viewer-search-input');
    if (input) setTimeout(function() { input.focus(); }, 0);
    return true;
  }
  function loadThsMarketModeData(normalized, done) {
    const loaders = window._THS_MARKET_MODE_LOADERS || {};
    const src = loaders[normalized];
    if (!src) return false;
    window._THS_MARKET_MODE_LOADING = window._THS_MARKET_MODE_LOADING || {};
    if (window._THS_MARKET_MODE_LOADING[normalized]) {
      setTimeout(function() { loadThsMarketModeData(normalized, done); }, 100);
      return true;
    }
    window._THS_MARKET_MODE_LOADING[normalized] = true;
    const script = document.createElement('script');
    script.src = src;
    script.async = true;
    script.onload = function() {
      window._THS_MARKET_MODE_LOADING[normalized] = false;
      if (typeof done === 'function') done();
    };
    script.onerror = function() {
      window._THS_MARKET_MODE_LOADING[normalized] = false;
      const list = document.getElementById('industry-member-list');
      if (list) list.innerHTML = '<div class="industry-member-empty">概念行情数据文件加载失败，请重新生成报告。</div>';
    };
    document.head.appendChild(script);
    return true;
  }
  function applyAndHashThsMode(normalized) {
    if (applyThsMarketMode(normalized) && window.history && window.history.replaceState) {
      window.history.replaceState(null, '', thsModeHash(normalized));
    }
  }
  window.switchThsMarketMode = function(mode) {
    const normalized = mode === 'concept' ? 'concept' : mode === 'watch' ? 'watch' : mode === 'stock' ? 'stock' : mode === 'index' ? 'index' : 'industry';
    if (normalized === 'stock') {
      applyStockViewerMode();
      if (window.history && window.history.replaceState) window.history.replaceState(null, '', thsModeHash(normalized));
      return;
    }
    if (normalized === 'watch') {
      const needsConcept = thsWatchLoad().some(function(item) { return item && item.mode === 'concept'; })
        && !(window._THS_MARKET_MODE_DATA || {}).concept
        && (window._THS_MARKET_MODE_LOADERS || {}).concept;
      if (needsConcept) {
        loadThsMarketModeData('concept', function() { applyAndHashThsMode('watch'); });
        return;
      }
      applyAndHashThsMode('watch');
      return;
    }
    if (applyThsMarketMode(normalized)) {
      if (window.history && window.history.replaceState) {
        window.history.replaceState(null, '', thsModeHash(normalized));
      }
      return;
    }
    loadThsMarketModeData(normalized, function() {
      applyThsMarketMode(normalized);
      if (window.history && window.history.replaceState) window.history.replaceState(null, '', thsModeHash(normalized));
    });
  };
  document.addEventListener('DOMContentLoaded', function() {
    const hash = (window.location.hash || '').toLowerCase();
    if (hash === '#watch') {
      window.switchThsMarketMode('watch');
      return;
    }
    if (hash === '#stock') {
      window.switchThsMarketMode('stock');
      return;
    }
    if (hash === '#concept') {
      window.switchThsMarketMode('concept');
      return;
    }
    if (hash === '#index') {
      window.switchThsMarketMode('index');
      return;
    }
    applyThsMarketMode(window._THS_MARKET_MODE || 'industry');
  });
})();
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


def _frame_latest_date(frame: pd.DataFrame) -> pd.Timestamp | None:
    if frame is None or frame.empty:
        return None
    date_column = "date" if "date" in frame.columns else "trade_date" if "trade_date" in frame.columns else None
    if date_column is None:
        return None
    dates = pd.to_datetime(frame[date_column], errors="coerce")
    if dates.dropna().empty:
        return None
    return dates.max()


def _ths_max_stale_calendar_days(config: dict, section: str) -> int:
    ths_cfg = config.get("ths_indices", {}) if isinstance(config.get("ths_indices"), dict) else {}
    section_cfg = ths_cfg.get(section) if isinstance(ths_cfg.get(section), dict) else {}
    value = section_cfg.get("max_stale_calendar_days", ths_cfg.get("max_stale_calendar_days", 4))
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 4


def _filter_fresh_ths_frames(
    config: dict,
    section: str,
    frames: dict[str, pd.DataFrame],
    as_of: pd.Timestamp | None,
) -> dict[str, pd.DataFrame]:
    """Drop stale 同花顺板块指数 so discontinued concepts do not rank as current."""
    if not frames or as_of is None:
        return frames
    max_stale_days = _ths_max_stale_calendar_days(config, section)
    cutoff = pd.Timestamp(as_of).normalize() - pd.Timedelta(days=max_stale_days)
    fresh: dict[str, pd.DataFrame] = {}
    for symbol, frame in frames.items():
        latest = _frame_latest_date(frame)
        if latest is not None and pd.Timestamp(latest).normalize() >= cutoff:
            fresh[symbol] = frame
    return fresh


def _ths_industry_names(config: dict) -> dict[str, str]:
    meta_dir = Path(config.get("data", {}).get("meta_dir", "data/meta"))
    path = meta_dir / "ths_indices.csv"
    if not path.exists():
        return {}
    try:
        frame = pd.read_csv(path, dtype={"ts_code": str})
    except Exception:
        return {}
    if not {"ts_code", "name"}.issubset(frame.columns):
        return {}
    return {str(row["ts_code"]).upper(): str(row["name"]) for _, row in frame.dropna(subset=["ts_code"]).iterrows()}


def _select_ths_industry_symbols_from_meta(config: dict) -> list[str]:
    return _select_ths_symbols_from_meta(config, "industries", default_type="I")


def _select_ths_concept_symbols_from_meta(config: dict) -> list[str]:
    return _select_ths_symbols_from_meta(config, "concepts", default_type="N")


def _ths_section_file_path(config: dict, value: Any) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    if path.is_absolute():
        return path
    meta_dir = Path(config.get("data", {}).get("meta_dir", "data/meta"))
    return meta_dir / path


def _read_ths_symbol_file(path: Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()
    try:
        frame = pd.read_csv(path, dtype=str).fillna("")
    except Exception:
        return set()
    if frame.empty:
        return set()
    symbol_column = next((column for column in ("ts_code", "symbol", "代码") if column in frame.columns), frame.columns[0])
    return {
        str(value).strip().upper()
        for value in frame[symbol_column].tolist()
        if str(value).strip().upper().endswith(".TI")
    }


def _apply_ths_section_symbol_files(symbols: list[str], config: dict, section_cfg: dict[str, Any]) -> list[str]:
    include_symbols = _read_ths_symbol_file(_ths_section_file_path(config, section_cfg.get("include_path")))
    exclude_symbols = _read_ths_symbol_file(_ths_section_file_path(config, section_cfg.get("exclude_path")))
    selected = [symbol for symbol in symbols if not include_symbols or symbol in include_symbols]
    if exclude_symbols:
        selected = [symbol for symbol in selected if symbol not in exclude_symbols]
    return selected


def _select_ths_symbols_from_meta(config: dict, section: str, *, default_type: str) -> list[str]:
    meta_dir = Path(config.get("data", {}).get("meta_dir", "data/meta"))
    path = meta_dir / "ths_indices.csv"
    if not path.exists():
        return []
    try:
        frame = pd.read_csv(path, dtype={"ts_code": str})
    except Exception:
        return []
    ths_cfg = config.get("ths_indices", {}) or {}
    section_cfg = ths_cfg.get(section) or {}
    exchange = str(section_cfg.get("exchange", "A")).upper()
    index_type = str(section_cfg.get("type", default_type)).upper()
    min_count = section_cfg.get("min_count", 1)
    mask = pd.Series(True, index=frame.index)
    if "exchange" in frame.columns:
        mask &= frame["exchange"].astype(str).str.upper() == exchange
    if "type" in frame.columns:
        mask &= frame["type"].astype(str).str.upper() == index_type
    if "count" in frame.columns and min_count is not None:
        mask &= pd.to_numeric(frame["count"], errors="coerce").fillna(0) >= float(min_count)
    if "ts_code" not in frame.columns:
        return []
    symbols = frame.loc[mask, "ts_code"].astype(str).str.upper().tolist()
    symbols = _apply_ths_section_symbol_files(symbols, config, section_cfg)
    limit = section_cfg.get("limit")
    if limit:
        symbols = symbols[: int(limit)]
    return list(dict.fromkeys(symbol for symbol in symbols if symbol.endswith(".TI")))


def _default_industry_frames(config: dict, structure: dict[str, Any]) -> dict[str, pd.DataFrame]:
    """Load local 同花顺行业指数 frames for all available industries."""
    as_of = _as_of(structure)
    rankings = structure.get("industry_rankings") or {}
    symbols: list[str] = []
    for row in (rankings.get("all") or []) + (rankings.get("strongest") or []) + (rankings.get("weakest") or []):
        symbol = str(row.get("symbol") or "").upper()
        if symbol.endswith(".TI") and symbol not in symbols:
            symbols.append(symbol)
    for symbol in _select_ths_industry_symbols_from_meta(config):
        if symbol not in symbols:
            symbols.append(symbol)
    frames: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        frame = _read_index_frame(config, symbol, as_of)
        if not frame.empty:
            frames[symbol] = frame
    return _filter_fresh_ths_frames(config, "industries", frames, as_of)


def _default_concept_frames(config: dict, structure: dict[str, Any]) -> dict[str, pd.DataFrame]:
    """Load local 同花顺概念指数 frames for cached concept indices."""
    as_of = _as_of(structure)
    frames: dict[str, pd.DataFrame] = {}
    for symbol in _select_ths_concept_symbols_from_meta(config):
        frame = _read_index_frame(config, symbol, as_of)
        if not frame.empty:
            frames[symbol] = frame
    return _filter_fresh_ths_frames(config, "concepts", frames, as_of)


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    return number


def _fmt_tushare_amount(value: Any) -> str:
    """Format Tushare amount fields from 千元 to readable CNY."""
    number = _finite_float(value)
    if number is None:
        return "--"
    cny = number * 1000.0
    abs_cny = abs(cny)
    if abs_cny >= 1_000_000_000_000:
        return f"{cny / 1_000_000_000_000:.2f}万亿"
    if abs_cny >= 100_000_000:
        return f"{cny / 100_000_000:.2f}亿"
    if abs_cny >= 10_000:
        return f"{cny / 10_000:.2f}万"
    return f"{cny:.0f}"


def _industry_frame_metrics(frame: pd.DataFrame, as_of: Any) -> dict[str, Any]:
    if frame is None or frame.empty:
        return {}
    work = frame.copy()
    date_column = "date" if "date" in work.columns else "trade_date" if "trade_date" in work.columns else None
    cutoff = pd.to_datetime(as_of, errors="coerce")
    if date_column is not None:
        dates = pd.to_datetime(work[date_column], errors="coerce")
        work = work.loc[dates.notna()].copy()
        work["_date"] = dates.loc[work.index]
        if pd.notna(cutoff):
            work = work.loc[work["_date"].le(cutoff)].copy()
        work = work.sort_values("_date")
    if work.empty or "close" not in work.columns:
        return {}
    close = pd.to_numeric(work["close"], errors="coerce")
    amount = pd.to_numeric(work.get("amount", pd.Series(index=work.index, dtype=float)), errors="coerce")
    latest = close.iloc[-1]
    if pd.isna(latest):
        return {}

    def ret(window: int) -> float | None:
        prev = close.shift(window).iloc[-1]
        if pd.isna(prev) or not prev:
            return None
        return _finite_float(latest / prev - 1.0)

    def amount_sum(window: int) -> float | None:
        if amount.empty:
            return None
        value = amount.tail(window).sum(min_count=1)
        return _finite_float(value)

    ma20 = close.rolling(20, min_periods=20).mean().iloc[-1]
    prev_amount = amount.shift(20).iloc[-1] if not amount.empty else None
    latest_amount = amount.iloc[-1] if not amount.empty else None
    return {
        "return_1d": ret(1),
        "return_5d": ret(5),
        "return_20d": ret(20),
        "pct_above_ma20": _finite_float(float(latest >= ma20)) if pd.notna(ma20) else None,
        "amount_1d": _finite_float(latest_amount),
        "amount_5d": amount_sum(5),
        "amount_10d": amount_sum(10),
        "amount_share_change_20d": (
            _finite_float(latest_amount / prev_amount - 1.0)
            if latest_amount is not None and prev_amount is not None and pd.notna(latest_amount) and pd.notna(prev_amount) and prev_amount
            else None
        ),
    }


def _industry_all_rows(
    rankings: dict[str, Any],
    frames: dict[str, pd.DataFrame],
    names: dict[str, str],
    as_of: Any,
) -> list[dict[str, Any]]:
    rows = [dict(row) for row in (rankings.get("all") or [])]
    if rows:
        rows = [
            row for row in rows
            if not str(row.get("symbol") or "").upper().endswith(".TI")
            or str(row.get("symbol") or "").upper() in frames
        ]
        for row in rows:
            symbol = str(row.get("symbol") or "").upper()
            metrics = _industry_frame_metrics(frames.get(symbol, pd.DataFrame()), as_of)
            for key, value in metrics.items():
                if row.get(key) is None:
                    row[key] = value
        return sorted(
            rows,
            key=lambda row: _finite_float(row.get("return_1d")) if _finite_float(row.get("return_1d")) is not None else -999.0,
            reverse=True,
        )

    existing: dict[str, dict[str, Any]] = {}
    for row in (rankings.get("strongest") or []) + (rankings.get("weakest") or []):
        symbol = str(row.get("symbol") or "").upper()
        if symbol:
            existing[symbol] = dict(row)

    cutoff = pd.to_datetime(as_of, errors="coerce")
    for symbol, frame in frames.items():
        if symbol in existing or frame is None or frame.empty:
            continue
        metrics = _industry_frame_metrics(frame, cutoff)
        if not metrics:
            continue
        existing[symbol] = {
            "industry": names.get(symbol, symbol),
            "symbol": symbol,
            "return_1d": metrics.get("return_1d"),
            "return_5d": metrics.get("return_5d"),
            "return_20d": metrics.get("return_20d"),
            "advance_ratio": None,
            "pct_above_ma20": metrics.get("pct_above_ma20"),
            "amount_1d": metrics.get("amount_1d"),
            "amount_5d": metrics.get("amount_5d"),
            "amount_10d": metrics.get("amount_10d"),
            "amount_share_change_20d": metrics.get("amount_share_change_20d"),
        }

    return sorted(
        existing.values(),
        key=lambda row: _finite_float(row.get("return_1d")) if _finite_float(row.get("return_1d")) is not None else -999.0,
        reverse=True,
    )


def _sort_attr(value: Any, fallback: str = "") -> str:
    number = _finite_float(value)
    if number is None:
        return escape(fallback, quote=True)
    return f"{number:.12g}"


def _industry_amount_cell(item: dict[str, Any], key: str) -> str:
    amount = _fmt_tushare_amount(item.get(key))
    share = _fmt_ratio_pct(item.get(f"{key}_share"))
    avg = _fmt_tushare_amount(item.get(f"{key}_avg"))
    return (
        "<div class='industry-amount-cell'>"
        f"<strong data-sort-key='{key}' data-sort-value='{_sort_attr(item.get(key))}'>{escape(amount)}</strong>"
        f"<span data-sort-key='{key}_share' data-sort-value='{_sort_attr(item.get(f'{key}_share'))}'>占 {escape(share)}</span>"
        f"<span data-sort-key='{key}_avg' data-sort-value='{_sort_attr(item.get(f'{key}_avg'))}'>均 {escape(avg)}</span>"
        "</div>"
    )


def _industry_amount_header(label: str, key: str) -> str:
    chips = (
        f"<button type=\"button\" class=\"industry-sort-chip\" data-key=\"{key}\" onclick=\"sortIndustryMarketTable('{key}', null, event)\">额</button>"
        f"<button type=\"button\" class=\"industry-sort-chip\" data-key=\"{key}_share\" onclick=\"sortIndustryMarketTable('{key}_share', null, event)\">占</button>"
        f"<button type=\"button\" class=\"industry-sort-chip\" data-key=\"{key}_avg\" onclick=\"sortIndustryMarketTable('{key}_avg', null, event)\">均</button>"
    )
    return f"<th class=\"industry-amount-head\"><div class=\"industry-amount-title\">{escape(label)}</div><div class=\"industry-sort-chips\">{chips}</div></th>"


def _attach_industry_amount_metrics(rows: list[dict[str, Any]]) -> None:
    amount_keys = ("amount_1d", "amount_5d", "amount_10d")
    totals: dict[str, float] = {}
    for key in amount_keys:
        totals[key] = sum(
            value
            for value in (_finite_float(row.get(key)) for row in rows)
            if value is not None and value > 0
        )
    for row in rows:
        for key in amount_keys:
            amount = _finite_float(row.get(key))
            total = totals.get(key) or 0.0
            count = _finite_float(row.get(f"{key}_stock_count"))
            row[f"{key}_share"] = _finite_float(amount / total) if amount is not None and total > 0 else None
            row[f"{key}_avg"] = _finite_float(amount / count) if amount is not None and count and count > 0 else None


def _stock_selector_path(config: dict) -> Path | None:
    raw = (
        (config.get("dashboard", {}) or {}).get("stock_selector")
        or config.get("stock_selector")
        or {}
    )
    if isinstance(raw, (str, Path)):
        raw = {"csv_path": str(raw)}
    if not isinstance(raw, dict) or raw.get("enabled", True) is False:
        return None
    value = str(raw.get("csv_path") or raw.get("path") or "").strip()
    return Path(value).expanduser() if value else None


def _split_tags(value: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for part in str(value or "").replace("，", "|").replace(",", "|").split("|"):
        item = part.strip()
        if item and item.lower() != "nan" and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _stock_cell(row: pd.Series, column: str) -> str:
    if column not in row:
        return ""
    value = row.get(column)
    if pd.isna(value):
        return ""
    return str(value).strip()


def _stock_price_text(value: Any) -> str:
    number = _finite_float(value)
    if number is None:
        return "--"
    return f"{number:.2f}" if abs(number) >= 1 else f"{number:.4f}"


def _stock_price_number(value: Any) -> float | None:
    number = _finite_float(value)
    return round(number, 4) if number is not None else None


def _stock_pct_points(value: Any) -> float | None:
    """Stock selector CSV stores 最新涨跌幅 as percentage points, e.g. 1.23 means +1.23%."""
    number = _finite_float(value)
    if number is None:
        return None
    return round(number, 3)


def _read_stock_cache_quote(config: dict, symbol: str, as_of: Any) -> dict[str, Any]:
    """Read latest price and 1-day pct-change from local stock K-line cache.

    This keeps the constituent table aligned with the K-line chart and avoids stale
    quote fields from the selector CSV.
    """
    path = _stock_cache_path(config, symbol)
    if not path.exists():
        return {}
    try:
        frame = pd.read_csv(path, dtype={"date": str, "trade_date": str, "ts_code": str})
    except Exception:
        return {}
    if frame.empty or "close" not in frame.columns:
        return {}
    date_column = "date" if "date" in frame.columns else "trade_date" if "trade_date" in frame.columns else None
    work = frame.copy()
    if date_column is not None:
        dates = pd.to_datetime(work[date_column].astype(str), errors="coerce")
        work = work.loc[dates.notna()].copy()
        work["_date"] = dates.loc[work.index]
        cutoff = pd.to_datetime(as_of, errors="coerce")
        if pd.notna(cutoff):
            work = work.loc[work["_date"].le(cutoff)].copy()
        work = work.sort_values("_date")
    if work.empty:
        return {}
    close = pd.to_numeric(work["close"], errors="coerce")
    close = close.loc[close.notna()]
    if close.empty:
        return {}
    latest = float(close.iloc[-1])
    previous = float(close.iloc[-2]) if len(close) >= 2 and close.iloc[-2] else None
    pct_chg = ((latest / previous - 1.0) * 100.0) if previous else None
    return {
        "price": _stock_price_text(latest),
        "price_num": round(latest, 4),
        "pct_chg": round(pct_chg, 3) if pct_chg is not None else None,
        "quote_source": "本地日线缓存",
    }


def _ths_member_cache_path(config: dict, symbol: str) -> Path:
    meta_dir = Path(config.get("data", {}).get("meta_dir", "data/meta"))
    return meta_dir / "ths_members" / f"{symbol.upper()}.csv"


def _normalize_ths_member_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    work = frame.copy()
    rename_map = {}
    if "con_code" not in work.columns and "ts_code" in work.columns:
        rename_map["ts_code"] = "con_code"
    if "con_name" not in work.columns and "name" in work.columns:
        rename_map["name"] = "con_name"
    if rename_map:
        work = work.rename(columns=rename_map)
    if not {"con_code", "con_name"}.issubset(work.columns):
        return pd.DataFrame()
    work["con_code"] = work["con_code"].astype(str).str.strip().str.upper()
    work["con_name"] = work["con_name"].astype(str).str.strip()
    work = work.loc[work["con_code"].ne("") & work["con_name"].ne("")].copy()
    return work.drop_duplicates(subset=["con_code"], keep="first")


def _read_cached_ths_members(config: dict, symbol: str) -> pd.DataFrame:
    path = _ths_member_cache_path(config, symbol)
    if not path.exists():
        return pd.DataFrame()
    try:
        frame = pd.read_csv(path, dtype=str).fillna("")
    except Exception:
        return pd.DataFrame()
    return _normalize_ths_member_frame(frame)


def _fetch_ths_members(config: dict, symbol: str, *, enabled: bool | None = None) -> pd.DataFrame:
    """Fetch official 同花顺指数成分 from Tushare and cache it locally.

    This is intentionally quiet on failure: report generation should still work from
    the local selector fallback when the token/network is unavailable.
    """
    raw_cfg = config.get("industry_market", {}) if isinstance(config.get("industry_market"), dict) else {}
    should_fetch = bool(raw_cfg.get("fetch_ths_members", False)) if enabled is None else bool(enabled)
    if not should_fetch:
        return pd.DataFrame()
    try:
        from data.tushare_client import configured_tokens
        import tushare as ts

        tokens = configured_tokens(config)
        pro = ts.pro_api(tokens[0])
        frame = pro.ths_member(ts_code=symbol.upper())
    except Exception:
        return pd.DataFrame()
    members = _normalize_ths_member_frame(frame)
    if members.empty:
        return pd.DataFrame()
    path = _ths_member_cache_path(config, symbol)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        members.to_csv(path, index=False)
    except Exception:
        pass
    return members


def _official_ths_members(config: dict, symbol: str, *, fetch: bool | None = None) -> pd.DataFrame:
    cached = _read_cached_ths_members(config, symbol)
    if not cached.empty:
        return cached
    return _fetch_ths_members(config, symbol, enabled=fetch)


def _fmt_market_cap(value: Any) -> str:
    """Format Tushare daily_basic total_mv/circ_mv values, whose unit is 10k CNY."""
    number = _finite_float(value)
    if number is None:
        return ""
    yi = number / 10000.0
    if abs(yi) >= 1000:
        return f"{yi:,.0f}亿"
    if abs(yi) >= 100:
        return f"{yi:,.1f}亿"
    return f"{yi:,.2f}亿"


def _fmt_valuation(value: Any) -> str:
    number = _finite_float(value)
    if number is None or number <= 0:
        return ""
    return f"{number:.1f}"


def _fmt_turnover_rate(value: Any) -> str:
    number = _finite_float(value)
    if number is None:
        return ""
    return f"{number:.2f}%"


def _read_daily_basic_metrics(
    config: dict,
    symbol: str,
    as_of: Any,
) -> dict[str, Any]:
    path = Path(config.get("data", {}).get("meta_dir", "data/meta")) / "daily_basic" / f"{symbol.upper()}.csv"
    if not path.exists():
        return {}
    try:
        frame = pd.read_csv(
            path,
            dtype={"ts_code": str, "trade_date": str},
            usecols=lambda column: column in {"trade_date", "total_mv", "circ_mv", "pe", "pe_ttm", "pb", "turnover_rate"},
        )
    except Exception:
        return {}
    if frame.empty:
        return {}
    work = frame.copy()
    if "trade_date" in work.columns:
        dates = pd.to_datetime(work["trade_date"].astype(str), errors="coerce")
        work = work.loc[dates.notna()].copy()
        work["_date"] = dates.loc[work.index]
        cutoff = pd.to_datetime(as_of, errors="coerce")
        if pd.notna(cutoff):
            work = work.loc[work["_date"].le(cutoff)].copy()
        work = work.sort_values("_date")
    if work.empty:
        return {}
    row = work.iloc[-1]
    total_mv = _finite_float(row.get("total_mv"))
    circ_mv = _finite_float(row.get("circ_mv"))
    pe = _finite_float(row.get("pe"))
    pe_ttm = _finite_float(row.get("pe_ttm"))
    pb = _finite_float(row.get("pb"))
    turnover_rate = _finite_float(row.get("turnover_rate"))
    return {
        "market_cap": total_mv,
        "float_market_cap": circ_mv,
        "market_cap_text": _fmt_market_cap(total_mv),
        "float_market_cap_text": _fmt_market_cap(circ_mv),
        "pe": pe,
        "pe_ttm": pe_ttm,
        "pb": pb,
        "turnover_rate": turnover_rate,
        "pe_text": _fmt_valuation(pe),
        "pe_ttm_text": _fmt_valuation(pe_ttm),
        "pb_text": _fmt_valuation(pb),
        "turnover_rate_text": _fmt_turnover_rate(turnover_rate),
    }


def _stock_cache_path(config: dict, symbol: str) -> Path:
    return Path(config.get("data", {}).get("cache_dir", "data/cache")) / f"{symbol.upper()}.csv"


def _read_stock_amount_windows(config: dict, symbol: str, as_of: Any) -> dict[str, float | None]:
    path = _stock_cache_path(config, symbol)
    if not path.exists():
        return {}
    try:
        frame = pd.read_csv(
            path,
            dtype={"date": str, "trade_date": str},
            usecols=lambda column: column in {"date", "trade_date", "amount"},
        )
    except Exception:
        return {}
    if frame.empty or "amount" not in frame.columns:
        return {}
    work = frame.copy()
    date_column = "date" if "date" in work.columns else "trade_date" if "trade_date" in work.columns else None
    if date_column is not None:
        dates = pd.to_datetime(work[date_column].astype(str), errors="coerce")
        work = work.loc[dates.notna()].copy()
        work["_date"] = dates.loc[work.index]
        cutoff = pd.to_datetime(as_of, errors="coerce")
        if pd.notna(cutoff):
            work = work.loc[work["_date"].le(cutoff)].copy()
        work = work.sort_values("_date")
    if work.empty:
        return {}
    amount = pd.to_numeric(work["amount"], errors="coerce")

    def amount_sum(window: int) -> float | None:
        value = amount.tail(window).sum(min_count=1)
        return _finite_float(value)

    return {
        "amount_1d": amount_sum(1),
        "amount_5d": amount_sum(5),
        "amount_10d": amount_sum(10),
    }


def _to_number_list(series: pd.Series, digits: int = 4) -> list[float | None]:
    result: list[float | None] = []
    for value in pd.to_numeric(series, errors="coerce").tolist():
        if pd.isna(value):
            result.append(None)
        else:
            result.append(round(float(value), digits))
    return result


def _stock_timeframe_payload(work: pd.DataFrame, freq: str | None, bars: int) -> dict[str, Any]:
    if work.empty:
        return {}
    if freq:
        source = work.set_index("_date").sort_index()
        frame = pd.DataFrame(
            {
                "open": source["open"].resample(freq).first(),
                "high": source["high"].resample(freq).max(),
                "low": source["low"].resample(freq).min(),
                "close": source["close"].resample(freq).last(),
                "volume": source["volume"].resample(freq).sum(min_count=1),
                "amount": source["amount"].resample(freq).sum(min_count=1),
            }
        ).dropna(subset=["open", "high", "low", "close"])
        frame["_date"] = frame.index
    else:
        frame = work.copy()
    if frame.empty:
        return {}
    if bars and bars > 0:
        frame = frame.tail(max(int(bars) + 70, int(bars))).copy()
    close_s = pd.to_numeric(frame["close"], errors="coerce")
    boll_mid = close_s.rolling(20, min_periods=20).mean()
    boll_std = close_s.rolling(20, min_periods=20).std(ddof=0)
    boll_upper = boll_mid + 2 * boll_std
    boll_lower = boll_mid - 2 * boll_std
    return {
        "dates": pd.to_datetime(frame["_date"], errors="coerce").dt.strftime("%Y-%m-%d").tolist(),
        "ohlc": [
            [round(float(o), 4), round(float(c), 4), round(float(l), 4), round(float(h), 4)]
            for o, c, l, h in zip(frame["open"], frame["close"], frame["low"], frame["high"], strict=False)
        ],
        "ma5": _to_number_list(close_s.rolling(5, min_periods=1).mean()),
        "ma10": _to_number_list(close_s.rolling(10, min_periods=1).mean()),
        "ma20": _to_number_list(close_s.rolling(20, min_periods=1).mean()),
        "ma60": _to_number_list(close_s.rolling(60, min_periods=1).mean()),
        "boll_upper": _to_number_list(boll_upper),
        "boll_mid": _to_number_list(boll_mid),
        "boll_lower": _to_number_list(boll_lower),
        "volume": _to_number_list(pd.to_numeric(frame["volume"], errors="coerce").fillna(0), 2),
        "amount": _to_number_list(pd.to_numeric(frame["amount"], errors="coerce").fillna(0), 2),
    }


def _direct_stock_kline_payload(config: dict, symbol: str, as_of: Any, bars: int) -> dict[str, Any] | None:
    """Build a compact direct-render payload for the industry page.

    The standalone stock page still owns the full feature set.  Here we only embed the
    latest daily K/MA/volume/amount data needed when clicking industry constituents,
    avoiding an iframe inside the industry report.
    """
    path = _stock_cache_path(config, symbol)
    if not path.exists():
        return None
    try:
        frame = pd.read_csv(path, dtype={"date": str, "trade_date": str, "ts_code": str})
    except Exception:
        return None
    if frame.empty:
        return None
    date_column = "date" if "date" in frame.columns else "trade_date" if "trade_date" in frame.columns else None
    required = {"open", "high", "low", "close"}
    if date_column is None or not required.issubset(frame.columns):
        return None
    work = frame.copy()
    dates = pd.to_datetime(work[date_column].astype(str), errors="coerce")
    work = work.loc[dates.notna()].copy()
    work["_date"] = dates.loc[work.index]
    cutoff = pd.to_datetime(as_of, errors="coerce")
    if pd.notna(cutoff):
        work = work.loc[work["_date"].le(cutoff)].copy()
    work = work.sort_values("_date")
    if work.empty:
        return None
    open_s = pd.to_numeric(work["open"], errors="coerce")
    high_s = pd.to_numeric(work["high"], errors="coerce")
    low_s = pd.to_numeric(work["low"], errors="coerce")
    close_s = pd.to_numeric(work["close"], errors="coerce")
    valid = open_s.notna() & high_s.notna() & low_s.notna() & close_s.notna()
    work = work.loc[valid].copy()
    open_s = open_s.loc[valid]
    high_s = high_s.loc[valid]
    low_s = low_s.loc[valid]
    close_s = close_s.loc[valid]
    work["open"] = open_s
    work["high"] = high_s
    work["low"] = low_s
    work["close"] = close_s
    if work.empty:
        return None
    volume_source = work["volume"] if "volume" in work.columns else work["vol"] if "vol" in work.columns else pd.Series(0, index=work.index)
    work["volume"] = pd.to_numeric(volume_source, errors="coerce")
    amount_source = work["amount"] if "amount" in work.columns else close_s * work["volume"]
    work["amount"] = pd.to_numeric(amount_source, errors="coerce")
    timeframes = {
        "1d": _stock_timeframe_payload(work, None, bars),
        "1w": _stock_timeframe_payload(work, "W-FRI", bars),
        "1m": _stock_timeframe_payload(work, "ME", bars),
    }
    return {
        "symbol": symbol.upper(),
        "bar_limit": bars,
        "timeframes": timeframes,
        **timeframes.get("1d", {}),
    }


def _write_industry_stock_kline_files(
    config: dict,
    output: Path,
    members_payload: dict[str, Any],
    as_of: Any,
) -> dict[str, str]:
    raw_cfg = config.get("industry_market", {}) if isinstance(config.get("industry_market"), dict) else {}
    # 760 个交易日略多于 3 年，给指标预热和非交易日差异留出余量。
    bars = max(760, int(raw_cfg.get("stock_kline_bars") or 760))
    data_dir = output.parent / "stock_kline_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    hrefs: dict[str, str] = {}
    seen: set[str] = set()
    for entry in members_payload.values():
        members = entry.get("members") if isinstance(entry, dict) else None
        if not isinstance(members, list):
            continue
        for item in members:
            symbol = str((item or {}).get("symbol") or "").upper()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            target = data_dir / f"{symbol}.js"
            cache_path = _stock_cache_path(config, symbol)
            if target.exists():
                try:
                    cache_mtime = cache_path.stat().st_mtime if cache_path.exists() else 0
                    marker = f'"bar_limit":{bars}'
                    with target.open("r", encoding="utf-8") as existing_file:
                        prefix = existing_file.read(512)
                        existing_file.seek(0, 2)
                        existing_file.seek(max(0, existing_file.tell() - 512))
                        suffix = existing_file.read(512)
                    if target.stat().st_mtime >= cache_mtime and (marker in prefix or marker in suffix):
                        hrefs[symbol] = relative_href(output, target)
                        continue
                except OSError:
                    pass
            data = _direct_stock_kline_payload(config, symbol, as_of, bars)
            if data:
                data["name"] = str((item or {}).get("name") or symbol)
                data["industry_path"] = str((item or {}).get("industry_path") or "")
                data["bar_limit"] = bars
                target.write_text(
                    "window._INDUSTRY_STOCK_KLINES=window._INDUSTRY_STOCK_KLINES||{};"
                    f"window._INDUSTRY_STOCK_KLINES[{to_compact_json(symbol)}]={to_compact_json(data)};",
                    encoding="utf-8",
                )
                hrefs[symbol] = relative_href(output, target)
    for entry in members_payload.values():
        members = entry.get("members") if isinstance(entry, dict) else None
        if not isinstance(members, list):
            continue
        for item in members:
            symbol = str((item or {}).get("symbol") or "").upper()
            if symbol in hrefs:
                item["stock_data_href"] = hrefs[symbol]
                item["kline_available"] = True
            else:
                item["stock_data_href"] = ""
                item["kline_available"] = False
    return hrefs


def _attach_stock_selector_kline_hrefs(selector: dict[str, Any], output: Path) -> None:
    rows = selector.get("rows") if isinstance(selector, dict) else None
    if not isinstance(rows, list):
        return
    data_dir = output.parent / "stock_kline_data"
    kline_count = 0
    for item in rows:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").upper()
        target = data_dir / f"{symbol}.js"
        available = bool(symbol and target.exists())
        item["stock_data_href"] = relative_href(output, target) if available else ""
        item["kline_available"] = available
        if available:
            kline_count += 1
    selector["kline_count"] = kline_count


def _industry_member_payload(
    config: dict,
    output: Path,
    industries: list[dict[str, Any]],
    as_of: Any,
    *,
    label_mode: str = "industry",
    force_official_members: bool = False,
    allow_selector_fallback: bool = True,
) -> dict[str, Any]:
    """Build industry constituents.

    Prefer Tushare ths_member official 同花顺指数成分.  The selector CSV can be kept as
    a metadata fallback for industry pages, but concept pages can disable fallback
    to avoid mixing official concept indices with approximate local concept labels.
    """
    source = _stock_selector_path(config)
    frame = pd.DataFrame()
    if source is not None and source.exists():
        try:
            frame = pd.read_csv(source, dtype=str).fillna("")
        except Exception:
            frame = pd.DataFrame()

    has_selector = not frame.empty and {"股票代码", "股票简称"}.issubset(frame.columns)
    selector_by_symbol: dict[str, pd.Series] = {}
    if has_selector:
        for _, row in frame.iterrows():
            stock_symbol = _stock_cell(row, "股票代码").upper()
            if stock_symbol and stock_symbol not in selector_by_symbol:
                selector_by_symbol[stock_symbol] = row

    reports_dir = Path(config.get("output", {}).get("reports_dir", "output/reports"))
    payload: dict[str, Any] = {}
    metrics_cache: dict[str, dict[str, Any]] = {}
    quote_cache: dict[str, dict[str, Any]] = {}
    amount_cache: dict[str, dict[str, float | None]] = {}

    def selector_member_rows(label: str) -> list[tuple[str, str, pd.Series | None]]:
        rows: list[tuple[str, str, pd.Series | None]] = []
        if not has_selector:
            return rows
        for _, row in frame.iterrows():
            stock_symbol = _stock_cell(row, "股票代码").upper()
            name = _stock_cell(row, "股票简称")
            if not stock_symbol or not name:
                continue
            if label_mode == "concept":
                matched_tags = _split_tags(_stock_cell(row, "概念板块"))
                if label not in {item for item in matched_tags if item}:
                    continue
            else:
                industry_levels = [
                    _stock_cell(row, "一级行业"),
                    _stock_cell(row, "二级行业"),
                    _stock_cell(row, "三级行业"),
                ]
                industry_tags = _split_tags(_stock_cell(row, "行业板块"))
                if label not in {item for item in industry_levels + industry_tags if item}:
                    continue
            rows.append((stock_symbol, name, row))
        return rows

    def member_from_row(
        stock_symbol: str,
        name: str,
        industry: str,
        row: pd.Series | None,
        amount_windows: dict[str, float | None] | None = None,
    ) -> dict[str, Any]:
        industry_levels: list[str] = []
        selector_quote: dict[str, Any] = {}
        if row is not None:
            industry_levels = [
                _stock_cell(row, "一级行业"),
                _stock_cell(row, "二级行业"),
                _stock_cell(row, "三级行业"),
            ]
            selector_quote = {
                "price": _stock_price_text(_stock_cell(row, "最新价")),
                "price_num": _stock_price_number(_stock_cell(row, "最新价")),
                "pct_chg": _stock_pct_points(_stock_cell(row, "最新涨跌幅")),
                "quote_source": "股票池CSV行情",
            }
        if stock_symbol not in quote_cache:
            quote_cache[stock_symbol] = _read_stock_cache_quote(config, stock_symbol, as_of)
        quote = quote_cache.get(stock_symbol) or selector_quote
        if stock_symbol not in metrics_cache:
            metrics_cache[stock_symbol] = _read_daily_basic_metrics(config, stock_symbol, as_of)
        metrics = metrics_cache.get(stock_symbol) or {}
        amount_1d = _finite_float((amount_windows or {}).get("amount_1d"))
        kline_path = reports_dir / "stock_kline" / f"{stock_symbol}.html"
        cache_path = _stock_cache_path(config, stock_symbol)
        return {
            "symbol": stock_symbol,
            "name": name,
            "industry_path": " / ".join(item for item in industry_levels if item) or industry,
            "price": quote.get("price") or "--",
            "price_num": quote.get("price_num"),
            "pct_chg": quote.get("pct_chg"),
            "quote_source": quote.get("quote_source") or "",
            "market_cap": metrics.get("market_cap"),
            "float_market_cap": metrics.get("float_market_cap"),
            "market_cap_text": metrics.get("market_cap_text") or "",
            "float_market_cap_text": metrics.get("float_market_cap_text") or "",
            "pe": metrics.get("pe"),
            "pe_ttm": metrics.get("pe_ttm"),
            "pb": metrics.get("pb"),
            "turnover_rate": metrics.get("turnover_rate"),
            "amount_1d": amount_1d,
            "pe_text": metrics.get("pe_text") or "",
            "pe_ttm_text": metrics.get("pe_ttm_text") or "",
            "pb_text": metrics.get("pb_text") or "",
            "turnover_rate_text": metrics.get("turnover_rate_text") or "",
            "amount_1d_text": _fmt_tushare_amount(amount_1d),
            "kline_available": bool(cache_path.exists()),
            "kline_href": relative_href(output, kline_path) if kline_path.exists() else "",
        }

    for industry_row in industries:
        symbol = str(industry_row.get("symbol") or "").upper()
        industry = str(industry_row.get("industry") or industry_row.get("name") or "").strip()
        if not symbol or not industry:
            continue
        official_members = _official_ths_members(config, symbol, fetch=True if force_official_members else None)
        if not official_members.empty:
            raw_members = [
                (
                    str(row.get("con_code") or "").upper(),
                    str(row.get("con_name") or "").strip(),
                    selector_by_symbol.get(str(row.get("con_code") or "").upper()),
                )
                for _, row in official_members.iterrows()
            ]
            source_label = "Tushare ths_member"
        elif not allow_selector_fallback:
            raw_members = []
            source_label = "Tushare ths_member（无可用官方成分）"
        else:
            raw_members = selector_member_rows(industry)
            fallback_label = "概念标签" if label_mode == "concept" else "行业标签"
            source_label = (
                f"本地股票池{fallback_label}近似匹配: {source.name}"
                if source is not None
                else f"本地股票池{fallback_label}近似匹配"
            )
        members: list[dict[str, Any]] = []
        amount_totals = {"amount_1d": 0.0, "amount_5d": 0.0, "amount_10d": 0.0}
        amount_counts = {"amount_1d": 0, "amount_5d": 0, "amount_10d": 0}
        for stock_symbol, name, row in raw_members:
            if not stock_symbol or not name:
                continue
            if stock_symbol not in amount_cache:
                amount_cache[stock_symbol] = _read_stock_amount_windows(config, stock_symbol, as_of)
            amount_windows = amount_cache.get(stock_symbol) or {}
            members.append(member_from_row(stock_symbol, name, industry, row, amount_windows))
            for key in amount_totals:
                value = _finite_float(amount_windows.get(key))
                if value is not None:
                    amount_totals[key] += value
                    amount_counts[key] += 1
        for key, total in amount_totals.items():
            if amount_counts[key]:
                industry_row[key] = total
                industry_row[f"{key}_stock_count"] = amount_counts[key]
        members.sort(
            key=lambda item: item.get("pct_chg") if item.get("pct_chg") is not None else -999.0,
            reverse=True,
        )
        payload[symbol] = {
            "industry": industry,
            "symbol": symbol,
            "source": source_label,
            "quote_source": "本地日线缓存优先",
            "members": members,
        }
    return payload


def _industry_market_rows(items: list[dict[str, Any]], clickable_symbols: set[str], *, empty_label: str = "行业") -> str:
    rows: list[str] = []
    for item in items:
        symbol = str(item.get("symbol") or "").upper()
        industry = str(item.get("industry") or item.get("name") or "--")
        escaped_symbol = escape(symbol, quote=True)
        escaped_industry = escape(industry, quote=True)
        search_text = f"{industry} {symbol}".lower()
        attrs = ""
        if symbol:
            attrs = (
                f" class='industry-row-clickable' data-industry-symbol='{escaped_symbol}'"
                f" data-ths-symbol='{escaped_symbol}' data-ths-name='{escaped_industry}'"
                f" data-ths-search='{escape(search_text, quote=True)}'"
                f" onclick='selectIndustryMarketRow(\"{escaped_symbol}\")'"
            )
        name_html = (
            f"<span class='industry-link'>{escape(industry)}</span><br><small>{escape(symbol)}</small>"
            if symbol in clickable_symbols else f"{escape(industry)}<br><small>{escape(symbol)}</small>"
        )
        label = (
            f"<div class='ths-market-name-cell'>"
            f"<button class='ths-watch-btn' type='button' title='加入关注池' onclick='toggleThsWatch(\"{escaped_symbol}\", event)'>☆</button>"
            f"<div>{name_html}</div>"
            f"</div>"
            if symbol else name_html
        )
        rows.append(
            f"<tr{attrs}>"
            f"<td data-sort-key='industry' data-sort-value='{escape(industry, quote=True)}'>{label}</td>"
            f"<td class='{_tone(item.get('return_1d'))}' data-sort-key='return_1d' data-sort-value='{_sort_attr(item.get('return_1d'))}'>{escape(_fmt_pct(item.get('return_1d')))}</td>"
            f"<td class='{_tone(item.get('return_5d'))}' data-sort-key='return_5d' data-sort-value='{_sort_attr(item.get('return_5d'))}'>{escape(_fmt_pct(item.get('return_5d')))}</td>"
            f"<td class='{_tone(item.get('return_20d'))}' data-sort-key='return_20d' data-sort-value='{_sort_attr(item.get('return_20d'))}'>{escape(_fmt_pct(item.get('return_20d')))}</td>"
            f"<td data-sort-key='amount_1d' data-sort-value='{_sort_attr(item.get('amount_1d'))}'>{_industry_amount_cell(item, 'amount_1d')}</td>"
            f"<td data-sort-key='amount_5d' data-sort-value='{_sort_attr(item.get('amount_5d'))}'>{_industry_amount_cell(item, 'amount_5d')}</td>"
            f"<td data-sort-key='amount_10d' data-sort-value='{_sort_attr(item.get('amount_10d'))}'>{_industry_amount_cell(item, 'amount_10d')}</td>"
            f"<td data-sort-key='advance_ratio' data-sort-value='{_sort_attr(item.get('advance_ratio'))}'>{escape(_fmt_ratio_pct(item.get('advance_ratio')))}</td>"
            f"<td data-sort-key='pct_above_ma20' data-sort-value='{_sort_attr(item.get('pct_above_ma20'))}'>{escape(_fmt_ratio_pct(item.get('pct_above_ma20')))}</td>"
            f"<td class='{_tone(item.get('amount_share_change_20d'))}' data-sort-key='amount_share_change_20d' data-sort-value='{_sort_attr(item.get('amount_share_change_20d'))}'>{escape(_fmt_pct(item.get('amount_share_change_20d')))}</td>"
            "</tr>"
        )
    return "".join(rows) or f"<tr><td colspan='10'>暂无{escape(empty_label)}数据</td></tr>"


def _index_market_table_head() -> str:
    columns = (
        ("指数", "industry"),
        ("最新", "close"),
        ("1日", "return_1d"),
        ("5日", "return_5d"),
        ("10日", "return_10d"),
        ("20日", "return_20d"),
        ("60日", "return_60d"),
        ("日趋势", "daily_trend"),
        ("周趋势", "weekly_trend"),
        ("MA20", "ma20_state"),
        ("MA60", "ma60_state"),
        ("量比20日", "amount_ratio_20d"),
        ("位置/状态", "support_pressure"),
    )
    return "<tr>" + "".join(
        f'<th class="sortable" data-key="{key}" onclick="sortIndustryMarketTable(\'{key}\')">{label}</th>'
        for label, key in columns
    ) + "</tr>"


def _industry_market_table_head(row_label: str) -> str:
    return (
        f'<tr><th id="industry-market-label-head" class="sortable" data-key="industry" onclick="sortIndustryMarketTable(\'industry\')">{escape(row_label)}</th>'
        f'<th class="sortable sorted" data-key="return_1d" data-sort-mark="↓" onclick="sortIndustryMarketTable(\'return_1d\')">1日</th>'
        f'<th class="sortable" data-key="return_5d" onclick="sortIndustryMarketTable(\'return_5d\')">5日</th>'
        f'<th class="sortable" data-key="return_20d" onclick="sortIndustryMarketTable(\'return_20d\')">20日</th>'
        f"{_industry_amount_header('当日', 'amount_1d')}{_industry_amount_header('5日', 'amount_5d')}{_industry_amount_header('10日', 'amount_10d')}"
        f'<th class="sortable" data-key="advance_ratio" onclick="sortIndustryMarketTable(\'advance_ratio\')">上涨比例</th>'
        f'<th class="sortable" data-key="pct_above_ma20" onclick="sortIndustryMarketTable(\'pct_above_ma20\')">MA20上方</th>'
        f'<th class="sortable" data-key="amount_share_change_20d" onclick="sortIndustryMarketTable(\'amount_share_change_20d\')">成交占比变化</th></tr>'
    )


def _index_state_text(value: Any) -> str:
    return {
        "uptrend": "上行",
        "downtrend": "下行",
        "sideways": "震荡",
        "above": "上方",
        "below": "下方",
    }.get(str(value or ""), "--")


def _index_market_rows(items: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for item in items:
        symbol = str(item.get("symbol") or "").upper()
        name = str(item.get("name") or symbol or "--")
        escaped_symbol = escape(symbol, quote=True)
        escaped_name = escape(name, quote=True)
        search_text = escape(f"{name} {symbol}".lower(), quote=True)
        state = str(item.get("support_pressure") or "--")
        rows.append(
            f"<tr class='industry-row-clickable' data-industry-symbol='{escaped_symbol}' "
            f"data-ths-symbol='{escaped_symbol}' data-ths-name='{escaped_name}' data-ths-search='{search_text}' "
            f"onclick='selectIndustryMarketRow(\"{escaped_symbol}\")'>"
            f"<td data-sort-key='industry' data-sort-value='{escaped_name}'><span class='industry-link'>{escaped_name}</span><br><small>{escaped_symbol}</small></td>"
            f"<td data-sort-key='close' data-sort-value='{_sort_attr(item.get('close'))}'>{escape(_fmt_index_value(item.get('close')))}</td>"
            f"<td class='{_tone(item.get('return_1d'))}' data-sort-key='return_1d' data-sort-value='{_sort_attr(item.get('return_1d'))}'>{escape(_fmt_pct(item.get('return_1d')))}</td>"
            f"<td class='{_tone(item.get('return_5d'))}' data-sort-key='return_5d' data-sort-value='{_sort_attr(item.get('return_5d'))}'>{escape(_fmt_pct(item.get('return_5d')))}</td>"
            f"<td class='{_tone(item.get('return_10d'))}' data-sort-key='return_10d' data-sort-value='{_sort_attr(item.get('return_10d'))}'>{escape(_fmt_pct(item.get('return_10d')))}</td>"
            f"<td class='{_tone(item.get('return_20d'))}' data-sort-key='return_20d' data-sort-value='{_sort_attr(item.get('return_20d'))}'>{escape(_fmt_pct(item.get('return_20d')))}</td>"
            f"<td class='{_tone(item.get('return_60d'))}' data-sort-key='return_60d' data-sort-value='{_sort_attr(item.get('return_60d'))}'>{escape(_fmt_pct(item.get('return_60d')))}</td>"
            f"<td data-sort-key='daily_trend' data-sort-value='{escape(str(item.get('daily_trend') or ''), quote=True)}'>{escape(_index_state_text(item.get('daily_trend')))}</td>"
            f"<td data-sort-key='weekly_trend' data-sort-value='{escape(str(item.get('weekly_trend') or ''), quote=True)}'>{escape(_index_state_text(item.get('weekly_trend')))}</td>"
            f"<td data-sort-key='ma20_state' data-sort-value='{escape(str(item.get('ma20_state') or ''), quote=True)}'>{escape(_index_state_text(item.get('ma20_state')))}</td>"
            f"<td data-sort-key='ma60_state' data-sort-value='{escape(str(item.get('ma60_state') or ''), quote=True)}'>{escape(_index_state_text(item.get('ma60_state')))}</td>"
            f"<td data-sort-key='amount_ratio_20d' data-sort-value='{_sort_attr(item.get('amount_ratio_20d'))}'>{escape(_fmt_multiple(item.get('amount_ratio_20d')))}</td>"
            f"<td data-sort-key='support_pressure' data-sort-value='{escape(state, quote=True)}'>{escape(state)}</td>"
            "</tr>"
        )
    return "".join(rows) or "<tr><td colspan='13'>暂无指数数据</td></tr>"


def _fmt_index_value(value: Any) -> str:
    number = _finite_float(value)
    if number is None:
        return "--"
    return f"{number:,.2f}"


def _fmt_multiple(value: Any) -> str:
    number = _finite_float(value)
    if number is None:
        return "--"
    return f"{number:.2f}x"


def _index_market_frames(config: dict, structure: dict[str, Any]) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    as_of = _as_of(structure)
    for item in (structure.get("indices") or {}).values():
        if not item.get("available"):
            continue
        symbol = str(item.get("symbol") or "").upper()
        if not symbol:
            continue
        frame = _read_index_frame(config, symbol, as_of)
        if not frame.empty:
            frames[symbol] = frame
    return frames


def _index_market_data(config: dict, structure: dict[str, Any]) -> dict[str, Any]:
    facts = [dict(item) for item in (structure.get("indices") or {}).values() if item.get("available")]
    frames = _index_market_frames(config, structure)
    rows = [{"name": item.get("name"), **item} for item in facts]
    rows.sort(key=lambda item: _finite_float(item.get("return_1d")) if _finite_float(item.get("return_1d")) is not None else -999.0, reverse=True)
    klines = {
        symbol: {"symbol": symbol, "name": next((str(item.get("name") or symbol) for item in facts if str(item.get("symbol") or "").upper() == symbol), symbol), "timeframes": _plain_multi_timeframe_kline_payload(frame)}
        for symbol, frame in frames.items()
    }
    primary = next((str(item.get("symbol") or "").upper() for item in facts if str(item.get("symbol") or "").upper() in klines), "")
    return {
        "mode": "index",
        "rowLabel": "指数",
        "rankingTitle": "指数行情",
        "chartTitle": "指数K线与技术指标",
        "memberDefaultTitle": "指数成分股",
        "memberEmptyText": "指数行情不展示成分股",
        "memberEmptyMessage": "指数行情不展示成分股，请点击其他行情页查看行业或概念成分股。",
        "panelHint": "市场摘录中的主要指数；默认按当日涨跌排序；点击表头可排序",
        "note": "指数列表来自市场摘录结构事实；K线读取本地指数日线缓存，点击指数可复用当前页面的周期切换、技术指标和画线功能。",
        "primary": primary,
        "rowsHtml": _index_market_rows(rows),
        "tableHeadHtml": _index_market_table_head(),
        "klines": klines,
        "members": {},
    }


def _write_ths_market_mode_data_file(
    output: Path,
    *,
    mode: str,
    row_label: str,
    ranking_title: str,
    chart_title: str,
    member_default_title: str,
    member_empty_text: str,
    member_empty_message: str,
    panel_hint: str,
    note: str,
    primary_symbol: str,
    rows: list[dict[str, Any]],
    clickable_symbols: set[str],
    kline_payload: dict[str, Any],
    members_payload: dict[str, Any],
) -> Path:
    data = {
        "mode": mode,
        "rowLabel": row_label,
        "rankingTitle": ranking_title,
        "chartTitle": chart_title,
        "memberDefaultTitle": member_default_title,
        "memberEmptyText": member_empty_text,
        "memberEmptyMessage": member_empty_message,
        "panelHint": panel_hint,
        "note": note,
        "primary": primary_symbol,
        "rowsHtml": _industry_market_rows(rows, clickable_symbols, empty_label=row_label),
        "klines": kline_payload,
        "members": members_payload,
    }
    target = output.parent / f"{mode}_market_data.js"
    target.write_text(
        "window._THS_MARKET_MODE_DATA=window._THS_MARKET_MODE_DATA||{};"
        f"window._THS_MARKET_MODE_DATA[{to_compact_json(mode)}]={to_compact_json(data)};",
        encoding="utf-8",
    )
    return target


def _stock_viewer_chips(selector: dict[str, Any]) -> str:
    chips = []
    for item in (selector.get("top_concepts") or [])[:12]:
        name = str(item.get("name") or "")
        if name:
            chips.append(
                f'<button type="button" class="viewer-chip" data-chip-mode="concept" '
                f'data-chip-query="{escape(name, quote=True)}">{escape(name)}'
                f'<span>{escape(str(item.get("count", 0)))}</span></button>'
            )
    for item in (selector.get("top_industries") or [])[:10]:
        name = str(item.get("name") or "")
        if name:
            chips.append(
                f'<button type="button" class="viewer-chip" data-chip-mode="industry" '
                f'data-chip-query="{escape(name, quote=True)}">{escape(name)}'
                f'<span>{escape(str(item.get("count", 0)))}</span></button>'
            )
    return "".join(chips)


def _embedded_stock_viewer_html(selector: dict[str, Any], selector_href: str) -> str:
    if not selector.get("enabled") or selector.get("error"):
        message = selector.get("error") or "股票选择器未启用。"
        return (
            "<section id='stock-viewer' class='embedded-stock-viewer ths-mode-pane' hidden>"
            f"<div class='industry-chart-empty'>{escape(str(message))}</div>"
            "</section>"
        )
    count = int(selector.get("count") or len(selector.get("rows") or []))
    cache_count = int(selector.get("cache_count") or 0)
    kline_count = int(selector.get("kline_count") or 0)
    chips = _stock_viewer_chips(selector)
    return f"""
      <section id="stock-viewer" class="embedded-stock-viewer ths-mode-pane" hidden>
        <section class="viewer-shell">
          <aside class="viewer-sidebar">
            <div class="viewer-controls-grid">
              <div class="viewer-search" data-viewer-section="search">
                <div class="viewer-panel-title">
                  <strong>查找</strong>
                  <span class="viewer-panel-sub">搜索后点行查看 K 线</span>
                  <button class="viewer-collapse" type="button" data-collapse-section="search">折叠</button>
                </div>
                <div class="viewer-section-body">
                  <div class="viewer-counts">
                    <div><span>股票</span><strong>{count}</strong></div>
                    <div><span>缓存</span><strong>{cache_count}</strong></div>
                    <div><span>K线数据</span><strong>{kline_count}</strong></div>
                  </div>
                  <div class="viewer-search-row">
                    <input id="viewer-search-input" type="search" placeholder="搜索代码、简称、行业、概念" autocomplete="off">
                    <button id="viewer-search-clear" class="viewer-button" type="button">清空</button>
                  </div>
                  <div class="viewer-modes">
                    <button type="button" class="viewer-mode active" data-viewer-mode="all">全部</button>
                    <button type="button" class="viewer-mode" data-viewer-mode="concept">概念</button>
                    <button type="button" class="viewer-mode" data-viewer-mode="industry">行业</button>
                    <button type="button" class="viewer-mode" data-viewer-mode="name">名称/代码</button>
                    <button type="button" class="viewer-mode" data-viewer-mode="custom">我的板块</button>
                  </div>
                  <div class="viewer-chip-strip">{chips}</div>
                </div>
              </div>
              <div class="viewer-boards" data-viewer-section="boards">
                <div class="viewer-board-title">
                  <strong>我的板块</strong>
                  <span id="viewer-board-status">浏览器本地保存</span>
                  <button class="viewer-collapse" type="button" data-collapse-section="boards">折叠</button>
                </div>
                <div class="viewer-section-body">
                  <div class="viewer-board-create">
                    <input id="viewer-board-input" type="text" placeholder="新建/选择板块">
                    <button id="viewer-board-create" type="button">新建/选择</button>
                    <button id="viewer-board-delete" class="viewer-danger" type="button">删除当前</button>
                  </div>
                  <div id="viewer-board-list" class="viewer-board-list"></div>
                </div>
              </div>
            </div>
            <div class="viewer-current">
              <div>
                <strong id="viewer-current-name">请选择股票</strong>
                <span id="viewer-current-meta">点击股票后复用下方 K 线与画线区域</span>
              </div>
              <div id="viewer-current-pct" class="tone flat">--</div>
            </div>
            <div class="viewer-list-head">
              <span id="viewer-list-summary">准备加载股票</span>
            </div>
            <div id="viewer-stock-list" class="viewer-list"></div>
          </aside>
        </section>
      </section>
    """


def _embedded_stock_viewer_script(element_id: str = "stock-viewer-data") -> str:
    return inline_script(
        f"""
(function(){{
  var raw=document.getElementById('{element_id}');
  var payload=raw?JSON.parse(raw.textContent||'{{}}'):{{}};
  var rows=payload.rows||[];
  var state={{mode:'all',query:'',activeBoard:'',selectedSymbol:'',sort:'match'}};
  var customKey='quantyb:stock_selector_custom_boards:v1';
  var fileBoards=normalizeBoards(payload.custom_boards||{{}});
  var customState=loadBoards();
  var rowsBySymbol={{}};
  rows.forEach(function(row,idx){{row._rank=idx;if(row.symbol)rowsBySymbol[row.symbol]=row;}});
  function esc(text){{return String(text==null?'':text).replace(/[&<>"']/g,function(ch){{return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch];}});}}
  function norm(text){{return String(text==null?'':text).trim().toLowerCase();}}
  function tone(v){{var n=Number(v);if(!isFinite(n)||n===0)return'flat';return n>0?'up':'down';}}
  function pct(v){{var n=Number(v);if(!isFinite(n))return'--';return(n>=0?'+':'')+n.toFixed(2)+'%';}}
  function price(v){{var n=Number(v);if(!isFinite(n))return'--';return n.toFixed(2);}}
  function mv(v){{var n=Number(v);if(!isFinite(n))return'市值 --';if(Math.abs(n)>=100000000)return'市值 '+(n/100000000).toFixed(2)+'万亿';if(Math.abs(n)>=10000)return'市值 '+(n/10000).toFixed(2)+'亿';return'市值 '+n.toFixed(0)+'万';}}
  function normalizeBoards(input){{
    var boards={{}}, source=input&&input.boards&&typeof input.boards==='object'?input.boards:input;
    if(!source||typeof source!=='object')return boards;
    Object.keys(source).forEach(function(name){{
      var boardName=String(name||'').trim();if(!boardName)return;
      var rawBoard=source[name];
      var stocks=Array.isArray(rawBoard)?rawBoard:(rawBoard&&Array.isArray(rawBoard.stocks)?rawBoard.stocks:(rawBoard&&Array.isArray(rawBoard.symbols)?rawBoard.symbols:[]));
      var seen={{}};
      boards[boardName]={{name:boardName,stocks:[]}};
      stocks.forEach(function(item){{
        var symbol=typeof item==='object'&&item?String(item.symbol||item.ts_code||item.code||'').trim().toUpperCase():String(item||'').trim().toUpperCase();
        if(symbol&&!seen[symbol]){{boards[boardName].stocks.push(symbol);seen[symbol]=1;}}
      }});
    }});
    return boards;
  }}
  function cloneBoards(boards){{
    var out={{}};
    Object.keys(boards||{{}}).forEach(function(name){{
      var board=boards[name]||{{}};
      out[name]={{name:board.name||name,stocks:Array.isArray(board.stocks)?board.stocks.slice():[]}};
    }});
    return out;
  }}
  function mergeBoard(target,name,board){{
    if(!name||!board)return;
    if(!target[name])target[name]={{name:name,stocks:[]}};
    var seen={{}};
    target[name].stocks.forEach(function(symbol){{seen[symbol]=1;}});
    (board.stocks||[]).forEach(function(symbol){{
      symbol=String(symbol||'').trim().toUpperCase();
      if(symbol&&!seen[symbol]){{target[name].stocks.push(symbol);seen[symbol]=1;}}
    }});
  }}
  function loadBoards(){{
    var fallback=cloneBoards(fileBoards);
    try{{
      var parsed=JSON.parse(localStorage.getItem(customKey)||'{{}}')||{{}};
      var boards=cloneBoards(parsed.boards||{{}});
      Object.keys(fallback).forEach(function(name){{mergeBoard(boards,name,fallback[name]);}});
      var names=Object.keys(boards).sort(function(a,b){{return a.localeCompare(b,'zh-Hans-CN');}});
      return {{active:parsed.active||names[0]||'',boards:boards}};
    }}catch(err){{
      var names=Object.keys(fallback).sort(function(a,b){{return a.localeCompare(b,'zh-Hans-CN');}});
      return {{active:names[0]||'',boards:fallback}};
    }}
  }}
  function saveBoards(){{try{{localStorage.setItem(customKey,JSON.stringify(customState));}}catch(err){{}}}}
  function boardNames(){{return Object.keys(customState.boards||{{}}).sort(function(a,b){{return a.localeCompare(b,'zh-Hans-CN');}});}}
  function boardCount(name){{var b=name?customState.boards[name]:null;return b&&Array.isArray(b.stocks)?b.stocks.length:0;}}
  function hasSymbol(name,symbol){{var b=name?customState.boards[name]:null;return !!(b&&Array.isArray(b.stocks)&&b.stocks.indexOf(symbol)>=0);}}
  function targetBoard(row){{return state.activeBoard&&customState.boards[state.activeBoard]?state.activeBoard:(boardNames()[0]||'');}}
  function boardOptions(selected){{
    var names=boardNames();
    if(!names.length)return '<option value="">先建板块</option>';
    return names.map(function(name){{return '<option value="'+esc(name)+'" '+(name===selected?'selected':'')+'>'+esc(name)+'</option>';}}).join('');
  }}
  function createBoard(){{
    var input=document.getElementById('viewer-board-input');
    var name=input?String(input.value||'').trim():'';
    if(!name){{if(input)input.focus();return;}}
    if(!customState.boards[name])customState.boards[name]={{name:name,created_at:new Date().toISOString(),stocks:[]}};
    state.activeBoard=name;customState.active=name;saveBoards();renderBoards();renderRows();
  }}
  function deleteCurrentBoard(){{
    var name=state.activeBoard||customState.active||'';
    if(!name||!customState.boards[name])return;
    var count=boardCount(name);
    if(window.confirm&&!confirm('删除观察板块「'+name+'」？'+(count?' 当前包含 '+count+' 只股票。':'')))return;
    delete customState.boards[name];
    var names=boardNames();
    state.activeBoard=names[0]||'';
    customState.active=state.activeBoard;
    var input=document.getElementById('viewer-board-input');
    if(input)input.value=state.activeBoard;
    saveBoards();renderBoards();renderRows();
  }}
  function viewerScrollSnapshot(){{
    var list=document.getElementById('viewer-stock-list');
    return {{windowX:window.scrollX||0,windowY:window.scrollY||0,listTop:list?list.scrollTop:0}};
  }}
  function restoreViewerScroll(snapshot){{
    if(!snapshot)return;
    var restore=function(){{var list=document.getElementById('viewer-stock-list');if(list)list.scrollTop=snapshot.listTop||0;window.scrollTo(snapshot.windowX||0,snapshot.windowY||0);}};
    restore();if(window.requestAnimationFrame)window.requestAnimationFrame(restore);else window.setTimeout(restore,0);
  }}
  function toggleInBoard(symbol,boardName,preserveScroll){{
    var scrollState=preserveScroll?viewerScrollSnapshot():null;
    boardName=String(boardName||'').trim();if(!boardName)return;
    if(!customState.boards[boardName])customState.boards[boardName]={{name:boardName,created_at:new Date().toISOString(),stocks:[]}};
    var stocks=customState.boards[boardName].stocks||[], idx=stocks.indexOf(symbol);
    if(idx>=0)stocks.splice(idx,1);else stocks.push(symbol);
    state.activeBoard=boardName;customState.active=boardName;saveBoards();renderBoards();renderRows();
    restoreViewerScroll(scrollState);
  }}
  function rowText(row){{
    if(state.mode==='custom')return row.search_text||'';
    if(state.mode==='concept')return row.concept_text||'';
    if(state.mode==='industry')return row.industry_text||'';
    if(state.mode==='name')return row.name_text||'';
    return row.search_text||'';
  }}
  function matches(row){{
    if(state.mode==='custom'&&(!state.activeBoard||!hasSymbol(state.activeBoard,row.symbol)))return false;
    var q=norm(state.query);if(!q)return true;
    return norm(rowText(row)).indexOf(q)>=0;
  }}
  function sortRows(list){{
    return list.slice().sort(function(a,b){{return(a._rank||0)-(b._rank||0);}});
  }}
  function setMode(mode){{
    state.mode=mode||'all';
    document.querySelectorAll('[data-viewer-mode]').forEach(function(btn){{btn.classList.toggle('active',btn.getAttribute('data-viewer-mode')===state.mode);}});
    renderRows();
  }}
  function toggleSection(name){{
    var section=document.querySelector('[data-viewer-section="'+name+'"]');
    if(!section)return;
    var collapsed=!section.classList.contains('viewer-section-collapsed');
    section.classList.toggle('viewer-section-collapsed',collapsed);
    var btn=section.querySelector('[data-collapse-section]');
    if(btn)btn.textContent=collapsed?'展开':'折叠';
  }}
  function setBoard(name){{
    state.activeBoard=name||'';
    customState.active=state.activeBoard;
    if(state.activeBoard)state.mode='custom';
    saveBoards();renderBoards();
    var input=document.getElementById('viewer-board-input');
    if(input)input.value=state.activeBoard;
    document.querySelectorAll('[data-viewer-mode]').forEach(function(btn){{btn.classList.toggle('active',btn.getAttribute('data-viewer-mode')===state.mode);}});
    renderRows();
  }}
  function renderBoards(){{
    var list=document.getElementById('viewer-board-list'), status=document.getElementById('viewer-board-status');
    var names=boardNames();
    if(state.activeBoard&&!customState.boards[state.activeBoard])state.activeBoard=names[0]||'';
    if(list)list.innerHTML=names.length?names.map(function(name){{return '<button type="button" class="viewer-board-chip '+(name===state.activeBoard?'active':'')+'" data-board="'+esc(name)+'">'+esc(name)+'<span>'+boardCount(name)+'</span></button>';}}).join(''):'<span class="empty">还没有我的板块。</span>';
    if(status)status.textContent=state.activeBoard?'当前：'+state.activeBoard+' · '+boardCount(state.activeBoard)+' 只':'新建后可从股票行加入。';
  }}
  function renderTags(items,limit){{return(items||[]).slice(0,limit||3).map(function(x){{return esc(x);}}).join(' / ');}}
  function renderRows(){{
    var list=document.getElementById('viewer-stock-list'), summary=document.getElementById('viewer-list-summary');
    if(!list)return;
    var matched=sortRows(rows.filter(matches));
    var limit=state.mode==='custom'?matched.length:180;
    var capped=matched.slice(0,limit);
    if(summary)summary.textContent=(state.mode==='custom'&&state.activeBoard?'我的板块「'+state.activeBoard+'」':'当前范围')+' · 匹配 '+matched.length+' 只'+(matched.length>capped.length?'，显示前 '+capped.length+' 只':'');
    list.innerHTML=capped.length?capped.map(function(row){{
      var disabled=!row.stock_data_href;
      var target=targetBoard(row), inBoard=target&&hasSymbol(target,row.symbol);
      return '<div class="viewer-row '+(row.symbol===state.selectedSymbol?'active':'')+'" data-symbol="'+esc(row.symbol||'')+'" data-disabled="'+(disabled?'1':'0')+'">'
        +'<div><strong>'+esc(row.name||row.symbol||'--')+'</strong><small>'+esc(row.symbol||'')+' · '+esc(renderTags(row.industry_tags,2)||row.industry||'--')+'</small><em>'+esc(renderTags(row.concepts,3)||'--')+'</em></div>'
        +'<div class="viewer-row-metrics"><span>'+esc(price(row.price))+'</span><span class="'+tone(row.pct_chg)+'">'+esc(pct(row.pct_chg))+'</span><small>'+esc(mv(row.market_cap))+'</small></div>'
        +'<div class="viewer-row-actions"><select class="viewer-board-target" data-symbol="'+esc(row.symbol||'')+'">'+boardOptions(target)+'</select><button type="button" class="viewer-add-board '+(inBoard?'in-board':'')+' '+(!target?'disabled':'')+'" data-symbol="'+esc(row.symbol||'')+'" '+(!target?'disabled':'')+'>'+(target?(inBoard?'移出板块':'加入板块'):'先建板块')+'</button><button type="button" class="viewer-open-new" data-view-stock="'+esc(row.symbol||'')+'" '+(disabled?'disabled':'')+'>'+(disabled?'无K线':'查看K线')+'</button></div>'
        +'</div>';
    }}).join(''):'<p class="empty">没有匹配股票，换个关键词或板块试试。</p>';
  }}
  function stockItem(row){{
    return {{
      symbol: row.symbol || '',
      name: row.name || row.symbol || '',
      industry_path: row.industry || renderTags(row.industry_tags,3) || '',
      pct_chg: row.pct_chg,
      price: row.price,
      stock_data_href: row.stock_data_href || '',
      kline_available: !!row.stock_data_href
    }};
  }}
  function selectStock(symbol){{
    var row=rowsBySymbol[String(symbol||'').toUpperCase()]||null;
    if(!row)return;
    state.selectedSymbol=row.symbol;
    var item=stockItem(row);
    window._CURRENT_STOCK_VIEWER_ITEM=item;
    window._CURRENT_INDUSTRY_STOCK_SYMBOL=String(row.symbol||'').toUpperCase();
    var name=document.getElementById('viewer-current-name'), meta=document.getElementById('viewer-current-meta'), pctNode=document.getElementById('viewer-current-pct');
    if(name)name.textContent=(row.name||row.symbol)+' '+row.symbol;
    if(meta)meta.textContent=(renderTags(row.industry_tags,3)||row.industry||'--')+' · '+(renderTags(row.concepts,4)||'--');
    if(pctNode){{pctNode.textContent=pct(row.pct_chg);pctNode.className='tone '+tone(row.pct_chg);}}
    var stockShell=document.getElementById('industry-stock-kline-shell'), kline=document.getElementById('industry-kline'), indicator=document.getElementById('industry-indicator'), toolbar=document.querySelector('.industry-manual-toolbar');
    if(kline)kline.style.display='none';
    if(indicator)indicator.style.display='none';
    if(toolbar)toolbar.style.display='none';
    if(stockShell)stockShell.style.display='block';
    if(typeof loadIndustryStockKlineData==='function')loadIndustryStockKlineData(row.symbol,item);
    if(stockShell)stockShell.scrollIntoView({{behavior:'smooth',block:'start'}});
    renderRows();
  }}
  document.querySelectorAll('[data-viewer-mode]').forEach(function(btn){{btn.addEventListener('click',function(){{setMode(btn.getAttribute('data-viewer-mode')||'all');}});}});
  document.querySelectorAll('[data-collapse-section]').forEach(function(btn){{btn.addEventListener('click',function(){{toggleSection(btn.getAttribute('data-collapse-section')||'');}});}});
  document.querySelectorAll('[data-chip-query]').forEach(function(btn){{btn.addEventListener('click',function(){{state.query=btn.getAttribute('data-chip-query')||'';var input=document.getElementById('viewer-search-input');if(input)input.value=state.query;setMode(btn.getAttribute('data-chip-mode')||'all');}});}});
  var search=document.getElementById('viewer-search-input');
  if(search)search.addEventListener('input',function(){{state.query=search.value||'';renderRows();}});
  var clear=document.getElementById('viewer-search-clear');
  if(clear)clear.addEventListener('click',function(){{state.query='';if(search){{search.value='';search.focus();}}renderRows();}});
  var boardInput=document.getElementById('viewer-board-input');
  if(boardInput)boardInput.addEventListener('keydown',function(evt){{if(evt.key==='Enter'){{evt.preventDefault();createBoard();}}}});
  var boardCreate=document.getElementById('viewer-board-create');
  if(boardCreate)boardCreate.addEventListener('click',createBoard);
  var boardDelete=document.getElementById('viewer-board-delete');
  if(boardDelete)boardDelete.addEventListener('click',deleteCurrentBoard);
  var boardList=document.getElementById('viewer-board-list');
  if(boardList)boardList.addEventListener('click',function(evt){{var chip=evt.target&&evt.target.closest?evt.target.closest('.viewer-board-chip'):null;if(chip)setBoard(chip.getAttribute('data-board')||'');}});
  var stockList=document.getElementById('viewer-stock-list');
  if(stockList){{
    stockList.addEventListener('click',function(evt){{
      var add=evt.target&&evt.target.closest?evt.target.closest('.viewer-add-board'):null;
      if(add){{evt.preventDefault();evt.stopPropagation();if(add.disabled)return;var rowEl=add.closest('.viewer-row'), target=rowEl?rowEl.querySelector('.viewer-board-target'):null;toggleInBoard(add.getAttribute('data-symbol')||'',target?target.value:state.activeBoard,true);return;}}
      if(evt.target&&evt.target.closest&&evt.target.closest('.viewer-board-target'))return;
      var rowEl=evt.target&&evt.target.closest?evt.target.closest('.viewer-row'):null;
      if(rowEl&&rowEl.getAttribute('data-disabled')!=='1')selectStock(rowEl.getAttribute('data-symbol')||'');
    }});
    stockList.addEventListener('change',function(evt){{
      var sel=evt.target&&evt.target.closest?evt.target.closest('.viewer-board-target'):null;if(!sel)return;
      var rowEl=sel.closest('.viewer-row'), btn=rowEl?rowEl.querySelector('.viewer-add-board'):null;
      if(!btn)return;
      var inBoard=sel.value&&hasSymbol(sel.value,sel.getAttribute('data-symbol')||'');
      btn.disabled=!sel.value;btn.classList.toggle('disabled',!sel.value);btn.classList.toggle('in-board',!!inBoard);btn.textContent=!sel.value?'先建板块':(inBoard?'移出板块':'加入板块');
    }});
  }}
  state.activeBoard=customState.active||boardNames()[0]||'';
  if(boardInput&&state.activeBoard)boardInput.value=state.activeBoard;
  renderBoards();renderRows();
}})();
        """
    )


def _build_concept_mode_data(config: dict, structure: dict[str, Any], output: Path) -> Path:
    concept_frames = _default_concept_frames(config, structure)
    names = _ths_industry_names(config)
    concept_rows = _industry_all_rows({}, concept_frames, names, structure.get("date"))
    concept_rankings = {"all": concept_rows}
    concept_kline_payload = _industry_technical_kline_payload(
        pd.DataFrame(),
        concept_rankings,
        concept_frames,
        config.get("technical_structure") if isinstance(config.get("technical_structure"), dict) else None,
        as_of=structure.get("date"),
    )
    concept_members_payload = _industry_member_payload(
        config,
        output,
        concept_rows,
        structure.get("date"),
        label_mode="concept",
        force_official_members=True,
        allow_selector_fallback=False,
    )
    _attach_industry_amount_metrics(concept_rows)
    primary_symbol = next(iter(concept_kline_payload), "") or next(iter(concept_members_payload), "")
    _write_industry_stock_kline_files(config, output, concept_members_payload, structure.get("date"))
    note_default = "同花顺概念指数行情口径，来源 Tushare ths_daily；概念成分由同花顺维护。"
    note = (
        f"{note_default} 成交额按同花顺概念成分对应的本地个股日线 amount 汇总，amount 为 Tushare 千元口径并换算成人民币；"
        "占比为当前表内全部概念成交额占比，均额为有成交额数据的成分股平均值。"
    )
    return _write_ths_market_mode_data_file(
        output,
        mode="concept",
        row_label="概念",
        ranking_title="概念强弱榜",
        chart_title="概念指数K线与技术指标",
        member_default_title="概念成分股",
        member_empty_text="点击左侧概念查看 Tushare 官方成分股",
        member_empty_message="当前概念没有可用官方成分股：请确认 Tushare ths_member 权限，或稍后重新生成概念行情。",
        panel_hint="同花顺概念指数代理；默认按当日强弱排序；点击表头可排序",
        note=note,
        primary_symbol=primary_symbol,
        rows=concept_rows,
        clickable_symbols=set(concept_kline_payload),
        kline_payload=concept_kline_payload,
        members_payload=concept_members_payload,
    )


def _generate_ths_market_report(
    config: dict,
    structure: dict[str, Any],
    output_path: str | Path,
    *,
    technical_frames: dict[str, pd.DataFrame] | None = None,
    market_kind: str = "industry",
    page_title: str = "行业行情",
    page_subtitle: str = "同花顺行业指数代理 · 行业强弱榜",
    ranking_title: str = "行业强弱榜",
    row_label: str = "行业",
    chart_title: str = "行业指数K线与技术指标",
    member_default_title: str = "行业成分股",
    member_empty_text: str = "点击左侧行业查看本地股票池匹配结果",
    note_default: str = "同花顺行业指数行情口径，来源 Tushare ths_daily；行业成分由同花顺维护。",
    empty_cache_hint: str = "当前行业榜没有可用的同花顺行业指数K线缓存；运行 <code>python main.py index ths</code> 后可点击行业查看K线。",
) -> Path:
    """Generate a standalone 同花顺板块强弱榜 report."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    rankings = (structure.get("industry_rankings") or {}) if market_kind == "industry" else {}
    industry_frames = technical_frames or (
        _default_industry_frames(config, structure)
        if market_kind == "industry"
        else _default_concept_frames(config, structure)
    )
    industry_names = _ths_industry_names(config)
    all_industry_rows = _industry_all_rows(rankings, industry_frames, industry_names, structure.get("date"))
    rankings_for_payload = {**rankings, "all": all_industry_rows}
    index_mode_data = _index_market_data(config, structure)
    industry_technical_payload = _industry_technical_kline_payload(
        pd.DataFrame(),
        rankings_for_payload,
        industry_frames,
        config.get("technical_structure") if isinstance(config.get("technical_structure"), dict) else None,
        as_of=structure.get("date"),
    )
    primary_industry_symbol = next(iter(industry_technical_payload), "")
    clickable_industry_symbols = set(industry_technical_payload)
    industry_members_payload = _industry_member_payload(
        config,
        output,
        all_industry_rows,
        structure.get("date"),
        label_mode="concept" if market_kind == "concept" else "industry",
        force_official_members=market_kind == "concept",
        allow_selector_fallback=market_kind != "concept",
    )
    _attach_industry_amount_metrics(all_industry_rows)
    if not primary_industry_symbol:
        primary_industry_symbol = next(iter(industry_members_payload), "")
    _write_industry_stock_kline_files(config, output, industry_members_payload, structure.get("date"))
    dashboard_href = relative_href(output, Path(config.get("output", {}).get("reports_dir", "output/reports")) / "dashboard.html")
    stock_selector_href = relative_href(output, Path(config.get("output", {}).get("reports_dir", "output/reports")) / "stock_selector.html")
    assets_href = relative_href(output, Path(config.get("output", {}).get("reports_dir", "output/reports")) / "assets" / "echarts.min.js")
    from visual.dashboard import _read_stock_selector

    selector_config = dict(config)
    dashboard_config = dict(config.get("dashboard") or {})
    selector_options = dict(dashboard_config.get("stock_selector") or {})
    selector_options["generate_kline_pages"] = False
    dashboard_config["stock_selector"] = selector_options
    selector_config["dashboard"] = dashboard_config
    stock_selector_data = _read_stock_selector(selector_config, output)
    _attach_stock_selector_kline_hrefs(stock_selector_data, output)
    stock_viewer_html = _embedded_stock_viewer_html(stock_selector_data, stock_selector_href)
    default_kline_title = f"点击上方{row_label}行查看K线"
    restore_label = f"返回{row_label}指数K线"
    member_empty_message = (
        "当前概念没有可用官方成分股：请确认 Tushare ths_member 权限，或稍后重新生成概念行情。"
        if market_kind == "concept"
        else "当前行业没有可用成分股：优先读取 Tushare ths_member 官方同花顺成分；若不可用，再用本地股票池行业标签近似匹配。"
    )
    mode_loader_href = ""
    if market_kind == "industry":
        mode_loader_href = relative_href(output, _build_concept_mode_data(config, structure, output))
    initial_note = (
        f"{rankings.get('method_note', note_default)} 成交额按同花顺{row_label}成分对应的本地个股日线 amount 汇总，amount 为 Tushare 千元口径并换算成人民币；"
        f"占比为当前表内全部{row_label}成交额占比，均额为有成交额数据的成分股平均值。"
    )
    mode_switch_html = (
        """
          <div class="ths-market-mode-switch" aria-label="行情类型">
            <button type="button" class="ths-market-mode-btn active" data-ths-market-mode="industry" onclick="switchThsMarketMode('industry')">行业行情</button>
            <button type="button" class="ths-market-mode-btn" data-ths-market-mode="concept" onclick="switchThsMarketMode('concept')">概念行情</button>
            <button type="button" class="ths-market-mode-btn" data-ths-market-mode="watch" onclick="switchThsMarketMode('watch')">关注池行情</button>
            <button type="button" class="ths-market-mode-btn" data-ths-market-mode="index" onclick="switchThsMarketMode('index')">指数行情</button>
            <button type="button" class="ths-market-mode-btn" data-ths-market-mode="stock" onclick="switchThsMarketMode('stock')">股票查看</button>
          </div>
        """
        if market_kind == "industry"
        else ""
    )
    default_table_head_html = _industry_market_table_head(row_label)
    industry_chart_html = (
        f"""
        <div class="industry-chart-head">
          <div class="industry-chart-title"><span id="ths-market-chart-title">{escape(chart_title)}</span><small id="industry-kline-title">{escape(default_kline_title)}</small></div>
          <div class="indicator-switches"><strong>周期</strong><button type="button" class="kline-period-btn industry-period-btn active" data-timeframe="1d" onclick="switchIndustryTimeframe('1d')">日K</button><button type="button" class="kline-period-btn industry-period-btn" data-timeframe="1w" onclick="switchIndustryTimeframe('1w')">周K</button><button type="button" class="kline-period-btn industry-period-btn" data-timeframe="1mo" onclick="switchIndustryTimeframe('1mo')">月K</button><strong>技术指标</strong><button type="button" class="industry-indicator-switch active" data-indicator="volume" onclick="switchIndustryIndicator('volume')">成交量</button><button type="button" class="industry-indicator-switch" data-indicator="kdj" onclick="switchIndustryIndicator('kdj')">KDJ</button><button type="button" class="industry-indicator-switch" data-indicator="macd" onclick="switchIndustryIndicator('macd')">MACD</button></div>
        </div>
        <div class="forecast-manual-tools industry-manual-toolbar">
          <strong>画线</strong>
          <button class="forecast-manual-btn" data-tool="trend" type="button" onclick="setForecastManualTool('trend')">趋势线</button>
          <button class="forecast-manual-btn" data-tool="support" type="button" onclick="setForecastManualTool('support')">支撑线</button>
          <button class="forecast-manual-btn" data-tool="resistance" type="button" onclick="setForecastManualTool('resistance')">阻力线</button>
          <button class="forecast-manual-btn" type="button" onclick="setForecastManualTool(null)">选择/调整</button>
          <button class="forecast-manual-btn" type="button" onclick="forecastManualUndo()">撤销</button>
          <button class="forecast-manual-btn danger" type="button" onclick="forecastManualClear()">清空本周期</button>
          <span id="forecast-manual-status" class="forecast-manual-status">选择工具后在行业 K 线图点击画线；画完可拖动圆点调整。</span>
        </div>
        <div id="industry-stock-kline-shell" class="industry-stock-kline-shell">
          <div class="industry-stock-kline-bar">
            <strong id="industry-stock-kline-label">个股K线</strong>
            <div class="industry-stock-kline-actions">
              <div class="industry-stock-period-switches">
                <button class="industry-stock-period-btn active" data-industry-stock-period="1d" type="button" onclick="switchIndustryStockPeriod('1d')">日K</button>
                <button class="industry-stock-period-btn" data-industry-stock-period="1w" type="button" onclick="switchIndustryStockPeriod('1w')">周K</button>
                <button class="industry-stock-period-btn" data-industry-stock-period="1m" type="button" onclick="switchIndustryStockPeriod('1m')">月K</button>
              </div>
              <button type="button" onclick="restoreIndustryIndexKline()">{escape(restore_label)}</button>
            </div>
          </div>
          <div class="industry-stock-drawing-tools">
            <strong>画线</strong>
            <button class="industry-stock-drawing-btn" data-industry-stock-draw="trend" type="button" onclick="industryStockSetDrawMode('trend')">趋势线</button>
            <button class="industry-stock-drawing-btn" data-industry-stock-draw="support" type="button" onclick="industryStockSetDrawMode('support')">支撑线</button>
            <button class="industry-stock-drawing-btn" data-industry-stock-draw="resistance" type="button" onclick="industryStockSetDrawMode('resistance')">阻力线</button>
            <button class="industry-stock-drawing-btn" data-industry-stock-draw="select" type="button" onclick="industryStockSetDrawMode('select')">选择/调整</button>
            <button class="industry-stock-drawing-btn" type="button" onclick="industryStockUndoDrawing()">撤销</button>
            <button class="industry-stock-drawing-btn danger" type="button" onclick="industryStockClearDrawings()">清空本周期</button>
            <span id="industry-stock-drawing-status" class="industry-stock-drawing-status">画线按当前周期本地保存。</span>
          </div>
          <div id="industry-stock-kline-empty" class="industry-stock-kline-empty" style="display:none"></div>
          <div class="industry-stock-chart-wrap">
            <div id="industry-stock-kline" class="industry-stock-kline-chart"></div>
            <svg id="industry-stock-drawing-layer" class="industry-stock-drawing-layer"></svg>
          </div>
        </div>
        <div id="industry-kline" class="chart"></div>
        <div id="industry-indicator" class="chart industry-indicator"></div>
        """
        if industry_technical_payload
        else f"<div class='industry-chart-empty'>{empty_cache_hint}</div>"
    )
    body = f"""
    <main class="shell industry-market-shell">
      <header class="topbar">
        <div>
          <h1>{escape(page_title)}</h1>
          <div class="sub">{escape(page_subtitle)} · 数据截至 {escape(str(structure.get('date', '--')))}</div>
        </div>
        <div class="top-actions">
          <a href="{escape(dashboard_href, quote=True)}">返回 Dashboard</a>
        </div>
      </header>

      <section class="panel">
        <div class="panel-head">
          <div class="ths-market-title-row"><h2 id="ths-market-ranking-title">{escape(ranking_title)}</h2>{mode_switch_html}</div>
          <span id="ths-market-panel-hint">同花顺{escape(row_label)}指数代理；默认按当日强弱排序；点击表头可排序</span>
        </div>
        <div id="ths-market-note" class="industry-market-note">{escape(initial_note)}</div>
        <div id="ths-market-pane" class="ths-mode-pane">
          <div class="ths-market-tools">
            <div class="ths-market-search">
              <input id="ths-market-search" type="search" placeholder="搜索行业/概念、代码" oninput="filterThsMarketRows()">
              <button class="ths-tool-btn" type="button" onclick="clearThsMarketSearch()">清空</button>
              <button id="ths-watch-only-btn" class="ths-tool-btn" type="button" onclick="toggleThsWatchOnly()">只看关注</button>
              <span id="ths-market-filter-status" class="ths-market-filter-status">显示全部</span>
            </div>
            <div class="ths-watch-pool">
              <strong>关注池</strong>
              <div id="ths-watch-pool-chips" class="ths-watch-pool-chips"><span class="ths-watch-empty">暂无关注</span></div>
            </div>
          </div>
          <div class="industry-market-overview-grid">
            <div class="v2-table-wrap compact industry-market-table-wrap">
              <table id="industry-market-table" class="industry-market-table" data-sort-key="return_1d" data-sort-direction="desc">
                <thead id="industry-market-thead">{default_table_head_html}</thead>
                <tbody>{_industry_market_rows(all_industry_rows, clickable_industry_symbols, empty_label=row_label)}</tbody>
              </table>
            </div>
            <aside class="industry-member-panel">
              <div class="industry-member-head">
                <strong id="industry-member-title">{escape(member_default_title)}</strong>
                <span id="industry-member-sub">{escape(member_empty_text)}</span>
              </div>
              <div id="industry-member-list" class="industry-member-list">
                <div class="industry-member-empty">正在初始化成分股列表。</div>
              </div>
            </aside>
          </div>
        </div>
        {stock_viewer_html}
        {industry_chart_html}
      </section>
    </main>
    """
    html = html_document(
        title=page_title,
        body=body,
        styles=_CSS + _INDUSTRY_CSS,
        head_extra=script_src(assets_href) + '<link rel="icon" href="data:,">',
        scripts=(
            inline_script(
                "window._FORECAST_CHART={};"
                "window._MARKET_STRUCTURE={};"
                "window._INDEX_LIFT_STRUCTURE={\"by_symbol\":{}};"
                "window._PRIMARY_TECHNICAL_INDEX=\"\";"
                "window._TECHNICAL_INDEX_KLINES={};"
                "window._TECHNICAL_KLINES={};"
                f"window._THS_MARKET_LABEL={to_compact_json(row_label)};"
                f"window._THS_MEMBER_EMPTY_MESSAGE={to_compact_json(member_empty_message)};"
                f"window._THS_MARKET_MODE={to_compact_json(market_kind)};"
                f"window._PRIMARY_INDUSTRY_INDEX={to_compact_json(primary_industry_symbol)};"
                f"window._INDUSTRY_KLINES={to_compact_json(industry_technical_payload)};"
                f"window._INDUSTRY_MEMBERS={to_compact_json(industry_members_payload)};"
                "window._THS_MARKET_MODE_DATA={};"
                f"window._THS_MARKET_MODE_DATA[{to_compact_json(market_kind)}]="
                "{"
                f"\"mode\":{to_compact_json(market_kind)},"
                f"\"rowLabel\":{to_compact_json(row_label)},"
                f"\"rankingTitle\":{to_compact_json(ranking_title)},"
                f"\"chartTitle\":{to_compact_json(chart_title)},"
                f"\"memberDefaultTitle\":{to_compact_json(member_default_title)},"
                f"\"memberEmptyText\":{to_compact_json(member_empty_text)},"
                f"\"memberEmptyMessage\":{to_compact_json(member_empty_message)},"
                f"\"panelHint\":{to_compact_json(f'同花顺{row_label}指数代理；默认按当日强弱排序；点击表头可排序')},"
                f"\"note\":{to_compact_json(initial_note)},"
                "\"primary\":window._PRIMARY_INDUSTRY_INDEX,"
                f"\"rowsHtml\":{to_compact_json(_industry_market_rows(all_industry_rows, clickable_industry_symbols, empty_label=row_label))},"
                "\"klines\":window._INDUSTRY_KLINES,"
                "\"members\":window._INDUSTRY_MEMBERS"
                "};"
                f"window._THS_MARKET_MODE_DATA['index']={to_compact_json(index_mode_data)};"
                f"window._THS_MARKET_DEFAULT_HEAD_HTML={to_compact_json(default_table_head_html)};"
                f"window._THS_MARKET_MODE_LOADERS={to_compact_json({'concept': mode_loader_href} if mode_loader_href else {})};"
                "window._INDUSTRY_STOCK_KLINES={};"
            )
            + inline_script(_INDUSTRY_MARKET_JS)
            + _JS_V11
            + inline_script(_INDUSTRY_MARKET_POST_JS)
            + json_script_data(stock_selector_data, "stock-viewer-data")
            + _embedded_stock_viewer_script("stock-viewer-data")
        ),
    )
    output.write_text(html, encoding="utf-8")
    return output


def generate_industry_market_report(
    config: dict,
    structure: dict[str, Any],
    output_path: str | Path,
    *,
    technical_industry_frames: dict[str, pd.DataFrame] | None = None,
) -> Path:
    """Generate the standalone industry market report from market-structure facts."""
    return _generate_ths_market_report(
        config,
        structure,
        output_path,
        technical_frames=technical_industry_frames,
        market_kind="industry",
        page_title="行业行情",
        page_subtitle="同花顺行业指数代理 · 行业强弱榜",
        ranking_title="行业强弱榜",
        row_label="行业",
        chart_title="行业指数K线与技术指标",
        member_default_title="行业成分股",
        member_empty_text="点击左侧行业查看本地股票池匹配结果",
        note_default="同花顺行业指数行情口径，来源 Tushare ths_daily；行业成分由同花顺维护。",
        empty_cache_hint="当前行业榜没有可用的同花顺行业指数K线缓存；运行 <code>python main.py index ths</code> 后可点击行业查看K线。",
    )


def generate_concept_market_report(
    config: dict,
    structure: dict[str, Any],
    output_path: str | Path,
    *,
    technical_concept_frames: dict[str, pd.DataFrame] | None = None,
) -> Path:
    """Generate the standalone 同花顺概念指数行情强弱榜."""
    return _generate_ths_market_report(
        config,
        structure,
        output_path,
        technical_frames=technical_concept_frames,
        market_kind="concept",
        page_title="概念行情",
        page_subtitle="同花顺概念指数代理 · 概念强弱榜",
        ranking_title="概念强弱榜",
        row_label="概念",
        chart_title="概念指数K线与技术指标",
        member_default_title="概念成分股",
        member_empty_text="点击左侧概念查看本地股票池匹配结果",
        note_default="同花顺概念指数行情口径，来源 Tushare ths_daily；概念成分由同花顺维护。",
        empty_cache_hint="当前概念榜没有可用的同花顺概念指数K线缓存；可先运行 <code>python main.py index ths --include-concepts</code> 下载概念指数日线。",
    )
