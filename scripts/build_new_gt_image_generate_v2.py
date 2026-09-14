#!/usr/bin/env python3
"""Append exact image-generate v2 records from the canonical mother cache."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from reverse.construct_common import (
    build_file_manifest, collect_resources, load_canonical_screenshots,
    read_code_bundle,
)


def rows(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def completed(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    return {
        str(row.get("instance_id")) for row in rows(path)
        if row.get("conversion_status") == "success"
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mother-pool", type=Path, required=True)
    parser.add_argument("--canonical-screenshot-dir", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--expected", type=int, default=5000)
    parser.add_argument(
        "--limit", type=int,
        help="Use only the first N mothers for a bounded real-data probe.",
    )
    args = parser.parse_args()
    mothers = list(rows(args.mother_pool))
    if args.limit is not None:
        if args.limit <= 0:
            raise ValueError("--limit must be positive")
        mothers = mothers[:args.limit]
    if len(mothers) != args.expected:
        raise ValueError(f"expected {args.expected} image-generate mothers, found {len(mothers)}")
    args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    done = completed(args.output_jsonl)
    with args.output_jsonl.open("a", encoding="utf-8") as output:
        for index, mother in enumerate(mothers, 1):
            project = Path(mother["project_path"])
            instance_id = str(mother["project_id"])
            if instance_id in done:
                continue
            screenshots = load_canonical_screenshots(
                args.canonical_screenshot_dir, instance_id
            )
            images = [item["path"] for item in screenshots]
            code = read_code_bundle(project, code_only=True)
            record = {
                "schema_version": "webcoding-image-generation-v2",
                "instance_id": instance_id,
                "task_type": [],
                "page_type": mother["page_scope"],
                "file_manifest": build_file_manifest(project),
                "resources": collect_resources(project),
                "task": "image-generation",
                "instruction": "",
                "input_files": [],
                "input_images": images,
                "src_screenshot": images,
                "dst_screenshot": [],
                "output_files": code,
                "patches": [],
                "response": code,
                "conversion_status": "success",
                "metadata": {
                    "release_schema_reference": "webcoding-sft-v2",
                    "base_task": "text-generation",
                    "source_instance_id": mother["instance_id"],
                    "source_project": str(project),
                    "source_benchmark": mother["source_benchmark"],
                    "page_scope": mother["page_scope"],
                    "project_pages": mother["project_pages"],
                    "canonical_clean_image_shared": True,
                    "screenshot_state": "target",
                    "screenshot_viewport": "desktop_1920_full_page",
                },
            }
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
            output.flush()
            done.add(instance_id)
            if index % 100 == 0:
                print(f"built {len(done)}/{args.expected}", flush=True)
    if len(done) != args.expected:
        raise RuntimeError(f"image-generate incomplete: {len(done)}/{args.expected}")
    print(json.dumps({"status": "ok", "image_generate": len(done)}), flush=True)


if __name__ == "__main__":
    main()
