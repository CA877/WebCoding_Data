#!/usr/bin/env python3
"""Text-repair task: LLM injects defects → flip patches to repair direction.

Output: a single JSONL file, one line per project.
"""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import tempfile
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from WebCoding_Data.construct.construct_common import (
    append_jsonl,
    balanced_task_count,
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
    repair_visual_difference,
    screenshot_project_to_dir,
    training_source_manifest,
    write_code_bundle_from_source,
)
from WebCoding_Data.construct.v2_records import repair_records

# Text-repair only needs a single desktop render of the injected defect.  The
# tablet/mobile variants and the clean-vs-defective visual delta are not part
# of the text-repair training contract.
DESKTOP_VIEWPORT = [("desktop", 1920, 1080)]


def _absolute_screens(screens: list[dict], root: Path) -> list[dict]:
    return [{**item, "path": str((root / Path(item["path"]).name).resolve())} for item in screens]


def _process_one(project_dir: Path, args, synthesizer, all_task_types,
                 task_count: int | None = None) -> dict:
    """Process a single project. Returns a JSONL record."""
    try:
        generation_data = build_generation_data(project_dir)
        task_count = task_count or choose_task_count(
            args.min_tasks, min(args.max_tasks, len(all_task_types)), args.seed, project_dir.name
        )
        task_types = choose_task_types(all_task_types, task_count, args.seed, project_dir.name, allow_repeat=False)
        task = synthesizer.generate_defect_task(generation_data, task_types)
        if not task:
            raise RuntimeError("repair generation returned None")

        defective_code = task["defective_code"]
        defective_full_code = task["defective_full_code"]
        defect_root = args.defect_screenshot_dir or (args.output_dir / "repair_defect_screenshots")
        defect_dir = defect_root / project_dir.name
        clean_dir = args.clean_screenshot_dir / project_dir.name
        raw_clean = screenshot_project_to_dir(
            project_dir, clean_dir, args.browser_proxy,
            viewports=DESKTOP_VIEWPORT, full_page=False,
        )
        with tempfile.TemporaryDirectory() as temp:
            broken = Path(temp) / "broken"
            write_code_bundle_from_source(project_dir, defective_full_code, broken)
            raw_screens = screenshot_project_to_dir(broken, defect_dir, args.browser_proxy,
                                                    viewports=DESKTOP_VIEWPORT, full_page=False)
        clean_screens = _absolute_screens(raw_clean, clean_dir)
        defect_screens = _absolute_screens(raw_screens, defect_dir)
        visual = repair_visual_difference(
            clean_screens, defect_screens, minimum_ratio=0.0, channel_threshold=8
        )
        # A second clean render detects animation/network nondeterminism.  A
        # visually unstable page may remain text-repair, but must not pass the
        # 1% image-repair gate because of unrelated frame drift.
        with tempfile.TemporaryDirectory() as stability_temp:
            stability_dir = Path(stability_temp) / project_dir.name
            raw_repeat = screenshot_project_to_dir(
                project_dir, stability_dir, args.browser_proxy,
                viewports=DESKTOP_VIEWPORT, full_page=False,
            )
            repeat_screens = _absolute_screens(raw_repeat, stability_dir)
            stability = repair_visual_difference(
                clean_screens, repeat_screens, minimum_ratio=0.0, channel_threshold=8
            )
        visual["clean_rerender_max_changed_ratio"] = stability["max_changed_ratio"]
        image_repair_eligible = (
            visual["max_changed_ratio"] >= args.minimum_changed_ratio
            and stability["max_changed_ratio"] <= args.maximum_clean_rerender_ratio
        )
        return {
            "instance_id": project_dir.name,
            "source_project": str(project_dir.resolve()),
            "task": "text-repair",
            "status": "ok",
            "task_type": task_types,
            "description": task["description"],
            # Release v2 text-repair has no task query: only broken input code.
            "instruction": defective_code,
            "reference": {"dst_code": generation_data["dst_code"]},
            "label_modified_files": task["label_modified_files"],
            "images": {"src_screenshot": defect_screens, "dst_screenshot": clean_screens},
            "visual_difference": visual,
            "image_repair_eligible": image_repair_eligible,
            "llm_response": task.get("llm_raw_response", ""),
            "llm_metadata": task.get("llm_metadata", {}),
            "prompt_tokens": generation_data.get("prompt_tokens", 0),
            "input_contract": generation_data.get("input_contract", {}),
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
    parser.add_argument("--min-tasks", type=int, default=1)
    parser.add_argument("--max-tasks", type=int, default=7)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--max-output-tokens", type=int, default=8_192)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--browser-proxy", default="http://127.0.0.1:7890")
    parser.add_argument("--defect-screenshot-dir", type=Path,
                        help="Image-repair asset root; defaults to <output-dir>/repair_defect_screenshots for direct CLI compatibility.")
    parser.add_argument("--clean-screenshot-dir", type=Path,
                        help="Clean pair assets; defaults to <output-dir>/repair_clean_screenshots.")
    parser.add_argument("--minimum-changed-ratio", type=float, default=0.01)
    parser.add_argument("--maximum-clean-rerender-ratio", type=float, default=0.002)
    parser.add_argument("--image-repair-target", type=int, default=0,
                        help="Stop scheduling new projects after this many v2 image-repair records; zero scans all.")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if bool(args.input_dir) == bool(args.project_list):
        parser.error("provide exactly one of --input-dir or --project-list")
    if args.min_tasks < 1 or args.max_tasks > 7 or args.max_tasks < args.min_tasks:
        parser.error("task range must satisfy 1 <= min-tasks <= max-tasks <= 7")
    if not 0 <= args.minimum_changed_ratio <= 1:
        parser.error("--minimum-changed-ratio must be between 0 and 1")
    if not 0 <= args.maximum_clean_rerender_ratio <= 1:
        parser.error("--maximum-clean-rerender-ratio must be between 0 and 1")
    if args.image_repair_target < 0:
        parser.error("--image-repair-target must be non-negative")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.clean_screenshot_dir = args.clean_screenshot_dir or (args.output_dir / "repair_clean_screenshots")
    out_jsonl = args.output_dir / "records.jsonl"
    text_v2_jsonl = args.output_dir / "text-repair.v2.jsonl"
    image_v2_jsonl = args.output_dir / "image-repair.v2.jsonl"

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
                text_record, image_record = repair_records(rec)
                if instance_id not in text_ids:
                    append_jsonl(text_v2_jsonl, text_record)
                    text_ids.add(instance_id)
                target_has_room = (
                    not args.image_repair_target
                    or len(image_ids) < args.image_repair_target
                )
                if image_record is not None and instance_id not in image_ids and target_has_room:
                    append_jsonl(image_v2_jsonl, image_record)
                    image_ids.add(instance_id)
                done_ids.add(instance_id)
        print(f"Resuming: {len(done_ids)} already done")

    api_key, base_url, model = ensure_api_env(prefer_vision=False)
    synthesizer = build_repair_synthesizer(api_key, base_url, model, max_retries=args.max_retries,
                                           max_tokens=args.max_output_tokens)
    all_task_types, _ = load_repair_catalog()
    projects = (iter_project_list(args.project_list, args.limit, args.offset)
                if args.project_list else iter_project_dirs(args.input_dir, args.limit, args.offset))
    assigned = [
        (p, balanced_task_count(index, args.seed, args.min_tasks, args.max_tasks))
        for index, p in enumerate(projects) if p.name not in done_ids
    ]
    total = len(assigned)
    print(f"text-repair: {total} projects, {args.workers} worker(s)")

    done = ok = errors = 0
    image_ok = len({str(rec.get("instance_id")) for rec in iter_jsonl_records(image_v2_jsonl, ignore_invalid=True)}) if image_v2_jsonl.exists() else 0
    if args.image_repair_target and image_ok >= args.image_repair_target:
        print(f"image-repair target already satisfied: {image_ok}/{args.image_repair_target}")
        return

    pending = iter(assigned)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {}

        def submit_one() -> bool:
            try:
                project, count = next(pending)
            except StopIteration:
                return False
            future = pool.submit(_process_one, project, args, synthesizer, all_task_types, count)
            futures[future] = project
            return True

        for _ in range(min(args.workers, total)):
            submit_one()
        while futures:
            completed, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in completed:
                futures.pop(future)
                result = future.result()
                append_jsonl(out_jsonl, result)
                if result["status"] == "ok":
                    text_record, image_record = repair_records(result)
                    append_jsonl(text_v2_jsonl, text_record)
                    target_has_room = (
                        not args.image_repair_target
                        or image_ok < args.image_repair_target
                    )
                    if image_record is not None and target_has_room:
                        append_jsonl(image_v2_jsonl, image_record)
                        image_ok += 1
                done += 1
                status = result["status"]
                if status == "ok":
                    ok += 1
                elif status == "error":
                    errors += 1
                tag = f" — {result.get('error', '')[:80]}" if status == "error" else ""
                target = f" image={image_ok}/{args.image_repair_target}" if args.image_repair_target else f" image={image_ok}"
                print(f"  [{done}/{total}] {result['instance_id']}: {status}{tag}{target}")
            target_met = args.image_repair_target and image_ok >= args.image_repair_target
            if not target_met:
                for _ in completed:
                    submit_one()
    print(f"text-repair done: {ok} ok, {errors} errors; image-repair eligible: {image_ok}")


if __name__ == "__main__":
    main()
