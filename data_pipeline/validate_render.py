"""
Rendering validation:
Use Playwright to verify that generated web pages render correctly.

Checks:
1. Page loads without timeout
2. No JavaScript console errors
3. Page has visible content (not blank)
4. Lists interactive elements (buttons, links, forms) for inspection

Usage:
    # Validate a single HTML directory:
    python -m data_pipeline.validate_render --html_dir output_text/694

    # Validate all dirs under a base:
    python -m data_pipeline.validate_render --base_dir output_text

    # Validate and save report:
    python -m data_pipeline.validate_render --html_dir output_text/694 --report data_pipeline/output/render_report.jsonl
"""

import argparse
import json
import os
import sys
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from playwright.sync_api import sync_playwright

from .common import append_jsonl


def validate_html(html_path: str, viewport_width: int = 1920, viewport_height: int = 1080) -> dict:
    """Validate an HTML file renders correctly.

    Returns dict with validation results.
    """
    result = {
        "html_path": html_path,
        "loaded": False,
        "console_errors": [],
        "has_visible_content": False,
        "page_title": "",
        "body_text_length": 0,
        "interactive_elements": [],
        "screenshot_path": None,
    }

    abs_path = os.path.abspath(html_path)
    if not os.path.exists(abs_path):
        result["error"] = f"File not found: {abs_path}"
        return result

    # Start a local HTTP server to serve the page directory
    # This allows the browser to load external CDN resources normally
    html_dir = os.path.dirname(abs_path)
    html_filename = os.path.basename(abs_path)

    class SilentHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=html_dir, **kwargs)
        def log_message(self, format, *args):
            pass  # suppress all HTTP server logs

    server = HTTPServer(("127.0.0.1", 0), SilentHandler)
    port = server.server_address[1]
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": viewport_width, "height": viewport_height})

            # Capture console errors
            console_errors = []
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda err: console_errors.append(str(err)))

            try:
                page.goto(f"http://127.0.0.1:{port}/{html_filename}", wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(2000)
                result["loaded"] = True
            except Exception as e:
                result["error"] = f"Load failed: {e}"
                browser.close()
                return result

            result["console_errors"] = console_errors
            result["page_title"] = page.title()

            # Check visible content
            body_text = page.evaluate("document.body ? document.body.innerText : ''")
            result["body_text_length"] = len(body_text.strip())
            result["has_visible_content"] = len(body_text.strip()) > 10

            # Collect interactive elements
            interactive = page.evaluate("""
                () => {
                    const elements = [];
                    // Buttons
                    document.querySelectorAll('button, [role="button"], input[type="button"], input[type="submit"]').forEach(el => {
                        elements.push({
                            type: 'button',
                            text: (el.textContent || el.value || '').trim().substring(0, 50),
                            visible: el.offsetParent !== null,
                            tag: el.tagName.toLowerCase(),
                        });
                    });
                    // Links
                    document.querySelectorAll('a[href]').forEach(el => {
                        elements.push({
                            type: 'link',
                            text: (el.textContent || '').trim().substring(0, 50),
                            href: el.href.substring(0, 100),
                            visible: el.offsetParent !== null,
                        });
                    });
                    // Forms
                    document.querySelectorAll('form').forEach(el => {
                        const inputs = el.querySelectorAll('input, select, textarea');
                        elements.push({
                            type: 'form',
                            action: (el.action || '').substring(0, 100),
                            input_count: inputs.length,
                        });
                    });
                    // Inputs outside forms
                    document.querySelectorAll('input:not(form input), select:not(form select), textarea:not(form textarea)').forEach(el => {
                        elements.push({
                            type: 'input',
                            input_type: el.type || el.tagName.toLowerCase(),
                            placeholder: (el.placeholder || '').substring(0, 50),
                            visible: el.offsetParent !== null,
                        });
                    });
                    return elements;
                }
            """)
            result["interactive_elements"] = interactive

            # Take validation screenshot
            screenshot_dir = os.path.dirname(abs_path)
            screenshot_path = os.path.join(screenshot_dir, "_validation_screenshot.png")
            page.screenshot(path=screenshot_path, full_page=True)
            result["screenshot_path"] = screenshot_path

            browser.close()
    finally:
        server.shutdown()

    return result


def validate_directory(html_dir: str) -> dict:
    """Validate all HTML files in a directory."""
    html_path = os.path.join(html_dir, "index.html")
    if not os.path.exists(html_path):
        # Find any HTML file
        html_files = list(Path(html_dir).glob("*.html"))
        if not html_files:
            return {"html_dir": html_dir, "error": "No HTML files found", "passed": False}
        html_path = str(html_files[0])

    result = validate_html(html_path)
    result["html_dir"] = html_dir

    # Determine pass/fail
    result["passed"] = (
        result["loaded"]
        and result["has_visible_content"]
        and len(result["console_errors"]) == 0
    )

    return result


def print_report(result: dict):
    """Print a human-readable validation report."""
    status = "PASS" if result.get("passed") else "FAIL"
    path = result.get("html_dir") or result.get("html_path")
    print(f"\n  [{status}] {path}")
    print(f"    Loaded: {result.get('loaded')}")
    print(f"    Title: {result.get('page_title', 'N/A')}")
    print(f"    Body text length: {result.get('body_text_length', 0)}")
    print(f"    Visible content: {result.get('has_visible_content')}")

    errors = result.get("console_errors", [])
    if errors:
        print(f"    Console errors ({len(errors)}):")
        for err in errors[:5]:
            print(f"      - {err[:100]}")

    interactive = result.get("interactive_elements", [])
    if interactive:
        buttons = [e for e in interactive if e["type"] == "button"]
        links = [e for e in interactive if e["type"] == "link"]
        forms = [e for e in interactive if e["type"] == "form"]
        inputs = [e for e in interactive if e["type"] == "input"]
        print(f"    Interactive: {len(buttons)} buttons, {len(links)} links, {len(forms)} forms, {len(inputs)} inputs")


def main():
    parser = argparse.ArgumentParser(description="Validate web page rendering")
    parser.add_argument("--html_dir", default=None, help="Single directory to validate")
    parser.add_argument("--base_dir", default=None, help="Base dir, validate all subdirs")
    parser.add_argument("--report", default=None, help="Output report JSONL path")
    args = parser.parse_args()

    if not args.html_dir and not args.base_dir:
        print("Error: provide --html_dir or --base_dir")
        sys.exit(1)

    dirs = []
    if args.html_dir:
        dirs = [args.html_dir]
    else:
        base = Path(args.base_dir)
        dirs = [str(d) for d in sorted(base.iterdir()) if d.is_dir()]

    passed = 0
    failed = 0
    for d in dirs:
        print(f"Validating {d}...")
        result = validate_directory(d)
        print_report(result)

        if result.get("passed"):
            passed += 1
        else:
            failed += 1

        if args.report:
            # Remove non-serializable fields
            report_item = {k: v for k, v in result.items() if k != "screenshot_path"}
            append_jsonl(args.report, report_item)

    print(f"\n=== Summary: {passed} passed, {failed} failed, {passed + failed} total ===")


if __name__ == "__main__":
    main()
