#!/usr/bin/env python3
"""Construct paired text/image edit data using forward synthesis only."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from reverse.construct_common import (
    affected_pages_from_patches,
    apply_search_replace_exact,
    append_jsonl,
    balanced_cycle_item,
    balanced_task_count,
    build_forward_edit_synthesizer,
    build_generation_data,
    choose_task_count,
    choose_task_types,
    ensure_api_env,
    existing_final_screenshots,
    infer_page_bucket,
    iter_project_dirs,
    iter_project_list,
    iter_jsonl_records,
    load_canonical_screenshots,
    load_edit_catalog,
    requires_cross_page,
    training_source_manifest,
    validate_screenshot_page_coverage,
)
from reverse.v2_records import edit_records
from reverse.task_specs import (
    benchmark_sources_for,
    interaction_types_for_tasks,
)


def _instance_id(project_dir: Path, args) -> str:
    return f"{getattr(args, 'instance_id_prefix', '')}{project_dir.name}"


def _process_one(project_dir: Path, args, synthesizer, all_task_types: list[str],
                 task_count: int | None = None, construction_profile: str = "all",
                 image_input_variant: str = "source_image") -> dict:
    """Process a single project. Returns a JSONL record."""
    instance_id = _instance_id(project_dir, args)
    try:
        generation_data = build_generation_data(project_dir)
        canonical_screens = (
            load_canonical_screenshots(args.canonical_screenshot_dir, project_dir.name)
            if getattr(args, "screenshot_dir", None) else []
        )
        clean_code = generation_data["dst_code"]
        task_count = task_count or choose_task_count(
            args.min_tasks, args.max_tasks, args.seed, instance_id
        )
        task_types = choose_task_types(
            all_task_types, task_count, args.seed, instance_id,
        )
        require_cross_page = requires_cross_page(
            generation_data, getattr(args, "page_scope", "any")
        )
        task = synthesizer.generate_forward_pair(
            generation_data, task_types, require_cross_page=require_cross_page
        )
        affected_pages = affected_pages_from_patches(
            generation_data, task["label_modified_files"]
        )
        src_code = clean_code
        dst_code = apply_search_replace_exact(src_code, task["label_modified_files"])
        # WebCompass Vision-Guided Editing supplies only the current/source
        # screenshot. Reuse the immutable mother canonical image and never
        # render the edited target or execute browser actions during patch
        # construction.
        source_screens = (
            canonical_screens if getattr(args, "screenshot_dir", None)
            else existing_final_screenshots(project_dir)
        )
        if getattr(args, "screenshot_dir", None):
            validate_screenshot_page_coverage(source_screens, affected_pages)
        visual_difference = {
            "status": "not_captured",
            "required_for_acceptance": False,
            "reason": "webcompass_source_screenshot_only",
        }
        images = {
            "src_screenshot": source_screens,
            "dst_screenshot": [],
            "interaction_screenshot": [],
        }
        interaction_types = interaction_types_for_tasks(task["task_type"])

        return {
            "instance_id": instance_id,
            "source_project": str(project_dir.resolve()),
            "task": "text-editing",
            "status": "ok",
            "construction_strategy": "forward",
            "construction_route": "forward_edit",
            "construction_profile": construction_profile,
            "page_scope": generation_data.get("page_scope", "sp"),
            "project_pages": generation_data.get("project_pages", []),
            "affected_pages": affected_pages,
            "image_input_variant": image_input_variant,
            "task_type": task["task_type"],
            "interaction_type": interaction_types,
            "benchmark_alignment": benchmark_sources_for(interaction_types),
            "description": task["description"],
            "instruction": {"src_code": src_code, "description": task["description"],
                            "source_manifest": training_source_manifest(project_dir)},
            "reference": {"dst_code": dst_code},
            "label_modified_files": task["label_modified_files"],
            # Only the original clean project has a reviewed render at this stage.
            "images": images,
            "visual_difference": visual_difference,
            "interaction_visual_differences": [],
            "browser_evidence": [],
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
            "task": "text-editing",
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
    parser.add_argument("--min-tasks", type=int, default=1)
    parser.add_argument("--max-tasks", type=int, default=7)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--instance-id-prefix", default="",
        help="Prefix generated IDs when reusing a mother in an additive supplement.",
    )
    parser.add_argument(
        "--skip-attempted", action="store_true",
        help="On resume, never submit an instance ID already recorded with any status.",
    )
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--max-output-tokens", type=int, default=8_192)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--success-target", type=int, default=0,
        help="Stop after this many successful text/image Edit pairs; zero scans every candidate.",
    )
    parser.add_argument("--screenshot-dir", type=Path,
                        help="Paired source/target image-edit screenshots; defaults to <output-dir>/edit_screenshots.")
    parser.add_argument(
        "--canonical-screenshot-dir", type=Path,
        help="Required immutable mother screenshot cache when image-edit screenshots are enabled.",
    )
    parser.add_argument(
        "--edit-profile",
        choices=("balanced", "all", "interaction2code", "artifactsbench", "frontendbench", "webcompass"),
        default="balanced",
        help="Rotate the four requested benchmark capability profiles or select one explicitly.",
    )
    parser.add_argument(
        "--page-scope", choices=("any", "sp", "mp"), default="any",
        help="Filter source projects; mp also enforces a cross-page patch effect.",
    )
    parser.add_argument(
        "--image-input-variants", default="source_image",
        help="Compatibility option; WebCompass image-edit accepts source_image only.",
    )
    parser.add_argument("--browser-proxy", default="http://127.0.0.1:7890")
    parser.add_argument("--minimum-changed-ratio", type=float, default=0.002)
    parser.add_argument("--minimum-interaction-changed-ratio", type=float, default=0.0001)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if bool(args.input_dir) == bool(args.project_list):
        parser.error("provide exactly one of --input-dir or --project-list")
    if args.screenshot_dir and not args.canonical_screenshot_dir:
        parser.error("--screenshot-dir requires --canonical-screenshot-dir; clean screenshots are never rerendered")
    if args.min_tasks < 1 or args.max_tasks > 12 or args.max_tasks < args.min_tasks:
        parser.error("task range must satisfy 1 <= min-tasks <= max-tasks <= 12")
    if args.success_target < 0:
        parser.error("--success-target must be non-negative")
    if args.success_target and args.workers != 1:
        parser.error("--success-target shards require --workers 1; parallelize independent quota shards")
    if not 0 <= args.minimum_changed_ratio <= 1:
        parser.error("--minimum-changed-ratio must be between 0 and 1")
    if not 0 <= args.minimum_interaction_changed_ratio <= 1:
        parser.error("--minimum-interaction-changed-ratio must be between 0 and 1")

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
    attempted_ids: set[str] = set()
    text_ids: set[str] = set()
    image_ids: set[str] = set()
    if out_jsonl.exists():
        text_ids = ({str(rec.get("instance_id")) for rec in iter_jsonl_records(text_v2_jsonl, ignore_invalid=True)}
                    if text_v2_jsonl.exists() else set())
        image_ids = ({str(rec.get("instance_id")) for rec in iter_jsonl_records(image_v2_jsonl, ignore_invalid=True)}
                     if image_v2_jsonl.exists() else set())
        for rec in iter_jsonl_records(out_jsonl, ignore_invalid=True):
            instance_id = str(rec.get("instance_id") or "")
            if instance_id:
                attempted_ids.add(instance_id)
            if rec.get("status") == "ok":
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
    synthesizer = build_forward_edit_synthesizer(
        api_key, base_url, model,
        max_retries=args.max_retries,
        max_tokens=args.max_output_tokens,
    )
    projects = (iter_project_list(args.project_list, args.limit, args.offset)
                if args.project_list else iter_project_dirs(args.input_dir, args.limit, args.offset))
    if args.page_scope != "any":
        projects = [
            project for project in projects
            if infer_page_bucket(project) == args.page_scope
        ]
    profile_cycle = ("interaction2code", "artifactsbench", "frontendbench", "webcompass")
    variants = [item.strip() for item in args.image_input_variants.split(",") if item.strip()]
    allowed_variants = {"source_image"}
    if not variants or any(item not in allowed_variants for item in variants):
        parser.error(
            "--image-input-variants must be source_image for WebCompass alignment"
        )
    assigned = [
        (
            p,
            balanced_task_count(index, args.seed, args.min_tasks, args.max_tasks),
            balanced_cycle_item(profile_cycle, index, args.offset, args.seed)
            if args.edit_profile == "balanced" else args.edit_profile,
            balanced_cycle_item(variants, index, args.offset, args.seed),
        )
        for index, p in enumerate(projects)
        if _instance_id(p, args) not in (attempted_ids if args.skip_attempted else done_ids)
    ]
    total = len(assigned)
    print(f"text/image-editing (forward): {total} projects, {args.workers} worker(s)")

    done = 0
    ok = len(image_ids)
    errors = 0
    if args.success_target:
        for p, count, profile, variant in assigned:
            if ok >= args.success_target:
                break
            result = _process_one(
                p, args, synthesizer, load_edit_catalog(profile)[0], count, profile, variant,
            )
            append_jsonl(out_jsonl, result)
            if result["status"] == "ok":
                text_record, image_record = edit_records(result)
                append_jsonl(text_v2_jsonl, text_record)
                append_jsonl(image_v2_jsonl, image_record)
                ok += 1
            else:
                errors += 1
            done += 1
            print(f"  [{done}/{total}] {result['instance_id']}: {result['status']}")
        print(f"text-editing shard done: accepted={ok}/{args.success_target}, errors={errors}")
        if ok < args.success_target:
            raise SystemExit(4)
        return

    ok = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                _process_one, p, args, synthesizer,
                load_edit_catalog(profile)[0], count, profile, variant,
            ): p
            for p, count, profile, variant in assigned
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
    if total and ok == 0:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
