#!/usr/bin/env python3
"""Build image-editing from raw OSS text-editing.jsonl records.

This keeps all raw edit samples that have source code and patches. Image URL
replacement is persisted into input_files before screenshotting, so code and
screenshots stay aligned.
"""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import json
import signal
from pathlib import Path
from typing import Any

from build_oss_image_editing_dataset import (
    append_jsonl,
    already_done,
    prepare_output_dir,
    safe_instance_name,
    timeout_handler,
    update_totals,
)
from build_oss_image_editing_pilot import normalize_files_for_render, persist_image_replacements, screenshot_index, write_files


def iter_raw_edit_records(path: Path, offset: int, limit: int):
    count = 0
    with path.open(encoding="utf-8") as f:
        for zero_index, line in enumerate(f):
            if zero_index < offset:
                continue
            if limit > 0 and count >= limit:
                break
            if not line.strip():
                continue
            count += 1
            yield zero_index + 1, json.loads(line)


def raw_src_code(record: dict[str, Any]) -> list[dict[str, str]]:
    instruction = record.get("instruction")
    if isinstance(instruction, dict) and isinstance(instruction.get("src_code"), list):
        return instruction["src_code"]
    if isinstance(record.get("input_files"), list):
        return record["input_files"]
    return []


def raw_description(record: dict[str, Any]) -> Any:
    instruction = record.get("instruction")
    if isinstance(instruction, dict):
        return instruction.get("description", "")
    return record.get("instruction", "")


def build_record(record: dict[str, Any], input_files: list[dict[str, str]], image_rel: str, image_stats: dict[str, int]) -> dict[str, Any]:
    patches = normalize_patch_items(record.get("response", record.get("patches", [])))
    metadata = dict(record.get("metadata") or {})
    metadata.update(
        {
            "base_task": "text-editing",
            "source_format": "raw_oss_text_editing",
            "screenshot_state": "before_edit",
            "screenshot_viewport": {"width": 1920, "height": 1080, "full_page": True},
            "image_stats": image_stats,
            "image_url_rewrite": "persisted_to_input_files_loremflickr",
        }
    )
    return {
        "schema_version": "webcoding-image-editing-raw-v1",
        "instance_id": record["instance_id"],
        "task": "image-editing",
        "task_type": record.get("task_type", []),
        "page_type": record.get("page_type", "sp"),
        "file_manifest": record.get("file_manifest", []),
        "resources": record.get("resources", []),
        "instruction": raw_description(record),
        "input_files": input_files,
        "input_images": [image_rel],
        "src_screenshot": [image_rel],
        "dst_screenshot": [],
        "patches": patches,
        "response": patches,
        "conversion_status": "success",
        "metadata": metadata,
    }


def normalize_patch_items(patches: Any) -> list[dict[str, Any]]:
    if not isinstance(patches, list):
        return []
    normalized: list[dict[str, Any]] = []
    for patch in patches:
        if not isinstance(patch, dict):
            continue
        item = dict(patch)
        if isinstance(item.get("search"), str):
            item["search"] = persist_image_replacements(item["search"])
        if isinstance(item.get("replace"), str):
            item["replace"] = persist_image_replacements(item["replace"])
        normalized.append(item)
    return normalized


def process_one_raw_edit(source_index: int, record: dict[str, Any], out_dir: str, proxy_server: str | None, site_timeout: int) -> dict[str, Any]:
    if site_timeout > 0:
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(site_timeout)
    try:
        root = Path(out_dir)
        instance_id = safe_instance_name(record["instance_id"])
        src_files = raw_src_code(record)
        if not src_files:
            raise ValueError("missing instruction.src_code")
        patches = record.get("response", record.get("patches", []))
        if not isinstance(patches, list) or not patches:
            raise ValueError("missing response patches")

        input_files = normalize_files_for_render(src_files)
        render_dir = root / "_rendered_src" / instance_id / "src"
        image_dir = root / "images" / instance_id / "src_screenshots"
        image_rel = str((Path("images") / instance_id / "src_screenshots" / "screenshot_index.jpg").as_posix())
        write_files(render_dir, input_files)
        _, image_stats = screenshot_index(render_dir, image_dir, proxy_server=proxy_server)
        output_record = build_record(record, input_files, image_rel, image_stats)
        return {
            "index": source_index,
            "instance_id": instance_id,
            "status": "ok",
            "record": output_record,
            "manifest": {
                "index": source_index,
                "instance_id": instance_id,
                "status": "ok",
                "input_image": image_rel,
                "patch_count": len(patches),
                "image_stats": image_stats,
            },
        }
    except Exception as exc:  # noqa: BLE001
        fail_row = {
            "schema_version": "webcoding-image-editing-raw-v1",
            "instance_id": record.get("instance_id"),
            "task": "image-editing",
            "conversion_status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }
        return {
            "index": source_index,
            "instance_id": record.get("instance_id"),
            "status": "error",
            "failed_record": fail_row,
            "manifest": {
                "index": source_index,
                "instance_id": record.get("instance_id"),
                "status": "error",
                "error": fail_row["error"],
            },
        }
    finally:
        if site_timeout > 0:
            signal.alarm(0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-jsonl", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--proxy-server", default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--site-timeout", type=int, default=180)
    args = parser.parse_args()

    success_path, failed_path, manifest_path = prepare_output_dir(args.out_dir, args.resume)
    done = already_done(success_path) if args.resume else set()
    workers = max(1, args.workers)
    max_pending = workers * 2
    pending = set()
    ok = failed = skipped = 0
    totals = {
        "image_count": 0,
        "loaded_image_count": 0,
        "loadable_image_count": 0,
        "loaded_loadable_image_count": 0,
        "visible_loadable_image_count": 0,
        "loaded_visible_loadable_image_count": 0,
    }

    def consume(done_futures) -> None:  # type: ignore[no-untyped-def]
        nonlocal ok, failed
        for future in done_futures:
            result = future.result()
            if result["status"] == "ok":
                append_jsonl(success_path, result["record"])
                ok += 1
                update_totals(totals, result["manifest"].get("image_stats", {}))
            else:
                append_jsonl(failed_path, result["failed_record"])
                failed += 1
            append_jsonl(manifest_path, result["manifest"])

    with ProcessPoolExecutor(max_workers=workers) as executor:
        for source_index, record in iter_raw_edit_records(args.input_jsonl, args.offset, args.limit):
            instance_id = safe_instance_name(record["instance_id"])
            if instance_id in done:
                skipped += 1
                append_jsonl(manifest_path, {"index": source_index, "instance_id": instance_id, "status": "skip_existing"})
                continue
            pending.add(executor.submit(process_one_raw_edit, source_index, record, str(args.out_dir), args.proxy_server, args.site_timeout))
            if len(pending) >= max_pending:
                done_futures, pending = wait(pending, return_when=FIRST_COMPLETED)
                consume(done_futures)
        while pending:
            done_futures, pending = wait(pending, return_when=FIRST_COMPLETED)
            consume(done_futures)

    summary = {
        "input_jsonl": str(args.input_jsonl),
        "out_dir": str(args.out_dir),
        "offset": args.offset,
        "limit": args.limit,
        "proxy_server": args.proxy_server,
        "workers": workers,
        "site_timeout": args.site_timeout,
        "ok": ok,
        "failed": failed,
        "skipped": skipped,
        "image_totals": totals,
        "miss_count": totals["loadable_image_count"] - totals["loaded_loadable_image_count"],
        "visible_miss_count": totals["visible_loadable_image_count"] - totals["loaded_visible_loadable_image_count"],
    }
    (args.out_dir / "_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
