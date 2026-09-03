"""Generate a facts-only daily A-share review markdown."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any


DEFAULT_INDEX_SYMBOL = "000001.SH"
DEFAULT_INDEX_NAME = "上证指数"


@dataclass(frozen=True)
class DailyReviewResult:
    output_path: Path
    structure_path: Path
    trade_date: str
    missing_items: list[str]


def _normalise_date(value: str | None, fallback_year: int | None = None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) == 4 and text.isdigit():
        year = fallback_year or datetime.now().year
        return f"{year}-{text[:2]}-{text[2:]}"
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return text


def _fmt(value: Any, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number != number:
        return ""
    return f"{number:,.{digits}f}{suffix}"


def _fmt_pct(value: Any, digits: int = 2, signed: bool = True) -> str:
    if value is None:
        return ""
    try:
        number = float(value) * 100.0
    except (TypeError, ValueError):
        return str(value)
    if number != number:
        return ""
    sign = "+" if signed and number > 0 else ""
    return f"{sign}{number:.{digits}f}%"


def _fmt_pp(value: Any, digits: int = 2, signed: bool = True) -> str:
    if value is None:
        return ""
    try:
        number = float(value) * 100.0
    except (TypeError, ValueError):
        return str(value)
    if number != number:
        return ""
    sign = "+" if signed and number > 0 else ""
    return f"{sign}{number:.{digits}f}pct"


def _fmt_ratio(value: Any, digits: int = 2) -> str:
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number != number:
        return ""
    return f"{number:.{digits}f}倍"


def _fmt_amount_yi_from_thousand(value: Any, digits: int = 0) -> str:
    """Tushare stock daily amount uses thousand RMB; render as Chinese yi RMB."""
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number != number:
        return ""
    return f"{number / 100000:,.{digits}f}亿"


def _fmt_count(value: Any) -> str:
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number != number:
        return ""
    return f"{int(round(number)):,}"


def _trend_cn(value: Any) -> str:
    mapping = {
        "uptrend": "上升",
        "downtrend": "下降",
        "sideways": "震荡",
        "unknown": "",
        None: "",
    }
    return mapping.get(value, str(value))


def _state_cn(value: Any) -> str:
    mapping = {
        "broad_rally": "普涨",
        "broad_decline": "普跌",
        "mixed": "分化",
        "normal": "正常",
        "broad_strength": "广度强",
        "strong": "强",
        "weak": "弱",
        "unknown": "",
        None: "",
    }
    return mapping.get(value, str(value))


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body = []
    for row in rows:
        cells = [str(cell) if cell is not None else "" for cell in row]
        body.append("| " + " | ".join(cell.replace("\n", "<br>") for cell in cells) + " |")
    return "\n".join([head, sep, *body])


def _history_row_by_date(history: list[dict[str, Any]], trade_date: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    current_index = None
    for idx, row in enumerate(history):
        if str(row.get("trade_date")) == trade_date:
            current_index = idx
    if current_index is None:
        return None, None
    current = history[current_index]
    previous = history[current_index - 1] if current_index > 0 else None
    return current, previous


def _diff_value(current: Any, previous: Any, pct: bool = False) -> str:
    if current is None or previous is None:
        return ""
    try:
        diff = float(current) - float(previous)
    except (TypeError, ValueError):
        return ""
    if pct:
        return _fmt_pp(diff)
    sign = "+" if diff > 0 else ""
    return f"{sign}{diff:,.0f}"


def _estimate_count(ratio: Any, total: Any) -> int | None:
    try:
        return int(round(float(ratio) * float(total)))
    except (TypeError, ValueError):
        return None


def _find_structure_json(config: dict[str, Any], symbol: str, trade_date: str | None) -> Path:
    stats_dir = Path(config.get("output", {}).get("statistics_dir", "output/statistics"))
    reports_dir = Path(config.get("output", {}).get("reports_dir", "output/reports"))
    symbol = symbol.upper()
    latest = stats_dir / "index_forecast" / f"market_structure_{symbol}.json"
    if latest.exists():
        if trade_date is None:
            return latest
        try:
            latest_date = json.loads(latest.read_text(encoding="utf-8")).get("date")
        except Exception:
            latest_date = None
        if latest_date == trade_date:
            return latest

    if trade_date:
        archive_dir = reports_dir / "index_forecast" / "archive" / "market_structure_v2" / trade_date
        if archive_dir.exists():
            matches = sorted(archive_dir.glob(f"{symbol}_*_market_structure.json"))
            if matches:
                return matches[-1]

    if latest.exists():
        return latest
    raise FileNotFoundError(f"没有找到市场结构 JSON: {latest}")


def _load_structure(config: dict[str, Any], symbol: str, date: str | None) -> tuple[dict[str, Any], Path]:
    path = _find_structure_json(config, symbol, date)
    data = json.loads(path.read_text(encoding="utf-8"))
    actual_date = _normalise_date(data.get("date"))
    if date and actual_date != date:
        raise ValueError(f"请求日期 {date} 与结构数据日期 {actual_date} 不一致: {path}")
    return data, path


def _render_index_section(structure: dict[str, Any], missing: list[str]) -> str:
    indices = structure.get("indices") or {}
    all_a = indices.get("同花顺平均股价指数") or indices.get("全A") or {}
    all_a_20 = all_a.get("return_20d")
    order = ["上证指数", "沪深300", "中证500", "中证1000", "中证2000", "创业板指", "科创50", "深证成指"]
    rows = []
    for name in order:
        item = indices.get(name) or {}
        rel = ""
        if all_a_20 is not None and item.get("return_20d") is not None:
            rel = _fmt_pp(float(item.get("return_20d")) - float(all_a_20))
        rows.append([
            name,
            item.get("symbol", ""),
            _fmt_pct(item.get("return_1d")),
            _fmt_pct(item.get("return_5d")),
            _fmt_pct(item.get("return_10d")),
            _fmt_pct(item.get("return_20d")),
            _fmt_ratio(item.get("amount_ratio_20d")),
            _trend_cn(item.get("daily_trend")),
            _trend_cn(item.get("weekly_trend")),
            item.get("support_pressure", ""),
            rel,
        ])
    rel = structure.get("relative_strength") or {}
    if not rel:
        missing.append("指数组间关系：缺少 relative_strength 字段")
    relation_rows = [
        ["沪深300相对同花顺平均股价20日", _fmt_pp(rel.get("hs300_vs_all_a_20d"))],
        ["沪深300相对同花顺平均股价5日", _fmt_pp(rel.get("hs300_vs_all_a_5d"))],
        ["小盘相对沪深300 20日", _fmt_pp(rel.get("small_vs_hs300_20d"))],
        ["权重价值相对科技成长5日", _fmt_pp(rel.get("value_vs_growth_5d"))],
        ["权重价值相对科技成长20日", _fmt_pp(rel.get("value_vs_growth_20d"))],
        ["消费相对同花顺平均股价20日", _fmt_pp(rel.get("consumer_vs_all_a_20d"))],
    ]
    return f"""# 二、主要指数与风格结构

## 1. 指数表现

{_table(["指数", "代码", "1日", "5日", "10日", "20日", "成交/20日均", "日线", "周线", "支撑/压力", "相对平均股价20日"], rows)}

## 2. 指数组间关系

{_table(["关系", "数值"], relation_rows)}

### 今日属于哪种结构

- [ ] 大小盘同步上涨
- [ ] 大盘强、小盘弱
- [ ] 小盘强、大盘弱
- [ ] 成长强、价值弱
- [ ] 价值强、成长弱
- [ ] 指数上涨但个股偏弱
- [ ] 指数下跌但个股抗跌

### 指数结构结论

> 
"""


def _render_breadth_section(structure: dict[str, Any], missing: list[str]) -> str:
    breadth = structure.get("breadth") or {}
    history = breadth.get("history") or []
    trade_date = str(structure.get("date") or "")
    current, previous = _history_row_by_date(history, trade_date)
    latest = breadth.get("latest") or current or {}
    if not latest:
        missing.append("市场广度：缺少 breadth.latest")
    layered_all_a = ((structure.get("layered_breadth") or {}).get("全A") or {}).get("latest") or {}
    valid = latest.get("valid_stock_count")
    rows = [
        ["上涨家数", _fmt_count(latest.get("advance_count")), _fmt_count(previous.get("advance_count") if previous else None), _diff_value(latest.get("advance_count"), previous.get("advance_count") if previous else None)],
        ["下跌家数", _fmt_count(latest.get("decline_count")), _fmt_count(previous.get("decline_count") if previous else None), _diff_value(latest.get("decline_count"), previous.get("decline_count") if previous else None)],
        ["平盘家数", _fmt_count(latest.get("flat_count")), _fmt_count(previous.get("flat_count") if previous else None), _diff_value(latest.get("flat_count"), previous.get("flat_count") if previous else None)],
        ["个股涨跌幅中位数", _fmt_pct(latest.get("median_stock_return_1d")), _fmt_pct(previous.get("median_stock_return_1d") if previous else None), _diff_value(latest.get("median_stock_return_1d"), previous.get("median_stock_return_1d") if previous else None, pct=True)],
        ["涨停家数（近似）", _fmt_count(_estimate_count(latest.get("approximate_limit_up_ratio"), valid)), _fmt_count(_estimate_count(previous.get("approximate_limit_up_ratio"), previous.get("valid_stock_count")) if previous else None), ""],
        ["跌停家数（近似）", _fmt_count(_estimate_count(latest.get("approximate_limit_down_ratio"), valid)), _fmt_count(_estimate_count(previous.get("approximate_limit_down_ratio"), previous.get("valid_stock_count")) if previous else None), ""],
        ["涨幅超过5%家数", _fmt_count(_estimate_count(latest.get("advance_gt_5_ratio"), valid)), _fmt_count(_estimate_count(previous.get("advance_gt_5_ratio"), previous.get("valid_stock_count")) if previous else None), ""],
        ["跌幅超过5%家数", _fmt_count(_estimate_count(latest.get("decline_gt_5_ratio"), valid)), _fmt_count(_estimate_count(previous.get("decline_gt_5_ratio"), previous.get("valid_stock_count")) if previous else None), ""],
        ["20日新高家数", _fmt_count(latest.get("new_high_20_count")), _fmt_count(previous.get("new_high_20_count") if previous else None), _diff_value(latest.get("new_high_20_count"), previous.get("new_high_20_count") if previous else None)],
        ["20日新低家数", _fmt_count(latest.get("new_low_20_count")), _fmt_count(previous.get("new_low_20_count") if previous else None), _diff_value(latest.get("new_low_20_count"), previous.get("new_low_20_count") if previous else None)],
        ["站上MA20比例", _fmt_pct(latest.get("pct_above_ma20"), signed=False), _fmt_pct(previous.get("pct_above_ma20") if previous else None, signed=False), _diff_value(latest.get("pct_above_ma20"), previous.get("pct_above_ma20") if previous else None, pct=True)],
        ["站上MA60比例", _fmt_pct(layered_all_a.get("pct_above_ma60"), signed=False), "", ""],
    ]
    return f"""# 三、市场广度与真实赚钱效应

## 1. 基础广度数据

{_table(["指标", "今日", "昨日", "变化"], rows)}

## 2. 广度判断

- [ ] 广度改善
- [ ] 广度恶化
- [ ] 指数强于广度
- [ ] 广度强于指数
- [ ] 普涨
- [ ] 普跌
- [ ] 局部赚钱效应
- [ ] 情绪修复
- [ ] 亏钱效应扩散

### 今日真实赚钱效应

> 

### 今日主要亏钱区域

> 
"""


def _stock_list(rows: list[dict[str, Any]], limit: int = 20) -> str:
    if not rows:
        return ""
    table_rows = []
    for row in rows[:limit]:
        table_rows.append([
            f"{row.get('name', '')}<br>{row.get('symbol', '')}",
            row.get("industry", ""),
            _fmt_pct(row.get("return_1d")),
            _fmt_amount_yi_from_thousand(row.get("amount"), digits=1),
            _fmt_ratio(row.get("amount_ratio_20d")),
            _fmt_pct(row.get("index_contribution")),
            _fmt_pct(row.get("contribution_share"), signed=False),
        ])
    return _table(["成分", "行业", "1日收益", "成交额", "成交/20日", "指数贡献", "贡献占比"], table_rows)


def _render_lift_section(structure: dict[str, Any], missing: list[str]) -> str:
    lift = structure.get("index_lift_structure") or {}
    if not lift:
        missing.append("指数拉动集中度：缺少 index_lift_structure")
    top_positive_rows = lift.get("top_positive_contributors") or []
    top_negative_rows = lift.get("top_negative_contributors") or []

    def share_sum(rows: list[dict[str, Any]]) -> float | None:
        values: list[float] = []
        for row in rows[:20]:
            value = row.get("contribution_share")
            if value is None:
                continue
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                continue
        return sum(values) if values else None

    summary = [
        ["观察指数", f"{lift.get('index_name', DEFAULT_INDEX_NAME)} {lift.get('symbol', DEFAULT_INDEX_SYMBOL)}"],
        ["指数涨跌幅", _fmt_pct(lift.get("index_return"))],
        ["等权表现", _fmt_pct(lift.get("equal_weight_return"))],
        ["成交额加权表现", _fmt_pct(lift.get("amount_weighted_return"))],
        ["上涨前20贡献占比", _fmt_pct(share_sum(top_positive_rows), signed=False)],
        ["下跌前20拖累占比", _fmt_pct(share_sum(top_negative_rows), signed=False)],
        ["成交额前20占比", _fmt_pct((lift.get("turnover_confirmation") or {}).get("top20_turnover_amount_share"), signed=False)],
    ]
    return f"""# 四、指数拉动集中度

## 1. 指数上涨由谁贡献

{_table(["指标", "数值"], summary)}

### 上涨贡献前20

{_stock_list(top_positive_rows, limit=20)}

### 下跌拖累前20

{_stock_list(top_negative_rows, limit=20)}

### 成交额前20

{_stock_list(lift.get("top_turnover_stocks") or [], limit=20)}

## 2. 集中度判断

- [ ] 少数权重股拉动
- [ ] 多数成分股共同上涨
- [ ] 指数上涨但中位数为负
- [ ] 指数上涨但等权指数弱
- [ ] 指数下跌但少数权重拖累
- [ ] 权重与个股方向一致

### 结论

> 
"""


def _render_liquidity_section(structure: dict[str, Any], missing: list[str]) -> str:
    liq = structure.get("liquidity_structure") or {}
    latest = liq.get("latest") or {}
    if not latest:
        missing.append("成交额结构：缺少 liquidity_structure.latest")
    cap = liq.get("cap_turnover_shares") or {}
    rows = [
        ["两市总成交额", _fmt_amount_yi_from_thousand(latest.get("total_amount"), digits=0)],
        ["相对5日均额", _fmt_ratio(latest.get("amount_ratio_5d"))],
        ["相对20日均额", _fmt_ratio(latest.get("amount_ratio_20d"))],
        ["上涨股票成交额占比", _fmt_pct(latest.get("advance_amount_ratio"), signed=False)],
        ["下跌股票成交额占比", _fmt_pct(latest.get("decline_amount_ratio"), signed=False)],
        ["涨跌成交比", _fmt_ratio(latest.get("advance_decline_amount_ratio"))],
        ["涨幅前10%成交集中度", f"{_fmt_pct(latest.get('top_10pct_gainer_amount_share'), signed=False)} / 样本 {_fmt_count(latest.get('top_10pct_gainer_count'))}只"],
        ["跌幅前10%成交集中度", f"{_fmt_pct(latest.get('top_10pct_loser_amount_share'), signed=False)} / 样本 {_fmt_count(latest.get('top_10pct_loser_count'))}只"],
        ["沪深300 / 中证1000 / 中证2000成交占比", f"{_fmt_pct(cap.get('沪深300'), signed=False)} / {_fmt_pct(cap.get('中证1000'), signed=False)} / {_fmt_pct(cap.get('中证2000'), signed=False)}"],
    ]
    industry_rows = []
    sorted_industries = sorted(
        liq.get("industry_turnover_shares") or [],
        key=lambda row: float(row.get("amount_share_change_20d") or 0.0),
        reverse=True,
    )
    for row in sorted_industries[:15]:
        industry_rows.append([
            row.get("industry", ""),
            _fmt_pct(row.get("amount_share"), signed=False),
            _fmt_pp(row.get("amount_share_change_5d")),
            _fmt_pp(row.get("amount_share_change_20d")),
            _fmt_ratio(row.get("amount_ratio_20d")),
            _fmt_pct(row.get("return_1d")),
        ])
    migration_rows = []
    for row in (liq.get("turnover_migration") or [])[:12]:
        migration_rows.append([
            row.get("bucket", ""),
            row.get("name", ""),
            _fmt_pct(row.get("amount_share"), signed=False),
            _fmt_pp(row.get("amount_share_change_5d")),
            _fmt_pp(row.get("amount_share_change_20d")),
        ])
    return f"""# 五、成交额与资金结构

## 1. 总体成交额

{_table(["指标", "数值"], rows)}

## 2. 成交额分布

### 行业成交额增量排名

{_table(["行业", "当前成交占比", "5日变化百分点", "20日变化百分点", "成交/20日", "1日收益"], industry_rows)}

### 权重板块与题材板块成交额迁移

{_table(["类型", "板块", "当前成交占比", "5日变化百分点", "20日变化百分点"], migration_rows)}

## 3. 努力与结果

- 放量是否带来指数上涨：
- 放量是否带来个股赚钱效应：
- 成交额是否集中在主线：
- 成交额是否集中在下跌板块：

### 成交额结构结论

> 
"""


def _render_board_section(structure: dict[str, Any], missing: list[str]) -> str:
    ind = structure.get("industry_structure") or {}
    if not ind:
        missing.append("板块复盘：缺少 industry_structure")

    def rows(items: list[dict[str, Any]]) -> list[list[Any]]:
        out = []
        for row in items[:10]:
            out.append([
                row.get("industry", ""),
                _fmt_pct(row.get("return_5d")),
                _fmt_pct(row.get("return_10d")),
                _fmt_pct(row.get("return_20d")),
                f"{_fmt_pct(row.get('advance_ratio'), signed=False)} / MA20 {_fmt_pct(row.get('pct_above_ma20'), signed=False)}",
                row.get("leadership_quality", ""),
                "",
            ])
        return out

    return f"""# 六、板块与主线复盘

## 1. 强势板块

{_table(["板块", "5日", "10日", "20日", "板块广度", "领涨质量", "核心股"], rows(ind.get("strongest") or []))}

## 2. 弱势板块

{_table(["板块", "5日", "10日", "20日", "板块广度", "领涨质量", "风险原因"], rows(ind.get("weakest") or []))}

## 3. 主线角色结构

### 当前主线

> 

### 龙头

- 股票：
- 今日表现：
- 是否打开空间：
- 是否出现放量滞涨 / 长上影 / 破位：

### 容量中军

- 股票：
- 今日表现：
- 是否提供板块成交容量：
- 是否保持趋势：

### 趋势核心

- 股票：
- 今日表现：

### 补涨股

- 股票：
- 是否形成有效扩散：

### 掉队与负反馈

- 股票：
- 负反馈是否扩大：

## 4. 主线质量判断

- [ ] 龙头、中军、补涨同步
- [ ] 只有龙头上涨
- [ ] 龙头强，但中军走弱
- [ ] 板块广度扩大
- [ ] 成交额持续流入
- [ ] 高位分歧后重新走强
- [ ] 跟风股亏钱效应扩大
- [ ] 主线进入高潮
- [ ] 主线进入退潮

### 主线结论

> 
"""


def _render_risk_section() -> str:
    return """# 七、风险结构

## 1. 今日风险信号

- [ ] 跌停数量增加
- [ ] 跌幅超过5%的股票增加
- [ ] 创新低数量增加
- [ ] 昨日强势股出现大面积负反馈
- [ ] 高位股放量长阴
- [ ] 龙头或中军补跌
- [ ] 指数跌破关键支撑
- [ ] 指数上涨但广度恶化
- [ ] 指数上涨但下跌成交额增加
- [ ] 小盘股连续弱于权重股
- [ ] 主线板块退潮扩散
- [ ] 市场流动性下降

## 2. 风险处于哪个层级

- [ ] 局部风险
- [ ] 板块性风险
- [ ] 风格性风险
- [ ] 全市场风险扩散
- [ ] 恐慌释放阶段
- [ ] 风险开始收敛

### 当前最值得防范的风险

> 

### 哪些证据出现后，说明风险缓解

> 
"""


def _render_verification_and_trading_sections() -> str:
    return """# 八、昨日判断验证

## 1. 昨日核心判断

> 

## 2. 今日实际结果

> 

## 3. 判断结果

- [ ] 正确
- [ ] 基本正确
- [ ] 方向正确但节奏错误
- [ ] 方向错误
- [ ] 无法验证
- [ ] 事后解释过多，昨日判断不够明确

## 4. 错误归因

- [ ] 数据看错
- [ ] 忽略市场广度
- [ ] 忽略成交额结构
- [ ] 忽略权重股影响
- [ ] 错判板块生命周期
- [ ] 把缩量止跌误判为转强
- [ ] 把放量上涨误判为有效突破
- [ ] 判断方向正确，但时间过早
- [ ] 受到持仓立场影响
- [ ] 把希望当成判断
- [ ] 结论过于笼统，无法检验

### 今日修正后的认识

> 

# 九、个人持仓与交易复盘

## 1. 当前持仓

| 股票 | 所属板块 | 持仓逻辑 | 当前状态 | 失效条件 | 明日计划 |
|---|---|---|---|---|---|
|  |  |  |  |  |  |
|  |  |  |  |  |  |

## 2. 今日交易记录

### 交易一

- 股票：
- 买入/卖出：
- 成交价格：
- 仓位：
- 所属市场环境：
- 所属板块阶段：
- 交易逻辑：
- 明确触发条件：
- 原计划失效条件：
- 原计划止损：
- 原计划止盈或退出方式：
- 实际执行：
- 是否临时改变计划：
- 改变计划的原因：
- 当时情绪：
- 最终结果：

### 交易质量

- [ ] 系统内盈利
- [ ] 系统内亏损
- [ ] 系统外盈利
- [ ] 系统外亏损
- [ ] 正确放弃
- [ ] 错过计划内机会
- [ ] 追涨
- [ ] 提前抄底
- [ ] 止损拖延
- [ ] 过早止盈
- [ ] 仓位过大
- [ ] 报复性交易

### 对这笔交易的评价

> 不依据盈亏评价，而依据逻辑、计划、仓位和执行评价。

> 

## 3. 今日执行评分

- 计划执行率：
- 是否出现系统外交易：
- 是否遵守仓位纪律：
- 是否遵守止损：
- 是否因情绪改变计划：
- 今日最好的执行：
- 今日最差的执行：
"""


def _render_plan_section(structure: dict[str, Any]) -> str:
    indices = structure.get("indices") or {}
    names = ["上证指数", "沪深300", "中证1000", "中证2000", "创业板指", "科创50"]
    lines = []
    for name in names:
        item = indices.get(name) or {}
        low = _fmt(item.get("low_20d"), digits=2)
        high = _fmt(item.get("high_20d"), digits=2)
        support = item.get("support_pressure", "")
        lines.append(f"- {name}：20日低 {low}；20日高 {high}；{support}")
    return f"""# 十、明日情景计划

## 情景A：市场继续走强

### 触发条件

- 
- 
- 

### 市场含义

> 

### 我的应对

- 
- 
- 

---

## 情景B：指数上涨，但内部继续分化

### 触发条件

- 
- 
- 

### 市场含义

> 

### 我的应对

- 
- 
- 

---

## 情景C：市场转弱或风险扩散

### 触发条件

- 
- 
- 

### 市场含义

> 

### 我的应对

- 
- 
- 

---

## 明日重点观察

### 指数关键位置

{chr(10).join(lines)}

### 重点板块

- 
- 
- 

### 重点个股

| 股票 | 观察原因 | 触发条件 | 失效条件 | 是否计划交易 |
|---|---|---|---|---|
|  |  |  |  |  |
|  |  |  |  |  |

### 明日明确禁止事项

- [ ] 不追板块高潮后的跟风股
- [ ] 不因指数拉升忽略市场广度
- [ ] 不在失效条件出现后继续幻想
- [ ] 不做计划外交易
- [ ] 不因错过机会临时追高
- [ ] 不因上一笔亏损扩大下一笔仓位
"""


def _render_research_sections() -> str:
    return """# 十一、今日专项研究

## 今日只研究一个问题

> 

例如：

- 指数上涨为什么多数股票下跌？
- 今日板块是启动还是退潮反抽？
- 这次突破为什么失败？
- 龙头上涨为什么没有带动板块？
- 高位放量是换手还是供应增加？
- 我为什么总在板块高潮阶段买入？

## 当时看到的事实

> 

## 当时的理解

> 

## 后续验证结果

> 

## 最有辨识度的细节

> 

## 下次遇到同类情况重点观察

> 

# 十二、今日经验沉淀

## 今天确认的一条有效经验

> 

## 今天发现的一项重复错误

> 

## 明天只改进一个行为

> 

## 最终复盘结论

> 今日市场：

> 当前主要机会：

> 当前主要风险：

> 明日核心原则：
"""


def _support_relation_text(item: dict[str, Any]) -> str:
    relation = item.get("support_pressure")
    return str(relation) if relation else ""


def _structure_change_text(item: dict[str, Any]) -> str:
    relation = str(item.get("support_pressure") or "")
    if "支撑" in relation:
        return "接近支撑"
    if "压力" in relation:
        return "接近压力"
    return "无明显变化"


def _amount_level_text(ratio_5d: Any, ratio_20d: Any) -> str:
    ratios: list[float] = []
    for value in (ratio_5d, ratio_20d):
        try:
            ratios.append(float(value))
        except (TypeError, ValueError):
            pass
    if not ratios:
        return "放量 / 缩量 / 基本持平"
    avg_ratio = sum(ratios) / len(ratios)
    if avg_ratio >= 1.05:
        return "放量"
    if avg_ratio <= 0.95:
        return "缩量"
    return "基本持平"


def _signed_amount_yi_diff_from_thousand(diff: float | None) -> str:
    if diff is None:
        return ""
    sign = "+" if diff > 0 else ""
    return f"{sign}{diff / 100000:,.0f}亿"


def _breadth_change_text(current_ratio: Any, previous_ratio: Any) -> str:
    if current_ratio is None or previous_ratio is None:
        return "改善 / 恶化 / 基本稳定"
    try:
        diff = float(current_ratio) - float(previous_ratio)
    except (TypeError, ValueError):
        return "改善 / 恶化 / 基本稳定"
    if diff >= 0.03:
        label = "改善"
    elif diff <= -0.03:
        label = "恶化"
    else:
        label = "基本稳定"
    return f"{label}（上涨比例 {_fmt_pp(diff)}）"


def _index_rank_lines(indices: dict[str, Any], *, reverse: bool) -> list[str]:
    ranked = sorted(
        (
            (name, row)
            for name, row in indices.items()
            if name != "同花顺平均股价指数" and row.get("return_1d") is not None
        ),
        key=lambda item: float(item[1].get("return_1d") or 0),
        reverse=reverse,
    )
    return [
        f"{idx}. {name}（{row.get('symbol', '')}，{_fmt_pct(row.get('return_1d'))}）"
        for idx, (name, row) in enumerate(ranked[:3], start=1)
    ]


def _daily_review_source_note(structure_path: Path, trade_date: str, template_path: Path | None) -> str:
    template_note = f"- 模版：{template_path}" if template_path else "- 模版：未指定，使用内置轻量结构"
    return f"""<!--
数据来源：
{template_note}
- 市场结构 JSON：{structure_path}
- 数据日期：{trade_date}
- 成交额口径：Tushare 日线 amount，原始单位千元，文中换算为亿元。
- 主观判断、持仓、交易计划与仓位建议按设计留空。
-->"""


def render_daily_review_markdown(
    structure: dict[str, Any],
    structure_path: Path,
    template_path: Path | None = None,
) -> tuple[str, list[str]]:
    missing: list[str] = []
    trade_date = _normalise_date(structure.get("date")) or ""
    indices = structure.get("indices") or {}
    breadth = structure.get("breadth") or {}
    breadth_latest = breadth.get("latest") or {}
    breadth_history = breadth.get("history") or []
    _, previous_breadth = _history_row_by_date(breadth_history, trade_date)
    previous_breadth = previous_breadth or {}
    liquidity = (structure.get("liquidity_structure") or {}).get("latest") or {}
    industry_rankings = structure.get("industry_rankings") or {}
    industries = industry_rankings.get("all") or []

    if not indices:
        missing.append("主要指数：缺少 indices 字段")
    if not breadth_latest:
        missing.append("市场广度：缺少 breadth.latest 字段")
    if not liquidity:
        missing.append("两市成交额：缺少 liquidity_structure.latest 字段")
    if not industries:
        missing.append("行业涨跌排名：缺少 industry_rankings.all 字段")

    main_index_names = ["上证指数", "沪深300", "中证500", "中证1000", "中证2000", "创业板指", "科创50"]
    index_rows = []
    for name in main_index_names:
        item = indices.get(name) or {}
        index_rows.append([
            name,
            _fmt_pct(item.get("return_1d")),
            _trend_cn(item.get("daily_trend")),
            _support_relation_text(item),
            _structure_change_text(item),
        ])

    strong_index_lines = _index_rank_lines(indices, reverse=True)
    weak_index_lines = _index_rank_lines(indices, reverse=False)
    while len(strong_index_lines) < 3:
        strong_index_lines.append(f"{len(strong_index_lines) + 1}. ")
    while len(weak_index_lines) < 3:
        weak_index_lines.append(f"{len(weak_index_lines) + 1}. ")

    industry_sorted = sorted(
        [row for row in industries if row.get("return_1d") is not None],
        key=lambda row: float(row.get("return_1d") or 0),
        reverse=True,
    )
    gain_rows = [
        [
            idx,
            row.get("industry", ""),
            _fmt_pct(row.get("return_1d")),
            f"5日 {_fmt_pct(row.get('return_5d'))} / 20日 {_fmt_pct(row.get('return_20d'))}",
        ]
        for idx, row in enumerate(industry_sorted[:10], start=1)
    ]
    loss_rows = [
        [
            idx,
            row.get("industry", ""),
            _fmt_pct(row.get("return_1d")),
            f"5日 {_fmt_pct(row.get('return_5d'))} / 20日 {_fmt_pct(row.get('return_20d'))}",
        ]
        for idx, row in enumerate(reversed(industry_sorted[-10:]), start=1)
    ]

    current_amount = liquidity.get("total_amount") or breadth_latest.get("total_market_amount")
    previous_amount = previous_breadth.get("total_market_amount")
    amount_diff: float | None = None
    amount_diff_pct = ""
    if current_amount is not None and previous_amount is not None:
        try:
            amount_diff = float(current_amount) - float(previous_amount)
            amount_diff_pct = _fmt_pct(amount_diff / float(previous_amount))
        except (TypeError, ValueError, ZeroDivisionError):
            amount_diff = None
            amount_diff_pct = ""

    valid_count = breadth_latest.get("valid_stock_count")
    limit_up_count = _estimate_count(breadth_latest.get("approximate_limit_up_ratio"), valid_count)
    limit_down_count = _estimate_count(breadth_latest.get("approximate_limit_down_ratio"), valid_count)

    markdown = f"""---
日期: "{trade_date}"
类型: A股每日复盘
市场环境:
建议仓位:
tags:
- 股票复盘
- 市场结构
---

# {trade_date} A股每日复盘

## 一、指数、成交额与市场结构

### 今日市场一句话总结

> 

### 两市成交额

- 今日成交额：{_fmt_amount_yi_from_thousand(current_amount)}
- 较昨日：{_signed_amount_yi_diff_from_thousand(amount_diff)}{f"（{amount_diff_pct}）" if amount_diff_pct else ""}
- 相对近期水平：{_amount_level_text(liquidity.get("amount_ratio_5d"), liquidity.get("amount_ratio_20d"))}（5日均额 {_fmt_ratio(liquidity.get("amount_ratio_5d"))} / 20日均额 {_fmt_ratio(liquidity.get("amount_ratio_20d"))}）
- 量价关系：上涨股票成交额占比 {_fmt_pct(liquidity.get("advance_amount_ratio"), signed=False)} / 下跌股票成交额占比 {_fmt_pct(liquidity.get("decline_amount_ratio"), signed=False)}

### 主要指数

{_table(["指数", "涨跌幅", "当前趋势", "与支撑/压力位置关系", "今日结构是否变化"], index_rows)}

结构变化可填写：

- 无明显变化
- 接近支撑
- 支撑得到确认
- 跌破支撑
- 跌破后反抽
- 接近压力
- 突破压力
- 突破后回踩
- 假突破
- 上升趋势转震荡
- 震荡转上涨
- 震荡转下跌

### 市场广度

- 上涨家数：{_fmt_count(breadth_latest.get("advance_count"))}
- 下跌家数：{_fmt_count(breadth_latest.get("decline_count"))}
- 个股涨跌幅中位数：{_fmt_pct(breadth_latest.get("median_stock_return_1d"))}
- 涨停 / 跌停：{_fmt_count(limit_up_count)} / {_fmt_count(limit_down_count)}（近似，按涨跌停比例折算）
- 广度状态：{_breadth_change_text(breadth_latest.get("advance_ratio"), previous_breadth.get("advance_ratio"))}

### 指数与广度综合判断

> 指数上涨或下跌是否代表大多数股票的真实表现：

> 今日属于普涨、普跌、权重拉升还是结构分化：

---

## 二、指数强弱与市场风格

### 强势指数

{chr(10).join(strong_index_lines)}

### 弱势指数

{chr(10).join(weak_index_lines)}

### 风格判断

- [ ] 大盘权重占优
- [ ] 中小盘占优
- [ ] 科技成长占优
- [ ] 价值防御占优
- [ ] 大小盘同步走强
- [ ] 大小盘同步走弱
- [ ] 风格分化，没有明确主导方向

### 今日强弱结论

> 

---

## 三、行业涨跌排名

### 涨幅靠前的10个行业

{_table(["排名", "行业", "涨跌幅", "简要观察"], gain_rows)}

### 跌幅靠前的10个行业

{_table(["排名", "行业", "涨跌幅", "简要观察"], loss_rows)}

### 行业结构结论

- 今日领涨方向：
- 今日主要风险方向：
- 强势行业是首次启动、延续还是加速：
- 弱势行业是正常调整还是风险扩散：
- 是否出现明显风格切换：

> 

---

## 四、市场环境与仓位建议

### 当前市场环境

- [ ] 积极：指数、广度和成交额相互确认
- [ ] 中性偏强：结构性机会存在，但不是全面强势
- [ ] 中性：方向不清晰，以等待和精选为主
- [ ] 中性偏弱：风险增加，赚钱效应有限
- [ ] 保守：趋势或广度明显恶化，以控制风险为主

### 环境结论

> 

### 建议仓位

- 建议仓位区间：
- 当前实际仓位：
- 是否需要调整：增加 / 保持 / 降低
- 主要理由：

### 仓位调整条件

**提高仓位需要看到：**

- 
- 

**降低仓位需要看到：**

- 
- 

> 仓位结论应结合交易系统、个股位置和风险承受能力，不仅依据指数单日涨跌。

---

## 五、交易复盘

### 当前持仓

| 股票 | 所属方向 | 持仓逻辑 | 当前状态 | 明日处理计划 |
|---|---|---|---|---|
|  |  |  |  |  |
|  |  |  |  |  |
|  |  |  |  |  |

### 今日交易

| 股票 | 操作 | 操作理由 | 是否符合计划 | 结果 |
|---|---|---|---|---|
|  |  |  |  |  |
|  |  |  |  |  |

### 今日做得好的地方

> 

### 今日存在的问题

- [ ] 计划外交易
- [ ] 追涨
- [ ] 提前抄底
- [ ] 仓位过重
- [ ] 止损拖延
- [ ] 过早卖出
- [ ] 受到情绪影响
- [ ] 市场判断与实际交易不一致
- [ ] 没有明显问题

> 

### 明日改进重点

> 明天只重点改进一个问题：

### 明日交易计划

- 重点观察方向：
- 重点观察股票：
- 允许交易的条件：
- 放弃交易的条件：
- 明日风险控制原则：

---

## 今日最终结论

> **市场状态：**

> **强势方向：**

> **弱势方向：**

> **建议仓位：**

> **明日核心策略：**

{_daily_review_source_note(structure_path, trade_date, template_path)}
"""

    return markdown.rstrip() + "\n", missing


def generate_daily_review(
    config: dict[str, Any],
    *,
    date: str | None,
    output_dir: str | Path,
    template: str | Path | None = None,
    symbol: str = DEFAULT_INDEX_SYMBOL,
    overwrite: bool = True,
) -> DailyReviewResult:
    requested_date = _normalise_date(date)
    structure, structure_path = _load_structure(config, symbol, requested_date)
    trade_date = _normalise_date(structure.get("date")) or requested_date or ""
    template_path = Path(template).expanduser() if template else None
    if template_path and not template_path.exists():
        raise FileNotFoundError(f"复盘模版不存在: {template_path}")

    markdown, missing = render_daily_review_markdown(
        structure,
        structure_path=structure_path,
        template_path=template_path,
    )
    output_root = Path(output_dir).expanduser()
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / f"{trade_date} 股票复盘.md"
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"输出文件已存在: {output_path}")
    output_path.write_text(markdown, encoding="utf-8")
    return DailyReviewResult(
        output_path=output_path,
        structure_path=structure_path,
        trade_date=trade_date,
        missing_items=missing,
    )
