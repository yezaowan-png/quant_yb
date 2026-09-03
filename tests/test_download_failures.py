import tempfile
import unittest
from pathlib import Path

import pandas as pd

from data.download_failures import load_symbols_from_file, write_failure_snapshot


class DownloadFailuresTest(unittest.TestCase):
    def test_load_symbols_from_failure_csv_deduplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "failed.csv"
            pd.DataFrame(
                [
                    {"symbol": "000001.sz"},
                    {"symbol": "000001.SZ"},
                    {"symbol": "600519.SH"},
                ]
            ).to_csv(path, index=False)

            self.assertEqual(load_symbols_from_file(path), ["000001.SZ", "600519.SH"])

    def test_load_symbols_from_text_allows_commas_comments_and_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "failed.txt"
            path.write_text(
                "000001.sz, 600519.SH\n# comment\n300750.SZ\n",
                encoding="utf-8",
            )

            self.assertEqual(
                load_symbols_from_file(path),
                ["000001.SZ", "600519.SH", "300750.SZ"],
            )

    def test_load_symbols_from_csv_requires_symbol_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "failed.csv"
            pd.DataFrame([{"ts_code": "000001.SZ"}]).to_csv(path, index=False)

            with self.assertRaisesRegex(ValueError, "缺少 symbol 字段"):
                load_symbols_from_file(path)

    def test_write_failure_snapshot_keeps_contract_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_failure_snapshot(
                Path(tmp),
                {"600519.SH": "timeout", "000001.SZ": "频率超限"},
                "20260101",
                "20260131",
                "final",
                "qfq",
                "20260201_120000",
            )

            self.assertEqual(path.name, "download_failures_20260201_120000_final.csv")
            df = pd.read_csv(path, dtype=str)
            self.assertEqual(
                df.columns.tolist(),
                ["symbol", "start", "end", "adj", "stage", "error", "recorded_at"],
            )
            self.assertEqual(df["symbol"].tolist(), ["000001.SZ", "600519.SH"])
            self.assertEqual(df.loc[0, "adj"], "qfq")

    def test_write_failure_snapshot_returns_none_when_no_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(
                write_failure_snapshot(Path(tmp), {}, "20260101", "20260131", "final", "qfq", "run")
            )


if __name__ == "__main__":
    unittest.main()
