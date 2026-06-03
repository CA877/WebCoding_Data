#!/usr/bin/env bash
# =============================================================================
# Pipeline A CLEAN ONLY — 只跑 clean，跳过 expand 和 add_js
#
# 最快模式：不调 LLM，纯本地处理（下载远程图片 + 清理 HTML）
# 31765 个输入，预计 2-4 小时完成
#
# 用法:
#   bash preprocess/run_pipeline_a_clean_only.sh
#   bash preprocess/run_pipeline_a_clean_only.sh --background
#
#   # 自定义参数
#   CONCURRENCY_A=120 PIPELINE_A_LIMIT=31765 bash preprocess/run_pipeline_a_clean_only.sh
# =============================================================================

# 不用 set -e，防止 tee 管道导致脚本提前退出
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="$SCRIPT_DIR/$(basename "${BASH_SOURCE[0]}")"
DEFAULT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# 加载 .env
ENV_FILE="${ENV_FILE:-$DEFAULT_ROOT/.env}"
if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

# 后台运行支持
BACKGROUND=0
if [ "${1:-}" = "--background" ]; then
    BACKGROUND=1
    shift
fi

# ======================== 配置 ========================

# --- 代理 ---
HTTP_PROXY_URL="${HTTP_PROXY_URL:-${HTTPS_PROXY:-${https_proxy:-${HTTP_PROXY:-${http_proxy:-}}}}}"

# --- 数据路径（H 集群默认值）---
PROJECT_BASE="${PROJECT_BASE:-/mnt/shared-storage-user/colab-share/liujiaheng/workspace/xieqianqian/webcoding_data}"
DATASET_DIR="${DATASET_DIR:-$PROJECT_BASE/datasets}"
PIPELINE_A_ROOT="${PIPELINE_A_ROOT:-$DATASET_DIR/pipeline_a}"
PIPELINE_A_INPUT="${PIPELINE_A_INPUT:-$PIPELINE_A_ROOT/useful}"

# --- conda ---
CONDA_ENV="${CONDA_ENV:-lora}"

# --- 运行参数 ---
ROOT="${ROOT:-$DEFAULT_ROOT}"
BROWSER_PROXY="${BROWSER_PROXY:-$HTTP_PROXY_URL}"
REQUESTS_PROXY="${REQUESTS_PROXY:-$HTTP_PROXY_URL}"
CONCURRENCY_A="${CONCURRENCY_A:-120}"
SITE_TIMEOUT="${SITE_TIMEOUT:-120}"
PIPELINE_A_LIMIT="${PIPELINE_A_LIMIT:-31765}"

# --- 输出路径 ---
RUN_NAME="${RUN_NAME:-run_a_clean_only}"
PIPELINE_A_RUN_DIR="${PIPELINE_A_RUN_DIR:-$PIPELINE_A_ROOT/runs/$RUN_NAME}"
PIPELINE_A_OUTPUT="${PIPELINE_A_OUTPUT:-$PIPELINE_A_RUN_DIR/output}"
PIPELINE_A_LOG_DIR="${PIPELINE_A_LOG_DIR:-$PIPELINE_A_RUN_DIR/logs}"

# ======================== 初始化 ========================

mkdir -p "$PIPELINE_A_OUTPUT" "$PIPELINE_A_LOG_DIR"

# 后台模式
if [ "$BACKGROUND" = "1" ] && [ "${WEBCODING_BACKGROUND_CHILD:-}" != "1" ]; then
    BG_LOG="$PIPELINE_A_LOG_DIR/background.log"
    PID_FILE="$PIPELINE_A_RUN_DIR/pipeline_a_clean_only.pid"
    nohup env WEBCODING_BACKGROUND_CHILD=1 bash "$SCRIPT_PATH" > "$BG_LOG" 2>&1 &
    CHILD_PID=$!
    echo "$CHILD_PID" > "$PID_FILE"
    echo "Pipeline A (clean only) 已在后台启动"
    echo "  PID: $CHILD_PID"
    echo "  PID 文件: $PID_FILE"
    echo "  日志: $BG_LOG"
    echo "  Pipeline 日志: $PIPELINE_A_LOG_DIR/pipeline_a.log"
    echo ""
    echo "查看进度: tail -f $PIPELINE_A_LOG_DIR/pipeline_a.log"
    echo "停止: kill \$(cat $PID_FILE)"
    exit 0
fi

# 激活 conda
set +u
if command -v conda &>/dev/null; then
    source "$(conda info --base)/etc/profile.d/conda.sh" 2>/dev/null || true
    conda activate "$CONDA_ENV" 2>/dev/null || true
fi
set -u

cd "$ROOT"
PYTHON="${PYTHON:-python3}"

# ======================== 日志 ========================

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$PIPELINE_A_LOG_DIR/run.log"
}

# ======================== 前置检查 ========================

log "=========================================="
log "Pipeline A CLEAN ONLY — no expand, no JS"
log "=========================================="
log "input=$PIPELINE_A_INPUT"
log "output=$PIPELINE_A_OUTPUT"
log "limit=$PIPELINE_A_LIMIT"
log "concurrency=$CONCURRENCY_A"
log "site_timeout=${SITE_TIMEOUT}s"
log "proxy=$BROWSER_PROXY"
log "python=$($PYTHON --version 2>&1)"
log "=========================================="

if [ ! -d "$PIPELINE_A_INPUT" ]; then
    log "错误: 输入目录不存在: $PIPELINE_A_INPUT"
    exit 1
fi

# 统计输入
INPUT_COUNT=$($PYTHON -c "
from pathlib import Path
p = Path('$PIPELINE_A_INPUT')
count = sum(1 for d in p.iterdir() if d.is_dir() and (d/'index.html').exists())
print(count)
" 2>/dev/null || echo "?")
log "输入项目数: $INPUT_COUNT"

# ======================== 运行 ========================

log ""
log "========== 开始运行 (clean only, 并发=$CONCURRENCY_A) =========="
log ""

$PYTHON preprocess/pipeline_a_sample_level.py \
    --input-dir "$PIPELINE_A_INPUT" \
    --output-dir "$PIPELINE_A_OUTPUT" \
    --concurrency "$CONCURRENCY_A" \
    --site-timeout "$SITE_TIMEOUT" \
    --max-pages 7 \
    --wait 3000 \
    --limit "$PIPELINE_A_LIMIT" \
    --browser-proxy "$BROWSER_PROXY" \
    --requests-proxy "$REQUESTS_PROXY" \
    --no-expand \
    --no-js \
    2>&1 | tee "$PIPELINE_A_LOG_DIR/pipeline_a.log"

PIPELINE_EXIT=${PIPESTATUS[0]}

# ======================== 汇总 ========================

log ""
log "=========================================="
log "Pipeline A CLEAN ONLY 运行完成"
log "=========================================="

MANIFEST="$PIPELINE_A_OUTPUT/sample_pipeline_results.jsonl"
if [ -f "$MANIFEST" ]; then
    $PYTHON -c "
import json, collections, sys
lines = open('$MANIFEST').readlines()
results = [json.loads(l) for l in lines if l.strip()]
total = len(results)
samples = sum(len(r.get('outputs',[])) for r in results)
statuses = dict(collections.Counter(r.get('status','?') for r in results))
failed = sum(1 for r in results if not r.get('outputs'))
print(f'项目={total}, 可用样本={samples}, 失败={failed}')
print(f'状态: {statuses}')
print(f'成功率: {samples/(samples+failed)*100:.1f}%' if (samples+failed) else '成功率: N/A')
" 2>/dev/null | while read -r line; do log "$line"; done
else
    log "警告: 未找到 manifest: $MANIFEST"
fi

log ""
log "输出目录: $PIPELINE_A_OUTPUT"
log "日志目录: $PIPELINE_A_LOG_DIR"
log "完成时间: $(date '+%Y-%m-%d %H:%M:%S')"

if [ "$PIPELINE_EXIT" -ne 0 ]; then
    log "警告: Pipeline A 退出码=$PIPELINE_EXIT"
fi

log ""
log "下游使用: construct 脚本的 --input-dir 指向 $PIPELINE_A_OUTPUT/single_page"

exit $PIPELINE_EXIT
