# 架构优化计划

本文档记录当前项目的整理方向。目标是降低维护成本，不改变现有回测口径、输出文件名和日常命令。

## 当前结论

本计划已归档，第一轮结构优化已经收敛完成。后续以 `docs/plans/completed/REFACTOR_PLAN.md` 的“收敛结论”为准：不再继续做大规模结构拆分，除非出现明确维护瓶颈或用户功能需求直接要求。

## 当前判断

项目功能已经进入可日常使用阶段：数据下载、回测、报告、指数概览、题材池和 dashboard 都能跑通，关键边界已经通过契约文档和测试固定。新增功能应优先保持现有命令、CSV 字段、输出路径和回测口径稳定。

优先保持以下契约稳定：

- 交互命令：`download`、`backtest`、`scan`、`report`、`stats`、`dashboard`
- 直接命令：`python main.py data ...`、`python main.py backtest ...`、`python main.py stats ...`
- K 线缓存：`data.cache_dir/{ts_code}.csv`
- 每日指标：`data.meta_dir/daily_basic/{ts_code}.csv`
- 交易流水：`output.trades_dir/{symbol}_{strategy}.csv`
- 题材看板：`output.statistics_dir/theme_{pool}_{start}_{end}.html`
- 总控面板：`output.reports_dir/dashboard.html`

## 主要问题

1. `DataDownloader` 已完成第一轮拆分，但仍保留兼容编排入口。
2. Click CLI 和 `quant>` shell 的主要命令已复用共享服务函数，超长参数装饰器暂缓迁移。
3. 报告层已抽出公共 HTML/JSON helper 和单标的报告数据 payload，剩余 HTML 组装暂缓拆分。
4. 文档已经归档到 `docs/operations`、`docs/strategies`、`docs/plans` 和 `docs/reference`。
5. 核心数据链路、报告聚合、CLI/REPL 参数一致性和周线未来函数约束已有第一轮测试覆盖。

## 阶段 0：补契约和测试

目标：先给后续重构加护栏。

- 补题材统计和 dashboard 收录测试。
- 补 CLI common 工具函数测试：策略列表、交易流水名解析、缓存读取。
- 补输出文件命名契约测试。
- 不改业务逻辑。

验收：

```bash
python -m unittest discover -s tests
python -m compileall main.py cli data engine strategy visual analysis
```

## 阶段 1：统一 CLI 基础层

目标：Click 命令和交互式 shell 复用同一批 service 函数。

状态：第一轮完成，剩余项暂缓。

当前进度：

- 已有 `cli/common.py`，提供配置读取、策略列表、缓存读取和交易流水查找。
- `download`、`stock-basic`、`daily-basic`、`index`、`dashboard` 已经通过 `run_*` 函数被 Click 和 `quant>` shell 复用。
- `stats analyze/compare/theme` 已有共享构建函数或共享执行函数。
- `compare --symbol` 已抽为 `cli.backtest_cli::run_strategy_comparison()`，Click 和 `quant>` shell 共用。
- `scan` 已抽为 `cli.backtest_cli::run_scan_buy_signals()`，Click 和 `quant>` shell 共用。
- `backtest run` 已抽为 `cli.backtest_cli::run_backtest_workflow()`，Click 和 `quant>` shell 共用。

现有边界：

- `cli/common.py`：配置读取、策略列表、缓存读取、交易流水查找。
- 各 CLI 模块暴露 `run_*` 或 `build_*` 服务函数，供 Click 和 shell 共用；暂不新增 `cli/services.py` 统一大入口。
- `cli/shell.py`：只保留文本解析、帮助信息、路由和异常展示。

验收：

- `quant> backtest ...` 与 `python main.py backtest run ...` 走同一业务函数。
- 新增参数只需要改一处参数归一化逻辑。

## 阶段 2：拆分数据下载层

目标：保持 `DataDownloader` 对外兼容，内部逐步委托到更小模块。

状态：第一轮完成，剩余拆分暂缓。

当前进度：

- 已新增 `data/cache_store.py`，负责缓存目录、meta 目录、失败记录目录、股票/指数 K 线 CSV、`daily_basic` CSV 和 K 线增量检查日期的读写。
- 已新增 `data/tushare_client.py`，负责 token 去重、token 轮换、限流、频率超限退避重试和取消检查。
- 已新增 `data/adjustment.py`，负责逐标的 qfq/hfq 价格调整和重叠日期价格不一致检测。
- 已新增 `data/download_failures.py`，负责失败文件读取和失败快照 CSV 写入。
- 已新增 `data/download_planner.py`，负责批量下载前的缓存命中、预计接口次数和预计耗时计算。
- 已新增 `data/download_retry.py`，负责失败是否可自动重试的判断和补下载命令生成。
- 已新增 `data/download_service.py`，第一轮承接下载标的解析、下载计划文案格式化和单轮并发下载执行 helper；失败快照、自动补下载和最终提示仍由 `DataDownloader` 编排。
- 已新增 `data/metadata.py`，负责股票基础信息、名称映射和 `daily_basic` 的清洗辅助。
- 已新增 `data/price_cleaning.py`，负责股票/指数日线字段映射和清洗。
- `DataDownloader` 仍保留原有对外入口和私有方法名，内部已委托给 `CsvCacheStore`、`TushareClient`、`data.adjustment`、`data.download_failures`、`data.download_planner`、`data.download_retry`、`data.metadata` 和 `data.price_cleaning`。
- 不再继续拆失败重试编排，除非后续出现明确维护瓶颈。

现有模块：

- `data/tushare_client.py`：token 轮换、限流、重试、Tushare API 调用。
- `data/cache_store.py`：K 线、指数、stock_basic、daily_basic 的读写。
- `data/adjustment.py`：前复权处理、复权因子变化检测。
- `data/download_failures.py`：失败文件读取和失败快照 CSV 写入。
- `data/download_planner.py`：批量下载预估和计划计算。
- `data/download_retry.py`：失败补下载筛选和命令生成。
- `data/metadata.py`：stock_basic、名称映射和 daily_basic 清洗。
- `data/price_cleaning.py`：股票/指数日线清洗。
- `data/download_service.py`：下载标的解析、计划文案格式化和单轮并发下载 helper。

约束：

- 不改变缓存 CSV 字段。
- 不改变失败文件字段。
- 不改变默认前复权口径。

## 阶段 3：整理报告层

目标：报告文件更小，样式和表格组件复用。

状态：第一轮完成，剩余拆分暂缓。

当前进度：

- 已新增 `visual/components.py`，提供 HTML 文档外壳、脚本标签、ECharts 引入和报告 JSON 序列化 helper。
- `visual/index_report.py` 已使用公共 HTML 外壳和 ECharts 引入 helper。
- `visual/dashboard.py` 已使用公共 HTML 外壳和 JSON 安全嵌入 helper。
- `analysis/theme_report.py` 已使用公共 HTML 外壳、ECharts 脚本标签和 JSON 安全嵌入 helper。
- `analysis/report.py` 已使用公共 HTML 外壳和 ECharts 脚本标签生成统计分析/策略对比报告。
- `visual/report.py` 已使用公共 HTML 外壳和 ECharts 脚本标签生成单标的回测报告。
- 已新增 `visual/stock_report_data.py`，负责单标的报告日/周/月周期 payload、权益曲线 payload、多周期量价趋势诊断 payload、共享指标计算、OHLC 重采样和周线 EMA 诊断 payload。
- `visual/index_report.py` 已复用 `visual.stock_report_data` 的指标计算和 OHLC 重采样 helper。
- 单标的报告的多周期策略诊断 HTML 不再继续拆分，先保持输出行为稳定。

现有边界：

- `visual/components.py`：HTML 外壳、卡片、表格、排序脚本、ECharts 引入、报告 JSON 序列化。
- `visual/stock_report_data.py`：单标的报告数据组装。
- `visual/report.py`：只负责单标的 HTML 页面拼装。
- `analysis/theme_report.py`：继续只负责题材 HTML 看板。
- `visual/dashboard.py`：继续只负责总控导航。

## 阶段 4：整理文档目录

目标：根目录只保留入口文档，设计和计划归档到 `docs/`。

当前进度：

- `README.md` 已精简为项目入口、快速开始、常用命令和文档导航。
- 日常操作文档已移到 `docs/operations/`。
- 策略设计文档已移到 `docs/strategies/`。
- 计划和调研文档已移到 `docs/plans/`。
- 行为契约已移到 `docs/reference/contracts.md`。

当前结构：

```text
docs/
  operations/
    DAILY_COMMANDS.md
    MAC_CONDA_SETUP.md
    GIT_GUIDE.md
  strategies/
    MULTI_TIMEFRAME_VOLUME_TREND.md
    MULTI_TIMEFRAME_VOLUME_TREND.pdf
    WYCKOFF_TRIPLE_SCREEN.md
  plans/
    completed/
      ARCHITECTURE_OPTIMIZATION_PLAN.md
      REFACTOR_PLAN.md
    TRADINGAGENTS_INTEGRATION_PLAN.md
    GITHUB_QUANT_PROJECTS_REFERENCE.md
  reference/
    contracts.md
```

README 目标：

- 控制在 200-300 行。
- 只保留项目定位、快速开始、最常用命令、文档入口。
- 详细策略和计划文档移到 `docs/`。

## 后续原则

- 先做业务需求，不继续为了结构洁癖拆模块。
- 改公开命令、CSV 字段、输出路径或回测口径前，必须同步更新 `docs/reference/contracts.md` 和测试。
- 下载稳定性、题材分析、策略规则优化优先于进一步架构拆分。
