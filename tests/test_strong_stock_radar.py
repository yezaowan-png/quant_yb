import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.strong_stock_radar import (
    build_strong_stock_radar,
    close_position,
    ma_slope,
    percentile_rank,
    radar_config,
    rolling_distance_to_high,
    rs_persistence,
    stock_state_for_row,
    trend_state_for_row,
    volume_price_state_for_row,
)
from analysis.custom_concept_pools import (
    ConceptPoolConfigError,
    build_custom_concept_rs_history,
    load_custom_concept_pools,
)
from visual.strong_stock_radar_report import (
    ROTATION_HELPERS_JS,
    generate_strong_stock_radar_report,
    heatmap_color_band,
)


class StrongStockRadarFormulaTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "需要 Node 执行浏览器热力图辅助函数")
    def test_rotation_helpers_preserve_missing_values_and_filter_current_rows(self):
        positive = {
            "传媒": 25.806452,
            "行业02": 19.354839,
            "行业03": 16.129032,
            "行业04": 16.129032,
            "行业05": 9.677419,
            "行业06": 9.677419,
            "行业07": 6.451613,
            "行业08": 6.451613,
            "行业09": 6.451613,
            "行业10": 3.225806,
            "行业11": 3.225806,
            "行业12": 3.225806,
        }
        negatives = {"汽车": -3.225806, "建筑装饰": -3.225806, "基础化工": -3.225806}
        names = ["传媒", *[f"行业{index:02d}" for index in range(2, 13)], "汽车", "建筑装饰", "基础化工", *[f"行业{index:02d}" for index in range(16, 32)]]
        history = []
        for index, industry in enumerate(names, start=1):
            value = index * 100.0 / 31.0
            current_value = 90.0 if industry == "传媒" else value
            current = {
                "trade_date": "20260831",
                "industry": industry,
                "industry_rs5_pct": 80.0,
                "industry_rs10_pct": value,
                "industry_rs20_pct": current_value,
                "industry_rs60_pct": current_value,
                "industry_rs120_pct": current_value,
                "industry_daily_return": 0.01,
                "pct_advancing": 0.7,
            }
            for date in ("20260817", "20260818", "20260819", "20260820", "20260821", "20260824"):
                previous = current.copy()
                previous["trade_date"] = date
                if industry in positive:
                    previous["industry_rs60_pct"] = 0.0
                if industry == "汽车":
                    previous["industry_rs20_pct"] = 0.0
                if industry == "行业12":
                    previous["industry_rs120_pct"] = 0.0
                history.append(previous)
            history.append(current)
        history.append({"trade_date": "20260831", "industry": "未分类", "industry_rs60_pct": None})
        script = ROTATION_HELPERS_JS + """
const assert = require('node:assert/strict');
const history = __HISTORY__;
assert.equal(finiteOrNull(null), null);
assert.equal(finiteOrNull(undefined), null);
assert.equal(finiteOrNull(''), null);
assert.equal(finiteOrNull(NaN), null);
assert.equal(finiteOrNull(Infinity), null);
assert.equal(finiteOrNull(0), 0);
assert.equal(finiteOrNull('0'), 0);
assert.equal(rotationMetric('industry_rs5_pct').deltaField, 'industry_rs5_pct_delta_5d_common');
assert.equal(rotationMetric('industry_rs10_pct').deltaField, 'industry_rs10_pct_delta_5d_common');
assert.equal(rotationMetric('industry_rs20_pct').deltaField, 'industry_rs20_pct_delta_5d_common');
assert.equal(rotationMetric('industry_rs60_pct').deltaField, 'industry_rs60_pct_delta_5d_common');
assert.equal(rotationMetric('industry_rs120_pct').deltaField, 'industry_rs120_pct_delta_5d_common');
const state60 = rotationState(history, 'industry_rs60_pct');
const improving60 = filteredRotationRows(state60, 'improving', [], 1);
assert.equal(state60.cutoffDate, '20260831');
assert.equal(state60.previousDate, '20260818');
assert.equal(state60.validCount, 31);
assert.equal(state60.rankByIndustry['行业20'], 13);
assert.ok(improving60.length > 0);
assert.equal(improving60[0].industry, '传媒');
assert.ok(improving60.every(row => state60.comparisonByIndustry[row.industry].rankChange >= 1));
assert.ok(!improving60.some(row => ['汽车', '建筑装饰', '基础化工', '未分类'].includes(row.industry)));
const improving20 = filteredRotationRows(rotationState(history, 'industry_rs20_pct'), 'improving', [], 1);
assert.ok(improving20.some(row => row.industry === '汽车'));
const improving120 = filteredRotationRows(rotationState(history, 'industry_rs120_pct'), 'improving', [], 1);
assert.deepEqual(improving120.map(row => row.industry), ['行业12']);
const shortFromRs60 = filteredRotationRows(state60, 'shortTerm', [], 2).map(row => row.industry);
const shortFromRs120 = filteredRotationRows(rotationState(history, 'industry_rs120_pct'), 'shortTerm', [], 2).map(row => row.industry);
assert.deepEqual(shortFromRs60, shortFromRs120);
""".replace("__HISTORY__", json.dumps(history, ensure_ascii=False))
        completed = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_heatmap_uses_fixed_rs_bands_and_preserves_missing_values(self):
        self.assertEqual(heatmap_color_band(3.23), "weak")
        self.assertEqual(heatmap_color_band(50), "neutral")
        self.assertEqual(heatmap_color_band(100), "strong")
        self.assertEqual(heatmap_color_band(float("nan")), "missing")

    def test_percentile_rank_and_persistence(self):
        frame = pd.DataFrame({"A": [1.0, 3.0], "B": [2.0, 2.0], "C": [3.0, 1.0]}, index=["T1", "T2"])
        ranked = percentile_rank(frame)
        self.assertAlmostEqual(ranked.at["T1", "A"], 100.0 / 3.0)
        self.assertAlmostEqual(ranked.at["T1", "C"], 100.0)
        persistence = rs_persistence(ranked, window=2, threshold=80.0)
        self.assertAlmostEqual(persistence.at["T2", "A"], 0.5)
        self.assertAlmostEqual(persistence.at["T2", "C"], 0.5)

    def test_rolling_high_distance_ma_slope_and_close_position(self):
        close = pd.DataFrame({"A": [10.0, 11.0, 12.0, 9.0]})
        high, distance = rolling_distance_to_high(close, 3)
        self.assertTrue(pd.isna(high.at[1, "A"]))
        self.assertEqual(high.at[2, "A"], 12.0)
        self.assertAlmostEqual(distance.at[3, "A"], 9.0 / 12.0 - 1.0)

        ma = pd.Series([10.0, 11.0, 12.0, 13.0])
        slope = ma_slope(ma, 2)
        self.assertAlmostEqual(slope.iloc[3], (13.0 / 11.0 - 1.0) / 2.0)

        position = close_position(
            pd.DataFrame({"A": [10.0, 10.0]}),
            pd.DataFrame({"A": [12.0, 10.0]}),
            pd.DataFrame({"A": [8.0, 10.0]}),
        )
        self.assertAlmostEqual(position.at[0, "A"], 0.5)
        self.assertAlmostEqual(position.at[1, "A"], 0.5)

    def test_deterministic_state_classifiers(self):
        cfg = radar_config({})
        self.assertEqual(cfg["rs"]["windows"], [5, 10, 20, 60, 120])
        self.assertEqual(cfg["industry"]["strengthening_delta_5d"], 0.03)
        self.assertEqual(cfg["industry"]["weakening_delta_10d"], -0.05)
        self.assertEqual(cfg["industry_rs_history"]["watchlist"], [])
        configured = radar_config({"strong_stock_radar": {"industry_rs_history": {"watchlist": [" 半导体 ", "电力设备", ""]}}})
        self.assertEqual(configured["industry_rs_history"]["watchlist"], ["半导体", "电力设备"])
        strong_row = pd.Series(
            {
                "close": 13.0,
                "ma20": 12.0,
                "ma60": 11.0,
                "ma120": 10.0,
                "ma20_slope": 0.01,
                "ma60_slope": 0.005,
            }
        )
        self.assertEqual(trend_state_for_row(strong_row, cfg), "STRONG")
        self.assertEqual(
            volume_price_state_for_row(
                pd.Series({"daily_return": 0.04, "amount_ratio_20d": 1.5, "close_position": 0.8}),
                cfg,
            ),
            "HEALTHY_EXPANSION",
        )
        self.assertEqual(
            stock_state_for_row(
                pd.Series(
                    {
                        "rs60_pct": 95.0,
                        "rs120_pct": 90.0,
                        "rs60_persistence_20d": 0.8,
                        "trend_state": "STRONG",
                        "industry_state": "STRONG",
                        "industry_rs60_pct": 90.0,
                        "distance_to_high_250d": -0.02,
                        "rs60_delta_5d": 0.0,
                        "rs60_delta_10d": 0.0,
                        "volume_price_state": "NORMAL",
                    }
                ),
                cfg,
            ),
            "CORE_STRONG",
        )


class StrongStockRadarBuildTest(unittest.TestCase):
    def _write_market(self, root: Path, symbol: str, closes: np.ndarray, dates: list[str]) -> None:
        frame = pd.DataFrame(
            {
                "date": dates,
                "open": closes * 0.995,
                "high": closes * 1.02,
                "low": closes * 0.98,
                "close": closes,
                "volume": np.full(len(dates), 2_000_000.0),
                "amount": np.full(len(dates), 120_000.0),
            }
        )
        frame.to_csv(root / f"{symbol}.csv", index=False)

    def _config(self, temp: Path) -> dict:
        return {
            "data": {"cache_dir": str(temp / "cache"), "meta_dir": str(temp / "meta")},
            "output": {"statistics_dir": str(temp / "stats"), "reports_dir": str(temp / "reports")},
            "benchmark": {"symbol": "000300.SH"},
            "strong_stock_radar": {
                "history_bars": 400,
                "universe": {"min_listing_days": 120, "min_avg_amount_20d": 50_000_000},
            },
        }

    def _fixture(self, temp: Path, rows: int = 290) -> tuple[dict, list[str]]:
        cache = temp / "cache"
        index_cache = cache / "index"
        meta = temp / "meta"
        cache.mkdir(parents=True)
        index_cache.mkdir(parents=True)
        meta.mkdir(parents=True)
        dates = [date.strftime("%Y%m%d") for date in pd.bdate_range("2020-01-01", periods=rows)]
        base = np.arange(rows, dtype=float)
        self._write_market(cache, "000001.SZ", 10.0 + base * 0.08, dates)
        self._write_market(cache, "000002.SZ", 20.0 + base * 0.02, dates)
        self._write_market(cache, "000003.SZ", 30.0 - base * 0.015, dates)
        benchmark = pd.DataFrame(
            {
                "date": dates,
                "close": 3000.0 + base,
            }
        )
        benchmark.to_csv(index_cache / "000300.SH.csv", index=False)
        pd.DataFrame(
            {
                "ts_code": ["000001.SZ", "000002.SZ", "000003.SZ"],
                "name": ["强势A", "中性B", "弱势C"],
                "industry": ["行业甲", "行业甲", "行业乙"],
            }
        ).to_csv(meta / "stock_basic.csv", index=False)
        return self._config(temp), dates

    def test_build_uses_cache_and_preserves_point_in_time_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            full_root = Path(tmp) / "full"
            truncated_root = Path(tmp) / "truncated"
            full_root.mkdir()
            truncated_root.mkdir()
            full_config, dates = self._fixture(full_root)
            cutoff = dates[250]

            truncated_config, _ = self._fixture(truncated_root, rows=251)
            full = build_strong_stock_radar(full_config, trade_date=cutoff)
            truncated = build_strong_stock_radar(truncated_config, trade_date=cutoff)

            columns = [
                "ts_code",
                "rs5_pct",
                "rs10_pct",
                "rs60_pct",
                "rs120_pct",
                "rs60_delta_5d",
                "trend_state",
                "distance_to_high_250d",
                "state",
            ]
            left = full["stock_snapshot"][columns].sort_values("ts_code").reset_index(drop=True)
            right = truncated["stock_snapshot"][columns].sort_values("ts_code").reset_index(drop=True)
            pd.testing.assert_frame_equal(left, right)
            self.assertEqual(full["trade_date"], cutoff)
            self.assertGreaterEqual(len(full["tradable_universe"]), 3)
            self.assertIn("industry_rs5_pct", full["industry_strength"].columns)
            self.assertIn("industry_rs10_pct", full["industry_strength"].columns)
            self.assertIn("pct_above_ma10", full["industry_strength"].columns)
            history = full["industry_rs_history"]
            self.assertTrue(history["industry_rs60_pct"].dropna().between(0, 100).all())
            self.assertIn("industry_rs60_pct_delta_5d", history.columns)
            self.assertIn("industry_rs120_pct_delta_5d", history.columns)
            self.assertIn("industry_rs5_pct_delta_5d", history.columns)
            self.assertIn("industry_rs10_pct_delta_5d", history.columns)
            self.assertIn("industry_rs5_pct_delta_5d_common", history.columns)
            self.assertIn("industry_rs10_pct_delta_5d_common", history.columns)
            self.assertIn("industry_rs20_pct_delta_5d_common", history.columns)
            self.assertIn("industry_rs60_pct_delta_5d_common", history.columns)
            self.assertIn("industry_rs120_pct_delta_5d_common", history.columns)
            self.assertIn("industry_daily_return", history.columns)
            self.assertIn("pct_advancing", history.columns)
            self.assertIn("industry_rs60_persistence_20d", history.columns)
            self.assertTrue(history["industry_rs60_persistence_20d"].dropna().between(0, 1).all())

    def test_common_delta_uses_one_trade_calendar_without_backfill(self):
        with tempfile.TemporaryDirectory() as tmp:
            config, dates = self._fixture(Path(tmp))
            history = build_strong_stock_radar(config, trade_date=dates[-1])["industry_rs_history"]
            ordered_dates = sorted(history["trade_date"].unique().tolist())
            for field in ("industry_rs5_pct", "industry_rs10_pct", "industry_rs20_pct", "industry_rs60_pct", "industry_rs120_pct"):
                target = f"{field}_delta_5d_common"
                pivot = history.pivot(index="trade_date", columns="industry", values=field).reindex(ordered_dates)
                expected = pivot - pivot.shift(5)
                actual = history.pivot(index="trade_date", columns="industry", values=target).reindex(ordered_dates)
                pd.testing.assert_frame_equal(actual, expected)
                self.assertTrue(actual.iloc[:5].isna().all().all())

    def test_report_includes_short_rs_ma10_and_sort_affordances(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, dates = self._fixture(root)
            radar = build_strong_stock_radar(config, trade_date=dates[-1])
            path = generate_strong_stock_radar_report(
                config,
                radar["trade_date"],
                radar["industry_strength"],
                radar["industry_rs_history"],
                radar["stock_snapshot"],
                pd.DataFrame(),
                radar["market_environment"],
                root / "radar.html",
            )
            report = path.read_text(encoding="utf-8")
            self.assertIn(">RS5<", report)
            self.assertIn(">RS10<", report)
            self.assertIn(">MA10以上<", report)
            self.assertIn("行业 RS 轮动", report)
            self.assertIn("rotationHeatmap", report)
            self.assertIn('id="heatFrequency"', report)
            self.assertIn('id="heatRange"', report)
            self.assertIn('id="heatFilter"', report)
            self.assertIn("watchlist=radarMeta.watchlist||[]", report)
            self.assertIn("function finiteOrNull(value)", report)
            self.assertIn("filter === 'improving'", report)
            self.assertIn("visibleRows.length + '/' + state.validCount", report)
            self.assertIn("RS百分位改善最快", report)
            self.assertIn("当前RS前15", report)
            self.assertIn("高位继续增强", report)
            self.assertIn("低位改善观察", report)
            self.assertIn("高位回落", report)
            self.assertIn("短线动量改善观察", report)
            self.assertIn('id="heatRankChange"', report)
            self.assertIn("industry_rs5_pct_delta_5d_common", report)
            self.assertIn("industry_rs10_pct_delta_5d_common", report)
            self.assertIn("比较日排名", report)
            self.assertIn("实际名次变化", report)
            self.assertIn("当前筛选依据日期", report)
            self.assertIn("const axisOf = row => frequency === 'week' ? weekKey(row.trade_date) : row.trade_date", report)
            self.assertIn("if (!picked[key] || picked[key].trade_date < row.trade_date)", report)
            self.assertIn("value === null ? { value: cell", report)
            self.assertNotIn("slice(0,16)", report)
            self.assertIn('th[data-order="asc"]::after', report)
            self.assertIn("Array.from(table.querySelectorAll('thead th')).indexOf(th)", report)
            self.assertIn("if (av === null && bv === null) return 0;", report)
            self.assertIn("strong-stock-table-wrap", report)
            self.assertIn("max-height:min(70vh,620px)", report)
            self.assertIn("if (av === null) return 1;", report)
            self.assertNotIn('id="rotationDimension"', report)
            self.assertNotIn("conceptHistory", report)
            self.assertNotIn("function selectConcept", report)
            for section_id in (
                "industryHeatSection",
                "strongIndustrySection",
                "industryDetailSection",
                "themeMembersSection",
                "strongStocksSection",
            ):
                self.assertIn(f'<details id="{section_id}"', report)
            self.assertIn("function drawWhenOpen(sectionId, draw)", report)
            self.assertIn("if(section&&section.open)requestAnimationFrame(draw)", report)
            self.assertIn("addEventListener('toggle',event=>{if(event.target.open)requestAnimationFrame(draw);}", report)
            self.assertNotIn("drawHeat();drawDetail();drawThemeStockHeatmap();", report)
            self.assertNotIn("||{{}}", report)


class CustomConceptPoolTest(unittest.TestCase):
    def _metadata(self) -> pd.DataFrame:
        return pd.DataFrame({"ts_code": ["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ", "000005.SZ"]})

    def test_pool_yaml_validates_members_and_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "concepts.yaml"
            path.write_text(
                """settings:\n  min_valid_members: 3\n  min_coverage_ratio: 0.6\n  history_mode: current_snapshot\npools:\n  - id: robot\n    name: 机器人\n    category: 先进制造\n    members: [000001.SZ, 000002.SZ, 000003.SZ, 000003.SZ, 999999.SZ]\n""",
                encoding="utf-8",
            )
            settings, pools, warnings, _ = load_custom_concept_pools({}, self._metadata(), path)
            self.assertEqual(settings.history_mode, "current_snapshot")
            self.assertEqual(pools[0].members, ("000001.SZ", "000002.SZ", "000003.SZ"))
            self.assertTrue(any("重复代码" in warning for warning in warnings))
            self.assertTrue(any("无效" in warning for warning in warnings))

            path.write_text("pools:\n  - id: x\n    name: A\n    members: [000001.SZ]\n  - id: x\n    name: B\n    members: [000002.SZ]\n", encoding="utf-8")
            with self.assertRaises(ConceptPoolConfigError):
                load_custom_concept_pools({}, self._metadata(), path)

    def test_concept_history_equal_weight_and_coverage_rules(self):
        dates = pd.Index([date.strftime("%Y%m%d") for date in pd.bdate_range("2026-01-01", periods=12)])
        close = pd.DataFrame(
            {
                "000001.SZ": np.linspace(10, 14, len(dates)),
                "000002.SZ": np.linspace(10, 13, len(dates)),
                "000003.SZ": np.linspace(10, 12, len(dates)),
                "000004.SZ": np.linspace(10, 11, len(dates)),
                "000005.SZ": np.linspace(10, 10.5, len(dates)),
            },
            index=dates,
        )
        close.loc[dates[-1], "000003.SZ"] = np.nan
        tradable = close.notna()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "concepts.yaml"
            path.write_text(
                """settings:\n  min_valid_members: 3\n  min_coverage_ratio: 0.6\n  history_mode: current_snapshot\npools:\n  - id: alpha\n    name: 概念甲\n    members: [000001.SZ, 000002.SZ, 000003.SZ]\n  - id: beta\n    name: 概念乙\n    members: [000003.SZ, 000004.SZ, 000005.SZ]\n""",
                encoding="utf-8",
            )
            settings, pools, _, _ = load_custom_concept_pools({}, self._metadata(), path)
            history = build_custom_concept_rs_history(
                pools, settings, close, tradable,
                benchmark_returns={5: pd.Series(0.0, index=dates)}, windows=[5],
            )
        self.assertEqual(set(history["concept_name"]), {"概念甲", "概念乙"})
        self.assertTrue(history["concept_rs5_pct"].dropna().between(0, 100).all())
        self.assertIn("concept_rs5_pct_delta_5d_common", history.columns)
        self.assertIn("concept_rs5_previous_denominator", history.columns)
        latest = history[history["trade_date"] == dates[-1]].set_index("concept_id")
        self.assertTrue(pd.isna(latest.at["alpha", "concept_rs_5d"]))
        self.assertEqual(int(latest.at["alpha", "valid_members"]), 2)


if __name__ == "__main__":
    unittest.main()
