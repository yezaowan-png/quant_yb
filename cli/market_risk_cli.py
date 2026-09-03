"""Independent CLI for market_risk_gate; it never mutates formal environment signals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import click
import pandas as pd

from analysis.market_risk_data import (
    load_risk_stock_close_matrix,
    load_risk_strategy_daily_returns,
    load_risk_strategy_trade_events,
)
from analysis.market_risk_diagnostics import (
    evaluate_strategy_risk_gate,
    experiment_gate,
    risk_stability_tables,
    run_experiment_matrix,
    save_experiment_matrix,
    summarize_risk_experiment,
)
from analysis.market_risk_features import build_market_risk_features
from analysis.market_risk_labels import (
    RISK_LABELS,
    build_market_risk_outcomes,
    expanding_risk_labels,
)
from analysis.market_risk_model import RiskExperiment, run_risk_experiment
from analysis.market_risk_policy import apply_policy_hysteresis, policy_payload
from analysis.market_risk_state import build_market_risk_states
from analysis.market_risk_validity import run_risk_gate_validity, save_risk_gate_validity
from cli.common import load_config
from data.downloader import default_start, today_str
from visual.market_risk_report import generate_market_risk_report
from visual.market_risk_validity_report import generate_market_risk_validity_report


DEFAULT_SYMBOL = "000001.SH"
LABEL_ALIASES = {
    "pure_tail_risk": "R1",
    "persistent_tail_risk": "R2",
    "broad_weakness": "R3",
    "path_max_drawdown": "R4",
    "large_decline_spread": "R5",
}


def _resolve_label(value: str) -> str:
    resolved = LABEL_ALIASES.get(str(value), str(value).upper())
    if resolved not in RISK_LABELS:
        choices = ", ".join([*RISK_LABELS, *LABEL_ALIASES])
        raise click.BadParameter(f"可选值: {choices}")
    return resolved


def _paths(config: dict, symbol: str) -> dict[str, Path]:
    stats = Path(config["output"].get("statistics_dir", "output/statistics")) / "market_risk_gate" / symbol.upper()
    reports = Path(config["output"].get("reports_dir", "output/reports")) / "market_risk_gate"
    return {
        "root": stats, "features": stats / "features.csv", "outcomes": stats / "outcomes.csv",
        "dataset": stats / "dataset.csv", "states": stats / "states.csv", "policies": stats / "policies.csv",
        "latest": stats / "latest_state.json", "experiments": stats / "experiments",
        "reports": reports, "report": reports / f"{symbol.upper()}_risk_gate.html",
        "validity": stats / "validity",
    }


def _load_index_cache(config: dict, symbol: str) -> pd.DataFrame:
    path = Path(config["data"]["cache_dir"]) / "index" / f"{symbol.upper()}.csv"
    if not path.exists():
        raise click.ClickException(f"指数缓存不存在: {path}，请先执行 index download")
    frame = pd.read_csv(path, dtype={"date": str})
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    return frame.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)


def _date_filter(frame: pd.DataFrame, start: str | None, end: str | None) -> pd.DataFrame:
    if "trade_date" not in frame.columns:
        return frame
    dates = pd.to_datetime(frame["trade_date"], errors="coerce")
    mask = pd.Series(True, index=frame.index)
    if start:
        mask &= dates >= pd.to_datetime(start)
    if end:
        mask &= dates <= pd.to_datetime(end)
    return frame[mask].reset_index(drop=True)


def _build_dataset(config: dict, symbol: str, force: bool = False) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Path]]:
    paths = _paths(config, symbol)
    if not force and all(paths[name].exists() for name in ("dataset", "states", "policies")):
        return (
            pd.read_csv(paths["dataset"], dtype={"trade_date": str}),
            pd.read_csv(paths["policies"], dtype={"trade_date": str}),
            paths,
        )
    index = _load_index_cache(config, symbol)
    close_matrix = load_risk_stock_close_matrix(config["data"]["cache_dir"], dates=index["date"])
    features = build_market_risk_features(index, close_matrix)
    outcomes = build_market_risk_outcomes(index, close_matrix)
    dataset = features.merge(outcomes, on="trade_date", how="left", validate="one_to_one")
    states = build_market_risk_states(features)
    policies = apply_policy_hysteresis(states)
    paths["root"].mkdir(parents=True, exist_ok=True)
    features.to_csv(paths["features"], index=False)
    outcomes.to_csv(paths["outcomes"], index=False)
    dataset.to_csv(paths["dataset"], index=False)
    states.to_csv(paths["states"], index=False)
    policies.to_csv(paths["policies"], index=False)
    payload = policy_payload(policies.iloc[-1])
    paths["latest"].write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return dataset, policies, paths


@click.group("market")
def market_group():
    """独立市场极端风险闸门研究。"""


@market_group.command("risk-state")
@click.option("--symbol", default=DEFAULT_SYMBOL, show_default=True)
@click.option("--date", default=None, help="查看日期 YYYYMMDD，默认最新")
@click.option("--force", is_flag=True, help="强制重建特征、结果和状态缓存")
def risk_state(symbol: str, date: Optional[str], force: bool):
    config = load_config()
    _, policies, paths = _build_dataset(config, symbol.upper(), force=force)
    if date:
        selected = policies[pd.to_datetime(policies["trade_date"]) <= pd.to_datetime(date)]
        if selected.empty:
            raise click.ClickException(f"没有不晚于 {date} 的风险状态")
        row = selected.iloc[-1]
    else:
        row = policies.iloc[-1]
    payload = policy_payload(row)
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    click.echo(f"状态缓存: {paths['policies']}")


@market_group.command("risk-labels")
@click.option("--symbol", default=DEFAULT_SYMBOL, show_default=True)
@click.option("--horizon", type=click.Choice(["1", "5", "10", "20"]), default="5")
@click.option("--label", "label_name", default="R2", help="R1-R5，或 persistent_tail_risk 等语义别名")
@click.option("--start", default=None)
@click.option("--end", default=None)
@click.option("--force", is_flag=True)
def risk_labels(symbol: str, horizon: str, label_name: str, start: Optional[str], end: Optional[str], force: bool):
    config = load_config()
    label_name = _resolve_label(label_name)
    dataset, _, paths = _build_dataset(config, symbol.upper(), force=force)
    labels = expanding_risk_labels(dataset, int(horizon))
    output = _date_filter(dataset.merge(labels, on="trade_date"), start or default_start(), end or today_str())
    path = paths["root"] / f"labels_h{horizon}_{label_name}.csv"
    output.to_csv(path, index=False)
    click.echo(f"风险标签已生成: {path}")
    click.echo(f"样本: {output[label_name].notna().sum()}，风险率: {pd.to_numeric(output[label_name], errors='coerce').mean():.2%}")


@market_group.command("risk-diagnose")
@click.option("--symbol", default=DEFAULT_SYMBOL, show_default=True)
@click.option("--horizon", type=click.Choice(["1", "5", "10", "20"]), default="5")
@click.option("--label", "label_name", default="R2", help="R1-R5，或 persistent_tail_risk 等语义别名")
@click.option("--feature-set", type=click.Choice(["minimal_v1", "minimal_no_interaction"]), default="minimal_v1")
@click.option("--class-weight", type=click.Choice(["none", "balanced"]), default="none")
@click.option("--calibration", type=click.Choice(["none", "platt_nested"]), default="none")
@click.option("--experiment", default="custom")
@click.option("--force", is_flag=True)
def risk_diagnose(
    symbol: str, horizon: str, label_name: str, feature_set: str,
    class_weight: str, calibration: str, experiment: str, force: bool,
):
    config = load_config()
    label_name = _resolve_label(label_name)
    dataset, policies, paths = _build_dataset(config, symbol.upper(), force=force)
    spec = RiskExperiment(experiment, int(horizon), label_name, feature_set, class_weight, calibration)
    result = run_risk_experiment(dataset, spec)
    summary = summarize_risk_experiment(result)
    gate = experiment_gate(summary)
    features = pd.read_csv(paths["features"], dtype={"trade_date": str})
    yearly, volatility, universe = risk_stability_tables(result, features)
    strategy_returns = load_risk_strategy_daily_returns(config["output"].get("trades_dir", "output/trades"))
    strategies = evaluate_strategy_risk_gate(result, strategy_returns)
    directory = paths["experiments"] / experiment
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("folds", "predictions", "baselines", "coefficients"):
        result[name].to_csv(directory / f"{name}.csv", index=False)
    summary.to_csv(directory / "summary.csv", index=False)
    gate.to_csv(directory / "gate.csv", index=False)
    for name, frame in (
        ("yearly", yearly), ("volatility", volatility),
        ("universe", universe), ("strategies", strategies),
    ):
        frame.to_csv(directory / f"{name}.csv", index=False)
    decision = str(gate.iloc[-1]["decision"])
    report = generate_market_risk_report(
        paths["reports"] / f"{symbol.upper()}_{experiment}_risk_gate.html",
        symbol, policy_payload(policies.iloc[-1]), summary, gate, decision, experiment,
        details={
            "folds": result["folds"], "baselines": result["baselines"],
            "coefficients": result["coefficients"], "yearly": yearly,
            "volatility": volatility, "universe": universe, "strategies": strategies,
        },
    )
    click.echo(f"实验输出: {directory}")
    click.echo(f"风险报告: {report}")
    click.echo(f"自动结论: {decision}")


@market_group.command("risk-matrix")
@click.option("--symbol", default=DEFAULT_SYMBOL, show_default=True)
@click.option("--force", is_flag=True)
def risk_matrix(symbol: str, force: bool):
    config = load_config()
    dataset, policies, paths = _build_dataset(config, symbol.upper(), force=force)
    features = pd.read_csv(paths["features"], dtype={"trade_date": str})
    strategy_returns = load_risk_strategy_daily_returns(config["output"].get("trades_dir", "output/trades"))
    matrix = run_experiment_matrix(dataset, features, strategy_returns=strategy_returns)
    root = save_experiment_matrix(matrix, paths["experiments"])
    state_payload = policy_payload(policies.iloc[-1])
    for experiment, result in matrix["results"].items():
        decision = str(result["gate"].iloc[-1].get("decision"))
        generate_market_risk_report(
            paths["reports"] / f"{symbol.upper()}_{experiment}_risk_gate.html",
            symbol, state_payload, result["summary"], result["gate"], decision, experiment,
            details={name: result[name] for name in (
                "folds", "baselines", "coefficients", "yearly", "volatility", "universe", "strategies"
            )},
        )
    report = generate_market_risk_report(
        paths["report"], symbol, state_payload, matrix["summary"], matrix["gates"], matrix["automatic_decision"],
    )
    click.echo(f"实验矩阵: {root}")
    click.echo(f"风险报告: {report}")
    click.echo(f"自动结论: {matrix['automatic_decision']}")


@market_group.command("risk-report")
@click.option("--symbol", default=DEFAULT_SYMBOL, show_default=True)
@click.option("--horizon", type=click.Choice(["1", "5", "10", "20"]), default="5")
@click.option("--experiment", default="E2")
def risk_report(symbol: str, horizon: str, experiment: str):
    config = load_config()
    _, policies, paths = _build_dataset(config, symbol.upper(), force=False)
    directory = paths["experiments"] / experiment
    if not (directory / "summary.csv").exists():
        raise click.ClickException(f"实验不存在: {directory}，请先执行 market risk-diagnose 或 risk-matrix")
    summary = pd.read_csv(directory / "summary.csv")
    if "horizon" in summary and int(summary.iloc[0]["horizon"]) != int(horizon):
        raise click.ClickException(
            f"实验 {experiment} 的周期是 {int(summary.iloc[0]['horizon'])} 日，与 --horizon {horizon} 不一致"
        )
    gate = pd.read_csv(directory / "gate.csv")
    decision = str(gate.iloc[-1].get("decision"))
    details = {}
    for name in ("folds", "baselines", "coefficients", "yearly", "volatility", "universe", "strategies"):
        path = directory / f"{name}.csv"
        if path.exists():
            details[name] = pd.read_csv(path)
    report = generate_market_risk_report(
        paths["reports"] / f"{symbol.upper()}_{experiment}_risk_gate.html",
        symbol, policy_payload(policies.iloc[-1]), summary, gate, decision, experiment, details=details,
    )
    click.echo(f"风险报告: {report}")


@market_group.command("risk-validity")
@click.option("--symbol", default=DEFAULT_SYMBOL, show_default=True)
@click.option("--horizon", type=click.Choice(["1", "5", "10", "20"]), default="5")
@click.option("--simulations", type=click.IntRange(min=1000), default=1000, show_default=True)
@click.option("--block-size", type=click.IntRange(min=5), default=5, show_default=True)
@click.option("--cooldown", type=click.IntRange(min=10), default=10, show_default=True)
@click.option("--seed", type=int, default=20260713, show_default=True)
@click.option("--force", is_flag=True, help="强制重建含等权未来收益的基础数据")
def risk_validity(
    symbol: str,
    horizon: str,
    simulations: int,
    block_size: int,
    cooldown: int,
    seed: int,
    force: bool,
):
    """运行状态、预测、决策效用与区块随机证伪检验。"""
    config = load_config()
    _, policies, paths = _build_dataset(config, symbol.upper(), force=force)
    features = pd.read_csv(paths["features"], dtype={"trade_date": str})
    outcomes = pd.read_csv(paths["outcomes"], dtype={"trade_date": str})
    required = f"future_equal_weight_return_{horizon}d"
    if required not in outcomes.columns:
        raise click.ClickException(f"基础结果缺少 {required}，请增加 --force 重建")
    index = _load_index_cache(config, symbol.upper())
    trades_dir = config["output"].get("trades_dir", "output/trades")
    strategy_returns = load_risk_strategy_daily_returns(trades_dir)
    strategy_trades = load_risk_strategy_trade_events(trades_dir)
    click.echo(
        f"运行风险闸门证伪检验: H={horizon}, simulations={simulations}, "
        f"block={block_size}, cooldown={cooldown}, strategies={len(strategy_returns)}"
    )
    result = run_risk_gate_validity(
        features, outcomes, policies, index,
        strategy_returns=strategy_returns, strategy_trades=strategy_trades,
        horizon=int(horizon), simulations=simulations, cooldown=cooldown,
        block_size=block_size, seed=seed,
    )
    directory = save_risk_gate_validity(result, paths["validity"] / f"h{horizon}")
    report = generate_market_risk_validity_report(
        paths["reports"] / f"{symbol.upper()}_risk_gate_validity_h{horizon}.html",
        symbol, result,
    )
    qualification = str(result["qualification"].iloc[0]["qualification"])
    click.echo(f"有效性与随机性检验: {directory}")
    click.echo(f"检验报告: {report}")
    click.echo(f"资格结论: {qualification}")
