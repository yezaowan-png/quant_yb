"""Limit-up database based strong-stock scoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from project_config import PROJECT_ROOT


DETAIL_PREFIX = "每日涨停个股明细-"
DETAIL_SUFFIX = ".csv"
DEFAULT_FOCUS_THEMES = ["机器人", "AI", "半导体", "芯片", "创新药", "华为", "算力", "低空经济", "军工", "储能"]
DEFAULT_OUTPUT_COLUMNS = [
    "股票名称",
    "股票代码",
    "所属行业",
    "涨停题材",
    "近期涨停数",
    "综合评分",
    "均线多头分",
    "突破前高分",
    "动量分",
    "成交量分",
    "所属题材",
    "新增/剔除状态",
]


@dataclass(frozen=True)
class LimitStrengthConfig:
    data_path: Path
    back_days: int
    min_limit_count: int
    output_dir: Path
    exclude_name_keywords: tuple[str, ...]
    exclude_code_prefixes: tuple[str, ...]
    focus_themes: tuple[str, ...]
    ma_windows: tuple[int, int, int, int]
    continue_days: int
    enlarge_times: float
    weights: dict[str, float]
    history_days: int
    adjust: str
    output_filename: str


@dataclass
class LimitStrengthResult:
    result_path: Path
    changes_path: Path
    latest_path: Path
    html_path: Path
    loaded_dates: list[str]
    records: pd.DataFrame
    candidates: pd.DataFrame
    result: pd.DataFrame
    changes: pd.DataFrame


def limit_strength_config(config: dict[str, Any]) -> LimitStrengthConfig:
    raw = config.get("limit_strength") or {}
    output_raw = raw.get("output_dir") or Path(config.get("output", {}).get("statistics_dir", "output/statistics")) / "limit_strength"
    raw_themes = raw.get("focus_themes", DEFAULT_FOCUS_THEMES)
    if raw_themes is None:
        raw_themes = DEFAULT_FOCUS_THEMES

    return LimitStrengthConfig(
        data_path=_resolve_path(raw.get("data_path") or "data/limit_up_database"),
        back_days=max(1, int(raw.get("back_days") or 10)),
        min_limit_count=max(1, int(raw.get("min_limit_count") or 2)),
        output_dir=_resolve_path(output_raw),
        exclude_name_keywords=tuple(raw.get("exclude_name_keywords") or ("ST",)),
        exclude_code_prefixes=tuple(str(item) for item in (raw.get("exclude_code_prefixes") or ("83", "87", "920"))),
        focus_themes=tuple(str(item) for item in raw_themes),
        ma_windows=tuple(int(item) for item in (raw.get("ma_windows") or (20, 30, 60, 120))),  # type: ignore[arg-type]
        continue_days=max(1, int(raw.get("continue_days") or 3)),
        enlarge_times=float(raw.get("enlarge_times") or 1.2),
        weights={
            "ma": float((raw.get("weights") or {}).get("ma", 0.35)),
            "breakout": float((raw.get("weights") or {}).get("breakout", 0.20)),
            "momentum": float((raw.get("weights") or {}).get("momentum", 0.25)),
            "volume": float((raw.get("weights") or {}).get("volume", 0.20)),
        },
        history_days=max(260, int(raw.get("history_days") or 365)),
        adjust=str(raw.get("adjust") or "qfq"),
        output_filename=str(raw.get("output_filename") or "每日强势股结果.csv"),
    )


def discover_limit_dates(data_path: Path) -> list[str]:
    if not data_path.exists():
        return []
    dates = []
    for path in data_path.iterdir():
        name = path.name
        if name.startswith(DETAIL_PREFIX) and name.endswith(DETAIL_SUFFIX):
            value = name[len(DETAIL_PREFIX):-len(DETAIL_SUFFIX)]
            if len(value) == 8 and value.isdigit():
                dates.append(value)
    return sorted(set(dates), reverse=True)


def load_limit_records(settings: LimitStrengthConfig) -> tuple[pd.DataFrame, list[str]]:
    dates = discover_limit_dates(settings.data_path)[: settings.back_days]
    frames: list[pd.DataFrame] = []
    loaded_dates: list[str] = []
    for trade_date in dates:
        path = settings.data_path / f"{DETAIL_PREFIX}{trade_date}{DETAIL_SUFFIX}"
        try:
            frame = _read_limit_csv(path)
        except Exception:
            continue
        if frame.empty:
            continue
        frame = _normalize_limit_frame(frame, trade_date)
        frame = _filter_limit_frame(frame, settings)
        if frame.empty:
            continue
        frames.append(frame)
        loaded_dates.append(trade_date)
    if not frames:
        return pd.DataFrame(columns=["股票名称", "股票代码", "所属行业", "涨停题材", "日期"]), loaded_dates
    records = pd.concat(frames, ignore_index=True).sort_values("日期", ascending=False).reset_index(drop=True)
    return records, loaded_dates


def build_limit_candidates(records: pd.DataFrame, min_limit_count: int) -> pd.DataFrame:
    if records.empty:
        return pd.DataFrame(columns=["股票名称", "股票代码", "所属行业", "涨停题材", "日期", "近期涨停数"])
    counts = records["股票代码"].value_counts().rename("近期涨停数").reset_index()
    counts.columns = ["股票代码", "近期涨停数"]
    latest = records.sort_values("日期", ascending=False).drop_duplicates("股票代码", keep="first")
    candidates = latest.merge(counts, on="股票代码", how="left")
    return candidates[candidates["近期涨停数"] >= int(min_limit_count)].reset_index(drop=True)


def score_daily_frame(frame: pd.DataFrame, settings: LimitStrengthConfig) -> dict[str, float]:
    data = _normalize_daily_frame(frame)
    if data.empty:
        return _zero_scores()
    close = pd.to_numeric(data["close"], errors="coerce")
    high = pd.to_numeric(data["high"], errors="coerce")
    volume = pd.to_numeric(data["volume"], errors="coerce")
    ma_score = _ma_score(close, settings)
    breakout_score = _breakout_score(close, high)
    momentum_score = _momentum_score(close)
    volume_score = _volume_score(volume)
    total = (
        ma_score * settings.weights["ma"]
        + breakout_score * settings.weights["breakout"]
        + momentum_score * settings.weights["momentum"]
        + volume_score * settings.weights["volume"]
    )
    return {
        "综合评分": round(float(total), 2),
        "均线多头分": round(float(ma_score), 2),
        "突破前高分": round(float(breakout_score), 2),
        "动量分": round(float(momentum_score), 2),
        "成交量分": round(float(volume_score), 2),
    }


def build_limit_strength(
    config: dict[str, Any],
    *,
    price_fetcher: Callable[[str, LimitStrengthConfig, str | None], pd.DataFrame] | None = None,
) -> LimitStrengthResult:
    settings = limit_strength_config(config)
    records, loaded_dates = load_limit_records(settings)
    candidates = build_limit_candidates(records, settings.min_limit_count)
    as_of = loaded_dates[0] if loaded_dates else None
    scored = _score_candidates(candidates, settings, price_fetcher=price_fetcher, as_of=as_of)
    filtered = _filter_focus_themes(scored, settings.focus_themes)
    previous = _read_previous_result(settings.output_dir / settings.output_filename)
    final, changes = _attach_change_status(filtered, previous)
    paths = _save_outputs(settings, final, changes, loaded_dates)
    return LimitStrengthResult(
        result_path=paths["result"],
        changes_path=paths["changes"],
        latest_path=paths["latest"],
        html_path=paths["html"],
        loaded_dates=loaded_dates,
        records=records,
        candidates=candidates,
        result=final,
        changes=changes,
    )


def _score_candidates(
    candidates: pd.DataFrame,
    settings: LimitStrengthConfig,
    *,
    price_fetcher: Callable[[str, LimitStrengthConfig, str | None], pd.DataFrame] | None,
    as_of: str | None,
) -> pd.DataFrame:
    if candidates.empty:
        return candidates.assign(综合评分=[], 均线多头分=[], 突破前高分=[], 动量分=[], 成交量分=[])
    rows = []
    fetcher = price_fetcher or _fetch_akshare_daily
    for _, row in candidates.iterrows():
        symbol = str(row.get("股票代码", "")).strip().upper()
        try:
            scores = score_daily_frame(fetcher(symbol, settings, as_of), settings)
        except Exception:
            scores = _zero_scores()
        item = row.to_dict()
        item.update(scores)
        rows.append(item)
    return pd.DataFrame(rows).sort_values("综合评分", ascending=False).reset_index(drop=True)


def _filter_focus_themes(frame: pd.DataFrame, themes: tuple[str, ...]) -> pd.DataFrame:
    if frame.empty:
        result = frame.copy()
        result["所属题材"] = []
        return result
    if not themes:
        result = frame.copy()
        result["所属题材"] = ""
        return result
    rows = []
    for _, row in frame.iterrows():
        text = str(row.get("涨停题材", "") or "")
        matched = [theme for theme in themes if theme and theme in text]
        if matched:
            item = row.to_dict()
            item["所属题材"] = "、".join(matched)
            rows.append(item)
    if not rows:
        return pd.DataFrame(columns=[*frame.columns, "所属题材"])
    return pd.DataFrame(rows).drop_duplicates("股票代码", keep="first").reset_index(drop=True)


def _attach_change_status(current: pd.DataFrame, previous: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    current = current.copy()
    old_codes = set(previous.get("股票代码", pd.Series(dtype=str)).astype(str)) if not previous.empty else set()
    current_codes = set(current.get("股票代码", pd.Series(dtype=str)).astype(str)) if not current.empty else set()
    if current.empty:
        for column in DEFAULT_OUTPUT_COLUMNS:
            if column not in current.columns:
                current[column] = []
    current["新增/剔除状态"] = ["新增" if str(code) not in old_codes else "保留" for code in current.get("股票代码", [])]
    removed = previous[previous["股票代码"].astype(str).isin(old_codes - current_codes)].copy() if not previous.empty else pd.DataFrame()
    if not removed.empty:
        removed["新增/剔除状态"] = "剔除"
    changes = pd.concat([current[current["新增/剔除状态"] == "新增"], removed], ignore_index=True)
    return _ensure_output_columns(current), _ensure_output_columns(changes)


def _save_outputs(settings: LimitStrengthConfig, result: pd.DataFrame, changes: pd.DataFrame, loaded_dates: list[str]) -> dict[str, Path]:
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    latest_date = loaded_dates[0] if loaded_dates else datetime.now().strftime("%Y%m%d")
    result_path = settings.output_dir / f"limit_strength_{latest_date}.csv"
    changes_path = settings.output_dir / f"limit_strength_{latest_date}_changes.csv"
    latest_path = settings.output_dir / settings.output_filename
    html_path = settings.output_dir / f"limit_strength_{latest_date}.html"
    for path, frame in ((result_path, result), (latest_path, result), (changes_path, changes)):
        frame.to_csv(path, index=False, encoding="utf-8-sig")
    _write_html_report(result, changes, html_path, latest_date, loaded_dates)
    return {"result": result_path, "changes": changes_path, "latest": latest_path, "html": html_path}


def _read_limit_csv(path: Path) -> pd.DataFrame:
    for encoding in ("GBK", "utf-8-sig", "utf-8"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path)


def _normalize_limit_frame(frame: pd.DataFrame, trade_date: str) -> pd.DataFrame:
    required = {
        "股票名称": _pick_column(frame, ("股票名称", "name", "名称")),
        "股票代码": _pick_column(frame, ("股票代码", "ts_code", "代码")),
        "所属行业": _pick_column(frame, ("所属行业", "industry", "行业")),
        "涨停题材": _pick_column(frame, ("涨停原因类别", "涨停题材汇总", "涨停题材", "reason")),
    }
    result = pd.DataFrame()
    for target, source in required.items():
        result[target] = frame[source] if source else ""
    result["股票代码"] = result["股票代码"].map(_normalize_symbol)
    result["日期"] = str(trade_date)
    return result.dropna(subset=["股票代码"]).reset_index(drop=True)


def _filter_limit_frame(frame: pd.DataFrame, settings: LimitStrengthConfig) -> pd.DataFrame:
    result = frame.copy()
    names = result["股票名称"].astype(str)
    for keyword in settings.exclude_name_keywords:
        result = result[~names.str.contains(str(keyword), case=False, na=False)]
        names = result["股票名称"].astype(str)
    codes = result["股票代码"].astype(str).str.replace(".", "", regex=False)
    for prefix in settings.exclude_code_prefixes:
        result = result[~codes.str.startswith(str(prefix))]
        codes = result["股票代码"].astype(str).str.replace(".", "", regex=False)
    return result.reset_index(drop=True)


def _fetch_akshare_daily(symbol: str, settings: LimitStrengthConfig, as_of: str | None = None) -> pd.DataFrame:
    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError("缺少 akshare 依赖，请先安装 requirements.txt") from exc
    end_date = str(as_of or datetime.now().strftime("%Y%m%d")).replace("-", "")
    end_dt = datetime.strptime(end_date, "%Y%m%d")
    start_date = (end_dt - timedelta(days=settings.history_days)).strftime("%Y%m%d")
    return ak.stock_zh_a_daily(symbol=_akshare_symbol(symbol), start_date=start_date, end_date=end_date, adjust=settings.adjust)


def _normalize_daily_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["close", "high", "volume"])
    data = frame.copy()
    rename = {"收盘价": "close", "最高价": "high", "成交量": "volume"}
    data = data.rename(columns={key: value for key, value in rename.items() if key in data.columns})
    if not {"close", "high", "volume"}.issubset(data.columns):
        return pd.DataFrame(columns=["close", "high", "volume"])
    return data.reset_index(drop=True)


def _ma_score(close: pd.Series, settings: LimitStrengthConfig) -> float:
    w1, w2, w3, w4 = settings.ma_windows
    if len(close) < max(150, w4 + settings.continue_days):
        return 0.0
    ma1, ma2, ma3, ma4 = (close.rolling(window).mean() for window in (w1, w2, w3, w4))
    for offset in range(settings.continue_days + 1):
        idx = -1 - offset
        if not (close.iloc[idx] > ma1.iloc[idx] > ma2.iloc[idx] > ma3.iloc[idx] > ma4.iloc[idx]):
            return 0.0
    diff_end = ma1.iloc[-1] - ma4.iloc[-1]
    diff_start = ma1.iloc[-settings.continue_days] - ma4.iloc[-settings.continue_days]
    if diff_start <= 0 or diff_end <= settings.enlarge_times * diff_start:
        return 0.0
    enlarge_ratio = diff_end / diff_start
    days_score = max(0, 100 - settings.continue_days * 15)
    enlarge_score = min(100, 60 + (enlarge_ratio - 1) * 40)
    return round(days_score * 0.6 + enlarge_score * 0.4, 2)


def _breakout_score(close: pd.Series, high: pd.Series) -> float:
    if len(close) < 250:
        return 0.0
    high_250 = high.rolling(250).max().iloc[-1]
    if high_250 <= 0 or pd.isna(high_250):
        return 0.0
    ratio = close.iloc[-1] / high_250
    if ratio >= 0.95:
        return round(min(100, 60 + (ratio - 0.95) * 400), 2)
    if ratio >= 0.85:
        return round(30 + (ratio - 0.85) * 300, 2)
    return round(max(0, ratio * 35), 2)


def _momentum_score(close: pd.Series) -> float:
    if len(close) < 11:
        return 0.0
    past = close.iloc[-11]
    if past <= 0 or pd.isna(past):
        return 0.0
    momentum = (close.iloc[-1] - past) / past * 100
    if momentum > 25:
        return 100.0
    if momentum > 15:
        return 80 + (momentum - 15) * 2
    if momentum > 8:
        return 60 + (momentum - 8) * 2.86
    if momentum > 0:
        return 40 + momentum * 2.5
    return max(0, 30 + momentum * 2)


def _volume_score(volume: pd.Series) -> float:
    if len(volume) < 30:
        return 0.0
    recent = volume.iloc[-10:].mean()
    historical = volume.iloc[-30:-10].mean()
    if historical <= 0 or pd.isna(historical):
        return 0.0
    ratio = recent / historical
    if ratio > 4:
        return 100.0
    if ratio > 2.5:
        return 80 + (ratio - 2.5) * 13.3
    if ratio > 1.5:
        return 60 + (ratio - 1.5) * 20
    if ratio > 1:
        return 40 + (ratio - 1) * 40
    return max(0, ratio * 40)


def _write_html_report(result: pd.DataFrame, changes: pd.DataFrame, output_path: Path, latest_date: str, loaded_dates: list[str]) -> None:
    from visual.components import html_document

    output_path.write_text(
        html_document(
            title=f"{latest_date} 涨停强势股筛选",
            styles="""
            body { margin:0; background:#f5f7fb; color:#172033; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans SC",sans-serif; }
            main { width:min(1380px, calc(100vw - 40px)); margin:0 auto; padding:28px 0 44px; }
            h1 { margin:0 0 8px; font-size:28px; }
            p { color:#667085; margin:0 0 18px; }
            table { width:100%; border-collapse:collapse; background:white; border:1px solid #d9e2ef; margin-bottom:22px; }
            th, td { padding:8px 10px; border-bottom:1px solid #e6edf5; text-align:left; font-size:13px; }
            th { background:#eef4ff; }
            .cards { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin:16px 0; }
            .cards div { background:white; border:1px solid #d9e2ef; border-radius:8px; padding:14px; }
            .cards span { display:block; color:#667085; font-size:12px; }
            .cards strong { font-size:24px; }
            """,
            body=f"""
            <main>
              <h1>{latest_date} 涨停强势股筛选</h1>
              <p>本地涨停数据库回看 {len(loaded_dates)} 天：{", ".join(loaded_dates[:10])}</p>
              <section class="cards">
                <div><span>上榜</span><strong>{len(result)}</strong></div>
                <div><span>新增</span><strong>{int((result.get("新增/剔除状态") == "新增").sum()) if len(result) else 0}</strong></div>
                <div><span>剔除</span><strong>{int((changes.get("新增/剔除状态") == "剔除").sum()) if len(changes) else 0}</strong></div>
                <div><span>最高分</span><strong>{_fmt_num(result.get("综合评分", pd.Series(dtype=float)).max())}</strong></div>
              </section>
              <h2>筛选结果</h2>
              {_html_table(result)}
              <h2>新增/剔除变化</h2>
              {_html_table(changes)}
            </main>
            """,
        ),
        encoding="utf-8",
    )


def _html_table(frame: pd.DataFrame, limit: int = 120) -> str:
    if frame.empty:
        return "<p>暂无数据</p>"
    view = _ensure_output_columns(frame).head(limit)
    header = "".join(f"<th>{_escape(column)}</th>" for column in view.columns)
    rows = []
    for _, row in view.iterrows():
        rows.append("<tr>" + "".join(f"<td>{_escape(_cell(value))}</td>" for value in row.tolist()) + "</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _ensure_output_columns(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if "涨停题材汇总" in result.columns and "涨停题材" not in result.columns:
        result = result.rename(columns={"涨停题材汇总": "涨停题材"})
    for column in DEFAULT_OUTPUT_COLUMNS:
        if column not in result.columns:
            result[column] = ""
    return result[DEFAULT_OUTPUT_COLUMNS]


def _read_previous_result(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=DEFAULT_OUTPUT_COLUMNS)
    for encoding in ("utf-8-sig", "GBK", "utf-8"):
        try:
            frame = pd.read_csv(path, encoding=encoding, dtype={"股票代码": str})
            return _ensure_output_columns(frame)
        except UnicodeDecodeError:
            continue
        except Exception:
            return pd.DataFrame(columns=DEFAULT_OUTPUT_COLUMNS)
    return pd.DataFrame(columns=DEFAULT_OUTPUT_COLUMNS)


def _zero_scores() -> dict[str, float]:
    return {"综合评分": 0.0, "均线多头分": 0.0, "突破前高分": 0.0, "动量分": 0.0, "成交量分": 0.0}


def _normalize_symbol(value: object) -> str:
    text = str(value or "").strip().upper()
    if not text or text == "NAN":
        return ""
    if "." in text:
        code, suffix = text.split(".", 1)
        return f"{code.zfill(6)}.{suffix}"
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return text
    suffix = "SH" if digits.startswith(("6", "9")) else "SZ"
    return f"{digits.zfill(6)}.{suffix}"


def _akshare_symbol(symbol: str) -> str:
    code, suffix = symbol.lower().split(".")
    return suffix + code


def _pick_column(frame: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    return next((name for name in names if name in frame.columns), None)


def _resolve_path(value: object) -> Path:
    path = Path(str(value)).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def _fmt_num(value: object) -> str:
    try:
        if pd.isna(value):
            return "--"
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "--"


def _cell(value: object) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _escape(value: object) -> str:
    import html

    return html.escape(str(value))
