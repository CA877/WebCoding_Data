#!/usr/bin/env python3
"""Stage a query-preserving 0921 Edit mother allocation without changing the release."""

import argparse
import collections
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from reverse.inventory_multihtml_edit_mothers import digest_code, html_paths, stack


SOURCE_ORDER = {
    "0921_text_generate": 0,
    "mother_manifest": 1,
    "physical_package_project": 2,
    "historical_text_generate": 3,
}
FORMAL_TEXT_GENERATE_RELEASES = ("0921", "0905", "0805supplement", "0805")
FRONTEND_EXTENSIONS = {".html", ".htm", ".css", ".js", ".mjs", ".cjs"}


def read_rows(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def source_rank(item: dict) -> int:
    return min((SOURCE_ORDER.get(value, 9) for value in item.get("sources", [])), default=9)


def candidate_rank(item: dict):
    lineages = item.get("lineages", [])
    release_rank = len(FORMAL_TEXT_GENERATE_RELEASES)
    for index, release in enumerate(FORMAL_TEXT_GENERATE_RELEASES):
        marker = f"/releases/{release}/text-generate/"
        if any(marker in str(lineage.get("container", "")) for lineage in lineages):
            release_rank = index
            break
    return (release_rank, source_rank(item), item.get("code_chars", 0), item["candidate_id"])


def formal_text_generate_lineages(item: dict) -> list[dict]:
    markers = tuple(f"/releases/{release}/text-generate/" for release in FORMAL_TEXT_GENERATE_RELEASES)
    return [
        lineage for lineage in item.get("lineages", [])
        if any(marker in str(lineage.get("container", "")) for marker in markers)
    ]


def plan_allocation(
    current_rows: list[dict],
    candidates: list[dict],
    *,
    target_total: int,
    target_sp: int,
    target_mp: int,
    preferred_stack: str,
    preferred_html_count: int,
    max_reuse: int,
    formal_text_generate_only: bool = False,
    frontend_only: bool = False,
):
    if target_sp + target_mp != target_total:
        raise ValueError("page targets must sum to the total")

    current_hashes = set()
    current_page_counts = collections.Counter()
    current_stack_counts = collections.Counter()
    preserved = []
    for row in current_rows:
        code = (row.get("instruction") or {}).get("src_code") or []
        pages = html_paths(code)
        if not pages:
            raise ValueError(f"source has no HTML: {row.get('instance_id')}")
        actual_page_type = "sp" if len(pages) == 1 else "mp"
        if row.get("page_type") != actual_page_type:
            raise ValueError(f"page_type mismatch: {row.get('instance_id')}")
        current_page_counts[actual_page_type] += 1
        kind = stack(code)
        current_stack_counts[kind] += 1
        code_hash = digest_code(code)
        current_hashes.add(code_hash)
        preserved.append(
            {
                "instance_id": row.get("instance_id"),
                "source_code_sha256": code_hash,
                "stack": kind,
                "html_count": len(pages),
                "instruction_status": (row.get("metadata") or {}).get("instruction_status"),
                "status": "preserved_existing_instruction",
            }
        )

    if len(current_rows) > target_total:
        raise ValueError("current release already exceeds target total")
    if current_page_counts["sp"] != target_sp:
        raise ValueError("preserving every current instruction does not satisfy the SP target")
    needed = target_mp - current_page_counts["mp"]
    if needed != target_total - len(current_rows) or needed < 0:
        raise ValueError("current rows and page targets do not have the same deficit")

    eligible_by_id = {}
    for item in candidates:
        candidate_id = item.get("candidate_id")
        allowed_lineages = formal_text_generate_lineages(item) if formal_text_generate_only else item.get("lineages", [])
        if (
            candidate_id
            and candidate_id not in current_hashes
            and item.get("stack") == preferred_stack
            and item.get("html_count", 0) >= 2
            and (allowed_lineages or not formal_text_generate_only)
            and (
                not frontend_only
                or set(item.get("source_extensions", [])) <= FRONTEND_EXTENSIONS
            )
        ):
            selected_item = dict(item)
            selected_item["lineages"] = allowed_lineages
            eligible_by_id.setdefault(candidate_id, selected_item)
    pool = list(eligible_by_id.values())
    exact_pool = sorted(
        (item for item in pool if item["html_count"] == preferred_html_count),
        key=candidate_rank,
    )
    fallback_pool = sorted(
        (item for item in pool if item["html_count"] != preferred_html_count),
        key=lambda item: (
            abs(item["html_count"] - preferred_html_count),
            -item["html_count"],
            candidate_rank(item),
        ),
    )
    if needed > len(pool) * max_reuse:
        raise ValueError("preferred mother pool cannot satisfy the requested allocation")

    assignments = []
    def append_pool(items, reuse_index):
        for item in items:
            if len(assignments) == needed:
                return
            slot_seed = f"{item['candidate_id']}:{reuse_index}".encode()
            assignments.append(
                {
                    "slot_id": hashlib.sha256(slot_seed).hexdigest(),
                    "candidate_id": item["candidate_id"],
                    "reuse_index": reuse_index,
                    "stack": item["stack"],
                    "html_count": item["html_count"],
                    "html_paths": item.get("html_paths", []),
                    "code_chars": item.get("code_chars"),
                    "file_count": item.get("file_count"),
                    "source_extensions": item.get("source_extensions", []),
                    "origins": item.get("origins", []),
                    "sources": item.get("sources", []),
                    "lineages": item.get("lineages", []),
                    "status": "awaiting_edit_instruction",
                }
            )

    # Match the official four-HTML shape as far as the reuse cap allows.
    for reuse_index in range(1, max_reuse + 1):
        append_pool(exact_pool, reuse_index)
        if len(assignments) == needed:
            break
    # Only then consume other existing multi-HTML Text Generate projects.
    for reuse_index in range(1, max_reuse + 1):
        append_pool(fallback_pool, reuse_index)
        if len(assignments) == needed:
            break

    use_counts = collections.Counter(item["candidate_id"] for item in assignments)
    projected_stack_counts = current_stack_counts + collections.Counter(
        item["stack"] for item in assignments
    )
    summary = {
        "status": "staged_not_applied",
        "policy": {
            "preserve_all_current_query_ready": True,
            "preferred_stack": preferred_stack,
            "preferred_html_count": preferred_html_count,
            "max_mother_reuse": max_reuse,
            "formal_text_generate_only": formal_text_generate_only,
            "frontend_only": frontend_only,
        },
        "preserved_existing": len(preserved),
        "preserved_query_ready": sum(item["instruction_status"] == "query_ready" for item in preserved),
        "new_assignments": len(assignments),
        "eligible_unique_mothers": len(pool),
        "eligible_exact_html_mothers": len(exact_pool),
        "selected_unique_mothers": len(use_counts),
        "mother_usage_distribution": dict(sorted(collections.Counter(use_counts.values()).items())),
        "assignment_reuse_index_counts": dict(
            sorted(collections.Counter(item["reuse_index"] for item in assignments).items())
        ),
        "assignment_html_count_counts": dict(
            sorted(collections.Counter(item["html_count"] for item in assignments).items())
        ),
        "projected_total": len(preserved) + len(assignments),
        "projected_page_counts": {
            "sp": current_page_counts["sp"],
            "mp": current_page_counts["mp"] + len(assignments),
        },
        "projected_stack_counts": dict(projected_stack_counts),
        "projected_instruction_status_counts": {
            "query_ready": sum(item["instruction_status"] == "query_ready" for item in preserved),
            "awaiting_query": len(assignments),
        },
    }
    return preserved, assignments, summary


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_jsonl(path: Path, rows) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-edit-shard", type=Path, required=True)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target-total", type=int, default=3914)
    parser.add_argument("--target-sp", type=int, default=1957)
    parser.add_argument("--target-mp", type=int, default=1957)
    parser.add_argument("--preferred-stack", default="vanilla")
    parser.add_argument("--preferred-html-count", type=int, default=4)
    parser.add_argument("--max-reuse", type=int, default=4)
    parser.add_argument("--formal-text-generate-only", action="store_true")
    parser.add_argument("--frontend-only", action="store_true")
    args = parser.parse_args()
    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    args.output_dir.mkdir(parents=True)
    preserved, assignments, summary = plan_allocation(
        read_rows(args.current_edit_shard),
        read_rows(args.candidate_manifest),
        target_total=args.target_total,
        target_sp=args.target_sp,
        target_mp=args.target_mp,
        preferred_stack=args.preferred_stack,
        preferred_html_count=args.preferred_html_count,
        max_reuse=args.max_reuse,
        formal_text_generate_only=args.formal_text_generate_only,
        frontend_only=args.frontend_only,
    )
    write_jsonl(args.output_dir / "preserved_existing.jsonl", preserved)
    write_jsonl(args.output_dir / "new_mother_assignments.jsonl", assignments)
    write_json(args.output_dir / "allocation_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
