import json
import tempfile
import unittest
from pathlib import Path

from cli.index_cli import run_market_environment
from visual.market_environment import generate_market_environment


def _structure():
    return {
        "date": "2026-09-02", "schema_version": "market_structure_v2", "data_quality_flags": ["example_flag"],
        "market_structure": {"headline": "现有市场结构结论。", "trend_state": "sideways", "breadth_state": "strong", "liquidity_state": "normal", "style_regime_name": "全面占优", "detail_lines": ["现有特征一。", "现有特征二。"], "breadth": {"today_state": "strong"}, "risk": {"state": "low_pressure_stable"}, "style": {"leader": "消费", "days_as_leader": 3, "leader_changes_20d": 2}},
        "indices": {"上证指数": {"return_1d": 0.01, "return_20d": 0.02}, "沪深300": {"return_1d": -0.01, "return_20d": 0.03}, "创业板指": {"return_1d": 0.02, "return_20d": -0.01}},
        "breadth": {"latest": {"advance_ratio": 0.6, "pct_above_ma20": 0.55, "new_high_20_ratio": 0.1, "new_low_20_ratio": 0.05}},
        "liquidity": {"state": "normal", "amount_ratio_20": 1.1}, "liquidity_structure": {"latest": {"total_amount": 1000000000, "amount_ratio_20d": 1.1, "advance_amount_ratio": 0.6, "decline_amount_ratio": 0.4}},
        "return_distribution": {"latest": {"median": 0.01, "q10": -0.02, "q90": 0.04, "decline_gt_3_ratio": 0.1, "decline_gt_5_ratio": 0.03}},
        "index_lift_structure": {"index_name": "上证指数", "contribution_concentration": {"top_10_positive_contribution_share": 0.2, "top_10_absolute_contribution_share": 0.3, "stocks_needed_for_80pct_positive_contribution": 16}, "turnover_confirmation": {"top20_turnover_amount_share": 0.4}},
    }


class MarketEnvironmentTest(unittest.TestCase):
    def test_summary_preserves_existing_facts_and_links_detail_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); brief = root / "brief.html"; full = root / "full.html"
            brief.write_text("brief", encoding="utf-8"); full.write_text("full", encoding="utf-8")
            output = generate_market_environment(_structure(), root / "market_environment.html", brief_path=brief, full_report_path=full)
            html = output.read_text(encoding="utf-8")
            for label in ("市场结论", "关键证据", "指数", "市场广度", "流动性", "风格", "横截面涨跌分布", "指数贡献结构", "详细研究"):
                self.assertIn(label, html)
            self.assertIn("暂无明确结论", html)
            self.assertIn("现有特征一。", html)
            self.assertIn('src="brief.html"', html)
            self.assertIn("展开市场结构摘录", html)

    def test_cli_reads_existing_json_without_running_structure_calculation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); reports = root / "reports" / "index_forecast"; stats = root / "statistics" / "index_forecast"
            reports.mkdir(parents=True); stats.mkdir(parents=True)
            (stats / "market_structure_000001.SH.json").write_text(json.dumps(_structure(), ensure_ascii=False), encoding="utf-8")
            config = {"output": {"reports_dir": str(root / "reports"), "statistics_dir": str(root / "statistics")}, "index_overview": {"default_symbol": "000001.SH", "indexes": [{"symbol": "000001.SH", "name": "上证指数"}]}}
            output = run_market_environment(config)
            self.assertTrue(output.exists())
            self.assertIn("市场环境", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
