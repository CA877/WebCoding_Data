#!/usr/bin/env bash
# WebCoding LoRA 微调启动脚本
# 用法: bash train/run_train.sh
set -uo pipefail

# ============ 配置区（按需修改）============
# LLaMA-Factory 安装路径
LLAMA_FACTORY_DIR="${LLAMA_FACTORY_DIR:-/mnt/shared-storage-user/colab-share/workspace_1/xwh_1/LLaMA-Factory}"
# 训练数据 JSONL 所在目录（构造脚本的输出）
DATA_ROOT="${DATA_ROOT:-/mnt/shared-storage-user/colab-share/liujiaheng/workspace/xieqianqian/webcoding_data}"
# GPU 数量
NUM_GPUS="${NUM_GPUS:-4}"
# ================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# LLaMA-Factory 数据目录
LF_DATA_DIR="$LLAMA_FACTORY_DIR/data"

echo "=== Step 1: 转换数据为 LLaMA-Factory 格式 ==="

# 收集所有 split JSONL
SPLIT_FILES=()
for split in text-repair text-generation text-editing; do
    # 构造脚本产出的 JSONL 分布在不同目录
    case "$split" in
        text-repair)     jsonl="$DATA_ROOT/repair/sp/$split.jsonl" ;;
        text-generation) jsonl="$DATA_ROOT/generate/sp/$split.jsonl" ;;
        text-editing)    jsonl="$DATA_ROOT/edit/sp/$split.jsonl" ;;
    esac
    if [ -f "$jsonl" ]; then
        SPLIT_FILES+=("$jsonl")
        echo "  找到: $jsonl"
    else
        echo "  跳过（不存在）: $jsonl"
    fi
done

if [ ${#SPLIT_FILES[@]} -eq 0 ]; then
    echo "ERROR: 没有找到任何 JSONL 文件"
    exit 1
fi

# 合并为 train.jsonl
MERGED_JSONL="$SCRIPT_DIR/train.jsonl"
cat "${SPLIT_FILES[@]}" > "$MERGED_JSONL"
TOTAL=$(wc -l < "$MERGED_JSONL" | tr -d ' ')
echo "  合并完成: $MERGED_JSONL ($TOTAL 条)"

# 转换为 sharegpt 格式
echo ""
echo "  转换中..."
python3 "$SCRIPT_DIR/convert_to_llamafactory.py" \
    --input "$MERGED_JSONL" \
    --output "$LF_DATA_DIR/train_sharegpt.json"

# 同时按 split 转换（可选，用于单任务训练）
for jsonl in "${SPLIT_FILES[@]}"; do
    stem=$(basename "$jsonl" .jsonl)
    python3 "$SCRIPT_DIR/convert_to_llamafactory.py" \
        --input "$jsonl" \
        --output "$LF_DATA_DIR/${stem}_sharegpt.json"
done

# 复制 dataset_info.json
echo ""
echo "  复制 dataset_info.json..."
# 合并到 LLaMA-Factory 的 dataset_info.json（追加，不覆盖已有条目）
python3 -c "
import json
from pathlib import Path

src = json.loads(Path('$SCRIPT_DIR/dataset_info.json').read_text())
dst_path = Path('$LF_DATA_DIR/dataset_info.json')
dst = json.loads(dst_path.read_text()) if dst_path.exists() else {}
dst.update(src)
dst_path.write_text(json.dumps(dst, ensure_ascii=False, indent=2))
print(f'  dataset_info.json 已更新: {list(src.keys())}')
"

# 复制训练配置
YAML_SRC="$SCRIPT_DIR/qwen3_vl_8b_lora.yaml"
YAML_DST="$LLAMA_FACTORY_DIR/examples/webcoding_lora.yaml"
cp "$YAML_SRC" "$YAML_DST"
echo "  训练配置: $YAML_DST"

echo ""
echo "=== Step 2: 启动 LoRA 训练 (${NUM_GPUS} GPUs) ==="
cd "$LLAMA_FACTORY_DIR"

FORCE_TORCHRUN=1 NNODES=1 NPROC_PER_NODE=$NUM_GPUS \
    llamafactory-cli train "$YAML_DST"
