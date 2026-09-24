#!/usr/bin/env python3
"""Watch browser-validation results and repair rejected Generate GT projects once."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import posixpath
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any
from urllib.parse import unquote, urlparse

from openai import OpenAI

_GT_SPEC = importlib.util.spec_from_file_location("webcoding_generate_gt", Path(__file__).with_name("generate.py"))
if _GT_SPEC is None or _GT_SPEC.loader is None:
    raise RuntimeError("cannot load sibling generate.py")
gt = importlib.util.module_from_spec(_GT_SPEC)
_GT_SPEC.loader.exec_module(gt)


RESPONSIVE_STYLE = """<style data-webcoding-auto-repair="responsive">
*,*::before,*::after{box-sizing:border-box}
img,video,canvas,svg{max-width:100%;height:auto}
pre,code{max-width:100%;overflow-wrap:anywhere}
</style>"""


def append_jsonl(path: Path, row: dict[str, Any], lock: threading.Lock | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    guard = lock or threading.Lock()
    with guard:
        with path.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def load_done(path: Path, *, retry_failed: bool = False) -> set[str]:
    latest: dict[str, str] = {}
    if not path.exists():
        return set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            latest[row["project_id"]] = row.get("status", "")
    retryable = {"repair_failed", "validator_error", "repair_skipped"}
    return {
        project_id for project_id, status in latest.items()
        if not retry_failed or status not in retryable
    }


def load_latest_validations(path: Path) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            latest[row["project_id"]] = row
    return list(latest.values())


def safe_rule_repair(project_dir: Path, validation: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    if any(page.get("severe_overflow") for page in validation.get("pages", [])):
        for html in project_dir.rglob("*.htm*"):
            text = html.read_text(encoding="utf-8")
            if "data-webcoding-auto-repair=\"responsive\"" in text:
                continue
            patched = text.replace("</head>", RESPONSIVE_STYLE + "\n</head>", 1)
            if patched == text:
                patched = RESPONSIVE_STYLE + "\n" + text
            html.write_text(patched, encoding="utf-8")
            actions.append(f"responsive_css:{html.relative_to(project_dir).as_posix()}")

    files = [path for path in project_dir.rglob("*") if path.is_file() and not path.name.startswith(".")]
    by_basename: dict[str, list[Path]] = {}
    for path in files:
        by_basename.setdefault(path.name, []).append(path)
    missing_urls: set[str] = set()
    for page in validation.get("pages", []):
        for failure in page.get("essential_failures", []):
            match = re.search(r":(?:404:)?(https?://[^:]+(?::\d+)?/[^:]+)", failure)
            if match:
                missing_urls.add(match.group(1))
    for url in missing_urls:
        requested = unquote(urlparse(url).path).lstrip("/")
        parts = requested.split("/", 1)
        relative = parts[1] if len(parts) == 2 else parts[0]
        candidates = by_basename.get(posixpath.basename(relative), [])
        if len(candidates) != 1:
            continue
        replacement = candidates[0].relative_to(project_dir).as_posix()
        for html in project_dir.rglob("*.htm*"):
            text = html.read_text(encoding="utf-8")
            if relative in text:
                html.write_text(text.replace(relative, replacement), encoding="utf-8")
                actions.append(f"local_path:{relative}->{replacement}")
    return actions


def run_validator(args: argparse.Namespace, project_id: str, suffix: str) -> dict[str, Any]:
    fd, output_name = tempfile.mkstemp(prefix=f"{project_id}.{suffix}.", suffix=".jsonl")
    os.close(fd)
    output = Path(output_name)
    env = os.environ.copy()
    env["PLAYWRIGHT_MODULE"] = args.playwright_module
    env["CHROMIUM_EXECUTABLE"] = args.chromium_executable
    try:
        command = [args.node, str(args.validator_script), "--projects-dir", str(args.projects_dir),
                   "--out", str(output), "--workers", "1", "--limit", "0",
                   "--timeout", str(args.browser_timeout_ms), "--project-id", project_id]
        if args.framework_builder and args.build_root:
            command.extend(["--framework-builder", str(args.framework_builder),
                            "--build-root", str(args.build_root),
                            "--build-timeout", str(args.build_timeout_ms)])
        subprocess.run(
            command,
            env=env, check=True, timeout=args.validator_timeout_seconds,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        )
        rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not rows:
            raise RuntimeError("validator returned no result")
        return rows[-1]
    finally:
        output.unlink(missing_ok=True)


def current_files(project_dir: Path) -> dict[str, str]:
    return {
        path.relative_to(project_dir).as_posix(): path.read_text(encoding="utf-8")
        for path in project_dir.rglob("*")
        if path.is_file() and not path.name.startswith(".")
    }


def call_llm_repair(args: argparse.Namespace, metadata: dict[str, Any], files: dict[str, str],
                    validation: dict[str, Any]) -> tuple[dict[str, str], Any]:
    client = OpenAI(api_key=args.api_key_file.read_text().strip(), base_url=args.base_url,
                    timeout=args.request_timeout_seconds, max_retries=0)
    source = "\n\n".join(
        f"<<<FILE:{name}>>>\n{content}\n<<<END_FILE>>>" for name, content in files.items()
    )
    prompt = f"""Repair this generated frontend project so it passes the supplied browser validation.
Preserve the requested product, working behavior, framework, pages, and existing correct content.
Return only complete replacement file blocks for files that must change, using:
<<<FILE:path/to/file>>>\ncomplete content\n<<<END_FILE>>>
Do not return commentary, patches, unchanged files, or tests.

QUERY:
{metadata.get('query','')}

VALIDATION:
{json.dumps(validation, ensure_ascii=False)}

CURRENT PROJECT:
{source}
"""
    parts: list[str] = []
    usage = None
    with client.responses.stream(
        model=args.model, instructions="You repair frontend projects from concrete browser failures.",
        input=prompt, max_output_tokens=args.max_output_tokens, store=False,
        extra_headers={"x-openai-actor-authorization": args.actor_authorization},
    ) as stream:
        for event in stream:
            if event.type == "response.output_text.delta":
                parts.append(event.delta)
        try:
            response = stream.get_final_response()
            usage = response.usage
        except RuntimeError:
            if not parts or not "".join(parts).rstrip().endswith("<<<END_FILE>>>"):
                raise
    changed = gt.parse_file_blocks("".join(parts))
    merged = dict(files)
    merged.update(changed)
    contract = gt.GenerationContract(**metadata["contract"])
    errors, _ = gt.validate_project_files(merged, contract)
    if errors:
        raise ValueError("; ".join(errors))
    return changed, gt._serialize_usage(usage)


def repair_one(args: argparse.Namespace, validation: dict[str, Any]) -> dict[str, Any]:
    project_id = validation["project_id"]
    project_dir = args.projects_dir / project_id
    marker = project_dir / ".generation.json"
    metadata = json.loads(marker.read_text(encoding="utf-8"))
    backup = args.backup_dir / project_id / str(time.time_ns())
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(project_dir, backup)
    actions: list[str] = []
    try:
        actions = safe_rule_repair(project_dir, validation)
        if actions:
            checked = run_validator(args, project_id, "rules")
            if checked.get("status") == "accept":
                return {"project_id": project_id, "status": "repaired_by_rules",
                        "rule_actions": actions, "validation": checked}
            validation = checked
        changed_files: set[str] = set()
        attempts: list[dict[str, Any]] = []
        for attempt in range(1, args.llm_attempts_per_case + 1):
            try:
                changed, usage = call_llm_repair(
                    args, metadata, current_files(project_dir), validation
                )
                for name, content in changed.items():
                    path = project_dir / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8")
                changed_files.update(changed)
                checked = run_validator(args, project_id, f"llm{attempt}")
                attempts.append({"attempt": attempt, "changed_files": sorted(changed),
                                 "usage": usage, "validation": checked})
                if checked.get("status") == "accept":
                    return {"project_id": project_id, "status": "repaired_by_llm",
                            "rule_actions": actions, "changed_files": sorted(changed_files),
                            "llm_attempts": attempts, "validation": checked}
                validation = checked
            except Exception as exc:
                attempts.append({"attempt": attempt, "error_type": type(exc).__name__,
                                 "error": str(exc)[:2000]})
        last = attempts[-1]
        raise RuntimeError(
            f"repair attempts exhausted: {last.get('error') or (last.get('validation') or {}).get('status')}"
        )
    except Exception as exc:
        shutil.rmtree(project_dir)
        shutil.copytree(backup, project_dir)
        return {"project_id": project_id, "status": "repair_failed",
                "rule_actions": actions, "error_type": type(exc).__name__, "error": str(exc)[:2000]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--projects-dir", type=Path, required=True)
    parser.add_argument("--validation-results", type=Path, required=True)
    parser.add_argument("--repair-results", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--validator-script", type=Path, required=True)
    parser.add_argument("--node", default="node")
    parser.add_argument("--playwright-module", required=True)
    parser.add_argument("--chromium-executable", required=True)
    parser.add_argument("--browser-timeout-ms", type=int, default=30000)
    parser.add_argument("--framework-builder", type=Path)
    parser.add_argument("--build-root", type=Path)
    parser.add_argument("--build-timeout-ms", type=int, default=120000)
    parser.add_argument("--validator-timeout-seconds", type=int, default=420)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--api-key-file", type=Path, required=True)
    parser.add_argument("--base-url", default="https://api.nju-link.com/v1")
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--actor-authorization", default="local-image-extension")
    parser.add_argument("--request-timeout-seconds", type=float, default=1200.0)
    parser.add_argument("--max-output-tokens", type=int, default=30000)
    parser.add_argument("--llm-attempts-per-case", type=int, default=1)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.workers < 1 or args.llm_attempts_per_case < 1:
        parser.error("worker and LLM attempt counts must be at least 1")
    done = load_done(args.repair_results, retry_failed=args.retry_failed)
    write_lock = threading.Lock()
    while True:
        pending: list[dict[str, Any]] = []
        if args.validation_results.exists():
            for validation in load_latest_validations(args.validation_results):
                project_id = validation["project_id"]
                if project_id in done:
                    continue
                done.add(project_id)
                pending.append(validation)

        def process(validation: dict[str, Any]) -> dict[str, Any]:
            project_id = validation["project_id"]
            try:
                if validation.get("status") == "accept":
                    return {"project_id": project_id, "status": "accepted_without_repair"}
                if validation.get("status") in {"review", "needs_repair"}:
                    return repair_one(args, validation)
                return {"project_id": project_id, "status": "repair_skipped",
                        "reason": validation.get("status")}
            except Exception as exc:  # one broken validator/project must not stop the batch
                return {"project_id": project_id, "status": "repair_failed",
                        "error_type": type(exc).__name__, "error": str(exc)[:2000]}

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(process, validation) for validation in pending]
            for future in as_completed(futures):
                result = future.result()
                append_jsonl(args.repair_results, result, write_lock)
                print(json.dumps(result, ensure_ascii=False), flush=True)
        if args.once:
            break
        time.sleep(max(0.5, args.poll_seconds))


if __name__ == "__main__":
    main()
