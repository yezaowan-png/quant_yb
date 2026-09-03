# rule_h3_v2 大盘 3 日预测模型说明

本文说明 `rule_h3_v2` 的设计目标、输入数据、指标含义、评分规则和输出字段。对应实现位置：

```text
analysis/index_forecast.py
```

常用命令：

```shell
python main.py index forecast --symbol 000001.SH --horizon 3 --model rule_h3_v2
python main.py index forecast-diagnose --symbol 000001.SH --horizon 3 --label-mode rank
```

输出文件示例：

```text
output.statistics_dir/index_forecast/indicators_000001.SH.csv
output.statistics_dir/index_forecast/features_000001.SH.csv
output.statistics_dir/index_forecast/predictions_000001.SH_h3_rule_h3_v2.csv
output.reports_dir/index_forecast/000001.SH_h3_rule_h3_v2.html
```

## 1. 模型定位

`rule_h3_v2` 是一个面向大盘指数未来 3 个交易日环境的规则模型。它不预测具体点位，而是输出：

| 输出 | 含义 |
| --- | --- |
| `bull` | 未来 3 日偏机会，进攻环境更好 |
| `neutral` | 方向不明确，保持观察或中性仓位 |
| `bear` | 未来 3 日偏风险，防守优先 |

它和 `rule_v1` 的核心区别：

| 项目 | `rule_v1` | `rule_h3_v2` |
| --- | --- | --- |
| 评分方式 | 单一总分累计 | 机会分、风险分、趋势背景分三轴 |
| 低分处理 | 低分容易直接看空 | 低分拆成弱势和超跌修复 |
| 放量下跌 | 偏扣分 | 若处于超跌背景，可能转为机会 |
| KDJ 过热 | `J>90` 直接偏风险 | 必须叠加广度转弱等条件 |
| 可解释性 | 只有模块分 | 增加 `signal_reason` 来源解释 |

## 2. 数据来源

### 2.1 指数日线

指数日线由 Tushare 指数行情下载后缓存到本地。模型至少需要：

| 字段 | 含义 |
| --- | --- |
| `open` | 开盘点位 |
| `high` | 最高点位 |
| `low` | 最低点位 |
| `close` | 收盘点位 |
| `volume` | 成交量 |
| `amount` | 成交金额 |
| `pct_chg` | 涨跌幅 |

在代码中，基础日线先经过 `_prepare_index_frame()` 清洗，生成统一字段：

| 字段 | 含义 |
| --- | --- |
| `trade_date` | `YYYY-MM-DD` 格式交易日 |
| `symbol` | 指数代码 |

### 2.2 全市场广度

全市场广度来自本地股票 K 线缓存。每个交易日统计：

| 字段 | 含义 |
| --- | --- |
| `breadth_up` | 上涨股票家数 |
| `breadth_down` | 下跌股票家数 |
| `breadth_flat` | 平盘股票家数 |
| `new_high` | 近一年新高股票数 |
| `new_low` | 近一年新低股票数 |

广度数据用于计算 A/D、NH-NL 以及它们的斜率。

### 2.3 分层广度

分层广度用于判断风格结构，例如沪深300、全A、中证1000、创业板之间的强弱差异。当前 `rule_h3_v2` 主要直接使用全市场广度，分层广度更多用于诊断和后续模型扩展。

## 3. 指标宽表

`indicators_000001.SH.csv` 是模型输入宽表。它只包含当日收盘后已知信息，不包含未来收益标签。

生成流程：

```text
指数日线 -> _add_index_features()
全市场广度 -> _breadth_frame()
分层广度 -> _group_breadth_frame()
合并 -> build_index_forecast_indicators()
```

当前 `rule_h3_v2` 直接参与打分的指标类别是：

| 类别 | 是否直接打分 | 说明 |
| --- | --- | --- |
| 指数趋势/均线 | 是 | 判断趋势背景，只轻微修正 3 日短线信号 |
| 短线收益/回撤/突破 | 是 | 判断超跌、突破和破位 |
| 成交金额 | 是 | 判断放量上涨、放量下跌和放量滞涨 |
| KDJ | 是 | 重点使用 J 值的负值机会和高位风险 |
| A/D 标准化腾落线 | 是 | 主要使用斜率和斜率变化 |
| NH-NL 新高新低 | 是 | 主要使用短期斜率辅助确认风险 |
| MACD | 否 | 当前仅生成到宽表，`rule_h3_v2` 暂未直接计分 |
| 分层广度 | 否 | 当前用于诊断和后续扩展，暂未直接计分 |

## 4. 指数自身指标

### 4.1 收益率

对收盘价计算多个周期收益：

```text
ret_Nd = close[t] / close[t-N] - 1
```

当前生成：

```text
ret_1d
ret_3d
ret_5d
ret_10d
ret_20d
ret_60d
```

`rule_h3_v2` 主要使用：

| 字段 | 用途 |
| --- | --- |
| `ret_5d` | 判断短线是否超跌 |
| `ret_20d` | 判断趋势背景是否偏强 |

### 4.2 均线和乖离

计算 MA5、MA10、MA20、MA60、MA120、MA250：

```text
maN = close 的 N 日移动平均
dist_maN = close / maN - 1
```

`rule_h3_v2` 主要使用：

| 字段 | 含义 | 用途 |
| --- | --- | --- |
| `above_ma20` | 收盘在 MA20 上方 | 趋势背景 |
| `above_ma60` | 收盘在 MA60 上方 | 趋势背景 |
| `ma20_gt_ma60` | MA20 > MA60 | 趋势背景 |
| `ma60_gt_ma120` | MA60 > MA120 | 趋势背景 |
| `ma20_slope_5` | MA20 近 5 日变化率 | 趋势背景 |
| `dist_ma20` | 收盘相对 MA20 乖离 | 超跌、过热风险 |

### 4.3 回撤和突破

对 20、60、120 日窗口计算：

```text
drawdown_Nd = close / rolling_high_N - 1
break_high_Nd = close >= rolling_high_N
break_low_Nd = close <= rolling_low_N
```

`rule_h3_v2` 主要使用：

| 字段 | 含义 | 用途 |
| --- | --- | --- |
| `drawdown_20d` | 20 日高点以来回撤 | 判断超跌 |
| `break_high_20d` | 20 日新高 | 判断短线突破机会 |
| `break_low_20d` | 20 日新低 | 判断弱势风险 |

### 4.4 波动和影线

ATR 使用真实波幅：

```text
true_range = max(high-low, abs(high-prev_close), abs(low-prev_close))
atrN_pct = MA(true_range, N) / close
```

其他波动指标：

```text
volatility_10d = ret_1d 的 10 日标准差
volatility_20d = ret_1d 的 20 日标准差
intraday_range_pct = (high - low) / close
upper_shadow_ratio = 上影线长度 / (high - low)
lower_shadow_ratio = 下影线长度 / (high - low)
```

`rule_h3_v2` 主要使用：

| 字段 | 含义 | 用途 |
| --- | --- | --- |
| `intraday_range_pct` | 当日振幅 | 超跌释放确认 |
| `upper_shadow_ratio` | 上影线比例 | 过热风险增强 |

## 5. 成交金额指标

成交金额比成交量更适合指数分析，因此模型优先使用 `amount`。

计算：

```text
amount_ratio_20 = amount / MA(amount, 20)
amount_ma5_ratio_20 = MA(amount, 5) / MA(amount, 20)
amount_slope_5_20 = amount_ma5_ratio_20 - 1
```

衍生布尔条件：

```text
amount_up_confirm = ret_1d > 0 且 amount_ratio_20 > 1.2
amount_down_expand = ret_1d < 0 且 amount_ratio_20 > 1.2
amount_stalling =
    amount_ratio_20 >= 1.5
    且 abs(ret_1d) <= 0.5 * atr20_pct
    且 upper_shadow_ratio >= 0.35
    且 close >= ma20
```

含义：

| 字段 | 含义 | 模型用途 |
| --- | --- | --- |
| `amount_ratio_20` | 今日成交金额相对 20 日均值 | 放量确认 |
| `amount_up_confirm` | 放量上涨 | 机会加分 |
| `amount_down_expand` | 放量下跌 | 超跌时转为释放机会，非超跌时可能是风险 |
| `amount_stalling` | 高位放量滞涨 | 过热风险增强 |

## 6. KDJ 指标

KDJ 计算：

```text
low9 = 9日最低价
high9 = 9日最高价
RSV = (close - low9) / (high9 - low9) * 100
K = RSV 的 3 日均值
D = K 的 3 日均值
J = 3K - 2D
```

为了统一量纲，宽表里的 `kdj_k`、`kdj_d`、`kdj_j` 会除以 100，但布尔条件仍按原始 KDJ 数值判断：

| 字段 | 条件 | 含义 |
| --- | --- | --- |
| `kdj_j_below_0` | J < 0 | 短线低位 |
| `kdj_j_below_minus10` | J < -10 | 深度短线超跌 |
| `kdj_j_above_90` | J > 90 | 短线过热 |
| `kdj_j_above_100` | J > 100 | 更强过热 |

`rule_h3_v2` 的关键点：

- `J < -10` 可以作为超跌条件之一。
- `J < 0` 只给较小机会分。
- `J > 90` 不单独看空，必须叠加 A/D 斜率转弱。
- `J > 100` 只是风险增强项。

## 7. MACD 指标

MACD 当前会被写入指标宽表，但 `rule_h3_v2` 这一版没有直接使用 MACD 加减分。保留它的原因是：

- 方便和旧版 `rule_v1` 对照。
- 后续可以评估 MACD 柱体斜率、DIF/DEA 位置是否有增量价值。
- 避免一次性把太多动量指标混入 3 日预测，导致规则不可解释。

当前生成字段：

| 字段 | 含义 | 当前用途 |
| --- | --- | --- |
| `macd_dif_norm` | DIF / close | 暂未直接计分 |
| `macd_dea_norm` | DEA / close | 暂未直接计分 |
| `macd_hist_norm` | MACD 柱 / close | 暂未直接计分 |
| `macd_diff_norm` | `(DIF - DEA) / close` | 暂未直接计分 |
| `macd_hist_delta_1` | MACD 柱 1 日变化 / close | 暂未直接计分 |
| `macd_hist_delta_3` | MACD 柱 3 日变化 / close | 暂未直接计分 |
| `macd_hist_delta_5` | MACD 柱 5 日变化 / close | 暂未直接计分 |
| `macd_gold` | DIF > DEA | `rule_v1` 使用，`rule_h3_v2` 暂未使用 |
| `macd_dif_above_zero` | DIF > 0 | `rule_v1` 使用，`rule_h3_v2` 暂未使用 |
| `macd_dea_above_zero` | DEA > 0 | 暂未直接计分 |
| `macd_hist_up_3` | MACD 柱连续 3 日走强 | `rule_v1` 使用，`rule_h3_v2` 暂未使用 |
| `macd_hist_down_3` | MACD 柱连续 3 日走弱 | `rule_v1` 使用，`rule_h3_v2` 暂未使用 |

也就是说，当前 `rule_h3_v2` 的短线动量核心不是 MACD，而是：

```text
KDJ 极值 + A/D 斜率 + 成交金额确认
```

## 8. A/D 广度指标

每日标准化广度：

```text
ad_norm = (上涨家数 - 下跌家数) / (上涨家数 + 下跌家数)
```

累计 A/D 线：

```text
ad_norm_line = ad_norm 的累计和
```

斜率：

```text
ad_slope_N = ad_norm_line[t] - ad_norm_line[t-N]
ad_slope_5_delta = ad_slope_5 今日值 - 昨日值
```

`rule_h3_v2` 使用：

| 字段 | 含义 | 用途 |
| --- | --- | --- |
| `ad_norm` | 当日全市场涨跌广度 | 突破确认 |
| `ad_slope_5` | 近 5 日广度变化 | 判断机会是否有广度支持，过热是否转弱 |
| `ad_slope_5_delta` | 5 日广度斜率的变化 | 超跌释放确认 |

## 9. NH-NL 新高新低指标

每日 NH-NL：

```text
nhnl = new_high - new_low
nhnl_norm = nhnl / breadth_total
```

斜率：

```text
nhnl_slope_N = nhnl_norm[t] - nhnl_norm[t-N]
```

`rule_h3_v2` 使用：

| 字段 | 含义 | 用途 |
| --- | --- | --- |
| `nhnl_slope_3` | 近 3 日新高新低力量变化 | 过热风险增强 |

当 `J > 90` 且 A/D 已经转弱，如果 `nhnl_slope_3 <= 0`，说明领涨力量没有继续扩散，风险更可信。

## 10. 三轴评分

`rule_h3_v2` 不直接用一个大分数判断，而是先算三条轴：

```text
trend_context_score
opportunity_score
risk_score
```

再计算：

```text
net_score = opportunity_score - risk_score
adjusted_net_score = net_score + (trend_context_score - 9) * 0.25
market_score = clip(50 + adjusted_net_score * 2, 0, 100)
```

其中：

- `net_score` 是机会和风险的直接差值。
- `adjusted_net_score` 只让趋势背景轻微修正短线信号。
- `market_score` 是给图表展示用的 0 到 100 分。

## 11. 趋势背景分

趋势背景分不直接决定 3 日方向，只做环境过滤。

评分规则：

| 条件 | 加减分 |
| --- | ---: |
| `above_ma20` 为真 | +4 |
| `above_ma20` 为假 | -1 |
| `above_ma60` 为真 | +4 |
| `above_ma60` 为假 | -1 |
| `ma20_gt_ma60` 为真 | +3 |
| `ma20_gt_ma60` 为假 | -1 |
| `ma60_gt_ma120` 为真 | +2 |
| `ma20_slope_5 > 0` | +2 |
| `ma20_slope_5 <= 0` | -1 |
| `ret_20d > 0` | +1.5 |
| `ret_20d <= 0` | -0.5 |

最后限制：

```text
trend_context_score = clip(trend_context_score, 0, 18)
```

## 12. 机会分

当前机会分已经从单一累加改成三类机会子分数：

```text
rebound_score       超跌修复分
breakout_score      突破确认分
trend_follow_score  趋势跟随分
```

最终：

```text
opportunity_score = max(rebound_score, breakout_score, trend_follow_score) + synergy
```

这样做的目的：

- 避免 `oversold`、`kdj_low` 这类弱来源单独堆出高分。
- 把超跌修复、突破延续、趋势顺风三类机会分开诊断。
- `signal_reason` 优先展示主导机会来源，而不是把所有来源混在一起。

### 12.1 超跌条件

满足任一条件即视为 `oversold`：

```text
drawdown_20d < -2%
或 dist_ma20 < -2%
或 ret_5d < -2%
或 kdj_j_below_minus10 = True
```

深度超跌 `deep_oversold` 条件更严格：

```text
drawdown_20d < -3.5%
或 dist_ma20 < -3%
或 ret_5d < -3.5%
或 kdj_j_below_minus10 = True
```

### 12.2 超跌修复分 rebound_score

`rebound_score` 只处理下跌后的修复机会。

| 条件 | 加分 | 来源标记 |
| --- | ---: | --- |
| `oversold` | +4 | `oversold` |
| `deep_oversold` | +2 | `deep_oversold` |
| `oversold` 且 `amount_ratio_20 > 1.1` | +2 | `release_amount_confirm` |
| `oversold` 且 `intraday_range_pct > 2.5%` | +1.5 | `release_range_confirm` |
| `oversold` 且 `amount_down_expand` | +3.5 | `volume_down_repair` |
| `oversold` 且 `ad_slope_5_delta > 0` | +2 | `breadth_delta_repair` |
| `oversold` 且 `kdj_j_below_minus10` | +2 | `kdj_deep_low` |
| `oversold` 且 `kdj_j_below_0` | +1 | `kdj_low_confirm` |
| 非 `oversold`，但 `J < -10` 且有放量或广度修复 | +4 起 | `kdj_deep_low` |

最后限制：

```text
rebound_score = clip(rebound_score, 0, 16)
```

注意：

- `kdj_j_below_0` 不再单独触发高机会分。
- `oversold` 从原来的 +7 降到 +4，必须叠加释放确认才更容易触发 `bull`。
- `volume_down_repair` 只在超跌背景中作为机会来源。

### 12.3 突破确认分 breakout_score

| 条件 | 加分 | 来源标记 |
| --- | ---: | --- |
| `break_high_20d` 且 `amount_ratio_20 > 1.1` 且 `ad_norm > 0` | +7 | `breakout_confirm` |
| 上述突破且 `ad_slope_5 > 0` | +2 | `breakout_breadth_follow` |
| 上述突破且放量不过猛 `amount_ratio_20 <= 1.8` | +1 | `breakout_volume_healthy` |
| `amount_up_confirm` 且 `ad_slope_5 > 0` | +3 | `volume_up_confirm` |
| 放量上涨且 `trend_context_score >= 11` | +1 | `volume_trend_support` |

最后限制：

```text
breakout_score = clip(breakout_score, 0, 14)
```

### 12.4 趋势跟随分 trend_follow_score

| 条件 | 加分 | 来源标记 |
| --- | ---: | --- |
| `trend_context_score >= 11` 且 `ad_slope_5 > 0` | +5 | `trend_breadth_support` |
| 上述趋势且 `nhnl_slope_3 > 0` 或 `nhnl_slope_5 > 0` | +2 | `trend_nhnl_support` |
| 上述趋势且 `amount_up_confirm` | +2 | `trend_volume_support` |
| 上述趋势且 `ret_20d > 0` | +1 | `trend_return_support` |

最后限制：

```text
trend_follow_score = clip(trend_follow_score, 0, 12)
```

### 12.5 opportunity_score 合成

先取三类机会最高分：

```text
base_opportunity = max(rebound_score, breakout_score, trend_follow_score)
```

如果至少两类机会子分数同时达到 5 分以上，加协同分：

```text
synergy += 2
```

如果超跌修复达到 8 分，且突破或趋势跟随达到 5 分，再额外加一点：

```text
synergy += 1
```

最终：

```text
opportunity_score = clip(base_opportunity + synergy, 0, 24)
```

## 13. 风险分

当前风险分已经从单一累加拆成两类风险子分数：

```text
overheat_risk_score   过热衰竭风险
breakdown_risk_score  弱势破位风险
```

最终：

```text
risk_score = max(overheat_risk_score, breakdown_risk_score) + risk_synergy
```

这样做的目的：

- 避免把“涨多后衰竭”和“弱势破位”混成同一个风险。
- 放量下跌、破位下跌如果已经深度超跌，会做风险折扣。
- 后续可以分别诊断高位风险和弱势延续风险。

### 13.1 过热转弱

基础风险条件：

```text
overheat_weak = kdj_j_above_90 且 ad_slope_5 < 0
```

注意：`J > 90` 单独不构成看空，必须广度转弱。

### 13.2 过热风险分 overheat_risk_score

| 条件 | 加分 | 来源标记 |
| --- | ---: | --- |
| `overheat_weak` | +6 | `overheat_ad_weak` |
| `overheat_weak` 且 `kdj_j_above_100` | +3 | `kdj_j_above_100` |
| `overheat_weak` 且 `nhnl_slope_3 <= 0` | +3 | `nhnl_weak` |
| `overheat_weak` 且 `upper_shadow_ratio > 0.35` 且伴随放量滞涨或 NH-NL 转弱 | +2 | `upper_shadow` |
| `overheat_weak` 且 `amount_stalling` | +3 | `amount_stalling` |
| `overheat_weak` 且 `dist_ma20 > 2%` | +2 | `high_above_ma20` |

最后限制：

```text
overheat_risk_score = clip(overheat_risk_score, 0, 18)
```

### 13.3 破位风险分 breakdown_risk_score

| 条件 | 加分/减分 | 来源标记 |
| --- | ---: | --- |
| `amount_down_expand` 且非超跌且 `ad_slope_5 < 0` | +4 | `volume_down_weak` |
| `break_low_20d` 且 `ad_slope_5 < 0` | +3 | `break_low_weak` |
| 上述破位且指数在 MA60 下方 | +2 | `below_ma60_break` |
| 上述破位且 `ma20_slope_5 <= 0` | +1 | `ma20_slope_weak` |
| 指数在 MA60 下方，A/D 和 NH-NL 同弱 | +3 | `trend_breadth_weak` |
| 近 5 日跌幅超过 2%，未深度超跌且 A/D 弱 | +2 | `short_down_weak` |
| 深度超跌且成交金额释放 | -2 | `deep_oversold_risk_discount` |

最后限制：

```text
breakdown_risk_score = clip(breakdown_risk_score, 0, 18)
```

### 13.4 risk_score 合成

先取两类风险最高分：

```text
risk_score = max(overheat_risk_score, breakdown_risk_score)
```

如果过热风险和破位风险同时达到 6 分以上，额外加协同风险：

```text
risk_score += 2
```

如果处于单边下跌状态，且破位风险达到 5 分以上，额外加一点：

```text
risk_score += 1
```

如果处于高波动修复状态，破位风险会做一点折扣：

```text
risk_score -= 1
```

最后限制：

```text
risk_score = clip(risk_score, 0, 24)
```

## 14. 市场状态 market_regime

`market_regime` 用于给信号阈值做轻微调整，不直接覆盖机会分和风险分。

当前状态：

| 状态 | 判断逻辑 | 信号影响 |
| --- | --- | --- |
| `trend_bull` | 趋势分较高，指数站上 MA20/MA60，MA20>MA60，A/D 不弱 | 更容易接受突破和趋势跟随，bear 阈值更严格 |
| `high_vol_repair` | 已超跌，同时出现放量下跌、放量、振幅扩大或广度修复 | 更容易接受超跌修复，bear 阈值略严格 |
| `downtrend` | MA60/MA120 下方，MA20 斜率不强，且 A/D 弱或破位 | bull 阈值更严格，bear 阈值略放宽 |
| `strong_range` | MA60 上方且趋势分不差 | 使用默认阈值 |
| `weak_range` | 其他偏弱震荡状态 | bull 阈值略严格 |

## 15. 信号生成

先计算：

```text
net_score = opportunity_score - risk_score
adjusted_net_score = net_score + (trend_context_score - 9) * 0.25
```

信号规则：

```text
if opportunity_score >= bull_min and adjusted_net_score >= bull_adjusted_min and bull_allowed:
    signal = bull
elif risk_score >= bear_min and adjusted_net_score <= bear_adjusted_max:
    signal = bear
else:
    signal = neutral
```

解释：

- `bull` 必须既有机会分，也要净机会足够高。
- `bear` 必须风险分足够高，且调整后净分明显偏负。
- `bear` 还必须有过热风险来源，或极少数非超跌背景下的放量破位来源；破位风险大多数时候只做观察和压制机会分。
- 低趋势背景不会直接变成 `bear`，它只会轻微拖低 `adjusted_net_score`。
- `downtrend` 状态下，除非是较强修复信号，否则不允许轻易输出 `bull`。

## 16. 概率近似

`p_bull`、`p_neutral`、`p_bear` 是规则映射出来的概率近似值，不是机器学习模型训练出的真实概率。

原始值：

```text
bull_raw = clip(0.25 + adjusted_net_score / 30, 0.05, 0.90)
bear_raw = clip(0.25 - adjusted_net_score / 30 + risk_score / 80, 0.05, 0.90)
neutral_raw = max(0.10, 1 - abs(adjusted_net_score) / 18)
```

归一化：

```text
p_bull = bull_raw / (bull_raw + neutral_raw + bear_raw)
p_neutral = neutral_raw / (bull_raw + neutral_raw + bear_raw)
p_bear = bear_raw / (bull_raw + neutral_raw + bear_raw)
```

注意：

- 这些概率主要用于排序和可视化。
- 当前诊断报告会输出概率校准表，检查预测概率和真实发生率是否匹配。
- 不应把 `p_bull=60%` 理解成严格统计意义上的 60% 上涨概率。

## 17. 来源字段

`rule_h3_v2` 输出多类来源字段：

| 字段 | 含义 |
| --- | --- |
| `opportunity_type` | 当前主导机会类型：`rebound`、`breakout`、`trend_follow` |
| `rebound_reason` | 超跌修复分由哪些条件贡献 |
| `breakout_reason` | 突破确认分由哪些条件贡献 |
| `trend_follow_reason` | 趋势跟随分由哪些条件贡献 |
| `overheat_risk_reason` | 过热风险分由哪些条件贡献 |
| `breakdown_risk_reason` | 破位风险分由哪些条件贡献 |
| `opportunity_reason` | 机会分由哪些条件贡献 |
| `risk_reason` | 风险分由哪些条件贡献 |
| `signal_reason` | 最终信号主要原因 |

来源使用 `|` 连接，例如：

```text
oversold|release_amount_confirm|breadth_delta_repair
overheat_ad_weak|kdj_j_above_100|upper_shadow
```

常见来源含义：

| 来源 | 含义 |
| --- | --- |
| `oversold` | 出现短线超跌 |
| `deep_oversold` | 深度短线超跌 |
| `release_amount_confirm` | 超跌后成交金额放大 |
| `release_range_confirm` | 超跌后日内振幅放大 |
| `volume_down_repair` | 放量下跌发生在超跌背景中，被视作释放 |
| `breadth_delta_repair` | A/D 斜率边际改善 |
| `kdj_deep_low` | KDJ J < -10 |
| `kdj_low_confirm` | KDJ J < 0 且有超跌或广度修复配合 |
| `volume_up_confirm` | 放量上涨且广度向上 |
| `breakout_confirm` | 20 日突破且量能、广度配合 |
| `breakout_breadth_follow` | 突破后 A/D 斜率继续向上 |
| `breakout_volume_healthy` | 突破放量但未极端放量 |
| `volume_trend_support` | 放量上涨且趋势背景偏强 |
| `trend_breadth_support` | 趋势背景和广度同时偏强 |
| `trend_nhnl_support` | 趋势背景中 NH-NL 继续改善 |
| `trend_volume_support` | 趋势背景中放量上涨 |
| `trend_return_support` | 趋势背景中 20 日收益为正 |
| `overheat_ad_weak` | KDJ 过热且 A/D 斜率转弱 |
| `kdj_j_above_100` | KDJ J > 100 |
| `nhnl_weak` | 新高新低力量转弱 |
| `upper_shadow` | 长上影风险 |
| `amount_stalling` | 放量滞涨 |
| `high_above_ma20` | 明显高于 MA20 |
| `volume_down_weak` | 非超跌背景下放量下跌且广度弱 |
| `break_low_weak` | 20 日新低且广度弱 |
| `below_ma60_break` | MA60 下方破位 |
| `ma20_slope_weak` | MA20 斜率走弱 |
| `trend_breadth_weak` | 趋势和广度同弱 |
| `short_down_weak` | 短线下跌且广度弱 |
| `deep_oversold_risk_discount` | 深度超跌后的破位风险折扣 |

## 18. 标签和评估

模型预测本身不使用未来收益。未来收益只用于评估。

常用标签：

| 标签 | 含义 |
| --- | --- |
| `label_3d` | 旧 ATR 自适应阈值标签 |
| `label_abs_3d` | 固定 ±0.8% 标签 |
| `label_rank_3d` | 滚动历史分位标签 |

推荐优先看：

```shell
python main.py index forecast-diagnose --symbol 000001.SH --horizon 3 --label-mode rank
```

原因：

- `rank` 标签更均衡，适合评估模型排序能力。
- `legacy` 标签中 `neutral` 占比过高，容易让“永远中性”的模型看起来不错。
- `abs` 标签更直观，适合检查交易解释。

## 19. 目前诊断结论

截至当前第一版来源诊断：

| 观察 | 含义 |
| --- | --- |
| `volume_down_repair` 表现较好 | 放量下跌如果发生在超跌背景里，确实可能是释放 |
| `breakout_confirm` 表现较好 | 放量且广度配合的 20 日突破有价值 |
| `trend_breadth_support` 表现较好 | 趋势和广度共振时，短线更容易偏强 |
| 单纯 `oversold` 表现一般 | 超跌本身不够，最好有释放确认 |
| `kdj_low` 表现偏弱 | J < 0 不能单独作为机会，应要求更深超跌或配合量能/广度 |
| `overheat_ad_weak` 有效 | 过热叠加广度转弱，确实有短线风险意义 |
| `upper_shadow` 单独不稳定 | 长上影最好和滞涨、NH-NL 转弱一起使用 |

## 20. 当前限制

- `rule_h3_v2` 是人工规则模型，不是机器学习模型。
- 概率值未做真实概率校准，只是规则映射。
- 目前主要为上证指数 3 日预测优化，其他指数和周期需要单独验证。
- 当前回测评估仍存在指数样本相对有限、未来 3 日收益窗口重叠等问题。
- 模型用于大盘环境判断，不构成投资建议。
