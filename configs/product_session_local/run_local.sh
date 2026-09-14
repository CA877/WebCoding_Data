#!/bin/zsh
set -euo pipefail

if (( $# != 5 )); then
  echo "usage: $0 RUN_ROOT SEED_SOURCE SEED_EVALUATION LIBRARY_ROOT HARNESS_ROOT" >&2
  exit 2
fi

run_root="${1:A}"
seed_source="${2:A}"
seed_evaluation="${3:A}"
library_root="${4:A}"
harness_root="${5:A}"
data_root="${0:A:h:h:h}"
proxy_url="${TOKENWAVE_API_PROXY:-http://127.0.0.1:7897}"

: "${TOKENWAVE_OPENAI_API_KEY:?TOKENWAVE_OPENAI_API_KEY is required}"

mkdir -p "$run_root/local_runtime"
if [[ -f "$run_root/autonomous.pid" ]] && kill -0 "$(cat "$run_root/autonomous.pid")" 2>/dev/null; then
  echo "This run is already active" >&2
  exit 1
fi
cat > "$run_root/local_runtime/harness-python" <<EOF
#!/bin/zsh
exec "$harness_root/.venv/bin/python" "\$@"
EOF
chmod +x "$run_root/local_runtime/harness-python"

if [[ ! -f "$run_root/jobs.jsonl" ]]; then
cp -R "$seed_source" "$run_root/seed"
mkdir -p "$run_root/preflight"
cp "$seed_evaluation" "$run_root/preflight/seed.json"
python3 - "$run_root" <<'PY'
import json
import sys
from pathlib import Path

run = Path(sys.argv[1]).resolve()
seed = {
    "seed_id": "local_multipage_seed",
    "project_path": str(run / "seed"),
    "evaluation": str(run / "preflight" / "seed.json"),
}
(run / "seed.json").write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n")
job = {"seed": str(run / "seed.json"), "run_dir": str(run / "session")}
(run / "jobs.jsonl").write_text(json.dumps(job, ensure_ascii=False) + "\n")
PY
fi

command=(
  "$data_root/.venv/bin/python"
  "$data_root/scripts/run_product_edit_batch.py"
  --manifest "$run_root/jobs.jsonl"
  --max-sessions 1
  --output "$run_root/batch"
  --library "$library_root"
  --harness-root "$harness_root"
  --harness-python "$run_root/local_runtime/harness-python"
  --api-proxy "$proxy_url"
  --no-api-budget
  --transient-retries 20
)

python3 - "$run_root" "${command[@]}" <<'PY'
import os
import subprocess
import sys
from pathlib import Path

run = Path(sys.argv[1])
log = (run / "autonomous.log").open("ab", buffering=0)
proc = subprocess.Popen(
    sys.argv[2:],
    cwd=sys.argv[2].rsplit("/", 3)[0],
    env=os.environ.copy(),
    stdin=subprocess.DEVNULL,
    stdout=log,
    stderr=subprocess.STDOUT,
    start_new_session=True,
    close_fds=True,
)
(run / "autonomous.pid").write_text(f"{proc.pid}\n")
print(proc.pid)
PY
