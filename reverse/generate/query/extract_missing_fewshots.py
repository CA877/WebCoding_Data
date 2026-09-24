#!/usr/bin/env python3
"""
One-command extractor for the missing benchmark few-shot cases.

Default output:
  78 complete cases =
    ArtifactsBench 7 categories × 3
    Cookie-Bench   7 categories × 3
    WebGen         5 categories × 3
    WebCompass     5 categories × 3
    Vision2Web     2 categories × 3

Outputs:
  fewshot_missing_78.json
  fewshot_missing_78.md
  coverage_report.json

The extractor reads exact original fields from the official/public sources:
  ArtifactsBench: question
  Cookie-Bench:   query
  WebGen:         instruction
  WebCompass:     full description list
  Vision2Web L2:  prompt.txt
  Vision2Web L3:  prd.md

Install:
  pip install -U huggingface_hub hf_xet pandas pyarrow requests

Usage:
  python extract_all_fewshots.py --out-dir ./fewshot_output

If you already downloaded files:
  python extract_all_fewshots.py \
      --source-dir ./benchmark_sources \
      --out-dir ./fewshot_output

Vision2Web archives are large (~3.7 GB total). To extract the other 72 only:
  python extract_all_fewshots.py --skip-vision2web
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tarfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import requests
from huggingface_hub import hf_hub_download

HERE = Path(__file__).resolve().parent
DEFAULT_SELECTORS = HERE / "fewshots" / "selectors_missing_78.json"


def s(v: Any) -> str:
    return str(v).strip()


def sha256_file(path: Path, block=1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(block)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def ensure_parent(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def hf_get(repo: str, filename: str, cache_root: Path) -> Path:
    """
    Download one official dataset file into a stable local source tree.
    """
    local_dir = cache_root / repo.replace("/", "__")
    local_dir.mkdir(parents=True, exist_ok=True)
    p = hf_hub_download(
        repo_id=repo,
        repo_type="dataset",
        filename=filename,
        local_dir=str(local_dir),
    )
    return Path(p)


def locate_or_download(
    source_dir: Path | None,
    candidates: list[Path],
    repo: str,
    filename: str,
    cache_root: Path,
) -> Path:
    if source_dir:
        for rel in candidates:
            p = source_dir / rel
            if p.is_file():
                return p
    return hf_get(repo, filename, cache_root)


def read_json_or_jsonl(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    stripped = text.lstrip()
    if stripped.startswith("["):
        obj = json.loads(text)
        if not isinstance(obj, list):
            raise TypeError(f"{path}: expected JSON list")
        return obj
    rows = []
    for ln, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception as e:
            raise ValueError(f"{path}:{ln}: invalid JSONL") from e
    return rows


def find_by(rows: Iterable[dict], field: str, value: Any) -> dict:
    target = s(value)
    for row in rows:
        if field in row and s(row[field]) == target:
            return row
    raise KeyError(f"not found: {field}={value}")


def find_df(df: pd.DataFrame, field: str, value: Any) -> dict:
    if field not in df.columns:
        raise KeyError(f"missing column {field}; columns={list(df.columns)}")
    target = s(value)
    mask = df[field].astype(str).str.strip() == target
    hit = df[mask]
    if hit.empty:
        raise KeyError(f"not found: {field}={value}")
    return hit.iloc[0].to_dict()


def webcompass_text(raw: Any) -> str:
    """
    Keep every original description. Only adds task-type headings for readability.
    raw_query in JSON preserves the exact original list.
    """
    if not isinstance(raw, list):
        return s(raw)
    chunks = []
    for item in raw:
        if isinstance(item, dict):
            t = s(item.get("task_type", ""))
            d = s(item.get("description", ""))
            chunks.append(f"[{t}]\n{d}" if t else d)
        else:
            chunks.append(s(item))
    return "\n\n".join(chunks)


def identify_task_name(row: dict) -> str:
    for k in ("task_name", "name", "id", "task_id", "site_name", "website_name"):
        v = row.get(k)
        if v is not None and s(v):
            return s(v)
    # Some metadata may keep a relative task path.
    for k in row:
        if "task" in k.lower() or "name" in k.lower():
            v = row.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip().strip("/").split("/")[-1]
    raise KeyError(f"cannot identify task name; keys={list(row.keys())}")


def tar_read_member_by_suffix(tar_path: Path, suffixes: list[str]) -> tuple[str, str]:
    """
    Read one member without extracting the full multi-GB archive.
    Returns (text, member_name).
    """
    normalized = [x.replace("\\", "/").lstrip("/") for x in suffixes]
    with tarfile.open(tar_path, "r:*") as tf:
        members = [m for m in tf.getmembers() if m.isfile()]
        for suffix in normalized:
            for m in members:
                name = m.name.replace("\\", "/").lstrip("/")
                if name == suffix or name.endswith("/" + suffix):
                    f = tf.extractfile(m)
                    if f is None:
                        continue
                    return f.read().decode("utf-8"), m.name
    raise FileNotFoundError(
        f"None of {normalized} found in {tar_path}"
    )


def rec(
    benchmark: str,
    category: str,
    shot: int,
    case_id: str,
    query: str,
    raw_query: Any,
    source: dict,
    mapping_note: str | None = None,
) -> dict:
    return {
        "benchmark": benchmark,
        "category": category,
        "shot": shot,
        "case_id": case_id,
        "query": query,
        "raw_query": raw_query,
        "source": source,
        "mapping_note": mapping_note,
    }


def extract_artifacts(selectors, source_dir, cache_root):
    path = locate_or_download(
        source_dir,
        [
            Path("artifactsbench/artifacts_bench.json"),
            Path("ArtifactsBench/artifacts_bench.json"),
            Path("dataset/artifacts_bench.json"),
            Path("artifacts_bench.json"),
        ],
        "tencent/ArtifactsBenchmark",
        "artifacts_bench.json",
        cache_root,
    )
    rows = read_json_or_jsonl(path)
    out = []
    for cat, ids in selectors["ArtifactsBench"].items():
        for shot, idx in enumerate(ids, 1):
            row = find_by(rows, "index", idx)
            q = row["question"]
            out.append(rec(
                "ArtifactsBench", cat, shot, s(row["index"]), q, q,
                {
                    "repo": "tencent/ArtifactsBenchmark",
                    "file": "artifacts_bench.json",
                    "field": "question",
                    "local_path": str(path),
                    "source_sha256": sha256_file(path),
                },
            ))
    return out


def extract_cookie(selectors, source_dir, cache_root):
    path = locate_or_download(
        source_dir,
        [
            Path("cookie/data/test.jsonl"),
            Path("cookie_bench/data/test.jsonl"),
            Path("Cookie-Bench/data/test.jsonl"),
            Path("data/test.jsonl"),
        ],
        "Y36521478Y/Cookie-Bench",
        "data/test.jsonl",
        cache_root,
    )
    rows = read_json_or_jsonl(path)
    out = []
    for cat, ids in selectors["Cookie-Bench"].items():
        for shot, cid in enumerate(ids, 1):
            row = find_by(rows, "data_id", cid)
            q = row["query"]
            out.append(rec(
                "Cookie-Bench", cat, shot, s(row["data_id"]), q, q,
                {
                    "repo": "Y36521478Y/Cookie-Bench",
                    "file": "data/test.jsonl",
                    "field": "query",
                    "language_group": row.get("language_group"),
                    "difficulty": row.get("difficulty"),
                    "l2_category": row.get("l2_category"),
                    "l3_category": row.get("l3_category"),
                    "local_path": str(path),
                    "source_sha256": sha256_file(path),
                },
            ))
    return out


def extract_webgen(selectors, source_dir, cache_root):
    path = locate_or_download(
        source_dir,
        [
            Path("webgen/data/train-00000-of-00001.parquet"),
            Path("WebGen-Bench/data/train-00000-of-00001.parquet"),
            Path("data/train-00000-of-00001.parquet"),
        ],
        "luzimu/WebGen-Bench",
        "data/train-00000-of-00001.parquet",
        cache_root,
    )
    df = pd.read_parquet(path)
    out = []
    for cat, ids in selectors["WebGen"].items():
        for shot, cid in enumerate(ids, 1):
            row = find_df(df, "id", cid)
            q = row["instruction"]
            out.append(rec(
                "WebGen", cat, shot, s(row["id"]), q, q,
                {
                    "repo": "luzimu/WebGen-Bench",
                    "file": "data/train-00000-of-00001.parquet",
                    "field": "instruction",
                    "application_type": row.get("application_type"),
                    "local_path": str(path),
                    "source_sha256": sha256_file(path),
                },
                "Uses WebGen-Instruct train examples, not WebGen-Bench test prompts.",
            ))
    return out


def load_wc_file(source_dir, cache_root, split: str):
    fn = f"editing/{split}/data.jsonl"
    path = locate_or_download(
        source_dir,
        [
            Path(f"webcompass/{fn}"),
            Path(f"WebCompass/{fn}"),
            Path(fn),
        ],
        "NJU-LINK/WebCompass",
        fn,
        cache_root,
    )
    return path, read_json_or_jsonl(path)


def extract_webcompass(selectors, source_dir, cache_root):
    sp_path, sp = load_wc_file(source_dir, cache_root, "sp")
    mp_path, mp = load_wc_file(source_dir, cache_root, "mp")
    combined = sp + mp

    out = []
    for cat, sels in selectors["WebCompass"].items():
        for shot, sel in enumerate(sels, 1):
            if isinstance(sel, dict) and "row_index" in sel:
                row = mp[int(sel["row_index"])]
                used_path = mp_path
                split = "mp"
            else:
                row = find_by(combined, "instance_id", sel)
                # Determine source split.
                if any(s(r.get("instance_id")) == s(sel) for r in sp):
                    used_path, split = sp_path, "sp"
                else:
                    used_path, split = mp_path, "mp"

            raw = row["description"]
            q = webcompass_text(raw)

            note = None
            if cat == "Full-stack":
                note = (
                    "Complex/stateful web-app proxy only. WebCompass does not "
                    "natively evaluate backend correctness."
                )

            out.append(rec(
                "WebCompass", cat, shot, s(row["instance_id"]), q, raw,
                {
                    "repo": "NJU-LINK/WebCompass",
                    "file": f"editing/{split}/data.jsonl",
                    "field": "description",
                    "difficulty": row.get("difficulty"),
                    "task_type": row.get("task_type"),
                    "local_path": str(used_path),
                    "source_sha256": sha256_file(used_path),
                },
                note,
            ))
    return out


def load_v2w_meta(source_dir, cache_root, subset: str) -> tuple[Path, pd.DataFrame]:
    fn = f"{subset}/test.parquet"
    path = locate_or_download(
        source_dir,
        [
            Path(f"vision2web/{fn}"),
            Path(f"Vision2Web/{fn}"),
            Path(fn),
        ],
        "zai-org/Vision2Web",
        fn,
        cache_root,
    )
    return path, pd.read_parquet(path)


def load_v2w_archive(source_dir, cache_root, subset: str) -> Path:
    fn = f"archives/{subset}.tar.gz"
    return locate_or_download(
        source_dir,
        [
            Path(f"vision2web/{fn}"),
            Path(f"Vision2Web/{fn}"),
            Path(fn),
        ],
        "zai-org/Vision2Web",
        fn,
        cache_root,
    )


def meta_find_task(df: pd.DataFrame, wanted: str) -> dict | None:
    for _, r in df.iterrows():
        d = r.to_dict()
        try:
            if identify_task_name(d).lower() == wanted.lower():
                return d
        except Exception:
            pass
    return None


def extract_vision2web(selectors, source_dir, cache_root):
    front_meta_path, front_df = load_v2w_meta(source_dir, cache_root, "frontend")
    web_meta_path, web_df = load_v2w_meta(source_dir, cache_root, "website")
    front_tar = load_v2w_archive(source_dir, cache_root, "frontend")
    web_tar = load_v2w_archive(source_dir, cache_root, "website")

    out = []

    # Level 2
    for shot, task_name in enumerate(selectors["Vision2Web"]["Multi-page"], 1):
        row = meta_find_task(front_df, task_name)
        # Even if metadata naming changes, archive lookup by the known task name remains valid.
        q, member = tar_read_member_by_suffix(
            front_tar,
            [
                f"frontend/{task_name}/prompt.txt",
                f"datasets/frontend/{task_name}/prompt.txt",
                f"{task_name}/prompt.txt",
            ],
        )
        out.append(rec(
            "Vision2Web", "Multi-page", shot, task_name, q, q,
            {
                "repo": "zai-org/Vision2Web",
                "metadata_file": "frontend/test.parquet",
                "archive": "archives/frontend.tar.gz",
                "field": "prompt.txt",
                "archive_member": member,
                "metadata_row": row,
                "archive_sha256": sha256_file(front_tar),
            },
            "Vision2Web Level 2: Interactive Frontend.",
        ))

    # Level 3 — deterministic first three official metadata rows.
    for shot, sel in enumerate(selectors["Vision2Web"]["Full-stack"], 1):
        idx = int(sel["row_index"])
        row = web_df.iloc[idx].to_dict()
        task_name = identify_task_name(row)
        q, member = tar_read_member_by_suffix(
            web_tar,
            [
                f"website/{task_name}/prd.md",
                f"datasets/website/{task_name}/prd.md",
                f"{task_name}/prd.md",
            ],
        )
        out.append(rec(
            "Vision2Web", "Full-stack", shot, task_name, q, q,
            {
                "repo": "zai-org/Vision2Web",
                "metadata_file": "website/test.parquet",
                "metadata_row_index": idx,
                "archive": "archives/website.tar.gz",
                "field": "prd.md",
                "archive_member": member,
                "metadata_row": row,
                "archive_sha256": sha256_file(web_tar),
            },
            "Vision2Web Level 3: Full-Stack Website.",
        ))

    return out


def validate(results: list[dict], expected_cells: dict) -> dict:
    counts = Counter((r["benchmark"], r["category"]) for r in results)
    expected = {
        (bench, cat): 3
        for bench, cats in expected_cells.items()
        for cat in cats.keys()
    }

    missing = []
    wrong = []
    for key, n in expected.items():
        if key not in counts:
            missing.append({"benchmark": key[0], "category": key[1], "count": 0})
        elif counts[key] != n:
            wrong.append({
                "benchmark": key[0],
                "category": key[1],
                "expected": n,
                "actual": counts[key],
            })

    extras = [
        {"benchmark": b, "category": c, "count": n}
        for (b, c), n in counts.items()
        if (b, c) not in expected
    ]

    return {
        "expected_cases": len(expected) * 3,
        "actual_cases": len(results),
        "expected_cells": len(expected),
        "actual_cells": len(counts),
        "all_cells_exactly_3": not missing and not wrong and not extras,
        "missing": missing,
        "wrong_count": wrong,
        "extras": extras,
        "counts": {
            f"{b} / {c}": n
            for (b, c), n in sorted(counts.items())
        },
    }


def write_outputs(results, report, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)

    j = out_dir / "fewshot_missing_78.json"
    j.write_text(json.dumps(
        {
            "count": len(results),
            "coverage": report,
            "cases": results,
        },
        ensure_ascii=False,
        indent=2,
    ), encoding="utf-8")

    (out_dir / "coverage_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    grouped = defaultdict(list)
    for r in results:
        grouped[(r["benchmark"], r["category"])].append(r)

    lines = [
        "# Missing Benchmark × Category Few-Shot Queries",
        "",
        f"Total extracted: **{len(results)}**",
        f"Coverage exact: **{report['all_cells_exactly_3']}**",
        "",
        "The code blocks below contain the complete original query field "
        "retrieved by the extractor.",
        "",
    ]
    current = None
    for (bench, cat), rows in grouped.items():
        if bench != current:
            lines.extend([f"## {bench}", ""])
            current = bench
        lines.extend([f"### {cat}", ""])
        for r in sorted(rows, key=lambda x: x["shot"]):
            lines.extend([
                f"#### Shot {r['shot']} — `{r['case_id']}`",
                "",
                "```text",
                str(r["query"]).rstrip(),
                "```",
                "",
            ])

    md = out_dir / "fewshot_missing_78.md"
    md.write_text("\n".join(lines), encoding="utf-8")

    return j, md


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--selectors",
        default=str(DEFAULT_SELECTORS),
        help="Selector manifest JSON."
    )
    ap.add_argument(
        "--source-dir",
        default=None,
        help="Optional root containing already-downloaded source files."
    )
    ap.add_argument(
        "--cache-dir",
        default="./benchmark_source_cache",
        help="Where official source files are downloaded."
    )
    ap.add_argument(
        "--out-dir",
        default="./fewshot_output",
        help="Output directory."
    )
    ap.add_argument(
        "--skip-vision2web",
        action="store_true",
        help="Extract 72 cases from the four other missing benchmarks only."
    )
    args = ap.parse_args()

    selectors = json.loads(Path(args.selectors).read_text(encoding="utf-8"))
    source_dir = Path(args.source_dir).resolve() if args.source_dir else None
    cache_root = Path(args.cache_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    cache_root.mkdir(parents=True, exist_ok=True)

    extractors = [
        ("ArtifactsBench", extract_artifacts),
        ("Cookie-Bench", extract_cookie),
        ("WebGen", extract_webgen),
        ("WebCompass", extract_webcompass),
    ]
    if not args.skip_vision2web:
        extractors.append(("Vision2Web", extract_vision2web))

    results = []
    failures = []

    for name, fn in extractors:
        print(f"[extract] {name}", flush=True)
        try:
            part = fn(selectors, source_dir, cache_root)
            results.extend(part)
            print(f"[ok] {name}: {len(part)}", flush=True)
        except Exception as e:
            failures.append({"benchmark": name, "error": repr(e)})
            print(f"[FAILED] {name}: {e!r}", file=sys.stderr, flush=True)

    expected = {
        k: v for k, v in selectors.items()
        if not (args.skip_vision2web and k == "Vision2Web")
    }
    report = validate(results, expected)
    report["failures"] = failures

    j, md = write_outputs(results, report, out_dir)

    print()
    print(f"JSON: {j}")
    print(f"Markdown: {md}")
    print(f"Coverage: {out_dir / 'coverage_report.json'}")
    print(
        f"Extracted {report['actual_cases']}/{report['expected_cases']} cases "
        f"across {report['actual_cells']}/{report['expected_cells']} cells."
    )

    if failures or not report["all_cells_exactly_3"]:
        sys.exit(2)


if __name__ == "__main__":
    main()
