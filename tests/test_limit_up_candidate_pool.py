import tempfile
import unittest
from pathlib import Path

import pandas as pd

from analysis.limit_up_candidate_pool import build_limit_up_candidate_pool, save_limit_up_candidate_pool


def _config(root: Path, **overrides) -> dict:
    settings = {
        "lookback_trade_days": 120,
        "cache_subdir": "limit_up_events",
        "trade_calendar_exchange": "SSE",
        "exclude_st": True,
        "exclude_beijing": True,
        "exclude_recent_ipo": True,
        "recent_ipo_trade_days": 20,
        "recent_limit_up_dates_count": 5,
    }
    settings.update(overrides)
    return {"data": {"cache_dir": str(root / "cache")}, "limit_up_candidate_pool": settings}


class FakePro:
    def __init__(self, dates, events=None, calendar_error=False, failing_dates=None):
        self.dates = dates
        self.events = events or {}
        self.calendar_error = calendar_error
        self.failing_dates = set(failing_dates or [])
        self.limit_calls = []

    def trade_cal(self, exchange, start_date, end_date, is_open=None, fields=None):
        if self.calendar_error:
            raise RuntimeError("calendar permission denied")
        return pd.DataFrame({"cal_date": self.dates, "is_open": 1})

    def limit_list_d(self, trade_date, fields=None):
        self.limit_calls.append(trade_date)
        if trade_date in self.failing_dates:
            raise RuntimeError("limit_list_d permission denied")
        rows = []
        for row in self.events.get(trade_date, []):
            rows.append({"trade_date": trade_date, **row})
        return pd.DataFrame(rows)


def _dates(count=125):
    return pd.bdate_range("2026-01-02", periods=count).strftime("%Y%m%d").tolist()


def _event(symbol, name, kind="U", **extra):
    return {
        "ts_code": symbol,
        "name": name,
        "industry": "测试行业",
        "limit_type": kind,
        "amount": 123456.0,
        "turnover_ratio": 6.5,
        "limit_times": 2,
        "up_stat": "2连板",
        **extra,
    }


class LimitUpCandidatePoolTest(unittest.TestCase):
    def test_uses_last_120_real_trade_dates_and_u_only_counts(self):
        dates = _dates()
        events = {
            dates[4]: [_event("000001.SZ", "窗口外")],
            dates[5]: [_event("000001.SZ", "甲")],
            dates[-60]: [_event("000001.SZ", "甲")],
            dates[-1]: [_event("000001.SZ", "甲"), _event("000002.SZ", "乙", "Z")],
        }
        with tempfile.TemporaryDirectory() as tmp:
            result = build_limit_up_candidate_pool(_config(Path(tmp)), dates[-1], pro=FakePro(dates, events))

        self.assertTrue(result.official)
        self.assertEqual(result.status["window_start_date"], dates[5])
        self.assertEqual(result.status["expected_trade_days"], 120)
        self.assertEqual(result.status["limit_up_event_count"], 3)
        self.assertEqual(result.status["opened_event_count"], 1)
        self.assertEqual(result.candidates["ts_code"].tolist(), ["000001.SZ"])
        row = result.candidates.iloc[0]
        self.assertEqual(row["limit_up_count_120d"], 3)
        self.assertEqual(row["limit_up_count_20d"], 1)
        self.assertEqual(row["limit_up_count_60d"], 2)
        self.assertEqual(row["trading_days_since_latest"], 0)

    def test_consecutive_boards_cross_weekend_via_trade_calendar(self):
        dates = _dates()
        friday = next(day for day in dates[5:] if pd.Timestamp(day).weekday() == 4)
        monday = dates[dates.index(friday) + 1]
        events = {friday: [_event("000001.SZ", "甲")], monday: [_event("000001.SZ", "甲")]}
        with tempfile.TemporaryDirectory() as tmp:
            result = build_limit_up_candidate_pool(_config(Path(tmp)), dates[-1], pro=FakePro(dates, events))

        self.assertEqual(result.candidates.iloc[0]["max_consecutive_limit_up"], 2)

    def test_calendar_failure_never_returns_official_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_limit_up_candidate_pool(_config(Path(tmp)), "20261231", pro=FakePro([], calendar_error=True))

        self.assertFalse(result.official)
        self.assertEqual(result.status["status"], "incomplete")
        self.assertTrue(result.candidates.empty)

    def test_failed_detail_keeps_status_incomplete_without_formal_output(self):
        dates = _dates()
        with tempfile.TemporaryDirectory() as tmp:
            result = build_limit_up_candidate_pool(
                _config(Path(tmp)), dates[-1], pro=FakePro(dates, failing_dates=[dates[-1]])
            )

        self.assertFalse(result.official)
        self.assertEqual(result.status["missing_trade_days"], [dates[-1]])
        self.assertTrue(result.candidates.empty)

    def test_daily_event_cache_makes_repeated_run_idempotent(self):
        dates = _dates()
        events = {dates[-1]: [_event("000001.SZ", "甲"), _event("000001.SZ", "甲")]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pro = FakePro(dates, events)
            first = build_limit_up_candidate_pool(_config(root), dates[-1], pro=pro)
            calls_after_first = len(pro.limit_calls)
            second = build_limit_up_candidate_pool(_config(root), dates[-1], pro=pro)

        self.assertEqual(calls_after_first, 120)
        self.assertEqual(len(pro.limit_calls), calls_after_first)
        self.assertEqual(first.candidates.iloc[0]["limit_up_count_120d"], 1)
        self.assertEqual(second.candidates.iloc[0]["limit_up_count_120d"], 1)

    def test_eligibility_exclusions_keep_events_but_mark_candidates(self):
        dates = _dates()
        events = {
            dates[-1]: [
                _event("000001.SZ", "ST甲"),
                _event("430001.BJ", "北交所乙"),
                _event("300001.SZ", "新股丙"),
            ]
        }
        metadata = pd.DataFrame(
            [
                {"ts_code": "300001.SZ", "list_date": dates[-5]},
                {"ts_code": "000001.SZ", "list_date": "20100101"},
                {"ts_code": "430001.BJ", "list_date": "20100101"},
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = build_limit_up_candidate_pool(_config(Path(tmp)), dates[-1], pro=FakePro(dates, events), stock_metadata=metadata)

        rows = result.candidates.set_index("ts_code")
        self.assertFalse(rows.loc["000001.SZ", "eligible_for_chatgpt_classification"])
        self.assertIn("ST/*ST", rows.loc["000001.SZ", "exclusion_reason"])
        self.assertFalse(rows.loc["430001.BJ", "eligible_for_chatgpt_classification"])
        self.assertTrue(rows.loc["430001.BJ", "is_beijing"])
        self.assertFalse(rows.loc["300001.SZ", "eligible_for_chatgpt_classification"])
        self.assertTrue(rows.loc["300001.SZ", "is_recent_ipo"])

    def test_only_complete_result_can_overwrite_official_output(self):
        dates = _dates()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            complete = build_limit_up_candidate_pool(
                _config(root), dates[-1], pro=FakePro(dates, {dates[-1]: [_event("000001.SZ", "甲")]})
            )
            paths = save_limit_up_candidate_pool(complete, root / "statistics")
            incomplete = build_limit_up_candidate_pool(
                _config(root), dates[-1], pro=FakePro(dates, failing_dates=[dates[-1]]), cache_dir=root / "other-cache"
            )
            with self.assertRaises(ValueError):
                save_limit_up_candidate_pool(incomplete, root / "statistics")

            self.assertTrue(paths["candidates_path"].exists())
            self.assertTrue(paths["status_path"].exists())


if __name__ == "__main__":
    unittest.main()
