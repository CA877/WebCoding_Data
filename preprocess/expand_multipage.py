#!/usr/bin/env python3
"""Expand WebRenderBench single-page projects into multi-page by crawling sub-pages."""

import argparse
import hashlib
import os
import re
import shutil
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


def extract_internal_links(html: str, max_links: int = 5) -> list[str]:
    """Extract unique same-domain links from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    all_hrefs = [a["href"] for a in soup.find_all("a", href=True)]

    # Find the main domain from href patterns
    domains: dict[str, int] = {}
    for h in all_hrefs:
        parsed = urlparse(h)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            domains[parsed.netloc] = domains.get(parsed.netloc, 0) + 1

    if not domains:
        return []

    main_domain = max(domains, key=domains.get)

    # Collect unique internal links (deeper than root)
    seen = set()
    internal = []
    for h in all_hrefs:
        parsed = urlparse(h)
        if parsed.netloc != main_domain:
            continue
        # Skip anchors, root, and already seen
        path = parsed.path.rstrip("/")
        if not path or path == "/" or path in seen:
            continue
        # Skip non-page extensions
        if any(path.endswith(ext) for ext in (".jpg", ".png", ".gif", ".pdf", ".zip", ".svg", ".ico")):
            continue
        seen.add(path)
        internal.append(h)
        if len(internal) >= max_links:
            break

    return internal


def safe_page_name(url: str, index: int, used: set[str]) -> str:
    """Generate a safe filename for a sub-page."""
    parsed = urlparse(url)
    stem = Path(parsed.path).stem or f"page_{index}"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-") or f"page_{index}"
    name = f"{stem}.html"
    if name == "index.html":
        name = f"page_{index}.html"
    base = name
    suffix = 2
    while name in used:
        name = f"{Path(base).stem}_{suffix}.html"
        suffix += 1
    used.add(name)
    return name


def download_resource(session: requests.Session, url: str, resources_dir: Path, timeout: int = 10, kind: str = "") -> str | None:
    """Download a resource and return local relative path, or None on failure."""
    try:
        resp = session.get(url, timeout=timeout, allow_redirects=True)
        if resp.status_code != 200 or len(resp.content) < 100:
            return None
    except Exception:
        return None

    # Determine filename from URL
    parsed = urlparse(url)
    basename = Path(parsed.path).name or "resource"
    # Add hash prefix to avoid collisions
    h = hashlib.md5(url.encode()).hexdigest()[:8]
    name = f"{h}_{basename}"
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80]

    # Ensure proper extension based on content-type or kind
    ct = resp.headers.get("content-type", "").lower()
    has_ext = "." in name.split("_", 1)[-1]  # check after hash prefix
    if not has_ext:
        ext = _guess_extension(ct, kind)
        if ext:
            name += ext

    target = resources_dir / name
    target.write_bytes(resp.content)
    return f"./resources/{name}"


def _guess_extension(content_type: str, kind: str) -> str:
    """Guess file extension from content-type or resource kind."""
    if "css" in content_type or kind == "css":
        return ".css"
    if "javascript" in content_type:
        return ".js"
    if "jpeg" in content_type or "jpg" in content_type:
        return ".jpg"
    if "png" in content_type:
        return ".png"
    if "svg" in content_type:
        return ".svg"
    if "gif" in content_type:
        return ".gif"
    if "webp" in content_type:
        return ".webp"
    if "woff2" in content_type:
        return ".woff2"
    if "woff" in content_type:
        return ".woff"
    if "font" in content_type or "octet-stream" in content_type:
        return ".woff2"
    if "html" in content_type:
        return ".html"
    return ""


def _resolve_css_urls(css_file: Path, css_origin_url: str, session: requests.Session, resources_dir: Path):
    """Resolve url() references inside a downloaded CSS file to local resources."""
    if not css_file.exists():
        return
    content = css_file.read_text(encoding="utf-8", errors="replace")

    def replace_url(match):
        raw = match.group(1).strip("\"'")
        if raw.startswith("data:") or raw.startswith("./resources/"):
            return match.group(0)
        abs_url = urljoin(css_origin_url, raw)
        if not abs_url.startswith("http"):
            return match.group(0)
        local = download_resource(session, abs_url, resources_dir)
        if local:
            # CSS file is in resources/, so relative path is just the filename
            return f"url({Path(local).name})"
        return match.group(0)

    new_content = re.sub(r"url\(([^)]+)\)", replace_url, content)
    if new_content != content:
        css_file.write_text(new_content, encoding="utf-8")


def localize_page_html(
    html: str,
    page_url: str,
    resources_dir: Path,
    session: requests.Session,
    existing_resources: set[str],
) -> tuple[str, Counter]:
    """Clean and localize a crawled sub-page HTML."""
    soup = BeautifulSoup(html, "html.parser")
    stats = Counter()

    # Remove scripts
    for tag in soup.find_all("script"):
        tag.decompose()
        stats["removed_script"] += 1

    # Remove tracking/noise
    for tag in list(soup.find_all("link")):
        if not tag.attrs:
            continue
        rel = " ".join(tag.get("rel") or []).lower()
        if any(t in rel for t in ("dns-prefetch", "preconnect", "canonical", "alternate", "manifest")):
            tag.decompose()
            stats["removed_noise_link"] += 1

    # Localize images
    for tag in list(soup.find_all(["img", "source"])):
        for attr in ("src", "data-src", "data-lazy-src"):
            val = tag.get(attr)
            if not val:
                continue
            if val.startswith("data:") or val.startswith("./resources/"):
                continue
            abs_url = urljoin(page_url, val)
            if not abs_url.startswith("http"):
                continue
            local = download_resource(session, abs_url, resources_dir)
            if local:
                tag[attr] = local
                stats["downloaded_image"] += 1
            else:
                # Remove broken images
                tag.decompose()
                stats["removed_broken_image"] += 1
                break
        # Remove srcset (complex to handle)
        try:
            if tag.get("srcset"):
                del tag["srcset"]
        except (AttributeError, TypeError):
            pass

    # Localize CSS background images in style attributes
    def replace_css_url(match):
        url = match.group(1).strip("\"'")
        if url.startswith("data:") or url.startswith("./resources/"):
            return match.group(0)
        abs_url = urljoin(page_url, url)
        if not abs_url.startswith("http"):
            return match.group(0)
        local = download_resource(session, abs_url, resources_dir)
        if local:
            stats["downloaded_css_resource"] += 1
            return f"url({local})"
        return match.group(0)

    for tag in soup.find_all(style=True):
        tag["style"] = re.sub(r"url\(([^)]+)\)", replace_css_url, tag["style"])

    for tag in soup.find_all("style"):
        if tag.string:
            tag.string = re.sub(r"url\(([^)]+)\)", replace_css_url, tag.get_text())

    # Localize stylesheet links
    for tag in list(soup.find_all("link")):
        if not tag.attrs:
            continue
        rel = " ".join(tag.get("rel") or []).lower()
        href = tag.get("href")
        if "stylesheet" in rel and href:
            if href.startswith("./resources/"):
                continue
            abs_url = urljoin(page_url, href)
            local = download_resource(session, abs_url, resources_dir, kind="css")
            if local:
                # Resolve url() references inside the CSS file
                _resolve_css_urls(resources_dir / Path(local).name, abs_url, session, resources_dir)
                tag["href"] = local
                stats["downloaded_css"] += 1
            else:
                tag.decompose()
                stats["removed_broken_css"] += 1

    # Keep external hrefs intact for now — relink_pages will convert matching ones
    # to local filenames, then neutralize_external_hrefs cleans up the rest.

    return str(soup), stats


def neutralize_external_hrefs(project_dir: Path):
    """Final pass: convert remaining http/external hrefs to '#'."""
    for html_file in project_dir.glob("*.html"):
        html = html_file.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        modified = False
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("http") or href.startswith("//"):
                a["href"] = "#"
                modified = True
        if modified:
            html_file.write_text(str(soup), encoding="utf-8")


def relink_pages(project_dir: Path, url_to_file: dict[str, str]):
    """Post-process: rewrite hrefs that match project pages to local filenames.

    Handles both absolute URLs (http://domain/path) and relative paths (/path, path.php?x=y).
    """
    if not url_to_file:
        return

    # Build multiple lookup indexes
    path_to_file: dict[str, str] = {}  # /path -> filename
    full_url_to_file: dict[str, str] = {}  # full url -> filename
    domain = None

    for url, filename in url_to_file.items():
        parsed = urlparse(url)
        if not domain:
            domain = parsed.netloc
        # Map by path (without query)
        path_to_file[parsed.path.rstrip("/")] = filename
        path_to_file[parsed.path] = filename
        # Map by path+query (for things like page.php?secao=company)
        path_with_query = parsed.path
        if parsed.query:
            path_with_query += "?" + parsed.query
        path_to_file[path_with_query] = filename
        # Full URL
        full_url_to_file[url] = filename

    if not domain:
        return

    # Also map index variants
    project_pages = set(url_to_file.values())

    for html_file in project_dir.glob("*.html"):
        html = html_file.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        modified = False

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href == "#" or href.startswith("mailto:") or href.startswith("tel:"):
                continue
            # Already a local project page link
            if href in project_pages:
                continue

            matched_file = None

            if href.startswith("http") or href.startswith("//"):
                # Absolute URL - match by domain+path
                parsed = urlparse(href)
                if parsed.netloc != domain:
                    continue
                path_q = parsed.path
                if parsed.query:
                    path_q += "?" + parsed.query
                matched_file = path_to_file.get(path_q) or path_to_file.get(parsed.path.rstrip("/"))
            else:
                # Relative path - match directly
                # Strip leading ./ if present
                clean_href = href.lstrip("./")
                # Try exact match
                matched_file = path_to_file.get(href) or path_to_file.get("/" + clean_href)
                # Try matching just the relative path as-is
                if not matched_file:
                    for known_url, fname in url_to_file.items():
                        kp = urlparse(known_url)
                        # Match path+query
                        kpath = kp.path
                        if kp.query:
                            kpath += "?" + kp.query
                        if href == kpath or href == kp.path or ("/" + clean_href) == kp.path:
                            matched_file = fname
                            break
                        # Match basename
                        if Path(kp.path).name and href.endswith(Path(kp.path).name):
                            matched_file = fname
                            break

            if matched_file:
                a["href"] = matched_file
                modified = True

        if modified:
            html_file.write_text(str(soup), encoding="utf-8")


def expand_project(
    project_dir: Path,
    session: requests.Session,
    max_pages: int = 4,
    timeout: int = 10,
) -> dict:
    """Try to expand a single-page project into multi-page."""
    index_html = project_dir / "index.html"
    if not index_html.exists():
        return {"status": "no_index", "pages_added": 0}

    html = index_html.read_text(encoding="utf-8", errors="replace")
    links = extract_internal_links(html, max_links=max_pages)

    if not links:
        return {"status": "no_internal_links", "pages_added": 0}

    resources_dir = project_dir / "resources"
    resources_dir.mkdir(exist_ok=True)
    existing_resources = set(os.listdir(resources_dir)) if resources_dir.exists() else set()

    used_names: set[str] = {"index.html"}
    pages_added = 0
    page_info = []

    for i, url in enumerate(links):
        try:
            resp = session.get(url, timeout=timeout, allow_redirects=True)
            if resp.status_code != 200:
                continue
            if len(resp.content) < 500:
                continue
            # Check it's HTML
            ct = resp.headers.get("content-type", "")
            if "html" not in ct and "text" not in ct:
                continue
        except Exception:
            continue

        page_html = resp.text
        page_name = safe_page_name(url, i + 1, used_names)

        # Localize the page
        cleaned, stats = localize_page_html(
            page_html, url, resources_dir, session, existing_resources
        )

        # Validate: must have some visible text
        soup_check = BeautifulSoup(cleaned, "html.parser")
        text_len = len(soup_check.get_text(strip=True))
        if text_len < 50:
            continue

        # Save
        (project_dir / page_name).write_text(cleaned, encoding="utf-8")
        pages_added += 1
        page_info.append({"name": page_name, "url": url, "text_len": text_len, "stats": dict(stats)})

        if pages_added >= max_pages:
            break

    # Post-process: relink pages to each other
    if pages_added > 0:
        # Build URL→filename mapping (including index)
        # Try to figure out the index page's original URL from its links
        url_to_file: dict[str, str] = {}
        for info in page_info:
            url_to_file[info["url"]] = info["name"]
        # Also map the root/index URL
        if links:
            parsed_first = urlparse(links[0])
            root_url = f"{parsed_first.scheme}://{parsed_first.netloc}/"
            url_to_file[root_url] = "index.html"
            # Common index variants
            url_to_file[f"{parsed_first.scheme}://{parsed_first.netloc}"] = "index.html"
            url_to_file[f"{parsed_first.scheme}://{parsed_first.netloc}/index.html"] = "index.html"
            url_to_file[f"{parsed_first.scheme}://{parsed_first.netloc}/index.php"] = "index.html"

        relink_pages(project_dir, url_to_file)

    # Final pass: neutralize any remaining external hrefs
    neutralize_external_hrefs(project_dir)

    return {
        "status": "expanded" if pages_added > 0 else "crawl_failed",
        "pages_added": pages_added,
        "links_found": len(links),
        "pages": page_info,
    }


def main():
    parser = argparse.ArgumentParser(description="Expand WebRenderBench projects to multi-page")
    parser.add_argument("--input-dir", required=True, help="Directory containing project subdirs")
    parser.add_argument("--max-pages", type=int, default=3, help="Max sub-pages to crawl per project")
    parser.add_argument("--timeout", type=int, default=10, help="HTTP timeout in seconds")
    parser.add_argument("--proxy", default="socks5h://127.0.0.1:13659", help="SOCKS5 proxy")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of projects to process")
    args = parser.parse_args()

    session = requests.Session()
    session.proxies = {"http": args.proxy, "https": args.proxy}
    session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

    input_dir = Path(args.input_dir)
    projects = sorted([d for d in input_dir.iterdir() if d.is_dir()])
    if args.limit:
        projects = projects[:args.limit]

    total_expanded = 0
    total_pages_added = 0

    for i, proj in enumerate(projects):
        try:
            result = expand_project(proj, session, max_pages=args.max_pages, timeout=args.timeout)
        except Exception as e:
            print(f"[{i+1}/{len(projects)}] {proj.name}: ERROR {e}")
            continue
        if result["pages_added"] > 0:
            total_expanded += 1
            total_pages_added += result["pages_added"]
            print(f"[{i+1}/{len(projects)}] {proj.name}: +{result['pages_added']} pages")
        else:
            print(f"[{i+1}/{len(projects)}] {proj.name}: {result['status']}")

    print(f"\nDone: {total_expanded}/{len(projects)} expanded, {total_pages_added} pages added total")


if __name__ == "__main__":
    main()
