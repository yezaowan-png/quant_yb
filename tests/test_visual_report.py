import unittest

from visual.report import _build_page


class VisualReportTest(unittest.TestCase):
    def test_build_page_uses_shared_html_shell_and_keeps_data_script(self):
        html = _build_page(
            symbol="000001.SZ",
            strategy_name="rsi",
            stats={
                "total_trades": 1,
                "win_rate": 100,
                "total_pnl": 12.3,
                "max_drawdown": -2.0,
                "total_return": 1.2,
                "annual_return": 3.4,
                "sharpe": 0.5,
            },
            period_data_json='{"daily":{}}',
            equity_data_json="null",
        )

        self.assertIn("<title>000001.SZ · RSI</title>", html)
        self.assertIn("<h1><span>000001.SZ</span> 回测报告</h1>", html)
        self.assertIn('<script src="https://assets.pyecharts.org/assets/v6/echarts.min.js"></script>', html)
        self.assertIn('<script>window._D={"daily":{}};window._E=null;</script>', html)
        self.assertIn("A-Share Quantitative Backtesting System", html)


if __name__ == "__main__":
    unittest.main()
