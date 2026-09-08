#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/Users/caleb/projects/quant_prj/quant_yb"
PYTHON="/Users/caleb/miniforge3/envs/quant_yb/bin/python"
LOG_DIR="$PROJECT_DIR/output/logs"
mkdir -p "$LOG_DIR"
cd "$PROJECT_DIR"

if [[ -f "$PROJECT_DIR/.env.local" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_DIR/.env.local"
  set +a
fi

TODAY="$("$PYTHON" - <<'PY'
from datetime import datetime
from zoneinfo import ZoneInfo
print(datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d"))
PY
)"

AS_OF="${QUANT_YB_AS_OF_DATE:-$("$PYTHON" - <<'PY'
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from cli.common import load_config
from data.downloader import DataDownloader

now = datetime.now(ZoneInfo("Asia/Shanghai"))
calendar_end = now if now.hour >= 18 else now - timedelta(days=1)
end = calendar_end.strftime("%Y%m%d")
start = (calendar_end - timedelta(days=20)).strftime("%Y%m%d")
dates = DataDownloader(load_config())._trade_dates(start, end)
if not dates:
    raise SystemExit("无法确定最近已完成交易日")
print(dates[-1])
PY
)}"

DATA_START="$(AS_OF_DATE="$AS_OF" "$PYTHON" - <<'PY'
from datetime import datetime, timedelta
import os
as_of = datetime.strptime(os.environ["AS_OF_DATE"], "%Y%m%d")
print((as_of - timedelta(days=45)).strftime("%Y%m%d"))
PY
)"

MEMBER_START="$(AS_OF_DATE="$AS_OF" "$PYTHON" - <<'PY'
from datetime import datetime, timedelta
import os
as_of = datetime.strptime(os.environ["AS_OF_DATE"], "%Y%m%d")
print((as_of - timedelta(days=180)).strftime("%Y%m%d"))
PY
)"

echo "每日数据目标交易日: ${AS_OF}（运行日 ${TODAY}）" | tee "$LOG_DIR/daily_${TODAY}.log"

if [[ "${QUANT_YB_FORCE_DAILY:-0}" != "1" ]] && \
  "$PYTHON" scripts/verify_daily_market_data.py \
    --strict \
    --expected-date "$AS_OF" \
    --max-lag-calendar-days 4 >> "$LOG_DIR/daily_${TODAY}.log" 2>&1; then
  echo "目标交易日 ${AS_OF} 的基础行情和核心报告均已完成，跳过重复更新。" | tee -a "$LOG_DIR/daily_${TODAY}.log"
  exit 0
fi

PIPELINE="download --start ${DATA_START} --end ${AS_OF}; \
daily-basic --start ${DATA_START} --end ${AS_OF}; \
stats stock-kline-pages --workers 5 --strict; \
index ths --start ${DATA_START} --end ${AS_OF} --include-concepts --skip-failures; \
index download --symbol 399001.SZ --start ${DATA_START} --end ${AS_OF}; \
index download --symbol 399006.SZ --start ${DATA_START} --end ${AS_OF}; \
index download --symbol 000688.SH --start ${DATA_START} --end ${AS_OF}; \
index download --symbol 000300.SH --start ${DATA_START} --end ${AS_OF}; \
index download --symbol 000016.SH --start ${DATA_START} --end ${AS_OF}; \
index download --symbol 000905.SH --start ${DATA_START} --end ${AS_OF}; \
index download --symbol 000852.SH --start ${DATA_START} --end ${AS_OF}; \
index download --symbol 932000.CSI --start ${DATA_START} --end ${AS_OF}; \
index members --all --start ${MEMBER_START} --end ${AS_OF}; \
index forecast --symbol 000001.SH --horizon 5 --start 20110101 --end ${AS_OF}; \
index structure-brief --symbol 000001.SH --horizon 5; \
index industry-market --symbol 000001.SH; \
stats radar --top 300; \
stats vpt --trade-date ${AS_OF} --top 100; \
data-audit; \
dashboard"

printf "y\ny\n" | "$PYTHON" main.py run "$PIPELINE" 2>&1 | tee -a "$LOG_DIR/daily_${TODAY}.log"
"$PYTHON" scripts/verify_daily_market_structure.py \
  --symbol 000001.SH \
  --horizon 5 2>&1 | tee -a "$LOG_DIR/daily_${TODAY}.log"
"$PYTHON" scripts/verify_daily_market_data.py \
  --strict \
  --expected-date "$AS_OF" \
  --max-lag-calendar-days 4 2>&1 | tee -a "$LOG_DIR/daily_${TODAY}.log"
