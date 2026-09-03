"""Industry sector money-flow collection and replay helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from project_config import PROJECT_ROOT


DEFAULT_SECTOR_NAMES = [
    "半导体",
    "电池",
    "白酒",
    "化学制药",
    "能源金属",
    "通信设备",
    "汽车零部件",
    "软件开发",
    "消费电子",
    "银行",
]

ARCHIVE_DIR_PREFIX = "data_"
ARCHIVE_FILE_PREFIX = "板块数据_"
ARCHIVE_TIME_FORMAT = "%Y-%m-%d_%H-%M"


@dataclass(frozen=True)
class SectorMoneyFlowConfig:
    sector_names: list[str]
    interval_seconds: int
    data_dir: Path
    history_replay_enabled: bool
    report_auto_refresh: bool


@dataclass
class SectorMoneyFlowState:
    sector_names: list[str]
    timestamps: list[datetime]
    history_data: dict[str, list[float | None]]
    current_idx: int
    max_data_idx: int
    is_replay_mode: bool
    archive_dir: Path


def sector_money_flow_config(config: dict[str, Any]) -> SectorMoneyFlowConfig:
    raw = config.get("sector_money_flow") or {}
    sectors = raw.get("sector_names") or raw.get("sectors") or DEFAULT_SECTOR_NAMES
    sector_names = [str(item).strip() for item in sectors if str(item).strip()]
    if not sector_names:
        sector_names = list(DEFAULT_SECTOR_NAMES)

    interval = int(raw.get("interval_seconds") or raw.get("collect_interval_seconds") or 60)
    interval = max(5, interval)

    raw_dir = Path(str(raw.get("data_dir") or "data/sector_money_flow")).expanduser()
    data_dir = raw_dir if raw_dir.is_absolute() else PROJECT_ROOT / raw_dir

    return SectorMoneyFlowConfig(
        sector_names=sector_names,
        interval_seconds=interval,
        data_dir=data_dir,
        history_replay_enabled=bool(raw.get("history_replay_enabled", True)),
        report_auto_refresh=bool(raw.get("report_auto_refresh", True)),
    )


def is_trading_hour(dt: datetime) -> bool:
    """Return whether *dt* is inside the A-share continuous auction sessions."""
    time_value = dt.hour + dt.minute / 60
    return (9.5 <= time_value <= 11.5) or (13.0 <= time_value <= 15.0)


def generate_trading_timeline(start_time: datetime, end_time: datetime) -> list[datetime]:
    """Generate a minute-level timeline, skipping the midday break."""
    timestamps: list[datetime] = []
    current = start_time.replace(second=0, microsecond=0)
    while current <= end_time:
        if is_trading_hour(current):
            timestamps.append(current)
        current += timedelta(minutes=1)
    return timestamps


def archive_day_dir(data_dir: Path, trade_date: date | datetime | str | None = None) -> Path:
    day = _normalize_trade_date(trade_date or datetime.now())
    return data_dir / f"{ARCHIVE_DIR_PREFIX}{day:%Y-%m-%d}"


def archive_file_path(data_dir: Path, dt: datetime) -> Path:
    return archive_day_dir(data_dir, dt) / f"{ARCHIVE_FILE_PREFIX}{dt.strftime(ARCHIVE_TIME_FORMAT)}.csv"


def collect_real_sector_frame(
    settings: SectorMoneyFlowConfig,
    *,
    now: datetime | None = None,
    fetcher: Callable[[], pd.DataFrame] | None = None,
) -> tuple[pd.DataFrame, Path]:
    """Fetch the full AkShare industry money-flow frame and archive it as CSV."""
    current = (now or datetime.now()).replace(second=0, microsecond=0)
    if fetcher is None:
        try:
            import akshare as ak
        except ImportError as exc:
            raise RuntimeError("缺少 akshare 依赖，请先安装 requirements.txt") from exc

        fetcher = lambda: ak.stock_fund_flow_industry(symbol="即时")

    frame = fetcher()
    if frame is None or frame.empty:
        raise RuntimeError("AkShare 行业资金流数据为空")
    if "行业" not in frame.columns or "净额" not in frame.columns:
        raise RuntimeError("AkShare 行业资金流数据缺少必需字段: 行业/净额")

    target = archive_file_path(settings.data_dir, current)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(target, encoding="utf-8-sig", index=False)
    return frame, target


def extract_sector_net_amounts(frame: pd.DataFrame, sector_names: list[str]) -> dict[str, float | None]:
    """Extract configured sector net amounts from an AkShare/archive frame."""
    if frame is None or frame.empty or "行业" not in frame.columns or "净额" not in frame.columns:
        return {sector: None for sector in sector_names}
    work = frame.copy()
    work["行业"] = work["行业"].astype(str).str.strip()
    values: dict[str, float | None] = {}
    for sector in sector_names:
        rows = work.loc[work["行业"] == sector, "净额"]
        values[sector] = _to_float(rows.iloc[0]) if not rows.empty else None
    return values


def load_local_history_data(
    settings: SectorMoneyFlowConfig,
    *,
    trade_date: date | datetime | str | None = None,
) -> SectorMoneyFlowState | None:
    """Load archived CSV files for a trading day into replay-ready state."""
    data_dir = archive_day_dir(settings.data_dir, trade_date)
    csv_files = sorted(data_dir.glob(f"{ARCHIVE_FILE_PREFIX}*.csv"))
    if not csv_files:
        return None

    parsed_files: list[tuple[datetime, Path]] = []
    for path in csv_files:
        parsed = _parse_archive_time(path)
        if parsed is not None:
            parsed_files.append((parsed, path))
    if not parsed_files:
        return None

    first_time = parsed_files[0][0].replace(second=0, microsecond=0)
    end_time = first_time.replace(hour=15, minute=0, second=0, microsecond=0)
    timestamps = generate_trading_timeline(first_time, end_time)
    if not timestamps:
        return None

    history_data = {sector: [None] * len(timestamps) for sector in settings.sector_names}
    max_data_idx = 0
    for file_time, path in parsed_files:
        if not is_trading_hour(file_time):
            continue
        try:
            frame = pd.read_csv(path, encoding="utf-8-sig")
        except Exception:
            continue
        idx = _nearest_timestamp_index(timestamps, file_time)
        values = extract_sector_net_amounts(frame, settings.sector_names)
        for sector in settings.sector_names:
            value = values.get(sector)
            if value is not None and value != 0:
                history_data[sector][idx] = value
            else:
                history_data[sector][idx] = _last_valid(history_data[sector], idx)
        max_data_idx = max(max_data_idx, idx)

    return SectorMoneyFlowState(
        sector_names=list(settings.sector_names),
        timestamps=timestamps,
        history_data=history_data,
        current_idx=0,
        max_data_idx=max_data_idx,
        is_replay_mode=True,
        archive_dir=data_dir,
    )


def init_sector_money_flow_state(
    settings: SectorMoneyFlowConfig,
    *,
    now: datetime | None = None,
    trade_date: date | datetime | str | None = None,
) -> SectorMoneyFlowState:
    """Initialize replay mode from local CSVs, otherwise prepare realtime state."""
    current = now or datetime.now()
    if settings.history_replay_enabled:
        history = load_local_history_data(settings, trade_date=trade_date or current)
        if history is not None:
            return history

    start_time = current.replace(second=0, microsecond=0)
    if current.hour >= 15:
        start_time = (current + timedelta(days=1)).replace(hour=9, minute=30, second=0, microsecond=0)
    end_time = start_time.replace(hour=15, minute=0, second=0, microsecond=0)
    timestamps = generate_trading_timeline(start_time, end_time)
    return SectorMoneyFlowState(
        sector_names=list(settings.sector_names),
        timestamps=timestamps,
        history_data={sector: [None] * len(timestamps) for sector in settings.sector_names},
        current_idx=0,
        max_data_idx=0,
        is_replay_mode=False,
        archive_dir=archive_day_dir(settings.data_dir, start_time),
    )


def add_new_data_point(
    settings: SectorMoneyFlowConfig,
    state: SectorMoneyFlowState,
    *,
    now: datetime | None = None,
    fetcher: Callable[[], pd.DataFrame] | None = None,
) -> tuple[bool, str, Path | None]:
    """Collect and merge one realtime data point into state."""
    current = now or datetime.now()
    if not is_trading_hour(current):
        return False, f"非交易时段，跳过采集: {current:%H:%M}", None
    if not state.timestamps:
        return False, "当前交易时间轴为空，跳过采集", None

    frame, path = collect_real_sector_frame(settings, now=current, fetcher=fetcher)
    idx = _nearest_timestamp_index(state.timestamps, current)
    values = extract_sector_net_amounts(frame, state.sector_names)
    for sector in state.sector_names:
        value = values.get(sector)
        if value is not None and value != 0:
            state.history_data[sector][idx] = value
        else:
            state.history_data[sector][idx] = _last_valid(state.history_data[sector], idx)
    state.max_data_idx = max(state.max_data_idx, idx)
    return True, f"已采集 {current:%H:%M} 行业资金流", path


def latest_sector_ranking(state: SectorMoneyFlowState, upto_idx: int | None = None) -> list[dict[str, Any]]:
    idx_limit = state.max_data_idx if upto_idx is None else min(upto_idx, state.max_data_idx)
    ranking = []
    for sector in state.sector_names:
        values = state.history_data.get(sector, [])
        latest = _last_valid(values, idx_limit + 1)
        ranking.append({"sector": sector, "value": latest if latest is not None else 0.0})
    return sorted(ranking, key=lambda item: float(item["value"]), reverse=True)


def state_to_payload(
    state: SectorMoneyFlowState,
    settings: SectorMoneyFlowConfig,
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    current = generated_at or datetime.now()
    data_indices = [
        idx
        for idx in range(len(state.timestamps))
        if any(
            values[idx] is not None
            for values in state.history_data.values()
            if idx < len(values)
        )
    ]
    snapshot_series = {
        sector: [
            values[idx] if idx < len(values) else None
            for idx in data_indices
        ]
        for sector, values in state.history_data.items()
    }
    return {
        "generated_at": current.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "history_replay" if state.is_replay_mode else "realtime",
        "sector_names": state.sector_names,
        "timestamps": [item.strftime("%H:%M") for item in state.timestamps],
        "series": state.history_data,
        "data_indices": data_indices,
        "data_point_count": len(data_indices),
        "snapshot_timestamps": [state.timestamps[idx].strftime("%H:%M") for idx in data_indices],
        "snapshot_series": snapshot_series,
        "current_idx": state.current_idx,
        "max_data_idx": state.max_data_idx,
        "ranking": latest_sector_ranking(state),
        "archive_dir": str(state.archive_dir),
        "interval_seconds": settings.interval_seconds,
        "history_replay_enabled": settings.history_replay_enabled,
        "report_auto_refresh": settings.report_auto_refresh,
    }


def _normalize_trade_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def _parse_archive_time(path: Path) -> datetime | None:
    stem = path.stem
    if not stem.startswith(ARCHIVE_FILE_PREFIX):
        return None
    text = stem[len(ARCHIVE_FILE_PREFIX):]
    try:
        return datetime.strptime(text, ARCHIVE_TIME_FORMAT)
    except ValueError:
        return None


def _nearest_timestamp_index(timestamps: list[datetime], value: datetime) -> int:
    return min(range(len(timestamps)), key=lambda idx: abs((timestamps[idx] - value).total_seconds()))


def _last_valid(values: list[float | None], before_idx: int) -> float | None:
    for idx in range(min(before_idx, len(values)) - 1, -1, -1):
        if values[idx] is not None:
            return values[idx]
    return None


def _to_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", "")
        if not value or value.lower() == "nan":
            return None
        value = value.rstrip("亿")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
