#!/usr/bin/env bash
# =============================================================================
# WebCoding Data Pipeline — 服务器运行脚本
#
# 并行执行 Pipeline A 和 Pipeline B。
# 默认运行规模为 A=15000、B=15000，可通过 PIPELINE_A_LIMIT / PIPELINE_B_URL_LIMIT 调整。
# 默认 RUN_NAME 固定，重复运行同一脚本会续跑同一批输出；需要新批次时显式设置 RUN_NAME。
#
# 用法:
#   # 已有 preflight 通过的 URL（默认）
#   export HTTP_PROXY_URL=http://your-proxy:port
#   export OPENAI_API_KEY=... OPENAI_BASE_URL=... OPENAI_MODEL=...
#   bash preprocess/run_server.sh
#
#   # 后台运行，SSH 断开后继续执行
#   bash preprocess/run_server.sh --background
#
#   # 从原始 URL 开始（需要跑 filter + preflight）
#   RUN_PREFLIGHT=1 bash preprocess/run_server.sh
#
#   # 只跑其中一个
#   SKIP_PIPELINE_B=1 bash preprocess/run_server.sh
#   SKIP_PIPELINE_A=1 bash preprocess/run_server.sh
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
    echo "Usage: bash preprocess/run_server.sh [--background]" >&2
    exit 2
fi

# ======================== ↓↓↓ 请在这里填写 ↓↓↓ ========================

# --- 代理（必填）---
HTTP_PROXY_URL="${HTTP_PROXY_URL:-${HTTPS_PROXY:-${https_proxy:-${HTTP_PROXY:-${http_proxy:-}}}}}"  # 例: http://192.168.1.1:7890

# --- LLM API（Pipeline A 的 add_js 需要，必填）---
export OPENAI_API_KEY="${OPENAI_API_KEY:-}"    # API 密钥
export OPENAI_BASE_URL="${OPENAI_BASE_URL:-}"  # 例: https://dashscope.aliyuncs.com/compatible-mode/v1
export OPENAI_MODEL="${OPENAI_MODEL:-}"        # 例: qwen-plus

# --- 数据路径 ---
PROJECT_BASE="${PROJECT_BASE:-/mnt/shared-storage-user/colab-share/liujiaheng/workspace/xieqianqian/webcoding_data}"
DATASET_DIR="${DATASET_DIR:-$PROJECT_BASE/datasets}"
PIPELINE_A_ROOT="${PIPELINE_A_ROOT:-$DATASET_DIR/pipeline_a}"
PIPELINE_B_ROOT="${PIPELINE_B_ROOT:-$DATASET_DIR/pipeline_b}"
PIPELINE_A_INPUT="${PIPELINE_A_INPUT:-$PIPELINE_A_ROOT/useful}"
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
CONCURRENCY_A="${CONCURRENCY_A:-50}"
CONCURRENCY_B="${CONCURRENCY_B:-100}"

# 超时（秒）
SITE_TIMEOUT="${SITE_TIMEOUT:-180}"

# 运行名
RUN_NAME="${RUN_NAME:-run_a15000_b15000}"
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

# JS 生成配置（Pipeline A 默认启用）
NO_JS="${NO_JS:-}"
JS_MODEL="${JS_MODEL:-}"
JS_RATIO="${JS_RATIO:-0.5}"  # add_js 比例（0.5 = 一半项目加 JS）

# 跳过控制
SKIP_PIPELINE_A="${SKIP_PIPELINE_A:-}"
SKIP_PIPELINE_B="${SKIP_PIPELINE_B:-}"

# ======================== 初始化 ========================

RUN_LOG_DIR="${RUN_LOG_DIR:-$RUN_BATCH_DIR/logs}"
mkdir -p "$RUN_LOG_DIR" "$PIPELINE_A_LOG_DIR" "$PIPELINE_B_LOG_DIR"

if [ "$BACKGROUND" = "1" ] && [ "${WEBCODING_BACKGROUND_CHILD:-}" != "1" ]; then
    BACKGROUND_LOG="$RUN_LOG_DIR/background.log"
    PID_FILE="$RUN_BATCH_DIR/run_server.pid"
    nohup env WEBCODING_BACKGROUND_CHILD=1 bash "$SCRIPT_PATH" > "$BACKGROUND_LOG" 2>&1 &
    CHILD_PID=$!
    echo "$CHILD_PID" > "$PID_FILE"
    echo "Started WebCoding pipeline in background."
    echo "PID: $CHILD_PID"
    echo "PID file: $PID_FILE"
    echo "Launcher log: $BACKGROUND_LOG"
    echo "Run log: $RUN_LOG_DIR/run.log"
    echo "Pipeline A log: $PIPELINE_A_LOG_DIR/pipeline_a.log"
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

# 构建通用参数
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
log "WebCoding Data Pipeline Server Run"
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
log "pipeline_b_root=$PIPELINE_B_ROOT"
log "pipeline_b_url_file=$PIPELINE_B_URL_FILE"
log "pipeline_b_output=$PIPELINE_B_OUTPUT"
log "pipeline_b_log_dir=$PIPELINE_B_LOG_DIR"
log "concurrency: A=$CONCURRENCY_A, B=$CONCURRENCY_B (总计=$((CONCURRENCY_A + CONCURRENCY_B)))"
log "site_timeout=${SITE_TIMEOUT}s"
log "browser_proxy=$BROWSER_PROXY"
log "requests_proxy=$REQUESTS_PROXY"
log "python=$($PYTHON --version 2>&1)"
log "skip_pipeline_a=${SKIP_PIPELINE_A:-no}"
log "skip_pipeline_b=${SKIP_PIPELINE_B:-no}"
log "run_preflight=${RUN_PREFLIGHT:-no}"
log "no_js=${NO_JS:-no}"
log "run_log_dir=$RUN_LOG_DIR"
log "=========================================="

if [ -z "$SKIP_PIPELINE_A" ]; then
    MISSING_API=()
    [ -n "$OPENAI_API_KEY" ] || MISSING_API+=("OPENAI_API_KEY")
    [ -n "$OPENAI_BASE_URL" ] || MISSING_API+=("OPENAI_BASE_URL")
    [ -n "$OPENAI_MODEL" ] || MISSING_API+=("OPENAI_MODEL")
    if [ "${#MISSING_API[@]}" -gt 0 ]; then
        log "[A] 错误: Pipeline A 需要 API 配置，缺少: ${MISSING_API[*]}"
        log "[A] 请在 $ENV_FILE 中配置，或运行脚本前 export 对应环境变量。"
        exit 1
    fi
fi

# ======================== Pipeline B 前置（可选）========================

if [ -z "$SKIP_PIPELINE_B" ] && [ -n "$RUN_PREFLIGHT" ]; then
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

# ======================== 并行运行两个 Pipeline ========================

PIDS=()

# --- 启动 Pipeline A ---
if [ -z "$SKIP_PIPELINE_A" ]; then
    if [ ! -d "$PIPELINE_A_INPUT" ]; then
        log "[A] 错误: 输入目录不存在: $PIPELINE_A_INPUT"
        exit 1
    fi

    log ""
    log "========== 启动 Pipeline A (并发=$CONCURRENCY_A, limit=$PIPELINE_A_LIMIT) =========="
    (
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
            --fast-clean \
            $JS_ARGS \
            2>&1 | tee "$PIPELINE_A_LOG_DIR/pipeline_a.log"
    ) &
    PID_A=$!
    PIDS+=($PID_A)
    log "[A] 已启动 PID=$PID_A"
fi

# --- 启动 Pipeline B ---
if [ -z "$SKIP_PIPELINE_B" ]; then
    if [ ! -f "$PIPELINE_B_URL_FILE" ]; then
        log "[B] 错误: URL 文件不存在: $PIPELINE_B_URL_FILE"
        log "[B] 提示: 设置 PIPELINE_B_URL_FILE 指向 preflight 通过的 URL 文件"
        log "[B]       或设置 RUN_PREFLIGHT=1 从原始 URL 开始"
        exit 1
    fi

    log ""
    log "========== 启动 Pipeline B (并发=$CONCURRENCY_B, limit=$PIPELINE_B_URL_LIMIT) =========="
    (
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
            2>&1 | tee "$PIPELINE_B_LOG_DIR/pipeline_b.log"
    ) &
    PID_B=$!
    PIDS+=($PID_B)
    log "[B] 已启动 PID=$PID_B"
fi

# --- 等待所有 Pipeline 完成 ---
log ""
log "等待所有 Pipeline 完成 (PIDs: ${PIDS[*]})..."
FAIL=0
for pid in "${PIDS[@]}"; do
    if ! wait "$pid"; then
        log "警告: PID=$pid 退出码非零"
        FAIL=1
    fi
done

# ======================== 汇总 ========================

log ""
log "=========================================="
log "运行完成"
log "=========================================="

if [ -z "$SKIP_PIPELINE_A" ] && [ -f "$PIPELINE_A_OUTPUT/sample_pipeline_results.jsonl" ]; then
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
fi

if [ -z "$SKIP_PIPELINE_B" ] && [ -f "$PIPELINE_B_OUTPUT/pipeline_b_results.jsonl" ]; then
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
fi

log "运行日志目录: $RUN_LOG_DIR"
log "Pipeline A 输出目录: $PIPELINE_A_OUTPUT"
log "Pipeline A 日志目录: $PIPELINE_A_LOG_DIR"
log "Pipeline B 输出目录: $PIPELINE_B_OUTPUT"
log "Pipeline B 日志目录: $PIPELINE_B_LOG_DIR"
log "完成时间: $(date '+%Y-%m-%d %H:%M:%S')"

if [ "$FAIL" -ne 0 ]; then
    log "警告: 有 Pipeline 退出码非零，请检查日志"
    exit 1
fi
