#!/usr/bin/env python3
"""Fetch the HF file manifest (size + LFS sha256) for a dataset repo.

Reads HF_ENDPOINT (default https://hf-mirror.com) and optional HTTP(S)_PROXY
from the environment. Writes {path: {"size": int, "sha256": str|None}}.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import httpx

DEFAULT_ENDPOINT = "https://hf-mirror.com"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", required=True, help="HF dataset repo id, e.g. lxpp/all_merged_instructions")
    ap.add_argument("--revision", default="main")
    ap.add_argument("--out", required=True, type=os.fspath)
    ap.add_argument("--endpoint", default=os.environ.get("HF_ENDPOINT", DEFAULT_ENDPOINT))
    args = ap.parse_args()

    url = f"{args.endpoint.rstrip('/')}/api/datasets/{args.repo}/tree/{args.revision}?recursive=true"
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        resp = client.get(url)
        if resp.status_code != 200:
            print(f"ERROR: {url} -> HTTP {resp.status_code}", file=sys.stderr)
            print(resp.text[:500], file=sys.stderr)
            return 2
        entries = resp.json()

    manifest = {}
    for entry in entries:
        if entry.get("type") != "file":
            continue
        path = entry["path"]
        lfs = entry.get("lfs") or {}
        manifest[path] = {
            "size": entry.get("size"),
            "sha256": lfs.get("oid"),
            "lfs": bool(lfs),
        }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
    print(f"fetched {len(manifest)} files from {url}")
    for path, meta in sorted(manifest.items()):
        print(f"  {path}: size={meta['size']} lfs={meta['lfs']} sha256={'yes' if meta['sha256'] else 'no'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
