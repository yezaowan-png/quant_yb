import tempfile
import unittest
from pathlib import Path

import pandas as pd

from data.downloader import DataDownloader
from data.market_benchmark import MARKET_BENCHMARK_SYMBOL


def _config(tmp: str) -> dict:
    root = Path(tmp)
    return {
        "tushare": {"token": "test-token"},
        "data": {
            "cache_dir": str(root / "cache"),
            "meta_dir": str(root / "meta"),
            "stock_adj": "raw",
        },
        "output": {
            "signals_dir": str(root / "signals"),
            "failed_downloads_dir": str(root / "failed"),
        },
        "rate_limit": {"calls_per_minute": 600, "failed_retry_rounds": 0},
        "parallel": {"download_workers": 1},
    }


class DownloaderCacheMergeTest(unittest.TestCase):
    def test_average_price_local_index_is_built_from_stock_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _config(tmp)
            cache_dir = Path(cfg["data"]["cache_dir"])
            cache_dir.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(
                {
                    "date": ["20260701", "20260702"],
                    "open": [10.0, 11.0],
                    "high": [11.0, 12.0],
                    "low": [9.5, 10.5],
                    "close": [10.5, 11.5],
                    "volume": [100.0, 120.0],
                    "amount": [1000.0, 1320.0],
                }
            ).to_csv(cache_dir / "000001.SZ.csv", index=False)
            pd.DataFrame(
                {
                    "date": ["20260701", "20260702"],
                    "open": [20.0, 18.0],
                    "high": [21.0, 19.0],
                    "low": [19.5, 17.5],
                    "close": [20.5, 18.5],
                    "volume": [200.0, 220.0],
                    "amount": [4000.0, 4070.0],
                }
            ).to_csv(cache_dir / "000002.SZ.csv", index=False)

            downloader = DataDownloader(cfg)
            result = downloader.download_index(MARKET_BENCHMARK_SYMBOL, "20260701", "20260702", force=True)

            self.assertEqual(result["ts_code"].unique().tolist(), [MARKET_BENCHMARK_SYMBOL])
            self.assertAlmostEqual(result.loc[0, "close"], 15.5)
            self.assertAlmostEqual(result.loc[1, "close"], 15.0)
            cached = downloader.load_index_cache(MARKET_BENCHMARK_SYMBOL)
            self.assertIsNotNone(cached)
            self.assertEqual(cached.loc[0, "date"].strftime("%Y%m%d"), "20260701")

    def test_ti_index_uses_ths_daily_and_shared_index_cache_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            downloader = DataDownloader(_config(tmp))
            calls = []
            raw = pd.DataFrame(
                [
                    {
                        "ts_code": "700082.TI",
                        "trade_date": "20260713",
                        "open": 15607.216,
                        "high": 15633.529,
                        "low": 15009.296,
                        "close": 15048.958,
                        "pre_close": 15687.729,
                        "change": -638.771,
                        "pct_change": -4.0718,
                        "vol": 1329356000,
                        "amount": 1930000000,
                        "turnover_rate": 1.827292,
                    }
                ]
            )

            def fake_call(symbol, api_name, call):
                calls.append((symbol, api_name))
                return raw

            downloader.tushare_client.call_primary = fake_call
            result = downloader._fetch_index_from_api("700082.TI", "20260701", "20260714")

            self.assertEqual(calls, [("700082.TI", "ths_daily")])
            self.assertEqual(result.loc[0, "ts_code"], "700082.TI")
            self.assertAlmostEqual(result.loc[0, "pct_chg"], -4.0718)
            self.assertAlmostEqual(result.loc[0, "amount"], 1930000000)
            cached = downloader.load_index_cache("700082.TI")
            self.assertEqual(cached.loc[0, "date"].strftime("%Y%m%d"), "20260713")
            self.assertAlmostEqual(cached.loc[0, "amount"], 1930000000)

    def test_ths_index_list_is_cached_under_meta_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            downloader = DataDownloader(_config(tmp))
            calls = []
            raw = pd.DataFrame(
                [
                    {"ts_code": "881155.TI", "name": "银行", "count": 42, "exchange": "A", "type": "I"},
                    {"ts_code": "700030.TI", "name": "同花顺小盘", "count": None, "exchange": "A", "type": "N"},
                ]
            )

            def fake_call(symbol, api_name, call):
                calls.append((symbol, api_name))
                return raw

            downloader.tushare_client.call_primary = fake_call
            result = downloader.download_ths_index_list(exchange="A", force=True)
            self.assertEqual(calls, [("THS_INDEX_LIST", "ths_index")])
            self.assertTrue(downloader._ths_index_list_path().exists())
            self.assertEqual(result["ts_code"].tolist(), ["700030.TI", "881155.TI"])

            downloader.tushare_client.call_primary = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should use cache"))
            cached = downloader.download_ths_index_list(exchange="A", force=False)
            self.assertEqual(cached["ts_code"].tolist(), ["700030.TI", "881155.TI"])

    def test_save_cache_merges_incremental_rows_and_keeps_latest_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            downloader = DataDownloader(_config(tmp))
            downloader._save_cache(
                "000001.SZ",
                pd.DataFrame(
                    [
                        {
                            "date": pd.Timestamp("2026-01-02"),
                            "open": 10.0,
                            "high": 11.0,
                            "low": 9.0,
                            "close": 10.5,
                            "volume": 1000,
                            "adj": "raw",
                        },
                        {
                            "date": pd.Timestamp("2026-01-03"),
                            "open": 11.0,
                            "high": 12.0,
                            "low": 10.0,
                            "close": 11.5,
                            "volume": 1100,
                            "adj": "raw",
                        },
                    ]
                ),
            )

            downloader._save_cache(
                "000001.SZ",
                pd.DataFrame(
                    [
                        {
                            "date": pd.Timestamp("2026-01-03"),
                            "open": 99.0,
                            "high": 100.0,
                            "low": 98.0,
                            "close": 99.5,
                            "volume": 9900,
                            "adj": "raw",
                        },
                        {
                            "date": pd.Timestamp("2026-01-04"),
                            "open": 12.0,
                            "high": 13.0,
                            "low": 11.0,
                            "close": 12.5,
                            "volume": 1200,
                            "adj": "raw",
                        },
                    ]
                ),
            )

            loaded = downloader._load_cache("000001.SZ")

            self.assertEqual(
                loaded["date"].dt.strftime("%Y%m%d").tolist(),
                ["20260102", "20260103", "20260104"],
            )
            overlap = loaded.loc[loaded["date"] == pd.Timestamp("2026-01-03")].iloc[0]
            self.assertEqual(overlap["open"], 99.0)
            self.assertEqual(overlap["volume"], 9900)


if __name__ == "__main__":
    unittest.main()
