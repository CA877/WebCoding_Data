#!/usr/bin/env python3
"""Merge ShareGPT jsonl files and tag every row with a source attribute.

Writes <backup> as an untouched copy of <base>, then writes <output> as
base rows (tagged with --base-source) followed by <extra> rows (which must
already carry a "source" field).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


def stream_rows(path: Path):
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"parse error {path}:{line_no}: {exc}", file=sys.stderr)
                raise SystemExit(2)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", type=Path, required=True)
    ap.add_argument("--extra", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--backup", type=Path, required=True)
    ap.add_argument("--base-source", default="webcompass_step5")
    args = ap.parse_args()

    args.backup.parent.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    # untouched backup of the original base file
    import shutil
    try:
        shutil.copyfile(args.base, args.backup)
    except shutil.SameFileError:
        pass

    base_ids, extra_ids = set(), set()
    base_count = extra_count = 0
    tmp_out = args.output.with_name(args.output.name + ".tmp")
    with tmp_out.open("w", encoding="utf-8") as out:
        for row in stream_rows(args.base):
            row["source"] = args.base_source
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            base_ids.add(row.get("id"))
            base_count += 1
        for row in stream_rows(args.extra):
            if "source" not in row:
                print("extra row missing source: %s" % row.get("id"), file=sys.stderr)
                return 3
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            extra_ids.add(row.get("id"))
            extra_count += 1
    import os
    os.replace(tmp_out, args.output)

    overlap = base_ids & extra_ids
    print(f"base={base_count} extra={extra_count} total={base_count + extra_count}")
    print(f"base unique ids={len(base_ids)} extra unique ids={len(extra_ids)} id overlap={len(overlap)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
