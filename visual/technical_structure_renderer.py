"""Convert technical-structure results into page-neutral ECharts series."""

from __future__ import annotations

from html import escape
from typing import Any

from analysis.technical_structure.models import TechnicalStructureResult


_TF_LABEL = {"1d": "日线", "1w": "周线", "1mo": "月线"}
_TF_WIDTH = {"1d": 1.2, "1w": 1.8, "1mo": 2.4}
_ADJUSTMENT_LABEL = {"qfq": "前复权", "hfq": "后复权", "none": "不复权"}


def _payload(result: TechnicalStructureResult | dict[str, Any]) -> dict[str, Any]:
    return result.to_dict() if isinstance(result, TechnicalStructureResult) else result


def _allowed(item: dict[str, Any], options: dict[str, Any]) -> bool:
    status = str(item.get("status", "active"))
    if status == "broken" and not options.get("include_broken", False):
        return False
    if status == "expired" and not options.get("include_expired", False):
        return False
    return True


def _line_points(
    line: dict[str, Any], data: dict[str, Any], date_axis: list[str]
) -> tuple[str, float, str, float]:
    """Clip a bar-index line to the visible axis without changing its slope."""
    bars = data.get("bars") or []
    axis_dates = set(date_axis)
    available = [
        item for item in bars
        if item.get("date") in axis_dates
        and int(line.get("start_bar_index", 0)) <= int(item.get("bar_index", 0))
        <= int(line.get("projection_end_bar_index", len(bars) - 1))
    ]
    if available:
        start_bar, end_bar = available[0], available[-1]
        slope = float(line.get("slope_per_bar") or 0.0)
        intercept = float(line.get("intercept") or 0.0)
        return (
            str(start_bar["date"]), intercept + slope * int(start_bar["bar_index"]),
            str(end_bar["date"]), intercept + slope * int(end_bar["bar_index"]),
        )
    return (
        max(str(line.get("start_date") or date_axis[0]), date_axis[0]),
        float(line.get("start_price") or 0),
        min(str(line.get("projection_end_date") or date_axis[-1]), date_axis[-1]),
        float(line.get("projection_end_price") or line.get("end_price") or 0),
    )


def _materialize_line(
    date_axis: list[str],
    start_date: str,
    start_price: float,
    end_date: str,
    end_price: float,
) -> list[list[Any]]:
    """Emit one point per category so ECharts dataZoom cannot drop a line.

    A two-endpoint category series disappears when both endpoints fall outside
    the zoomed window. Dense category-aligned points preserve the same straight
    line while ensuring every visible sub-window contains drawable points.
    """
    eligible = [
        (index, date)
        for index, date in enumerate(date_axis)
        if str(start_date) <= str(date) <= str(end_date)
    ]
    if not eligible:
        return []
    left, right = eligible[0][0], eligible[-1][0]
    span = max(right - left, 1)
    return [
        [
            date_axis[index],
            round(float(start_price) + (float(end_price) - float(start_price)) * (index - left) / span, 8),
        ]
        for index in range(left, right + 1)
    ]


class TechnicalStructureRenderer:
    """Build aligned ECharts series without depending on a business page."""

    def build_echarts_series(
        self,
        result: TechnicalStructureResult | dict[str, Any],
        date_axis: list[str],
        options: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        data = _payload(result)
        if not date_axis:
            return []
        opts = {
            "show_horizontal": True,
            "show_zones": True,
            "show_trendlines": True,
            "show_channels": True,
            "include_broken": False,
            "include_expired": False,
            "high_score_only": False,
            "score_threshold": 55.0,
            "max_levels_per_role": 2,
            "max_lines_per_type": 2,
            **(options or {}),
        }
        timeframe = str(data.get("timeframe", "1d"))
        tf_label = _TF_LABEL.get(timeframe, timeframe)
        width = float(opts.get("line_width", _TF_WIDTH.get(timeframe, 1.2)))
        opacity = float(opts.get("opacity", 0.82 if timeframe == "1d" else 0.72))
        first_date, last_date = date_axis[0], date_axis[-1]
        series: list[dict[str, Any]] = []

        if opts["show_horizontal"]:
            candidates = []
            for level in data.get("horizontal_levels") or []:
                if not _allowed(level, opts):
                    continue
                if opts["high_score_only"] and level.get("source") != "manual" and float(level.get("score") or 0) < float(opts["score_threshold"]):
                    continue
                candidates.append(level)
            levels = []
            for role in ("support", "resistance"):
                typed = [item for item in candidates if item.get("type") == role]
                typed.sort(key=lambda item: (item.get("source") != "manual", -float(item.get("score") or 0), abs(float(item.get("distance_pct") or 0))))
                levels.extend(typed[: int(opts["max_levels_per_role"])])
            for index, level in enumerate(levels):
                level_type = str(level.get("type", "support"))
                role = "支撑" if level_type == "support" else "阻力"
                price = float(level["price"])
                color = "#166534" if level_type == "support" else "#991b1b"
                start = max(str(level.get("first_touch_date") or first_date), first_date)
                name = f"结构·{tf_label}·{role}{index + 1}"
                level_data = _materialize_line(
                    date_axis, start, price, last_date, price
                )
                if len(level_data) < 2:
                    continue
                item: dict[str, Any] = {
                    "name": name,
                    "type": "line",
                    "data": level_data,
                    "symbol": "none",
                    "smooth": False,
                    "silent": False,
                    "z": 6,
                    "technicalStructureKind": "horizontal",
                    "technicalStructureStatus": level.get("status"),
                    "lineStyle": {
                        "color": color,
                        "width": width,
                        "type": "dashed" if timeframe == "1d" else "solid",
                        "opacity": opacity,
                    },
                    "tooltip": {
                        "formatter": (
                            f"{tf_label}{role}区<br/>中心 {price:.2f}<br/>"
                            f"区间 {float(level.get('zone_low', price)):.2f} - {float(level.get('zone_high', price)):.2f}<br/>"
                            f"触碰 {int(level.get('touch_count') or 0)} 次 · 得分 {float(level.get('score') or 0):.1f}<br/>"
                            f"状态 {escape(str(level.get('status', 'active')))}"
                        )
                    },
                }
                if opts["show_zones"] and float(level.get("zone_high", price)) > float(level.get("zone_low", price)):
                    item["markArea"] = {
                        "silent": True,
                        "itemStyle": {"color": color, "opacity": 0.035 if timeframe == "1d" else 0.055},
                        "data": [[
                            {"xAxis": start, "yAxis": float(level["zone_low"])},
                            {"xAxis": last_date, "yAxis": float(level["zone_high"])},
                        ]],
                    }
                series.append(item)

        if opts["show_trendlines"]:
            line_candidates = []
            for line in data.get("trendlines") or []:
                if not _allowed(line, opts):
                    continue
                if opts["high_score_only"] and line.get("source") != "manual" and float(line.get("score") or 0) < float(opts["score_threshold"]):
                    continue
                line_candidates.append(line)
            lines = []
            for line_type in sorted({str(item.get("type")) for item in line_candidates}):
                typed = [item for item in line_candidates if str(item.get("type")) == line_type]
                typed.sort(key=lambda item: (item.get("source") != "manual", -float(item.get("score") or 0)))
                lines.extend(typed[: int(opts["max_lines_per_type"])])
            for index, line in enumerate(lines):
                line_type = str(line.get("type", ""))
                role = "上升支撑" if line_type == "ascending_support" else "下降阻力" if line_type == "descending_resistance" else "趋势线"
                start_date, start_price, end_date, end_price = _line_points(line, data, date_axis)
                name = f"结构·{tf_label}·{role}{index + 1}"
                line_data = _materialize_line(
                    date_axis, start_date, start_price, end_date, end_price
                )
                if len(line_data) < 2:
                    continue
                series.append(
                    {
                        "name": name,
                        "type": "line",
                        "data": line_data,
                        "symbol": "none",
                        "smooth": False,
                        "z": 8,
                        "technicalStructureKind": "trendline",
                        "technicalStructureStatus": line.get("status"),
                        "lineStyle": {
                            "color": "#111827",
                            "width": width + 0.35,
                            "type": "solid" if line.get("status") == "active" else "dashed",
                            "opacity": opacity,
                        },
                        "tooltip": {
                            "formatter": (
                                f"{tf_label}{role}<br/>{start_date} → {end_date}<br/>"
                                f"斜率 {float(line.get('slope_per_bar') or 0):.4f}/bar<br/>"
                                f"触碰 {int(line.get('touch_count') or 0)} 次 · 得分 {float(line.get('score') or 0):.1f}<br/>"
                                f"确认 {escape(str(line.get('confirmation_date') or '-'))} · 状态 {escape(str(line.get('status') or '-'))}"
                            )
                        },
                    }
                )

        if opts["show_channels"]:
            for index, channel in enumerate(data.get("channels") or []):
                if not _allowed(channel, opts):
                    continue
                for side, label in (("upper_line", "通道上轨"), ("lower_line", "通道下轨")):
                    line = channel.get(side) or {}
                    start_date, start_price, end_date, end_price = _line_points(line, data, date_axis)
                    line_data = _materialize_line(
                        date_axis, start_date, start_price, end_date, end_price
                    )
                    if len(line_data) < 2:
                        continue
                    series.append(
                        {
                            "name": f"结构·{tf_label}·{label}{index + 1}",
                            "type": "line",
                            "data": line_data,
                            "symbol": "none",
                            "smooth": False,
                            "z": 5,
                            "technicalStructureKind": "channel",
                            "technicalStructureStatus": channel.get("status"),
                            "lineStyle": {"color": "#475569", "width": width, "type": "dotted", "opacity": opacity * 0.75},
                            "tooltip": {"formatter": f"{tf_label}{label}<br/>得分 {float(channel.get('score') or 0):.1f}"},
                        }
                    )
        return series

    def build_multi_timeframe_series(
        self,
        results: dict[str, TechnicalStructureResult | dict[str, Any]],
        chart_timeframe: str,
        date_axis: list[str],
        options: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        overlays = {
            "1d": ["1d", "1w", "1mo"],
            "1w": ["1w", "1mo"],
            "1mo": ["1mo"],
        }.get(chart_timeframe, [chart_timeframe])
        series: list[dict[str, Any]] = []
        for timeframe in overlays:
            result = results.get(timeframe)
            if result is None:
                continue
            high_period = timeframe != chart_timeframe
            show_high_period_trendlines = bool((options or {}).get("show_high_period_trendlines", False))
            show_high_period_channels = bool((options or {}).get("show_high_period_channels", False))
            local_options = {
                **(options or {}),
                "high_score_only": high_period,
                "score_threshold": 60.0,
                # On a lower-period chart, high-period oblique lines distort
                # the visual structure and dominate the current swing. Keep
                # high-period horizontal levels by default; users can opt in
                # to higher-period trendlines/channels explicitly.
                "show_trendlines": not high_period or show_high_period_trendlines,
                "show_channels": (not high_period) or show_high_period_channels,
                "max_levels_per_role": 1 if high_period else 2,
                "max_lines_per_type": 1 if high_period else 2,
                "line_width": _TF_WIDTH.get(timeframe, 1.2),
                "opacity": 0.64 if high_period else 0.84,
            }
            series.extend(self.build_echarts_series(result, date_axis, local_options))
        return series

    def build_summary_html(self, result: TechnicalStructureResult | dict[str, Any]) -> str:
        data = _payload(result)
        context = data.get("current_context") or {}
        lines = context.get("summary_lines") or ["暂无有效技术结构"]
        adjustment = _ADJUSTMENT_LABEL.get(str(data.get("adjustment")), str(data.get("adjustment", "-")))
        flags = "、".join(str(item) for item in data.get("data_quality_flags") or []) or "无"
        return (
            f"<div class='technical-structure-summary'><strong>{escape(_TF_LABEL.get(str(data.get('timeframe')), str(data.get('timeframe'))))}技术结构</strong>"
            f"<span>{escape(adjustment)} · 截止 {escape(str(data.get('as_of_date', '-')))}</span>"
            + "".join(f"<p>{escape(str(line))}</p>" for line in lines)
            + f"<small>数据质量：{escape(flags)}</small></div>"
        )
