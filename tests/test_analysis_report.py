import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from analysis.report import build_analyze_page, build_compare_page


def _summary_frame(scale: float = 1.0) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "total_return_pct": 5.0 * scale,
                "sharpe_ratio": 1.2,
                "max_drawdown_pct": -3.0,
                "win_rate_pct": 60.0,
                "total_trades": 2,
                "annual_return_pct": 10.0 * scale,
                "annual_volatility_pct": 18.0,
                "excess_return_pct": 2.0 * scale,
                "information_ratio": 0.3,
            },
            {
                "symbol": "600519.SH",
                "total_return_pct": -2.0 * scale,
                "sharpe_ratio": -0.2,
                "max_drawdown_pct": -6.0,
                "win_rate_pct": 40.0,
                "total_trades": 1,
                "annual_return_pct": -4.0 * scale,
                "annual_volatility_pct": 22.0,
                "excess_return_pct": -1.0 * scale,
                "information_ratio": -0.1,
            },
        ]
    )


class AnalysisReportTest(unittest.TestCase):
    def test_build_analyze_page_uses_shared_html_shell(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            stack.enter_context(patch("analysis.report.render_charts", return_value=[]))
            for name in [
                "create_return_histogram",
                "create_risk_scatter",
                "create_sharpe_histogram",
                "create_trade_histogram",
            ]:
                stack.enter_context(patch(f"analysis.report.{name}", return_value=None))
            output_path = Path(tmp) / "analysis_rsi.html"

            build_analyze_page("rsi", _summary_frame(), output_path)

            html = output_path.read_text(encoding="utf-8")
            self.assertIn("<title>RSI — 策略统计分析</title>", html)
            self.assertIn("<h1><span>RSI</span> 策略画像</h1>", html)
            self.assertIn("../reports/000001.SZ_rsi.html", html)

    def test_build_compare_page_uses_shared_html_shell(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            stack.enter_context(patch("analysis.report.render_charts", return_value=[]))
            for name in [
                "create_radar_chart",
                "create_boxplot_comparison",
                "create_bar_comparison",
                "create_correlation_heatmap",
                "create_bubble_chart",
            ]:
                stack.enter_context(patch(f"analysis.report.{name}", return_value=None))
            output_path = Path(tmp) / "comparison.html"

            build_compare_page(
                {
                    "rsi": _summary_frame(),
                    "sma_cross": _summary_frame(scale=0.5),
                },
                output_path,
            )

            html = output_path.read_text(encoding="utf-8")
            self.assertIn("<title>策略对比分析</title>", html)
            self.assertIn("<h1><span>策略横向对比</span> 分析报告</h1>", html)
            self.assertIn('href="analysis_rsi.html"', html)


if __name__ == "__main__":
    unittest.main()
