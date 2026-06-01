#!/usr/bin/env python3
"""Postprocess WebCode2M crawl outputs.

This pass keeps the raw crawl manifest intact and writes a postprocessed
manifest next to it. It can quarantine challenge pages and remove invisible
analytics/tracking JavaScript from otherwise usable projects.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup


CHALLENGE_MARKERS = (
    "robot challenge screen",
    "checking the site connection security",
    "this page requires cookies to be enabled in your browser settings",
    "sgcaptcha",
    "powcaptcha",
    "cf-challenge",
    "checking if the site connection is secure",
    "verify you are human",
)

ANALYTICS_KEYWORDS = (
    "google-analytics",
    "googletagmanager",
    "googlesyndication",
    "gtag",
    "frontend-gtag",
    "monsterinsights",
    "analytics",
    "adsbygoogle",
    "doubleclick",
    "facebook",
    "fbq(",
    "hotjar",
    "mixpanel",
    "segment",
    "optimizely",
    "pinterest",
    "linkedin",
    "twitter",
    "tiktok",
)

ANALYTICS_DOMAINS = (
    "google-analytics.com",
    "googletagmanager.com",
    "googlesyndication.com",
    "doubleclick.net",
    "facebook.net",
    "connect.facebook.com",
    "hotjar.com",
    "mixpanel.com",
    "segment.com",
    "optimizely.com",
    "pinterest.com",
    "linkedin.com",
    "twitter.com",
    "tiktok.com",
)


def project_name_from_url(url: str) -> str:
    parsed = urlparse(url)
    return re.sub(r"[^A-Za-z0-9._-]", "_", parsed.netloc)[:60]


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def html_files(project_dir: Path) -> list[Path]:
    return sorted(project_dir.glob("*.html"))


def find_challenge_markers(project_dir: Path) -> list[str]:
    found: set[str] = set()
    for html_file in html_files(project_dir):
        text = html_file.read_text(encoding="utf-8", errors="replace").lower()
        for marker in CHALLENGE_MARKERS:
            if marker in text:
                found.add(marker)
    return sorted(found)


def script_is_analytics(script) -> bool:
    parts = [
        script.get("src", ""),
        script.get("id", ""),
        " ".join(script.get("class") or []),
        script.get("data-wpfc-render", ""),
        script.get("data-wp-strategy", ""),
        script.get_text("", strip=False),
    ]
    haystack = " ".join(str(part) for part in parts).lower()
    return any(domain in haystack for domain in ANALYTICS_DOMAINS) or any(
        keyword in haystack for keyword in ANALYTICS_KEYWORDS
    )


def local_script_path(project_dir: Path, src: str) -> Path | None:
    if not src or src.startswith(("http://", "https://", "//", "data:", "blob:", "javascript:")):
        return None
    candidate = (project_dir / src).resolve()
    try:
        candidate.relative_to(project_dir.resolve())
    except ValueError:
        return None
    return candidate if candidate.suffix == ".js" else None


def referenced_local_js(project_dir: Path) -> set[Path]:
    refs: set[Path] = set()
    for html_file in html_files(project_dir):
        soup = BeautifulSoup(html_file.read_text(encoding="utf-8", errors="replace"), "html.parser")
        for script in soup.find_all("script", src=True):
            path = local_script_path(project_dir, script.get("src", ""))
            if path:
                refs.add(path)
    return refs


def clean_analytics(project_dir: Path, dry_run: bool) -> dict:
    removed_scripts = 0
    candidate_js: set[Path] = set()

    for html_file in html_files(project_dir):
        soup = BeautifulSoup(html_file.read_text(encoding="utf-8", errors="replace"), "html.parser")
        changed = False
        for script in list(soup.find_all("script")):
            if not script_is_analytics(script):
                continue
            local_path = local_script_path(project_dir, script.get("src", ""))
            if local_path:
                candidate_js.add(local_path)
            script.decompose()
            removed_scripts += 1
            changed = True
        if changed and not dry_run:
            html_file.write_text(str(soup), encoding="utf-8")

    removed_js_files = 0
    if candidate_js:
        still_referenced = referenced_local_js(project_dir) if not dry_run else set()
        for js_path in candidate_js:
            if js_path.exists() and js_path not in still_referenced:
                removed_js_files += 1
                if not dry_run:
                    js_path.unlink()

    return {
        "removed_analytics_scripts": removed_scripts,
        "removed_analytics_js_files": removed_js_files,
    }


def quarantine_project(project_dir: Path, quarantine_dir: Path, dry_run: bool) -> str:
    target = quarantine_dir / project_dir.name
    if dry_run:
        return str(target)
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.move(str(project_dir), str(target))
    return str(target)


def main() -> None:
    parser = argparse.ArgumentParser(description="Postprocess WebCode2M crawl outputs")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--output-manifest", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--quarantine-dir", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    input_dir = args.input_dir
    manifest = args.manifest or input_dir / "crawl_results.jsonl"
    output_manifest = args.output_manifest or input_dir / "crawl_results.postprocessed.jsonl"
    report_path = args.report or input_dir / "postprocess_report.json"
    quarantine_dir = args.quarantine_dir or input_dir / "_rejected_challenge_pages"

    rows = load_jsonl(manifest)
    processed_rows: list[dict] = []
    summary = Counter()
    challenge_examples: list[dict] = []
    analytics_removed = Counter()

    for row in rows:
        updated = dict(row)
        status = row.get("status")
        if status in {"single_page", "multi_page"}:
            project_dir = input_dir / project_name_from_url(row.get("url", ""))
            markers = find_challenge_markers(project_dir) if project_dir.exists() else []
            if markers:
                updated["status"] = "challenge_page"
                updated["postprocess_original_status"] = status
                updated["challenge_markers"] = markers
                updated["has_single_page"] = False
                updated["has_multi_page"] = False
                updated["quarantine_path"] = quarantine_project(project_dir, quarantine_dir, args.dry_run)
                summary["challenge_page"] += 1
                if len(challenge_examples) < 20:
                    challenge_examples.append(
                        {"url": row.get("url"), "project": project_dir.name, "markers": markers}
                    )
            elif project_dir.exists():
                cleaned = clean_analytics(project_dir, args.dry_run)
                analytics_removed.update(cleaned)
                summary[status] += 1
            else:
                summary[status] += 1
        else:
            summary[status or "unknown"] += 1
        processed_rows.append(updated)

    if not args.dry_run:
        write_jsonl(output_manifest, processed_rows)

    report = {
        "input_dir": str(input_dir),
        "manifest": str(manifest),
        "output_manifest": str(output_manifest),
        "dry_run": args.dry_run,
        "summary": dict(summary),
        "analytics_removed": dict(analytics_removed),
        "challenge_examples": challenge_examples,
    }
    if not args.dry_run:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
