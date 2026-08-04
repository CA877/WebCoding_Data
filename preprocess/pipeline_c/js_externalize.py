"""Externalize executable inline JavaScript into local relative files."""
from __future__ import annotations

import hashlib
from pathlib import Path

from bs4 import BeautifulSoup


EXECUTABLE_TYPES = {"", "text/javascript", "application/javascript", "module"}


def externalize_inline_js(project: Path) -> dict[str, int]:
    stats = {"inline_scripts_externalized": 0, "inline_script_bytes_externalized": 0}
    for html_path in sorted(project.rglob("*.html")):
        soup = BeautifulSoup(html_path.read_text(encoding="utf-8", errors="replace"), "html.parser")
        changed = False
        for index, script in enumerate(list(soup.find_all("script")), 1):
            if script.get("src"):
                continue
            script_type = str(script.get("type", "")).strip().lower()
            body = script.string or script.get_text()
            if script_type not in EXECUTABLE_TYPES or not body.strip():
                continue
            digest = hashlib.sha256(
                f"{html_path.relative_to(project)}:{index}:{body}".encode("utf-8")
            ).hexdigest()[:12]
            target = html_path.with_name(f"{html_path.stem}_inline_{index}_{digest}.js")
            target.write_text(body, encoding="utf-8")
            script.clear()
            script["src"] = target.name
            stats["inline_scripts_externalized"] += 1
            stats["inline_script_bytes_externalized"] += len(body.encode("utf-8"))
            changed = True
        if changed:
            html_path.write_text(str(soup), encoding="utf-8")
    return stats
