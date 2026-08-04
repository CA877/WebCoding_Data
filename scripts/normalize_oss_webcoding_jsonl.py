#!/usr/bin/env python3
"""Normalize WebCoding OSS JSONL samples into a unified, apply-checked schema.

The script is intentionally non-destructive: it only reads source JSONL files and
writes converted files plus summaries to a separate output directory.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any


SOURCE_FILES = {
    "text-generation": "text-generation.jsonl",
    "text-editing": "text-editing.jsonl",
    "text-repair": "text-repair.jsonl",
}


def read_jsonl(path: Path, limit: int | None):
    count = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            if limit is not None and count >= limit:
                break
            yield json.loads(line)
            count += 1


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def strip_cdata(value: str) -> str:
    if value.startswith("<![CDATA[") and value.endswith("]]>"):
        return value[9:-3]
    return value


def transform_text(value: str, transform: str) -> str:
    if transform == "exact":
        return value
    if transform == "html_unescape":
        return html.unescape(value)
    if transform == "strip_cdata":
        return strip_cdata(value)
    if transform == "strip_cdata_html_unescape":
        return html.unescape(strip_cdata(value))
    if transform == "html_unescape_strip_cdata":
        return strip_cdata(html.unescape(value))
    raise ValueError(f"unknown transform: {transform}")


TRANSFORMS = [
    "exact",
    "html_unescape",
    "strip_cdata",
    "strip_cdata_html_unescape",
    "html_unescape_strip_cdata",
]


def line_col(text: str, offset: int) -> dict[str, int]:
    line = text.count("\n", 0, offset) + 1
    last_newline = text.rfind("\n", 0, offset)
    col = offset + 1 if last_newline < 0 else offset - last_newline
    return {"line": line, "column": col}


def find_unique(code: str, search: str) -> tuple[str | None, str | None, int | None]:
    for transform in TRANSFORMS:
        candidate = transform_text(search, transform)
        count = code.count(candidate)
        if count == 1:
            return candidate, transform, code.index(candidate)
        if count > 1:
            return None, f"ambiguous:{transform}:{count}", None
    return None, "not_found", None


def apply_patch_items(
    input_files: list[dict[str, str]],
    patch_items: list[dict[str, Any]],
    *,
    allow_inverse: bool = False,
) -> tuple[list[dict[str, str]] | None, list[dict[str, Any]], list[str]]:
    files = {item["path"]: item["code"] for item in input_files}
    normalized_patches: list[dict[str, Any]] = []
    errors: list[str] = []

    for patch_index, patch in enumerate(patch_items):
        path = patch.get("path")
        raw_search = patch.get("search")
        raw_replace = patch.get("replace")
        if not isinstance(path, str) or not isinstance(raw_search, str) or not isinstance(raw_replace, str):
            errors.append(f"patch {patch_index}: invalid patch item types")
            continue
        if path not in files:
            errors.append(f"patch {patch_index}: path not in input files: {path}")
            continue

        current = files[path]
        search, transform, offset = find_unique(current, raw_search)
        direction = "repair"
        if search is None or transform is None or offset is None:
            if allow_inverse:
                inverse_search, inverse_transform, inverse_offset = find_unique(current, raw_replace)
                if inverse_search is not None and inverse_transform is not None and inverse_offset is not None:
                    search = inverse_search
                    transform = inverse_transform
                    offset = inverse_offset
                    direction = "inject_bug"
                else:
                    errors.append(
                        f"patch {patch_index}: neither search nor replace found uniquely in {path}"
                    )
                    normalized_patches.append(
                        {
                            "path": path,
                            "search": raw_search,
                            "replace": raw_replace,
                            "status": "failed",
                            "match_strategy": f"search={transform};replace={inverse_transform}",
                        }
                    )
                    continue
            else:
                errors.append(f"patch {patch_index}: search {transform} in {path}")
                normalized_patches.append(
                    {
                        "path": path,
                        "search": raw_search,
                        "replace": raw_replace,
                        "status": "failed",
                        "match_strategy": transform,
                    }
                )
                continue

        if direction == "repair":
            repair_search = search
            repair_replace = transform_text(raw_replace, transform)
            applied_search = repair_search
            applied_replace = repair_replace
        else:
            repair_search = transform_text(raw_search, transform)
            repair_replace = search
            applied_search = repair_replace
            applied_replace = repair_search

        replace = applied_replace
        files[path] = current[:offset] + applied_replace + current[offset + len(applied_search) :]
        normalized_patches.append(
            {
                "path": path,
                "search": repair_search,
                "replace": repair_replace,
                "status": "applied",
                "match_strategy": transform,
                "direction": direction,
                "location": line_col(current, offset),
            }
        )

    if errors:
        return None, normalized_patches, errors

    output_files = [{"path": path, "code": code} for path, code in files.items()]
    return output_files, normalized_patches, []


def apply_repair_patch_items(
    source_files: list[dict[str, str]], patch_items: list[dict[str, Any]]
) -> tuple[list[dict[str, str]] | None, list[dict[str, str]] | None, list[dict[str, Any]], list[str], str | None]:
    """Create buggy input files and fixed output files for repair training.

    Repair labels are interpreted as search=buggy snippet and replace=fixed snippet.
    Some source records already contain the buggy snippet; others contain the fixed
    snippet and need inverse bug injection. This function supports both cases per
    patch and always emits training patches in buggy -> fixed orientation.
    """

    buggy = {item["path"]: item["code"] for item in source_files}
    fixed = {item["path"]: item["code"] for item in source_files}
    normalized_patches: list[dict[str, Any]] = []
    errors: list[str] = []
    directions: list[str] = []

    for patch_index, patch in enumerate(patch_items):
        path = patch.get("path")
        raw_search = patch.get("search")
        raw_replace = patch.get("replace")
        if not isinstance(path, str) or not isinstance(raw_search, str) or not isinstance(raw_replace, str):
            errors.append(f"patch {patch_index}: invalid patch item types")
            continue
        if path not in fixed:
            errors.append(f"patch {patch_index}: path not in input files: {path}")
            continue

        bug_snippet, transform, offset = find_unique(fixed[path], raw_search)
        direction = "repair"
        if bug_snippet is not None and transform is not None and offset is not None:
            fixed_snippet = transform_text(raw_replace, transform)
            before = fixed[path]
            fixed[path] = before[:offset] + fixed_snippet + before[offset + len(bug_snippet) :]
        else:
            fixed_match_error = transform
            fixed_snippet, transform, offset = find_unique(buggy[path], raw_replace)
            direction = "inject_bug"
            if fixed_snippet is None or transform is None or offset is None:
                errors.append(
                    f"patch {patch_index}: neither buggy search nor clean replace found uniquely in {path}"
                )
                normalized_patches.append(
                    {
                        "path": path,
                        "search": raw_search,
                        "replace": raw_replace,
                        "status": "failed",
                        "match_strategy": f"search={fixed_match_error};replace={transform}",
                    }
                )
                continue
            bug_snippet = transform_text(raw_search, transform)
            before = buggy[path]
            buggy[path] = before[:offset] + bug_snippet + before[offset + len(fixed_snippet) :]

        normalized_patches.append(
            {
                "path": path,
                "search": bug_snippet,
                "replace": fixed_snippet,
                "status": "applied",
                "match_strategy": transform,
                "direction": direction,
                "location": line_col(fixed[path] if direction == "repair" else buggy[path], offset),
            }
        )
        directions.append(direction)

    if errors:
        return None, None, normalized_patches, errors, None

    for patch_index, patch in enumerate(normalized_patches):
        path = patch["path"]
        if patch["search"] not in buggy[path]:
            errors.append(f"patch {patch_index}: normalized search not present in buggy input: {path}")
        if patch["replace"] not in fixed[path]:
            errors.append(f"patch {patch_index}: normalized replace not present in fixed output: {path}")
    if errors:
        return None, None, normalized_patches, errors, None

    mode = (
        "injected_bug_from_clean_input"
        if set(directions) == {"inject_bug"}
        else "repaired_existing_buggy_input"
        if set(directions) == {"repair"}
        else "mixed_bug_state_normalized"
    )
    buggy_files = [{"path": path, "code": code} for path, code in buggy.items()]
    fixed_files = [{"path": path, "code": code} for path, code in fixed.items()]
    return buggy_files, fixed_files, normalized_patches, [], mode


def manifest_from_files(files: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {"path": item["path"], "type": "code", "size_bytes": len(item["code"].encode("utf-8"))}
        for item in files
    ]


def normalize_generation(row: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    output_files = [
        {"path": item["path"], "code": item["code"]}
        for item in row.get("response", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str) and isinstance(item.get("code"), str)
    ]
    if len(output_files) != len(row.get("response", [])):
        return None, reject(row, ["invalid generation response item"])
    return (
        base_record(row)
        | {
            "instruction": row.get("instruction", ""),
            "input_files": [],
            "output_files": output_files,
            "patches": [],
            "output_manifest": manifest_from_files(output_files),
            "conversion_status": "success",
        },
        None,
    )


def normalize_editing(row: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    instruction = row.get("instruction", {})
    src_code = instruction.get("src_code", []) if isinstance(instruction, dict) else []
    input_files = [
        {"path": item["path"], "code": item["code"]}
        for item in src_code
        if isinstance(item, dict) and isinstance(item.get("path"), str) and isinstance(item.get("code"), str)
    ]
    description = instruction.get("description", "") if isinstance(instruction, dict) else ""
    if not isinstance(description, str):
        description = json.dumps(description, ensure_ascii=False)
    output_files, patches, errors = apply_patch_items(input_files, row.get("response", []))
    if output_files is None:
        return None, reject(row, errors, patches)
    return (
        base_record(row)
        | {
            "instruction": description,
            "input_files": input_files,
            "output_files": output_files,
            "patches": patches,
            "output_manifest": manifest_from_files(output_files),
            "conversion_status": "success",
        },
        None,
    )


def normalize_repair(row: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    src_code = row.get("instruction", [])
    input_files = [
        {"path": item["path"], "code": item["code"]}
        for item in src_code
        if isinstance(item, dict) and isinstance(item.get("path"), str) and isinstance(item.get("code"), str)
    ]
    buggy_files, fixed_files, patches, errors, conversion_mode = apply_repair_patch_items(
        input_files, row.get("response", [])
    )
    if buggy_files is None or fixed_files is None or conversion_mode is None:
        return None, reject(row, errors, patches)
    return (
        base_record(row)
        | {
            "instruction": "Repair the provided web project according to the defect type.",
            "input_files": buggy_files,
            "output_files": fixed_files,
            "patches": patches,
            "output_manifest": manifest_from_files(fixed_files),
            "conversion_status": "success",
            "conversion_mode": conversion_mode,
        },
        None,
    )


def base_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "webcoding-unified-v0.1",
        "instance_id": row.get("instance_id"),
        "task": row.get("task"),
        "task_type": row.get("task_type", []),
        "page_type": row.get("page_type"),
        "resources": row.get("resources", []),
        "source_schema": "oss-webcoding260622",
        "source_file_manifest": row.get("file_manifest", []),
    }


def reject(
    row: dict[str, Any], errors: list[str], patches: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return base_record(row) | {
        "conversion_status": "failed",
        "conversion_errors": errors,
        "patches": patches or [],
    }


NORMALIZERS = {
    "text-generation": normalize_generation,
    "text-editing": normalize_editing,
    "text-repair": normalize_repair,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--tasks", nargs="+", choices=sorted(NORMALIZERS), default=sorted(NORMALIZERS))
    args = parser.parse_args()

    src_dir = Path(args.src_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    limit = None if args.limit <= 0 else args.limit
    summary: dict[str, Any] = {"limit": args.limit, "tasks": {}}
    for task, filename in SOURCE_FILES.items():
        if task not in args.tasks:
            continue
        stem = Path(filename).stem
        success_path = out_dir / f"{stem}.unified.success.jsonl"
        failed_path = out_dir / f"{stem}.unified.failed.jsonl"
        if success_path.exists() or failed_path.exists():
            raise FileExistsError(f"refusing to overwrite existing output for {task}: {out_dir}")
        read_count = 0
        success_count = 0
        failed_count = 0
        for row in read_jsonl(src_dir / filename, limit):
            read_count += 1
            ok, bad = NORMALIZERS[task](deepcopy(row))
            if ok is not None:
                append_jsonl(success_path, ok)
                success_count += 1
            if bad is not None:
                append_jsonl(failed_path, bad)
                failed_count += 1

        summary["tasks"][task] = {
            "source_file": filename,
            "read_records": read_count,
            "success_records": success_count,
            "failed_records": failed_count,
        }

    (out_dir / "_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
