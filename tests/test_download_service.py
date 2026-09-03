import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from data.download_planner import DownloadPlanEstimate
from data.download_service import (
    download_symbols_parallel,
    format_download_plan_messages,
    normalize_symbol_csv,
    resolve_download_symbols,
)


class DownloadServiceTest(unittest.TestCase):
    def test_normalize_symbol_csv(self):
        self.assertEqual(
            normalize_symbol_csv(" 000001.sz,600519.SH ,, "),
            ["000001.SZ", "600519.SH"],
        )

    def test_failed_file_takes_priority(self):
        selection = resolve_download_symbols(
            symbol="000001.SZ",
            failed_file=Path("failed.csv"),
            load_symbols_from_file=lambda path: [f"FROM:{path}"],
            get_stock_list=lambda: [{"ts_code": "600519.SH"}],
        )

        self.assertEqual(selection.symbols, ["FROM:failed.csv"])
        self.assertEqual(selection.source, "failed_file")
        self.assertEqual(selection.source_detail, "failed.csv")
        self.assertFalse(selection.requires_confirm)

    def test_explicit_symbol_selection(self):
        selection = resolve_download_symbols(
            symbol="000001.sz, 600519.sh",
            failed_file=None,
            load_symbols_from_file=lambda _path: [],
            get_stock_list=lambda: [{"ts_code": "300750.SZ"}],
        )

        self.assertEqual(selection.symbols, ["000001.SZ", "600519.SH"])
        self.assertEqual(selection.source, "symbol")
        self.assertFalse(selection.requires_confirm)

    def test_all_stock_selection_requires_confirmation(self):
        selection = resolve_download_symbols(
            symbol=None,
            failed_file=None,
            load_symbols_from_file=lambda _path: [],
            get_stock_list=lambda: [
                {"ts_code": "000001.SZ"},
                {"ts_code": "600519.SH"},
                {"name": "missing code"},
            ],
        )

        self.assertEqual(selection.symbols, ["000001.SZ", "600519.SH"])
        self.assertEqual(selection.source, "all_stocks")
        self.assertTrue(selection.requires_confirm)

    def test_format_download_plan_messages_for_api_download(self):
        messages = format_download_plan_messages(
            DownloadPlanEstimate(
                total=10,
                cached_count=3,
                need_api=7,
                api_calls=14,
                effective_rpm=120,
                estimated_seconds=7.0,
            ),
            workers=5,
        )

        self.assertEqual(
            messages,
            [
                "  共 10 只 | 缓存命中 3 只 | 需下载 7 只 | 预计接口 14 次",
                "  并行线程: 5 | 有效API限速: 120次/分钟",
                "  ⏱ 预计约需 7 秒",
            ],
        )

    def test_format_download_plan_messages_for_long_download(self):
        messages = format_download_plan_messages(
            DownloadPlanEstimate(
                total=100,
                cached_count=0,
                need_api=100,
                api_calls=240,
                effective_rpm=120,
                estimated_seconds=120.0,
            ),
            workers=8,
        )

        self.assertEqual(messages[-1], "  ⏱ 预计约需 2 分钟 120 秒")

    def test_format_download_plan_messages_for_cache_hit(self):
        messages = format_download_plan_messages(
            DownloadPlanEstimate(
                total=2,
                cached_count=2,
                need_api=0,
                api_calls=0,
                effective_rpm=120,
                estimated_seconds=0.0,
            ),
            workers=5,
        )

        self.assertEqual(messages, ["  共 2 只 | 全部已缓存，直接从本地读取"])

    def test_download_symbols_parallel_records_results_and_failures(self):
        results = {}
        failed = {"600519.SH": "old error"}
        completed = []

        def download_one(symbol: str) -> pd.DataFrame:
            if symbol == "000002.SZ":
                raise RuntimeError("network error")
            return pd.DataFrame([{"symbol": symbol}])

        with patch("data.download_service.click.echo") as echo:
            download_symbols_parallel(
                ["000001.SZ", "000002.SZ", "600519.SH"],
                download_one=download_one,
                results=results,
                failed=failed,
                workers=2,
                cancel_event=threading.Event(),
                on_item_done=completed.append,
            )

        self.assertEqual(set(results), {"000001.SZ", "600519.SH"})
        self.assertEqual(failed, {"000002.SZ": "network error"})
        self.assertEqual(set(completed), {"000001.SZ", "000002.SZ", "600519.SH"})
        echo.assert_called_once()


if __name__ == "__main__":
    unittest.main()
