#!/usr/bin/env python3
"""Independent quality gate for interaction-rich Edit and controlled Repair."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from reverse.construct_common import apply_search_replace_exact
from reverse.task_specs import repair_defect_metadata


def _image_paths(record: dict[str, Any]) -> list[str]:
    images = record.get("images", {})
    return [
        str(item.get("path", ""))
        for key in ("src_screenshot", "dst_screenshot", "interaction_screenshot")
        for item in images.get(key, [])
        if isinstance(item, dict)
    ]


def _check_patch_round_trip(record: dict[str, Any]) -> None:
    patches = record.get("label_modified_files")
    if not isinstance(patches, list) or not patches:
        raise ValueError("missing exact patches")
    if record.get("task") == "text-editing":
        source = record.get("instruction", {}).get("src_code")
        expected = record.get("reference", {}).get("dst_code")
    else:
        source = record.get("instruction")
        expected = record.get("reference", {}).get("dst_code")
    if not isinstance(source, list) or not isinstance(expected, list):
        raise ValueError("missing source/reference code bundles")
    if apply_search_replace_exact(source, patches) != expected:
        raise ValueError("patch output does not exactly reconstruct reference")


def audit_record(record: dict[str, Any], *, require_files: bool = True) -> list[str]:
    errors: list[str] = []
    if record.get("status") != "ok":
        return [f"constructor_status:{record.get('status', 'missing')}"]
    try:
        _check_patch_round_trip(record)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"patch_round_trip:{exc}")

    if require_files:
        missing = [path for path in _image_paths(record) if not path or not Path(path).is_file()]
        if missing:
            errors.append(f"missing_images:{len(missing)}")

    task = record.get("task")
    task_types = record.get("task_type", [])
    if not isinstance(task_types, list) or not task_types:
        errors.append("missing_task_types")
        return errors

    if task == "text-editing":
        interactions = record.get("interaction_type", [])
        if interactions:
            evidence = record.get("browser_evidence", [])
            if len(evidence) != len(task_types) or any(item.get("status") != "ok" for item in evidence):
                errors.append("interaction_browser_evidence_incomplete")
            differences = record.get("interaction_visual_differences", [])
            if len(differences) != len(task_types):
                errors.append("interaction_screenshot_difference_incomplete")
            elif any(item.get("max_changed_ratio", 0) < item.get("minimum_changed_ratio", 0) for item in differences):
                errors.append("interaction_screenshot_difference_below_threshold")
        variant = record.get("image_input_variant")
        images = record.get("images", {})
        if variant in {"target_image", "source_target_images"} and not images.get("dst_screenshot"):
            errors.append("target_image_variant_without_target_image")
    elif task == "text-repair":
        defect_types = record.get("defect_type", task_types)
        try:
            metadata = repair_defect_metadata(defect_types)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"repair_taxonomy:{exc}")
            return errors
        if record.get("repair_family") != metadata["repair_family"]:
            errors.append("repair_family_mismatch")
        if record.get("repair_subfamily") != metadata["repair_subfamily"]:
            errors.append("repair_subfamily_mismatch")
        if record.get("benchmark_alignment") != metadata["benchmark_alignment"]:
            errors.append("benchmark_alignment_mismatch")
        if len(metadata["repair_family"]) != 1:
            errors.append("repair_record_mixes_families")
            return errors
        family = metadata["repair_family"][0]
        evidence = record.get("failure_evidence", [])
        if not evidence or any(item.get("status") != "reproduced" for item in evidence):
            errors.append("repair_failure_evidence_missing")
        elif family == "runtime_repair" and not any(item.get("introduced_failures") for item in evidence):
            errors.append("runtime_defect_only_failure_missing")
        elif family == "visual_repair":
            visual = record.get("visual_difference", {})
            if visual.get("max_changed_ratio", 0) < visual.get("minimum_changed_ratio", 1):
                errors.append("visual_repair_difference_below_threshold")
        elif family == "interaction_repair" and len(evidence) != len(defect_types):
            errors.append("interaction_repair_contract_count_mismatch")
        elif family == "quality_refinement" and not any(item.get("regressions") for item in evidence):
            errors.append("quality_regression_not_measured")
    else:
        errors.append(f"unsupported_task:{task}")
    return errors


def audit_jsonl(path: Path, *, require_files: bool = True) -> dict[str, Any]:
    rows = passed = 0
    error_counts: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            rows += 1
            try:
                record = json.loads(line)
                errors = audit_record(record, require_files=require_files)
            except Exception as exc:  # noqa: BLE001
                errors = [f"invalid_json_or_record:{exc}"]
                record = {}
            if not errors:
                passed += 1
            else:
                error_counts.update(errors)
                if len(examples) < 20:
                    examples.append({
                        "line": line_number,
                        "instance_id": record.get("instance_id", ""),
                        "errors": errors,
                    })
    return {
        "input": str(path.resolve()),
        "rows": rows,
        "passed": passed,
        "failed": rows - passed,
        "pass_rate": passed / rows if rows else 0.0,
        "error_counts": dict(error_counts),
        "examples": examples,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--report-jsonl", type=Path, required=True)
    parser.add_argument("--minimum-pass-rate", type=float, default=1.0)
    parser.add_argument("--skip-file-check", action="store_true")
    args = parser.parse_args()
    report = audit_jsonl(args.input, require_files=not args.skip_file_check)
    report.update({
        "status": "pass" if report["rows"] and report["pass_rate"] >= args.minimum_pass_rate else "fail",
        "minimum_pass_rate": args.minimum_pass_rate,
        "audited_at": datetime.now(timezone.utc).isoformat(),
    })
    args.report_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with args.report_jsonl.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, ensure_ascii=False) + "\n")
        handle.flush()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
