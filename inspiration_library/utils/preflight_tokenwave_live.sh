#!/usr/bin/env bash
# 在物理机上预检「灵感挖掘（live 浏览器 + LLM）」这条线能不能跑。
#
# 覆盖三件事：
#   1. 凭据注入：从受保护文件读 TokenWave key，映射成仓库约定的 DOC_API_KEY。
#      凭据只在内存里传递，不写进任何日志。
#   2. API 连通性：按 CLAUDE.md 要求，对 (有代理/无代理) × (流式/非流式)
#      四种组合各打一次真实请求，实测延迟，供后续脚本选最快方案。
#   3. 浏览器可用性：live 探索要开真浏览器，检查 playwright 自带 chromium 或系统 Chrome。
#
# 用法（在物理机上）：
#   bash inspiration_library/utils/preflight_tokenwave_live.sh
# 可用环境变量覆盖：VENV REPO LOG_ROOT PROBE_PROXY

set -euo pipefail

VENV="${VENV:-/data2/adminweihunj/webcoding/dataset_capability_study_20260914/venv}"
REPO="${REPO:-/data2/adminweihunj/webcoding/inspiration_library/code_debug_20260914}"
LOG_ROOT="${LOG_ROOT:-$REPO/logs/preflight_tokenwave_live}"
RUN_ID="$(date +%Y%m%d_%H%M)"
LOG_DIR="$LOG_ROOT/$RUN_ID"
mkdir -p "$LOG_DIR"
PY="$VENV/bin/python"

# 受保护凭据文件（0600）；不复制、不落盘
CRED_FILE="${CRED_FILE:-$HOME/.config/codex/tokenwave.env}"
if [ ! -f "$CRED_FILE" ]; then
  echo "missing credential file: $CRED_FILE" >&2
  exit 2
fi
# shellcheck disable=SC1090
. "$CRED_FILE"
export DOC_API_KEY="${TOKENWAVE_API_KEY:-}"
export DOC_API_BASE_URL="https://api.tokenwave.us/v1"
export DOC_API_CHAT_MODEL="${DOC_API_CHAT_MODEL:-gpt-5.5}"
if [ -z "$DOC_API_KEY" ]; then
  echo "credential file carried no TOKENWAVE_API_KEY" >&2
  exit 2
fi

# 浏览器爬网页才走代理；调 API 不走。这里显式清掉全局代理变量，
# 因为 DocApiClient 用 trust_env=False 本来就忽略它们，清掉是为了避免其它库误用。
unset ALL_PROXY HTTPS_PROXY HTTP_PROXY all_proxy https_proxy http_proxy 2>/dev/null || true
export NO_PROXY="api.tokenwave.us,localhost,127.0.0.1"

cd "$REPO"
echo "run_id=$RUN_ID"
echo "log_dir=$LOG_DIR"
echo "repo=$REPO"
echo "venv=$VENV"
echo "key_length=${#DOC_API_KEY}"          # 只报长度，不报内容
echo "base_url=$DOC_API_BASE_URL"
echo "chat_model=$DOC_API_CHAT_MODEL"
echo

echo "=== 1. API 连通性：四种组合实测 ==="
PROBE_PROXY="${PROBE_PROXY:-http://127.0.0.1:7890}"
"$PY" - "$PROBE_PROXY" <<'PY' 2>&1 | tee "$LOG_DIR/api_probe.log"
import os, sys, time, json
from pathlib import Path

proxy = sys.argv[1]
sys.path.insert(0, os.getcwd())
from inspiration_library.doc_api import DocApiClient

results = []
for label, use_proxy, stream in (
    ("direct/non-stream", False, False),
    ("direct/stream", False, True),
    ("proxy/non-stream", True, False),
    ("proxy/stream", True, True),
):
    os.environ.pop("DOC_API_PROXY", None)
    os.environ.pop("TOKENWAVE_API_PROXY", None)
    if use_proxy:
        os.environ["DOC_API_PROXY"] = proxy
    started = time.monotonic()
    row = {"combo": label, "status": "ok"}
    try:
        client = DocApiClient(api_key=os.environ["DOC_API_KEY"],
                              log_dir=Path("/tmp/preflight_provider"),
                              timeout_seconds=60, request_attempts=1)
        # DocApiClient 要求 system_prompt / stable_context / task 三段都非空，
        # 这里给一段与预检无关的中性上下文，只测通路与延迟。
        text, _ = client.chat_text(
            request_id=f"preflight_{label.replace('/', '_')}",
            system_prompt="Answer with one word.",
            stable_context="The user is checking connectivity.",
            task="Reply with exactly: ok",
            max_tokens=16,
            stream=stream,
            cache_stable_context=False,
        )
        row["reply_head"] = (text or "").strip()[:20]
    except Exception as exc:                                   # noqa: BLE001
        row["status"] = f"error:{type(exc).__name__}"
        row["error"] = str(exc)[:160].replace(os.environ["DOC_API_KEY"], "<redacted>")
    row["elapsed_sec"] = round(time.monotonic() - started, 2)
    results.append(row)
    print(json.dumps(row, ensure_ascii=False), flush=True)

ok = [r for r in results if r["status"] == "ok"]
if ok:
    best = min(ok, key=lambda r: r["elapsed_sec"])
    print(f"\nfastest_ok = {best['combo']} ({best['elapsed_sec']}s)")
else:
    print("\nno combo succeeded")
PY

echo
echo "=== 2. 浏览器可用性 ==="
# live 探索要开真浏览器。若 playwright 自带 chromium 缺失，这里按需安装；
# 安装走 7890（mihomo）下载，不经过 API 那条链路。
if [ "${INSTALL_BROWSER:-0}" = "1" ]; then
  echo "-- installing playwright chromium (via $PROBE_PROXY) --"
  HTTPS_PROXY="$PROBE_PROXY" HTTP_PROXY="$PROBE_PROXY" \
    "$PY" -m playwright install chromium 2>&1 | tee "$LOG_DIR/browser_install.log"
fi
"$PY" - <<'PY' 2>&1 | tee "$LOG_DIR/browser_check.log"
import sys
from pathlib import Path
sys.path.insert(0, ".")
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    bundled = Path(p.chromium.executable_path)
    print(f"bundled_chromium = {bundled} exists={bundled.exists()}")
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        print(f"system_chrome = ok ({browser.version})")
        browser.close()
except Exception as exc:                                        # noqa: BLE001
    print(f"system_chrome = unavailable ({type(exc).__name__})")
PY

echo
echo "logs -> $LOG_DIR"
