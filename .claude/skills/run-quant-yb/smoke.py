"""QuantYB smoke test — verifies the full pipeline on a single stock.

Usage:
    python .claude/skills/run-quant-yb/smoke.py           # quick smoke (sma_cross only)
    python .claude/skills/run-quant-yb/smoke.py --full    # all strategies + REPL
    python .claude/skills/run-quant-yb/smoke.py --symbol 600519.SH  # pick a stock
"""

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command from repo root, print stdout on failure."""
    result = subprocess.run(
        cmd, cwd=str(ROOT), capture_output=True, text=True, **kwargs,
    )
    if result.returncode != 0:
        print(f"  FAIL (exit {result.returncode})")
        if result.stdout:
            print(f"  stdout:\n{result.stdout[:800]}")
        if result.stderr:
            print(f"  stderr:\n{result.stderr[:800]}")
    return result


def run_repl(command: str) -> str:
    """Pipe a command to the REPL and return its stdout."""
    result = subprocess.run(
        [sys.executable, "main.py"],
        cwd=str(ROOT),
        input=command + "\nexit\n",
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.stdout


def check(label: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    extra = f" — {detail}" if detail else ""
    print(f"  [{status}] {label}{extra}")
    return ok


def step_imports() -> bool:
    """Verify all core modules are importable."""
    print("\n--- Imports ---")
    all_ok = True
    try:
        from strategy.base import BaseStrategy
        all_ok &= check("strategy.base", True)
    except Exception as e:
        all_ok &= check("strategy.base", False, str(e))

    try:
        from engine.runner import BacktestRunner, load_strategy_class
        all_ok &= check("engine.runner", True)
    except Exception as e:
        all_ok &= check("engine.runner", False, str(e))

    try:
        from data.downloader import DataDownloader
        all_ok &= check("data.downloader", True)
    except Exception as e:
        all_ok &= check("data.downloader", False, str(e))

    try:
        from visual.kline_chart import create_kline_chart, create_macd_chart, create_kdj_chart
        from visual.report import generate_report
        all_ok &= check("visual.*", True)
    except Exception as e:
        all_ok &= check("visual.*", False, str(e))

    # Verify all 6 strategies load
    strategies = ["sma_cross", "macd_cross", "kdj", "bollinger", "rsi", "single_ma"]
    for name in strategies:
        try:
            cls = load_strategy_class(name)
            all_ok &= check(f"load {name}", cls.__name__.endswith("Strategy"), cls.__name__)
        except Exception as e:
            all_ok &= check(f"load {name}", False, str(e))

    return all_ok


def step_download(symbol: str) -> bool:
    """Ensure data is cached for the target symbol."""
    print(f"\n--- Download ({symbol}) ---")
    cache_path = ROOT / "data" / "cache" / f"{symbol}.csv"
    if cache_path.exists():
        print(f"  [SKIP] Already cached: {cache_path}")
        return True

    result = run([
        sys.executable, "main.py", "data", "download",
        "--symbol", symbol, "--start", "20210101",
    ], timeout=120)
    ok = result.returncode == 0 and cache_path.exists()
    return check("download", ok, f"cache={'hit' if cache_path.exists() else 'miss'}")


def step_backtest(symbol: str, strategy: str = "sma_cross", extra_args: list = None) -> bool:
    """Run a single-stock backtest and verify outputs."""
    print(f"\n--- Backtest ({symbol} / {strategy}) ---")
    cmd = [sys.executable, "main.py", "backtest", "run",
           "--strategy", strategy, "--symbol", symbol]
    if extra_args:
        cmd.extend(extra_args)
    result = run(cmd, timeout=120)

    trade_path = ROOT / "output" / "trades" / f"{symbol}_{strategy}.csv"
    equity_path = ROOT / "output" / "trades" / f"{symbol}_{strategy}_equity.csv"
    trades_ok = trade_path.exists()
    equity_ok = equity_path.exists()
    all_ok = result.returncode == 0 and trades_ok and equity_ok
    return check(f"backtest ({strategy})", all_ok,
                 f"trades={'OK' if trades_ok else 'MISSING'}, equity={'OK' if equity_ok else 'MISSING'}")


def step_report(symbol: str, strategy: str = "sma_cross") -> bool:
    """Generate HTML report and verify it contains all indicator charts."""
    print(f"\n--- Report ({symbol} / {strategy}) ---")
    result = run([
        sys.executable, "main.py", "backtest", "report",
        "--symbol", symbol, "--strategy", strategy,
    ], timeout=60)

    report_path = ROOT / "output" / "reports" / f"{symbol}_{strategy}.html"
    ok = result.returncode == 0 and report_path.exists()
    detail = f"size={report_path.stat().st_size}B" if report_path.exists() else "missing"

    # Verify chart elements are present
    if report_path.exists():
        html = report_path.read_text(encoding="utf-8")
        for elem in ["MA5", "MA10", "MA20", "MA60", "MACD", "DIF", "DEA", "KDJ"]:
            if elem not in html:
                ok = False
                detail += f" [missing:{elem}]"

    return check("report", ok, detail)


def step_compare(symbol: str) -> bool:
    """Run strategy comparison on a single stock."""
    print(f"\n--- Compare ({symbol}) ---")
    result = run([
        sys.executable, "main.py", "backtest", "compare",
        "--symbol", symbol,
    ], timeout=300)
    ok = result.returncode == 0
    return check("compare", ok)


def step_repl() -> bool:
    """Verify the REPL starts, shows help, and processes commands."""
    print("\n--- REPL ---")
    stdout = run_repl("help")
    all_ok = True
    all_ok &= check("REPL help", "可用命令" in stdout or "download" in stdout.lower())
    all_ok &= check("REPL strategies", "macd_cross" in stdout.lower() or len(stdout) > 500)

    # Try backtest through REPL
    stdout2 = run_repl("backtest --strategy sma_cross --symbol 000001.SZ")
    all_ok &= check("REPL backtest", "绩效摘要" in stdout2 or "总收益率" in stdout2 or "final_value" in stdout2.lower())

    return all_ok


def main():
    symbol = "000001.SZ"
    full = "--full" in sys.argv

    for arg in sys.argv[1:]:
        if arg.startswith("--symbol="):
            symbol = arg.split("=", 1)[1]

    print(f"QuantYB Smoke Test — {symbol}")
    t0 = time.monotonic()

    results = {}
    results["imports"] = step_imports()
    results["download"] = step_download(symbol)
    results["backtest_sma"] = step_backtest(symbol, "sma_cross")

    if full:
        results["backtest_macd"] = step_backtest(symbol, "macd_cross", ["--fast", "12", "--slow", "26"])
        results["backtest_rsi"] = step_backtest(symbol, "rsi", ["--period", "14"])
        results["backtest_kdj"] = step_backtest(symbol, "kdj", ["--k-period", "9"])
        results["backtest_bollinger"] = step_backtest(symbol, "bollinger", ["--period", "20"])
        results["backtest_single_ma"] = step_backtest(symbol, "single_ma", ["--period", "20"])

    results["report"] = step_report(symbol, "sma_cross")

    if full:
        results["compare"] = step_compare(symbol)
        results["repl"] = step_repl()

    elapsed = time.monotonic() - t0
    passed = sum(results.values())
    total = len(results)
    print(f"\n{'='*50}")
    print(f"Results: {passed}/{total} passed in {elapsed:.1f}s")
    for name, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print(f"{'='*50}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
