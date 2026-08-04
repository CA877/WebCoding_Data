#!/usr/bin/env python3
"""Generate one new query from multiple WebCompass queries in each domain.

This intentionally performs no quality filtering or similarity screening.  It
stores source IDs so the raw LLM synthesis can be inspected directly.
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


def load_env(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def parse_json_object(text: str) -> dict[str, Any]:
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
        raise ValueError("model response has no non-empty query")
    return value


def seed_excerpt(instruction: str, limit: int) -> str:
    instruction = instruction.strip()
    return instruction if len(instruction) <= limit else instruction[:limit] + "\n[seed truncated]"


def build_prompt(domain: str, seeds: list[dict[str, Any]], max_seed_chars: int) -> str:
    blocks = []
    for number, seed in enumerate(seeds, 1):
        blocks.append(
            f"<seed number=\"{number}\" id=\"{seed['instance_id']}\">\n"
            f"{seed_excerpt(seed['instruction'], max_seed_chars)}\n</seed>"
        )
    return f"""You synthesize realistic text-guided web generation requests.

The examples below belong to the WebCompass domain: {domain}.
Create ONE new query in the same domain by learning the shared scope and level of detail across all examples.

Requirements:
- The result must describe a genuinely new website or browser application, not summarize or combine the seed products.
- Specify page/content structure, important interactive behavior, and a coherent visual direction.
- Include enough detail for a coding model to implement a demonstrable result.
- Keep the feature set coherent; do not output a grading rubric or checklist.
- Do not mention WebCompass, benchmark, seeds, reference examples, or evaluation.
- Do not copy brand names, distinctive phrases, exact data, or rare entity combinations from a seed.
- Do not output code.
- Aim for 180-350 English words. Natural headings or bullet points inside the query are allowed.

Return JSON only:
{{
  "query": "the new query",
  "short_name": "a concise internal name",
  "artifact_archetype": "what kind of web product this is"
}}

Examples:
{chr(10).join(blocks)}
"""


def generate_one(client: OpenAI, model: str, domain: str, seeds: list[dict[str, Any]],
                 max_seed_chars: int, max_retries: int) -> dict[str, Any]:
    prompt = build_prompt(domain, seeds, max_seed_chars)
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "Generate one new web-development user query and return valid JSON only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.9,
                max_tokens=1800,
            )
            parsed = parse_json_object(response.choices[0].message.content or "")
            return {
                "status": "ok",
                "class": domain,
                "query": str(parsed["query"]).strip(),
                "short_name": str(parsed.get("short_name", "")).strip(),
                "artifact_archetype": str(parsed.get("artifact_archetype", "")).strip(),
                "source_instance_ids": [str(seed["instance_id"]) for seed in seeds],
                "model": model,
                "attempt": attempt,
            }
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    return {
        "status": "error",
        "class": domain,
        "source_instance_ids": [str(seed["instance_id"]) for seed in seeds],
        "model": model,
        "error": f"{type(last_error).__name__}: {last_error}",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("datasets/WebCompass_text_generation/data.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--seeds-per-class", type=int, default=4)
    parser.add_argument("--max-seed-chars", type=int, default=2800)
    parser.add_argument("--seed", type=int, default=20260730)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-retries", type=int, default=3)
    args = parser.parse_args()
    load_env(args.env_file)
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "")
    model = os.environ.get("OPENAI_MODEL", "")
    if not api_key or not base_url or not model:
        parser.error("OPENAI_API_KEY, OPENAI_BASE_URL and OPENAI_MODEL are required")
    rows = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()]
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        domain = str((row.get("meta") or {}).get("class", "")).strip()
        if domain and row.get("instruction"):
            groups.setdefault(domain, []).append(row)

    jobs = []
    for domain in sorted(groups):
        rng = random.Random(f"{args.seed}:{domain}")
        pool = groups[domain]
        count = min(args.seeds_per_class, len(pool))
        jobs.append((domain, rng.sample(pool, count)))

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=180.0, max_retries=0)
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(generate_one, client, model, domain, seeds, args.max_seed_chars, args.max_retries): domain
            for domain, seeds in jobs
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(f"{result['class']}: {result['status']}", flush=True)

    order = {domain: index for index, domain in enumerate(sorted(groups))}
    results.sort(key=lambda item: order[item["class"]])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in results), encoding="utf-8")
    print(f"wrote {len(results)} records to {args.output}")


if __name__ == "__main__":
    main()
