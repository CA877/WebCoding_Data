"""Pure policy helpers for Pipeline C.

No network requests are made here.  The crawler uses these helpers to make every
resource decision during the initial crawl rather than repairing output later.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import quote
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


PUBLIC_LIBRARY_HOSTS = {
    "cdn.jsdelivr.net", "unpkg.com", "cdnjs.cloudflare.com", "code.jquery.com",
    "ajax.googleapis.com", "stackpath.bootstrapcdn.com", "cdn.jsdelivr.net",
}
DEAD_PAGE_MARKERS = (
    "account has been suspended", "domain is for sale", "buy this domain",
    "website is under construction", "parked domain", "welcome to nginx",
    "apache2 default page", "expired domain", "site not found", "coming soon",
    "verify you are human", "checking your browser", "attention required",
    "just a moment", "enable javascript and cookies to continue", "access denied",
    "you have been blocked", "captcha", "robot challenge", "cf-challenge",
    "too many requests", "rate limit exceeded", "service has ended", "service ended",
    "this service is no longer available", "i am a human",
    "you are all set to go", "upload your website files", "hostinger",
    "there has been a critical error on this website", "troubleshooting wordpress",
    "parklogic.com", "this domain may be for sale",
    "private site", "log in to wordpress.com to request access",
    "http error 401", "you are not authorized to view this page",
    "需要验证阿里账号登录信息", "阿里账号登录信息", "oneagent-filter.alibaba-inc.com",
)
UNSAFE_PATTERNS = {
    "adult": ("porn", "xxx", "sex cam", "adult video", "escort service", "性爱", "色情", "裸体"),
    "gambling": ("online casino", "sports betting", "slot machine", "赌博", "博彩"),
    "drugs": ("buy cocaine", "buy heroin", "illegal drugs", "购买毒品"),
    "self_harm": ("suicide methods", "self harm methods", "自杀方法", "自残方法"),
    "hate": ("white supremacy", "ethnic cleansing", "种族灭绝"),
    "weapons": ("buy assault rifle", "ghost gun", "购买枪支"),
}


@dataclass(frozen=True)
class ResourceDecision:
    action: str
    absolute_url: str
    reason: str


@dataclass(frozen=True)
class HtmlAssessment:
    passed: bool
    language: str
    reasons: tuple[str, ...]
    text_chars: int


def _is_absolute(url: str) -> bool:
    return url.startswith(("http://", "https://", "//"))


def _origin_host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _same_site(host_a: str, host_b: str) -> bool:
    if host_a == host_b:
        return True
    a, b = host_a.split("."), host_b.split(".")
    return len(a) >= 2 and len(b) >= 2 and a[-2:] == b[-2:]


def classify_resource(raw_url: str, page_url: str, kind: str) -> ResourceDecision:
    """Classify a static dependency before any rewrite is made."""
    absolute = urljoin(page_url, raw_url)
    if kind == "image":
        return ResourceDecision("preserve_remote" if _is_absolute(raw_url) else "absolutize_source", absolute,
                                "absolute image" if _is_absolute(raw_url) else "site-relative image")
    resource_host = _origin_host(absolute)
    if not _is_absolute(raw_url):
        return ResourceDecision("absolutize_source", absolute, "relative source dependency")
    if resource_host in PUBLIC_LIBRARY_HOSTS:
        return ResourceDecision("preserve_third_party_library", absolute, "known public library CDN")
    return ResourceDecision("preserve_remote_code", absolute, "absolute code dependency")


def picsum_url(source_url: str, width: int, height: int) -> str:
    """Deterministic Picsum URL for a missing relative content image."""
    digest = hashlib.sha256(source_url.encode("utf-8")).hexdigest()
    width = min(max(int(width or 400), 50), 2000)
    height = min(max(int(height or 300), 50), 2000)
    return f"https://picsum.photos/seed/{digest[:20]}/{width}/{height}"


def ui_image_placeholder(source_url: str, width: int, height: int) -> str:
    """Create a local deterministic SVG for broken site-relative UI artwork.

    Logos, favicons, and privacy/icons should not turn into unrelated stock
    photography.  The SVG is embedded directly so no additional fetch is needed.
    """
    width, height = min(max(int(width or 120), 16), 512), min(max(int(height or 60), 16), 512)
    name = PurePosixPath(urlparse(source_url).path).stem or "UI"
    label = re.sub(r"[^A-Za-z0-9]", "", name).upper()[:2] or "UI"
    digest = hashlib.sha256(source_url.encode("utf-8")).hexdigest()
    color = f"#{digest[:6]}"
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{label}">'
        f'<rect width="100%" height="100%" rx="{max(4, min(width, height)//8)}" fill="{color}"/>'
        f'<text x="50%" y="54%" dominant-baseline="middle" text-anchor="middle" '
        f'font-family="Arial,sans-serif" font-size="{max(10, min(width, height)//2)}" fill="white">{label}</text></svg>'
    )
    return "data:image/svg+xml," + quote(svg, safe="")


def content_image_placeholder(source_url: str, width: int, height: int) -> str:
    """Local SVG fallback when a replacement photo service is unreachable.

    It preserves an image box's proportions and visual mass without adding a
    network dependency to the final training bundle.  This is used only for a
    previously missing site-relative image, never for real downloaded content.
    """
    width, height = min(max(int(width or 400), 50), 2000), min(max(int(height or 300), 50), 2000)
    digest = hashlib.sha256(source_url.encode("utf-8")).hexdigest()
    first, second = f"#{digest[:6]}", f"#{digest[6:12]}"
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="image placeholder">'
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{first}"/><stop offset="1" stop-color="{second}"/></linearGradient></defs>'
        f'<rect width="100%" height="100%" fill="url(#g)"/><circle cx="{width * .72:.0f}" cy="{height * .3:.0f}" r="{min(width, height) * .16:.0f}" fill="white" fill-opacity=".22"/>'
        f'<path d="M0 {height * .78:.0f} L{width * .32:.0f} {height * .48:.0f} L{width * .56:.0f} {height * .68:.0f} L{width} {height * .34:.0f} V{height} H0Z" fill="white" fill-opacity=".2"/>'
        '</svg>'
    )
    return "data:image/svg+xml," + quote(svg, safe="")


def _css_dimension_map(soup: BeautifulSoup) -> dict[str, tuple[int, int, float | None]]:
    mapping: dict[str, tuple[int, int, float | None]] = {}
    for style in soup.find_all("style"):
        text = style.string or ""
        for match in re.finditer(r"([.#][\w-]+)\s*\{([^}]*)\}", text):
            block = match.group(2)
            width = re.search(r"(?<![-\w])width\s*:\s*(\d+)px", block)
            height = re.search(r"(?<![-\w])height\s*:\s*(\d+)px", block)
            ratio = re.search(r"aspect-ratio\s*:\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", block)
            mapping[match.group(1)] = (
                int(width.group(1)) if width else 0,
                int(height.group(1)) if height else 0,
                float(ratio.group(1)) / float(ratio.group(2)) if ratio else None,
            )
    return mapping


def infer_image_dimensions(html_or_tag: str) -> tuple[int, int, str]:
    """Apply the prior ten-layer size inference without fetching the image itself."""
    soup = BeautifulSoup(html_or_tag, "html.parser")
    tag = soup.find(["img", "source", "input"])
    if tag is None:
        return 400, 300, "default"
    width = int(tag.get("width")) if str(tag.get("width", "")).isdigit() else 0
    height = int(tag.get("height")) if str(tag.get("height", "")).isdigit() else 0
    source = "html_attributes" if width or height else ""
    style = tag.get("style", "")
    for key, target in (("width", "width"), ("height", "height")):
        match = re.search(rf"{key}\s*:\s*(\d+)px", style)
        if match and not (width if target == "width" else height):
            if target == "width": width = int(match.group(1))
            else: height = int(match.group(1))
            source = "inline_style"
    if not width or not height:
        match = re.search(r"(\d{2,4})x(\d{2,4})", " ".join(tag.get("class") or []))
        if match:
            width, height, source = int(match.group(1)), int(match.group(2)), "class_hint"
    url = tag.get("src") or tag.get("data-src") or ""
    if not width or not height:
        wm, hm = re.search(r"[?&](?:width|w)=(\d+)", url), re.search(r"[?&](?:height|h)=(\d+)", url)
        fm = re.search(r"(\d{2,4})x(\d{2,4})(?:\.[a-zA-Z0-9]+)?$", url)
        if wm: width = int(wm.group(1))
        if hm: height = int(hm.group(1))
        if fm and (not width or not height): width, height = int(fm.group(1)), int(fm.group(2))
        if wm or hm or fm: source = "url_hint"
    if not width or not height:
        srcset = tag.get("srcset", "")
        widths = [int(value) for value in re.findall(r"\b(\d+)w\b", srcset)]
        if widths and not width:
            width, source = max(widths), "srcset"
    if not width or not height:
        for attr, axis in (("data-width", "width"), ("data-full-width", "width"), ("data-orig-width", "width"),
                           ("data-height", "height"), ("data-full-height", "height"), ("data-orig-height", "height")):
            value = tag.get(attr, "")
            if str(value).isdigit() and not (width if axis == "width" else height):
                if axis == "width": width = int(value)
                else: height = int(value)
                source = "data_attributes"
        original = re.match(r"(\d+)\s*[,x]\s*(\d+)", tag.get("data-orig-size", ""))
        if original:
            width, height, source = width or int(original.group(1)), height or int(original.group(2)), "data_attributes"
    ratio: float | None = None
    if not width or not height:
        mapping = _css_dimension_map(soup)
        for selector in [f"#{tag.get('id')}" if tag.get("id") else "", *[f".{c}" for c in tag.get("class") or []]]:
            if selector in mapping:
                cw, ch, ratio = mapping[selector]
                width, height = width or cw, height or ch
                source = "css_selector"
                break
    if not width or not height:
        parent_style = tag.parent.get("style", "") if tag.parent else ""
        wm, hm = re.search(r"width\s*:\s*(\d+)px", parent_style), re.search(r"height\s*:\s*(\d+)px", parent_style)
        if wm: width = width or int(wm.group(1))
        if hm: height = height or int(hm.group(1))
        if wm or hm: source = "parent_style"
    ar = re.search(r"aspect-ratio\s*:\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", style)
    ratio = ratio or (float(ar.group(1)) / float(ar.group(2)) if ar else None)
    if width and not height: height = int(width / ratio) if ratio else width * 2 // 3
    if height and not width: width = int(height * ratio) if ratio else height * 3 // 2
    return width or 400, height or 300, source or "default"


def assess_html(html: str) -> HtmlAssessment:
    soup = BeautifulSoup(html, "html.parser")
    declared_lang = str(soup.html.get("lang", "")).lower() if soup.html else ""
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    text = soup.get_text(" ", strip=True)
    lowered = text.lower() + " " + (soup.title.get_text(" ", strip=True).lower() if soup.title else "")
    reasons: list[str] = []
    if declared_lang and not (declared_lang.startswith("en") or declared_lang.startswith("zh")):
        reasons.append("unsupported_language")
    if any(marker in lowered for marker in DEAD_PAGE_MARKERS):
        reasons.append("unavailable_or_challenge_page")
    if re.search(r"\[(?:et_pb|vc_|fusion_|elementor_|shortcode)[\w_-]*\b", text, re.I):
        reasons.append("unrendered_cms_shortcode")
    # Long pages dominated by dozens of unrelated outbound links are typically
    # expired SEO/link-farm pages, not interfaces worth using as training gold.
    anchors = soup.find_all("a", href=True)
    anchor_text = sum(len(anchor.get_text(" ", strip=True)) for anchor in anchors)
    if len(anchors) >= 60 and anchor_text / max(len(text), 1) >= 0.45:
        reasons.append("link_farm_or_directory_page")
    for category, patterns in UNSAFE_PATTERNS.items():
        if any(pattern in lowered for pattern in patterns):
            reasons.append(f"unsafe_content:{category}")
            break
    chinese, latin = len(re.findall(r"[\u4e00-\u9fff]", text)), len(re.findall(r"[A-Za-z]", text))
    supported = chinese + latin
    language = "zh" if chinese > latin else "en"
    # This is only a cheap, high-confidence prefilter.  The final screenshot
    # VLM judges the visible language.  Do not reject a mostly-English page
    # merely because it contains symbols, names, code, or short mixed labels.
    # Reject only substantial text that is overwhelmingly neither Chinese nor
    # Latin, plus explicit non-zh/non-en ``lang`` declarations upstream.
    if len(text) >= 80 and (supported < 20 or supported / max(len(re.sub(r"\s", "", text)), 1) < 0.20):
        language = "other"
        reasons.append("unsupported_language")
    return HtmlAssessment(not reasons, language, tuple(reasons), len(text))
