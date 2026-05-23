# A股量化回测系统 — 使用说明

## 这个系统是干什么的？

简单说：**帮你用历史数据验证炒股策略是不是靠谱**。

比如你有一个想法："当 5 日均线上穿 20 日均线时买入，下穿时卖出"，这个策略到底能不能赚钱？在过去三年里表现如何？这个系统可以给你答案，并生成图表让你直观看到每一次买卖点。

它包含五个功能：
1. **下载数据** — 从网络获取 A 股的历史K线数据，存到本地（默认全市场非ST股票）
2. **策略回测** — 用历史数据模拟你的策略，算出收益率、胜率等指标（内置6种策略）
3. **策略对比** — 一次运行所有策略，横向对比找出最优
4. **扫描买点** — 检测最近N日内存在买入信号的股票，汇总导出
5. **生成报告** — 把回测结果画成 K线图（含均线、成交量）+ MACD + KDJ + 资金曲线图，存为 HTML 文件

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
quant> compare --symbol 000001.SZ
quant> report --symbol 000001.SZ --strategy sma_cross
quant> help
quant> exit
```

输入 `help` 查看所有可用命令及参数说明。

#### 工作流程示例

1. `download` → 下载全部A股（剔除ST）日K线数据，默认从20210101至今
2. `backtest --strategy sma_cross --symbol 000001.SZ` → 对平安银行回测双均线策略，查看绩效
3. `scan --strategy sma_cross` → 扫描全部已缓存股票，找出近5日有买点的股票
4. `report --symbol 000001.SZ --strategy sma_cross` → 生成 HTML 可视化报告

生成的报告在 `output/reports/` 文件夹里，用浏览器打开即可查看。

报告包含以下内容：
- **K线图**：带 5/10/20/60 日均线叠加和买卖点标记
- **联动指标区**（标签页切换，缩放同步）：
  - 成交量 — 红涨绿跌柱状图
  - MACD — DIF / DEA 线 + 柱状图
  - KDJ — K / D / J 三线（0-100 区间）
  - RSI — RSI 线 + 30/70 超买超卖参考线
- **权益曲线**：账户资金变化 + 回撤阴影

> 提示：在 K 线图上缩放/平移时，下方指标图会同步联动。点击标签页可在成交量、MACD、KDJ、RSI 之间切换。

命令示例：

```
quant> compare --symbol 000001.SZ
```

这会对指定股票依次运行所有6种策略，输出横向对比表格，帮你快速找到最适合这只股票的策略。

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

# 生成报告
python main.py backtest report --symbol 000001.SZ
```

## 可用策略一览

系统内置 6 种策略，可通过 `compare --symbol <代码>` 一键对比：

| 策略 | 命令名 | 核心参数 | 适合场景 |
|------|--------|----------|----------|
| 双均线交叉 | `sma_cross` | `--fast 5 --slow 20` | 趋势跟踪 |
| MACD金叉 | `macd_cross` | `--fast 12 --slow 26` | 趋势跟踪 |
| KDJ超买超卖 | `kdj` | `--oversold 20 --overbought 80` | 震荡市 |
| 布林带 | `bollinger` | `--period 20 --devfactor 2` | 均值回归 |
| RSI超买超卖 | `rsi` | `--period 14 --oversold 30 --overbought 70` | 震荡市 |
| 单均线 | `single_ma` | `--period 20` | 简单趋势 |

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
├── visual/              ← 图表生成相关代码
├── output/
│   ├── trades/          ← 回测交易记录输出
│   ├── reports/         ← HTML 报告输出
│   └── signals/         ← 买点扫描汇总输出
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

## 常见问题

**Q: 下载数据时提示 "token 无效"？**
A: 检查 `config.yaml` 里的 token 是否正确。注册 Tushare 后需要激活账号才能使用。

**Q: 下载速度很慢？**
A: 系统每次 API 调用后会等待 1.5 秒（可在 config.yaml 的 `rate_limit.sleep_seconds` 调整），这是为了避免被服务器限流。全市场股票数据量较大，首次下载可能需要较长时间。

**Q: 如何添加自己的策略？**
A: 在 `strategy/` 目录下新建一个 `.py` 文件，模仿 `sma_cross.py` 的写法即可。具体请参考技术文档。

**Q: 如何排除ST股票？**
A: 系统默认从 Tushare 获取股票列表时会自动过滤名称中包含 "ST" 的股票。
