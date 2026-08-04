#!/usr/bin/env python3
"""Generate runnable multi-file web projects for synthesized queries."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Any

from openai import OpenAI

from generate_artifactsbench_queries import load_env, load_jsonl


FILE_RE = re.compile(
    "^<<<FILE:(?P<path>[^>\\r\\n]+)>>>\\r?\\n"
    "(?P<content>.*?)^<<<END_FILE>>>(?:\\r?\\n|$)",
    re.MULTILINE | re.DOTALL,
)

SYSTEM_PROMPT = """You are a senior frontend engineer and interaction designer.
Build a polished, genuinely functional browser artifact from the user's specification.
Think through architecture, state, geometry, algorithms, and interactions privately before coding.
Return only complete project files using the required file-boundary protocol."""


def build_solver_prompt(query: str) -> str:
    return f"""Implement the following web artifact as a complete runnable project.

<user_request>
{query.strip()}
</user_request>

Implementation contract:
- The project must run when its directory is served by `python3 -m http.server`; no build step is allowed.
- Use semantic HTML, handcrafted CSS, and vanilla JavaScript. Use native SVG, Canvas, and Web Audio APIs when appropriate.
- All dependencies, data, fonts, and visual assets must be local or generated in code. Never use a CDN, remote URL, remote API, iframe, analytics, or network request.
- Implement the requested core algorithm and interactions honestly. Every visible primary control must work; do not create decorative buttons, TODOs, fake loading, or claims of functionality that is not implemented.
- Start with meaningful bundled sample data/state so the artifact is visually rich and demonstrable immediately, without requiring an upload or setup step.
- Deliver a composed, professional interface: strong hierarchy, intentional typography, coherent color system, useful spacing, clear affordances, hover/focus/active states, and responsive behavior down to 768px width.
- Keep the principal artifact visible in a 1440x900 viewport. Avoid oversized introductions, excessive prose, and layouts whose important content begins below the fold.
- Scale the principal canvas/SVG/object to occupy roughly 45-75% of its available workspace in the initial state. Do not leave the core visualization tiny in a large empty field.
- Keep toolbars, instructions, telemetry, and floating panels outside the core object's active manipulation region whenever possible. They must not obscure the initial artifact or each other.
- Handle reset, invalid input, empty state, and the main success/failure or completion state where relevant.
- For animation loops, use requestAnimationFrame and delta time; pause or reduce expensive work when appropriate. Resize Canvas/SVG correctly and avoid unbounded DOM growth.
- Keep scope coherent. Prefer a robust implementation of the requested core experience over many shallow extras.
- Do not mention these implementation instructions in the UI.

Required files:
- `index.html`: accessible document structure; reference `styles.css` and defer `script.js`.
- `styles.css`: all styling; do not rely on remote fonts.
- `script.js`: all behavior and sample data.

You may add small local text/data files only when truly useful. Do not add package manifests or compiled assets.

Output protocol (mandatory):
<<<FILE:index.html>>>
complete file content
<<<END_FILE>>>
<<<FILE:styles.css>>>
complete file content
<<<END_FILE>>>
<<<FILE:script.js>>>
complete file content
<<<END_FILE>>>

Output files only. Do not use Markdown fences, explanations, summaries, or omitted sections. Never place the boundary markers inside file content.
"""


def parse_files(text: str) -> dict[str, str]:
    files: dict[str, str] = {}
    for match in FILE_RE.finditer(text.strip() + "\n"):
        path = match.group("path").strip()
        content = match.group("content")
        pure = PurePosixPath(path)
        if pure.is_absolute() or ".." in pure.parts or not pure.parts:
            raise ValueError(f"unsafe output path: {path}")
        if path in files:
            raise ValueError(f"duplicate output path: {path}")
        files[path] = content
    required = {"index.html", "styles.css", "script.js"}
    missing = required - files.keys()
    if missing:
        raise ValueError(f"missing required files: {sorted(missing)}")
    return files


def validate_files(files: dict[str, str]) -> list[str]:
    warnings = []
    html = files["index.html"]
    css = files["styles.css"]
    js = files["script.js"]
    if not re.search(r"styles\.css", html, re.I):
        warnings.append("index.html does not reference styles.css")
    if not re.search(r"script\.js", html, re.I):
        warnings.append("index.html does not reference script.js")
    combined = "\n".join(files.values())
    network_text = combined.replace("http://www.w3.org/2000/svg", "")
    if re.search(r"https?://|//cdn\.|@import\s+url", network_text, re.I):
        warnings.append("contains a remote URL or CSS import")
    if re.search(r"\b(?:TODO|FIXME|placeholder implementation|implement later)\b", combined, re.I):
        warnings.append("contains placeholder/TODO text")
    if len(html) < 500:
        warnings.append("index.html is suspiciously short")
    if len(css) < 800:
        warnings.append("styles.css is suspiciously short")
    if len(js) < 1200:
        warnings.append("script.js is suspiciously short")
    try:
        completed = subprocess.run(
            ["node", "--check"], input=js, text=True,
            capture_output=True, timeout=20, check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip().splitlines()[-1]
            warnings.append(f"script.js syntax check failed: {detail}")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return warnings


def write_project(root: Path, job_id: str, files: dict[str, str], metadata: dict[str, Any]) -> None:
    target = root / job_id
    target.mkdir(parents=True, exist_ok=True)
    for relative, content in files.items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    meta_path = target / "metadata.json"
    temporary = meta_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, meta_path)


def solve_one(client: OpenAI, model: str, row: dict[str, Any], output_dir: Path,
              max_tokens: int, enable_thinking: bool, max_retries: int) -> dict[str, Any]:
    job_id = str(row["job_id"])
    completed = output_dir / "projects" / job_id / "metadata.json"
    if completed.exists():
        return {"job_id": job_id, "status": "skipped"}
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_solver_prompt(str(row["query"]))},
                ],
                temperature=0.35,
                max_tokens=max_tokens,
                extra_body={"enable_thinking": enable_thinking},
            )
            raw = response.choices[0].message.content or ""
            try:
                files = parse_files(raw)
            except Exception:
                raw_dir = output_dir / "raw_failures"
                raw_dir.mkdir(parents=True, exist_ok=True)
                (raw_dir / f"{job_id}.txt").write_text(raw, encoding="utf-8")
                raise
            warnings = validate_files(files)
            metadata = {
                "job_id": job_id,
                "category": row.get("category"),
                "target_subclass": row.get("target_subclass"),
                "query": row["query"],
                "model": model,
                "thinking": enable_thinking,
                "attempt": attempt,
                "warnings": warnings,
                "files": {path: len(content) for path, content in files.items()},
            }
            write_project(output_dir / "projects", job_id, files, metadata)
            return {"job_id": job_id, "status": "ok", "warnings": warnings, "attempt": attempt}
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    return {"job_id": job_id, "status": "error", "error": f"{type(last_error).__name__}: {last_error}"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("runs/artifactsbench_queries_3k_qwen3.7max_20260731/queries.jsonl"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--job-id", action="append", dest="job_ids")
    parser.add_argument("--all", action="store_true", help="process every row in --input")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--model")
    parser.add_argument("--max-tokens", type=int, default=14000)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--enable-thinking", action="store_true")
    parser.add_argument("--request-timeout", type=float, default=600.0)
    args = parser.parse_args()

    load_env(args.env_file)
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "")
    model = args.model or os.environ.get("OPENAI_MODEL", "")
    if not api_key or not base_url or not model:
        parser.error("OPENAI_API_KEY, OPENAI_BASE_URL, and model are required")
    if not args.all and not args.job_ids:
        parser.error("provide --all or at least one --job-id")

    all_rows = load_jsonl(args.input)
    wanted = set(args.job_ids or [])
    rows = all_rows if args.all else [row for row in all_rows if row.get("job_id") in wanted]
    if not args.all:
        found = {row["job_id"] for row in rows}
        missing = wanted - found
        if missing:
            parser.error(f"job IDs not found: {sorted(missing)}")

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=args.request_timeout, max_retries=0)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(
                solve_one, client, model, row, args.output_dir,
                args.max_tokens, args.enable_thinking, args.max_retries,
            )
            for row in rows
        ]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            with (args.output_dir / "results.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(result, ensure_ascii=False) + "\n")
    results.sort(key=lambda row: row["job_id"])
    (args.output_dir / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if any(row["status"] != "ok" for row in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
