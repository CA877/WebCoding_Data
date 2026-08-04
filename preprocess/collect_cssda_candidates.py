#!/usr/bin/env python3
"""Collect real nominee-site URLs from CSS Design Awards public gallery pages."""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup


EXCLUDED = {"cssdesignawards.com", "www.cssdesignawards.com", "linkedin.com", "www.linkedin.com"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pages", type=int, default=8)
    args = parser.parse_args()
    found: list[str] = []; domains: set[str] = set()
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/145 Safari/537.36"}
    with httpx.Client(timeout=20, verify=False, follow_redirects=True, headers=headers) as client:
        for number in range(1, args.pages + 1):
            response = client.get(f"https://www.cssdesignawards.com/wotd-award-nominees?page={number}")
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            for anchor in soup.select(".sp__meta a[href], .gallery-projects a[href]"):
                url = anchor.get("href", "")
                parsed = urlparse(url)
                if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                    continue
                host = parsed.hostname.lower()
                if host in EXCLUDED or host in domains:
                    continue
                domains.add(host); found.append(url)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(found) + "\n", encoding="utf-8")
    print(f"collected {len(found)} CSSDA nominee URLs")


if __name__ == "__main__":
    main()
