# CODEX.md

## 项目当前状态

这是一个面向中国 A 股的本地量化研究/回测项目。主入口是 `python main.py`，无子命令时进入 `quant>` REPL；直接命令使用 Click 子命令。当前主链路是 Tushare 数据缓存、Backtrader 事件驱动回测、批量扫描、统计分析、指数/题材/信号看板和 HTML 报告。

当前结构优化已收敛，不要为了风格继续拆目录或迁移 Click 参数。新增能力优先复用现有分层：`cli/` 负责命令，`data/` 负责下载和股票池，`engine/` 负责回测，`strategy/` 负责交易策略，`analysis/` 负责研究分析，`visual/` 负责 HTML 报告和 dashboard。

## 最新落地能力

- RPS：`analysis/rps.py`，命令为 `python main.py stats rps` 和 `stats rps-track`。
- 形态扫描：`analysis/patterns.py`，支持 `main_rise_wave`、`bottom_pattern_break`、`needle_bottom_raise`。
- 股票池流转：`data/stock_pool.py` 支持 CSV、QTYX `trade_pool.json`、通达信 `.blk` 导入/导出，以及扫描结果转股票池。
- 轮动研究：`analysis/rotation.py`，支持 `momentum` 和 `three_factor`，属于研究输出，不进入 Backtrader。
- 涨跌停看板：`analysis/limit_moves.py`，命令为 `python main.py stats limit-board --trade-date YYYYMMDD --save-pools`。
- 半年涨停研究：`analysis/limit_up_research.py`，命令为 `python main.py stats limit-research --months 6 --min-limit-count 1`；按液冷温控、PCB载板、AI高速材料、存储/HBM、CPO光模块、铜缆高速连接、算力电力配套、机器人等细分主题写入股票池，并生成基本面 Markdown。
- dashboard：`visual/dashboard.py` 已改为本地研究工作台，左侧为市场/信号/指数/题材/策略/报告索引，主区包含市场状态、信号流、指数导航、题材看板、策略汇总和最近单标的报告。

## 关键命令

```bash
python main.py dashboard
python main.py stats rps --window 120 --top 50
python main.py stats rps-track --symbol 000001.SZ --window 120
python main.py stats pattern --pattern main_rise_wave
python main.py stats pattern --pattern bottom_pattern_break --pool 机器人
python main.py stats pattern --pattern needle_bottom_raise
python main.py stats rotation --model three_factor --hold-count 5 --rebalance-days 5
python main.py stats limit-board --trade-date 20260703 --save-pools
python main.py stats limit-research --months 6 --min-limit-count 1 --fundamental-top 120
python main.py stats pool-import --input stocks.csv --name 候选池
python main.py stats pool-export --pool 候选池 --output 候选池.blk --format blk
python main.py stats pool-from-signals --input output/signals/pattern_signals_bottom_pattern_break_20260703.csv --name 底部突破池
```

## 输出契约

- 交易流水：`output.trades_dir/{symbol}_{strategy}.csv`。
- 权益曲线：`output.trades_dir/{symbol}_{strategy}_equity.csv`。
- 批量汇总：`output.trades_dir/_summary_{strategy}.csv`。
- 买点扫描：`output.signals_dir/buy_signals_{strategy}_{date}.csv`。
- 形态扫描：`output.signals_dir/pattern_signals_{pattern}_{date}.csv` 和同名 `.html`。
- RPS：`output.statistics_dir/rps_top_{date}_w{window}.csv/html`、`rps_track_{symbol}_{window}.csv/html`。
- 轮动：`output.statistics_dir/rotation_{model}_{pool}_{start}_{end}_nav.csv`、`*_holdings.csv`、同名 `.html`。
- 涨跌停：`output.statistics_dir/limit_board_{date}.csv/html`，以及 `_industry.csv`、`_concepts.csv`。
- 半年涨停研究：`output.statistics_dir/limit_up_research_{start}_{end}_detail.csv`、`*_stocks.csv`、`*_themes.csv`、`*_fundamentals.csv`，研究文档为 `docs/research/limit_up_research_{start}_{end}.md`，股票池写入 `stock_pool.path` 下的 `半年涨停_*_{start}_{end}`。
- dashboard：`output.reports_dir/dashboard.html`。

## 回测可信度边界

- 不得让 dashboard、报告层、统计分析或全市场研究结果反向影响单次策略信号。
- 策略信号只能使用当前 bar 及之前的数据；周线过滤只能使用已完成周线。
- 形态扫描中，突破基准、箱体上沿、历史高点等条件必须使用信号日之前的窗口。
- RPS、形态扫描、轮动研究和半年涨停研究属于研究输出，不改变成交价格、手续费、滑点、涨跌停、T+1、成交量限制或交易流水字段。
- 批量选股仍存在当前上市列表口径带来的幸存者偏差，严肃绩效判断必须标注。

## 验证基线

优先使用项目 conda 环境：

```bash
/Users/caleb/miniforge3/envs/quant_yb/bin/python -m compileall main.py cli data engine strategy visual analysis tests
/Users/caleb/miniforge3/envs/quant_yb/bin/python -m unittest discover -s tests
```

dashboard 最近一次验证：

- `python main.py dashboard` 已生成 `/Volumes/extend/quant_yb_data/output/reports/dashboard.html`。
- Playwright 浏览器检查过 1440px 和 390px 视口，无 console 错误，移动端无横向溢出。

## 常用参考文档

- `README.md`：用户入口和常用命令。
- `TECHNICAL.md`：技术实现和模块说明。
- `docs/operations/DAILY_COMMANDS.md`：日常命令速查。
- `docs/reference/contracts.md`：当前行为契约。
- `docs/plans/QTYX_352_REFERENCE_COMPARISON.md`：QTYX_352 对比参考和已吸收方向。
