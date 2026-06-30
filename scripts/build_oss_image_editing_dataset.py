#!/usr/bin/env python3
"""Build image-editing JSONL from unified text-editing records.

The output keeps the text-editing supervision target (patches) and adds a
before-edit screenshot rendered from the local input_files.
"""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import json
import signal
from pathlib import Path
from typing import Any

from build_oss_image_editing_pilot import screenshot_index, write_files


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def safe_instance_name(instance_id: str) -> str:
    if not instance_id or "/" in instance_id or "\x00" in instance_id or instance_id in {".", ".."}:
        raise ValueError(f"unsafe instance_id: {instance_id!r}")
    return instance_id


def build_image_edit_record(
    record: dict[str, Any],
    image_rel_path: str,
    image_stats: dict[str, int],
) -> dict[str, Any]:
    metadata = dict(record.get("metadata") or {})
    metadata.update(
        {
            "base_task": "text-editing",
            "screenshot_state": "before_edit",
            "screenshot_viewport": {"width": 1920, "height": 1080, "full_page": True},
            "image_stats": image_stats,
        }
    )
    return {
        "schema_version": record.get("schema_version", "webcoding_unified_v1"),
        "instance_id": record["instance_id"],
        "task": "image-editing",
        "task_type": record.get("task_type", []),
        "page_type": record.get("page_type", "sp"),
        "resources": record.get("resources", []),
        "source_schema": record.get("source_schema"),
        "source_file_manifest": record.get("source_file_manifest", []),
        "instruction": record.get("instruction", ""),
        "input_files": record.get("input_files", []),
        "input_images": [image_rel_path],
        "src_screenshot": [image_rel_path],
        "output_files": record.get("output_files", []),
        "patches": record.get("patches", []),
        "output_manifest": record.get("output_manifest", []),
        "conversion_status": "success",
        "metadata": metadata,
    }


def prepare_output_dir(out_dir: Path, resume: bool) -> tuple[Path, Path, Path]:
    success_path = out_dir / "image-editing.unified.success.jsonl"
    failed_path = out_dir / "image-editing.unified.failed.jsonl"
    manifest_path = out_dir / "manifest_image_editing.jsonl"
    if out_dir.exists() and not resume:
        existing = [p for p in out_dir.iterdir()]
        if existing:
            raise FileExistsError(f"output dir is not empty; use a new dir or --resume: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    return success_path, failed_path, manifest_path


def already_done(success_path: Path) -> set[str]:
    done: set[str] = set()
    if not success_path.exists():
        return done
    with success_path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                done.add(json.loads(line)["instance_id"])
            except Exception:
                continue
    return done


def timeout_handler(signum, frame) -> None:  # type: ignore[no-untyped-def]
    raise TimeoutError("sample timed out")


def process_one_record(
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
        image_dir = image_root / instance_id / "src_screenshots"
        render_dir = work_root / instance_id / "src"
        image_rel = str((Path("images") / instance_id / "src_screenshots" / "screenshot_index.jpg").as_posix())

        write_files(render_dir, record.get("input_files", []))
        _, image_stats = screenshot_index(render_dir, image_dir, proxy_server=proxy_server)
        output_record = build_image_edit_record(record, image_rel, image_stats)
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
                "patch_count": len(record.get("patches", [])),
                "image_stats": image_stats,
            },
        }
    except Exception as exc:  # noqa: BLE001
        instance_id = record.get("instance_id")
        fail_row = {
            "schema_version": record.get("schema_version", "webcoding_unified_v1"),
            "instance_id": instance_id,
            "task": "image-editing",
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


def iter_jsonl_records(path: Path, offset: int, limit: int):
    yielded = 0
    with path.open(encoding="utf-8") as f:
        for zero_index, line in enumerate(f):
            if zero_index < offset:
                continue
            if limit and yielded >= limit:
                break
            if not line.strip():
                continue
            yielded += 1
            yield zero_index + 1, json.loads(line)


def update_totals(totals: dict[str, int], image_stats: dict[str, int]) -> None:
    for key in totals:
        totals[key] += int(image_stats.get(key, 0))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-jsonl", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--proxy-server", default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--site-timeout", type=int, default=180, help="Hard timeout seconds per sample; 0 disables")
    args = parser.parse_args()

    success_path, failed_path, manifest_path = prepare_output_dir(args.out_dir, args.resume)
    done = already_done(success_path) if args.resume else set()

    ok = 0
    failed = 0
    skipped = 0
    totals = {
        "image_count": 0,
        "loaded_image_count": 0,
        "loadable_image_count": 0,
        "loaded_loadable_image_count": 0,
        "visible_loadable_image_count": 0,
        "loaded_visible_loadable_image_count": 0,
    }

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
                update_totals(totals, result["manifest"].get("image_stats", {}))
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
                    process_one_record,
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
        "image_totals": totals,
        "miss_count": totals["loadable_image_count"] - totals["loaded_loadable_image_count"],
        "visible_miss_count": totals["visible_loadable_image_count"] - totals["loaded_visible_loadable_image_count"],
    }
    (args.out_dir / "_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
