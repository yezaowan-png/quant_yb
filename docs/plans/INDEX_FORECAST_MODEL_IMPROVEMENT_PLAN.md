# 大盘指数预测模型优化计划

> 口径更新（2026-07）：主预测目标已由指数未来收益切换为个股横截面机会/风险环境标签。本文中的 `legacy/abs/rank` 指数收益标签只保留为兼容诊断，不再是默认目标；当前口径见 `docs/reference/index_forecast_report.md`。

本文基于当前 `000001.SH` 的 3 日预测结果做一次发散分析，并收敛出下一版模型优化方案。

分析对象：

```text
output.statistics_dir/index_forecast/predictions_000001.SH_h3.csv
output.statistics_dir/index_forecast/features_000001.SH.csv
```

当前模型：

```text
rule_v1
```

预测周期：

```text
horizon = 3 个交易日
```

## 1. 当前 3 日预测的关键发现

### 1.1 样本分布

本次检查到：

| 项目 | 数值 |
| --- | ---: |
| 总预测行数 | 1323 |
| 可评估样本 | 1301 |
| 当前整体命中率 | 约 50.7% |

预测信号分布：

| 预测信号 | 样本数 |
| --- | ---: |
| `bull` | 297 |
| `neutral` | 796 |
| `bear` | 208 |

真实标签分布：

| 真实标签 | 样本数 |
| --- | ---: |
| `bull` | 169 |
| `neutral` | 973 |
| `bear` | 159 |

结论：

- 真实标签里 `neutral` 占比很高，约 75%。
- 这说明当前 3 日标签阈值偏宽，很多实际有交易意义的小波动被归为中性。
- 只看命中率会误导，因为模型预测中性较多时，天然容易“看起来命中率不低”。

### 1.2 当前信号的收益表现

按预测信号分组后，未来 3 日平均收益大致为：

| 预测信号 | 样本数 | 平均未来3日收益 | 胜率 | 标签命中 |
| --- | ---: | ---: | ---: | ---: |
| `bull` | 297 | +0.18% | 55.6% | 9.1% |
| `neutral` | 796 | -0.02% | 51.1% | 74.7% |
| `bear` | 208 | +0.16% | 49.5% | 17.8% |

结论：

- `bull` 信号有一点正收益，但优势不明显。
- `bear` 信号的未来平均收益仍是正的，说明当前防守信号不够有效。
- `neutral` 命中率高，主要是因为真实标签中 neutral 太多，不代表模型有很强预测力。

### 1.3 大盘分数和未来收益几乎不相关

当前 `market_score` 与未来 3 日收益的相关性约为：

```text
相关系数 ≈ -0.0007
```

这基本等于没有线性关系。

各分数桶未来 3 日收益也不单调：

| 分数区间 | 样本数 | 平均未来3日收益 | 胜率 |
| --- | ---: | ---: | ---: |
| 20-35 | 184 | +0.17% | 48.9% |
| 35-45 | 190 | +0.06% | 51.6% |
| 45-55 | 265 | -0.05% | 51.3% |
| 55-65 | 240 | -0.06% | 50.8% |
| 65-70 | 125 | +0.01% | 51.2% |
| 70-80 | 185 | +0.21% | 50.3% |
| 80-100 | 112 | +0.13% | 64.3% |

结论：

- 当前分数不是一个稳定的“越高越好”指标。
- 低分区并不差，甚至有正收益，说明低分有时代表短线超跌后的反弹机会。
- 中间分数区反而表现较差，可能对应“趋势不强但还没充分释放风险”的阶段。

### 1.4 3 日预测更像短线均值回归，不像趋势跟随

一些指标与未来 3 日收益的关系显示，短线更偏均值回归：

正相关较明显的指标：

| 指标 | 解释 |
| --- | --- |
| `intraday_range_pct` | 日内振幅越大，短线后续可能有修复/延续波动 |
| `volatility_10d` | 短期波动越大，未来 3 日机会反而更明显 |
| `atr20_pct` | 波动环境高时，短线反弹/波动收益更大 |
| `amount_ratio_20` | 成交金额放大，短线活跃度提高 |
| `nhnl_slope_3` | 新高新低力量短线改善有帮助 |
| `ad_slope_5_delta` | 广度斜率加速改善有帮助 |

负相关较明显的指标：

| 指标 | 解释 |
| --- | --- |
| `drawdown_20d` | 值越低代表回撤越深，未来 3 日反弹倾向越强 |
| `dist_ma20` | 离 MA20 越远且偏高，短线继续上涨优势变弱 |
| `ret_5d` | 近 5 日涨幅越大，短线继续上涨优势变弱 |
| `ret_20d` | 近 20 日涨幅越大，短线继续上涨优势变弱 |
| `ma20_slope_5` | 趋势越顺，短线未必越强 |
| `ad_slope_5` | 广度短线已经改善后，未来 3 日可能边际递减 |

结论：

- 3 日预测不能简单沿用中期趋势评分。
- 趋势强不一定代表未来 3 日还会继续强。
- 短线更需要区分“超跌修复”“放量活跃”“过热回落”“趋势延续”几类结构。

### 1.5 当前规则里几个关键误判点

#### 低分不一定代表看空

当前 `score <= 35` 会归为 `bear`，但 20-35 分数桶平均收益是正的。

这说明：

```text
低分可能代表弱，也可能代表超跌修复机会。
```

不能直接把低分等同于看空。

#### 放量下跌不一定是坏事

当前 `amount_down_expand` 在规则里偏扣分，但数据里：

| 条件 | 样本数 | 平均未来3日收益 | 胜率 |
| --- | ---: | ---: | ---: |
| `amount_down_expand` | 58 | +0.37% | 56.9% |
| `amount_down_expand` 且 `drawdown_20d < -2%` | 19 | +0.73% | 57.9% |

结论：

- 放量下跌在 3 日维度可能是恐慌释放后的修复信号。
- 不能简单作为风险扣分项。

#### KDJ 的 J 值要看组合

当前数据：

| 条件 | 样本数 | 平均未来3日收益 | 胜率 |
| --- | ---: | ---: | ---: |
| `J < 0` | 112 | +0.12% | 52.7% |
| `J < -10` | 46 | +0.25% | 56.5% |
| `J > 90` 且 `ad_slope_5 < 0` | 53 | -0.09% | 45.3% |
| `J > 100` 且 `ad_slope_5 < 0` | 30 | -0.11% | 43.3% |

结论：

- `J < -10` 更像短线修复机会。
- `J > 90` 单独看不一定很差，但如果同时广度走弱，风险明显提高。
- J 值必须和 A/D、NH-NL、位置、成交金额一起看。

## 2. 发散性优化思路

### 2.1 按周期拆模型

不同预测周期的逻辑不同：

| 周期 | 更适合的核心逻辑 |
| --- | --- |
| 3日 | 均值回归、情绪修复、过热风险 |
| 5日 | 修复和趋势混合 |
| 20日 | 趋势结构、主线强度、量能确认 |

当前 `rule_v1` 用同一套分数解释多个周期，这不够精细。

建议：

```text
h3 用短线模型
h5 用混合模型
h20 用趋势模型
```

### 2.2 从单一 market_score 改成多轴评分

当前只有一个总分，容易把不同含义混在一起。

建议拆成至少三条轴：

| 评分轴 | 含义 |
| --- | --- |
| `opportunity_score` | 短线机会，包括超跌、放量活跃、广度修复 |
| `risk_score` | 短线风险，包括过热、广度转弱、滞涨 |
| `trend_score` | 趋势背景，包括均线结构、趋势斜率 |

最终信号不要只看总分，而是看：

```text
net_score = opportunity_score - risk_score
```

同时保留 `trend_score` 作为环境过滤。

### 2.3 把低分拆成“弱势”和“超跌”

当前低分直接归为 `bear`，这是明显问题。

低分至少要拆成两类：

| 类型 | 特征 | 处理 |
| --- | --- | --- |
| 弱势延续 | 趋势差、广度继续恶化、无恐慌释放 | 偏空 |
| 超跌修复 | 跌幅大、J 低位、放量释放、波动抬升 | 可能偏多 |

### 2.4 把过热风险做成组合信号

`J > 90` 不应该单独作为强风险。

更合理的风险组合：

```text
J > 90
且 ad_slope_5 < 0
且 nhnl_slope_3 <= 0
且 dist_ma20 > 0
```

如果只是 `J > 90`，但成交金额放大、A/D 斜率仍向上，可能是强趋势，不应过早看空。

### 2.5 标签体系需要优化

当前 3 日标签使用固定最小阈值，导致 `neutral` 太多。

可以考虑三种标签：

#### 方案 A：降低 3 日阈值

例如：

```text
h3_min_threshold = 0.8%
```

优点：

- 更容易识别短线机会。
- 真实标签不至于过度集中在 neutral。

缺点：

- 噪声会增加。

#### 方案 B：分位数标签

按未来 3 日收益排名：

```text
top 30% -> bull
middle 40% -> neutral
bottom 30% -> bear
```

优点：

- 标签更平衡。
- 更适合训练机器学习模型。

缺点：

- 标签含义不是固定收益阈值，不如交易直观。

#### 方案 C：双标签

保留两套标签：

| 标签 | 用途 |
| --- | --- |
| `label_abs_3d` | 固定阈值标签，用于交易解释 |
| `label_rank_3d` | 分位数标签，用于训练和排序 |

这是最推荐的方案。

### 2.6 概率需要校准

当前 `p_bull / p_bear` 是规则映射值，不是真实概率。

可以用历史分桶校准：

```text
score_bucket + signal -> 历史 bull 发生率 / bear 发生率
```

例如：

```text
p_bull_calibrated = 历史同类样本中 label=bull 的比例
```

这样展示出来的概率更接近真实历史概率。

### 2.7 模型可以从规则走向轻量机器学习

在不破坏当前结构的前提下，可以加多个算法：

| 模型 | 说明 |
| --- | --- |
| `rule_h3_v2` | 手工规则，专门优化 3 日 |
| `logistic_h3_v1` | 线性模型，看特征方向 |
| `tree_h3_v1` | 决策树/随机森林，捕捉非线性 |
| `hgb_h3_v1` | 梯度提升树，作为更强基线 |

但机器学习必须走严格时间验证，不能随机切分。

## 3. 收敛后的推荐方案

建议下一步先做 `rule_h3_v2`，不要马上上复杂机器学习。

原因：

- 当前样本只有约 1300 行，不算大。
- 特征和收益相关性普遍不强，直接上复杂模型容易过拟合。
- 规则模型更容易解释，也更方便和你现有盘感对齐。

### 3.1 新模型结构

新增一个 3 日专用规则模型：

```text
rule_h3_v2
```

输出字段：

```text
opportunity_score
risk_score
trend_context_score
net_score
signal
p_bull_calibrated
p_bear_calibrated
```

信号逻辑：

```text
net_score = opportunity_score - risk_score

if net_score >= bull_threshold:
    signal = bull
elif net_score <= bear_threshold:
    signal = bear
else:
    signal = neutral
```

### 3.2 opportunity_score 设计

短线机会得分重点捕捉三类机会。

#### 超跌修复

候选条件：

```text
drawdown_20d < -2%
或 dist_ma20 < -2%
或 ret_5d < -2%
或 kdj_j_below_minus10 = True
```

加分条件：

```text
amount_ratio_20 > 1.1
或 intraday_range_pct 抬升
或 ad_slope_5_delta > 0
```

#### 放量活跃

候选条件：

```text
amount_up_confirm = True
或 amount_down_expand = True
```

注意：

- 3 日维度里，放量下跌不直接扣分。
- 放量下跌且已有明显回撤，反而可能加分。

#### 短线突破

候选条件：

```text
break_high_20d = True
且 amount_ratio_20 > 1.1
且 ad_norm > 0
```

说明：

- 突破必须有成交金额和广度配合。
- 只突破但广度差，不应高分。

### 3.3 risk_score 设计

短线风险重点捕捉过热衰竭，而不是简单“涨多了”。

候选条件：

```text
kdj_j_above_90 = True
且 ad_slope_5 < 0
```

增强风险：

```text
kdj_j_above_100 = True
nhnl_slope_3 <= 0
upper_shadow_ratio > 0.35
amount_stalling = True
dist_ma20 > 2%
```

注意：

- `J > 90` 单独不作为强风险。
- 必须和广度转弱、领涨力量转弱、滞涨或位置偏高组合判断。

### 3.4 trend_context_score 设计

趋势背景只作为环境过滤，不直接决定 3 日方向。

候选条件：

```text
above_ma20
above_ma60
ma20_gt_ma60
ma60_gt_ma120
```

使用方式：

- 趋势强时，放宽 `bull` 触发阈值。
- 趋势弱时，放宽“超跌修复”触发，但限制持仓级别。
- 趋势强但过热风险高时，信号可以保持 neutral，而不是直接 bear。

### 3.5 标签优化

新增两套标签：

```text
label_abs_3d
label_rank_3d
```

建议参数：

#### 固定阈值标签

```text
label_abs_3d:
  bull: fwd_ret_3d >= +0.8%
  bear: fwd_ret_3d <= -0.8%
  neutral: 其他
```

#### 分位数标签

```text
label_rank_3d:
  bull: 未来3日收益进入滚动或全样本 top 30%
  bear: 未来3日收益进入 bottom 30%
  neutral: 中间 40%
```

第一版模型评估可以同时展示两套标签：

- `label_abs_3d` 看交易意义。
- `label_rank_3d` 看排序能力。

## 4. 评估体系升级

后续模型不能只看命中率。

### 4.1 必看指标

| 指标 | 目的 |
| --- | --- |
| bull 平均未来收益 | 看多信号是否有收益优势 |
| bear 平均未来收益 | 看空信号是否能避开弱势 |
| 分数分桶收益 | 看分数是否有单调性 |
| IC / Rank IC | 看分数与未来收益相关性 |
| 多空差 | `bull平均收益 - bear平均收益` |
| 年度稳定性 | 防止只在某一年有效 |
| 择时曲线 | 看实际仓位使用价值 |
| 最大回撤 | 看防守价值 |

### 4.2 时间切分

不能随机切分。

建议：

```text
训练: 2021-2023
验证: 2024
测试: 2025-2026
```

再做滚动验证：

```text
训练窗口: 756 个交易日
测试窗口: 126 个交易日
滚动步长: 63 个交易日
```

### 4.3 模型比较表

每个模型输出一张比较表：

```text
model
horizon
label_type
sample_count
bull_count
bear_count
bull_avg_return
bear_avg_return
long_short_spread
score_ic
rank_ic
timing_return
timing_max_drawdown
buyhold_return
buyhold_max_drawdown
```

## 5. 机器学习前的评估框架补强

在考虑 `logistic_h3_v1` 或 `hgb_h3_v1` 之前，需要先把评估框架固定下来。否则模型很容易出现“回测报告好看，但只是调参调到了历史噪声”的问题。

### 5.1 现有评估框架的主要问题

当前评估框架可以做初步观察，但还不足以支撑机器学习模型上线。

#### 只看命中率不够

当前命中率只能回答：

```text
预测标签和实际标签是否一致
```

但它不能回答：

```text
信号是否有收益优势
信号是否能降低回撤
看多信号是否比看空信号明显更强
概率输出是否真的接近历史发生率
```

例如当前 3 日预测中，`bear` 信号未来 3 日平均收益仍然为正，这说明：

```text
即使命中率看起来不低，也不代表信号具有交易价值。
```

#### 标签分布不均衡

当前 3 日真实标签中 `neutral` 占比很高。模型如果大量预测中性，命中率天然不会太差。

因此后续必须单独评估：

| 指标 | 说明 |
| --- | --- |
| `bull_precision` | 预测看多时，实际看多的比例 |
| `bear_precision` | 预测看空时，实际看空的比例 |
| `bull_avg_fwd_return` | 看多信号后的平均未来收益 |
| `bear_avg_fwd_return` | 看空信号后的平均未来收益 |
| `long_short_spread` | 看多收益 - 看空收益 |
| `neutral_ratio` | 模型是否过度躲在中性里 |

#### 3 日样本高度重叠

3 日预测有天然重叠：

```text
今天预测未来 3 日
明天也预测未来 3 日
```

这两个样本共享大量未来收益区间，并不是完全独立样本。

因此机器学习评估时不能简单随机切分，也不能直接用相邻日期做训练/测试边界。需要引入：

```text
purge_days = horizon
embargo_days = max(horizon, 5)
```

含义：

- `purge_days`：训练集和测试集之间至少隔离预测周期长度，避免未来收益窗口重叠。
- `embargo_days`：测试窗口前后留出缓冲区，避免滚动特征和标签边界相互污染。

#### 缺少固定基准模型

每次新增模型都必须和固定基准比较。

建议保留以下基准：

| 基准 | 用途 |
| --- | --- |
| `always_neutral` | 检查模型是否只是靠中性标签刷命中率 |
| `buy_and_hold` | 检查择时是否真的优于持有指数 |
| `rule_v1` | 当前规则基准 |
| `simple_oversold_h3` | 简单超跌反弹基准 |
| `simple_trend_h3` | 简单趋势基准 |

如果新模型不能稳定超过这些基准，就不应该进入下一阶段。

#### 缺少时间稳定性检查

不能只看全样本结果。至少要按年度和市场环境拆开看：

```text
2021
2022
2023
2024
2025
2026
```

并进一步按市场环境分组：

| 市场环境 | 划分依据 |
| --- | --- |
| 高波动 / 低波动 | `atr20_pct` 或 `volatility_10d` 分位数 |
| 放量 / 缩量 | `amount_ratio_20` |
| 强趋势 / 弱趋势 | `dist_ma20`、`ma20_slope_5`、均线结构 |
| 广度改善 / 广度恶化 | `ad_slope_5`、`nhnl_slope_3` |

如果模型只在某一年、某一种环境有效，应该降级为“条件信号”，不能当作通用预测模型。

#### 缺少概率质量评估

如果报告展示 `p_bull / p_bear`，就必须检查概率是否可信。

建议新增：

| 指标 | 说明 |
| --- | --- |
| Brier Score | 概率预测误差 |
| Calibration Table | 概率分桶后的真实发生率 |
| Reliability Curve | 预测概率和真实概率是否接近 |
| High Confidence Precision | 高置信信号是否真的更准 |

如果 `p_bull = 60%` 的样本，真实看多比例只有 35%，那概率就不能直接展示为“历史概率”，只能标注为“规则强度分”。

### 5.2 数据量扩展计划

单个上证指数从 2021 到 2026 约 1300 个交易日，对规则模型诊断勉强够用，但对机器学习偏少。

建议按两条线扩展数据。

#### 时间维度扩展

优先把指数和全市场广度数据向前扩展到：

```text
start_date = 20150101
```

如果数据质量可接受，再考虑扩展到：

```text
start_date = 20100101
```

原因：

- 2021-2026 样本覆盖的市场阶段有限。
- 机器学习需要经历更多牛市、熊市、震荡市、急跌修复和高波动阶段。
- A 股市场制度和成分股数量变化较大，时间过长也要保留版本说明，不盲目追求越长越好。

#### 指数横向扩展

建议逐步纳入多指数样本：

| 指数 | 作用 |
| --- | --- |
| `000001.SH` 上证指数 | 主指数，优先优化 |
| `000300.SH` 沪深300 | 权重蓝筹 |
| `399006.SZ` 创业板指 | 成长风格 |
| `000905.SH` 中证500 | 中盘 |
| `000852.SH` 中证1000 | 小盘 |
| `932000.CSI` 中证2000 | 更小盘风格，如数据可得则加入 |

注意：

```text
这些指数不是完全独立市场，不能简单把样本数乘以指数数量。
```

更合理的用途是：

- 增加模型对不同风格环境的理解。
- 观察同一特征在不同指数上的稳定性。
- 训练时可做 pooled model，但最终评估仍要按指数单独出报告。

### 5.3 评估维度扩展清单

下一阶段诊断报告至少需要覆盖以下维度。

#### 预测质量

```text
accuracy
balanced_accuracy
confusion_matrix
bull_precision
bear_precision
bull_recall
bear_recall
neutral_ratio
```

#### 收益质量

```text
bull_avg_fwd_return
bear_avg_fwd_return
neutral_avg_fwd_return
bull_median_fwd_return
bear_median_fwd_return
bull_win_rate
bear_win_rate
long_short_spread
tail_loss_5pct
tail_gain_95pct
```

#### 分数和排序能力

```text
score_bucket_return
score_bucket_win_rate
score_ic
rank_ic
top_decile_return
bottom_decile_return
top_bottom_spread
```

#### 时间稳定性

```text
yearly_metrics
rolling_window_metrics
train_validate_test_metrics
market_regime_metrics
```

#### 策略化评估

将预测信号转成简单仓位：

| 信号 | 仓位建议 |
| --- | --- |
| `bull` | 100% |
| `neutral` | 50% 或 0% 两种版本都评估 |
| `bear` | 0% |

输出：

```text
timing_return
timing_annual_return
timing_max_drawdown
timing_sharpe
timing_calmar
buyhold_return
buyhold_max_drawdown
excess_return
excess_max_drawdown
```

#### 概率校准

```text
brier_score_bull
brier_score_bear
calibration_bins
high_confidence_signal_count
high_confidence_precision
```

### 5.4 机器学习模型上线门槛

机器学习模型必须满足以下门槛，才进入报告默认展示。

| 门槛 | 要求 |
| --- | --- |
| 时间隔离 | 训练、验证、测试严格按时间切分，含 purge/embargo |
| 基准比较 | 至少超过 `rule_v1` 和一个简单基准 |
| 稳定性 | 测试期和滚动窗口不能只靠单一年份贡献收益 |
| 收益有效 | `bull_avg_fwd_return > neutral_avg_fwd_return > bear_avg_fwd_return` 或至少 `bull - bear` 明显为正 |
| 回撤有效 | 策略化评估最大回撤不高于 buy-and-hold |
| 概率可信 | 高置信信号真实表现优于低置信信号 |
| 可解释 | 能输出主要特征贡献或分组表现，不做黑箱结论 |

如果只满足部分条件，模型可以保留为实验模型，但不作为默认信号。

### 5.5 Claude Code 监督机制

可以引入 Claude Code 作为“第二审查员”，但它不能替代统计验证。

建议用于三类监督。

#### 代码审计

重点检查：

```text
是否存在未来函数
滚动窗口是否误用了未来数据
标签是否被特征间接泄露
训练、验证、测试是否严格隔离
purge/embargo 是否正确执行
```

#### 评估审计

重点检查：

```text
是否只报告了有利指标
是否遗漏失败年份
是否反复用测试集调参
是否基准模型设置过弱
机器学习模型是否真的超过规则基准
```

#### 解释审计

重点检查：

```text
模型解释是否和数据证据一致
概率是否被误写成确定性结论
报告是否明确标注样本范围和局限
```

执行方式建议：

```text
每次新增模型或大改评估框架后，导出 diagnostics HTML + metrics CSV。
把模型代码、评估报告、关键 CSV 字段说明交给 Claude Code 做一次 review。
只采纳有数据证据或代码证据支持的意见。
```

### 5.6 推荐收敛顺序

为了避免工程发散，建议按下面顺序推进：

```text
1. 先做 forecast-diagnose 诊断报告
2. 固定评估字段和模型比较表
3. 增加 purged time split 和滚动验证
4. 加入 simple_oversold_h3 / simple_trend_h3 基准
5. 再实现 rule_h3_v2
6. 如果 rule_h3_v2 明显优于 rule_v1，再引入 logistic_h3_v1
7. 最后再考虑 hgb_h3_v1
```

本阶段的核心原则：

```text
先让评估可信，再让模型复杂。
```

## 6. 实施步骤

### 阶段 1：诊断自动化和评估框架固化

实施状态：已完成第一版自动化诊断入口 `index forecast-diagnose`，用于先固化评估框架，再进入规则或机器学习模型优化。

新增：

```text
analysis/index_forecast_diagnostics.py
```

功能：

- 自动读取 `indicators/features/predictions`。
- 输出分数桶收益。
- 输出信号分组收益。
- 输出特征相关性排名。
- 输出关键条件组合表现。
- 输出年度稳定性。
- 输出混淆矩阵、看多/看空 precision、recall。
- 输出基准模型比较。
- 输出概率校准表。

报告：

```text
output.reports_dir/index_forecast/diagnostics_000001.SH_h3.html
```

同时导出机器可读指标：

```text
output.statistics_dir/index_forecast/diagnostics_000001.SH_h3_metrics.csv
```

第一版同时导出：

```text
output.statistics_dir/index_forecast/diagnostics_000001.SH_h3_feature_correlations.csv
output.statistics_dir/index_forecast/diagnostics_000001.SH_h3_conditions.csv
output.statistics_dir/index_forecast/diagnostics_000001.SH_h3_yearly.csv
output.statistics_dir/index_forecast/diagnostics_000001.SH_h3_calibration.csv
```

常用命令：

```shell
python main.py index forecast-diagnose --symbol 000001.SH --horizon 3
```

### 阶段 2：标签优化

实施状态：已完成第一版双标签生成和诊断切换。

在 `features_000001.SH.csv` 中新增：

```text
fwd_ret_3d
threshold_abs_3d
rank_lower_3d
rank_upper_3d
label_abs_3d
label_rank_3d
```

注意：

- 保留原有 `label_3d`，避免破坏兼容。
- `label_abs_3d` 使用固定阈值：`fwd_ret_3d >= +0.8%` 为 `bull`，`<= -0.8%` 为 `bear`，其他为 `neutral`。
- `label_rank_3d` 使用滚动历史分位：只使用到当前日期已经能够确认的历史 `fwd_ret_3d.shift(3)`，窗口 252 个交易日，最少 80 个样本；top 30% 为 `bull`，bottom 30% 为 `bear`，中间为 `neutral`。
- 新模型和诊断报告可以通过 `--label-mode abs|rank` 使用新标签评估；默认 `legacy` 仍使用旧 `label_3d`。

常用命令：

```shell
python main.py index forecast-diagnose --symbol 000001.SH --horizon 3 --label-mode abs
python main.py index forecast-diagnose --symbol 000001.SH --horizon 3 --label-mode rank
```

第一版上证指数 h3 标签分布参考：

| 标签列 | bull | neutral | bear | 空值 |
| --- | ---: | ---: | ---: | ---: |
| `label_3d` | 563 | 2666 | 505 | 22 |
| `label_abs_3d` | 1215 | 1426 | 1112 | 3 |
| `label_rank_3d` | 1095 | 1492 | 1084 | 85 |

### 阶段 3：时间切分和基准模型

实施状态：已完成固定时间切分、purge/embargo 边界处理、基准模型对比输出。

新增固定评估切分：

```text
train: 2021-2023
validate: 2024
test: 2025-2026
purge_days: horizon
embargo_days: max(horizon, 5)
```

新增基准：

```text
always_neutral
buy_and_hold
simple_oversold_h3
simple_trend_h3
rule_v1
```

只有在诊断报告里能稳定超过这些基准后，才进入下一阶段。

实现口径：

- `train_2021_2023`：2021-01-01 到 2023-12-31，并在区间末尾剔除 `purge_days=horizon` 个交易日。
- `validate_2024`：2024-01-01 到 2024-12-31，并在区间开头剔除 `embargo_days=max(horizon, 5)` 个交易日，末尾剔除 `purge_days=horizon` 个交易日。
- `test_2025_2026`：2025-01-01 到 2026-12-31，并在区间开头剔除 `embargo_days=max(horizon, 5)` 个交易日。
- `buy_and_hold` 在标签评估中等价于始终 `bull`，在择时收益中等价于满仓持有。

新增诊断产物：

```text
output.statistics_dir/index_forecast/diagnostics_000001.SH_h3_splits.csv
output.statistics_dir/index_forecast/diagnostics_000001.SH_h3_abs_splits.csv
output.statistics_dir/index_forecast/diagnostics_000001.SH_h3_rank_splits.csv
```

诊断 HTML 中新增“时间切分验证”表，展示每个 split 下各基准模型的：

- 样本数
- 命中率
- 平衡命中率
- 多空收益差
- 择时收益
- 买入持有收益

### 阶段 4：数据扩展可行性检查

检查是否可以将数据扩展到：

```text
20150101 ~ latest
```

检查内容：

- 指数 K 线是否可完整下载。
- 个股缓存是否足以计算历史 A/D 和 NH-NL。
- 早期股票数量较少时，标准化 A/D 是否保持可比。
- 成分指数成员数据是否足以做沪深300/创业板/中证1000/中证2000分层 A/D。

如果数据完整，再把默认训练样本向前扩展；如果不完整，则先保留 2021 起的数据，并在报告里明确限制。

### 阶段 5：实现 rule_h3_v2

实施状态：已完成第一版 `rule_h3_v2`，作为可选模型接入 `index forecast --model rule_h3_v2`，并纳入 `forecast-diagnose` 的模型对比和时间切分验证。

新增模型：

```text
rule_h3_v2
```

核心改动：

- 低分不再直接看空。
- 放量下跌在超跌背景下转为机会信号。
- J>90 必须叠加广度转弱才作为风险。
- 输出机会分、风险分、趋势背景分。

第一版输出字段：

```text
opportunity_score
risk_score
trend_context_score
net_score
adjusted_net_score
opportunity_reason
risk_reason
signal_reason
```

使用命令：

```shell
python main.py index forecast --symbol 000001.SH --horizon 3 --model rule_h3_v2
python main.py index forecast-diagnose --symbol 000001.SH --horizon 3 --label-mode rank
```

输出文件：

```text
output.statistics_dir/index_forecast/predictions_000001.SH_h3_rule_h3_v2.csv
output.reports_dir/index_forecast/000001.SH_h3_rule_h3_v2.html
```

第一版验证结论：

- `rule_h3_v2` 已明显优于 `rule_v1`，尤其修正了 `rule_v1` 在 test 区间多空收益差为负的问题。
- 第一轮优化后，`rule_h3_v2` 的 bull 触发从 `opportunity_score>=10 and adjusted_net_score>=5` 放宽到 `opportunity_score>=8 and adjusted_net_score>=5`；bear 触发从 `risk_score>=9 and adjusted_net_score<=-5` 放宽到 `risk_score>=8 and adjusted_net_score<=-4`。
- `test_2025_2026` 的 rank 标签下，`rule_v1` 平衡命中率约 31.6%，多空收益差约 -0.79%；优化后的 `rule_h3_v2` 平衡命中率约 38.3%，多空收益差约 +0.98%。
- 优化后的 `rule_h3_v2` 已接近 `simple_oversold_h3` 在 test 区间的多空收益差表现，但全样本和训练区间仍未完全稳定胜出；后续继续优化时要避免只按 2025-2026 过拟合。

第二轮诊断增强：

- `rule_h3_v2` 新增 `opportunity_reason`、`risk_reason`、`signal_reason`，用于解释每个信号的触发来源。
- `forecast-diagnose` 新增来源表现 CSV：

```text
output.statistics_dir/index_forecast/diagnostics_000001.SH_h3_rank_reasons.csv
```

第一版来源诊断观察：

- 表现较好的 bull 来源包括 `volume_down_repair`、`breakout_confirm`、`trend_breadth_support`、`volume_up_confirm`。
- 单纯 `oversold`、`release_confirm`、`breadth_delta_repair` 样本很多，但平均收益偏弱，会稀释 bull 质量。
- `kdj_low` 作为 bull 来源表现偏弱，后续不宜单独加分，应要求配合成交金额、广度修复或更深超跌。
- bear 来源中 `overheat_ad_weak`、`kdj_j_above_100`、`nhnl_weak` 整体方向有效；`upper_shadow` 单独作为风险不稳定，后续需要和滞涨或 NH-NL 走弱绑定。

### 阶段 6：模型对比报告

预测报告新增模型切换或对比区域：

```text
rule_v1 vs rule_h3_v2
```

重点展示：

- 分数桶单调性是否改善。
- bull/bear 分组收益差是否扩大。
- 择时曲线是否更稳。
- 2025-2026 测试区间是否仍有效。

### 阶段 7：再考虑机器学习

如果 `rule_h3_v2` 比 `rule_v1` 明显改善，再接入：

```text
logistic_h3_v1
hgb_h3_v1
```

机器学习模型必须：

- 只读取 `indicators_*.csv`。
- 只用训练区间拟合。
- 用验证区间调参。
- 用测试区间做最终评估。
- 输出特征重要性、概率校准和滚动测试结果。
- 通过 Claude Code 做一次代码和评估审计。

## 7. 最小可执行下一步

我建议下一步先做：

```text
index forecast-diagnose --symbol 000001.SH --horizon 3
```

先把“诊断报告”做出来。

原因：

- 当前结论来自一次手工分析。
- 后续每次调规则，都需要自动比较前后效果。
- 没有诊断报告，模型优化很容易变成凭感觉调参。

诊断报告出来后，再做 `rule_h3_v2`，这样每次修改都能马上看：

```text
有没有真的提高 bull/bear 分组收益差
有没有降低回撤
有没有提高分数桶单调性
有没有只在某一年有效
```

## 8. 当前结论

当前 `rule_v1` 对 3 日预测的主要问题不是“参数小修小补”，而是模型结构不适合短线：

1. 它把低分直接当作看空，但低分常常包含超跌反弹机会。
2. 它把趋势强弱当作方向判断，但 3 日更偏均值回归。
3. 它把放量下跌偏风险处理，但数据里放量下跌后短线反弹并不少。
4. 它的总分和未来 3 日收益几乎没有线性关系。
5. 它缺少模型诊断和版本比较机制。

因此，推荐方向是：

```text
先建诊断体系
再做 3 日专用 rule_h3_v2
然后再考虑机器学习模型
```

同时，在进入机器学习前，必须先完成：

```text
固定评估框架
固定基准模型
固定时间切分
固定上线门槛
固定诊断报告
```

否则复杂模型的提升很可能只是样本内调参结果。
