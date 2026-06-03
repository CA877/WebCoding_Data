#!/usr/bin/env bash
# Phase 2a: 不依赖 Phase 1 的截图任务（可与 Phase 1 同时跑）
# image-generation, video-generation — 直接对原始项目截图/录屏
set -euo pipefail

INPUT_DIR="${INPUT_DIR:?请设置 INPUT_DIR（清洗后的项目目录）}"
OUTPUT_DIR="${OUTPUT_DIR:?请设置 OUTPUT_DIR（输出目录）}"
LIMIT="${LIMIT:-0}"
SEED="${SEED:-0}"
PARTITION="${PARTITION:-2:2:1:2:2}"    # text-gen:image-gen:video-gen:text-edit:text-repair
OVERWRITE="${OVERWRITE:-}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

OVERWRITE_FLAG=""
[ -n "$OVERWRITE" ] && OVERWRITE_FLAG="--overwrite"
LIMIT_FLAG=""
[ "$LIMIT" -gt 0 ] 2>/dev/null && LIMIT_FLAG="--limit $LIMIT"

# ============ 确保分区存在 ============
PARTITIONS="$OUTPUT_DIR/.partitions"
if [ ! -d "$PARTITIONS" ]; then
    echo "=== 创建项目分区 ==="
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
fi

# ============ image-generation（对项目截图）============
echo ""
echo "=== image-generation ==="
if [ -d "$PARTITIONS/image-generation" ]; then
    python3 WebCoding_Data/construct/construct_image_generation.py \
        --input-dir "$PARTITIONS/image-generation" \
        --output-dir "$OUTPUT_DIR/image-generation" \
        $LIMIT_FLAG $OVERWRITE_FLAG
else
    echo "  跳过（无分区）"
fi

# ============ video-generation（对项目录屏）============
echo ""
echo "=== video-generation ==="
if [ -d "$PARTITIONS/video-generation" ]; then
    python3 WebCoding_Data/construct/construct_video_generation.py \
        --input-dir "$PARTITIONS/video-generation" \
        --output-dir "$OUTPUT_DIR/video-generation" \
        $LIMIT_FLAG $OVERWRITE_FLAG
else
    echo "  跳过（无分区）"
fi

echo ""
echo "=== Phase 2a 完成 ==="
echo "输出目录: $OUTPUT_DIR"

# 统计
echo ""
echo "=== 产出统计 ==="
for task in image-generation video-generation; do
    manifest="$OUTPUT_DIR/$task/manifest_${task//-/_}.jsonl"
    if [ -f "$manifest" ]; then
        ok=$(grep -c '"status": "ok"' "$manifest" 2>/dev/null || echo 0)
        err=$(grep -c '"status": "error"' "$manifest" 2>/dev/null || echo 0)
        printf "  %-20s ok=%-6s error=%-6s\n" "$task" "$ok" "$err"
    fi
done
