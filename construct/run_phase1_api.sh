#!/usr/bin/env bash
# Phase 1: 需要 API 的任务（text-editing, text-repair, text-generation）
# 给有 API 的人跑，跑完把 OUTPUT_DIR 传回来
set -euo pipefail

# ============ 必须配置 ============
INPUT_DIR="${INPUT_DIR:-./single_page}"
OUTPUT_DIR="${OUTPUT_DIR:-./output}"

# API 配置
export OPENAI_API_KEY="0356831d861695f2622f50025b9ee465"
export OPENAI_BASE_URL="https://idealab.alibaba-inc.com/api/openai/v1"
export OPENAI_MODEL="kimi-k2.6"

# 视觉模型（text-generation 的 PRD 需要，同一套 API）
export VISION_OPENAI_API_KEY="$OPENAI_API_KEY"
export VISION_OPENAI_BASE_URL="$OPENAI_BASE_URL"
export VISION_MODEL="Qwen3-235B-A22B"

# ============ 可选配置 ============
LIMIT="${LIMIT:-0}"                    # 0=不限制
SEED="${SEED:-0}"
PARTITION="${PARTITION:-2:2:1:2:2}"    # text-gen:image-gen:video-gen:text-edit:text-repair
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

# 用 Python 做项目分区
echo "=== 项目分区 ==="
python3 -c "
import sys; sys.path.insert(0, '.')
from WebCoding_Data.construct.construct_webcode2m_dataset import resolve_projects_dir, partition_projects, create_partition_dir
from pathlib import Path
import json

input_dir = Path('$INPUT_DIR')
output_dir = Path('$OUTPUT_DIR')
output_dir.mkdir(parents=True, exist_ok=True)

projects_dir = resolve_projects_dir(input_dir)
groups = partition_projects(projects_dir, '$PARTITION', $SEED)
for task, projs in groups.items():
    print(f'  {task}: {len(projs)} projects')
    if projs:
        create_partition_dir(output_dir, task, projs)
print(f'  total: {sum(len(p) for p in groups.values())} projects')

# 保存分区信息
info = {task: len(projs) for task, projs in groups.items()}
(output_dir / 'partition_info.json').write_text(json.dumps(info, indent=2))
"

PARTITIONS="$OUTPUT_DIR/.partitions"

# ============ text-generation（需要 VLM API）============
echo ""
echo "=== Phase 1a: text-generation ==="
if [ -d "$PARTITIONS/text-generation" ]; then
    python3 WebCoding_Data/construct/construct_text_generation.py \
        --input-dir "$PARTITIONS/text-generation" \
        --output-dir "$OUTPUT_DIR/text-generation" \
        $LIMIT_FLAG $OVERWRITE_FLAG
else
    echo "  跳过（无分区）"
fi

# ============ text-editing（需要 LLM API）============
echo ""
echo "=== Phase 1b: text-editing ==="
if [ -d "$PARTITIONS/text-editing" ]; then
    python3 WebCoding_Data/construct/construct_text_editing.py \
        --input-dir "$PARTITIONS/text-editing" \
        --output-dir "$OUTPUT_DIR/text-editing" \
        --min-tasks "$EDIT_MIN_TASKS" \
        --max-tasks "$EDIT_MAX_TASKS" \
        --seed "$SEED" \
        --max-retries "$MAX_RETRIES" \
        $LIMIT_FLAG $OVERWRITE_FLAG
else
    echo "  跳过（无分区）"
fi

# ============ text-repair（需要 LLM API）============
echo ""
echo "=== Phase 1c: text-repair ==="
if [ -d "$PARTITIONS/text-repair" ]; then
    python3 WebCoding_Data/construct/construct_text_repair.py \
        --input-dir "$PARTITIONS/text-repair" \
        --output-dir "$OUTPUT_DIR/text-repair" \
        --min-tasks "$REPAIR_MIN_TASKS" \
        --max-tasks "$REPAIR_MAX_TASKS" \
        --seed "$SEED" \
        --max-retries "$MAX_RETRIES" \
        $LIMIT_FLAG $OVERWRITE_FLAG
else
    echo "  跳过（无分区）"
fi

echo ""
echo "=== Phase 1 完成 ==="
echo "输出目录: $OUTPUT_DIR"
echo "请将此目录传给 Phase 2 执行截图任务"
