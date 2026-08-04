#!/usr/bin/env python3
"""Build image-generation JSONL from fake_url/image-generate projects.

Each source project is a local single-page capture with an existing screenshot.
The emitted schema mirrors the image-editing/image-repair JSONL layout:
input_images contains the page screenshot and response/output_files contains the
target HTML code.
"""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import json
import shutil
from pathlib import Path
from typing import Any

from build_oss_image_editing_dataset import append_jsonl, safe_instance_name
from build_oss_image_editing_pilot import normalize_files_for_render


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def iter_project_dirs(input_dir: Path, offset: int, limit: int):
    yielded = 0
    for index, project_dir in enumerate(sorted(p for p in input_dir.iterdir() if p.is_dir()), start=1):
        if index <= offset:
            continue
        if limit > 0 and yielded >= limit:
            break
        yielded += 1
        yield index, project_dir


def read_index_file(project_dir: Path) -> list[dict[str, str]]:
    html = project_dir / "index.html"
    if not html.exists():
        raise FileNotFoundError(f"missing index.html in {project_dir}")
    return [{"path": "index.html", "code": html.read_text(encoding="utf-8", errors="ignore")}]


def find_screenshot(project_dir: Path) -> Path:
    preferred = project_dir / "screenshot.png"
    if preferred.exists():
        return preferred
    matches = [p for p in project_dir.iterdir() if p.is_file() and p.stem.startswith("screenshot") and p.suffix.lower() in IMAGE_SUFFIXES]
    if not matches:
        raise FileNotFoundError(f"missing screenshot image in {project_dir}")
    return sorted(matches)[0]


def build_file_manifest(files: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "path": item["path"],
            "type": "code",
            "size_bytes": len(item["code"].encode("utf-8")),
        }
        for item in files
    ]


def build_record(instance_id: str, output_files: list[dict[str, str]], image_rel: str, source_project: Path) -> dict[str, Any]:
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
            "source_format": "fake_url_image_generate_project",
            "source_project": str(source_project),
            "screenshot_state": "target_page",
            "screenshot_viewport": "source_capture_existing",
            "target_format": "single_html",
        },
    }


def process_one(index: int, project_dir: str, out_dir: str) -> dict[str, Any]:
    try:
        project = Path(project_dir)
        root = Path(out_dir)
        instance_id = safe_instance_name(project.name)
        output_files = normalize_files_for_render(read_index_file(project))
        screenshot = find_screenshot(project)

        image_ext = ".jpg" if screenshot.suffix.lower() in {".jpg", ".jpeg"} else screenshot.suffix.lower()
        image_rel = str((Path("images") / instance_id / "input_screenshots" / f"screenshot_index{image_ext}").as_posix())
        image_dest = root / image_rel
        image_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(screenshot, image_dest)

        record = build_record(instance_id, output_files, image_rel, project)
        return {
            "index": index,
            "instance_id": instance_id,
            "status": "ok",
            "record": record,
            "manifest": {
                "index": index,
                "instance_id": instance_id,
                "status": "ok",
                "input_image": image_rel,
                "output_file_count": len(output_files),
                "source_project": str(project),
            },
        }
    except Exception as exc:  # noqa: BLE001
        instance_id = Path(project_dir).name
        failed = {
            "schema_version": "webcoding-image-generation-fake-url-v1",
            "instance_id": instance_id,
            "task": "image-generation",
            "conversion_status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }
        return {
            "index": index,
            "instance_id": instance_id,
            "status": "error",
            "failed_record": failed,
            "manifest": {
                "index": index,
                "instance_id": instance_id,
                "status": "error",
                "error": failed["error"],
            },
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    success_path = args.out_dir / "image-generation.unified.success.jsonl"
    failed_path = args.out_dir / "image-generation.unified.failed.jsonl"
    manifest_path = args.out_dir / "manifest_image_generation.jsonl"
    if args.out_dir.exists() and not args.resume and any(args.out_dir.iterdir()):
        raise FileExistsError(f"output dir is not empty; use a new dir or --resume: {args.out_dir}")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    done: set[str] = set()
    if args.resume and success_path.exists():
        with success_path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        done.add(json.loads(line)["instance_id"])
                    except Exception:
                        pass

    ok = failed = skipped = 0
    workers = max(1, args.workers)
    max_pending = workers * 4
    pending = set()

    def consume(done_futures) -> None:  # type: ignore[no-untyped-def]
        nonlocal ok, failed
        for future in done_futures:
            result = future.result()
            if result["status"] == "ok":
                append_jsonl(success_path, result["record"])
                ok += 1
            else:
                append_jsonl(failed_path, result["failed_record"])
                failed += 1
            append_jsonl(manifest_path, result["manifest"])

    with ProcessPoolExecutor(max_workers=workers) as executor:
        for index, project_dir in iter_project_dirs(args.input_dir, args.offset, args.limit):
            instance_id = safe_instance_name(project_dir.name)
            if instance_id in done:
                skipped += 1
                append_jsonl(manifest_path, {"index": index, "instance_id": instance_id, "status": "skip_existing"})
                continue
            pending.add(executor.submit(process_one, index, str(project_dir), str(args.out_dir)))
            if len(pending) >= max_pending:
                done_futures, pending = wait(pending, return_when=FIRST_COMPLETED)
                consume(done_futures)
        while pending:
            done_futures, pending = wait(pending, return_when=FIRST_COMPLETED)
            consume(done_futures)

    summary = {
        "input_dir": str(args.input_dir),
        "out_dir": str(args.out_dir),
        "offset": args.offset,
        "limit": args.limit,
        "workers": workers,
        "ok": ok,
        "failed": failed,
        "skipped": skipped,
    }
    (args.out_dir / "_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
