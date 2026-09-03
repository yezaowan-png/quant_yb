"""Single-stock moving-average and Fibonacci resonance analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd


FIBONACCI_RATIOS: tuple[tuple[str, float], ...] = (
    ("0.236", 0.236),
    ("0.382", 0.382),
    ("0.500", 0.500),
    ("0.618", 0.618),
    ("0.786", 0.786),
)


@dataclass(frozen=True)
class SupportResistanceConfig:
    ma_periods: tuple[int, ...]
    resonance_threshold_pct: float
    adjust: str
    output_dir: Path

    @classmethod
    def from_project_config(cls, config: dict) -> "SupportResistanceConfig":
        raw = dict(config.get("support_resistance") or {})
        periods = tuple(dict.fromkeys(int(value) for value in raw.get("ma_periods", [20, 60, 120])))
        if not periods or any(period <= 0 for period in periods):
            raise ValueError("support_resistance.ma_periods 必须是正整数列表")

        threshold = float(raw.get("resonance_threshold_pct", 2.0))
        if threshold <= 0:
            raise ValueError("support_resistance.resonance_threshold_pct 必须大于 0")

        adjust = str(raw.get("adjust", "qfq") or "").strip().lower()
        if adjust == "none":
            adjust = ""
        if adjust not in {"", "qfq", "hfq"}:
            raise ValueError("support_resistance.adjust 仅支持 qfq、hfq 或 none")

        reports_dir = Path(config.get("output", {}).get("reports_dir", "output/reports"))
        output_dir = Path(raw.get("output_dir") or reports_dir / "support_resistance")
        return cls(
            ma_periods=periods,
            resonance_threshold_pct=threshold,
            adjust=adjust,
            output_dir=output_dir,
        )


@dataclass
class SupportResistanceResult:
    symbol: str
    ak_symbol: str
    stock_name: str
    requested_start: str
    requested_end: str
    start_date: str
    end_date: str
    data: pd.DataFrame
    fibonacci_levels: dict[str, object]
    ma_values: dict[str, float]
    resonance_zones: list[dict[str, object]]
    report_lines: list[str]
    settings: SupportResistanceConfig
    report_path: Path | None = field(default=None)


PriceFetcher = Callable[[str, str], pd.DataFrame]


def normalize_stock_symbol(symbol: str) -> tuple[str, str]:
    """Return AkShare's prefixed symbol and the project's Tushare-style symbol."""
    raw = str(symbol or "").strip().upper()
    if not raw:
        raise ValueError("股票代码不能为空")

    if raw.startswith(("SH", "SZ")) and raw[2:].isdigit():
        exchange = raw[:2]
        code = raw[2:]
    elif raw.endswith((".SH", ".SZ")) and raw[:-3].isdigit():
        exchange = raw[-2:]
        code = raw[:-3]
    elif raw.isdigit():
        code = raw
        exchange = "SH" if code.startswith(("5", "6")) else "SZ"
    else:
        raise ValueError(f"无法识别股票代码: {symbol}")

    if len(code) != 6:
        raise ValueError(f"股票代码必须为 6 位数字: {symbol}")
    return f"{exchange.lower()}{code}", f"{code}.{exchange}"


def _parse_date(value: str, label: str) -> pd.Timestamp:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label}不能为空")
    try:
        return pd.to_datetime(text, format="%Y%m%d" if "-" not in text else "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}格式应为 YYYYMMDD: {value}") from exc


def _fetch_akshare_daily(symbol: str, adjust: str) -> pd.DataFrame:
    import akshare as ak

    return ak.stock_zh_a_daily(symbol=symbol, adjust=adjust)


def get_stock_data(
    symbol: str,
    start_date: str,
    end_date: str,
    adjust: str = "qfq",
    price_fetcher: PriceFetcher | None = None,
) -> tuple[str, str, pd.DataFrame]:
    """Fetch and normalize adjusted daily OHLCV data for one A-share stock."""
    start = _parse_date(start_date, "开始日期")
    end = _parse_date(end_date, "结束日期")
    if start > end:
        raise ValueError("开始日期不能晚于结束日期")

    ak_symbol, project_symbol = normalize_stock_symbol(symbol)
    fetcher = price_fetcher or _fetch_akshare_daily
    frame = fetcher(ak_symbol, adjust)
    if frame is None or frame.empty:
        raise ValueError(f"未获取到 {project_symbol} 的日线数据")

    df = frame.copy()
    df.columns = [str(column).strip().lower() for column in df.columns]
    if "date" not in df.columns:
        index_name = str(df.index.name or "").strip().lower()
        if index_name == "date" or isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index()
            df.rename(columns={df.columns[0]: "date"}, inplace=True)

    required = {"date", "open", "high", "low", "close"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"日线数据缺少字段: {', '.join(missing)}")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    numeric_columns = [column for column in ("open", "high", "low", "close", "volume", "turnover") if column in df.columns]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["date", "open", "high", "low", "close"])
    df = df[(df["date"] >= start) & (df["date"] <= end)]
    df = df.sort_values("date").drop_duplicates(subset=["date"], keep="last").set_index("date")
    if df.empty:
        raise ValueError(f"{project_symbol} 在 {start_date} 至 {end_date} 区间内没有日线数据")
    return ak_symbol, project_symbol, df


def calc_fibonacci_levels(df: pd.DataFrame) -> dict[str, object]:
    """Calculate the original script's direction-aware Fibonacci levels."""
    if df.empty:
        raise ValueError("无法对空行情计算斐波那契价位")

    high_price = float(df["high"].max())
    low_price = float(df["low"].min())
    high_date = pd.Timestamp(df["high"].idxmax())
    low_date = pd.Timestamp(df["low"].idxmin())
    if high_date < low_date:
        start_price, end_price, trend_dir = high_price, low_price, "下跌"
    else:
        start_price, end_price, trend_dir = low_price, high_price, "上涨"

    difference = end_price - start_price
    levels: dict[str, object] = {
        key: float(start_price + difference * ratio)
        for key, ratio in FIBONACCI_RATIOS
    }
    levels.update(
        {
            "high": high_price,
            "low": low_price,
            "high_date": high_date,
            "low_date": low_date,
            "trend_dir": trend_dir,
        }
    )
    return levels


def add_moving_averages(df: pd.DataFrame, ma_periods: tuple[int, ...]) -> tuple[pd.DataFrame, dict[str, float]]:
    frame = df.copy()
    values: dict[str, float] = {}
    for period in ma_periods:
        name = f"MA{period}"
        frame[name] = frame["close"].rolling(window=period, min_periods=period).mean()
        latest = frame[name].dropna()
        if not latest.empty:
            values[name] = float(latest.iloc[-1])
    return frame, values


def find_resonance_zone(
    df: pd.DataFrame,
    fib_levels: dict[str, object],
    ma_periods: tuple[int, ...] = (20, 60, 120),
    threshold_pct: float = 2.0,
) -> list[dict[str, object]]:
    """Find current moving averages within the threshold of Fibonacci levels."""
    _, ma_values = add_moving_averages(df, ma_periods)
    current_price = float(df["close"].iloc[-1])
    zones: list[dict[str, object]] = []
    for ma_name, ma_value in ma_values.items():
        if ma_value == 0:
            continue
        for fib_name, _ in FIBONACCI_RATIOS:
            fib_value = float(fib_levels[fib_name])
            difference_pct = abs(ma_value - fib_value) / abs(ma_value) * 100
            if difference_pct >= threshold_pct:
                continue
            center = (ma_value + fib_value) / 2
            reference_type = "支撑" if center < current_price else "压力" if center > current_price else "当前价附近"
            half_width_pct = threshold_pct / 200
            zones.append(
                {
                    "ma": ma_name,
                    "ma_value": ma_value,
                    "fib": fib_name,
                    "fib_value": fib_value,
                    "diff_pct": difference_pct,
                    "center": center,
                    "lower": ma_value * (1 - half_width_pct),
                    "upper": ma_value * (1 + half_width_pct),
                    "reference_type": reference_type,
                }
            )
    return sorted(zones, key=lambda item: (float(item["diff_pct"]), str(item["ma"]), str(item["fib"])))


def _build_report_lines(
    data: pd.DataFrame,
    fib_levels: dict[str, object],
    ma_values: dict[str, float],
    resonance_zones: list[dict[str, object]],
) -> list[str]:
    current_price = float(data["close"].iloc[-1])
    lines = [
        f"区间趋势按高低点先后识别为{fib_levels['trend_dir']}，区间为 {float(fib_levels['low']):.2f} 至 {float(fib_levels['high']):.2f}。",
        f"最新收盘价为 {current_price:.2f}。",
    ]
    if ma_values:
        ma_text = "、".join(f"{name} {value:.2f}" for name, value in ma_values.items())
        lines.append(f"当前有效均线：{ma_text}。")
    if resonance_zones:
        support_count = sum(zone["reference_type"] == "支撑" for zone in resonance_zones)
        pressure_count = sum(zone["reference_type"] == "压力" for zone in resonance_zones)
        lines.append(f"发现 {len(resonance_zones)} 组均线与黄金分割共振，其中支撑参考 {support_count} 组、压力参考 {pressure_count} 组。")
        nearest = min(resonance_zones, key=lambda item: abs(float(item["center"]) - current_price))
        lines.append(
            f"离当前价最近的是 {nearest['ma']} 与 Fib {nearest['fib']}，中心价约 {float(nearest['center']):.2f}，归类为{nearest['reference_type']}参考。"
        )
    else:
        lines.append("当前未发现满足偏差阈值的均线与黄金分割共振区域。")
    lines.append("共振价位仅用于技术结构观察，应结合成交量、市场环境和风险控制判断。")
    return lines


def analyze_support_resistance(
    config: dict,
    symbol: str,
    stock_name: str,
    start_date: str,
    end_date: str,
    price_fetcher: PriceFetcher | None = None,
) -> SupportResistanceResult:
    settings = SupportResistanceConfig.from_project_config(config)
    ak_symbol, project_symbol, data = get_stock_data(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        adjust=settings.adjust,
        price_fetcher=price_fetcher,
    )
    data, ma_values = add_moving_averages(data, settings.ma_periods)
    fib_levels = calc_fibonacci_levels(data)
    resonance_zones = find_resonance_zone(
        data,
        fib_levels,
        ma_periods=settings.ma_periods,
        threshold_pct=settings.resonance_threshold_pct,
    )
    return SupportResistanceResult(
        symbol=project_symbol,
        ak_symbol=ak_symbol,
        stock_name=str(stock_name or "").strip(),
        requested_start=str(start_date),
        requested_end=str(end_date),
        start_date=data.index.min().strftime("%Y%m%d"),
        end_date=data.index.max().strftime("%Y%m%d"),
        data=data,
        fibonacci_levels=fib_levels,
        ma_values=ma_values,
        resonance_zones=resonance_zones,
        report_lines=_build_report_lines(data, fib_levels, ma_values, resonance_zones),
        settings=settings,
    )


def save_support_resistance_analysis(
    config: dict,
    symbol: str,
    stock_name: str,
    start_date: str,
    end_date: str,
    price_fetcher: PriceFetcher | None = None,
) -> SupportResistanceResult:
    """Run the analysis and save its interactive HTML report."""
    from visual.support_resistance_report import build_support_resistance_report

    result = analyze_support_resistance(
        config=config,
        symbol=symbol,
        stock_name=stock_name,
        start_date=start_date,
        end_date=end_date,
        price_fetcher=price_fetcher,
    )
    result.settings.output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{result.symbol}_{result.requested_start}_{result.requested_end}_support_resistance"
    result.report_path = result.settings.output_dir / f"{stem}.html"
    build_support_resistance_report(result, result.report_path)
    return result
