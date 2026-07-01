#!/usr/bin/env python3
"""Audit and optionally slim WebCoding project resources.

Default mode is read-only. Use --apply to remove orphan/duplicate resources.
Referenced third-party/vendor blobs are only externalized when both
--allow-cdn-externalize and --externalize-map are provided.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.webcoding_pipeline.resources import (
    apply_resource_slimming,
    audit_to_dict,
    load_externalize_map,
)


def iter_projects(root: Path) -> list[Path]:
    if (root / "index.html").exists():
        return [root]
    return sorted(path for path in root.iterdir() if path.is_dir() and (path / "index.html").exists())


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit and slim project resources")
    parser.add_argument("--project-root", type=Path, required=True, help="A project dir or a parent containing project dirs")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="Actually delete orphan/duplicate resources")
    parser.add_argument("--protected-path", action="append", default=[], help="Resource path that must never be deleted")
    parser.add_argument("--externalize-map", type=Path, help="JSON map: resources/file.js -> https://cdn.example/file.js")
    parser.add_argument(
        "--allow-cdn-externalize",
        action="store_true",
        help="Allow rewriting mapped referenced vendor blobs to CDN URLs",
    )
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    externalize_map = load_externalize_map(args.externalize_map)
    projects = iter_projects(args.project_root)

    totals = {
        "projects": 0,
        "total_files": 0,
        "orphan_files": 0,
        "duplicate_files": 0,
        "vendor_or_blob_files": 0,
        "delete_candidate_files": 0,
        "delete_candidate_bytes": 0,
        "deleted_files": 0,
        "deleted_bytes": 0,
        "rewritten_refs": 0,
    }
    report_path = args.out_dir / "resource_slimming_report.jsonl"
    deleted_path = args.out_dir / "deleted_resources.jsonl"
    report_path.write_text("", encoding="utf-8")
    deleted_path.write_text("", encoding="utf-8")

    for project in projects:
        audit = apply_resource_slimming(
            project,
            args.protected_path,
            dry_run=not args.apply,
            externalize_map=externalize_map,
            allow_cdn_externalize=args.allow_cdn_externalize,
        )
        row = {"project": str(project), "applied": args.apply, **audit_to_dict(audit)}
        with report_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        with deleted_path.open("a", encoding="utf-8") as handle:
            for item in audit.deleted_files:
                handle.write(
                    json.dumps({"project": str(project), **item}, ensure_ascii=False, separators=(",", ":")) + "\n"
                )
        totals["projects"] += 1
        for key in ("total_files", "orphan_files", "duplicate_files", "vendor_or_blob_files"):
            totals[key] += int(audit.summary.get(key, 0))
        candidate_bytes = sum(int(item.get("size_bytes", 0)) for item in audit.deleted_files)
        totals["delete_candidate_files"] += len(audit.deleted_files)
        totals["delete_candidate_bytes"] += candidate_bytes
        if args.apply:
            totals["deleted_files"] += len(audit.deleted_files)
            totals["deleted_bytes"] += candidate_bytes
        totals["rewritten_refs"] += len(audit.rewritten_refs)

    summary = {
        "project_root": str(args.project_root),
        "out_dir": str(args.out_dir),
        "applied": args.apply,
        "allow_cdn_externalize": args.allow_cdn_externalize,
        "externalize_map": str(args.externalize_map) if args.externalize_map else "",
        **totals,
    }
    (args.out_dir / "resource_slimming_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
