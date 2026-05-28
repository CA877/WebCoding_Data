#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from WebCoding_Data.construct.construct_common import (
    append_jsonl,
    base_info,
    collect_resources,
    copy_project,
    iter_project_dirs,
    read_code_bundle,
    safe_write_json,
    screenshot_project_to_dir,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = args.output_dir / "manifest_image_generation.jsonl"

    for project_dir in iter_project_dirs(args.input_dir, args.limit):
        instance_dir = args.output_dir / project_dir.name
        if instance_dir.exists():
            if not args.overwrite:
                append_jsonl(manifest, {"instance_id": project_dir.name, "status": "skip_existing"})
                continue
            shutil.rmtree(instance_dir)
        instance_dir.mkdir(parents=True, exist_ok=True)

        try:
            screenshots = screenshot_project_to_dir(project_dir, instance_dir / "input_screenshots")
            copy_project(project_dir, instance_dir / "dst")

            info = base_info(project_dir.name, "image-generation", "generation")
            info["dst_code"] = read_code_bundle(project_dir)
            info["resources"] = collect_resources(project_dir)
            info["input_screenshots"] = screenshots
            info["meta"] = {"source_project": str(project_dir)}
            safe_write_json(instance_dir / "info.json", info)
            append_jsonl(manifest, {"instance_id": project_dir.name, "status": "ok"})
        except Exception as exc:  # noqa: BLE001
            shutil.rmtree(instance_dir, ignore_errors=True)
            append_jsonl(manifest, {"instance_id": project_dir.name, "status": "error", "error": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    main()
