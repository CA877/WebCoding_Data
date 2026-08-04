#!/usr/bin/env python3
"""Strict structural audit for the six-task WebCompass release-v2 JSONLs."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


TASK_FILES = {
    "text-generation": "text-generate.jsonl",
    "image-generation": "image-generate.jsonl",
    "text-editing": "text-edit.jsonl",
    "image-editing": "image-edit.jsonl",
    "text-repair": "text-repair.jsonl",
    "image-repair": "image-repair.jsonl",
}


def apply_exact(code: list[dict], patches: list[dict]) -> None:
    code_map = {item["path"]: item["code"] for item in code}
    for index, patch in enumerate(patches):
        path, search, replace = patch["path"], patch["search"], patch["replace"]
        if path not in code_map or not search or search == replace:
            raise ValueError(f"invalid patch {index} for {path}")
        count = code_map[path].count(search)
        if count != 1:
            raise ValueError(f"patch {index} search count is {count}, expected 1")
        code_map[path] = code_map[path].replace(search, replace, 1)


def input_code(record: dict) -> list[dict] | None:
    task = record["task"]
    if task == "text-editing":
        return record["instruction"]["src_code"]
    if task == "text-repair":
        return record["instruction"]
    if task in {"image-editing", "image-repair"}:
        return record["input_files"]
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jsonl-dir", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--expected-generate", type=int, default=6502)
    parser.add_argument("--expected-edit", type=int, default=3000)
    parser.add_argument("--expected-image-repair", type=int, default=3000)
    args = parser.parse_args()

    ids: dict[str, set[str]] = {}
    counts: dict[str, int] = {}
    task_count_distributions: dict[str, dict[str, int]] = {}
    errors: list[str] = []
    for task, name in TASK_FILES.items():
        path = args.jsonl_dir / name
        seen: set[str] = set()
        distribution: Counter[int] = Counter()
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                try:
                    record = json.loads(line)
                    instance_id = str(record["instance_id"])
                    if instance_id in seen:
                        raise ValueError("duplicate instance_id")
                    seen.add(instance_id)
                    if record.get("task") != task:
                        raise ValueError(f"task={record.get('task')!r}, expected {task!r}")
                    if int(record.get("metadata", {}).get("prompt_tokens", 0)) > 40000:
                        raise ValueError("prompt_tokens exceeds 40K")
                    if record.get("metadata", {}).get("input_contract", {}).get("all_files_included") is not True:
                        raise ValueError("all-files input contract missing")
                    if task == "image-generation" and record.get("instruction"):
                        raise ValueError("image-generation must not contain a text query")
                    if task == "text-generation" and not str(record.get("instruction", "")).strip():
                        raise ValueError("text-generation query is empty")
                    if task.startswith("image-"):
                        images = record.get("input_images", [])
                        if not images or any(not Path(image).is_file() for image in images):
                            raise ValueError("missing input image")
                    code = input_code(record)
                    if task in {"text-generation", "image-generation"}:
                        output_paths = {item["path"] for item in record["response"]}
                        manifest_paths = {item["path"] for item in record.get("file_manifest", []) if item.get("type") == "code"}
                        if output_paths != manifest_paths:
                            raise ValueError("generation response does not contain every code file")
                    if code is not None:
                        task_types = list(record.get("task_type", []))
                        if not 1 <= len(task_types) <= 7 or len(task_types) != len(set(task_types)):
                            raise ValueError("task_type count must be 1--7 and distinct")
                        distribution[len(task_types)] += 1
                        patches = record["response"]
                        mapping = Counter(str(patch.get("task_type", "")) for patch in patches)
                        if set(mapping) != set(task_types) or any(not 1 <= value <= 10 for value in mapping.values()):
                            raise ValueError("task-to-patch mapping violates 1--10 contract")
                        apply_exact(code, patches)
                        code_paths = {item["path"] for item in code}
                        manifest_paths = {item["path"] for item in record.get("file_manifest", []) if item.get("type") == "code"}
                        if code_paths != manifest_paths:
                            raise ValueError("input does not contain every code file")
                    if task == "image-repair":
                        ratio = float(record.get("metadata", {}).get("visual_difference", {}).get("max_changed_ratio", 0))
                        if ratio < 0.01 or not record.get("dst_screenshot"):
                            raise ValueError("image-repair fails 1% paired-image gate")
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{name}:{line_number}: {type(exc).__name__}: {exc}")
        ids[task] = seen
        counts[task] = len(seen)
        task_count_distributions[task] = {str(key): value for key, value in sorted(distribution.items())}

    expected = {
        "text-generation": args.expected_generate,
        "image-generation": args.expected_generate,
        "text-editing": args.expected_edit,
        "image-editing": args.expected_edit,
        "image-repair": args.expected_image_repair,
    }
    for task, count in expected.items():
        if counts.get(task) != count:
            errors.append(f"{task}: count={counts.get(task)}, expected={count}")
    for left, right in (("text-generation", "image-generation"), ("text-editing", "image-editing")):
        if ids[left] != ids[right]:
            errors.append(f"paired ids differ: {left} vs {right}")
    if not ids["image-repair"].issubset(ids["text-repair"]):
        errors.append("image-repair ids are not a subset of text-repair ids")

    summary = {
        "status": "pass" if not errors else "fail",
        "counts": counts,
        "task_count_distributions": task_count_distributions,
        "errors": errors[:1000],
        "error_count": len(errors),
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
