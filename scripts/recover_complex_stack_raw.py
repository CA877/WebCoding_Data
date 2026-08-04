#!/usr/bin/env python3
"""Recover valid multi-root projects previously rejected by strict parsing."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.solve_complex_stack_cases import parse, write_project


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    rows = {
        row["job_id"]: row
        for row in (json.loads(line) for line in args.input.read_text().splitlines() if line.strip())
    }
    recovered, failed = [], []
    for raw in sorted((args.output_dir / "raw_failures").glob("complex-*.txt")):
        job_id = raw.stem
        target = args.output_dir / "projects" / job_id / ".generation.json"
        if target.exists() or job_id not in rows:
            continue
        try:
            files = parse(raw.read_text(encoding="utf-8"))
            write_project(
                args.output_dir, rows[job_id], files,
                model="qwen3.7-max", usage=None, enable_thinking=False,
            )
            recovered.append({"job_id": job_id, "files": len(files)})
        except Exception as exc:  # noqa: BLE001
            failed.append({"job_id": job_id, "error": f"{type(exc).__name__}: {exc}"})
    report = {"recovered": recovered, "failed": failed}
    (args.output_dir / "raw_recovery_results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"recovered": len(recovered), "failed": len(failed)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
