#!/usr/bin/env python3
"""Validate image attributes already embedded in current edit records.

Pipeline C/rescue already stores the reviewed local-render screenshots in each
source project's project-level screenshots.  Re-rendering here is wasteful and
can produce a different network state, so this adapter only validates records.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from WebCoding_Data.construct.construct_common import (
    append_jsonl,
    existing_final_screenshots,
    iter_jsonl_records,
)


def _screenshots(project: Path) -> list[dict[str, str]]:
    return existing_final_screenshots(project)


def _to_image_edit_record(record: dict) -> dict:
    """Convert one successful forward text-edit record without re-rendering.

    The reviewed project-root PNG describes the original project, which is the
    *source* state for forward editing.  It must never be copied into the
    destination screenshot field because the LLM-generated destination has not
    been rendered or reviewed.
    """
    instance_id = record.get("instance_id", "")
    if record.get("status") != "ok":
        raise ValueError(f"source record is not successful: {instance_id}")
    images = dict(record.get("images") or {})
    images["src_screenshot"] = list(images.get("src_screenshot") or [])
    images["dst_screenshot"] = list(images.get("dst_screenshot") or [])
    if not images["src_screenshot"]:
        if record.get("construction_strategy") != "forward":
            raise ValueError("reverse edit has no reviewed source screenshot")
        images["src_screenshot"] = _screenshots(Path(record["source_project"]))
    for image in [*images["src_screenshot"], *images["dst_screenshot"]]:
        if not Path(image["path"]).is_file():
            raise FileNotFoundError(image["path"])
    metadata = dict(record.get("metadata") or {})
    metadata.update({"base_task": "text-editing", "screenshot_state": "before_edit"})
    return {
        **record,
        "task": "image-editing",
        "images": images,
        "metadata": metadata,
        "screenshot_source": "project_embedded_final_screenshots",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate/copy unified edit records; never re-screenshot.")
    parser.add_argument("--records-jsonl", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if args.output_jsonl.exists() and args.overwrite:
        args.output_jsonl.unlink()
    done: set[str] = set()
    if args.output_jsonl.exists():
        for record in iter_jsonl_records(args.output_jsonl, ignore_invalid=True):
            if record.get("status") == "ok" and record.get("instance_id"):
                done.add(record["instance_id"])

    total = ok = errors = 0
    for record in iter_jsonl_records(args.records_jsonl):
        instance_id = record.get("instance_id", "")
        if record.get("status") != "ok" or instance_id in done:
            continue
        total += 1
        try:
            payload = _to_image_edit_record(record)
            append_jsonl(args.output_jsonl, payload); ok += 1
        except Exception as exc:  # noqa: BLE001
            append_jsonl(args.output_jsonl, {"instance_id": instance_id, "task": "image-editing",
                                             "status": "error", "error": f"{type(exc).__name__}: {exc}"})
            errors += 1
    print(f"image-editing adapter done: {ok} ok, {errors} errors, {total} considered")


if __name__ == "__main__":
    main()
