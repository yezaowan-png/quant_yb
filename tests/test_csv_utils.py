import tempfile
import unittest
from pathlib import Path

import pandas as pd

from data.csv_utils import read_csv_tail_records
from visual.dashboard import (
    _output_is_fresh,
    _read_stock_selector_cache_metrics,
    _read_stock_selector_daily_basic_metrics,
    _ths_section_cache_paths,
)


class CsvTailReaderTest(unittest.TestCase):
    def test_reads_only_requested_tail_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prices.csv"
            pd.DataFrame(
                [{"date": f"202601{day:02d}", "close": float(day)} for day in range(1, 21)]
            ).to_csv(path, index=False)

            rows = read_csv_tail_records(path, 3)

            self.assertEqual([row["date"] for row in rows], ["20260118", "20260119", "20260120"])

    def test_stock_selector_metrics_use_latest_cache_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            price_path = root / "000001.SZ.csv"
            pd.DataFrame(
                [
                    {"date": f"202601{day:02d}", "close": float(10 + day)}
                    for day in range(1, 21)
                ]
            ).to_csv(price_path, index=False)
            basic_path = root / "daily_basic.csv"
            pd.DataFrame(
                [
                    {"trade_date": "20260119", "total_mv": 100000.0},
                    {"trade_date": "20260120", "total_mv": 125000.0},
                ]
            ).to_csv(basic_path, index=False)

            metrics = _read_stock_selector_cache_metrics(price_path)
            basic = _read_stock_selector_daily_basic_metrics(basic_path)

            self.assertEqual(metrics["date"], "20260120")
            self.assertEqual(metrics["price"], 30.0)
            self.assertAlmostEqual(metrics["pct_chg"], (30.0 / 29.0 - 1.0) * 100.0, places=3)
            self.assertAlmostEqual(metrics["pct_5d"], (30.0 / 25.0 - 1.0) * 100.0, places=3)
            self.assertEqual(basic["market_cap"], 125000.0)

    def test_derived_output_freshness_uses_source_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.json"
            target = root / "report.html"
            source.write_text("{}", encoding="utf-8")
            target.write_text("report", encoding="utf-8")
            source.touch()

            self.assertFalse(_output_is_fresh(target, [source]))

            target.touch()
            self.assertTrue(_output_is_fresh(target, [source]))

    def test_ths_section_cache_paths_follow_include_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir = root / "cache"
            meta_dir = root / "meta"
            index_cache = cache_dir / "index"
            index_cache.mkdir(parents=True)
            meta_dir.mkdir(parents=True)
            pd.DataFrame(
                [
                    {"ts_code": "881001.TI", "name": "行业甲", "exchange": "A", "type": "I", "count": 5},
                    {"ts_code": "885001.TI", "name": "概念甲", "exchange": "A", "type": "N", "count": 5},
                    {"ts_code": "885002.TI", "name": "概念乙", "exchange": "A", "type": "N", "count": 5},
                ]
            ).to_csv(meta_dir / "ths_indices.csv", index=False)
            pd.DataFrame([{"ts_code": "885002.TI"}]).to_csv(meta_dir / "ths_concept_include.csv", index=False)
            for symbol in ["881001.TI", "885001.TI", "885002.TI"]:
                (index_cache / f"{symbol}.csv").write_text("date,close\n20260102,1\n", encoding="utf-8")

            config = {
                "data": {"cache_dir": str(cache_dir), "meta_dir": str(meta_dir)},
                "ths_indices": {
                    "industries": {"exchange": "A", "type": "I"},
                    "concepts": {"exchange": "A", "type": "N", "include_path": "ths_concept_include.csv"},
                },
            }

            self.assertEqual(
                [path.name for path in _ths_section_cache_paths(config, "industries")],
                ["881001.TI.csv"],
            )
            self.assertEqual(
                [path.name for path in _ths_section_cache_paths(config, "concepts")],
                ["885002.TI.csv"],
            )


if __name__ == "__main__":
    unittest.main()
