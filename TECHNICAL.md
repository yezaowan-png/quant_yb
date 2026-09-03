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

配置加载统一由 `project_config.py` 提供：默认解析项目根目录 `config.yaml`，也支持通过 `QUANTYB_CONFIG` 指向另一份配置。`cli.common`、数据下载器、分析器和维护脚本保留原有兼容函数，但不再各自实现 YAML 路径规则。

## 整体架构

```
┌──────────────────────────────────────────────┐
│                    main.py                    │
│              (Click CLI Group)                │
│    注册 data / backtest / stats / index       │
│    / dashboard 命令                           │
│    无子命令时 → 进入交互式命令 REPL           │
└──────┬──────────┬──────────┬──────────┬────────┘
       │          │          │          │
 ┌─────▼─────┐ ┌──▼───────┐ ┌▼────────┐ ┌▼────────────┐
 │ data_cli  │ │backtest  │ │stats_cli│ │index/dashboard│
 │ 股票下载  │ │回测/扫描 │ │统计报告 │ │指数概览/面板 │
 └─────┬─────┘ └──┬───────┘ └────┬────┘ └──────┬──────┘
       │          │              │             │
 ┌─────▼──────────▼───┐    ┌─────▼─────┐ ┌────▼────────┐
 │ data/downloader    │    │analysis/  │ │visual/      │
 │ 下载编排兼容入口   │    │统计与指数 │ │HTML 报告    │
 │ 委托 client/store  │    │指标计算   │ │dashboard    │
 └─────┬──────────────┘    └───────────┘ └────┬────────┘
       │                                      │
 ┌─────▼────────┐   ┌──────────────────┐ ┌───▼────────┐
 │ data/cache/  │   │ engine/runner    │ │ output/    │
 │ 或外部磁盘缓存│   │ Backtrader 回测  │ │ 或外部磁盘产物│
 └──────────────┘   └──────────────────┘ └────────────┘
```

### 数据流

```
Tushare API (stock_basic)
    │ 获取全A股列表，剔除ST
    ▼
DataDownloader.download_batch()
    │ 股票调用 Tushare daily + adj_factor，普通指数调用 index_daily，`.TI` 指数调用 ths_daily，清洗数据
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
Tushare index_daily / ths_daily（`.TI`）
    │
    ▼
DataDownloader.download_index()
    │ 清洗字段：date/open/high/low/close/pre_close/change/pct_chg/volume/amount
    ▼
data/cache/index/{symbol}.csv
    │
    ├─ analysis/index_overview.py 生成趋势、动量、震荡和风险概览
    ├─ analysis/market_breadth.py 从本地股票缓存统计每日上涨/下跌/平盘家数、A/D 和 NH-NL
    ├─ analysis/index_market.py 生成多指数大盘环境评分和横向比较
    │
    ▼
visual/index_report.py
    │ 生成日K/周K/月K + MACD/KDJ/RSI HTML
    ▼
output/reports/index/{symbol}_overview.html
output/reports/market_overview.html
```

CLI 入口为 `python main.py index download/report/overview/ths/market`，单指数使用 `--symbol`，第一阶段批量生成使用 `--all`。`overview` 会先调用 `download_index()` 更新缓存，再调用 `generate_index_report()` 生成 HTML；`--all` 会按配置顺序逐个处理 `000001.SH`、`399001.SZ`、`399006.SZ`、`000688.SH`、`000300.SH`、`000905.SH`、`000852.SH`、`000985.SH` 和 `AVG_PRICE.LOCAL`。其中 `AVG_PRICE.LOCAL` 是同花顺平均股价指数代理，由本地股票 K 线缓存等权平均生成；`.TI` 使用 Tushare `ths_daily`，其他指数使用 `index_daily`。`index ths` 会先缓存 Tushare `ths_index` 指数列表到 `data.meta_dir/ths_indices.csv`，再按 `config.yaml::ths_indices` 下载同花顺行业指数、风格代理指数和额外指数到 `data.cache_dir/index/`，供市场结构报告的“市场风格”和“行业强弱榜”优先使用；缓存缺失或行业指数数量不足时，报告回退到本地股票篮子口径。该链路不读取交易流水、不生成权益曲线，也不改变现有回测 CSV 字段。

`python main.py index members --all` 会调用 Tushare `index_weight` 下载默认分层广度所需指数成分，保存到 `data.meta_dir/index_members/{index_code}.csv`。当前默认包括沪深300、中证1000和中证2000；创业板广度第一版使用 `stocks.csv` 中 `market=创业板` 的全板块股票，因此默认不会下载创业板指成分。如需额外缓存创业板指成分，可执行 `python main.py index members --all --include-chinext-index`。

`python main.py index market` 会更新配置中的指数并生成 `output/reports/market_overview.html`。该看板横向比较配置指数的近 5/20/60 日表现、年初至今、20 日回撤、20 日波动率、MA20/MA60/MA120 状态、相对强弱分和趋势分。若本地股票 K 线缓存存在，则同时统计最新交易日上涨、下跌、平盘家数；A/D、A/D线、标准化A/D线、NH-NL 和 NH-NL 5 日加总以“上证广度指标”副图呈现，不放在顶部卡片里。标准化 A/D 使用 `(上涨家数 - 下跌家数) / (上涨家数 + 下跌家数)`，用于减少长期股票数量变化造成的尺度漂移。若指数成分缓存存在，A/D 副图会额外展示沪深300、中证1000、中证2000、创业板等分层标准化 A/D 线；图上默认使用起点归零后的累计线，方便观察斜率变化。

`python main.py index forecast --symbol 000001.SH --horizon 5` 会生成市场环境预测报告，支持未来 1/5/10/20 个交易日。主标签不再由单一指数未来收益决定，而是读取 `data.cache_dir/*.csv`，计算有效股票池的未来等权收益、个股收益中位数、上涨比例、标准化 A/D 累计、Q10 尾部收益、个股最大回撤中位数、波动率和大跌股票比例，再用只包含当时已完成样本的滚动分位数生成机会分、风险分和 `positive/neutral/conservative` 环境标签。指数未来收益权重为 0%，只作辅助诊断；风险分具有否决权。
该链路先生成只含当日已知特征的 `indicators_{symbol}.csv`，再追加四个周期未来横截面结果和标签生成 `features_{symbol}.csv`，最后输出 `predictions_{symbol}_h{horizon}.csv` 和 HTML。报告按预测环境统计个股中位收益、等权收益、上涨比例、尾部亏损及标签命中；若已有策略权益 CSV，还会比较环境过滤前后的策略收益、胜率、最大回撤和盈亏比。详细口径见 `docs/reference/index_forecast_report.md`。

`python main.py index forecast-diagnose` 还会运行不影响正式信号的 P0/P1 研究链路。该链路使用两个独立的 NumPy L2 逻辑回归预测机会和尾部风险，按“扩展训练→purge→验证→embargo→测试”生成时间外概率；缺失值、Winsorize、标准化、特征组、L2、Platt 校准和二维政策阈值都在测试前冻结。诊断输出逐折基线、系数、消融、标签/年度/波动状态稳定性、区块 Bootstrap、策略 A-E 对照和数值门槛审计。门槛未通过时 `gate_audit.csv` 明确阻止进入非线性模型或替换正式环境规则。

`python main.py market risk-state|risk-labels|risk-diagnose|risk-matrix|risk-report` 是独立的 `market_risk_gate` 研究链路。`analysis/market_risk_data.py` 只读加载本地个股收盘矩阵和已有策略权益；`analysis/market_risk_features.py` 只构造 T 日可知的 10 个基础特征和一个预声明交互项；`analysis/market_risk_labels.py` 构造未来路径结果，并在每个训练折内冻结 R1-R5 阈值；`analysis/market_risk_model.py` 只运行冻结单变量基线和 NumPy L2 逻辑回归；`analysis/market_risk_diagnostics.py` 负责严格 walk-forward、稳定性、A-E 策略对照和自动停止门槛；`analysis/market_risk_state.py` 与 `analysis/market_risk_policy.py` 单独输出当前压力状态和带 hysteresis 的模拟政策。该链路不调用或覆盖 `analysis/market_environment_labels.py`、`analysis/index_forecast.py`、正式策略信号和仓位逻辑。详细口径见 `docs/reference/market_risk_gate.md`。

上证指数单页 `output/reports/index/000001.SH_overview.html` 的日 K 指标区会额外展示 A/D 和 NH-NL 两个副图，其中 A/D 副图同时包含原始 A/D 线和标准化 A/D 线。其他指数单页保留原有 K 线、成交量、MACD、KDJ、RSI 和 tooltip 涨跌家数，不增加 A/D/NH-NL 副图。

指数单页报告的日 K tooltip 会读取同一份本地涨跌家数统计，在鼠标悬停某根 K 线时显示该日期的上涨、下跌和平盘股票数量。该统计来自 `data.cache_dir/*.csv`，不额外请求 Tushare。

### 汇总面板链路

`python main.py dashboard` 会调用 `visual/dashboard.py::generate_dashboard()`，扫描本地输出目录并生成 `output/reports/dashboard.html`。页面采用工作台式布局：左侧为市场/信号/指数/题材/策略/报告索引，主区域按市场状态、信号流、指数导航、题材看板、策略汇总和最近单标的报告组织：

- 指数导航：读取 `config.yaml::index_overview.indexes`、`data/cache/index/{symbol}.csv` 和 `output/reports/index/{symbol}_overview.html`
- 大盘环境：读取 `output/reports/market_overview.html`，生成后在顶部入口和市场状态区展示
- 策略汇总：读取 `output/trades/_summary_{strategy}.csv`，复用 `analysis/analyzer.py::compute_stats()` 计算核心卡片
- 策略报告：链接到 `output/statistics/analysis_{strategy}.html` 和 `output/statistics/comparison.html`
- 题材看板：读取 `output/statistics/theme_*_summary.csv` 作为摘要索引，并链接到同名 `theme_*.html`
- 信号中心：读取最近的 `rps_top_*.csv`、`pattern_signals_*.csv`、`limit_board_*.csv` 和 `rotation_*_nav.csv`，组合成信号流，并展示 RPS、形态扫描、涨跌停和轮动研究入口
- 单标的报告：扫描 `output/reports/*.html`，展示最近生成的报告入口

该面板只聚合已有输出，不重新下载数据、不运行回测、不改变任何 CSV 口径。

### 报告组件

报告层第一轮公共组件抽取已经完成，后续除非有明确维护瓶颈，不继续做大规模拆分：

- `visual/components.py`：提供 HTML 文档外壳、脚本标签、ECharts 引入 helper 和报告 JSON 序列化 helper。
- `visual/index_report.py` 已使用公共组件生成指数概览 HTML。
- `visual/dashboard.py` 已使用公共组件生成总控面板 HTML 外壳和 JSON 数据脚本。
- `analysis/theme_report.py` 已使用公共组件生成题材看板 HTML 外壳、ECharts 脚本标签和 JSON 数据脚本。
- `analysis/report.py` 已使用公共组件生成统计分析和策略对比报告 HTML 外壳。
- `visual/report.py` 已使用公共组件生成单标的回测报告 HTML 外壳。
- `visual/stock_report_data.py` 已承接单标的报告日/周/月周期 payload、权益曲线 payload、多周期量价趋势诊断 payload、共享指标计算、OHLC 重采样和周线 EMA 诊断 payload。
- `visual/index_report.py` 已复用 `visual.stock_report_data` 的指标计算和 OHLC 重采样 helper。
- 单标的回测报告仍保留自己的多周期策略诊断 HTML；为保持输出稳定，剩余 HTML 组装拆分暂缓。

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
2. **命令路由**：交互模式和流水线统一调用 `_dispatch_command()`，再根据第一个词路由到对应处理函数；支持简写（如 `dl` → download、`bt` → backtest、`rp` → report）。
3. **异常保护**：每个命令用 `try/except` 包裹，出错时打印错误信息但不退出程序。
4. **公共能力**：配置加载、缓存读取、策略发现和交易流水识别统一放在 `cli/common.py`，Click CLI 与 REPL 共用。数据下载、指数、统计、回测报告和 dashboard 由各自 CLI 模块暴露公共服务函数，避免两套实现漂移。
5. **命令流水线**：`_execute_pipeline()` 接受分号或换行分隔的命令字符串，按序逐条执行。遇到错误时默认中止，可用 `!` 前缀忽略某条失败继续。`_cmd_run()` 在交互式 Shell 中暴露该能力（支持字符串参数和 `--file` 脚本文件）。CLI 中对应的 `run` 命令注册在 `main.py`。

**为什么从菜单改为命令 REPL？**
菜单模式需要一级一级输入，操作效率低，且无法组合参数。命令模式一次输入就能完成操作（如 `download --symbol 000001.SZ --start 20110101 --force`），更符合程序员使用习惯，也方便脚本化。

---

### `cli/data_cli.py` — 数据下载命令

**实现思路**：

- 未指定 `--symbol` 时，自动调用 `DataDownloader.get_stock_list()` 获取全A股列表（剔除ST股票）
- `--start` 和 `--end` 分别默认为 `20110101` 和当天日期
- 下载全部股票时会弹出确认提示，防止误操作

---

### `cli/backtest_cli.py` — 回测、扫描与报告命令

**实现思路**：

1. **`backtest run`**：
   - 股票选择优先级：`--symbols`（逗号分隔多只） > `--symbol`（单只） > `--pool`（JSON 题材股票池） > 所有已缓存股票
   - `--pool` 从 `config.yaml::stock_pool.path` 指向的 JSON 读取题材股票池，`--pool-mode any/all` 分别表示多个题材取并集/交集。题材 JSON 推荐使用 `{"pools": {"题材": {"stocks": [{"ts_code": "...", "name": "..."}]}}}`，解析器也兼容旧的纯代码数组格式。
   - 单只股票回测时，直接输出绩效摘要到命令行
   - 多只股票回测时，调用 `run_batch()` 静默执行，最后导出汇总 CSV，同时自动扫描近5日买点
2. **`backtest scan`**：
   - 新增命令，对所有已缓存股票运行策略，检测近N日买点
   - 结果导出到 `output/signals/buy_signals_{策略名}_{日期}.csv`
3. **`backtest report`**：
   - 自动查找对应的交易流水文件和权益文件
   - 如果文件不存在给出明确提示（比如"请先执行 backtest run"）
4. **批量报告并行**：`_run_batch_reports()` 使用 `ThreadPoolExecutor`（而非 `ProcessPoolExecutor`）并行生成 HTML 报告。线程池避免 Windows 上多进程 spawn 导致的 OpenBLAS 内存耗尽和进程挂起问题。模块顶部在 import pandas 之前设置 `OPENBLAS_NUM_THREADS=1` 等环境变量，防止子线程中 OpenBLAS 多线程竞争。

---

### `data/downloader.py` — 数据下载器

**核心类**：`DataDownloader`

`DataDownloader` 仍是 CLI 和其它模块使用的数据下载入口。为降低单文件复杂度，内部已经完成第一轮拆分；后续继续拆分暂缓，优先保持下载行为稳定：

- `data/tushare_client.py::TushareClient`：负责 Tushare token 去重、token 轮换、每个 token 的限流、频率超限退避重试和取消检查。
- `data/cache_store.py::CsvCacheStore`：负责股票/指数 K 线缓存路径和读写、`daily_basic` 拆分追加、`kline_checked_dates.csv` 记录和失败目录路径。
- `data/adjustment.py`：负责逐标的 `daily + adj_factor` 的 qfq/hfq 价格调整，以及重叠日期价格不一致检测。
- `data/download_failures.py`：负责失败股票文件读取和失败快照 CSV 写入。
- `data/download_planner.py`：负责批量下载前的缓存命中、预计接口次数和预计耗时计算。
- `data/download_retry.py`：负责失败股票是否可重试的判断，以及补下载命令文本生成。
- `data/download_service.py`：负责下载工作流前置编排 helper，当前已承接失败文件/显式股票/全市场股票列表的标的解析、批量下载计划文案格式化，以及单轮并发下载执行 helper。
- `data/metadata.py`：负责股票基础信息、名称映射和 `daily_basic` 日指标数据的清洗辅助。
- `data/price_cleaning.py`：负责股票/指数日线字段映射、日期转换、数值化和排序清洗。
- `DataDownloader` 继续负责编排下载流程、增量判断、前复权清洗、失败补下载和对外兼容方法。失败快照、自动补下载和最终提示仍保留在该类中，避免改变现有命令体验。

**设计要点**：

1. **股票列表获取**：`get_stock_list()` 方法调用 `pro.stock_basic(exchange='', list_status='L')` 获取全市场上市股票，自动过滤名称含 "ST" 的股票。返回包含 `ts_code` 和 `name` 的字典列表。

2. **股票基础信息与名称映射**：`download_stock_basic()` 调用 Tushare `stock_basic` 保存完整基础信息到 `data.meta_dir/stocks.csv`，并额外保存 `data.meta_dir/stock_names.csv` 作为 `ts_code -> name` 映射表，供题材池展示和后续分析 join 使用。

3. **每日指标跟踪**：`download_daily_basic()` 先通过交易日历得到交易日列表，再按交易日调用 Tushare `daily_basic(trade_date=...)` 获取全市场指标，并拆分追加到 `data.meta_dir/daily_basic/{ts_code}.csv`，即每只股票一个指标文件。该表保留换手率、量比、估值、市值等字段，后续可和题材股票池 JSON 聚合，比较近 1 周、1 个月等周期内不同题材的指标变化。

4. **默认日期范围**：`default_start()` 从 `config.yaml` 的 `defaults.start_date` 读取默认起始日期（当前为 `20110101`），`today_str()` 返回当天日期作为默认结束日期。

5. **增量更新**：`_save_cache()` 方法在保存时先读取已有缓存，与新数据 `pd.concat` 后再去重排序。这样多次下载同一只股票的不同时间段，数据会自动合并。

6. **缓存命中与增量更新**：`download()` 方法先检查缓存的时间范围是否覆盖请求区间；股票缓存还会检查 `adj` 复权口径是否匹配 `config.yaml::data.stock_adj`，旧的未复权缓存会被视为不匹配并重新下载。若全市场已有缓存且只是向后补最新交易日，`download_batch()` 会提示用户选择按交易日增量下载或重新全量下载。选择增量时，一次调用 `daily(trade_date=...)` 拉全市场 K 线，一次调用 `adj_factor(trade_date=...)` 拉全市场复权因子，然后按 `ts_code` 拆分追加到各股票 CSV。首次建库、补历史头部、强制刷新、指数数据仍走逐标的逻辑；若检测到某只股票复权因子变化，则对该股票从本地缓存起点到本次结束日期做逐标的刷新。
   - 增量路径会维护 `data.meta_dir/kline_checked_dates.csv`，记录已按全市场日截面检查过的交易日。下次即使少数停牌或无数据股票文件尾部日期较早，也会跳过这些已检查日期，避免重复请求。

7. **API 容错与失败汇总**：如果 Tushare API 调用失败，只有本地缓存完整覆盖请求日期区间时才会回退到缓存；否则该股票会计入批量下载失败列表。批量下载结束后会打印失败股票列表，并给出一条带 `--symbol`、`--start`、`--end` 的增量补下载命令，方便直接重试失败标的。

8. **限流保护**：`download_batch()` 通过 `TushareClient` 按 `config.yaml::rate_limit.calls_per_minute` 控制 Tushare API 调用频率；多 token 配置时每个 token 独立限流，并用 `parallel.download_workers` 控制并发下载线程数，避免触发频率限制。
9. **失败记录与增量补下载**：批量下载会通过 `data/download_failures.py` 把第一轮失败和每轮补下载后剩余失败写入 `output.failed_downloads_dir`，文件名形如 `download_failures_{run_id}_{stage}.csv`。失败是否适合自动补下载、补下载命令文本由 `data/download_retry.py` 生成。CLI 支持 `python main.py data download --failed-file <csv>` 只补下载失败文件中的 `symbol`。

10. **数据清洗**：`_clean()` 方法把 Tushare 返回的字段名映射为标准英文名（如 `trade_date` → `date`），统一数据类型，删除空值行。

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

### 8. 多周期量价趋势策略 (multi_timeframe_volume_trend) — `strategy/multi_timeframe_volume_trend.py`

**核心思想**：用已完成周线特征过滤大方向，等待日线趋势内回调，再通过突破历史高点和量价确认触发买入。当前实现只使用日 K 成交和回测，不引入小时线 feed，不新增交易流水字段。

**参数**：
- `trend_filter_mode=weekly`：默认使用已完成周线特征；可设为 `daily_proxy` 回退到阶段 1 的日线扩周期代理
- `weekly_fast_ema=13` / `weekly_slow_ema=26`：周线 EMA 周期
- `weekly_macd_fast=12` / `weekly_macd_slow=26` / `weekly_macd_signal=9`：周线 MACD 参数
- `daily_ema_period=50`：日线回调 EMA 周期
- `rsi_period=14` / `pullback_lookback=20` / `pullback_pct=0.02` / `pullback_rsi=40.0`：回调识别参数
- `pullback_valid_days=10`：回调信号有效期
- `breakout_lookback=3`：突破高点窗口
- `vol_ma_period=20` / `volume_mult=1.5`：相对成交量确认
- `vpt_ma_period=20` / `obv_ma_period=20`：VPT/OBV 均线周期
- `min_volume_confirmations=2`：最少量价确认数量
- `atr_period=14` / `atr_mult=2.0` / `trail_atr_mult=2.5`：ATR 初始止损和跟踪止损
- `trend_exit_confirm_days=2`：趋势失效确认天数
- `use_post_accel_platform_filter=true`：启用加速上涨后平台震荡禁买过滤
- `accel_lookback=10` / `accel_scan_days=60` / `accel_return_pct=0.30`：加速上涨滚动扫描参数
- `post_accel_pullback_pct=0.08` / `platform_lookback=20` / `platform_max_range_pct=0.10` / `platform_ma_slope_pct=0.03`：回落平台识别参数
- `platform_breakout_pct=0.01` / `platform_breakout_volume_mult=1.5`：解除平台过滤的带量突破参数
- `use_stalling_buy_filter=true` / `stalling_buy_filter_days=5`：过滤买入前 5 个已知交易日内出现放量滞涨的信号
- `use_stalling_ma_exit=true` / `use_entry_day_stalling_exit=true`：启用“放量滞涨后跌破短均线”清仓，以及买入成交当天放量滞涨时下一根 K 线开盘退出
- `stalling_volume_mult=1.3` / `stalling_max_close_gain_pct=0.005` / `stalling_exit_ma_period=5`：普通放量滞涨和清仓均线参数
- `stalling_prev_gain_min_pct=0.05` / `stalling_gain_fade_pct=0.025` / `stalling_upper_shadow_pct=0.04` / `stalling_close_position_max=0.60`：前一日大涨后冲高回落型放量滞涨参数
- `use_take_profit=false` / `take_profit_r=3.0`：可选固定 R 倍数止盈
- `use_volume_exhaust_exit=false`：可选量价衰竭退出

#### 严格周线过滤

`engine/runner.py::_add_completed_weekly_features()` 会在数据进入 Backtrader 前，从日 K 重采样出周线收盘价并计算周线 EMA/MACD：

```text
weekly_close = resample("W-FRI").last(close)
weekly_ema_fast = EMA(weekly_close, weekly_fast_ema)
weekly_ema_slow = EMA(weekly_close, weekly_slow_ema)
weekly_macd_hist = MACD(weekly_close, weekly_macd_fast, weekly_macd_slow, weekly_macd_signal)
```

这些特征通过 `merge_asof(direction="backward")` 贴回每天的日线 bar，只允许当前日读取日期不晚于当前日的已完成周线特征。周一到周四通常读取上一根已完成周线；周五收盘后可以读取本周已完成周线。

多头趋势成立：

```text
close > weekly_ema_slow
weekly_ema_fast > weekly_ema_slow
weekly_macd_hist > 0
```

`trend_filter_mode=daily_proxy` 仍保留为对照模式，使用阶段 1 的日线扩周期近似：

$$TrendEMAFast = EMA(close, weekly\_fast\_ema \times 5)$$

$$TrendEMASlow = EMA(close, weekly\_slow\_ema \times 5)$$

$$TrendMACDHist = MACD(close, 12 \times 5, 26 \times 5, 9 \times 5)$$


#### 回调与突破

回调高点和突破高点都排除今天，只读取历史 bar：

```text
RecentHigh = max(high[-1], ..., high[-pullback_lookback])
BreakoutHigh = max(high[-1], ..., high[-breakout_lookback])
```

回调条件三选一：

```text
close < EMA(close, daily_ema_period)
or (RecentHigh - close) / RecentHigh >= pullback_pct
or RSI <= pullback_rsi
```

买入要求最近 `pullback_valid_days` 日内出现过回调，且今天收盘价突破 `BreakoutHigh`。

买入前过滤：

```text
not post_acceleration_platform_filter
and
not any(volume_stalling over last stalling_buy_filter_days known daily bars)
```

加速上涨后平台过滤的状态机：

```text
recent_acceleration =
    any(
        close[end] / close[end - accel_lookback] - 1 >= accel_return_pct
        for end in last accel_scan_days known daily bars
    )

if recent_acceleration:
    filter_active = true

platform =
    range(high/low over platform_lookback) <= platform_max_range_pct
    and abs(MA20_now / MA20_5_days_ago - 1) <= platform_ma_slope_pct
    and pullback_from_recent_peak >= post_accel_pullback_pct

if filter_active and platform:
    platform_seen = true

解除过滤 =
    platform_seen
    and close > platform_high[-platform_lookback:-1] * (1 + platform_breakout_pct)
    and volume / SMA(volume, vol_ma_period)[t-1] >= platform_breakout_volume_mult
```

这里的 `recent_acceleration` 不是只看当前日，而是向前扫描。例如当前是 8 号，如果 4 号往前 10 个交易日累计涨幅超过阈值，也会认为近期发生过加速上涨。

默认 `stalling_buy_filter_days=5`。由于买入信号在日线收盘后产生、下一根 bar 成交，这里的“已知日线 bar”包含信号日自身和之前交易日，不读取未来数据。

放量滞涨定义保留原先的“小涨/阴线放量”，并新增冲高回落场景：前一日涨幅达到 `stalling_prev_gain_min_pct`，当日仍上涨但涨幅较前一日衰减至少 `stalling_gain_fade_pct`，同时上影线达到 `stalling_upper_shadow_pct` 且收盘位置不高于当日振幅的 `stalling_close_position_max`。这用于覆盖放量明显、但攻击效率明显下降的长上影 K 线。

#### 量价确认

买入时至少满足以下条件中的 `min_volume_confirmations` 项：

```text
volume / SMA(volume, vol_ma_period)[t-1] >= volume_mult
VPT > SMA(VPT, vpt_ma_period)
OBV > SMA(OBV, obv_ma_period)
close > close[-1]
```

其中均量使用昨天及以前的数据；VPT/OBV 是随 bar 推进的内部状态，不读取未来数据。

#### 卖出规则

- 收盘价跌破基于真实成交价计算的 ATR 初始止损
- 或收盘价跌破最高收盘价以来的 ATR 跟踪止损
- 或买入成交当天出现放量滞涨，下一根 K 线开盘退出
- 或持仓期间出现放量滞涨后，后续收盘价跌破 `stalling_exit_ma_period` 日均线
- 或周线趋势过滤连续 `trend_exit_confirm_days` 日失效
- 可选固定 R 倍数止盈
- 可选量价衰竭退出

#### 实现细节

**文件**：`strategy/multi_timeframe_volume_trend.py`
**类名**：`MultiTimeframeVolumeTrendStrategy(BaseStrategy)`

**核心状态变量**：
- `data.weekly_ema_fast` / `data.weekly_ema_slow` / `data.weekly_macd_hist`：由 runner 预先计算的已完成周线特征
- `self._vpt_value[data]` / `self._obv_value[data]`：VPT 和 OBV 累计值
- `self._vpt_history[data]` / `self._obv_history[data]`：计算均线用的历史序列
- `self._pullback_history[data]`：近 N 日是否出现回调
- `self._stalling_history[data]`：近 N 日是否出现放量滞涨，用于买入前过滤
- `self._post_accel_filter_active[data]` / `self._post_accel_platform_seen[data]`：加速上涨后平台禁买状态
- `self._entry_price[data]` / `self._initial_stop[data]`：真实成交价和初始止损
- `self._highest_close_since_entry[data]`：持仓以来最高收盘价，用于跟踪止损
- `self._entry_day_stalling_exit[data]`：买入成交当天出现放量滞涨时置为 True，下一根 K 线开盘清仓
- `self._stalling_exit_armed[data]`：持仓期间出现放量滞涨后置为 True，之后跌破短均线清仓

#### 报告标注增强

`visual/report.py` 会在 `multi_timeframe_volume_trend` 单标的报告中复算诊断序列：

- 回调发生日：日 K 图用蓝色圆点标注。
- 突破触发日：日 K 图用橙色菱形标注。
- 买入设置日：趋势、回调、突破和量价确认同时成立时，用紫色 pin 标注。
- 放量滞涨日：持仓退出规则中的放量滞涨候选，用橙色方块标注。
- EMA50(日线)：用于对照回调条件 `close < EMA50`。
- ATR 初始止损线：根据真实买入成交价和报告层复算 ATR 绘制。
- ATR 跟踪止损线：根据持仓以来最高收盘价和 ATR 绘制。
- 顶部诊断卡片显示最新一日的周线趋势、近10日回调、近5日滞涨、加速平台过滤、今日突破、量价确认数量和买入设置状态。
- 多周期量价趋势的“买入设置”标记已经扣除加速平台过滤和近 N 日放量滞涨过滤；被过滤的候选不会被标成完整买点。

该报告层诊断用于解释和复盘，不写回交易流水，也不会反向影响策略信号。

**回测可信度边界**：
- 当前周线过滤来自日 K 重采样后的已完成周线特征，不新增第二个 Backtrader 周线 feed，避免基类对周线 data 下单。
- 路线确认不引入小时线第三屏，买点为日线收盘后信号、下一 bar 由 Backtrader 成交模型处理。
- 不改变手续费、滑点、涨跌停、成交量限制、T+1 或现有 CSV 字段。

---

### `cli/stats_cli.py` — 数据统计命令

**实现思路**：

注册 `stats` 命令组，包含以下子命令：
- `stats analyze --strategy <name>` — 加载 `_summary_*.csv` 汇总数据，生成单策略全市场画像 HTML 报告
- `stats compare` — 加载所有可用策略的汇总数据，生成多策略横向对比 HTML 报告
- `stats theme --pool <题材> --start <YYYYMMDD> --end <YYYYMMDD>` — 读取题材 JSON、本地 K 线缓存和可选 daily_basic 指标，统计题材区间涨跌；同时按成员首个有效收盘价归一化并等权合成概念指数，导出摘要 CSV、个股明细 CSV、概念指数 CSV 和 HTML 专题看板
- `stats rps --window <N> --top <N>` — 基于本地 K 线缓存计算全市场或股票池 RPS Top N，输出 CSV 和 HTML
- `stats rps-track --symbol <ts_code> --window <N>` — 输出单只股票 RPS 历史轨迹
- `stats pattern --pattern main_rise_wave|bottom_pattern_break|needle_bottom_raise` — 扫描主升浪、底部突破和单针探底候选，结果写入 `output/signals/`
- `stats screen --preset trendline_pullback` — 通用选股筛选入口，第一版筛选“上升趋势线有效 + 最近回踩趋势线 + 未有效跌破”的候选，可叠加 `--pool/--pool-mode` 并可选写入股票池
- `stats rotation --model momentum|three_factor` — 用本地 K 线做动量或三因子组合轮动研究，输出净值、换仓明细和 HTML 报告
- `stats limit-board --trade-date <YYYYMMDD>` — 调用 Tushare 涨跌停榜接口生成每日涨跌停看板；`--save-pools` 会把涨停、跌停、炸板和涨停行业分类写入股票池
- `stats limit-research --months <N>` — 调用 Tushare 区间涨停榜和同花顺概念成员，按液冷温控、PCB载板、AI高速材料、存储/HBM、CPO光模块、铜缆高速连接、算力电力配套、机器人等细分主题生成股票池，并输出基本面研究 Markdown
- `stats radar --trade-date <YYYYMMDD> --top <N>` — 基于本地日 K 和股票元数据生成研究型强势股雷达、行业强度、当日 snapshot、后验审计 CSV 和 HTML 看板
- `stats pool-import/pool-export/pool-from-signals` — 负责 CSV、QTYX/通达信 `.blk` 和扫描结果到项目股票池 JSON 的流转

数据来源于 `output/trades/_summary_{strategy}.csv`（批量回测时自动生成），无需重新运行回测。报告输出到 `output/statistics/` 目录。
题材涨跌统计不依赖回测结果，也不会调用 Tushare；输出为 `output/statistics/theme_{题材}_{开始日期}_{结束日期}.csv`、`output/statistics/theme_{题材}_{开始日期}_{结束日期}_summary.csv`、`output/statistics/theme_index_{题材}_{开始日期}_{结束日期}.csv` 和同名 `.html` 看板。概念指数 CSV 包含 `open/high/low/close/volume/amount/member_count/pct_chg/ma5/ma20/ma60/volume_ma5/volume_ma20/amount_ma5/amount_ma20/advance_count/decline_count/flat_count/advance_ratio_pct/above_ma20_count/above_ma20_ratio_pct/above_ma60_count/above_ma60_ratio_pct/new_high_20_count/new_high_20_ratio_pct/new_low_20_count/new_low_20_ratio_pct/member_return_std_pct`。个股明细 CSV 额外包含 `annualized_volatility_pct/return_drawdown_ratio/latest_close_vs_ma20_pct/latest_close_vs_ma60_pct/latest_volume_ratio_20/latest_high20_distance_pct/latest_low20_distance_pct` 等本地 K 线派生指标。概念指数按股票缓存完整区间合成，摘要指标和个股区间表现仍按命令里的 `--start/--end` 统计；HTML 看板展示可切换日线/周线/月线的概念 K 线，成交量/成交金额/涨跌家数/趋势广度标签切换，涨幅前 7 / 跌幅后 5 个股排行、收益回撤分布、趋势强弱和明细表。

RPS、形态扫描、通用选股筛选、轮动研究和强势股雷达只读取本地 K 线缓存，不调用回测引擎，也不改交易流水字段。形态扫描里的突破基准、箱体上沿、历史高点等条件均使用信号日之前的窗口；`stats screen` 和 `stats radar` 会先把每只股票切到 `--trade-date` 或最新缓存日，避免使用截止日之后的数据。雷达的 future_return、MFE、MAE 只在历史 snapshot 后验审计阶段补充，不参与当日 state 分类。涨跌停看板只在显式执行 `limit-board` 时访问 Tushare，并将 Tushare 的涨跌停榜、概念榜字段清洗为本地 CSV/HTML 和可选股票池。半年涨停研究只生成研究 CSV、细分股票池和 Markdown 基本面分析文档，不反向影响策略信号。

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
| 平均最大回撤 | `avg_max_dd` | `mean(max_drawdown_pct)` |
| 平均胜率 | `avg_win_rate` | `mean(win_rate_pct)` |
| 平均交易次数 | `avg_trades` | `mean(total_trades)` |

注意事项：

1. `avg_return`、`avg_annual_return`、`avg_annual_volatility` 都包含无交易股票。无交易股票的收益、年化收益和波动通常为 0，因此信号很少的策略会被 0 值明显稀释。
2. `avg_active_return` 和 `avg_active_annual_return` 排除了无交易股票，更接近“策略真正出手后的平均效果”。
3. `median_return` 用于观察典型股票表现。如果平均收益很高但中位数很低，通常说明少数大赢家拉高了均值。
4. `positive_ratio` 统计的是全部股票中的正收益比例，不只统计有交易股票。
5. `avg_win_rate` 是“先算每只股票自己的胜率，再取平均”，不是把所有交易混在一起算总体胜率。
6. `avg_excess_return` 和 `avg_information_ratio` 依赖基准指数缓存。若 `data/cache/{benchmark.symbol}.csv` 不存在，相关字段不会出现在 summary 中，统计报告会显示 0。

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
3. **不再使用 pyecharts**：所有图表数据序列化为紧凑 JSON，嵌入页面一次；JS 图表工厂模板（`_CHART_JS`，约 7.5KB）从共享数据创建 16 个 ECharts 实例
4. 日K/周K/月K 各 5 张图（K线 + 成交量/MACD/KDJ/RSI）+ 1 张权益曲线 = 16 张图，数据共享不发生重复
5. 报告体积从原来 pyecharts 方案的 3.2 MB 降低到 ~230 KB（**93% 缩减**）
6. `_build_page()` 拼装完整 HTML，包含：
   - **周期标签栏**（日K | 周K | 月K）
   - **指标标签页**（成交量/MACD/KDJ/RSI 切换，作用域在当期周期 section 内）
   - **ECharts 联动**：所有图表通过 `echarts.connect('qg')` 同步 dataZoom
   - 标签切换时 80ms 延迟 resize 目标区域内的图表
7. 多周期量价趋势报告会读取交易流水旁的 `*.params.json` 边车文件，用本次回测的实际参数复算诊断标记、日线 EMA 和 ATR 止损线；旧流水没有边车文件时退回策略默认参数。
8. 单标的报告会调用 `analysis/trendlines.py` 生成自动画线 payload，并在 K 线图上叠加趋势线、通道线、支撑压力线和颈线。该 payload 只解释价格结构，不参与策略信号。

**报告包含的图表板块**：
1. K线图（含 MA5/MA10/MA20/MA60 + 买卖点标记），高度 500px
2. 联动指标区（标签页切换，与 K线图缩放同步）：
   - 成交量（红涨绿跌柱状图），300px
   - MACD（DIF/DEA + 柱状图），350px
   - KDJ（K/D/J 三线，自动缩放），350px
   - RSI（RSI线 + 30/70 参考线），300px
3. 权益曲线 + 回撤，520px

---

### `analysis/trendlines.py` — 自动画线分析模块

**定位**：确定性结构识别与可视化，不做涨跌预测，不改变交易流水、权益曲线或回测绩效口径。

**输入**：包含 `date, open, high, low, close, volume` 的 OHLCV DataFrame。日期会转为 datetime，价格列转为数值并按日期排序。

**核心输出**：

| 字段 | 说明 |
|------|------|
| `pivots` | fractal/pivot 局部高低点，含 `index/date/price/type/strength/confirmed_date` |
| `uptrend_lines` | 基于 `swing_low` 的上升趋势线，含斜率、截距、触碰数、违规数、分数和最新价距离 |
| `downtrend_lines` | 基于 `swing_high` 的下降趋势线 |
| `channels` | 以上升/下降趋势线为基准的平行通道 |
| `support` / `resistance` | swing low/high 聚类得到的支撑压力水平位 |
| `necklines` | 双顶、双底、头肩顶、倒头肩的颈线候选 |

**关键规则**：

1. `identify_pivots(df, pivot_window=5)` 只在左右窗口都存在时确认 pivot，因此 pivot 的 `confirmed_date` 是 `index + pivot_window` 对应日期。
2. `analyze_trendlines(df, as_of=...)` / `as_of_index=...` 会先截断数据，再识别 pivot；策略特征必须使用该 rolling 模式，不能用全样本结果。
3. 趋势线容差默认取 `max(ATR20 * 0.35, close * 0.01)`，支撑压力聚类默认取 `max(ATR20 * 0.5, close * 0.01)`。
4. 趋势线评分来自触碰次数、持续长度、最近性、pivot 强度和违规次数；线条只用于结构化解释，不能视作预测信号。
5. 参数可在 `config.yaml::trendlines` 中配置，也可通过 `TrendlineConfig` 覆盖。`backtest trendlines` 命令作为兼容入口保留，但现在生成集成手动画线工具的股票 K 线页面。

**示例**：

```bash
python main.py backtest trendlines --symbol 000001.SZ --bars 0
```

输出 HTML：`output.reports_dir/stock_kline/{symbol}.html`；命令打印最新行情摘要和手动画线启用状态。

---

### `analysis/` — 全市场统计分析模块

基于批量回测汇总数据（`_summary_*.csv`）生成亮色主题 HTML 分析报告。模块结构：

| 文件 | 职责 |
|------|------|
| `analyzer.py` | 数据加载（`load_summary()`、`load_all_summaries()`）、分布统计（`compute_stats()`）、直方图分箱（`build_return_histogram()`）、雷达图归一化（`normalize_for_radar()`）、策略相关性矩阵（`compute_correlation_matrix()`） |
| `charts.py` | 亮色主题 pyecharts 图表组件：收益率/夏普/交易次数直方图、风险收益散点图、雷达图、箱线图、柱状图、相关性图、策略叠加散点图 |
| `report.py` | HTML 报告组装：`build_analyze_page()`（单策略画像）、`build_compare_page()`（多策略对比）。生成响应式卡片布局 + 图表嵌入页面 |
| `rps.py` | 从本地 K 线缓存计算 RPS Top N 和个股 RPS 轨迹，输出 CSV/HTML |
| `patterns.py` | 扫描主升浪、底部突破、单针探底等研究候选，输出到 `output/signals/` |
| `screener.py` | 通用选股筛选器，第一版支持趋势线回踩预设，输出到 `output/signals/` 并可选写入股票池 |
| `rotation.py` | 组合层动量/三因子轮动研究，输出净值、换仓明细和 HTML |
| `limit_moves.py` | 基于 Tushare 涨跌停榜生成每日涨跌停看板，并可按涨跌停状态/行业分类写入股票池 |
| `limit_up_research.py` | 基于 Tushare 区间涨停榜、同花顺概念成员和财务指标，生成半年涨停细分股票池、主题汇总、基本面快照和 Markdown 研究文档 |

**亮色主题常量**（独立于 `visual/kline_chart.py` 的暗色主题）：`_BG_COLOR = "white"`、`_TITLE_COLOR = "#1a1a2e"`、`_UP_COLOR = "#ef5350"`（红涨）、`_DOWN_COLOR = "#26a69a"`（绿跌）。

---

## 配置文件说明

```yaml
tushare:
  token: "你的token"          # Tushare API 密钥

data:
  cache_dir: "data/cache"     # 数据缓存目录
  stock_adj: "qfq"            # 股票日线复权口径：qfq=前复权，hfq=后复权，null=不复权

backtest:
  initial_cash: 100000.0      # 初始资金（元）
  commission: 0.00025         # 佣金费率 0.025%
  stamp_duty: 0.001           # 印花税 0.1%（仅卖出）
  min_commission: 5.0         # 最低佣金 5 元
  slippage_perc: 0.001        # 滑点比例
  enforce_price_limits: true  # 模拟涨跌停限制
  limit_pct: 0.10             # 默认涨跌停幅度
  volume_limit_ratio: 0.02    # 单笔成交不超过当日成交量比例
  volume_unit: 100            # Tushare vol 单位为手，1 手 = 100 股

rate_limit:
  calls_per_minute: 500       # API 调用频率上限

benchmark:
  enabled: true
  symbol: "000300.SH"         # 基准指数，用于超额收益/信息比率

index_overview:
  default_symbol: "000001.SH"
  indexes:
    - symbol: "000001.SH"
      name: "上证指数"
      market: "SH"

output:
  trades_dir: "output/trades"     # 交易流水输出目录
  reports_dir: "output/reports"   # 报告输出目录
  signals_dir: "output/signals"   # 买点扫描汇总输出目录
  statistics_dir: "output/statistics"

parallel:
  download_workers: 5
  backtest_workers: 12
  backtest_max_tasks_per_child: null

defaults:
  start_date: "20110101"          # 默认起始日期

watchlist:                    # 默认关注的股票列表（供快速下载参考）
  - "000001.SZ"   # 平安银行
  - "000002.SZ"   # 万科 A
  - "600519.SH"   # 贵州茅台
```

本地大规模缓存和输出可以通过 `config.yaml` 指向外部磁盘，例如 `/Volumes/extend/quant_yb_data/cache` 和 `/Volumes/extend/quant_yb_data/output/...`。代码应始终从配置读取路径，避免把个人机器的绝对路径硬编码进模块。

批量回测默认不启用 `ProcessPoolExecutor.max_tasks_per_child`。历史上曾默认每个子进程处理 100 个任务后轮换，在 8 个回测进程时会刚好在 800 个任务附近触发整批 worker 重建；macOS/交互式入口下可能表现为进度停在 `800/xxxx` 且无报错。因此当前 `parallel.backtest_max_tasks_per_child` 默认为 `null`，只有明确需要控制子进程生命周期时再手动设置。

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
