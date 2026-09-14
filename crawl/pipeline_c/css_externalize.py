"""Externalize inline author CSS after CSS purge.

Keeping every stylesheet as a file makes the training boundary auditable:
author CSS may enter the prompt, while vendor/framework/bundle CSS can remain
only as a render-time manifest entry.  This runs after purge so no extra
unneeded CSS is created.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from bs4 import BeautifulSoup
import tinycss2
from tinycss2.ast import FunctionBlock, URLToken


def _relative_url(raw: str) -> bool:
    return bool(raw) and not raw.startswith(("http://", "https://", "//", "data:", "blob:", "#", "/"))


def _rewrite_urls_for_new_css_location(css: str, old_base: Path, new_base: Path) -> str:
    """Preserve inline-style URL semantics after moving it to author_styles/.

    Inline style URLs resolve relative to the HTML page.  A raw move would make
    the browser resolve them relative to ``author_styles/`` instead.  Rewrite
    only local relative URLs through tinycss2; keep absolute URLs and data URIs
    untouched.
    """
    rules = tinycss2.parse_stylesheet(css, skip_comments=False, skip_whitespace=False)
    if any(rule.type == "error" for rule in rules):
        raise ValueError("unparseable_css")

    def rewrite(values) -> None:
        for token in values:
            if isinstance(token, URLToken):
                raw = token.value.strip()
                if _relative_url(raw):
                    absolute = (old_base / raw).resolve()
                    relative = Path(os.path.relpath(absolute, new_base)).as_posix()
                    token.value = relative
                    token.representation = f'url("{relative}")'
            elif isinstance(token, FunctionBlock):
                if token.name.lower() == "url":
                    raw = tinycss2.serialize(token.arguments).strip().strip("'\"")
                    if _relative_url(raw):
                        absolute = (old_base / raw).resolve()
                        relative = Path(os.path.relpath(absolute, new_base)).as_posix()
                        token.arguments = tinycss2.parse_component_value_list(f'"{relative}"')
                else:
                    rewrite(token.arguments)
            elif getattr(token, "content", None) is not None:
                rewrite(token.content)

    for rule in rules:
        if getattr(rule, "content", None) is not None:
            rewrite(rule.content)
    try:
        return tinycss2.serialize(rules)
    except (TypeError, ValueError) as exc:
        raise ValueError("unserializable_css") from exc


def externalize_inline_css(project: Path) -> dict[str, int]:
    stats = {"inline_style_blocks_externalized": 0, "inline_style_bytes_externalized": 0,
             "inline_style_blocks_kept_inline_unparseable": 0}
    out_dir = project / "author_styles"
    for html_path in sorted(project.rglob("*.html")):
        soup = BeautifulSoup(html_path.read_text(encoding="utf-8", errors="replace"), "html.parser")
        styles = [tag for tag in soup.find_all("style") if (tag.string or tag.get_text() or "").strip()]
        if not styles:
            continue
        changed = False
        for index, style in enumerate(styles, 1):
            css = style.string or style.get_text()
            digest = hashlib.sha256(f"{html_path.relative_to(project)}:{index}".encode()).hexdigest()[:12]
            target = out_dir / f"{html_path.stem}_{index}_{digest}.css"
            try:
                css = _rewrite_urls_for_new_css_location(css, html_path.parent.resolve(), target.parent.resolve())
            except ValueError:
                # Do not turn a CSS parser limitation into a dataset rejection.
                # The untouched inline block keeps its original URL base and is
                # still counted as author CSS in the training context.
                stats["inline_style_blocks_kept_inline_unparseable"] += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(css, encoding="utf-8")
            link = soup.new_tag("link", rel="stylesheet", href=target.relative_to(html_path.parent).as_posix())
            style.replace_with(link)
            stats["inline_style_blocks_externalized"] += 1
            stats["inline_style_bytes_externalized"] += len(css.encode("utf-8"))
            changed = True
        if changed:
            html_path.write_text(str(soup), encoding="utf-8")
    return stats
