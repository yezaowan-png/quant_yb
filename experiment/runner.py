"""Run reproducible backtest experiments from YAML configs."""

from __future__ import annotations

import copy
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from engine.runner import BacktestRunner, load_strategy_class
from strategy.base import normalize_strategy_params
from visual.report import generate_report


TRADE_COLUMNS = ["date", "symbol", "direction", "price", "size", "commission", "pnl"]
ALLOWED_COST_KEYS = {
    "initial_cash",
    "commission",
    "stamp_duty",
    "min_commission",
    "slippage_perc",
    "enforce_price_limits",
    "limit_pct",
    "volume_limit_ratio",
    "volume_unit",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return slug.strip("._-")


def _experiment_id(raw: Any, config_path: Path) -> str:
    value = str(raw or config_path.stem)
    exp_id = _slug(value)
    if not exp_id:
        raise ValueError("实验 id 不能为空，且只能包含字母、数字、点、下划线或短横线")
    return exp_id


def _load_experiment_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"实验配置不存在: {config_path}")
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("实验配置必须是 YAML mapping")
    return data


def _as_symbol_list(data: dict[str, Any]) -> list[str]:
    raw = data.get("symbols")
    if raw is None and data.get("symbol"):
        raw = [data["symbol"]]
    if isinstance(raw, str):
        symbols = [s.strip().upper() for s in raw.split(",") if s.strip()]
    elif isinstance(raw, list):
        symbols = [str(s).strip().upper() for s in raw if str(s).strip()]
    else:
        symbols = []
    if not symbols:
        raise ValueError("实验配置必须显式提供 symbols 或 symbol，避免误跑全市场")
    return sorted(dict.fromkeys(symbols))


def _load_cache_df(symbol: str, config: dict[str, Any]) -> pd.DataFrame:
    cache_dir = Path(config["data"]["cache_dir"])
    path = cache_dir / f"{symbol}.csv"
    if not path.exists():
        raise FileNotFoundError(f"缓存数据不存在: {path}")
    df = pd.read_csv(path, dtype={"date": str})
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def _filter_dates(df: pd.DataFrame, start: Any, end: Any) -> pd.DataFrame:
    out = df
    if start:
        out = out[out["date"] >= pd.to_datetime(str(start))]
    if end:
        out = out[out["date"] <= pd.to_datetime(str(end))]
    return out.reset_index(drop=True)


def _apply_overrides(project_config: dict[str, Any], exp_config: dict[str, Any], exp_dir: Path) -> dict[str, Any]:
    config = copy.deepcopy(project_config)

    cost = exp_config.get("cost") or {}
    if not isinstance(cost, dict):
        raise ValueError("cost 必须是 mapping")
    unknown_cost = sorted(set(cost) - ALLOWED_COST_KEYS)
    if unknown_cost:
        raise ValueError(f"未知 cost 字段: {', '.join(unknown_cost)}")
    config.setdefault("backtest", {}).update(cost)

    benchmark = exp_config.get("benchmark")
    if benchmark:
        config["benchmark"] = {"enabled": True, "symbol": str(benchmark).upper()}

    output = config.setdefault("output", {})
    output["trades_dir"] = str(exp_dir / "trades")
    output["reports_dir"] = str(exp_dir / "reports")
    output["signals_dir"] = str(exp_dir / "signals")
    output["statistics_dir"] = str(exp_dir / "statistics")
    output["decisions_dir"] = str(exp_dir / "decisions")

    # 实验回测不应污染全局 decision memory；信号复盘可由后续显式导入流程处理。
    config["decision_memory"] = {**config.get("decision_memory", {}), "enabled": False}
    config.setdefault("parallel", {})["backtest_workers"] = 1
    return config


def _write_manifest(exp_dir: Path, manifest: dict[str, Any]) -> Path:
    path = exp_dir / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _write_experiment_config(exp_dir: Path, exp_config: dict[str, Any]) -> Path:
    path = exp_dir / "config.yaml"
    path.write_text(yaml.safe_dump(exp_config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _summary_path(exp_dir: Path) -> Path:
    return exp_dir / "summary.csv"


def _experiments_root(project_config: dict[str, Any]) -> Path:
    output = project_config["output"]
    if output.get("experiments_dir"):
        return Path(output["experiments_dir"])
    if output.get("trades_dir"):
        return Path(output["trades_dir"]).parent / "experiments"
    if output.get("reports_dir"):
        return Path(output["reports_dir"]).parent / "experiments"
    return Path("output/experiments")


def run_experiment(project_config: dict[str, Any], experiment_config_path: str | Path) -> dict[str, Any]:
    """Run one YAML-defined experiment and archive outputs under output/experiments."""
    config_path = Path(experiment_config_path)
    exp_config = _load_experiment_config(config_path)
    exp_id = _experiment_id(exp_config.get("id"), config_path)
    strategy = str(exp_config.get("strategy") or "").strip()
    if not strategy:
        raise ValueError("实验配置必须提供 strategy")

    symbols = _as_symbol_list(exp_config)
    output_root = _experiments_root(project_config)
    exp_dir = output_root / exp_id
    exp_dir.mkdir(parents=True, exist_ok=True)
    for sub in ["trades", "reports", "signals", "statistics", "decisions"]:
        (exp_dir / sub).mkdir(parents=True, exist_ok=True)

    started = _now()
    manifest: dict[str, Any] = {
        "id": exp_id,
        "strategy": strategy,
        "symbols": symbols,
        "status": "running",
        "source_config": str(config_path),
        "output_dir": str(exp_dir),
        "started_at": started,
        "finished_at": None,
        "duration_seconds": None,
        "inputs": {
            "start": str(exp_config.get("start") or ""),
            "end": str(exp_config.get("end") or ""),
            "benchmark": str(exp_config.get("benchmark") or project_config.get("benchmark", {}).get("symbol", "")),
            "params": exp_config.get("params") or {},
            "cost": exp_config.get("cost") or {},
        },
        "outputs": {},
        "warnings": [],
        "errors": [],
    }
    _write_manifest(exp_dir, manifest)

    t0 = time.monotonic()
    try:
        runtime_config = _apply_overrides(project_config, exp_config, exp_dir)
        archived_config = _write_experiment_config(exp_dir, exp_config)

        strategy_cls = load_strategy_class(strategy)
        params, ignored = normalize_strategy_params(strategy_cls, exp_config.get("params") or {})
        if ignored:
            manifest["warnings"].append(f"已忽略当前策略不使用的参数: {', '.join(ignored)}")

        runner = BacktestRunner(runtime_config)
        summaries: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []

        for symbol in symbols:
            try:
                df = _load_cache_df(symbol, runtime_config)
                df = _filter_dates(df, exp_config.get("start"), exp_config.get("end"))
                if df.empty:
                    raise ValueError("日期过滤后无可用数据")

                run_params = {**params, "symbol": symbol}
                result = runner.run(df, strategy_cls, run_params, verbose=False)
                stats = dict(result["stats"])
                stats["symbol"] = symbol
                summaries.append(stats)

                trades_path = runner._export_trade_log(
                    result["trade_records"], exp_dir / "trades", symbol, strategy
                )
                equity_path = runner._export_equity(result["equity"], exp_dir / "trades", symbol, strategy)

                trades_df = pd.DataFrame(result["trade_records"], columns=TRADE_COLUMNS)
                equity_df = pd.DataFrame(result["equity"])
                report_path = exp_dir / "reports" / f"{symbol}_{strategy}.html"
                generate_report(df, trades_df, symbol, strategy, report_path, equity_df)

                manifest.setdefault("symbol_outputs", {})[symbol] = {
                    "trades": str(trades_path),
                    "equity": str(equity_path),
                    "report": str(report_path),
                    "buy_signal_count": len(result["buy_signal_dates"]),
                }
            except Exception as exc:
                failures.append({"symbol": symbol, "error": str(exc)})

        if summaries:
            summary = pd.DataFrame(summaries).sort_values("symbol")
            summary_file = _summary_path(exp_dir)
            summary.to_csv(summary_file, index=False)
            manifest["outputs"]["summary"] = str(summary_file)
        else:
            manifest["outputs"]["summary"] = ""

        manifest["outputs"].update(
            {
                "config": str(archived_config),
                "reports_dir": str(exp_dir / "reports"),
                "trades_dir": str(exp_dir / "trades"),
                "manifest": str(exp_dir / "manifest.json"),
            }
        )
        manifest["result_counts"] = {
            "requested": len(symbols),
            "succeeded": len(summaries),
            "failed": len(failures),
        }
        manifest["errors"] = failures
        manifest["status"] = "ready" if summaries and not failures else ("partial" if summaries else "failed")
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["errors"].append({"error": str(exc)})
    finally:
        manifest["finished_at"] = _now()
        manifest["duration_seconds"] = round(time.monotonic() - t0, 3)
        _write_manifest(exp_dir, manifest)

    if manifest["status"] == "failed":
        errors = manifest.get("errors") or []
        detail = errors[0].get("error") if errors and isinstance(errors[0], dict) else "未知错误"
        raise RuntimeError(f"实验运行失败: {detail}")

    return manifest
