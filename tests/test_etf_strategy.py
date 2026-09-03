import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from click.testing import CliRunner

from etf_strategy.data_provider import EtfDataProvider
from etf_strategy.config import resolve_ftp_config
from etf_strategy.models import RankResult
from etf_strategy.portfolio import order_intents_from_ranking, order_intents_from_rank_signal
from etf_strategy.runner import run_etf_strategy_report
from etf_strategy.signal_provider import ExternalSignalProvider, parse_rank_emotion_frame, red_green_decision
from etf_strategy.strategies import macd_timing, momentum_rotation, three_factor_rotation
from main import cli as root_cli
from visual.dashboard import generate_dashboard


def _config(root: Path) -> dict:
    cache_dir = root / "cache"
    reports_dir = root / "reports"
    stats_dir = root / "statistics"
    trades_dir = root / "trades"
    signals_dir = root / "signals"
    for path in (cache_dir / "etf", reports_dir, stats_dir, trades_dir, signals_dir):
        path.mkdir(parents=True, exist_ok=True)
    return {
        "data": {"cache_dir": str(cache_dir), "meta_dir": str(root / "meta")},
        "output": {
            "reports_dir": str(reports_dir),
            "statistics_dir": str(stats_dir),
            "trades_dir": str(trades_dir),
            "signals_dir": str(signals_dir),
        },
        "index_overview": {"indexes": []},
        "etf_strategy": {
            "cache_dir": str(cache_dir / "etf"),
            "holdings_dir": str(root / "meta" / "etf_holdings"),
            "pool": [
                {"symbol": "515880.SH", "name": "通信ETF"},
                {"symbol": "159919.SZ", "name": "沪深300ETF"},
                {"symbol": "588200.SH", "name": "科创芯片ETF"},
            ],
        },
    }


def _write_etf_cache(config: dict, symbol: str, start_price: float, step: float) -> None:
    rows = []
    for idx in range(70):
        close = start_price + idx * step
        rows.append(
            {
                "date": (pd.Timestamp("2026-01-01") + pd.Timedelta(days=idx)).strftime("%Y%m%d"),
                "open": close * 0.99,
                "high": close * 1.02,
                "low": close * 0.98,
                "close": close,
                "volume": 1000 + idx * 10,
            }
        )
    pd.DataFrame(rows).to_csv(Path(config["etf_strategy"]["cache_dir"]) / f"{symbol}.csv", index=False)


class EtfStrategyIntegrationTest(unittest.TestCase):
    def test_provider_returns_standard_daily_bars_from_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(Path(tmp))
            _write_etf_cache(config, "515880.SH", 1.0, 0.01)

            frame = EtfDataProvider(config).get_daily_bars("515880.SH")

            self.assertEqual(list(frame.columns), ["Open", "High", "Low", "Close", "Volume"])
            self.assertIsInstance(frame.index, pd.DatetimeIndex)
            self.assertGreater(len(frame), 50)

    def test_macd_and_momentum_rotation_emit_signal_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(Path(tmp))
            _write_etf_cache(config, "515880.SH", 1.0, 0.02)
            _write_etf_cache(config, "159919.SZ", 1.0, 0.01)
            _write_etf_cache(config, "588200.SH", 1.0, -0.002)
            provider = EtfDataProvider(config)
            data = {symbol: provider.get_daily_bars(symbol) for symbol in ("515880.SH", "159919.SZ", "588200.SH")}

            macd = macd_timing(data["515880.SH"])
            rotation = momentum_rotation(data, momentum_window=20, hold_period=5, hold_count=2)

            self.assertIn("Signal", macd["data"].columns)
            self.assertIn("Signal", rotation["signals"]["515880.SH"].columns)
            self.assertFalse(rotation["ranking"].empty)
            self.assertIn("momentum", rotation["ranking"].columns)
            self.assertEqual(int(rotation["signals"]["515880.SH"]["Signal"].iloc[-1]), -1)

    def test_three_factor_rotation_uses_prior_data_and_emits_daily_ranking(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(Path(tmp))
            symbols = ["515880.SH", "159919.SZ", "588200.SH", "513000.SH", "512760.SH"]
            for idx, symbol in enumerate(symbols, start=1):
                _write_etf_cache(config, symbol, 1.0 + idx * 0.05, 0.002 * idx)
            provider = EtfDataProvider(config)
            data = {symbol: provider.get_daily_bars(symbol) for symbol in symbols}

            result = three_factor_rotation(data, trend_window=15, momentum_short=5, momentum_long=10, volume_short=5, volume_long=15)

            self.assertEqual(set(result["signals"]), set(symbols))
            for frame in result["signals"].values():
                self.assertIn("Signal", frame.columns)
            self.assertFalse(result["ranking"].empty)
            self.assertIn("score_norm", result["ranking"].columns)
            first_signal_date = min(result["ranking"]["date"])
            first_symbol = result["ranking"].loc[result["ranking"]["date"] == first_signal_date, "symbol"].iloc[0]
            self.assertLess(data[first_symbol].loc[data[first_symbol].index < first_signal_date].index.max(), first_signal_date)

    def test_report_outputs_etf_panel_and_dashboard_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _config(root)
            _write_etf_cache(config, "515880.SH", 1.0, 0.02)
            _write_etf_cache(config, "159919.SZ", 1.0, 0.01)
            _write_etf_cache(config, "588200.SH", 1.0, -0.002)
            holdings_dir = Path(config["etf_strategy"]["holdings_dir"])
            holdings_dir.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(
                [
                    {
                        "symbol": "600519.SH",
                        "stock_name": "贵州茅台",
                        "mkv": 1000000,
                        "amount": 1000,
                        "weight": "12.34%",
                        "end_date": "20260331",
                    }
                ]
            ).to_csv(holdings_dir / "515880.SH.csv", index=False)

            result = run_etf_strategy_report(config)
            dashboard = generate_dashboard(config)
            dashboard_html = dashboard.read_text(encoding="utf-8")
            report_html = Path(result["report_path"]).read_text(encoding="utf-8")
            summary = pd.read_csv(result["summary_path"])

            self.assertTrue(Path(result["summary_path"]).exists())
            self.assertIn("category", summary.columns)
            self.assertIn("subcategory", summary.columns)
            self.assertIn("ETF 策略研究板块", report_html)
            self.assertIn("ETF 分类池", report_html)
            self.assertIn("window._ETF_KLINES=", report_html)
            self.assertIn('id="etf-kline-chart"', report_html)
            self.assertIn('class="etf-row"', report_html)
            self.assertIn('class="category-tab active"', report_html)
            self.assertIn('class="mini-etf-switcher"', report_html)
            self.assertIn('class="mini-etf-chip"', report_html)
            self.assertIn('<details class="holdings-panel">', report_html)
            self.assertIn("MA5", report_html)
            self.assertIn("MA10", report_html)
            self.assertIn("BOLL上轨", report_html)
            self.assertIn('"boll_upper"', report_html)
            self.assertIn('"holdings"', report_html)
            self.assertIn("贵州茅台", report_html)
            self.assertIn("MACD", report_html)
            self.assertIn("双KAMA", report_html)
            self.assertIn("zoomStart", report_html)
            self.assertIn("barData", report_html)
            self.assertIn("mini-etf-chip", report_html)
            self.assertIn("画线", report_html)
            self.assertIn("data-draw-tool=\"trend\"", report_html)
            self.assertIn("data-draw-tool=\"select\"", report_html)
            self.assertIn("setEtfDrawTool", report_html)
            self.assertIn("etfDrawUndo", report_html)
            self.assertIn("quantyb.etf-manual-draw.v1.", report_html)
            self.assertIn("动量轮动策略", report_html)
            self.assertIn("三因子轮动策略", report_html)
            momentum_section = report_html.split("<h2>动量轮动策略</h2>", 1)[1].split("<h2>三因子轮动策略</h2>", 1)[0]
            factor_section = report_html.split("<h2>三因子轮动策略</h2>", 1)[1].split("<h2>外部三因子排名抄作业</h2>", 1)[0]
            self.assertIn("<th>ETF 名称 / 代码</th>", momentum_section)
            self.assertIn("<strong>通信ETF</strong><span>515880.SH</span>", momentum_section)
            self.assertIn("<th>ETF 名称 / 代码</th>", factor_section)
            self.assertIn("<strong>通信ETF</strong><span>515880.SH</span>", factor_section)
            self.assertIn("<strong>通信ETF</strong><span>515880.SH</span>", report_html)
            self.assertIn("<strong>沪深300ETF</strong><span>159919.SZ</span>", report_html)
            self.assertNotIn("ETF 策略总览", report_html)
            self.assertIn("ETF 策略板块", dashboard_html)
            self.assertIn("etf_strategy/etf_strategy_dashboard.html", dashboard_html)

    def test_root_cli_exposes_etf_group(self):
        result = CliRunner().invoke(root_cli, ["etf", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("ETF 策略研究", result.output)
        self.assertIn("signals", result.output)

    def test_ranking_can_be_converted_to_order_intents_without_broker_side_effects(self):
        ranking = [
            RankResult(symbol="515880.SH", name="通信ETF", rank=1, score=1.2, target=True, strategy="三因子排名"),
            RankResult(symbol="588200.SH", name="科创芯片ETF", rank=2, score=0.8, target=True, strategy="三因子排名", raw={"status": "上涨趋缓"}),
        ]
        positions = pd.DataFrame([{"symbol": "515880.SH", "amount": 1000}])

        intents = order_intents_from_ranking(
            ranking,
            positions,
            buy_amount=1_000_000,
            trend_position_pct={"上涨趋缓": 20},
        )

        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0].symbol, "588200.SH")
        self.assertEqual(intents[0].side, "buy")
        self.assertEqual(intents[0].amount, 200_000)

    def test_red_green_wide_file_and_rank_emotion_drive_mock_order_intents(self):
        red_green = pd.DataFrame(
            {
                "2026-01-03": ["0.60|抄"],
                "2026-01-02": ["0.26"],
                "2026-01-01": ["0.27"],
            },
            index=["通信ETF[515880] 抄底"],
        )
        decision = red_green_decision(red_green, "515880.SH")
        self.assertEqual(decision["action"], "buy")
        self.assertTrue(any("抄" in reason or "提前买入" in reason for reason in decision["reasons"]))

        rank_frame = pd.DataFrame(
            {"排名变化": ["→", "↑5", "→", "↓2"]},
            index=[
                "通信ETF[515880] 上涨趋势",
                "科创芯片ETF[588200] 砸 上涨趋缓",
                "沪深300ETF[159919] 砸 下跌趋势",
                "证券ETF[512880] 上涨趋势",
            ],
        )
        rank = parse_rank_emotion_frame(rank_frame, top_n=3)
        self.assertEqual(len(rank["ranking"]), 3)
        self.assertEqual(rank["new_entries"][0]["symbol"], "588200.SH")
        self.assertEqual(rank["exits"][0]["symbol"], "512880.SH")
        self.assertEqual(rank["smash_signals"][0]["symbol"], "159919.SZ")
        self.assertEqual(rank["trend_reduced_entries"][0]["status"], "上涨趋缓")

        positions = pd.DataFrame(
            [
                {"symbol": "159919.SZ", "amount": 1000, "available_amount": 1000},
                {"symbol": "512880.SH", "amount": 500, "available_amount": 500},
            ]
        )
        intents = order_intents_from_rank_signal(
            rank,
            positions,
            prices={"159919.SZ": 10.0},
            buy_amount=1_000_000,
            top_n=3,
            trend_position_pct={"上涨趋缓": 20, "下跌趋势": 30, "由涨转跌": 30},
            smash_sell_pct=10,
        )
        by_symbol_side = {(item.symbol, item.side): item.amount for item in intents}
        self.assertEqual(by_symbol_side[("159919.SZ", "sell")], 900)
        self.assertEqual(by_symbol_side[("512880.SH", "sell")], 500)
        self.assertEqual(by_symbol_side[("515880.SH", "buy")], 1_000_000)
        self.assertEqual(by_symbol_side[("588200.SH", "buy")], 200_000)

    def test_external_signal_provider_refreshes_ftp_directories_with_fake_ftp(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _config(root)
            config["etf_strategy"]["external_signal_dir"] = str(root / "external")
            config["etf_strategy"]["ftp"] = {
                "enabled": True,
                "auto_download": True,
                "password": "test-password",
            }

            class FakeFtp:
                files = {
                    "/每日选股结果分享/ETF红绿灯信号": {
                        "指数通行红绿灯.csv": "ETF红绿灯,2026-01-03,2026-01-02,2026-01-01\n通信ETF[515880] 抄,0.60|抄,0.26,0.27\n".encode("gbk")
                    },
                    "/每日选股结果分享/红绿灯排名与情绪": {
                        "指数通行红绿灯带排名和情绪.csv": "ETF,排名变化\n通信ETF[515880] 上涨趋势,→\n科创芯片ETF[588200] 上涨趋缓,↑5\n".encode("gbk")
                    },
                }

                def __init__(self):
                    self.current = ""
                    self.encoding = ""

                def connect(self, *_args, **_kwargs):
                    return None

                def login(self, *_args, **_kwargs):
                    return None

                def cwd(self, path):
                    if path == "..":
                        self.current = ""
                        return None
                    if path in self.files:
                        self.current = path
                        return None
                    raise OSError(path)

                def pwd(self):
                    return self.current

                def nlst(self):
                    return list(self.files[self.current])

                def retrbinary(self, command, writer):
                    name = command.split(" ", 1)[1]
                    writer(self.files[self.current][name])

                def quit(self):
                    return None

            provider = ExternalSignalProvider(config, ftp_factory=FakeFtp)
            provider.refresh()

            self.assertEqual(red_green_decision(provider.load_red_green_signal(), "515880.SH")["action"], "buy")
            rank = parse_rank_emotion_frame(provider.load_rank_emotion_signal(), top_n=2)
            self.assertEqual(rank["ranking_rows"][1]["symbol"], "588200.SH")

    def test_ftp_password_can_be_supplied_by_environment(self):
        with patch.dict("os.environ", {"QUANTYB_ETF_FTP_PASSWORD": "local-secret"}, clear=False):
            ftp = resolve_ftp_config({"password": ""})

        self.assertEqual(ftp["password"], "local-secret")


if __name__ == "__main__":
    unittest.main()
