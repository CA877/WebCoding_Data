#!/usr/bin/env python3
"""Sample-level Pipeline B preprocessing for WebCode2M.

For each input URL:
1. Crawl the site with Playwright (multi-page).
2. Postprocess: detect challenge pages, remove analytics scripts.

This integrates crawl + postprocess into a single per-sample flow,
matching the architecture of pipeline_a_sample_level.py.
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

from playwright_crawl import build_requests_session, crawl_site
from postprocess_webcode2m_crawl import (
    clean_analytics,
    find_challenge_markers,
    project_name_from_url,
    quarantine_project,
)


def process_sample(payload: tuple[str, str, str, str, int, int]) -> dict[str, Any]:
    """Process one URL: crawl → postprocess."""
    url, output_root, browser_proxy, requests_proxy, max_pages, wait_ms = payload
    output_dir = Path(output_root)
    crawl_root = output_dir / "crawled"
    quarantine_dir = output_dir / "quarantined"
    crawl_root.mkdir(parents=True, exist_ok=True)

    proj_name = project_name_from_url(url)
    proj_dir = crawl_root / proj_name

    started = time.time()
    result: dict[str, Any] = {
        "url": url,
        "project": proj_name,
        "status": "ok",
        "crawl_status": None,
        "crawl_result": {},
        "postprocess": {},
        "errors": [],
    }

    session = build_requests_session(requests_proxy)

    # --- Step 1: Crawl ---
    with sync_playwright() as p:
        browser = p.chromium.launch(
            proxy={"server": browser_proxy} if browser_proxy else None,
        )
        try:
            crawl_result = crawl_site(
                url, proj_dir, browser, session,
                max_pages=max_pages, wait_ms=wait_ms,
            )
        except Exception as exc:  # noqa: BLE001
            crawl_result = {
                "status": "error",
                "url": url,
                "error": f"{type(exc).__name__}: {exc}",
            }
        finally:
            browser.close()

    result["crawl_status"] = crawl_result.get("status")
    result["crawl_result"] = crawl_result

    # Only postprocess if crawl produced usable content
    if crawl_result.get("status") in ("single_page", "multi_page"):
        # --- Step 2a: Challenge detection ---
        try:
            markers = find_challenge_markers(proj_dir)
            if markers:
                quarantine_project(proj_dir, quarantine_dir, dry_run=False)
                result["status"] = "challenge_page"
                result["postprocess"]["challenge_markers"] = markers
                result["elapsed"] = round(time.time() - started, 1)
                return result
        except Exception as exc:  # noqa: BLE001
            result["errors"].append({"stage": "challenge_check", "error": f"{type(exc).__name__}: {exc}"})

        # --- Step 2b: Analytics removal ---
        try:
            analytics_result = clean_analytics(proj_dir, dry_run=False)
            result["postprocess"]["analytics_removed"] = analytics_result
        except Exception as exc:  # noqa: BLE001
            result["errors"].append({"stage": "clean_analytics", "error": f"{type(exc).__name__}: {exc}"})
    else:
        # Crawl failed — propagate crawl status as overall status
        result["status"] = crawl_result.get("status", "error")

    if result["errors"] and result["status"] == "ok":
        result["status"] = "partial"
    result["elapsed"] = round(time.time() - started, 1)
    return result


def process_sample_entry(payload: tuple[str, str, str, str, int, int],
                         result_queue: mp.Queue) -> None:
    result_queue.put(process_sample(payload))


def timeout_result(payload: tuple[str, str, str, str, int, int],
                   elapsed: float, site_timeout: int) -> dict[str, Any]:
    url = payload[0]
    return {
        "url": url,
        "project": project_name_from_url(url),
        "status": "site_timeout",
        "crawl_status": "site_timeout",
        "crawl_result": {},
        "postprocess": {},
        "errors": [{"stage": "sample", "error": f"site_timeout after {site_timeout}s"}],
        "elapsed": round(elapsed, 1),
        "site_timeout": site_timeout,
    }


def cleanup_sample_outputs(payload: tuple[str, str, str, str, int, int]) -> None:
    url = payload[0]
    output_dir = Path(payload[1])
    proj_name = project_name_from_url(url)
    shutil.rmtree(output_dir / "crawled" / proj_name, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run sample-level Pipeline B: crawl → postprocess",
    )
    parser.add_argument("--url-file", type=Path, required=True,
                        help="URL list file (one URL per line, e.g. preflight output)")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--max-pages", type=int, default=7)
    parser.add_argument("--wait", type=int, default=3000)
    parser.add_argument("--browser-proxy", default="")
    parser.add_argument("--requests-proxy", default="")
    parser.add_argument(
        "--site-timeout", type=int, default=0,
        help="Hard wall-clock timeout per sample in seconds.",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    crawl_root = args.output_dir / "crawled"
    if args.overwrite:
        shutil.rmtree(crawl_root, ignore_errors=True)
    crawl_root.mkdir(parents=True, exist_ok=True)

    # --- Load URLs ---
    urls = [line.strip() for line in args.url_file.read_text().splitlines() if line.strip()]
    if args.limit:
        urls = urls[:args.limit]

    # --- Resume support ---
    manifest = args.output_dir / "pipeline_b_results.jsonl"
    done_urls: set[str] = set()
    if manifest.exists() and not args.overwrite:
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    entry = json.loads(line)
                    done_urls.add(entry.get("url", ""))
                except json.JSONDecodeError:
                    pass
        if done_urls:
            print(f"Resuming: {len(done_urls)} URLs already processed, skipping")
    else:
        manifest.write_text("", encoding="utf-8")

    payloads = [
        (url, str(args.output_dir), args.browser_proxy or "", args.requests_proxy or "",
         args.max_pages, args.wait)
        for url in urls if url not in done_urls
    ]

    total = len(payloads)
    print(f"Processing {total} URLs with concurrency={args.concurrency}", flush=True)
    results: list[dict[str, Any]] = []

    def record_result(i: int, result: dict[str, Any]) -> None:
        results.append(result)
        with manifest.open("a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
        print(
            f"[{i}/{total}] {result['project']}: {result['status']} "
            f"(crawl={result.get('crawl_status')}, {result.get('elapsed', 0)}s)",
            flush=True,
        )

    if args.site_timeout and args.site_timeout > 0:
        ctx = mp.get_context()
        pending = list(payloads)
        active: dict[mp.Process, tuple[tuple, float, mp.Queue]] = {}
        completed = 0

        def start_next() -> None:
            payload = pending.pop(0)
            result_queue = ctx.Queue(maxsize=1)
            proc = ctx.Process(target=process_sample_entry,
                               args=(payload, result_queue))
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
                        "url": payload[0],
                        "project": project_name_from_url(payload[0]),
                        "status": "worker_exited",
                        "crawl_status": "worker_exited",
                        "crawl_result": {},
                        "postprocess": {},
                        "errors": [{"stage": "sample", "error": "worker exited without result"}],
                        "elapsed": round(elapsed, 1),
                    }
                    record_result(completed, result)

            time.sleep(0.5)
    else:
        with ProcessPoolExecutor(max_workers=args.concurrency) as executor:
            futures = {executor.submit(process_sample, p): p for p in payloads}
            for i, future in enumerate(as_completed(futures), 1):
                try:
                    result = future.result(timeout=300)
                except TimeoutError:
                    result = {
                        "url": futures[future][0],
                        "project": project_name_from_url(futures[future][0]),
                        "status": "future_timeout",
                        "crawl_result": {},
                        "postprocess": {},
                        "errors": [{"stage": "sample", "error": "future.result() timeout"}],
                    }
                except Exception as exc:  # noqa: BLE001
                    result = {
                        "url": futures[future][0],
                        "project": project_name_from_url(futures[future][0]),
                        "status": "error",
                        "crawl_result": {},
                        "postprocess": {},
                        "errors": [{"stage": "sample", "error": f"{type(exc).__name__}: {exc}"}],
                    }
                record_result(i, result)

    statuses = Counter(r.get("status", "?") for r in results)
    crawl_statuses = Counter(r.get("crawl_status", "?") for r in results)
    print(f"\nDone: statuses={dict(statuses)}, crawl={dict(crawl_statuses)}", flush=True)


if __name__ == "__main__":
    main()
