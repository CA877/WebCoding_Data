#!/usr/bin/env python3
"""Organize the WebCoding six-task SFT release directory.

This script documents the move-based release layout used for
`/data1/xieqianqian/webcoding/release_sft_6tasks_v1`.
It is intentionally non-destructive to existing release directories: if the
target already exists, it refuses to overwrite it.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path


def line_count(path: Path) -> int:
    with path.open(encoding="utf-8", errors="ignore") as f:
        return sum(1 for _ in f)


def main() -> None:
    release = Path("/data1/xieqianqian/webcoding/release_sft_6tasks_v1")
    jsonl_dir = release / "jsonl"
    images_dir = release / "images"
    if release.exists():
        raise SystemExit(f"release exists, refusing to overwrite: {release}")
    jsonl_dir.mkdir(parents=True)
    images_dir.mkdir(parents=True)

    src = {
        "text-generate": Path("/data1/xieqianqian/webcoding/datasets/oss/data-disclosure/opencoder/xwh/webcoding260622/text-generation.jsonl"),
        "text-edit": Path("/data1/xieqianqian/webcoding/datasets/oss/data-disclosure/opencoder/xwh/webcoding260622/text-editing.jsonl"),
        "text-repair": Path("/data1/xieqianqian/webcoding/datasets/oss/data-disclosure/opencoder/xwh/webcoding260622/text-repair.jsonl"),
        "image-generate": Path("/data1/xieqianqian/webcoding/output_full/fake_url/image-generate/image-generation.unified.success.jsonl"),
        "image-edit": Path("/data1/xieqianqian/webcoding/datasets/oss/data-disclosure/opencoder/xwh/webcoding260622_processed/image_editing_raw_v1_full/image-editing.unified.success.final.jsonl"),
        "image-repair-base": Path("/data1/xieqianqian/webcoding/datasets/oss/data-disclosure/opencoder/xwh/webcoding260622_processed/image_repair_raw_v1_full/image-repair.unified.success.jsonl"),
        "image-repair-retry": Path("/data1/xieqianqian/webcoding/datasets/oss/data-disclosure/opencoder/xwh/webcoding260622_processed/image_repair_remaining_no_record_749_hardtimeout/image-repair.unified.success.jsonl"),
    }
    for name, path in src.items():
        if not path.exists():
            raise SystemExit(f"missing source {name}: {path}")

    for task in ["text-generate", "text-edit", "text-repair", "image-generate", "image-edit"]:
        shutil.move(str(src[task]), str(jsonl_dir / f"{task}.jsonl"))

    image_generate_src = Path("/data1/xieqianqian/webcoding/output_full/fake_url/image-generate")
    image_generate_dst = images_dir / "image-generate"
    image_generate_dst.mkdir()
    for project_dir in sorted(p for p in image_generate_src.iterdir() if p.is_dir()):
        shot = project_dir / "screenshot.png"
        if not shot.exists():
            continue
        target_dir = image_generate_dst / project_dir.name
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(shot), str(target_dir / "screenshot.png"))

    image_edit_src = Path("/data1/xieqianqian/webcoding/datasets/oss/data-disclosure/opencoder/xwh/webcoding260622_processed/image_editing_raw_v1_full/images")
    image_edit_root = images_dir / "image-edit"
    image_edit_root.mkdir()
    shutil.move(str(image_edit_src), str(image_edit_root / "images"))

    image_repair_root = images_dir / "image-repair"
    image_repair_root.mkdir()
    image_repair_base_images = Path("/data1/xieqianqian/webcoding/datasets/oss/data-disclosure/opencoder/xwh/webcoding260622_processed/image_repair_raw_v1_full/images")
    shutil.move(str(image_repair_base_images), str(image_repair_root / "images"))

    retry_single_runs = Path("/data1/xieqianqian/webcoding/datasets/oss/data-disclosure/opencoder/xwh/webcoding260622_processed/image_repair_remaining_no_record_749_hardtimeout/_single_runs")
    for images_subdir in retry_single_runs.glob("*/out/images/*"):
        if images_subdir.is_dir():
            dest = image_repair_root / "images" / images_subdir.name
            if dest.exists():
                for file_path in images_subdir.rglob("*"):
                    if file_path.is_file():
                        rel = file_path.relative_to(images_subdir)
                        target = dest / rel
                        target.parent.mkdir(parents=True, exist_ok=True)
                        if not target.exists():
                            shutil.move(str(file_path), str(target))
                shutil.rmtree(images_subdir, ignore_errors=True)
            else:
                shutil.move(str(images_subdir), str(dest))

    image_repair_jsonl = jsonl_dir / "image-repair.jsonl"
    shutil.move(str(src["image-repair-base"]), str(image_repair_jsonl))
    seen = set()
    with image_repair_jsonl.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.strip():
                seen.add(json.loads(line)["instance_id"])
    retry_seen = set()
    with src["image-repair-retry"].open(encoding="utf-8", errors="ignore") as f, image_repair_jsonl.open("a", encoding="utf-8") as out:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            instance_id = record["instance_id"]
            if instance_id in seen or instance_id in retry_seen:
                continue
            out.write(line if line.endswith("\n") else line + "\n")
            retry_seen.add(instance_id)

    tasks = {
        "text-generate": {"jsonl": "jsonl/text-generate.jsonl", "num_samples": line_count(jsonl_dir / "text-generate.jsonl"), "image_root": None},
        "text-edit": {"jsonl": "jsonl/text-edit.jsonl", "num_samples": line_count(jsonl_dir / "text-edit.jsonl"), "image_root": None},
        "text-repair": {"jsonl": "jsonl/text-repair.jsonl", "num_samples": line_count(jsonl_dir / "text-repair.jsonl"), "image_root": None},
        "image-generate": {"jsonl": "jsonl/image-generate.jsonl", "num_samples": line_count(jsonl_dir / "image-generate.jsonl"), "image_root": "images/image-generate"},
        "image-edit": {"jsonl": "jsonl/image-edit.jsonl", "num_samples": line_count(jsonl_dir / "image-edit.jsonl"), "image_root": "images/image-edit"},
        "image-repair": {"jsonl": "jsonl/image-repair.jsonl", "num_samples": line_count(jsonl_dir / "image-repair.jsonl"), "image_root": "images/image-repair"},
    }
    (release / "dataset_index.json").write_text(json.dumps({"name": release.name, "root": str(release), "tasks": tasks}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
