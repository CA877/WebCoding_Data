#!/usr/bin/env python3
"""
将项目 JSONL 训练数据转换为 LLaMA-Factory sharegpt 格式。

用法:
    # 转换所有 split
    python3 train/convert_to_llamafactory.py \
        --input train.jsonl \
        --output train_sharegpt.json

    # 转换单个 split
    python3 train/convert_to_llamafactory.py \
        --input splits/text-generation.jsonl \
        --output text-generation_sharegpt.json

    # 预览
    python3 train/convert_to_llamafactory.py \
        --input train.jsonl --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# ============ 序列化函数 ============

def serialize_code_files(code_files: list[dict]) -> str:
    """将代码文件列表序列化为文本。"""
    parts = []
    for f in code_files:
        path = f.get("path", "unknown")
        code = f.get("code", "")
        parts.append(f"```{path}\n{code}\n```")
    return "\n\n".join(parts)


def serialize_patches(patches: list[dict]) -> str:
    """将 search/replace patch 列表序列化为 XML 格式。"""
    parts = []
    for p in patches:
        path = p.get("path", "unknown")
        search = p.get("search", "")
        replace = p.get("replace", "")
        parts.append(
            f"<patch file=\"{path}\">\n"
            f"<search>\n{search}\n</search>\n"
            f"<replace>\n{replace}\n</replace>\n"
            f"</patch>"
        )
    return "\n\n".join(parts)


def serialize_descriptions(descriptions: list[dict]) -> str:
    """将编辑描述列表序列化为文本。"""
    parts = []
    for i, d in enumerate(descriptions, 1):
        task_type = d.get("task_type", "")
        desc = d.get("description", "")
        parts.append(f"{i}. [{task_type}] {desc}")
    return "\n".join(parts)


# ============ 各任务转换 ============

SYSTEM_PROMPTS = {
    "text-generation": (
        "You are a professional web developer. "
        "Given a product requirements document (PRD), generate the complete code implementation. "
        "Output all necessary files (HTML, CSS, JavaScript) with their paths."
    ),
    "text-repair": (
        "You are a professional web developer specializing in debugging. "
        "Given code with visual or functional defects, identify and fix all issues. "
        "Output the fixes as search/replace patches in XML format."
    ),
    "text-editing": (
        "You are a professional web developer. "
        "Given existing code and edit requirements, implement the requested changes. "
        "Output the edits as search/replace patches in XML format."
    ),
}


def convert_text_generation(record: dict) -> dict:
    instruction = record["instruction"]  # str: PRD
    response = record["response"]  # list[dict]: code files
    return {
        "system": SYSTEM_PROMPTS["text-generation"],
        "conversations": [
            {"from": "human", "value": instruction},
            {"from": "gpt", "value": serialize_code_files(response)},
        ],
    }


def convert_text_repair(record: dict) -> dict:
    instruction = record["instruction"]  # list[dict]: defective code files
    response = record["response"]  # list[dict]: patches

    human_text = (
        "The following code contains visual or functional defects. "
        "Please identify and fix all issues.\n\n"
        + serialize_code_files(instruction)
    )
    return {
        "system": SYSTEM_PROMPTS["text-repair"],
        "conversations": [
            {"from": "human", "value": human_text},
            {"from": "gpt", "value": serialize_patches(response)},
        ],
    }


def convert_text_editing(record: dict) -> dict:
    instruction = record["instruction"]  # dict: {src_code, description}
    response = record["response"]  # list[dict]: patches

    src_code = instruction.get("src_code", [])
    descriptions = instruction.get("description", [])

    human_text = (
        "Please make the following edits to the code:\n\n"
        + serialize_descriptions(descriptions)
        + "\n\nSource code:\n\n"
        + serialize_code_files(src_code)
    )
    return {
        "system": SYSTEM_PROMPTS["text-editing"],
        "conversations": [
            {"from": "human", "value": human_text},
            {"from": "gpt", "value": serialize_patches(response)},
        ],
    }


CONVERTERS = {
    "text-generation": convert_text_generation,
    "text-repair": convert_text_repair,
    "text-editing": convert_text_editing,
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert project JSONL to LLaMA-Factory sharegpt format"
    )
    parser.add_argument("--input", type=Path, required=True,
                        help="输入 JSONL 文件（train.jsonl 或 splits/*.jsonl）")
    parser.add_argument("--output", type=Path, default=None,
                        help="输出 JSON 文件（默认: {input_stem}_sharegpt.json）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只统计不写文件")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: 文件不存在: {args.input}", file=sys.stderr)
        sys.exit(1)

    if args.output is None:
        args.output = args.input.parent / f"{args.input.stem}_sharegpt.json"

    results = []
    errors = 0
    task_counts: dict[str, int] = {}

    with open(args.input, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"  L{lineno} JSON 解析错误: {e}", file=sys.stderr)
                errors += 1
                continue

            task = record.get("task", "")
            converter = CONVERTERS.get(task)
            if converter is None:
                print(f"  L{lineno} 未知 task={task!r}", file=sys.stderr)
                errors += 1
                continue

            try:
                converted = converter(record)
                results.append(converted)
                task_counts[task] = task_counts.get(task, 0) + 1
            except Exception as e:
                print(f"  L{lineno} 转换错误: {e}", file=sys.stderr)
                errors += 1

    print(f"转换完成: {len(results)} 条, {errors} 个错误")
    for task, count in sorted(task_counts.items()):
        print(f"  {task}: {count}")

    if args.dry_run:
        print("\n--dry-run 模式，不写文件。")
        if results:
            print("\n示例（第 1 条）:")
            sample = results[0]
            print(f"  system: {sample['system'][:80]}...")
            print(f"  human: {sample['conversations'][0]['value'][:80]}...")
            print(f"  gpt: {sample['conversations'][1]['value'][:80]}...")
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"写入 {args.output} ({len(results)} 条)")


if __name__ == "__main__":
    main()
