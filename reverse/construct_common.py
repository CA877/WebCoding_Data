from __future__ import annotations

import json
import functools
import hashlib
import http.server
from html import unescape as html_unescape
import os
import random
import re
import shutil
import socketserver
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlparse

from .task_specs import REPAIR_DEFECT_TAXONOMY, repair_defect_metadata


REPO_ROOT = Path(__file__).resolve().parents[1]

CODE_EXTS = {".html", ".htm", ".css", ".js", ".jsx", ".ts", ".tsx", ".json", ".svg"}
TRAIN_CODE_EXTS = {".html", ".htm", ".css", ".js", ".jsx", ".ts", ".tsx"}
JS_SUFFIXES = {".js", ".jsx", ".ts", ".tsx"}
PROVENANCE_FILES = {"metadata.json", "original_webcode2m_screenshot.png"}
REMOTE_URL_RE = re.compile(r"https?://[^\s\"'<>)]*", re.I)
SVG_NAMESPACE_URLS = {
    "http://www.w3.org/2000/svg",
    "http://www.w3.org/1999/xlink",
    "http://purl.org/dc/elements/1.1/",
    "http://creativecommons.org/ns#",
    "http://www.inkscape.org/namespaces/inkscape",
    "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd",
    "http://www.serif.com/",
}
VIEWPORTS = [
    ("desktop", 1920, 1080),
    ("tablet", 768, 1024),
    ("mobile", 375, 812),
]
CODE_PRD_PROMPT = """You are a product manager writing a web design document for a front-end developer. You will be shown the source code of a web project, but your output must read as if you designed this product from scratch — a pure design spec, not a code analysis.

The developer who reads your document has never seen the original code and will build the entire project from your spec alone.

Output exactly these three sections:

# Web page content
Describe WHAT the page contains — its functional areas, components, and what they do.

Requirements:
- Organize into numbered functional areas with descriptive names (e.g., "### 1. Global Navigation & Layout Structure", "### 2. Landing Page (Public View)", "### 3. User Dashboard", "### 4. Messaging & Collaboration"). Use names that describe PURPOSE, not position.
- For each area, list components using bold labels and bullet points:
  *   **Component Name:** What it is, what it shows, what it does.
- Name components by function: "Job Creation Wizard", "Priority Inbox", "Transaction History Table", "Feature Highlights Grid".
- For repeated components (cards, list items), describe the template: what fields it contains (e.g., "Freelancer Name, Bid Amount, Cover Letter snippet, Match Score").
- Describe the page's domain and purpose (e.g., "a freelancing platform dashboard", "an RSS feed reader").
- Include representative text and labels to clarify intent (e.g., tagline "Find the perfect match", menu items "Find Work, My Jobs, Reports", category names "Development, Design, Writing").
- Briefly note mobile adaptation where relevant (e.g., "On mobile, the header simplifies to a logo and hamburger menu").
- If there are multiple pages, describe the shared shell once, then each page's unique content.
- Do NOT describe spatial layout geometry (no "left column 60%, right column 40%", no pixel dimensions like "528×317", no "two-column row" or "three-column grid"). Describe WHAT each component is, not WHERE it sits. The developer decides layout.

# Web page interaction
Describe HOW users interact with the page — logic, rules, and step-by-step user flows.

Requirements:
- Start with "### Interaction Logic & Rules": business rules, state management, role-based access, data flow, filtering/sorting logic, form validation rules.
- Then "### Interaction Action Sequences": named scenarios with numbered steps using Trigger → Action → System Response format. Example:
  **Sequence A: The Hiring Flow (Client Perspective)**
  1. **Trigger:** User clicks "Post a Job."
  2. **Action:** User fills out the multi-step wizard and clicks "Publish."
  3. **System Response:** Job appears in the public feed; user receives notification "Your job is live."
- Write from the USER's perspective — what they see and do, what the system does in response.
- Do NOT describe implementation details: no CSS transitions, no animation durations in milliseconds, no easing functions, no HTTP methods, no URL patterns, no event handler names.
- Keep animation descriptions at a product level: "dropdown appears smoothly", "slider auto-advances", "scroll-to-top button fades in after scrolling down".

# Web page visual
Describe the visual DESIGN LANGUAGE — aesthetic direction, color palette, typography, and component styling.

Requirements:
- Start with "### Color Palette & Theme" including a **Core Concept** line naming the aesthetic (e.g., 'A "Royal Digital" aesthetic that feels creative yet professional', 'A "Clean Corporate Blue" look with generous white space').
- Define colors with approximate hex values, descriptive names, and their roles:
  *   **Main Background:** **Pale Orchid** (Hex approx: `#E6D8E6`). A soft lavender shade for eye comfort.
  *   **Primary Containers:** **Deep Purple** (`#4A148C`). Content cards and panels.
  *   **Primary Action Buttons:** **Bright Magenta** (`#D500F9`). High contrast against purple.
- "### Typography & Iconography": SUGGEST font styles with "e.g." — do not dictate exact font-family names:
  *   **Font:** A modern, rounded Sans-Serif (e.g., *Nunito* or *Quicksand*).
  *   **Headings:** Bold, large. **Body:** Comfortable line height for readability.
  *   **Icons:** Describe style (line-art, filled, outline) and states (active vs inactive).
- "### Component Styling": high-level patterns for buttons (primary vs ghost/secondary), input fields, feedback indicators (success color, error color), card styling.
- "### Visual Hierarchy Example": a narrative paragraph painting the assembled picture:
  *   *Imagine the Dashboard:* A soft Orchid background. In the center, a large rounded card (Deep Purple). Inside, "Active Jobs" in bold White text. Job rows separated by thin lavender lines. The "View" button is a popping Bright Magenta.
- Do NOT list pixel values for spacing, font sizes, margins, padding, or border-radius. Describe them qualitatively: "generous padding", "compact layout", "large bold headings", "small muted metadata text", "rounded corners".

Hard constraints (apply to ALL sections):
- You are a product manager, NOT a developer reading code. Never let the reader sense that you analyzed source code.
- FORBIDDEN WORDS AND PATTERNS — if you catch yourself writing any of these, rewrite the sentence:
  * Framework/library/CMS/plugin names: "WordPress", "Divi", "Bootstrap", "React", "jQuery", "WooCommerce", "Formidable Forms", "Cloudflare Turnstile", "Adaxes", etc.
  * Code artifacts: CSS selectors, class names, HTML tags ("<hr>", "<h2>"), JS variables, URL paths ("/search?s="), HTTP methods ("POST request", "GET request"), file names.
  * CSS/code values: "rgba(...)", "border-width: 0", "opacity: 0.7", "z-index", "float left", "inline label style", "object-fit: cover".
  * Any numeric measurement with units: "52px", "14px", "2em", "4px", "0.62", "1.7–2.0", "5 rows", "980px". Use qualitative descriptions only: "very large", "comfortable", "rounded", "subtle".
  * Implementation jargon: "regex pattern", "AJAX", "honeypot field", "anti-spam field", "hidden field", "pattern validation", "URL change", "POST request", "viewport".
  * Spatial layout terms: "left column", "right column", "three-column grid", "two-column layout", "three-column arrangement", "stacked vertically". Describe components by what they ARE.
  * Responsive breakpoint details: do not write "viewports narrower than...", "below 980px", or "defined breakpoint". Mobile adaptation is a brief note in the content section ONLY (e.g., "On mobile, the menu collapses to a hamburger icon").
- Be concrete and specific — every statement should describe something buildable. No vague filler.
- Do not invent features not present in the original design.
"""


def maybe_load_env() -> None:
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    for candidate in (REPO_ROOT / ".env",):
        if candidate.exists():
            load_dotenv(candidate)


def safe_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def iter_jsonl_records(path: Path, *, ignore_invalid: bool = False):
    """Yield JSON objects one physical file line at a time.

    Web source can contain Unicode line/paragraph separators.  ``splitlines``
    treats those characters as record boundaries even though JSONL only uses
    the physical newline written by :func:`append_jsonl`.
    """
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                if ignore_invalid:
                    continue
                raise ValueError(f"invalid JSONL record at {path}:{line_number}") from None


# ============ Patch 后处理 ============

def _snap_to_source(llm_text: str, source_code: str) -> str:
    """将 LLM 输出的代码片段对齐到真实源码（修复空白不匹配）。

    LLM 经常给代码加漂亮缩进，但实际 HTML 可能已被压平。
    用去空白签名在源码中定位，然后提取原始文本。
    """
    import re

    if not llm_text or not source_code:
        return llm_text
    # 如果已经是精确匹配，直接返回
    if llm_text in source_code:
        return llm_text

    # 用去空白的签名定位
    def _collapse(s: str) -> str:
        return re.sub(r'\s+', '', s)

    sig = _collapse(llm_text)
    if not sig:
        return llm_text

    src_collapsed = _collapse(source_code)
    pos = src_collapsed.find(sig)
    if pos == -1:
        # 签名找不到，尝试用前半段
        half = sig[:len(sig) // 2]
        if len(half) < 20:
            return llm_text  # 太短，放弃
        pos = src_collapsed.find(half)
        if pos == -1:
            return llm_text  # 完全找不到，返回原文

    # 将 collapsed 位置映射回原始源码位置
    # pos = collapsed 中的字符位置 → 对应源码中第 pos 个非空白字符
    non_ws_count = 0
    start_idx = None
    end_idx = None
    for i, ch in enumerate(source_code):
        if not ch.isspace() and ch not in ('\n', '\r', '\t', ' '):
            # 更准确的判断: 和 re.sub(r'\s+', '', ...) 一致
            pass
        if re.match(r'\S', ch):
            if non_ws_count == pos and start_idx is None:
                start_idx = i
            non_ws_count += 1
            if non_ws_count == pos + len(sig):
                end_idx = i + 1
                break

    if start_idx is not None and end_idx is not None:
        return source_code[start_idx:end_idx]
    return llm_text


# ============ info.json → 统一 JSONL 训练格式转换 ============

def _apply_patches_reverse(dst_code: list[dict], patches: list[dict]) -> list[dict]:
    """对 dst_code 反向应用 patch，得到有缺陷的 src_code。

    repair 的 label_modified_files: search=缺陷代码, replace=干净代码
    反向应用: 在 dst_code(干净) 中把 replace 替换为 search → 得到缺陷代码
    """
    code_map = {item["path"]: item["code"] for item in dst_code}
    for patch in patches:
        path = patch["path"]
        if path in code_map:
            code_map[path] = code_map[path].replace(patch["replace"], patch["search"])
    return [{"path": item["path"], "code": code_map.get(item["path"], item["code"])}
            for item in dst_code]


def info_to_training_record(info: dict) -> dict | None:
    """将 info.json 字典转换为统一的 instruction+response 训练记录。

    返回 None 表示未知 task 类型。
    """
    task = info.get("task", "")
    base = {
        "instance_id": info["instance_id"],
        "task_type": info.get("task_type", []),
        "page_type": info.get("page_type", "sp"),
        "file_manifest": info.get("file_manifest", []),
        "resources": info.get("resources", []),
    }

    if task == "text-generation":
        base["task"] = "text-generation"
        base["instruction"] = info["instruction"]
        base["response"] = info["dst_code"]
    elif task == "repair":
        base["task"] = "text-repair"
        patches = info.get("label_modified_files", [])
        dst_code = info.get("dst_code", [])
        base["instruction"] = _apply_patches_reverse(dst_code, patches)
        base["response"] = patches
    elif task == "edit":
        base["task"] = "text-editing"
        patches = info.get("label_modified_files", [])
        dst_code = info.get("dst_code", [])
        base["instruction"] = {
            "src_code": _apply_patches_reverse(dst_code, patches),  # code without features
            "description": info.get("description", []),
        }
        base["response"] = patches  # search=without feature, replace=with feature
    else:
        return None

    return base


def iter_project_dirs(root: Path, limit: int = 0, offset: int = 0) -> list[Path]:
    projects = sorted(p for p in root.iterdir() if p.is_dir())
    if offset > 0:
        projects = projects[offset:]
    return projects[:limit] if limit > 0 else projects


def iter_project_list(project_list: Path, limit: int = 0, offset: int = 0) -> list[Path]:
    """Read an auditable, newline-delimited project list for batch construction."""
    projects: list[Path] = []
    seen: set[Path] = set()
    for raw in project_list.read_text(encoding="utf-8").splitlines():
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        path = Path(value).resolve()
        if not path.is_dir():
            raise FileNotFoundError(f"project from list does not exist: {path}")
        if path not in seen:
            projects.append(path); seen.add(path)
    projects = projects[offset:]
    return projects[:limit] if limit > 0 else projects


def find_html_pages(project_dir: Path) -> list[Path]:
    pages = []
    for page in sorted(project_dir.rglob("*.html")):
        rel_parts = page.relative_to(project_dir).parts
        if any(part.lower() in {"resources", "assets", "static", "node_modules"} for part in rel_parts[:-1]):
            continue
        pages.append(page)
    index = project_dir / "index.html"
    if index.exists() and index not in pages:
        pages.insert(0, index)
    return pages


_HASH_ROUTE_PATTERNS = (
    # User-reachable links are the strongest evidence and their exact slash
    # spelling must be preserved (``#home`` is not always ``#/home``).
    (40, re.compile(r"\bhref\s*=\s*['\"]#(?P<route>[^'\"\s<>]+)['\"]", re.I)),
    (35, re.compile(
        r"\b(?:window\.)?location\.hash\s*=\s*['\"`]#?(?P<route>[^'\"`\s]+)['\"`]",
        re.I,
    )),
    (30, re.compile(r"\bdata-route\s*=\s*['\"](?P<route>[^'\"\s<>]+)['\"]", re.I)),
    # Literal hash-router maps are useful fallback evidence, but must not
    # override an actual link or assignment discovered above.
    (20, re.compile(r"['\"](?P<route>/[^'\"\s]+|/)['\"]\s*:", re.I)),
)
_CLIENT_ROUTER_RE = re.compile(
    r"\bhashchange\b|\blocation\.hash\b|\bHashRouter\b|\bcreateHashRouter\b", re.I
)
_ANCHOR_TAG_RE = re.compile(r"<a\b(?P<attrs>[^>]*)>", re.I)
_HREF_HASH_ATTR_RE = re.compile(r"\bhref\s*=\s*['\"]#(?P<route>[^'\"\s<>]+)['\"]", re.I)
_CLASS_ATTR_RE = re.compile(r"\bclass\s*=\s*['\"](?P<value>[^'\"]*)['\"]", re.I)


def _generation_page_mode(project_dir: Path) -> str:
    marker = project_dir / ".generation.json"
    if not marker.is_file():
        return ""
    try:
        metadata = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    contract = metadata.get("contract") if isinstance(metadata.get("contract"), dict) else {}
    return str(contract.get("page_mode") or metadata.get("page_mode") or "")


_LITERAL_HASH_ROUTE_RE = re.compile(
    r"^/?[A-Za-z][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_.-]+)*$"
)


def _literal_hash_route(value: str) -> str | None:
    """Normalize a concrete hash route and reject parameter templates.

    ``:id``, ``${item.id}``, wildcards, query strings and fragments produced
    at runtime are not directly browser-reachable canonical states.  They may
    be exercised later by an interaction contract with a concrete value, but
    must never be expanded into a canonical route by static regex matching.
    """
    route = value.strip()
    if route.startswith("#"):
        route = route[1:]
    if route == "/":
        return "/"
    if not route or any(marker in route for marker in ("$", "{", "}", ":", "*", "?", "#")):
        return None
    if not _LITERAL_HASH_ROUTE_RE.fullmatch(route):
        return None
    return "/" + route.strip("/") if route.startswith("/") else route.strip("/")


def _skip_link_route_keys(code: str) -> set[str]:
    """Return accessibility skip-target hashes that are not application pages."""
    result: set[str] = set()
    for match in _ANCHOR_TAG_RE.finditer(code):
        attrs = match.group("attrs")
        class_match = _CLASS_ATTR_RE.search(attrs)
        classes = set(class_match.group("value").lower().split()) if class_match else set()
        if not ({"skip-link", "skip-to-content", "skip-navigation"} & classes):
            continue
        href_match = _HREF_HASH_ATTR_RE.search(attrs)
        if not href_match:
            continue
        route = _literal_hash_route(href_match.group("route"))
        if route is not None:
            result.add(route.strip("/"))
    return result


def discover_browser_routes(project_dir: Path) -> list[str]:
    """Return distinct browser-reachable documents or hash routes.

    A one-document application counts as multi-page only when the Generate
    contract declares it multi-page and its source exposes at least two literal
    hash routes plus client-router behavior. Ordinary tabs/hidden sections are
    therefore not upgraded to multi-page by this structural helper.
    """
    documents = [page.relative_to(project_dir).as_posix() for page in find_html_pages(project_dir)]
    if len(documents) != 1 or _generation_page_mode(project_dir) != "multi_page":
        return documents
    code = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(project_dir.rglob("*"))
        if path.is_file()
        and path.suffix.lower() in TRAIN_CODE_EXTS
        and not any(part.lower() in {"resources", "assets", "node_modules"} for part in path.relative_to(project_dir).parts[:-1])
    )
    if not _CLIENT_ROUTER_RE.search(code):
        return documents
    # Collapse ``foo`` and ``/foo`` to one semantic route while retaining the
    # spelling from the strongest/first source occurrence.  This prevents the
    # same state from being captured twice under slash variants.
    hashes: dict[str, tuple[int, int, str]] = {}
    route_map_hashes: dict[str, tuple[int, int, str]] = {}
    occurrence = 0
    for confidence, pattern in _HASH_ROUTE_PATTERNS:
        for match in pattern.finditer(code):
            occurrence += 1
            route = _literal_hash_route(match.group("route"))
            if route is None:
                continue
            semantic_key = route.strip("/")
            previous = hashes.get(semantic_key)
            candidate = (confidence, -occurrence, route)
            if previous is None or candidate[:2] > previous[:2]:
                hashes[semantic_key] = candidate
            if confidence == 20:
                route_map_hashes[semantic_key] = candidate
    # A concrete dispatch table is stronger reachability evidence than an
    # arbitrary ``href="#section"`` in the same document.  Once at least two
    # literal map entries exist, use that table as the route universe so skip
    # links and section anchors cannot become fake pages.
    if len(route_map_hashes) >= 2:
        hashes = route_map_hashes
    else:
        for skip_key in _skip_link_route_keys(code):
            hashes.pop(skip_key, None)
    if len(hashes) < 2:
        return documents
    host = documents[0]
    return [f"{host}#{item[2]}" for item in sorted(hashes.values(), key=lambda item: item[2])]


def infer_page_bucket(project_dir: Path) -> str:
    """Classify physical pages; hash-route SPAs remain single-page projects."""
    return "mp" if len(find_html_pages(project_dir)) >= 2 else "sp"


def _code_priority(path: str) -> int:
    """文件排序优先级：HTML 最前 → CSS 其次 → JS/TS 最后。"""
    ext = Path(path).suffix.lower()
    if ext in {".html", ".htm"}:
        return 0
    if ext == ".css":
        return 1
    return 2


def read_code_bundle(project_dir: Path, code_only: bool = False) -> list[dict[str, str]]:
    """Read code files from project. code_only=True excludes .svg/.json (for training data)."""
    exts = TRAIN_CODE_EXTS if code_only else CODE_EXTS
    code = []
    for path in sorted(project_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in exts:
            continue
        rel = path.relative_to(project_dir).as_posix()
        if rel in PROVENANCE_FILES:
            continue
        code.append({"path": rel, "code": sanitize_render_text(path.read_text("utf-8", errors="ignore"))})
    return code


def collect_resources(project_dir: Path) -> list[dict[str, Any]]:
    resources = []
    for path in sorted(project_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(project_dir).as_posix()
        if rel in PROVENANCE_FILES:
            continue
        if path.suffix.lower() in CODE_EXTS:
            continue
        kind = "image"
        if path.suffix.lower() in {".woff", ".woff2", ".ttf", ".otf", ".eot"}:
            kind = "font"
        elif path.suffix.lower() in {".mp4", ".webm"}:
            kind = "video"
        resources.append({"type": kind, "path": rel, "description": "", "size_bytes": path.stat().st_size})
    return resources


def build_file_manifest(project_dir: Path) -> list[dict[str, Any]]:
    """List all files with type classification and size (for training data context)."""
    manifest = []
    for path in sorted(project_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name in PROVENANCE_FILES:
            continue
        rel = path.relative_to(project_dir).as_posix()
        suffix = path.suffix.lower()
        if suffix in TRAIN_CODE_EXTS:
            ftype = "code"
        elif suffix in {".svg", ".json"}:
            ftype = "asset"
        elif suffix in {".woff", ".woff2", ".ttf", ".otf", ".eot"}:
            ftype = "font"
        elif suffix in {".mp4", ".webm"}:
            ftype = "video"
        else:
            ftype = "image"
        manifest.append({"path": rel, "type": ftype, "size_bytes": path.stat().st_size})
    return manifest


def copy_project(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*PROVENANCE_FILES))
    sanitize_project_files(dst)


def sanitize_render_text(text: str) -> str:
    def replace_url(match: re.Match[str]) -> str:
        url = match.group(0)
        if url in SVG_NAMESPACE_URLS:
            return url
        # Keep picsum.photos fallback URLs (injected by clean step)
        if "picsum.photos" in url:
            return url
        return "#"

    def replace_css_url(match: re.Match[str]) -> str:
        if "picsum.photos" in match.group(0):
            return match.group(0)
        return 'url("")'

    text = re.sub(r"url\(\s*(['\"]?)https?://[^'\"\)]*\1\s*\)", replace_css_url, text, flags=re.I)
    text = re.sub(r"@import\s+(['\"])https?://[^'\"]*\1\s*;?", "", text, flags=re.I)
    return REMOTE_URL_RE.sub(replace_url, text)


def sanitize_project_files(project_dir: Path) -> None:
    for path in project_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in (CODE_EXTS - {".json"}):
            continue
        text = path.read_text("utf-8", errors="ignore")
        sanitized = sanitize_render_text(text)
        if sanitized != text:
            path.write_text(sanitized, encoding="utf-8")


def write_code_bundle(code_bundle: list[dict[str, str]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for item in code_bundle:
        target = out_dir / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item["code"], encoding="utf-8")


def write_code_bundle_from_source(source_project: Path, code_bundle: list[dict[str, str]], out_dir: Path) -> None:
    copy_project(source_project, out_dir)
    for item in code_bundle:
        target = out_dir / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item["code"], encoding="utf-8")


def serialize_patch_xml(modified_files: list[dict[str, str]]) -> str:
    blocks = []
    for patch in modified_files:
        blocks.append(
            "<search>\n"
            f"{patch['search']}\n"
            "</search>\n"
            "<replace>\n"
            f"{patch['replace']}\n"
            "</replace>"
        )
    return "\n".join(blocks)


def choose_task_types(
    all_task_types: list[str],
    count: int | tuple[int, int],
    seed: int | None,
    instance_id: str,
    allow_repeat: bool = False,
) -> list[str]:
    """Select task types for an instance.

    count: either a fixed int or (min, max) tuple for random range.
    allow_repeat: if True, use choices (with replacement) instead of sample.
        Needed for repair tasks where type pool (11) < max count (12).
    """
    rng = random.Random(f"{seed}:{instance_id}" if seed is not None else instance_id)
    if isinstance(count, tuple):
        min_c, max_c = count
        if not allow_repeat:
            max_c = min(max_c, len(all_task_types))
        n = rng.randint(min_c, max_c)
    else:
        n = count
    if allow_repeat:
        return rng.choices(all_task_types, k=n)
    if n > len(all_task_types):
        raise ValueError(f"Requested {n} task types, only {len(all_task_types)} available")
    return rng.sample(all_task_types, n)


def choose_task_count(min_tasks: int, max_tasks: int, seed: int, instance_id: str) -> int:
    """Deterministically sample a task count inside the requested range."""
    if min_tasks < 1 or max_tasks < min_tasks:
        raise ValueError("task count range must satisfy 1 <= min <= max")
    rng = random.Random(f"task-count:{seed}:{instance_id}")
    return rng.randint(min_tasks, max_tasks)


def balanced_task_count(ordinal: int, seed: int, min_tasks: int = 1, max_tasks: int = 7) -> int:
    """Assign counts evenly across a stable ordered batch.

    Every complete block of ``max_tasks-min_tasks+1`` samples contains each
    task count exactly once.  Concurrency and retries therefore cannot skew
    the requested 1--7 distribution.
    """
    if ordinal < 0 or min_tasks < 1 or max_tasks < min_tasks:
        raise ValueError("invalid balanced task-count arguments")
    width = max_tasks - min_tasks + 1
    return min_tasks + ((ordinal + seed) % width)


def balanced_cycle_item(
    items: tuple[str, ...] | list[str], ordinal: int, offset: int, seed: int
) -> str:
    """Select a stable cycle item across separately launched offset shards."""
    if not items:
        raise ValueError("balanced cycle requires at least one item")
    return items[(ordinal + offset + seed) % len(items)]


def training_source_manifest(project: Path) -> dict[str, Any]:
    """No retained training code is omitted under the full-code contract."""
    return {"javascript": [], "stylesheet_bundles": []}


def existing_final_screenshots(project: Path) -> list[dict[str, str]]:
    """Return reviewed Pipeline-C screenshots already stored with a project."""
    files = sorted(project.glob(f"{project.name}*.png"))
    if not files:
        raise FileNotFoundError(f"missing project-root screenshots for {project}")
    return [{"path": str(path.resolve()), "kind": "clean_final_render"} for path in files]


def load_canonical_screenshots(cache_root: Path, instance_id: str) -> list[dict[str, str]]:
    """Load the immutable Generate/Edit/Repair clean screenshot pack."""
    instance_dir = cache_root / instance_id
    manifest = instance_dir / "screens.json"
    if not manifest.is_file():
        raise FileNotFoundError(f"missing canonical screenshot manifest: {manifest}")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    screens = payload.get("screens") if isinstance(payload, dict) else None
    if not isinstance(screens, list) or not screens:
        raise ValueError(f"invalid canonical screenshot manifest: {manifest}")
    result = []
    for item in screens:
        if not isinstance(item, dict) or not str(item.get("path", "")).strip():
            raise ValueError(f"invalid canonical screenshot entry: {manifest}")
        path = Path(str(item["path"]))
        if not path.is_absolute():
            path = cache_root / path
        if not path.is_file():
            raise FileNotFoundError(f"canonical screenshot is missing: {path}")
        result.append({**item, "path": str(path.resolve()), "kind": "shared_canonical_clean"})
    return result


def safe_name(value: str) -> str:
    value = str(value).replace(os.sep, "__")
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_") or "page"


def local_route_url(port: int, route: str) -> str:
    """Quote the served file path without percent-encoding its URL hash."""
    path, separator, fragment = route.partition("#")
    url = f"http://127.0.0.1:{port}/{quote(path)}"
    return f"{url}#{fragment}" if separator else url


def route_url_targets_page(url: str, target_page: str) -> bool:
    """Return whether a resolved browser URL addresses the requested HTML page."""
    target_path = unquote(target_page.split("#", 1)[0].split("?", 1)[0].lstrip("/"))
    return unquote(urlparse(url).path.lstrip("/")) == target_path


def _navigate_through_visible_entry(
    page: Any,
    port: int,
    target_page: str,
    project_pages: list[str],
    navigation_timeout_ms: int,
) -> dict[str, str] | None:
    """Reach a page through a visible project link so query/storage state is retained."""
    entry_pages = sorted(
        (item for item in project_pages if item != target_page),
        key=lambda item: (Path(item.split("#", 1)[0]).name.lower() != "index.html", item),
    )
    discovery_settle_ms = int(os.environ.get("SCREENSHOT_ENTRY_DISCOVERY_SETTLE_MS", "1000"))
    target_literal = target_page.split("#", 1)[0].split("?", 1)[0]
    for entry_page in entry_pages:
        response = page.goto(
            local_route_url(port, entry_page),
            wait_until="domcontentloaded",
            timeout=navigation_timeout_ms,
        )
        if response is None or response.status >= 400:
            continue
        page.wait_for_timeout(discovery_settle_ms)
        candidates = page.locator("a[href], [onclick]")
        for index in range(min(candidates.count(), 300)):
            candidate = candidates.nth(index)
            href = candidate.get_attribute("href") or ""
            onclick = candidate.get_attribute("onclick") or ""
            resolved_href = urljoin(page.url, href) if href else ""
            if not (
                (resolved_href and route_url_targets_page(resolved_href, target_page))
                or target_literal in onclick
            ):
                continue
            # Reload the entry before every trial so a rejected candidate cannot
            # leak UI or storage mutations into the next candidate.
            page.goto(
                local_route_url(port, entry_page),
                wait_until="domcontentloaded",
                timeout=navigation_timeout_ms,
            )
            page.wait_for_timeout(discovery_settle_ms)
            fresh = page.locator("a[href], [onclick]").nth(index)
            text = " ".join(fresh.inner_text(timeout=2000).split())[:240]
            try:
                # DOM activation follows the real link/handler but is not blocked
                # by hover overlays that make an otherwise valid entry hard to
                # hit with pointer coordinates in a headless capture.
                fresh.evaluate("element => element.click()")
                page.wait_for_load_state("domcontentloaded", timeout=2000)
            except Exception:
                # A same-document handler may complete correctly without a load
                # event; final URL and visible state below remain authoritative.
                pass
            page.wait_for_timeout(discovery_settle_ms)
            if not route_url_targets_page(page.url, target_page):
                continue
            visible_text = page.locator("body").inner_text(timeout=5000)
            if detect_initial_route_texts(visible_text)["hard"]:
                continue
            if detect_unsettled_loading_texts(visible_text):
                continue
            return {
                "capture_mode": "visible_entry",
                "capture_entry_page": entry_page,
                "capture_entry_href": href,
                "capture_entry_text": text,
            }
    return None


def detect_initial_route_texts(visible_text: str) -> dict[str, list[str]]:
    """Classify direct-route empty states without rejecting ordinary first-use pages."""
    lines = [
        line.strip() for line in visible_text.splitlines()
        if line.strip() and len(line.strip()) <= 160
    ]
    empty = [
        line for line in lines
        if re.search(
            r"\b(?:not found|no .+ (?:yet|selected|available)|nothing here|"
            r"no .+ (?:id|identifier) (?:provided|specified|supplied))\b",
            line, re.IGNORECASE,
        )
    ]
    hard = [
        line for line in lines
        if re.search(
            r"(?:^|\b)(?:not found|(?:item|story|lesson|project|page|route|record|resource)"
            r"(?:\s+\w+){0,4}\s+not found|"
            r"no\s+[a-z][a-z0-9 _-]{0,60}\s+(?:id|identifier)\s+"
            r"(?:provided|specified|supplied)|"
            r"missing\s+(?:required\s+)?[a-z][a-z0-9 _-]{0,60}\s+"
            r"(?:id|identifier|parameter))(?:\b|$)",
            line, re.IGNORECASE,
        )
    ]
    return {"empty": empty, "hard": hard}


def detect_unsettled_loading_texts(visible_text: str) -> list[str]:
    """Find loading status copy without treating place names as application state."""
    result = []
    for raw_line in visible_text.splitlines():
        line = raw_line.strip()
        if len(line) > 160 or not re.match(
            r"^(?:loading|fetching|please wait)(?:\b|[.]{2,})",
            line,
            re.IGNORECASE,
        ):
            continue
        if re.match(r"^loading\s+dock\b", line, re.IGNORECASE):
            continue
        result.append(line)
    return result


def is_actionable_console_error(message_type: str, message_text: str) -> bool:
    """Keep application console errors; resource failures have dedicated evidence."""
    return message_type == "error" and not message_text.startswith(
        "Failed to load resource:"
    )


class _ScreenshotServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _QuietScreenshotHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        return


def screenshot_project_to_dir(project_dir: Path, out_dir: Path, browser_proxy: str = "",
                              viewports: list[tuple[str, int, int]] | None = None,
                              full_page: bool = False,
                              index_only: bool = False,
                              stateful_pages: set[str] | None = None) -> list[dict[str, str]]:
    """Capture every user-facing page/viewport over local HTTP.

    This is used for image-editing/image-repair pairs.  It deliberately does
    not use ``file://``: root-relative assets and the frozen project's routing
    must be tested exactly as in Pipeline C.  The local server bypasses the
    optional browser proxy while permitted remote image URLs still use it.
    """
    from playwright.sync_api import sync_playwright

    viewports = viewports if viewports is not None else VIEWPORTS
    pages = discover_browser_routes(project_dir)
    if index_only:
        index_pages = [page for page in pages if page == "index.html"]
        pages = index_pages or pages[:1]
    if not pages:
        raise RuntimeError("no html pages found")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Bind port 0 directly so the kernel reserves the selected port for this
    # server atomically.  Selecting a free port with a separate probe socket
    # creates a TOCTOU race when many screenshot workers start together.
    server = _ScreenshotServer(("127.0.0.1", 0), functools.partial(_QuietScreenshotHandler, directory=str(project_dir)))
    port = int(server.server_address[1])
    threading.Thread(target=server.serve_forever, daemon=True).start()
    records: list[dict[str, str]] = []
    navigation_timeout_ms = int(os.environ.get("SCREENSHOT_NAVIGATION_TIMEOUT_MS", "45000"))
    screenshot_attempts = max(1, int(os.environ.get("SCREENSHOT_ATTEMPTS", "2")))
    try:
      with sync_playwright() as p:
        executable_path = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or None
        launch_args: list[str] = []
        if browser_proxy:
            launch_args.append("--proxy-bypass-list=127.0.0.1,localhost")
        if os.environ.get("PLAYWRIGHT_CHROMIUM_NO_SANDBOX", "").strip().lower() in {
            "1", "true", "yes", "on",
        }:
            launch_args.extend(["--no-sandbox", "--disable-dev-shm-usage"])
        browser = p.chromium.launch(
            headless=True,
            executable_path=executable_path,
            proxy={"server": browser_proxy} if browser_proxy else None,
            args=launch_args or None,
        )
        try:
            for rel in pages:
                page_key = safe_name(rel[:-5] if rel.lower().endswith(".html") else rel)
                for vp_name, width, height in viewports:
                    for attempt in range(1, screenshot_attempts + 1):
                        page = browser.new_page(viewport={"width": width, "height": height})
                        console_errors: list[str] = []
                        page_errors: list[str] = []
                        failed_requests: list[str] = []
                        bad_responses: list[str] = []
                        page.on(
                            "console",
                            lambda message: console_errors.append(message.text)
                            if is_actionable_console_error(message.type, message.text)
                            else None,
                        )
                        page.on(
                            "pageerror",
                            lambda error: page_errors.append(
                                str(getattr(error, "stack", "") or error)
                            ),
                        )
                        page.on(
                            "requestfailed",
                            lambda request: failed_requests.append(request.url),
                        )
                        page.on(
                            "response",
                            lambda response: bad_responses.append(
                                f"{response.status} {response.url}"
                            ) if response.status >= 400 else None,
                        )
                        try:
                            navigation = None
                            if stateful_pages and rel in stateful_pages:
                                navigation = _navigate_through_visible_entry(
                                    page, port, rel, pages, navigation_timeout_ms
                                )
                            if navigation is None:
                                response = page.goto(
                                    local_route_url(port, rel),
                                    wait_until="domcontentloaded",
                                    timeout=navigation_timeout_ms,
                                )
                                if response is None or response.status >= 400:
                                    raise RuntimeError(f"local_http_status:{response.status if response else 'none'}")
                                navigation = {
                                    "capture_mode": "direct",
                                    "capture_entry_page": rel,
                                    "capture_entry_href": "",
                                    "capture_entry_text": "",
                                }
                            # Timed intro/loading overlays in real projects often
                            # disappear around 2--2.5 seconds after window.load.
                            # Capture the settled application rather than a splash
                            # screen; the value remains configurable for audits.
                            page.wait_for_timeout(int(os.environ.get("SCREENSHOT_SETTLE_MS", "3000")))
                            visible_text = page.locator("body").inner_text(timeout=5000)
                            main_locator = page.locator(
                                "main, [role='main'], #app, #root, .main, .content"
                            ).first
                            main_text = (
                                main_locator.inner_text(timeout=5000)
                                if main_locator.count() and main_locator.is_visible()
                                else ""
                            )
                            dom = page.locator("body").inner_html(timeout=5000)
                            unsettled_loading_texts = detect_unsettled_loading_texts(
                                visible_text
                            )
                            visible_dialogs = []
                            dialogs = page.locator("[role='dialog']:visible, dialog[open]:visible")
                            for dialog_index in range(dialogs.count()):
                                dialog = dialogs.nth(dialog_index)
                                visible_dialogs.append({
                                    "text": dialog.inner_text(timeout=2000).strip(),
                                    "interactive_count": dialog.locator(
                                        "button, a[href], input, select, textarea"
                                    ).count(),
                                })
                            visible_hidden_elements = []
                            hidden_visible = page.locator("[hidden]:visible")
                            for hidden_index in range(hidden_visible.count()):
                                element = hidden_visible.nth(hidden_index)
                                visible_hidden_elements.append({
                                    "tag": element.evaluate("node => node.tagName.toLowerCase()"),
                                    "id": element.get_attribute("id") or "",
                                    "text": element.inner_text(timeout=2000).strip()[:240],
                                })
                            route_texts = detect_initial_route_texts(visible_text)
                            initial_empty_state_texts = route_texts["empty"]
                            initial_hard_failure_texts = route_texts["hard"]
                            dest = out_dir / f"{page_key}__{vp_name}.jpg"
                            page.screenshot(path=str(dest), full_page=full_page, type="jpeg", quality=92,
                                            animations="disabled", caret="hide", timeout=90000)
                            records.append({"page": rel, "viewport": vp_name,
                                            "path": dest.relative_to(out_dir.parent).as_posix(),
                                            "browser_version": browser.version,
                                            "final_url": page.url,
                                            "document_title": page.title(),
                                            "visible_text_chars": len(visible_text.strip()),
                                            "main_text_chars": len(main_text.strip()),
                                            "visible_text_sha256": hashlib.sha256(
                                                visible_text.strip().encode("utf-8")
                                            ).hexdigest(),
                                            "dom_sha256": hashlib.sha256(
                                                dom.encode("utf-8")
                                            ).hexdigest(),
                                            "console_errors": console_errors,
                                            "page_errors": page_errors,
                                            "failed_requests": failed_requests,
                                            "bad_responses": bad_responses,
                                            "unsettled_loading_texts": unsettled_loading_texts,
                                            "visible_dialogs": visible_dialogs,
                                            "visible_hidden_elements": visible_hidden_elements,
                                            "initial_empty_state_texts": initial_empty_state_texts,
                                            "initial_hard_failure_texts": initial_hard_failure_texts,
                                            **navigation})
                            break
                        except Exception as exc:
                            print(
                                f"  screenshot attempt {attempt}/{screenshot_attempts} failed "
                                f"for {rel} ({vp_name}): {exc}"
                            )
                        finally:
                            page.close()
        finally:
            browser.close()
    finally:
        server.shutdown(); server.server_close()
    expected = len(pages) * len(viewports)
    if len(records) != expected:
        raise RuntimeError(f"incomplete_playwright_screenshots:{len(records)}/{expected}")
    return records


def repair_visual_difference(clean_screens: list[dict], defective_screens: list[dict],
                             minimum_ratio: float = .01,
                             channel_threshold: int = 8) -> dict[str, Any]:
    """Reject repair defects that do not visibly change a rendered screenshot.

    Records returned by :func:`screenshot_project_to_dir` have paths relative
    to the parent of their screenshot directory.  Callers must resolve them
    before this function.  Keeping this gate in the common module ensures the
    JSONL text-repair and legacy image-repair paths enforce the same policy.
    """
    from PIL import Image, ImageChops

    clean_by_key = {(x["page"], x["viewport"]): x for x in clean_screens}
    defect_by_key = {(x["page"], x["viewport"]): x for x in defective_screens}
    if clean_by_key.keys() != defect_by_key.keys():
        raise RuntimeError("clean_defective_screenshot_keys_mismatch")
    metrics: list[dict[str, Any]] = []
    for key, clean in clean_by_key.items():
        defective = defect_by_key[key]
        with Image.open(clean["path"]) as raw_a, Image.open(defective["path"]) as raw_b:
            a, b = raw_a.convert("RGB"), raw_b.convert("RGB")
            if a.size != b.size:
                raise RuntimeError(f"screenshot_size_mismatch:{key}")
            diff = ImageChops.difference(a, b)
            pixels = (
                diff.get_flattened_data()
                if hasattr(diff, "get_flattened_data")
                else diff.getdata()
            )
            changed = sum(1 for pixel in pixels if max(pixel) >= channel_threshold)
            ratio = changed / max(a.width * a.height, 1)
        metrics.append({"page": key[0], "viewport": key[1], "changed_pixels": changed,
                        "total_pixels": a.width * a.height, "changed_ratio": round(ratio, 6)})
    strongest = max((item["changed_ratio"] for item in metrics), default=0.0)
    if strongest < minimum_ratio:
        raise RuntimeError(f"repair_defect_not_visually_observable:{strongest:.6f}<{minimum_ratio:.6f}")
    return {"minimum_changed_ratio": minimum_ratio, "channel_threshold": channel_threshold,
            "max_changed_ratio": strongest, "screens": metrics}


def screenshot_pair_difference(
    before_screens: list[dict],
    after_screens: list[dict],
    *,
    minimum_ratio: float = 0.002,
    channel_threshold: int = 8,
) -> dict[str, Any]:
    """Compare full-page Edit states while allowing page-height changes."""
    from PIL import Image, ImageChops

    before_by_key = {(item.get("page", "index.html"), item.get("viewport", "desktop")): item
                     for item in before_screens}
    after_by_key = {(item.get("page", "index.html"), item.get("viewport", "desktop")): item
                    for item in after_screens}
    if before_by_key.keys() != after_by_key.keys():
        raise RuntimeError("edit_source_target_screenshot_keys_mismatch")
    metrics = []
    for key, before in before_by_key.items():
        after = after_by_key[key]
        with Image.open(before["path"]) as raw_before, Image.open(after["path"]) as raw_after:
            left, right = raw_before.convert("RGB"), raw_after.convert("RGB")
            width, height = max(left.width, right.width), max(left.height, right.height)
            left_canvas = Image.new("RGB", (width, height), "white")
            right_canvas = Image.new("RGB", (width, height), "white")
            left_canvas.paste(left, (0, 0)); right_canvas.paste(right, (0, 0))
            diff = ImageChops.difference(left_canvas, right_canvas)
            masks = [
                channel.point(lambda value: 255 if value >= channel_threshold else 0)
                for channel in diff.split()
            ]
            combined = ImageChops.lighter(ImageChops.lighter(masks[0], masks[1]), masks[2])
            changed = width * height - combined.histogram()[0]
            ratio = changed / max(width * height, 1)
        metrics.append({
            "page": key[0], "viewport": key[1], "changed_pixels": changed,
            "total_pixels": width * height, "changed_ratio": round(ratio, 6),
            "before_size": [left.width, left.height], "after_size": [right.width, right.height],
        })
    strongest = max((item["changed_ratio"] for item in metrics), default=0.0)
    if strongest < minimum_ratio:
        raise RuntimeError(
            f"edit_not_visually_observable:{strongest:.6f}<{minimum_ratio:.6f}"
        )
    return {
        "minimum_changed_ratio": minimum_ratio,
        "channel_threshold": channel_threshold,
        "max_changed_ratio": strongest,
        "screens": metrics,
    }


_CONSTRUCT_BROWSER_ACTIONS = {
    "click", "hover", "focus", "fill", "select_option", "key_press",
    "drag_and_drop", "scroll", "wait_for",
}
_CONSTRUCT_BROWSER_ASSERTIONS = {"visible", "hidden", "text", "attribute", "value", "url"}


def _browser_route_identity(route: str) -> tuple[str, str]:
    path_and_query, _, fragment = route.lstrip("/").partition("#")
    path = path_and_query.split("?", 1)[0] or "index.html"
    return path, fragment.strip("/")


def _normalize_browser_route(route: Any, project_pages: list[str]) -> str:
    pages = [str(page).strip() for page in project_pages if str(page).strip()]
    if not pages:
        raise ValueError("project_pages must contain at least one browser route")
    raw = str(route or "").strip()
    if raw in {"", "/"}:
        return pages[0]
    raw = raw.lstrip("/")
    if raw.startswith("#"):
        host = pages[0].partition("#")[0] or "index.html"
        raw = f"{host}{raw}"
    identity = _browser_route_identity(raw)
    for page in pages:
        if _browser_route_identity(page) == identity:
            return page
    # Query strings select state within an existing document and are safe to
    # retain when the underlying document is an accepted canonical route.
    raw_path = identity[0]
    if not identity[1] and any(_browser_route_identity(page)[0] == raw_path for page in pages):
        return raw
    return raw


def normalize_browser_checks(checks: Any, project_pages: list[str]) -> Any:
    """Canonicalize common Doc API aliases without weakening browser evidence."""
    if not isinstance(checks, list):
        return checks
    normalized: list[Any] = []
    action_aliases = {
        "type": "fill", "input": "fill", "select": "select_option",
        "press": "key_press", "keypress": "key_press", "drag/drop": "drag_and_drop",
        "drag_drop": "drag_and_drop",
    }
    for raw_check in checks:
        if not isinstance(raw_check, dict):
            normalized.append(raw_check)
            continue
        check = dict(raw_check)
        check["route"] = _normalize_browser_route(check.get("route"), project_pages)
        actions = []
        for raw_action in check.get("actions", []):
            if not isinstance(raw_action, dict):
                actions.append(raw_action)
                continue
            action = dict(raw_action)
            name = action_aliases.get(str(action.get("action", "")).lower(), action.get("action"))
            action["action"] = name
            if name in {"fill", "select_option"} and "value" not in action:
                for alias in ("text", "option", "input"):
                    if alias in action:
                        action["value"] = action[alias]
                        break
            if name == "drag_and_drop":
                action.setdefault("source_selector", action.get("source"))
                action.setdefault("target_selector", action.get("target"))
            for alias in ("text", "option", "input", "source", "target"):
                action.pop(alias, None)
            actions.append(action)
        check["actions"] = actions
        raw_assertion = check.get("assertion")
        if isinstance(raw_assertion, dict):
            assertion = dict(raw_assertion)
            kind = str(assertion.get("type", ""))
            if kind in {"url_contains", "url_includes"}:
                assertion["type"] = "url"
            if "expected" not in assertion:
                for alias in ("value", "text"):
                    if alias in assertion:
                        assertion["expected"] = assertion[alias]
                        break
            if assertion.get("type") == "attribute" and "name" not in assertion:
                for alias in ("attribute", "property"):
                    if alias in assertion:
                        assertion["name"] = assertion[alias]
                        break
            for alias in ("value", "text", "attribute", "property"):
                assertion.pop(alias, None)
            if assertion.get("type") in {"attribute", "value"} and not assertion.get("selector"):
                for action in reversed(actions):
                    if isinstance(action, dict) and str(action.get("selector", "")).strip():
                        assertion["selector"] = action["selector"]
                        break
            check["assertion"] = assertion
        normalized.append(check)
    return normalized


def validate_browser_checks(
    checks: Any, expected_task_types: list[str], project_pages: list[str]
) -> list[dict[str, Any]]:
    """Validate hidden screenshot actions without exposing them to training."""
    checks = normalize_browser_checks(checks, project_pages)
    if not isinstance(checks, list) or len(checks) != len(expected_task_types):
        raise ValueError("browser_checks must contain exactly one check per task type")
    actual = [str(check.get("task_type", "")) for check in checks if isinstance(check, dict)]
    if Counter(actual) != Counter(expected_task_types):
        raise ValueError("browser_checks task types must match selected edit task types")
    allowed_pages = set(project_pages)
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            raise ValueError(f"browser check {index} must be an object")
        route = str(check.get("route", ""))
        # SPA routers often create concrete hash routes from runtime data, so
        # static route discovery cannot enumerate every valid fragment.  The
        # browser contract may retain such a fragment as long as its backing
        # HTML document is one of the accepted project pages.
        if route not in allowed_pages and not any(
            _browser_route_identity(page)[0] == _browser_route_identity(route)[0]
            for page in project_pages
        ):
            raise ValueError(f"browser check {index} uses unknown route {route!r}")
        actions = check.get("actions")
        if not isinstance(actions, list) or not actions:
            raise ValueError(f"browser check {index} must contain actions")
        for action_index, action in enumerate(actions):
            if not isinstance(action, dict) or action.get("action") not in _CONSTRUCT_BROWSER_ACTIONS:
                raise ValueError(f"browser check {index} action {action_index} is unsupported")
            name = str(action["action"])
            if name in {"click", "hover", "focus", "fill", "select_option", "wait_for"}:
                if not str(action.get("selector", "")).strip():
                    raise ValueError(f"browser action {name} requires selector")
            if name in {"fill", "select_option"} and "value" not in action:
                raise ValueError(f"browser action {name} requires value")
            if name == "key_press" and not str(action.get("key", "")).strip():
                raise ValueError("browser action key_press requires key")
            if name == "drag_and_drop" and not (
                str(action.get("source_selector", "")).strip()
                and str(action.get("target_selector", "")).strip()
            ):
                raise ValueError("browser action drag_and_drop requires source and target selectors")
        assertion = check.get("assertion")
        if not isinstance(assertion, dict) or assertion.get("type") not in _CONSTRUCT_BROWSER_ASSERTIONS:
            raise ValueError(f"browser check {index} has unsupported assertion")
        if assertion["type"] != "url" and not str(assertion.get("selector", "")).strip():
            raise ValueError(f"browser check {index} assertion requires selector")
        if assertion["type"] in {"text", "attribute", "value", "url"} and "expected" not in assertion:
            raise ValueError(
                f"browser check {index} {assertion['type']} assertion requires expected"
            )
        if assertion["type"] == "attribute" and not str(assertion.get("name", "")).strip():
            raise ValueError(f"browser check {index} attribute assertion requires name")
        delay = check.get("capture_delay_ms", 150)
        if isinstance(delay, bool) or not isinstance(delay, int) or not 0 <= delay <= 5000:
            raise ValueError("capture_delay_ms must be an integer from 0 to 5000")
    return checks


def _attribute_value_represented(code: str, attribute: str, expected: str) -> bool:
    values = re.findall(
        rf"{re.escape(attribute)}\s*=\s*(['\"])(.*?)\1", code, flags=re.DOTALL
    )
    for _, value in values:
        if value == expected:
            return True
        parts = re.split(r"(\$\{[^}]+\})", value)
        if len(parts) > 1:
            pattern = "".join(".+" if part.startswith("${") else re.escape(part)
                              for part in parts)
            if re.fullmatch(pattern, expected):
                return True
    return False


def validate_stable_browser_selectors(
    checks: list[dict[str, Any]], code_files: list[dict[str, str]]
) -> None:
    """Reject explicit ID/test-id contracts absent from the rendered target code."""
    code = "\n".join(str(item.get("code", "")) for item in code_files)
    selectors: list[str] = []
    for check in checks:
        for action in check.get("actions", []):
            for key in ("selector", "source_selector", "target_selector"):
                if str(action.get(key, "")).strip():
                    selectors.append(str(action[key]).strip())
        assertion = check.get("assertion", {})
        if str(assertion.get("selector", "")).strip():
            selectors.append(str(assertion["selector"]).strip())
    for selector in selectors:
        test_id = re.fullmatch(r"\[data-testid=(['\"])([^'\"]+)\1\]", selector)
        if test_id and not _attribute_value_represented(
            code, "data-testid", test_id.group(2)
        ):
            raise ValueError(f"browser selector missing-test-id in patched code: {selector}")
        element_id = re.fullmatch(r"#([A-Za-z][A-Za-z0-9_:\-.]*)", selector)
        if element_id and not _attribute_value_represented(
            code, "id", element_id.group(1)
        ):
            raise ValueError(f"browser selector missing-id in patched code: {selector}")


def _first_visible_locator(locator: Any) -> Any:
    """Choose a visible match instead of blindly using a hidden first node."""
    try:
        for index in range(locator.count()):
            candidate = locator.nth(index)
            if candidate.is_visible():
                return candidate
    except Exception:  # Playwright will provide the authoritative action error.
        pass
    return locator.first


def _perform_browser_action(page: Any, action: dict[str, Any]) -> None:
    """Execute one normalized browser action against its usable DOM control."""
    name = str(action["action"])
    selector = str(action.get("selector", ""))
    locator = _first_visible_locator(page.locator(selector)) if selector else None
    if name == "click":
        if locator.is_visible():
            locator.click()
        else:
            # Native checkboxes/radios are often visually hidden behind a
            # styled label while remaining the actual stateful control.
            locator.evaluate("el => el.click()")
    elif name == "hover":
        locator.hover(force=True)
    elif name == "focus":
        locator.focus()
    elif name == "fill":
        # Doc API occasionally labels a native select interaction as `fill`.
        # Honor the observable intent using the element's real DOM type.
        tag_name = str(locator.evaluate("el => el.tagName.toLowerCase()"))
        if tag_name == "select":
            locator.select_option(str(action["value"]))
        else:
            locator.fill(str(action["value"]))
    elif name == "select_option":
        locator.select_option(str(action["value"]))
    elif name == "key_press":
        if locator is not None:
            locator.press(str(action["key"]))
        else:
            page.keyboard.press(str(action["key"]))
    elif name == "drag_and_drop":
        page.drag_and_drop(
            str(action["source_selector"]), str(action["target_selector"])
        )
    elif name == "scroll":
        page.evaluate("y => window.scrollTo(0, y)", int(action.get("y", 600)))
    elif name == "wait_for":
        page.locator(selector).first.wait_for(
            state=str(action.get("state", "visible")),
            timeout=min(int(action.get("timeout_ms", 5000)), 5000),
        )


def _resolve_interaction_route(
    page: Any, port: int, check: dict[str, Any], project_routes: list[str]
) -> str:
    """Open the declared route, relocating only when its first trigger lives elsewhere."""
    initial_route = str(check["route"])
    first_action = check.get("actions", [{}])[0]
    probe_selector = str(
        first_action.get("selector") or first_action.get("source_selector") or ""
    ).strip()
    candidates = list(dict.fromkeys([initial_route, *project_routes]))
    attached_route = ""
    for route in candidates:
        response = page.goto(
            local_route_url(port, route),
            wait_until="domcontentloaded", timeout=45_000,
        )
        if response is None or response.status >= 400:
            if route == initial_route:
                raise RuntimeError(
                    f"local_http_status:{response.status if response else 'none'}"
                )
            continue
        page.wait_for_timeout(300)
        if not probe_selector:
            return route
        locator = page.locator(probe_selector)
        if locator.count() > 0:
            attached_route = attached_route or route
            if any(locator.nth(index).is_visible() for index in range(locator.count())):
                return route
    if attached_route:
        page.goto(
            local_route_url(port, attached_route),
            wait_until="domcontentloaded", timeout=45_000,
        )
        page.wait_for_timeout(300)
        return attached_route
    raise RuntimeError(f"interaction_selector_missing_on_all_routes:{probe_selector}")


def capture_interaction_screenshots(
    project_dir: Path,
    out_dir: Path,
    browser_checks: list[dict[str, Any]],
    browser_proxy: str = "",
    allow_assertion_failure: bool = False,
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """Execute hidden LLM-authored actions and capture the observable states."""
    from playwright.sync_api import sync_playwright

    project_routes = discover_browser_routes(project_dir)
    browser_checks = validate_browser_checks(
        browser_checks,
        [str(check["task_type"]) for check in browser_checks],
        project_routes,
    )
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    server = _ScreenshotServer(
        ("127.0.0.1", 0),
        functools.partial(_QuietScreenshotHandler, directory=str(project_dir)),
    )
    port = int(server.server_address[1])
    threading.Thread(target=server.serve_forever, daemon=True).start()
    screenshots: list[dict[str, str]] = []
    evidence: list[dict[str, Any]] = []
    try:
        with sync_playwright() as playwright:
            executable_path = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or None
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=executable_path,
                proxy={"server": browser_proxy} if browser_proxy else None,
                args=["--proxy-bypass-list=127.0.0.1,localhost"] if browser_proxy else None,
            )
            try:
                for index, check in enumerate(browser_checks):
                    page = browser.new_page(viewport={"width": 1920, "height": 1080})
                    try:
                        route = _resolve_interaction_route(
                            page, port, check, project_routes
                        )
                        item = {
                            "task_type": check["task_type"], "route": route,
                            "declared_route": str(check["route"]), "actions": [],
                        }
                        for action in check["actions"]:
                            name = str(action["action"])
                            _perform_browser_action(page, action)
                            item["actions"].append({"action": name, "status": "ok"})
                        page.wait_for_timeout(int(check.get("capture_delay_ms", 150)))
                        assertion = check["assertion"]
                        assertion_type = str(assertion["type"])
                        locator = _first_visible_locator(
                            page.locator(str(assertion.get("selector", "body")))
                        )
                        if assertion_type == "visible":
                            observed = locator.is_visible()
                        elif assertion_type == "hidden":
                            observed = not locator.is_visible()
                        elif assertion_type == "text":
                            observed = str(assertion.get("expected", "")) in locator.inner_text()
                        elif assertion_type == "attribute":
                            observed = locator.get_attribute(str(assertion["name"])) == str(assertion["expected"])
                        elif assertion_type == "value":
                            observed = locator.input_value() == str(assertion["expected"])
                        else:
                            observed = str(assertion.get("expected", "")) in page.url
                        filename = f"{index:02d}__{safe_name(str(check['task_type']))}.jpg"
                        destination = out_dir / filename
                        page.screenshot(
                            path=str(destination), full_page=True, type="jpeg", quality=92,
                            animations="disabled", caret="hide", timeout=90_000,
                        )
                        screenshots.append({
                            "page": route,
                            "viewport": f"desktop_interaction_{index}",
                            "task_type": str(check["task_type"]),
                            "path": destination.relative_to(out_dir.parent).as_posix(),
                        })
                        item.update({
                            "status": "ok" if observed else "assertion_failed",
                            "assertion": assertion,
                            "assertion_observed": observed,
                            "url": page.url,
                        })
                        if not observed and not allow_assertion_failure:
                            raise RuntimeError(f"interaction_assertion_failed:{assertion_type}")
                    finally:
                        page.close()
                    evidence.append(item)
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close()
    return screenshots, evidence


def collect_browser_failures(
    project_dir: Path, browser_proxy: str = ""
) -> list[dict[str, str]]:
    """Collect reproducible browser/runtime failures from every local page."""
    from playwright.sync_api import sync_playwright

    pages = discover_browser_routes(project_dir)
    server = _ScreenshotServer(
        ("127.0.0.1", 0),
        functools.partial(_QuietScreenshotHandler, directory=str(project_dir)),
    )
    port = int(server.server_address[1])
    threading.Thread(target=server.serve_forever, daemon=True).start()
    failures: list[dict[str, str]] = []
    try:
        with sync_playwright() as playwright:
            executable_path = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or None
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=executable_path,
                proxy={"server": browser_proxy} if browser_proxy else None,
                args=["--proxy-bypass-list=127.0.0.1,localhost"] if browser_proxy else None,
            )
            try:
                for route in pages:
                    page = browser.new_page(viewport={"width": 1920, "height": 1080})
                    page.on(
                        "pageerror",
                        lambda error, route=route: failures.append(
                            {"kind": "page_error", "route": route, "message": str(error)}
                        ),
                    )
                    page.on(
                        "console",
                        lambda message, route=route: failures.append(
                            {"kind": "console_error", "route": route, "message": message.text}
                        ) if message.type == "error" else None,
                    )
                    page.on(
                        "requestfailed",
                        lambda request, route=route: failures.append(
                            {
                                "kind": "request_failure",
                                "route": route,
                                "message": f"{request.url}: {request.failure}",
                            }
                        ),
                    )
                    try:
                        response = page.goto(
                            local_route_url(port, route),
                            wait_until="domcontentloaded",
                            timeout=45_000,
                        )
                        if response is None or response.status >= 400:
                            failures.append({
                                "kind": "request_failure",
                                "route": route,
                                "message": f"local_http_status:{response.status if response else 'none'}",
                            })
                        page.wait_for_timeout(1000)
                    finally:
                        page.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
    return failures


def collect_quality_audit(project_dir: Path, browser_proxy: str = "") -> dict[str, int]:
    """Return deterministic DOM/accessibility regression counters."""
    from playwright.sync_api import sync_playwright

    pages = discover_browser_routes(project_dir)
    server = _ScreenshotServer(
        ("127.0.0.1", 0),
        functools.partial(_QuietScreenshotHandler, directory=str(project_dir)),
    )
    port = int(server.server_address[1])
    threading.Thread(target=server.serve_forever, daemon=True).start()
    totals = Counter()
    audit_script = """() => ({
      images_without_alt: document.querySelectorAll('img:not([alt])').length,
      controls_without_name: [...document.querySelectorAll('button,input,select,textarea')]
        .filter(el => !((el.getAttribute('aria-label') || '').trim()) &&
          !(el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`)) &&
          !((el.textContent || '').trim()) && !((el.getAttribute('title') || '').trim())).length,
      links_without_name: [...document.querySelectorAll('a[href]')]
        .filter(el => !((el.textContent || '').trim()) && !((el.getAttribute('aria-label') || '').trim()) && !el.querySelector('img[alt]')).length,
      duplicate_ids: [...document.querySelectorAll('[id]')]
        .map(el => el.id).filter((id, i, ids) => ids.indexOf(id) !== i).length,
      positive_tabindex: document.querySelectorAll('[tabindex]:not([tabindex="0"]):not([tabindex="-1"])').length
    })"""
    try:
        with sync_playwright() as playwright:
            executable_path = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or None
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=executable_path,
                proxy={"server": browser_proxy} if browser_proxy else None,
                args=["--proxy-bypass-list=127.0.0.1,localhost"] if browser_proxy else None,
            )
            try:
                for route in pages:
                    page = browser.new_page(viewport={"width": 1920, "height": 1080})
                    try:
                        page.goto(
                            local_route_url(port, route),
                            wait_until="domcontentloaded",
                            timeout=45_000,
                        )
                        page.wait_for_timeout(300)
                        totals.update(page.evaluate(audit_script))
                    finally:
                        page.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
    return dict(totals)


def _truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n<!-- truncated for PRD synthesis -->"


def generate_prd_from_code(project_dir: Path) -> str:
    """Generate PRD instruction from source code only (no screenshots/VLM)."""
    from openai import OpenAI

    maybe_load_env()
    api_key, base_url, model = ensure_api_env(prefer_vision=False)
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=300.0)

    code_items = read_code_bundle(project_dir, code_only=True)
    resources = collect_resources(project_dir)
    # Reserve tokens for prompt template + output.
    # 1 token ≈ 4 chars for code. Default 200K tokens.
    # Override via OPENAI_MAX_INPUT_TOKENS env var for smaller-context models.
    max_input_tokens = int(os.environ.get("OPENAI_MAX_INPUT_TOKENS", "200000"))
    prompt_overhead = len(CODE_PRD_PROMPT) + 200
    max_chars = max(max_input_tokens * 4 - prompt_overhead, 20_000)
    context = "<code_context>\n"
    remaining = max_chars
    for item in sorted(code_items, key=lambda it: (_code_priority(it["path"]), it["path"])):
        if remaining <= 0:
            break
        code = _truncate_text(item["code"], remaining)
        context += f'<file path="{item["path"]}">\n{code}\n</file>\n'
        remaining -= len(code)
    context += "</code_context>"

    if resources:
        context += "\n<resources>\n"
        for res in resources:
            context += f'  <file path="{res["path"]}" type="{res.get("type", "image")}" />\n'
        context += "</resources>"

    prompt = CODE_PRD_PROMPT + "\n\n" + context

    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=16_384,
            )
            result = response.choices[0].message.content or ""
            if result.strip():
                print(f"  PRD generated (attempt {attempt}, {len(result)} chars)")
                return result
            raise ValueError("Empty response from LLM")
        except Exception as e:
            last_error = e
            err_lower = str(e).lower()
            if any(kw in err_lower for kw in ["invalid api key", "authentication", "model not found"]):
                raise
            if attempt < 3:
                delay = 10 * attempt
                print(f"  PRD generation error (attempt {attempt}): {e} — retrying in {delay}s")
                time.sleep(delay)
    raise Exception(f"PRD generation failed after 3 attempts: {last_error}") from last_error


def description_to_text(description: Any) -> str:
    if isinstance(description, str):
        return description.strip()
    if isinstance(description, list):
        lines = []
        for item in description:
            if isinstance(item, dict):
                task_type = str(item.get("task_type", "")).strip()
                desc = str(item.get("description", "")).strip()
                if task_type and desc:
                    lines.append(f"[{task_type}] {desc}")
                elif desc:
                    lines.append(desc)
            elif item:
                lines.append(str(item).strip())
        return "\n".join(line for line in lines if line)
    return str(description or "").strip()


def base_info(instance_id: str, task: str) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "task": task,
        "task_type": [],
        "description": [],
        "src_code": [],
        "dst_code": [],
        "file_manifest": [],
        "src_screenshot": [],
        "dst_screenshot": [],
        "label_modified_files": [],
        "resources": [],
        "meta": {},
    }


def ensure_api_env(prefer_vision: bool = False) -> tuple[str, str | None, str]:
    maybe_load_env()
    if prefer_vision:
        api_key = os.environ.get("VISION_OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("KIMI_API_KEY")
        base_url = os.environ.get("VISION_OPENAI_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
        model = os.environ.get("VISION_MODEL") or os.environ.get("OPENAI_MODEL") or os.environ.get("MODEL") or "gpt-4o"
    else:
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("KIMI_API_KEY") or os.environ.get("VISION_OPENAI_API_KEY")
        base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("KIMI_BASE_URL") or os.environ.get("VISION_OPENAI_BASE_URL")
        model = os.environ.get("OPENAI_MODEL") or os.environ.get("KIMI_MODEL") or os.environ.get("MODEL") or "kimi-k2.6"
        if os.environ.get("KIMI_API_KEY") and not base_url:
            base_url = "https://api.moonshot.cn/v1"
    if not api_key:
        raise ValueError("Missing API key in environment")
    return api_key, base_url, model


def write_generation_instance(
    output_root: Path,
    task: str,
    project_dir: Path,
    info: dict[str, Any],
) -> Path:
    instance_dir = output_root / project_dir.name
    if instance_dir.exists():
        shutil.rmtree(instance_dir)
    instance_dir.mkdir(parents=True, exist_ok=True)
    copy_project(project_dir, instance_dir / "dst")
    safe_write_json(instance_dir / "info.json", info)
    return instance_dir


def write_pair_instance(
    output_root: Path,
    bucket: str,
    project_dir: Path,
    src_code: list[dict[str, str]],
    dst_code: list[dict[str, str]],
    info: dict[str, Any],
) -> Path:
    instance_dir = output_root / bucket / project_dir.name
    if instance_dir.exists():
        shutil.rmtree(instance_dir)
    instance_dir.mkdir(parents=True, exist_ok=True)
    write_code_bundle_from_source(project_dir, src_code, instance_dir / "src")
    write_code_bundle_from_source(project_dir, dst_code, instance_dir / "dst")
    safe_write_json(instance_dir / "info.json", info)
    return instance_dir


def build_generation_data(
    project_dir: Path,
    tokenizer_json: Path | None = None,
    max_prompt_tokens: int = 40_000,
    *, image_based: bool = False,
) -> dict[str, Any]:
    """Prepare <=40K model code; image tasks may retain frozen render resources."""
    try:  # package import for tests; direct import for CLI scripts from repo root
        from crawl.pipeline_c.qwen_token_gate import (
            count_project_tokens,
            count_serialized_tokens,
            iter_training_code_files,
            serialize_training_project,
            read_render_dependencies,
        )
    except ModuleNotFoundError:
        from crawl.pipeline_c.qwen_token_gate import (
            count_project_tokens,
            count_serialized_tokens,
            iter_training_code_files,
            serialize_training_project,
            read_render_dependencies,
        )

    tokenizer_json = tokenizer_json or Path(
        os.environ.get("QWEN_TOKENIZER_JSON", REPO_ROOT / ".cache/qwen3-tokenizer.json")
    )
    render_dependencies = read_render_dependencies(project_dir,verify_hashes=True)
    if render_dependencies and not image_based:
        raise ValueError('render_only_dependencies_require_image_based_task')
    all_code_files = iter_training_code_files(project_dir)
    full_code = [
        {"path": path.relative_to(project_dir).as_posix(),
         "code": path.read_text(encoding="utf-8", errors="replace")}
        for path in all_code_files
    ]

    if tokenizer_json.is_file():
        full_prompt_tokens = count_project_tokens(project_dir, tokenizer_json)
    else:
        # Local debug convenience: without the exact Qwen tokenizer the 40K gate
        # cannot run, so skip it explicitly instead of failing every project.
        print(f"WARNING: tokenizer not found ({tokenizer_json}); skipping 40K token gate")
        full_prompt_tokens = 0
    if full_prompt_tokens > max_prompt_tokens:
        raise ValueError(
            f"model-visible source is {full_prompt_tokens} Qwen tokens, over {max_prompt_tokens}"
        )
    visible_code = full_code
    context_mode = "image_render_assisted" if render_dependencies else "full"
    model_context = serialize_training_project(project_dir)
    prompt_tokens = full_prompt_tokens
    project_documents = [
        path.relative_to(project_dir).as_posix()
        for path in find_html_pages(project_dir)
    ]
    project_pages = discover_browser_routes(project_dir)

    return {
        "instance_id": project_dir.name,
        "dst_code": visible_code,
        "full_code": full_code,
        "resources": render_dependencies,
        "prompt_tokens": prompt_tokens,
        "full_prompt_tokens": full_prompt_tokens,
        "context_mode": context_mode,
        "model_context": model_context,
        "page_scope": "mp" if len(project_documents) >= 2 else "sp",
        "project_pages": project_pages,
        "project_routes": project_pages,
        "project_documents": project_documents,
        "input_contract": {"max_prompt_tokens": max_prompt_tokens,
            "all_files_included": not bool(render_dependencies),
            "image_based_only": bool(render_dependencies),
            "read_only_render_files": [x['file'] for x in render_dependencies]},
    }




def strip_markdown_fence(response_text: str) -> str:
    if "```xml" in response_text:
        return response_text.split("```xml", 1)[1].split("```", 1)[0].strip()
    if "```json" in response_text:
        return response_text.split("```json", 1)[1].split("```", 1)[0].strip()
    if "```" not in response_text:
        return response_text
    parts = response_text.split("```")
    if len(parts) < 3:
        return response_text
    fenced = parts[1].strip()
    for lang in ("xml", "XML", "json", "JSON"):
        if fenced.startswith(lang):
            return fenced[len(lang) :].strip()
    return fenced


_EDIT_TASKS: list[str] = [
    "Data Table",
    "Rich Text Editor",
    "Drag & Drop Interface",
    "Tree View",
    "Real-time Dashboard",
    "Infinite Scroll",
    "Async Form Validation",
    "File Upload with Progress",
    "Parallax Scrolling",
    "Page Transitions",
    "Particle Effects",
    "Skeleton Loading",
    "Shopping Cart",
    "User Authentication",
    "Multi-step Wizard",
    "Notification Center",
    "Dark Mode Toggle",
    "Accordion",
    "Modal Dialog",
    "Tooltip",
    "Breadcrumb Navigation",
    "Tabs",
    "Toast Notifications",
    "Star Rating",
    "Copy to Clipboard",
    "Back to Top",
    "Cookie Consent",
    "Responsive Navigation",
    "Sticky Header",
    "Search Autocomplete",
    "Image Lightbox",
    "Countdown Timer",
    "Color Picker",
    "Date Picker",
    "Carousel",
    "Keyboard Shortcuts",
    "Context Menu",
    "Lazy Loading Images",
    "Print Stylesheet",
    "Undo Redo",
]

_EDIT_TASK_DESCRIPTIONS: dict[str, str] = {
    "Data Table": "Implement an advanced data table component with rich functionality.\n    Requirements:\n    - Display tabular data with sortable columns (click header to sort asc/desc).\n    - Add pagination controls (previous/next, page numbers, items per page selector).\n    - Implement column filtering with dropdown or text input per column.\n    - Support row selection with checkboxes (single and select-all).\n    - Add inline editing capability for editable cells.\n    - Responsive design: horizontal scroll or card view on mobile.",
    "Rich Text Editor": "Implement a WYSIWYG rich text editor component.\n    Requirements:\n    - Create a toolbar with formatting buttons (Bold, Italic, Underline, Strikethrough).\n    - Support heading levels (H1-H3), lists (ordered/unordered), and blockquotes.\n    - Implement link insertion with URL input dialog.\n    - Add image embedding via URL or placeholder.\n    - Use contenteditable div or textarea with preview mode.\n    - Sync formatted content to a hidden textarea for form submission.",
    "Drag & Drop Interface": "Implement a drag-and-drop interface for reordering or organizing items.\n    Requirements:\n    - Create draggable items with visual drag handles.\n    - Implement drop zones with visual feedback (highlight on dragover).\n    - Support reordering within a single list (Kanban column style).\n    - Add cross-container drag support if multiple lists exist.\n    - Show placeholder/ghost element during drag operation.\n    - Persist order changes to data structure and optionally localStorage.",
    "Tree View": "Implement a hierarchical tree view component for nested data.\n    Requirements:\n    - Display nested items with expand/collapse toggles (arrows or +/- icons).\n    - Support multiple levels of nesting (at least 3 levels deep).\n    - Implement lazy loading or virtual rendering for large trees.\n    - Add checkbox selection with parent-child cascade (select parent selects all children).\n    - Support keyboard navigation (arrow keys, Enter to toggle).\n    - Add search/filter functionality to highlight matching nodes.",
    "Real-time Dashboard": "Implement a real-time dashboard with live-updating metrics.\n    Requirements:\n    - Create dashboard cards displaying key metrics (numbers, percentages).\n    - Simulate real-time data updates using setInterval or mock WebSocket.\n    - Add animated counters that smoothly transition between values.\n    - Implement mini charts/sparklines showing trend data (use CSS or canvas).\n    - Add status indicators (green/yellow/red) based on thresholds.\n    - Include a \"last updated\" timestamp that refreshes automatically.",
    "Infinite Scroll": "Implement infinite scroll pagination for a content feed.\n    Requirements:\n    - Load initial batch of items (e.g., 10-20 items).\n    - Detect when user scrolls near bottom using Intersection Observer or scroll event.\n    - Fetch and append next batch of items seamlessly.\n    - Show loading spinner/skeleton during fetch.\n    - Handle end-of-content state with \"No more items\" message.\n    - Implement scroll position restoration on back navigation (optional).",
    "Async Form Validation": "Implement comprehensive async form validation with server-side checks.\n    Requirements:\n    - Real-time validation on input blur and form submit.\n    - Simulate async validation (e.g., username availability check with delay).\n    - Show loading spinner next to field during async validation.\n    - Display inline error/success messages with appropriate icons.\n    - Debounce rapid input to avoid excessive validation calls.\n    - Disable submit button while any async validation is pending.",
    "File Upload with Progress": "Implement a file upload component with progress tracking.\n    Requirements:\n    - Create a drag-and-drop zone with click-to-browse fallback.\n    - Show file preview (thumbnail for images, icon for others).\n    - Display upload progress bar with percentage for each file.\n    - Simulate upload progress using XMLHttpRequest or fetch with mock delay.\n    - Support multiple file selection and queue management.\n    - Add cancel upload and remove file functionality.",
    "Parallax Scrolling": "Implement parallax scrolling effects for visual depth.\n    Requirements:\n    - Create multiple layers that move at different speeds on scroll.\n    - Apply parallax to background images, floating elements, or text.\n    - Use transform: translate3d for GPU-accelerated smooth performance.\n    - Implement both vertical and optional horizontal parallax.\n    - Add fade-in/scale effects for elements entering viewport.\n    - Ensure graceful degradation on mobile (reduce or disable effects).",
    "Page Transitions": "Implement smooth page/view transitions for SPA-like experience.\n    Requirements:\n    - Create animated transitions between different content sections/pages.\n    - Implement multiple transition types (fade, slide, zoom, flip).\n    - Add enter/exit animations that coordinate timing.\n    - Use CSS transitions/animations or Web Animations API.\n    - Handle browser back/forward with appropriate reverse animations.\n    - Add loading state during content fetch if applicable.",
    "Particle Effects": "Implement interactive particle effects for visual enhancement.\n    Requirements:\n    - Create a canvas-based particle system with configurable particle count.\n    - Implement particle physics (velocity, gravity, friction, bounce).\n    - Add mouse/touch interaction (particles follow cursor, explode on click).\n    - Support different particle shapes (circles, squares, custom images).\n    - Implement connection lines between nearby particles (constellation effect).\n    - Optimize performance with requestAnimationFrame and particle pooling.",
    "Skeleton Loading": "Implement skeleton loading screens for improved perceived performance.\n    Requirements:\n    - Create skeleton placeholders matching the layout of actual content.\n    - Add shimmer/pulse animation effect on skeleton elements.\n    - Implement skeletons for various content types (text, images, cards, lists).\n    - Smooth transition from skeleton to actual content when loaded.\n    - Support different skeleton variants based on content type.\n    - Ensure skeletons are accessible (aria-busy, aria-label).",
    "Shopping Cart": "Implement a fully functional shopping cart system.\n    Requirements:\n    - Add \"Add to Cart\" buttons on product items with quantity selector.\n    - Create cart sidebar/dropdown showing added items with thumbnails.\n    - Implement quantity adjustment (+/-) and remove item functionality.\n    - Calculate and display subtotal, tax, and total in real-time.\n    - Persist cart data in localStorage across page refreshes.\n    - Add cart badge showing item count on cart icon.",
    "User Authentication": "Implement a complete user authentication UI flow.\n    Requirements:\n    - Create login form with email/username and password fields.\n    - Create registration form with password confirmation and terms checkbox.\n    - Implement \"Forgot Password\" flow with email input.\n    - Add form validation with appropriate error messages.\n    - Show/hide password toggle functionality.\n    - Simulate auth state with localStorage and update UI accordingly (logged in/out).",
    "Multi-step Wizard": "Implement a multi-step form wizard with progress tracking.\n    Requirements:\n    - Create a step indicator showing current step and total steps.\n    - Implement step navigation (Next, Previous, Skip if allowed).\n    - Validate each step before allowing progression.\n    - Show step completion status (completed, current, upcoming).\n    - Persist form data across steps (don't lose data on back navigation).\n    - Add final review step showing all entered data before submission.",
    "Notification Center": "Implement a notification center with real-time alerts.\n    Requirements:\n    - Create notification bell icon with unread count badge.\n    - Implement dropdown panel showing notification list.\n    - Support different notification types (info, success, warning, error).\n    - Add mark as read (individual and mark all) functionality.\n    - Implement notification grouping by date or type.\n    - Add simulated real-time notifications using setInterval or mock events.",
    "Dark Mode Toggle": "Implement a dark/light theme switcher using CSS custom properties.\n    Requirements:\n    - Define CSS variables for background, text, border, and accent colors in :root and [data-theme='dark'].\n    - Create a toggle button (sun/moon icon) in the header that switches themes.\n    - Apply smooth transition on all color changes (transition: background-color 0.3s, color 0.3s).\n    - Persist the user's preference in localStorage.\n    - Respect prefers-color-scheme media query as default on first visit.\n    - Ensure all page components respond correctly to the theme change.",
    "Accordion": "Implement collapsible accordion panels for organizing content.\n    Requirements:\n    - Create a list of header/content panel pairs that expand/collapse on header click.\n    - Only one panel open at a time (exclusive mode) or allow multiple (configurable).\n    - Animate the expand/collapse with smooth height transition (max-height or CSS grid).\n    - Show open/close indicator (chevron/plus icon) that rotates on toggle.\n    - Support keyboard navigation (Enter/Space to toggle, arrow keys between headers).\n    - Add aria-expanded and aria-controls for accessibility.",
    "Modal Dialog": "Implement a modal dialog system with backdrop overlay.\n    Requirements:\n    - Create a centered modal with semi-transparent backdrop overlay.\n    - Close on ESC key press, backdrop click, or close button.\n    - Implement focus trap (Tab cycles only within modal while open).\n    - Add open/close animation (fade + scale or slide).\n    - Prevent body scroll when modal is open (overflow: hidden on body).\n    - Support multiple modal sizes (small, medium, large) via CSS classes.",
    "Tooltip": "Implement a tooltip/popover component for contextual information.\n    Requirements:\n    - Show tooltip on hover (with 200ms delay) or focus on trigger element.\n    - Position tooltip automatically (top/bottom/left/right) based on available space.\n    - Add a small arrow/caret pointing to the trigger element.\n    - Support both plain text and rich HTML content in tooltip.\n    - Dismiss on mouse leave, blur, ESC, or scroll.\n    - Ensure tooltip stays within viewport bounds (flip if necessary).",
    "Breadcrumb Navigation": "Implement dynamic breadcrumb navigation reflecting page hierarchy.\n    Requirements:\n    - Display a horizontal breadcrumb trail showing the current navigation path.\n    - Use separator characters (/ or >) between items.\n    - Make all items except the last one clickable links.\n    - Highlight the current (last) item as non-clickable text.\n    - Add structured data (schema.org BreadcrumbList) for SEO.\n    - Truncate long paths with ellipsis on mobile (show first, last, and ellipsis).",
    "Tabs": "Implement a tabbed content interface with keyboard accessibility.\n    Requirements:\n    - Create a horizontal tab bar with multiple tab buttons.\n    - Show/hide corresponding tab panels when a tab is clicked.\n    - Style the active tab distinctly (border-bottom, background change, or underline).\n    - Support keyboard navigation (arrow keys between tabs, Enter/Space to select).\n    - Implement proper ARIA roles (tablist, tab, tabpanel) with aria-selected.\n    - Add smooth fade or slide transition when switching panels.",
    "Toast Notifications": "Implement an auto-dismissing toast notification system.\n    Requirements:\n    - Display toast messages at a fixed screen position (top-right or bottom-right).\n    - Support multiple types: success (green), error (red), warning (yellow), info (blue).\n    - Auto-dismiss after configurable duration (default 5 seconds) with progress bar.\n    - Stack multiple toasts vertically with smooth entrance/exit animations.\n    - Allow manual dismiss via close button.\n    - Pause auto-dismiss timer on hover.",
    "Star Rating": "Implement an interactive star rating widget.\n    Requirements:\n    - Display 5 clickable star icons in a row.\n    - Highlight stars on hover to preview the rating (fill stars up to cursor).\n    - On click, set the rating and keep stars filled.\n    - Support half-star precision (optional).\n    - Show numeric rating value next to the stars.\n    - Add visual feedback animation on selection (brief scale pulse).\n    - Make it accessible with aria-label and keyboard support (arrow keys).",
    "Copy to Clipboard": "Implement copy-to-clipboard functionality with visual feedback.\n    Requirements:\n    - Add a copy button next to code blocks or text content.\n    - Use navigator.clipboard.writeText() API with fallback for older browsers.\n    - Show visual confirmation on copy (icon changes to checkmark, tooltip says 'Copied!').\n    - Revert the icon/text back to original state after 2 seconds.\n    - Support copying from multiple elements on the same page.\n    - Style the button to blend with the content context (inline or floating).",
    "Back to Top": "Implement a smooth scroll-to-top button.\n    Requirements:\n    - Show a floating button (fixed position, bottom-right) when user scrolls down >300px.\n    - Hide the button with fade animation when near the top.\n    - On click, smoothly scroll to page top using window.scrollTo with behavior: 'smooth'.\n    - Add a subtle hover effect (scale or shadow increase).\n    - Use an upward arrow icon inside a circular button.\n    - Ensure the button doesn't overlap important content (add appropriate z-index).",
    "Cookie Consent": "Implement a GDPR-compliant cookie consent banner.\n    Requirements:\n    - Display a fixed banner at the bottom of the page on first visit.\n    - Include 'Accept All', 'Reject All', and 'Customize' buttons.\n    - 'Customize' opens a panel with toggle switches for cookie categories (Essential, Analytics, Marketing).\n    - Store the user's choice in localStorage; don't show banner again once decided.\n    - Add a small 'Cookie Settings' link in the footer to re-open preferences.\n    - Animate the banner entrance (slide up) and exit (slide down).",
    "Responsive Navigation": "Implement a responsive navigation with mobile hamburger menu.\n    Requirements:\n    - On desktop (>768px): show a horizontal nav bar with all menu items visible.\n    - On mobile (<=768px): collapse nav into a hamburger icon (three lines).\n    - Clicking hamburger opens a full-height sidebar or dropdown with menu items.\n    - Animate the menu open/close (slide-in from left or fade-down).\n    - Close the menu on link click, outside click, or ESC key.\n    - Add smooth transition for the hamburger icon to X (close) transformation.",
    "Sticky Header": "Implement a sticky header with scroll spy highlighting.\n    Requirements:\n    - Make the header fixed at the top when scrolling past its natural position.\n    - Add a subtle shadow or border-bottom when the header becomes sticky.\n    - Implement scroll spy: highlight the nav link corresponding to the currently visible section.\n    - Use Intersection Observer to detect which section is in view.\n    - Smooth scroll to section when clicking nav links (scroll-behavior or JS).\n    - Optionally shrink/transform the header on scroll (smaller height, logo resize).",
    "Search Autocomplete": "Implement a search input with dropdown autocomplete suggestions.\n    Requirements:\n    - Create a search input field with a search icon.\n    - Show a dropdown of matching suggestions as the user types.\n    - Debounce input to avoid excessive filtering (300ms delay).\n    - Highlight the matching text portion in each suggestion.\n    - Support keyboard navigation in the dropdown (arrow up/down, Enter to select, ESC to close).\n    - Show 'No results found' when no matches; show recent searches when input is empty.",
    "Image Lightbox": "Implement a full-screen image lightbox gallery.\n    Requirements:\n    - Display a grid/list of thumbnail images that open in lightbox on click.\n    - Lightbox shows the full-size image centered on a dark backdrop.\n    - Add previous/next navigation arrows to browse through images.\n    - Support keyboard navigation (arrow keys, ESC to close).\n    - Add smooth zoom/fade animation on open and close.\n    - Show image caption and counter (e.g., '3 of 12') below the image.",
    "Countdown Timer": "Implement an animated countdown timer display.\n    Requirements:\n    - Display days, hours, minutes, and seconds in separate styled boxes.\n    - Update every second using setInterval with smooth digit transitions.\n    - Add flip or fade animation when digits change.\n    - Accept a target date/time as configuration.\n    - Show 'Time expired!' or trigger an action when countdown reaches zero.\n    - Style with clear visual hierarchy (large numbers, small labels below).",
    "Color Picker": "Implement an interactive color picker component.\n    Requirements:\n    - Create a color spectrum canvas (hue/saturation gradient) for visual selection.\n    - Add a hue slider bar for selecting the base hue.\n    - Display the selected color as a preview swatch.\n    - Show hex, RGB, and HSL values that update in real-time.\n    - Allow manual input of hex/RGB values with validation.\n    - Add preset color swatches for quick selection.\n    - Copy hex value to clipboard on click of the preview swatch.",
    "Date Picker": "Implement a calendar-based date picker component.\n    Requirements:\n    - Create a text input that opens a calendar dropdown on click/focus.\n    - Display a month grid with selectable day cells.\n    - Add month/year navigation (previous/next arrows, month/year dropdowns).\n    - Highlight today's date and the selected date distinctly.\n    - Disable dates outside a valid range if configured.\n    - Close the calendar on date selection or outside click.\n    - Format and display the selected date in the input field.",
    "Carousel": "Implement a content carousel/slider with navigation controls.\n    Requirements:\n    - Display one slide at a time (or multiple in a row) with smooth horizontal sliding.\n    - Add previous/next arrow buttons on the sides.\n    - Add dot indicators below showing the current slide position.\n    - Support auto-play with configurable interval and pause-on-hover.\n    - Implement infinite loop (wrap from last to first slide seamlessly).\n    - Add swipe/drag support for touch devices.\n    - Ensure smooth CSS transition between slides.",
    "Keyboard Shortcuts": "Implement a keyboard shortcuts system with help overlay.\n    Requirements:\n    - Register global keyboard shortcuts (e.g., Ctrl+K for search, ? for help).\n    - Create a help overlay (modal) showing all available shortcuts in a grid.\n    - Toggle the help panel with '?' key press.\n    - Prevent shortcuts from firing when user is typing in input/textarea fields.\n    - Group shortcuts by category (Navigation, Actions, Editing).\n    - Show visual key badges (styled kbd elements) next to each shortcut description.",
    "Context Menu": "Implement a custom right-click context menu.\n    Requirements:\n    - Override the default browser context menu on specific elements or the page.\n    - Show a styled dropdown menu at the cursor position on right-click.\n    - Include menu items with icons, text, and optional keyboard shortcut hints.\n    - Support nested submenus (hover to expand).\n    - Close the menu on item click, outside click, or ESC.\n    - Position the menu to stay within viewport bounds (flip if near edge).",
    "Lazy Loading Images": "Implement lazy loading for images with placeholder effects.\n    Requirements:\n    - Defer loading of off-screen images until they enter the viewport.\n    - Use Intersection Observer API to detect visibility.\n    - Show a blurred low-resolution placeholder or solid color box while loading.\n    - Animate the transition from placeholder to full image (fade-in).\n    - Add loading='lazy' attribute as progressive enhancement.\n    - Handle error state with a fallback broken-image indicator.",
    "Print Stylesheet": "Implement an optimized print layout using CSS @media print.\n    Requirements:\n    - Hide navigation, footer, ads, and interactive elements when printing.\n    - Expand all collapsed/accordion content so nothing is hidden.\n    - Force a white background with black text for readability and ink saving.\n    - Display URLs after links in parentheses (content: ' (' attr(href) ')').\n    - Add page-break-inside: avoid on cards, images, and tables.\n    - Add a 'Print this page' button that triggers window.print().",
    "Undo Redo": "Implement an undo/redo system for user actions.\n    Requirements:\n    - Track user modifications in a history stack (array of state snapshots or commands).\n    - Add Undo (Ctrl+Z) and Redo (Ctrl+Shift+Z or Ctrl+Y) keyboard shortcuts.\n    - Create visible Undo/Redo buttons in the UI with disabled state when unavailable.\n    - Support at least 20 levels of undo history.\n    - Clear the redo stack when a new action is performed after undoing.\n    - Show a brief indicator or toast when undo/redo is performed.",
}

# Interaction-first additions for the 0805 supplement.  The older catalog is
# kept intact for compatibility; these entries make the atomic interaction
# requirements explicit instead of relying on a compound component such as a
# data table to happen to include sorting, filtering, or pagination.
_INTERACTION_EDIT_TASK_DESCRIPTIONS: dict[str, str] = {
    "Click State": "Add a meaningful click target. The default and clicked states must be visually distinct, the click must update observable DOM/ARIA state, and the surrounding page must remain unchanged.",
    "Hover State": "Add a meaningful hover interaction. Keep the hovered state stable long enough to capture, reveal or change visible content, and provide the same information on keyboard focus.",
    "Focus State": "Add a keyboard-reachable focus interaction with a conspicuous focus indicator and an observable semantic state. Do not use color alone.",
    "Input-driven Update": "Add an input whose typed value changes a visible result, preview, count, or suggestion list. Include empty and populated states and deterministic local data.",
    "Select Control": "Add a select/listbox control whose chosen option visibly updates related content. Include a stable default option and at least two deterministic alternatives.",
    "Toggle Control": "Add an accessible binary toggle with visibly different on/off states, correct aria-checked or aria-pressed state, and deterministic local persistence when appropriate.",
    "Tab Switch": "Add a tab switch with distinct panels, active styling, click and arrow-key support, and observable aria-selected state.",
    "Dropdown": "Add a dropdown/menu with closed, open, selected, and dismissed states. Support click, keyboard operation, outside click, and Escape.",
    "Sort Control": "Add deterministic ascending and descending sorting. The visible order and active sort direction must both change after activation.",
    "Filter Control": "Add a deterministic filter that changes the visible result set, result count, and active-filter indicator, including a no-results or reset path.",
    "Pagination": "Add deterministic pagination with previous/next and page selection. The visible item slice and current-page indicator must change.",
    "Navigation Flow": "Add same-origin navigation between existing project pages. The destination must visibly differ, links must work over local HTTP, and a return path must preserve relevant local state.",
    "Form Validation": "Add form validation with invalid and valid paths, accessible inline messages, visible error/success states, and submission prevention until valid.",
    "Conditional Rendering": "Add a user-controlled condition that inserts, removes, or replaces a meaningful visible region while preserving unrelated content.",
    "Loading State": "Add a deterministic, capturable loading state followed by a settled success or empty result. Do not depend on a real backend or remote timer source.",
    "Animation State": "Add a user-triggered animation with deterministic before and after keyframes, reduced-motion handling, and a stable final state suitable for screenshots.",
}

_EDIT_TASK_DESCRIPTIONS.update(_INTERACTION_EDIT_TASK_DESCRIPTIONS)
for _interaction_task in _INTERACTION_EDIT_TASK_DESCRIPTIONS:
    if _interaction_task not in _EDIT_TASKS:
        _EDIT_TASKS.append(_interaction_task)

# Balanced construction profiles distilled from the four requested sources.
# FrontendBench remains a capability reference only; generated rows must not
# claim that unpublished benchmark examples were used as source instances.
WEBCOMPASS_EDIT_TASKS = (
    "Async Form Validation",
    "Data Table",
    "Drag & Drop Interface",
    "File Upload with Progress",
    "Infinite Scroll",
    "Multi-step Wizard",
    "Notification Center",
    "Page Transitions",
    "Parallax Scrolling",
    "Particle Effects",
    "Real-time Dashboard",
    "Rich Text Editor",
    "Shopping Cart",
    "Skeleton Loading",
    "Tree View",
    "User Authentication",
)


_EDIT_BENCHMARK_PROFILES: dict[str, tuple[str, ...]] = {
    "interaction2code": (
        "Click State", "Hover State", "Input-driven Update", "Select Control",
        "Toggle Control", "Dropdown", "Modal Dialog", "Tooltip", "Carousel",
        "Conditional Rendering", "Animation State", "Navigation Flow",
    ),
    "artifactsbench": (
        "Click State", "Input-driven Update", "Select Control", "Drag & Drop Interface",
        "Sort Control", "Filter Control", "Pagination", "Form Validation",
        "Conditional Rendering", "Loading State", "Toast Notifications", "Modal Dialog",
    ),
    "frontendbench": (
        "Hover State", "Focus State", "Toggle Control", "Tab Switch", "Accordion",
        "Dropdown", "Tooltip", "Carousel", "Sort Control", "Filter Control",
        "Form Validation", "Animation State",
    ),
    "webcompass": WEBCOMPASS_EDIT_TASKS,
}

WEBCOMPASS_REPAIR_TYPES = (
    "Occlusion",
    "Crowding",
    "Text Overlap",
    "Alignment",
    "Color Contrast",
    "Overflow",
    "Sizing Proportion",
    "Loss of Interactivity",
    "Semantic Error",
    "Nesting Error",
    "Missing Attributes",
)

_DEFECT_TYPES: list[str] = list(WEBCOMPASS_REPAIR_TYPES)

_DEFECT_DESCRIPTIONS: dict[str, str] = {
    "Occlusion": "Increase the z-index of element A so that it covers element B.\n    For example, make a modal overlay cover important content, or make a fixed header cover interactive elements.",
    "Crowding": "Remove margin or padding between elements A and B, or shrink their parent container size.\n    For example, remove spacing between navigation items, or collapse the gap between form fields.",
    "Text Overlap": "Reduce the width or line-height of a text container, or position two text containers at the same location.\n    For example, make text overflow its container and overlap with adjacent elements.",
    "Alignment": "Adjust the left/top properties of element A so it's not aligned with the grid or sibling element B.\n    For example, misalign navigation items, or offset a button from its expected position.",
    "Color Contrast": "Set text color to a value similar to the background color (e.g., light gray text on white background).\n    For example, make body text nearly invisible, or reduce contrast of important labels.",
    "Overflow": "Add excessive content to a fixed height/width container and set overflow: visible or remove overflow handling.\n    For example, add too much text to a card component causing it to break layout.",
    "Sizing Proportion": "Set an image to extreme dimensions (e.g., width: 10px, height: 200px), or make a container unnecessarily huge.\n    For example, distort an image aspect ratio, or make a small icon take up entire width.",
    "Loss of Interactivity": "Disable a button element, or use CSS pointer-events: none to make a link unclickable.\n    For example, add disabled attribute to submit button, or block clicks on navigation links.",
    "Semantic Error": "Replace heading <h1> element with <div> element styled the same way.\n    For example, convert semantic nav to div, or replace button with styled span.",
    "Nesting Error": "Place an <a> tag inside another <a> tag, or put a <div> inside a <p> tag.\n    For example, nest block elements inside inline elements incorrectly.",
    "Missing Attributes": "Remove alt attribute from <img> elements, or remove aria-label from form inputs.\n    For example, remove accessibility attributes, or remove required form attributes.",
}

_REPAIR_FAMILY_DESCRIPTIONS: dict[str, str] = {
    "Runtime Repair": "Create a locally reproducible runtime failure in existing frontend behavior, such as an exception in an event path, a broken local import/reference, or invalid state access. Preserve enough of the page to diagnose and repair it; do not create an infrastructure or remote-network failure.",
    "Visual Repair": "Create a conspicuous visual defect in an existing component or layout while keeping the page runnable. The defective and repaired states must have an observable screenshot difference.",
    "Interaction Repair": "Break an existing click, hover, focus, input, selection, toggle, drag/drop, form, or navigation behavior while leaving its trigger visible. The defect must be reproducible with a bounded browser action sequence.",
    "Quality Refinement": "Create a measurable frontend quality regression, such as broken keyboard access, missing accessible state, poor responsive behavior, confusing feedback, or unstable loading/animation behavior. The issue must be independently auditable, not merely a subjective request to beautify the page.",
}

_REPAIR_FAMILY_TITLE = {
    "runtime_repair": "Runtime Repair",
    "visual_repair": "Visual Repair",
    "interaction_repair": "Interaction Repair",
    "quality_refinement": "Quality Refinement",
}

_REPAIR_LEAF_DESCRIPTIONS: dict[str, str] = {
    defect_type: (
        f"Inject a controlled, independently reproducible {defect_type.replace('_', ' ')} "
        f"defect under {metadata['subfamily'].replace('_', ' ')}. "
        f"{_REPAIR_FAMILY_DESCRIPTIONS[_REPAIR_FAMILY_TITLE[str(metadata['family'])]]}"
    )
    for defect_type, metadata in REPAIR_DEFECT_TAXONOMY.items()
}

for _repair_family in _REPAIR_FAMILY_DESCRIPTIONS:
    if _repair_family not in _DEFECT_TYPES:
        _DEFECT_TYPES.append(_repair_family)
_DEFECT_DESCRIPTIONS.update(_REPAIR_FAMILY_DESCRIPTIONS)


def load_edit_catalog(profile: str = "all") -> tuple[list[str], dict[str, str]]:
    if profile == "all":
        task_types = list(_EDIT_TASKS)
    elif profile in _EDIT_BENCHMARK_PROFILES:
        task_types = list(_EDIT_BENCHMARK_PROFILES[profile])
    else:
        raise ValueError(
            f"unknown edit benchmark profile {profile!r}; "
            f"expected all or one of {sorted(_EDIT_BENCHMARK_PROFILES)}"
        )
    return task_types, {task_type: _EDIT_TASK_DESCRIPTIONS[task_type] for task_type in task_types}


def load_repair_catalog(profile: str = "all") -> tuple[list[str], dict[str, str]]:
    if profile == "all":
        task_types = [*list(_DEFECT_TYPES), *list(REPAIR_DEFECT_TAXONOMY)]
    elif profile == "taxonomy":
        task_types = list(REPAIR_DEFECT_TAXONOMY)
    elif profile == "family":
        task_types = list(_REPAIR_FAMILY_DESCRIPTIONS)
    elif profile in {"legacy", "webcompass"}:
        task_types = [item for item in _DEFECT_TYPES if item not in _REPAIR_FAMILY_DESCRIPTIONS]
    else:
        raise ValueError("repair profile must be all, taxonomy, family, legacy, or webcompass")
    descriptions = {**_DEFECT_DESCRIPTIONS, **_REPAIR_LEAF_DESCRIPTIONS}
    return task_types, {task_type: descriptions[task_type] for task_type in task_types}


def _normalize_whitespace(text: str) -> str:
    """Collapse all whitespace runs to single spaces for fuzzy matching."""
    return re.sub(r"\s+", " ", text.strip())


def _fuzzy_replace(code: str, search_text: str, replace_text: str) -> str | None:
    """Try whitespace-normalized matching as fallback.

    Finds the substring in code whose normalized form matches normalized search_text,
    then replaces that exact substring with replace_text.
    """
    norm_search = _normalize_whitespace(search_text)
    if not norm_search:
        return None
    # Sliding window: normalize chunks of code and look for match
    # Use a line-based approach for efficiency
    code_lines = code.split("\n")
    search_lines = search_text.strip().split("\n")
    n_search = len(search_lines)
    for start in range(len(code_lines) - n_search + 1):
        candidate = "\n".join(code_lines[start : start + n_search])
        if _normalize_whitespace(candidate) == norm_search:
            return code.replace(candidate, replace_text, 1)
    # Also try with varying window sizes (+/- 2 lines)
    for delta in range(1, 3):
        for start in range(len(code_lines)):
            for size in (n_search + delta, n_search - delta):
                if size <= 0 or start + size > len(code_lines):
                    continue
                candidate = "\n".join(code_lines[start : start + size])
                if _normalize_whitespace(candidate) == norm_search:
                    return code.replace(candidate, replace_text, 1)
    return None


def apply_search_replace_local(
    code_list: list[dict[str, str]], modified_files: list[dict[str, str]], strict_mode: bool = True
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """Local copy of web_coding_demo.utils.apply_search_replace without heavyweight image deps."""
    result_code = []
    code_map = {item["path"]: item["code"] for item in code_list}
    errors: list[dict[str, Any]] = []
    blocks_by_path: dict[str, list[dict[str, str]]] = {}
    for block in modified_files:
        blocks_by_path.setdefault(block["path"], []).append(block)

    for path, blocks in blocks_by_path.items():
        if path not in code_map:
            if blocks and blocks[0]["search"] == "":
                code_map[path] = ""
            else:
                error_msg = f"File path not found in code_list: {path}"
                if strict_mode:
                    raise ValueError(error_msg)
                errors.extend(
                    {"path": path, "block_index": idx, "error_type": "path_not_found", "error": error_msg}
                    for idx, _ in enumerate(blocks)
                )
                continue

        code = code_map[path]
        for block_idx, block in enumerate(blocks):
            search_text = block["search"]
            replace_text = block["replace"]
            if search_text.strip() == replace_text.strip():
                error_msg = f"Search and replace are identical in {path} (block {block_idx})."
                if strict_mode:
                    raise ValueError(error_msg)
                errors.append(
                    {
                        "path": path,
                        "block_index": block_idx,
                        "error_type": "identical_search_replace",
                        "error": error_msg,
                    }
                )
                continue
            if search_text == "" and code == "":
                code = replace_text
            elif search_text in code:
                code = code.replace(search_text, replace_text, 1)
            elif _fuzzy_replace(code, search_text, replace_text) is not None:
                code = _fuzzy_replace(code, search_text, replace_text)
            else:
                error_msg = (
                    f"Failed to apply search/replace in {path} (block {block_idx}).\n"
                    f"Search text (first 200 chars): {search_text[:200]}...\n"
                    "This may indicate LLM generated invalid modifications."
                )
                if strict_mode:
                    raise ValueError(error_msg)
                errors.append(
                    {"path": path, "block_index": block_idx, "error_type": "search_not_found", "error": error_msg}
                )
                continue
        code_map[path] = code

    existing_paths = {item["path"] for item in code_list}
    for item in code_list:
        new_item = item.copy()
        if item["path"] in code_map:
            new_item["code"] = code_map[item["path"]]
        result_code.append(new_item)
    for path, content in code_map.items():
        if path not in existing_paths:
            result_code.append({"path": path, "code": content})
    return result_code, errors


def apply_search_replace_exact(
    code_list: list[dict[str, str]],
    modified_files: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Apply sequential patches only when each search has one exact match."""
    code_map = {item["path"]: item["code"] for item in code_list}
    for index, patch in enumerate(modified_files):
        path = str(patch.get("path", ""))
        search = patch.get("search")
        replace = patch.get("replace")
        if path not in code_map:
            raise ValueError(f"patch {index}: unknown file path {path!r}")
        if not isinstance(search, str) or not search:
            raise ValueError(f"patch {index}: search must be non-empty")
        if not isinstance(replace, str) or search == replace:
            raise ValueError(f"patch {index}: replace must differ from search")
        matches = code_map[path].count(search)
        if matches != 1:
            raise ValueError(
                f"patch {index}: search must match exactly once in {path}; got {matches}"
            )
        code_map[path] = code_map[path].replace(search, replace, 1)
    return [{**item, "code": code_map[item["path"]]} for item in code_list]


def validate_patch_round_trip(
    visible_clean: list[dict[str, str]],
    full_clean: list[dict[str, str]],
    forward_patches: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Validate exact patches on both the model-visible and full render code."""
    visible_changed = apply_search_replace_exact(visible_clean, forward_patches)
    full_changed = apply_search_replace_exact(full_clean, forward_patches)
    reverse = [
        {**patch, "search": patch["replace"], "replace": patch["search"]}
        for patch in reversed(forward_patches)
    ]
    if apply_search_replace_exact(visible_changed, reverse) != visible_clean:
        raise ValueError("visible-code patch round trip failed")
    if apply_search_replace_exact(full_changed, reverse) != full_clean:
        raise ValueError("full-code patch round trip failed")
    return visible_changed, full_changed


def validate_patch_paths_for_context(generation_data: dict[str, Any], patches: list[dict[str, str]]) -> None:
    """Keep oversized-project patches inside the HTML-only construction contract."""
    if generation_data.get("context_mode") != "html_only":
        return
    allowed = {item["path"] for item in generation_data.get("dst_code", [])}
    for patch in patches:
        path = str(patch.get("path", ""))
        if path not in allowed or Path(path).suffix.lower() not in {".html", ".htm"}:
            raise ValueError(f"HTML-only context cannot patch non-HTML or unseen path: {path}")


def validate_multipage_patch_scope(
    generation_data: dict[str, Any], patches: list[dict[str, str]], *, required: bool
) -> None:
    """Require a real cross-page effect while allowing shared code changes."""
    if not required:
        return
    project_pages = set(generation_data.get("project_pages") or [])
    project_documents = set(
        generation_data.get("project_documents")
        or [page.split("#", 1)[0] for page in project_pages]
    )
    if len(project_documents) < 2:
        raise ValueError("cross-page task requires at least two independent HTML documents")
    paths = {str(patch.get("path", "")) for patch in patches}
    touched_html_pages = paths & project_documents
    touched_shared_code = {
        path
        for path in paths
        if Path(path).suffix.lower() in {".css", ".js", ".jsx", ".ts", ".tsx"}
    }
    if len(touched_html_pages) < 2 and not touched_shared_code:
        raise ValueError(
            "cross-page task must patch at least two HTML documents or shared CSS/JS/TS code"
        )


def affected_pages_from_patches(
    generation_data: dict[str, Any], patches: list[dict[str, str]]
) -> list[str]:
    """Return the physical documents whose rendered state may be changed by patches.

    Direct HTML patches affect those documents. Any non-HTML source/style patch is
    conservatively treated as shared runtime code and therefore affects every
    physical document; the browser diff later decides which of those candidates
    changed observably.
    """
    project_documents = sorted(set(
        generation_data.get("project_documents")
        or [page.split("#", 1)[0] for page in generation_data.get("project_pages", [])]
    ))
    paths = {str(patch.get("path", "")).split("#", 1)[0] for patch in patches}
    direct = set(project_documents) & paths
    has_shared_runtime_patch = any(
        path and Path(path).suffix.lower() not in {".html", ".htm"}
        for path in paths
    )
    affected = set(project_documents if has_shared_runtime_patch else direct)
    if not affected:
        raise ValueError("patches do not identify an affected physical page")
    return sorted(affected)


def validate_screenshot_page_coverage(
    screens: list[dict[str, Any]], affected_pages: list[str]
) -> None:
    """Require at least one screenshot for every page modified by an image task."""
    captured = {
        str(item.get("page", "")).split("#", 1)[0]
        for item in screens
        if str(item.get("page", "")).strip()
    }
    missing = sorted(set(affected_pages) - captured)
    if missing:
        raise ValueError(f"screenshots do not cover affected pages: {missing}")


def requires_cross_page(generation_data: dict[str, Any], requested_scope: str) -> bool:
    """Treat every genuinely multi-page source as cross-page, including `any` runs."""
    return requested_scope == "mp" or generation_data.get("page_scope") == "mp"


def patch_scope_instruction(generation_data: dict[str, Any]) -> str:
    if generation_data.get("context_mode") != "html_only":
        return ""
    return """CONTEXT SCOPE (MANDATORY): This oversized project is shown in HTML-only mode.
Generate patches only for existing .html/.htm files present below. Do not create or patch CSS,
JavaScript, bundle, or other files. Existing dependencies remain in the rendered project but are
intentionally unavailable for patch construction.\n\n"""


class ConstructionFailure(RuntimeError):
    """Construction failed after one or more paid attempts; retain audit evidence."""

    def __init__(self, message: str, attempts: list[dict[str, Any]]):
        super().__init__(message)
        self.llm_attempts = attempts


class LocalSearchReplaceSynthesizer:
    """Dependency-light adapter for web_coding_demo.synthetic.synthesizer.BaseSynthesizer."""

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        model: str = "gpt-4o",
        max_tokens: int = 8192,
        max_retries: int = 1,
    ):
        from openai import OpenAI

        # Real 40K-code requests regularly exceed two minutes.
        self.client = OpenAI(api_key=api_key, base_url=base_url,
                             timeout=float(os.environ.get("CONSTRUCT_API_TIMEOUT", "600")), max_retries=0)
        self.base_url = base_url or ""
        self.model = model
        self.max_tokens = max_tokens
        self.max_retries = max_retries

    @staticmethod
    def _retryable_transport_error(exc: Exception) -> bool:
        if type(exc).__name__ in {
            "APIConnectionError",
            "APITimeoutError",
            "RateLimitError",
            "InternalServerError",
        }:
            return True
        status = getattr(exc, "status_code", None)
        return isinstance(status, int) and (status == 429 or status >= 500)

    def _chat_completion(self, messages: list[dict[str, Any]]):
        """Retry transient transport failures without consuming validation attempts."""
        # Paid requests are single-attempt by default. A value above one is
        # only supplied for a run with explicit retry authorization.
        attempts = max(1, int(os.environ.get("CONSTRUCT_TRANSPORT_ATTEMPTS", "1")))
        backoff_base = max(0.0, float(os.environ.get("CONSTRUCT_TRANSPORT_BACKOFF_BASE", "2")))
        stream_response = os.environ.get("CONSTRUCT_STREAM", "0").strip().lower() in {
            "1", "true", "yes", "on",
        }
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                if attempts > 1:
                    print(f"LLM transport request started {attempt}/{attempts}", flush=True)
                request = {
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": self.max_tokens,
                    "stream": stream_response,
                }
                extra_body: dict[str, Any] = {}
                if "dashscope.aliyuncs.com" in self.base_url:
                    extra_body["enable_thinking"] = os.environ.get(
                        "CONSTRUCT_ENABLE_THINKING", "0"
                    ).strip().lower() in {
                        "1", "true", "yes", "on"
                    }
                thinking_type = os.environ.get("CONSTRUCT_THINKING_TYPE", "").strip()
                if thinking_type:
                    extra_body["thinking"] = {"type": thinking_type}
                if extra_body:
                    request["extra_body"] = extra_body
                response = self.client.chat.completions.create(
                    **request,
                )
                if not stream_response:
                    if attempts > 1:
                        usage = getattr(response, "usage", None)
                        print(f"LLM transport request succeeded {attempt}/{attempts}; usage={usage}", flush=True)
                    return response
                parts: list[str] = []
                for chunk in response:
                    delta = chunk.choices[0].delta.content if chunk.choices else None
                    if delta:
                        parts.append(delta)
                content = "".join(parts).strip()
                if not content:
                    raise ValueError("Empty streamed response content from LLM.")
                if attempts > 1:
                    print(f"LLM transport request succeeded {attempt}/{attempts}; usage=not_reported", flush=True)
                return content
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if not self._retryable_transport_error(exc) or attempt >= attempts:
                    if attempts > 1:
                        print(f"LLM transport request failed {attempt}/{attempts}: {type(exc).__name__}; usage=unknown", flush=True)
                    raise
                delay = (backoff_base ** (attempt - 1) if backoff_base else 0.0) + random.random()
                print(
                    f"Transient LLM transport failure {attempt}/{attempts}: "
                    f"{type(exc).__name__}: {exc}; retrying in {delay:.1f}s"
                )
                time.sleep(delay)
        raise RuntimeError(f"transport retry loop exhausted: {last_error}") from last_error

    def format_code_context(
        self,
        code_list: list[dict[str, str]],
        resources: list[dict[str, Any]] | None = None,
        max_tokens: int = 200_000,
    ) -> str:
        """Build XML context for LLM — all code files + resources file list.

        Token estimation: ~1 token per 4 chars for ASCII code.
        """
        max_chars = max_tokens * 4
        context = "<code_context>\n"
        remaining = max_chars
        for item in sorted(code_list, key=lambda it: (_code_priority(it["path"]), it["path"])):
            if remaining <= 0:
                break
            code = _truncate_text(item["code"], remaining)
            context += f'<file path="{item["path"]}">\n{code}\n</file>\n'
            remaining -= len(code)
        context += "</code_context>"

        if resources:
            context += "\n<resources>\n"
            for res in resources:
                context += f'  <file path="{res["path"]}" type="{res.get("type", "image")}" />\n'
            context += "</resources>"

        return context

    def parse_llm_response(self, response_text: str) -> dict[str, Any]:
        response_text = strip_markdown_fence(response_text)
        desc_match = re.search(r"<description>(.*?)</description>", response_text, re.DOTALL)
        if not desc_match:
            raise ValueError("No <description> tag found in LLM response")
        description = json.loads(desc_match.group(1).strip())
        if isinstance(description, list):
            for item in description:
                if isinstance(item, dict) and isinstance(item.get("task_type"), str):
                    item["task_type"] = html_unescape(item["task_type"].strip())

        sr_matches = re.findall(
            r'<search_replace\s+path="([^"]+)"(?:\s+task_type="([^"]+)")?>\s*<search>(.*?)</search>\s*<replace>(.*?)</replace>\s*</search_replace>',
            response_text,
            re.DOTALL,
        )
        modified_files = []
        for path, task_type, search, replace in sr_matches:
            def unwrap_cdata(value: str) -> str:
                value = value.strip()
                if value.startswith("<![CDATA[") and value.endswith("]]>"):
                    value = value[len("<![CDATA["):-len("]]>")]
                return value.strip()

            search_stripped = unwrap_cdata(search)
            replace_stripped = unwrap_cdata(replace)
            if search_stripped == replace_stripped:
                continue
            item = {"path": path.strip(), "search": search_stripped, "replace": replace_stripped}
            if task_type:
                item["task_type"] = html_unescape(task_type.strip())
            modified_files.append(item)
        checks_match = re.search(r"<browser_checks>(.*?)</browser_checks>", response_text, re.DOTALL)
        browser_checks = json.loads(checks_match.group(1).strip()) if checks_match else []
        return {
            "description": description,
            "modified_files": modified_files,
            "browser_checks": browser_checks,
        }

    def regenerate_browser_checks(
        self,
        code_files: list[dict[str, str]],
        task_types: list[str],
        descriptions: Any,
        project_pages: list[str],
        previous_checks: list[dict[str, Any]],
        failure: str,
    ) -> list[dict[str, Any]]:
        """Repair only failed browser evidence without regenerating valid patches."""
        prompt = f"""The edited project code below is already fixed and MUST NOT be changed.
Regenerate only its hidden browser checks after the previous checks failed.
Output ONLY one <browser_checks> JSON array and nothing else.

Task types: {json.dumps(task_types, ensure_ascii=False)}
Task descriptions: {json.dumps(descriptions, ensure_ascii=False)}
Existing routes: {json.dumps(project_pages, ensure_ascii=False)}
Previous checks: {json.dumps(previous_checks, ensure_ascii=False)}
Observed browser failure: {failure}

Return exactly one check per task type. Use only actions click, hover, focus,
fill, select_option, key_press, drag_and_drop, scroll, or wait_for. Use only
visible, hidden, text, attribute, value, or url assertions. Every selector must
resolve to an element actually rendered by this code and every assertion must
demonstrate the corresponding edited behavior after the actions. Prefer
existing stable IDs or data-testid values and valid rendered data items.
<browser_checks>[{{"task_type":"...","route":"existing route","actions":[{{"action":"click","selector":"#real-trigger"}}],"assertion":{{"type":"visible","selector":"#real-result"}},"capture_delay_ms":150}}]</browser_checks>

{self.format_code_context(code_files)}"""
        response = self._chat_completion([
            {"role": "system", "content": "Output ONLY the browser_checks XML element."},
            {"role": "user", "content": prompt},
        ])
        response_text = (
            response if isinstance(response, str)
            else response.choices[0].message.content
        ) or ""
        match = re.search(r"<browser_checks>(.*?)</browser_checks>", response_text, re.DOTALL)
        if not match:
            raise ValueError("browser-check repair response missing browser_checks")
        checks = validate_browser_checks(
            json.loads(match.group(1).strip()), task_types, project_pages
        )
        validate_stable_browser_selectors(checks, code_files)
        return checks

    def _validate_task_types(self, description: list[dict[str, Any]], expected_task_types: list[str] | None = None) -> None:
        if not expected_task_types:
            return
        actual_task_types = []
        for idx, item in enumerate(description):
            task_type = item.get("task_type")
            if not task_type:
                raise ValueError(f"Missing task_type at index {idx}: {item}")
            actual_task_types.append(task_type)
        if len(actual_task_types) != len(expected_task_types):
            raise ValueError(
                f"Task type count mismatch: got {len(actual_task_types)}, expected {len(expected_task_types)}"
            )
        if Counter(actual_task_types) != Counter(expected_task_types):
            raise ValueError(f"Task types do not match expected list. got={actual_task_types}, expected={expected_task_types}")

    def _validate_task_patch_mapping(
        self,
        description: list[dict[str, Any]],
        patches: list[dict[str, str]],
        expected_task_types: list[str] | None = None,
        *,
        allow_repeated_task_types: bool = False,
    ) -> None:
        """Require every task to own one or more unambiguous patches.

        Earlier data only had a list of task types plus one shared patch list,
        which allowed a nominal multi-task sample to contain patches for a
        single task.  The explicit ``task_type`` on every search/replace block
        makes the relation machine-checkable and available to downstream
        edit/repair constructors.
        """
        self._validate_task_types(description, expected_task_types)
        task_types = [str(item["task_type"]) for item in description]
        if not 1 <= len(task_types) <= 12:
            raise ValueError(f"Expected 1--12 task types, got {task_types}")
        if not allow_repeated_task_types and len(set(task_types)) != len(task_types):
            raise ValueError(f"Task types must be distinct, got {task_types}")
        expected_counts = Counter(task_types)
        if allow_repeated_task_types:
            for task_type, count in expected_counts.items():
                if count <= 1:
                    continue
                details = [
                    str(item.get("description", "")).strip()
                    for item in description
                    if str(item.get("task_type", "")) == task_type
                ]
                if any(not detail for detail in details) or len(set(details)) != count:
                    raise ValueError(
                        f"Repeated task type {task_type!r} must describe {count} distinct issues"
                    )
        mapped = Counter()
        for patch in patches:
            patch_type = str(patch.get("task_type", "")).strip()
            if patch_type not in task_types:
                raise ValueError(f"Patch has unknown/missing task_type: {patch_type!r}")
            mapped[patch_type] += 1
        missing = {
            task_type: count - mapped[task_type]
            for task_type, count in expected_counts.items()
            if mapped[task_type] < count
        }
        if missing:
            raise ValueError(f"Not enough patches assigned to task occurrences: {missing}")
        excessive = {
            task_type: count
            for task_type, count in mapped.items()
            if count > 10 * expected_counts[task_type]
        }
        if excessive:
            raise ValueError(f"Each task may own at most 10 patches: {excessive}")

    def _generate(
        self,
        messages: list[dict[str, Any]],
        max_retries: int = 3,
        backoff_base: int = 2,
    ) -> dict[str, Any]:
        """Call LLM and parse response. No patch application."""
        last_error: Exception | None = None
        attempt_audit: list[dict[str, Any]] = []
        for attempt in range(1, max_retries + 1):
            response_text: str | None = None
            try:
                response = self._chat_completion(messages)
                response_text = (
                    response
                    if isinstance(response, str)
                    else response.choices[0].message.content
                    if response and response.choices
                    else None
                )
                if not response_text:
                    raise ValueError("Empty response content from LLM.")
                print(f"LLM response received (attempt {attempt})")

                parsed = self.parse_llm_response(response_text)
                if not parsed.get("modified_files"):
                    raise ValueError("Parsed LLM response has no modified_files.")

                return {
                    "description": parsed.get("description", []),
                    "modified_files": parsed["modified_files"],
                    "browser_checks": parsed.get("browser_checks", []),
                    "raw_response": response_text,
                    "llm_metadata": {"model": self.model, "attempt": attempt},
                    "llm_attempts": [
                        *attempt_audit,
                        {
                            "attempt": attempt,
                            "status": "ok",
                            "error": "",
                            "raw_response": response_text,
                        },
                    ],
                }
            except Exception as exc:
                last_error = exc
                attempt_audit.append({
                    "attempt": attempt,
                    "status": "timeout" if "timeout" in str(exc).lower() else "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "raw_response": response_text or "",
                })
                print(f"Attempt {attempt}/{max_retries} failed: {exc}")
                if attempt < max_retries:
                    time.sleep(backoff_base**attempt)
        raise ConstructionFailure(
            f"Failed after {max_retries} attempts. Last error: {last_error}",
            attempt_audit,
        ) from last_error


def build_forward_edit_synthesizer(api_key: str, base_url: str | None, model: str, max_retries: int = 1,
                                   max_tokens: int = 8_192):
    from reverse.web_coding_demo.synthetic.official_prompts import edit_prompt
    _, task_descriptions = load_edit_catalog()

    class ForwardEditPairSynthesizer(LocalSearchReplaceSynthesizer):
        def generate_forward_pair(
            self,
            generation_data: dict[str, Any],
            task_types: list[str],
            *,
            require_cross_page: bool = False,
        ) -> dict[str, Any]:
            src_code = generation_data["dst_code"]
            resources = generation_data.get("resources", [])
            src_code_context = generation_data.get("model_context") or self.format_code_context(src_code, resources=resources)
            task_descriptions_str = ""
            for idx, task_type in enumerate(task_types, 1):
                task_descriptions_str += f"Task {idx}: {task_type}\n  Guideline: {task_descriptions[task_type]}\n\n"
            task_types_json = json.dumps(task_types, ensure_ascii=False)
            prompt = edit_prompt(task_descriptions_str, task_types_json, src_code_context, len(task_types))

            source_map = {item["path"]: item["code"] for item in src_code}
            validation_error = ""
            last_error: Exception | None = None
            attempt_audit: list[dict[str, Any]] = []
            for validation_attempt in range(1, self.max_retries + 1):
                result = None
                retry_instruction = ""
                if validation_error:
                    retry_instruction = f"""

VALIDATION FEEDBACK FROM THE PREVIOUS ATTEMPT:
{validation_error}
Regenerate the complete XML response from the original code. Every search is
applied sequentially, so patches must be non-overlapping and each search must
still occur exactly once after all earlier patches. Do not reuse text created
by another patch as a later search target.
"""
                try:
                    result = self._generate(
                        messages=[
                            {
                                "role": "system",
                                "content": "Output ONLY XML. No explanations, no markdown fences, no commentary.",
                            },
                            {"role": "user", "content": prompt + retry_instruction},
                        ],
                        # This outer loop retries both transport/parsing and
                        # strict semantic validation without multiplying two
                        # independent retry budgets.
                        max_retries=1,
                    )
                    snapped_mods = []
                    for mod in result["modified_files"]:
                        snapped = dict(mod)
                        snapped["search"] = _snap_to_source(
                            mod["search"], source_map.get(mod["path"], "")
                        )
                        snapped_mods.append(snapped)
                    validate_patch_paths_for_context(generation_data, snapped_mods)
                    validate_patch_round_trip(src_code, generation_data.get("full_code", src_code), snapped_mods)
                    metadata = dict(result.get("llm_metadata") or {})
                    metadata["validation_attempt"] = validation_attempt
                    return {
                        "task": "edit",
                        "task_type": task_types,
                        "description": result["description"],
                        "resources": generation_data.get("resources", []),
                        "label_modified_files": snapped_mods,
                        "llm_raw_response": result.get("raw_response"),
                        "llm_metadata": metadata,
                        "llm_attempts": [
                            *attempt_audit, *result.get("llm_attempts", [])
                        ],
                        "browser_checks": [],
                        "page_scope": "mp" if require_cross_page else generation_data.get("page_scope", "sp"),
                    }
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    inherited = getattr(exc, "llm_attempts", None)
                    if inherited:
                        attempt_audit.extend(inherited)
                    elif result is not None:
                        attempt_audit.append({
                            "attempt": validation_attempt,
                            "status": "validation_error",
                            "error": f"{type(exc).__name__}: {exc}",
                            "raw_response": result.get("raw_response", ""),
                        })
                    validation_error = f"{type(exc).__name__}: {exc}"
                    print(
                        f"Forward-edit validation attempt "
                        f"{validation_attempt}/{self.max_retries} failed: {validation_error}"
                    )
            raise ConstructionFailure(
                f"forward-edit generation failed after {self.max_retries} "
                f"validated attempts: {last_error}",
                attempt_audit,
            ) from last_error

        def process_single_generation_entry(self, *args, **kwargs) -> list[dict[str, Any]]:
            raise NotImplementedError

    return ForwardEditPairSynthesizer(api_key, base_url, model, max_tokens=max_tokens, max_retries=max_retries)


def build_reverse_edit_synthesizer(api_key: str, base_url: str | None, model: str, max_retries: int = 1,
                                   max_tokens: int = 8_192):
    """Reverse edit: LLM identifies existing features → generates removal patches → we flip them."""

    class ReverseEditPairSynthesizer(LocalSearchReplaceSynthesizer):

        def generate_reverse_pair(self, generation_data: dict[str, Any], n_features: int) -> dict[str, Any]:
            dst_code = generation_data["dst_code"]
            resources = generation_data.get("resources", [])
            code_context = generation_data.get("model_context") or self.format_code_context(dst_code, resources=resources)
            scope_instruction = patch_scope_instruction(generation_data)

            prompt = f"""{scope_instruction}Analyze the webpage code below. Identify exactly {n_features} distinct, self-contained features or components that already exist in the code.

A "feature" is any meaningful piece of functionality, interaction, visual component, or content block, such as:
- Interactive components: navigation menus, modals, carousels, accordions, tab panels, dropdowns, slideshows, hamburger menus, scroll-to-top buttons
- Form features: validation, autocomplete, date pickers, file uploads, multi-step wizards
- Visual effects: animations, transitions, parallax scrolling, particle effects, hover effects, CSS gradients, skeleton loaders
- Layout components: card grids, sidebars, sticky headers, breadcrumbs, footers, hero sections, testimonial sections
- UX features: dark mode, lazy loading, cookie consent banners, toast notifications, search bars, pagination
- Content blocks: team/about sections, pricing tables, FAQ sections, contact forms, image galleries, social media links, statistics counters

For each feature:
1. Assign a concise task_type name (e.g. "Responsive Navigation", "Full-width Image with Side Text", "Stacked Card Grid")
2. Write a detailed STRUCTURAL description — see description rules below
3. Generate search/replace patches that REMOVE the feature from the code while keeping the rest of the page functional

=== Description rules (CRITICAL) ===
Descriptions must focus on LAYOUT STRUCTURE, SPATIAL RELATIONSHIPS, and INTERACTION PATTERNS — not on specific content.

DO describe:
- Layout approach: "a full-width section containing a large image on the left (60% width) with a text block on the right (40% width), vertically centered using flexbox"
- Spatial relationships: "a 3-column card grid with equal-width items, 20px gap, wrapping to single column below 768px"
- Component structure: "a fixed-position top bar containing a logo area on the left and a horizontal link list on the right, collapsing into a hamburger menu on mobile"
- Styling patterns: "rounded corners, drop shadow, gradient background from dark to light, semi-transparent overlay"
- Interaction behavior: "clicking the hamburger icon slides a full-height panel from the left with a fade-in backdrop"
- Responsive changes: "switches from a 3-column grid to a single stacked column below 768px"

DO NOT describe:
- Specific text content: NOT "displays company name 'Acme Corp'" → instead "displays a heading text"
- Specific image subjects: NOT "hero image shows a mountain landscape" → instead "a full-width background image"
- Brand names, people names, product names
- The semantic meaning or purpose of content: NOT "About Us section introducing the team" → instead "a two-column layout with an image on the left and a paragraph block on the right"

Think of yourself as describing a WIREFRAME, not the actual page content.
=== End description rules ===

Important rules for patches:
- Choose features that are independent: removing one must not break other features
- Each feature's patches must completely remove ALL related code (HTML structure, CSS rules, JS logic) for that feature
- Use the exact source text in <search> (including whitespace)
- The <replace> should contain whatever remains after the feature is cleanly removed (could be empty string if the entire block is removed)
- Do NOT pick trivially small features (e.g. a single CSS property). Each feature should involve at least one meaningful HTML section or component.

Output ONLY XML, no explanation:
<description>[{{"task_type": "...", "description": "structural layout description"}}]</description>
Choose exactly {n_features} distinct task types. Each task type must have one
or more patches. Mark EVERY patch with the exact task_type it removes.
<search_replace path="path/to/file" task_type="the feature task_type"><search>exact code with the feature</search><replace>code without the feature</replace></search_replace>

{code_context}"""

            result = self._generate(
                messages=[
                    {
                        "role": "system",
                        "content": "Output ONLY XML. No explanations, no markdown fences, no commentary.",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_retries=self.max_retries,
            )

            # Snap LLM's search text to exact source code (fix whitespace mismatches)
            source_map = {item["path"]: item["code"] for item in dst_code}
            snapped_mods = []
            for mod in result.get("modified_files", []):
                snapped = dict(mod)
                snapped["search"] = _snap_to_source(mod["search"], source_map.get(mod["path"], ""))
                snapped_mods.append(snapped)

            validate_patch_paths_for_context(generation_data, snapped_mods)
            self._validate_task_patch_mapping(result["description"], snapped_mods)
            apply_search_replace_local(dst_code, snapped_mods, strict_mode=True)

            # LLM's search = code WITH feature, replace = code WITHOUT feature (removal direction)
            # Flip to ADD direction: search = without feature, replace = with feature
            label_modified_files = [
                {"path": mod["path"], "task_type": mod["task_type"],
                 "search": mod["replace"], "replace": mod["search"]}
                for mod in snapped_mods
            ]
            task_types = [d.get("task_type", "") for d in result.get("description", [])]

            return {
                "task": "edit",
                "task_type": task_types,
                "description": result["description"],
                "resources": generation_data.get("resources", []),
                "label_modified_files": label_modified_files,
                "llm_raw_response": result.get("raw_response"),
                "llm_metadata": result.get("llm_metadata"),
                "llm_attempts": result.get("llm_attempts", []),
            }

        def process_single_generation_entry(self, *args, **kwargs) -> list[dict[str, Any]]:
            raise NotImplementedError

    return ReverseEditPairSynthesizer(api_key, base_url, model, max_tokens=max_tokens, max_retries=max_retries)


def build_repair_synthesizer(api_key: str, base_url: str | None, model: str, max_retries: int = 1,
                             max_tokens: int = 8_192):
    from reverse.web_coding_demo.synthetic.official_prompts import repair_prompt
    _, defect_descriptions = load_repair_catalog()

    class RepairPairSynthesizer(LocalSearchReplaceSynthesizer):
        def generate_defect_task(
            self,
            generation_data: dict[str, Any],
            defect_types: list[str],
            *,
            require_cross_page: bool = False,
        ) -> dict[str, Any]:
            dst_code = generation_data["dst_code"]
            resources = generation_data.get("resources", [])
            dst_code_context = generation_data.get("model_context") or self.format_code_context(dst_code, resources=resources)
            defect_descriptions_str = ""
            for idx, defect_type in enumerate(defect_types, 1):
                defect_descriptions_str += f"Defect {idx}: {defect_type}\n  Guideline: {defect_descriptions[defect_type]}\n\n"
            defect_types_json = json.dumps(defect_types, ensure_ascii=False)
            prompt = repair_prompt(defect_descriptions_str, defect_types_json, dst_code_context, len(defect_types))
            # Repair search text denotes the clean source.  Preserve the exact
            # source spelling/whitespace before validating or flipping it,
            # just as reverse-edit does for feature-removal patches.
            source_map = {item["path"]: item["code"] for item in dst_code}
            validation_error = ""
            last_error: Exception | None = None
            attempt_audit: list[dict[str, Any]] = []
            result: dict[str, Any] = {}
            snapped_mods: list[dict[str, Any]] = []
            defective_visible: list[dict[str, str]] = []
            defective_full: list[dict[str, str]] = []
            for validation_attempt in range(1, self.max_retries + 1):
                retry_instruction = ""
                if validation_error:
                    retry_instruction = f"""

VALIDATION FEEDBACK FROM THE PREVIOUS ATTEMPT:
{validation_error}
Regenerate the complete XML response from the original clean code. Keep every
search string verbatim and uniquely present in the supplied source.
"""
                try:
                    result = self._generate(
                        messages=[
                            {
                                "role": "system",
                                "content": "Output ONLY XML. No explanations, no markdown fences, no commentary.",
                            },
                            {"role": "user", "content": prompt + retry_instruction},
                        ],
                        max_retries=1,
                    )
                    snapped_mods = []
                    for mod in result.get("modified_files", []):
                        snapped = dict(mod)
                        snapped["search"] = _snap_to_source(
                            mod["search"], source_map.get(mod["path"], "")
                        )
                        snapped_mods.append(snapped)
                    validate_patch_paths_for_context(generation_data, snapped_mods)
                    defective_visible, defective_full = validate_patch_round_trip(
                        dst_code, generation_data.get("full_code", dst_code), snapped_mods
                    )
                    metadata = dict(result.get("llm_metadata") or {})
                    metadata["validation_attempt"] = validation_attempt
                    result["llm_metadata"] = metadata
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    validation_error = f"{type(exc).__name__}: {exc}"
                    attempt_audit.extend(result.get("llm_attempts", []))
                    attempt_audit.append({
                        "attempt": validation_attempt,
                        "status": "validation_error",
                        "error": validation_error,
                        "raw_response": result.get("raw_response", ""),
                    })
                    print(
                        f"Repair validation attempt {validation_attempt}/{self.max_retries} "
                        f"failed: {validation_error}"
                    )
            else:
                raise ConstructionFailure(
                    f"repair validation failed after {self.max_retries} attempts: {last_error}",
                    attempt_audit,
                ) from last_error
            # For repair: LLM's search = clean code, replace = defective code
            # label is the *fix* direction: search = defective, replace = clean
            label_modified_files = [
                {"path": mod["path"],
                 "search": mod["replace"], "replace": mod["search"]}
                for mod in reversed(snapped_mods)
            ]
            return {
                "task": "repair",
                "task_type": defect_types,
                "description": result["description"],
                "resources": generation_data.get("resources", []),
                "label_modified_files": label_modified_files,
                "defective_code": defective_visible,
                "defective_full_code": defective_full,
                "llm_raw_response": result.get("raw_response"),
                "llm_metadata": result.get("llm_metadata"),
                "llm_attempts": [*attempt_audit, *result.get("llm_attempts", [])],
                "browser_checks": result.get("browser_checks", []),
                "page_scope": "mp" if require_cross_page else generation_data.get("page_scope", "sp"),
            }

    return RepairPairSynthesizer(api_key, base_url, model, max_tokens=max_tokens, max_retries=max_retries)
