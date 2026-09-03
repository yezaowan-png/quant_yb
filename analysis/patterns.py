"""Pattern scanners for local A-share K-line caches.

The scanners are research filters, not trading strategies. They evaluate the
latest completed bar and only use previous bars to define breakout bases.
"""

from __future__ import annotations

from dataclasses import dataclass
import html
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

from data.stock_pool import resolve_pool_symbols
from visual.components import html_document, stock_link_html


@dataclass
class PatternScanResult:
    pattern: str
    output_path: Path
    html_path: Path
    rows: pd.DataFrame


def _cache_dir(config: dict) -> Path:
    return Path(config["data"]["cache_dir"])


def _signals_dir(config: dict) -> Path:
    return Path(config["output"].get("signals_dir", "output/signals"))


def _load_stock_name_map(config: dict) -> dict[str, str]:
    path = Path(config.get("data", {}).get("meta_dir", "data/meta")) / "stock_names.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype=str)
    if "ts_code" not in df.columns or "name" not in df.columns:
        return {}
    return dict(zip(df["ts_code"].astype(str), df["name"].astype(str)))


def _list_cached_symbols(config: dict) -> list[str]:
    cache_dir = _cache_dir(config)
    if not cache_dir.exists():
        return []
    return sorted(path.stem.upper() for path in cache_dir.glob("*.csv") if not path.name.startswith("_"))


def _resolve_symbols(
    config: dict,
    pool: str | None = None,
    pool_mode: str = "any",
    symbols: Iterable[str] | None = None,
) -> list[str]:
    if symbols:
        seen = set()
        result = []
        for symbol in symbols:
            normalized = str(symbol).strip().upper()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result
    if pool:
        return resolve_pool_symbols(config, pool, pool_mode)
    return _list_cached_symbols(config)


def _load_kline(config: dict, symbol: str) -> pd.DataFrame | None:
    path = _cache_dir(config) / f"{symbol}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, dtype={"date": str})
    if "date" not in df.columns or "close" not in df.columns:
        return None
    df = df.copy()
    df["date"] = df["date"].astype(str).str.replace("-", "", regex=False)
    for col in ("open", "high", "low", "close", "volume", "amount", "pct_chg"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "open" not in df.columns:
        df["open"] = df["close"]
    if "high" not in df.columns:
        df["high"] = df["close"]
    if "low" not in df.columns:
        df["low"] = df["close"]
    if "volume" not in df.columns:
        df["volume"] = 0.0
    if "pct_chg" not in df.columns:
        df["pct_chg"] = df["close"].pct_change() * 100
    return df.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)


def _score_range(value: float, low: float, high: float) -> float:
    if value <= low:
        return 0.0
    if value >= high:
        return 100.0
    return (value - low) / (high - low) * 100.0


def scan_main_rise_wave(df: pd.DataFrame, **params) -> dict | None:
    ma_periods = tuple(int(v) for v in params.get("ma_periods", (5, 10, 20, 30)))
    continue_days = int(params.get("continue_days", 5))
    enlarge_times = float(params.get("enlarge_times", 1.2))
    high_lookback = int(params.get("high_lookback", 120))
    high_lower = float(params.get("high_lower", 0.95))
    high_upper = float(params.get("high_upper", 1.05))
    trend_days = int(params.get("trend_days", 20))
    momentum_days = int(params.get("momentum_days", 10))
    volume_days = int(params.get("volume_days", 10))

    min_len = max(max(ma_periods), high_lookback + trend_days, momentum_days + 1, volume_days * 2) + 2
    if len(df) < min_len:
        return None

    close = df["close"]
    high = df["high"]
    volume = df["volume"]
    mas = [close.rolling(period).mean() for period in ma_periods]
    latest = df.iloc[-1]

    ma_ok = True
    for offset in range(continue_days):
        idx = -1 - offset
        if not (close.iloc[idx] > mas[0].iloc[idx] > mas[1].iloc[idx] > mas[2].iloc[idx] > mas[3].iloc[idx]):
            ma_ok = False
            break
    spread_now = mas[0].iloc[-1] - mas[-1].iloc[-1]
    spread_start = mas[0].iloc[-continue_days - 1] - mas[-1].iloc[-continue_days - 1]
    spread_ratio = float(spread_now / spread_start) if spread_start and pd.notna(spread_start) else 0.0
    ma_ok = bool(ma_ok and spread_now > 0 and spread_ratio >= enlarge_times)

    historical_high = float(high.iloc[:-1].tail(high_lookback).max())
    close_to_high = float(latest["close"] / historical_high) if historical_high else 0.0
    prior_overheated = (
        high.iloc[:-1].tail(trend_days) > historical_high * high_upper
    ).any()
    breakout_ok = high_lower <= close_to_high <= high_upper and not prior_overheated

    momentum = float((close.iloc[-1] / close.iloc[-momentum_days - 1] - 1.0) * 100)
    recent_volume = float(volume.iloc[-volume_days:].mean())
    prior_volume = float(volume.iloc[-volume_days * 3:-volume_days].mean()) if len(volume) >= volume_days * 3 else float(volume.iloc[:-volume_days].mean())
    volume_ratio = recent_volume / prior_volume if prior_volume else 0.0

    if not (ma_ok or breakout_ok):
        return None

    ma_score = min(100.0, 55.0 + max(spread_ratio - 1.0, 0.0) * 35.0) if ma_ok else 0.0
    high_score = _score_range(close_to_high, high_lower, high_upper) if breakout_ok else 0.0
    momentum_score = _score_range(momentum, 0.0, 25.0)
    volume_score = _score_range(volume_ratio, 0.8, 3.0)
    score = ma_score * 0.4 + high_score * 0.2 + momentum_score * 0.2 + volume_score * 0.2
    reasons = []
    if ma_ok:
        reasons.append(f"均线多头连续{continue_days}日, 开口{spread_ratio:.2f}倍")
    if breakout_ok:
        reasons.append(f"收盘接近/突破{high_lookback}日历史高点, 比例{close_to_high:.2f}")
    return {
        "score": round(score, 2),
        "close": round(float(latest["close"]), 4),
        "reason": "; ".join(reasons),
        "ma_score": round(ma_score, 2),
        "breakout_score": round(high_score, 2),
        "momentum_score": round(momentum_score, 2),
        "volume_score": round(volume_score, 2),
        "history_high": round(historical_high, 4),
        "volume_ratio": round(volume_ratio, 4),
    }


def scan_bottom_pattern_break(df: pd.DataFrame, **params) -> dict | None:
    enable_double = bool(params.get("enable_double_bottom", True))
    enable_box = bool(params.get("enable_box_break", True))
    detect_range = int(params.get("detect_range", 40))
    mid_error = int(params.get("mid_error", 5))
    bottom_error_pct = float(params.get("bottom_error_pct", 0.02))
    neck_break_pct = float(params.get("neck_break_pct", 0.03))
    volume_threshold_pct = float(params.get("volume_threshold_pct", 0.05))
    first_break_only = bool(params.get("first_break_only", False))
    box_window = int(params.get("box_window", 40))
    box_range_pct = float(params.get("box_range_pct", 0.15))
    ma_periods = tuple(int(v) for v in params.get("ma_periods", (20, 30, 60)))
    ma_bond_pct = float(params.get("ma_bond_pct", 0.05))
    break_pct = float(params.get("break_pct", 0.05))

    latest = df.iloc[-1]
    reasons = []
    score = 0.0
    payload: dict[str, object] = {
        "close": round(float(latest["close"]), 4),
        "score": 0.0,
        "reason": "",
    }

    if enable_double and len(df) >= detect_range + 2:
        hist = df.iloc[-detect_range - 1:-1].copy()
        mid = int(detect_range / 2)
        left = hist.iloc[: max(1, mid + mid_error)]
        right = hist.iloc[max(0, mid - mid_error):]
        left_low_idx = left["close"].idxmin()
        right_low_idx = right["close"].idxmin()
        if left_low_idx != right_low_idx:
            left_low = float(df.loc[left_low_idx, "close"])
            right_low = float(df.loc[right_low_idx, "close"])
            denominator = min(left_low, right_low)
            error_ratio = abs(left_low - right_low) / denominator if denominator else 1.0
            between = df.loc[min(left_low_idx, right_low_idx): max(left_low_idx, right_low_idx)]
            neck = float(between["close"].max()) if not between.empty else 0.0
            effective_neck = neck * (1 + neck_break_pct)
            current_close = float(latest["close"])
            range_mean_volume = float(hist["volume"].mean())
            current_volume = float(latest["volume"])
            prev_after_right = df.loc[right_low_idx: df.index[-2]]
            previous_breaks = prev_after_right[prev_after_right["close"] > effective_neck]
            first_break = len(previous_breaks) == 0
            volume_ok = (
                (current_volume - range_mean_volume) / range_mean_volume >= volume_threshold_pct
                if range_mean_volume
                else False
            )
            if error_ratio <= bottom_error_pct and current_close > effective_neck and (first_break or not first_break_only):
                score += 55.0 + (10.0 if first_break else 0.0) + (10.0 if volume_ok else 0.0)
                reasons.append(
                    f"双底突破: 左底{left_low:.2f}, 右底{right_low:.2f}, 颈线{neck:.2f}, 首次突破{'是' if first_break else '否'}"
                )
                payload.update(
                    {
                        "left_bottom": round(left_low, 4),
                        "right_bottom": round(right_low, 4),
                        "neckline": round(neck, 4),
                        "first_break": first_break,
                        "volume_break": volume_ok,
                    }
                )

    if enable_box and len(df) >= max(box_window, max(ma_periods)) + 2:
        hist = df.iloc[-box_window - 1:-1].copy()
        upper = float(hist["high"].max())
        lower = float(hist["low"].min())
        mean_close = float(hist["close"].mean())
        range_ok = (upper - lower) / mean_close <= box_range_pct if mean_close else False
        ma_values = [float(df["close"].iloc[:-1].rolling(period).mean().iloc[-1]) for period in ma_periods]
        ma_max = max(ma_values)
        ma_min = min(ma_values)
        ma_ok = ma_min > 0 and (ma_max / ma_min - 1.0) <= ma_bond_pct
        prev_close = float(df["close"].iloc[-2])
        current_gain = float(latest["close"] / prev_close - 1.0) if prev_close else 0.0
        breakout_ok = float(latest["close"]) > upper and current_gain >= break_pct
        if range_ok and ma_ok and breakout_ok:
            score += 45.0
            reasons.append(f"箱体突破: 历史上沿{upper:.2f}, 振幅{(upper-lower)/mean_close:.2%}, 均线粘合")
            payload.update({"box_upper": round(upper, 4), "box_lower": round(lower, 4)})

    if not reasons:
        return None
    payload["score"] = round(min(score, 100.0), 2)
    payload["reason"] = "; ".join(reasons)
    return payload


def scan_needle_bottom_raise(df: pd.DataFrame, **params) -> dict | None:
    bottom_pct = float(params.get("bottom_pct", 0.05))
    raise_pct = float(params.get("raise_pct", 0.03))
    occur_range = int(params.get("occur_range", 10))
    volume_mult = float(params.get("volume_mult", 1.5))
    if len(df) < occur_range + 2:
        return None

    history = df.iloc[-occur_range - 1:-1].copy()
    if history.empty:
        return None
    min_low = float(history["low"].min())
    candidates = history[
        (history["low"] <= min_low * 1.000001)
        & (history["open"] / history["low"] > 1 + bottom_pct)
        & (history["close"] / history["low"] > 1 + bottom_pct)
    ]
    if candidates.empty:
        return None
    candidate = candidates.iloc[-1]
    avg_volume = float(history["volume"].mean())
    volume_ok = float(candidate["volume"]) > avg_volume * volume_mult if avg_volume else False
    current = df.iloc[-1]
    price_ok = float(current["close"]) > float(candidate["high"]) * (1 + raise_pct)
    if not (price_ok and volume_ok):
        return None
    score = min(100.0, 60.0 + (float(current["close"]) / float(candidate["high"]) - 1.0) * 300.0)
    return {
        "score": round(score, 2),
        "close": round(float(current["close"]), 4),
        "reason": (
            f"单针探底后回升: 单针日{candidate['date']}, "
            f"低点{float(candidate['low']):.2f}, 当前收盘突破单针高点"
        ),
        "needle_date": str(candidate["date"]),
        "needle_low": round(float(candidate["low"]), 4),
        "needle_high": round(float(candidate["high"]), 4),
        "needle_volume_ratio": round(float(candidate["volume"]) / avg_volume, 4) if avg_volume else None,
    }


PATTERN_SCANNERS: dict[str, Callable[..., dict | None]] = {
    "main_rise_wave": scan_main_rise_wave,
    "bottom_pattern_break": scan_bottom_pattern_break,
    "needle_bottom_raise": scan_needle_bottom_raise,
}

PATTERN_LABELS = {
    "main_rise_wave": "主升浪启动",
    "bottom_pattern_break": "底部盘整突破",
    "needle_bottom_raise": "单针探底回升",
}


def scan_patterns(
    config: dict,
    pattern: str,
    pool: str | None = None,
    pool_mode: str = "any",
    symbols: Iterable[str] | None = None,
    **params,
) -> pd.DataFrame:
    pattern = str(pattern).strip()
    if pattern not in PATTERN_SCANNERS:
        available = ", ".join(PATTERN_SCANNERS)
        raise ValueError(f"未知形态: {pattern}。可用: {available}")
    scanner = PATTERN_SCANNERS[pattern]
    names = _load_stock_name_map(config)
    rows = []
    for symbol in _resolve_symbols(config, pool=pool, pool_mode=pool_mode, symbols=symbols):
        df = _load_kline(config, symbol)
        if df is None or df.empty:
            continue
        hit = scanner(df, **params)
        if not hit:
            continue
        row = {
            "signal_date": str(df["date"].iloc[-1]),
            "ts_code": symbol,
            "name": names.get(symbol, ""),
            "pattern": pattern,
            "pattern_name": PATTERN_LABELS.get(pattern, pattern),
        }
        row.update(hit)
        rows.append(row)

    result = pd.DataFrame(rows)
    if result.empty:
        return pd.DataFrame(
            columns=["signal_date", "ts_code", "name", "pattern", "pattern_name", "score", "close", "reason"]
        )
    return result.sort_values(["score", "ts_code"], ascending=[False, True]).reset_index(drop=True)


def _table_html(df: pd.DataFrame, output_path: Path, config: dict | None = None, limit: int = 200) -> str:
    if df.empty:
        return '<p class="empty">暂无命中股票</p>'
    header = "".join(f"<th>{html.escape(str(col))}</th>" for col in df.columns)
    rows = []
    for _, row in df.head(limit).iterrows():
        cells = []
        for column, value in row.items():
            if column == "ts_code" and not pd.isna(value):
                cells.append(f"<td>{stock_link_html(config, output_path, value)}</td>")
            else:
                cells.append(f"<td>{html.escape('' if pd.isna(value) else str(value))}</td>")
        cells = "".join(cells)
        rows.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _write_report(title: str, df: pd.DataFrame, output_path: Path, config: dict | None = None) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        html_document(
            title=title,
            styles="""
            body { margin: 0; background: #f4f6fa; color: #1f2937; font-family: "Microsoft YaHei", "Noto Sans SC", sans-serif; }
            main { width: min(1280px, calc(100vw - 40px)); margin: 0 auto; padding: 28px 0 44px; }
            h1 { margin: 0 0 8px; font-size: 28px; }
            .sub { color: #667085; margin-bottom: 18px; }
            table { width: 100%; border-collapse: collapse; background: white; border: 1px solid #d9e2ef; }
            th, td { padding: 8px 10px; border-bottom: 1px solid #e6edf5; text-align: left; font-size: 13px; vertical-align: top; }
            th { background: #eef4ff; color: #334155; }
            td:nth-child(6), td:nth-child(7) { text-align: right; }
            a.stock-link { color: #2454a6; font-weight: 700; text-decoration: none; }
            a.stock-link:hover { text-decoration: underline; }
            .empty { background: white; border: 1px solid #d9e2ef; padding: 18px; }
            """,
            body=f"""
            <main>
              <h1>{html.escape(title)}</h1>
              <div class="sub">扫描结果只基于本地 K 线缓存；突破基准窗口不包含信号当日。</div>
              {_table_html(df, output_path, config)}
            </main>
            """,
        ),
        encoding="utf-8",
    )
    return output_path


def save_pattern_scan(
    config: dict,
    pattern: str,
    pool: str | None = None,
    pool_mode: str = "any",
    symbols: Iterable[str] | None = None,
    **params,
) -> PatternScanResult:
    rows = scan_patterns(config, pattern, pool=pool, pool_mode=pool_mode, symbols=symbols, **params)
    date_part = (
        str(rows["signal_date"].iloc[0])
        if not rows.empty and "signal_date" in rows.columns
        else pd.Timestamp.today().strftime("%Y%m%d")
    )
    safe_pool = f"_{str(pool).replace(',', '_').replace('/', '_')}" if pool else ""
    out_dir = _signals_dir(config)
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / f"pattern_signals_{pattern}{safe_pool}_{date_part}.csv"
    html_path = out_dir / f"pattern_signals_{pattern}{safe_pool}_{date_part}.html"
    rows.to_csv(output_path, index=False)
    _write_report(f"{PATTERN_LABELS.get(pattern, pattern)} 形态扫描", rows, html_path, config)
    return PatternScanResult(pattern, output_path, html_path, rows)
