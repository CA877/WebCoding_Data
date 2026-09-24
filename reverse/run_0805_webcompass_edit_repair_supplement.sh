#!/usr/bin/env bash
# Run the bounded 0805_supplement -> WebCompass-aligned Edit/Repair plan.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
cd "$repo_root"

pool_root="${POOL_ROOT:-$repo_root/datasets/0805_webcompass_edit_repair_plan_20260906_v2}"
manifest="$pool_root/quota_manifest.json"
run_root="${RUN_ROOT:-$repo_root/runs/0805_webcompass_edit_repair_20260906_v2}"
canonical_root="${CANONICAL_ROOT:-}"
mode="${MODE:-pilot}"
confirm_bulk="${CONFIRM_BULK:-0}"
allow_concurrent_generate="${ALLOW_CONCURRENT_GENERATE:-0}"
shard_timeout_seconds="${SHARD_TIMEOUT_SECONDS:-7200}"
max_total_target="${MAX_TOTAL_TARGET:-4000}"
python_bin="${PYTHON_BIN:-$repo_root/harness/.venv/bin/python}"

[[ -f "$manifest" ]] || { echo "missing manifest: $manifest" >&2; exit 2; }
[[ -d "$canonical_root" ]] || { echo "set CANONICAL_ROOT to the immutable mother screenshot cache" >&2; exit 2; }
[[ -x "$python_bin" ]] || { echo "missing lora python: $python_bin" >&2; exit 2; }
[[ "$mode" == "pilot" || "$mode" == "bulk" ]] || { echo "MODE must be pilot or bulk" >&2; exit 2; }
if [[ "$mode" == "bulk" && "$confirm_bulk" != "1" ]]; then
  echo "bulk mode requires CONFIRM_BULK=1 after the four-lane pilot is accepted" >&2
  exit 2
fi
if [[ -z "${OPENAI_API_KEY:-${KIMI_API_KEY:-}}" ]]; then
  echo "inject OPENAI_API_KEY or KIMI_API_KEY through the inherited environment" >&2
  exit 2
fi
if [[ "$allow_concurrent_generate" != "1" ]] && command -v systemctl >/dev/null 2>&1; then
  if systemctl --user --no-legend --state=running --type=service 2>/dev/null \
      | grep -Eqi 'image[-_ ]?generate|0805-supplement-api'; then
    echo "an Image Generate service is active; wait for it to finish or explicitly set ALLOW_CONCURRENT_GENERATE=1" >&2
    exit 3
  fi
fi

total_target="$($python_bin - "$manifest" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
print(sum(int(row["success_target"]) for row in data["work"]))
PY
)"
if (( total_target > max_total_target )); then
  echo "planned target $total_target exceeds MAX_TOTAL_TARGET=$max_total_target" >&2
  exit 2
fi

export PYTHONUNBUFFERED=1
export CONSTRUCT_API_TIMEOUT="${CONSTRUCT_API_TIMEOUT:-240}"
export CONSTRUCT_TRANSPORT_ATTEMPTS=1
export CONSTRUCT_STREAM=1
unset ALL_PROXY HTTPS_PROXY HTTP_PROXY all_proxy https_proxy http_proxy
export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1}"

mkdir -p "$run_root/logs" "$run_root/images"
batch_log="$run_root/logs/batch.log"
child_pid=""
heartbeat_pid=""
cleanup() {
  [[ -z "$heartbeat_pid" ]] || kill "$heartbeat_pid" 2>/dev/null || true
  [[ -z "$child_pid" ]] || kill "$child_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

heartbeat() {
  local label="$1" output="$2"
  while [[ -n "$child_pid" ]] && kill -0 "$child_pid" 2>/dev/null; do
    local count=0
    if [[ -f "$output" ]]; then count=$(wc -l < "$output"); fi
    printf '%s heartbeat shard=%s records=%s\n' "$(date --iso-8601=seconds)" "$label" "$count" | tee -a "$batch_log"
    sleep 30
  done
}

run_constructor() {
  local family="$1" scope="$2" task_count="$3" target="$4" relative_list="$5" prefix="$6"
  local name="${family}_${scope}_t$(printf '%02d' "$task_count")"
  local project_list="$pool_root/$relative_list"
  # Pilot and bulk share append-only outputs. A successful pilot row is reused;
  # an unsuccessful attempted ID is also skipped, so no paid mother is retried.
  local output_dir="$run_root/data/$family/$name"
  local image_dir="$run_root/images/$family/$name"
  local effective_target="$target"
  local effective_list="$project_list"
  local pilot_list=""
  [[ -f "$project_list" ]] || { echo "missing project list: $project_list" >&2; return 2; }
  if [[ "$mode" == "pilot" ]]; then
    effective_target=1
    pilot_list=$(mktemp "$run_root/.pilot-${name}.XXXXXX")
    head -n 1 "$project_list" > "$pilot_list"
    effective_list="$pilot_list"
  fi
  mkdir -p "$output_dir" "$image_dir"
  local output_record="$output_dir/image-${family}.v2.jsonl"
  local log="$run_root/logs/${mode}_${name}.log"
  local command=(
    "$python_bin"
  )
  if [[ "$family" == "edit" ]]; then
    command+=(reverse/edit/query/construct.py
      --project-list "$effective_list" --output-dir "$output_dir"
      --screenshot-dir "$image_dir" --canonical-screenshot-dir "$canonical_root"
      --workers 1 --min-tasks "$task_count" --max-tasks "$task_count"
      --success-target "$effective_target" --seed 20260906 --max-retries 1
      --max-output-tokens 16384 --edit-profile webcompass --page-scope "$scope"
      --instance-id-prefix "$prefix" --skip-attempted
      --image-input-variants source_image --browser-proxy "")
  else
    command+=(reverse/repair/gt/construct.py
      --project-list "$effective_list" --output-dir "$output_dir"
      --defect-screenshot-dir "$image_dir" --canonical-screenshot-dir "$canonical_root"
      --workers 1 --min-tasks "$task_count" --max-tasks "$task_count"
      --image-repair-target "$effective_target" --seed 20260906 --max-retries 1
      --max-output-tokens 16384 --repair-profile webcompass --page-scope "$scope"
      --instance-id-prefix "$prefix" --skip-attempted
      --injection-strategy llm --browser-proxy ""
      --minimum-changed-ratio 0.01)
  fi
  printf '%s start shard=%s target=%s candidates=%s\n' \
    "$(date --iso-8601=seconds)" "$name" "$effective_target" "$(wc -l < "$effective_list")" | tee -a "$batch_log"
  timeout --signal=TERM --kill-after=30 "$shard_timeout_seconds" \
    "${command[@]}" > "$log" 2>&1 &
  child_pid=$!
  heartbeat "$name" "$output_record" & heartbeat_pid=$!
  local status=0
  wait "$child_pid" || status=$?
  child_pid=""
  kill "$heartbeat_pid" 2>/dev/null || true
  wait "$heartbeat_pid" 2>/dev/null || true
  heartbeat_pid=""
  [[ -z "$pilot_list" ]] || rm -f "$pilot_list"
  local accepted=0
  if [[ -f "$output_record" ]]; then accepted=$(wc -l < "$output_record"); fi
  if (( accepted < effective_target )); then
    echo "shard $name accepted $accepted/$effective_target" >> "$log"
    status=4
  fi
  printf '%s finish shard=%s status=%s\n' "$(date --iso-8601=seconds)" "$name" "$status" | tee -a "$batch_log"
  return "$status"
}

work_rows() {
  "$python_bin" - "$manifest" "$mode" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
mode = sys.argv[2]
rows = data["work"]
if mode == "pilot":
    chosen = []
    for family, scope in (("edit", "mp"), ("edit", "sp"), ("repair", "mp"), ("repair", "sp")):
        chosen.append(next(row for row in rows if row["family"] == family and row["page_scope"] == scope))
    rows = chosen
for row in rows:
    print("\t".join(str(row[key]) for key in (
        "family", "page_scope", "task_count", "success_target", "project_list", "instance_id_prefix"
    )))
PY
}

printf '%s mode=%s total_target=%s manifest=%s\n' \
  "$(date --iso-8601=seconds)" "$mode" "$total_target" "$manifest" | tee -a "$batch_log"
while IFS=$'\t' read -r family scope task_count target project_list prefix; do
  run_constructor "$family" "$scope" "$task_count" "$target" "$project_list" "$prefix"
done < <(work_rows)
printf '%s status=finished mode=%s\n' "$(date --iso-8601=seconds)" "$mode" | tee -a "$batch_log"
