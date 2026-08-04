#!/usr/bin/env python3
"""Count likely non zh/en HTML lang attributes in JSONL records."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


PATTERNS = {
    "any_lang_attr": r"lang=\\?['\"][A-Za-z][A-Za-z0-9_-]*",
    "likely_non_zh_en_lang_attr": r"lang=\\?['\"](?!en|zh|zh-CN|zh-Hans|zh-Hant)[A-Za-z][A-Za-z0-9_-]*",
}


def grep_count(path: Path, pattern: str) -> int:
    proc = subprocess.run(
        ["grep", "-P", "-i", "-c", pattern, str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    return int(proc.stdout.strip() or 0)


def line_count(path: Path) -> int:
    return int(subprocess.check_output(["wc", "-l", str(path)]).split()[0])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    files = []
    for path in args.paths:
        if path.is_dir():
            files.extend(sorted(path.glob("*.jsonl")))
        else:
            files.append(path)

    rows = []
    for path in files:
        total = line_count(path)
        row = {"file": str(path), "name": path.name, "total": total}
        for key, pattern in PATTERNS.items():
            count = grep_count(path, pattern)
            row[key] = count
            row[key + "_ratio"] = count / total if total else 0.0
        rows.append(row)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "lang_attr_counts.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Language Attribute Counts",
        "",
        "| file | total | any lang attr | likely non zh/en lang attr |",
        "|---|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| `{row['name']}` | {row['total']} | "
            f"{row['any_lang_attr']} ({row['any_lang_attr_ratio']:.2%}) | "
            f"{row['likely_non_zh_en_lang_attr']} ({row['likely_non_zh_en_lang_attr_ratio']:.2%}) |"
        )
    (args.out_dir / "lang_attr_counts.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"out_dir": str(args.out_dir), "files": len(files)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
