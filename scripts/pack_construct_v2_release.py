#!/usr/bin/env python3
"""Assemble six constructor outputs into one self-contained release-v2 tree."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from collections import defaultdict
from pathlib import Path


SOURCE_NAMES = {
    "text-generate": ("generate/text-generate.v2.jsonl", "text-generate.jsonl"),
    "image-generate": ("generate/image-generate.v2.jsonl", "image-generate.jsonl"),
    "text-edit": ("edit/text-edit.v2.jsonl", "text-edit.jsonl"),
    "image-edit": ("edit/image-edit.v2.jsonl", "image-edit.jsonl"),
    "text-repair": ("repair/text-repair.v2.jsonl", "text-repair.jsonl"),
    "image-repair": ("repair/image-repair.v2.jsonl", "image-repair.jsonl"),
}
IMAGE_KEYS = ("input_images", "src_screenshot", "dst_screenshot")


def link_or_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_source_records(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def rewrite_images(record: dict, task: str, release_root: Path) -> dict:
    mapping: dict[str, str] = {}
    instance_id = str(record["instance_id"])
    all_paths = []
    for key in IMAGE_KEYS:
        all_paths.extend(str(value) for value in record.get(key, []))
    for index, raw in enumerate(dict.fromkeys(all_paths)):
        source = Path(raw)
        if not source.is_file():
            raise FileNotFoundError(source)
        state = "image"
        if raw in record.get("src_screenshot", []):
            state = "source"
        if raw in record.get("dst_screenshot", []):
            state = "destination"
        relative = Path("images") / task / instance_id / f"{state}_{index}{source.suffix.lower()}"
        link_or_copy(source, release_root / relative)
        mapping[raw] = relative.as_posix()
    for key in IMAGE_KEYS:
        record[key] = [mapping[str(value)] for value in record.get(key, [])]
    record.setdefault("metadata", {})["image_paths_relative_to"] = "release_root"
    return record


def select_balanced_text_repairs(records: list[dict], required_ids: set[str]) -> list[dict]:
    """Balance 1--7 task counts while retaining every paired image repair.

    Visual gating is correlated with the number of injected defect types, so
    the full construction stream is intentionally allowed to oversample task
    counts whose screenshots pass less often.  The release view removes that
    sampling bias without breaking the text/image pairing contract.
    """
    by_count: dict[int, list[dict]] = defaultdict(list)
    by_id: dict[str, dict] = {}
    for record in records:
        instance_id = str(record["instance_id"])
        if instance_id in by_id:
            raise ValueError(f"duplicate text-repair instance_id: {instance_id}")
        by_id[instance_id] = record
        by_count[int(record.get("metadata", {}).get("task_count", 0))].append(record)
    missing = required_ids - set(by_id)
    if missing:
        raise ValueError(f"image-repair pairs missing from text-repair: {sorted(missing)[:5]}")
    if set(by_count) != set(range(1, 8)):
        raise ValueError(f"text-repair task counts must cover 1--7, got {sorted(by_count)}")

    per_count = min(len(values) for values in by_count.values())
    selected_ids: set[str] = set()
    for count in range(1, 8):
        required = [record for record in by_count[count]
                    if str(record["instance_id"]) in required_ids]
        if len(required) > per_count:
            raise ValueError(
                f"cannot balance text-repair count={count}: {len(required)} paired records > {per_count}"
            )
        selected = required + [
            record for record in by_count[count]
            if str(record["instance_id"]) not in required_ids
        ][:per_count - len(required)]
        selected_ids.update(str(record["instance_id"]) for record in selected)
    return [record for record in records if str(record["instance_id"]) in selected_ids]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--production-root", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    args = parser.parse_args()
    jsonl_dir = args.release_root / "jsonl"
    jsonl_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_reference": "webcoding-sft-v2", "tasks": {}}
    image_repair_source = args.production_root / SOURCE_NAMES["image-repair"][0]
    paired_repair_ids = {
        str(record["instance_id"])
        for record in iter_source_records(image_repair_source)
    }

    for task, (relative_source, output_name) in SOURCE_NAMES.items():
        source = args.production_root / relative_source
        output = jsonl_dir / output_name
        count = 0
        if task == "text-repair":
            records = list(iter_source_records(source))
            records = select_balanced_text_repairs(records, paired_repair_ids)
        else:
            records = iter_source_records(source)
        with output.open("w", encoding="utf-8") as output_handle:
            for record in records:
                if task in {"text-repair", "image-repair"}:
                    record.setdefault("metadata", {}).setdefault("visual_difference", {})[
                        "minimum_changed_ratio"
                    ] = 0.01
                if task.startswith("image-"):
                    record = rewrite_images(record, task, args.release_root)
                output_handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1
        manifest["tasks"][task] = {
            "jsonl": f"jsonl/{output_name}",
            "count": count,
            "sha256": checksum(output),
            "image_root": f"images/{task}" if task.startswith("image-") else None,
        }
        print(f"{task}: {count}", flush=True)
    manifest_path = args.release_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(manifest_path)


if __name__ == "__main__":
    main()
