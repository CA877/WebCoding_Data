#!/usr/bin/env python3
"""Count risky domains/paths from instance_id fields in huge JSONL files."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


INSTANCE_ID_RE = r'"instance_id":"[^"]+"'
RISK_RE = re.compile(
    r"(^|[^a-z])(adult|porn|porno|sex|xxx|escort|escorts|dating|casino|gambling|betting|call-girls|callgirls|webcam|nude|erotic|hookup|bdsm)([^a-z]|$)",
    re.I,
)


def line_count(path: Path) -> int:
    return int(subprocess.check_output(["wc", "-l", str(path)]).split()[0])


def instance_ids(path: Path) -> list[str]:
    proc = subprocess.run(
        ["grep", "-aoE", INSTANCE_ID_RE, str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    values = []
    for line in proc.stdout.splitlines():
        try:
            values.append(line.split(":", 1)[1].strip().strip('"'))
        except Exception:
            pass
    return values


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
        risky = [value for value in instance_ids(path) if RISK_RE.search(value)]
        rows.append(
            {
                "file": str(path),
                "name": path.name,
                "total": total,
                "risky_instance_id": len(risky),
                "risky_instance_id_ratio": len(risky) / total if total else 0.0,
                "examples": risky[:50],
            }
        )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "id_risk_counts.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Instance ID Risk Counts",
        "",
        "| file | total | risky instance_id | examples |",
        "|---|---:|---:|---|",
    ]
    for row in rows:
        examples = ", ".join(row["examples"][:8])
        lines.append(
            f"| `{row['name']}` | {row['total']} | {row['risky_instance_id']} ({row['risky_instance_id_ratio']:.2%}) | `{examples}` |"
        )
    (args.out_dir / "id_risk_counts.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"out_dir": str(args.out_dir), "files": len(files)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
