"""Materialize planned Edit queries as versioned projects with browser evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any

from inspiration_library.doc_api import DocApiClient
from inspiration_library.production import (
    admission_decision,
    apply_exact_patches,
    invert_exact_patches,
    parse_json_object,
    validate_browser_checks,
)
from inspiration_library.production_browser import verify_project
from inspiration_library.state_hypergraph import CapabilityEdge, load_capability_library


GENERATION_SYSTEM = """You are implementing one incremental Edit in an existing offline frontend project.
Return JSON only. Preserve all unrelated behavior and visual design. Use only local HTML, CSS, and JavaScript.
Implement every supplied browser check exactly, including stable selectors. Do not use CDNs, remote assets,
network calls, test-only shortcuts, hidden answer data, or JavaScript injected by the evaluator. Make the
smallest coherent change. Each patch is an exact text replacement whose search string occurs once in the
supplied source. Never use ellipses or omit unchanged text inside a search/replace value."""


TEXT_SUFFIXES = {".html", ".css", ".js", ".mjs", ".jsx", ".ts", ".tsx"}


def _write_json_once(path: Path, payload: Any) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != rendered:
            raise ValueError(f"immutable output differs: {path}")
        return
    path.write_text(rendered, encoding="utf-8")


def _append_jsonl_once(path: Path, row: dict[str, Any], *, id_field: str) -> None:
    seen: set[str] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value = json.loads(line).get(id_field)
                if isinstance(value, str):
                    seen.add(value)
    if row[id_field] in seen:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_project_files(project: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(project.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in {".git", "node_modules", ".harness"} for part in path.parts):
            continue
        files[path.relative_to(project).as_posix()] = path.read_text(encoding="utf-8")
    if "index.html" not in files:
        raise ValueError(f"project has no index.html: {project}")
    return files


def project_digest(files: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for name, content in sorted(files.items()):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content.encode("utf-8"))
    return digest.hexdigest()


def changed_bytes(source: dict[str, str], target: dict[str, str]) -> int:
    return sum(
        abs(len(target[name].encode("utf-8")) - len(source[name].encode("utf-8")))
        + sum(a != b for a, b in zip(source[name], target[name]))
        for name in sorted(source)
    )


def validate_patch_response(
    payload: dict[str, Any], *, capability: CapabilityEdge, source_files: dict[str, str]
) -> tuple[list[dict[str, str]], dict[str, str]]:
    if payload.get("capability_id") != capability.id:
        raise ValueError("patch response capability_id does not match the requested Edit")
    patches = payload.get("patches")
    if not isinstance(patches, list):
        raise ValueError("patch response requires patches")
    allowed = set(capability.write_files)
    normalized: list[dict[str, str]] = []
    for row in patches:
        if not isinstance(row, dict):
            raise ValueError("every patch must be an object")
        file_name = row.get("file")
        if file_name not in allowed:
            raise ValueError(f"patch writes a file outside capability scope: {file_name}")
        normalized.append(
            {
                "file": str(file_name),
                "search": row.get("search"),
                "replace": row.get("replace"),
            }
        )
    target_files = apply_exact_patches(source_files, normalized)
    if target_files == source_files:
        raise ValueError("patch response did not change the project")
    replay = apply_exact_patches(source_files, normalized)
    if replay != target_files:
        raise ValueError("patch replay is not deterministic")
    restored = apply_exact_patches(target_files, invert_exact_patches(normalized))
    if restored != source_files:
        raise ValueError("inverse patch does not restore the source")
    return normalized, target_files


def stage_schedule() -> tuple[dict[str, Any], ...]:
    return (
        {"id": "q1", "source": "seed", "capability_index": 0, "includes": [0]},
        {"id": "q2", "source": "q1", "capability_index": 1, "includes": [0, 1]},
        {"id": "q3", "source": "q1", "capability_index": 2, "includes": [0, 2]},
        {"id": "q2_then_q3", "source": "q2", "capability_index": 2, "includes": [0, 1, 2]},
        {"id": "q3_then_q2", "source": "q3", "capability_index": 1, "includes": [0, 1, 2]},
    )


def _source_context(files: dict[str, str]) -> str:
    return "\n\n".join(
        f"===== FILE: {name} =====\n{content}" for name, content in sorted(files.items())
    )


def _repair_failed_stage(
    *,
    stage_id: str,
    stage_dir: Path,
    failed_project: Path,
    capability: CapabilityEdge,
    cumulative_checks: list[dict[str, Any]],
    regression_checks: list[dict[str, Any]],
    failed_verification: dict[str, Any],
    prior_result: dict[str, Any],
    run_dir: Path,
    client: DocApiClient,
) -> dict[str, Any]:
    repair_id = f"repair_{stage_id}_1"
    repair_project = stage_dir / "project_repair_1"
    repair_metadata = stage_dir / "stage_repair_1.json"
    if repair_metadata.exists():
        return json.loads(repair_metadata.read_text(encoding="utf-8"))
    failed_files = read_project_files(failed_project)
    response_path = run_dir / "provider" / "responses" / f"{repair_id}.txt"
    if response_path.exists():
        payload = parse_json_object(response_path.read_text(encoding="utf-8"))
    else:
        payload, _ = client.chat_json(
            request_id=repair_id,
            system_prompt=GENERATION_SYSTEM,
            stable_context=(
                "FAILED TARGET PROJECT\n"
                + _source_context(failed_files)
                + "\n\nEDIT SPECIFICATION\n"
                + json.dumps(capability.to_dict(), ensure_ascii=False)
                + "\n\nFAILED BROWSER EVIDENCE\n"
                + json.dumps(failed_verification, ensure_ascii=False)
                + "\n\nALL REQUIRED CHECKS\n"
                + json.dumps(cumulative_checks, ensure_ascii=False)
            ),
            task=(
                "Repair only the failed target. Return {capability_id, implementation_summary, "
                "patches}, where patches contains exact {file, search, replace} replacements. "
                "Use the browser evidence to fix the actual state-update defect while preserving "
                "all passing behavior."
            ),
            max_tokens=10000,
            stream=True,
        )
    patches, repaired_files = validate_patch_response(
        payload, capability=capability, source_files=failed_files
    )
    if repair_project.exists():
        raise FileExistsError(f"incomplete repair project already exists: {repair_project}")
    shutil.copytree(failed_project, repair_project)
    for name, content in repaired_files.items():
        (repair_project / name).write_text(content, encoding="utf-8")
    _write_json_once(
        stage_dir / "repair_patch_1.json",
        {
            "repair_id": repair_id,
            "capability_id": capability.id,
            "implementation_summary": payload.get("implementation_summary", ""),
            "patches": patches,
        },
    )
    verification_dir = stage_dir / "verification_repair_1"
    capability_result = verify_project(
        repair_project,
        cumulative_checks,
        verification_dir,
        label="capabilities",
    )
    regression_result = verify_project(
        repair_project,
        regression_checks,
        verification_dir,
        label="regressions",
    )
    original_source_files = read_project_files(Path(prior_result["source_project"]))
    result = {
        **prior_result,
        "status": (
            "ok"
            if capability_result["status"] == "ok" and regression_result["status"] == "ok"
            else "error"
        ),
        "target_project": str(repair_project.resolve()),
        "target_sha256": project_digest(repaired_files),
        "changed_bytes": changed_bytes(original_source_files, repaired_files),
        "capability_browser_status": capability_result["status"],
        "regression_browser_status": regression_result["status"],
        "resource_closure_passed": not capability_result["remote_requests"]
        and not regression_result["remote_requests"],
        "repair_of": str(failed_project.resolve()),
        "repair_request_count": 1,
    }
    _write_json_once(repair_metadata, result)
    if result["status"] != "ok":
        raise ValueError(f"one targeted repair failed browser verification: {stage_id}")
    return result


def materialize_stage(
    *,
    stage_id: str,
    source_project: Path,
    capability: CapabilityEdge,
    cumulative_checks: list[dict[str, Any]],
    regression_checks: list[dict[str, Any]],
    run_dir: Path,
    client: DocApiClient,
) -> dict[str, Any]:
    stage_dir = run_dir / "stages" / stage_id
    metadata_path = stage_dir / "stage.json"
    project_dir = stage_dir / "project"
    if metadata_path.exists():
        metadata_candidates = [metadata_path, *sorted(stage_dir.glob("stage_recheck_*.json"))]
        result = json.loads(metadata_candidates[-1].read_text(encoding="utf-8"))
        if not project_dir.is_dir():
            raise FileNotFoundError(f"stage metadata exists without project: {stage_id}")
        if result.get("status") == "ok":
            return result
        recheck_index = len(list(stage_dir.glob("stage_recheck_*.json"))) + 1
        verification_dir = stage_dir / f"verification_recheck_{recheck_index}"
        capability_result = verify_project(
            project_dir,
            cumulative_checks,
            verification_dir,
            label="capabilities",
        )
        regression_result = verify_project(
            project_dir,
            regression_checks,
            verification_dir,
            label="regressions",
        )
        result = {
            **result,
            "status": (
                "ok"
                if capability_result["status"] == "ok"
                and regression_result["status"] == "ok"
                else "error"
            ),
            "capability_browser_status": capability_result["status"],
            "regression_browser_status": regression_result["status"],
            "resource_closure_passed": not capability_result["remote_requests"]
            and not regression_result["remote_requests"],
            "recheck_of": str(metadata_candidates[-1]),
        }
        _write_json_once(stage_dir / f"stage_recheck_{recheck_index}.json", result)
        if result["status"] != "ok":
            return _repair_failed_stage(
                stage_id=stage_id,
                stage_dir=stage_dir,
                failed_project=project_dir,
                capability=capability,
                cumulative_checks=cumulative_checks,
                regression_checks=regression_checks,
                failed_verification=capability_result,
                prior_result=result,
                run_dir=run_dir,
                client=client,
            )
        return result

    source_files = read_project_files(source_project)
    response_path = run_dir / "provider" / "responses" / f"generate_{stage_id}.txt"
    if response_path.exists():
        payload = parse_json_object(response_path.read_text(encoding="utf-8"))
    else:
        payload, _ = client.chat_json(
            request_id=f"generate_{stage_id}",
            system_prompt=GENERATION_SYSTEM,
            stable_context=(
                "SOURCE PROJECT\n"
                + _source_context(source_files)
                + "\n\nEDIT SPECIFICATION\n"
                + json.dumps(capability.to_dict(), ensure_ascii=False)
                + "\n\nCUMULATIVE BROWSER CHECKS\n"
                + json.dumps(cumulative_checks, ensure_ascii=False)
                + "\n\nREGRESSION REQUIREMENTS\n"
                + json.dumps(regression_checks, ensure_ascii=False)
            ),
            task=(
                "Return {capability_id, implementation_summary, patches}. patches is a list "
                "of {file, search, replace}. Use only files listed in write_files. Every search "
                "must be copied exactly from the source and occur exactly once. Keep the patch "
                "small while fully satisfying the Edit and all browser checks."
            ),
            max_tokens=20000,
            stream=True,
        )
    patches, target_files = validate_patch_response(
        payload, capability=capability, source_files=source_files
    )
    if project_dir.exists():
        raise FileExistsError(f"incomplete stage project already exists: {project_dir}")
    shutil.copytree(source_project, project_dir)
    for name, content in target_files.items():
        (project_dir / name).write_text(content, encoding="utf-8")
    _write_json_once(
        stage_dir / "patch.json",
        {
            "capability_id": capability.id,
            "implementation_summary": payload.get("implementation_summary", ""),
            "patches": patches,
        },
    )
    capability_result = verify_project(
        project_dir,
        cumulative_checks,
        stage_dir / "verification",
        label="capabilities",
    )
    regression_result = verify_project(
        project_dir,
        regression_checks,
        stage_dir / "verification",
        label="regressions",
    )
    result = {
        "schema_version": "webcoding-materialized-edit-stage-v1",
        "stage_id": stage_id,
        "status": (
            "ok"
            if capability_result["status"] == "ok" and regression_result["status"] == "ok"
            else "error"
        ),
        "capability_id": capability.id,
        "source_project": str(source_project.resolve()),
        "target_project": str(project_dir.resolve()),
        "source_sha256": project_digest(source_files),
        "target_sha256": project_digest(target_files),
        "changed_bytes": changed_bytes(source_files, target_files),
        "patch_replay_passed": True,
        "capability_browser_status": capability_result["status"],
        "regression_browser_status": regression_result["status"],
        "resource_closure_passed": not capability_result["remote_requests"]
        and not regression_result["remote_requests"],
        "model": client.chat_model,
        "sdk_retries": 0,
        "outer_retries": 0,
    }
    _write_json_once(metadata_path, result)
    if result["status"] != "ok":
        raise ValueError(f"materialized stage failed browser verification: {stage_id}")
    return result


def run_materialization(
    *,
    seed_project: Path,
    capability_library_path: Path,
    query_path: Path,
    regression_profile_path: Path,
    run_dir: Path,
    client: DocApiClient,
    stop_after_stage: str | None = None,
) -> dict[str, Any]:
    seed_project = seed_project.resolve()
    capabilities = load_capability_library(capability_library_path)
    if len(capabilities) != 4:
        raise ValueError("the fork/join materializer requires exactly four capabilities")
    all_checks = [
        validate_browser_checks(list(capability.browser_checks))[0]
        for capability in capabilities
    ]
    profile = json.loads(regression_profile_path.read_text(encoding="utf-8"))
    regression_checks = validate_browser_checks(profile.get("core_regression_checks"))
    queries = [
        json.loads(line)
        for line in query_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if [row.get("capability_id") for row in queries] != [item.id for item in capabilities]:
        raise ValueError("query order and capability library differ")
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "run_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "ok":
            raise ValueError("existing materialization manifest is not successful")
        return manifest

    seed_verification_path = run_dir / "seed_verification" / "regressions.json"
    if seed_verification_path.exists():
        seed_verification = json.loads(seed_verification_path.read_text(encoding="utf-8"))
    else:
        seed_verification = verify_project(
            seed_project,
            regression_checks,
            run_dir / "seed_verification",
            label="regressions",
        )
    if seed_verification["status"] != "ok":
        raise ValueError("Seed failed the regression baseline")

    projects: dict[str, Path] = {"seed": seed_project}
    stages: dict[str, dict[str, Any]] = {}
    for spec in stage_schedule():
        source = projects[spec["source"]]
        stage = materialize_stage(
            stage_id=spec["id"],
            source_project=source,
            capability=capabilities[spec["capability_index"]],
            cumulative_checks=[all_checks[index] for index in spec["includes"]],
            regression_checks=regression_checks,
            run_dir=run_dir,
            client=client,
        )
        stages[spec["id"]] = stage
        projects[spec["id"]] = Path(stage["target_project"])
        if stop_after_stage == spec["id"]:
            partial = {
                "schema_version": "webcoding-full-edit-materialization-precheck-v1",
                "status": "partial_ok",
                "completed_stage": spec["id"],
                "stage": stage,
                "next_action": "resume the same run without stop_after_stage",
            }
            _write_json_once(run_dir / f"precheck_{spec['id']}.json", partial)
            return partial

    order_ok = all(stages[name]["status"] == "ok" for name in ("q2_then_q3", "q3_then_q2"))
    candidates = [stages["q2_then_q3"], stages["q3_then_q2"]]
    selected_merge = min(candidates, key=lambda row: (row["changed_bytes"], row["stage_id"]))
    merge = {
        "status": "ok" if order_ok else "error",
        "parents": ["q2_then_q3", "q3_then_q2"],
        "selected_parent": selected_merge["stage_id"],
        "selection_rule": "both orders pass identical cumulative browser checks; choose fewer changed bytes",
        "browser_order_audit_passed": order_ok,
    }
    _write_json_once(run_dir / "order_audit.json", merge)
    if not order_ok:
        raise ValueError("Q2→Q3 and Q3→Q2 did not both pass")

    q4 = materialize_stage(
        stage_id="q4",
        source_project=Path(selected_merge["target_project"]),
        capability=capabilities[3],
        cumulative_checks=all_checks,
        regression_checks=regression_checks,
        run_dir=run_dir,
        client=client,
    )
    stages["q4"] = q4
    projects["q4"] = Path(q4["target_project"])

    training_mapping = (
        (0, "seed", "q1"),
        (1, "q1", "q2"),
        (2, "q1", "q3"),
        (3, selected_merge["stage_id"], "q4"),
    )
    training_records: list[dict[str, Any]] = []
    for query_index, source_id, target_id in training_mapping:
        target_stage = stages[target_id]
        decision = admission_decision(
            {
                "source_verified": source_id == "seed"
                or stages[source_id]["status"] == "ok",
                "target_generated": target_stage["target_sha256"] != target_stage["source_sha256"],
                "target_browser_passed": target_stage["capability_browser_status"] == "ok",
                "regression_passed": target_stage["regression_browser_status"] == "ok",
                "resource_closure_passed": target_stage["resource_closure_passed"],
                "patch_replay_passed": target_stage["patch_replay_passed"],
                "order_audit_passed": order_ok,
            }
        )
        record = {
            **queries[query_index],
            "source_project": str(projects[source_id].resolve()),
            "target_project": str(projects[target_id].resolve()),
            "target_code_status": "generated_and_browser_verified",
            "generation_model": client.chat_model,
            "training_admission": decision,
            "status": "ok" if decision["status"] == "eligible" else "error",
        }
        training_records.append(record)
        _append_jsonl_once(
            run_dir / "training_records.jsonl", record, id_field="record_id"
        )

    manifest = {
        "schema_version": "webcoding-full-edit-materialization-run-v1",
        "status": "ok" if all(row["status"] == "ok" for row in training_records) else "error",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed_project": str(seed_project),
        "chat_model": client.chat_model,
        "sdk_retries": 0,
        "outer_retries": 0,
        "stage_count": len(stages),
        "training_record_count": len(training_records),
        "eligible_training_record_count": sum(
            row["training_admission"]["status"] == "eligible" for row in training_records
        ),
        "order_audit": merge,
        "stages": stages,
    }
    _write_json_once(manifest_path, manifest)
    return manifest


__all__ = [
    "changed_bytes",
    "materialize_stage",
    "project_digest",
    "read_project_files",
    "run_materialization",
    "stage_schedule",
    "validate_patch_response",
]
