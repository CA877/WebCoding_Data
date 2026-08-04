#!/usr/bin/env python3
"""Text-repair task: LLM injects defects → flip patches to repair direction.

Output: a single JSONL file, one line per project.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import tempfile
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from WebCoding_Data.construct.construct_common import (
    append_jsonl,
    build_generation_data,
    build_repair_synthesizer,
    choose_task_count,
    choose_task_types,
    ensure_api_env,
    existing_final_screenshots,
    iter_project_dirs,
    iter_project_list,
    iter_jsonl_records,
    load_repair_catalog,
    _apply_patches_reverse,
    screenshot_project_to_dir,
    training_source_manifest,
    write_code_bundle_from_source,
)

# Text-repair only needs a single desktop render of the injected defect.  The
# tablet/mobile variants and the clean-vs-defective visual delta are not part
# of the text-repair training contract.
DESKTOP_VIEWPORT = [("desktop", 1920, 1080)]


def _process_one(project_dir: Path, args, synthesizer, all_task_types) -> dict:
    """Process a single project. Returns a JSONL record."""
    try:
        generation_data = build_generation_data(project_dir)
        task_count = choose_task_count(args.min_tasks, min(args.max_tasks, len(all_task_types)), args.seed, project_dir.name)
        task_types = choose_task_types(all_task_types, task_count, args.seed, project_dir.name, allow_repeat=False)
        task = synthesizer.generate_defect_task(generation_data, task_types)
        if not task:
            raise RuntimeError("repair generation returned None")

        defective_code = _apply_patches_reverse(generation_data["dst_code"], task["label_modified_files"])
        # The JSONL belongs to text-repair, while the injected-defect render is
        # a single desktop screenshot.  Keep the storage root separate so
        # downstream consumers do not confuse a code-only record with its
        # visual pair.
        defect_root = args.defect_screenshot_dir or (args.output_dir / "repair_defect_screenshots")
        defect_dir = defect_root / project_dir.name
        with tempfile.TemporaryDirectory() as temp:
            broken = Path(temp) / "broken"
            write_code_bundle_from_source(project_dir, defective_code, broken)
            raw_screens = screenshot_project_to_dir(broken, defect_dir, args.browser_proxy,
                                                    viewports=DESKTOP_VIEWPORT)
        defect_screens = [{**item, "path": str((defect_dir / Path(item["path"]).name).resolve())}
                          for item in raw_screens]
        return {
            "instance_id": project_dir.name,
            "source_project": str(project_dir.resolve()),
            "task": "text-repair",
            "status": "ok",
            "task_type": task_types,
            "description": task["description"],
            "instruction": {"src_code": defective_code, "description": task["description"],
                            "source_manifest": training_source_manifest(project_dir)},
            "reference": {"dst_code": generation_data["dst_code"]},
            "label_modified_files": task["label_modified_files"],
            "images": {"src_screenshot": defect_screens, "dst_screenshot": existing_final_screenshots(project_dir)},
            "llm_response": task.get("llm_raw_response", ""),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "instance_id": project_dir.name,
            "task": "text-repair",
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
    parser.add_argument("--browser-proxy", default="http://127.0.0.1:7890")
    parser.add_argument("--defect-screenshot-dir", type=Path,
                        help="Image-repair asset root; defaults to <output-dir>/repair_defect_screenshots for direct CLI compatibility.")
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
        for rec in iter_jsonl_records(out_jsonl, ignore_invalid=True):
            if rec.get("status") == "ok":
                done_ids.add(rec["instance_id"])
        print(f"Resuming: {len(done_ids)} already done")

    api_key, base_url, model = ensure_api_env(prefer_vision=False)
    synthesizer = build_repair_synthesizer(api_key, base_url, model, max_retries=args.max_retries,
                                           max_tokens=args.max_output_tokens)
    all_task_types, _ = load_repair_catalog()
    projects = (iter_project_list(args.project_list, args.limit, args.offset)
                if args.project_list else iter_project_dirs(args.input_dir, args.limit, args.offset))
    projects = [p for p in projects if p.name not in done_ids]
    total = len(projects)
    print(f"text-repair: {total} projects, {args.workers} worker(s)")

    done = 0
    ok = 0
    errors = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_process_one, p, args, synthesizer, all_task_types): p for p in projects}
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
    print(f"text-repair done: {ok} ok, {errors} errors, {done - ok - errors} skipped")


if __name__ == "__main__":
    main()
