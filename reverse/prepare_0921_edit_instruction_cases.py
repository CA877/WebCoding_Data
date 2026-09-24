#!/usr/bin/env python3
"""Pair removed 0921 Edit identities/types with the replacement mother pool."""
from __future__ import annotations

import argparse
import collections
import gzip
import json
from pathlib import Path


def rows(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--removed-records", type=Path, required=True)
    parser.add_argument("--assignments", type=Path, required=True)
    parser.add_argument("--resolved-mothers", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    removed = list(rows(args.removed_records))
    assignments = list(rows(args.assignments))
    resolved = {item["candidate_id"]: item for item in rows(args.resolved_mothers)}
    if len(removed) != len(assignments):
        raise ValueError("removed-record and replacement-assignment counts differ")

    args.output_dir.mkdir(parents=True)
    task_counts = collections.Counter()
    html_counts = collections.Counter()
    type_sets_by_mother: dict[str, set[tuple[str, ...]]] = collections.defaultdict(set)
    manifest = []
    for old, assignment in zip(removed, assignments):
        instance_id = old.get("instance_id")
        task_types = old.get("task_type") or []
        candidate_id = assignment["candidate_id"]
        mother = resolved.get(candidate_id)
        if not instance_id or not 4 <= len(task_types) <= 12:
            raise ValueError(f"invalid removed Edit identity/types: {instance_id}")
        if len(set(task_types)) != len(task_types):
            raise ValueError(f"duplicate task types: {instance_id}")
        if mother is None:
            raise ValueError(f"unresolved replacement mother: {candidate_id}")
        if mother.get("html_count") != assignment.get("html_count"):
            raise ValueError(f"HTML count mismatch: {candidate_id}")
        ordered_types = tuple(task_types)
        if ordered_types in type_sets_by_mother[candidate_id]:
            raise ValueError(f"reused mother has duplicate task-type set: {candidate_id}")
        type_sets_by_mother[candidate_id].add(ordered_types)

        case = {
            "instance_id": instance_id,
            "task_types": task_types,
            "source_code": mother["source_code"],
            "replacement_mother": {
                "slot_id": assignment["slot_id"],
                "candidate_id": candidate_id,
                "reuse_index": assignment["reuse_index"],
                "html_count": assignment["html_count"],
                "html_paths": assignment["html_paths"],
                "source_extensions": assignment["source_extensions"],
                "source_instance_id": mother.get("source_instance_id"),
                "container": mother.get("container"),
            },
        }
        path = args.output_dir / f"{instance_id}.json.gz"
        with gzip.open(path, "wt", encoding="utf-8", compresslevel=1) as stream:
            json.dump(case, stream, ensure_ascii=False)
        task_counts[len(task_types)] += 1
        html_counts[assignment["html_count"]] += 1
        manifest.append({
            "instance_id": instance_id,
            "case": path.name,
            "candidate_id": candidate_id,
            "reuse_index": assignment["reuse_index"],
            "task_count": len(task_types),
            "html_count": assignment["html_count"],
        })

    with (args.output_dir.parent / "case_manifest.jsonl").open("w", encoding="utf-8") as stream:
        for item in manifest:
            stream.write(json.dumps(item, ensure_ascii=False) + "\n")
    summary = {
        "status": "complete",
        "case_count": len(manifest),
        "unique_instance_ids": len({item["instance_id"] for item in manifest}),
        "unique_mothers": len(type_sets_by_mother),
        "task_count_distribution": dict(sorted(task_counts.items())),
        "html_count_distribution": dict(sorted(html_counts.items())),
        "duplicate_type_sets_per_mother": 0,
    }
    (args.output_dir.parent / "case_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
