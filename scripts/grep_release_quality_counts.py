#!/usr/bin/env python3
"""Use grep to count common release-quality issues in huge JSONL files."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


PATTERNS = {
    "adult_sensitive": r"(^|[^a-z])(adult|porn|porno|sex|xxx|escort|escorts|dating|casino|gambling|betting|call-girls|callgirls|webcam|nude|erotic|hookup|bdsm)([^a-z]|$)",
    "challenge_captcha": r"captcha|cloudflare|access denied|checking your browser|are you human|security check",
    "placeholder_parked": r"lorem ipsum|domain for sale|parked domain|under construction|coming soon|buy this domain",
    "remote_url": r"https?://|//[A-Za-z0-9.-]+",
    "has_input_files": r'"input_files"',
    "has_dst_screenshot": r'"dst_screenshot"',
}


def grep_count(path: Path, pattern: str) -> int:
    proc = subprocess.run(
        ["grep", "-E", "-i", "-c", pattern, str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    try:
        return int(proc.stdout.strip() or 0)
    except ValueError:
        return 0


def line_count(path: Path) -> int:
    return int(subprocess.check_output(["wc", "-l", str(path)]).split()[0])


def cell(row: dict, key: str) -> str:
    return f"{row[key]} ({row[key + '_ratio']:.2%})"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    files: list[Path] = []
    for path in args.paths:
        if path.is_dir():
            files.extend(sorted(path.glob("*.jsonl")))
        else:
            files.append(path)

    rows = []
    for path in files:
        total = line_count(path)
        row: dict[str, object] = {"file": str(path), "name": path.name, "total": total}
        for key, pattern in PATTERNS.items():
            count = grep_count(path, pattern)
            row[key] = count
            row[key + "_ratio"] = count / total if total else 0.0
        row["missing_input_files"] = total - int(row["has_input_files"])
        row["missing_input_files_ratio"] = row["missing_input_files"] / total if total else 0.0
        row["missing_dst_screenshot"] = total - int(row["has_dst_screenshot"])
        row["missing_dst_screenshot_ratio"] = row["missing_dst_screenshot"] / total if total else 0.0
        rows.append(row)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "grep_counts.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Grep-Based Full Release Counts",
        "",
        "| file | total | adult/sensitive | challenge | placeholder | remote URL | missing input_files | missing dst_screenshot |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| `{row['name']}` | {row['total']} | {cell(row, 'adult_sensitive')} | "
            f"{cell(row, 'challenge_captcha')} | {cell(row, 'placeholder_parked')} | "
            f"{cell(row, 'remote_url')} | {row['missing_input_files']} ({row['missing_input_files_ratio']:.2%}) | "
            f"{row['missing_dst_screenshot']} ({row['missing_dst_screenshot_ratio']:.2%}) |"
        )
    lines.extend(
        [
            "",
            "Notes:",
            "- Counts are line-level full-release scans over JSONL records.",
            "- They are intentionally conservative: a hit anywhere in code, metadata, image path, or instruction marks the sample.",
            "- `missing_input_files` is expected for lightweight text release files, but means patch uniqueness cannot be checked from that release JSONL.",
        ]
    )
    (args.out_dir / "grep_counts.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"out_dir": str(args.out_dir), "files": len(files)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
