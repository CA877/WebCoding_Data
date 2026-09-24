#!/usr/bin/env python3
"""Inventory real multi-HTML Edit mother candidates without changing a release."""

import argparse
import collections
import gzip
import hashlib
import json
from pathlib import Path
import re


TEXT_EXTENSIONS = {
    ".html", ".htm", ".css", ".js", ".jsx", ".ts", ".tsx", ".vue",
    ".json", ".svg", ".md", ".txt", ".mjs", ".cjs", ".scss", ".sass", ".less",
}
SKIP_DIRS = {
    ".git", "node_modules", "dist", "build", ".next", "coverage", ".venv", "venv",
    "__pycache__", ".cache",
}
TARGETS = {"vanilla": 1305, "react": 1305, "vue": 1304}


def stack(code: list[dict]) -> str:
    evidence = set()
    unknown = False
    for item in code:
        name = str(item.get("path", "")).lower()
        text = str(item.get("code", ""))
        if name.endswith("package.json"):
            try:
                package = json.loads(text)
                dependencies = {
                    **(package.get("dependencies") or {}),
                    **(package.get("devDependencies") or {}),
                }
                if "react" in dependencies or "react-dom" in dependencies:
                    evidence.add("react")
                if "vue" in dependencies:
                    evidence.add("vue")
            except (TypeError, ValueError):
                unknown = True
        if name.endswith(".vue"):
            evidence.add("vue")
        if re.search(r'''(?:from\s*|require\s*\(\s*|import\s*)["'](?:react|react-dom)(?:[/"'])''', text):
            evidence.add("react")
        if re.search(r'''(?:from\s*|require\s*\(\s*|import\s*)["']vue(?:[/"'])''', text):
            evidence.add("vue")
        if name.endswith((".jsx", ".tsx")) and not evidence:
            unknown = True
    if len(evidence) == 1:
        return next(iter(evidence))
    if evidence:
        return "mixed"
    return "unknown" if unknown else "vanilla"


def digest_code(code: list[dict]) -> str:
    normalized = sorted(
        ({"path": str(item["path"]), "code": str(item["code"])} for item in code),
        key=lambda item: item["path"],
    )
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def valid_code(code) -> bool:
    if not isinstance(code, list) or not code:
        return False
    paths = []
    for item in code:
        if not isinstance(item, dict) or "path" not in item or "code" not in item:
            return False
        path = Path(str(item["path"]))
        if path.is_absolute() or ".." in path.parts:
            return False
        paths.append(path.as_posix())
    return len(paths) == len(set(paths))


def html_paths(code: list[dict]) -> list[str]:
    return sorted(
        str(item["path"])
        for item in code
        if str(item.get("path", "")).lower().endswith((".html", ".htm"))
    )


def read_project(root: Path) -> list[dict]:
    code = []
    try:
        for path in sorted(root.rglob("*")):
            if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
                continue
            if not path.is_file() or path.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            code.append({"path": path.relative_to(root).as_posix(), "code": path.read_text(errors="replace")})
    except OSError:
        return []
    return code


def package_roots(path: Path):
    seen = set()
    with path.open() as stream:
        for line in stream:
            package = Path(line.strip())
            if not package.name == "package.json" or not package.is_file():
                continue
            root = package.parent.resolve()
            if root not in seen:
                seen.add(root)
                yield root


def manifest_roots(paths: list[Path]):
    seen = set()
    for path in paths:
        with path.open() as stream:
            for line in stream:
                row = json.loads(line)
                raw = row.get("project") or row.get("source_project") or row.get("path")
                if not raw:
                    continue
                root = Path(raw).resolve()
                if root.is_dir() and root not in seen:
                    seen.add(root)
                yield root


def framework_roots(path: Path):
    """Recover unpackaged projects from framework files and nearby physical HTML entries."""
    seen = set()
    with path.open() as stream:
        for line in stream:
            source = Path(line.strip())
            if not source.is_file():
                continue
            root = None
            for parent in source.parents:
                if (parent / "package.json").is_file():
                    root = None
                    break
                direct_html = [
                    child for child in parent.iterdir()
                    if child.is_file() and child.suffix.lower() in {".html", ".htm"}
                ]
                if len(direct_html) >= 2:
                    root = parent.resolve()
                    break
                if len(parent.parts) <= 5:
                    break
            if root is not None and root not in seen:
                seen.add(root)
                yield root


def add_candidate(candidates: dict, code, origin: str, source: str, max_chars: int, container: str = "") -> str:
    if not valid_code(code):
        return "invalid_code"
    pages = html_paths(code)
    if len(pages) < 2:
        return "single_html"
    kind = stack(code)
    if kind not in TARGETS:
        return "unsupported_stack"
    chars = sum(len(str(item["code"])) for item in code)
    if chars > max_chars:
        return "over_size"
    key = digest_code(code)
    item = candidates.setdefault(
        key,
        {
            "candidate_id": key,
            "stack": kind,
            "html_count": len(pages),
            "html_paths": pages,
            "code_chars": chars,
            "file_count": len(code),
            "origins": [],
            "sources": [],
            "lineages": [],
            "status": "static_candidate",
        },
    )
    if origin not in item["origins"]:
        item["origins"].append(origin)
    if source not in item["sources"]:
        item["sources"].append(source)
    lineage = {"source": source, "origin": origin}
    if container:
        lineage["container"] = container
    if lineage not in item["lineages"]:
        item["lineages"].append(lineage)
    return "candidate"


def read_gzip_rows(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def read_rows(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_jsonl(path: Path, rows) -> None:
    with path.open("w") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def current_inventory(edit_shard: Path):
    rows = list(read_gzip_rows(edit_shard))
    counts = collections.Counter()
    hashes = set()
    for row in rows:
        code = (row.get("instruction") or {}).get("src_code") or []
        if valid_code(code):
            counts[stack(code)] += 1
            hashes.add(digest_code(code))
    return rows, counts, hashes


def source_rank(item: dict):
    source_order = {
        "0921_text_generate": 0,
        "mother_manifest": 1,
        "physical_package_project": 2,
        "framework_file_project": 3,
        "historical_text_generate": 4,
    }
    return min(source_order.get(source, 9) for source in item["sources"])


def selection_rank(item: dict):
    html_count = item["html_count"]
    return (
        html_count != 4,
        source_rank(item),
        abs(html_count - 4),
        item["code_chars"],
        item["candidate_id"],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text-generate-shard", type=Path, required=True)
    parser.add_argument("--historical-text-generate-list", type=Path)
    parser.add_argument("--text-edit-shard", type=Path, required=True)
    parser.add_argument("--package-list", type=Path)
    parser.add_argument("--framework-file-list", type=Path)
    parser.add_argument("--mother-manifest", type=Path, action="append", default=[])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-chars", type=int, default=120000)
    parser.add_argument("--reserve-ratio", type=float, default=0.10)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    args.output_dir.mkdir(parents=True)

    current_rows, current_counts, current_hashes = current_inventory(args.text_edit_shard)
    deficits = {kind: max(0, TARGETS[kind] - current_counts[kind]) for kind in TARGETS}
    candidates = {}
    audit = collections.Counter()

    for row in read_gzip_rows(args.text_generate_shard):
        code = row.get("response")
        if isinstance(code, dict):
            code = code.get("files")
        origin = (row.get("metadata") or {}).get("source_project") or row.get("instance_id", "")
        audit[("0921_text_generate", add_candidate(candidates, code, str(origin), "0921_text_generate", args.max_chars, str(args.text_generate_shard)))] += 1

    if args.historical_text_generate_list:
        with args.historical_text_generate_list.open() as stream:
            historical_shards = [Path(line.strip()) for line in stream if line.strip()]
        for shard in historical_shards:
            if not shard.is_file() or shard.resolve() == args.text_generate_shard.resolve():
                continue
            try:
                for row in read_rows(shard):
                    code = row.get("response")
                    if isinstance(code, dict):
                        code = code.get("files")
                    origin = (row.get("metadata") or {}).get("source_project") or row.get("instance_id", "")
                    audit[("historical_text_generate", add_candidate(candidates, code, str(origin), "historical_text_generate", args.max_chars, str(shard)))] += 1
            except (OSError, UnicodeError, json.JSONDecodeError):
                audit[("historical_text_generate", "unreadable_shard")] += 1

    for root in manifest_roots(args.mother_manifest):
        audit[("mother_manifest", add_candidate(candidates, read_project(root), str(root), "mother_manifest", args.max_chars, ";".join(str(path) for path in args.mother_manifest)))] += 1

    if args.package_list:
        for index, root in enumerate(package_roots(args.package_list), 1):
            audit[("physical_package_project", add_candidate(candidates, read_project(root), str(root), "physical_package_project", args.max_chars))] += 1
            if index % 1000 == 0:
                print(json.dumps({"package_projects_scanned": index, "unique_candidates": len(candidates)}), flush=True)

    if args.framework_file_list:
        for root in framework_roots(args.framework_file_list):
            audit[("framework_file_project", add_candidate(candidates, read_project(root), str(root), "framework_file_project", args.max_chars))] += 1

    eligible = [item for key, item in candidates.items() if key not in current_hashes]
    selected = []
    reserve = []
    shortfall = {}
    for kind in TARGETS:
        pool = sorted((item for item in eligible if item["stack"] == kind), key=selection_rank)
        need = deficits[kind]
        reserve_need = int(need * args.reserve_ratio + 0.999999)
        selected.extend(pool[:need])
        reserve.extend(pool[need:need + reserve_need])
        shortfall[kind] = {
            "current": current_counts[kind],
            "target": TARGETS[kind],
            "needed": need,
            "eligible_unique": len(pool),
            "selected": min(need, len(pool)),
            "reserve_target": reserve_need,
            "reserve": min(reserve_need, max(0, len(pool) - need)),
            "selection_shortfall": max(0, need - len(pool)),
        }

    ordered = sorted(candidates.values(), key=lambda item: (item["stack"], selection_rank(item)))
    write_jsonl(args.output_dir / "candidate_manifest.jsonl", ordered)
    write_jsonl(args.output_dir / "selected_candidates.jsonl", selected)
    write_jsonl(args.output_dir / "reserve_candidates.jsonl", reserve)
    write_json(args.output_dir / "shortfall.json", shortfall)
    summary = {
        "status": "static_inventory_complete",
        "text_edit_rows": len(current_rows),
        "current_stack_counts": dict(current_counts),
        "targets": TARGETS,
        "deficits": deficits,
        "unique_candidates_including_current": len(candidates),
        "eligible_unique_candidates": len(eligible),
        "candidate_counts": dict(collections.Counter(item["stack"] for item in eligible)),
        "four_html_candidate_counts": dict(collections.Counter(item["stack"] for item in eligible if item["html_count"] == 4)),
        "selected_counts": dict(collections.Counter(item["stack"] for item in selected)),
        "reserve_counts": dict(collections.Counter(item["stack"] for item in reserve)),
        "audit": {f"{source}/{status}": count for (source, status), count in sorted(audit.items())},
    }
    write_json(args.output_dir / "pool_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
