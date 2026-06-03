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

# 视觉模型（text-generation 的 PRD 需要，同一套 API）
export VISION_OPENAI_API_KEY="$OPENAI_API_KEY"
export VISION_OPENAI_BASE_URL="$OPENAI_BASE_URL"
export VISION_MODEL="Qwen3-235B-A22B"

# ============ 可选配置 ============
LIMIT="${LIMIT:-0}"                    # 0=不限制
SEED="${SEED:-0}"
EDIT_LIMIT="${EDIT_LIMIT:-10000}"
REPAIR_LIMIT="${REPAIR_LIMIT:-10000}"
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

# ============ 项目分区 ============
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

OVERWRITE_FLAG=""
[ -n "$OVERWRITE" ] && OVERWRITE_FLAG="--overwrite"
LIMIT_FLAG=""
[ "$LIMIT" -gt 0 ] 2>/dev/null && LIMIT_FLAG="--limit $LIMIT"

# 简单分区：前 10K edit，后 10K repair
echo "=== 项目分区 ==="
python3 -c "
import sys, shutil
from pathlib import Path

input_dir = Path('$INPUT_DIR')
output_dir = Path('$OUTPUT_DIR')
edit_dir = output_dir / 'text-editing'
repair_dir = output_dir / 'text-repair'
edit_dir.mkdir(parents=True, exist_ok=True)
repair_dir.mkdir(parents=True, exist_ok=True)

projects = sorted(d for d in input_dir.iterdir() if d.is_dir() and (d/'index.html').exists())

edit_projs = projects[:$EDIT_LIMIT]
repair_projs = projects[$EDIT_LIMIT:$EDIT_LIMIT+$REPAIR_LIMIT]

# 创建软链接
for proj in edit_projs:
    dst = edit_dir / proj.name
    if not dst.exists():
        dst.symlink_to(proj.resolve(), target_is_directory=True)

for proj in repair_projs:
    dst = repair_dir / proj.name
    if not dst.exists():
        dst.symlink_to(proj.resolve(), target_is_directory=True)

print(f'  text-editing: {len(edit_projs)} projects')
print(f'  text-repair: {len(repair_projs)} projects')
print(f'  total: {len(edit_projs)+len(repair_projs)} projects')
"

PARTITIONS="$OUTPUT_DIR"

# ============ text-editing（需要 LLM API）============
echo ""
echo "=== Phase 1: text-editing ==="
python3 WebCoding_Data/construct/construct_text_editing.py \
    --input-dir "$PARTITIONS/text-editing" \
    --output-dir "$OUTPUT_DIR/editing" \
    --min-tasks "$EDIT_MIN_TASKS" \
    --max-tasks "$EDIT_MAX_TASKS" \
    --seed "$SEED" \
    --max-retries "$MAX_RETRIES" \
    $LIMIT_FLAG $OVERWRITE_FLAG

# ============ text-repair（需要 LLM API）============
echo ""
echo "=== Phase 2: text-repair ==="
python3 WebCoding_Data/construct/construct_text_repair.py \
    --input-dir "$PARTITIONS/text-repair" \
    --output-dir "$OUTPUT_DIR/repair" \
    --min-tasks "$REPAIR_MIN_TASKS" \
    --max-tasks "$REPAIR_MAX_TASKS" \
    --seed "$SEED" \
    --max-retries "$MAX_RETRIES" \
    $LIMIT_FLAG $OVERWRITE_FLAG

echo ""
echo "=== Phase 1 完成 ==="
echo "输出目录: $OUTPUT_DIR"
echo "请将此目录传给 Phase 2 执行截图任务"
