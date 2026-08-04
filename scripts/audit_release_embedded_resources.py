#!/usr/bin/env python3
"""Audit embedded resources in WebCoding release JSONL files.

This script is read-only: it does not rewrite release data. It inspects code
items embedded in JSONL records and reports orphan, duplicate, vendor/blob, and
missing `resources/*` references.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.webcoding_pipeline.release_resources import (  # noqa: E402
    audit_record_resources,
    audit_to_detail,
    audit_to_summary,
    load_jsonl,
)


DEFAULT_TASKS = [
    "text-generate",
    "text-edit",
    "text-repair",
    "image-generate",
    "image-edit",
    "image-repair",
]


def add_counts(total: dict[str, Any], row: dict[str, Any]) -> None:
    for key, value in row.items():
        if isinstance(value, int):
            total[key] = total.get(key, 0) + value


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit embedded release resources")
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--tasks", nargs="*", default=DEFAULT_TASKS)
    parser.add_argument("--limit", type=int, default=0, help="Optional per-task sample limit")
    parser.add_argument("--top-k", type=int, default=50)
    args = parser.parse_args()

    jsonl_dir = args.release_root / "jsonl"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    detail_path = args.out_dir / "record_resource_audit.jsonl"
    top_path = args.out_dir / "top_resource_issues.jsonl"
    summary_path = args.out_dir / "resource_audit_summary.json"
    markdown_path = args.out_dir / "resource_audit_summary.md"

    by_task: dict[str, dict[str, Any]] = defaultdict(dict)
    surface_counts: dict[str, Counter[str]] = defaultdict(Counter)
    top_rows: list[dict[str, Any]] = []
    total_records = 0

    with detail_path.open("w", encoding="utf-8") as detail_out:
        for task in args.tasks:
            path = jsonl_dir / f"{task}.jsonl"
            if not path.exists():
                by_task[task]["missing_file"] = str(path)
                continue
            task_total: dict[str, Any] = {"records": 0}
            for _, record in load_jsonl(path, args.limit):
                audit = audit_record_resources(record)
                summary = audit_to_summary(audit)
                detail = audit_to_detail(audit)
                detail["release_task"] = task
                detail_out.write(json.dumps(detail, ensure_ascii=False, separators=(",", ":")) + "\n")
                task_total["records"] += 1
                total_records += 1
                add_counts(task_total, summary)
                surface_counts[task][summary["code_surface"]] += 1
                issue_score = (
                    summary["orphan_chars"]
                    + summary["duplicate_chars"]
                    + summary["vendor_or_blob_chars"]
                    + summary["missing_resource_refs"] * 50_000
                )
                if issue_score:
                    top_rows.append(
                        {
                            "release_task": task,
                            "instance_id": summary["instance_id"],
                            "issue_score": issue_score,
                            **summary,
                        }
                    )
            by_task[task].update(task_total)
            by_task[task]["code_surface_counts"] = dict(surface_counts[task])

    top_rows.sort(key=lambda row: row["issue_score"], reverse=True)
    with top_path.open("w", encoding="utf-8") as top_out:
        for row in top_rows[: args.top_k]:
            top_out.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    summary = {
        "release_root": str(args.release_root),
        "limit_per_task": args.limit,
        "total_records_scanned": total_records,
        "tasks": by_task,
        "outputs": {
            "detail_jsonl": str(detail_path),
            "top_issues_jsonl": str(top_path),
            "summary_json": str(summary_path),
            "summary_md": str(markdown_path),
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Release Embedded Resource Audit",
        "",
        f"- release_root: `{summary['release_root']}`",
        f"- total_records_scanned: {summary['total_records_scanned']}",
        f"- limit_per_task: {summary['limit_per_task']}",
        "",
        "| task | records | code surface | resource files | orphan chars | duplicate chars | vendor/blob chars | missing refs |",
        "|---|---:|---|---:|---:|---:|---:|---:|",
    ]
    for task, data in summary["tasks"].items():
        surfaces = ", ".join(f"{k}:{v}" for k, v in sorted(data.get("code_surface_counts", {}).items()))
        lines.append(
            "| {task} | {records} | {surfaces} | {resource_files} | {orphan_chars} | {duplicate_chars} | {vendor_chars} | {missing_refs} |".format(
                task=task,
                records=data.get("records", 0),
                surfaces=surfaces or "-",
                resource_files=data.get("resource_files", 0),
                orphan_chars=data.get("orphan_chars", 0),
                duplicate_chars=data.get("duplicate_chars", 0),
                vendor_chars=data.get("vendor_or_blob_chars", 0),
                missing_refs=data.get("missing_resource_refs", 0),
            )
        )
    lines.extend(
        [
            "",
            "Policy:",
            "",
            "- Keep HTML and inline CSS/JS.",
            "- Delete orphan and exact duplicate `resources/*.js` after audit.",
            "- Externalize only confirmed third-party JS with an explicit CDN map.",
            "- Keep author JS and uncertain mixed bundles.",
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
