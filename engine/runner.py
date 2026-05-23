"""回测引擎 —— 封装 backtrader，输出绩效与交易流水"""

import time
import threading
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any, Optional

import backtrader as bt
import click
import numpy as np
import pandas as pd

from strategy.base import AShareCommission


class EquityCurveAnalyzer(bt.Analyzer):
    """记录每个 bar 的账户权益值，用于绘制权益曲线"""

    def __init__(self):
        self.equity: list[float] = []
        self.dates: list[str] = []
        super().__init__()

    def next(self):
        self.equity.append(self.strategy.broker.getvalue())
        self.dates.append(self.data.datetime.date(0).strftime("%Y-%m-%d"))

    def get_analysis(self):
        return {"dates": self.dates, "equity": self.equity}


def compute_drawdowns(equity: list[float]) -> list[float]:
    """计算回撤序列（正值表示回撤幅度）"""
    arr = np.array(equity)
    peak = np.maximum.accumulate(arr)
    dd = (arr - peak) / peak
    return (dd * 100).tolist()


def load_strategy_class(strategy_name: str):
    """按约定加载策略类: sma_cross → strategy.sma_cross:SmaCrossStrategy"""
    import importlib

    module: ModuleType = importlib.import_module(f"strategy.{strategy_name}")
    class_name = "".join(w.capitalize() for w in strategy_name.split("_")) + "Strategy"
    cls = getattr(module, class_name, None)
    if cls is None:
        raise ValueError(f"未在 strategy/{strategy_name}.py 找到类 {class_name}")
    return cls


# ============================================================
#  模块级 worker 函数 —— 供 ProcessPoolExecutor 使用
# ============================================================

def _process_backtest_worker(task: dict) -> dict:
    """进程级回测 worker：独立创建 BacktestRunner，完成单只股票回测"""
    sym = task["sym"]
    df_json = task["df_json"]
    df = pd.read_json(df_json, orient="table")
    df["date"] = pd.to_datetime(df["date"])
    config = task["config"]
    strategy_name = task["strategy_name"]
    strategy_params = task.get("strategy_params", {})

    runner = BacktestRunner(config)
    strategy_cls = load_strategy_class(strategy_name)
    params = {**strategy_params, "symbol": sym}
    result = runner.run(df, strategy_cls, params, verbose=False)

    return {
        "sym": sym,
        "stats": result["stats"],
        "trade_records": result["trade_records"],
        "equity": result["equity"],
        "buy_signal_dates": result["buy_signal_dates"],
    }


def _process_scan_worker(task: dict) -> Optional[dict]:
    """进程级扫描 worker"""
    sym = task["sym"]
    df_json = task["df_json"]
    df = pd.read_json(df_json, orient="table")
    df["date"] = pd.to_datetime(df["date"])
    config = task["config"]
    strategy_name = task["strategy_name"]
    strategy_params = task.get("strategy_params", {})
    lookback_days = task.get("lookback_days", 5)

    runner = BacktestRunner(config)
    strategy_cls = load_strategy_class(strategy_name)
    params = {**strategy_params, "symbol": sym}
    result = runner.run(df, strategy_cls, params, verbose=False)

    all_dates = sorted(df["date"].unique())
    recent_boundary = (
        all_dates[-lookback_days] if len(all_dates) >= lookback_days else all_dates[0]
    )
    boundary_str = (
        recent_boundary.strftime("%Y-%m-%d")
        if hasattr(recent_boundary, "strftime")
        else str(recent_boundary)[:10]
    )
    recent = [d for d in result["buy_signal_dates"] if d >= boundary_str]

    if not recent:
        return None
    return {
        "symbol": sym,
        "recent_buy_dates": ", ".join(recent),
        "signal_count": len(recent),
        "last_price": float(df["close"].iloc[-1]),
        "total_return_pct": result["stats"]["total_return_pct"],
    }


# ============================================================
#  BacktestRunner
# ============================================================

class BacktestRunner:
    """回测运行器"""

    def __init__(self, config: dict):
        self.config = config
        self.cash = config["backtest"]["initial_cash"]
        self.commission = config["backtest"]["commission"]
        self.stamp_duty = config["backtest"]["stamp_duty"]
        self.min_comm = config["backtest"].get("min_commission", 5.0)
        self._max_workers = config.get("parallel", {}).get("backtest_workers", 12)

    def run(
        self,
        df: pd.DataFrame,
        strategy_cls,
        strategy_params: Optional[dict] = None,
        verbose: bool = True,
    ) -> dict[str, Any]:
        """
        执行回测。

        Returns:
            {
                "trade_records": list[dict],
                "equity": {"dates": [...], "equity": [...], "drawdowns": [...]},
                "stats": {...},
                "buy_signal_dates": [...],
            }
        """
        cerebro = bt.Cerebro()

        data_feed = bt.feeds.PandasData(
            dataname=df.set_index("date"),
            datetime=None,
            open="open",
            high="high",
            low="low",
            close="close",
            volume="volume",
            openinterest=-1,
        )
        cerebro.adddata(data_feed)

        cerebro.broker.setcash(self.cash)

        comm_info = AShareCommission(
            commission=self.commission,
            stamp_duty=self.stamp_duty,
            min_commission=self.min_comm,
        )
        cerebro.broker.addcommissioninfo(comm_info)
        cerebro.broker.set_slippage_perc(0.001)

        params = strategy_params or {}
        cerebro.addstrategy(strategy_cls, **params)

        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", riskfreerate=0.03)
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
        cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
        cerebro.addanalyzer(EquityCurveAnalyzer, _name="equity")

        if verbose:
            click.echo(f"  初始资金: {self.cash:,.0f}")

        results = cerebro.run()
        strat = results[0]

        final_value = cerebro.broker.getvalue()
        if verbose:
            click.echo(f"  最终资金: {final_value:,.2f}")

        equity_data = strat.analyzers.equity.get_analysis()
        equity_data["drawdowns"] = compute_drawdowns(equity_data["equity"])

        stats = self._build_stats(strat, final_value)

        return {
            "trade_records": strat.get_trade_records(),
            "equity": equity_data,
            "stats": stats,
            "buy_signal_dates": strat.buy_signal_dates,
        }

    # ------------------------------------------------------------
    #  批量回测 / 扫描（ProcessPoolExecutor）
    # ------------------------------------------------------------

    def run_batch(
        self,
        data_map: dict[str, pd.DataFrame],
        strategy_name: str,
        strategy_params: Optional[dict] = None,
    ) -> list[dict[str, Any]]:
        """进程并行批量回测"""
        sp = strategy_params or {}
        workers = max(1, self._max_workers)
        total = len(data_map)

        summaries: list[dict] = []
        all_buy_signals: list[dict] = []
        trades_dir = Path(self.config["output"]["trades_dir"])
        trades_dir.mkdir(parents=True, exist_ok=True)

        click.echo(f"  并行回测 (进程数: {workers}, 共 {total} 只)")

        # 构建 task 列表（DataFrame 序列化为 dict）
        tasks = []
        for sym, df in data_map.items():
            # 预先提取日期用于信号过滤
            all_dates = sorted(df["date"].unique())
            recent_boundary = all_dates[-5] if len(all_dates) >= 5 else all_dates[0]
            boundary_str = (
                recent_boundary.strftime("%Y-%m-%d")
                if hasattr(recent_boundary, "strftime")
                else str(recent_boundary)[:10]
            )
            tasks.append({
                "sym": sym,
                "df_json": self._df_to_json(df),
                "config": self.config,
                "strategy_name": strategy_name,
                "strategy_params": sp,
                "boundary_str": boundary_str,
            })

        boundary_map = {t["sym"]: t["boundary_str"] for t in tasks}
        t0 = time.monotonic()
        completed = 0

        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_process_backtest_worker, t): t["sym"] for t in tasks}
            for future in as_completed(futures):
                sym = futures[future]
                completed += 1
                try:
                    r = future.result()
                except Exception as e:
                    click.echo(f"  [{sym}] 回测失败: {e}", err=True)
                    continue

                # 主进程负责文件 I/O
                self._export_trade_log(r["trade_records"], trades_dir, sym, strategy_name)
                self._export_equity(r["equity"], trades_dir, sym, strategy_name)

                stats = r["stats"]
                stats["symbol"] = sym
                summaries.append(stats)

                # 近5日买点
                boundary = boundary_map.get(sym, "0000-01-01")
                recent = [d for d in r["buy_signal_dates"] if d >= boundary]
                if recent:
                    all_buy_signals.append({
                        "symbol": sym,
                        "recent_buy_dates": ", ".join(recent),
                        "signal_count": len(recent),
                    })

                if completed % 50 == 0 or completed == total:
                    elapsed = time.monotonic() - t0
                    rate = completed / elapsed if elapsed > 0 else 0
                    click.echo(f"  进度: {completed}/{total}  已耗时: {elapsed:.0f}s  速率: {rate:.1f}只/秒")

        elapsed = time.monotonic() - t0
        click.echo(f"  回测完成，总耗时: {elapsed:.0f} 秒 ({elapsed/60:.1f} 分钟)")

        summaries.sort(key=lambda x: x["symbol"])
        all_buy_signals.sort(key=lambda x: x["symbol"])
        self._export_summary(summaries, strategy_name)
        self._export_buy_signals(all_buy_signals, strategy_name)
        return summaries

    def scan_recent_buy_signals(
        self,
        data_map: dict[str, pd.DataFrame],
        strategy_name: str,
        strategy_params: Optional[dict] = None,
        lookback_days: int = 5,
    ) -> list[dict]:
        """进程并行扫描近N日买点"""
        sp = strategy_params or {}
        workers = max(1, self._max_workers)
        total = len(data_map)

        click.echo(f"  并行扫描 (进程数: {workers}, 共 {total} 只, 回看 {lookback_days} 日)")

        tasks = [
            {
                "sym": sym,
                "df_json": self._df_to_json(df),
                "config": self.config,
                "strategy_name": strategy_name,
                "strategy_params": sp,
                "lookback_days": lookback_days,
            }
            for sym, df in data_map.items()
        ]

        results: list[dict] = []
        t0 = time.monotonic()
        completed = 0

        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_process_scan_worker, t): t["sym"] for t in tasks}
            for future in as_completed(futures):
                completed += 1
                try:
                    r = future.result()
                    if r is not None:
                        results.append(r)
                except Exception as e:
                    click.echo(f"  [{futures[future]}] 扫描失败: {e}", err=True)
                if completed % 50 == 0 or completed == total:
                    click.echo(f"  进度: {completed}/{total}")

        elapsed = time.monotonic() - t0
        click.echo(f"  扫描完成，总耗时: {elapsed:.0f} 秒")

        results.sort(key=lambda x: x["symbol"])
        self._export_buy_signals(results, strategy_name)
        return results

    # ------------------------------------------------------------
    #  工具方法
    # ------------------------------------------------------------

    @staticmethod
    def _df_to_json(df: pd.DataFrame) -> str:
        """将 DataFrame 序列化为 JSON 字符串（保留日期类型）"""
        out = df.copy()
        out["date"] = out["date"].apply(lambda x: x.strftime("%Y-%m-%d") if hasattr(x, "strftime") else str(x)[:10])
        return out.to_json(orient="table", date_format="iso")

    def _build_stats(self, strat: bt.Strategy, final_value: float) -> dict[str, Any]:
        ta = strat.analyzers.trades.get_analysis()
        sharpe = strat.analyzers.sharpe.get_analysis()
        dd = strat.analyzers.drawdown.get_analysis()

        total_return = (final_value - self.cash) / self.cash * 100

        won = ta.get("won", {}).get("total", 0)
        lost = ta.get("lost", {}).get("total", 0)
        total_trades = won + lost
        win_rate = (won / total_trades * 100) if total_trades > 0 else 0.0

        return {
            "initial_cash": self.cash,
            "final_value": round(final_value, 2),
            "total_return_pct": round(total_return, 2),
            "total_trades": total_trades,
            "win_trades": won,
            "lose_trades": lost,
            "win_rate_pct": round(win_rate, 2),
            "sharpe_ratio": round(sharpe.get("sharperatio", 0) or 0, 4),
            "max_drawdown_pct": round(dd.get("max", {}).get("drawdown", 0), 2),
            "max_drawdown_days": dd.get("max", {}).get("len", 0),
        }

    def _export_trade_log(
        self, records: list[dict], trades_dir: Path, symbol: str, strategy_name: str,
    ) -> Path:
        if not records:
            return trades_dir / f"{symbol}_{strategy_name}.csv"
        df = pd.DataFrame(records)
        columns = ["date", "symbol", "direction", "price", "size", "commission", "pnl"]
        df = df[columns]
        path = trades_dir / f"{symbol}_{strategy_name}.csv"
        df.to_csv(path, index=False)
        return path

    def _export_equity(
        self, equity_data: dict, trades_dir: Path, symbol: str, strategy_name: str,
    ) -> Path:
        df = pd.DataFrame(equity_data)
        path = trades_dir / f"{symbol}_{strategy_name}_equity.csv"
        df.to_csv(path, index=False)
        return path

    def _export_summary(self, summaries: list[dict], strategy_name: str) -> Path:
        df = pd.DataFrame(summaries)
        path = Path(self.config["output"]["trades_dir"]) / f"_summary_{strategy_name}.csv"
        df.to_csv(path, index=False)
        click.echo(f"\n批量回测汇总已导出: {path}")
        return path

    def _export_buy_signals(self, signals: list[dict], strategy_name: str) -> Path:
        if not signals:
            click.echo("\n  近5日内无买点信号。")
            return Path(".")
        signals_dir = Path(self.config["output"].get("signals_dir", "output/signals"))
        signals_dir.mkdir(parents=True, exist_ok=True)
        today = date.today().strftime("%Y%m%d")
        path = signals_dir / f"buy_signals_{strategy_name}_{today}.csv"
        pd.DataFrame(signals).to_csv(path, index=False)
        click.echo(f"\n  近5日买点汇总已导出: {path}  (共 {len(signals)} 只)")
        return path
