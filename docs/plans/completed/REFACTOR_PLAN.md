# 项目结构优化计划

## 目标

在不改变策略信号、成交模型、复权口径、命令参数和输出文件格式的前提下，降低 CLI、数据下载、报告生成和文档维护成本。

## 基本原则

- 小步修改，每个阶段可以独立验证和回滚。
- 先补契约测试，再拆共享逻辑。
- 保留现有命令和输出路径，不做大规模重命名。
- 数据下载、回测引擎、策略和报告层保持单向依赖。
- 重构不用于顺带修改策略参数或回测结果。

## 收敛结论

状态：第一轮收敛完成

本轮结构优化到此暂停。当前已完成契约冻结、CLI/REPL 服务复用、下载层第一轮拆分、报告层公共组件抽取、文档归档和重点测试覆盖。后续不再继续做大规模结构拆分，除非出现明确的维护瓶颈或用户功能需求直接要求。

暂缓项：

- 暂不继续迁移超长 Click 参数装饰器，避免引入命令参数兼容风险。
- 暂不继续拆 `DataDownloader.download_batch()` 的失败重试编排，当前已有测试覆盖且行为清晰。
- 暂不继续拆 `visual.report` 的 HTML 组装，现有公共组件和数据 payload 已足够支撑维护。
- 暂不调整目录、命令、CSV 字段和输出文件名。

## 阶段 0：冻结现有契约

状态：已完成

任务：

- 建立 `docs/reference/contracts.md`，记录命令、目录、CSV 和回测约束。
- 补题材统计、dashboard 收录、股票池解析等快速测试。
- 为后续 CLI 和下载器拆分建立行为基线。

已完成：

- 新增当前行为契约文档。
- 题材统计、题材看板发现和交易流水识别测试已加入基线。

验收标准：

- `python -m unittest discover -s tests` 通过。
- 现有命令名称和输出文件名不变。
- 不改手续费、滑点、涨跌停、T+1、成交量限制和信号逻辑。

## 阶段 1：统一 CLI 公共能力

状态：第一轮完成，剩余项暂缓

任务：

- 抽取配置加载、策略枚举、缓存读取和交易流水识别等公共函数。
- Click CLI 和 `quant>` REPL 调用相同的服务函数。
- 合并 REPL 与流水线重复的命令路由。
- 将策略参数定义从超长 Click 装饰器逐步迁移到可复用元数据。

已完成：

- 新增 `cli/common.py`。
- 统一配置加载、策略枚举、股票缓存读取和交易流水识别。
- 数据下载、stock_basic、daily_basic 和 dashboard 已由 Click CLI 与 REPL 共用服务函数。
- REPL 与流水线已统一使用 `_dispatch_command()` 路由。
- 指数下载/报告/概览、策略统计和回测 HTML 报告已由 Click CLI 与 REPL 共用服务函数。
- 回测执行、买点扫描和策略对比已由 Click CLI 与 REPL 共用服务函数。
- 公共服务边界已增加契约测试，覆盖指数输出路径、策略统计报告和交易报告自动识别。

暂缓项：

- 进一步缩短超长 Click 参数装饰器，迁移到更集中、更可复用的参数元数据。

验收标准：

- 直接命令与 REPL 对相同输入产生相同结果。
- 新增策略参数只需要修改一处元数据。
- `cli/shell.py` 不再复制回测、报告和统计业务实现。

## 阶段 2：拆分数据下载层

状态：第一轮完成，剩余拆分暂缓

建议模块：

- `data/tushare_client.py`：API 调用、token 轮换、限流和重试。第一轮已新增。
- `data/cache_store.py`：股票、指数、daily_basic 和基础信息 CSV 读写。第一轮已新增。
- `data/adjustment.py`：复权处理和复权因子变化检测。第一轮已新增。
- `data/download_failures.py`：失败文件读取和失败快照 CSV 写入。第一轮已新增。
- `data/download_planner.py`：批量下载预估和计划计算。第一轮已新增。
- `data/download_retry.py`：失败补下载筛选和命令生成。第一轮已新增。
- `data/metadata.py`：stock_basic、名称映射和 daily_basic 清洗。第一轮已新增。
- `data/price_cleaning.py`：股票/指数日线清洗。第一轮已新增。
- `data/download_service.py`：全量、增量、按交易日下载和失败补下载编排。第一轮已新增，当前承接下载标的解析和计划文案格式化。

已完成：

- 新增 `data/cache_store.py`。
- `DataDownloader` 内部已委托 `CsvCacheStore` 处理缓存路径、股票/指数 K 线缓存、`daily_basic` 缓存和 K 线增量检查日期。
- 新增 `data/tushare_client.py`。
- `DataDownloader` 内部已委托 `TushareClient` 处理 token 去重、token 轮换、限流、频率超限退避重试和取消检查。
- 新增 `data/adjustment.py`。
- `DataDownloader` 内部已委托 `data.adjustment` 处理逐标的 qfq/hfq 价格调整和重叠日期价格不一致检测。
- 新增 `data/download_failures.py`。
- `DataDownloader` 内部已委托 `data.download_failures` 处理失败文件读取和失败快照 CSV 写入。
- 新增 `data/download_planner.py`。
- `DataDownloader` 内部已委托 `data.download_planner` 处理缓存命中、预计接口次数和预计耗时计算。
- 新增 `data/download_retry.py`。
- `DataDownloader` 内部已委托 `data.download_retry` 处理失败是否可重试的判断和补下载命令生成。
- 新增 `data/metadata.py`。
- `DataDownloader` 内部已委托 `data.metadata` 处理股票列表过滤、基础信息缓存清洗、名称映射和 daily_basic 清洗。
- 新增 `data/price_cleaning.py`。
- `DataDownloader` 内部已委托 `data.price_cleaning` 处理股票/指数日线字段映射、日期转换和数值清洗。
- 新增 `data/download_service.py`。
- `cli.data_cli` 已委托 `data.download_service` 解析失败文件、显式股票和全市场下载标的；`DataDownloader.download_batch()` 已委托它格式化计划文案；实际下载仍由 `DataDownloader.download_batch()` 负责。
- `DataDownloader.download_batch()` 已委托 `data.download_service.download_symbols_parallel()` 执行单轮并发下载；失败快照、自动补下载和最终提示仍保留在 `DataDownloader`，避免一次性改动过大。
- 保留 `DataDownloader` 原有对外入口和私有方法名，避免 CLI 与调用方改动。

实施方式：

- 暂时保留 `DataDownloader` 作为兼容入口，内部委托给新模块。
- 先拆纯函数和文件读写，再拆并发调度。
- 用户确认逻辑留在 CLI 层，下载服务接收明确的执行模式。

## 阶段 3：整理报告层

状态：第一轮完成，剩余拆分暂缓

任务：

- 抽取 HTML 外壳、统计卡片、表格和 ECharts 公共组件。
- 单标的报告、策略统计、题材看板和总 dashboard 各自保留业务数据准备。
- 将 `visual/report.py` 中指标计算、诊断数据和 HTML 渲染逐步拆开。

已完成：

- 新增 `visual/components.py`。
- `visual/index_report.py` 已委托公共组件生成 HTML 外壳和 ECharts 脚本标签。
- `visual/dashboard.py` 已委托公共组件生成 HTML 外壳和 JSON 数据脚本。
- `analysis/theme_report.py` 已委托公共组件生成 HTML 外壳、ECharts 脚本标签和 JSON 数据脚本。
- `analysis/report.py` 已委托公共组件生成统计分析和策略对比报告的 HTML 外壳。
- `visual/report.py` 已委托公共组件生成单标的回测报告的 HTML 外壳。
- 新增 `visual/stock_report_data.py`，单标的报告日/周/月周期 payload、共享指标计算、OHLC 重采样和周线 EMA 诊断 payload 已迁入。
- `visual/index_report.py` 已复用 `visual.stock_report_data` 的指标计算和 OHLC 重采样 helper。
- 报告紧凑 JSON 序列化已迁入 `visual.components.to_compact_json()`，指数报告不再从单标的报告模块导入 `_to_json`。
- 单标的报告权益曲线 payload 和回撤计算已迁入 `visual.stock_report_data`。
- 单标的回测报告的多周期策略诊断 payload 已迁入 `visual.stock_report_data`，HTML 卡片仍由 `visual.report` 组装。
- `visual.report._calc_mtf_diagnostics()` 当前保留兼容入口，旧的大段诊断计算代码已删除。

## 阶段 4：整理文档

状态：已完成第一轮整理

目标结构：

```text
docs/
  operations/
  plans/
  strategies/
  reference/
    contracts.md
```

任务：

- `README.md` 已保留项目简介、快速开始、核心命令和文档导航。
- `DAILY_COMMANDS.md` 已移到 `docs/operations/`，保留日常速查。
- 策略设计文档已移到 `docs/strategies/`。
- 研究草案和参考资料已移到 `docs/plans/`。
- 行为契约已移到 `docs/reference/contracts.md`。

## 阶段 5：扩大测试覆盖

状态：已完成第一轮覆盖

优先测试：

- K 线尾部增量合并和重复日期去重。第一轮已补测试。
- 前复权缓存口径与复权因子变化。第一轮已补测试。
- Tushare 限流、重试、取消和失败记录。第一轮已补测试。
- 周线特征仅使用已完成周线。第一轮已补测试。
- 题材统计和 dashboard 报告发现。第一轮已补测试。
- Click CLI 与 REPL 参数一致性。第一轮已补测试。

## 明确不做

- 不迁移到数据库，除非 CSV 已被证明是性能瓶颈。
- 不替换 Backtrader。
- 不重写现有策略。
- 不改变现有交易流水、权益曲线和汇总 CSV 字段。
- 不在本轮重构中加入新的交易信号。
