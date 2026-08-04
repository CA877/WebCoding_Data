#!/usr/bin/env python3
"""Construct text-editing data with forward synthesis by default.

Forward: extend an existing page with new features.
Reverse: remove existing features, then train the model to restore them.
Output is a single JSONL file, one line per project.
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
    apply_search_replace_local,
    append_jsonl,
    build_forward_edit_synthesizer,
    build_generation_data,
    build_reverse_edit_synthesizer,
    choose_task_count,
    choose_task_types,
    ensure_api_env,
    existing_final_screenshots,
    iter_project_dirs,
    iter_project_list,
    load_edit_catalog,
    training_source_manifest,
    _apply_patches_reverse,
)


def _process_one(project_dir: Path, args, synthesizer, all_task_types: list[str]) -> dict:
    """Process a single project. Returns a JSONL record."""
    try:
        generation_data = build_generation_data(project_dir)
        clean_code = generation_data["dst_code"]
        if args.strategy == "forward":
            task_types = choose_task_types(
                all_task_types,
                (args.min_tasks, args.max_tasks),
                args.seed,
                project_dir.name,
            )
            task = synthesizer.generate_forward_pair(generation_data, task_types)
            src_code = clean_code
            dst_code, _ = apply_search_replace_local(
                src_code, task["label_modified_files"], strict_mode=True
            )
            images = {
                "src_screenshot": existing_final_screenshots(project_dir),
                "dst_screenshot": [],
            }
        else:
            n_features = choose_task_count(
                args.min_tasks, args.max_tasks, args.seed, project_dir.name
            )
            task = synthesizer.generate_reverse_pair(generation_data, n_features)
            src_code = _apply_patches_reverse(clean_code, task["label_modified_files"])
            dst_code = clean_code
            images = {
                "src_screenshot": [],
                "dst_screenshot": existing_final_screenshots(project_dir),
            }

        return {
            "instance_id": project_dir.name,
            "source_project": str(project_dir.resolve()),
            "task": "text-editing",
            "status": "ok",
            "construction_strategy": args.strategy,
            "task_type": task["task_type"],
            "description": task["description"],
            "instruction": {"src_code": src_code, "description": task["description"],
                            "source_manifest": training_source_manifest(project_dir)},
            "reference": {"dst_code": dst_code},
            "label_modified_files": task["label_modified_files"],
            # Only the original clean project has a reviewed render at this stage.
            "images": images,
            "llm_response": task.get("llm_raw_response", ""),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "instance_id": project_dir.name,
            "task": "text-editing",
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, help="Project directory root (mutually exclusive with --project-list).")
    parser.add_argument("--project-list", type=Path, help="One absolute project path per line; use for fixed batch splits.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--min-tasks", type=int, default=2)
    parser.add_argument("--max-tasks", type=int, default=10)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--max-output-tokens", type=int, default=8_192)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--strategy",
        choices=("forward", "reverse"),
        default="forward",
        help="forward adds new features to the input project (default); reverse removes and restores existing features",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if bool(args.input_dir) == bool(args.project_list):
        parser.error("provide exactly one of --input-dir or --project-list")
    if args.min_tasks < 2 or args.max_tasks < args.min_tasks:
        parser.error("--min-tasks must be >=2 and <= --max-tasks")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_jsonl = args.output_dir / "records.jsonl"

    # Resume support
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

    api_key, base_url, model = ensure_api_env(prefer_vision=False)
    all_task_types, _ = load_edit_catalog()
    if args.strategy == "forward":
        synthesizer = build_forward_edit_synthesizer(
            api_key, base_url, model,
            max_retries=args.max_retries,
            max_tokens=args.max_output_tokens,
        )
    else:
        synthesizer = build_reverse_edit_synthesizer(
            api_key, base_url, model,
            max_retries=args.max_retries,
            max_tokens=args.max_output_tokens,
        )
    projects = (iter_project_list(args.project_list, args.limit, args.offset)
                if args.project_list else iter_project_dirs(args.input_dir, args.limit, args.offset))
    projects = [p for p in projects if p.name not in done_ids]
    total = len(projects)
    print(f"text-editing ({args.strategy}): {total} projects, {args.workers} worker(s)")

    done = 0
    ok = 0
    errors = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(_process_one, p, args, synthesizer, all_task_types): p
            for p in projects
        }
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
    print(f"text-editing done: {ok} ok, {errors} errors, {done - ok - errors} skipped")


if __name__ == "__main__":
    main()
