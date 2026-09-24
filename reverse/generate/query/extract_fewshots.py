#!/usr/bin/env python3
"""
Extract the exact, complete original query/description/PRD for the selected
Benchmark × Category few-shot cases.

Outputs:
  - fewshot_full_queries.json
  - fewshot_full_queries.md

Install:
  pip install datasets huggingface_hub requests

Vision2Web:
  Full prompt.txt / prd.md text lives inside the official archives, not only
  the small parquet preview. Preferred:
      --vision2web-root /path/to/extracted/Vision2Web
  The root may contain frontend/<task>/prompt.txt and website/<task>/prd.md.

  Or allow this script to download the official frontend/website archives:
      --download-vision2web-archives
  These archives are large, so this is opt-in.
"""

from __future__ import annotations

import argparse
import json
import os
import tarfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import requests
from datasets import load_dataset
from huggingface_hub import hf_hub_download


HERE = Path(__file__).resolve().parent
DEFAULT_MANIFEST = HERE / "fewshots" / "fewshot_manifest.json"


def norm(v: Any) -> str:
    return str(v).strip()


def select_row(ds, selector: dict) -> dict:
    if "row_index" in selector:
        idx = int(selector["row_index"])
        if idx < 0 or idx >= len(ds):
            raise IndexError(f"row_index={idx}, dataset length={len(ds)}")
        return dict(ds[idx])

    field = selector["field"]
    target = norm(selector["value"])
    for row in ds:
        if field in row and norm(row[field]) == target:
            return dict(row)
    raise KeyError(f"Could not find {field}={target}")


def select_json_row(rows: list[dict], selector: dict) -> dict:
    if "row_index" in selector:
        return rows[int(selector["row_index"])]

    field = selector["field"]
    target = norm(selector["value"])
    for i, row in enumerate(rows):
        if field in row and norm(row[field]) == target:
            return row

    # Some JSON exports omit an explicit index field while preserving 1-based order.
    if field == "index":
        idx = int(selector["value"]) - 1
        if 0 <= idx < len(rows):
            return rows[idx]

    raise KeyError(f"Could not find {field}={target}")


def load_hf(repo: str, config: str | None, split: str):
    if config:
        return load_dataset(repo, config, split=split)
    return load_dataset(repo, split=split)


def webcompass_query(row: dict) -> tuple[str, Any]:
    """
    WebCompass editing stores a complete case as a list of description objects.
    Preserve the raw structure in JSON and create a lossless readable text form.
    """
    raw = row.get("description")
    if isinstance(raw, list):
        chunks = []
        for item in raw:
            if isinstance(item, dict):
                task_type = item.get("task_type")
                desc = item.get("description", "")
                if task_type:
                    chunks.append(f"[{task_type}]\n{desc}")
                else:
                    chunks.append(str(desc))
            else:
                chunks.append(str(item))
        return "\n\n".join(chunks), raw
    return str(raw), raw


def find_v2w_local(root: Path, subset: str, task_name: str, filename: str) -> Path | None:
    candidates = [
        root / subset / task_name / filename,
        root / "datasets" / subset / task_name / filename,
        root / task_name / filename,
    ]
    for p in candidates:
        if p.is_file():
            return p

    # Last resort: bounded recursive match.
    matches = list(root.glob(f"**/{subset}/{task_name}/{filename}"))
    if not matches:
        matches = list(root.glob(f"**/{task_name}/{filename}"))
    return matches[0] if matches else None


def read_text_from_tar(tar_path: Path, subset: str, task_name: str, filename: str) -> str:
    suffix = f"/{task_name}/{filename}"
    with tarfile.open(tar_path, "r:*") as tf:
        matches = [
            m for m in tf.getmembers()
            if m.isfile()
            and (m.name.endswith(suffix) or m.name == f"{task_name}/{filename}")
        ]
        if not matches:
            raise FileNotFoundError(
                f"{task_name}/{filename} not found inside {tar_path.name}"
            )
        f = tf.extractfile(matches[0])
        if f is None:
            raise RuntimeError(f"Could not extract {matches[0].name}")
        return f.read().decode("utf-8")


def resolve_v2w_task_name(entry: dict, cache: dict) -> str:
    sel = entry["selector"]
    if "task_name" in sel:
        return str(sel["task_name"])

    subset = entry["subset"]
    key = ("v2w_meta", subset)
    if key not in cache:
        # Official dataset metadata. The exact config/split layout may evolve,
        # so try the common forms in order.
        attempts = [
            lambda: load_dataset(entry["repo"], subset, split="test"),
            lambda: load_dataset(entry["repo"], split=subset),
            lambda: load_dataset(entry["repo"], subset, split="train"),
        ]
        last_err = None
        for fn in attempts:
            try:
                cache[key] = fn()
                break
            except Exception as e:
                last_err = e
        else:
            raise RuntimeError(
                f"Could not load Vision2Web metadata for subset={subset}"
            ) from last_err

    row = cache[key][int(sel["row_index"])]
    for k in ("task_name", "name", "id", "task_id"):
        if k in row and row[k]:
            return str(row[k])
    raise KeyError(
        f"Could not identify task name from Vision2Web {subset} metadata row. "
        f"Available keys: {list(row.keys())}"
    )


def get_v2w_text(entry: dict, args, cache: dict) -> tuple[str, str]:
    subset = entry["subset"]
    task_name = resolve_v2w_task_name(entry, cache)
    filename = entry["text_file"]

    if args.vision2web_root:
        p = find_v2w_local(Path(args.vision2web_root), subset, task_name, filename)
        if p:
            return p.read_text(encoding="utf-8"), task_name

    if args.download_vision2web_archives:
        key = ("v2w_tar", subset)
        if key not in cache:
            archive_name = f"archives/{subset}.tar.gz"
            cache[key] = Path(
                hf_hub_download(
                    repo_id=entry["repo"],
                    repo_type="dataset",
                    filename=archive_name,
                )
            )
        text = read_text_from_tar(cache[key], subset, task_name, filename)
        return text, task_name

    raise RuntimeError(
        f"Vision2Web {subset}/{task_name}/{filename} requires the full official "
        "archive. Pass --vision2web-root PATH, or opt in to "
        "--download-vision2web-archives."
    )


def case_id(entry: dict, row: dict | None = None, resolved_task_name: str | None = None) -> str:
    if resolved_task_name:
        return resolved_task_name
    sel = entry["selector"]
    if "value" in sel:
        return str(sel["value"])
    if row:
        for key in ("instance_id", "data_id", "id", "index", "task_name"):
            if key in row:
                return str(row[key])
    return f"row_{sel.get('row_index')}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    ap.add_argument("--out-dir", default="./fewshot_output")
    ap.add_argument("--vision2web-root", default=None)
    ap.add_argument("--download-vision2web-archives", action="store_true")
    ap.add_argument(
        "--skip-vision2web",
        action="store_true",
        help="Extract all other benchmarks; omit Vision2Web."
    )
    args = ap.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cache: dict[Any, Any] = {}
    results = []
    errors = []

    for entry in manifest["entries"]:
        try:
            loader = entry["loader"]
            row = None
            raw_query = None
            resolved_task_name = None

            if loader == "hf":
                key = ("hf", entry["repo"], entry.get("config"), entry["split"])
                if key not in cache:
                    cache[key] = load_hf(
                        entry["repo"], entry.get("config"), entry["split"]
                    )
                row = select_row(cache[key], entry["selector"])
                query = row[entry["query_field"]]
                raw_query = query

            elif loader == "json_url":
                key = ("json_url", entry["url"])
                if key not in cache:
                    r = requests.get(entry["url"], timeout=60)
                    r.raise_for_status()
                    obj = r.json()
                    if isinstance(obj, dict):
                        # Common wrappers.
                        for k in ("data", "items", "queries", "examples"):
                            if isinstance(obj.get(k), list):
                                obj = obj[k]
                                break
                    if not isinstance(obj, list):
                        raise TypeError(f"Expected list JSON from {entry['url']}")
                    cache[key] = obj
                row = select_json_row(cache[key], entry["selector"])
                query = row[entry["query_field"]]
                raw_query = query

            elif loader == "webcompass":
                key = ("hf", entry["repo"], entry["config"], entry["split"])
                if key not in cache:
                    cache[key] = load_hf(
                        entry["repo"], entry["config"], entry["split"]
                    )
                row = select_row(cache[key], entry["selector"])
                query, raw_query = webcompass_query(row)

            elif loader == "vision2web":
                if args.skip_vision2web:
                    continue
                query, resolved_task_name = get_v2w_text(entry, args, cache)
                raw_query = query

            else:
                raise ValueError(f"Unknown loader: {loader}")

            rec = {
                "benchmark": entry["benchmark"],
                "category": entry["category"],
                "shot": entry["shot"],
                "case_id": case_id(entry, row, resolved_task_name),
                "source": {
                    "repo": entry.get("repo"),
                    "config": entry.get("config"),
                    "split": entry.get("split"),
                    "subset": entry.get("subset"),
                    "field": entry.get("query_field") or entry.get("text_file"),
                },
                "mapping_note": entry.get("mapping_note"),
                "query": query,
                "raw_query": raw_query,
            }
            results.append(rec)

        except Exception as e:
            errors.append({
                "benchmark": entry["benchmark"],
                "category": entry["category"],
                "shot": entry["shot"],
                "selector": entry["selector"],
                "error": repr(e),
            })

    # JSON
    json_path = out_dir / "fewshot_full_queries.json"
    json_path.write_text(
        json.dumps(
            {
                "count": len(results),
                "errors": errors,
                "cases": results,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # Markdown grouped for direct few-shot inspection/copying.
    grouped = defaultdict(list)
    for r in results:
        grouped[(r["benchmark"], r["category"])].append(r)

    md = [
        "# Benchmark × Category 3-shot Full Query Library",
        "",
        f"Extracted cases: **{len(results)}**",
        f"Extraction errors: **{len(errors)}**",
        "",
        "> Text below is retrieved from the original public benchmark/dataset fields.",
        "",
    ]
    current_bench = None
    for (bench, cat), rows in grouped.items():
        if bench != current_bench:
            md += [f"## {bench}", ""]
            current_bench = bench
        md += [f"### {cat}", ""]
        for r in sorted(rows, key=lambda x: x["shot"]):
            md += [
                f"#### Shot {r['shot']} — `{r['case_id']}`",
                "",
                "```text",
                str(r["query"]).rstrip(),
                "```",
                "",
            ]

    if errors:
        md += ["## Extraction errors", "", "```json",
               json.dumps(errors, indent=2, ensure_ascii=False), "```", ""]

    md_path = out_dir / "fewshot_full_queries.md"
    md_path.write_text("\n".join(md), encoding="utf-8")

    print(f"Wrote: {json_path}")
    print(f"Wrote: {md_path}")
    print(f"Extracted: {len(results)} / {len(manifest['entries'])}")
    if errors:
        print(f"Errors: {len(errors)} (see JSON/Markdown output)")


if __name__ == "__main__":
    main()
