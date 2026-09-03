"""Contract coverage for optional theme-member presentation in the radar report."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from analysis.strong_stock_radar import build_theme_stock_rs_history
from visual.strong_stock_radar_report import generate_strong_stock_radar_report


def _radar_meta(report: str) -> dict:
    marker = '<script type="application/json" id="radarMeta">'
    start = report.index(marker) + len(marker)
    end = report.index("</script>", start)
    return json.loads(report[start:end])


class ThemeStockRadarReportTest(unittest.TestCase):
    def test_confirmed_theme_members_render_with_optional_payloads(self):
        payload = {
            "themes": {"ai_power": {"name": "AI电源", "enabled": True, "definition": "数据中心电源"}},
            "stocks": {
                "000001.SZ": {
                    "stock_name": "电源甲",
                    "latest_limit_up_date": "20260901",
                    "limit_up_count_20d": 1,
                    "limit_up_count_60d": 2,
                    "limit_up_count_120d": 3,
                    "assignments": {
                        "ai_power": {
                            "status": "confirmed",
                            "classification_source": "chatgpt_manual_handoff",
                            "reason": "主营服务器电源",
                            "industry_relation": "direct",
                            "market_theme_relation": "active",
                            "confidence": "medium",
                        }
                    },
                },
                "000002.SZ": {"stock_name": "待确认", "assignments": {"ai_power": {"status": "pending"}}},
            },
        }
        history = pd.DataFrame(
            [
                {"trade_date": "20260824", "theme_id": "ai_power", "ts_code": "000001.SZ", "rs5_pct": 30, "rs10_pct": 35, "rs20_pct": 40, "rs60_pct": 45},
                {"trade_date": "20260825", "theme_id": "ai_power", "ts_code": "000001.SZ", "rs5_pct": 40, "rs10_pct": 45, "rs20_pct": 50, "rs60_pct": 55},
                {"trade_date": "20260826", "theme_id": "ai_power", "ts_code": "000001.SZ", "rs5_pct": 50, "rs10_pct": 55, "rs20_pct": 60, "rs60_pct": 65},
                {"trade_date": "20260827", "theme_id": "ai_power", "ts_code": "000001.SZ", "rs5_pct": 60, "rs10_pct": 65, "rs20_pct": 70, "rs60_pct": 75},
                {"trade_date": "20260828", "theme_id": "ai_power", "ts_code": "000001.SZ", "rs5_pct": 70, "rs10_pct": 75, "rs20_pct": 80, "rs60_pct": 85},
                {"trade_date": "20260831", "theme_id": "ai_power", "ts_code": "000001.SZ", "rs5_pct": 80, "rs10_pct": 85, "rs20_pct": 90, "rs60_pct": None},
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "radar.html"
            generate_strong_stock_radar_report(
                {}, "20260831", pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), {}, target,
                theme_pool_payload=payload, theme_stock_history=history,
            )
            report = target.read_text(encoding="utf-8")
        meta = _radar_meta(report)
        theme_history = meta["themeStockHistory"]
        value_columns = ["rs5_pct", "rs10_pct", "rs20_pct", "rs60_pct", "rs120_pct"]
        self.assertEqual(set(theme_history), {"valueColumns", "byTheme"})
        self.assertEqual(theme_history["valueColumns"], value_columns)
        self.assertEqual(list(theme_history["byTheme"]), ["ai_power"])
        theme_group = theme_history["byTheme"]["ai_power"]
        self.assertEqual(set(theme_group), {"dates", "series"})
        self.assertEqual(
            theme_group["dates"],
            ["20260824", "20260825", "20260826", "20260827", "20260828", "20260831"],
        )
        self.assertEqual(set(theme_group["series"]), {"000001.SZ"})
        compact_series = theme_group["series"]["000001.SZ"]
        self.assertEqual(len(compact_series), 6)
        self.assertTrue(all(isinstance(row, list) for row in compact_series))
        self.assertEqual(compact_series[0], [30, 35, 40, 45, None])
        self.assertEqual(compact_series[-1], [80, 85, 90, None, None])
        self.assertNotIn("columns", theme_history)
        self.assertNotIn("trade_date", theme_group)
        self.assertNotIn("classification_source", theme_history)
        self.assertNotIn("theme_name", theme_history)
        self.assertNotIn('id="themeAnalysisRange"', report)
        self.assertIn('id="themePoolSelect"', report)
        self.assertIn('id="themeQuickSelect"', report)
        self.assertIn('id="themeMembersSection"', report)
        self.assertIn('id="themeStockHeatmap"', report)
        self.assertIn('id="themeRotationSection"', report)
        self.assertIn('id="themeRotationHeatmap"', report)
        self.assertIn('"AI电源"', report)
        self.assertIn('"000001.SZ"', report)
        self.assertNotIn('"000002.SZ"', report)
        self.assertIn("function drawThemeStockHeatmap", report)
        self.assertIn("function setThemeStockEmptyState", report)
        self.assertIn("function drawThemeRotationHeatmap", report)
        self.assertIn("function themeRotationRows(field)", report)
        self.assertIn("themeRotationChart.on('click'", report)
        self.assertIn("主题间排名", report)
        self.assertIn("主题内 '+themeHtml(metric.replace('_pct','').toUpperCase())+' 排名", report)
        self.assertIn("visible.map(memberLabel)", report)
        self.assertIn("function themeHistoryRows(themeId)", report)
        self.assertIn("const columns=themeStockHistory.valueColumns||[]", report)
        self.assertIn("group=((themeStockHistory.byTheme||{})[themeId]||{})", report)
        self.assertNotIn("themeHistoryRows();", report)
        self.assertIn('"pendingByTheme"', report)
        self.assertIn("min:0,max:100", report)
        self.assertIn("color:'#f1f3f5'", report)
        self.assertIn("主题内排名", report)
        self.assertIn("5日主题内名次变化", report)
        self.assertIn('id="themePoolSelect"', report)
        for section_id in (
            "industryHeatSection",
            "strongIndustrySection",
            "industryDetailSection",
            "themeMembersSection",
            "themeRotationSection",
            "strongStocksSection",
        ):
            self.assertIn(f'<details id="{section_id}"', report)
        self.assertIn("function drawWhenOpen(sectionId, draw)", report)
        self.assertIn("requestAnimationFrame(drawThemeStockHeatmap)", report)
        self.assertIn("const section=document.getElementById('themeMembersSection');section.open=true", report)
        self.assertIn("section.scrollIntoView({behavior:'smooth',block:'start'})", report)
        self.assertNotIn('id="rotationDimension"', report)
        self.assertNotIn("conceptHistory", report)

    def test_theme_arguments_and_legacy_custom_concept_arguments_remain_compatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "radar.html"
            legacy_history = pd.DataFrame([{"trade_date": "20260831", "concept_name": "legacy concept"}])
            generate_strong_stock_radar_report(
                {}, "20260831", pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), {}, target,
                None, legacy_history, [], ["legacy concept warning"],
            )
            report = target.read_text(encoding="utf-8")
        self.assertIn('id="themePoolSelect" disabled', report)
        self.assertIn("暂无已确认的正式 RS 成员", report)
        self.assertNotIn('id="rotationDimension"', report)
        self.assertNotIn("conceptHistory", report)
        self.assertNotIn("legacy concept", report)

    def test_only_confirmed_rs_members_enter_theme_history_and_denominator(self):
        payload = {
            "themes": {"theme": {"name": "主题", "enabled": True, "definition": "测试"}},
            "stocks": {
                "000001.SZ": {"stock_name": "正式", "assignments": {"theme": {"status": "confirmed", "pool_role": "rs_member"}}},
                "000002.SZ": {"stock_name": "观察", "assignments": {"theme": {"status": "confirmed", "pool_role": "watch_only"}}},
                "000003.SZ": {"stock_name": "待确认", "assignments": {"theme": {"status": "pending", "pool_role": "rs_member"}}},
                "000004.SZ": {"stock_name": "已拒绝", "assignments": {"theme": {"status": "rejected", "pool_role": "rs_member"}}},
                "000005.SZ": {"stock_name": "旧成员", "assignments": {"theme": {"status": "confirmed"}}},
            },
        }
        dates = ["20260831", "20260901"]
        values = pd.DataFrame({
            "000001.SZ": [80, 81], "000002.SZ": [70, 71], "000003.SZ": [60, 61],
            "000004.SZ": [50, 51], "000005.SZ": [40, 41],
        }, index=dates)
        history = build_theme_stock_rs_history(payload, {window: values for window in (5, 10, 20, 60, 120)}, dates)
        self.assertEqual(set(history["ts_code"]), {"000001.SZ", "000005.SZ"})
        latest = history[history["trade_date"] == "20260901"]
        self.assertEqual(set(latest["theme_rs60_denominator"]), {2})

    def test_confirmed_watch_member_renders_only_in_observation_section(self):
        payload = {
            "themes": {"ai_power": {"name": "AI电源", "enabled": True, "definition": "数据中心电源"}},
            "stocks": {
                "000001.SZ": {"stock_name": "正式", "assignments": {"ai_power": {"status": "confirmed", "pool_role": "rs_member", "reason": "正式", "industry_relation": "core", "market_theme_relation": "core", "confidence": "high"}}},
                "000002.SZ": {"stock_name": "观察", "assignments": {"ai_power": {"status": "confirmed", "pool_role": "watch_only", "reason": "观察", "industry_relation": "indirect", "market_theme_relation": "active", "confidence": "medium", "evidence": [{"title": "证据", "supports": "支持", "url": None}]}}},
            },
        }
        history = pd.DataFrame([{"trade_date": "20260831", "ts_code": "000001.SZ", "rs5_pct": 80, "rs10_pct": 80, "rs20_pct": 80, "rs60_pct": 80}])
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "radar.html"
            generate_strong_stock_radar_report({}, "20260831", pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), {}, target, theme_pool_payload=payload, theme_stock_history=history)
            report = target.read_text(encoding="utf-8")
        self.assertIn('"watchByTheme"', report)
        self.assertIn("仅观察，不参与主题RS", report)
        self.assertIn('"000002.SZ"', report)


if __name__ == "__main__":
    unittest.main()
