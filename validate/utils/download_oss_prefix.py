#!/usr/bin/env python3
"""Download an Aliyun OSS prefix into a local directory with a manifest."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import oss2


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"missing required environment variable: {name}")
    return value


def fmt_gib(num_bytes: int) -> str:
    return f"{num_bytes / 1024 ** 3:.3f} GiB"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--dest", required=True)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--part-size", type=int, default=64 * 1024 * 1024)
    args = parser.parse_args()

    auth = oss2.Auth(require_env("OSS_ACCESS_KEY_ID"), require_env("OSS_ACCESS_KEY_SECRET"))
    bucket = oss2.Bucket(auth, args.endpoint, args.bucket)
    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    checkpoint_dir = dest / ".oss_download_checkpoint"
    checkpoint_dir.mkdir(exist_ok=True)

    objects = [obj for obj in oss2.ObjectIterator(bucket, prefix=args.prefix) if not obj.key.endswith("/")]
    total_bytes = sum(obj.size or 0 for obj in objects)
    print(f"objects: {len(objects)}")
    print(f"total: {total_bytes} bytes ({fmt_gib(total_bytes)})")
    print(f"dest: {dest}")

    manifest = {
        "bucket": args.bucket,
        "prefix": args.prefix,
        "endpoint": args.endpoint,
        "dest": str(dest),
        "download_started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "objects": [],
    }

    for index, obj in enumerate(objects, start=1):
        rel = obj.key[len(args.prefix) :].lstrip("/")
        if not rel:
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists() and target.stat().st_size == obj.size:
            print(f"[{index}/{len(objects)}] skip existing {rel} ({fmt_gib(obj.size or 0)})")
        else:
            print(f"[{index}/{len(objects)}] download {rel} ({fmt_gib(obj.size or 0)})")

            last_report = {"t": 0.0, "n": 0}

            def progress(consumed_bytes: int, total_object_bytes: int) -> None:
                now = time.time()
                if now - last_report["t"] >= 20 or consumed_bytes == total_object_bytes:
                    last_report["t"] = now
                    last_report["n"] = consumed_bytes
                    pct = 100 * consumed_bytes / total_object_bytes if total_object_bytes else 100
                    print(f"  {pct:6.2f}% {fmt_gib(consumed_bytes)} / {fmt_gib(total_object_bytes)}", flush=True)

            oss2.resumable_download(
                bucket,
                obj.key,
                str(target),
                store=oss2.ResumableDownloadStore(root=str(checkpoint_dir)),
                multiget_threshold=32 * 1024 * 1024,
                part_size=args.part_size,
                num_threads=args.jobs,
                progress_callback=progress,
            )

        manifest["objects"].append(
            {
                "key": obj.key,
                "relative_path": rel,
                "size": obj.size,
                "etag": obj.etag,
                "last_modified": obj.last_modified,
            }
        )

    manifest["download_finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    (dest / "_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"wrote manifest: {dest / '_manifest.json'}")


if __name__ == "__main__":
    main()
