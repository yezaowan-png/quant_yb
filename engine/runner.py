"""回测引擎 —— 封装 backtrader，输出绩效与交易流水"""

import os
import sys
import time
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
        self.cash: list[float] = []
        self.position_size: list[int] = []
        self.position_price: list[float] = []
        self.position_value: list[float] = []
        self.exposure_pct: list[float] = []
        super().__init__()

    def next(self):
        equity = self.strategy.broker.getvalue()
        cash = self.strategy.broker.getcash()
        pos = self.strategy.getposition(self.data)
        close = float(self.data.close[0])
        position_value = float(pos.size) * close

        self.dates.append(self.data.datetime.date(0).strftime("%Y-%m-%d"))
        self.equity.append(equity)
        self.cash.append(cash)
        self.position_size.append(int(pos.size))
        self.position_price.append(float(pos.price or 0))
        self.position_value.append(position_value)
        self.exposure_pct.append(position_value / equity * 100 if equity else 0.0)

    def get_analysis(self):
        return {
            "dates": self.dates,
            "equity": self.equity,
            "cash": self.cash,
            "position_size": self.position_size,
            "position_price": self.position_price,
            "position_value": self.position_value,
            "exposure_pct": self.exposure_pct,
        }


def compute_drawdowns(equity: list[float]) -> list[float]:
    """计算回撤序列（正值表示回撤幅度）"""
    arr = np.array(equity)
    if len(arr) == 0:
        return []
    peak = np.maximum.accumulate(arr)
    dd = (arr - peak) / peak
    return (dd * 100).tolist()


def _longest_streak(values: list[float], positive: bool) -> int:
    longest = 0
    current = 0
    for value in values:
        matched = value > 0 if positive else value < 0
        if matched:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


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

def _make_executor(workers: int) -> ProcessPoolExecutor:
    """创建进程池，兼容不同 Python 版本（max_tasks_per_child 需 3.11+）"""
    try:
        return ProcessPoolExecutor(max_workers=workers, max_tasks_per_child=100)
    except TypeError:
        return ProcessPoolExecutor(max_workers=workers)


def _process_backtest_worker(task: dict) -> Optional[dict]:
    """进程级回测 worker：回测 + 文件导出"""
    # 子进程抑制所有输出，防止 VS Code 终端白屏
    sys.stdout = open(os.devnull, "w")
    sys.stderr = open(os.devnull, "w")
    # 限制 BLAS 线程数，防止 OpenBLAS 在多进程中耗尽内存
    for key in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS",
                "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[key] = "1"

    try:
        sym = task["sym"]
        df = task["df"]
        config = task["config"]
        strategy_name = task["strategy_name"]
        strategy_params = task.get("strategy_params", {})
        trades_dir = task["trades_dir"]

        runner = BacktestRunner(config)
        strategy_cls = load_strategy_class(strategy_name)
        params = {**strategy_params, "symbol": sym}
        result = runner.run(df, strategy_cls, params, verbose=False)

        runner._export_trade_log(result["trade_records"], trades_dir, sym, strategy_name)
        runner._export_equity(result["equity"], trades_dir, sym, strategy_name)

        return {
            "sym": sym,
            "stats": result["stats"],
            "buy_signal_dates": result["buy_signal_dates"],
        }
    except Exception as e:
        return {"sym": sym, "error": str(e)}


def _process_scan_worker(task: dict) -> Optional[dict]:
    """进程级扫描 worker"""
    sys.stdout = open(os.devnull, "w")
    sys.stderr = open(os.devnull, "w")
    for key in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS",
                "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[key] = "1"

    try:
        sym = task["sym"]
        df = task["df"]
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
    except Exception:
        return None


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
        self.slippage_perc = config["backtest"].get("slippage_perc", 0.001)
        self.enforce_price_limits = config["backtest"].get("enforce_price_limits", True)
        self.limit_pct = config["backtest"].get("limit_pct", 0.10)
        self.volume_limit_ratio = config["backtest"].get("volume_limit_ratio", 0.0)
        self.volume_unit = config["backtest"].get("volume_unit", 100)
        self._max_workers = config.get("parallel", {}).get("backtest_workers", 12)
        self._benchmark_df: Optional[pd.DataFrame] = None

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
        cerebro.broker.set_slippage_perc(self.slippage_perc)

        params = strategy_params or {}
        params = {
            **params,
            "enforce_price_limits": self.enforce_price_limits,
            "limit_pct": self.limit_pct,
            "volume_limit_ratio": self.volume_limit_ratio,
            "volume_unit": self.volume_unit,
        }
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

        stats = self._build_stats(strat, final_value, equity_data, df)

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
        failed = 0
        trades_dir = Path(self.config["output"]["trades_dir"])
        trades_dir.mkdir(parents=True, exist_ok=True)

        click.echo(f"  并行回测 (进程数: {workers}, 共 {total} 只)")

        # 构建 task 列表
        tasks = []
        for sym, df in data_map.items():
            all_dates = sorted(df["date"].unique())
            recent_boundary = all_dates[-5] if len(all_dates) >= 5 else all_dates[0]
            boundary_str = (
                recent_boundary.strftime("%Y-%m-%d")
                if hasattr(recent_boundary, "strftime")
                else str(recent_boundary)[:10]
            )
            tasks.append({
                "sym": sym,
                "df": df,
                "config": self.config,
                "strategy_name": strategy_name,
                "strategy_params": sp,
                "trades_dir": trades_dir,
                "boundary_str": boundary_str,
            })

        boundary_map = {t["sym"]: t["boundary_str"] for t in tasks}
        t0 = time.monotonic()
        completed = 0

        with _make_executor(workers) as executor:
            futures = {executor.submit(_process_backtest_worker, t): t["sym"] for t in tasks}
            for future in as_completed(futures):
                sym = futures[future]
                completed += 1
                try:
                    r = future.result()
                except Exception as e:
                    failed += 1
                    click.echo(f"  [{sym}] 进程异常: {e}", err=True)
                    continue

                if r is None or "error" in r:
                    failed += 1
                    continue

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

                if completed % 100 == 0 or completed == total:
                    elapsed = time.monotonic() - t0
                    rate = completed / elapsed if elapsed > 0 else 0
                    click.echo(f"  进度: {completed}/{total}  已耗时: {elapsed:.0f}s  速率: {rate:.1f}只/秒")

        elapsed = time.monotonic() - t0
        click.echo(f"  回测完成，总耗时: {elapsed:.0f} 秒 ({elapsed/60:.1f} 分钟)")
        if failed:
            click.echo(f"  失败: {failed} 只 (数据异常或指标计算失败，已自动跳过)")

        summaries.sort(key=lambda x: x["symbol"])
        all_buy_signals.sort(key=lambda x: x["symbol"])
        self._export_summary(summaries, strategy_name)
        self._export_buy_signals(all_buy_signals, strategy_name, sp)
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
                "df": df,
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

        with _make_executor(workers) as executor:
            futures = {executor.submit(_process_scan_worker, t): t["sym"] for t in tasks}
            for future in as_completed(futures):
                completed += 1
                try:
                    r = future.result()
                    if r is not None:
                        results.append(r)
                except Exception:
                    pass
                if completed % 100 == 0 or completed == total:
                    click.echo(f"  进度: {completed}/{total}")

        elapsed = time.monotonic() - t0
        click.echo(f"  扫描完成，总耗时: {elapsed:.0f} 秒")

        results.sort(key=lambda x: x["symbol"])
        self._export_buy_signals(results, strategy_name, sp)
        return results

    # ------------------------------------------------------------
    #  工具方法
    # ------------------------------------------------------------

    def _load_benchmark_df(self) -> Optional[pd.DataFrame]:
        benchmark_cfg = self.config.get("benchmark", {})
        if not benchmark_cfg.get("enabled", True):
            return None
        if self._benchmark_df is not None:
            return self._benchmark_df

        symbol = benchmark_cfg.get("symbol")
        if not symbol:
            return None
        path = Path(self.config["data"]["cache_dir"]) / f"{symbol}.csv"
        if not path.exists():
            return None
        df = pd.read_csv(path, dtype={"date": str})
        df["date"] = pd.to_datetime(df["date"])
        self._benchmark_df = df.sort_values("date").reset_index(drop=True)
        return self._benchmark_df

    def _benchmark_metrics(self, equity_data: dict, data_df: pd.DataFrame) -> dict[str, Any]:
        benchmark_df = self._load_benchmark_df()
        if benchmark_df is None or not equity_data.get("dates"):
            return {}

        start_date = pd.Timestamp(data_df["date"].min())
        end_date = pd.Timestamp(data_df["date"].max())
        sub = benchmark_df[
            (benchmark_df["date"] >= start_date) & (benchmark_df["date"] <= end_date)
        ].copy()
        if len(sub) < 2:
            return {}

        benchmark_return = (sub["close"].iloc[-1] / sub["close"].iloc[0] - 1) * 100
        strategy_return = (equity_data["equity"][-1] / equity_data["equity"][0] - 1) * 100

        eq = pd.DataFrame({
            "date": pd.to_datetime(equity_data["dates"]),
            "equity": equity_data["equity"],
        }).set_index("date")
        bm = sub.set_index("date")["close"]
        joined = pd.concat([
            eq["equity"].pct_change().rename("strategy"),
            bm.pct_change().rename("benchmark"),
        ], axis=1).dropna()

        info_ratio = 0.0
        if len(joined) > 2:
            active = joined["strategy"] - joined["benchmark"]
            active_std = active.std()
            if active_std and not pd.isna(active_std):
                info_ratio = float(active.mean() / active_std * np.sqrt(252))

        symbol = self.config.get("benchmark", {}).get("symbol", "")
        return {
            "benchmark_symbol": symbol,
            "benchmark_return_pct": round(float(benchmark_return), 2),
            "excess_return_pct": round(float(strategy_return - benchmark_return), 2),
            "information_ratio": round(info_ratio, 4),
        }

    def _build_stats(
        self,
        strat: bt.Strategy,
        final_value: float,
        equity_data: dict,
        data_df: pd.DataFrame,
    ) -> dict[str, Any]:
        ta = strat.analyzers.trades.get_analysis()
        sharpe = strat.analyzers.sharpe.get_analysis()
        dd = strat.analyzers.drawdown.get_analysis()

        total_return = (final_value - self.cash) / self.cash * 100
        trading_days = len(equity_data.get("equity", []))
        annual_return = 0.0
        annual_volatility = 0.0
        calmar = 0.0
        sortino = 0.0
        if trading_days > 0 and final_value > 0:
            annual_return = ((final_value / self.cash) ** (252 / trading_days) - 1) * 100
        eq_series = pd.Series(equity_data.get("equity", []), dtype="float64")
        if len(eq_series) > 2:
            daily_returns = eq_series.pct_change().dropna()
            annual_volatility = float(daily_returns.std() * np.sqrt(252) * 100)
            downside = daily_returns[daily_returns < 0]
            downside_std = float(downside.std()) if len(downside) > 1 else 0.0
            if downside_std > 0:
                sortino = float(daily_returns.mean() / downside_std * np.sqrt(252))

        won = ta.get("won", {}).get("total", 0)
        lost = ta.get("lost", {}).get("total", 0)
        total_trades = won + lost
        win_rate = (won / total_trades * 100) if total_trades > 0 else 0.0
        max_drawdown = dd.get("max", {}).get("drawdown", 0)
        if max_drawdown:
            calmar = annual_return / max_drawdown

        sell_pnls = [
            float(rec.get("pnl", 0) or 0)
            for rec in strat.get_trade_records()
            if rec.get("direction") == "SELL"
        ]
        gross_profit = sum(pnl for pnl in sell_pnls if pnl > 0)
        gross_loss = sum(pnl for pnl in sell_pnls if pnl < 0)
        if gross_loss < 0:
            profit_factor = gross_profit / abs(gross_loss)
        elif gross_profit > 0:
            profit_factor = float("inf")
        else:
            profit_factor = 0.0
        finite_profit_factor = round(profit_factor, 4) if np.isfinite(profit_factor) else None
        avg_trade_pnl = float(np.mean(sell_pnls)) if sell_pnls else 0.0
        best_trade_pnl = max(sell_pnls) if sell_pnls else 0.0
        worst_trade_pnl = min(sell_pnls) if sell_pnls else 0.0
        exposure_vals = pd.Series(equity_data.get("exposure_pct", []), dtype="float64").dropna()
        avg_exposure = float(exposure_vals.mean()) if len(exposure_vals) else 0.0

        stats = {
            "initial_cash": self.cash,
            "final_value": round(final_value, 2),
            "total_return_pct": round(total_return, 2),
            "annual_return_pct": round(annual_return, 2),
            "annual_volatility_pct": round(annual_volatility, 2),
            "calmar_ratio": round(calmar, 4),
            "sortino_ratio": round(sortino, 4),
            "profit_factor": finite_profit_factor,
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "avg_trade_pnl": round(avg_trade_pnl, 2),
            "best_trade_pnl": round(best_trade_pnl, 2),
            "worst_trade_pnl": round(worst_trade_pnl, 2),
            "longest_win_streak": _longest_streak(sell_pnls, positive=True),
            "longest_loss_streak": _longest_streak(sell_pnls, positive=False),
            "avg_exposure_pct": round(avg_exposure, 2),
            "total_trades": total_trades,
            "win_trades": won,
            "lose_trades": lost,
            "win_rate_pct": round(win_rate, 2),
            "sharpe_ratio": round(sharpe.get("sharperatio", 0) or 0, 4),
            "max_drawdown_pct": round(max_drawdown, 2),
            "max_drawdown_days": dd.get("max", {}).get("len", 0),
            "start_date": data_df["date"].min().strftime("%Y-%m-%d"),
            "end_date": data_df["date"].max().strftime("%Y-%m-%d"),
            "trading_days": trading_days,
        }
        stats.update(self._benchmark_metrics(equity_data, data_df))
        return stats

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

    def _export_buy_signals(
        self,
        signals: list[dict],
        strategy_name: str,
        strategy_params: Optional[dict] = None,
    ) -> Path:
        if not signals:
            click.echo("\n  近5日内无买点信号。")
            return Path(".")
        signals_dir = Path(self.config["output"].get("signals_dir", "output/signals"))
        signals_dir.mkdir(parents=True, exist_ok=True)
        today = date.today().strftime("%Y%m%d")
        path = signals_dir / f"buy_signals_{strategy_name}_{today}.csv"
        pd.DataFrame(signals).to_csv(path, index=False)
        click.echo(f"\n  近5日买点汇总已导出: {path}  (共 {len(signals)} 只)")
        self._record_decision_signals(signals, strategy_name, strategy_params, path)
        return path

    def _record_decision_signals(
        self,
        signals: list[dict],
        strategy_name: str,
        strategy_params: Optional[dict],
        source_path: Path,
    ) -> None:
        if not self.config.get("decision_memory", {}).get("enabled", True):
            return
        try:
            from decision.recorder import append_buy_signals

            memory_path, added = append_buy_signals(
                config=self.config,
                strategy=strategy_name,
                signals=signals,
                strategy_params=strategy_params,
                source=str(source_path),
            )
            click.echo(f"  决策记忆已更新: {memory_path}  (新增 {added} 条)")
        except Exception as e:
            click.echo(f"  决策记忆更新失败: {e}", err=True)
