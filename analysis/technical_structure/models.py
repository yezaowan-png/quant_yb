"""Shared models for causal technical-chart structure analysis."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd


SUPPORTED_ASSET_TYPES = {"index", "stock", "fund", "other"}
SUPPORTED_TIMEFRAMES = {"1d", "1w", "1mo"}
SUPPORTED_ADJUSTMENTS = {"qfq", "hfq", "none"}


@dataclass
class OHLCVFrame:
    symbol: str
    asset_type: str
    timeframe: str
    adjustment: str
    data: pd.DataFrame
    metadata: dict[str, Any] = field(default_factory=dict)
    data_quality_flags: list[str] = field(default_factory=list)


@dataclass
class TechnicalStructureResult:
    symbol: str
    asset_type: str
    timeframe: str
    adjustment: str
    as_of_date: str
    bar_count: int
    pivots: list[dict[str, Any]] = field(default_factory=list)
    horizontal_levels: list[dict[str, Any]] = field(default_factory=list)
    trendlines: list[dict[str, Any]] = field(default_factory=list)
    channels: list[dict[str, Any]] = field(default_factory=list)
    current_context: dict[str, Any] = field(default_factory=dict)
    data_quality_flags: list[str] = field(default_factory=list)
    bars: list[dict[str, Any]] = field(default_factory=list)
    algorithm_version: str = "technical_structure_v1"
    cache_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TechnicalStructureResult":
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: value for key, value in payload.items() if key in allowed})

