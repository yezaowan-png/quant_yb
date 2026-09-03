# 市场极端风险闸门研究说明

## 结论与边界

`market_risk_gate` 是与现有 `index forecast`、大盘环境标签和正式策略完全隔离的研究模块。它首先描述当前市场压力，再研究未来 1/5/10/20 个交易日的极端风险是否可预测。当前只生成研究结果和模拟政策，不修改正式信号、订单或仓位。

自动结论只允许为：

- `continue_risk_gate_research`
- `stop_future_risk_prediction_use_state_monitor_only`
- `eligible_for_strategy_validation`

即使达到最后一项，也只表示可以申请下一轮策略验证，不会自动接入正式仓位。

## 当前市场状态规则

状态只使用 T 日收盘时已知的数据，并以最长 756 个交易日、至少 60 个有效样本的滚动历史分位数判断极端程度：

- `normal`：未出现系统性风险扩散。
- `stressed`：至少两项指标进入极端区，或广度水平偏弱且 A/D、NH-NL 同时恶化。
- `panic`：至少五项指标进入极端区，且 A/D、NH-NL 同时恶化。
- `recovering`：广度水平仍弱，但 A/D 与 NH-NL 斜率同时改善。

极端项包括标准化 A/D、标准化 NH-NL、MA20 上方比例、大跌股票比例、横截面离散度、5 日实现波动率、新低比例和近似跌停比例。状态层不读取任何 `future_*` 字段。

模拟政策使用 `green/yellow/orange/red` 四级：

| 等级 | 允许新开仓 | 仓位上限 | 含义 |
|---|---:|---:|---|
| green | 是 | 1.0 | 不主动增加信号，不代表看多 |
| yellow | 是 | 0.6 | 仅研究性限制 |
| orange | 否 | 0.3 | 只允许管理或降低已有风险 |
| red | 否 | 0.0 | 禁止新增风险仓位，不代表做空 |

风险升级可立即发生；降级必须连续 3 日改善，并且逐级解除，`red` 不会直接返回 `green`。所有仓位动作在策略对照中滞后一个交易日执行。

## 未来状态与 R1-R5 标签

四个未来状态互斥，阈值只在每个训练窗口内计算并冻结：

- `persistent_tail_risk`：严重尾部损失，窗口结束仍未明显修复。
- `shock_then_recovery`：出现严重尾部损失，随后明显恢复。
- `broad_weakness`：没有尾部崩溃，但多数股票持续弱势。
- `normal_or_positive`：不符合以上三类。

R1-R5 是五种彼此独立验证的二分类实验定义，而不是一个加权复合标签：

- R1：未来个股收益 Q10 位于训练期最差 20%。
- R2：同时满足 R1、未来个股收益中位数低于 0 或训练期低分位、窗口恢复比例低于 50%。
- R3：未来上涨股票比例低于 40%、大跌股票比例处于训练期最高 20%、负广度日占多数、未来收益中位数低于 0，四项中至少满足两项。
- R4：未来个股最大回撤中位数位于训练期最差 20%。
- R5：未来大跌股票比例位于训练期最高 20%。

未来结果包含 Q10、收益中位数、上涨比例、大跌比例、个股最大回撤中位数、窗口结束剩余回撤、恢复比例和负广度日数。它们只能用于标签和时间外评估，不能进入预测特征。

## 最小特征白名单

模型最多使用以下 11 个 T 日及以前特征：

1. `current_large_decline_ratio`
2. `cross_section_dispersion`
3. `realized_volatility_5d`
4. `normalized_ad`
5. `ad_slope_5`
6. `normalized_nhnl`
7. `nhnl_slope_5`
8. `index_return_5d`
9. `pct_above_ma20`
10. `equal_weight_minus_cap_weight_return_5d`
11. `ad_level_x_slope_5`，唯一允许的预先声明交互项

禁止 KDJ、重复 MACD 字段、原始累计 A/D 和 NH-NL、重复均线/成交量/风格特征、第二个交互项、所有未来结果与标签。第一阶段模型仅允许单变量冻结基线和标准化 L2 逻辑回归，不使用树模型、神经网络、SMOTE、自动特征生成或大规模参数搜索。

## 严格时间外验证

每折固定为：

```text
扩展训练集 -> purge=H -> 验证集63日 -> embargo=H -> 测试集63日
```

标签阈值、缺失值填充、1%/99% Winsorize、标准化、L2、类别权重、校准和政策阈值全部在测试集之前确定。自然类别权重模型可输出 `risk_probability`；`balanced` 模型或校准样本不足时只输出 `risk_score`，避免把排序分误称为概率。

冻结基线包括当前大跌比例、标准化 A/D、标准化 NH-NL、实现波动率、简单趋势、简单均值回归和训练期风险发生率。测试结果不能用于逐折挑选基线。

## E1-E10 实验矩阵

| 实验 | 唯一主要变化 |
|---|---|
| E1 | R1，5 日，11 特征，balanced |
| E2 | R2，其他同 E1 |
| E3 | R3，其他同 E1 |
| E4 | R4，其他同 E1 |
| E5 | R5，其他同 E1 |
| E6 | R2，删除交互项，改为 10 特征 |
| E7 | E6 的 `class_weight` 改为 `none` |
| E8 | E7 增加严格嵌套 Platt 校准 |
| E9 | E7 的周期从 5 日改为 10 日 |
| E10 | E9 的周期从 10 日改为 20 日 |

另保留 `H1_R1`，单独诊断 1 日冲击目标。每个实验有独立 CSV 目录和独立 HTML，不会覆盖其他实验。

## 评估与自动门槛

每个标签报告 ROC-AUC、PR-AUC、风险基础率、Brier、Brier Skill、ECE、召回率、精确率、误报率、漏报率、年均误报天数、平均提前预警日数、高低风险组尾部结果、逐折基线胜率、年度/波动环境/有效股票数量稳定性。

继续研究需同时满足 AUC ≥ 0.57、PR-AUC 高于基础率、高风险组尾部方向正确、至少 55% 测试折优于冻结的大跌比例基线。申请策略验证还要求 AUC ≥ 0.60、至少 70% 测试折胜出、Brier Skill > 0、ECE ≤ 0.10；年度一致性、至少三类策略方向一致和相对同暴露随机降仓的增量价值仍需在正式申请时审计。

只有当 R1-R5 全部同时出现 AUC < 0.57、尾部排序失败、逐折基线胜率 < 55%，才自动停止未来风险预测并降级为当前压力监测器。

## 策略 A-E 对照

若 `output.trades_dir` 存在策略权益数据，会运行：A 原策略、B 指数趋势过滤、C 简单广度过滤、D 极端风险闸门、E 与 D 平均暴露匹配的固定随机降仓。输出总收益、最大回撤、Calmar、最差 5/20 日收益、尾部损失、平均暴露、阻止天数、被阻止日实际收益和机会成本。

当前只有两类策略权益时，该部分只能诊断，不能支持正式接入。权益日收益无法可靠还原“被阻止交易数量”，所以现阶段输出 `blocked_days`，不伪造交易计数。

## CLI 与输出

```bash
python main.py market risk-state --symbol 000001.SH --date 20260710
python main.py market risk-labels --symbol 000001.SH --horizon 5 --label R2 --start 20110101 --end 20260710
python main.py market risk-diagnose --symbol 000001.SH --horizon 5 --label R2 --feature-set minimal_v1 --class-weight none --calibration none
python main.py market risk-matrix --symbol 000001.SH
python main.py market risk-report --symbol 000001.SH --horizon 5 --experiment E2
```

研究数据保存到 `output.statistics_dir/market_risk_gate/{symbol}/`，实验逐折文件在其 `experiments/{experiment}/` 下；汇总和独立实验报告保存到 `output.reports_dir/market_risk_gate/`。

## 数据限制

所有输出必须保留：

```text
incomplete_point_in_time_universe
missing_delisted_stocks
missing_historical_st_status
```

当前个股矩阵来自现有本地股票缓存，缺少完整历史退市股与历史 ST 状态，存在幸存者偏差。系统按年份、有效股票数量和 2011-2015/2016-2020/2021-当前分段报告稳定性，并优先使用比例指标，但结果仍不能表述为完整历史 A 股真实风险表现。
