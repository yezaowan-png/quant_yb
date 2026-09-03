"""HTML 统计报告组装 —— 亮色主题"""

from pathlib import Path
from typing import Optional

import pandas as pd

from analysis.analyzer import (
    _STRATEGY_LABELS,
    build_return_histogram,
    compute_stats,
    get_scatter_data,
    get_top_bottom,
    normalize_for_radar,
    compute_correlation_matrix,
)
from analysis.charts import (
    create_return_histogram,
    create_risk_scatter,
    create_sharpe_histogram,
    create_trade_histogram,
    create_radar_chart,
    create_boxplot_comparison,
    create_bar_comparison,
    create_correlation_heatmap,
    create_bubble_chart,
    render_charts,
)
from visual.components import html_document, inline_script, script_src

# ---- 亮色主题 CSS ----
_CSS = """* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
    background: #f0f2f5; color: #333; line-height: 1.6;
    -webkit-font-smoothing: antialiased;
}
.container { max-width: 1440px; margin: 0 auto; padding: 28px 24px; }

/* ---- Top Bar ---- */
.topbar {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 28px; padding-bottom: 16px;
    border-bottom: 1px solid #e0e0e8;
}
.topbar h1 {
    font-size: 24px; font-weight: 700; color: #1a1a2e;
    letter-spacing: .2px;
}
.topbar h1 span { color: #5470c6; }
.topbar .badge {
    font-size: 12px; color: #5470c6; background: #eef1fb;
    padding: 4px 14px; border-radius: 4px; font-weight: 600;
    letter-spacing: .5px;
}

/* ---- Stats Cards ---- */
.stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px; margin-bottom: 28px;
}
.stat-card {
    background: #fff; border-radius: 8px; padding: 18px 20px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.04);
    border: 1px solid #eaeaef;
    transition: box-shadow .2s, transform .2s;
}
.stat-card:hover {
    box-shadow: 0 3px 12px rgba(0,0,0,0.08);
    transform: translateY(-1px);
}
.stat-label {
    font-size: 11px; color: #999; text-transform: uppercase;
    letter-spacing: .8px; margin-bottom: 8px; font-weight: 600;
}
.stat-value {
    font-size: 24px; font-weight: 700; color: #1a1a2e;
    letter-spacing: -.3px;
}
.stat-value.up { color: #ef5350; }
.stat-value.down { color: #26a69a; }
.stat-value.neutral { color: #5470c6; }

/* ---- Chart Section ---- */
.chart-section {
    background: #fff; border-radius: 8px; padding: 20px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.04);
    border: 1px solid #eaeaef; margin-bottom: 18px;
}
.chart-section .chart-container { width: 100% !important; }

/* ---- Tables ---- */
.table-grid {
    display: grid; grid-template-columns: 1fr 1fr; gap: 18px;
    margin-bottom: 18px;
}
.table-card {
    background: #fff; border-radius: 8px; padding: 20px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.04);
    border: 1px solid #eaeaef;
}
.table-card h3 {
    font-size: 15px; font-weight: 700; color: #1a1a2e;
    margin-bottom: 14px; padding-bottom: 8px;
    border-bottom: 2px solid #eaeaef;
}
.table-card h3.top { border-bottom-color: #ef5350; color: #ef5350; }
.table-card h3.bottom { border-bottom-color: #26a69a; color: #26a69a; }

table { width: 100%; border-collapse: collapse; font-size: 13px; }
thead th {
    background: #f7f8fa; padding: 8px 10px; text-align: right;
    font-weight: 600; color: #666; font-size: 11px;
    text-transform: uppercase; letter-spacing: .4px;
    border-bottom: 1px solid #eaeaef;
}
thead th:first-child { text-align: left; }
tbody td {
    padding: 6px 10px; text-align: right;
    border-bottom: 1px solid #f5f5f8; color: #444;
    font-variant-numeric: tabular-nums; font-family: "SF Mono", "JetBrains Mono", monospace;
}
tbody td:first-child { text-align: left; color: #5470c6; font-weight: 500; }
.return-up { color: #ef5350; font-weight: 600; }
.return-down { color: #26a69a; font-weight: 600; }

th.sortable-th {
    cursor: pointer;
    user-select: none;
    position: relative;
    transition: background .15s;
}
th.sortable-th:hover { background: #e8eaef; }
th.sortable-th.asc::after {
    content: " ▲"; font-size: 9px; color: #ef5350;
}
th.sortable-th.desc::after {
    content: " ▼"; font-size: 9px; color: #26a69a;
}

/* ---- Links ---- */
.table-link {
    color: #5470c6; text-decoration: none; font-weight: 600;
    transition: color .15s;
}
.table-link:hover { color: #3b51a0; text-decoration: underline; }
.card-detail-link {
    display: inline-block; margin-top: 8px; font-size: 12px;
    color: #5470c6; text-decoration: none; font-weight: 500;
    transition: color .15s;
}
.card-detail-link:hover { color: #3b51a0; text-decoration: underline; }

/* ---- Footer ---- */
.footer {
    text-align: center; color: #bbb; font-size: 11px;
    padding: 32px 0 8px; letter-spacing: .4px;
}

/* ---- Animations ---- */
@keyframes fadeUp {
    from { opacity: 0; transform: translateY(12px); }
    to { opacity: 1; transform: translateY(0); }
}
.stat-card, .chart-section, .table-card {
    animation: fadeUp .4s ease both;
}
.stat-card:nth-child(1) { animation-delay: .02s; }
.stat-card:nth-child(2) { animation-delay: .05s; }
.stat-card:nth-child(3) { animation-delay: .08s; }
.stat-card:nth-child(4) { animation-delay: .11s; }
.stat-card:nth-child(5) { animation-delay: .14s; }
.stat-card:nth-child(6) { animation-delay: .17s; }

.full-list-section {
    background: #fff; border-radius: 8px; padding: 20px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.04);
    border: 1px solid #eaeaef; margin-bottom: 18px;
    overflow-x: auto; max-height: 600px; overflow-y: auto;
    animation: fadeUp .4s ease both;
}
.full-list-section h3 {
    font-size: 16px; font-weight: 700; color: #1a1a2e;
    margin-bottom: 14px; padding-bottom: 8px;
    border-bottom: 2px solid #5470c6;
}
.full-list-section thead { position: sticky; top: 0; z-index: 1; }

@media (max-width: 768px) {
    .table-grid { grid-template-columns: 1fr; }
    .container { padding: 12px; }
}
"""

_STRATEGY_NAMES = _STRATEGY_LABELS  # alias


def _build_stat_card(label: str, value: str, css_class: str = "neutral") -> str:
    return f'<div class="stat-card"><div class="stat-label">{label}</div><div class="stat-value {css_class}">{value}</div></div>'


def _build_table(title: str, rows: list[dict], css_class: str = "",
                 link_col: str = "", link_template: str = "") -> str:
    if not rows:
        return ""

    cols = list(rows[0].keys())
    header_cells = "".join(
        f'<th class="sortable-th" data-col="{i}">{c}</th>'
        for i, c in enumerate(cols)
    )
    header = f"<thead><tr>{header_cells}</tr></thead>"

    def _extract(raw_val):
        if isinstance(raw_val, (int, float)):
            return str(raw_val)
        if isinstance(raw_val, str):
            try:
                return str(float(raw_val.replace("%", "").replace("+", "").replace(",", "")))
            except ValueError:
                return raw_val
        return str(raw_val)

    body_rows = []
    for r in rows:
        cells = []
        for i, c in enumerate(cols):
            val = r[c]
            sort_val = _extract(val)

            if isinstance(val, float):
                s = f"{val:+.2f}" if "return" in c.lower() or "sharpe" in c.lower() else f"{val:.2f}"
            else:
                s = str(val)

            if link_col and link_template and c == link_col:
                href = link_template.format(val)
                s = f'<a class="table-link" href="{href}" target="_blank">{s}</a>'

            css = ""
            if c in ("total_return_pct", "return_pct"):
                css = ' class="return-up"' if isinstance(val, (int, float)) and val >= 0 else ' class="return-down"'
            cells.append(f'<td{css} data-sort="{sort_val}">{s}</td>')
        body_rows.append(f"<tr>{''.join(cells)}</tr>")

    h3_cls = f' class="{css_class}"' if css_class else ""
    return f"""<div class="table-card">
    <h3{h3_cls}>{title}</h3>
    <table>{header}<tbody>{"".join(body_rows)}</tbody></table>
</div>"""


# ============================================================
#  单策略分析页面
# ============================================================

def build_analyze_page(
    strategy_name: str,
    df: pd.DataFrame,
    output_path: Path,
) -> None:
    """生成单策略深度分析 HTML 报告。"""
    stats = compute_stats(df)
    display = _STRATEGY_NAMES.get(strategy_name, strategy_name)

    # 图表
    hist_data = build_return_histogram(df)
    scatter_data = get_scatter_data(df)
    top20, bottom20 = get_top_bottom(df, n=20)

    chart_objects = [
        create_return_histogram(hist_data, stats["avg_return"], stats["median_return"], strategy_name),
        create_risk_scatter(scatter_data, strategy_name),
        create_sharpe_histogram(df, strategy_name),
        create_trade_histogram(df, strategy_name),
    ]
    rendered = render_charts(chart_objects)
    echarts_src = rendered[0]["echarts_src"] if rendered else "https://assets.pyecharts.org/assets/v6/echarts.min.js"

    # 统计卡片
    cards = [
        _build_stat_card("分析股票数", str(stats["count"]), "neutral"),
        _build_stat_card("有交易股票", f"{stats['active_count']} ({stats['active_ratio']:.1f}%)", "neutral"),
        _build_stat_card("平均收益率", f"{stats['avg_return']:+.2f}%",
                         "up" if stats["avg_return"] >= 0 else "down"),
        _build_stat_card("平均年化收益", f"{stats['avg_annual_return']:+.2f}%",
                         "up" if stats["avg_annual_return"] >= 0 else "down"),
        _build_stat_card("交易股平均收益", f"{stats['avg_active_return']:+.2f}%",
                         "up" if stats["avg_active_return"] >= 0 else "down"),
        _build_stat_card("交易股平均年化", f"{stats['avg_active_annual_return']:+.2f}%",
                         "up" if stats["avg_active_annual_return"] >= 0 else "down"),
        _build_stat_card("平均年化波动", f"{stats['avg_annual_volatility']:.1f}%", "neutral"),
        _build_stat_card("平均超额收益", f"{stats['avg_excess_return']:+.1f}%",
                         "up" if stats["avg_excess_return"] >= 0 else "down"),
        _build_stat_card("平均信息比率", f"{stats['avg_information_ratio']:.3f}",
                         "up" if stats["avg_information_ratio"] >= 0 else "down"),
        _build_stat_card("中位数收益率", f"{stats['median_return']:+.1f}%",
                         "up" if stats["median_return"] >= 0 else "down"),
        _build_stat_card("正收益比例", f"{stats['positive_ratio']:.1f}%",
                         "up" if stats["positive_ratio"] >= 50 else "down"),
        _build_stat_card("平均夏普", f"{stats['avg_sharpe']:.3f}",
                         "up" if stats["avg_sharpe"] >= 0 else "down"),
        _build_stat_card("平均最大回撤", f"{stats['avg_max_dd']:.1f}%", "down"),
        _build_stat_card("平均胜率", f"{stats['avg_win_rate']:.1f}%",
                         "up" if stats["avg_win_rate"] >= 50 else "down"),
        _build_stat_card("平均交易次数", str(stats["avg_trades"]), "neutral"),
    ]

    # TABLE: relabel columns for display
    col_map = {
        "symbol": "股票代码", "total_return_pct": "收益率%",
        "sharpe_ratio": "夏普", "max_drawdown_pct": "最大回撤%",
        "win_rate_pct": "胜率%", "total_trades": "交易次数",
        "annual_return_pct": "年化收益%",
        "annual_volatility_pct": "年化波动%",
        "excess_return_pct": "超额收益%",
        "information_ratio": "信息比率",
    }
    def _relabel(rows):
        result = []
        for r in rows:
            nr = {}
            for k, v in r.items():
                nr[col_map.get(k, k)] = v
            result.append(nr)
        return result

    report_link_tpl = f"../reports/{{}}_{strategy_name}.html"
    top_table = _build_table("TOP 20 收益最高", _relabel(top20), "top",
                             link_col="股票代码", link_template=report_link_tpl)
    bottom_table = _build_table("BOTTOM 20 收益最低", _relabel(bottom20), "bottom",
                                link_col="股票代码", link_template=report_link_tpl)

    # 全部股票排名表
    all_cols = ["symbol", "total_return_pct", "sharpe_ratio", "max_drawdown_pct",
                "win_rate_pct", "total_trades"]
    for optional_col in ("annual_return_pct", "annual_volatility_pct", "excess_return_pct", "information_ratio"):
        if optional_col in df.columns:
            all_cols.append(optional_col)
    all_rows = df[all_cols].to_dict("records")
    full_table = _build_table(f"全部股票排名 ({len(all_rows)} 只)", _relabel(all_rows),
                              link_col="股票代码", link_template=report_link_tpl)

    # 收集所有图表 var 名
    all_vars = [c["var"] for c in rendered if c["var"]]
    vars_json = "[" + ", ".join(all_vars) + "]"

    body = f"""<div class="container">
    <div class="topbar">
        <h1><span>{display}</span> 策略画像</h1>
        <span class="badge">QuantYB Stats</span>
    </div>

    <div class="stats-grid">{"".join(cards)}</div>

    {_render_sections(rendered)}

    <div class="table-grid">{top_table}{bottom_table}</div>

    <div class="full-list-section">{full_table}</div>

    <div class="footer">QuantYB &copy; 2026 &nbsp;&middot;&nbsp; A-Share Quantitative Analysis</div>
</div>"""
    script = inline_script(f"""
(function() {{
    var allCharts = {vars_json};
    allCharts.forEach(function(c) {{ if (c) c.group = 'stats_group'; }});
    echarts.connect('stats_group');

    // ---- sortable table ----
    (function() {{
        var tables = document.querySelectorAll('table');
        tables.forEach(function(table) {{
            var headers = table.querySelectorAll('th.sortable-th');
            if (headers.length === 0) return;
            var tbody = table.querySelector('tbody');
            if (!tbody) return;
            var hlist = Array.from(headers);
            hlist.forEach(function(th) {{
                th.addEventListener('click', function() {{
                    var col = parseInt(this.getAttribute('data-col'));
                    var rows = Array.from(tbody.querySelectorAll('tr'));
                    var asc = this.classList.contains('asc');

                    hlist.forEach(function(h) {{ h.classList.remove('asc', 'desc'); }});
                    this.classList.add(asc ? 'desc' : 'asc');

                    rows.sort(function(a, b) {{
                        var va = a.children[col].getAttribute('data-sort') || '';
                        var vb = b.children[col].getAttribute('data-sort') || '';
                        var na = parseFloat(va), nb = parseFloat(vb);
                        if (!isNaN(na) && !isNaN(nb)) {{
                            return asc ? nb - na : na - nb;
                        }}
                        return asc ? vb.localeCompare(va) : va.localeCompare(vb);
                    }});
                    rows.forEach(function(row) {{ tbody.appendChild(row); }});
                }});
            }});
        }});
    }})();
}})();
""")
    html = html_document(
        title=f"{display} — 策略统计分析",
        body=body,
        styles=_CSS,
        head_extra=script_src(echarts_src),
        scripts=script,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")


# ============================================================
#  多策略对比页面
# ============================================================

def build_compare_page(
    data_map: dict[str, pd.DataFrame],
    output_path: Path,
) -> None:
    """生成多策略横向对比 HTML 报告。"""
    if len(data_map) < 2:
        return

    stats_map = {name: compute_stats(df) for name, df in data_map.items()}
    names = list(data_map.keys())

    # 策略对比摘要卡片
    cards: list[str] = []
    for i, name in enumerate(names):
        s = stats_map[name]
        color = ["#5470c6", "#fac858", "#ee6666", "#73c0de", "#9a7fd4", "#3ba272"][i % 6]
        display = _STRATEGY_NAMES.get(name, name)
        cards.append(f"""<div class="stat-card" style="border-left: 3px solid {color};">
<div class="stat-label">{display}</div>
<div class="stat-value {'up' if s['avg_return'] >= 0 else 'down'}" style="font-size:20px;">{s['avg_return']:+.1f}%</div>
<span style="font-size:11px;color:#999;">{s['active_count']}/{s['count']}只交易 | 交易股{s['avg_active_return']:+.2f}%</span>
<a class="card-detail-link" href="analysis_{name}.html" target="_blank">查看详情 →</a>
</div>""")

    # 图表
    normed = normalize_for_radar(stats_map)
    corr_df = compute_correlation_matrix(data_map) if len(data_map) >= 2 else pd.DataFrame()

    chart_objects = [
        create_radar_chart(stats_map, normed),
        create_boxplot_comparison(data_map),
        create_bar_comparison(data_map),
        create_correlation_heatmap(corr_df),
        create_bubble_chart(data_map),
    ]
    rendered = render_charts(chart_objects)
    echarts_src = rendered[0]["echarts_src"] if rendered else "https://assets.pyecharts.org/assets/v6/echarts.min.js"

    all_vars = [c["var"] for c in rendered if c["var"]]
    vars_json = "[" + ", ".join(all_vars) + "]"

    # 汇总对比表
    summary_rows = []
    for name in names:
        s = stats_map[name]
        summary_rows.append({
            "策略": _STRATEGY_NAMES.get(name, name),
            "_link_key": name,
            "股票数": s["count"],
            "有交易股票": s["active_count"],
            "平均收益%": f"{s['avg_return']:+.2f}",
            "平均年化%": f"{s['avg_annual_return']:+.2f}",
            "交易股平均%": f"{s['avg_active_return']:+.2f}",
            "交易股年化%": f"{s['avg_active_annual_return']:+.2f}",
            "平均年化波动%": f"{s['avg_annual_volatility']:.1f}",
            "平均超额%": f"{s['avg_excess_return']:+.1f}",
            "平均信息比率": f"{s['avg_information_ratio']:.3f}",
            "中位数收益%": f"{s['median_return']:+.1f}",
            "正向率%": f"{s['positive_ratio']:.1f}",
            "平均夏普": f"{s['avg_sharpe']:.3f}",
            "平均回撤%": f"{s['avg_max_dd']:.1f}",
            "平均胜率%": f"{s['avg_win_rate']:.1f}",
            "平均交易次数": str(s["avg_trades"]),
        })

    summary_table_html = _build_summary_table(summary_rows,
        link_col="策略", link_template="analysis_{}.html")

    compare_css = f"""{_CSS}
.compare-cards {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 12px; margin-bottom: 20px;
}}
.summary-section {{
    background: #fff; border-radius: 8px; padding: 20px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.04);
    border: 1px solid #eaeaef; margin-bottom: 18px;
    overflow-x: auto;
}}
.summary-section h3 {{
    font-size: 16px; font-weight: 700; color: #1a1a2e;
    margin-bottom: 14px;
}}
.summary-section table {{
    min-width: 800px;
}}
th.sortable-th {{
    cursor: pointer;
    user-select: none;
    position: relative;
    transition: background .15s;
}}
th.sortable-th:hover {{
    background: #e8eaef;
}}
th.sortable-th.asc::after {{
    content: " ▲";
    font-size: 9px;
    color: #ef5350;
}}
th.sortable-th.desc::after {{
    content: " ▼";
    font-size: 9px;
    color: #26a69a;
}}
"""
    body = f"""<div class="container">
    <div class="topbar">
        <h1><span>策略横向对比</span> 分析报告</h1>
        <span class="badge">{len(names)} 个策略 &middot; QuantYB</span>
    </div>

    <div class="compare-cards">{"".join(cards)}</div>

    <div class="summary-section">
        <h3>核心指标汇总</h3>
        {summary_table_html}
    </div>

    {_render_sections(rendered)}

    <div class="footer">QuantYB &copy; 2026 &nbsp;&middot;&nbsp; A-Share Quantitative Analysis</div>
</div>"""
    script = inline_script(f"""
(function() {{
    var allCharts = {vars_json};
    allCharts.forEach(function(c) {{ if (c) c.group = 'stats_group'; }});
    echarts.connect('stats_group');

    // ---- sortable table ----
    (function() {{
        var tables = document.querySelectorAll('table');
        tables.forEach(function(table) {{
            var headers = table.querySelectorAll('th.sortable-th');
            if (headers.length === 0) return;
            var tbody = table.querySelector('tbody');
            if (!tbody) return;
            var hlist = Array.from(headers);
            hlist.forEach(function(th) {{
                th.addEventListener('click', function() {{
                    var col = parseInt(this.getAttribute('data-col'));
                    var rows = Array.from(tbody.querySelectorAll('tr'));
                    var asc = this.classList.contains('asc');

                    hlist.forEach(function(h) {{ h.classList.remove('asc', 'desc'); }});
                    this.classList.add(asc ? 'desc' : 'asc');

                    rows.sort(function(a, b) {{
                        var va = a.children[col].getAttribute('data-sort') || '';
                        var vb = b.children[col].getAttribute('data-sort') || '';
                        var na = parseFloat(va), nb = parseFloat(vb);
                        if (!isNaN(na) && !isNaN(nb)) {{
                            return asc ? nb - na : na - nb;
                        }}
                        return asc ? vb.localeCompare(va) : va.localeCompare(vb);
                    }});
                    rows.forEach(function(row) {{ tbody.appendChild(row); }});
                }});
            }});
        }});
    }})();
}})();
""")
    html = html_document(
        title="策略对比分析",
        body=body,
        styles=compare_css,
        head_extra=script_src(echarts_src),
        scripts=script,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")


# ============================================================
#  Helpers
# ============================================================

def _render_sections(rendered: list[dict]) -> str:
    """将渲染后的图表列表转为 HTML sections。"""
    sections = []
    for c in rendered:
        sections.append(f"""<div class="chart-section">
    {c["div"]}
</div>
{c["script"]}""")
    return "\n".join(sections)


def _build_summary_table(rows: list[dict], link_col: str = "", link_template: str = "") -> str:
    if not rows:
        return ""
    cols = list(rows[0].keys())
    # filter out internal _link column from display
    display_cols = [c for c in cols if not c.startswith("_")]
    header = "<thead><tr>" + "".join(
        f'<th class="sortable-th" data-col="{i}">{c}</th>'
        for i, c in enumerate(display_cols)
    ) + "</tr></thead>"

    def _extract_sort(raw_val) -> str:
        """Extract a sortable value from raw cell data."""
        if isinstance(raw_val, (int, float)):
            return str(raw_val)
        if isinstance(raw_val, str):
            try:
                return str(float(raw_val.replace("%", "").replace("+", "").replace(",", "")))
            except ValueError:
                return raw_val
        return str(raw_val)

    body_rows = []
    for r in rows:
        cells = []
        for c in display_cols:
            raw_val = r[c]
            sort_val = _extract_sort(raw_val)

            display_val = raw_val
            if link_col and link_template and c == link_col:
                href = link_template.format(r.get("_link_key", display_val))
                display_val = f'<a class="table-link" href="{href}" target="_blank">{display_val}</a>'

            css = ""
            if isinstance(raw_val, str) and "%" in c and raw_val.startswith("+"):
                css = ' class="return-up"'
            elif isinstance(raw_val, str) and "%" in c and raw_val.startswith("-"):
                css = ' class="return-down"'
            cells.append(f'<td{css} data-sort="{sort_val}">{display_val}</td>')
        body_rows.append(f"<tr>{''.join(cells)}</tr>")
    return f"<table>{header}<tbody>{''.join(body_rows)}</tbody></table>"
