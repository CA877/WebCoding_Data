#!/usr/bin/env python3
"""Audit recent Pipeline C/D outputs with exact Qwen token counting and deduplication."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path

from preprocess.pipeline_c.qwen_token_gate import count_project_tokens


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    records = []
    for run in sorted((args.root / "runs").glob("pipeline_[cd]*20260724*")):
        manifests = list(run.glob("output/*manifest.jsonl"))
        if not manifests:
            continue
        is_d = run.name.startswith("pipeline_d_")
        for line in manifests[0].open(encoding="utf-8", errors="ignore"):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("status") != "pass" or not row.get("source_url"):
                continue
            project = run / "output" / "projects" / str(row.get("project_id"))
            if project.is_dir() and (project / "index.html").is_file():
                records.append((str(row["source_url"]), run.name, project, is_d))

    chosen = {}
    for record in records:
        url = record[0]
        if url not in chosen or (chosen[url][3] and not record[3]):
            chosen[url] = record

    counts = collections.Counter()
    eligible = []
    for index, record in enumerate(chosen.values(), 1):
        url, run_name, project, is_d = record
        try:
            tokens = count_project_tokens(project, args.tokenizer)
        except Exception:
            counts["token_failures"] += 1
            continue
        source = "d" if is_d else "c"
        counts[f"checked_{source}"] += 1
        if tokens <= 40_000:
            counts[f"eligible_{source}"] += 1
            eligible.append((url, run_name, project, tokens))
        else:
            counts[f"over_40k_{source}"] += 1
        if index % 100 == 0:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps({"progress": index, "counts": counts}, indent=2), encoding="utf-8")

    html_hashes = {hashlib.sha256((project / "index.html").read_bytes()).hexdigest()
                   for _, _, project, _ in eligible}
    result = {
        "manifest_pass_records": len(records),
        "unique_source_urls_with_project": len(chosen),
        "counts": dict(counts),
        "eligible_url_dedup": len(eligible),
        "eligible_html_hash_dedup": len(html_hashes),
        "eligible_by_run": dict(collections.Counter(run for _, run, _, _ in eligible)),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
