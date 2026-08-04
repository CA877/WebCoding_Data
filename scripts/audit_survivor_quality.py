#!/usr/bin/env python3
"""Broad second-pass quality audit for surviving legacy multi-page sites.

This pass is deliberately report-only.  It extracts page and screenshot signals
that are useful for stratified review without turning subjective weak signals
into irreversible deletion decisions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from bs4 import BeautifulSoup
from PIL import Image, ImageStat, UnidentifiedImageError


SPAM_TOPICS = {
    "gambling": ("online casino", "sports betting", "slot machine", "betting site", "casino bonus"),
    "adult": ("porn video", "escort service", "sex cam", "adult hookup"),
    "loans": ("payday loan", "instant loan", "no credit check loan"),
    "pills": ("buy viagra", "buy cialis", "online pharmacy without prescription"),
    "essay": ("buy essay", "write my essay", "dissertation writing service"),
}
PLACEHOLDER_MARKERS = (
    "lorem ipsum", "image placeholder", "your logo here", "sample text",
    "coming soon", "website under construction",
)
BROKEN_RESOURCE_MARKERS = (
    "about:blank", "net::err_", "failed to load resource", "image not found",
)


def visible_text(html: str) -> tuple[str, BeautifulSoup]:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript", "template"]):
        node.decompose()
    return soup.get_text(" ", strip=True), soup


def screenshot_signals(path: Path, analyze_pixels: bool = True) -> dict:
    try:
        old_limit = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = None
        with Image.open(path) as image:
            width, height = image.size
            if not analyze_pixels:
                Image.MAX_IMAGE_PIXELS = old_limit
                return {"width": width, "height": height, "aspect": height / max(width, 1)}
            if width * height > 50_000_000:
                Image.MAX_IMAGE_PIXELS = old_limit
                return {"width": width, "height": height, "aspect": height / max(width, 1),
                        "pixel_analysis_skipped": "oversized"}
            thumb = image.convert("RGB")
            thumb.thumbnail((192, 768))
            gray = thumb.convert("L")
            stat = ImageStat.Stat(gray)
            entropy = float(gray.entropy())
            stddev = float(stat.stddev[0])
            pixels = list(gray.get_flattened_data())
            near_white = sum(value >= 248 for value in pixels) / max(len(pixels), 1)
            near_midgray = sum(145 <= value <= 175 for value in pixels) / max(len(pixels), 1)
            digest = hashlib.sha256(thumb.tobytes()).hexdigest()
        Image.MAX_IMAGE_PIXELS = old_limit
        return {
            "width": width, "height": height, "aspect": height / max(width, 1),
            "entropy": round(entropy, 3), "stddev": round(stddev, 3),
            "near_white": round(near_white, 4), "near_midgray": round(near_midgray, 4),
            "thumbnail_hash": digest,
        }
    except (OSError, UnidentifiedImageError) as exc:
        return {"error": type(exc).__name__}


def inspect_site(site: Path) -> dict:
    pages = sorted([*site.glob("*.html"), *site.glob("*.htm")])
    signals: Counter[str] = Counter()
    topic_pages: Counter[str] = Counter()
    page_rows = []
    hashes = []
    for page in pages:
        html = page.read_text(encoding="utf-8", errors="replace")
        text, soup = visible_text(html)
        resource_soup = BeautifulSoup(html, "html.parser")
        lowered = text.lower()
        page_signals = []
        for topic, markers in SPAM_TOPICS.items():
            count = sum(lowered.count(marker) for marker in markers)
            if count:
                topic_pages[topic] += 1
            if count >= 2:
                page_signals.append(f"repeated_spam_topic:{topic}")
        if any(marker in lowered for marker in PLACEHOLDER_MARKERS):
            page_signals.append("placeholder_copy")
        raw_lower = html.lower()
        if any(marker in raw_lower for marker in BROKEN_RESOURCE_MARKERS):
            page_signals.append("broken_resource_marker")
        local_missing = 0
        for tag, attr in (("img", "src"), ("script", "src"), ("link", "href")):
            for node in resource_soup.find_all(tag):
                value = str(node.get(attr, "")).strip()
                if not value or value.startswith(("http://", "https://", "//", "data:", "#", "mailto:", "tel:", "javascript:")):
                    continue
                target = (page.parent / value.split("?", 1)[0].split("#", 1)[0].lstrip("/")).resolve()
                if page.parent.resolve() not in target.parents and target != page.parent.resolve():
                    continue
                if not target.exists():
                    local_missing += 1
        if local_missing >= 3:
            page_signals.append("multiple_missing_local_resources")
        screenshot = page.parent / ("screenshot.png" if page.name == "index.html" else f"{page.stem}_screenshot.png")
        shot = screenshot_signals(screenshot, analyze_pixels=page.name == "index.html")
        if "error" not in shot:
            if "thumbnail_hash" in shot:
                hashes.append(shot["thumbnail_hash"])
            if shot["aspect"] >= 12 and shot.get("near_white", 0) >= 0.72:
                page_signals.append("very_long_mostly_blank_screenshot")
            if shot.get("near_midgray", 0) >= 0.72 and shot.get("entropy", 99) < 3.0:
                page_signals.append("dominant_gray_placeholder")
            if shot.get("entropy", 99) < 1.6 and shot.get("near_white", 0) >= 0.85:
                page_signals.append("low_information_screenshot")
        else:
            page_signals.append("invalid_screenshot")
        signals.update(page_signals)
        page_rows.append({
            "page": page.name, "text_chars": len(text), "signals": sorted(set(page_signals)),
            "missing_local_resources": local_missing, "screenshot": shot,
        })
    for topic, count in topic_pages.items():
        if count >= 2:
            signals[f"spam_topic_across_pages:{topic}"] += count
    severity = sum(
        count * (3 if key.startswith(("spam_topic_across_pages", "repeated_spam_topic")) else 1)
        for key, count in signals.items()
    )
    return {
        "site": site.name, "path": str(site), "page_count": len(pages),
        "severity": severity, "signals": dict(signals), "pages": page_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    sites = sorted(path for path in args.root.iterdir() if path.is_dir())
    sites = sites[args.offset:]
    if args.limit:
        sites = sites[:args.limit]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    candidate_count = 0
    with args.output.open("w", encoding="utf-8") as handle:
        with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
            for number, row in enumerate(pool.map(inspect_site, sites, chunksize=4), 1):
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                counts.update(row["signals"])
                candidate_count += row["severity"] > 0
                if number % 250 == 0 or number == len(sites):
                    print(f"[{number}/{len(sites)}] candidates={candidate_count}", flush=True)
    print(json.dumps({"sites": len(sites), "signal_page_counts": counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
