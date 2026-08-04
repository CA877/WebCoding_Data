#!/usr/bin/env python3
"""Pipeline C URL crawler.

The crawler makes resource decisions while it has the original page available.
It deliberately has no screenshot code: visual assets are generated only by the
downstream final-sample stage after this project's code is frozen.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import functools
import hashlib
import http.server
import httpx
import json
import multiprocessing as mp
import mimetypes
import os
import re
import shutil
import socket
import socketserver
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import BrowserContext, Page, sync_playwright
import tinycss2
from tinycss2.ast import FunctionBlock, URLToken

from .policy import HtmlAssessment, assess_html, classify_resource, infer_image_dimensions, picsum_url, ui_image_placeholder
from .qwen_token_gate import project_context_stats
from .offline_rescue import normalize_existing_project
from .visual_review import review_screenshot
from preprocess.purge_css import purge_project
from preprocess.final_screenshot import capture_all as capture_all_final_screenshots


TRACKER_RE = re.compile(
    r"google-analytics|googletagmanager|doubleclick|facebook\.net|hotjar|mixpanel|segment|"
    r"clarity\.ms|adsbygoogle|optimizely|tiktok.*pixel|cookie(consent)?", re.I
)
TYPEKIT_TELEMETRY_RE = re.compile(r"Typekit\.load|p\.typekit\.net", re.I)
UI_IMAGE_RE = re.compile(r"(?:logo|favicon|icon|privacy|badge|avatar|symbol)", re.I)
CHALLENGE_RE = re.compile(
    r"AWSC/et|cf-challenge|turnstile|hcaptcha|recaptcha|captcha|verify you are human|"
    r"checking your browser|enable javascript and cookies", re.I,
)
PREFLIGHT_DENY_RE = re.compile(r"porn|sex|escort|adult|casino|bet(?:ting)?|gambl|drug|cocaine|weapon|gun|xxx|cam", re.I)
PREFLIGHT_HOSTING_RE = re.compile(
    r"(?:netsolhost|netsolstores|rcomhost|myftpupload|wpengine|clickbank|blogspot|"
    r"hosting|free-counters|mystat|nxcli|c-o-u-n-t)\.", re.I,
)
IMAGE_EXT_RE = re.compile(r"\.(?:avif|bmp|gif|ico|jpe?g|png|svg|webp)(?:[?#].*)?$", re.I)
FONT_EXT_RE = re.compile(r"\.(?:eot|otf|ttf|woff2?)(?:[?#].*)?$", re.I)
CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I)
JS_IMPORT_RE = re.compile(r"(?:(?:import|export)\s+(?:[^'\"]*?\s+from\s+)?|import\s*\()(['\"])([^'\"]+)\1", re.M)
FRAMEWORK_RUNTIME_RE = re.compile(
    r"/(?:_next|_nuxt|_astro)(?:/|$)|(?:^|[._/-])(?:webpack|runtime|vite|react(?:-dom)?)(?:[._/-]|$)", re.I
)
VENDOR_JS_RE = re.compile(
    r"(?:^|[._/-])(?:jquery(?:-migrate)?|bootstrap|swiper|slick|gsap|three(?:\.min)?|"
    r"lodash|moment|anime|lottie|lightbox|fancybox|videojs|mediaelement)(?:[._/-]|$)", re.I
)
MAX_AUTHOR_JS_BYTES = 192 * 1024
MAX_AUTHOR_JS_LINE_RATIO = 0.45
MAX_FIRST_PARTY_IMAGE_BYTES = 5 * 1024 * 1024
MAX_FIRST_PARTY_IMAGE_TOTAL_BYTES = 30 * 1024 * 1024


class CrawlRejected(RuntimeError):
    pass


class ExcludedScript(RuntimeError):
    """A script is real but is not eligible author code for training."""
    pass


_PREFLIGHT_LOCAL = threading.local()


def _preflight_client(timeout: float) -> httpx.Client:
    """Reuse proxy connections within each thread instead of reconnecting per URL."""
    client = getattr(_PREFLIGHT_LOCAL, "client", None)
    client_timeout = getattr(_PREFLIGHT_LOCAL, "timeout", None)
    if client is None or client_timeout != timeout:
        if client is not None:
            client.close()
        client = httpx.Client(
            follow_redirects=True,
            headers={"Range": "bytes=0-65535"},
            timeout=httpx.Timeout(timeout, connect=min(timeout, 10)),
            verify=False,
            trust_env=True,
        )
        _PREFLIGHT_LOCAL.client = client
        _PREFLIGHT_LOCAL.timeout = timeout
    return client


def sample_preflight(url: str, timeout: float = 12.0) -> tuple[bool, str, str]:
    """Cheap per-sample HTTP gate run immediately before browser crawling."""
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    label = hostname.removeprefix("www.").split(".")[0]
    if (parsed.scheme not in {"http", "https"} or not hostname or PREFLIGHT_DENY_RE.search(url)
            or PREFLIGHT_HOSTING_RE.search(hostname) or len(label) < 3
            or sum(char.isdigit() for char in label) > 2):
        return False, url, "static_url_reject"
    response = None
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = _preflight_client(timeout).get(url)
            break
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
        except (httpx.HTTPError, UnicodeError) as exc:
            return False, url, f"request_failed:{type(exc).__name__}"
    if response is None:
        return False, url, f"request_failed:{type(last_error).__name__}"
    try:
        content_type = response.headers.get("content-type", "").lower()
        text = response.text[:20_000]
        if response.status_code >= 400:
            return False, str(response.url), f"http_status:{response.status_code}"
        if "html" not in content_type:
            return False, str(response.url), "non_html"
        if len(text) < 3000:
            return False, str(response.url), "html_too_short"
        if CHALLENGE_RE.search(text):
            return False, str(response.url), "challenge_page"
        return True, str(response.url), "pass"
    except (httpx.HTTPError, UnicodeError) as exc:
        return False, url, f"request_failed:{type(exc).__name__}"


def rewrite_css_ast(css_text: str, stylesheet_url: str, localize_css, replace_relative_image) -> str:
    """Rewrite CSS dependencies through tinycss2's parsed AST, never regex CSS."""
    rules = tinycss2.parse_stylesheet(css_text, skip_comments=False, skip_whitespace=False)

    def rewrite_values(values, context: str) -> None:
        for token in values:
            if isinstance(token, URLToken):
                raw = token.value.strip()
                if _is_relative(raw):
                    absolute = urljoin(stylesheet_url, raw)
                    replacement = replace_relative_image(absolute, context)
                    token.value = replacement
                    token.representation = f'url("{replacement}")'
            elif isinstance(token, FunctionBlock):
                if token.name.lower() == "url":
                    raw = tinycss2.serialize(token.arguments).strip().strip("'\"")
                    if _is_relative(raw):
                        absolute = urljoin(stylesheet_url, raw)
                        replacement = replace_relative_image(absolute, context)
                        token.arguments = tinycss2.parse_component_value_list(f'"{replacement}"')
                else:
                    rewrite_values(token.arguments, context)
            elif hasattr(token, "content") and token.content is not None:
                rewrite_values(token.content, context)

    for rule in rules:
        if rule.type == "at-rule" and rule.lower_at_keyword == "import":
            import_tokens = rule.prelude or []
            raw = ""
            for token in import_tokens:
                if isinstance(token, URLToken): raw = token.value
                elif isinstance(token, FunctionBlock) and token.name.lower() == "url": raw = tinycss2.serialize(token.arguments).strip().strip("'\"")
                elif token.type == "string": raw = token.value
                if raw: break
            if raw and _is_relative(raw):
                local = localize_css(urljoin(stylesheet_url, raw))
                rule.prelude = tinycss2.parse_component_value_list(f' url("{local}")')
        if getattr(rule, "content", None) is not None:
            rewrite_values(rule.content, tinycss2.serialize(rule.prelude or []))
    return tinycss2.serialize(rules)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _filename(url: str, fallback: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if not suffix or len(suffix) > 8:
        suffix = fallback
    return f"{_sha(url)}{suffix}"


def _is_relative(raw: str) -> bool:
    return bool(raw) and not raw.startswith(("http://", "https://", "//", "data:", "blob:", "#"))


def _same_site_hosts(left: str, right: str) -> bool:
    if left == right:
        return True
    a, b = left.lower().split("."), right.lower().split(".")
    return len(a) >= 2 and len(b) >= 2 and a[-2:] == b[-2:]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def discover_same_site_pages(html: str, page_url: str, max_pages: int) -> list[str]:
    """Collect navigational same-site HTML targets, excluding auth/download anchors."""
    origin = urlparse(page_url)
    found: list[str] = []
    for anchor in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        raw = anchor["href"].strip()
        if raw.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
            continue
        absolute = urljoin(page_url, raw).split("#", 1)[0]
        parsed = urlparse(absolute)
        if not parsed.scheme.startswith("http") or not _same_site_hosts(parsed.hostname or "", origin.hostname or ""):
            continue
        if re.search(r"/(?:wp-login|wp-admin|logout|cart|checkout)(?:/|$)|\.(?:pdf|zip|jpg|png|css|js)$", parsed.path, re.I):
            continue
        if absolute != page_url and absolute not in found:
            found.append(absolute)
        if len(found) >= max_pages:
            break
    return found


def local_page_name(url: str) -> str:
    return "page_" + _sha(url) + ".html"


def rewrite_local_page_links(html: str, page_url: str, page_map: dict[str, str]) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        absolute = urljoin(page_url, anchor["href"]).split("#", 1)[0]
        if absolute in page_map:
            anchor["href"] = page_map[absolute]
    return str(soup)


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        return


class _ValidationServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


@dataclass
class ResourceLog:
    first_party_css_downloaded: int = 0
    first_party_js_downloaded: int = 0
    first_party_fonts_downloaded: int = 0
    font_files_skipped: int = 0
    first_party_images_downloaded: int = 0
    first_party_image_bytes: int = 0
    relative_images_picsum_replaced: int = 0
    third_party_libraries_preserved: list[str] = field(default_factory=list)
    remote_code_preserved: list[str] = field(default_factory=list)
    remote_css_default_font_overrides: int = 0
    third_party_code_removed: list[str] = field(default_factory=list)
    framework_runtime_kept: list[str] = field(default_factory=list)
    excluded_first_party_scripts: list[dict[str, str]] = field(default_factory=list)
    loaded_first_party_script_responses: int = 0
    mirrored_first_party_responses: int = 0
    mirrored_first_party_bytes: int = 0
    skipped_oversize_first_party_responses: list[str] = field(default_factory=list)
    tracking_removed: int = 0
    required_resource_failures: list[dict[str, str]] = field(default_factory=list)


class FirstPartyResponseMirror:
    """Persist responses that a framework actually loaded at their URL paths.

    A Next/Nuxt/Astro runtime commonly imports ``/_next/...`` or ``/_nuxt/...``
    after the initial HTML has been parsed.  Keeping those paths beneath the
    project lets a local HTTP server satisfy the exact same absolute-path
    request.  This complements (rather than replaces) explicit HTML/CSS rewrite.
    """

    _RESOURCE_TYPES = {"script", "stylesheet", "font", "image", "media", "manifest", "fetch", "xhr", "other"}
    _MAX_ITEM_BYTES = 20 * 1024 * 1024
    _MAX_TOTAL_BYTES = 150 * 1024 * 1024

    def __init__(self, project_dir: Path, origin_url: str, log: ResourceLog) -> None:
        self.project_dir, self.origins, self.log = project_dir, {urlparse(origin_url).hostname}, log
        self._written_urls: set[str] = set()

    def add_origin(self, url: str) -> None:
        hostname = urlparse(url).hostname
        if hostname:
            self.origins.add(hostname)

    def _target(self, url: str) -> Path | None:
        parsed = urlparse(url)
        # The browser will resolve root-relative URLs against localhost in the
        # frozen project.  Only exact-origin responses can safely be served at
        # that path; cross-origin dependencies stay absolute and remote.
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in self.origins:
            return None
        # These are server-side image optimisation APIs, not static files.  A
        # local static server cannot reproduce their query semantics; HTML image
        # rewrite handles their underlying relative source instead.
        if parsed.path in {"/_next/image", "/_vercel/image"}:
            return None
        path = parsed.path or "/"
        if path.endswith("/"):
            path += "index.html"
        parts = Path(path.lstrip("/")).parts
        if not parts or any(part in {"", ".", ".."} for part in parts):
            return None
        return self.project_dir.joinpath(*parts)

    def capture(self, response: Any) -> None:
        try:
            request = response.request
            if not response.ok or request.resource_type not in self._RESOURCE_TYPES:
                return
            target = self._target(response.url)
            if target is None or response.url in self._written_urls:
                return
            content_length = int(response.headers.get("content-length", "0") or 0)
            if content_length > self._MAX_ITEM_BYTES or self.log.mirrored_first_party_bytes >= self._MAX_TOTAL_BYTES:
                self.log.skipped_oversize_first_party_responses.append(response.url)
                return
            body = response.body()
            if not body or len(body) > self._MAX_ITEM_BYTES or self.log.mirrored_first_party_bytes + len(body) > self._MAX_TOTAL_BYTES:
                self.log.skipped_oversize_first_party_responses.append(response.url)
                return
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
            self._written_urls.add(response.url)
            self.log.mirrored_first_party_responses += 1
            self.log.mirrored_first_party_bytes += len(body)
        except Exception:
            # Mirroring is opportunistic.  The final local validation remains
            # the source of truth and will report any required missing asset.
            return

    def local_url(self, url: str) -> str | None:
        """Return the root-local URL only after its frozen copy exists."""
        target = self._target(url)
        if target is None or not target.is_file():
            return None
        return "/" + target.relative_to(self.project_dir).as_posix()


class ResourceLocalizer:
    def __init__(self, context: BrowserContext, page_url: str, project_dir: Path,
                 computed_sizes: dict[str, tuple[int, int]] | None = None,
                 resource_log: ResourceLog | None = None,
                 mirror: FirstPartyResponseMirror | None = None) -> None:
        self.context, self.page_url, self.project_dir = context, page_url, project_dir
        self.resources = project_dir / "resources"
        self.resources.mkdir(parents=True, exist_ok=True)
        self.log = resource_log or ResourceLog()
        self.mirror = mirror
        self._written: dict[str, str] = {}
        self.computed_sizes = computed_sizes or {}
        self.loaded_script_responses: dict[str, tuple[bytes, str]] = {}
        self._excluded_scripts: dict[str, str] = {}
        self._excluded_vendor_globals: set[str] = set()
        self.observed_script_sizes: dict[str, int] = {}

    def set_loaded_script_responses(self, responses: dict[str, tuple[bytes, str]]) -> None:
        self.loaded_script_responses = responses

    def set_observed_script_sizes(self, sizes: dict[str, int]) -> None:
        self.observed_script_sizes = sizes

    def _upgrade_first_party_http(self, url: str) -> str:
        """Avoid mixed content when a secure page references its own HTTP asset."""
        parsed, page = urlparse(url), urlparse(self.page_url)
        if parsed.scheme == "http" and page.scheme == "https" and _same_site_hosts(parsed.hostname or "", page.hostname or ""):
            return parsed._replace(scheme="https").geturl()
        return url

    def _css_image_dimensions(self, css: str, position: int) -> tuple[int, int]:
        """Use the source selector's rendered element box before heuristic fallback."""
        brace = css.rfind("{", 0, position)
        selector_start = max(css.rfind("}", 0, brace), css.rfind(";", 0, brace)) + 1
        selector = css[selector_start:brace]
        for token in re.findall(r"[.#][A-Za-z_][\w-]*", selector):
            if token in self.computed_sizes:
                return self.computed_sizes[token]
        context = css[brace:css.find("}", position) + 1] if brace >= 0 else ""
        wh = re.search(r"background-size\s*:\s*(\d+)px\s+(\d+)px", context, re.I)
        if wh:
            return int(wh.group(1)), int(wh.group(2))
        return (1920, 1080) if "background" in context.lower() else (400, 300)

    def _fetch(self, url: str) -> tuple[bytes, str]:
        url = self._upgrade_first_party_http(url)
        if url in self.loaded_script_responses:
            return self.loaded_script_responses[url]
        try:
            response = self.context.request.get(url, timeout=30_000)
            if not response.ok:
                raise CrawlRejected(f"HTTP {response.status}")
            body = response.body()
            if len(body) < 2:
                raise CrawlRejected("empty response")
            return body, response.headers.get("content-type", "")
        except Exception as exc:
            self.log.required_resource_failures.append({"url": url, "error": str(exc)})
            raise CrawlRejected(f"required_resource_fetch_failed: {url}: {exc}") from exc

    def _author_script_reason(self, url: str, text: str) -> str | None:
        """Reject build output/vendor JS without treating it as a fetch failure.

        Origin is deliberately not used as a positive signal: a first-party
        host commonly serves Webpack bundles, copied libraries and minified
        CMS plugins.  We keep only small, multi-line code that a model can
        reasonably learn as page-specific author logic.
        """
        path = urlparse(url).path
        if "jquery" in self._excluded_vendor_globals and re.search(r"\bjQuery\b|\$\s*\(", text):
            return "requires_excluded_jquery"
        # Framework runtime is render-only source: it is omitted from the
        # learner prompt by qwen_token_gate, but must remain in the frozen
        # project for local rendering.  This matches legacy normalization.
        if FRAMEWORK_RUNTIME_RE.search(path):
            self.log.framework_runtime_kept.append(url)
            return None
        if VENDOR_JS_RE.search(path):
            return "known_vendor_library"
        size = len(text.encode("utf-8", errors="replace"))
        if size > MAX_AUTHOR_JS_BYTES:
            return f"oversize:{size}"
        nonempty = [line for line in text.splitlines() if line.strip()]
        longest = max((len(line) for line in nonempty), default=0)
        if size >= 2_048 and longest / max(size, 1) >= MAX_AUTHOR_JS_LINE_RATIO:
            return "minified_single_line"
        # Common bundle banners remain useful evidence even when the filename
        # was hashed by a CMS/CDN.
        prefix = text[:4_096]
        if re.search(r"(?:webpackBootstrap|__webpack_require__|vite:preload|React\.createElement|jQuery v\d)", prefix):
            return "bundle_signature"
        return None

    def _write_binary(self, url: str, fallback: str, kind: str) -> str:
        if url in self._written:
            return self._written[url]
        body, content_type = self._fetch(url)
        if kind == "image":
            if len(body) > MAX_FIRST_PARTY_IMAGE_BYTES:
                raise CrawlRejected(f"relative_image_over_limit:{url}:{len(body)}")
            if self.log.first_party_image_bytes + len(body) > MAX_FIRST_PARTY_IMAGE_TOTAL_BYTES:
                raise CrawlRejected(f"relative_images_total_over_limit:{MAX_FIRST_PARTY_IMAGE_TOTAL_BYTES}")
        suffix = Path(urlparse(url).path).suffix or mimetypes.guess_extension(content_type.split(";", 1)[0]) or fallback
        target = self.resources / f"{_sha(url)}{suffix}"
        target.write_bytes(body)
        local = f"./resources/{target.name}"
        self._written[url] = local
        if kind == "font": self.log.first_party_fonts_downloaded += 1
        if kind == "image":
            self.log.first_party_images_downloaded += 1
            self.log.first_party_image_bytes += len(body)
        return local

    def localize_image(self, url: str) -> str:
        """Persist a relative first-party image so frozen CSS/HTML has no path break."""
        return self._write_binary(url, ".img", "image")

    def localize_css(self, url: str) -> str:
        url = self._upgrade_first_party_http(url)
        if url in self._written:
            return self._written[url]
        body, _ = self._fetch(url)
        text = body.decode("utf-8", errors="replace")
        target = self.resources / _filename(url, ".css")
        local = f"./resources/{target.name}"
        self._written[url] = local

        def local_import(import_url: str) -> str:
            if self.mirror and (mirrored := self.mirror.local_url(import_url)):
                return mirrored
            child = self.localize_css(import_url)
            return "./" + Path(child).name

        def replace_image(image_url: str, context: str) -> str:
            if self.mirror and (mirrored := self.mirror.local_url(image_url)):
                return mirrored
            # Font URL tokens are handled separately by inspecting their suffix.
            if FONT_EXT_RE.search(image_url):
                self.log.font_files_skipped += 1
                return "data:font/woff2;base64,"
            width, height = self._css_image_dimensions(text, text.find(context))
            self.log.relative_images_picsum_replaced += 1
            return picsum_url(image_url, width, height)

        target.write_text(rewrite_css_ast(text, url, local_import, replace_image), encoding="utf-8")
        self.log.first_party_css_downloaded += 1
        return local

    def localize_js(self, url: str) -> str:
        url = self._upgrade_first_party_http(url)
        if url in self._excluded_scripts:
            raise ExcludedScript(self._excluded_scripts[url])
        if url in self._written:
            return self._written[url]
        observed_size = self.observed_script_sizes.get(url, 0)
        if observed_size > MAX_AUTHOR_JS_BYTES:
            reason = f"oversize_response:{observed_size}"
            self._excluded_scripts[url] = reason
            self.log.excluded_first_party_scripts.append({"url": url, "reason": reason})
            raise ExcludedScript(reason)
        body, _ = self._fetch(url)
        text = body.decode("utf-8", errors="replace")
        if reason := self._author_script_reason(url, text):
            self._excluded_scripts[url] = reason
            self.log.excluded_first_party_scripts.append({"url": url, "reason": reason})
            if reason == "known_vendor_library" and "jquery" in url.lower():
                self._excluded_vendor_globals.add("jquery")
            raise ExcludedScript(reason)
        target = self.resources / _filename(url, ".js")
        local = f"./resources/{target.name}"
        self._written[url] = local

        def replace_import(match: re.Match[str]) -> str:
            raw = match.group(2)
            if not _is_relative(raw):
                return match.group(0)
            absolute = urljoin(url, raw)
            child = self.mirror.local_url(absolute) if self.mirror else None
            child = child or self.localize_js(absolute)
            # Module URLs are relative to the current file in resources/.
            replacement = child if child.startswith("/") else "./" + Path(child).name
            return match.group(0).replace(raw, replacement)

        try:
            rewritten = JS_IMPORT_RE.sub(replace_import, text)
        except ExcludedScript:
            self._written.pop(url, None)
            target.unlink(missing_ok=True)
            raise
        target.write_text(rewritten, encoding="utf-8")
        self.log.first_party_js_downloaded += 1
        return local

    def rewrite_html(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        base_tag = soup.find("base", href=True)
        resolution_base = urljoin(self.page_url, base_tag.get("href", "")) if base_tag else self.page_url
        for base in soup.find_all("base"):
            base.decompose()  # Every source dependency is made explicit below.
        # Analytics often hides in a noscript iframe, so script-only removal is
        # insufficient for a static project.
        for noscript in list(soup.find_all("noscript")):
            if TRACKER_RE.search(noscript.decode_contents()):
                noscript.decompose(); self.log.tracking_removed += 1
        for iframe in list(soup.find_all("iframe", src=True)):
            if TRACKER_RE.search(iframe.get("src", "")):
                iframe.decompose(); self.log.tracking_removed += 1
        for script in list(soup.find_all("script")):
            src = script.get("src", "")
            text = script.string or ""
            if TRACKER_RE.search(src) or TRACKER_RE.search(text):
                script.decompose(); self.log.tracking_removed += 1; continue
            if TYPEKIT_TELEMETRY_RE.search(src) or TYPEKIT_TELEMETRY_RE.search(text):
                # @font-face declarations remain; only the telemetry/loader JS is removed.
                script.decompose(); self.log.tracking_removed += 1; continue
            if not src:
                continue
            decision = classify_resource(src, resolution_base, "js")
            if decision.action in {"absolutize_source", "preserve_third_party_library", "preserve_remote_code"}:
                script["src"] = decision.absolute_url
                self.log.remote_code_preserved.append(decision.absolute_url)
                if decision.action == "preserve_third_party_library":
                    self.log.third_party_libraries_preserved.append(decision.absolute_url)
        has_stylesheet = False
        for link in list(soup.find_all("link")):
            rel, href = " ".join(link.get("rel") or []).lower(), link.get("href", "")
            if "stylesheet" not in rel or not href:
                continue
            has_stylesheet = True
            decision = classify_resource(href, resolution_base, "css")
            if decision.action in {"absolutize_source", "preserve_third_party_library", "preserve_remote_code"}:
                link["href"] = decision.absolute_url
                self.log.remote_code_preserved.append(decision.absolute_url)
                if decision.action == "preserve_third_party_library":
                    self.log.third_party_libraries_preserved.append(decision.absolute_url)
        if has_stylesheet:
            override = soup.new_tag("style")
            override["data-remote-font-fallback"] = "system-default"
            override.string = (
                "html,body,button,input,select,textarea,body *,body *::before,body *::after{"
                "font-family:Arial,Helvetica,sans-serif!important}"
            )
            (soup.head or soup).append(override)
            self.log.remote_css_default_font_overrides = 1
        for tag in soup.find_all(["img", "source", "input"]):
            if tag.name == "input" and tag.get("type", "").lower() != "image":
                continue
            width, height, _ = infer_image_dimensions(str(tag))
            for attr in ("src", "data-src", "data-lazy-src", "data-original", "poster"):
                raw = tag.get(attr, "")
                if raw and _is_relative(raw):
                    tag[attr] = urljoin(resolution_base, raw)
            if tag.get("srcset"):
                candidates = []
                for item in tag["srcset"].split(","):
                    parts = item.strip().split()
                    if parts and _is_relative(parts[0]):
                        parts[0] = urljoin(resolution_base, parts[0])
                    candidates.append(" ".join(parts))
                tag["srcset"] = ", ".join(candidates)
        for tag in soup.find_all(style=True):
            def inline_url(match: re.Match[str]) -> str:
                raw = match.group(2).strip()
                if _is_relative(raw):
                    return f'url("{urljoin(resolution_base, raw)}")'
                return match.group(0)
            tag["style"] = CSS_URL_RE.sub(inline_url, tag["style"])
        return str(soup)


def _validate_local(project_dir: Path, browser_proxy: str, wait_ms: int) -> dict[str, Any]:
    """Render final local code with Playwright but intentionally do not take a screenshot."""
    port = _free_port()
    handler = functools.partial(_QuietHandler, directory=str(project_dir))
    server = _ValidationServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    console_errors: list[str] = []; failed: list[str] = []; page_errors: list[str] = []
    try:
        with sync_playwright() as p:
            # Serve the project over HTTP but bypass SOCKS only for the local
            # server; its remote images/fonts still use the browser proxy.
            browser = p.chromium.launch(
                headless=True,
                proxy={"server": browser_proxy} if browser_proxy else None,
                args=["--proxy-bypass-list=127.0.0.1,localhost"] if browser_proxy else None,
            )
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.on("requestfailed", lambda req: failed.append(f"{req.url}: {req.failure}"))
            page.on("response", lambda response: failed.append(f"{response.status}: {response.url}")
                    if response.status >= 400 and response.request.resource_type in {"script", "stylesheet", "image", "font"} else None)
            page.goto(f"http://127.0.0.1:{port}/index.html", wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_timeout(wait_ms)
            text = page.locator("body").inner_text(timeout=10_000)
            browser.close()
        return {"ok": len(text.strip()) >= 50 and not page_errors and not failed, "console_errors": console_errors[:20],
                "page_errors": page_errors[:20], "failed_requests": failed[:40], "text_chars": len(text)}
    finally:
        server.shutdown(); server.server_close()


def crawl_one(url: str, output_root: Path, browser_proxy: str, wait_ms: int,
              qwen_tokenizer: Path, max_training_code_tokens: int, max_child_pages: int,
              visual_review: bool = True, exclude_render_bundles: bool = True) -> dict[str, Any]:
    project_id = _sha(url)
    project_dir = output_root / "projects" / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"source_url": url, "project_id": project_id, "status": "rejected",
                              "exclude_render_bundles": exclude_render_bundles}
    localizer: ResourceLocalizer | None = None
    validation: dict[str, Any] | None = None
    token_usage: dict[str, int] | None = None
    css_purge: dict[str, Any] | None = None
    visual_review_result: dict[str, Any] | None = None
    final_screenshot_path: Path | None = None
    resource_log = ResourceLog()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, proxy={"server": browser_proxy} if browser_proxy else None)
            context = browser.new_context(viewport={"width": 1280, "height": 800}, ignore_https_errors=True)
            page = context.new_page()
            # Cache only scripts the real page actually executed.  This avoids
            # downloading directory/orphan JS, trackers, or a second copy of a
            # first-party script that was already available in the browser.
            loaded_scripts: dict[str, tuple[bytes, str]] = {}
            observed_script_sizes: dict[str, int] = {}

            def cache_loaded_script(response) -> None:
                try:
                    if response.request.resource_type != "script" or not response.ok:
                        return
                    script_url = response.url
                    if TRACKER_RE.search(script_url) or TYPEKIT_TELEMETRY_RE.search(script_url):
                        return
                    # The final redirect host may be different from the input;
                    # only cache first-party scripts relative to the active page.
                    if classify_resource(script_url, page.url or url, "js").action != "localize_required":
                        return
                    if FRAMEWORK_RUNTIME_RE.search(urlparse(script_url).path) or VENDOR_JS_RE.search(urlparse(script_url).path):
                        return
                    content_length = int(response.headers.get("content-length", "0") or 0)
                    if content_length:
                        observed_script_sizes[script_url] = content_length
                    if content_length > MAX_AUTHOR_JS_BYTES:
                        return
                    body = response.body()
                    if len(body) > MAX_AUTHOR_JS_BYTES:
                        return
                    loaded_scripts[script_url] = (body, response.headers.get("content-type", ""))
                except Exception:
                    # A response cache miss safely falls back to the required
                    # first-party fetch path and is recorded if that fails.
                    return

            page.on("response", cache_loaded_script)
            # Modern sites can keep parser-blocking third-party work alive long
            # after the document itself is available.  Waiting for commit gets
            # the actual HTML response without letting analytics/CDN stalls
            # consume the whole site budget; the later content and local-render
            # gates remain the acceptance criteria.
            response = page.goto(url, wait_until="commit", timeout=30_000)
            page.wait_for_timeout(wait_ms)
            if response is None or response.status >= 400:
                raise CrawlRejected(f"navigation_failed:{response.status if response else 'no_response'}")
            source_html = page.content()
            assessment: HtmlAssessment = assess_html(source_html)
            if not assessment.passed:
                raise CrawlRejected(";".join(assessment.reasons))
            if CHALLENGE_RE.search(source_html):
                raise CrawlRejected("unavailable_or_challenge_page")
            raw_sizes = page.evaluate("""() => {
                const sizes = {};
                for (const el of document.querySelectorAll('[id], [class]')) {
                    const box = el.getBoundingClientRect();
                    if (box.width < 1 || box.height < 1) continue;
                    if (el.id) sizes['#' + el.id] = [Math.round(box.width), Math.round(box.height)];
                    for (const name of el.classList) {
                        const key = '.' + name;
                        const prior = sizes[key] || [0, 0];
                        sizes[key] = [Math.max(prior[0], Math.round(box.width)), Math.max(prior[1], Math.round(box.height))];
                    }
                }
                return sizes;
            }""")
            sizes = {key: (int(value[0]), int(value[1])) for key, value in raw_sizes.items()}
            final_url = page.url
            # Resource discovery deliberately has no screenshot.  It triggers
            # lazy framework chunks/models before freezing the local project.
            page.evaluate("""async () => {
                const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
                const limit = Math.min(document.documentElement.scrollHeight, innerHeight * 12);
                for (let y = 0; y < limit; y += Math.max(300, innerHeight * .8)) {
                    scrollTo(0, y); await pause(120);
                }
                scrollTo(0, 0);
            }""")
            page.wait_for_timeout(800)
            # Training-only output: do not persist a framework/runtime mirror.
            # If a retained author script relies on dynamic chunks, the local
            # validation gate rejects it; Pipeline C never emits a separate
            # render archive.
            localizer = ResourceLocalizer(context, final_url, project_dir, sizes, resource_log, mirror=None)
            localizer.set_loaded_script_responses(loaded_scripts)
            localizer.set_observed_script_sizes(observed_script_sizes)
            localizer.log.loaded_first_party_script_responses = len(loaded_scripts)
            page_sources: dict[str, tuple[str, str]] = {final_url: ("index.html", source_html)}
            # Only follow pages that are reachable from the accepted homepage.
            # Child failure is recorded but does not discard a valid homepage.
            child_failures: list[dict[str, str]] = []
            for child_url in discover_same_site_pages(source_html, final_url, max_pages=max_child_pages):
                try:
                    child_response = page.goto(child_url, wait_until="commit", timeout=30_000)
                    page.wait_for_timeout(wait_ms)
                    child_html = page.content()
                    child_assessment = assess_html(child_html)
                    if child_response is None or child_response.status >= 400 or not child_assessment.passed:
                        raise CrawlRejected("child_quality_gate")
                    # Navigation links frequently differ only by a trailing
                    # slash.  After redirect they may resolve to the homepage;
                    # never overwrite its required index.html with a child
                    # filename in that case.
                    if page.url == final_url:
                        continue
                    page_sources[page.url] = (local_page_name(page.url), child_html)
                except Exception as exc:
                    child_failures.append({"url": child_url, "reason": str(exc)[:300]})
            page_map = {url: filename for url, (filename, _) in page_sources.items()}
            for source_url, (filename, raw_html) in page_sources.items():
                localizer.page_url = source_url
                rewritten = rewrite_local_page_links(localizer.rewrite_html(raw_html), source_url, page_map)
                (project_dir / filename).write_text(rewritten, encoding="utf-8")
            browser.close()
        # Static template/framework exports often carry a whole design system.
        # The tinycss2 DOM-aware pass drops selectors unused by the frozen
        # project before token accounting.  It never truncates a stylesheet;
        # final screenshot review remains required before release.
        normalized = normalize_existing_project(project_dir)
        if normalized["status"] != "normalized_candidate":
            raise CrawlRejected("post_crawl_normalize_failed:" + ";".join(normalized["assessment"]["reasons"]))
        css_purge = normalized["css_purge"]
        css_externalize = normalized["css_externalize"]
        token_usage = project_context_stats(
            project_dir, qwen_tokenizer, exclude_render_bundles=exclude_render_bundles)
        code_tokens = token_usage["prompt_tokens"]
        token_usage["code_token_limit"] = max_training_code_tokens
        if code_tokens > max_training_code_tokens:
            raise CrawlRejected(f"qwen_code_tokens_over_limit:{code_tokens}>{max_training_code_tokens}")
        validation = _validate_local(project_dir, browser_proxy, wait_ms)
        if not validation["ok"]:
            raise CrawlRejected("local_render_failed")
        if visual_review:
            final_screenshot_path = project_dir
            screenshot_verdict = capture_all_final_screenshots(
                project_dir, final_screenshot_path, browser_proxy, 60, .05, filename_prefix=project_dir.name)
            if screenshot_verdict.get("status") != "pass":
                raise CrawlRejected("final_screenshot_failed:" + screenshot_verdict.get("reason", "unknown"))
            page_reviews = []
            for page_result in screenshot_verdict["pages"]:
                visual = review_screenshot(Path(page_result["screenshot"]))
                page_reviews.append({"page": page_result["page"], **visual})
                if visual["status"] != "pass":
                    raise CrawlRejected("visual_review_" + visual["status"] + ":" + page_result["page"])
            visual_review_result = {"status": "pass", "pages": page_reviews}
        result.update({"status": "pass", "final_url": final_url, "language": assessment.language,
                       "quality_status": "pass", "resource_policy": "source_resources_absolute_remote__no_explicit_download",
                       "resources": localizer.log.__dict__, "validation": validation,
                       "token_usage": token_usage, "css_purge": css_purge, "css_externalize": css_externalize,
                       "exclude_render_bundles": exclude_render_bundles,
                       "visual_review": visual_review_result,
                       "pages": {"passed": len(page_sources), "child_failures": child_failures, "files": page_map}})
    except Exception as exc:
        # A final-render rejection is useful data, not an opaque failure.  Keep
        # the resource actions and browser diagnostics in the manifest so it is
        # possible to distinguish a real broken asset from an over-strict gate.
        result.update({"reason": str(exc), "quality_status": "reject"})
        if localizer is not None:
            result["resources"] = localizer.log.__dict__
        if validation is not None:
            result["validation"] = validation
        if token_usage is not None:
            result["token_usage"] = token_usage
        if css_purge is not None:
            result["css_purge"] = css_purge
        if visual_review_result is not None:
            result["visual_review"] = visual_review_result
        # Pipeline C outputs training answers, not a render archive.  A rejected
        # candidate must not leave a copied project or an attractive-but-invalid
        # screenshot that could be mistaken for accepted data later.
        shutil.rmtree(project_dir, ignore_errors=True)
        if final_screenshot_path is not None:
            shutil.rmtree(final_screenshot_path, ignore_errors=True)
    return result


def _crawl_entry(url: str, output_root: str, browser_proxy: str, wait_ms: int,
                 qwen_tokenizer: str, max_training_code_tokens: int, max_child_pages: int,
                 visual_review: bool, exclude_render_bundles: bool, queue: Any) -> None:
    """Process entrypoint so a stuck browser/resource request cannot block a run."""
    try:
        queue.put(crawl_one(url, Path(output_root), browser_proxy, wait_ms,
                            Path(qwen_tokenizer), max_training_code_tokens, max_child_pages,
                            visual_review, exclude_render_bundles))
    except Exception as exc:
        queue.put({"source_url": url, "status": "rejected", "quality_status": "reject", "reason": f"worker_exited:{exc}"})


def _run_url_with_timeout(url: str, output_root: Path, browser_proxy: str, wait_ms: int,
                          qwen_tokenizer: Path, max_training_code_tokens: int,
                          max_child_pages: int, site_timeout: int, visual_review: bool,
                          exclude_render_bundles: bool, run_sample_preflight: bool = True,
                          preflight_timeout: float = 12.0) -> dict[str, Any]:
    """Run one isolated browser worker; safe to call concurrently from threads."""
    original_url = url
    if run_sample_preflight:
        accepted, final_url, reason = sample_preflight(url, preflight_timeout)
        if not accepted:
            if reason.startswith("request_failed:"):
                return {"source_url": url, "final_url": final_url, "status": "preflight_network_error",
                        "quality_status": "retryable", "reason": "preflight_" + reason}
            return {"source_url": url, "final_url": final_url, "status": "preflight_rejected",
                    "quality_status": "reject", "reason": "preflight_" + reason}
        url = final_url
    context = mp.get_context("spawn")
    queue: Any = context.Queue(maxsize=1)
    worker = context.Process(
        target=_crawl_entry,
        args=(url, str(output_root), browser_proxy, wait_ms,
              str(qwen_tokenizer), max_training_code_tokens, max_child_pages,
              visual_review, exclude_render_bundles, queue),
    )
    worker.start(); worker.join(site_timeout)
    if worker.is_alive():
        worker.kill(); worker.join(timeout=5)
        return {"source_url": original_url, "status": "site_timeout", "quality_status": "retryable",
                "reason": f"site_timeout:{site_timeout}s"}
    try:
        row = queue.get(timeout=1)
        row["source_url"] = original_url
        return row
    except Exception:
        return {"source_url": original_url, "status": "worker_exited", "quality_status": "retryable",
                "reason": f"worker_exit_code:{worker.exitcode}"}


def completed_source_urls(manifest: Path) -> set[str]:
    """Read completed input URLs from an append-only manifest for safe resume."""
    completed: set[str] = set()
    if not manifest.is_file():
        return completed
    for line in manifest.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        source_url = str(row.get("source_url", "")).strip()
        if source_url and row.get("quality_status") != "retryable":
            completed.add(source_url)
    return completed


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline C: crawl, clean, locally render, and visually validate web projects.")
    parser.add_argument("--urls", type=Path, required=True, help="One URL per line")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--browser-proxy", default="")
    parser.add_argument("--wait-ms", type=int, default=3000)
    parser.add_argument("--qwen-tokenizer", type=Path, default=os.environ.get("QWEN_TOKENIZER_JSON", ""),
                        help="Qwen3 tokenizer.json; can also set QWEN_TOKENIZER_JSON.")
    parser.add_argument("--max-training-code-tokens", type=int, default=40_000,
                        help="Exact full retained HTML/CSS/JS/JSX/TS/TSX cap.")
    parser.add_argument("--max-child-pages", type=int, default=3,
                        help="Accepted same-site child pages per project; use 0 for single-page prechecks.")
    parser.add_argument("--site-timeout", type=int, default=60,
                        help="Hard per-site timeout in seconds; timeout rows are retryable.")
    parser.add_argument("--sample-preflight", action=argparse.BooleanOptionalAction, default=True,
                        help="Run the cheap HTTP gate per URL immediately before launching its browser.")
    parser.add_argument("--preflight-timeout", type=float, default=12.0,
                        help="HTTP timeout for the per-sample preflight gate.")
    parser.add_argument("--workers", type=int, default=1,
                        help="Concurrent isolated sites. Each worker owns one browser process.")
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True,
                        help="Skip source URLs already present in the output manifest.")
    parser.add_argument("--visual-review", action=argparse.BooleanOptionalAction, default=True,
                        help="Call the configured official Moonshot vision model on the final local-render screenshot after all other gates.")
    parser.add_argument("--exclude-render-bundles", action=argparse.BooleanOptionalAction, default=True,
                        help="Keep render bundles on disk but omit strongly-classified bundle bodies from the 40K training context.")
    args = parser.parse_args()
    if not args.qwen_tokenizer or not args.qwen_tokenizer.is_file():
        parser.error("--qwen-tokenizer must point to Qwen3 tokenizer.json (or set QWEN_TOKENIZER_JSON)")
    if not 1 <= args.max_training_code_tokens <= 131_072:
        parser.error("--max-training-code-tokens must be between 1 and 131072")
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    if args.max_child_pages < 0:
        parser.error("--max-child-pages must be non-negative")
    urls = [line.strip() for line in args.urls.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.limit: urls = urls[:args.limit]
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = args.output / "preprocess_manifest.jsonl"
    if args.resume:
        done = completed_source_urls(manifest)
        urls = [url for url in urls if url not in done]
        print(f"resume: skipped={len(done)} remaining={len(urls)}", flush=True)
    config = {"resource_policy": "source_resources_absolute_remote__no_explicit_download", "screenshots": bool(args.visual_review),
              "wait_ms": args.wait_ms, "site_timeout": args.site_timeout, "input_urls": str(args.urls),
              "qwen_tokenizer": str(args.qwen_tokenizer), "max_training_code_tokens": args.max_training_code_tokens,
              "reserved_task_tokens": None, "workers": args.workers,
              "max_child_pages": args.max_child_pages, "visual_review": args.visual_review,
              "sample_preflight": args.sample_preflight, "preflight_timeout": args.preflight_timeout,
              "resume": args.resume,
              "exclude_render_bundles": args.exclude_render_bundles,
              "visual_model": os.environ.get("VISION_MODEL", "moonshot-v1-128k-vision-preview") if args.visual_review else None}
    (args.output / "run_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    with manifest.open("a", encoding="utf-8") as handle, ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(_run_url_with_timeout, url, args.output, args.browser_proxy, args.wait_ms,
                        args.qwen_tokenizer, args.max_training_code_tokens, args.max_child_pages, args.site_timeout,
                        args.visual_review, args.exclude_render_bundles, args.sample_preflight,
                        args.preflight_timeout): (index, url)
            for index, url in enumerate(urls, 1)
        }
        completed = 0
        for future in as_completed(futures):
            index, url = futures[future]
            try:
                row = future.result()
            except Exception as exc:  # noqa: BLE001
                row = {"source_url": url, "status": "worker_exited", "quality_status": "retryable",
                       "reason": f"scheduler_error:{type(exc).__name__}:{exc}"}
            handle.write(json.dumps(row, ensure_ascii=False) + "\n"); handle.flush()
            completed += 1
            print(f"[{completed}/{len(urls)}; input={index}] {url}: {row['status']}", flush=True)


if __name__ == "__main__":
    main()
