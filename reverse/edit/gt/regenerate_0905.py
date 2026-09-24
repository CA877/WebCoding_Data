"""Regenerate 0905 Edit GT one frozen subtask at a time."""
from __future__ import annotations

import argparse
import base64
import collections
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
import gzip
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any

from openai import OpenAI


REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from reverse.construct_common import (  # noqa: E402
    LocalSearchReplaceSynthesizer,
    capture_interaction_screenshots,
    discover_browser_routes,
    validate_browser_checks,
    validate_stable_browser_selectors,
)


SHARD = "train-00000-of-00001.jsonl.gz"
EDIT_TASKS = ("text-edit", "image-edit")
ALL_TASKS = (
    "text-generate",
    "image-generate",
    "text-edit",
    "image-edit",
    "text-repair",
    "image-repair",
)
DSL_MARKUP = re.compile(
    r"</?(?:search_replace|search|replace|code-box|full)(?:\s|>)", re.I
)
INLINE_SCRIPT = re.compile(
    r"<script(?P<attrs>[^>]*)>(?P<body>.*?)</script\s*>", re.I | re.S
)


def read_records(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSONL at {path}:{line_number}") from exc


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def code_sha256(code: list[dict[str, str]]) -> str:
    payload = json.dumps(code, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def frozen_descriptions(row: dict[str, Any], modality: str) -> list[dict[str, str]]:
    instruction = row.get("instruction")
    if modality == "text":
        descriptions = (instruction or {}).get("description", [])
    else:
        descriptions = instruction if isinstance(instruction, list) else []
    task_types = row.get("task_type") or []
    if len(descriptions) != len(task_types):
        raise ValueError(
            f"{row.get('instance_id')}: description/task count mismatch "
            f"({len(descriptions)} != {len(task_types)})"
        )
    normalized = []
    for index, description in enumerate(descriptions):
        if not isinstance(description, dict):
            raise ValueError(f"description {index} is not an object")
        actual_type = str(description.get("task_type", "")).strip()
        text = str(description.get("description", "")).strip()
        if not actual_type or not text:
            raise ValueError(
                f"{row.get('instance_id')}: invalid frozen description {index}"
            )
        normalized.append({"task_type": actual_type, "description": text})
    if collections.Counter(item["task_type"] for item in normalized) != collections.Counter(task_types):
        raise ValueError(f"{row.get('instance_id')}: instruction/task types differ")
    return normalized


def visual_only_descriptions(row: dict[str, Any]) -> list[dict[str, str]]:
    metadata = row.get("metadata") or {}
    if metadata.get("image_input_variant") != "source_target_images_no_query":
        return []
    if row.get("instruction") not in (None, "", []):
        return []
    return [
        {
            "task_type": task_type,
            "description": (
                f"Implement the {task_type} target state shown in the supplied "
                "visual Edit reference while preserving unrelated page behavior."
            ),
        }
        for task_type in row.get("task_type") or []
    ]


def visual_references(row: dict[str, Any], source: Path) -> dict[str, Any]:
    source_images = [
        str(source / "image-edit" / path) for path in row.get("src_screenshot") or []
    ]
    targets = {}
    destination_images = row.get("dst_screenshot") or []
    for task_type in row.get("task_type") or []:
        slug = re.sub(r"[^a-z0-9]+", "_", task_type.lower()).strip("_")
        matches = [
            path
            for path in destination_images
            if slug
            in re.sub(r"[^a-z0-9]+", "_", Path(path).stem.lower()).strip("_")
        ]
        if len(matches) != 1:
            raise ValueError(
                f"{row.get('instance_id')}: expected one visual target for "
                f"{task_type}, got {matches}"
            )
        targets[task_type] = str(source / "image-edit" / matches[0])
    for path in [*source_images, *targets.values()]:
        if not Path(path).is_file():
            raise FileNotFoundError(path)
    return {"source_images": source_images, "target_by_task": targets}


def source_code(row: dict[str, Any], modality: str) -> list[dict[str, str]]:
    if modality == "text":
        code = (row.get("instruction") or {}).get("src_code") or []
    else:
        code = row.get("input_files") or []
    if not code or any(not item.get("path") or "code" not in item for item in code):
        raise ValueError(f"{row.get('instance_id')}: missing complete source code")
    return code


def apply_exact(
    code: list[dict[str, str]], patches: list[dict[str, str]]
) -> list[dict[str, str]]:
    order = [item["path"] for item in code]
    code_map = {item["path"]: item["code"] for item in code}
    if len(code_map) != len(code):
        raise ValueError("duplicate source paths")
    for index, patch in enumerate(patches):
        path = str(patch.get("path", "")).strip()
        search = patch.get("search")
        replace = patch.get("replace")
        if not path or not isinstance(search, str) or not isinstance(replace, str):
            raise ValueError(f"patch {index}: invalid path/search/replace")
        if search == replace:
            raise ValueError(f"patch {index}: search equals replace")
        if path not in code_map:
            if search:
                raise ValueError(f"patch {index}: unknown path {path}")
            code_map[path] = replace
            order.append(path)
            continue
        if not search:
            raise ValueError(f"patch {index}: empty search for existing path {path}")
        matches = code_map[path].count(search)
        if matches != 1:
            raise ValueError(
                f"patch {index}: search must match once in {path}; got {matches}"
            )
        code_map[path] = code_map[path].replace(search, replace, 1)
    return [{"path": path, "code": code_map[path]} for path in order]


def validate_subtask_response(
    raw_response: str,
    frozen: dict[str, str],
    current_code: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, Any]]]:
    parsed = LocalSearchReplaceSynthesizer.parse_llm_response(None, raw_response)
    description = parsed.get("description")
    if description != [frozen]:
        raise ValueError("response changed the frozen Edit instruction")
    patches = parsed.get("modified_files") or []
    if not patches:
        raise ValueError("response contains no patch")
    seen = set()
    normalized = []
    for index, patch in enumerate(patches):
        item = {
            "path": str(patch.get("path", "")).strip(),
            "task_type": str(patch.get("task_type", "")).strip(),
            "search": patch.get("search"),
            "replace": patch.get("replace"),
        }
        if item["task_type"] != frozen["task_type"]:
            raise ValueError(f"patch {index}: wrong or missing task_type")
        for field in ("search", "replace"):
            if not isinstance(item[field], str):
                raise ValueError(f"patch {index}: {field} is not text")
            if DSL_MARKUP.search(item[field]):
                raise ValueError(f"patch {index}: nested patch markup in {field}")
        signature = (item["path"], item["search"], item["replace"])
        if signature in seen:
            raise ValueError(f"patch {index}: duplicate patch")
        seen.add(signature)
        normalized.append(item)
    checks = parsed.get("browser_checks") or []
    if len(checks) != 1:
        raise ValueError("response must contain exactly one browser check")
    return normalized, apply_exact(current_code, normalized), checks


def materialize_project(code: list[dict[str, str]], root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for item in code:
        target = (root / item["path"]).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError(f"source path escapes project: {item['path']}") from exc
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item["code"], encoding="utf-8")


def validate_browser_subtask(
    code: list[dict[str, str]], frozen: dict[str, str], checks: list[dict[str, Any]], output: Path
) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="g2-browser-") as temporary:
        project = Path(temporary) / "project"
        materialize_project(code, project)
        checked = validate_browser_checks(
            checks, [frozen["task_type"]], discover_browser_routes(project)
        )
        validate_stable_browser_selectors(checked, code)
        _, evidence = capture_interaction_screenshots(project, output, checked)
    if len(evidence) != 1 or evidence[0].get("status") != "ok":
        raise ValueError(f"browser acceptance failed: {evidence}")
    return evidence


def _node_check(node: str, source: str, *, module: bool, label: str) -> None:
    command = [node, "--check"]
    if module:
        command.append("--input-type=module")
    result = subprocess.run(
        command,
        input=source,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    if result.returncode:
        message = (result.stderr or result.stdout).strip()[:1000]
        raise ValueError(f"JavaScript syntax error in {label}: {message}")


def validate_javascript(
    before: list[dict[str, str]], after: list[dict[str, str]], node: str
) -> list[str]:
    before_map = {item["path"]: item["code"] for item in before}
    checked = []
    for item in after:
        path = item["path"]
        content = item["code"]
        if before_map.get(path) == content:
            continue
        suffix = Path(path).suffix.lower()
        if suffix in {".js", ".mjs", ".cjs"}:
            module = suffix == ".mjs" or bool(
                re.search(r"^\s*(?:import|export)\b", content, re.M)
            )
            _node_check(node, content, module=module, label=path)
            checked.append(path)
        if suffix not in {".html", ".htm"}:
            continue
        for script_index, match in enumerate(INLINE_SCRIPT.finditer(content)):
            attrs = match.group("attrs")
            if re.search(r"\bsrc\s*=", attrs, re.I):
                continue
            type_match = re.search(r"\btype\s*=\s*['\"]([^'\"]+)", attrs, re.I)
            script_type = type_match.group(1).lower() if type_match else ""
            if script_type and script_type not in {
                "module",
                "text/javascript",
                "application/javascript",
            }:
                continue
            body = match.group("body").strip()
            if body:
                _node_check(
                    node,
                    body,
                    module=script_type == "module",
                    label=f"{path}#inline-script-{script_index}",
                )
                checked.append(f"{path}#inline-script-{script_index}")
    return checked


def build_prompt(
    current_code: list[dict[str, str]],
    frozen: dict[str, str],
    accepted: list[dict[str, str]],
    validation_error: str,
    visual_reference: bool = False,
) -> str:
    adapter = object.__new__(LocalSearchReplaceSynthesizer)
    code_context = LocalSearchReplaceSynthesizer.format_code_context(
        adapter, current_code
    )
    feedback = ""
    if validation_error:
        feedback = (
            "\nThe previous attempt failed validation:\n"
            f"{validation_error}\nRegenerate only this subtask from the current code.\n"
        )
    visual_requirement = ""
    if visual_reference:
        visual_requirement = (
            "\nThe attached images are ordered as source page screenshots followed by "
            "the target interaction screenshot for this subtask. Use that final image "
            "as the frozen visual instruction.\n"
        )
    return f"""Implement exactly one frozen Edit subtask in the current accepted project.

Frozen subtask (copy this object unchanged into <description>):
{json.dumps(frozen, ensure_ascii=False)}

Already accepted subtasks that must remain working:
{json.dumps(accepted, ensure_ascii=False)}

Requirements:
- Fully implement every behavior stated in the frozen subtask across every relevant existing page.
- Work from the current code below; it already includes all accepted earlier subtasks.
- Output the smallest complete ordered patch sequence for this subtask.
- Every search must be exact current source text and match once.
- To create a new file, use an empty <search> only for a path that does not exist.
- Every <search_replace> must include task_type="{frozen['task_type']}".
- Do not place search_replace/search/replace tags inside search or replacement code.
- Do not change the instruction and do not output unrelated edits.
{visual_requirement}

Output ONLY XML in this exact shape:
<description>[{json.dumps(frozen, ensure_ascii=False)}]</description>
<search_replace path="path/to/file" task_type="{frozen['task_type']}"><search>exact current code</search><replace>complete edited code</replace></search_replace>
<browser_checks>[{{"task_type":"{frozen['task_type']}","route":"existing.html","actions":[{{"action":"click","selector":"#stable-control"}}],"assertion":{{"type":"visible","selector":"#stable-result"}},"capture_delay_ms":150}}]</browser_checks>
The browser check is hidden verification metadata: use only a real route and a stable selector created or exercised by this subtask; its assertion must prove the requested behavior.
{feedback}
{code_context}"""


def image_content(path: str) -> dict[str, str]:
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return {"type": "input_image", "image_url": f"data:{mime};base64,{encoded}"}


def response_text(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if text:
        return text
    parts = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            value = getattr(content, "text", None)
            if value:
                parts.append(value)
    return "".join(parts)


def usage_dict(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    return dict(usage)


def streamed_response(client: OpenAI, **request: Any) -> tuple[str, Any]:
    """Collect a completed Responses stream without relying on gateway buffering."""
    parts: list[str] = []
    completed = None
    for event in client.responses.create(stream=True, **request):
        if event.type == "response.output_text.delta":
            parts.append(event.delta)
        elif event.type in {"response.completed", "response.incomplete"}:
            completed = event.response
    if completed is None or completed.status != "completed":
        raise RuntimeError("response stream did not complete")
    return "".join(parts), completed


def plan(args: argparse.Namespace) -> None:
    index = json.loads((args.source / "dataset_index.json").read_text())
    for task in EDIT_TASKS:
        shard = args.source / task / SHARD
        expected = index["tasks"][task]["sha256"]
        actual = sha256_file(shard)
        if actual != expected:
            raise ValueError(f"source hash mismatch for {task}: {actual} != {expected}")

    text_rows = {
        row["instance_id"]: row
        for row in read_records(args.source / "text-edit" / SHARD)
    }
    image_rows = {
        row["instance_id"]: row
        for row in read_records(args.source / "image-edit" / SHARD)
    }
    jobs = []
    dropped = collections.Counter()
    task_counts = collections.Counter()
    instruction_order_repairs = 0
    visual_only_cases = 0
    for instance_id in sorted(set(text_rows) | set(image_rows)):
        text_row = text_rows.get(instance_id)
        image_row = image_rows.get(instance_id)
        canonical = text_row or image_row
        modality = "text" if text_row else "image"
        task_types = canonical.get("task_type") or []
        count = len(task_types)
        if count <= 3:
            dropped[count] += 1
            continue
        if not 4 <= count <= 7:
            raise ValueError(f"{instance_id}: unexpected task count {count}")
        hidden_visual_descriptions = (
            visual_only_descriptions(image_row) if image_row else []
        )
        visual_only = bool(hidden_visual_descriptions)
        descriptions = (
            hidden_visual_descriptions
            if visual_only
            else frozen_descriptions(canonical, modality)
        )
        if visual_only:
            visual_only_cases += 1
        frozen_task_types = [item["task_type"] for item in descriptions]
        if frozen_task_types != task_types:
            instruction_order_repairs += 1
        code = source_code(canonical, modality)
        if text_row and image_row:
            if descriptions != frozen_descriptions(image_row, "image"):
                raise ValueError(f"{instance_id}: paired descriptions differ")
            if code != source_code(image_row, "image"):
                raise ValueError(f"{instance_id}: paired source code differs")
        visual = visual_references(image_row, args.source) if visual_only else {}
        case = {
            "instance_id": instance_id,
            "task_count": count,
            "task_types": frozen_task_types,
            "descriptions": descriptions,
            "source_code": code,
            "source_code_sha256": code_sha256(code),
            "has_text": text_row is not None,
            "has_image": image_row is not None,
            "visual_only_instruction": visual_only,
            "visual_references": visual,
        }
        case_path = args.run / "cases" / f"{instance_id}.json.gz"
        case_path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(case_path, "wt", encoding="utf-8") as stream:
            json.dump(case, stream, ensure_ascii=False)
        jobs.append(
            {
                "instance_id": instance_id,
                "task_count": count,
                "case": str(case_path),
                "has_text": text_row is not None,
                "has_image": image_row is not None,
            }
        )
        task_counts[count] += 1
    payload = {
        "source": str(args.source),
        "source_edit_sha256": {
            task: index["tasks"][task]["sha256"] for task in EDIT_TASKS
        },
        "model": args.model,
        "concurrency": args.concurrency,
        "case_timeout_seconds": args.case_timeout,
        "request_timeout_seconds": args.request_timeout,
        "max_attempts_per_subtask": args.max_attempts,
        "jobs": jobs,
        "unique_kept_by_task_count": dict(sorted(task_counts.items())),
        "unique_dropped_by_task_count": dict(sorted(dropped.items())),
        "instruction_order_repairs": instruction_order_repairs,
        "visual_only_cases": visual_only_cases,
    }
    save_json(args.run / "plan.json", payload)
    print(json.dumps({key: value for key, value in payload.items() if key != "jobs"}))


def load_case(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def worker(args: argparse.Namespace) -> None:
    case = load_case(args.case)
    output = args.run / "outputs" / case["instance_id"]
    output.mkdir(parents=True, exist_ok=True)
    result_path = output / "result.json"
    if result_path.exists() and json.loads(result_path.read_text()).get("status") == "ok":
        print(f"already complete {case['instance_id']}")
        return

    api_key = os.environ.get("TOKENWAVE_OPENAI_API_KEY") or os.environ.get(
        "OPENAI_API_KEY"
    )
    base_url = (
        os.environ.get("TOKENWAVE_OPENAI_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or "https://api.tokenwave.us/v1"
    ).rstrip("/")
    if base_url == "https://api.tokenwave.us":
        base_url += "/v1"
    if not api_key:
        raise ValueError("TOKENWAVE_OPENAI_API_KEY is required")
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=args.request_timeout,
        max_retries=0,
    )

    current = case["source_code"]
    all_patches = []
    accepted = []
    usage = collections.Counter()
    task_results = []
    try:
        for task_index, frozen in enumerate(case["descriptions"], 1):
            task_dir = output / f"task_{task_index:02d}"
            task_dir.mkdir(exist_ok=True)
            validation_error = ""
            for attempt in range(1, args.max_attempts + 1):
                visual_only = bool(case.get("visual_only_instruction"))
                prompt = build_prompt(
                    current,
                    frozen,
                    accepted,
                    validation_error,
                    visual_reference=visual_only,
                )
                user_content: str | list[dict[str, str]] = prompt
                if visual_only:
                    references = case["visual_references"]
                    paths = [
                        *references["source_images"],
                        references["target_by_task"][frozen["task_type"]],
                    ]
                    user_content = [
                        {"type": "input_text", "text": prompt},
                        *(image_content(path) for path in paths),
                    ]
                request_log = {
                    "attempt": attempt,
                    "task_index": task_index,
                    "task_type": frozen["task_type"],
                    "input_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                    "status": "started",
                    "started_at": time.time(),
                }
                save_json(task_dir / f"attempt_{attempt}.json", request_log)
                raw = ""
                try:
                    raw, response = streamed_response(
                        client,
                        model=args.model,
                        input=[
                            {
                                "role": "system",
                                "content": "Output only exact XML patches for one frozen web Edit subtask.",
                            },
                            {"role": "user", "content": user_content},
                        ],
                        max_output_tokens=args.max_output_tokens,
                        reasoning={"effort": "medium"},
                        store=False,
                    )
                    request_usage = usage_dict(response)
                    for name in ("input_tokens", "output_tokens", "total_tokens"):
                        usage[name] += int(request_usage.get(name, 0) or 0)
                    request_log.update(
                        status="response_received",
                        response_id=getattr(response, "id", None),
                        usage=request_usage,
                    )
                    (task_dir / f"response_{attempt}.xml").write_text(
                        raw, encoding="utf-8"
                    )
                    patches, changed, browser_checks = validate_subtask_response(raw, frozen, current)
                    js_checked = validate_javascript(current, changed, args.node)
                    browser_evidence = validate_browser_subtask(
                        changed, frozen, browser_checks,
                        task_dir / f"browser_attempt_{attempt}",
                    )
                    request_log.update(
                        status="accepted",
                        patch_count=len(patches),
                        js_checked=js_checked,
                        browser_evidence=browser_evidence,
                        finished_at=time.time(),
                    )
                    save_json(task_dir / f"attempt_{attempt}.json", request_log)
                    task_results.append(
                        {
                            "task_index": task_index,
                            "task_type": frozen["task_type"],
                            "attempts": attempt,
                            "patch_count": len(patches),
                            "js_checked": js_checked,
                            "browser_evidence": browser_evidence,
                        }
                    )
                    all_patches.extend(patches)
                    current = changed
                    accepted.append(frozen)
                    save_json(
                        output / "checkpoint.json",
                        {
                            "accepted_subtasks": task_index,
                            "patches": all_patches,
                            "current_code_sha256": code_sha256(current),
                            "usage": dict(usage),
                        },
                    )
                    print(
                        json.dumps(
                            {
                                "instance_id": case["instance_id"],
                                "accepted_subtask": task_index,
                                "task_count": case["task_count"],
                                "task_type": frozen["task_type"],
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                    break
                except Exception as exc:  # noqa: BLE001
                    validation_error = f"{type(exc).__name__}: {exc}"
                    request_log.update(
                        status="error",
                        error=validation_error,
                        finished_at=time.time(),
                    )
                    save_json(task_dir / f"attempt_{attempt}.json", request_log)
                    status_code = getattr(exc, "status_code", None)
                    lowered = str(exc).lower()
                    if status_code in {401, 403} or any(
                        marker in lowered
                        for marker in (
                            "invalid_api_key",
                            "authentication",
                            "insufficient_quota",
                            "credit balance",
                        )
                    ):
                        raise RuntimeError(f"authentication/quota blocked: {exc}") from exc
                    if attempt < args.max_attempts:
                        time.sleep(5 if attempt == 1 else 10)
            else:
                raise RuntimeError(
                    f"subtask {task_index}/{case['task_count']} failed: {validation_error}"
                )
        result = {
            "status": "ok",
            "instance_id": case["instance_id"],
            "task_count": case["task_count"],
            "task_types": case["task_types"],
            "source_code_sha256": case["source_code_sha256"],
            "final_code_sha256": code_sha256(current),
            "patch_count": len(all_patches),
            "patch_count_by_task": dict(
                collections.Counter(patch["task_type"] for patch in all_patches)
            ),
            "response": all_patches,
            "subtasks": task_results,
            "usage": dict(usage),
            "model": args.model,
        }
    except Exception as exc:  # noqa: BLE001
        result = {
            "status": "error",
            "instance_id": case["instance_id"],
            "task_count": case["task_count"],
            "accepted_subtasks": len(accepted),
            "error": f"{type(exc).__name__}: {exc}",
            "usage": dict(usage),
            "model": args.model,
        }
    save_json(result_path, result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if result["status"] != "ok":
        raise SystemExit(2)


def run_one_job(args: argparse.Namespace, job: dict[str, Any]) -> dict[str, Any]:
    result_path = args.run / "outputs" / job["instance_id"] / "result.json"
    if result_path.exists() and not args.retry_failed:
        return json.loads(result_path.read_text())
    if result_path.exists() and json.loads(result_path.read_text()).get("status") == "ok":
        return json.loads(result_path.read_text())
    folder = result_path.parent
    folder.mkdir(parents=True, exist_ok=True)
    log = (folder / "worker.log").open("a", encoding="utf-8")
    command = [
        sys.executable, "-u", str(Path(__file__).resolve()), "worker",
        "--source", str(args.source), "--run", str(args.run), "--case", job["case"],
        "--model", args.model, "--node", args.node,
        "--request-timeout", str(args.request_timeout),
        "--max-attempts", str(args.max_attempts),
        "--max-output-tokens", str(args.max_output_tokens),
    ]
    active = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        active.wait(timeout=args.case_timeout)
    except subprocess.TimeoutExpired:
        os.killpg(active.pid, signal.SIGKILL)
        active.wait()
        save_json(result_path, {"status": "error", "instance_id": job["instance_id"],
                                "task_count": job["task_count"], "error": "case hard timeout"})
    finally:
        log.close()
    if not result_path.exists():
        save_json(result_path, {"status": "error", "instance_id": job["instance_id"],
                                "task_count": job["task_count"], "error": "worker exited without result"})
    return json.loads(result_path.read_text())


def run(args: argparse.Namespace) -> None:
    plan_data = json.loads((args.run / "plan.json").read_text())
    jobs = plan_data["jobs"]
    if args.limit:
        jobs = jobs[: args.limit]
    stopped = False
    def stop(_signum, _frame):
        nonlocal stopped
        stopped = True

    for name in ("SIGINT", "SIGTERM", "SIGHUP"):
        signal.signal(getattr(signal, name), stop)

    counts = collections.Counter()
    total_usage = collections.Counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(run_one_job, args, job): job for job in jobs}
        for ordinal, future in enumerate(as_completed(futures), 1):
            job = futures[future]
            result = future.result()
            counts[result.get("status", "error")] += 1
            for name, value in (result.get("usage") or {}).items():
                total_usage[name] += int(value or 0)
            status = {
                "processed": ordinal,
                "selected": len(jobs),
                "counts": dict(counts),
                "usage": dict(total_usage),
                "last_instance_id": job["instance_id"],
                "updated_at": time.time(),
            }
            save_json(args.run / "status.json", status)
            print(json.dumps(status), flush=True)
    save_json(
        args.run / ("smoke.json" if args.limit else "generation.json"),
        {
            "status": "interrupted" if stopped else "complete",
            "processed": sum(counts.values()),
            "counts": dict(counts),
            "usage": dict(total_usage),
        },
    )


def update_record(row: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    updated = copy.deepcopy(row)
    patches = copy.deepcopy(result["response"])
    updated["task_type"] = list(result["task_types"])
    updated["response"] = patches
    if "patches" in updated:
        updated["patches"] = copy.deepcopy(patches)
    metadata = dict(updated.get("metadata") or {})
    metadata.update(
        {
            "task_count": result["task_count"],
            "patch_count": result["patch_count"],
            "patch_count_by_task": result["patch_count_by_task"],
            "construction_model": result["model"],
            "construction_route": "0905_edit_gt_sequential_subtask",
            "gt_regeneration": {
                "strategy": "frozen_instruction_sequential_subtask",
                "source_construction_model": (row.get("metadata") or {}).get(
                    "construction_model"
                ),
                "source_code_sha256": result["source_code_sha256"],
                "final_code_sha256": result["final_code_sha256"],
            },
        }
    )
    updated["metadata"] = metadata
    return updated


def finalize(args: argparse.Namespace) -> None:
    if args.dest.exists():
        raise FileExistsError(args.dest)
    plan_data = json.loads((args.run / "plan.json").read_text())
    results = {}
    failed = []
    for job in plan_data["jobs"]:
        path = args.run / "outputs" / job["instance_id"] / "result.json"
        if not path.exists():
            failed.append({"instance_id": job["instance_id"], "error": "not attempted"})
            continue
        result = json.loads(path.read_text())
        if result.get("status") == "ok":
            results[job["instance_id"]] = result
        else:
            failed.append(
                {
                    "instance_id": job["instance_id"],
                    "error": result.get("error", "failed"),
                }
            )
    args.dest.mkdir(parents=True)
    source_index = json.loads((args.source / "dataset_index.json").read_text())
    index = copy.deepcopy(source_index)
    task_summary = {}
    for task in ALL_TASKS:
        source_folder = args.source / task
        target_folder = args.dest / task
        target_folder.mkdir()
        for child in source_folder.iterdir():
            if child.name == SHARD:
                continue
            if child.is_dir():
                (target_folder / child.name).symlink_to(child.resolve(), target_is_directory=True)
            else:
                shutil.copy2(child, target_folder / child.name)
        source_shard = source_folder / SHARD
        target_shard = target_folder / SHARD
        if task not in EDIT_TASKS:
            shutil.copy2(source_shard, target_shard)
            count = source_index["tasks"][task]["num_samples"]
        else:
            before = kept = dropped_low = dropped_failed = 0
            with gzip.open(target_shard, "wt", encoding="utf-8") as stream:
                for row in read_records(source_shard):
                    before += 1
                    task_count = len(row.get("task_type") or [])
                    if task_count <= 3:
                        dropped_low += 1
                        continue
                    result = results.get(row["instance_id"])
                    if result is None:
                        dropped_failed += 1
                        continue
                    stream.write(
                        json.dumps(update_record(row, result), ensure_ascii=False) + "\n"
                    )
                    kept += 1
            count = kept
            task_summary[task] = {
                "before": before,
                "kept": kept,
                "dropped_1_to_3": dropped_low,
                "dropped_failed_regeneration": dropped_failed,
            }
        index["tasks"][task]["num_samples"] = count
        index["tasks"][task]["sha256"] = sha256_file(target_shard)
        index["tasks"][task]["compressed_gib"] = round(
            target_shard.stat().st_size / 2**30, 6
        )
    index["name"] = args.dest.name
    index["source_release"] = str(args.source)
    index.pop("publication", None)
    index["notes"] = list(index.get("notes") or []) + [
        "Edit task_count 1--3 removed; task_count 4--7 GT regenerated sequentially per frozen subtask with exact replay, nested-patch rejection, and JavaScript syntax checks."
    ]
    save_json(args.dest / "dataset_index.json", index)
    save_json(
        args.run / "final.json",
        {
            "status": "complete",
            "dataset": str(args.dest),
            "successful_unique_instances": len(results),
            "failed_unique_instances": len(failed),
            "failed": failed,
            "edit_tasks": task_summary,
        },
    )
    print(json.dumps(task_summary, ensure_ascii=False))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("mode", choices=("plan", "worker", "run", "finalize"))
    result.add_argument("--source", type=Path, required=True)
    result.add_argument("--run", type=Path, required=True)
    result.add_argument("--dest", type=Path)
    result.add_argument("--case", type=Path)
    result.add_argument("--model", default="gpt-5.6-luna")
    result.add_argument("--node", default="node")
    result.add_argument("--limit", type=int, default=0)
    result.add_argument("--retry-failed", action="store_true")
    result.add_argument("--request-timeout", type=float, default=300)
    result.add_argument("--case-timeout", type=float, default=3600)
    result.add_argument("--max-attempts", type=int, default=3)
    result.add_argument("--max-output-tokens", type=int, default=32768)
    result.add_argument("--concurrency", type=int, default=1)
    return result


if __name__ == "__main__":
    arguments = parser().parse_args()
    if arguments.mode == "worker" and not arguments.case:
        raise SystemExit("--case is required for worker")
    if arguments.mode == "finalize" and not arguments.dest:
        raise SystemExit("--dest is required for finalize")
    arguments.run.mkdir(parents=True, exist_ok=True)
    globals()[arguments.mode](arguments)
