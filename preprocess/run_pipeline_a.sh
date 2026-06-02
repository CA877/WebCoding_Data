#!/usr/bin/env bash
# =============================================================================
# Pipeline A — WebRenderBench 预处理（expand → clean → add_js）
#
# 默认运行规模 15000 项目，可通过 PIPELINE_A_LIMIT 调整。
# 默认 RUN_NAME 固定，重复运行同一脚本会续跑同一批输出；需要新批次时显式设置 RUN_NAME。
#
# 用法:
#   export HTTP_PROXY_URL=http://your-proxy:port
#   export OPENAI_API_KEY=... OPENAI_BASE_URL=... OPENAI_MODEL=...
#   bash preprocess/run_pipeline_a.sh
#
#   # 后台运行
#   bash preprocess/run_pipeline_a.sh --background
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="$SCRIPT_DIR/$(basename "${BASH_SOURCE[0]}")"
DEFAULT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${ENV_FILE:-$DEFAULT_ROOT/.env}"
if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

BACKGROUND=0
if [ "${1:-}" = "--background" ]; then
    BACKGROUND=1
    shift
fi
if [ "$#" -gt 0 ]; then
    echo "Unknown arguments: $*" >&2
    echo "Usage: bash preprocess/run_pipeline_a.sh [--background]" >&2
    exit 2
fi

# ======================== ↓↓↓ 请在这里填写 ↓↓↓ ========================

# --- 代理（必填）---
HTTP_PROXY_URL="${HTTP_PROXY_URL:-${HTTPS_PROXY:-${https_proxy:-${HTTP_PROXY:-${http_proxy:-}}}}}"

# --- LLM API（add_js 需要，必填）---
export OPENAI_API_KEY="${OPENAI_API_KEY:-}"
export OPENAI_BASE_URL="${OPENAI_BASE_URL:-}"
export OPENAI_MODEL="${OPENAI_MODEL:-}"

# --- 数据路径 ---
PROJECT_BASE="${PROJECT_BASE:-/mnt/shared-storage-user/colab-share/liujiaheng/workspace/xieqianqian/webcoding_data}"
DATASET_DIR="${DATASET_DIR:-$PROJECT_BASE/datasets}"
PIPELINE_A_ROOT="${PIPELINE_A_ROOT:-$DATASET_DIR/pipeline_a}"
PIPELINE_A_INPUT="${PIPELINE_A_INPUT:-$PIPELINE_A_ROOT/useful}"

# --- conda 环境名 ---
CONDA_ENV="${CONDA_ENV:-lora}"

# ======================== ↑↑↑ 填写结束 ↑↑↑ ========================

# 项目路径
ROOT="${ROOT:-$DEFAULT_ROOT}"
BROWSER_PROXY="${BROWSER_PROXY:-$HTTP_PROXY_URL}"
REQUESTS_PROXY="${REQUESTS_PROXY:-$HTTP_PROXY_URL}"

# 并发数
CONCURRENCY_A="${CONCURRENCY_A:-50}"

# 超时（秒）
SITE_TIMEOUT="${SITE_TIMEOUT:-180}"

# 运行名
RUN_NAME="${RUN_NAME:-run_a15000}"
RUN_BATCH_DIR="${RUN_BATCH_DIR:-$DATASET_DIR/runs/$RUN_NAME}"
FIRST_RUN_DATE_FILE="${FIRST_RUN_DATE_FILE:-$RUN_BATCH_DIR/first_run_date.txt}"
mkdir -p "$RUN_BATCH_DIR"
if [ ! -s "$FIRST_RUN_DATE_FILE" ]; then
    date +%Y%m%d > "$FIRST_RUN_DATE_FILE"
fi
FIRST_RUN_DATE="$(tr -d '[:space:]' < "$FIRST_RUN_DATE_FILE")"
RUN_BATCH_ID="${RUN_BATCH_ID:-${RUN_NAME}_${FIRST_RUN_DATE}}"

# Pipeline A 输出 & 限量
PIPELINE_A_RUN_DIR="${PIPELINE_A_RUN_DIR:-$PIPELINE_A_ROOT/runs/$RUN_NAME}"
PIPELINE_A_OUTPUT="${PIPELINE_A_OUTPUT:-$PIPELINE_A_RUN_DIR/output}"
PIPELINE_A_LOG_DIR="${PIPELINE_A_LOG_DIR:-$PIPELINE_A_RUN_DIR/logs}"
PIPELINE_A_LIMIT="${PIPELINE_A_LIMIT:-15000}"

# JS 生成配置（默认启用，ratio=0.5）
NO_JS="${NO_JS:-}"
JS_MODEL="${JS_MODEL:-}"
JS_RATIO="${JS_RATIO:-0.5}"

# ======================== 初始化 ========================

RUN_LOG_DIR="${RUN_LOG_DIR:-$RUN_BATCH_DIR/logs}"
mkdir -p "$RUN_LOG_DIR" "$PIPELINE_A_LOG_DIR"

if [ "$BACKGROUND" = "1" ] && [ "${WEBCODING_BACKGROUND_CHILD:-}" != "1" ]; then
    BACKGROUND_LOG="$RUN_LOG_DIR/background.log"
    PID_FILE="$RUN_BATCH_DIR/run_pipeline_a.pid"
    nohup env WEBCODING_BACKGROUND_CHILD=1 bash "$SCRIPT_PATH" > "$BACKGROUND_LOG" 2>&1 &
    CHILD_PID=$!
    echo "$CHILD_PID" > "$PID_FILE"
    echo "Started Pipeline A in background."
    echo "PID: $CHILD_PID"
    echo "PID file: $PID_FILE"
    echo "Launcher log: $BACKGROUND_LOG"
    echo "Run log: $RUN_LOG_DIR/run.log"
    echo "Pipeline A log: $PIPELINE_A_LOG_DIR/pipeline_a.log"
    exit 0
fi

# 激活 conda 环境
set +u
if command -v conda &>/dev/null; then
    source "$(conda info --base)/etc/profile.d/conda.sh" 2>/dev/null || true
    conda activate "$CONDA_ENV" 2>/dev/null || true
fi
set -u

cd "$ROOT"
PYTHON="${PYTHON:-python3}"

# 构建 JS 参数
JS_ARGS="--js-ratio $JS_RATIO"
if [ -n "$NO_JS" ]; then
    JS_ARGS="--no-js"
fi
if [ -n "$JS_MODEL" ]; then
    JS_ARGS="$JS_ARGS --js-model $JS_MODEL"
fi

# ======================== 日志函数 ========================

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$RUN_LOG_DIR/run.log"
}

# ======================== 打印配置 ========================

log "=========================================="
log "Pipeline A — WebRenderBench 预处理"
log "=========================================="
log "run_name=$RUN_NAME"
log "run_batch_id=$RUN_BATCH_ID"
log "first_run_date=$FIRST_RUN_DATE"
log "run_batch_dir=$RUN_BATCH_DIR"
log "project_base=$PROJECT_BASE"
log "root=$ROOT"
log "dataset_dir=$DATASET_DIR"
log "pipeline_a_root=$PIPELINE_A_ROOT"
log "pipeline_a_input=$PIPELINE_A_INPUT"
log "pipeline_a_output=$PIPELINE_A_OUTPUT"
log "pipeline_a_log_dir=$PIPELINE_A_LOG_DIR"
log "concurrency=$CONCURRENCY_A"
log "site_timeout=${SITE_TIMEOUT}s"
log "browser_proxy=$BROWSER_PROXY"
log "requests_proxy=$REQUESTS_PROXY"
log "python=$($PYTHON --version 2>&1)"
log "no_js=${NO_JS:-no}"
log "js_ratio=$JS_RATIO"
log "run_log_dir=$RUN_LOG_DIR"
log "=========================================="

# 检查 API 配置
MISSING_API=()
[ -n "$OPENAI_API_KEY" ] || MISSING_API+=("OPENAI_API_KEY")
[ -n "$OPENAI_BASE_URL" ] || MISSING_API+=("OPENAI_BASE_URL")
[ -n "$OPENAI_MODEL" ] || MISSING_API+=("OPENAI_MODEL")
if [ "${#MISSING_API[@]}" -gt 0 ]; then
    log "[A] 错误: Pipeline A 需要 API 配置，缺少: ${MISSING_API[*]}"
    log "[A] 请在 $ENV_FILE 中配置，或运行脚本前 export 对应环境变量。"
    exit 1
fi

# ======================== 检查输入 ========================

if [ ! -d "$PIPELINE_A_INPUT" ]; then
    log "[A] 错误: 输入目录不存在: $PIPELINE_A_INPUT"
    exit 1
fi

INPUT_COUNT=$(find "$PIPELINE_A_INPUT" -maxdepth 1 -name "index.html" -exec dirname {} \; | wc -l || echo 0)
log "[A] 输入目录项目数: $INPUT_COUNT"

# ======================== 运行 Pipeline A ========================

log ""
log "========== 启动 Pipeline A (并发=$CONCURRENCY_A, limit=$PIPELINE_A_LIMIT) =========="

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
    $JS_ARGS \
    2>&1 | tee "$PIPELINE_A_LOG_DIR/pipeline_a.log"

PIPELINE_EXIT=$?

# ======================== 汇总 ========================

log ""
log "=========================================="
log "Pipeline A 运行完成"
log "=========================================="

if [ -f "$PIPELINE_A_OUTPUT/sample_pipeline_results.jsonl" ]; then
    A_TOTAL=$(wc -l < "$PIPELINE_A_OUTPUT/sample_pipeline_results.jsonl")
    A_STATS=$($PYTHON -c "
import json, collections
lines = open('$PIPELINE_A_OUTPUT/sample_pipeline_results.jsonl').readlines()
results = [json.loads(l) for l in lines]
total_samples = sum(len(r.get('outputs',[])) for r in results)
single_count = sum(1 for r in results for o in r.get('outputs',[]) if o.get('variant')=='single')
multi_count = sum(1 for r in results for o in r.get('outputs',[]) if o.get('variant')=='multi')
statuses = dict(collections.Counter(r.get('status','?') for r in results))
print(f'项目={len(results)}, 总样本={total_samples} (单页={single_count}, 多页={multi_count}), 状态分布={statuses}')
" 2>/dev/null || echo "统计失败")
    log "Pipeline A: $A_STATS"
else
    log "[A] 警告: 未找到输出 manifest"
fi

log "运行日志目录: $RUN_LOG_DIR"
log "Pipeline A 输出目录: $PIPELINE_A_OUTPUT"
log "Pipeline A 日志目录: $PIPELINE_A_LOG_DIR"
log "完成时间: $(date '+%Y-%m-%d %H:%M:%S')"

if [ "$PIPELINE_EXIT" -ne 0 ]; then
    log "警告: Pipeline A 退出码非零 ($PIPELINE_EXIT)，请检查日志"
    exit 1
fi
