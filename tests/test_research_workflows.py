import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from analysis.limit_moves import save_limit_board
from analysis.limit_up_research import save_limit_up_research
from analysis.patterns import scan_bottom_pattern_break, scan_main_rise_wave, scan_needle_bottom_raise
from analysis.rotation import save_rotation
from analysis.rps import save_rps_top, save_rps_track
from data.stock_pool import (
    export_stock_pool,
    import_stock_pool,
    load_stock_pools,
    save_pool_from_result_csv,
)
from visual.dashboard import generate_dashboard


def _config(root: Path) -> dict:
    cache_dir = root / "cache"
    meta_dir = root / "meta"
    stats_dir = root / "output" / "statistics"
    reports_dir = root / "output" / "reports"
    trades_dir = root / "output" / "trades"
    signals_dir = root / "output" / "signals"
    for path in (cache_dir, meta_dir, stats_dir, reports_dir, trades_dir, signals_dir):
        path.mkdir(parents=True, exist_ok=True)
    pool_path = meta_dir / "stock_pools.json"
    pool_path.write_text(json.dumps({"pools": {}}, ensure_ascii=False), encoding="utf-8")
    pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "name": "甲"},
            {"ts_code": "000002.SZ", "name": "乙"},
            {"ts_code": "000003.SZ", "name": "丙"},
        ]
    ).to_csv(meta_dir / "stock_names.csv", index=False)
    return {
        "data": {"cache_dir": str(cache_dir), "meta_dir": str(meta_dir)},
        "stock_pool": {"path": str(pool_path)},
        "output": {
            "statistics_dir": str(stats_dir),
            "reports_dir": str(reports_dir),
            "trades_dir": str(trades_dir),
            "signals_dir": str(signals_dir),
        },
        "index_overview": {"indexes": []},
    }


def _write_kline(config: dict, symbol: str, closes: list[float]) -> None:
    rows = []
    for idx, close in enumerate(closes):
        rows.append(
            {
                "date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=idx),
                "open": close * 0.99,
                "high": close * 1.02,
                "low": close * 0.98,
                "close": close,
                "volume": 1000 + idx * 5,
            }
        )
    df = pd.DataFrame(rows)
    df["date"] = df["date"].dt.strftime("%Y%m%d")
    df.to_csv(Path(config["data"]["cache_dir"]) / f"{symbol}.csv", index=False)


class FakeLimitPro:
    def limit_list_d(self, trade_date, fields=None):
        return pd.DataFrame(
            [
                {
                    "trade_date": trade_date,
                    "ts_code": "000001.SZ",
                    "industry": "银行",
                    "name": "甲",
                    "close": 12.0,
                    "pct_chg": 10.0,
                    "turnover_ratio": 3.0,
                    "pe": 8.0,
                    "total_mv": 1000,
                    "float_mv": 800,
                    "fd_amount": 200,
                    "limit_times": 2,
                    "up_stat": "2连板",
                    "limit_type": "U",
                },
                {
                    "trade_date": trade_date,
                    "ts_code": "000002.SZ",
                    "industry": "地产",
                    "name": "乙",
                    "close": 8.0,
                    "pct_chg": -10.0,
                    "limit_type": "D",
                },
            ]
        )

    def limit_cpt_list(self, trade_date):
        return pd.DataFrame(
            [{"ts_code": "885001.TI", "name": "银行", "trade_date": trade_date, "up_nums": 1, "rank": "1"}]
        )


class FakeLimitResearchPro:
    def trade_cal(self, exchange, start_date, end_date, is_open=None, fields=None):
        return pd.DataFrame(
            [
                {"cal_date": "20260102", "is_open": 1},
                {"cal_date": "20260103", "is_open": 1},
            ]
        )

    def limit_list_d(self, trade_date, fields=None):
        rows = {
            "20260102": [
                {
                    "trade_date": trade_date,
                    "ts_code": "002837.SZ",
                    "industry": "专用设备",
                    "name": "英维克",
                    "close": 30.0,
                    "pct_chg": 10.0,
                    "turnover_ratio": 6.0,
                    "pe": 60.0,
                    "total_mv": 9000000,
                    "float_mv": 8000000,
                    "amount": 300000000,
                    "limit_times": 1,
                    "open_times": 0,
                    "limit": "U",
                },
                {
                    "trade_date": trade_date,
                    "ts_code": "002463.SZ",
                    "industry": "元件",
                    "name": "沪电股份",
                    "close": 50.0,
                    "pct_chg": 10.0,
                    "turnover_ratio": 4.0,
                    "pe": 38.0,
                    "total_mv": 28000000,
                    "float_mv": 26000000,
                    "amount": 500000000,
                    "limit_times": 1,
                    "open_times": 0,
                    "limit": "U",
                },
            ],
            "20260103": [
                {
                    "trade_date": trade_date,
                    "ts_code": "688525.SH",
                    "industry": "半导体",
                    "name": "佰维存储",
                    "close": 80.0,
                    "pct_chg": 20.0,
                    "turnover_ratio": 9.0,
                    "pe": 48.0,
                    "total_mv": 18000000,
                    "float_mv": 12000000,
                    "amount": 700000000,
                    "limit_times": 2,
                    "open_times": 1,
                    "limit": "U",
                },
                {
                    "trade_date": trade_date,
                    "ts_code": "600000.SH",
                    "industry": "银行",
                    "name": "浦发银行",
                    "close": 12.0,
                    "pct_chg": -10.0,
                    "limit": "D",
                },
            ],
        }
        return pd.DataFrame(rows.get(trade_date, []))

    def ths_member(self, ts_code):
        members = {
            "886044.TI": [{"ts_code": ts_code, "con_code": "002837.SZ", "con_name": "英维克"}],
            "885959.TI": [{"ts_code": ts_code, "con_code": "002463.SZ", "con_name": "沪电股份"}],
            "884092.TI": [{"ts_code": ts_code, "con_code": "002463.SZ", "con_name": "沪电股份"}],
            "886042.TI": [{"ts_code": ts_code, "con_code": "688525.SH", "con_name": "佰维存储"}],
        }
        return pd.DataFrame(members.get(ts_code, []))

    def fina_indicator(self, ts_code, start_date, end_date, fields=None):
        return pd.DataFrame(
            [
                {
                    "ts_code": ts_code,
                    "ann_date": "20260430",
                    "end_date": "20260331",
                    "roe": 12.0,
                    "or_yoy": 25.0,
                    "netprofit_yoy": 30.0,
                    "grossprofit_margin": 35.0,
                    "debt_to_assets": 45.0,
                }
            ]
        )


class ResearchWorkflowTest(unittest.TestCase):
    def test_rps_top_and_track_use_local_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(Path(tmp))
            _write_kline(config, "000001.SZ", list(range(10, 160)))
            _write_kline(config, "000002.SZ", [100 + i * 0.1 for i in range(150)])

            top = save_rps_top(config, window=20, top=2)
            track = save_rps_track(config, "000001.SZ", window=20)

            self.assertTrue(top.output_path.exists())
            self.assertTrue(top.html_path.exists())
            self.assertEqual(top.rows.iloc[0]["ts_code"], "000001.SZ")
            top_html = top.html_path.read_text(encoding="utf-8")
            self.assertIn('class="stock-link"', top_html)
            self.assertIn("../reports/stock_kline/000001.SZ.html", top_html)
            self.assertTrue(track.output_path.exists())
            self.assertGreater(len(track.rows), 0)

    def test_bottom_breakout_excludes_signal_day_from_box_base(self):
        hist = []
        for idx in range(25):
            close = 10.0 + (idx % 3) * 0.05
            hist.append({"date": f"202601{idx+1:02d}", "open": close, "high": 10.2, "low": 9.8, "close": close, "volume": 1000})
        hist.append({"date": "20260201", "open": 10.2, "high": 13.0, "low": 10.1, "close": 12.0, "volume": 2200})
        df = pd.DataFrame(hist)

        hit = scan_bottom_pattern_break(
            df,
            enable_double_bottom=False,
            enable_box_break=True,
            box_window=20,
            box_range_pct=0.08,
            ma_periods=(3, 5, 8),
            ma_bond_pct=0.03,
            break_pct=0.05,
        )

        self.assertIsNotNone(hit)
        self.assertAlmostEqual(hit["box_upper"], 10.2)
        self.assertIn("箱体突破", hit["reason"])

    def test_main_rise_wave_excludes_signal_day_from_history_high(self):
        rows = []
        for idx in range(32):
            close = 10.0 + (idx % 4) * 0.03
            rows.append({"date": f"202601{idx+1:02d}", "open": close, "high": 10.5, "low": 9.9, "close": close, "volume": 1000})
        rows.append({"date": "20260210", "open": 10.6, "high": 13.0, "low": 10.5, "close": 10.95, "volume": 1800})
        hit = scan_main_rise_wave(
            pd.DataFrame(rows),
            ma_periods=(3, 5, 8, 10),
            continue_days=3,
            high_lookback=20,
            trend_days=5,
            momentum_days=5,
            volume_days=3,
            high_upper=1.1,
        )

        self.assertIsNotNone(hit)
        self.assertAlmostEqual(hit["history_high"], 10.5)
        self.assertIn("历史高点", hit["reason"])

    def test_needle_bottom_uses_previous_needle_and_current_confirmation(self):
        rows = []
        for idx in range(15):
            rows.append({"date": f"202601{idx+1:02d}", "open": 10, "high": 10.5, "low": 9.8, "close": 10.1, "volume": 1000})
        rows[-3].update({"date": "20260113", "open": 10.5, "high": 10.8, "low": 9.0, "close": 10.4, "volume": 2500})
        rows.append({"date": "20260116", "open": 11.0, "high": 11.4, "low": 10.9, "close": 11.2, "volume": 1200})
        hit = scan_needle_bottom_raise(pd.DataFrame(rows), occur_range=10, bottom_pct=0.05, raise_pct=0.03, volume_mult=1.5)

        self.assertIsNotNone(hit)
        self.assertEqual(hit["needle_date"], "20260113")

    def test_stock_pool_import_export_and_result_to_pool(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(Path(tmp))
            source = Path(tmp) / "stocks.csv"
            source.write_text("ts_code,name\n000001,甲\n600519,茅台\n", encoding="utf-8")

            import_stock_pool(config, source, "导入池")
            pools = load_stock_pools(config["stock_pool"]["path"])
            self.assertEqual(pools["导入池"], ["000001.SZ", "600519.SH"])

            blk = Path(tmp) / "out.blk"
            export_stock_pool(config, "导入池", blk, output_format="blk")
            self.assertIn("0000001", blk.read_text(encoding="utf-8"))

            signals = Path(tmp) / "signals.csv"
            signals.write_text("ts_code,name\n000002.SZ,乙\n", encoding="utf-8")
            save_pool_from_result_csv(config, signals, "信号池")
            self.assertEqual(load_stock_pools(config["stock_pool"]["path"])["信号池"], ["000002.SZ"])

            qtyx = Path(tmp) / "trade_pool.json"
            qtyx.write_text(
                json.dumps(
                    {
                        "股票交易池": {
                            "璞泰来": {"code": "603659.SH", "percent": 12},
                            "恒华科技": {"code": "300365.SZ", "amount": 1000},
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            import_stock_pool(config, qtyx, "QTYX池", source_format="qtyx", source_pool="股票交易池")
            self.assertEqual(load_stock_pools(config["stock_pool"]["path"])["QTYX池"], ["603659.SH", "300365.SZ"])

            blk_source = Path(tmp) / "in.blk"
            blk_source.write_text("1600684\n0301398\n", encoding="utf-8")
            import_stock_pool(config, blk_source, "通达信池", source_format="blk")
            self.assertEqual(load_stock_pools(config["stock_pool"]["path"])["通达信池"], ["600684.SH", "301398.SZ"])

    def test_rotation_and_limit_board_outputs_feed_dashboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(Path(tmp))
            _write_kline(config, "000001.SZ", list(range(10, 80)))
            _write_kline(config, "000002.SZ", [20 + i * 0.05 for i in range(70)])

            rotation = save_rotation(config, model="momentum", hold_count=1, rebalance_days=5, momentum_window=10)
            three_factor = save_rotation(
                config,
                model="three_factor",
                hold_count=1,
                rebalance_days=5,
                momentum_window=10,
                trend_window=8,
                volume_short=3,
                volume_long=10,
            )
            limit = save_limit_board(config, "20260703", pro=FakeLimitPro(), save_pools=True)
            dashboard = generate_dashboard(config)
            dashboard_html = dashboard.read_text(encoding="utf-8")

            self.assertTrue(rotation.nav_path.exists())
            self.assertTrue(rotation.holdings_path.exists())
            self.assertTrue(three_factor.nav_path.exists())
            self.assertEqual(three_factor.summary["model"], "three_factor")
            self.assertTrue(limit.html_path.exists())
            self.assertIsNotNone(limit.pool_path)
            self.assertIn("信号中心", dashboard_html)
            self.assertIn("信号流", dashboard_html)
            self.assertIn("当天涨跌分布", dashboard_html)
            self.assertNotIn("成交额与市场状态", dashboard_html)
            self.assertIn("Research Desk", dashboard_html)
            self.assertIn("涨跌停", dashboard_html)
            self.assertIn("轮动研究", dashboard_html)
            self.assertIn('class="stock-link"', dashboard_html)
            self.assertIn("stock_kline/000001.SZ.html", dashboard_html)

    def test_limit_up_research_classifies_fine_themes_and_writes_pools(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(Path(tmp))

            result = save_limit_up_research(
                config,
                start="20260101",
                end="20260105",
                min_limit_count=1,
                fundamental_top=3,
                pro=FakeLimitResearchPro(),
            )

            themes = dict(zip(result.stock_summary["ts_code"], result.stock_summary["primary_theme"]))
            self.assertEqual(themes["002837.SZ"], "AI液冷温控")
            self.assertEqual(themes["002463.SZ"], "AI_PCB载板")
            self.assertEqual(themes["688525.SH"], "存储_HBM")
            self.assertTrue(result.report_path.exists())
            self.assertIn("AI液冷温控", result.report_path.read_text(encoding="utf-8"))

            pools = load_stock_pools(config["stock_pool"]["path"])
            self.assertIn("半年涨停_AI液冷温控_20260102_20260103", pools)
            self.assertIn("半年涨停_AI_PCB载板_20260102_20260103", pools)
            self.assertIn("半年涨停_存储_HBM_20260102_20260103", pools)


if __name__ == "__main__":
    unittest.main()
