#!/usr/bin/env bash
# =============================================================================
# WebCoding Data Pipeline — 服务器运行脚本
#
# 并行执行 Pipeline A 和 Pipeline B。
# 默认小批量试跑（A=1000, B=2000），全量跑时调大 PIPELINE_A_LIMIT / PIPELINE_B_URL_LIMIT。
#
# 用法:
#   # 已有 preflight 通过的 URL（默认）
#   export HTTP_PROXY_URL=http://your-proxy:port
#   export OPENAI_API_KEY=... OPENAI_BASE_URL=... OPENAI_MODEL=...
#   bash preprocess/run_server.sh
#
#   # 从原始 URL 开始（需要跑 filter + preflight）
#   RUN_PREFLIGHT=1 bash preprocess/run_server.sh
#
#   # 只跑其中一个
#   SKIP_PIPELINE_B=1 bash preprocess/run_server.sh
#   SKIP_PIPELINE_A=1 bash preprocess/run_server.sh
# =============================================================================
set -euo pipefail

# ======================== ↓↓↓ 请在这里填写 ↓↓↓ ========================

# --- 代理（必填）---
HTTP_PROXY_URL="${HTTP_PROXY_URL:-}"          # 例: http://192.168.1.1:7890

# --- LLM API（Pipeline A 的 add_js 需要，必填）---
export OPENAI_API_KEY="${OPENAI_API_KEY:-}"    # API 密钥
export OPENAI_BASE_URL="${OPENAI_BASE_URL:-}"  # 例: https://dashscope.aliyuncs.com/compatible-mode/v1
export OPENAI_MODEL="${OPENAI_MODEL:-}"        # 例: qwen-plus

# --- 数据路径（按服务器实际路径修改）---
DATASET_DIR="${DATASET_DIR:-/path/to/datasets}"
PIPELINE_A_INPUT="${PIPELINE_A_INPUT:-$DATASET_DIR/webrenderbench_projects}"
PIPELINE_B_URL_FILE="${PIPELINE_B_URL_FILE:-$DATASET_DIR/webcode2m_preflight_passed_urls.txt}"

# --- conda 环境名 ---
CONDA_ENV="${CONDA_ENV:-lora}"

# ======================== ↑↑↑ 填写结束 ↑↑↑ ========================

# 项目路径
ROOT="${ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
BROWSER_PROXY="${BROWSER_PROXY:-$HTTP_PROXY_URL}"
REQUESTS_PROXY="${REQUESTS_PROXY:-$HTTP_PROXY_URL}"

# 并发数（A 调 LLM 限流，B 纯爬取可以开大）
CONCURRENCY_A="${CONCURRENCY_A:-50}"
CONCURRENCY_B="${CONCURRENCY_B:-100}"

# 超时（秒）
SITE_TIMEOUT="${SITE_TIMEOUT:-900}"

# Pipeline A 输出 & 限量
PIPELINE_A_OUTPUT="${PIPELINE_A_OUTPUT:-$DATASET_DIR/pipeline_a_output}"
PIPELINE_A_LIMIT="${PIPELINE_A_LIMIT:-12000}"

# Pipeline B 输出 & 限量
PIPELINE_B_OUTPUT="${PIPELINE_B_OUTPUT:-$DATASET_DIR/pipeline_b_output}"
PIPELINE_B_URL_LIMIT="${PIPELINE_B_URL_LIMIT:-28000}"

# 可选: 从原始 URL 开始跑 filter + preflight（默认跳过）
RUN_PREFLIGHT="${RUN_PREFLIGHT:-}"
PIPELINE_B_ALL_URLS="${PIPELINE_B_ALL_URLS:-$DATASET_DIR/webcode2m_all_urls.txt}"
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

RUN_NAME="run_$(date +%Y%m%d_%H%M%S)"
LOG_DIR="$DATASET_DIR/logs/$RUN_NAME"
mkdir -p "$LOG_DIR"

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
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_DIR/run.log"
}

# ======================== 打印配置 ========================

log "=========================================="
log "WebCoding Data Pipeline Server Run"
log "=========================================="
log "run_name=$RUN_NAME"
log "root=$ROOT"
log "dataset_dir=$DATASET_DIR"
log "concurrency: A=$CONCURRENCY_A, B=$CONCURRENCY_B (总计=$((CONCURRENCY_A + CONCURRENCY_B)))"
log "site_timeout=${SITE_TIMEOUT}s"
log "browser_proxy=$BROWSER_PROXY"
log "requests_proxy=$REQUESTS_PROXY"
log "python=$($PYTHON --version 2>&1)"
log "skip_pipeline_a=${SKIP_PIPELINE_A:-no}"
log "skip_pipeline_b=${SKIP_PIPELINE_B:-no}"
log "run_preflight=${RUN_PREFLIGHT:-no}"
log "no_js=${NO_JS:-no}"
log "log_dir=$LOG_DIR"
log "=========================================="

# ======================== Pipeline B 前置（可选）========================

if [ -z "$SKIP_PIPELINE_B" ] && [ -n "$RUN_PREFLIGHT" ]; then
    log ""
    log "========== Pipeline B: 前置过滤 =========="

    mkdir -p "$PIPELINE_B_OUTPUT"
    FILTERED_URLS="$PIPELINE_B_OUTPUT/filtered_urls.txt"
    PREFLIGHT_PASSED="$PIPELINE_B_OUTPUT/preflight_passed.txt"

    # Step 1: filter
    if [ -f "$FILTERED_URLS" ] && [ -s "$FILTERED_URLS" ]; then
        log "[B-filter] 已有过滤结果，跳过"
    else
        log "[B-filter] 过滤 URL..."
        $PYTHON preprocess/filter_webcode2m_urls.py \
            --input "$PIPELINE_B_ALL_URLS" \
            --output "$FILTERED_URLS" \
            --rejected-output "$PIPELINE_B_OUTPUT/filter_rejected.tsv" \
            2>&1 | tee "$LOG_DIR/pipeline_b_filter.log"
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
            --rejected-output "$PIPELINE_B_OUTPUT/preflight_rejected.jsonl" \
            --report "$PIPELINE_B_OUTPUT/preflight_report.json" \
            --proxy "$REQUESTS_PROXY" \
            --concurrency "$PIPELINE_B_PREFLIGHT_CONCURRENCY" \
            --limit "$PIPELINE_B_PREFLIGHT_LIMIT" \
            2>&1 | tee "$LOG_DIR/pipeline_b_preflight.log"
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
            $JS_ARGS \
            2>&1 | tee "$LOG_DIR/pipeline_a.log"
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
            2>&1 | tee "$LOG_DIR/pipeline_b.log"
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
outputs = sum(len(r.get('outputs',[])) for r in results)
statuses = dict(collections.Counter(r.get('status','?') for r in results))
print(f'项目={len(results)}, 可用变体={outputs}, 状态分布={statuses}')
" 2>/dev/null || echo "统计失败")
    log "Pipeline A: $A_STATS"
fi

if [ -z "$SKIP_PIPELINE_B" ] && [ -f "$PIPELINE_B_OUTPUT/pipeline_b_results.jsonl" ]; then
    B_STATS=$($PYTHON -c "
import json, collections
lines = open('$PIPELINE_B_OUTPUT/pipeline_b_results.jsonl').readlines()
results = [json.loads(l) for l in lines]
ok = sum(1 for r in results if r.get('status') in ('ok','partial'))
statuses = dict(collections.Counter(r.get('status','?') for r in results))
print(f'总URL={len(results)}, 可用={ok}, 状态分布={statuses}')
" 2>/dev/null || echo "统计失败")
    log "Pipeline B: $B_STATS"
fi

log "日志目录: $LOG_DIR"
log "完成时间: $(date '+%Y-%m-%d %H:%M:%S')"

if [ "$FAIL" -ne 0 ]; then
    log "警告: 有 Pipeline 退出码非零，请检查日志"
    exit 1
fi
