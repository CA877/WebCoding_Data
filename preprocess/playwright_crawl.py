#!/usr/bin/env python3
"""Playwright-based web crawler for building multi-page training samples.

Three modes:
1. crawl: Given a URL list, crawl each site (index + sub-pages) into a local project.
2. expand: Given existing WebRenderBench projects, expand to multi-page by
   crawling sub-pages found in index.html.
3. clean: Given existing projects with remote image/CSS refs, download them locally.

Each project output:
    project_dir/
        index.html        (main page, CSS inlined, images localized)
        about.html        (sub-page 1)
        services.html     (sub-page 2)
        ...
        resources/        (images, fonts, etc.)

Proxy configuration:
    - On this Mac (M4 laptop), the SOCKS5 proxy is at 127.0.0.1:13659
      provided by AliMgrSoc. Chromium needs 'socks5://' (NOT socks5h).
      requests library needs 'socks5h://' for remote DNS resolution.
    - On server: adjust --browser-proxy and --requests-proxy accordingly.
      If server has direct internet access, set both to empty string.

Usage:
    # Crawl new sites from URL list
    python3 playwright_crawl.py crawl --url-file urls.txt --output-dir output/ --concurrency 5

    # Expand WebRenderBench projects to multi-page
    python3 playwright_crawl.py expand --input-dir projects/ --output-dir expanded/ --concurrency 5

    # Clean existing projects (download remote images)
    python3 playwright_crawl.py clean --input-dir projects/ --concurrency 5

Dependencies:
    pip install playwright requests beautifulsoup4
    playwright install chromium
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Browser, Page

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Fallback image URLs — reliable placeholder services.
# Used when a remote image cannot be downloaded.
# placehold.co is confirmed working through SOCKS5 proxy.
# Different colors provide visual diversity.
FALLBACK_IMAGE_URLS = [
    "https://placehold.co/800x600/e8e8e8/666666?text=Image",
    "https://placehold.co/800x600/d4e6f1/2c3e50?text=Photo",
    "https://placehold.co/800x600/d5f5e3/1e8449?text=Image",
    "https://placehold.co/800x600/fdebd0/e67e22?text=Photo",
    "https://placehold.co/800x600/ebdef0/8e44ad?text=Image",
    "https://placehold.co/800x600/fadbd8/c0392b?text=Photo",
    "https://placehold.co/800x600/d6eaf8/2980b9?text=Image",
    "https://placehold.co/800x600/e8daef/7d3c98?text=Photo",
    "https://placehold.co/400x400/e8e8e8/666666?text=Icon",
    "https://placehold.co/200x200/d4e6f1/2c3e50?text=Avatar",
    "https://placehold.co/1200x400/fdebd0/e67e22?text=Banner",
    "https://placehold.co/600x400/d5f5e3/1e8449?text=Thumb",
    "https://placehold.co/300x200/fadbd8/c0392b?text=Card",
    "https://placehold.co/800x600/aed6f1/1a5276?text=Image",
    "https://placehold.co/800x600/a9dfbf/196f3d?text=Photo",
    "https://placehold.co/800x600/f9e79f/7d6608?text=Image",
    "https://placehold.co/800x600/f5b7b1/922b21?text=Photo",
    "https://placehold.co/800x600/d2b4de/6c3483?text=Image",
    "https://placehold.co/800x600/a3e4d7/0e6655?text=Photo",
    "https://placehold.co/800x600/abebc6/1e8449?text=Image",
]

# JS to inject into page — inlines CSS, removes scripts and noise
INLINE_CSS_JS = """() => {
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
            // Cross-origin stylesheet, skip
        }
    }
    // Remove scripts
    document.querySelectorAll('script, noscript').forEach(s => s.remove());
    // Remove noise links
    document.querySelectorAll('link[rel*="preconnect"], link[rel*="prefetch"], link[rel*="dns-prefetch"], link[rel*="canonical"], link[rel*="manifest"], link[rel*="alternate"]').forEach(l => l.remove());
    // Remove comments
    const walker = document.createTreeWalker(document, NodeFilter.SHOW_COMMENT);
    const comments = [];
    while (walker.nextNode()) comments.push(walker.currentNode);
    comments.forEach(c => c.remove());

    return '<!DOCTYPE html>\\n' + document.documentElement.outerHTML;
}"""


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def build_requests_session(proxy: str) -> requests.Session:
    """Build a requests session with proxy and retry."""
    session = requests.Session()
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}
    session.headers["User-Agent"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    return session


MAX_RESOURCES_PER_PAGE = 50  # Limit downloads to prevent hanging on heavy pages


def download_resource(session: requests.Session, url: str, resources_dir: Path,
                      fallback_index: int = -1) -> str | None:
    """Download a resource to resources/ dir. Returns relative path or None.

    If download fails and fallback_index >= 0, downloads a fallback image instead.
    """
    try:
        resp = session.get(url, timeout=8, allow_redirects=True)
        if resp.status_code == 200 and len(resp.content) >= 100:
            h = hashlib.md5(url.encode()).hexdigest()[:8]
            name = Path(urlparse(url).path).name or "resource"
            name = f"{h}_{name}"
            name = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80]
            # Ensure extension exists
            if "." not in name.split("_", 1)[-1]:
                ct = resp.headers.get("content-type", "").lower()
                ext = _guess_ext(ct)
                if ext:
                    name += ext
            target = resources_dir / name
            target.write_bytes(resp.content)
            return f"./resources/{name}"
    except Exception:
        pass

    # Fallback: download a placeholder image
    if fallback_index >= 0:
        fb_url = FALLBACK_IMAGE_URLS[fallback_index % len(FALLBACK_IMAGE_URLS)]
        try:
            resp = session.get(fb_url, timeout=10, allow_redirects=True)
            if resp.status_code == 200:
                name = f"placeholder_{fallback_index:04d}.jpg"
                target = resources_dir / name
                target.write_bytes(resp.content)
                return f"./resources/{name}"
        except Exception:
            pass

    return None


def _guess_ext(content_type: str) -> str:
    """Guess file extension from content-type."""
    if "jpeg" in content_type or "jpg" in content_type:
        return ".jpg"
    if "png" in content_type:
        return ".png"
    if "gif" in content_type:
        return ".gif"
    if "svg" in content_type:
        return ".svg"
    if "webp" in content_type:
        return ".webp"
    if "css" in content_type:
        return ".css"
    if "javascript" in content_type:
        return ".js"
    if "woff2" in content_type:
        return ".woff2"
    if "woff" in content_type:
        return ".woff"
    return ""


def localize_resources(html: str, page_url: str, resources_dir: Path,
                       session: requests.Session) -> str:
    """Download remote images and inline remaining remote CSS.

    Failed image downloads get a fallback placeholder (not removed from DOM).
    Remote CSS that couldn't be inlined by Playwright gets downloaded and inlined here.
    """
    # Remove IE conditional comments and HTML comments containing scripts
    html = re.sub(r'<!--\[if[^\]]*\]>.*?<!\[endif\]-->', '', html, flags=re.DOTALL)
    html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)

    soup = BeautifulSoup(html, "html.parser")

    # Remove remaining scripts
    for script in list(soup.find_all("script")):
        script.decompose()
    fallback_idx = 0
    download_count = 0

    # Process <img>, <source>, and <input type="image"> tags
    for tag in list(soup.find_all(["img", "source", "input"])):
        # Skip <input> that aren't type="image"
        if tag.name == "input" and (tag.get("type") or "").lower() != "image":
            continue
        for attr in ("src", "data-src", "data-lazy-src", "data-cke-saved-src"):
            val = tag.get(attr)
            if not val or val.startswith("data:") or val.startswith("./resources/"):
                continue
            abs_url = urljoin(page_url, val)
            if not abs_url.startswith("http"):
                continue
            if download_count >= MAX_RESOURCES_PER_PAGE:
                # Hit limit — remove to avoid broken remote ref
                tag.decompose()
                break
            local = download_resource(session, abs_url, resources_dir,
                                      fallback_index=fallback_idx)
            download_count += 1
            fallback_idx += 1
            if local:
                tag[attr] = local
            else:
                # Even fallback failed — remove broken tag
                tag.decompose()
                break
        # Remove srcset (too complex to handle)
        try:
            if tag.get("srcset"):
                del tag["srcset"]
        except (AttributeError, TypeError):
            pass

    # Process data-src on any element (lazy-load divs, etc.)
    for tag in list(soup.find_all(attrs={"data-src": True})):
        val = tag["data-src"]
        if val.startswith("data:") or val.startswith("./resources/"):
            continue
        abs_url = urljoin(page_url, val)
        if not abs_url.startswith("http"):
            continue
        if download_count >= MAX_RESOURCES_PER_PAGE:
            del tag["data-src"]
            continue
        local = download_resource(session, abs_url, resources_dir,
                                  fallback_index=fallback_idx)
        download_count += 1
        fallback_idx += 1
        if local:
            tag["data-src"] = local
        else:
            del tag["data-src"]

    # Remove CKEditor artifacts and other data-*-src/href with remote URLs
    for tag in soup.find_all(True):
        attrs_to_remove = [k for k in tag.attrs
                          if k.startswith("data-cke-saved-") or
                          (k.startswith("data-") and k.endswith(("-src", "-href"))
                           and isinstance(tag[k], str) and tag[k].startswith("http"))]
        for attr in attrs_to_remove:
            del tag[attr]

    # Remove iframes (YouTube embeds, etc.) — not needed for training
    for iframe in list(soup.find_all("iframe")):
        iframe.decompose()

    # Remove <video> and <audio> with remote sources (too large for training)
    for tag in list(soup.find_all(["video", "audio"])):
        src = tag.get("src", "")
        has_remote_source = src.startswith("http") or any(
            s.get("src", "").startswith("http") for s in tag.find_all("source")
        )
        if has_remote_source:
            tag.decompose()

    # Process CSS background-image url() in style attributes
    def replace_bg_url(match):
        nonlocal fallback_idx, download_count
        img_url = match.group(1).strip("\"'")
        if img_url.startswith("data:") or img_url.startswith("./resources/"):
            return match.group(0)
        abs_url = urljoin(page_url, img_url)
        if not abs_url.startswith("http"):
            return match.group(0)
        if download_count >= MAX_RESOURCES_PER_PAGE:
            return match.group(0)  # Skip, leave as-is (will be a broken ref but layout preserved)
        local = download_resource(session, abs_url, resources_dir,
                                  fallback_index=fallback_idx)
        download_count += 1
        fallback_idx += 1
        if local:
            return f"url({local})"
        return match.group(0)

    for tag in soup.find_all(style=True):
        if tag.get("style"):
            tag["style"] = re.sub(r"url\(([^)]+)\)", replace_bg_url, tag["style"])

    for tag in soup.find_all("style"):
        if tag.string:
            tag.string = re.sub(r"url\(([^)]+)\)", replace_bg_url, tag.get_text())

    # Inline remaining remote CSS (cross-origin sheets Playwright couldn't read)
    for link in list(soup.find_all("link")):
        if not link.attrs:
            continue
        rel = " ".join(link.get("rel") or []).lower()
        href = link.get("href", "")
        if "stylesheet" in rel and href.startswith("http"):
            try:
                resp = session.get(href, timeout=10)
                if resp.status_code == 200 and "text" in resp.headers.get("content-type", ""):
                    style = soup.new_tag("style")
                    css_text = resp.text
                    # Also resolve url() in downloaded CSS
                    css_text = re.sub(r"url\(([^)]+)\)", replace_bg_url, css_text)
                    style.string = css_text
                    link.replace_with(style)
                else:
                    link.decompose()
            except Exception:
                link.decompose()

    return str(soup)


def extract_nav_links(html: str, base_url: str, max_links: int = 5) -> list[str]:
    """Extract internal navigation links from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc

    seen_paths = set()
    links = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        if href.startswith("javascript:"):
            continue

        abs_url = urljoin(base_url, href)
        parsed = urlparse(abs_url)

        # Must be same domain
        if parsed.netloc != base_domain:
            continue

        # Must be a different path from root
        path = parsed.path.rstrip("/")
        if not path or path == "/" or path == parsed_base.path.rstrip("/"):
            continue

        # Skip non-page extensions
        if any(path.endswith(ext) for ext in (".jpg", ".png", ".gif", ".pdf", ".zip", ".svg", ".ico", ".xml", ".rss")):
            continue

        # Dedup by path
        path_key = path + ("?" + parsed.query if parsed.query else "")
        if path_key in seen_paths:
            continue
        seen_paths.add(path_key)

        links.append(abs_url)
        if len(links) >= max_links:
            break

    return links


def safe_filename(url: str, index: int, used: set) -> str:
    """Generate a safe HTML filename for a sub-page URL."""
    parsed = urlparse(url)
    # Try to use meaningful name from path
    stem = Path(parsed.path).stem or f"page_{index}"
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_") or f"page_{index}"
    name = f"{stem}.html"
    # Avoid index.html
    if name == "index.html":
        name = f"page_{index}.html"
    # Dedup
    base = name
    suffix = 2
    while name in used:
        name = f"{Path(base).stem}_{suffix}.html"
        suffix += 1
    used.add(name)
    return name


def relink_pages(project_dir: Path, url_to_file: dict[str, str]):
    """Rewrite hrefs between project pages to use local filenames."""
    if not url_to_file:
        return

    # Build lookup indexes
    path_to_file: dict[str, str] = {}
    domain = None

    for url, filename in url_to_file.items():
        parsed = urlparse(url)
        if not domain:
            domain = parsed.netloc
        path_to_file[parsed.path.rstrip("/")] = filename
        path_to_file[parsed.path] = filename
        if parsed.query:
            path_to_file[parsed.path + "?" + parsed.query] = filename

    project_pages = set(url_to_file.values())

    for html_file in project_dir.glob("*.html"):
        html = html_file.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        modified = False

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href == "#" or href.startswith("mailto:") or href.startswith("tel:"):
                continue
            if href in project_pages:
                continue

            matched = None
            if href.startswith("http") or href.startswith("//"):
                parsed = urlparse(href)
                if parsed.netloc == domain:
                    path_q = parsed.path + ("?" + parsed.query if parsed.query else "")
                    matched = path_to_file.get(path_q) or path_to_file.get(parsed.path.rstrip("/"))
            else:
                # Relative path
                clean = href.lstrip("./")
                matched = (path_to_file.get(href) or
                          path_to_file.get("/" + clean) or
                          path_to_file.get(href.split("?")[0]))

            if matched:
                a["href"] = matched
                modified = True

        if modified:
            html_file.write_text(str(soup), encoding="utf-8")


def neutralize_external_links(project_dir: Path):
    """Convert all remaining absolute URL links to '#' or local file references.

    relink_pages() should be called BEFORE this to map known internal pages.
    This function handles everything that's left.
    """
    local_files = {f.name for f in project_dir.glob("*.html")}

    for html_file in project_dir.glob("*.html"):
        html = html_file.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        modified = False

        # Neutralize <a> and <area> href links
        for a in soup.find_all(["a", "area"], href=True):
            href = a["href"]
            if not (href.startswith("http") or href.startswith("//")):
                continue

            # Try to match basename to a local file
            parsed = urlparse(href)
            basename = Path(parsed.path).name if parsed.path else ""
            if basename and basename in local_files:
                a["href"] = basename
            else:
                a["href"] = "#"
            modified = True

        # Remove <link> tags with remote hrefs (favicons, etc.) except stylesheets
        # (stylesheets are already handled by localize_resources)
        for link in list(soup.find_all("link")):
            href = link.get("href", "")
            if href.startswith("http") or href.startswith("//"):
                rel = " ".join(link.get("rel") or []).lower()
                if "stylesheet" not in rel:
                    link.decompose()
                    modified = True

        if modified:
            html_file.write_text(str(soup), encoding="utf-8")


def validate_page(html: str, min_text_len: int = 50) -> bool:
    """Check if page has enough visible content."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(strip=True)
    return len(text) >= min_text_len


def detect_language(html: str) -> str:
    """Simple language detection: returns 'en', 'zh', or 'other'."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(strip=True)[:2000]

    # Check lang attribute first
    html_tag = soup.find("html")
    if html_tag:
        lang = (html_tag.get("lang") or "").lower()
        if lang.startswith("zh"):
            return "zh"
        if lang.startswith("en"):
            return "en"

    # Heuristic: count Chinese characters vs Latin
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin_chars = len(re.findall(r"[a-zA-Z]", text))
    total = chinese_chars + latin_chars

    if total < 20:
        return "other"
    if chinese_chars / max(total, 1) > 0.3:
        return "zh"
    if latin_chars / max(total, 1) > 0.5:
        return "en"
    return "other"


# ---------------------------------------------------------------------------
# Core crawl logic
# ---------------------------------------------------------------------------

def snapshot_page(page: Page, url: str, wait_ms: int = 3000) -> str | None:
    """Navigate to URL and return inlined HTML, or None on failure."""
    try:
        page.goto(url, wait_until="commit", timeout=30000)
        page.wait_for_timeout(wait_ms)
        html = page.evaluate(INLINE_CSS_JS)
        return html
    except Exception:
        # Retry with longer wait
        try:
            page.goto(url, wait_until="networkidle", timeout=45000)
            html = page.evaluate(INLINE_CSS_JS)
            return html
        except Exception:
            return None


def crawl_site(url: str, output_dir: Path, browser: Browser,
               session: requests.Session, max_pages: int = 4,
               wait_ms: int = 3000) -> dict:
    """Crawl a website: index page + sub-pages.

    Returns a result dict with status and metadata.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    resources_dir = output_dir / "resources"
    resources_dir.mkdir(exist_ok=True)

    page = browser.new_page(viewport={"width": 1280, "height": 800})

    try:
        # Step 1: Snapshot index page
        index_html = snapshot_page(page, url, wait_ms)
        if not index_html:
            page.close()
            return {"status": "failed_index", "url": url}

        # Validate content
        if not validate_page(index_html):
            page.close()
            return {"status": "empty_page", "url": url}

        # Language check
        lang = detect_language(index_html)
        if lang == "other":
            page.close()
            return {"status": "wrong_language", "url": url, "lang": lang}

        # Localize images
        index_html = localize_resources(index_html, url, resources_dir, session)

        # Save index
        (output_dir / "index.html").write_text(index_html, encoding="utf-8")

        # Step 2: Find and crawl sub-pages
        nav_links = extract_nav_links(index_html, url, max_links=max_pages)

        if not nav_links:
            # Single page only
            neutralize_external_links(output_dir)
            page.close()
            return {
                "status": "single_page",
                "url": url,
                "lang": lang,
                "pages": 1,
                "html_size": len(index_html),
            }

        # Crawl sub-pages
        url_to_file: dict[str, str] = {}
        used_names: set[str] = {"index.html"}
        pages_added = 0

        # Map index URL
        parsed_url = urlparse(url)
        root = f"{parsed_url.scheme}://{parsed_url.netloc}/"
        url_to_file[root] = "index.html"
        url_to_file[url] = "index.html"

        for i, sub_url in enumerate(nav_links):
            sub_html = snapshot_page(page, sub_url, wait_ms=2000)
            if not sub_html:
                continue
            if not validate_page(sub_html):
                continue

            # Localize images
            sub_html = localize_resources(sub_html, sub_url, resources_dir, session)

            # Save
            filename = safe_filename(sub_url, i + 1, used_names)
            (output_dir / filename).write_text(sub_html, encoding="utf-8")
            url_to_file[sub_url] = filename
            pages_added += 1

            if pages_added >= max_pages:
                break

        # Step 3: Relink pages to each other
        relink_pages(output_dir, url_to_file)

        # Step 4: Neutralize remaining external links
        neutralize_external_links(output_dir)

        page.close()
        return {
            "status": "multi_page" if pages_added > 0 else "single_page",
            "url": url,
            "lang": lang,
            "pages": 1 + pages_added,
            "html_size": sum(f.stat().st_size for f in output_dir.glob("*.html")),
        }

    except Exception as e:
        page.close()
        return {"status": "error", "url": url, "error": str(e)}


def expand_project(project_dir: Path, output_dir: Path, browser: Browser,
                   session: requests.Session, max_pages: int = 4,
                   wait_ms: int = 3000) -> dict:
    """Expand an existing WebRenderBench project to multi-page.

    Reads index.html, finds the original URL from internal links,
    then crawls sub-pages using Playwright.
    """
    index_html_path = project_dir / "index.html"
    if not index_html_path.exists():
        return {"status": "no_index", "project": project_dir.name}

    html = index_html_path.read_text(encoding="utf-8", errors="replace")

    # Find the original domain from http links in the HTML
    all_urls = re.findall(r'https?://([^/\s"\'<>]+)', html)
    # Filter out CDN/generic domains
    noise = {"google", "facebook", "twitter", "cdn", "fonts.g", "jquery",
             "bootstrap", "cloudflare", "gstatic", "w3.org", "schema.org",
             "gravatar", "youtube", "vimeo", "instagram", "linkedin", "pinterest"}
    real_domains = [d for d in all_urls
                    if not any(n in d.lower() for n in noise)]

    if not real_domains:
        return {"status": "no_domain", "project": project_dir.name}

    # Most common real domain
    from collections import Counter
    domain_counts = Counter(real_domains)
    main_domain = domain_counts.most_common(1)[0][0]
    base_url = f"https://{main_domain}/"

    # Also look for navigation links
    nav_links = extract_nav_links(html, base_url, max_links=max_pages)

    if not nav_links:
        # Try to find links from href patterns
        href_links = re.findall(rf'href="(https?://{re.escape(main_domain)}[^"]+)"', html)
        # Filter to navigable pages
        nav_links = []
        seen = set()
        for link in href_links:
            parsed = urlparse(link)
            path = parsed.path.rstrip("/")
            if not path or path == "/" or path in seen:
                continue
            if any(path.endswith(ext) for ext in (".jpg", ".png", ".gif", ".pdf", ".css", ".js", ".ico")):
                continue
            seen.add(path)
            nav_links.append(link)
            if len(nav_links) >= max_pages:
                break

    if not nav_links:
        return {"status": "no_nav_links", "project": project_dir.name}

    # Set up output
    out = output_dir / project_dir.name
    out.mkdir(parents=True, exist_ok=True)

    # Copy existing project
    shutil.copytree(project_dir, out, dirs_exist_ok=True)

    # Crawl sub-pages with Playwright
    resources_dir = out / "resources"
    resources_dir.mkdir(exist_ok=True)

    # Clean copied index.html: download remote images, inline remote CSS
    index_out = out / "index.html"
    index_html = index_out.read_text(encoding="utf-8", errors="replace")
    index_html = localize_resources(index_html, base_url, resources_dir, session)
    # Inline any remaining remote CSS
    soup = BeautifulSoup(index_html, "html.parser")
    for link in list(soup.find_all("link")):
        if not link.attrs:
            continue
        rel = " ".join(link.get("rel") or []).lower()
        href = link.get("href", "")
        if "stylesheet" in rel and href.startswith("http"):
            try:
                resp = session.get(href, timeout=10)
                if resp.status_code == 200:
                    style = soup.new_tag("style")
                    style.string = resp.text
                    link.replace_with(style)
                else:
                    link.decompose()
            except Exception:
                link.decompose()
    index_html = str(soup)
    index_out.write_text(index_html, encoding="utf-8")

    page = browser.new_page(viewport={"width": 1280, "height": 800})

    url_to_file: dict[str, str] = {base_url: "index.html"}
    used_names: set[str] = {"index.html"}
    pages_added = 0

    for i, sub_url in enumerate(nav_links):
        sub_html = snapshot_page(page, sub_url, wait_ms=wait_ms)
        if not sub_html:
            continue
        if not validate_page(sub_html):
            continue

        # Localize images
        sub_html = localize_resources(sub_html, sub_url, resources_dir, session)

        # Save
        filename = safe_filename(sub_url, i + 1, used_names)
        (out / filename).write_text(sub_html, encoding="utf-8")
        url_to_file[sub_url] = filename
        pages_added += 1

        if pages_added >= max_pages:
            break

    page.close()

    if pages_added == 0:
        # Clean up copied dir if nothing was expanded
        shutil.rmtree(out)
        return {"status": "crawl_failed", "project": project_dir.name}

    # Relink all pages
    relink_pages(out, url_to_file)
    neutralize_external_links(out)

    return {
        "status": "expanded",
        "project": project_dir.name,
        "pages_added": pages_added,
        "total_pages": 1 + pages_added,
    }


def clean_project(project_dir: Path, session: requests.Session) -> dict:
    """Clean an existing project: download remote images, inline CSS, neutralize links."""
    index_html_path = project_dir / "index.html"
    if not index_html_path.exists():
        return {"status": "no_index", "project": project_dir.name}

    resources_dir = project_dir / "resources"
    resources_dir.mkdir(exist_ok=True)

    total_remaining = 0

    for html_file in project_dir.glob("*.html"):
        html = html_file.read_text(encoding="utf-8", errors="replace")

        # Detect the base URL for resolving relative paths
        urls_in_html = re.findall(r'https?://([^/\s"\'<>]+)', html)
        base_url = f"https://{urls_in_html[0]}/" if urls_in_html else "https://example.com/"

        # Localize images
        cleaned = localize_resources(html, base_url, resources_dir, session)

        # Remove remaining external CSS links (inline them if possible)
        soup = BeautifulSoup(cleaned, "html.parser")
        for link in list(soup.find_all("link")):
            if not link.attrs:
                continue
            rel = " ".join(link.get("rel") or []).lower()
            href = link.get("href", "")
            if "stylesheet" in rel and href.startswith("http"):
                try:
                    resp = session.get(href, timeout=10)
                    if resp.status_code == 200:
                        style = soup.new_tag("style")
                        style.string = resp.text
                        link.replace_with(style)
                    else:
                        link.decompose()
                except Exception:
                    link.decompose()

        cleaned = str(soup)
        html_file.write_text(cleaned, encoding="utf-8")

        # Count truly remote references (exclude data-*-src attributes)
        remaining = len(re.findall(r'(?<![a-z-])src="https?://', cleaned))
        total_remaining += remaining

    # Neutralize external links
    neutralize_external_links(project_dir)

    return {
        "status": "cleaned",
        "project": project_dir.name,
        "remaining_remote_refs": total_remaining,
    }


# ---------------------------------------------------------------------------
# CLI entry points
# ---------------------------------------------------------------------------

def cmd_crawl(args):
    """Crawl sites from URL list."""
    url_file = Path(args.url_file)
    urls = [line.strip() for line in url_file.read_text().splitlines() if line.strip()]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Crawling {len(urls)} URLs with concurrency={args.concurrency}")

    session = build_requests_session(args.requests_proxy)
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            proxy={"server": args.browser_proxy} if args.browser_proxy else None,
        )

        for i, url in enumerate(urls):
            # Skip if already done
            parsed = urlparse(url)
            proj_name = re.sub(r"[^A-Za-z0-9._-]", "_", parsed.netloc)[:60]
            proj_dir = output_dir / proj_name

            if proj_dir.exists() and (proj_dir / "index.html").exists():
                print(f"[{i+1}/{len(urls)}] {proj_name}: SKIP (already exists)")
                continue

            t0 = time.time()
            result = crawl_site(url, proj_dir, browser, session,
                               max_pages=args.max_pages, wait_ms=args.wait)
            elapsed = time.time() - t0
            result["elapsed"] = round(elapsed, 1)
            results.append(result)

            status = result["status"]
            pages = result.get("pages", 0)
            print(f"[{i+1}/{len(urls)}] {proj_name}: {status} ({pages} pages, {elapsed:.1f}s)")

        browser.close()

    # Save results
    results_path = output_dir / "crawl_results.jsonl"
    with open(results_path, "w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Summary
    statuses = Counter(r["status"] for r in results)
    print(f"\nDone! {len(results)} processed:")
    for s, c in statuses.most_common():
        print(f"  {s}: {c}")


def cmd_expand(args):
    """Expand existing projects to multi-page."""
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    projects = sorted(d for d in input_dir.iterdir() if d.is_dir())
    if args.limit:
        projects = projects[:args.limit]

    print(f"Expanding {len(projects)} projects with concurrency={args.concurrency}")

    session = build_requests_session(args.requests_proxy)
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            proxy={"server": args.browser_proxy} if args.browser_proxy else None,
        )

        for i, proj in enumerate(projects):
            # Skip if already expanded
            out_proj = output_dir / proj.name
            if out_proj.exists() and len(list(out_proj.glob("*.html"))) > 1:
                print(f"[{i+1}/{len(projects)}] {proj.name}: SKIP")
                continue

            t0 = time.time()
            result = expand_project(proj, output_dir, browser, session,
                                   max_pages=args.max_pages, wait_ms=args.wait)
            elapsed = time.time() - t0
            result["elapsed"] = round(elapsed, 1)
            results.append(result)

            status = result["status"]
            pages = result.get("pages_added", 0)
            print(f"[{i+1}/{len(projects)}] {proj.name}: {status} (+{pages} pages, {elapsed:.1f}s)")

        browser.close()

    # Save results
    results_path = output_dir / "expand_results.jsonl"
    with open(results_path, "w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    from collections import Counter
    statuses = Counter(r["status"] for r in results)
    total_pages = sum(r.get("pages_added", 0) for r in results)
    print(f"\nDone! {statuses.get('expanded', 0)} expanded, {total_pages} pages added")


def cmd_clean(args):
    """Clean existing projects (download remote images)."""
    input_dir = Path(args.input_dir)
    projects = sorted(d for d in input_dir.iterdir() if d.is_dir())
    if args.limit:
        projects = projects[:args.limit]

    print(f"Cleaning {len(projects)} projects")

    session = build_requests_session(args.requests_proxy)
    results = []

    for i, proj in enumerate(projects):
        result = clean_project(proj, session)
        results.append(result)
        remaining = result.get("remaining_remote_refs", 0)
        print(f"[{i+1}/{len(projects)}] {proj.name}: {result['status']} (remaining={remaining})")

    from collections import Counter
    statuses = Counter(r["status"] for r in results)
    print(f"\nDone: {statuses}")


def main():
    parser = argparse.ArgumentParser(description="Playwright web crawler for training data")
    parser.add_argument("--browser-proxy", default="socks5://127.0.0.1:13659",
                        help="Proxy for Playwright/Chromium. Use 'socks5://' (NOT socks5h). "
                             "Set to '' for direct access.")
    parser.add_argument("--requests-proxy", default="socks5h://127.0.0.1:13659",
                        help="Proxy for requests library. 'socks5h://' enables remote DNS. "
                             "Set to '' for direct access.")
    parser.add_argument("--concurrency", type=int, default=1,
                        help="Number of concurrent browser pages (NOT browsers). "
                             "Mac M4 16GB: use 3-5. Server 64GB: use 15-20.")
    parser.add_argument("--max-pages", type=int, default=4,
                        help="Max sub-pages to crawl per site")
    parser.add_argument("--wait", type=int, default=3000,
                        help="Wait time (ms) after page load for rendering")

    subparsers = parser.add_subparsers(dest="command")

    # crawl
    p_crawl = subparsers.add_parser("crawl", help="Crawl new sites from URL list")
    p_crawl.add_argument("--url-file", required=True, help="File with one URL per line")
    p_crawl.add_argument("--output-dir", required=True, help="Output directory")

    # expand
    p_expand = subparsers.add_parser("expand", help="Expand existing projects to multi-page")
    p_expand.add_argument("--input-dir", required=True, help="Directory with project subdirs")
    p_expand.add_argument("--output-dir", required=True, help="Output directory for expanded")
    p_expand.add_argument("--limit", type=int, default=None, help="Limit projects to process")

    # clean
    p_clean = subparsers.add_parser("clean", help="Clean projects (download remote images)")
    p_clean.add_argument("--input-dir", required=True, help="Directory with project subdirs")
    p_clean.add_argument("--limit", type=int, default=None, help="Limit projects to process")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "crawl":
        cmd_crawl(args)
    elif args.command == "expand":
        cmd_expand(args)
    elif args.command == "clean":
        cmd_clean(args)


if __name__ == "__main__":
    from collections import Counter
    main()
