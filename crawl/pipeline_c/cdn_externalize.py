"""Rewrite confidently identified public vendor CSS/JS to versioned CDN URLs."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
import re
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup
import httpx


VERSION = r"(\d+\.\d+\.\d+)"


@dataclass
class CdnStats:
    references_rewritten: int = 0
    jquery_files: int = 0
    bootstrap_files: int = 0
    swiper_files: int = 0


def _cdn_url(path: Path, text: str) -> tuple[str, str] | None:
    suffix = path.suffix.lower()
    name = path.name.lower()
    if suffix == ".js":
        match = re.search(rf"jQuery(?: JavaScript Library)?\s+v?{VERSION}", text[:4096], re.I)
        if match:
            return f"https://cdnjs.cloudflare.com/ajax/libs/jquery/{match.group(1)}/jquery.min.js", "jquery"
    match = re.search(rf"Bootstrap\s+v?{VERSION}", text[:8192], re.I)
    if match and suffix in {".css", ".js"}:
        version = match.group(1)
        if suffix == ".css":
            filename = "bootstrap.min.css"
        else:
            filename = "bootstrap.bundle.min.js" if "bundle" in name or "popper" in text[:16384].lower() else "bootstrap.min.js"
        return f"https://cdnjs.cloudflare.com/ajax/libs/bootstrap/{version}/{filename}", "bootstrap"
    match = re.search(rf"Swiper(?:\.js)?\s+v?{VERSION}", text[:8192], re.I)
    if match and suffix in {".css", ".js"}:
        filename = "swiper-bundle.min.css" if suffix == ".css" else "swiper-bundle.min.js"
        return f"https://cdnjs.cloudflare.com/ajax/libs/Swiper/{match.group(1)}/{filename}", "swiper"
    return None


@lru_cache(maxsize=32)
def _cdn_text(url: str) -> str | None:
    try:
        response = httpx.get(url, follow_redirects=True, timeout=20, verify=False)
        if response.status_code == 200:
            return response.text
    except httpx.HTTPError:
        pass
    return None


def _same_bytes_as_cdn(url: str, local_text: str) -> bool:
    remote = _cdn_text(url)
    if remote is None:
        return False
    normalize = lambda value: value.replace("\r\n", "\n").rstrip()
    return normalize(remote) == normalize(local_text)


def _local_target(html: Path, project: Path, value: str) -> Path | None:
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc or value.startswith("//"):
        return None
    candidate = (project / unquote(parsed.path).lstrip("/")) if parsed.path.startswith("/") else (
        html.parent / unquote(parsed.path))
    try:
        target = candidate.resolve()
        target.relative_to(project.resolve())
    except (ValueError, OSError):
        return None
    return target if target.is_file() else None


def externalize_public_vendors(project: Path) -> dict[str, int]:
    stats = CdnStats()
    cache: dict[Path, tuple[str, str] | None] = {}
    for html in [*project.rglob("*.html"), *project.rglob("*.htm")]:
        soup = BeautifulSoup(html.read_text(encoding="utf-8", errors="replace"), "html.parser")
        changed = False
        nodes = [(node, "src") for node in soup.find_all("script", src=True)]
        nodes += [(node, "href") for node in soup.find_all("link", href=True)
                  if "stylesheet" in [str(x).lower() for x in node.get("rel", [])]]
        for node, attribute in nodes:
            target = _local_target(html, project, str(node[attribute]))
            if target is None or target.suffix.lower() not in {".css", ".js"}:
                continue
            if target not in cache:
                cache[target] = _cdn_url(target, target.read_text(encoding="utf-8", errors="replace"))
            decision = cache[target]
            if decision is None:
                continue
            cdn_url, library = decision
            local_text = target.read_text(encoding="utf-8", errors="replace")
            if not _same_bytes_as_cdn(cdn_url, local_text):
                continue
            node[attribute] = cdn_url
            stats.references_rewritten += 1
            setattr(stats, f"{library}_files", getattr(stats, f"{library}_files") + 1)
            changed = True
        if changed:
            html.write_text(str(soup), encoding="utf-8")
    return asdict(stats)
