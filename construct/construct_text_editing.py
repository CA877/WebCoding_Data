#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from WebCoding_Data.construct.construct_common import (
    append_jsonl,
    base_info,
    build_file_manifest,
    build_forward_edit_synthesizer,
    build_generation_data,
    choose_task_types,
    ensure_api_env,
    infer_page_bucket,
    load_edit_catalog,
    read_code_bundle,
    safe_write_json,
    serialize_patch_xml,
    write_pair_instance,
    iter_project_dirs,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--min-tasks", type=int, default=4)
    parser.add_argument("--max-tasks", type=int, default=12)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = args.output_dir / "manifest_text_editing.jsonl"
    api_key, base_url, model = ensure_api_env(prefer_vision=False)
    synthesizer = build_forward_edit_synthesizer(api_key, base_url, model, max_retries=args.max_retries)
    all_task_types, _ = load_edit_catalog()

    for project_dir in iter_project_dirs(args.input_dir, args.limit):
        bucket = infer_page_bucket(project_dir)
        instance_dir = args.output_dir / bucket / project_dir.name
        if instance_dir.exists():
            if not args.overwrite:
                append_jsonl(manifest, {"instance_id": project_dir.name, "bucket": bucket, "status": "skip_existing"})
                continue
            shutil.rmtree(instance_dir)
        try:
            generation_data = build_generation_data(project_dir)
            task_types = choose_task_types(all_task_types, (args.min_tasks, args.max_tasks), args.seed, project_dir.name)
            task = synthesizer.generate_forward_pair(generation_data, task_types)

            info = base_info(project_dir.name, "edit")
            info["task_type"] = task_types
            info["description"] = task["description"]  # [{task_type, description}, ...] array
            info["src_code"] = read_code_bundle(project_dir, code_only=True)
            # Filter dst_code to code-only files (html/css/js), matching src_code
            dst_code_only = [f for f in task["dst_code"] if any(f["path"].endswith(ext) for ext in (".html", ".htm", ".css", ".js", ".jsx", ".ts", ".tsx"))]
            info["dst_code"] = dst_code_only
            info["file_manifest"] = build_file_manifest(project_dir)
            info["label_modified_files"] = task["label_modified_files"]
            info["resources"] = task["resources"]
            info["meta"] = {
                "source_project": str(project_dir),
                "patch_xml": serialize_patch_xml(task["label_modified_files"]),
                "llm_metadata": task.get("llm_metadata", {}),
            }

            instance_dir = write_pair_instance(args.output_dir, bucket, project_dir, task["src_code"], task["dst_code"], info)
            safe_write_json(
                instance_dir / "llm_log.json",
                {
                    "llm_raw_response": task.get("llm_raw_response", ""),
                    "llm_metadata": task.get("llm_metadata", {}),
                    "synthetic_modified_files": task.get("synthetic_modified_files", []),
                },
            )
            append_jsonl(manifest, {"instance_id": project_dir.name, "bucket": bucket, "status": "ok", "task_type": task_types})
        except Exception as exc:  # noqa: BLE001
            shutil.rmtree(instance_dir, ignore_errors=True)
            append_jsonl(manifest, {"instance_id": project_dir.name, "bucket": bucket, "status": "error", "error": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    main()
