#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
cd "$repo_root"
: "${OPENAI_API_KEY:?Inject the Doc API key through the inherited environment}"
export OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1" OPENAI_MODEL="qwen3.8-max"
unset ALL_PROXY HTTPS_PROXY HTTP_PROXY all_proxy https_proxy http_proxy
export NO_PROXY="idealab.alibaba-inc.com,alibaba-inc.com,api.deepseek.com,localhost,127.0.0.1"
export SSL_NO_VERIFY=1 PYTHONUNBUFFERED=1 CONSTRUCT_STREAM=1 CONSTRUCT_TRANSPORT_ATTEMPTS=2
export CONSTRUCT_API_TIMEOUT="${CONSTRUCT_API_TIMEOUT:-240}"
export QWEN_TOKENIZER_JSON="$repo_root/.cache/qwen3-tokenizer.json"
export PATH="/data1/xieqianqian/webcoding/.local/bin:$PATH"

run_root="${RUN_ROOT:-$repo_root/runs/new_gt_webcompass_task_count_supplements_20260822_v1}"
tail_root="${TAIL_ROOT:-$repo_root/datasets/new_gt_webcompass_task_count_tail_20260822_v1}"
manifest="$tail_root/tail_manifest.json"
canonical_root="$repo_root/runs/new_gt_edit_repair_bulk_20260821_v1/canonical_v2"
log_root="$run_root/logs/tail_v1"
python_runtime="$repo_root/harness/.venv/bin/python"
uv_python=(uv run --no-project --python "$python_runtime" -- python)
edit_concurrency="${EDIT_CONCURRENCY:-22}" repair_concurrency="${REPAIR_CONCURRENCY:-10}"
(( edit_concurrency >= 1 && repair_concurrency >= 1 && edit_concurrency + repair_concurrency <= 32 )) || exit 2
mkdir -p "$log_root/edit" "$log_root/repair"
{
  echo "started_at=$(date --iso-8601=seconds)"
  echo "scheduling_unit=single_llm_case"
  echo "edit_concurrency=$edit_concurrency"
  echo "repair_concurrency=$repair_concurrency"
} | tee -a "$log_root/batch.log"

run_edit() {
  local name="$1" scope="$2" profile="$3" count="$4" target="$5" list="$6"
  "${uv_python[@]}" reverse/construct_text_editing.py \
    --project-list "$list" --output-dir "$run_root/edit/$name" \
    --screenshot-dir "$run_root/images/edit/$name" --canonical-screenshot-dir "$canonical_root" \
    --workers 1 --min-tasks "$count" --max-tasks "$count" --success-target "$target" \
    --seed 20260822 --max-retries 3 --max-output-tokens 16384 --edit-profile "$profile" \
    --page-scope "$scope" --image-input-variants source_image --browser-proxy "" \
    >> "$log_root/edit/$name.log" 2>&1
}

run_repair() {
  local name="$1" scope="$2" injection="$3" count="$4" target="$5" list="$6"
  "${uv_python[@]}" reverse/construct_text_repair.py \
    --project-list "$list" --output-dir "$run_root/repair/$name" \
    --defect-screenshot-dir "$run_root/images/repair/$name" --canonical-screenshot-dir "$canonical_root" \
    --workers 1 --min-tasks "$count" --max-tasks "$count" --image-repair-target "$target" \
    --seed 20260822 --repair-profile taxonomy --mixed-families --max-retries 3 \
    --max-output-tokens 16384 --page-scope "$scope" --injection-strategy "$injection" \
    --browser-proxy "" --minimum-changed-ratio 0.01 >> "$log_root/repair/$name.log" 2>&1
}

rows() {
  local kind="$1"
  "${uv_python[@]}" - "$manifest" "$kind" <<'PY'
import json,sys
kind=sys.argv[2]
for row in json.load(open(sys.argv[1],encoding="utf-8"))[kind]:
    if kind=="edit":
        values=[row["name"],row["page_scope"],row["profile"],row["task_count"],row["success_target"],row["project_list"]]
    else:
        values=[row["name"],row["page_scope"],row["injection_strategy"],row["task_count"],row["image_success_target"],row["project_list"]]
    print("\t".join(map(str,values)))
PY
}

run_edit_group() {
  local active=0 failed=0
  while IFS=$'\t' read -r name scope profile count target list; do
    run_edit "$name" "$scope" "$profile" "$count" "$target" "$list" & active=$((active+1))
    if (( active >= edit_concurrency )); then wait -n || failed=1; active=$((active-1)); fi
  done < <(rows edit)
  while (( active > 0 )); do wait -n || failed=1; active=$((active-1)); done
  return "$failed"
}

run_repair_group() {
  local active=0 failed=0
  while IFS=$'\t' read -r name scope injection count target list; do
    run_repair "$name" "$scope" "$injection" "$count" "$target" "$list" & active=$((active+1))
    if (( active >= repair_concurrency )); then wait -n || failed=1; active=$((active-1)); fi
  done < <(rows repair)
  while (( active > 0 )); do wait -n || failed=1; active=$((active-1)); done
  return "$failed"
}

set +e
run_edit_group & edit_pid=$!
run_repair_group & repair_pid=$!
wait "$edit_pid"; edit_status=$?
wait "$repair_pid"; repair_status=$?
set -e
echo "completed_at=$(date --iso-8601=seconds) edit_status=$edit_status repair_status=$repair_status" | tee -a "$log_root/batch.log"
(( edit_status == 0 && repair_status == 0 ))
