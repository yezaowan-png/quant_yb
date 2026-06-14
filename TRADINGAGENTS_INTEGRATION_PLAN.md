# TradingAgents 借鉴改造项目计划

## 1. 计划目标

本计划用于把 GitHub 项目 `TauricResearch/TradingAgents` 中值得借鉴的工程思想，逐步引入当前 A 股量化回测项目。

注意：本计划不把 LLM 作为直接交易决策器，也不替代现有 Backtrader 回测和策略规则。借鉴重点是：

- 决策留痕
- 事后复盘
- 风险审查
- 结构化评级
- 汇总面板与研究工作流

最终目标是让系统从“策略回测工具”升级为“可持续积累经验的研究与复盘平台”。

## 2. 借鉴对象概览

`TradingAgents` 是一个多智能体金融交易研究框架。它把交易决策拆成多个角色：

- Analyst Team：基本面、情绪、新闻、技术分析
- Researcher Team：多头研究员与空头研究员辩论
- Trader Agent：整合观点形成交易建议
- Risk Management：从波动、流动性、风险暴露角度审查建议
- Portfolio Manager：最终批准或拒绝交易

对当前项目最有价值的不是“多 agent 形式”，而是它的工作流理念：

```text
多源分析 -> 多空审查 -> 交易建议 -> 风险 veto -> 事后记录 -> 未来复盘
```

当前项目已有数据下载、策略回测、买点扫描、指数概览、策略画像和 dashboard，因此更适合先做轻量版：

```text
策略信号 -> 指数环境 -> 风险审查 -> 结构化评级 -> 决策日志 -> 未来收益复盘
```

## 3. 总体原则

### 3.1 不让 LLM 直接决定买卖

LLM 输出具有非确定性，不适合作为可复现回测信号。当前系统的核心仍应是明确策略规则和 Backtrader 回测。

LLM 或 agent 层只负责：

- 解释信号
- 总结风险
- 生成复盘文字
- 辅助研究

### 3.2 先做确定性模块，再做 AI 模块

第一阶段只做本地结构化数据：

- 信号记录
- 未来收益计算
- 相对指数超额
- 风险标签
- dashboard 展示

等这些稳定后，再接入 AI 解读层。

### 3.3 保持现有输出兼容

不得破坏现有文件格式：

- `output/trades/{symbol}_{strategy}.csv`
- `output/trades/{symbol}_{strategy}_equity.csv`
- `output/trades/_summary_{strategy}.csv`
- `output/signals/buy_signals_{strategy}_{date}.csv`
- `output/reports/{symbol}_{strategy}.html`

新增能力优先写入新目录：

```text
output/decisions/
```

## 4. 阶段规划

## 阶段 1：决策留痕与信号记忆

### 目标

把每次买点扫描或策略信号保存成结构化日志，形成项目自己的“交易记忆”。

### 新增输出目录

```text
output/decisions/
```

### 建议文件

```text
output/decisions/decision_memory.csv
output/decisions/decision_memory.md
```

CSV 用于程序统计，Markdown 用于人工阅读。

### 建议 CSV 字段

| 字段 | 含义 |
|---|---|
| `signal_date` | 信号日期 |
| `symbol` | 股票代码 |
| `strategy` | 策略名称 |
| `setup_tag` | 信号类型，如 `MACD_CROSS`、`LPS_READY` |
| `close` | 信号日收盘价 |
| `index_symbol` | 用于比较的指数 |
| `index_state` | 指数环境标签 |
| `strategy_return_rank` | 策略历史表现分位，可选 |
| `risk_level` | 风险等级 |
| `rating` | 结构化评级 |
| `reason` | 简短原因 |
| `created_at` | 记录生成时间 |
| `future_5d_return` | 未来 5 个交易日收益 |
| `future_10d_return` | 未来 10 个交易日收益 |
| `future_20d_return` | 未来 20 个交易日收益 |
| `future_20d_alpha` | 相对基准 20 日超额 |
| `outcome_status` | `pending` / `resolved` |
| `reflection` | 事后复盘摘要 |

### 技术实现

建议新增模块：

```text
analysis/decision_memory.py
cli/decision_cli.py
```

建议命令：

```bash
python main.py decision record --strategy sma_cross --days 5
python main.py decision resolve --horizon 20
python main.py decision list
```

REPL 命令：

```text
decision record --strategy sma_cross --days 5
decision resolve --horizon 20
decision list
```

### 验收标准

- 扫描买点后能生成或追加 `decision_memory.csv`
- 同一 `signal_date + symbol + strategy + setup_tag` 不重复写入
- 能识别 `pending` 与 `resolved`
- 不影响原有 `backtest scan`
- `compileall` 和单元测试通过

### 最小验证命令

```bash
E:\anaconda3\envs\QYTX\python.exe -m compileall main.py cli data engine strategy visual analysis
E:\anaconda3\envs\QYTX\python.exe -m unittest discover -s tests
E:\anaconda3\envs\QYTX\python.exe main.py decision record --strategy sma_cross --days 5
```

## 阶段 2：未来收益与相对指数复盘

### 目标

参考 TradingAgents 的 outcome reflection 思路，为历史信号补齐未来表现：

- 5 日收益
- 10 日收益
- 20 日收益
- 相对指数超额收益

### 数据来源

股票：

```text
data/cache/{symbol}.csv
```

指数：

```text
data/cache/index/{index_symbol}.csv
```

默认基准建议：

| 股票类型 | 默认基准 |
|---|---|
| 大盘/普通 A 股 | `000300.SH` 沪深300 |
| 中小盘 | `000985.SH` 中证全指 |
| 创业板股票 | `399006.SZ` 创业板指 |
| 科创板股票 | `000688.SH` 科创50 |

第一版可以统一使用 `000300.SH`，后续再做自动匹配。

### 技术实现

在 `analysis/decision_memory.py` 中实现：

```python
resolve_outcomes(memory_df, stock_cache_dir, index_cache_dir, horizons=(5, 10, 20))
```

计算方式：

```text
future_return_N = Close[t+N] / Close[t] - 1
benchmark_return_N = IndexClose[t+N] / IndexClose[t] - 1
alpha_N = future_return_N - benchmark_return_N
```

必须按实际交易日定位，不得按自然日直接加天数。

### 验收标准

- 对已经满 20 个交易日的信号自动补齐结果
- 未满周期的信号保持 `pending`
- 缺股票缓存或指数缓存时清晰提示，不编造数据
- 输出结果可重复运行，重复运行不会重复追加

### 最小验证命令

```bash
E:\anaconda3\envs\QYTX\python.exe main.py decision resolve --horizon 20
```

## 阶段 3：风险审查器

### 目标

借鉴 TradingAgents 的 Risk Management / Portfolio Manager，把策略信号经过一个确定性风险审查层，输出评级。

### 输入

- 策略信号
- 股票近期波动
- 股票最大回撤
- 指数环境
- 策略历史表现
- 成交量/流动性

### 输出评级

建议使用五档：

```text
STRONG_WATCH  强关注
WATCH         关注
NEUTRAL       中性
AVOID         回避
STRONG_AVOID  强回避
```

不使用“买入/卖出”作为评级名称，避免误解为自动交易指令。

### 风险规则建议

| 条件 | 处理 |
|---|---|
| 上证指数、沪深300、全指均在 MA20 下方 | 降一档 |
| 目标股票 20 日波动显著高于历史中位数 | 降一档 |
| 最近 20 日最大回撤超过阈值 | 降一档 |
| 所属策略历史正收益比例低于 45% | 降一档 |
| 策略历史平均最大回撤过大 | 降一档 |
| 股票成交量过低或近期停牌缺口多 | 回避 |
| 指数趋势向上且策略历史表现优秀 | 升一档 |

### 技术实现

建议新增：

```text
analysis/risk_review.py
```

核心函数：

```python
review_signal(signal: dict, config: dict) -> dict
```

返回：

```python
{
    "rating": "WATCH",
    "risk_level": "medium",
    "score": 62,
    "reasons": [
        "沪深300位于MA20上方",
        "策略历史正收益比例59.4%",
        "标的20日波动偏高，评级下调"
    ]
}
```

### 验收标准

- 所有评级由确定性规则生成
- 每个评级必须有原因
- 风险审查不改变策略买卖信号，只改变展示评级
- dashboard 可以显示评级分布

## 阶段 4：Dashboard 集成

### 目标

把决策记忆和风险审查结果加入现有总控面板：

```text
output/reports/dashboard.html
```

### 新增面板区域

1. 最近信号
2. 待复盘信号
3. 已复盘信号胜率
4. 20 日平均超额收益
5. 按策略分组的信号质量
6. 按评级分组的未来收益

### 推荐展示指标

| 指标 | 含义 |
|---|---|
| `pending_count` | 待复盘信号数 |
| `resolved_count` | 已复盘信号数 |
| `positive_20d_ratio` | 20 日正收益比例 |
| `positive_alpha_ratio` | 20 日跑赢基准比例 |
| `avg_20d_alpha` | 平均 20 日超额 |
| `best_strategy_by_alpha` | 复盘表现最好的策略 |
| `worst_strategy_by_alpha` | 复盘表现最差的策略 |

### 验收标准

- `python main.py dashboard` 自动读取 `output/decisions/decision_memory.csv`
- 没有 decision 文件时正常显示空状态
- 有 decision 文件时显示最近信号和复盘统计
- 原有指数导航、策略汇总、最近报告不受影响

## 阶段 5：AI 解读层

### 目标

在确定性数据和风险审查稳定后，再加入 AI 解释能力。

AI 层只做解释，不做信号生成。

### 输入材料

- 股票 K 线摘要
- 策略信号
- 指数环境
- 风险审查结果
- 历史同类信号复盘结果

### 输出

```text
1. 信号解释
2. 主要支持因素
3. 主要风险因素
4. 类似历史信号表现
5. 操作建议级别：观察 / 谨慎关注 / 回避
```

### 建议命令

```bash
python main.py decision explain --symbol 000001.SZ --strategy sma_cross
```

### 注意事项

- 不把 API key 写入仓库
- 不把 AI 输出作为回测信号
- AI 输出必须标注“解释性文本，不构成交易建议”
- 最好支持 `--offline`，没有 AI key 时仍能显示确定性摘要

## 阶段 6：轻量多角色研究流

### 目标

在前五阶段完成后，再考虑轻量多角色，而不是一开始照搬完整 TradingAgents。

建议角色：

| 角色 | 输入 | 输出 |
|---|---|---|
| 技术分析员 | K 线、指标、策略信号 | 技术面摘要 |
| 指数环境分析员 | 指数概览、宽基趋势 | 市场环境摘要 |
| 风险审查员 | 波动、回撤、流动性 | 风险意见 |
| 总结员 | 所有摘要 | 最终解释 |

### 输出文件

```text
output/decisions/reports/{symbol}_{strategy}_{date}.html
output/decisions/reports/{symbol}_{strategy}_{date}.md
```

### 验收标准

- 多角色只影响解释报告
- 不影响回测和买卖信号
- 支持关闭 AI 层
- 支持缓存同一日期同一标的的解释结果

## 5. 推荐执行顺序

建议按下面顺序调用 Codex 实施：

```text
1. 实现阶段 1：决策留痕与 signal memory
2. 实现阶段 2：未来收益和相对指数复盘
3. 实现阶段 4 的基础 dashboard 集成
4. 实现阶段 3：确定性风险审查器
5. 再次增强 dashboard，加入评级分布和复盘统计
6. 实现阶段 5：AI 解读层
7. 最后再考虑阶段 6：轻量多角色研究流
```

原因：

- 阶段 1 和 2 是数据地基。
- dashboard 能让你尽早看到成果。
- 风险审查依赖已有信号和复盘统计。
- AI 层必须建立在稳定结构化数据之上。

## 6. 与当前项目模块的对应关系

| 当前模块 | 计划改造 |
|---|---|
| `cli/backtest_cli.py` | 可选：扫描后调用 decision record |
| `cli/shell.py` | 增加 `decision` 命令 |
| `main.py` | 注册 `decision` 命令组 |
| `analysis/` | 增加 decision memory、risk review |
| `visual/dashboard.py` | 增加决策记忆区块 |
| `output/signals/` | 保持买点扫描原始输出 |
| `output/decisions/` | 新增决策留痕和复盘输出 |
| `README.md` | 补充 decision workflow |
| `TECHNICAL.md` | 补充技术链路和字段说明 |

## 7. 数据与未来函数约束

### 7.1 未来收益复盘不参与信号生成

`future_5d_return`、`future_10d_return`、`future_20d_return` 只能用于事后复盘和统计，不能被策略读取，不能影响扫描结果。

### 7.2 风险审查只能使用信号日之前的数据

风险评级如果在信号日生成，只能使用：

- 信号日及之前的股票数据
- 信号日及之前的指数数据
- 已经完成的历史策略统计

不能使用未来收益。

### 7.3 Dashboard 可以展示未来复盘结果

dashboard 是研究输出，可以展示已完成信号的未来表现，但必须与实时评级分开显示。

## 8. 输出文件约定

建议最终形成：

```text
output/decisions/
    decision_memory.csv
    decision_memory.md
    reports/
        {symbol}_{strategy}_{date}.html
        {symbol}_{strategy}_{date}.md
```

其中：

- CSV 是主数据源。
- Markdown 是人工复盘日志。
- HTML 是后续 AI 解读报告。

## 9. 配置建议

后续可在 `config.yaml` 增加：

```yaml
decision_memory:
  enabled: true
  output_dir: "output/decisions"
  default_benchmark: "000300.SH"
  horizons: [5, 10, 20]
  deduplicate: true

risk_review:
  enabled: true
  index_ma_period: 20
  volatility_period: 20
  high_volatility_multiplier: 1.5
  min_strategy_positive_ratio: 45.0
  rating_floor_when_index_weak: "NEUTRAL"
```

示例配置不要包含任何真实 token。

## 10. 第一阶段详细任务拆分

### 任务 1：新增 decision memory 数据模块

文件：

```text
analysis/decision_memory.py
```

函数：

```python
load_memory(path) -> pd.DataFrame
save_memory(df, path) -> None
append_signals(signals_df, context) -> pd.DataFrame
deduplicate_memory(df) -> pd.DataFrame
```

### 任务 2：新增 CLI

文件：

```text
cli/decision_cli.py
```

命令：

```text
decision record
decision resolve
decision list
```

### 任务 3：注册入口

文件：

```text
main.py
cli/shell.py
```

### 任务 4：文档同步

文件：

```text
README.md
TECHNICAL.md
```

### 任务 5：最小验证

命令：

```bash
E:\anaconda3\envs\QYTX\python.exe -m compileall main.py cli data engine strategy visual analysis
E:\anaconda3\envs\QYTX\python.exe -m unittest discover -s tests
E:\anaconda3\envs\QYTX\python.exe main.py decision --help
```

如需要真实扫描数据，再运行：

```bash
E:\anaconda3\envs\QYTX\python.exe main.py backtest scan --strategy sma_cross --days 5
E:\anaconda3\envs\QYTX\python.exe main.py decision record --strategy sma_cross --days 5
```

## 11. 成功标准

完成本计划后，项目应具备：

- 每个策略信号可以被记录。
- 每个记录可以在未来自动补齐表现。
- 每个信号有确定性风险评级。
- dashboard 能展示信号质量和复盘情况。
- AI 层只负责解释，不改变策略信号。
- 所有新增输出与现有回测输出兼容。

## 12. 后续调用建议

后续你可以按下面方式调用 Codex：

```text
请按照 TRADINGAGENTS_INTEGRATION_PLAN.md 实现阶段 1。
```

或：

```text
请按照 TRADINGAGENTS_INTEGRATION_PLAN.md 实现阶段 2，并用真实 main.py 入口验证。
```

每个阶段完成后，都应更新本计划中的状态或在 `TECHNICAL.md` 中补充实际实现细节。
