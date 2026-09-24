#!/usr/bin/env bash
# Bounded retry of the two completed plans; successful cases are always skipped.
set -u
py="$1"
code_root="$2"
data_root="$3"
key_file="$4"
workers="${5:-10}"
first_limit="${6:-62}"
second_limit="${7:-22}"
if ! [[ "$workers" =~ ^[0-9]+$ && "$first_limit" =~ ^[0-9]+$ && "$second_limit" =~ ^[0-9]+$ ]] ||
   (( workers < 1 || workers > 10 || first_limit < 1 || first_limit > 62 || second_limit < 1 || second_limit > 22 )); then
  exit 64
fi
child_pid=""
stop() {
  if [[ -n "$child_pid" ]]; then
    kill -TERM "$child_pid" 2>/dev/null || true
    wait "$child_pid" 2>/dev/null || true
  fi
  exit 130
}
trap stop INT TERM
run_child() {
  "$@" &
  child_pid=$!
  wait "$child_pid"
  local result=$?
  child_pid=""
  return "$result"
}
write_release() {
  run_child "$py" -u "$code_root/reverse/write_0921_release.py" once \
    --control "$data_root/runs/0921_release_writer_20260921"
}
write_release || exit $?
for spec in "0905_text_edit_instructions_luna_20260921:$first_limit" "0905_text_edit_instructions_8to12_combined_luna_20260921:$second_limit"; do
  run_name="${spec%:*}"
  case_limit="${spec##*:}"
  run_child "$py" -u "$code_root/reverse/edit/query/regenerate.py" run \
    --output-dir "$data_root/runs/$run_name" --workers "$workers" --limit "$case_limit" \
    --retry-failed --api-key-file "$key_file"
  generation_status=$?
  write_release || exit $?
  if [[ "$generation_status" -ne 0 ]]; then exit "$generation_status"; fi
done
