#!/usr/bin/env python3
"""Run Pipeline C checks independently for a URL list with hard per-site limits."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
from pathlib import Path


def check_one(url: str, output: str, proxy: str, wait_ms: int, timeout: int) -> dict:
    code = (
        "import json, os; from pathlib import Path; from preprocess.pipeline_c.main import crawl_one; "
        "print(json.dumps(crawl_one(os.environ['PIPELINE_C_URL'], Path(os.environ['PIPELINE_C_OUTPUT']), "
        "os.environ['PIPELINE_C_PROXY'], int(os.environ['PIPELINE_C_WAIT']))))"
    )
    env = os.environ | {"PIPELINE_C_URL": url, "PIPELINE_C_OUTPUT": output,
                        "PIPELINE_C_PROXY": proxy, "PIPELINE_C_WAIT": str(wait_ms)}
    try:
        done = subprocess.run([sys.executable, "-c", code], cwd=Path.cwd(), env=env,
                              capture_output=True, text=True, timeout=timeout)
        if done.returncode != 0:
            return {"source_url": url, "status": "worker_exited", "quality_status": "retryable",
                    "reason": done.stderr[-1000:]}
        return json.loads(done.stdout)
    except subprocess.TimeoutExpired:
        return {"source_url": url, "status": "site_timeout", "quality_status": "retryable",
                "reason": f"site_timeout:{timeout}s"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--urls", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser-proxy", default="")
    parser.add_argument("--wait-ms", type=int, default=2500)
    parser.add_argument("--site-timeout", type=int, default=60)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()
    urls = [line.strip() for line in args.urls.read_text().splitlines() if line.strip()]
    args.output.mkdir(parents=True, exist_ok=True)
    config = {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()}
    config |= {"urls": str(args.urls), "count": len(urls)}
    (args.output / "run_config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2))
    manifest = args.output / "preprocess_manifest.jsonl"
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool, manifest.open("w") as handle:
        futures = {pool.submit(check_one, url, str(args.output), args.browser_proxy, args.wait_ms, args.site_timeout): url for url in urls}
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            row = future.result()
            handle.write(json.dumps(row, ensure_ascii=False) + "\n"); handle.flush()
            print(f"[{index}/{len(urls)}] {row['source_url']}: {row['status']}", flush=True)


if __name__ == "__main__":
    main()
