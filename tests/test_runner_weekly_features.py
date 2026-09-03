import unittest

import pandas as pd

from engine.runner import _add_completed_weekly_features
from strategy.multi_timeframe_volume_trend import MultiTimeframeVolumeTrendStrategy


def _daily_frame() -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-01", "2026-01-16")
    rows = []
    for idx, date in enumerate(dates, start=1):
        close = 100.0 + idx
        rows.append(
            {
                "date": date,
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1000 + idx,
            }
        )
    return pd.DataFrame(rows)


class RunnerWeeklyFeaturesTest(unittest.TestCase):
    def test_weekly_features_only_use_completed_weekly_bars(self):
        df = _daily_frame()

        result = _add_completed_weekly_features(
            df,
            MultiTimeframeVolumeTrendStrategy,
            {
                "weekly_fast_ema": 1,
                "weekly_slow_ema": 1,
                "weekly_macd_fast": 1,
                "weekly_macd_slow": 1,
                "weekly_macd_signal": 1,
            },
        )
        by_date = result.set_index(result["date"].dt.strftime("%Y-%m-%d"))

        self.assertTrue(pd.isna(by_date.loc["2026-01-01", "weekly_close"]))
        self.assertEqual(
            by_date.loc["2026-01-05", "weekly_close"],
            by_date.loc["2026-01-02", "close"],
        )
        self.assertEqual(
            by_date.loc["2026-01-08", "weekly_close"],
            by_date.loc["2026-01-02", "close"],
        )
        self.assertEqual(
            by_date.loc["2026-01-09", "weekly_close"],
            by_date.loc["2026-01-09", "close"],
        )
        self.assertEqual(
            by_date.loc["2026-01-12", "weekly_close"],
            by_date.loc["2026-01-09", "close"],
        )

    def test_non_weekly_strategy_gets_empty_weekly_columns(self):
        class NoWeeklyStrategy:
            REQUIRES_WEEKLY_FEATURES = False

        result = _add_completed_weekly_features(_daily_frame(), NoWeeklyStrategy, {})

        for column in ["weekly_close", "weekly_ema_fast", "weekly_ema_slow", "weekly_macd_hist"]:
            self.assertIn(column, result.columns)
            self.assertTrue(result[column].isna().all())


if __name__ == "__main__":
    unittest.main()
