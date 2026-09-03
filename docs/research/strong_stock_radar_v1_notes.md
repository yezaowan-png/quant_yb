# 强势股雷达 v1 说明

> 当前版本：v1  
> 模块定位：研究、观察、复盘、后验审计  
> 命令入口：`python main.py stats radar --top 300`

## 1. 当前实现范围

本版在现有项目内新增研究型“强势股雷达”，不新建交易系统，不接入正式策略、仓位、订单或 `market_risk_gate`。

已实现：

- 可交易股票池过滤。
- 行业相对强度与行业广度。
- 股票 RS percentile、RS persistence、RS momentum。
- 趋势结构、高位距离、成交量价状态、结构收缩。
- deterministic state 分类。
- 当日 snapshot 保存。
- 基于历史 snapshot 的 T+5/T+10/T+20、MFE、MAE 后验审计。
- HTML 雷达看板与 dashboard 入口。

尚未实现：

- 单只股票详情页中的 RS20 / RS60 / RS120 时间序列图。
- 更严格的历史时点行业分类、历史 ST 状态和历史成分口径。
- 全市场构建性能优化。

## 2. 使用的数据

复用现有本地缓存：

- 个股日 K：`config.data.cache_dir/*.csv`
- 基准指数：`config.data.cache_dir/index/{benchmark_symbol}.csv`
- 股票名称与行业：优先 `dashboard.stock_selector.csv_path`，其次 `data.meta_dir/stock_basic.csv`、`stocks.csv`、`stock_names.csv`
- 市场环境摘要：`output.statistics_dir/index_forecast/market_structure_000001.SH.json`

未新增外部数据源。

## 3. 输出文件

默认输出：

- `output.statistics_dir/strong_stock_radar/radar_snapshot_{date}.csv`
- `output.statistics_dir/strong_stock_radar/strong_stock_radar_latest.csv`
- `output.statistics_dir/strong_stock_radar/tradable_universe_{date}.csv`
- `output.statistics_dir/strong_stock_radar/industry_strength_{date}.csv`
- `output.statistics_dir/strong_stock_radar/industry_rs_history_{date}.csv`：最近 250 个交易日的行业 RS 长表。
- `output.statistics_dir/strong_stock_radar/industry_rs_history_latest.csv`：最新行业 RS 历史长表。
- `output.statistics_dir/strong_stock_radar/radar_evaluation.csv`
- `output.reports_dir/strong_stock_radar/strong_stock_radar.html`

每日脚本已加入：

```bash
stats radar --top 300
```

## 4. 核心指标公式

可交易股票池先于所有 RS 和 state 计算。某只股票在某个交易日必须同时满足：

- 有不晚于该交易日的有效 K 线。
- 有效历史 bar 数 `>= strong_stock_radar.universe.min_listing_days`，默认 120。
- 20 日平均成交额 `avg_amount_20d >= strong_stock_radar.universe.min_avg_amount_20d`，默认 5000 万元。
- 当日成交额 `amount > 0`。
- 名称不包含 ST，前提是 `exclude_st: true`。
- 非一字涨跌停不可交易近似：`high == low` 且 `abs(daily_return) >= one_word_limit_return_abs` 时排除，默认阈值 9.5%。

当前 `exclude_suspended` 通过“有有效 K 线且成交额大于 0”近似处理，尚未接入完整停复牌表。

股票区间收益：

```text
return_Nd = close / close.shift(N) - 1
```

股票相对基准收益：

```text
excess_return_Nd = return_Nd - benchmark_return_Nd
```

股票 RS percentile：

```text
rsN_pct = 当日可交易股票池内 excess_return_Nd 的横截面 percentile rank * 100
```

RS persistence：

```text
rs60_persistence_20d = 最近20个有效交易日中 rs60_pct >= 90 的天数 / 有效交易日数
```

RS momentum：

```text
rs60_delta_5d = rs60_pct - rs60_pct.shift(5)
rs60_delta_10d = rs60_pct - rs60_pct.shift(10)
rs120_delta_10d = rs120_pct - rs120_pct.shift(10)
```

均线斜率：

```text
ma_slope = (MA / MA.shift(slope_window) - 1) / slope_window
```

高位距离：

```text
distance_to_high_Nd = close / rolling_high_Nd - 1
```

成交额倍率：

```text
amount_ratio_20d = amount / avg_amount_20d
```

收盘位置：

```text
close_position = (close - low) / (high - low)
```

当 `high == low` 时，`close_position = 0.5`。

## 5. 强势行业如何判断

行业强度只用于观察和股票 state 分类，不是单独买卖信号。

### 5.1 行业成员

行业来自股票元数据：

- 优先 `dashboard.stock_selector.csv_path` 中的行业字段。
- 其次 `data.meta_dir/stock_basic.csv`、`stocks.csv`、`stock_names.csv`。
- 缺失行业归为 `未分类`。

行业成员使用当前元数据映射。历史行业变更目前不做 point-in-time 还原。

### 5.2 行业收益

对每个行业，在每个日期按该行业内可交易股票等权计算区间收益：

```text
stock_return_Nd = close / close.shift(N) - 1
industry_return_Nd = mean(stock_return_Nd of tradable members)
```

当前窗口：

- 20 日。
- 60 日。
- 120 日。

只有当日属于可交易股票池的成员会进入 `industry_return_Nd` 均值。

### 5.3 行业相对强度 RS

行业相对强度使用行业等权收益减去基准指数同期收益：

```text
benchmark_return_Nd = benchmark_close / benchmark_close.shift(N) - 1
industry_rs_Nd = industry_return_Nd - benchmark_return_Nd
```

之后在全部行业中做横截面 percentile rank：

```text
industry_rs20_pct = rank_percentile(industry_rs_20) * 100
industry_rs60_pct = rank_percentile(industry_rs_60) * 100
industry_rs120_pct = rank_percentile(industry_rs_120) * 100
```

`industry_rs60_pct = 80` 表示该行业 60 日相对强度位于全部行业前 20% 左右。

### 5.4 行业广度

行业广度不是打分项，而是辅助判断“行业是否内部普遍走强”：

```text
pct_above_ma20 = 当日可交易成员中 close > MA20 的比例
pct_above_ma60 = 当日可交易成员中 close > MA60 的比例
pct_new_high_20d = 当日可交易成员中 close >= rolling_high_20d 的比例
pct_stock_rs60_above_80 = 当日可交易成员中 rs60_pct >= 80 的比例
```

这里 `pct_stock_rs60_above_80` 的 80 来自 `strong_stock_radar.rs.industry_stock_rs_threshold`。

### 5.5 行业 RS 动量

行业 RS 动量只看 60 日 RS 的变化：

```text
industry_rs60_delta_5d = industry_rs_60 - industry_rs_60.shift(5)
industry_rs60_delta_10d = industry_rs_60 - industry_rs_60.shift(10)
```

注意这里的 delta 是相对收益的变化值，不是 percentile 的变化。

行业原始超额收益 delta 使用小数收益率单位：`0.03` 表示 3%，`-0.05` 表示 -5%。因此行业 state 的 `strengthening_delta_5d` 和 `weakening_delta_10d` 默认分别为 `0.03`、`-0.05`；此前的 `3`、`-5` 与实际字段单位不一致。

行业 RS 历史额外输出 RS20/RS60/RS120 百分位的排名变化（单位为百分点），以及 RS60 最近 20 个有效交易日位于前 20% 的持续率。RS60=100 仅表示最近 60 日相对表现位居当日有效行业最高，不代表上涨 100%、上涨概率或交易建议。

### 5.6 行业 state

当前行业 state 的判断顺序如下：

`UNKNOWN`：

- `industry_rs60_pct` 缺失。

`WEAKENING`：

- `industry_rs60_pct >= strong_stock_radar.industry.strong_rs60_pct`，默认 80。
- 且 `industry_rs60_delta_10d <= strong_stock_radar.industry.weakening_delta_10d`，默认 -5。

`STRENGTHENING`：

- `industry_rs60_delta_5d >= strong_stock_radar.industry.strengthening_delta_5d`，默认 3。

`STRONG`：

- `industry_rs60_pct >= strong_stock_radar.industry.strong_rs60_pct`，默认 80。
- 且 `pct_above_ma20 >= strong_stock_radar.industry.strong_above_ma20_pct`，默认 0.55。

其他行业归为 `NORMAL`。

HTML 顶部“强势行业”数量统计的是：

```text
industry_state in {"STRONG", "STRENGTHENING"}
```

行业表默认按 `industry_rs60_pct` 和 `industry_rs20_pct` 从高到低排序。

## 6. 强势股票如何判断

股票判断采用：

```text
可交易股票池 -> RS 排名 -> 趋势结构 -> 位置/量价/收缩 -> state 分类
```

没有综合分，也没有 AI 打分。

### 6.1 股票 RS

只在当日可交易股票池内计算 RS：

```text
return_Nd = close / close.shift(N) - 1
excess_return_Nd = return_Nd - benchmark_return_Nd
rsN_pct = rank_percentile(excess_return_Nd among tradable universe) * 100
```

当前输出：

- `rs20_pct`
- `rs60_pct`
- `rs120_pct`

例如 `rs60_pct = 97` 表示该股票 60 日超额收益位于当日可交易股票池前 3% 左右。

### 6.2 RS persistence

用于区分“一日暴涨进入强势区”和“持续强势”：

```text
rs60_persistence_20d =
  最近20个有效交易日中 rs60_pct >= 90 的天数 / 有效交易日数
```

阈值 90 来自 `strong_stock_radar.rs.persistence_threshold`。

### 6.3 RS momentum

用于识别增强或掉队：

```text
rs60_delta_5d = rs60_pct - rs60_pct.shift(5)
rs60_delta_10d = rs60_pct - rs60_pct.shift(10)
rs120_delta_10d = rs120_pct - rs120_pct.shift(10)
```

这里 delta 是 percentile 的变化，单位是百分点。

### 6.4 trend_state

趋势结构使用 MA20、MA60、MA120 和均线斜率。

均线斜率：

```text
ma_slope = (MA / MA.shift(slope_window) - 1) / slope_window
```

`slope_window` 默认 5。

`STRONG`：

- `close > MA20 > MA60 > MA120`
- `ma20_slope > strong_slope_min`
- `ma60_slope > strong_slope_min`

`MID_STRONG`：

- `close > MA60 > MA120`
- `ma60_slope > mid_slope_min`

`BROKEN`：

- `close < MA60`
- 且 `ma60_slope` 缺失或 `ma60_slope <= mid_slope_min`

`WEAKENING`：

- `close < MA20`。
- 或者不满足前面更强状态时的兜底弱化状态。

`UNKNOWN`：

- 缺少 `close`、`MA60` 或 `MA120`。

### 6.5 高位位置

计算 20、60、120、250 日 rolling high：

```text
distance_to_high_Nd = close / high_Nd - 1
```

例如 `distance_to_high_250d = -0.05` 表示距离 250 日高点还有 5%。

### 6.6 volume_price_state

量价状态用于区分“放量有效”和“放量无结果”，不把放量直接解释为看涨。

`HEALTHY_EXPANSION`：

- `daily_return >= healthy_min_return`，默认 2.5%。
- `amount_ratio_20d >= healthy_min_amount_ratio`，默认 1.3。
- `close_position >= healthy_min_close_position`，默认 0.7。

`EFFORT_NO_RESULT`：

- `amount_ratio_20d >= effort_min_amount_ratio`，默认 2.0。
- 且 `daily_return <= effort_max_return`，默认 1%，或 `close_position <= effort_max_close_position`，默认 0.45。

`CONTRACTION`：

- 接近高位。
- `amount_ratio_20d <= contraction_max_amount_ratio`，默认 0.75。
- `abs(daily_return) <= contraction_max_abs_return`，默认 2.5%。

其他归为 `NORMAL`。

### 6.7 contraction_state

收缩状态用于识别“高位 + 波动收敛 + 缩量”。

底层指标：

```text
range_20d_pct = rolling_high_20d / rolling_low_20d - 1
range_10d_pct = rolling_high_10d / rolling_low_10d - 1
range_5d_pct = rolling_high_5d / rolling_low_5d - 1
volume_ma5_to_ma20 = volume_ma5 / volume_ma20
```

若 `distance_to_high_250d < contraction.near_high_250d`，默认 -12%，直接为 `NONE`。

`CLEAR`：

- `range_5d_pct <= range_20d_pct * clear_range5_to_20_max`，默认 0.45。
- `volume_ma5_to_ma20 <= clear_volume_ma5_to_ma20_max`，默认 0.7。

`EARLY`：

- `range_10d_pct <= range_20d_pct * early_range10_to_20_max`，默认 0.75。
- `volume_ma5_to_ma20 <= early_volume_ma5_to_ma20_max`，默认 0.85。

其他归为 `NONE`。

### 6.8 股票 state 分类优先级

股票 state 按顺序判断，先命中的状态会直接返回。这个顺序很重要。

第一优先级：`STRONG_WEAKENING`

- `rs60_pct >= weakening_rs60_pct`，默认 80。
- 且满足以下任一条件：
- `rs60_delta_5d <= weakening_delta_5d`，默认 -5。
- `rs60_delta_10d <= weakening_delta_10d`，默认 -8。
- `trend_state in {"WEAKENING", "BROKEN"}`。
- `industry_state == "WEAKENING"`。
- `volume_price_state == "EFFORT_NO_RESULT"`。

这个状态优先级最高，是为了优先标出旧强势股退潮。

第二优先级：`BREAKOUT`

- `breakout_signal == true`。
- `amount_ratio_20d >= breakout_amount_ratio_min`，默认 1.3。
- `close_position >= breakout_close_position_min`，默认 0.7。

`breakout_signal` 使用前一日已知高点：

```text
close > high_20d.shift(1) * (1 + breakout_buffer)
or
close > high_60d.shift(1) * (1 + breakout_buffer)
```

默认 `breakout_buffer = 0`。

第三优先级：`CORE_STRONG`

`CORE_STRONG`：

- `industry_rs60_pct >= core_industry_rs60_pct`，默认 80。
- `rs60_pct >= core_rs60_pct`，默认 90。
- `rs120_pct >= core_rs120_pct`，默认 85。
- `rs60_persistence_20d >= core_persistence_min`，默认 0.55。
- `trend_state == STRONG`。
- `distance_to_high_250d >= core_near_high_250d`，默认 -8%。

第四优先级：`HIGH_TIGHT`

- `rs60_pct >= high_tight_rs60_pct`，默认 85。
- `trend_state in {"STRONG", "MID_STRONG"}`。
- `distance_to_high_250d >= high_tight_near_high_250d`，默认 -8%。
- `contraction_state == CLEAR`。

第五优先级：`ACCELERATING`

`ACCELERATING`：

- `rs60_pct >= accelerating_rs60_pct`，默认 80。
- `rs60_delta_5d >= accelerating_delta_5d`，默认 5。
- `rs60_delta_10d >= accelerating_delta_10d`，默认 8。
- `industry_rs60_delta_5d >= industry.strengthening_delta_5d`，默认 3。
- `trend_state in {"STRONG", "MID_STRONG"}`。

最后：`WATCH`

- 已进入可交易股票池，但未命中上述任何状态。

## 7. 看板里的“强势股票”口径

HTML 表格默认按以下字段排序后展示：

```text
rs60_pct desc, rs120_pct desc
```

也就是说，表格里的“强势股票”不是另一个隐藏筛选器，而是全部可交易股票的 state 分类结果，默认优先展示 60 日和 120 日相对强度更靠前的股票。

如果运行时传入：

```bash
python main.py stats radar --top 300
```

则 HTML 表格只展示排序后的前 300 只；但顶部 KPI 统计使用全量 `strong_stock_radar_latest.csv`，不受 `--top` 影响。

## 8. 可配置阈值

所有主要阈值集中在 `config.yaml` 的 `strong_stock_radar`：

- `universe`
- `rs`
- `trend`
- `high_position`
- `volume_price`
- `contraction`
- `industry`
- `state`
- `evaluation`

`config.example.yaml` 已给出默认配置。

## 9. 当前页面说明

HTML 看板顶部展示：

- 市场环境短摘要。
- 强势行业数量。
- 各类强势股 state 数量。

强势行业表支持排序和点击行业过滤。

行业 RS 轮动区包含最近 26 周周末有效交易日的热力图；点击行业可联动行业历史曲线与个股过滤。曲线使用固定 0-100 纵轴，缺失值保留断点。行业映射来自当前元数据，非严格历史 point-in-time 行业分类。

强势股票表支持：

- 行业过滤。
- state 过滤。
- 趋势过滤。
- RS60 阈值过滤。
- 接近 250 日高点过滤。
- 点击表头排序。

Dashboard 已新增“强势股雷达”入口和信号中心卡片。

## 10. 后验审计说明

生成当日 state 时不使用未来数据。

未来数据只在后续再次运行雷达时，根据历史 snapshot 补充：

- `future_return_5d`
- `future_return_10d`
- `future_return_20d`
- `mfe_20d`
- `mae_20d`

用于回答“这些分类在历史上描述了什么”，不用于调仓或自动交易。

## 11. 已知限制

- 当前可交易过滤中的上市时间使用缓存有效 bar 数近似，不等同严格上市自然日。
- `exclude_suspended` 主要依赖当日有有效 K 线和成交额，不含完整停复牌表。
- ST 过滤依赖当前名称/元数据，历史 ST 时点不严格。
- 行业口径主要来自当前股票元数据，历史行业变更不严格 point-in-time。
- 行业强度第一版按行业内股票等权聚合，不直接使用同花顺行业指数收益作为行业收益。
- 市场环境卡片只展示短摘要，完整市场结构限制仍以 `market_structure_000001.SH.json` 为准。
- 全市场运行当前约 40-50 秒。
