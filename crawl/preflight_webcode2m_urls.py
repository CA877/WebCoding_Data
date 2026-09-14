#!/usr/bin/env python3
"""Cheap HTTP preflight for WebCode2M crawl candidates.

This script runs before the expensive Playwright crawl. It fetches only the
homepage HTML with requests, rejects obvious dead/challenge/parked/resource
pages, and writes a higher-quality URL queue for the browser crawler.
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import json
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.8,zh-CN;q=0.7,zh;q=0.6",
}

CHALLENGE_MARKERS = (
    "robot challenge screen",
    "checking the site connection security",
    "checking if the site connection is secure",
    "verify you are human",
    "just a moment...",
    "cf-challenge",
    "sgcaptcha",
    "powcaptcha",
    "access denied",
    "enable javascript and cookies",
)

PARKED_MARKERS = (
    "this domain is for sale",
    "buy this domain",
    "domain parking",
    "parked free",
    "sedo domain parking",
    "afternic",
    "hugedomains.com",
    "namecheap parking",
    "godaddy.com/domainsearch",
    "related searches",
)

DEAD_MARKERS = (
    "apache2 ubuntu default page",
    "iis windows server",
    "index of /",
    "site not found",
    "website coming soon",
    "coming soon",
    "under construction",
    "account suspended",
    "service unavailable",
    "the page cannot be displayed",
    "there has been a critical error on this website",
)

HTML_HINT_RE = re.compile(r"<\s*(html|head|body|main|section|div|p|h1|h2|nav)\b", re.I)
TEXT_RE = re.compile(r"<[^>]+>")


@dataclass
class PreflightResult:
    url: str
    accepted: bool
    reason: str
    status_code: int | None = None
    final_url: str | None = None
    content_type: str | None = None
    bytes_read: int = 0
    text_chars: int = 0
    elapsed_sec: float = 0.0
    marker: str | None = None
    error: str | None = None


def proxy_config(proxy: str) -> dict[str, str] | None:
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


def read_limited(response: requests.Response, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=16384):
        if not chunk:
            continue
        remaining = max_bytes - total
        if remaining <= 0:
            break
        chunks.append(chunk[:remaining])
        total += len(chunks[-1])
    return b"".join(chunks)


def visible_text_chars(html: str) -> int:
    text = TEXT_RE.sub(" ", html)
    text = re.sub(r"\s+", " ", text)
    return len(text.strip())


def find_marker(text: str, markers: tuple[str, ...]) -> str | None:
    lower = text.lower()
    for marker in markers:
        if marker in lower:
            return marker
    return None


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme:
        return url.strip()
    return f"https://{url.strip()}"


def check_url(
    url: str,
    proxy: str,
    timeout: float,
    max_bytes: int,
    min_text_chars: int,
) -> PreflightResult:
    started = time.monotonic()
    normalized = normalize_url(url)
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        response = session.get(
            normalized,
            allow_redirects=True,
            timeout=timeout,
            proxies=proxy_config(proxy),
            stream=True,
        )
        body = read_limited(response, max_bytes)
        elapsed = time.monotonic() - started
        content_type = response.headers.get("content-type", "").lower()
        final_url = response.url
        html = body.decode(response.encoding or "utf-8", errors="replace")
        text_chars = visible_text_chars(html)

        result = PreflightResult(
            url=normalized,
            accepted=False,
            reason="unknown",
            status_code=response.status_code,
            final_url=final_url,
            content_type=content_type,
            bytes_read=len(body),
            text_chars=text_chars,
            elapsed_sec=round(elapsed, 3),
        )

        if response.status_code >= 400:
            result.reason = f"http_{response.status_code}"
            return result
        if content_type and not any(token in content_type for token in ("html", "xml", "text/plain")):
            result.reason = "non_html_content_type"
            return result
        if not HTML_HINT_RE.search(html):
            result.reason = "html_hint_missing"
            return result

        marker = find_marker(html, CHALLENGE_MARKERS)
        if marker:
            result.reason = "challenge_page"
            result.marker = marker
            return result
        marker = find_marker(html, PARKED_MARKERS)
        if marker:
            result.reason = "parked_page"
            result.marker = marker
            return result
        marker = find_marker(html, DEAD_MARKERS)
        if marker:
            result.reason = "dead_page"
            result.marker = marker
            return result
        if text_chars < min_text_chars:
            result.reason = "too_little_text"
            return result

        result.accepted = True
        result.reason = "accepted"
        return result
    except requests.RequestException as exc:
        elapsed = time.monotonic() - started
        return PreflightResult(
            url=normalized,
            accepted=False,
            reason="request_error",
            elapsed_sec=round(elapsed, 3),
            error=exc.__class__.__name__,
        )


def iter_urls(path: Path, limit: int | None) -> list[str]:
    urls = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return urls[:limit] if limit else urls


def main() -> None:
    parser = argparse.ArgumentParser(description="HTTP preflight WebCode2M URL candidates")
    parser.add_argument("--input", type=Path, required=True, help="Input URL list")
    parser.add_argument("--accepted-output", type=Path, required=True, help="Passed URL output")
    parser.add_argument("--rejected-output", type=Path, required=True, help="Rejected JSONL output")
    parser.add_argument("--report", type=Path, default=None, help="Summary JSON output")
    parser.add_argument("--proxy", default="", help="HTTP/SOCKS proxy for requests")
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--max-bytes", type=int, default=524288)
    parser.add_argument("--min-text-chars", type=int, default=120)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    urls = iter_urls(args.input, args.limit)
    args.accepted_output.parent.mkdir(parents=True, exist_ok=True)
    args.rejected_output.parent.mkdir(parents=True, exist_ok=True)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)

    accepted: list[str] = []
    reasons = Counter()
    started = time.monotonic()

    with args.accepted_output.open("w", encoding="utf-8") as accepted_f, args.rejected_output.open(
        "w", encoding="utf-8"
    ) as rejected_f:
        with futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            future_map = {
                executor.submit(
                    check_url,
                    url,
                    args.proxy,
                    args.timeout,
                    args.max_bytes,
                    args.min_text_chars,
                ): url
                for url in urls
            }
            for i, future in enumerate(futures.as_completed(future_map), 1):
                result = future.result()
                reasons[result.reason] += 1
                if result.accepted:
                    accepted_url = result.final_url or result.url
                    accepted.append(accepted_url)
                    accepted_f.write(accepted_url + "\n")
                    accepted_f.flush()
                else:
                    rejected_f.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
                if i % 500 == 0:
                    print(
                        f"checked={i}/{len(urls)} accepted={len(accepted)} "
                        f"rate={len(accepted)/i:.3f} reasons={dict(reasons.most_common(5))}",
                        flush=True,
                    )

    elapsed = time.monotonic() - started
    report = {
        "input": str(args.input),
        "accepted_output": str(args.accepted_output),
        "rejected_output": str(args.rejected_output),
        "checked": len(urls),
        "accepted": len(accepted),
        "rejected": len(urls) - len(accepted),
        "accepted_rate": round(len(accepted) / len(urls), 4) if urls else 0.0,
        "elapsed_sec": round(elapsed, 3),
        "urls_per_sec": round(len(urls) / elapsed, 3) if elapsed else 0.0,
        "reasons": dict(reasons.most_common()),
    }
    if args.report:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
