# 大盘预测策略后续改进与机器学习路线

> 口径更新（2026-07）：后续规则与机器学习模型均应预测 `positive/neutral/conservative` 横截面市场环境标签，不再以单一指数涨跌分类作为主目标。当前标签和无未来函数约束见 `docs/reference/index_forecast_report.md`。

本文基于当前 `rule_h3_v2`、诊断报告和 2011 年以来的上证指数样本，讨论大盘 3 日预测模型下一步怎么改，以及如果引入机器学习，方向、优势、风险和实施顺序是什么。

当前主线模型：

```text
rule_h3_v2
```

当前重点周期：

```text
horizon = 3 个交易日
```

相关说明：

```text
docs/reference/rule_h3_v2_model.md
docs/plans/INDEX_FORECAST_MODEL_IMPROVEMENT_PLAN.md
```

## 1. 当前模型状态判断

`rule_h3_v2` 相比 `rule_v1` 已经解决了几个关键问题：

| 问题 | `rule_v1` 问题 | `rule_h3_v2` 改进 |
| --- | --- | --- |
| 低分含义混乱 | 低分容易直接看空 | 拆成超跌修复和弱势延续 |
| 放量下跌误判 | 放量下跌偏扣分 | 超跌背景下可视为释放机会 |
| KDJ 高位误判 | `J>90` 容易直接偏空 | 必须叠加 A/D 转弱 |
| 信号不可解释 | 只有总分 | 输出机会、风险、趋势和来源字段 |

从当前诊断看，`rule_h3_v2` 的有效信号大致集中在：

| 类型 | 诊断观察 | 后续处理 |
| --- | --- | --- |
| 放量下跌修复 | `volume_down_repair` 表现较好 | 保留并细化 |
| 突破确认 | `breakout_confirm` 表现较好 | 加强趋势和广度确认 |
| 趋势广度共振 | `trend_breadth_support` 表现较好 | 保留作为趋势顺风 |
| 单纯超跌 | `oversold` 单独表现一般 | 降权，必须要二次确认 |
| 单纯 KDJ 低位 | `kdj_low` 表现偏弱 | 降权或改成观察条件 |
| KDJ 过热叠加广度弱 | `overheat_ad_weak` 有风险意义 | 保留并做分层 |
| 长上影 | `upper_shadow` 单独不稳定 | 只作为组合风险增强 |

结论：

```text
下一步不要简单继续加指标，而是要把“有效来源”和“无效来源”拆得更细。
```

## 2. 规则模型还能怎么改

### 2.1 先做来源分层，而不是整体调分

实施状态：已完成第一版。

当前 `rule_h3_v2` 的最大优势是有 `signal_reason`。下一步应该按来源拆分优化：

| 来源 | 当前问题 | 改进方向 |
| --- | --- | --- |
| `oversold` | 样本多但平均收益不强 | 单独不触发 `bull`，只作为候选状态 |
| `release_confirm` | 过宽，放量、振幅、广度修复混在一起 | 拆成成交金额释放、波动释放、广度修复 |
| `breadth_delta_repair` | 单独表现不强 | 要求同时满足超跌或 KDJ 深低位 |
| `kdj_low` | 单独偏弱 | `J < 0` 降权，`J < -10` 或 `J < -20` 才增强 |
| `volume_down_repair` | 表现较好但样本少 | 增加更严格的恐慌释放条件，避免泛化 |
| `breakout_confirm` | 表现较好 | 加入突破后是否接近前高、是否放量过猛 |
| `upper_shadow` | 单独不稳定 | 必须叠加放量滞涨或 NH-NL 转弱 |

建议规则：

```text
弱来源只做候选，不单独触发信号。
强来源可以直接提高机会/风险分。
来源组合比单个指标更重要。
```

当前已落地：

- `oversold` 从强触发源降为候选状态。
- `kdj_low` 改为 `kdj_low_confirm`，需要超跌或广度修复配合。
- `release_confirm` 拆成 `release_amount_confirm` 和 `release_range_confirm`。
- `upper_shadow` 必须叠加放量滞涨或 NH-NL 转弱才计入风险。
- `signal_reason` 优先展示主导机会来源。

### 2.2 把机会分拆成三个子模型

实施状态：已完成第一版。

当前 `opportunity_score` 可以进一步拆成：

```text
rebound_score      超跌修复
breakout_score     突破延续
trend_follow_score 趋势顺风
```

这样可以避免三种完全不同的机会混在一个分数里。

| 子分数 | 适合场景 | 核心指标 |
| --- | --- | --- |
| `rebound_score` | 下跌后短线修复 | `drawdown_20d`、`dist_ma20`、`J<-10`、放量释放 |
| `breakout_score` | 突破平台或 20 日新高 | `break_high_20d`、`amount_ratio_20`、`ad_norm` |
| `trend_follow_score` | 趋势多头继续走强 | 均线结构、`ad_slope_5`、`nhnl_slope_5` |

最终 `bull` 不再只看一个 `opportunity_score`，而是看：

```text
max(rebound_score, breakout_score, trend_follow_score)
```

优点：

- 解释更清楚。
- 可以分别调参。
- 可以发现到底是哪类机会贡献收益。

当前已落地输出字段：

```text
rebound_score
breakout_score
trend_follow_score
opportunity_type
rebound_reason
breakout_reason
trend_follow_reason
```

### 2.3 风险分拆成过热风险和破位风险

实施状态：已完成第一版。

当前 `risk_score` 可以拆成：

```text
overheat_risk_score   过热衰竭
breakdown_risk_score  弱势破位
```

| 子分数 | 适合场景 | 核心指标 |
| --- | --- | --- |
| `overheat_risk_score` | 涨多后转弱 | `J>90`、`ad_slope_5<0`、`nhnl_slope_3<=0`、滞涨 |
| `breakdown_risk_score` | 弱势继续下跌 | `break_low_20d`、均线下方、广度恶化、放量下跌 |

当前一个重要问题是：

```text
有些破位或放量下跌在 3 日维度反而会反弹。
```

所以破位风险不能只看下跌本身，还要看有没有恐慌释放和是否已经超跌。

当前已落地输出字段：

```text
overheat_risk_score
breakdown_risk_score
risk_type
overheat_risk_reason
breakdown_risk_reason
```

当前已落地：

- 过热风险继续由 `J>90 + A/D 转弱` 触发。
- 长上影必须叠加放量滞涨或 NH-NL 转弱才计入过热风险。
- 破位风险单独统计 `break_low_weak`、`below_ma60_break`、`trend_breadth_weak` 等来源。
- 深度超跌且成交金额释放时，对破位风险做折扣。
- 破位风险大多数时候只压制机会分或输出观察，不再单独轻易触发 `bear`。

### 2.4 增加市场状态分层

实施状态：已完成第一版。

同一个指标在不同市场环境下含义不同。

建议先把每一天归入状态：

| 状态 | 条件示例 | 含义 |
| --- | --- | --- |
| 趋势多头 | MA20>MA60，指数在 MA20 上方，A/D 斜率不弱 | 顺势信号更可信 |
| 强势震荡 | 指数在 MA60 上方但 MA20 反复穿越 | 低吸和突破都可观察 |
| 弱势震荡 | 指数在 MA60 下方但未持续新低 | 谨慎做反弹 |
| 单边下跌 | 跌破 MA60/MA120，A/D 和 NH-NL 同弱 | 反弹信号降仓位 |
| 高波动修复 | ATR/振幅分位较高，放量释放明显 | 短线修复信号更重要 |

信号阈值按状态调整：

```text
趋势多头：更容易接受 breakout/trend_follow。
弱势震荡：只接受 rebound，且仓位折扣。
单边下跌：除非强释放，否则不做 bull。
高波动修复：允许 volume_down_repair 触发机会。
```

当前已落地输出字段：

```text
market_regime
```

当前状态：

```text
trend_bull
high_vol_repair
downtrend
strong_range
weak_range
```

当前已落地：

- `trend_bull`：更容易接受突破/趋势跟随，bear 阈值更严格。
- `high_vol_repair`：更容易接受超跌修复，bear 阈值略严格。
- `downtrend`：bull 阈值更严格，除非是较强修复；bear 阈值略放宽。
- `weak_range`：bull 阈值略严格。

### 2.5 引入 MACD 但只作为过滤器

当前 `rule_h3_v2` 不直接使用 MACD，这是合理的，因为 3 日预测里 MACD 可能偏慢。

后续可以只用 MACD 做过滤，不做主信号：

| MACD 条件 | 用途 |
| --- | --- |
| `macd_hist_delta_3 > 0` | 超跌修复时确认动能边际改善 |
| `macd_hist_delta_3 < 0` | 过热风险时确认动能衰减 |
| `macd_dif_norm > 0` | 趋势背景增强 |
| `macd_gold` | 只给趋势顺风小加分 |

建议：

```text
MACD 不要直接触发 bull/bear，只做确认项。
```

### 2.6 分层 A/D 纳入规则

当前分层广度主要用于诊断，下一步可以让它参与模型：

| 分层 A/D | 判断 |
| --- | --- |
| 全A A/D 上升，沪深300 A/D 上升 | 普涨或共振，信号更强 |
| 沪深300 A/D 上升，全A A/D 下跌 | 权重护盘，谨慎看多 |
| 中证1000/2000 A/D 上升 | 小票赚钱效应改善 |
| 创业板 A/D 上升 | 成长风格风险偏好提升 |

建议先加两个差值特征：

```text
small_vs_large_ad = csi1000_ad_slope_5 - hs300_ad_slope_5
growth_vs_large_ad = chinext_ad_slope_5 - hs300_ad_slope_5
```

用途：

```text
指数上涨但小票/成长广度不跟，降低 bull 信号强度。
指数回调但小票/成长广度提前修复，提高 rebound_score。
```

## 3. 机器学习应该怎么上

机器学习不是替代规则模型，而是作为两件事：

```text
1. 学习指标权重和非线性组合。
2. 检查规则模型哪些判断被数据支持。
```

### 3.1 第一阶段：监督学习分类模型

目标：

```text
预测未来 3 日属于 bull / neutral / bear
```

推荐标签：

| 标签 | 用途 |
| --- | --- |
| `label_rank_3d` | 训练主标签，类别更均衡 |
| `label_abs_3d` | 交易解释辅助标签 |

第一批模型：

| 模型 | 名称建议 | 用途 |
| --- | --- | --- |
| 逻辑回归 | `logistic_h3_v1` | 线性基线，检查特征方向 |
| HistGradientBoosting | `hgb_h3_v1` | 非线性模型，捕捉组合关系 |

不建议第一版就上深度学习、LSTM 或复杂时序模型。原因：

- 单指数日线样本仍不算大。
- 金融市场噪声高。
- 当前最需要的是稳定评估，不是模型复杂度。

### 3.2 第二阶段：排序模型

如果分类效果一般，可以改成排序思路。

目标不是判断绝对涨跌，而是判断：

```text
未来 3 日收益处在历史分布的高位还是低位
```

可行方案：

| 方案 | 输出 |
| --- | --- |
| 回归未来收益 `fwd_ret_3d` | 得到连续预测分数 |
| 分类 `label_rank_3d` | 得到 top/bottom 概率 |
| 学习 `rank_score` | 只关心排序，不强调具体收益数值 |

评估重点：

```text
Rank IC
Top 30% 平均收益
Bottom 30% 平均收益
Top-Bottom Spread
```

### 3.3 第三阶段：规则 + 机器学习融合

机器学习模型如果有效，不建议立刻替换规则模型，而是先做融合：

```text
final_signal = rule_signal + ml_probability + regime_filter
```

融合方式：

| 方式 | 说明 |
| --- | --- |
| 规则兜底 | 规则模型输出解释，机器学习只调整置信度 |
| ML 过滤 | 规则 bull 但 ML 概率低，则降为 neutral |
| ML 增强 | 规则 neutral 但 ML 高置信，则进入观察或轻仓 |
| 风险否决 | ML 高风险时，降低规则 bull 仓位 |

第一版推荐：

```text
规则模型负责解释，机器学习负责置信度校准。
```

## 4. 机器学习相对当前规则方案的优势

### 4.1 自动学习权重

当前规则权重是人工设定：

```text
oversold +7
release_confirm +4
volume_down_repair +3
```

机器学习可以从历史中学习：

```text
哪些指标更重要
不同指标组合时权重如何变化
某些条件是否其实应该降权
```

优势：

- 减少人工拍脑袋调参。
- 能发现人工忽略的弱关系。
- 可以定期重新训练，适应市场阶段变化。

### 4.2 捕捉非线性组合

规则模型需要手工写：

```text
J > 90 且 A/D 转弱 且 NH-NL 转弱
```

树模型可以自动学习类似组合：

```text
如果 KDJ 高位、A/D 斜率低、成交金额放大但收益滞涨，则风险升高。
```

优势：

- 更适合处理指标之间的相互作用。
- 对阈值不需要完全手工固定。
- 可能识别“弱信号组合成强信号”的情况。

### 4.3 概率输出更容易校准

当前 `p_bull/p_bear` 是规则映射，不是真实概率。

机器学习可以输出：

```text
P(label_rank_3d = bull)
P(label_rank_3d = bear)
```

再配合校准：

```text
CalibratedClassifierCV
或按时间验证集做分桶校准
```

优势：

- 报告里的概率更接近历史发生率。
- 可以定义高置信信号。
- 可以用概率差值控制仓位。

### 4.4 更适合多指数共享学习

规则模型针对上证指数写死较多。

机器学习可以把多个指数合并训练：

```text
上证指数
沪深300
创业板指
中证500
中证1000
中证2000
```

加入字段：

```text
index_symbol
index_style
```

优势：

- 样本更多。
- 能比较不同风格指数的共性。
- 对风格切换可能更敏感。

注意：

```text
多指数不是完全独立样本，最终仍然要按指数单独评估。
```

## 5. 机器学习的主要风险

### 5.1 过拟合

A 股指数预测噪声很大。如果反复调模型、看测试结果再改参数，很容易把历史噪声当规律。

必须坚持：

```text
训练集调模型
验证集选参数
测试集只看一次
```

并且使用：

```text
purge_days = horizon
embargo_days = max(horizon, 5)
```

### 5.2 样本重叠

3 日预测天然有重叠：

```text
今天的未来 3 日收益
明天的未来 3 日收益
```

这两个标签共享部分未来区间。

因此：

- 不能随机切分。
- 不能把相邻日期直接一边训练、一边测试。
- 评估时要看滚动窗口稳定性。

### 5.3 概率容易被误读

机器学习输出的概率也不一定是真概率。

必须报告：

```text
Brier Score
Calibration Table
High Confidence Precision
```

如果概率没有校准，只能叫：

```text
模型置信度
```

不能叫：

```text
真实上涨概率
```

### 5.4 可解释性下降

规则模型能直接回答：

```text
为什么今天是 bull？
因为放量下跌修复 + A/D 边际修复。
```

机器学习如果直接上复杂模型，解释会变弱。

所以第一版必须输出：

| 内容 | 目的 |
| --- | --- |
| 特征重要性 | 看模型主要依赖什么 |
| 分组表现 | 看高概率信号是否真的好 |
| 规则对照 | 看 ML 和规则冲突时谁更可靠 |
| 错误案例 | 看模型常犯什么错 |

## 6. 推荐实施路线

### 阶段 A：规则模型继续收敛

目标：

```text
让 rule_h3_v2 更稳定、更可解释。
```

任务：

1. 拆分 `opportunity_score` 为 `rebound_score / breakout_score / trend_follow_score`。
2. 拆分 `risk_score` 为 `overheat_risk_score / breakdown_risk_score`。
3. 降低 `oversold`、`kdj_low` 的单独权重。
4. 强化 `volume_down_repair`、`breakout_confirm`、`trend_breadth_support`。
5. 长上影、滞涨、NH-NL 转弱必须组合使用。
6. 把 MACD 柱体变化作为过滤器，而不是主信号。

验收：

```text
rule_h3_v3 在 test_2025_2026 上 long_short_spread 不低于 rule_h3_v2。
年度表现不能明显劣化。
neutral_ratio 不能过高到失去使用意义。
```

### 阶段 B：固定机器学习数据集

目标：

```text
生成可复用的 ML 训练表。
```

输出：

```text
output.statistics_dir/index_forecast/ml_dataset_000001.SH_h3.csv
```

字段分区：

| 区域 | 示例 |
| --- | --- |
| ID 字段 | `trade_date`, `symbol`, `horizon` |
| 特征字段 | 当前 indicators 宽表里的可用指标 |
| 规则字段 | `rule_h3_v2` 的各子分数和来源 |
| 标签字段 | `fwd_ret_3d`, `label_abs_3d`, `label_rank_3d` |
| 切分字段 | `split`, `fold_id`, `purge_group` |

要求：

```text
同一份数据集供 Logistic、HGB、后续模型共同使用。
不要每个模型各自重新拼数据。
```

### 阶段 C：逻辑回归基线

目标：

```text
建立第一个可解释机器学习基线。
```

模型：

```text
logistic_h3_v1
```

建议参数：

```text
model = LogisticRegression(
    penalty="l2",
    C in [0.1, 0.3, 1.0, 3.0],
    class_weight="balanced",
    max_iter=2000
)
```

预处理：

```text
缺失值填充：训练集 median
标准化：StandardScaler
异常值裁剪：1% ~ 99% 分位
```

评估：

```text
balanced_accuracy
long_short_spread
rank_ic
timing_return
timing_max_drawdown
calibration
```

价值：

- 看线性权重是否和规则经验一致。
- 判断哪些指标方向可靠。
- 作为 HGB 的低复杂度基准。

### 阶段 D：HistGradientBoosting

目标：

```text
测试非线性组合是否明显优于规则和线性模型。
```

模型：

```text
hgb_h3_v1
```

建议参数范围：

```text
max_iter: [80, 120, 180]
learning_rate: [0.03, 0.05, 0.08]
max_leaf_nodes: [7, 15, 31]
l2_regularization: [0.0, 0.1, 1.0]
min_samples_leaf: [20, 40, 80]
```

约束：

- 只在验证集选参数。
- 测试集只做最终报告。
- 如果 HGB 只在训练集好，测试集不如 Logistic 或 rule，则不进入默认展示。

### 阶段 E：规则 + ML 融合

目标：

```text
让模型更强，但保留解释。
```

第一版融合规则：

```text
if rule_signal == bull and ml_p_bull >= 0.45:
    final_signal = bull
elif rule_signal == bear and ml_p_bear >= 0.45:
    final_signal = bear
elif ml_p_bull - ml_p_bear >= 0.25 and rule_signal != bear:
    final_signal = watch_bull
elif ml_p_bear - ml_p_bull >= 0.25 and rule_signal != bull:
    final_signal = watch_bear
else:
    final_signal = neutral
```

报告上区分：

| 字段 | 含义 |
| --- | --- |
| `rule_signal` | 规则模型信号 |
| `ml_signal` | 机器学习信号 |
| `final_signal` | 融合后信号 |
| `conflict_flag` | 规则和 ML 是否冲突 |
| `decision_reason` | 最终采用原因 |

## 7. 机器学习上线门槛

机器学习模型不能因为某次报告好看就上线。建议设置硬门槛：

| 维度 | 门槛 |
| --- | --- |
| 基准比较 | 测试期 `long_short_spread` 高于 `rule_h3_v2` 或明显改善风险 |
| 稳定性 | 至少 60% 滚动窗口优于 `always_neutral` 和 `buy_and_hold` 择时 |
| 回撤 | 策略化最大回撤不高于买入持有 |
| 置信度 | 高置信样本表现优于低置信样本 |
| 概率校准 | Calibration Table 不出现严重反向 |
| 可解释 | 能输出主要特征和错误案例 |
| 工程稳定 | 同一命令可复现训练、预测、评估和报告 |

如果不满足：

```text
模型只作为实验报告，不作为默认信号。
```

## 8. 推荐下一步

推荐先做：

```text
阶段 A：规则模型继续收敛
```

原因：

- 当前 `rule_h3_v2` 已经有来源诊断，能直接指导调优。
- 规则模型仍然是解释最强的主线。
- 机器学习前需要先把特征、标签、切分和评估口径固化。

然后做：

```text
阶段 B：固定 ML 数据集
阶段 C：逻辑回归基线
```

暂时不建议立刻把 HGB 放到默认报告里。更合理的顺序是：

```text
先用 Logistic 验证特征方向和评估框架。
再用 HGB 检查非线性增益。
最后再考虑规则 + ML 融合。
```

核心原则：

```text
规则模型负责可解释。
机器学习负责学习权重和校准置信度。
评估框架负责防止过拟合。
```
