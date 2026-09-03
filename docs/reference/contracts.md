# 当前行为契约

本文件记录结构优化期间必须保持兼容的外部行为。除非单独提出需求，否则重构不得修改这些契约。

## 命令入口

- 交互模式：`python main.py`，提示符为 `quant>`。
- 直接下载：`python main.py data download ...`。
- 数据质量：`python main.py data audit [--deep]`；REPL 对应 `data-audit`。
- 回测：`python main.py backtest run ...`。
- 报告：`python main.py backtest report ...`。
- 手动画线：`python main.py backtest trendlines --symbol ...`。
- 统计：`python main.py stats analyze|compare|theme|rps|rps-track|pattern|screen|rotation|limit-board|limit-research|limit-strength|support-resistance ...`。
- 指数：`python main.py index download|report|overview|market|forecast|forecast-diagnose ...`。
- ETF 策略研究：`python main.py etf report ...`，只生成 ETF 信号、排名和报告，不直接下单。
- 极端风险研究：`python main.py market risk-state|risk-labels|risk-diagnose|risk-matrix|risk-report ...`，与正式环境信号和策略仓位隔离。
- 总面板：`python main.py dashboard`，生成本地研究工作台，不重新运行回测。
- 流水线：`python main.py run "command; command"`。

REPL 中的短命令必须与直接命令保持相同业务行为。

## 数据目录

- 股票 K 线：`data.cache_dir/{ts_code}.csv`。
- 指数 K 线：`data.cache_dir/index/{ts_code}.csv`。
- ETF K 线：`etf_strategy.cache_dir/{ts_code}.csv`，没有配置时默认位于 `data.cache_dir/etf/`。
- 股票基础信息：`data.meta_dir/stocks.csv`。
- 股票名称映射：`data.meta_dir/stock_names.csv`。
- 每日指标：`data.meta_dir/daily_basic/{ts_code}.csv`。
- 已检查交易日：`data.meta_dir/kline_checked_dates.csv`。
- 题材股票池：`stock_pool.path`。

所有实际路径必须从 `config.yaml` 读取，不得在业务模块中硬编码本机绝对路径。

## 股票 K 线口径

- 默认复权方式由 `data.stock_adj` 控制，当前推荐值为 `qfq`。
- K 线至少包含 `date,open,high,low,close,volume,amount`。
- 增量更新按日期合并，重复日期必须去重并以新数据覆盖旧数据。
- 复权因子变化时必须保证历史价格与新增价格处于同一口径。

## 回测约束

- 策略信号只能使用当前 bar 及之前的数据。
- 周线过滤只能使用已完成周线。
- A 股手续费、印花税、最低佣金、滑点、涨跌停、T+1 和成交量限制由现有配置、`BaseStrategy` 和执行经纪层共同处理。卖出印花税默认按成交日期在 2023-08-28 从 0.1% 切换为 0.05%；可关闭 `date_aware_stamp_duty` 使用固定税率。
- `board_aware_price_limits=true` 时，常规涨跌停按代码与日期识别：主板 10%，科创板 20%，创业板自 2020-08-24 起 20%，北交所 30%；`limit_pct` 只作未知代码和创业板改革前的兜底。限制会在信号日和次日实际开盘成交时分别检查。新股无涨跌幅窗口及历史 ST 时点状态尚未自动建模。
- 重构不得改变默认成交价格和订单成交回调记录口径。

## 输出文件

- 交易流水：`output.trades_dir/{symbol}_{strategy}.csv`。
- 权益曲线：`output.trades_dir/{symbol}_{strategy}_equity.csv`。
- 批量汇总：`output.trades_dir/_summary_{strategy}.csv`。
- 买点扫描：`output.signals_dir/buy_signals_{strategy}_{date}.csv`。
- 单标的报告：`output.reports_dir/{symbol}_{strategy}.html`。
- 股票 K 线页面：`output.reports_dir/stock_kline/{symbol}.html`，集成日/周/月 K、技术指标与手动画线工具。
- 策略统计：`output.statistics_dir/analysis_{strategy}.html`。
- 题材明细：`output.statistics_dir/theme_{pool}_{start}_{end}.csv`。
- 题材摘要：`output.statistics_dir/theme_{pool}_{start}_{end}_summary.csv`。
- 题材看板：`output.statistics_dir/theme_{pool}_{start}_{end}.html`。
- RPS 排行：`output.statistics_dir/rps_top_{date}_w{window}.csv` 和同名 `.html`。
- 个股 RPS 轨迹：`output.statistics_dir/rps_track_{symbol}_{window}.csv` 和同名 `.html`。
- 形态扫描：`output.signals_dir/pattern_signals_{pattern}_{date}.csv` 和同名 `.html`。
- 通用选股筛选：`output.signals_dir/screen_signals_{preset}[_pool]_{date}.csv` 和同名 `.html`。
- 轮动研究：`output.statistics_dir/rotation_{model}_{pool}_{start}_{end}_nav.csv`、`*_holdings.csv` 和同名 `.html`。
- 涨跌停看板：`output.statistics_dir/limit_board_{date}.csv`、`*_industry.csv`、`*_concepts.csv` 和同名 `.html`。
- 半年涨停研究：`output.statistics_dir/limit_up_research_{start}_{end}_detail.csv`、`*_stocks.csv`、`*_themes.csv`、`*_fundamentals.csv`，研究文档保存到 `docs/research/limit_up_research_{start}_{end}.md`，细分股票池写入 `stock_pool.path` 的 `半年涨停_*_{start}_{end}`。
- 支撑压力共振：`support_resistance.output_dir/{symbol}_{start}_{end}_support_resistance.html`；默认目录为 `output.reports_dir/support_resistance/`，复权、均线周期和共振阈值分别由 `support_resistance.adjust`、`ma_periods`、`resonance_threshold_pct` 控制。报告只作技术结构观察，不参与正式策略、仓位或订单。
- ETF 策略板块：`output.reports_dir/etf_strategy/etf_strategy_dashboard.html`，展示 ETF 择时信号、动量轮动、三因子轮动、外部红绿灯/排名解析状态；只作研究展示，不参与正式交易、仓位或订单。
- ETF 策略统计：`output.statistics_dir/etf_strategy/etf_strategy_summary.csv`、`etf_strategy_timing_signals.csv`、`etf_strategy_momentum_ranking.csv`、`etf_strategy_three_factor_ranking.csv`。
- 指数概览：`output.reports_dir/index/{symbol}_overview.html`。
- 大盘环境看板：`output.reports_dir/market_overview.html`。
- 市场环境预测报告：`output.reports_dir/index_forecast/{symbol}_h{1|5|10|20}.html`。
- 市场环境指标：`output.statistics_dir/index_forecast/indicators_{symbol}.csv`，只含当日及以前可知特征。
- 市场环境标签：`output.statistics_dir/index_forecast/features_{symbol}.csv`，包含未来 1/5/10/20 日横截面结果、滚动得分和环境标签。
- 市场环境预测：`output.statistics_dir/index_forecast/predictions_{symbol}_h{horizon}.csv`。
- 极端风险研究：`output.statistics_dir/market_risk_gate/{symbol}/`，每个实验保存到独立的 `experiments/{experiment}/` 子目录。
- 极端风险报告：`output.reports_dir/market_risk_gate/{symbol}_{experiment}_risk_gate.html`；矩阵汇总为 `{symbol}_risk_gate.html`。
- 总面板：`output.reports_dir/dashboard.html`，展示市场状态、信号流、指数、题材、ETF、策略和最近单标的报告入口，并提供市场结构摘录版导航。
- 数据质量报告：`output.reports_dir/data_quality.html`；机器可读摘要和问题明细分别为 `output.statistics_dir/data_quality/market_data_audit.json`、`market_data_issues.csv`。默认快速模式只证明全部文件的字段和末尾记录通过检查，完整历史逐行检查必须显式使用 `--deep`。
- 市场结构摘录版：`output.reports_dir/index_forecast/{symbol}_market_structure_brief.html`，从市场结构 JSON 事实层和本地指数/行业缓存生成第 2-5 屏：指数趋势与技术结构、分层市场广度、横截面收益分布、风格轮动/领涨质量/行业结构；可通过 `python main.py index structure-brief` 单独生成，不要求完整九屏 HTML 已存在；只作解释展示，不参与策略、仓位或订单。
- 行业行情页：`output.reports_dir/industry/industry_market.html`，从市场结构 JSON 事实层和本地同花顺行业指数缓存生成全行业强弱表、可点击表头排序，并提供行业指数 K 线入口；右侧成分股优先读取 `data.meta_dir/ths_members/{行业指数}.csv` 的 Tushare `ths_member` 官方同花顺成分，缺失时再用 `dashboard.stock_selector.csv_path` 股票池行业标签近似匹配，价格和日涨跌幅优先使用本地日线缓存计算；由 dashboard 自动生成，只作解释展示，不参与策略、仓位或订单。

## 交易流水字段

交易流水字段保持：

```text
date,symbol,direction,price,size,commission,pnl
```

允许新增向后兼容的辅助文件，但不得无提示地重命名或删除现有字段。

## 市场环境标签约束

- 主标签必须使用有效股票池的未来收益横截面和尾部风险；市值加权指数未来收益只作辅助指标，主标签权重不超过 15%，当前为 0%。
- 支持的预测周期固定为 1、5、10、20 个交易日。
- 历史分位数只能使用评分日当时已经走完整个未来窗口的样本，不得使用尚未完成的标签或全样本分位数。
- 环境标签为 `positive / neutral / conservative`；`risk_score >= 80` 必须否决积极标签。
- 预测特征只能读取当日及以前的数据；未来横截面字段只能用于训练、验证和报告复盘。

## 极端风险闸门约束

- `market_risk_gate` 不读取或修改正式环境标签、策略信号、订单和仓位；第一阶段只生成研究结果与模拟政策。
- 当前状态只能使用 T 日及以前数据；R1-R5 的未来标签阈值必须在每个训练窗口内计算并冻结。
- walk-forward 固定使用扩展训练、`purge=H`、63 日验证、`embargo=H`、63 日测试。
- `balanced` 类别权重或无效校准结果只能称为 `risk_score`；只有自然类别概率或严格时间外有效校准才能称为 `risk_probability`。
- 自动结论只允许 `continue_risk_gate_research`、`stop_future_risk_prediction_use_state_monitor_only`、`eligible_for_strategy_validation`，不得据此自动接入正式仓位。
- 报告必须保留历史退市股、历史 ST 和 point-in-time 股票池不完整的数据质量提示。

## 验证基线

每个重构阶段至少运行：

```bash
python -m unittest discover -s tests
python -m compileall main.py cli data engine strategy visual analysis tests
```

涉及回测共享逻辑时，再运行单标的验证：

```bash
python main.py backtest run --strategy multi_timeframe_volume_trend --symbol 000001.SZ
```
