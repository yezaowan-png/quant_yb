import unittest

import pandas as pd

from data.metadata import (
    build_stock_name_map,
    clean_daily_basic,
    clean_stock_basic,
    filter_non_st_stocks,
    missing_daily_basic_dates,
)


class MetadataTest(unittest.TestCase):
    def test_filter_non_st_stocks(self):
        df = pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "name": "平安银行"},
                {"ts_code": "000002.SZ", "name": "ST示例"},
                {"ts_code": "000003.SZ", "name": "*ST示例"},
            ]
        )

        filtered = filter_non_st_stocks(df)

        self.assertEqual(filtered["ts_code"].tolist(), ["000001.SZ"])

    def test_clean_stock_basic_sorts_and_stringifies(self):
        raw = pd.DataFrame(
            [
                {"ts_code": "600519.SH", "symbol": 600519, "name": "贵州茅台"},
                {"ts_code": "000001.SZ", "symbol": 1, "name": "平安银行"},
            ]
        )

        cleaned = clean_stock_basic(raw)

        self.assertEqual(cleaned["ts_code"].tolist(), ["000001.SZ", "600519.SH"])
        self.assertEqual(str(cleaned["symbol"].dtype), "string")

    def test_build_stock_name_map_deduplicates(self):
        raw = pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "name": "旧名"},
                {"ts_code": "000001.SZ", "name": "新名"},
                {"ts_code": "600519.SH", "name": "贵州茅台"},
            ]
        )

        name_map = build_stock_name_map(raw)

        self.assertEqual(name_map["ts_code"].tolist(), ["000001.SZ", "600519.SH"])
        self.assertEqual(name_map.loc[0, "name"], "新名")

    def test_clean_daily_basic_keeps_fields_and_numeric_columns(self):
        raw = pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": 20260102,
                    "close": "10.5",
                    "turnover_rate": "1.2",
                    "ignored": "x",
                }
            ]
        )

        cleaned = clean_daily_basic(raw, "ts_code,trade_date,close,turnover_rate")

        self.assertEqual(cleaned.columns.tolist(), ["ts_code", "trade_date", "close", "turnover_rate"])
        self.assertEqual(cleaned.loc[0, "trade_date"], "20260102")
        self.assertAlmostEqual(cleaned.loc[0, "close"], 10.5)

    def test_missing_daily_basic_dates_respects_force(self):
        trade_dates = ["20260102", "20260105"]

        self.assertEqual(
            missing_daily_basic_dates(trade_dates, {"20260102"}, force=False),
            ["20260105"],
        )
        self.assertEqual(
            missing_daily_basic_dates(trade_dates, {"20260102"}, force=True),
            trade_dates,
        )


if __name__ == "__main__":
    unittest.main()
