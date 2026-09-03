# 多周期量价趋势策略技术设计文档

## 1. 策略定位

本策略是一套基于“周线趋势过滤 + 日线触发 + 量价确认 + ATR 风控”的趋势跟随系统。

核心思想：

```text
高周期判断大方向 -> 日线等待回调 -> 量价确认恢复 -> 风控约束入场与退出
```

当前确认的实现方案只使用周线和日线两层：

- 周线：判断大趋势方向。
- 日线：识别回调、突破触发和量价确认。

当前项目主要数据粒度是日 K，因此策略基准形态为：

```text
已完成周线趋势过滤 + 日线回调识别 + 日线量价确认 + ATR 止损/止盈
```

不再规划小时线或 4 小时线第三屏，后续优化都以日线交易、周线过滤为边界。

建议策略命名：

```text
multi_timeframe_volume_trend
```

建议策略文件：

```text
strategy/multi_timeframe_volume_trend.py
```

建议策略类：

```text
MultiTimeframeVolumeTrendStrategy
```

## 1.1 Review 阅读路线

如果要重点 review 策略实现，建议按下面顺序看：

1. 本文档第 4-8 节：先确认信号公式、卖出规则、参数和防未来函数要求。
2. `strategy/multi_timeframe_volume_trend.py`：看真实买卖信号实现，重点函数是：
   - `_trend_long()` / `_weekly_trend_long()`：周线长周期过滤。
   - `_current_pullback()` / `_recent_pullback()`：日线回调候选状态。
   - `_breakout_long()`：日线突破触发。
   - `_volume_confirm_count()`：RVOL、VPT、OBV 和收盘上涨确认。
   - `_ensure_state_updated()`：每天只更新一次 VPT/OBV、回调历史和趋势失效计数。
   - `notify_order()`：用 Backtrader 真实成交价建立初始止损和 R 风险。
   - `_next_sell_signal()`：ATR 初始止损、跟踪止损、趋势失效和可选退出。
3. `engine/runner.py::_add_completed_weekly_features()`：看已完成周线特征如何从日 K 重采样并贴回日线，重点确认没有使用未来周线。
4. `visual/report.py::_calc_mtf_diagnostics()`：只用于报告复盘，不参与交易信号。
5. `../../TECHNICAL.md` 的“多周期量价趋势策略”小节：看和项目架构、CLI、报告层的集成说明。

## 1.2 基础指标与术语定义

本节解释本文档和代码中反复出现的基础指标。阅读后面的买入/卖出规则时，可以直接把这些定义代入公式。

### 1.2.1 K 线基础字段

日 K 或周 K 的一根 bar 包含：

| 字段 | 英文 | 含义 |
|---|---|---|
| 开盘价 | `open` | 当前周期第一笔或开盘集合竞价形成的价格 |
| 最高价 | `high` | 当前周期内出现过的最高成交价 |
| 最低价 | `low` | 当前周期内出现过的最低成交价 |
| 收盘价 | `close` | 当前周期最后成交价，本策略大多数信号用收盘价判断 |
| 成交量 | `volume` | 当前周期成交量，Tushare 股票日线 `vol` 通常以“手”为单位，1 手 = 100 股 |

本策略主要使用日 K 作为交易周期；周线特征由日 K 重采样得到，只用于判断长周期方向。

### 1.2.2 SMA：简单移动平均线

SMA 全称 Simple Moving Average，中文常叫简单移动平均线或均线。

```text
SMA_t(n) = (Close_t + Close_{t-1} + ... + Close_{t-n+1}) / n
```

含义：

- `n` 是窗口长度，例如 SMA20 表示最近 20 根 K 线收盘价的平均值。
- SMA 对窗口内每一天给同样权重。
- SMA 越长越平滑，但反应越慢；SMA 越短越灵敏，但噪音更多。

本策略中 SMA 主要用于量价确认：

```text
RVOL = Volume / SMA(Volume, vol_ma_period)
VPT > SMA(VPT, vpt_ma_period)
OBV > SMA(OBV, obv_ma_period)
```

报告里普通 `MA5/MA10/MA20/MA60` 也是 SMA 风格的均线，用于辅助看图；它们不是本策略买入条件里的核心趋势线。

### 1.2.3 EMA：指数移动平均线

EMA 全称 Exponential Moving Average，中文常叫指数移动平均线。

```text
EMA_t(n) = alpha * Close_t + (1 - alpha) * EMA_{t-1}(n)
alpha = 2 / (n + 1)
```

含义：

- EMA 会给越新的价格越高权重，给越久远的价格越低权重。
- 同样周期下，EMA 通常比 SMA 对价格变化更敏感。
- EMA 需要预热期；刚开始的若干根 K 线可能没有稳定值或显示为空。

本策略中使用：

- `EMA50(日线)`：判断日线是否进入回调候选状态。若 `close < EMA50`，认为价格短期回落到趋势均线下方。
- `WeeklyEMAFast`：周线快 EMA，默认 13 周。
- `WeeklyEMASlow`：周线慢 EMA，默认 26 周。

### 1.2.4 快线和慢线

快线/慢线不是单独的指标，而是一组相同指标的不同周期：

```text
快线 = 周期更短的均线或指标线
慢线 = 周期更长的均线或指标线
```

例如：

```text
WeeklyEMAFast = EMA(WeeklyClose, 13)
WeeklyEMASlow = EMA(WeeklyClose, 26)
```

含义：

- 快线更贴近当前价格，反应更快。
- 慢线更平滑，代表更长期的方向。
- 当快线在慢线上方，通常说明中短期价格强于长期趋势。

本策略的周线趋势条件之一是：

```text
WeeklyEMAFast > WeeklyEMASlow
```

这表示周线级别的趋势结构偏多。

### 1.2.5 MACD：趋势动能指标

MACD 全称 Moving Average Convergence Divergence，常用于观察趋势动能。

常见参数是 `12, 26, 9`：

```text
DIF = EMA(Close, 12) - EMA(Close, 26)
DEA = EMA(DIF, 9)
MACDHist = DIF - DEA
```

含义：

- `DIF` 是快慢 EMA 的差值。
- `DEA` 是 DIF 的平滑线。
- `MACDHist` 是 DIF 相对 DEA 的差值，常叫 MACD 柱。
- `MACDHist > 0` 说明短期动能强于其平滑基准，趋势动能偏正。

本策略在周线层使用 MACD 柱：

```text
WeeklyMACDHist > 0
```

它不是单独买点，只是周线趋势过滤的一部分。

### 1.2.6 RSI：相对强弱指标

RSI 全称 Relative Strength Index，用来衡量一段时间内上涨力度和下跌力度的相对关系。

常见公式：

```text
RS = 平均上涨幅度 / 平均下跌幅度
RSI = 100 - 100 / (1 + RS)
```

含义：

- RSI 范围通常在 0 到 100。
- RSI 较低表示近期下跌或回落压力较强。
- RSI 较高表示近期上涨力度较强。

本策略用 RSI 判断“是否出现回调”，默认 RSI 周期是 `rsi_period=14`：

```text
rsi_period = 14
RSI <= 40.0
```

这表示价格已经有一定回落，不追高。它不是买入信号本身，还需要后续突破和量价确认。

### 1.2.7 ATR：平均真实波幅

ATR 全称 Average True Range，用来衡量价格波动幅度。

先计算真实波幅 TR：

```text
TR_t = max(
    High_t - Low_t,
    abs(High_t - Close_{t-1}),
    abs(Low_t - Close_{t-1})
)
```

再对 TR 做平滑得到 ATR：

```text
ATR = 平滑平均(TR, atr_period)
```

含义：

- ATR 越大，说明股票近期波动越大。
- ATR 越小，说明股票近期波动越小。
- 用 ATR 做止损，可以让止损距离随股票波动自动变化。

本策略使用 ATR14：

```text
InitialStop = EntryPrice - atr_mult * ATR(14)
TrailingStop = HighestCloseSinceEntry - trail_atr_mult * ATR(14)
```

### 1.2.8 VPT：量价趋势指标

VPT 全称 Volume Price Trend，把成交量按价格涨跌幅加权累计。

```text
VPT_t = VPT_{t-1} + Volume_t * (Close_t - Close_{t-1}) / Close_{t-1}
```

含义：

- 收盘上涨时，成交量按涨幅加入 VPT。
- 收盘下跌时，成交量按跌幅从 VPT 扣除。
- 涨幅越大、成交量越大，对 VPT 影响越大。

本策略用：

```text
VPT > SMA(VPT, vpt_ma_period)
```

表示量价趋势高于自身均线，是量价确认项之一。

### 1.2.9 OBV：能量潮

OBV 全称 On Balance Volume，根据收盘涨跌方向累计成交量。

```text
if Close_t > Close_{t-1}: OBV_t = OBV_{t-1} + Volume_t
if Close_t < Close_{t-1}: OBV_t = OBV_{t-1} - Volume_t
if Close_t == Close_{t-1}: OBV_t = OBV_{t-1}
```

含义：

- 上涨日把成交量视为流入。
- 下跌日把成交量视为流出。
- OBV 上行通常表示成交量更偏向上涨日。

本策略用：

```text
OBV > SMA(OBV, obv_ma_period)
```

表示成交量累积方向偏多，是量价确认项之一。

### 1.2.10 RVOL：相对成交量

RVOL 全称 Relative Volume，中文可理解为相对成交量。

```text
RVOL = Volume_t / SMA(Volume, vol_ma_period)
```

含义：

- `RVOL = 1.0` 表示今天成交量约等于均量。
- `RVOL = 1.5` 表示今天成交量约为均量的 1.5 倍。
- RVOL 越高，说明当天成交量越明显放大。

本策略默认要求量价确认项之一为：

```text
RVOL >= 1.5
```

注意：本策略计算均量时使用昨天及以前的历史成交量，今天成交量只作为被比较对象，避免把当天成交量混入基准。

### 1.2.11 rolling window、shift 和历史窗口

`rolling window` 指滚动窗口，例如最近 20 日高点：

```text
rolling_max(High, 20)
```

`shift(1)` 表示整体向后错一位，只使用昨天及以前的数据：

```text
RecentHigh = rolling_max(High, 20).shift(1)
```

本策略所有突破和回调基准都必须排除当天：

- 回调高点不能包含今天高点。
- 突破高点不能包含今天高点。
- 均量基准不能包含今天成交量。

这是为了避免未来函数或“用当天结果定义当天门槛”的数据泄露。

### 1.2.12 突破、回调、买入设置

本文档中三个词含义不同：

| 名称 | 含义 | 是否直接买入 |
|---|---|---|
| 回调 | 趋势中价格出现下探或转弱，例如跌破 EMA50、从高点回撤、RSI 偏低 | 否 |
| 突破 | 今日收盘价突破过去 N 日历史高点 | 否 |
| 买入设置 | 周线趋势、近期回调、今日突破、量价确认同时成立 | 是，进入买入信号 |

报告里的蓝色圆点是“回调发生日”，橙色菱形是“突破触发日”，紫色 pin 是完整“买入设置”。

## 2. 理论依据

### 2.1 Elder 三重滤网思想的两层适配

本策略借鉴 Elder 三重滤网的决策顺序，但工程实现固定为“周线 + 日线”两层，不再引入小时线：

1. 大周期只判断交易方向。
2. 日线等待趋势内回调，不追涨杀跌。
3. 日线突破和量价确认作为趋势恢复触发。

在多头方向上：

```text
周线趋势向上 -> 日线出现回调 -> 价格重新转强且量价确认 -> 做多
```

在空头方向上理论可以镜像：

```text
周线趋势向下 -> 日线出现反弹 -> 价格重新转弱且量价确认 -> 做空
```

当前 A 股现货项目建议第一版只做多头。做空镜像可保留在理论文档中，但不进入第一版实现。

### 2.2 趋势跟随与回调买入

趋势跟随系统常见问题是追高。周线过滤叠加日线回调可以改善入场位置：

- 如果高周期向上，但日线短期回落，说明可能出现更好的风险收益比。
- 如果价格重新突破前高或重新站回短均线，并且成交量确认，则认为回调结束。
- 如果一直没有回调，则继续观望。

第一版将回调定义为一个工程化条件，而不是主观图形：

```text
Close < EMA(daily_ema_period)
or 从近 N 日高点回撤 >= pullback_pct
or RSI <= pullback_rsi
```

当前实现固定使用三选一的 OR 逻辑，可通过参数调整各条件的阈值。

### 2.3 量价确认

趋势信号如果没有成交量配合，容易是假突破。本策略使用 VPT、OBV 和相对成交量过滤信号。

#### VPT

VPT 全称 Volume Price Trend：

```text
VPT_t = VPT_{t-1} + Volume_t * (Close_t - Close_{t-1}) / Close_{t-1}
```

含义：

- 收盘上涨时，成交量按涨幅加到 VPT。
- 收盘下跌时，成交量按跌幅从 VPT 扣除。
- VPT 同时考虑价格变化幅度和成交量。

多头确认：

```text
VPT > SMA(VPT, vpt_ma_period)
```

#### OBV

OBV 全称 On Balance Volume：

```text
if Close_t > Close_{t-1}: OBV_t = OBV_{t-1} + Volume_t
if Close_t < Close_{t-1}: OBV_t = OBV_{t-1} - Volume_t
if Close_t == Close_{t-1}: OBV_t = OBV_{t-1}
```

多头确认：

```text
OBV > SMA(OBV, obv_ma_period)
```

#### 相对成交量

```text
RVOL = Volume / SMA(Volume, vol_ma_period)
```

多头突破要求：

```text
RVOL >= volume_mult
```

默认 `volume_mult = 1.5`。

### 2.4 ATR 风控

ATR 用于让止损距离随波动变化：

```text
InitialStop = EntryPrice - atr_mult * ATR(atr_period)
```

相比固定百分比止损，ATR 止损能适配不同价格、不同波动率的股票。

## 3. 当前项目适配方案

### 3.1 当前项目已有能力

当前项目已经具备：

- Tushare 股票日线下载和缓存。
- Backtrader 回测引擎。
- A 股手续费、印花税、滑点、T+1、涨跌停限制。
- 策略基类 `BaseStrategy`。
- 单标的报告、批量回测汇总、策略画像和 dashboard。

当前已落地版本除了新增策略文件，还扩展了回测引擎的数据喂入层：在日线数据进入 Backtrader 前生成已完成周线特征，供策略读取。

### 3.2 当前实现边界

本策略不接入小时线数据链路，统一以日线作为交易决策和成交模拟基准，以已完成周线特征作为长周期过滤。

日线触发定义为：

```text
日线突破前高 + 日线量价确认
```

### 3.3 实现边界

当前版本实现：

- 多头策略。
- 日线数据。
- 周线趋势用日线重采样生成的已完成周线特征。
- 日线回调识别。
- 日线突破触发。
- VPT/OBV/RVOL 量价确认。
- ATR 止损和可选 R 倍数止盈。

暂不实现：

- 做空。
- 小时线或 4 小时线第三屏。
- 真实风险预算仓位。
- 总账户 6% 风险闸门。
- 蒙特卡洛、滚动窗口参数优化。

## 4. 策略信号定义

## 4.1 高周期趋势过滤

当前实现提供两种趋势过滤方式：

```text
weekly
daily_proxy
```

默认使用 `weekly`，也就是由 `BacktestRunner` 在数据进入策略前生成的已完成周线 EMA/MACD 特征：

```text
WeeklyClose = resample(日K, W-FRI).last(close)
WeeklyEMAFast = EMA(WeeklyClose, weekly_fast_ema)
WeeklyEMASlow = EMA(WeeklyClose, weekly_slow_ema)
WeeklyMACDHist = MACD(WeeklyClose, weekly_macd_fast, weekly_macd_slow, weekly_macd_signal).hist
```

周线多头趋势成立：

```text
Close > WeeklyEMASlow
WeeklyEMAFast > WeeklyEMASlow
WeeklyMACDHist > 0
```

这些周线特征通过 `merge_asof(direction="backward")` 贴回日线，只允许当前日读取日期不晚于当前日的已完成周线特征。

`daily_proxy` 保留为对照模式，用日线扩周期近似周线趋势：

```text
TrendEMAFast = EMA(Close, weekly_fast_ema * 5)
TrendEMASlow = EMA(Close, weekly_slow_ema * 5)
TrendMACDHist = MACD(Close, 12 * 5, 26 * 5, 9 * 5).hist
```

多头趋势成立：

```text
Close > TrendEMASlow
TrendEMAFast > TrendEMASlow
TrendMACDHist > 0
```

### 4.2 日线回调识别

多头趋势中，回调条件默认使用三选一，RSI 周期由 `rsi_period` 控制：

```text
Close < EMA(daily_ema_period)
or PullbackFromHigh >= pullback_pct
or RSI <= pullback_rsi
```

其中：

```text
RecentHigh = rolling_max(High, pullback_lookback).shift(1)
PullbackFromHigh = (RecentHigh - Close) / RecentHigh
```

默认参数：

```text
daily_ema_period = 50
rsi_period = 14
pullback_lookback = 20
pullback_pct = 0.02
pullback_rsi = 40.0
```

注意：

- `RecentHigh` 必须使用 `.shift(1)`，不能包含当天高点。
- 回调只表示“进入候选状态”，不是买点。

### 4.3 回调状态机

策略需要记住“已经发生过回调”，再等待趋势恢复。

建议状态：

```text
WAIT_TREND
WAIT_PULLBACK
WAIT_TRIGGER
IN_POSITION
```

状态转换：

```text
WAIT_TREND:
    if trend_long -> WAIT_PULLBACK

WAIT_PULLBACK:
    if not trend_long -> WAIT_TREND
    if pullback_long -> WAIT_TRIGGER

WAIT_TRIGGER:
    if not trend_long -> WAIT_TREND
    if trigger_long -> buy -> IN_POSITION
    if pullback_timeout exceeded -> WAIT_PULLBACK

IN_POSITION:
    if exit_condition -> sell -> WAIT_TREND or WAIT_PULLBACK
```

当前实现不显式保存 `WAIT_TREND/WAIT_PULLBACK/WAIT_TRIGGER` 枚举状态，而是通过最近 `pullback_valid_days` 内是否出现过回调来近似：

```text
RecentPullback = rolling_any(pullback_long, pullback_valid_days)
```

默认：

```text
pullback_valid_days = 10
```

### 4.4 日线入场触发

日线多头触发：

```text
BreakoutLong =
    Close > rolling_max(High, breakout_lookback).shift(1)
```

默认：

```text
breakout_lookback = 3
```

也可使用前一日高点：

```text
Close > High[-1]
```

第一版建议默认用 `breakout_lookback = 3`，比单日前高更稳定。

### 4.5 量价确认

多头量价确认至少满足以下条件中的两个：

```text
RVOL >= volume_mult
VPT > SMA(VPT, vpt_ma_period)
OBV > SMA(OBV, obv_ma_period)
Close > Close[-1]
```

建议参数：

```text
volume_mult = 1.5
vol_ma_period = 20
vpt_ma_period = 20
obv_ma_period = 20
min_volume_confirmations = 2
```

买入信号：

```text
trend_long
and recent_pullback
and breakout_long
and volume_confirm_count >= min_volume_confirmations
and not post_acceleration_platform_filter
and no volume_stalling in last stalling_buy_filter_days known daily bars
```

### 4.1 加速上涨后平台震荡禁买

这个过滤用于处理“已经加速上涨过，随后回落进入平台震荡”的形态。在平台没有真正带量突破前，不执行新的买入。

加速上涨不是只看当前日，而是做滚动扫描：

```text
recent_acceleration =
    any(
        close[end] / close[end - accel_lookback] - 1 >= accel_return_pct
        for end in last accel_scan_days known daily bars
    )
```

默认：

```text
accel_lookback = 10
accel_scan_days = 60
accel_return_pct = 0.30
```

例如当前是 8 号，如果 4 号往前 10 个交易日累计涨幅超过 30%，也算近期发生过加速上涨。

发生过加速上涨后，进入禁买状态。若随后识别到回落平台，则继续禁买：

```text
platform_range <= platform_max_range_pct
and abs(MA20_now / MA20_5_days_ago - 1) <= platform_ma_slope_pct
and pullback_from_recent_peak >= post_accel_pullback_pct
```

默认：

```text
post_accel_pullback_pct = 0.08
platform_lookback = 20
platform_max_range_pct = 0.10
platform_ma_slope_pct = 0.03
```

只有平台被带量突破后，解除禁买：

```text
close > platform_high[-platform_lookback:-1] * (1 + platform_breakout_pct)
and volume / SMA(volume, vol_ma_period)[t-1] >= platform_breakout_volume_mult
```

默认：

```text
platform_breakout_pct = 0.01
platform_breakout_volume_mult = 1.5
```

默认启用买入前滞涨过滤：

```text
use_stalling_buy_filter = true
stalling_buy_filter_days = 5
```

因为买入信号在日线收盘后产生、实际成交在下一根 bar，过滤窗口包含信号日自身和之前交易日。这些都是买入执行前已经可见的数据，不涉及未来函数。

## 5. 卖出与风控

### 5.1 初始止损

多头初始止损：

```text
InitialStop = EntryPrice - atr_mult * ATR
```

默认：

```text
atr_period = 14
atr_mult = 2.0
```

成交价来自 Backtrader 订单成交回调。当前实现会在 `notify_order()` 中用真实成交价计算初始止损和 R 风险，不使用信号日收盘价手工替代成交价。

如果历史兼容或异常状态导致策略内记录的入场价缺失，但 Backtrader 仍显示持仓存在，
卖出判断会使用 Backtrader 的持仓均价作为兜底入场价，并按当前 ATR 补建初始止损和 R 风险。
这是防御性逻辑，只用于已有持仓状态恢复，不改变正常成交路径。

### 5.2 移动止损

入场后跟踪最高收盘价：

```text
HighestCloseSinceEntry = max(Close since entry)
TrailingStop = HighestCloseSinceEntry - trail_atr_mult * ATR
```

默认：

```text
trail_atr_mult = 2.5
```

卖出条件：

```text
Close < InitialStop
or Close < TrailingStop
```

### 5.3 R 倍数止盈

可选止盈：

```text
R = EntryPrice - InitialStop
TakeProfit = EntryPrice + take_profit_r * R
```

默认：

```text
take_profit_r = 3.0
```

第一版可提供参数：

```text
use_take_profit = false
```

默认关闭固定止盈，让 ATR 移动止损跟随趋势。

### 5.4 趋势失效卖出

如果高周期趋势失效，应退出：

```text
trend_long == false
```

为了避免轻微抖动，可增加确认天数：

```text
trend_exit_confirm_days = 2
```

### 5.5 放量滞涨后跌破短均线卖出

如果持仓期间出现放量但价格没有继续有效上攻，先进入短线防守状态；后续一旦收盘价跌破短均线，清仓离场。

放量滞涨定义：

```text
volume / SMA(volume, vol_ma_period)[t-1] >= stalling_volume_mult
and (
    close <= open
    or close / close[-1] - 1 <= stalling_max_close_gain_pct
    or (
        close[-1] / close[-2] - 1 >= stalling_prev_gain_min_pct
        and close / close[-1] - 1 > stalling_max_close_gain_pct
        and (close[-1] / close[-2] - 1) - (close / close[-1] - 1) >= stalling_gain_fade_pct
        and upper_shadow / close[-1] >= stalling_upper_shadow_pct
        and (close - low) / (high - low) <= stalling_close_position_max
    )
)
```

默认：

```text
use_stalling_ma_exit = true
use_entry_day_stalling_exit = true
stalling_volume_mult = 1.3
stalling_max_close_gain_pct = 0.005
stalling_prev_gain_min_pct = 0.05
stalling_gain_fade_pct = 0.025
stalling_upper_shadow_pct = 0.04
stalling_close_position_max = 0.60
stalling_exit_ma_period = 5
```

触发放量滞涨后，卖出条件为：

```text
close < SMA(close, stalling_exit_ma_period)
```

如果买入成交当天就出现放量滞涨，则不等待跌破短均线，直接在下一根 K 线开盘清仓。这样可以处理“信号日收盘给出买点、次日开盘成交，但成交当天走成放量长上影滞涨”的情况。

例如 `000001.SZ` 的 `2023-01-30`，成交量约为过去 20 日均量的 1.31 倍，收盘仅较前收微涨且低于开盘，进入放量滞涨防守；后续跌破 5 日线时触发清仓信号。

### 5.6 量价衰竭卖出

如果价格上涨但量价确认转弱，触发谨慎退出：

```text
Close > Close[-1]
and RVOL < 1.0
and VPT < SMA(VPT, vpt_ma_period)
```

第一版建议作为可选卖出条件：

```text
use_volume_exhaust_exit = false
```

避免过早退出趋势。

## 6. 参数设计

| 参数 | 默认值 | 类型 | 说明 |
|---|---:|---|---|
| `trend_filter_mode` | weekly | str | 趋势过滤模式，`weekly` 使用已完成周线特征，`daily_proxy` 使用日线扩周期代理 |
| `weekly_fast_ema` | 13 | int | 周线快 EMA |
| `weekly_slow_ema` | 26 | int | 周线慢 EMA |
| `weekly_macd_fast` | 12 | int | 周线 MACD 快线 |
| `weekly_macd_slow` | 26 | int | 周线 MACD 慢线 |
| `weekly_macd_signal` | 9 | int | 周线 MACD 信号线 |
| `daily_ema_period` | 50 | int | 日线回调均线 |
| `rsi_period` | 14 | int | RSI 周期 |
| `pullback_lookback` | 20 | int | 局部高点回看窗口 |
| `pullback_pct` | 0.02 | float | 从局部高点回撤比例 |
| `pullback_rsi` | 40.0 | float | 回调 RSI 阈值 |
| `pullback_valid_days` | 10 | int | 回调有效期 |
| `breakout_lookback` | 3 | int | 突破高点窗口 |
| `vol_ma_period` | 20 | int | 均量周期 |
| `volume_mult` | 1.5 | float | 放量倍数 |
| `vpt_ma_period` | 20 | int | VPT 均线周期 |
| `obv_ma_period` | 20 | int | OBV 均线周期 |
| `min_volume_confirmations` | 2 | int | 最少量价确认数量 |
| `atr_period` | 14 | int | ATR 周期 |
| `atr_mult` | 2.0 | float | 初始止损 ATR 倍数 |
| `trail_atr_mult` | 2.5 | float | 移动止损 ATR 倍数 |
| `trend_exit_confirm_days` | 2 | int | 周线趋势失效确认天数 |
| `use_post_accel_platform_filter` | true | bool | 是否过滤加速上涨后的平台震荡买入 |
| `accel_lookback` | 10 | int | 加速上涨累计涨幅窗口 |
| `accel_scan_days` | 60 | int | 向前扫描加速上涨的交易日数 |
| `accel_return_pct` | 0.30 | float | 加速上涨累计涨幅阈值 |
| `post_accel_pullback_pct` | 0.08 | float | 加速后回落确认比例 |
| `platform_lookback` | 20 | int | 加速后平台观察窗口 |
| `platform_max_range_pct` | 0.10 | float | 平台最大振幅 |
| `platform_ma_slope_pct` | 0.03 | float | 平台均线走平阈值 |
| `platform_breakout_pct` | 0.01 | float | 解除平台过滤的突破幅度 |
| `platform_breakout_volume_mult` | 1.5 | float | 解除平台过滤的放量倍数 |
| `use_stalling_buy_filter` | true | bool | 是否过滤近 N 日放量滞涨后的买入 |
| `stalling_buy_filter_days` | 5 | int | 买入前放量滞涨过滤交易日数 |
| `use_stalling_ma_exit` | true | bool | 是否启用放量滞涨后跌破短均线清仓 |
| `use_entry_day_stalling_exit` | true | bool | 买入成交当天放量滞涨时是否下一根 K 线开盘退出 |
| `stalling_volume_mult` | 1.3 | float | 放量滞涨的相对成交量阈值 |
| `stalling_max_close_gain_pct` | 0.005 | float | 滞涨允许的最大收盘涨幅 |
| `stalling_prev_gain_min_pct` | 0.05 | float | 冲高回落滞涨要求的前一日最小涨幅 |
| `stalling_gain_fade_pct` | 0.025 | float | 冲高回落滞涨要求的涨幅衰减 |
| `stalling_upper_shadow_pct` | 0.04 | float | 冲高回落滞涨要求的上影线比例 |
| `stalling_close_position_max` | 0.60 | float | 冲高回落滞涨允许的最高收盘位置 |
| `stalling_exit_ma_period` | 5 | int | 放量滞涨后的清仓均线周期 |
| `use_take_profit` | false | bool | 是否启用固定 R 止盈 |
| `take_profit_r` | 3.0 | float | 固定止盈 R 倍数 |
| `use_volume_exhaust_exit` | false | bool | 是否启用量价衰竭退出 |

## 7. 代码实现设计

### 7.1 新增策略文件

```text
strategy/multi_timeframe_volume_trend.py
```

类：

```python
class MultiTimeframeVolumeTrendStrategy(BaseStrategy):
    ...
```

必须继承：

```python
from strategy.base import BaseStrategy
```

### 7.2 策略接口

实现：

```python
def _init_indicators(self):
    ...

def _next_buy_signal(self, data) -> bool:
    ...

def _next_sell_signal(self, data) -> bool:
    ...
```

如启用部分止盈，需要覆盖：

```python
def _next_sell_size(self, data, pos) -> int:
    ...
```

第一版建议不做部分止盈，减少和基类成交逻辑的耦合。

### 7.3 指标实现

Backtrader 可直接使用：

```text
EMA
MACD
RSI
ATR
Highest
SMA
```

VPT 和 OBV 可以手写 line 逻辑：

```text
VPT 当前值 = VPT 前值 + volume * close pct change
OBV 当前值 = OBV 前值 +/- volume
```

当前实现使用 Python 状态变量计算 VPT/OBV，并通过 `_ensure_state_updated()` 保证同一交易日只推进一次状态。

当前实现的核心内部状态变量：

```python
self._vpt_value
self._obv_value
self._vpt_history
self._obv_history
self._pullback_history
self._highest_close_since_entry
self._entry_price
self._initial_stop
self._entry_risk
self._trend_fail_count
```

这些状态都以 `data` 为 key 分开存储，避免多标的回测时不同股票互相污染。

### 7.4 参数元数据

新增：

```python
PARAM_DEFINITIONS = {
    "daily_ema_period": {"type": int, "default": 50, "help": "日线回调 EMA 周期"},
    "pullback_pct": {"type": float, "default": 0.02, "help": "从局部高点回撤比例"},
    "volume_mult": {"type": float, "default": 1.5, "help": "放量倍数"},
    "atr_mult": {"type": float, "default": 2.0, "help": "初始止损 ATR 倍数"},
}
```

这样 CLI 和 REPL 能自动识别参数。

### 7.5 输出与兼容性

第一版不改变现有交易流水字段：

```text
date,symbol,direction,price,size,commission,pnl
```

同时，回测会为交易流水写入同名 `*.params.json` 边车文件，例如：

```text
000001.SZ_multi_timeframe_volume_trend.csv
000001.SZ_multi_timeframe_volume_trend.params.json
```

HTML 报告中的多周期诊断标记、EMA 线和 ATR 止损线会优先读取该边车文件，
使用本次回测的实际参数复算展示层指标。这样即使用户用
`--volume-mult 2.0`、`--atr-mult 3.0` 等非默认参数回测，报告也不会再按默认值解释信号。
旧交易流水如果没有边车文件，报告会退回策略默认参数生成。

后续可考虑新增：

```text
setup_tag
initial_stop
exit_reason
volume_confirm_count
```

但这需要同步修改报告和统计分析。

## 8. 防未来函数要求

必须遵守：

1. `rolling_max(High, breakout_lookback)` 必须使用上一 bar 完成值，不能包含当天。
2. `RecentHigh` 必须只使用历史 bar。
3. 回调条件可以使用当前收盘，但买入执行由 Backtrader 下一步成交模型处理。
4. 周线过滤只能使用已完成周线特征，不能使用尚未收完的未来周线信息。
5. 未来收益复盘或 dashboard 统计不能影响策略信号。
6. 参数优化只能在样本内进行，样本外结果不得反向调参。

## 9. 回测验证计划

### 9.1 单标的验证

```bash
python main.py backtest run --strategy multi_timeframe_volume_trend --symbol 000001.SZ
python main.py backtest report --strategy multi_timeframe_volume_trend --symbol 000001.SZ
```

验证：

- 策略能正常加载。
- 指标预热期不报错。
- 交易流水和权益曲线正常导出。
- 报告 HTML 正常生成。

### 9.2 多标的验证

```bash
python main.py backtest run --strategy multi_timeframe_volume_trend --symbols "000001.SZ,600519.SH,300750.SZ"
```

验证：

- 大盘股、白马股、高波动成长股都能运行。
- 买点数量不过度稀疏或爆炸。

### 9.3 扫描买点

```bash
python main.py backtest scan --strategy multi_timeframe_volume_trend --days 10
```

验证：

- 最近买点候选符合“趋势回调后放量恢复”的叙事。
- 输出 CSV 正常。

### 9.4 全市场统计

```bash
python main.py backtest run --strategy multi_timeframe_volume_trend
python main.py stats analyze --strategy multi_timeframe_volume_trend
python main.py dashboard
```

验证：

- 生成 `_summary_multi_timeframe_volume_trend.csv`
- 生成策略画像 HTML
- dashboard 自动识别新策略

## 10. 稳健性测试建议

第一版跑通后，建议测试三组参数。

### 保守型

```text
daily_ema_period = 50
pullback_pct = 0.03
breakout_lookback = 5
volume_mult = 1.8
min_volume_confirmations = 3
atr_mult = 2.5
trail_atr_mult = 3.0
```

特点：信号少，过滤强。

### 平衡型

```text
daily_ema_period = 50
pullback_pct = 0.02
breakout_lookback = 3
volume_mult = 1.5
min_volume_confirmations = 2
atr_mult = 2.0
trail_atr_mult = 2.5
```

特点：推荐默认。

### 激进型

```text
daily_ema_period = 30
pullback_pct = 0.015
breakout_lookback = 2
volume_mult = 1.2
min_volume_confirmations = 2
atr_mult = 1.8
trail_atr_mult = 2.0
```

特点：信号更多，假突破更多。

## 11. 与前一个 Wyckoff Triple Screen 策略的区别

| 维度 | 本策略 | Wyckoff Triple Screen |
|---|---|---|
| 核心思想 | 趋势回调 + 量价确认 | 威科夫结构事件 + 三重滤网 |
| 主观结构 | 少 | 较多 |
| 主要信号 | EMA、MACD、VPT、OBV、RVOL、突破 | Spring、Test、SOS、LPS |
| 第一版实现难度 | 较低 | 中等 |
| 可解释性 | 偏指标化 | 偏结构化 |
| 适合用途 | 通用趋势跟随基线 | 深度量价结构研究 |

建议先实现本策略作为“多周期量价趋势基线”，再实现 Wyckoff 版作为更复杂的结构策略。两者后续可以在 `stats compare` 中横向对比。

## 12. 实施阶段规划

### 阶段 1：日线可跑版（已落地）

新增 `strategy/multi_timeframe_volume_trend.py`，实现：

- 日线扩周期代理趋势过滤
- 日线回调识别
- 日线突破触发
- VPT/OBV/RVOL 量价确认
- ATR 初始止损和跟踪止损

不改引擎、不改数据层、不改报告字段。

### 阶段 2：严格周线过滤（已落地）

扩展 `BacktestRunner` 在数据进入策略前生成周线特征。

目标：

- 替代日线扩周期代理。
- 更贴近“长周期过滤、短周期触发”的策略设计。

实际实现：

- 采用“数据进入策略前生成周线特征”的路线，避免新增第二个 Backtrader 周线 feed 后触发基类对周线 data 下单。
- `engine/runner.py::_add_completed_weekly_features()` 从日 K 重采样 `W-FRI` 周线收盘价，计算 `weekly_ema_fast`、`weekly_ema_slow`、`weekly_macd_hist`。
- 使用 `merge_asof(direction="backward")` 把日期不晚于当前交易日的已完成周线特征贴回日线 bar，避免读取未来周线。
- `strategy/multi_timeframe_volume_trend.py` 默认 `trend_filter_mode=weekly`，读取上述周线特征；`daily_proxy` 保留为阶段 1 对照模式。

### 阶段 3：报告标注增强（已落地）

报告中标注：

- 回调发生日
- 突破触发日
- VPT/OBV 确认状态
- ATR 止损线

实际实现：

- `visual/report.py` 在生成 `multi_timeframe_volume_trend` 单标的报告时复算诊断序列。
- 日 K 图新增回调、突破和买入设置标记。
- 日 K 图新增 EMA50(日线) 线，用于对照回调条件中的 `close < EMA50`。
- 日 K 图新增 ATR 初始止损和 ATR 跟踪止损线。
- 报告顶部新增诊断卡片：周线趋势、近10日回调、今日突破、量价确认数量和买入设置状态。
- 该增强只影响 HTML 报告展示，不改变策略信号、交易流水 CSV 字段或统计口径。

### 阶段 4：日线/周线优化（待落地）

不再新增小时线数据链路。后续优化集中在当前日线/周线框架内：

- 参数敏感性检查
- 不同市场环境下的表现拆分
- 回调、突破、量价确认阈值的稳健性对比
- 买点信号复盘和 dashboard 化

### 阶段 5：组合级风控与稳健性

实现：

- 单笔风险预算仓位
- 总风险 6% 闸门
- 参数敏感性报告
- 滚动样本外验证

## 13. 主要风险

### 13.1 日线触发不追求小时级精确入场

当前策略明确不接入小时线，买点为日线收盘后信号、下一 bar 由 Backtrader 成交模型处理。优点是数据链路简单、可复现性更强；缺点是入场精度不追求小时级优化。

### 13.2 量价指标可能滞后

VPT/OBV 本质是累计指标，确认能力强，但反应可能慢。

### 13.3 放量阈值需要适配 A 股

不同股票成交量分布差异很大，统一 `1.5x` 可能过严或过松。

### 13.4 回调定义影响交易频率

如果要求跌破 EMA50，强趋势股票可能很久没有信号；如果用 2% 回撤，震荡股可能信号过多。

## 14. 最终建议

当前阶段 1-3 已落地。后续建议优先围绕日线/周线版本做稳健性验证和组合级风控，而不是扩展小时线。

推荐第一版买入公式：

```text
trend_long
and recent_pullback
and close > highest(high, breakout_lookback).shift(1)
and volume_confirm_count >= 2
```

推荐第一版卖出公式：

```text
close < initial_stop
or close < trailing_stop
or trend_long == false
```

这套规则足够清晰、参数较少、和当前项目兼容性高，适合作为后续 Wyckoff 结构策略、AI 决策留痕、dashboard 信号复盘的基础对照组。
