#!/usr/bin/env python3
"""Generate a deterministic, independent Codex audit of a 400-day batch."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analysis.index_market_llm import _markdown_html  # noqa: E402
from cli.common import load_config  # noqa: E402


def _pct(value: Any, digits: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return "—" if not np.isfinite(number) else f"{number * 100:+.{digits}f}%"


def _num(value: Any, digits: int = 3) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return "—" if not np.isfinite(number) else f"{number:.{digits}f}"


def _md_table(headers: list[str], rows: list[list[Any]]) -> str:
    def clean(value: Any) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")

    lines = ["| " + " | ".join(clean(item) for item in headers) + " |"]
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    lines.extend("| " + " | ".join(clean(item) for item in row) + " |" for row in rows)
    return "\n".join(lines)


def _bool_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index)
    values = frame[column]
    if pd.api.types.is_bool_dtype(values):
        return values.fillna(False)
    return values.astype(str).str.lower().isin({"true", "1", "yes"})


def _episode_count(mask: pd.Series) -> int:
    active = mask.fillna(False).astype(bool)
    return int((active & ~active.shift(1, fill_value=False)).sum())


def _moving_block_difference_ci(
    outcome: pd.Series,
    event: pd.Series,
    *,
    block: int = 20,
    draws: int = 3000,
    seed: int = 20260714,
) -> tuple[float, float, float, int, int]:
    y = pd.to_numeric(outcome, errors="coerce").to_numpy(dtype="float64")
    e = event.fillna(False).astype(bool).to_numpy()
    valid = np.isfinite(y)
    observed = float(np.nanmean(y[valid & e]) - np.nanmean(y[valid & ~e])) if (valid & e).any() and (valid & ~e).any() else np.nan
    n = len(y)
    if n < block or not np.isfinite(observed):
        return observed, np.nan, np.nan, int((valid & e).sum()), int((valid & ~e).sum())
    rng = np.random.default_rng(seed)
    blocks_needed = int(np.ceil(n / block))
    differences: list[float] = []
    for _ in range(draws):
        starts = rng.integers(0, n - block + 1, size=blocks_needed)
        index = np.concatenate([np.arange(start, start + block) for start in starts])[:n]
        sample_y, sample_e, sample_valid = y[index], e[index], valid[index]
        if (sample_valid & sample_e).sum() < 2 or (sample_valid & ~sample_e).sum() < 2:
            continue
        differences.append(
            float(np.nanmean(sample_y[sample_valid & sample_e]) - np.nanmean(sample_y[sample_valid & ~sample_e]))
        )
    if not differences:
        return observed, np.nan, np.nan, int((valid & e).sum()), int((valid & ~e).sum())
    low, high = np.quantile(differences, [0.025, 0.975])
    return observed, float(low), float(high), int((valid & e).sum()), int((valid & ~e).sum())


def _state_outcome_rows(panel: pd.DataFrame, dimension: str, states: list[str]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for state in states:
        group = panel[panel[dimension].astype(str).eq(state)]
        row: list[Any] = [state, len(group), f"{len(group) / len(panel):.1%}"]
        for horizon in (1, 5, 20):
            mature = _bool_series(group, f"future_mature_{horizon}d")
            returns = pd.to_numeric(group.loc[mature, f"future_all_a_return_{horizon}d"], errors="coerce").dropna()
            mdd = pd.to_numeric(group.loc[mature, f"future_all_a_max_drawdown_{horizon}d"], errors="coerce").dropna()
            row.extend(
                [
                    f"{len(returns)}/{_pct(returns.mean())}/{returns.gt(0).mean():.1%}" if not returns.empty else "0/—/—",
                    _pct(mdd.mean()) if not mdd.empty else "—",
                ]
            )
        rows.append(row)
    return rows


def _candidate_rows(panel: pd.DataFrame, score_column: str, label: str) -> list[list[Any]]:
    rows: list[list[Any]] = []
    score = pd.to_numeric(panel[score_column], errors="coerce")
    for cutoff in (3, 4, 5):
        event = score.ge(cutoff)
        values: list[Any] = [label, f">={cutoff}", int(event.sum()), _episode_count(event)]
        for horizon in (5, 20):
            observed, low, high, n_event, _ = _moving_block_difference_ci(
                panel[f"future_all_a_return_{horizon}d"], event, block=20,
                seed=20260714 + cutoff * 100 + horizon,
            )
            event_return = pd.to_numeric(
                panel.loc[event & _bool_series(panel, f"future_mature_{horizon}d"), f"future_all_a_return_{horizon}d"],
                errors="coerce",
            ).dropna()
            values.append(
                f"n={n_event}，均值{_pct(event_return.mean())}，相对其余{_pct(observed)}，"
                f"区块CI[{_pct(low)}, {_pct(high)}]"
            )
        rows.append(values)
    return rows


def _bh_fdr(p_values: pd.Series) -> pd.Series:
    result = pd.Series(np.nan, index=p_values.index, dtype="float64")
    valid = pd.to_numeric(p_values, errors="coerce").dropna().sort_values()
    if valid.empty:
        return result
    m = len(valid)
    adjusted = (valid * m / np.arange(1, m + 1)).iloc[::-1].cummin().iloc[::-1].clip(upper=1.0)
    result.loc[adjusted.index] = adjusted
    return result


def _correlation_diagnostics(correlations: pd.DataFrame) -> tuple[pd.DataFrame, int | None]:
    work = correlations.copy()
    r = pd.to_numeric(work["spearman"], errors="coerce")
    n = pd.to_numeric(work["sample_count"], errors="coerce")
    denominator = (1.0 - r.pow(2)).clip(lower=1e-12)
    statistic = r * np.sqrt((n - 2).clip(lower=1) / denominator)
    try:
        from scipy.stats import t as student_t

        work["naive_p"] = 2.0 * student_t.sf(np.abs(statistic), df=(n - 2).clip(lower=1))
        fdr_count: int | None = int(_bh_fdr(work["naive_p"]).le(0.10).sum())
    except ImportError:
        work["naive_p"] = np.nan
        fdr_count = None
    work["bh_q"] = _bh_fdr(work["naive_p"])
    work["abs_spearman"] = r.abs()
    return work.sort_values("abs_spearman", ascending=False), fdr_count


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_completed_batch(batch_dir: Path) -> dict[str, Any]:
    in_progress = batch_dir / "market_structure_400d_in_progress.json"
    complete_path = batch_dir / "market_structure_400d_complete.json"
    if in_progress.exists() or not complete_path.is_file():
        raise RuntimeError("历史批次仍在写入或缺少完成哨兵")
    complete = json.loads(complete_path.read_text(encoding="utf-8"))
    if complete.get("status") != "complete" or int(complete.get("snapshot_count", 0)) != 400:
        raise RuntimeError("历史批次完成哨兵未通过")
    for name, expected in (complete.get("input_files") or {}).items():
        path = batch_dir / name
        if not path.is_file():
            raise RuntimeError(f"完成哨兵中的输入文件缺失: {name}")
        if path.stat().st_size != int(expected.get("bytes", -1)):
            raise RuntimeError(f"完成后输入文件大小变化: {name}")
        if _sha256(path) != expected.get("sha256"):
            raise RuntimeError(f"完成后输入文件哈希变化: {name}")
    return complete


def build_report(batch_dir: Path) -> str:
    completion = _validate_completed_batch(batch_dir)
    panel = pd.read_csv(batch_dir / "market_structure_400d_panel.csv", dtype={"trade_date": str})
    config = load_config()
    quality = json.loads((batch_dir / "market_structure_400d_quality_checks.json").read_text(encoding="utf-8"))
    episodes = pd.read_csv(batch_dir / "market_structure_400d_event_episodes.csv")
    transitions = pd.read_csv(batch_dir / "market_structure_400d_state_transitions.csv")
    correlations = pd.read_csv(batch_dir / "market_structure_400d_feature_correlations.csv")
    style_validation = pd.read_csv(batch_dir / "market_structure_400d_style_validation.csv")
    industry_validation = pd.read_csv(batch_dir / "market_structure_400d_industry_validation.csv")
    missingness = pd.read_csv(batch_dir / "market_structure_400d_missingness.csv")

    required_checks = (
        "snapshot_count_passed", "all_as_of_checks_passed", "all_required_files_exist",
        "facts_contain_no_future_labels", "breadth_counts_reconcile",
        "tail_pressure_recomputed_matches_production", "future_maturity_checks_passed",
        "per_snapshot_deepseek_calls_zero",
    )
    if (
        quality.get("status") != "passed"
        or quality.get("batch_run_id") != completion.get("batch_run_id")
        or not all(quality.get(key) is True for key in required_checks)
        or len(panel) != 400
        or panel["trade_date"].nunique() != 400
    ):
        raise RuntimeError("Codex审计要求通过质量检查的400个唯一交易日")

    ice = _bool_series(panel, "research_icepoint_candidate_v1")
    hot = _bool_series(panel, "research_overheat_candidate_v1")
    ice5 = _moving_block_difference_ci(panel["future_all_a_return_5d"], ice, block=20, seed=15)
    hot20 = _moving_block_difference_ci(panel["future_all_a_return_20d"], hot, block=20, seed=20)
    corrected_pressure = bool(quality.get("tail_pressure_recomputed_matches_production"))
    evidence_verdict = (
        "机械完整性和修正规则一致性通过，但预测有效性证据仍不足"
        if corrected_pressure else "批次内部口径未通过，不能用于有效性判断"
    )

    state_headers = [
        "状态", "天数", "占比", "1日 n/均值/胜率", "1日MDD", "5日 n/均值/胜率", "5日MDD",
        "20日 n/均值/胜率", "20日MDD",
    ]
    tail_rows = _state_outcome_rows(panel, "tail_pressure", ["low", "medium", "high", "extreme"])
    risk_rows = _state_outcome_rows(panel, "risk_direction", ["expanding", "stable", "contracting", "repairing"])
    candidate_rows = _candidate_rows(panel, "research_icepoint_score_v1", "冰点")
    candidate_rows += _candidate_rows(panel, "research_overheat_score_v1", "过热")

    episode_rows: list[list[Any]] = []
    for event_type, group in episodes.groupby("event_type"):
        returns5 = pd.to_numeric(group["future_all_a_return_5d"], errors="coerce").dropna()
        returns20 = pd.to_numeric(group["future_all_a_return_20d"], errors="coerce").dropna()
        episode_rows.append(
            [
                event_type, len(group), int(group["duration_days"].sum()),
                len(returns5), _pct(returns5.mean()), _pct(returns5.median()),
                len(returns20), _pct(returns20.mean()), _pct(returns20.median()),
            ]
        )

    transition_rows: list[list[Any]] = []
    for dimension in ("tail_pressure", "risk_direction", "breadth_today_state"):
        selected = transitions[transitions["dimension"].eq(dimension)]
        for state in sorted(selected["from_state"].unique()):
            row = selected[selected["from_state"].eq(state)]
            self_probability = row.loc[row["to_state"].eq(state), "probability"]
            top = row.sort_values("probability", ascending=False).iloc[0]
            transition_rows.append(
                [dimension, state, _pct(self_probability.iloc[0], 1) if not self_probability.empty else "0.0%", top["to_state"], _pct(top["probability"], 1)]
            )

    corr, fdr_count = _correlation_diagnostics(correlations)
    correlation_rows = [
        [row.feature, row.outcome, int(row.sample_count), _num(row.spearman), _num(row.bh_q)]
        for row in corr.head(15).itertuples()
    ]

    lag_rows: list[list[Any]] = []
    for column in panel.columns:
        if not column.endswith("_lag_calendar_days"):
            continue
        values = pd.to_numeric(panel[column], errors="coerce")
        lag_rows.append(
            [column, int(values.notna().sum()), int(values.gt(0).sum()), _num(values.max(), 0), _num(values.mean())]
        )
    high_missing = missingness[pd.to_numeric(missingness["missing_ratio"], errors="coerce").gt(0.05)].head(20)
    missing_rows = [
        [row.column, int(row.missing_count), f"{float(row.missing_ratio):.1%}"]
        for row in high_missing.itertuples()
    ]

    style_rows = [
        [
            row.dimension, int(row.horizon),
            int(row.leader_hit_n) if pd.notna(row.leader_hit_n) else "—",
            _pct(row.leader_hit_rate) if pd.notna(row.leader_hit_rate) else "—",
            int(row.strength_rank_ic_n) if pd.notna(row.strength_rank_ic_n) else "—",
            _num(row.strength_rank_ic_mean), _num(row.strength_rank_ic_median),
        ]
        for row in style_validation.itertuples()
        if row.dimension == "all_styles"
    ]
    industry_rows = [
        [
            int(row.horizon), int(row.sample_count), _pct(row.strong_minus_weak_mean),
            _pct(row.strong_minus_weak_median), _pct(row.strong_outperforms_rate, 1),
            _pct(row.q10), _pct(row.q90),
        ]
        for row in industry_validation.itertuples()
    ]

    date_year = panel["trade_date"].str[:4]
    annual_rows: list[list[Any]] = []
    for label, event in (("冰点>=4", ice), ("过热>=4", hot)):
        for year in sorted(date_year.unique()):
            selected = event & date_year.eq(year)
            values = pd.to_numeric(panel.loc[selected, "future_all_a_return_5d"], errors="coerce").dropna()
            annual_rows.append([label, year, int(selected.sum()), _episode_count(selected), _pct(values.mean()), _pct(values.median())])

    try:
        revision = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=PROJECT_ROOT, text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        revision = "unknown"

    return f"""# Codex 独立审计：A股市场结构 400 交易日

生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}  
数据范围：{panel['trade_date'].min()} 至 {panel['trade_date'].max()}，400 个交易日  
研究标的：上证指数结构页；全市场基准为 700082.TI 同花顺全A（沪深京等权）  
数据源：本地 Tushare/同花顺指数及当前个股缓存，共 {quality.get('stock_file_count')} 个股票文件；股票复权口径 `{config.get('data', {}).get('stock_adj')}`  
预热口径：每个信号日最多 {quality.get('history_bars')} 个交易日，尾压分位窗口最多756日  
代码基线：Git `{revision}`，包含本轮未提交修正  
结论属性：离线结构研究，不是策略回测；没有成交、手续费、滑点或仓位口径，不构成交易建议。

## 1. 结论先行

**结论：{evidence_verdict}。** 400 日只覆盖约 19 个月，适合发现数据错误、状态命名问题和候选规则方向，不足以证明跨牛熊稳定性。20 日标签虽然有 {int(_bool_series(panel, 'future_mature_20d').sum())} 行，但高度重叠，粗略独立窗口只有约 {int(_bool_series(panel, 'future_mature_20d').sum() / 20)} 个。

- 冰点候选（分数>=4）有 {int(ice.sum())} 日、{_episode_count(ice)} 个连续 episode。未来5日相对非候选的全A收益差为 {_pct(ice5[0])}，按20日移动区块重采样得到的95%区间为 [{_pct(ice5[1])}, {_pct(ice5[2])}]。若区间跨0，只能写“有反弹迹象但证据不足”。
- 过热候选（分数>=4）有 {int(hot.sum())} 日、{_episode_count(hot)} 个 episode。未来20日相对非候选收益差为 {_pct(hot20[0])}，95%区间 [{_pct(hot20[1])}, {_pct(hot20[2])}]。当前分数衡量“市场热”，不能直接等同于“即将下跌”。
- 尾部压力应解释为**同日压力温度**，不能默认越高未来越差；高压后的反弹、继续下探和修复必须由风险方向与 episode 分开验证。
- `risk_direction` 是逐日差分，状态翻转较频繁；在进入仓位或预测模型前应增加变化死区和持续性确认。
- 风格与行业榜已补未来相对收益、leader命中率和横截面 rank IC，但400日与代理指数成分历史仍不足，暂不应转成交易信号。

## 2. 数据质量与口径审计

- 机械检查：`{quality.get('status')}`；400个日期唯一、逐日文件存在、事实包无未来标签、逐日 DeepSeek 调用为 {quality.get('per_snapshot_deepseek_calls')}。
- as-of：指数、市场广度、风格历史均截断到信号日；未来标签只存在批次离线面板，不进入日归档或LLM事实包。
- 本轮已修正：历史分位按最近756个交易日行窗口、北交所近似涨跌停阈值29.5%、背离差值统一为“全A－沪深300”、强修复要求弱势背景、MAE与真正峰谷MDD分开。
- 尾压重算与生产是否完全一致：`{quality.get('tail_pressure_recomputed_matches_production')}`。
- 原有日常归档隔离数：{quality.get('isolated_source_conflict_count')}；日期：{quality.get('isolated_source_conflict_dates')}。原文件保留，研究面板引用本次新鲜重放快照。
- 仍未解决：当前股票池不是 point-in-time，缺退市股、历史ST、历史行业分类、IPO无涨跌幅限制日和精确每日涨跌停价；存在幸存者偏差。
- 同花顺代理的成分历史由供应商维护，`data_coverage=1` 只表示代理指数当日有行情，不代表底层成分完全可追溯。

### 数据新鲜度

{_md_table(['字段', '有效日', '滞后日数>0', '最大日历滞后', '平均滞后'], lag_rows)}

### 缺失率超过5%的前20字段

{_md_table(['字段', '缺失数', '缺失率'], missing_rows)}

## 3. 尾部压力与风险方向

每个“收益”单元为 `成熟样本数/全A平均收益/胜率`；MDD是真正的信号日至未来窗口峰谷最大回撤。

### 尾部压力

{_md_table(state_headers, tail_rows)}

### 风险方向

{_md_table(state_headers, risk_rows)}

### 次日持续与主要转移

{_md_table(['维度', '当前状态', '自保持率', '最大概率去向', '概率'], transition_rows)}

判断：压力等级首先验证是否能区分**当日**极端程度；未来收益若不单调，不代表指标无效，而说明它不是方向预测器。风险方向若 contracting/expanding 高频互换，应采用滚动MAD或分位变化死区、至少2日确认，并按“新低、极端跌幅、波动/离散”三个低相关证据族聚合，避免重复投票。

## 4. 冰点与过热候选

下面的区块CI按20日移动区块、3000次固定种子重采样，比较候选日与其余日平均收益差；它仍是探索性区间，不替代冻结样本外检验。

{_md_table(['候选', '阈值', '天数', 'episode', '未来5日', '未来20日'], candidate_rows)}

### 去重 episode

{_md_table(['事件', 'episode', '覆盖日', '5日成熟n', '5日均值', '5日中位', '20日成熟n', '20日均值', '20日中位'], episode_rows)}

### 分年度稳定性

{_md_table(['候选', '年度', '天数', 'episode', '5日均值', '5日中位'], annual_rows)}

冰点必须拆成：高压扩散、 高压稳定、 高压收缩/修复、规则候选四类。真正可用的冰点信号还应报告距离后续最低点天数、恢复到信号价时间、5日MAE和假冰点率。过热则应拆成“高温延续”和“高温衰竭”：后者至少需要新高减少、A/D转弱、上涨比例下降或放量滞涨确认。

## 5. 风格与行业强弱榜

风格 rank IC 是当前五类风格 strength 排名与未来收益排名的日度 Spearman；leader命中表示当前20日leader在未来窗口仍为五类第一。

{_md_table(['范围', '周期', 'leader样本', '命中率', 'rankIC样本', 'rankIC均值', 'rankIC中位'], style_rows)}

行业表比较当前20日最强前三与最弱前三的未来等权收益差。

{_md_table(['周期', '样本', '强-弱均值', '中位', '强者继续领先率', 'Q10', 'Q90'], industry_rows)}

判断：若rank IC或强弱差缺少稳定正值，只能把榜单作为当前结构描述。正式验证需扩大到完整行业集合，计算逐日横截面排名IC、换手率、成分变更，并按年度/波动阶段检查稳定性。

## 6. 连续指标与未来结果

以下为绝对Spearman最大的15组。`BH q` 是对当前相关表的朴素多重检验修正；由于收益重叠和序列相关，它仍会低估不确定性，只用于筛选研究方向。

{_md_table(['特征', '未来结果', 'n', 'Spearman', 'BH q'], correlation_rows)}

朴素 BH-FDR 10% 下显著组合数：{fdr_count if fdr_count is not None else '未计算（当前环境没有SciPy）'}。即使能够计算，重叠收益会违反独立样本假设；正式推断应使用 Newey-West HAC（滞后至少 horizon-1）、移动区块 bootstrap（10/20/40日敏感性）和 purged walk-forward，不能把400行当作400个独立样本。

## 7. 失败模式与系统问题

1. **股票池偏差**：当前上市池回放历史，退市股与历史ST缺失，会高估广度和修复质量。
2. **精确涨跌停缺失**：虽已修正北交所30%板块规则，仍需Tushare每日涨跌停价/涨跌停明细来处理ST变更、IPO前五日和价格取整。
3. **代理指数成分不可追溯**：同花顺行业/风格指数历史行情可用，但成分调整是供应商黑箱。
4. **状态内部异质**：同为high/extreme，扩散与收缩的含义相反；同为高温，趋势延续与衰竭也相反。
5. **阈值同源相关**：跌超5%、近似跌停、离散度和波动不是五份独立证据，应按证据族降权。
6. **标签重叠**：5/10/20日结果高度重叠；事件天数、episode数和有效独立窗口必须同时报告。
7. **数据版本仍未完全冻结**：本批次已记录代码哈希、安全配置、股票元数据哈希及缓存文件名/大小/mtime清单，但还没有对数千份行情CSV逐文件做内容哈希，也没有历史股票池快照。

## 8. 改进优先级

### P0：进入下一轮验证前必须完成

1. 建设point-in-time股票池：上市/退市、历史ST、上市板块、行业分类生效区间。
2. 接入逐日精确涨跌停价或Tushare涨跌停明细，替代近似阈值作为正式冰点证据。
3. 对每个指数、风格代理和行业代理增加独立新鲜度门禁；滞后时降级或停止该分支结论。
4. 冻结状态定义与参数版本，记录代码、配置、源CSV哈希、股票池快照；批次质量分为“机械完整性”和“研究有效性”。
5. 把未来标签、MAE、MFE、真正MDD的字段名与定义写入契约测试，禁止报告层混用。

### P1：验证设计

1. 扩展到至少5年、最好8—10年（约1200—2500交易日），覆盖牛、熊、震荡和流动性冲击。
2. 按episode起点推断，20日信号至少20日purge/embargo；使用block bootstrap、HAC和BH-FDR。
3. 用事前20日收益、5日波动、MA20覆盖、流动性、年度匹配对照；报告效应量而非只看胜率。
4. 风险方向增加死区/持续确认；尾压按“下跌强度、创新低、波动离散”证据族重构。
5. 对风格/行业计算未来相对收益rank IC、leader持续期、换手率和不同阶段稳定性。

### P2：样本外运行

1. 将规则开发期与冻结测试期分开，采用purged walk-forward；规则冻结后才进入样本外监控。
2. 做80/85/90/95%分位、分数3/4/5、区块10/20/40日的敏感性矩阵。
3. 建立假冰点、过热后继续上涨、风险方向频繁翻转的失败案例库。
4. LLM只解释冻结事实和审计结果，不参与状态生成、标签或阈值调参。

## 9. 可否用于预测、仓位或交易

- **市场描述/人工复盘：可以，且修正后比原版可靠。**
- **预测概率：暂不可以。** 当前样本短、非完整point-in-time、标签重叠，置信区间与阶段稳定性尚未通过。
- **自动仓位或交易：不可以。** 本批次不是含手续费、滑点、T+1、涨跌停成交约束的策略回测，也没有样本外门槛。
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="生成Codex独立400日市场结构审计")
    parser.add_argument("batch_dir")
    args = parser.parse_args()
    root = Path(args.batch_dir)
    report = build_report(root)
    md_path = root / "codex_market_structure_400d_audit.md"
    html_path = root / "codex_market_structure_400d_audit.html"
    repo_path = PROJECT_ROOT / "docs" / "research" / "market_structure_400d_codex_audit_20260714.md"
    md_path.write_text(report, encoding="utf-8")
    html_path.write_text(_markdown_html(report, "Codex：市场结构400日独立审计"), encoding="utf-8")
    repo_path.parent.mkdir(parents=True, exist_ok=True)
    repo_path.write_text(report, encoding="utf-8")
    print(f"Codex审计: {md_path}")
    print(f"HTML报告: {html_path}")
    print(f"项目文档: {repo_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
