"""
Crawl web pages from WebRenderBench domain list.

Downloads metadata from WebRenderBench (45k real-world website domains),
visits each domain with Playwright, saves the rendered HTML and resources
as self-contained local directories for offline rendering.

Usage:
    # Small test run
    python -m data_pipeline.web_crawl \
        --meta_dir data_pipeline/output/wrb_metadata/ \
        --output_dir data_pipeline/output/wrb_pages \
        --manifest data_pipeline/output/wrb_manifest.jsonl \
        --limit 5

    # Full run
    python -m data_pipeline.web_crawl \
        --meta_dir data_pipeline/output/wrb_metadata/ \
        --output_dir data_pipeline/output/wrb_pages \
        --manifest data_pipeline/output/wrb_manifest.jsonl \
        --limit 0
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from playwright.sync_api import sync_playwright

from .common import append_jsonl


# ---------------------------------------------------------------------------
# Metadata loading
# ---------------------------------------------------------------------------

def load_domains(meta_dir: str) -> list[dict]:
    """Load unique domains from WebRenderBench metadata files."""
    seen = set()
    domains = []

    for fname in sorted(Path(meta_dir).glob("*.jsonl")):
        with open(fname) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                name = obj.get("name", "")
                # Format: NUMBER_DOMAIN_ or NUMBER_DOMAIN
                parts = name.split("_", 1)
                if len(parts) < 2:
                    continue
                domain = parts[1].rstrip("_")
                if not domain or domain in seen:
                    continue
                seen.add(domain)
                domains.append({
                    "domain": domain,
                    "industry": obj.get("industry", ""),
                    "element_count": obj.get("element_count", 0),
                    "company_type": obj.get("company_type", ""),
                })

    return domains


# ---------------------------------------------------------------------------
# Resource downloading
# ---------------------------------------------------------------------------

MAX_RESOURCE_SIZE = 5 * 1024 * 1024   # 5MB per resource
MAX_TOTAL_SIZE = 50 * 1024 * 1024     # 50MB total per page
RESOURCE_TIMEOUT = 10                  # seconds


def download_resource(url: str, dest_path: str, session: requests.Session) -> bool:
    """Download a single resource. Returns True on success."""
    try:
        resp = session.get(url, timeout=RESOURCE_TIMEOUT, stream=True)
        if resp.status_code != 200:
            return False
        content_length = int(resp.headers.get("content-length", 0))
        if content_length > MAX_RESOURCE_SIZE:
            return False

        data = b""
        for chunk in resp.iter_content(8192):
            data += chunk
            if len(data) > MAX_RESOURCE_SIZE:
                return False

        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(data)
        return True
    except Exception:
        return False


def make_local_filename(url: str) -> str:
    """Convert a URL to a safe local filename, preserving extension."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    ext = Path(path).suffix if path else ""
    if not ext or len(ext) > 10:
        ext = ""
    # Use hash for uniqueness
    url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
    name = Path(path).stem if path else "resource"
    # Sanitize name
    name = re.sub(r"[^\w\-.]", "_", name)[:40]
    return f"{name}_{url_hash}{ext}"


# ---------------------------------------------------------------------------
# Page crawling
# ---------------------------------------------------------------------------

def crawl_page(page, domain: str, output_dir: str, session: requests.Session) -> dict:
    """Crawl a single domain with Playwright, save as self-contained directory.

    Returns dict with crawl results.
    """
    url = f"https://{domain}"
    page_dir = os.path.join(output_dir, domain.replace("/", "_"))
    result = {
        "domain": domain,
        "url": url,
        "status": "error",
        "error": None,
        "body_text_length": 0,
        "resource_count": 0,
        "total_size": 0,
    }

    # Capture console errors
    console_errors = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda err: console_errors.append(str(err)))

    try:
        resp = page.goto(url, wait_until="networkidle", timeout=30000)
        if resp is None or resp.status >= 400:
            result["error"] = f"HTTP {resp.status if resp else 'no response'}"
            result["status"] = "http_error"
            return result
    except Exception as e:
        err_str = str(e)[:200]
        if "timeout" in err_str.lower():
            result["status"] = "timeout"
        else:
            result["status"] = "load_error"
        result["error"] = err_str
        return result

    # Wait for dynamic content
    page.wait_for_timeout(2000)

    # Check content
    body_text = page.evaluate("document.body ? document.body.innerText : ''")
    body_len = len(body_text.strip())
    result["body_text_length"] = body_len

    if body_len < 50:
        result["status"] = "blank"
        result["error"] = f"Body text too short ({body_len})"
        return result

    if len(console_errors) > 10:
        result["status"] = "js_errors"
        result["error"] = f"{len(console_errors)} console errors"
        return result

    # Get the rendered HTML
    html_content = page.content()

    # Collect resource URLs from the page
    resources = page.evaluate("""
        () => {
            const resources = [];
            // CSS
            document.querySelectorAll('link[rel="stylesheet"][href]').forEach(el => {
                resources.push({type: 'css', url: el.href, attr: 'href'});
            });
            // JS
            document.querySelectorAll('script[src]').forEach(el => {
                resources.push({type: 'js', url: el.src, attr: 'src'});
            });
            // Images
            document.querySelectorAll('img[src]').forEach(el => {
                if (el.src && !el.src.startsWith('data:')) {
                    resources.push({type: 'img', url: el.src, attr: 'src'});
                }
            });
            // Favicon
            document.querySelectorAll('link[rel*="icon"][href]').forEach(el => {
                resources.push({type: 'icon', url: el.href, attr: 'href'});
            });
            return resources;
        }
    """)

    # Create output directory
    os.makedirs(page_dir, exist_ok=True)
    assets_dir = os.path.join(page_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)

    # Download resources and build URL mapping
    total_downloaded = 0
    downloaded_count = 0
    url_map = {}  # original_url -> local_path

    for res in resources:
        res_url = res["url"]
        if not res_url or res_url.startswith("data:"):
            continue
        if res_url in url_map:
            continue

        local_name = make_local_filename(res_url)
        local_path = os.path.join(assets_dir, local_name)

        if download_resource(res_url, local_path, session):
            file_size = os.path.getsize(local_path)
            total_downloaded += file_size
            downloaded_count += 1
            url_map[res_url] = f"assets/{local_name}"

            if total_downloaded > MAX_TOTAL_SIZE:
                result["status"] = "too_large"
                result["error"] = f"Total resources > {MAX_TOTAL_SIZE // 1024 // 1024}MB"
                # Clean up
                import shutil
                shutil.rmtree(page_dir, ignore_errors=True)
                return result

    # Replace URLs in HTML with local paths
    for original_url, local_path in url_map.items():
        html_content = html_content.replace(original_url, local_path)

    # Save HTML
    index_path = os.path.join(page_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    result["status"] = "ok"
    result["resource_count"] = downloaded_count
    result["total_size"] = total_downloaded
    result["console_errors"] = len(console_errors)

    return result


# ---------------------------------------------------------------------------
# Resume support
# ---------------------------------------------------------------------------

def load_processed_domains(manifest_path: str) -> set[str]:
    """Load already-processed domains from manifest."""
    processed = set()
    if not os.path.exists(manifest_path):
        return processed
    with open(manifest_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                processed.add(obj["domain"])
            except (json.JSONDecodeError, KeyError):
                continue
    return processed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Crawl web pages from WebRenderBench domain list"
    )
    parser.add_argument(
        "--meta_dir", default="data_pipeline/output/wrb_metadata/",
        help="Directory with WebRenderBench metadata JSONL files",
    )
    parser.add_argument(
        "--output_dir", default="data_pipeline/output/wrb_pages",
        help="Directory to store crawled page directories",
    )
    parser.add_argument(
        "--manifest", default="data_pipeline/output/wrb_manifest.jsonl",
        help="Manifest JSONL tracking all processed domains",
    )
    parser.add_argument(
        "--limit", type=int, default=100,
        help="Max domains to process (0 = unlimited)",
    )
    args = parser.parse_args()

    # Setup
    os.makedirs(args.output_dir, exist_ok=True)
    processed = load_processed_domains(args.manifest)
    print(f"Resuming: {len(processed)} domains already processed")

    # Load domains
    all_domains = load_domains(args.meta_dir)
    print(f"Total unique domains in metadata: {len(all_domains)}")

    # Filter already processed
    candidates = [d for d in all_domains if d["domain"] not in processed]
    print(f"Remaining to process: {len(candidates)}")

    limit = args.limit if args.limit > 0 else len(candidates)

    # Setup HTTP session for resource downloading
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    # Use proxy from environment if set
    proxy = os.environ.get("ALL_PROXY") or os.environ.get("HTTPS_PROXY")
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}

    # Stats
    total_processed = 0
    total_ok = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

        # Configure proxy for the browser context
        proxy_config = None
        if proxy:
            proxy_config = {"server": proxy}

        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            proxy=proxy_config,
            ignore_https_errors=True,
        )

        page = context.new_page()

        for domain_info in candidates:
            if total_processed >= limit:
                break

            domain = domain_info["domain"]
            total_processed += 1

            print(f"\n[{total_processed}/{limit}] {domain} ({domain_info['industry']})")

            result = crawl_page(page, domain, args.output_dir, session)

            if result["status"] == "ok":
                total_ok += 1
                print(f"    [OK] body={result['body_text_length']} resources={result['resource_count']}")
            else:
                print(f"    [{result['status'].upper()}] {result.get('error', '')[:100]}")

            # Write manifest
            append_jsonl(args.manifest, {
                "domain": domain,
                "industry": domain_info["industry"],
                "element_count": domain_info["element_count"],
                "status": result["status"],
                "error": result.get("error"),
                "body_text_length": result.get("body_text_length", 0),
                "resource_count": result.get("resource_count", 0),
                "total_size": result.get("total_size", 0),
                "timestamp": datetime.now().isoformat(),
            })

            # Periodic summary
            if total_processed % 50 == 0:
                print(f"\n=== Progress: {total_processed} processed, {total_ok} ok ({total_ok*100//total_processed}%) ===")

            # Polite delay
            time.sleep(1)

        browser.close()

    # Summary
    print(f"\n=== Summary ===")
    print(f"Domains processed: {total_processed}")
    print(f"Pages saved: {total_ok}")
    print(f"Success rate: {total_ok*100//max(total_processed,1)}%")
    print(f"Output directory: {args.output_dir}")
    print(f"Manifest: {args.manifest}")


if __name__ == "__main__":
    main()
