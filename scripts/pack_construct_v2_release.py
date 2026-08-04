#!/usr/bin/env python3
"""Assemble six constructor outputs into one self-contained release-v2 tree."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--production-root", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    args = parser.parse_args()
    jsonl_dir = args.release_root / "jsonl"
    jsonl_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_reference": "webcoding-sft-v2", "tasks": {}}

    for task, (relative_source, output_name) in SOURCE_NAMES.items():
        source = args.production_root / relative_source
        output = jsonl_dir / output_name
        count = 0
        with source.open("r", encoding="utf-8") as input_handle, output.open("w", encoding="utf-8") as output_handle:
            for line in input_handle:
                record = json.loads(line)
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
