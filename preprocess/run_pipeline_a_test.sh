#!/usr/bin/env bash
# =============================================================================
# Pipeline A 测试脚本 — 只跑 50 个项目，用于验证流程是否正确
#
# 用法:
#   export HTTP_PROXY_URL=http://your-proxy:port
#   export OPENAI_API_KEY=... OPENAI_BASE_URL=... OPENAI_MODEL=...
#   bash preprocess/run_pipeline_a_test.sh
# =============================================================================
# 不用 set -e，防止 tee 管道导致脚本提前退出
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${ENV_FILE:-$DEFAULT_ROOT/.env}"
if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

# ======================== ↓↓↓ 测试配置 ↓↓↓ ========================

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

# ======================== ↑↑↑ 配置结束 ========================

# 项目路径
ROOT="${ROOT:-$DEFAULT_ROOT}"
BROWSER_PROXY="${BROWSER_PROXY:-$HTTP_PROXY_URL}"
REQUESTS_PROXY="${REQUESTS_PROXY:-$HTTP_PROXY_URL}"

# ★ 测试专用: 只跑 50 个，低并发，短超时
TEST_LIMIT=50
TEST_CONCURRENCY=5
TEST_SITE_TIMEOUT=180
TEST_RUN_NAME="test_a50"

# 运行名
RUN_NAME="${RUN_NAME:-$TEST_RUN_NAME}"
RUN_BATCH_DIR="${RUN_BATCH_DIR:-$DATASET_DIR/runs/$RUN_NAME}"
PIPELINE_A_RUN_DIR="${PIPELINE_A_RUN_DIR:-$PIPELINE_A_ROOT/runs/$RUN_NAME}"
PIPELINE_A_OUTPUT="${PIPELINE_A_OUTPUT:-$PIPELINE_A_RUN_DIR/output}"
PIPELINE_A_LOG_DIR="${PIPELINE_A_LOG_DIR:-$PIPELINE_A_RUN_DIR/logs}"

# JS 配置
NO_JS="${NO_JS:-}"
JS_MODEL="${JS_MODEL:-}"
JS_RATIO="${JS_RATIO:-0.5}"

# ======================== 初始化 ========================

RUN_LOG_DIR="${RUN_LOG_DIR:-$RUN_BATCH_DIR/logs}"
mkdir -p "$RUN_LOG_DIR" "$PIPELINE_A_LOG_DIR"

# 激活 conda 环境
set +u
if command -v conda &>/dev/null; then
    source "$(conda info --base)/etc/profile.d/conda.sh" 2>/dev/null || true
    conda activate "$CONDA_ENV" 2>/dev/null || true
fi
set -u

cd "$ROOT"
PYTHON="${PYTHON:-python3}"

JS_ARGS="--js-ratio $JS_RATIO"
if [ -n "$NO_JS" ]; then
    JS_ARGS="--no-js"
fi
if [ -n "$JS_MODEL" ]; then
    JS_ARGS="$JS_ARGS --js-model $JS_MODEL"
fi

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$RUN_LOG_DIR/run.log"
}

# ======================== 打印配置 ========================

log "=========================================="
log "Pipeline A 🧪 测试模式 (limit=$TEST_LIMIT)"
log "=========================================="
log "run_name=$RUN_NAME"
log "pipeline_a_input=$PIPELINE_A_INPUT"
log "pipeline_a_output=$PIPELINE_A_OUTPUT"
log "pipeline_a_log_dir=$PIPELINE_A_LOG_DIR"
log "concurrency=$TEST_CONCURRENCY"
log "site_timeout=${TEST_SITE_TIMEOUT}s"
log "js_ratio=$JS_RATIO"
log "browser_proxy=$BROWSER_PROXY"
log "requests_proxy=$REQUESTS_PROXY"
log "python=$($PYTHON --version 2>&1)"
log "=========================================="

# 检查 API 配置
MISSING_API=()
[ -n "$OPENAI_API_KEY" ] || MISSING_API+=("OPENAI_API_KEY")
[ -n "$OPENAI_BASE_URL" ] || MISSING_API+=("OPENAI_BASE_URL")
[ -n "$OPENAI_MODEL" ] || MISSING_API+=("OPENAI_MODEL")
if [ "${#MISSING_API[@]}" -gt 0 ]; then
    log "[A] 错误: 缺少: ${MISSING_API[*]}"
    exit 1
fi

if [ ! -d "$PIPELINE_A_INPUT" ]; then
    log "[A] 错误: 输入目录不存在: $PIPELINE_A_INPUT"
    exit 1
fi

# ======================== 运行 ========================

log ""
log "========== 启动 Pipeline A 测试 (并发=$TEST_CONCURRENCY, limit=$TEST_LIMIT) =========="

$PYTHON preprocess/pipeline_a_sample_level.py \
    --input-dir "$PIPELINE_A_INPUT" \
    --output-dir "$PIPELINE_A_OUTPUT" \
    --concurrency "$TEST_CONCURRENCY" \
    --site-timeout "$TEST_SITE_TIMEOUT" \
    --max-pages 7 \
    --wait 3000 \
    --limit "$TEST_LIMIT" \
    --browser-proxy "$BROWSER_PROXY" \
    --requests-proxy "$REQUESTS_PROXY" \
    --fast-clean \
    $JS_ARGS \
    2>&1 | tee "$PIPELINE_A_LOG_DIR/pipeline_a.log"

PIPELINE_EXIT=${PIPESTATUS[0]}

# ======================== 汇总 ========================

log ""
log "=========================================="
log "Pipeline A 测试完成"
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
    log "Pipeline A 测试结果: $A_STATS"
fi

log "输出目录: $PIPELINE_A_OUTPUT"
log "日志目录: $PIPELINE_A_LOG_DIR"
log "完成时间: $(date '+%Y-%m-%d %H:%M:%S')"

exit $PIPELINE_EXIT
