#!/usr/bin/env python3
"""Direct WebCode2M crawler: save final DOM exactly as the browser exposes it."""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import hashlib
import json
import multiprocessing as mp
from pathlib import Path
import shutil
import time
from typing import Any

from playwright.sync_api import sync_playwright

from preprocess.pipeline_c.qwen_token_gate import count_project_tokens


def project_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]


def completed_source_urls(manifest: Path) -> set[str]:
    completed: set[str] = set()
    if not manifest.is_file():
        return completed
    for line in manifest.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("quality_status") == "retryable":
            continue
        if row.get("source_url"):
            completed.add(str(row["source_url"]))
    return completed


def completed_pass_count(manifest: Path) -> int:
    """Count latest successful rows so a resumed target is cumulative."""
    latest: dict[str, str] = {}
    if not manifest.is_file():
        return 0
    for line in manifest.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("source_url"):
            latest[str(row["source_url"])] = str(row.get("status", ""))
    return sum(status == "pass" for status in latest.values())


def crawl_one(url: str, output: Path, browser_proxy: str, wait_ms: int,
              tokenizer: Path, max_code_tokens: int) -> dict[str, Any]:
    started = time.monotonic()
    pid = project_id(url)
    target = output / "projects" / pid
    temporary = output / "projects" / f".{pid}.partial"
    shutil.rmtree(temporary, ignore_errors=True)
    temporary.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                proxy={"server": browser_proxy} if browser_proxy else None,
            )
            context = browser.new_context(viewport={"width": 1280, "height": 800}, ignore_https_errors=True)
            page = context.new_page()
            response = page.goto(url, wait_until="commit", timeout=30_000)
            if response is None or response.status >= 400:
                raise RuntimeError(f"navigation_failed:{response.status if response else 'no_response'}")
            page.wait_for_timeout(wait_ms)
            html = page.content()
            final_url = page.url
            status_code = response.status
            browser.close()
        (temporary / "index.html").write_text(html, encoding="utf-8")
        code_tokens = count_project_tokens(temporary, tokenizer)
        if code_tokens > max_code_tokens:
            shutil.rmtree(temporary, ignore_errors=True)
            shutil.rmtree(target, ignore_errors=True)
            return {
                "source_url": url,
                "final_url": final_url,
                "project_id": pid,
                "status": "token_rejected",
                "quality_status": "reject",
                "reason": f"qwen_code_tokens_over_limit:{code_tokens}>{max_code_tokens}",
                "code_tokens": code_tokens,
                "max_code_tokens": max_code_tokens,
                "html_bytes": len(html.encode("utf-8")),
                "elapsed_seconds": round(time.monotonic() - started, 3),
            }
        metadata = {
            "source_url": url,
            "final_url": final_url,
            "http_status": status_code,
            "capture": "playwright_final_dom",
            "resource_policy": "preserve_all_references_unchanged",
            "code_tokens": code_tokens,
            "max_code_tokens": max_code_tokens,
        }
        (temporary / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        shutil.rmtree(target, ignore_errors=True)
        temporary.rename(target)
        return {
            **metadata,
            "project_id": pid,
            "status": "pass",
            "quality_status": "unfiltered",
            "html_bytes": len(html.encode("utf-8")),
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    except Exception as exc:
        shutil.rmtree(temporary, ignore_errors=True)
        return {
            "source_url": url,
            "project_id": pid,
            "status": "crawl_failed",
            "quality_status": "retryable",
            "reason": f"{type(exc).__name__}:{exc}",
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }


def _entry(url: str, output: str, browser_proxy: str, wait_ms: int,
           tokenizer: str, max_code_tokens: int, queue: Any) -> None:
    queue.put(crawl_one(url, Path(output), browser_proxy, wait_ms, Path(tokenizer), max_code_tokens))


def crawl_with_timeout(url: str, output: Path, browser_proxy: str, wait_ms: int, site_timeout: int,
                       tokenizer: Path, max_code_tokens: int) -> dict[str, Any]:
    context = mp.get_context("spawn")
    queue = context.Queue(maxsize=1)
    process = context.Process(
        target=_entry,
        args=(url, str(output), browser_proxy, wait_ms, str(tokenizer), max_code_tokens, queue),
    )
    process.start()
    process.join(site_timeout)
    if process.is_alive():
        process.kill()
        process.join(timeout=5)
        return {
            "source_url": url,
            "project_id": project_id(url),
            "status": "site_timeout",
            "quality_status": "retryable",
            "reason": f"site_timeout:{site_timeout}s",
        }
    try:
        return queue.get(timeout=1)
    except Exception:
        return {
            "source_url": url,
            "project_id": project_id(url),
            "status": "worker_exited",
            "quality_status": "retryable",
            "reason": f"worker_exit_code:{process.exitcode}",
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline D: direct final-DOM crawler with no rewriting or quality gates")
    parser.add_argument("--urls", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser-proxy", default="")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--wait-ms", type=int, default=3000)
    parser.add_argument("--site-timeout", type=int, default=120)
    parser.add_argument("--qwen-tokenizer", type=Path, required=True)
    parser.add_argument("--max-code-tokens", type=int, default=40_000)
    parser.add_argument("--target-passes", type=int, default=0,
                        help="Stop after this many <=40K projects; 0 processes all URLs")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()
    if args.workers < 1 or args.site_timeout < 1 or args.max_code_tokens < 1 or args.target_passes < 0:
        parser.error("workers, site-timeout and max-code-tokens must be positive; target-passes cannot be negative")
    if not args.qwen_tokenizer.is_file():
        parser.error(f"Qwen tokenizer does not exist: {args.qwen_tokenizer}")

    urls = [line.strip() for line in args.urls.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.limit:
        urls = urls[: args.limit]
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = args.output / "manifest.jsonl"
    existing_passes = completed_pass_count(manifest)
    if args.resume:
        done = completed_source_urls(manifest)
        urls = [url for url in urls if url not in done]
        print(f"resume: skipped={len(done)} remaining={len(urls)}", flush=True)
    if args.target_passes and existing_passes >= args.target_passes:
        print(f"target already met: pass={existing_passes} target={args.target_passes}", flush=True)
        return
    config = {
        "pipeline": "D",
        "input_urls": str(args.urls),
        "workers": args.workers,
        "wait_ms": args.wait_ms,
        "site_timeout": args.site_timeout,
        "browser_proxy": args.browser_proxy,
        "capture": "playwright_final_dom",
        "resource_policy": "preserve_all_references_unchanged",
        "quality_gates": [f"qwen_exact_tokens<={args.max_code_tokens}"],
        "qwen_tokenizer": str(args.qwen_tokenizer),
        "max_code_tokens": args.max_code_tokens,
        "target_passes": args.target_passes,
    }
    (args.output / "run_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

    with manifest.open("a", encoding="utf-8") as handle, ThreadPoolExecutor(max_workers=args.workers) as pool:
        source = iter(enumerate(urls, 1))
        pending = {}
        passes = existing_passes

        def submit_one() -> bool:
            try:
                index, url = next(source)
            except StopIteration:
                return False
            future = pool.submit(
                crawl_with_timeout, url, args.output, args.browser_proxy, args.wait_ms, args.site_timeout,
                args.qwen_tokenizer, args.max_code_tokens)
            pending[future] = (index, url)
            return True

        for _ in range(args.workers):
            if not submit_one():
                break
        completed = 0
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                index, url = pending.pop(future)
                try:
                    row = future.result()
                except Exception as exc:
                    row = {"source_url": url, "status": "worker_error", "quality_status": "retryable", "reason": repr(exc)}
                completed += 1
                passes += int(row.get("status") == "pass")
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                print(f"[{completed}/{len(urls)}; input={index}; pass={passes}] {url}: {row['status']}", flush=True)
            target_met = bool(args.target_passes and passes >= args.target_passes)
            if not target_met:
                while len(pending) < args.workers and submit_one():
                    pass
            elif not pending:
                break


if __name__ == "__main__":
    main()
