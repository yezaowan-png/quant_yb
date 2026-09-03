# 日常命令速查

这份文档以 `quant>` 交互模式里的 shell 命令为主。先进入交互模式：

```bash
python main.py
```

看到 `quant>` 后，直接输入下面这些命令即可。

纯文本版命令清单见同目录 `DAILY_WORKFLOW_COMMANDS.txt`，适合直接复制到终端或按日期批量替换。

如果要交给 Codex 或系统定时任务每天自动运行，见同目录 `DAILY_AUTOMATION.md`。

## 1. 数据更新

更新股票代码和名称映射：

```text
quant> stock-basic --force
```

更新全市场每日指标，用于后续题材热度分析：

```text
quant> daily-basic --start 20260601 --end 20260618
```

更新单只股票行情：

```text
quant> download --symbol 000001.SZ
```

更新多只股票行情：

```text
quant> download --symbol "000001.SZ,600519.SH"
```

全市场行情增量更新：

```text
quant> download
```

已有缓存只补最新交易日时，`download` 会按交易日一次拉取全市场 K 线，再拆分追加到每只股票 CSV；首次建库或强制刷新仍会按股票逐只下载。
检测到可以增量下载时，程序会先询问是否使用增量；选择 `n` 会改为重新全量下载。
增量下载会维护 `data.meta_dir/kline_checked_dates.csv`，避免停牌或无数据股票导致旧交易日被反复请求。

用失败文件补下载：

```text
quant> download --failed-file output/download_failures/download_failures_xxx_final.csv
```

## 2. 单标的回测

回测一只股票：

```text
quant> backtest --strategy multi_timeframe_volume_trend --symbol 000001.SZ
```

生成单只股票报告：

```text
quant> report --symbol 000001.SZ --strategy multi_timeframe_volume_trend
```

对比一只股票的所有策略：

```text
quant> compare --symbol 000001.SZ
```

## 3. 批量回测

回测全部已缓存股票：

```text
quant> backtest --strategy multi_timeframe_volume_trend
```

回测指定多只股票：

```text
quant> backtest --strategy multi_timeframe_volume_trend --symbols "000001.SZ,600519.SH"
```

回测题材股票池：

```text
quant> backtest --strategy multi_timeframe_volume_trend --pool 机器人
```

多个题材取并集：

```text
quant> backtest --strategy multi_timeframe_volume_trend --pool 机器人,AI --pool-mode any
```

多个题材取交集：

```text
quant> backtest --strategy multi_timeframe_volume_trend --pool 机器人,AI --pool-mode all
```

## 4. 扫描买点

扫描最近 5 个交易日买点：

```text
quant> scan --strategy multi_timeframe_volume_trend --days 5
```

扫描最近 10 个交易日买点：

```text
quant> scan --strategy multi_timeframe_volume_trend --days 10
```

## 5. 报告和统计

为已有交易流水批量生成报告：

```text
quant> report --strategy multi_timeframe_volume_trend
```

生成某只股票最近 250 根 K 线的手动画线页面：

```text
quant> trendlines --symbol 000001.SZ --bars 250
```

生成单策略统计画像：

```text
quant> stats analyze --strategy multi_timeframe_volume_trend
```

生成多策略统计对比：

```text
quant> stats compare
```

统计题材区间涨跌：

```text
quant> stats theme --pool 人形机器人 --start 20260601 --end 20260619
```

输出会包含题材平均涨跌、中位涨跌、上涨占比、平均回撤、TOP 个股，并保存题材摘要 CSV、个股明细 CSV 和 HTML 看板到 `output.statistics_dir`。

RPS、形态扫描、通用选股筛选和轮动研究：

```text
quant> stats rps --window 120 --top 50
quant> stats rps-track --symbol 000001.SZ --window 120
quant> stats pattern --pattern main_rise_wave
quant> stats pattern --pattern bottom_pattern_break --pool 人形机器人
quant> stats pattern --pattern needle_bottom_raise
quant> stats screen --preset trendline_pullback --pool 人形机器人,AI --pool-mode any --top 50
quant> stats screen --preset trendline_pullback --pool 人形机器人 --save-pool --pool-name 趋势线回踩池
quant> stats rotation --model three_factor --hold-count 5 --rebalance-days 5
quant> stats radar --top 300
```

`stats screen` 第一版用于筛选“趋势向上、最近回踩趋势线、未有效跌破”的股票。它只读取本地 K 线缓存，支持 `--trade-date` 做历史截止日筛选，结果默认写到 `output.signals_dir/screen_signals_*.csv/html`；只有传 `--save-pool --pool-name ...` 才会更新股票池。

`stats radar` 生成强势股雷达、行业强度、当日 snapshot 和 T+5/T+10/T+20 后验审计，默认输出到 `output.statistics_dir/strong_stock_radar/` 与 `output.reports_dir/strong_stock_radar/strong_stock_radar.html`。该模块只做市场观察和复盘分类，不输出买卖建议。

生成每日涨跌停看板，并把涨停、跌停、炸板和行业分类写入股票池：

```text
quant> stats limit-board --trade-date 20260703 --save-pools
```

生成最近半年涨停股研究，按液冷、PCB、材料、存储、CPO、铜缆、算力、机器人等细分主题写入股票池，并保存基本面分析文档：

```text
quant> stats limit-research --months 6 --min-limit-count 1 --fundamental-top 120
```

导入/导出股票池，或把扫描结果 CSV 转成股票池：

```text
quant> stats pool-import --input stocks.csv --name 候选池
quant> stats pool-export --pool 候选池 --output 候选池.blk --format blk
quant> stats pool-from-signals --input output/signals/pattern_signals_bottom_pattern_break_20260703.csv --name 底部突破池
```

生成本地汇总面板：

```text
quant> dashboard
```

`dashboard` 是本地研究工作台，会自动收录已经生成的市场状态、信号流、指数报告、策略报告、单标的报告、题材 HTML 看板和信号中心结果。

## 6. 指数概览

更新并生成单个指数概览：

```text
quant> index overview --symbol 000001.SH
```

更新并生成全部配置指数概览：

```text
quant> index overview --all
```

下载分层广度所需指数成分：

```text
quant> index members --all
```

下载同花顺行业/风格代理指数缓存：

```text
quant> index ths --start 20110101 --end 20260714
```

生成大盘环境分析看板：

```text
quant> index market
```

生成上证指数预测模型报告：

```text
quant> index forecast --symbol 000001.SH --horizon 5
```

`index ths` 会调用 Tushare `ths_index` 缓存同花顺指数列表到 `data.meta_dir/ths_indices.csv`，并用 `ths_daily` 下载 `config.yaml::ths_indices` 中的同花顺行业指数、风格代理指数和额外指数到 `data.cache_dir/index/`。市场结构报告会优先使用这些缓存来生成“市场风格”和“行业强弱榜”；缓存缺失或行业指数数量不足时，自动回退到本地股票篮子口径。
`index members --all` 会下载沪深300、中证1000、中证2000等默认分层广度所需指数成分，保存到 `data.meta_dir/index_members/`。创业板广度默认使用 `stocks.csv` 中的创业板全板块股票，不需要下载；如果要额外下载创业板指成分，可使用 `index members --all --include-chinext-index`。`index market` 会更新配置中的指数，横向比较近 5/20/60 日表现、MA20/MA60/MA120 状态、回撤、波动率、相对强弱和趋势分，并输出到 `output.reports_dir/market_overview.html`。如果本地股票缓存齐全，看板会展示上涨/下跌/平盘家数，并在“上证广度指标”区域用副图展示全A、沪深300、中证1000、中证2000、创业板等分层标准化 A/D 线，以及 NH-NL 和 NH-NL 5 日加总；指数 K 线报告的日 K tooltip 会显示每日上涨、下跌和平盘家数。
`index forecast` 会基于上证指数趋势、MACD/KDJ、成交金额、A/D 斜率、NH-NL 斜率和分层广度生成规则预测报告，输出到 `output.reports_dir/index_forecast/`。数据会拆成三张 CSV：`indicators_*.csv` 是纯指标宽表，`features_*.csv` 是追加未来标签后的训练/验证表，`predictions_*.csv` 是模型预测结果。

`index structure-brief` 只读取已有 `output.statistics_dir/index_forecast/market_structure_{symbol}.json`、可用 `features_{symbol}.csv` 和本地指数/行业缓存，单独生成 `output.reports_dir/index_forecast/{symbol}_market_structure_brief.html`；它不生成完整九屏 HTML、不调用 LLM、不写归档。
预测报告里重点看“模型评估图表”和“模型评估明细”：分数分桶收益是否随分数提高而变好，bull/neutral/bear 分组的未来收益是否有明显差异，以及规则择时曲线是否优于买入持有。

## 7. 常用流水线

单策略全流程：

```text
quant> run "stock-basic --force; daily-basic --start 20260601 --end 20260618; backtest --strategy multi_timeframe_volume_trend; report --strategy multi_timeframe_volume_trend; stats analyze --strategy multi_timeframe_volume_trend; dashboard"
```

只更新数据、指数和面板：

```text
quant> run "stock-basic --force; daily-basic --start 20260601 --end 20260618; index ths --start 20110101 --end 20260618; index overview --all; index market; dashboard"
```

题材股票池回测：

```text
quant> run "backtest --strategy multi_timeframe_volume_trend --pool 机器人; report --strategy multi_timeframe_volume_trend; stats analyze --strategy multi_timeframe_volume_trend; dashboard"
```

## 8. 脚本模式对应写法

如果不想进入 `quant>`，也可以直接在系统 shell 里执行。常用对应关系如下：

```bash
python main.py data stock-basic --force
python main.py data daily-basic --start 20260601 --end 20260618
python main.py data download --symbol 000001.SZ
python main.py backtest run --strategy multi_timeframe_volume_trend --symbol 000001.SZ
python main.py backtest report --symbol 000001.SZ --strategy multi_timeframe_volume_trend
python main.py stats theme --pool 人形机器人 --start 20260601 --end 20260619
python main.py index ths --start 20110101 --end 20260618
python main.py index market
python main.py index forecast --symbol 000001.SH --horizon 5
python main.py dashboard
```

脚本模式的一键流水线也使用 shell 短命令：

```bash
python main.py run "stock-basic --force; daily-basic --start 20260601 --end 20260618; index ths --start 20110101 --end 20260618; backtest --strategy multi_timeframe_volume_trend; report --strategy multi_timeframe_volume_trend; dashboard"
```

## 9. 常用文件

基础信息和每日指标：

```text
data.meta_dir/stocks.csv
data.meta_dir/stock_names.csv
data.meta_dir/daily_basic/{股票代码}.csv
data.meta_dir/kline_checked_dates.csv
```

题材股票池：

```text
stock_pool.path
```

推荐 JSON 格式：

```json
{
  "pools": {
    "人形机器人": {
      "stocks": [
        {"ts_code": "300024.SZ", "name": "机器人"}
      ]
    }
  }
}
```

主要输出目录：

```text
output.trades_dir
output.reports_dir
output.signals_dir
output.statistics_dir
```

## 10. 最常用的一组

平时只记这几条：

```text
quant> stock-basic --force
quant> daily-basic --start 20260601 --end 20260618
quant> download
quant> backtest --strategy multi_timeframe_volume_trend --pool 机器人
quant> stats theme --pool 机器人 --start 20260601 --end 20260619
quant> report --strategy multi_timeframe_volume_trend
quant> dashboard
```

`stats theme` 会额外生成 `output.statistics_dir/theme_index_{pool}_{start}_{end}.csv`，并在 HTML 题材看板中展示等权概念指数 K 线。概念 K 线支持日线、周线、月线切换；指标区域可在成交量、成交金额、涨跌家数、趋势广度之间切换，并与 K 线缩放联动。概念 K 线使用股票缓存完整区间，个股涨跌排行按 `--start/--end` 展示涨幅前 7 和跌幅后 5，并在标题旁标注统计区间。明细和看板会额外展示 MA20/MA60 上方占比、20 日新高/新低、个股离散度、年化波动率、收益/回撤比、距均线和 20 日量能等本地缓存派生指标。

## 11. 验证和文档

改完代码后常用验证：

```bash
python -m unittest discover -s tests
python -m compileall main.py cli data engine strategy visual analysis tests
```

常看文档：

```text
README.md
TECHNICAL.md
AGENTS.md
docs/reference/contracts.md
docs/plans/completed/REFACTOR_PLAN.md
```

当前结构优化已经第一轮收敛，后续优先围绕下载稳定性、题材分析和策略规则做小步迭代。
