import tempfile
import unittest
from pathlib import Path

import pandas as pd

from data.cache_store import CsvCacheStore


class CsvCacheStoreTest(unittest.TestCase):
    def test_price_cache_roundtrip_deduplicates_and_sorts(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CsvCacheStore(Path(tmp) / "cache")
            path = store.stock_cache_path("000001.SZ")

            df = pd.DataFrame(
                [
                    {"date": pd.Timestamp("2026-01-03"), "open": 3, "close": 3},
                    {"date": pd.Timestamp("2026-01-02"), "open": 2, "close": 2},
                    {"date": pd.Timestamp("2026-01-02"), "open": 9, "close": 9},
                ]
            )
            store.save_price_cache(path, df)

            raw = path.read_text(encoding="utf-8")
            self.assertIn("20260102", raw)
            loaded = store.load_stock_cache("000001.SZ")

            self.assertEqual(loaded["date"].dt.strftime("%Y%m%d").tolist(), ["20260102", "20260103"])
            self.assertEqual(loaded.loc[0, "open"], 9)

    def test_index_cache_reads_legacy_root_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CsvCacheStore(Path(tmp) / "cache")
            legacy = store.stock_cache_path("000001.SH")
            pd.DataFrame(
                [{"date": "20260102", "ts_code": "000001.SH", "open": 1, "close": 2}]
            ).to_csv(legacy, index=False)

            loaded = store.load_index_cache("000001.SH")

            self.assertEqual(loaded.loc[0, "ts_code"], "000001.SH")
            self.assertEqual(loaded.loc[0, "date"].strftime("%Y%m%d"), "20260102")

    def test_daily_basic_split_deduplicates_by_symbol(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CsvCacheStore(Path(tmp) / "cache")
            first = pd.DataFrame(
                [
                    {"ts_code": "000001.SZ", "trade_date": "20260102", "close": 10},
                    {"ts_code": "000002.SZ", "trade_date": "20260102", "close": 20},
                ]
            )
            second = pd.DataFrame(
                [{"ts_code": "000001.SZ", "trade_date": "20260102", "close": 11}]
            )

            self.assertEqual(store.save_daily_basic_by_symbol(first), 2)
            self.assertEqual(store.save_daily_basic_by_symbol(second), 1)

            loaded = store.load_daily_basic("000001.SZ")
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded.loc[0, "close"], 11)
            self.assertEqual(store.daily_basic_cached_dates(), {"20260102"})

    def test_kline_checked_dates_keep_latest_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CsvCacheStore(Path(tmp) / "cache")

            store.record_kline_checked_date("20260102", rows=1, target_symbols=2)
            store.record_kline_checked_date("20260102", rows=3, target_symbols=4)

            self.assertEqual(store.load_kline_checked_dates(), {"20260102"})
            df = pd.read_csv(store.kline_checked_dates_path(), dtype={"trade_date": str})
            self.assertEqual(len(df), 1)
            self.assertEqual(df.loc[0, "rows"], 3)


if __name__ == "__main__":
    unittest.main()
