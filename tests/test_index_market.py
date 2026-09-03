import tempfile
import unittest
from pathlib import Path

import pandas as pd

from analysis.index_market import build_market_overview
from analysis.market_breadth import build_market_breadth, breadth_for_payload, breadth_indicator_payload
from visual.index_report import generate_index_report
from visual.market_report import generate_market_report


def _index_frame(base: float, step: float = 1.0, days: int = 130) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=days, freq="B")
    close = [base + i * step for i in range(days)]
    return pd.DataFrame(
        {
            "date": dates,
            "open": close,
            "high": [v + 1 for v in close],
            "low": [v - 1 for v in close],
            "close": close,
            "volume": [1000 + i for i in range(days)],
            "amount": [10000 + i for i in range(days)],
            "pct_chg": [0.0] + [step / close[i - 1] * 100 for i in range(1, days)],
        }
    )


class IndexMarketTest(unittest.TestCase):
    def test_build_market_breadth_counts_daily_up_down_flat(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            pd.DataFrame(
                [
                    {"date": "20260101", "close": 10},
                    {"date": "20260102", "close": 11},
                    {"date": "20260105", "close": 11},
                ]
            ).to_csv(cache_dir / "000001.SZ.csv", index=False)
            pd.DataFrame(
                [
                    {"date": "20260101", "close": 20},
                    {"date": "20260102", "close": 19},
                    {"date": "20260105", "close": 20},
                ]
            ).to_csv(cache_dir / "000002.SZ.csv", index=False)

            breadth = build_market_breadth(cache_dir, nhnl_lookback=3)

            self.assertEqual(
                breadth["2026-01-02"],
                {"up": 1, "down": 1, "flat": 0, "new_high": 0, "new_low": 0},
            )
            self.assertEqual(
                breadth["2026-01-05"],
                {"up": 1, "down": 0, "flat": 1, "new_high": 2, "new_low": 0},
            )
            self.assertEqual(
                breadth_for_payload(["2026-01-02", "2026-01-06"], breadth),
                [{"up": 1, "down": 1, "flat": 0}, None],
            )

    def test_market_overview_and_report_include_index_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = [
                ("000001.SH", "上证指数", _index_frame(3000, 2.0)),
                ("399006.SZ", "创业板指", _index_frame(2000, -1.0)),
            ]
            breadth = {
                "2026-06-30": {"up": 1, "down": 2, "flat": 0, "new_high": 0, "new_low": 1},
                "2026-07-01": {"up": 3, "down": 1, "flat": 1, "new_high": 2, "new_low": 1},
            }

            overview = build_market_overview(frames, breadth)
            self.assertEqual(overview["breadth"]["up"], 3)
            self.assertEqual(overview["breadth"]["ad"], 2)
            self.assertEqual(overview["breadth"]["ad_line"], 1)
            self.assertEqual(overview["breadth"]["nhnl"], 1)
            self.assertEqual(len(overview["rows"]), 2)
            self.assertEqual(overview["strongest"][0]["symbol"], "000001.SH")
            self.assertEqual(overview["weakest"][0]["symbol"], "399006.SZ")

            out_path = Path(tmp) / "market.html"
            grouped = {
                "全A": breadth_indicator_payload(["2026-06-30", "2026-07-01"], breadth),
                "沪深300": breadth_indicator_payload(["2026-06-30", "2026-07-01"], breadth),
            }
            generate_market_report(frames, out_path, breadth, breadth_groups=grouped)
            html = out_path.read_text(encoding="utf-8")
            self.assertIn("大盘环境分析", html)
            self.assertIn("上证指数", html)
            self.assertIn("market-sh-kline-chart", html)
            self.assertIn("上证指数 K线", html)
            self.assertIn("上涨家数", html)
            self.assertIn("A/D线", html)
            self.assertIn("NH-NL", html)
            self.assertIn("沪深300", html)
            self.assertIn('href="index/000001.SH_overview.html"', html)
            self.assertIn("趋势", html)

    def test_breadth_indicator_payload_includes_normalized_ad(self):
        payload = breadth_indicator_payload(
            ["2026-06-30", "2026-07-01"],
            {
                "2026-06-30": {"up": 3, "down": 1, "flat": 0, "new_high": 1, "new_low": 0},
                "2026-07-01": {"up": 1, "down": 2, "flat": 0, "new_high": 0, "new_low": 1},
            },
        )

        self.assertEqual(payload["ad"], [2, -1])
        self.assertEqual(payload["ad_norm"], [0.5, -0.3333])
        self.assertEqual(payload["ad_norm_line"], [0.5, 0.1667])
        self.assertEqual(payload["ad_norm_line_rebased"], [0.0, -0.3333])

    def test_index_report_payload_contains_breadth_for_kline_tooltip(self):
        with tempfile.TemporaryDirectory() as tmp:
            df = _index_frame(3000, 2.0, days=30)
            latest = df["date"].iloc[-1].strftime("%Y-%m-%d")
            out_path = Path(tmp) / "index.html"

            generate_index_report(
                df,
                symbol="000001.SH",
                name="上证指数",
                output_path=out_path,
                breadth_by_date={latest: {"up": 10, "down": 5, "flat": 2}},
                breadth_groups={
                    "全A": breadth_indicator_payload(
                        [latest],
                        {latest: {"up": 10, "down": 5, "flat": 2}},
                    ),
                    "沪深300": breadth_indicator_payload(
                        [latest],
                        {latest: {"up": 2, "down": 1, "flat": 0}},
                    ),
                },
            )

            html = out_path.read_text(encoding="utf-8")
            self.assertIn('"breadth"', html)
            self.assertIn('"up":10', html)
            self.assertIn("上涨 '+b.up+' 家", html)
            self.assertIn("panel-ad-daily", html)
            self.assertIn("panel-nhnl-daily", html)
            self.assertIn("起点归零A/D线", html)
            self.assertIn("沪深300", html)

            other_path = Path(tmp) / "other_index.html"
            generate_index_report(
                df,
                symbol="399006.SZ",
                name="创业板指",
                output_path=other_path,
                breadth_by_date={latest: {"up": 10, "down": 5, "flat": 2}},
            )
            other_html = other_path.read_text(encoding="utf-8")
            self.assertIn("上涨 '+b.up+' 家", other_html)
            self.assertNotIn("panel-ad-daily", other_html)
            self.assertNotIn("panel-nhnl-daily", other_html)


if __name__ == "__main__":
    unittest.main()
