# A 股量化回测系统

这是一个面向中国 A 股的本地量化研究工具。它用 Tushare 下载和缓存行情数据，用 Backtrader 做事件驱动回测，并生成交易流水、权益曲线、策略统计、指数概览、题材分析和 HTML 看板。

日常使用优先看这里：

- [日常命令速查](docs/operations/DAILY_COMMANDS.md)
- [每日常用命令 TXT](docs/operations/DAILY_WORKFLOW_COMMANDS.txt)
- [技术实现说明](TECHNICAL.md)
- [当前行为契约](docs/reference/contracts.md)
- [结构优化收敛记录](docs/plans/completed/REFACTOR_PLAN.md)

## 核心功能

1. 下载 A 股日 K、指数日 K、股票基础信息和每日指标。
2. 支持单标的、批量、题材股票池回测。
3. 内置双均线、MACD、KDJ、布林带、RSI、单均线、放量平台突破、多周期量价趋势等策略。
4. 扫描近期买点，导出买点信号。
5. 生成单标的 HTML 回测报告，支持日 K、周 K、月 K 切换。
6. 生成全市场策略画像、多策略对比、指数概览、大盘环境分析和题材涨跌看板。
7. 提供 RPS 强弱排行、个股 RPS 轨迹、主升浪/底部突破/单针探底扫描、通用选股筛选、涨跌停看板、半年涨停细分股票池和轮动研究。
8. 提供个股手动画线工具，可在 K 线图上手动画趋势线、支撑线和阻力线。
9. 通过统一 dashboard 工作台汇总市场状态、信号流、指数、题材、策略和个股报告入口。
10. 提供行业板块资金流分钟级采集、CSV 归档、历史回放和动态监控页。

## 当前状态

结构优化第一轮已经收敛完成。当前重点不再继续拆模块，而是保持命令、CSV 字段、输出路径和回测口径稳定，在明确业务需求下迭代数据下载、题材分析和策略规则。详细记录见 [历史重构计划](docs/plans/completed/REFACTOR_PLAN.md)。

## 快速开始

安装依赖：

```bash
pip install -r requirements.txt
```

复制并配置 `config.yaml`，至少需要设置 Tushare token。大规模数据建议放到外部磁盘：

```yaml
tushare:
  token: "你的Tushare Token"

data:
  cache_dir: "/Volumes/extend/quant_yb_data/cache"
  meta_dir: "/Volumes/extend/quant_yb_data/meta"
  stock_adj: "qfq"

output:
  trades_dir: "/Volumes/extend/quant_yb_data/output/trades"
  reports_dir: "/Volumes/extend/quant_yb_data/output/reports"
  signals_dir: "/Volumes/extend/quant_yb_data/output/signals"
  statistics_dir: "/Volumes/extend/quant_yb_data/output/statistics"
```

项目中的 CLI、下载器、分析器和维护脚本统一通过 `project_config.py` 读取配置。默认使用项目根目录的 `config.yaml`；临时运行另一套配置时可设置 `QUANTYB_CONFIG=/path/to/config.yaml`，无需修改代码或复制配置文件。

进入交互式命令行：

```bash
python main.py
```

看到 `quant>` 后即可执行日常命令：

```text
quant> download
quant> backtest --strategy multi_timeframe_volume_trend --symbol 000001.SZ
quant> report --symbol 000001.SZ --strategy multi_timeframe_volume_trend
quant> stats theme --pool 人形机器人 --start 20260601 --end 20260619
quant> dashboard
```

## 常用命令

更新数据：

```text
quant> stock-basic --force
quant> daily-basic --start 20260601 --end 20260618
quant> data-audit
quant> download
quant> index overview --all
quant> index members --all
quant> index ths
quant> index market
quant> index forecast --symbol 000001.SH --horizon 5
```

回测和报告：

```text
quant> backtest --strategy multi_timeframe_volume_trend --symbol 000001.SZ
quant> backtest --strategy multi_timeframe_volume_trend
quant> backtest --strategy multi_timeframe_volume_trend --pool 机器人
quant> scan --strategy multi_timeframe_volume_trend --days 5
quant> report --strategy multi_timeframe_volume_trend
quant> stats analyze --strategy multi_timeframe_volume_trend
quant> stats rps --window 120 --top 50
quant> stats pattern --pattern bottom_pattern_break
quant> stats screen --preset trendline_pullback --pool 机器人,AI --pool-mode any
quant> stats limit-board --trade-date 20260703 --save-pools
quant> stats limit-research --months 6 --min-limit-count 1
quant> stats limit-strength --back-days 10 --min-limit-count 2
quant> stats support-resistance --symbol 688981 --name 中芯国际 --start 20240101 --end 20260717
quant> stats radar --top 300
quant> trendlines --symbol 000001.SZ --bars 0
quant> sector-flow report
quant> dashboard
```

直接命令模式：

```bash
python main.py data download
python main.py data audit
python main.py backtest run --strategy multi_timeframe_volume_trend --symbol 000001.SZ
python main.py backtest report --symbol 000001.SZ --strategy multi_timeframe_volume_trend
python main.py stats theme --pool 人形机器人 --start 20260601 --end 20260619
python main.py stats rps --window 120 --top 50
python main.py stats pattern --pattern main_rise_wave
python main.py stats screen --preset trendline_pullback --pool 机器人,AI --pool-mode any --top 50
python main.py stats rotation --model three_factor --hold-count 5
python main.py stats limit-board --trade-date 20260703 --save-pools
python main.py stats limit-research --months 6 --min-limit-count 1
python main.py stats limit-strength --back-days 10 --min-limit-count 2
python main.py stats support-resistance --symbol 688981 --name 中芯国际 --start 20240101 --end 20260717
python main.py stats radar --top 300
python main.py backtest trendlines --symbol 000001.SZ --bars 0
python main.py index members --all
python main.py index ths --start 20110101 --end 20260714 --refresh-list --include-concepts --skip-failures
python main.py index market
python main.py index forecast --symbol 000001.SH --horizon 5
python main.py market risk-state --symbol 000001.SH
python main.py market risk-matrix --symbol 000001.SH
python main.py sector-flow report
python main.py sector-flow watch --once
python main.py dashboard
```

流水线：

```text
quant> run "download; backtest --strategy multi_timeframe_volume_trend; report --strategy multi_timeframe_volume_trend; stats analyze --strategy multi_timeframe_volume_trend; dashboard"
```

更完整的日常命令见 [DAILY_COMMANDS.md](docs/operations/DAILY_COMMANDS.md)。

## 题材股票池

题材股票池使用 JSON 维护，路径由 `config.yaml` 的 `stock_pool.path` 指定。推荐每个题材保存股票代码和名称，同一只股票可以出现在多个题材里。

示例：

```json
{
  "pools": {
    "机器人": {
      "description": "机器人产业链",
      "stocks": [
        {"ts_code": "002747.SZ", "name": "埃斯顿"}
      ]
    }
  }
}
```

回测题材池：

```text
quant> backtest --strategy multi_timeframe_volume_trend --pool 机器人
quant> backtest --strategy multi_timeframe_volume_trend --pool 机器人,AI --pool-mode all
```

统计题材区间涨跌并生成专题看板：

```text
quant> stats theme --pool 机器人 --start 20260601 --end 20260619
```

题材看板会把股票池里的成员按本地 K 线首个有效收盘价归一化，等权合成为一个“概念指数”。概念 K 线支持日线、周线、月线切换；成交量、成交金额、涨跌家数和趋势广度使用股票缓存完整区间并与 K 线缩放联动。看板还会展示 MA20/MA60 上方占比、20 日新高/新低、个股离散度、年化波动率、收益/回撤比、距均线和 20 日量能等派生指标。上方摘要、个股涨跌排行和区间明细仍按命令里的 `--start/--end` 统计，其中个股涨跌排行展示涨幅前 7 和跌幅后 5，并标注统计区间。

导入、导出和把扫描结果转成股票池：

```text
quant> stats pool-import --input stocks.csv --name 候选池
quant> stats pool-export --pool 候选池 --output 候选池.blk --format blk
quant> stats pool-from-signals --input output/signals/pattern_signals_bottom_pattern_break_20260703.csv --name 底部突破池
```

## 研究扫描和信号中心

`stats rps`、`stats rps-track`、`stats pattern`、`stats screen`、`stats rotation` 和 `stats radar` 都只读取本地 K 线缓存；`stats limit-board` 调用 Tushare 涨跌停接口，并可把涨停、跌停、炸板和涨停行业分类保存为股票池。`stats limit-research` 会抓取最近区间涨停股，按液冷温控、PCB载板、材料、存储、CPO、铜缆、算力、机器人等细分主题写入股票池，并生成基本面研究 Markdown。`stats limit-strength` 读取本地涨停明细 CSV 数据库，统计近期涨停次数后按均线多头、前高突破、动量和成交量评分，并输出新增/剔除变化。`stats support-resistance` 通过 AkShare 获取指定股票的复权日线，计算 MA 与五档斐波那契价位，输出 K 线、共振区域和文字分析报告。它们属于研究和复盘输出，不改变回测交易模型、手续费、滑点、涨跌停、T+1、成交量限制或已有交易流水字段。

```text
quant> stats rps --window 120 --top 50
quant> stats rps-track --symbol 000001.SZ --window 120
quant> stats pattern --pattern main_rise_wave
quant> stats pattern --pattern bottom_pattern_break --pool 机器人
quant> stats pattern --pattern needle_bottom_raise
quant> stats screen --preset trendline_pullback --pool 机器人,AI --pool-mode any --top 50
quant> stats screen --preset trendline_pullback --pool 机器人 --save-pool --pool-name 趋势线回踩池
quant> stats vpt --top 100 --min-score 70
quant> stats rotation --model momentum --hold-count 5 --rebalance-days 5
quant> stats limit-board --trade-date 20260703 --save-pools
quant> stats limit-research --months 6 --min-limit-count 1 --fundamental-top 120
quant> stats limit-strength --data-path /path/to/UplimData --back-days 10 --min-limit-count 2
quant> stats support-resistance --symbol 688981 --name 中芯国际 --start 20240101 --end 20260717
quant> stats radar --top 300
quant> etf report
quant> dashboard
```

`stats screen` 是通用选股筛选入口，第一版内置 `trendline_pullback`：寻找存在有效上升趋势线、最近 3 个交易日回落/贴近趋势线且未有效跌破的股票，可叠加 `--pool` 和 `--pool-mode any/all` 做题材漏斗。结果默认只输出 CSV/HTML；只有显式传 `--save-pool --pool-name ...` 才会写入股票池。

`stats vpt` 是独立的 VPT-01 放量启动—供给收缩趋势筛选器。它从本地日 K 中识别 T0 放量上涨/突破事件，再以 T0 后的 UDVR、方向成交量、回调量比、MA10/MA20、高低点和趋势回归质量生成 `NONE`、`SPIKE_DETECTED`、`TREND_CONFIRMING`、`QUALIFIED`、`WEAKENING`、`FAILED` 状态。扫描严格按截止日截断数据，T0 巨量不进入后续量能比较；VPT 与 RS 分开呈现，不写入正式策略、仓位或订单。核心阈值可在 `config.yaml` 的 `vpt` 段按 `VPTConfig` 字段覆盖。

`stats radar` 生成研究型“强势股雷达”：从可交易股票池出发，计算行业 RS、股票 RS percentile、RS persistence、趋势结构、高位距离、量价状态、收缩状态和 deterministic state，并保存每日 snapshot 供 T+5/T+10/T+20 后验审计。`BREAKOUT` 等 state 只表示观察分类，不是买入建议，也不会写入正式策略、仓位或风险闸门。

`etf report` 会生成独立 ETF 策略研究板块：ETF 日线统一适配为 OHLCV，输出 MACD、双 KAMA、布林带、N 日突破、ATR 止盈止损等择时信号，并生成动量轮动和三因子轮动排名；外部红绿灯/排名情绪文件可从 `etf_strategy.ftp` 配置的 QTYX_352 公共 FTP 自动刷新，也可通过 `red_green_path` / `rank_emotion_path` 指向本地 CSV。默认报告为 `output.reports_dir/etf_strategy/etf_strategy_dashboard.html`，只生成研究信号和模拟交易意图，不连接 QMT、不真实下单。

外部信号也可以单独刷新和验算：

```bash
python main.py etf signals --refresh --symbol 515880.SH --top-n 10
```

`sector-flow` 提供行业板块资金流实时监控/历史回放。`sector-flow collect` 在交易时段内通过 AkShare 采集一次 `stock_fund_flow_industry(symbol="即时")` 并按分钟归档 CSV；`sector-flow report` 从当天本地 CSV 进入历史回放，否则生成实时监控页；`sector-flow watch` 按 `sector_money_flow.interval_seconds` 持续采集并刷新 `output.reports_dir/sector_money_flow.html`。关注板块、采集间隔、归档目录和是否优先历史回放均在 `config.yaml` 的 `sector_money_flow` 段配置。

`data audit` 会检查全部本地个股、指数和 `daily_basic` 文件的字段、最新日期覆盖、末尾日期顺序、最新 OHLC 合法性与成交额口径，输出 JSON、问题 CSV 和 HTML；`--deep` 才会逐行扫描完整历史。`dashboard` 会显示最近一次审计的新鲜度并链接到数据质量报告。

回测涨跌停默认启用板块识别：主板 10%，科创板 20%，创业板在 2020-08-24 前使用 10%、之后使用 20%，北交所 30%。`backtest.board_aware_price_limits: false` 可退回统一使用 `limit_pct`。当前仍不自动处理新股上市前五个交易日无涨跌幅限制和历史 ST 时点状态。

市场单在次一交易日开盘执行前会再次检查当日涨跌停价格，避免只检查信号日却在次日一字涨停买入或一字跌停卖出。卖出印花税默认按成交日期切换：2023-08-28 前为 0.1%，之后为 0.05%；可用 `date_aware_stamp_duty: false` 固定使用 `stamp_duty`。

`dashboard` 默认生成轻量的产品导航壳：主入口为今日总览、数据中心、市场环境、行情中心、强势方向和策略选股；RPS、涨停、ETF、回测、预测等研究页归入备用报告入口。它只读取已有本地报告，不下载数据、不刷新市场结构、不生成行业/个股页面。原来的聚合总面板仍可用 `python main.py dashboard --legacy` 生成到 `output.reports_dir/legacy_dashboard.html`；摘录页也可以用 `python main.py index structure-brief` 从已有 JSON 和本地缓存单独生成。

`index environment` 从已有市场结构 JSON 生成 `output.reports_dir/index_forecast/{symbol}_market_environment.html`：先展示现有状态结论与六类关键证据，再在“详细研究”折叠区保留原市场结构摘录和完整报告入口。该命令不下载数据、不运行市场结构计算、不调用 LLM。

## 股票 K 线与手动画线工具

股票 K 线页面现在集成浏览器端手动画线工具，不再单独生成手动画线 report。页面默认内嵌全部本地缓存历史，打开时只显示最近一年，后续可用滚轮或底部缩放条调整时间跨度。页面提供日 K / 周 K / 月 K、MA5/10/20/60、成交量、成交额、MACD、RSI、KDJ，以及趋势线、支撑线、阻力线、撤销和清空当前周期等工具；手动画线结果保存在浏览器 localStorage 中，按股票代码和日/周/月周期隔离。

直接读取全部本地缓存 K 线生成股票 K 线页面：

```bash
python main.py backtest trendlines --symbol 000001.SZ --bars 0
```

交互模式中也可以执行：

```text
quant> trendlines --symbol 000001.SZ --bars 0
```

报告输出到 `output.reports_dir/stock_kline/{symbol}.html`，RPS、筛选器、dashboard 和其它个股入口统一链接到这个页面。`trendlines` 命令仅作为兼容入口保留，也会生成同一个股票 K 线页面。底层自动结构识别模块仍保留在 `analysis/trendlines.py`，仅供研究或其它明确调用场景使用。

## 输出位置

路径以 `config.yaml` 为准，常见输出包括：

- `data.cache_dir/{ts_code}.csv`：股票日 K 缓存。
- `data.meta_dir/stocks.csv`：股票基础信息。
- `data.meta_dir/stock_names.csv`：股票代码和名称映射。
- `data.meta_dir/daily_basic/{ts_code}.csv`：每日指标。
- `output.trades_dir/{symbol}_{strategy}.csv`：交易流水。
- `output.trades_dir/{symbol}_{strategy}_equity.csv`：权益曲线。
- `output.reports_dir/{symbol}_{strategy}.html`：单标的报告。
- `output.reports_dir/stock_kline/{symbol}.html`：股票 K 线页面，含日/周/月 K、技术指标与手动画线工具。
- `output.statistics_dir/theme_{pool}_{start}_{end}.html`：题材看板。
- `output.statistics_dir/theme_index_{pool}_{start}_{end}.csv`：题材等权概念指数 OHLCV 与广度指标。
- `output.statistics_dir/rps_top_{date}_w{window}.csv/html`：RPS Top N 排行。
- `output.statistics_dir/rps_track_{symbol}_{window}.csv/html`：个股 RPS 轨迹。
- `output.signals_dir/pattern_signals_{pattern}_{date}.csv/html`：形态扫描结果。
- `output.signals_dir/screen_signals_{preset}[_pool]_{date}.csv/html`：通用选股筛选结果。
- `output.signals_dir/vpt_candidates_{date}.csv`：VPT-01 候选；全量状态与候选历史分别为 `output.statistics_dir/vpt/vpt_snapshot_{date}.csv`、`vpt_history_{date}.csv`，交互报告为 `output.reports_dir/vpt/vpt_candidates.html`。
- `output.statistics_dir/rotation_{model}_{pool}_{start}_{end}_nav.csv`：轮动研究净值。
- `output.statistics_dir/limit_board_{date}.csv/html`：每日涨跌停看板。
- `output.statistics_dir/limit_up_research_{start}_{end}_detail.csv`：区间涨停明细。
- `output.statistics_dir/limit_up_research_{start}_{end}_stocks.csv`：区间涨停个股细分主题汇总。
- `output.statistics_dir/limit_up_research_{start}_{end}_themes.csv`：区间涨停主题热度汇总。
- `output.statistics_dir/limit_up_research_{start}_{end}_fundamentals.csv`：高频涨停股基本面快照。
- `docs/research/limit_up_research_{start}_{end}.md`：区间涨停股票池与基本面分析文档。
- `output.statistics_dir/limit_strength/limit_strength_{date}.csv`：本地涨停数据库强势股评分结果。
- `output.statistics_dir/limit_strength/limit_strength_{date}_changes.csv`：相对上一版结果的新增/剔除清单。
- `output.statistics_dir/limit_strength/每日强势股结果.csv`：最新强势股筛选结果。
- `output.statistics_dir/limit_strength/limit_strength_{date}.html`：涨停强势股评分报告。
- `output.statistics_dir/strong_stock_radar/radar_snapshot_{date}.csv`：强势股雷达当日审计快照。
- `output.statistics_dir/strong_stock_radar/strong_stock_radar_latest.csv`：强势股雷达最新全量结果。
- `output.statistics_dir/strong_stock_radar/radar_evaluation.csv`：基于历史 snapshot 补齐的 T+5/T+10/T+20、MFE、MAE 后验审计。
- `output.reports_dir/strong_stock_radar/strong_stock_radar.html`：强势行业、强势股票和审计摘要看板。
- `output.reports_dir/etf_strategy/etf_strategy_dashboard.html`：ETF 策略独立板块。
- `output.statistics_dir/etf_strategy/etf_strategy_summary.csv`：ETF 择时和轮动排名汇总。
- `output.statistics_dir/etf_strategy/etf_strategy_timing_signals.csv`：ETF 通用择时信号。
- `output.statistics_dir/etf_strategy/etf_strategy_momentum_ranking.csv`：ETF 动量轮动排名。
- `output.statistics_dir/etf_strategy/etf_strategy_three_factor_ranking.csv`：ETF 三因子轮动排名。
- `output.reports_dir/market_overview.html`：大盘环境分析看板，包含多指数强弱、涨跌家数、A/D线和 NH-NL。
- `output.reports_dir/index_forecast/{symbol}_h{horizon}.html`：市场环境预测报告，支持 1/5/10/20 个交易日。
- `output.statistics_dir/index_forecast/indicators_{symbol}.csv`：只含当日已知数据的市场环境预测指标宽表。
- `output.statistics_dir/index_forecast/features_{symbol}.csv`：未来个股横截面结果、机会/风险分和环境标签。
- `output.statistics_dir/market_risk_gate/{symbol}/`：独立极端风险闸门的状态、未来结果、逐折实验矩阵和自动门槛审计。
- `output.reports_dir/market_risk_gate/{symbol}_{experiment}_risk_gate.html`：E1-E10 独立实验报告；该模块不修改正式环境信号或仓位。
- `output.reports_dir/dashboard.html`：本地研究工作台，聚合市场状态、信号中心、指数、题材、ETF、策略和报告入口。
- `output.reports_dir/data_quality.html`：本地市场数据质量报告。
- `output.statistics_dir/data_quality/market_data_audit.json`：数据质量机器可读摘要。
- `output.statistics_dir/data_quality/market_data_issues.csv`：数据质量问题明细。
- `output.reports_dir/industry/industry_market.html`：行业行情页，展示行业强弱榜、官方/近似行业成分股、个股 K 线与可点击行业指数 K 线。

## 文档导航

操作类：

- [日常命令速查](docs/operations/DAILY_COMMANDS.md)
- [Mac Conda 环境说明](docs/operations/MAC_CONDA_SETUP.md)
- [Git 使用说明](docs/operations/GIT_GUIDE.md)

策略类：

- [多周期量价趋势策略](docs/strategies/MULTI_TIMEFRAME_VOLUME_TREND.md)
- [多周期量价趋势策略 PDF](docs/strategies/MULTI_TIMEFRAME_VOLUME_TREND.pdf)
- [Wyckoff 三屏策略设计](docs/strategies/WYCKOFF_TRIPLE_SCREEN.md)

计划和参考：

- [结构优化收敛记录](docs/plans/completed/REFACTOR_PLAN.md)
- [架构优化计划归档](docs/plans/completed/ARCHITECTURE_OPTIMIZATION_PLAN.md)
- [大盘指数分析计划](docs/plans/MARKET_INDEX_ANALYSIS_PLAN.md)
- [指数预测报告说明](docs/reference/index_forecast_report.md)
- [市场极端风险闸门研究说明](docs/reference/market_risk_gate.md)
- [市场极端风险闸门 E1-E10 结果](docs/research/market_risk_gate_results_20260713.md)
- [指数环境预测 P0/P1 最终研究结果](docs/research/index_forecast_p0_p1_results_20260713.md)
- [TradingAgents 集成计划](docs/plans/TRADINGAGENTS_INTEGRATION_PLAN.md)
- [GitHub 量化项目参考](docs/plans/GITHUB_QUANT_PROJECTS_REFERENCE.md)
- [当前行为契约](docs/reference/contracts.md)

## 验证命令

```bash
python -m unittest discover -s tests
python -m compileall main.py cli data engine strategy visual analysis tests
```

批量回测会写入大量输出文件；修改共享逻辑时，优先使用单标的命令验证。
