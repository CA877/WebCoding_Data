#!/usr/bin/env python3
"""Resolve selected Edit mother manifests to exact source-code bundles."""

import argparse
import collections
import gzip
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from reverse.inventory_multihtml_edit_mothers import digest_code, html_paths, read_project, stack

RELEASE_ORDER = ("0921", "0905", "0805supplement", "0805")


def read_rows(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def row_code(row: dict):
    instruction = row.get("instruction")
    for value in (
        row.get("response"),
        instruction.get("src_code") if isinstance(instruction, dict) else None,
        row.get("source_code"),
    ):
        if isinstance(value, dict):
            value = value.get("files")
        if isinstance(value, list) and value and all(
            isinstance(item, dict) and "path" in item and "code" in item for item in value
        ):
            return [{"path": item["path"], "code": item["code"]} for item in value]
    return None


def validate(code: list[dict], manifest: dict) -> None:
    if digest_code(code) != manifest["candidate_id"]:
        raise ValueError("source-code hash mismatch")
    if stack(code) != manifest["stack"]:
        raise ValueError("source stack mismatch")
    if len(html_paths(code)) != manifest["html_count"]:
        raise ValueError("source HTML count mismatch")


def resolved_record(item: dict, code: list[dict], **fields) -> dict:
    return {
        "candidate_id": item["candidate_id"],
        "stack": item["stack"],
        "html_count": item["html_count"],
        "html_paths": item.get("html_paths", html_paths(code)),
        "source_extensions": sorted({Path(entry["path"]).suffix.lower() for entry in code}),
        "code_chars": item.get("code_chars"),
        "file_count": item.get("file_count"),
        "origins": item.get("origins", []),
        "sources": item.get("sources", []),
        "lineages": item.get("lineages", []),
        "source_code": code,
        **fields,
    }


def container_rank(path: Path):
    value = str(path)
    for index, release in enumerate(RELEASE_ORDER):
        if f"/releases/{release}/text-generate/" in value:
            return (index, value)
    return (len(RELEASE_ORDER), value)


def resolve(assignments: list[dict], *, allow_physical: bool = True):
    targets = {}
    for item in assignments:
        targets.setdefault(item["candidate_id"], item)
    resolved = {}
    resolution_counts = collections.Counter()

    if allow_physical:
        for candidate_id, item in targets.items():
            for raw in item.get("origins", []):
                root = Path(raw)
                if not root.is_dir():
                    continue
                code = read_project(root)
                if code and digest_code(code) == candidate_id:
                    validate(code, item)
                    resolved[candidate_id] = resolved_record(
                        item,
                        code,
                        origin=str(root),
                        container=None,
                        source="physical_project",
                    )
                    resolution_counts["physical_project"] += 1
                    break

    containers = collections.defaultdict(set)
    for candidate_id, item in targets.items():
        if candidate_id in resolved:
            continue
        for lineage in item.get("lineages", []):
            raw = lineage.get("container")
            if raw:
                containers[Path(raw)].add(candidate_id)

    for container in sorted(containers, key=container_rank):
        wanted = containers[container] - resolved.keys()
        if not wanted or not container.is_file():
            continue
        for row in read_rows(container):
            code = row_code(row)
            if not code:
                continue
            candidate_id = digest_code(code)
            if candidate_id not in wanted:
                continue
            item = targets[candidate_id]
            validate(code, item)
            resolved[candidate_id] = resolved_record(
                item,
                code,
                origin=(row.get("metadata") or {}).get("source_project") or row.get("instance_id"),
                source_instance_id=row.get("instance_id"),
                resources=row.get("resources", []),
                container=str(container),
                source="dataset_row",
            )
            resolution_counts[str(container)] += 1
            if wanted <= resolved.keys():
                break

    missing = sorted(targets.keys() - resolved.keys())
    return resolved, resolution_counts, missing


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assignments", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--dataset-lineages-only", action="store_true")
    args = parser.parse_args()
    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    args.output_dir.mkdir(parents=True)
    assignments = list(read_rows(args.assignments))
    resolved, counts, missing = resolve(assignments, allow_physical=not args.dataset_lineages_only)
    with gzip.open(args.output_dir / "resolved_mothers.jsonl.gz", "wt", encoding="utf-8", compresslevel=1) as stream:
        for candidate_id in sorted(resolved):
            stream.write(json.dumps(resolved[candidate_id], ensure_ascii=False) + "\n")
    summary = {
        "status": "complete" if not missing else "incomplete",
        "assignment_count": len(assignments),
        "requested_unique_mothers": len({item["candidate_id"] for item in assignments}),
        "resolved_unique_mothers": len(resolved),
        "resolution_counts": dict(counts),
        "missing_candidate_ids": missing,
    }
    (args.output_dir / "resolution_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(summary, ensure_ascii=False))
    if missing:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
