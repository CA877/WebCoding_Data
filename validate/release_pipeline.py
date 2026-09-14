from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .content_qc import IssueSet, audit_code_blob, classify_issues
from .image_qc import compare_images, inspect_image
from .io import append_jsonl, read_jsonl, write_json
from .patches import validate_and_apply_patches
from .records import (
    EXPECTED_TASK_BY_RELEASE_FILE,
    IMAGE_ROOT_BY_RELEASE_FILE,
    all_code,
    image_refs,
    normalized_domain,
    normalized_hash,
    sample_id,
    target_code_for_hash,
)


@dataclass
class SampleDecision:
    status: str
    issues: IssueSet
    metadata: dict[str, Any] = field(default_factory=dict)


def audit_release_record(
    record: dict[str, Any],
    *,
    file_name: str,
    line_no: int,
    release_root: Path | None = None,
    check_images: bool = True,
    require_output_files: bool = True,
) -> SampleDecision:
    sid = sample_id(record, file_name, line_no)
    if "__parse_error__" in record:
        return SampleDecision("reject", classify_issues(["json_parse_error"]), {"parse_error": record["__parse_error__"]})

    issues = audit_code_blob(all_code(record), sample_key=sid)
    metadata: dict[str, Any] = {"instance_id": sid, "domain": normalized_domain(record)}
    expected_task = EXPECTED_TASK_BY_RELEASE_FILE.get(file_name)
    task_value = record.get("task")
    if expected_task and task_value != expected_task:
        issues.p0.append("task_field_mismatch_or_missing")
    if not isinstance(record.get("instance_id"), str) or not record.get("instance_id"):
        issues.p0.append("missing_or_empty_instance_id")

    if "edit" in file_name or "repair" in file_name:
        patch_check = validate_and_apply_patches(record, require_output_files=require_output_files)
        if patch_check.issues:
            issues.p0.extend(patch_check.issues)
        metadata["normalized_patch_count"] = len(patch_check.normalized_patches)

    if "generate" in file_name and record.get("patches"):
        issues.p0.append("generation_unexpected_patches_field")

    image_root = IMAGE_ROOT_BY_RELEASE_FILE.get(file_name)
    if image_root is not None:
        refs = image_refs(record)
        if not refs:
            issues.p0.append("image_task_missing_image_references")
        if check_images and release_root is not None:
            image_details = []
            for key, rel in refs:
                full = release_root / image_root / rel
                check = inspect_image(full)
                image_details.append({"key": key, "path": rel, "issues": check.issues, "width": check.width, "height": check.height})
                for issue in check.issues:
                    if issue in {"image_file_missing", "image_file_empty", "image_decode_failed"}:
                        issues.p0.append(f"{key}_{issue}")
                    else:
                        issues.p1.append(f"{key}_{issue}")
            metadata["images"] = image_details
        if file_name == "image-repair.jsonl":
            if not record.get("dst_screenshot"):
                issues.p0.append("image_repair_missing_dst_screenshot")
            elif check_images and release_root is not None and record.get("src_screenshot"):
                src_rel = record["src_screenshot"][0]
                dst_rel = record["dst_screenshot"][0]
                diff = compare_images(release_root / image_root / src_rel, release_root / image_root / dst_rel)
                metadata["image_repair_diff"] = {
                    "rms": diff.rms,
                    "changed_pixel_ratio": diff.changed_pixel_ratio,
                    "issues": diff.issues,
                }
                if diff.issues:
                    issues.p0.extend(diff.issues)

    issues.p0 = sorted(set(issues.p0))
    issues.p1 = sorted(set(issues.p1))
    issues.p2 = sorted(set(issues.p2))
    return SampleDecision(issues.status, issues, metadata)


def run_release_quality_pipeline(
    release_root: Path,
    out_dir: Path,
    *,
    check_images: bool = True,
    require_output_files: bool = True,
) -> dict[str, Any]:
    jsonl_dir = release_root / "jsonl"
    out_dir.mkdir(parents=True, exist_ok=True)
    accepted_path = out_dir / "accepted.jsonl"
    rejected_path = out_dir / "rejected.jsonl"
    review_path = out_dir / "review.jsonl"
    issues_path = out_dir / "sample_issues.jsonl"
    for path in (accepted_path, rejected_path, review_path, issues_path):
        if path.exists():
            path.unlink()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    counts: Counter[str] = Counter()
    issue_counts: Counter[str] = Counter()
    file_counts: dict[str, Counter[str]] = defaultdict(Counter)
    instance_seen: dict[str, list[str]] = defaultdict(list)
    domain_seen: dict[str, list[str]] = defaultdict(list)
    code_hash_seen: dict[str, list[str]] = defaultdict(list)

    for jsonl_path in sorted(jsonl_dir.glob("*.jsonl")):
        file_name = jsonl_path.name
        for line_no, record in read_jsonl(jsonl_path):
            decision = audit_release_record(
                record,
                file_name=file_name,
                line_no=line_no,
                release_root=release_root,
                check_images=check_images,
                require_output_files=require_output_files,
            )
            sid = sample_id(record, file_name, line_no)
            counts[decision.status] += 1
            file_counts[file_name][decision.status] += 1
            for issue in decision.issues.all:
                issue_counts[issue] += 1
            row = {
                "file": file_name,
                "line": line_no,
                "instance_id": sid,
                "qc_status": decision.status,
                "qc_issues": decision.issues.all,
                "qc_metadata": decision.metadata,
            }
            if decision.status == "accept":
                append_jsonl(accepted_path, record | {"qc_status": "accepted", "qc_issues": []})
            elif decision.status == "review":
                append_jsonl(review_path, record | {"qc_status": "review", "qc_issues": decision.issues.all})
            else:
                append_jsonl(rejected_path, record | {"qc_status": "rejected", "qc_issues": decision.issues.all})
            if decision.issues.all:
                append_jsonl(issues_path, row)

            instance_seen[sid].append(file_name)
            domain = normalized_domain(record)
            if domain:
                domain_seen[domain].append(sid)
            task = str(record.get("task") or EXPECTED_TASK_BY_RELEASE_FILE.get(file_name) or file_name)
            code = target_code_for_hash(record, task)
            if code:
                code_hash_seen[normalized_hash(code)].append(sid)

    duplicate_instances = {k: v for k, v in instance_seen.items() if len(v) > 1}
    duplicate_domains = {k: v for k, v in domain_seen.items() if len(v) > 1}
    duplicate_code = {k: v for k, v in code_hash_seen.items() if len(v) > 1}
    report = {
        "release_root": str(release_root),
        "out_dir": str(out_dir),
        "counts": dict(counts),
        "files": {name: dict(counter) for name, counter in file_counts.items()},
        "issue_counts": dict(issue_counts.most_common()),
        "outputs": {
            "accepted": str(accepted_path),
            "review": str(review_path),
            "rejected": str(rejected_path),
            "sample_issues": str(issues_path),
        },
        "leakage_risk": {
            "duplicate_instance_groups": len(duplicate_instances),
            "duplicate_domain_groups": len(duplicate_domains),
            "duplicate_code_hash_groups": len(duplicate_code),
            "duplicate_instance_examples": dict(list(duplicate_instances.items())[:30]),
            "duplicate_domain_examples": dict(list(duplicate_domains.items())[:30]),
            "duplicate_code_hash_examples": dict(list(duplicate_code.items())[:30]),
        },
    }
    write_json(out_dir / "quality_pipeline_summary.json", report)
    return report
