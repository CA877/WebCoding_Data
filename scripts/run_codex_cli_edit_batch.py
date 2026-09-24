#!/usr/bin/env python3
"""Run a bounded batch of 0921 Edit cases through Codex CLI."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.scripts.export_trajectory_dataset import (
    CODE_EXTENSIONS,
    IGNORED_CODE_FILES,
    apply_patches,
    make_patches,
)


WRAPPER = ROOT / "scripts" / "codex_cli_with_edit_skills.sh"
SHELL_GUARD = ROOT / "scripts" / "codex_shell_guard.py"
MAX_SUBTASK_TIMEOUT_SECONDS = 120


def save_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def code_sha256(code: list[dict[str, str]]) -> str:
    payload = json.dumps(code, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def snapshot_code(frontend: Path) -> list[dict[str, str]]:
    bundle = []
    for path in sorted(frontend.rglob("*")):
        if (
            not path.is_file()
            or path.suffix.lower() not in CODE_EXTENSIONS
            or path.name in IGNORED_CODE_FILES
            or any(part in {".git", ".agents", "node_modules"} for part in path.parts)
        ):
            continue
        bundle.append(
            {
                "path": path.relative_to(frontend).as_posix(),
                "code": path.read_text(encoding="utf-8"),
            }
        )
    return bundle


def run_bounded(command: list[str], *, cwd: Path, stream, timeout: int, env: dict) -> tuple[str, int | None]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=stream,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=env,
    )
    try:
        return "ok", process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        return "timeout", None


def materialize(case: dict, destination: Path) -> Path:
    source = destination / "frontend"
    if source.exists():
        raise FileExistsError(f"case output already exists: {source}")
    source.mkdir(parents=True, exist_ok=True)
    skills = destination / ".agents" / "skills"
    skills.parent.mkdir(parents=True, exist_ok=True)
    skills.symlink_to(ROOT / "harness" / ".agents" / "skills", target_is_directory=True)
    for item in case["instruction"]["src_code"]:
        target = (source / str(item["path"])).resolve()
        target.relative_to(source.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(item["code"]), encoding="utf-8")
    return source


def prepare_dependencies(frontend: Path, case_dir: Path) -> dict:
    return {"status": "not-run", "reason": "fast-generation-mode"}


def prompt(case: dict, port: int, item: dict, task_number: int, total_tasks: int) -> str:
    instruction = f"[{item.get('task_type', 'edit')}] {item.get('description', '')}"
    return f"""You are generating one WebCoding Edit GT case.

Current working directory is an isolated case directory. The source project is in `frontend/`.
The 16 reusable component Skills are already available under `.agents/skills/`. Read the matching Skill `SKILL.md`: it is the source of truth for the API signature, parameters, host wiring, lifecycle, and cleanup. Do not open complete reference source files; use the signature and wiring example from `SKILL.md` and adapt only the host.

This is task {task_number} of {total_tasks} for this case. Implement only this task now:
{instruction}

Hard implementation rules (strict minimal-path policy):
- First inspect the existing route/component/container and identify ONE host entry point for each instruction. State that file and the existing event/data path mentally before editing.
- Read the matching Skill `SKILL.md`, then only the host file and its directly imported data/state file. Do not browse reference source, acceptance files, stylesheets, package manifests, or unrelated routes.
- Shell reads are guarded. Use at most three read commands, each targeted to a named file; project-wide listings, recursive scans, and repeated rereads will be rejected or truncated.
- Implement only the smallest end-to-end slice that makes the requested behavior observable: reuse the Skill's component and existing host state/events, then adapt its selectors/props. Do not build a complete product subsystem.
- Keep the patch local: normally 1-3 existing source files and under 120 changed lines per instruction. If more is needed, stop and choose a narrower integration instead of expanding scope.
- Once the core behavior is wired in those files, stop. Do not add optional polish, broad responsive work, extra states, or secondary screens in the same task.
- Preserve the existing framework, routes, DOM containers, data, styling system, and unrelated behavior. Never rewrite or delete a full source file, create a parallel app, add a new dependency, or fabricate a new data model.
- Do not copy an entire reference implementation. Copy only the smallest function/style fragment required for the selected host entry point.
- Do not run npm install, scaffold, migrate, or reformat. Use already-installed dependencies and the project's existing scripts only.
- Do not start a dev server, watcher, or browser. Do not run a full build, typecheck, audit, or dependency install. After the focused patch, inspect only the changed files and run at most one quick syntax check when it is directly available. Stop immediately after the patch is written.
- Implement only the task above. Do not inspect, plan, or implement any other task from the case.
- Identify one host entry point and patch only that entry point and its local wiring. There is no post-edit validation in fast generation mode. Implement the smallest core observable behavior; do not exhaustively implement every sentence or optional edge case.
- If a check fails, first decide whether the error points to a file or dependency you changed. If it is an existing unrelated source/dependency failure (for example a missing import in an untouched page), record it and stop immediately. Only then may you make one focused repair in the same changed files and rerun the same path.
- Do not stop at a written explanation: edit the files and end the turn immediately after the minimal patch is applied.
- Do not print credentials or modify the desktop Codex configuration.

At the end, summarize changed files, the browser path actually run, and any unresolved failure. Keep all changes inside this case directory.
"""


def run_one(job: dict, output: Path, ordinal: int, subtask_timeout: int) -> dict:
    case = job["case"]
    case_id = str(job.get("instance_id") or f"case-{ordinal}")
    case_dir = (output / case_id).resolve()
    case_dir.mkdir(parents=True, exist_ok=True)
    frontend = materialize(case, case_dir)
    dependency = prepare_dependencies(frontend, case_dir)
    guard_bin = case_dir / ".codex-shell-guard"
    guard_bin.mkdir(exist_ok=True)
    for command in ("rg", "sed", "cat", "find", "ls", "head", "tail"):
        (guard_bin / command).symlink_to(SHELL_GUARD)
    port = 19200 + ordinal
    tasks = case["instruction"]["description"]
    task_results = []
    original_code = snapshot_code(frontend)
    current_code = original_code
    all_patches: list[dict[str, str]] = []
    for task_number, item in enumerate(tasks, 1):
        log = case_dir / f"task_{task_number:02d}.codex.log"
        started = time.time()
        command = [str(WRAPPER), "exec", "-C", str(case_dir), "--skip-git-repo-check",
                   "--dangerously-bypass-approvals-and-sandbox", "-m", "gpt-5.6-luna",
                   "-c", "model_reasoning_effort=low",
                   "--json", "-o", str(case_dir / f"task_{task_number:02d}.last_message.txt"),
                   prompt(case, port, item, task_number, len(tasks))]
        run_env = {**os.environ, "PATH": f"{guard_bin}:{os.environ.get('PATH', '')}"}
        with log.open("w", encoding="utf-8") as stream:
            process_status, returncode = run_bounded(
                command,
                cwd=case_dir,
                stream=stream,
                timeout=subtask_timeout,
                env=run_env,
            )
        elapsed = round(time.time() - started, 3)
        task_status = "timeout" if process_status == "timeout" else (
            "ok" if returncode == 0 else "error"
        )
        patches: list[dict[str, str]] = []
        error = None
        if task_status == "ok":
            try:
                changed_code = snapshot_code(frontend)
                patches = make_patches(
                    current_code,
                    changed_code,
                    str(item.get("task_type") or "edit"),
                )
                if not patches:
                    raise ValueError("Codex exited successfully but produced no source change")
                if apply_patches(current_code, patches) != changed_code:
                    raise ValueError("exported subtask patches do not replay exactly")
                current_code = changed_code
                all_patches.extend(patches)
            except Exception as exc:  # noqa: BLE001
                task_status = "error"
                error = f"{type(exc).__name__}: {exc}"
        task_results.append(
            {
                "task": task_number,
                "task_type": str(item.get("task_type") or "edit"),
                "status": task_status,
                "elapsed_seconds": elapsed,
                "patch_count": len(patches),
                "log": str(log),
                **({"error": error} if error else {}),
            }
        )
        if task_status != "ok":
            break
    status = "ok" if len(task_results) == len(tasks) and all(
        item["status"] == "ok" for item in task_results
    ) else "error"
    if status == "ok" and apply_patches(original_code, all_patches) != current_code:
        status = "error"
        task_results[-1]["status"] = "error"
        task_results[-1]["error"] = "full ordered GT patch replay failed"
    result = {
        "instance_id": case_id,
        "status": status,
        "task_count": len(tasks),
        "task_types": [str(item.get("task_type") or "edit") for item in tasks],
        "tasks": task_results,
        "elapsed_seconds": round(sum(t["elapsed_seconds"] for t in task_results), 3),
        "subtask_timeout_seconds": subtask_timeout,
        "source_code_sha256": code_sha256(original_code),
        "final_code_sha256": code_sha256(current_code),
        "patch_count": len(all_patches),
        "patch_count_by_task": dict(Counter(patch["task_type"] for patch in all_patches)),
        "response": all_patches,
        "reference": {"dst_code": current_code},
        "port": port,
        "dependency": dependency,
        "route_check": {"status": "not-run", "reason": "fast-generation-mode"},
        "log": str(log),
    }
    save_json(case_dir / "result.json", result)
    if status == "ok":
        gt_record = {
            **case,
            "response": all_patches,
            "reference": {"dst_code": current_code},
            "metadata": {
                **(case.get("metadata") or {}),
                "task_count": len(tasks),
                "patch_count": len(all_patches),
                "patch_count_by_task": result["patch_count_by_task"],
                "construction_model": "gpt-5.6-luna",
                "construction_route": "codex_cli_edit_skills_fast_sequential",
                "source_code_sha256": result["source_code_sha256"],
                "final_code_sha256": result["final_code_sha256"],
                "subtask_timeout_seconds": subtask_timeout,
                "validation": "exact_patch_replay",
            },
        }
        save_json(case_dir / "gt_record.json", gt_record)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True, help="JSONL containing physical 0921 records")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--max-tasks-per-case", type=int, default=None)
    parser.add_argument("--subtask-timeout", type=int, default=MAX_SUBTASK_TIMEOUT_SECONDS)
    args = parser.parse_args()
    if not 1 <= args.subtask_timeout <= MAX_SUBTASK_TIMEOUT_SECONDS:
        parser.error(
            f"--subtask-timeout must be between 1 and {MAX_SUBTASK_TIMEOUT_SECONDS} seconds"
        )
    jobs = []
    for line in args.cases.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        jobs.append({"instance_id": case.get("instance_id"), "case": case})
    jobs = jobs[: args.limit]
    args.output.mkdir(parents=True, exist_ok=True)
    if args.max_tasks_per_case is not None:
        for job in jobs:
            job["case"]["instruction"]["description"] = job["case"]["instruction"]["description"][:args.max_tasks_per_case]
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [
            pool.submit(
                run_one, job, args.output, index, args.subtask_timeout
            )
            for index, job in enumerate(jobs)
        ]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    summary = {
        "selected": len(jobs),
        "workers": args.workers,
        "subtask_timeout_seconds": args.subtask_timeout,
        "results": results,
    }
    save_json(args.output / "summary.json", summary)
    return 0 if all(item["status"] == "ok" for item in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
