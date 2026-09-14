#!/usr/bin/env python3
"""Create a physical-copy release with WebCompass-compatible model inputs."""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import json
import os
from pathlib import Path
import shutil
from typing import Any

from scripts.build_0805_combined_training_view import SHARD_NAME, TASKS, sha256


MODEL_INPUT_TASKS = ("image-generate", "text-repair", "image-repair")
IMAGE_GENERATE_INSTRUCTION = (
    "Generate a complete runnable web project that matches the provided reference "
    "screenshot(s) as closely as possible. Reproduce the visible layout, colors, "
    "typography, spacing, UI components, and responsive behavior. Implement interactions "
    "that are clearly implied by the screenshots. Output all required HTML, CSS, and "
    "JavaScript files with their paths."
)


def build_repair_instruction(issue_count: int) -> str:
    """Build the label-free Repair instruction used by WebCompass."""
    if issue_count < 1:
        raise ValueError("repair issue_count must be positive")
    return (
        "Repair the provided web project. "
        f"You have only {issue_count} issues to fix, and you can not fix more than "
        f"{issue_count} issues."
    )


def _repair_task_types(record: dict[str, Any]) -> list[str]:
    raw = record.get("task_type")
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            f"{record.get('instance_id', '<unknown>')} Repair requires a non-empty task_type list"
        )
    labels = [str(item).strip() for item in raw]
    if any(not label for label in labels):
        raise ValueError(f"{record.get('instance_id', '<unknown>')} has an empty task_type")
    return labels


def normalize_model_input_record(task: str, record: dict[str, Any]) -> dict[str, Any]:
    """Return a normalized record without mutating the source object."""
    normalized = dict(record)
    if task == "image-generate":
        normalized["instruction"] = IMAGE_GENERATE_INSTRUCTION
        return normalized
    if task not in {"text-repair", "image-repair"}:
        return normalized

    labels = _repair_task_types(record)
    prompt = build_repair_instruction(len(labels))
    prompt_folded = prompt.casefold()
    leaked = [label for label in labels if label.casefold() in prompt_folded]
    if leaked:
        raise ValueError(
            f"{record.get('instance_id', '<unknown>')} Repair prompt leaks task_type: {leaked}"
        )
    normalized["repair_instruction"] = prompt
    if task == "text-repair":
        if not isinstance(record.get("instruction"), list) or not record["instruction"]:
            raise ValueError(
                f"{record.get('instance_id', '<unknown>')} text-repair instruction must be code files"
            )
    else:
        if not isinstance(record.get("input_files"), list) or not record["input_files"]:
            raise ValueError(
                f"{record.get('instance_id', '<unknown>')} image-repair input_files must be code files"
            )
        normalized["instruction"] = prompt
    return normalized


def _rewrite_task_shard(
    task: str, source: Path, destination: Path
) -> tuple[int, Counter[int], int, bool]:
    rows = 0
    issue_counts: Counter[int] = Counter()
    label_leaks = 0
    content_changed = False
    temporary = destination.with_name(destination.name + f".rewrite-{os.getpid()}")
    try:
        with gzip.open(source, "rt", encoding="utf-8") as reader, gzip.open(
            temporary, "wt", encoding="utf-8", compresslevel=6
        ) as writer:
            for rows, line in enumerate(reader, 1):
                record = json.loads(line)
                normalized = normalize_model_input_record(task, record)
                content_changed = content_changed or normalized != record
                if task in {"text-repair", "image-repair"}:
                    labels = _repair_task_types(normalized)
                    issue_counts[len(labels)] += 1
                    prompt = str(normalized["repair_instruction"])
                    if any(label.casefold() in prompt.casefold() for label in labels):
                        label_leaks += 1
                writer.write(
                    json.dumps(normalized, ensure_ascii=False, separators=(",", ":")) + "\n"
                )
        if content_changed:
            os.replace(temporary, destination)
        else:
            temporary.unlink()
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return rows, issue_counts, label_leaks, content_changed


def _copy_release(source: Path, destination: Path) -> None:
    for child in source.iterdir():
        if child.name == ".ms_upload_cache":
            continue
        target = destination / child.name
        if child.is_symlink():
            raise ValueError(f"source release contains a symlink: {child}")
        if child.is_dir():
            shutil.copytree(
                child,
                target,
                symlinks=False,
                copy_function=shutil.copy2,
            )
        elif child.is_file():
            shutil.copy2(child, target)


def _materialization_counts(root: Path) -> tuple[int, int, int, int]:
    files = 0
    total_bytes = 0
    symlinks = 0
    hardlinked_files = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            symlinks += 1
        elif path.is_file():
            files += 1
            stat = path.stat()
            total_bytes += stat.st_size
            if stat.st_nlink != 1:
                hardlinked_files += 1
    return files, total_bytes, symlinks, hardlinked_files


def finalize_validation_file(root: Path, validation: dict[str, Any]) -> dict[str, Any]:
    """Write validation.json until its self-inclusive byte total is stable."""
    validation_path = root / "validation.json"
    for _attempt in range(4):
        validation_path.write_text(
            json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        files, total_bytes, symlinks, hardlinked_files = _materialization_counts(root)
        if files != validation["expected_files"] or symlinks or hardlinked_files:
            raise ValueError(
                {
                    "files": files,
                    "expected_files": validation["expected_files"],
                    "symlinks": symlinks,
                    "hardlinked_files": hardlinked_files,
                }
            )
        if validation.get("files") == files and validation.get("bytes") == total_bytes:
            return validation
        validation.update({"files": files, "bytes": total_bytes})
    raise ValueError("validation.json byte total did not stabilize")


def _task_contract() -> dict[str, Any]:
    hidden = ["task_type"]
    return {
        "image-generate": {
            "text_field": "instruction",
            "required_text": IMAGE_GENERATE_INSTRUCTION,
            "image_fields": ["input_images"],
        },
        "text-repair": {
            "text_field": "repair_instruction",
            "code_field": "instruction",
            "hidden_metadata_fields": hidden,
            "task_type_values_model_visible": False,
        },
        "image-repair": {
            "text_field": "repair_instruction",
            "legacy_text_field_with_same_value": "instruction",
            "code_field": "input_files",
            "current_image_field": "src_screenshot",
            "target_image_field": "dst_screenshot",
            "hidden_metadata_fields": hidden,
            "task_type_values_model_visible": False,
        },
    }


def repackage_release(source_root: Path, output_root: Path) -> dict[str, Any]:
    """Repackage an existing combined release into a new physical-copy directory."""
    source_root = source_root.resolve()
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite {output_root}")
    if not source_root.is_dir():
        raise FileNotFoundError(source_root)
    source_index_path = source_root / "dataset_index.json"
    source_validation_path = source_root / "validation.json"
    if not source_index_path.is_file() or not source_validation_path.is_file():
        raise FileNotFoundError("source dataset_index.json or validation.json is missing")
    source_index = json.loads(source_index_path.read_text(encoding="utf-8"))
    if set(source_index.get("tasks", {})) != set(TASKS):
        raise ValueError("source task set mismatch")
    if source_index.get("materialization") != "full_copy_no_links":
        raise ValueError("source is not a fully materialized release")

    source_files, source_bytes, source_symlinks, _source_hardlinks = _materialization_counts(
        source_root
    )
    if source_symlinks:
        raise ValueError(f"source release contains {source_symlinks} symlinks")
    required_bytes = source_bytes + 2 * 1024**3
    output_root.parent.mkdir(parents=True, exist_ok=True)
    free_bytes = shutil.disk_usage(output_root.parent).free
    print(
        json.dumps(
            {
                "status": "space_preflight",
                "source_files": source_files,
                "source_bytes": source_bytes,
                "required_bytes": required_bytes,
                "free_bytes": free_bytes,
            }
        ),
        flush=True,
    )
    if free_bytes < required_bytes:
        raise OSError(
            f"insufficient free space under {output_root.parent}: "
            f"required={required_bytes} free={free_bytes}"
        )

    temporary = output_root.parent / f".{output_root.name}.incomplete-{os.getpid()}"
    if temporary.exists():
        raise FileExistsError(temporary)
    temporary.mkdir()
    try:
        _copy_release(source_root, temporary)
        audit: dict[str, Any] = {}
        for task in MODEL_INPUT_TASKS:
            shard = temporary / task / SHARD_NAME
            expected_rows = int(source_index["tasks"][task]["num_samples"])
            rows, issue_counts, label_leaks, content_changed = _rewrite_task_shard(
                task, shard, shard
            )
            if rows != expected_rows:
                raise ValueError(f"{task} rows={rows}, expected={expected_rows}")
            task_audit: dict[str, Any] = {
                "rows": rows,
                "task_type_value_leaks_into_model_instruction": label_leaks,
                "shard_content_changed": content_changed,
            }
            if task == "image-generate":
                task_audit["shared_instruction_rows"] = rows
            else:
                task_audit["issue_count_distribution"] = {
                    str(key): value for key, value in sorted(issue_counts.items())
                }
            audit[task] = task_audit
            if label_leaks:
                raise ValueError(f"{task} has {label_leaks} task_type value leaks")
            print(
                json.dumps({"status": "task_normalized", "task": task, **task_audit}),
                flush=True,
            )

        tasks = source_index["tasks"]
        for task in TASKS:
            shard = temporary / task / SHARD_NAME
            tasks[task]["sha256"] = sha256(shard)
            tasks[task]["compressed_gib"] = round(shard.stat().st_size / 1024**3, 3)

        index = dict(source_index)
        index.update(
            {
                "name": "reversed",
                "schema_version": "webcoding-sft-v2-combined-v3",
                "derived_from_release": {
                    "name": source_index.get("name"),
                    "directory_name": source_root.name,
                    "dataset_index_sha256": sha256(source_index_path),
                },
                "model_input_contract": _task_contract(),
                "tasks": tasks,
                "notes": [
                    "All rows and images from the combined source release are retained.",
                    "Every image-generate record carries the same screenshot-grounded generic instruction.",
                    "Repair model instructions state only N; task_type values remain hidden metadata.",
                    "All images are ordinary copied files; there are no symbolic links or hard links.",
                ],
            }
        )
        (temporary / "dataset_index.json").write_text(
            json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        total_rows = sum(int(item["num_samples"]) for item in tasks.values())
        total_images = sum(int(item.get("image_files", 0)) for item in tasks.values())
        (temporary / "README.md").write_text(
            "# reversed\n\n"
            "0805 与 0805_supplement 的完整合并训练包，保持 0805 v2 的六任务目录、"
            "单 gzip shard、代码字段和图片相对路径。图片全部是包内普通实体文件。\n\n"
            "模型输入约定：每条 `image-generate.instruction` 均为同一条截图驱动通用提示词；"
            "`text-repair` 从 `repair_instruction` 读取含 N 的文本、从 `instruction` 读取缺陷源码；"
            "`image-repair` 从 `repair_instruction`（与 `instruction` 相同）读取含 N 的文本、"
            "从 `input_files` 读取缺陷源码，并使用 `src_screenshot` / `dst_screenshot`。"
            "`task_type` 仅保留为隐藏元数据，不得拼入模型输入。\n\n"
            f"总样本数：{total_rows}；总图片数：{total_images}。详细字段和 SHA-256 见 "
            "`dataset_index.json`。\n",
            encoding="utf-8",
        )
        validation = {
            "status": "ok",
            "source_release": source_root.name,
            "task_count": len(TASKS),
            "total_samples": total_rows,
            "total_images": total_images,
            "model_input_audit": audit,
            "symlinks": 0,
            "hardlinked_files": 0,
            "expected_files": 3 + len(TASKS) + total_images,
        }
        validation = finalize_validation_file(temporary, validation)
        os.replace(temporary, output_root)
        print(
            json.dumps(
                {"status": "ok", "output_root": str(output_root), **validation},
                ensure_ascii=False,
            ),
            flush=True,
        )
        return index
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    repackage_release(args.source_root, args.output_root)


if __name__ == "__main__":
    main()
