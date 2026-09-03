"""HTML report for market risk gate validity and block-random falsification tests."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

import pandas as pd

from visual.components import html_document


_CSS = """
body{margin:0;background:#f4f6f8;color:#172033;font-family:"Microsoft YaHei","PingFang SC",sans-serif}
.shell{width:min(1550px,calc(100vw - 40px));margin:auto;padding:28px 0 46px}.hero,.panel,.card{background:#fff;border:1px solid #d9e0ea}.hero,.panel{padding:18px;margin-bottom:18px}
h1,h2{margin:0 0 12px}.sub,.note{color:#667085;line-height:1.7}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:18px}.card{padding:15px}.card b{display:block;font-size:20px;margin-top:8px;overflow-wrap:anywhere}
table{width:100%;border-collapse:collapse;font-size:12px}th,td{padding:8px 10px;border-bottom:1px solid #edf0f5;text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}th{background:#fafbfc;color:#667085}
@media(max-width:900px){.cards{grid-template-columns:1fr 1fr}.panel{overflow:auto}}
"""


def _display(value: Any) -> str:
    if isinstance(value, (list, tuple, dict, set)):
        return str(value)
    try:
        return "" if bool(pd.isna(value)) else str(value)
    except (TypeError, ValueError):
        return str(value)


def _table(frame: pd.DataFrame, limit: int = 200) -> str:
    if frame.empty:
        return "<p class='note'>暂无数据</p>"
    shown = frame.head(limit)
    headers = "".join(f"<th>{escape(str(column))}</th>" for column in shown.columns)
    rows = "".join(
        "<tr>" + "".join(f"<td>{escape(_display(value))}</td>" for value in row) + "</tr>"
        for _, row in shown.iterrows()
    )
    return f"<table><thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table>"


def generate_market_risk_validity_report(
    output_path: str | Path,
    symbol: str,
    result: dict[str, Any],
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    qualification = result["qualification"].iloc[0]
    core = result["core_metrics"].iloc[0]
    cards = [
        ("资格结论", qualification.get("qualification")),
        ("风险 Episode", core.get("episode_count")),
        ("Episode Precision", core.get("episode_precision")),
        ("随机模拟", qualification.get("simulation_count")),
    ]
    sections = [
        ("资格判定", result["qualification"]),
        ("核心风险事件指标", result["core_metrics"]),
        ("Measurement validity", result["measurement_checks"]),
        ("当日压力分级明细", result["measurement"]),
        ("Predictive validity", result["predictive_checks"]),
        ("各状态未来风险明细", result["predictive"]),
        ("风险 Episodes", result["episodes"]),
        ("Episode 命中、误报和提前量", result["episode_details"]),
        ("真实结果相对区块随机分布", result["random_comparison"]),
        ("冻结简单规则逐项对照", result["simple_rules"]),
        ("真实策略同暴露决策效用", result["decision_utility"]),
        ("LOCO/LOYO/时期/波动/牛熊/Offset 稳定性", result["stability"]),
        ("区块随机模拟样例（前200组）", result["random_distribution"]),
    ]
    body = f"""
    <main class='shell'>
      <section class='hero'><h1>{escape(symbol.upper())} 风险闸门有效性与随机性检验</h1>
      <div class='sub'>目标是证伪风险闸门是否只是随机结果。Measurement validity 不等于 Predictive validity，状态看起来合理不能作为策略接入依据。</div></section>
      <section class='cards'>{''.join(f"<div class='card'><span>{escape(str(k))}</span><b>{escape(_display(v))}</b></div>" for k,v in cards)}</section>
      {''.join(f"<section class='panel'><h2>{escape(title)}</h2>{_table(frame)}</section>" for title,frame in sections)}
      <section class='panel note'>随机警报保持真实 episode 数量、起始年份数量和持续时间分布，使用至少5个交易日区块放置，不进行逐日 IID 随机。所有策略动作滞后一个交易日。当前明确禁止输出 hard_gate_candidate。</section>
      <section class='panel note'>数据限制：incomplete_point_in_time_universe、missing_delisted_stocks、missing_historical_st_status。结果不能表述为完整历史 A 股真实风险表现。</section>
    </main>
    """
    path.write_text(
        html_document(title=f"{symbol.upper()} 风险闸门有效性检验", body=body, styles=_CSS),
        encoding="utf-8",
    )
    return path
