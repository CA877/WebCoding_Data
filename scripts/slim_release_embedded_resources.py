#!/usr/bin/env python3
"""Create a slimmed WebCoding release by removing embedded orphan/duplicate resources."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.webcoding_pipeline.release_resources import slim_record_resources  # noqa: E402


DEFAULT_TASKS = [
    "text-generate",
    "text-edit",
    "text-repair",
    "image-generate",
    "image-edit",
    "image-repair",
]


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Slim embedded resources in release JSONL")
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--tasks", nargs="*", default=DEFAULT_TASKS)
    parser.add_argument("--limit", type=int, default=0, help="Optional per-task limit for smoke tests")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--copy-images", action="store_true", help="Hardlink/copy release images into out-root")
    parser.add_argument("--drop-vendor-blobs", action="store_true", help="Drop referenced vendor/blob resources from embedded code")
    parser.add_argument("--externalize-map", type=Path, default=None, help="JSON map of local resources paths to CDN URLs")
    parser.add_argument("--optimize-code", action="store_true", help="Minify embedded HTML/CSS for training budget checks")
    parser.add_argument(
        "--max-training-chars",
        type=int,
        default=0,
        help="Deprecated guardrail; formal data must filter over-budget samples instead of truncating them",
    )
    args = parser.parse_args()
    if args.max_training_chars:
        raise SystemExit(
            "--max-training-chars is disabled: do not truncate samples for length. "
            "Use scripts/check_release_training_lengths.py and filter over-budget records."
        )
    externalize_map = {}
    if args.externalize_map:
        externalize_map = json.loads(args.externalize_map.read_text(encoding="utf-8"))
        if not isinstance(externalize_map, dict):
            raise SystemExit("--externalize-map must be a JSON object: local path -> CDN URL")

    if args.out_root.exists():
        if not args.overwrite:
            raise SystemExit(f"out-root exists; pass --overwrite: {args.out_root}")
        shutil.rmtree(args.out_root)
    (args.out_root / "jsonl").mkdir(parents=True)
    audit_dir = args.out_root / "resource_slimming_audit"
    audit_dir.mkdir(parents=True)
    copy_release_metadata(args.release_root, args.out_root)
    if args.copy_images:
        hardlink_or_copy_tree(args.release_root / "images", args.out_root / "images")

    change_path = audit_dir / "deleted_resources.jsonl"
    summary_path = audit_dir / "resource_slimming_summary.json"
    task_summary: dict[str, dict] = {}

    with change_path.open("w", encoding="utf-8") as change_out:
        for task in args.tasks:
            src = args.release_root / "jsonl" / f"{task}.jsonl"
            dst = args.out_root / "jsonl" / f"{task}.jsonl"
            if not src.exists():
                task_summary[task] = {"missing_file": str(src)}
                continue
            counts = {
                "records": 0,
                "deleted_items": 0,
                "deleted_chars": 0,
                "duplicate_rewrites": 0,
                "removed_missing_asset_refs": 0,
                "dropped_vendor_blobs": 0,
                "externalized_vendor_rewrites": 0,
                "budget_enforced": 0,
                "budget_satisfied": 0,
                "removed_inline_script_chars": 0,
                "removed_style_chars": 0,
                "removed_non_html_code_chars": 0,
                "truncated_html_chars": 0,
                "post_budget_orphans_removed": 0,
                "before_chars": 0,
                "after_chars": 0,
                "before_resource_chars": 0,
                "after_resource_chars": 0,
            }
            with dst.open("w", encoding="utf-8") as out:
                for record in iter_jsonl(src, args.limit):
                    slimmed, change = slim_record_resources(
                        record,
                        drop_vendor_blobs=args.drop_vendor_blobs,
                        optimize_code=args.optimize_code,
                        max_training_chars=args.max_training_chars,
                        externalize_map=externalize_map,
                    )
                    out.write(json.dumps(slimmed, ensure_ascii=False, separators=(",", ":")) + "\n")
                    counts["records"] += 1
                    counts["deleted_items"] += len(change["deleted_items"])
                    counts["deleted_chars"] += sum(item["size_chars"] for item in change["deleted_items"])
                    counts["duplicate_rewrites"] += len(change["duplicate_rewrites"])
                    counts["removed_missing_asset_refs"] += len(change["removed_missing_asset_refs"])
                    counts["dropped_vendor_blobs"] += len(change["dropped_vendor_blob_paths"])
                    counts["externalized_vendor_rewrites"] += len(change.get("externalized_vendor_rewrites", {}))
                    budget_change = change.get("budget_change", {})
                    if budget_change.get("budget_enforced"):
                        counts["budget_enforced"] += 1
                    if budget_change.get("budget_satisfied"):
                        counts["budget_satisfied"] += 1
                    counts["removed_inline_script_chars"] += int(budget_change.get("removed_inline_script_chars", 0))
                    counts["removed_style_chars"] += int(budget_change.get("removed_style_chars", 0))
                    counts["removed_non_html_code_chars"] += int(budget_change.get("removed_non_html_code_chars", 0))
                    counts["truncated_html_chars"] += int(budget_change.get("truncated_html_chars", 0))
                    counts["post_budget_orphans_removed"] += len(change.get("post_budget_orphans_removed", []))
                    counts["before_chars"] += change["before"]["total_chars"]
                    counts["after_chars"] += change["after"]["total_chars"]
                    counts["before_resource_chars"] += change["before"]["resource_chars"]
                    counts["after_resource_chars"] += change["after"]["resource_chars"]
                    if (
                        change["deleted_items"]
                        or change["duplicate_rewrites"]
                        or change["removed_missing_asset_refs"]
                        or change["dropped_vendor_blob_paths"]
                        or change.get("externalized_vendor_rewrites")
                        or change.get("budget_change", {}).get("budget_enforced")
                        or change.get("post_budget_orphans_removed")
                    ):
                        change["release_task"] = task
                        change_out.write(json.dumps(change, ensure_ascii=False, separators=(",", ":")) + "\n")
            task_summary[task] = counts

    summary = {
        "source_release": str(args.release_root),
        "out_root": str(args.out_root),
        "limit_per_task": args.limit,
        "policy": "keep HTML + inline CSS/JS + author JS; delete embedded orphan and exact duplicate resources",
        "drop_vendor_blobs": args.drop_vendor_blobs,
        "externalize_map": str(args.externalize_map) if args.externalize_map else "",
        "optimize_code": args.optimize_code,
        "max_training_chars": args.max_training_chars,
        "tasks": task_summary,
        "audit_files": {"deleted_resources_jsonl": str(change_path), "summary_json": str(summary_path)},
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
