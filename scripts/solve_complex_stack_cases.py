#!/usr/bin/env python3
"""One-shot generation of complete projects for complex-stack queries."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any

from openai import OpenAI

try:
    from .generate_artifactsbench_queries import load_env, load_jsonl
except ImportError:  # Direct CLI execution: python scripts/solve_complex_stack_cases.py
    from generate_artifactsbench_queries import load_env, load_jsonl


FILE_RE = re.compile(
    "^<<<FILE:(?P<path>[^>\\r\\n]+)>>>\\r?\\n"
    "(?P<content>.*?)^<<<END_FILE>>>(?:\\r?\\n|$)",
    re.MULTILINE | re.DOTALL,
)

STACK_RULES = {
    "vue": "Produce a Vite Vue project with package.json and all Vue/TypeScript source files. Use locally installed npm dependencies at runtime.",
    "react": "Produce a Vite React project with package.json and all React/TypeScript source files. Do not rely on runtime CDN imports.",
    "typescript": "Produce the requested typed Vite/React project. It must pass TypeScript compilation without suppressing errors using ts-ignore or any.",
    "python_backend": "Produce a Python project with pyproject.toml or requirements.txt, backend modules, static frontend/templates, seeded SQLite initialization, and exact local start instructions.",
    "java_backend": "Produce a Maven Java 17 Spring Boot project with pom.xml, complete Java packages, resources/templates/static files, seed data, and no remote browser assets.",
    "database_fullstack": "Produce the requested full-stack project including package manifests, ORM schema/migrations, seed script, server code, and frontend. SQLite must initialize locally.",
    "desktop_electron": "Produce a complete Electron + Vite project with package.json, main/preload/renderer source, secure context isolation, IPC handlers, and fixture data. It must build without packaging/signing.",
    "mobile_miniprogram": "Produce a complete uni-app/Vue project targeting WeChat Mini Program, including package.json, pages.json, manifest.json, source pages/components/store, and local fixtures.",
    "threejs": "Produce a local Vite or static ES-module project with package.json when importing Three.js. Include all scene, interaction, and fixture code; no CDN imports.",
    "webgl": "Produce a complete static project using raw WebGL 2.0, including shader sources inline or as local files, matrix utilities, buffers, controls, and fallback error UI.",
}

SYSTEM = """You are a principal software engineer completing a take-home implementation.
Privately plan the architecture and verify file references before answering. Generate a coherent, runnable project rather than a tutorial or snippets. Return only project files using the requested boundary protocol."""


def prompt_for(row: dict[str, Any]) -> str:
    track = row["technology_track"]
    return f"""Implement this request as a complete local project:

<request>
{row['query']}
</request>

Technology-track contract:
{STACK_RULES[track]}

One-shot acceptance requirements:
- Provide every source/configuration file needed to install, build, and run the core demonstration from a fresh directory. Include the correct package/build manifest and exact version-compatible scripts.
- Implement the main workflow end to end with bundled fixtures/seed data. Every prominent control must have working behavior; do not return a UI-only mockup when API, persistence, IPC, shader, or platform behavior is requested.
- Keep the implementation compact enough to be complete. You may simplify non-core extras while preserving the named stack and the request's central workflow.
- Use no ellipses, TODOs, pseudocode, omitted sections, placeholder implementations, generated lockfiles, binary files, base64 blobs, private credentials, paid services, or remote browser assets/CDNs.
- Network access during dependency installation is allowed, but the running project must use local installed dependencies and bundled data.
- Include robust loading, empty, validation, error, and success states where relevant.
- Preserve a professional, information-rich interface with responsive layout and a clearly visible principal visualization/workspace.
- Add README.md containing exact install, build, run, and verification commands, plus the expected local URL or target platform.
- Ensure imports, file paths, scripts, API routes, schemas, and versions agree across all files.
- Do not explain the project outside its files.

Output protocol:
<<<FILE:path/to/file>>>
complete literal file content
<<<END_FILE>>>

Repeat for every file. Output file blocks only, without Markdown fences. Never place boundary markers inside file content.
"""


def parse(text: str) -> dict[str, str]:
    files: dict[str, str] = {}
    for match in FILE_RE.finditer(text.strip() + "\n"):
        name = match.group("path").strip()
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError(f"unsafe path: {name}")
        # Some long generations revise a file later in the same response.
        # The last complete block is the model's final version.
        files[name] = match.group("content")
    if not files:
        raise ValueError("no files")
    manifest_names = {
        "package.json", "pom.xml", "pyproject.toml", "requirements.txt",
        "index.html", "app.json", "project.config.json", "docker-compose.yml",
    }
    if not any(PurePosixPath(name).name in manifest_names for name in files):
        raise ValueError("missing build/runtime manifest")
    return files


def write_project(root: Path, row: dict[str, Any], files: dict[str, str], model: str,
                  usage: Any, enable_thinking: bool) -> None:
    project = root / "projects" / row["job_id"]
    project.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        target = project / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    (project / ".generation.json").write_text(json.dumps({
        "job_id": row["job_id"], "technology_track": row["technology_track"],
        "query": row["query"], "model": model, "thinking": enable_thinking,
        "files": {name: len(content) for name, content in files.items()},
        "usage": usage.model_dump() if usage else None,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def solve(client: OpenAI, model: str, row: dict[str, Any], output: Path,
          max_tokens: int, enable_thinking: bool) -> dict[str, Any]:
    try:
        completed = output / "projects" / row["job_id"] / ".generation.json"
        if completed.exists():
            return {"job_id": row["job_id"], "track": row["technology_track"], "status": "skipped"}
        stream = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt_for(row)}],
            temperature=0.25,
            max_tokens=max_tokens,
            extra_body={"enable_thinking": enable_thinking},
            stream=True,
            stream_options={"include_usage": True},
        )
        parts: list[str] = []
        usage = None
        for chunk in stream:
            if chunk.usage is not None:
                usage = chunk.usage
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                parts.append(delta.content)
        content = "".join(parts)
        try:
            files = parse(content)
        except Exception:
            raw = output / "raw_failures"
            raw.mkdir(parents=True, exist_ok=True)
            (raw / f"{row['job_id']}.txt").write_text(content, encoding="utf-8")
            raise
        write_project(output, row, files, model, usage, enable_thinking)
        return {
            "job_id": row["job_id"], "track": row["technology_track"],
            "status": "generated", "files": len(files),
            "usage": usage.model_dump() if usage else None,
        }
    except Exception as exc:  # noqa: BLE001
        return {"job_id": row["job_id"], "track": row["technology_track"], "status": "error", "error": f"{type(exc).__name__}: {exc}"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("runs/artifactsbench_complex_stack_1k_qwen3.7max_20260731/queries.jsonl"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--model")
    parser.add_argument("--job-id", action="append", dest="job_ids")
    parser.add_argument("--all", action="store_true", help="process every row in --input")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--max-tokens", type=int, default=30000)
    parser.add_argument("--timeout", type=float, default=1200)
    parser.add_argument("--enable-thinking", action="store_true")
    args = parser.parse_args()
    load_env(args.env_file)
    key, url = os.environ.get("OPENAI_API_KEY", ""), os.environ.get("OPENAI_BASE_URL", "")
    model = args.model or os.environ.get("OPENAI_MODEL", "")
    if not key or not url or not model:
        parser.error("API configuration is missing")
    if not args.all and not args.job_ids:
        parser.error("provide --all or at least one --job-id")
    all_rows = load_jsonl(args.input)
    wanted = set(args.job_ids or [])
    rows = all_rows if args.all else [row for row in all_rows if row["job_id"] in wanted]
    if not args.all and {row["job_id"] for row in rows} != wanted:
        parser.error("one or more job IDs are missing")
    client = OpenAI(api_key=key, base_url=url, timeout=args.timeout, max_retries=0)
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [
            pool.submit(
                solve, client, model, row, args.output_dir,
                args.max_tokens, args.enable_thinking,
            )
            for row in rows
        ]
        for future in as_completed(futures):
            result = future.result(); results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    results.sort(key=lambda row: row["job_id"])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "generation_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
