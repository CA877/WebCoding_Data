#!/usr/bin/env bash
# Phase 1: 串行跑 text-generation → text-editing → text-repair，各 5K
# 用法：
#   1. 把 text-generate.tar.gz edit.tar.gz repair.tar.gz 解压到 REPO_ROOT（本脚本 ../.. ）
#   2. 设置 API 环境变量
#   3. bash WebCoding_Data/construct/run_phase1_5k.sh
set -euo pipefail

# ============ API 配置（必须） ============
export OPENAI_API_KEY="${OPENAI_API_KEY:?请设置 OPENAI_API_KEY}"
export OPENAI_BASE_URL="${OPENAI_BASE_URL:?请设置 OPENAI_BASE_URL}"
export OPENAI_MODEL="${OPENAI_MODEL:-kimi-k2.6}"

# ============ 可选配置 ============
WORKERS="${WORKERS:-1}"               # 并发线程数
OVERWRITE="${OVERWRITE:-}"            # 设置为 1 则覆盖已有输出
MAX_RETRIES="${MAX_RETRIES:-3}"

# text-generation 参数
GEN_WORKERS="${GEN_WORKERS:-$WORKERS}"

# text-editing 参数
EDIT_MIN_TASKS="${EDIT_MIN_TASKS:-4}"
EDIT_MAX_TASKS="${EDIT_MAX_TASKS:-12}"
EDIT_SEED="${EDIT_SEED:-0}"
EDIT_WORKERS="${EDIT_WORKERS:-$WORKERS}"

# text-repair 参数
REPAIR_MIN_TASKS="${REPAIR_MIN_TASKS:-4}"
REPAIR_MAX_TASKS="${REPAIR_MAX_TASKS:-12}"
REPAIR_SEED="${REPAIR_SEED:-0}"
REPAIR_WORKERS="${REPAIR_WORKERS:-$WORKERS}"

# ============ 路径 ============
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/output}"

OVERWRITE_FLAG=""
[ "${OVERWRITE}" = "1" ] && OVERWRITE_FLAG="--overwrite"

echo "============================================"
echo "Phase 1: 5K × 3 tasks (串行)"
echo "REPO_ROOT:  $REPO_ROOT"
echo "OUTPUT_DIR: $OUTPUT_DIR"
echo "MODEL:      $OPENAI_MODEL"
echo "============================================"

# ============ 1. text-generation (5K) ============
echo ""
echo "=== [1/3] text-generation (limit=5000, workers=$GEN_WORKERS) ==="
python3 WebCoding_Data/construct/construct_text_generation.py \
    --input-dir "$REPO_ROOT/text-generate" \
    --output-dir "$OUTPUT_DIR/text-generation" \
    --limit 5000 \
    --workers "$GEN_WORKERS" \
    $OVERWRITE_FLAG

# ============ 2. text-editing (5K) ============
echo ""
echo "=== [2/3] text-editing (limit=5000, workers=$EDIT_WORKERS) ==="
python3 WebCoding_Data/construct/construct_text_editing.py \
    --input-dir "$REPO_ROOT/edit" \
    --output-dir "$OUTPUT_DIR/text-editing" \
    --limit 5000 \
    --min-tasks "$EDIT_MIN_TASKS" \
    --max-tasks "$EDIT_MAX_TASKS" \
    --seed "$EDIT_SEED" \
    --max-retries "$MAX_RETRIES" \
    --workers "$EDIT_WORKERS" \
    $OVERWRITE_FLAG

# ============ 3. text-repair (5K) ============
echo ""
echo "=== [3/3] text-repair (limit=5000, workers=$REPAIR_WORKERS) ==="
python3 WebCoding_Data/construct/construct_text_repair.py \
    --input-dir "$REPO_ROOT/repair" \
    --output-dir "$OUTPUT_DIR/text-repair" \
    --limit 5000 \
    --min-tasks "$REPAIR_MIN_TASKS" \
    --max-tasks "$REPAIR_MAX_TASKS" \
    --seed "$REPAIR_SEED" \
    --max-retries "$MAX_RETRIES" \
    --workers "$REPAIR_WORKERS" \
    $OVERWRITE_FLAG

echo ""
echo "============================================"
echo "Phase 1 完成！输出："
echo "  text-generation: $OUTPUT_DIR/text-generation/"
echo "  text-editing:    $OUTPUT_DIR/text-editing/"
echo "  text-repair:     $OUTPUT_DIR/text-repair/"
echo "============================================"
