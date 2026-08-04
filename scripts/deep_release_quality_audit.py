#!/usr/bin/env python3
"""Deep static quality audit for the WebCoding six-task release.

This script is read-only. It scans release JSONL files and referenced images,
then writes sample-level issue lists plus aggregate Markdown/JSON reports.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import hashlib
import json
import re
from pathlib import Path
from typing import Any


EXPECTED_TASK_BY_FILE = {
    "text-generate.jsonl": "text-generation",
    "image-generate.jsonl": "image-generation",
    "text-edit.jsonl": "text-editing",
    "image-edit.jsonl": "image-editing",
    "text-repair.jsonl": "text-repair",
    "image-repair.jsonl": "image-repair",
}

IMAGE_ROOT_BY_FILE = {
    "image-generate.jsonl": Path("images/image-generate"),
    "image-edit.jsonl": Path("images/image-edit"),
    "image-repair.jsonl": Path("images/image-repair"),
}

LANG_RE = re.compile(r"""<html[^>]+lang\s*=\s*['"]?([A-Za-z][A-Za-z0-9_-]*)""", re.I)
REMOTE_RE = re.compile(r"""(?i)(https?:)?//[A-Za-z0-9][A-Za-z0-9.-]*(?::\d+)?[^\s"'<>)]*""")
SCRIPT_REMOTE_RE = re.compile(r"""(?is)<script\b[^>]*\bsrc\s*=\s*['"]((?:https?:)?//[^'"]+)""")
STYLE_REMOTE_RE = re.compile(r"""(?is)<link\b[^>]*(?:rel\s*=\s*['"][^'"]*stylesheet[^'"]*['"][^>]*href|href\s*=\s*['"]((?:https?:)?//[^'"]+)[^>]*rel\s*=\s*['"][^'"]*stylesheet)""")
STYLE_HREF_RE = re.compile(r"""(?is)<link\b[^>]*\bhref\s*=\s*['"]((?:https?:)?//[^'"]+)[^>]*>""")
IMG_REMOTE_RE = re.compile(r"""(?is)<(?:img|source)\b[^>]*(?:src|srcset)\s*=\s*['"]((?:https?:)?//[^'"]+)""")
IFRAME_REMOTE_RE = re.compile(r"""(?is)<iframe\b[^>]*\bsrc\s*=\s*['"]((?:https?:)?//[^'"]+)""")
MEDIA_REMOTE_RE = re.compile(r"""(?is)<(?:video|audio|source)\b[^>]*\bsrc\s*=\s*['"]((?:https?:)?//[^'"]+)""")
FONT_REMOTE_RE = re.compile(r"""(?i)(?:fonts\.googleapis|fonts\.gstatic|\.woff2?|\.ttf|\.otf|fontawesome)""")
BAD_PROTOCOL_RE = re.compile(r"""(?i)(href|src)\s*=\s*['"]\s*(javascript:|data:text/html|vbscript:)""")
SRCSET_BAD_RE = re.compile(r"""(?i)(src|srcset)\s*=\s*['"]\s*(?:null|#|/null|about:blank)\s*['"]""")
ONERROR_RE = re.compile(r"""(?i)\son(?:error|load|click|mouseover)\s*=""")
BODY_RE = re.compile(r"""(?is)<body\b[^>]*>(.*?)</body>""")
TAG_RE = re.compile(r"""(?s)<[^>]+>""")
WHITESPACE_RE = re.compile(r"\s+")

CHALLENGE_RE = re.compile(
    r"(?i)(just a moment|checking your browser|verify you are human|are you human|"
    r"access denied|attention required|cloudflare|captcha|security check|enable javascript)"
)
PARKED_RE = re.compile(
    r"(?i)(domain for sale|buy this domain|parked domain|sedo parking|"
    r"this domain is available|under construction|coming soon)"
)
ERROR_PAGE_RE = re.compile(r"(?i)(404 not found|page not found|403 forbidden|500 internal server error|nginx|apache2 ubuntu default page)")
ADULT_PATH_RE = re.compile(
    r"(?i)(^|[^a-z])(adult|porn|porno|xxx|escort|escorts|dating|casino|gambling|"
    r"betting|call-girls|callgirls|webcam|nude|erotic|hookup|bdsm)([^a-z]|$)"
)


def read_jsonl(path: Path):
    with path.open("rb") as handle:
        for line_no, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            try:
                yield line_no, json.loads(raw)
            except Exception as exc:  # noqa: BLE001
                yield line_no, {"__parse_error__": f"{type(exc).__name__}: {exc}"}


def sid(record: dict[str, Any], name: str, line_no: int) -> str:
    value = record.get("instance_id")
    return value if isinstance(value, str) and value else f"{name}:{line_no}"


def file_array(record: dict[str, Any], key: str) -> list[dict[str, str]]:
    out = []
    for item in record.get(key) or []:
        if isinstance(item, dict) and isinstance(item.get("path"), str) and isinstance(item.get("code"), str):
            out.append({"path": item["path"], "code": item["code"]})
    return out


def instruction_code_files(record: dict[str, Any]) -> list[dict[str, str]]:
    instruction = record.get("instruction")
    if isinstance(instruction, dict):
        for key in ("src_code", "input_files", "files"):
            files = instruction.get(key)
            if isinstance(files, list):
                out = []
                for item in files:
                    if isinstance(item, dict) and isinstance(item.get("path"), str) and isinstance(item.get("code"), str):
                        out.append({"path": item["path"], "code": item["code"]})
                if out:
                    return out
    if isinstance(instruction, list):
        out = []
        for item in instruction:
            if isinstance(item, dict) and isinstance(item.get("path"), str) and isinstance(item.get("code"), str):
                out.append({"path": item["path"], "code": item["code"]})
        if out:
            return out
    return []


def input_code_files(record: dict[str, Any]) -> list[dict[str, str]]:
    return file_array(record, "input_files") or instruction_code_files(record)


def response_files(record: dict[str, Any]) -> list[dict[str, str]]:
    response = record.get("response")
    if isinstance(response, list) and all(isinstance(x, dict) for x in response):
        if any("code" in x for x in response):
            return [
                {"path": str(x.get("path", "index.html")), "code": x.get("code", "")}
                for x in response
                if isinstance(x.get("code"), str)
            ]
    return []


def patch_array(record: dict[str, Any]) -> list[dict[str, Any]]:
    patches = record.get("patches")
    if patches is None:
        patches = record.get("response")
    return patches if isinstance(patches, list) else []


def all_code(record: dict[str, Any]) -> str:
    chunks: list[str] = []
    for item in input_code_files(record):
        chunks.append(item["code"])
    for item in file_array(record, "output_files"):
        chunks.append(item["code"])
    for item in response_files(record):
        chunks.append(item["code"])
    return "\n".join(chunks)


def target_code_for_hash(record: dict[str, Any], task_name: str) -> str:
    if "generation" in task_name or "generate" in task_name:
        files = file_array(record, "output_files") or response_files(record)
    else:
        files = input_code_files(record)
    return "\n".join(f["path"] + "\n" + f["code"] for f in files)


def normalized_hash(text: str) -> str:
    norm = WHITESPACE_RE.sub(" ", text).strip()
    return hashlib.sha1(norm.encode("utf-8", "ignore")).hexdigest()


def text_from_html(code: str) -> str:
    body_match = BODY_RE.search(code)
    body = body_match.group(1) if body_match else code
    body = re.sub(r"(?is)<script\b.*?</script>", " ", body)
    body = re.sub(r"(?is)<style\b.*?</style>", " ", body)
    return WHITESPACE_RE.sub(" ", TAG_RE.sub(" ", body)).strip()


def code_quality_issues(code: str) -> list[str]:
    issues: list[str] = []
    if not code:
        return ["empty_code"]
    scan = code[:200_000]
    lowered = scan.lower()
    if len(code) < 500:
        issues.append("code_too_short_lt_500")
    if "<html" not in lowered:
        issues.append("missing_html_tag")
    if "<body" not in lowered:
        issues.append("missing_body_tag")
    if SRCSET_BAD_RE.search(scan):
        issues.append("bad_src_or_srcset_null_hash")
    if BAD_PROTOCOL_RE.search(scan):
        issues.append("dangerous_href_or_src_protocol")
    if ONERROR_RE.search(scan):
        issues.append("inline_event_handler_present")
    text = text_from_html(scan)
    if len(text) < 80:
        issues.append("low_visible_text_lt_80")
    if CHALLENGE_RE.search(text[:5000]):
        issues.append("challenge_or_access_denied_text")
    if PARKED_RE.search(text[:5000]):
        issues.append("parked_or_placeholder_page_text")
    if ERROR_PAGE_RE.search(text[:3000]):
        issues.append("error_or_default_server_page_text")
    if len(TAG_RE.findall(scan)) < 8:
        issues.append("very_few_html_tags")
    return issues


def remote_issues(code: str) -> list[str]:
    issues: list[str] = []
    if REMOTE_RE.search(code):
        issues.append("remote_url_present")
    if SCRIPT_REMOTE_RE.search(code):
        issues.append("remote_script_src")
    if STYLE_REMOTE_RE.search(code) or any(".css" in m.lower() for m in STYLE_HREF_RE.findall(code)):
        issues.append("remote_stylesheet_href")
    if IFRAME_REMOTE_RE.search(code):
        issues.append("remote_iframe_src")
    if MEDIA_REMOTE_RE.search(code):
        issues.append("remote_media_src")
    if IMG_REMOTE_RE.search(code):
        issues.append("remote_image_src_or_srcset")
    if FONT_REMOTE_RE.search(code):
        issues.append("remote_or_web_font_reference")
    if "loremflickr.com" in code.lower():
        issues.append("loremflickr_placeholder_image")
    if "picsum.photos" in code.lower():
        issues.append("picsum_image_residual")
    return issues


def lang_issues(code: str) -> list[str]:
    issues: list[str] = []
    langs = {m.group(1).lower() for m in LANG_RE.finditer(code)}
    non_allowed = [x for x in langs if not (x == "en" or x.startswith("en-") or x == "zh" or x.startswith("zh-"))]
    if langs:
        issues.append("html_lang_attr_present")
    else:
        issues.append("missing_html_lang_attr")
    if non_allowed:
        issues.append("non_zh_en_html_lang_attr")
    return issues


def patch_issues(record: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    patches = patch_array(record)
    if not patches:
        return ["missing_or_empty_patches"]
    before = {x["path"]: x["code"] for x in input_code_files(record)}
    after = {x["path"]: x["code"] for x in file_array(record, "output_files")}
    if not before:
        issues.append("patch_uncheckable_missing_input_files")
    if not after:
        issues.append("patch_replace_uncheckable_missing_output_files")
    for i, patch in enumerate(patches):
        if not isinstance(patch, dict):
            issues.append("patch_item_not_dict")
            continue
        path = patch.get("path")
        search = patch.get("search")
        replace = patch.get("replace")
        if not isinstance(path, str) or not isinstance(search, str) or not isinstance(replace, str):
            issues.append("patch_bad_field_type")
            continue
        if search == "":
            issues.append("patch_empty_search")
        if replace == "":
            issues.append("patch_empty_replace")
        if search == replace:
            issues.append("patch_noop_search_equals_replace")
        if len(search) < 20:
            issues.append("patch_search_too_short_lt_20")
        if before:
            if path not in before:
                issues.append("patch_path_missing_input")
            else:
                count = before[path].count(search)
                if count == 0:
                    issues.append("patch_search_not_found")
                elif count > 1:
                    issues.append("patch_search_ambiguous")
        if after and path in after and isinstance(replace, str) and replace not in after[path]:
            issues.append("patch_replace_not_in_output")
    return issues


def image_paths(record: dict[str, Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for key in ("input_images", "src_screenshot", "dst_screenshot"):
        for value in record.get(key) or []:
            if isinstance(value, str):
                out.append((key, value))
    return out


def image_issue_stats(path: Path) -> list[str]:
    issues: list[str] = []
    if not path.exists():
        return ["image_file_missing"]
    size = path.stat().st_size
    if size == 0:
        return ["image_file_empty"]
    if size < 2048:
        issues.append("image_file_very_small_lt_2kb")
    try:
        from PIL import Image, ImageStat
    except Exception:
        return issues
    try:
        with Image.open(path) as im:
            width, height = im.size
            if width < 200 or height < 150:
                issues.append("image_dimensions_too_small")
            sample = im.convert("L").resize((64, 64))
            stat = ImageStat.Stat(sample)
            mean = stat.mean[0]
            stddev = stat.stddev[0]
            if stddev < 3:
                issues.append("image_nearly_solid_color")
            if mean > 248:
                issues.append("image_nearly_all_white")
            if mean < 7:
                issues.append("image_nearly_all_black")
    except Exception:
        issues.append("image_decode_failed")
    return issues


@dataclass
class FileStats:
    total: int = 0
    issue_counts: Counter[str] = field(default_factory=Counter)
    examples: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))

    def add(self, issues: list[str], sample_id: str) -> None:
        self.total += 1
        for issue in sorted(set(issues)):
            self.issue_counts[issue] += 1
            if len(self.examples[issue]) < 20:
                self.examples[issue].append(sample_id)


def add_issue(issues: list[str], issue: str) -> None:
    issues.append(issue)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--skip-image-open", action="store_true")
    parser.add_argument("--sample-issues-out", default="sample_issues.jsonl")
    args = parser.parse_args()

    jsonl_dir = args.release_root / "jsonl"
    paths = sorted(jsonl_dir.glob("*.jsonl"))
    args.out_dir.mkdir(parents=True, exist_ok=True)

    stats: dict[str, FileStats] = {p.name: FileStats() for p in paths}
    global_ids: dict[str, list[str]] = defaultdict(list)
    hash_to_ids: dict[str, list[str]] = defaultdict(list)
    image_ref_counts: Counter[str] = Counter()
    task_values: dict[str, Counter[str]] = defaultdict(Counter)
    sample_issue_path = args.out_dir / args.sample_issues_out

    with sample_issue_path.open("w", encoding="utf-8") as sample_out:
        for path in paths:
            expected_task = EXPECTED_TASK_BY_FILE.get(path.name)
            image_root = IMAGE_ROOT_BY_FILE.get(path.name)
            for line_no, record in read_jsonl(path):
                sample_id = sid(record, path.name, line_no)
                issues: list[str] = []
                if "__parse_error__" in record:
                    issues.append("json_parse_error")
                    stats[path.name].add(issues, sample_id)
                    sample_out.write(json.dumps({"file": path.name, "line": line_no, "instance_id": sample_id, "issues": issues}, ensure_ascii=False) + "\n")
                    continue

                global_ids[sample_id].append(path.name)
                task_value = record.get("task")
                task_values[path.name][str(task_value)] += 1
                if not isinstance(record.get("instance_id"), str) or not record.get("instance_id"):
                    issues.append("missing_or_empty_instance_id")
                if expected_task and task_value != expected_task:
                    issues.append("task_field_mismatch_or_missing")
                if ADULT_PATH_RE.search(sample_id):
                    issues.append("adult_casino_dating_risky_instance_id")

                code = all_code(record)
                if not code:
                    issues.append("no_embedded_code_found")
                else:
                    issues.extend(code_quality_issues(code))
                    issues.extend(remote_issues(code))
                    issues.extend(lang_issues(code))

                if "edit" in path.name or "repair" in path.name:
                    issues.extend(patch_issues(record))

                if "generate" in path.name:
                    files = file_array(record, "output_files") or response_files(record)
                    if not files:
                        issues.append("generation_missing_output_files_or_response_code")
                    if record.get("patches"):
                        issues.append("generation_unexpected_patches_field")

                if image_root is not None:
                    refs = image_paths(record)
                    if not refs:
                        issues.append("image_task_missing_image_references")
                    seen_refs = set()
                    for key, rel in refs:
                        ref_key = (key, rel)
                        if ref_key in seen_refs:
                            issues.append("duplicate_image_reference_in_sample")
                        seen_refs.add(ref_key)
                        image_ref_counts[f"{path.name}:{rel}"] += 1
                        full = args.release_root / image_root / rel
                        if args.skip_image_open:
                            if not full.exists():
                                issues.append(f"{key}_image_file_missing")
                            elif full.stat().st_size == 0:
                                issues.append(f"{key}_image_file_empty")
                        else:
                            for issue in image_issue_stats(full):
                                issues.append(f"{key}_{issue}")
                    if path.name == "image-repair.jsonl":
                        if not record.get("dst_screenshot"):
                            issues.append("image_repair_missing_dst_screenshot")
                        if record.get("conversion_status") == "partial_success_src_screenshot_only":
                            issues.append("image_repair_partial_success_src_only")

                h_code = target_code_for_hash(record, str(task_value or expected_task or path.name))
                if h_code:
                    hash_to_ids[normalized_hash(h_code)].append(sample_id)

                stats[path.name].add(issues, sample_id)
                if issues:
                    sample_out.write(json.dumps({"file": path.name, "line": line_no, "instance_id": sample_id, "issues": sorted(set(issues))}, ensure_ascii=False) + "\n")

    duplicate_id_groups = {k: v for k, v in global_ids.items() if len(v) > 1}
    duplicate_code_groups = {k: v for k, v in hash_to_ids.items() if len(v) > 1}
    duplicate_image_refs = {k: v for k, v in image_ref_counts.items() if v > 1}

    report = {
        "release_root": str(args.release_root),
        "files": {},
        "task_field_values": {k: dict(v) for k, v in task_values.items()},
        "duplicate_instance_ids": {
            "groups": len(duplicate_id_groups),
            "samples_in_groups": sum(len(v) for v in duplicate_id_groups.values()),
            "examples": dict(list(duplicate_id_groups.items())[:50]),
        },
        "duplicate_target_code_hashes": {
            "groups": len(duplicate_code_groups),
            "samples_in_groups": sum(len(v) for v in duplicate_code_groups.values()),
            "examples": dict(list(duplicate_code_groups.items())[:50]),
        },
        "duplicate_image_references": {
            "groups": len(duplicate_image_refs),
            "references_in_groups": sum(duplicate_image_refs.values()),
            "examples": dict(list(duplicate_image_refs.items())[:50]),
        },
        "sample_issues_jsonl": str(sample_issue_path),
    }
    for name, item in stats.items():
        report["files"][name] = {
            "total": item.total,
            "issue_counts": dict(item.issue_counts.most_common()),
            "examples": dict(item.examples),
        }

    (args.out_dir / "deep_quality_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = ["# Deep Release Quality Audit", ""]
    lines.append(f"Release root: `{args.release_root}`")
    lines.append("")
    lines.append("## Issue Counts")
    for name in sorted(stats):
        item = stats[name]
        lines.extend(["", f"### {name}", "", "| issue | count | ratio | examples |", "|---|---:|---:|---|"])
        for issue, count in item.issue_counts.most_common():
            examples = ", ".join(f"`{x}`" for x in item.examples.get(issue, [])[:6])
            ratio = count / item.total if item.total else 0
            lines.append(f"| `{issue}` | {count} | {ratio:.2%} | {examples} |")
    lines.extend([
        "",
        "## Cross Sample Duplication",
        "",
        f"- duplicate instance_id groups: {len(duplicate_id_groups)}",
        f"- samples in duplicate instance_id groups: {sum(len(v) for v in duplicate_id_groups.values())}",
        f"- duplicate target-code hash groups: {len(duplicate_code_groups)}",
        f"- samples in duplicate target-code groups: {sum(len(v) for v in duplicate_code_groups.values())}",
        f"- duplicate image reference groups: {len(duplicate_image_refs)}",
        "",
        "## Task Field Values",
        "",
    ])
    for name in sorted(task_values):
        values = ", ".join(f"`{k}`={v}" for k, v in task_values[name].most_common())
        lines.append(f"- `{name}`: {values}")
    (args.out_dir / "deep_quality_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"out_dir": str(args.out_dir), "files": len(paths), "sample_issues": str(sample_issue_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
