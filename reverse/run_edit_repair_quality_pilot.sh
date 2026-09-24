#!/usr/bin/env bash
set -euo pipefail

: "${OPENAI_API_KEY:?Pass the Doc API key only through the inherited process environment}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
cd "$repo_root"

python_bin="${PYTHON_BIN:-$repo_root/harness/.venv/bin/python}"
edit_list="${EDIT_PROJECT_LIST:-$repo_root/runs/webcompass_6503_production_20260805/edit_3000.txt}"
repair_list="${REPAIR_PROJECT_LIST:-$repo_root/runs/webcompass_6503_production_20260805/repair_candidates_6502.txt}"
run_id="${RUN_ID:-edit_repair_quality_pilot_$(date +%Y%m%dT%H%M%S)}"
output_root="${OUTPUT_ROOT:-$repo_root/runs/$run_id}"
limit="${LIMIT:-1}"
offset="${OFFSET:-0}"
edit_workers="${EDIT_WORKERS:-1}"
repair_workers="${REPAIR_WORKERS:-1}"
min_tasks="${MIN_TASKS:-1}"
max_tasks="${MAX_TASKS:-1}"
tasks="${TASKS:-edit,repair}"
mkdir -p "$output_root/logs"
log_file="$output_root/logs/run.log"

export OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export OPENAI_MODEL="qwen3.8-max"
export QWEN_TOKENIZER_JSON="${QWEN_TOKENIZER_JSON:-$repo_root/.cache/qwen3-tokenizer.json}"
export CONSTRUCT_API_TIMEOUT="${CONSTRUCT_API_TIMEOUT:-600}"
export CONSTRUCT_STREAM="${CONSTRUCT_STREAM:-1}"
export CONSTRUCT_TRANSPORT_ATTEMPTS="${CONSTRUCT_TRANSPORT_ATTEMPTS:-2}"
unset ALL_PROXY HTTPS_PROXY HTTP_PROXY all_proxy https_proxy http_proxy
export API_NETWORK_MODE=direct
export NO_PROXY="idealab.alibaba-inc.com,alibaba-inc.com,api.deepseek.com,localhost,127.0.0.1"
export SSL_NO_VERIFY=1

{
  echo "run_id=$run_id"
  echo "model=$OPENAI_MODEL"
  echo "api_profile=inherited_doc_direct"
  echo "stream=$CONSTRUCT_STREAM"
  echo "limit=$limit"
  echo "offset=$offset"
  echo "min_tasks=$min_tasks"
  echo "max_tasks=$max_tasks"
  echo "tasks=$tasks"
  echo "edit_list=$edit_list"
  echo "repair_list=$repair_list"
} | tee -a "$log_file"

run_logged() {
  { printf '+ '; printf '%q ' "$@"; printf '\n'; } | tee -a "$log_file"
  "$@" 2>&1 | tee -a "$log_file"
}

if [[ "$tasks" == *"edit"* ]]; then
run_logged "$python_bin" reverse/edit/query/construct.py \
  --project-list "$edit_list" --output-dir "$output_root/text_edit" \
  --screenshot-dir "$output_root/images/image-edit" --limit "$limit" --offset "$offset" \
  --workers "$edit_workers" --min-tasks "$min_tasks" --max-tasks "$max_tasks" \
  --seed 20260805 --max-retries 3 --max-output-tokens 8192 \
  --edit-profile balanced --page-scope any \
  --image-input-variants source_image,target_image,source_target_images \
  --browser-proxy ""

run_logged "$python_bin" reverse/utils/audit_edit_repair_taxonomy_quality.py \
  --input "$output_root/text_edit/records.jsonl" \
  --report-jsonl "$output_root/quality_reports.jsonl" --minimum-pass-rate 1.0
fi

if [[ "$tasks" == *"repair"* ]]; then
run_logged "$python_bin" reverse/repair/gt/construct.py \
  --project-list "$repair_list" --output-dir "$output_root/text_repair" \
  --defect-screenshot-dir "$output_root/images/image-repair/defective" \
  --clean-screenshot-dir "$output_root/images/image-repair/clean" \
  --limit "$limit" --offset "$offset" --workers "$repair_workers" \
  --min-tasks "$min_tasks" --max-tasks "$max_tasks" --seed 20260805 \
  --max-retries 3 --max-output-tokens 8192 --repair-profile taxonomy \
  --page-scope any --browser-proxy "" --minimum-changed-ratio 0.01

run_logged "$python_bin" reverse/utils/audit_edit_repair_taxonomy_quality.py \
  --input "$output_root/text_repair/records.jsonl" \
  --report-jsonl "$output_root/quality_reports.jsonl" --minimum-pass-rate 1.0
fi

echo "exit_status=0" | tee -a "$log_file"
printf 'output_root=%s\n' "$output_root"
