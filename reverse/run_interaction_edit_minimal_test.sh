#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

RUN_ID="${RUN_ID:-interaction_edit_hover_real1_20260821}"
SOURCE_PROJECT="${SOURCE_PROJECT:-$REPO_ROOT/runs/pipeline_c_strict_lightweight_final3_20260820/projects/31fb4c7d9ab7e6ef}"
OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/runs/$RUN_ID}"
LOG_DIR="${LOG_DIR:-$REPO_ROOT/logs/reverse/$RUN_ID}"
PROJECT_LIST="$LOG_DIR/project_list.txt"
LOG_FILE="$LOG_DIR/run.log"
COMMAND_FILE="$LOG_DIR/command.txt"
STATUS_FILE="$LOG_DIR/exit_status.txt"

mkdir -p "$LOG_DIR" "$OUTPUT_DIR"
printf '%s\n' "$SOURCE_PROJECT" > "$PROJECT_LIST"

API_DOC="${DASHSCOPE_API_DOC:-$REPO_ROOT/docs/项目用api.pdf}"
if [[ ! -f "$API_DOC" ]]; then
  echo "DashScope API document not found: $API_DOC" >&2
  exit 2
fi
if command -v pdftotext >/dev/null 2>&1; then
  OPENAI_API_KEY="$(pdftotext -layout "$API_DOC" - | sed -nE 's/.*(sk-[A-Za-z0-9_-]{20,}).*/\1/p' | head -n 1)"
else
  OPENAI_API_KEY="$(uv run --with pypdf python scripts/extract_dashscope_key.py "$API_DOC")"
fi
if [[ -z "$OPENAI_API_KEY" ]]; then
  echo "Could not locate a DashScope key in the API document" >&2
  exit 2
fi
export OPENAI_API_KEY
export OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export OPENAI_MODEL="qwen3.8-max"

# Workspace ../../AGENTS.md requires the physical-machine Doc API route to be direct.
unset ALL_PROXY HTTPS_PROXY HTTP_PROXY all_proxy https_proxy http_proxy
export NO_PROXY="idealab.alibaba-inc.com,alibaba-inc.com,api.deepseek.com,localhost,127.0.0.1"
export SSL_NO_VERIFY=1
export API_NETWORK_MODE=direct
export CONSTRUCT_API_TIMEOUT="${CONSTRUCT_API_TIMEOUT:-180}"
export CONSTRUCT_TRANSPORT_ATTEMPTS="${CONSTRUCT_TRANSPORT_ATTEMPTS:-1}"
export CONSTRUCT_STREAM="${CONSTRUCT_STREAM:-1}"
MAX_OUTPUT_TOKENS="${MAX_OUTPUT_TOKENS:-2048}"
MAX_RETRIES="${MAX_RETRIES:-2}"

COMMAND=(
  uv run python reverse/construct_text_editing.py
  --project-list "$PROJECT_LIST"
  --output-dir "$OUTPUT_DIR"
  --limit 1
  --workers 1
  --min-tasks 1
  --max-tasks 1
  --seed 21
  --max-retries "$MAX_RETRIES"
  --max-output-tokens "$MAX_OUTPUT_TOKENS"
  --edit-profile interaction2code
  --page-scope sp
  --image-input-variants source_target_images
  --browser-proxy ""
  --minimum-changed-ratio 0.002
  --minimum-interaction-changed-ratio 0.0001
)

printf '%q ' "${COMMAND[@]}" > "$COMMAND_FILE"
printf '\n' >> "$COMMAND_FILE"
{
  echo "run_id=$RUN_ID"
  echo "source_project=$SOURCE_PROJECT"
  echo "model=${OPENAI_MODEL:-${KIMI_MODEL:-unknown}}"
  echo "api_profile=dashscope_doc_direct"
  echo "endpoint=https://dashscope.aliyuncs.com/compatible-mode/v1"
  echo "max_output_tokens=$MAX_OUTPUT_TOKENS"
  echo "max_retries=$MAX_RETRIES"
  echo "started_at=$(date -Iseconds)"
} | tee -a "$LOG_FILE"

set +e
"${COMMAND[@]}" 2>&1 | tee -a "$LOG_FILE"
status=${PIPESTATUS[0]}
set -e
printf '%s\n' "$status" > "$STATUS_FILE"
echo "finished_at=$(date -Iseconds) status=$status" | tee -a "$LOG_FILE"
exit "$status"
