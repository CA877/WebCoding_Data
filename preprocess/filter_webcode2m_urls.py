#!/usr/bin/env python3
"""Filter WebCode2M URL candidates toward likely real websites.

The raw extraction is intentionally broad and sorted, which front-loads many
numeric hosts, tracking domains, CDN assets, temporary hosting domains, and
path-like false positives. This script keeps a higher-quality crawl queue and
shuffles it deterministically so early crawl batches are representative.
"""

from __future__ import annotations

import argparse
import random
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse


BAD_SUBSTRINGS = (
    "google-analytics",
    "googletagmanager",
    "googlesyndication",
    "doubleclick",
    "adsense",
    "analytics",
    "counter",
    "free-counters",
    "mystat",
    "scorecardresearch",
    "serving-sys",
    "sitemeter",
    "cloudfront",
    "amazonaws",
    "blob.core",
    "azurewebsites",
    "githubusercontent",
    "wpengine.netdna",
    "netdna-ssl",
    "bp.blogspot",
    "blogspot.com",
    "imgur.com",
    "imagekit.io",
    "cloudinary.com",
    "staticflickr",
    "twimg.com",
    "gravatar.com",
    "wixstatic",
    "cdn.",
    "static.",
    "assets.",
    "media.",
    "images.",
    "image.",
    "img.",
    "fonts.",
    "jquery",
    "bootstrap",
    "paypal.com",
    "fandom.com",
    "hubspotusercontent",
    "photobucket",
    "akamai",
    "akamaihd",
    "imgix",
    "imageshack",
    "optimole",
    "alicdn",
    "aliyuncs",
    "digitaloceanspaces",
    "wpenginepowered",
    "shinyapps.io",
    "office.com",
    "slideplayer.com",
    "themeforest.net",
    "academia.edu",
    "libguides.",
    "docs.google",
)

BAD_SUFFIXES = (
    ".netsolhost.com",
    ".netsolstores.com",
    ".myftpupload.com",
    ".rcomhost.com",
    ".218hosting.com",
    ".nxcli.net",
    ".netdna-ssl.com",
    ".wpengine.com",
    ".wpenginepowered.com",
    ".hubspotusercontent-na1.net",
    ".herokuapp.com",
    ".blogspot.com",
    ".wordpress.com",
    ".s3.amazonaws.com",
)

GOOD_TLDS = {
    "com", "org", "net", "edu", "gov", "io", "co", "us", "uk", "ca", "au",
    "de", "fr", "nl", "ie", "in", "cn", "jp", "sg", "nz", "za", "eu",
}

GOOD_SUBDOMAINS = {
    "www", "blog", "news", "shop", "store", "support", "docs", "help",
    "learn", "events", "careers", "about", "community", "portal",
}


def registrable_parts(host: str) -> list[str]:
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in {"co", "com", "org", "net", "ac", "gov", "edu"}:
        return parts[-3:]
    return parts[-2:] if len(parts) >= 2 else parts


def looks_random(label: str) -> bool:
    if len(label) >= 12 and re.fullmatch(r"[a-f0-9]+", label):
        return True
    if len(label) >= 10:
        digits = sum(ch.isdigit() for ch in label)
        vowels = sum(ch in "aeiou" for ch in label.lower())
        if digits / len(label) > 0.45:
            return True
        if vowels <= 1 and re.fullmatch(r"[a-z0-9-]+", label):
            return True
    return False


def reject_reason(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower().strip(".")
    path = parsed.path or "/"
    if not host or "." not in host:
        return "invalid_host"
    if len(host) > 80:
        return "host_too_long"
    if "/" in host or "..." in host:
        return "malformed_host"
    if any(ch in host for ch in ("_", ")", "(", ",")):
        return "bad_host_chars"
    if path not in {"", "/"}:
        return "path_url"
    if any(s in host for s in BAD_SUBSTRINGS):
        return "noise_substring"
    if any(host.endswith(s) for s in BAD_SUFFIXES):
        return "hosting_suffix"
    parts = host.split(".")
    if len(parts) > 4:
        return "too_many_subdomains"
    if len(parts) == 3 and parts[0] not in GOOD_SUBDOMAINS and parts[-2] not in {
        "co", "com", "org", "net", "ac", "gov", "edu",
    }:
        return "untrusted_subdomain"
    tld = parts[-1]
    if tld not in GOOD_TLDS:
        return "low_priority_tld"
    core_parts = registrable_parts(host)
    core = core_parts[0]
    if core[:1].isdigit() and sum(ch.isdigit() for ch in core) >= 3:
        return "numeric_core"
    if looks_random(core):
        return "random_core"
    for label in parts[:-2]:
        if looks_random(label):
            return "random_subdomain"
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Filter WebCode2M URL candidates")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rejected-output", type=Path, default=None)
    parser.add_argument("--seed", type=int, default=20260531)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    urls = [line.strip() for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()]
    kept: list[str] = []
    rejected: list[tuple[str, str]] = []
    reasons = Counter()
    seen_hosts: set[str] = set()

    for url in urls:
        host = urlparse(url).netloc.lower().strip(".")
        if host in seen_hosts:
            reasons["duplicate_host"] += 1
            rejected.append((url, "duplicate_host"))
            continue
        seen_hosts.add(host)
        reason = reject_reason(url)
        if reason:
            reasons[reason] += 1
            rejected.append((url, reason))
        else:
            kept.append(url)

    random.Random(args.seed).shuffle(kept)
    if args.limit:
        kept = kept[: args.limit]

    args.output.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    if args.rejected_output:
        with args.rejected_output.open("w", encoding="utf-8") as f:
            for url, reason in rejected:
                f.write(f"{reason}\t{url}\n")

    print(f"input={len(urls)} kept={len(kept)} rejected={len(rejected)}")
    for reason, count in reasons.most_common():
        print(f"{reason}: {count}")


if __name__ == "__main__":
    main()
