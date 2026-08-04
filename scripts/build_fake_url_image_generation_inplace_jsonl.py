#!/usr/bin/env python3
"""Create an in-place image-generation JSONL for fake_url/image-generate.

The source directory already stores screenshots beside each index.html, so this
script does not copy images. It writes JSONL records that reference the existing
relative screenshot path and embed the target HTML code.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from build_oss_image_editing_dataset import safe_instance_name
from build_oss_image_editing_pilot import normalize_files_for_render


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def iter_project_dirs(input_dir: Path, limit: int):
    yielded = 0
    for index, project_dir in enumerate(sorted(p for p in input_dir.iterdir() if p.is_dir()), start=1):
        if limit > 0 and yielded >= limit:
            break
        yielded += 1
        yield index, project_dir


def find_screenshot(project_dir: Path) -> Path:
    preferred = project_dir / "screenshot.png"
    if preferred.exists():
        return preferred
    matches = [
        p
        for p in project_dir.iterdir()
        if p.is_file() and p.stem.startswith("screenshot") and p.suffix.lower() in IMAGE_SUFFIXES
    ]
    if not matches:
        raise FileNotFoundError(f"missing screenshot image in {project_dir}")
    return sorted(matches)[0]


def read_output_files(project_dir: Path) -> list[dict[str, str]]:
    html = project_dir / "index.html"
    if not html.exists():
        raise FileNotFoundError(f"missing index.html in {project_dir}")
    return normalize_files_for_render([{"path": "index.html", "code": html.read_text(encoding="utf-8", errors="ignore")}])


def build_file_manifest(files: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "path": item["path"],
            "type": "code",
            "size_bytes": len(item["code"].encode("utf-8")),
        }
        for item in files
    ]


def build_record(input_dir: Path, project_dir: Path) -> dict[str, Any]:
    instance_id = safe_instance_name(project_dir.name)
    output_files = read_output_files(project_dir)
    screenshot = find_screenshot(project_dir)
    image_rel = screenshot.relative_to(input_dir).as_posix()
    instruction = "Generate the complete HTML code for the webpage shown in the provided screenshot."
    return {
        "schema_version": "webcoding-image-generation-fake-url-v1",
        "instance_id": instance_id,
        "task": "image-generation",
        "task_type": [],
        "page_type": "sp",
        "file_manifest": build_file_manifest(output_files),
        "resources": [],
        "instruction": instruction,
        "input_files": [],
        "input_images": [image_rel],
        "src_screenshot": [image_rel],
        "dst_screenshot": [],
        "output_files": output_files,
        "patches": [],
        "response": output_files,
        "conversion_status": "success",
        "metadata": {
            "base_task": "image-generation",
            "source_format": "fake_url_image_generate_project_inplace",
            "source_project": project_dir.relative_to(input_dir).as_posix(),
            "screenshot_state": "target_page",
            "screenshot_viewport": "source_capture_existing",
            "target_format": "single_html",
            "image_paths_relative_to": str(input_dir),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, default=None)
    parser.add_argument("--failed-jsonl", type=Path, default=None)
    parser.add_argument("--manifest-jsonl", type=Path, default=None)
    parser.add_argument("--summary-json", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    output_jsonl = args.output_jsonl or (args.input_dir / "image-generation.unified.success.jsonl")
    failed_jsonl = args.failed_jsonl or (args.input_dir / "image-generation.unified.failed.jsonl")
    manifest_jsonl = args.manifest_jsonl or (args.input_dir / "manifest_image_generation.jsonl")
    summary_json = args.summary_json or (args.input_dir / "_image_generation_jsonl_summary.json")
    targets = [output_jsonl, failed_jsonl, manifest_jsonl, summary_json]
    if args.overwrite:
        for path in targets:
            if path.exists():
                path.unlink()
    else:
        existing = [str(path) for path in targets if path.exists()]
        if existing:
            raise FileExistsError(f"output files exist; pass --overwrite: {existing}")

    ok = failed = 0
    for index, project_dir in iter_project_dirs(args.input_dir, args.limit):
        try:
            record = build_record(args.input_dir, project_dir)
            append_jsonl(output_jsonl, record)
            append_jsonl(
                manifest_jsonl,
                {
                    "index": index,
                    "instance_id": record["instance_id"],
                    "status": "ok",
                    "input_image": record["input_images"][0],
                    "output_file_count": len(record["output_files"]),
                },
            )
            ok += 1
        except Exception as exc:  # noqa: BLE001
            row = {
                "schema_version": "webcoding-image-generation-fake-url-v1",
                "instance_id": project_dir.name,
                "task": "image-generation",
                "conversion_status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
            append_jsonl(failed_jsonl, row)
            append_jsonl(manifest_jsonl, {"index": index, "instance_id": project_dir.name, "status": "error", "error": row["error"]})
            failed += 1

    summary = {
        "input_dir": str(args.input_dir),
        "output_jsonl": str(output_jsonl),
        "failed_jsonl": str(failed_jsonl),
        "manifest_jsonl": str(manifest_jsonl),
        "limit": args.limit,
        "ok": ok,
        "failed": failed,
        "images_copied": False,
        "image_paths": "relative_to_input_dir",
    }
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
