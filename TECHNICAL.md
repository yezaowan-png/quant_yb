# A股量化回测系统 — 技术文档

## 技术栈

| 组件 | 库 | 用途 |
|------|-----|------|
| CLI 框架 | click | 命令行参数解析、交互式命令 REPL |
| 数据源 | tushare | A股日K线行情数据 API、股票列表 |
| 回测引擎 | backtrader | 事件驱动回测框架（Cerebro 架构） |
| 图表 | pyecharts | 基于 ECharts 的 Python 可视化库 |
| 数据处理 | pandas, numpy | DataFrame 操作、数值计算 |
| 配置 | pyyaml | YAML 配置文件解析 |

## 整体架构

```
┌──────────────────────────────────────────────┐
│                    main.py                    │
│              (Click CLI Group)                │
│    注册 data / backtest 命令组                │
│    无子命令时 → 进入交互式命令 REPL           │
└──────────────┬───────────────┬────────────────┘
               │               │
    ┌──────────▼──────┐  ┌─────▼───────────────┐
    │  cli/data_cli   │  │  cli/backtest_cli   │
    │  data download  │  │  backtest run       │
    │                  │  │  backtest scan      │
    │                  │  │  backtest report    │
    └────────┬────────┘  └─────┬───────────────┘
             │                 │
    ┌────────▼────────┐  ┌─────▼───────────────┐
    │ data/downloader │  │  engine/runner      │
    │ Tushare API 封装 │  │  Backtrader 封装    │
    │ 股票列表获取     │  │  绩效计算/交易导出   │
    │ 本地CSV缓存      │  │  买点扫描/汇总      │
    └────────┬────────┘  └─────┬───────┬───────┘
             │                 │       │
             │          ┌──────▼──┐    │
             │          │ strategy │    │
             │          │ base.py  │    │
             │          │ sma_cross│    │
             │          └──────────┘    │
             │                          │
             │                 ┌────────▼──────┐
             │                 │ visual/report │
             │                 │ K线 + 权益曲线 │
             │                 └───────────────┘
             │
    ┌────────▼────────┐
    │   data/cache/   │  ← CSV 缓存文件
    │   output/       │  ← 交易流水 & 买点信号 & HTML 报告
    └─────────────────┘
```

### 数据流

```
Tushare API (stock_basic)
    │ 获取全A股列表，剔除ST
    ▼
DataDownloader.download_batch()
    │ 调用 Tushare daily API，清洗数据
    ▼
data/cache/*.csv
    │
    ▼
BacktestRunner.run()
    │ 传入 DataFrame + 策略类
    ▼
output/trades/{symbol}_{strategy}.csv         ← 交易流水
output/trades/{symbol}_{strategy}_equity.csv  ← 每日权益
    │
    ▼
BacktestRunner.scan_recent_buy_signals()
    │ 扫描各股票的 buy_signal_dates
    ▼
output/signals/buy_signals_{strategy}_{date}.csv  ← 近5日买点汇总
    │
    ▼
generate_report()
    │ 读取 K线数据 + 交易流水 + 权益数据
    ▼
output/reports/{symbol}_{strategy}.html       ← 可视化报告
```

---

## 各模块实现思路

### `main.py` — 程序入口

**核心思路**：利用 Click 的 `group(invoke_without_command=True)` 特性，实现"无子命令时自动进入交互模式"。

```python
@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    if ctx.invoked_subcommand is None:
        from cli.shell import run_interactive
        run_interactive()
```

这样设计的好处：同一个入口，既能 `python main.py` 进入 REPL，也能 `python main.py data download ...` 直接执行命令。后者适合脚本化、批量处理场景。

---

### `cli/shell.py` — 交互式命令 REPL

**实现思路**：

1. **命令解析**：使用 `shlex.split()` 对用户输入进行安全分词（支持带引号的参数），然后用 `_parse_args()` 将 `--key value` 格式解析为字典。
2. **命令路由**：根据第一个词路由到对应的处理函数（`_cmd_download`、`_cmd_backtest`、`_cmd_scan`、`_cmd_report`），支持简写（如 `dl` → download、`bt` → backtest、`rp` → report）。
3. **异常保护**：每个命令用 `try/except` 包裹，出错时打印错误信息但不退出程序。
4. **自动发现**：`_list_cached_symbols()` 扫描 `data/cache/*.csv` 自动列出已下载的股票；`_list_strategies()` 扫描 `strategy/*.py` 自动列出可用策略。

**为什么从菜单改为命令 REPL？**
菜单模式需要一级一级输入，操作效率低，且无法组合参数。命令模式一次输入就能完成操作（如 `download --symbol 000001.SZ --start 20210101 --force`），更符合程序员使用习惯，也方便脚本化。

---

### `cli/data_cli.py` — 数据下载命令

**实现思路**：

- 未指定 `--symbol` 时，自动调用 `DataDownloader.get_stock_list()` 获取全A股列表（剔除ST股票）
- `--start` 和 `--end` 分别默认为 `20210101` 和当天日期
- 下载全部股票时会弹出确认提示，防止误操作

---

### `cli/backtest_cli.py` — 回测、扫描与报告命令

**实现思路**：

1. **`backtest run`**：
   - 股票选择有三种优先级：`--symbols`（逗号分隔多只） > `--symbol`（单只） > 所有已缓存股票
   - 单只股票回测时，直接输出绩效摘要到命令行
   - 多只股票回测时，调用 `run_batch()` 静默执行，最后导出汇总 CSV，同时自动扫描近5日买点
2. **`backtest scan`**：
   - 新增命令，对所有已缓存股票运行策略，检测近N日买点
   - 结果导出到 `output/signals/buy_signals_{策略名}_{日期}.csv`
3. **`backtest report`**：
   - 自动查找对应的交易流水文件和权益文件
   - 如果文件不存在给出明确提示（比如"请先执行 backtest run"）

---

### `data/downloader.py` — 数据下载器

**核心类**：`DataDownloader`

**设计要点**：

1. **股票列表获取**：`get_stock_list()` 方法调用 `pro.stock_basic(exchange='', list_status='L')` 获取全市场上市股票，自动过滤名称含 "ST" 的股票。返回包含 `ts_code` 和 `name` 的字典列表。

2. **默认日期范围**：`default_start()` 从 `config.yaml` 的 `defaults.start_date` 读取默认起始日期（当前为 `20210101`），`today_str()` 返回当天日期作为默认结束日期。

3. **增量更新**：`_save_cache()` 方法在保存时先读取已有缓存，与新数据 `pd.concat` 后再去重排序。这样多次下载同一只股票的不同时间段，数据会自动合并。

4. **缓存命中判断**：`download()` 方法先检查缓存的时间范围是否覆盖请求区间，如果完全覆盖则直接返回缓存数据，节省 API 调用。

5. **API 容错**：如果 Tushare API 调用失败，会回退到本地缓存数据（如果有的话），保证程序不会因网络问题崩溃。

6. **限流保护**：`download_batch()` 中每次 API 调用间隔 `sleep_seconds` 秒（配置文件中设置），避免触发 Tushare 的频率限制。

7. **数据清洗**：`_clean()` 方法把 Tushare 返回的字段名映射为标准英文名（如 `trade_date` → `date`），统一数据类型，删除空值行。

**为什么用 CSV 而不是数据库？**
对于个人量化回测场景，每只股票几千行数据，CSV 文件足够简单高效。不需要安装数据库，方便查看和手动编辑。

---

### `engine/runner.py` — 回测引擎

**核心类**：`BacktestRunner`、`EquityCurveAnalyzer`

**设计要点**：

1. **Backtrader 封装**：所有 backtrader 的 Cerebro 配置（数据喂入、资金设置、手续费、分析器）都在 `run()` 方法中完成，外部只需传入 DataFrame 和策略类即可。

2. **A 股手续费**：通过 `AShareCommission` 类（在 `strategy/base.py` 中定义）注入 Cerebro，实现佣金 + 卖出印花税 + 最低佣金。

3. **自定义分析器**：`EquityCurveAnalyzer` 继承 `bt.Analyzer`，在每个 bar 记录账户权益值。这是 backtrader 内置分析器不提供的功能。

4. **结果聚合**：`run()` 方法返回一个字典，包含四个部分：
   - `trade_records`：每笔交易的详细信息（日期、方向、价格、数量、盈亏）
   - `equity`：每日权益值 + 回撤序列
   - `stats`：绩效汇总（收益率、夏普比率、最大回撤、胜率等）
   - `buy_signal_dates`：所有出现买入信号的日期列表

5. **批量回测**：`run_batch()` 遍历多只股票，分别回测并导出各自的交易流水和权益数据，最后导出汇总 CSV。同时自动检测各股票近5日买点信号并导出汇总。

6. **买点扫描**：`scan_recent_buy_signals()` 对所有股票运行策略但不导出交易流水，只收集近N日出现买点的股票信息。

7. **信号过滤**：`_filter_recent_signals()` 根据数据的实际交易日历（而非自然日），取最后 N 个交易日作为判断窗口。

8. **动态加载策略**：`load_strategy_class()` 使用 `importlib.import_module()` 动态加载策略模块。命名约定：文件名 `sma_cross` → 类名 `SmaCrossStrategy`。

**回撤计算逻辑**：
```python
def compute_drawdowns(equity):
    arr = np.array(equity)
    peak = np.maximum.accumulate(arr)  # 历史最高点
    dd = (arr - peak) / peak           # 当前值与最高点的差距比例
    return dd * 100                     # 转为百分比
```

---

### `strategy/base.py` — 策略基类

**核心类**：`BaseStrategy`、`AShareCommission`

**设计思路**：模板方法模式。基类定义回测流程框架，子类只需覆写三个方法。

#### AShareCommission — A股手续费模型

```python
class AShareCommission(bt.CommInfoBase):
    def _getcommission(self, size, price, pseudoexec):
        value = abs(size) * price
        comm = value * 0.00025           # 佣金 0.025%
        comm = max(comm, 5.0)            # 最低 5 元
        if size < 0:                     # size < 0 表示卖出
            comm += value * 0.001        # 加收 0.1% 印花税
        return comm
```

关键点：
- `size > 0` 是买入，`size < 0` 是卖出
- A 股印花税只在卖出时收取
- 佣金有最低 5 元限制

#### BaseStrategy — 策略基类

**T+1 卖出限制**：A 股不能当天买当天卖。实现方式是记录买入日期，卖出前检查：

```python
def next(self):
    if self._next_buy_signal(data):
        self.buy_signal_dates.append(today)   # 记录买点日期
        if pos == 0:
            # A股最小交易单位 100 股（1手），按可用资金 95% 计算手数
            cash = self.broker.getcash()
            price = data.close[0]
            lots = int(cash * 0.95 / (price * 100))
            size = lots * 100
            if size > 0:
                self.buy(data=data, size=size)
                self._buy_dates[data] = today     # 记录买入日期

    elif pos > 0 and self._next_sell_signal(data):
        if today > buy_date:                      # 必须持有超过一天
            self.sell(data=data, size=pos)
```

**持仓管理**：
- 买入时按可用资金的 95% 计算手数（留 5% 缓冲应对滑点和手续费）
- 按 A 股规则取 100 股（1手）整数倍
- 卖出时清仓（size=pos），避免分批卖出复杂度

**买点追踪**：`buy_signal_dates` 列表记录所有出现买入信号的日期（无论是否实际成交），用于后续的买点扫描功能。这比只查交易记录更准确，因为当已有持仓时买入信号不会产生新的交易。

**交易记录**：通过覆写 `notify_order()` 和 `notify_trade()` 两个回调：
- `notify_order`：订单成交时记录买卖信息（日期、方向、价格、数量）
- `notify_trade`：一次完整买卖（开仓到平仓）完成后，把盈亏填充到对应的卖出记录上

#### 如何添加新策略？

1. 在 `strategy/` 下新建文件，比如 `macd_cross.py`
2. 继承 `BaseStrategy`，类名遵循 `XxxStrategy` 命名（如 `MacdCrossStrategy`）
3. 覆写三个方法：
   - `_init_indicators()` — 初始化技术指标（MACD、RSI 等）
   - `_next_buy_signal(data)` — 返回 True 时买入
   - `_next_sell_signal(data)` — 返回 True 时卖出
4. 定义 `params` 元组设置策略参数

示例框架：
```python
from strategy.base import BaseStrategy
import backtrader as bt

class MacdCrossStrategy(BaseStrategy):
    params = (
        ("fast", 12),
        ("slow", 26),
        ("signal", 9),
    )

    def _init_indicators(self):
        self.macd = {}
        self.macd_signal = {}
        for data in self.datas:
            macd = bt.indicators.MACD(
                data.close,
                period_me1=self.p.fast,
                period_me2=self.p.slow,
                period_signal=self.p.signal,
            )
            self.macd[data] = macd.macd
            self.macd_signal[data] = macd.signal

    def _next_buy_signal(self, data):
        return self.macd[data][0] > self.macd_signal[data][0]

    def _next_sell_signal(self, data):
        return self.macd[data][0] < self.macd_signal[data][0]
```

---

## 所有策略实现细节

### 1. 双均线交叉策略 (sma_cross) — `strategy/sma_cross.py`

#### 数学原理

**简单移动平均线 (SMA)**：

$$SMA_t(n) = \frac{1}{n}\sum_{i=0}^{n-1} P_{t-i}$$

其中 $P_t$ 是第 $t$ 天的收盘价，$n$ 是周期长度。

**金叉 (Golden Cross)**：短期均线从下方上穿长期均线，即：

$$SMA_t(n_{fast}) > SMA_t(n_{slow}) \quad \text{且} \quad SMA_{t-1}(n_{fast}) \leq SMA_{t-1}(n_{slow})$$

**死叉 (Death Cross)**：短期均线从上方下穿长期均线，即：

$$SMA_t(n_{fast}) < SMA_t(n_{slow}) \quad \text{且} \quad SMA_{t-1}(n_{fast}) \geq SMA_{t-1}(n_{slow})$$

#### 实现细节

**文件**：`strategy/sma_cross.py`
**类名**：`SmaCrossStrategy(BaseStrategy)`
**参数**：`fast_period=5`, `slow_period=20`

**技术指标初始化**（`_init_indicators`）：
```python
def _init_indicators(self):
    self.sma_fast = {}
    self.sma_slow = {}
    self.cross_up = {}
    self.cross_down = {}

    for data in self.datas:
        sma_f = bt.indicators.SMA(data.close, period=self.p.fast_period)
        sma_s = bt.indicators.SMA(data.close, period=self.p.slow_period)
        self.sma_fast[data] = sma_f
        self.sma_slow[data] = sma_s
        self.cross_up[data] = bt.indicators.CrossOver(sma_f, sma_s)
        self.cross_down[data] = bt.indicators.CrossDown(sma_f, sma_s)
```

- `CrossOver` 返回 1.0 表示当天发生上穿（金叉），0.0 表示未发生
- `CrossDown` 返回 1.0 表示当天发生下穿（死叉），0.0 表示未发生
- 使用字典存储指标是因为 backtrader 支持多数据源架构

**买入信号**（`_next_buy_signal`）：
```python
def _next_buy_signal(self, data) -> bool:
    return bool(self.cross_up.get(data, 0))
```

**卖出信号**（`_next_sell_signal`）：
```python
def _next_sell_signal(self, data) -> bool:
    return bool(self.cross_down.get(data, 0))
```

#### 策略优缺点

**优点**：
- 逻辑简单易懂，适合入门
- 在趋势明显的市场（牛市/熊市）中能捕捉到大段行情
- 参数少，不易过拟合

**缺点**：
- 震荡市中频繁产生假信号，导致连续亏损
- 信号滞后于价格变化（基于历史均值）
- 无法识别市场状态（趋势 vs 震荡）

#### 参数调优建议

| 快线 | 慢线 | 特点 | 适用场景 |
|------|------|------|----------|
| 5 | 20 | 偏短线，信号灵敏 | 短线交易、波动大的个股 |
| 10 | 30 | 偏中线，过滤噪音 | 中短线、兼顾趋势和灵活性 |
| 20 | 60 | 中长线，趋势明确 | 大趋势行情、大盘蓝筹 |

---

### 2. MACD金叉策略 (macd_cross) — `strategy/macd_cross.py`

**核心思想**：MACD 指标的金叉/死叉判断买卖。DIF（快线）上穿 DEA（慢线）为金叉买入，下穿为死叉卖出。

**参数**：`fast_period=12`, `slow_period=26`, `signal_period=9`

**数学公式**（EMA = 指数移动平均）：

$$DIF = EMA(close, 12) - EMA(close, 26)$$
$$DEA = EMA(DIF, 9)$$
$$MACD柱 = 2 \times (DIF - DEA)$$

**金叉条件**：`DIF_t > DEA_t` 且 `DIF_{t-1} <= DEA_{t-1}`
**死叉条件**：`DIF_t < DEA_t` 且 `DIF_{t-1} >= DEA_{t-1}`

---

### 3. KDJ超买超卖策略 (kdj) — `strategy/kdj.py`

**核心思想**：利用KDJ指标的超买超卖区间。K值低于oversold（20）且出现金叉时买入，高于overbought（80）且出现死叉时卖出。

**参数**：`k_period=9`, `smooth=3`, `oversold=20`, `overbought=80`

**KDJ 计算流程**：
1. $RSV(n) = \frac{close - low_n}{high_n - low_n} \times 100$
2. $K = EMA(RSV, smooth)$
3. $D = EMA(K, smooth)$
4. $J = 3K - 2D$

**引入自定义 Indicator**：因为 backtrader 不内置 KDJ，策略文件中定义了 `KDJIndicator(bt.Indicator)` 类，通过 `Highest`/`Lowest` 加 `EMA` 组合实现。

---

### 4. 布林带策略 (bollinger) — `strategy/bollinger.py`

**核心思想**：价格触及布林下轨后反弹买入，触及上轨后回落卖出。前一天收盘价低于下轨 → 今天可能反弹买入；前一天收盘价高于上轨 → 今天可能回落卖出。

**参数**：`period=20`, `devfactor=2.0`

**布林带公式**：
- 中轨 = $SMA(close, period)$
- 上轨 = 中轨 + $devfactor \times \text{标准差}$
- 下轨 = 中轨 - $devfactor \times \text{标准差}$

---

### 5. RSI超买超卖策略 (rsi) — `strategy/rsi.py`

**核心思想**：RSI < oversold（30）为超卖区买入，RSI > overbought（70）为超买区卖出。

**参数**：`period=14`, `oversold=30`, `overbought=70`

**RSI 公式**（Wilder's RSI）：

$$RSI = 100 - \frac{100}{1 + RS}$$

其中 $RS = \frac{\text{平均涨幅}}{\text{平均跌幅}}$（period 日平滑）

---

### 6. 单均线策略 (single_ma) — `strategy/single_ma.py`

**核心思想**：最简单的趋势策略——收盘价上穿均线买入，下穿卖出。

**参数**：`period=20`

**适用场景**：强趋势行情中简单有效；震荡市中假信号非常多。

---

### `visual/kline_chart.py` — K线 + 均线 + 指标图表组件

**核心函数**：

| 函数 | 产出 | 说明 |
|------|------|------|
| `create_kline_chart()` | K线 + MA叠加 Grid | 可选 ma5/ma10/ma20/ma60 均线叠加，含买卖点标记 |
| `create_volume_chart()` | 成交量柱状图 Grid | 红涨绿跌双 Bar 系列（stack 叠加），含 dataZoom |
| `create_macd_chart()` | MACD 指标图 | DIF/DEA 线 + 柱状图 |
| `create_kdj_chart()` | KDJ 指标图 | K/D/J 三线，0-100 定轴 |
| `create_rsi_chart()` | RSI 指标图 | RSI 线 + 30/70 超买超卖虚线参考线 |

**实现思路**：

1. K 线图使用 pyecharts 的 `Kline`，通过 `.overlap()` 叠加多条 Line（均线）
2. 成交量通过 Bar 双系列（stack 叠加）实现红涨绿跌配色
3. 各指标图（成交量/MACD/KDJ/RSI）均为独立 Grid 图表，高度 300px
4. 每个图表都包含 `DataZoomOpts(type_="inside")` 用于同步联动
5. 买卖点标记：买入红三角朝上，卖出绿三角朝下
6. 默认展示最近约 30% 的数据范围，避免数据太多时蜡烛太窄

---

### `visual/report.py` — 完整报告

**实现思路**：

1. `generate_report()` 是总入口，接收 K线数据、交易记录、权益数据
2. 从 OHLC 数据计算技术指标：`_calc_ma()`（4条均线）、`_calc_macd()`（DIF/DEA/柱）、`_calc_kdj()`（K/D/J）、`_calc_rsi()`（RSI）
3. 依次生成 5 个图表：K线图（含均线+买卖点）+ 4个指标图（成交量/MACD/KDJ/RSI）+ 权益曲线图
4. `_extract_chart_parts()` 用正则从 pyecharts 的 `render_embed()` 输出中提取 div、script 和 chart 变量名
5. `_build_page()` 拼装完整 HTML，包含：
   - **标签页 UI**（CSS 控制显示/隐藏）在 K线图下方切换成交量/MACD/KDJ/RSI
   - **ECharts 联动**：通过 `chart.group = 'quant_group'` + `echarts.connect('quant_group')` 让所有图表的 dataZoom 同步
   - 标签切换时对目标图表调用 `chart.resize()` 修复隐藏后的渲染问题

**报告包含的图表板块**：
1. K线图（含 MA5/MA10/MA20/MA60 + 买卖点标记）
2. 联动指标区（标签页切换，与 K线图缩放同步）：
   - 成交量（红涨绿跌柱状图）
   - MACD（DIF/DEA + 柱状图）
   - KDJ（K/D/J 三线，0-100）
   - RSI（RSI线 + 30/70 参考线）
3. 权益曲线 + 回撤

---

## 配置文件说明

```yaml
tushare:
  token: "你的token"          # Tushare API 密钥

data:
  cache_dir: "data/cache"     # 数据缓存目录

backtest:
  initial_cash: 100000.0      # 初始资金（元）
  commission: 0.00025         # 佣金费率 0.025%
  stamp_duty: 0.001           # 印花税 0.1%（仅卖出）
  min_commission: 5.0         # 最低佣金 5 元

rate_limit:
  sleep_seconds: 1.5          # API 调用间隔（防止限流）

output:
  trades_dir: "output/trades"     # 交易流水输出目录
  reports_dir: "output/reports"   # 报告输出目录
  signals_dir: "output/signals"   # 买点扫描汇总输出目录

defaults:
  start_date: "20210101"          # 默认起始日期

watchlist:                    # 默认关注的股票列表（供快速下载参考）
  - "000001.SZ"   # 平安银行
  - "000002.SZ"   # 万科 A
  - "600519.SH"   # 贵州茅台
```

## 关键设计决策

### 为什么用 backtrader？

backtrader 是 Python 生态中最成熟的回测框架之一，提供完整的事件驱动回测引擎、内置常用技术指标和分析器。相比于自己从零实现回测循环，使用 backtrader 可以避免处理除权除息、资金管理、手续费计算等边界情况。

### 为什么 CSV 而不是数据库？

个人量化场景下数据量不大（每只股票每天一条记录），CSV 的优势是：
- 零安装成本，不需要额外配置数据库
- 可以直接用 Excel 打开查看
- 方便版本管理（Git 可 diff CSV）

### 策略加载为什么用约定而非注册？

`load_strategy_class()` 通过命名约定自动查找策略类，省去了手动注册的步骤。用户只需按规范命名文件（`snake_case`）和类（`PascalCase + Strategy`），系统就能自动发现。

### 为什么使用命令 REPL 而非逐级菜单？

命令式交互允许用户一次输入完成完整操作（如 `download --symbol 000001.SZ --force`），而菜单模式需要多次输入。命令模式还支持参数组合、简写别名，更符合开发者使用习惯，且方便脚本化。
