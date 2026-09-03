import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from analysis.screener import save_screen, screen_stocks
from data.stock_pool import load_stock_pools
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


def _pullback_frame(extra_broken_bars: int = 0) -> pd.DataFrame:
    low_pivots = {5, 15, 25, 35, 45, 55}
    high_pivots = {10, 20, 30, 40, 50}
    rows = []
    for idx in range(65):
        base = 10.0 + idx * 0.08
        if idx >= 62:
            low = base + 0.04
            high = base + 1.0
            close = base + 0.12
        else:
            low = base if idx in low_pivots else base + 0.7
            high = base + 2.8 if idx in high_pivots else low + 1.1
            close = (high + low) / 2.0
        rows.append(
            {
                "date": (pd.Timestamp("2026-01-01") + pd.Timedelta(days=idx)).strftime("%Y%m%d"),
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1000 + idx,
            }
        )
    for offset in range(extra_broken_bars):
        idx = 65 + offset
        base = 10.0 + idx * 0.08
        close = base * 0.92
        rows.append(
            {
                "date": (pd.Timestamp("2026-01-01") + pd.Timedelta(days=idx)).strftime("%Y%m%d"),
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": 1000 + idx,
            }
        )
    return pd.DataFrame(rows)


def _broken_frame() -> pd.DataFrame:
    df = _pullback_frame()
    idx = len(df) - 1
    base = 10.0 + idx * 0.08
    close = base * 0.92
    df.loc[idx, ["open", "high", "low", "close"]] = [close, close * 1.01, close * 0.99, close]
    return df


def _write_kline(config: dict, symbol: str, df: pd.DataFrame) -> None:
    df.to_csv(Path(config["data"]["cache_dir"]) / f"{symbol}.csv", index=False)


class ScreenerTest(unittest.TestCase):
    def test_trendline_pullback_hits_recent_touch(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(Path(tmp))
            _write_kline(config, "000001.SZ", _pullback_frame())

            rows = screen_stocks(
                config,
                symbols=["000001.SZ"],
                pivot_window=2,
                max_distance_pct=1.5,
                touch_days=3,
            )

            self.assertEqual(len(rows), 1)
            row = rows.iloc[0]
            self.assertEqual(row["ts_code"], "000001.SZ")
            self.assertEqual(row["preset"], "trendline_pullback")
            self.assertGreater(float(row["score"]), 0)
            self.assertLessEqual(abs(float(row["touch_distance_pct"])), 1.5)
            self.assertIn("上升趋势线有效", row["reason"])

    def test_trendline_pullback_rejects_effective_break(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(Path(tmp))
            _write_kline(config, "000001.SZ", _broken_frame())

            rows = screen_stocks(
                config,
                symbols=["000001.SZ"],
                pivot_window=2,
                max_distance_pct=1.5,
                break_pct=1.0,
            )

            self.assertTrue(rows.empty)

    def test_pool_intersection_limits_screen_universe(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(Path(tmp))
            _write_kline(config, "000001.SZ", _pullback_frame())
            _write_kline(config, "000002.SZ", _pullback_frame())
            pool_path = Path(config["stock_pool"]["path"])
            pool_path.write_text(
                json.dumps(
                    {
                        "pools": {
                            "机器人": {"stocks": [{"ts_code": "000001.SZ", "name": "甲"}]},
                            "AI": {
                                "stocks": [
                                    {"ts_code": "000001.SZ", "name": "甲"},
                                    {"ts_code": "000002.SZ", "name": "乙"},
                                ]
                            },
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            rows = screen_stocks(
                config,
                pool="机器人,AI",
                pool_mode="all",
                pivot_window=2,
                max_distance_pct=1.5,
            )

            self.assertEqual(list(rows["ts_code"]), ["000001.SZ"])
            self.assertEqual(rows.iloc[0]["matched_pool"], "机器人,AI")

    def test_trade_date_slices_out_future_bars(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(Path(tmp))
            df = _pullback_frame(extra_broken_bars=5)
            target_date = str(df["date"].iloc[64])
            _write_kline(config, "000001.SZ", df)

            rows = screen_stocks(
                config,
                symbols=["000001.SZ"],
                trade_date=target_date,
                pivot_window=2,
                max_distance_pct=1.5,
            )

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows.iloc[0]["signal_date"], target_date)

    def test_save_screen_outputs_files_pool_and_dashboard_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(Path(tmp))
            _write_kline(config, "000001.SZ", _pullback_frame())

            result = save_screen(
                config,
                symbols=["000001.SZ"],
                pivot_window=2,
                max_distance_pct=1.5,
                save_pool=True,
                pool_name="趋势线回踩池",
            )
            dashboard = generate_dashboard(config)
            dashboard_html = dashboard.read_text(encoding="utf-8")

            self.assertTrue(result.output_path.exists())
            self.assertTrue(result.html_path.exists())
            screen_html = result.html_path.read_text(encoding="utf-8")
            self.assertIn('class="stock-link"', screen_html)
            self.assertIn("../reports/stock_kline/000001.SZ.html", screen_html)
            self.assertIn("distance_pct", result.rows.columns)
            pools = load_stock_pools(config["stock_pool"]["path"])
            self.assertEqual(pools["趋势线回踩池"], ["000001.SZ"])
            self.assertIn("选股筛选", dashboard_html)
            self.assertIn("趋势线回踩", dashboard_html)


if __name__ == "__main__":
    unittest.main()
