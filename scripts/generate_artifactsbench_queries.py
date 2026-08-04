#!/usr/bin/env python3
"""Synthesize new ArtifactsBench-style queries from multiple same-class seeds.

This is deliberately a raw generation stage: it does not create checklists and
does not run a reviewer, similarity screen, or other filtering stage.
"""
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


CATEGORY_GUIDANCE = {
    "Game Development": "a playable game with a concrete core loop, controls, state transitions, feedback, and win/fail conditions",
    "SVG Generation": "an SVG-native visual artifact whose composition, paths/shapes, animation, and interaction are central—not a generic app with an icon",
    "Web Applications": "a coherent browser product with a user journey, meaningful state, and working interactions",
    "Simulation & Modeling": "an interactive model with parameters, evolving state, visualized behavior, and reset/comparison controls",
    "Data Science": "an exploratory or analytical artifact where data transformations, visual encodings, and linked interactions matter",
    "Management Systems": "a stateful management workflow with records, status changes, search/filtering, and concrete operations",
    "Multimedia Editing": "a working image/audio/video editing artifact with import or sample media, manipulation controls, preview, and output state",
    "Utility Tools": "a focused, immediately usable tool with inputs, transformation/calculation logic, validation, and copy/downloadable output",
    "Other": "a distinctive executable visual artifact that does not collapse into a routine dashboard or CRUD product",
}

# Fine classes that add capabilities underrepresented by ordinary website data.
# Every selected class has at least four official ArtifactsBench examples.
SPECIAL_FINE_CLASSES = (
    "Game Development-Puzzle",
    "Game Development-Action/Rhythm",
    "SVG Generation-SVG Images",
    "SVG Generation-SVG Icons/Logos",
    "Simulation & Modeling-Physics Simulation",
    "Simulation & Modeling-3D Simulation",
    "Simulation & Modeling-Mathematical Abstraction",
    "Data Science-Statistical Analysis",
    "Data Science-Predictive Modeling",
    "Data Science-Machine Learning",
    "Multimedia Editing-Image Editing",
    "Multimedia Editing-Audio Editing",
    "Multimedia Editing-Video Production",
    "Utility Tools-Calculation Tools",
    "Utility Tools-Batch Processing",
    "Mermaid Flowcharts-Mind Maps",
)

FINE_CLASS_GUIDANCE = {
    "Game Development-Action/Rhythm": "Use one learnable action-rhythm loop, 2-4 controls, explicit timing feedback, and clear start/play/win-or-fail states. Avoid combining a full editor, campaign, and procedural generator.",
    "Game Development-Puzzle": "Use one deterministic puzzle system with a small board, visible state changes, undo/reset or level progression, and a mechanically checkable solution condition.",
    "SVG Generation-SVG Icons/Logos": "The SVG mark itself must remain the main artifact. Use a small number of paths/groups and at most three meaningful interactions or animations; do not turn it into a general application.",
    "SVG Generation-SVG Images": "Make composition and manipulation of native SVG geometry central. Keep geometric algorithms bounded and do not disguise a physics simulator or dashboard as an SVG image.",
    "Simulation & Modeling-3D Simulation": "Use 6-30 simple projected 3D primitives or modest native WebGL geometry. Do not require a custom 3D engine, shaders, procedural terrain, complex collision engine, or high-fidelity continuum physics.",
    "Simulation & Modeling-Mathematical Abstraction": "Name a compact deterministic model and expose a few parameters. Keep entity counts and numerical methods modest enough for a transparent client-side implementation.",
    "Simulation & Modeling-Physics Simulation": "Model one physical phenomenon with a bounded number of bodies, explicit parameters, observable state, and reset/compare controls. Prefer stable simple integration over research-grade accuracy.",
    "Data Science-Machine Learning": "Use a small bundled dataset and explicitly implement one understandable client-side algorithm such as k-means, k-NN, or a decision stump. Never imply a pretrained model or opaque AI service.",
    "Data Science-Predictive Modeling": "This must be data-driven predictive modeling, not a physics formula labeled as prediction. Fit a small regression, moving-average, exponential-smoothing, or Markov model from bundled observations; show features, predictions, actual/reference values, and an error metric. Do not promise real-world accuracy.",
    "Data Science-Statistical Analysis": "Specify one or two standard statistics over a small bundled dataset, linked views, and an interaction that visibly changes the calculation.",
    "Multimedia Editing-Audio Editing": "Use generated tones/noise and lightweight Web Audio nodes. Editing may change timing, gain, pan, filters, or a cue-sheet state; only JSON metadata may be exported.",
    "Multimedia Editing-Image Editing": "Use Canvas pixel operations or layer transforms that produce an honest preview. PNG/SVG/JSON export is allowed; keep the processing pipeline to at most three effects.",
    "Multimedia Editing-Video Production": "Create a previsualization, storyboard, shot planner, crop/keyframe planner, or simulated-frame editor. Do not process, encode, upload, or export actual video.",
    "Utility Tools-Batch Processing": "Process bounded text, JSON, CSV, SVG, or metadata inputs with preview, validation, and lightweight browser-native output. Do not promise arbitrary binary file conversion.",
    "Utility Tools-Calculation Tools": "Expose validated numeric inputs, show formulas or intermediate values, visualize the result, and handle invalid or boundary cases.",
    "Mermaid Flowcharts-Mind Maps": "Center the task on editing or generating valid Mermaid `mindmap` indentation syntax plus a visible tree preview. Use only this accurate supported subset: default `Node text`, square `id[Node text]`, rounded `id(Node text)`, and circle `id((Node text))`. It must not use arrows, call `(( ))` a cloud, invent decorators, or claim full Mermaid compatibility.",
}

DIVERSITY_LANES = (
    "direct manipulation with immediate visual feedback",
    "parameter exploration with before/after comparison",
    "constructive editing with a small reusable output",
    "temporal sequencing with play, pause, and scrubbing",
    "linked views where one selection updates another view",
    "state progression with explicit transitions and recovery",
    "spatial arrangement with drag, snap, and constraint feedback",
    "guided input, validation, transformation, and result explanation",
)

FINE_CLASS_LANES = {
    "Game Development-Action/Rhythm": (0, 3, 5),
    "Game Development-Puzzle": (0, 2, 5, 6),
    "SVG Generation-SVG Icons/Logos": (0, 2, 5),
    "SVG Generation-SVG Images": (0, 2, 6),
    "Simulation & Modeling-3D Simulation": (1, 5, 6),
    "Simulation & Modeling-Mathematical Abstraction": (1, 2, 4),
    "Simulation & Modeling-Physics Simulation": (1, 4, 5),
    "Data Science-Machine Learning": (1, 4, 7),
    "Data Science-Predictive Modeling": (1, 4, 7),
    "Data Science-Statistical Analysis": (1, 2, 4),
    "Multimedia Editing-Audio Editing": (2, 3, 5),
    "Multimedia Editing-Image Editing": (0, 2, 6),
    "Multimedia Editing-Video Production": (2, 3, 6),
    "Utility Tools-Batch Processing": (2, 7),
    "Utility Tools-Calculation Tools": (1, 6, 7),
    "Mermaid Flowcharts-Mind Maps": (2, 5, 7),
}


def load_env(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def coarse_class(fine_class: str) -> str:
    prefix = fine_class.split("-", 1)[0].strip()
    if prefix == "Mermaid Flowcharts":
        return "Other"
    return prefix


def parse_response(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, dict) or not str(value.get("query", "")).strip():
        raise ValueError("response has no non-empty query")
    return value


def clean_seed(question: str, limit: int) -> str:
    boilerplate = [
        "You are a code expert. Please use your professional knowledge to generate accurate and professional responses.",
        "Make sure the generated code is executable for demonstration.",
        "Make sure the code you generate is executable for demonstration purposes.",
    ]
    for phrase in boilerplate:
        question = question.replace(phrase, "")
    question = question.strip()
    return question if len(question) <= limit else question[:limit] + "\n[seed truncated]"


def build_prompt(category: str, seeds: list[dict[str, Any]], max_seed_chars: int,
                 target_subclass: str | None = None, diversity_lane: str | None = None) -> str:
    examples = []
    for i, seed in enumerate(seeds, 1):
        examples.append(
            f'<seed number="{i}" index="{seed["index"]}" subclass="{seed["class"]}" '
            f'difficulty="{seed["difficulty"]}">\n{clean_seed(seed["question"], max_seed_chars)}\n</seed>'
        )
    subclass_requirement = (
        f"The exact target subclass is {target_subclass}. Keep the task within this subclass.\n"
        f"Subclass scope and complexity limit: {FINE_CLASS_GUIDANCE.get(target_subclass, '')}"
        if target_subclass else
        "Infer a suitable fine-grained subclass from the category."
    )
    return f"""Create ONE new browser-executable coding query in the ArtifactsBench category: {category}.

Category identity: {CATEGORY_GUIDANCE[category]}.
{subclass_requirement}
Interaction-diversity direction for this sample: {diversity_lane or 'choose a coherent interaction structure'}.
The diversity direction is subordinate to the exact subclass; never distort the task category merely to satisfy it.

Use every seed only as evidence of the category's capability range. Create a genuinely new task; do not summarize, splice, or paraphrase the seed scenarios.

Requirements:
- Preserve the category's distinctive artifact type and request real, demonstrable interactions.
- Change the domain scenario, entities, data/state model, visual composition, and interaction structure from the seeds.
- Prefer an unusual but coherent artifact that would add coverage to a web-code training set.
- Describe the intended artifact, visual presentation, controls, and observable behavior clearly enough to implement.
- Keep scope feasible as an offline-capable browser artifact using ordinary HTML/CSS/JavaScript browser APIs.
- Every requested core feature must be honestly demonstrable in a static browser project.
- HARD PROHIBITION: Do not request video/audio transcoding, pitch-preserving time stretching, beat/source separation, modified audio/video export, recording, speech recognition, or other heavyweight media processing. Multimedia tasks should use lightweight Canvas/Web Audio previews and parameter/state editing only.
- HARD PROHIBITION: Do not request fake AI, fake machine learning, fake prediction, generative services, server-like behavior, authentication, collaboration, or cloud persistence. Data-science tasks may implement small, explicit client-side algorithms over bundled mock data.
- HARD PROHIBITION: Do not name or require an external library, CDN, remote API, backend, unavailable hardware, network access, or remote asset. All data and media must be bundled locally or generated in the browser.
- Downloads are allowed only for lightweight browser-native outputs such as JSON, CSV, SVG, PNG, plain text, or Mermaid source. Never request exported/processed audio or video.
- Do not use vague verbs such as "analyze", "predict", "intelligently", or "AI-powered" unless the query also specifies a small deterministic algorithm that can visibly run in client-side JavaScript.
- Complexity budget: one core artifact, at most three supporting views/panels, at most six primary controls, and at most three core algorithms. Do not request a framework or engine to be built from scratch.
- Write like a real product/design request. The feasibility and dependency restrictions in this prompt are private authoring constraints, not requested query content: do not repeat them as boilerplate.
- HARD PROHIBITION: Never require a single HTML file and never prescribe a repository/file layout. Describe the artifact, not its packaging.
- Avoid generic admin dashboards and overused scenarios unless the subclass specifically calls for one. Favor a concrete, visually distinctive scenario.
- Do not request backend services, private APIs, authentication, or unavailable hardware.
- Do not mention ArtifactsBench, benchmark, evaluation, categories, seeds, or source examples.
- Do not output code, a grading checklist, rubric, solution, or implementation commentary.
- Aim for 130-280 English words. Bullets are allowed when natural.

Before returning JSON, silently verify that the request stays in the exact subclass, differs structurally from every seed, is fully demonstrable offline, obeys the complexity budget, and contains no prohibited capability. Revise it internally if any check fails. Do not output this verification.

Return JSON only:
{{
  "query": "the complete new user request",
  "short_name": "a concise internal name",
  "artifact_archetype": "the specific artifact form",
  "target_subclass": "{target_subclass or 'a suitable fine-grained subclass'}"
}}

Source queries:
{chr(10).join(examples)}
"""


def generate_one(client: OpenAI, model: str, category: str, sample_id: int,
                 seeds: list[dict[str, Any]], max_seed_chars: int,
                 max_retries: int, target_subclass: str | None = None,
                 diversity_lane: str | None = None) -> dict[str, Any]:
    prompt = build_prompt(category, seeds, max_seed_chars, target_subclass, diversity_lane)
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "Synthesize one novel executable visual-artifact request. Return valid JSON only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.95,
                max_tokens=1500,
            )
            parsed = parse_response(response.choices[0].message.content or "")
            return {
                "status": "ok",
                "category": category,
                "sample_id": sample_id,
                "query": str(parsed["query"]).strip(),
                "short_name": str(parsed.get("short_name", "")).strip(),
                "artifact_archetype": str(parsed.get("artifact_archetype", "")).strip(),
                "target_subclass": target_subclass or str(parsed.get("target_subclass", "")).strip(),
                "diversity_lane": diversity_lane or "",
                "source_indices": [seed["index"] for seed in seeds],
                "source_classes": [seed["class"] for seed in seeds],
                "model": model,
                "attempt": attempt,
            }
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    return {
        "status": "error", "category": category, "sample_id": sample_id,
        "source_indices": [seed["index"] for seed in seeds], "model": model,
        "error": f"{type(last_error).__name__}: {last_error}",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("datasets/ArtifactsBenchmark_full/artifacts_bench.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--model", help="override OPENAI_MODEL without changing the env file")
    parser.add_argument("--per-category", type=int, default=2)
    parser.add_argument("--special-fine-classes", action="store_true",
                        help="generate per official ArtifactsBench-specific fine class")
    parser.add_argument("--fine-class", action="append", dest="fine_classes",
                        help="limit special generation to this exact fine class; repeatable")
    parser.add_argument("--seeds-per-query", type=int, default=4)
    parser.add_argument("--max-seed-chars", type=int, default=1800)
    parser.add_argument("--seed", type=int, default=20260730)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-retries", type=int, default=3)
    args = parser.parse_args()

    load_env(args.env_file)
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "")
    model = args.model or os.environ.get("OPENAI_MODEL", "")
    if not api_key or not base_url or not model:
        parser.error("OPENAI_API_KEY, OPENAI_BASE_URL and OPENAI_MODEL are required")

    rows = load_jsonl(args.input)
    groups = {category: [] for category in CATEGORY_GUIDANCE}
    for row in rows:
        category = coarse_class(str(row.get("class", "")))
        if category in groups and row.get("question"):
            groups[category].append(row)

    jobs = []
    if args.special_fine_classes:
        fine_groups: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            fine_groups.setdefault(str(row.get("class", "")), []).append(row)
        selected_fine_classes = tuple(args.fine_classes or SPECIAL_FINE_CLASSES)
        unknown = set(selected_fine_classes) - set(SPECIAL_FINE_CLASSES)
        if unknown:
            raise ValueError(f"unsupported fine classes: {sorted(unknown)}")
        for fine_class in selected_fine_classes:
            pool = fine_groups.get(fine_class, [])
            if len(pool) < args.seeds_per_query:
                raise ValueError(f"{fine_class} has only {len(pool)} seeds")
            category = coarse_class(fine_class)
            # Mermaid is a separately published class, folded into the paper's
            # ninth catch-all family for the coarse nine-category view.
            rng = random.Random(f"{args.seed}:{fine_class}:pool")
            shuffled = pool[:]
            rng.shuffle(shuffled)
            for sample_id in range(1, args.per_category + 1):
                # Sliding windows cover the pool more evenly across outputs;
                # wraparound is necessary for official classes with few seeds.
                start = ((sample_id - 1) * args.seeds_per_query) % len(shuffled)
                seeds = [shuffled[(start + i) % len(shuffled)] for i in range(args.seeds_per_query)]
                lane_rng = random.Random(f"{args.seed}:{fine_class}:{sample_id}:lane")
                allowed_lanes = FINE_CLASS_LANES[fine_class]
                lane = DIVERSITY_LANES[allowed_lanes[lane_rng.randrange(len(allowed_lanes))]]
                jobs.append((category, sample_id, seeds, fine_class, lane))
    else:
        for category, pool in groups.items():
            if len(pool) < args.seeds_per_query:
                raise ValueError(f"{category} has only {len(pool)} seeds")
            for sample_id in range(1, args.per_category + 1):
                rng = random.Random(f"{args.seed}:{category}:{sample_id}")
                lane = DIVERSITY_LANES[(sample_id - 1) % len(DIVERSITY_LANES)]
                jobs.append((category, sample_id, rng.sample(pool, args.seeds_per_query), None, lane))

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=180.0, max_retries=0)
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(generate_one, client, model, category, sample_id, seeds,
                            args.max_seed_chars, args.max_retries, target_subclass, diversity_lane)
            for category, sample_id, seeds, target_subclass, diversity_lane in jobs
        ]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(f"{result['category']} #{result['sample_id']}: {result['status']}", flush=True)

    category_order = {category: i for i, category in enumerate(CATEGORY_GUIDANCE)}
    results.sort(key=lambda row: (category_order[row["category"]], row["target_subclass"], row["sample_id"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in results), encoding="utf-8")
    print(f"wrote {len(results)} records to {args.output}")


if __name__ == "__main__":
    main()
