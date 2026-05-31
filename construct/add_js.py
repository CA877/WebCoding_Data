#!/usr/bin/env python3
"""Add clean, functional Vanilla JS to existing HTML/CSS projects.

Takes cleaned WebRenderBench or crawled projects (which may lack JS or have broken JS),
analyzes the HTML/CSS structure, and uses an LLM to generate appropriate main.js.

Follows WebCompass's approach: output is separate index.html + styles.css + main.js files.

Usage:
    python3 construct/add_js.py \
        --input-dir /data/cleaned_projects/ \
        --output-dir /data/projects_with_js/ \
        --concurrency 5 \
        --limit 10
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from construct_common import (
    ensure_api_env,
    find_html_pages,
    maybe_load_env,
    read_code_bundle,
)


# ---------------------------------------------------------------------------
# Prompt template — inspired by WebCompass text-to-web generation
# ---------------------------------------------------------------------------

JS_GENERATION_PROMPT = """\
You are a senior front-end engineer. You will be given the HTML and CSS code of an existing website project.

Your task: analyze the website's structure, content, and interactive elements, then write a complete `main.js` file that adds appropriate interactivity.

## What to implement (pick what fits the page)

Look at the page structure and add interactions that make sense:
- **Navigation**: mobile hamburger menu toggle, dropdown menus on hover/click, smooth scroll to anchors, active link highlighting
- **UI Components**: tabs, accordions/collapsibles, modals/lightboxes, tooltips, carousels/sliders (if the HTML has slide-like structure)
- **Forms**: input validation, character counters, show/hide password, form submission feedback
- **Scroll effects**: back-to-top button, sticky header on scroll, scroll-triggered animations (fade-in, slide-up)
- **Content**: image lazy loading, search/filter for lists, "read more" truncation
- **Feedback**: notification toasts, loading states, hover effects that need JS

## Hard constraints

1. **Vanilla JS only** — no jQuery, no React, no frameworks. Use `document.querySelector`, `addEventListener`, etc.
2. **ES6+ syntax** — `const`/`let`, arrow functions, template literals, destructuring.
3. **Self-contained** — the JS must work with the existing HTML as-is. Do NOT assume elements exist that aren't in the HTML.
4. **Defensive** — wrap each feature in a null check: `const el = document.querySelector('.menu'); if (el) { ... }`. This prevents errors if an element doesn't exist.
5. **No external dependencies** — no CDN imports, no fetch to external APIs.
6. **DOMContentLoaded** — wrap everything in `document.addEventListener('DOMContentLoaded', () => { ... })`.
7. **Readable** — use clear variable names, add brief comments for each feature section.
8. **Reasonable size** — aim for 50-200 lines. Don't over-engineer.

## Output format

Return ONLY the JavaScript code. No markdown fences, no explanations, no HTML modifications.
Start directly with `// main.js` and the code.

## Website code to analyze

{code_context}
"""


def build_code_context(project_dir: Path, max_chars: int = 20000) -> str:
    """Build a compact code context from project files."""
    code_items = read_code_bundle(project_dir)
    chunks = []
    remaining = max_chars

    # Prioritize HTML first, then CSS, then existing JS
    priority = {".html": 0, ".htm": 0, ".css": 1, ".js": 2}
    code_items.sort(key=lambda x: (priority.get(Path(x["path"]).suffix.lower(), 9), x["path"]))

    for item in code_items:
        if remaining <= 0:
            break
        code = item["code"]
        if len(code) > 6000:
            code = code[:6000] + "\n<!-- ... truncated ... -->"
        chunks.append(f'--- {item["path"]} ---\n{code}')
        remaining -= len(code)

    return "\n\n".join(chunks)


def generate_js(project_dir: Path, model: str, client) -> str | None:
    """Generate main.js content for a project using LLM."""
    code_context = build_code_context(project_dir)
    if not code_context.strip():
        return None

    prompt = JS_GENERATION_PROMPT.replace("{code_context}", code_context)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You write clean, functional Vanilla JavaScript for existing websites."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=4096,
            temperature=0.7,
        )
        content = response.choices[0].message.content or ""

        # Strip markdown fences if present
        content = content.strip()
        if content.startswith("```"):
            # Remove opening fence
            content = re.sub(r'^```\w*\n?', '', content)
            # Remove closing fence
            content = re.sub(r'\n?```\s*$', '', content)

        return content.strip()
    except Exception as e:
        print(f"  LLM error: {e}")
        return None


def process_project(
    project_dir: Path,
    output_dir: Path,
    model: str,
    client,
) -> dict:
    """Process a single project: copy + generate JS."""
    name = project_dir.name
    out = output_dir / name

    # Check if already processed
    if (out / "main.js").exists():
        return {"project": name, "status": "skipped"}

    # Copy project to output
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(project_dir, out)

    # Generate JS
    js_content = generate_js(project_dir, model, client)
    if not js_content:
        return {"project": name, "status": "generation_failed"}

    # Write main.js
    (out / "main.js").write_text(js_content, encoding="utf-8")

    # Add <script src="main.js"> to all HTML files if not already present
    for html_file in out.glob("*.html"):
        html = html_file.read_text(encoding="utf-8", errors="replace")
        if "main.js" not in html:
            # Insert before </body> or at end
            if "</body>" in html:
                html = html.replace("</body>", '  <script src="main.js"></script>\n</body>')
            else:
                html += '\n<script src="main.js"></script>'
            html_file.write_text(html, encoding="utf-8")

    # Also extract inline CSS to styles.css if not already separate
    index_html = out / "index.html"
    styles_css = out / "styles.css"
    if index_html.exists() and not styles_css.exists():
        html = index_html.read_text(encoding="utf-8", errors="replace")
        # Don't extract — inline CSS is fine for training. WebCompass uses separate files
        # but our crawled data has inline CSS which is equally valid.

    return {
        "project": name,
        "status": "ok",
        "js_lines": len(js_content.splitlines()),
        "js_size": len(js_content),
    }


def main():
    parser = argparse.ArgumentParser(description="Add Vanilla JS to existing HTML/CSS projects using LLM")
    parser.add_argument("--input-dir", required=True, help="Directory with project subdirs")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--concurrency", type=int, default=3, help="Concurrent LLM calls")
    parser.add_argument("--limit", type=int, default=None, help="Limit projects to process")
    parser.add_argument("--model", default=None, help="Override model (default: from env)")
    args = parser.parse_args()

    maybe_load_env()
    api_key, base_url, env_model = ensure_api_env()
    model = args.model or env_model

    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=180.0)

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    projects = sorted(d for d in input_dir.iterdir() if d.is_dir() and (d / "index.html").exists())
    if args.limit:
        projects = projects[:args.limit]

    print(f"Adding JS to {len(projects)} projects (model={model}, concurrency={args.concurrency})")

    results = []

    def _process_one(proj):
        t0 = time.time()
        result = process_project(proj, output_dir, model, client)
        result["elapsed"] = round(time.time() - t0, 1)
        return result

    if args.concurrency <= 1:
        for i, proj in enumerate(projects):
            result = _process_one(proj)
            results.append(result)
            js_lines = result.get("js_lines", 0)
            print(f"[{i+1}/{len(projects)}] {result['project']}: {result['status']} ({js_lines} lines, {result['elapsed']:.1f}s)")
    else:
        with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            futures = {executor.submit(_process_one, proj): proj for proj in projects}
            for i, future in enumerate(as_completed(futures), 1):
                result = future.result()
                results.append(result)
                js_lines = result.get("js_lines", 0)
                print(f"[{i}/{len(projects)}] {result['project']}: {result['status']} ({js_lines} lines, {result['elapsed']:.1f}s)")

    # Save results
    results_path = output_dir / "add_js_results.jsonl"
    with open(results_path, "w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    statuses = Counter(r["status"] for r in results)
    print(f"\nDone: {statuses}")


if __name__ == "__main__":
    main()
