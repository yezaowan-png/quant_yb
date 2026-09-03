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
# 60个交易日通常超过80个自然日；保留180天可覆盖节假日和低频成分快照。
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
"$PYTHON" main.py stats limit-up-candidates --as-of-date "$TODAY" 2>&1 | tee -a "$LOG_DIR/daily_${TODAY}.log"
LIMIT_CANDIDATES="$($PYTHON - <<'PY'
from pathlib import Path
from project_config import load_project_config
config = load_project_config()
print(Path(config["output"].get("statistics_dir", "output/statistics")) / "limit_up_candidates_latest.csv")
PY
)"
LIMIT_AS_OF="$($PYTHON - <<'PY'
import json
from pathlib import Path
from project_config import load_project_config
config = load_project_config()
path = Path(config["output"].get("statistics_dir", "output/statistics")) / "limit_up_candidates_status.json"
print(json.loads(path.read_text(encoding="utf-8"))["as_of_date"])
PY
)"
"$PYTHON" main.py stats theme-pool batch \
  --candidates "$LIMIT_CANDIDATES" --as-of-date "$LIMIT_AS_OF" \
  --output-dir "$(dirname "$LIMIT_CANDIDATES")/theme_classification_batches" 2>&1 | tee -a "$LOG_DIR/daily_${TODAY}.log"
"$PYTHON" scripts/verify_daily_market_structure.py \
  --symbol 000001.SH \
  --horizon 5 2>&1 | tee -a "$LOG_DIR/daily_${TODAY}.log"
"$PYTHON" scripts/verify_daily_market_data.py \
  --strict \
  --max-lag-calendar-days 4 2>&1 | tee -a "$LOG_DIR/daily_${TODAY}.log"
"$PYTHON" main.py review daily \
  --template "$REVIEW_TEMPLATE" \
  --output-dir "$REVIEW_OUTPUT_DIR" 2>&1 | tee -a "$LOG_DIR/daily_${TODAY}.log"
