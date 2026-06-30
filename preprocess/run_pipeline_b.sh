#!/usr/bin/env bash
# =============================================================================
# Pipeline B — WebCode2M 预处理（crawl → postprocess）
#
# 默认运行规模 15000 URL，可通过 PIPELINE_B_URL_LIMIT 调整。
# 默认 RUN_NAME 固定，重复运行同一脚本会续跑同一批输出；需要新批次时显式设置 RUN_NAME。
#
# 用法:
#   # 已有 preflight 通过的 URL（默认）
#   export HTTP_PROXY_URL=http://your-proxy:port
#   bash preprocess/run_pipeline_b.sh
#
#   # 后台运行
#   bash preprocess/run_pipeline_b.sh --background
#
#   # 从原始 URL 开始（需要跑 filter + preflight）
#   RUN_PREFLIGHT=1 bash preprocess/run_pipeline_b.sh
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
    echo "Usage: bash preprocess/run_pipeline_b.sh [--background]" >&2
    exit 2
fi

# ======================== ↓↓↓ 请在这里填写 ↓↓↓ ========================

# --- 代理（必填）---
HTTP_PROXY_URL="${HTTP_PROXY_URL:-${HTTPS_PROXY:-${https_proxy:-${HTTP_PROXY:-${http_proxy:-}}}}}"

# --- 数据路径 ---
PROJECT_BASE="${PROJECT_BASE:-/mnt/shared-storage-user/colab-share/liujiaheng/workspace/xieqianqian/webcoding_data}"
DATASET_DIR="${DATASET_DIR:-$PROJECT_BASE/datasets}"
PIPELINE_B_ROOT="${PIPELINE_B_ROOT:-$DATASET_DIR/pipeline_b}"
PIPELINE_B_INPUT_DIR="${PIPELINE_B_INPUT_DIR:-$PIPELINE_B_ROOT/inputs}"
PIPELINE_B_URL_FILE="${PIPELINE_B_URL_FILE:-$PIPELINE_B_INPUT_DIR/webcode2m_preflight_passed_urls.txt}"

# --- conda 环境名 ---
CONDA_ENV="${CONDA_ENV:-lora}"

# ======================== ↑↑↑ 填写结束 ↑↑↑ ========================

# 项目路径
ROOT="${ROOT:-$DEFAULT_ROOT}"
BROWSER_PROXY="${BROWSER_PROXY:-$HTTP_PROXY_URL}"
REQUESTS_PROXY="${REQUESTS_PROXY:-$HTTP_PROXY_URL}"

# 并发数
CONCURRENCY_B="${CONCURRENCY_B:-100}"

# 超时（秒）
SITE_TIMEOUT="${SITE_TIMEOUT:-120}"
CODE_RESOURCES_ONLY="${CODE_RESOURCES_ONLY:-}"

# 运行名
RUN_NAME="${RUN_NAME:-run_b15000}"
RUN_BATCH_DIR="${RUN_BATCH_DIR:-$DATASET_DIR/runs/$RUN_NAME}"
FIRST_RUN_DATE_FILE="${FIRST_RUN_DATE_FILE:-$RUN_BATCH_DIR/first_run_date.txt}"
mkdir -p "$RUN_BATCH_DIR"
if [ ! -s "$FIRST_RUN_DATE_FILE" ]; then
    date +%Y%m%d > "$FIRST_RUN_DATE_FILE"
fi
FIRST_RUN_DATE="$(tr -d '[:space:]' < "$FIRST_RUN_DATE_FILE")"
RUN_BATCH_ID="${RUN_BATCH_ID:-${RUN_NAME}_${FIRST_RUN_DATE}}"

# Pipeline B 输出 & 限量
PIPELINE_B_RUN_DIR="${PIPELINE_B_RUN_DIR:-$PIPELINE_B_ROOT/runs/$RUN_NAME}"
PIPELINE_B_OUTPUT="${PIPELINE_B_OUTPUT:-$PIPELINE_B_RUN_DIR/output}"
PIPELINE_B_LOG_DIR="${PIPELINE_B_LOG_DIR:-$PIPELINE_B_RUN_DIR/logs}"
PIPELINE_B_URL_LIMIT="${PIPELINE_B_URL_LIMIT:-15000}"

# 可选: 从原始 URL 开始跑 filter + preflight（默认跳过）
RUN_PREFLIGHT="${RUN_PREFLIGHT:-}"
PIPELINE_B_PREFLIGHT_DIR="${PIPELINE_B_PREFLIGHT_DIR:-$PIPELINE_B_ROOT/preflight/$RUN_NAME}"
PIPELINE_B_ALL_URLS="${PIPELINE_B_ALL_URLS:-$PIPELINE_B_INPUT_DIR/webcode2m_all_urls.txt}"
PIPELINE_B_PREFLIGHT_LIMIT="${PIPELINE_B_PREFLIGHT_LIMIT:-30000}"
PIPELINE_B_PREFLIGHT_CONCURRENCY="${PIPELINE_B_PREFLIGHT_CONCURRENCY:-200}"

# ======================== 初始化 ========================

RUN_LOG_DIR="${RUN_LOG_DIR:-$RUN_BATCH_DIR/logs}"
mkdir -p "$RUN_LOG_DIR" "$PIPELINE_B_LOG_DIR"

if [ "$BACKGROUND" = "1" ] && [ "${WEBCODING_BACKGROUND_CHILD:-}" != "1" ]; then
    BACKGROUND_LOG="$RUN_LOG_DIR/background.log"
    PID_FILE="$RUN_BATCH_DIR/run_pipeline_b.pid"
    nohup env WEBCODING_BACKGROUND_CHILD=1 bash "$SCRIPT_PATH" > "$BACKGROUND_LOG" 2>&1 &
    CHILD_PID=$!
    echo "$CHILD_PID" > "$PID_FILE"
    echo "Started Pipeline B in background."
    echo "PID: $CHILD_PID"
    echo "PID file: $PID_FILE"
    echo "Launcher log: $BACKGROUND_LOG"
    echo "Run log: $RUN_LOG_DIR/run.log"
    echo "Pipeline B log: $PIPELINE_B_LOG_DIR/pipeline_b.log"
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

# ======================== 日志函数 ========================

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$RUN_LOG_DIR/run.log"
}

# ======================== 打印配置 ========================

log "=========================================="
log "Pipeline B — WebCode2M 预处理"
log "=========================================="
log "run_name=$RUN_NAME"
log "run_batch_id=$RUN_BATCH_ID"
log "first_run_date=$FIRST_RUN_DATE"
log "run_batch_dir=$RUN_BATCH_DIR"
log "project_base=$PROJECT_BASE"
log "root=$ROOT"
log "dataset_dir=$DATASET_DIR"
log "pipeline_b_root=$PIPELINE_B_ROOT"
log "pipeline_b_url_file=$PIPELINE_B_URL_FILE"
log "pipeline_b_output=$PIPELINE_B_OUTPUT"
log "pipeline_b_log_dir=$PIPELINE_B_LOG_DIR"
log "concurrency=$CONCURRENCY_B"
log "site_timeout=${SITE_TIMEOUT}s"
log "code_resources_only=${CODE_RESOURCES_ONLY:-no}"
log "browser_proxy=$BROWSER_PROXY"
log "requests_proxy=$REQUESTS_PROXY"
log "python=$($PYTHON --version 2>&1)"
log "run_preflight=${RUN_PREFLIGHT:-no}"
log "run_log_dir=$RUN_LOG_DIR"
log "=========================================="

# ======================== Pipeline B 前置（可选）========================

if [ -n "$RUN_PREFLIGHT" ]; then
    log ""
    log "========== Pipeline B: 前置过滤 =========="

    mkdir -p "$PIPELINE_B_PREFLIGHT_DIR"
    FILTERED_URLS="$PIPELINE_B_PREFLIGHT_DIR/filtered_urls.txt"
    PREFLIGHT_PASSED="$PIPELINE_B_PREFLIGHT_DIR/preflight_passed.txt"

    # Step 1: filter
    if [ -f "$FILTERED_URLS" ] && [ -s "$FILTERED_URLS" ]; then
        log "[B-filter] 已有过滤结果，跳过"
    else
        log "[B-filter] 过滤 URL..."
        $PYTHON preprocess/filter_webcode2m_urls.py \
            --input "$PIPELINE_B_ALL_URLS" \
            --output "$FILTERED_URLS" \
            --rejected-output "$PIPELINE_B_PREFLIGHT_DIR/filter_rejected.tsv" \
            2>&1 | tee "$PIPELINE_B_LOG_DIR/filter.log"
        log "[B-filter] 完成: $(wc -l < "$FILTERED_URLS") URLs"
    fi

    # Step 2: preflight
    if [ -f "$PREFLIGHT_PASSED" ] && [ -s "$PREFLIGHT_PASSED" ]; then
        log "[B-preflight] 已有 preflight 结果，跳过"
    else
        log "[B-preflight] HTTP 可达性检查 (limit=$PIPELINE_B_PREFLIGHT_LIMIT)..."
        $PYTHON preprocess/preflight_webcode2m_urls.py \
            --input "$FILTERED_URLS" \
            --accepted-output "$PREFLIGHT_PASSED" \
            --rejected-output "$PIPELINE_B_PREFLIGHT_DIR/preflight_rejected.jsonl" \
            --report "$PIPELINE_B_PREFLIGHT_DIR/preflight_report.json" \
            --proxy "$REQUESTS_PROXY" \
            --concurrency "$PIPELINE_B_PREFLIGHT_CONCURRENCY" \
            --limit "$PIPELINE_B_PREFLIGHT_LIMIT" \
            2>&1 | tee "$PIPELINE_B_LOG_DIR/preflight.log"
        log "[B-preflight] 完成: $(wc -l < "$PREFLIGHT_PASSED") URLs"
    fi

    # 使用 preflight 输出作为后续输入
    PIPELINE_B_URL_FILE="$PREFLIGHT_PASSED"
fi

# ======================== 检查输入 ========================

if [ ! -f "$PIPELINE_B_URL_FILE" ]; then
    log "[B] 错误: URL 文件不存在: $PIPELINE_B_URL_FILE"
    log "[B] 提示: 设置 PIPELINE_B_URL_FILE 指向 preflight 通过的 URL 文件"
    log "[B]       或设置 RUN_PREFLIGHT=1 从原始 URL 开始"
    exit 1
fi

URL_COUNT=$(wc -l < "$PIPELINE_B_URL_FILE")
log "[B] URL 文件行数: $URL_COUNT"

# ======================== 运行 Pipeline B ========================

log ""
log "========== 启动 Pipeline B (并发=$CONCURRENCY_B, limit=$PIPELINE_B_URL_LIMIT) =========="

CODE_RESOURCE_ARGS=()
if [ -n "$CODE_RESOURCES_ONLY" ]; then
    CODE_RESOURCE_ARGS+=(--code-resources-only)
fi

$PYTHON preprocess/pipeline_b_sample_level.py \
    --url-file "$PIPELINE_B_URL_FILE" \
    --output-dir "$PIPELINE_B_OUTPUT" \
    --concurrency "$CONCURRENCY_B" \
    --site-timeout "$SITE_TIMEOUT" \
    --max-pages 7 \
    --wait 3000 \
    --limit "$PIPELINE_B_URL_LIMIT" \
    --browser-proxy "$BROWSER_PROXY" \
    --requests-proxy "$REQUESTS_PROXY" \
    "${CODE_RESOURCE_ARGS[@]}" \
    2>&1 | tee "$PIPELINE_B_LOG_DIR/pipeline_b.log"

PIPELINE_EXIT=$?

# ======================== 汇总 ========================

log ""
log "=========================================="
log "Pipeline B 运行完成"
log "=========================================="

if [ -f "$PIPELINE_B_OUTPUT/pipeline_b_results.jsonl" ]; then
    B_STATS=$($PYTHON -c "
import json, collections
lines = open('$PIPELINE_B_OUTPUT/pipeline_b_results.jsonl').readlines()
results = [json.loads(l) for l in lines]
total_samples = sum(len(r.get('outputs',[])) for r in results)
single_count = sum(1 for r in results for o in r.get('outputs',[]) if o.get('variant')=='single')
multi_count = sum(1 for r in results for o in r.get('outputs',[]) if o.get('variant')=='multi')
ok = sum(1 for r in results if r.get('status') in ('ok','partial'))
statuses = dict(collections.Counter(r.get('status','?') for r in results))
print(f'URL={len(results)}, 总样本={total_samples} (单页={single_count}, 多页={multi_count}), 可用={ok}, 状态分布={statuses}')
" 2>/dev/null || echo "统计失败")
    log "Pipeline B: $B_STATS"
else
    log "[B] 警告: 未找到输出 manifest"
fi

log "运行日志目录: $RUN_LOG_DIR"
log "Pipeline B 输出目录: $PIPELINE_B_OUTPUT"
log "Pipeline B 日志目录: $PIPELINE_B_LOG_DIR"
log "完成时间: $(date '+%Y-%m-%d %H:%M:%S')"

if [ "$PIPELINE_EXIT" -ne 0 ]; then
    log "警告: Pipeline B 退出码非零 ($PIPELINE_EXIT)，请检查日志"
    exit 1
fi
