#!/usr/bin/env python3
"""Apply conservative CSS slimming to existing WebCoding release JSONL.

This is a postprocess for already-built samples. It does not truncate records:
it externalizes confirmed third-party inline CSS blocks, tree-shakes remaining
inline CSS against the page HTML, and writes a new release directory.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PREPROCESS_ROOT = REPO_ROOT / "preprocess"
for path in (REPO_ROOT, PREPROCESS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from playwright_crawl import slim_pipeline_c_html  # noqa: E402


DEFAULT_TASKS = [
    "text-generate",
    "text-edit",
    "text-repair",
    "image-generate",
    "image-edit",
    "image-repair",
]
HTML_EXTS = {".html", ".htm"}


def iter_jsonl(path: Path, limit: int = 0):
    with path.open(encoding="utf-8", errors="ignore") as handle:
        for index, line in enumerate(handle, start=1):
            if limit and index > limit:
                break
            if line.strip():
                yield json.loads(line)


def copy_release_metadata(source_root: Path, out_root: Path) -> None:
    for name in ("README.md", "dataset_index.json"):
        src = source_root / name
        if src.exists():
            shutil.copy2(src, out_root / name)


def hardlink_or_copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        target = dst / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                target.hardlink_to(path)
            except OSError:
                shutil.copy2(path, target)


def is_html_path(path: str) -> bool:
    return Path(path).suffix.lower() in HTML_EXTS


def slim_item(item: Any) -> tuple[bool, int, int]:
    if not isinstance(item, dict):
        return False, 0, 0
    path = item.get("path")
    code = item.get("code")
    if not isinstance(path, str) or not isinstance(code, str) or not is_html_path(path):
        return False, 0, 0
    before = len(code)
    after_code = slim_pipeline_c_html(code)
    item["code"] = after_code
    return before != len(after_code), before, len(after_code)


def slim_record(record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    before_chars = 0
    after_chars = 0
    changed_items = 0
    html_items = 0
    for key in ("response", "output_files", "input_files"):
        value = record.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, dict) and is_html_path(str(item.get("path", ""))):
                html_items += 1
            changed, before, after = slim_item(item)
            if before:
                before_chars += before
                after_chars += after
            if changed:
                changed_items += 1

    instruction = record.get("instruction")
    if isinstance(instruction, list):
        for item in instruction:
            if isinstance(item, dict) and is_html_path(str(item.get("path", ""))):
                html_items += 1
            changed, before, after = slim_item(item)
            if before:
                before_chars += before
                after_chars += after
            if changed:
                changed_items += 1
    elif isinstance(instruction, dict) and isinstance(instruction.get("src_code"), list):
        for item in instruction["src_code"]:
            if isinstance(item, dict) and is_html_path(str(item.get("path", ""))):
                html_items += 1
            changed, before, after = slim_item(item)
            if before:
                before_chars += before
                after_chars += after
            if changed:
                changed_items += 1

    metadata = record.setdefault("metadata", {})
    if isinstance(metadata, dict):
        metadata["css_tree_shaking_policy"] = (
            "externalize_confirmed_third_party_inline_css_and_keep_matching_css_rules"
        )

    return record, {
        "html_items": html_items,
        "changed_items": changed_items,
        "before_html_chars": before_chars,
        "after_html_chars": after_chars,
        "removed_html_chars": before_chars - after_chars,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Slim inline CSS in existing release JSONL")
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--tasks", nargs="*", default=DEFAULT_TASKS)
    parser.add_argument("--limit", type=int, default=0, help="Optional per-task limit")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--copy-images", action="store_true")
    args = parser.parse_args()

    if args.out_root.exists():
        if not args.overwrite:
            raise SystemExit(f"out-root exists; pass --overwrite: {args.out_root}")
        shutil.rmtree(args.out_root)
    (args.out_root / "jsonl").mkdir(parents=True)
    audit_dir = args.out_root / "css_tree_shaking_audit"
    audit_dir.mkdir(parents=True)
    copy_release_metadata(args.release_root, args.out_root)
    if args.copy_images:
        hardlink_or_copy_tree(args.release_root / "images", args.out_root / "images")

    changes_path = audit_dir / "css_tree_shaking_changes.jsonl"
    summary_path = audit_dir / "css_tree_shaking_summary.json"
    task_summary: dict[str, dict[str, Any]] = {}
    with changes_path.open("w", encoding="utf-8") as changes_out:
        for task in args.tasks:
            src = args.release_root / "jsonl" / f"{task}.jsonl"
            dst = args.out_root / "jsonl" / f"{task}.jsonl"
            if not src.exists():
                task_summary[task] = {"missing_file": str(src)}
                continue
            counts = {
                "records": 0,
                "records_changed": 0,
                "html_items": 0,
                "changed_items": 0,
                "before_html_chars": 0,
                "after_html_chars": 0,
                "removed_html_chars": 0,
            }
            with dst.open("w", encoding="utf-8") as out:
                for record in iter_jsonl(src, args.limit):
                    slimmed, change = slim_record(record)
                    out.write(json.dumps(slimmed, ensure_ascii=True, separators=(",", ":")) + "\n")
                    counts["records"] += 1
                    if change["changed_items"]:
                        counts["records_changed"] += 1
                    for key in (
                        "html_items",
                        "changed_items",
                        "before_html_chars",
                        "after_html_chars",
                        "removed_html_chars",
                    ):
                        counts[key] += int(change[key])
                    if change["changed_items"]:
                        change["release_task"] = task
                        change["instance_id"] = record.get("instance_id", "")
                        changes_out.write(json.dumps(change, ensure_ascii=True, separators=(",", ":")) + "\n")
            task_summary[task] = counts

    summary = {
        "source_release": str(args.release_root),
        "out_root": str(args.out_root),
        "limit_per_task": args.limit,
        "policy": "confirmed third-party inline CSS externalized; remaining inline CSS tree-shaken conservatively",
        "tasks": task_summary,
        "audit_files": {
            "changes_jsonl": str(changes_path),
            "summary_json": str(summary_path),
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
