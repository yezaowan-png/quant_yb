"""Standalone HTML report for market_risk_gate research."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from visual.components import html_document


_CSS = """
body{margin:0;background:#f4f6f8;color:#172033;font-family:"Microsoft YaHei","PingFang SC",sans-serif}
.shell{width:min(1500px,calc(100vw - 40px));margin:auto;padding:28px 0 46px}.hero,.panel{background:#fff;border:1px solid #d9e0ea;margin-bottom:18px;padding:18px}
h1,h2{margin:0 0 12px}.sub,.note{color:#667085;line-height:1.7}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.card{background:#fff;border:1px solid #d9e0ea;padding:15px}.card b{display:block;font-size:22px;margin-top:8px}
table{width:100%;border-collapse:collapse;font-size:12px;overflow:auto}th,td{padding:8px 10px;border-bottom:1px solid #edf0f5;text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}th{background:#fafbfc;color:#667085}
.bad{color:#b42318}.good{color:#067647}@media(max-width:900px){.cards{grid-template-columns:1fr 1fr}.panel{overflow:auto}}
"""


def _table(frame: pd.DataFrame, limit: int = 200) -> str:
    if frame.empty:
        return "<p class='note'>暂无数据</p>"
    shown = frame.head(limit)
    headers = "".join(f"<th>{escape(str(column))}</th>" for column in shown.columns)
    rows = []

    def display(value: Any) -> str:
        if isinstance(value, (list, tuple, dict, set)):
            return str(value)
        try:
            return "" if bool(pd.isna(value)) else str(value)
        except (TypeError, ValueError):
            return str(value)

    for _, row in shown.iterrows():
        cells = "".join(
            f"<td>{escape(display(value))}</td>" for value in row
        )
        rows.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def generate_market_risk_report(
    output_path: str | Path,
    symbol: str,
    state_payload: dict[str, Any],
    summary: pd.DataFrame,
    gates: pd.DataFrame,
    automatic_decision: str,
    experiment: str | None = None,
    details: Mapping[str, pd.DataFrame] | None = None,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cards = [
        ("当前状态", state_payload.get("current_state", "--")),
        ("风险等级", state_payload.get("risk_level", "--")),
        ("风险分", state_payload.get("risk_score", "--")),
        ("自动门槛", automatic_decision),
    ]
    section_titles = {
        "folds": "Walk-forward 逐折结果",
        "baselines": "冻结基线",
        "coefficients": "模型系数",
        "yearly": "年度稳定性",
        "volatility": "波动状态稳定性",
        "universe": "有效股票数与时期敏感性",
        "strategies": "策略 A-E 对照",
    }
    detail_html = "".join(
        f"<section class='panel'><h2>{escape(section_titles.get(name, name))}</h2>{_table(frame)}</section>"
        for name, frame in (details or {}).items()
        if isinstance(frame, pd.DataFrame)
    )
    body = f"""
    <main class='shell'>
      <section class='hero'><h1>{escape(symbol.upper())} 市场极端风险闸门</h1>
      <div class='sub'>独立研究模块 · green 不代表看多，red 不代表做空 · 正式环境信号和仓位逻辑保持不变</div></section>
      <section class='cards'>{''.join(f"<div class='card'><span>{escape(str(k))}</span><b>{escape(str(v))}</b></div>" for k,v in cards)}</section>
      <section class='panel'><h2>当前模拟政策</h2>{_table(pd.DataFrame([state_payload]))}</section>
      <section class='panel'><h2>实验矩阵汇总</h2>{_table(summary)}</section>
      <section class='panel'><h2>自动门槛</h2>{_table(gates)}</section>
      {detail_html}
      <section class='panel note'>
      概率字段只在自然类别概率或严格嵌套校准有效时输出；否则仅输出 risk_score。
      数据存在 incomplete_point_in_time_universe、missing_delisted_stocks 和 missing_historical_st_status 限制。
      本报告不得表述为完整历史 A 股真实风险表现，也不会自动接入正式策略。
      </section>
    </main>
    """
    path.write_text(html_document(title=f"{symbol.upper()} 市场极端风险闸门", body=body, styles=_CSS), encoding="utf-8")
    return path
