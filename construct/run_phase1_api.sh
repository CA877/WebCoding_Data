#!/usr/bin/env bash
# Phase 1: repair + generate 并行跑（edit 暂不跑）
set -uo pipefail

# ============ 必须配置 ============
INPUT_DIR="${INPUT_DIR:-./single_page}"
# 服务器端存数据的根路径
DATA_ROOT="${DATA_ROOT:-/mnt/shared-storage-user/colab-share/liujiaheng/workspace/xieqianqian/webcoding_data}"

# API 配置
export OPENAI_API_KEY="${OPENAI_API_KEY:?请设置 OPENAI_API_KEY}"
export OPENAI_BASE_URL="${OPENAI_BASE_URL:?请设置 OPENAI_BASE_URL}"
export OPENAI_MODEL="${OPENAI_MODEL:-kimi-k2.6}"

# ============ 可选配置 ============
SEED="${SEED:-0}"
WORKERS="${WORKERS:-1}"               # 并发线程数
REPAIR_MIN_TASKS="${REPAIR_MIN_TASKS:-4}"
REPAIR_MAX_TASKS="${REPAIR_MAX_TASKS:-12}"
MAX_RETRIES="${MAX_RETRIES:-3}"
OVERWRITE="${OVERWRITE:-}"            # 设置为 1 则覆盖已有

# 代理（按需设置）
if [ -n "${ALL_PROXY:-}" ]; then
    export ALL_PROXY HTTPS_PROXY HTTP_PROXY
    export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1}"
fi

# ============ 初始化 ============
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

OVERWRITE_FLAG=""
[ -n "$OVERWRITE" ] && OVERWRITE_FLAG="--overwrite"

# 输出路径
REPAIR_OUTPUT="$DATA_ROOT/repair"
GEN_OUTPUT="$DATA_ROOT/generate"

# ============ 分区：前 5K repair，后 5K generate ============
REPAIR_LIMIT="${REPAIR_LIMIT:-5000}"
REPAIR_OFFSET="${REPAIR_OFFSET:-0}"
GEN_LIMIT="${GEN_LIMIT:-5000}"
GEN_OFFSET="${GEN_OFFSET:-5000}"

echo "=== 项目分区（offset=$REPAIR_OFFSET limit=$REPAIR_LIMIT repair + offset=$GEN_OFFSET limit=$GEN_LIMIT generate）==="

LOG_DIR="$DATA_ROOT/_logs"
mkdir -p "$LOG_DIR"

# ============ repair + generate 并行 ============
echo ""
echo "=== text-repair + text-generation 并行启动 (workers=$WORKERS) ==="

python3 WebCoding_Data/construct/construct_text_repair.py \
    --input-dir "$INPUT_DIR" \
    --output-dir "$REPAIR_OUTPUT" \
    --offset "$REPAIR_OFFSET" \
    --limit "$REPAIR_LIMIT" \
    --min-tasks "$REPAIR_MIN_TASKS" \
    --max-tasks "$REPAIR_MAX_TASKS" \
    --seed "$SEED" \
    --max-retries "$MAX_RETRIES" \
    --workers "$WORKERS" \
    $OVERWRITE_FLAG \
    >"$LOG_DIR/repair.log" 2>&1 &
PID_REPAIR=$!

python3 WebCoding_Data/construct/construct_text_generation.py \
    --input-dir "$INPUT_DIR" \
    --output-dir "$GEN_OUTPUT" \
    --offset "$GEN_OFFSET" \
    --limit "$GEN_LIMIT" \
    --workers "$WORKERS" \
    $OVERWRITE_FLAG \
    >"$LOG_DIR/generate.log" 2>&1 &
PID_GEN=$!

echo "  repair   PID=$PID_REPAIR → $REPAIR_OUTPUT (offset=$REPAIR_OFFSET, limit=$REPAIR_LIMIT)"
echo "  generate PID=$PID_GEN → $GEN_OUTPUT (offset=$GEN_OFFSET, limit=$GEN_LIMIT)"
echo "  日志: $LOG_DIR/repair.log"
echo "        $LOG_DIR/generate.log"
echo ""
echo "等待两个任务完成…（可用 tail -f $LOG_DIR/*.log 查看进度）"

# 等待两个任务完成
wait $PID_REPAIR
RC_REPAIR=$?
wait $PID_GEN
RC_GEN=$?

echo ""
echo "=== Phase 1 完成 ==="
echo "text-repair:     $REPAIR_OUTPUT (exit=$RC_REPAIR)"
echo "text-generation: $GEN_OUTPUT (exit=$RC_GEN)"
echo "完整日志: $LOG_DIR/{repair,generate}.log"
