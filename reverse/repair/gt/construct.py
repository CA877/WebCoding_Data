#!/usr/bin/env python3
"""Text-repair task: LLM injects defects → flip patches to repair direction.

Output: a single JSONL file, one line per project.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import random
import tempfile
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from reverse.construct_common import (
    affected_pages_from_patches,
    append_jsonl,
    build_generation_data,
    build_repair_synthesizer,
    choose_task_count,
    choose_task_types,
    ensure_api_env,
    existing_final_screenshots,
    infer_page_bucket,
    iter_project_dirs,
    iter_project_list,
    iter_jsonl_records,
    load_canonical_screenshots,
    load_repair_catalog,
    screenshot_pair_difference,
    screenshot_project_to_dir,
    training_source_manifest,
    validate_screenshot_page_coverage,
    write_code_bundle_from_source,
)
from reverse.v2_records import repair_records

# Match the legacy demo's project-level behavior: render every HTML page in the
# project for both the defective and clean states.  Each MP project remains one
# sample; it is not reduced to index.html or required to have a cross-page patch.
DESKTOP_VIEWPORT = [("desktop", 1920, 1080)]

def _absolute_screens(screens: list[dict], root: Path) -> list[dict]:
    return [{**item, "path": str((root / Path(item["path"]).name).resolve())} for item in screens]


def _canonical_clean_screen(project_dir: Path) -> dict:
    expected = project_dir / f"{project_dir.name}_clean.png"
    if expected.is_file():
        return {"path": str(expected.resolve()), "kind": "shared_image_generate_full_page"}
    # New Pipeline-C pilots store a reviewed root PNG without the historical
    # `_clean` suffix. Accept that existing artifact instead of copying or
    # renaming production data merely to satisfy a filename convention.
    fallback = existing_final_screenshots(project_dir)
    return {**fallback[0], "kind": "shared_reviewed_clean_full_page"}


def _full_page_difference(clean_path: str, defect_path: str, channel_threshold: int = 8) -> dict:
    """Compare canonical and defective full-page renders, padding size changes."""
    from PIL import Image, ImageChops

    with Image.open(clean_path) as raw_clean, Image.open(defect_path) as raw_defect:
        clean, defect = raw_clean.convert("RGB"), raw_defect.convert("RGB")
        width, height = max(clean.width, defect.width), max(clean.height, defect.height)
        clean_canvas = Image.new("RGB", (width, height), "white")
        defect_canvas = Image.new("RGB", (width, height), "white")
        clean_canvas.paste(clean, (0, 0))
        defect_canvas.paste(defect, (0, 0))
        diff = ImageChops.difference(clean_canvas, defect_canvas)
        channels = diff.split()
        masks = [
            channel.point(lambda value: 255 if value >= channel_threshold else 0)
            for channel in channels
        ]
        combined = ImageChops.lighter(ImageChops.lighter(masks[0], masks[1]), masks[2])
        changed = width * height - combined.histogram()[0]
    ratio = changed / max(width * height, 1)
    return {
        "minimum_changed_ratio": 0.0,
        "channel_threshold": channel_threshold,
        "max_changed_ratio": round(ratio, 6),
        "comparison": "canonical_image_generate_vs_rule_defect_full_page",
        "screens": [{
            "page": "index.html", "viewport": "desktop_full_page",
            "changed_pixels": changed, "total_pixels": width * height,
            "changed_ratio": round(ratio, 6),
            "clean_size": [clean.width, clean.height],
            "defect_size": [defect.width, defect.height],
        }],
    }


def _process_one(project_dir: Path, args, synthesizer, all_task_types,
                 task_count: int | None = None) -> dict:
    """Process a single project. Returns a JSONL record."""
    instance_id = f"{getattr(args, 'instance_id_prefix', '')}{project_dir.name}"
    try:
        generation_data = build_generation_data(project_dir)
        canonical_screens = load_canonical_screenshots(
            args.canonical_screenshot_dir, project_dir.name
        )
        task_count = task_count or choose_task_count(
            args.min_tasks,
            args.max_tasks,
            args.seed,
            instance_id,
        )
        task_types = choose_task_types(
            all_task_types, task_count, args.seed, instance_id, allow_repeat=True,
        )
        task = synthesizer.generate_defect_task(
            generation_data, task_types
        )
        if not task:
            raise RuntimeError("repair generation returned None")

        affected_pages = affected_pages_from_patches(
            generation_data, task["label_modified_files"]
        )

        defective_code = task["defective_code"]
        defective_full_code = task["defective_full_code"]
        defect_root = args.defect_screenshot_dir or (args.output_dir / "repair_defect_screenshots")
        defect_dir = defect_root / project_dir.name
        failure_evidence: list[dict] = [{
            "kind": "exact_patch_round_trip",
            "status": "reproduced",
            "patch_count": len(task["label_modified_files"]),
        }]
        with tempfile.TemporaryDirectory() as temp:
            broken = Path(temp) / "broken"
            write_code_bundle_from_source(project_dir, defective_full_code, broken)
            clean_screens_all = canonical_screens
            raw_screens = screenshot_project_to_dir(broken, defect_dir, args.browser_proxy,
                                                    viewports=DESKTOP_VIEWPORT, full_page=True)
        defect_screens_all = _absolute_screens(raw_screens, defect_dir)
        # The legacy save_task() calls save_screenshots() on the complete src
        # and dst project directories. Preserve that all-pages pairing for SP
        # and MP instead of silently collapsing MP to index.html.
        defect_screens = defect_screens_all
        clean_reference_screens = clean_screens_all
        visual = screenshot_pair_difference(
            clean_reference_screens, defect_screens, minimum_ratio=0.0,
        )
        visual["comparison"] = "canonical_clean_vs_defect_all_pages"
        visual["clean_rerender_max_changed_ratio"] = 0.0
        changed_affected_pages = sorted({
            str(item["page"]).split("#", 1)[0]
            for item in visual["screens"]
            if item["changed_ratio"] > 0
        })
        # WebCompass synthetic accepts the injected patch after code
        # validation; screenshot difference is evidence, not an admission
        # threshold. Keep the computed metrics for downstream analysis.
        image_repair_eligible = True
        visual["minimum_changed_ratio"] = args.minimum_changed_ratio
        failure_evidence.append({
            "kind": "screenshot_diff",
            "status": "measured",
            "max_changed_ratio": visual["max_changed_ratio"],
            "changed_affected_pages": changed_affected_pages,
        })
        return {
            "instance_id": instance_id,
            "source_project": str(project_dir.resolve()),
            "task": "text-repair",
            "status": "ok",
            "construction_route": "controlled_repair",
            "task_type": task_types,
            "repair_family": [],
            "repair_subfamily": [],
            "benchmark_alignment": [],
            "defect_type": task_types,
            "failure_evidence": failure_evidence,
            "page_scope": generation_data.get("page_scope", "sp"),
            "project_pages": generation_data.get("project_pages", []),
            "affected_pages": affected_pages,
            "changed_affected_pages": changed_affected_pages,
            "description": task["description"],
            # Release v2 text-repair has no task query: only broken input code.
            "instruction": defective_code,
            "reference": {"dst_code": generation_data["dst_code"]},
            "label_modified_files": task["label_modified_files"],
            "images": {"src_screenshot": defect_screens, "dst_screenshot": clean_reference_screens},
            "visual_difference": visual,
            "image_repair_eligible": image_repair_eligible,
            "llm_response": task.get("llm_raw_response", ""),
            "llm_metadata": task.get("llm_metadata", {}),
            "llm_attempts": task.get("llm_attempts", []),
            "prompt_tokens": generation_data.get("prompt_tokens", 0),
            "input_contract": generation_data.get("input_contract", {}),
        }
    except Exception as exc:  # noqa: BLE001
        error_text = f"{type(exc).__name__}: {exc}"
        return {
            "instance_id": instance_id,
            "task": "text-repair",
            "status": "error",
            "error_type": "timeout" if "timeout" in error_text.lower() else "validation_error",
            "error": error_text,
            "llm_attempts": getattr(exc, "llm_attempts", []),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, help="Project directory root (mutually exclusive with --project-list).")
    parser.add_argument("--project-list", type=Path, help="One absolute project path per line; use for fixed batch splits.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--min-tasks", type=int, default=4)
    parser.add_argument("--max-tasks", type=int, default=12)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--instance-id-prefix", default="",
        help="Prefix generated IDs when reusing a mother in an additive supplement.",
    )
    parser.add_argument(
        "--skip-attempted", action="store_true",
        help="On resume, never submit an instance ID already recorded with any status.",
    )
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--max-output-tokens", type=int, default=8_192)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--browser-proxy", default="http://127.0.0.1:7890")
    parser.add_argument("--defect-screenshot-dir", type=Path,
                        help="Image-repair asset root; defaults to <output-dir>/repair_defect_screenshots for direct CLI compatibility.")
    parser.add_argument("--clean-screenshot-dir", type=Path,
                        help="Deprecated; clean rerenders are forbidden. Use --canonical-screenshot-dir.")
    parser.add_argument(
        "--canonical-screenshot-dir", type=Path, required=True,
        help="Immutable mother screenshot cache shared with image-generate and image-edit.",
    )
    parser.add_argument("--minimum-changed-ratio", type=float, default=0.0,
                        help="Compatibility option; WebCompass synthetic has no visual-difference gate.")
    parser.add_argument("--image-repair-target", type=int, default=0,
                        help="Stop scheduling new projects after this many v2 image-repair records; zero scans all.")
    parser.add_argument(
        "--injection-strategy", choices=("llm",), default="llm",
        help="Use the official WebCompass LLM injection path.",
    )
    parser.add_argument(
        "--repair-profile", choices=("webcompass",), default="webcompass",
        help="Official WebCompass synthetic Repair catalog.",
    )
    parser.add_argument(
        "--page-scope", choices=("any", "sp", "mp"), default="any",
        help="Filter source projects; mp keeps each complete multi-page project as one sample.",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if bool(args.input_dir) == bool(args.project_list):
        parser.error("provide exactly one of --input-dir or --project-list")
    if args.clean_screenshot_dir:
        parser.error("--clean-screenshot-dir is no longer supported; Repair must reuse canonical screenshots")
    if args.min_tasks < 1 or args.max_tasks > 12 or args.max_tasks < args.min_tasks:
        parser.error("task range must satisfy 1 <= min-tasks <= max-tasks <= 12")
    if not 0 <= args.minimum_changed_ratio <= 1:
        parser.error("--minimum-changed-ratio must be between 0 and 1")
    if args.image_repair_target < 0:
        parser.error("--image-repair-target must be non-negative")
    if args.image_repair_target and args.workers != 1:
        parser.error("exact image-repair quota shards require --workers 1")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_jsonl = args.output_dir / "records.jsonl"
    text_v2_jsonl = args.output_dir / "text-repair.v2.jsonl"
    image_v2_jsonl = args.output_dir / "image-repair.v2.jsonl"

    if args.overwrite:
        for path in (out_jsonl, text_v2_jsonl, image_v2_jsonl):
            if path.exists():
                path.unlink()

    # Resume support also repairs an interrupted multi-file append.
    done_ids: set[str] = set()
    attempted_ids: set[str] = set()
    if out_jsonl.exists():
        text_ids = ({str(rec.get("instance_id")) for rec in iter_jsonl_records(text_v2_jsonl, ignore_invalid=True)}
                    if text_v2_jsonl.exists() else set())
        resume_image_records = (list(iter_jsonl_records(image_v2_jsonl, ignore_invalid=True))
                                if image_v2_jsonl.exists() else [])
        image_ids = {str(rec.get("instance_id")) for rec in resume_image_records}
        resume_image_counts = Counter(
            int(rec.get("metadata", {}).get("task_count", 0))
            for rec in resume_image_records
        )
        for rec in iter_jsonl_records(out_jsonl, ignore_invalid=True):
            instance_id = str(rec.get("instance_id") or "")
            if instance_id:
                attempted_ids.add(instance_id)
            if rec.get("status") == "ok":
                text_record, image_record = repair_records(rec)
                if instance_id not in text_ids:
                    append_jsonl(text_v2_jsonl, text_record)
                    text_ids.add(instance_id)
                result_count = len(rec.get("task_type", []))
                target_has_room = not args.image_repair_target or len(image_ids) < args.image_repair_target
                if image_record is not None and instance_id not in image_ids and target_has_room:
                    append_jsonl(image_v2_jsonl, image_record)
                    image_ids.add(instance_id)
                    resume_image_counts[result_count] += 1
                done_ids.add(instance_id)
        print(f"Resuming: {len(done_ids)} already done")

    api_key, base_url, model = ensure_api_env(prefer_vision=False)
    synthesizer = build_repair_synthesizer(api_key, base_url, model, max_retries=args.max_retries,
                                           max_tokens=args.max_output_tokens)
    all_task_types, _ = load_repair_catalog("webcompass")
    projects = (iter_project_list(args.project_list, args.limit, args.offset)
                if args.project_list else iter_project_dirs(args.input_dir, args.limit, args.offset))
    if args.page_scope != "any":
        projects = [
            project for project in projects
            if infer_page_bucket(project) == args.page_scope
        ]
    assigned = [
        (
            p,
            choose_task_count(
                args.min_tasks, args.max_tasks, args.seed,
                f"{args.instance_id_prefix}{p.name}",
            ),
        )
        for index, p in enumerate(projects)
        if f"{args.instance_id_prefix}{p.name}" not in (
            attempted_ids if args.skip_attempted else done_ids
        )
    ]
    total = len(assigned)
    print(f"text-repair: {total} projects, {args.workers} worker(s)")

    done = ok = errors = 0
    image_records = (list(iter_jsonl_records(image_v2_jsonl, ignore_invalid=True))
                     if image_v2_jsonl.exists() else [])
    image_ok = len({str(rec.get("instance_id")) for rec in image_records})
    image_task_counts = Counter(int(rec.get("metadata", {}).get("task_count", 0))
                                for rec in image_records)
    quotas_satisfied = bool(args.image_repair_target) and image_ok >= args.image_repair_target
    if args.image_repair_target and quotas_satisfied:
        print(f"image-repair target already satisfied: {image_ok}/{args.image_repair_target}")
        return

    pending = iter(assigned)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {}

        def submit_one() -> bool:
            try:
                project, default_count = next(pending)
            except StopIteration:
                return False
            count = default_count
            future = pool.submit(
                _process_one, project, args, synthesizer, all_task_types, count,
            )
            futures[future] = (project, count)
            return True

        for _ in range(min(args.workers, total)):
            submit_one()
        while futures:
            completed, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in completed:
                _, scheduled_count = futures.pop(future)
                result = future.result()
                append_jsonl(out_jsonl, result)
                if result["status"] == "ok":
                    text_record, image_record = repair_records(result)
                    append_jsonl(text_v2_jsonl, text_record)
                    result_count = len(result["task_type"])
                    target_has_room = not args.image_repair_target or image_ok < args.image_repair_target
                    if image_record is not None and target_has_room:
                        append_jsonl(image_v2_jsonl, image_record)
                        image_ok += 1
                        image_task_counts[result_count] += 1
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
    if total and ok == 0:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
