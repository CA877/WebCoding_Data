#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

PYTHON_BIN="${PYTHON_BIN:-/data1/xieqianqian/webcoding/venv/bin/python}"
URLS="${URLS:-datasets/pipeline_d/modern_inspiration_urls_4000_20260904_v2/candidate_urls.txt}"
RUN_ROOT="${RUN_ROOT:-runs/pipeline_d_inspiration_4000_20260904}"
TOKENIZER="${QWEN_TOKENIZER_JSON:-.cache/qwen3-tokenizer.json}"
TARGET_PASSES="${TARGET_PASSES:-0}"
BROWSER_PROXY="${PIPELINE_D_PROXY_URL-http://127.0.0.1:7890}"
WORKERS="${PIPELINE_D_WORKERS:-16}"
LIMIT="${PIPELINE_D_LIMIT:-0}"
MAX_CODE_TOKENS="${PIPELINE_D_MAX_CODE_TOKENS:-0}"
ADMISSION_PROFILE="${PIPELINE_D_ADMISSION_PROFILE:-inspiration}"

export ALL_PROXY="${ALL_PROXY-http://127.0.0.1:7890}"
export HTTPS_PROXY="${HTTPS_PROXY-http://127.0.0.1:7890}"
export HTTP_PROXY="${HTTP_PROXY-http://127.0.0.1:7890}"
export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1}"
export SSL_NO_VERIFY="${SSL_NO_VERIFY:-1}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

mkdir -p "$RUN_ROOT"
command -v setsid >/dev/null 2>&1 || {
  printf 'setsid is required so interruption can clean the crawler process group\n' >&2
  exit 2
}

CRAWLER_PID=""
cleanup() {
  local status=$?
  trap - EXIT INT TERM
  if [[ -n "$CRAWLER_PID" ]] && kill -0 "$CRAWLER_PID" 2>/dev/null; then
    kill -TERM -- "-$CRAWLER_PID" 2>/dev/null || true
    for _ in 1 2 3 4 5; do
      kill -0 "$CRAWLER_PID" 2>/dev/null || break
      sleep 1
    done
    kill -KILL -- "-$CRAWLER_PID" 2>/dev/null || true
  fi
  exit "$status"
}
trap cleanup EXIT INT TERM

setsid "$PYTHON_BIN" -m crawl.pipeline_d.main \
  --urls "$URLS" \
  --output "$RUN_ROOT/output" \
  --browser-proxy "$BROWSER_PROXY" \
  --workers "$WORKERS" \
  --wait-ms 3000 \
  --site-timeout 120 \
  --qwen-tokenizer "$TOKENIZER" \
  --max-code-tokens "$MAX_CODE_TOKENS" \
  --admission-profile "$ADMISSION_PROFILE" \
  --target-passes "$TARGET_PASSES" \
  --limit "$LIMIT" \
  > >(tee -a "$RUN_ROOT/pipeline.log") 2>&1 &
CRAWLER_PID=$!
printf '%s\n' "$CRAWLER_PID" > "$RUN_ROOT/pid.txt"
wait "$CRAWLER_PID"
CRAWLER_STATUS=$?
CRAWLER_PID=""
trap - EXIT INT TERM
exit "$CRAWLER_STATUS"
