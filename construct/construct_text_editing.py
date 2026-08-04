#!/usr/bin/env python3
"""Construct paired text/image edit data using forward synthesis only."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from WebCoding_Data.construct.construct_common import (
    apply_search_replace_exact,
    append_jsonl,
    balanced_task_count,
    build_forward_edit_synthesizer,
    build_generation_data,
    choose_task_count,
    choose_task_types,
    ensure_api_env,
    existing_final_screenshots,
    iter_project_dirs,
    iter_project_list,
    iter_jsonl_records,
    load_edit_catalog,
    screenshot_project_to_dir,
    training_source_manifest,
)
from WebCoding_Data.construct.v2_records import edit_records


DESKTOP_VIEWPORT = [("desktop", 1920, 1080)]


def _absolute_screens(screens: list[dict], root: Path) -> list[dict]:
    return [{**item, "path": str((root / Path(item["path"]).name).resolve())} for item in screens]


def _process_one(project_dir: Path, args, synthesizer, all_task_types: list[str],
                 task_count: int | None = None) -> dict:
    """Process a single project. Returns a JSONL record."""
    try:
        generation_data = build_generation_data(project_dir)
        clean_code = generation_data["dst_code"]
        task_count = task_count or choose_task_count(
            args.min_tasks, args.max_tasks, args.seed, project_dir.name
        )
        task_types = choose_task_types(
            all_task_types, task_count, args.seed, project_dir.name,
        )
        task = synthesizer.generate_forward_pair(generation_data, task_types)
        src_code = clean_code
        dst_code = apply_search_replace_exact(src_code, task["label_modified_files"])
        screenshot_root = getattr(args, "screenshot_dir", None)
        if screenshot_root:
            instance_screens = screenshot_root / project_dir.name
            raw_screens = screenshot_project_to_dir(
                project_dir, instance_screens, getattr(args, "browser_proxy", ""),
                viewports=DESKTOP_VIEWPORT, full_page=False,
            )
            clean_screens = _absolute_screens(raw_screens, instance_screens)
        else:
            clean_screens = existing_final_screenshots(project_dir)
        images = {"src_screenshot": clean_screens, "dst_screenshot": []}

        return {
            "instance_id": project_dir.name,
            "source_project": str(project_dir.resolve()),
            "task": "text-editing",
            "status": "ok",
            "construction_strategy": "forward",
            "task_type": task["task_type"],
            "description": task["description"],
            "instruction": {"src_code": src_code, "description": task["description"],
                            "source_manifest": training_source_manifest(project_dir)},
            "reference": {"dst_code": dst_code},
            "label_modified_files": task["label_modified_files"],
            # Only the original clean project has a reviewed render at this stage.
            "images": images,
            "llm_response": task.get("llm_raw_response", ""),
            "llm_metadata": task.get("llm_metadata", {}),
            "prompt_tokens": generation_data.get("prompt_tokens", 0),
            "input_contract": generation_data.get("input_contract", {}),
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
    parser.add_argument("--min-tasks", type=int, default=1)
    parser.add_argument("--max-tasks", type=int, default=7)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--max-output-tokens", type=int, default=8_192)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--screenshot-dir", type=Path,
                        help="Paired image-edit assets; defaults to <output-dir>/edit_screenshots.")
    parser.add_argument("--browser-proxy", default="http://127.0.0.1:7890")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if bool(args.input_dir) == bool(args.project_list):
        parser.error("provide exactly one of --input-dir or --project-list")
    if args.min_tasks < 1 or args.max_tasks > 7 or args.max_tasks < args.min_tasks:
        parser.error("task range must satisfy 1 <= min-tasks <= max-tasks <= 7")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.screenshot_dir = args.screenshot_dir or (args.output_dir / "edit_screenshots")
    out_jsonl = args.output_dir / "records.jsonl"
    text_v2_jsonl = args.output_dir / "text-edit.v2.jsonl"
    image_v2_jsonl = args.output_dir / "image-edit.v2.jsonl"

    if args.overwrite:
        for path in (out_jsonl, text_v2_jsonl, image_v2_jsonl):
            if path.exists():
                path.unlink()

    # Resume support also repairs an interrupted multi-file append.
    done_ids: set[str] = set()
    if out_jsonl.exists():
        text_ids = ({str(rec.get("instance_id")) for rec in iter_jsonl_records(text_v2_jsonl, ignore_invalid=True)}
                    if text_v2_jsonl.exists() else set())
        image_ids = ({str(rec.get("instance_id")) for rec in iter_jsonl_records(image_v2_jsonl, ignore_invalid=True)}
                     if image_v2_jsonl.exists() else set())
        for rec in iter_jsonl_records(out_jsonl, ignore_invalid=True):
            if rec.get("status") == "ok":
                instance_id = str(rec["instance_id"])
                text_record, image_record = edit_records(rec)
                if instance_id not in text_ids:
                    append_jsonl(text_v2_jsonl, text_record)
                    text_ids.add(instance_id)
                if instance_id not in image_ids:
                    append_jsonl(image_v2_jsonl, image_record)
                    image_ids.add(instance_id)
                done_ids.add(instance_id)
        print(f"Resuming: {len(done_ids)} already done")

    api_key, base_url, model = ensure_api_env(prefer_vision=False)
    all_task_types, _ = load_edit_catalog()
    synthesizer = build_forward_edit_synthesizer(
        api_key, base_url, model,
        max_retries=args.max_retries,
        max_tokens=args.max_output_tokens,
    )
    projects = (iter_project_list(args.project_list, args.limit, args.offset)
                if args.project_list else iter_project_dirs(args.input_dir, args.limit, args.offset))
    assigned = [
        (p, balanced_task_count(index, args.seed, args.min_tasks, args.max_tasks))
        for index, p in enumerate(projects) if p.name not in done_ids
    ]
    total = len(assigned)
    print(f"text/image-editing (forward): {total} projects, {args.workers} worker(s)")

    done = 0
    ok = 0
    errors = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(_process_one, p, args, synthesizer, all_task_types, count): p
            for p, count in assigned
        }
        for future in as_completed(futures):
            result = future.result()
            append_jsonl(out_jsonl, result)
            if result["status"] == "ok":
                text_record, image_record = edit_records(result)
                append_jsonl(text_v2_jsonl, text_record)
                append_jsonl(image_v2_jsonl, image_record)
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
