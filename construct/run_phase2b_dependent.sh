#!/usr/bin/env bash
# Phase 2b: 依赖 Phase 1 的截图任务（需要 text-editing/text-repair 输出）
# image-editing, image-repair
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

# ============ image-editing（对 text-editing 结果截图）============
echo "=== image-editing ==="
if [ -d "$OUTPUT_DIR/text-editing" ]; then
    python3 WebCoding_Data/construct/construct_image_editing.py \
        --input-dir "$OUTPUT_DIR/text-editing" \
        --output-dir "$OUTPUT_DIR/image-editing" \
        $LIMIT_FLAG $OVERWRITE_FLAG
else
    echo "  跳过（text-editing 输出不存在，需要先跑 Phase 1）"
fi

# ============ image-repair（对 text-repair 结果截图 + apply patch）============
echo ""
echo "=== image-repair ==="
if [ -d "$OUTPUT_DIR/text-repair" ]; then
    python3 WebCoding_Data/construct/construct_image_repair.py \
        --input-dir "$OUTPUT_DIR/text-repair" \
        --output-dir "$OUTPUT_DIR/image-repair" \
        $LIMIT_FLAG $OVERWRITE_FLAG
else
    echo "  跳过（text-repair 输出不存在，需要先跑 Phase 1）"
fi

echo ""
echo "=== Phase 2b 完成 ==="
echo "输出目录: $OUTPUT_DIR"

# 统计（包含所有已有任务）
echo ""
echo "=== 全部产出统计 ==="
for task in text-generation image-generation video-generation text-editing text-repair image-editing image-repair; do
    manifest="$OUTPUT_DIR/$task/manifest_${task//-/_}.jsonl"
    if [ -f "$manifest" ]; then
        ok=$(grep -c '"status": "ok"' "$manifest" 2>/dev/null || echo 0)
        err=$(grep -c '"status": "error"' "$manifest" 2>/dev/null || echo 0)
        printf "  %-20s ok=%-6s error=%-6s\n" "$task" "$ok" "$err"
    fi
done
