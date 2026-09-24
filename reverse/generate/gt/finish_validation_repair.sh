#!/usr/bin/env bash
set -euo pipefail

base="${1:?run base is required}"
current_repair_unit="${2:?current repair unit is required}"
browser="$base/batch/browser_results_v3_framework_20260924.jsonl"
repair="$base/batch/repair_results_v3_framework_20260924.jsonl"
total=4364

count_unique() {
  /usr/bin/python3 - "$1" <<'PY'
from pathlib import Path
import json, sys
p = Path(sys.argv[1])
ids = set()
if p.exists():
    for line in p.open(errors="ignore"):
        try:
            ids.add(json.loads(line)["project_id"])
        except Exception:
            pass
print(len(ids))
PY
}

while [[ "$(count_unique "$repair")" -lt "$total" ]]; do
  sleep 30
done
systemctl --user stop "$current_repair_unit.service" 2>/dev/null || true

export PLAYWRIGHT_MODULE=/home/adminweihunj/.npm/_npx/420ff84f11983ee5/node_modules/playwright
export CHROMIUM_EXECUTABLE=/home/adminweihunj/.cache/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-linux64/chrome-headless-shell

/home/adminweihunj/.local/bin/node "$base/code/validate.js" \
  --projects-dir "$base/batch/projects" --out "$browser" --workers 8 --limit 0 \
  --timeout 30000 --retry-status validator_error \
  --framework-builder "$base/code/build_vite_project.mjs" \
  --build-root "$base/browser_builds_v3" --build-timeout 120000

for pass in 1; do
  /usr/bin/python3 "$base/code/watch_repair.py" \
    --projects-dir "$base/batch/projects" --validation-results "$browser" \
    --repair-results "$repair" --backup-dir "$base/batch/repair_backups_v3_framework_20260924" \
    --validator-script "$base/code/validate.js" --node /home/adminweihunj/.local/bin/node \
    --playwright-module "$PLAYWRIGHT_MODULE" --chromium-executable "$CHROMIUM_EXECUTABLE" \
    --framework-builder "$base/code/build_vite_project.mjs" --build-root "$base/browser_builds_v3" \
    --build-timeout-ms 120000 --api-key-file /home/adminweihunj/.config/webcoding/credentials/njulink-luna.key \
    --base-url https://api.nju-link.com/v1 --model gpt-5.6-luna \
    --actor-authorization local-image-extension --workers 8 --retry-failed \
    --llm-attempts-per-case 3 --once
done

/usr/bin/python3 - "$browser" "$repair" "$base/batch/final_summary_v3_framework_20260924.json" <<'PY'
from pathlib import Path
import collections, json, sys

def latest(path):
    rows = {}
    for line in Path(path).open(errors="ignore"):
        try:
            row = json.loads(line)
            rows[row["project_id"]] = row
        except Exception:
            pass
    return rows

browser, repair = latest(sys.argv[1]), latest(sys.argv[2])
summary = {
    "browser_total": len(browser),
    "browser_status": dict(collections.Counter(row.get("status") for row in browser.values())),
    "repair_total": len(repair),
    "repair_status": dict(collections.Counter(row.get("status") for row in repair.values())),
}
Path(sys.argv[3]).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(summary, ensure_ascii=False), flush=True)
PY
