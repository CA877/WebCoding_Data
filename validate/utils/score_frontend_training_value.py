#!/usr/bin/env python3
"""Score every surviving site by frontend-training value."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from bs4 import BeautifulSoup


def score_site(task: tuple[Path, dict, dict]) -> dict:
    site, quality, prior = task
    page = next((item for item in quality.get("pages", []) if item["page"] == "index.html"), {})
    shot = page.get("screenshot", {})
    entropy = float(shot.get("entropy", 0))
    near_white = float(shot.get("near_white", 1))
    html = (site / "index.html").read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    media = len(soup.find_all(["img", "picture", "svg", "video", "canvas"]))
    interactive = len(soup.find_all(["form", "button", "input", "select", "textarea", "details", "dialog"]))
    layout = len(soup.find_all(["header", "nav", "main", "section", "article", "aside", "footer"]))
    components = len(soup.find_all(class_=re.compile(
        r"card|grid|hero|gallery|slider|carousel|modal|tabs?|accordion|menu|navbar|banner|feature|product", re.I
    )))
    stylesheets = len(soup.find_all("link", rel=lambda value: value and "stylesheet" in value))
    inline_css = sum(len(tag.get_text()) for tag in soup.find_all("style"))
    score = 0
    score += 0 if entropy < 2 else 1 if entropy < 3 else 2 if entropy < 4 else 3
    score += 0 if media == 0 else 1 if media <= 2 else 2 if media <= 8 else 3
    score += 0 if interactive == 0 else 1 if interactive <= 2 else 2
    score += 0 if layout == 0 else 1 if layout <= 4 else 2
    score += 0 if components == 0 else 1 if components <= 4 else 2
    score += 1 if stylesheets or inline_css >= 500 else 0
    if near_white >= 0.90:
        score -= 2
    elif near_white >= 0.80:
        score -= 1
    signals = quality.get("signals", {})
    if signals.get("multiple_missing_local_resources", 0) >= 4:
        score -= 1
    if signals.get("broken_resource_marker", 0) >= 2:
        score -= 2
    if signals.get("placeholder_copy", 0) >= 3:
        score -= 1
    warnings = prior.get("warnings", {})
    if warnings.get("link_farm_or_directory_page", 0) >= 2:
        score -= 1
    return {
        "site": site.name, "score": score,
        "features": {"entropy": entropy, "near_white": near_white, "media": media,
                     "interactive": interactive, "layout": layout, "components": components,
                     "stylesheets": stylesheets, "inline_css": inline_css},
        "penalty_signals": signals, "prior_warnings": warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--quality-audit", type=Path, required=True)
    parser.add_argument("--prior-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=24)
    args = parser.parse_args()
    current = {path.name: path for path in args.root.iterdir() if path.is_dir()}
    quality = {row["site"]: row for row in map(json.loads, args.quality_audit.open()) if row["site"] in current}
    prior = {row["site"]: row for row in map(json.loads, args.prior_audit.open()) if row["site"] in current}
    tasks = [(current[name], quality[name], prior.get(name, {})) for name in sorted(current)]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    distribution: Counter[int] = Counter()
    with args.output.open("w", encoding="utf-8") as handle:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            for number, row in enumerate(pool.map(score_site, tasks, chunksize=8), 1):
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                distribution[row["score"]] += 1
                if number % 1000 == 0:
                    print(f"[{number}/{len(tasks)}]", flush=True)
    print(json.dumps({"sites": len(tasks), "score_distribution": dict(sorted(distribution.items()))}))


if __name__ == "__main__":
    main()
