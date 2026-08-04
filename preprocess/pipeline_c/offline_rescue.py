#!/usr/bin/env python3
"""Offline rescue for legacy crawled projects.

This never mutates the legacy source tree.  It produces a copied render bundle
and a deliberately small training candidate, with a baseline/final render to
decide whether the latter is safe to keep.  It does not use the old URL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from preprocess.pipeline_c.policy import HtmlAssessment, assess_html, infer_image_dimensions, picsum_url, ui_image_placeholder
from preprocess.pipeline_c.css_externalize import externalize_inline_css
from preprocess.pipeline_c.js_externalize import externalize_inline_js
from preprocess.pipeline_c.cleanup_nonlearning_code import cleanup_project

TRACKER_RE = re.compile(
    r"google-analytics|googletagmanager|doubleclick|facebook\.net|hotjar|mixpanel|segment|"
    r"clarity\.ms|adsbygoogle|optimizely|tiktok.*pixel|cookie(consent)?|typekit\.net", re.I)
CODE_SUFFIXES = {".html", ".htm", ".css", ".js", ".jsx", ".ts", ".tsx"}
LEGACY_PLACEHOLDER_IMAGE_RE = re.compile(r"(?:https?:)?//(?:picsum\.photos|images\.picsum\.photos)/", re.I)
REMOTE_URL_RE = re.compile(r"^(?:https?:)?//", re.I)
FONT_SUFFIX_RE = re.compile(r"\.(?:woff2?|ttf|otf|eot)(?:[?#].*)?$", re.I)
IMAGE_PATH_RE = re.compile(r"\.(?:avif|bmp|gif|ico|jpe?g|png|svg|webp)(?:[?#].*)?$", re.I)

# These are historical, third-party page plumbing rather than author-written
# behaviour.  They are candidates for removal from a *training* bundle only.
# The before/after screenshot gate remains authoritative: classification is not
# a claim that removing a file is visually safe on every site.
REMOVABLE_SCRIPT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("wordpress_emoji", re.compile(r"wp-emoji|wpemoji|print_emoji", re.I)),
    ("jquery_migrate", re.compile(r"jquery[._-]?migrate", re.I)),
    ("cookie_consent", re.compile(r"cookie[-_. ]?(?:consent|banner|notice)|\bconsent\b|\bgdpr\b|onetrust|cookiebot", re.I)),
    ("analytics_tracking", TRACKER_RE),
    ("advertising", re.compile(r"adsbygoogle|googlesyndication|doubleclick|(?:^|[/_.-])ca-pub-", re.I)),
    ("captcha_challenge", re.compile(r"recaptcha|hcaptcha|turnstile|captcha(?:__|[._-])", re.I)),
    ("media_player", re.compile(r"mediaelement|videojs|video-js|soundmanager", re.I)),
    ("legacy_gallery", re.compile(r"(?:^|[-_.])(?:lightbox|fancybox|prettyphoto|flexslider|supersized)(?:[-_.]|$)", re.I)),
)
FRAMEWORK_RUNTIME_RE = re.compile(r"(?:^|[-_.])(?:runtime|webpack|vite|react(?:-dom)?|next|nuxt|astro)(?:[-_.]|$)", re.I)


@dataclass
class RescueStats:
    tracking_nodes_removed: int = 0
    inline_tracker_scripts_removed: int = 0
    orphan_files_removed: int = 0
    categorized_js_files_removed: int = 0
    categorized_js_bytes_removed: int = 0
    categorized_js_by_kind: dict[str, int] | None = None
    framework_runtime_files_kept: int = 0
    legacy_picsum_replaced: int = 0
    missing_relative_images_replaced: int = 0
    missing_relative_images_local_fallback: int = 0
    css_original_bytes: int = 0
    css_purged_bytes: int = 0
    duplicate_code_files_removed: int = 0
    duplicate_code_bytes_removed: int = 0
    dynamic_js_orphan_preserved: int = 0


def _is_local_ref(value: str) -> str | None:
    value = value.strip().split("#", 1)[0].split("?", 1)[0]
    if not value or value.startswith(("http:", "https:", "//", "data:", "blob:", "#", "mailto:", "tel:")):
        return None
    return value.lstrip("/")


def _remove_trackers(project: Path, stats: RescueStats) -> None:
    for path in project.glob("*.html"):
        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
        changed = False
        for tag in list(soup.find_all(["script", "iframe", "noscript"])):
            src, body = tag.get("src", ""), tag.decode_contents()
            if TRACKER_RE.search(src) or TRACKER_RE.search(body):
                tag.decompose(); changed = True; stats.tracking_nodes_removed += 1
                if tag.name == "script" and not src:
                    stats.inline_tracker_scripts_removed += 1
        if changed:
            path.write_text(str(soup), encoding="utf-8")


def _direct_local_refs(project: Path) -> set[str]:
    """Return assets reachable from HTML and the recursive CSS import graph."""
    refs: set[str] = set()
    css_re = re.compile(r"url\(\s*['\"]?([^'\")]+)", re.I)
    import_re = re.compile(r"@import\s+(?:url\()?\s*['\"]?([^'\"\s;)]+)", re.I)
    project_root = project.resolve()
    pending_css: list[Path] = []

    def add(source: Path, raw: str) -> None:
        local = _is_local_ref(raw)
        if not local:
            return
        target = ((project_root / local) if raw.strip().startswith("/") else (source.parent / local)).resolve()
        try:
            rel = target.relative_to(project_root).as_posix()
        except ValueError:
            return
        if rel in refs:
            return
        refs.add(rel)
        if target.suffix.lower() == ".css":
            pending_css.append(target)

    for path in project.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".html", ".htm"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(text, "html.parser")
        for tag in soup.find_all(True):
            for attribute in ("src", "href", "poster", "data-src", "data-lazy-src", "data-original"):
                if tag.get(attribute):
                    add(path, str(tag[attribute]))
            for candidate in str(tag.get("srcset", "")).split(","):
                raw = candidate.strip().split(maxsplit=1)[0] if candidate.strip() else ""
                if raw:
                    add(path, raw)
        for raw in css_re.findall(text):
            add(path, raw.strip())

    visited_css: set[Path] = set()
    while pending_css:
        path = pending_css.pop().resolve()
        if path in visited_css or not path.is_file():
            continue
        visited_css.add(path)
        text = path.read_text(encoding="utf-8", errors="replace")
        for raw in [*css_re.findall(text), *import_re.findall(text)]:
            add(path, raw.strip())
    return refs


def _remove_clear_orphans(project: Path, stats: RescueStats) -> None:
    """Remove unreferenced assets while preserving the reachable JS graph."""
    refs = _direct_local_refs(project)
    project_root = project.resolve()
    quoted_code_ref = re.compile(
        r"['\"]([^'\"\s]{1,512}\.(?:js|jsx|ts|tsx)(?:[?#][^'\"\s]*)?)['\"]", re.I
    )
    dynamic_code_ref = re.compile(
        r"(?:\bimport|\brequire)\s*\(\s*[^'\"\s]|\.src\s*=\s*[^'\"\s]", re.I
    )
    pending = [project / ref for ref in refs if Path(ref).suffix.lower() in {".js", ".jsx", ".ts", ".tsx"}]
    preserve_all_js = False

    def discover(source: Path, text: str) -> None:
        nonlocal preserve_all_js
        if dynamic_code_ref.search(text):
            preserve_all_js = True
        for raw in quoted_code_ref.findall(text):
            local = _is_local_ref(raw)
            if not local:
                continue
            target = (source.parent / local).resolve()
            try:
                rel = target.relative_to(project_root).as_posix()
            except ValueError:
                continue
            if rel not in refs:
                refs.add(rel)
                pending.append(target)

    for html in project.rglob("*.html"):
        soup = BeautifulSoup(html.read_text(encoding="utf-8", errors="replace"), "html.parser")
        for script in soup.find_all("script"):
            if not script.get("src"):
                discover(html.resolve(), script.string or script.get_text())

    visited: set[Path] = set()
    while pending:
        source = pending.pop().resolve()
        if source in visited or not source.is_file():
            continue
        visited.add(source)
        text = source.read_text(encoding="utf-8", errors="replace")
        discover(source, text)
    if preserve_all_js:
        stats.dynamic_js_orphan_preserved = 1
    for path in project.rglob("*"):
        if not path.is_file() or path.name == "index.html":
            continue
        rel = path.relative_to(project).as_posix()
        if (rel in refs or path.suffix.lower() in {".html"} or
                (preserve_all_js and path.suffix.lower() in {".js", ".jsx", ".ts", ".tsx"})):
            continue
        # Never aggressively remove files that might be loaded dynamically.
        if path.suffix.lower() in {".json", ".wasm", ".glb", ".bin"}:
            continue
        path.unlink(); stats.orphan_files_removed += 1


def _classify_script(raw_ref: str, target: Path, text: str) -> str | None:
    """Return a narrowly-defined non-author JS category, or ``None``.

    Never infer ``vendor`` from minification or size: those are useful signals
    for triage, but deleting a bundle based on either silently breaks modern
    sites.  Name/path and a small source prefix are deliberately both used so
    that a custom script merely mentioning a library is not discarded.
    """
    evidence = f"{raw_ref}\n{target.name}\n{text[:4096]}"
    for category, pattern in REMOVABLE_SCRIPT_PATTERNS:
        if pattern.search(evidence):
            return category
    return None


def _strip_categorized_scripts(project: Path, stats: RescueStats) -> list[dict[str, object]]:
    """Remove direct references to explicitly-classified non-author scripts.

    The returned manifest makes every removal reviewable.  Framework runtimes
    are explicitly retained; if they make the answer too large, the project is
    rejected by token/render gates rather than producing a broken answer.
    """
    removed: list[dict[str, object]] = []
    removed_targets: dict[Path, str] = {}
    stats.categorized_js_by_kind = {}
    for html in project.glob("*.html"):
        soup = BeautifulSoup(html.read_text(encoding="utf-8", errors="replace"), "html.parser")
        changed = False
        for script in list(soup.find_all("script", src=True)):
            raw = _is_local_ref(script["src"])
            if not raw:
                continue
            target = (html.parent / raw).resolve()
            if target in removed_targets:
                script.decompose(); changed = True
                continue
            try:
                target.relative_to(project.resolve())
                size = target.stat().st_size
                text = target.read_text(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                continue
            category = _classify_script(raw, target, text)
            if category:
                script.decompose(); changed = True
                target.unlink(missing_ok=True)
                stats.categorized_js_files_removed += 1
                stats.categorized_js_bytes_removed += size
                stats.categorized_js_by_kind[category] = stats.categorized_js_by_kind.get(category, 0) + 1
                removed_targets[target] = category
                removed.append({"html": html.relative_to(project).as_posix(), "path": target.relative_to(project.resolve()).as_posix(),
                                "category": category, "bytes": size})
            elif FRAMEWORK_RUNTIME_RE.search(f"{raw}\n{target.name}"):
                stats.framework_runtime_files_kept += 1
        if changed:
            html.write_text(str(soup), encoding="utf-8")
    return removed


def _code_bytes(project: Path) -> int:
    return sum(path.stat().st_size for path in project.rglob("*") if path.is_file() and path.suffix.lower() in CODE_SUFFIXES)


def deduplicate_code_assets(project: Path) -> dict[str, int]:
    """Deduplicate byte-identical CSS/JS assets and relink their HTML users.

    HTML pages are intentionally never deduplicated: each one is a distinct
    route and training example surface.  Restricting this to exact bytes makes
    the operation semantic-preserving; similar bundles are left untouched.
    """
    groups: dict[tuple[str, str], list[Path]] = {}
    for path in sorted(project.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".css", ".js", ".jsx", ".ts", ".tsx"}:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        groups.setdefault((path.suffix.lower(), digest), []).append(path)

    replacements: dict[Path, Path] = {}
    for paths in groups.values():
        canonical = paths[0].resolve()
        for duplicate in paths[1:]:
            replacements[duplicate.resolve()] = canonical

    references_rewritten = 0
    for html in project.rglob("*.html"):
        soup = BeautifulSoup(html.read_text(encoding="utf-8", errors="replace"), "html.parser")
        changed = False
        for tag, attribute in [(tag, attr) for tag in soup.find_all(True) for attr in ("src", "href") if tag.get(attr)]:
            raw = str(tag[attribute])
            local = _is_local_ref(raw)
            if not local:
                continue
            target = (html.parent / local).resolve()
            canonical = replacements.get(target)
            if canonical is None:
                continue
            suffix = ""
            if "?" in raw:
                suffix = "?" + raw.split("?", 1)[1]
            elif "#" in raw:
                suffix = "#" + raw.split("#", 1)[1]
            tag[attribute] = Path(os.path.relpath(canonical, html.parent.resolve())).as_posix() + suffix
            references_rewritten += 1
            changed = True
        if changed:
            html.write_text(str(soup), encoding="utf-8")

    quoted_ref = re.compile(
        r"(?P<quote>['\"])(?P<path>[^'\"\s]{1,512}\.(?:css|js|jsx|ts|tsx)(?:[?#][^'\"\s]*)?)(?P=quote)",
        re.I,
    )
    for source in project.rglob("*"):
        if not source.is_file() or source.suffix.lower() not in {".css", ".js", ".jsx", ".ts", ".tsx"}:
            continue
        text = source.read_text(encoding="utf-8", errors="replace")

        def replace_quoted(match: re.Match[str]) -> str:
            nonlocal references_rewritten
            raw = match.group("path")
            local = _is_local_ref(raw)
            if not local:
                return match.group(0)
            target = (source.parent / local).resolve()
            canonical = replacements.get(target)
            if canonical is None:
                return match.group(0)
            suffix = ""
            clean = raw
            for marker in ("?", "#"):
                if marker in clean:
                    clean, tail = clean.split(marker, 1)
                    suffix = marker + tail
                    break
            relative = Path(os.path.relpath(canonical, source.parent.resolve())).as_posix()
            if not relative.startswith("."):
                relative = "./" + relative
            references_rewritten += 1
            return f"{match.group('quote')}{relative}{suffix}{match.group('quote')}"

        rewritten = quoted_ref.sub(replace_quoted, text)
        if rewritten != text:
            source.write_text(rewritten, encoding="utf-8")

    removed_bytes = 0
    for duplicate in replacements:
        if duplicate.is_file():
            removed_bytes += duplicate.stat().st_size
            duplicate.unlink()
    return {
        "duplicate_code_files_removed": len(replacements),
        "duplicate_code_bytes_removed": removed_bytes,
        "duplicate_references_rewritten": references_rewritten,
    }


def _replace_legacy_picsum(project: Path, stats: RescueStats) -> None:
    """Preserve pre-existing Picsum URLs.

    The physical-machine proxy can fetch Picsum reliably.  Existing historical
    Picsum URLs are therefore render-valid placeholders and must not be
    rewritten.  The function remains as a named no-op for manifest/API
    compatibility with earlier rescue runs.
    """
    return


def _is_missing_local_image(project: Path, source: Path, raw: str) -> bool:
    """Whether an image-relative URL cannot be satisfied by the copied project."""
    value = raw.strip().strip("'\"").split("#", 1)[0].split("?", 1)[0]
    if not value or value.startswith(("http:", "https:", "//", "data:", "blob:", "#")):
        return False
    candidate = ((project / value.lstrip("/")) if value.startswith("/") else (source.parent / value)).resolve()
    try:
        candidate.relative_to(project.resolve())
    except ValueError:
        return True
    return not candidate.is_file()


def _replace_missing_relative_images(project: Path, stats: RescueStats) -> None:
    """Replace only missing local image assets after copying a legacy project.

    The old crawler frequently left HTML/CSS references such as ``/img/a.jpg``
    without the corresponding asset.  In a local HTTP bundle they become 404s.
    Per the training policy, preserve real local/absolute images; use stable
    Picsum only for these missing relative *image* references.
    """
    for html_path in project.rglob("*.html"):
        soup = BeautifulSoup(html_path.read_text(encoding="utf-8", errors="replace"), "html.parser")
        changed = False
        for tag in soup.find_all(["img", "source", "input"]):
            width, height, _ = infer_image_dimensions(str(tag))
            for attr in ("src", "data-src", "data-lazy-src", "data-original", "poster"):
                raw = tag.get(attr, "")
                if raw and _is_missing_local_image(project, html_path, raw):
                    is_ui = bool(re.search(r"logo|favicon|icon|avatar|badge", raw + " " + (tag.get("alt") or ""), re.I))
                    tag[attr] = ui_image_placeholder(raw, width, height) if is_ui else picsum_url(raw, width, height)
                    stats.missing_relative_images_replaced += 1; changed = True
        def replace_style(match: re.Match[str]) -> str:
            raw = match.group(1).strip(" '\"")
            if not _is_missing_local_image(project, html_path, raw):
                return match.group(0)
            stats.missing_relative_images_replaced += 1
            return f'url("{picsum_url(raw, 1920, 1080)}")'
        for tag in soup.find_all(style=True):
            rewritten = re.sub(r"url\(\s*([^\)]+)\s*\)", replace_style, tag["style"], flags=re.I)
            if rewritten != tag["style"]:
                tag["style"] = rewritten; changed = True
        # Historical pages often put hero/background URLs in a <style> block
        # in index.html rather than a .css file.  Treat it with the same
        # relative-asset rule before that block is externalized later.
        for style_tag in soup.find_all("style"):
            css = style_tag.string or style_tag.get_text()
            rewritten = re.sub(r"url\(\s*([^\)]+)\s*\)", replace_style, css, flags=re.I)
            if rewritten != css:
                style_tag.clear(); style_tag.append(rewritten); changed = True
        if changed:
            html_path.write_text(str(soup), encoding="utf-8")
    for css_path in project.rglob("*.css"):
        text = css_path.read_text(encoding="utf-8", errors="replace")
        def replace_css(match: re.Match[str]) -> str:
            raw = match.group(1).strip(" '\"")
            if not IMAGE_PATH_RE.search(raw) or not _is_missing_local_image(project, css_path, raw):
                return match.group(0)
            stats.missing_relative_images_replaced += 1
            return f'url("{picsum_url(raw, 1920, 1080)}")'
        rewritten = re.sub(r"url\(\s*([^\)]+)\s*\)", replace_css, text, flags=re.I)
        if rewritten != text:
            css_path.write_text(rewritten, encoding="utf-8")


def _external_code_dependencies(project: Path) -> list[str]:
    """Find direct external CSS, JS, and font dependencies in a final answer.

    External content images are governed by the separate image policy.  Code
    and fonts are different: keeping them would make the answer nonportable,
    waste context on URLs, and contradict the training-only output contract.
    """
    dependencies: set[str] = set()
    for html in project.rglob("*.html"):
        try:
            soup = BeautifulSoup(html.read_text(encoding="utf-8", errors="replace"), "html.parser")
        except OSError:
            continue
        for script in soup.find_all("script", src=True):
            if REMOTE_URL_RE.match(script["src"].strip()):
                dependencies.add(script["src"].strip())
        for link in soup.find_all("link", href=True):
            rel = " ".join(link.get("rel") or []).lower()
            href = link["href"].strip()
            if REMOTE_URL_RE.match(href) and ("stylesheet" in rel or FONT_SUFFIX_RE.search(href)):
                dependencies.add(href)
    for css in project.rglob("*.css"):
        try:
            text = css.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for raw in re.findall(r"url\(\s*['\"]?([^'\")\s]+)", text, flags=re.I):
            if REMOTE_URL_RE.match(raw) and FONT_SUFFIX_RE.search(raw):
                dependencies.add(raw)
        for raw in re.findall(r"@import\s+(?:url\()?\s*['\"]?([^'\"\s;)]+)", text, flags=re.I):
            if REMOTE_URL_RE.match(raw):
                dependencies.add(raw)
    return sorted(dependencies)


def _remove_remote_code_dependencies(project: Path, stats: RescueStats) -> list[str]:
    """Remove executable remote dependencies from a frozen training project.

    Pipeline C localizes first-party code while it still has the origin.  A
    legacy project cannot safely do that, so both routes share the same final
    contract: no remote CSS/JS/font code remains.  If removal is essential,
    the later local-render gate rejects the project.
    """
    removed: list[str] = []
    for html in project.rglob("*.html"):
        soup = BeautifulSoup(html.read_text(encoding="utf-8", errors="replace"), "html.parser")
        changed = False
        for tag in list(soup.find_all(["script", "link"])):
            raw = tag.get("src") or tag.get("href") or ""
            if not REMOTE_URL_RE.match(raw.strip()):
                continue
            if tag.name == "link":
                rel = " ".join(tag.get("rel") or []).lower()
                if "stylesheet" not in rel and not FONT_SUFFIX_RE.search(raw):
                    continue
            tag.decompose(); changed = True; removed.append(raw.strip())
        if changed:
            html.write_text(str(soup), encoding="utf-8")
    return removed


def normalize_existing_project(project: Path) -> dict:
    """Shared post-crawl normalizer for Pipeline C and legacy rescue.

    ``project`` is already a local project: Pipeline C has fetched first-party
    relative resources, while legacy rescue has copied its historical bundle.
    From here onward the two routes intentionally use identical cleanup.
    """
    stats = RescueStats()
    _replace_legacy_picsum(project, stats)
    _replace_missing_relative_images(project, stats)
    remote_code_removed: list[str] = []
    _remove_trackers(project, stats)
    before = _code_bytes(project)
    removed_scripts = _strip_categorized_scripts(project, stats)
    _remove_clear_orphans(project, stats)
    # Rule-level CSS elimination cannot be proven safe for arbitrary runtime
    # classes without executing the page.  The production path removes only
    # unreachable files; keep this audit shape for manifest compatibility.
    purge = {"status": "skipped_rule_level_static_unsafe", "project": project.name,
             "reduction_bytes": 0, "reduction_pct": "0.0%", "original_bytes": 0,
             "purged_bytes": 0, "style_blocks_processed": 0, "css_files_processed": 0}
    externalized = externalize_inline_css(project)
    js_externalized = externalize_inline_js(project)
    cleanup = cleanup_project(project)
    deduplication = deduplicate_code_assets(project)
    _remove_clear_orphans(project, stats)
    stats.css_original_bytes, stats.css_purged_bytes = purge.get("original_bytes", 0), purge.get("purged_bytes", 0)
    index = project / "index.html"
    final = assess_html(index.read_text(encoding="utf-8", errors="replace")) if index.is_file() else HtmlAssessment(False, "other", ("missing_index",), 0)
    return {
        "status": "normalized_candidate" if final.passed else "reject",
        "before_code_bytes": before,
        "after_code_bytes": _code_bytes(project),
        "stats": asdict(stats),
        "remote_code_removed": remote_code_removed,
        "removed_scripts": removed_scripts,
        "css_purge": purge,
        "css_externalize": externalized,
        "js_externalize": js_externalized,
        "cleanup": cleanup,
        "deduplication": deduplication,
        "assessment": asdict(final),
    }


def rescue(source: Path, output: Path, max_bundle_bytes: int = 80_000) -> dict:
    source, output = source.resolve(), output.resolve()
    index = source / "index.html"
    if not index.is_file():
        return {"status": "reject", "reason": "missing_index", "source": str(source)}
    initial = assess_html(index.read_text(encoding="utf-8", errors="replace"))
    if not initial.passed:
        return {"status": "reject", "reason": ";".join(initial.reasons), "source": str(source)}
    if output.exists():
        shutil.rmtree(output)
    shutil.copytree(source, output, symlinks=False)
    normalized = normalize_existing_project(output)
    normalized.update({"status": "rescued_candidate" if normalized["status"] == "normalized_candidate" else "reject",
                       "source": str(source), "project": str(output), "language": normalized["assessment"]["language"]})
    return normalized


def main() -> None:
    parser = argparse.ArgumentParser(description="Copy and rescue one legacy project without mutating its source.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    # Kept only for command-line compatibility with the first rescue trial.
    # Size is now triage metadata, never a deletion criterion.
    parser.add_argument("--max-minified-bundle-bytes", type=int, default=80_000)
    args = parser.parse_args()
    print(json.dumps(rescue(args.source, args.output, args.max_minified_bundle_bytes), ensure_ascii=False))


if __name__ == "__main__":
    main()
