#!/usr/bin/env python3
"""Build a fully materialized training release from compatible 0805 releases."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
from typing import Any, Iterable


TASKS = (
    "text-generate", "image-generate", "text-edit",
    "image-edit", "text-repair", "image-repair",
)
IMAGE_FIELDS = ("input_images", "src_screenshot", "dst_screenshot")
SHARD_NAME = "train-00000-of-00001.jsonl.gz"


@dataclass(frozen=True)
class SourceTask:
    label: str
    root: Path
    shard: Path
    row_count: int
    identifiers: frozenset[str]
    schema_keys: frozenset[str]
    image_files: frozenset[str]
    image_bytes: int
    shard_sha256: str


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative_path(raw: str, *, expected_first: str | None = None) -> PurePosixPath:
    relative = PurePosixPath(raw)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe relative path: {raw}")
    if expected_first is not None and relative.parts[0] != expected_first:
        raise ValueError(f"path must start with {expected_first}/: {raw}")
    return relative


def _read_index(label: str, root: Path) -> tuple[dict[str, Any], str]:
    index_path = root / "dataset_index.json"
    if not index_path.is_file():
        raise FileNotFoundError(index_path)
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if set(index.get("tasks", {})) != set(TASKS):
        raise ValueError(f"{label} dataset_index task set mismatch")
    return index, sha256(index_path)


def _audit_source_task(
    label: str, root: Path, task: str, metadata: dict[str, Any]
) -> SourceTask:
    shard_relative = _safe_relative_path(str(metadata.get("jsonl", "")))
    if shard_relative.parts[0] != task:
        raise ValueError(f"{label}/{task} JSONL is outside its task folder")
    shard = root / Path(*shard_relative.parts)
    if not shard.is_file():
        raise FileNotFoundError(shard)
    shard_digest = sha256(shard)
    if metadata.get("sha256") != shard_digest:
        raise ValueError(f"{label}/{task} shard checksum mismatch")

    identifiers: set[str] = set()
    schema_keys: frozenset[str] | None = None
    image_references: set[str] = set()
    row_count = 0
    with gzip.open(shard, "rt", encoding="utf-8") as handle:
        for row_count, line in enumerate(handle, 1):
            record = json.loads(line)
            current_keys = frozenset(record)
            if schema_keys is None:
                schema_keys = current_keys
            elif current_keys != schema_keys:
                raise ValueError(f"{label}/{task} row {row_count} schema keys changed")
            instance_id = str(record.get("instance_id", "")).strip()
            if not instance_id:
                raise ValueError(f"{label}/{task} row {row_count} has no instance_id")
            if instance_id in identifiers:
                raise ValueError(f"{label}/{task} duplicate instance_id: {instance_id}")
            identifiers.add(instance_id)
            if task.startswith("image-"):
                for field in IMAGE_FIELDS:
                    values = record.get(field, [])
                    if not isinstance(values, list):
                        raise ValueError(f"{label}/{task}/{instance_id} {field} is not a list")
                    for raw in values:
                        relative = _safe_relative_path(str(raw), expected_first="images")
                        full = root / task / Path(*relative.parts)
                        if not full.is_file():
                            raise FileNotFoundError(full)
                        image_references.add(relative.as_posix())
    if row_count != int(metadata.get("num_samples", -1)):
        raise ValueError(
            f"{label}/{task} row count {row_count}, expected {metadata.get('num_samples')}"
        )

    image_files: set[str] = set()
    image_bytes = 0
    image_root = root / task / "images"
    if image_root.is_dir():
        for path in image_root.rglob("*"):
            if path.is_file():
                image_files.add(f"images/{path.relative_to(image_root).as_posix()}")
                image_bytes += path.stat().st_size
    expected_images = int(metadata.get("image_files", 0))
    if len(image_files) != expected_images or image_files != image_references:
        raise ValueError(
            f"{label}/{task} image closure mismatch: disk={len(image_files)} "
            f"refs={len(image_references)} expected={expected_images}"
        )
    return SourceTask(
        label=label,
        root=root,
        shard=shard,
        row_count=row_count,
        identifiers=frozenset(identifiers),
        schema_keys=schema_keys or frozenset(),
        image_files=frozenset(image_files),
        image_bytes=image_bytes,
        shard_sha256=shard_digest,
    )


def _audit_sources(
    sources: list[tuple[str, Path]],
) -> tuple[dict[str, list[SourceTask]], list[dict[str, Any]]]:
    if len(sources) < 2:
        raise ValueError("at least two source releases are required")
    labels = [label for label, _ in sources]
    if len(set(labels)) != len(labels) or any(not label.strip() for label in labels):
        raise ValueError("source labels must be non-empty and unique")

    source_indices: list[dict[str, Any]] = []
    audits = {task: [] for task in TASKS}
    for label, raw_root in sources:
        root = raw_root.resolve()
        index, index_digest = _read_index(label, root)
        source_indices.append({
            "label": label,
            "release_name": index.get("name"),
            "directory_name": root.name,
            "dataset_index_sha256": index_digest,
        })
        for task in TASKS:
            audits[task].append(_audit_source_task(label, root, task, index["tasks"][task]))

    for task, task_sources in audits.items():
        seen_ids: set[str] = set()
        seen_images: set[str] = set()
        expected_schema = task_sources[0].schema_keys
        for source in task_sources:
            duplicate_ids = seen_ids & source.identifiers
            if duplicate_ids:
                example = sorted(duplicate_ids)[0]
                raise ValueError(f"{task} duplicate instance_id across releases: {example}")
            duplicate_images = seen_images & source.image_files
            if duplicate_images:
                example = sorted(duplicate_images)[0]
                raise ValueError(f"{task} duplicate image path across releases: {example}")
            if source.schema_keys != expected_schema:
                raise ValueError(f"{task} schema keys differ between source releases")
            seen_ids.update(source.identifiers)
            seen_images.update(source.image_files)
    return audits, source_indices


def _write_combined_shard(sources: Iterable[SourceTask], destination: Path) -> int:
    rows = 0
    with gzip.open(destination, "wt", encoding="utf-8", compresslevel=6) as target:
        for source in sources:
            with gzip.open(source.shard, "rt", encoding="utf-8") as handle:
                for line in handle:
                    target.write(line)
                    rows += 1
    return rows


def _copy_images(sources: Iterable[SourceTask], destination: Path) -> None:
    for source in sources:
        image_root = source.root / destination.parent.name / "images"
        if image_root.is_dir():
            try:
                shutil.copytree(
                    image_root,
                    destination,
                    dirs_exist_ok=True,
                    symlinks=False,
                    copy_function=shutil.copy2,
                )
            except shutil.Error as exc:
                errors = exc.args[0] if exc.args and isinstance(exc.args[0], list) else []
                first = errors[0] if errors else "unknown copy error"
                raise OSError(
                    f"image copy failed for {source.label}/{destination.parent.name}: "
                    f"errors={len(errors)} first={first}"
                ) from None


def _materialization_counts(root: Path) -> tuple[int, int, int, int]:
    files = 0
    bytes_total = 0
    symlinks = 0
    hardlinked_files = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            symlinks += 1
        elif path.is_file():
            files += 1
            stat = path.stat()
            bytes_total += stat.st_size
            if stat.st_nlink != 1:
                hardlinked_files += 1
    return files, bytes_total, symlinks, hardlinked_files


def build_combined_release(
    sources: list[tuple[str, Path]], output_root: Path
) -> dict[str, Any]:
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite {output_root}")
    audits, source_indices = _audit_sources(sources)
    output_root.parent.mkdir(parents=True, exist_ok=True)
    image_bytes = sum(
        source.image_bytes for task_sources in audits.values() for source in task_sources
    )
    source_shard_bytes = sum(
        source.shard.stat().st_size for task_sources in audits.values() for source in task_sources
    )
    required_bytes = image_bytes + int(source_shard_bytes * 1.5) + 2 * 1024**3
    free_bytes = shutil.disk_usage(output_root.parent).free
    print(json.dumps({
        "status": "space_preflight",
        "output_filesystem": str(output_root.parent),
        "required_bytes": required_bytes,
        "free_bytes": free_bytes,
    }), flush=True)
    if free_bytes < required_bytes:
        raise OSError(
            f"insufficient free space under {output_root.parent}: "
            f"required={required_bytes} free={free_bytes}"
        )
    temporary = output_root.parent / f".{output_root.name}.incomplete-{os.getpid()}"
    if temporary.exists():
        raise FileExistsError(temporary)
    temporary.mkdir(parents=True)
    try:
        tasks: dict[str, Any] = {}
        for task in TASKS:
            task_root = temporary / task
            task_root.mkdir()
            shard = task_root / SHARD_NAME
            rows = _write_combined_shard(audits[task], shard)
            expected_rows = sum(source.row_count for source in audits[task])
            if rows != expected_rows:
                raise ValueError(f"{task} combined row count {rows}, expected {expected_rows}")
            image_count = sum(len(source.image_files) for source in audits[task])
            if task.startswith("image-"):
                _copy_images(audits[task], task_root / "images")
                copied = sum(1 for path in (task_root / "images").rglob("*") if path.is_file())
                if copied != image_count:
                    raise ValueError(f"{task} copied image count {copied}, expected {image_count}")
            tasks[task] = {
                "jsonl": f"{task}/{SHARD_NAME}",
                "data_files": [f"{task}/{SHARD_NAME}"],
                "num_samples": rows,
                "image_root": f"{task}/images" if task.startswith("image-") else None,
                "image_files": image_count,
                "compressed_gib": round(shard.stat().st_size / 1024**3, 3),
                "sha256": sha256(shard),
                "source_shards": [
                    {
                        "label": source.label,
                        "num_samples": source.row_count,
                        "sha256": source.shard_sha256,
                    }
                    for source in audits[task]
                ],
            }
            if task.startswith("image-"):
                tasks[task]["image_path_mode"] = "paths in records are relative to the task folder"
            print(json.dumps({"status": "task_ok", "task": task, **tasks[task]}, ensure_ascii=False), flush=True)

        index = {
            "name": "0805_combined",
            "schema_version": "webcoding-sft-v2-combined-v1",
            "materialization": "full_copy_no_links",
            "source_releases": source_indices,
            "tasks": tasks,
            "notes": [
                "All source records are retained; no rows are dropped or deduplicated.",
                "Each task is recompressed into one standard gzip member for legacy loader compatibility.",
                "All images are ordinary copied files; there are no symbolic links or hard links.",
            ],
        }
        (temporary / "dataset_index.json").write_text(
            json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        total_rows = sum(item["num_samples"] for item in tasks.values())
        total_images = sum(item["image_files"] for item in tasks.values())
        (temporary / "README.md").write_text(
            "# 0805_combined\n\n"
            "0805 与 0805_supplement 的完整合并训练包。六类任务沿用 0805 v2 布局，"
            "每类任务包含一个 `train-00000-of-00001.jsonl.gz`。图片均为包内普通实体文件，"
            "不依赖软链接、硬链接或外部目录。\n\n"
            f"总样本数：{total_rows}；总图片数：{total_images}。详细数量和 SHA-256 见 "
            "`dataset_index.json`。\n",
            encoding="utf-8",
        )
        expected_files = 3 + len(TASKS) + total_images
        validation = {
            "status": "ok",
            "source_release_count": len(sources),
            "task_count": len(TASKS),
            "total_samples": total_rows,
            "total_images": total_images,
            "instance_id_collisions": 0,
            "image_path_collisions": 0,
            "symlinks": 0,
            "hardlinked_files": 0,
            "expected_files": expected_files,
        }
        (temporary / "validation.json").write_text(
            json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        files, _bytes_total, symlinks, hardlinked_files = _materialization_counts(temporary)
        if files != expected_files or symlinks or hardlinked_files:
            raise ValueError({
                "files": files, "expected_files": expected_files,
                "symlinks": symlinks, "hardlinked_files": hardlinked_files,
            })
        validation["files"] = files
        (temporary / "validation.json").write_text(
            json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(temporary, output_root)
        print(json.dumps({"status": "ok", "output_root": str(output_root), **validation}, ensure_ascii=False), flush=True)
        return index
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _parse_source(raw: str) -> tuple[str, Path]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError("source must use LABEL=PATH")
    label, path = raw.split("=", 1)
    if not label.strip() or not path.strip():
        raise argparse.ArgumentTypeError("source must use non-empty LABEL=PATH")
    return label, Path(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", action="append", type=_parse_source, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    build_combined_release(args.source, args.output_root)


if __name__ == "__main__":
    main()
