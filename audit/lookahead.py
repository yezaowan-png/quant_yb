"""Heuristic lookahead-bias audit for strategy source files."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from html import escape
from pathlib import Path
import re

import pandas as pd


@dataclass
class AuditFinding:
    severity: str
    file: str
    line: int
    check: str
    message: str
    snippet: str


_CHECKS: list[tuple[str, str, str, str]] = [
    (
        "positive_bar_index",
        r"\bdata\.(?:open|high|low|close|volume)\s*\[\s*[1-9]\d*\s*\]",
        "high",
        "发现 data.*[正数] 读取，Backtrader 中正向索引通常表示未来 bar。",
    ),
    (
        "negative_shift",
        r"\.shift\s*\(\s*-\d+",
        "high",
        "发现负向 shift，可能把未来数据移到当前行。",
    ),
    (
        "future_iloc",
        r"\.iloc\s*\[\s*i\s*\+\s*\d+",
        "high",
        "发现 iloc[i + n] 形态，循环中可能读取未来行。",
    ),
    (
        "strategy_reads_outputs",
        r"(output/|output\\\\|reports/|reports\\\\|statistics/|statistics\\\\|decisions/|decisions\\\\)",
        "medium",
        "策略或审计目标引用输出目录，需确认没有用报告/复盘结果反向影响信号。",
    ),
    (
        "current_bar_window",
        r"range\s*\(\s*0\s*,",
        "medium",
        "发现从 0 开始的历史窗口，需确认窗口没有把当前 bar 纳入历史基准。",
    ),
    (
        "full_sample_extrema",
        r"\.(?:max|min|mean|std)\s*\(\s*\)",
        "low",
        "发现聚合统计调用；若作用于完整 DataFrame，可能产生全样本信息泄露。",
    ),
]


def _strategy_paths(strategy: str | None = None, strategy_dir: Path | None = None) -> list[Path]:
    root = strategy_dir or Path(__file__).resolve().parents[1] / "strategy"
    if strategy:
        path = root / f"{strategy}.py"
        if not path.exists():
            raise FileNotFoundError(path)
        return [path]
    return sorted(p for p in root.glob("*.py") if p.stem not in {"__init__", "base"})


def audit_file(path: Path) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    text = path.read_text(encoding="utf-8")
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for check, pattern, severity, message in _CHECKS:
            if re.search(pattern, stripped):
                findings.append(
                    AuditFinding(
                        severity=severity,
                        file=str(path),
                        line=line_no,
                        check=check,
                        message=message,
                        snippet=stripped[:220],
                    )
                )

    if "buy_signal_dates" in text and "future_" in text:
        findings.append(
            AuditFinding(
                severity="high",
                file=str(path),
                line=1,
                check="signal_uses_future_returns",
                message="策略文件同时出现买点记录和 future_* 字段，请确认没有用未来收益生成信号。",
                snippet="buy_signal_dates + future_*",
            )
        )

    return findings


def run_lookahead_audit(
    strategy: str | None = None,
    output_dir: Path | str = "output/audit",
) -> tuple[pd.DataFrame, Path, Path]:
    """Run heuristic audit and write CSV + HTML reports."""
    paths = _strategy_paths(strategy)
    findings: list[AuditFinding] = []
    for path in paths:
        findings.extend(audit_file(path))

    rows = [asdict(f) for f in findings]
    df = pd.DataFrame(rows, columns=["severity", "file", "line", "check", "message", "snippet"])

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = strategy or "all"
    csv_path = out_dir / f"lookahead_audit_{suffix}.csv"
    html_path = out_dir / f"lookahead_audit_{suffix}.html"
    df.to_csv(csv_path, index=False)
    html_path.write_text(_render_html(df, strategy, paths), encoding="utf-8")
    return df, csv_path, html_path


def _render_html(df: pd.DataFrame, strategy: str | None, paths: list[Path]) -> str:
    title = f"Lookahead Audit: {strategy or 'all strategies'}"
    if df.empty:
        body = "<p class='ok'>未发现启发式规则命中的明显风险。</p>"
    else:
        rows = []
        for r in df.to_dict("records"):
            rows.append(
                "<tr>"
                f"<td class='{escape(str(r['severity']))}'>{escape(str(r['severity']))}</td>"
                f"<td>{escape(Path(str(r['file'])).name)}:{int(r['line'])}</td>"
                f"<td>{escape(str(r['check']))}</td>"
                f"<td>{escape(str(r['message']))}</td>"
                f"<td><code>{escape(str(r['snippet']))}</code></td>"
                "</tr>"
            )
        body = (
            "<table><thead><tr><th>Severity</th><th>File</th><th>Check</th>"
            "<th>Message</th><th>Snippet</th></tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table>"
        )
    files = ", ".join(escape(p.name) for p in paths)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{escape(title)}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; margin: 28px; color: #1f2933; }}
h1 {{ font-size: 24px; margin-bottom: 8px; }}
.meta {{ color: #667085; margin-bottom: 18px; }}
.ok {{ color: #0f766e; font-weight: 700; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ border: 1px solid #e5e7eb; padding: 8px; vertical-align: top; }}
th {{ background: #f8fafc; text-align: left; }}
td.high {{ color: #b42318; font-weight: 700; }}
td.medium {{ color: #b54708; font-weight: 700; }}
td.low {{ color: #175cd3; font-weight: 700; }}
code {{ white-space: pre-wrap; }}
</style>
</head>
<body>
<h1>{escape(title)}</h1>
<div class="meta">审计文件: {files}</div>
<div class="meta">说明: 第一版为启发式静态检查，命中项代表需要人工复核，不等于已经确认存在未来函数。</div>
{body}
</body>
</html>"""
