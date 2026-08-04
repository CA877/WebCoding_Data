#!/usr/bin/env python3
"""Generate engineering-heavy ArtifactsBench-style queries by technology stack."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import random
import re
from typing import Any

from openai import OpenAI

from generate_artifactsbench_queries import load_env, load_jsonl, parse_response


STACKS: dict[str, dict[str, str]] = {
    "vue": {
        "pattern": r"\bVue(?:\.js|JS)?\b",
        "contract": "Require a Vue 3 project with components, Composition API state, routing or structured views where useful, and a concrete visual interaction. TypeScript may be included.",
    },
    "react": {
        "pattern": r"\bReact(?:\.js|JS)?\b",
        "contract": "Require a React project with meaningful component boundaries, hooks/state transitions, and a concrete interactive visual experience. TypeScript is preferred.",
    },
    "typescript": {
        "pattern": r"\bTypeScript\b",
        "contract": "Make TypeScript essential through typed domain models, discriminated state, or reusable typed modules—not merely a file extension change.",
    },
    "python_backend": {
        "pattern": r"\b(?:Python|Flask|Django|FastAPI)\b",
        "contract": "Require a small Python web backend (Flask, FastAPI, or Django as appropriate) plus a browser frontend. Include a real API/data flow that can run locally, while keeping deployment modest.",
    },
    "java_backend": {
        "pattern": r"\b(?:Java|Spring Boot|Spring MVC)\b",
        "contract": "Require a Java web project, preferably Spring Boot for the backend, with a browser UI and a bounded but real end-to-end workflow.",
    },
    "database_fullstack": {
        "pattern": r"\b(?:database|MySQL|MongoDB|SQLite|PostgreSQL|SQL Server)\b",
        "contract": "Require a real local persistence layer with a concise schema, CRUD or transactional behavior, validation, and a visual frontend that exposes meaningful state changes.",
    },
    "desktop_electron": {
        "pattern": r"\b(?:Electron|desktop application|desktop app)\b",
        "contract": "Require an Electron desktop application with renderer/main-process responsibilities, local filesystem or desktop integration, and a polished interactive renderer UI.",
    },
    "mobile_miniprogram": {
        "pattern": r"\b(?:Android|iOS|mobile app|mini.program|WeChat Mini|uni-?app|Flutter)\b",
        "contract": "Require a genuine mobile or mini-program project and name one appropriate stack (Flutter, native Android, or uni-app/WeChat Mini Program). Include touch-first interaction and device-sized layouts.",
    },
    "threejs": {
        "pattern": r"\bThree\.js\b",
        "contract": "Require Three.js as a genuine 3D scene dependency with camera, lighting, geometry, spatial interaction, animation, and resize handling—not a decorative background.",
    },
    "webgl": {
        "pattern": r"\bWebGL\b",
        "contract": "Require native WebGL with explicit shaders, buffers, transforms, and a meaningful interactive visual or simulation. Keep shader and scene scope implementable.",
    },
}

SCENARIOS = (
    "scientific fieldwork", "cultural heritage", "small-scale manufacturing",
    "community infrastructure", "environmental monitoring", "creative production",
    "clinical logistics", "education laboratory", "public transportation",
    "archive preservation", "energy systems", "accessible communication",
)


def select_pool(rows: list[dict[str, Any]], pattern: str) -> list[dict[str, Any]]:
    regex = re.compile(pattern, re.I)
    return [row for row in rows if regex.search(str(row.get("question", "")))]


def supplement_pool(stack: str, rows: list[dict[str, Any]], pool: list[dict[str, Any]],
                    required: int) -> list[dict[str, Any]]:
    if len(pool) >= required:
        return pool
    fallback_patterns = {
        "webgl": r"\bThree\.js\b|^$",
    }
    pattern = fallback_patterns.get(stack)
    if not pattern:
        return pool
    existing = {row["index"] for row in pool}
    candidates = [
        row for row in rows
        if row["index"] not in existing and (
            re.search(pattern, str(row.get("question", "")), re.I)
            or str(row.get("class", "")).startswith("Simulation & Modeling-3D Simulation")
        )
    ]
    return pool + candidates[:max(0, required - len(pool))]


def clean_question(text: str, limit: int = 1800) -> str:
    text = re.sub(
        r"^You are a code expert.*?(?=(?:Please|Create|Build|Implement|How|For|Tech|\{))",
        "", text.strip(), flags=re.I | re.S,
    ).strip()
    return text if len(text) <= limit else text[:limit] + "\n[seed truncated]"


def build_prompt(stack: str, seeds: list[dict[str, Any]], ordinal: int) -> str:
    spec = STACKS[stack]
    scenario = SCENARIOS[(ordinal + sum(ord(c) for c in stack)) % len(SCENARIOS)]
    blocks = []
    for number, seed in enumerate(seeds, 1):
        blocks.append(
            f'<seed number="{number}" index="{seed["index"]}" class="{seed["class"]}">\n'
            f'{clean_question(seed["question"])}\n</seed>'
        )
    return f"""Create ONE new ArtifactsBench-style coding request in the technology track `{stack}`.

Technology contract:
{spec['contract']}

Use the source queries to understand authentic requests for this stack, but create a structurally new project. Use `{scenario}` only as loose domain inspiration.

Requirements for the new query:
- Ask for a runnable project, not an architecture essay, tutorial, isolated snippet, or cosmetic mockup.
- Make the named stack materially necessary and state an appropriate project/file structure or deliverables.
- Include a visually substantial user interface and at least one interaction whose state crosses meaningful modules or layers.
- For full-stack projects, define a small real API, data model, validation behavior, and frontend response to success/error; do not request cloud deployment, paid services, or production-scale authentication.
- For desktop/mobile projects, require platform-native interaction that a plain webpage would not satisfy.
- For Three.js/WebGL, require genuine 3D/rendering mechanics and direct manipulation, not a static scene.
- Keep the project feasible for a strong coding model to complete as a local demonstration. Avoid sprawling enterprise scope, unavailable proprietary SDKs, private data, and remote credentials.
- Specify bundled fixtures or seed data so the project demonstrates immediately after setup.
- Include a coherent visual direction, observable states, and concrete completion behavior.
- Do not mention ArtifactsBench, benchmark, sources, evaluation, or these instructions.
- Do not output code, a solution, checklist, rubric, or commentary.
- Aim for 180-320 English words.

Silently verify before answering: the output is not implementable as merely vanilla HTML/CSS/JS without violating the request; the requested stack has a real purpose; the scope is locally runnable; and the task differs from every seed.

Return JSON only:
{{
  "query": "complete new coding request",
  "short_name": "concise project name",
  "technology_track": "{stack}",
  "required_stack": ["explicit", "technologies"],
  "project_shape": "brief description of deliverables"
}}

Source queries:
{chr(10).join(blocks)}
"""


def generate_one(client: OpenAI, model: str, stack: str, ordinal: int,
                 seeds: list[dict[str, Any]], max_retries: int) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "Generate one realistic, engineering-heavy visual coding request. Return JSON only."},
                    {"role": "user", "content": build_prompt(stack, seeds, ordinal)},
                ],
                temperature=0.9,
                max_tokens=1800,
                extra_body={"enable_thinking": False},
            )
            parsed = parse_response(response.choices[0].message.content or "")
            return {
                "status": "ok", "technology_track": stack, "sample_id": ordinal,
                "query": str(parsed["query"]).strip(),
                "short_name": str(parsed.get("short_name", "")).strip(),
                "required_stack": parsed.get("required_stack", []),
                "project_shape": str(parsed.get("project_shape", "")).strip(),
                "source_indices": [seed["index"] for seed in seeds],
                "source_classes": [seed["class"] for seed in seeds],
                "model": model, "attempt": attempt,
            }
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    return {
        "status": "error", "technology_track": stack, "sample_id": ordinal,
        "source_indices": [seed["index"] for seed in seeds], "model": model,
        "error": f"{type(last_error).__name__}: {last_error}",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("datasets/ArtifactsBenchmark_full/artifacts_bench.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--model")
    parser.add_argument("--per-track", type=int, default=2)
    parser.add_argument("--seeds-per-query", type=int, default=4)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20260731)
    parser.add_argument("--max-retries", type=int, default=3)
    args = parser.parse_args()

    load_env(args.env_file)
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "")
    model = args.model or os.environ.get("OPENAI_MODEL", "")
    if not api_key or not base_url or not model:
        parser.error("OPENAI_API_KEY, OPENAI_BASE_URL, and model are required")

    rows = load_jsonl(args.input)
    jobs = []
    for stack, spec in STACKS.items():
        pool = supplement_pool(
            stack, rows, select_pool(rows, spec["pattern"]), args.seeds_per_query,
        )
        if len(pool) < args.seeds_per_query:
            raise ValueError(f"{stack}: only {len(pool)} official seeds")
        shuffled = pool[:]
        random.Random(f"{args.seed}:{stack}").shuffle(shuffled)
        for ordinal in range(1, args.per_track + 1):
            start = ((ordinal - 1) * args.seeds_per_query) % len(shuffled)
            seeds = [shuffled[(start + offset) % len(shuffled)] for offset in range(args.seeds_per_query)]
            jobs.append((stack, ordinal, seeds))

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=240, max_retries=0)
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(generate_one, client, model, stack, ordinal, seeds, args.max_retries)
            for stack, ordinal, seeds in jobs
        ]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(f"{result['technology_track']} #{result['sample_id']}: {result['status']}", flush=True)

    order = {stack: i for i, stack in enumerate(STACKS)}
    results.sort(key=lambda row: (order[row["technology_track"]], row["sample_id"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in results),
        encoding="utf-8",
    )
    print(f"wrote {len(results)} records to {args.output}")


if __name__ == "__main__":
    main()
