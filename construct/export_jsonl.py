#!/usr/bin/env python3
"""
将构造脚本产出的 per-project info.json 转换为统一 JSONL 训练格式。

注意: 构造脚本（construct_text_*.py）已在处理每个 case 时实时追加写入 JSONL，
本脚本用于从 info.json 批量补生成，或合并多个 split 为 train.jsonl。

用法:
    # 从 info.json 批量转换
    python3 construct/export_jsonl.py \
        --input-dirs /path/to/repair/sp /path/to/generate/sp \
        --dataset-dir ./dataset

    # 合并已有的 split JSONL（跳过 info.json 扫描）
    python3 construct/export_jsonl.py \
        --merge-splits /path/to/repair/sp/text-repair.jsonl /path/to/generate/sp/text-generation.jsonl \
        --dataset-dir ./dataset

    # 预览不写文件
    python3 construct/export_jsonl.py \
        --input-dirs /path/to/repair/sp \
        --dataset-dir ./dataset --dry-run

输出结构:
    dataset/
    ├── train.jsonl                   # 所有样本合并
    └── splits/
        ├── text-generation.jsonl
        ├── text-repair.jsonl
        └── text-editing.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from WebCoding_Data.construct.construct_common import info_to_training_record

# task 字段 → split 文件名
TASK_TO_SPLIT = {
    "text-generation": "text-generation",
    "repair": "text-repair",
    "edit": "text-editing",
}


def iter_info_jsons(input_dir: Path):
    """递归查找 input_dir 下所有 info.json。"""
    yield from sorted(input_dir.rglob("info.json"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Export info.json → unified JSONL")
    parser.add_argument("--input-dirs", type=Path, nargs="+", default=[],
                        help="构造脚本的输出目录（可多个），从 info.json 转换")
    parser.add_argument("--merge-splits", type=Path, nargs="+", default=[],
                        help="已有的 split JSONL 文件（可多个），直接合并")
    parser.add_argument("--dataset-dir", type=Path, required=True,
                        help="JSONL 输出目录")
    parser.add_argument("--dry-run", action="store_true",
                        help="只统计不写文件")
    args = parser.parse_args()

    if not args.input_dirs and not args.merge_splits:
        parser.error("需要 --input-dirs 或 --merge-splits 至少一个")

    splits: dict[str, list[dict]] = {}
    errors = 0

    # 模式 1: 从 info.json 转换
    for d in args.input_dirs:
        if not d.exists():
            print(f"WARNING: 目录不存在，跳过: {d}", file=sys.stderr)
            continue
        found = list(iter_info_jsons(d))
        print(f"  {d}: {len(found)} info.json")

        for info_path in found:
            try:
                info = json.loads(info_path.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"  ERROR 读取 {info_path}: {e}", file=sys.stderr)
                errors += 1
                continue

            record = info_to_training_record(info)
            if record is None:
                print(f"  WARNING 未知 task={info.get('task')!r}: {info_path}", file=sys.stderr)
                errors += 1
                continue

            split_name = TASK_TO_SPLIT.get(info["task"], info["task"])
            splits.setdefault(split_name, []).append(record)

    # 模式 2: 合并已有 split JSONL
    for jsonl_path in args.merge_splits:
        if not jsonl_path.exists():
            print(f"WARNING: 文件不存在，跳过: {jsonl_path}", file=sys.stderr)
            continue
        count = 0
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except Exception as e:
                    print(f"  ERROR 解析 {jsonl_path}: {e}", file=sys.stderr)
                    errors += 1
                    continue
                split_name = record.get("task", jsonl_path.stem)
                splits.setdefault(split_name, []).append(record)
                count += 1
        print(f"  {jsonl_path}: {count} 条")

    # 统计
    total = sum(len(v) for v in splits.values())
    print(f"\n共 {total} 条记录, {errors} 个错误")
    for name, records in sorted(splits.items()):
        print(f"  {name}: {len(records)}")

    if args.dry_run:
        print("\n--dry-run 模式，不写文件。")
        return

    # 写文件
    splits_dir = args.dataset_dir / "splits"
    splits_dir.mkdir(parents=True, exist_ok=True)

    train_path = args.dataset_dir / "train.jsonl"
    train_count = 0

    with open(train_path, "w", encoding="utf-8") as train_f:
        for split_name, records in sorted(splits.items()):
            split_path = splits_dir / f"{split_name}.jsonl"
            with open(split_path, "w", encoding="utf-8") as split_f:
                for record in records:
                    line = json.dumps(record, ensure_ascii=False)
                    split_f.write(line + "\n")
                    train_f.write(line + "\n")
                    train_count += 1
            print(f"  写入 {split_path} ({len(records)} 条)")

    print(f"  写入 {train_path} ({train_count} 条)")
    print("完成!")


if __name__ == "__main__":
    main()
