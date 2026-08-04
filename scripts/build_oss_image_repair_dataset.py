#!/usr/bin/env python3
"""Build image-repair JSONL from unified text-repair records.

src_screenshot is the buggy state before repair; dst_screenshot is the fixed
state after repair. The training target remains patches: buggy -> fixed.
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
    iter_jsonl_records,
    prepare_output_dir,
    safe_instance_name,
    timeout_handler,
    update_totals,
)
from build_oss_image_editing_pilot import screenshot_index, write_files


def build_image_repair_record(
    record: dict[str, Any],
    src_image_rel: str,
    dst_image_rel: str,
    src_image_stats: dict[str, int],
    dst_image_stats: dict[str, int],
) -> dict[str, Any]:
    metadata = dict(record.get("metadata") or {})
    metadata.update(
        {
            "base_task": "text-repair",
            "src_screenshot_state": "before_repair_buggy",
            "dst_screenshot_state": "after_repair_fixed",
            "screenshot_viewport": {"width": 1920, "height": 1080, "full_page": True},
            "src_image_stats": src_image_stats,
            "dst_image_stats": dst_image_stats,
            "conversion_mode": record.get("conversion_mode"),
        }
    )
    return {
        "schema_version": record.get("schema_version", "webcoding_unified_v1"),
        "instance_id": record["instance_id"],
        "task": "image-repair",
        "task_type": record.get("task_type", []),
        "page_type": record.get("page_type", "sp"),
        "resources": record.get("resources", []),
        "source_schema": record.get("source_schema"),
        "source_file_manifest": record.get("source_file_manifest", []),
        "instruction": record.get("instruction", "Repair the provided web project according to the defect type."),
        "input_files": record.get("input_files", []),
        "input_images": [src_image_rel],
        "src_screenshot": [src_image_rel],
        "dst_screenshot": [dst_image_rel],
        "output_files": record.get("output_files", []),
        "patches": record.get("patches", []),
        "output_manifest": record.get("output_manifest", []),
        "conversion_status": "success",
        "conversion_mode": record.get("conversion_mode"),
        "metadata": metadata,
    }


def process_one_repair_record(
    source_index: int,
    record: dict[str, Any],
    out_dir: str,
    proxy_server: str | None,
    site_timeout: int,
) -> dict[str, Any]:
    if site_timeout > 0:
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(site_timeout)
    try:
        root = Path(out_dir)
        instance_id = safe_instance_name(record["instance_id"])
        work_root = root / "_rendered_src"
        image_root = root / "images"

        buggy_dir = work_root / instance_id / "buggy"
        fixed_dir = work_root / instance_id / "fixed"
        src_image_dir = image_root / instance_id / "src_screenshots"
        dst_image_dir = image_root / instance_id / "dst_screenshots"
        src_image_rel = str((Path("images") / instance_id / "src_screenshots" / "screenshot_index.jpg").as_posix())
        dst_image_rel = str((Path("images") / instance_id / "dst_screenshots" / "screenshot_index.jpg").as_posix())

        write_files(buggy_dir, record.get("input_files", []))
        write_files(fixed_dir, record.get("output_files", []))
        _, src_stats = screenshot_index(buggy_dir, src_image_dir, proxy_server=proxy_server)
        _, dst_stats = screenshot_index(fixed_dir, dst_image_dir, proxy_server=proxy_server)
        output_record = build_image_repair_record(record, src_image_rel, dst_image_rel, src_stats, dst_stats)
        return {
            "index": source_index,
            "instance_id": instance_id,
            "status": "ok",
            "record": output_record,
            "manifest": {
                "index": source_index,
                "instance_id": instance_id,
                "status": "ok",
                "src_screenshot": src_image_rel,
                "dst_screenshot": dst_image_rel,
                "patch_count": len(record.get("patches", [])),
                "src_image_stats": src_stats,
                "dst_image_stats": dst_stats,
            },
        }
    except Exception as exc:  # noqa: BLE001
        instance_id = record.get("instance_id")
        fail_row = {
            "schema_version": record.get("schema_version", "webcoding_unified_v1"),
            "instance_id": instance_id,
            "task": "image-repair",
            "source_task": record.get("task"),
            "conversion_status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }
        return {
            "index": source_index,
            "instance_id": instance_id,
            "status": "error",
            "failed_record": fail_row,
            "manifest": {
                "index": source_index,
                "instance_id": instance_id,
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
    parser.add_argument("--site-timeout", type=int, default=240, help="Hard timeout seconds per sample; 0 disables")
    args = parser.parse_args()

    success_path, failed_path, manifest_path = prepare_output_dir(args.out_dir, args.resume)
    success_path = args.out_dir / "image-repair.unified.success.jsonl"
    failed_path = args.out_dir / "image-repair.unified.failed.jsonl"
    manifest_path = args.out_dir / "manifest_image_repair.jsonl"
    done = already_done(success_path) if args.resume else set()

    ok = 0
    failed = 0
    skipped = 0
    src_totals = {
        "image_count": 0,
        "loaded_image_count": 0,
        "loadable_image_count": 0,
        "loaded_loadable_image_count": 0,
        "visible_loadable_image_count": 0,
        "loaded_visible_loadable_image_count": 0,
    }
    dst_totals = dict(src_totals)

    workers = max(1, args.workers)
    max_pending = workers * 2
    pending = set()

    def consume_done(done_futures) -> None:  # type: ignore[no-untyped-def]
        nonlocal ok, failed
        for future in done_futures:
            result = future.result()
            if result["status"] == "ok":
                append_jsonl(success_path, result["record"])
                ok += 1
                update_totals(src_totals, result["manifest"].get("src_image_stats", {}))
                update_totals(dst_totals, result["manifest"].get("dst_image_stats", {}))
            else:
                append_jsonl(failed_path, result["failed_record"])
                failed += 1
            append_jsonl(manifest_path, result["manifest"])

    with ProcessPoolExecutor(max_workers=workers) as executor:
        for source_index, record in iter_jsonl_records(args.input_jsonl, args.offset, args.limit):
            instance_id = safe_instance_name(record["instance_id"])
            if instance_id in done:
                skipped += 1
                append_jsonl(manifest_path, {"index": source_index, "instance_id": instance_id, "status": "skip_existing"})
                continue
            pending.add(
                executor.submit(
                    process_one_repair_record,
                    source_index,
                    record,
                    str(args.out_dir),
                    args.proxy_server,
                    args.site_timeout,
                )
            )
            if len(pending) >= max_pending:
                done_futures, pending = wait(pending, return_when=FIRST_COMPLETED)
                consume_done(done_futures)
        while pending:
            done_futures, pending = wait(pending, return_when=FIRST_COMPLETED)
            consume_done(done_futures)

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
        "src_image_totals": src_totals,
        "dst_image_totals": dst_totals,
        "src_miss_count": src_totals["loadable_image_count"] - src_totals["loaded_loadable_image_count"],
        "dst_miss_count": dst_totals["loadable_image_count"] - dst_totals["loaded_loadable_image_count"],
    }
    (args.out_dir / "_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
