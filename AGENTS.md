# AGENTS.md

## 项目概览

这是一个面向中国 A 股的量化交易/回测项目。项目使用 Tushare 下载日线行情并缓存为本地 CSV，使用 Backtrader 执行事件驱动回测，通过 Click 提供直接命令和交互式 REPL，并输出交易流水、权益曲线、买点扫描结果和 HTML 可视化报告。

当前主要数据粒度是日 K。策略以单标的或批量 A 股为对象，内置均线、MACD、KDJ、RSI、布林带、单均线和放量平台突破等技术指标策略。

## 目录结构说明

- `main.py`：程序入口，注册 `data`、`backtest`、`stats` 命令组；无子命令时进入交互式 REPL。
- `cli/`：命令行层。`data_cli.py` 负责数据下载，`backtest_cli.py` 负责回测、扫描、策略对比和报告生成，`stats_cli.py` 负责统计分析报告，`shell.py` 负责交互式命令和流水线执行。
- `data/`：数据读取和下载。`downloader.py` 封装 Tushare API、本地 CSV 缓存、限流和批量下载；`data/cache/` 存放行情缓存。
- `engine/`：回测引擎封装。`runner.py` 负责加载策略、配置 Backtrader、计算绩效、导出交易流水/权益/买点信号。
- `strategy/`：策略代码。`base.py` 定义 `BaseStrategy`、A 股交易约束和手续费模型；其他文件是一类策略一个模块。
- `visual/`：单标的 HTML 回测报告和 K 线/指标图相关代码。
- `analysis/`：基于批量回测汇总 CSV 的全市场统计分析和策略对比报告。
- `output/`：运行产物。`trades/` 为交易流水、权益曲线和汇总 CSV，`reports/` 为单标的 HTML 报告，`signals/` 为买点扫描 CSV，`statistics/` 为统计分析 HTML。
- `README.md`、`TECHNICAL.md`、`CLAUDE.md`：用户说明、技术说明和历史 AI 协作规范。

## 策略开发规范

- 新策略放在 `strategy/` 下，文件名使用 `snake_case.py`，策略类名使用 `PascalCaseStrategy`。例如 `sma_cross.py` 对应 `SmaCrossStrategy`。
- 新策略继承 `strategy.base.BaseStrategy`，优先只实现：
  - `_init_indicators()`
  - `_next_buy_signal(data) -> bool`
  - `_next_sell_signal(data) -> bool`
  - 如需部分卖出，再实现 `_next_sell_size(data, pos) -> int`
- 策略参数写在 `params` 元组中；面向 CLI 的参数元数据写在 `PARAM_DEFINITIONS`，别名写在 `PARAM_ALIASES`。
- 复用 `BaseStrategy` 中已有的仓位、T+1、涨跌停、成交量上限、买点记录和交易流水逻辑，除非明确要改交易模型。
- 指标计算优先使用 Backtrader 指标或清晰的 pandas/numpy 计算，不要在策略里混入文件读写、下载数据或报告生成。
- 策略中涉及历史窗口时，必须先检查数据长度；读取历史 bar 时明确区分 `data.close[0]` 当前 bar 和 `data.close[-1]` 历史 bar。

## 回测可靠性要求

- 修改回测逻辑时，必须说明影响范围：成交价格、手续费、滑点、涨跌停、成交量限制、T+1、绩效指标、导出文件格式中哪些发生变化。
- 单标的验证优先使用较小命令，例如：
  - `python main.py backtest run --strategy sma_cross --symbol 000001.SZ`
  - `python main.py backtest report --symbol 000001.SZ --strategy sma_cross`
- 批量回测会写入大量 `output/` 文件，修改共享逻辑前先用单标的验证，再考虑批量。
- 绩效统计字段来自 `engine/runner.py::_build_stats()`，改字段名或含义时必须同步更新 `analysis/`、`visual/` 和文档。
- 若依赖本地缓存或 Tushare 网络数据，验证结论中要注明数据来源和时间范围。

## 严禁未来函数和数据泄露

- 策略信号只能使用当前 bar 及其之前的数据，不得使用未来 bar、全样本统计或回测结束后才知道的信息。
- 构造突破、平台、均量、排名等条件时，若当天数据用于触发信号，历史基准窗口应从 `-1` 开始，不要把当天高低点反向纳入基准。
- 扫描买点时必须基于实际交易日窗口，而不是自然日粗略相减。
- 不得用报告生成、汇总分析或全市场回测结果反向影响单次策略信号。
- 批量选股需注意幸存者偏差：当前 `get_stock_list()` 以 Tushare 当前上市列表为基础并过滤 ST，历史退市股/历史 ST 状态可能未覆盖；涉及严肃绩效判断时必须标注该限制。

## 手续费、滑点和成交价格

- A 股手续费模型在 `strategy/base.py::AShareCommission`：佣金、卖出印花税、最低佣金来自 `config.yaml` 的 `backtest` 配置。
- `engine/runner.py::BacktestRunner` 会设置 `cerebro.broker.set_slippage_perc()`，默认值来自 `backtest.slippage_perc`。
- `BaseStrategy` 默认按可用资金 95% 买入，按 100 股一手取整；卖出默认清仓，除非策略覆盖 `_next_sell_size()`。
- 成交记录中的 `price` 和 `commission` 来自 Backtrader 订单成交回调，不要用信号日收盘价手工替代真实成交价。
- 涨跌停和成交量限制由 `enforce_price_limits`、`limit_pct`、`volume_limit_ratio`、`volume_unit` 控制；调整这些规则需要同步说明回测可比性变化。

## 修改代码前后的流程

- 开始前先读相关入口、策略、配置和文档，不要只凭文件名猜行为。
- 先检查工作区状态；当前仓库可能有用户未提交改动，不得回滚或覆盖无关改动。
- 改业务逻辑前先定位影响链路：CLI 参数 -> 配置 -> 数据读取 -> 策略 -> 回测引擎 -> 输出/报告。
- 小步修改，避免顺手重构；只改完成任务必需的文件。
- 改动影响用户命令、参数、输出字段或架构时，同步更新 `README.md` 和/或 `TECHNICAL.md`；纯内部修复可不更新文档。
- 提交结果前运行可行的最小验证命令，并在回复中说明实际运行了什么、是否通过、有哪些未验证。

## 运行和验证命令

- 安装依赖：`pip install -r requirements.txt`
- 进入交互式 REPL：`python main.py`
- 下载数据：`python main.py data download --symbol 000001.SZ --start 20210101 --end 20231231`
- 单标的回测：`python main.py backtest run --strategy sma_cross --symbol 000001.SZ`
- 多标的回测：`python main.py backtest run --strategy sma_cross --symbols "000001.SZ,600519.SH"`
- 扫描买点：`python main.py backtest scan --strategy sma_cross --days 5`
- 生成单标的报告：`python main.py backtest report --symbol 000001.SZ --strategy sma_cross`
- 策略对比：`python main.py backtest compare --symbol 000001.SZ`
- 单策略统计：`python main.py stats analyze --strategy rsi`
- 多策略统计对比：`python main.py stats compare`
- 流水线执行：`python main.py run "download; backtest --strategy rsi; report; stats compare"`
- 自动化测试命令：`python -m unittest discover -s tests`
- 语法检查命令：`python -m compileall main.py cli data engine strategy visual analysis`
- 格式化/静态检查命令：待确认。当前未发现 Ruff、Black、Mypy 或 pre-commit 配置。

## 回测报告输出要求

- 回测流水导出到 `output/trades/{symbol}_{strategy}.csv`，字段应保持 `date,symbol,direction,price,size,commission,pnl`。
- 权益曲线导出到 `output/trades/{symbol}_{strategy}_equity.csv`，至少包含日期、权益和回撤序列；新增字段需保持向后兼容。
- 批量回测汇总导出到 `output/trades/_summary_{strategy}.csv`；统计分析依赖该文件。
- 买点扫描导出到 `output/signals/buy_signals_{strategy}_{date}.csv`。
- 单标的 HTML 报告导出到 `output/reports/{symbol}_{strategy}.html`；统计分析 HTML 导出到 `output/statistics/`。
- 报告中的指标口径必须与回测导出的 CSV 一致，不得在报告层重新定义收益、回撤、胜率等核心口径。

## Codex 回复格式要求

- 回复使用中文，先给结论，再列关键依据和验证结果。
- 涉及代码修改时，明确列出修改文件、修改目的、运行过的命令和结果。
- 如果命令未运行、依赖本地数据缺失或需要网络/Tushare token，直接标注“未验证”或“待确认”，不要编造成功结果。
- 涉及量化结果时，注明标的、策略、日期范围、数据源、手续费/滑点设置和输出文件路径。
- 对可能影响回测可信度的问题要主动提示，例如未来函数、数据泄露、幸存者偏差、成交约束不完整。

## 重构限制

- 不要为了风格偏好大规模重命名、移动目录或改写 CLI。
- 不要把策略、数据下载、回测引擎和报告生成混在一个模块中。
- 不要改变现有输出文件名、CSV 字段或命令参数，除非用户明确要求；必须改变时要同步更新所有调用方和文档。
- 不要删除 `output/`、`data/cache/` 或用户配置文件，除非用户明确要求。
- 不要把真实 Tushare token、缓存数据或大规模运行产物写入文档或回复。
