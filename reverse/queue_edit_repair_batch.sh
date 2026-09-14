#!/usr/bin/env bash
# Queue the production Edit/Repair constructors behind known Doc API jobs.
# The caller injects OPENAI_API_KEY through the process environment. The key is
# never written to this script, the queue log, command-line arguments, or data.
set -euo pipefail

: "${OPENAI_API_KEY:?Inject the Doc API key through the inherited environment}"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
cd "$repo_root"

output_root="${OUTPUT_ROOT:-$repo_root/runs/edit_repair_interaction_taxonomy_batch_20260821_v1}"
edit_list="${EDIT_PROJECT_LIST:-$repo_root/runs/webcompass_6503_production_20260805/edit_3000.txt}"
repair_list="${REPAIR_PROJECT_LIST:-$repo_root/runs/webcompass_6503_production_20260805/repair_candidates_6502.txt}"
wait_pids="${WAIT_PIDS:-}"
queue_log_dir="${QUEUE_LOG_DIR:-$output_root/logs/queue}"
mkdir -p "$queue_log_dir"
queue_log="$queue_log_dir/queue.log"

{
  echo "queue_started_at=$(date --iso-8601=seconds)"
  echo "output_root=$output_root"
  echo "edit_project_list=$edit_list"
  echo "repair_project_list=$repair_list"
  echo "wait_pids=$wait_pids"
  echo "planned_workers=edit:24,repair:8,total:32"
} | tee -a "$queue_log"

for pid in $wait_pids; do
  if kill -0 "$pid" 2>/dev/null; then
    echo "waiting_for_pid=$pid" | tee -a "$queue_log"
    # GNU tail provides a non-busy process wait and returns when PID exits.
    tail --pid="$pid" -f /dev/null
    echo "wait_pid_finished=$pid at=$(date --iso-8601=seconds)" | tee -a "$queue_log"
  else
    echo "wait_pid_already_finished=$pid" | tee -a "$queue_log"
  fi
done

echo "batch_launch_at=$(date --iso-8601=seconds)" | tee -a "$queue_log"

env API_PROFILE=inherited_doc TASKS=edit \
  EDIT_PROJECT_LIST="$edit_list" OUTPUT_ROOT="$output_root" \
  LOG_DIR="$output_root/logs/edit" EDIT_WORKERS=24 REPAIR_WORKERS=0 \
  EDIT_PROFILE=balanced EDIT_PAGE_SCOPE=any \
  IMAGE_INPUT_VARIANTS=source_image,target_image,source_target_images \
  PYTHONUNBUFFERED=1 \
  bash reverse/run_edit_repair_batch.sh \
  > "$queue_log_dir/edit_launcher.log" 2>&1 &
edit_pid=$!

env API_PROFILE=inherited_doc TASKS=repair \
  REPAIR_PROJECT_LIST="$repair_list" OUTPUT_ROOT="$output_root" \
  LOG_DIR="$output_root/logs/repair" EDIT_WORKERS=0 REPAIR_WORKERS=8 \
  REPAIR_PROFILE=taxonomy REPAIR_PAGE_SCOPE=any IMAGE_REPAIR_TARGET=3000 \
  PYTHONUNBUFFERED=1 \
  bash reverse/run_edit_repair_batch.sh \
  > "$queue_log_dir/repair_launcher.log" 2>&1 &
repair_pid=$!

{
  echo "edit_pid=$edit_pid"
  echo "repair_pid=$repair_pid"
} | tee -a "$queue_log"

set +e
wait "$edit_pid"
edit_status=$?
wait "$repair_pid"
repair_status=$?
set -e

{
  echo "edit_exit_status=$edit_status"
  echo "repair_exit_status=$repair_status"
  echo "queue_finished_at=$(date --iso-8601=seconds)"
} | tee -a "$queue_log"

if [[ "$edit_status" -ne 0 || "$repair_status" -ne 0 ]]; then
  exit 1
fi
