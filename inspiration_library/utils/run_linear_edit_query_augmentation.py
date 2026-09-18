#!/usr/bin/env python3
"""Retrieve page-change cards once and generate 4-12 linear Edit queries per Seed."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
import random
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from inspiration_library.doc_api import DEFAULT_BASE_URL, DocApiClient
from inspiration_library.deep_browser_exploration import deep_explore_project
from inspiration_library.linear_edit_queries import (
    DEFAULT_EDIT_COUNT,
    MAX_EDIT_COUNT,
    MIN_EDIT_COUNT,
    append_jsonl,
    compact_browser_evidence,
    generate_edit_sequence,
    load_json_response,
    normalize_repeated_instruction_openings,
    planner_host_evidence_corpus,
    read_jsonl,
    validate_edit_sequence,
    validate_quality_audit,
)
from inspiration_library.dynamic_capability_retrieval import pool_snapshot_sha256
from inspiration_library.one_shot_capability_retrieval import (
    build_seed_retrieval_query,
    generate_seed_retrieval_query,
    generate_seed_retrieval_plan,
    retrieve_top_k_cards,
    validate_generated_retrieval_query,
    validate_generated_retrieval_plan,
)


def safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def write_json_once(path: Path, payload: object) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != rendered:
            raise ValueError(f"immutable output differs: {path}")
        return
    path.write_text(rendered, encoding="utf-8")


def completed_ids(path: Path, key: str) -> set[str]:
    if not path.exists():
        return set()
    return {str(row[key]) for row in read_jsonl(path) if key in row}


def successful_ids(path: Path, key: str) -> set[str]:
    if not path.exists():
        return set()
    return {
        str(row[key])
        for row in read_jsonl(path)
        if key in row and row.get("status") == "ok"
    }


def parse_edit_count_argument(value: str) -> int | str | None:
    if value.strip().lower() == "random":
        return "random"
    if value.strip().lower() == "auto":
        return None
    try:
        count = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("edit-count must be random, auto or an integer") from exc
    if not MIN_EDIT_COUNT <= count <= MAX_EDIT_COUNT:
        raise argparse.ArgumentTypeError(
            f"edit-count must be auto or an integer from {MIN_EDIT_COUNT} to {MAX_EDIT_COUNT}"
        )
    return count


def select_edit_counts(*, seed_ids: list[str], requested: int | str | None,
                       run_dir: Path, length_seed: int | None = None,
                       preserved_count: int | None = None) -> dict[str, int | None]:
    """Draw each chain length once; persist the seed and choices before any API work."""
    ids = sorted(seed_ids)
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('chain length selection requires unique seed ids')
    if preserved_count is not None and not MIN_EDIT_COUNT <= preserved_count <= MAX_EDIT_COUNT:
        raise ValueError('saved candidate length must be 4 to 12')
    identity = dict(seed_ids=ids, requested=requested, length_seed=length_seed,
                    preserved_count=preserved_count)
    path = run_dir/'edit_count_selection.json'
    if path.exists():
        saved = json.loads(path.read_text())
        if saved['identity'] != identity:
            raise ValueError('immutable chain length selection settings differ')
        sampled_seed = saved['sampled_seed']
    else:
        sampled_seed = length_seed if length_seed is not None else random.SystemRandom().getrandbits(64)
    rng = random.Random(sampled_seed)
    counts = {seed_id: preserved_count if preserved_count is not None else
              rng.randint(MIN_EDIT_COUNT, MAX_EDIT_COUNT) if requested == 'random' else requested
              for seed_id in ids}
    write_json_once(path, dict(identity=identity, sampled_seed=sampled_seed, counts=counts))
    return counts


def _reusable_artifact(
    evidence_run_dirs: tuple[Path, ...], relative: Path
) -> Path | None:
    matches = [directory / relative for directory in evidence_run_dirs]
    existing = [path for path in matches if path.exists()]
    if len(existing) > 1:
        first = existing[0].read_bytes()
        if any(path.read_bytes() != first for path in existing[1:]):
            raise ValueError(f"reusable evidence differs across run directories: {relative}")
    return existing[0] if existing else None


def load_or_observe(
    seed: dict[str, Any],
    run_dir: Path,
    *,
    client: DocApiClient,
    exploration_rounds: int,
    evidence_run_dirs: tuple[Path, ...] = (),
) -> dict[str, Any]:
    output_dir = run_dir / "browser" / seed["seed_id"]
    path = output_dir / "observation.json"
    source_path = path if path.exists() else _reusable_artifact(
        evidence_run_dirs,
        Path("browser") / str(seed["seed_id"]) / "observation.json",
    )
    if source_path is not None:
        observation = json.loads(source_path.read_text(encoding="utf-8"))
        if "deep_search" not in observation:
            raise ValueError(
                "cached host observation predates browser deep exploration; use a new run directory"
            )
        if source_path != path:
            observation = {**observation, "reused_from": str(source_path.resolve())}
            write_json_once(path, observation)
        return observation
    return deep_explore_project(
        project=Path(seed["project_path"]),
        output_dir=output_dir,
        client=client,
        request_prefix=f"host_observe__{safe_id(seed['seed_id'])}",
        max_rounds=exploration_rounds,
        max_paths=24,
    )


def _saved_embedding_vector(path: Path) -> list[float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    vectors = payload.get("vectors")
    if not isinstance(vectors, list) or len(vectors) != 1:
        raise ValueError(f"saved retrieval embedding has the wrong shape: {path}")
    vector = vectors[0]
    if not isinstance(vector, list) or not vector:
        raise ValueError(f"saved retrieval embedding is empty: {path}")
    return vector


def load_or_retrieve(
    *,
    seed: dict[str, Any],
    observation: dict[str, Any],
    embedded_pool: list[dict[str, Any]],
    top_k: int,
    max_per_family: int,
    run_dir: Path,
    query_client: DocApiClient,
    embedding_client: DocApiClient,
    evidence_run_dirs: tuple[Path, ...] = (),
    edit_count: int | None = None,
) -> dict[str, Any]:
    seed_key = safe_id(seed["seed_id"])
    output_path = run_dir / "retrievals" / f"{seed_key}.json"
    source_path = output_path if output_path.exists() else _reusable_artifact(
        evidence_run_dirs, Path("retrievals") / f"{seed_key}.json"
    )
    if source_path is not None:
        saved = json.loads(source_path.read_text(encoding="utf-8"))
        if saved.get("schema_version") != "webcoding-retrieve-before-plan-v3":
            if source_path == output_path:
                raise ValueError(
                    "cached retrieval predates retrieve-before-plan; use a new run directory"
                )
            source_path = None
        else:
            if saved.get("requested_edit_count") != edit_count:
                raise ValueError("cached retrieval has a different requested edit count")
            validated_plan = validate_generated_retrieval_plan(
                {
                    "retrieval_query": saved.get("retrieval_query"),
                    "dependency_plan": saved.get("dependency_plan"),
                    "module_plan": saved.get("module_plan"),
                },
                host_evidence_corpus=build_seed_retrieval_query(
                    seed=seed, observation=observation
                ),
            )
            if (
                saved.get("dependency_plan") != validated_plan["dependency_plan"]
                or saved.get("module_plan") != validated_plan["module_plan"]
            ):
                raise ValueError("immutable retrieval contains a non-canonical module plan")
            if saved.get("top_k") != top_k or saved.get("max_per_family") != max_per_family:
                raise ValueError("immutable retrieval was produced with different selection settings")
            current_pool_hash = pool_snapshot_sha256(embedded_pool)
            if saved.get("pool_snapshot_sha256") != current_pool_hash:
                raise ValueError("reusable retrieval was produced from a different capability pool")
            if source_path != output_path:
                saved = {**saved, "reused_from": str(source_path.resolve())}
                write_json_once(output_path, saved)
            return saved
    query_request_id = f"retrieval_query__{seed_key}"
    saved_query_response = (
        query_client.log_dir / "responses" / f"{query_request_id}.txt"
    )
    if saved_query_response.exists():
        retrieval_query = validate_generated_retrieval_query(load_json_response(saved_query_response))
    else:
        retrieval_query = generate_seed_retrieval_query(
            seed=seed,
            observation=observation,
            client=query_client,
            request_id=query_request_id,
        )
    request_id = f"retrieve_embed__{seed_key}"
    saved_response = embedding_client.log_dir / "responses" / f"{request_id}.json"
    if saved_response.exists():
        query_vector = _saved_embedding_vector(saved_response)
    else:
        vectors, _ = embedding_client.embeddings(
            request_id=request_id, inputs=[retrieval_query]
        )
        query_vector = vectors[0]
    selected = retrieve_top_k_cards(
        query_vector=query_vector,
        embedded_pool=embedded_pool,
        host_seed_id=str(seed["seed_id"]),
        top_k=top_k,
        max_per_family=max_per_family,
    )
    compact_selected = [
        {key: value for key, value in row.items() if key != "embedding"}
        for row in selected
    ]
    write_json_once(run_dir / 'recalls' / f'{seed_key}.json', {
        'retrieval_query':retrieval_query, 'cards':compact_selected,
        'pool_snapshot_sha256':pool_snapshot_sha256(embedded_pool),
    })
    plan_path = run_dir / "plans" / f"{seed_key}.json"
    if plan_path.exists():
        retrieval_plan = validate_generated_retrieval_plan(
            json.loads(plan_path.read_text()),
            host_evidence_corpus=build_seed_retrieval_query(seed=seed, observation=observation),
        )
    else:
        retrieval_plan = generate_seed_retrieval_plan(
            seed=seed, observation=observation, client=query_client,
            request_id=f"module_plan__{seed_key}", retrieved_cards=compact_selected,
            edit_count=edit_count, retrieval_query=retrieval_query,
        )
        write_json_once(plan_path, retrieval_plan)
    if edit_count is not None and len(retrieval_plan["module_plan"]) != edit_count:
        raise ValueError("module_plan does not match requested edit_count")
    payload = {
        "schema_version": "webcoding-retrieve-before-plan-v3",
        "requested_edit_count": edit_count,
        "seed_id": seed["seed_id"],
        "pool_snapshot_sha256": pool_snapshot_sha256(embedded_pool),
        "retrieval_query": retrieval_query,
        "retrieval_query_sha256": sha256(retrieval_query.encode("utf-8")).hexdigest(),
        "dependency_plan": retrieval_plan["dependency_plan"],
        "module_plan": retrieval_plan["module_plan"],
        "top_k": top_k,
        "max_per_family": max_per_family,
        "retrieved_capability_ids": [row["capability_id"] for row in selected],
        "cards": compact_selected,
        "retrieval_query_owner": "one_llm_call_from_seed_instruction_and_saved_browser_states",
        "planner_source_policy": "complete_host_source_facts_plus_browser_facts_and_topk_source_slices",
    }
    write_json_once(output_path, payload)
    return payload


def load_or_generate(
    *,
    seed: dict[str, Any],
    observation: dict[str, Any],
    retrieval: dict[str, Any],
    run_dir: Path,
    client: DocApiClient,
    edit_count: int | None,
    revision_candidate: Path | None = None,
    revision_feedback: str | None = None,
    candidate_response: Path | None = None,
) -> dict[str, Any]:
    seed_key = safe_id(seed["seed_id"])
    output_path = run_dir / "sequences" / f"{seed_key}.json"
    planner_cards = retrieval["cards"]
    module_plan = retrieval["module_plan"]
    effective_edit_count = edit_count if edit_count is not None else len(module_plan)
    if len(module_plan) != effective_edit_count:
        raise ValueError('module_plan does not match requested edit_count')
    donor_ids = {str(row["capability_id"]) for row in planner_cards}
    if output_path.exists():
        saved = json.loads(output_path.read_text(encoding="utf-8"))
        if saved.get("edit_count") != effective_edit_count:
            raise ValueError("immutable sequence was produced with a different edit count")
        validated = validate_edit_sequence(
            saved,
            seed_id=str(seed["seed_id"]),
            donor_ids=donor_ids,
            planner_cards=planner_cards,
            edit_count=effective_edit_count,
            host_evidence_corpus=planner_host_evidence_corpus(seed, observation),
            module_plan=module_plan,
        )
        validated["retrieval"] = saved.get("retrieval", {})
        if saved.get('instruction_review'):
            validated['instruction_review'] = saved['instruction_review']
        return validated
    response_path = run_dir / "provider" / "responses" / f"generate__{seed_key}.txt"
    if candidate_response and not response_path.exists():
        response_path = candidate_response
    if response_path.exists():
        sequence = validate_edit_sequence(
            normalize_repeated_instruction_openings(load_json_response(response_path)),
            seed_id=str(seed["seed_id"]),
            donor_ids=donor_ids,
            planner_cards=planner_cards,
            edit_count=effective_edit_count,
            host_evidence_corpus=planner_host_evidence_corpus(seed, observation),
            module_plan=module_plan,
        )
    else:
        sequence = generate_edit_sequence(
            seed=seed,
            observation=observation,
            capability_bank={"capabilities": []},
            client=client,
            request_id=f"generate__{seed_key}",
            retrieved_cards=planner_cards,
            edit_count=effective_edit_count,
            module_plan=module_plan,
            revision_candidate=load_json_response(revision_candidate) if revision_candidate else None,
            revision_feedback=revision_feedback,
        )
    sequence["retrieval"] = {
        "pool_snapshot_sha256": retrieval["pool_snapshot_sha256"],
        "retrieval_query_sha256": retrieval["retrieval_query_sha256"],
        "top_k": retrieval["top_k"],
        "retrieved_capability_ids": retrieval["retrieved_capability_ids"],
        "dependency_plan": retrieval["dependency_plan"],
        "module_plan_sha256": sha256(
            json.dumps(module_plan, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "planner_source_policy": "complete_host_source_facts_plus_browser_facts_and_topk_source_slices",
    }
    write_json_once(run_dir / 'candidates' / f'{seed_key}.json', sequence)
    write_json_once(output_path, sequence)
    return sequence


def export_queries(
    *,
    seed: dict[str, Any],
    observation: dict[str, Any],
    sequence: dict[str, Any],
    output_path: Path,
) -> None:
    if sequence.get('instruction_review'):
        review = validate_quality_audit(sequence['instruction_review'], seed_id=str(seed['seed_id']),
                                        edit_count=len(sequence['edits']))
        if review['sequence_decision'] != 'accept':
            raise ValueError('cannot export a semantically rejected sequence')
    done = completed_ids(output_path, "record_id")
    browser = compact_browser_evidence(observation)
    seed_runtime_status = "ok" if observation.get("status") == "ok" else "warning"
    for edit in sequence["edits"]:
        record_id = f"{seed['seed_id']}__{edit['edit_id']}"
        if record_id in done:
            continue
        append_jsonl(
            output_path,
            {
                "schema_version": "webcoding-linear-edit-query-record-v1",
                "record_id": record_id,
                "status": "ok",
                "seed_id": seed["seed_id"],
                "seed_dataset": seed["dataset"],
                "seed_project": seed["project_path"],
                "seed_runtime_status": seed_runtime_status,
                "source_version": edit["source_version"],
                "target_version": edit["target_version"],
                "edit_index": edit["edit_index"],
                "instruction": edit["instruction"],
                "origin": edit["origin"],
                "donor_capability_id": edit["donor_capability_id"],
                "donor_capability_ids": edit.get('donor_capability_ids', []),
                "source_gap": edit["source_gap"],
                "user_value": edit["user_value"],
                "product_fit": edit["product_fit"],
                "requires": edit["requires"],
                "produces": edit["produces"],
                "depends_on": edit["depends_on"],
                "dependency_evidence": edit["dependency_evidence"],
                "source_claims": edit["source_claims"],
                "new_values": edit["new_values"],
                "dependency_reason": edit["dependency_reason"],
                "preserve": edit["preserve"],
                "acceptance": edit["acceptance"],
                "instruction_validation": {
                    "status": "ok",
                    "method": "structure_and_semantic_review" if sequence.get('instruction_review') else "single_planner_output_plus_host_quote_dependency_order_and_leakage_checks",
                    "independent_llm_audit": sequence.get('instruction_review', {}).get('sequence_decision') == 'accept',
                },
                "sequence_decision": "accepted_by_structure_and_semantic_review" if sequence.get('instruction_review') else "accepted_by_deterministic_checks",
                **({'instruction_review': sequence['instruction_review']} if sequence.get('instruction_review') else {}),
                "retrieval": sequence["retrieval"],
                "seed_browser_warnings": {
                    "remote_requests": browser["remote_requests"],
                    "console_errors": browser["console_errors"],
                    "page_errors": browser["page_errors"],
                    "horizontal_overflow": browser["horizontal_overflow"],
                },
                "target_status": "not_generated",
                "training_admission": {
                    "status": "not_eligible",
                    "reason": "target_ground_truth_not_generated",
                },
            },
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument(
        "--sampled-seeds", type=Path, help="Defaults to RUN_DIR/sampled_seeds.jsonl"
    )
    parser.add_argument(
        "--embedded-capability-pool",
        type=Path,
        help="Optional precomputed vectors; otherwise embed the current inspiration pool.",
    )
    parser.add_argument('--capability-pool', type=Path, default=Path(
        '/data2/adminweihunj/webcoding/inspiration_library/current/capability_pool.jsonl'))
    parser.add_argument('--embedding-dir', type=Path, help='Immutable vector cache; defaults to RUN_DIR/pool')
    parser.add_argument('--max-pool-cards', type=int, default=200)
    parser.add_argument('--max-embedding-requests', type=int, default=20)
    parser.add_argument('--api-timeout-seconds', type=float, default=120)
    parser.add_argument('--revision-candidate', type=Path)
    parser.add_argument('--revision-feedback', type=Path)
    parser.add_argument('--candidate-response', type=Path, help='Run structural checks on a saved candidate without regenerating or calling a reviewer')
    parser.add_argument('--length-seed', type=int, help='Reproducible random chain-length seed')
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--max-per-family", type=int, default=2)
    parser.add_argument(
        "--edit-count",
        type=parse_edit_count_argument,
        default="random",
        help=(
            f"Default random uniformly draws {MIN_EDIT_COUNT}..{MAX_EDIT_COUNT} per chain; "
            "use an integer for fixed count or auto for model-selected count."
        ),
    )
    parser.add_argument("--stage", choices=("retrieval", "full"), default="full")
    parser.add_argument(
        "--exploration-rounds",
        type=int,
        default=2,
        help=(
            "LLM exploration rounds after two browser-generated rounds (default: 2); "
            "round two is skipped when round one finds no new state or control."
        ),
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--seed-id",
        help="Run exactly one matching Seed from sampled-seeds; useful for bounded debugging.",
    )
    parser.add_argument(
        "--evidence-run-dir",
        type=Path,
        action="append",
        default=[],
        help="Reuse immutable browser exploration and Top-K retrieval from a prior compatible run; repeatable.",
    )
    parser.add_argument("--expected-total", type=int, default=10)
    args = parser.parse_args()
    key = os.environ.get("DOC_API_KEY")
    if not key:
        raise ValueError("DOC_API_KEY is required")
    sampled_path = args.sampled_seeds or args.run_dir / "sampled_seeds.jsonl"
    seeds = list(read_jsonl(sampled_path))
    if len(seeds) != args.expected_total:
        raise ValueError(
            f"sampled Seed count {len(seeds)} does not equal expected {args.expected_total}"
        )
    if not 1 <= args.limit <= len(seeds):
        raise ValueError("limit is outside sampled Seed range")
    selected_seeds = seeds[: args.limit]
    if args.seed_id:
        selected_seeds = [
            seed for seed in seeds if str(seed.get("seed_id")) == args.seed_id
        ]
        if len(selected_seeds) != 1:
            raise ValueError("seed-id must match exactly one sampled Seed")
    requested_count = len(selected_seeds)
    if bool(args.revision_candidate) != bool(args.revision_feedback) or (args.revision_candidate and requested_count != 1):
        raise ValueError('revision requires one selected seed plus candidate and feedback files')
    if args.candidate_response and (args.revision_candidate or requested_count != 1):
        raise ValueError('candidate replay requires one seed and excludes revision')
    prior_candidate = args.candidate_response or args.revision_candidate
    preserved_count = len(load_json_response(prior_candidate)['edits']) if prior_candidate else None
    if preserved_count is not None and isinstance(args.edit_count, int) and args.edit_count != preserved_count:
        raise ValueError('candidate replay/revision must preserve its chain length')
    edit_counts = select_edit_counts(seed_ids=[str(seed['seed_id']) for seed in selected_seeds],
        requested=args.edit_count, run_dir=args.run_dir, length_seed=args.length_seed,
        preserved_count=preserved_count)
    write_json_once(args.run_dir / 'run_identity.json', {
        'workflow':'retrieve-before-plan-instruction-only-v4',
        'seed_sha256':sha256(json.dumps(selected_seeds, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        'pool_sha256':sha256((args.embedded_capability_pool or args.capability_pool).read_bytes()).hexdigest(),
        'edit_count':args.edit_count, 'top_k':args.top_k, 'max_per_family':args.max_per_family,
        'resolved_edit_counts':edit_counts,
        'chat_model':os.environ.get('DOC_API_CHAT_MODEL', 'qwen3.8-max'),
        'revision_candidate_sha256':sha256(args.revision_candidate.read_bytes()).hexdigest() if args.revision_candidate else None,
        'candidate_response_sha256':sha256(args.candidate_response.read_bytes()).hexdigest() if args.candidate_response else None,
        'revision_feedback_sha256':sha256(args.revision_feedback.read_bytes()).hexdigest() if args.revision_feedback else None,
        'code_sha256':sha256(b''.join(path.read_bytes() for path in [Path(__file__),
            PROJECT_ROOT/'inspiration_library/one_shot_capability_retrieval.py',
            PROJECT_ROOT/'inspiration_library/linear_edit_queries.py'])).hexdigest(),
    })
    if not 1 <= args.top_k <= 20:
        raise ValueError("top-k must be from 1 to 20")
    if not 1 <= args.max_per_family <= args.top_k:
        raise ValueError("max-per-family must be from 1 to top-k")
    if not 0 <= args.exploration_rounds <= 2:
        raise ValueError("exploration-rounds must be from 0 to 2")
    if args.api_timeout_seconds <= 0:
        raise ValueError('API timeout must be positive')
    retrieval_results = args.run_dir / "retrieval_results.jsonl"
    generation_results = args.run_dir / "generation_results.jsonl"
    query_records = args.run_dir / "edit_queries.jsonl"
    generated_done = successful_ids(generation_results, "seed_id")
    retrieved_done = successful_ids(retrieval_results, "seed_id")
    chat_base_url = os.environ.get("DOC_API_BASE_URL")
    embedding_base_url = os.environ.get("DOC_EMBEDDING_BASE_URL")
    embedding_key = os.environ.get("DOC_EMBEDDING_API_KEY")
    if (
        chat_base_url
        and urlsplit(chat_base_url).hostname in {"api.deepseek.com", "api.tokenwave.us"}
        and (not embedding_base_url or not embedding_key)
    ):
        raise ValueError(
            "This chat provider requires DOC_EMBEDDING_BASE_URL and DOC_EMBEDDING_API_KEY "
            "for the separate embedding provider"
        )
    embedding_base_url = embedding_base_url or chat_base_url or DEFAULT_BASE_URL
    embedding_key = embedding_key or key
    with DocApiClient(
        api_key=key,
        log_dir=args.run_dir / "provider",
        base_url=chat_base_url,
        timeout_seconds=args.api_timeout_seconds,
    ) as client, DocApiClient(
        api_key=embedding_key,
        log_dir=args.run_dir / "provider_embeddings",
        base_url=embedding_base_url,
        timeout_seconds=args.api_timeout_seconds,
    ) as embedding_client:
        if args.embedded_capability_pool is None:
            from inspiration_library.utils.embed_capability_pool import embed_pool
            embedding_dir = args.embedding_dir or args.run_dir / 'pool'
            embedded_pool = embed_pool(pool_path=args.capability_pool, run_dir=embedding_dir,
                client=embedding_client, max_cards=args.max_pool_cards,
                max_requests=args.max_embedding_requests)
            args.embedded_capability_pool = embedding_dir / 'embedded_capability_pool.jsonl'
        else:
            embedded_pool = list(read_jsonl(args.embedded_capability_pool))
        if not embedded_pool or any(not row.get('embedding') for row in embedded_pool):
            raise ValueError('embedded capability pool is empty or contains a card without an embedding')
        for index, seed in enumerate(selected_seeds, 1):
            edit_count = edit_counts[str(seed['seed_id'])]
            print(f"[{index}/{requested_count}] chain_length={edit_count if edit_count is not None else 'auto'} seed={seed['seed_id']}", flush=True)
            print(f"[{index}/{requested_count}] observe {seed['seed_id']}", flush=True)
            observation = load_or_observe(
                seed,
                args.run_dir,
                client=client,
                exploration_rounds=args.exploration_rounds,
                evidence_run_dirs=tuple(args.evidence_run_dir),
            )
            print(f"[{index}/{requested_count}] retrieve Top-{args.top_k} {seed['seed_id']}", flush=True)
            try:
                retrieval = load_or_retrieve(
                    seed=seed,
                    observation=observation,
                    embedded_pool=embedded_pool,
                    top_k=args.top_k,
                    max_per_family=args.max_per_family,
                    run_dir=args.run_dir,
                    query_client=client,
                    embedding_client=embedding_client,
                    evidence_run_dirs=tuple(args.evidence_run_dir),
                    edit_count=edit_count,
                )
            except Exception as exc:
                if seed["seed_id"] not in retrieved_done:
                    append_jsonl(
                        retrieval_results,
                        {
                            "seed_id": seed["seed_id"],
                            "status": "error",
                            "error": f"{type(exc).__name__}: {exc}",
                        },
                    )
                raise
            if seed["seed_id"] not in retrieved_done:
                append_jsonl(
                    retrieval_results,
                    {
                        "seed_id": seed["seed_id"],
                        "status": "ok",
                        "top_k": retrieval["top_k"],
                        "max_per_family": retrieval["max_per_family"],
                        "retrieved_capability_ids": retrieval["retrieved_capability_ids"],
                    },
                )
            if args.stage == "retrieval":
                continue
            print(
                f"[{index}/{requested_count}] generate {seed['seed_id']} "
                f"browser_status={observation.get('status')}",
                flush=True,
            )
            try:
                sequence = load_or_generate(
                    seed=seed,
                    observation=observation,
                    retrieval=retrieval,
                    run_dir=args.run_dir,
                    client=client,
                    edit_count=edit_count,
                    revision_candidate=args.revision_candidate,
                    revision_feedback=args.revision_feedback.read_text() if args.revision_feedback else None,
                    candidate_response=args.candidate_response,
                )
            except Exception as exc:
                if seed["seed_id"] not in generated_done:
                    append_jsonl(
                        generation_results,
                        {
                            "seed_id": seed["seed_id"],
                            "status": "error",
                            "error": f"{type(exc).__name__}: {exc}",
                        },
                    )
                raise
            if seed["seed_id"] not in generated_done:
                append_jsonl(
                    generation_results,
                    {
                        "seed_id": seed["seed_id"],
                        "status": "ok",
                        "edit_count": sequence["edit_count"],
                        "dependent_edit_count": sequence["dependent_edit_count"],
                        "independent_later_edit_count": sequence[
                            "independent_later_edit_count"
                        ],
                        "browser_status": observation.get("status"),
                        "retrieval_query_sha256": retrieval["retrieval_query_sha256"],
                        "retrieved_capability_ids": retrieval["retrieved_capability_ids"],
                    },
                )
            export_queries(
                seed=seed,
                observation=observation,
                sequence=sequence,
                output_path=query_records,
            )
    if args.stage == "retrieval":
        completed_retrievals = successful_ids(retrieval_results, "seed_id")
        append_jsonl(
            args.run_dir / "progress_snapshots.jsonl",
            {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "status": "ok",
                "stage": "retrieval",
                "requested_limit": requested_count,
                "completed_seed_count": len(completed_retrievals),
            },
        )
        print(
            json.dumps(
                {
                    "status": "ok",
                    "stage": "retrieval",
                    "completed_seed_count": len(completed_retrievals),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return 0
    completed = successful_ids(generation_results, "seed_id")
    append_jsonl(
        args.run_dir / "progress_snapshots.jsonl",
        {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "ok",
            "requested_limit": requested_count,
            "completed_seed_count": len(completed),
            "query_record_count": sum(1 for _ in read_jsonl(query_records)),
        },
    )
    if len(completed) == args.expected_total:
        query_rows = list(read_jsonl(query_records))
        usage_rows = list(read_jsonl(args.run_dir / "provider" / "usage.jsonl"))
        write_json_once(
            args.run_dir / "run_manifest.json",
            {
                "schema_version": "webcoding-linear-edit-query-run-v2",
                "status": "ok",
                "seed_count": args.expected_total,
                "edit_query_count": len(query_rows),
                "accepted_edit_query_count": sum(row["status"] == "ok" for row in query_rows),
                "rejected_edit_query_count": 0,
                "accepted_sequence_count": len(completed),
                "independent_llm_audit": False,
                "dependent_edit_count": sum(bool(row["depends_on"]) for row in query_rows),
                "independent_edit_count": sum(not row["depends_on"] for row in query_rows),
                "seed_browser_ok_count": sum(
                    json.loads(
                        (
                            args.run_dir
                            / "browser"
                            / seed["seed_id"]
                            / "observation.json"
                        ).read_text(encoding="utf-8")
                    ).get("status")
                    == "ok"
                    for seed in seeds
                ),
                "provider_request_count": len(usage_rows),
                "provider_error_count": sum(row.get("status") != "ok" for row in usage_rows),
                "sdk_retries": 0,
                "outer_retries": 0,
                "target_status": "not_generated",
                "training_admission": "not_eligible",
                "retrieval": {
                    "strategy": "embedding_top_k_once_per_seed",
                    "top_k": args.top_k,
                    "max_per_family": args.max_per_family,
                    "pool_path": str(args.embedded_capability_pool.resolve()),
                    "pool_card_count": len(embedded_pool),
                    "pool_snapshot_sha256": pool_snapshot_sha256(embedded_pool),
                    "source_slice_policy": "exact_framework_independent_project_source_slices_only",
                },
                "files": {
                    "candidate_seeds": str((args.run_dir / "candidate_seeds.jsonl").resolve()),
                    "sampled_seeds": str(sampled_path.resolve()),
                    "edit_queries": str(query_records.resolve()),
                    "retrievals": str((args.run_dir / "retrievals").resolve()),
                },
            },
        )
    print(
        json.dumps(
            {
                "status": "ok",
                "completed_seed_count": len(completed),
                "query_record_count": sum(1 for _ in read_jsonl(query_records)),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
