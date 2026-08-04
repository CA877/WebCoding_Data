from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


LANG_RE = re.compile(r"""<html[^>]+lang\s*=\s*['"]?([A-Za-z][A-Za-z0-9_-]*)""", re.I)
REMOTE_RE = re.compile(r"""(?i)(https?:)?//[A-Za-z0-9][A-Za-z0-9.-]*(?::\d+)?[^\s"'<>)]*""")
SCRIPT_REMOTE_RE = re.compile(r"""(?is)<script\b[^>]*\bsrc\s*=\s*['"]((?:https?:)?//[^'"]+)""")
STYLE_REMOTE_RE = re.compile(r"""(?is)<link\b[^>]*(?:rel\s*=\s*['"][^'"]*stylesheet[^'"]*['"][^>]*href|href\s*=\s*['"]((?:https?:)?//[^'"]+)[^>]*rel\s*=\s*['"][^'"]*stylesheet)""")
STYLE_HREF_RE = re.compile(r"""(?is)<link\b[^>]*\bhref\s*=\s*['"]((?:https?:)?//[^'"]+)[^>]*>""")
IMG_REMOTE_RE = re.compile(r"""(?is)<(?:img|source)\b[^>]*(?:src|srcset)\s*=\s*['"]((?:https?:)?//[^'"]+)""")
IFRAME_REMOTE_RE = re.compile(r"""(?is)<iframe\b[^>]*\bsrc\s*=\s*['"]((?:https?:)?//[^'"]+)""")
MEDIA_REMOTE_RE = re.compile(r"""(?is)<(?:video|audio|source)\b[^>]*\bsrc\s*=\s*['"]((?:https?:)?//[^'"]+)""")
FONT_REMOTE_RE = re.compile(r"""(?i)(?:fonts\.googleapis|fonts\.gstatic|\.woff2?|\.ttf|\.otf|fontawesome)""")
BAD_PROTOCOL_RE = re.compile(r"""(?i)(href|src)\s*=\s*['"]\s*(javascript:|data:text/html|vbscript:)""")
SRCSET_BAD_RE = re.compile(r"""(?i)(src|srcset)\s*=\s*['"]\s*(?:null|#|/null|about:blank)\s*['"]""")
ON_EVENT_RE = re.compile(r"""(?i)\son(?:error|load|click|mouseover)\s*=""")
BODY_RE = re.compile(r"""(?is)<body\b[^>]*>(.*?)</body>""")
TAG_RE = re.compile(r"""(?s)<[^>]+>""")
WHITESPACE_RE = re.compile(r"\s+")

CHALLENGE_RE = re.compile(
    r"(?i)(just a moment|checking your browser|verify you are human|are you human|"
    r"access denied|attention required|cloudflare|captcha|security check|enable javascript)"
)
PARKED_RE = re.compile(
    r"(?i)(domain for sale|buy this domain|parked domain|sedo parking|"
    r"this domain is available|under construction|coming soon)"
)
ERROR_PAGE_RE = re.compile(r"(?i)(404 not found|page not found|403 forbidden|500 internal server error|nginx|apache2 ubuntu default page)")
RISK_RE = re.compile(
    r"(?i)(^|[^a-z])(adult|porn|porno|xxx|escort|escorts|dating|casino|gambling|"
    r"betting|call-girls|callgirls|webcam|nude|erotic|hookup|bdsm)([^a-z]|$)"
)

P0_ISSUES = {
    "adult_casino_dating_risky_text",
    "adult_casino_dating_risky_instance_id",
    "non_zh_en_html_lang_attr",
    "challenge_or_access_denied_text",
    "parked_or_placeholder_page_text",
    "error_or_default_server_page_text",
    "dangerous_href_or_src_protocol",
    "remote_script_src",
    "remote_stylesheet_href",
    "remote_iframe_src",
    "remote_media_src",
    "picsum_image_residual",
    "loremflickr_placeholder_image",
}

P1_ISSUES = {
    "bad_src_or_srcset_null_hash",
    "remote_image_src_or_srcset",
    "remote_or_web_font_reference",
    "low_visible_text_lt_80",
    "code_too_short_lt_500",
    "inline_event_handler_present",
}


@dataclass
class IssueSet:
    p0: list[str] = field(default_factory=list)
    p1: list[str] = field(default_factory=list)
    p2: list[str] = field(default_factory=list)

    @property
    def all(self) -> list[str]:
        return sorted(set(self.p0 + self.p1 + self.p2))

    @property
    def status(self) -> str:
        if self.p0:
            return "reject"
        if self.p1:
            return "review"
        return "accept"


def text_from_html(code: str) -> str:
    body_match = BODY_RE.search(code)
    body = body_match.group(1) if body_match else code
    body = re.sub(r"(?is)<script\b.*?</script>", " ", body)
    body = re.sub(r"(?is)<style\b.*?</style>", " ", body)
    return WHITESPACE_RE.sub(" ", TAG_RE.sub(" ", body)).strip()


def code_quality_issues(code: str) -> list[str]:
    issues: list[str] = []
    if not code:
        return ["empty_code"]
    scan = code[:200_000]
    lowered = scan.lower()
    if len(code) < 500:
        issues.append("code_too_short_lt_500")
    if "<html" not in lowered:
        issues.append("missing_html_tag")
    if "<body" not in lowered:
        issues.append("missing_body_tag")
    if SRCSET_BAD_RE.search(scan):
        issues.append("bad_src_or_srcset_null_hash")
    if BAD_PROTOCOL_RE.search(scan):
        issues.append("dangerous_href_or_src_protocol")
    if ON_EVENT_RE.search(scan):
        issues.append("inline_event_handler_present")
    text = text_from_html(scan)
    if len(text) < 80:
        issues.append("low_visible_text_lt_80")
    if CHALLENGE_RE.search(text[:5000]):
        issues.append("challenge_or_access_denied_text")
    if PARKED_RE.search(text[:5000]):
        issues.append("parked_or_placeholder_page_text")
    if ERROR_PAGE_RE.search(text[:3000]):
        issues.append("error_or_default_server_page_text")
    if RISK_RE.search(text[:10_000]):
        issues.append("adult_casino_dating_risky_text")
    if len(TAG_RE.findall(scan)) < 8:
        issues.append("very_few_html_tags")
    return issues


def remote_issues(code: str) -> list[str]:
    issues: list[str] = []
    if REMOTE_RE.search(code):
        issues.append("remote_url_present")
    if SCRIPT_REMOTE_RE.search(code):
        issues.append("remote_script_src")
    if STYLE_REMOTE_RE.search(code) or any(".css" in match.lower() for match in STYLE_HREF_RE.findall(code)):
        issues.append("remote_stylesheet_href")
    if IFRAME_REMOTE_RE.search(code):
        issues.append("remote_iframe_src")
    if MEDIA_REMOTE_RE.search(code):
        issues.append("remote_media_src")
    if IMG_REMOTE_RE.search(code):
        issues.append("remote_image_src_or_srcset")
    if FONT_REMOTE_RE.search(code):
        issues.append("remote_or_web_font_reference")
    if "loremflickr.com" in code.lower():
        issues.append("loremflickr_placeholder_image")
    if "picsum.photos" in code.lower():
        issues.append("picsum_image_residual")
    return issues


def lang_issues(code: str) -> list[str]:
    langs = {m.group(1).lower() for m in LANG_RE.finditer(code)}
    issues = ["html_lang_attr_present"] if langs else ["missing_html_lang_attr"]
    non_allowed = [x for x in langs if not (x == "en" or x.startswith("en-") or x == "zh" or x.startswith("zh-"))]
    if non_allowed:
        issues.append("non_zh_en_html_lang_attr")
    return issues


def classify_issues(issues: list[str]) -> IssueSet:
    out = IssueSet()
    for issue in sorted(set(issues)):
        if issue in P0_ISSUES or issue.startswith("patch_") or issue.endswith("_image_file_missing") or issue.endswith("_image_file_empty") or issue.endswith("_image_decode_failed"):
            out.p0.append(issue)
        elif issue in P1_ISSUES:
            out.p1.append(issue)
        else:
            out.p2.append(issue)
    return out


def audit_code_blob(code: str, *, sample_key: str = "") -> IssueSet:
    issues: list[str] = []
    if sample_key and RISK_RE.search(sample_key):
        issues.append("adult_casino_dating_risky_instance_id")
    if not code:
        issues.append("no_embedded_code_found")
    else:
        issues.extend(code_quality_issues(code))
        issues.extend(remote_issues(code))
        issues.extend(lang_issues(code))
    return classify_issues(issues)
