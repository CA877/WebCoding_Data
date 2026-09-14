#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
cd "$repo_root"
IFS= read -r OPENAI_API_KEY
export OPENAI_API_KEY EDIT_CONCURRENCY="${EDIT_CONCURRENCY:-22}" REPAIR_CONCURRENCY="${REPAIR_CONCURRENCY:-10}"
run_root="$repo_root/runs/new_gt_webcompass_task_count_supplements_20260822_v1"
mkdir -p "$run_root/logs/tail_v1"
nohup bash reverse/run_edit_repair_tail_microshards_20260822.sh >> "$run_root/logs/tail_v1/launcher.log" 2>&1 &
pid=$!
printf '%s\n' "$pid" > "$run_root/logs/tail_v1/launcher.pid"
printf 'pid=%s\n' "$pid"
