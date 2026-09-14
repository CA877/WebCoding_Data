from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

CODE_EXTS = {".html", ".htm", ".css", ".js", ".jsx", ".ts", ".tsx", ".json", ".svg"}
RESOURCE_REF_RE = re.compile(r"""(?i)(?:['"(=]\s*)(?:\./)?(resources/[^'")\s<>]+)""")
VENDOR_NAME_RE = re.compile(
    r"(?i)(recaptcha|grecaptcha|captcha|jquery|bootstrap|popper|lodash|moment|"
    r"react|vue|angular|swiper|slick|fontawesome|font-awesome|gtag|"
    r"google-analytics|googletagmanager|analytics|adsbygoogle|doubleclick|"
    r"cloudflare|cdnjs|jsdelivr|unpkg)"
)
MINIFIED_HINT_RE = re.compile(r"(?s)[A-Za-z_$][\w$]*=[^;\n]{400,};|;\s*function\(|!function\(")
TEXT_RESOURCE_EXTS = {".html", ".htm", ".css", ".js", ".jsx", ".ts", ".tsx", ".json", ".svg", ".map", ".txt"}


@dataclass
class ResourceAudit:
    referenced: set[str] = field(default_factory=set)
    orphan_files: list[dict] = field(default_factory=list)
    duplicate_files: list[dict] = field(default_factory=list)
    vendor_or_blob_files: list[dict] = field(default_factory=list)
    author_or_kept_files: list[dict] = field(default_factory=list)
    protected_files: set[str] = field(default_factory=set)
    rewritten_refs: list[dict] = field(default_factory=list)
    deleted_files: list[dict] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)


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


def _normalize_resource_ref(value: str) -> str:
    return value.removeprefix("./").split("#", 1)[0].split("?", 1)[0]


def collect_resource_references(project_dir: Path) -> set[str]:
    refs: set[str] = set()
    for path in code_files(project_dir):
        text = path.read_text("utf-8", errors="ignore")
        for match in RESOURCE_REF_RE.finditer(text):
            refs.add(_normalize_resource_ref(match.group(1)))
        for resource in (project_dir / "resources").glob("*") if (project_dir / "resources").exists() else []:
            if resource.name in text:
                refs.add(f"resources/{resource.name}")
    return refs


def _is_text_resource(path: Path) -> bool:
    return path.suffix.lower() in TEXT_RESOURCE_EXTS


def _text_sample(path: Path, limit: int = 200_000) -> str:
    if not _is_text_resource(path):
        return ""
    try:
        return path.read_text("utf-8", errors="ignore")[:limit]
    except OSError:
        return ""


def classify_resource(path: Path, rel: str, *, referenced: bool, size: int) -> tuple[str, str]:
    """Classify a resource for slimming.

    The policy is intentionally conservative: referenced unknown code is kept.
    Only unreferenced files and exact duplicates are automatically removable.
    """
    suffix = path.suffix.lower()
    name = path.name.lower()
    text = _text_sample(path)
    if not referenced:
        return "orphan", "not referenced by any scanned HTML/CSS/JS"
    if VENDOR_NAME_RE.search(rel) or VENDOR_NAME_RE.search(text[:20_000]):
        return "vendor_or_blob", "referenced third-party/vendor keyword"
    if suffix in {".js", ".css"} and (size > 250_000 or ".min." in name or MINIFIED_HINT_RE.search(text[:80_000])):
        return "vendor_or_blob", "referenced large or minified code blob"
    return "author_or_kept", "referenced page code or asset"


def audit_resources(project_dir: Path, protected_paths: Iterable[str] = ()) -> ResourceAudit:
    resources_dir = project_dir / "resources"
    protected = {_normalize_resource_ref(p) for p in protected_paths}
    audit = ResourceAudit(protected_files=protected)
    if not resources_dir.exists():
        audit.summary = {"total_files": 0, "total_bytes": 0}
        return audit
    audit.referenced = collect_resource_references(project_dir)
    seen_hashes: dict[str, str] = {}
    total_files = 0
    total_bytes = 0
    def resource_priority(path: Path) -> tuple[bool, bool, str]:
        rel = path.relative_to(project_dir).as_posix()
        return (rel not in protected, rel not in audit.referenced, rel)

    for path in sorted((p for p in resources_dir.rglob("*") if p.is_file()), key=resource_priority):
        rel = path.relative_to(project_dir).as_posix()
        size = path.stat().st_size
        total_files += 1
        total_bytes += size
        item = {"path": rel, "size_bytes": size}
        digest = sha1_file(path)
        item["sha1"] = digest
        referenced = rel in audit.referenced
        kind, reason = classify_resource(path, rel, referenced=referenced, size=size)
        item = item | {"kind": kind, "reason": reason, "referenced": referenced, "protected": rel in protected}
        if kind == "orphan" and rel not in protected:
            audit.orphan_files.append(item)
        elif kind == "vendor_or_blob":
            audit.vendor_or_blob_files.append(item)
        else:
            audit.author_or_kept_files.append(item)
        if digest in seen_hashes and rel not in protected:
            audit.duplicate_files.append(item | {"reason": "duplicate", "duplicate_of": seen_hashes[digest]})
        else:
            seen_hashes[digest] = rel
    audit.summary = {
        "total_files": total_files,
        "total_bytes": total_bytes,
        "referenced_files": len(audit.referenced),
        "orphan_files": len(audit.orphan_files),
        "duplicate_files": len(audit.duplicate_files),
        "vendor_or_blob_files": len(audit.vendor_or_blob_files),
        "author_or_kept_files": len(audit.author_or_kept_files),
    }
    return audit


def _replace_resource_refs(project_dir: Path, mapping: dict[str, str]) -> list[dict]:
    rewrites: list[dict] = []
    normalized_mapping = {_normalize_resource_ref(k): v for k, v in mapping.items()}
    for path in code_files(project_dir):
        text = path.read_text("utf-8", errors="ignore")
        new_text = text
        for local_ref, external_url in normalized_mapping.items():
            if local_ref not in text and f"./{local_ref}" not in text:
                continue
            new_text = new_text.replace(f"./{local_ref}", external_url)
            new_text = new_text.replace(local_ref, external_url)
            if new_text != text:
                rewrites.append(
                    {
                        "file": path.relative_to(project_dir).as_posix(),
                        "from": local_ref,
                        "to": external_url,
                    }
                )
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
    return rewrites


def apply_resource_slimming(
    project_dir: Path,
    protected_paths: Iterable[str] = (),
    *,
    dry_run: bool = True,
    externalize_map: dict[str, str] | None = None,
    allow_cdn_externalize: bool = False,
) -> ResourceAudit:
    audit = audit_resources(project_dir, protected_paths)
    delete_candidates = list(audit.orphan_files) + list(audit.duplicate_files)
    if allow_cdn_externalize and externalize_map:
        normalized_map = {_normalize_resource_ref(k): v for k, v in externalize_map.items()}
        mapped_vendor = [
            item
            for item in audit.vendor_or_blob_files
            if item["path"] in normalized_map and item["path"] not in audit.protected_files
        ]
        if not dry_run:
            audit.rewritten_refs = _replace_resource_refs(project_dir, normalized_map)
        delete_candidates.extend(item | {"reason": "externalized_vendor"} for item in mapped_vendor)

    seen_delete_paths: set[str] = set()
    for item in delete_candidates:
        if item["path"] in seen_delete_paths:
            continue
        seen_delete_paths.add(item["path"])
        path = project_dir / item["path"]
        audit.deleted_files.append(item)
        if not dry_run and path.exists():
            path.unlink()
    return audit


def clean_orphan_resources(project_dir: Path, protected_paths: Iterable[str] = (), *, dry_run: bool = True) -> ResourceAudit:
    return apply_resource_slimming(project_dir, protected_paths, dry_run=dry_run)


def audit_to_dict(audit: ResourceAudit) -> dict:
    return {
        "summary": audit.summary,
        "referenced": sorted(audit.referenced),
        "protected_files": sorted(audit.protected_files),
        "orphan_files": audit.orphan_files,
        "duplicate_files": audit.duplicate_files,
        "vendor_or_blob_files": audit.vendor_or_blob_files,
        "author_or_kept_files": audit.author_or_kept_files,
        "rewritten_refs": audit.rewritten_refs,
        "deleted_files": audit.deleted_files,
    }


def load_externalize_map(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("externalize map must be a JSON object: local resource path -> external URL")
    out: dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("externalize map keys and values must be strings")
        out[_normalize_resource_ref(key)] = value
    return out
