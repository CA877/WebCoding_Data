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
export CONSTRUCT_API_TIMEOUT="${CONSTRUCT_API_TIMEOUT:-180}" CONSTRUCT_STREAM=1 CONSTRUCT_TRANSPORT_ATTEMPTS=2
export PATH="/data1/xieqianqian/webcoding/.local/bin:$PATH"

pool_root="$repo_root/datasets/new_gt_edit_repair_mother_pools_20260821_v10"
canonical="$repo_root/runs/new_gt_edit_repair_bulk_20260821_v1/canonical_v2"
run_root="$repo_root/runs/new_gt_edit_repair_postfix_gate_20260821_v1"
python_runtime="$repo_root/harness/.venv/bin/python"
uv_python=(uv run --no-project --python "$python_runtime" -- python)
mkdir -p "$run_root/logs" "$run_root/edit" "$run_root/repair" "$run_root/images"

run_edit() {
  local count="$1" offset="$2"
  "${uv_python[@]}" reverse/construct_text_editing.py \
    --project-list "$pool_root/shards/edit/edit_mp_interaction2code_source_image.txt" \
    --output-dir "$run_root/edit/t$count" --screenshot-dir "$run_root/images/edit_t$count" \
    --canonical-screenshot-dir "$canonical" --workers 1 --limit 8 --offset "$offset" \
    --min-tasks "$count" --max-tasks "$count" --success-target 1 --seed 20260821 \
    --max-retries 3 --max-output-tokens 8192 --edit-profile interaction2code \
    --page-scope mp --image-input-variants source_image --browser-proxy "" \
    >> "$run_root/logs/edit_t$count.log" 2>&1
}

run_repair() {
  local family="$1" count="$2" strategy="$3"
  local shard="repair_mp_${family}_t${count}_${strategy}"
  "${uv_python[@]}" reverse/construct_text_repair.py \
    --project-list "$pool_root/shards/repair/$shard.txt" \
    --output-dir "$run_root/repair/$shard" --defect-screenshot-dir "$run_root/images/$shard" \
    --canonical-screenshot-dir "$canonical" --workers 1 --limit 8 \
    --min-tasks "$count" --max-tasks "$count" --image-repair-target 1 --seed 20260821 \
    --max-retries 3 --max-output-tokens 8192 --repair-profile taxonomy \
    --assigned-family "$family" --page-scope mp --injection-strategy "$strategy" \
    --browser-proxy "" --minimum-changed-ratio 0.01 \
    >> "$run_root/logs/${shard}.log" 2>&1
}

{
  echo "started_at=$(date --iso-8601=seconds)"
  echo "model=$OPENAI_MODEL"
  echo "pool_root=$pool_root"
} | tee -a "$run_root/run.log"

set +e
pids=()
names=()
for spec in "1 0" "3 8" "5 16" "7 24"; do
  read -r count offset <<< "$spec"
  run_edit "$count" "$offset" & pids+=("$!"); names+=("edit_t$count")
done
for spec in "runtime_repair 3 rule" "visual_repair 3 llm" \
            "interaction_repair 1 llm" "quality_refinement 3 llm"; do
  read -r family count strategy <<< "$spec"
  run_repair "$family" "$count" "$strategy" & pids+=("$!"); names+=("${family}_t${count}_${strategy}")
done

failed=0
for index in "${!pids[@]}"; do
  status=0
  wait "${pids[$index]}" || status=$?
  echo "gate=${names[$index]} exit_status=$status" | tee -a "$run_root/run.log"
  [[ "$status" -eq 0 ]] || failed=1
done
echo "completed_at=$(date --iso-8601=seconds)" | tee -a "$run_root/run.log"
exit "$failed"
