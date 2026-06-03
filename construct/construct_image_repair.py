#!/usr/bin/env python3
"""image-repair: text-repair + screenshots.

Reads text-repair output, applies defect patches to produce broken code,
screenshots both clean (dst) and broken (src) states.
"""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from WebCoding_Data.construct.construct_common import (
    append_jsonl,
    apply_search_replace_local,
    read_code_bundle,
    safe_write_json,
    screenshot_project_to_dir,
    write_code_bundle_from_source,
)


def iter_pair_instances(root: Path, limit: int = 0) -> list[tuple[str, Path]]:
    pairs = []
    for bucket in ("sp", "mp"):
        bucket_dir = root / bucket
        if not bucket_dir.exists():
            continue
        for instance_dir in sorted(p for p in bucket_dir.iterdir() if p.is_dir()):
            pairs.append((bucket, instance_dir))
    return pairs[:limit] if limit > 0 else pairs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True, help="text-repair dataset root")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = args.output_dir / "manifest_image_repair.jsonl"

    for bucket, src_instance_dir in iter_pair_instances(args.input_dir, args.limit):
        dst_instance_dir = args.output_dir / bucket / src_instance_dir.name
        if dst_instance_dir.exists():
            if not args.overwrite:
                append_jsonl(manifest, {"instance_id": src_instance_dir.name, "bucket": bucket, "status": "skip_existing"})
                continue
            shutil.rmtree(dst_instance_dir)
        try:
            # Copy text-repair instance
            shutil.copytree(src_instance_dir, dst_instance_dir)
            info = json.loads((dst_instance_dir / "info.json").read_text(encoding="utf-8"))

            source_project = Path(info["meta"]["source_project"])
            if not source_project.exists():
                raise FileNotFoundError(f"source project not found: {source_project}")

            # dst_screenshot: clean state (original project)
            dst_screens = screenshot_project_to_dir(source_project, dst_instance_dir / "dst_screenshots")

            # src_screenshot: defective state (apply patches to inject defects)
            # label_modified_files is in fix direction (search=defective, replace=clean)
            # To get defective code: reverse the patches (search=clean, replace=defective)
            defect_patches = [
                {"path": p["path"], "search": p["replace"], "replace": p["search"]}
                for p in info.get("label_modified_files", [])
            ]
            clean_code = read_code_bundle(source_project)
            defective_code, apply_errors = apply_search_replace_local(clean_code, defect_patches, strict_mode=False)

            with tempfile.TemporaryDirectory() as tmp:
                tmp_dir = Path(tmp) / "defective"
                write_code_bundle_from_source(source_project, defective_code, tmp_dir)
                src_screens = screenshot_project_to_dir(tmp_dir, dst_instance_dir / "src_screenshots")

            info["src_screenshot"] = src_screens
            info["dst_screenshot"] = dst_screens
            if apply_errors:
                info["meta"]["screenshot_apply_errors"] = apply_errors
            safe_write_json(dst_instance_dir / "info.json", info)
            append_jsonl(manifest, {"instance_id": src_instance_dir.name, "bucket": bucket, "status": "ok"})
        except Exception as exc:  # noqa: BLE001
            shutil.rmtree(dst_instance_dir, ignore_errors=True)
            append_jsonl(manifest, {"instance_id": src_instance_dir.name, "bucket": bucket, "status": "error", "error": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    main()
