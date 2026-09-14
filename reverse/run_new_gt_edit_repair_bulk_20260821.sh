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
export CONSTRUCT_API_TIMEOUT=600 CONSTRUCT_STREAM=1 CONSTRUCT_TRANSPORT_ATTEMPTS=2

pool_root="${POOL_ROOT:-$repo_root/datasets/new_gt_edit_repair_mother_pools_20260821_v9}"
run_root="${RUN_ROOT:-$repo_root/runs/new_gt_edit_repair_bulk_20260821_v1}"
legacy_cache_root="$run_root/canonical"
cache_root="$run_root/canonical_v2"
canonical_ledger="$run_root/canonical_v2.jsonl"
log_root="$run_root/logs"
python_bin="$repo_root/harness/.venv/bin/python"
manifest="$pool_root/shards/quota_manifest.json"
mkdir -p "$log_root/canonical" "$log_root/edit" "$log_root/repair"

{
  echo "started_at=$(date --iso-8601=seconds)"
  echo "pool_root=$pool_root"
  echo "run_root=$run_root"
  echo "model=$OPENAI_MODEL"
  echo "canonical_workers=24"
  echo "constructor_process_limit=32"
} | tee -a "$log_root/run.log"

# Retry only unfinished/error screenshot cases. Successful canonical manifests
# are immutable and are skipped on every later pass.
for attempt in 1 2 3; do
  "$python_bin" scripts/prepare_canonical_screenshot_cache.py \
    --project-list "$pool_root/canonical_all_projects.txt" \
    --cache-root "$cache_root" --ledger "$canonical_ledger" \
    --reuse-cache-root "$legacy_cache_root" \
    --workers 24 --browser-proxy "" \
    2>&1 | tee "$log_root/canonical/attempt_${attempt}.log"
done

"$python_bin" scripts/build_new_gt_image_generate_v2.py \
  --mother-pool "$pool_root/image_generate_mothers.jsonl" \
  --canonical-screenshot-dir "$cache_root" \
  --output-jsonl "$run_root/image-generate.v2.jsonl" --expected 5000 \
  2>&1 | tee "$log_root/image_generate.log"

run_edit_shard() {
  local name="$1" scope="$2" profile="$3" variant="$4" target="$5" project_list="$6"
  "$python_bin" reverse/construct_text_editing.py \
    --project-list "$project_list" --output-dir "$run_root/edit/$name" \
    --screenshot-dir "$run_root/images/edit/$name" --canonical-screenshot-dir "$cache_root" \
    --workers 1 --min-tasks 1 --max-tasks 7 --success-target "$target" --seed 20260821 \
    --edit-profile "$profile" --page-scope "$scope" --image-input-variants "$variant" \
    --browser-proxy "" > "$log_root/edit/$name.log" 2>&1
}

run_repair_shard() {
  local name="$1" scope="$2" family="$3" task_count="$4" injection="$5" target="$6" project_list="$7"
  "$python_bin" reverse/construct_text_repair.py \
    --project-list "$project_list" --output-dir "$run_root/repair/$name" \
    --defect-screenshot-dir "$run_root/images/repair/$name" --canonical-screenshot-dir "$cache_root" \
    --workers 1 --min-tasks "$task_count" --max-tasks "$task_count" \
    --image-repair-target "$target" --seed 20260821 --repair-profile taxonomy \
    --assigned-family "$family" --page-scope "$scope" --injection-strategy "$injection" \
    --browser-proxy "" --minimum-changed-ratio 0.01 > "$log_root/repair/$name.log" 2>&1
}

wait_group() {
  local active=0 failed=0
  while IFS=$'\t' read -r kind name scope field1 field2 target project_list; do
    if [[ "$kind" == "edit" ]]; then
      run_edit_shard "$name" "$scope" "$field1" "$field2" "$target" "$project_list" &
    else
      local family="${field1%%|*}" task_count="${field1##*|}"
      run_repair_shard "$name" "$scope" "$family" "$task_count" "$field2" "$target" "$project_list" &
    fi
    active=$((active + 1))
    if [[ "$active" -ge 32 ]]; then
      wait -n || failed=1
      active=$((active - 1))
    fi
  done
  while [[ "$active" -gt 0 ]]; do
    wait -n || failed=1
    active=$((active - 1))
  done
  return "$failed"
}

edit_rows() {
  "$python_bin" - "$manifest" <<'PY'
import json, sys
for row in json.load(open(sys.argv[1], encoding="utf-8"))["edit"]:
    print("\t".join(map(str, ["edit", row["name"], row["page_scope"], row["profile"],
        row["image_input_variant"], row["success_target"], row["project_list"]])))
PY
}

repair_rows() {
  "$python_bin" - "$manifest" <<'PY'
import json, sys
for row in json.load(open(sys.argv[1], encoding="utf-8"))["repair"]:
    print("\t".join(map(str, ["repair", row["name"], row["page_scope"],
        row["repair_family"] + "|" + str(row["task_count"]), row["injection_strategy"],
        row["image_success_target"], row["project_list"]])))
PY
}

wait_group < <(edit_rows)
wait_group < <(repair_rows)

"$python_bin" - "$run_root" <<'PY' | tee "$log_root/final_counts.json"
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
def count(pattern):
    total = 0
    for path in root.glob(pattern):
        total += sum(1 for line in path.open(encoding="utf-8") if line.strip())
    return total
counts = {
    "image_generate": count("image-generate.v2.jsonl"),
    "text_edit": count("edit/*/text-edit.v2.jsonl"),
    "image_edit": count("edit/*/image-edit.v2.jsonl"),
    "text_repair": count("repair/*/text-repair.v2.jsonl"),
    "image_repair": count("repair/*/image-repair.v2.jsonl"),
}
print(json.dumps(counts, ensure_ascii=False))
if counts["image_generate"] != 5000 or counts["text_edit"] != 3000 or counts["image_edit"] != 3000 or counts["image_repair"] != 3000:
    raise SystemExit(5)
PY

echo "completed_at=$(date --iso-8601=seconds)" | tee "$run_root/COMPLETE"
