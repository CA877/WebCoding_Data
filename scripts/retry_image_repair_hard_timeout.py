#!/usr/bin/env python3
"""Retry image-repair records with a subprocess-level hard timeout per sample.

This wrapper is intentionally slower than the normal batch builder, but it is
robust against Playwright/Chromium hangs: each sample runs in its own child
process and is killed if it exceeds the hard timeout.
"""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as f:
        for index, line in enumerate(f, start=1):
            if line.strip():
                yield index, json.loads(line)


def safe_name(value: str) -> str:
    if not value or "/" in value or "\x00" in value or value in {".", ".."}:
        raise ValueError(f"unsafe instance_id: {value!r}")
    return value


def merge_jsonl(src: Path, dst: Path) -> int:
    if not src.exists():
        return 0
    count = 0
    with src.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.strip():
                with dst.open("a", encoding="utf-8") as w:
                    w.write(line if line.endswith("\n") else line + "\n")
                count += 1
    return count


def process_one(
    source_index: int,
    record: dict[str, Any],
    out_dir: str,
    script_path: str,
    python_bin: str,
    sample_timeout: int,
    site_timeout: int,
) -> dict[str, Any]:
    instance_id = safe_name(record["instance_id"])
    root = Path(out_dir)
    single_root = root / "_single_runs" / instance_id
    if single_root.exists():
        shutil.rmtree(single_root)
    single_root.mkdir(parents=True, exist_ok=True)
    single_input = single_root / "input.jsonl"
    single_input.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    single_out = single_root / "out"

    cmd = [
        python_bin,
        script_path,
        "--input-jsonl",
        str(single_input),
        "--out-dir",
        str(single_out),
        "--limit",
        "0",
        "--workers",
        "1",
        "--site-timeout",
        str(site_timeout),
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(Path(script_path).resolve().parent.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=sample_timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "index": source_index,
            "instance_id": instance_id,
            "status": "timeout",
            "error": f"subprocess_timeout_{sample_timeout}s",
            "stdout": (exc.stdout or "")[-2000:],
            "stderr": (exc.stderr or "")[-2000:],
            "single_out": str(single_out),
        }

    success = single_out / "image-repair.unified.success.jsonl"
    failed = single_out / "image-repair.unified.failed.jsonl"
    manifest = single_out / "manifest_image_repair.jsonl"
    if success.exists() and success.stat().st_size > 0:
        return {
            "index": source_index,
            "instance_id": instance_id,
            "status": "ok",
            "success": str(success),
            "manifest": str(manifest),
            "returncode": proc.returncode,
        }
    if failed.exists() and failed.stat().st_size > 0:
        return {
            "index": source_index,
            "instance_id": instance_id,
            "status": "error",
            "failed": str(failed),
            "manifest": str(manifest),
            "returncode": proc.returncode,
        }
    return {
        "index": source_index,
        "instance_id": instance_id,
        "status": "empty",
        "error": f"returncode={proc.returncode}",
        "stdout": proc.stdout[-2000:],
        "stderr": proc.stderr[-2000:],
        "single_out": str(single_out),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-jsonl", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--builder-script", type=Path, required=True)
    parser.add_argument("--python-bin", default="python3")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--sample-timeout", type=int, default=300)
    parser.add_argument("--site-timeout", type=int, default=180)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    success_path = args.out_dir / "image-repair.unified.success.jsonl"
    failed_path = args.out_dir / "image-repair.unified.failed.jsonl"
    manifest_path = args.out_dir / "manifest_image_repair.jsonl"
    summary_path = args.out_dir / "_summary.json"
    if args.out_dir.exists() and not args.resume and any(args.out_dir.iterdir()):
        raise FileExistsError(f"output dir is not empty; use --resume: {args.out_dir}")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    done: set[str] = set()
    if args.resume:
        for p in [success_path, failed_path]:
            if p.exists():
                for line in p.open(encoding="utf-8", errors="ignore"):
                    if line.strip():
                        try:
                            done.add(json.loads(line)["instance_id"])
                        except Exception:
                            pass

    ok = failed = timeout = empty = skipped = 0
    pending = set()
    max_pending = max(1, args.workers) * 2

    def consume(done_futures) -> None:  # type: ignore[no-untyped-def]
        nonlocal ok, failed, timeout, empty
        for fut in done_futures:
            result = fut.result()
            status = result["status"]
            if status == "ok":
                merge_jsonl(Path(result["success"]), success_path)
                if result.get("manifest"):
                    merge_jsonl(Path(result["manifest"]), manifest_path)
                ok += 1
            elif status == "error":
                merge_jsonl(Path(result["failed"]), failed_path)
                if result.get("manifest"):
                    merge_jsonl(Path(result["manifest"]), manifest_path)
                failed += 1
            else:
                fail_row = {
                    "schema_version": "webcoding-image-repair-raw-v1",
                    "instance_id": result["instance_id"],
                    "task": "image-repair",
                    "conversion_status": "failed",
                    "error": result.get("error", status),
                }
                append_jsonl(failed_path, fail_row)
                append_jsonl(
                    manifest_path,
                    {
                        "index": result["index"],
                        "instance_id": result["instance_id"],
                        "status": "error",
                        "error": fail_row["error"],
                    },
                )
                if status == "timeout":
                    timeout += 1
                else:
                    empty += 1

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        for index, record in read_jsonl(args.input_jsonl):
            instance_id = safe_name(record["instance_id"])
            if instance_id in done:
                skipped += 1
                continue
            pending.add(
                executor.submit(
                    process_one,
                    index,
                    record,
                    str(args.out_dir),
                    str(args.builder_script),
                    args.python_bin,
                    args.sample_timeout,
                    args.site_timeout,
                )
            )
            if len(pending) >= max_pending:
                done_futures, pending = wait(pending, return_when=FIRST_COMPLETED)
                consume(done_futures)
        while pending:
            done_futures, pending = wait(pending, return_when=FIRST_COMPLETED)
            consume(done_futures)

    summary = {
        "input_jsonl": str(args.input_jsonl),
        "out_dir": str(args.out_dir),
        "workers": args.workers,
        "sample_timeout": args.sample_timeout,
        "site_timeout": args.site_timeout,
        "ok": ok,
        "failed": failed,
        "timeout": timeout,
        "empty": empty,
        "skipped": skipped,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
