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


def _copy_fresh(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def process_sample(payload: tuple[str, str, str, str, int, int, bool]) -> dict[str, Any]:
    """Process one URL: crawl → postprocess.

    Output:
    - Always produces single_page/{project}/ (1 sample) if crawl succeeds.
    - If crawl is multi_page, also produces multi_page/{project}/ (+1 sample).
    """
    url, output_root, browser_proxy, requests_proxy, max_pages, wait_ms, code_resources_only = payload
    output_dir = Path(output_root)
    single_root = output_dir / "single_page"
    multi_root = output_dir / "multi_page"
    quarantine_dir = output_dir / "quarantined"
    crawl_tmp_root = output_dir / "_crawl_tmp"
    single_root.mkdir(parents=True, exist_ok=True)
    multi_root.mkdir(parents=True, exist_ok=True)
    crawl_tmp_root.mkdir(parents=True, exist_ok=True)

    proj_name = project_name_from_url(url)
    tmp_dir = crawl_tmp_root / proj_name
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)

    started = time.time()
    result: dict[str, Any] = {
        "url": url,
        "project": proj_name,
        "status": "ok",
        "crawl_status": None,
        "crawl_result": {},
        "outputs": [],
        "postprocess": {},
        "errors": [],
    }

    session = build_requests_session(requests_proxy)

    # --- Step 1: Crawl to temp directory ---
    with sync_playwright() as p:
        browser = p.chromium.launch(
            proxy={"server": browser_proxy} if browser_proxy else None,
        )
        try:
            crawl_result = crawl_site(
                url, tmp_dir, browser, session,
                max_pages=max_pages, wait_ms=wait_ms,
                code_resources_only=code_resources_only,
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

    # --- Step 2: Distribute to single_page / multi_page ---
    crawl_ok = crawl_result.get("status") in ("single_page", "multi_page")
    if not crawl_ok or not (tmp_dir / "index.html").exists():
        result["status"] = crawl_result.get("status", "error")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        result["elapsed"] = round(time.time() - started, 1)
        return result

    # --- Step 2a: Challenge detection (before copying) ---
    try:
        markers = find_challenge_markers(tmp_dir)
        if markers:
            quarantine_project(tmp_dir, quarantine_dir, dry_run=False)
            result["status"] = "challenge_page"
            result["postprocess"]["challenge_markers"] = markers
            result["elapsed"] = round(time.time() - started, 1)
            return result
    except Exception as exc:  # noqa: BLE001
        result["errors"].append({"stage": "challenge_check", "error": f"{type(exc).__name__}: {exc}"})

    # --- Step 2b: Analytics removal on temp ---
    try:
        analytics_result = clean_analytics(tmp_dir, dry_run=False)
        result["postprocess"]["analytics_removed"] = analytics_result
    except Exception as exc:  # noqa: BLE001
        result["errors"].append({"stage": "clean_analytics", "error": f"{type(exc).__name__}: {exc}"})

    # --- Step 3: Copy to single_page/ (always) ---
    single_out = single_root / proj_name
    try:
        _copy_fresh(tmp_dir, single_out)
        result["outputs"].append({
            "variant": "single",
            "path": str(single_out),
        })
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(single_out, ignore_errors=True)
        result["errors"].append({"stage": "copy_single", "error": f"{type(exc).__name__}: {exc}"})

    # --- Step 4: Also copy to multi_page/ if crawl was multi_page ---
    crawl_is_multi = crawl_result.get("status") == "multi_page"
    if crawl_is_multi:
        multi_out = multi_root / proj_name
        try:
            _copy_fresh(tmp_dir, multi_out)
            result["outputs"].append({
                "variant": "multi",
                "path": str(multi_out),
                "pages": crawl_result.get("pages", 0),
            })
        except Exception as exc:  # noqa: BLE001
            shutil.rmtree(multi_out, ignore_errors=True)
            result["errors"].append({"stage": "copy_multi", "error": f"{type(exc).__name__}: {exc}"})

    # Clean up temp
    shutil.rmtree(tmp_dir, ignore_errors=True)

    if result["errors"] and result["status"] == "ok":
        result["status"] = "partial"
    result["elapsed"] = round(time.time() - started, 1)
    return result


def process_sample_entry(payload: tuple[str, str, str, str, int, int, bool],
                         result_queue: mp.Queue) -> None:
    result_queue.put(process_sample(payload))


def timeout_result(payload: tuple[str, str, str, str, int, int, bool],
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


def cleanup_sample_outputs(payload: tuple[str, str, str, str, int, int, bool]) -> None:
    url = payload[0]
    output_dir = Path(payload[1])
    proj_name = project_name_from_url(url)
    shutil.rmtree(output_dir / "_crawl_tmp" / proj_name, ignore_errors=True)
    shutil.rmtree(output_dir / "single_page" / proj_name, ignore_errors=True)
    shutil.rmtree(output_dir / "multi_page" / proj_name, ignore_errors=True)


def load_done_urls(manifest: Path, output_dir: Path) -> set[str]:
    done_urls: set[str] = set()
    if not manifest.exists():
        return done_urls

    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        url = entry.get("url", "")
        project = entry.get("project") or project_name_from_url(url)
        # URL is "done" if single_page output exists
        if url and (output_dir / "single_page" / project / "index.html").exists():
            done_urls.add(url)
    return done_urls


def existing_crawl_result(url: str, output_dir: Path) -> dict[str, Any] | None:
    project = project_name_from_url(url)
    outputs: list[dict[str, Any]] = []
    for variant, root_name in [("single", "single_page"), ("multi", "multi_page")]:
        out_path = output_dir / root_name / project
        if (out_path / "index.html").exists():
            html_count = len(list(out_path.glob("*.html")))
            outputs.append({
                "variant": variant,
                "path": str(out_path),
                "pages": html_count,
            })
    if not outputs:
        return None
    return {
        "url": url,
        "project": project,
        "status": "existing_output",
        "crawl_status": "existing_output",
        "crawl_result": {"status": "existing_output", "reused_from_disk": True},
        "outputs": outputs,
        "postprocess": {},
        "errors": [],
        "elapsed": 0,
    }


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
        "--code-resources-only",
        action="store_true",
        help="Do not fetch or store non-code resources; keep only HTML plus JS/CSS.",
    )
    parser.add_argument(
        "--site-timeout", type=int, default=0,
        help="Hard wall-clock timeout per sample in seconds.",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    single_root = args.output_dir / "single_page"
    multi_root = args.output_dir / "multi_page"
    if args.overwrite:
        shutil.rmtree(single_root, ignore_errors=True)
        shutil.rmtree(multi_root, ignore_errors=True)
        shutil.rmtree(args.output_dir / "_crawl_tmp", ignore_errors=True)
    single_root.mkdir(parents=True, exist_ok=True)
    multi_root.mkdir(parents=True, exist_ok=True)

    # --- Load URLs ---
    urls = [line.strip() for line in args.url_file.read_text().splitlines() if line.strip()]
    if args.limit:
        urls = urls[:args.limit]

    # --- Resume support ---
    manifest = args.output_dir / "pipeline_b_results.jsonl"
    done_urls = set()
    if args.overwrite:
        manifest.write_text("", encoding="utf-8")
    else:
        if not manifest.exists():
            manifest.write_text("", encoding="utf-8")
        done_urls = load_done_urls(manifest, args.output_dir)
        recovered = []
        for url in urls:
            if url in done_urls:
                continue
            result = existing_crawl_result(url, args.output_dir)
            if result is not None:
                recovered.append(result)
                done_urls.add(url)
        if recovered:
            with manifest.open("a", encoding="utf-8") as f:
                for result in recovered:
                    f.write(json.dumps(result, ensure_ascii=False) + "\n")
            print(f"Recovered {len(recovered)} existing crawled projects into manifest", flush=True)
        if done_urls:
            print(f"Resuming: {len(done_urls)} URLs already processed, skipping")

    payloads = [
        (url, str(args.output_dir), args.browser_proxy or "", args.requests_proxy or "",
         args.max_pages, args.wait, args.code_resources_only)
        for url in urls if url not in done_urls
    ]

    total = len(payloads)
    total_inputs = len(urls)
    initial_done = len(done_urls)
    print(
        f"Processing {total} URLs with concurrency={args.concurrency}; "
        f"resume_done={initial_done}, total_inputs={total_inputs}",
        flush=True,
    )
    results: list[dict[str, Any]] = []
    progress_statuses: Counter[str] = Counter({"resumed": initial_done})
    sample_count = initial_done
    failed_count = 0

    def record_result(i: int, result: dict[str, Any]) -> None:
        nonlocal sample_count, failed_count
        results.append(result)
        with manifest.open("a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
        status = result.get("status", "?")
        progress_statuses[status] += 1
        outputs_count = len(result.get("outputs", []))
        if outputs_count > 0:
            sample_count += outputs_count  # single=1, single+multi=2
        else:
            failed_count += 1
        overall_done = initial_done + i
        success_rate = sample_count / (sample_count + failed_count) if (sample_count + failed_count) else 0.0
        print(
            f"[{i}/{total}] {result['project']}: {result['status']} "
            f"(crawl={result.get('crawl_status')}, samples={outputs_count}, "
            f"{result.get('elapsed', 0)}s) "
            f"progress={overall_done}/{total_inputs} samples={sample_count} "
            f"failed={failed_count} success_rate={success_rate:.2%} "
            f"statuses={dict(progress_statuses)}",
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
    total_outputs = sum(len(r.get("outputs", [])) for r in results)
    single_count = sum(1 for r in results for o in r.get("outputs", []) if o.get("variant") == "single")
    multi_count = sum(1 for r in results for o in r.get("outputs", []) if o.get("variant") == "multi")
    print(f"\nDone: statuses={dict(statuses)}, crawl={dict(crawl_statuses)}, "
          f"total_samples={total_outputs} (single={single_count}, multi={multi_count})", flush=True)


if __name__ == "__main__":
    main()
