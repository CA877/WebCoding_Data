#!/usr/bin/env bash
# =============================================================================
# Pipeline A CLEAN ONLY TEST — 跑前 50 个 case，用于快速验证
#
# 用法:
#   bash preprocess/run_pipeline_a_clean_only_test.sh
# =============================================================================

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

ENV_FILE="${ENV_FILE:-$DEFAULT_ROOT/.env}"
if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

# ======================== 配置 ========================

HTTP_PROXY_URL="${HTTP_PROXY_URL:-${HTTPS_PROXY:-${https_proxy:-${HTTP_PROXY:-${http_proxy:-}}}}}"

PROJECT_BASE="${PROJECT_BASE:-/mnt/shared-storage-user/colab-share/liujiaheng/workspace/xieqianqian/webcoding_data}"
DATASET_DIR="${DATASET_DIR:-$PROJECT_BASE/datasets}"
PIPELINE_A_ROOT="${PIPELINE_A_ROOT:-$DATASET_DIR/pipeline_a}"
PIPELINE_A_INPUT="${PIPELINE_A_INPUT:-$PIPELINE_A_ROOT/useful}"

CONDA_ENV="${CONDA_ENV:-lora}"

ROOT="${ROOT:-$DEFAULT_ROOT}"
BROWSER_PROXY="${BROWSER_PROXY:-$HTTP_PROXY_URL}"
REQUESTS_PROXY="${REQUESTS_PROXY:-$HTTP_PROXY_URL}"
CONCURRENCY_A="${CONCURRENCY_A:-20}"
SITE_TIMEOUT="${SITE_TIMEOUT:-120}"

RUN_NAME="${RUN_NAME:-run_a_clean_only_test}"
PIPELINE_A_RUN_DIR="${PIPELINE_A_RUN_DIR:-$PIPELINE_A_ROOT/runs/$RUN_NAME}"
PIPELINE_A_OUTPUT="${PIPELINE_A_OUTPUT:-$PIPELINE_A_RUN_DIR/output}"
PIPELINE_A_LOG_DIR="${PIPELINE_A_LOG_DIR:-$PIPELINE_A_RUN_DIR/logs}"

mkdir -p "$PIPELINE_A_OUTPUT" "$PIPELINE_A_LOG_DIR"

# 激活 conda
set +u
if command -v conda &>/dev/null; then
    source "$(conda info --base)/etc/profile.d/conda.sh" 2>/dev/null || true
    conda activate "$CONDA_ENV" 2>/dev/null || true
fi
set -u

cd "$ROOT"
PYTHON="${PYTHON:-python3}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$PIPELINE_A_LOG_DIR/run.log"
}

log "=========================================="
log "Pipeline A CLEAN ONLY TEST — 50 cases"
log "=========================================="
log "input=$PIPELINE_A_INPUT"
log "output=$PIPELINE_A_OUTPUT"
log "limit=50"
log "concurrency=$CONCURRENCY_A"
log "proxy=$BROWSER_PROXY"
log "=========================================="

if [ ! -d "$PIPELINE_A_INPUT" ]; then
    log "错误: 输入目录不存在: $PIPELINE_A_INPUT"
    exit 1
fi

$PYTHON preprocess/pipeline_a_sample_level.py \
    --input-dir "$PIPELINE_A_INPUT" \
    --output-dir "$PIPELINE_A_OUTPUT" \
    --concurrency "$CONCURRENCY_A" \
    --site-timeout "$SITE_TIMEOUT" \
    --max-pages 7 \
    --wait 3000 \
    --limit 50 \
    --browser-proxy "$BROWSER_PROXY" \
    --requests-proxy "$REQUESTS_PROXY" \
    --no-expand \
    --no-js \
    2>&1 | tee "$PIPELINE_A_LOG_DIR/pipeline_a.log"

PIPELINE_EXIT=${PIPESTATUS[0]}

log ""
log "=========================================="
log "TEST 运行完成"
log "=========================================="

MANIFEST="$PIPELINE_A_OUTPUT/sample_pipeline_results.jsonl"
if [ -f "$MANIFEST" ]; then
    $PYTHON -c "
import json, collections
lines = open('$MANIFEST').readlines()
results = [json.loads(l) for l in lines if l.strip()]
total = len(results)
samples = sum(len(r.get('outputs',[])) for r in results)
failed = sum(1 for r in results if not r.get('outputs'))
statuses = dict(collections.Counter(r.get('status','?') for r in results))
print(f'项目={total}, 可用样本={samples}, 失败={failed}')
print(f'状态: {statuses}')
print(f'成功率: {samples/(samples+failed)*100:.1f}%' if (samples+failed) else '成功率: N/A')
" 2>/dev/null | while read -r line; do log "$line"; done
else
    log "警告: 未找到 manifest: $MANIFEST"
fi

log "输出目录: $PIPELINE_A_OUTPUT"
exit $PIPELINE_EXIT
