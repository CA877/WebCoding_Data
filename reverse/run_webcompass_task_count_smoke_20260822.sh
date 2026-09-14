#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
cd "$repo_root"

IFS= read -r OPENAI_API_KEY
export OPENAI_API_KEY
export OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export OPENAI_MODEL="qwen3.8-max"
unset ALL_PROXY HTTPS_PROXY HTTP_PROXY all_proxy https_proxy http_proxy
export NO_PROXY="idealab.alibaba-inc.com,alibaba-inc.com,api.deepseek.com,localhost,127.0.0.1"
export SSL_NO_VERIFY=1 CONSTRUCT_STREAM=1 CONSTRUCT_TRANSPORT_ATTEMPTS=2
export PYTHONUNBUFFERED=1
export CONSTRUCT_API_TIMEOUT="${CONSTRUCT_API_TIMEOUT:-240}"
export QWEN_TOKENIZER_JSON="$repo_root/.cache/qwen3-tokenizer.json"
export PATH="/data1/xieqianqian/webcoding/.local/bin:$PATH"

pool_root="$repo_root/datasets/new_gt_webcompass_task_count_supplements_20260822_v1"
run_root="$repo_root/runs/new_gt_webcompass_task_count_smoke_20260822_v1"
canonical_root="$repo_root/runs/new_gt_edit_repair_bulk_20260821_v1/canonical_v2"
manifest="$pool_root/quota_manifest.json"
python_runtime="$repo_root/harness/.venv/bin/python"
uv_python=(uv run --no-project --python "$python_runtime" -- python)
mkdir -p "$run_root/logs" "$run_root/lists"

"${uv_python[@]}" - "$manifest" "$run_root/lists" <<'PY'
import json, sys
from pathlib import Path
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
out = Path(sys.argv[2])
for kind, predicate in (
    ("edit", lambda row: row["task_count"] == 12 and row["page_scope"] == "mp" and row["profile"] == "webcompass"),
    ("repair", lambda row: row["task_count"] == 12 and row["page_scope"] == "mp" and row["injection_strategy"] == "llm"),
):
    row = next(row for row in manifest[kind] if predicate(row))
    candidates = Path(row["project_list"]).read_text(encoding="utf-8").splitlines()
    (out / f"{kind}.txt").write_text("\n".join(candidates[:3]) + "\n", encoding="utf-8")
PY

{
  echo "started_at=$(date --iso-8601=seconds)"
  echo "model=$OPENAI_MODEL"
  echo "network_mode=direct"
  echo "task_count=12"
} | tee -a "$run_root/logs/smoke.log"

"${uv_python[@]}" reverse/construct_text_editing.py \
  --project-list "$run_root/lists/edit.txt" --output-dir "$run_root/edit" \
  --screenshot-dir "$run_root/images/edit" --canonical-screenshot-dir "$canonical_root" \
  --workers 1 --min-tasks 12 --max-tasks 12 --success-target 1 --seed 20260822 \
  --max-retries 3 --max-output-tokens 16384 --edit-profile webcompass --page-scope mp \
  --image-input-variants source_image --browser-proxy "" \
  2>&1 | tee -a "$run_root/logs/edit.log"

"${uv_python[@]}" reverse/construct_text_repair.py \
  --project-list "$run_root/lists/repair.txt" --output-dir "$run_root/repair" \
  --defect-screenshot-dir "$run_root/images/repair" --canonical-screenshot-dir "$canonical_root" \
  --workers 1 --min-tasks 12 --max-tasks 12 --image-repair-target 1 --seed 20260822 \
  --repair-profile taxonomy --mixed-families --max-retries 3 --max-output-tokens 16384 \
  --page-scope mp --injection-strategy llm --browser-proxy "" --minimum-changed-ratio 0.01 \
  2>&1 | tee -a "$run_root/logs/repair.log"

echo "completed_at=$(date --iso-8601=seconds)" | tee -a "$run_root/logs/smoke.log"
