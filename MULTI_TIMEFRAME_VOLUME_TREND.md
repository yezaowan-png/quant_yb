# 多周期量价趋势策略技术设计文档

## 1. 策略定位

本策略是一套基于“三重滤网 + 量价确认 + ATR 风控”的趋势跟随系统。

核心思想：

```text
高周期判断大方向 -> 日线等待回调 -> 量价确认恢复 -> 风控约束入场与退出
```

原始方案中包含周线、日线、小时线三层：

- 周线：判断大趋势方向。
- 日线：识别回调、整理或趋势内低吸位置。
- 小时线或 4 小时线：触发精确入场。

当前项目主要数据粒度是日 K，因此第一版建议先实现为：

```text
周线代理趋势过滤 + 日线回调识别 + 日线量价确认 + ATR 止损/止盈
```

后续再扩展严格周线 feed 和小时线第三屏。

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

## 2. 理论依据

### 2.1 Elder 三重滤网

三重滤网的关键不是某个固定指标，而是决策顺序：

1. 大周期只判断交易方向。
2. 中周期等待逆势回调，不追涨杀跌。
3. 小周期等待趋势恢复的触发信号。

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

趋势跟随系统常见问题是追高。三重滤网通过“趋势内回调”改善入场位置：

- 如果高周期向上，但日线短期回落，说明可能出现更好的风险收益比。
- 如果价格重新突破前高或重新站回短均线，并且成交量确认，则认为回调结束。
- 如果一直没有回调，则继续观望。

第一版将回调定义为一个工程化条件，而不是主观图形：

```text
Close < EMA(daily_ema_period)
or 从近 N 日高点回撤 >= pullback_pct
or RSI <= pullback_rsi
```

可通过参数选择启用哪些回调条件。

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

因此第一版可以只新增策略文件，不改下载器和回测引擎。

### 3.2 当前缺口

原方案要求小时线或 4 小时线入场，但当前项目没有小时线数据链路。

缺口包括：

- 小时线数据下载与缓存。
- 小时线和日线/周线的对齐。
- 多 feed Backtrader 回测。
- 小时线成交量确认。

所以第一版将小时线触发改成日线触发：

```text
日线突破前高 + 日线量价确认
```

### 3.3 第一版实现边界

第一版只实现：

- 多头策略。
- 日线数据。
- 周线趋势用日线代理或日线重采样近似。
- 日线回调识别。
- 日线突破触发。
- VPT/OBV/RVOL 量价确认。
- ATR 止损和可选 R 倍数止盈。

暂不实现：

- 做空。
- 小时线第三屏。
- 真实风险预算仓位。
- 总账户 6% 风险闸门。
- 蒙特卡洛、滚动窗口参数优化。

## 4. 策略信号定义

## 4.1 高周期趋势过滤

第一版提供三种趋势过滤方式：

```text
weekly_macd
weekly_ema
daily_proxy
```

默认使用日线代理的周线趋势，减少对引擎层的改动：

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

可选严格版本：

后续在 `BacktestRunner` 中增加周线 feed 后，使用真实周线：

```text
WeeklyMACDHist > 0
WeeklyEMAFast > WeeklyEMASlow
```

### 4.2 日线回调识别

多头趋势中，回调条件默认使用三选一：

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
pullback_lookback = 20
pullback_pct = 0.02
pullback_rsi = 40
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

第一版若不显式写状态机，也可以通过最近 `pullback_valid_days` 内是否出现过回调来近似：

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
```

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

在现有 `BaseStrategy` 下，成交价来自 Backtrader 订单回调；策略在买入信号时可以用当前 close 近似记录计划止损，成交后再根据实际成交价更新会更准确。第一版可以先用信号日 close 作为入场价近似。

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

### 5.5 量价衰竭卖出

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
| `weekly_fast_ema` | 13 | int | 周线代理快 EMA |
| `weekly_slow_ema` | 26 | int | 周线代理慢 EMA |
| `weekly_macd_fast` | 12 | int | 周线代理 MACD 快线 |
| `weekly_macd_slow` | 26 | int | 周线代理 MACD 慢线 |
| `weekly_macd_signal` | 9 | int | 周线代理 MACD 信号线 |
| `daily_ema_period` | 50 | int | 日线回调均线 |
| `pullback_lookback` | 20 | int | 局部高点回看窗口 |
| `pullback_pct` | 0.02 | float | 从局部高点回撤比例 |
| `pullback_rsi` | 40 | float | 回调 RSI 阈值 |
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

也可以先在策略 `next()` 中用 Python 状态变量计算。

推荐第一版内部状态变量：

```python
self.vpt_value
self.obv_value
self.vpt_history
self.obv_history
self.highest_close_since_entry
self.initial_stop_by_data
```

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
4. 周线代理如果用日线扩周期 EMA，不涉及未来数据；若后续改真实周线 feed，只能使用已完成周线。
5. 未来收益复盘或 dashboard 统计不能影响策略信号。
6. 参数优化只能在样本内进行，样本外结果不得反向调参。

## 9. 回测验证计划

### 9.1 单标的验证

```bash
E:\anaconda3\envs\QYTX\python.exe main.py backtest run --strategy multi_timeframe_volume_trend --symbol 000001.SZ
E:\anaconda3\envs\QYTX\python.exe main.py backtest report --strategy multi_timeframe_volume_trend --symbol 000001.SZ
```

验证：

- 策略能正常加载。
- 指标预热期不报错。
- 交易流水和权益曲线正常导出。
- 报告 HTML 正常生成。

### 9.2 多标的验证

```bash
E:\anaconda3\envs\QYTX\python.exe main.py backtest run --strategy multi_timeframe_volume_trend --symbols "000001.SZ,600519.SH,300750.SZ"
```

验证：

- 大盘股、白马股、高波动成长股都能运行。
- 买点数量不过度稀疏或爆炸。

### 9.3 扫描买点

```bash
E:\anaconda3\envs\QYTX\python.exe main.py backtest scan --strategy multi_timeframe_volume_trend --days 10
```

验证：

- 最近买点候选符合“趋势回调后放量恢复”的叙事。
- 输出 CSV 正常。

### 9.4 全市场统计

```bash
E:\anaconda3\envs\QYTX\python.exe main.py backtest run --strategy multi_timeframe_volume_trend
E:\anaconda3\envs\QYTX\python.exe main.py stats analyze --strategy multi_timeframe_volume_trend
E:\anaconda3\envs\QYTX\python.exe main.py dashboard
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

### 阶段 1：日线可跑版

新增 `strategy/multi_timeframe_volume_trend.py`，实现：

- 周线代理趋势过滤
- 日线回调识别
- 日线突破触发
- VPT/OBV/RVOL 量价确认
- ATR 初始止损和跟踪止损

不改引擎、不改数据层、不改报告字段。

### 阶段 2：严格周线过滤

扩展 `BacktestRunner` 支持真实周线 feed 或在数据进入策略前生成周线特征。

目标：

- 替代日线扩周期代理。
- 更贴近三重滤网理论。

### 阶段 3：报告标注增强

报告中标注：

- 回调发生日
- 突破触发日
- VPT/OBV 确认状态
- ATR 止损线

### 阶段 4：小时线第三屏

新增小时线数据链路后实现：

- 小时 MACD
- 小时 RVOL
- 小时突破前高
- 小时级止损触发

### 阶段 5：组合级风控与稳健性

实现：

- 单笔风险预算仓位
- 总风险 6% 闸门
- 参数敏感性报告
- 滚动样本外验证

## 13. 主要风险

### 13.1 日线版不是完整三重滤网

第一版没有小时线精确入场，入场价格可能不如原方案精细。

### 13.2 量价指标可能滞后

VPT/OBV 本质是累计指标，确认能力强，但反应可能慢。

### 13.3 放量阈值需要适配 A 股

不同股票成交量分布差异很大，统一 `1.5x` 可能过严或过松。

### 13.4 回调定义影响交易频率

如果要求跌破 EMA50，强趋势股票可能很久没有信号；如果用 2% 回撤，震荡股可能信号过多。

## 14. 最终建议

建议后续优先实现阶段 1，作为项目里的“多周期量价趋势基线策略”。

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
