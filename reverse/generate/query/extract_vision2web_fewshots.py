#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tarfile
from pathlib import Path

import pandas as pd
from huggingface_hub import hf_hub_download

REPO = "zai-org/Vision2Web"

# Three official Level-2 tasks chosen as diverse multi-page examples.
FRONTEND_TASKS = ["1daycloud", "401trucksource", "6abc"]


def hf_get(filename: str, cache_dir: Path) -> Path:
    p = hf_hub_download(
        repo_id=REPO,
        repo_type="dataset",
        filename=filename,
        local_dir=str(cache_dir),
    )
    return Path(p)


def find_member(tf: tarfile.TarFile, task_name: str, filename: str):
    suffixes = [
        f"frontend/{task_name}/{filename}",
        f"website/{task_name}/{filename}",
        f"datasets/frontend/{task_name}/{filename}",
        f"datasets/website/{task_name}/{filename}",
        f"{task_name}/{filename}",
    ]
    for m in tf.getmembers():
        if not m.isfile():
            continue
        n = m.name.replace("\\", "/").lstrip("/")
        if any(n == s or n.endswith("/" + s) for s in suffixes):
            return m
    raise FileNotFoundError(f"{task_name}/{filename} not found")


def read_tar_text(tar_path: Path, task_name: str, filename: str) -> str:
    with tarfile.open(tar_path, "r:*") as tf:
        m = find_member(tf, task_name, filename)
        f = tf.extractfile(m)
        if f is None:
            raise RuntimeError(f"Cannot extract {m.name}")
        return f.read().decode("utf-8")


def task_name_from_row(row: dict) -> str:
    for key in ("task_name", "name", "id", "task_id"):
        v = row.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    raise KeyError(f"Cannot infer task name from columns: {list(row)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", default="./vision2web_cache")
    ap.add_argument("--out-dir", default="./vision2web_fewshot_output")
    ap.add_argument(
        "--website-rows",
        default="0,1,2",
        help="Three row indices from official website/test.parquet; default: 0,1,2",
    )
    args = ap.parse_args()

    cache = Path(args.cache_dir)
    out = Path(args.out_dir)
    cache.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)

    print("[1/4] Downloading metadata...")
    frontend_meta = hf_get("frontend/test.parquet", cache)
    website_meta = hf_get("website/test.parquet", cache)

    print("[2/4] Downloading official archives...")
    frontend_tar = hf_get("archives/frontend.tar.gz", cache)
    website_tar = hf_get("archives/website.tar.gz", cache)

    website_df = pd.read_parquet(website_meta)
    website_rows = [int(x.strip()) for x in args.website_rows.split(",")]
    if len(website_rows) != 3:
        raise ValueError("--website-rows must contain exactly 3 indices")

    records = []

    print("[3/4] Extracting Level-2 Multi-page prompts...")
    for shot, task in enumerate(FRONTEND_TASKS, 1):
        text = read_tar_text(frontend_tar, task, "prompt.txt")
        records.append({
            "benchmark": "Vision2Web",
            "category": "Multi-page",
            "shot": shot,
            "case_id": task,
            "source": f"frontend/{task}/prompt.txt",
            "query": text,
        })

    print("[4/4] Extracting Level-3 Full-stack PRDs...")
    for shot, idx in enumerate(website_rows, 1):
        row = website_df.iloc[idx].to_dict()
        task = task_name_from_row(row)
        text = read_tar_text(website_tar, task, "prd.md")
        records.append({
            "benchmark": "Vision2Web",
            "category": "Full-stack",
            "shot": shot,
            "case_id": task,
            "source": f"website/{task}/prd.md",
            "metadata_row_index": idx,
            "query": text,
        })

    # Validate 3 + 3.
    mp = [r for r in records if r["category"] == "Multi-page"]
    fs = [r for r in records if r["category"] == "Full-stack"]
    assert len(mp) == 3 and len(fs) == 3 and len(records) == 6

    json_path = out / "vision2web_fewshot_6.json"
    json_path.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    md = ["# Vision2Web Few-shot Examples", ""]
    for category in ("Multi-page", "Full-stack"):
        md += [f"## {category}", ""]
        for r in [x for x in records if x["category"] == category]:
            md += [
                f"### Shot {r['shot']} — `{r['case_id']}`",
                "",
                "```text",
                r["query"].rstrip(),
                "```",
                "",
            ]

    md_path = out / "vision2web_fewshot_6.md"
    md_path.write_text("\n".join(md), encoding="utf-8")

    print(f"\nDone: {json_path}")
    print(f"Done: {md_path}")
    print("Coverage: Multi-page=3, Full-stack=3, Total=6")


if __name__ == "__main__":
    main()
