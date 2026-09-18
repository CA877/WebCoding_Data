#!/usr/bin/env python3
"""Audit referenced release images without comparing before/after screenshots."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any


IMAGE_ROOT_BY_FILE = {
    "image-generate.jsonl": Path("images/image-generate"),
    "image-edit.jsonl": Path("images/image-edit"),
    "image-repair.jsonl": Path("images/image-repair"),
}


def read_jsonl(path: Path):
    with path.open("rb") as handle:
        for line_no, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            yield line_no, json.loads(raw)


def image_refs(record: dict[str, Any]) -> list[tuple[str, str]]:
    out = []
    for key in ("input_images", "src_screenshot", "dst_screenshot"):
        for value in record.get(key) or []:
            if isinstance(value, str):
                out.append((key, value))
    return out


def image_issues(path: Path) -> list[str]:
    issues = []
    if not path.exists():
        return ["missing"]
    size = path.stat().st_size
    if size == 0:
        return ["empty_file"]
    if size < 2048:
        issues.append("very_small_file_lt_2kb")
    try:
        from PIL import Image, ImageStat
    except Exception:
        return issues
    try:
        with Image.open(path) as im:
            width, height = im.size
            if width < 200 or height < 150:
                issues.append("small_dimensions")
            sample = im.convert("L").resize((64, 64))
            stat = ImageStat.Stat(sample)
            mean = stat.mean[0]
            stddev = stat.stddev[0]
            if stddev < 3:
                issues.append("nearly_solid")
            if mean > 248:
                issues.append("nearly_all_white")
            if mean < 7:
                issues.append("nearly_all_black")
    except Exception:
        issues.append("decode_failed")
    return issues


@dataclass
class Stats:
    samples: int = 0
    image_refs: int = 0
    issue_counts: Counter[str] = field(default_factory=Counter)
    sample_issue_counts: Counter[str] = field(default_factory=Counter)
    examples: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stats: dict[str, Stats] = {}
    sample_rows = []

    for jsonl_name, image_root in IMAGE_ROOT_BY_FILE.items():
        path = args.release_root / "jsonl" / jsonl_name
        task_stats = Stats()
        stats[jsonl_name] = task_stats
        for line_no, record in read_jsonl(path):
            task_stats.samples += 1
            sample_id = record.get("instance_id") or f"{jsonl_name}:{line_no}"
            per_sample = set()
            refs = image_refs(record)
            if not refs:
                per_sample.add("no_image_refs")
            for key, rel in refs:
                task_stats.image_refs += 1
                full = args.release_root / image_root / rel
                for issue in image_issues(full):
                    name = f"{key}_{issue}"
                    task_stats.issue_counts[name] += 1
                    per_sample.add(name)
                    if len(task_stats.examples[name]) < 20:
                        task_stats.examples[name].append(str(sample_id))
            for issue in sorted(per_sample):
                task_stats.sample_issue_counts[issue] += 1
            if per_sample:
                sample_rows.append({"file": jsonl_name, "instance_id": sample_id, "issues": sorted(per_sample)})

    report = {
        "release_root": str(args.release_root),
        "files": {
            name: {
                "samples": s.samples,
                "image_refs": s.image_refs,
                "issue_counts": dict(s.issue_counts.most_common()),
                "sample_issue_counts": dict(s.sample_issue_counts.most_common()),
                "examples": dict(s.examples),
            }
            for name, s in stats.items()
        },
    }
    (args.out_dir / "image_only_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (args.out_dir / "image_only_sample_issues.jsonl").open("w", encoding="utf-8") as handle:
        for row in sample_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    lines = ["# Image Only Audit", ""]
    for name, s in stats.items():
        lines.extend(["", f"## {name}", "", "| issue | image refs | sample count | examples |", "|---|---:|---:|---|"])
        all_issues = set(s.issue_counts) | set(s.sample_issue_counts)
        for issue in sorted(all_issues, key=lambda x: (-s.sample_issue_counts.get(x, 0), x)):
            examples = ", ".join(f"`{x}`" for x in s.examples.get(issue, [])[:6])
            lines.append(
                f"| `{issue}` | {s.issue_counts.get(issue, 0)} | "
                f"{s.sample_issue_counts.get(issue, 0)} ({s.sample_issue_counts.get(issue, 0) / s.samples:.2%}) | {examples} |"
            )
    (args.out_dir / "image_only_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"out_dir": str(args.out_dir)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
