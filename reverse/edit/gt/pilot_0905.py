"""Pilot one-call frozen-instruction GT generation for a 0905 Edit case."""
from __future__ import annotations

import argparse
import collections
import difflib
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any

from openai import OpenAI


DSL_MARKUP = re.compile(r"</?(?:search_replace|search|replace)(?:\s|>)", re.I)
INLINE_SCRIPT = re.compile(
    r"<script(?P<attrs>[^>]*)>(?P<body>.*?)</script\s*>", re.I | re.S
)


def records(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def save(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def code_context(code: list[dict[str, str]]) -> str:
    return "<code_context>\n" + "".join(
        f'<file path="{item["path"]}">\n{item["code"]}\n</file>\n'
        for item in code
    ) + "</code_context>"


def frozen_case(row: dict[str, Any]) -> dict[str, Any]:
    instruction = row.get("instruction") or {}
    descriptions = instruction.get("description") or []
    code = instruction.get("src_code") or []
    task_types = [item.get("task_type") for item in descriptions]
    if not 4 <= len(descriptions) <= 7:
        raise ValueError("pilot requires 4--7 frozen subtasks")
    if any(not task_type or not item.get("description") for task_type, item in zip(task_types, descriptions)):
        raise ValueError("invalid frozen instruction")
    if collections.Counter(task_types) != collections.Counter(row.get("task_type") or []):
        raise ValueError("instruction and task types differ")
    return {
        "instance_id": row["instance_id"],
        "descriptions": descriptions,
        "task_types": task_types,
        "source_code": code,
    }


def parse_generation(raw: str, case: dict[str, Any]) -> list[dict[str, str]]:
    description_match = re.search(r"<description>(.*?)</description>", raw, re.S)
    if not description_match:
        raise ValueError("missing description")
    if json.loads(description_match.group(1).strip()) != case["descriptions"]:
        raise ValueError("frozen instruction changed")
    checklist_match = re.search(
        r"<implementation_checklist>(.*?)</implementation_checklist>", raw, re.S
    )
    if not checklist_match:
        raise ValueError("missing implementation checklist")
    checklist = json.loads(checklist_match.group(1).strip())
    if [item.get("task_type") for item in checklist] != case["task_types"]:
        raise ValueError("checklist does not cover frozen subtask order")
    if any(not item.get("files") or not item.get("implemented_behaviors") for item in checklist):
        raise ValueError("incomplete implementation checklist")

    matches = re.findall(
        r'<search_replace\s+path="([^"]+)"\s+task_type="([^"]+)">\s*'
        r"<search>(.*?)</search>\s*<replace>(.*?)</replace>\s*</search_replace>",
        raw,
        re.S,
    )
    patches = []
    for path, task_type, search, replace in matches:
        def unwrap(value: str) -> str:
            value = value.strip()
            if value.startswith("<![CDATA[") and value.endswith("]]>"):
                value = value[9:-3]
            elif value.startswith("<![CDATA:") and value.endswith("]]>"):
                value = value[9:-3]
            return value.strip()

        item = {
            "path": path.strip(),
            "task_type": task_type.strip(),
            "search": unwrap(search),
            "replace": unwrap(replace),
        }
        if item["task_type"] not in case["task_types"]:
            raise ValueError(f"unknown task_type in patch: {item['task_type']}")
        if DSL_MARKUP.search(item["search"]) or DSL_MARKUP.search(item["replace"]):
            raise ValueError("nested patch markup")
        patches.append(item)
    if not patches:
        raise ValueError("no patches")
    mapped = collections.Counter(patch["task_type"] for patch in patches)
    missing = [task_type for task_type in case["task_types"] if not mapped[task_type]]
    if missing:
        raise ValueError(f"subtasks without patches: {missing}")
    if any(count > 10 for count in mapped.values()):
        raise ValueError("more than 10 patches assigned to one subtask")
    return patches


def apply_exact(
    code: list[dict[str, str]], patches: list[dict[str, str]]
) -> list[dict[str, str]]:
    order = [item["path"] for item in code]
    code_map = {item["path"]: item["code"] for item in code}
    for index, patch in enumerate(patches):
        path, search, replace = patch["path"], patch["search"], patch["replace"]
        if search == replace:
            raise ValueError(f"patch {index}: search equals replace")
        if path not in code_map:
            if search:
                raise ValueError(f"patch {index}: unknown path {path}")
            code_map[path] = replace
            order.append(path)
            continue
        if not search:
            raise ValueError(f"patch {index}: empty search for existing path")
        count = code_map[path].count(search)
        if count != 1:
            raise ValueError(f"patch {index}: exact search count is {count}")
        code_map[path] = code_map[path].replace(search, replace, 1)
    return [{"path": path, "code": code_map[path]} for path in order]


def normalize_full_file_searches(
    code: list[dict[str, str]], patches: list[dict[str, str]]
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    normalized = [dict(patch) for patch in patches]
    code_map = {item["path"]: item["code"] for item in code}
    events = []
    for index, patch in enumerate(normalized):
        path, search, replace = patch["path"], patch["search"], patch["replace"]
        current = code_map.get(path)
        if current is None:
            if not search:
                code_map[path] = replace
            continue
        if current.count(search) != 1:
            covers_file = len(search) >= int(len(current) * 0.8)
            same_edges = search[:80] == current[:80] and search[-80:] == current[-80:]
            similarity = difflib.SequenceMatcher(None, current, search).ratio()
            if covers_file and same_edges and similarity >= 0.995:
                events.append(
                    {
                        "patch_index": index,
                        "path": path,
                        "similarity": round(similarity, 6),
                        "original_search_length": len(search),
                        "normalized_search_length": len(current),
                    }
                )
                patch["search"] = current
                search = current
        if current.count(search) == 1:
            code_map[path] = current.replace(search, replace, 1)
    return normalized, events


def node_check(node: str, source: str, label: str, module: bool = False) -> None:
    command = [node, "--check"] + (["--input-type=module"] if module else [])
    result = subprocess.run(
        command, input=source, text=True, capture_output=True, timeout=15
    )
    if result.returncode:
        raise ValueError(f"JavaScript syntax error in {label}: {result.stderr[:500]}")


def validate_javascript(
    before: list[dict[str, str]], after: list[dict[str, str]], node: str
) -> list[str]:
    old = {item["path"]: item["code"] for item in before}
    checked = []
    for item in after:
        path, content = item["path"], item["code"]
        if old.get(path) == content:
            continue
        suffix = Path(path).suffix.lower()
        if suffix in {".js", ".mjs", ".cjs"}:
            module = suffix == ".mjs" or bool(
                re.search(r"^\s*(?:import|export)\b", content, re.M)
            )
            node_check(node, content, path, module)
            checked.append(path)
        if suffix in {".html", ".htm"}:
            for index, match in enumerate(INLINE_SCRIPT.finditer(content)):
                attrs, body = match.group("attrs"), match.group("body").strip()
                if re.search(r"\bsrc\s*=", attrs, re.I) or not body:
                    continue
                type_match = re.search(r"\btype\s*=\s*['\"]([^'\"]+)", attrs, re.I)
                script_type = type_match.group(1).lower() if type_match else ""
                if script_type and script_type not in {
                    "module", "text/javascript", "application/javascript"
                }:
                    continue
                label = f"{path}#inline-{index}"
                node_check(node, body, label, script_type == "module")
                checked.append(label)
    return checked


def generation_prompt(case: dict[str, Any]) -> str:
    return f"""Implement all frozen Edit subtasks in the supplied source project.
The instructions are final and must not be rewritten or expanded.

Frozen instructions, in required implementation order:
{json.dumps(case['descriptions'], ensure_ascii=False)}

Before answering, inspect every relevant page and make a private implementation plan.
Then verify each requested behavior against the code you wrote. Output only these XML elements:

<description>{json.dumps(case['descriptions'], ensure_ascii=False)}</description>
<implementation_checklist>[{{"task_type":"exact frozen type","files":["changed path"],"implemented_behaviors":["concrete behavior"]}}]</implementation_checklist>
<search_replace path="path/to/file" task_type="exact frozen type"><search>exact current source</search><replace>complete replacement</replace></search_replace>

Rules:
- Preserve the frozen subtask order in the checklist.
- Fully implement every stated behavior, including cross-page coverage, state, keyboard, empty/error, and async edge cases where requested.
- Assign every patch to exactly one frozen task_type; every subtask needs at least one patch.
- Patches are applied globally in output order. A later search may target code inserted by an earlier patch.
- Every non-empty search must exactly match once at the moment it is applied.
- Empty search is allowed only when creating a new path.
- Never put search_replace/search/replace tags inside code content.
- Avoid unrelated changes. Output no markdown or prose.

{code_context(case['source_code'])}"""


JUDGE_SYSTEM = """You audit web Edit ground truth. Given frozen subtasks, source code, and exact ordered patches, determine whether every requested behavior is fully implemented and whether the patches introduce functional errors. Return only JSON: {"verdict":"pass|minor_issue|major_issue","instruction_coverage_score":0,"functional_correctness_score":0,"minimality_score":0,"subtasks":[{"task_type":"","status":"fulfilled|partial|missing","issues":[]}],"introduced_errors":[],"summary":""}. Scores are integers 0--4. Use major_issue when a core behavior is missing or broken; minor_issue for localized incompleteness."""


def judge_prompt(case: dict[str, Any], patches: list[dict[str, str]]) -> str:
    return (
        "Frozen subtasks:\n"
        + json.dumps(case["descriptions"], ensure_ascii=False)
        + "\n\nOrdered patches:\n"
        + json.dumps(patches, ensure_ascii=False)
        + "\n\nSource code:\n"
        + json.dumps(case["source_code"], ensure_ascii=False)
    )


def output_text(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if text:
        return text
    return "".join(
        getattr(content, "text", "")
        for item in getattr(response, "output", []) or []
        for content in getattr(item, "content", []) or []
    )


def usage(response: Any) -> dict[str, Any]:
    value = getattr(response, "usage", None)
    return value.model_dump() if hasattr(value, "model_dump") else {}


def json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    return json.loads(text)


def find_row(shard: Path, instance_id: str) -> dict[str, Any]:
    for row in records(shard):
        if row.get("instance_id") == instance_id:
            return row
    raise KeyError(instance_id)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text-shard", type=Path, required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL"))
    parser.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY"))
    parser.add_argument("--node", default="node")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--judge", action="store_true")
    args = parser.parse_args()
    if not args.api_key or not args.base_url:
        parser.error("OPENAI_API_KEY and OPENAI_BASE_URL are required")
    args.output.mkdir(parents=True, exist_ok=True)
    case = frozen_case(find_row(args.text_shard, args.instance_id))
    save(args.output / "case.json", case)

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
    raw_path = args.output / "generation.xml"
    raw_parts = []
    generated = None
    try:
        events = client.responses.create(
            model=args.model,
            input=[
                {"role": "system", "content": "Produce exact web Edit patches and no prose."},
                {"role": "user", "content": generation_prompt(case)},
            ],
            max_output_tokens=32768,
            reasoning={"effort": "medium"},
            store=False,
            stream=True,
        )
        for event in events:
            if event.type == "response.output_text.delta":
                raw_parts.append(event.delta)
            elif event.type in {"response.completed", "response.incomplete"}:
                generated = event.response
    except Exception:
        if raw_parts:
            raw_path.write_text("".join(raw_parts), encoding="utf-8")
        raise
    raw = "".join(raw_parts)
    raw_path.write_text(raw, encoding="utf-8")
    if generated is None or generated.status != "completed":
        raise ValueError("generation stream did not complete")
    generation_call = {
        "response_id": getattr(generated, "id", None),
        "model": args.model,
        "usage": usage(generated),
        "elapsed_seconds": round(time.time() - started, 2),
    }
    save(args.output / "generation_call.json", generation_call)
    patches = parse_generation(raw, case)
    patches, search_normalizations = normalize_full_file_searches(
        case["source_code"], patches
    )
    changed = apply_exact(case["source_code"], patches)
    js_checked = validate_javascript(case["source_code"], changed, args.node)
    generation_result = {
        "status": "accepted_by_static_checks",
        "instance_id": args.instance_id,
        "patch_count": len(patches),
        "patch_count_by_task": dict(
            collections.Counter(patch["task_type"] for patch in patches)
        ),
        "js_checked": js_checked,
        "search_normalizations": search_normalizations,
        "usage": generation_call["usage"],
        "elapsed_seconds": generation_call["elapsed_seconds"],
        "response": patches,
    }
    save(args.output / "generation.json", generation_result)

    if not args.judge:
        result = {
            "generation": generation_result,
            "production_generation_calls": 1,
            "pilot_audit_calls": 0,
        }
        save(args.output / "result.json", result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    judge_started = time.time()
    judged = client.responses.create(
        model=args.model,
        input=[
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": judge_prompt(case, patches)},
        ],
        max_output_tokens=8192,
        reasoning={"effort": "medium"},
        store=False,
    )
    judge_raw = output_text(judged)
    (args.output / "judge_raw.txt").write_text(judge_raw, encoding="utf-8")
    result = {
        "generation": generation_result,
        "judge": json_object(judge_raw),
        "judge_usage": usage(judged),
        "judge_elapsed_seconds": round(time.time() - judge_started, 2),
        "production_generation_calls": 1,
        "pilot_audit_calls": 1,
    }
    save(args.output / "result.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
