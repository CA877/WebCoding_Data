"""Deterministically clean 0905 Edit records for later GT regeneration."""
from __future__ import annotations

import argparse
import collections
import copy
import gzip
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any


SHARD = "train-00000-of-00001.jsonl.gz"
EDIT_TASKS = ("text-edit", "image-edit")


def records(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_number}") from exc


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def descriptions(row: dict[str, Any], modality: str) -> list[dict[str, str]]:
    instruction = row.get("instruction")
    if modality == "text":
        values = (instruction or {}).get("description") or []
    else:
        values = instruction if isinstance(instruction, list) else []
    return [
        {
            "task_type": str(item.get("task_type", "")).strip(),
            "description": str(item.get("description", "")).strip(),
        }
        for item in values
        if isinstance(item, dict)
    ]


def source_code(row: dict[str, Any], modality: str) -> list[dict[str, str]]:
    if modality == "text":
        return (row.get("instruction") or {}).get("src_code") or []
    return row.get("input_files") or []


def clean_pending_record(
    row: dict[str, Any], ordered_task_types: list[str]
) -> dict[str, Any]:
    cleaned = copy.deepcopy(row)
    cleaned.pop("response", None)
    cleaned.pop("patches", None)
    cleaned["task_type"] = list(ordered_task_types)
    metadata = dict(cleaned.get("metadata") or {})
    source_model = metadata.get("construction_model")
    metadata.pop("patch_count", None)
    metadata.pop("patch_count_by_task", None)
    metadata.update(
        {
            "task_count": len(ordered_task_types),
            "gt_status": "pending_regeneration",
            "gt_regeneration_strategy": "frozen_instruction_sequential_subtask",
            "source_gt_construction_model": source_model,
        }
    )
    cleaned["metadata"] = metadata
    return cleaned


def prepare(source: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(output)
    index = json.loads((source / "dataset_index.json").read_text())
    source_hashes = {}
    rows_by_modality = {}
    for task in EDIT_TASKS:
        shard = source / task / SHARD
        actual = sha256(shard)
        expected = index["tasks"][task]["sha256"]
        if actual != expected:
            raise ValueError(f"source hash mismatch for {task}: {actual} != {expected}")
        source_hashes[task] = actual
        rows_by_modality[task] = {
            row["instance_id"]: row for row in records(shard)
        }

    text_rows = rows_by_modality["text-edit"]
    image_rows = rows_by_modality["image-edit"]
    temporary = output.with_name(output.name + ".tmp")
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)

    pending_text = gzip.open(temporary / "text-edit.pending.jsonl.gz", "wt", encoding="utf-8")
    pending_image = gzip.open(temporary / "image-edit.pending.jsonl.gz", "wt", encoding="utf-8")
    queue = gzip.open(temporary / "regeneration_queue.jsonl.gz", "wt", encoding="utf-8")
    removed = gzip.open(temporary / "removed_1_to_3.jsonl.gz", "wt", encoding="utf-8")

    unique_kept = collections.Counter()
    unique_removed = collections.Counter()
    modality_kept = collections.Counter()
    order_repairs = 0
    visual_only = 0
    try:
        for instance_id in sorted(set(text_rows) | set(image_rows)):
            text = text_rows.get(instance_id)
            image = image_rows.get(instance_id)
            canonical = text or image
            task_types = list(canonical.get("task_type") or [])
            task_count = len(task_types)
            modalities = [
                name
                for name, value in (("text", text), ("image", image))
                if value is not None
            ]
            if task_count <= 3:
                removed.write(
                    json.dumps(
                        {
                            "instance_id": instance_id,
                            "task_count": task_count,
                            "modalities": modalities,
                            "reason": "remove_1_to_3_subtasks",
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                unique_removed[task_count] += 1
                continue
            if not 4 <= task_count <= 7:
                raise ValueError(f"{instance_id}: unexpected task count {task_count}")

            canonical_modality = "text" if text else "image"
            frozen = descriptions(canonical, canonical_modality)
            is_visual_only = bool(
                image
                and not frozen
                and (image.get("metadata") or {}).get("image_input_variant")
                == "source_target_images_no_query"
            )
            if is_visual_only:
                ordered_task_types = task_types
                visual_only += 1
            else:
                if len(frozen) != task_count or any(
                    not item["task_type"] or not item["description"] for item in frozen
                ):
                    raise ValueError(f"{instance_id}: invalid frozen instruction")
                ordered_task_types = [item["task_type"] for item in frozen]
                if collections.Counter(ordered_task_types) != collections.Counter(task_types):
                    raise ValueError(f"{instance_id}: instruction/task types differ")
                if ordered_task_types != task_types:
                    order_repairs += 1

            code = source_code(canonical, canonical_modality)
            if not code:
                raise ValueError(f"{instance_id}: missing source code")
            if text and image:
                if source_code(text, "text") != source_code(image, "image"):
                    raise ValueError(f"{instance_id}: paired source code differs")
                if descriptions(text, "text") != descriptions(image, "image"):
                    raise ValueError(f"{instance_id}: paired instruction differs")

            if text:
                pending_text.write(
                    json.dumps(
                        clean_pending_record(text, ordered_task_types),
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                modality_kept["text"] += 1
            if image:
                pending_image.write(
                    json.dumps(
                        clean_pending_record(image, ordered_task_types),
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                modality_kept["image"] += 1

            queue_row = {
                "instance_id": instance_id,
                "task_count": task_count,
                "task_type": ordered_task_types,
                "instruction": canonical.get("instruction"),
                "source_code": code,
                "modalities": modalities,
                "visual_only_instruction": is_visual_only,
                "gt_status": "pending_regeneration",
            }
            if image:
                queue_row["image_context"] = {
                    "input_images": image.get("input_images") or [],
                    "src_screenshot": image.get("src_screenshot") or [],
                    "dst_screenshot": image.get("dst_screenshot") or [],
                    "target_reference_images": image.get("target_reference_images") or [],
                    "image_root": str(source / "image-edit"),
                }
            queue.write(json.dumps(queue_row, ensure_ascii=False) + "\n")
            unique_kept[task_count] += 1
    finally:
        pending_text.close()
        pending_image.close()
        queue.close()
        removed.close()

    summary = {
        "status": "prepared_for_gt_regeneration",
        "source_release": str(source),
        "source_edit_sha256": source_hashes,
        "llm_calls": 0,
        "unique_kept_4_to_7": sum(unique_kept.values()),
        "unique_kept_by_task_count": dict(sorted(unique_kept.items())),
        "unique_removed_1_to_3": sum(unique_removed.values()),
        "unique_removed_by_task_count": dict(sorted(unique_removed.items())),
        "pending_records": dict(modality_kept),
        "paired_instances": sum(
            1
            for instance_id in set(text_rows) & set(image_rows)
            if 4 <= len(text_rows[instance_id].get("task_type") or []) <= 7
        ),
        "instruction_order_repairs": order_repairs,
        "visual_only_instruction_instances": visual_only,
        "outputs": {
            name: {
                "sha256": sha256(temporary / name),
                "bytes": (temporary / name).stat().st_size,
            }
            for name in (
                "text-edit.pending.jsonl.gz",
                "image-edit.pending.jsonl.gz",
                "regeneration_queue.jsonl.gz",
                "removed_1_to_3.jsonl.gz",
            )
        },
    }
    write_json(temporary / "summary.json", summary)
    temporary.replace(output)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
