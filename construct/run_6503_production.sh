#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON_BIN="${PYTHON_BIN:-$REPO_ROOT/web-coding-agent/.conda/lora/bin/python}"
PRODUCTION_ROOT="${PRODUCTION_ROOT:-runs/webcompass_6503_production_20260805}"
RELEASE_ROOT="${RELEASE_ROOT:-releases/webcompass_6503_sft_v2_20260806}"
SOURCE_JSONL="${SOURCE_JSONL:-/data1/xieqianqian/webcoding/data/20260804/all_merged_instructions/sft_train/train_sharegpt_webcompass_only_6503.jsonl}"
EDIT_WORKERS="${EDIT_WORKERS:-16}"
REPAIR_WORKERS="${REPAIR_WORKERS:-16}"
IMAGE_REPAIR_TARGET="${IMAGE_REPAIR_TARGET:-3000}"
SEED="${SEED:-20260805}"

if [[ $((EDIT_WORKERS + REPAIR_WORKERS)) -gt 32 ]]; then
  echo "edit + repair workers must not exceed 32" >&2
  exit 2
fi
if [[ -z "${KIMI_API_KEY:-${OPENAI_API_KEY:-}}" ]]; then
  echo "missing API key" >&2
  exit 2
fi

export ALL_PROXY="${ALL_PROXY:-http://127.0.0.1:7890}"
export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:7890}"
export HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:7890}"
export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1}"
export SSL_NO_VERIFY="${SSL_NO_VERIFY:-1}"
export CONSTRUCT_API_TIMEOUT="${CONSTRUCT_API_TIMEOUT:-600}"
export QWEN_TOKENIZER_JSON="${QWEN_TOKENIZER_JSON:-$REPO_ROOT/.cache/qwen3-tokenizer.json}"
export PYTHONUNBUFFERED=1

mkdir -p "$PRODUCTION_ROOT/logs" "$PRODUCTION_ROOT/generate" "$PRODUCTION_ROOT/edit" "$PRODUCTION_ROOT/repair"

while pgrep -f 'prepare_clean_screenshots.py.*missing_screenshots.txt' >/dev/null; do
  echo "waiting for existing image-generation screenshot workers..."
  sleep 30
done

while true; do
  : > "$PRODUCTION_ROOT/missing_screenshots.txt"
  while IFS= read -r project; do
    screenshot="$project/$(basename "$project")_clean.png"
    [[ -f "$screenshot" ]] || echo "$project" >> "$PRODUCTION_ROOT/missing_screenshots.txt"
  done < "$PRODUCTION_ROOT/eligible_40k_all_files.txt"
  missing="$(wc -l < "$PRODUCTION_ROOT/missing_screenshots.txt")"
  echo "image-generation screenshots missing=$missing"
  [[ "$missing" -eq 0 ]] && break
  "$PYTHON_BIN" scripts/prepare_clean_screenshots.py \
    --project-list "$PRODUCTION_ROOT/missing_screenshots.txt" \
    --browser-proxy http://127.0.0.1:7890 --width 1920 --height 1080 --workers 32 \
    >> "$PRODUCTION_ROOT/logs/image_generate_screenshots_supervised.log" 2>&1 || true
done

"$PYTHON_BIN" scripts/build_webcompass_generate_v2.py \
  --source-jsonl "$SOURCE_JSONL" \
  --project-list "$PRODUCTION_ROOT/eligible_40k_all_files.txt" \
  --token-audit "$PRODUCTION_ROOT/token_gate_audit.jsonl" \
  --text-output "$PRODUCTION_ROOT/generate/text-generate.v2.jsonl" \
  --image-output "$PRODUCTION_ROOT/generate/image-generate.v2.jsonl"

run_edit() {
  local previous=-1 stalls=0 count=0
  while [[ "$count" -lt 3000 ]]; do
    "$PYTHON_BIN" construct/construct_text_editing.py \
      --project-list "$PRODUCTION_ROOT/edit_3000.txt" \
      --output-dir "$PRODUCTION_ROOT/edit" \
      --screenshot-dir "$PRODUCTION_ROOT/images/image-edit" \
      --workers "$EDIT_WORKERS" --min-tasks 1 --max-tasks 7 --seed "$SEED" \
      --max-retries 3 --max-output-tokens 8192 --browser-proxy http://127.0.0.1:7890
    count="$(wc -l < "$PRODUCTION_ROOT/edit/text-edit.v2.jsonl")"
    echo "edit v2 count=$count"
    if [[ "$count" -eq "$previous" ]]; then
      stalls=$((stalls + 1))
      [[ "$stalls" -ge 3 ]] && return 3
    else
      stalls=0
    fi
    previous="$count"
  done
}

run_repair() {
  local previous=-1 stalls=0 count=0
  while [[ "$count" -lt "$IMAGE_REPAIR_TARGET" ]]; do
    "$PYTHON_BIN" construct/construct_text_repair.py \
      --project-list "$PRODUCTION_ROOT/repair_candidates_6502.txt" \
      --output-dir "$PRODUCTION_ROOT/repair" \
      --defect-screenshot-dir "$PRODUCTION_ROOT/images/image-repair/defective" \
      --clean-screenshot-dir "$PRODUCTION_ROOT/images/image-repair/clean" \
      --workers "$REPAIR_WORKERS" --min-tasks 1 --max-tasks 7 --seed "$SEED" \
      --max-retries 3 --max-output-tokens 8192 --browser-proxy http://127.0.0.1:7890 \
      --minimum-changed-ratio 0.01 --maximum-clean-rerender-ratio 0.002 \
      --image-repair-target "$IMAGE_REPAIR_TARGET"
    count="$(wc -l < "$PRODUCTION_ROOT/repair/image-repair.v2.jsonl")"
    echo "image-repair v2 count=$count"
    if [[ "$count" -eq "$previous" ]]; then
      stalls=$((stalls + 1))
      [[ "$stalls" -ge 3 ]] && return 3
    else
      stalls=0
    fi
    previous="$count"
  done
}

run_edit > "$PRODUCTION_ROOT/logs/edit_production.log" 2>&1 &
edit_pid=$!
run_repair > "$PRODUCTION_ROOT/logs/repair_production.log" 2>&1 &
repair_pid=$!
echo "edit_pid=$edit_pid repair_pid=$repair_pid"

edit_status=0
repair_status=0
wait "$edit_pid" || edit_status=$?
wait "$repair_pid" || repair_status=$?
if [[ "$edit_status" -ne 0 || "$repair_status" -ne 0 ]]; then
  echo "construction failed: edit=$edit_status repair=$repair_status" >&2
  exit 3
fi

"$PYTHON_BIN" scripts/pack_construct_v2_release.py \
  --production-root "$PRODUCTION_ROOT" --release-root "$RELEASE_ROOT"
"$PYTHON_BIN" scripts/audit_construct_v2_release.py \
  --jsonl-dir "$RELEASE_ROOT/jsonl" --summary "$RELEASE_ROOT/audit_summary.json" \
  --expected-generate 6502 --expected-edit 3000 --expected-image-repair "$IMAGE_REPAIR_TARGET"
touch "$RELEASE_ROOT/COMPLETE"
echo "production complete: $RELEASE_ROOT"
