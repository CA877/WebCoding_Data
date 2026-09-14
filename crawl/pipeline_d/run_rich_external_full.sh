#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."
export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}."

UV_BIN="${UV_BIN:-/data1/xieqianqian/webcoding/.local/bin/uv}"
SOURCE_DIR="${SOURCE_DIR:-datasets/pipeline_c/rich_url_preflight_20260903_v1}"
RUN_ROOT="${RUN_ROOT:-runs/pipeline_d_rich_external_4k_20260903_v1}"
TOKENIZER="${QWEN_TOKENIZER_JSON:-.cache/qwen3-tokenizer.json}"
BROWSER_PROXY="${PIPELINE_D_PROXY_URL:-http://127.0.0.1:7890}"
PROBE_WORKERS="${PROBE_WORKERS:-8}"
CRAWL_WORKERS="${CRAWL_WORKERS:-8}"
INPUT_LIMIT="${INPUT_LIMIT:-4000}"
SELECT_LIMIT="${SELECT_LIMIT:-4000}"
MAX_CODE_TOKENS="${PIPELINE_D_MAX_CODE_TOKENS:-0}"
ADMISSION_PROFILE="${PIPELINE_D_ADMISSION_PROFILE:-inspiration}"

mkdir -p "$RUN_ROOT"

"$UV_BIN" run python scripts/probe_pipeline_c_url_complexity.py \
  --urls "$SOURCE_DIR/selected_urls.txt" \
  --output "$RUN_ROOT/probe_results.jsonl" \
  --limit "$INPUT_LIMIT" \
  --timeout-seconds 25 \
  --hard-timeout-seconds 40 \
  --wait-ms 1500 \
  --workers "$PROBE_WORKERS" \
  --browser-proxy "$BROWSER_PROXY"

if test ! -e "$RUN_ROOT/selection"; then
  "$UV_BIN" run python scripts/select_pipeline_c_probe_results.py \
    --probe-results "$RUN_ROOT/probe_results.jsonl" \
    --probe-manifest "$SOURCE_DIR/selected_manifest.jsonl" \
    --output-dir "$RUN_ROOT/selection" \
    --limit "$SELECT_LIMIT"
elif test ! -f "$RUN_ROOT/selection/summary.json"; then
  echo "incomplete selection directory: $RUN_ROOT/selection" >&2
  exit 1
fi

"$UV_BIN" run python -m crawl.pipeline_d.main \
  --urls "$RUN_ROOT/selection/selected_urls.txt" \
  --output "$RUN_ROOT/output" \
  --browser-proxy "$BROWSER_PROXY" \
  --workers "$CRAWL_WORKERS" \
  --wait-ms 3000 \
  --site-timeout 120 \
  --qwen-tokenizer "$TOKENIZER" \
  --max-code-tokens "$MAX_CODE_TOKENS" \
  --admission-profile "$ADMISSION_PROFILE"
