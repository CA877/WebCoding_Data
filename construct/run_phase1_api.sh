#!/usr/bin/env bash
# Phase 1: 需要 API 的任务（text-editing, text-repair, text-generation）
# 给有 API 的人跑，跑完把 OUTPUT_DIR 传回来
set -euo pipefail

# ============ 必须配置 ============
INPUT_DIR="${INPUT_DIR:-./single_page}"
OUTPUT_DIR="${OUTPUT_DIR:-./output}"

# API 配置
export OPENAI_API_KEY="${OPENAI_API_KEY:?请设置 OPENAI_API_KEY}"
export OPENAI_BASE_URL="${OPENAI_BASE_URL:?请设置 OPENAI_BASE_URL}"
export OPENAI_MODEL="${OPENAI_MODEL:-kimi-k2.6}"

# 视觉模型（text-generation 的 PRD 需要）
export VISION_OPENAI_API_KEY="${VISION_OPENAI_API_KEY:-$OPENAI_API_KEY}"
export VISION_OPENAI_BASE_URL="${VISION_OPENAI_BASE_URL:-$OPENAI_BASE_URL}"
export VISION_MODEL="${VISION_MODEL:-$OPENAI_MODEL}"

# ============ 可选配置 ============
LIMIT="${LIMIT:-0}"                    # 0=不限制
SEED="${SEED:-0}"
WORKERS="${WORKERS:-1}"               # 并发线程数
EDIT_MIN_TASKS="${EDIT_MIN_TASKS:-4}"
EDIT_MAX_TASKS="${EDIT_MAX_TASKS:-12}"
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
LIMIT_FLAG=""
[ "$LIMIT" -gt 0 ] 2>/dev/null && LIMIT_FLAG="--limit $LIMIT"

# ============ 分区：edit 10K / repair 10K / generation 10K ============
EDIT_LIMIT="${EDIT_LIMIT:-10000}"
REPAIR_LIMIT="${REPAIR_LIMIT:-10000}"
GEN_LIMIT="${GEN_LIMIT:-10000}"

echo "=== 项目分区（edit ${EDIT_LIMIT} + repair ${REPAIR_LIMIT} + generation ${GEN_LIMIT}）==="
python3 -c "
from pathlib import Path
import os

input_dir = Path('$INPUT_DIR')
output_dir = Path('$OUTPUT_DIR')
src_dir = output_dir / '_src'

edit_src = src_dir / 'text-editing'
repair_src = src_dir / 'text-repair'
gen_src = src_dir / 'text-generation'
for d in (edit_src, repair_src, gen_src):
    d.mkdir(parents=True, exist_ok=True)

projects = sorted(d for d in input_dir.iterdir() if d.is_dir() and (d/'index.html').exists())

edit_projs = projects[:$EDIT_LIMIT]
repair_projs = projects[$EDIT_LIMIT:$EDIT_LIMIT+$REPAIR_LIMIT]
gen_projs = projects[$EDIT_LIMIT+$REPAIR_LIMIT:$EDIT_LIMIT+$REPAIR_LIMIT+$GEN_LIMIT]

for proj in edit_projs:
    dst = edit_src / proj.name
    if not dst.exists():
        os.symlink(proj.resolve(), str(dst), target_is_directory=True)

for proj in repair_projs:
    dst = repair_src / proj.name
    if not dst.exists():
        os.symlink(proj.resolve(), str(dst), target_is_directory=True)

for proj in gen_projs:
    dst = gen_src / proj.name
    if not dst.exists():
        os.symlink(proj.resolve(), str(dst), target_is_directory=True)

print(f'  text-editing:    {len(edit_projs)} projects')
print(f'  text-repair:     {len(repair_projs)} projects')
print(f'  text-generation: {len(gen_projs)} projects')
"

# ============ text-editing（需要 LLM API）============
echo ""
echo "=== text-editing (workers=$WORKERS) ==="
python3 WebCoding_Data/construct/construct_text_editing.py \
    --input-dir "$OUTPUT_DIR/_src/text-editing" \
    --output-dir "$OUTPUT_DIR/text-editing" \
    --min-tasks "$EDIT_MIN_TASKS" \
    --max-tasks "$EDIT_MAX_TASKS" \
    --seed "$SEED" \
    --max-retries "$MAX_RETRIES" \
    --workers "$WORKERS" \
    $LIMIT_FLAG $OVERWRITE_FLAG

# ============ text-repair（需要 LLM API）============
echo ""
echo "=== text-repair (workers=$WORKERS) ==="
python3 WebCoding_Data/construct/construct_text_repair.py \
    --input-dir "$OUTPUT_DIR/_src/text-repair" \
    --output-dir "$OUTPUT_DIR/text-repair" \
    --min-tasks "$REPAIR_MIN_TASKS" \
    --max-tasks "$REPAIR_MAX_TASKS" \
    --seed "$SEED" \
    --max-retries "$MAX_RETRIES" \
    --workers "$WORKERS" \
    $LIMIT_FLAG $OVERWRITE_FLAG

# ============ text-generation（需要 VLM API + playwright）============
echo ""
echo "=== text-generation (workers=$WORKERS) ==="
python3 WebCoding_Data/construct/construct_text_generation.py \
    --input-dir "$OUTPUT_DIR/_src/text-generation" \
    --output-dir "$OUTPUT_DIR/text-generation" \
    --workers "$WORKERS" \
    $LIMIT_FLAG $OVERWRITE_FLAG

echo ""
echo "=== Phase 1 完成 ==="
echo "text-editing:    $OUTPUT_DIR/text-editing/"
echo "text-repair:     $OUTPUT_DIR/text-repair/"
echo "text-generation: $OUTPUT_DIR/text-generation/"
