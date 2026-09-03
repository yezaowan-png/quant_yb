# 当前项目状态（精简上下文）

> 更新日期：2026-08-09  
> 用途：后续 Codex 对话先读取本文件和根目录 `AGENTS.md`，再只读取与任务直接相关的详细文档。

## 1. 稳定架构

- 项目入口为 `main.py`，CLI、数据、回测引擎、策略、分析和可视化分别保留在原有目录。
- `DataDownloader`、`visual.report`、Click/REPL 保留兼容入口，不再为“更干净”继续拆模块。
- 正式交易链路与指数概览、市场结构、dashboard 相互隔离；后者不得生成或修改正式交易信号。
- 数据缓存和输出目录均通过 `config.yaml` 配置，当前个人环境可能指向外部磁盘。

## 2. 市场结构分析 v2

当前市场结构第一版已完成，入口命令为：

```bash
python main.py index market
```

主要实现：

- `analysis/market_structure_v2.py`：九屏指标与状态计算
- `analysis/market_structure_state_v2.py`：跨日状态跟踪
- `analysis/index_market_structure.py`：市场结构数据组织
- `analysis/index_market_history.py`：历史记录与归档
- `analysis/index_market_llm.py`：DeepSeek 事实包和复盘总结
- `visual/index_forecast_report.py`：HTML 报告与交互图表
- `cli/index_cli.py`：命令入口

报告包含九个部分：总览、指数与技术结构、指数强弱、市场宽度、市场风格、行业强弱、银行保险证券、新高新低与风险扩散、历史状态与复盘。各字段、公式、阈值和阅读顺序见 `docs/reference/index_market_structure.md`。

关键约束：

- 市场结构属于解释层，不参与正式策略、仓位、订单和风险闸门。
- 技术结构、行业/风格代理指数和 LLM 结论都要保留数据口径与局限说明。
- DeepSeek 密钥只从环境文件读取，不得写入代码、文档或回复。

## 3. 每日自动化与归档

- 每日脚本：`scripts/daily_quant_job.sh`
- 结果校验：`scripts/verify_daily_market_structure.py`
- 历史补档：`scripts/backfill_market_structure_history.py`
- macOS launchd 任务：`com.caleb.quant-yb.daily`，计划在交易日晚间 18:40 执行。
- 每次生成市场结构报告时，同时生成 LLM 复盘总结并在主 HTML 中提供链接。
- 主报告和复盘总结按“数据日期”归档到 `reports/index_forecast/archive/market_structure_v2/YYYY-MM-DD/`，不能只按脚本运行日期命名。
- 自动化操作与故障排查见 `docs/operations/DAILY_AUTOMATION.md`。

## 4. 最近验证基线

- 最近确认的数据日期：2026-08-07。
- 最近完整测试基线：`python -m unittest discover -s tests`，332 项通过（2026-08-09，228.5 秒）。
- `python -m compileall -q main.py project_config.py cli data engine strategy visual analysis etf_strategy tests scripts` 通过。
- `.agents/skills/run-quant-yb/smoke.py --symbol 000001.SZ` 缓存数据端到端检查 4/4 通过，并覆盖 8 个策略的导入。
- 深度数据审计扫描个股 12,594,344 行、指数 683,026 行、daily_basic 144,186 行；个股最新日覆盖 99.6%。当前 6 只北交所股票的早期新三板历史含 12 条坏行情记录，报告给出强制重拉命令，未自动改写用户缓存。
- Dashboard 同一命令耗时由优化前 86.33 秒降至本轮首跑 5.57 秒、紧接复跑 2.14 秒；外部磁盘缓存状态会影响绝对耗时。
- 市场结构说明文档已与实际 HTML 和 v2 测试口径核对。
- 冻结的 400 日归档基线保持不变：27 个文件、7,400,140 字节；SHA-256 为 `fc3c849e365d7471da1443bfad00e8071a7d7123d26708520150ca7d56f93c57`。

以上是历史验证基线，不代表后续修改自动通过；每次仍需按改动范围重新验证。

## 5. 已知限制

- `000985.SH` 当前数据源不可用，相关对比需使用已有替代口径并明确标注。
- 部分估值和外部数据接口尚未接入或稳定性未知。
- 历史股票池、行业分类、ST 状态和指数成分并非全部严格时点数据，存在幸存者偏差或回溯偏差。
- 新股上市初期无涨跌幅限制、历史 ST 时点状态及交易经手/过户费的日期化规则尚未完整建模；常规板块涨跌停与 2023-08-28 印花税调整已按成交日期处理。
- 当前深度审计发现 `920139.BJ`、`920489.BJ`、`920556.BJ`、`920641.BJ`、`920682.BJ`、`920809.BJ` 的早期历史源数据异常；在重拉并复审前，涉及这些标的早期区间的回测不应作为正式结论。
- 部分 pandas 计算存在 DataFrame fragmentation 性能告警，目前不影响结果，但后续可做定向性能优化。
- 市场结构历史归档尚未设置自动保留期和压缩策略。
- `visual/dashboard.py`、`analysis/index_market_structure.py` 等仍有超长组装函数；当前无导入环，后续拆分应先补细粒度契约测试，再按数据准备/视图模型/HTML 渲染边界分阶段进行。

## 6. 后续任务最小交代方式

新对话可直接说明：

> 请先读 `AGENTS.md` 和 `docs/reference/CURRENT_STATE.md`，保持现有市场结构 v2、输出契约和交易链路隔离，只处理以下任务：……

需要核对详细口径时再补充指定文档，避免重复粘贴完整项目背景。
