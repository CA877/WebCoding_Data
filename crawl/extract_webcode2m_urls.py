#!/usr/bin/env python3
"""Extract crawlable domain URLs from WebCode2M dataset via HuggingFace datasets-server API.

This script queries the HF datasets-server API in batches to extract domain URLs
from WebCode2M HTML samples. It filters for English/Chinese content and excludes
CDN/social media domains.

Output: A text file with one URL per line, suitable for playwright_crawl.py crawl mode.

Usage:
    # On server (needs proxy for HuggingFace):
    export ALL_PROXY=socks5h://127.0.0.1:13659
    python3 extract_webcode2m_urls.py --output urls.txt --max-rows 50000

    # Rate limit: datasets-server allows ~100 req/min, each returns 100 rows.
    # 50,000 rows = 500 requests = ~5 minutes.
    # Expected yield: ~35-40% of rows have usable domains = ~18,000 unique URLs.
"""

import argparse
import json
import re
import time
from collections import Counter
from pathlib import Path

import requests

# Domains to skip (CDNs, social media, generic services)
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

# Domains that are likely not real websites (hosting infra, etc.)
SKIP_PATTERNS = [
    r"\.s3\.", r"\.blob\.", r"\.azurewebsites\.", r"static\.",
    r"assets\.", r"media\.", r"img\.", r"images?\.", r"cdn\.",
]


def is_noise_domain(domain: str) -> bool:
    """Check if domain is a CDN/noise domain."""
    domain_lower = domain.lower()
    if any(n in domain_lower for n in NOISE_DOMAINS):
        return True
    if any(re.search(pat, domain_lower) for pat in SKIP_PATTERNS):
        return True
    return False


def extract_main_domain(html: str) -> str | None:
    """Extract the most likely 'main' domain from HTML content."""
    # Find all domains in the HTML
    domains = re.findall(r'https?://([^/\s"\'<>]+)', html)
    if not domains:
        return None

    # Filter noise
    real_domains = [d for d in domains if not is_noise_domain(d)]
    if not real_domains:
        return None

    # Most common non-noise domain is likely the site itself
    counts = Counter(real_domains)
    main_domain = counts.most_common(1)[0][0]

    # Basic validation: must have at least one dot, reasonable length
    if "." not in main_domain or len(main_domain) < 4 or len(main_domain) > 100:
        return None

    return main_domain


def fetch_rows(session: requests.Session, offset: int, length: int = 100) -> list[dict]:
    """Fetch rows from HF datasets-server API."""
    url = (
        f"https://datasets-server.huggingface.co/rows"
        f"?dataset=xcodemind/webcode2m&config=default&split=train"
        f"&offset={offset}&length={length}"
    )
    resp = session.get(url, timeout=30)
    if resp.status_code != 200:
        return []
    data = resp.json()
    return [r["row"] for r in data.get("rows", [])]


def main():
    parser = argparse.ArgumentParser(description="Extract URLs from WebCode2M")
    parser.add_argument("--output", default="webcode2m_urls.txt", help="Output file")
    parser.add_argument("--max-rows", type=int, default=50000, help="Max rows to scan")
    parser.add_argument("--batch-size", type=int, default=100, help="Rows per API call")
    parser.add_argument("--proxy", default="socks5h://127.0.0.1:13659", help="Proxy for requests")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay between requests (seconds)")
    args = parser.parse_args()

    session = requests.Session()
    if args.proxy:
        session.proxies = {"http": args.proxy, "https": args.proxy}
    session.headers["User-Agent"] = "Mozilla/5.0"

    domains_found: set[str] = set()
    total_processed = 0
    lang_stats = Counter()
    errors = 0

    print(f"Scanning WebCode2M (max {args.max_rows} rows, batch={args.batch_size})...")

    for offset in range(0, args.max_rows, args.batch_size):
        try:
            rows = fetch_rows(session, offset, args.batch_size)
        except Exception as e:
            errors += 1
            if errors > 10:
                print(f"Too many errors, stopping at offset {offset}")
                break
            time.sleep(2)
            continue

        if not rows:
            # May have reached end of dataset
            if offset > 0:
                print(f"No rows at offset {offset}, stopping.")
                break
            errors += 1
            continue

        for row in rows:
            total_processed += 1
            lang = row.get("lang", "")
            lang_stats[lang] += 1

            # Only keep English and Chinese
            if lang not in ("en", "zh"):
                continue

            text = row.get("text", "")
            if not text:
                continue

            domain = extract_main_domain(text)
            if domain:
                domains_found.add(domain)

        # Progress
        if (offset // args.batch_size) % 20 == 0:
            print(f"  offset={offset}, processed={total_processed}, "
                  f"domains={len(domains_found)}, errors={errors}")

        time.sleep(args.delay)

    # Write output
    urls = sorted(f"https://{d}/" for d in domains_found)
    Path(args.output).write_text("\n".join(urls) + "\n")

    print(f"\nDone!")
    print(f"  Rows processed: {total_processed}")
    print(f"  Languages: {lang_stats.most_common(5)}")
    print(f"  Unique domains extracted: {len(domains_found)}")
    print(f"  Output: {args.output}")


if __name__ == "__main__":
    main()
