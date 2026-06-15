# A股量化回测系统 — 使用说明

## 这个系统是干什么的？

简单说：**帮你用历史数据验证炒股策略是不是靠谱**。

比如你有一个想法："当 5 日均线上穿 20 日均线时买入，下穿时卖出"，这个策略到底能不能赚钱？在过去三年里表现如何？这个系统可以给你答案，并生成图表让你直观看到每一次买卖点。

它包含八个功能：
1. **下载数据** — 从网络获取 A 股的历史K线数据，存到本地（默认全市场非ST股票）
2. **策略回测** — 用历史数据模拟你的策略，算出收益率、胜率等指标（内置8种策略）
3. **策略对比** — 一次运行所有策略，横向对比找出最优
4. **扫描买点** — 检测最近N日内存在买入信号的股票，汇总导出
5. **生成报告** — 把回测结果画成 K线图（日K/周K/月K可切换，含均线、成交量、MACD、KDJ、RSI）+ 权益曲线，存为 HTML 文件
6. **数据统计** — 基于回测结果生成全市场策略画像和多策略对比分析报告
7. **决策记忆** — 记录买点信号，基于未来实际交易日窗口复盘 5/10/20 日收益和相对基准表现
8. **未来函数审计** — 静态扫描策略源码里的明显未来数据/数据泄露风险
9. **组合权重** — 从买点信号生成研究用候选组合和目标权重
10. **命令流水线** — 按顺序批量执行多条命令，支持分号分隔和脚本文件

## 第一次使用（环境准备）

### 1. 安装 Python

你的电脑需要安装 Python（3.8 或更高版本）。

去 Python 官网 [python.org](https://www.python.org) 下载安装包，安装时**勾选 "Add Python to PATH"** 这个选项。

安装完成后，打开"命令提示符"（按 `Win+R`，输入 `cmd`，回车），输入：

```
python --version
```

如果显示出 Python 的版本号，说明安装成功。

### 2. 安装依赖包

在命令提示符中，进入本项目所在的文件夹。比如项目在 `E:\quant_code\quant_yb`，就输入：

```
cd E:\quant_code\quant_yb
```

然后安装依赖：

```
pip install -r requirements.txt
```

等待安装完成（可能需要几分钟）。

### 3. 配置 Tushare Token

这个系统通过 Tushare 获取股票数据，需要一个 token（相当于账号密码）。

- 打开 [tushare.pro](https://tushare.pro) 注册账号
- 登录后，在"个人主页"找到"接口TOKEN"，复制那一串字符
- 打开项目里的 `config.yaml` 文件（用记事本即可）
- 把 `token:` 后面的内容替换成你的 token

### 数据源 Provider

`config.yaml` 中的 `data.provider` 控制行情来源：

```yaml
data:
  provider: "tushare"  # 可选: tushare / local_csv / akshare(占位)
  cache_dir: "data/cache"
```

默认 `tushare` 会保持原来的 Tushare 下载和缓存行为。`local_csv` 只读取本地缓存，适合离线验证和自动化测试。`akshare` 目前只是接口占位，尚未启用真实 AKShare 下载，避免在字段口径未验证前悄悄切换数据源。

## 怎么使用？

系统提供两种使用方式：**命令模式**（交互式）和**直接命令**（脚本化）。

### 方式一：命令模式（推荐）

在命令提示符中输入：

```
python main.py
```

会看到提示符 `quant>`，直接输入命令即可：

```
quant> download --start 20210101 --end 20231231
quant> backtest --strategy sma_cross --symbol 000001.SZ
quant> scan --strategy sma_cross
quant> decision record --strategy sma_cross
quant> decision evaluate --strategy sma_cross
quant> decision summary --strategy sma_cross
quant> audit lookahead --strategy sma_cross
quant> portfolio build --signals output/signals/buy_signals_sma_cross_YYYYMMDD.csv
quant> compare --symbol 000001.SZ
quant> report --symbol 000001.SZ --strategy sma_cross
quant> run "download; backtest --strategy rsi; report; stats compare"
quant> help
quant> exit
```

输入 `help` 查看所有可用命令及参数说明。

`run` 命令支持按顺序批量执行：用分号 `;` 或换行分隔多条命令，也可以 `--file` 从脚本文件读取。每行可加 `!` 前缀忽略该条失败继续执行。

```
quant> run "download; backtest --strategy rsi; backtest --strategy kdj; report; stats compare"
quant> run --file pipeline.txt
```

#### 工作流程示例

1. `download` → 下载全部A股（剔除ST）日K线数据，默认从20210101至今
2. `backtest --strategy sma_cross --symbol 000001.SZ` → 对平安银行回测双均线策略，查看绩效
3. `scan --strategy sma_cross` → 扫描全部已缓存股票，找出近5日有买点的股票
4. `report --symbol 000001.SZ --strategy sma_cross` → 生成 HTML 可视化报告

生成的报告在 `output/reports/` 文件夹里，用浏览器打开即可查看。

报告包含以下内容：
- **周期标签栏**：日K | 周K | 月K 三个周期可点击切换，每个周期独立展示K线图和指标
- **K线图**：带 5/10/20/60 日均线叠加和买卖点标记（红三角买入，绿三角卖出）
- **联动指标区**（每个周期内标签页切换，缩放与K线同步）：
  - 成交量 — 红涨绿跌柱状图
  - MACD — DIF / DEA 线 + 柱状图
  - KDJ — K / D / J 三线（0-100 区间）
  - RSI — RSI 线 + 30/70 超买超卖参考线
- **权益/风险面板**：账户资金变化、Underwater 回撤、60 日 rolling Sharpe、月度收益热力图和交易 PnL 分布

> 提示：在 K 线图上缩放/平移时，同周期指标图和权益曲线会同步联动。点击顶部标签可切换日K/周K/月K。

命令示例：

```
quant> compare --symbol 000001.SZ
```

这会对指定股票依次运行所有内置策略，输出横向对比表格，帮你快速找到最适合这只股票的策略。

### 策略对比

### 方式二：直接命令（适合脚本和自动化）

```bash
# 下载全部A股数据（默认20210101至今）
python main.py data download

# 下载某一只股票
python main.py data download --symbol 000001.SZ --start 20210101 --end 20231231 --force

# 回测一只股票
python main.py backtest run --strategy sma_cross --symbol 000001.SZ

# 回测全部已缓存股票（同时输出近5日买点）
python main.py backtest run --strategy sma_cross

# 扫描近5日买点
python main.py backtest scan --strategy sma_cross --days 5

# 把最近一次买点扫描结果写入决策记忆
python main.py decision record --strategy sma_cross

# 用本地缓存复盘信号未来 5/10/20 个实际交易日表现
python main.py decision evaluate --strategy sma_cross --horizons 5,10,20

# 查看决策记忆摘要
python main.py decision summary --strategy sma_cross

# 静态审计某个策略是否存在明显未来函数风险
python main.py audit lookahead --strategy sma_cross

# 从买点信号生成研究用目标权重
python main.py portfolio build --signals output/signals/buy_signals_sma_cross_YYYYMMDD.csv --method equal

# 生成报告
python main.py backtest report --symbol 000001.SZ

# 批量流水线：一次性完成 下载→回测→报告→统计
python main.py run "download; backtest --strategy rsi; backtest --strategy kdj; report; stats compare"
```

### 指数每日概览

第一阶段指数概览覆盖主要宽基和风格指数，指数数据单独缓存到 `data/cache/index/`，不会混入股票回测流水。

```bash
# 下载上证指数日线
python main.py index download --symbol 000001.SH --start 20210101

# 基于本地缓存生成指数图表报告
python main.py index report --symbol 000001.SH

# 每日使用：先更新数据，再生成概览报告
python main.py index overview --symbol 000001.SH

# 第一阶段指数全部更新并生成报告
python main.py index overview --all

# 生成本地汇总导航面板
python main.py dashboard

# 运行一个可归档实验配置
python main.py experiment run experiments/sma_cross_baseline.yaml
```

默认报告输出到 `output/reports/index/{指数代码}_overview.html`，包含日K/周K/月K、MA5/10/20/60、成交量、MACD、KDJ、RSI，以及最新收盘、当日涨跌幅、近5日/20日收益、年初至今、20日最大回撤和波动率等概览卡片。

汇总面板默认输出到 `output/reports/dashboard.html`。阶段 4 之后它升级为本地研究总控面板，会自动扫描指数概览、策略画像、策略横向对比、批量回测汇总 CSV、决策记忆、实验归档和最近生成的单标的报告，方便从一个入口判断“市场环境、数据是否齐、策略表现、信号复盘、哪些报告可以继续打开”。

面板主要模块：

- **市场温度**：读取 `data/cache/index/{指数代码}.csv` 的最新涨跌幅，展示指数平均涨跌、上涨/下跌数量和最强/最弱指数。
- **数据健康**：统计本地股票缓存数量、最新缓存日期、指数缓存覆盖度、指数报告数量和过期缓存数量。
- **策略排行榜**：读取 `output/trades/_summary_{strategy}.csv`，复用统计分析口径按全市场平均收益排序。
- **策略汇总**：展示每个策略是否已有批量汇总、策略画像报告，以及股票数、平均收益、交易股平均收益、正收益占比、夏普和回撤。
- **信号复盘**：读取 `output/decisions/decision_memory.csv`，展示信号总数、已评估/待评估数量、最新信号日期、5 日未来收益和 5 日超额收益。
- **最近实验/最近报告**：扫描 `output/experiments/` 和 `output/reports/*.html`，提供最近产物入口。
- **目标权重**：读取最新 `output/portfolio/target_weights_*.csv`，展示组合标的数、总仓位、最大单股权重和前几大权重。
- **风险提示**：主动标注幸存者偏差、本地缓存缺失/过期、基准缺失、信号待评估和未来函数审计未接入等限制。

这个面板只聚合已有本地产物，不会重新下载数据、不会运行回测，也不会改变任何 CSV 字段口径。

### 实验配置化

`experiment run` 用 YAML 固化一次研究任务，把输入配置、回测汇总、交易流水、权益曲线、单标的报告和 manifest 归档到独立目录，方便复现和比较。它复用现有 Backtrader 回测逻辑，但输出写入 `output/experiments/{experiment_id}/`，不会覆盖全局 `output/trades/` 下的批量汇总。

示例：

```bash
python main.py experiment run experiments/sma_cross_baseline.yaml
```

示例配置：

```yaml
id: sma_cross_baseline
strategy: sma_cross
symbols:
  - 000001.SZ
start: "20210101"
end: "20231231"
benchmark: 000300.SH
params:
  fast: 5
  slow: 20
cost:
  commission: 0.00025
  stamp_duty: 0.001
  slippage_perc: 0.001
```

输出结构：

```text
output/experiments/{experiment_id}/
├── config.yaml      # 归档后的实验 YAML
├── manifest.json    # 输入、输出、状态、耗时、错误和警告
├── summary.csv      # 本次实验标的级绩效汇总
├── trades/          # 实验内交易流水和权益曲线
└── reports/         # 实验内单标的 HTML 报告
```

为避免误跑全市场，实验配置必须显式提供 `symbols` 或 `symbol`。`cost` 只允许覆盖现有回测成本字段；拼错字段会直接报错。

### 决策记忆和信号复盘

`decision` 命令用于把策略产生的买点信号记录下来，并在未来数据足够后做事后复盘。它不是新的交易策略，也不会把未来收益反向用于买卖信号；它只是回答一个复盘问题：**这个信号出现之后，未来 5/10/20 个实际交易日表现如何？是否跑赢基准？**

常用流程：

```bash
# 第一步：先扫描买点，会生成 output/signals/buy_signals_{strategy}_{日期}.csv
python main.py backtest scan --strategy sma_cross --days 5

# 第二步：把买点扫描 CSV 写入 decision memory
python main.py decision record --strategy sma_cross

# 第三步：等未来数据足够后，基于本地缓存评估未来收益
python main.py decision evaluate --strategy sma_cross --horizons 5,10,20

# 第四步：查看摘要，或重新生成 dashboard
python main.py decision summary --strategy sma_cross
python main.py dashboard
```

输出文件：

```text
output/decisions/decision_memory.csv
```

核心字段说明：

| 字段 | 含义 |
|------|------|
| `signal_id` | 根据信号标的、策略、日期、类型和参数生成的稳定 ID，用于去重 |
| `symbol` / `strategy` | 信号对应股票和策略 |
| `signal_date` | 买点信号日期，按实际交易日记录 |
| `price` | 信号日期附近的收盘价；如果没有本地缓存则可为空 |
| `params_json` | 策略参数快照，用于区分不同参数组合 |
| `future_5d_return_pct` | 信号后第 5 个实际交易日的收益率 |
| `benchmark_5d_return_pct` | 同一窗口内基准指数收益率，默认来自 `benchmark.symbol` |
| `excess_5d_return_pct` | 信号收益减去基准收益 |
| `evaluation_status` | `pending`、`partial`、`evaluated`、`pending_future_data` 或 `missing_symbol_data` |

复盘口径注意：

- `5/10/20d` 指的是**实际交易日数量**，不是自然日。
- 未来收益只用于事后评估，不能参与策略信号。
- 若未来数据不足，对应字段保持空值，状态显示为待评估或部分评估。
- 基准数据来自本地缓存；如果基准缓存不存在，仍会计算个股未来收益，但超额收益为空。

第一阶段重点指数包括：

| 指数 | 代码 | 观察重点 |
|------|------|----------|
| 上证指数 | `000001.SH` | 大盘综合温度 |
| 深证成指 | `399001.SZ` | 深市与成长制造 |
| 创业板指 | `399006.SZ` | 成长股风险偏好 |
| 科创50 | `000688.SH` | 硬科技与科创板龙头 |
| 沪深300 | `000300.SH` | 大盘蓝筹基准 |
| 中证500 | `000905.SH` | 中盘股表现 |
| 中证1000 | `000852.SH` | 小盘股表现 |
| 中证全指 | `000985.SH` | 全市场整体表现 |

## 可用策略一览

系统内置 8 种策略，可通过 `compare --symbol <代码>` 一键对比：

| 策略 | 命令名 | 核心参数 | 适合场景 |
|------|--------|----------|----------|
| 双均线交叉 | `sma_cross` | `--fast 5 --slow 20` | 趋势跟踪 |
| MACD金叉 | `macd_cross` | `--fast 12 --slow 26` | 趋势跟踪 |
| KDJ超买超卖 | `kdj` | `--oversold 20 --overbought 80` | 震荡市 |
| 布林带 | `bollinger` | `--period 20 --devfactor 2` | 均值回归 |
| RSI超买超卖 | `rsi` | `--period 14 --oversold 30 --overbought 70` | 震荡市 |
| 单均线 | `single_ma` | `--period 20` | 简单趋势 |
| 放量平台突破 | `volume_platform_breakout` | `--lookback 30 --volume-multiplier 1.5` | 平台整理后的趋势突破 |
| 多周期放量趋势 | `multi_timeframe_volume_trend` | `--lookback 20 --vol-mult 1.5 --weekly 20` | 周线趋势过滤 + 日线放量突破 |

## 策略详解

### 双均线交叉策略 (sma_cross)

**核心思想**：利用短期和长期两条移动平均线的交叉关系判断买卖时机。

**为什么均线交叉能赚钱？**

移动平均线（SMA，Simple Moving Average）是对过去N天收盘价的简单平均。它能平滑价格波动，反映趋势方向：
- **短期均线**（如5日均线）反应灵敏，紧跟价格变化
- **长期均线**（如20日均线）反应滞后，反映中期趋势

当短期均线**上穿**长期均线（金叉）时，说明短期价格上涨动能超过长期趋势，趋势可能由跌转涨→**买入信号**。

当短期均线**下穿**长期均线（死叉）时，说明短期价格下跌动能超过长期趋势，趋势可能由涨转跌→**卖出信号**。

**策略实现细节**：

1. **指标计算**：
   - `SMA(close, 5)` — 5日简单移动平均线（快线）
   - `SMA(close, 20)` — 20日简单移动平均线（慢线）
   - `CrossOver(fast, slow)` — 检测快线上穿慢线的瞬间（当天快线 > 慢线 且 昨天快线 <= 慢线）
   - `CrossDown(fast, slow)` — 检测快线下穿慢线的瞬间

2. **买卖规则**：
   - 买入条件：出现金叉信号 + 当前无持仓
   - 卖出条件：出现死叉信号 + 当前有持仓 + 买入日期不是今天（T+1限制）

3. **A股交易规则**：
   - **T+1 卖出限制**：当天买入的股票不能当天卖出，必须至少持有到下一个交易日
   - **佣金**：成交金额的 0.025%，最低 5 元每笔
   - **印花税**：卖出时收取成交金额的 0.1%（买入不收）
   - **初始资金**：默认 100,000 元

4. **参数说明**：
   - `fast_period`（快线周期，默认5）：值越小，信号越灵敏，但假信号也越多
   - `slow_period`（慢线周期，默认20）：值越大，趋势判断越稳定，但反应越滞后

**策略适用范围**：
- 适合趋势明显的市场（牛市中表现较好）
- 不适合震荡市（频繁的假金叉/死叉会导致反复亏损）
- 大盘蓝筹股通常比小盘题材股更适用（走势更平滑、趋势更稳定）

**如何优化参数？**

可以尝试不同的快慢线组合来找到最佳参数：
```
quant> backtest --strategy sma_cross --symbol 000001.SZ --fast 10 --slow 30
```

常见的参数组合：
- `5/20`：偏短线，信号较多
- `10/30`：偏中线，减少假信号
- `20/60`：中长线，适合大趋势

### 放量平台突破策略 (volume_platform_breakout)

**核心思想**：先识别一段窄幅横盘平台，再等待价格放量向上突破，同时用 MA20 过滤短中期趋势方向。它想捕捉的是这类走势：股价长时间在一个相对稳定的区间里反复震荡，说明筹码和压力位逐渐清晰；当价格带着明显放大的成交量突破平台上沿时，可能意味着资金开始主动进攻。

这个策略不是每天都会给很多信号。它属于偏严格的“突破确认”型选股逻辑，宁愿少选，也要尽量避开普通震荡里的假突破。

**怎么运行**：

```bash
python main.py backtest run --strategy volume_platform_breakout --symbol 000001.SZ
```

扫描最近买点：

```bash
python main.py backtest scan --strategy volume_platform_breakout --days 10
```

放宽条件，让候选股票多一些：

```bash
python main.py backtest scan --strategy volume_platform_breakout --days 10 --max-range-pct 0.18 --volume-multiplier 1.2 --breakout-pct 0.005
```

**买入条件**：
- 使用今天之前 `lookback` 个交易日识别平台，默认 60 日。注意：平台计算不使用今天的数据，避免“用突破当天的高点反过来定义平台”。
- 平台上沿 `upper` 是过去 `lookback` 日最高价的最大值，平台下沿 `lower` 是过去 `lookback` 日最低价的最小值。
- 平台振幅 `(upper - lower) / lower` 不超过 `max_range_pct`，默认 20%。这个条件用来确认横盘足够紧凑。
- 上沿触碰次数不少于 `min_upper_touches`，默认 2 次；下沿触碰次数不少于 `min_lower_touches`，默认 2 次。这个条件用来确认平台边界真的被市场反复测试过。
- 今日收盘价突破平台上沿 `breakout_pct`，默认 2%。例如平台上沿是 10 元，默认要求收盘价大于 10.20 元。
- 今日成交量大于过去 `volume_period` 日均量的 `volume_multiplier` 倍，默认 30 日均量的 1.3 倍。这个条件用来确认突破时有资金参与。
- 趋势过滤：`close > MA20`，且 MA20 最近 `ma_slope_days` 日向上。这个条件用来避免在短中期均线仍然走弱时追突破。

**卖出条件**：
- 收盘价跌破 MA20
- 或收盘价跌破买入时平台上沿的 95%，也就是 `entry_upper * (1 - platform_sell_tolerance)`，默认容忍 5%
- 或收盘价相对实际买入成交价亏损超过 `stop_loss_pct`，默认 10%

**参数说明**：

| 参数 | 默认值 | 含义 | 调大/调小的影响 |
|------|--------|------|----------------|
| `lookback` | 60 | 识别平台使用的历史交易日数 | 调大：平台更稳定但信号更少；调小：更灵敏但假信号更多 |
| `max_range_pct` | 0.20 | 平台最大振幅 | 调大：允许更宽的平台，信号更多；调小：平台更紧凑，信号更少 |
| `touch_tolerance` | 0.06 | 触碰上下沿的容忍度 | 调大：更容易算作触碰；调小：平台边界要求更精确 |
| `min_upper_touches` | 2 | 上沿最少触碰次数 | 调大：压力位更明确，信号更少 |
| `min_lower_touches` | 2 | 下沿最少触碰次数 | 调大：支撑位更明确，信号更少 |
| `breakout_pct` | 0.02 | 突破上沿的确认幅度 | 调大：突破更强才买；调小：更早进场 |
| `volume_period` | 30 | 均量周期 | 调大：成交量基准更平滑；调小：更敏感 |
| `volume_multiplier` | 1.3 | 放量倍数 | 调大：要求更明显放量，信号更少；调小：信号更多 |
| `ma_slope_days` | 1 | MA20 向上确认天数 | 调大：趋势过滤更严格 |
| `platform_sell_tolerance` | 0.05 | 跌破平台上沿卖出的容忍度 | 调大：给回踩更多空间；调小：更快确认突破失败 |
| `stop_loss_pct` | 0.10 | 相对实际买入成交价的止损比例 | 调大：止损更宽；调小：止损更快 |

**调参建议**：

- 如果买点太少：优先把 `max_range_pct` 调到 `0.15~0.20`，把 `volume_multiplier` 调到 `1.2~1.3`，把 `breakout_pct` 调到 `0.005`。
- 如果假突破太多：把 `volume_multiplier` 调高到 `1.8~2.0`，或把 `min_upper_touches` 提高到 3。
- 如果买得太晚：降低 `breakout_pct`。
- 如果突破后正常回踩却太快卖出：提高 `platform_sell_tolerance`，比如从 `0.05` 调到 `0.08`。
- 如果亏损扩大太多：降低 `stop_loss_pct`，比如从 `0.10` 调到 `0.06~0.08`。

**适用场景**：

- 横盘整理后突破的个股
- 中期趋势已经转强的股票
- 有明显压力位、突破当天成交量明显放大的形态

**不适用场景**：

- 长期阴跌或均线空头排列的股票
- 无量突破、尾盘拉升但成交量没有确认的股票
- 震荡很宽的平台，因为平台上沿/下沿不稳定，突破容易失真

### 多周期放量趋势策略 (multi_timeframe_volume_trend)

**核心思想**：先用周线判断大级别趋势，再用日线放量突破寻找入场点。它适合试验“周线定方向、日线找买点”的多周期框架。

运行示例：

```bash
python main.py backtest run --strategy multi_timeframe_volume_trend --symbol 000001.SZ
```

**关键边界**：

- 周线由日线数据通过 Backtrader `resampledata()` 生成，策略读取已经形成的周线 bar。
- 下单仍然只发生在日线 data0 上，周线 data1 只做趋势过滤。
- 日线突破基准使用今天之前的历史高点窗口，不把当天高点反向纳入突破基准。
- 这是多周期试点策略，可继续扩展到三重筛选、量价趋势或行业过滤，但不会改变现有单周期策略的运行方式。

## 回测结果怎么看？

回测完成后，系统会输出类似这样的摘要：

```
--- 绩效摘要 [000001.SZ] ---
  总收益率:    15.23%
  夏普比率:    0.85
  最大回撤:    -12.50%
  交易次数:    8
  胜率:        50.00%
  最终资金:    115,230.00
```

各指标的含义：

| 指标 | 含义 |
|------|------|
| 总收益率 | 从开始到结束，资金涨了多少百分比 |
| 夏普比率 | 衡量"每承担一份风险获得多少回报"，越高越好，一般 > 1 算不错 |
| 最大回撤 | 资金从最高点跌到最低点的最大幅度，越小越好 |
| 交易次数 | 一共做了多少次买卖 |
| 胜率 | 盈利交易占总交易次数的比例 |
| 最终资金 | 回测结束时的账户总金额 |

## 买点扫描

`scan` 命令会对所有已缓存的股票运行策略，检测最近N个交易日内哪些股票出现了买入信号，并汇总导出到 CSV 文件。

```
quant> scan --strategy sma_cross --days 5
```

输出文件保存在 `output/signals/buy_signals_{策略名}_{日期}.csv`，包含股票代码、买点日期、最新价格等信息。这相当于一个简易的"选股器"，帮你快速筛选出当前值得关注的股票。

如果 `config.yaml` 中 `decision_memory.enabled` 为 `true`，扫描或批量回测导出买点时，还会自动把这些买点写入 `output/decisions/decision_memory.csv`。后续可以用 `decision evaluate` 对这些信号做未来表现复盘。

## 数据统计

`stats` 命令基于已有的回测结果，生成全市场维度的可视化统计分析 HTML 报告。包含两个子命令：

### 单策略画像

```
quant> stats analyze --strategy rsi
```

对某个策略在全部股票上的表现做深度分析，HTML 报告包含：
- **统计卡片**：股票数、平均/中位数收益率、正收益比例、夏普、Sortino、Calmar、Profit Factor、回撤持续天数、胜率
- **收益率分布直方图**：所有股票的收益率分布形态，标注均值和中位数线
- **风险/收益散点图**：每只股票对应一个点（X=最大回撤，Y=收益率，颜色=胜率）
- **风险画像图**：Profit Factor 分布、最大回撤持续时间分布、平均交易 PnL 分布
- **Monte Carlo 模拟图**：基于全市场单标的收益分布做路径抽样，观察策略结果对样本路径的敏感度
- **TOP 20 / BOTTOM 20 榜单**：收益最高和最低的 20 只股票
- **夏普比率分布、交易频率分布**

#### 策略画像卡片怎么看？

策略画像的每一张卡片，都是先对每只股票单独回测，得到一行汇总数据，再对所有股票做统计。假设某个策略对 5000 只股票回测完成，就会先生成 `output/trades/_summary_{策略名}.csv`，然后统计报告从这个 CSV 里计算下面这些指标。

| 卡片 | 含义 | 计算方式 | 怎么理解 |
|------|------|----------|----------|
| 分析股票数 | 本次参与统计的股票数量 | `_summary_{策略名}.csv` 的总行数 | 数值越大，说明覆盖的样本越多。它包含有交易和无交易的股票。 |
| 有交易股票 | 至少发生过 1 次完整交易的股票数量和占比 | `total_trades > 0` 的股票数；占比 = 有交易股票数 / 分析股票数 × 100% | 如果这个比例很低，说明策略很严格，很多股票从未触发买卖。 |
| 平均收益率 | 所有股票回测收益率的平均值 | 对所有股票的 `total_return_pct` 求平均；单股 `total_return_pct = (final_value - initial_cash) / initial_cash × 100%` | 包含无交易股票。无交易股票收益为 0，会把平均值拉向 0。 |
| 平均年化收益 | 所有股票年化收益的平均值 | 对所有股票的 `annual_return_pct` 求平均；单股年化收益约为 `(final_value / initial_cash) ^ (252 / trading_days) - 1` | 用于把不同回测天数折算到年度口径。包含无交易股票。 |
| 交易股平均收益 | 只统计有交易股票的平均收益率 | 只筛选 `total_trades > 0` 的股票，再对 `total_return_pct` 求平均 | 更能反映策略真正出手后的表现。适合和“平均收益率”一起看。 |
| 交易股平均年化 | 只统计有交易股票的平均年化收益 | 只筛选 `total_trades > 0` 的股票，再对 `annual_return_pct` 求平均 | 排除了无交易股票的 0 值影响。 |
| 平均年化波动 | 所有股票账户权益日收益波动的平均值 | 单股年化波动 = 每日权益收益率标准差 × √252 × 100%；再对所有股票求平均 | 衡量收益曲线波动程度。越低越平稳，但如果很多股票无交易，也会被 0 波动拉低。 |
| 平均超额收益 | 策略收益相对基准指数的平均超额 | 单股超额收益 = 策略总收益率 - 基准同期收益率；再对所有股票求平均 | 需要本地有基准指数缓存，例如 `000300.SH.csv`。没有基准数据时会显示 0。 |
| 平均信息比率 | 策略相对基准的风险调整后超额表现 | 单股信息比率 = 主动收益日均值 / 主动收益标准差 × √252；再对所有股票求平均 | 衡量超额收益是否稳定。大于 0 表示平均跑赢基准，越高越好。 |
| 中位数收益率 | 所有股票收益率的中间值 | 对所有股票 `total_return_pct` 取中位数 | 比平均值更不容易被少数大牛股拉高。若中位数低于平均值，通常说明少数大赢家抬高了均值。 |
| 正收益比例 | 收益率大于 0 的股票占比 | `total_return_pct > 0` 的股票数 / 分析股票数 × 100% | 衡量策略在全市场的普适性。比例越高，说明赚钱股票覆盖面越广。 |
| 平均夏普 | 所有股票夏普比率的平均值 | 单股夏普来自 Backtrader `SharpeRatio` 分析器；再对所有股票求平均 | 衡量承担波动后得到的收益。一般越高越好，低于 0 表示风险调整后表现较差。 |
| 平均 Sortino | 所有股票 Sortino 的平均值 | 单股日收益均值 / 下行波动，再年化；旧 summary 没有该字段时显示 0 | 只惩罚下跌波动，更关注“坏波动”。 |
| 平均 Calmar | 所有股票 Calmar 的平均值 | 单股年化收益 / 最大回撤；再对所有股票求平均 | 衡量收益和最大回撤之间是否划算。 |
| 平均 Profit Factor | 所有股票 Profit Factor 的平均值 | 平仓盈利总额 / 平仓亏损绝对值；无亏损样本留空 | 大于 1 表示盈利交易总额高于亏损交易总额。 |
| 平均最大回撤 | 所有股票最大回撤的平均值 | 单股最大回撤来自 Backtrader `DrawDown` 分析器；再对所有股票求平均 | 衡量最糟糕资金回撤幅度。越低越好。 |
| 回撤持续天数 | 最大回撤持续时间的平均值 | `max_drawdown_days` 求平均 | 反映资金从高点回落后的修复时间。 |
| 最长连赢/连亏 | 全市场样本中的最长连续盈利/亏损次数 | 基于每只股票的平仓 PnL 序列统计 | 帮助判断交易质量和连续亏损压力。 |
| 平均胜率 | 所有股票交易胜率的平均值 | 单股胜率 = 盈利交易数 / 总交易数 × 100%；再对所有股票求平均 | 胜率不等于收益率。低胜率策略也可能靠少数大盈利赚钱，高胜率策略也可能小赚大亏。 |
| 平均交易次数 | 每只股票平均发生多少次完整交易 | 对所有股票的 `total_trades` 求平均 | 衡量策略活跃度。太低说明信号少；太高可能代表过度交易。 |

看策略画像时，建议同时看三组指标：

- **覆盖度**：分析股票数、有交易股票、平均交易次数。
- **赚钱能力**：平均收益率、交易股平均收益、中位数收益率、正收益比例。
- **风险质量**：平均年化波动、平均最大回撤、平均夏普、Sortino、Calmar、Profit Factor、平均信息比率。

一个常见误解是：平均收益率接近 0，不一定代表所有股票都没收益。它可能是因为大量股票无交易收益为 0，也可能是少数大赢家和大量小亏损互相抵消。所以要结合“有交易股票”“交易股平均收益”“中位数收益率”和“正收益比例”一起看。

### 多策略横向对比

```
quant> stats compare
```

对所有有回测数据的策略做横向对比，HTML 报告包含：
- **策略摘要卡片**：每个策略的核心指标一览
- **多维雷达图**：6 个维度（收益率、夏普、胜率、正向率、回撤控制、交易活跃度）
- **收益率箱线图**：各策略收益分布并排对比
- **核心指标柱状图**：收益率、夏普、胜率、正向率
- **策略相关性分析**：基于同股票跨策略收益率的 Spearman 秩相关
- **风险收益散点图**：多策略叠加在同一坐标中

报告保存在 `output/statistics/` 目录下，用浏览器打开即可查看。

## 文件目录说明

```
quant_yb/
├── main.py              ← 程序入口
├── config.yaml          ← 配置文件（token、资金、手续费等）
├── requirements.txt     ← 依赖包列表
├── cli/                 ← 菜单和命令行相关代码
├── data/                ← 数据下载相关代码
│   └── cache/           ← 下载的股票数据缓存（CSV 文件）
├── engine/              ← 回测引擎相关代码
├── strategy/            ← 策略代码（你的买卖逻辑放在这里）
├── decision/            ← 决策记忆与信号复盘
├── experiment/          ← 实验配置化运行与归档
├── experiments/         ← 可复现实验 YAML 配置
├── analysis/            ← 数据统计分析相关代码
├── visual/              ← 图表生成相关代码
├── output/
│   ├── trades/          ← 回测交易记录输出
│   ├── reports/         ← HTML 报告输出
│   ├── signals/         ← 买点扫描汇总输出
│   ├── decisions/       ← 决策记忆与复盘输出
│   ├── experiments/     ← 实验归档和阶段性研究记录
│   └── statistics/      ← 统计分析 HTML 报告输出
└── CLAUDE.md            ← 给 AI 助手的说明文档
```

## 输出文件说明

回测和扫描会产生以下 CSV 文件，均位于 `output/` 目录下。

### 1. 交易流水 — `trades/{symbol}_{strategy}.csv`

每笔买卖的详细记录。

| 列名 | 含义 |
|------|------|
| `date` | 交易日期 |
| `symbol` | 股票代码 |
| `direction` | 买卖方向：`BUY`（买入）或 `SELL`（卖出） |
| `price` | 成交均价（含滑点） |
| `size` | 成交股数，正数为买入、负数为卖出 |
| `commission` | 手续费（佣金 + 卖出印花税） |
| `pnl` | 盈亏金额（仅卖出时有效，买入行为 0） |

每两行构成一次完整交易（买入 → 卖出），卖出行的 `pnl` 即本次交易的盈亏。

### 2. 权益曲线 — `trades/{symbol}_{strategy}_equity.csv`

每个交易日的账户权益和回撤，用于画资金曲线图。

| 列名 | 含义 |
|------|------|
| `dates` | 交易日期 |
| `equity` | 当日账户总资金（现金 + 持仓市值） |
| `drawdowns` | 当日回撤幅度（%）。计算公式：`(当前权益 - 历史最高权益) / 历史最高权益 × 100` |

### 3. 批量汇总 — `trades/_summary_{strategy}.csv`

批量回测时，所有股票的绩效汇总在一张表中。

| 列名 | 含义 |
|------|------|
| `symbol` | 股票代码 |
| `initial_cash` | 初始资金（默认 100,000 元） |
| `final_value` | 最终资金 |
| `total_return_pct` | 总收益率（%） |
| `total_trades` | 总交易次数 |
| `win_trades` | 盈利交易次数 |
| `lose_trades` | 亏损交易次数 |
| `win_rate_pct` | 胜率（%） |
| `sharpe_ratio` | 夏普比率（越高越好，> 1 算优秀） |
| `sortino_ratio` | Sortino 比率，只惩罚下行波动 |
| `calmar_ratio` | Calmar 比率，年化收益相对最大回撤 |
| `profit_factor` | 盈利交易总额 / 亏损交易总额绝对值 |
| `avg_trade_pnl` | 平均平仓盈亏 |
| `longest_win_streak` / `longest_loss_streak` | 最长连续盈利/亏损次数 |
| `max_drawdown_pct` | 最大回撤（%） |
| `max_drawdown_days` | 最大回撤持续天数 |

### 4. 策略对比 — `trades/_comparison_{symbol}.csv`

`compare` 命令的输出，对比同一只股票上所有策略的表现。

| 列名 | 含义 |
|------|------|
| `strategy` | 策略名称 |
| `return_pct` | 总收益率（%） |
| `sharpe` | 夏普比率 |
| `max_dd_pct` | 最大回撤（%） |
| `trades` | 交易次数 |
| `win_rate_pct` | 胜率（%） |
| `final_value` | 最终资金 |

### 5. 买点信号 — `signals/buy_signals_{strategy}_{日期}.csv`

`scan` 命令或批量回测的输出，汇总最近 N 日内出现买入信号的股票。

| 列名 | 含义 |
|------|------|
| `symbol` | 股票代码 |
| `recent_buy_dates` | 最近 N 日内的买点日期（多个用逗号分隔） |
| `signal_count` | 买点数量 |

### 6. 决策记忆 — `decisions/decision_memory.csv`

`decision record` 或买点扫描自动写入的信号复盘表。它用于事后分析策略信号质量，不参与交易信号生成。

| 列名 | 含义 |
|------|------|
| `signal_id` | 信号唯一 ID，用于去重 |
| `symbol` | 股票代码 |
| `strategy` | 策略名称 |
| `signal_date` | 信号出现日期 |
| `signal_type` | 信号类型，当前主要为 `BUY` |
| `price` | 信号日期附近收盘价；缓存不足时可为空 |
| `params_json` | 策略参数快照 |
| `source` | 信号来源文件或来源说明 |
| `evaluation_status` | 复盘状态 |
| `future_5d_return_pct` / `future_10d_return_pct` / `future_20d_return_pct` | 信号后第 N 个实际交易日收益 |
| `benchmark_5d_return_pct` / `benchmark_10d_return_pct` / `benchmark_20d_return_pct` | 同窗口基准收益 |
| `excess_5d_return_pct` / `excess_10d_return_pct` / `excess_20d_return_pct` | 个股信号收益减基准收益 |

### 7. 未来函数审计 — `audit/lookahead_*.csv`

`audit lookahead` 会静态扫描 `strategy/` 下的策略源码，查找明显的未来函数和数据泄露风险，例如：

- `data.close[1]` 这类 Backtrader 正向索引读取。
- `shift(-1)` 这类把未来行移到当前行的写法。
- 策略代码读取 `output/reports`、`output/statistics`、`output/decisions` 等事后产物。
- 历史窗口从 `range(0, ...)` 开始，可能把当前 bar 纳入历史基准。

命令：

```bash
python main.py audit lookahead --strategy sma_cross
python main.py audit lookahead
```

输出文件：

```text
output/audit/lookahead_audit_{strategy}.csv
output/audit/lookahead_audit_{strategy}.html
```

注意：第一版审计是启发式静态检查，命中项表示“需要人工复核”，不等于已经确认存在未来函数；未命中也不等于数学上证明完全没有数据泄露。

### 8. 组合目标权重 — `portfolio/target_weights_YYYYMMDD.csv`

`portfolio build` 从买点扫描 CSV 生成研究用候选组合，不会下单，也不是实盘建议。

```bash
python main.py portfolio build --signals output/signals/buy_signals_sma_cross_YYYYMMDD.csv
python main.py portfolio build --signals output/signals/buy_signals_sma_cross_YYYYMMDD.csv --method inverse_vol --max-weight 0.10
```

支持的方法：

- `equal`：等权。
- `inverse_vol`：按本地缓存近 N 日年化波动率倒数分配权重；缺失缓存或波动率无效时标注 `fallback_equal`。

输出字段：

| 列名 | 含义 |
|------|------|
| `date` | 权重生成日期 |
| `symbol` | 股票代码 |
| `signal_dates` | 来源信号日期 |
| `method` | 权重方法 |
| `raw_weight` | 应用单股上限前的原始权重 |
| `target_weight` | 应用单股上限后的目标权重 |
| `max_weight` | 本次设置的单股最大权重 |
| `gross_exposure` | 本次设置的总目标仓位 |
| `annual_volatility` | `inverse_vol` 使用的年化波动率 |
| `data_status` | 波动率数据状态，如 `ok`、`missing_cache`、`fallback_equal` |
| `source` | 来源 signals CSV |

如果候选股票太少，`max_weight × 股票数` 小于 `gross_exposure`，系统会优先遵守单股上限，此时实际总仓位会低于目标总仓位。

## 常见问题

**Q: 下载数据时提示 "token 无效"？**
A: 检查 `config.yaml` 里的 token 是否正确。注册 Tushare 后需要激活账号才能使用。

**Q: 下载速度很慢？**
A: 系统每次 API 调用后会等待 1.5 秒（可在 config.yaml 的 `rate_limit.sleep_seconds` 调整），这是为了避免被服务器限流。全市场股票数据量较大，首次下载可能需要较长时间。

**Q: 如何添加自己的策略？**
A: 在 `strategy/` 目录下新建一个 `.py` 文件，模仿 `sma_cross.py` 的写法即可。具体请参考技术文档。

**Q: 如何排除ST股票？**
A: 系统默认从 Tushare 获取股票列表时会自动过滤名称中包含 "ST" 的股票。
