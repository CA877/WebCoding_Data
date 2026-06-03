#!/usr/bin/env bash
# Phase 1: 需要 API 的任务（text-generation, text-editing, text-repair）
# 给有 API 的人跑，跑完把 OUTPUT_DIR 传回来
set -euo pipefail

# ============ 必须配置 ============
INPUT_DIR="${INPUT_DIR:?请设置 INPUT_DIR（清洗后的项目目录）}"
OUTPUT_DIR="${OUTPUT_DIR:?请设置 OUTPUT_DIR（输出目录）}"

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

# ============ 初始化 ============
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

OVERWRITE_FLAG=""
[ -n "$OVERWRITE" ] && OVERWRITE_FLAG="--overwrite"
LIMIT_FLAG=""
[ "$LIMIT" -gt 0 ] 2>/dev/null && LIMIT_FLAG="--limit $LIMIT"

PARTITIONS="$OUTPUT_DIR/.partitions"

# ============ 统一分区（与 Phase 2a 共享） ============
if [ ! -d "$PARTITIONS" ]; then
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

info = {task: len(projs) for task, projs in groups.items()}
(output_dir / 'partition_info.json').write_text(json.dumps(info, indent=2))
"
else
    echo "=== 分区已存在，跳过 ==="
    cat "$OUTPUT_DIR/partition_info.json" 2>/dev/null || true
fi

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
echo "请将此目录传给 Phase 2b 执行截图任务"

# 统计
echo ""
echo "=== 产出统计 ==="
for task in text-generation text-editing text-repair; do
    manifest="$OUTPUT_DIR/$task/manifest_${task//-/_}.jsonl"
    if [ -f "$manifest" ]; then
        ok=$(grep -c '"status": "ok"' "$manifest" 2>/dev/null || echo 0)
        err=$(grep -c '"status": "error"' "$manifest" 2>/dev/null || echo 0)
        printf "  %-20s ok=%-6s error=%-6s\n" "$task" "$ok" "$err"
    fi
done
