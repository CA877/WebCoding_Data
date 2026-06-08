#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from WebCoding_Data.construct.construct_common import (
    append_jsonl,
    base_info,
    build_file_manifest,
    collect_resources,
    copy_project,
    generate_prd_from_code,
    infer_page_bucket,
    info_to_training_record,
    iter_project_dirs,
    read_code_bundle,
    safe_write_json,
)


def _process_one(project_dir: Path, args) -> dict:
    """Process a single project. Returns manifest record."""
    instance_dir = args.output_dir / project_dir.name
    if instance_dir.exists():
        if not args.overwrite:
            return {"instance_id": project_dir.name, "status": "skip_existing"}
        shutil.rmtree(instance_dir)
    instance_dir.mkdir(parents=True, exist_ok=True)
    try:
        instruction = generate_prd_from_code(project_dir)
        copy_project(project_dir, instance_dir / "dst")

        info = base_info(project_dir.name, "text-generation")
        info["page_type"] = infer_page_bucket(project_dir)
        info["instruction"] = instruction
        info["dst_code"] = read_code_bundle(project_dir, code_only=True)
        info["file_manifest"] = build_file_manifest(project_dir)
        info["resources"] = collect_resources(project_dir)
        info["meta"] = {"source_project": str(project_dir)}
        safe_write_json(instance_dir / "info.json", info)
        return {"instance_id": project_dir.name, "status": "ok", "_info": info}
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(instance_dir, ignore_errors=True)
        return {"instance_id": project_dir.name, "status": "error", "error": f"{type(exc).__name__}: {exc}"}


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
    manifest = args.output_dir / "manifest_text_generation.jsonl"
    train_jsonl = args.output_dir / "text-generation.jsonl"
    projects = iter_project_dirs(args.input_dir, args.limit, args.offset)
    total = len(projects)
    print(f"text-generation: {total} projects, {args.workers} worker(s)")

    done = 0
    ok = 0
    errors = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_process_one, p, args): p for p in projects}
        for future in as_completed(futures):
            project_dir = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001
                result = {"instance_id": project_dir.name, "status": "error", "error": f"Worker crash: {exc}"}
            # 写 manifest（不含 _info）
            manifest_record = {k: v for k, v in result.items() if k != "_info"}
            append_jsonl(manifest, manifest_record)
            # 写训练 JSONL
            if result.get("_info"):
                record = info_to_training_record(result["_info"])
                if record:
                    append_jsonl(train_jsonl, record)
            done += 1
            status = result["status"]
            if status == "ok":
                ok += 1
            elif status == "error":
                errors += 1
            tag = f" — {result['error'][:80]}" if status == "error" else ""
            print(f"  [{done}/{total}] {result['instance_id']}: {status}{tag}")
    print(f"text-generation done: {ok} ok, {errors} errors, {done - ok - errors} skipped")


if __name__ == "__main__":
    main()
