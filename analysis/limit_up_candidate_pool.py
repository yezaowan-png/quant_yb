"""120 个真实交易日的涨停基础候选池服务。

本模块只维护原始涨停事件缓存与可解释候选统计；不写入主题池，也不
负责分类、报告或调度。交易日历或任一交易日明细不完整时，调用方会收到
``official=False`` 的结果，不能将其当作正式候选池使用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import json
import os
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from analysis.limit_moves import LIMIT_FIELDS, clean_limit_detail
from data.tushare_client import TushareClient, configured_tokens


EVENT_COLUMNS = LIMIT_FIELDS.split(",") + ["limit_type"]
CACHE_SCHEMA_VERSION = 2
CANDIDATE_COLUMNS = [
    "as_of_date",
    "ts_code",
    "stock_name",
    "industry",
    "market",
    "is_st",
    "is_beijing",
    "is_recent_ipo",
    "eligible_for_chatgpt_classification",
    "exclusion_reason",
    "latest_limit_up_date",
    "trading_days_since_latest",
    "limit_up_count_20d",
    "limit_up_count_60d",
    "limit_up_count_120d",
    "max_consecutive_limit_up",
    "latest_amount",
    "latest_turnover_ratio",
    "latest_limit_times",
    "latest_up_stat",
    "recent_limit_up_dates",
    "latest_limit_up_reason",
    "latest_concept_tags",
    "source",
    "updated_at",
]


@dataclass
class LimitUpCandidatePoolResult:
    """Candidate data plus completeness metadata for a future CLI/task."""

    candidates: pd.DataFrame
    events: pd.DataFrame
    status: dict[str, Any]
    cache_dir: Path
    official: bool
    errors: list[str] = field(default_factory=list)


def _yyyymmdd(value: str | date | datetime) -> str:
    return pd.Timestamp(value).strftime("%Y%m%d")


def _pool_config(config: dict) -> dict:
    return config.get("limit_up_candidate_pool", {}) or {}


def _cache_dir(config: dict, cache_dir: str | Path | None = None) -> Path:
    if cache_dir is not None:
        path = Path(cache_dir)
    else:
        cfg = _pool_config(config)
        configured = cfg.get("cache_dir")
        if configured:
            path = Path(configured)
        else:
            base = Path(config.get("data", {}).get("cache_dir", "data/cache"))
            path = base / cfg.get("cache_subdir", "limit_up_events")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _call_api(
    config: dict,
    symbol: str,
    api_name: str,
    callback: Callable[[Any], pd.DataFrame],
    pro: Any | None,
    client: TushareClient | None,
) -> pd.DataFrame:
    if pro is not None:
        return callback(pro)
    active_client = client or TushareClient.from_config(config)
    return active_client.call(symbol, api_name, callback)


def limit_data_client(config: dict) -> tuple[TushareClient, str, bool]:
    """Create the isolated client used only for ``limit_list_d`` requests.

    The account selection is deliberately not shared with quotes, calendars or
    RS.  Callers may log the returned label, never the token itself.
    """
    special = os.environ.get("TUSHARE_LIMIT_TOKEN")
    if special:
        return TushareClient([special]), "limit专用账号", True
    default = os.environ.get("TUSHARE_TOKEN")
    if default:
        return TushareClient([default]), "默认账号", True
    # Keep the limit source on one deterministic default account.  The general
    # client may rotate through configured tokens with different entitlements.
    return TushareClient([configured_tokens(config)[0]]), "默认账号", False


def probe_limit_list_permission(
    config: dict,
    trade_date: str | date | datetime,
) -> dict[str, Any]:
    """Perform one minimal, non-persistent permission check for limit_list_d."""
    day = _yyyymmdd(trade_date)
    account_label = "limit专用账号" if os.environ.get("TUSHARE_LIMIT_TOKEN") else "默认账号"
    token_from_environment = bool(os.environ.get("TUSHARE_LIMIT_TOKEN") or os.environ.get("TUSHARE_TOKEN"))
    try:
        _, account_label, token_from_environment = select_limit_data_client(config, day)
    except Exception as exc:
        return {"ok": False, "account": account_label, "token_from_environment": token_from_environment, "trade_date": day, "error_type": type(exc).__name__}
    return {"ok": True, "account": account_label, "token_from_environment": token_from_environment, "trade_date": day, "error_type": ""}


def select_limit_data_client(
    config: dict,
    trade_date: str | date | datetime,
) -> tuple[TushareClient, str, bool]:
    """Select one entitled limit-data account without exposing credentials.

    Environment tokens take precedence.  With project-configured tokens, each
    configured account is probed once and the first account granted access is
    pinned for the complete backfill instead of participating in normal token
    rotation.
    """
    day = _yyyymmdd(trade_date)
    special = os.environ.get("TUSHARE_LIMIT_TOKEN")
    default = os.environ.get("TUSHARE_TOKEN")
    candidates = [(special, "limit专用账号", True)] if special else [(default, "默认账号", True)] if default else [(token, "默认账号", False) for token in configured_tokens(config)]
    errors: list[str] = []
    for token, label, from_environment in candidates:
        client = TushareClient([str(token)])
        try:
            client.call(day, "limit_list_d", lambda api: api.limit_list_d(trade_date=day, fields="trade_date,ts_code"))
        except Exception as exc:
            errors.append(type(exc).__name__)
            continue
        return client, label, from_environment
    raise RuntimeError("limit_list_d 权限探测失败: " + "/".join(sorted(set(errors)) or ["unknown"]))


def _empty_events() -> pd.DataFrame:
    return pd.DataFrame(columns=EVENT_COLUMNS)


def _empty_candidates() -> pd.DataFrame:
    return pd.DataFrame(columns=CANDIDATE_COLUMNS)


def _string_value(value: Any) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()


def _normalise_limit_detail(raw: pd.DataFrame | None) -> pd.DataFrame:
    """Make a partial API/mock response safe for the shared detail cleaner."""

    if raw is None or raw.empty:
        return _empty_events()
    # The shared cleaner needs its sort columns, but ``limit_type`` must stay
    # absent when the provider uses ``limit`` so it can derive U/Z correctly.
    prepared = raw.copy()
    for column in LIMIT_FIELDS.split(","):
        if column not in prepared.columns:
            prepared[column] = pd.NA
    detail = clean_limit_detail(prepared)
    for column in EVENT_COLUMNS:
        if column not in detail.columns:
            detail[column] = pd.NA
    return detail


def _read_event_cache(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        cached = pd.read_csv(path, dtype={"trade_date": str, "ts_code": str})
    except (OSError, pd.errors.EmptyDataError, ValueError):
        return None
    if "cache_schema_version" not in cached.columns or not cached["cache_schema_version"].eq(CACHE_SCHEMA_VERSION).all():
        return None
    return _normalise_limit_detail(cached)


def _write_event_cache(path: Path, detail: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    output = detail.copy()
    for column in EVENT_COLUMNS:
        if column not in output.columns:
            output[column] = pd.NA
    output["cache_schema_version"] = CACHE_SCHEMA_VERSION
    output[EVENT_COLUMNS + ["cache_schema_version"]].to_csv(path, index=False)


def fetch_recent_trade_dates(
    config: dict,
    as_of_date: str | date | datetime | None = None,
    pro: Any | None = None,
    client: TushareClient | None = None,
) -> list[str]:
    """Return the latest configured number of actual SSE open dates.

    Unlike older research helpers, this function never falls back to business
    days. Callers must treat any exception or insufficient calendar as invalid.
    """

    cfg = _pool_config(config)
    lookback = int(cfg.get("lookback_trade_days", 120))
    end = _yyyymmdd(as_of_date or date.today())
    # 120 sessions need about six calendar months; leave generous room for long
    # holidays while keeping the API query bounded.
    start = _yyyymmdd(pd.Timestamp(end) - pd.Timedelta(days=max(lookback * 4, 400)))
    exchange = str(cfg.get("trade_calendar_exchange", "SSE"))
    raw = _call_api(
        config,
        "trade_cal",
        "trade_cal",
        lambda api: api.trade_cal(
            exchange=exchange,
            start_date=start,
            end_date=end,
            is_open="1",
            fields="cal_date,is_open",
        ),
        pro,
        client,
    )
    if raw is None or raw.empty or "cal_date" not in raw.columns:
        raise RuntimeError("Tushare trade_cal 未返回有效开市日，不能生成正式候选池")
    calendar = sorted({_yyyymmdd(value) for value in raw["cal_date"].dropna()})
    if len(calendar) < lookback:
        raise RuntimeError(f"交易日历仅返回 {len(calendar)}/{lookback} 个开市日，不能生成正式候选池")
    return calendar[-lookback:]


def _fetch_one_day(
    config: dict,
    trade_date: str,
    cache_dir: Path,
    pro: Any | None,
    client: TushareClient | None,
) -> tuple[pd.DataFrame, bool]:
    path = cache_dir / f"{trade_date}.csv"
    cached = _read_event_cache(path)
    if cached is not None:
        return cached, True
    raw = _call_api(
        config,
        trade_date,
        "limit_list_d",
        lambda api: api.limit_list_d(trade_date=trade_date, fields=LIMIT_FIELDS),
        pro,
        client,
    )
    detail = _normalise_limit_detail(raw)
    detail["trade_date"] = trade_date
    detail["limit_type"] = detail["limit_type"].astype(str).str.upper()
    # Keep U/Z for subsequent explainability. D is not part of this candidate pool.
    detail = detail[detail["limit_type"].isin(["U", "Z"])].copy()
    _write_event_cache(path, detail)
    return detail, False


def load_limit_up_events(
    config: dict,
    trade_dates: list[str],
    pro: Any | None = None,
    client: TushareClient | None = None,
    cache_dir: str | Path | None = None,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Load one cached or remote event file per expected trade date.

    The returned missing list contains dates whose API call failed. An empty
    successful response is a valid, cached trading-day result rather than a
    missing date.
    """

    resolved_cache_dir = _cache_dir(config, cache_dir)
    frames: list[pd.DataFrame] = []
    loaded_dates: list[str] = []
    missing_dates: list[str] = []
    active_client = client
    for trade_date in trade_dates:
        try:
            if pro is None and active_client is None:
                active_client = TushareClient.from_config(config)
            detail, _ = _fetch_one_day(config, trade_date, resolved_cache_dir, pro, active_client)
        except Exception as exc:
            missing_dates.append(trade_date)
            # Account permissions cannot be fixed by trying every remaining
            # date. Stop immediately and leave the previous official output.
            message = str(exc)
            if "访问权限" in message or "没有接口" in message:
                missing_dates.extend(day for day in trade_dates if day not in loaded_dates and day not in missing_dates)
                break
            continue
        loaded_dates.append(trade_date)
        if not detail.empty:
            frames.append(detail)
    if not frames:
        return _empty_events(), loaded_dates, missing_dates
    events = pd.concat(frames, ignore_index=True)
    events["trade_date"] = events["trade_date"].map(_yyyymmdd)
    events["ts_code"] = events["ts_code"].astype(str).str.upper()
    events["limit_type"] = events["limit_type"].astype(str).str.upper()
    events = events.drop_duplicates(subset=["trade_date", "ts_code", "limit_type"], keep="last")
    return events.sort_values(["trade_date", "ts_code", "limit_type"]).reset_index(drop=True), loaded_dates, missing_dates


def _metadata_index(stock_metadata: pd.DataFrame | None) -> pd.DataFrame:
    if stock_metadata is None or stock_metadata.empty or "ts_code" not in stock_metadata.columns:
        return pd.DataFrame()
    metadata = stock_metadata.copy()
    metadata["ts_code"] = metadata["ts_code"].astype(str).str.upper()
    return metadata.drop_duplicates("ts_code", keep="last").set_index("ts_code", drop=False)


def _market(symbol: str) -> str:
    parts = str(symbol).upper().split(".")
    return parts[-1] if len(parts) == 2 else ""


def _is_st(name: Any, metadata: pd.Series | None) -> bool:
    if metadata is not None and "is_st" in metadata.index and pd.notna(metadata["is_st"]):
        value = metadata["is_st"]
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y"}
        return bool(value)
    return str(name or "").strip().upper().startswith(("ST", "*ST"))


def _recent_ipo(
    metadata: pd.Series | None,
    trade_dates: list[str],
    threshold: int,
) -> bool:
    if metadata is None or "list_date" not in metadata.index or pd.isna(metadata["list_date"]):
        return False
    try:
        list_date = _yyyymmdd(metadata["list_date"])
    except (TypeError, ValueError):
        return False
    listed_sessions = sum(day >= list_date for day in trade_dates)
    return listed_sessions < threshold


def _latest_text(group: pd.DataFrame, columns: tuple[str, ...]) -> str | None:
    latest = group.iloc[-1]
    for column in columns:
        value = latest.get(column)
        if pd.notna(value) and str(value).strip():
            return str(value).strip()
    return None


def _max_consecutive_limit_up(up_dates: list[str], trade_dates: list[str]) -> int:
    positions = {day: index for index, day in enumerate(trade_dates)}
    streak = maximum = 0
    previous: int | None = None
    for day in sorted(set(up_dates)):
        position = positions.get(day)
        if position is None:
            continue
        streak = streak + 1 if previous is not None and position == previous + 1 else 1
        maximum = max(maximum, streak)
        previous = position
    return maximum


def build_candidate_statistics(
    events: pd.DataFrame,
    trade_dates: list[str],
    config: dict,
    stock_metadata: pd.DataFrame | None = None,
    updated_at: datetime | None = None,
) -> pd.DataFrame:
    """Create one row per stock from U events while retaining U/Z event cache."""

    if events.empty:
        return _empty_candidates()
    up = events[events["limit_type"].astype(str).str.upper() == "U"].copy()
    if up.empty:
        return _empty_candidates()
    up["trade_date"] = up["trade_date"].map(_yyyymmdd)
    up["ts_code"] = up["ts_code"].astype(str).str.upper()
    metadata = _metadata_index(stock_metadata)
    cfg = _pool_config(config)
    recent_dates_count = int(cfg.get("recent_limit_up_dates_count", 5))
    recent_ipo_days = int(cfg.get("recent_ipo_trade_days", 20))
    exclude_st = bool(cfg.get("exclude_st", True))
    exclude_beijing = bool(cfg.get("exclude_beijing", True))
    exclude_recent_ipo = bool(cfg.get("exclude_recent_ipo", True))
    as_of_date = trade_dates[-1]
    now = (updated_at or datetime.now()).isoformat(timespec="seconds")
    last_20 = set(trade_dates[-20:])
    last_60 = set(trade_dates[-60:])
    date_positions = {day: index for index, day in enumerate(trade_dates)}
    rows: list[dict[str, Any]] = []

    for symbol, group in up.groupby("ts_code", sort=False):
        group = group.sort_values("trade_date").drop_duplicates(["trade_date", "ts_code"], keep="last")
        latest = group.iloc[-1]
        meta = metadata.loc[symbol] if not metadata.empty and symbol in metadata.index else None
        stock_name = _string_value(latest.get("name")) or _string_value(meta.get("name") if meta is not None else None)
        industry = _string_value(latest.get("industry")) or _string_value(meta.get("industry") if meta is not None else None)
        market = _market(symbol)
        is_beijing = market == "BJ"
        is_st = _is_st(stock_name, meta)
        is_recent_ipo = _recent_ipo(meta, trade_dates, recent_ipo_days)
        exclusions: list[str] = []
        if exclude_st and is_st:
            exclusions.append("ST/*ST")
        if exclude_beijing and is_beijing:
            exclusions.append("北交所")
        if exclude_recent_ipo and is_recent_ipo:
            exclusions.append(f"上市未满{recent_ipo_days}个交易日")
        up_dates = group["trade_date"].tolist()
        latest_date = up_dates[-1]
        rows.append(
            {
                "as_of_date": as_of_date,
                "ts_code": symbol,
                "stock_name": stock_name,
                "industry": industry,
                "market": market,
                "is_st": bool(is_st),
                "is_beijing": bool(is_beijing),
                "is_recent_ipo": bool(is_recent_ipo),
                "eligible_for_chatgpt_classification": not exclusions,
                "exclusion_reason": ";".join(exclusions),
                "latest_limit_up_date": latest_date,
                "trading_days_since_latest": date_positions[as_of_date] - date_positions[latest_date],
                "limit_up_count_20d": sum(day in last_20 for day in up_dates),
                "limit_up_count_60d": sum(day in last_60 for day in up_dates),
                "limit_up_count_120d": len(up_dates),
                "max_consecutive_limit_up": _max_consecutive_limit_up(up_dates, trade_dates),
                "latest_amount": pd.to_numeric(latest.get("amount"), errors="coerce"),
                "latest_turnover_ratio": pd.to_numeric(latest.get("turnover_ratio"), errors="coerce"),
                "latest_limit_times": pd.to_numeric(latest.get("limit_times"), errors="coerce"),
                "latest_up_stat": _latest_text(group, ("up_stat",)),
                "recent_limit_up_dates": ",".join(up_dates[-recent_dates_count:]),
                "latest_limit_up_reason": _latest_text(group, ("limit_up_reason", "reason", "reason_detail")),
                "latest_concept_tags": _latest_text(group, ("concept_tags", "concept", "concept_name")),
                "source": "tushare.limit_list_d",
                "updated_at": now,
            }
        )
    result = pd.DataFrame(rows, columns=CANDIDATE_COLUMNS)
    return result.sort_values(
        ["limit_up_count_120d", "latest_limit_up_date", "ts_code"], ascending=[False, False, True]
    ).reset_index(drop=True)


def build_limit_up_candidate_pool(
    config: dict,
    as_of_date: str | date | datetime | None = None,
    pro: Any | None = None,
    client: TushareClient | None = None,
    stock_metadata: pd.DataFrame | None = None,
    cache_dir: str | Path | None = None,
) -> LimitUpCandidatePoolResult:
    """Build a complete 120-trading-day candidate pool or return incomplete state.

    ``pro`` and ``client`` are dependency-injection points for tests and callers.
    The function deliberately does not write a ``latest`` CSV: a future CLI can
    write one only after checking ``result.official``.
    """

    resolved_cache_dir = _cache_dir(config, cache_dir)
    lookback = int(_pool_config(config).get("lookback_trade_days", 120))
    try:
        trade_dates = fetch_recent_trade_dates(config, as_of_date, pro=pro, client=client)
    except Exception as exc:
        status = {
            "status": "incomplete",
            "official": False,
            "as_of_date": None,
            "window_start_date": None,
            "window_end_date": None,
            "expected_trade_days": lookback,
            "loaded_trade_days": 0,
            "missing_trade_days": [],
        }
        return LimitUpCandidatePoolResult(_empty_candidates(), _empty_events(), status, resolved_cache_dir, False, [str(exc)])

    limit_client = client
    needs_limit_fetch = any(_read_event_cache(resolved_cache_dir / f"{trade_date}.csv") is None for trade_date in trade_dates)
    if pro is None and limit_client is None and needs_limit_fetch:
        limit_client, _, _ = select_limit_data_client(config, "20260703")
    events, loaded_dates, missing_dates = load_limit_up_events(
        config, trade_dates, pro=pro, client=limit_client, cache_dir=resolved_cache_dir
    )
    status = {
        "status": "complete" if not missing_dates else "incomplete",
        "official": not missing_dates,
        "as_of_date": trade_dates[-1],
        "window_start_date": trade_dates[0],
        "window_end_date": trade_dates[-1],
        "expected_trade_days": len(trade_dates),
        "loaded_trade_days": len(loaded_dates),
        "missing_trade_days": missing_dates,
        "limit_up_event_count": int((events["limit_type"] == "U").sum()) if not events.empty else 0,
        "opened_event_count": int((events["limit_type"] == "Z").sum()) if not events.empty else 0,
    }
    if missing_dates:
        return LimitUpCandidatePoolResult(
            _empty_candidates(), events, status, resolved_cache_dir, False, [f"缺少 {len(missing_dates)} 个交易日的 limit_list_d 明细"]
        )
    candidates = build_candidate_statistics(events, trade_dates, config, stock_metadata=stock_metadata)
    return LimitUpCandidatePoolResult(candidates, events, status, resolved_cache_dir, True)


def save_limit_up_candidate_pool(
    result: LimitUpCandidatePoolResult,
    output_dir: str | Path,
    candidate_filename: str = "limit_up_candidates_latest.csv",
    status_filename: str = "limit_up_candidates_status.json",
) -> dict[str, Path]:
    """Persist an official candidate snapshot and its completeness status.

    Refusing incomplete results is intentional: scheduled callers can leave the
    previous complete snapshot intact while surfacing ``result.status`` as a
    warning. This function never touches ``stock_pools.json``.
    """

    if not result.official:
        raise ValueError("涨停数据不完整，拒绝覆盖正式候选池输出")
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    candidate_path = directory / candidate_filename
    status_path = directory / status_filename
    result.candidates.to_csv(candidate_path, index=False)
    status_path.write_text(json.dumps(result.status, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"candidates_path": candidate_path, "status_path": status_path}
