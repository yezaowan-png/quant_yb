# QuantYB 架构与数据面板改造计划

> 计划日期：2026-06-14  
> 依据：`GITHUB_QUANT_PROJECTS_REFERENCE.md`、当前代码结构、A 股回测可靠性要求  
> 目标：在不推倒现有 Backtrader + Tushare + 静态 HTML 报告体系的前提下，把项目从“能跑回测”升级为“能复盘、能比较、能解释、能扩展”的 A 股量化研究工作台。

## 1. 总体原则

1. **不大重构主链路**
   - 保留现有 `data -> strategy -> engine -> output -> visual/analysis` 主流程。
   - 不替换 Backtrader，不直接引入 Qlib、RQAlpha、vectorbt 等大型框架作为主依赖。
   - 参考这些项目的架构思想，优先做小步可验证改造。

2. **回测可信度优先**
   - 任何策略、扫描、报告改动都必须避免未来函数。
   - 涉及成交价格、手续费、滑点、涨跌停、成交量上限、T+1、绩效字段、CSV 字段时，需要明确影响范围。
   - 输出字段保持向后兼容；必须新增字段时，先让旧字段继续存在。

3. **研究闭环优先**
   - 当前项目已经能下载、回测、扫描、生成报告；下一步最有价值的是记录信号和自动复盘。
   - 优先实现 `decision memory`、策略 tear sheet、dashboard v2，而不是先做复杂 AI 或组合优化。

4. **A 股约束优先**
   - 海外项目常常不考虑 T+1、涨跌停、100 股一手、停牌、ST、幸存者偏差。
   - 所有借鉴都必须经过 A 股交易约束适配。

## 2. 分阶段路线图

### 阶段 0：基线保护与最小测试

参考项目：

- RQAlpha：分析器输出标准化
- Freqtrade：工具命令和回测结果可重复验证

目标：

- 先固定当前项目的核心契约，避免后续改动破坏已有命令和文件格式。

建议修改：

- 扩充 `tests/` 中的契约测试：
  - 策略文件命名与 loader 约定。
  - `.gitignore` 必须排除敏感配置和大规模输出。
  - `config.example.yaml` 中回测安全默认值保持存在。
  - 交易流水字段保持 `date,symbol,direction,price,size,commission,pnl`。
  - 权益曲线至少包含 `dates,equity,drawdowns`，允许新增现金、仓位等字段。
  - `_summary_{strategy}.csv` 必须保留核心统计字段。

候选文件：

- `tests/test_project_contracts.py`
- `engine/runner.py`
- `analysis/analyzer.py`
- `visual/report.py`

验证命令：

```bash
python -m unittest discover -s tests
python -m compileall main.py cli data engine strategy visual analysis
```

验收标准：

- 测试通过。
- 不生成大规模 `output/` 文件。
- 不需要 Tushare token。

### 阶段 1：Decision Memory 信号复盘层

参考项目：

- TradingAgents：决策留痕、风险审查、事后复盘
- Qlib：研究任务和实验记录
- QuantStats：用结果数据做绩效分析

目标：

- 把买点扫描和回测中产生的信号记录下来，后续自动计算未来 5/10/20 日表现和相对基准超额收益。
- 让 dashboard 能回答：“这个策略最近发出的信号，后面到底表现如何？”

建议新增目录：

```text
decision/
    __init__.py
    recorder.py
    evaluator.py
```

建议新增输出：

```text
output/decisions/decision_memory.csv
```

建议字段：

```text
signal_id
symbol
strategy
signal_date
signal_type
price
params_json
market_context_json
future_5d_return_pct
future_10d_return_pct
future_20d_return_pct
benchmark_5d_return_pct
benchmark_10d_return_pct
benchmark_20d_return_pct
excess_5d_return_pct
excess_10d_return_pct
excess_20d_return_pct
evaluated_at
```

候选命令：

```bash
python main.py decision record --strategy sma_cross --symbol 000001.SZ
python main.py decision evaluate --strategy sma_cross
python main.py decision report --strategy sma_cross
```

注意事项：

- 未来收益计算只能用于复盘，不能反向影响策略信号。
- 复盘窗口必须基于实际交易日，不用自然日粗略相减。
- 若未来数据不足，字段应为空并写明 `pending` 或 `insufficient_data`。

验收标准：

- 能基于本地缓存完成复盘，不需要联网。
- 能处理未来数据不足。
- dashboard 可以展示最近信号和已评估信号表现。

### 阶段 2：QuantStats 风格策略画像增强

参考项目：

- QuantStats：tear sheet、rolling statistics、drawdown analysis、Monte Carlo
- vectorbt：交互式绩效分析和参数研究可视化

目标：

- 把当前“策略画像”从简单分布统计升级成更完整的策略 tear sheet。

建议新增指标：

- Sortino Ratio
- Calmar Ratio
- Profit Factor
- 最大回撤持续天数
- 最长连续盈利/亏损次数
- 月度收益表
- rolling Sharpe
- underwater drawdown
- Monte Carlo 风险模拟

建议新增图表：

- 月度收益热力图
- rolling Sharpe 折线图
- underwater 回撤图
- trade pnl 分布图
- Monte Carlo 路径分布图

候选文件：

- `analysis/analyzer.py`
- `analysis/charts.py`
- `analysis/report.py`
- `engine/runner.py`

注意事项：

- 单标的报告和全市场策略画像的口径要一致。
- 核心收益、回撤、胜率等不要在报告层重新定义。
- 若指标依赖交易流水，则无交易股票需要显示为 `N/A` 或 0，并说明口径。

验收标准：

- `python main.py stats analyze --strategy rsi` 能生成增强报告。
- `python main.py stats compare` 能继续生成多策略对比。
- 旧字段和旧报告链接不失效。

### 阶段 3：多周期 Backtrader feed 试点

参考项目：

- Backtrader：多 data feed、resample/replay、analyzers、sizer
- RQAlpha：清晰的交易约束与分析器体系

目标：

- 先实现一个日线 + 周线策略试点，为后续 `WYCKOFF_TRIPLE_SCREEN.md` 和 `MULTI_TIMEFRAME_VOLUME_TREND.md` 做准备。

建议路线：

1. 在 `BacktestRunner.run()` 中支持可选多周期参数。
2. 先用 `cerebro.resampledata()` 从日线生成周线。
3. 新增一个独立策略，例如：

```text
strategy/multi_timeframe_volume_trend.py
```

4. CLI 增加多周期策略参数，但不要影响单周期策略。

注意事项：

- 周线信号只能在周线 bar 完成后使用，不能提前看到未来周内数据。
- 买卖仍走日线成交。
- 输出交易流水格式保持不变。

验收标准：

- 单周期策略原有命令继续可用。
- 多周期策略可跑单标的回测。
- 报告能展示日线成交点，并说明周线过滤条件。

### 阶段 4：Dashboard v2 研究总控面板

参考项目：

- OpenBB：connect once, consume everywhere
- QuantStats：绩效面板布局
- TradingAgents：决策留痕和风险提示

目标：

- 把现有 dashboard 从“HTML 报告导航页”升级为“研究总控面板”。

建议首页结构：

1. **市场温度**
   - 主要指数涨跌幅
   - 20 日波动率
   - 年初至今收益
   - 成交额状态

2. **数据健康**
   - 缓存覆盖股票数
   - 最新交易日
   - 指数缓存状态
   - 缺失/过期数据提示

3. **策略排行榜**
   - 平均收益
   - 交易股平均收益
   - 正收益比例
   - 夏普
   - 最大回撤

4. **近期信号与复盘**
   - 最近买点
   - 已评估信号未来收益
   - 策略信号胜率

5. **最近实验**
   - 最近运行的实验 ID
   - 策略、标的池、时间范围
   - 输出链接

6. **风险提示**
   - 幸存者偏差说明
   - 数据源时间范围
   - 未评估信号数量
   - 未来函数审计状态

候选文件：

- `visual/dashboard.py`
- `cli/dashboard_cli.py`
- `analysis/index_overview.py`
- `decision/evaluator.py`

验收标准：

- `python main.py dashboard` 能生成新的总控面板。
- 缺失数据时页面不报错，而是明确显示“待生成/缺失/未评估”。
- 页面链接仍能跳到指数报告、策略报告、单标的报告。

### 阶段 5：实验配置化

参考项目：

- Qlib：标准化研究工作流
- OpenBB：统一数据接口供多端消费

目标：

- 用 YAML 固化一次研究任务，让回测结果可复现、可归档、可比较。

建议新增目录：

```text
experiments/
    sma_cross_baseline.yaml
experiment/
    __init__.py
    runner.py
```

实验配置建议：

```yaml
id: sma_cross_baseline_20260614
strategy: sma_cross
symbols:
  - 000001.SZ
start: 20210101
end: 20231231
benchmark: 000300.SH
params:
  fast: 5
  slow: 20
cost:
  commission: 0.00025
  stamp_duty: 0.001
  slippage_perc: 0.001
```

候选命令：

```bash
python main.py experiment run experiments/sma_cross_baseline.yaml
```

输出建议：

```text
output/experiments/{experiment_id}/
    config.yaml
    summary.csv
    manifest.json
    reports/
```

验收标准：

- 相同实验配置可重复运行。
- manifest 能记录输入、输出、时间和运行状态。

### 阶段 6：数据 Provider 抽象

参考项目：

- AKShare：中文金融数据覆盖
- OpenBB：统一数据服务层
- Qlib：数据处理和特征层解耦

目标：

- 不把 Tushare 直接写死在业务逻辑里，为后续接 AKShare、Local CSV、行业/宏观数据留接口。

建议新增目录：

```text
data/providers/
    __init__.py
    base.py
    tushare_provider.py
    akshare_provider.py
    local_csv_provider.py
```

建议 provider 接口：

```text
get_daily(symbol, start, end)
get_index_daily(symbol, start, end)
get_stock_list()
get_metadata()
```

建议新增数据元信息：

```text
source
fetched_at
rows
start
end
quality_warnings
```

第一批增强数据：

- 申万行业指数
- 中证行业指数
- 北向资金
- 融资融券
- 估值
- 宏观利率

注意事项：

- 不一次性接入所有 AKShare 接口。
- 先保证 Tushare provider 与现有缓存行为兼容。
- AKShare 数据源需标注接口变动风险。

验收标准：

- 原 `data download` 命令继续可用。
- provider 可通过配置选择。
- 缓存仍保持原 CSV 兼容格式。

### 阶段 7：Lookahead Audit 未来函数审计

参考项目：

- Freqtrade：lookahead-analysis、recursive-analysis

目标：

- 自动检查策略和扫描过程是否存在明显未来函数风险。

建议新增目录：

```text
audit/
    __init__.py
    lookahead.py
```

候选命令：

```bash
python main.py audit lookahead --strategy sma_cross
```

第一版检查项：

- 策略代码是否出现明显正向索引读取，例如 `data.close[1]`。
- 平台突破、均量、区间高低点是否错误包含当前 bar 作为历史基准。
- 扫描买点是否基于实际交易日。
- 报告和统计结果是否被策略调用。

注意事项：

- 第一版审计可以是启发式检查，不宣称完全证明无未来函数。
- 对每条风险给出文件、行号和说明。

验收标准：

- 能对 `strategy/` 下所有策略给出审计结果。
- 不误改策略文件。
- 审计报告可输出到 `output/audit/`。

### 阶段 8：组合层与目标权重

参考项目：

- PyPortfolioOpt：组合优化
- Riskfolio-Lib：风险贡献
- FinRL-X：weight-centric interface

目标：

- 从“买点列表”升级为“候选组合 + 目标权重 + 风险约束”。

建议新增目录：

```text
portfolio/
    __init__.py
    allocator.py
    risk.py
```

第一版组合方法：

- 等权
- 波动率倒数
- 最大单股权重限制
- 行业权重限制
- 大盘弱势时降低总仓位

候选命令：

```bash
python main.py portfolio build --signals output/signals/buy_signals_sma_cross_YYYYMMDD.csv
```

输出建议：

```text
output/portfolio/target_weights_YYYYMMDD.csv
```

注意事项：

- 不在第一版引入复杂优化器。
- 输出目标权重不等于真实实盘建议，仅作为研究结果。

验收标准：

- 能从买点扫描结果生成候选组合。
- dashboard 能展示组合权重和风险集中度。

## 3. 推荐执行顺序

近期优先：

```text
阶段 0：基线保护与最小测试
阶段 1：Decision Memory 信号复盘层
阶段 2：QuantStats 风格策略画像增强
阶段 4：Dashboard v2 研究总控面板
```

中期推进：

```text
阶段 3：多周期 Backtrader feed 试点
阶段 5：实验配置化
阶段 6：数据 Provider 抽象
```

后期增强：

```text
阶段 7：Lookahead Audit 未来函数审计
阶段 8：组合层与目标权重
```

## 4. 每阶段通用验证要求

每个阶段完成后至少运行：

```bash
python -m unittest discover -s tests
python -m compileall main.py cli data engine strategy visual analysis
```

涉及单标的回测时优先运行：

```bash
python main.py backtest run --strategy sma_cross --symbol 000001.SZ
python main.py backtest report --symbol 000001.SZ --strategy sma_cross
```

涉及统计报告时运行：

```bash
python main.py stats analyze --strategy rsi
python main.py stats compare
```

涉及 dashboard 时运行：

```bash
python main.py dashboard
```

如因缺少 Tushare token、本地缓存或依赖导致无法验证，需要在回复和文档中明确标注“未验证/待确认”。

## 5. 风险清单

1. **未来函数风险**
   - 多周期策略和信号复盘最容易出错。
   - 所有未来收益字段只能用于复盘，不能参与信号生成。

2. **输出兼容风险**
   - `output/trades/{symbol}_{strategy}.csv` 字段不能随意改。
   - `_summary_{strategy}.csv` 被统计分析依赖，新增字段要保持兼容。

3. **数据源风险**
   - Tushare token、积分、接口权限会影响下载。
   - AKShare 数据接口可能变化，必须记录来源和抓取时间。

4. **幸存者偏差**
   - 当前股票列表来自 Tushare 当前上市列表并过滤 ST。
   - 严肃绩效判断需标注退市股和历史 ST 覆盖不足。

5. **许可证风险**
   - Backtrader、Freqtrade、vectorbt 等项目许可证约束不同。
   - 本项目只借鉴思想，不复制源码。

## 6. 当前建议落地目标

本轮建议先落地：

1. 阶段 0 的契约测试增强。
2. 阶段 1 的 decision memory 第一版。
3. dashboard 增加 decision memory 的信号复盘入口。
4. 同步更新 `TECHNICAL.md` 和 `README.md`，详细说明新增命令、输出文件、复盘口径和未来函数边界。

