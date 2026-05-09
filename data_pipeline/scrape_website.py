"""
Complete website scraper:
Given a URL, download the full page with all CSS/JS/images so it renders offline.

This is for webrenderbench data re-scraping — existing data may have incomplete source code,
so we re-crawl the full page using Playwright (to get rendered HTML) and download all
referenced assets.

Usage:
    # Scrape a single URL:
    python -m data_pipeline.scrape_website \
        --url https://example.com \
        --output_dir data_pipeline/output/scraped/example_com

    # Scrape from a URL list:
    python -m data_pipeline.scrape_website \
        --urls_file data_pipeline/input/urls.txt \
        --output_base data_pipeline/output/scraped

    # Then feed scraped dirs into image_reverse pipeline for data generation:
    python -m data_pipeline.image_reverse --html_dir data_pipeline/output/scraped/example_com
"""

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


def scrape_website(url: str, output_dir: str, timeout: int = 30000) -> dict:
    """Scrape a website completely: HTML + CSS + JS + images.

    Uses Playwright to get the fully rendered HTML, then parses it to find
    and download all referenced assets.

    Returns dict with stats.
    """
    os.makedirs(output_dir, exist_ok=True)
    stats = {"html": 0, "css": 0, "js": 0, "images": 0, "errors": []}

    # Step 1: Use Playwright to get rendered HTML and take screenshots
    print(f"  [1/4] Loading page with Playwright...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        try:
            page.goto(url, wait_until="networkidle", timeout=timeout)
            page.wait_for_timeout(3000)
        except Exception as e:
            stats["errors"].append(f"Page load failed: {e}")
            browser.close()
            return stats

        # Get rendered HTML
        rendered_html = page.content()

        # Take screenshots
        screenshots_dir = os.path.join(output_dir, "screenshots")
        os.makedirs(screenshots_dir, exist_ok=True)
        for vp_name, w, h in [("desktop", 1920, 1080), ("tablet", 768, 1024), ("mobile", 375, 812)]:
            page.set_viewport_size({"width": w, "height": h})
            page.wait_for_timeout(1000)
            page.screenshot(
                path=os.path.join(screenshots_dir, f"screenshot_{vp_name}.png"),
                full_page=True,
            )

        # Extract all stylesheets content via JS
        inline_styles = page.evaluate("""
            () => {
                const styles = [];
                for (const sheet of document.styleSheets) {
                    try {
                        let css = '';
                        for (const rule of sheet.cssRules) {
                            css += rule.cssText + '\\n';
                        }
                        styles.push({href: sheet.href || 'inline', css: css});
                    } catch(e) {
                        // Cross-origin sheets can't be read
                        styles.push({href: sheet.href, css: null});
                    }
                }
                return styles;
            }
        """)

        browser.close()

    # Step 2: Parse HTML and download assets
    print(f"  [2/4] Parsing HTML and identifying assets...")
    soup = BeautifulSoup(rendered_html, "html.parser")

    # Rewrite external resource URLs to local paths
    resources_dir = os.path.join(output_dir, "resources")
    os.makedirs(resources_dir, exist_ok=True)

    # Step 3: Download CSS files
    print(f"  [3/4] Downloading CSS/JS assets...")
    css_index = 0
    for style_info in inline_styles:
        href = style_info.get("href")
        css_content = style_info.get("css")

        if href and href != "inline" and css_content:
            # Save extracted CSS
            css_filename = f"style_{css_index}.css"
            css_path = os.path.join(resources_dir, css_filename)
            with open(css_path, "w", encoding="utf-8") as f:
                f.write(css_content)
            stats["css"] += 1
            css_index += 1
        elif href and href != "inline" and not css_content:
            # Try downloading directly
            try:
                resp = requests.get(href, timeout=10)
                resp.raise_for_status()
                css_filename = f"style_{css_index}.css"
                css_path = os.path.join(resources_dir, css_filename)
                with open(css_path, "w", encoding="utf-8") as f:
                    f.write(resp.text)
                stats["css"] += 1
                css_index += 1
            except Exception as e:
                stats["errors"].append(f"CSS download failed {href}: {e}")

    # Download JS files referenced in HTML
    for script_tag in soup.find_all("script", src=True):
        src = script_tag["src"]
        if src.startswith("data:") or src.startswith("blob:"):
            continue
        abs_url = urljoin(url, src)
        js_filename = _safe_filename(abs_url, "js")
        js_path = os.path.join(resources_dir, js_filename)
        if not os.path.exists(js_path):
            try:
                resp = requests.get(abs_url, timeout=10)
                resp.raise_for_status()
                with open(js_path, "w", encoding="utf-8") as f:
                    f.write(resp.text)
                stats["js"] += 1
            except Exception as e:
                stats["errors"].append(f"JS download failed {abs_url}: {e}")

    # Step 4: Download images
    print(f"  [4/4] Downloading images...")
    for img_tag in soup.find_all("img", src=True):
        src = img_tag["src"]
        if src.startswith("data:"):
            continue
        abs_url = urljoin(url, src)
        img_filename = _safe_filename(abs_url, "img")
        img_path = os.path.join(resources_dir, img_filename)
        if not os.path.exists(img_path):
            try:
                resp = requests.get(abs_url, timeout=10)
                resp.raise_for_status()
                with open(img_path, "wb") as f:
                    f.write(resp.content)
                stats["images"] += 1
            except Exception as e:
                stats["errors"].append(f"Image download failed {abs_url}: {e}")

    # Also look for background-image URLs in inline styles
    for tag in soup.find_all(style=True):
        style_val = tag.get("style", "")
        bg_urls = re.findall(r'url\(["\']?(https?://[^"\')\s]+)["\']?\)', style_val)
        for bg_url in bg_urls:
            img_filename = _safe_filename(bg_url, "bg")
            img_path = os.path.join(resources_dir, img_filename)
            if not os.path.exists(img_path):
                try:
                    resp = requests.get(bg_url, timeout=10)
                    resp.raise_for_status()
                    with open(img_path, "wb") as f:
                        f.write(resp.content)
                    stats["images"] += 1
                except Exception:
                    pass

    # Save the rendered HTML with CSS inlined
    # Rewrite link[rel=stylesheet] to point to local files
    link_tags = soup.find_all("link", rel="stylesheet")
    for i, link_tag in enumerate(link_tags):
        local_css = f"resources/style_{i}.css"
        if os.path.exists(os.path.join(output_dir, local_css)):
            link_tag["href"] = local_css

    # Save final HTML
    html_path = os.path.join(output_dir, "index.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(str(soup))
    stats["html"] = 1

    return stats


def _safe_filename(url: str, prefix: str) -> str:
    """Generate a safe filename from a URL."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    name = os.path.basename(path) if path else "index"
    # Sanitize
    name = re.sub(r'[^\w.\-]', '_', name)
    if not name or name == "_":
        name = f"{prefix}_{abs(hash(url)) % 100000}"
    # Ensure we don't lose the extension
    if "." not in name:
        # Guess extension from URL
        ext_map = {".css": ".css", ".js": ".js", ".png": ".png", ".jpg": ".jpg",
                   ".jpeg": ".jpeg", ".gif": ".gif", ".svg": ".svg", ".webp": ".webp"}
        for ext_key, ext_val in ext_map.items():
            if ext_key in url.lower():
                name += ext_val
                break
    return f"{prefix}_{name}"


def main():
    parser = argparse.ArgumentParser(description="Complete website scraper")
    parser.add_argument("--url", default=None, help="Single URL to scrape")
    parser.add_argument("--urls_file", default=None, help="File with one URL per line")
    parser.add_argument("--output_dir", default=None, help="Output dir (for single URL)")
    parser.add_argument("--output_base", default="data_pipeline/output/scraped", help="Base output dir (for URL list)")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    if not args.url and not args.urls_file:
        print("Error: provide --url or --urls_file")
        sys.exit(1)

    if args.url:
        urls = [args.url]
    else:
        with open(args.urls_file) as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        if args.limit > 0:
            urls = urls[:args.limit]

    for i, url in enumerate(urls):
        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "").replace(".", "_")
        if args.output_dir and len(urls) == 1:
            out_dir = args.output_dir
        else:
            out_dir = os.path.join(args.output_base, f"{i}_{domain}")

        print(f"\n=== Scraping {url} -> {out_dir} ===")
        stats = scrape_website(url, out_dir)
        print(f"  HTML: {stats['html']}, CSS: {stats['css']}, JS: {stats['js']}, Images: {stats['images']}")
        if stats["errors"]:
            print(f"  Errors: {len(stats['errors'])}")
            for err in stats["errors"][:3]:
                print(f"    - {err}")

    print(f"\nDone! {len(urls)} sites scraped.")


if __name__ == "__main__":
    main()
