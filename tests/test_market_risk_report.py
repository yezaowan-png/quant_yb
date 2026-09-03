import tempfile
import unittest
from pathlib import Path

import pandas as pd

from visual.market_risk_report import generate_market_risk_report


class MarketRiskReportTest(unittest.TestCase):
    def test_list_payload_renders(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "risk.html"
            result = generate_market_risk_report(
                path,
                "000001.SH",
                {
                    "current_state": "stressed", "risk_level": "yellow", "risk_score": 20,
                    "risk_flags": ["dispersion_extreme"], "release_conditions": [],
                },
                pd.DataFrame([{"experiment": "E2", "roc_auc": 0.58}]),
                pd.DataFrame([{"gate": "auc_at_least_057", "passed": True}]),
                "continue_risk_gate_research",
                "E2",
            )
            self.assertEqual(result, path)
            self.assertIn("dispersion_extreme", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
