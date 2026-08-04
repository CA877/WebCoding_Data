#!/usr/bin/env python3
"""Check approximate training text lengths for WebCoding release JSONL files."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.webcoding_pipeline.release_resources import get_code_bearing_items, suffix_of  # noqa: E402

TASKS = [
    "text-generate",
    "text-edit",
    "text-repair",
    "image-generate",
    "image-edit",
    "image-repair",
]

TRAIN_CODE_EXTS = {".html", ".htm", ".css", ".js", ".jsx", ".ts", ".tsx"}


def iter_jsonl(path: Path, limit: int = 0):
    with path.open(encoding="utf-8", errors="ignore") as handle:
        for index, line in enumerate(handle, start=1):
            if limit and index > limit:
                break
            if line.strip():
                yield json.loads(line)


def text_len(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value)
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def instruction_chars(record: dict[str, Any]) -> int:
    instruction = record.get("instruction")
    if isinstance(instruction, dict) and "src_code" in instruction:
        shallow = {k: v for k, v in instruction.items() if k != "src_code"}
        return text_len(shallow)
    if isinstance(instruction, list):
        non_code_items = [
            item
            for item in instruction
            if not (isinstance(item, dict) and isinstance(item.get("code"), str))
        ]
        return text_len(non_code_items)
    return text_len(instruction)


def patch_chars(record: dict[str, Any]) -> int:
    value = record.get("response")
    if not isinstance(value, list):
        return 0
    total = 0
    for item in value:
        if not isinstance(item, dict):
            continue
        if "search" in item or "replace" in item:
            total += len(str(item.get("path", "")))
            total += len(str(item.get("search", "")))
            total += len(str(item.get("replace", "")))
    return total


def code_length_record(record: dict[str, Any]) -> dict[str, Any]:
    items = [
        item
        for item in get_code_bearing_items(record)
        if suffix_of(item["path"]) in TRAIN_CODE_EXTS
    ]
    ext_counts: Counter[str] = Counter()
    ext_chars: Counter[str] = Counter()
    for item in items:
        ext = suffix_of(item["path"]) or "<none>"
        ext_counts[ext] += 1
        ext_chars[ext] += len(item["code"])
    code_concat_chars = sum(len(item["code"]) for item in items)
    instr_chars = instruction_chars(record)
    patch_text_chars = patch_chars(record)
    return {
        "instance_id": record.get("instance_id", ""),
        "task": record.get("task", ""),
        "code_file_count": len(items),
        "code_concat_chars": code_concat_chars,
        "instruction_chars": instr_chars,
        "patch_chars": patch_text_chars,
        "training_text_chars": code_concat_chars + instr_chars + patch_text_chars,
        "ext_counts": dict(sorted(ext_counts.items())),
        "ext_chars": dict(sorted(ext_chars.items())),
    }


def percentile(values: list[int], q: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[int((len(ordered) - 1) * q)]


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"records": len(rows)}
    for key in ("code_concat_chars", "instruction_chars", "patch_chars", "training_text_chars", "code_file_count"):
        values = [int(row[key]) for row in rows]
        out[key] = {
            "min": min(values) if values else 0,
            "p50": percentile(values, 0.50),
            "p90": percentile(values, 0.90),
            "p95": percentile(values, 0.95),
            "p99": percentile(values, 0.99),
            "max": max(values) if values else 0,
            "mean": round(statistics.fmean(values), 2) if values else 0,
        }
    ext_counts: Counter[str] = Counter()
    ext_chars: Counter[str] = Counter()
    for row in rows:
        ext_counts.update(row["ext_counts"])
        ext_chars.update(row["ext_chars"])
    out["ext_counts"] = dict(sorted(ext_counts.items()))
    out["ext_chars"] = dict(sorted(ext_chars.items()))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Check release training lengths")
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--tasks", nargs="*", default=TASKS)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--top-k", type=int, default=50)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    detail_path = args.out_dir / "training_length_records.jsonl"
    top_path = args.out_dir / "training_length_top.jsonl"
    summary_path = args.out_dir / "training_length_summary.json"
    md_path = args.out_dir / "training_length_summary.md"

    by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    all_rows: list[dict[str, Any]] = []
    with detail_path.open("w", encoding="utf-8") as detail_out:
        for task in args.tasks:
            path = args.release_root / "jsonl" / f"{task}.jsonl"
            if not path.exists():
                continue
            for record in iter_jsonl(path, args.limit):
                row = {"release_task": task, **code_length_record(record)}
                by_task[task].append(row)
                all_rows.append(row)
                detail_out.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    top_rows = sorted(all_rows, key=lambda row: row["training_text_chars"], reverse=True)[: args.top_k]
    with top_path.open("w", encoding="utf-8") as top_out:
        for row in top_rows:
            top_out.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    summary = {
        "release_root": str(args.release_root),
        "limit_per_task": args.limit,
        "total_records": len(all_rows),
        "definition": {
            "code_concat_chars": "Concatenated embedded .html/.css/.js/.jsx/.ts/.tsx code used by the training sample.",
            "patch_chars": "For edit/repair, approximate length of response path/search/replace text.",
            "training_text_chars": "instruction_chars + code_concat_chars + patch_chars.",
        },
        "tasks": {task: summarize(rows) for task, rows in by_task.items()},
        "outputs": {
            "detail_jsonl": str(detail_path),
            "top_jsonl": str(top_path),
            "summary_json": str(summary_path),
            "summary_md": str(md_path),
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def fmt_stats(stats: dict[str, Any]) -> str:
    return "p50={p50}, p90={p90}, p95={p95}, max={max}".format(**stats)


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Training Length Check",
        "",
        f"- release_root: `{summary['release_root']}`",
        f"- total_records: {summary['total_records']}",
        f"- limit_per_task: {summary['limit_per_task']}",
        "",
        "| task | records | code_concat_chars | training_text_chars | patch_chars | code_file_count | ext_counts |",
        "|---|---:|---|---|---|---|---|",
    ]
    for task, data in summary["tasks"].items():
        lines.append(
            "| {task} | {records} | {code} | {training} | {patch} | {files} | {exts} |".format(
                task=task,
                records=data["records"],
                code=fmt_stats(data["code_concat_chars"]),
                training=fmt_stats(data["training_text_chars"]),
                patch=fmt_stats(data["patch_chars"]),
                files=fmt_stats(data["code_file_count"]),
                exts=", ".join(f"{k}:{v}" for k, v in data["ext_counts"].items()) or "-",
            )
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
