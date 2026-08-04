#!/usr/bin/env python3
"""Extract diverse website URLs from Common Crawl Index.

Common Crawl indexes billions of pages. We query their CDX API to get
real, crawled URLs with paths (not just homepages).

Strategy:
- Query multiple TLDs and patterns to get diversity
- Filter for HTML pages (mime:text/html)
- Filter for English/Chinese content
- Deduplicate by domain (keep one URL per domain, preferring paths)
- Shuffle deterministically

Usage:
    export ALL_PROXY=socks5://127.0.0.1:13659
    python3 preprocess/extract_commoncrawl_urls.py --output cc_urls.txt --limit 50000

    # Use specific crawl index (default: latest)
    python3 preprocess/extract_commoncrawl_urls.py --output cc_urls.txt --index CC-MAIN-2025-18
"""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

import httpx

# ---------------------------------------------------------------------------
# Query patterns — diverse sampling across web
# ---------------------------------------------------------------------------

# Top-level queries to get diverse sites
QUERY_PATTERNS = [
    # By TLD — commercial sites
    "*.com/*",
    "*.org/*",
    "*.net/*",
    "*.io/*",
    "*.co/*",
    # Country TLDs
    "*.edu/*",
    "*.gov/*",
    "*.co.uk/*",
    "*.de/*",
    "*.fr/*",
    "*.ca/*",
    "*.com.au/*",
    "*.nl/*",
    # Specific path patterns (real content pages)
    "*.com/about*",
    "*.com/blog/*",
    "*.com/products/*",
    "*.com/services/*",
    "*.org/about*",
    "*.edu/academics*",
    "*.edu/research*",
    "*.com/portfolio*",
    "*.com/contact*",
    "*.com/team*",
    "*.com/pricing*",
    "*.com/features*",
]

# Domains to exclude (noise, not real websites)
EXCLUDE_DOMAINS = {
    "google.com", "facebook.com", "twitter.com", "youtube.com",
    "instagram.com", "linkedin.com", "pinterest.com", "reddit.com",
    "amazon.com", "ebay.com", "wikipedia.org", "wikimedia.org",
    "apple.com", "microsoft.com", "github.com", "stackoverflow.com",
    "wordpress.com", "blogspot.com", "tumblr.com", "medium.com",
    "tiktok.com", "whatsapp.com", "telegram.org",
    "cloudflare.com", "amazonaws.com", "googleapis.com",
    "godaddy.com", "squarespace.com", "wix.com", "shopify.com",
    "archive.org", "web.archive.org",
}

EXCLUDE_SUBSTRINGS = (
    "cdn.", "static.", "assets.", "media.", "img.", "images.",
    "api.", "mail.", "login.", "admin.", "cpanel.",
    "wp-content", "wp-admin", "wp-json",
    ".pdf", ".xml", ".json", ".rss", ".atom",
    "sitemap", "robots.txt", "favicon",
)


def is_good_url(url: str) -> bool:
    """Filter for URLs likely to be real, renderable web pages."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()

    # Exclude known noise domains
    domain_parts = host.split(".")
    registrable = ".".join(domain_parts[-2:]) if len(domain_parts) >= 2 else host
    if registrable in EXCLUDE_DOMAINS:
        return False

    # Exclude substrings
    if any(s in host or s in path for s in EXCLUDE_SUBSTRINGS):
        return False

    # Must have reasonable length
    if len(url) > 200 or len(host) > 80:
        return False

    # Exclude URLs with too many path segments (usually not interesting pages)
    if path.count("/") > 5:
        return False

    # Exclude obvious non-HTML paths
    if re.search(r'\.(js|css|jpg|jpeg|png|gif|svg|ico|woff|woff2|ttf|mp4|mp3|zip|tar|gz)$', path):
        return False

    # Exclude URLs with lots of query params (dynamic/tracking pages)
    if parsed.query and parsed.query.count("&") > 2:
        return False

    # Exclude numeric-heavy paths (usually pagination/IDs, not interesting standalone pages)
    path_parts = [p for p in path.split("/") if p]
    if path_parts:
        numeric_parts = sum(1 for p in path_parts if re.fullmatch(r'\d+', p))
        if numeric_parts > 1:
            return False

    return True


def query_cc_index(client: httpx.Client, index_url: str, pattern: str,
                   limit: int = 2000, page: int = 0) -> list[dict]:
    """Query Common Crawl CDX index API."""
    params = {
        "url": pattern,
        "output": "json",
        "limit": limit,
        "page": page,
        "filter": "mime:text/html",
        "fl": "url,status,languages",
    }
    try:
        resp = client.get(index_url, params=params, timeout=60)
        if resp.status_code != 200:
            return []
        lines = resp.text.strip().split("\n")
        results = []
        for line in lines:
            if not line.strip():
                continue
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return results
    except Exception as e:
        print(f"  Error querying {pattern}: {e}")
        return []


def get_available_indexes(client: httpx.Client) -> list[str]:
    """Get list of available CC indexes."""
    try:
        resp = client.get("https://index.commoncrawl.org/collinfo.json", timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            return [item["cdx-api"] for item in data]
    except Exception:
        pass
    return []


def main():
    parser = argparse.ArgumentParser(description="Extract URLs from Common Crawl Index")
    parser.add_argument("--output", type=Path, default=Path("cc_urls.txt"))
    parser.add_argument("--limit", type=int, default=50000,
                        help="Target number of unique URLs to collect")
    parser.add_argument("--per-query", type=int, default=3000,
                        help="Max results per query pattern")
    parser.add_argument("--index", default="",
                        help="CC index to use (e.g. CC-MAIN-2025-18). Empty=latest")
    parser.add_argument("--seed", type=int, default=20260609)
    parser.add_argument("--lang", nargs="*", default=["eng", "zho"],
                        help="Language filter (ISO 639-3 codes used by CC)")
    args = parser.parse_args()

    client = httpx.Client(timeout=60)

    # Determine index URL
    if args.index:
        index_url = f"https://index.commoncrawl.org/{args.index}-index"
    else:
        print("Fetching available indexes...")
        indexes = get_available_indexes(client)
        if indexes:
            index_url = indexes[0]  # Latest
            print(f"Using latest index: {index_url}")
        else:
            index_url = "https://index.commoncrawl.org/CC-MAIN-2025-18-index"
            print(f"Fallback index: {index_url}")

    # Collect URLs
    all_urls: dict[str, str] = {}  # domain -> best URL
    domain_urls: defaultdict[str, list[str]] = defaultdict(list)
    lang_set = set(args.lang) if args.lang else None

    print(f"Target: {args.limit} URLs")
    print(f"Languages: {args.lang}")
    print(f"Query patterns: {len(QUERY_PATTERNS)}")
    print()

    for i, pattern in enumerate(QUERY_PATTERNS):
        if len(all_urls) >= args.limit:
            break

        print(f"[{i+1}/{len(QUERY_PATTERNS)}] Querying: {pattern} ...", end=" ", flush=True)

        results = query_cc_index(client, index_url, pattern, limit=args.per_query)

        added = 0
        for record in results:
            url = record.get("url", "")
            status = record.get("status", "")
            languages = record.get("languages", "")

            # Only successful responses
            if status and status != "200":
                continue

            # Language filter
            if lang_set and languages:
                page_langs = set(languages.split(","))
                if not page_langs & lang_set:
                    continue

            if not is_good_url(url):
                continue

            # Deduplicate by domain — keep URL with path over homepage
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            domain_urls[domain].append(url)

            if domain not in all_urls:
                all_urls[domain] = url
                added += 1
            else:
                # Prefer URL with path over just "/"
                existing_path = urlparse(all_urls[domain]).path
                new_path = parsed.path
                if existing_path in ("", "/") and new_path not in ("", "/"):
                    all_urls[domain] = url

        print(f"+{added} (total: {len(all_urls)})")

        # Rate limit — be nice to CC servers
        time.sleep(1.5)

    # For domains with multiple URLs, pick the most interesting one
    # (longest path that's not too long — indicates real content page)
    for domain, urls in domain_urls.items():
        if len(urls) > 1:
            scored = []
            for u in urls:
                path = urlparse(u).path
                # Score: prefer paths with 2-3 segments, not too short, not too long
                segments = len([p for p in path.split("/") if p])
                if segments == 0:
                    score = 0
                elif segments <= 3:
                    score = segments * 10 + len(path)
                else:
                    score = 30 - segments  # penalize very deep paths
                scored.append((score, u))
            scored.sort(reverse=True)
            all_urls[domain] = scored[0][1]

    # Shuffle and write
    urls_list = list(all_urls.values())
    random.Random(args.seed).shuffle(urls_list)

    if len(urls_list) > args.limit:
        urls_list = urls_list[:args.limit]

    args.output.write_text("\n".join(urls_list) + "\n", encoding="utf-8")

    print(f"\nDone!")
    print(f"  Unique domains: {len(urls_list)}")
    print(f"  URLs with paths: {sum(1 for u in urls_list if urlparse(u).path not in ('', '/'))}")
    print(f"  Output: {args.output}")

    # Show sample
    print(f"\n  Sample URLs:")
    for u in urls_list[:15]:
        print(f"    {u}")


if __name__ == "__main__":
    main()
