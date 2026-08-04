"""Conservative cleanup of non-learning code missed by historical rescue."""
from __future__ import annotations

from dataclasses import dataclass, asdict
import re
from pathlib import Path

from bs4 import BeautifulSoup


COOKIE_SIGNATURE_RE = re.compile(
    r"onetrust|optanon|ot-sdk-cookie|cookiebot|CybotCookiebotDialog|"
    r"cookie[-_ ]?(?:consent|banner|notice|policy)|consent[-_ ]?(?:banner|manager)", re.I
)


@dataclass
class CleanupResult:
    cookie_css_files_removed: int = 0
    cookie_css_bytes_removed: int = 0
    cookie_stylesheet_links_removed: int = 0
    cookie_html_nodes_removed: int = 0


def is_dominant_cookie_css(text: str) -> bool:
    """Require strong dominance so mixed author stylesheets are never deleted."""
    if len(text) < 1024 or len(COOKIE_SIGNATURE_RE.findall(text)) < 8:
        return False
    nonempty = [line for line in text.splitlines() if line.strip()]
    if not nonempty:
        return False
    matched_chars = sum(len(line) for line in nonempty if COOKIE_SIGNATURE_RE.search(line))
    return matched_chars / max(sum(map(len, nonempty)), 1) >= 0.80


def cleanup_project(project: Path) -> dict[str, int]:
    result = CleanupResult()
    removed: set[Path] = set()
    for css in project.rglob("*.css"):
        text = css.read_text(encoding="utf-8", errors="replace")
        if is_dominant_cookie_css(text):
            result.cookie_css_files_removed += 1
            result.cookie_css_bytes_removed += css.stat().st_size
            removed.add(css.resolve())
            css.unlink()

    for html in [*project.rglob("*.html"), *project.rglob("*.htm")]:
        soup = BeautifulSoup(html.read_text(encoding="utf-8", errors="replace"), "html.parser")
        changed = False
        for link in list(soup.find_all("link", href=True)):
            href = str(link["href"]).split("?", 1)[0].split("#", 1)[0]
            target = (html.parent / href.lstrip("/")).resolve()
            if target in removed:
                link.decompose(); changed = True
                result.cookie_stylesheet_links_removed += 1
        for node in list(soup.find_all(True)):
            if node.attrs is None:  # descendant of an already decomposed node
                continue
            evidence = " ".join([str(node.get("id", "")), *map(str, node.get("class", []))])
            if evidence and COOKIE_SIGNATURE_RE.search(evidence):
                # A CMS occasionally puts a consent-related class on a root
                # application shell.  Removing it destroys the whole page.
                if node.name in {"html", "head", "body", "main"}:
                    continue
                if node.find(["main", "header", "footer", "article"]):
                    continue
                node.decompose(); changed = True
                result.cookie_html_nodes_removed += 1
        if changed:
            html.write_text(str(soup), encoding="utf-8")
    return asdict(result)


def main() -> None:
    import argparse, json
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, action="append", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    projects = sorted((p for root in args.project_root for p in root.iterdir() if p.is_dir()), key=str)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    totals = CleanupResult()
    with args.manifest.open("w", encoding="utf-8") as out:
        for index, project in enumerate(projects, 1):
            stats = cleanup_project(project)
            for key, value in stats.items():
                setattr(totals, key, getattr(totals, key) + value)
            if any(stats.values()):
                out.write(json.dumps({"project": str(project.resolve()), **stats}, ensure_ascii=False) + "\n")
            if index % 500 == 0:
                print(f"cleaned={index}/{len(projects)} css_removed={totals.cookie_css_files_removed}", flush=True)
    print(json.dumps({"projects": len(projects), **asdict(totals)}))


if __name__ == "__main__":
    main()
