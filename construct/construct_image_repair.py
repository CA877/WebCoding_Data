#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from WebCoding_Data.construct.construct_common import (
    append_jsonl,
    safe_write_json,
    screenshot_project_to_dir,
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
            shutil.copytree(src_instance_dir, dst_instance_dir)
            info = json.loads((dst_instance_dir / "info.json").read_text(encoding="utf-8"))
            src_screens = screenshot_project_to_dir(dst_instance_dir / "src", dst_instance_dir / "src_screenshots")
            dst_screens = screenshot_project_to_dir(dst_instance_dir / "dst", dst_instance_dir / "dst_screenshots")
            info["task"] = "repair"
            info.pop("instruction", None)
            info["src_screenshot"] = src_screens
            info["dst_screenshot"] = dst_screens
            safe_write_json(dst_instance_dir / "info.json", info)
            append_jsonl(manifest, {"instance_id": src_instance_dir.name, "bucket": bucket, "status": "ok"})
        except Exception as exc:  # noqa: BLE001
            shutil.rmtree(dst_instance_dir, ignore_errors=True)
            append_jsonl(manifest, {"instance_id": src_instance_dir.name, "bucket": bucket, "status": "error", "error": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    main()
