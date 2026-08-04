#!/usr/bin/env python3
"""Final-project screenshotter with lazy-image and visual-stability gates.

This is deliberately separate from Pipeline C crawling.  It serves a frozen
project through local HTTP while the browser proxy remains available for allowed
remote image URLs.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import socket
import socketserver
import threading
import time
from pathlib import Path
from urllib.parse import quote

from PIL import Image, ImageFilter

from playwright.sync_api import sync_playwright


ERROR_PAGE_MARKERS = (
    "error response", "error code: 404", "file not found.",
    "httpstatus.not_found", "page not found", "404 not found",
    "there has been a critical error on this website", "troubleshooting wordpress",
    "parklogic.com", "domain is for sale", "buy this domain", "parked domain",
    "this domain may be for sale", "website is under construction",
    "private site", "log in to wordpress.com to request access",
    "http error 401", "unauthorized", "you are not authorized to view this page",
    "a php error was encountered", "severity:", "uncaught exception", "stack trace",
)


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _scroll_and_wait(page, deadline: float) -> dict:
    """Trigger lazy loading, then wait for a stable height and visible images."""
    page.evaluate("""async () => {
        const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
        const max = Math.max(document.documentElement.scrollHeight, document.body.scrollHeight);
        for (let y = 0; y < max; y += Math.max(250, innerHeight * 0.75)) {
            scrollTo(0, y); await pause(180);
        }
        scrollTo(0, 0);
    }""")
    previous_height = 0
    stable_rounds = 0
    while time.monotonic() < deadline:
        page.wait_for_timeout(750)
        state = page.evaluate("""() => {
            const viewHeight = innerHeight;
            const images = [...document.images].filter(image => {
                const box = image.getBoundingClientRect();
                return box.width >= 24 && box.height >= 24 && box.bottom > 0 && box.top < viewHeight;
            });
            const broken = images.filter(image => !image.complete || image.naturalWidth === 0);
            return {height: document.documentElement.scrollHeight, visible: images.length, broken: broken.length};
        }""")
        stable_rounds = stable_rounds + 1 if state["height"] == previous_height else 0
        previous_height = state["height"]
        if stable_rounds >= 2:
            return {**state, "stable": True}
    state["stable"] = False
    return state


def _visual_metrics(path: Path) -> dict:
    """Cheap blank/shell detector; it complements, never replaces, review."""
    image = Image.open(path).convert("L")
    # A gradient has large colour variation but almost no edges.  Edge density
    # catches the common failure where a JS app shell leaves only a background.
    edges = image.filter(ImageFilter.FIND_EDGES)
    if image.width > 4 and image.height > 4:
        edges = edges.crop((2, 2, image.width - 2, image.height - 2))
    histogram = edges.histogram()
    pixels = max(sum(histogram), 1)
    return {
        "edge_density": round(sum(histogram[20:]) / pixels, 6),
        "screenshot_width": image.width,
        "screenshot_height": image.height,
    }


def _semantic_layout_metrics(page) -> dict:
    return page.evaluate("""() => {
        const visible = el => {
          const box = el.getBoundingClientRect(), style = getComputedStyle(el);
          return style.display !== 'none' && style.visibility !== 'hidden' &&
            +style.opacity !== 0 && box.width >= 8 && box.height >= 8;
        };
        const semantic = [...document.querySelectorAll('main,header,footer,section,article,nav,aside,h1,h2,h3,p,button,a,li')]
          .filter(visible);
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        const chunks = [];
        for (let node = walker.nextNode(); node; node = walker.nextNode()) {
          const value = node.nodeValue.trim();
          if (value.length >= 2 && node.parentElement && visible(node.parentElement)) chunks.push(value);
        }
        const text = chunks.join(' ');
        return {
          visible_semantic_elements: semantic.length,
          visible_text_chars: text.length,
          body_children: [...document.body.children].filter(visible).length,
        };
    }""")


def _css_image_metrics(page) -> dict:
    """Check rendered CSS image URLs, including backgrounds and content:url()."""
    return page.evaluate("""async () => {
        const urls = new Set();
        const addUrls = value => {
          if (!value || value === 'none') return;
          for (const match of value.matchAll(/url\\((?:"|')?(.+?)(?:"|')?\\)/g)) {
            const raw = match[1].trim();
            if (raw && !raw.startsWith('data:')) urls.add(new URL(raw, document.baseURI).href);
          }
        };
        for (const element of document.querySelectorAll('*')) {
          const style = getComputedStyle(element);
          addUrls(style.backgroundImage); addUrls(style.content); addUrls(style.maskImage);
          addUrls(style.listStyleImage); addUrls(style.borderImageSource);
        }
        // A remote CSS background can remain pending indefinitely (neither
        // onload nor onerror).  Bound every probe so one bad third-party image
        // cannot occupy an entire rescue worker forever.
        const results = await Promise.all([...urls].map(url => new Promise(resolve => {
          const image = new Image();
          const timer = setTimeout(() => resolve({url, ok: false, timeout: true}), 5000);
          image.onload = () => { clearTimeout(timer); resolve({url, ok: true}); };
          image.onerror = () => { clearTimeout(timer); resolve({url, ok: false}); };
          image.src = url;
        })));
        const failed = results.filter(result => !result.ok).map(result => result.url);
        const timedOut = results.filter(result => result.timeout).map(result => result.url);
        return {css_image_urls: results.length, css_image_failed: failed.length,
          css_image_timeouts: timedOut.length, css_image_failures: failed.slice(0, 20)};
    }""")


def capture(project: Path, output: Path, proxy: str, timeout: int, max_broken_ratio: float,
            page_path: str = "index.html") -> dict:
    port = _port()
    server = _Server(("127.0.0.1", port), functools.partial(_Handler, directory=str(project)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                proxy={"server": proxy} if proxy else None,
                args=["--proxy-bypass-list=127.0.0.1,localhost"] if proxy else None,
            )
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            relative = page_path.lstrip("/") or "index.html"
            if ".." in Path(relative).parts:
                return {"status": "reject", "reason": "invalid_page_path"}
            response = page.goto(f"http://127.0.0.1:{port}/{quote(relative)}", wait_until="domcontentloaded", timeout=20_000)
            state = _scroll_and_wait(page, time.monotonic() + max(1, timeout - 30))
            ratio = state["broken"] / max(state["visible"], 1)
            layout = _semantic_layout_metrics(page)
            css_images = _css_image_metrics(page)
            page_text = page.locator("body").inner_text(timeout=10_000).lower()
            basic_ok = bool(response and 200 <= response.status < 400 and state["stable"] and
                            ratio <= max_broken_ratio and css_images["css_image_failed"] == 0)
            result = {"status": "pass" if basic_ok else "reject",
                      "http_status": response.status if response else None, "broken_image_ratio": ratio,
                      **state, **css_images}
            if basic_ok:
                page.screenshot(path=str(output), full_page=True, timeout=25_000)
                result["screenshot"] = str(output)
                visual = _visual_metrics(output)
                result.update(layout); result.update(visual)
                sparse_shell = (visual["edge_density"] < 0.012 or layout["visible_semantic_elements"] < 6 or
                                layout["visible_text_chars"] < 160)
                if any(marker in page_text for marker in ERROR_PAGE_MARKERS):
                    result.update({"status": "reject", "reason": "rendered_error_page"})
                elif sparse_shell:
                    result.update({"status": "reject", "reason": "visual_sparse_or_js_shell"})
            browser.close()
            return result
    except Exception as exc:
        return {"status": "retryable", "reason": f"{type(exc).__name__}: {exc}"}
    finally:
        server.shutdown(); server.server_close()


def capture_all(project: Path, output_dir: Path, proxy: str, timeout: int,
                max_broken_ratio: float, filename_prefix: str = "") -> dict:
    """Run the final render gate for every user-facing HTML page."""
    pages = []
    for path in sorted(project.rglob("*.html")):
        rel = path.relative_to(project)
        if any(part.lower() in {"resources", "assets", "static", "node_modules"} for part in rel.parts[:-1]):
            continue
        pages.append(rel.as_posix())
    if not pages:
        return {"status": "reject", "reason": "no_html_pages", "pages": []}
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for rel_text in pages:
        rel = Path(rel_text)
        page_key = rel.with_suffix("").as_posix().replace("/", "__")
        # The primary homepage screenshot is named exactly after its sample;
        # additional pages retain an unambiguous page suffix.
        if filename_prefix:
            name = filename_prefix if rel.name.lower() == "index.html" else f"{filename_prefix}__{page_key}"
        else:
            name = page_key
        screenshot = output_dir / f"{name}.png"
        verdict = capture(project, screenshot, proxy, timeout, max_broken_ratio, rel.as_posix())
        verdict["page"] = rel.as_posix()
        results.append(verdict)
        if verdict.get("status") != "pass":
            detail = verdict.get("reason")
            if not detail and verdict.get("css_image_failed"):
                detail = f"css_images_failed:{verdict['css_image_failed']}"
            elif not detail and verdict.get("broken_image_ratio", 0) > max_broken_ratio:
                detail = f"broken_image_ratio:{verdict['broken_image_ratio']:.3f}"
            elif not detail:
                detail = "render_gate_failed"
            return {"status": "reject", "reason": f"page_render_failed:{rel}:{detail}", "pages": results}
    return {"status": "pass", "pages": results}


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture final projects after lazy-load/stability validation.")
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser-proxy", default="")
    parser.add_argument("--site-timeout", type=int, default=60)
    parser.add_argument("--max-broken-image-ratio", type=float, default=0.05)
    args = parser.parse_args()
    result = capture(args.project, args.output, args.browser_proxy, args.site_timeout, args.max_broken_image_ratio)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
