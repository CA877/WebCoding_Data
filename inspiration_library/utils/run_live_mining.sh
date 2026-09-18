#!/usr/bin/env bash
# 在物理机上跑「AI 自由访问网页」的 live 挖掘：真浏览器打开 URL，模型自己规划点击路径，
# 产出 capability_pool.jsonl。不是轨迹回放，是现场浏览。
#
# 用法：
#   bash inspiration_library/utils/run_live_mining.sh <sources.jsonl> <run_dir> [rounds] [max_paths] [max_actions]
#
# 例（最小单元，1 个 URL，默认视野）：
#   bash inspiration_library/utils/run_live_mining.sh \
#       configs/live_url_capability_sources/mode_url_20260908.jsonl \
#       runs/live_mining/smoke_url_20260915 1 10 6
#
# STAGE=scan 时只开浏览器探一遍（报控件数、文本量、控制台错误），不调 LLM、零成本，
# 用来在放量前筛掉被封禁或空白的目标站：
#   STAGE=scan bash inspiration_library/utils/run_live_mining.sh <sources.jsonl> <run_dir>
#
# 只想跑清单里的某几条时，把额外参数放进 EXTRA_ARGS（会被原样透传给挖掘脚本）：
#   EXTRA_ARGS="--seed-id accor_booking" bash inspiration_library/utils/run_live_mining.sh <sources.jsonl> <run_dir>
# 不放进 EXTRA_ARGS 的额外参数会被拒绝，而不是被静默忽略——静默忽略会让人以为只跑了一条，
# 实际对着整份清单烧钱。
#
# 环境变量覆盖：VENV REPO BROWSER_PROXY CRED_FILE STAGE EXTRA_ARGS

set -euo pipefail

if [ "$#" -gt 5 ]; then
  echo "too many positional args ($#); extra args go in EXTRA_ARGS, see the header" >&2
  exit 2
fi

SOURCES="${1:?usage: run_live_mining.sh <sources.jsonl> <run_dir> [rounds] [max_paths] [max_actions]}"
RUN_DIR="${2:?missing run_dir}"
ROUNDS="${3:-1}"
MAX_PATHS="${4:-10}"
MAX_ACTIONS="${5:-6}"
STAGE="${STAGE:-full}"
EXTRA_ARGS="${EXTRA_ARGS:-}"

VENV="${VENV:-/data2/adminweihunj/webcoding/dataset_capability_study_20260914/venv}"
REPO="${REPO:-/data2/adminweihunj/webcoding/inspiration_library/code_debug_20260914}"
BROWSER_PROXY="${BROWSER_PROXY:-http://127.0.0.1:7890}"
CRED_FILE="${CRED_FILE:-$HOME/.config/codex/tokenwave.env}"
PY="$VENV/bin/python"

RUN_ID="$(date +%Y%m%d_%H%M%S)"
LOG_DIR="$REPO/logs/live_mining/$RUN_ID"
mkdir -p "$LOG_DIR"
cd "$REPO"

# 凭据只从受保护文件读进内存，不写进日志、不落到 run_dir
# shellcheck disable=SC1090
. "$CRED_FILE"
export DOC_API_KEY="${TOKENWAVE_API_KEY:-}"
export DOC_API_BASE_URL="https://api.tokenwave.us/v1"
export DOC_API_CHAT_MODEL="${DOC_API_CHAT_MODEL:-gpt-5.5}"
if [ -z "$DOC_API_KEY" ]; then
  echo "credential file carried no TOKENWAVE_API_KEY" >&2
  exit 2
fi

# API 直连（实测 1.9s，与走代理无差别）；只有浏览器抓网页走代理。
unset ALL_PROXY HTTPS_PROXY HTTP_PROXY all_proxy https_proxy http_proxy 2>/dev/null || true
export SSL_NO_VERIFY=1
export NO_PROXY="api.tokenwave.us,localhost,127.0.0.1"

CMD=("$PY" inspiration_library/utils/mine_live_url_capability_pool.py
     --sources "$SOURCES"
     --run-dir "$RUN_DIR"
     --mode url
     --stage "$STAGE"
     --exploration-rounds "$ROUNDS"
     --max-paths "$MAX_PATHS"
     --max-actions "$MAX_ACTIONS"
     --browser-proxy "$BROWSER_PROXY")
if [ -n "$EXTRA_ARGS" ]; then
  # 有意按空白切分：EXTRA_ARGS 就是一条命令行片段
  # shellcheck disable=SC2206
  CMD+=($EXTRA_ARGS)
fi

{
  echo "run_id=$RUN_ID"
  echo "started_at=$(date -Is)"
  echo "repo=$REPO"
  echo "sources=$SOURCES"
  echo "run_dir=$RUN_DIR"
  echo "stage=$STAGE"
  echo "rounds=$ROUNDS max_paths=$MAX_PATHS max_actions=$MAX_ACTIONS"
  echo "browser_proxy=$BROWSER_PROXY"
  echo "chat_model=$DOC_API_CHAT_MODEL base_url=$DOC_API_BASE_URL key_length=${#DOC_API_KEY}"
  echo "command=${CMD[*]}"
  echo "---"
} | tee "$LOG_DIR/run_meta.log"

set +e
"${CMD[@]}" 2>&1 | tee "$LOG_DIR/stdout.log"
STATUS="${PIPESTATUS[0]}"
set -e

echo "exit_status=$STATUS" | tee -a "$LOG_DIR/run_meta.log"
echo "finished_at=$(date -Is)" | tee -a "$LOG_DIR/run_meta.log"
echo "logs -> $LOG_DIR"
exit "$STATUS"
