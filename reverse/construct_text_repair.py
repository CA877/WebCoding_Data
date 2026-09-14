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

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from reverse.construct_common import (
    affected_pages_from_patches,
    append_jsonl,
    balanced_cycle_item,
    balanced_task_count,
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
    requires_cross_page,
    screenshot_pair_difference,
    screenshot_project_to_dir,
    training_source_manifest,
    validate_screenshot_page_coverage,
    write_code_bundle_from_source,
)
from reverse.v2_records import repair_records
from reverse.rule_defect_injector import available_rule_types, build_rule_defect_task
from reverse.task_specs import (
    REPAIR_DEFECT_TAXONOMY,
    REPAIR_FAMILIES,
    repair_defect_metadata,
)

# Text-repair only needs a single desktop render of the injected defect.  The
# tablet/mobile variants and the clean-vs-defective visual delta are not part
# of the text-repair training contract.
DESKTOP_VIEWPORT = [("desktop", 1920, 1080)]

# This constructor validates browser-served projects. Build-only and
# trajectory-only leaves remain in the shared taxonomy for future dedicated
# DesignBench/FronTalk constructors, but are fail-closed here instead of being
# mislabeled from screenshot-only evidence.
_BROWSER_CONSTRUCTIBLE_QUALITY = {
    "semantic_structure", "missing_attributes", "accessibility_regression",
}
_BROWSER_CONSTRUCTIBLE_RUNTIME = {
    "bootstrap_render_crash", "route_resource_failure", "event_runtime_exception",
}


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


def validate_repair_task_bounds(
    profile: str, min_tasks: int, max_tasks: int
) -> tuple[list[str], dict[str, str]]:
    """Reject impossible task counts before any API call is made."""
    task_types, descriptions = load_repair_catalog(profile)
    maximum = 12 if profile == "webcompass" else len(task_types)
    if min_tasks < 1 or max_tasks < min_tasks or max_tasks > maximum:
        raise ValueError(
            f"repair profile {profile} supports 1..{maximum} tasks; "
            f"received {min_tasks}..{max_tasks}"
        )
    return task_types, descriptions


def choose_mixed_family_task_types(
    all_task_types: list[str], task_count: int, seed: int, instance_id: str
) -> list[str]:
    """Choose distinct defects across all four families for 4--12 task rows."""
    if not 4 <= task_count <= 12:
        raise ValueError("mixed-family Repair requires 4..12 task types")
    buckets = {
        family: [
            task_type for task_type in all_task_types
            if REPAIR_DEFECT_TAXONOMY[task_type]["family"] == family
        ]
        for family in REPAIR_FAMILIES
    }
    rng = random.Random(f"mixed-repair:{seed}:{instance_id}:{task_count}")
    family_order = list(REPAIR_FAMILIES)
    rng.shuffle(family_order)
    for values in buckets.values():
        rng.shuffle(values)
    selected: list[str] = []
    while len(selected) < task_count:
        advanced = False
        for family in family_order:
            if buckets[family] and len(selected) < task_count:
                selected.append(buckets[family].pop())
                advanced = True
        if not advanced:
            raise ValueError(f"only {len(selected)} mixed-family defects available")
    return selected


def _process_one(project_dir: Path, args, synthesizer, all_task_types,
                 task_count: int | None = None,
                 assigned_family: str | None = None) -> dict:
    """Process a single project. Returns a JSONL record."""
    instance_id = f"{getattr(args, 'instance_id_prefix', '')}{project_dir.name}"
    try:
        generation_data = build_generation_data(project_dir)
        canonical_screens = load_canonical_screenshots(
            args.canonical_screenshot_dir, project_dir.name
        )
        task_count = task_count or choose_task_count(
            args.min_tasks,
            args.max_tasks if getattr(args, "repair_profile", "legacy") == "webcompass"
            else min(args.max_tasks, len(all_task_types)),
            args.seed,
            instance_id,
        )
        eligible_task_types = all_task_types
        if getattr(args, "repair_profile", "legacy") == "taxonomy":
            mixed_families = bool(getattr(args, "mixed_families", False))
            if not mixed_families:
                if assigned_family not in REPAIR_FAMILIES:
                    raise RuntimeError(f"invalid assigned repair family: {assigned_family}")
                eligible_task_types = [
                    defect_type for defect_type in all_task_types
                    if REPAIR_DEFECT_TAXONOMY[defect_type]["family"] == assigned_family
                ]
                if assigned_family == "runtime_repair":
                    eligible_task_types = [
                        item for item in eligible_task_types
                        if item in _BROWSER_CONSTRUCTIBLE_RUNTIME
                    ]
                elif assigned_family == "quality_refinement":
                    eligible_task_types = [
                        item for item in eligible_task_types
                        if item in _BROWSER_CONSTRUCTIBLE_QUALITY
                    ]
            if args.injection_strategy == "rule":
                supported_rules = set(available_rule_types())
                eligible_task_types = [
                    item for item in eligible_task_types if item in supported_rules
                ]
            if generation_data.get("page_scope") != "mp":
                eligible_task_types = [
                    item for item in eligible_task_types
                    if not item.startswith("cross_page_")
                ]
        allow_repeated_types = (
            getattr(args, "repair_profile", "legacy") == "webcompass"
        )
        if not allow_repeated_types:
            task_count = min(task_count, len(eligible_task_types))
        if getattr(args, "mixed_families", False):
            task_types = choose_mixed_family_task_types(
                eligible_task_types, task_count, args.seed, instance_id
            )
        else:
            task_types = choose_task_types(
                eligible_task_types, task_count, args.seed, instance_id,
                allow_repeat=allow_repeated_types,
            )
        require_cross_page = requires_cross_page(
            generation_data, getattr(args, "page_scope", "any")
        )
        if args.injection_strategy == "rule":
            task = build_rule_defect_task(generation_data, task_types)
        elif args.injection_strategy == "fallback":
            try:
                task = synthesizer.generate_defect_task(
                    generation_data, task_types, require_cross_page=require_cross_page
                )
            except Exception as exc:  # noqa: BLE001
                print(f"LLM defect injection failed; using deterministic rules: {exc}")
                task = build_rule_defect_task(generation_data, task_types)
        else:
            task = synthesizer.generate_defect_task(
                generation_data, task_types, require_cross_page=require_cross_page
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
        taxonomy = (
            repair_defect_metadata(task_types)
            if getattr(args, "repair_profile", "legacy") == "taxonomy"
            else {
                "repair_family": task_types if getattr(args, "repair_profile", "legacy") == "family" else [],
                "repair_subfamily": [],
                "benchmark_alignment": [],
            }
        )
        repair_family = taxonomy["repair_family"][0] if len(taxonomy["repair_family"]) == 1 else ""
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
        if require_cross_page:
            affected_page_set = set(affected_pages)
            defect_screens = [
                item for item in defect_screens_all
                if str(item.get("page", "")).split("#", 1)[0] in affected_page_set
            ]
            clean_reference_screens = [
                item for item in clean_screens_all
                if str(item.get("page", "")).split("#", 1)[0] in affected_page_set
            ]
            validate_screenshot_page_coverage(defect_screens, affected_pages)
            validate_screenshot_page_coverage(clean_reference_screens, affected_pages)
        else:
            defect_screen = next(
                (item for item in defect_screens_all if item.get("page") == "index.html"),
                defect_screens_all[0],
            )
            clean_screen = next(
                (item for item in clean_screens_all if item.get("page") == "index.html"),
                clean_screens_all[0],
            )
            defect_screens = [defect_screen]
            clean_reference_screens = [clean_screen]
        visual = screenshot_pair_difference(
            clean_reference_screens, defect_screens, minimum_ratio=0.0,
        )
        visual["comparison"] = (
            "canonical_clean_vs_defect_all_pages" if require_cross_page else
            "canonical_clean_vs_defect_index"
        )
        visual["clean_rerender_max_changed_ratio"] = 0.0
        changed_affected_pages = sorted({
            str(item["page"]).split("#", 1)[0]
            for item in visual["screens"]
            if item["changed_ratio"] >= args.minimum_changed_ratio
        })
        image_repair_eligible = bool(changed_affected_pages)
        # ``repair_visual_difference`` is also used to measure sub-threshold
        # text-only repairs, so it is called with a zero raising threshold.
        # The persisted metadata must nevertheless describe the real release
        # gate used below, not that measurement implementation detail.
        visual["minimum_changed_ratio"] = args.minimum_changed_ratio
        if image_repair_eligible:
            failure_evidence.append({
                "kind": "screenshot_diff",
                "status": "reproduced",
                "max_changed_ratio": visual["max_changed_ratio"],
                "minimum_changed_ratio": args.minimum_changed_ratio,
                "changed_affected_pages": changed_affected_pages,
            })
        return {
            "instance_id": instance_id,
            "source_project": str(project_dir.resolve()),
            "task": "text-repair",
            "status": "ok",
            "construction_route": "controlled_repair",
            "task_type": task_types,
            **taxonomy,
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
    parser.add_argument("--min-tasks", type=int, default=1)
    parser.add_argument("--max-tasks", type=int, default=3)
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
    parser.add_argument("--browser-proxy", default="http://127.0.0.1:7890")
    parser.add_argument("--defect-screenshot-dir", type=Path,
                        help="Image-repair asset root; defaults to <output-dir>/repair_defect_screenshots for direct CLI compatibility.")
    parser.add_argument("--clean-screenshot-dir", type=Path,
                        help="Deprecated; clean rerenders are forbidden. Use --canonical-screenshot-dir.")
    parser.add_argument(
        "--canonical-screenshot-dir", type=Path, required=True,
        help="Immutable mother screenshot cache shared with image-generate and image-edit.",
    )
    parser.add_argument("--minimum-changed-ratio", type=float, default=0.01)
    parser.add_argument("--maximum-clean-rerender-ratio", type=float, default=0.002,
                        help="Deprecated compatibility option; paired rerenders now use identical viewports.")
    parser.add_argument("--image-repair-target", type=int, default=0,
                        help="Stop scheduling new projects after this many v2 image-repair records; zero scans all.")
    parser.add_argument(
        "--injection-strategy", choices=("llm", "rule", "fallback"), default="llm",
        help="Use LLM injection, deterministic rules only, or rules when LLM validation fails.",
    )
    parser.add_argument(
        "--repair-profile", choices=("all", "taxonomy", "family", "legacy", "webcompass"), default="taxonomy",
        help="taxonomy constructs leaf defects grouped under one of the four Repair families.",
    )
    parser.add_argument(
        "--assigned-family", choices=REPAIR_FAMILIES,
        help="Pin one taxonomy family for an exact quota shard.",
    )
    parser.add_argument(
        "--mixed-families", action="store_true",
        help="Select 4--12 distinct defects across all four Repair families.",
    )
    parser.add_argument(
        "--page-scope", choices=("any", "sp", "mp"), default="any",
        help="Filter source projects; mp enforces a cross-page defect/fix effect.",
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
    if not 0 <= args.maximum_clean_rerender_ratio <= 1:
        parser.error("--maximum-clean-rerender-ratio must be between 0 and 1")
    if args.image_repair_target < 0:
        parser.error("--image-repair-target must be non-negative")
    if args.injection_strategy == "fallback" and args.repair_profile != "legacy":
        parser.error("fallback injection only supports --repair-profile legacy")
    if args.assigned_family and args.repair_profile != "taxonomy":
        parser.error("--assigned-family requires --repair-profile taxonomy")
    if args.mixed_families and args.repair_profile != "taxonomy":
        parser.error("--mixed-families requires --repair-profile taxonomy")
    if args.mixed_families and args.assigned_family:
        parser.error("--mixed-families cannot be combined with --assigned-family")
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

    image_task_quotas = Counter()
    if args.image_repair_target:
        image_task_quotas.update(
            balanced_task_count(index, args.seed, args.min_tasks, args.max_tasks)
            for index in range(args.image_repair_target)
        )

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
                target_has_room = not args.image_repair_target or (
                    len(image_ids) < args.image_repair_target
                    and resume_image_counts[result_count] < image_task_quotas[result_count]
                )
                if image_record is not None and instance_id not in image_ids and target_has_room:
                    append_jsonl(image_v2_jsonl, image_record)
                    image_ids.add(instance_id)
                    resume_image_counts[result_count] += 1
                done_ids.add(instance_id)
        print(f"Resuming: {len(done_ids)} already done")

    synthesizer = None
    if args.injection_strategy != "rule":
        api_key, base_url, model = ensure_api_env(prefer_vision=False)
        synthesizer = build_repair_synthesizer(api_key, base_url, model, max_retries=args.max_retries,
                                               max_tokens=args.max_output_tokens)
    try:
        all_task_types, _ = validate_repair_task_bounds(
            args.repair_profile, args.min_tasks, args.max_tasks
        )
    except ValueError as exc:
        parser.error(str(exc))
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
            balanced_task_count(index, args.seed, args.min_tasks, args.max_tasks),
            (None if args.mixed_families else args.assigned_family or balanced_cycle_item(
                REPAIR_FAMILIES, index, args.offset, args.seed
            )) if args.repair_profile == "taxonomy" else None,
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
    if args.image_repair_target:
        invalid_existing = {
            count: value for count, value in image_task_counts.items()
            if count not in image_task_quotas or value > image_task_quotas[count]
        }
        if invalid_existing:
            raise RuntimeError(f"existing image-repair task-count quotas exceeded: {invalid_existing}")
    quotas_satisfied = bool(image_task_quotas) and all(
        image_task_counts[count] >= quota
        for count, quota in image_task_quotas.items()
    )
    if args.image_repair_target and quotas_satisfied:
        print(f"image-repair target already satisfied: {image_ok}/{args.image_repair_target}")
        return

    pending = iter(assigned)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {}
        inflight_task_counts = Counter()

        def next_target_task_count(default_count: int) -> int:
            if not image_task_quotas:
                return default_count
            available = [
                count for count in sorted(image_task_quotas)
                if image_task_counts[count] < image_task_quotas[count]
            ]
            if not available:
                return default_count
            # Keep every image-repair quota advancing together.  Counting
            # in-flight work prevents a whole worker wave from selecting the
            # same task count, while repeated sub-threshold results naturally
            # cause that count to receive more future candidates.
            return min(
                available,
                key=lambda count: (
                    (image_task_counts[count] + 0.75 * inflight_task_counts[count])
                    / image_task_quotas[count],
                    (count - args.seed) % len(available),
                ),
            )

        def submit_one() -> bool:
            try:
                project, default_count, assigned_family = next(pending)
            except StopIteration:
                return False
            count = next_target_task_count(default_count)
            future = pool.submit(
                _process_one, project, args, synthesizer, all_task_types, count,
                assigned_family,
            )
            futures[future] = (project, count, assigned_family)
            inflight_task_counts[count] += 1
            return True

        for _ in range(min(args.workers, total)):
            submit_one()
        while futures:
            completed, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in completed:
                _, scheduled_count, _ = futures.pop(future)
                inflight_task_counts[scheduled_count] -= 1
                result = future.result()
                append_jsonl(out_jsonl, result)
                if result["status"] == "ok":
                    text_record, image_record = repair_records(result)
                    append_jsonl(text_v2_jsonl, text_record)
                    result_count = len(result["task_type"])
                    target_has_room = not args.image_repair_target or (
                        image_ok < args.image_repair_target
                        and image_task_counts[result_count] < image_task_quotas[result_count]
                    )
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
            target_met = args.image_repair_target and all(
                image_task_counts[count] >= quota
                for count, quota in image_task_quotas.items()
            )
            if not target_met:
                for _ in completed:
                    submit_one()
    print(f"text-repair done: {ok} ok, {errors} errors; image-repair eligible: {image_ok}")
    if total and ok == 0:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
