#!/usr/bin/env bash
# =============================================================================
# Pipeline B 测试脚本 — 只跑 50 个 URL，用于验证流程是否正确
#
# 用法:
#   export HTTP_PROXY_URL=http://your-proxy:port
#   bash preprocess/run_pipeline_b_test.sh
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

# --- 数据路径 ---
PROJECT_BASE="${PROJECT_BASE:-/mnt/shared-storage-user/colab-share/liujiaheng/workspace/xieqianqian/webcoding_data}"
DATASET_DIR="${DATASET_DIR:-$PROJECT_BASE/datasets}"
PIPELINE_B_ROOT="${PIPELINE_B_ROOT:-$DATASET_DIR/pipeline_b}"
PIPELINE_B_INPUT_DIR="${PIPELINE_B_INPUT_DIR:-$PIPELINE_B_ROOT/inputs}"
PIPELINE_B_URL_FILE="${PIPELINE_B_URL_FILE:-$PIPELINE_B_INPUT_DIR/webcode2m_preflight_passed_urls.txt}"

# --- conda 环境名 ---
CONDA_ENV="${CONDA_ENV:-lora}"

# ======================== ↑↑↑ 配置结束 ========================

# 项目路径
ROOT="${ROOT:-$DEFAULT_ROOT}"
BROWSER_PROXY="${BROWSER_PROXY:-$HTTP_PROXY_URL}"
REQUESTS_PROXY="${REQUESTS_PROXY:-$HTTP_PROXY_URL}"

# ★ 测试专用: 只跑 50 个，低并发，短超时
TEST_LIMIT=50
TEST_CONCURRENCY=10
TEST_SITE_TIMEOUT=120
TEST_RUN_NAME="test_b50"

# 运行名
RUN_NAME="${RUN_NAME:-$TEST_RUN_NAME}"
RUN_BATCH_DIR="${RUN_BATCH_DIR:-$DATASET_DIR/runs/$RUN_NAME}"
PIPELINE_B_RUN_DIR="${PIPELINE_B_RUN_DIR:-$PIPELINE_B_ROOT/runs/$RUN_NAME}"
PIPELINE_B_OUTPUT="${PIPELINE_B_OUTPUT:-$PIPELINE_B_RUN_DIR/output}"
PIPELINE_B_LOG_DIR="${PIPELINE_B_LOG_DIR:-$PIPELINE_B_RUN_DIR/logs}"

# ======================== 初始化 ========================

RUN_LOG_DIR="${RUN_LOG_DIR:-$RUN_BATCH_DIR/logs}"
mkdir -p "$RUN_LOG_DIR" "$PIPELINE_B_LOG_DIR"

# 激活 conda 环境
set +u
if command -v conda &>/dev/null; then
    source "$(conda info --base)/etc/profile.d/conda.sh" 2>/dev/null || true
    conda activate "$CONDA_ENV" 2>/dev/null || true
fi
set -u

cd "$ROOT"
PYTHON="${PYTHON:-python3}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$RUN_LOG_DIR/run.log"
}

# ======================== 打印配置 ========================

log "=========================================="
log "Pipeline B 🧪 测试模式 (limit=$TEST_LIMIT)"
log "=========================================="
log "run_name=$RUN_NAME"
log "pipeline_b_url_file=$PIPELINE_B_URL_FILE"
log "pipeline_b_output=$PIPELINE_B_OUTPUT"
log "pipeline_b_log_dir=$PIPELINE_B_LOG_DIR"
log "concurrency=$TEST_CONCURRENCY"
log "site_timeout=${TEST_SITE_TIMEOUT}s"
log "browser_proxy=$BROWSER_PROXY"
log "requests_proxy=$REQUESTS_PROXY"
log "python=$($PYTHON --version 2>&1)"
log "=========================================="

# ======================== 检查输入 ========================

if [ ! -f "$PIPELINE_B_URL_FILE" ]; then
    log "[B] 错误: URL 文件不存在: $PIPELINE_B_URL_FILE"
    log "[B] 提示: 请先确保 preflight 已跑过，或设置 PIPELINE_B_URL_FILE 指向正确的 URL 文件"
    exit 1
fi

URL_COUNT=$(wc -l < "$PIPELINE_B_URL_FILE")
log "[B] URL 文件行数: $URL_COUNT (将只处理前 $TEST_LIMIT 条)"

# ======================== 运行 ========================

log ""
log "========== 启动 Pipeline B 测试 (并发=$TEST_CONCURRENCY, limit=$TEST_LIMIT) =========="

$PYTHON preprocess/pipeline_b_sample_level.py \
    --url-file "$PIPELINE_B_URL_FILE" \
    --output-dir "$PIPELINE_B_OUTPUT" \
    --concurrency "$TEST_CONCURRENCY" \
    --site-timeout "$TEST_SITE_TIMEOUT" \
    --max-pages 7 \
    --wait 3000 \
    --limit "$TEST_LIMIT" \
    --browser-proxy "$BROWSER_PROXY" \
    --requests-proxy "$REQUESTS_PROXY" \
    2>&1 | tee "$PIPELINE_B_LOG_DIR/pipeline_b.log"

PIPELINE_EXIT=${PIPESTATUS[0]}

# ======================== 汇总 ========================

log ""
log "=========================================="
log "Pipeline B 测试完成"
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
    log "Pipeline B 测试结果: $B_STATS"
fi

log "输出目录: $PIPELINE_B_OUTPUT"
log "日志目录: $PIPELINE_B_LOG_DIR"
log "完成时间: $(date '+%Y-%m-%d %H:%M:%S')"

exit $PIPELINE_EXIT
