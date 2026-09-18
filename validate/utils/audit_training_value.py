#!/usr/bin/env python3
"""Find visually sparse survivors that add little frontend-training value."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--quality-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    current = {path.name for path in args.root.iterdir() if path.is_dir()}
    rows = []
    for quality in map(json.loads, args.quality_audit.open()):
        site = quality["site"]
        if site not in current:
            continue
        index_page = next((page for page in quality.get("pages", []) if page["page"] == "index.html"), None)
        shot = (index_page or {}).get("screenshot", {})
        entropy = shot.get("entropy")
        near_white = shot.get("near_white")
        strict_low = "low_information_screenshot" in quality.get("signals", {})
        if not strict_low and not (
            isinstance(entropy, (int, float)) and isinstance(near_white, (int, float))
            and near_white >= 0.55 and entropy < 4.2
        ):
            continue
        index = args.root / site / "index.html"
        if not index.is_file():
            continue
        soup = BeautifulSoup(index.read_text(encoding="utf-8", errors="replace"), "html.parser")
        media = len(soup.find_all(["img", "picture", "svg", "video", "canvas"]))
        interactive = len(soup.find_all(["form", "button", "input", "select", "textarea", "details"]))
        layout = len(soup.find_all(["header", "nav", "main", "section", "article", "aside", "footer"]))
        styled_components = len(soup.find_all(class_=re.compile(r"card|grid|hero|gallery|slider|carousel|modal|tabs?", re.I)))
        stylesheets = len(soup.find_all("link", rel=lambda value: value and "stylesheet" in value))
        anchors = len(soup.find_all("a", href=True))
        reasons = []
        if strict_low:
            reasons.append("strict_low_information_render")
        if (
            near_white >= 0.78 and entropy < 2.5 and media <= 1 and interactive <= 1
            and layout <= 5 and styled_components <= 2
        ):
            reasons.append("plain_document_or_minimal_template")
        if near_white >= 0.90 and entropy < 2.2 and media <= 2 and interactive <= 2:
            reasons.append("near_empty_visual_design")
        if (
            near_white >= 0.60 and entropy < 4.0 and media == 0 and interactive == 0
            and layout <= 5 and styled_components <= 1
        ):
            reasons.append("text_only_document")
        rows.append({
            "site": site, "status": "reject" if reasons else "pass", "reasons": reasons,
            "features": {"entropy": entropy, "near_white": near_white, "media": media,
                         "interactive": interactive, "layout": layout,
                         "styled_components": styled_components, "stylesheets": stylesheets,
                         "anchors": anchors},
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    rejected = [row for row in rows if row["status"] == "reject"]
    print(json.dumps({"reviewed_sparse_pool": len(rows), "reject": len(rejected),
                      "strict_low": sum("strict_low_information_render" in row["reasons"] for row in rejected),
                      "plain": sum("plain_document_or_minimal_template" in row["reasons"] for row in rejected),
                      "empty": sum("near_empty_visual_design" in row["reasons"] for row in rejected),
                      "text_only": sum("text_only_document" in row["reasons"] for row in rejected)}))


if __name__ == "__main__":
    main()
