#!/usr/bin/env python3
"""Count sample-level patch search matching status for JSONL files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def count_file(path: Path) -> dict:
    total = 0
    any_not_found = 0
    any_ambiguous = 0
    any_path_missing = 0
    all_unique = 0
    no_patches = 0
    examples = {"not_found": [], "ambiguous": [], "path_missing": []}

    with path.open("rb") as f:
        for line in f:
            if not line.strip():
                continue
            total += 1
            record = json.loads(line)
            instance_id = record.get("instance_id", str(total))
            files = {
                item.get("path"): item.get("code", "")
                for item in (record.get("input_files") or [])
                if isinstance(item, dict)
            }
            patches = record.get("patches") or record.get("response") or []
            if not patches:
                no_patches += 1
                continue

            not_found = ambiguous = path_missing = False
            for patch in patches:
                if not isinstance(patch, dict):
                    continue
                patch_path = patch.get("path")
                search = patch.get("search")
                if not isinstance(patch_path, str) or not isinstance(search, str):
                    continue
                if patch_path not in files:
                    path_missing = True
                    continue
                count = files[patch_path].count(search)
                if count == 0:
                    not_found = True
                elif count > 1:
                    ambiguous = True

            if not_found:
                any_not_found += 1
                if len(examples["not_found"]) < 20:
                    examples["not_found"].append(instance_id)
            if ambiguous:
                any_ambiguous += 1
                if len(examples["ambiguous"]) < 20:
                    examples["ambiguous"].append(instance_id)
            if path_missing:
                any_path_missing += 1
                if len(examples["path_missing"]) < 20:
                    examples["path_missing"].append(instance_id)
            if not (not_found or ambiguous or path_missing):
                all_unique += 1

    return {
        "file": str(path),
        "name": path.name,
        "total": total,
        "all_patch_search_unique": all_unique,
        "all_patch_search_unique_ratio": all_unique / total if total else 0.0,
        "any_search_not_found": any_not_found,
        "any_search_not_found_ratio": any_not_found / total if total else 0.0,
        "any_search_ambiguous": any_ambiguous,
        "any_search_ambiguous_ratio": any_ambiguous / total if total else 0.0,
        "any_path_missing": any_path_missing,
        "any_path_missing_ratio": any_path_missing / total if total else 0.0,
        "no_patches": no_patches,
        "examples": examples,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    files = []
    for path in args.paths:
        if path.is_dir():
            files.extend(sorted(path.glob("*.jsonl")))
        else:
            files.append(path)

    rows = [count_file(path) for path in files]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "patch_sample_counts.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Patch Sample Counts",
        "",
        "| file | total | all unique | any search not found | any ambiguous | any path missing |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| `{row['name']}` | {row['total']} | "
            f"{row['all_patch_search_unique']} ({row['all_patch_search_unique_ratio']:.2%}) | "
            f"{row['any_search_not_found']} ({row['any_search_not_found_ratio']:.2%}) | "
            f"{row['any_search_ambiguous']} ({row['any_search_ambiguous_ratio']:.2%}) | "
            f"{row['any_path_missing']} ({row['any_path_missing_ratio']:.2%}) |"
        )
    (args.out_dir / "patch_sample_counts.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"out_dir": str(args.out_dir), "files": len(files)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
