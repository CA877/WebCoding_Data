#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
cd "$repo_root"

IFS= read -r OPENAI_API_KEY
export OPENAI_API_KEY
export RUN_ROOT="${RUN_ROOT:-$repo_root/runs/new_gt_edit_repair_bulk_20260821_v1}"
export EDIT_DATA_ROOT="${EDIT_DATA_ROOT:-$RUN_ROOT/edit_webcompass_source}"
export REPAIR_DATA_ROOT="${REPAIR_DATA_ROOT:-$RUN_ROOT/repair}"
export EDIT_CONCURRENCY="${EDIT_CONCURRENCY:-27}"
export REPAIR_CONCURRENCY="${REPAIR_CONCURRENCY:-5}"

launcher_log="$RUN_ROOT/logs/webcompass_source_launcher.log"
pid_file="$RUN_ROOT/logs/webcompass_source_launcher.pid"
mkdir -p "$RUN_ROOT/logs"

nohup bash reverse/run_new_gt_edit_repair_shards_only_20260821.sh \
  >> "$launcher_log" 2>&1 &
pid=$!
printf '%s\n' "$pid" > "$pid_file"
printf 'pid=%s\nlog=%s\nedit_data_root=%s\nrepair_data_root=%s\n' \
  "$pid" "$launcher_log" "$EDIT_DATA_ROOT" "$REPAIR_DATA_ROOT"
