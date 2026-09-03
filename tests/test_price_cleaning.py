import unittest

import pandas as pd

from data.price_cleaning import clean_index_daily, clean_stock_daily, clean_ths_index_daily


class PriceCleaningTest(unittest.TestCase):
    def test_clean_stock_daily_renames_sorts_and_marks_adjustment(self):
        raw = pd.DataFrame(
            [
                {
                    "trade_date": "20260103",
                    "open": "3",
                    "high": "4",
                    "low": "2",
                    "close": "3.5",
                    "vol": "100",
                    "amount": "200",
                    "adj_factor": "1.1",
                    "ignored": "x",
                },
                {
                    "trade_date": "20260102",
                    "open": "1",
                    "high": "2",
                    "low": "0.5",
                    "close": "1.5",
                    "vol": "80",
                    "amount": "120",
                    "adj_factor": "1.0",
                },
            ]
        )

        cleaned = clean_stock_daily(raw, adj="qfq")

        self.assertEqual(cleaned["date"].dt.strftime("%Y%m%d").tolist(), ["20260102", "20260103"])
        self.assertEqual(cleaned.columns.tolist(), ["date", "open", "high", "low", "close", "volume", "amount", "adj_factor", "adj"])
        self.assertAlmostEqual(cleaned.loc[0, "volume"], 80)
        self.assertEqual(cleaned["adj"].tolist(), ["qfq", "qfq"])

    def test_clean_stock_daily_drops_invalid_ohlc(self):
        raw = pd.DataFrame(
            [
                {"trade_date": "20260102", "open": "1", "high": "2", "low": "0.5", "close": "1.5", "vol": 10},
                {"trade_date": "20260103", "open": None, "high": "2", "low": "0.5", "close": "1.5", "vol": 10},
                {"trade_date": "20260104", "open": "1", "high": "2", "low": "0", "close": "1.5", "vol": 10},
                {"trade_date": "20260105", "open": "1", "high": "1.4", "low": "0.5", "close": "1.5", "vol": 10},
                {"trade_date": "20260106", "open": "1", "high": "2", "low": "0.5", "close": "1.5", "vol": -1},
            ]
        )

        cleaned = clean_stock_daily(raw)

        self.assertEqual(cleaned["date"].dt.strftime("%Y%m%d").tolist(), ["20260102"])

    def test_clean_index_daily_keeps_index_fields(self):
        raw = pd.DataFrame(
            [
                {
                    "ts_code": "000001.SH",
                    "trade_date": "20260102",
                    "open": "1",
                    "high": "2",
                    "low": "0.5",
                    "close": "1.5",
                    "pre_close": "1.4",
                    "change": "0.1",
                    "pct_chg": "7.14",
                    "vol": "100",
                    "amount": "200",
                }
            ]
        )

        cleaned = clean_index_daily(raw)

        self.assertEqual(cleaned.loc[0, "ts_code"], "000001.SH")
        self.assertEqual(cleaned.loc[0, "date"].strftime("%Y%m%d"), "20260102")
        self.assertAlmostEqual(cleaned.loc[0, "pct_chg"], 7.14)

    def test_clean_ths_index_daily_normalizes_pct_change_and_market_fields(self):
        raw = pd.DataFrame(
            [
                {
                    "ts_code": "700082.TI",
                    "trade_date": "20260713",
                    "open": "15607.216",
                    "high": "15633.529",
                    "low": "15009.296",
                    "close": "15048.958",
                    "pre_close": "15687.729",
                    "change": "-638.771",
                    "pct_change": "-4.0718",
                    "vol": "1329356000",
                    "amount": "1930000000",
                    "turnover_rate": "1.827292",
                    "total_mv": "1000000",
                    "float_mv": "900000",
                }
            ]
        )

        cleaned = clean_ths_index_daily(raw)

        self.assertEqual(cleaned.loc[0, "ts_code"], "700082.TI")
        self.assertAlmostEqual(cleaned.loc[0, "pct_chg"], -4.0718)
        self.assertAlmostEqual(cleaned.loc[0, "amount"], 1930000000)
        self.assertAlmostEqual(cleaned.loc[0, "turnover_rate"], 1.827292)


if __name__ == "__main__":
    unittest.main()
