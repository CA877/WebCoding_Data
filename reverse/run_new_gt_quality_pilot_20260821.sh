#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
cd "$repo_root"

pool_root="${POOL_ROOT:-$repo_root/datasets/new_gt_edit_repair_mother_pools_20260821_v5}"
run_root="${RUN_ROOT:-$repo_root/runs/new_gt_edit_repair_quality_pilot_20260821_v1}"
cache_root="${CANONICAL_ROOT:-$run_root/canonical}"
log_root="$run_root/logs"
mkdir -p "$log_root"

api_doc="${DASHSCOPE_API_DOC:-$repo_root/docs/项目用api.pdf}"
if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  if command -v pdftotext >/dev/null 2>&1; then
    OPENAI_API_KEY="$(pdftotext -layout "$api_doc" - | sed -nE 's/.*(sk-[A-Za-z0-9_-]{20,}).*/\1/p' | head -n 1)"
  else
    OPENAI_API_KEY="$("$repo_root/harness/.venv/bin/python" scripts/extract_dashscope_key.py "$api_doc")"
  fi
fi
test -n "$OPENAI_API_KEY"
export OPENAI_API_KEY
export OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export OPENAI_MODEL="qwen3.8-max"
unset ALL_PROXY HTTPS_PROXY HTTP_PROXY all_proxy https_proxy http_proxy
export NO_PROXY="idealab.alibaba-inc.com,alibaba-inc.com,api.deepseek.com,localhost,127.0.0.1"
export SSL_NO_VERIFY=1
export QWEN_TOKENIZER_JSON="$repo_root/.cache/qwen3-tokenizer.json"
export CONSTRUCT_API_TIMEOUT=600 CONSTRUCT_STREAM=1 CONSTRUCT_TRANSPORT_ATTEMPTS=2
python_bin="$repo_root/harness/.venv/bin/python"

edit_mp="$pool_root/shards/edit/edit_mp_interaction2code_source_target_images_no_query.txt"
edit_sp="$pool_root/shards/edit/edit_sp_webcompass_target_image.txt"
repair_runtime="$pool_root/shards/repair/repair_mp_runtime_repair_t1_llm.txt"
repair_visual="$pool_root/shards/repair/repair_mp_visual_repair_t1_llm.txt"
repair_interaction="$pool_root/shards/repair/repair_mp_interaction_repair_t1_llm.txt"
repair_quality_rule="$pool_root/shards/repair/repair_mp_quality_refinement_t1_rule.txt"

for project_list in "$edit_mp" "$edit_sp" "$repair_runtime" "$repair_visual" "$repair_interaction" "$repair_quality_rule"; do
  "$python_bin" scripts/prepare_canonical_screenshot_cache.py \
    --project-list "$project_list" --cache-root "$cache_root" \
    --ledger "$run_root/canonical.jsonl" --workers 4 --limit 5 --browser-proxy "" \
    2>&1 | tee -a "$log_root/canonical.log"
done

if [[ "${SKIP_EDIT:-0}" != "1" ]]; then
"$python_bin" reverse/construct_text_editing.py \
  --project-list "$edit_mp" --output-dir "$run_root/edit_mp" \
  --screenshot-dir "$run_root/images/edit_mp" --canonical-screenshot-dir "$cache_root" \
  --workers 1 --min-tasks 1 --max-tasks 1 --success-target 1 --seed 20260821 \
  --edit-profile interaction2code --page-scope mp \
  --image-input-variants source_target_images_no_query --browser-proxy "" \
  2>&1 | tee "$log_root/edit_mp.log"

"$python_bin" reverse/construct_text_editing.py \
  --project-list "$edit_sp" --output-dir "$run_root/edit_sp" \
  --screenshot-dir "$run_root/images/edit_sp" --canonical-screenshot-dir "$cache_root" \
  --workers 1 --min-tasks 1 --max-tasks 1 --success-target 1 --seed 20260821 \
  --edit-profile webcompass --page-scope sp \
  --image-input-variants target_image --browser-proxy "" \
  2>&1 | tee "$log_root/edit_sp.log"
fi

run_repair() {
  local name="$1" family="$2" strategy="$3" project_list="$4"
  "$python_bin" reverse/construct_text_repair.py \
    --project-list "$project_list" --output-dir "$run_root/$name" \
    --defect-screenshot-dir "$run_root/images/$name" --canonical-screenshot-dir "$cache_root" \
    --workers 1 --min-tasks 1 --max-tasks 1 --image-repair-target 1 --seed 20260821 \
    --repair-profile taxonomy --assigned-family "$family" --page-scope mp \
    --injection-strategy "$strategy" --browser-proxy "" --minimum-changed-ratio 0.01 \
    2>&1 | tee "$log_root/$name.log"
}

run_repair repair_runtime runtime_repair llm "$repair_runtime"
run_repair repair_visual visual_repair llm "$repair_visual"
run_repair repair_interaction interaction_repair llm "$repair_interaction"
run_repair repair_quality_rule quality_refinement rule "$repair_quality_rule"

echo "quality_pilot_complete_at=$(date --iso-8601=seconds)" | tee "$run_root/COMPLETE"
