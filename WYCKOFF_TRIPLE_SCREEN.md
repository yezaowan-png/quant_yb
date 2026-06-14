# Wyckoff Triple Screen 策略技术设计文档

## 1. 设计目标

本策略把威科夫量价分析与 Elder《以交易为生》的三重滤网框架合并成一个可回测、可扫描、可解释的 A 股多头策略。

核心目标不是完整复刻人工威科夫读盘，而是把其中最稳定、最容易程序化的部分抽象出来：

- 用周线趋势过滤决定只在大方向有利时寻找机会。
- 用日线 Elder Force Index 与威科夫事件识别寻找回调、吸筹、突破和回踩。
- 用 ATR、结构低点、R 倍数和组合风险阈值管理交易风险。
- 在交易日志中保留 `setup_tag`，便于后续统计哪类结构最有效。

当前项目以日 K 为主，因此第一版建议实现为“周线过滤 + 日线结构 + 日线执行”的可跑版本。小时线执行层、VWAP/AVWAP、月度组合风险闸门和加仓逻辑作为后续增强。

## 2. 理论框架

### 2.1 威科夫三大定律

#### 供求定律

价格上涨通常代表需求强于供给，价格下跌通常代表供给强于需求。程序无法直接看到真实主动买卖盘，因此用 OHLCV 构造近似变量：

```text
CLV = (Close - Low) / (High - Low + eps)
RVOL = Volume / SMA(Volume, n)
NormSpread = (High - Low) / ATR(n)
NetPressure = RVOL * NormSpread * (2 * CLV - 1)
```

其中：

- `CLV` 越接近 1，说明收盘越靠近日内高点。
- `RVOL` 衡量成交量是否显著高于近期均量。
- `NormSpread` 衡量当日价格扩张是否显著。
- `NetPressure` 作为买压/卖压的近似值。

#### 因果定律

威科夫中的“Cause”通常来自横盘、吸筹或派发区间，后续趋势是“Effect”。程序化第一版不做完整 PnF 横向计数，而采用交易区间宽度与持续时间近似识别基础结构：

```text
RangeHigh = rolling_max(High, range_len)
RangeLow = rolling_min(Low, range_len)
RangeWidth = (RangeHigh - RangeLow) / Close
RangeCandidate = RangeWidth <= max_range_pct
```

该条件只说明股票进入相对收敛的结构区域，不直接等同于吸筹。后续必须结合 Spring、SOS、LPS 等量价事件确认。

#### 努力与结果定律

成交量代表努力，价格扩张代表结果。健康趋势中，高成交量通常伴随有效价格推进；如果成交量极高但价差很小，可能表示吸收、衰竭或分歧。

```text
Effort = RVOL
Result = NormSpread
EffortResultExhaust = RVOL > 2.0 and NormSpread < 0.6
```

该信号在第一版中主要用于减仓或卖出过滤，不建议直接作为独立买入信号。

### 2.2 Elder 三重滤网

Elder 的三重滤网强调决策顺序：

1. 大周期判断方向。
2. 中周期等待逆势回调或结构机会。
3. 小周期执行入场。

完整原版可设计为：

```text
周线趋势过滤 -> 日线回调/威科夫结构 -> 小时线突破触发
```

但当前项目主数据粒度为日 K，因此第一版工程化实现为：

```text
周线趋势过滤 -> 日线 Elder/Wyckoff 设置 -> 下一日执行
```

这样可以先验证策略思想是否有边际，再决定是否扩展小时线数据层和多周期执行层。

## 3. 当前项目落地边界

### 3.1 当前已有能力

项目当前具备：

- Tushare 股票日线下载与本地 CSV 缓存。
- Backtrader 事件驱动回测。
- A 股手续费、印花税、滑点、涨跌停、T+1 和成交量上限约束。
- 策略类继承 `strategy.base.BaseStrategy`。
- 批量回测汇总、策略画像、单标的 HTML 报告。
- 日 K/周 K/月 K 可视化能力。

因此第一版策略可以不改数据下载和引擎主体，直接新增一个策略模块。

### 3.2 当前缺口

完整策略还需要但当前没有的能力：

- 小时线或分钟线下载、缓存与回测 feed。
- 多周期数据对齐，尤其是“小时线只读取已完成日线/周线 bar”。
- VWAP/Anchored VWAP 的稳定实现。
- 订单级止损单、分批止盈、加仓、月度风险闸门。
- 做空逻辑。A 股现货环境下第一版不建议实现做空镜像。

### 3.3 第一版范围

第一版策略命名建议：

```text
wyckoff_triple_screen
```

文件：

```text
strategy/wyckoff_triple_screen.py
```

策略类：

```text
WyckoffTripleScreenStrategy
```

第一版只做多头，使用日 K 数据，内部把日线重采样为周线特征。

## 4. 指标与特征定义

### 4.1 周线趋势过滤

周线由日线重采样得到。任意交易日只允许使用上一根已完成周线数据。

多头趋势成立条件：

```text
WeeklyClose > WeeklyEMA26
WeeklyEMA13 > WeeklyEMA26
WeeklyMACDHist > 0
WeeklyMACDHist > WeeklyMACDHist[-1]
```

含义：

- `Close > EMA26`：价格站在中期趋势之上。
- `EMA13 > EMA26`：周线均线多头排列。
- `MACDHist > 0`：趋势动量为正。
- `MACDHist 上升`：动量没有衰退。

第一版可提供参数开关：

```text
use_weekly_filter = true
weekly_fast_ema = 13
weekly_slow_ema = 26
weekly_macd_fast = 12
weekly_macd_slow = 26
weekly_macd_signal = 9
```

### 4.2 日线 Elder 回调

Force Index 定义：

```text
ForceIndex1 = (Close - Close[-1]) * Volume
EFI2 = EMA(ForceIndex1, 2)
```

趋势背景：

```text
DailyEMA22 = EMA(Close, 22)
```

多头回调成立：

```text
EFI2 < 0
Close > EMA22
not AbnormalSupply
```

含义：

- 周线向上时，日线短期回落。
- 价格仍在 EMA22 上方，说明回调未破坏日线趋势。
- 没有异常供应，避免接入放量大阴线。

### 4.3 日线威科夫交易区间

交易区间用于构造支撑、阻力和后续 Spring/SOS/LPS。

```text
Support = rolling_min(Low, range_len).shift(1)
Resistance = rolling_max(High, range_len).shift(1)
RangeWidth = (Resistance - Support) / Close
RangeCandidate = RangeWidth <= max_range_pct
```

必须使用 `.shift(1)`，因为当天信号不能把当天高低点纳入区间边界，否则会产生未来函数或当天自我定义问题。

建议默认值：

```text
range_len = 40
max_range_pct = 0.18
```

### 4.4 CLV、RVOL 与 ATR

```text
ATR = AverageTrueRange(high, low, close, atr_period)
Spread = High - Low
NormSpread = Spread / ATR
RVOL = Volume / SMA(Volume, rvol_period)
CLV = (Close - Low) / (High - Low + eps)
```

建议默认值：

```text
atr_period = 20
rvol_period = 20
```

### 4.5 Spring

Spring 是跌破支撑后快速收回，表示潜在洗盘或供应测试。

```text
is_spring =
    RangeCandidate
    and Low < Support * (1 - spring_penetration)
    and Close > Support
    and CLV > spring_clv_min
    and RVOL >= spring_rvol_min
```

默认参数：

```text
spring_penetration = 0.005
spring_clv_min = 0.55
spring_rvol_min = 1.2
```

注意：

- Spring 不等于立即买入。
- 更稳的做法是等待 Test 或后续突破确认。

### 4.6 Test

Test 是 Spring 后若干日内再次回落但不创新低，并且成交量缩小。

第一版可以用滚动事件状态实现：

```text
is_test =
    within_n_days_after_spring
    and Low > SpringLow
    and Close > Support
    and RVOL < SpringRVOL * test_rvol_ratio
```

默认参数：

```text
test_lookahead = 10
test_rvol_ratio = 0.8
```

Test 触发后，`setup_tag = SPRING_TESTED`。

### 4.7 SOS

SOS 是放量、宽价差、收盘靠近高点的有效突破。

```text
is_sos =
    RangeCandidate
    and Close > Resistance
    and NormSpread >= sos_spread_atr_min
    and RVOL >= sos_rvol_min
    and CLV >= sos_clv_min
```

默认参数：

```text
sos_spread_atr_min = 1.2
sos_rvol_min = 1.5
sos_clv_min = 0.70
```

SOS 触发后，`setup_tag = SOS_CONFIRMED`。

### 4.8 LPS

LPS 是 SOS 后的低量回踩，要求价格仍站在原阻力上方附近。

```text
is_lps =
    within_n_days_after_sos
    and Close > PriorResistance
    and abs(Low - PriorResistance) <= ATR
    and RVOL <= lps_rvol_max
    and NormSpread <= lps_spread_atr_max
```

默认参数：

```text
lps_lookahead = 15
lps_rvol_max = 1.0
lps_spread_atr_max = 1.0
```

LPS 触发后，`setup_tag = LPS_READY`。

### 4.9 异常供应

异常供应用于过滤买入、触发谨慎减仓或卖出。

```text
abnormal_supply =
    Close < Open
    and RVOL > abnormal_supply_rvol
    and CLV < abnormal_supply_clv
    and NormSpread > abnormal_supply_spread_atr
```

默认参数：

```text
abnormal_supply_rvol = 1.5
abnormal_supply_clv = 0.25
abnormal_supply_spread_atr = 1.2
```

## 5. 买入逻辑

第一版多头买入信号：

```text
weekly_bias_long
and (
    elder_pullback_long
    or is_test
    or is_sos
    or is_lps
)
and not abnormal_supply
```

信号优先级：

```text
LPS_READY > SOS_CONFIRMED > SPRING_TESTED > EFI_PULLBACK
```

如果同一天多个条件成立，交易日志记录最高优先级标签。

建议 `setup_tag`：

| 标签 | 来源 | 含义 |
|---|---|---|
| `EFI_PULLBACK` | Elder 回调 | 周线趋势向上，日线短期回落 |
| `SPRING_TESTED` | Spring + Test | 潜在洗盘后供应缩小 |
| `SOS_CONFIRMED` | SOS | 放量突破阻力 |
| `LPS_READY` | LPS | 突破后低量回踩 |

## 6. 卖出与风控逻辑

### 6.1 第一版简化卖出

为了适配当前 `BaseStrategy`，第一版建议先用可落地的日线卖出条件：

```text
Close < EMA22
or Close < trailing_stop
or abnormal_supply
or weekly_bias_long == false
```

其中 `trailing_stop` 可用：

```text
highest_close_since_entry - trail_atr_mult * ATR
```

默认：

```text
trail_atr_mult = 2.5
```

### 6.2 结构止损

入场时记录结构止损：

```text
structure_stop =
    SpringLow if setup_tag == SPRING_TESTED
    PriorResistance - ATR if setup_tag == LPS_READY
    Low - 0.5 * ATR otherwise
```

第一版在 Backtrader 基类限制下，可以先把结构止损转为每日检查的卖出条件：

```text
Close < initial_stop
```

后续增强时可改成 intraday stop order 或 next-bar stop 模拟。

### 6.3 R 倍数管理

完整版本建议：

```text
R = EntryPrice - InitialStop
TP1 = EntryPrice + 2R
TP2 = EntryPrice + 4R
```

第一版若不改基类，可以先不做分批止盈，只做：

```text
Close >= EntryPrice + 2R -> 卖出 50%
剩余仓位使用 ATR 跟踪止损
```

这需要策略覆盖 `_next_sell_size(data, pos)`。

### 6.4 仓位管理

当前 `BaseStrategy` 默认使用 95% 可用资金买入。该策略理论上更适合风险预算仓位：

```text
risk_capital = equity * risk_per_trade
per_share_risk = EntryPrice - StopPrice
size = floor(risk_capital / per_share_risk / 100) * 100
```

但这会突破当前基类统一买入逻辑。建议实施顺序：

1. v1 使用基类 95% 仓位，先验证信号有效性。
2. v2 增加可选风险预算下单模式。
3. v3 增加组合同时暴露风险与月度 6% 闸门。

## 7. 防未来函数要求

本策略必须严格遵守以下规则：

1. 交易区间边界必须使用 `shift(1)` 后的历史高低点。
2. 周线过滤只能使用已完成周线，不能使用当前未收盘周线。
3. 日线买入信号只能使用当前 bar 及之前数据。
4. 若未来实现小时线第三屏，小时线在任一时刻只能读取上一根已完成日线和周线。
5. Spring 后 Test、SOS 后 LPS 的检测不能反向标记历史交易，只能在事件发生后向前推进状态。
6. 报告层不得重新定义信号，也不得把回测结果反向影响策略。

第一版推荐在 pandas 预计算时生成所有特征，但策略读取时仍必须遵守 Backtrader 当前 bar 的可见性。

## 8. 代码实现设计

### 8.1 策略文件结构

```text
strategy/wyckoff_triple_screen.py
```

类定义：

```python
class WyckoffTripleScreenStrategy(BaseStrategy):
    params = (
        ("weekly_fast_ema", 13),
        ("weekly_slow_ema", 26),
        ("daily_ema", 22),
        ("efi_period", 2),
        ("atr_period", 20),
        ("rvol_period", 20),
        ("range_len", 40),
        ("max_range_pct", 0.18),
        ...
    )
```

### 8.2 参数元数据

需要补充：

```python
PARAM_DEFINITIONS = {
    "weekly_fast_ema": {"type": int, "default": 13, "help": "周线快 EMA"},
    "weekly_slow_ema": {"type": int, "default": 26, "help": "周线慢 EMA"},
    "daily_ema": {"type": int, "default": 22, "help": "日线趋势 EMA"},
    "range_len": {"type": int, "default": 40, "help": "威科夫交易区间长度"},
    "max_range_pct": {"type": float, "default": 0.18, "help": "交易区间最大宽度"},
    "sos_rvol_min": {"type": float, "default": 1.5, "help": "SOS 最小相对成交量"},
}
```

这样 CLI、REPL、流水线都能自动识别参数。

### 8.3 指标实现方式

Backtrader 内置指标适合 EMA、MACD、ATR。Force Index、RVOL、CLV、威科夫状态建议在策略内部用 line buffer 或轻量 rolling 计算。

第一版推荐策略内部计算，原因：

- 不需要改数据 CSV 字段。
- 不影响其他策略。
- 避免在 downloader 层混入策略特征。

如果后续要批量扫描性能更高，可以再把威科夫特征抽到 `analysis` 或 `strategy/features.py`。

### 8.4 周线特征实现

当前 `BacktestRunner` 只加载一个日线 feed。第一版有两种选择：

方案 A：在策略内部用最近 5 个交易日近似周线。

- 优点：改动最小。
- 缺点：不是真正自然周。

方案 B：改 `BacktestRunner` 支持 resample 周线 feed。

- 优点：更接近理论。
- 缺点：会影响引擎层，需要更谨慎验证。

建议第一版选择方案 A 或只在策略内部构造“周频代理”，待策略有效后再做方案 B。

日线代理周线可以这样做：

```text
weekly_proxy_close = Close
weekly_proxy_ema13 = EMA(Close, 13 * 5)
weekly_proxy_ema26 = EMA(Close, 26 * 5)
weekly_proxy_macd = MACD(Close, fast=12 * 5, slow=26 * 5, signal=9 * 5)
```

但文档层面要明确：这是工程近似，不是真正周线。若要严格贴合理论，后续必须实现真实周线 resample。

### 8.5 交易日志扩展

当前交易流水字段要求保持：

```text
date,symbol,direction,price,size,commission,pnl
```

为了不破坏兼容性，第一版可以不改 CSV 字段，而是在策略内部维护：

```python
self.current_setup_tag
```

后续如果要扩展交易流水，建议新增字段但保持旧字段存在：

```text
setup_tag,initial_stop,r_multiple,exit_reason
```

这会影响 `visual`、`analysis`、`TECHNICAL.md`，需要单独同步。

## 9. 参数建议

### 9.1 默认平衡型

| 参数 | 默认值 | 含义 |
|---|---:|---|
| `weekly_fast_ema` | 13 | 周线快 EMA |
| `weekly_slow_ema` | 26 | 周线慢 EMA |
| `daily_ema` | 22 | Elder 日线趋势 EMA |
| `efi_period` | 2 | Force Index EMA 平滑 |
| `atr_period` | 20 | ATR 周期 |
| `rvol_period` | 20 | 相对成交量均量周期 |
| `range_len` | 40 | 威科夫交易区间长度 |
| `max_range_pct` | 0.18 | 横盘区间最大宽度 |
| `spring_penetration` | 0.005 | Spring 跌破支撑幅度 |
| `spring_rvol_min` | 1.2 | Spring 最小 RVOL |
| `sos_rvol_min` | 1.5 | SOS 最小 RVOL |
| `sos_spread_atr_min` | 1.2 | SOS 最小价差 ATR 倍数 |
| `lps_rvol_max` | 1.0 | LPS 最大 RVOL |
| `trail_atr_mult` | 2.5 | ATR 跟踪止损倍数 |

### 9.2 保守型

```text
range_len = 50
max_range_pct = 0.15
sos_rvol_min = 1.8
sos_spread_atr_min = 1.4
trail_atr_mult = 3.0
```

特点：信号更少，更适合大盘股、指数 ETF、趋势更慢的品种。

### 9.3 激进型

```text
range_len = 30
max_range_pct = 0.22
sos_rvol_min = 1.2
sos_spread_atr_min = 1.0
trail_atr_mult = 2.0
```

特点：信号更多，但假突破也会明显增加。

## 10. 回测与验证方案

### 10.1 最小单标的验证

```bash
python main.py backtest run --strategy wyckoff_triple_screen --symbol 000001.SZ
python main.py backtest report --strategy wyckoff_triple_screen --symbol 000001.SZ
```

验证目标：

- 策略能正常加载。
- 不出现指标长度不足错误。
- 买卖点日期合理。
- 交易流水字段保持兼容。
- 单标的报告能正常生成。

### 10.2 小样本批量验证

```bash
python main.py backtest run --strategy wyckoff_triple_screen --symbols "000001.SZ,600519.SH,300750.SZ"
```

验证目标：

- 不同板块、不同价格、不同波动股票都能运行。
- 涨跌停、T+1、成交量上限逻辑不被破坏。

### 10.3 全市场验证

```bash
python main.py backtest run --strategy wyckoff_triple_screen
python main.py stats analyze --strategy wyckoff_triple_screen
python main.py dashboard
```

验证目标：

- 输出 `_summary_wyckoff_triple_screen.csv`。
- 策略画像报告可生成。
- 汇总面板能发现新策略。

### 10.4 买点扫描

```bash
python main.py backtest scan --strategy wyckoff_triple_screen --days 10
```

验证目标：

- 近期买点数量不过度爆炸。
- 候选股票 K 线形态与威科夫叙事大体一致。

## 11. 报告增强建议

第一版实现后，建议增强报告标注：

- 在 K 线上标记 Spring、Test、SOS、LPS。
- 买点 tooltip 显示 `setup_tag`。
- 画出 Support、Resistance、EMA22、ATR trailing stop。
- 交易表增加入场原因、出场原因、初始止损和 R 倍数。

策略画像中建议增加：

- 按 `setup_tag` 分组的收益率。
- 按 `setup_tag` 分组的胜率和盈亏比。
- 不同市场阶段下的分层表现。

这些增强会改变输出字段和报告结构，建议在策略 v1 稳定后再做。

## 12. 实施阶段规划

### 阶段 1：日线多头可跑版

范围：

- 新增 `strategy/wyckoff_triple_screen.py`
- 实现周线代理过滤、EFI 回调、Spring/Test/SOS/LPS、ATR 跟踪止损。
- 使用现有 `BaseStrategy` 下单逻辑。
- 不改 downloader、runner、report CSV 字段。

目标：

- 快速验证信号是否有研究价值。
- 保持对现有项目影响最小。

### 阶段 2：严格周线 feed

范围：

- `BacktestRunner` 支持日线 + 周线数据 feed。
- 策略读取已完成周线 bar。

目标：

- 消除周线代理近似。
- 更贴合 Triple Screen 理论。

### 阶段 3：交易日志与报告增强

范围：

- 交易流水增加 `setup_tag`、`exit_reason`、`initial_stop`。
- 报告标注威科夫事件与止损线。
- 策略画像支持按信号类型拆分。

目标：

- 让回测结果可解释、可复盘。

### 阶段 4：小时线第三屏

范围：

- 增加小时线或分钟线下载缓存。
- 增加多周期对齐。
- 实现 Donchian 突破、小时 RVOL、Session VWAP。

目标：

- 回到完整的“周线-日线-小时线”三重滤网。

### 阶段 5：组合风控与稳健性

范围：

- 单笔风险预算仓位。
- 组合同时暴露风险上限。
- 月度 6% 风险闸门。
- 参数网格、滚动样本外、稳定性热力图。

目标：

- 从单策略回测升级为更接近真实组合交易系统。

## 13. 主要风险

### 13.1 主观结构被过度机械化

威科夫原本依赖大量图表阅读。程序化版本只能近似，不能假设 Spring/SOS/LPS 标签完全等同于人工判断。

应对：

- 交易日志保留 `setup_tag`。
- 抽样复盘信号图。
- 参数不要过度优化。

### 13.2 参数过拟合

该策略参数较多，如果一开始做全市场网格，很容易找到“看起来很好”的过拟合参数。

应对：

- 第一版固定一组平衡参数。
- 先看信号质量和交易分布。
- 再做少量离散参数组合。

### 13.3 日线执行偏离原理论

原策略的小周期执行层是小时线。日线版会牺牲入场精度，可能扩大回撤或错过更优价格。

应对：

- 文档和报告中明确这是 v1 近似。
- 后续引入小时线第三屏。

### 13.4 A 股交易约束

A 股有 T+1、涨跌停、最小 100 股、停牌、流动性差异。威科夫理论本身不包含这些约束。

应对：

- 复用 `BaseStrategy` 的 A 股交易约束。
- 保持成交量上限配置。
- 对小盘股回测结果特别谨慎。

## 14. 最终建议

建议先实现“阶段 1：日线多头可跑版”。它能用当前项目最少改动验证策略核心：

```text
周线趋势过滤 + 日线 EFI 回调 + 日线威科夫事件 + ATR 风控
```

如果第一版在单标的报告和全市场策略画像中表现出稳定边际，再进入严格周线、多周期 feed、小时线触发和组合风险控制。这样实现节奏更稳，也能避免一开始把数据层、引擎层、策略层和报告层同时改复杂。
