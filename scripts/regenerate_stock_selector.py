"""Fast refresh for reports/stock_selector.html.

This keeps the existing embedded stock universe and only refreshes the
selector HTML template plus custom board JSON snapshot. It avoids the slower
full dashboard path that may inspect or generate thousands of K-line pages.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import load_project_config
from visual.dashboard import _build_stock_selector_html, _read_stock_selector_custom_boards, _rel


def main() -> int:
    config = load_project_config()
    reports_dir = Path(config["output"]["reports_dir"])
    selector_path = reports_dir / "stock_selector.html"
    if not selector_path.exists():
        raise FileNotFoundError(f"股票选择器 HTML 不存在: {selector_path}")

    html_text = selector_path.read_text(encoding="utf-8")
    match = re.search(
        r'<script type="application/json" id="stock-selector-data">(.*?)</script>',
        html_text,
        flags=re.S,
    )
    if not match:
        raise RuntimeError(f"没有找到 stock-selector-data: {selector_path}")

    selector = json.loads(match.group(1))
    data_cfg = config.get("data", {}) or {}
    dashboard_selector_cfg = ((config.get("dashboard", {}) or {}).get("stock_selector") or {})
    cache_dir = Path(data_cfg.get("cache_dir", "data/cache"))
    meta_dir = Path(data_cfg.get("meta_dir") or (cache_dir.parent / "meta"))
    custom_path = Path(
        dashboard_selector_cfg.get("custom_boards_path")
        or meta_dir / "stock_selector_custom_boards.json"
    ).expanduser()
    custom = _read_stock_selector_custom_boards(custom_path)

    selector.update(
        {
            "custom_boards_path": custom.get("path", ""),
            "custom_boards_exists": bool(custom.get("exists")),
            "custom_boards_error": custom.get("error", ""),
            "custom_boards": custom.get("boards", {}),
        }
    )
    selector_path.write_text(
        _build_stock_selector_html(selector, _rel(selector_path, reports_dir / "dashboard.html")),
        encoding="utf-8",
    )
    print(f"refreshed {selector_path}")
    print(f"custom boards {custom.get('path', '')}: {len(custom.get('boards', {}))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
