import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.limit_strength import (
    DEFAULT_OUTPUT_COLUMNS,
    build_limit_strength,
    build_limit_candidates,
    load_limit_records,
    score_daily_frame,
)
from visual.dashboard import generate_dashboard


class LimitStrengthTest(unittest.TestCase):
    def test_build_limit_strength_from_local_database_with_change_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "uplim"
            output_dir = root / "out"
            data_dir.mkdir()
            output_dir.mkdir()
            self._write_limit_csv(
                data_dir / "每日涨停个股明细-20260110.csv",
                [
                    {"股票名称": "甲科技", "股票代码": "000001.SZ", "所属行业": "机器人", "涨停原因类别": "机器人+AI"},
                    {"股票名称": "乙酒业", "股票代码": "000002.SZ", "所属行业": "白酒", "涨停原因类别": "白酒"},
                    {"股票名称": "ST坏样本", "股票代码": "000003.SZ", "所属行业": "其他", "涨停原因类别": "机器人"},
                    {"股票名称": "北交样本", "股票代码": "830001.BJ", "所属行业": "其他", "涨停原因类别": "AI"},
                ],
            )
            self._write_limit_csv(
                data_dir / "每日涨停个股明细-20260109.csv",
                [
                    {"股票名称": "甲科技", "股票代码": "000001.SZ", "所属行业": "机器人", "涨停原因类别": "机器人+AI"},
                    {"股票名称": "乙酒业", "股票代码": "000002.SZ", "所属行业": "白酒", "涨停原因类别": "白酒"},
                ],
            )
            pd.DataFrame(
                [
                    {
                        "股票名称": "旧股票",
                        "股票代码": "000004.SZ",
                        "所属行业": "旧行业",
                        "涨停题材": "机器人",
                        "近期涨停数": 2,
                        "综合评分": 10,
                        "均线多头分": 0,
                        "突破前高分": 0,
                        "动量分": 0,
                        "成交量分": 0,
                        "所属题材": "机器人",
                        "新增/剔除状态": "保留",
                    }
                ]
            ).to_csv(output_dir / "每日强势股结果.csv", index=False, encoding="utf-8-sig")

            config = {
                "limit_strength": {
                    "data_path": str(data_dir),
                    "output_dir": str(output_dir),
                    "back_days": 10,
                    "min_limit_count": 2,
                    "focus_themes": ["机器人", "AI"],
                }
            }

            seen_as_of = []

            def fetcher(symbol, settings, as_of):
                seen_as_of.append(as_of)
                return self._daily_frame()

            result = build_limit_strength(config, price_fetcher=fetcher)

            self.assertEqual(result.loaded_dates, ["20260110", "20260109"])
            self.assertEqual(set(result.records["股票代码"]), {"000001.SZ", "000002.SZ"})
            self.assertEqual(set(result.candidates["股票代码"]), {"000001.SZ", "000002.SZ"})
            self.assertEqual(result.result["股票代码"].tolist(), ["000001.SZ"])
            row = result.result.iloc[0]
            self.assertEqual(row["近期涨停数"], 2)
            self.assertEqual(row["所属题材"], "机器人、AI")
            self.assertEqual(row["新增/剔除状态"], "新增")
            self.assertGreater(row["综合评分"], 0)
            self.assertTrue(result.result_path.exists())
            self.assertTrue(result.latest_path.exists())
            self.assertTrue(result.html_path.exists())
            self.assertEqual(list(result.result.columns), DEFAULT_OUTPUT_COLUMNS)
            self.assertIn("剔除", set(result.changes["新增/剔除状态"]))
            self.assertEqual(set(seen_as_of), {"20260110"})

            dashboard_config = {
                **config,
                "data": {"cache_dir": str(root / "cache"), "meta_dir": str(root / "meta")},
                "output": {
                    "statistics_dir": str(root / "stats"),
                    "reports_dir": str(root / "reports"),
                    "trades_dir": str(root / "trades"),
                    "signals_dir": str(root / "signals"),
                },
                "index_overview": {"indexes": []},
            }
            for key in ("cache", "meta", "stats", "reports", "trades", "signals"):
                (root / key).mkdir(exist_ok=True)
            dashboard_config["limit_strength"]["output_dir"] = str(root / "stats" / "limit_strength")
            build_limit_strength(dashboard_config, price_fetcher=lambda symbol, settings, as_of: self._daily_frame())
            dashboard = generate_dashboard(dashboard_config).read_text(encoding="utf-8")
            self.assertIn("涨停强势", dashboard)
            self.assertIn("limit_strength_", dashboard)

    def test_score_daily_frame_returns_component_scores(self):
        scores = score_daily_frame(self._daily_frame(), self._settings())
        self.assertGreater(scores["综合评分"], 0)
        self.assertGreater(scores["突破前高分"], 0)
        self.assertGreater(scores["动量分"], 0)
        self.assertGreater(scores["成交量分"], 0)

    def test_load_records_and_candidates_handle_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings(data_path=Path(tmp))
            records, dates = load_limit_records(settings)
            candidates = build_limit_candidates(records, settings.min_limit_count)
            self.assertEqual(dates, [])
            self.assertTrue(records.empty)
            self.assertTrue(candidates.empty)

    def _write_limit_csv(self, path: Path, rows: list[dict]):
        pd.DataFrame(rows).to_csv(path, index=False, encoding="GBK")

    def _daily_frame(self) -> pd.DataFrame:
        close = np.linspace(10, 20, 280)
        volume = np.concatenate([np.full(250, 1000), np.full(20, 1200), np.full(10, 3200)])
        return pd.DataFrame({"close": close, "high": close * 1.01, "volume": volume})

    def _settings(self, data_path: Path | None = None):
        from analysis.limit_strength import LimitStrengthConfig

        return LimitStrengthConfig(
            data_path=data_path or Path("/tmp/missing"),
            back_days=10,
            min_limit_count=2,
            output_dir=Path("/tmp/out"),
            exclude_name_keywords=("ST",),
            exclude_code_prefixes=("83", "87", "920"),
            focus_themes=("机器人", "AI"),
            ma_windows=(20, 30, 60, 120),
            continue_days=3,
            enlarge_times=1.0,
            weights={"ma": 0.35, "breakout": 0.20, "momentum": 0.25, "volume": 0.20},
            history_days=365,
            adjust="qfq",
            output_filename="每日强势股结果.csv",
        )


if __name__ == "__main__":
    unittest.main()
