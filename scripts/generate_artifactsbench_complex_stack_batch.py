#!/usr/bin/env python3
"""Resume-safe batch generation for complex-stack ArtifactsBench queries."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
import os
from pathlib import Path
import random
import time
from typing import Any

from openai import OpenAI

from generate_artifactsbench_queries import load_env, load_jsonl
from generate_artifactsbench_complex_stack_queries import (
    STACKS,
    build_prompt,
    generate_one,
    select_pool,
    supplement_pool,
)


# Counts measured directly from the 1,825 official questions. Tracks overlap in
# the source set by design; here they define the desired generation mixture.
TRACK_WEIGHTS = {
    "vue": 137,
    "react": 35,
    "typescript": 19,
    "python_backend": 24,
    "java_backend": 15,
    "database_fullstack": 82,
    "desktop_electron": 16,
    "mobile_miniprogram": 127,
    "threejs": 7,
    "webgl": 2,
}


def largest_remainder(total: int) -> dict[str, int]:
    denominator = sum(TRACK_WEIGHTS.values())
    exact = {key: total * value / denominator for key, value in TRACK_WEIGHTS.items()}
    quota = {key: math.floor(value) for key, value in exact.items()}
    remaining = total - sum(quota.values())
    order = {key: i for i, key in enumerate(TRACK_WEIGHTS)}
    ranked = sorted(
        TRACK_WEIGHTS,
        key=lambda key: (-(exact[key] - quota[key]), order[key]),
    )
    for key in ranked[:remaining]:
        quota[key] += 1
    return quota


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def build_plan(rows: list[dict[str, Any]], total: int, seeds_per_query: int,
               seed: int) -> list[dict[str, Any]]:
    quota = largest_remainder(total)
    plan = []
    sequence = 0
    for track in TRACK_WEIGHTS:
        pool = supplement_pool(
            track, rows, select_pool(rows, STACKS[track]["pattern"]), seeds_per_query,
        )
        if len(pool) < seeds_per_query:
            raise ValueError(f"{track}: only {len(pool)} seeds")
        shuffled = pool[:]
        random.Random(f"{seed}:{track}").shuffle(shuffled)
        for ordinal in range(1, quota[track] + 1):
            sequence += 1
            start = ((ordinal - 1) * seeds_per_query) % len(shuffled)
            seeds = [shuffled[(start + offset) % len(shuffled)] for offset in range(seeds_per_query)]
            plan.append({
                "job_id": f"complex-{sequence:05d}",
                "technology_track": track,
                "sample_id": ordinal,
                "track_quota": quota[track],
                "source_indices": [row["index"] for row in seeds],
                "source_classes": [row["class"] for row in seeds],
            })
    return plan


def run_one(client: OpenAI, model: str, job: dict[str, Any], by_id: dict[int, dict[str, Any]],
            records: Path, errors: Path, max_retries: int) -> dict[str, Any]:
    seeds = [by_id[index] for index in job["source_indices"]]
    last: dict[str, Any] | None = None
    for outer_attempt in range(1, max_retries + 1):
        result = generate_one(client, model, job["technology_track"], job["sample_id"], seeds, 1)
        if result["status"] == "ok":
            result.update({
                "job_id": job["job_id"],
                "track_quota": job["track_quota"],
                "attempt": outer_attempt,
            })
            atomic_json(records / f"{job['job_id']}.json", result)
            error_path = errors / f"{job['job_id']}.json"
            if error_path.exists():
                error_path.unlink()
            return result
        last = result
        if outer_attempt < max_retries:
            jitter = random.Random(f"{job['job_id']}:{outer_attempt}").random()
            time.sleep(min(45.0, 2 ** outer_attempt) * (0.8 + 0.4 * jitter))
    error = {**job, "status": "error", "model": model, "error": (last or {}).get("error", "unknown")}
    atomic_json(errors / f"{job['job_id']}.json", error)
    return error


def merge(plan: list[dict[str, Any]], records: Path, output: Path) -> int:
    rows = []
    for job in plan:
        path = records / f"{job['job_id']}.json"
        if path.is_file():
            row = json.loads(path.read_text(encoding="utf-8"))
            if row.get("status") == "ok":
                rows.append(row)
    write_jsonl(output, rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("datasets/ArtifactsBenchmark_full/artifacts_bench.json"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--model")
    parser.add_argument("--total", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seeds-per-query", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20260731)
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()

    rows = load_jsonl(args.input)
    by_id = {int(row["index"]): row for row in rows}
    root = args.output_dir
    plan_path = root / "plan.jsonl"
    summary_path = root / "plan_summary.json"
    records = root / "records"
    errors = root / "errors"
    output = root / "queries.jsonl"

    if plan_path.is_file():
        plan = load_jsonl(plan_path)
        if len(plan) != args.total:
            parser.error(f"existing plan has {len(plan)} jobs, requested {args.total}")
    else:
        plan = build_plan(rows, args.total, args.seeds_per_query, args.seed)
        write_jsonl(plan_path, plan)
        atomic_json(summary_path, {
            "total": args.total,
            "weights": TRACK_WEIGHTS,
            "quota": largest_remainder(args.total),
            "seed": args.seed,
            "seeds_per_query": args.seeds_per_query,
        })

    records.mkdir(parents=True, exist_ok=True)
    errors.mkdir(parents=True, exist_ok=True)
    completed = {path.stem for path in records.glob("complex-*.json")}
    pending = [job for job in plan if job["job_id"] not in completed]
    print(f"plan={len(plan)} completed={len(completed)} pending={len(pending)} quota={largest_remainder(args.total)}", flush=True)
    if args.plan_only:
        print(f"merged={merge(plan, records, output)}")
        return

    load_env(args.env_file)
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "")
    model = args.model or os.environ.get("OPENAI_MODEL", "")
    if not api_key or not base_url or not model:
        parser.error("OPENAI_API_KEY, OPENAI_BASE_URL, and model are required")
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=240, max_retries=0)

    ok = len(completed)
    failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(run_one, client, model, job, by_id, records, errors, args.max_retries)
            for job in pending
        ]
        for done, future in enumerate(as_completed(futures), 1):
            result = future.result()
            if result["status"] == "ok":
                ok += 1
            else:
                failed += 1
            if done <= 20 or done % 25 == 0 or done == len(pending):
                print(
                    f"progress={done}/{len(pending)} total_ok={ok} run_errors={failed} "
                    f"last={result['job_id']}:{result['status']}", flush=True,
                )
    merged = merge(plan, records, output)
    print(f"finished merged={merged}/{len(plan)} errors={failed} output={output}", flush=True)


if __name__ == "__main__":
    main()
