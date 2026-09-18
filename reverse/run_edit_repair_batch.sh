#!/usr/bin/env bash
# Current batch entrypoint for materialized WebCompass ShareGPT projects.
#
# It supersedes the old phase1/phase2 scripts, which expected fake_url,
# deleted constructors, and per-instance info.json directories.  The current
# contract is a pair of project lists -> append-only records.jsonl files.
#
# Example (physical machine, Doc API key is read from docs/项目用api.pdf):
#   nohup bash reverse/run_edit_repair_batch.sh > logs/construct_batch_launcher.log 2>&1 &
#
# Optional environment variables:
#   TASKS=edit,repair          edit, repair, or both
#   EDIT_PROJECT_LIST=...      required, final 40K-eligible project list
#   REPAIR_PROJECT_LIST=...    required, final 40K-eligible project list
#   OUTPUT_ROOT=runs/construct_edit_repair_<run-id>
#   EDIT_WORKERS=24 REPAIR_WORKERS=8 MIN_TASKS=1 MAX_TASKS=7
#   EDIT_PROFILE=balanced EDIT_PAGE_SCOPE=any REPAIR_PROFILE=taxonomy REPAIR_PAGE_SCOPE=any
#   IMAGE_INPUT_VARIANTS=source_image,target_image,source_target_images
#   DRY_RUN=1                  print resolved commands, make no API calls
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$REPO_ROOT"

# Default to the protected Doc API route documented for this launcher. The key is extracted
# only into this process environment and is never written to logs or outputs.
API_PROFILE="${API_PROFILE:-dashscope_doc_direct}"
API_ENV_FILE="${API_ENV_FILE:-$REPO_ROOT/.env}"
if [[ "$API_PROFILE" == "dashscope_doc_direct" ]]; then
  API_DOC="${DASHSCOPE_API_DOC:-$REPO_ROOT/docs/项目用api.pdf}"
  [[ -f "$API_DOC" ]] || { echo "DashScope API document not found: $API_DOC" >&2; exit 2; }
  if command -v pdftotext >/dev/null 2>&1; then
    OPENAI_API_KEY="$(pdftotext -layout "$API_DOC" - | sed -nE 's/.*(sk-[A-Za-z0-9_-]{20,}).*/\1/p' | head -n 1)"
  else
    OPENAI_API_KEY="$(uv run --with pypdf python reverse/utils/extract_dashscope_key.py "$API_DOC")"
  fi
  [[ -n "$OPENAI_API_KEY" ]] || { echo "Could not locate a DashScope key in the API document" >&2; exit 2; }
  export OPENAI_API_KEY
  export OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
  export OPENAI_MODEL="qwen3.8-max"
  unset ALL_PROXY HTTPS_PROXY HTTP_PROXY all_proxy https_proxy http_proxy
  export API_NETWORK_MODE=direct
  export NO_PROXY="idealab.alibaba-inc.com,alibaba-inc.com,api.deepseek.com,localhost,127.0.0.1"
  export SSL_NO_VERIFY=1
elif [[ "$API_PROFILE" == "inherited_doc" ]]; then
  [[ -n "${OPENAI_API_KEY:-}" ]] || {
    echo "inherited_doc requires OPENAI_API_KEY in the current process environment" >&2
    exit 2
  }
  export OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
  export OPENAI_MODEL="qwen3.8-max"
  unset ALL_PROXY HTTPS_PROXY HTTP_PROXY all_proxy https_proxy http_proxy
  export API_NETWORK_MODE=direct
  export NO_PROXY="idealab.alibaba-inc.com,alibaba-inc.com,api.deepseek.com,localhost,127.0.0.1"
  export SSL_NO_VERIFY=1
elif [[ "$API_PROFILE" == "env" ]]; then
  [[ -f "$API_ENV_FILE" ]] || { echo "API env file not found: $API_ENV_FILE" >&2; exit 2; }
  # shellcheck disable=SC1090
  set -a; source "$API_ENV_FILE"; set +a
else
  echo "API_PROFILE must be dashscope_doc_direct, inherited_doc, or env" >&2
  exit 2
fi

TASKS="${TASKS:-edit,repair}"
EDIT_PROJECT_LIST="${EDIT_PROJECT_LIST:-}"
REPAIR_PROJECT_LIST="${REPAIR_PROJECT_LIST:-}"
OUTPUT_ROOT="${OUTPUT_ROOT:-runs/construct_edit_repair_$(date +%Y%m%d)}"
EDIT_WORKERS="${EDIT_WORKERS:-24}"
REPAIR_WORKERS="${REPAIR_WORKERS:-8}"
MIN_TASKS="${MIN_TASKS:-1}"
MAX_TASKS="${MAX_TASKS:-12}"
EDIT_MIN_TASKS="${EDIT_MIN_TASKS:-$MIN_TASKS}"
EDIT_MAX_TASKS="${EDIT_MAX_TASKS:-$MAX_TASKS}"
REPAIR_MIN_TASKS="${REPAIR_MIN_TASKS:-$MIN_TASKS}"
REPAIR_MAX_TASKS="${REPAIR_MAX_TASKS:-12}"
SEED="${SEED:-20260805}"
MAX_RETRIES="${MAX_RETRIES:-1}"
MAX_OUTPUT_TOKENS="${MAX_OUTPUT_TOKENS:-8192}"
IMAGE_REPAIR_TARGET="${IMAGE_REPAIR_TARGET:-3000}"
EDIT_PROFILE="${EDIT_PROFILE:-webcompass}"
EDIT_PAGE_SCOPE="${EDIT_PAGE_SCOPE:-any}"
REPAIR_PROFILE="${REPAIR_PROFILE:-webcompass}"
REPAIR_PAGE_SCOPE="${REPAIR_PAGE_SCOPE:-any}"
IMAGE_INPUT_VARIANTS="${IMAGE_INPUT_VARIANTS:-source_image}"
DRY_RUN="${DRY_RUN:-0}"

# The physical machine must use the project lora environment.  Keep an
# explicit override for collaborators and fall back to PATH only when the
# bundled environment is not present (for example on a fresh laptop).
DEFAULT_LORA_PYTHON="$REPO_ROOT/harness/.venv/bin/python"
if [[ -x "$DEFAULT_LORA_PYTHON" ]]; then
  PYTHON_BIN="${PYTHON_BIN:-$DEFAULT_LORA_PYTHON}"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

export CONSTRUCT_API_TIMEOUT="${CONSTRUCT_API_TIMEOUT:-600}"
export CONSTRUCT_STREAM="${CONSTRUCT_STREAM:-1}"
export CONSTRUCT_TRANSPORT_ATTEMPTS="${CONSTRUCT_TRANSPORT_ATTEMPTS:-1}"
BROWSER_PROXY="${BROWSER_PROXY:-}"

if [[ "$EDIT_MIN_TASKS" -lt 4 || "$EDIT_MAX_TASKS" -lt "$EDIT_MIN_TASKS" || "$EDIT_MAX_TASKS" -gt 12 ]]; then
  echo "EDIT_MIN_TASKS/EDIT_MAX_TASKS must satisfy 4 <= min <= max <= 12" >&2
  exit 2
fi
if [[ "$REPAIR_MIN_TASKS" -lt 1 || "$REPAIR_MAX_TASKS" -lt "$REPAIR_MIN_TASKS" ]]; then
  echo "REPAIR_MIN_TASKS/REPAIR_MAX_TASKS must satisfy 1 <= min <= max" >&2
  exit 2
fi
if [[ "$REPAIR_PROFILE" == "family" && "$REPAIR_MAX_TASKS" -gt 4 ]]; then
  echo "REPAIR_PROFILE=family has four distinct families; REPAIR_MAX_TASKS must be <= 4" >&2
  exit 2
fi
if [[ $((EDIT_WORKERS + REPAIR_WORKERS)) -gt 32 ]]; then
  echo "EDIT_WORKERS + REPAIR_WORKERS must not exceed the physical-machine total of 32" >&2
  exit 2
fi
if [[ "$TASKS" != *"edit"* && "$TASKS" != *"repair"* ]]; then
  echo "TASKS must include edit and/or repair" >&2
  exit 2
fi
if [[ "$TASKS" == *"edit"* && -z "$EDIT_PROJECT_LIST" ]]; then
  echo "Set EDIT_PROJECT_LIST to a 40K-eligible materialized WebCompass project list." >&2
  exit 2
fi
if [[ "$TASKS" == *"repair"* && -z "$REPAIR_PROJECT_LIST" ]]; then
  echo "Set REPAIR_PROJECT_LIST to a 40K-eligible materialized WebCompass project list." >&2
  exit 2
fi
if [[ "$DRY_RUN" != "1" && -z "${OPENAI_API_KEY:-${KIMI_API_KEY:-}}" ]]; then
  echo "No API key available for API_PROFILE=$API_PROFILE" >&2
  exit 2
fi
QWEN_TOKENIZER_JSON="${QWEN_TOKENIZER_JSON:-$REPO_ROOT/.cache/qwen3-tokenizer.json}"
export QWEN_TOKENIZER_JSON
if [[ "$DRY_RUN" != "1" && ! -f "$QWEN_TOKENIZER_JSON" ]]; then
  echo "missing Qwen tokenizer.json: $QWEN_TOKENIZER_JSON (set QWEN_TOKENIZER_JSON)" >&2
  exit 2
fi

run() {
  { printf '+ '; printf '%q ' "$@"; printf '\n'; } | tee -a "$LOG_FILE"
  [[ "$DRY_RUN" == "1" ]] || "$@" 2>&1 | tee -a "$LOG_FILE"
}

count_records() {
  local record="$1"
  [[ -f "$record" ]] || { echo 'ok=0 error=0'; return; }
  "$PYTHON_BIN" - "$record" <<'PY'
import json, sys
ok = error = 0
for line in open(sys.argv[1], encoding='utf-8'):
    try:
        rec = json.loads(line); status = rec.get('status', rec.get('conversion_status', 'ok'))
    except json.JSONDecodeError: continue
    ok += status in {'ok', 'success'}; error += status == 'error'
print(f'ok={ok} error={error}')
PY
}

mkdir -p "$OUTPUT_ROOT"
LOG_DIR="${LOG_DIR:-$OUTPUT_ROOT/logs}"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/batch_$(date +%Y%m%d_%H%M%S).log"
{
  echo "batch_log=$LOG_FILE"
  echo "edit_project_list=$EDIT_PROJECT_LIST"
  echo "repair_project_list=$REPAIR_PROJECT_LIST"
  echo "qwen_tokenizer=$QWEN_TOKENIZER_JSON"
  echo "python_bin=$PYTHON_BIN"
  echo "api_profile=$API_PROFILE"
  echo "model=${OPENAI_MODEL:-${KIMI_MODEL:-unknown}}"
  echo "construct_stream=$CONSTRUCT_STREAM"
  echo "transport_attempts=$CONSTRUCT_TRANSPORT_ATTEMPTS"
} | tee -a "$LOG_FILE"

if [[ "$TASKS" == *"edit"* ]]; then
  [[ -f "$EDIT_PROJECT_LIST" ]] || { echo "missing: $EDIT_PROJECT_LIST" >&2; exit 2; }
  run "$PYTHON_BIN" reverse/construct_text_editing.py \
    --project-list "$EDIT_PROJECT_LIST" --output-dir "$OUTPUT_ROOT/text_edit" \
    --screenshot-dir "$OUTPUT_ROOT/images/image-edit" \
    --workers "$EDIT_WORKERS" --min-tasks "$EDIT_MIN_TASKS" --max-tasks "$EDIT_MAX_TASKS" \
    --seed "$SEED" --max-retries "$MAX_RETRIES" --max-output-tokens "$MAX_OUTPUT_TOKENS" \
    --edit-profile "$EDIT_PROFILE" --page-scope "$EDIT_PAGE_SCOPE" \
    --image-input-variants "$IMAGE_INPUT_VARIANTS" \
    --browser-proxy "$BROWSER_PROXY"
fi

if [[ "$TASKS" == *"repair"* ]]; then
  [[ -f "$REPAIR_PROJECT_LIST" ]] || { echo "missing: $REPAIR_PROJECT_LIST" >&2; exit 2; }
  run "$PYTHON_BIN" reverse/construct_text_repair.py \
    --project-list "$REPAIR_PROJECT_LIST" --output-dir "$OUTPUT_ROOT/text_repair" \
    --defect-screenshot-dir "$OUTPUT_ROOT/images/image-repair/defective" \
    --clean-screenshot-dir "$OUTPUT_ROOT/images/image-repair/clean" \
    --workers "$REPAIR_WORKERS" --min-tasks "$REPAIR_MIN_TASKS" --max-tasks "$REPAIR_MAX_TASKS" \
    --seed "$SEED" --max-retries "$MAX_RETRIES" --max-output-tokens "$MAX_OUTPUT_TOKENS" \
    --repair-profile "$REPAIR_PROFILE" --page-scope "$REPAIR_PAGE_SCOPE" \
    --browser-proxy "$BROWSER_PROXY" --minimum-changed-ratio 0 \
    --image-repair-target "$IMAGE_REPAIR_TARGET"
fi

echo "=== current outputs ==="
if [[ "$TASKS" == *"edit"* ]]; then
  echo "text_edit: $(count_records "$OUTPUT_ROOT/text_edit/records.jsonl")"
  echo "image_edit: $(count_records "$OUTPUT_ROOT/text_edit/image-edit.v2.jsonl")"
fi
if [[ "$TASKS" == *"repair"* ]]; then
  echo "text_repair: $(count_records "$OUTPUT_ROOT/text_repair/records.jsonl")"
  echo "image_repair: $(count_records "$OUTPUT_ROOT/text_repair/image-repair.v2.jsonl")"
fi
