#!/usr/bin/env python3
"""Strict structural audit for the six-task WebCompass release-v2 JSONLs."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from PIL import Image, ImageChops, ImageStat


TASK_FILES = {
    "text-generation": "text-generate.jsonl",
    "image-generation": "image-generate.jsonl",
    "text-editing": "text-edit.jsonl",
    "image-editing": "image-edit.jsonl",
    "text-repair": "text-repair.jsonl",
    "image-repair": "image-repair.jsonl",
}
MANIFEST_TASK_KEYS = {
    "text-generation": "text-generate",
    "image-generation": "image-generate",
    "text-editing": "text-edit",
    "image-editing": "image-edit",
    "text-repair": "text-repair",
    "image-repair": "image-repair",
}


def _apply_exact_once(code: list[dict], patches: list[dict]) -> list[dict]:
    code_map = {item["path"]: item["code"] for item in code}
    for index, patch in enumerate(patches):
        path, search, replace = patch["path"], patch["search"], patch["replace"]
        if path not in code_map or not search or search == replace:
            raise ValueError(f"invalid patch {index} for {path}")
        count = code_map[path].count(search)
        if count != 1:
            raise ValueError(f"patch {index} search count is {count}, expected 1")
        code_map[path] = code_map[path].replace(search, replace, 1)
    return [{**item, "code": code_map[item["path"]]} for item in code]


def apply_exact(code: list[dict], patches: list[dict]) -> list[dict]:
    """Apply patches and prove that their exact inverse restores every file."""
    modified = _apply_exact_once(code, patches)
    reverse = [
        {**patch, "search": patch["replace"], "replace": patch["search"]}
        for patch in reversed(patches)
    ]
    restored = _apply_exact_once(modified, reverse)
    if restored != code:
        raise ValueError("patches do not round-trip to the exact original code")
    return modified


def input_code(record: dict) -> list[dict] | None:
    task = record["task"]
    if task == "text-editing":
        return record["instruction"]["src_code"]
    if task == "text-repair":
        return record["instruction"]
    if task in {"image-editing", "image-repair"}:
        return record["input_files"]
    return None


def validate_instruction_contract(record: dict, task_types: list[str]) -> None:
    """Enforce explicit edit queries and non-disclosing repair instructions."""
    task = record["task"]
    if task in {"text-editing", "image-editing"}:
        descriptions = (
            record.get("instruction", {}).get("description")
            if task == "text-editing"
            else record.get("instruction")
        )
        if not isinstance(descriptions, list):
            raise ValueError("edit query must be a per-task description list")
        described_types = [
            str(item.get("task_type", ""))
            for item in descriptions
            if isinstance(item, dict)
        ]
        if described_types != task_types or len(described_types) != len(descriptions):
            raise ValueError("edit query descriptions do not map exactly to task_type")
        if any(not str(item.get("description", "")).strip() for item in descriptions):
            raise ValueError("edit query contains an empty task description")
    elif task == "image-repair":
        instruction = str(record.get("instruction", "")).strip()
        if instruction != "Repair the provided web project.":
            raise ValueError("image-repair instruction must not disclose injected bug tasks")


def validate_image(path: Path) -> None:
    with Image.open(path) as raw:
        raw.verify()
    with Image.open(path) as raw:
        if raw.width < 300 or raw.height < 300:
            raise ValueError(f"image is too small: {raw.size}")
        preview = raw.convert("L")
        preview.thumbnail((128, 128))
        # Some valid applications are intentionally sparse (for example a
        # blank writing canvas with a small toolbar).  Pure/near-solid failed
        # captures remain below 0.1, while antialiased real UI content passes.
        if ImageStat.Stat(preview).stddev[0] < 0.1:
            raise ValueError("image is near-uniform/blank")


def changed_ratio(left: Path, right: Path, channel_threshold: int = 8) -> float:
    """Recompute max-channel pixel difference from the released PNG pair."""
    with Image.open(left) as raw_left, Image.open(right) as raw_right:
        a, b = raw_left.convert("RGB"), raw_right.convert("RGB")
        if a.size != b.size:
            raise ValueError(f"paired screenshot sizes differ: {a.size} vs {b.size}")
        channels = ImageChops.difference(a, b).split()
        masks = [channel.point(lambda value: 255 if value >= channel_threshold else 0)
                 for channel in channels]
        combined = ImageChops.lighter(ImageChops.lighter(masks[0], masks[1]), masks[2])
        unchanged = combined.histogram()[0]
        return (a.width * a.height - unchanged) / max(a.width * a.height, 1)


def fingerprint(value) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_unique_ids(path: Path) -> set[str]:
    values = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
              if line.strip()]
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate IDs in {path}")
    return set(values)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jsonl-dir", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--expected-generate", type=int, default=6502)
    parser.add_argument("--expected-source", type=int, default=6503)
    parser.add_argument("--expected-edit", type=int, default=3000)
    parser.add_argument("--expected-image-repair", type=int, default=3000)
    args = parser.parse_args()

    ids: dict[str, set[str]] = {}
    counts: dict[str, int] = {}
    task_count_distributions: dict[str, dict[str, int]] = {}
    pair_fingerprints: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    checked_images: set[Path] = set()
    release_root = args.jsonl_dir.resolve().parent
    for task, name in TASK_FILES.items():
        path = args.jsonl_dir / name
        seen: set[str] = set()
        task_fingerprints: dict[str, str] = {}
        distribution: Counter[int] = Counter()
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                try:
                    record = json.loads(line)
                    instance_id = str(record["instance_id"])
                    if instance_id in seen:
                        raise ValueError("duplicate instance_id")
                    seen.add(instance_id)
                    if record.get("task") != task:
                        raise ValueError(f"task={record.get('task')!r}, expected {task!r}")
                    if int(record.get("metadata", {}).get("prompt_tokens", 0)) > 40000:
                        raise ValueError("prompt_tokens exceeds 40K")
                    if record.get("metadata", {}).get("input_contract", {}).get("all_files_included") is not True:
                        raise ValueError("all-files input contract missing")
                    if task == "image-generation" and record.get("instruction"):
                        raise ValueError("image-generation must not contain a text query")
                    if task == "text-generation" and not str(record.get("instruction", "")).strip():
                        raise ValueError("text-generation query is empty")
                    if task.startswith("image-"):
                        images = record.get("input_images", [])
                        all_images = list(dict.fromkeys(
                            [*images, *record.get("src_screenshot", []), *record.get("dst_screenshot", [])]
                        ))
                        resolved_images = [
                            (Path(image) if Path(image).is_absolute() else release_root / image).resolve()
                            for image in all_images
                        ]
                        if not images or any(not image.is_file() for image in resolved_images):
                            raise ValueError("missing input image")
                        for image in resolved_images:
                            if image not in checked_images:
                                validate_image(image)
                                checked_images.add(image)
                    code = input_code(record)
                    if task in {"text-generation", "image-generation"}:
                        output_paths = {item["path"] for item in record["response"]}
                        manifest_paths = {item["path"] for item in record.get("file_manifest", []) if item.get("type") == "code"}
                        if output_paths != manifest_paths:
                            raise ValueError("generation response does not contain every code file")
                        task_fingerprints[instance_id] = fingerprint(record["response"])
                    if code is not None:
                        task_types = list(record.get("task_type", []))
                        if not 1 <= len(task_types) <= 7 or len(task_types) != len(set(task_types)):
                            raise ValueError("task_type count must be 1--7 and distinct")
                        validate_instruction_contract(record, task_types)
                        distribution[len(task_types)] += 1
                        patches = record["response"]
                        mapping = Counter(str(patch.get("task_type", "")) for patch in patches)
                        if set(mapping) != set(task_types) or any(not 1 <= value <= 10 for value in mapping.values()):
                            raise ValueError("task-to-patch mapping violates 1--10 contract")
                        apply_exact(code, patches)
                        task_fingerprints[instance_id] = fingerprint(
                            {"task_type": task_types, "input": code, "patches": patches}
                        )
                        code_paths = {item["path"] for item in code}
                        manifest_paths = {item["path"] for item in record.get("file_manifest", []) if item.get("type") == "code"}
                        if code_paths != manifest_paths:
                            raise ValueError("input does not contain every code file")
                    if task == "image-repair":
                        reported_ratio = float(record.get("metadata", {}).get("visual_difference", {}).get("max_changed_ratio", 0))
                        src = record.get("src_screenshot", [])
                        dst = record.get("dst_screenshot", [])
                        if not src or len(src) != len(dst):
                            raise ValueError("image-repair screenshot pairing is incomplete")
                        actual_ratio = max(
                            changed_ratio(
                                (Path(left) if Path(left).is_absolute() else release_root / left).resolve(),
                                (Path(right) if Path(right).is_absolute() else release_root / right).resolve(),
                            )
                            for left, right in zip(src, dst, strict=True)
                        )
                        if actual_ratio < 0.01:
                            raise ValueError("image-repair fails 1% paired-image gate")
                        if abs(actual_ratio - reported_ratio) > 0.0000015:
                            raise ValueError(
                                f"image-repair pixel ratio metadata mismatch: actual={actual_ratio:.6f}, "
                                f"reported={reported_ratio:.6f}"
                            )
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{name}:{line_number}: {type(exc).__name__}: {exc}")
        ids[task] = seen
        pair_fingerprints[task] = task_fingerprints
        counts[task] = len(seen)
        task_count_distributions[task] = {str(key): value for key, value in sorted(distribution.items())}
        if task in {"text-editing", "image-editing", "text-repair", "image-repair"}:
            if set(distribution) != set(range(1, 8)):
                errors.append(f"{name}: task-count distribution does not cover 1--7: {dict(distribution)}")
            elif max(distribution.values()) - min(distribution.values()) > 1:
                errors.append(f"{name}: task-count distribution is not even: {dict(distribution)}")

    expected = {
        "text-generation": args.expected_generate,
        "image-generation": args.expected_generate,
        "text-editing": args.expected_edit,
        "image-editing": args.expected_edit,
        "image-repair": args.expected_image_repair,
    }
    for task, count in expected.items():
        if counts.get(task) != count:
            errors.append(f"{task}: count={counts.get(task)}, expected={count}")
    for left, right in (("text-generation", "image-generation"), ("text-editing", "image-editing")):
        if ids[left] != ids[right]:
            errors.append(f"paired ids differ: {left} vs {right}")
        else:
            mismatched = [instance_id for instance_id in ids[left]
                          if pair_fingerprints[left].get(instance_id) != pair_fingerprints[right].get(instance_id)]
            if mismatched:
                errors.append(f"paired payloads differ: {left} vs {right}: {mismatched[:5]}")
    if not ids["image-repair"].issubset(ids["text-repair"]):
        errors.append("image-repair ids are not a subset of text-repair ids")
    else:
        mismatched = [instance_id for instance_id in ids["image-repair"]
                      if pair_fingerprints["image-repair"].get(instance_id)
                      != pair_fingerprints["text-repair"].get(instance_id)]
        if mismatched:
            errors.append(f"paired payloads differ: text-repair vs image-repair: {mismatched[:5]}")

    # Manifest and portable provenance are part of the release contract, not
    # sidecar operator state.  Recompute every published checksum and prove
    # the 6503 -> 6502 token-gate decision from release-local evidence.
    try:
        manifest_path = release_root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_reference") != "webcoding-sft-v2":
            raise ValueError("manifest schema reference mismatch")
        for task, name in TASK_FILES.items():
            entry = manifest["tasks"][MANIFEST_TASK_KEYS[task]]
            task_path = release_root / entry["jsonl"]
            if int(entry["count"]) != counts[task]:
                raise ValueError(f"manifest count mismatch for {task}")
            if entry["sha256"] != checksum(task_path):
                raise ValueError(f"manifest checksum mismatch for {task}")

        provenance_root = release_root / "provenance"
        provenance = manifest["provenance"]
        for name, entry in provenance.items():
            path = provenance_root / name
            if entry["sha256"] != checksum(path):
                raise ValueError(f"provenance checksum mismatch for {name}")

        eligible_ids = read_unique_ids(provenance_root / "eligible_40k.ids.txt")
        edit_ids = read_unique_ids(provenance_root / "edit_3000.ids.txt")
        repair_candidate_ids = read_unique_ids(provenance_root / "repair_candidates.ids.txt")
        if eligible_ids != ids["text-generation"]:
            raise ValueError("eligible token-gate IDs differ from generation release IDs")
        if edit_ids != ids["text-editing"]:
            raise ValueError("selected edit IDs differ from edit release IDs")
        if not ids["text-repair"].issubset(repair_candidate_ids):
            raise ValueError("released text-repair IDs are outside repair candidate IDs")

        token_records = list(
            json.loads(line) for line in
            (provenance_root / "token_gate_audit.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        token_ids = [str(record["instance_id"]) for record in token_records]
        if len(token_ids) != args.expected_source or len(token_ids) != len(set(token_ids)):
            raise ValueError("token-gate audit source count/uniqueness mismatch")
        audited_eligible = {
            str(record["instance_id"]) for record in token_records
            if record["status"] == "eligible" and int(record["tokens"]) <= 40000
        }
        invalid_gate = [record for record in token_records if (
            (record["status"] == "eligible" and int(record["tokens"]) > 40000)
            or (record["status"] != "eligible" and int(record["tokens"]) <= 40000)
        )]
        if invalid_gate or audited_eligible != eligible_ids:
            raise ValueError("token-gate audit does not prove the 40K decision")
        selection = json.loads(
            (provenance_root / "selection_manifest.json").read_text(encoding="utf-8")
        )
        if (int(selection["source_input_count"]) != args.expected_source
                or int(selection["eligible_count"]) != args.expected_generate
                or int(selection["edit_count"]) != args.expected_edit
                or int(selection["repair_candidate_count"]) != len(repair_candidate_ids)
                or int(selection["maximum_qwen_tokens"]) != 40000):
            raise ValueError("selection manifest counts/limits mismatch")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"manifest/provenance: {type(exc).__name__}: {exc}")

    summary = {
        "status": "pass" if not errors else "fail",
        "counts": counts,
        "task_count_distributions": task_count_distributions,
        "errors": errors[:1000],
        "error_count": len(errors),
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
