# ETF 策略集成交付说明

更新日期：2026-08-07

## 迁移范围

已按 `/Users/caleb/projects/codex_prj/QTYX_352/docs/ETF_STRATEGY_INTEGRATION_GUIDE.md` 将 ETF 策略能力集成到当前项目的 `etf_strategy/` 模块，保留当前项目“研究报告与正式交易链路隔离”的约束。

- 数据层：`EtfDataProvider` 支持 ETF 日线、分钟线，日线统一为 `Open / High / Low / Close / Volume`，本地缓存优先，Tushare/Sina 兜底。
- 外部信号：`ExternalSignalProvider` 支持本地 CSV 和 QTYX_352 公共 FTP 下载，兼容红绿灯与排名情绪文件。
- 策略层：已迁移 MACD、双 KAMA、布林带、N 日突破、ATR 止盈止损、动量轮动、三因子轮动。
- 抄作业策略：已实现指数红绿灯通行、三因子排名轮动抄作业的解析与原因输出。
- 执行层：提供 `Broker` 协议、`DryRunBroker` 和 `OrderIntent`，默认只生成模拟交易意图，不连接 QMT、不真实下单。
- 报告层：`python main.py etf report` 输出独立 ETF 策略研究 HTML 和 CSV，并接入 dashboard。

## 配置

当前项目已在 `config.yaml` 的 `etf_strategy` 下迁移公共 FTP 配置：

```yaml
external_signal_dir: "/Volumes/extend/quant_yb_data/meta/etf_external_signals"
ftp:
  enabled: true
  auto_download: true
  server: "101.132.65.156"
  port: 21
  username: "QuantTraderYX"
  password: ""  # 推荐通过 QUANTYB_ETF_FTP_PASSWORD 提供
  encoding: "GB2312"
  remote_root: "/每日选股结果分享"
  red_green_remote_dir: "ETF红绿灯信号"
  rank_emotion_remote_dir: "红绿灯排名与情绪"
```

示例配置不再保存 FTP 密码，默认 `enabled: false`、`auto_download: false`。需要刷新外部信号时，在本机设置 `QUANTYB_ETF_FTP_PASSWORD`；也可完全禁用 FTP，只读取 `external_signal_dir` 下的本地 CSV。

交易参数已迁移：

- `rank_top_n: 10`
- `buy_amount: 1000000`
- `smash_sell_pct: 10`
- `blacklist_amounts`
- `trend_position_pct`

## 使用命令

刷新并验算外部信号：

```bash
python main.py etf signals --refresh --symbol 515880.SH --top-n 10
```

生成 ETF 策略研究报告：

```bash
python main.py etf report --start 2026-01-01 --end 2026-08-06
```

输出位置：

- ETF 报告：`/Volumes/extend/quant_yb_data/output/reports/etf_strategy/etf_strategy_dashboard.html`
- ETF 汇总：`/Volumes/extend/quant_yb_data/output/statistics/etf_strategy/etf_strategy_summary.csv`
- 外部红绿灯：`/Volumes/extend/quant_yb_data/meta/etf_external_signals/指数通行红绿灯.csv`
- 外部排名情绪：`/Volumes/extend/quant_yb_data/meta/etf_external_signals/指数通行红绿灯带排名和情绪.csv`

## 验收结果

已运行：

```bash
/Users/caleb/miniforge3/envs/quant_yb/bin/python -m unittest tests.test_etf_strategy
/Users/caleb/miniforge3/envs/quant_yb/bin/python -m compileall main.py cli data engine strategy visual analysis etf_strategy tests
/Users/caleb/miniforge3/envs/quant_yb/bin/python main.py etf signals --refresh --symbol 515880.SH --top-n 10
/Users/caleb/miniforge3/envs/quant_yb/bin/python main.py etf report --start 2026-01-01 --end 2026-08-06
```

结果：

- `tests.test_etf_strategy`：8 项通过。
- `compileall`：通过。
- 公共 FTP：实际下载成功，红绿灯输出 `515880.SH: hold / 无触发`，外部排名解析前 10 条。
- ETF 报告：生成成功，汇总 CSV 包含 16 只 ETF。

## 指南验收点对应

1. ETF 日线：测试验证 `515880.SH` 可从缓存读出标准 OHLCV，index 为 `DatetimeIndex`。
2. 单 ETF 择时：测试验证 MACD 输出最新信号和 `Signal` 列。
3. 动量轮动：测试验证 3 只 ETF 输出 ranking 和各 ETF `Signal` 列，末尾清仓。
4. 三因子轮动：测试验证 5 只 ETF 输出每日综合得分排序，并检查今日信号使用前一日以前数据。
5. 红绿灯：测试覆盖 QTYX 宽表样例，能输出买入/卖出/持有原因。
6. 三因子排名抄作业：测试覆盖前 N、 新入、退出、抢砸、趋势状态解析。
7. 模拟交易：测试覆盖抢砸部分卖出、退出全卖、排名买入、趋势仓位降低；策略仅输出 `OrderIntent`。

## 设计边界

- 本次没有接入真实 QMT 账号、路径或下单动作。
- `Broker` 是协议层，真实交易适配器应另建本地安全配置后接入。
- 当前 ETF 报告属于研究输出，不改变股票回测、正式策略、仓位、订单或市场风险闸门。
