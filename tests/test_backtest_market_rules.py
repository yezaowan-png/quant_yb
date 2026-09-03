import unittest
from datetime import date

import pandas as pd

from engine.runner import BacktestRunner
from strategy.base import (
    AShareCommission,
    BaseStrategy,
    price_limit_pct_for_symbol,
    stamp_duty_rate_for_date,
)


class _OneShotBuyStrategy(BaseStrategy):
    params = (("signal_date", "2026-08-04"),)

    def _init_indicators(self):
        pass

    def _next_buy_signal(self, data) -> bool:
        return data.datetime.date(0).isoformat() == self.p.signal_date


def _runner_config() -> dict:
    return {
        "backtest": {
            "initial_cash": 100_000.0,
            "commission": 0.00025,
            "stamp_duty": 0.001,
            "stamp_duty_after_reform": 0.0005,
            "date_aware_stamp_duty": True,
            "min_commission": 5.0,
            "slippage_perc": 0.0,
            "enforce_price_limits": True,
            "board_aware_price_limits": True,
            "limit_pct": 0.10,
            "volume_limit_ratio": 0.0,
            "volume_unit": 100,
        },
        "parallel": {"backtest_workers": 1},
        "benchmark": {"enabled": False},
    }


def _bars(execution_open: float) -> pd.DataFrame:
    rows = [
        ("2026-08-03", 10.0, 10.2, 9.8, 10.0),
        ("2026-08-04", 10.0, 10.2, 9.8, 10.0),
        ("2026-08-05", execution_open, max(execution_open, 10.2), min(execution_open, 10.0), execution_open),
        ("2026-08-06", 10.2, 10.3, 10.0, 10.2),
    ]
    return pd.DataFrame(
        [
            {"date": pd.Timestamp(day), "open": open_, "high": high, "low": low, "close": close, "volume": 1_000_000}
            for day, open_, high, low, close in rows
        ]
    )


class AShareMarketRuleTest(unittest.TestCase):
    def test_price_limit_ratio_is_board_and_date_aware(self):
        self.assertEqual(price_limit_pct_for_symbol("600000.SH", "20260807"), 0.10)
        self.assertEqual(price_limit_pct_for_symbol("000001.SZ", "20260807"), 0.10)
        self.assertEqual(price_limit_pct_for_symbol("688001.SH", "20260807"), 0.20)
        self.assertEqual(price_limit_pct_for_symbol("300001.SZ", date(2026, 8, 7)), 0.20)
        self.assertEqual(price_limit_pct_for_symbol("300001.SZ", "20200821"), 0.10)
        self.assertEqual(price_limit_pct_for_symbol("920305.BJ", "20260807"), 0.30)

    def test_unknown_symbol_uses_configured_fallback(self):
        self.assertEqual(price_limit_pct_for_symbol("UNKNOWN", fallback=0.15), 0.15)

    def test_stamp_duty_changes_on_2023_reform_date(self):
        self.assertEqual(stamp_duty_rate_for_date("20230827"), 0.001)
        self.assertEqual(stamp_duty_rate_for_date("20230828"), 0.0005)
        commission = AShareCommission(
            commission=0.00025,
            stamp_duty=0.001,
            stamp_duty_after_reform=0.0005,
            min_commission=5.0,
        )
        commission.set_trade_date("20230827")
        self.assertAlmostEqual(commission.getcommission(-1000, 10.0), 15.0)
        commission.set_trade_date("20230828")
        self.assertAlmostEqual(commission.getcommission(-1000, 10.0), 10.0)
        self.assertAlmostEqual(commission.getcommission(1000, 10.0), 5.0)

    def test_execution_day_limit_up_cancels_pending_market_buy(self):
        result = BacktestRunner(_runner_config()).run(
            _bars(11.0),
            _OneShotBuyStrategy,
            {"symbol": "600000.SH"},
            verbose=False,
        )

        self.assertEqual(result["buy_signal_dates"], ["2026-08-04"])
        self.assertEqual(result["trade_records"], [])

    def test_normal_execution_open_fills_pending_market_buy(self):
        result = BacktestRunner(_runner_config()).run(
            _bars(10.1),
            _OneShotBuyStrategy,
            {"symbol": "600000.SH"},
            verbose=False,
        )

        self.assertEqual(len(result["trade_records"]), 1)
        self.assertEqual(result["trade_records"][0]["direction"], "BUY")
        self.assertEqual(result["trade_records"][0]["date"], "2026-08-05")


if __name__ == "__main__":
    unittest.main()
