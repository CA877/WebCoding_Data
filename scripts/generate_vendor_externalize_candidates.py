#!/usr/bin/env python3
"""Generate conservative CDN externalization candidates for embedded vendor JS."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.webcoding_pipeline.release_resources import (  # noqa: E402
    audit_record_resources,
    load_jsonl,
    normalize_resource_ref,
)

TASKS = [
    "text-generate",
    "text-edit",
    "text-repair",
    "image-generate",
    "image-edit",
    "image-repair",
]


def infer_cdn_url(path: str, code: str) -> tuple[str | None, str, str]:
    name = Path(path).name.lower()
    haystack = f"{path}\n{code[:5000]}".lower()
    if "recaptcha" in haystack or "grecaptcha" in haystack:
        return "https://www.google.com/recaptcha/api.js", "confirmed_candidate", "google_recaptcha"
    if "jquery-migrate" in name:
        return "https://code.jquery.com/jquery-migrate-3.4.1.min.js", "confirmed_candidate", "jquery_migrate"
    if re.search(r"jquery(?:[.-]\d[\w.-]*)?\.min\.js$", name) or name.endswith("_jquery.min.js"):
        return "https://code.jquery.com/jquery-3.7.1.min.js", "confirmed_candidate", "jquery"
    if "bootstrap.bundle" in name and name.endswith(".js"):
        return "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js", "confirmed_candidate", "bootstrap_bundle"
    if "bootstrap" in name and name.endswith(".js"):
        return "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.min.js", "confirmed_candidate", "bootstrap"
    if "popper" in name and name.endswith(".js"):
        return "https://cdn.jsdelivr.net/npm/@popperjs/core@2.11.8/dist/umd/popper.min.js", "confirmed_candidate", "popper"
    if "lodash" in name and name.endswith(".js"):
        return "https://cdn.jsdelivr.net/npm/lodash@4.17.21/lodash.min.js", "confirmed_candidate", "lodash"
    if "moment" in name and name.endswith(".js"):
        return "https://cdn.jsdelivr.net/npm/moment@2.30.1/min/moment.min.js", "confirmed_candidate", "moment"
    if "swiper-bundle" in name and name.endswith(".js"):
        return "https://cdn.jsdelivr.net/npm/swiper@11/swiper-bundle.min.js", "confirmed_candidate", "swiper"
    if "slick" in name and name.endswith(".js"):
        return "https://cdnjs.cloudflare.com/ajax/libs/slick-carousel/1.8.1/slick.min.js", "confirmed_candidate", "slick"
    if name.endswith("webfont.js") or "_webfont.js" in name:
        return "https://ajax.googleapis.com/ajax/libs/webfont/1.6.26/webfont.js", "confirmed_candidate", "webfont"
    if "wp-emoji-release" in name:
        return None, "uncertain_vendor_blob", "wordpress_emoji_no_cdn_mapping"
    if any(token in name for token in ["vendor", "bundle", "embed.php", "api.js", "common.js", "util.js", "map.js", "marker.js"]):
        return None, "uncertain_vendor_blob", "generic_or_site_specific_bundle"
    return None, "uncertain_vendor_blob", "no_safe_mapping"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate vendor externalization candidates")
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--tasks", nargs="*", default=TASKS)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    candidates_path = args.out_dir / "vendor_externalize_candidates.jsonl"
    map_path = args.out_dir / "vendor_externalize_map.confirmed.json"
    summary_path = args.out_dir / "vendor_externalize_summary.json"
    md_path = args.out_dir / "vendor_externalize_summary.md"

    confirmed_map: dict[str, str] = {}
    reason_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    task_counts: dict[str, Counter[str]] = defaultdict(Counter)
    total_vendor_chars = 0
    total_confirmed_chars = 0

    with candidates_path.open("w", encoding="utf-8") as out:
        for task in args.tasks:
            path = args.release_root / "jsonl" / f"{task}.jsonl"
            if not path.exists():
                continue
            for _, record in load_jsonl(path, args.limit):
                audit = audit_record_resources(record)
                by_path = {normalize_resource_ref(item["path"]): item["code"] for item in _record_items(record)}
                for item in audit.vendor_or_blob_resources:
                    local_path = item["path"]
                    code = by_path.get(local_path, "")
                    cdn_url, status, reason = infer_cdn_url(local_path, code)
                    total_vendor_chars += item["size_chars"]
                    if cdn_url:
                        confirmed_map[local_path] = cdn_url
                        total_confirmed_chars += item["size_chars"]
                    status_counts[status] += 1
                    reason_counts[reason] += 1
                    task_counts[task][status] += 1
                    row = {
                        "release_task": task,
                        "instance_id": audit.instance_id,
                        "path": local_path,
                        "size_chars": item["size_chars"],
                        "status": status,
                        "reason": reason,
                        "cdn_url": cdn_url,
                    }
                    out.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    map_path.write_text(json.dumps(confirmed_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "release_root": str(args.release_root),
        "limit_per_task": args.limit,
        "candidate_rows": sum(status_counts.values()),
        "status_counts": dict(status_counts),
        "reason_counts": dict(reason_counts),
        "task_status_counts": {task: dict(counter) for task, counter in task_counts.items()},
        "total_vendor_chars": total_vendor_chars,
        "total_confirmed_externalizable_chars": total_confirmed_chars,
        "outputs": {
            "candidates_jsonl": str(candidates_path),
            "confirmed_map_json": str(map_path),
            "summary_json": str(summary_path),
            "summary_md": str(md_path),
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _record_items(record: dict[str, Any]) -> list[dict[str, str]]:
    from utils.webcoding_pipeline.release_resources import get_code_bearing_items

    return get_code_bearing_items(record)


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Vendor Externalization Candidates",
        "",
        f"- release_root: `{summary['release_root']}`",
        f"- candidate_rows: {summary['candidate_rows']}",
        f"- total_vendor_chars: {summary['total_vendor_chars']}",
        f"- confirmed_externalizable_chars: {summary['total_confirmed_externalizable_chars']}",
        "",
        "## Status Counts",
        "",
    ]
    for key, value in sorted(summary["status_counts"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Reason Counts", ""])
    for key, value in sorted(summary["reason_counts"].items()):
        lines.append(f"- {key}: {value}")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
