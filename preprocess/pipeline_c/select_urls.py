#!/usr/bin/env python3
"""Create a traceable, statically safe candidate slice from WebCode2M URLs."""
from __future__ import annotations

import argparse
import random
import re
from pathlib import Path
from urllib.parse import urlparse


DENY = re.compile(r"porn|sex|escort|adult|casino|bet(?:ting)?|gambl|drug|cocaine|weapon|gun|xxx|cam", re.I)
HOSTING = re.compile(r"(?:netsolhost|netsolstores|rcomhost|myftpupload|wpengine|clickbank|blogspot|"
                     r"hosting|free-counters|mystat|nxcli|c-o-u-n-t)\.", re.I)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260715)
    args = parser.parse_args()
    selected: list[str] = []
    domains: set[str] = set()
    candidates = args.input.read_text(encoding="utf-8", errors="ignore").splitlines()
    random.Random(args.seed).shuffle(candidates)
    for raw in candidates:
        url = raw.strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            continue
        first_label = parsed.hostname.split(".")[0].removeprefix("www")
        if (DENY.search(url) or HOSTING.search(parsed.hostname) or parsed.hostname in domains
                or len(first_label) < 3 or sum(char.isdigit() for char in first_label) > 2):
            continue
        domains.add(parsed.hostname); selected.append(url)
        if len(selected) == args.limit:
            break
    if len(selected) < args.limit:
        raise SystemExit(f"only selected {len(selected)} URLs")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(selected) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
