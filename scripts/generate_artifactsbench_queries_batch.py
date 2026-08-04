#!/usr/bin/env python3
"""Robust large-batch ArtifactsBench query synthesis.

The script first freezes a deterministic job plan whose coarse and fine-class
quotas follow the official benchmark distribution. Each successful API result
is written atomically as one record, so interrupted runs can resume safely.

This stage intentionally performs no reviewer scoring or quality filtering.
It only validates that the API returned the required JSON shape.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import threading
import time
from typing import Any, Iterable

from openai import OpenAI

from generate_artifactsbench_queries import (
    CATEGORY_GUIDANCE,
    DIVERSITY_LANES,
    FINE_CLASS_GUIDANCE,
    FINE_CLASS_LANES,
    build_prompt,
    clean_seed,
    coarse_class,
    load_env,
    load_jsonl,
    parse_response,
)


PAPER_CATEGORY_ORDER = (
    "Game Development",
    "SVG Generation",
    "Web Applications",
    "Simulation & Modeling",
    "Data Science",
    "Management Systems",
    "Multimedia Editing",
    "Utility Tools",
    "Other",
)

# Scenario hints are deliberately broad. They provide combinatorial diversity
# without prescribing the final product or overriding the target fine class.
SCENARIO_HINTS = {
    "Game Development": (
        "clockwork workshop", "deep-sea expedition", "night market", "orbital station",
        "botanical conservatory", "desert caravan", "paper-theater stage", "signal tower",
        "microbial world", "museum after hours", "weather observatory", "subway maintenance",
        "alpine rescue", "ceramic studio", "bioluminescent reef", "archive restoration",
    ),
    "SVG Generation": (
        "ecological field guide", "kinetic typography", "astronomical instrument", "folk textile",
        "mechanical cutaway", "botanical specimen", "wayfinding system", "festival identity",
        "scientific illustration", "architectural ornament", "weather symbol set", "music notation",
        "packaging emblem", "topographic composition", "stained glass", "modular paper craft",
    ),
    "Web Applications": (
        "community tool library", "oral-history archive", "field research notebook", "repair cafe",
        "small venue program", "citizen science project", "language exchange", "local food network",
        "museum collection", "volunteer coordination", "study cohort", "accessible travel planning",
        "independent publishing", "craft marketplace", "neighborhood observatory", "public workshop",
    ),
    "Simulation & Modeling": (
        "material deformation", "collective motion", "wave interference", "ecological succession",
        "orbital mechanics", "structural balance", "fluid flow", "thermal diffusion",
        "transport network", "optical system", "population dynamics", "acoustic resonance",
        "geometric packing", "electromagnetic field", "erosion process", "mechanical linkage",
    ),
    "Data Science": (
        "urban tree health", "library circulation", "microclimate sensors", "wildlife observations",
        "energy demand", "public transit reliability", "crop trials", "material fatigue tests",
        "water quality", "museum attendance", "bicycle counts", "coastal measurements",
        "workshop production", "astronomy survey", "language learning", "habitat restoration",
    ),
    "Management Systems": (
        "conservation lab", "equipment lending", "community kitchen", "field expedition",
        "small theater", "makerspace", "seed library", "animal shelter",
        "research collection", "repair workshop", "mobile clinic", "event production",
        "public garden", "training program", "archive digitization", "shared studio",
    ),
    "Multimedia Editing": (
        "radio drama", "stop-motion planning", "field recording", "oral-history clips",
        "experimental typography", "museum labels", "dance rehearsal", "nature soundscape",
        "photo contact sheet", "projection mapping plan", "podcast cues", "animation blocking",
        "collage composition", "color study", "foley session", "documentary storyboard",
    ),
    "Utility Tools": (
        "workshop measurements", "research data cleanup", "print production", "inventory labels",
        "travel packing", "garden planning", "energy estimates", "fabric cutting",
        "classroom materials", "maintenance records", "photography metadata", "shipping layout",
        "recipe scaling", "survey formatting", "calendar conversion", "accessibility checks",
    ),
    "Other": (
        "knowledge map", "interactive essay", "procedural pattern", "decision explorer",
        "spatial narrative", "visual notation", "concept atlas", "generative diagram",
        "timeline artifact", "experimental interface", "learning manipulative", "symbolic system",
        "branching story", "relationship map", "visual proof", "creative coding study",
    ),
}

VISUAL_HINTS = (
    "restrained editorial", "technical blueprint", "warm tactile", "high-contrast monochrome",
    "soft scientific", "retro-futurist", "museum exhibit", "playful geometric",
    "dense information-design", "calm minimal", "handcrafted paper", "luminous dark-mode",
)


def paper_category(fine_class: str) -> str:
    category = coarse_class(fine_class)
    return "Other" if fine_class.startswith("Mermaid Flowcharts-") else category


def stable_int(text: str) -> int:
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")


def allocate_largest_remainder(weights: dict[str, int], total: int,
                               order: Iterable[str] | None = None) -> dict[str, int]:
    """Allocate integer quotas summing exactly to total."""
    if total < 0 or not weights or sum(weights.values()) <= 0:
        raise ValueError("invalid quota inputs")
    denominator = sum(weights.values())
    exact = {key: total * value / denominator for key, value in weights.items()}
    quota = {key: math.floor(value) for key, value in exact.items()}
    remaining = total - sum(quota.values())
    rank = {key: i for i, key in enumerate(order or weights)}
    candidates = sorted(
        weights,
        key=lambda key: (-(exact[key] - quota[key]), rank.get(key, len(rank)), key),
    )
    for key in candidates[:remaining]:
        quota[key] += 1
    return quota


def official_groups(rows: list[dict[str, Any]]) -> tuple[
        dict[str, list[dict[str, Any]]], dict[str, dict[str, list[dict[str, Any]]]]]:
    coarse: dict[str, list[dict[str, Any]]] = {category: [] for category in PAPER_CATEGORY_ORDER}
    fine: dict[str, dict[str, list[dict[str, Any]]]] = {category: {} for category in PAPER_CATEGORY_ORDER}
    for row in rows:
        fine_class = str(row.get("class", "")).strip()
        question = str(row.get("question", "")).strip()
        if not fine_class or not question:
            continue
        category = paper_category(fine_class)
        if category not in coarse:
            continue
        coarse[category].append(row)
        fine[category].setdefault(fine_class, []).append(row)
    return coarse, fine


def make_quota(rows: list[dict[str, Any]], total: int) -> tuple[dict[str, int], dict[str, int]]:
    coarse_groups, fine_groups = official_groups(rows)
    coarse_weights = {category: len(coarse_groups[category]) for category in PAPER_CATEGORY_ORDER}
    coarse_quota = allocate_largest_remainder(coarse_weights, total, PAPER_CATEGORY_ORDER)
    fine_quota: dict[str, int] = {}
    for category in PAPER_CATEGORY_ORDER:
        weights = {fine_class: len(pool) for fine_class, pool in fine_groups[category].items()}
        allocated = allocate_largest_remainder(weights, coarse_quota[category], sorted(weights))
        fine_quota.update(allocated)
    if sum(fine_quota.values()) != total:
        raise AssertionError("fine-class quota does not sum to requested total")
    return coarse_quota, fine_quota


def choose_seeds(fine_pool: list[dict[str, Any]], coarse_pool: list[dict[str, Any]],
                 count: int, job_key: str, ordinal: int) -> list[dict[str, Any]]:
    """Prefer target-fine-class seeds, then supplement rare classes."""
    rng = random.Random(f"{job_key}:seed-pool")
    fine_shuffled = fine_pool[:]
    rng.shuffle(fine_shuffled)
    chosen: list[dict[str, Any]] = []
    if fine_shuffled:
        start = ((ordinal - 1) * count) % len(fine_shuffled)
        for offset in range(min(count, len(fine_shuffled))):
            chosen.append(fine_shuffled[(start + offset) % len(fine_shuffled)])

    chosen_ids = {row["index"] for row in chosen}
    supplement = [row for row in coarse_pool if row["index"] not in chosen_ids]
    supplement_rng = random.Random(f"{job_key}:{ordinal}:supplement")
    supplement_rng.shuffle(supplement)
    chosen.extend(supplement[:max(0, count - len(chosen))])
    if len(chosen) != count:
        raise ValueError(f"could not select {count} distinct seeds for {job_key}")
    return chosen


def lane_for(fine_class: str, ordinal: int, global_seed: int) -> str:
    allowed = FINE_CLASS_LANES.get(fine_class, tuple(range(len(DIVERSITY_LANES))))
    offset = stable_int(f"{global_seed}:{fine_class}:lane") % len(allowed)
    return DIVERSITY_LANES[allowed[(offset + ordinal - 1) % len(allowed)]]


def creative_brief(category: str, fine_class: str, ordinal: int, global_seed: int) -> str:
    scenario_pool = SCENARIO_HINTS[category]
    base = stable_int(f"{global_seed}:{fine_class}:creative")
    scenario = scenario_pool[(base + ordinal - 1) % len(scenario_pool)]
    visual = VISUAL_HINTS[((base // len(scenario_pool)) + ordinal - 1) % len(VISUAL_HINTS)]
    return (
        f"Use `{scenario}` only as loose scenario inspiration and a `{visual}` visual direction. "
        "Change or reinterpret either when needed to preserve the exact subclass."
    )


def build_plan(rows: list[dict[str, Any]], total: int, seeds_per_query: int,
               global_seed: int) -> tuple[list[dict[str, Any]], dict[str, int]]:
    coarse_groups, fine_groups = official_groups(rows)
    coarse_quota, fine_quota = make_quota(rows, total)
    plan: list[dict[str, Any]] = []
    sequence = 0
    for category in PAPER_CATEGORY_ORDER:
        for fine_class in sorted(fine_groups[category]):
            quota = fine_quota.get(fine_class, 0)
            for ordinal in range(1, quota + 1):
                sequence += 1
                job_id = f"abq-{sequence:06d}"
                seeds = choose_seeds(
                    fine_groups[category][fine_class], coarse_groups[category],
                    seeds_per_query, f"{global_seed}:{fine_class}", ordinal,
                )
                plan.append({
                    "job_id": job_id,
                    "category": category,
                    "target_subclass": fine_class,
                    "class_ordinal": ordinal,
                    "class_quota": quota,
                    "diversity_lane": lane_for(fine_class, ordinal, global_seed),
                    "creative_brief": creative_brief(category, fine_class, ordinal, global_seed),
                    "source_indices": [row["index"] for row in seeds],
                    "source_classes": [row["class"] for row in seeds],
                })
    if len(plan) != total:
        raise AssertionError(f"plan has {len(plan)} jobs, expected {total}")
    return plan, coarse_quota


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(temporary, path)


def read_plan(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def add_batch_context(prompt: str, job: dict[str, Any]) -> str:
    return prompt.replace(
        "Source queries:\n",
        "Additional variation brief:\n"
        f"- This is concept {job['class_ordinal']} of {job['class_quota']} planned for this subclass.\n"
        f"- {job['creative_brief']}\n"
        "- Produce a distinct concept, not a generic dashboard and not a cosmetic reskin of a source.\n\n"
        "Source queries:\n",
    )


def retry_delay_seconds(attempt: int, job_id: str, base: float, maximum: float) -> float:
    jitter_rng = random.Random(f"{job_id}:{attempt}:retry")
    return min(maximum, base * (2 ** (attempt - 1))) * (0.75 + 0.5 * jitter_rng.random())


def run_job(client: OpenAI, model: str, job: dict[str, Any], source_by_id: dict[int, dict[str, Any]],
            records_dir: Path, errors_dir: Path, max_seed_chars: int, max_retries: int,
            max_tokens: int, retry_base: float, retry_max: float,
            enable_thinking: bool) -> dict[str, Any]:
    seeds = [source_by_id[index] for index in job["source_indices"]]
    prompt = build_prompt(
        job["category"], seeds, max_seed_chars,
        job["target_subclass"], job["diversity_lane"],
    )
    prompt = add_batch_context(prompt, job)
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
                max_tokens=max_tokens,
                extra_body={"enable_thinking": enable_thinking},
            )
            parsed = parse_response(response.choices[0].message.content or "")
            record = {
                "status": "ok",
                **job,
                "query": str(parsed["query"]).strip(),
                "short_name": str(parsed.get("short_name", "")).strip(),
                "artifact_archetype": str(parsed.get("artifact_archetype", "")).strip(),
                "model": model,
                "attempt": attempt,
            }
            atomic_write_json(records_dir / f"{job['job_id']}.json", record)
            error_path = errors_dir / f"{job['job_id']}.json"
            if error_path.exists():
                error_path.unlink()
            return record
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < max_retries:
                time.sleep(retry_delay_seconds(attempt, job["job_id"], retry_base, retry_max))
    error = {
        "status": "error", **job, "model": model, "attempt": max_retries,
        "error": f"{type(last_error).__name__}: {last_error}",
    }
    atomic_write_json(errors_dir / f"{job['job_id']}.json", error)
    return error


def merge_records(plan: list[dict[str, Any]], records_dir: Path, output_path: Path) -> int:
    rows = []
    for job in plan:
        path = records_dir / f"{job['job_id']}.json"
        if path.is_file():
            row = json.loads(path.read_text(encoding="utf-8"))
            if row.get("status") == "ok":
                rows.append(row)
    write_jsonl(output_path, rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("datasets/ArtifactsBenchmark_full/artifacts_bench.json"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--total", type=int, default=3000)
    parser.add_argument("--seeds-per-query", type=int, default=4)
    parser.add_argument("--max-seed-chars", type=int, default=1800)
    parser.add_argument("--seed", type=int, default=20260731)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--max-retries", type=int, default=6)
    parser.add_argument("--max-tokens", type=int, default=1600)
    parser.add_argument("--request-timeout", type=float, default=180.0)
    parser.add_argument("--enable-thinking", action="store_true",
                        help="enable model reasoning tokens; disabled by default to control cost")
    parser.add_argument("--retry-base", type=float, default=2.0)
    parser.add_argument("--retry-max", type=float, default=60.0)
    parser.add_argument("--model", help="override OPENAI_MODEL")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--base-url-env", default="OPENAI_BASE_URL")
    parser.add_argument("--model-env", default="OPENAI_MODEL")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--rebuild-plan", action="store_true")
    args = parser.parse_args()

    if args.total <= 0 or args.seeds_per_query < 2 or args.workers <= 0:
        parser.error("total and workers must be positive; seeds-per-query must be at least 2")

    rows = load_jsonl(args.input)
    source_by_id = {int(row["index"]): row for row in rows}
    output_dir = args.output_dir
    plan_path = output_dir / "plan.jsonl"
    summary_path = output_dir / "plan_summary.json"
    records_dir = output_dir / "records"
    errors_dir = output_dir / "errors"
    output_path = output_dir / "queries.jsonl"

    if plan_path.exists() and not args.rebuild_plan:
        plan = read_plan(plan_path)
        if len(plan) != args.total:
            parser.error(
                f"existing plan has {len(plan)} jobs, not --total {args.total}; "
                "use the original total or --rebuild-plan"
            )
    else:
        plan, coarse_quota = build_plan(rows, args.total, args.seeds_per_query, args.seed)
        write_jsonl(plan_path, plan)
        fine_quota: dict[str, int] = {}
        for job in plan:
            fine_quota[job["target_subclass"]] = fine_quota.get(job["target_subclass"], 0) + 1
        atomic_write_json(summary_path, {
            "total": args.total,
            "seed": args.seed,
            "seeds_per_query": args.seeds_per_query,
            "coarse_quota": coarse_quota,
            "fine_quota": fine_quota,
        })

    records_dir.mkdir(parents=True, exist_ok=True)
    errors_dir.mkdir(parents=True, exist_ok=True)
    completed = {
        path.stem for path in records_dir.glob("abq-*.json")
        if json.loads(path.read_text(encoding="utf-8")).get("status") == "ok"
    }
    pending = [job for job in plan if job["job_id"] not in completed]
    print(f"plan={len(plan)} completed={len(completed)} pending={len(pending)}", flush=True)
    if args.plan_only:
        merged = merge_records(plan, records_dir, output_path)
        print(f"plan only; merged {merged} completed records into {output_path}")
        return

    load_env(args.env_file)
    api_key = os.environ.get(args.api_key_env, "")
    base_url = os.environ.get(args.base_url_env, "")
    model = args.model or os.environ.get(args.model_env, "")
    if not api_key or not base_url or not model:
        parser.error(
            f"missing API configuration: {args.api_key_env}, {args.base_url_env}, "
            f"and --model/{args.model_env} are required"
        )

    client = OpenAI(
        api_key=api_key, base_url=base_url,
        timeout=args.request_timeout, max_retries=0,
    )
    progress_lock = threading.Lock()
    counters = {"ok": len(completed), "error": 0, "finished": 0}
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                run_job, client, model, job, source_by_id, records_dir, errors_dir,
                args.max_seed_chars, args.max_retries, args.max_tokens,
                args.retry_base, args.retry_max, args.enable_thinking,
            ): job["job_id"]
            for job in pending
        }
        for future in as_completed(futures):
            result = future.result()
            with progress_lock:
                counters["finished"] += 1
                if result["status"] == "ok":
                    counters["ok"] += 1
                else:
                    counters["error"] += 1
                done = counters["finished"]
                if done <= 20 or done % 25 == 0 or done == len(pending):
                    print(
                        f"progress={done}/{len(pending)} total_ok={counters['ok']} "
                        f"run_errors={counters['error']} last={result['job_id']}:{result['status']}",
                        flush=True,
                    )

    merged = merge_records(plan, records_dir, output_path)
    print(
        f"finished: merged={merged}/{len(plan)} errors={counters['error']} "
        f"output={output_path}",
        flush=True,
    )


if __name__ == "__main__":
    main()
