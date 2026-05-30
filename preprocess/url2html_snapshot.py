#!/usr/bin/env python3
"""Convert a live URL to a self-contained HTML file using Playwright.

Approach: Navigate with Playwright (through proxy), inline CSS via JS evaluation,
then post-process to download images to local resources/.

Usage:
    python3 url2html_snapshot.py --url https://example.com --output output_dir/
"""

import argparse
import hashlib
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


PROXY = "socks5://127.0.0.1:13659"  # NOT socks5h - Chromium needs local DNS


def snapshot_url(url: str, output_dir: Path, wait_ms: int = 2000, viewport_w: int = 1280):
    """Capture a URL as self-contained HTML with local resources."""
    output_dir.mkdir(parents=True, exist_ok=True)
    resources_dir = output_dir / "resources"
    resources_dir.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(proxy={"server": PROXY})
        page = browser.new_page(viewport={"width": viewport_w, "height": 800})

        # Navigate — use 'commit' (first response) since full load can be slow via proxy
        page.goto(url, wait_until="commit", timeout=45000)
        page.wait_for_timeout(wait_ms)

        # Inline stylesheets and remove scripts via JS
        html = page.evaluate("""() => {
            // Inline all stylesheets
            for (const sheet of document.styleSheets) {
                try {
                    if (sheet.href && sheet.ownerNode) {
                        let css = '';
                        for (const rule of sheet.cssRules) {
                            css += rule.cssText + '\\n';
                        }
                        const style = document.createElement('style');
                        style.textContent = css;
                        sheet.ownerNode.replaceWith(style);
                    }
                } catch(e) {
                    // Cross-origin, skip
                }
            }
            
            // Remove scripts
            document.querySelectorAll('script').forEach(s => s.remove());
            
            // Remove noise links
            document.querySelectorAll('link[rel*="preconnect"], link[rel*="prefetch"], link[rel*="dns-prefetch"], link[rel*="canonical"]').forEach(l => l.remove());
            
            return '<!DOCTYPE html>\\n' + document.documentElement.outerHTML;
        }""")

        # Take screenshot
        page.screenshot(
            path=str(output_dir / "screenshot.png"),
            full_page=True,
            clip={"x": 0, "y": 0, "width": viewport_w, "height": 2000}
        )

        browser.close()

    # Post-process: download images to resources/
    session = requests.Session()
    session.proxies = {"http": "socks5h://127.0.0.1:13659", "https": "socks5h://127.0.0.1:13659"}

    soup = BeautifulSoup(html, "html.parser")

    # Download images
    for tag in soup.find_all(["img", "source"]):
        src = tag.get("src") or tag.get("data-src")
        if not src or src.startswith("data:") or src.startswith("./"):
            continue
        abs_url = urljoin(url, src)
        if not abs_url.startswith("http"):
            continue
        local = _download_to_resources(session, abs_url, resources_dir)
        if local:
            if tag.get("src"):
                tag["src"] = local
            if tag.get("data-src"):
                tag["data-src"] = local
        else:
            tag.decompose()
        # Remove srcset
        if tag.name and tag.get("srcset"):
            del tag["srcset"]

    # Download CSS background images
    def replace_bg_url(match):
        img_url = match.group(1).strip("\"'")
        if img_url.startswith("data:") or img_url.startswith("./"):
            return match.group(0)
        abs_url = urljoin(url, img_url)
        if not abs_url.startswith("http"):
            return match.group(0)
        local = _download_to_resources(session, abs_url, resources_dir)
        return f"url({local})" if local else match.group(0)

    for tag in soup.find_all("style"):
        if tag.string:
            tag.string = re.sub(r"url\(([^)]+)\)", replace_bg_url, tag.get_text())

    for tag in soup.find_all(style=True):
        tag["style"] = re.sub(r"url\(([^)]+)\)", replace_bg_url, tag["style"])

    # Download remaining external CSS that couldn't be inlined
    for link in list(soup.find_all("link", rel="stylesheet")):
        href = link.get("href", "")
        if href.startswith("http"):
            try:
                resp = session.get(href, timeout=10)
                if resp.status_code == 200:
                    style = soup.new_tag("style")
                    css_text = resp.text
                    # Also resolve urls in CSS
                    css_text = re.sub(r"url\(([^)]+)\)", replace_bg_url, css_text)
                    style.string = css_text
                    link.replace_with(style)
                else:
                    link.decompose()
            except Exception:
                link.decompose()

    # Neutralize external hrefs
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("http") or href.startswith("//"):
            a["href"] = "#"

    # Write output
    final_html = str(soup)
    index_path = output_dir / "index.html"
    index_path.write_text(final_html, encoding="utf-8")

    return {
        "html_size": len(final_html),
        "resources": len(list(resources_dir.iterdir())),
        "output": str(index_path),
    }


def _download_to_resources(session: requests.Session, url: str, resources_dir: Path) -> str | None:
    """Download a URL to resources/ and return relative path."""
    try:
        resp = session.get(url, timeout=8, allow_redirects=True)
        if resp.status_code != 200 or len(resp.content) < 100:
            return None
    except Exception:
        return None

    h = hashlib.md5(url.encode()).hexdigest()[:8]
    name = Path(urlparse(url).path).name or "resource"
    name = f"{h}_{name}"
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80]

    target = resources_dir / name
    target.write_bytes(resp.content)
    return f"./resources/{name}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Snapshot URL to self-contained HTML")
    parser.add_argument("--url", required=True, help="URL to capture")
    parser.add_argument("--output", required=True, help="Output directory")
    parser.add_argument("--wait", type=int, default=2000, help="Wait time after load (ms)")
    parser.add_argument("--viewport", type=int, default=1280, help="Viewport width")
    args = parser.parse_args()

    result = snapshot_url(args.url, Path(args.output), args.wait, args.viewport)
    print(f"Done: {result['html_size']} bytes HTML, {result['resources']} resources")
    print(f"Output: {result['output']}")
