#!/usr/bin/env bash
# Current batch entrypoint for materialized WebCompass ShareGPT projects.
#
# It supersedes the old phase1/phase2 scripts, which expected fake_url,
# deleted constructors, and per-instance info.json directories.  The current
# contract is a pair of project lists -> append-only records.jsonl files.
#
# Example (physical machine):
#   export KIMI_API_KEY='...'
#   bash construct/run_edit_repair_batch.sh
#
# Optional environment variables:
#   TASKS=edit,repair          edit, repair, or both
#   EDIT_PROJECT_LIST=...      required, final 40K-eligible project list
#   REPAIR_PROJECT_LIST=...    required, final 40K-eligible project list
#   OUTPUT_ROOT=runs/construct_edit_repair_<run-id>
#   EDIT_WORKERS=1 REPAIR_WORKERS=1 MIN_TASKS=2 MAX_TASKS=10
#   DRY_RUN=1                  print resolved commands, make no API calls
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$REPO_ROOT"

# API credentials stay outside git and outside output JSONL.  By default load
# <repo>/.env; collaborators may point API_ENV_FILE at their own secret file.
API_ENV_FILE="${API_ENV_FILE:-$REPO_ROOT/.env}"
if [[ -f "$API_ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a
  source "$API_ENV_FILE"
  set +a
fi

TASKS="${TASKS:-edit,repair}"
EDIT_PROJECT_LIST="${EDIT_PROJECT_LIST:-}"
REPAIR_PROJECT_LIST="${REPAIR_PROJECT_LIST:-}"
OUTPUT_ROOT="${OUTPUT_ROOT:-runs/construct_edit_repair_$(date +%Y%m%d)}"
EDIT_WORKERS="${EDIT_WORKERS:-1}"
REPAIR_WORKERS="${REPAIR_WORKERS:-1}"
MIN_TASKS="${MIN_TASKS:-2}"
MAX_TASKS="${MAX_TASKS:-10}"
SEED="${SEED:-20260721}"
MAX_RETRIES="${MAX_RETRIES:-3}"
MAX_OUTPUT_TOKENS="${MAX_OUTPUT_TOKENS:-8192}"
DRY_RUN="${DRY_RUN:-0}"

# The physical machine must use the project lora environment.  Keep an
# explicit override for collaborators and fall back to PATH only when the
# bundled environment is not present (for example on a fresh laptop).
DEFAULT_LORA_PYTHON="$REPO_ROOT/web-coding-agent/.conda/lora/bin/python"
if [[ -x "$DEFAULT_LORA_PYTHON" ]]; then
  PYTHON_BIN="${PYTHON_BIN:-$DEFAULT_LORA_PYTHON}"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

# Physical-machine defaults.  Do not overwrite a caller-provided proxy.
export ALL_PROXY="${ALL_PROXY:-http://127.0.0.1:7890}"
export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:7890}"
export HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:7890}"
export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1}"
export SSL_NO_VERIFY="${SSL_NO_VERIFY:-1}"
export CONSTRUCT_API_TIMEOUT="${CONSTRUCT_API_TIMEOUT:-600}"

if [[ "$MIN_TASKS" -lt 2 || "$MAX_TASKS" -lt "$MIN_TASKS" || "$MAX_TASKS" -gt 10 ]]; then
  echo "MIN_TASKS/MAX_TASKS must satisfy 2 <= MIN_TASKS <= MAX_TASKS <= 10" >&2
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
if [[ "$DRY_RUN" != "1" && -z "${KIMI_API_KEY:-${OPENAI_API_KEY:-}}" ]]; then
  echo "Set KIMI_API_KEY (or OPENAI_API_KEY) in $API_ENV_FILE before invoking the constructor." >&2
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
    try: status = json.loads(line).get('status')
    except json.JSONDecodeError: continue
    ok += status == 'ok'; error += status == 'error'
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
} | tee -a "$LOG_FILE"

if [[ "$TASKS" == *"edit"* ]]; then
  [[ -f "$EDIT_PROJECT_LIST" ]] || { echo "missing: $EDIT_PROJECT_LIST" >&2; exit 2; }
  run "$PYTHON_BIN" construct/construct_text_editing.py \
    --project-list "$EDIT_PROJECT_LIST" --output-dir "$OUTPUT_ROOT/text_edit" \
    --workers "$EDIT_WORKERS" --min-tasks "$MIN_TASKS" --max-tasks "$MAX_TASKS" \
    --seed "$SEED" --max-retries "$MAX_RETRIES" --max-output-tokens "$MAX_OUTPUT_TOKENS"
  # Image-editing does not re-render: it only verifies/reuses project-root PNGs.
  run "$PYTHON_BIN" construct/construct_image_editing.py \
    --records-jsonl "$OUTPUT_ROOT/text_edit/records.jsonl" \
    --output-jsonl "$OUTPUT_ROOT/image_edit_records.jsonl"
fi

if [[ "$TASKS" == *"repair"* ]]; then
  [[ -f "$REPAIR_PROJECT_LIST" ]] || { echo "missing: $REPAIR_PROJECT_LIST" >&2; exit 2; }
  run "$PYTHON_BIN" construct/construct_text_repair.py \
    --project-list "$REPAIR_PROJECT_LIST" --output-dir "$OUTPUT_ROOT/text_repair" \
    --defect-screenshot-dir "$OUTPUT_ROOT/image_repair/repair_defect_screenshots" \
    --workers "$REPAIR_WORKERS" --min-tasks "$MIN_TASKS" --max-tasks "$MAX_TASKS" \
    --seed "$SEED" --max-retries "$MAX_RETRIES" --max-output-tokens "$MAX_OUTPUT_TOKENS" \
    --browser-proxy "$HTTP_PROXY"
fi

echo "=== current outputs ==="
if [[ "$TASKS" == *"edit"* ]]; then
  echo "text_edit: $(count_records "$OUTPUT_ROOT/text_edit/records.jsonl")"
  echo "image_edit: $(count_records "$OUTPUT_ROOT/image_edit_records.jsonl")"
fi
if [[ "$TASKS" == *"repair"* ]]; then
  echo "text_repair: $(count_records "$OUTPUT_ROOT/text_repair/records.jsonl")"
fi
