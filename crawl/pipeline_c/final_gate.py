"""Strict final contract for freshly crawled training projects.

The crawler may use the network while freezing a site.  A project accepted by
this gate is different: it is a small, self-contained source project that does
not need the origin, a CDN, or a build/runtime bundle to render.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup

from .qwen_token_gate import TRAIN_CODE_SUFFIXES, is_render_bundle, project_context_stats


REMOTE_URL_RE = re.compile(r"^(?:https?:)?//", re.I)
CSS_REMOTE_RE = re.compile(
    r"(?:url\(|@import\s+(?:url\()?\s*)['\"]?((?:https?:)?//[^'\"\s)]+)", re.I
)
JS_REMOTE_RE = re.compile(
    r"(?:\bfetch\s*\(|\bimport\s*\(|\b(?:new\s+)?(?:WebSocket|EventSource)\s*\(|"
    r"\.open\s*\(\s*['\"](?:GET|POST|PUT|PATCH|DELETE)['\"]\s*,|"
    r"\b(?:import|export)\s+[^;\n]*?\bfrom\s*)\s*['\"]((?:https?:)?//[^'\"]+)",
    re.I,
)
SOURCE_MAP_RE = re.compile(r"(?:sourceMappingURL=|\.map(?:[?#]|$))", re.I)
LOCAL_CODE_EXTENSIONS = {".css", ".js", ".mjs", ".jsx", ".ts", ".tsx"}
MEDIA_HTML_ATTRIBUTES = ("src", "srcset", "poster", "data-src", "data-lazy-src", "data-original")


@dataclass
class FinalContractAudit:
    status: str
    reasons: list[str] = field(default_factory=list)
    external_references: list[dict[str, str]] = field(default_factory=list)
    bundle_files: list[str] = field(default_factory=list)
    source_map_files: list[str] = field(default_factory=list)
    orphan_code_files: list[str] = field(default_factory=list)
    duplicate_code_files: list[list[str]] = field(default_factory=list)
    code_tokens: int = 0
    code_token_limit: int = 40_000
    code_files: int = 0
    html_files: int = 0
    page_mode: str = "single"

    def to_dict(self) -> dict:
        return asdict(self)


def _clean_reference(raw: str) -> str:
    return unquote(raw.strip()).split("#", 1)[0].split("?", 1)[0]


def _local_target(project: Path, source: Path, raw: str) -> Path | None:
    value = _clean_reference(raw)
    if not value or value.startswith(("data:", "blob:", "#", "mailto:", "tel:", "javascript:")):
        return None
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc or value.startswith("//"):
        return None
    target = (project / value.lstrip("/")) if value.startswith("/") else (source.parent / value)
    try:
        resolved = target.resolve()
        resolved.relative_to(project.resolve())
    except (OSError, ValueError):
        return None
    return resolved


def _html_external_references(path: Path) -> list[dict[str, str]]:
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    found: list[dict[str, str]] = []
    for tag in soup.find_all(True):
        attributes: tuple[str, ...] = ()
        if tag.name == "script":
            attributes = ("src",)
        elif tag.name == "link":
            rel = {str(item).lower() for item in tag.get("rel", [])}
            if rel.intersection({"stylesheet", "icon", "apple-touch-icon", "mask-icon", "preload", "modulepreload", "manifest"}):
                attributes = ("href",)
        elif tag.name in {"img", "source", "input", "video", "audio"}:
            attributes = MEDIA_HTML_ATTRIBUTES
        elif tag.name in {"iframe", "embed"}:
            attributes = ("src",)
        elif tag.name in {"image", "use"}:
            attributes = ("href", "xlink:href")
        for attribute in attributes:
            raw = str(tag.get(attribute, "")).strip()
            if not raw:
                continue
            candidates = [item.strip().split(maxsplit=1)[0] for item in raw.split(",")] if attribute == "srcset" else [raw]
            for candidate in candidates:
                if REMOTE_URL_RE.match(candidate):
                    found.append({"file": str(path), "kind": f"html:{tag.name}[{attribute}]", "url": candidate})
        if tag.name == "script" and not tag.get("src"):
            for match in JS_REMOTE_RE.finditer(tag.string or ""):
                found.append({"file": str(path), "kind": "html:inline-script-network", "url": match.group(1)})
    return found


def _code_external_references(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    pattern = CSS_REMOTE_RE if path.suffix.lower() == ".css" else JS_REMOTE_RE
    return [{"file": str(path), "kind": path.suffix.lower().lstrip(".") + ":network", "url": match.group(1)}
            for match in pattern.finditer(text)]


def _direct_code_references(project: Path) -> tuple[set[Path], bool]:
    """Trace the statically resolvable HTML/CSS/JS code graph.

    Dynamic imports are not guessed.  Their presence makes the project
    ineligible for the strict no-redundancy contract because reachability cannot
    be audited without retaining an opaque runtime graph.
    """
    reachable: set[Path] = set()
    pending: list[Path] = []
    dynamic_graph = False

    def add(source: Path, raw: str) -> None:
        target = _local_target(project, source, raw)
        if target is None or not target.is_file() or target.suffix.lower() not in LOCAL_CODE_EXTENSIONS:
            return
        if target not in reachable:
            reachable.add(target)
            pending.append(target)

    for html in [*project.rglob("*.html"), *project.rglob("*.htm")]:
        soup = BeautifulSoup(html.read_text(encoding="utf-8", errors="replace"), "html.parser")
        for script in soup.find_all("script", src=True):
            add(html, str(script["src"]))
        for link in soup.find_all("link", href=True):
            if "stylesheet" in [str(item).lower() for item in link.get("rel", [])]:
                add(html, str(link["href"]))

    quoted_import = re.compile(
        r"(?:@import\s+(?:url\()?\s*|(?:import|export)\s+(?:[^'\"]*?\s+from\s+)?|import\s*\()"
        r"['\"]([^'\"]+)['\"]", re.I
    )
    dynamic_import = re.compile(r"\bimport\s*\(\s*[^'\"\s]", re.I)
    while pending:
        source = pending.pop()
        text = source.read_text(encoding="utf-8", errors="replace")
        dynamic_graph = dynamic_graph or bool(dynamic_import.search(text))
        for raw in quoted_import.findall(text):
            add(source, raw)
    return reachable, dynamic_graph


def audit_project_structure(project: Path) -> FinalContractAudit:
    project = project.resolve()
    code_files = sorted(
        path for path in project.rglob("*")
        if path.is_file() and path.suffix.lower() in TRAIN_CODE_SUFFIXES
    )
    html_files = [path for path in code_files if path.suffix.lower() in {".html", ".htm"}]
    audit = FinalContractAudit(
        status="pass",
        code_files=len(code_files),
        html_files=len(html_files),
        page_mode="multi" if len(html_files) > 1 else "single",
    )
    for html in html_files:
        audit.external_references.extend(_html_external_references(html))
    for path in code_files:
        if path.suffix.lower() in LOCAL_CODE_EXTENSIONS:
            audit.external_references.extend(_code_external_references(path))
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix.lower() in LOCAL_CODE_EXTENSIONS and is_render_bundle(project, path, text):
            audit.bundle_files.append(path.relative_to(project).as_posix())
        if path.suffix.lower() == ".map" or SOURCE_MAP_RE.search(text):
            audit.source_map_files.append(path.relative_to(project).as_posix())

    reachable, dynamic_graph = _direct_code_references(project)
    for path in code_files:
        if path.suffix.lower() in LOCAL_CODE_EXTENSIONS and path.resolve() not in reachable:
            audit.orphan_code_files.append(path.relative_to(project).as_posix())

    duplicate_groups: dict[tuple[str, str], list[Path]] = {}
    for path in code_files:
        if path.suffix.lower() not in LOCAL_CODE_EXTENSIONS:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        duplicate_groups.setdefault((path.suffix.lower(), digest), []).append(path)
    audit.duplicate_code_files = [
        [path.relative_to(project).as_posix() for path in paths]
        for paths in duplicate_groups.values() if len(paths) > 1
    ]

    if not (project / "index.html").is_file():
        audit.reasons.append("missing_index")
    if audit.external_references:
        audit.reasons.append("external_references_present")
    # Bundles, duplicate code and dynamically loaded chunks still belong to the
    # model input and 40K accounting.  They are recorded for analysis but are
    # not rejection reasons; strict offline browser replay proves runtime use.
    audit.status = "reject" if audit.reasons else "pass"
    return audit


def audit_final_project(project: Path, tokenizer_json: Path, max_code_tokens: int = 40_000) -> dict:
    audit = audit_project_structure(project)
    stats = project_context_stats(project, tokenizer_json, exclude_render_bundles=False)
    audit.code_tokens = stats["code_tokens"]
    audit.code_token_limit = max_code_tokens
    if audit.code_tokens > max_code_tokens:
        audit.reasons.append(f"code_tokens_over_limit:{audit.code_tokens}>{max_code_tokens}")
    audit.status = "reject" if audit.reasons else "pass"
    result = audit.to_dict()
    result["token_usage"] = {**stats, "code_token_limit": max_code_tokens}
    return result
