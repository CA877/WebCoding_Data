#!/usr/bin/env python3
"""Cluster surviving sites by normalized index-page DOM structure."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from bs4 import BeautifulSoup


def structure_digest(index: Path) -> tuple[str, int]:
    soup = BeautifulSoup(index.read_text(encoding="utf-8", errors="replace"), "html.parser")
    tokens = []
    for tag in soup.find_all(True):
        classes = sorted(
            re.sub(r"\d+", "#", value.lower())
            for value in (tag.get("class") or [])
            if len(value) <= 80
        )
        tokens.append(tag.name + ("." + ".".join(classes) if classes else ""))
    signature = "|".join(tokens)
    return hashlib.sha256(signature.encode()).hexdigest(), len(tokens)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-group", type=int, default=2)
    args = parser.parse_args()
    groups: dict[tuple[str, int], list[str]] = defaultdict(list)
    for number, site in enumerate(sorted(p for p in args.root.iterdir() if p.is_dir()), 1):
        index = site / "index.html"
        if index.is_file():
            digest, tags = structure_digest(index)
            groups[(digest, tags)].append(site.name)
        if number % 2000 == 0:
            print(f"[{number}]", flush=True)
    rows = [
        {"digest": digest, "tag_count": tags, "size": len(sites), "sites": sites}
        for (digest, tags), sites in groups.items() if len(sites) >= args.min_group
    ]
    rows.sort(key=lambda row: (-row["size"], row["digest"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    print(json.dumps({"groups": len(rows), "clustered_sites": sum(row["size"] for row in rows),
                      "largest": rows[0]["size"] if rows else 0}))


if __name__ == "__main__":
    main()
