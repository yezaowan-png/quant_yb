# 大盘指数预测模型实现计划

> 口径更新（2026-07）：主预测目标已重构为未来个股横截面市场环境标签，指数未来收益仅作辅助诊断。当前实现与字段以 `docs/reference/index_forecast_report.md` 和 `docs/reference/contracts.md` 为准；本文后续涉及单指数收益标签的内容仅保留为历史方案。

> 说明：本文件沿用当前文件名 `index_forcast.md`。后续代码模块建议统一使用正确拼写 `forecast`。

## 1. 目标与边界

目标不是预测指数精确点位，而是预测大盘未来一段时间的“风险收益状态”：

- 预测对象：第一阶段只做 `000001.SH` 上证指数。
- 预测周期：默认 1 ， 3， 5 个交易日和 10 个交易日。
- 输出结果：看多、震荡、看空三类概率，以及一个可解释的大盘风险分数。
- 使用方式：每日收盘后生成预测，辅助判断次日及后续一段时间的大盘环境。

第一版不直接参与交易下单，也不改现有策略信号，只作为指数环境看板的一部分。

## 2. 预测标签设计

### 2.1 未来收益

对每个交易日 `t`，计算未来 `H` 个交易日收益：

```text
fwd_ret_H = close[t + H] / close[t] - 1
```

其中：
- `H = 1`：1天短线环境。
- `H = 3`：3天短线环境。
- `H = 5`：1周短线环境。
- `H = 20`：波段环境。

### 2.2 波动率自适应三分类

为了避免固定涨跌幅阈值在不同波动环境下失真，采用 ATR 百分比做动态阈值：

```text
atr20_pct = ATR(20) / close
threshold_H = max(min_threshold_H, k_H * atr20_pct * sqrt(H))
```

默认参数：

| 周期 | `min_threshold_H` | `k_H` | 含义 |
| --- | ---: | ---: | --- |
| 5日 | 1.5% | 0.70 | 短线需要超过噪声才判定方向 |
| 20日 | 4.0% | 1.00 | 波段需要更明确的趋势确认 |

三分类标签：

```text
if fwd_ret_H >= threshold_H:
    label = bull
elif fwd_ret_H <= -threshold_H:
    label = bear
else:
    label = neutral
```

### 2.3 辅助回归标签

第一版先不训练回归模型，但数据集保留以下字段，方便后续扩展：

- `fwd_ret_5d`
- `fwd_ret_20d`
- `fwd_max_drawdown_10d`
- `fwd_max_drawdown_20d`
- `fwd_max_return_20d`

## 3. 数据来源

### 3.1 指数行情

使用本地指数日线缓存：

```text
data.cache_dir/index/{symbol}.csv
```

第一阶段默认：

```text
000001.SH  上证指数
```

后续可扩展：

- `000300.SH` 或 `399300.SZ`：沪深300
- `399006.SZ`：创业板指
- `000852.SH`：中证1000
- `932000.CSI`：中证2000

### 3.2 全市场广度

基于本地股票日线缓存计算：

- 上涨家数
- 下跌家数
- 平盘家数
- 上涨占比
- A/D 值
- 标准化 A/D
- 累计标准化 A/D
- 新高数量
- 新低数量
- NH-NL
- 站上 MA20 股票数和比例
- 站上 MA60 股票数和比例

### 3.3 分层广度

使用现有指数成分缓存：

```text
data.meta_dir/index_members/{index_code}.csv
```

第一阶段纳入：

| 分层 | 数据来源 |
| --- | --- |
| 全A | 非 ST 股票本地缓存 |
| 沪深300 | `399300.SZ` 成分 |
| 中证1000 | `000852.SH` 成分 |
| 中证2000 | `932000.CSI` 成分 |
| 创业板 | 股票基础信息中创业板市场 |

### 3.4 题材强度

后续阶段可接入：

```text
meta/stock_pools.json
```

第一版先预留字段，不作为必需输入，避免模型过早依赖人工题材维护质量。

## 4. 特征工程

所有特征必须只使用 `t` 日及以前的数据，预测在 `t` 日收盘后生成。

### 4.1 指数趋势特征

| 特征 | 参数 |
| --- | --- |
| 日收益 | `ret_1d` |
| 短期收益 | `ret_3d`, `ret_5d`, `ret_10d` |
| 中期收益 | `ret_20d`, `ret_60d` |
| 均线距离 | `close / MA5 - 1`, `MA10`, `MA20`, `MA60`, `MA120`, `MA250` |
| 均线斜率 | `MA20`、`MA60` 的 5日和10日斜率 |
| 多头结构 | `close > MA20`, `MA20 > MA60`, `MA60 > MA120` |
| 回撤 | 距 20日、60日、120日最高点回撤 |
| 突破 | 是否创 20日、60日新高 |
| 跌破 | 是否跌破 20日、60日新低 |

均线斜率计算：

```text
ma_slope_N_W = (MA_N[t] / MA_N[t - W] - 1)
```

默认：

- `N = 20, 60`
- `W = 5, 10`

### 4.2 技术指标特征

指数自身除均线外，加入 MACD 和 KDJ。它们不单独决定预测结果，而是作为趋势动能、拐点和过热/超跌状态的补充输入。

#### MACD

默认使用常见参数：

```text
fast = 12
slow = 26
signal = 9
```

计算字段：

```text
ema_fast = EMA(close, 12)
ema_slow = EMA(close, 26)
dif = ema_fast - ema_slow
dea = EMA(dif, 9)
macd_hist = 2 * (dif - dea)
```

入模特征：

| 特征 | 参数 |
| --- | --- |
| DIF 标准化 | `dif / close` |
| DEA 标准化 | `dea / close` |
| MACD 柱标准化 | `macd_hist / close` |
| MACD 柱斜率 | `macd_hist[t] - macd_hist[t - 1]`，以及 3日、5日变化 |
| DIF 与 DEA 距离 | `(dif - dea) / close` |
| 金叉状态 | `dif > dea` |
| 零轴状态 | `dif > 0`, `dea > 0` |
| 动能连续改善 | `macd_hist` 连续 3 日抬升 |
| 动能连续转弱 | `macd_hist` 连续 3 日下降 |

重点不是简单看金叉死叉，而是看 MACD 柱体斜率和 DIF/DEA 是否在零轴上方扩张。

#### KDJ

默认参数：

```text
n = 9
k_smooth = 3
d_smooth = 3
```

计算字段：

```text
RSV = (close - LLV(low, 9)) / (HHV(high, 9) - LLV(low, 9)) * 100
K = SMA(RSV, 3)
D = SMA(K, 3)
J = 3 * K - 2 * D
```

入模特征：

| 特征 | 参数 |
| --- | --- |
| K 值 | `K / 100` |
| D 值 | `D / 100` |
| J 值 | `J / 100` |
| KDJ 动量 | `(K - D) / 100` |
| K 斜率 | `K[t] - K[t - 1]`，以及 3日变化 |
| J 斜率 | `J[t] - J[t - 1]`，以及 3日变化 |
| 金叉状态 | `K > D` |
| J 值负值机会 | `J < 0`，重点观察短线超跌后的修复机会 |
| J 值极端负值 | `J < -10`，作为更强的短线超跌信号 |
| J 值高位风险 | `J > 90`，重点观察短线过热风险 |
| J 值极端高位 | `J > 100`，作为更强的短线过热信号 |
| 超买状态 | `K > 80` 或 `J > 90` |
| 超卖状态 | `K < 20` 或 `J < 0` |
| 高位钝化 | `K > 80` 且连续 3 日 `K > D` |
| 低位修复 | `K < 30` 后向上穿越 `D` |

KDJ 容易短线噪声较大，第一版主要用于 5日预测，20日预测中降低权重。KDJ 的重点不是普通金叉死叉，而是：

- `J < 0` 后，观察指数是否出现短线修复机会。
- `J > 90` 后，观察指数是否进入短线过热风险区。
- 若 `J > 90` 同时出现 A/D 斜率转弱或 NH-NL 斜率转弱，风险权重提高。
- 若 `J < 0` 同时出现 A/D 斜率抬升或 NH-NL 斜率抬升，修复机会权重提高。

### 4.3 波动特征

| 特征 | 参数 |
| --- | --- |
| ATR 百分比 | `ATR14 / close`, `ATR20 / close` |
| 实现波动率 | `ret_1d` 的 10日、20日标准差 |
| 日内振幅 | `(high - low) / close` |
| 上影线比例 | `(high - max(open, close)) / (high - low)` |
| 下影线比例 | `(min(open, close) - low) / (high - low)` |

### 4.4 量能特征

指数成交量本身可靠性不如成交金额，原因是指数 `volume` 汇总口径和指数成分变化会影响可比性；第一版量能特征以 `amount` 成交金额为主，`volume` 成交量只作为辅助观察。

| 特征 | 参数 |
| --- | --- |
| 成交金额相对20日 | `amount / amount_ma20`，核心量能特征 |
| 5日成交金额相对20日 | `amount_ma5 / amount_ma20` |
| 成交金额斜率 | `amount_ma5 / amount_ma20 - 1`，观察资金活跃度抬升/下降 |
| 放量上涨 | `ret_1d > 0` 且 `amount / amount_ma20 > 1.2` |
| 放量下跌 | `ret_1d < 0` 且 `amount / amount_ma20 > 1.2` |
| 高位放量滞涨 | `amount / amount_ma20 > 1.5` 且实体涨幅小且上影线偏长 |
| 成交量辅助比值 | `volume / volume_ma20`，只作为辅助字段，不作为第一权重特征 |

高位放量滞涨建议口径：

```text
amount_ratio_20 >= 1.5
abs(ret_1d) <= 0.5 * atr20_pct
upper_shadow_ratio >= 0.35
close >= MA20
```

成交金额数据来源：

- 普通指数下载使用 `Tushare index_daily`；`AVG_PRICE.LOCAL` 同花顺平均股价指数代理由本地股票 K 线缓存等权平均生成。
- 下载字段已包含 `amount`。
- 本地指数缓存字段包含 `volume` 和 `amount`，例如 `cache/index/000001.SH.csv`。

### 4.5 全市场广度特征

A/D 原始值可以保留用于展示和诊断，但入模重点使用“标准化 A/D 的斜率、变化率和背离”。原因是 A 股股票数量持续变化，原始上涨家数减下跌家数不适合长期直接比较。

| 特征 | 参数 |
| --- | --- |
| 上涨占比 | `up_count / (up_count + down_count + flat_count)` |
| 标准化 A/D | `(up_count - down_count) / (up_count + down_count)`，作为基础序列 |
| 标准化 A/D 均值 | 3日、5日、10日均值 |
| 累计标准化 A/D | 每日标准化 A/D 累加，主要用于计算斜率 |
| A/D 斜率 | 累计标准化 A/D 的 3日、5日、10日、20日斜率，核心入模特征 |
| A/D 斜率变化 | `ad_slope_5[t] - ad_slope_5[t - 1]`，观察广度是否加速改善/恶化 |
| A/D 短长斜率差 | `ad_slope_5 - ad_slope_20` |
| 指数与 A/D 背离 | 指数 20日上涨但 `ad_slope_20 < 0`，或指数 20日下跌但 `ad_slope_20 > 0` |
| 站上 MA20 比例 | `above_ma20_count / valid_stock_count` |
| 站上 MA60 比例 | `above_ma60_count / valid_stock_count` |

斜率计算：

```text
ad_slope_W = ad_cum[t] - ad_cum[t - W]
```

默认：

- `W = 3, 5, 10, 20`

### 4.6 NH-NL 特征

NH-NL 原始值保留，但模型重点使用 NH-NL 的标准化、斜率、5日合计变化和背离。这样更符合“领先指标”的定位：看领涨/领跌力量是在增强还是衰减。

近一年按 252 个交易日计算：

```text
new_high_count = close[t] >= rolling_high_252[t]
new_low_count = close[t] <= rolling_low_252[t]
nh_nl = new_high_count - new_low_count
```

衍生特征：

| 特征 | 参数 |
| --- | --- |
| NH-NL 原始值 | `nh_nl` |
| NH-NL 5日合计 | `nh_nl_sum_5` |
| NH-NL 10日合计 | `nh_nl_sum_10` |
| 新高占比 | `new_high_count / valid_stock_count` |
| 新低占比 | `new_low_count / valid_stock_count` |
| NH-NL 标准化 | `nh_nl / valid_stock_count` |
| NH-NL 斜率 | `nh_nl_norm[t] - nh_nl_norm[t - W]`，`W = 3, 5, 10, 20` |
| NH-NL 5日合计斜率 | `nh_nl_sum_5[t] - nh_nl_sum_5[t - 5]` |
| NH-NL 短长斜率差 | `nhnl_slope_5 - nhnl_slope_20` |
| NH-NL Z 分数 | 60日滚动 z-score |
| 指数与 NH-NL 背离 | 指数创新高但 NH-NL 斜率下降，或指数创新低但 NH-NL 斜率抬升 |

Z 分数：

```text
nhnl_z60 = (nh_nl - mean(nh_nl, 60)) / std(nh_nl, 60)
```

### 4.7 分层广度特征

对每个分层分别计算：

- `group_ad_norm`
- `group_ad_cum`
- `group_ad_slope_5`
- `group_ad_slope_10`
- `group_ad_slope_20`
- `group_up_ratio`
- `group_above_ma20_ratio`
- `group_above_ma60_ratio`

重点构造风格分化特征：

```text
hs300_minus_allA_ad_slope_5
csi1000_minus_hs300_ad_slope_5
csi2000_minus_hs300_ad_slope_5
chinext_minus_hs300_ad_slope_5
```

解释：

- 沪深300强于全A：权重行情。
- 中证1000/2000强于沪深300：小盘题材活跃。
- 创业板强于沪深300：成长风格占优。

### 4.7 相对强弱特征

比较不同指数的阶段收益：

```text
rs_index_vs_base_20 = ret_20d(index) - ret_20d(base_index)
```

第一版：

- 基准指数：上证指数。
- 对比指数：沪深300、创业板指、中证1000、中证2000。

## 5. 数据集生成

新增模块建议：

```text
analysis/index_forecast_features.py
```

输出文件分三层，方便后续接入多个预测算法：

```text
output/statistics/index_forecast/indicators_{symbol}.csv
output/statistics/index_forecast/features_{symbol}.csv
output/statistics/index_forecast/predictions_{symbol}_h{H}.csv
```

`indicators_{symbol}.csv` 是核心指标宽表，只包含 `t` 日收盘后已知的指标，不包含未来收益和标签。所有预测算法都应优先读取这张表作为输入。

指标表字段结构：

```text
trade_date
symbol
close
indicator_*
```

`features_{symbol}.csv` 在指标表基础上追加未来收益和训练标签，用于模型训练、历史验证和回测评估：

```text
fwd_ret_5d
fwd_ret_20d
label_5d
label_20d
```

`predictions_{symbol}_h{H}.csv` 保存具体模型输出。后续多个算法共存时，使用 `model` 字段区分，例如 `rule_v1`、`hgb_v1`、`logistic_v1`。

默认参数：

| 参数 | 默认值 |
| --- | --- |
| `symbol` | `000001.SH` |
| `start` | `20110101` |
| `end` | 当前最新交易日 |
| `max_feature_window` | 252 |
| `min_train_rows` | 600 |
| `drop_warmup_rows` | 260 |

由于 MA250、NH-NL 需要长窗口，前 `260` 个交易日不进入训练。

## 6. 模型方案

### 6.1 第一阶段：规则基线

先做一个无需新增依赖的规则模型，作为机器学习模型的对照组。

规则分数范围：

```text
market_score = 0 ~ 100
```

建议权重：

| 模块 | 分值 |
| --- | ---: |
| 指数趋势 | 20 |
| MACD/KDJ 动能 | 10 |
| 量能确认 | 15 |
| 全市场广度斜率 | 20 |
| 分层广度 | 15 |
| NH-NL 斜率 | 15 |
| 波动风险 | 5 |

状态划分：

| 分数 | 状态 |
| ---: | --- |
| `>= 75` | 偏强 |
| `55 ~ 75` | 震荡偏强 |
| `45 ~ 55` | 中性震荡 |
| `25 ~ 45` | 震荡偏弱 |
| `< 25` | 偏弱 |

### 6.2 第二阶段：机器学习分类模型

建议新增轻量依赖：

```text
scikit-learn
```

第一版模型：

```text
HistGradientBoostingClassifier
```

默认技术参数：

| 参数 | 默认值 |
| --- | --- |
| `loss` | `log_loss` |
| `max_iter` | `300` |
| `learning_rate` | `0.03` |
| `max_leaf_nodes` | `15` |
| `l2_regularization` | `0.1` |
| `early_stopping` | `True` |
| `validation_fraction` | `0.15` |
| `random_state` | `42` |

对照模型：

```text
LogisticRegression
```

默认技术参数：

| 参数 | 默认值 |
| --- | --- |
| `C` | `0.5` |
| `class_weight` | `balanced` |
| `max_iter` | `2000` |
| `multi_class` | `auto` |

### 6.3 概率到信号

模型输出：

```text
p_bull
p_neutral
p_bear
forecast_score = p_bull - p_bear
```

信号转换：

```text
if p_bull >= 0.45 and p_bull - p_bear >= 0.15:
    signal = bull
elif p_bear >= 0.45 and p_bear - p_bull >= 0.15:
    signal = bear
else:
    signal = neutral
```

## 7. 训练和验证

### 7.1 时间切分

不能随机打乱，必须按时间顺序验证。

第一版固定切分：

| 数据段 | 时间 |
| --- | --- |
| 训练集 | `2011-01-01 ~ 2023-12-31` |
| 验证集 | `2024-01-01 ~ 2024-12-31` |
| 测试集 | `2025-01-01 ~ 最新` |

后续增加滚动验证：

| 参数 | 默认值 |
| --- | --- |
| 训练窗口 | 756 个交易日 |
| 测试窗口 | 126 个交易日 |
| 滚动步长 | 63 个交易日 |

### 7.2 评估指标

分类指标：

- Accuracy
- Balanced Accuracy
- Macro F1
- Log Loss
- Brier Score
- Confusion Matrix

交易环境指标：

- 看多信号后的未来 5日/20日平均收益
- 看空信号后的未来 5日/20日平均收益
- 看多命中率
- 看空命中率
- 多空概率差分桶统计

类择时回测：

```text
signal = bull     -> index_exposure = 1.0
signal = neutral  -> index_exposure = 0.3
signal = bear     -> index_exposure = 0.0
```

对比基准：

- 上证指数买入持有。
- 规则基线模型。

输出指标：

- 年化收益
- 最大回撤
- 夏普比率
- 胜率
- 换手次数
- 空仓天数占比

## 8. CLI 设计

建议在 `index` 命令下新增预测相关命令，避免新开顶层命令。

### 8.1 生成训练数据

```bash
python main.py index forecast-data --symbol 000001.SH --start 20110101 --end 20260623 --horizon 5
```

参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--symbol` | `000001.SH` | 指数代码 |
| `--start` | 配置开始日期 | 起始日期 |
| `--end` | 最新交易日 | 结束日期 |
| `--horizon` | `5` | 预测周期 |
| `--force` | `False` | 是否强制重建数据集 |

### 8.2 训练模型

```bash
python main.py index forecast-train --symbol 000001.SH --horizon 5 --model hgb
```

参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--model` | `hgb` | `rule`, `logistic`, `hgb` |
| `--horizon` | `5` | `5` 或 `20` |
| `--walk-forward` | `False` | 是否执行滚动验证 |
| `--save-model` | `True` | 是否保存模型 |

### 8.3 生成预测报告

```bash
python main.py index forecast-report --symbol 000001.SH --horizon 5
```

输出：

```text
output/reports/index_forecast/000001.SH_h5.html
```

### 8.4 一键执行

```bash
python main.py index forecast --symbol 000001.SH --horizon 5
```

执行顺序：

1. 检查数据缓存。
2. 生成或更新指标表。
3. 基于指标表追加训练标签。
4. 加载已有模型；若无模型则训练。
5. 生成最新预测。
6. 输出 HTML 报告。

## 9. 文件和模块规划

建议新增：

```text
analysis/index_forecast_features.py
analysis/index_forecast_model.py
visual/index_forecast_report.py
```

建议修改：

```text
cli/index_cli.py
visual/dashboard.py 或相关 dashboard 入口
README.md
DAILY_COMMANDS.md
TECHNICAL.md
AGENTS.md
```

输出目录：

```text
output/statistics/index_forecast/
output/statistics/index_forecast/models/
output/reports/index_forecast/
```

模型文件：

```text
output/statistics/index_forecast/models/000001.SH_h5_hgb.pkl
output/statistics/index_forecast/models/000001.SH_h20_hgb.pkl
```

预测文件：

```text
output/statistics/index_forecast/predictions_000001.SH_h5.csv
output/statistics/index_forecast/predictions_000001.SH_h20.csv
```

## 10. HTML 报告设计

报告标题：

```text
上证指数预测模型
```

核心区域：

1. 最新预测卡片
   - 日期
   - 当前指数收盘价
   - 看多概率
   - 震荡概率
   - 看空概率
   - 预测状态
   - 风险分数

2. 指数 K 线 + 预测背景
   - K 线图。
   - MA20、MA60、MA120。
   - 背景色标记历史预测状态。

3. 广度指标对照
   - 标准化 A/D。
   - 分层标准化 A/D。
   - NH-NL。
   - A/D 斜率。
   - NH-NL 斜率。
   - 上涨/下跌/平盘家数。

4. 模型验证
   - 测试集分类指标。
   - 看多/看空信号表现。
   - 与买入持有对比。

5. 最近 60 个交易日预测明细
   - 日期
   - 收盘价
   - `p_bull`
   - `p_neutral`
   - `p_bear`
   - 预测状态
   - 未来实际收益，历史区间可显示；最新日期为空。

## 11. 风险控制和防未来函数

必须遵守：

- 特征只使用 `t` 日及以前数据。
- 标签才允许使用 `t + H`。
- 训练集、验证集、测试集按时间切分，不能随机打乱。
- 模型调参只能基于训练集和验证集，不能看测试集后反复调参。
- 每日预测默认在收盘后生成，不用于当日收盘前决策。
- 分层成分数据需要注意历史成分偏差；第一版使用现有成分缓存时，报告中必须标注该限制。
- 全A股票池当前以本地缓存和当前非 ST 列表为主，存在退市股和历史 ST 幸存者偏差。

## 12. 第一阶段最小可交付版本

第一阶段只做这几个功能：

1. 生成上证指数预测指标表。
2. 基于指标表生成 5日和20日三分类训练标签。
3. 实现规则基线模型。
4. 实现 `HistGradientBoostingClassifier` 模型。
5. 输出预测 CSV。
6. 输出上证指数预测 HTML 报告。
7. 在 dashboard 增加预测报告入口。

暂不做：

- 不接入实盘交易。
- 不自动影响策略仓位。
- 不做深度学习。
- 不做分钟级预测。
- 不预测具体点位。

## 13. 推荐实施顺序

### 阶段 1：数据集

- 新增 `analysis/index_forecast_features.py`。
- 复用现有指数行情、市场广度、分层 A/D、NH-NL 计算结果。
- 生成 `indicators_000001.SH.csv` 指标表。
- 基于指标表生成 `features_000001.SH.csv` 训练/验证表。
- 增加单元测试，验证没有未来函数。

### 阶段 2：规则基线

- 新增规则评分函数。
- 对历史每一天生成 `rule_score` 和 `rule_signal`。
- 统计规则信号未来收益表现。

### 阶段 3：机器学习模型

- 新增 `analysis/index_forecast_model.py`。
- 训练 `logistic` 和 `hgb` 两个模型。
- 输出测试集指标和预测概率。

### 阶段 4：报告

- 新增 `visual/index_forecast_report.py`。
- 报告中展示 K 线、A/D、NH-NL、预测概率、验证结果。
- dashboard 增加入口。

### 阶段 5：收敛优化

- 做滚动验证。
- 做概率校准。
- 做特征重要性。
- 决定是否把预测结果作为策略过滤器，但这一步需要单独讨论。

## 14. 默认技术参数汇总

| 参数 | 默认值 |
| --- | --- |
| 预测指数 | `000001.SH` |
| 预测周期 | `5`, `20` |
| 最大特征窗口 | `252` |
| 训练最少样本 | `600` |
| warmup 丢弃 | `260` |
| ATR 标签窗口 | `20` |
| NH-NL 窗口 | `252` |
| NH-NL 斜率窗口 | `3`, `5`, `10`, `20` |
| A/D 斜率窗口 | `3`, `5`, `10`, `20` |
| 均线窗口 | `5`, `10`, `20`, `60`, `120`, `250` |
| MACD 参数 | `12`, `26`, `9` |
| MACD 核心特征 | DIF/DEA/柱体标准化，柱体 1日/3日/5日变化 |
| KDJ 参数 | `9`, `3`, `3` |
| KDJ 核心特征 | J<0 修复机会，J>90 过热风险，K-D 差值，K/J 斜率 |
| 量能优先字段 | 指数 `amount` 成交金额 |
| 量能辅助字段 | 指数 `volume` 成交量 |
| 规则看多阈值 | `>= 75` |
| 规则看空阈值 | `< 25` |
| ML 看多概率阈值 | `p_bull >= 0.45` 且 `p_bull - p_bear >= 0.15` |
| ML 看空概率阈值 | `p_bear >= 0.45` 且 `p_bear - p_bull >= 0.15` |
| HGB 迭代次数 | `300` |
| HGB 学习率 | `0.03` |
| HGB 叶子数 | `15` |
| HGB L2 | `0.1` |
| 随机种子 | `42` |

## 15. 后续讨论点

实施前建议确认三件事：

1. 第一版是否允许新增 `scikit-learn` 依赖。
2. 预测标签更偏向固定收益阈值，还是 ATR 自适应阈值。
3. 预测结果是否只展示在报告里，还是未来要接入策略仓位过滤。
