#!/usr/bin/env python3
"""Text-generation task: LLM reads project code → outputs PRD.

Output: a single JSONL file, one line per project.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from WebCoding_Data.construct.construct_common import (
    append_jsonl,
    generate_prd_from_code,
    iter_project_dirs,
)


def _process_one(project_dir: Path, args) -> dict:
    """Process a single project. Returns a JSONL record."""
    try:
        prd = generate_prd_from_code(project_dir)
        return {
            "instance_id": project_dir.name,
            "task": "text-generation",
            "status": "ok",
            "llm_response": prd,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "instance_id": project_dir.name,
            "task": "text-generation",
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_jsonl = args.output_dir / "text-generation.jsonl"

    # Skip already-done instances (resume support)
    done_ids: set[str] = set()
    if not args.overwrite and out_jsonl.exists():
        import json
        for line in out_jsonl.read_text().splitlines():
            if line.strip():
                try:
                    rec = json.loads(line)
                    if rec.get("status") == "ok":
                        done_ids.add(rec["instance_id"])
                except json.JSONDecodeError:
                    pass
        print(f"Resuming: {len(done_ids)} already done")

    projects = iter_project_dirs(args.input_dir, args.limit, args.offset)
    projects = [p for p in projects if p.name not in done_ids]
    total = len(projects)
    print(f"text-generation: {total} projects, {args.workers} worker(s)")

    done = 0
    ok = 0
    errors = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_process_one, p, args): p for p in projects}
        for future in as_completed(futures):
            result = future.result()
            append_jsonl(out_jsonl, result)
            done += 1
            status = result["status"]
            if status == "ok":
                ok += 1
            elif status == "error":
                errors += 1
            tag = f" — {result.get('error', '')[:80]}" if status == "error" else ""
            print(f"  [{done}/{total}] {result['instance_id']}: {status}{tag}")
    print(f"text-generation done: {ok} ok, {errors} errors, {done - ok - errors} skipped")


if __name__ == "__main__":
    main()
