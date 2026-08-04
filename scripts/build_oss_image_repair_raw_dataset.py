#!/usr/bin/env python3
"""Build image-repair from raw OSS text-repair.jsonl records."""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from copy import deepcopy
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
from normalize_oss_webcoding_jsonl import normalize_repair


def iter_raw_records(path: Path, offset: int, limit: int):
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


def raw_source_files(raw_record: dict[str, Any]) -> list[dict[str, str]]:
    source = raw_record.get("instruction", [])
    return source if isinstance(source, list) else []


def normalize_patch_items(patches: Any) -> list[dict[str, Any]]:
    if not isinstance(patches, list):
        return []
    out: list[dict[str, Any]] = []
    for patch in patches:
        if not isinstance(patch, dict):
            continue
        item = dict(patch)
        if isinstance(item.get("search"), str):
            item["search"] = persist_image_replacements(item["search"])
        if isinstance(item.get("replace"), str):
            item["replace"] = persist_image_replacements(item["replace"])
        out.append(item)
    return out


def build_record(
    normalized: dict[str, Any],
    input_files: list[dict[str, str]],
    output_files: list[dict[str, str]],
    patches: list[dict[str, Any]],
    src_image_rel: str,
    dst_image_rel: str,
    src_stats: dict[str, int],
    dst_stats: dict[str, int],
) -> dict[str, Any]:
    metadata = dict(normalized.get("metadata") or {})
    metadata.update(
        {
            "base_task": "text-repair",
            "source_format": "raw_oss_text_repair",
            "src_screenshot_state": "before_repair_buggy",
            "dst_screenshot_state": "after_repair_fixed",
            "screenshot_viewport": {"width": 1920, "height": 1080, "full_page": True},
            "src_image_stats": src_stats,
            "dst_image_stats": dst_stats,
            "conversion_mode": normalized.get("conversion_mode"),
            "image_url_rewrite": "persisted_to_input_output_files_and_patches_loremflickr",
        }
    )
    return {
        "schema_version": "webcoding-image-repair-raw-v1",
        "instance_id": normalized["instance_id"],
        "task": "image-repair",
        "task_type": normalized.get("task_type", []),
        "page_type": normalized.get("page_type", "sp"),
        "resources": normalized.get("resources", []),
        "source_schema": normalized.get("source_schema"),
        "source_file_manifest": normalized.get("source_file_manifest", []),
        "instruction": normalized.get("instruction", "Repair the provided web project according to the defect type."),
        "input_files": input_files,
        "output_files": output_files,
        "input_images": [src_image_rel],
        "src_screenshot": [src_image_rel],
        "dst_screenshot": [dst_image_rel],
        "patches": patches,
        "response": patches,
        "output_manifest": normalized.get("output_manifest", []),
        "conversion_status": "success",
        "conversion_mode": normalized.get("conversion_mode"),
        "metadata": metadata,
    }


def build_src_only_record(
    raw_record: dict[str, Any],
    input_files: list[dict[str, str]],
    patches: list[dict[str, Any]],
    src_image_rel: str,
    src_stats: dict[str, int],
    reason: str,
) -> dict[str, Any]:
    metadata = dict(raw_record.get("metadata") or {})
    metadata.update(
        {
            "base_task": "text-repair",
            "source_format": "raw_oss_text_repair",
            "src_screenshot_state": "raw_input_before_fix",
            "dst_screenshot_state": "unavailable_patch_not_matched",
            "screenshot_viewport": {"width": 1920, "height": 1080, "full_page": True},
            "src_image_stats": src_stats,
            "image_url_rewrite": "persisted_to_input_files_and_patches_loremflickr",
            "repair_image_mode": "src_only",
            "src_only_reason": reason,
        }
    )
    return {
        "schema_version": "webcoding-image-repair-raw-v1",
        "instance_id": raw_record["instance_id"],
        "task": "image-repair",
        "task_type": raw_record.get("task_type", []),
        "page_type": raw_record.get("page_type", "sp"),
        "resources": raw_record.get("resources", []),
        "instruction": "Repair the provided web project according to the defect type.",
        "input_files": input_files,
        "output_files": [],
        "input_images": [src_image_rel],
        "src_screenshot": [src_image_rel],
        "dst_screenshot": [],
        "patches": patches,
        "response": patches,
        "conversion_status": "partial_success_src_screenshot_only",
        "metadata": metadata,
    }


def process_one(source_index: int, raw_record: dict[str, Any], out_dir: str, proxy_server: str | None, site_timeout: int) -> dict[str, Any]:
    if site_timeout > 0:
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(site_timeout)
    try:
        normalized, rejected = normalize_repair(deepcopy(raw_record))
        if normalized is None:
            errors = rejected.get("conversion_errors") if isinstance(rejected, dict) else None
            reason = f"normalize_repair failed: {errors}"
            instance_id = safe_instance_name(raw_record["instance_id"])
            input_files = normalize_files_for_render(raw_source_files(raw_record))
            patches = normalize_patch_items(raw_record.get("response", raw_record.get("patches", [])))
            if not input_files or not patches:
                raise ValueError(reason)
            root = Path(out_dir)
            raw_dir = root / "_rendered_src" / instance_id / "raw_input"
            src_dir = root / "images" / instance_id / "src_screenshots"
            src_rel = str((Path("images") / instance_id / "src_screenshots" / "screenshot_index.jpg").as_posix())
            write_files(raw_dir, input_files)
            _, src_stats = screenshot_index(raw_dir, src_dir, proxy_server=proxy_server)
            record = build_src_only_record(raw_record, input_files, patches, src_rel, src_stats, reason)
            return {
                "index": source_index,
                "instance_id": instance_id,
                "status": "ok",
                "record": record,
                "manifest": {
                    "index": source_index,
                    "instance_id": instance_id,
                    "status": "ok_src_only",
                    "src_screenshot": src_rel,
                    "dst_screenshot": "",
                    "patch_count": len(patches),
                    "src_image_stats": src_stats,
                    "dst_image_stats": {},
                    "repair_image_mode": "src_only",
                    "src_only_reason": reason,
                },
            }

        root = Path(out_dir)
        instance_id = safe_instance_name(normalized["instance_id"])
        input_files = normalize_files_for_render(normalized.get("input_files", []))
        output_files = normalize_files_for_render(normalized.get("output_files", []))
        patches = normalize_patch_items(normalized.get("patches", []))
        if not input_files or not output_files or not patches:
            raise ValueError("missing normalized input/output/patches")

        buggy_dir = root / "_rendered_src" / instance_id / "buggy"
        fixed_dir = root / "_rendered_src" / instance_id / "fixed"
        src_dir = root / "images" / instance_id / "src_screenshots"
        dst_dir = root / "images" / instance_id / "dst_screenshots"
        src_rel = str((Path("images") / instance_id / "src_screenshots" / "screenshot_index.jpg").as_posix())
        dst_rel = str((Path("images") / instance_id / "dst_screenshots" / "screenshot_index.jpg").as_posix())

        write_files(buggy_dir, input_files)
        write_files(fixed_dir, output_files)
        _, src_stats = screenshot_index(buggy_dir, src_dir, proxy_server=proxy_server)
        _, dst_stats = screenshot_index(fixed_dir, dst_dir, proxy_server=proxy_server)
        record = build_record(normalized, input_files, output_files, patches, src_rel, dst_rel, src_stats, dst_stats)
        return {
            "index": source_index,
            "instance_id": instance_id,
            "status": "ok",
            "record": record,
            "manifest": {
                "index": source_index,
                "instance_id": instance_id,
                "status": "ok",
                "src_screenshot": src_rel,
                "dst_screenshot": dst_rel,
                "patch_count": len(patches),
                "src_image_stats": src_stats,
                "dst_image_stats": dst_stats,
                "conversion_mode": normalized.get("conversion_mode"),
            },
        }
    except Exception as exc:  # noqa: BLE001
        fail = {
            "schema_version": "webcoding-image-repair-raw-v1",
            "instance_id": raw_record.get("instance_id"),
            "task": "image-repair",
            "conversion_status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }
        return {
            "index": source_index,
            "instance_id": raw_record.get("instance_id"),
            "status": "error",
            "failed_record": fail,
            "manifest": {"index": source_index, "instance_id": raw_record.get("instance_id"), "status": "error", "error": fail["error"]},
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
    parser.add_argument("--site-timeout", type=int, default=240)
    args = parser.parse_args()

    success_path, failed_path, manifest_path = prepare_output_dir(args.out_dir, args.resume)
    success_path = args.out_dir / "image-repair.unified.success.jsonl"
    failed_path = args.out_dir / "image-repair.unified.failed.jsonl"
    manifest_path = args.out_dir / "manifest_image_repair.jsonl"
    done = already_done(success_path) if args.resume else set()

    workers = max(1, args.workers)
    max_pending = workers * 2
    pending = set()
    ok = failed = skipped = 0
    src_totals = {k: 0 for k in ["image_count", "loaded_image_count", "loadable_image_count", "loaded_loadable_image_count", "visible_loadable_image_count", "loaded_visible_loadable_image_count"]}
    dst_totals = dict(src_totals)

    def consume(done_futures) -> None:  # type: ignore[no-untyped-def]
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
        for source_index, raw_record in iter_raw_records(args.input_jsonl, args.offset, args.limit):
            instance_id = safe_instance_name(raw_record["instance_id"])
            if instance_id in done:
                skipped += 1
                append_jsonl(manifest_path, {"index": source_index, "instance_id": instance_id, "status": "skip_existing"})
                continue
            pending.add(executor.submit(process_one, source_index, raw_record, str(args.out_dir), args.proxy_server, args.site_timeout))
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
        "src_image_totals": src_totals,
        "dst_image_totals": dst_totals,
        "src_miss_count": src_totals["loadable_image_count"] - src_totals["loaded_loadable_image_count"],
        "dst_miss_count": dst_totals["loadable_image_count"] - dst_totals["loaded_loadable_image_count"],
    }
    (args.out_dir / "_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
