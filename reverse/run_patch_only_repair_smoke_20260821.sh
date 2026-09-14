#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
cd "$repo_root"
: "${PROJECT_LIST:?Set PROJECT_LIST}"
: "${CANONICAL_SCREENSHOT_DIR:?Set CANONICAL_SCREENSHOT_DIR}"
: "${OUTPUT_DIR:?Set OUTPUT_DIR}"

IFS= read -r OPENAI_API_KEY
export OPENAI_API_KEY
export OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export OPENAI_MODEL="qwen3.8-max"
export CONSTRUCT_API_TIMEOUT="${CONSTRUCT_API_TIMEOUT:-180}"
export CONSTRUCT_STREAM=1 CONSTRUCT_TRANSPORT_ATTEMPTS=2 SSL_NO_VERIFY=1
unset ALL_PROXY HTTPS_PROXY HTTP_PROXY all_proxy https_proxy http_proxy
export NO_PROXY="idealab.alibaba-inc.com,alibaba-inc.com,api.deepseek.com,localhost,127.0.0.1"
export QWEN_TOKENIZER_JSON="$repo_root/.cache/qwen3-tokenizer.json"
export PATH="/data1/xieqianqian/webcoding/.local/bin:$PATH"

mkdir -p "$OUTPUT_DIR/logs"
set +e
PYTHONPATH=.:.. uv run --no-project \
  --python "$repo_root/harness/.venv/bin/python" -- python \
  reverse/construct_text_repair.py \
  --project-list "$PROJECT_LIST" --limit 1 --output-dir "$OUTPUT_DIR/data" \
  --defect-screenshot-dir "$OUTPUT_DIR/defect_images" \
  --canonical-screenshot-dir "$CANONICAL_SCREENSHOT_DIR" \
  --workers 1 --min-tasks 1 --max-tasks 1 --seed 20260821 \
  --max-retries 3 --max-output-tokens 8192 --repair-profile taxonomy \
  --assigned-family interaction_repair --page-scope any --injection-strategy llm \
  --browser-proxy "" --minimum-changed-ratio 0.01 \
  2>&1 | tee -a "$OUTPUT_DIR/logs/run.log"
status=${PIPESTATUS[0]}
set -e
echo "exit_status=$status" | tee -a "$OUTPUT_DIR/logs/run.log"
exit "$status"
