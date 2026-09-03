import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

from analysis.sector_money_flow import (
    SectorMoneyFlowConfig,
    add_new_data_point,
    archive_file_path,
    generate_trading_timeline,
    init_sector_money_flow_state,
    is_trading_hour,
    latest_sector_ranking,
    load_local_history_data,
    sector_money_flow_config,
    state_to_payload,
)
from visual.sector_money_flow_report import generate_sector_money_flow_report


class SectorMoneyFlowTest(unittest.TestCase):
    def test_trading_hour_and_timeline_skip_midday_break(self):
        self.assertFalse(is_trading_hour(datetime(2026, 8, 24, 9, 29)))
        self.assertTrue(is_trading_hour(datetime(2026, 8, 24, 9, 30)))
        self.assertTrue(is_trading_hour(datetime(2026, 8, 24, 11, 30)))
        self.assertFalse(is_trading_hour(datetime(2026, 8, 24, 11, 31)))
        self.assertFalse(is_trading_hour(datetime(2026, 8, 24, 12, 59)))
        self.assertTrue(is_trading_hour(datetime(2026, 8, 24, 13, 0)))
        self.assertTrue(is_trading_hour(datetime(2026, 8, 24, 15, 0)))
        self.assertFalse(is_trading_hour(datetime(2026, 8, 24, 15, 1)))

        timeline = generate_trading_timeline(
            datetime(2026, 8, 24, 11, 29),
            datetime(2026, 8, 24, 13, 1),
        )
        self.assertEqual([item.strftime("%H:%M") for item in timeline], ["11:29", "11:30", "13:00", "13:01"])

    def test_config_uses_project_defaults_and_overrides(self):
        settings = sector_money_flow_config(
            {
                "sector_money_flow": {
                    "sector_names": ["半导体", "银行"],
                    "interval_seconds": 1,
                    "data_dir": "tmp/sector-flow",
                    "history_replay_enabled": False,
                    "report_auto_refresh": False,
                }
            }
        )
        self.assertEqual(settings.sector_names, ["半导体", "银行"])
        self.assertEqual(settings.interval_seconds, 5)
        self.assertFalse(settings.history_replay_enabled)
        self.assertFalse(settings.report_auto_refresh)
        self.assertTrue(settings.data_dir.is_absolute())

    def test_load_local_history_replays_csvs_and_carries_last_valid_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = SectorMoneyFlowConfig(
                sector_names=["半导体", "银行"],
                interval_seconds=60,
                data_dir=Path(tmp),
                history_replay_enabled=True,
                report_auto_refresh=True,
            )
            first = datetime(2026, 8, 24, 9, 30)
            second = datetime(2026, 8, 24, 9, 31)
            lunch = datetime(2026, 8, 24, 12, 0)
            self._write_archive(settings, first, [{"行业": "半导体", "净额": 1.5}, {"行业": "银行", "净额": -0.5}])
            self._write_archive(settings, second, [{"行业": "半导体", "净额": 0}])
            self._write_archive(settings, lunch, [{"行业": "半导体", "净额": 9.9}, {"行业": "银行", "净额": 9.9}])

            state = load_local_history_data(settings, trade_date="2026-08-24")

            self.assertIsNotNone(state)
            assert state is not None
            self.assertTrue(state.is_replay_mode)
            self.assertEqual(state.max_data_idx, 1)
            self.assertEqual(state.history_data["半导体"][:2], [1.5, 1.5])
            self.assertEqual(state.history_data["银行"][:2], [-0.5, -0.5])
            ranking = latest_sector_ranking(state)
            self.assertEqual(ranking[0]["sector"], "半导体")
            payload = state_to_payload(state, settings)
            self.assertEqual(payload["data_indices"], [0, 1])
            self.assertEqual(payload["data_point_count"], 2)
            self.assertEqual(payload["snapshot_timestamps"], ["09:30", "09:31"])
            self.assertEqual(payload["snapshot_series"]["半导体"], [1.5, 1.5])

    def test_add_new_data_point_archives_and_merges_realtime_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = SectorMoneyFlowConfig(
                sector_names=["半导体", "银行"],
                interval_seconds=60,
                data_dir=Path(tmp),
                history_replay_enabled=False,
                report_auto_refresh=True,
            )
            now = datetime(2026, 8, 24, 10, 0)
            state = init_sector_money_flow_state(settings, now=now)
            ok, message, path = add_new_data_point(
                settings,
                state,
                now=now,
                fetcher=lambda: pd.DataFrame([{"行业": "半导体", "净额": 2.2}, {"行业": "银行", "净额": -1.0}]),
            )

            self.assertTrue(ok, message)
            self.assertIsNotNone(path)
            assert path is not None
            self.assertTrue(path.exists())
            idx = state.max_data_idx
            self.assertEqual(state.history_data["半导体"][idx], 2.2)
            self.assertEqual(state.history_data["银行"][idx], -1.0)

    def test_report_contains_payload_and_chart_mount(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = SectorMoneyFlowConfig(
                sector_names=["半导体"],
                interval_seconds=60,
                data_dir=Path(tmp) / "data",
                history_replay_enabled=True,
                report_auto_refresh=False,
            )
            state = init_sector_money_flow_state(settings, now=datetime(2026, 8, 24, 9, 30))
            state.history_data["半导体"][0] = 1.0
            state.max_data_idx = 0
            output = generate_sector_money_flow_report(state, settings, Path(tmp) / "sector_money_flow.html")
            text = output.read_text(encoding="utf-8")

            self.assertIn("行业板块资金流监控", text)
            self.assertIn("sector-flow-data", text)
            self.assertIn("半导体", text)
            self.assertIn("flow-chart", text)
            self.assertIn("只有 1 个归档数据点", text)
            self.assertIn("仅显示已采集快照", text)

    def _write_archive(self, settings: SectorMoneyFlowConfig, dt: datetime, rows: list[dict]):
        path = archive_file_path(settings.data_dir, dt)
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(path, encoding="utf-8-sig", index=False)


if __name__ == "__main__":
    unittest.main()
