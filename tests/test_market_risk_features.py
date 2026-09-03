import unittest

import numpy as np
import pandas as pd

from analysis.market_risk_features import (
    MINIMAL_RISK_FEATURES,
    assert_asof_feature_contract,
    available_minimal_features,
    build_market_risk_features,
)


class MarketRiskFeaturesTest(unittest.TestCase):
    def _data(self, rows=280, stocks=30):
        dates = pd.bdate_range("2020-01-01", periods=rows)
        rng = np.random.default_rng(11)
        returns = rng.normal(0.0002, 0.015, size=(rows, stocks))
        closes = pd.DataFrame(20 * np.cumprod(1 + returns, axis=0), index=dates)
        index_close = 3000 * np.cumprod(1 + returns.mean(axis=1))
        index = pd.DataFrame({"date": dates, "close": index_close, "amount": 1e10 * (1 + rng.random(rows))})
        return index, closes

    def test_minimal_feature_contract_has_no_future_fields(self):
        index, closes = self._data()
        frame = build_market_risk_features(index, closes)
        assert_asof_feature_contract(frame)
        self.assertEqual(available_minimal_features(frame), list(MINIMAL_RISK_FEATURES))
        self.assertFalse(any(column.startswith("future_") for column in frame.columns))

    def test_future_rows_do_not_change_past_features(self):
        index, closes = self._data()
        full = build_market_risk_features(index, closes)
        prefix = build_market_risk_features(index.iloc[:240], closes.iloc[:240])
        columns = ["normalized_ad", "ad_slope_5", "normalized_nhnl", "nhnl_slope_5", "pct_above_ma20"]
        pd.testing.assert_frame_equal(
            full.iloc[:240][columns].reset_index(drop=True), prefix[columns].reset_index(drop=True)
        )


if __name__ == "__main__":
    unittest.main()
