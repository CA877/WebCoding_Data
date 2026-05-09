"""
Reverse image-generation pipeline:
Given a website's source code, take screenshots and use LLM to generate
a detailed description (query). Source code serves as ground truth.

Supports two caption modes:
- vision: use claude_sonnet4_5 to describe from screenshots (higher quality)
- code: use qwen3-coder-plus to describe from source code (cheaper)

Usage:
    python -m data_pipeline.image_reverse \
        --html_dir /path/to/website \
        --output data_pipeline/output/image_reverse.jsonl \
        [--mode vision|code] [--instance_id my_id]
"""

import argparse
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from .common import (
    get_client, call_llm_text, call_llm_with_images, append_jsonl,
    TEXT_MODEL, VISION_MODEL,
)


CAPTION_FROM_VISION_PROMPT = """You are a product manager writing a web design document for a developer.
You are looking at screenshots of a website. Write a structured design document with exactly three sections.

The document must follow this format:

# Web page content
Describe the page structure, layout, and all visible content using nested markdown headers and bullet points.
- What sections exist (header, sidebar, main content, footer, etc.)
- What UI components are present (navigation, buttons, forms, cards, lists, modals, etc.)
- What text content, labels, and data are shown
- How different areas are organized and related to each other
- For complex pages, describe each major section in detail

# Web page interaction
Describe all interactive behaviors and user flows:
- What happens when users click buttons, links, or other interactive elements
- Form submission flows, validation behaviors
- State changes (hover, focus, active, disabled states)
- Navigation flows between pages or views
- Dynamic content loading, animations, transitions
- Include 1-2 concrete "Action Sequences" describing step-by-step user interactions and expected system responses

# Web page visual description
Describe the visual design and aesthetic:
- Overall design style and aesthetic (e.g., "Modern SaaS", "Minimalist", "Corporate")
- Color palette described in natural language (e.g., "deep navy blue background", "bright orange accent")
- Typography style (e.g., "clean sans-serif headers with serif body text")
- Spacing and layout feel (e.g., "generous whitespace", "compact data-dense layout")
- Special visual effects (gradients, shadows, glassmorphism, animations)
- Responsive behavior across desktop, tablet, and mobile
- Do NOT list exact hex codes or pixel values — describe colors and sizes in natural, descriptive language

IMPORTANT:
- Write as requirements for a developer, NOT as a description of existing screenshots
- Use natural language, not CSS values or technical specifications
- Focus on WHAT the page should look like and DO, not HOW it is implemented
- Be specific about content and behavior, but descriptive (not numeric) about visual style

Output ONLY the design document."""


CAPTION_FROM_CODE_PROMPT = """You are a product manager writing a web design document for a developer.
Below is the complete source code of a website. Write a structured design document with exactly three sections.

The document must follow this format:

# Web page content
Describe the page structure, layout, and all visible content using nested markdown headers and bullet points.
- What sections exist (header, sidebar, main content, footer, etc.)
- What UI components are present (navigation, buttons, forms, cards, lists, modals, etc.)
- What text content, labels, and data are shown
- How different areas are organized and related to each other
- For complex pages, describe each major section in detail

# Web page interaction
Describe all interactive behaviors and user flows:
- What happens when users click buttons, links, or other interactive elements
- Form submission flows, validation behaviors
- State changes (hover, focus, active, disabled states)
- Navigation flows between pages or views
- Dynamic content loading, animations, transitions
- Include 1-2 concrete "Action Sequences" describing step-by-step user interactions and expected system responses

# Web page visual description
Describe the visual design and aesthetic:
- Overall design style and aesthetic (e.g., "Modern SaaS", "Minimalist", "Corporate")
- Color palette described in natural language (e.g., "deep navy blue background", "bright orange accent")
- Typography style (e.g., "clean sans-serif headers with serif body text")
- Spacing and layout feel (e.g., "generous whitespace", "compact data-dense layout")
- Special visual effects (gradients, shadows, glassmorphism, animations)
- Responsive behavior across desktop, tablet, and mobile
- Do NOT list exact hex codes or pixel values — describe colors and sizes in natural, descriptive language

IMPORTANT:
- Write as requirements for a developer, NOT as a description of source code
- Use natural language, not CSS values or technical specifications
- Focus on WHAT the page should look like and DO, not HOW it is implemented
- Be specific about content and behavior, but descriptive (not numeric) about visual style
- Do NOT reference the source code in any way

Output ONLY the design document.

Source code:
---
{source_code}
---"""


CHECKLIST_PROMPT = """You are an expert web QA engineer. Given the following web design document,
generate an evaluation checklist in JSON format.

Categories:
1. "Runnability" (1 item, max_score: 10)
2. "Spec Implementation" (5-8 items, total ~65)
3. "Design Quality" (2-3 items, total ~25)

Each item must have these exact fields:
- "task": short description
- "category": one of the three above
- "operation_sequence": numbered steps to verify
- "expected_result": what passing looks like
- "criteria": scoring rubric
- "max_score": integer

Output ONLY a valid JSON array. No markdown fences, no explanation.

Design document:
---
{document}
---"""


def take_screenshots(html_path: str, output_dir: str) -> list[str]:
    """Take screenshots of a local HTML file at multiple viewports.

    Uses route blocking to abort external requests (CDN fonts, scripts, etc.)
    that would cause networkidle to hang indefinitely.
    """
    os.makedirs(output_dir, exist_ok=True)
    html_url = f"file://{os.path.abspath(html_path)}"
    viewports = [
        {"width": 1920, "height": 1080, "name": "desktop"},
        {"width": 768, "height": 1024, "name": "tablet"},
        {"width": 375, "height": 812, "name": "mobile"},
    ]
    screenshots = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for vp in viewports:
            page = browser.new_page(viewport={"width": vp["width"], "height": vp["height"]})
            # Block external requests to prevent hanging on CDN resources
            page.route("**/*", lambda route: (
                route.continue_()
                if route.request.url.startswith("file://")
                else route.abort("connectionfailed")
            ))
            page.goto(html_url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(1000)
            path = os.path.join(output_dir, f"screenshot_{vp['name']}.png")
            page.screenshot(path=path, full_page=True)
            screenshots.append(path)
            page.close()
        browser.close()

    return screenshots


def collect_source_files(html_dir: str) -> list[dict]:
    """Collect source files. Returns [{"path": ..., "code": ...}]."""
    source_exts = {".html", ".css", ".js", ".json", ".svg"}
    src_files = []
    root = Path(html_dir)
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in source_exts:
            continue
        if f.stat().st_size > 500_000:
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        src_files.append({"path": str(f.relative_to(root)), "code": content})
    return src_files


def format_source_for_prompt(src_files: list[dict], max_chars: int = 30000) -> str:
    """Format source files into a string for LLM prompt."""
    parts = []
    total = 0
    for f in src_files:
        header = f"\n=== {f['path']} ===\n"
        content = f["code"]
        if total + len(header) + len(content) > max_chars:
            remaining = max_chars - total - len(header) - 50
            if remaining > 200:
                parts.append(header + content[:remaining] + "\n... (truncated)")
            break
        parts.append(header + content)
        total += len(header) + len(content)
    return "".join(parts)


def parse_json_from_response(response: str) -> list:
    """Extract JSON array from LLM response."""
    response = response.strip()
    if response.startswith("```"):
        lines = response.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        response = "\n".join(lines)
    return json.loads(response)


def process_one(
    html_dir: str,
    instance_id: str,
    client,
    output_jsonl: str,
    screenshots_dir: str,
    mode: str = "vision",
):
    """Process a single website directory into an image-generation data item."""
    html_path = os.path.join(html_dir, "index.html")
    if not os.path.exists(html_path):
        html_files = list(Path(html_dir).glob("*.html"))
        if not html_files:
            print(f"[SKIP] No HTML files found in {html_dir}")
            return None
        html_path = str(html_files[0])

    # Step 1: Collect source files
    print(f"[1/4] Collecting source files...")
    src_files = collect_source_files(html_dir)
    print(f"  -> {len(src_files)} source files")
    if not src_files:
        print(f"[SKIP] No source files")
        return None

    # Step 2: Take screenshots
    print(f"[2/4] Taking screenshots...")
    screenshot_out = os.path.join(screenshots_dir, instance_id)
    screenshots = take_screenshots(html_path, screenshot_out)
    screenshot_names = [Path(s).name for s in screenshots]
    print(f"  -> {len(screenshots)} screenshots")

    # Step 3: Generate description
    if mode == "vision" and screenshots:
        print(f"[3/4] Generating description via vision LLM ({VISION_MODEL})...")
        description = call_llm_with_images(
            client, VISION_MODEL, CAPTION_FROM_VISION_PROMPT, screenshots
        )
    else:
        print(f"[3/4] Generating description via text LLM ({TEXT_MODEL})...")
        source_text = format_source_for_prompt(src_files)
        prompt = CAPTION_FROM_CODE_PROMPT.format(source_code=source_text)
        description = call_llm_text(client, TEXT_MODEL, prompt)
    print(f"  -> Description: {len(description)} chars")

    # Step 4: Generate checklist (use cheaper text model)
    print(f"[4/4] Generating checklist ({TEXT_MODEL})...")
    checklist = parse_json_from_response(
        call_llm_text(client, TEXT_MODEL, CHECKLIST_PROMPT.format(document=description))
    )
    print(f"  -> {len(checklist)} checklist items")

    item = {
        "repo": "claude/webcoding",
        "instance_id": str(instance_id),
        "base_commit": "main",
        "problem_statement": checklist,
        "meta": {"class": "image_genration", "difficulty": "medium"},
        "working_dir": "/testbed",
        "instruction": description,
        "screenshots": screenshot_names,
    }
    append_jsonl(output_jsonl, item)
    print(f"  -> Saved to {output_jsonl}")
    return item


def main():
    parser = argparse.ArgumentParser(description="Reverse image-generation pipeline")
    parser.add_argument("--html_dir", required=True)
    parser.add_argument("--output", default="data_pipeline/output/image_reverse.jsonl")
    parser.add_argument("--instance_id", default=None)
    parser.add_argument("--screenshots_dir", default="data_pipeline/output/screenshots")
    parser.add_argument("--mode", default="vision", choices=["vision", "code"],
                        help="vision=use claude_sonnet4_5, code=use qwen3-coder-plus")
    args = parser.parse_args()

    instance_id = args.instance_id or Path(args.html_dir).name
    client = get_client()
    result = process_one(
        html_dir=args.html_dir,
        instance_id=instance_id,
        client=client,
        output_jsonl=args.output,
        screenshots_dir=args.screenshots_dir,
        mode=args.mode,
    )
    if result:
        print(f"\nDone! Instance {instance_id} saved.")
    else:
        print(f"\nFailed for {args.html_dir}")
        sys.exit(1)


if __name__ == "__main__":
    main()
