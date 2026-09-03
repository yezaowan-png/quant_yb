# GitHub 量化与金融分析项目参考清单

> 调研日期：2026-06-13  
> 目标：筛选 GitHub 上对当前 A 股量化回测项目有实际借鉴价值的量化、金融分析、市场分析、AI 金融研究项目，并给出可落地的改进方向。

## 1. 筛选标准

本清单不只按 star 排序，而按当前项目的改进价值筛选。

当前项目特点：

- A 股日 K 数据为主。
- 使用 Tushare 下载和本地 CSV 缓存。
- 使用 Backtrader 做事件驱动回测。
- 已有策略、买点扫描、单标的报告、策略画像、指数概览和 dashboard。
- 未来方向包括多周期策略、决策留痕、风险审查、AI 解读、组合级管理。

筛选标准：

- 是否能启发当前项目的数据层、策略层、回测层、报告层或研究流程。
- 是否有成熟工程结构可参考。
- 是否和 A 股研究场景接近。
- 是否值得“借鉴思想”，而不是直接复制代码。
- 是否存在许可证或依赖风险。

## 2. 高优先级参考项目

## 2.1 Microsoft Qlib

项目：

- GitHub: https://github.com/microsoft/qlib
- 定位：AI-oriented Quant investment platform
- 语言：Python
- 许可证：MIT
- 规模：约 44k stars、7k forks

### 核心价值

Qlib 是最值得重点研究的项目之一。它覆盖完整量化研究链路：

```text
数据处理 -> 特征/因子 -> 模型训练 -> 回测 -> 风险建模 -> 组合优化 -> 订单执行 -> 分析
```

它强调模块松耦合，每个组件可以单独使用，也可以组合成完整研究工作流。Qlib 还支持 supervised learning、market dynamics modeling、reinforcement learning，并有中国市场数据路径和 1min 数据支持。

### 当前项目可借鉴点

1. **研究工作流标准化**

当前项目更偏“命令式跑策略”。可以借鉴 Qlib，把研究过程标准化成：

```text
数据集定义 -> 策略/因子定义 -> 回测任务 -> 分析报告 -> 实验记录
```

建议后续新增：

```text
experiments/
    {experiment_id}.yaml
output/experiments/
    {experiment_id}/
```

2. **实验配置化**

把策略参数、标的池、时间范围、基准、成本模型写进 YAML，而不是只靠 CLI 参数。

3. **因子/特征层**

当前策略指标都写在策略类中。后续可抽出：

```text
features/
    technical.py
    volume_price.py
    market_state.py
```

4. **模型研究预留**

即使短期不做机器学习，也可以预留 `features + labels + experiment` 的结构，方便以后做多因子或信号评分。

### 不建议直接搬的点

- 不建议直接引入 Qlib 作为主引擎，体量太大。
- 不建议马上做 ML 模型训练，当前项目更需要稳固数据、回测和复盘链路。

### 建议优先级

高。重点借鉴“研究工作流、实验管理、特征层、模型/策略/回测解耦”。

## 2.2 RQAlpha

项目：

- GitHub: https://github.com/ricequant/rqalpha
- 定位：A 股/多证券程序化回测与交易框架
- 语言：Python
- 规模：约 6.5k stars、1.8k forks

### 核心价值

RQAlpha 是中文量化生态里非常值得参考的项目。它从数据获取、算法交易、回测引擎、模拟交易、实盘交易到数据分析提供全套解决方案，并且有清晰的 Mod 扩展机制。

官方 README 中列出的 Mod 很值得当前项目参考：

- `sys_accounts`：账户、下单、持仓模型
- `sys_analyser`：记录订单、成交、组合、持仓，计算风险指标并输出 CSV/图表
- `sys_risk`：事前风控校验
- `sys_scheduler`：定时任务
- `sys_transaction_cost`：交易税费

### 当前项目可借鉴点

1. **Mod 插件思想**

当前项目功能逐渐变多：指数、dashboard、decision memory、风险审查。可以借鉴 RQAlpha 的 Mod 思想，把扩展功能分层：

```text
core: 数据、回测、策略
mods:
    analyser
    risk_review
    decision_memory
    dashboard
```

2. **事前风控模块**

当前 `BaseStrategy` 已有涨跌停、T+1、成交量限制。后续可以抽出统一风险检查器：

```text
risk/checks.py
    check_limit_up
    check_limit_down
    check_volume_cap
    check_max_position
    check_market_regime
```

3. **分析器输出标准化**

当前策略画像和单标的报告已经有基础。可以进一步统一订单、成交、持仓、权益、风险指标输出。

### 不建议直接搬的点

- RQAlpha 的数据和交易生态与本项目 Tushare + Backtrader 已有结构不同，不建议重构替换。
- 商业使用限制需注意，借鉴架构思想即可。

### 建议优先级

高。重点借鉴“Mod 扩展、事前风控、分析器标准输出”。

## 2.3 Backtrader

项目：

- GitHub: https://github.com/mementum/backtrader
- 定位：Python trading strategy backtesting library
- 语言：Python
- 许可证：GPL-3.0
- 规模：约 22k stars、5.1k forks

### 核心价值

当前项目已经使用 Backtrader。需要继续深入利用它，而不是只用最基础的单数据 feed。

Backtrader 支持：

- 多数据 feed
- 多时间周期
- resampling/replaying
- 自定义指标
- analyzers
- 多种订单类型：Market、Close、Limit、Stop、StopLimit、StopTrail 等
- broker 模拟、滑点、佣金、sizer

### 当前项目可借鉴点

1. **多周期策略支持**

当前多周期策略文档已经有两个：

- `../strategies/WYCKOFF_TRIPLE_SCREEN.md`
- `../strategies/MULTI_TIMEFRAME_VOLUME_TREND.md`

后续应优先研究 Backtrader 的 `resampledata` 和多 feed 支持，实现：

```text
日线 feed + 周线 feed
日线 feed + 小时线 feed
```

2. **订单类型增强**

当前策略多是“信号收盘买/卖”。后续可支持：

- Stop 订单
- StopTrail 移动止损
- Bracket order
- 分批止盈

3. **Sizer**

当前 `BaseStrategy` 默认 95% 可用资金买入。可借鉴 Backtrader Sizer 思路，实现：

```text
fixed_cash
fixed_percent
risk_per_trade
atr_risk
```

### 不建议直接改的点

- 不要一次性把所有订单模型重写。
- 先扩展一个策略使用 ATR 风险仓位，再考虑通用化。

### 建议优先级

最高。因为项目已经依赖 Backtrader，深入使用它收益最大。

## 2.4 vectorbt

项目：

- GitHub: https://github.com/polakowo/vectorbt
- 定位：高速向量化回测与策略研究
- 语言：Python
- 规模：约 7.9k stars、1k forks
- 许可证：Apache 2.0 with Commons Clause，注意商业限制

### 核心价值

vectorbt 的关键思想是“矩阵化研究”：把大量参数组合、多个资产、多个时间窗口打包成 NumPy 数组并行计算。它适合快速探索策略参数，而不是模拟真实订单细节。

它的 README 强调：

- 大规模参数搜索
- 多资产广播
- trade/drawdown/performance analytics
- walk-forward optimization
- 交互式 Plotly 可视化

### 当前项目可借鉴点

1. **研究模式与回测模式分离**

当前项目所有策略都走 Backtrader，比较慢。可以新增一个轻量研究层：

```text
research/
    vectorized_signals.py
    parameter_grid.py
```

用途：

- 快速测试均线、RSI、MACD 参数组合。
- 先找到有潜力的参数范围，再交给 Backtrader 做事件驱动复核。

2. **参数热力图**

可在策略统计报告里加入：

```text
fast_ma x slow_ma -> total_return / sharpe / max_dd
```

3. **walk-forward 思想**

不是只做全样本最优，而是：

```text
训练窗口 -> 测试窗口 -> 滚动前进
```

### 不建议直接搬的点

- 不建议替换 Backtrader。vectorbt 不适合模拟 A 股 T+1、涨跌停、成交量上限这类细节。
- 许可证有 Commons Clause，商业场景需谨慎。

### 建议优先级

高。适合作为“研究加速器”，不是主回测引擎。

## 2.5 QuantStats

项目：

- GitHub: https://github.com/ranaroussi/quantstats
- 定位：Portfolio analytics for quants
- 语言：Python
- 许可证：Apache-2.0
- 规模：约 7.3k stars、1.2k forks

### 核心价值

QuantStats 专注绩效分析和报告：

- `quantstats.stats`：Sharpe、胜率、波动等指标
- `quantstats.plots`：回撤、滚动统计、月度收益等图
- `quantstats.reports`：生成 HTML tear sheet
- 新版本还提供 Monte Carlo 风险模拟

### 当前项目可借鉴点

1. **策略报告指标补全**

当前项目已有收益、夏普、回撤、胜率等。可继续补：

- Calmar
- Sortino
- Omega
- Profit Factor
- 月度收益热力图
- rolling Sharpe
- underwater drawdown chart

2. **Monte Carlo 风险分析**

对交易收益序列做重采样，估计：

- 爆仓/大回撤概率
- 达到目标收益概率
- 收益路径分布

3. **统一 tear sheet**

当前报告分散：单标的报告、策略画像、dashboard。可以新增：

```text
output/statistics/tearsheet_{strategy}.html
```

### 不建议直接搬的点

- 当前报告系统已经自研 ECharts，不一定需要引入 QuantStats 依赖。
- 可以先借鉴指标和布局，再决定是否引入库。

### 建议优先级

高。对当前可视化和统计分析提升直接。

## 2.6 AKShare

项目：

- GitHub: https://github.com/akfamily/akshare
- 定位：开源财经数据接口库
- 语言：Python
- 许可证：MIT
- 规模：约 20.3k stars、3.3k forks

### 核心价值

AKShare 是中文金融数据生态中非常实用的数据接口库，覆盖股票、债券、基金、期货、宏观、指数、经济数据等大量公开数据源。

### 当前项目可借鉴点

1. **作为 Tushare 的补充数据源**

当前项目高度依赖 Tushare。可增加 provider 抽象：

```text
data/providers/
    tushare_provider.py
    akshare_provider.py
```

用途：

- Tushare 接口失败时 fallback。
- 补充行业、板块、宏观、资金流、估值数据。
- 获取一些 Tushare 积分不足的数据。

2. **指数和宏观数据增强**

当前已做指数概览。后续可加入：

- 申万行业指数
- 中证行业指数
- 北向资金
- 融资融券
- 宏观利率/货币数据

3. **数据质量提示**

AKShare README 明确提示数据仅供研究、接口可能变动。当前项目也应在数据源层记录：

```text
source
fetched_at
api_status
```

### 不建议直接搬的点

- 不要把所有数据接口一次性接入。
- 先从指数/行业/宏观三个对策略判断最有用的方向开始。

### 建议优先级

高。尤其适合增强市场环境分析。

## 3. 中高优先级参考项目

## 3.1 OpenBB

项目：

- GitHub: https://github.com/OpenBB-finance/OpenBB
- 定位：Financial data platform for analysts, quants and AI agents
- 语言：Python
- 规模：约 69k stars、7k forks

### 核心价值

OpenBB 的核心思想是“connect once, consume everywhere”：

```text
数据接入一次 -> Python / UI / Excel / API / AI Agent 多处消费
```

它提供 Python 包、API server、Workspace、AI agent 接入方式。

### 当前项目可借鉴点

1. **数据统一服务层**

当前项目是 CLI 直接读写 CSV。后续可以考虑轻量 API：

```text
python main.py serve
```

提供：

- 本地缓存数据查询
- 策略结果查询
- dashboard 数据接口

2. **AI agent 数据接口**

如果后续做 AI 解读层，不要让 AI 自己乱读文件。可以提供稳定接口：

```text
get_symbol_summary(symbol)
get_strategy_stats(strategy)
get_index_environment()
```

3. **Excel/外部工具友好**

当前输出 CSV 已经不错。后续可以再加：

```text
output/export/
    strategy_summary.xlsx
    signals.xlsx
```

### 不建议直接搬的点

- OpenBB 体量大，不适合作为当前项目依赖。
- 数据源偏全球市场，A 股特色仍需 Tushare/AKShare。

### 建议优先级

中高。重点借鉴“统一数据接口”和“AI agent 友好数据层”。

## 3.2 vn.py

项目：

- GitHub: https://github.com/vnpy/vnpy
- 定位：基于 Python 的开源量化交易平台开发框架
- 语言：Python
- 许可证：MIT
- 规模：约 41.6k stars、11.9k forks

### 核心价值

vn.py 更偏实盘交易平台和交易接口生态，适合学习工程化交易系统架构。

### 当前项目可借鉴点

1. **事件驱动交易平台结构**

虽然当前项目不是实盘系统，但后续如果要接实盘或模拟交易，可借鉴：

```text
event engine
gateway
app
strategy
risk
data recorder
```

2. **代码质量要求**

vn.py 明确使用 `ruff` 和 `mypy`。当前项目还没有格式化/静态检查配置，后续可加：

```text
ruff
mypy
pre-commit
```

3. **实盘前的模拟架构**

如果未来要做实盘，不建议直接让当前回测项目接券商。应该先加 paper trading / dry run 层。

### 不建议直接搬的点

- 不建议现在引入 vn.py 依赖；当前项目还处于研究与回测阶段。
- 实盘接口复杂度高，会分散策略研究重点。

### 建议优先级

中高。适合未来实盘化阶段参考。

## 3.3 Riskfolio-Lib

项目：

- GitHub: https://github.com/dcajasn/Riskfolio-Lib
- 定位：Portfolio Optimization in Python
- 语言：Python
- 许可证：BSD-3-Clause
- 规模：约 4.3k stars、673 forks

### 核心价值

Riskfolio-Lib 覆盖非常丰富的组合优化模型：

- Mean-Risk
- Kelly
- 多种 convex risk measures
- CVaR / EVaR / CDaR / Max Drawdown
- Risk Parity
- HRP / HERC
- Black-Litterman
- 约束、风险贡献、有效前沿、Excel/Jupyter 报告

### 当前项目可借鉴点

1. **组合层从“单策略单标的”升级**

当前项目主要统计单标的回测。后续可以加入：

```text
portfolio/
    allocator.py
    risk_parity.py
    equal_weight.py
```

2. **信号组合**

买点扫描输出很多股票后，需要决定买哪些、买多少。可先做简单版本：

```text
等权
波动率倒数加权
风险平价
最大单股权重限制
```

3. **风险贡献报告**

dashboard 增加：

- 每个持仓风险贡献
- 行业风险贡献
- 策略风险贡献

### 不建议直接搬的点

- 不要一开始上复杂优化器。
- A 股股票池大，优化器约束多时可能慢，先用简单组合规则。

### 建议优先级

中高。等决策留痕和风险审查完成后再做。

## 3.4 PyPortfolioOpt

项目：

- GitHub: https://github.com/PyPortfolio/PyPortfolioOpt
- 定位：Financial portfolio optimisation in Python
- 语言：Python/Jupyter
- 许可证：MIT
- 规模：约 5.8k stars、1.1k forks

### 核心价值

PyPortfolioOpt 提供更轻量的组合优化工具：

- Efficient Frontier
- Black-Litterman
- Hierarchical Risk Parity
- 协方差估计
- 组合管理

### 当前项目可借鉴点

相比 Riskfolio-Lib，PyPortfolioOpt 更适合做第一版组合优化：

```text
输入：候选股票收益率矩阵
输出：目标权重
约束：单股最大权重、总权重=1
```

### 建议优先级

中。可作为组合优化第一步，Riskfolio-Lib 作为更复杂版本。

## 3.5 FinRL-X / FinRL-Trading

项目：

- GitHub: https://github.com/AI4Finance-Foundation/FinRL-Trading
- 定位：AI-Native Modular Infrastructure for Quantitative Trading
- 语言：Python
- 规模：约 3.3k stars、1k forks

### 核心价值

FinRL-X 的核心设计非常值得借鉴：**weight-centric interface**。

它把策略输出统一成目标权重：

```text
stock selection -> allocation -> timing -> risk overlay -> target weights -> backtest/live execution
```

所有模块通过 `target portfolio weights` 连接，策略逻辑与执行逻辑解耦。

### 当前项目可借鉴点

1. **从买卖信号升级到目标权重**

当前策略输出买/卖。后续组合层可以统一成：

```text
signal -> score -> target_weight
```

2. **风险 overlay**

把市场环境、指数状态、组合风险作为最后一层调整：

```text
raw_weight -> risk_adjusted_weight
```

3. **研究和实盘一致**

即使不接实盘，也可以保证：

```text
回测用的权重逻辑 == 模拟交易用的权重逻辑
```

### 不建议直接搬的点

- 不建议一开始做 RL。
- 当前项目先把 rule-based 策略统一成 target weight 即可。

### 建议优先级

中高。适合作为长期架构方向。

## 4. 特定场景参考项目

## 4.1 QuantConnect Lean

项目：

- GitHub: https://github.com/QuantConnect/Lean
- 定位：Lean Algorithmic Trading Engine by QuantConnect
- 语言：C#，支持 Python 策略
- 许可证：Apache-2.0
- 规模：约 19.8k stars、4.9k forks

### 核心价值

Lean 是生产级多资产算法交易引擎，覆盖股票、期权、期货、外汇、加密等，工程复杂度高。

### 当前项目可借鉴点

- 证券类型抽象
- 订单模型和撮合模型
- 算法生命周期
- 研究/回测/实盘统一
- 数据订阅与交易日历

### 不建议直接搬的点

- 技术栈是 C# 为主，和当前 Python 项目不匹配。
- 体量过大，不适合作为直接依赖。

### 建议优先级

中。主要作为长期工程设计参考。

## 4.2 Freqtrade

项目：

- GitHub: https://github.com/freqtrade/freqtrade
- 定位：开源加密货币交易机器人
- 语言：Python
- 许可证：GPL-3.0
- 规模：约 51.4k stars、10.7k forks

### 核心价值

虽然它是加密货币交易机器人，但有几个工程能力非常值得借鉴：

- dry-run 模拟交易
- WebUI
- Telegram 控制
- backtesting
- hyperopt 参数优化
- backtesting-analysis
- lookahead-analysis
- recursive-analysis
- FreqAI 自训练模型

### 当前项目可借鉴点

1. **lookahead-analysis**

当前项目有未来函数要求，但没有自动检测工具。可以做一个轻量检查：

```text
python main.py audit lookahead --strategy xxx
```

检查：

- rolling 是否包含当前 bar 做边界
- 扫描买点是否使用未来窗口
- 报告层是否反向影响信号

2. **dry-run / paper trading**

未来可新增：

```text
python main.py paper run --strategy xxx
```

只记录模拟订单，不实盘。

3. **任务命令体系**

Freqtrade CLI 很丰富。当前项目也可以按功能继续整理：

```text
data
backtest
scan
stats
decision
dashboard
audit
portfolio
```

### 不建议直接搬的点

- 不适合 A 股数据和交易约束。
- GPL-3.0，复制代码需谨慎。

### 建议优先级

中。重点借鉴“lookahead-analysis、dry-run、CLI 工具化”。

## 4.3 Zipline

项目：

- GitHub: https://github.com/quantopian/zipline
- 定位：Pythonic algorithmic trading library
- 语言：Python
- 许可证：Apache-2.0
- 规模：约 19.9k stars、5k forks
- 状态：原 Quantopian 项目，最新 release 较老

### 核心价值

Zipline 曾是 Quantopian 的事件驱动回测引擎，强调：

- 易用 API
- Pandas 集成
- algorithm lifecycle
- history/data.current/order_target/record 等接口

### 当前项目可借鉴点

- `record()` 思想：策略运行中记录关键变量供后续分析。
- `order_target()` 思想：用目标仓位而不是单纯 buy/sell。
- 回测输出 performance DataFrame。

### 不建议直接搬的点

- 项目本身维护状态较老。
- 当前项目已有 Backtrader，不建议替换。

### 建议优先级

中低。借鉴 API 设计，不引入依赖。

## 4.4 FinRL-Meta

项目：

- GitHub: https://github.com/AI4Finance-Foundation/FinRL-Meta
- 定位：金融强化学习市场环境与 benchmark
- 语言：Python/Jupyter
- 规模：约 1.9k stars、748 forks

### 核心价值

FinRL-Meta 强调 data-centric market environments，用于金融强化学习环境构建和 benchmark。

### 当前项目可借鉴点

- 把市场环境封装成标准接口。
- 为策略提供 benchmark。
- 对动态数据、幸存者偏差、噪声和过拟合保持警惕。

### 建议优先级

中低。当前不建议做 RL，但可借鉴 benchmark 和环境抽象。

## 5. AI 金融分析参考项目

## 5.1 TradingAgents

项目：

- GitHub: https://github.com/TauricResearch/TradingAgents
- 定位：Multi-Agents LLM Financial Trading Framework
- 语言：Python
- 许可证：Apache-2.0
- 规模：约 85.6k stars、16.5k forks

### 核心价值

TradingAgents 把金融交易研究拆成多角色：

- Fundamentals Analyst
- Sentiment Analyst
- News Analyst
- Technical Analyst
- Bull/Bear Researcher
- Trader Agent
- Risk Management
- Portfolio Manager

它明确声明是研究用途，不构成投资建议，且 LLM 结果存在非确定性。

### 当前项目可借鉴点

前面已单独写入：

```text
docs/plans/TRADINGAGENTS_INTEGRATION_PLAN.md
```

核心借鉴：

- 决策留痕
- 风险审查
- 多角色解释
- Portfolio Manager veto
- 事后复盘

### 不建议直接搬的点

- 不让 LLM 直接决定买卖。
- 不用多 agent 取代明确策略规则。

### 建议优先级

高，但应按已有计划分阶段做。

## 5.2 FinGPT

项目：

- GitHub: https://github.com/AI4Finance-Foundation/FinGPT
- 定位：Open-source financial large language models
- 语言：Python/Jupyter
- 许可证：MIT
- 规模：约 20.5k stars、2.9k forks

### 核心价值

FinGPT 关注金融大模型、金融情绪分析、新闻分析、金融实体/关系抽取、预测解释等。它强调金融数据动态更新和低成本微调。

### 当前项目可借鉴点

1. **情绪/新闻特征作为外部解释层**

未来可以给 decision memory 增加：

```text
news_sentiment
policy_sentiment
sector_news_summary
```

2. **AI 解读报告**

不是用 AI 生成交易信号，而是用 AI 解释：

- 为什么这个策略触发
- 当前指数环境如何
- 新闻/公告是否有风险
- 同类历史信号表现如何

3. **中文金融问答/分类**

可用于后续本地知识库，比如解释财报、公告、宏观政策。

### 不建议直接搬的点

- 不建议自己训练金融大模型。
- 不建议用 LLM 预测短期价格作为交易信号。

### 建议优先级

中。等 decision memory 和 risk review 稳定后再接入。

## 6. 推荐改进路线

基于以上项目，建议当前项目按以下方向演进。

## 6.1 第一优先级：把现有 Backtrader 用深

参考：

- Backtrader
- RQAlpha
- Freqtrade

任务：

1. 多周期 feed：

```text
日线 + 周线
日线 + 小时线
```

2. 通用风险仓位：

```text
fixed_percent
risk_per_trade
atr_risk
```

3. 通用风险检查器：

```text
涨跌停
成交量上限
最大单股仓位
大盘弱势降级
```

4. lookahead audit：

```bash
python main.py audit lookahead --strategy xxx
```

## 6.2 第二优先级：建设研究与复盘层

参考：

- Qlib
- TradingAgents
- QuantStats

任务：

1. 实现 `TRADINGAGENTS_INTEGRATION_PLAN.md` 阶段 1 和 2：

```text
decision_memory.csv
未来 5/10/20 日收益
相对指数超额
```

2. 增加实验记录：

```text
output/experiments/{experiment_id}/
```

3. 增强策略画像：

```text
月度收益热力图
rolling Sharpe
underwater 回撤
Monte Carlo 风险
```

## 6.3 第三优先级：增强数据层

参考：

- AKShare
- OpenBB
- Qlib

任务：

1. 数据 provider 抽象：

```text
TushareProvider
AkshareProvider
LocalCsvProvider
```

2. 增加市场环境数据：

```text
行业指数
北向资金
融资融券
估值
宏观利率
成交额/换手
```

3. 增加数据元信息：

```text
source
fetched_at
rows
start
end
quality_warnings
```

## 6.4 第四优先级：组合级管理

参考：

- Riskfolio-Lib
- PyPortfolioOpt
- FinRL-X

任务：

1. 从“买点列表”升级为“候选组合”：

```text
signal_score -> target_weight
```

2. 基础组合方法：

```text
等权
波动率倒数
最大单股权重限制
行业权重限制
```

3. 后续组合优化：

```text
HRP
risk parity
CVaR
Black-Litterman
```

## 6.5 第五优先级：AI 解读，不做 AI 交易

参考：

- TradingAgents
- FinGPT
- OpenBB

任务：

1. 给 AI 稳定数据接口：

```text
get_symbol_context(symbol)
get_strategy_context(strategy)
get_index_context()
get_decision_memory(symbol, strategy)
```

2. 生成解释报告：

```text
信号解释
市场环境
风险点
历史同类信号表现
结论评级
```

3. 坚持原则：

```text
AI 只解释，不生成交易信号
```

## 7. 项目清单总表

| 项目 | 类型 | 当前项目借鉴价值 | 优先级 |
|---|---|---:|---|
| Backtrader | 回测引擎 | 多周期、订单、Sizer、Analyzer | 最高 |
| Qlib | AI 量化研究平台 | 实验管理、特征层、研究工作流 | 高 |
| RQAlpha | A 股/多证券回测框架 | Mod、风控、分析器、A 股语境 | 高 |
| vectorbt | 向量化研究 | 参数网格、热力图、快速研究 | 高 |
| QuantStats | 绩效分析 | tear sheet、Monte Carlo、报告指标 | 高 |
| AKShare | 中文金融数据 | Tushare 补充、行业/宏观/指数数据 | 高 |
| TradingAgents | AI 多角色研究 | 决策留痕、风险审查、解释层 | 高 |
| OpenBB | 金融数据平台 | 数据接口统一、AI/分析工具接口 | 中高 |
| vn.py | 实盘平台框架 | 事件引擎、gateway、代码质量 | 中高 |
| Riskfolio-Lib | 组合优化 | 风险贡献、HRP、CVaR、组合约束 | 中高 |
| PyPortfolioOpt | 轻量组合优化 | Efficient Frontier、HRP、Black-Litterman | 中 |
| FinRL-X | AI-native 交易架构 | target weight 合约、风险 overlay | 中高 |
| Freqtrade | 交易机器人 | dry-run、lookahead-analysis、hyperopt | 中 |
| Lean | 生产级交易引擎 | 多资产工程架构、订单模型 | 中 |
| Zipline | 事件回测历史项目 | record/order_target/performance DataFrame | 中低 |
| FinGPT | 金融大模型 | 情绪/新闻/公告解释层 | 中 |
| FinRL-Meta | RL 环境 | benchmark、环境抽象、数据偏差意识 | 中低 |

## 8. 建议近期落地任务

### 任务 A：多周期 Backtrader feed 试点

来源参考：Backtrader、Qlib。

目标：

- 支持日线 + 周线。
- 为 `MULTI_TIMEFRAME_VOLUME_TREND.md` 和 `WYCKOFF_TRIPLE_SCREEN.md` 做准备。

### 任务 B：decision memory 阶段 1-2

来源参考：TradingAgents。

目标：

- 记录信号。
- 自动计算未来收益和相对指数超额。
- dashboard 展示信号复盘。

### 任务 C：策略报告增强

来源参考：QuantStats。

目标：

- 月度收益热力图。
- 回撤持续期。
- rolling Sharpe。
- Profit Factor。
- Monte Carlo 风险。

### 任务 D：数据 provider 抽象

来源参考：AKShare、OpenBB。

目标：

- 不把 Tushare 写死在业务逻辑里。
- 支持后续 AKShare 补充数据。

### 任务 E：lookahead audit

来源参考：Freqtrade。

目标：

- 自动检查策略是否可能使用未来函数。
- 强化项目可信度。

## 9. 风险与注意事项

### 9.1 不要大而全重构

这些项目很强，但当前项目的优势是简单、可控、贴近 A 股日 K。不要把多个大型框架直接混进来。

### 9.2 注意许可证

需要特别注意：

- Backtrader：GPL-3.0
- Freqtrade：GPL-3.0
- vectorbt：Apache 2.0 with Commons Clause

建议只借鉴架构思想，不复制源码。

### 9.3 AI 只做解释层

TradingAgents 和 FinGPT 很有启发，但不能替代可复现策略。策略信号仍应来自明确规则、回测和复盘。

### 9.4 A 股约束优先

海外项目很多不考虑：

- T+1
- 涨跌停
- 100 股一手
- 停牌
- ST
- 幸存者偏差

所有借鉴都必须经过 A 股交易约束适配。

## 10. 后续调用建议

可以按下面方式让我继续执行：

```text
按照 GITHUB_QUANT_PROJECTS_REFERENCE.md，先实现任务 A：多周期 Backtrader feed 试点。
```

或：

```text
按照 GITHUB_QUANT_PROJECTS_REFERENCE.md，先实现任务 E：lookahead audit。
```

或：

```text
按照 GITHUB_QUANT_PROJECTS_REFERENCE.md，把 QuantStats 风格的指标补进策略画像报告。
```

建议先做顺序：

```text
1. decision memory 阶段 1-2
2. 多周期 Backtrader feed 试点
3. 策略报告增强
4. 数据 provider 抽象
5. lookahead audit
```

这样能最快提升当前项目的研究闭环质量。

## 11. 资料链接

- Microsoft Qlib: https://github.com/microsoft/qlib
- RQAlpha: https://github.com/ricequant/rqalpha
- Backtrader: https://github.com/mementum/backtrader
- vectorbt: https://github.com/polakowo/vectorbt
- QuantStats: https://github.com/ranaroussi/quantstats
- AKShare: https://github.com/akfamily/akshare
- OpenBB: https://github.com/OpenBB-finance/OpenBB
- vn.py: https://github.com/vnpy/vnpy
- Riskfolio-Lib: https://github.com/dcajasn/Riskfolio-Lib
- PyPortfolioOpt: https://github.com/PyPortfolio/PyPortfolioOpt
- FinRL-X / FinRL-Trading: https://github.com/AI4Finance-Foundation/FinRL-Trading
- FinRL-Meta: https://github.com/AI4Finance-Foundation/FinRL-Meta
- TradingAgents: https://github.com/TauricResearch/TradingAgents
- FinGPT: https://github.com/AI4Finance-Foundation/FinGPT
- QuantConnect Lean: https://github.com/QuantConnect/Lean
- Freqtrade: https://github.com/freqtrade/freqtrade
- Zipline: https://github.com/quantopian/zipline
