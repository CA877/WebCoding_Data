from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .resources import VENDOR_NAME_RE

CODE_EXTS = {".html", ".htm", ".css", ".js", ".jsx", ".ts", ".tsx", ".json", ".svg"}
RESOURCE_CODE_EXTS = {".js", ".css", ".jsx", ".ts", ".tsx", ".json", ".svg", ".map", ".txt"}
SAFE_MISSING_REF_EXTS = {
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".ico",
    ".avif",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".eot",
}
RESOURCE_REF_RE = re.compile(r"""(?i)(?:['"(=]\s*)(?:\./)?(resources/[^'")\s<>]+)""")


@dataclass
class EmbeddedResourceAudit:
    instance_id: str
    task: str
    code_surface: str
    total_files: int = 0
    total_chars: int = 0
    resource_files: list[dict[str, Any]] = field(default_factory=list)
    referenced_resources: set[str] = field(default_factory=set)
    missing_resource_refs: list[str] = field(default_factory=list)
    orphan_resources: list[dict[str, Any]] = field(default_factory=list)
    duplicate_resources: list[dict[str, Any]] = field(default_factory=list)
    vendor_or_blob_resources: list[dict[str, Any]] = field(default_factory=list)
    author_or_kept_resources: list[dict[str, Any]] = field(default_factory=list)


def normalize_resource_ref(value: str) -> str:
    return value.removeprefix("./").split("#", 1)[0].split("?", 1)[0]


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def suffix_of(path: str) -> str:
    return Path(path).suffix.lower()


def is_code_path(path: str) -> bool:
    return suffix_of(path) in CODE_EXTS


def is_resource_path(path: str) -> bool:
    return normalize_resource_ref(path).startswith("resources/")


def _items_from_list(value: Any) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if not isinstance(value, list):
        return items
    for item in value:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        code = item.get("code")
        if isinstance(path, str) and isinstance(code, str):
            items.append({"path": path, "code": code})
    return items


def get_code_bearing_items(record: dict[str, Any]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    task = str(record.get("task", ""))
    response_items = _items_from_list(record.get("response"))
    if "generation" in task and response_items:
        items.extend(response_items)
    else:
        for key in ("input_files", "output_files", "response"):
            items.extend(_items_from_list(record.get(key)))
    instruction = record.get("instruction")
    if isinstance(instruction, list):
        items.extend(_items_from_list(instruction))
    elif isinstance(instruction, dict):
        items.extend(_items_from_list(instruction.get("src_code")))

    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        key = (item["path"], sha1_text(item["code"]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def get_code_bearing_items_all_surfaces(record: dict[str, Any]) -> list[dict[str, str]]:
    """Return code-bearing items across all fields, without task-specific pruning."""
    items: list[dict[str, str]] = []
    for key in ("response", "output_files", "input_files"):
        value = record.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            code = item.get("code")
            if isinstance(path, str) and isinstance(code, str):
                items.append({"path": path, "code": code})
    instruction = record.get("instruction")
    if isinstance(instruction, list):
        items.extend(_items_from_list(instruction))
    elif isinstance(instruction, dict):
        items.extend(_items_from_list(instruction.get("src_code")))
    return items


def infer_code_surface(items: Iterable[dict[str, str]]) -> str:
    paths = [item["path"] for item in items]
    if not paths:
        return "no_embedded_code"
    resource_count = sum(1 for path in paths if is_resource_path(path))
    html_count = sum(1 for path in paths if suffix_of(path) in {".html", ".htm"})
    if len(paths) == 1 and html_count == 1:
        return "single_html"
    if resource_count:
        return "multi_file_with_resources"
    return "multi_file_no_resources"


def collect_referenced_resources(items: list[dict[str, str]]) -> set[str]:
    refs: set[str] = set()
    resource_names = {
        Path(normalize_resource_ref(item["path"])).name: normalize_resource_ref(item["path"])
        for item in items
        if is_resource_path(item["path"])
    }
    for item in items:
        path = normalize_resource_ref(item["path"])
        if is_resource_path(path):
            continue
        if not is_code_path(path):
            continue
        text = item["code"]
        for match in RESOURCE_REF_RE.finditer(text):
            refs.add(normalize_resource_ref(match.group(1)))
        for name, rel in resource_names.items():
            if name and name in text:
                refs.add(rel)
    return refs


def classify_embedded_resource(path: str, code: str, *, referenced: bool) -> tuple[str, str]:
    rel = normalize_resource_ref(path)
    suffix = suffix_of(rel)
    name = Path(rel).name.lower()
    size = len(code)
    if not referenced:
        return "orphan", "not referenced by embedded HTML/CSS/JS"
    if VENDOR_NAME_RE.search(rel) or VENDOR_NAME_RE.search(code[:20_000]):
        return "vendor_or_blob", "referenced third-party/vendor keyword"
    if suffix in RESOURCE_CODE_EXTS and (size > 250_000 or ".min." in name or _looks_minified(code[:80_000])):
        return "vendor_or_blob", "referenced large or minified code blob"
    return "author_or_kept", "referenced page code or author script"


def _looks_minified(text: str) -> bool:
    if len(text) < 10_000:
        return False
    lines = text.splitlines()[:200]
    if not lines:
        return False
    long_lines = sum(1 for line in lines if len(line) > 500)
    return long_lines >= 3 or max((len(line) for line in lines), default=0) > 5000


def audit_record_resources(record: dict[str, Any]) -> EmbeddedResourceAudit:
    items = get_code_bearing_items(record)
    audit = EmbeddedResourceAudit(
        instance_id=str(record.get("instance_id", "")),
        task=str(record.get("task", "")),
        code_surface=infer_code_surface(items),
        total_files=len(items),
        total_chars=sum(len(item["code"]) for item in items),
    )
    refs = collect_referenced_resources(items)
    audit.referenced_resources = refs
    resource_items = [item for item in items if is_resource_path(item["path"])]
    resource_paths = {normalize_resource_ref(item["path"]) for item in resource_items}
    audit.missing_resource_refs = sorted(ref for ref in refs if ref not in resource_paths)
    seen_hashes: dict[str, str] = {}
    for item in resource_items:
        rel = normalize_resource_ref(item["path"])
        code = item["code"]
        digest = sha1_text(code)
        res = {
            "path": rel,
            "size_chars": len(code),
            "sha1": digest,
            "referenced": rel in refs,
        }
        kind, reason = classify_embedded_resource(rel, code, referenced=rel in refs)
        res.update({"kind": kind, "reason": reason})
        audit.resource_files.append(res)
        if digest in seen_hashes:
            audit.duplicate_resources.append(res | {"reason": "duplicate", "duplicate_of": seen_hashes[digest]})
        else:
            seen_hashes[digest] = rel
        if kind == "orphan":
            audit.orphan_resources.append(res)
        elif kind == "vendor_or_blob":
            audit.vendor_or_blob_resources.append(res)
        else:
            audit.author_or_kept_resources.append(res)
    return audit


def audit_to_summary(audit: EmbeddedResourceAudit) -> dict[str, Any]:
    return {
        "instance_id": audit.instance_id,
        "task": audit.task,
        "code_surface": audit.code_surface,
        "total_files": audit.total_files,
        "total_chars": audit.total_chars,
        "resource_files": len(audit.resource_files),
        "resource_chars": sum(item["size_chars"] for item in audit.resource_files),
        "referenced_resources": len(audit.referenced_resources),
        "missing_resource_refs": len(audit.missing_resource_refs),
        "orphan_resources": len(audit.orphan_resources),
        "orphan_chars": sum(item["size_chars"] for item in audit.orphan_resources),
        "duplicate_resources": len(audit.duplicate_resources),
        "duplicate_chars": sum(item["size_chars"] for item in audit.duplicate_resources),
        "vendor_or_blob_resources": len(audit.vendor_or_blob_resources),
        "vendor_or_blob_chars": sum(item["size_chars"] for item in audit.vendor_or_blob_resources),
        "author_or_kept_resources": len(audit.author_or_kept_resources),
        "author_or_kept_chars": sum(item["size_chars"] for item in audit.author_or_kept_resources),
    }


def audit_to_detail(audit: EmbeddedResourceAudit) -> dict[str, Any]:
    return audit_to_summary(audit) | {
        "missing_resource_refs_list": audit.missing_resource_refs,
        "orphan_resources_list": audit.orphan_resources,
        "duplicate_resources_list": audit.duplicate_resources,
        "vendor_or_blob_resources_list": audit.vendor_or_blob_resources,
        "author_or_kept_resources_list": audit.author_or_kept_resources,
    }


def protected_resource_paths(record: dict[str, Any]) -> set[str]:
    protected: set[str] = set()
    for key in ("response", "patches"):
        value = record.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            if key == "response" and not ("search" in item or "replace" in item):
                continue
            path = item.get("path")
            if isinstance(path, str) and is_resource_path(path):
                protected.add(normalize_resource_ref(path))
    return protected


def _rewrite_resource_refs(text: str, rewrites: dict[str, str]) -> str:
    new_text = text
    for old, new in rewrites.items():
        replacement = new if new.startswith(("http://", "https://", "//")) else f"./{new}"
        new_text = new_text.replace(f"./{old}", replacement)
        new_text = new_text.replace(old, new)
    return new_text


def _remove_tags_for_refs(text: str, refs: set[str]) -> str:
    new_text = text
    for ref in sorted(refs, key=len, reverse=True):
        escaped = re.escape(ref)
        patterns = [
            rf"""(?is)<script\b[^>]*(?:src\s*=\s*["'](?:\./)?{escaped}["'])[^>]*>\s*</script>""",
            rf"""(?is)<script\b[^>]*(?:src\s*=\s*["'](?:\./)?{escaped}["'])[^>]*>.*?</script>""",
            rf"""(?is)<link\b[^>]*(?:href\s*=\s*["'](?:\./)?{escaped}["'])[^>]*>""",
        ]
        for pattern in patterns:
            new_text = re.sub(pattern, "", new_text)
    return new_text


def safe_missing_refs_to_remove(audit: EmbeddedResourceAudit) -> set[str]:
    return {
        ref
        for ref in audit.missing_resource_refs
        if suffix_of(ref) in SAFE_MISSING_REF_EXTS
    }


def _remove_missing_refs(text: str, refs: set[str]) -> tuple[str, list[str]]:
    removed: list[str] = []
    new_text = _remove_tags_for_refs(text, refs)
    for ref in sorted(refs, key=len, reverse=True):
        before = new_text
        new_text = new_text.replace(f"./{ref}", "")
        new_text = new_text.replace(ref, "")
        if new_text != before:
            removed.append(ref)
    return new_text, removed


def _minify_css(css: str) -> str:
    css = re.sub(r"(?s)/\*.*?\*/", "", css)
    css = re.sub(r"\s+", " ", css)
    css = re.sub(r"\s*([{}:;,>+~])\s*", r"\1", css)
    css = css.replace(";}", "}")
    return css.strip()


def _minify_html(html: str) -> str:
    html = re.sub(r"(?s)<!--.*?-->", "", html)
    html = re.sub(
        r"(?is)<style\b([^>]*)>(.*?)</style>",
        lambda m: f"<style{m.group(1)}>{_minify_css(m.group(2))}</style>",
        html,
    )
    html = re.sub(r"(?is)<script\b[^>]*>\s*</script>", "", html)
    html = re.sub(r">\s+<", "><", html)
    html = re.sub(r"\s{2,}", " ", html)
    return html.strip()


def _drop_inline_scripts(html: str) -> str:
    return re.sub(r"(?is)<script\b[^>]*>.*?</script>", "", html)


def _cap_style_blocks(html: str, max_style_chars: int) -> tuple[str, int]:
    if max_style_chars < 0:
        max_style_chars = 0
    kept_total = 0
    removed_total = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal kept_total, removed_total
        attrs = match.group(1)
        css = match.group(2)
        remaining = max_style_chars - kept_total
        if remaining <= 0:
            removed_total += len(css)
            return f"<style{attrs}></style>"
        if len(css) <= remaining:
            kept_total += len(css)
            return match.group(0)
        kept = css[:remaining]
        removed_total += len(css) - len(kept)
        kept_total += len(kept)
        return f"<style{attrs}>{kept}</style>"

    return re.sub(r"(?is)<style\b([^>]*)>(.*?)</style>", repl, html), removed_total


def _optimize_code(path: str, code: str) -> str:
    suffix = suffix_of(path)
    if suffix in {".html", ".htm"}:
        return _minify_html(code)
    if suffix == ".css":
        return _minify_css(code)
    return code


def _training_chars_for_record(record: dict[str, Any]) -> int:
    total = sum(len(item["code"]) for item in get_code_bearing_items(record))
    instruction = record.get("instruction")
    if isinstance(instruction, str):
        total += len(instruction)
    elif isinstance(instruction, dict):
        total += len(json.dumps({k: v for k, v in instruction.items() if k != "src_code"}, ensure_ascii=False))
    elif isinstance(instruction, list):
        non_code = [
            item
            for item in instruction
            if not (isinstance(item, dict) and isinstance(item.get("code"), str))
        ]
        total += len(json.dumps(non_code, ensure_ascii=False))
    response = record.get("response")
    if isinstance(response, list):
        for item in response:
            if isinstance(item, dict) and ("search" in item or "replace" in item):
                total += len(str(item.get("path", "")))
                total += len(str(item.get("search", "")))
                total += len(str(item.get("replace", "")))
    return total


def _map_code_items(record: dict[str, Any], transform) -> dict[str, Any]:
    def map_list(value: Any) -> Any:
        if not isinstance(value, list):
            return value
        out = []
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("path"), str) and isinstance(item.get("code"), str):
                new_item = dict(item)
                new_item["code"] = transform(new_item["path"], new_item["code"])
                out.append(new_item)
            else:
                out.append(item)
        return out

    new_record = dict(record)
    for key in ("response", "output_files", "input_files"):
        if key in new_record:
            new_record[key] = map_list(new_record[key])
    instruction = new_record.get("instruction")
    if isinstance(instruction, list):
        new_record["instruction"] = map_list(instruction)
    elif isinstance(instruction, dict) and isinstance(instruction.get("src_code"), list):
        new_instruction = dict(instruction)
        new_instruction["src_code"] = map_list(instruction["src_code"])
        new_record["instruction"] = new_instruction
    return new_record


def _remove_code_paths(record: dict[str, Any], remove_paths: set[str]) -> dict[str, Any]:
    def filter_list(value: Any) -> Any:
        if not isinstance(value, list):
            return value
        out = []
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("path"), str) and isinstance(item.get("code"), str):
                if normalize_resource_ref(item["path"]) in remove_paths:
                    continue
            out.append(item)
        return out

    new_record = dict(record)
    for key in ("response", "output_files", "input_files"):
        if key in new_record:
            new_record[key] = filter_list(new_record[key])
    instruction = new_record.get("instruction")
    if isinstance(instruction, list):
        new_record["instruction"] = filter_list(instruction)
    elif isinstance(instruction, dict) and isinstance(instruction.get("src_code"), list):
        new_instruction = dict(instruction)
        new_instruction["src_code"] = filter_list(instruction["src_code"])
        new_record["instruction"] = new_instruction
    return new_record


def _truncate_html_to_budget(record: dict[str, Any], max_training_chars: int) -> tuple[dict[str, Any], int]:
    current = _training_chars_for_record(record)
    if current <= max_training_chars:
        return record, 0
    overflow = current - max_training_chars
    removed = 0

    def truncate(path: str, code: str) -> str:
        nonlocal overflow, removed
        if overflow <= 0 or suffix_of(path) not in {".html", ".htm"}:
            return code
        keep = max(0, len(code) - overflow)
        updated = code[:keep]
        removed += len(code) - len(updated)
        overflow -= len(code) - len(updated)
        return updated

    return _map_code_items(record, truncate), removed


def enforce_training_char_budget(record: dict[str, Any], max_training_chars: int) -> tuple[dict[str, Any], dict[str, Any]]:
    if max_training_chars <= 0:
        return record, {"budget_enforced": False}
    before = _training_chars_for_record(record)
    if before <= max_training_chars:
        return record, {"budget_enforced": False, "before_training_chars": before, "after_training_chars": before}

    new_record = record
    removed_inline_script_chars = 0
    removed_style_chars = 0
    removed_non_html_code_chars = 0
    truncated_html_chars = 0

    def drop_scripts(path: str, code: str) -> str:
        nonlocal removed_inline_script_chars
        if suffix_of(path) not in {".html", ".htm"}:
            return code
        updated = _drop_inline_scripts(code)
        removed_inline_script_chars += len(code) - len(updated)
        return updated

    new_record = _map_code_items(new_record, drop_scripts)
    after_scripts = _training_chars_for_record(new_record)

    if after_scripts > max_training_chars:
        overflow = after_scripts - max_training_chars
        style_total = 0
        for item in get_code_bearing_items(new_record):
            if suffix_of(item["path"]) in {".html", ".htm"}:
                style_total += sum(len(match) for match in re.findall(r"(?is)<style\b[^>]*>(.*?)</style>", item["code"]))
        target_style_total = max(0, style_total - overflow - 2_000)

        def cap_styles(path: str, code: str) -> str:
            nonlocal removed_style_chars, target_style_total
            if suffix_of(path) not in {".html", ".htm"}:
                return code
            updated, removed = _cap_style_blocks(code, target_style_total)
            removed_style_chars += removed
            target_style_total = max(0, target_style_total - (len(code) - len(updated) - removed))
            return updated

        new_record = _map_code_items(new_record, cap_styles)

    after_styles = _training_chars_for_record(new_record)
    if after_styles > max_training_chars:
        remove_paths = {
            normalize_resource_ref(item["path"])
            for item in get_code_bearing_items(new_record)
            if suffix_of(item["path"]) not in {".html", ".htm"}
        }
        removed_non_html_code_chars = sum(
            len(item["code"])
            for item in get_code_bearing_items(new_record)
            if normalize_resource_ref(item["path"]) in remove_paths
        )

        def remove_remaining_refs(path: str, code: str) -> str:
            if suffix_of(path) not in {".html", ".htm"}:
                return code
            return _remove_tags_for_refs(code, remove_paths)

        new_record = _map_code_items(new_record, remove_remaining_refs)
        new_record = _remove_code_paths(new_record, remove_paths)

    after_non_html = _training_chars_for_record(new_record)
    if after_non_html > max_training_chars:
        def remove_all_styles(path: str, code: str) -> str:
            nonlocal removed_style_chars
            if suffix_of(path) not in {".html", ".htm"}:
                return code
            updated, removed = _cap_style_blocks(code, 0)
            removed_style_chars += removed
            return updated

        new_record = _map_code_items(new_record, remove_all_styles)

    new_record, truncated_html_chars = _truncate_html_to_budget(new_record, max_training_chars)
    after = _training_chars_for_record(new_record)
    meta = new_record.get("metadata") if isinstance(new_record.get("metadata"), dict) else {}
    meta = dict(meta)
    meta["training_char_budget"] = max_training_chars
    meta["budget_enforced"] = True
    meta["budget_satisfied"] = after <= max_training_chars
    new_record["metadata"] = meta
    return new_record, {
        "budget_enforced": True,
        "budget_satisfied": after <= max_training_chars,
        "before_training_chars": before,
        "after_training_chars": after,
        "removed_inline_script_chars": removed_inline_script_chars,
        "removed_style_chars": removed_style_chars,
        "removed_non_html_code_chars": removed_non_html_code_chars,
        "truncated_html_chars": truncated_html_chars,
    }


def remove_current_orphan_resources(record: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    audit = audit_record_resources(record)
    orphan_paths = {item["path"] for item in audit.orphan_resources}
    if not orphan_paths:
        return record, []
    removed = [
        {"path": item["path"], "size_chars": item["size_chars"]}
        for item in audit.orphan_resources
    ]
    return _remove_code_paths(record, orphan_paths), removed


def _slim_item_list(
    value: Any,
    delete_paths: set[str],
    rewrites: dict[str, str],
    missing_refs_to_remove: set[str],
    optimize_code: bool,
) -> tuple[Any, list[dict[str, Any]]]:
    if not isinstance(value, list):
        return value, []
    out: list[Any] = []
    deleted: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            out.append(item)
            continue
        path = item.get("path")
        code = item.get("code")
        if isinstance(path, str) and isinstance(code, str):
            rel = normalize_resource_ref(path)
            if rel in delete_paths:
                deleted.append({"path": rel, "size_chars": len(code)})
                continue
            new_item = dict(item)
            new_item["code"] = _rewrite_resource_refs(code, rewrites)
            new_item["code"], _ = _remove_missing_refs(new_item["code"], missing_refs_to_remove)
            new_item["code"] = _remove_tags_for_refs(new_item["code"], delete_paths)
            if optimize_code:
                new_item["code"] = _optimize_code(rel, new_item["code"])
            out.append(new_item)
        else:
            out.append(item)
    return out, deleted


def slim_record_resources(
    record: dict[str, Any],
    *,
    drop_vendor_blobs: bool = False,
    optimize_code: bool = False,
    max_training_chars: int = 0,
    externalize_map: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if max_training_chars:
        raise ValueError(
            "Hard truncation/capping is not allowed for formal training samples; "
            "run length checks and filter over-budget samples instead."
        )
    externalize_map = {
        normalize_resource_ref(key): value
        for key, value in (externalize_map or {}).items()
    }
    audit = audit_record_resources(record)
    protected = protected_resource_paths(record)
    duplicate_rewrites = {
        item["path"]: item["duplicate_of"]
        for item in audit.duplicate_resources
        if item["path"] not in protected and item.get("duplicate_of") and item.get("referenced")
    }
    duplicate_keep_paths = set(duplicate_rewrites.values())
    duplicate_delete_paths = {
        item["path"]
        for item in audit.duplicate_resources
        if item["path"] not in protected
    }
    vendor_delete_paths = {
        item["path"]
        for item in audit.vendor_or_blob_resources
        if (drop_vendor_blobs or item["path"] in externalize_map) and item["path"] not in protected
    }
    externalize_rewrites = {
        path: externalize_map[path]
        for path in vendor_delete_paths
        if path in externalize_map
    }
    missing_refs_to_remove = safe_missing_refs_to_remove(audit)
    delete_paths = {
        item["path"]
        for item in audit.orphan_resources
        if item["path"] not in protected and item["path"] not in duplicate_keep_paths
    } | duplicate_delete_paths | vendor_delete_paths

    new_record = dict(record)
    deleted_items: list[dict[str, Any]] = []
    for key in ("response", "output_files", "input_files"):
        new_value, deleted = _slim_item_list(
            record.get(key),
            delete_paths,
            duplicate_rewrites | externalize_rewrites,
            missing_refs_to_remove,
            optimize_code,
        )
        if key in record:
            new_record[key] = new_value
        deleted_items.extend({"field": key, **item} for item in deleted)

    instruction = record.get("instruction")
    if isinstance(instruction, list):
        new_value, deleted = _slim_item_list(
            instruction,
            delete_paths,
            duplicate_rewrites | externalize_rewrites,
            missing_refs_to_remove,
            optimize_code,
        )
        new_record["instruction"] = new_value
        deleted_items.extend({"field": "instruction", **item} for item in deleted)
    elif isinstance(instruction, dict) and isinstance(instruction.get("src_code"), list):
        new_instruction = dict(instruction)
        new_value, deleted = _slim_item_list(
            instruction.get("src_code"),
            delete_paths,
            duplicate_rewrites | externalize_rewrites,
            missing_refs_to_remove,
            optimize_code,
        )
        new_instruction["src_code"] = new_value
        new_record["instruction"] = new_instruction
        deleted_items.extend({"field": "instruction.src_code", **item} for item in deleted)

    manifest = new_record.get("file_manifest")
    if isinstance(manifest, list):
        new_record["file_manifest"] = [
            item
            for item in manifest
            if not (
                isinstance(item, dict)
                and isinstance(item.get("path"), str)
                and normalize_resource_ref(item["path"]) in delete_paths
            )
        ]

    meta = new_record.get("metadata") if isinstance(new_record.get("metadata"), dict) else {}
    meta = dict(meta)
    meta["code_surface"] = infer_code_surface(get_code_bearing_items(new_record))
    meta["resource_slimming_policy"] = "keep_html_inline_css_author_js_delete_orphan_duplicate_externalize_confirmed_vendor"
    if drop_vendor_blobs:
        meta["resource_slimming_policy"] += "_drop_vendor_blobs"
    if externalize_rewrites:
        meta["externalized_vendor_resources"] = len(externalize_rewrites)
    if optimize_code:
        meta["code_optimized_for_training_budget"] = True
    new_record["metadata"] = meta
    new_record, post_budget_orphans = remove_current_orphan_resources(new_record)
    change = {
        "instance_id": audit.instance_id,
        "task": audit.task,
        "protected_resource_paths": sorted(protected),
        "deleted_items": deleted_items,
        "duplicate_rewrites": duplicate_rewrites,
        "externalized_vendor_rewrites": externalize_rewrites,
        "dropped_vendor_blob_paths": sorted(vendor_delete_paths),
        "removed_missing_asset_refs": sorted(missing_refs_to_remove),
        "budget_change": {"budget_enforced": False},
        "post_budget_orphans_removed": post_budget_orphans,
        "before": audit_to_summary(audit),
        "after": audit_to_summary(audit_record_resources(new_record)),
    }
    return new_record, change


def load_jsonl(path: Path, limit: int = 0):
    with path.open(encoding="utf-8", errors="ignore") as handle:
        for index, line in enumerate(handle, start=1):
            if limit and index > limit:
                break
            if line.strip():
                yield index, json.loads(line)
