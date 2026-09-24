#!/usr/bin/env python3
"""Generate context-aware Edit instructions without generating answers."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from reverse.construct_common import (
    append_jsonl,
    build_forward_edit_synthesizer,
    build_generation_data,
    choose_task_count,
    choose_task_types,
    ensure_api_env,
    infer_page_bucket,
    iter_project_dirs,
    iter_project_list,
    iter_jsonl_records,
    load_edit_catalog,
)


def _instance_id(project_dir: Path, args) -> str:
    return f"{getattr(args, 'instance_id_prefix', '')}{project_dir.name}"


def _normalize_api_base_url(base_url: str | None) -> str | None:
    """Use Nju-Link's OpenAI-compatible API root instead of its web frontend."""
    if base_url and base_url.rstrip("/") == "https://api.nju-link.com":
        return f"{base_url.rstrip('/')}/v1"
    return base_url


def _available_edit_task_types(generation_data: dict, all_task_types: list[str]) -> list[str]:
    """Match the legacy demo's resource-aware Edit catalog filtering."""
    resources = generation_data.get("resources", [])
    has_images = any(item.get("type") == "image" for item in resources)
    if has_images:
        return list(all_task_types)
    return [task_type for task_type in all_task_types if task_type != "Parallax Scrolling"]


def _process_one(project_dir: Path, args, synthesizer, all_task_types: list[str],
                 task_count: int | None = None,
                 construction_profile: str = "webcompass") -> dict:
    """Generate Edit instructions for one project without an answer patch."""
    instance_id = _instance_id(project_dir, args)
    try:
        generation_data = build_generation_data(project_dir)
        available_task_types = _available_edit_task_types(
            generation_data, all_task_types
        )
        if not available_task_types:
            raise ValueError("no Edit task types are available for this project")
        task_count = task_count or choose_task_count(
            args.min_tasks, args.max_tasks, args.seed, instance_id
        )
        if not 4 <= task_count <= 12:
            raise ValueError("Edit instruction tasks must contain 4 to 12 subtasks")
        task_types = choose_task_types(
            available_task_types,
            min(task_count, len(available_task_types)),
            args.seed,
            instance_id,
        )
        task = synthesizer.generate_instruction(
            generation_data, task_types
        )

        return {
            "instance_id": instance_id,
            "source_project": str(project_dir.resolve()),
            "task": "text-editing",
            "status": "ok",
            "construction_strategy": "forward",
            "construction_route": "edit_instruction_only",
            "construction_profile": construction_profile,
            "page_scope": generation_data.get("page_scope", "sp"),
            "project_pages": generation_data.get("project_pages", []),
            "task_count": len(task["task_type"]),
            "task_type": task["task_type"],
            "description": task["description"],
            "instruction": task["description"],
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
    parser.add_argument(
        "--success-target", type=int, default=0,
        help="Stop after this many successful Edit-instruction records; zero scans every candidate.",
    )
    parser.add_argument(
        "--edit-profile",
        choices=("webcompass",),
        default="webcompass",
        help="Official WebCompass synthetic Edit catalog.",
    )
    parser.add_argument(
        "--page-scope", choices=("any", "sp", "mp"), default="any",
        help="Filter source projects; mp keeps each complete multi-page project as one sample.",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if bool(args.input_dir) == bool(args.project_list):
        parser.error("provide exactly one of --input-dir or --project-list")
    if args.min_tasks < 4 or args.max_tasks > 12 or args.max_tasks < args.min_tasks:
        parser.error("task range must satisfy 4 <= min-tasks <= max-tasks <= 12")
    if args.success_target < 0:
        parser.error("--success-target must be non-negative")
    if args.success_target and args.workers != 1:
        parser.error("--success-target shards require --workers 1; parallelize independent quota shards")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_jsonl = args.output_dir / "records.jsonl"

    if args.overwrite and out_jsonl.exists():
        out_jsonl.unlink()

    done_ids: set[str] = set()
    attempted_ids: set[str] = set()
    if out_jsonl.exists():
        for rec in iter_jsonl_records(out_jsonl, ignore_invalid=True):
            instance_id = str(rec.get("instance_id") or "")
            if instance_id:
                attempted_ids.add(instance_id)
            if rec.get("status") == "ok":
                done_ids.add(instance_id)
        print(f"Resuming: {len(done_ids)} already done")

    os.environ.setdefault("CONSTRUCT_STREAM", "1")
    api_key, base_url, model = ensure_api_env(prefer_vision=False)
    base_url = _normalize_api_base_url(base_url)
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
    assigned = [
        (
            p,
            choose_task_count(args.min_tasks, args.max_tasks, args.seed, _instance_id(p, args)),
            "webcompass",
        )
        for p in projects
        if _instance_id(p, args) not in (attempted_ids if args.skip_attempted else done_ids)
    ]
    total = len(assigned)
    print(f"edit-instruction generation: {total} projects, {args.workers} worker(s)")

    done = 0
    ok = len(done_ids)
    errors = 0
    if args.success_target:
        for p, count, profile in assigned:
            if ok >= args.success_target:
                break
            result = _process_one(
                p, args, synthesizer, load_edit_catalog(profile)[0], count, profile,
            )
            append_jsonl(out_jsonl, result)
            if result["status"] == "ok":
                ok += 1
            else:
                errors += 1
            done += 1
            print(f"  [{done}/{total}] {result['instance_id']}: {result['status']}")
        print(f"edit-instruction shard done: accepted={ok}/{args.success_target}, errors={errors}")
        if ok < args.success_target:
            raise SystemExit(4)
        return

    ok = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                _process_one, p, args, synthesizer,
                load_edit_catalog(profile)[0], count, profile,
            ): p
            for p, count, profile in assigned
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
    print(f"edit-instruction generation done: {ok} ok, {errors} errors, {done - ok - errors} skipped")
    if total and ok == 0:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
