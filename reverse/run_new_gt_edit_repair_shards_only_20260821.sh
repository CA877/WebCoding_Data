#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
cd "$repo_root"

: "${OPENAI_API_KEY:?Inject the Doc API key through the inherited environment}"
export OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export OPENAI_MODEL="qwen3.8-max"
unset ALL_PROXY HTTPS_PROXY HTTP_PROXY all_proxy https_proxy http_proxy
export NO_PROXY="idealab.alibaba-inc.com,alibaba-inc.com,api.deepseek.com,localhost,127.0.0.1"
export SSL_NO_VERIFY=1
export QWEN_TOKENIZER_JSON="$repo_root/.cache/qwen3-tokenizer.json"
export CONSTRUCT_API_TIMEOUT="${CONSTRUCT_API_TIMEOUT:-180}" CONSTRUCT_STREAM=1 CONSTRUCT_TRANSPORT_ATTEMPTS=2
export PATH="/data1/xieqianqian/webcoding/.local/bin:$PATH"

pool_root="${POOL_ROOT:-$repo_root/datasets/new_gt_edit_repair_mother_pools_20260821_v10}"
run_root="${RUN_ROOT:-$repo_root/runs/new_gt_edit_repair_bulk_20260821_v1}"
edit_data_root="${EDIT_DATA_ROOT:-$run_root/edit}"
repair_data_root="${REPAIR_DATA_ROOT:-$run_root/repair}"
cache_root="$run_root/canonical_v2"
log_root="$run_root/logs"
python_runtime="$repo_root/harness/.venv/bin/python"
uv_python=(uv run --no-project --python "$python_runtime" -- python)
manifest="$pool_root/shards/quota_manifest.json"
edit_concurrency="${EDIT_CONCURRENCY:-16}"
repair_concurrency="${REPAIR_CONCURRENCY:-16}"
if (( edit_concurrency < 1 || repair_concurrency < 1 || edit_concurrency + repair_concurrency > 32 )); then
  echo "invalid concurrency: edit=$edit_concurrency repair=$repair_concurrency max_total=32" >&2
  exit 2
fi
mkdir -p "$log_root/edit" "$log_root/repair" "$edit_data_root" "$repair_data_root"

{
  echo "started_at=$(date --iso-8601=seconds)"
  echo "pool_root=$pool_root"
  echo "run_root=$run_root"
  echo "edit_data_root=$edit_data_root"
  echo "repair_data_root=$repair_data_root"
  echo "endpoint=$OPENAI_BASE_URL"
  echo "model=$OPENAI_MODEL"
  echo "network_mode=direct"
  echo "edit_concurrency=$edit_concurrency"
  echo "repair_concurrency=$repair_concurrency"
  echo "api_timeout_seconds=$CONSTRUCT_API_TIMEOUT"
} | tee -a "$log_root/edit_repair_shards.log"

run_edit_shard() {
  local name="$1" scope="$2" profile="$3" variant="$4" target="$5" project_list="$6"
  local previous=-1 stalls=0 count=0 result_file="$edit_data_root/$name/text-edit.v2.jsonl"
  while [[ "$count" -lt "$target" ]]; do
    "${uv_python[@]}" reverse/construct_text_editing.py \
      --project-list "$project_list" --output-dir "$edit_data_root/$name" \
      --screenshot-dir "$run_root/images/edit/$name" --canonical-screenshot-dir "$cache_root" \
      --workers 1 --min-tasks 1 --max-tasks 7 --success-target "$target" --seed 20260821 \
      --max-retries 3 --max-output-tokens 8192 \
      --edit-profile "$profile" --page-scope "$scope" --image-input-variants source_image \
      --browser-proxy "" >> "$log_root/edit/$name.log" 2>&1 || true
    if [[ -f "$result_file" ]]; then count=$(wc -l < "$result_file"); else count=0; fi
    echo "edit shard=$name count=$count/$target" >> "$log_root/edit/$name.log"
    if [[ "$count" -eq "$previous" ]]; then
      stalls=$((stalls + 1))
      [[ "$stalls" -ge 3 ]] && return 3
    else
      stalls=0
    fi
    previous="$count"
  done
}

run_repair_shard() {
  local name="$1" scope="$2" family="$3" task_count="$4" injection="$5" target="$6" project_list="$7"
  local previous=-1 stalls=0 count=0 result_file="$repair_data_root/$name/image-repair.v2.jsonl"
  while [[ "$count" -lt "$target" ]]; do
    "${uv_python[@]}" reverse/construct_text_repair.py \
      --project-list "$project_list" --output-dir "$repair_data_root/$name" \
      --defect-screenshot-dir "$run_root/images/repair/$name" --canonical-screenshot-dir "$cache_root" \
      --workers 1 --min-tasks "$task_count" --max-tasks "$task_count" \
      --image-repair-target "$target" --seed 20260821 --repair-profile taxonomy \
      --max-retries 3 --max-output-tokens 8192 \
      --assigned-family "$family" --page-scope "$scope" --injection-strategy "$injection" \
      --browser-proxy "" --minimum-changed-ratio 0.01 >> "$log_root/repair/$name.log" 2>&1 || true
    if [[ -f "$result_file" ]]; then count=$(wc -l < "$result_file"); else count=0; fi
    echo "repair shard=$name count=$count/$target" >> "$log_root/repair/$name.log"
    if [[ "$count" -eq "$previous" ]]; then
      stalls=$((stalls + 1))
      [[ "$stalls" -ge 3 ]] && return 3
    else
      stalls=0
    fi
    previous="$count"
  done
}

edit_rows() {
  "${uv_python[@]}" - "$manifest" <<'PY'
import json, sys
for row in json.load(open(sys.argv[1], encoding="utf-8"))["edit"]:
    print("\t".join(map(str, [row["name"], row["page_scope"], row["profile"],
        row["image_input_variant"], row["success_target"], row["project_list"]])))
PY
}

repair_rows() {
  "${uv_python[@]}" - "$manifest" <<'PY'
import json, sys
for row in json.load(open(sys.argv[1], encoding="utf-8"))["repair"]:
    print("\t".join(map(str, [row["name"], row["page_scope"], row["repair_family"],
        row["task_count"], row["injection_strategy"], row["image_success_target"],
        row["project_list"]])))
PY
}

run_edit_group() {
  local active=0 failed=0
  while IFS=$'\t' read -r name scope profile variant target project_list; do
    run_edit_shard "$name" "$scope" "$profile" "$variant" "$target" "$project_list" &
    active=$((active + 1))
    if [[ "$active" -ge "$edit_concurrency" ]]; then
      wait -n || failed=1
      active=$((active - 1))
    fi
  done
  while [[ "$active" -gt 0 ]]; do wait -n || failed=1; active=$((active - 1)); done
  return "$failed"
}

run_repair_group() {
  local active=0 failed=0
  while IFS=$'\t' read -r name scope family task_count injection target project_list; do
    run_repair_shard "$name" "$scope" "$family" "$task_count" "$injection" "$target" "$project_list" &
    active=$((active + 1))
    if [[ "$active" -ge "$repair_concurrency" ]]; then
      wait -n || failed=1
      active=$((active - 1))
    fi
  done
  while [[ "$active" -gt 0 ]]; do wait -n || failed=1; active=$((active - 1)); done
  return "$failed"
}

set +e
run_edit_group < <(edit_rows) & edit_group_pid=$!
run_repair_group < <(repair_rows) & repair_group_pid=$!
wait "$edit_group_pid"; edit_status=$?
wait "$repair_group_pid"; repair_status=$?
set -e

{
  echo "edit_exit_status=$edit_status"
  echo "repair_exit_status=$repair_status"
  echo "completed_at=$(date --iso-8601=seconds)"
} | tee -a "$log_root/edit_repair_shards.log"

if [[ "$edit_status" -ne 0 || "$repair_status" -ne 0 ]]; then
  exit 4
fi
