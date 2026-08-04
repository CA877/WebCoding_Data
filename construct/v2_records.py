"""Release-v2 record builders for the paired edit/repair constructors."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .construct_common import build_file_manifest, collect_resources, infer_page_bucket


def _image_paths(images: list[dict[str, Any]]) -> list[str]:
    return [str(item["path"]) for item in images]


def _patch_counts(patches: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(patch.get("task_type", "")) for patch in patches))


def _metadata(record: dict[str, Any]) -> dict[str, Any]:
    patches = record["label_modified_files"]
    return {
        "release_schema_reference": "webcoding-sft-v2",
        "source_project": record["source_project"],
        "task_count": len(record["task_type"]),
        "patch_count": len(patches),
        "patch_count_by_task": _patch_counts(patches),
        "prompt_tokens": record.get("prompt_tokens", 0),
        "input_contract": record.get("input_contract", {}),
        "construction_model": record.get("llm_metadata", {}).get("model", ""),
    }


def edit_records(record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    project = Path(record["source_project"])
    screenshots = _image_paths(record["images"]["src_screenshot"])
    patches = record["label_modified_files"]
    common = {
        "instance_id": record["instance_id"],
        "task_type": record["task_type"],
        "page_type": infer_page_bucket(project),
        "file_manifest": build_file_manifest(project),
        "resources": collect_resources(project),
    }
    text = {
        **common,
        "task": "text-editing",
        "instruction": {
            "src_code": record["instruction"]["src_code"],
            "description": record["description"],
        },
        "response": patches,
        "metadata": _metadata(record),
    }
    image = {
        "schema_version": "webcoding-image-editing-v2",
        **common,
        "task": "image-editing",
        "instruction": record["description"],
        "input_files": record["instruction"]["src_code"],
        "input_images": screenshots,
        "src_screenshot": screenshots,
        "dst_screenshot": [],
        "patches": patches,
        "response": patches,
        "conversion_status": "success",
        "metadata": {**_metadata(record), "base_task": "text-editing",
                     "screenshot_state": "before_edit", "screenshot_viewport": "desktop_1920x1080"},
    }
    return text, image


def repair_records(record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    project = Path(record["source_project"])
    defect = _image_paths(record["images"]["src_screenshot"])
    clean = _image_paths(record["images"]["dst_screenshot"])
    patches = record["label_modified_files"]
    common = {
        "instance_id": record["instance_id"],
        "task_type": record["task_type"],
        "page_type": infer_page_bucket(project),
        "file_manifest": build_file_manifest(project),
        "resources": collect_resources(project),
    }
    text = {
        **common,
        "task": "text-repair",
        # No defect query: the model receives only the broken project.
        "instruction": record["instruction"],
        "response": patches,
        "metadata": {**_metadata(record), "image_repair_eligible": record["image_repair_eligible"],
                     "visual_difference": record["visual_difference"]},
    }
    if not record["image_repair_eligible"]:
        return text, None
    image = {
        "schema_version": "webcoding-image-repair-v2",
        **common,
        "task": "image-repair",
        "instruction": "Repair the provided web project.",
        "input_files": record["instruction"],
        "input_images": defect,
        "src_screenshot": defect,
        "dst_screenshot": clean,
        "patches": patches,
        "response": patches,
        "conversion_status": "success",
        "conversion_mode": "injected_bug_from_clean_input",
        "metadata": {**_metadata(record), "base_task": "text-repair",
                     "src_screenshot_state": "defective", "dst_screenshot_state": "clean",
                     "screenshot_viewport": "desktop_1920x1080",
                     "visual_difference": record["visual_difference"]},
    }
    return text, image
