#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 7 ]]; then
  echo "Usage: $0 CANDIDATE_MANIFEST OUTPUT_ROOT [PREFLIGHT_TARGET] [BROWSER_PROBE_LIMIT] [STRICT_LIMIT] [WORKERS] [SITE_TIMEOUT]" >&2
  exit 2
fi

CANDIDATE_MANIFEST=$1
OUTPUT_ROOT=$2
PREFLIGHT_TARGET=${3:-4000}
BROWSER_PROBE_LIMIT=${4:-200}
STRICT_LIMIT=${5:-30}
WORKERS=${6:-4}
SITE_TIMEOUT=${7:-180}

PROJECT_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
UV_BIN=${UV_BIN:-uv}
PROXY_URL=${PIPELINE_C_PROXY_URL:-http://127.0.0.1:7890}
TOKENIZER=${QWEN_TOKENIZER_JSON:-$PROJECT_ROOT/.cache/qwen3-tokenizer.json}
PREFLIGHT_DIR=$OUTPUT_ROOT/http_preflight
PROBE_RESULTS=$OUTPUT_ROOT/browser_probe_results.jsonl
SELECTED_DIR=$OUTPUT_ROOT/browser_selected
STRICT_DIR=$OUTPUT_ROOT/strict_crawl

test -f "$CANDIDATE_MANIFEST"
test -f "$TOKENIZER"
mkdir -p "$OUTPUT_ROOT"

cd "$PROJECT_ROOT"
"$UV_BIN" run python crawl/utils/preflight_pipeline_c_rich_urls.py \
  --candidate-manifest "$CANDIDATE_MANIFEST" \
  --output-dir "$PREFLIGHT_DIR" \
  --target "$PREFLIGHT_TARGET" \
  --concurrency 50 \
  --timeout 10 \
  --proxy "$PROXY_URL"

"$UV_BIN" run python crawl/utils/probe_pipeline_c_url_complexity.py \
  --urls "$PREFLIGHT_DIR/selected_urls.txt" \
  --output "$PROBE_RESULTS" \
  --limit "$BROWSER_PROBE_LIMIT" \
  --workers "$WORKERS" \
  --timeout-seconds 30 \
  --hard-timeout-seconds 45 \
  --browser-proxy "$PROXY_URL"

if [[ -e "$SELECTED_DIR" ]]; then
  echo "Refusing to overwrite existing selection: $SELECTED_DIR" >&2
  exit 1
fi
"$UV_BIN" run python crawl/utils/select_pipeline_c_probe_results.py \
  --probe-results "$PROBE_RESULTS" \
  --probe-manifest "$PREFLIGHT_DIR/selected_manifest.jsonl" \
  --output-dir "$SELECTED_DIR" \
  --limit "$STRICT_LIMIT"

PIPELINE_C_PROXY_URL=$PROXY_URL UV_BIN=$UV_BIN \
  bash crawl/pipeline_c/run_strict_local_debug.sh \
  "$SELECTED_DIR/selected_urls.txt" "$STRICT_DIR" "$STRICT_LIMIT" "$WORKERS" 0 "$SITE_TIMEOUT"
