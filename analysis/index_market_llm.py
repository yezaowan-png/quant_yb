"""LLM-ready summaries for the index market-structure report.

The module deliberately separates deterministic market facts from model-written
commentary.  The LLM receives a compact fact package and a fixed writing
instruction; it must not recompute indicators or feed back into trading logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request
from typing import Any


DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"


@dataclass(frozen=True)
class LLMSummaryPaths:
    facts: Path
    prompt: Path
    summary: Path
    html: Path


def llm_summary_paths(config: dict[str, Any], symbol: str, horizon: int = 5) -> LLMSummaryPaths:
    reports_dir = Path(config.get("output", {}).get("reports_dir", "output/reports")) / "index_forecast"
    prefix = reports_dir / f"{symbol.upper()}_h{int(horizon)}_market_structure"
    return LLMSummaryPaths(
        facts=Path(f"{prefix}_llm_input.md"),
        prompt=Path(f"{prefix}_llm_prompt.md"),
        summary=Path(f"{prefix}_llm_summary.md"),
        html=Path(f"{prefix}_llm_summary.html"),
    )


def market_structure_json_path(config: dict[str, Any], symbol: str) -> Path:
    stats_dir = Path(config.get("output", {}).get("statistics_dir", "output/statistics"))
    return stats_dir / "index_forecast" / f"market_structure_{symbol.upper()}.json"


def load_market_structure_json(config: dict[str, Any], symbol: str) -> dict[str, Any]:
    path = market_structure_json_path(config, symbol)
    if not path.exists():
        raise FileNotFoundError(f"市场结构 JSON 不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _dotenv_value(env_name: str, config: dict[str, Any] | None = None) -> str | None:
    """Read a single key from a local dotenv file without echoing secrets."""
    candidate_paths: list[Path] = []
    llm_cfg = ((config or {}).get("llm_summary") or {})
    dotenv_path = llm_cfg.get("dotenv_path")
    if dotenv_path:
        candidate_paths.append(Path(str(dotenv_path)))
    candidate_paths.append(Path.cwd() / ".env.local")
    for path in candidate_paths:
        if not path.exists() or not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if key.strip() != env_name:
                continue
            cleaned = value.strip().strip('"').strip("'")
            if cleaned:
                return cleaned
    return None


def _api_key_from_env_or_dotenv(env_name: str, config: dict[str, Any] | None = None) -> str | None:
    return os.getenv(env_name) or _dotenv_value(env_name, config)


def _num(value: Any, digits: int = 2, suffix: str = "") -> str:
    try:
        if value is None:
            return "--"
        number = float(value)
        if number != number:
            return "--"
        return f"{number:.{digits}f}{suffix}"
    except Exception:
        return "--"


def _pct(value: Any, digits: int = 2, signed: bool = True) -> str:
    try:
        if value is None:
            return "--"
        number = float(value) * 100
        if number != number:
            return "--"
        sign = "+" if signed else ""
        return f"{number:{sign}.{digits}f}%"
    except Exception:
        return "--"


def _cn(mapping: dict[str, str], value: Any, default: str = "数据不足") -> str:
    return mapping.get(str(value), default)


def _state_name(value: Any) -> str:
    return _cn(
        {
            "up": "上升",
            "down": "下降",
            "uptrend": "上升",
            "downtrend": "下降",
            "sideways": "震荡",
            "bull": "偏强",
            "bear": "偏弱",
            "neutral": "中性",
            "strong": "强势",
            "weak": "弱势",
            "very_weak": "很弱",
            "very_strong": "很强",
            "outperforming": "强于基准",
            "underperforming": "弱于基准",
            "pullback": "回调",
            "mixed": "分化",
            "expanding": "正在扩散",
            "contracting": "正在收缩",
            "repairing": "正在修复",
            "stable": "相对稳定",
            "low": "较低",
            "medium": "中等",
            "high": "较高",
            "extreme": "极端",
        },
        value,
        str(value) if value is not None else "数据不足",
    )


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return ""
    head = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join(["---"] * len(headers)) + " |"
    body = ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join([head, sep, *body])


def _latest_style_strength(structure: dict[str, Any], key: str) -> Any:
    rows = structure.get("style_history") or []
    column = f"{key}_strength"
    for row in reversed(rows):
        value = row.get(column)
        if value is not None:
            return value
    return None


def _append_v2_fact_sections(lines: list[str], structure: dict[str, Any]) -> bool:
    """Append the deterministic v2 facts consumed by the downstream writer.

    This remains a serialization step only: no state is recalculated here and
    research candidates are explicitly separated from the formal description.
    """
    if str(structure.get("schema_version") or "") != "market_structure_v2":
        return False

    state = structure.get("market_structure") or {}
    evidence = state.get("evidence") or {}
    summary = structure.get("deterministic_summary") or {}
    lines.extend(
        [
            "",
            "## 7. v2确定性状态总表",
            "",
            f"- Schema：{structure.get('schema_version')}；算法版本：{structure.get('algorithm_version') or '--'}",
            f"- 配置哈希：{structure.get('config_hash') or '--'}；数据哈希：{structure.get('data_hash') or '--'}",
            "- 状态用途：描述已经发生的结构；置信度表示证据完整性与一致性，不是未来概率。",
        ]
    )
    if summary.get("headline"):
        lines.append(f"- 确定性摘要：{summary.get('headline')}")
    state_rows: list[list[str]] = []
    for key, label in (
        ("participation", "参与度"),
        ("concentration", "集中度"),
        ("breadth", "全A广度"),
        ("leadership", "主线质量"),
        ("risk", "风险阶段"),
        ("repair", "修复阶段"),
        ("divergence", "指数/个股分化"),
    ):
        item = state.get(key) or {}
        tracker = item.get("state_tracker") or {}
        proof = evidence.get(key) or {}
        state_rows.append(
            [
                label,
                str(item.get("state") or "unknown"),
                str(tracker.get("duration_days") or tracker.get("duration_trading_days") or "--"),
                str(tracker.get("transition_date") or tracker.get("last_transition_date") or "--"),
                _num(tracker.get("stability_score"), 2),
                str(proof.get("confidence") or "--"),
                _num(proof.get("confidence_score"), 2),
            ]
        )
    lines.extend(
        [
            "",
            _table(["维度", "状态", "持续交易日", "最近切换", "稳定分", "证据置信", "置信分"], state_rows),
        ]
    )

    layer_rows: list[list[str]] = []
    for layer_name, item in (structure.get("layered_breadth") or {}).items():
        latest = item.get("latest") or {}
        layer_rows.append(
            [
                str(layer_name),
                str(item.get("state") or latest.get("state") or "unknown"),
                str(latest.get("effective_count") or latest.get("valid_count") or "--"),
                _pct(latest.get("advance_ratio"), signed=False),
                _pct(latest.get("pct_above_ma20"), signed=False),
                _pct(latest.get("pct_above_ma60"), signed=False),
                _pct(latest.get("new_high_20_ratio"), signed=False),
                _pct(latest.get("new_low_20_ratio"), signed=False),
                _pct(latest.get("equal_weight_return_1d")),
                str(item.get("membership_snapshot_date") or "--"),
                "是" if item.get("composition_point_in_time") else "否/近似",
            ]
        )
    lines.extend(
        [
            "",
            "## 8. v2分层广度",
            "",
            _table(["层级", "状态", "有效数", "上涨占比", "MA20上", "MA60上", "20日新高", "20日新低", "等权1日", "成分快照", "PIT"], layer_rows),
        ]
    )

    concentration = structure.get("contribution_analysis") or {}
    c_latest = concentration.get("latest") or {}
    distribution = structure.get("return_distribution") or {}
    d_latest = distribution.get("latest") or {}
    liquidity = structure.get("liquidity_structure") or {}
    q_latest = liquidity.get("latest") or {}
    lines.extend(
        [
            "",
            "## 9. v2贡献、分布与流动性",
            "",
            f"- 集中度状态：{concentration.get('state') or 'unknown'}；综合历史分位：{_pct(c_latest.get('concentration_percentile'), signed=False)}；前10%股票成交占比：{_pct(c_latest.get('top_10pct_turnover_share'), signed=False)}；前三行业正贡献占比：{_pct(c_latest.get('top3_industry_positive_contribution_share'), signed=False)}；权重HHI：{_num(c_latest.get('weight_hhi'), 3)}。",
            f"- 当日收益分布：{distribution.get('state') or 'unknown'}；中位数：{_pct(d_latest.get('median'))}；Q10/Q90：{_pct(d_latest.get('q10'))} / {_pct(d_latest.get('q90'))}；标准差：{_pct(d_latest.get('std'), signed=False)}；偏度：{_num(d_latest.get('skew'), 2)}。",
            f"- 流动性结构：{liquidity.get('state') or 'unknown'}；成交额/20日均值：{_num(q_latest.get('amount_ratio_20d'), 2)}倍；上涨/下跌成交占比：{_pct(q_latest.get('advance_amount_ratio'), signed=False)} / {_pct(q_latest.get('decline_amount_ratio'), signed=False)}；新高/新低成交占比：{_pct(q_latest.get('new_high_amount_share'), signed=False)} / {_pct(q_latest.get('new_low_amount_share'), signed=False)}。",
        ]
    )

    rotation = structure.get("style_rotation") or {}
    rotation_rows: list[list[str]] = []
    for style_name, item in (rotation.get("styles") or {}).items():
        latest = item.get("latest") or {}
        rotation_rows.append(
            [
                str(style_name),
                str(item.get("state") or "unknown"),
                _num(latest.get("level"), 1),
                _num(latest.get("change_5d"), 1),
                _pct(latest.get("relative_slope_20d")),
                _pct(latest.get("acceleration")),
                str(item.get("leadership_quality") or "--"),
            ]
        )
    risk = state.get("risk") or {}
    risk_latest = risk.get("latest") or {}
    repair = state.get("repair") or {}
    repair_latest = repair.get("latest") or {}
    lines.extend(
        [
            "",
            "## 10. v2风格轮动与风险修复",
            "",
            f"- 当前风格领涨：{rotation.get('leader') or '--'}；连续领涨：{rotation.get('days_as_leader') or 0}日；20/60日领涨切换：{rotation.get('leader_changes_20d') or rotation.get('leader_change_count_20d') or 0} / {rotation.get('leader_changes_60d') or rotation.get('leader_change_count_60d') or 0}。",
            _table(["风格", "轮动状态", "强度", "5日变化", "20日相对斜率", "加速度", "主线质量"], rotation_rows),
            "",
            f"- 风险阶段：{risk.get('state') or 'unknown'}；原始/3日/5日风险分：{_num(risk_latest.get('risk_score_raw') or risk_latest.get('raw_score'), 1)} / {_num(risk_latest.get('risk_score_smoothed_3d') or risk_latest.get('smooth_3d'), 1)} / {_num(risk_latest.get('risk_score_smoothed_5d') or risk_latest.get('smooth_5d'), 1)}；5日变化：{_num(risk_latest.get('risk_change_5d') or risk_latest.get('change_5d'), 1)}。",
            f"- 修复阶段：{repair.get('state') or 'unknown'}；新低5日变化：{_pct(repair_latest.get('new_low_change_5d'))}；MA20上方比例5日变化：{_pct(repair_latest.get('pct_above_ma20_change_5d'))}；风险再扩散：{'是' if repair_latest.get('risk_reexpanding') else '否'}。",
        ]
    )

    freshness_rows = [
        [
            str(source_key),
            str(item.get("status") or "missing"),
            str(item.get("data_date") or "--"),
            str(item.get("as_of_date") or item.get("as_of") or "--"),
            str(item.get("lag_trading_days") if item.get("lag_trading_days") is not None else "--"),
            "是" if item.get("point_in_time") else "否",
            str(item.get("limitation") or "--"),
        ]
        for source_key, item in (structure.get("source_freshness") or {}).items()
    ]
    point_in_time = structure.get("point_in_time") or {}
    lines.extend(
        [
            "",
            "## 11. v2数据新鲜度与时点边界",
            "",
            _table(["数据源", "状态", "数据日", "分析日", "滞后交易日", "PIT", "限制"], freshness_rows),
            "",
            "- PIT总览：" + "；".join(f"{key}={'是' if value else '否'}" for key, value in point_in_time.items()),
        ]
    )

    candidate_rows = [
        [
            str(name),
            str(item.get("phase") or "none"),
            "是" if item.get("exploratory_only") else "否",
            str(item.get("leader") or "--"),
        ]
        for name, item in (structure.get("research_candidates") or {}).items()
    ]
    lines.extend(
        [
            "",
            "## 12. 仅供研究的候选相位",
            "",
            "- 以下字段全部是 exploratory_only，只能作为后续验证线索，不得写成正式市场状态、收益预测或交易信号。",
            _table(["候选", "相位", "仅探索", "补充"], candidate_rows),
            "",
            f"- 估值接口：{(structure.get('valuation_context') or {}).get('status') or 'unknown'}；外部资金/期权/情绪接口：{(structure.get('external_context') or {}).get('status') or 'unknown'}。缺失时保持unknown，不允许中性填充。",
            "- 隔离检查：LLM调用数=" + str(structure.get("llm_calls", 0))
            + "；正式策略影响=" + str(bool(structure.get("formal_strategy_influence")))
            + "；仓位/订单影响=" + str(bool(structure.get("position_or_order_influence")))
            + "；市场风险闸门影响=" + str(bool(structure.get("market_risk_gate_influence"))) + "。",
        ]
    )
    return True


def build_llm_fact_markdown(structure: dict[str, Any], symbol: str, name: str | None = None) -> str:
    """Create a compact, model-friendly fact package in Markdown."""
    date = structure.get("date") or "--"
    state = structure.get("market_structure") or {}
    trend = state.get("trend") or {}
    breadth_state = state.get("breadth") or {}
    risk = state.get("risk") or {}
    divergence = state.get("divergence") or {}
    latest = ((structure.get("breadth") or {}).get("latest") or {})

    lines: list[str] = [
        f"# A股市场结构事实包",
        "",
        f"- 标的：{name or symbol}（{symbol.upper()}）",
        f"- 数据日期：{date}",
        "- 用途：供大模型撰写复盘总结；只描述市场结构，不生成交易指令。",
        "",
        "## 1. 总状态",
        "",
        f"- 系统总判断：{state.get('style_regime_name') or state.get('legacy_style_regime_name') or '--'}",
        f"- 权重指数日线趋势：{_state_name(trend.get('large_cap_daily'))}；周线趋势：{_state_name(trend.get('large_cap_weekly'))}",
        f"- 成长指数日线趋势：{_state_name(trend.get('growth_daily'))}；周线趋势：{_state_name(trend.get('growth_weekly'))}",
        f"- 当日赚钱效应：{_state_name(breadth_state.get('today_state'))}",
        f"- 5日市场广度：{_state_name(breadth_state.get('short_5d_state'))}",
        f"- 20日市场广度：{_state_name(breadth_state.get('medium_20d_state'))}",
        f"- 尾部压力等级：{_state_name(risk.get('pressure_level'))}",
        f"- 风险扩散方向：{_state_name(risk.get('risk_direction'))}",
        f"- 指数与个股分化：{divergence.get('summary') or '--'}",
    ]
    headline = state.get("headline")
    if headline:
        lines.extend(["", f"> 程序原始摘要：{headline}"])

    indices = structure.get("indices") or {}
    index_rows: list[list[str]] = []
    for index_name, item in indices.items():
        index_rows.append(
            [
                str(index_name),
                str(item.get("symbol") or "--"),
                _pct(item.get("return_1d")),
                _pct(item.get("return_5d")),
                _pct(item.get("return_10d")),
                _pct(item.get("return_20d")),
                _pct(item.get("return_60d")),
                _state_name(item.get("daily_trend")),
                _state_name(item.get("weekly_trend")),
            ]
        )
    lines.extend(
        [
            "",
            "## 2. 主要指数强弱",
            "",
            _table(["指数", "代码", "1日", "5日", "10日", "20日", "60日", "日线", "周线"], index_rows),
        ]
    )

    style_key_map = {
        "权重价值": "value",
        "证券风险偏好": "securities",
        "科技成长": "growth",
        "消费": "consumer",
        "小盘题材": "small_cap",
    }
    style_rows: list[list[str]] = []
    for style_name, item in (structure.get("styles") or {}).items():
        key = style_key_map.get(style_name, str(item.get("key") or ""))
        style_rows.append(
            [
                str(style_name),
                _pct(item.get("return_5d")),
                _pct(item.get("return_20d")),
                _pct(item.get("return_60d")),
                _state_name(item.get("state_5d")),
                _state_name(item.get("state_20d")),
                _state_name(item.get("state_60d")),
                _pct(item.get("relative_all_a_20d")),
                _num(item.get("strength") if item.get("strength") is not None else _latest_style_strength(structure, key), 1),
                str(item.get("proxy_note") or item.get("basket_type") or "--"),
            ]
        )
    lines.extend(
        [
            "",
            "## 3. 市场风格",
            "",
            _table(["风格", "5日", "20日", "60日", "5日状态", "20日状态", "60日状态", "相对平均股价20日", "强度", "口径"], style_rows),
        ]
    )

    strongest = (structure.get("industry_rankings") or {}).get("strongest") or []
    weakest = (structure.get("industry_rankings") or {}).get("weakest") or []

    def industry_rows(items: list[dict[str, Any]]) -> list[list[str]]:
        return [
            [
                str(item.get("industry") or item.get("name") or "--"),
                str(item.get("symbol") or "--"),
                _pct(item.get("return_1d")),
                _pct(item.get("return_5d")),
                _pct(item.get("return_20d")),
                _pct(item.get("amount_share_change_20d")),
                _pct(item.get("pct_above_ma20"), signed=False),
            ]
            for item in items[:10]
        ]

    lines.extend(
        [
            "",
            "## 4. 行业强弱榜",
            "",
            f"- 行业排序口径：{(structure.get('industry_rankings') or {}).get('method_note') or '--'}",
            "",
            "### 最强行业",
            "",
            _table(["行业", "代码", "1日", "5日", "20日", "成交占比变化", "MA20上方"], industry_rows(strongest)),
            "",
            "### 最弱行业",
            "",
            _table(["行业", "代码", "1日", "5日", "20日", "成交占比变化", "MA20上方"], industry_rows(weakest)),
        ]
    )

    sector_rows: list[list[str]] = []
    for sector_name, item in (structure.get("sector_details") or {}).items():
        sector_rows.append(
            [
                str(sector_name),
                ", ".join(str(x) for x in (item.get("symbols") or [])) or str(item.get("stock_count") or "--"),
                _pct(item.get("return_1d")),
                _pct(item.get("return_5d")),
                _pct(item.get("return_20d")),
                _pct(item.get("pct_above_ma20"), signed=False),
                str(item.get("data_source") or item.get("basket_type") or "--"),
            ]
        )
    rs_names = {
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
    rs_rows = [
        [rs_names.get(key, key), _pct(value)]
        for key, value in (structure.get("relative_strength") or {}).items()
    ]
    lines.extend(
        [
            "",
            "## 5. 金融权重与相对强弱",
            "",
            _table(["板块", "样本", "1日", "5日", "20日", "MA20上方", "数据源"], sector_rows),
            "",
            _table(["相对强弱", "当前值"], rs_rows),
        ]
    )

    lines.extend(
        [
            "",
            "## 6. 市场广度与风险扩散",
            "",
            f"- 上涨比例：{_pct(latest.get('advance_ratio'), signed=False)}；下跌比例：{_pct(latest.get('decline_ratio'), signed=False)}",
            f"- MA20/MA50/MA200 上方比例：{_pct(latest.get('pct_above_ma20'), signed=False)} / {_pct(latest.get('pct_above_ma50'), signed=False)} / {_pct(latest.get('pct_above_ma200'), signed=False)}",
            f"- 20日新高/新低比例：{_pct(latest.get('new_high_20_ratio'), signed=False)} / {_pct(latest.get('new_low_20_ratio'), signed=False)}",
            f"- 跌超3%/跌超5%比例：{_pct(latest.get('decline_gt_3_ratio'), signed=False)} / {_pct(latest.get('decline_gt_5_ratio'), signed=False)}",
            f"- 近似涨停/跌停比例：{_pct(latest.get('approximate_limit_up_ratio'), signed=False)} / {_pct(latest.get('approximate_limit_down_ratio'), signed=False)}",
            f"- 标准化A/D：{_num(latest.get('normalized_ad'), 3)}；20日A/D：{_num(latest.get('normalized_ad_20d'), 3)}",
            f"- NH-NL方向：{_state_name(risk.get('nhnl_direction'))}；新低方向：{_state_name(risk.get('new_low_direction'))}；跌超5%方向：{_state_name(risk.get('large_decline_direction'))}",
            f"- 成交额/20日均值：{_num((structure.get('liquidity') or {}).get('amount_ratio_20'), 2)}倍；流动性状态：{_state_name((structure.get('liquidity') or {}).get('state'))}",
        ]
    )

    is_v2 = _append_v2_fact_sections(lines, structure)
    flags = structure.get("data_quality_flags") or []
    if flags:
        lines.extend(
            [
                "",
                "## 13. 数据限制与解释边界" if is_v2 else "## 7. 数据限制与解释边界",
                "",
                "- 当前报告只描述已经发生的市场结构，不等同于未来收益概率。",
                "- 模型总结不得给出确定性买卖建议。",
                "- 数据质量标记：" + "、".join(str(flag) for flag in flags),
            ]
        )
    return "\n".join(part for part in lines if part is not None)


def build_llm_prompt(facts_markdown: str) -> str:
    return f"""你是一名A股市场结构复盘助手。

请只基于下面提供的事实包写一篇中文分析总结，不要编造事实包之外的数据，不要给确定性预测，不要输出具体买卖指令。

写作要求：
1. 开头先给“一句话总判断”。
2. 正文分成：市场总览、指数强弱、风格结构、行业线索、风险扩散、后续观察点。
3. 每个主要判断必须引用至少一个事实包里的数据证据。
4. 如果出现“指数强但广度弱”“某风格强但风险扩散”等冲突，要明确指出。
5. 语言要像交易复盘，克制、具体、可检查；不要夸张，不要说必涨必跌。
6. 结尾给出3-5个下一交易日/下一阶段要观察的指标。
7. 如果事实包包含v2状态，优先使用v2确定性状态、分层广度、集中度、分布、流动性、轮动、风险修复和新鲜度证据；不要自行重算。
8. “仅供研究的候选相位”必须明确标注为探索性线索，不得写成正式判断、收益预测或买卖信号。

事实包如下：

{facts_markdown}
"""


def call_deepseek_summary(
    prompt: str,
    config: dict[str, Any] | None = None,
    *,
    api_key: str | None = None,
) -> str:
    llm_cfg = ((config or {}).get("llm_summary") or {})
    provider_cfg = llm_cfg.get("deepseek") or {}
    env_name = str(provider_cfg.get("api_key_env") or "DEEPSEEK_API_KEY")
    token = api_key or _api_key_from_env_or_dotenv(env_name, config)
    if not token:
        raise RuntimeError(f"缺少 DeepSeek API Key，请设置环境变量 {env_name}")
    base_url = str(provider_cfg.get("base_url") or DEFAULT_DEEPSEEK_BASE_URL).rstrip("/")
    model = str(provider_cfg.get("model") or DEFAULT_DEEPSEEK_MODEL)
    temperature = float(provider_cfg.get("temperature", 0.25))
    max_tokens = int(provider_cfg.get("max_tokens", 3000))
    timeout = float(provider_cfg.get("timeout_seconds", 90))
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是严谨的A股市场结构复盘助手，只基于用户给定事实写总结。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek API 请求失败: HTTP {exc.code}: {body[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"DeepSeek API 网络错误: {exc}") from exc

    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"DeepSeek API 未返回 choices: {data}")
    content = ((choices[0].get("message") or {}).get("content") or "").strip()
    if not content:
        raise RuntimeError("DeepSeek API 返回内容为空")
    return content


def _markdown_html(markdown: str, title: str) -> str:
    def inline(text: str) -> str:
        escaped = escape(text)
        return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)

    def table(lines: list[str]) -> str:
        headers = [cell.strip() for cell in lines[0].strip().strip("|").split("|")]
        body_lines = lines[2:]
        head_html = "".join(f"<th>{inline(cell)}</th>" for cell in headers)
        body_html = []
        for row in body_lines:
            cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
            body_html.append("<tr>" + "".join(f"<td>{inline(cell)}</td>" for cell in cells) + "</tr>")
        return f"<div class='table-wrap'><table><thead><tr>{head_html}</tr></thead><tbody>{''.join(body_html)}</tbody></table></div>"

    blocks: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    lines = markdown.splitlines()
    i = 0

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            blocks.append(f"<p>{inline(' '.join(part.strip() for part in paragraph))}</p>")
            paragraph = []

    def flush_list() -> None:
        nonlocal list_items
        if list_items:
            blocks.append("<ul>" + "".join(f"<li>{inline(item)}</li>" for item in list_items) + "</ul>")
            list_items = []

    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        if not line:
            flush_paragraph()
            flush_list()
            i += 1
            continue
        if line.startswith("|") and i + 1 < len(lines) and set(lines[i + 1].strip().replace("|", "").replace(" ", "")) <= {"-", ":"}:
            flush_paragraph()
            flush_list()
            table_lines = [line, lines[i + 1].strip()]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            blocks.append(table(table_lines))
            continue
        if line in {"---", "***", "___"}:
            flush_paragraph()
            flush_list()
            blocks.append("<hr>")
            i += 1
            continue
        if line.startswith("### "):
            flush_paragraph()
            flush_list()
            blocks.append(f"<h3>{inline(line[4:])}</h3>")
            i += 1
            continue
        if line.startswith("## "):
            flush_paragraph()
            flush_list()
            blocks.append(f"<h2>{inline(line[3:])}</h2>")
            i += 1
            continue
        if line.startswith("# "):
            flush_paragraph()
            flush_list()
            blocks.append(f"<h1>{inline(line[2:])}</h1>")
            i += 1
            continue
        if line.startswith(">"):
            flush_paragraph()
            flush_list()
            blocks.append(f"<blockquote>{inline(line.lstrip('> ').strip())}</blockquote>")
            i += 1
            continue
        list_match = re.match(r"^(?:[-*]|\d+\.)\s+(.*)$", line)
        if list_match:
            flush_paragraph()
            list_items.append(list_match.group(1))
            i += 1
            continue
        flush_list()
        paragraph.append(line)
        i += 1
    flush_paragraph()
    flush_list()
    article = "\n".join(blocks)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escape(title)}</title>
  <style>
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:#f5f6f8; color:#172033; font-family:"Microsoft YaHei","Noto Sans SC","PingFang SC",sans-serif; }}
    main {{ width:min(980px, calc(100vw - 40px)); margin:0 auto; padding:32px 0 56px; }}
    .topbar {{ display:flex; justify-content:space-between; align-items:flex-end; gap:16px; margin-bottom:16px; border-bottom:1px solid #d9e0ea; padding-bottom:16px; }}
    .topbar h1 {{ margin:0; font-size:30px; line-height:1.2; }}
    .sub {{ color:#69748a; font-size:13px; margin-top:6px; }}
    .badge {{ padding:8px 12px; background:#172033; color:#fff; font-weight:900; white-space:nowrap; }}
    article {{ background:#fff; border:1px solid #d9e0ea; padding:28px 34px; line-height:1.82; box-shadow:0 1px 2px rgba(23,32,51,.04); }}
    article h1 {{ margin:0 0 18px; font-size:28px; }}
    article h2 {{ margin:28px 0 12px; padding-top:18px; border-top:1px solid #edf0f5; font-size:22px; }}
    article h3 {{ margin:22px 0 10px; font-size:17px; color:#465268; }}
    p {{ margin:10px 0; }}
    strong {{ color:#172033; font-weight:900; }}
    ul {{ margin:10px 0 14px; padding-left:22px; }}
    li {{ margin:7px 0; }}
    blockquote {{ margin:14px 0; padding:12px 14px; background:#fbfcfe; border-left:4px solid #8796b2; color:#465268; }}
    hr {{ border:0; border-top:1px solid #edf0f5; margin:20px 0; }}
    .table-wrap {{ overflow-x:auto; margin:12px 0 18px; border:1px solid #edf0f5; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th, td {{ padding:9px 11px; border-bottom:1px solid #edf0f5; text-align:left; white-space:nowrap; }}
    th {{ background:#fbfcfe; color:#69748a; font-weight:900; }}
    tr:last-child td {{ border-bottom:0; }}
    @media (max-width:620px) {{ main {{ width:min(100vw - 24px, 980px); }} .topbar {{ align-items:flex-start; flex-direction:column; }} article {{ padding:22px 18px; }} }}
  </style>
</head>
<body>
  <main>
    <header class="topbar">
      <div><h1>{escape(title)}</h1><div class="sub">由 DeepSeek 基于市场结构事实包生成，仅供复盘参考，不构成投资建议。</div></div>
      <div class="badge">复盘总结</div>
    </header>
    <article>{article}</article>
  </main>
</body>
</html>
"""


def write_llm_summary_artifacts(
    config: dict[str, Any],
    symbol: str,
    horizon: int,
    name: str | None = None,
    *,
    call_api: bool = True,
    skip_if_no_key: bool = False,
) -> tuple[LLMSummaryPaths, str | None]:
    structure = load_market_structure_json(config, symbol)
    paths = llm_summary_paths(config, symbol, horizon)
    paths.facts.parent.mkdir(parents=True, exist_ok=True)
    facts = build_llm_fact_markdown(structure, symbol=symbol, name=name)
    prompt = build_llm_prompt(facts)
    paths.facts.write_text(facts, encoding="utf-8")
    paths.prompt.write_text(prompt, encoding="utf-8")

    summary: str | None = None
    if call_api:
        env_name = str((((config.get("llm_summary") or {}).get("deepseek") or {}).get("api_key_env")) or "DEEPSEEK_API_KEY")
        if skip_if_no_key and not _api_key_from_env_or_dotenv(env_name, config):
            return paths, None
        summary = call_deepseek_summary(prompt, config)
        paths.summary.write_text(summary, encoding="utf-8")
        data_date = str(structure.get("date") or "数据日期未知")
        paths.html.write_text(
            _markdown_html(summary, f"{symbol.upper()} {data_date} 市场结构大模型总结"),
            encoding="utf-8",
        )
    return paths, summary
