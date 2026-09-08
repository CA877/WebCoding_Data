#!/usr/bin/env python3
"""Verify cache use for the stable prefix used by linear Edit query generation."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from instruction_augmentation.doc_api import DocApiClient, usage_cache_counts
from instruction_augmentation.linear_edit_queries import GENERATION_SYSTEM, generation_stable_prefix


UNRELATED_SOURCE = """<<<FILE:index.html>>>
<main><h1>Community Garden Roster</h1><button id="assign">Assign plot</button></main>
<<<END_FILE>>>
<<<FILE:app.js>>>
const plots = [{id: 'p1', gardener: null}];
<<<END_FILE>>>"""


def load_completed_preflight(log_dir: Path) -> tuple[str, dict, str, dict] | None:
    usage_path = log_dir / "usage.jsonl"
    response_paths = [
        log_dir / "responses" / "linear_cache_1.txt",
        log_dir / "responses" / "linear_cache_2.txt",
    ]
    artifacts_exist = usage_path.exists() or any(path.exists() for path in response_paths)
    if not artifacts_exist:
        return None
    if not usage_path.is_file() or not all(path.is_file() for path in response_paths):
        raise ValueError("cache preflight has partial artifacts; paid requests will not be repeated")
    usage_by_id = {
        row["request_id"]: row
        for row in (
            json.loads(line)
            for line in usage_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }
    rows = [usage_by_id.get("linear_cache_1"), usage_by_id.get("linear_cache_2")]
    if any(not isinstance(row, dict) or row.get("status") != "ok" for row in rows):
        raise ValueError("cache preflight has failed artifacts; paid requests will not be repeated")
    return (
        response_paths[0].read_text(encoding="utf-8"),
        rows[0].get("usage") or {},
        response_paths[1].read_text(encoding="utf-8"),
        rows[1].get("usage") or {},
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-dir", type=Path, required=True)
    parser.add_argument("--retrieval", type=Path, required=True)
    args = parser.parse_args()
    key = os.environ.get("DOC_API_KEY")
    if not key:
        raise ValueError("DOC_API_KEY is required")
    retrieval = json.loads(args.retrieval.read_text(encoding="utf-8"))
    cards = retrieval.get("cards")
    if not isinstance(cards, list) or not cards:
        raise ValueError("retrieval artifact contains no planner cards")
    prefix = generation_stable_prefix({"capabilities": []}, retrieved_cards=cards)
    task = UNRELATED_SOURCE + "\nReply with exactly CACHE_OK."
    completed = load_completed_preflight(args.log_dir)
    if completed is not None:
        first_text, first_usage, second_text, second_usage = completed
    else:
        with DocApiClient(api_key=key, log_dir=args.log_dir) as client:
            first_text, first_usage = client.chat_text(
                request_id="linear_cache_1",
                system_prompt=GENERATION_SYSTEM,
                stable_context=prefix,
                task=task,
                max_tokens=8,
                stream=True,
            )
            second_text, second_usage = client.chat_text(
                request_id="linear_cache_2",
                system_prompt=GENERATION_SYSTEM,
                stable_context=prefix,
                task=task,
                max_tokens=8,
                stream=True,
            )
    first = usage_cache_counts(first_usage)
    second = usage_cache_counts(second_usage)
    if not first_text.strip() or not second_text.strip():
        raise ValueError("cache preflight returned an empty response")
    if first["cache_creation_input_tokens"] <= 0 or second["cached_tokens"] <= 0:
        raise ValueError(f"cache preflight failed: first={first}, second={second}")
    summary = {
        "status": "ok",
        "model": "qwen3.8-max",
        "stream": True,
        "cache_creation_input_tokens": first["cache_creation_input_tokens"],
        "cache_read_input_tokens": second["cached_tokens"],
        "sdk_retries": 0,
        "outer_retries": 0,
        "retrieval": str(args.retrieval.resolve()),
        "retrieval_query_sha256": retrieval["retrieval_query_sha256"],
    }
    (args.log_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
