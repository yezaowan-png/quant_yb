# AGENTS.md

## 项目与入口

这是一个中国 A 股日 K 量化交易、回测与市场分析项目。`main.py` 注册 `data`、`backtest`、`stats`、`index`、`dashboard` 等命令；主要代码位于 `cli/`、`data/`、`engine/`、`strategy/`、`analysis/`、`visual/`。

开始任务时先读 [当前项目状态](docs/reference/CURRENT_STATE.md)。再按任务需要选择性阅读以下文档，不要一次加载全部长文档：

- 用户命令：`README.md`、`docs/operations/DAILY_COMMANDS.md`
- 技术架构：`TECHNICAL.md`
- 行为与输出契约：`docs/reference/contracts.md`
- 每日自动化：`docs/operations/DAILY_AUTOMATION.md`
- 市场结构口径：`docs/reference/index_market_structure.md`
- 已完成重构：`docs/plans/completed/REFACTOR_PLAN.md`

## 修改原则

- 修改前检查工作区状态。现有改动和新增文件可能属于用户，不得回滚、覆盖或清理无关内容。
- 先定位完整影响链路：CLI 参数 → 配置 → 数据读取 → 策略/分析 → 引擎 → 输出/报告。
- 小步修改，只改任务必需内容；不要为风格偏好重命名、迁移目录、重写 CLI 或继续拆分已稳定模块。
- 路径从 `config.yaml` 读取，不得硬编码个人机器的 `/Volumes/...` 路径。
- 不提交 Tushare、DeepSeek 等密钥，不把真实 token、大规模缓存或运行产物写入文档。
- 不执行破坏性 Git 或文件命令，不删除 `output/`、`data/cache/` 或用户配置，除非用户明确要求。

## 回测与数据可信度

- 严禁未来函数和数据泄露：信号只能使用当前 bar 及之前数据；突破基准通常排除触发当日；周线过滤只能使用已完成周线。
- 报告、统计、市场结构和 LLM 总结只能解释结果，不得反向影响正式策略、仓位、订单或 `market_risk_gate`。
- 历史股票池存在幸存者偏差；历史行业、ST 和成分若非严格时点数据，严肃结论必须明确标注。
- 新策略继承 `strategy.base.BaseStrategy`，复用仓位、T+1、涨跌停、成交量、手续费和交易流水逻辑。
- 修改回测逻辑时说明对成交价格、手续费、滑点、涨跌停、成交量限制、T+1、绩效指标和导出格式的影响。
- 保持 `docs/reference/contracts.md` 规定的命令、文件名和 CSV 字段兼容；必须改变时同步所有调用方和文档。

## 验证要求

- 共享回测逻辑先做单标的验证，再运行相关测试；批量任务会写大量输出，不作为首轮验证。
- 常用检查：`python -m unittest discover -s tests`、`python -m compileall main.py cli data engine strategy visual analysis tests`。
- 依赖网络、Tushare token 或本地缓存的结论，要注明数据源、日期范围和未验证项，不得编造成功结果。
- 架构类改动应先补或更新契约测试；用户命令、参数、输出或架构变化需同步 `README.md` 或 `TECHNICAL.md`。

## 回复要求

- 使用中文，先给结论。
- 代码修改需列出修改文件及目的、实际运行的命令与结果、未验证项和已知风险。
- 量化结果需注明标的、策略、日期范围、数据源、手续费/滑点设置及输出路径。
