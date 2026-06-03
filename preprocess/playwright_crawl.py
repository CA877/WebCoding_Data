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
import multiprocessing as mp
import os
import queue
import re
import shutil
import threading
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Browser, Page

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Fallback image IDs for picsum.photos.
# When a remote image cannot be downloaded, we use https://picsum.photos/id/{ID}/800/600
# directly in the HTML (not downloaded). The model learns to reference this URL pattern.
# All IDs verified working — each returns a consistent, real photograph.
PICSUM_IDS = [
    10, 11, 12, 13, 14, 15, 16, 17, 18, 19,
    20, 21, 22, 23, 24, 25, 26, 27, 28, 29,
    30, 31, 32, 33, 34, 35, 36, 37, 38, 39,
    40, 41, 42, 43, 44, 45, 46, 47, 48, 49,
    50, 51, 52, 53, 54, 55, 56, 57, 58, 59,
    60, 61, 62, 63, 64, 65, 66, 67, 68, 69,
    70, 71, 72, 73, 74, 75, 76, 77, 78, 79,
    80, 81, 82, 83, 84, 85, 86, 87, 88, 89,
    90, 91, 92, 93, 94, 95, 96, 97, 98, 99,
    100, 101, 102, 103, 104, 106, 107, 108, 109, 110,
]


def _fallback_url(index: int) -> str:
    """Generate a picsum.photos fallback URL for a given index."""
    pid = PICSUM_IDS[index % len(PICSUM_IDS)]
    return f"https://picsum.photos/id/{pid}/800/600"

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
    // Unwrap <noscript> tags — preserve fallback images for lazy-loaded content
    document.querySelectorAll('noscript').forEach(s => {
        const content = s.textContent || s.innerHTML;
        if (content.includes('<')) {
            const temp = document.createElement('div');
            temp.innerHTML = content;
            while (temp.firstChild) s.parentNode.insertBefore(temp.firstChild, s);
        }
        s.remove();
    });
    // Remove tracking/analytics scripts (both remote and inline)
    const trackingDomains = ['google-analytics.com', 'googletagmanager.com',
        'googlesyndication.com', 'facebook.net', 'connect.facebook.com',
        'doubleclick.net', 'hotjar.com', 'mixpanel.com', 'segment.com',
        'optimizely.com', 'tiktok.com', 'pinterest.com', 'linkedin.com', 'twitter.com'];
    document.querySelectorAll('script[src]').forEach(s => {
        const src = (s.getAttribute('src') || '').toLowerCase();
        const id = (s.getAttribute('id') || '').toLowerCase();
        if (trackingDomains.some(d => src.includes(d))) s.remove();
        if (['monsterinsights', 'frontend-gtag', 'gtag'].some(k => src.includes(k) || id.includes(k))) s.remove();
    });
    const trackingKw = ['google-analytics', 'googletagmanager', 'gtag', 'fbq(',
        'hotjar', 'adsbygoogle', '_gaq', 'ga(', 'mixpanel', 'segment',
        'optimizely', 'googlesyndication', 'monsterinsights', 'frontend-gtag'];
    document.querySelectorAll('script:not([src])').forEach(s => {
        const t = s.textContent.toLowerCase();
        if (trackingKw.some(k => t.includes(k))) s.remove();
    });
    // Remove noise links
    document.querySelectorAll('link[rel*="preconnect"], link[rel*="prefetch"], link[rel*="dns-prefetch"], link[rel*="canonical"], link[rel*="manifest"], link[rel*="alternate"]').forEach(l => l.remove());
    // Remove comments
    const walker = document.createTreeWalker(document, NodeFilter.SHOW_COMMENT);
    const comments = [];
    while (walker.nextNode()) comments.push(walker.currentNode);
    comments.forEach(c => c.remove());

    // Ensure charset declaration exists
    if (!document.querySelector('meta[charset]') && !document.querySelector('meta[http-equiv="Content-Type"]')) {
        const meta = document.createElement('meta');
        meta.setAttribute('charset', 'UTF-8');
        const head = document.head || document.querySelector('head');
        if (head) head.prepend(meta);
    }
    // Fix LiteSpeed-blocked scripts
    document.querySelectorAll('script[type="litespeed/javascript"]').forEach(s => {
        s.setAttribute('type', 'text/javascript');
    });

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


def _resolve_proxy(explicit: str, env_names: tuple[str, ...]) -> str:
    """Prefer an explicit proxy; otherwise fall back to common env vars."""
    if explicit:
        return explicit
    for name in env_names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def resolve_browser_proxy(explicit: str) -> str:
    """Resolve proxy for Chromium/Playwright."""
    return _resolve_proxy(
        explicit,
        ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"),
    )


def resolve_requests_proxy(explicit: str) -> str:
    """Resolve proxy for requests-based resource downloads."""
    return _resolve_proxy(
        explicit,
        ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"),
    )


MAX_RESOURCES_PER_PAGE = 50  # Limit downloads to prevent hanging on heavy pages


def _is_alive(session: requests.Session, url: str) -> bool:
    """Quick HEAD check before attempting a full download."""
    try:
        r = session.head(url, timeout=2, allow_redirects=True)
        return r.status_code < 400
    except Exception:
        return False


def _download_js(session: requests.Session, url: str, resources_dir: Path) -> str | None:
    """Download a remote JS file to resources/ dir. Returns relative path or None."""
    if not _is_alive(session, url):
        return None
    try:
        resp = session.get(url, timeout=(5, 10), allow_redirects=True)
        if resp.status_code == 200 and len(resp.content) >= 10:
            h = hashlib.md5(url.encode()).hexdigest()[:8]
            name = Path(urlparse(url).path).name or "script.js"
            name = f"{h}_{name}"
            name = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80]
            if not name.endswith(".js"):
                name += ".js"
            target = resources_dir / name
            target.write_bytes(resp.content)
            return f"./resources/{name}"
    except Exception:
        pass
    return None


def _download_css(session: requests.Session, url: str, resources_dir: Path,
                   _sanitize_urls: bool = True) -> str | None:
    """Download a remote CSS file to resources/ dir. Returns relative path or None.

    When _sanitize_urls is True (default in fast-clean mode), replaces remote
    url() references inside the CSS with placeholders so the CSS doesn't depend
    on any external resources.
    """
    try:
        resp = session.get(url, timeout=(5, 10), allow_redirects=True)
        if resp.status_code == 200 and len(resp.content) >= 10:
            h = hashlib.md5(url.encode()).hexdigest()[:8]
            name = Path(urlparse(url).path).name or "style.css"
            name = f"{h}_{name}"
            name = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80]
            if not name.endswith(".css"):
                name += ".css"
            target = resources_dir / name
            css_text = resp.content.decode("utf-8", errors="replace")
            if _sanitize_urls:
                _font_exts = (".woff", ".woff2", ".ttf", ".otf", ".eot")
                _counter = [0]
                def _replace_css_remote_url(m):
                    inner = m.group(1).strip("'\"")
                    if not (inner.startswith("http") or inner.startswith("//")):
                        return m.group(0)
                    if any(inner.lower().endswith(ext) for ext in _font_exts):
                        return "url()"  # drop remote font — browser falls back
                    placeholder = _picsum_url(_counter[0])
                    _counter[0] += 1
                    return f"url({placeholder})"
                css_text = re.sub(r'url\(["\']?([^)]+?)["\']?\)', _replace_css_remote_url, css_text)
            target.write_text(css_text, encoding="utf-8")
            return f"./resources/{name}"
    except Exception:
        pass
    return None


def download_resource(session: requests.Session, url: str, resources_dir: Path,
                      fallback_index: int = -1) -> str | None:
    """Download a resource to resources/ dir. Returns relative path or None.

    If download fails and fallback_index >= 0, downloads a fallback image instead.
    """
    try:
        resp = session.get(url, timeout=(2, 3), allow_redirects=True)
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

    # Fallback: use a stable image URL directly (model learns to reference URLs)
    if fallback_index >= 0:
        return _fallback_url(fallback_index)

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


def rewrite_to_existing_resources(html: str, page_url: str, resources_dir: Path) -> str:
    """Rewrite remote URLs in HTML to point to already-downloaded resources.

    No new downloads — only rewrites URLs whose file already exists in resources/.
    Used by expand sub-pages to share resources with the index page.
    """
    if not resources_dir.exists():
        return html
    # Build lookup: md5_hash_prefix -> local filename
    existing = {}
    for f in resources_dir.iterdir():
        if f.is_file() and "_" in f.name:
            prefix = f.name.split("_", 1)[0]
            existing[prefix] = f"./resources/{f.name}"

    soup = BeautifulSoup(html, "html.parser")

    # Rewrite <img>, <source>, <input type="image">
    for tag in soup.find_all(["img", "source", "input"]):
        if tag.name == "input" and (tag.get("type") or "").lower() != "image":
            continue
        for attr in ("src", "data-src", "data-lazy-src"):
            val = tag.get(attr)
            if not val or val.startswith("data:") or val.startswith("./resources/"):
                continue
            abs_url = urljoin(page_url, val)
            if abs_url.startswith("http"):
                h = hashlib.md5(abs_url.encode()).hexdigest()[:8]
                if h in existing:
                    tag[attr] = existing[h]

    # Rewrite CSS background-image url()
    for style_tag in soup.find_all("style"):
        if style_tag.string:
            def _rewrite_bg(m):
                url = m.group(1).strip("'\"")
                abs_url = urljoin(page_url, url)
                if abs_url.startswith("http"):
                    h = hashlib.md5(abs_url.encode()).hexdigest()[:8]
                    if h in existing:
                        return f"url({existing[h]})"
                return m.group(0)
            style_tag.string = re.sub(r'url\(([^)]+)\)', _rewrite_bg, style_tag.string)

    # Rewrite <link rel="stylesheet"> to existing local CSS
    for link in soup.find_all("link"):
        rel = " ".join(link.get("rel") or []).lower()
        href = link.get("href", "")
        if "stylesheet" in rel and href.startswith("http"):
            h = hashlib.md5(href.encode()).hexdigest()[:8]
            if h in existing:
                link["href"] = existing[h]
            else:
                link.decompose()

    # Rewrite <script src>
    for script in soup.find_all("script"):
        src = script.get("src", "")
        if src and src.startswith("http"):
            h = hashlib.md5(src.encode()).hexdigest()[:8]
            if h in existing:
                script["src"] = existing[h]
            else:
                script.decompose()

    return str(soup)


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

    # Ensure charset declaration
    head = soup.find("head")
    if head and not soup.find("meta", attrs={"charset": True}) and not soup.find("meta", attrs={"http-equiv": "Content-Type"}):
        meta = soup.new_tag("meta", charset="UTF-8")
        head.insert(0, meta)

    # Fix LiteSpeed-blocked scripts
    for script in soup.find_all("script", type="litespeed/javascript"):
        script["type"] = "text/javascript"

    # Download remote JS files to local; remove tracking/analytics scripts
    TRACKING_KEYWORDS = (
        "google-analytics", "googletagmanager", "gtag", "facebook", "fbq(",
        "hotjar", "adsbygoogle", "_gaq", "ga(", "googlesyndication",
        "mixpanel", "segment", "optimizely", "tiktok",
        "pinterest", "twitter", "linkedin", "monsterinsights", "frontend-gtag",
    )
    TRACKING_DOMAINS = (
        "google-analytics.com", "googletagmanager.com", "googlesyndication.com",
        "facebook.net", "connect.facebook.com", "doubleclick.net",
        "hotjar.com", "mixpanel.com", "segment.com", "optimizely.com",
        "tiktok.com", "pinterest.com", "linkedin.com", "twitter.com",
    )
    for script in list(soup.find_all("script")):
        src = script.get("src", "")
        script_identity = " ".join(
            str(script.get(attr, "")) for attr in ("id", "class", "data-wpfc-render", "data-wp-strategy")
        ).lower()
        if src:
            abs_src = urljoin(page_url, src)
            # Skip tracking/analytics scripts
            src_lower = src.lower()
            abs_src_lower = abs_src.lower()
            if (
                any(d in abs_src_lower for d in TRACKING_DOMAINS)
                or any(kw in src_lower or kw in abs_src_lower or kw in script_identity for kw in TRACKING_KEYWORDS)
            ):
                script.decompose()
                continue
            # Remove broken MHTML cid: references (WebRenderBench artifacts)
            if src.startswith("cid:"):
                script.decompose()
                continue
            # Download remote JS file to local
            if abs_src.startswith("http"):
                local = _download_js(session, abs_src, resources_dir)
                if local:
                    script["src"] = local
                else:
                    # Download failed — remove (broken offline)
                    script.decompose()
        elif script.string:
            # Inline script — remove only if it's tracking/analytics
            text_lower = script.string.lower()
            if any(kw in text_lower for kw in TRACKING_KEYWORDS):
                script.decompose()
    fallback_idx = 0
    download_count = 0

    # Process <img>, <source>, and <input type="image"> tags
    # NOTE: Skip image downloads — keep original URLs (fast mode)
    for tag in list(soup.find_all(["img", "source", "input"])):
        if tag.name == "input" and (tag.get("type") or "").lower() != "image":
            continue
        for attr in ("src", "data-src", "data-lazy-src", "data-cke-saved-src",
                      "nitro-lazy-src", "data-original", "data-lazy"):
            val = tag.get(attr)
            if not val or val.startswith("data:") or val.startswith("./resources/"):
                continue
            abs_url = urljoin(page_url, val)
            if abs_url.startswith("http"):
                # Keep original URL — don't download, don't replace
                tag[attr] = abs_url
        try:
            if tag.get("srcset"):
                del tag["srcset"]
        except (AttributeError, TypeError):
            pass

    # Process data-src on any element — keep original URLs, skip downloads
    for tag in list(soup.find_all(attrs={"data-src": True})):
        val = tag["data-src"]
        if val.startswith("data:") or val.startswith("./resources/"):
            continue
        abs_url = urljoin(page_url, val)
        if abs_url.startswith("http"):
            tag["data-src"] = abs_url

    # Clean up lazy attributes — keep original URLs
    LAZY_ATTRS = ("data-lazy-src", "data-src", "nitro-lazy-src", "data-original", "data-lazy")
    for img in soup.find_all("img"):
        # Remove loading="lazy" — we want immediate rendering
        if img.get("loading"):
            del img["loading"]

    # Deduplicate adjacent <img> tags with the same src (from noscript unwrap).
    # Only remove if the previous kept img has the same src — logos/decorations
    # legitimately reappear in different sections.
    all_imgs = list(soup.find_all("img"))
    prev_src = ""
    for img in all_imgs:
        cur_src = img.get("src", "")
        if cur_src and cur_src == prev_src:
            img.decompose()
        else:
            prev_src = cur_src

    # Remove CKEditor artifacts and other data-*-src/href with remote URLs
    for tag in soup.find_all(True):
        attrs_to_remove = [k for k in tag.attrs
                          if k.startswith("data-cke-saved-") or
                          (k.startswith("data-") and k.endswith(("-src", "-href"))
                           and isinstance(tag[k], str) and tag[k].startswith("http"))]
        for attr in attrs_to_remove:
            del tag[attr]

    # Remove off-canvas / mobile-nav panels — hidden by JS, but render as visible
    # blocks at the page bottom when JS is missing.
    # Use word-boundary matching and only target container-level elements (div/nav/aside).
    OFFCANVAS_RE = re.compile(
        r'\b(?:off-?canvas|offcanvas)\b', re.I
    )
    for el in list(soup.find_all(class_=OFFCANVAS_RE)):
        if el.name in ("div", "nav", "aside", "section"):
            el.decompose()

    # Trim carousel/slider containers — keep only first few slides.
    # Without the original JS, all slides stack vertically causing massive page height.
    # Match whole class names (word-bounded) to avoid false positives like "slide-in".
    CAROUSEL_CLASS_RE = re.compile(
        r'\b(?:swiper-wrapper|slick-track|owl-stage|splide__list|flickity-slider'
        r'|carousel-inner|x-slide-container|glide__slides'
        r'|slides|slider-track)\b', re.I
    )
    MAX_SLIDES = 3
    for container in soup.find_all(class_=CAROUSEL_CLASS_RE):
        element_children = [c for c in container.children if hasattr(c, 'name') and c.name]
        if len(element_children) > MAX_SLIDES + 2:
            # Extra safety: check that children look homogeneous (same tag + similar classes)
            first_tag = element_children[0].name
            if all(c.name == first_tag for c in element_children[:6]):
                for child in element_children[MAX_SLIDES:]:
                    child.decompose()

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

    # Remove height/min-height from empty containers (left after iframe/video removal)
    for tag in soup.find_all(style=True):
        style_str = tag.get("style", "")
        if not style_str or "height" not in style_str:
            continue
        text = tag.get_text(strip=True)
        has_visible_child = bool(tag.find(["img", "svg", "canvas", "video", "iframe",
                                           "input", "select", "textarea", "button", "table"]))
        if not text and not has_visible_child:
            new_style = re.sub(r'(min-)?height\s*:\s*[^;]+;?\s*', '', style_str)
            if new_style.strip():
                tag["style"] = new_style
            else:
                del tag["style"]

    # Non-image extensions that should NOT get picsum fallbacks
    _NON_IMAGE_EXTS = {".woff", ".woff2", ".ttf", ".otf", ".eot", ".css", ".js", ".json", ".xml", ".svg"}

    # Process CSS background-image url() in style attributes
    # Skip image downloads — keep original URLs for background images
    def replace_bg_url(match):
        nonlocal download_count
        img_url = match.group(1).strip("\"'")
        if img_url.startswith("data:") or img_url.startswith("./resources/") or "picsum.photos" in img_url:
            return match.group(0)
        abs_url = urljoin(page_url, img_url)
        if not abs_url.startswith("http"):
            return match.group(0)
        # Only download non-image resources (fonts); skip images
        url_path = urlparse(abs_url).path.lower()
        ext = Path(url_path).suffix if url_path else ""
        is_non_image = ext in _NON_IMAGE_EXTS
        if is_non_image:
            if download_count >= MAX_RESOURCES_PER_PAGE:
                return 'url("")'
            local = download_resource(session, abs_url, resources_dir, fallback_index=-1)
            download_count += 1
            if local:
                return f"url({local})"
            return 'url("")'
        # Keep original image URL — don't download
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
                resp = session.get(href, timeout=(5, 10))
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

            # Try to match URL path to a local file
            parsed = urlparse(href)
            path = parsed.path.rstrip("/")
            matched = None

            # Strategy 1: exact basename match (e.g. "page.html")
            basename = Path(path).name if path else ""
            if basename and basename in local_files:
                matched = basename

            # Strategy 2: path slug → slug.html (e.g. "/contact-us/" → "contact-us.html")
            if not matched and path:
                slug = path.rsplit("/", 1)[-1]
                if slug:
                    candidate = slug + ".html" if "." not in slug else slug
                    if candidate in local_files:
                        matched = candidate

            # Strategy 3: safe_filename style match (e.g. "page_1.html")
            if not matched and path:
                slug = path.strip("/").replace("/", "_")
                slug = re.sub(r"[^A-Za-z0-9_-]", "", slug)
                if slug:
                    for lf in local_files:
                        if slug in lf:
                            matched = lf
                            break

            a["href"] = matched if matched else "#"
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


DEAD_PAGE_MARKERS = [
    "account has been suspended",
    "account suspended",
    "this site can't be reached",
    "domain is for sale",
    "buy this domain",
    "page not found",
    "website is under construction",
    "coming soon",
    "under maintenance",
    "parked domain",
    "this domain is parked",
    "web hosting default page",
    "apache2 default page",
    "welcome to nginx",
    "index of /",
    "403 forbidden",
    "site not found",
    "expired domain",
    # Cloudflare / bot-detection / CAPTCHA pages
    "verify you are human",
    "checking your browser",
    "attention required",
    "just a moment",
    "enable javascript and cookies to continue",
    "ray id:",
    "performance & security by cloudflare",
    "please turn javascript on and reload the page",
    "access denied",
    "you have been blocked",
    "please verify you are a human",
    "complete the security check",
    # Other anti-bot / paywall / cookie walls
    "enable cookies to continue",
    "please enable cookies",
    "browser check",
    "robot challenge screen",
    "checking the site connection security",
    "this page requires cookies to be enabled in your browser settings",
    "sgcaptcha",
    "powcaptcha",
]


def validate_page(html: str, min_text_len: int = 50) -> bool:
    """Check if page has enough visible content and isn't a dead/parked page."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(strip=True)
    if len(text) < min_text_len:
        return False
    text_lower = text.lower()
    for marker in DEAD_PAGE_MARKERS:
        if marker in text_lower:
            return False
    return True


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

def snapshot_page(
    page: Page,
    url: str,
    wait_ms: int = 5000,
    timeout_ms: int = 30000,
    retry_timeout_ms: int | None = None,  # kept for backward compat, no longer used
) -> str | None:
    """Navigate to URL and return inlined HTML, or None on failure. No retry."""
    # Try commit first (fastest, works for most sites)
    try:
        page.goto(url, wait_until="commit", timeout=min(timeout_ms, 10000))
        page.wait_for_timeout(max(wait_ms, 5000))  # extra time for JS to render
        return page.evaluate(INLINE_CSS_JS)
    except Exception:
        pass
    # Fallback: domcontentloaded (slower but works for more sites through proxy)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(wait_ms)
        return page.evaluate(INLINE_CSS_JS)
    except Exception:
        return None


def crawl_site(url: str, output_dir: Path, browser: Browser,
               session: requests.Session, max_pages: int = 4,
               wait_ms: int = 3000, subpage_wait_ms: int = 2000,
               timeout_ms: int = 20000) -> dict:
    """Crawl a website: index page + sub-pages.

    Returns a result dict with status and metadata.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    resources_dir = output_dir / "resources"
    resources_dir.mkdir(exist_ok=True)

    page = browser.new_page(viewport={"width": 1280, "height": 800})

    try:
        # Step 1: Snapshot index page
        index_html = snapshot_page(
            page,
            url,
            wait_ms,
            timeout_ms=timeout_ms,
        )
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
                "pages_added": 0,
                "has_single_page": True,
                "has_multi_page": False,
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
            sub_html = snapshot_page(
                page,
                sub_url,
                wait_ms=subpage_wait_ms,
                timeout_ms=timeout_ms,
            )
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
            "pages_added": pages_added,
            "has_single_page": True,
            "has_multi_page": pages_added > 0,
            "html_size": sum(f.stat().st_size for f in output_dir.glob("*.html")),
        }

    except Exception as e:
        page.close()
        return {"status": "error", "url": url, "error": str(e)}


def crawl_one_process(payload: tuple[str, str, str, str, str, int, int, int, int, int]) -> tuple[str, dict]:
    """Process-isolated crawl worker.

    Playwright's sync API is greenlet-backed and unsafe to share across threads.
    A separate process per worker gives each task its own driver and browser.
    """
    (
        url,
        proj_name,
        proj_dir,
        browser_proxy,
        requests_proxy,
        max_pages,
        wait_ms,
        subpage_wait_ms,
        timeout_ms,
        retry_timeout_ms,
    ) = payload
    session = build_requests_session(requests_proxy)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            proxy={"server": browser_proxy} if browser_proxy else None,
        )
        try:
            t0 = time.time()
            try:
                result = crawl_site(
                    url,
                    Path(proj_dir),
                    browser,
                    session,
                    max_pages=max_pages,
                    wait_ms=wait_ms,
                    subpage_wait_ms=subpage_wait_ms,
                    timeout_ms=timeout_ms,
                )
            except Exception as e:
                result = {"status": "error", "url": url, "error": str(e)}
            result["elapsed"] = round(time.time() - t0, 1)
            return proj_name, result
        finally:
            browser.close()


def crawl_one_process_entry(payload: tuple, result_queue) -> None:
    """Run one crawl payload in a killable process and report through a queue."""
    proj_name = str(payload[1])
    try:
        result_queue.put(crawl_one_process(payload))
    except BaseException as e:
        result_queue.put((proj_name, {"status": "error", "url": payload[0], "error": str(e)}))


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
                resp = session.get(href, timeout=(5, 10))
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
    total_fails = 0

    for i, sub_url in enumerate(nav_links):
        sub_html = snapshot_page(page, sub_url, wait_ms=wait_ms)
        if not sub_html:
            total_fails += 1
            if total_fails >= 3:
                break
            continue
        if not validate_page(sub_html):
            total_fails += 1
            if total_fails >= 3:
                break
            continue

        # Success — keep going, no fail limit on successes

        # Rewrite remote URLs to existing local resources (no new downloads)
        sub_html = rewrite_to_existing_resources(sub_html, sub_url, resources_dir)

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


def expand_one_process(payload: tuple[str, str, str, str, int, int]) -> tuple[str, dict]:
    """Process-isolated expand worker; see crawl_one_process."""
    proj_dir, output_dir, browser_proxy, requests_proxy, max_pages, wait_ms = payload
    project_dir = Path(proj_dir)
    session = build_requests_session(requests_proxy)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            proxy={"server": browser_proxy} if browser_proxy else None,
        )
        try:
            t0 = time.time()
            try:
                result = expand_project(project_dir, Path(output_dir), browser, session,
                                        max_pages=max_pages, wait_ms=wait_ms)
            except Exception as e:
                result = {"status": "error", "project": project_dir.name, "error": str(e)}
            result["elapsed"] = round(time.time() - t0, 1)
            return project_dir.name, result
        finally:
            browser.close()


def expand_one_process_entry(payload: tuple[str, str, str, str, int, int], result_queue: mp.Queue) -> None:
    """mp.Process entry point for expand with site-timeout support."""
    result_queue.put(expand_one_process(payload))


# Placeholder image config — picsum.photos/id/{id}/{w}/{h} returns real photos
# IDs 1-200 cover diverse subjects; sizes match common web image dimensions
# picsum.photos valid IDs: 0-1084, excluding known 404s/timeouts
_PICSUM_UNAVAILABLE = {
    86, 97, 105, 138, 148, 150, 188, 200, 205, 207, 210, 224, 226, 245, 246,
    262, 285, 286, 298, 303, 332, 333, 346, 359, 394, 414, 422, 438, 449,
    462, 463, 470, 489, 540, 561, 578, 587, 589, 592, 595, 597, 601, 624,
    632, 636, 644, 647, 673, 697, 706, 707, 708, 709, 710, 711, 712, 713,
    714, 720, 725, 734, 745, 746, 747, 748, 749, 750, 751, 752, 753, 754,
    759, 761, 762, 763, 771, 792, 801, 812, 843, 850, 854, 895, 897, 899,
    917, 920, 934, 947, 956, 963, 968, 1007, 1017, 1030, 1034, 1046,
}
_PICSUM_IDS = [i for i in range(0, 1085) if i not in _PICSUM_UNAVAILABLE]  # 988 unique photos
_PICSUM_SIZES = [
    (300, 200), (400, 300), (350, 250), (250, 250),
    (200, 150), (150, 150), (320, 240), (280, 180),
    (360, 240), (200, 200), (240, 160), (180, 180),
    (300, 300), (400, 250), (350, 200), (260, 200),
]
PLACEHOLDER_ICON = "https://picsum.photos/id/1/32/32"

# Placeholder CSS — only lightweight/non-invasive CSS that won't break inline layouts
_PLACEHOLDER_CSS = [
    "https://cdnjs.cloudflare.com/ajax/libs/normalize/8.0.1/normalize.min.css",
    "https://cdnjs.cloudflare.com/ajax/libs/animate.css/4.1.1/animate.min.css",
    "https://cdnjs.cloudflare.com/ajax/libs/hover.css/2.3.1/css/hover-min.css",
    "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css",
    "https://cdnjs.cloudflare.com/ajax/libs/hint.css/2.7.0/hint.min.css",
    "https://cdnjs.cloudflare.com/ajax/libs/aos/2.3.4/aos.css",
    "https://cdnjs.cloudflare.com/ajax/libs/lightbox2/2.11.4/css/lightbox.min.css",
    "https://cdnjs.cloudflare.com/ajax/libs/toastr.js/2.1.4/toastr.min.css",
]

# Placeholder JS — common CDN scripts (real, stable URLs)
_PLACEHOLDER_JS = [
    "https://cdnjs.cloudflare.com/ajax/libs/jquery/3.7.1/jquery.min.js",
    "https://cdnjs.cloudflare.com/ajax/libs/lodash.js/4.17.21/lodash.min.js",
    "https://cdnjs.cloudflare.com/ajax/libs/axios/1.6.2/axios.min.js",
    "https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.4/gsap.min.js",
    "https://cdnjs.cloudflare.com/ajax/libs/moment.js/2.30.1/moment.min.js",
    "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js",
    "https://cdnjs.cloudflare.com/ajax/libs/animejs/3.2.2/anime.min.js",
    "https://cdnjs.cloudflare.com/ajax/libs/aos/2.3.4/aos.js",
]

# Placeholder fonts — Google Fonts (real, stable URLs)
_PLACEHOLDER_FONTS = [
    "https://fonts.googleapis.com/css2?family=Roboto:wght@400;700&display=swap",
    "https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;600&display=swap",
    "https://fonts.googleapis.com/css2?family=Lato:wght@400;700&display=swap",
    "https://fonts.googleapis.com/css2?family=Montserrat:wght@400;700&display=swap",
    "https://fonts.googleapis.com/css2?family=Poppins:wght@400;600&display=swap",
    "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700&display=swap",
    "https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700&display=swap",
    "https://fonts.googleapis.com/css2?family=Nunito:wght@400;700&display=swap",
]


def _picsum_url(idx: int, w: int = 0, h: int = 0) -> str:
    """Return a picsum.photos URL with deterministic photo ID.

    If w/h are given (from original tag attributes), use them.
    Otherwise cycle through default sizes.
    """
    photo_id = _PICSUM_IDS[idx % len(_PICSUM_IDS)]
    if w > 0 and h > 0:
        # Clamp to reasonable range for picsum
        w = max(50, min(w, 2000))
        h = max(50, min(h, 2000))
    else:
        w, h = _PICSUM_SIZES[idx % len(_PICSUM_SIZES)]
    return f"https://picsum.photos/id/{photo_id}/{w}/{h}"


def _parse_img_dimensions(tag) -> tuple[int, int]:
    """Try to extract width/height from an HTML tag's attributes, inline style, or CSS class hints."""
    w, h = 0, 0
    try:
        w_raw = tag.get("width", "")
        h_raw = tag.get("height", "")
        # Handle "100%" or "auto"
        if str(w_raw).isdigit():
            w = int(w_raw)
        if str(h_raw).isdigit():
            h = int(h_raw)
    except (ValueError, TypeError):
        pass
    # Try inline style
    if (w == 0 or h == 0) and tag.get("style"):
        style = tag["style"]
        wm = re.search(r'width:\s*(\d+)px', style)
        hm = re.search(r'height:\s*(\d+)px', style)
        if wm:
            w = int(wm.group(1))
        if hm:
            h = int(hm.group(1))
    # Try CSS class hints for common patterns like "size-thumbnail", "wp-image-150x150"
    if w == 0 or h == 0:
        cls = " ".join(tag.get("class") or [])
        dim_m = re.search(r'(\d{2,4})x(\d{2,4})', cls)
        if dim_m:
            w, h = int(dim_m.group(1)), int(dim_m.group(2))
    return w, h


def clean_project_fast(project_dir: Path, session: requests.Session | None = None) -> dict:
    """Clean project with minimal network — download CSS/JS, placeholder everything else.

    CSS/JS → download to resources/ and reference locally
    Images → picsum.photos real photos (198 unique IDs × 12 sizes)
    Fonts → Google Fonts placeholder URLs
    """
    index_html_path = project_dir / "index.html"
    if not index_html_path.exists():
        return {"status": "no_index", "project": project_dir.name}

    # Remove only image/video files from resources/ — keep CSS, JS, and fonts
    resources_dir = project_dir / "resources"
    resources_dir.mkdir(exist_ok=True)
    _keep_exts = {".css", ".js", ".jsx", ".ts", ".tsx",
                  ".woff", ".woff2", ".ttf", ".otf", ".eot"}
    for f in list(resources_dir.iterdir()) if resources_dir.exists() else []:
        if f.is_file() and f.suffix.lower() not in _keep_exts:
            f.unlink()

    img_idx = 0
    css_idx = 0
    js_idx = 0
    font_idx = 0

    for html_file in project_dir.glob("*.html"):
        html = html_file.read_text(encoding="utf-8", errors="replace")

        # Remove IE conditional comments and HTML comments
        html = re.sub(r'<!--\[if[^\]]*\]>.*?<!\[endif\]-->', '', html, flags=re.DOTALL)
        html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)

        soup = BeautifulSoup(html, "html.parser")

        # Ensure charset
        head = soup.find("head")
        if head and not soup.find("meta", attrs={"charset": True}):
            meta = soup.new_tag("meta", charset="UTF-8")
            head.insert(0, meta)

        # Remote CSS → download to resources/; fonts/icons → placeholder URL
        for link in list(soup.find_all("link")):
            rel = " ".join(link.get("rel") or []).lower()
            href = link.get("href", "")
            if not (href.startswith("http") or href.startswith("//")):
                continue  # keep all local links (./resources/*.css etc.)
            href_lower = href.lower()
            if "stylesheet" in rel or href_lower.endswith(".css"):
                if "font" in href_lower:
                    link["href"] = _PLACEHOLDER_FONTS[font_idx % len(_PLACEHOLDER_FONTS)]
                    font_idx += 1
                elif session:
                    local = _download_css(session, href, resources_dir)
                    if local:
                        link["href"] = local
                        css_idx += 1
                    else:
                        link["href"] = _PLACEHOLDER_CSS[css_idx % len(_PLACEHOLDER_CSS)]
                        css_idx += 1
                else:
                    link["href"] = _PLACEHOLDER_CSS[css_idx % len(_PLACEHOLDER_CSS)]
                    css_idx += 1
            elif "font" in href_lower:
                link["href"] = _PLACEHOLDER_FONTS[font_idx % len(_PLACEHOLDER_FONTS)]
                font_idx += 1
            elif "icon" in rel:
                link["href"] = PLACEHOLDER_ICON
            elif "preconnect" in rel or "dns-prefetch" in rel:
                link.decompose()
            else:
                link.decompose()

        # Remote JS → download to resources/; fallback to CDN placeholder
        for script in list(soup.find_all("script")):
            src = script.get("src", "")
            if src.startswith("http") or src.startswith("//"):
                if session:
                    local = _download_js(session, src, resources_dir)
                    if local:
                        script["src"] = local
                        js_idx += 1
                    else:
                        script["src"] = _PLACEHOLDER_JS[js_idx % len(_PLACEHOLDER_JS)]
                        js_idx += 1
                else:
                    script["src"] = _PLACEHOLDER_JS[js_idx % len(_PLACEHOLDER_JS)]
                    js_idx += 1
            elif src.startswith("cid:"):
                script.decompose()

        # Replace remote URLs in <meta> tags (og:image, twitter:image, etc.)
        for meta in soup.find_all("meta"):
            content = meta.get("content", "")
            if content.startswith("http") or content.startswith("//"):
                prop = (meta.get("property") or meta.get("name") or "").lower()
                if "image" in prop:
                    meta["content"] = _picsum_url(img_idx)
                    img_idx += 1

        # Replace remote <video>/<audio> src with placeholder
        for tag in soup.find_all(["video", "audio"]):
            src = tag.get("src", "")
            if src.startswith("http") or src.startswith("//"):
                tag["src"] = _picsum_url(img_idx)
                img_idx += 1
            poster = tag.get("poster", "")
            if poster.startswith("http") or poster.startswith("//"):
                tag["poster"] = _picsum_url(img_idx)
                img_idx += 1

        # Replace ALL images with placeholders (preserving original dimensions)
        # Includes remote URLs AND local ./resources/ paths (since resources dir is deleted)
        for tag in soup.find_all(["img", "source", "input"]):
            if tag.name == "input" and (tag.get("type") or "").lower() != "image":
                continue
            w, h = _parse_img_dimensions(tag)
            # Also try to parse dimensions from URL (e.g. ?width=720&height=480 or filename-655x533.jpg)
            first_url = tag.get("src") or tag.get("data-src") or ""
            if w == 0 or h == 0:
                wm = re.search(r'[?&](?:width|w)=(\d+)', first_url)
                hm = re.search(r'[?&](?:height|h)=(\d+)', first_url)
                if wm: w = int(wm.group(1))
                if hm: h = int(hm.group(1))
            # Try filename pattern like image-655x533.jpg
            if w == 0 or h == 0:
                dim_m = re.search(r'(\d{2,4})x(\d{2,4})\.\w+$', first_url)
                if dim_m:
                    w, h = int(dim_m.group(1)), int(dim_m.group(2))

            for attr in ("src", "data-src", "data-lazy-src", "data-cke-saved-src",
                         "nitro-lazy-src", "data-original", "data-lazy"):
                val = tag.get(attr)
                if not val or val.startswith("data:"):
                    continue
                # Replace remote URLs AND local resource paths
                if val.startswith("http") or val.startswith("//") or val.startswith("./resources/"):
                    tag[attr] = _picsum_url(img_idx, w, h)
                    img_idx += 1

            # Also handle srcset
            srcset = tag.get("srcset", "")
            if srcset and ("http" in srcset or "//" in srcset):
                tag["srcset"] = _picsum_url(img_idx, w, h)
                img_idx += 1

        # Replace remote CSS url() — images → picsum, fonts → placeholder font URL
        _font_exts = {".woff", ".woff2", ".ttf", ".otf", ".eot"}
        for style_tag in soup.find_all("style"):
            if style_tag.string:
                def _replace_css_url(m):
                    nonlocal img_idx, font_idx
                    url = m.group(1).strip("'\"")
                    if not (url.startswith("http") or url.startswith("//")):
                        return m.group(0)  # keep local paths
                    # Font files → placeholder font CSS
                    if any(url.lower().endswith(ext) for ext in _font_exts):
                        placeholder = _PLACEHOLDER_FONTS[font_idx % len(_PLACEHOLDER_FONTS)]
                        font_idx += 1
                        return f"url({placeholder})"
                    # Everything else (images, SVG, etc.) → picsum
                    placeholder = _picsum_url(img_idx)
                    img_idx += 1
                    return f"url({placeholder})"
                style_tag.string = re.sub(r'url\(([^)]+)\)', _replace_css_url, style_tag.string)

        # Replace inline style url() — handle url("...") with nested quotes
        for tag in soup.find_all(style=True):
            style = tag["style"]
            if "url(" in style and ("http" in style or "//" in style):
                _box = [img_idx]
                def _do_replace(m):
                    url = m.group(1)
                    if url.startswith("http") or url.startswith("//"):
                        placeholder = _picsum_url(_box[0])
                        _box[0] += 1
                        return f"url({placeholder})"
                    return m.group(0)
                tag["style"] = re.sub(r'url\(["\']?(https?://[^\s)\"\']+)["\']?\)', _do_replace, style)
                img_idx = _box[0]

        # Fallback: replace any remaining remote src/poster on ANY tag
        _already_handled = {"img", "source", "input", "script", "link", "video", "audio"}
        for tag in soup.find_all(True):
            if tag.name in _already_handled:
                continue
            for attr in ("src", "poster"):
                val = tag.get(attr, "")
                if val and (val.startswith("http") or val.startswith("//")):
                    tag[attr] = _picsum_url(img_idx)
                    img_idx += 1

        html_file.write_text(str(soup), encoding="utf-8")

    # Sanitize remote url() inside ALL CSS files in resources/
    _font_exts_set = {".woff", ".woff2", ".ttf", ".otf", ".eot"}
    for css_file in list(resources_dir.glob("*.css")):
        try:
            css_text = css_file.read_text(encoding="utf-8", errors="replace")
            if not re.search(r'url\([^)]*https?://', css_text):
                continue
            _css_box = [img_idx]
            def _sanitize_css_url(m, _b=_css_box):
                inner = m.group(1).strip("'\"")
                if not (inner.startswith("http") or inner.startswith("//")):
                    return m.group(0)
                if any(inner.lower().endswith(ext) for ext in _font_exts_set):
                    return "url()"
                placeholder = _picsum_url(_b[0])
                _b[0] += 1
                return f"url({placeholder})"
            css_text = re.sub(r'url\(["\']?([^)]+?)["\']?\)', _sanitize_css_url, css_text)
            css_file.write_text(css_text, encoding="utf-8")
            img_idx = _css_box[0]
        except Exception:
            pass

    # Neutralize external links
    neutralize_external_links(project_dir)

    return {
        "status": "cleaned",
        "project": project_dir.name,
        "remaining_remote_refs": 0,
        "images_replaced": img_idx,
        "css_replaced": css_idx,
        "js_replaced": js_idx,
        "fonts_replaced": font_idx,
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

        # Localize images, inline CSS, clean up — all handled inside localize_resources
        cleaned = localize_resources(html, base_url, resources_dir, session)
        html_file.write_text(cleaned, encoding="utf-8")

        # Count truly remote references (any *src= attribute, exclude picsum fallbacks)
        all_remote = re.findall(r'[a-z-]*src="(https?://[^"]+)"', cleaned)
        remaining = sum(1 for u in all_remote if "picsum.photos" not in u)
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
    """Crawl sites from URL list (supports concurrency via multiple browser pages)."""
    url_file = Path(args.url_file)
    urls = [line.strip() for line in url_file.read_text().splitlines() if line.strip()]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    concurrency = args.concurrency
    browser_proxy = resolve_browser_proxy(args.browser_proxy)
    requests_proxy = resolve_requests_proxy(args.requests_proxy)

    print(f"Crawling {len(urls)} URLs with concurrency={concurrency}")
    print(f"Using proxies: browser={browser_proxy or 'direct'}, requests={requests_proxy or 'direct'}")

    results = []
    done_count = 0

    # Incremental results file — append after each project
    results_path = output_dir / "crawl_results.jsonl"
    results_lock = threading.Lock()

    def _append_result(result):
        with results_lock:
            results.append(result)
            with open(results_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")

    # Filter out already-done URLs
    todo = []
    for url in urls:
        parsed = urlparse(url)
        proj_name = re.sub(r"[^A-Za-z0-9._-]", "_", parsed.netloc)[:60]
        proj_dir = output_dir / proj_name
        if proj_dir.exists() and (proj_dir / "index.html").exists():
            done_count += 1
            continue
        todo.append((url, proj_name, proj_dir))

    if done_count:
        print(f"Skipped {done_count} already-done projects")

    # Clear results file for this run
    results_path.write_text("", encoding="utf-8")

    def _crawl_one_with_browser(item, browser: Browser, session: requests.Session):
        url, proj_name, proj_dir = item
        t0 = time.time()
        try:
            result = crawl_site(url, proj_dir, browser, session,
                                max_pages=args.max_pages, wait_ms=args.wait,
                                subpage_wait_ms=args.subpage_wait,
                                timeout_ms=args.timeout)
        except Exception as e:
            result = {"status": "error", "url": url, "error": str(e)}
        result["elapsed"] = round(time.time() - t0, 1)
        return proj_name, result

    if concurrency <= 1:
        session = build_requests_session(requests_proxy)
        with sync_playwright() as p:
            browser = p.chromium.launch(
                proxy={"server": browser_proxy} if browser_proxy else None,
            )
            try:
                for i, item in enumerate(todo):
                    proj_name, result = _crawl_one_with_browser(item, browser, session)
                    _append_result(result)
                    status = result["status"]
                    pages = result.get("pages", 0)
                    print(f"[{i+1}/{len(todo)}] {proj_name}: {status} ({pages} pages, {result['elapsed']:.1f}s)")
            finally:
                browser.close()
    else:
        payloads = [
            (
                url,
                proj_name,
                str(proj_dir),
                browser_proxy,
                requests_proxy,
                args.max_pages,
                args.wait,
                args.subpage_wait,
                args.timeout,
                args.retry_timeout,
            )
            for url, proj_name, proj_dir in todo
        ]
        if args.site_timeout and args.site_timeout > 0:
            ctx = mp.get_context()
            pending = list(payloads)
            active: dict[mp.Process, tuple[tuple, float, mp.Queue]] = {}
            completed = 0

            def _start_next() -> None:
                payload = pending.pop(0)
                result_queue = ctx.Queue(maxsize=1)
                proc = ctx.Process(target=crawl_one_process_entry, args=(payload, result_queue))
                proc.start()
                active[proc] = (payload, time.time(), result_queue)

            while pending or active:
                while pending and len(active) < concurrency:
                    _start_next()

                for proc, (payload, started, result_queue) in list(active.items()):
                    url, proj_name, proj_dir = payload[0], payload[1], Path(payload[2])
                    try:
                        got_proj_name, result = result_queue.get_nowait()
                    except queue.Empty:
                        got_proj_name, result = None, None

                    if result is not None:
                        proc.join(timeout=2)
                        active.pop(proc, None)
                        completed += 1
                        _append_result(result)
                        status = result["status"]
                        pages = result.get("pages", 0)
                        print(
                            f"[{completed}/{len(todo)}] {got_proj_name}: {status} "
                            f"({pages} pages, {result.get('elapsed', 0):.1f}s)",
                            flush=True,
                        )
                        continue

                    elapsed = time.time() - started
                    if elapsed > args.site_timeout:
                        proc.terminate()
                        proc.join(timeout=5)
                        if proc.is_alive():
                            proc.kill()
                            proc.join(timeout=5)
                        if proj_dir.exists():
                            shutil.rmtree(proj_dir, ignore_errors=True)
                        active.pop(proc, None)
                        completed += 1
                        result = {
                            "status": "site_timeout",
                            "url": url,
                            "project": proj_name,
                            "elapsed": round(elapsed, 1),
                            "site_timeout": args.site_timeout,
                            "has_single_page": False,
                            "has_multi_page": False,
                            "pages_added": 0,
                        }
                        _append_result(result)
                        print(
                            f"[{completed}/{len(todo)}] {proj_name}: site_timeout "
                            f"(0 pages, {elapsed:.1f}s)",
                            flush=True,
                        )
                    elif not proc.is_alive():
                        proc.join(timeout=2)
                        active.pop(proc, None)
                        completed += 1
                        result = {
                            "status": "worker_exited",
                            "url": url,
                            "project": proj_name,
                            "elapsed": round(elapsed, 1),
                            "has_single_page": False,
                            "has_multi_page": False,
                            "pages_added": 0,
                        }
                        _append_result(result)
                        print(
                            f"[{completed}/{len(todo)}] {proj_name}: worker_exited "
                            f"(0 pages, {elapsed:.1f}s)",
                            flush=True,
                        )

                time.sleep(0.2)
        else:
            with ProcessPoolExecutor(max_workers=concurrency) as executor:
                futures = {executor.submit(crawl_one_process, payload): payload for payload in payloads}
                for i, future in enumerate(as_completed(futures), 1):
                    try:
                        proj_name, result = future.result(timeout=300)
                    except TimeoutError:
                        proj_name = str(futures[future][1])
                        result = {"status": "future_timeout", "project": proj_name}
                    except Exception as e:
                        proj_name = str(futures[future][1])
                        result = {"status": "error", "error": str(e)}
                    _append_result(result)
                    status = result["status"]
                    pages = result.get("pages", 0)
                    print(f"[{i}/{len(todo)}] {proj_name}: {status} ({pages} pages, {result.get('elapsed', 0):.1f}s)")

    # Summary
    statuses = Counter(r["status"] for r in results)
    single_page_samples = sum(1 for r in results if r.get("has_single_page"))
    multi_page_samples = sum(1 for r in results if r.get("has_multi_page"))
    print(f"\nDone! {len(results)} processed:")
    for s, c in statuses.most_common():
        print(f"  {s}: {c}")
    print(f"  usable_single_page_samples: {single_page_samples}")
    print(f"  multi_page_samples: {multi_page_samples}")


def cmd_expand(args):
    """Expand existing projects to multi-page (supports concurrency)."""
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    concurrency = args.concurrency
    browser_proxy = resolve_browser_proxy(args.browser_proxy)
    requests_proxy = resolve_requests_proxy(args.requests_proxy)

    projects = sorted(d for d in input_dir.iterdir() if d.is_dir())
    if args.limit:
        projects = projects[:args.limit]

    print(f"Expanding {len(projects)} projects with concurrency={concurrency}")
    print(f"Using proxies: browser={browser_proxy or 'direct'}, requests={requests_proxy or 'direct'}")

    results = []

    # Incremental results file
    results_path = output_dir / "expand_results.jsonl"
    results_lock = threading.Lock()

    def _append_result(result):
        with results_lock:
            results.append(result)
            with open(results_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")

    # Filter already-expanded
    todo = []
    skipped = 0
    for proj in projects:
        out_proj = output_dir / proj.name
        if out_proj.exists() and len(list(out_proj.glob("*.html"))) > 1:
            skipped += 1
            continue
        todo.append(proj)

    if skipped:
        print(f"Skipped {skipped} already-expanded projects")

    # Clear results file for this run
    results_path.write_text("", encoding="utf-8")

    def _expand_one_with_browser(proj, browser: Browser, session: requests.Session):
        t0 = time.time()
        try:
            result = expand_project(proj, output_dir, browser, session,
                                    max_pages=args.max_pages, wait_ms=args.wait)
        except Exception as e:
            result = {"status": "error", "project": proj.name, "error": str(e)}
        result["elapsed"] = round(time.time() - t0, 1)
        return proj.name, result

    if concurrency <= 1:
        session = build_requests_session(requests_proxy)
        with sync_playwright() as p:
            browser = p.chromium.launch(
                proxy={"server": browser_proxy} if browser_proxy else None,
            )
            try:
                for i, proj in enumerate(todo):
                    name, result = _expand_one_with_browser(proj, browser, session)
                    _append_result(result)
                    status = result["status"]
                    pages = result.get("pages_added", 0)
                    print(f"[{i+1}/{len(todo)}] {name}: {status} (+{pages} pages, {result['elapsed']:.1f}s)")
            finally:
                browser.close()
    else:
        payloads = [
            (
                str(proj),
                str(output_dir),
                browser_proxy,
                requests_proxy,
                args.max_pages,
                args.wait,
            )
            for proj in todo
        ]
        site_timeout = args.site_timeout if args.site_timeout and args.site_timeout > 0 else 0
        if site_timeout:
            ctx = mp.get_context()
            pending = list(payloads)
            active: dict[mp.Process, tuple[tuple, float, mp.Queue]] = {}
            completed = 0

            def _start_next_expand() -> None:
                payload = pending.pop(0)
                rq = ctx.Queue(maxsize=1)
                proc = ctx.Process(target=expand_one_process_entry, args=(payload, rq))
                proc.start()
                active[proc] = (payload, time.time(), rq)

            while pending or active:
                while pending and len(active) < concurrency:
                    _start_next_expand()

                for proc, (payload, started, rq) in list(active.items()):
                    proj_name = Path(payload[0]).name
                    try:
                        name, result = rq.get_nowait()
                    except queue.Empty:
                        name, result = None, None

                    if result is not None:
                        proc.join(timeout=2)
                        active.pop(proc, None)
                        completed += 1
                        _append_result(result)
                        pages = result.get("pages_added", 0)
                        print(f"[{completed}/{len(todo)}] {name}: {result['status']} "
                              f"(+{pages} pages, {result.get('elapsed', 0):.1f}s)", flush=True)
                        continue

                    elapsed = time.time() - started
                    if elapsed > site_timeout:
                        proc.terminate()
                        proc.join(timeout=5)
                        if proc.is_alive():
                            proc.kill()
                            proc.join(timeout=5)
                        out_proj = output_dir / proj_name
                        if out_proj.exists():
                            shutil.rmtree(out_proj, ignore_errors=True)
                        active.pop(proc, None)
                        completed += 1
                        result = {"status": "site_timeout", "project": proj_name,
                                  "elapsed": round(elapsed, 1), "site_timeout": site_timeout,
                                  "pages_added": 0}
                        _append_result(result)
                        print(f"[{completed}/{len(todo)}] {proj_name}: site_timeout "
                              f"({elapsed:.1f}s)", flush=True)
                    elif not proc.is_alive():
                        proc.join(timeout=2)
                        active.pop(proc, None)
                        completed += 1
                        result = {"status": "worker_exited", "project": proj_name,
                                  "elapsed": round(elapsed, 1), "pages_added": 0}
                        _append_result(result)
                        print(f"[{completed}/{len(todo)}] {proj_name}: worker_exited "
                              f"({elapsed:.1f}s)", flush=True)

                time.sleep(0.2)
        else:
            with ProcessPoolExecutor(max_workers=concurrency) as executor:
                futures = {executor.submit(expand_one_process, payload): payload for payload in payloads}
                for i, future in enumerate(as_completed(futures), 1):
                    try:
                        name, result = future.result(timeout=300)
                    except TimeoutError:
                        name = Path(futures[future][0]).name
                        result = {"status": "future_timeout", "project": name, "pages_added": 0}
                    except Exception as e:
                        name = Path(futures[future][0]).name
                        result = {"status": "error", "error": str(e)}
                    _append_result(result)
                    status = result["status"]
                    pages = result.get("pages_added", 0)
                    print(f"[{i}/{len(todo)}] {name}: {status} (+{pages} pages, {result.get('elapsed', 0):.1f}s)")

    statuses = Counter(r["status"] for r in results)
    total_pages = sum(r.get("pages_added", 0) for r in results)
    print(f"\nDone! {statuses.get('expanded', 0)} expanded, {total_pages} pages added")


def cmd_clean(args):
    """Clean existing projects (download remote images, supports concurrency)."""
    input_dir = Path(args.input_dir)
    projects = sorted(d for d in input_dir.iterdir() if d.is_dir())
    if args.limit:
        projects = projects[:args.limit]
    concurrency = args.concurrency
    requests_proxy = resolve_requests_proxy(args.requests_proxy)

    print(f"Cleaning {len(projects)} projects with concurrency={concurrency}")
    print(f"Using requests proxy: {requests_proxy or 'direct'}")

    proxy = requests_proxy
    results = []

    # Each thread gets its own session to avoid race conditions.
    _thread_local = threading.local()

    def _get_session():
        if not hasattr(_thread_local, "session"):
            _thread_local.session = build_requests_session(proxy)
        return _thread_local.session

    def _clean_one(proj):
        try:
            return clean_project(proj, _get_session())
        except Exception as e:
            return {"status": "error", "project": proj.name, "error": str(e)}

    clean_timeout = args.site_timeout if args.site_timeout and args.site_timeout > 0 else 300

    if concurrency <= 1:
        for i, proj in enumerate(projects):
            result = _clean_one(proj)
            results.append(result)
            remaining = result.get("remaining_remote_refs", 0)
            print(f"[{i+1}/{len(projects)}] {proj.name}: {result['status']} (remaining={remaining})")
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {executor.submit(_clean_one, proj): proj for proj in projects}
            for i, future in enumerate(as_completed(futures), 1):
                proj = futures[future]
                try:
                    result = future.result(timeout=clean_timeout)
                except TimeoutError:
                    result = {"status": "clean_timeout", "project": proj.name,
                              "remaining_remote_refs": -1}
                except Exception as e:
                    result = {"status": "error", "project": proj.name, "error": str(e)}
                results.append(result)
                remaining = result.get("remaining_remote_refs", 0)
                print(f"[{i}/{len(projects)}] {proj.name}: {result['status']} (remaining={remaining})")

    statuses = Counter(r["status"] for r in results)
    print(f"\nDone: {statuses}")


VALIDATE_IGNORE_PATTERNS = (
    "CORS policy", "net::ERR_", "Failed to load resource",
    "favicon.ico", "blocked by CORS",
    "the server responded with a status of 404",
    "Unsafe attempt to load URL",
    "PAGE_LOAD_ERROR",
)


def _validate_one_project(proj_path: str, purge: bool) -> dict:
    """Validate a single project. Runs in a subprocess."""
    proj = Path(proj_path)
    index_html = proj / "index.html"
    if not index_html.exists():
        return {"project": proj.name, "status": "no_index"}

    html = index_html.read_text(encoding="utf-8", errors="replace")
    if not validate_page(html):
        if purge:
            shutil.rmtree(proj, ignore_errors=True)
        return {"project": proj.name, "status": "garbage", "purged": purge}

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        console_errors = []

        def on_console(msg):
            if msg.type == "error":
                text = msg.text
                if not any(pat in text for pat in VALIDATE_IGNORE_PATTERNS):
                    console_errors.append(text)

        page.on("console", on_console)

        try:
            page.goto(f"file://{index_html.resolve()}", wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(2000)
        except Exception:
            pass

        page.close()
        browser.close()

    status = "ok" if not console_errors else f"errors({len(console_errors)})"
    return {
        "project": proj.name,
        "status": status,
        "console_errors": console_errors[:10],
    }


def cmd_validate(args):
    """Validate projects: content quality check + Playwright Console error check.

    Checks performed:
    1. Content quality — enough text, not a dead/parked/CAPTCHA page (validate_page)
    2. Console errors — open in Playwright, check for JS errors

    With --purge: delete projects that fail content quality check.
    """
    input_dir = Path(args.input_dir)
    projects = sorted(d for d in input_dir.iterdir() if d.is_dir())
    if args.limit:
        projects = projects[:args.limit]
    purge = getattr(args, "purge", False)
    concurrency = args.concurrency

    print(f"Validating {len(projects)} projects (content + console, purge={purge}, concurrency={concurrency})")

    results = []
    results_path = input_dir / "validate_results.jsonl"
    results_path.write_text("", encoding="utf-8")
    purged = 0

    validate_timeout = args.site_timeout if args.site_timeout and args.site_timeout > 0 else 120

    if concurrency <= 1:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            for i, proj in enumerate(projects):
                index_html = proj / "index.html"
                if not index_html.exists():
                    result = {"project": proj.name, "status": "no_index"}
                    results.append(result)
                    with open(results_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps(result, ensure_ascii=False) + "\n")
                    continue

                html = index_html.read_text(encoding="utf-8", errors="replace")
                if not validate_page(html):
                    result = {"project": proj.name, "status": "garbage"}
                    results.append(result)
                    with open(results_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps(result, ensure_ascii=False) + "\n")
                    if purge:
                        shutil.rmtree(proj, ignore_errors=True)
                        purged += 1
                    print(f"[{i+1}/{len(projects)}] {proj.name}: GARBAGE"
                          f"{' (purged)' if purge else ''}")
                    continue

                page = browser.new_page()
                console_errors = []

                def on_console(msg):
                    if msg.type == "error":
                        text = msg.text
                        if not any(pat in text for pat in VALIDATE_IGNORE_PATTERNS):
                            console_errors.append(text)

                page.on("console", on_console)
                try:
                    page.goto(f"file://{index_html.resolve()}", wait_until="load", timeout=60000)
                    page.wait_for_timeout(2000)
                except Exception:
                    try:
                        page.goto(f"file://{index_html.resolve()}", wait_until="domcontentloaded", timeout=15000)
                        page.wait_for_timeout(3000)
                    except Exception:
                        pass

                page.close()
                status = "ok" if not console_errors else f"errors({len(console_errors)})"
                result = {"project": proj.name, "status": status, "console_errors": console_errors[:10]}
                results.append(result)
                with open(results_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(result, ensure_ascii=False) + "\n")
                error_summary = f" — {console_errors[0][:80]}" if console_errors else ""
                print(f"[{i+1}/{len(projects)}] {proj.name}: {status}{error_summary}")

            browser.close()
    else:
        payloads = [(str(proj), purge) for proj in projects]
        with ProcessPoolExecutor(max_workers=concurrency) as executor:
            future_map = {executor.submit(_validate_one_project, *p): p for p in payloads}
            for i, future in enumerate(as_completed(future_map), 1):
                proj_name = Path(future_map[future][0]).name
                try:
                    result = future.result(timeout=validate_timeout)
                except TimeoutError:
                    result = {"project": proj_name, "status": "validate_timeout"}
                except Exception as e:
                    result = {"project": proj_name, "status": "error", "error": str(e)}
                results.append(result)
                with open(results_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(result, ensure_ascii=False) + "\n")
                if result.get("purged"):
                    purged += 1
                status = result["status"]
                extra = ""
                if status.startswith("errors"):
                    errs = result.get("console_errors", [])
                    extra = f" — {errs[0][:80]}" if errs else ""
                print(f"[{i}/{len(projects)}] {proj_name}: {status}{extra}")

    ok_count = sum(1 for r in results if r["status"] == "ok")
    garbage_count = sum(1 for r in results if r["status"] == "garbage")
    print(f"\nDone: {ok_count}/{len(results)} passed, {garbage_count} garbage"
          f"{f', {purged} purged' if purge else ''}")


def main():
    parser = argparse.ArgumentParser(description="Playwright web crawler for training data")
    parser.add_argument("--browser-proxy", default="",
                        help="Proxy for Playwright/Chromium. Supports both 'socks5://' and "
                             "'http://'. If omitted, falls back to HTTPS_PROXY/HTTP_PROXY/ALL_PROXY.")
    parser.add_argument("--requests-proxy", default="",
                        help="Proxy for requests library. Supports both 'socks5h://' and "
                             "'http://'. If omitted, falls back to HTTPS_PROXY/HTTP_PROXY/ALL_PROXY.")
    parser.add_argument("--concurrency", type=int, default=1,
                        help="Number of concurrent browser pages (NOT browsers). "
                             "Mac M4 16GB: use 3-5. Server 64GB: use 15-20.")
    parser.add_argument("--max-pages", type=int, default=7,
                        help="Max sub-pages to crawl per site")
    parser.add_argument("--wait", type=int, default=3000,
                        help="Wait time (ms) after page load for rendering")
    parser.add_argument("--subpage-wait", type=int, default=2000,
                        help="Wait time (ms) after sub-page load for rendering")
    parser.add_argument("--timeout", type=int, default=30000,
                        help="Initial navigation timeout (ms)")
    parser.add_argument("--retry-timeout", type=int, default=45000,
                        help="Fallback navigation timeout (ms)")
    parser.add_argument("--site-timeout", type=int, default=0,
                        help="Hard wall-clock timeout per URL in seconds. "
                             "When set, stuck crawl workers are terminated and marked site_timeout.")

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

    # validate
    p_validate = subparsers.add_parser("validate", help="Content quality + Console error check")
    p_validate.add_argument("--input-dir", required=True, help="Directory with project subdirs")
    p_validate.add_argument("--limit", type=int, default=None, help="Limit projects to process")
    p_validate.add_argument("--purge", action="store_true",
                            help="Delete projects that fail content quality check")

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
    elif args.command == "validate":
        cmd_validate(args)


if __name__ == "__main__":
    main()
