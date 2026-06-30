#!/usr/bin/env python3
"""Prepare and optionally upload a Hugging Face layout for the six-task release."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any


TASKS = [
    "text-generate",
    "text-edit",
    "text-repair",
    "image-generate",
    "image-edit",
    "image-repair",
]


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def hardlink_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.mkdir(parents=True, exist_ok=True)
    run(["cp", "-al", f"{src}/.", str(dst)])


def prefix_image_paths(record: dict[str, Any], prefix: str) -> dict[str, Any]:
    def fix(value: Any) -> Any:
        if not isinstance(value, list):
            return value
        out = []
        for item in value:
            if isinstance(item, str) and item and not item.startswith(prefix):
                out.append(prefix + item)
            else:
                out.append(item)
        return out

    for key in ["input_images", "src_screenshot", "dst_screenshot"]:
        if key in record:
            record[key] = fix(record[key])
    return record


def gzip_task(source_jsonl: Path, target_gz: Path, task: str) -> dict[str, Any]:
    target_gz.parent.mkdir(parents=True, exist_ok=True)
    tmp = target_gz.with_suffix(target_gz.suffix + ".tmp")
    count = 0
    in_bytes = source_jsonl.stat().st_size
    with source_jsonl.open(encoding="utf-8", errors="ignore") as src, gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as dst:
        for line in src:
            if not line.strip():
                continue
            if task == "image-generate":
                record = prefix_image_paths(json.loads(line), "images/")
                dst.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            else:
                dst.write(line if line.endswith("\n") else line + "\n")
            count += 1
    os.replace(tmp, target_gz)
    out_bytes = target_gz.stat().st_size
    return {
        "task": task,
        "samples": count,
        "source": str(source_jsonl),
        "shards": [str(target_gz)],
        "input_gib": round(in_bytes / 1024**3, 3),
        "gzip_gib": round(out_bytes / 1024**3, 3),
    }


def write_metadata(out_root: Path, source_index: dict[str, Any], results: dict[str, dict[str, Any]]) -> None:
    tasks = {}
    for task in TASKS:
        meta = dict(source_index["tasks"][task])
        meta["data_files"] = [f"{task}/train-00000-of-00001.jsonl.gz"]
        meta["jsonl"] = meta["data_files"][0]
        if task.startswith("image-"):
            meta["image_root"] = f"{task}/images"
            meta["image_path_mode"] = "paths in records are relative to the task folder"
        meta["compressed_gib"] = results[task]["gzip_gib"]
        meta["uncompressed_gib"] = results[task]["input_gib"]
        tasks[task] = meta
    index = {
        "name": "release_sft_6tasks_v1_hf",
        "source_release": source_index.get("root"),
        "tasks": tasks,
        "notes": [
            "Each task is stored in its own folder.",
            "JSONL files are gzip compressed.",
            "Image folders are ordinary files, prepared via hard links on the local filesystem.",
            "For image tasks, read images as task_root / record image path.",
            "Edit and repair targets are patch arrays; do not assume a single patch.",
        ],
    }
    (out_root / "dataset_index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    readme = """# WebCoding SFT 六类任务 Hugging Face 版本

这个目录用于上传 Hugging Face。每个任务一个文件夹，JSONL 已 gzip 压缩，图片任务的图片以普通文件形式放在对应任务目录下。

## 目录结构

```text
text-generate/train-00000-of-00001.jsonl.gz
text-edit/train-00000-of-00001.jsonl.gz
text-repair/train-00000-of-00001.jsonl.gz
image-generate/train-00000-of-00001.jsonl.gz
image-generate/images/
image-edit/train-00000-of-00001.jsonl.gz
image-edit/images/
image-repair/train-00000-of-00001.jsonl.gz
image-repair/images/
```

图片没有打包压缩。训练时直接按 JSONL 中的相对路径读取，例如：

```python
image_path = task_root / record["input_images"][0]
```

详细任务信息、样本数、分片路径和图片根目录见 `dataset_index.json`。
"""
    (out_root / "README.md").write_text(readme, encoding="utf-8")


def upload_to_hub(out_root: Path, repo_id: str, private: bool) -> None:
    from huggingface_hub import HfApi

    api = HfApi()
    api.create_repo(repo_id=repo_id, repo_type="dataset", private=private, exist_ok=True)
    api.upload_folder(
        repo_id=repo_id,
        repo_type="dataset",
        folder_path=str(out_root),
        path_in_repo=".",
        commit_message="Upload WebCoding SFT six-task release",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=Path("/data1/xieqianqian/webcoding/release_sft_6tasks_v1"))
    parser.add_argument("--out-root", type=Path, default=Path("/data1/xieqianqian/webcoding/release_sft_6tasks_v1_hf"))
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--repo-id", default="")
    parser.add_argument("--private", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if args.out_root.exists():
        if not args.overwrite:
            raise SystemExit(f"output exists; pass --overwrite to rebuild: {args.out_root}")
        shutil.rmtree(args.out_root)
    args.out_root.mkdir(parents=True)

    source_index = json.loads((args.source_root / "dataset_index.json").read_text(encoding="utf-8"))

    # Prepare images as hard links in the desired task-local layout.
    hardlink_tree(args.source_root / "images/image-generate", args.out_root / "image-generate/images")
    hardlink_tree(args.source_root / "images/image-edit/images", args.out_root / "image-edit/images")
    hardlink_tree(args.source_root / "images/image-repair/images", args.out_root / "image-repair/images")

    futures = {}
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for task in TASKS:
            source_jsonl = args.source_root / "jsonl" / f"{task}.jsonl"
            target_gz = args.out_root / task / "train-00000-of-00001.jsonl.gz"
            futures[executor.submit(gzip_task, source_jsonl, target_gz, task)] = task

        results = {}
        for future in as_completed(futures):
            result = future.result()
            results[result["task"]] = result
            print(json.dumps(result, ensure_ascii=False), flush=True)

    write_metadata(args.out_root, source_index, results)
    print(json.dumps({"out_root": str(args.out_root), "tasks": results}, ensure_ascii=False, indent=2), flush=True)

    if args.repo_id:
        upload_to_hub(args.out_root, args.repo_id, args.private)
        print(json.dumps({"uploaded_to": args.repo_id}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
