# A股量化回测系统 — 技术文档

## 技术栈

| 组件 | 库 | 用途 |
|------|-----|------|
| CLI 框架 | click | 命令行参数解析、交互式命令 REPL |
| 数据源 | tushare | A股日K线行情数据 API、股票列表 |
| 回测引擎 | backtrader | 事件驱动回测框架（Cerebro 架构） |
| 图表 | pyecharts / ECharts | pyecharts 用于分析报告图表；回测报告改用自研 JS 渲染器直连 ECharts CDN |
| 数据处理 | pandas, numpy | DataFrame 操作、数值计算 |
| 配置 | pyyaml | YAML 配置文件解析 |

## 整体架构

```
┌──────────────────────────────────────────────┐
│                    main.py                    │
│              (Click CLI Group)                │
│    注册 data / backtest 命令组                │
│    无子命令时 → 进入交互式命令 REPL           │
└──────────────┬───────────────┬────────────────┘
               │               │
    ┌──────────▼──────┐  ┌─────▼───────────────┐
    │  cli/data_cli   │  │  cli/backtest_cli   │
    │  data download  │  │  backtest run       │
    │                  │  │  backtest scan      │
    │                  │  │  backtest report    │
    └────────┬────────┘  └─────┬───────────────┘
             │                 │
    ┌────────▼────────┐  ┌─────▼───────────────┐
    │ data/downloader │  │  engine/runner      │
    │ Tushare API 封装 │  │  Backtrader 封装    │
    │ 股票列表获取     │  │  绩效计算/交易导出   │
    │ 本地CSV缓存      │  │  买点扫描/汇总      │
    └────────┬────────┘  └─────┬───────┬───────┘
             │                 │       │
             │          ┌──────▼──┐    │
             │          │ strategy │    │
             │          │ base.py  │    │
             │          │ sma_cross│    │
             │          └──────────┘    │
             │                          │
             │                 ┌────────▼──────┐
             │                 │ visual/report │
             │                 │ K线 + 权益曲线 │
             │                 └───────────────┘
             │
    ┌────────▼────────┐
    │   data/cache/   │  ← CSV 缓存文件
    │   output/       │  ← 交易流水 & 买点信号 & HTML 报告
    └─────────────────┘
```

### 数据流

```
Tushare API (stock_basic)
    │ 获取全A股列表，剔除ST
    ▼
DataDownloader.download_batch()
    │ 调用 Tushare daily API，清洗数据
    ▼
data/cache/*.csv
    │
    ▼
BacktestRunner.run()
    │ 传入 DataFrame + 策略类
    ▼
output/trades/{symbol}_{strategy}.csv         ← 交易流水
output/trades/{symbol}_{strategy}_equity.csv  ← 每日权益
    │
    ▼
BacktestRunner.scan_recent_buy_signals()
    │ 扫描各股票的 buy_signal_dates
    ▼
output/signals/buy_signals_{strategy}_{date}.csv  ← 近5日买点汇总
    │
    ▼
generate_report()
    │ 读取 K线数据 + 交易流水 + 权益数据
    ▼
output/reports/{symbol}_{strategy}.html       ← 可视化报告
```

---

## 各模块实现思路

### 指数概览链路

第一阶段指数概览覆盖主要宽基和风格指数，指数清单配置在 `config.yaml::index_overview.indexes`，和股票回测链路保持隔离：

```
Tushare index_daily
    │
    ▼
DataDownloader.download_index()
    │ 清洗字段：date/open/high/low/close/pre_close/change/pct_chg/volume/amount
    ▼
data/cache/index/{symbol}.csv
    │
    ├─ analysis/index_overview.py 生成趋势、动量、震荡和风险概览
    │
    ▼
visual/index_report.py
    │ 生成日K/周K/月K + MACD/KDJ/RSI HTML
    ▼
output/reports/index/{symbol}_overview.html
```

CLI 入口为 `python main.py index download/report/overview`，单指数使用 `--symbol`，第一阶段批量生成使用 `--all`。`overview` 会先调用 `download_index()` 更新缓存，再调用 `generate_index_report()` 生成 HTML；`--all` 会按配置顺序逐个处理 `000001.SH`、`399001.SZ`、`399006.SZ`、`000688.SH`、`000300.SH`、`000905.SH`、`000852.SH`、`000985.SH`。该链路不读取交易流水、不生成权益曲线，也不改变现有回测 CSV 字段。

### 汇总面板链路

`python main.py dashboard` 会调用 `visual/dashboard.py::generate_dashboard()`，扫描本地输出目录并生成 `output/reports/dashboard.html`。阶段 4 后该页面定位为“研究总控面板”，用于把市场环境、数据健康、策略表现、信号复盘、实验归档和最近报告放在同一个入口查看。

面板只读本地产物：

- 指数概览：读取 `config.yaml::index_overview.indexes`、`data/cache/index/{symbol}.csv` 和 `output/reports/index/{symbol}_overview.html`。
- 市场温度：从指数缓存最新一行读取 `pct_chg`，计算指数平均涨跌、上涨/下跌数量、最强/最弱指数；无指数缓存时显示待生成。
- 数据健康：扫描 `data/cache/*.csv`、`data/cache/index/*.csv`、`output/reports/index/*.html`，展示股票缓存数量、最新股票缓存日期、过期缓存数量、指数缓存覆盖度和指数报告数量。
- 策略排行榜：读取 `output/trades/_summary_{strategy}.csv`，复用 `analysis/analyzer.py::compute_stats()`，按全市场平均收益排序，避免 dashboard 另起一套绩效口径。
- 策略汇总：按 `strategy/*.py` 自动发现策略模块，链接到 `output/statistics/analysis_{strategy}.html`，展示股票数、平均收益、交易股平均收益、正收益比例、夏普、回撤和报告生成状态。
- 策略横向对比：若存在 `output/statistics/comparison.html`，顶部提供入口；不存在时显示为待生成状态。
- 信号复盘：读取 `output/decisions/decision_memory.csv`，展示信号数量、已评估/待评估数量、最近信号日期、5 日未来收益均值和 5 日超额收益均值。
- 最近实验：扫描 `output/experiments/*/manifest.json` 和实验目录的 `reports/` 子目录，用于展示最近实验归档入口。
- 单标的报告：扫描 `output/reports/*.html`，排除 `dashboard.html`，展示最近生成的单标的报告入口。
- 风险提示：根据本地状态提示幸存者偏差、缓存日期不齐、基准缓存缺失、信号待评估、未来函数审计尚未接入等限制。

该面板只聚合已有输出，不重新下载数据、不运行回测、不改变任何 CSV 口径。页面中的策略收益、回撤、夏普、正收益占比等字段必须继续来自回测汇总 CSV 和 `compute_stats()`；不得在 dashboard 层重新定义绩效指标。

### 实验配置化链路

`python main.py experiment run experiments/sma_cross_baseline.yaml` 会调用 `experiment/runner.py::run_experiment()`，把一次研究任务从 YAML 配置转换为独立归档目录：

```text
experiments/{name}.yaml
    │
    ▼
experiment.runner.run_experiment()
    │  读取 config.yaml 的数据目录、回测默认值和输出根目录
    │  应用实验 YAML 中的 strategy / symbols / date range / params / cost / benchmark
    ▼
BacktestRunner.run()
    │  对每个显式 symbols 顺序回测
    ▼
output/experiments/{experiment_id}/
    ├── config.yaml
    ├── summary.csv
    ├── manifest.json
    ├── trades/
    └── reports/
```

设计边界：

- 实验配置必须显式提供 `symbols` 或 `symbol`，不允许默认全市场运行，避免误触发大批量任务。
- 回测仍使用 `BacktestRunner.run()` 和现有策略加载约定，不改变成交价格、手续费模型、滑点、T+1、涨跌停或成交量限制逻辑。
- `cost` 只允许覆盖 `backtest` 中已有的成本/约束字段：`initial_cash`、`commission`、`stamp_duty`、`min_commission`、`slippage_perc`、`enforce_price_limits`、`limit_pct`、`volume_limit_ratio`、`volume_unit`。未知字段直接报错。
- 实验输出写入 `output/experiments/{experiment_id}/`，不会覆盖全局 `output/trades/_summary_{strategy}.csv`，也不会自动写入全局 `output/decisions/decision_memory.csv`。
- `manifest.json` 记录实验输入、输出路径、开始/结束时间、运行状态、成功/失败标的数量、警告和错误；dashboard 会读取这些 manifest 展示最近实验。

实验配置示例：

```yaml
id: sma_cross_baseline
strategy: sma_cross
symbols:
  - 000001.SZ
start: "20210101"
end: "20231231"
benchmark: 000300.SH
params:
  fast: 5
  slow: 20
cost:
  commission: 0.00025
  stamp_duty: 0.001
  slippage_perc: 0.001
```

### 决策记忆链路

Decision Memory 是一个事后复盘层，目标是记录策略产生的买点，并在未来数据足够后评估这些买点之后的表现。它不改变策略信号、不参与下单、不改变 Backtrader 成交模型。

```
backtest scan / 批量 backtest run
    │ 产生近 N 个交易日买点
    ▼
output/signals/buy_signals_{strategy}_{date}.csv
    │
    ├─ engine/runner.py::_export_buy_signals()
    │     自动调用 decision.recorder.append_buy_signals()
    ▼
output/decisions/decision_memory.csv
    │
    ├─ python main.py decision evaluate
    │     用本地行情缓存计算未来 5/10/20 个实际交易日收益
    ▼
dashboard / decision summary
```

#### 记录阶段

`decision/recorder.py` 负责稳定记录信号：

- `signal_id` 由 `symbol + strategy + signal_date + signal_type + params_json` 生成，用于去重。
- `params_json` 保存策略参数快照，避免不同参数组合的同日信号混在一起。
- `market_context_json` 预留给后续市场环境、指数状态、行业状态等上下文。
- 记录时不计算未来收益，未来收益字段保持空值，`evaluation_status` 默认为 `pending`。

这一步可以由两种方式触发：

```bash
# 扫描或批量回测后自动写入
python main.py backtest scan --strategy sma_cross --days 5

# 手动把最近一次买点扫描 CSV 写入
python main.py decision record --strategy sma_cross
```

#### 评估阶段

`decision/evaluator.py` 只读取本地缓存，不联网：

1. 读取 `output/decisions/decision_memory.csv`。
2. 对每条信号找到 `signal_date` 当天或之后的第一个交易日。
3. 以该交易日收盘价为起点，计算未来第 5、10、20 个实际交易日的收益。
4. 如果 `benchmark.enabled=true` 且本地存在基准指数缓存，则计算同期基准收益和超额收益。
5. 根据数据完整程度更新状态：
   - `evaluated`：所有窗口都有未来数据。
   - `partial`：部分窗口有未来数据。
   - `pending_future_data`：未来数据不足。
   - `missing_symbol_data`：找不到标的缓存。

命令：

```bash
python main.py decision evaluate --strategy sma_cross --horizons 5,10,20
python main.py decision summary --strategy sma_cross
```

#### 未来函数边界

Decision Memory 中的 `future_*`、`benchmark_*` 和 `excess_*` 字段只能用于事后复盘：

- 策略类不得读取 `output/decisions/decision_memory.csv`。
- 回测信号不得依赖未来收益字段。
- dashboard 只展示已经生成的复盘结果，不反向影响任何策略。
- 若未来数据不足，字段保留空值，不用估算值填充。

这个设计可以帮助分析“信号有没有用”，但不会改变“信号如何产生”。

### `main.py` — 程序入口

**核心思路**：利用 Click 的 `group(invoke_without_command=True)` 特性，实现"无子命令时自动进入交互模式"。

```python
@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    if ctx.invoked_subcommand is None:
        from cli.shell import run_interactive
        run_interactive()
```

这样设计的好处：同一个入口，既能 `python main.py` 进入 REPL，也能 `python main.py data download ...` 直接执行命令。后者适合脚本化、批量处理场景。

**`run` 命令**：注册为 `@cli.command("run")`，接受命令字符串（分号/换行分隔）或 `--file` 脚本文件，调用 `shell.py` 中的 `_execute_pipeline()` 按顺序执行。支持 `!` 前缀忽略某条命令的失败。

---

### `cli/shell.py` — 交互式命令 REPL

**实现思路**：

1. **命令解析**：使用 `shlex.split()` 对用户输入进行安全分词（支持带引号的参数），然后用 `_parse_args()` 将 `--key value` 格式解析为字典。
2. **命令路由**：根据第一个词路由到对应的处理函数（`_cmd_download`、`_cmd_backtest`、`_cmd_scan`、`_cmd_report`），支持简写（如 `dl` → download、`bt` → backtest、`rp` → report）。
3. **异常保护**：每个命令用 `try/except` 包裹，出错时打印错误信息但不退出程序。
4. **自动发现**：`_list_cached_symbols()` 扫描 `data/cache/*.csv` 自动列出已下载的股票；`_list_strategies()` 扫描 `strategy/*.py` 自动列出可用策略。
5. **命令流水线**：`_execute_pipeline()` 接受分号或换行分隔的命令字符串，按序逐条执行。遇到错误时默认中止，可用 `!` 前缀忽略某条失败继续。`_cmd_run()` 在交互式 Shell 中暴露该能力（支持字符串参数和 `--file` 脚本文件）。CLI 中对应的 `run` 命令注册在 `main.py`。

**为什么从菜单改为命令 REPL？**
菜单模式需要一级一级输入，操作效率低，且无法组合参数。命令模式一次输入就能完成操作（如 `download --symbol 000001.SZ --start 20210101 --force`），更符合程序员使用习惯，也方便脚本化。

---

### `cli/data_cli.py` — 数据下载命令

**实现思路**：

- 未指定 `--symbol` 时，自动调用 `DataDownloader.get_stock_list()` 获取全A股列表（剔除ST股票）
- `--start` 和 `--end` 分别默认为 `20210101` 和当天日期
- 下载全部股票时会弹出确认提示，防止误操作

---

### `cli/backtest_cli.py` — 回测、扫描与报告命令

**实现思路**：

1. **`backtest run`**：
   - 股票选择有三种优先级：`--symbols`（逗号分隔多只） > `--symbol`（单只） > 所有已缓存股票
   - 单只股票回测时，直接输出绩效摘要到命令行
   - 多只股票回测时，调用 `run_batch()` 静默执行，最后导出汇总 CSV，同时自动扫描近5日买点
2. **`backtest scan`**：
   - 新增命令，对所有已缓存股票运行策略，检测近N日买点
   - 结果导出到 `output/signals/buy_signals_{策略名}_{日期}.csv`
   - 若 `decision_memory.enabled=true`，会同步写入 `output/decisions/decision_memory.csv`
3. **`backtest report`**：
   - 自动查找对应的交易流水文件和权益文件
   - 如果文件不存在给出明确提示（比如"请先执行 backtest run"）
4. **批量报告并行**：`_run_batch_reports()` 使用 `ThreadPoolExecutor`（而非 `ProcessPoolExecutor`）并行生成 HTML 报告。线程池避免 Windows 上多进程 spawn 导致的 OpenBLAS 内存耗尽和进程挂起问题。模块顶部在 import pandas 之前设置 `OPENBLAS_NUM_THREADS=1` 等环境变量，防止子线程中 OpenBLAS 多线程竞争。

---

### `data/downloader.py` — 数据下载器

**核心类**：`DataDownloader`

**设计要点**：

1. **股票列表获取**：`get_stock_list()` 方法调用 `pro.stock_basic(exchange='', list_status='L')` 获取全市场上市股票，自动过滤名称含 "ST" 的股票。返回包含 `ts_code` 和 `name` 的字典列表。

2. **默认日期范围**：`default_start()` 从 `config.yaml` 的 `defaults.start_date` 读取默认起始日期（当前为 `20210101`），`today_str()` 返回当天日期作为默认结束日期。

3. **增量更新**：`_save_cache()` 方法在保存时先读取已有缓存，与新数据 `pd.concat` 后再去重排序。这样多次下载同一只股票的不同时间段，数据会自动合并。

4. **缓存命中判断**：`download()` 方法先检查缓存的时间范围是否覆盖请求区间，如果完全覆盖则直接返回缓存数据，节省 API 调用。

5. **API 容错**：如果 Tushare API 调用失败，会回退到本地缓存数据（如果有的话），保证程序不会因网络问题崩溃。

6. **限流保护**：`download_batch()` 中每次 API 调用间隔 `sleep_seconds` 秒（配置文件中设置），避免触发 Tushare 的频率限制。

7. **数据清洗**：`_clean()` 方法把 Tushare 返回的字段名映射为标准英文名（如 `trade_date` → `date`），统一数据类型，删除空值行。

**为什么用 CSV 而不是数据库？**
对于个人量化回测场景，每只股票几千行数据，CSV 文件足够简单高效。不需要安装数据库，方便查看和手动编辑。

---

### `engine/runner.py` — 回测引擎

**核心类**：`BacktestRunner`、`EquityCurveAnalyzer`

**设计要点**：

1. **Backtrader 封装**：所有 backtrader 的 Cerebro 配置（数据喂入、资金设置、手续费、分析器）都在 `run()` 方法中完成，外部只需传入 DataFrame 和策略类即可。

2. **A 股手续费**：通过 `AShareCommission` 类（在 `strategy/base.py` 中定义）注入 Cerebro，实现佣金 + 卖出印花税 + 最低佣金。

3. **自定义分析器**：`EquityCurveAnalyzer` 继承 `bt.Analyzer`，在每个 bar 记录账户权益值。这是 backtrader 内置分析器不提供的功能。

4. **结果聚合**：`run()` 方法返回一个字典，包含四个部分：
   - `trade_records`：每笔交易的详细信息（日期、方向、价格、数量、盈亏）
   - `equity`：每日权益值 + 回撤序列
   - `stats`：绩效汇总（收益率、夏普比率、最大回撤、胜率等）
   - `buy_signal_dates`：所有出现买入信号的日期列表

5. **批量回测**：`run_batch()` 遍历多只股票，分别回测并导出各自的交易流水和权益数据，最后导出汇总 CSV。同时自动检测各股票近5日买点信号并导出汇总。

6. **买点扫描**：`scan_recent_buy_signals()` 对所有股票运行策略但不导出交易流水，只收集近N日出现买点的股票信息。

7. **信号过滤**：`_filter_recent_signals()` 根据数据的实际交易日历（而非自然日），取最后 N 个交易日作为判断窗口。

8. **动态加载策略**：`load_strategy_class()` 使用 `importlib.import_module()` 动态加载策略模块。命名约定：文件名 `sma_cross` → 类名 `SmaCrossStrategy`。

**回撤计算逻辑**：
```python
def compute_drawdowns(equity):
    arr = np.array(equity)
    peak = np.maximum.accumulate(arr)  # 历史最高点
    dd = (arr - peak) / peak           # 当前值与最高点的差距比例
    return dd * 100                     # 转为百分比
```

---

### `strategy/base.py` — 策略基类

**核心类**：`BaseStrategy`、`AShareCommission`

**设计思路**：模板方法模式。基类定义回测流程框架，子类只需覆写三个方法。

#### AShareCommission — A股手续费模型

```python
class AShareCommission(bt.CommInfoBase):
    def _getcommission(self, size, price, pseudoexec):
        value = abs(size) * price
        comm = value * 0.00025           # 佣金 0.025%
        comm = max(comm, 5.0)            # 最低 5 元
        if size < 0:                     # size < 0 表示卖出
            comm += value * 0.001        # 加收 0.1% 印花税
        return comm
```

关键点：
- `size > 0` 是买入，`size < 0` 是卖出
- A 股印花税只在卖出时收取
- 佣金有最低 5 元限制

#### BaseStrategy — 策略基类

**T+1 卖出限制**：A 股不能当天买当天卖。实现方式是记录买入日期，卖出前检查：

```python
def next(self):
    if self._next_buy_signal(data):
        self.buy_signal_dates.append(today)   # 记录买点日期
        if pos == 0:
            # A股最小交易单位 100 股（1手），按可用资金 95% 计算手数
            cash = self.broker.getcash()
            price = data.close[0]
            lots = int(cash * 0.95 / (price * 100))
            size = lots * 100
            if size > 0:
                self.buy(data=data, size=size)
                self._buy_dates[data] = today     # 记录买入日期

    elif pos > 0 and self._next_sell_signal(data):
        if today > buy_date:                      # 必须持有超过一天
            self.sell(data=data, size=pos)
```

**持仓管理**：
- 买入时按可用资金的 95% 计算手数（留 5% 缓冲应对滑点和手续费）
- 按 A 股规则取 100 股（1手）整数倍
- 卖出时清仓（size=pos），避免分批卖出复杂度

**买点追踪**：`buy_signal_dates` 列表记录所有出现买入信号的日期（无论是否实际成交），用于后续的买点扫描功能。这比只查交易记录更准确，因为当已有持仓时买入信号不会产生新的交易。

**交易记录**：通过覆写 `notify_order()` 和 `notify_trade()` 两个回调：
- `notify_order`：订单成交时记录买卖信息（日期、方向、价格、数量）
- `notify_trade`：一次完整买卖（开仓到平仓）完成后，把盈亏填充到对应的卖出记录上

#### 如何添加新策略？

1. 在 `strategy/` 下新建文件，比如 `macd_cross.py`
2. 继承 `BaseStrategy`，类名遵循 `XxxStrategy` 命名（如 `MacdCrossStrategy`）
3. 覆写三个方法：
   - `_init_indicators()` — 初始化技术指标（MACD、RSI 等）
   - `_next_buy_signal(data)` — 返回 True 时买入
   - `_next_sell_signal(data)` — 返回 True 时卖出
4. 定义 `params` 元组设置策略参数

示例框架：
```python
from strategy.base import BaseStrategy
import backtrader as bt

class MacdCrossStrategy(BaseStrategy):
    params = (
        ("fast", 12),
        ("slow", 26),
        ("signal", 9),
    )

    def _init_indicators(self):
        self.macd = {}
        self.macd_signal = {}
        for data in self.datas:
            macd = bt.indicators.MACD(
                data.close,
                period_me1=self.p.fast,
                period_me2=self.p.slow,
                period_signal=self.p.signal,
            )
            self.macd[data] = macd.macd
            self.macd_signal[data] = macd.signal

    def _next_buy_signal(self, data):
        return self.macd[data][0] > self.macd_signal[data][0]

    def _next_sell_signal(self, data):
        return self.macd[data][0] < self.macd_signal[data][0]
```

---

## 所有策略实现细节

### 1. 双均线交叉策略 (sma_cross) — `strategy/sma_cross.py`

#### 数学原理

**简单移动平均线 (SMA)**：

$$SMA_t(n) = \frac{1}{n}\sum_{i=0}^{n-1} P_{t-i}$$

其中 $P_t$ 是第 $t$ 天的收盘价，$n$ 是周期长度。

**金叉 (Golden Cross)**：短期均线从下方上穿长期均线，即：

$$SMA_t(n_{fast}) > SMA_t(n_{slow}) \quad \text{且} \quad SMA_{t-1}(n_{fast}) \leq SMA_{t-1}(n_{slow})$$

**死叉 (Death Cross)**：短期均线从上方下穿长期均线，即：

$$SMA_t(n_{fast}) < SMA_t(n_{slow}) \quad \text{且} \quad SMA_{t-1}(n_{fast}) \geq SMA_{t-1}(n_{slow})$$

#### 实现细节

**文件**：`strategy/sma_cross.py`
**类名**：`SmaCrossStrategy(BaseStrategy)`
**参数**：`fast_period=5`, `slow_period=20`

**技术指标初始化**（`_init_indicators`）：
```python
def _init_indicators(self):
    self.sma_fast = {}
    self.sma_slow = {}
    self.cross_up = {}
    self.cross_down = {}

    for data in self.datas:
        sma_f = bt.indicators.SMA(data.close, period=self.p.fast_period)
        sma_s = bt.indicators.SMA(data.close, period=self.p.slow_period)
        self.sma_fast[data] = sma_f
        self.sma_slow[data] = sma_s
        self.cross_up[data] = bt.indicators.CrossOver(sma_f, sma_s)
        self.cross_down[data] = bt.indicators.CrossDown(sma_f, sma_s)
```

- `CrossOver` 返回 1.0 表示当天发生上穿（金叉），0.0 表示未发生
- `CrossDown` 返回 1.0 表示当天发生下穿（死叉），0.0 表示未发生
- 使用字典存储指标是因为 backtrader 支持多数据源架构

**买入信号**（`_next_buy_signal`）：
```python
def _next_buy_signal(self, data) -> bool:
    return bool(self.cross_up.get(data, 0))
```

**卖出信号**（`_next_sell_signal`）：
```python
def _next_sell_signal(self, data) -> bool:
    return bool(self.cross_down.get(data, 0))
```

#### 策略优缺点

**优点**：
- 逻辑简单易懂，适合入门
- 在趋势明显的市场（牛市/熊市）中能捕捉到大段行情
- 参数少，不易过拟合

**缺点**：
- 震荡市中频繁产生假信号，导致连续亏损
- 信号滞后于价格变化（基于历史均值）
- 无法识别市场状态（趋势 vs 震荡）

#### 参数调优建议

| 快线 | 慢线 | 特点 | 适用场景 |
|------|------|------|----------|
| 5 | 20 | 偏短线，信号灵敏 | 短线交易、波动大的个股 |
| 10 | 30 | 偏中线，过滤噪音 | 中短线、兼顾趋势和灵活性 |
| 20 | 60 | 中长线，趋势明确 | 大趋势行情、大盘蓝筹 |

---

### 2. MACD金叉策略 (macd_cross) — `strategy/macd_cross.py`

**核心思想**：MACD 指标的金叉/死叉判断买卖。DIF（快线）上穿 DEA（慢线）为金叉买入，下穿为死叉卖出。

**参数**：`fast_period=12`, `slow_period=26`, `signal_period=9`

**数学公式**（EMA = 指数移动平均）：

$$DIF = EMA(close, 12) - EMA(close, 26)$$
$$DEA = EMA(DIF, 9)$$
$$MACD柱 = 2 \times (DIF - DEA)$$

**金叉条件**：`DIF_t > DEA_t` 且 `DIF_{t-1} <= DEA_{t-1}`
**死叉条件**：`DIF_t < DEA_t` 且 `DIF_{t-1} >= DEA_{t-1}`

---

### 3. KDJ超买超卖策略 (kdj) — `strategy/kdj.py`

**核心思想**：利用KDJ指标的超买超卖区间。K值低于oversold（20）且出现金叉时买入，高于overbought（80）且出现死叉时卖出。

**参数**：`k_period=9`, `smooth=3`, `oversold=20`, `overbought=80`

**KDJ 计算流程**：
1. $RSV(n) = \frac{close - low_n}{high_n - low_n} \times 100$
2. $K = EMA(RSV, smooth)$
3. $D = EMA(K, smooth)$
4. $J = 3K - 2D$

**引入自定义 Indicator**：因为 backtrader 不内置 KDJ，策略文件中定义了 `KDJIndicator(bt.Indicator)` 类，通过 `Highest`/`Lowest` 加 `EMA` 组合实现。

---

### 4. 布林带策略 (bollinger) — `strategy/bollinger.py`

**核心思想**：价格触及布林下轨后反弹买入，触及上轨后回落卖出。前一天收盘价低于下轨 → 今天可能反弹买入；前一天收盘价高于上轨 → 今天可能回落卖出。

**参数**：`period=20`, `devfactor=2.0`

**布林带公式**：
- 中轨 = $SMA(close, period)$
- 上轨 = 中轨 + $devfactor \times \text{标准差}$
- 下轨 = 中轨 - $devfactor \times \text{标准差}$

---

### 5. RSI超买超卖策略 (rsi) — `strategy/rsi.py`

**核心思想**：RSI < oversold（30）为超卖区买入，RSI > overbought（70）为超买区卖出。

**参数**：`period=14`, `oversold=30`, `overbought=70`

**RSI 公式**（Wilder's RSI）：

$$RSI = 100 - \frac{100}{1 + RS}$$

其中 $RS = \frac{\text{平均涨幅}}{\text{平均跌幅}}$（period 日平滑）

---

### 6. 单均线策略 (single_ma) — `strategy/single_ma.py`

**核心思想**：最简单的趋势策略——收盘价上穿均线买入，下穿卖出。

**参数**：`period=20`

**适用场景**：强趋势行情中简单有效；震荡市中假信号非常多。

---

### 7. 放量平台突破策略 (volume_platform_breakout) — `strategy/volume_platform_breakout.py`

**核心思想**：用今天之前的历史 K 线识别窄幅整理平台，等待价格放量向上突破，并用 MA20 趋势过滤减少假突破。

该策略刻意把“平台识别”和“突破确认”分成两部分：
- 平台识别只使用历史窗口，即 `[-1]` 到 `[-lookback]`，不包含今天。
- 突破确认使用今天的收盘价和成交量，即 `[0]`。

这样可以避免前视偏差。如果把今天的 high 放进平台上沿，突破当天的高点会抬高 `upper`，导致突破判断被污染，甚至出现“用今天定义今天是否突破”的逻辑错误。

**参数**：
- `lookback=60`：平台识别回看交易日数
- `max_range_pct=0.20`：平台最大振幅
- `touch_tolerance=0.06`：上下沿触碰容忍度
- `min_upper_touches=2` / `min_lower_touches=2`：上下沿最少触碰次数
- `breakout_pct=0.02`：突破上沿确认幅度
- `volume_period=30` / `volume_multiplier=1.3`：放量确认条件
- `ma_slope_days=1`：MA20 向上确认天数
- `platform_sell_tolerance=0.05`：跌破买入平台上沿卖出的容忍度
- `stop_loss_pct=0.10`：相对实际买入成交价的止损比例

#### 平台定义

对每个交易日 `t`，平台窗口为：

$$[t-lookback, t-1]$$

平台上沿：

$$upper_t = \max(high_{t-lookback}, ..., high_{t-1})$$

平台下沿：

$$lower_t = \min(low_{t-lookback}, ..., low_{t-1})$$

平台振幅：

$$range\_pct_t = \frac{upper_t - lower_t}{lower_t}$$

当 `range_pct_t <= max_range_pct` 时，认为平台足够紧凑。

#### 边界触碰次数

上沿触碰条件：

$$high_i \ge upper_t \times (1 - touch\_tolerance)$$

下沿触碰条件：

$$low_i \le lower_t \times (1 + touch\_tolerance)$$

触碰次数用于过滤“只有一次尖峰或一次探底”的不稳定区间。默认要求上下沿都至少触碰 2 次，表示平台压力位和支撑位都被市场反复确认过。

#### 突破与放量确认

突破条件：

$$close_t > upper_t \times (1 + breakout\_pct)$$

放量条件：

$$volume_t > SMA(volume, volume\_period)_{t-1} \times volume\_multiplier$$

均量计算同样排除今天，使用 `data.volume[-1]` 到 `data.volume[-volume_period]`。这样今日成交量只作为突破当天的确认信号。

#### 趋势过滤

策略额外要求：

$$close_t > MA20_t$$

$$MA20_t > MA20_{t-ma\_slope\_days}$$

这两条用于确认突破发生在短中期转强环境里，而不是均线仍然走弱时的下跌反弹。

**买入规则**：
1. 平台上沿 `upper` 使用过去 `lookback` 日 high 的最高值，平台下沿 `lower` 使用过去 `lookback` 日 low 的最低值。
2. 平台计算排除今天，只使用 `data.high[-1]` 到 `data.high[-lookback]`、`data.low[-1]` 到 `data.low[-lookback]`。
3. 平台振幅 `(upper - lower) / lower <= max_range_pct`。
4. 上沿触碰次数 `high >= upper * (1 - touch_tolerance)` 不少于 `min_upper_touches`。
5. 下沿触碰次数 `low <= lower * (1 + touch_tolerance)` 不少于 `min_lower_touches`。
6. 今日收盘价 `close > upper * (1 + breakout_pct)`。
7. 今日成交量大于过去 `volume_period` 日均量的 `volume_multiplier` 倍。
8. 趋势过滤：`close > MA20`，且 `MA20[0] > MA20[-ma_slope_days]`。

**卖出规则**：
- 收盘价跌破 MA20
- 或收盘价跌破买入时记录的平台上沿的 95%，即 `entry_upper * (1 - platform_sell_tolerance)`
- 或收盘价相对实际买入成交价跌幅达到 `stop_loss_pct`

#### 实现细节

**文件**：`strategy/volume_platform_breakout.py`
**类名**：`VolumePlatformBreakoutStrategy(BaseStrategy)`

**核心状态变量**：
- `self.ma20[data]`：20 日均线，用于趋势过滤和卖出判断
- `self._entry_upper[data]`：买入信号出现时的平台上沿。卖出时判断是否跌回该平台上沿下方
- `self._entry_price[data]`：实际买入成交价。卖出时用于计算固定止损

**为什么要保存 `_entry_upper`**：

平台上沿每天都会变化。如果卖出时重新计算平台上沿，可能会用新的平台边界替代买入时的突破位，导致突破失败判断漂移。因此策略在买入信号成立时记录当时的 `upper`，后续平台跌破只对比这个入场平台。

**为什么要保存 `_entry_price`**：

买入信号通常在收盘后产生，实际成交发生在下一根 K 线。策略通过 `notify_order()` 记录真实成交价，而不是用信号日收盘价估算止损价。固定止损阈值为：

$$entry\_price \times (1 - stop\_loss\_pct)$$

**为什么持仓时 `_next_buy_signal()` 直接返回 False**：

`BaseStrategy.next()` 会在每个 bar 都调用 `_next_buy_signal()`，即使已经持仓也会先检查买入信号。新策略在持仓期间不再刷新 `_entry_upper`，避免后续再次出现突破形态时覆盖原始入场平台。

**历史长度要求**：

策略至少需要：

```python
max(lookback, volume_period, 20 + ma_slope_days)
```

个交易日以上的数据，才能同时满足平台识别、均量计算、MA20 和 MA20 斜率判断。

**Backtrader 索引约定**：
- `data.close[0]`：今天
- `data.close[-1]`：昨天
- `data.high[-lookback]`：平台窗口内最早一天

本策略的平台和均量都从 `-1` 开始取值，确保没有前视偏差。

#### 参数调优方向

| 目标 | 推荐调整 |
|------|----------|
| 信号太少 | 提高 `max_range_pct`，降低 `volume_multiplier`，降低 `breakout_pct` |
| 假突破太多 | 提高 `volume_multiplier`，提高 `min_upper_touches`，提高 `breakout_pct` |
| 买点太滞后 | 降低 `breakout_pct`，或缩短 `lookback` |
| 平台太松散 | 降低 `max_range_pct` |
| 回踩平台就被过早卖出 | 提高 `platform_sell_tolerance` |
| 平台跌破后卖出太慢 | 降低 `platform_sell_tolerance` |
| 固定止损太宽 | 降低 `stop_loss_pct` |
| 固定止损太容易触发 | 提高 `stop_loss_pct` |

---

### `cli/stats_cli.py` — 数据统计命令

**实现思路**：

注册 `stats` 命令组，包含两个子命令：
- `stats analyze --strategy <name>` — 加载 `_summary_*.csv` 汇总数据，生成单策略全市场画像 HTML 报告
- `stats compare` — 加载所有可用策略的汇总数据，生成多策略横向对比 HTML 报告

数据来源于 `output/trades/_summary_{strategy}.csv`（批量回测时自动生成），无需重新运行回测。报告输出到 `output/statistics/` 目录。

**分析指标计算**（见 `analysis/analyzer.py`）：
- 收益率分布（histogram binning）
- 风险收益散点数据（return vs max_dd）
- TOP/BOTTOM 排行
- 多策略雷达图归一化（Min-Max 归一化到 0-100，回撤维度反转）
- Spearman 秩相关系数矩阵（基于同股票跨策略收益率）

#### 策略画像统计卡片字段

策略画像页面由 `analysis/report.py::build_analyze_page()` 生成，卡片数据来自 `analysis/analyzer.py::compute_stats()`。`compute_stats()` 的输入是批量回测生成的 `output/trades/_summary_{strategy}.csv`。

单只股票回测的核心字段由 `engine/runner.py::BacktestRunner._build_stats()` 生成：

| CSV 字段 | 单股含义 | 计算来源 |
|----------|----------|----------|
| `initial_cash` | 初始资金 | `config.yaml` 中 `backtest.initial_cash` |
| `final_value` | 回测结束后的账户权益 | `cerebro.broker.getvalue()` |
| `total_return_pct` | 单股总收益率 | `(final_value - initial_cash) / initial_cash * 100` |
| `annual_return_pct` | 单股年化收益率 | `(final_value / initial_cash) ** (252 / trading_days) - 1`，再乘以 100 |
| `annual_volatility_pct` | 单股年化波动率 | `equity.pct_change().std() * sqrt(252) * 100` |
| `calmar_ratio` | 单股 Calmar 比率 | `annual_return_pct / max_drawdown_pct` |
| `sortino_ratio` | 单股 Sortino 比率 | 日权益收益均值 / 下行收益标准差 × `sqrt(252)`；下行波动不足时为 0 |
| `profit_factor` | Profit Factor | 平仓盈利总额 / 平仓亏损绝对值；无亏损且有盈利时留空，避免写入无限值 |
| `gross_profit` / `gross_loss` | 平仓盈利/亏损总额 | 来自策略交易流水中 SELL 记录的 `pnl` |
| `avg_trade_pnl` | 平均平仓盈亏 | SELL 记录 `pnl` 的均值 |
| `best_trade_pnl` / `worst_trade_pnl` | 单笔最佳/最差平仓盈亏 | SELL 记录 `pnl` 的最大/最小值 |
| `longest_win_streak` / `longest_loss_streak` | 最长连续盈利/亏损次数 | 按 SELL 记录 `pnl` 顺序统计 |
| `avg_exposure_pct` | 平均持仓暴露 | `EquityCurveAnalyzer` 逐 bar 记录的持仓市值 / 权益 |
| `total_trades` | 单股完整交易次数 | Backtrader `TradeAnalyzer` 的盈利交易数 + 亏损交易数 |
| `win_trades` | 盈利交易次数 | Backtrader `TradeAnalyzer` |
| `lose_trades` | 亏损交易次数 | Backtrader `TradeAnalyzer` |
| `win_rate_pct` | 单股胜率 | `win_trades / total_trades * 100`；无交易时为 0 |
| `sharpe_ratio` | 单股夏普比率 | Backtrader `SharpeRatio` 分析器，`riskfreerate=0.03` |
| `max_drawdown_pct` | 单股最大回撤 | Backtrader `DrawDown` 分析器 |
| `max_drawdown_days` | 最大回撤持续长度 | Backtrader `DrawDown` 分析器 |
| `start_date` / `end_date` | 回测起止日期 | K 线数据的最小/最大日期 |
| `trading_days` | 权益曲线交易日数 | `EquityCurveAnalyzer` 记录的 bar 数 |
| `benchmark_return_pct` | 基准同期收益率 | 基准指数缓存存在时计算，例如 `000300.SH` |
| `excess_return_pct` | 超额收益率 | `total_return_pct - benchmark_return_pct` |
| `information_ratio` | 信息比率 | 主动收益均值 / 主动收益标准差 × `sqrt(252)` |

策略画像卡片字段在全市场维度上进一步聚合：

| 卡片文案 | `compute_stats()` 字段 | 计算方式 |
|----------|------------------------|----------|
| 分析股票数 | `count` | `len(df)`，即 summary CSV 行数 |
| 有交易股票 | `active_count` / `active_ratio` | `total_trades > 0` 的行数；占比 = `active_count / count * 100` |
| 平均收益率 | `avg_return` | `mean(total_return_pct)`，包含无交易股票 |
| 平均年化收益 | `avg_annual_return` | `mean(annual_return_pct)`，包含无交易股票 |
| 交易股平均收益 | `avg_active_return` | 只对 `total_trades > 0` 的股票计算 `mean(total_return_pct)` |
| 交易股平均年化 | `avg_active_annual_return` | 只对 `total_trades > 0` 的股票计算 `mean(annual_return_pct)` |
| 平均年化波动 | `avg_annual_volatility` | `mean(annual_volatility_pct)` |
| 平均超额收益 | `avg_excess_return` | `mean(excess_return_pct)`；如果没有基准列则默认为 0 |
| 平均信息比率 | `avg_information_ratio` | `mean(information_ratio)`；如果没有基准列则默认为 0 |
| 中位数收益率 | `median_return` | `median(total_return_pct)` |
| 正收益比例 | `positive_ratio` | `count(total_return_pct > 0) / count * 100` |
| 平均夏普 | `avg_sharpe` | `mean(sharpe_ratio)` |
| 平均 Sortino | `avg_sortino` | `mean(sortino_ratio)`；旧 summary 没有该列时默认为 0 |
| 平均 Calmar | `avg_calmar` | `mean(calmar_ratio)` |
| 平均 Profit Factor | `avg_profit_factor` | `mean(profit_factor)`，自动忽略空值和无限值 |
| 平均最大回撤 | `avg_max_dd` | `mean(max_drawdown_pct)` |
| 回撤持续天数 | `avg_max_drawdown_days` | `mean(max_drawdown_days)` |
| 最长连赢/连亏 | `max_win_streak` / `max_loss_streak` | 全市场样本中 `longest_win_streak` / `longest_loss_streak` 的最大值 |
| 平均交易 PnL | `avg_trade_pnl` | `mean(avg_trade_pnl)` |
| 平均胜率 | `avg_win_rate` | `mean(win_rate_pct)` |
| 平均交易次数 | `avg_trades` | `mean(total_trades)` |

注意事项：

1. `avg_return`、`avg_annual_return`、`avg_annual_volatility` 都包含无交易股票。无交易股票的收益、年化收益和波动通常为 0，因此信号很少的策略会被 0 值明显稀释。
2. `avg_active_return` 和 `avg_active_annual_return` 排除了无交易股票，更接近“策略真正出手后的平均效果”。
3. `median_return` 用于观察典型股票表现。如果平均收益很高但中位数很低，通常说明少数大赢家拉高了均值。
4. `positive_ratio` 统计的是全部股票中的正收益比例，不只统计有交易股票。
5. `avg_win_rate` 是“先算每只股票自己的胜率，再取平均”，不是把所有交易混在一起算总体胜率。
6. `avg_excess_return` 和 `avg_information_ratio` 依赖基准指数缓存。若 `data/cache/{benchmark.symbol}.csv` 不存在，相关字段不会出现在 summary 中，统计报告会显示 0。
7. Sortino、Profit Factor、连续盈亏等字段是阶段 2 新增字段；旧的 `_summary_*.csv` 没有这些列时，统计页会保持兼容并显示 0 或跳过对应图表。重新执行批量回测后，新 summary 才会完整携带这些字段。
8. Profit Factor 使用平仓交易流水中的 `pnl`，不改变 Backtrader 成交价格、手续费、滑点、涨跌停、成交量限制或 T+1 规则。

---

### `visual/kline_chart.py` — K线 + 均线 + 指标图表组件

**核心函数**：

| 函数 | 产出 | 说明 |
|------|------|------|
| `create_kline_chart()` | K线 + MA叠加 Grid | 可选 ma5/ma10/ma20/ma60 均线叠加，含买卖点标记 |
| `create_volume_chart()` | 成交量柱状图 Grid | 红涨绿跌双 Bar 系列（stack 叠加），含 dataZoom |
| `create_macd_chart()` | MACD 指标图 | DIF/DEA 线 + 柱状图 |
| `create_kdj_chart()` | KDJ 指标图 | K/D/J 三线，0-100 定轴 |
| `create_rsi_chart()` | RSI 指标图 | RSI 线 + 30/70 超买超卖虚线参考线 |

**实现思路**：

1. K 线图使用 pyecharts 的 `Kline`，通过 `.overlap()` 叠加多条 Line（均线）
2. 成交量通过 Bar 双系列（stack 叠加）实现红涨绿跌配色
3. 各指标图（成交量/MACD/KDJ/RSI）均为独立 Grid 图表，高度 300px
4. 每个图表都包含 `DataZoomOpts(type_="inside")` 用于同步联动
5. 买卖点标记：买入红三角朝上，卖出绿三角朝下
6. 默认展示最近约 30% 的数据范围，避免数据太多时蜡烛太窄

---

### `visual/report.py` — 完整报告（自研轻量渲染器）

**实现思路**：

1. `generate_report()` 是总入口，接收 K线数据、交易记录、权益数据
2. 从 OHLC 数据计算技术指标：`_calc_ma()`（4条均线）、`_calc_macd()`（DIF/DEA/柱）、`_calc_kdj()`（K/D/J）、`_calc_rsi()`（RSI）
3. **不再使用 pyecharts**：所有图表数据序列化为紧凑 JSON，嵌入页面一次；JS 图表工厂模板（`_CHART_JS`）从共享数据创建 ECharts 实例
4. 日K/周K/月K 各 5 张图（K线 + 成交量/MACD/KDJ/RSI），再加权益曲线/Underwater 回撤、60 日 rolling Sharpe、月度收益热力图、交易 PnL 分布，共 19 张图，数据共享不发生重复
5. 报告体积从原来 pyecharts 方案的 3.2 MB 降低到 ~230 KB（**93% 缩减**）
6. `_build_page()` 拼装完整 HTML，包含：
   - **周期标签栏**（日K | 周K | 月K）
   - **指标标签页**（成交量/MACD/KDJ/RSI 切换，作用域在当期周期 section 内）
   - **ECharts 联动**：所有图表通过 `echarts.connect('qg')` 同步 dataZoom
   - 标签切换时 80ms 延迟 resize 目标区域内的图表

**报告包含的图表板块**：
1. K线图（含 MA5/MA10/MA20/MA60 + 买卖点标记），高度 500px
2. 联动指标区（标签页切换，与 K线图缩放同步）：
   - 成交量（红涨绿跌柱状图），300px
   - MACD（DIF/DEA + 柱状图），350px
   - KDJ（K/D/J 三线，自动缩放），350px
   - RSI（RSI线 + 30/70 参考线），300px
3. 权益曲线 + Underwater 回撤，520px
4. 60 日 rolling Sharpe，350px
5. 月度收益热力图，350px
6. 交易 PnL 分布，350px

---

### `analysis/` — 全市场统计分析模块

基于批量回测汇总数据（`_summary_*.csv`）生成亮色主题 HTML 分析报告。模块结构：

| 文件 | 职责 |
|------|------|
| `analyzer.py` | 数据加载（`load_summary()`、`load_all_summaries()`）、分布统计（`compute_stats()`）、直方图分箱（`build_return_histogram()`）、雷达图归一化（`normalize_for_radar()`）、策略相关性矩阵（`compute_correlation_matrix()`） |
| `charts.py` | 亮色主题 pyecharts 图表组件：收益率/夏普/交易次数/Profit Factor/回撤持续时间/平均交易 PnL 直方图、风险收益散点图、Monte Carlo 路径、雷达图、箱线图、柱状图、相关性图、策略叠加散点图 |
| `report.py` | HTML 报告组装：`build_analyze_page()`（单策略画像）、`build_compare_page()`（多策略对比）。生成响应式卡片布局 + 图表嵌入页面 |

**亮色主题常量**（独立于 `visual/kline_chart.py` 的暗色主题）：`_BG_COLOR = "white"`、`_TITLE_COLOR = "#1a1a2e"`、`_UP_COLOR = "#ef5350"`（红涨）、`_DOWN_COLOR = "#26a69a"`（绿跌）。

---

## 配置文件说明

```yaml
tushare:
  token: "你的token"          # Tushare API 密钥

data:
  cache_dir: "data/cache"     # 数据缓存目录

backtest:
  initial_cash: 100000.0      # 初始资金（元）
  commission: 0.00025         # 佣金费率 0.025%
  stamp_duty: 0.001           # 印花税 0.1%（仅卖出）
  min_commission: 5.0         # 最低佣金 5 元

rate_limit:
  sleep_seconds: 1.5          # API 调用间隔（防止限流）

output:
  trades_dir: "output/trades"     # 交易流水输出目录
  reports_dir: "output/reports"   # 报告输出目录
  signals_dir: "output/signals"   # 买点扫描汇总输出目录
  statistics_dir: "output/statistics" # 策略画像和对比报告目录
  decisions_dir: "output/decisions"   # 决策记忆复盘表目录
  experiments_dir: "output/experiments" # 实验归档目录，供 dashboard 展示最近实验入口

decision_memory:
  enabled: true                    # 导出买点时同步写入 decision memory
  horizons: [5, 10, 20]            # 默认复盘窗口，单位为实际交易日

defaults:
  start_date: "20210101"          # 默认起始日期

watchlist:                    # 默认关注的股票列表（供快速下载参考）
  - "000001.SZ"   # 平安银行
  - "000002.SZ"   # 万科 A
  - "600519.SH"   # 贵州茅台
```

## 关键设计决策

### 为什么用 backtrader？

backtrader 是 Python 生态中最成熟的回测框架之一，提供完整的事件驱动回测引擎、内置常用技术指标和分析器。相比于自己从零实现回测循环，使用 backtrader 可以避免处理除权除息、资金管理、手续费计算等边界情况。

### 为什么 CSV 而不是数据库？

个人量化场景下数据量不大（每只股票每天一条记录），CSV 的优势是：
- 零安装成本，不需要额外配置数据库
- 可以直接用 Excel 打开查看
- 方便版本管理（Git 可 diff CSV）

### 策略加载为什么用约定而非注册？

`load_strategy_class()` 通过命名约定自动查找策略类，省去了手动注册的步骤。用户只需按规范命名文件（`snake_case`）和类（`PascalCase + Strategy`），系统就能自动发现。

### 为什么使用命令 REPL 而非逐级菜单？

命令式交互允许用户一次输入完成完整操作（如 `download --symbol 000001.SZ --force`），而菜单模式需要多次输入。命令模式还支持参数组合、简写别名，更符合开发者使用习惯，且方便脚本化。
