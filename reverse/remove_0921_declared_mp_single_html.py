#!/usr/bin/env python3
"""Remove Text Edit rows declared mp whose source bundle has fewer than two HTML files."""

import argparse
import collections
import copy
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil


SHARD = "text-edit/train-00000-of-00001.jsonl.gz"
METADATA_FILES = ("dataset_index.json", "README.md", "manifest.json")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text())


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def read_rows(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def html_count(row: dict) -> int:
    code = (row.get("instruction") or {}).get("src_code") or []
    return sum(
        str(item.get("path", "")).lower().endswith((".html", ".htm"))
        for item in code
        if isinstance(item, dict)
    )


def should_remove(row: dict) -> bool:
    return row.get("page_type") == "mp" and html_count(row) < 2


def render_readme(index: dict) -> str:
    table = "\n".join(
        f'| {name} | {entry["num_samples"]} |'
        for name, entry in index["tasks"].items()
    )
    total = sum(entry["num_samples"] for entry in index["tasks"].values())
    return (
        "# 0921\n\n"
        "Canonical working dataset for this optimization round. All new optimization outputs belong here.\n\n"
        "| Task | Records |\n|---|---:|\n"
        f"{table}\n\n"
        f"Total: {total:,}. Text Edit excludes rows declared as multi-HTML when their source bundle contains fewer than two `.html`/`.htm` files. "
        "Text Edit excludes 1–3-subtask rows and contains no old GT. Text Edit rows carry `metadata.instruction_status`: "
        "`query_ready`, `awaiting_query`, or `query_failed`; pending/failed rows have an empty description list. Only query-ready rows may be used for subsequent GT generation. "
        "This Text Edit shard is not a completed SFT input/GT dataset. Other task shards are preserved as recorded in the index. "
        "Image Edit must derive from the current Text Edit code/query/GT and matching canonical source screenshots; obsolete Image Edit records must not be retained alongside regenerated Text Edit.\n\n"
        "Read `dataset_index.json` for current counts and `manifest.json` for hashes. During updates, obey `.0921-write.lock` or retry when index/shard hashes differ. "
        "ModelScope 0905 remains unchanged; 0921 is not uploaded.\n"
    )


def stage(release: Path, control: Path) -> dict:
    shard = release / SHARD
    index = read_json(release / "dataset_index.json")
    manifest = read_json(release / "manifest.json")
    actual = sha256(shard)
    if actual != index["tasks"]["text-edit"]["sha256"]:
        raise ValueError("Text Edit shard hash differs from dataset_index.json")
    if actual != manifest[SHARD]["sha256"]:
        raise ValueError("Text Edit shard hash differs from manifest.json")

    rows = read_rows(shard)
    removed = [row for row in rows if should_remove(row)]
    kept = [row for row in rows if not should_remove(row)]
    if not removed:
        raise ValueError("no declared-mp single-HTML rows found")
    if len(rows) != index["tasks"]["text-edit"]["num_samples"]:
        raise ValueError("Text Edit row count differs from dataset_index.json")

    staged = control / "staged"
    (staged / "text-edit").mkdir(parents=True, exist_ok=False)
    with gzip.open(staged / SHARD, "wt", encoding="utf-8", compresslevel=1) as stream:
        for row in kept:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    with gzip.open(control / "removed.jsonl.gz", "wt", encoding="utf-8", compresslevel=1) as stream:
        for row in removed:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    updated_index = copy.deepcopy(index)
    entry = updated_index["tasks"]["text-edit"]
    status_counts = collections.Counter(
        (row.get("metadata") or {}).get("instruction_status", "missing") for row in kept
    )
    entry.update(
        num_samples=len(kept),
        sha256=sha256(staged / SHARD),
        compressed_gib=round((staged / SHARD).stat().st_size / 1024**3, 6),
        instruction_status_counts=dict(status_counts),
        removed_declared_mp_single_html=len(removed),
        physical_html_counts={
            "single_html": sum(html_count(row) < 2 for row in kept),
            "multi_html": sum(html_count(row) >= 2 for row in kept),
        },
    )
    optimization = updated_index.get("current_optimization", {}).get("text_edit")
    if isinstance(optimization, dict):
        for key in ("query_ready", "awaiting_query", "query_failed"):
            optimization[key] = status_counts.get(key, 0)
        optimization["removed_declared_mp_single_html"] = len(removed)
    write_json(staged / "dataset_index.json", updated_index)
    (staged / "README.md").write_text(render_readme(updated_index))

    updated_manifest = copy.deepcopy(manifest)
    for name in (SHARD, "dataset_index.json", "README.md"):
        path = staged / name
        updated_manifest[name] = {"size": path.stat().st_size, "sha256": sha256(path)}
    write_json(staged / "manifest.json", updated_manifest)

    report = {
        "status": "staged",
        "release": str(release),
        "before_count": len(rows),
        "removed_count": len(removed),
        "after_count": len(kept),
        "before_sha256": actual,
        "after_sha256": sha256(staged / SHARD),
        "kept_page_type_counts": dict(collections.Counter(row.get("page_type") for row in kept)),
        "kept_html_counts": entry["physical_html_counts"],
        "removed_instance_ids": [row.get("instance_id") for row in removed],
    }
    write_json(control / "report.json", report)
    return report


def apply(release: Path, control: Path) -> dict:
    report = read_json(control / "report.json")
    if report.get("status") != "staged" or report.get("release") != str(release):
        raise ValueError("control directory is not a matching staged removal")
    with (release / ".0921-write.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if sha256(release / SHARD) != report["before_sha256"]:
            raise ValueError("formal Text Edit shard changed after staging")
        backup = control / "backup"
        backup.mkdir(exist_ok=False)
        for name in (SHARD, *METADATA_FILES):
            target = backup / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(release / name, target)
        for name in (SHARD, *METADATA_FILES):
            source = control / "staged" / name
            temporary = (release / name).with_name((release / name).name + ".physical-html-filter.tmp")
            shutil.copy2(source, temporary)
            os.replace(temporary, release / name)
        if sha256(release / SHARD) != report["after_sha256"]:
            raise ValueError("post-install Text Edit hash mismatch")
        index = read_json(release / "dataset_index.json")
        manifest = read_json(release / "manifest.json")
        if index["tasks"]["text-edit"]["sha256"] != report["after_sha256"]:
            raise ValueError("post-install dataset index mismatch")
        if manifest[SHARD]["sha256"] != report["after_sha256"]:
            raise ValueError("post-install manifest mismatch")
    report["status"] = "applied"
    write_json(control / "report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stage", "apply"))
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--control", type=Path, required=True)
    args = parser.parse_args()
    result = stage(args.release, args.control) if args.action == "stage" else apply(args.release, args.control)
    print(json.dumps({key: result[key] for key in ("status", "before_count", "removed_count", "after_count")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
