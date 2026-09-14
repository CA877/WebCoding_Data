from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import Any

from .records import input_code_files, output_code_files, patch_array


TRANSFORMS = (
    "exact",
    "html_unescape",
    "strip_cdata",
    "strip_cdata_html_unescape",
    "html_unescape_strip_cdata",
)


@dataclass
class PatchCheck:
    issues: list[str] = field(default_factory=list)
    normalized_patches: list[dict[str, Any]] = field(default_factory=list)
    applied_output_files: list[dict[str, str]] | None = None

    @property
    def ok(self) -> bool:
        return not self.issues


def strip_cdata(value: str) -> str:
    if value.startswith("<![CDATA[") and value.endswith("]]>"):
        return value[9:-3]
    return value


def transform_text(value: str, transform: str) -> str:
    if transform == "exact":
        return value
    if transform == "html_unescape":
        return html.unescape(value)
    if transform == "strip_cdata":
        return strip_cdata(value)
    if transform == "strip_cdata_html_unescape":
        return html.unescape(strip_cdata(value))
    if transform == "html_unescape_strip_cdata":
        return strip_cdata(html.unescape(value))
    raise ValueError(f"unknown transform: {transform}")


def line_col(text: str, offset: int) -> dict[str, int]:
    line = text.count("\n", 0, offset) + 1
    last_newline = text.rfind("\n", 0, offset)
    col = offset + 1 if last_newline < 0 else offset - last_newline
    return {"line": line, "column": col}


def find_unique(code: str, search: str) -> tuple[str | None, str, int | None]:
    for transform in TRANSFORMS:
        candidate = transform_text(search, transform)
        count = code.count(candidate)
        if count == 1:
            return candidate, transform, code.index(candidate)
        if count > 1:
            return None, f"ambiguous:{transform}:{count}", None
    return None, "not_found", None


def validate_and_apply_patches(record: dict[str, Any], *, require_output_files: bool = True) -> PatchCheck:
    patches = patch_array(record)
    before_files = {x["path"]: x["code"] for x in input_code_files(record)}
    after_files = {x["path"]: x["code"] for x in output_code_files(record)}
    issues: list[str] = []
    normalized: list[dict[str, Any]] = []

    if not patches:
        return PatchCheck(["missing_or_empty_patches"])
    if not before_files:
        issues.append("patch_uncheckable_missing_input_files")
    if require_output_files and not after_files:
        issues.append("patch_replace_uncheckable_missing_output_files")

    current_files = dict(before_files)
    for index, patch in enumerate(patches):
        prefix = f"patch_{index}"
        if not isinstance(patch, dict):
            issues.append(f"{prefix}_item_not_dict")
            continue
        path = patch.get("path")
        search = patch.get("search")
        replace = patch.get("replace")
        if not isinstance(path, str) or not isinstance(search, str) or not isinstance(replace, str):
            issues.append(f"{prefix}_bad_field_type")
            continue
        if search == "":
            issues.append("patch_empty_search")
        if replace == "":
            issues.append("patch_empty_replace")
        if search == replace:
            issues.append("patch_noop_search_equals_replace")
        if len(search) < 20:
            issues.append("patch_search_too_short_lt_20")
        if path not in current_files:
            issues.append("patch_path_missing_input")
            continue

        matched, strategy, offset = find_unique(current_files[path], search)
        if matched is None or offset is None:
            if strategy.startswith("ambiguous"):
                issues.append("patch_search_ambiguous")
            else:
                issues.append("patch_search_not_found")
            normalized.append({"path": path, "search": search, "replace": replace, "status": "failed", "match_strategy": strategy})
            continue

        transformed_replace = transform_text(replace, strategy)
        current = current_files[path]
        current_files[path] = current[:offset] + transformed_replace + current[offset + len(matched) :]
        normalized.append(
            {
                "path": path,
                "search": matched,
                "replace": transformed_replace,
                "status": "applied",
                "match_strategy": strategy,
                "location": line_col(current, offset),
            }
        )
        if after_files and path in after_files and transformed_replace not in after_files[path]:
            issues.append("patch_replace_not_in_output")

    applied = [{"path": path, "code": code} for path, code in current_files.items()] if current_files else None
    return PatchCheck(sorted(set(issues)), normalized, applied)
