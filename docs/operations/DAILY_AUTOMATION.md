# 每日自动化运行说明

这份说明用于把“每天更新数据、生成大盘分析、刷新信号和总看板”交给 Codex 或系统定时任务执行。定时任务只做研究输出，不改变回测成交模型、手续费、滑点、涨跌停、T+1 或既有交易流水字段。

## 1. 推荐执行节奏

建议在 A 股收盘并等待数据源更新后执行，优先放在北京时间 20:30 之后。同花顺行业/概念日线通常晚于个股日线可用，过早执行可能出现个股已更新但板块仍停在上一交易日。周末和节假日可以不跑；如果定时任务每天都跑，完整性预检会在目标交易日已经产出时直接结束。

推荐拆成三类：

- 每日核心任务：基础行情、daily_basic、必要指数成分、同花顺行业/概念、市场结构摘录、强势股雷达、VPT 策略选股和 dashboard。
- 每日可选任务：其它策略买点扫描、指定题材看板。
- 每周或手动任务：股票基础信息强制刷新、同花顺指数列表刷新、半年涨停研究、主题分类、形态研究、批量回测和批量报告。

## 2. 当前项目环境

本机项目路径：

```bash
/Users/caleb/projects/quant_prj/quant_yb
```

推荐 Python：

```bash
/Users/caleb/miniforge3/envs/quant_yb/bin/python
```

当前配置里的主要数据目录：

```text
data.cache_dir      /Volumes/extend/quant_yb_data/cache
data.meta_dir       /Volumes/extend/quant_yb_data/meta
stock_pool.path     /Volumes/extend/quant_yb_data/meta/stock_pools.json
output.reports_dir  /Volumes/extend/quant_yb_data/output/reports
output.signals_dir  /Volumes/extend/quant_yb_data/output/signals
```

注意：`download` 下载全市场时会有确认提示，自动化脚本需要给它传入确认输入；下面脚本使用 `printf "y\ny\n"`，分别确认“下载全部股票”和“使用交易日增量下载”。

## 3. 每日核心流水线

每日任务以 Dashboard 的主产品边界为准：基础行情与必要元数据、市场结构摘录、
行业行情（含概念/关注/指数/个股视图）、强势股雷达、VPT 策略选股和 Dashboard。
形态研究、题材统计、涨停候选与分类批次改为手动或低频任务。

脚本会通过交易日历确定 `AS_OF`，盘中、周末和节假日使用最近已完成交易日；股票和
同花顺指数只扫描最近 45 个自然日的尾部缺口，既有历史缓存不截断。指数成分保留
180 天增量窗口。宽基行情只更新市场结构实际使用且数据源可用的指数缓存，不在每日任务中重写
独立指数概览 HTML；已知不可用的 `000985.SH` 保留历史缓存，但不再每天等待失败重试。

```bash
bash scripts/daily_quant_job.sh

# 仅用于补跑指定交易日
QUANT_YB_AS_OF_DATE=20260904 bash scripts/daily_quant_job.sh

# 目标交易日已经完整产出时仍强制重跑
QUANT_YB_FORCE_DAILY=1 bash scripts/daily_quant_job.sh
```

`index forecast` 更新事实层后，流水线会依次重建市场结构摘录和行业行情页，
避免轻量 `dashboard` 只刷新导航壳而遗留旧报告。最后一步是只读验收，不会下载数据
或调用大模型。它从最新市场结构 JSON
读取实际交易数据日期，并检查该日期目录下的市场结构 HTML/JSON、归档清单和
SHA256，并核对市场结构摘录、行业行情、强势股雷达和 VPT 策略页的“数据截至”日期。任一流水线命令失败、归档缺失、
报告日期落后或文件校验失败，脚本都会以非零退出码结束，
使 launchd 不再把失败任务记录成成功。周末或节假日仍按最近交易数据日期验收，
不使用自然日伪造归档日期。若目标交易日的基础行情和四个核心报告均已完整产出，重复触发会
直接结束；可用 `QUANT_YB_FORCE_DAILY=1` 强制重跑。每日流程不调用 LLM；如需大模型复盘，使用手动
`python main.py index llm-summary`。指数成分快照每天增量刷新，用于 v2 分层广度的时点口径。

每日任务不调用 LLM，也不生成自动复盘。需要人工研究时，应单独运行相应研究命令，
不得让其结果影响每日行情更新或验收状态。

每日市场结构按实际交易数据日期归档，例如：

```text
/Volumes/extend/quant_yb_data/output/reports/index_forecast/archive/market_structure_v2/2026-07-15/
000001.SH_h5_2026-07-15_market_structure.html
000001.SH_h5_2026-07-15_market_structure.json
000001.SH_h5_2026-07-15_archive_manifest.json
```

核心输出：

```text
/Volumes/extend/quant_yb_data/output/reports/dashboard.html
/Volumes/extend/quant_yb_data/output/reports/index_forecast/000001.SH_market_structure_brief.html
/Volumes/extend/quant_yb_data/output/reports/industry/industry_market.html
/Volumes/extend/quant_yb_data/output/reports/strong_stock_radar/strong_stock_radar.html
/Volumes/extend/quant_yb_data/output/reports/vpt/vpt_candidates.html
```

性能口径：旧流水线按 `20110101` 扫描全部股票并串行更新同花顺指数。改为 45 个自然日尾部扫描、
5 路同花顺指数并发后，在本地缓存已覆盖目标交易日的实测中，全市场股票检查由约 54 分钟降至
约 55 秒，1,164 个同花顺指数检查由约 59 分钟降至约 11 秒。遇到真实缺口时耗时仍取决于缺失
交易日数量、接口响应和统一限流器，不以这组无缺口数据冒充下载速度。

## 4. 每周或手动补充任务

这些任务耗时或调用接口更多，建议每周跑一次，或者让 Codex 手动触发。

```bash
# 更新股票基础信息和名称映射
/Users/caleb/miniforge3/envs/quant_yb/bin/python main.py data stock-basic --force

# 更新主要宽基指数成分，用于分层广度
/Users/caleb/miniforge3/envs/quant_yb/bin/python main.py index members --all --start 20260701 --end 20260706

# 最近半年涨停研究，可能调用更多 Tushare/概念成员接口
/Users/caleb/miniforge3/envs/quant_yb/bin/python main.py stats limit-research --months 6 --min-limit-count 1 --fundamental-top 120
```

策略研究如果需要每日跑，可以单独放一个晚间任务，避免和数据更新混在一起：

```bash
/Users/caleb/miniforge3/envs/quant_yb/bin/python main.py run "scan --strategy multi_timeframe_volume_trend --days 5; report --strategy multi_timeframe_volume_trend; stats analyze --strategy multi_timeframe_volume_trend; dashboard"
```

## 5. launchd 定时任务模板

如果让 Codex 创建 macOS 定时任务，建议先让它生成脚本：

```text
/Users/caleb/projects/quant_prj/quant_yb/scripts/daily_quant_job.sh
```

脚本内容可直接使用第 3 节模板。然后创建 plist：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.caleb.quant-yb.daily</string>

  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>/Users/caleb/projects/quant_prj/quant_yb/scripts/daily_quant_job.sh</string>
  </array>

  <key>StartCalendarInterval</key>
  <array>
    <dict>
      <key>Hour</key>
      <integer>20</integer>
      <key>Minute</key>
      <integer>30</integer>
    </dict>
    <dict>
      <key>Hour</key>
      <integer>22</integer>
      <key>Minute</key>
      <integer>30</integer>
    </dict>
  </array>

  <key>WorkingDirectory</key>
  <string>/Users/caleb/projects/quant_prj/quant_yb</string>

  <key>StandardOutPath</key>
  <string>/Users/caleb/projects/quant_prj/quant_yb/output/logs/launchd_daily.out</string>
  <key>StandardErrorPath</key>
  <string>/Users/caleb/projects/quant_prj/quant_yb/output/logs/launchd_daily.err</string>

  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
```

推荐保存到：

```text
~/Library/LaunchAgents/com.caleb.quant-yb.daily.plist
```

注意：`StartCalendarInterval` 按 Mac 当前系统时区触发，不会自动理解“北京时间”。如果 Mac 系统时区不是 Asia/Shanghai，请把 `Hour/Minute` 换算成本地时间，或把执行时间设得更晚一些，确保已过 A 股收盘和数据源更新时间。

加载和测试：

```bash
launchctl load ~/Library/LaunchAgents/com.caleb.quant-yb.daily.plist
launchctl start com.caleb.quant-yb.daily
launchctl list | grep quant-yb
```

停用：

```bash
launchctl unload ~/Library/LaunchAgents/com.caleb.quant-yb.daily.plist
```

## 6. 给 Codex 的任务提示

可以把下面这段直接发给 Codex，让它代你落地定时任务：

```text
请在 /Users/caleb/projects/quant_prj/quant_yb 中创建 scripts/daily_quant_job.sh，
内容按 docs/operations/DAILY_AUTOMATION.md 第 3 节的每日核心流水线实现。
使用 /Users/caleb/miniforge3/envs/quant_yb/bin/python。
脚本要 set -euo pipefail，日志写到 output/logs/daily_YYYYMMDD.log。
然后创建 ~/Library/LaunchAgents/com.caleb.quant-yb.daily.plist，
每天 20:30 执行主任务，22:30 再做一次兜底触发；如果主任务已经完整成功，兜底任务会在预检后直接退出。如果 Mac 系统时区不是 Asia/Shanghai，请先换算成本地时间。
不要把 Tushare token 写入脚本或日志；只使用项目 config.yaml。
创建后用 launchctl load 和 launchctl start 测试一次，
最后告诉我 dashboard.html、market_overview.html 和日志文件路径。
```

## 7. 日常检查

每次自动任务跑完，优先看这几个文件：

```text
/Volumes/extend/quant_yb_data/output/reports/dashboard.html
/Volumes/extend/quant_yb_data/output/reports/index_forecast/000001.SH_market_structure_brief.html
/Volumes/extend/quant_yb_data/output/reports/industry/industry_market.html
/Volumes/extend/quant_yb_data/output/reports/strong_stock_radar/strong_stock_radar.html
/Volumes/extend/quant_yb_data/output/reports/vpt/vpt_candidates.html
/Users/caleb/projects/quant_prj/quant_yb/output/logs/daily_YYYYMMDD.log
```

如果失败：

- 先看 `output/logs/daily_YYYYMMDD.log`。
- 如果是下载失败，按程序打印的 `download --failed-file ...` 补下载命令重跑。
- 如果是 Tushare 限流，晚一点重跑同一条脚本。
- 如果是股票池名称不存在，检查 `/Volumes/extend/quant_yb_data/meta/stock_pools.json`。
