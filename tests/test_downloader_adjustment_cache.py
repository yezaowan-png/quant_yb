import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from data.downloader import DataDownloader


def _config(tmp: str, adj: str = "qfq") -> dict:
    root = Path(tmp)
    return {
        "tushare": {"token": "test-token"},
        "data": {
            "cache_dir": str(root / "cache"),
            "meta_dir": str(root / "meta"),
            "stock_adj": adj,
        },
        "output": {
            "signals_dir": str(root / "signals"),
            "failed_downloads_dir": str(root / "failed"),
        },
        "rate_limit": {"calls_per_minute": 600, "failed_retry_rounds": 0},
        "parallel": {"download_workers": 1},
    }


def _cached_row(date: str, close: float, adj: str = "qfq", adj_factor: float = 1.0) -> dict:
    return {
        "date": pd.Timestamp(date),
        "open": close - 0.5,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": 1000,
        "adj": adj,
        "adj_factor": adj_factor,
    }


class DownloaderAdjustmentCacheTest(unittest.TestCase):
    def test_stock_cache_matches_adjustment_requires_current_adj(self):
        with tempfile.TemporaryDirectory() as tmp:
            downloader = DataDownloader(_config(tmp, adj="qfq"))

            qfq_cache = pd.DataFrame([_cached_row("2026-01-02", 10.0, adj="qfq")])
            raw_cache = pd.DataFrame([_cached_row("2026-01-02", 10.0, adj="raw")])
            legacy_cache = pd.DataFrame([{"date": pd.Timestamp("2026-01-02"), "close": 10.0}])

            self.assertTrue(downloader._stock_cache_matches_adjustment(qfq_cache))
            self.assertFalse(downloader._stock_cache_matches_adjustment(raw_cache))
            self.assertFalse(downloader._stock_cache_matches_adjustment(legacy_cache))

    def test_raw_mode_accepts_legacy_cache_without_adj_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            downloader = DataDownloader(_config(tmp, adj="raw"))
            legacy_cache = pd.DataFrame([{"date": pd.Timestamp("2026-01-02"), "close": 10.0}])

            self.assertTrue(downloader._stock_cache_matches_adjustment(legacy_cache))

    def test_datewise_groups_allow_new_symbols_to_regular_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            downloader = DataDownloader(_config(tmp, adj="qfq"))
            downloader._save_cache(
                "000001.SZ",
                pd.DataFrame(
                    [
                        _cached_row("2026-01-02", 10.0),
                        _cached_row("2026-01-03", 11.0),
                    ]
                ),
            )

            datewise, regular = downloader._datewise_stock_update_groups(
                ["000001.SZ", "000002.SZ"],
                "20260102",
                "20260105",
                force=False,
            )

            self.assertEqual(datewise, ["000001.SZ"])
            self.assertEqual(regular, ["000002.SZ"])

    def test_adjusted_tail_overlap_mismatch_refreshes_requested_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            downloader = DataDownloader(_config(tmp, adj="qfq"))
            cached = pd.DataFrame(
                [
                    _cached_row("2026-01-02", 10.0, adj_factor=1.0),
                    _cached_row("2026-01-03", 11.0, adj_factor=1.0),
                ]
            )
            downloader._save_cache("000001.SZ", cached)
            cached = downloader._load_cache("000001.SZ")

            calls: list[tuple[str, str, str]] = []

            def fake_fetch(symbol: str, start: str, end: str) -> pd.DataFrame:
                calls.append((symbol, start, end))
                if start == "20260103" and end == "20260104":
                    return pd.DataFrame(
                        [
                            _cached_row("2026-01-03", 99.0, adj_factor=1.1),
                            _cached_row("2026-01-04", 12.0, adj_factor=1.1),
                        ]
                    )
                return pd.DataFrame(
                    [
                        _cached_row("2026-01-02", 20.0, adj_factor=1.1),
                        _cached_row("2026-01-03", 21.0, adj_factor=1.1),
                        _cached_row("2026-01-04", 22.0, adj_factor=1.1),
                    ]
                )

            downloader._fetch_api_clean = fake_fetch  # type: ignore[method-assign]

            with patch("click.echo"):
                result = downloader._download_incremental("000001.SZ", cached, "20260102", "20260104")

            self.assertEqual(
                calls,
                [
                    ("000001.SZ", "20260103", "20260104"),
                    ("000001.SZ", "20260102", "20260104"),
                ],
            )
            self.assertEqual(result["close"].tolist(), [20.0, 21.0, 22.0])
            refreshed = downloader._load_cache("000001.SZ")
            self.assertEqual(refreshed["close"].tolist(), [20.0, 21.0, 22.0])


if __name__ == "__main__":
    unittest.main()
