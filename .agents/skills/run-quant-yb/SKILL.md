---
name: run-quant-yb
description: Run, build, test, and smoke-test the A-share quant backtesting system. Use for: running backtests, generating reports, downloading data, scanning buy signals, comparing strategies, verifying the pipeline works end-to-end.
---

# QuantYB — A-share quant backtesting system

Python CLI tool + interactive REPL for Chinese A-share stock backtesting.
Built on Backtrader + Tushare + Pyecharts.

All paths below are relative to the repository root.

## Prerequisites

```bash
pip install -r requirements.txt
```

Required: Python 3.9+, a Tushare API token in `config.yaml`.

## Build

```bash
pip install -r requirements.txt
```

No compile step. The project is pure Python.

## Available strategies (8)

| Strategy | Name | Key params | Description |
|----------|------|------------|-------------|
| `sma_cross` | 双均线交叉 | `--fast` `--slow` | 快线上穿慢线买入，下穿卖出 |
| `macd_cross` | MACD金叉死叉 | `--fast` `--slow` `--signal-period` | DIF上穿DEA买入 |
| `kdj` | KDJ超买超卖 | `--k-period` `--smooth` `--oversold` `--overbought` | K<20金叉买入，K>80死叉卖出 |
| `bollinger` | 布林带 | `--period` `--devfactor` | 触及下轨反弹买入 |
| `rsi` | RSI超买超卖 | `--period` `--oversold` `--overbought` | RSI<30买入，>70卖出 |
| `single_ma` | 单均线 | `--period` | 价格上穿均线买入 |
| `volume_platform_breakout` | 放量平台突破 | strategy defaults | 平台突破并结合成交量确认 |
| `multi_timeframe_volume_trend` | 多周期量价趋势 | strategy defaults | 仅使用已完成周线过滤日线信号 |

## Run (agent path) — smoke test

The smoke test exercises the full pipeline programmatically:

```bash
python .agents/skills/run-quant-yb/smoke.py              # quick: imports + backtest + report
python .agents/skills/run-quant-yb/smoke.py --full       # also test REPL + all strategies
python .agents/skills/run-quant-yb/smoke.py --symbol 600519.SH  # pick a stock
```

What it verifies:
1. All core modules import cleanly (strategy, engine, data, visual)
2. All 8 strategies load without errors
3. Data is cached for the target symbol (downloads if missing)
4. A single-stock backtest runs for each strategy and produces trade/equity CSV files
5. An HTML report is generated (non-empty) with MA/MACD/KDJ charts
6. (--full) The interactive REPL starts and processes commands

Exit code 0 = all checks passed.

## Run (agent path) — direct CLI

For individual operations without the full smoke test:

```bash
# Download a single stock (skip if already cached)
python main.py data download --symbol 000001.SZ --start 20210101

# Run backtest with any strategy
python main.py backtest run --strategy sma_cross --symbol 000001.SZ --fast 5 --slow 20
python main.py backtest run --strategy macd_cross --symbol 000001.SZ --fast 12 --slow 26
python main.py backtest run --strategy rsi --symbol 000001.SZ --period 14 --oversold 30 --overbought 70
python main.py backtest run --strategy kdj --symbol 000001.SZ --k-period 9 --smooth 3
python main.py backtest run --strategy bollinger --symbol 000001.SZ --period 20 --devfactor 2
python main.py backtest run --strategy single_ma --symbol 000001.SZ --period 20

# Generate HTML report (with technical indicators)
python main.py backtest report --symbol 000001.SZ --strategy sma_cross

# Compare all strategies on one stock
python main.py backtest compare --symbol 000001.SZ
```

## Run (agent path) — REPL via pipe

```bash
echo "backtest --strategy sma_cross --symbol 000001.SZ" | python main.py
echo "report --symbol 000001.SZ --strategy sma_cross" | python main.py
```

The REPL exits when stdin closes. Exit code may be non-zero (EOF interrupts the loop); check stdout for results.

## Run (human path)

```bash
python main.py              # interactive REPL — type commands at the quant> prompt
python main.py data download --symbol 000001.SZ  # direct CLI (scriptable)
```

## Direct invocation (library path)

Strategies and engine are importable without the CLI layer:

```python
import sys; sys.path.insert(0, '.')
from engine.runner import BacktestRunner, load_strategy_class
import yaml, pandas as pd

config = yaml.safe_load(open('config.yaml'))
df = pd.read_csv('data/cache/000001.SZ.csv', dtype={'date': str})
df['date'] = pd.to_datetime(df['date'])

runner = BacktestRunner(config)
cls = load_strategy_class('sma_cross')
result = runner.run(df, cls, {'symbol': '000001.SZ'})
print(result['stats'])
```

## Tests

Run the unit/contract suite first, then the cached-data smoke test for end-to-end verification:

```bash
python -m unittest discover -s tests
python .agents/skills/run-quant-yb/smoke.py --full
```

## Gotchas

- **Tushare token required**: `config.yaml` must contain a valid `tushare.token`. Without it, `data download` will fail (backtest/report work fine on cached data).
- **Data must be downloaded before backtesting**: `backtest run --symbol X` needs `data/cache/X.csv` to exist first. The smoke test handles this automatically.
- **REPL exit code**: Piping commands to the REPL produces non-zero exit codes because the EOF raises `KeyboardInterrupt` in the read loop. Check stdout for results, not exit code.
- **Pyecharts version**: Tested with pyecharts 2.0.3 and 2.1.0. The `label_opts` parameter on `MarkPointItem` requires 2.0+.
- **Position sizing**: Strategies buy 95% of available cash rounded to 100-share lots (A-share minimum unit). Small accounts may have trouble with high-priced stocks.
- **Win rate**: The backtest stats show "win rate" based on net PnL (after commission). The report's win rate is based on gross PnL. These may differ because of minimum commission effects.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `No module named 'strategy'` | Run from repo root, or add repo root to `sys.path` |
| `缓存数据不存在` | Run `python main.py data download --symbol <SYMBOL>` first |
| `交易流水不存在` | Run `python main.py backtest run --strategy <S> --symbol <SYM>` first |
| `__init__() got an unexpected keyword argument 'label_opts'` | Upgrade pyecharts: `pip install pyecharts>=2.0.0` |
| `is_connect_nones` error | Upgrade pyecharts: `pip install pyecharts>=2.0.0` |
