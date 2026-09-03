"""User-maintained custom-concept pools for the strong-stock radar.

The pools deliberately use the current membership list for every historical
date.  They are a research view, not point-in-time index constituents.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from data.stock_pool import normalize_symbol


DEFAULT_PATH = Path("config/custom_concept_pools.yaml")


class ConceptPoolConfigError(ValueError):
    """Raised for an invalid custom-concept YAML document."""


@dataclass(frozen=True)
class CustomConceptPool:
    concept_id: str
    name: str
    category: str
    note: str
    members: tuple[str, ...]
    invalid_members: tuple[str, ...] = ()


@dataclass(frozen=True)
class CustomConceptSettings:
    benchmark: str = "default"
    weighting: str = "equal_weight"
    min_valid_members: int = 3
    min_coverage_ratio: float = 0.60
    history_mode: str = "current_snapshot"


def custom_concept_pool_path(config: dict[str, Any]) -> Path:
    configured = (config.get("strong_stock_radar", {}) or {}).get("custom_concepts", {}).get("path")
    return Path(configured) if configured else DEFAULT_PATH


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "settings": {}, "pools": []}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConceptPoolConfigError(f"自定义概念池 YAML 格式错误: {path}: {exc}") from exc
    if payload is None:
        return {"version": 1, "settings": {}, "pools": []}
    if not isinstance(payload, dict):
        raise ConceptPoolConfigError("自定义概念池 YAML 顶层必须是映射")
    if not isinstance(payload.get("settings", {}), dict) or not isinstance(payload.get("pools", []), list):
        raise ConceptPoolConfigError("自定义概念池 YAML 必须包含 settings 映射和 pools 列表")
    return payload


def load_custom_concept_pools(
    config: dict[str, Any], metadata: pd.DataFrame, path: str | Path | None = None
) -> tuple[CustomConceptSettings, list[CustomConceptPool], list[str], Path]:
    """Load enabled pools, retaining invalid member codes as warnings only."""
    file_path = Path(path) if path is not None else custom_concept_pool_path(config)
    payload = _read_yaml(file_path)
    settings_raw = payload.get("settings", {}) or {}
    settings = CustomConceptSettings(
        benchmark=str(settings_raw.get("benchmark", "default")),
        weighting=str(settings_raw.get("weighting", "equal_weight")),
        min_valid_members=max(1, int(settings_raw.get("min_valid_members", 3))),
        min_coverage_ratio=float(settings_raw.get("min_coverage_ratio", 0.60)),
        history_mode=str(settings_raw.get("history_mode", "current_snapshot")),
    )
    if not 0 < settings.min_coverage_ratio <= 1:
        raise ConceptPoolConfigError("min_coverage_ratio 必须在 (0, 1] 内")
    if settings.benchmark != "default":
        raise ConceptPoolConfigError("当前仅支持 benchmark: default（复用行业 RS 基准）")
    if settings.weighting != "equal_weight":
        raise ConceptPoolConfigError("当前仅支持 weighting: equal_weight")
    if settings.history_mode != "current_snapshot":
        raise ConceptPoolConfigError("当前仅支持 history_mode: current_snapshot")

    known = set(metadata.get("ts_code", pd.Series(dtype=str)).dropna().astype(str).str.upper())
    ids: set[str] = set()
    names: set[str] = set()
    pools: list[CustomConceptPool] = []
    warnings: list[str] = []
    for item in payload.get("pools", []):
        if not isinstance(item, dict):
            raise ConceptPoolConfigError("pools 的每项必须是映射")
        if not bool(item.get("enabled", True)):
            continue
        concept_id = str(item.get("id", "")).strip()
        name = str(item.get("name", "")).strip()
        if not concept_id or not name:
            raise ConceptPoolConfigError("启用概念池必须包含非空 id 和 name")
        if concept_id in ids or name in names:
            raise ConceptPoolConfigError(f"启用概念池 id/name 重复: {concept_id} / {name}")
        ids.add(concept_id)
        names.add(name)
        raw_members = item.get("members", [])
        if not isinstance(raw_members, list):
            raise ConceptPoolConfigError(f"概念池 {name} 的 members 必须是列表")
        members: list[str] = []
        invalid: list[str] = []
        seen: set[str] = set()
        for raw in raw_members:
            code = normalize_symbol(raw.get("code") if isinstance(raw, dict) else raw)
            if not code:
                invalid.append(str(raw))
                continue
            if code in seen:
                warnings.append(f"概念池 {name} 含重复代码 {code}，已去重")
                continue
            seen.add(code)
            if code not in known:
                invalid.append(code)
                warnings.append(f"概念池 {name} 无效或无主数据代码 {code}，已排除")
                continue
            members.append(code)
        if len(members) < 5:
            warnings.append(f"概念池 {name} 配置成员少于5只，属于小样本")
        if not members:
            warnings.append(f"概念池 {name} 没有有效成员，不参与计算")
            continue
        pools.append(CustomConceptPool(concept_id, name, str(item.get("category", "")), str(item.get("note", "")), tuple(members), tuple(invalid)))
    return settings, pools, warnings, file_path


def validate_custom_concept_pools(config: dict[str, Any], metadata: pd.DataFrame, path: str | Path | None = None) -> dict[str, Any]:
    settings, pools, warnings, file_path = load_custom_concept_pools(config, metadata, path)
    return {
        "path": str(file_path),
        "pool_count": len(pools),
        "enabled_count": len(pools),
        "history_mode": settings.history_mode,
        "benchmark": settings.benchmark,
        "weighting": settings.weighting,
        "warnings": warnings,
        "pools": [
            {"id": pool.concept_id, "name": pool.name, "members": len(pool.members), "invalid_members": list(pool.invalid_members), "small_sample": len(pool.members) < 5}
            for pool in pools
        ],
        "can_run": bool(pools),
    }


def build_custom_concept_rs_history(
    pools: list[CustomConceptPool],
    settings: CustomConceptSettings,
    close: pd.DataFrame,
    tradable_mask: pd.DataFrame,
    benchmark_returns: dict[int, pd.Series],
    windows: list[int],
) -> pd.DataFrame:
    """Calculate equal-weight concept returns using the radar's existing inputs."""
    frames: list[pd.DataFrame] = []
    for pool in pools:
        symbols = [symbol for symbol in pool.members if symbol in close.columns]
        if not symbols:
            continue
        member_close = close[symbols]
        member_tradable = tradable_mask[symbols]
        item = pd.DataFrame(index=member_close.index)
        item["trade_date"] = item.index.astype(str)
        item["concept_id"] = pool.concept_id
        item["concept_name"] = pool.name
        item["category"] = pool.category
        item["total_members"] = len(pool.members)
        daily_return = member_close / member_close.shift(1) - 1.0
        daily_valid = member_tradable & daily_return.notna()
        valid_members = daily_valid.sum(axis=1)
        coverage = valid_members / len(pool.members)
        eligible_daily = valid_members.ge(settings.min_valid_members) & coverage.ge(settings.min_coverage_ratio)
        item["valid_members"] = valid_members
        item["coverage_ratio"] = coverage
        item["member_return_mean"] = daily_return.where(daily_valid).mean(axis=1).where(eligible_daily)
        item["member_return_median"] = daily_return.where(daily_valid).median(axis=1).where(eligible_daily)
        item["pct_advancing"] = (daily_return.gt(0).where(daily_valid).sum(axis=1) / valid_members.replace(0, np.nan)).where(eligible_daily)
        item["small_sample"] = len(pool.members) < 5
        item["insufficient_members"] = valid_members.lt(settings.min_valid_members)
        item["insufficient_coverage"] = coverage.lt(settings.min_coverage_ratio)
        item["history_mode"] = settings.history_mode
        for window in windows:
            stock_return = member_close / member_close.shift(int(window)) - 1.0
            valid = member_tradable & stock_return.notna()
            count = valid.sum(axis=1)
            ratio = count / len(pool.members)
            eligible = count.ge(settings.min_valid_members) & ratio.ge(settings.min_coverage_ratio)
            group_return = stock_return.where(valid).mean(axis=1).where(eligible)
            item[f"concept_return_{window}d"] = group_return
            item[f"concept_rs_{window}d"] = (group_return - benchmark_returns[int(window)]).where(eligible)
        frames.append(item.reset_index(drop=True))
    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if result.empty:
        return result
    for window in windows:
        raw = f"concept_rs_{window}d"
        pct = f"concept_rs{window}_pct"
        result[pct] = result.groupby("trade_date")[raw].rank(pct=True, method="max") * 100.0
        rank = result.groupby("trade_date")[pct].rank(method="max", ascending=False)
        denominator = result.groupby("trade_date")[pct].transform("count")
        result[f"concept_rs{window}_rank"] = rank.where(result[pct].notna())
        result[f"concept_rs{window}_denominator"] = denominator.where(result[pct].notna())
        matrix = result.pivot(index="trade_date", columns="concept_id", values=pct).sort_index()
        delta = matrix - matrix.shift(5)
        result = result.merge(delta.rename_axis(index="trade_date", columns="concept_id").reset_index().melt(id_vars="trade_date", var_name="concept_id", value_name=f"concept_rs{window}_pct_delta_5d_common"), on=["trade_date", "concept_id"], how="left", validate="one_to_one")
        rank_matrix = result.pivot(index="trade_date", columns="concept_id", values=f"concept_rs{window}_rank").sort_index()
        previous_rank = rank_matrix.shift(5)
        result = result.merge(previous_rank.rename_axis(index="trade_date", columns="concept_id").reset_index().melt(id_vars="trade_date", var_name="concept_id", value_name=f"concept_rs{window}_previous_rank"), on=["trade_date", "concept_id"], how="left", validate="one_to_one")
        denominator_matrix = result.pivot(index="trade_date", columns="concept_id", values=f"concept_rs{window}_denominator").sort_index()
        previous_denominator = denominator_matrix.shift(5)
        result = result.merge(previous_denominator.rename_axis(index="trade_date", columns="concept_id").reset_index().melt(id_vars="trade_date", var_name="concept_id", value_name=f"concept_rs{window}_previous_denominator"), on=["trade_date", "concept_id"], how="left", validate="one_to_one")
        result[f"concept_rs{window}_rank_change_5d"] = result[f"concept_rs{window}_previous_rank"] - result[f"concept_rs{window}_rank"]
    return result.sort_values(["trade_date", "concept_id"]).reset_index(drop=True)
