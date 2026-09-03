# 每日自动化运行说明

这份说明用于把“每天更新数据、生成大盘分析、刷新信号和总看板”交给 Codex 或系统定时任务执行。定时任务只做研究输出，不改变回测成交模型、手续费、滑点、涨跌停、T+1 或既有交易流水字段。

## 1. 推荐执行节奏

建议在 A 股收盘并等待数据源更新后执行，优先放在北京时间 18:30 之后。周末和节假日可以不跑；如果定时任务每天都跑，程序通常只会发现没有新交易日或没有新数据，但日志里会多一些无效运行记录。

推荐拆成三类：

- 每日核心任务：行情增量、daily_basic、同花顺行业/概念/风格代理指数、指数概览与指数行情、大盘环境、RPS/形态/选股筛选、强势股雷达、dashboard。
- 每日可选任务：策略买点扫描、指定题材看板。
- 每周或手动任务：股票基础信息强制刷新、指数成分、半年涨停研究、批量回测和批量报告。

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

下面是一条适合定时执行的主流水线。日期用脚本动态生成：

- `TODAY`：当天日期。
- `THEME_START`：最近 60 天，用于题材看板。
- `MEMBER_START`：最近 180 天，用于覆盖至少 60 个交易日的指数成分快照。

```bash
#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/Users/caleb/projects/quant_prj/quant_yb"
PYTHON="/Users/caleb/miniforge3/envs/quant_yb/bin/python"
LOG_DIR="$PROJECT_DIR/output/logs"
REVIEW_TEMPLATE="${REVIEW_TEMPLATE:-/Users/caleb/projects/note/笔记/模版/A股每日复盘模版.md}"
REVIEW_OUTPUT_DIR="${REVIEW_OUTPUT_DIR:-/Users/caleb/projects/note/笔记/A股每日复盘}"
mkdir -p "$LOG_DIR"

TODAY="$("$PYTHON" - <<'PY'
from datetime import datetime
from zoneinfo import ZoneInfo
print(datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d"))
PY
)"

THEME_START="$("$PYTHON" - <<'PY'
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
print((datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(days=60)).strftime("%Y%m%d"))
PY
)"

MEMBER_START="$("$PYTHON" - <<'PY'
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
print((datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(days=180)).strftime("%Y%m%d"))
PY
)"

cd "$PROJECT_DIR"

if [[ -f "$PROJECT_DIR/.env.local" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_DIR/.env.local"
  set +a
fi

PIPELINE="download --start 20110101 --end ${TODAY}; \
daily-basic --start ${TODAY} --end ${TODAY}; \
index ths --start 20110101 --end ${TODAY} --refresh-list --include-concepts --skip-failures; \
index overview --all --start 20110101 --end ${TODAY}; \
index members --all --start ${MEMBER_START} --end ${TODAY}; \
index market --start 20110101 --end ${TODAY}; \
index forecast --symbol 000001.SH --horizon 5 --start 20110101 --end ${TODAY}; \
stats rps --window 120 --top 80; \
stats pattern --pattern main_rise_wave; \
stats pattern --pattern bottom_pattern_break; \
stats pattern --pattern needle_bottom_raise; \
stats screen --preset trendline_pullback --pool 人形机器人,AI --pool-mode any --top 80; \
stats theme --pool 人形机器人 --start ${THEME_START} --end ${TODAY}; \
stats theme --pool AI --start ${THEME_START} --end ${TODAY}; \
stats theme --pool 创新药 --start ${THEME_START} --end ${TODAY}; \
stats radar --top 300; \
data-audit; \
dashboard"

printf "y\ny\n" | "$PYTHON" main.py run "$PIPELINE" 2>&1 | tee "$LOG_DIR/daily_${TODAY}.log"
"$PYTHON" scripts/verify_daily_market_structure.py \
  --symbol 000001.SH \
  --horizon 5 2>&1 | tee -a "$LOG_DIR/daily_${TODAY}.log"
"$PYTHON" scripts/verify_daily_market_data.py \
  --strict \
  --max-lag-calendar-days 4 2>&1 | tee -a "$LOG_DIR/daily_${TODAY}.log"
"$PYTHON" main.py review daily \
  --template "$REVIEW_TEMPLATE" \
  --output-dir "$REVIEW_OUTPUT_DIR" 2>&1 | tee -a "$LOG_DIR/daily_${TODAY}.log"
```

最后一步是只读验收，不会下载数据或调用大模型。它从最新市场结构 JSON
读取实际交易数据日期，并检查该日期目录下的市场结构 HTML/JSON、DeepSeek
总结 Markdown/HTML、归档清单和 SHA256。任一流水线命令失败、LLM 调用未成功、
归档缺失或文件校验失败，脚本都会以非零退出码结束，使 launchd 不再把失败任务
记录成成功。周末或节假日仍按最近交易数据日期验收，不使用自然日伪造归档日期。
`.env.local` 只用于向子进程提供 `DEEPSEEK_API_KEY` 等本机密钥；脚本和日志不会打印
密钥值。指数成分快照每天增量刷新，用于 v2 分层广度的时点口径。

验收通过后，脚本会继续生成一份事实填充版 A 股每日复盘 Markdown。复盘命令不传
自然日 `TODAY`，而是读取最新市场结构 JSON 的实际交易日期，避免周末、节假日或
数据源延迟时误用非交易日。默认输出到：

```text
/Users/caleb/projects/note/笔记/A股每日复盘/YYYY-MM-DD 股票复盘.md
```

如需临时改模板或输出目录，可在运行脚本前覆盖环境变量：

```bash
REVIEW_TEMPLATE=/path/to/template.md REVIEW_OUTPUT_DIR=/path/to/reviews bash scripts/daily_quant_job.sh
```

每日市场结构与大模型复盘按实际交易数据日期归档，例如：

```text
/Volumes/extend/quant_yb_data/output/reports/index_forecast/archive/market_structure_v2/2026-07-15/
000001.SH_h5_2026-07-15_market_structure.html
000001.SH_h5_2026-07-15_market_structure.json
000001.SH_h5_2026-07-15_llm_summary.md
000001.SH_h5_2026-07-15_llm_summary.html
000001.SH_h5_2026-07-15_archive_manifest.json
```

核心输出：

```text
/Volumes/extend/quant_yb_data/output/reports/dashboard.html
/Volumes/extend/quant_yb_data/output/reports/market_overview.html
/Volumes/extend/quant_yb_data/output/reports/index/
/Volumes/extend/quant_yb_data/output/reports/index_forecast/
/Volumes/extend/quant_yb_data/output/signals/
/Volumes/extend/quant_yb_data/output/statistics/
```

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
  <dict>
    <key>Hour</key>
    <integer>18</integer>
    <key>Minute</key>
    <integer>40</integer>
  </dict>

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
每天 18:40 执行该脚本；如果 Mac 系统时区不是 Asia/Shanghai，请先换算成本地时间。
不要把 Tushare token 写入脚本或日志；只使用项目 config.yaml。
创建后用 launchctl load 和 launchctl start 测试一次，
最后告诉我 dashboard.html、market_overview.html 和日志文件路径。
```

## 7. 日常检查

每次自动任务跑完，优先看这几个文件：

```text
/Volumes/extend/quant_yb_data/output/reports/dashboard.html
/Volumes/extend/quant_yb_data/output/reports/market_overview.html
/Users/caleb/projects/quant_prj/quant_yb/output/logs/daily_YYYYMMDD.log
```

如果失败：

- 先看 `output/logs/daily_YYYYMMDD.log`。
- 如果是下载失败，按程序打印的 `download --failed-file ...` 补下载命令重跑。
- 如果是 Tushare 限流，晚一点重跑同一条脚本。
- 如果是股票池名称不存在，检查 `/Volumes/extend/quant_yb_data/meta/stock_pools.json`。
