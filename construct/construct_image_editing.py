#!/usr/bin/env python3
"""Validate image attributes already embedded in current edit records.

Pipeline C/rescue already stores the reviewed local-render screenshots in each
source project's project-level screenshots.  Re-rendering here is wasteful and
can produce a different network state, so this adapter only validates records.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from WebCoding_Data.construct.construct_common import append_jsonl, existing_final_screenshots


def _screenshots(project: Path) -> list[dict[str, str]]:
    return existing_final_screenshots(project)


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
        for line in args.output_jsonl.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
                if record.get("status") == "ok": done.add(record["instance_id"])
            except (json.JSONDecodeError, KeyError):
                continue

    total = ok = errors = 0
    for line in args.records_jsonl.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line); instance_id = record.get("instance_id", "")
        if record.get("status") != "ok" or instance_id in done:
            continue
        total += 1
        try:
            images = record.get("images") or {}
            if not images.get("dst_screenshot"):
                project = Path(record["source_project"])
                images["dst_screenshot"] = _screenshots(project)
                images.setdefault("src_screenshot", [])
            for image in [*images.get("src_screenshot", []), *images.get("dst_screenshot", [])]:
                if not Path(image["path"]).is_file():
                    raise FileNotFoundError(image["path"])
            payload = {**record, "images": images, "screenshot_source": "project_embedded_final_screenshots"}
            append_jsonl(args.output_jsonl, payload); ok += 1
        except Exception as exc:  # noqa: BLE001
            append_jsonl(args.output_jsonl, {"instance_id": instance_id, "task": "image-editing",
                                             "status": "error", "error": f"{type(exc).__name__}: {exc}"})
            errors += 1
    print(f"image-editing adapter done: {ok} ok, {errors} errors, {total} considered")


if __name__ == "__main__":
    main()
