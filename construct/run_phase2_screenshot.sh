#!/usr/bin/env bash
# Phase 2: 纯本地截图任务（不需要 API）
# image-generation, video-generation, image-editing, image-repair
# 在 Phase 1 完成后执行
set -euo pipefail

OUTPUT_DIR="${OUTPUT_DIR:?请设置 OUTPUT_DIR（Phase 1 的输出目录）}"
LIMIT="${LIMIT:-0}"
OVERWRITE="${OVERWRITE:-}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

OVERWRITE_FLAG=""
[ -n "$OVERWRITE" ] && OVERWRITE_FLAG="--overwrite"
LIMIT_FLAG=""
[ "$LIMIT" -gt 0 ] 2>/dev/null && LIMIT_FLAG="--limit $LIMIT"

PARTITIONS="$OUTPUT_DIR/.partitions"

# ============ image-generation（对项目截图）============
echo "=== Phase 2a: image-generation ==="
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
echo "=== Phase 2b: video-generation ==="
if [ -d "$PARTITIONS/video-generation" ]; then
    python3 WebCoding_Data/construct/construct_video_generation.py \
        --input-dir "$PARTITIONS/video-generation" \
        --output-dir "$OUTPUT_DIR/video-generation" \
        $LIMIT_FLAG $OVERWRITE_FLAG
else
    echo "  跳过（无分区）"
fi

# ============ image-editing（对 text-editing 结果截图）============
echo ""
echo "=== Phase 2c: image-editing ==="
if [ -d "$OUTPUT_DIR/text-editing" ]; then
    python3 WebCoding_Data/construct/construct_image_editing.py \
        --input-dir "$OUTPUT_DIR/text-editing" \
        --output-dir "$OUTPUT_DIR/image-editing" \
        $LIMIT_FLAG $OVERWRITE_FLAG
else
    echo "  跳过（text-editing 输出不存在）"
fi

# ============ image-repair（对 text-repair 结果截图 + apply patch）============
echo ""
echo "=== Phase 2d: image-repair ==="
if [ -d "$OUTPUT_DIR/text-repair" ]; then
    python3 WebCoding_Data/construct/construct_image_repair.py \
        --input-dir "$OUTPUT_DIR/text-repair" \
        --output-dir "$OUTPUT_DIR/image-repair" \
        $LIMIT_FLAG $OVERWRITE_FLAG
else
    echo "  跳过（text-repair 输出不存在）"
fi

echo ""
echo "=== Phase 2 完成 ==="
echo "输出目录: $OUTPUT_DIR"
echo ""

# 统计
echo "=== 各任务产出统计 ==="
for task in text-generation image-generation video-generation text-editing text-repair image-editing image-repair; do
    manifest="$OUTPUT_DIR/$task/manifest_${task//-/_}.jsonl"
    if [ -f "$manifest" ]; then
        ok=$(grep -c '"status": "ok"' "$manifest" 2>/dev/null || echo 0)
        err=$(grep -c '"status": "error"' "$manifest" 2>/dev/null || echo 0)
        printf "  %-20s ok=%-6s error=%-6s\n" "$task" "$ok" "$err"
    fi
done
