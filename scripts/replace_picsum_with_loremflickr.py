#!/usr/bin/env python3
"""Legacy helper: replace picsum.photos URLs in old JSONL releases.

Do not use this script in new data production. The current policy is to keep
original image URLs, localize real downloaded resources when possible, and let
QC reject samples that still contain synthetic placeholder image services.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


PICSUM_ID_RE = re.compile(r"https?://picsum\.photos/id/(\d+)/(\d+)/(\d+)(?:\?[^\"'\s<>)\\]*)?")
PICSUM_SIZE_RE = re.compile(r"https?://picsum\.photos/(\d+)/(\d+)(?:\?[^\"'\s<>)\\]*)?")


def stable_lock(value: str) -> int:
    return int(hashlib.sha1(value.encode("utf-8")).hexdigest()[:8], 16) % 100000


def replacement_for(width: str, height: str, lock: str) -> str:
    return f"https://loremflickr.com/{width}/{height}?lock={lock}"


def replace_picsum(text: str) -> tuple[str, int]:
    count = 0

    def repl_id(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        image_id, width, height = match.groups()
        return replacement_for(width, height, image_id)

    text = PICSUM_ID_RE.sub(repl_id, text)

    def repl_size(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        width, height = match.groups()
        return replacement_for(width, height, str(stable_lock(match.group(0))))

    text = PICSUM_SIZE_RE.sub(repl_size, text)
    return text, count


def walk_replace(value: Any) -> tuple[Any, int]:
    if isinstance(value, str):
        return replace_picsum(value)
    if isinstance(value, list):
        total = 0
        out = []
        for item in value:
            new_item, n = walk_replace(item)
            total += n
            out.append(new_item)
        return out, total
    if isinstance(value, dict):
        total = 0
        out = {}
        for key, item in value.items():
            new_item, n = walk_replace(item)
            total += n
            out[key] = new_item
        return out, total
    return value, 0


def validate_patches(record: dict[str, Any]) -> list[str]:
    if not record.get("patches"):
        return []
    before = {item["path"]: item["code"] for item in record.get("input_files", [])}
    after = {item["path"]: item["code"] for item in record.get("output_files", [])}
    errors = []
    for index, patch in enumerate(record.get("patches", [])):
        path = patch.get("path")
        if path not in before:
            errors.append(f"patch {index}: path not in input_files: {path}")
            continue
        if path not in after:
            errors.append(f"patch {index}: path not in output_files: {path}")
            continue
        if patch.get("search") not in before[path]:
            errors.append(f"patch {index}: search not found in input file: {path}")
        if patch.get("replace") not in after[path]:
            errors.append(f"patch {index}: replace not found in output file: {path}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--allow-legacy-rewrite",
        action="store_true",
        help="Required acknowledgement: this legacy script must not be used for new production data.",
    )
    parser.add_argument("--input-jsonl", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--failed-jsonl", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    if not args.allow_legacy_rewrite:
        parser.error(
            "--allow-legacy-rewrite is required. New production data should not rewrite image URLs to loremflickr."
        )

    args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    args.failed_jsonl.parent.mkdir(parents=True, exist_ok=True)

    total = success = failed = replacements = 0
    with args.input_jsonl.open(encoding="utf-8") as src, args.output_jsonl.open(
        "w", encoding="utf-8"
    ) as ok_out, args.failed_jsonl.open("w", encoding="utf-8") as bad_out:
        for line in src:
            if args.limit and total >= args.limit:
                break
            total += 1
            record = json.loads(line)
            record, count = walk_replace(record)
            replacements += count
            record.setdefault("metadata", {})
            record["metadata"]["image_url_rewrite"] = {
                "from": "picsum.photos",
                "to": "loremflickr.com",
                "replacements": count,
            }
            errors = validate_patches(record)
            if errors:
                record["conversion_status"] = "failed_after_image_url_rewrite"
                record["conversion_errors"] = errors
                bad_out.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                failed += 1
            else:
                ok_out.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                success += 1

    summary = {
        "input_jsonl": str(args.input_jsonl),
        "output_jsonl": str(args.output_jsonl),
        "total": total,
        "success": success,
        "failed": failed,
        "replacements": replacements,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
