"""
Forward image-generation pipeline:
Crawl real websites -> take screenshots + capture source -> LLM writes caption.
No ground truth source code provided (query-only dataset).

Supports vision mode (claude_sonnet4_5) or code mode (qwen3-coder-plus).

Usage:
    python -m data_pipeline.image_forward \
        --urls_file data_pipeline/input/urls.txt \
        --output data_pipeline/output/image_forward.jsonl \
        [--mode vision|code]
"""

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from .common import (
    get_client, call_llm_text, call_llm_with_images, append_jsonl,
    TEXT_MODEL, VISION_MODEL,
)


CAPTION_FROM_VISION_PROMPT = """You are an expert web developer. You are looking at screenshots of a real website.
Write a detailed, specific web design document for reproducing this website from scratch.

Requirements:
1. Describe layout and structure (header, sections, footer)
2. Describe UI components (navigation, buttons, forms, cards, modals)
3. Describe colors, typography, spacing in detail
4. Describe interactive elements and behavior
5. Be concrete: exact colors, layout patterns, sizes
6. Do NOT reference "screenshots"

Output ONLY the design document."""


CAPTION_FROM_CODE_PROMPT = """You are an expert web developer. Below is the HTML source of a real website.
Write a detailed, specific web design document for reproducing this website.

Requirements:
1. Describe layout and structure
2. Describe UI components
3. Describe colors, typography, spacing
4. Describe interactive elements
5. Be concrete
6. Write as requirements — do NOT reference source code

Output ONLY the design document.

HTML source (may be truncated):
---
{source_code}
---"""


CHECKLIST_PROMPT = """You are an expert web QA engineer. Given the following web design document,
generate an evaluation checklist in JSON format.

Categories:
1. "Runnability" (1 item, max_score: 10)
2. "Spec Implementation" (5-8 items, total ~65)
3. "Design Quality" (2-3 items, total ~25)

Each item: {{"task", "category", "operation_sequence", "expected_result", "criteria", "max_score"}}

Output ONLY a valid JSON array. No fences, no explanation.

Design document:
---
{document}
---"""


def crawl_page(url: str, output_dir: str) -> tuple[list[str], str]:
    """Visit URL, take screenshots, capture source. Returns (screenshot_paths, page_html)."""
    os.makedirs(output_dir, exist_ok=True)
    viewports = [
        {"width": 1920, "height": 1080, "name": "desktop"},
        {"width": 768, "height": 1024, "name": "tablet"},
        {"width": 375, "height": 812, "name": "mobile"},
    ]
    screenshots = []
    page_html = ""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for vp in viewports:
            page = browser.new_page(viewport={"width": vp["width"], "height": vp["height"]})
            try:
                page.goto(url, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(3000)
            except Exception as e:
                print(f"  [WARN] Failed to load {url} at {vp['name']}: {e}")
                page.close()
                continue
            if not page_html:
                page_html = page.content()
            path = os.path.join(output_dir, f"screenshot_{vp['name']}.png")
            page.screenshot(path=path, full_page=True)
            screenshots.append(path)
            page.close()
        browser.close()

    return screenshots, page_html


def parse_json_from_response(response: str) -> list:
    response = response.strip()
    if response.startswith("```"):
        lines = response.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        response = "\n".join(lines)
    return json.loads(response)


def process_url(
    url: str,
    instance_id: str,
    client,
    output_jsonl: str,
    screenshots_base: str,
    mode: str = "vision",
):
    print(f"\n--- Processing {url} (id={instance_id}) ---")

    print(f"[1/3] Crawling and taking screenshots...")
    screenshot_dir = os.path.join(screenshots_base, instance_id)
    screenshots, page_html = crawl_page(url, screenshot_dir)
    if not screenshots:
        print(f"  [SKIP] No screenshots captured")
        return None
    screenshot_names = [Path(s).name for s in screenshots]
    print(f"  -> {len(screenshots)} screenshots, HTML: {len(page_html)} chars")

    print(f"[2/3] Generating description...")
    if mode == "vision":
        description = call_llm_with_images(
            client, VISION_MODEL, CAPTION_FROM_VISION_PROMPT, screenshots
        )
    else:
        prompt = CAPTION_FROM_CODE_PROMPT.format(source_code=page_html[:30000])
        description = call_llm_text(client, TEXT_MODEL, prompt)
    print(f"  -> Description: {len(description)} chars")

    print(f"[3/3] Generating checklist ({TEXT_MODEL})...")
    checklist = parse_json_from_response(
        call_llm_text(client, TEXT_MODEL, CHECKLIST_PROMPT.format(document=description))
    )
    print(f"  -> {len(checklist)} checklist items")

    item = {
        "repo": "claude/webcoding",
        "instance_id": instance_id,
        "base_commit": "main",
        "problem_statement": checklist,
        "meta": {"class": "image_genration", "difficulty": "medium", "source_url": url},
        "working_dir": "/testbed",
        "instruction": description,
        "screenshots": screenshot_names,
    }
    append_jsonl(output_jsonl, item)
    print(f"  -> Saved to {output_jsonl}")
    return item


def main():
    parser = argparse.ArgumentParser(description="Forward image-generation pipeline")
    parser.add_argument("--urls_file", required=True)
    parser.add_argument("--output", default="data_pipeline/output/image_forward.jsonl")
    parser.add_argument("--screenshots_dir", default="data_pipeline/output/screenshots_forward")
    parser.add_argument("--mode", default="vision", choices=["vision", "code"])
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    with open(args.urls_file, "r") as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    if args.limit > 0:
        urls = urls[:args.limit]

    client = get_client()
    success = 0
    for i, url in enumerate(urls):
        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "").replace(".", "_")
        instance_id = f"fwd_{i}_{domain}"
        result = process_url(url, instance_id, client, args.output, args.screenshots_dir, args.mode)
        if result:
            success += 1

    print(f"\nDone! {success}/{len(urls)} URLs processed.")


if __name__ == "__main__":
    main()
