# 市场环境预测报告说明

> 当前 HTML 页面已经以“大盘指数与市场结构分析”为主，旧预测模型和评估位于折叠的实验诊断区域。市场结构栏目的最新口径见 [大盘指数与市场结构分析说明](index_market_structure.md)。本文继续说明旧市场环境预测与诊断字段。

`index forecast` 不再把市值加权指数未来涨跌作为唯一预测目标。当前目标是判断未来一段时间内，多数 A 股是否具有正收益机会，以及市场尾部风险是否可控，从而辅助提高或降低风险暴露。

```text
python main.py index forecast --symbol 000001.SH --horizon 5
```

支持的预测周期为 `1 / 5 / 10 / 20` 个交易日。报告默认输出到：

```text
output.reports_dir/index_forecast/{symbol}_h{horizon}.html
```

## 1. 环境标签

| 显示 | 字段值 | 风险暴露含义 |
| --- | --- | --- |
| 积极 | `positive` | 多数股票机会较好且尾部风险可控，可以提高风险暴露 |
| 中性 | `neutral` | 机会或风险没有形成一致结论，保持中等仓位 |
| 保守 | `conservative` | 赚钱效应弱或尾部风险过高，应降低风险暴露 |

标签不是由上证指数单独决定。每个历史交易日都会基于当日有效股票池计算未来 H 日：

| 字段 | 含义 |
| --- | --- |
| `market_cap_index_return_Hd` | 市值加权指数未来 H 日收盘到收盘收益，仅作辅助诊断 |
| `equal_weight_return_Hd` | 有效股票未来收益的等权平均值 |
| `median_stock_return_Hd` | 有效股票未来收益中位数 |
| `stock_win_rate_Hd` | 未来收益大于 0 的股票比例 |
| `future_breadth_Hd` | 未来 H 日标准化 A/D 的累计值 |
| `return_q10_Hd` | 个股未来收益 10% 分位数，衡量左尾风险 |
| `median_max_drawdown_Hd` | 个股未来 H 日路径最大回撤的中位数 |
| `volatility_Hd` | 未来等权市场日收益的年化波动率 |
| `large_decline_ratio_Hd` | 未来 H 日跌幅不高于配置阈值的股票比例 |

默认大跌阈值为 `-5%`，可通过 `config.yaml::index_forecast.large_decline_threshold` 调整。

## 2. 机会分、风险分和最终标签

所有子项先转换成 `0~100` 的历史滚动分位分。对日期 T 的样本，只允许使用截至 T 已经走完整个未来 H 日窗口的历史样本作为分位基准；最近 H 日尚未完成的标签不会进入阈值计算。

```text
opportunity_score =
    35% × median_stock_return_score
  + 25% × equal_weight_return_score
  + 20% × stock_win_rate_score
  + 20% × future_breadth_score

risk_score =
    30% × downside_quantile_score
  + 25% × max_drawdown_score
  + 20% × volatility_score
  + 15% × large_decline_ratio_score
  + 10% × negative_breadth_score

environment_score =
    70% × opportunity_score
  + 30% × (100 - risk_score)
```

指数未来收益不进入主标签得分，实际权重为 `0%`，只保留作辅助对照。

标签规则：

```text
积极：environment_score >= 65 且 risk_score < 70
保守：environment_score <= 40 或 risk_score >= 80
中性：其余情况
```

风险分具有否决权：即使机会分较高，只要 `risk_score >= 80`，实际环境仍为保守。

## 3. 指数与个股分化

```text
index_breadth_gap_Hd =
    market_cap_index_return_Hd - equal_weight_return_Hd
```

| 分化字段 | 含义 |
| --- | --- |
| `index_only_rally` | 指数上涨，但等权收益不涨且上涨股票不足一半，属于指数虚强 |
| `breadth_stronger_than_index` | 指数下跌，但等权收益上涨且多数股票上涨 |
| `broad_market_rally` | 指数、等权市场和上涨比例同步偏强 |
| `broad_market_decline` | 指数、等权市场和上涨比例同步偏弱 |
| `mixed_market` | 其余分化状态 |

市场环境优先参考个股收益中位数、等权收益和上涨股票比例，而不是单独参考指数涨跌。

## 4. 预测特征

`indicators_{symbol}.csv` 只保存当日收盘后已经可知的预测特征，包括：

- 指数趋势、均线、成交量、成交额、MACD、KDJ；
- `daily_ad`、`normalized_ad` 和 A/D 线 5/10/20 日斜率；
- `daily_nhnl`、`normalized_nhnl` 和 NH-NL 线 5/10/20 日斜率；
- 站上 20/50/200 日均线的股票比例、上涨股票比例；
- 当前横截面波动率和单日大跌股票比例；
- 指数与等权市场强弱差；
- 沪深300与中证1000的大小盘相对强弱。该项使用各自历史指数缓存，不用最新成分股倒推历史。

规则模型输出：

| 字段 | 含义 |
| --- | --- |
| `environment_signal` | `positive / neutral / conservative` 预测环境 |
| `market_score` | 预测环境综合分 |
| `predicted_opportunity_score` | 由当日已知特征形成的预测机会分 |
| `predicted_risk_score` | 由当日已知特征形成的预测风险分 |

`legacy_index_rule_score`、`p_bull`、`p_neutral`、`p_bear` 和旧指数收益标签仅为兼容历史诊断保留，不再是主环境目标。

## 5. 模型评估明细

报告按预测环境展示：

- 个股未来收益中位数；
- 等权市场未来收益；
- 上涨股票比例；
- 尾部 `Q10` 收益；
- 个股路径最大回撤中位数；
- 环境标签命中率。

评估的理想排序是：积极环境的个股中位数、等权收益和上涨比例高于中性，保守环境的尾部收益和回撤最差。指数未来收益分桶仍显示为辅助对照，但不能单独用于判断模型有效性。

## 6. 策略实际收益与环境过滤

如果 `output.trades_dir` 中已有 `{symbol}_{strategy}_equity.csv`，报告会按策略汇总日收益，并展示：

- 各预测环境下策略未来 H 日实际收益；
- 环境过滤前后累计收益、日胜率、最大回撤和盈亏比；
- 环境从积极转为保守后 20 个交易日，过滤前回撤、过滤后回撤及两者变化。

过滤仓位为：

```text
positive     -> 100%
neutral      -> 50%
conservative -> 0%
```

环境信号滞后一个交易日应用，避免用当天收盘后才生成的信号参与当天收益。

## 7. 输出文件

| 文件 | 内容 |
| --- | --- |
| `indicators_{symbol}.csv` | 只含当日及以前可知的预测特征 |
| `features_{symbol}.csv` | 指标加未来 1/5/10/20 日横截面结果、得分和环境标签 |
| `predictions_{symbol}_h{H}.csv` | 指定周期预测、实际环境结果和兼容字段 |
| `{symbol}_h{H}.html` | 市场环境预测与验证报告 |

执行 `index forecast-diagnose` 还会输出 P0/P1 研究文件：

| 文件 | 内容 |
| --- | --- |
| `diagnostics_{symbol}_h{H}_feature_whitelist.csv` | 排除未来目标及派生分数后的固定可训练特征白名单 |
| `diagnostics_{symbol}_h{H}_breadth_events.csv` | A/D、NH-NL 历史水平与斜率方向的二维事件研究 |
| `diagnostics_{symbol}_h{H}_walk_forward.csv` | 机会/风险双逻辑回归的逐折样本外指标 |
| `diagnostics_{symbol}_h{H}_walk_forward_predictions.csv` | 逐日样本外机会概率、风险概率和环境映射 |
| `diagnostics_{symbol}_h{H}_walk_forward_baselines.csv` | 多数先验、趋势、均值回归、仅 A/D、仅 NH-NL 的逐折对照 |
| `diagnostics_{symbol}_h{H}_walk_forward_coefficients.csv` | 每折实际选择的特征和标准化系数 |
| `diagnostics_{symbol}_h{H}_coefficient_stability.csv` | 系数入选率、正负方向和跨折稳定性 |
| `diagnostics_{symbol}_h{H}_label_stability.csv` | 透明 A/B/C 标签和复合目标的逐折发生率 |
| `diagnostics_{symbol}_h{H}_feature_deciles.csv` | 每项可用特征的历史可观测十分位事件研究 |
| `diagnostics_{symbol}_h{H}_ablation.csv` | 趋势、广度、风险/结构特征组消融 |
| `diagnostics_{symbol}_h{H}_research_summary.csv` | AUC、IC、概率质量、分组收益和区块 Bootstrap 汇总 |
| `diagnostics_{symbol}_h{H}_regime_stability.csv` | 年度和波动状态稳定性 |
| `diagnostics_{symbol}_h{H}_transitions.csv` | 样本外环境切换后的 1/5/10/20 日结果 |
| `diagnostics_{symbol}_h{H}_strategy_policies.csv` | 策略 A-E 过滤及相同平均暴露随机对照 |
| `diagnostics_{symbol}_h{H}_point_in_time_quality.csv` | 各年份有效股票数和历史股票池限制 |
| `diagnostics_{symbol}_h{H}_gate_audit.csv` | P2/P3 数值门槛及最终允许/停止决策 |

诊断会验证已有预测文件的日期覆盖。若文件不覆盖命令请求的起止日期，会自动重建，避免把短区间旧文件误当作全历史样本。指标文件同时记录日频重叠样本数和 `floor(日频样本/H)` 约当不重叠样本数；后者只用于直观提示，不代表独立样本统计。

P1 使用两个独立逻辑回归研究机会和风险，严格按“训练→purge→验证→embargo→测试”生成时间外概率。它是诊断模型，不会自动替换 `index forecast` 的正式规则。只有 `gate_audit.csv` 全部通过时，才允许继续非线性模型或正式仓位接入。

最新 H 个交易日的未来结果和实际标签为空是正常现象，因为相应观察窗口尚未完成。

## 8. 数据限制

- 横截面来自 `data.cache_dir/*.csv` 的本地股票缓存，缓存覆盖不完整会改变有效股票池和标签。
- 当前缓存通常基于当前上市股票列表，历史退市股和历史 ST 状态可能不完整，存在幸存者偏差。
- 大小盘相对强弱依赖本地沪深300和中证1000指数缓存；缺失时该特征为空，不使用最新指数成分倒推历史。
- 标签用于研究风险暴露，不构成实盘交易建议；真实应用仍需考虑基金跟踪误差、成交成本和组合约束。
