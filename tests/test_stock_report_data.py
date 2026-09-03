import unittest

import pandas as pd

from visual.stock_report_data import (
    build_equity_payload,
    build_mtf_diagnostics_payload,
    build_stock_period_payload,
    build_weekly_ema_diagnostics,
    compute_drawdowns,
    resample_ohlc,
)


def _ohlc_frame(days: int = 30) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=days, freq="D")
    rows = []
    for idx, date in enumerate(dates, start=1):
        rows.append(
            {
                "date": date,
                "open": 10 + idx,
                "high": 11 + idx,
                "low": 9 + idx,
                "close": 10.5 + idx,
                "volume": 1000 + idx,
            }
        )
    return pd.DataFrame(rows)


class StockReportDataTest(unittest.TestCase):
    def test_build_stock_period_payload_for_daily_period(self):
        df = _ohlc_frame()
        trades = pd.DataFrame(
            [
                {"date": "2026-01-02", "direction": "BUY", "price": 12.34},
                {"date": "2026-01-03", "direction": "SELL", "price": 13.45},
            ]
        )

        payload = build_stock_period_payload(
            symbol="000001.SZ",
            strategy_name="rsi",
            period_id="daily",
            period_label="日K",
            df_period=df,
            df_trades=trades,
        )

        self.assertEqual(payload["title"], "000001.SZ  —  rsi  (日K)")
        self.assertEqual(payload["dates"][0], "2026-01-01")
        self.assertEqual(payload["ohlc"][0], [11.0, 11.5, 10.0, 12.0])
        self.assertEqual(payload["trades"]["buy"], [("2026-01-02", 12.34)])
        self.assertEqual(payload["trades"]["sell"], [("2026-01-03", 13.45)])
        self.assertIn("macd", payload)
        self.assertIn("kdj", payload)
        self.assertIn("rsi", payload)

    def test_build_weekly_ema_diagnostics(self):
        df = _ohlc_frame()

        diagnostics = build_weekly_ema_diagnostics(df["close"], fast_period=5, slow_period=10)

        self.assertEqual(diagnostics["weeklyEmaFastLabel"], "周EMA5")
        self.assertEqual(diagnostics["weeklyEmaSlowLabel"], "周EMA10")
        self.assertEqual(len(diagnostics["weeklyEmaFast"]), len(df))
        self.assertEqual(len(diagnostics["weeklyEmaSlow"]), len(df))

    def test_resample_ohlc_aggregates_volume(self):
        df = _ohlc_frame(days=10)

        weekly = resample_ohlc(df, "W")

        self.assertFalse(weekly.empty)
        self.assertIn("volume", weekly.columns)
        self.assertEqual(int(weekly["volume"].sum()), int(df["volume"].sum()))

    def test_compute_drawdowns(self):
        self.assertEqual(compute_drawdowns([100.0, 110.0, 99.0, 120.0]), [0.0, 0.0, -10.0, 0.0])

    def test_build_equity_payload(self):
        equity = pd.DataFrame(
            {
                "dates": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
                "equity": [10000.126, 10500.0, 9975.0],
            }
        )

        payload = build_equity_payload(equity)

        self.assertEqual(payload["dates"], ["2026-01-01", "2026-01-02", "2026-01-03"])
        self.assertEqual(payload["equity"], [10000.13, 10500.0, 9975.0])
        self.assertEqual(payload["drawdowns"], [0.0, 0.0, -5.0])

    def test_build_equity_payload_returns_none_for_empty_input(self):
        self.assertIsNone(build_equity_payload(None))
        self.assertIsNone(build_equity_payload(pd.DataFrame()))

    def test_build_mtf_diagnostics_payload_daily_proxy(self):
        from strategy.multi_timeframe_volume_trend import MultiTimeframeVolumeTrendStrategy

        df = _ohlc_frame(days=90)
        trades = pd.DataFrame(
            [
                {"date": "2026-01-20", "direction": "BUY", "price": 30.0},
                {"date": "2026-02-10", "direction": "SELL", "price": 35.0},
            ]
        )

        diagnostics, summary = build_mtf_diagnostics_payload(
            df_ohlc=df,
            df_trades=trades,
            strategy_cls=MultiTimeframeVolumeTrendStrategy,
            strategy_params={"trend_filter_mode": "daily_proxy"},
        )

        self.assertIn("pullback", diagnostics)
        self.assertIn("breakout", diagnostics)
        self.assertIn("setup", diagnostics)
        self.assertIn("stalling", diagnostics)
        self.assertEqual(len(diagnostics["confirmCount"]), len(df))
        self.assertEqual(len(diagnostics["initialStop"]), len(df))
        self.assertEqual(summary["trend_label"], "代理趋势")
        self.assertIn(summary["setup_text"], {"是", "否"})


if __name__ == "__main__":
    unittest.main()
