from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

CODE_EXTS = {".html", ".htm", ".css", ".js", ".jsx", ".ts", ".tsx", ".json", ".svg"}
RESOURCE_REF_RE = re.compile(r"""(?i)(?:['"(=]\s*)(?:\./)?(resources/[^'")\s<>]+)""")


@dataclass
class ResourceAudit:
    referenced: set[str] = field(default_factory=set)
    orphan_files: list[dict] = field(default_factory=list)
    duplicate_files: list[dict] = field(default_factory=list)
    protected_files: set[str] = field(default_factory=set)


def sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def code_files(project_dir: Path) -> list[Path]:
    return [
        path
        for path in sorted(project_dir.rglob("*"))
        if path.is_file() and path.suffix.lower() in CODE_EXTS and "resources" not in path.relative_to(project_dir).parts[:-1]
    ]


def collect_resource_references(project_dir: Path) -> set[str]:
    refs: set[str] = set()
    for path in code_files(project_dir):
        text = path.read_text("utf-8", errors="ignore")
        for match in RESOURCE_REF_RE.finditer(text):
            refs.add(match.group(1).split("#", 1)[0].split("?", 1)[0])
        for resource in (project_dir / "resources").glob("*") if (project_dir / "resources").exists() else []:
            if resource.name in text:
                refs.add(f"resources/{resource.name}")
    return refs


def audit_resources(project_dir: Path, protected_paths: Iterable[str] = ()) -> ResourceAudit:
    resources_dir = project_dir / "resources"
    protected = {p.removeprefix("./") for p in protected_paths}
    audit = ResourceAudit(protected_files=protected)
    if not resources_dir.exists():
        return audit
    audit.referenced = collect_resource_references(project_dir)
    seen_hashes: dict[str, str] = {}
    for path in sorted(p for p in resources_dir.rglob("*") if p.is_file()):
        rel = path.relative_to(project_dir).as_posix()
        size = path.stat().st_size
        item = {"path": rel, "size_bytes": size}
        digest = sha1_file(path)
        item["sha1"] = digest
        if rel not in audit.referenced and rel not in protected:
            audit.orphan_files.append(item | {"reason": "orphan"})
        if digest in seen_hashes and rel not in protected:
            audit.duplicate_files.append(item | {"reason": "duplicate", "duplicate_of": seen_hashes[digest]})
        else:
            seen_hashes[digest] = rel
    return audit


def clean_orphan_resources(project_dir: Path, protected_paths: Iterable[str] = (), *, dry_run: bool = True) -> ResourceAudit:
    audit = audit_resources(project_dir, protected_paths)
    for item in audit.orphan_files + audit.duplicate_files:
        path = project_dir / item["path"]
        if not dry_run and path.exists():
            path.unlink()
    return audit
