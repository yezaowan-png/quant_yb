"""Small shared HTML helpers for report pages."""

from __future__ import annotations

import html
import json
import os
from pathlib import Path
from typing import Any

import numpy as np


DEFAULT_ECHARTS_CDN = "https://assets.pyecharts.org/assets/v6/echarts.min.js"


def script_src(src: str) -> str:
    return f'<script src="{html.escape(str(src), quote=True)}"></script>'


def inline_script(js: str) -> str:
    return f"<script>{js}</script>"


def safe_json(data: Any, allow_nan: bool = True) -> str:
    """Serialize JSON for embedding inside HTML script tags."""
    return json.dumps(data, ensure_ascii=False, allow_nan=allow_nan).replace("</", "<\\/")


class CompactJsonEncoder(json.JSONEncoder):
    """Serialize numpy values into compact report JSON."""

    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return None if np.isnan(obj) else round(float(obj), 6)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


def _normalize_compact_json_value(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else round(float(value), 6)
    if isinstance(value, np.ndarray):
        return [_normalize_compact_json_value(item) for item in value.tolist()]
    if isinstance(value, dict):
        return {key: _normalize_compact_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_compact_json_value(item) for item in value]
    return value


def to_compact_json(data: Any) -> str:
    """Serialize report payloads as compact JSON without JavaScript NaN values."""
    return json.dumps(
        _normalize_compact_json_value(data),
        ensure_ascii=False,
        separators=(",", ":"),
        cls=CompactJsonEncoder,
        allow_nan=False,
    )


def json_script_data(data: Any, element_id: str) -> str:
    safe_id = html.escape(str(element_id), quote=True)
    return f'<script type="application/json" id="{safe_id}">{safe_json(data)}</script>'


def relative_href(from_path: str | Path, target_path: str | Path) -> str:
    """Return a browser-friendly relative href from one generated file to another."""
    source = Path(from_path).resolve()
    target = Path(target_path).resolve()
    try:
        return target.relative_to(source.parent).as_posix()
    except ValueError:
        return Path(os.path.relpath(target, source.parent)).as_posix()


def stock_report_href(config: dict | None, from_path: str | Path, symbol: object) -> str:
    """Return the best local stock report href for a Tushare symbol.

    The canonical no-strategy stock page is the lightweight K-line page under
    ``stock_kline/{symbol}.html``.  Manual drawing is integrated there, so
    research dashboards should not route users to the old standalone
    ``{symbol}_trendlines.html`` page anymore.
    """
    code = str(symbol or "").strip().upper()
    if not code:
        return ""
    reports_dir = Path((config or {}).get("output", {}).get("reports_dir", "output/reports"))
    canonical = reports_dir / "stock_kline" / f"{code}.html"
    if canonical.exists():
        return relative_href(from_path, canonical)

    candidates = [
        path
        for path in reports_dir.glob(f"{code}_*.html")
        if path.name != "dashboard.html" and not path.name.endswith("_trendlines.html")
    ]
    if candidates:
        latest = max(candidates, key=lambda item: item.stat().st_mtime)
        cache_dir = Path((config or {}).get("data", {}).get("cache_dir", "data/cache"))
        cache_file = cache_dir / f"{code}.csv"
        if cache_file.exists() and latest.stat().st_mtime < cache_file.stat().st_mtime:
            return relative_href(from_path, canonical)
        return relative_href(from_path, latest)
    return relative_href(from_path, canonical)


def stock_link_html(
    config: dict | None,
    from_path: str | Path,
    symbol: object,
    label: object | None = None,
    class_name: str = "stock-link",
) -> str:
    """Render a stock code/link used by static dashboard tables."""
    text = str(label if label is not None else symbol or "")
    safe_text = html.escape(text)
    href = stock_report_href(config, from_path, symbol)
    if not href:
        return safe_text
    safe_href = html.escape(href, quote=True)
    safe_class = html.escape(class_name, quote=True)
    title = html.escape(f"打开个股页面: {str(symbol or '').strip().upper()}", quote=True)
    return f'<a class="{safe_class}" href="{safe_href}" target="_blank" title="{title}">{safe_text}</a>'


def echarts_script_tag(
    cdn: str = DEFAULT_ECHARTS_CDN,
    local_path: str | Path | None = None,
) -> str:
    """Return an ECharts script tag, preferring an inline local bundle when provided."""
    if local_path is not None:
        path = Path(local_path)
        if path.exists():
            js = path.read_text(encoding="utf-8", errors="ignore")
            return inline_script(js)
    return script_src(cdn)


def html_document(
    title: str,
    body: str,
    styles: str = "",
    head_extra: str = "",
    scripts: str = "",
    lang: str = "zh-CN",
) -> str:
    """Build a basic HTML document shell used by generated reports."""
    style_tag = f"<style>{styles}</style>" if styles else ""
    return f"""<!DOCTYPE html>
<html lang="{html.escape(lang, quote=True)}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(str(title))}</title>
{head_extra}
{style_tag}
</head>
<body>
{body}
{scripts}
</body>
</html>"""
