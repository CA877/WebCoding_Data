#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 6 ]]; then
  echo "Usage: $0 URL_FILE OUTPUT_DIR [LIMIT] [WORKERS] [MAX_CHILD_PAGES] [SITE_TIMEOUT_SECONDS]" >&2
  exit 2
fi

URL_FILE=$1
OUTPUT_DIR=$2
LIMIT=${3:-1}
WORKERS=${4:-1}
MAX_CHILD_PAGES=${5:-0}
SITE_TIMEOUT_SECONDS=${6:-180}

PROJECT_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
RUN_ID=$(date +%Y%m%d_%H%M%S)_limit${LIMIT}_workers${WORKERS}
LOG_DIR="$PROJECT_ROOT/logs/pipeline_c_strict/$RUN_ID"
TOKENIZER="$PROJECT_ROOT/.cache/qwen3-tokenizer.json"
PROXY_URL=${PIPELINE_C_PROXY_URL:-socks5://127.0.0.1:7897}
UV_BIN=${UV_BIN:-uv}
VISUAL_REVIEW=${PIPELINE_C_VISUAL_REVIEW:-0}
VISUAL_REVIEW_FLAG=--no-visual-review
if [[ "$VISUAL_REVIEW" == "1" ]]; then
  VISUAL_REVIEW_FLAG=--visual-review
fi

mkdir -p "$LOG_DIR" "$OUTPUT_DIR"
test -f "$URL_FILE"
test -f "$TOKENIZER"

export ALL_PROXY="$PROXY_URL"
export HTTPS_PROXY="$PROXY_URL"
export HTTP_PROXY="$PROXY_URL"
export NO_PROXY="idealab.alibaba-inc.com,alibaba-inc.com,api.deepseek.com,localhost,127.0.0.1"
export SSL_NO_VERIFY=1
export PIPELINE_C_KEEP_REJECTED_DEBUG=1

COMMAND=(
  "$UV_BIN" run python -m crawl.pipeline_c.main
  --urls "$URL_FILE"
  --output "$OUTPUT_DIR"
  --limit "$LIMIT"
  --workers "$WORKERS"
  --max-child-pages "$MAX_CHILD_PAGES"
  --site-timeout "$SITE_TIMEOUT_SECONDS"
  --wait-ms 2500
  --browser-proxy "$PROXY_URL"
  --qwen-tokenizer "$TOKENIZER"
  --max-training-code-tokens 40000
  "$VISUAL_REVIEW_FLAG"
  --no-exclude-render-bundles
)

{
  printf 'run_id=%s\n' "$RUN_ID"
  printf 'cwd=%s\n' "$PROJECT_ROOT"
  printf 'url_file=%s\n' "$URL_FILE"
  printf 'output_dir=%s\n' "$OUTPUT_DIR"
  printf 'limit=%s\nworkers=%s\nmax_child_pages=%s\nsite_timeout_seconds=%s\n' \
    "$LIMIT" "$WORKERS" "$MAX_CHILD_PAGES" "$SITE_TIMEOUT_SECONDS"
  printf 'keep_rejected_debug=1\n'
  printf 'visual_review=%s\n' "$VISUAL_REVIEW"
  printf 'proxy_url=%s\nuv_bin=%s\n' "$PROXY_URL" "$UV_BIN"
  printf 'command='
  printf '%q ' "${COMMAND[@]}"
  printf '\n'
} > "$LOG_DIR/run.env"

cd "$PROJECT_ROOT"
set +e
"${COMMAND[@]}" 2>&1 | tee "$LOG_DIR/run.log"
STATUS=${PIPESTATUS[0]}
set -e
printf 'exit_status=%s\nfinished_at=%s\n' "$STATUS" "$(date -Iseconds)" | tee "$LOG_DIR/status.txt"
exit "$STATUS"
