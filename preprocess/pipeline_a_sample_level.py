#!/usr/bin/env python3
"""Sample-level Pipeline A preprocessing for WebRenderBench.

For each input project:
1. Try to expand it to multiple pages.
2. Always clean the original project.
3. If expansion succeeds, also clean the expanded project.

This keeps concurrency at the sample level instead of running all expand work
before all clean work.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import queue
import shutil
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

from playwright_crawl import build_requests_session, clean_project, expand_project


def _copy_fresh(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def process_sample(payload: tuple[str, str, str, str, int, int]) -> dict[str, Any]:
    project_path, output_root, browser_proxy, requests_proxy, max_pages, wait_ms = payload
    project_dir = Path(project_path)
    output_dir = Path(output_root)
    clean_root = output_dir / "clean_projects"
    expand_tmp_root = output_dir / "_expand_tmp"
    clean_root.mkdir(parents=True, exist_ok=True)
    expand_tmp_root.mkdir(parents=True, exist_ok=True)

    started = time.time()
    result: dict[str, Any] = {
        "project": project_dir.name,
        "status": "ok",
        "expand_status": None,
        "outputs": [],
        "errors": [],
    }

    session = build_requests_session(requests_proxy)

    expanded_project = expand_tmp_root / project_dir.name
    if expanded_project.exists():
        shutil.rmtree(expanded_project)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            proxy={"server": browser_proxy} if browser_proxy else None,
        )
        try:
            expand_result = expand_project(
                project_dir,
                expand_tmp_root,
                browser,
                session,
                max_pages=max_pages,
                wait_ms=wait_ms,
            )
        except Exception as exc:  # noqa: BLE001
            expand_result = {
                "status": "error",
                "project": project_dir.name,
                "error": f"{type(exc).__name__}: {exc}",
            }
        finally:
            browser.close()

    result["expand_status"] = expand_result.get("status")
    result["expand_result"] = expand_result

    original_out = clean_root / f"{project_dir.name}__original"
    try:
        _copy_fresh(project_dir, original_out)
        clean_result = clean_project(original_out, session)
        result["outputs"].append(
            {
                "variant": "original",
                "path": str(original_out),
                "clean_status": clean_result.get("status"),
                "remaining_remote_refs": clean_result.get("remaining_remote_refs"),
            }
        )
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(original_out, ignore_errors=True)
        result["errors"].append({"stage": "clean_original", "error": f"{type(exc).__name__}: {exc}"})

    if expand_result.get("status") == "expanded" and expanded_project.exists():
        expanded_out = clean_root / f"{project_dir.name}__expanded"
        try:
            _copy_fresh(expanded_project, expanded_out)
            clean_result = clean_project(expanded_out, session)
            result["outputs"].append(
                {
                    "variant": "expanded",
                    "path": str(expanded_out),
                    "clean_status": clean_result.get("status"),
                    "remaining_remote_refs": clean_result.get("remaining_remote_refs"),
                    "pages_added": expand_result.get("pages_added"),
                    "total_pages": expand_result.get("total_pages"),
                }
            )
        except Exception as exc:  # noqa: BLE001
            shutil.rmtree(expanded_out, ignore_errors=True)
            result["errors"].append({"stage": "clean_expanded", "error": f"{type(exc).__name__}: {exc}"})

    shutil.rmtree(expanded_project, ignore_errors=True)

    if result["errors"]:
        result["status"] = "partial" if result["outputs"] else "error"
    result["elapsed"] = round(time.time() - started, 1)
    return result


def process_sample_entry(payload: tuple[str, str, str, str, int, int], result_queue: mp.Queue) -> None:
    result_queue.put(process_sample(payload))


def timeout_result(payload: tuple[str, str, str, str, int, int], elapsed: float, site_timeout: int) -> dict[str, Any]:
    return {
        "project": Path(payload[0]).name,
        "status": "site_timeout",
        "expand_status": "site_timeout",
        "outputs": [],
        "errors": [{"stage": "sample", "error": f"site_timeout after {site_timeout}s"}],
        "elapsed": round(elapsed, 1),
        "site_timeout": site_timeout,
    }


def cleanup_sample_outputs(payload: tuple[str, str, str, str, int, int]) -> None:
    project = Path(payload[0]).name
    output_dir = Path(payload[1])
    shutil.rmtree(output_dir / "_expand_tmp" / project, ignore_errors=True)
    shutil.rmtree(output_dir / "clean_projects" / f"{project}__original", ignore_errors=True)
    shutil.rmtree(output_dir / "clean_projects" / f"{project}__expanded", ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run sample-level WebRenderBench expand/clean preprocessing")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--max-pages", type=int, default=4)
    parser.add_argument("--wait", type=int, default=3000)
    parser.add_argument("--browser-proxy", default="")
    parser.add_argument("--requests-proxy", default="")
    parser.add_argument(
        "--site-timeout",
        type=int,
        default=0,
        help="Hard wall-clock timeout per sample in seconds. When set, stuck workers are terminated.",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    clean_root = args.output_dir / "clean_projects"
    if args.overwrite:
        shutil.rmtree(clean_root, ignore_errors=True)
        shutil.rmtree(args.output_dir / "_expand_tmp", ignore_errors=True)
    clean_root.mkdir(parents=True, exist_ok=True)

    projects = sorted(d for d in args.input_dir.iterdir() if d.is_dir() and (d / "index.html").exists())
    if args.limit:
        projects = projects[: args.limit]

    manifest = args.output_dir / "sample_pipeline_results.jsonl"
    manifest.write_text("", encoding="utf-8")

    payloads = [
        (
            str(project),
            str(args.output_dir),
            args.browser_proxy or "",
            args.requests_proxy or "",
            args.max_pages,
            args.wait,
        )
        for project in projects
    ]

    print(f"Processing {len(payloads)} samples with concurrency={args.concurrency}", flush=True)
    results: list[dict[str, Any]] = []

    def record_result(i: int, result: dict[str, Any]) -> None:
        results.append(result)
        with manifest.open("a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
        print(
            f"[{i}/{len(payloads)}] {result['project']}: {result['status']} "
            f"(expand={result.get('expand_status')}, outputs={len(result.get('outputs', []))}, "
            f"{result.get('elapsed', 0)}s)",
            flush=True,
        )

    if args.site_timeout and args.site_timeout > 0:
        ctx = mp.get_context()
        pending = list(payloads)
        active: dict[mp.Process, tuple[tuple[str, str, str, str, int, int], float, mp.Queue]] = {}
        completed = 0

        def start_next() -> None:
            payload = pending.pop(0)
            result_queue = ctx.Queue(maxsize=1)
            proc = ctx.Process(target=process_sample_entry, args=(payload, result_queue))
            proc.start()
            active[proc] = (payload, time.time(), result_queue)

        while pending or active:
            while pending and len(active) < args.concurrency:
                start_next()

            for proc, (payload, started, result_queue) in list(active.items()):
                try:
                    result = result_queue.get_nowait()
                except queue.Empty:
                    result = None

                if result is not None:
                    proc.join(timeout=2)
                    active.pop(proc, None)
                    completed += 1
                    record_result(completed, result)
                    continue

                elapsed = time.time() - started
                if elapsed > args.site_timeout:
                    proc.terminate()
                    proc.join(timeout=5)
                    if proc.is_alive():
                        proc.kill()
                        proc.join(timeout=5)
                    cleanup_sample_outputs(payload)
                    active.pop(proc, None)
                    completed += 1
                    record_result(completed, timeout_result(payload, elapsed, args.site_timeout))
                elif not proc.is_alive():
                    proc.join(timeout=2)
                    active.pop(proc, None)
                    completed += 1
                    result = {
                        "project": Path(payload[0]).name,
                        "status": "worker_exited",
                        "expand_status": "worker_exited",
                        "outputs": [],
                        "errors": [{"stage": "sample", "error": "worker exited without result"}],
                        "elapsed": round(elapsed, 1),
                    }
                    record_result(completed, result)

            time.sleep(0.5)
    else:
        with ProcessPoolExecutor(max_workers=args.concurrency) as executor:
            futures = {executor.submit(process_sample, payload): payload for payload in payloads}
            for i, future in enumerate(as_completed(futures), 1):
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001
                    result = {
                        "project": Path(futures[future][0]).name,
                        "status": "error",
                        "error": f"{type(exc).__name__}: {exc}",
                        "outputs": [],
                    }
                record_result(i, result)

    statuses = Counter(r.get("status", "?") for r in results)
    expand_statuses = Counter(r.get("expand_status", "?") for r in results)
    outputs = sum(len(r.get("outputs", [])) for r in results)
    print(f"Done: statuses={dict(statuses)}, expand={dict(expand_statuses)}, outputs={outputs}", flush=True)


if __name__ == "__main__":
    main()
