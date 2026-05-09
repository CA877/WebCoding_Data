"""
Batch collect renderable web pages from GitHub repositories.

Searches GitHub API for high-star frontend projects, clones them,
finds index.html entry points, validates rendering with Playwright,
and saves passing pages to an output directory.

Usage:
    # Small test run
    python -m data_pipeline.github_collect \
        --output_dir data_pipeline/output/github_pages \
        --manifest data_pipeline/output/github_manifest.jsonl \
        --min_stars 50 --limit 5

    # Full run
    python -m data_pipeline.github_collect \
        --output_dir data_pipeline/output/github_pages \
        --manifest data_pipeline/output/github_manifest.jsonl \
        --min_stars 5 --limit 0
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import requests

from .common import append_jsonl, load_env
from .validate_render import validate_directory


# ---------------------------------------------------------------------------
# GitHub API client
# ---------------------------------------------------------------------------

class GitHubAPI:
    BASE = "https://api.github.com"

    def __init__(self, token: str | None = None):
        self.session = requests.Session()
        self.session.headers["Accept"] = "application/vnd.github.v3+json"
        self.session.headers["User-Agent"] = "webcompass-data-collector"
        if token:
            self.session.headers["Authorization"] = f"token {token}"

    def _request(self, url: str, params: dict | None = None) -> requests.Response:
        """Make a rate-limit-aware request with retries."""
        for attempt in range(4):
            resp = self.session.get(url, params=params, timeout=30)

            # Check rate limit
            remaining = int(resp.headers.get("X-RateLimit-Remaining", 1))
            if remaining == 0:
                reset_ts = int(resp.headers.get("X-RateLimit-Reset", 0))
                wait = max(reset_ts - int(time.time()), 1) + 2
                print(f"  [RATE LIMIT] Waiting {wait}s...")
                time.sleep(wait)
                if resp.status_code == 403:
                    continue  # retry after wait

            if resp.status_code == 200:
                return resp

            if resp.status_code == 422:
                # Validation error (e.g., bad query)
                print(f"  [API ERROR] 422: {resp.json().get('message', '')}")
                return resp

            if resp.status_code in (403, 429, 500, 502, 503):
                wait = 2 ** attempt * 5
                print(f"  [RETRY] {resp.status_code}, waiting {wait}s (attempt {attempt+1}/4)")
                time.sleep(wait)
                continue

            return resp

        return resp

    def search_repos(self, query: str, sort: str = "stars",
                     per_page: int = 100, max_pages: int = 10):
        """Search repositories, yielding repo dicts. Max 1000 results per query."""
        for page in range(1, max_pages + 1):
            resp = self._request(
                f"{self.BASE}/search/repositories",
                params={"q": query, "sort": sort, "per_page": per_page, "page": page},
            )
            if resp.status_code != 200:
                break

            data = resp.json()
            items = data.get("items", [])
            if not items:
                break

            for repo in items:
                yield repo

            # Stop if we've fetched all results
            if len(items) < per_page:
                break

            # Small delay between pages to be polite
            time.sleep(1)


# ---------------------------------------------------------------------------
# Search queries
# ---------------------------------------------------------------------------

def build_search_queries(min_stars: int) -> list[str]:
    """Build diverse search queries with star-range splits to bypass 1000 limit."""

    # Star ranges — finer splits for ranges with many repos
    if min_stars <= 10:
        star_ranges = [
            "5..6", "7..8", "9..10",
            "10..12", "13..15", "16..20",
            "20..30", "31..50",
            "50..100", "100..200", "200..500", "500..1000", ">1000",
        ]
    elif min_stars <= 50:
        star_ranges = [
            f"{min_stars}..100", "100..200", "200..500", "500..1000", ">1000",
        ]
    else:
        star_ranges = [
            f"{min_stars}..200", "200..500", "500..1000", ">1000",
        ]

    queries = []
    for sr in star_ranges:
        queries.append(f"language:HTML stars:{sr} fork:false")

    # Topic-specific queries (supplement)
    topics = [
        "portfolio", "landing-page", "website-template", "html-template",
        "personal-website", "github-pages", "html-css-javascript",
        "responsive-website", "bootstrap-template", "static-site",
        "website", "html-css", "web-design",
    ]
    for topic in topics:
        queries.append(f"language:HTML stars:>{max(min_stars, 5)} topic:{topic}")

    return queries


# ---------------------------------------------------------------------------
# Repo filtering
# ---------------------------------------------------------------------------

SKIP_KEYWORDS = {
    "framework", "library", "sdk", "cli", "plugin", "package",
    "npm", "webpack", "babel", "eslint", "prettier",
    "node", "deno", "tutorial", "course", "learn",
    "awesome", "cheatsheet", "interview",
    "blog", "documentation",
}

def should_clone(repo: dict) -> tuple[bool, str]:
    """Check if a repo is worth cloning. Returns (should_clone, skip_reason)."""
    if repo.get("size", 0) > 100_000:  # > 100MB
        return False, "too_large"
    if repo.get("archived"):
        return False, "archived"
    if repo.get("fork"):
        return False, "fork"

    name_desc = (repo.get("name", "") + " " + (repo.get("description") or "")).lower()
    for kw in SKIP_KEYWORDS:
        if kw in name_desc.split():  # Match whole words only
            return False, f"keyword:{kw}"

    lang = (repo.get("language") or "").lower()
    if lang not in ("html", "css", "javascript", "typescript", "scss", ""):
        return False, f"language:{lang}"

    return True, ""


# ---------------------------------------------------------------------------
# HTML entry point discovery
# ---------------------------------------------------------------------------

SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", "vendor", "test", "tests",
    "spec", "examples", ".github", ".vscode", "coverage",
}

def find_html_entry_points(repo_dir: str) -> list[str]:
    """Find directories containing index.html."""
    entry_points = []
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if "index.html" in files:
            entry_points.append(root)
    return entry_points


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------

MAX_ENTRY_POINTS = 5  # Skip repos with too many index.html (blog sites etc.)


def process_repo(
    repo_info: dict,
    output_dir: str,
) -> dict:
    """Clone repo, find HTML pages, validate, copy passing ones.

    Returns dict with pages_found, pages_passed, page_ids.
    """
    clone_url = repo_info["clone_url"]
    repo_name = repo_info["full_name"].replace("/", "_")

    tmpdir = tempfile.mkdtemp(prefix="gh_collect_")
    try:
        # Clone
        proc = subprocess.run(
            ["git", "clone", "--depth", "1", clone_url, tmpdir],
            capture_output=True, text=True, timeout=120,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Clone failed: {proc.stderr[:200]}")

        # Find entry points
        entry_points = find_html_entry_points(tmpdir)
        if not entry_points:
            return {"pages_found": 0, "pages_passed": 0, "page_ids": []}

        # Skip repos with too many pages (blogs, docs sites)
        if len(entry_points) > MAX_ENTRY_POINTS:
            print(f"    [SKIP] {len(entry_points)} entry points (likely blog/docs, max={MAX_ENTRY_POINTS})")
            return {"pages_found": len(entry_points), "pages_passed": 0, "page_ids": []}

        pages_passed = 0
        page_ids = []

        for entry_dir in entry_points:
            rel_path = os.path.relpath(entry_dir, tmpdir)
            if rel_path == ".":
                page_id = repo_name
            else:
                page_id = f"{repo_name}__{rel_path.replace('/', '_')}"

            # Skip if already exists in output
            dest = os.path.join(output_dir, page_id)
            if os.path.exists(dest):
                pages_passed += 1
                page_ids.append(page_id)
                continue

            # Validate
            result = validate_directory(entry_dir)
            if not result.get("passed"):
                errors = result.get("console_errors", [])
                print(f"    [FAIL] {rel_path}/ body={result.get('body_text_length', 0)} errors={len(errors)}")
                continue

            # Copy to output
            shutil.copytree(entry_dir, dest, dirs_exist_ok=True)
            # Remove validation screenshot from copy
            screenshot = os.path.join(dest, "_validation_screenshot.png")
            if os.path.exists(screenshot):
                os.remove(screenshot)

            pages_passed += 1
            page_ids.append(page_id)
            print(f"    [PASS] {rel_path}/ body={result.get('body_text_length', 0)}")

        return {
            "pages_found": len(entry_points),
            "pages_passed": pages_passed,
            "page_ids": page_ids,
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Resume support
# ---------------------------------------------------------------------------

def load_processed_repos(manifest_path: str) -> set[str]:
    """Load already-processed repo full_names from manifest."""
    processed = set()
    if not os.path.exists(manifest_path):
        return processed
    with open(manifest_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                processed.add(obj["repo_full_name"])
            except (json.JSONDecodeError, KeyError):
                continue
    return processed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Collect renderable web pages from GitHub repos"
    )
    parser.add_argument(
        "--output_dir", default="data_pipeline/output/github_pages",
        help="Directory to store validated page directories",
    )
    parser.add_argument(
        "--manifest", default="data_pipeline/output/github_manifest.jsonl",
        help="Manifest JSONL tracking all processed repos",
    )
    parser.add_argument(
        "--limit", type=int, default=100,
        help="Max repos to process (0 = unlimited)",
    )
    parser.add_argument(
        "--min_stars", type=int, default=50,
        help="Minimum stars filter for search queries",
    )
    parser.add_argument(
        "--max_pages_per_query", type=int, default=10,
        help="Max pages to fetch per search query (100 repos/page)",
    )
    args = parser.parse_args()

    # Setup
    load_env()
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Warning: No GITHUB_TOKEN found. Rate limits will be very low.")
    api = GitHubAPI(token=token)

    os.makedirs(args.output_dir, exist_ok=True)
    processed = load_processed_repos(args.manifest)
    print(f"Resuming: {len(processed)} repos already processed")

    # Phase 1: Search and collect unique candidate repos
    print("\n=== Phase 1: Searching GitHub ===")
    queries = build_search_queries(args.min_stars)
    print(f"Using {len(queries)} search queries")

    seen_repos = {}  # full_name -> repo dict
    for i, query in enumerate(queries):
        print(f"\n[{i+1}/{len(queries)}] {query}")
        count = 0
        for repo in api.search_repos(query, max_pages=args.max_pages_per_query):
            full_name = repo["full_name"]
            if full_name not in seen_repos and full_name not in processed:
                seen_repos[full_name] = repo
                count += 1
        print(f"  -> {count} new repos")

        # Check if we have enough candidates
        if args.limit > 0 and len(seen_repos) >= args.limit * 3:
            print(f"  Enough candidates ({len(seen_repos)}), stopping search")
            break

    # Sort by stars descending
    candidates = sorted(seen_repos.values(), key=lambda r: r["stargazers_count"], reverse=True)
    print(f"\nTotal unique candidates: {len(candidates)}")

    # Phase 2: Clone, validate, collect
    print("\n=== Phase 2: Clone and Validate ===")
    total_processed = 0
    total_passed = 0
    total_pages = 0
    limit = args.limit if args.limit > 0 else len(candidates)

    for repo_info in candidates:
        if total_processed >= limit:
            break

        name = repo_info["full_name"]
        stars = repo_info["stargazers_count"]
        size_kb = repo_info.get("size", 0)

        # Pre-clone filter
        ok, reason = should_clone(repo_info)
        if not ok:
            print(f"[SKIP] {name} ({reason})")
            append_jsonl(args.manifest, {
                "repo_full_name": name,
                "stars": stars,
                "status": "skipped",
                "skip_reason": reason,
                "timestamp": datetime.now().isoformat(),
            })
            processed.add(name)
            continue

        total_processed += 1
        print(f"\n[{total_processed}/{limit}] {name} ({stars} stars, {size_kb}KB)")

        try:
            result = process_repo(repo_info, args.output_dir)
            status = "ok"
            error = None
        except Exception as e:
            print(f"  [ERROR] {e}")
            result = {"pages_found": 0, "pages_passed": 0, "page_ids": []}
            status = "error"
            error = str(e)[:200]

        # Write manifest entry
        append_jsonl(args.manifest, {
            "repo_full_name": name,
            "repo_url": repo_info.get("html_url", ""),
            "stars": stars,
            "size_kb": size_kb,
            "description": (repo_info.get("description") or "")[:200],
            "pages_found": result["pages_found"],
            "pages_passed": result["pages_passed"],
            "page_ids": result["page_ids"],
            "status": status,
            "error": error,
            "timestamp": datetime.now().isoformat(),
        })
        processed.add(name)

        total_passed += result["pages_passed"]
        total_pages += result["pages_found"]

    # Summary
    print(f"\n=== Summary ===")
    print(f"Repos processed: {total_processed}")
    print(f"Pages found: {total_pages}")
    print(f"Pages passed validation: {total_passed}")
    print(f"Output directory: {args.output_dir}")
    print(f"Manifest: {args.manifest}")


if __name__ == "__main__":
    main()
