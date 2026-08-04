#!/usr/bin/env python3
"""Read-only triage of legacy ``output_full`` projects for a new rescue run.

The legacy directory contains historical duplicates and failed remnants.  This
tool consumes only ``status=ok`` rows from ``pipeline_b_results.jsonl`` and
emits one JSONL row per manifest-declared output; it neither edits nor copies a
project.  Rendering and tokenizer gates deliberately happen in a later stage.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from preprocess.pipeline_c.policy import assess_html

CODE_SUFFIXES = {".html", ".htm", ".css", ".js", ".jsx", ".ts", ".tsx"}
MINIFIED_LINE_RATIO = 0.9
LEGACY_PICSUM_RE = re.compile(r"(?:https?:)?//(?:picsum\.photos|images\.picsum\.photos)/", re.I)


def _candidate_rows(manifest: Path, root: Path) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    candidates: list[dict] = []
    for line in manifest.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("status") != "ok":
            continue
        for output in row.get("outputs", []):
            raw_path = output.get("path", "")
            project = (root.parent / raw_path).resolve()
            key = (row.get("url", ""), str(project))
            if not raw_path or key in seen:
                continue
            seen.add(key)
            candidates.append({
                "source_url": row.get("url"), "project": str(project),
                "variant": output.get("variant"), "crawl_language": row.get("crawl_result", {}).get("lang"),
            })
    return candidates


def _all_project_rows(root: Path, manifest: Path, include_unmanifested: bool) -> list[dict]:
    """Return every project directory, not merely historical ``status=ok`` rows.

    The old manifest is useful provenance but its ``ok`` label is not a quality
    verdict.  Rescue must therefore be able to audit the complete on-disk
    corpus, including projects which the historical pipeline mislabelled.
    """
    rows = _candidate_rows(manifest, root)
    known = {str(Path(row["project"]).resolve()) for row in rows}
    if not include_unmanifested:
        return rows
    for variant in ("single", "multi"):
        directory = root / f"{variant}_page"
        if not directory.is_dir():
            continue
        for project in directory.iterdir():
            if not project.is_dir():
                continue
            resolved = str(project.resolve())
            if resolved in known:
                continue
            rows.append({"source_url": None, "project": resolved, "variant": variant,
                         "crawl_language": None, "manifest_status": "unmanifested"})
            known.add(resolved)
    return rows


def _js_stats(project: Path) -> tuple[int, int, int]:
    files = list(project.rglob("*.js"))
    total_bytes = minified_bytes = 0
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        size = len(text.encode("utf-8", errors="replace")); total_bytes += size
        longest = max((len(line) for line in text.splitlines()), default=0)
        if size and longest / size >= MINIFIED_LINE_RATIO:
            minified_bytes += size
    return len(files), total_bytes, minified_bytes


def audit(candidate: dict) -> dict:
    project = Path(candidate["project"])
    index = project / "index.html"
    result = {**candidate, "status": "review"}
    if not index.is_file():
        return {**result, "status": "reject_static", "reasons": ["missing_index"]}
    try:
        html = index.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {**result, "status": "reject_static", "reasons": [f"read_error:{type(exc).__name__}"]}
    assessment = assess_html(html)
    has_legacy_picsum = False
    for asset in project.rglob("*"):
        if not asset.is_file() or asset.suffix.lower() not in {".html", ".htm", ".css"}:
            continue
        try:
            if LEGACY_PICSUM_RE.search(asset.read_text(encoding="utf-8", errors="replace")):
                has_legacy_picsum = True
                break
        except OSError:
            continue
    code_files = [p for p in project.rglob("*") if p.is_file() and p.suffix.lower() in CODE_SUFFIXES]
    code_bytes = sum(p.stat().st_size for p in code_files)
    js_files, js_bytes, minified_js_bytes = _js_stats(project)
    soup = BeautifulSoup(html, "html.parser")
    reasons = list(assessment.reasons)
    if len(html) > 500_000:
        reasons.append("html_over_500kb")
    if code_bytes > 1_500_000:
        reasons.append("code_over_1_5mb")
    if js_bytes and minified_js_bytes / js_bytes > 0.8:
        reasons.append("mostly_minified_js")
    return {
        **result,
        "status": "candidate_static" if not assessment.reasons else "reject_static",
        "reasons": reasons,
        "language": assessment.language,
        "html_bytes": len(html.encode("utf-8")),
        "text_chars": assessment.text_chars,
        "html_pages": len(list(project.glob("*.html"))),
        "code_bytes": code_bytes,
        "code_files": len(code_files),
        "js_files": js_files,
        "js_bytes": js_bytes,
        "minified_js_bytes": minified_js_bytes,
        "html_script_tags": len(soup.find_all("script")),
        "html_style_tags": len(soup.find_all("style")),
        "has_legacy_picsum": has_legacy_picsum,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only audit of legacy output_full manifest candidates.")
    parser.add_argument("--root", type=Path, required=True, help=".../output_full")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--include-unmanifested", action="store_true",
                        help="Audit every directory under single_page/multi_page, not only old manifest ok rows.")
    args = parser.parse_args()
    rows = _all_project_rows(args.root, args.manifest, args.include_unmanifested)[args.offset:]
    if args.limit:
        rows = rows[:args.limit]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    with args.output.open("w", encoding="utf-8") as handle:
        # ``executor.map`` preserves input order, keeping this resumable and
        # making the output deterministic while up to N projects are inspected
        # concurrently.  Each worker only reads the legacy tree.
        with ProcessPoolExecutor(max_workers=max(1, args.workers)) as executor:
            results = executor.map(audit, rows, chunksize=16)
            for number, result in enumerate(results, 1):
                counts[result["status"]] += 1
                handle.write(json.dumps(result, ensure_ascii=False) + "\n")
                if number % 100 == 0 or number == len(rows):
                    print(f"[{number}/{len(rows)}] {dict(counts)}", flush=True)
    print(json.dumps({"candidates": len(rows), "status_counts": counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
