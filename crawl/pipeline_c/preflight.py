#!/usr/bin/env python3
"""Cheap HTTP preflight before expensive Pipeline C browser crawling."""
from __future__ import annotations

import argparse
import asyncio
import random
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx


DENY = re.compile(r"porn|sex|escort|adult|casino|bet(?:ting)?|gambl|drug|cocaine|weapon|gun|xxx|cam", re.I)
HOSTING = re.compile(r"(?:netsolhost|netsolstores|rcomhost|myftpupload|wpengine|clickbank|blogspot|"
                     r"hosting|free-counters|mystat|nxcli|c-o-u-n-t)\.", re.I)
CHALLENGE = re.compile(r"verify you are human|checking your browser|just a moment|captcha|cf-challenge|access denied", re.I)


def static_candidates(urls: list[str], seed: int) -> list[str]:
    random.Random(seed).shuffle(urls)
    domains: set[str] = set(); selected: list[str] = []
    for raw in urls:
        url = raw.strip(); parsed = urlparse(url)
        label = (parsed.hostname or "").removeprefix("www.").split(".")[0]
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.hostname in domains
                or DENY.search(url) or HOSTING.search(parsed.hostname) or len(label) < 3
                or sum(char.isdigit() for char in label) > 2):
            continue
        domains.add(parsed.hostname); selected.append(url)
    return selected


async def check(client: httpx.AsyncClient, url: str, semaphore: asyncio.Semaphore) -> str | None:
    async with semaphore:
        try:
            response = await client.get(url, follow_redirects=True, headers={"Range": "bytes=0-65535"})
            content_type = response.headers.get("content-type", "").lower()
            text = response.text[:20_000]
            if response.status_code < 400 and "html" in content_type and len(text) >= 3000 and not CHALLENGE.search(text):
                return str(response.url)
        except (httpx.HTTPError, UnicodeError):
            pass
    return None


async def run(args) -> list[str]:
    candidates = static_candidates(args.input.read_text(encoding="utf-8", errors="ignore").splitlines(), args.seed)
    candidates = candidates[:args.scan_limit]
    semaphore = asyncio.Semaphore(args.concurrency)
    timeout = httpx.Timeout(args.timeout, connect=min(args.timeout, 10))
    async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
        accepted: list[str] = []
        for start in range(0, len(candidates), args.concurrency * 4):
            rows = await asyncio.gather(*(check(client, url, semaphore) for url in candidates[start:start + args.concurrency * 4]))
            for url in rows:
                if url and url not in accepted:
                    accepted.append(url)
                    if len(accepted) >= args.limit:
                        return accepted
        return accepted


def main() -> None:
    parser = argparse.ArgumentParser(description="HTTP filter for Pipeline C candidates.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=160, help="Number of browser candidates to output")
    parser.add_argument("--scan-limit", type=int, default=5000)
    parser.add_argument("--concurrency", type=int, default=30)
    parser.add_argument("--timeout", type=float, default=12)
    parser.add_argument("--seed", type=int, default=20260715)
    args = parser.parse_args()
    accepted = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(accepted) + ("\n" if accepted else ""), encoding="utf-8")
    print(f"preflight accepted {len(accepted)} URLs")


if __name__ == "__main__":
    main()
