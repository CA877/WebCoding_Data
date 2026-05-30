#!/usr/bin/env python3
"""Convert WebCode2M preview rows into local clean projects.

This pipeline is intentionally dataset-specific. WebCode2M exposes rendered
screenshots plus purified HTML/layout text, but not a full original website
bundle. We therefore make each row self-contained:

- save `text` as `index.html`
- download reachable remote images/CSS/fonts into `assets/`
- replace root-relative or failed image/icon refs with local deterministic SVGs
- remove tracking/counter pixels and provenance-noise resources
- try to crawl original child pages only when the row exposes absolute links
- write per-project metadata for later filtering
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import mimetypes
from pathlib import Path
import re
import shutil
import sys
import time
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Doctype
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


REPO_ROOT = Path(__file__).resolve().parents[2]
WEBCODE2M_ROOT = REPO_ROOT / "third_party" / "naturalcc" / "examples" / "webcode2m"
WEBCODE2M_DEPS = WEBCODE2M_ROOT / ".deps"
if WEBCODE2M_DEPS.exists() and str(WEBCODE2M_DEPS) not in sys.path:
    sys.path.insert(0, str(WEBCODE2M_DEPS))
if str(WEBCODE2M_ROOT) not in sys.path:
    sys.path.insert(0, str(WEBCODE2M_ROOT))

try:
    from scripts.data_cc_pipeline.format_utils import formatCss, formatHtml, mergeHtmlCss

    OFFICIAL_FORMAT_IMPORT_ERROR = ""
except Exception as exc:  # noqa: BLE001
    formatCss = formatHtml = mergeHtmlCss = None  # type: ignore[assignment]
    OFFICIAL_FORMAT_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"


MEDIA_ATTRS = ("src", "data-src", "data-lazy-src", "data-bg", "poster")
CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)(?P<url>[^)'\"\n]+)\1\s*\)", re.I)
SRCSET_PART_RE = re.compile(r"\s*,\s*")
TRACKING_RE = re.compile(
    r"(googletagmanager|google-analytics|gtag|yandex|mc\.yandex|top-fwz|mail\.ru/counter|"
    r"linkwithin|pixel|beacon|counter|analytics|doubleclick|facebook\.com/tr|collect)",
    re.I,
)
ICON_HINT_RE = re.compile(
    r"(icon|favicon|logo|sprite|social|facebook|twitter|linkedin|instagram|youtube|vk-|ok-|"
    r"cart|search|menu|arrow|button|reply|statusicon)",
    re.I,
)
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico"}
FONT_EXTS = {".woff", ".woff2", ".ttf", ".otf", ".eot"}
CSS_EXTS = {".css"}
OFFICIAL_CLEAN_ATTR = "data-cleaned-by"


VISUAL_ASSET_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">
<defs>
  <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#f4f7fb"/>
    <stop offset="0.55" stop-color="#d9e7f2"/>
    <stop offset="1" stop-color="#c9d8e8"/>
  </linearGradient>
  <linearGradient id="a" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#4f83cc"/>
    <stop offset="1" stop-color="#2fbf9f"/>
  </linearGradient>
</defs>
<rect width="960" height="540" fill="url(#g)"/>
<circle cx="760" cy="120" r="96" fill="#ffffff" opacity=".55"/>
<circle cx="180" cy="420" r="150" fill="#ffffff" opacity=".38"/>
<path d="M120 390 C245 250 330 330 430 220 C548 90 640 190 820 120 L820 430 L120 430 Z" fill="url(#a)" opacity=".82"/>
<path d="M120 430 L840 430" stroke="#ffffff" stroke-width="8" opacity=".7"/>
</svg>
"""

ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96">
<rect width="96" height="96" rx="20" fill="#f3f6f8"/>
<circle cx="48" cy="48" r="24" fill="none" stroke="#52616f" stroke-width="7"/>
<path d="M62 62 L78 78" stroke="#52616f" stroke-width="7" stroke-linecap="round"/>
</svg>
"""

AVATAR_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160" viewBox="0 0 160 160">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#8bc6ec"/><stop offset="1" stop-color="#9599e2"/></linearGradient></defs>
<circle cx="80" cy="80" r="80" fill="url(#g)"/>
<circle cx="80" cy="62" r="26" fill="#fff" opacity=".88"/>
<path d="M34 137 C42 105 56 92 80 92 C104 92 118 105 126 137" fill="#fff" opacity=".88"/>
</svg>
"""


def sha1(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha1(value).hexdigest()


# Deterministic pool of picsum photo IDs for diverse placeholder images.
PICSUM_IDS = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19,
              20, 21, 22, 23, 24, 25, 26, 27, 28, 29,
              30, 31, 32, 33, 34, 35, 36, 37, 38, 39]


def download_placeholder(session: requests.Session, assets_dir: Path, index: int, width: int = 800, height: int = 600) -> str | None:
    """Download a picsum photo as a diverse placeholder image."""
    pid = PICSUM_IDS[index % len(PICSUM_IDS)]
    width = max(100, min(width, 1920))
    height = max(100, min(height, 1080))
    url = f"https://picsum.photos/id/{pid}/{width}/{height}"
    name = f"placeholder_{index:03d}.jpg"
    target = assets_dir / name
    try:
        resp = session.get(url, timeout=15, allow_redirects=True)
        if resp.status_code == 200 and len(resp.content) > 100:
            target.write_bytes(resp.content)
            return f"assets/{name}"
    except Exception:  # noqa: BLE001
        pass
    return None


def extract_img_dimensions(tag) -> tuple[int, int]:
    """Extract width/height from an img tag, with sensible defaults."""
    def parse_dim(val, default: int) -> int:
        if not val:
            return default
        val = str(val).strip().rstrip("px%")
        try:
            return max(100, int(float(val)))
        except (ValueError, TypeError):
            return default
    w = parse_dim(tag.get("width"), 800)
    h = parse_dim(tag.get("height"), 600)
    return w, h


def build_session(proxy: str | None = None) -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}
    retry = Retry(total=2, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504))
    adapter = HTTPAdapter(max_retries=retry, pool_connections=16, pool_maxsize=16)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": "Mozilla/5.0 WebCode2M-cleaner"})
    return session


def safe_ext(url: str, content_type: str | None, default: str = ".bin") -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix and len(suffix) <= 8:
        return suffix
    if content_type:
        ext = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if ext:
            return ext
    return default


def is_remote(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://") or url.startswith("//")


def normalize_remote(url: str) -> str:
    return "https:" + url if url.startswith("//") else url


def is_data_or_safe(url: str) -> bool:
    return url.startswith(("data:", "#", "mailto:", "tel:", "javascript:", "blob:", "cid:"))


def classify_url(url: str) -> str:
    lower = url.lower()
    suffix = Path(urlparse(url).path).suffix.lower()
    if TRACKING_RE.search(lower):
        return "noise"
    if "avatar" in lower or "gravatar" in lower:
        return "avatar"
    if suffix in CSS_EXTS:
        return "css"
    if suffix in FONT_EXTS:
        return "font"
    if ICON_HINT_RE.search(lower) or suffix in {".ico", ".svg"}:
        return "icon"
    if suffix in IMAGE_EXTS:
        return "image"
    return "asset"


def write_shared_assets(project_dir: Path) -> dict[str, str]:
    assets = project_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    files = {
        "visual": "assets/generated-visual.svg",
        "icon": "assets/generated-icon.svg",
        "avatar": "assets/generated-avatar.svg",
    }
    (project_dir / files["visual"]).write_text(VISUAL_ASSET_SVG, encoding="utf-8")
    (project_dir / files["icon"]).write_text(ICON_SVG, encoding="utf-8")
    (project_dir / files["avatar"]).write_text(AVATAR_SVG, encoding="utf-8")
    return files


def download_asset(session: requests.Session, url: str, assets_dir: Path, kind: str, timeout: float) -> tuple[str | None, dict[str, Any]]:
    info: dict[str, Any] = {"url": url, "kind": kind, "ok": False}
    try:
        response = session.get(url, timeout=timeout, stream=True)
        info["status"] = response.status_code
        if response.status_code >= 400:
            info["error"] = f"HTTP {response.status_code}"
            return None, info
        content_type = response.headers.get("content-type")
        if content_type and "text/html" in content_type.lower() and kind != "css":
            info["error"] = "html_embed_not_localized"
            return None, info
        ext = safe_ext(url, content_type, ".css" if kind == "css" else ".bin")
        name = f"{kind}_{sha1(url)[:12]}{ext}"
        target = assets_dir / name
        total = 0
        with target.open("wb") as f:
            for chunk in response.iter_content(65536):
                if not chunk:
                    continue
                total += len(chunk)
                if total > 8_000_000:
                    info["error"] = "too_large"
                    target.unlink(missing_ok=True)
                    return None, info
                f.write(chunk)
        if target.stat().st_size == 0:
            target.unlink(missing_ok=True)
            info["error"] = "empty"
            return None, info
        info.update({"ok": True, "path": f"assets/{name}", "bytes": target.stat().st_size, "content_type": content_type})
        return f"assets/{name}", info
    except Exception as exc:  # noqa: BLE001
        info["error"] = f"{type(exc).__name__}: {exc}"
        return None, info


def fallback_for(kind: str, shared: dict[str, str]) -> str | None:
    if kind == "noise":
        return None
    if kind == "icon":
        return shared["icon"]
    if kind == "avatar":
        return shared["avatar"]
    if kind in {"image", "asset"}:
        return shared["visual"]
    if kind == "css":
        return None
    if kind == "font":
        return None
    return shared["visual"]


def rewrite_css_urls(css: str, localize) -> str:
    def repl(match: re.Match[str]) -> str:
        url = match.group("url").strip()
        new = localize(url, context="css")
        return f"url('{new}')" if new else "none"

    return CSS_URL_RE.sub(repl, css)


def rewrite_srcset(value: str, localize) -> str:
    parts = SRCSET_PART_RE.split(value)
    out = []
    for part in parts:
        fields = part.strip().split()
        if not fields:
            continue
        new_url = localize(fields[0], context="srcset")
        if new_url:
            out.append(" ".join([new_url] + fields[1:]))
    return ", ".join(out)


def collect_absolute_child_links(soup: BeautifulSoup, base_url: str = "") -> list[str]:
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        if not href or is_data_or_safe(href) or TRACKING_RE.search(href):
            continue
        absolute = href
        if href.startswith("//"):
            absolute = "https:" + href
        elif not href.startswith(("http://", "https://")):
            if not base_url:
                continue
            absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        clean = parsed._replace(fragment="").geturl()
        if parsed.scheme in {"http", "https"} and clean not in links:
            links.append(clean)
    return links


def read_local_stylesheet(href: str, project_dir: Path | None) -> str:
    if not project_dir:
        return ""
    parsed = urlparse(href)
    if parsed.scheme or href.startswith("//"):
        return ""
    css_path = (project_dir / parsed.path).resolve()
    try:
        css_path.relative_to(project_dir.resolve())
    except ValueError:
        return ""
    if css_path.exists() and css_path.is_file():
        return css_path.read_text(encoding="utf-8", errors="ignore")
    return ""


def official_webcode2m_purify(html: str, uri: str = "", project_dir: Path | None = None) -> tuple[str, dict[str, Any]]:
    """Run the downloaded WebCode2M HTML/CSS purification code when available."""
    info: dict[str, Any] = {
        "enabled": False,
        "source": "third_party/naturalcc/examples/webcode2m/scripts/data_cc_pipeline/format_utils.py",
    }
    if not (formatHtml and formatCss and mergeHtmlCss):
        info["error"] = OFFICIAL_FORMAT_IMPORT_ERROR or "official_format_utils_unavailable"
        return html, info

    try:
        soup = BeautifulSoup(html, "html.parser")
        style_contents = [style.get_text() for style in soup.find_all("style") if style.get_text()]
        for style in soup.find_all("style"):
            style.decompose()
        stylesheet_count = 0
        stylesheet_chars = 0
        for link in soup.find_all("link"):
            href = str(link.get("href") or "").strip()
            rel = " ".join(link.get("rel") or []).lower()
            if href and ("stylesheet" in rel or classify_url(href) == "css"):
                stylesheet_css = read_local_stylesheet(href, project_dir)
                if stylesheet_css.strip():
                    style_contents.append(stylesheet_css)
                    stylesheet_count += 1
                    stylesheet_chars += len(stylesheet_css)
                link.decompose()
        css = "\n".join(style_contents)
        official_html = formatHtml(str(soup), uri)
        official_css = formatCss(css, official_html) if css.strip() else ""
        purified = mergeHtmlCss(official_html, official_css)
        purified_soup = BeautifulSoup(purified, "html.parser")
        for item in list(purified_soup.contents):
            if isinstance(item, Doctype):
                item.extract()
        body = purified_soup.body or purified_soup
        body[OFFICIAL_CLEAN_ATTR] = "webcode2m-format-utils"
        info["enabled"] = True
        info["html_chars_before"] = len(html)
        info["html_chars_after"] = len(str(purified_soup))
        info["css_chars_before"] = len(css)
        info["css_chars_after"] = len(official_css)
        info["local_stylesheet_count"] = stylesheet_count
        info["local_stylesheet_chars"] = stylesheet_chars
        return str(purified_soup), info
    except Exception as exc:  # noqa: BLE001
        info["error"] = f"{type(exc).__name__}: {exc}"
        return html, info


def clean_row(row: dict[str, Any], output_dir: Path, session: requests.Session, args: argparse.Namespace) -> dict[str, Any]:
    row_idx = int(row["row_idx"])
    project_name = f"webcode2m_{row_idx:03d}_{row.get('lang') or 'unk'}"
    project_dir = output_dir / "projects" / project_name
    if project_dir.exists():
        shutil.rmtree(project_dir)
    assets_dir = project_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    shared = write_shared_assets(project_dir)

    html = row.get("text") or ""
    raw_soup = BeautifulSoup(html, "html.parser")
    source_url = str(row.get("url") or "")
    child_links = collect_absolute_child_links(raw_soup, source_url)
    soup = BeautifulSoup(html, "html.parser")
    stats = Counter()
    actions: list[dict[str, Any]] = []
    cache: dict[str, str | None] = {}
    download_infos: list[dict[str, Any]] = []
    placeholder_counter = [0]  # mutable counter for closures

    def _get_placeholder(kind: str, width: int = 800, height: int = 600) -> str | None:
        """Get a diverse placeholder image for unresolvable paths."""
        if kind in {"image", "icon", "avatar", "asset"}:
            idx = placeholder_counter[0]
            placeholder_counter[0] += 1
            local = download_placeholder(session, assets_dir, idx, width, height)
            if local:
                return local
        # Fallback to SVG if picsum download fails
        return fallback_for(kind, shared)

    def localize(raw_url: str, context: str, tag=None) -> str | None:
        url = (raw_url or "").strip().strip("\"'")
        if not url or is_data_or_safe(url):
            return url if url.startswith("data:") else None
        if url in cache:
            return cache[url]
        kind = classify_url(url)
        if kind == "noise":
            stats["removed_noise_ref"] += 1
            actions.append({"url": url, "kind": kind, "action": "removed_noise", "context": context})
            cache[url] = None
            return None
        if is_remote(url):
            absolute = normalize_remote(url)
            local, info = download_asset(session, absolute, assets_dir, kind, args.timeout)
            download_infos.append(info)
            if local:
                stats["downloaded"] += 1
                actions.append({"url": url, "kind": kind, "action": "downloaded", "local": local, "context": context})
                cache[url] = local
                return local
            # Remote download failed — use placeholder
            w, h = extract_img_dimensions(tag) if tag else (800, 600)
            fallback = _get_placeholder(kind, w, h)
            if fallback:
                stats["fallback_asset"] += 1
                actions.append({"url": url, "kind": kind, "action": "fallback", "local": fallback, "context": context, "error": info.get("error")})
            else:
                stats["removed_unavailable"] += 1
                actions.append({"url": url, "kind": kind, "action": "removed_unavailable", "context": context, "error": info.get("error")})
            cache[url] = fallback
            return fallback
        if url.startswith("/"):
            kind = classify_url(url)
            w, h = extract_img_dimensions(tag) if tag else (800, 600)
            fallback = _get_placeholder(kind, w, h)
            if fallback:
                stats["root_relative_fallback"] += 1
                actions.append({"url": url, "kind": kind, "action": "root_relative_fallback", "local": fallback, "context": context})
            else:
                stats["root_relative_removed"] += 1
                actions.append({"url": url, "kind": kind, "action": "root_relative_removed", "context": context})
            cache[url] = fallback
            return fallback
        # Plain relative URLs cannot be resolved because WebCode2M does not ship
        # the original directory. Keep simple anchors/pages, replace asset-like refs.
        kind = classify_url(url)
        if kind in {"image", "icon", "avatar", "asset"}:
            w, h = extract_img_dimensions(tag) if tag else (800, 600)
            fallback = _get_placeholder(kind, w, h)
            stats["relative_fallback"] += 1
            actions.append({"url": url, "kind": kind, "action": "relative_fallback", "local": fallback, "context": context})
            cache[url] = fallback
            return fallback
        cache[url] = url
        return url

    for tag in soup.find_all("script"):
        src = tag.get("src")
        text = tag.get_text(" ", strip=True)
        if src or TRACKING_RE.search(src or text):
            tag.decompose()
            stats["removed_script"] += 1

    for tag in soup.find_all(True):
        if not any(tag.has_attr(attr) for attr in MEDIA_ATTRS + ("srcset",)):
            continue
        removed = False
        for attr in MEDIA_ATTRS:
            if not tag.has_attr(attr):
                continue
            new = localize(str(tag.get(attr)), context=f"{tag.name}.{attr}", tag=tag)
            if new:
                tag[attr] = new
            else:
                if tag.name in {"img", "iframe", "embed"}:
                    tag.decompose()
                    removed = True
                else:
                    del tag[attr]
                break
        if removed:
            continue
        if tag.has_attr("srcset"):
            new_srcset = rewrite_srcset(str(tag["srcset"]), lambda url, ctx: localize(url, ctx, tag=tag))
            if new_srcset:
                tag["srcset"] = new_srcset
            else:
                del tag["srcset"]
        if tag.name == "img" and not tag.get("alt"):
            tag["alt"] = "Decorative visual asset"

    for tag in soup.find_all("link"):
        href = tag.get("href")
        rel = " ".join(tag.get("rel") or []).lower()
        if not href:
            continue
        if any(token in rel for token in ("dns-prefetch", "preconnect", "canonical", "alternate", "manifest")):
            tag.decompose()
            stats["removed_noise_link"] += 1
            continue
        if "stylesheet" in rel or "icon" in rel or classify_url(str(href)) in {"css", "icon"}:
            new = localize(str(href), context=f"link.{rel or 'asset'}", tag=tag)
            if new:
                tag["href"] = new
            else:
                tag.decompose()

    for tag in soup.find_all(style=True):
        tag["style"] = rewrite_css_urls(str(tag["style"]), localize)
    for tag in soup.find_all("style"):
        tag.string = rewrite_css_urls(tag.get_text(), localize)

    # Keep hrefs during local resource rewriting. Official WebCode2M formatting
    # runs after link collection and removes href attributes from the final text.
    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        if TRACKING_RE.search(href):
            a["href"] = "#"
            stats["neutralized_tracking_href"] += 1

    index_path = project_dir / "index.html"
    purified_index, official_clean_info = official_webcode2m_purify(str(soup), uri=source_url, project_dir=project_dir)
    if official_clean_info.get("enabled"):
        stats["official_webcode2m_purified"] += 1
    else:
        stats["official_webcode2m_purify_failed"] += 1
    index_path.write_text(purified_index, encoding="utf-8")

    pages = [{"path": "index.html", "source": "webcode2m_text"}]
    crawl_result = try_crawl_child_pages(child_links, project_dir, session, args, shared, source_url)
    pages.extend(crawl_result["pages"])
    stats.update(crawl_result["stats"])
    actions.extend(crawl_result.get("actions", []))
    download_infos.extend(crawl_result.get("download_results", []))

    image_meta = row.get("image") or {}
    original_img = image_meta.get("local_path")
    if original_img and Path(original_img).exists():
        shutil.copy2(original_img, project_dir / "original_webcode2m_screenshot.png")

    metadata = {
        "project_name": project_name,
        "row_idx": row_idx,
        "hash": row.get("hash"),
        "lang": row.get("lang"),
        "score": row.get("score"),
        "image": row.get("image"),
        "pages": pages,
        "multipage_status": "ok" if len(pages) > 1 else "multipage_unavailable",
        "reason_if_single_page": "no crawlable internal hrefs in source HTML" if len(pages) == 1 else "",
        "stats": dict(stats),
        "official_clean": official_clean_info,
        "resource_actions": actions,
        "download_results": download_infos,
    }
    (project_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"project": project_name, "status": "ok", "stats": dict(stats), "pages": len(pages)}


def safe_child_page_name(parsed_url, index: int, used_names: set[str]) -> str:
    stem = Path(parsed_url.path).stem or f"page_{index+1}"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-") or f"page_{index+1}"
    name = f"{stem}.html"
    if name == "index.html":
        name = f"page_{index+1}.html"
    base = name
    suffix = 2
    while name in used_names:
        name = f"{Path(base).stem}_{suffix}.html"
        suffix += 1
    used_names.add(name)
    return name


def clean_crawled_child_html(
    html: str,
    source_url: str,
    project_dir: Path,
    session: requests.Session,
    args: argparse.Namespace,
    shared: dict[str, str],
) -> tuple[str, Counter, list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    stats = Counter()
    actions: list[dict[str, Any]] = []
    download_infos: list[dict[str, Any]] = []
    assets_dir = project_dir / "assets"
    cache: dict[str, str | None] = {}

    def localize(raw_url: str, context: str) -> str | None:
        url = (raw_url or "").strip().strip("\"'")
        if not url or is_data_or_safe(url):
            return url if url.startswith("data:") else None
        absolute = urljoin(source_url, normalize_remote(url))
        if url in cache:
            return cache[url]
        kind = classify_url(url)
        if kind == "noise":
            stats["child_removed_noise_ref"] += 1
            actions.append({"url": url, "kind": kind, "action": "child_removed_noise", "context": context, "source_page": source_url})
            cache[url] = None
            return None
        if is_remote(url) or url.startswith("/") or kind in {"image", "icon", "avatar", "asset", "css", "font"}:
            local, info = download_asset(session, absolute, assets_dir, kind, args.timeout)
            info["source_page"] = source_url
            download_infos.append(info)
            if local:
                stats["child_downloaded"] += 1
                actions.append({"url": url, "kind": kind, "action": "child_downloaded", "local": local, "context": context, "source_page": source_url})
                cache[url] = local
                return local
            fallback = fallback_for(kind, shared)
            if fallback:
                stats["child_fallback_asset"] += 1
                actions.append({"url": url, "kind": kind, "action": "child_fallback", "local": fallback, "context": context, "source_page": source_url, "error": info.get("error")})
            else:
                stats["child_removed_unavailable"] += 1
                actions.append({"url": url, "kind": kind, "action": "child_removed_unavailable", "context": context, "source_page": source_url, "error": info.get("error")})
            cache[url] = fallback
            return fallback
        cache[url] = url
        return url

    for tag in soup.find_all("script"):
        tag.decompose()
        stats["child_removed_script"] += 1

    for tag in soup.find_all(True):
        if not any(tag.has_attr(attr) for attr in MEDIA_ATTRS + ("srcset",)):
            continue
        removed = False
        for attr in MEDIA_ATTRS:
            if not tag.has_attr(attr):
                continue
            new = localize(str(tag.get(attr)), context=f"child.{tag.name}.{attr}")
            if new:
                tag[attr] = new
            else:
                if tag.name in {"img", "iframe", "embed"}:
                    tag.decompose()
                    removed = True
                else:
                    del tag[attr]
                break
        if removed:
            continue
        if tag.has_attr("srcset"):
            new_srcset = rewrite_srcset(str(tag["srcset"]), localize)
            if new_srcset:
                tag["srcset"] = new_srcset
            else:
                del tag["srcset"]
        if tag.name == "img" and not tag.get("alt"):
            tag["alt"] = "Decorative visual asset"

    for tag in soup.find_all("link"):
        href = tag.get("href")
        rel = " ".join(tag.get("rel") or []).lower()
        if not href:
            continue
        if any(token in rel for token in ("dns-prefetch", "preconnect", "canonical", "alternate", "manifest")):
            tag.decompose()
            stats["child_removed_noise_link"] += 1
            continue
        if "stylesheet" in rel or "icon" in rel or classify_url(str(href)) in {"css", "icon"}:
            new = localize(str(href), context=f"child.link.{rel or 'asset'}")
            if new:
                tag["href"] = new
            else:
                tag.decompose()

    for tag in soup.find_all(style=True):
        tag["style"] = rewrite_css_urls(str(tag["style"]), localize)
    for tag in soup.find_all("style"):
        tag.string = rewrite_css_urls(tag.get_text(), localize)
    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        if TRACKING_RE.search(href):
            a["href"] = "#"
            stats["child_neutralized_tracking_href"] += 1

    purified, official_info = official_webcode2m_purify(str(soup), uri=source_url, project_dir=project_dir)
    if official_info.get("enabled"):
        stats["child_official_webcode2m_purified"] += 1
    else:
        stats["child_official_webcode2m_purify_failed"] += 1
    return purified, stats, actions, download_infos, official_info


def try_crawl_child_pages(
    links: list[str],
    project_dir: Path,
    session: requests.Session,
    args: argparse.Namespace,
    shared: dict[str, str],
    source_url: str = "",
) -> dict[str, Any]:
    if not links or args.max_child_pages <= 0:
        return {"pages": [], "stats": Counter(), "actions": [], "download_results": []}
    stats = Counter()
    actions: list[dict[str, Any]] = []
    download_results: list[dict[str, Any]] = []
    parsed_links = [urlparse(link) for link in links if link.startswith(("http://", "https://"))]
    if not parsed_links:
        return {"pages": [], "stats": stats, "actions": actions, "download_results": download_results}
    source_domain = urlparse(source_url).netloc
    domain_counts = Counter(p.netloc for p in parsed_links)
    base_domain = source_domain or domain_counts.most_common(1)[0][0]
    pages = []
    seen = set()
    used_names = {"index.html"}
    attempts = 0
    for link in links:
        parsed = urlparse(link)
        if parsed.netloc != base_domain or link in seen:
            continue
        path_suffix = Path(parsed.path).suffix.lower()
        if path_suffix and path_suffix not in {".html", ".htm", ".php", ".asp", ".aspx"}:
            continue
        seen.add(link)
        if len(pages) >= args.max_child_pages:
            break
        if attempts >= args.max_child_attempts:
            break
        attempts += 1
        try:
            response = session.get(link, timeout=args.timeout)
            if response.status_code >= 400 or "text/html" not in response.headers.get("content-type", ""):
                stats["child_page_failed"] += 1
                continue
            name = safe_child_page_name(parsed, len(pages), used_names)
            target = project_dir / name
            cleaned_html, child_stats, child_actions, child_downloads, official_info = clean_crawled_child_html(
                response.text,
                link,
                project_dir,
                session,
                args,
                shared,
            )
            target.write_text(cleaned_html, encoding=response.encoding or "utf-8", errors="ignore")
            pages.append({"path": name, "source": link, "official_clean": official_info})
            stats["child_page_downloaded"] += 1
            stats.update(child_stats)
            actions.extend(child_actions)
            download_results.extend(child_downloads)
            time.sleep(0.2)
        except Exception as exc:  # noqa: BLE001
            stats["child_page_failed"] += 1
            actions.append({"url": link, "action": "child_page_failed", "error": f"{type(exc).__name__}: {exc}"})
    return {"pages": pages, "stats": stats, "actions": actions, "download_results": download_results}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples-jsonl", type=Path, default=Path("paper/research_samples/webcode2m_100_samples/samples.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("WebCoding_Data/local_trials/webcode2m_clean_100"))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--max-child-pages", type=int, default=6)
    parser.add_argument("--max-child-attempts", type=int, default=30)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--proxy", default=None, help="SOCKS5 proxy, e.g. socks5h://127.0.0.1:13659")
    args = parser.parse_args()

    if args.output_dir.exists() and args.overwrite:
        shutil.rmtree(args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    with args.samples_jsonl.open(encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    if args.limit:
        rows = rows[: args.limit]

    session = build_session(proxy=args.proxy)
    manifest = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(clean_row, row, args.output_dir, session, args) for row in rows]
        for future in as_completed(futures):
            try:
                item = future.result()
            except Exception as exc:  # noqa: BLE001
                item = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            manifest.append(item)
            print(json.dumps(item, ensure_ascii=False), flush=True)

    manifest = sorted(manifest, key=lambda x: x.get("project", ""))
    summary = Counter()
    for item in manifest:
        summary[item["status"]] += 1
        for key, value in item.get("stats", {}).items():
            summary[key] += value
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_dir / "summary.json").write_text(json.dumps(dict(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    print("SUMMARY", json.dumps(dict(summary), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
