#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
cd "$repo_root"

IFS= read -r OPENAI_API_KEY
export OPENAI_API_KEY
export EDIT_CONCURRENCY="${EDIT_CONCURRENCY:-27}"
export REPAIR_CONCURRENCY="${REPAIR_CONCURRENCY:-5}"
run_root="${RUN_ROOT:-$repo_root/runs/new_gt_webcompass_task_count_supplements_20260822_v1}"
mkdir -p "$run_root/logs"

nohup bash reverse/run_webcompass_task_count_supplements_20260822.sh \
  >> "$run_root/logs/launcher.log" 2>&1 &
pid=$!
printf '%s\n' "$pid" > "$run_root/logs/launcher.pid"
printf 'pid=%s\nlog=%s\nrun_root=%s\n' "$pid" "$run_root/logs/launcher.log" "$run_root"
