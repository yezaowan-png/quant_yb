import tempfile
import unittest
import os
from pathlib import Path

from analysis.index_market_llm import (
    _api_key_from_env_or_dotenv,
    _markdown_html,
    build_llm_fact_markdown,
    build_llm_prompt,
    llm_summary_paths,
    write_llm_summary_artifacts,
)


def _sample_structure() -> dict:
    return {
        "date": "2026-07-13",
        "market_structure": {
            "style_regime_name": "全面弱势",
            "trend": {
                "large_cap_daily": "downtrend",
                "large_cap_weekly": "sideways",
                "growth_daily": "mixed",
                "growth_weekly": "mixed",
            },
            "breadth": {
                "today_state": "weak",
                "short_5d_state": "weak",
                "medium_20d_state": "very_weak",
            },
            "risk": {"pressure_level": "high", "risk_direction": "expanding"},
            "divergence": {"summary": "权重指数强于平均股价"},
            "headline": "当前属于全面弱势。",
        },
        "indices": {
            "上证指数": {
                "symbol": "000001.SH",
                "return_1d": -0.01,
                "return_5d": -0.03,
                "return_10d": -0.04,
                "return_20d": -0.05,
                "return_60d": 0.01,
                "daily_trend": "downtrend",
                "weekly_trend": "sideways",
            }
        },
        "styles": {
            "证券风险偏好": {
                "key": "securities",
                "return_5d": -0.04,
                "return_20d": 0.03,
                "return_60d": -0.02,
                "state_5d": "weak",
                "state_20d": "strong",
                "state_60d": "weak",
                "relative_all_a_20d": 0.10,
                "strength": 42.0,
                "proxy_note": "证券同花顺行业指数代理",
            }
        },
        "style_history": [],
        "industry_rankings": {
            "method_note": "同花顺行业指数行情口径",
            "strongest": [{"industry": "半导体", "symbol": "881121.TI", "return_20d": 0.16}],
            "weakest": [{"industry": "火电", "symbol": "884146.TI", "return_20d": -0.18}],
        },
        "sector_details": {
            "证券": {"symbols": ["881157.TI"], "return_20d": 0.03, "data_source": "Tushare ths_daily"}
        },
        "relative_strength": {"securities_vs_bank_20d": 0.04},
        "breadth": {
            "latest": {
                "advance_ratio": 0.4,
                "decline_ratio": 0.6,
                "pct_above_ma20": 0.18,
                "new_low_20_ratio": 0.45,
                "decline_gt_5_ratio": 0.41,
            }
        },
        "liquidity": {"state": "decline_on_volume", "amount_ratio_20": 1.2},
        "data_quality_flags": ["ths_style_proxy_indexes_used"],
    }


class IndexMarketLLMTest(unittest.TestCase):
    def test_fact_package_contains_required_sections_and_chinese_states(self):
        facts = build_llm_fact_markdown(_sample_structure(), "000001.SH", "上证指数")

        self.assertIn("A股市场结构事实包", facts)
        self.assertIn("系统总判断：全面弱势", facts)
        self.assertIn("权重指数日线趋势：下降", facts)
        self.assertIn("主要指数强弱", facts)
        self.assertIn("市场风格", facts)
        self.assertIn("行业强弱榜", facts)
        self.assertIn("市场广度与风险扩散", facts)
        self.assertNotIn("downtrend", facts)

    def test_prompt_embeds_facts_and_writing_rules(self):
        facts = "# facts"
        prompt = build_llm_prompt(facts)

        self.assertIn("只基于下面提供的事实包", prompt)
        self.assertIn("# facts", prompt)
        self.assertIn("仅供研究的候选相位", prompt)

    def test_v2_fact_package_exposes_deterministic_layers_and_boundaries(self):
        structure = _sample_structure()
        structure.update(
            {
                "schema_version": "market_structure_v2",
                "algorithm_version": "2.0.0",
                "config_hash": "c" * 64,
                "data_hash": "d" * 64,
                "layered_breadth": {
                    "全A": {
                        "state": "broad_strength",
                        "composition_point_in_time": False,
                        "latest": {
                            "effective_count": 5000,
                            "advance_ratio": 0.62,
                            "pct_above_ma20": 0.51,
                            "pct_above_ma60": 0.48,
                        },
                    }
                },
                "contribution_analysis": {"state": "moderate_concentration", "latest": {}},
                "return_distribution": {"state": "broad_rally", "latest": {}},
                "liquidity_structure": {"state": "broad_expansion", "latest": {}},
                "style_rotation": {"leader": "科技成长", "styles": {}},
                "source_freshness": {
                    "stock_universe": {
                        "status": "fresh",
                        "data_date": "2026-07-13",
                        "as_of_date": "2026-07-13",
                        "lag_trading_days": 0,
                        "point_in_time": False,
                    }
                },
                "point_in_time": {"future_rows_used": False},
                "research_candidates": {
                    "ice": {"phase": "none", "exploratory_only": True}
                },
                "valuation_context": {"status": "unknown"},
                "external_context": {"status": "unknown"},
                "llm_calls": 0,
                "formal_strategy_influence": False,
                "position_or_order_influence": False,
                "market_risk_gate_influence": False,
            }
        )
        state = structure["market_structure"]
        state["participation"] = {"state": "broad_participation", "state_tracker": {}}
        state["concentration"] = {"state": "moderate_concentration", "state_tracker": {}}
        state["leadership"] = {"state": "broad", "state_tracker": {}}
        state["repair"] = {"state": "normal", "state_tracker": {}}

        facts = build_llm_fact_markdown(structure, "000001.SH", "上证指数")

        self.assertIn("v2确定性状态总表", facts)
        self.assertIn("v2分层广度", facts)
        self.assertIn("broad_participation", facts)
        self.assertIn("moderate_concentration", facts)
        self.assertIn("仅供研究的候选相位", facts)
        self.assertIn("exploratory_only", facts)
        self.assertIn("缺失时保持unknown", facts)
        self.assertIn("正式策略影响=False", facts)

    def test_markdown_summary_html_is_rendered_not_preformatted(self):
        html = _markdown_html(
            "**一句话总判断**\n\n### 市场总览\n- **上涨比例** 40%\n\n| 指标 | 值 |\n| --- | --- |\n| 尾部压力 | 较高 |",
            "测试总结",
        )

        self.assertIn("<h3>市场总览</h3>", html)
        self.assertIn("<strong>一句话总判断</strong>", html)
        self.assertIn("<ul><li><strong>上涨比例</strong> 40%</li></ul>", html)
        self.assertIn("<table>", html)
        self.assertNotIn("<pre>", html)

    def test_write_artifacts_can_skip_api_without_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {
                "output": {"reports_dir": tmp, "statistics_dir": tmp},
                "llm_summary": {"deepseek": {"api_key_env": "MISSING_DEEPSEEK_KEY_FOR_TEST"}},
            }
            stats_root = Path(tmp) / "index_forecast"
            stats_root.mkdir(parents=True)
            (stats_root / "market_structure_000001.SH.json").write_text(
                __import__("json").dumps(_sample_structure(), ensure_ascii=False),
                encoding="utf-8",
            )

            paths, summary = write_llm_summary_artifacts(
                config, "000001.SH", 5, "上证指数", call_api=True, skip_if_no_key=True
            )

            self.assertIsNone(summary)
            self.assertTrue(paths.facts.exists())
            self.assertTrue(paths.prompt.exists())
            self.assertFalse(paths.summary.exists())
            self.assertEqual(paths, llm_summary_paths(config, "000001.SH", 5))

    def test_api_key_can_be_loaded_from_local_dotenv(self):
        old_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp)
                Path(".env.local").write_text("DEEPSEEK_API_KEY=test-local-key\n", encoding="utf-8")
                self.assertEqual(_api_key_from_env_or_dotenv("DEEPSEEK_API_KEY", {}), "test-local-key")
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
