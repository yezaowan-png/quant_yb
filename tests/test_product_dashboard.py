import json
import tempfile
import unittest
from pathlib import Path

from visual.product_dashboard import PRODUCT_SHELL_MARKER, generate_product_dashboard


class ProductDashboardTest(unittest.TestCase):
    def _config(self, root: Path) -> dict:
        return {
            "output": {
                "reports_dir": str(root / "reports"),
                "statistics_dir": str(root / "statistics"),
                "signals_dir": str(root / "signals"),
            }
        }

    def test_product_shell_preserves_legacy_and_only_links_existing_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._config(root)
            reports = root / "reports"
            stats = root / "statistics"
            (reports / "strong_stock_radar").mkdir(parents=True)
            (reports / "vpt").mkdir(parents=True)
            (stats / "data_quality").mkdir(parents=True)
            (stats / "strong_stock_radar").mkdir(parents=True)
            (stats / "vpt").mkdir(parents=True)
            (root / "signals").mkdir(parents=True)
            (reports / "dashboard.html").write_text("<html>legacy</html>", encoding="utf-8")
            (reports / "data_quality.html").write_text("quality", encoding="utf-8")
            (reports / "strong_stock_radar" / "strong_stock_radar.html").write_text("radar", encoding="utf-8")
            (reports / "vpt" / "vpt_candidates.html").write_text("vpt", encoding="utf-8")
            (stats / "data_quality" / "market_data_audit.json").write_text(
                json.dumps({"status": "healthy", "datasets": {"stocks": {"reference_date": "20260902", "latest_coverage": 1.0}}}),
                encoding="utf-8",
            )
            (stats / "strong_stock_radar" / "strong_stock_radar_latest.csv").write_text(
                "trade_date,state\n20260902,CORE_STRONG\n20260902,ACCELERATING\n", encoding="utf-8"
            )
            (root / "signals" / "vpt_candidates_20260902.csv").write_text(
                "trade_date,vpt_state\n20260902,QUALIFIED\n20260902,TREND_CONFIRMING\n",
                encoding="utf-8",
            )
            (stats / "vpt" / "vpt_snapshot_20260902.csv").write_text(
                "trade_date,vpt_state,is_current_date,eligible\n"
                "20260902,QUALIFIED,True,True\n"
                "20260902,QUALIFIED,True,True\n"
                "20260901,QUALIFIED,False,True\n",
                encoding="utf-8",
            )

            output = generate_product_dashboard(config)
            page = output.read_text(encoding="utf-8")

            self.assertTrue((reports / "legacy_dashboard.html").exists())
            self.assertEqual((reports / "legacy_dashboard.html").read_text(encoding="utf-8"), "<html>legacy</html>")
            self.assertIn(PRODUCT_SHELL_MARKER, page)
            for label in ("今日总览", "数据中心", "市场环境", "行情中心", "强势方向", "策略选股", "研究工具"):
                self.assertIn(label, page)
            self.assertIn("data_quality.html", page)
            self.assertIn("vpt/vpt_candidates.html", page)
            self.assertIn("VPT-01 报告候选", page)
            self.assertIn("全量合格 2", page)
            self.assertIn("待生成", page)
            self.assertNotIn("generate_market_structure_brief", page)


if __name__ == "__main__":
    unittest.main()
