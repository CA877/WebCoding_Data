#!/usr/bin/env python3
"""Append independent Image Generate records to the current release; retain legacy merge API."""
from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import fcntl
from pathlib import Path
import shutil

from PIL import Image


SHARD = Path("image-generate/train-00000-of-00001.jsonl.gz")
MODE_SUFFIX = {"multipage": "multi_page", "interaction": "interaction_keyframe",
               "transient": "transient_ui_state", "sequence": "multi_step_sequence"}
DEFAULT_IMAGE_GENERATE_INSTRUCTION = (
    "Generate a complete runnable web project that matches the provided reference screenshot(s) as closely as possible. "
    "Reproduce the visible layout, colors, typography, spacing, UI components, and responsive behavior. "
    "Implement interactions that are clearly implied by the screenshots. Output all required HTML, CSS, and JavaScript files with their paths."
)
ROLE_MARKER = "\n\nReference image roles:\n"


def response_sha256(row: dict) -> str:
    payload = json.dumps(row.get("response"), sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def read_rows(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_rows_atomic(path: Path, rows: list[dict]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with gzip.open(temporary, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    temporary.replace(path)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def accepted_overlays(run_root: Path) -> list[tuple[str, str, dict, Path, dict]]:
    overlays = []
    seen = set()
    direct = run_root / "manifest.jsonl"
    manifests = [direct] if direct.is_file() else sorted(run_root.glob("*/manifest.jsonl"))
    for manifest_path in manifests:
        worker_root = manifest_path.parent
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            if item.get("status") != "ok":
                continue
            mode = item["mode"]
            parent_id = item["parent_instance_id"]
            key = (mode, parent_id)
            if key in seen:
                raise ValueError(f"duplicate overlay: {key}")
            seen.add(key)
            case_dir = worker_root / mode / parent_id
            record = json.loads((case_dir / "record.json").read_text(encoding="utf-8"))
            overlays.append((mode, parent_id, record, case_dir, item))
    return overlays


def copy_overlay_images(
    release_root: Path, parent_id: str, mode: str, record: dict, case_dir: Path
) -> tuple[list[str], dict[str, str]]:
    destination = release_root / "image-generate" / "images" / parent_id
    destination.mkdir(parents=True, exist_ok=True)
    paths = []
    mapping = {}
    for value in record.get("input_images") or []:
        source = case_dir / Path(value).name
        if not source.is_file():
            raise FileNotFoundError(source)
        filename = f"refresh_{mode}__{source.name}"
        target = destination / filename
        shutil.copy2(source, target)
        relative = (Path("images") / parent_id / filename).as_posix()
        paths.append(relative)
        mapping[Path(value).name] = relative
    return paths, mapping


def expected_overlay_paths(parent_id: str, mode: str, record: dict) -> list[str]:
    return [
        (Path("images") / parent_id / f"refresh_{mode}__{Path(value).name}").as_posix()
        for value in record.get("input_images") or []
    ]


def rebase_mapping(value: object, filename_map: dict[str, str]) -> object:
    if isinstance(value, list):
        return [rebase_mapping(item, filename_map) for item in value]
    if isinstance(value, dict):
        return {
            key: filename_map.get(Path(item).name, item)
            if key in {"image", "before", "after", "source_image", "target_image"} and isinstance(item, str)
            else rebase_mapping(item, filename_map)
            for key, item in value.items()
        }
    return value


def visual_context_suffix(instruction: object) -> str:
    text = instruction if isinstance(instruction, str) else ""
    marker = "\n\nReference image roles:\n"
    return text.split(marker, 1)[1] if marker in text else ""


def apply_in_place(release_root: Path, run_root: Path, backup_root: Path, *, modes=None, only_known_parents=False) -> dict:
    shard = release_root / SHARD
    rows = read_rows(shard)
    original_response_hashes = {row["instance_id"]: response_sha256(row) for row in rows}
    by_id = {row["instance_id"]: row for row in rows}
    if len(by_id) != len(rows):
        raise ValueError("duplicate source instance_id")
    overlays = accepted_overlays(run_root)
    if modes is not None:
        overlays = [item for item in overlays if item[0] in modes]
    if only_known_parents:
        overlays = [item for item in overlays if item[1] in by_id]
    for _mode, parent_id, overlay, _case_dir, item in overlays:
        if parent_id not in by_id:
            raise KeyError(parent_id)
        expected = response_sha256(by_id[parent_id])
        if item.get("ground_truth_sha256") != expected or response_sha256(overlay) != expected:
            raise ValueError(f"ground truth changed: {parent_id}")

    backup_root.mkdir(parents=True, exist_ok=False)
    shutil.copy2(shard, backup_root / shard.name)
    index_path = release_root / "dataset_index.json"
    if index_path.is_file():
        shutil.copy2(index_path, backup_root / index_path.name)

    touched = set()
    mode_counts: dict[str, int] = {}
    already_applied = 0
    for mode, parent_id, overlay, case_dir, _item in overlays:
        row = by_id[parent_id]
        expected_paths = expected_overlay_paths(parent_id, mode, overlay)
        if expected_paths and all(path in (row.get("input_images") or []) for path in expected_paths):
            already_applied += 1
            continue
        new_images, filename_map = copy_overlay_images(release_root, parent_id, mode, overlay, case_dir)
        if mode == "multipage":
            row["input_images"] = new_images
            row["page_entry_mapping"] = rebase_mapping(overlay.get("page_entry_mapping") or [], filename_map)
            if overlay.get("additional_page_mapping"):
                row["additional_page_mapping"] = rebase_mapping(overlay["additional_page_mapping"], filename_map)
        else:
            row["input_images"] = list(dict.fromkeys((row.get("input_images") or []) + new_images))
            if overlay.get("interaction_mapping"):
                row.setdefault("interaction_mappings", []).append(
                    {"mode": mode, **rebase_mapping(overlay["interaction_mapping"], filename_map)}
                )
            if overlay.get("interaction_sequence_mapping"):
                row.setdefault("interaction_sequence_mappings", []).append(
                    {"mode": mode, "steps": rebase_mapping(overlay["interaction_sequence_mapping"], filename_map)}
                )
        visual_types = set(row.get("image_generate_visual_types") or [])
        visual_types.update(overlay.get("image_generate_visual_types") or [])
        row["image_generate_visual_types"] = sorted(visual_types)
        suffix = visual_context_suffix(overlay.get("instruction"))
        if suffix:
            for name in sorted(filename_map, key=len, reverse=True):
                suffix = suffix.replace(name, filename_map[name])
            row["instruction"] = str(row.get("instruction") or "").rstrip() + "\n\nReference image roles:\n" + suffix
        row["src_screenshot"] = list(row["input_images"])
        row["dst_screenshot"] = []
        row.setdefault("metadata", {})["image_generate_visual_refresh"] = True
        touched.add(parent_id)
        mode_counts[mode] = mode_counts.get(mode, 0) + 1

    output_rows = [by_id[row["instance_id"]] for row in rows]
    if len(output_rows) != len(rows):
        raise AssertionError("sample count changed")
    if any(original_response_hashes[row["instance_id"]] != response_sha256(row) for row in output_rows):
        raise AssertionError("ground truth changed")
    write_rows_atomic(shard, output_rows)
    missing = sum(
        not (release_root / "image-generate" / image).is_file()
        for row in output_rows for image in row.get("input_images") or []
    )
    if missing:
        raise ValueError(f"missing input images after write: {missing}")
    if index_path.is_file():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        task = index["tasks"]["image-generate"]
        task["num_samples"] = len(output_rows)
        task["image_files"] = sum(
            path.is_file() for path in (release_root / "image-generate" / "images").rglob("*")
        )
        task["compressed_gib"] = round(shard.stat().st_size / (1024 ** 3), 3)
        task["sha256"] = file_sha256(shard)
        temporary_index = index_path.with_name(index_path.name + ".tmp")
        temporary_index.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary_index.replace(index_path)
    result = {
        "status": "ok",
        "samples_before": len(rows),
        "samples_after": len(output_rows),
        "touched_samples": len(touched),
        "mode_counts": mode_counts,
        "already_applied": already_applied,
        "missing_input_images": missing,
        "backup_root": str(backup_root),
    }
    (backup_root / "apply_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def independent_record(mode: str, parent_id: str, overlay: dict, base_instruction: str) -> tuple[dict, dict[str, str]]:
    """Discard inherited, unrelated screenshot context while preserving the GT."""
    if mode not in MODE_SUFFIX or Path(parent_id).name != parent_id or parent_id in {".", ".."}:
        raise ValueError("unsafe parent id or unsupported mode")
    record = copy.deepcopy(overlay)
    record_id = f"{parent_id}__{MODE_SUFFIX[mode]}"
    names = [Path(value).name for value in record.get("input_images") or []]
    minimum_images = 3 if mode in {"multipage", "sequence"} else 2
    if len(names) < minimum_images or len(set(names)) != len(names):
        raise ValueError(f"invalid input image inventory: {record_id}")
    filename_map = {name: f"images/{record_id}/{name}" for name in names}
    mapping_field = {"multipage":"page_entry_mapping", "interaction":"interaction_mapping",
                     "transient":"interaction_mapping", "sequence":"interaction_sequence_mapping"}[mode]
    own_mapping = copy.deepcopy(record.get(mapping_field))
    if not own_mapping:
        raise ValueError(f"missing mode-specific mapping: {record_id}")
    for field in ("page_entry_mapping", "additional_page_mapping", "interaction_mapping", "interaction_mappings",
                  "interaction_sequence_mapping", "interaction_sequence_mappings", "_capture_plan"):
        record.pop(field, None)
    record.update(instance_id=record_id, parent_instance_id=parent_id,
                  input_images=list(filename_map.values()), src_screenshot=list(filename_map.values()), dst_screenshot=[])
    if mode == "multipage":
        record["visual_input_type"] = "multi_page"
        record["image_generate_visual_types"] = ["multi_page"]
        record["page_entry_mapping"] = rebase_mapping(own_mapping, filename_map)
        if overlay.get("additional_page_mapping"):
            record["additional_page_mapping"] = rebase_mapping(overlay["additional_page_mapping"], filename_map)
    elif mode in {"interaction", "transient"}:
        record["visual_input_type"] = "interaction_keyframes"
        record["image_generate_visual_types"] = ["same_page_interaction_states" if mode == "interaction" else "transient_ui_state"]
        record["interaction_mapping"] = rebase_mapping(own_mapping, filename_map)
    else:
        record["visual_input_type"] = "multi_step_interaction_sequence"
        record["image_generate_visual_types"] = ["multi_step_interaction_sequence"]
        record["interaction_sequence_mapping"] = rebase_mapping(own_mapping, filename_map)
    instruction = str(overlay.get("instruction") or "")
    if ROLE_MARKER not in instruction:
        raise ValueError(f"missing image role instruction: {record_id}")
    suffix = instruction.rsplit(ROLE_MARKER, 1)[1]
    for name in sorted(filename_map, key=len, reverse=True):
        suffix = suffix.replace(name, filename_map[name])
    prompt = base_instruction.split(ROLE_MARKER, 1)[0].rstrip() or DEFAULT_IMAGE_GENERATE_INSTRUCTION
    record["instruction"] = prompt + ROLE_MARKER + suffix
    metadata = record.setdefault("metadata", {})
    metadata.update(image_generate_primary_mode=mode, refresh_preserves_ground_truth=True,
                    image_root="images", image_paths_relative_to="task_root",
                    screenshot_viewport="desktop_1440x900", canonical_clean_image_shared=False)
    if mode in {"interaction", "transient"}:
        actual = {record["interaction_mapping"].get("before"), record["interaction_mapping"].get("after")}
    elif mode == "sequence":
        actual = {step.get("image") for step in record["interaction_sequence_mapping"]}
    else:
        actual = {x.get("source_image") for x in record["page_entry_mapping"]} | {x.get("target_image") for x in record["page_entry_mapping"]}
        actual |= {x.get("target_image") for x in record.get("additional_page_mapping", [])}
    if actual - set(record["input_images"]):
        raise ValueError(f"mapping references unrelated or missing images: {record_id}")
    return record, filename_map


def _append_records_locked(release_root: Path, run_roots: list[Path], backup_root: Path,
                           max_records: int, only_parent: str | None, parent_release_root: Path | None) -> dict:
    # Later roots (the reviewed pilot) take precedence; no historical files are changed.
    selected = {}
    for root in run_roots:
        manifests = [root / "manifest.jsonl"] if (root / "manifest.jsonl").is_file() else sorted(root.glob("*/manifest.jsonl"))
        if not manifests:
            raise ValueError(f"no candidate manifests: {root}")
        for path in manifests:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip(): continue
                item = json.loads(line)
                mode, parent = item.get("mode"), item.get("parent_instance_id")
                if item.get("status") != "ok" or mode not in MODE_SUFFIX or (only_parent and parent != only_parent):
                    continue
                if not isinstance(parent, str) or Path(parent).name != parent or parent in {".", ".."}:
                    raise ValueError("unsafe parent id")
                selected[(mode, parent)] = (path.parent / mode / parent, item)
    if not selected:
        raise ValueError("no accepted candidates")
    shard = release_root / SHARD
    task_root = release_root / "image-generate"
    desired_ids = {f"{parent}__{MODE_SUFFIX[mode]}" for mode, parent in selected}
    parents, existing, seen = {}, {}, set()
    original_hash = hashlib.sha256()
    original_count = 0
    primary_counts = {mode: 0 for mode in MODE_SUFFIX}
    with gzip.open(shard, "rt", encoding="utf-8") as handle:
        for line in handle:
            original_hash.update(line.encode())
            row = json.loads(line); identity = row["instance_id"]
            if identity in seen: raise ValueError(f"duplicate original id: {identity}")
            seen.add(identity); original_count += 1
            if identity in desired_ids:
                existing[identity] = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
            primary = row.get("metadata", {}).get("image_generate_primary_mode")
            if primary in primary_counts: primary_counts[primary] += 1
            for image in row.get("input_images") or []:
                if not (task_root / image).is_file(): raise ValueError(f"missing existing image: {image}")
            if original_count % 1000 == 0:
                print(json.dumps({"event":"source_scan", "rows":original_count}), flush=True)
    parent_shard = (parent_release_root or release_root) / SHARD
    with gzip.open(parent_shard, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line); identity = row["instance_id"]
            if any((mode, identity) in selected for mode in MODE_SUFFIX):
                parents[identity] = (response_sha256(row), str(row.get("instruction") or ""))
    selected = {key:value for key,value in selected.items() if key[1] in parents}
    if not selected or len(selected) > max_records:
        raise ValueError(f"source-matched candidate count {len(selected)} outside allowed 1..{max_records}")
    pending, already = [], 0
    for (mode, parent), (case_dir, item) in selected.items():
        overlay = json.loads((case_dir / "record.json").read_text(encoding="utf-8"))
        expected_hash, instruction = parents[parent]
        if item.get("ground_truth_sha256") != expected_hash or response_sha256(overlay) != expected_hash:
            raise ValueError(f"ground truth changed: {parent}")
        record, mapping = independent_record(mode, parent, overlay, instruction)
        identity = record["instance_id"]
        for name, relative in mapping.items():
            source = case_dir / name
            if source.is_symlink() or not source.is_file(): raise ValueError(f"invalid source image: {source}")
            with Image.open(source) as image: image.verify()
            target = task_root / relative
            if target.exists() and (target.is_symlink() or target.stat().st_nlink != 1 or file_sha256(source) != file_sha256(target)):
                raise ValueError(f"image collision: {target}")
            if identity in existing and not target.is_file(): raise ValueError(f"missing committed image: {target}")
        fingerprint = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
        if identity in existing:
            if existing[identity] != fingerprint: raise ValueError(f"record collision: {identity}")
            already += 1
        else:
            pending.append((mode, parent, case_dir, fingerprint))
    if not pending:
        return {"status":"already_applied", "samples_before":original_count, "samples_after":original_count,
                "appended":0, "already_applied":already, "independent_mode_counts":primary_counts}
    backup_root.mkdir(parents=True, exist_ok=False)
    shutil.copy2(shard, backup_root / shard.name)
    index_path = release_root / "dataset_index.json"
    shutil.copy2(index_path, backup_root / index_path.name)
    ledger_path = backup_root / "new_images.jsonl"
    updated = backup_root / "updated.jsonl.gz"
    added_ids, new_files = [], []
    appended_counts = {mode: 0 for mode in MODE_SUFFIX}
    with gzip.open(updated, "wt", encoding="utf-8", compresslevel=6) as out:
        copied_hash = hashlib.sha256()
        with gzip.open(shard, "rt", encoding="utf-8") as source:
            for line in source:
                copied_hash.update(line.encode()); out.write(line)
        if copied_hash.digest() != original_hash.digest(): raise ValueError("source changed during append")
        for index, (mode, parent, case_dir, fingerprint) in enumerate(pending, 1):
            overlay = json.loads((case_dir / "record.json").read_text(encoding="utf-8"))
            record, mapping = independent_record(mode, parent, overlay, parents[parent][1])
            if hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest() != fingerprint:
                raise ValueError("candidate changed during append")
            for name, relative in mapping.items():
                target = task_root / relative
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(case_dir / name, target)
                    new_files.append(relative)
                    with ledger_path.open("a", encoding="utf-8") as ledger:
                        ledger.write(json.dumps({"path": relative}) + "\n")
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            added_ids.append(record["instance_id"])
            primary_counts[mode] += 1; appended_counts[mode] += 1
            if index % 25 == 0 or index == len(pending):
                print(json.dumps({"event":"append_staging", "done":index, "total":len(pending)}), flush=True)
    index = json.loads(index_path.read_text(encoding="utf-8"))
    task = index["tasks"]["image-generate"]
    task.update(num_samples=original_count + len(pending), sha256=file_sha256(updated),
                image_files=sum(p.is_file() for p in (task_root / "images").rglob("*")),
                compressed_gib=round(updated.stat().st_size / 1024**3, 3), independent_mode_counts=primary_counts)
    staged_index = backup_root / "updated_index.json"
    staged_index.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {"status":"staged", "samples_before":original_count, "samples_after":original_count+len(pending),
              "appended":len(pending), "appended_mode_counts":appended_counts,
              "already_applied":already, "independent_mode_counts":primary_counts,
              "original_rows_sha256":original_hash.hexdigest(), "sha256":task["sha256"],
              "new_instance_ids":added_ids, "new_image_files":new_files, "backup_root":str(backup_root)}
    journal = backup_root / "append_result.json"
    journal.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    updated.replace(shard)
    staged_index.replace(index_path)
    result["status"] = "ok"
    journal.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {key:value for key,value in result.items() if key not in {"new_instance_ids", "new_image_files"}}


def append_records(release_root: Path, run_roots: list[Path], backup_root: Path,
                   max_records: int = 4000, only_parent: str | None = None,
                   parent_release_root: Path | None = None) -> dict:
    if max_records <= 0: raise ValueError("max-records must be positive")
    lock = release_root.parent / f".{release_root.name}.image-generate-append.lock"
    with lock.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _append_records_locked(release_root, run_roots, backup_root, max_records, only_parent, parent_release_root)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True, action="append")
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--max-records", type=int, default=4000)
    parser.add_argument("--only-parent")
    parser.add_argument("--parent-release-root", type=Path)
    parser.add_argument("--legacy-merge", action="store_true", help="Explicit historical overlay behavior")
    args = parser.parse_args()
    if args.legacy_merge:
        if len(args.run_root) != 1: parser.error("legacy merge accepts one run root")
        result = apply_in_place(args.release_root, args.run_root[0], args.backup_root)
    else:
        result = append_records(args.release_root, args.run_root, args.backup_root, args.max_records,
                                args.only_parent, args.parent_release_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
