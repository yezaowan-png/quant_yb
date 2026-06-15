"""数据加载与统计计算"""

import os
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yaml


# 策略列表与显示名
_STRATEGIES = [
    "sma_cross",
    "macd_cross",
    "kdj",
    "bollinger",
    "rsi",
    "single_ma",
    "volume_platform_breakout",
]
_STRATEGY_LABELS = {
    "sma_cross": "双均线交叉", "macd_cross": "MACD 金叉",
    "kdj": "KDJ", "bollinger": "布林带", "rsi": "RSI", "single_ma": "单均线",
    "volume_platform_breakout": "放量平台突破",
}


def _load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_summary(strategy_name: str) -> Optional[pd.DataFrame]:
    """加载某个策略的批量回测汇总 CSV。返回 None 表示没有数据。"""
    config = _load_config()
    path = Path(config["output"]["trades_dir"]) / f"_summary_{strategy_name}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    df["symbol"] = df["symbol"].astype(str)
    return df


def load_all_summaries() -> dict[str, pd.DataFrame]:
    """加载所有策略的汇总数据。返回 {strategy_name: DataFrame}，跳过无数据的策略。"""
    result: dict[str, pd.DataFrame] = {}
    for name in _STRATEGIES:
        df = load_summary(name)
        if df is not None and len(df) > 0:
            result[name] = df
    return result


def compute_stats(df: pd.DataFrame) -> dict:
    """从汇总 DataFrame 计算分布统计量。"""
    returns = df["total_return_pct"].values
    sharpe = df["sharpe_ratio"].values
    dd = df["max_drawdown_pct"].values
    win_rate = df["win_rate_pct"].values
    trades = df["total_trades"].values

    positive = (returns > 0).sum()
    total = len(returns)
    active_df = df[df["total_trades"] > 0] if "total_trades" in df.columns else df.iloc[0:0]
    active_total = len(active_df)

    def _avg_col(name: str, default: float = 0.0) -> float:
        if name not in df.columns or total == 0:
            return default
        vals = pd.to_numeric(df[name], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().values
        if len(vals) == 0:
            return default
        return round(float(np.mean(vals)), 4)

    def _median_col(name: str, default: float = 0.0) -> float:
        if name not in df.columns or total == 0:
            return default
        vals = pd.to_numeric(df[name], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().values
        if len(vals) == 0:
            return default
        return round(float(np.median(vals)), 4)

    def _max_col(name: str, default: float = 0.0) -> float:
        if name not in df.columns or total == 0:
            return default
        vals = pd.to_numeric(df[name], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().values
        if len(vals) == 0:
            return default
        return round(float(np.max(vals)), 4)

    def _min_col(name: str, default: float = 0.0) -> float:
        if name not in df.columns or total == 0:
            return default
        vals = pd.to_numeric(df[name], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().values
        if len(vals) == 0:
            return default
        return round(float(np.min(vals)), 4)

    downside_returns = returns[returns < 0]
    downside_std = float(np.std(downside_returns)) if len(downside_returns) > 1 else 0.0
    cross_section_sortino = (
        round(float(np.mean(returns) / downside_std), 4)
        if downside_std > 0 else 0.0
    )

    return {
        "count": total,
        "avg_return": round(float(np.mean(returns)), 2),
        "median_return": round(float(np.median(returns)), 2),
        "std_return": round(float(np.std(returns)), 2),
        "positive_ratio": round(positive / total * 100, 1) if total > 0 else 0.0,
        "positive_count": int(positive),
        "negative_count": int(total - positive),
        "active_count": int(active_total),
        "active_ratio": round(active_total / total * 100, 1) if total > 0 else 0.0,
        "avg_active_return": round(float(np.mean(active_df["total_return_pct"])), 2) if active_total > 0 else 0.0,
        "avg_active_annual_return": (
            round(float(np.mean(active_df["annual_return_pct"])), 2)
            if active_total > 0 and "annual_return_pct" in active_df.columns else 0.0
        ),
        "avg_sharpe": round(float(np.mean(sharpe)), 4),
        "median_sharpe": round(float(np.median(sharpe)), 4),
        "avg_max_dd": round(float(np.mean(dd)), 2),
        "median_max_dd": round(float(np.median(dd)), 2),
        "avg_win_rate": round(float(np.mean(win_rate)), 2) if total > 0 else 0.0,
        "median_win_rate": round(float(np.median(win_rate)), 2) if total > 0 else 0.0,
        "avg_trades": round(float(np.mean(trades)), 1),
        "median_trades": round(float(np.median(trades)), 1),
        "min_return": round(float(np.min(returns)), 2),
        "max_return": round(float(np.max(returns)), 2),
        "avg_annual_return": round(_avg_col("annual_return_pct"), 2),
        "median_annual_return": round(_median_col("annual_return_pct"), 2),
        "avg_annual_volatility": round(_avg_col("annual_volatility_pct"), 2),
        "avg_calmar": round(_avg_col("calmar_ratio"), 4),
        "avg_sortino": round(_avg_col("sortino_ratio"), 4),
        "median_sortino": round(_median_col("sortino_ratio"), 4),
        "cross_section_sortino": cross_section_sortino,
        "avg_profit_factor": round(_avg_col("profit_factor"), 4),
        "median_profit_factor": round(_median_col("profit_factor"), 4),
        "avg_max_drawdown_days": round(_avg_col("max_drawdown_days"), 1),
        "median_max_drawdown_days": round(_median_col("max_drawdown_days"), 1),
        "avg_trade_pnl": round(_avg_col("avg_trade_pnl"), 2),
        "best_trade_pnl": round(_max_col("best_trade_pnl"), 2),
        "worst_trade_pnl": round(_min_col("worst_trade_pnl"), 2),
        "max_win_streak": int(_max_col("longest_win_streak")),
        "max_loss_streak": int(_max_col("longest_loss_streak")),
        "avg_exposure": round(_avg_col("avg_exposure_pct"), 2),
        "avg_benchmark_return": round(_avg_col("benchmark_return_pct"), 2),
        "avg_excess_return": round(_avg_col("excess_return_pct"), 2),
        "avg_information_ratio": round(_avg_col("information_ratio"), 4),
    }


def build_return_histogram(df: pd.DataFrame, bins: int = 50) -> list[dict]:
    """将收益率分成 bins 个区间，返回 {bin_label, count, color} 列表。"""
    returns = df["total_return_pct"].values
    hist, edges = np.histogram(returns, bins=bins)
    result = []
    for i in range(len(hist)):
        left = round(float(edges[i]), 1)
        right = round(float(edges[i + 1]), 1)
        result.append({
            "label": f"{left}",
            "left": left,
            "right": right,
            "count": int(hist[i]),
            "color": "#ef5350" if left >= 0 and right >= 0 else "#26a69a",
        })
    return result


def compute_correlation_matrix(data_map: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """基于同股票跨策略收益率计算秩相关系数矩阵。"""
    # 找出所有在所有策略中都有的 symbol
    symbols_list = [set(df["symbol"].unique()) for df in data_map.values()]
    common = symbols_list[0]
    for s in symbols_list[1:]:
        common = common & s
    if len(common) < 3:
        return pd.DataFrame()

    rows = []
    for sym in common:
        row = {"symbol": sym}
        for name, df in data_map.items():
            sub = df[df["symbol"] == sym]
            if not sub.empty:
                row[name] = sub.iloc[0]["total_return_pct"]
        if len(row) == len(data_map) + 1:  # all strategies present
            rows.append(row)

    wide = pd.DataFrame(rows)
    if wide.empty or len(wide.columns) < 3:
        return pd.DataFrame()

    strat_cols = [c for c in wide.columns if c != "symbol"]
    return wide[strat_cols].corr(method="spearman")


def get_scatter_data(df: pd.DataFrame) -> list[dict]:
    """提取散点图所需数据：symbol, return, max_dd, sharpe, win_rate。"""
    records = df.to_dict("records")
    result = []
    for r in records:
        result.append({
            "symbol": str(r["symbol"]),
            "return_pct": round(float(r["total_return_pct"]), 2),
            "max_dd": round(float(r["max_drawdown_pct"]), 2),
            "sharpe": round(float(r["sharpe_ratio"]), 4),
            "win_rate": round(float(r["win_rate_pct"]), 2),
        })
    return result


def get_top_bottom(df: pd.DataFrame, n: int = 20) -> tuple[list[dict], list[dict]]:
    """返回 (top_n, bottom_n) 股票列表，按收益率排序。"""
    sorted_df = df.sort_values("total_return_pct", ascending=False)
    top_cols = ["symbol", "total_return_pct", "sharpe_ratio", "max_drawdown_pct",
                "win_rate_pct", "total_trades"]
    for col in ("sortino_ratio", "profit_factor", "calmar_ratio", "max_drawdown_days"):
        if col in sorted_df.columns:
            top_cols.append(col)
    top = sorted_df.head(n)[top_cols].to_dict("records")
    bottom = sorted_df.tail(n)[top_cols].to_dict("records")
    return top, bottom


def normalize_for_radar(stats_map: dict[str, dict]) -> dict[str, list[float]]:
    """将各策略的原始指标归一化到 0-100，用于雷达图。

    指标与归一化方向：
    - avg_return: 越高越好
    - avg_sharpe: 越高越好
    - avg_win_rate: 越高越好
    - positive_ratio: 越高越好
    - avg_max_dd: 越低越好 → 反转
    - avg_trades: 适中为宜（交易次数太少缺乏信号，太多则过度交易）

    Returns {strategy_name: [val1, val2, val3, val4, val5, val6]}
    """
    metrics = ["avg_return", "avg_sharpe", "avg_win_rate", "positive_ratio", "avg_max_dd", "avg_trades"]
    reverse_idx = {4}  # avg_max_dd 反转

    # 提取原始值
    raw: dict[str, list[float]] = {k: [] for k in metrics}
    for name, s in stats_map.items():
        for m in metrics:
            raw[m].append(s[m])

    # Min-Max 归一化
    normed: dict[str, list[float]] = {}
    for i, m in enumerate(metrics):
        vals = np.array(raw[m])
        vmin, vmax = vals.min(), vals.max()
        if vmax - vmin < 1e-10:
            normed[m] = [50.0] * len(vals)
        else:
            scaled = (vals - vmin) / (vmax - vmin) * 100
            if i in reverse_idx:
                scaled = 100 - scaled
            normed[m] = scaled.tolist()

    result: dict[str, list[float]] = {}
    names = list(stats_map.keys())
    for j, name in enumerate(names):
        result[name] = [round(normed[m][j], 1) for m in metrics]

    return result
