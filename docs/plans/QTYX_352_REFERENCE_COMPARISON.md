# QTYX_352 全面对比参考

扫描日期：2026-07-04

## 结论

QTYX_352 值得参考，但不适合整体迁移。

它的优势在于“桌面工作台式产品经验”：股票池管理、形态选股、RPS 强度、ETF 轮动、特殊数据筛选、图表标记、AI 提示词和实盘扫描都已经串成用户工作流。quant_yb 的优势在于“研究和回测内核”：CLI 可脚本化、Backtrader 事件驱动回测、A 股交易约束、输出契约、HTML 报告、测试套件和文档更清晰。

最合适的参考方式是：吸收 QTYX 的规则、指标、产品流程和看板组织方式，重新按 quant_yb 现有分层实现；不要复制 wxPython 架构、交易驱动、敏感配置或没有测试保护的批处理回测逻辑。

## 扫描范围

QTYX_352 实际路径：

- `/Users/caleb/projects/codex_prj/QTYX_352`

已读基础材料：

- `QTYX_352/CODEX.md`
- `QTYX_352/docs/PROJECT_FUNCTIONS.md`
- `QTYX_352/docs/STRATEGIES.md`

抽读源码范围：

- `StrategyGath/SignalGath.py`
- `StrategyGath/PattenGath.py`
- `StrategyGath/IndicateGath.py`
- `CommIf/DefPool.py`
- `CommIf/CodeHandle.py`
- `ApiData/HistoryOCHLV.py`
- `ApiData/SpecialData.py`
- `MainlyGui/UserFrame.py`
- `MainlyGui/TradeFrame.py`
- `MainlyGui/ElementGui/DefDialogs.py`
- `ConfigFiles/trade_para.json`

当前 quant_yb 对照范围：

- `README.md`
- `TECHNICAL.md`
- `docs/reference/contracts.md`
- `main.py`
- `cli/`
- `data/`
- `engine/runner.py`
- `strategy/`
- `analysis/`
- `visual/`
- `tests/`

规模粗略对比：

| 项目 | Python 行数 | 形态 |
| --- | ---: | --- |
| quant_yb | 约 18,571 行 | CLI + Backtrader + HTML 报告 + 测试 |
| QTYX_352 | 约 52,734 行 | wxPython 桌面工作台 + 数据/图表/选股/实盘辅助 |

## 项目定位对比

| 维度 | quant_yb | QTYX_352 | 参考判断 |
| --- | --- | --- | --- |
| 核心定位 | A 股研究、回测、批量扫描、报告流水线 | 桌面量化分析与交易辅助工作台 | QTYX 的工作流可参考，内核不宜替换 |
| 入口 | `python main.py`、Click 子命令、REPL、pipeline | `python StartEntry.py`、wxPython GUI | quant_yb 保持 CLI 优先，可在 dashboard 吸收工作台入口 |
| 数据粒度 | 当前以日 K 为主，指数和题材看板扩展 | 日线、分钟线、特色数据、财务、北向、涨停、问财 | 可参考多数据源和特色数据目录，但主行情口径保持 Tushare 缓存 |
| 回测模型 | Backtrader 事件驱动，成交、费用、T+1、涨跌停和成交量限制集中在基类/runner | DataFrame `Signal` + GUI 回测，部分策略信号延迟一天 | 回测可信度 quant_yb 更强，QTYX 规则需重写进现有模型 |
| 选股能力 | 买点扫描、题材股票池、统计分析 | 形态选股、条件筛选、RPS、股票池漏斗 | 这是 QTYX 最值得借鉴的方向 |
| 策略类型 | 单标的策略为主，多周期日/周过滤 | 择时、轮动、形态、外部策略、实盘扫描 | 轮动和形态应先做研究扫描，再评估是否纳入交易策略 |
| 报告展示 | ECharts HTML，输出路径稳定 | wx/matplotlib/pyecharts 桌面图表 | 图表思想可借鉴，技术栈保持 HTML 报告 |
| 实盘交易 | 当前不做实盘下单 | QMT、同花顺、IBKR 相关逻辑 | 不建议近期引入真实下单，可先做监控/提醒接口设计 |
| 工程质量 | 有测试、文档、行为契约、配置路径约束 | 无标准测试，依赖不完整，敏感配置集中在 ConfigFiles | quant_yb 的工程约束应保留 |

## 可参考程度分级

### A 级：强烈建议参考并重写实现

这些方向和 quant_yb 当前路线一致，迁移风险可控。

1. RPS 相对强度分析
   - QTYX 来源：`StrategyGath/IndicateGath.py`
   - 价值：全市场强弱排名、Top N、个股 RPS 轨迹，是买点扫描和题材分析的天然补充。
   - quant_yb 落地：新增 `analysis/rps.py`，基于本地 K 线缓存计算，不读取 QTYX 的 `DataFiles/stock_history`。
   - 推荐命令：`python main.py stats rps --window 120 --top 50`、`python main.py stats rps-track --symbol 000001.SZ --window 120`。
   - 输出建议：`output/statistics/rps_top_{window}_{date}.csv`、`output/statistics/rps_track_{symbol}_{window}.csv`、HTML 看板。

2. 形态选股扫描器
   - QTYX 来源：`StrategyGath/PattenGath.py`
   - 优先参考：底部盘整突破、主升浪启动、单针探底回升、六脉神剑。
   - 暂缓参考：杯柄、头肩底、相似度形态。它们参数多，部分日期/位置计算需要先校验。
   - quant_yb 落地：新增纯 pandas 扫描层，例如 `analysis/patterns.py` 或 `analysis/pattern_scanner.py`，不要直接塞进 `strategy/BaseStrategy`。
   - 推荐命令：`python main.py stats pattern --pattern main_rise_wave --pool 机器人` 或 `python main.py backtest pattern-scan ...`。
   - 输出建议：`output/signals/pattern_signals_{pattern}_{date}.csv`，dashboard 增加“形态扫描结果”入口。
   - 必须补测试：每个形态都要有“突破基准不包含当天”的测试，防止未来函数。

3. ETF/股票池轮动研究
   - QTYX 来源：`StrategyGath/SignalGath.py::momentum_rotation_strategy`、`three_factor_rotation_strategy`
   - 价值：quant_yb 目前偏单标的回测，轮动是明显扩展方向。
   - 风险：quant_yb 当前 `BacktestRunner` 是单数据 feed + 单标的导出模型，直接做多标的组合会影响资金、持仓、交易流水和统计口径。
   - 推荐路线：先做研究型组合回测，不改变现有单标的回测契约。新增 `analysis/rotation.py`，输出组合净值、换仓日志、持仓明细，再决定是否改 engine。
   - 推荐命令：`python main.py stats rotation --pool ETF --model momentum --hold-count 3 --rebalance 5`。

4. 股票池漏斗和结果表格
   - QTYX 来源：`MainlyGui/UserFrame.py`、`CommIf/CodeHandle.py`、`DefDialogs.py`
   - 价值：股票池范围、特殊数据筛选、形态扫描、保存结果、导出股票池组成一条完整选股链路。
   - quant_yb 落地：保留 JSON 股票池规范，补充导入/导出工具和扫描结果转股票池功能。
   - 推荐命令：`python main.py stats pool-import --format qtyx|csv|blk`、`python main.py stats pool-export --format csv|blk`、`python main.py stats pool-from-signals ...`。

5. Dashboard 组织方式
   - QTYX 价值：把“当前市场、股票池、策略、选股结果、RPS、图表”集中在一个工作台。
   - quant_yb 落地：继续用 `visual/dashboard.py`，增加 RPS、形态扫描、最新买点、题材池和指数环境的卡片入口。
   - 不建议引入 wxPython。HTML dashboard 更符合当前项目的可分享、可自动生成方向。

### B 级：可以参考，但需要边界隔离

这些方向有价值，但依赖、数据口径或风险较高。

1. 多数据源适配
   - QTYX 覆盖新浪、东方财富、baostock、Tushare、问财等。
   - quant_yb 当前主行情应继续以 Tushare + 本地 CSV 为标准口径。
   - 可新增 `data/providers/` 实验适配层，先用于补充数据或特殊指标，不直接混入回测主行情。
   - 每个 provider 必须输出统一字段：`date,open,high,low,close,volume,amount`。

2. 北向、涨停、财务、问财等特色数据
   - QTYX 来源：`ApiData/SpecialData.py`
   - quant_yb 已有每日指标和题材看板，缺少北向/涨停/问财筛选。
   - 可优先引入“涨停明细”和“北向持股变化”作为题材看板辅助字段。
   - 不建议复制爬虫代码。应重新封装请求、缓存、失败重试和字段清洗。

3. 外部策略文件导入
   - QTYX 要求外部 `.py` 包含 `strategy_main` 和 `STRATEGY_CONFIG`。
   - quant_yb 目前按 `strategy/{name}.py` + `BaseStrategy` 类约定加载，更利于测试。
   - 可以参考“策略元数据”的思想，但不建议动态导入任意用户脚本参与回测。若要做，应先设计插件目录、沙箱边界和最小接口。

4. AI 提示词工作流
   - QTYX 已有 ETF 红绿灯、K 线预测、题材主线分析提示词。
   - quant_yb 可参考为报告增加“导出分析提示词”或“生成研究摘要”的功能。
   - 不能让 AI 输出反向改变策略信号或回测结果，只能作为解释层或研究辅助。

### C 级：暂不建议引入

1. QMT/同花顺/IBKR 实盘下单驱动
   - 涉及真实资金、Windows 环境、账户配置、外部程序状态。
   - quant_yb 当前没有实盘风控、订单状态机、账户持仓同步和交易审计链路。
   - 近期最多参考“测试模式、黑名单、持仓上限、邮件提醒”的产品思路，先做 watchlist/alert，不做下单。

2. wxPython GUI 架构
   - QTYX 的 GUI 功能丰富，但代码和业务耦合较高，很多中文字段、JSON 键和控件事件互相依赖。
   - quant_yb 已经形成 CLI + HTML 报告路线，迁移 GUI 会增加维护负担。

3. 直接复用 QTYX 配置文件
   - `ConfigFiles/sys_para.json`、`trade_para.json`、`token.txt`、`trade_pool.json` 可能含账号、token、路径、邮箱、FTP、交易配置。
   - 只可参考结构，不可复制真实值。

4. 直接复制 QTYX 源码
   - 多个源码文件头部写有“仅用于教学目的，严禁转发和用于盈利目的”等提示。
   - 即便只做个人项目，也建议只吸收算法思想，重新实现并保留测试。

## 分模块详细对比

### 1. 架构与边界

quant_yb 的边界更清楚：

- `cli/` 负责命令和 REPL。
- `data/` 负责下载、缓存、清洗。
- `strategy/` 负责 Backtrader 策略。
- `engine/runner.py` 负责回测执行、绩效和导出。
- `analysis/` 负责统计、指数、题材。
- `visual/` 负责 HTML 报告。

QTYX 的功能更多，但 GUI、配置、数据、策略、回测和交易逻辑交叉较多。它适合借鉴“用户实际会怎么用”，不适合作为 quant_yb 的架构模板。

建议：

- 保持 quant_yb 现有分层。
- QTYX 的形态、RPS、轮动统一先进入 `analysis/`，等口径稳定后再考虑进入 `strategy/` 或 `engine/`。
- 不改变现有 CSV 字段和输出路径，新增结果另放 `output/signals/` 或 `output/statistics/`。

### 2. 数据和缓存

quant_yb：

- 以 Tushare 为主。
- 股票日 K、指数日 K、股票基础信息和 daily_basic 分别缓存。
- 路径从 `config.yaml` 读取。
- 数据清洗有独立模块和测试。

QTYX：

- 数据源覆盖更广，包括新浪、东方财富、baostock、Tushare、问财、FTP 远程文件。
- 同时支持 CSV 和 SQLite。
- `ConfigFiles/`、`DataFiles/` 里沉淀了很多本地数据和映射文件。

参考建议：

- 参考 QTYX 的“数据类型覆盖清单”，不要替换 quant_yb 当前主行情链路。
- 若补特色数据，优先做可缓存、可重跑、字段清晰的接口。
- QTYX 的代码转换工具值得参考，但 quant_yb 应实现为纯函数并补测试，例如 `normalize_ts_code()`、`to_baostock_code()`、`detect_stock_or_etf()`。

### 3. 股票池与题材

quant_yb 已有题材股票池 JSON：

- 支持 `{"pools": {"机器人": {"stocks": [{"ts_code": "..."}]}}}`。
- 支持多池并集/交集。
- 题材看板能生成等权概念指数和广度指标。

QTYX 的股票池体验更完整：

- 交易池、ETF 池、自定义股票池、全市场、概念板块池、行业板块池。
- 支持导入、导出、删除、追加、通达信 `zxg.blk`。
- 选股结果可以再保存为股票池。

参考建议：

- 给 quant_yb 增加股票池工具命令，而不是引入 GUI。
- 支持从 QTYX `trade_pool.json` 只读导入，但不复制敏感配置。
- 支持从扫描结果生成新股票池，形成“扫描 -> 复核 -> 回测题材池”的闭环。

### 4. 择时策略

两边已有重叠：

| 策略 | quant_yb 当前 | QTYX 当前 | 参考价值 |
| --- | --- | --- | --- |
| 双均线 | 已有 | 外部 demo | 低 |
| MACD | 已有 | 已有 | 低 |
| KDJ | 已有 | 已有超买超卖和图表标记 | 中，参数和标记可参考 |
| 布林带 | 已有 | 已有 | 低 |
| RSI | 已有 | 形态组合里使用 | 低 |
| N 日突破 | 暂无独立策略 | 已有 | 中，适合新增唐奇安/ATR 变体 |
| ATR 止盈止损 | 多周期策略里有 ATR 止损思想 | 已有 N 日突破 + ATR | 中 |
| 双 KAMA | 暂无 | 已有 | 中，可作为趋势策略补充 |

重要差异：

- QTYX 多数回测策略在 DataFrame 里 `Signal.shift(1)`，减少当日信号当日成交的问题。
- quant_yb 通过 Backtrader 的逐 bar 策略和基类交易约束统一处理成交、费用和 T+1，更适合严肃回测。

建议：

- 若新增 N 日突破、ATR 止盈止损、双 KAMA，必须重写为 `BaseStrategy` 子类。
- 策略里的历史窗口应明确排除当日基准，沿用 `volume_platform_breakout` 的做法。
- 不把 QTYX 的 `Signal` 批处理直接作为交易流水来源。

### 5. 形态选股

QTYX 形态库是最值得参考的部分：

- 底部盘整突破：双底突破 + 箱体突破。
- 主升浪启动：均线多头、突破前高、动量和成交量评分。
- 单针探底回升。
- 六脉神剑：均线、前高、成交量、MACD、KDJ、RSI 六条件共振。
- 杯柄形态。
- 头肩底形态。
- 相似度形态。

落地建议：

- 第一阶段只做扫描，不做回测策略。
- 输入统一用 quant_yb 缓存字段：`date,open,high,low,close,volume,amount,pct_chg`。
- 输出包含：`symbol,name,pattern,signal_date,score,close,reason,params`。
- 每个形态函数都返回结构化诊断，方便 HTML 报告解释。

未来函数注意：

- 双底/箱体/突破类基准必须用今天之前的窗口。
- QTYX 的部分实现使用当前日高点参与 N 日高点判断，迁移时要改成 `shift(1)` 或显式历史窗口。
- 杯柄和头肩底使用整段窗口定位形态，必须检查“当前日扫描”时是否只用了已发生数据。

### 6. RPS 强度

QTYX 的 RPS 当前实现比较粗糙：

- 只截取了前 100 只股票的样例逻辑。
- 使用本地 `DataFiles/stock_history`。
- 以 rolling 平均涨跌幅生成排名。

但产品方向很有价值：

- 每日 Top N 强势股。
- 个股历史 RPS 排名跟踪。
- RPS 动画/竞赛展示。

quant_yb 更适合实现可靠版本：

- 使用完整本地缓存。
- 支持窗口：20、60、120、250。
- 支持剔除上市未满 N 日股票。
- 支持按全市场、题材池、指数成分池排名。
- 报告层展示 Top N、行业/题材分布、个股 RPS 曲线。

### 7. 轮动策略

QTYX 的轮动策略有两个方向：

- 动量轮动：过去 N 日收益排名，持有 Top K。
- 三因子轮动：趋势、动量、成交量综合得分。

它们对 quant_yb 的意义很大，因为当前 quant_yb 以单标的策略为主。

但落地要分两步：

1. 研究型组合回测：
   - 自定义 pandas 组合引擎。
   - 每日按因子打分。
   - 按交易日换仓。
   - 输出组合净值、持仓、换仓、费用估算。

2. 事件驱动组合回测：
   - 再评估是否扩展 Backtrader 多数据 feed。
   - 需要重新定义批量汇总、交易流水和权益曲线口径。

不要直接改 `BacktestRunner.run_batch()`，否则会破坏当前单标的批量回测语义。

### 8. 报告和图表

QTYX 的图表能力：

- K 线、成交量、均线、MACD、KDJ、布林带、跳空、黄金分割、K 线形态标记。
- 回测资金曲线、相对收益、最大回撤、交易区间。
- RPS 动画和多图布局。

quant_yb 已有：

- 单标的 HTML 回测报告。
- 日/周/月 K 线切换。
- 指数概览和大盘环境。
- 题材看板。
- dashboard 总入口。

参考建议：

- 增加“信号标记层”：买点、形态、RPS 强度、突破位、止损位可以作为 overlays 进入现有 ECharts payload。
- dashboard 增加最新 RPS、最新形态、最新买点和题材池信号。
- 不引入 matplotlib GUI 图表作为主路径。

### 9. 实盘扫描和交易

QTYX 的实盘扫描逻辑包括：

- QMT/同花顺连接。
- 持仓、资产、可用资金、委托状态检查。
- 多账户。
- 黑名单。
- 止盈、止损、回撤止盈、阶梯止盈止损。
- 邮件提醒。
- 测试模式。

quant_yb 当前不应引入真实下单。

建议：

- 先做“盘后扫描”和“watchlist/alert”。
- 可以参考 QTYX 的风控清单，设计只读提醒字段。
- 若未来引入交易，应单独建 `execution/` 或 `broker/` 边界，并先完成模拟账户、订单状态机和审计日志。

### 10. AI 辅助

QTYX 的 AI 菜单是提示词工作流，不是模型自动决策：

- ETF 红绿灯分析提示词。
- K 线走势预测提示词。
- 题材主线分析提示词。

quant_yb 可参考：

- 在 HTML 报告里增加“复制研究摘要/提示词”的按钮。
- 给题材看板生成结构化 prompt。
- 给指数预测报告生成“解释当前信号”的文本材料。

约束：

- AI 输出不能反向参与策略信号。
- 报告必须标注数据源、日期范围和指标口径。

### 11. 工程、依赖和风险

QTYX 风险点：

- 没有标准测试套件。
- requirements 不完整或有不规范项，代码还引用 `talib`、`easytrader`、`scipy`、`tqdm` 等。
- 交易驱动和 Windows `.pyd` 依赖难在 macOS 验证。
- `ConfigFiles/` 可能含 token、邮箱、FTP、账户和本机路径。
- 大量中文列名和 GUI 控件强耦合。

quant_yb 应坚持：

- 新功能先写契约和单元测试。
- 所有路径从 `config.yaml` 读取。
- 不把真实 token、账号、路径写入文档。
- 不改变现有回测输出 CSV 字段。
- 对形态和轮动先做研究输出，再进入交易策略。

## 推荐实施路线

### 第一阶段：低风险增强

目标：不改回测引擎，不改变现有输出契约。

1. 新增代码格式工具测试
   - 参考 QTYX `CodeConvert`，实现纯函数。
   - 目标文件：`data/code_utils.py` 或 `data/metadata.py`。
   - 测试：代码格式转换、ETF/股票识别、异常输入。

2. 新增 RPS 分析
   - 目标文件：`analysis/rps.py`、`cli/stats_cli.py`、`visual` 或 `analysis/report`。
   - 输出 Top N 和个股轨迹。
   - dashboard 增加入口。

3. 新增形态扫描第一批
   - 先做 `main_rise_wave`、`bottom_pattern_break`、`needle_bottom_raise`。
   - 每个形态有独立测试和未来函数测试。
   - 输出到 `output/signals/`。

4. 股票池导入/导出
   - 支持 CSV、QTYX trade_pool 只读导入、通达信 blk 导出。
   - 不读取 QTYX 敏感字段。

### 第二阶段：研究型组合和可视化

目标：补齐全市场和题材池研究能力。

1. 轮动研究模块
   - 动量轮动。
   - 三因子轮动。
   - 组合净值、换仓日志、持仓明细。

2. 信号中心 dashboard
   - 最新买点。
   - 最新形态。
   - 最新 RPS Top。
   - 题材池强弱。
   - 指数环境。

3. 报告 overlays
   - 在单标的报告上叠加形态点、突破位、RPS 轨迹。

### 第三阶段：外部数据和提醒

目标：补充研究维度，不改变主行情口径。

1. 北向/涨停/问财数据适配
   - 独立缓存和失败重试。
   - 可用于题材分析和股票池筛选。

2. 盘后提醒
   - 邮件或本地文件提醒。
   - 不做真实下单。

3. AI 辅助摘要
   - 输出 prompt 或报告摘要。
   - 严格保持解释层定位。

## 优先级建议表

| 优先级 | 参考点 | 原因 | 风险 | 建议落点 |
| --- | --- | --- | --- | --- |
| P0 | RPS Top N 和个股轨迹 | 与全市场扫描和题材强弱高度互补 | 低 | `analysis/rps.py` |
| P0 | 主升浪、底部突破、单针探底扫描 | 直接提升选股能力 | 中，需防未来函数 | `analysis/patterns.py` |
| P1 | 股票池导入/导出/结果转池 | 串起扫描和回测闭环 | 低 | `data/stock_pool.py`、`cli/stats_cli.py` |
| P1 | dashboard 信号中心 | 提升日常使用效率 | 低 | `visual/dashboard.py` |
| P2 | 动量/三因子轮动研究 | 扩展到组合层面 | 中高，口径需新定义 | `analysis/rotation.py` |
| P2 | 多数据源特色数据 | 丰富题材和筛选 | 中，接口不稳定 | `data/providers/` |
| P3 | 外部策略插件 | 灵活但难控 | 高 | 暂缓 |
| P3 | 实盘交易驱动 | 真实资金风险 | 很高 | 暂缓 |

## 不建议照搬的内容

- wxPython 主界面和控件事件结构。
- `TradeDrv/` 下的 QMT、同花顺、IBKR 驱动。
- `ConfigFiles/*.json` 的真实内容。
- `DataFiles/` 的本地数据。
- 没有测试保护的回测计算方式。
- 直接动态导入任意外部策略文件参与资金回测。
- 带有教学/传播限制声明的源码实现。

## 对 quant_yb 的具体落地原则

1. 保持现有主线：
   - Tushare 缓存为主数据源。
   - Backtrader 继续负责交易策略回测。
   - HTML 报告继续作为主要展示。
   - 现有 CSV 字段和命令不变。

2. 新增能力先放在研究层：
   - RPS、形态、轮动先输出研究结果。
   - 只有经过单元测试和样例验证后，再考虑进入交易策略。

3. 每个扫描器都要有结构化诊断：
   - 不只输出“命中”，还输出“为什么命中”。
   - 报告层只解释信号，不影响信号。

4. 严格防未来函数：
   - 突破基准用历史窗口。
   - 周期排名用当日之前或收盘后已知数据。
   - 组合轮动明确下一交易日成交假设。

5. 保持可验证：
   - 新增测试。
   - 文档写明数据源、日期范围、手续费/滑点假设。
   - 大批量命令前保留单标的或小池验证命令。

