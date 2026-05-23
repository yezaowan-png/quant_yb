# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

A股（Chinese A-share）量化回测系统。支持从 Tushare 下载日K线数据、运行策略回测、扫描买点信号、生成可视化 HTML 报告。提供 CLI 直接命令和交互式命令 REPL 两种使用方式。

## Commands

```bash
# 安装依赖
pip install -r requirements.txt

# 交互式命令 REPL
python main.py

# 数据下载（默认全部A股剔除ST，默认20210101至今）
python main.py data download
python main.py data download --symbol 000001.SZ --start 20220101 --end 20231231 --force

# 策略回测（单只 / 批量）
python main.py backtest run --strategy sma_cross --symbol 000001.SZ
python main.py backtest run --strategy sma_cross --symbols "000001.SZ,600519.SH" --fast 5 --slow 20

# 扫描近N日买点
python main.py backtest scan --strategy sma_cross --days 5

# 生成可视化报告
python main.py backtest report --symbol 000001.SZ --strategy sma_cross
```

## Architecture

```
main.py              → Click CLI 入口，注册 data / backtest 两个命令组
cli/
  shell.py           → 交互式命令 REPL（直接输入命令而非逐级菜单）
  data_cli.py        → `data download` 命令组
  backtest_cli.py    → `backtest run` / `backtest scan` / `backtest report` 命令组
data/
  downloader.py      → Tushare API 封装（股票列表获取、日K线下载、本地CSV缓存）
engine/
  runner.py          → Backtrader 回测引擎封装（绩效指标、交易流水、权益曲线、买点扫描）
strategy/
  base.py            → BaseStrategy 基类（T+1 规则、A股佣金/印花税、交易记录、买点追踪）
  sma_cross.py       → 双均线交叉策略示例
visual/
  kline_chart.py     → Pyecharts K线图 + 买卖点标记
  report.py          → 组合 HTML 报告（K线图 + 权益曲线 + 回撤）
```

## Key design patterns

- **策略加载约定**：策略名用 snake_case（如 `sma_cross`），对应文件 `strategy/sma_cross.py`，类名自动推导为 PascalCase + `Strategy`（如 `SmaCrossStrategy`）。见 `engine/runner.py:load_strategy_class()`。
- **策略子类化**：所有策略继承 `BaseStrategy`，只需覆写 `_init_indicators()`、`_next_buy_signal(data)`、`_next_sell_signal(data)` 三个方法，并定义 `params` 元组。
- **A股手续费**：`AShareCommission` 类（`strategy/base.py`）实现佣金 + 卖出千分之一印花税 + 最低5元佣金。`BaseStrategy.notify_order` 通过 `today > buy_date` 保证 T+1 卖出限制。
- **买点追踪**：`BaseStrategy.buy_signal_dates` 记录所有买入信号日期（无论是否实际成交），供 `BacktestRunner.scan_recent_buy_signals()` 扫描使用。
- **配置单一入口**：所有配置集中在项目根目录 `config.yaml`，通过 `yaml.safe_load` 加载。各 CLI 模块有各自的 `_load_config()` 函数。
- **数据流**：Tushare stock_basic（获取全A股列表，剔除ST）→ `DataDownloader.download_batch()` → `data/cache/*.csv` → `BacktestRunner.run()` → `output/trades/*.csv` + `output/signals/*.csv` → `generate_report()` → `output/reports/*.html`

## Documentation sync

当代码发生改动时，必须同步更新以下两篇文档：
- **`README.md`** — 面向软件小白的用户使用说明。如果改动影响使用方式（新增命令、修改参数、改变输出格式等），需更新对应章节。
- **`TECHNICAL.md`** — 面向初学者的技术文档。如果改动涉及架构变化、新增/删除模块、修改设计模式或数据流，需更新对应章节。

纯 bug 修复、代码格式化、内部重构（不改变外部行为和架构）不需要更新文档。

## Dependencies

- **backtrader** — 回测引擎核心，Cerebro 架构
- **tushare** — A股行情数据 API（需 token，配在 config.yaml）
- **click** — CLI 框架
- **pyecharts** — ECharts Python 绑定，生成 HTML 图表
- **pandas / numpy** — 数据处理
