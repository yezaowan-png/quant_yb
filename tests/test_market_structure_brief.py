from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from data.downloader import DataDownloader
from cli.index_cli import _select_ths_concept_symbols, run_market_structure_brief
from visual.dashboard import generate_dashboard
from visual.industry_market_report import generate_concept_market_report, generate_industry_market_report
from visual.market_structure_brief import generate_market_structure_brief


def _config(root: Path) -> dict:
    return {
        "tushare": {"token": "test-token"},
        "data": {"cache_dir": str(root / "cache"), "meta_dir": str(root / "meta")},
        "output": {
            "reports_dir": str(root / "reports"),
            "statistics_dir": str(root / "statistics"),
            "trades_dir": str(root / "trades"),
            "signals_dir": str(root / "signals"),
        },
        "rate_limit": {"calls_per_minute": 600, "failed_retry_rounds": 0},
        "parallel": {"download_workers": 1},
        "index_overview": {"indexes": [{"symbol": "000001.SH", "name": "上证指数"}]},
        "industry_market": {"fetch_ths_members": False},
    }


def _structure() -> dict:
    industry = {
        "industry": "银行",
        "stock_count": 40,
        "return_5d": 0.02,
        "return_10d": 0.04,
        "return_20d": 0.05,
        "relative_strength_20d": 0.03,
        "advance_ratio": 0.6,
        "pct_above_ma20": 0.7,
        "leadership_quality": "healthy",
    }
    lift_positive_rows = [
        {
            "symbol": "600000.SH",
            "name": "浦发银行",
            "industry": "银行",
            "index_weight": 0.04,
            "return_1d": 0.03,
            "amount": 120000000,
            "amount_ratio_20d": 1.2,
            "index_contribution": 0.0012,
            "contribution_share": 0.32,
            "amount_share": 0.08,
        }
    ]
    lift_negative_rows = [
        {
            "symbol": "600519.SH",
            "name": "贵州茅台",
            "industry": "白酒",
            "index_weight": 0.03,
            "return_1d": -0.02,
            "amount": 90000000,
            "amount_ratio_20d": 0.9,
            "index_contribution": -0.0006,
            "contribution_share": 0.28,
            "amount_share": 0.06,
        }
    ]
    return {
        "date": "2026-07-21",
        "market_structure": {"headline": "权重偏强，赚钱效应一般。", "breadth_state": "neutral"},
        "indices": {
            "上证指数": {
                "symbol": "000001.SH",
                "available": True,
                "return_1d": 0.01,
                "return_5d": 0.02,
                "return_20d": 0.03,
                "amount_ratio_20d": 1.1,
            }
        },
        "breadth": {
            "latest": {
                "advance_count": 3000,
                "decline_count": 2200,
                "advance_ratio": 0.57,
                "median_stock_return_1d": 0.006,
                "equal_weight_return_1d": 0.01,
            }
        },
        "return_distribution": {
            "state": "broad_rally",
            "latest": {"median": 0.006, "q10": -0.02, "q90": 0.04},
            "histogram": [{"label": "0~3%", "count": 100}],
        },
        "liquidity_structure": {
            "state": "normal",
            "latest": {
                "total_amount": 1234567890,
                "amount_ratio_5d": 1.08,
                "amount_ratio_20d": 1.05,
                "advance_amount_ratio": 0.62,
                "decline_amount_ratio": 0.33,
                "advance_decline_amount_ratio": 1.88,
                "top_10pct_gainer_amount_share": 0.24,
                "top_10pct_loser_amount_share": 0.18,
                "top_10pct_gainer_count": 530,
            },
            "history": [{"trade_date": "2026-07-21", "total_amount": 1234567890, "amount_ratio_5d": 1.08, "amount_ratio_20d": 1.05}],
            "cap_turnover_shares": {"沪深300": 0.31, "中证1000": 0.20, "中证2000": 0.16},
            "style_turnover_shares": {"科技成长": 0.19, "红利价值": 0.11},
            "industry_turnover_shares": [
                {
                    "industry": "银行",
                    "amount_share": 0.12,
                    "amount_share_change_5d": 0.01,
                    "amount_share_change_20d": 0.02,
                    "amount_ratio_20d": 1.2,
                    "return_1d": 0.01,
                }
            ],
            "turnover_migration": [
                {"bucket": "权重宽基", "name": "沪深300", "amount_share": 0.31, "amount_share_change_5d": 0.01, "amount_share_change_20d": -0.02},
                {"bucket": "题材风格", "name": "科技成长", "amount_share": 0.19, "amount_share_change_5d": 0.03, "amount_share_change_20d": 0.04},
            ],
        },
        "industry_structure": {"strongest": [industry], "weakest": [{**industry, "industry": "纺织"}]},
        "industry_rankings": {
            "method_note": "同花顺行业指数行情口径，来源 Tushare ths_daily。",
            "all": [
                {
                    "industry": "银行",
                    "symbol": "884001.TI",
                    "return_1d": 0.03,
                    "return_5d": 0.05,
                    "return_20d": 0.10,
                    "advance_ratio": 0.7,
                    "pct_above_ma20": 0.8,
                    "amount_share_change_20d": 0.01,
                },
                {
                    "industry": "纺织",
                    "symbol": "884002.TI",
                    "return_1d": -0.02,
                    "return_5d": -0.05,
                    "return_20d": -0.08,
                    "advance_ratio": 0.3,
                    "pct_above_ma20": 0.2,
                    "amount_share_change_20d": -0.01,
                },
                {
                    "industry": "电子",
                    "symbol": "884003.TI",
                    "return_1d": 0.01,
                    "return_5d": 0.02,
                    "return_20d": 0.03,
                    "advance_ratio": 0.5,
                    "pct_above_ma20": 0.6,
                    "amount_share_change_20d": 0.02,
                },
            ],
            "strongest": [
                {
                    "industry": "银行",
                    "symbol": "884001.TI",
                    "return_1d": 0.03,
                    "return_5d": 0.05,
                    "return_20d": 0.10,
                    "advance_ratio": 0.7,
                    "pct_above_ma20": 0.8,
                    "amount_share_change_20d": 0.01,
                }
            ],
            "weakest": [
                {
                    "industry": "纺织",
                    "symbol": "884002.TI",
                    "return_1d": -0.02,
                    "return_5d": -0.05,
                    "return_20d": -0.08,
                    "advance_ratio": 0.3,
                    "pct_above_ma20": 0.2,
                    "amount_share_change_20d": -0.01,
                }
            ],
        },
        "index_lift_structure": {
            "symbol": "000001.SH",
            "by_symbol": {
                "000001.SH": {
                    "symbol": "000001.SH",
                    "index_name": "上证指数",
                    "trade_date": "2026-07-21",
                    "returns": {"index_return": 0.01},
                    "contribution_concentration": {
                        "top_10_positive_contribution_share": 0.42,
                        "top_10_signed_index_contribution": 0.006,
                        "top_10_signed_index_return_share": 0.60,
                        "stocks_needed_for_80pct_positive_contribution": 18,
                    },
                    "turnover_confirmation": {
                        "top10_contributor_amount_share": 0.12,
                        "top20_turnover_amount_share": 0.36,
                    },
                    "top_positive_contributors": lift_positive_rows,
                    "top_negative_contributors": lift_negative_rows,
                    "top_turnover_stocks": lift_positive_rows + lift_negative_rows,
                }
            },
        },
    }


class MarketStructureBriefTest(unittest.TestCase):
    def test_brief_contains_requested_full_report_excerpt_screens(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _config(root)
            index_dir = root / "cache" / "index"
            index_dir.mkdir(parents=True)
            pd.DataFrame(
                [
                    {
                        "date": date.strftime("%Y%m%d"),
                        "open": 10 + idx * 0.1,
                        "high": 10.5 + idx * 0.1,
                        "low": 9.5 + idx * 0.1,
                        "close": 10.2 + idx * 0.1,
                        "vol": 100 + idx,
                        "amount": 1000 + idx * 10,
                    }
                    for idx, date in enumerate(pd.bdate_range("2026-01-01", periods=140))
                ]
            ).to_csv(index_dir / "000001.SH.csv", index=False)

            output = generate_market_structure_brief(config, _structure(), root / "reports" / "index_forecast" / "brief.html")
            html = output.read_text(encoding="utf-8")
            for title in ("指数趋势与技术结构", "分层市场广度", "横截面收益分布", "风格轮动、领涨质量与行业结构"):
                self.assertIn(title, html)
            self.assertNotIn("第2屏", html)
            self.assertNotIn("第3屏", html)
            self.assertNotIn("第4屏", html)
            self.assertNotIn("第5屏", html)
            self.assertIn('class="panel brief-section" data-section="index-technical" open', html)
            self.assertIn('class="panel brief-section" data-section="layered-breadth" open', html)
            self.assertIn('class="panel brief-section" data-section="style-and-structure" open', html)
            self.assertIn("window.dispatchEvent(new Event('resize'))", html)
            self.assertNotIn("市场广度明细", html)
            self.assertIn("forecast-kline", html)
            self.assertIn("structure-layered-breadth", html)
            self.assertNotIn("按10日强弱排序", html)
            self.assertNotIn("同花顺行业指数代理；按当日强弱排序", html)
            self.assertIn("structure-return-distribution", html)
            self.assertIn("风格轮动状态", html)
            self.assertNotIn('id="structure-style"', html)
            self.assertNotIn("兼容版市场风格", html)
            self.assertNotIn("行业结构 v2", html)
            self.assertNotIn("银行、保险与证券", html)
            self.assertIn("brief-distribution-grid", html)
            self.assertIn("指数涨跌与成交贡献", html)
            self.assertIn("上涨贡献前20", html)
            self.assertIn("下跌拖累前20", html)
            self.assertIn("成交额前20", html)
            self.assertIn("成交额结构", html)
            self.assertIn("总成交额 / 5日 / 20日均额", html)
            self.assertIn("12,346亿", html)
            self.assertNotIn("1,234,567,890 / 1.08倍 / 1.05倍", html)
            self.assertIn("function compactTushareAmount(v)", html)
            self.assertIn("tooltip:{valueFormatter:compactTushareAmount}", html)
            self.assertIn("三市总成交额", html)
            self.assertIn("三市总额5日均额", html)
            self.assertIn("三市总额20日均额", html)
            self.assertIn("function rollingMarketAmount(values,windowSize)", html)
            self.assertIn("量额比", html)
            self.assertIn("market_total_amount", html)
            self.assertIn("axisPointer:{link:[{xAxisIndex:[0,1,2,3,4]}]}", html)
            self.assertIn("axis.axisPointer={show:true,type:'line',snap:true", html)
            self.assertIn("量额比',3,volumeAmountRatio", html)
            self.assertIn("三市总额',4,compactTushareAmount", html)

            industry_output = generate_industry_market_report(config, _structure(), root / "reports" / "industry" / "industry_market.html")
            industry_html = industry_output.read_text(encoding="utf-8")
            self.assertIn("{type: 'inside', xAxisIndex: [0,1,2], start, end: 100}", industry_html)
            self.assertNotIn("function bindIndustryStockPointerZoom", industry_html)
            self.assertIn("function forecastKlineTooltip(params,d)", html)
            self.assertIn("forecastIndexName()+(change>=0?'上涨 ':'下跌 ')", html)
            self.assertIn("沪深300 / 中证1000 / 中证2000成交占比", html)
            self.assertIn("涨幅前10% / 跌幅前10%成交集中度", html)
            self.assertIn("行业成交额增量排名", html)
            self.assertIn("权重板块与题材板块成交额迁移", html)
            self.assertIn("5日变化百分点", html)
            self.assertIn("20日变化百分点", html)
            self.assertNotIn("日内 5min K", html)

    def test_dashboard_generates_and_links_brief(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _config(root)
            for key in ("reports_dir", "statistics_dir", "trades_dir", "signals_dir"):
                Path(config["output"][key]).mkdir(parents=True, exist_ok=True)
            stats = root / "statistics" / "index_forecast"
            reports = root / "reports" / "index_forecast"
            cache = root / "cache" / "index"
            stats.mkdir(parents=True)
            reports.mkdir(parents=True)
            cache.mkdir(parents=True)
            (stats / "market_structure_000001.SH.json").write_text(json.dumps(_structure(), ensure_ascii=False), encoding="utf-8")
            (reports / "000001.SH_market_structure.html").write_text("full", encoding="utf-8")
            pd.DataFrame([{"date": "20260721", "open": 10, "high": 12, "low": 9, "close": 11, "vol": 100}]).to_csv(
                cache / "000001.SH.csv", index=False
            )
            dashboard = generate_dashboard(config)
            html = dashboard.read_text(encoding="utf-8")
            self.assertIn("市场结构摘录", html)
            self.assertIn("行业行情", html)
            self.assertIn("备用报告入口", html)
            self.assertIn("强势股雷达", html)
            self.assertIn("涨停强势", html)
            self.assertIn("支撑压力", html)
            self.assertIn("股票查看器", html)
            self.assertIn("industry/industry_market.html", html)
            report_section = html[html.index('id="report-entry"'):]
            primary_links = report_section[:report_section.index('<details class="report-entry-backup">')]
            for label in ("市场结构摘录", "行业行情", "强势股雷达", "涨停强势", "支撑压力", "股票查看器"):
                self.assertIn(label, primary_links)
            for label in ("大盘环境", "概念行情", "板块资金流", "ETF 策略板块", "完整市场结构", "数据质量", "项目优化审计"):
                self.assertNotIn(label, primary_links)
            self.assertTrue((reports / "000001.SH_market_structure_brief.html").exists())
            self.assertTrue((root / "reports" / "industry" / "industry_market.html").exists())

    def test_industry_market_report_contains_rankings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _config(root)
            index_dir = root / "cache" / "index"
            index_dir.mkdir(parents=True)
            for symbol in ("884001.TI", "884002.TI"):
                pd.DataFrame(
                    [
                        {
                            "date": date.strftime("%Y%m%d"),
                            "open": 10 + idx * 0.1,
                            "high": 10.5 + idx * 0.1,
                            "low": 9.5 + idx * 0.1,
                            "close": 10.2 + idx * 0.1,
                            "vol": 100 + idx,
                            "amount": 1000 + idx * 10,
                        }
                        for idx, date in enumerate(pd.bdate_range("2026-01-01", periods=140))
                    ]
                ).to_csv(index_dir / f"{symbol}.csv", index=False)
            selector_csv = root / "selector.csv"
            pd.DataFrame(
                [
                    {
                        "股票代码": "000001.SZ",
                        "股票简称": "平安银行",
                        "一级行业": "银行",
                        "二级行业": "银行",
                        "三级行业": "股份制银行",
                        "行业板块": "银行|股份制银行",
                        "概念板块": "融资融券|深股通",
                        "最新价": "11.08",
                        "最新涨跌幅": "1.23",
                    },
                    {
                        "股票代码": "600000.SH",
                        "股票简称": "浦发银行",
                        "一级行业": "银行",
                        "二级行业": "银行",
                        "三级行业": "股份制银行",
                        "行业板块": "银行|股份制银行",
                        "概念板块": "沪股通",
                        "最新价": "9.87",
                        "最新涨跌幅": "-0.45",
                    },
                ]
            ).to_csv(selector_csv, index=False)
            config["dashboard"] = {"stock_selector": {"csv_path": str(selector_csv)}}
            ths_member_dir = root / "meta" / "ths_members"
            ths_member_dir.mkdir(parents=True)
            pd.DataFrame(
                [
                    {
                        "ts_code": "884001.TI",
                        "con_code": "000001.SZ",
                        "con_name": "平安银行",
                    }
                ]
            ).to_csv(ths_member_dir / "884001.TI.csv", index=False)
            stock_kline_dir = root / "reports" / "stock_kline"
            stock_kline_dir.mkdir(parents=True)
            (stock_kline_dir / "000001.SZ.html").write_text("kline", encoding="utf-8")
            stock_cache_dir = root / "cache"
            stock_cache_dir.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(
                [
                    {
                        "date": date.strftime("%Y%m%d"),
                        "open": 10 + idx * 0.05,
                        "high": 10.3 + idx * 0.05,
                        "low": 9.8 + idx * 0.05,
                        "close": 10.1 + idx * 0.05,
                        "volume": 1000 + idx * 10,
                        "amount": 12000 + idx * 100,
                    }
                    for idx, date in enumerate(pd.bdate_range("2026-01-01", periods=140))
                ]
            ).to_csv(stock_cache_dir / "000001.SZ.csv", index=False)
            daily_basic_dir = root / "meta" / "daily_basic"
            daily_basic_dir.mkdir(parents=True)
            pd.DataFrame(
                [
                    {
                        "ts_code": "000001.SZ",
                        "trade_date": "20260721",
                        "total_mv": 20376210,
                        "circ_mv": 20375880,
                        "pe": 4.78,
                        "pe_ttm": 4.73,
                        "pb": 0.44,
                        "turnover_rate": 2.34,
                    }
                ]
            ).to_csv(daily_basic_dir / "000001.SZ.csv", index=False)

            output = generate_industry_market_report(config, _structure(), root / "reports" / "industry" / "industry_market.html")
            html = output.read_text(encoding="utf-8")
            self.assertIn("行业行情", html)
            self.assertIn("概念行情", html)
            self.assertIn("关注池行情", html)
            self.assertIn("行业强弱榜", html)
            self.assertIn("switchThsMarketMode('concept')", html)
            self.assertIn("switchThsMarketMode('watch')", html)
            self.assertIn("concept_market_data.js", html)
            self.assertIn("window._THS_MARKET_MODE_DATA", html)
            self.assertIn("buildThsWatchModeData", html)
            self.assertIn("data-ths-market-mode=\"watch\"", html)
            self.assertIn("ths-market-mode-btn", html)
            self.assertIn("ths-market-ranking-title", html)
            self.assertIn("ths-market-search", html)
            self.assertIn("filterThsMarketRows", html)
            self.assertIn("toggleThsWatch", html)
            self.assertIn("ths-watch-pool-chips", html)
            self.assertIn("quantyb:ths_market_watch_pool:v1", html)
            self.assertIn("data-ths-symbol", html)
            self.assertIn("data-ths-search", html)
            self.assertIn("ths-watch-btn", html)
            self.assertIn("只看关注", html)
            self.assertIn("银行", html)
            self.assertIn("纺织", html)
            self.assertIn("电子", html)
            self.assertIn("industry-market-table", html)
            self.assertIn("sortIndustryMarketTable", html)
            self.assertIn("点击表头可排序", html)
            self.assertIn("股票查看", html)
            self.assertIn("switchThsMarketMode('stock')", html)
            self.assertIn("#stock", html)
            self.assertIn("ths-market-pane", html)
            self.assertIn("embedded-stock-viewer", html)
            self.assertIn("stock-viewer-data", html)
            self.assertIn("viewer-search-input", html)
            self.assertIn("viewer-board-input", html)
            self.assertIn("viewer-board-delete", html)
            self.assertIn("deleteCurrentBoard", html)
            self.assertNotIn("viewer-frame", html)
            self.assertIn("stock_data_href", html)
            self.assertIn("quantyb:stock_selector_custom_boards:v1", html)
            self.assertIn("['turnover_rate','换手','num']", html)
            self.assertIn("['amount_1d','成交额','num']", html)
            self.assertIn("2.34%", html)
            self.assertIn("换手", html)
            self.assertIn("industry-amount-head", html)
            self.assertIn("industry-sort-chip", html)
            self.assertIn(">当日</div>", html)
            self.assertIn(">5日</div>", html)
            self.assertIn(">10日</div>", html)
            self.assertIn("industry-amount-cell", html)
            self.assertIn("data-key=\"amount_1d\"", html)
            self.assertIn("data-key=\"amount_1d_share\"", html)
            self.assertIn("data-key=\"amount_1d_avg\"", html)
            self.assertIn("data-key=\"amount_5d\"", html)
            self.assertIn("data-key=\"amount_5d_share\"", html)
            self.assertIn("data-key=\"amount_5d_avg\"", html)
            self.assertIn("data-key=\"amount_10d\"", html)
            self.assertIn("data-key=\"amount_10d_share\"", html)
            self.assertIn("data-key=\"amount_10d_avg\"", html)
            self.assertIn("2590.00万", html)
            self.assertIn("1.28亿", html)
            self.assertIn("2.54亿", html)
            self.assertIn("占比为当前表内全部行业成交额占比", html)
            self.assertNotIn("['tags','标签'", html)
            self.assertNotIn("最强行业</th>", html)
            self.assertNotIn("最弱行业</th>", html)
            self.assertIn("industry-kline", html)
            self.assertIn("行业 K 线图点击画线", html)
            self.assertIn("setForecastManualTool('trend')", html)
            self.assertIn("forecastManualUndo()", html)
            self.assertIn("884001.TI", html)
            self.assertIn("industry-market-overview-grid", html)
            self.assertIn("industry-member-panel", html)
            self.assertIn("window._INDUSTRY_MEMBERS", html)
            self.assertIn("Tushare ths_member", html)
            self.assertIn("本地日线缓存优先", html)
            self.assertIn('"quote_source":"本地日线缓存"', html)
            self.assertIn("平安银行", html)
            self.assertNotIn('"symbol":"600000.SH","name":"浦发银行"', html)
            self.assertIn('"symbol": "600000.SH"', html)
            self.assertIn('"pct_chg":0.294', html)
            self.assertNotIn('"pct_chg":1.23', html)
            self.assertIn("../stock_kline/000001.SZ.html", html)
            self.assertIn("2,038亿", html)
            self.assertIn("PE", html)
            self.assertIn("industry-member-table", html)
            self.assertIn("sortIndustryMembers", html)
            self.assertIn("data-member-key", html)
            self.assertIn('"market_cap":20376210.0', html)
            self.assertNotIn("industry-stock-kline-frame", html)
            self.assertIn("industry-stock-kline-chart", html)
            self.assertIn("window._INDUSTRY_STOCK_KLINES", html)
            self.assertIn("stock_kline_data/000001.SZ.js", html)
            self.assertIn("function zoom(d,indexes){var target=760", html)
            self.assertIn("visibleBars = period === '1w' ? 156 : period === '1m' ? 36 : 760", html)
            stock_payload = root / "reports" / "industry" / "stock_kline_data" / "000001.SZ.js"
            self.assertIn('"bar_limit":760', stock_payload.read_text(encoding="utf-8"))
            self.assertIn("selectIndustryStockKline", html)
            self.assertIn("loadIndustryStockKlineData", html)
            self.assertIn("renderIndustryStockKline", html)
            self.assertIn("industry-stock-drawing-layer", html)
            self.assertIn("industryStockSetDrawMode('trend')", html)
            self.assertIn("quantyb:stock_kline_drawings:", html)
            self.assertIn("industryStockRenderDrawings", html)
            self.assertIn("switchIndustryTimeframe('1w')", html)
            self.assertIn("switchIndustryTimeframe('1mo')", html)
            self.assertIn('"1mo"', html)
            self.assertIn("switchIndustryStockPeriod('1w')", html)
            self.assertIn("switchIndustryStockPeriod('1m')", html)
            self.assertIn("'BOLL','成交量','成交额'", html)
            self.assertIn("bindIndustryStockLegendGroups", html)
            self.assertIn("params.name !== 'BOLL'", html)
            self.assertIn("restoreIndustryIndexKline", html)
            self.assertIn("industry-member-stock-row", html)
            stock_data_js = root / "reports" / "industry" / "stock_kline_data" / "000001.SZ.js"
            self.assertTrue(stock_data_js.exists())
            concept_data_js = root / "reports" / "industry" / "concept_market_data.js"
            self.assertTrue(concept_data_js.exists())
            concept_data_text = concept_data_js.read_text(encoding="utf-8")
            self.assertIn("window._THS_MARKET_MODE_DATA", concept_data_text)
            self.assertIn("概念强弱榜", concept_data_text)
            self.assertIn("当前概念没有可用官方成分股", concept_data_text)
            stock_data_text = stock_data_js.read_text(encoding="utf-8")
            self.assertIn('"timeframes"', stock_data_text)
            self.assertIn('"1w"', stock_data_text)
            self.assertIn('"1m"', stock_data_text)
            self.assertIn('"boll_upper"', stock_data_text)
            self.assertIn('"boll_mid"', stock_data_text)
            self.assertIn('"boll_lower"', stock_data_text)
            self.assertIn('"ma5"', stock_data_text)
            self.assertIn('"ohlc"', stock_data_text)
            stock_payload = json.loads(stock_data_text.split("]=", 1)[1].rstrip(";"))
            daily_payload = stock_payload["timeframes"]["1d"]
            boll_points = zip(
                daily_payload["boll_upper"],
                daily_payload["boll_mid"],
                daily_payload["boll_lower"],
                strict=False,
            )
            self.assertTrue(
                all(
                    upper is None
                    or mid is None
                    or lower is None
                    or upper >= mid >= lower
                    for upper, mid, lower in boll_points
                )
            )

    def test_concept_market_report_uses_ths_concept_indices(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _config(root)
            config["ths_indices"] = {
                "concepts": {"exchange": "A", "type": "N", "min_count": 1},
            }
            index_dir = root / "cache" / "index"
            index_dir.mkdir(parents=True)
            for symbol, base in (("885001.TI", 10.0), ("885002.TI", 20.0)):
                pd.DataFrame(
                    [
                        {
                            "date": date.strftime("%Y%m%d"),
                            "open": base + idx * 0.1,
                            "high": base + 0.5 + idx * 0.1,
                            "low": base - 0.5 + idx * 0.1,
                            "close": base + 0.2 + idx * 0.1,
                            "vol": 100 + idx,
                            "amount": 1000 + idx * 10,
                        }
                        for idx, date in enumerate(pd.bdate_range("2026-01-01", periods=140))
                    ]
                ).to_csv(index_dir / f"{symbol}.csv", index=False)
            meta_dir = root / "meta"
            meta_dir.mkdir(parents=True)
            pd.DataFrame(
                [
                    {"ts_code": "885001.TI", "name": "机器人概念", "count": 2, "exchange": "A", "type": "N"},
                    {"ts_code": "885002.TI", "name": "AI概念", "count": 3, "exchange": "A", "type": "N"},
                    {"ts_code": "884001.TI", "name": "银行", "count": 40, "exchange": "A", "type": "I"},
                ]
            ).to_csv(meta_dir / "ths_indices.csv", index=False)
            ths_member_dir = meta_dir / "ths_members"
            ths_member_dir.mkdir(parents=True)
            pd.DataFrame(
                [
                    {
                        "ts_code": "885001.TI",
                        "con_code": "000001.SZ",
                        "con_name": "平安银行",
                    }
                ]
            ).to_csv(ths_member_dir / "885001.TI.csv", index=False)
            selector_csv = root / "selector.csv"
            pd.DataFrame(
                [
                    {
                        "股票代码": "000001.SZ",
                        "股票简称": "平安银行",
                        "一级行业": "银行",
                        "二级行业": "银行",
                        "三级行业": "股份制银行",
                        "行业板块": "银行|股份制银行",
                        "概念板块": "机器人概念|融资融券",
                        "最新价": "11.08",
                        "最新涨跌幅": "1.23",
                    },
                    {
                        "股票代码": "600000.SH",
                        "股票简称": "浦发银行",
                        "一级行业": "银行",
                        "二级行业": "银行",
                        "三级行业": "股份制银行",
                        "行业板块": "银行|股份制银行",
                        "概念板块": "沪股通",
                        "最新价": "9.87",
                        "最新涨跌幅": "-0.45",
                    },
                ]
            ).to_csv(selector_csv, index=False)
            config["dashboard"] = {"stock_selector": {"csv_path": str(selector_csv)}}
            stock_cache_dir = root / "cache"
            stock_cache_dir.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(
                [
                    {
                        "date": date.strftime("%Y%m%d"),
                        "open": 10 + idx * 0.05,
                        "high": 10.3 + idx * 0.05,
                        "low": 9.8 + idx * 0.05,
                        "close": 10.1 + idx * 0.05,
                        "volume": 1000 + idx * 10,
                        "amount": 12000 + idx * 100,
                    }
                    for idx, date in enumerate(pd.bdate_range("2026-01-01", periods=140))
                ]
            ).to_csv(stock_cache_dir / "000001.SZ.csv", index=False)

            output = generate_concept_market_report(config, _structure(), root / "reports" / "concept" / "concept_market.html")
            html = output.read_text(encoding="utf-8")
            self.assertIn("概念行情", html)
            self.assertIn("概念强弱榜", html)
            self.assertIn("机器人概念", html)
            self.assertIn("AI概念", html)
            self.assertNotIn("884001.TI", html)
            self.assertIn("同花顺概念指数代理", html)
            self.assertIn("点击上方概念行查看K线", html)
            self.assertIn("返回概念指数K线", html)
            self.assertIn("window._THS_MARKET_LABEL=\"概念\"", html)
            self.assertIn("Tushare ths_member", html)
            self.assertIn("平安银行", html)
            self.assertNotIn('"symbol":"600000.SH","name":"浦发银行"', html)
            self.assertIn('"symbol": "600000.SH"', html)
            self.assertNotIn("本地股票池概念标签近似匹配", html)
            self.assertIn("当前概念没有可用官方成分股", html)
            self.assertIn("switchIndustryTimeframe('1w')", html)
            self.assertIn("switchIndustryTimeframe('1mo')", html)
            self.assertTrue((root / "reports" / "concept" / "stock_kline_data" / "000001.SZ.js").exists())

    def test_ths_concept_include_file_filters_download_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _config(root)
            config["ths_indices"] = {
                "concepts": {"exchange": "A", "type": "N", "min_count": 1, "include_path": "ths_concept_include.csv"},
            }
            meta_dir = root / "meta"
            meta_dir.mkdir(parents=True)
            index_list = pd.DataFrame(
                [
                    {"ts_code": "885001.TI", "name": "机器人概念", "count": 2, "exchange": "A", "type": "N"},
                    {"ts_code": "885002.TI", "name": "AI概念", "count": 3, "exchange": "A", "type": "N"},
                ]
            )
            index_list.to_csv(meta_dir / "ths_indices.csv", index=False)
            pd.DataFrame([{"ts_code": "885001.TI", "name": "机器人概念", "count": 2}]).to_csv(
                meta_dir / "ths_concept_include.csv",
                index=False,
            )
            self.assertEqual(_select_ths_concept_symbols(index_list, config), ["885001.TI"])

            index_dir = root / "cache" / "index"
            index_dir.mkdir(parents=True)
            for symbol, base in (("885001.TI", 10.0), ("885002.TI", 20.0)):
                pd.DataFrame(
                    [
                        {
                            "date": date.strftime("%Y%m%d"),
                            "open": base + idx * 0.1,
                            "high": base + 0.5 + idx * 0.1,
                            "low": base - 0.5 + idx * 0.1,
                            "close": base + 0.2 + idx * 0.1,
                            "vol": 100 + idx,
                            "amount": 1000 + idx * 10,
                        }
                        for idx, date in enumerate(pd.bdate_range("2026-01-01", periods=140))
                    ]
                ).to_csv(index_dir / f"{symbol}.csv", index=False)

            output = generate_concept_market_report(config, _structure(), root / "reports" / "concept" / "concept_market.html")
            html = output.read_text(encoding="utf-8")
            self.assertIn("机器人概念", html)
            self.assertNotIn("AI概念", html)

    def test_brief_can_be_generated_without_full_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _config(root)
            for key in ("reports_dir", "statistics_dir", "trades_dir", "signals_dir"):
                Path(config["output"][key]).mkdir(parents=True, exist_ok=True)
            stats = root / "statistics" / "index_forecast"
            cache = root / "cache" / "index"
            stats.mkdir(parents=True)
            cache.mkdir(parents=True)
            (stats / "market_structure_000001.SH.json").write_text(
                json.dumps(_structure(), ensure_ascii=False),
                encoding="utf-8",
            )
            pd.DataFrame(
                [
                    {
                        "date": date.strftime("%Y%m%d"),
                        "open": 10 + idx * 0.1,
                        "high": 10.5 + idx * 0.1,
                        "low": 9.5 + idx * 0.1,
                        "close": 10.2 + idx * 0.1,
                        "vol": 100 + idx,
                    }
                    for idx, date in enumerate(pd.bdate_range("2026-01-01", periods=130))
                ]
            ).to_csv(cache / "000001.SH.csv", index=False)

            output = run_market_structure_brief(config)
            html = output.read_text(encoding="utf-8")
            self.assertIn("市场结构摘录", html)
            self.assertIn("指数趋势与技术结构", html)
            self.assertNotIn("第2屏", html)
            self.assertNotIn("完整市场结构报告", html)

    def test_index_intraday_download_is_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            downloader = DataDownloader(_config(Path(tmp)))
            raw = pd.DataFrame(
                [{"ts_code": "000001.SH", "trade_time": "2026-07-21 09:35:00", "open": 10, "high": 11, "low": 9, "close": 10.5, "vol": 10}]
            )
            downloader.tushare_client.call_primary = lambda symbol, api_name, call: call(object())
            with patch("data.downloader.ts.pro_bar", return_value=raw) as pro_bar:
                first = downloader.download_index_intraday("000001.SH", "2026-07-21", "5min")
                second = downloader.download_index_intraday("000001.SH", "2026-07-21", "5min")
            self.assertEqual(len(first), 1)
            self.assertEqual(len(second), 1)
            pro_bar.assert_called_once()
            self.assertTrue(downloader._index_intraday_path("000001.SH", "5min").exists())
