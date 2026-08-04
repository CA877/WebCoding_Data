#!/usr/bin/env python3
"""Build paired text/image-generation release-v2 JSONL from WebCompass projects."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from construct.construct_common import (
    TRAIN_CODE_EXTS,
    build_file_manifest,
    collect_resources,
    infer_page_bucket,
)


def read_projects(path: Path) -> list[Path]:
    projects = [Path(line.strip()).resolve() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(projects) != len({project.name for project in projects}):
        raise ValueError("project list has duplicate instance ids")
    return projects


def source_queries(path: Path) -> dict[str, str]:
    queries: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            instance_id = str(row.get("id", ""))
            for message in row.get("conversations", []):
                if message.get("from") in {"human", "user"} and isinstance(message.get("value"), str):
                    queries[instance_id] = message["value"]
                    break
    return queries


def audit_tokens(path: Path) -> dict[str, int]:
    result = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("status") == "eligible":
                result[Path(row["project"]).name] = int(row["tokens"])
    return result


def temp_path(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(prefix=f".{target.name}.", dir=target.parent, delete=False)
    handle.close()
    return Path(handle.name)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-jsonl", type=Path, required=True)
    parser.add_argument("--project-list", type=Path, required=True)
    parser.add_argument("--token-audit", type=Path, required=True)
    parser.add_argument("--text-output", type=Path, required=True)
    parser.add_argument("--image-output", type=Path, required=True)
    args = parser.parse_args()

    projects = read_projects(args.project_list)
    queries = source_queries(args.source_jsonl)
    tokens = audit_tokens(args.token_audit)
    text_tmp, image_tmp = temp_path(args.text_output), temp_path(args.image_output)
    try:
        with text_tmp.open("w", encoding="utf-8") as text_out, image_tmp.open("w", encoding="utf-8") as image_out:
            for index, project in enumerate(projects, 1):
                if project.name not in queries:
                    raise ValueError(f"missing source query for {project.name}")
                screenshots = sorted(project.glob(f"{project.name}*.png"))
                if len(screenshots) != 1:
                    raise ValueError(f"expected one image-generation screenshot for {project.name}; got {len(screenshots)}")
                code = [
                    {"path": path.relative_to(project).as_posix(),
                     "code": path.read_text(encoding="utf-8", errors="replace")}
                    for path in sorted(project.rglob("*"))
                    if path.is_file() and path.suffix.lower() in TRAIN_CODE_EXTS
                ]
                common = {
                    "instance_id": project.name,
                    "task_type": [],
                    "page_type": infer_page_bucket(project),
                    "file_manifest": build_file_manifest(project),
                    "resources": collect_resources(project),
                }
                metadata = {
                    "release_schema_reference": "webcoding-sft-v2",
                    "source": "train_sharegpt_webcompass_only_6503.jsonl",
                    "source_project": str(project),
                    "prompt_tokens": tokens[project.name],
                    "input_contract": {"max_prompt_tokens": 40000, "all_files_included": True},
                }
                text_record = {
                    **common,
                    "task": "text-generation",
                    "instruction": queries[project.name],
                    "response": code,
                    "metadata": metadata,
                }
                shot = str(screenshots[0].resolve())
                image_record = {
                    "schema_version": "webcoding-image-generation-v2",
                    **common,
                    "task": "image-generation",
                    # Deliberately empty: the screenshot is the only input query.
                    "instruction": "",
                    "input_files": [],
                    "input_images": [shot],
                    "src_screenshot": [shot],
                    "dst_screenshot": [],
                    "output_files": code,
                    "patches": [],
                    "response": code,
                    "conversion_status": "success",
                    "metadata": {**metadata, "base_task": "text-generation",
                                 "screenshot_state": "target", "screenshot_viewport": "desktop_1920x1080"},
                }
                text_out.write(json.dumps(text_record, ensure_ascii=False) + "\n")
                image_out.write(json.dumps(image_record, ensure_ascii=False) + "\n")
                if index % 500 == 0:
                    print(f"built {index}/{len(projects)}", flush=True)
        os.replace(text_tmp, args.text_output)
        os.replace(image_tmp, args.image_output)
    finally:
        for path in (text_tmp, image_tmp):
            if path.exists():
                path.unlink()
    print(json.dumps({"text_generate": len(projects), "image_generate": len(projects)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
