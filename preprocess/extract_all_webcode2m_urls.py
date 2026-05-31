#!/usr/bin/env python3
"""Extract ALL domain URLs from WebCode2M dataset via DuckDB column projection.

Uses DuckDB's httpfs extension to read ONLY the text+lang columns from remote
parquet files (HTTP range requests → ~1-2MB per file instead of ~570MB).

Usage:
    export HF_ENDPOINT=https://hf-mirror.com   # optional, defaults to mirror
    python3 preprocess/extract_all_webcode2m_urls.py --output webcode2m_all_urls.txt

    # Resume after interruption:
    python3 preprocess/extract_all_webcode2m_urls.py --output webcode2m_all_urls.txt

    # Keep all languages:
    python3 preprocess/extract_all_webcode2m_urls.py --lang-filter --output all_urls.txt

Expected: ~3.17M rows across 2065 parquet files.
Each file: ~7s with column projection → ~4h serial, ~1h with 4 workers.
"""

import argparse
import json
import os
import re
import signal
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import duckdb

# ── Domain filtering ──────────────────────────────────────────────────────────

NOISE_DOMAINS = {
    "google", "facebook", "twitter", "cdn", "fonts.g", "jquery",
    "bootstrap", "cloudflare", "gstatic", "w3.org", "schema.org",
    "gravatar", "youtube", "flickr", "blogblog", "blogger",
    "wordpress.com", "wp.com", "linkedin", "pinterest", "instagram",
    "amazonaws", "cloudfront", "github", "githubusercontent",
    "vimeo", "typekit", "fontawesome", "unpkg", "jsdelivr",
    "staticflickr", "wixstatic", "squarespace", "shopify",
    "googleapis", "googlesyndication", "googletagmanager",
    "doubleclick", "adsense", "analytics", "recaptcha",
}

SKIP_PATTERNS = re.compile(
    r"\.s3\.|\.blob\.|\.azurewebsites\.|static\.|assets\.|media\.|img\.|images?\.|cdn\."
)

DOMAIN_RE = re.compile(r'https?://([^/\s"\'<>]+)')


def is_noise_domain(domain: str) -> bool:
    dl = domain.lower()
    if any(n in dl for n in NOISE_DOMAINS):
        return True
    if SKIP_PATTERNS.search(dl):
        return True
    return False


def extract_main_domain(html: str) -> str | None:
    domains = DOMAIN_RE.findall(html)
    if not domains:
        return None
    real = [d for d in domains if not is_noise_domain(d)]
    if not real:
        return None
    main = Counter(real).most_common(1)[0][0]
    if "." not in main or len(main) < 4 or len(main) > 100:
        return None
    return main


def process_parquet_file(url: str, lang_filter: set[str] | None
                         ) -> tuple[set[str], Counter, int]:
    """Read one remote parquet file via DuckDB (column projection), extract domains."""
    con = duckdb.connect()
    con.execute("LOAD httpfs;")
    rows = con.execute(f"SELECT text, lang FROM read_parquet('{url}')").fetchall()
    con.close()

    domains = set()
    lang_stats = Counter()
    for text, lang in rows:
        lang_stats[lang] += 1
        if lang_filter and lang not in lang_filter:
            continue
        if not text:
            continue
        d = extract_main_domain(text)
        if d:
            domains.add(d)
    return domains, lang_stats, len(rows)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Extract ALL URLs from WebCode2M")
    parser.add_argument("--output", default="webcode2m_all_urls.txt")
    parser.add_argument("--lang-filter", nargs="*", default=["en", "zh"],
                        help="Languages to keep (default: en zh). Pass nothing for all.")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--checkpoint", default="webcode2m_urls_checkpoint.json")
    args = parser.parse_args()

    hf_base = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com")
    lang_filter = set(args.lang_filter) if args.lang_filter else None

    # Install httpfs once
    con = duckdb.connect()
    con.execute("INSTALL httpfs;")
    con.close()

    # Get parquet file list from HF API
    print("Fetching parquet file list...")
    from huggingface_hub import HfApi
    api = HfApi()
    info = api.dataset_info("xcodemind/webcode2m")
    parquet_names = sorted(
        s.rfilename for s in info.siblings if s.rfilename.endswith(".parquet")
    )
    print(f"Found {len(parquet_names)} parquet files")

    # Build URLs via resolve endpoint (DuckDB follows redirects)
    file_urls = {
        name: f"{hf_base}/datasets/xcodemind/webcode2m/resolve/main/{name}"
        for name in parquet_names
    }

    # Resume from checkpoint
    ckpt_path = Path(args.checkpoint)
    all_domains: set[str] = set()
    completed_files: set[str] = set()
    if ckpt_path.exists():
        ckpt = json.loads(ckpt_path.read_text())
        completed_files = set(ckpt.get("completed", []))
        all_domains = set(ckpt.get("domains", []))
        print(f"Resuming: {len(completed_files)} files done, {len(all_domains)} domains")

    remaining = [n for n in parquet_names if n not in completed_files]
    print(f"Remaining: {len(remaining)} files")

    if not remaining:
        print("All files already processed!")
        _write_output(args.output, all_domains)
        return

    # Graceful interrupt
    interrupted = False
    def handle_signal(sig, frame):
        nonlocal interrupted
        interrupted = True
        print("\nInterrupted! Will save checkpoint after current batch...")
    signal.signal(signal.SIGINT, handle_signal)

    all_lang_stats = Counter()
    total_rows = 0
    start = time.time()
    files_done = len(completed_files)
    errors = 0

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        remaining_idx = 0
        futures = {}

        # Fill the pool
        while remaining_idx < len(remaining) and len(futures) < args.concurrency * 2:
            name = remaining[remaining_idx]
            remaining_idx += 1
            f = pool.submit(process_parquet_file, file_urls[name], lang_filter)
            futures[f] = name

        while futures and not interrupted:
            # Wait for any one future to complete
            done_set = set()
            for f in list(futures):
                if f.done():
                    done_set.add(f)
            if not done_set:
                # Busy-wait briefly
                time.sleep(0.1)
                continue

            for future in done_set:
                name = futures.pop(future)
                try:
                    domains, lang_stats, nrows = future.result()
                    all_domains.update(domains)
                    all_lang_stats += lang_stats
                    total_rows += nrows
                    files_done += 1
                    completed_files.add(name)

                    elapsed = time.time() - start
                    processed_this_run = files_done - (len(parquet_names) - len(remaining))
                    if processed_this_run > 0:
                        rate = processed_this_run / elapsed
                        files_left = len(parquet_names) - files_done
                        eta = files_left / rate
                    else:
                        eta = 0
                    print(f"  [{files_done}/{len(parquet_names)}] {name}  "
                          f"+{len(domains)} domains  total={len(all_domains):,}  "
                          f"rows={total_rows:,}  "
                          f"ETA={eta/60:.0f}min")

                except Exception as e:
                    errors += 1
                    print(f"  ERROR [{errors}] {name}: {e}")
                    if errors > 20:
                        print("Too many errors, saving and stopping.")
                        interrupted = True

                # Checkpoint every 50 files
                if files_done % 50 == 0:
                    _save_checkpoint(ckpt_path, completed_files, all_domains)

                # Submit next
                if remaining_idx < len(remaining) and not interrupted:
                    next_name = remaining[remaining_idx]
                    remaining_idx += 1
                    f = pool.submit(process_parquet_file, file_urls[next_name], lang_filter)
                    futures[f] = next_name

    # Final save
    _save_checkpoint(ckpt_path, completed_files, all_domains)
    _write_output(args.output, all_domains)

    elapsed = time.time() - start
    print(f"\n{'Interrupted' if interrupted else 'Done'}!")
    print(f"  Files: {files_done}/{len(parquet_names)}, Errors: {errors}")
    print(f"  Rows: {total_rows:,}")
    print(f"  Languages: {all_lang_stats.most_common(10)}")
    print(f"  Unique domains: {len(all_domains):,}")
    print(f"  Time: {elapsed/60:.1f}min")
    print(f"  Output: {args.output}")

    if not interrupted and files_done == len(parquet_names):
        ckpt_path.unlink(missing_ok=True)
        print("  Checkpoint removed (completed)")


def _save_checkpoint(path: Path, files: set[str], domains: set[str]):
    data = {"completed": sorted(files), "domains": sorted(domains)}
    path.write_text(json.dumps(data))
    print(f"  [checkpoint] {len(files)} files, {len(domains)} domains saved")


def _write_output(path: str, domains: set[str]):
    urls = sorted(f"https://{d}/" for d in domains)
    Path(path).write_text("\n".join(urls) + "\n")
    print(f"  Written {len(urls)} URLs to {path}")


if __name__ == "__main__":
    main()
