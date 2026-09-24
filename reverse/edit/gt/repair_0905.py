"""Repair one browser-rejected subtask without regenerating accepted GT."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import time
from typing import Any

from openai import OpenAI

from reverse.edit.gt.pilot_0905 import (
    DSL_MARKUP,
    apply_exact,
    normalize_full_file_searches,
    parse_generation,
    save,
    usage,
    validate_javascript,
)


def repair_prompt(
    tasks: list[dict[str, str]],
    evidence: str,
    current_code: list[dict[str, str]],
) -> str:
    return f"""Repair only the failed frozen Edit subtasks below.

Frozen subtasks:
{json.dumps(tasks, ensure_ascii=False)}

Observed browser failure:
{evidence}

Current relevant files after the original patches:
{json.dumps(current_code, ensure_ascii=False)}

Return only JSON with this shape:
{{"patches":[{{"task_type":"exact failed task type","path":"existing path","search":"exact current code","replace":"corrected code"}}]}}

Rules:
- Fix the observed failure and preserve the rest of the current behavior.
- Every failed subtask must have at least one patch assigned to its exact task_type.
- Every search must be non-empty and match exactly once in the current file at application time.
- Patches are applied in output order.
- Keep each search and replacement as small as is safely exact.
- Do not include markdown, commentary, or patch DSL tags inside code.
"""


def parse_repair(
    raw: str, allowed_paths: dict[str, set[str]], task_types: list[str]
) -> list[dict[str, str]]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    payload = json.loads(text)
    patches = payload.get("patches")
    if not isinstance(patches, list) or not patches:
        raise ValueError("repair returned no patches")
    result = []
    for index, patch in enumerate(patches):
        task_type = patch.get("task_type")
        if task_type is None and len(task_types) == 1:
            task_type = task_types[0]
        path = patch.get("path")
        search = patch.get("search")
        replace = patch.get("replace")
        if task_type not in allowed_paths:
            raise ValueError(f"repair patch {index}: unknown task type")
        if path not in allowed_paths[task_type]:
            raise ValueError(f"repair patch {index}: path outside failed subtask")
        if not isinstance(search, str) or not search:
            raise ValueError(f"repair patch {index}: empty search")
        if not isinstance(replace, str) or search == replace:
            raise ValueError(f"repair patch {index}: invalid replacement")
        if DSL_MARKUP.search(search) or DSL_MARKUP.search(replace):
            raise ValueError(f"repair patch {index}: nested patch markup")
        result.append(
            {"path": path, "task_type": task_type, "search": search, "replace": replace}
        )
    missing = [task_type for task_type in task_types if not any(
        patch["task_type"] == task_type for patch in result
    )]
    if missing:
        raise ValueError(f"failed subtasks without repair patches: {missing}")
    return result


def focused_repair_context(
    current: list[dict[str, str]],
    original: list[dict[str, str]],
    task_types: list[str],
) -> list[dict[str, Any]]:
    by_path = {item["path"]: item["code"] for item in current}
    result = []
    for path in sorted({
        patch["path"] for patch in original if patch["task_type"] in task_types
    }):
        code = by_path[path]
        fragments = []
        for patch in original:
            if patch["path"] != path or patch["task_type"] not in task_types:
                continue
            replacement = patch["replace"]
            if len(replacement) <= 12000 and code.count(replacement) == 1:
                fragments.append(replacement)
        for match in re.finditer(r"<!--EDIT:[^>]+-->", code):
            start = max(0, match.start() - 1200)
            end = min(len(code), match.end() + 1200)
            fragments.append(code[start:end])
        deduped = list(dict.fromkeys(fragments))
        result.append(
            {
                "path": path,
                "excerpts": deduped if deduped else [code],
                "full_file": not deduped,
            }
        )
    return result


def fold_repairs(
    source_code: list[dict[str, str]],
    original: list[dict[str, str]],
    repairs: list[dict[str, str]],
) -> list[dict[str, str]]:
    merged = [dict(patch) for patch in original]
    pending = []
    for repair in repairs:
        folded = False
        for patch in reversed(merged):
            if patch["path"] != repair["path"]:
                continue
            if patch["replace"].count(repair["search"]) == 1:
                original_replace = patch["replace"]
                patch["replace"] = patch["replace"].replace(
                    repair["search"], repair["replace"], 1
                )
                try:
                    apply_exact(source_code, merged + pending)
                except ValueError:
                    patch["replace"] = original_replace
                    continue
                folded = True
                break
        if not folded:
            pending.append(repair)
    result = merged + pending
    apply_exact(source_code, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--generation", type=Path, required=True)
    parser.add_argument("--task-type", action="append", required=True)
    parser.add_argument("--failure-evidence", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL"))
    parser.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY"))
    parser.add_argument("--node", default="node")
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()

    case = json.loads(args.case.read_text(encoding="utf-8"))
    original = parse_generation(args.generation.read_text(encoding="utf-8"), case)
    original, _ = normalize_full_file_searches(case["source_code"], original)
    current = apply_exact(case["source_code"], original)
    requested = list(dict.fromkeys(args.task_type))
    tasks = [
        item for item in case["descriptions"] if item["task_type"] in requested
    ]
    if [item["task_type"] for item in tasks] != [
        task_type for task_type in case["task_types"] if task_type in requested
    ] or len(tasks) != len(requested):
        parser.error("every task type must be in the frozen instruction")
    allowed_paths = {
        task_type: {
            patch["path"] for patch in original if patch["task_type"] == task_type
        }
        for task_type in requested
    }
    relevant = focused_repair_context(current, original, requested)
    if not relevant:
        parser.error("failed subtask has no generated files")

    args.output.mkdir(parents=True, exist_ok=True)
    raw_path = args.output / "repair_raw.json"
    call_path = args.output / "repair_call.json"
    if raw_path.exists() and call_path.exists():
        raw = raw_path.read_text(encoding="utf-8")
        call = json.loads(call_path.read_text(encoding="utf-8"))
    else:
        if not args.api_key or not args.base_url:
            parser.error("OPENAI_API_KEY and OPENAI_BASE_URL are required for a new call")
        client = OpenAI(
            api_key=args.api_key,
            base_url=args.base_url.rstrip("/"),
            default_headers={
                "x-openai-actor-authorization": "local-image-extension"
            }
            if "nju-link.com" in args.base_url
            else None,
            timeout=args.timeout,
            max_retries=0,
        )
        started = time.time()
        raw_parts = []
        response = None
        try:
            events = client.responses.create(
                model=args.model,
                instructions="Return exact minimal code repair patches as JSON.",
                input=repair_prompt(tasks, args.failure_evidence, relevant),
                max_output_tokens=4096,
                reasoning={"effort": "medium"},
                store=False,
                stream=True,
            )
            for event in events:
                if event.type == "response.output_text.delta":
                    raw_parts.append(event.delta)
                elif event.type in {"response.completed", "response.incomplete"}:
                    response = event.response
        except Exception:
            if raw_parts:
                raw_path.write_text("".join(raw_parts), encoding="utf-8")
            raise
        raw = "".join(raw_parts)
        raw_path.write_text(raw, encoding="utf-8")
        if response is None or response.status != "completed":
            raise ValueError("repair stream did not complete")
        call = {
            "response_id": getattr(response, "id", None),
            "model": args.model,
            "usage": usage(response),
            "elapsed_seconds": round(time.time() - started, 2),
        }
        save(call_path, call)

    repairs = parse_repair(raw, allowed_paths, requested)
    repaired_current = apply_exact(current, repairs)
    validate_javascript(current, repaired_current, args.node)
    merged = fold_repairs(case["source_code"], original, repairs)
    final_code = apply_exact(case["source_code"], merged)
    js_checked = validate_javascript(case["source_code"], final_code, args.node)
    result: dict[str, Any] = {
        "instance_id": case["instance_id"],
        "task_types": requested,
        "failure_evidence": args.failure_evidence,
        "repair_patches": repairs,
        "response": merged,
        "original_patch_count": len(original),
        "final_patch_count": len(merged),
        "js_checked": js_checked,
        "usage": call["usage"],
    }
    save(args.output / "repair_result.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
